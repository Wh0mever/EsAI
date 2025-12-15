from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("users", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="user",
            name="free_plan_activated",
            field=models.BooleanField(default=False, verbose_name="Бесплатный тариф активирован"),
        ),
    ]
