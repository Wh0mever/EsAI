from django.db import models
from django.conf import settings


class Payment(models.Model):

    PROVIDER_CHOICES = (
        ("freedompay", "FreedomPay"),
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
    NAMES = ("pricing_view", "topup_click", "studio_view", "studio_scene_add")

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
