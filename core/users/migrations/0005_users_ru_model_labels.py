from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("users", "0004_user_auto_renew"),
    ]

    operations = [
        migrations.AlterModelOptions(
            name="user",
            options={"verbose_name": "Пользователь", "verbose_name_plural": "Пользователи"},
        ),
        migrations.AlterModelOptions(
            name="usercardbind",
            options={
                "ordering": ["-created_at"],
                "verbose_name": "Привязка карты пользователя",
                "verbose_name_plural": "Привязки карт пользователей",
            },
        ),
        migrations.AlterModelOptions(
            name="userquestions",
            options={
                "ordering": ["-created_at"],
                "verbose_name": "Вопрос пользователя",
                "verbose_name_plural": "Вопросы пользователей",
            },
        ),
        migrations.AlterModelOptions(
            name="notification",
            options={"ordering": ["-created_at"], "verbose_name": "Уведомление", "verbose_name_plural": "Уведомления"},
        ),
        migrations.AlterModelOptions(
            name="notificationdelivery",
            options={
                "ordering": ["-assigned_at"],
                "verbose_name": "Доставка уведомления",
                "verbose_name_plural": "Доставки уведомлений",
            },
        ),
    ]
