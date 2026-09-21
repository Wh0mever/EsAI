from django.db import migrations, models


class Migration(migrations.Migration):
    """Музыка и эффекты делаются в фоне: у дорожки появляется состояние."""

    dependencies = [
        ('cartoon', '0016_keyframe_aspect'),
    ]

    operations = [
        migrations.AddField(
            model_name='cartoonaudiotrack',
            name='status',
            field=models.CharField(choices=[('pending', 'Готовится'), ('ready', 'Готова'), ('failed', 'Не получилась')], default='ready', max_length=8, verbose_name='Состояние'),
        ),
        migrations.AddField(
            model_name='cartoonaudiotrack',
            name='error',
            field=models.CharField(blank=True, default='', max_length=300, verbose_name='Ошибка'),
        ),
        migrations.AddField(
            model_name='cartoonaudiotrack',
            name='credits_planned',
            field=models.PositiveIntegerField(default=0, verbose_name='Цена в кредитах'),
        ),
        migrations.AddField(
            model_name='cartoonaudiotrack',
            name='seconds_asked',
            field=models.FloatField(default=0, verbose_name='Запрошенная длительность, с'),
        ),
        migrations.AlterField(
            model_name='cartoonaudiotrack',
            name='file',
            field=models.CharField(blank=True, default='', max_length=512, verbose_name='Файл'),
        ),
    ]
