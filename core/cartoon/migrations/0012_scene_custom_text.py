from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('cartoon', '0011_cartoonpairvideo'),
    ]

    operations = [
        migrations.AddField(
            model_name='cartoonscene',
            name='custom_text',
            field=models.TextField(blank=True, default='', verbose_name='Своя сцена: описание'),
        ),
        migrations.AddField(
            model_name='cartoonscene',
            name='custom_title',
            field=models.CharField(blank=True, default='', max_length=80, verbose_name='Своя сцена: название'),
        ),
        migrations.AddField(
            model_name='cartoonscene',
            name='custom_prompt',
            field=models.TextField(blank=True, default='', verbose_name='Своя сцена: промпт кадра'),
        ),
        migrations.AddField(
            model_name='cartoonscene',
            name='custom_motion',
            field=models.TextField(blank=True, default='', verbose_name='Своя сцена: промпт движения'),
        ),
    ]
