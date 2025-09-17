from django.db import migrations, models
import django.db.models.deletion
from django.conf import settings


class Migration(migrations.Migration):

    dependencies = [
        ("users", "0005_user_bonus_images_user_bonus_music_user_bonus_songs_and_more"),
    ]

    operations = [
        migrations.RemoveField(
            model_name="notification",
            name="recipient",
        ),
        migrations.RemoveField(
            model_name="notification",
            name="is_read",
        ),
        migrations.RemoveField(
            model_name="notification",
            name="read_at",
        ),
        migrations.CreateModel(
            name="NotificationDelivery",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("is_read", models.BooleanField(default=False)),
                ("assigned_at", models.DateTimeField(auto_now_add=True)),
                ("read_at", models.DateTimeField(blank=True, null=True)),
                ("notification", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="deliveries", to="users.notification")),
                ("recipient", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="notification_deliveries", to=settings.AUTH_USER_MODEL)),
            ],
            options={
                "ordering": ["-assigned_at"],
            },
        ),
        migrations.AddField(
            model_name="notification",
            name="recipients",
            field=models.ManyToManyField(blank=True, related_name="notifications_received", through="users.NotificationDelivery", to=settings.AUTH_USER_MODEL),
        ),
        migrations.AlterUniqueTogether(
            name="notificationdelivery",
            unique_together={("notification", "recipient")},
        ),
    ]

