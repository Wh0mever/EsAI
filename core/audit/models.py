from django.conf import settings
from django.db import models


class EventType(models.TextChoices):
    ERROR_OPENROUTER = "error_openrouter", "Ошибка OpenRouter"
    ERROR_FREEDOMPAY = "error_freedompay", "Ошибка FreedomPay"
    ERROR_SERVER = "error_server", "Ошибка сервера"
    LOGIN = "login", "Вход"
    PAYMENT = "payment", "Оплата"
    MODEL_USAGE = "model_usage", "Использование модели"
    TOKEN_SPEND = "token_spend", "Списание токенов"
    OTHER = "other", "Другое"


class EventLevel(models.TextChoices):
    INFO = "info", "Info"
    WARNING = "warning", "Warning"
    ERROR = "error", "Error"


class EventLog(models.Model):
    """Централизованный журнал событий системы (ТЗ 9/18).

    Append-only: пишется через audit.services.log_event, не редактируется
    из админки. Используется и как источник метрик дашборда.
    """

    type = models.CharField(
        max_length=32,
        choices=EventType.choices,
        default=EventType.OTHER,
        db_index=True,
        verbose_name="Тип события",
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="event_logs",
        verbose_name="Пользователь",
    )
    message = models.TextField(blank=True, verbose_name="Сообщение")
    meta = models.JSONField(null=True, blank=True, verbose_name="Метаданные")
    level = models.CharField(
        max_length=10,
        choices=EventLevel.choices,
        default=EventLevel.INFO,
        verbose_name="Уровень",
    )
    created_at = models.DateTimeField(
        auto_now_add=True, db_index=True, verbose_name="Создано"
    )

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["type", "created_at"]),
            models.Index(fields=["created_at"]),
        ]
        verbose_name = "Событие (лог)"
        verbose_name_plural = "События (логи)"

    def __str__(self) -> str:
        return f"[{self.created_at:%Y-%m-%d %H:%M}] {self.type} ({self.level})"


class SignupDevice(models.Model):
    """Слепок сессии регистрации/входа (антифрод v1, ТЗ 4.3).

    Пишется при создании нового аккаунта (email-OTP/соц-вход). По набору
    записей за окно 24ч считаем многоаккаунтность с одного устройства/IP,
    чтобы притормозить выдачу welcome-бонуса фейкам.
    """

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="signup_devices",
        verbose_name="Пользователь",
    )
    ip = models.GenericIPAddressField(null=True, blank=True, verbose_name="IP-адрес")
    subnet = models.CharField(
        max_length=64,
        blank=True,
        verbose_name="Подсеть (/24)",
    )
    user_agent = models.TextField(blank=True, verbose_name="User-Agent")
    fingerprint = models.CharField(
        max_length=128,
        blank=True,
        db_index=True,
        verbose_name="Отпечаток устройства",
    )
    created_at = models.DateTimeField(
        auto_now_add=True, db_index=True, verbose_name="Создано"
    )

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["ip"]),
            models.Index(fields=["created_at"]),
            # Антифрод-проверка (users/antifraud.py::decide_welcome_bonus) фильтрует
            # именно по этой паре на каждой регистрации — составной индекс покрывает
            # запрос целиком вместо range-scan по created_at + фильтрации без индекса.
            models.Index(fields=["fingerprint", "created_at"]),
        ]
        verbose_name = "Слепок устройства (регистрация)"
        verbose_name_plural = "Слепки устройств (регистрация)"

    def __str__(self) -> str:
        return f"[{self.created_at:%Y-%m-%d %H:%M}] {self.ip or '-'} ({self.subnet or '-'})"


class PendingBonusStatus(models.TextChoices):
    PENDING = "pending", "Ожидает"
    APPROVED = "approved", "Начислен"
    REJECTED = "rejected", "Отклонён"


class PendingBonus(models.Model):
    """Отложенный welcome-бонус (антифрод v1, ТЗ 4.3).

    Когда регистрация выглядит подозрительной (многоаккаунтность с одного
    IP/подсети/устройства), бонус не выдаётся сразу, а кладётся в очередь на
    24ч. Позже крон (users.tasks.process_pending_bonuses) начисляет его, если
    запись всё ещё в статусе pending и наступило available_at.
    """

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="pending_bonuses",
        verbose_name="Пользователь",
    )
    amount = models.BigIntegerField(verbose_name="Сумма (токены)")
    reason = models.CharField(
        max_length=32,
        default="welcome",
        verbose_name="Причина",
    )
    status = models.CharField(
        max_length=16,
        choices=PendingBonusStatus.choices,
        default=PendingBonusStatus.PENDING,
        db_index=True,
        verbose_name="Статус",
    )
    available_at = models.DateTimeField(verbose_name="Доступно с")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="Создано")
    decided_at = models.DateTimeField(null=True, blank=True, verbose_name="Решено")
    ip = models.GenericIPAddressField(null=True, blank=True, verbose_name="IP-адрес")
    meta = models.JSONField(null=True, blank=True, verbose_name="Метаданные")

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "Отложенный бонус"
        verbose_name_plural = "Отложенные бонусы"
        constraints = [
            # Идемпотентность welcome-бонуса (#35): не больше одной записи на
            # (пользователь, причина). Реально reason всегда 'welcome'. Делает
            # get_or_create в antifraud гонко-безопасным (ловит IntegrityError).
            models.UniqueConstraint(
                fields=["user", "reason"], name="uniq_pendingbonus_user_reason"
            ),
        ]

    def __str__(self) -> str:
        return f"PendingBonus(user={self.user_id}, {self.amount}, {self.status})"
