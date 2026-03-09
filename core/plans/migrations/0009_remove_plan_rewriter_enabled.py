from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("plans", "0008_remove_plan_chat_output_tokens_limit"),
    ]

    operations = [
        migrations.RemoveField(
            model_name="plan",
            name="rewriter_enabled",
        ),
    ]

