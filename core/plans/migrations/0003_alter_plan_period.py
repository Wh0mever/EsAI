from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("plans", "0002_subscription_grace_and_issue"),
    ]

    operations = [
        migrations.AlterField(
            model_name="plan",
            name="period",
            field=models.CharField(
                choices=[("weekly", "Неделя"), ("monthly", "Месяц"), ("yearly", "Год")],
                max_length=10,
            ),
        ),
    ]

