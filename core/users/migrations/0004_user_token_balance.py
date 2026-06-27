from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("users", "0003_zero_default_user_bonuses"),
    ]

    operations = [
        migrations.AddField(
            model_name="user",
            name="token_balance",
            field=models.BigIntegerField(default=0, verbose_name="Баланс токенов"),
        ),
    ]
