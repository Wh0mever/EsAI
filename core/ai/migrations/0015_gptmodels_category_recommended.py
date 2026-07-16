from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("ai", "0014_aichatsession_context_summary"),
    ]

    operations = [
        migrations.AddField(
            model_name="gptmodels",
            name="category",
            field=models.CharField(
                choices=[
                    ("chat", "💬 Для общения"),
                    ("writing", "✍️ Тексты и SEO"),
                    ("coding", "💻 Программирование"),
                    ("reasoning", "🧠 Анализ и рассуждения"),
                    ("search", "🌐 Поиск в интернете"),
                    ("image", "🖼️ Изображения"),
                    ("fast", "⚡️ Быстрые"),
                    ("budget", "💰 Экономичные"),
                ],
                default="chat",
                max_length=20,
            ),
        ),
        migrations.AddField(
            model_name="gptmodels",
            name="recommended",
            field=models.BooleanField(default=False),
        ),
    ]
