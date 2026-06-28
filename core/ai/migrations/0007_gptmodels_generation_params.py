from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('ai', '0006_deactivate_legacy_models'),
    ]

    operations = [
        migrations.AddField(
            model_name='gptmodels',
            name='system_prompt',
            field=models.TextField(
                blank=True,
                default='',
                help_text='Системный промпт по умолчанию для этой модели',
            ),
        ),
        migrations.AddField(
            model_name='gptmodels',
            name='temperature',
            field=models.FloatField(
                blank=True,
                null=True,
                help_text='Temperature (0..2). Пусто — использовать значение по умолчанию',
            ),
        ),
        migrations.AddField(
            model_name='gptmodels',
            name='top_p',
            field=models.FloatField(
                blank=True,
                null=True,
                help_text='Top-p (0..1). Пусто — использовать значение по умолчанию',
            ),
        ),
    ]
