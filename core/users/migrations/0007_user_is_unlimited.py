from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("users", "0006_user_memory_enabled_usermemory"),
    ]

    operations = [
        migrations.AddField(
            model_name="user",
            name="is_unlimited",
            field=models.BooleanField(default=False, verbose_name="Безлимитный (тест)"),
        ),
    ]
