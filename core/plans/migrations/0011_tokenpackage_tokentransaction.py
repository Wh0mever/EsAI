import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("plans", "0010_remove_plan_topmedia_engine"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="TokenPackage",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("name", models.CharField(max_length=100, verbose_name="Название")),
                ("tokens", models.BigIntegerField(verbose_name="Токенов")),
                ("bonus_tokens", models.BigIntegerField(default=0, verbose_name="Бонусных токенов")),
                ("price", models.DecimalField(decimal_places=2, max_digits=12, verbose_name="Цена")),
                ("currency", models.CharField(default="KGS", max_length=10, verbose_name="Валюта")),
                ("is_active", models.BooleanField(default=True, verbose_name="Активен")),
                ("sort_order", models.PositiveIntegerField(default=100, verbose_name="Порядок сортировки")),
                ("description", models.TextField(blank=True, verbose_name="Описание")),
            ],
            options={
                "verbose_name": "Пакет токенов",
                "verbose_name_plural": "Пакеты токенов",
                "ordering": ["sort_order", "id"],
            },
        ),
        migrations.CreateModel(
            name="TokenTransaction",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("delta", models.BigIntegerField(verbose_name="Изменение")),
                (
                    "reason",
                    models.CharField(
                        choices=[
                            ("chat", "Списание за чат"),
                            ("purchase", "Покупка пакета"),
                            ("admin", "Ручная корректировка"),
                            ("bonus", "Бонус"),
                            ("refund", "Возврат"),
                        ],
                        max_length=20,
                        verbose_name="Причина",
                    ),
                ),
                ("balance_after", models.BigIntegerField(verbose_name="Баланс после")),
                ("created_at", models.DateTimeField(auto_now_add=True, db_index=True, verbose_name="Создано")),
                ("meta", models.JSONField(blank=True, null=True, verbose_name="Метаданные")),
                (
                    "user",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="token_transactions",
                        to=settings.AUTH_USER_MODEL,
                        verbose_name="Пользователь",
                    ),
                ),
            ],
            options={
                "verbose_name": "Транзакция токенов",
                "verbose_name_plural": "Транзакции токенов",
                "ordering": ["-created_at"],
            },
        ),
    ]
