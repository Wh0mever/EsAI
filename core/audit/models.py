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
