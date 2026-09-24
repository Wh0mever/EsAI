# Видеостудия: источник журнала «vstudio» и показ модели в студии.
# Только choices и новые поля — откат простым migrate назад.

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('ai', '0025_alter_generationjob_status'),
    ]

    operations = [
        migrations.AddField(
            model_name='gptmodels',
            name='vstudio_enabled',
            field=models.BooleanField(default=False, help_text='Модель появится в видеостудии, только если она активна и код знает её семейство (vstudio/caps.py).', verbose_name='Показывать в видеостудии'),
        ),
        migrations.AddField(
            model_name='gptmodels',
            name='vstudio_overrides',
            field=models.JSONField(blank=True, default=dict, help_text='Только ключи: badge, sort, refs ("off"), refs_verified ("ГГГГ-ММ-ДД"), max_image_refs, eta_s. Остальное отклоняется.', verbose_name='Правки видеостудии'),
        ),
        migrations.AlterField(
            model_name='generationlog',
            name='source',
            field=models.CharField(choices=[('chat', 'Чат'), ('studio', 'Студия'), ('bot', 'Бот'), ('vstudio', 'Видеостудия')], default='chat', max_length=8, verbose_name='Откуда'),
        ),
    ]
