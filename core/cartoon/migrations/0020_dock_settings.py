"""Мультстудия: модель, качество и длительность из дока + снимок настроек сцены.

Все поля пустые по умолчанию: пустое значение значит «как в пресете сцены», так
что старые мультфильмы, бот и сцены, которые снимаются прямо во время выкладки,
считаются и снимаются ровно как раньше.
"""
import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('ai', '0027_pricing_markup'),
        ('cartoon', '0019_purge_private_pair_videos'),
    ]

    operations = [
        migrations.AddField(
            model_name='cartoonproject',
            name='video_model',
            field=models.ForeignKey(blank=True, help_text='Пусто — модель пресета каждой сцены.', null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='+', to='ai.gptmodels', verbose_name='Модель видео'),
        ),
        migrations.AddField(
            model_name='cartoonproject',
            name='resolution',
            field=models.CharField(blank=True, help_text='Пусто — качество пресета сцены.', max_length=8, null=True, verbose_name='Качество'),
        ),
        migrations.AddField(
            model_name='cartoonproject',
            name='duration',
            field=models.PositiveSmallIntegerField(blank=True, help_text='Пусто — длительность пресета сцены.', null=True, verbose_name='Длительность новых сцен, с'),
        ),
        migrations.AddField(
            model_name='cartoonscene',
            name='duration',
            field=models.PositiveSmallIntegerField(blank=True, help_text='Пусто — как у мультфильма (или пресета).', null=True, verbose_name='Длительность сцены, с'),
        ),
        migrations.AddField(
            model_name='cartoonscene',
            name='shot_model',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='+', to='ai.gptmodels', verbose_name='Снята моделью'),
        ),
        migrations.AddField(
            model_name='cartoonscene',
            name='shot_resolution',
            field=models.CharField(blank=True, max_length=8, null=True, verbose_name='Снята в качестве'),
        ),
        migrations.AddField(
            model_name='cartoonscene',
            name='shot_duration',
            field=models.PositiveSmallIntegerField(blank=True, null=True, verbose_name='Снята длительностью, с'),
        ),
        migrations.AddField(
            model_name='cartoonscene',
            name='shot_aspect',
            field=models.CharField(blank=True, max_length=8, null=True, verbose_name='Снята в формате'),
        ),
        migrations.AddField(
            model_name='cartoonscene',
            name='credits_planned',
            field=models.PositiveIntegerField(blank=True, help_text='Сколько показали на кнопке «Снять»: кадр + видео (или только видео с готовым кадром).', null=True, verbose_name='Цена при запуске'),
        ),
        migrations.AddField(
            model_name='cartoonscene',
            name='shot_video_credits',
            field=models.PositiveIntegerField(blank=True, help_text='Видео-часть цены при запуске — её и списывает готовый ролик.', null=True, verbose_name='Видео по цене запуска'),
        ),
    ]
