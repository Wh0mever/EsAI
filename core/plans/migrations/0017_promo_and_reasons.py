from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("plans", "0016_tokenpackage_badge_featured_marketing"),
    ]

    operations = [
        migrations.AlterField(
            model_name="tokentransaction",
            name="reason",
            field=models.CharField(
                choices=[
                    ("chat", "Списание за чат"),
                    ("purchase", "Покупка пакета"),
                    ("admin", "Ручная корректировка"),
                    ("bonus", "Бонус"),
                    ("welcome", "Приветственный бонус"),
                    ("daily_bonus", "Ежедневный бонус"),
                    ("refund", "Возврат"),
                    ("referral", "Реферальное начисление"),
                    ("transfer_in", "Перевод получен"),
                    ("transfer_out", "Перевод отправлен"),
                    ("promo", "Промокод"),
                ],
                max_length=20,
                verbose_name="Причина",
            ),
        ),
        migrations.CreateModel(
            name="PromoCode",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("code", models.CharField(max_length=40, unique=True, verbose_name="Код")),
                ("bonus_credits", models.PositiveIntegerField(verbose_name="Кредитов")),
                ("expires_at", models.DateTimeField(blank=True, null=True, verbose_name="Истекает")),
                ("max_activations", models.PositiveIntegerField(blank=True, help_text="Пусто — безлимит.", null=True, verbose_name="Максимум активаций")),
                ("used_count", models.PositiveIntegerField(default=0, verbose_name="Использовано раз")),
                ("per_user_once", models.BooleanField(default=True, verbose_name="Один раз на пользователя")),
                ("new_users_only", models.BooleanField(default=False, verbose_name="Только для новых пользователей")),
                ("is_active", models.BooleanField(default=True, verbose_name="Активен")),
                ("created_at", models.DateTimeField(auto_now_add=True, verbose_name="Создан")),
                ("note", models.CharField(blank=True, max_length=200, verbose_name="Заметка")),
            ],
            options={
                "verbose_name": "Промокод",
                "verbose_name_plural": "Промокоды",
                "ordering": ["-created_at"],
            },
        ),
        migrations.CreateModel(
            name="PromoActivation",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("credited", models.PositiveIntegerField(verbose_name="Начислено кредитов")),
                ("created_at", models.DateTimeField(auto_now_add=True, verbose_name="Создано")),
                (
                    "promo",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="activations",
                        to="plans.promocode",
                        verbose_name="Промокод",
                    ),
                ),
                (
                    "user",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="promo_activations",
                        to=settings.AUTH_USER_MODEL,
                        verbose_name="Пользователь",
                    ),
                ),
            ],
            options={
                "verbose_name": "Активация промокода",
                "verbose_name_plural": "Активации промокодов",
                "ordering": ["-created_at"],
                "unique_together": {("promo", "user")},
            },
        ),
    ]
