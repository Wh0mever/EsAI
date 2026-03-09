from django.conf import settings
from django.db import models
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
    topmedia_engine = models.ForeignKey(
        'ai.TopMediaModels', on_delete=models.SET_NULL, null=True, blank=True, related_name='+'
    )
    
    # Template Names
    template_name_ru = models.CharField(max_length=100, null=True, blank=True)
    template_name_en = models.CharField(max_length=100, null=True, blank=True)
    template_name_kg = models.CharField(max_length=100, null=True, blank=True)

    # Limits (0 => no included generations)
    ai_templates_limit = models.PositiveIntegerField(null=True, blank=True)
    operations_per_month_limit = models.PositiveIntegerField(null=True, blank=True)
    covers_limit = models.PositiveIntegerField(null=True, blank=True)

    # Chat response tokens limit (per reply). If null -> fallback to model default.
    chat_output_tokens_limit = models.PositiveIntegerField(null=True, blank=True)

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
    rewriter_enabled = models.BooleanField(default=False)
    antiplag_enabled = models.BooleanField(default=False)
    images_enabled = models.BooleanField(default=False)
    diffusion_images_enabled = models.BooleanField(default=False)
    blog_master_enabled = models.BooleanField(default=False)
    music_enabled = models.BooleanField(default=False)
    tts_enabled = models.BooleanField(default=False)
    my_templates_enabled = models.BooleanField(default=False)
    manager_enabled = models.BooleanField(default=False)
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
