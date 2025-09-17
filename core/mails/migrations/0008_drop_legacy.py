from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("mails", "0007_simple_mail"),
    ]

    operations = [
        migrations.DeleteModel(name="EmailLog"),
        migrations.DeleteModel(name="EmailCampaign"),
        migrations.DeleteModel(name="EmailPreference"),
        migrations.DeleteModel(name="EmailTemplate"),
    ]

