from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("users", "0008_usercardbind_unique"),
    ]

    operations = [
        migrations.AddField(
            model_name="user",
            name="avatar_url",
            field=models.URLField(blank=True, default="", max_length=512, verbose_name="Аватар (URL)"),
        ),
    ]
