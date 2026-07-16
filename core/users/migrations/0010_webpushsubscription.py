from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("users", "0009_user_avatar_url"),
    ]

    operations = [
        migrations.CreateModel(
            name="WebPushSubscription",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("endpoint", models.TextField(unique=True, verbose_name="Endpoint")),
                ("p256dh", models.CharField(max_length=255, verbose_name="Ключ p256dh")),
                ("auth", models.CharField(max_length=255, verbose_name="Ключ auth")),
                ("user_agent", models.CharField(blank=True, max_length=300, verbose_name="User-Agent")),
                ("created_at", models.DateTimeField(auto_now_add=True, verbose_name="Создана")),
                ("last_ok_at", models.DateTimeField(null=True, verbose_name="Последняя успешная доставка")),
                (
                    "user",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="push_subs",
                        to=settings.AUTH_USER_MODEL,
                        verbose_name="Пользователь",
                    ),
                ),
            ],
            options={
                "verbose_name": "Web Push подписка",
                "verbose_name_plural": "Web Push подписки",
                "ordering": ["-created_at"],
            },
        ),
    ]
