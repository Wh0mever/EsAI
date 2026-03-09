from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("plans", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="usersubscription",
            name="billing_issue_code",
            field=models.CharField(blank=True, default="", max_length=32),
        ),
        migrations.AddField(
            model_name="usersubscription",
            name="grace_until",
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]

