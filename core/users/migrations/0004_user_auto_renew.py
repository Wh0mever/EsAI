from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("users", "0003_user_selected_currency"),
    ]

    operations = [
        migrations.AddField(
            model_name="user",
            name="auto_renew",
            field=models.BooleanField(default=True, verbose_name="Автосписание"),
        ),
    ]
