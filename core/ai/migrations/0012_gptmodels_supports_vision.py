from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("ai", "0011_aichatmessage_session_created_idx"),
    ]

    operations = [
        migrations.AddField(
            model_name="gptmodels",
            name="supports_vision",
            field=models.BooleanField(
                default=False,
                help_text="Модель принимает изображения (vision). Если выкл — отправка картинки вернёт понятную ошибку, без вызова провайдера.",
            ),
        ),
    ]
