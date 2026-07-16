from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("ai", "0013_gptmodels_free_tier_and_fara_rates"),
    ]

    operations = [
        migrations.AddField(
            model_name="aichatsession",
            name="context_summary",
            field=models.TextField(blank=True, default=""),
        ),
        migrations.AddField(
            model_name="aichatsession",
            name="summary_upto_message_id",
            field=models.BigIntegerField(blank=True, null=True),
        ),
    ]
