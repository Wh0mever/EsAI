from django.db import migrations, models
from django.conf import settings


class Migration(migrations.Migration):

    dependencies = [
        ("mails", "0008_drop_legacy"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField(
            model_name="simplemail",
            name="recipients",
            field=models.ManyToManyField(blank=True, help_text="Выберите конкретных пользователей для отправки (используется, если не включено 'Отправить всем').", related_name="simple_mail_recipients", to=settings.AUTH_USER_MODEL),
        ),
        # Optionally, you could remove recipients_text in a later migration.
    ]

