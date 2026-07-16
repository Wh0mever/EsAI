import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models
import django.db.models.expressions
import django.db.models.query_utils


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("payments", "0001_initial"),
        ("plans", "0017_promo_and_reasons"),
    ]

    operations = [
        migrations.CreateModel(
            name="ExitDiscountOffer",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("device_key", models.CharField(blank=True, db_index=True, default="", max_length=64, verbose_name="Device key", help_text="localStorage UUID для гостя (не авторизован).")),
                ("ip_address", models.GenericIPAddressField(blank=True, null=True, verbose_name="IP-адрес", help_text="Только для аудита/статистики. НЕ используется как ключ блокировки повторного показа (CGNAT).")),
                ("shown_at", models.DateTimeField(blank=True, null=True, verbose_name="Показан")),
                ("expires_at", models.DateTimeField(blank=True, null=True, verbose_name="Истекает")),
                ("percent", models.PositiveSmallIntegerField(blank=True, null=True, verbose_name="Процент скидки", help_text="Зафиксирован на момент показа оффера.")),
                ("claimed_at", models.DateTimeField(blank=True, null=True, verbose_name="Принят пользователем")),
                ("dismissed_at", models.DateTimeField(blank=True, null=True, verbose_name="Отклонён", help_text="Аналитика явного отказа (крестик/«Нет спасибо»). НЕ гейт повторного показа — гейт это shown_at.")),
                ("redeemed_at", models.DateTimeField(blank=True, null=True, verbose_name="Погашен", help_text="Когда скидка реально применилась к успешно оплаченному платежу.")),
                ("created_at", models.DateTimeField(auto_now_add=True, verbose_name="Создан")),
                ("applied_to_payment", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="exit_discount_offer", to="payments.payment", verbose_name="Применён к платежу")),
                ("user", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="exit_discount_offers", to=settings.AUTH_USER_MODEL, verbose_name="Пользователь")),
            ],
            options={
                "verbose_name": "Оффер скидки при уходе",
                "verbose_name_plural": "Офферы скидки при уходе",
            },
        ),
        migrations.AddConstraint(
            model_name="exitdiscountoffer",
            constraint=models.UniqueConstraint(condition=django.db.models.query_utils.Q(("user__isnull", False)), fields=("user",), name="uniq_exit_discount_user"),
        ),
        migrations.AddConstraint(
            model_name="exitdiscountoffer",
            constraint=models.UniqueConstraint(condition=~django.db.models.query_utils.Q(("device_key", "")), fields=("device_key",), name="uniq_exit_discount_device"),
        ),
    ]
