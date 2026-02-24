from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("mails", "0001_initial"),
    ]

    operations = [
        migrations.AlterModelOptions(
            name="mailcontext",
            options={
                "ordering": ["-updated_at", "id"],
                "verbose_name": "Почтовый контекст",
                "verbose_name_plural": "Почтовые контексты",
            },
        ),
        migrations.AlterModelOptions(
            name="simplemail",
            options={
                "ordering": ["-created_at", "id"],
                "verbose_name": "Простое письмо",
                "verbose_name_plural": "Простые письма",
            },
        ),
    ]
