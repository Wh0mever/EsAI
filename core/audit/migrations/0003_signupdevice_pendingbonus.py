import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("audit", "0002_rename_audit_event_type_4f1f9d_idx_audit_event_type_4e6167_idx_and_more"),
        ("users", "0004_user_token_balance"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="SignupDevice",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("ip", models.GenericIPAddressField(blank=True, null=True, verbose_name="IP-адрес")),
                ("subnet", models.CharField(blank=True, max_length=64, verbose_name="Подсеть (/24)")),
                ("user_agent", models.TextField(blank=True, verbose_name="User-Agent")),
                ("fingerprint", models.CharField(blank=True, max_length=128, verbose_name="Отпечаток устройства")),
                ("created_at", models.DateTimeField(auto_now_add=True, db_index=True, verbose_name="Создано")),
                (
                    "user",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="signup_devices",
                        to=settings.AUTH_USER_MODEL,
                        verbose_name="Пользователь",
                    ),
                ),
            ],
            options={
                "verbose_name": "Слепок устройства (регистрация)",
                "verbose_name_plural": "Слепки устройств (регистрация)",
                "ordering": ["-created_at"],
            },
        ),
        migrations.CreateModel(
            name="PendingBonus",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("amount", models.BigIntegerField(verbose_name="Сумма (токены)")),
                ("reason", models.CharField(default="welcome", max_length=32, verbose_name="Причина")),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("pending", "Ожидает"),
                            ("approved", "Начислен"),
                            ("rejected", "Отклонён"),
                        ],
                        db_index=True,
                        default="pending",
                        max_length=16,
                        verbose_name="Статус",
                    ),
                ),
                ("available_at", models.DateTimeField(verbose_name="Доступно с")),
                ("created_at", models.DateTimeField(auto_now_add=True, verbose_name="Создано")),
                ("decided_at", models.DateTimeField(blank=True, null=True, verbose_name="Решено")),
                ("ip", models.GenericIPAddressField(blank=True, null=True, verbose_name="IP-адрес")),
                ("meta", models.JSONField(blank=True, null=True, verbose_name="Метаданные")),
                (
                    "user",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="pending_bonuses",
                        to=settings.AUTH_USER_MODEL,
                        verbose_name="Пользователь",
                    ),
                ),
            ],
            options={
                "verbose_name": "Отложенный бонус",
                "verbose_name_plural": "Отложенные бонусы",
                "ordering": ["-created_at"],
            },
        ),
        migrations.AddIndex(
            model_name="signupdevice",
            index=models.Index(fields=["ip"], name="audit_signu_ip_3d6f2a_idx"),
        ),
        migrations.AddIndex(
            model_name="signupdevice",
            index=models.Index(fields=["created_at"], name="audit_signu_created_7b1e9c_idx"),
        ),
    ]
