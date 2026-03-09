from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("plans", "0004_remove_plan_duration_days"),
    ]

    operations = [
        migrations.AddField(
            model_name="plan",
            name="mp4_enabled",
            field=models.BooleanField(default=False),
        ),
    ]

