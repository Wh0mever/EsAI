from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("audit", "0004_rename_audit_signu_ip_3d6f2a_idx_audit_signu_ip_95d93f_idx_and_more"),
    ]

    operations = [
        migrations.AddConstraint(
            model_name="pendingbonus",
            constraint=models.UniqueConstraint(
                fields=["user", "reason"], name="uniq_pendingbonus_user_reason"
            ),
        ),
    ]
