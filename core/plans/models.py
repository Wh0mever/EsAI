from django.conf import settings
from django.db import models
from django.db.models import Q
from django.core.exceptions import ValidationError
from datetime import timedelta


class Currency(models.TextChoices):
    RUB = "RUB", "Российский рубль"
    KGS = "KGS", "Кыргызский сом"


class BillingPeriod(models.TextChoices):
    WEEKLY = "weekly", "Неделя"
    MONTHLY = "monthly", "Месяц"
    YEARLY  = "yearly", "Год"


def _plan_cycle_days(period: str | None) -> int:
    p = (period or "").strip().lower()
    if p == BillingPeriod.WEEKLY:
        return 7
    if p == BillingPeriod.YEARLY:
        return 365
    return 30
    

class CurrencyRate(models.Model):
    # rate_to_usd: сколько 1 единица выбранной валюты стоит в USD
    currency = models.CharField(max_length=3, choices=Currency.choices, unique=True)
    rate_to_usd = models.DecimalField(max_digits=18, decimal_places=8)
    fetched_at = models.DateTimeField(auto_now=True)
    source = models.URLField(blank=True, default="")

    class Meta:
        db_table = "currency_rate"
        verbose_name = "Курс валюты"
        verbose_name_plural = "Курсы валют"

    def __str__(self):
        return f"{self.currency}={self.rate_to_usd} USD"


class GenerationUnitPrice(models.Model):
    """Singleton config for one-off generation unit prices."""
    music_price = models.DecimalField(max_digits=12, decimal_places=2, default=0, verbose_name="Цена за музыку (USD)")
    image_price = models.DecimalField(max_digits=12, decimal_places=2, default=0, verbose_name="Цена за изображение (USD)")
    text_price = models.DecimalField(max_digits=12, decimal_places=2, default=0, verbose_name="Цена за текст (USD)")

    class Meta:
        verbose_name = "Покупка дополнения"
        verbose_name_plural = "Покупки дополнений"

    def __str__(self):
        return "Цены докупки генераций"

    def clean(self):
        exists_qs = type(self).objects.exclude(pk=self.pk)
        if exists_qs.exists():
            raise ValidationError("Разрешена только одна запись с ценами докупки генераций.")

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)


class Plan(models.Model):
    # Meta
    is_active = models.BooleanField(default=True)
    is_free = models.BooleanField(default=False)
    period = models.CharField(max_length=10, choices=BillingPeriod.choices)
    sort_order = models.PositiveIntegerField(default=100)

    price_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    price_base_amount = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)

    # Engine mapping (frontend resolves to a label)
    llm_engine = models.ForeignKey(
        'ai.GPTModels', on_delete=models.SET_NULL, null=True, blank=True, related_name='+'
    )

    # Template Names
    template_name_ru = models.CharField(max_length=100, null=True, blank=True)
    template_name_en = models.CharField(max_length=100, null=True, blank=True)
    template_name_kg = models.CharField(max_length=100, null=True, blank=True)

    # Legacy-style content limits to keep your current counters
    song_limit = models.PositiveIntegerField(default=0)   # 0 => no included generations
    music_limit = models.PositiveIntegerField(default=0)  # 0 => no included generations
    text_limit = models.PositiveIntegerField(default=0)   # 0 => no included generations
    image_limit = models.PositiveIntegerField(default=0)  # 0 => no included generations

    # Sunday bonuses (legacy behavior)
    sunday_bonus_songs = models.PositiveIntegerField(default=0)
    sunday_bonus_music = models.PositiveIntegerField(default=0)
    sunday_bonus_texts = models.PositiveIntegerField(default=0)
    sunday_bonus_images = models.PositiveIntegerField(default=0)

    # Feature toggles
    ai_chat_enabled = models.BooleanField(default=False)
    realtime_chat_enabled = models.BooleanField(default=False)
    images_enabled = models.BooleanField(default=False)
    music_enabled = models.BooleanField(default=False)
    mp4_enabled = models.BooleanField(default=False)
    support_enabled = models.BooleanField(default=False)

    # Purchases
    can_purchase_addons = models.BooleanField(default=False)

    class Meta:
        ordering = ["sort_order", "id"]
        verbose_name = "Тариф"
        verbose_name_plural = "Тарифы"

    def __str__(self):
        tag = "FREE" if self.is_free else self.period.upper()
        return f"Plan #{self.id} [{tag}] {self.price_amount}"

    def clean(self):
        # Basic consistency
        if self.is_free:
            if self.price_amount != 0 or (self.price_base_amount and self.price_base_amount != 0):
                raise ValidationError("Free plan must have zero price and no base price.")
            if self.can_purchase_addons:
                raise ValidationError({
                    "can_purchase_addons": "Опция докупки доступна только для платных тарифов."
                })
        if self.price_base_amount is not None and self.price_base_amount <= self.price_amount:
            raise ValidationError("Base price should be greater than current price.")


class SubscriptionStatus(models.TextChoices):
    ACTIVE = "active", "Активна"
    INACTIVE = "inactive", "Неактивна"


class PaymentStatus(models.TextChoices):
    PAID = "paid", "Оплачено"
    UNPAID = "unpaid", "Не оплачено"


class UserSubscription(models.Model):
    # Use AUTH_USER_MODEL for flexibility
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="subscriptions")
    plan = models.ForeignKey(Plan, on_delete=models.PROTECT, related_name="subscriptions")

    start_date = models.DateTimeField(auto_now_add=True)
    end_date = models.DateTimeField(null=True, blank=True)

    status = models.CharField(max_length=20, choices=SubscriptionStatus.choices, default=SubscriptionStatus.ACTIVE)
    payment_status = models.CharField(max_length=20, choices=PaymentStatus.choices, default=PaymentStatus.UNPAID)
    payment_date = models.DateTimeField(null=True, blank=True)
    auto_renew = models.BooleanField(default=True)
    grace_until = models.DateTimeField(null=True, blank=True)
    billing_issue_code = models.CharField(max_length=32, blank=True, default="")

    class Meta:
        indexes = [
            models.Index(fields=["user", "status"]),
            models.Index(fields=["start_date"]),
        ]
        verbose_name = "Подписка пользователя"
        verbose_name_plural = "Подписки пользователей"

    def __str__(self):
        return f"{self.user} — Plan #{self.plan_id}"

    def save(self, *args, **kwargs):
        # Admin/manual creation may leave end_date empty; ensure billing cycle end is always set.
        if self.end_date is None and self.plan_id:
            start = self.start_date
            if start is None:
                from django.utils import timezone
                start = timezone.now()
                self.start_date = start
            days = _plan_cycle_days(getattr(self.plan, "period", None))
            self.end_date = start + timedelta(days=days)
        return super().save(*args, **kwargs)

    # Helpers
    def is_unlimited(self, value: int | None) -> bool:
        # Only NULL can represent unlimited; 0 means no included generations.
        return value is None

    def apply_addon_to_usage(self, addon: "AddonPurchase") -> None:
        """Increment usage counters by addon amounts."""
        usage = getattr(self, "usage", None)
        if not usage:
            return
        usage.music_left = (usage.music_left or 0) + addon.music_added
        usage.texts_left = (usage.texts_left or 0) + addon.texts_added
        usage.images_left = (usage.images_left or 0) + addon.images_added
        usage.save(update_fields=["music_left", "texts_left", "images_left"])

    # ---- Limits helpers ----
    def _get_usage_locked(self) -> "GenerationUsage":
        from django.db import transaction
        from django.db.models import F
        # Ensure usage row exists and lock for update when mutating
        with transaction.atomic():
            usage, _ = GenerationUsage.objects.select_for_update().get_or_create(subscription=self)
        return usage

    def _has_available(self, kind: str) -> bool:
        """Quick availability check without locking (best-effort)."""
        plan = self.plan
        usage = getattr(self, "usage", None)
        if kind == "text":
            if self.is_unlimited(plan.text_limit):
                return True
            left = (getattr(usage, "texts_left", 0) or 0)
            bonus = (getattr(self.user, "bonus_texts", 0) or 0)
            return (left > 0) or (bonus > 0)
        if kind == "image":
            if self.is_unlimited(plan.image_limit):
                return True
            left = (getattr(usage, "images_left", 0) or 0)
            bonus = (getattr(self.user, "bonus_images", 0) or 0)
            return (left > 0) or (bonus > 0)
        if kind == "song":
            if self.is_unlimited(plan.song_limit):
                return True
            left = (getattr(usage, "songs_left", 0) or 0)
            bonus = (getattr(self.user, "bonus_songs", 0) or 0)
            return (left > 0) or (bonus > 0)
        if kind == "music":
            if self.is_unlimited(plan.music_limit):
                return True
            left = (getattr(usage, "music_left", 0) or 0)
            bonus = (getattr(self.user, "bonus_music", 0) or 0)
            return (left > 0) or (bonus > 0)
        return False

    def can_consume(self, kind: str) -> bool:
        """Public best-effort check if user can perform generation of given kind."""
        return self._has_available(kind)

    def consume(self, kind: str) -> None:
        """
        Consume one unit for the given kind.
        Priority: plan usage -> user bonus. Raises ValidationError if none.
        """
        from django.db import transaction
        from django.core.exceptions import ValidationError
        from django.db.models import F
        from users.services import process_free_plan_triggers

        plan = self.plan
        with transaction.atomic():
            usage = GenerationUsage.objects.select_for_update().get_or_create(subscription=self)[0]
            user = type(self.user).objects.select_for_update().get(pk=self.user_id)

            if kind == "text":
                if not self.is_unlimited(plan.text_limit):
                    if usage.texts_left and usage.texts_left > 0:
                        usage.texts_left -= 1
                        usage.save(update_fields=["texts_left"])
                        process_free_plan_triggers(self)
                        return
                    if user.bonus_texts and user.bonus_texts > 0:
                        user.bonus_texts -= 1
                        user.save(update_fields=["bonus_texts"])
                        process_free_plan_triggers(self)
                        return
                    raise ValidationError("Лимит текстов исчерпан")
                # unlimited
                process_free_plan_triggers(self)
                return

            if kind == "image":
                if not self.is_unlimited(plan.image_limit):
                    if usage.images_left and usage.images_left > 0:
                        usage.images_left -= 1
                        usage.save(update_fields=["images_left"])
                        process_free_plan_triggers(self)
                        return
                    if user.bonus_images and user.bonus_images > 0:
                        user.bonus_images -= 1
                        user.save(update_fields=["bonus_images"])
                        process_free_plan_triggers(self)
                        return
                    raise ValidationError("Лимит изображений исчерпан")
                process_free_plan_triggers(self)
                return

            if kind == "song":
                if not self.is_unlimited(plan.song_limit):
                    if usage.songs_left and usage.songs_left > 0:
                        usage.songs_left -= 1
                        usage.save(update_fields=["songs_left"])
                        process_free_plan_triggers(self)
                        return
                    if user.bonus_songs and user.bonus_songs > 0:
                        user.bonus_songs -= 1
                        user.save(update_fields=["bonus_songs"])
                        process_free_plan_triggers(self)
                        return
                    raise ValidationError("Лимит песен исчерпан")
                process_free_plan_triggers(self)
                return

            if kind == "music":
                if not self.is_unlimited(plan.music_limit):
                    if usage.music_left and usage.music_left > 0:
                        usage.music_left -= 1
                        usage.save(update_fields=["music_left"])
                        process_free_plan_triggers(self)
                        return
                    if user.bonus_music and user.bonus_music > 0:
                        user.bonus_music -= 1
                        user.save(update_fields=["bonus_music"])
                        process_free_plan_triggers(self)
                        return
                    raise ValidationError("Лимит музыки исчерпан")
                process_free_plan_triggers(self)
                return

            raise ValidationError("Неизвестный тип ресурса")


class GenerationUsage(models.Model):
    subscription = models.OneToOneField(UserSubscription, on_delete=models.CASCADE, related_name="usage")

    # 0 means no remaining included generations.
    songs_left = models.IntegerField(default=0)
    music_left = models.IntegerField(default=0)
    texts_left = models.IntegerField(default=0)
    images_left = models.IntegerField(default=0)

    # Sunday bonus bookkeeping
    sunday_bonus_used = models.BooleanField(default=False)

    class Meta:
        indexes = [models.Index(fields=["subscription"])]
        verbose_name = "Остатки генераций"
        verbose_name_plural = "Остатки генераций"

    def __str__(self):
        return f"Usage for {self.subscription_id}"

    # Safe decrement helpers
    def _dec(self, field: str, unlimited: bool) -> None:
        """Decrement counter if not unlimited; never go negative."""
        if unlimited:
            return
        value = getattr(self, field, 0)
        if value <= 0:
            raise ValidationError(f"{field} limit exceeded.")
        setattr(self, field, value - 1)

    def consume_song(self, unlimited: bool) -> None:
        self._dec("songs_left", unlimited)

    def consume_music(self, unlimited: bool) -> None:
        self._dec("music_left", unlimited)

    def consume_text(self, unlimited: bool) -> None:
        self._dec("texts_left", unlimited)

    def consume_image(self, unlimited: bool) -> None:
        self._dec("images_left", unlimited)


class AddonPurchase(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="addon_purchases")
    purchase_date = models.DateTimeField(auto_now_add=True)
    music_added = models.PositiveIntegerField(default=0)
    texts_added = models.PositiveIntegerField(default=0)
    images_added = models.PositiveIntegerField(default=0)

    class Meta:
        indexes = [models.Index(fields=["user", "purchase_date"])]
        verbose_name = "Покупка дополнения"
        verbose_name_plural = "Покупки дополнений"

    def __str__(self):
        return f"{self.user} — +M:{self.music_added} +T:{self.texts_added} +I:{self.images_added}"


# =========================================================================
# Pay-as-you-go токен-система (новая бизнес-логика; не ломает таблицы выше)
# =========================================================================


class TokenPackage(models.Model):
    """Пакет кредитов для покупки (pay-as-you-go). Редактируется в админке.

    Название, бейдж и подпись переводятся отдельными полями на язык — так же,
    как статьи блога и библиотека студии. Иначе на английской и кыргызской
    витрине среди переведённого интерфейса оставались русские «Старт» и
    «Выбор большинства»: этот текст пишет клиент в админке, и подставить его
    из locales нельзя. Пусто — покажется русский вариант.
    """
    name = models.CharField(max_length=100, verbose_name="Название")
    name_en = models.CharField(max_length=100, blank=True, default="", verbose_name="Название (EN)")
    name_kg = models.CharField(max_length=100, blank=True, default="", verbose_name="Название (KG)")
    tokens = models.BigIntegerField(verbose_name="Кредитов")
    bonus_tokens = models.BigIntegerField(default=0, verbose_name="Бонусных кредитов")
    price = models.DecimalField(max_digits=12, decimal_places=2, verbose_name="Цена")
    currency = models.CharField(max_length=10, default="KGS", verbose_name="Валюта")
    is_active = models.BooleanField(default=True, verbose_name="Активен")
    sort_order = models.PositiveIntegerField(default=100, verbose_name="Порядок сортировки")
    description = models.TextField(blank=True, verbose_name="Описание (подпись под пакетом)")
    description_en = models.TextField(blank=True, default="", verbose_name="Описание (EN)")
    description_kg = models.TextField(blank=True, default="", verbose_name="Описание (KG)")
    badge = models.CharField(
        max_length=60, blank=True, default="", verbose_name="Бейдж",
        help_text="Маркетинговая плашка над пакетом, напр. «⭐ Популярный», «🔥 Лучший выбор». Пусто — без бейджа.")
    badge_en = models.CharField(max_length=60, blank=True, default="", verbose_name="Бейдж (EN)")
    badge_kg = models.CharField(max_length=60, blank=True, default="", verbose_name="Бейдж (KG)")
    featured = models.BooleanField(
        default=False, verbose_name="Выделенный",
        help_text="Визуально выделить пакет (рамка/увеличение) как рекомендованный. Включайте только у ОДНОГО пакета.")
    # Оплата в Telegram-боте. Пусто — пакет в боте не продаётся. Цена в Stars
    # задаётся человеком, а не курсом: она должна быть стабильной, подсказка
    # по формуле показывается рядом в админке (plans/stars.py).
    stars_price = models.PositiveIntegerField(
        null=True, blank=True, verbose_name="Цена в Telegram Stars",
        help_text="Пусто — в боте не продаётся. 1 Star ≈ $0.013 для нас.")
    stars_bonus_tokens = models.PositiveIntegerField(
        default=0, verbose_name="Бонус за оплату в боте, кредитов",
        help_text="Дополнительно к пакету при оплате Stars — вместо скидки.")

    class Meta:
        ordering = ["sort_order", "id"]
        verbose_name = "Пакет токенов"
        verbose_name_plural = "Пакеты токенов"

    def __str__(self):
        return f"{self.name} ({self.tokens}+{self.bonus_tokens} = {self.price} {self.currency})"


class TokenTransactionReason(models.TextChoices):
    CHAT = "chat", "Списание за чат"
    PURCHASE = "purchase", "Покупка пакета"
    ADMIN = "admin", "Ручная корректировка"
    BONUS = "bonus", "Бонус"
    WELCOME = "welcome", "Приветственный бонус"
    DAILY_BONUS = "daily_bonus", "Ежедневный бонус"
    REFUND = "refund", "Возврат"
    REFERRAL = "referral", "Реферальное начисление"
    TRANSFER_IN = "transfer_in", "Перевод получен"
    TRANSFER_OUT = "transfer_out", "Перевод отправлен"
    PROMO = "promo", "Промокод"
    # Студия и распознавание речи писали свои причины мимо этого списка —
    # в базе они лежат давно, а в фильтрах и подписях админки их не было.
    CARTOON_KEYFRAME = "cartoon_keyframe", "Студия: кадр"
    CARTOON_SCENE = "cartoon_scene", "Студия: сцена"
    CARTOON_CHARACTER = "cartoon_character", "Студия: свой герой"
    CARTOON_VOICE = "cartoon_voice", "Студия: озвучка"
    CARTOON_MUSIC = "cartoon_music", "Студия: музыка"
    CARTOON_SFX = "cartoon_sfx", "Студия: звуковой эффект"
    STT = "stt", "Распознавание голоса"
    # Видеостудия списывает только за готовый результат, поэтому причин
    # «возврат» у неё нет: несостоявшийся дубль просто снимает резерв.
    VSTUDIO_VIDEO = "vstudio_video", "Видеостудия: видео"
    VSTUDIO_IMAGE = "vstudio_image", "Видеостудия: картинка"


# Списания видеостудии. Метрики трат считают их вместе с чатом — иначе
# выручка студии в админке не видна вовсе.
VSTUDIO_SPEND_REASONS = (TokenTransactionReason.VSTUDIO_VIDEO.value,
                         TokenTransactionReason.VSTUDIO_IMAGE.value)


class TokenTransaction(models.Model):
    """Леджер движения токенов (для аудита). Только append, не редактируется."""
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="token_transactions",
        verbose_name="Пользователь",
    )
    # delta: + начисление / − списание
    delta = models.BigIntegerField(verbose_name="Изменение")
    reason = models.CharField(
        max_length=20,
        choices=TokenTransactionReason.choices,
        verbose_name="Причина",
    )
    balance_after = models.BigIntegerField(verbose_name="Баланс после")
    created_at = models.DateTimeField(auto_now_add=True, db_index=True, verbose_name="Создано")
    meta = models.JSONField(null=True, blank=True, verbose_name="Метаданные")

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "Транзакция токенов"
        verbose_name_plural = "Транзакции токенов"

    def __str__(self):
        sign = "+" if self.delta >= 0 else ""
        return f"{self.user_id}: {sign}{self.delta} ({self.reason}) -> {self.balance_after}"


# =========================================================================
# Промокоды (фиксированные кредиты)
# =========================================================================


class PromoCode(models.Model):
    """Промокод, дающий ФИКСИРОВАННОЕ число кредитов (без процентов).

    Код хранится в верхнем регистре (нормализация в бизнес-слое). Ограничения
    активаций: max_activations (null=безлимит), per_user_once (один раз на юзера),
    new_users_only (только для новых регистраций), expires_at, is_active.
    """
    code = models.CharField(max_length=40, unique=True, verbose_name="Код")
    bonus_credits = models.PositiveIntegerField(verbose_name="Кредитов")
    expires_at = models.DateTimeField(null=True, blank=True, verbose_name="Истекает")
    max_activations = models.PositiveIntegerField(
        null=True, blank=True,
        verbose_name="Максимум активаций",
        help_text="Пусто — безлимит.",
    )
    used_count = models.PositiveIntegerField(default=0, verbose_name="Использовано раз")
    per_user_once = models.BooleanField(default=True, verbose_name="Один раз на пользователя")
    new_users_only = models.BooleanField(default=False, verbose_name="Только для новых пользователей")
    is_active = models.BooleanField(default=True, verbose_name="Активен")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="Создан")
    note = models.CharField(max_length=200, blank=True, verbose_name="Заметка")

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "Промокод"
        verbose_name_plural = "Промокоды"

    def __str__(self):
        return self.code


class PromoActivation(models.Model):
    """Факт активации промокода пользователем (идемпотентность + аудит)."""
    promo = models.ForeignKey(
        PromoCode,
        on_delete=models.CASCADE,
        related_name="activations",
        verbose_name="Промокод",
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="promo_activations",
        verbose_name="Пользователь",
    )
    credited = models.PositiveIntegerField(verbose_name="Начислено кредитов")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="Создано")

    class Meta:
        ordering = ["-created_at"]
        unique_together = (("promo", "user"),)
        verbose_name = "Активация промокода"
        verbose_name_plural = "Активации промокодов"

    def __str__(self):
        return f"{self.promo_id}:{self.user_id} (+{self.credited})"


# =========================================================================
# Скидка при уходе со страницы тарифов (exit-intent discount)
# =========================================================================


class ExitDiscountOffer(models.Model):
    """Оффер скидки на оплату тарифа, показанный при попытке ухода со страницы pricing.

    Скидка реализуется как СНИЖЕНИЕ СУММЫ ОПЛАТЫ за тот же пакет (не бонусные
    кредиты). shown_at/expires_at — окно действия оффера, сервер источник
    истины. percent фиксируется на момент показа, чтобы смена рантайм-настройки
    не меняла задним числом уже выданные офферы. applied_to_payment — мягкая
    бронь скидки за конкретной попыткой оплаты (ставится атомарно через
    select_for_update при старте покупки), чтобы 2 параллельных клика "Купить"
    не оба получили скидку.
    """
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True, blank=True,
        on_delete=models.SET_NULL,
        related_name="exit_discount_offers",
        verbose_name="Пользователь",
    )
    device_key = models.CharField(
        max_length=64, blank=True, default="", db_index=True,
        verbose_name="Device key",
        help_text="localStorage UUID для гостя (не авторизован).",
    )
    ip_address = models.GenericIPAddressField(
        null=True, blank=True, verbose_name="IP-адрес",
        help_text="Только для аудита/статистики. НЕ используется как ключ блокировки повторного показа (CGNAT).",
    )
    shown_at = models.DateTimeField(null=True, blank=True, verbose_name="Показан")
    expires_at = models.DateTimeField(null=True, blank=True, verbose_name="Истекает")
    percent = models.PositiveSmallIntegerField(
        null=True, blank=True, verbose_name="Процент скидки",
        help_text="Зафиксирован на момент показа оффера.",
    )
    claimed_at = models.DateTimeField(null=True, blank=True, verbose_name="Принят пользователем")
    dismissed_at = models.DateTimeField(
        null=True, blank=True, verbose_name="Отклонён",
        help_text="Аналитика явного отказа (крестик/«Нет спасибо»). НЕ гейт повторного показа — гейт это shown_at.",
    )
    redeemed_at = models.DateTimeField(
        null=True, blank=True, verbose_name="Погашен",
        help_text="Когда скидка реально применилась к успешно оплаченному платежу.",
    )
    applied_to_payment = models.ForeignKey(
        "payments.Payment",
        null=True, blank=True,
        on_delete=models.SET_NULL,
        related_name="exit_discount_offer",
        verbose_name="Применён к платежу",
    )
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="Создан")

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["user"],
                condition=Q(user__isnull=False),
                name="uniq_exit_discount_user",
            ),
            models.UniqueConstraint(
                fields=["device_key"],
                condition=~Q(device_key=""),
                name="uniq_exit_discount_device",
            ),
        ]
        verbose_name = "Оффер скидки при уходе"
        verbose_name_plural = "Офферы скидки при уходе"

    def __str__(self):
        return f"ExitDiscountOffer user={self.user_id} device={self.device_key or '-'}"
