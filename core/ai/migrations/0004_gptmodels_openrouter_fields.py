from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('ai', '0003_remove_aigeneratedimage_provider_and_more'),
    ]

    operations = [
        # Added without the unique constraint first; existing rows would all default
        # to "" and collide. The unique constraint is applied in 0005 after backfill.
        migrations.AddField(
            model_name='gptmodels',
            name='openrouter_id',
            field=models.CharField(
                default='',
                help_text="Системный ID модели в OpenRouter (напр. 'openai/gpt-4o')",
                max_length=128,
            ),
        ),
        migrations.AddField(
            model_name='gptmodels',
            name='markup_coefficient',
            field=models.DecimalField(
                decimal_places=3,
                default=1.0,
                help_text='Коэффициент наценки для списания токенов',
                max_digits=6,
            ),
        ),
        migrations.AddField(
            model_name='gptmodels',
            name='sort_order',
            field=models.PositiveIntegerField(default=100),
        ),
        migrations.AlterField(
            model_name='gptmodels',
            name='name',
            field=models.CharField(
                help_text='Отображаемое имя модели',
                max_length=100,
                unique=True,
            ),
        ),
        migrations.AlterModelOptions(
            name='gptmodels',
            options={
                'ordering': ['sort_order', 'id'],
                'verbose_name': 'GPT модель',
                'verbose_name_plural': 'GPT модели',
            },
        ),
    ]
