from django.db import models
from django.conf import settings


class Payment(models.Model):

    PROVIDER_CHOICES = (
        ("freedompay", "FreedomPay"),
        # ЮKassa и крипта появились позже FreedomPay; у старых рублёвых
        # платежей провайдер записан только внутри request["provider"] —
        # миграция 0003 их доразмечает.
        ("yookassa", "ЮKassa"),
        ("crypto_nowpayments", "NOWPayments (крипта)"),
        # Оплата внутри Telegram-бота. Сумма хранится в Stars, валюта XTR.
        ("telegram_stars", "Telegram Stars"),
        # Межбанковский QR в сомах. Номера заказов той же формы tokpkg-…, что у
        # FreedomPay, поэтому различать их можно только по этому полю.
        ("gopay", "GoPay (единый QR)"),
    )

    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="payment_logs",
    )
    
    # Payment details
    provider = models.CharField(max_length=32, choices=PROVIDER_CHOICES, default="freedompay")
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    currency = models.CharField(max_length=10, default="USD")
    order_id = models.CharField(max_length=64, blank=True, null=True, db_index=True)
    description = models.CharField(max_length=255, blank=True, null=True)
    
    # Logging fields
    is_test = models.BooleanField(default=False)
    success = models.BooleanField(default=False)
    request = models.JSONField(default=dict)
    response = models.JSONField(default=dict)
    error = models.TextField(blank=True, null=True)

    class Meta:
        ordering = ("-created_at", "-id")
        indexes = [
            models.Index(fields=["created_at"]),
            models.Index(fields=["order_id"]),
        ]
        verbose_name = "Платеж"
        verbose_name_plural = "Платежи"

    def __str__(self) -> str:
        return f"[{self.created_at:%Y-%m-%d %H:%M}] {self.provider} {self.amount} {self.currency} -> {'OK' if self.success else 'FAIL'}"


class FunnelEvent(models.Model):
    """Шаги воронки оплаты, которые не видны по платежам.

    Зачем. По таблице платежей видно только то, что началось с нажатия
    «Пополнить»: 95 попыток, 12 оплат. Но 73 из них — это люди, которых
    увели на страницу банка, и они не вернулись; понять, сколько народу
    вообще дошло до тарифов и сколько нажало кнопку, было нельзя.

    Поэтому клиентские шаги пишутся сюда, а серверные (платёж создан, ушёл
    на оплату, вернулся, оплачен) по-прежнему считаются по Payment —
    дублировать их событиями значит завести второй источник правды о деньгах.

    Гость узнаётся по тому же ключу устройства, что и скидка при уходе, —
    он лежит в браузере и общий на весь сайт.
    """
    NAMES = ("pricing_view", "topup_click",
             # Студия: от первого экрана до оплаты. Шаги заведены давно, но фронт
             # их не отправлял — неделя рекламы прошла без единой цифры.
             "studio_view", "studio_hero_pick", "studio_scene_add", "studio_tryon",
             "studio_auth_prompt", "studio_render_click", "studio_paywall",
             # Крипта: между «выбрал монету» и «оплатил» человек уходит в свой
             # кошелёк, и без этих шагов видно только начало и конец пути.
             "crypto_currency_pick", "crypto_invoice_created", "crypto_paid",
             # Оплата в сомах: какой способ (банк-приложение или карта) человек
             # выбрал у нас перед уходом на страницу FreedomPay.
             "kgs_method_pick",
             # Единый QR на нашем экране: показали, открыли банк, сохранили
             # картинку, оплатили, не успели, ушли к другому способу. По ним
             # клиент сравнивает QR с картой.
             "kgs_qr_shown", "kgs_qr_app_open", "kgs_qr_save",
             "kgs_qr_paid", "kgs_qr_expired", "kgs_qr_other_method",
             # Бот: от первого /start до оплаты Stars.
             "bot_start", "bot_pricing_view", "bot_stars_invoice", "bot_stars_paid",
             # Видеостудия (/video-studio): только клиентские шаги. Исходы
             # генераций сюда не пишутся — их источник правды таблица дублей.
             "vstudio_view", "vstudio_upload", "vstudio_mention", "vstudio_imagegen",
             "vstudio_blocked", "vstudio_run_click", "vstudio_paywall",
             "vstudio_auth_prompt", "vstudio_condense", "vstudio_share",
             # Первый экран видеостудии: что человек нажал до первого запроса
             # (meta {what: reel|template|model|tool|showcase|continue, id}).
             "vstudio_home_pick",
             # «Скачать» на телефоне: все исходы, кроме сразу удачного сохранения
             # (шторка, отказ окна, файл не скачался, шаги в шторке). Анонимно;
             # meta — только белый список полей (payments/funnel.py, MEDIA_SAVE_FIELDS).
             "media_save")

    name = models.CharField(max_length=32, db_index=True, verbose_name="Шаг")
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="funnel_events", verbose_name="Пользователь")
    device_key = models.CharField(max_length=64, blank=True, default="", db_index=True,
                                  verbose_name="Ключ устройства")
    meta = models.JSONField(default=dict, blank=True, verbose_name="Подробности")
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ("-created_at",)
        verbose_name = "Шаг воронки"
        verbose_name_plural = "Шаги воронки"

    def __str__(self):
        return f"{self.name} ({self.device_key[:8]})"


class CryptoInvoice(models.Model):
    """Счёт на оплату криптовалютой: адрес, точная сумма и что по нему пришло.

    Своих узлов и кошельков у нас нет — адрес выдаёт процессор, он же следит
    за сетью и присылает подписанный вебхук. Здесь наша сторона правды:
    сколько ждём, сколько реально пришло и сколько кредитов за это уже
    начислено.

    Ключевое поле — credited_tokens: начисляем всегда ДЕЛЬТУ (положено минус
    уже начислено), поэтому повторный вебхук, ручная перепроверка и сверка по
    расписанию не могут заплатить второй раз, а недоплата с последующей
    доплатой закрывается сама.
    """

    STATUS_WAITING = "waiting"
    STATUS_CONFIRMING = "confirming"
    STATUS_CONFIRMED = "confirmed"
    STATUS_SENDING = "sending"
    STATUS_PARTIALLY_PAID = "partially_paid"
    STATUS_FINISHED = "finished"
    STATUS_FAILED = "failed"
    STATUS_REFUNDED = "refunded"
    STATUS_EXPIRED = "expired"

    STATUS_CHOICES = (
        (STATUS_WAITING, "Ждём перевод"),
        (STATUS_CONFIRMING, "Перевод найден, подтверждается"),
        (STATUS_CONFIRMED, "Подтверждён сетью"),
        (STATUS_SENDING, "Уходит на наш кошелёк"),
        (STATUS_PARTIALLY_PAID, "Пришло меньше суммы"),
        (STATUS_FINISHED, "Оплачен"),
        (STATUS_FAILED, "Не прошёл"),
        (STATUS_REFUNDED, "Возвращён"),
        (STATUS_EXPIRED, "Просрочен"),
    )

    # По этим статусам счёт ещё живой — за ним следит сверка.
    OPEN_STATES = (STATUS_WAITING, STATUS_CONFIRMING, STATUS_CONFIRMED,
                   STATUS_SENDING, STATUS_PARTIALLY_PAID)
    # По этим деньги уже в сети и подтверждены — можно начислять. Намеренно без
    # confirming: там перевод виден, но ещё может не дойти.
    CREDIT_STATES = (STATUS_CONFIRMED, STATUS_SENDING, STATUS_FINISHED,
                     STATUS_PARTIALLY_PAID)

    payment = models.OneToOneField(
        "payments.Payment", on_delete=models.CASCADE, related_name="crypto_invoice",
        verbose_name="Платёж")
    provider = models.CharField(max_length=32, default="nowpayments", db_index=True,
                                verbose_name="Процессор")
    provider_invoice_id = models.CharField(max_length=64, unique=True,
                                           verbose_name="Счёт у процессора")
    status = models.CharField(max_length=24, choices=STATUS_CHOICES,
                              default=STATUS_WAITING, db_index=True,
                              verbose_name="Статус")

    # Цена, зафиксированная в момент создания счёта: человек её увидел и на неё
    # согласился, пересчитывать задним числом нельзя.
    price_amount = models.DecimalField(max_digits=12, decimal_places=2,
                                       verbose_name="Цена")
    price_currency = models.CharField(max_length=8, default="USD",
                                      verbose_name="Валюта цены")

    pay_currency = models.CharField(max_length=24, verbose_name="Код монеты у процессора")
    pay_coin = models.CharField(max_length=16, blank=True, default="", verbose_name="Монета")
    pay_network = models.CharField(max_length=32, blank=True, default="", verbose_name="Сеть")
    pay_address = models.CharField(max_length=160, verbose_name="Адрес перевода")
    # memo/tag: в TON и XRP без него перевод не найти. Пусто — значит не нужен.
    pay_extra_id = models.CharField(max_length=160, blank=True, default="",
                                    verbose_name="Memo / tag")
    pay_amount = models.DecimalField(max_digits=36, decimal_places=18,
                                     verbose_name="Сумма к переводу")
    # Только растёт: процессор может на секунду отдать старое значение, а
    # уменьшение здесь означало бы «часть денег пропала» — такого не бывает.
    actually_paid = models.DecimalField(max_digits=36, decimal_places=18, default=0,
                                        verbose_name="Пришло")
    actually_paid_fiat = models.DecimalField(max_digits=12, decimal_places=2, null=True,
                                             blank=True, verbose_name="Пришло, в валюте цены")
    tx_hash = models.CharField(max_length=160, blank=True, default="",
                               verbose_name="Транзакция")
    confirmations = models.IntegerField(null=True, blank=True, verbose_name="Подтверждений")

    credited_tokens = models.BigIntegerField(default=0, verbose_name="Начислено кредитов")
    credited_paid_amount = models.DecimalField(max_digits=36, decimal_places=18, default=0,
                                               verbose_name="Оплачено на момент начисления")
    credit_events = models.JSONField(default=list, blank=True, verbose_name="Начисления")
    # Ручной разбор: аномальное отношение сумм, переплата сверх потолка, возврат.
    flags = models.JSONField(default=dict, blank=True, verbose_name="Пометки")

    expires_at = models.DateTimeField(null=True, blank=True, db_index=True,
                                      verbose_name="Действителен до")
    last_checked_at = models.DateTimeField(null=True, blank=True, verbose_name="Последняя сверка")
    last_webhook_at = models.DateTimeField(null=True, blank=True, verbose_name="Последний вебхук")
    finalized_at = models.DateTimeField(null=True, blank=True, verbose_name="Закрыт")
    provider_updated_at = models.CharField(max_length=40, blank=True, default="",
                                           verbose_name="Обновлён у процессора")
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("-created_at", "-id")
        indexes = [models.Index(fields=["status", "created_at"])]
        verbose_name = "Криптосчёт"
        verbose_name_plural = "Криптосчета"

    def __str__(self) -> str:
        return f"{self.pay_coin or self.pay_currency} {self.pay_amount} -> {self.status}"

    @property
    def is_open(self) -> bool:
        return self.status in self.OPEN_STATES


class CryptoWebhookEvent(models.Model):
    """Каждый принятый вебхук процессора: защита от повтора и журнал разбора.

    Уникальность event_key — единственная надёжная защита от повторной
    обработки: процессор доставляет уведомления «хотя бы один раз» и при нашем
    5xx повторяет их сам.

    Тело хранится очищенным (без заголовков и подписи) и нужно только для
    разбора инцидентов: суммы и статус мы всё равно перезапрашиваем у
    процессора, телу вебхука не доверяем.
    """
    provider = models.CharField(max_length=32, verbose_name="Процессор")
    provider_invoice_id = models.CharField(max_length=64, db_index=True,
                                           verbose_name="Счёт у процессора")
    event_key = models.CharField(max_length=64, unique=True, verbose_name="Ключ события")
    status = models.CharField(max_length=24, blank=True, default="", verbose_name="Статус")
    actually_paid = models.DecimalField(max_digits=36, decimal_places=18, default=0,
                                        verbose_name="Пришло")
    payload = models.JSONField(default=dict, blank=True, verbose_name="Тело")
    signature_ok = models.BooleanField(default=False, verbose_name="Подпись верна")
    processed = models.BooleanField(default=False, verbose_name="Обработан")
    result = models.CharField(max_length=64, blank=True, default="", verbose_name="Итог")
    received_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ("-received_at", "-id")
        verbose_name = "Вебхук криптоплатежа"
        verbose_name_plural = "Вебхуки криптоплатежей"

    def __str__(self) -> str:
        return f"{self.provider} {self.provider_invoice_id} {self.status}"


class StarInvoice(models.Model):
    """Счёт в Telegram Stars: что выставили боту и что по нему пришло.

    payload — случайный ключ, который Telegram возвращает дословно в
    pre_checkout_query и successful_payment; по нему находим счёт, и угадать
    его нельзя. telegram_payment_charge_id уникален: второй апдейт об одной
    оплате упирается в базу, а не в наше внимание.
    """

    STATUS_CREATED = "created"
    STATUS_PAID = "paid"
    STATUS_REFUNDED = "refunded"
    STATUS_FAILED = "failed"
    STATUS_EXPIRED = "expired"
    STATUS_CHOICES = (
        (STATUS_CREATED, "Выставлен"),
        (STATUS_PAID, "Оплачен"),
        (STATUS_REFUNDED, "Возвращён"),
        (STATUS_FAILED, "Не сошёлся"),
        (STATUS_EXPIRED, "Просрочен"),
    )

    payment = models.OneToOneField(
        "payments.Payment", on_delete=models.CASCADE, related_name="star_invoice",
        verbose_name="Платёж")
    telegram_id = models.BigIntegerField(db_index=True, verbose_name="Telegram ID покупателя")
    payload = models.CharField(max_length=64, unique=True, verbose_name="Ключ счёта")
    package_id = models.PositiveIntegerField(verbose_name="Пакет")
    package_name = models.CharField(max_length=100, blank=True, default="", verbose_name="Название пакета")
    tokens = models.BigIntegerField(default=0, verbose_name="Кредитов")
    bonus_tokens = models.BigIntegerField(default=0, verbose_name="Бонусных кредитов")
    stars_amount = models.PositiveIntegerField(verbose_name="Сумма, Stars")
    status = models.CharField(max_length=12, choices=STATUS_CHOICES, default=STATUS_CREATED,
                              db_index=True, verbose_name="Статус")
    expires_at = models.DateTimeField(db_index=True, verbose_name="Действителен до")
    invoice_message_id = models.BigIntegerField(null=True, blank=True,
                                                verbose_name="Сообщение со счётом")
    telegram_payment_charge_id = models.CharField(
        max_length=128, unique=True, null=True, blank=True,
        verbose_name="Идентификатор оплаты в Telegram")
    provider_payment_charge_id = models.CharField(max_length=128, blank=True, default="")
    paid_at = models.DateTimeField(null=True, blank=True, verbose_name="Оплачен")
    refunded_at = models.DateTimeField(null=True, blank=True, verbose_name="Возвращён")
    refund_reason = models.CharField(max_length=120, blank=True, default="",
                                     verbose_name="Причина возврата")
    refund_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="+", verbose_name="Кто вернул")
    raw = models.JSONField(default=dict, blank=True, verbose_name="Данные апдейта")
    flags = models.JSONField(default=dict, blank=True, verbose_name="Пометки")
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("-created_at", "-id")
        indexes = [models.Index(fields=["status", "created_at"])]
        verbose_name = "Счёт в Stars"
        verbose_name_plural = "Счета в Stars"

    def __str__(self) -> str:
        return f"{self.stars_amount} ⭐ за {self.tokens + self.bonus_tokens} кр → {self.status}"

    @property
    def total_tokens(self) -> int:
        return int(self.tokens or 0) + int(self.bonus_tokens or 0)


class GoPayInvoice(models.Model):
    """Счёт единого QR (GoPay): что показываем человеку и что знаем об оплате.

    Состояние живёт здесь, а не в Payment.response: по нему ищут «открытые счета
    этого покупателя», «что сверять» и «счёт заказа X» — это индексы, а не пути
    внутри JSON. Строка помнит и среду (test/live), в которой счёт создан:
    статус спрашивают той же парой ключей, даже если среду потом переключили.

    Менять строку вправе только payments.gopay.service — там же блокировки.
    """

    STATUS_CREATED, STATUS_PENDING, STATUS_COMMITTED = "created", "pending", "committed"
    STATUS_FAILED, STATUS_EXPIRED, STATUS_CANCELLED = "failed", "expired", "cancelled"
    STATUS_CHOICES = ((STATUS_CREATED, "Ждём оплату"), (STATUS_PENDING, "Банк обрабатывает"),
                      (STATUS_COMMITTED, "Оплачен"), (STATUS_FAILED, "Не прошёл"),
                      (STATUS_EXPIRED, "Просрочен"), (STATUS_CANCELLED, "Отменён"))
    # Счёт ещё может быть оплачен — за ним следит сверка.
    OPEN_STATES = (STATUS_CREATED, STATUS_PENDING)
    # Закрыт без денег. «Оплачен» сюда не входит и побеждает любой из них.
    CLOSED_UNPAID = (STATUS_FAILED, STATUS_EXPIRED, STATUS_CANCELLED)
    ENV_CHOICES = (("test", "Тест"), ("live", "Боевой"))

    payment = models.OneToOneField(
        "payments.Payment", on_delete=models.CASCADE, related_name="gopay_invoice",
        verbose_name="Платёж")
    env = models.CharField(max_length=4, choices=ENV_CHOICES, verbose_name="Среда")
    provider_payment_id = models.CharField(max_length=64, unique=True,
                                           verbose_name="Платёж в GoPay")
    status = models.CharField(max_length=12, choices=STATUS_CHOICES, default=STATUS_CREATED,
                              db_index=True, verbose_name="Статус")
    amount = models.DecimalField(max_digits=12, decimal_places=2, verbose_name="Сумма, сом")
    lifetime_seconds = models.PositiveIntegerField(verbose_name="Срок жизни, сек")
    # Пусто бывает только у тестового счёта: тестовый QR не предназначен для оплаты.
    qr_data = models.TextField(blank=True, default="", verbose_name="Содержимое QR")
    qr_url = models.CharField(max_length=500, blank=True, default="", verbose_name="Картинка QR")
    checkout_url = models.CharField(max_length=500, blank=True, default="",
                                    verbose_name="Страница оплаты GoPay")
    app_links = models.JSONField(default=dict, blank=True, verbose_name="Ссылки в банки")
    # НАШ срок: момент перед запросом создания плюс срок жизни. Время GoPay
    # приходит без часового пояса и хранится ниже только для справки.
    expires_at = models.DateTimeField(db_index=True, verbose_name="Действителен до")
    provider_expires_at = models.CharField(max_length=40, blank=True, default="",
                                           verbose_name="Срок по данным GoPay")
    committed_at = models.DateTimeField(null=True, blank=True, verbose_name="Оплачен")
    bank_op_date = models.DateField(null=True, blank=True,
                                    verbose_name="Операционный день банка")
    receipt_url = models.CharField(max_length=500, blank=True, default="", verbose_name="Чек")
    # Заполнено — у покупателя этого QR больше нет: отменён или оставлен.
    cancel_requested_at = models.DateTimeField(null=True, blank=True,
                                               verbose_name="Отмена запрошена")
    last_checked_at = models.DateTimeField(null=True, blank=True, verbose_name="Последняя сверка")
    last_webhook_at = models.DateTimeField(null=True, blank=True, verbose_name="Последний вебхук")
    finalized_at = models.DateTimeField(null=True, blank=True, verbose_name="Закрыт")
    flags = models.JSONField(default=dict, blank=True, verbose_name="Пометки")
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("-created_at", "-id")
        indexes = [models.Index(fields=["status", "created_at"]),
                   models.Index(fields=["status", "expires_at"])]
        verbose_name = "Счёт единого QR (GoPay)"
        verbose_name_plural = "Счета единого QR (GoPay)"

    def __str__(self) -> str:
        return f"{self.amount} сом ({self.env}) -> {self.status}"

    @property
    def is_open(self) -> bool:
        return self.status in self.OPEN_STATES


class GoPayWebhookEvent(models.Model):
    """Журнал подписанных событий GoPay — дневник для разбора, а не защита денег.

    Номера события у GoPay нет, поэтому ключ собираем сами. От повторной
    доставки деньги защищает идемпотентное начисление, а не эта таблица.
    Тело хранится очищенным: только поля из белого списка, без заголовков.
    """
    event_key = models.CharField(max_length=64, unique=True, verbose_name="Ключ события")
    event = models.CharField(max_length=48, db_index=True, verbose_name="Событие")
    provider_payment_id = models.CharField(max_length=64, blank=True, default="",
                                           db_index=True, verbose_name="Платёж в GoPay")
    order_id = models.CharField(max_length=64, blank=True, default="", db_index=True,
                                verbose_name="Заказ")
    status = models.CharField(max_length=32, blank=True, default="", verbose_name="Статус")
    amount = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True,
                                 verbose_name="Сумма")
    testing_mode = models.BooleanField(default=False, verbose_name="Тестовый")
    payload = models.JSONField(default=dict, blank=True, verbose_name="Тело")
    processed = models.BooleanField(default=False, verbose_name="Обработан")
    result = models.CharField(max_length=64, blank=True, default="", verbose_name="Итог")
    received_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ("-received_at", "-id")
        verbose_name = "Вебхук GoPay"
        verbose_name_plural = "Вебхуки GoPay"

    def __str__(self) -> str:
        return f"{self.event} {self.order_id} {self.status}"
