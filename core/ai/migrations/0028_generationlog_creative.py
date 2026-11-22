# Creative Studio: источник журнала генераций «creative». Только choices — откат простым migrate назад.

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('ai', '0027_pricing_markup'),
    ]

    operations = [
        migrations.AlterField(
            model_name='generationlog',
            name='source',
            field=models.CharField(choices=[('chat', 'Чат'), ('studio', 'Студия'), ('bot', 'Бот'), ('vstudio', 'Видеостудия'), ('creative', 'Creative Studio')], default='chat', max_length=8, verbose_name='Откуда'),
        ),
    ]
