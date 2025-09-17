from django.db import migrations, models
import django.db.models.deletion
from django.conf import settings


class Migration(migrations.Migration):

    dependencies = [
        ("mails", "0004_emailcampaign_emaillog_emailpreference_emailtemplate_and_more"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="MailContext",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("name", models.CharField(max_length=200)),
                ("data", models.JSONField(blank=True, default=dict, help_text="JSON-контекст. Правила рендера: каждый ключ — новая строка.\nЕсли в ключе есть 'title' — строка становится заголовком.\nЕсли в ключе есть 'link' — значение объект {href, text}.\nЕсли в ключе есть 'list' — значение список или объект элементов.\nПорядок вывода соответствует порядку ключей.")),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={"ordering": ["-updated_at", "id"]},
        ),
        migrations.CreateModel(
            name="SimpleMail",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("name", models.CharField(help_text="Внутреннее имя рассылки", max_length=200)),
                ("subject", models.CharField(max_length=255)),
                ("send_to_all", models.BooleanField(default=False, help_text="Отправить всем активным пользователям")),
                ("recipients_text", models.TextField(blank=True, default="", help_text="Список email, по одному на строку. Используется, если 'Отправить всем' не отмечено.")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("last_sent_at", models.DateTimeField(blank=True, null=True)),
                ("context", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="mails", to="mails.mailcontext")),
            ],
            options={"ordering": ["-created_at", "id"]},
        ),
    ]

