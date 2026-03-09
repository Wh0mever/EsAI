from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("plans", "0005_plan_mp4_enabled"),
    ]

    operations = [
        migrations.RemoveField(
            model_name="plan",
            name="ai_templates_limit",
        ),
        migrations.RemoveField(
            model_name="plan",
            name="operations_per_month_limit",
        ),
        migrations.RemoveField(
            model_name="plan",
            name="covers_limit",
        ),
    ]

