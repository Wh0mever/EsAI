from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('cartoon', '0014_scene_audio'),
    ]

    operations = [
        migrations.AddField(
            model_name='cartoonscene',
            name='dialogue',
            field=models.CharField(blank=True, default='', max_length=300, verbose_name='Реплика героя'),
        ),
        migrations.AddField(
            model_name='cartoonscene',
            name='video_prompt',
            field=models.TextField(blank=True, default='', verbose_name='Промпт съёмки'),
        ),
        migrations.AddField(
            model_name='cartoonscene',
            name='video_negative',
            field=models.TextField(blank=True, default='', verbose_name='Чего в кадре быть не должно'),
        ),
        migrations.AddField(
            model_name='cartoonscene',
            name='last_frame',
            field=models.CharField(blank=True, default='', max_length=512, verbose_name='Последний кадр ролика'),
        ),
    ]
