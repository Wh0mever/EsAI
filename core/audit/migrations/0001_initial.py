import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="EventLog",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                (
                    "type",
                    models.CharField(
                        choices=[
                            ("error_openrouter", "Ошибка OpenRouter"),
                            ("error_freedompay", "Ошибка FreedomPay"),
                            ("error_server", "Ошибка сервера"),
                            ("login", "Вход"),
                            ("payment", "Оплата"),
                            ("model_usage", "Использование модели"),
                            ("token_spend", "Списание токенов"),
                            ("other", "Другое"),
                        ],
                        db_index=True,
                        default="other",
                        max_length=32,
                        verbose_name="Тип события",
                    ),
                ),
                ("message", models.TextField(blank=True, verbose_name="Сообщение")),
                ("meta", models.JSONField(blank=True, null=True, verbose_name="Метаданные")),
                (
                    "level",
                    models.CharField(
                        choices=[("info", "Info"), ("warning", "Warning"), ("error", "Error")],
                        default="info",
                        max_length=10,
                        verbose_name="Уровень",
                    ),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True, db_index=True, verbose_name="Создано")),
                (
                    "user",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="event_logs",
                        to=settings.AUTH_USER_MODEL,
                        verbose_name="Пользователь",
                    ),
                ),
            ],
            options={
                "verbose_name": "Событие (лог)",
                "verbose_name_plural": "События (логи)",
                "ordering": ["-created_at"],
            },
        ),
        migrations.AddIndex(
            model_name="eventlog",
            index=models.Index(fields=["type", "created_at"], name="audit_event_type_4f1f9d_idx"),
        ),
        migrations.AddIndex(
            model_name="eventlog",
            index=models.Index(fields=["created_at"], name="audit_event_created_8c2a1b_idx"),
        ),
    ]
