from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("users", "0007_user_is_unlimited"),
    ]

    operations = [
        migrations.AddConstraint(
            model_name="usercardbind",
            constraint=models.UniqueConstraint(
                fields=["user", "card_token"], name="uniq_usercardbind_user_token"
            ),
        ),
    ]
