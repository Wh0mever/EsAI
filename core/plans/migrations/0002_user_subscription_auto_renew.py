from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("plans", "0001_initial"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            database_operations=[
                migrations.RunSQL(
                    sql=(
                        "ALTER TABLE plans_usersubscription "
                        "ADD COLUMN IF NOT EXISTS auto_renew boolean DEFAULT true"
                    ),
                    reverse_sql=(
                        "ALTER TABLE plans_usersubscription "
                        "DROP COLUMN IF EXISTS auto_renew"
                    ),
                )
            ],
            state_operations=[
                migrations.AddField(
                    model_name="usersubscription",
                    name="auto_renew",
                    field=models.BooleanField(default=True),
                )
            ],
        ),
    ]
