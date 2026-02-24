from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("ai", "0001_initial"),
    ]

    operations = [
        migrations.AlterModelOptions(
            name="gptmodels",
            options={"verbose_name": "GPT модель", "verbose_name_plural": "GPT модели"},
        ),
        migrations.AlterModelOptions(
            name="aiprovider",
            options={"verbose_name": "AI провайдер", "verbose_name_plural": "AI провайдеры"},
        ),
        migrations.AlterModelOptions(
            name="aiprompttemplate",
            options={"verbose_name": "AI шаблон промпта", "verbose_name_plural": "AI шаблоны промптов"},
        ),
        migrations.AlterModelOptions(
            name="aiprompttemplatefavorite",
            options={"verbose_name": "Избранный шаблон", "verbose_name_plural": "Избранные шаблоны"},
        ),
        migrations.AlterModelOptions(
            name="aichatsession",
            options={"verbose_name": "AI сессия чата", "verbose_name_plural": "AI сессии чата"},
        ),
        migrations.AlterModelOptions(
            name="aichatmessage",
            options={
                "ordering": ["created_at"],
                "verbose_name": "AI сообщение чата",
                "verbose_name_plural": "AI сообщения чата",
            },
        ),
        migrations.AlterModelOptions(
            name="aigeneratedimage",
            options={
                "verbose_name": "AI сгенерированное изображение",
                "verbose_name_plural": "AI сгенерированные изображения",
            },
        ),
    ]
