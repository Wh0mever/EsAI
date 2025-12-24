from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("plans", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="usersubscription",
            name="auto_renew",
            field=models.BooleanField(default=True),
        ),
    ]
