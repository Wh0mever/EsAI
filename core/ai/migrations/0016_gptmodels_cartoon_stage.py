from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("ai", "0015_gptmodels_category_recommended"),
    ]

    operations = [
        migrations.AddField(
            model_name="gptmodels",
            name="cartoon_stage",
            field=models.CharField(
                blank=True,
                choices=[
                    ("", "—"),
                    ("script", "Сценарий"),
                    ("image", "Изображения"),
                    ("video", "Видео"),
                ],
                default="",
                max_length=10,
            ),
        ),
    ]
