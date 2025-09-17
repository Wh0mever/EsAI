from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("plans", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="plan",
            name="chat_output_tokens_limit",
            field=models.PositiveIntegerField(null=True, blank=True),
        ),
    ]

