from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("content", "0001_initial"),
    ]

    operations = [
        migrations.AlterModelOptions(
            name="blogpost",
            options={"verbose_name": "Пост блога", "verbose_name_plural": "Посты блога"},
        ),
    ]
