"""Модели партнёрской программы EsAI Creators.

Правила, которые держит сама схема:
- привязка покупателя к креатору — отдельная строка (CreatorReferral), а не
  User.referred_by: обычная реферальная программа живёт рядом и не меняется;
- балансов в таблицах нет. Заработано, доступно и выплачено считаются из строк
  комиссий и выводов под блокировкой строки Creator (Creator.objects.locked);
- «один открытый», «один основной», «один раз за платёж» — частичные
  уникальные индексы, а не проверки в коде: гонку двух запросов ловит база.
"""
from __future__ import annotations

from django.conf import settings
from django.db import models
from django.db.models import Q
from django.utils import timezone

User = settings.AUTH_USER_MODEL


class CreatorLevel(models.Model):
    """Уровень программы: процент комиссии и пороги «условия выполнены».

    Пороги только показываются в кабинете. Уровень креатору меняет
    администратор вручную — автоматического повышения нет.
    """

    key = models.SlugField(max_length=32, unique=True, verbose_name="Ключ")
    title = models.CharField(max_length=64, verbose_name="Название")
    percent = models.DecimalField(max_digits=5, decimal_places=2, verbose_name="Комиссия, %")
    sort = models.PositiveSmallIntegerField(unique=True, verbose_name="Порядок")
    min_publications = models.PositiveIntegerField(default=0, verbose_name="Публикаций, от")
    min_registrations = models.PositiveIntegerField(default=0, verbose_name="Регистраций, от")
    min_paying = models.PositiveIntegerField(default=0, verbose_name="Платящих, от")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="Изменён")

    class Meta:
        ordering = ["sort"]
        verbose_name = "Уровень креатора"
        verbose_name_plural = "Уровни креаторов"
        constraints = [
            # Клиент обещает «до 25%»: больше не запишет ни админка, ни ошибка в коде.
            models.CheckConstraint(condition=Q(percent__gt=0) & Q(percent__lte=25),
                                   name="creators_level_percent_range"),
        ]

    def __str__(self) -> str:
        return f"{self.title} ({self.percent}%)"


class CreatorApplication(models.Model):
    """Заявка на участие. Одобряет только человек; до одобрения креатора нет."""

    class Status(models.TextChoices):
        NEW = "new", "На рассмотрении"
        APPROVED = "approved", "Одобрена"
        REJECTED = "rejected", "Отклонена"
        # Отклонена, и подать заново нельзя, пока главный администратор не снимет запрет.
        BLOCKED = "blocked", "Заблокирована"

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="creator_applications",
                             verbose_name="Пользователь")
    name = models.CharField(max_length=120, verbose_name="Имя")
    telegram = models.CharField(max_length=64, verbose_name="Telegram")
    country = models.CharField(max_length=64, verbose_name="Страна")
    instagram_url = models.CharField(max_length=300, blank=True, default="", verbose_name="Instagram")
    tiktok_url = models.CharField(max_length=300, blank=True, default="", verbose_name="TikTok")
    youtube_url = models.CharField(max_length=300, blank=True, default="", verbose_name="YouTube")
    # Список до 5 ссылок на другие соцсети.
    other_links = models.JSONField(default=list, blank=True, verbose_name="Другие соцсети")
    followers = models.PositiveIntegerField(default=0, verbose_name="Подписчиков")
    occupation = models.TextField(verbose_name="Чем занимается")
    motivation = models.TextField(verbose_name="Зачем участвует")
    # Примеры работ — только ссылки (до 10), файлы не загружаются.
    samples = models.JSONField(default=list, blank=True, verbose_name="Примеры работ")
    lang = models.CharField(max_length=5, default="ru", verbose_name="Язык")
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.NEW,
                              db_index=True, verbose_name="Статус")
    decided_at = models.DateTimeField(null=True, blank=True, verbose_name="Решено")
    decided_by = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL,
                                   related_name="+", verbose_name="Кто решил")
    reject_reason = models.TextField(blank=True, default="", verbose_name="Причина отказа")
    ip = models.GenericIPAddressField(null=True, blank=True, verbose_name="IP-адрес")
    created_at = models.DateTimeField(auto_now_add=True, db_index=True, verbose_name="Создана")

    class Meta:
        verbose_name = "Заявка креатора"
        verbose_name_plural = "Заявки креаторов"
        constraints = [
            # Одна заявка на рассмотрении на человека; отклонённый может подать снова.
            models.UniqueConstraint(fields=["user"], condition=Q(status="new"),
                                    name="creators_app_one_open"),
        ]
        indexes = [
            models.Index(fields=["status", "created_at"], name="creators_app_status"),
        ]

    def __str__(self) -> str:
        return f"Заявка #{self.pk} {self.name} · {self.get_status_display()}"


class CreatorManager(models.Manager):
    def locked(self, pk):
        """Единственная «блокировка креатора». Вызывающий уже внутри transaction.atomic().

        of=("self",): блокируется только строка creators_creator. Без этого
        Postgres вместе с ней заблокировал бы общую строку уровня (встали бы в
        очередь начисления всех креаторов уровня) и строку пользователя
        креатора (нарушился бы порядок блокировок Payment -> User -> Creator).

        no_key=True (FOR NO KEY UPDATE): денежные операции по-прежнему идут по
        одной, но блокировка не спорит с проверкой внешнего ключа. С FOR UPDATE
        выдача кредитов (строка User -> запись журнала со ссылкой на креатора)
        и действие самого креатора (строка Creator -> запись со ссылкой на его
        User) брали две строки в обратном порядке и запирали друг друга.
        Нет строки — Creator.DoesNotExist.
        """
        return (self.select_for_update(of=("self",), no_key=True)
                .select_related("level", "user").get(pk=pk))


class Creator(models.Model):
    """Участник программы. Создаётся при одобрении заявки; created_at — дата вступления.

    Искать по Creator.objects.filter(user_id=...), а не через user.creator:
    у обычного пользователя обратная связь бросает исключение.
    """

    class Status(models.TextChoices):
        ACTIVE = "active", "Активен"
        BLOCKED = "blocked", "Заблокирован"

    user = models.OneToOneField(User, on_delete=models.PROTECT, related_name="creator",
                                verbose_name="Пользователь")
    application = models.ForeignKey(CreatorApplication, null=True, blank=True,
                                    on_delete=models.SET_NULL, related_name="+",
                                    verbose_name="Заявка")
    level = models.ForeignKey(CreatorLevel, on_delete=models.PROTECT, related_name="creators",
                              verbose_name="Уровень")
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.ACTIVE,
                              db_index=True, verbose_name="Статус")
    # Имя из заявки: его видит приглашённый («вы пришли по приглашению …»).
    display_name = models.CharField(max_length=120, verbose_name="Имя для приглашённых")
    # Язык уведомлений: у пользователя своего поля языка нет.
    lang = models.CharField(max_length=5, default="ru", verbose_name="Язык уведомлений")
    payout_address = models.CharField(max_length=64, blank=True, default="",
                                      verbose_name="Адрес USDT TRC20")
    payout_address_changed_at = models.DateTimeField(null=True, blank=True,
                                                     verbose_name="Адрес изменён")
    # Ключ уровня, про который уже отправлено «условия выполнены» — чтобы не слать дважды.
    next_level_notified = models.CharField(max_length=32, blank=True, default="",
                                           verbose_name="Уведомлён об уровне")
    blocked_at = models.DateTimeField(null=True, blank=True, verbose_name="Заблокирован")
    blocked_reason = models.TextField(blank=True, default="", verbose_name="Причина блокировки")
    created_at = models.DateTimeField(auto_now_add=True, db_index=True, verbose_name="Вступил")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="Изменён")

    objects = CreatorManager()

    class Meta:
        verbose_name = "Креатор"
        verbose_name_plural = "Креаторы"

    def __str__(self) -> str:
        return f"{self.display_name} (#{self.pk})"


class CreatorCode(models.Model):
    """Промокод креатора: он же идентификатор ссылки ?ref=CODE.

    Строка не удаляется никогда: старый код после замены остаётся псевдонимом
    того же креатора и поэтому не может достаться другому.
    """

    code = models.CharField(max_length=16, unique=True, verbose_name="Код")
    creator = models.ForeignKey(Creator, on_delete=models.PROTECT, related_name="codes",
                                verbose_name="Креатор")
    is_primary = models.BooleanField(default=True, verbose_name="Основной")
    # True — код работает. Старый код после замены: is_primary=False, is_active=True.
    # False ставят только вручную, когда код надо погасить совсем.
    is_active = models.BooleanField(default=True, verbose_name="Действует")
    created_by = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL,
                                   related_name="+", verbose_name="Кто создал")
    created_at = models.DateTimeField(auto_now_add=True, db_index=True, verbose_name="Создан")

    class Meta:
        verbose_name = "Промокод креатора"
        verbose_name_plural = "Промокоды креаторов"
        constraints = [
            models.UniqueConstraint(fields=["creator"], condition=Q(is_primary=True),
                                    name="creators_code_one_primary"),
        ]

    def save(self, *args, **kwargs):
        # В базе код всегда в верхнем регистре: сравнение идёт по точному совпадению.
        self.code = str(self.code or "").strip().upper()
        return super().save(*args, **kwargs)

    def __str__(self) -> str:
        return self.code


class CreatorReferralManager(models.Manager):
    def active_for(self, user_id):
        """Действующая привязка пользователя или None."""
        return (self.filter(user_id=user_id, ended_at__isnull=True)
                .select_related("creator", "creator__level").first())

    def covering(self, user_id, at):
        """Привязка, которая действовала в момент `at`, или None."""
        return (self.filter(user_id=user_id, bound_at__lte=at)
                .filter(Q(ended_at__isnull=True) | Q(ended_at__gt=at))
                .select_related("creator", "creator__level").order_by("-bound_at").first())


class CreatorReferral(models.Model):
    """Привязка пользователя к креатору. Пишет её только creators.attribution.bind."""

    class Source(models.TextChoices):
        LINK = "link", "Ссылка"
        PROMO = "promo", "Промокод"
        BOT = "bot", "Telegram-бот"
        ADMIN = "admin", "Администратор"

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="creator_referrals",
                             verbose_name="Пользователь")
    creator = models.ForeignKey(Creator, on_delete=models.PROTECT, related_name="referrals",
                                verbose_name="Креатор")
    source = models.CharField(max_length=8, choices=Source.choices, verbose_name="Источник")
    code_used = models.CharField(max_length=16, blank=True, default="", verbose_name="Код")
    bound_at = models.DateTimeField(default=timezone.now, db_index=True, verbose_name="Привязан")
    # Администратор, который привязал вручную (source=admin).
    bound_by = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL,
                                 related_name="+", verbose_name="Кто привязал")
    ended_at = models.DateTimeField(null=True, blank=True, verbose_name="Снята")
    # admin_rebind, admin_unbind, merge_self, merge_dropped
    end_reason = models.CharField(max_length=32, blank=True, default="",
                                  verbose_name="Причина снятия")
    # Подозрительная привязка не считается регистрацией, а её комиссии копятся в held.
    suspect = models.BooleanField(default=False, db_index=True, verbose_name="Подозрительная")
    flags = models.JSONField(default=dict, blank=True, verbose_name="Признаки")
    ip = models.GenericIPAddressField(null=True, blank=True, verbose_name="IP-адрес")
    subnet = models.CharField(max_length=64, blank=True, default="", verbose_name="Подсеть")
    fingerprint = models.CharField(max_length=128, blank=True, default="",
                                   verbose_name="Отпечаток устройства")
    # Telegram id на момент привязки: у пришедших из бота отпечатка устройства
    # нет, повторную регистрацию видно только по нему.
    telegram_uid = models.CharField(max_length=32, blank=True, default="", db_index=True,
                                    verbose_name="Telegram id")

    objects = CreatorReferralManager()

    class Meta:
        verbose_name = "Реферал креатора"
        verbose_name_plural = "Рефералы креаторов"
        constraints = [
            # Один пользователь — один креатор: вторую действующую привязку не даст база.
            models.UniqueConstraint(fields=["user"], condition=Q(ended_at__isnull=True),
                                    name="creators_ref_one_active"),
        ]
        indexes = [
            models.Index(fields=["creator", "bound_at"], name="creators_ref_creator"),
            models.Index(fields=["creator", "fingerprint"], name="creators_ref_fp"),
        ]

    def __str__(self) -> str:
        return f"Реферал #{self.pk}: пользователь {self.user_id} -> креатор {self.creator_id}"


class CreatorClick(models.Model):
    """Переход по ссылке креатора: одно устройство — один переход в день."""

    creator = models.ForeignKey(Creator, on_delete=models.CASCADE, related_name="clicks",
                                verbose_name="Креатор")
    code = models.CharField(max_length=16, verbose_name="Код")
    device_key = models.CharField(max_length=80, verbose_name="Ключ устройства")
    day = models.DateField(verbose_name="День")
    ip_hash = models.CharField(max_length=64, blank=True, default="", verbose_name="Хеш IP")
    created_at = models.DateTimeField(auto_now_add=True, db_index=True, verbose_name="Создан")

    class Meta:
        verbose_name = "Переход по ссылке креатора"
        verbose_name_plural = "Переходы по ссылкам креаторов"
        constraints = [
            models.UniqueConstraint(fields=["creator", "device_key", "day"],
                                    name="creators_click_dedupe"),
        ]
        indexes = [
            models.Index(fields=["creator", "day"], name="creators_click_day"),
        ]

    def __str__(self) -> str:
        return f"{self.code} · {self.day}"


class CreatorPublication(models.Model):
    """Публикация креатора. В прогресс уровня идут только подтверждённые."""

    class Network(models.TextChoices):
        INSTAGRAM = "instagram", "Instagram"
        TIKTOK = "tiktok", "TikTok"
        YOUTUBE = "youtube", "YouTube"
        TELEGRAM = "telegram", "Telegram"
        FACEBOOK = "facebook", "Facebook"
        X = "x", "X (Twitter)"
        VK = "vk", "ВКонтакте"
        OTHER = "other", "Другое"

    class Status(models.TextChoices):
        REVIEW = "review", "На проверке"
        APPROVED = "approved", "Подтверждено"
        REJECTED = "rejected", "Отклонено"

    creator = models.ForeignKey(Creator, on_delete=models.CASCADE, related_name="publications",
                                verbose_name="Креатор")
    network = models.CharField(max_length=16, choices=Network.choices, verbose_name="Соцсеть")
    url = models.CharField(max_length=500, verbose_name="Ссылка")
    # Ссылка без www, хвостового / и меток — по ней ищем повторы.
    url_norm = models.CharField(max_length=500, db_index=True, verbose_name="Ссылка (нормализованная)")
    description = models.CharField(max_length=500, blank=True, default="", verbose_name="Описание")
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.REVIEW,
                              db_index=True, verbose_name="Статус")
    decided_at = models.DateTimeField(null=True, blank=True, verbose_name="Решено")
    decided_by = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL,
                                   related_name="+", verbose_name="Кто решил")
    reject_reason = models.TextField(blank=True, default="", verbose_name="Причина отказа")
    created_at = models.DateTimeField(auto_now_add=True, db_index=True, verbose_name="Добавлена")

    class Meta:
        verbose_name = "Публикация креатора"
        verbose_name_plural = "Публикации креаторов"
        constraints = [
            # Один пост засчитывается одному креатору; отклонённую ссылку можно подать снова.
            models.UniqueConstraint(fields=["url_norm"], condition=~Q(status="rejected"),
                                    name="creators_pub_url_once"),
        ]
        indexes = [
            models.Index(fields=["creator", "status"], name="creators_pub_creator"),
        ]

    def __str__(self) -> str:
        return f"{self.get_network_display()} · {self.url[:60]} · {self.get_status_display()}"


class CreatorCommission(models.Model):
    """Комиссия креатора с одного оплаченного заказа (или его части — у крипты).

    Процент, уровень, курс и база — слепки на момент начисления: смена уровня
    или курса старые строки не трогает.
    """

    class Status(models.TextChoices):
        ACCRUED = "accrued", "Начислена"
        HELD = "held", "Придержана"
        REVERSED = "reversed", "Отменена (возврат)"
        VOID = "void", "Аннулирована"

    creator = models.ForeignKey(Creator, on_delete=models.PROTECT, related_name="commissions",
                                verbose_name="Креатор")
    referral = models.ForeignKey(CreatorReferral, null=True, blank=True,
                                 on_delete=models.SET_NULL, related_name="commissions",
                                 verbose_name="Привязка")
    buyer = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL,
                              related_name="+", verbose_name="Покупатель")
    # Слепок id покупателя: остаётся, даже если пользователя удалят.
    buyer_pk = models.PositiveBigIntegerField(db_index=True, verbose_name="ID покупателя")
    payment = models.ForeignKey("payments.Payment", on_delete=models.PROTECT,
                                related_name="creator_commissions", verbose_name="Платёж")
    # "" — оплата одним куском; у крипты — накопленные кредиты строкой (её idem).
    part = models.CharField(max_length=32, blank=True, default="", verbose_name="Часть")
    order_id = models.CharField(max_length=64, blank=True, default="", db_index=True,
                                verbose_name="Заказ")
    provider = models.CharField(max_length=32, verbose_name="Платёжная система")
    paid_amount = models.DecimalField(max_digits=14, decimal_places=2, verbose_name="Оплачено")
    paid_currency = models.CharField(max_length=10, verbose_name="Валюта оплаты")
    # Фактический курс: base_usd / paid_amount.
    rate_to_usd = models.DecimalField(max_digits=18, decimal_places=8, verbose_name="Курс к USD")
    rate_source = models.CharField(max_length=32, verbose_name="Источник курса")
    base_usd = models.DecimalField(max_digits=18, decimal_places=6, verbose_name="База, USD")
    level_key = models.CharField(max_length=32, verbose_name="Уровень (слепок)")
    percent = models.DecimalField(max_digits=5, decimal_places=2, verbose_name="Процент (слепок)")
    amount_usdt = models.DecimalField(max_digits=18, decimal_places=6, verbose_name="Комиссия, USDT")
    status = models.CharField(max_length=10, choices=Status.choices, db_index=True,
                              verbose_name="Статус")
    # Код причины для void/held/reversed. У начисленной: "" — начислил хук,
    # "released" — администратор снял удержание, "restored" — вернул после отмены.
    reason = models.CharField(max_length=64, blank=True, default="", verbose_name="Причина")
    # С этой даты комиссия доступна к выводу (холд по дате, без отдельной задачи).
    available_at = models.DateTimeField(null=True, blank=True, verbose_name="Доступна с")
    reversed_at = models.DateTimeField(null=True, blank=True, verbose_name="Отменена")
    # Когда опрос возвратов последний раз спрашивал провайдера об этом платеже.
    refund_checked_at = models.DateTimeField(null=True, blank=True, db_index=True,
                                             verbose_name="Проверка возврата")
    created_at = models.DateTimeField(auto_now_add=True, db_index=True, verbose_name="Создана")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="Изменена")

    class Meta:
        verbose_name = "Комиссия креатора"
        verbose_name_plural = "Комиссии креаторов"
        constraints = [
            # Идемпотентность начисления: одна строка на (платёж, часть).
            models.UniqueConstraint(fields=["payment", "part"], name="creators_comm_payment_part"),
            models.CheckConstraint(condition=Q(amount_usdt__gte=0),
                                   name="creators_comm_amount_nonneg"),
        ]
        indexes = [
            models.Index(fields=["creator", "status", "available_at"], name="creators_comm_balance"),
            models.Index(fields=["status", "created_at"], name="creators_comm_status"),
        ]

    def __str__(self) -> str:
        return f"Комиссия #{self.pk}: {self.amount_usdt} USDT · {self.get_status_display()}"


class CreatorWithdrawal(models.Model):
    """Заявка на вывод USDT TRC20. Выплата ручная: код ничего не отправляет в сеть."""

    class Status(models.TextChoices):
        REVIEW = "review", "На проверке"
        APPROVED = "approved", "Одобрено"
        PAID = "paid", "Выплачено"
        REJECTED = "rejected", "Отклонено"

    creator = models.ForeignKey(Creator, on_delete=models.PROTECT, related_name="withdrawals",
                                verbose_name="Креатор")
    amount_usdt = models.DecimalField(max_digits=18, decimal_places=2, verbose_name="Сумма, USDT")
    # Слепок адреса на момент заявки: смена адреса в профиле заявку не меняет.
    address = models.CharField(max_length=64, verbose_name="Адрес")
    network = models.CharField(max_length=10, default="TRC20", verbose_name="Сеть")
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.REVIEW,
                              db_index=True, verbose_name="Статус")
    # Хеш перевода, hex в нижнем регистре.
    txid = models.CharField(max_length=64, blank=True, default="", verbose_name="TXID")
    approved_by = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL,
                                    related_name="+", verbose_name="Кто одобрил")
    paid_by = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL,
                                related_name="+", verbose_name="Кто выплатил")
    rejected_by = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL,
                                    related_name="+", verbose_name="Кто отклонил")
    approved_at = models.DateTimeField(null=True, blank=True, verbose_name="Одобрено")
    paid_at = models.DateTimeField(null=True, blank=True, verbose_name="Выплачено")
    rejected_at = models.DateTimeField(null=True, blank=True, verbose_name="Отклонено")
    reject_reason = models.TextField(blank=True, default="", verbose_name="Причина отказа")
    ip = models.GenericIPAddressField(null=True, blank=True, verbose_name="IP-адрес")
    created_at = models.DateTimeField(auto_now_add=True, db_index=True, verbose_name="Создана")

    class Meta:
        verbose_name = "Вывод креатора"
        verbose_name_plural = "Выводы креаторов"
        constraints = [
            models.CheckConstraint(condition=Q(amount_usdt__gte=10),
                                   name="creators_wd_min_amount"),
            # Одна заявка в работе на креатора.
            models.UniqueConstraint(fields=["creator"],
                                    condition=Q(status__in=["review", "approved"]),
                                    name="creators_wd_one_open"),
            # Один перевод не закрывает две выплаты.
            models.UniqueConstraint(fields=["txid"], condition=~Q(txid=""),
                                    name="creators_wd_txid_unique"),
            # «Выплачено» без TXID не бывает.
            models.CheckConstraint(condition=~Q(status="paid") | ~Q(txid=""),
                                   name="creators_wd_paid_has_txid"),
        ]

    def __str__(self) -> str:
        return f"Вывод #{self.pk}: {self.amount_usdt} USDT · {self.get_status_display()}"
