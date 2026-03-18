from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("users", "0002_ensure_usercardbind_table"),
    ]

    operations = [
        migrations.AlterField(
            model_name="user",
            name="bonus_texts",
            field=models.PositiveIntegerField(default=0, verbose_name="Бонусные тексты"),
        ),
        migrations.AlterField(
            model_name="user",
            name="bonus_images",
            field=models.PositiveIntegerField(default=0, verbose_name="Бонусные изображения"),
        ),
        migrations.AlterField(
            model_name="user",
            name="bonus_songs",
            field=models.PositiveIntegerField(default=0, verbose_name="Бонусные песни"),
        ),
        migrations.AlterField(
            model_name="user",
            name="bonus_music",
            field=models.PositiveIntegerField(default=0, verbose_name="Бонусная музыка"),
        ),
    ]
