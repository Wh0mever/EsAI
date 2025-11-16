from django.db import models
from django.conf import settings


class PaymentLog(models.Model):
    """Audit record for executed payment attempts via providers (FreedomPay).

    Stores minimal required fields: user, amount, date, and provider response (JSON).
    """

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
    provider = models.CharField(max_length=32, choices=PROVIDER_CHOICES, default="freedompay")
    amount = models.IntegerField()
    currency = models.CharField(max_length=10, default="KGS")
    order_id = models.CharField(max_length=64, blank=True, null=True, db_index=True)
    description = models.CharField(max_length=255, blank=True, null=True)
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

    def __str__(self) -> str:
        return f"[{self.created_at:%Y-%m-%d %H:%M}] {self.provider} {self.amount} {self.currency} -> {'OK' if self.success else 'FAIL'}"
