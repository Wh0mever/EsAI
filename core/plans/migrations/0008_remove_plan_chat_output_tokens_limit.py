from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("plans", "0007_remove_plan_unused_feature_flags"),
    ]

    operations = [
        migrations.RemoveField(
            model_name="plan",
            name="chat_output_tokens_limit",
        ),
    ]

