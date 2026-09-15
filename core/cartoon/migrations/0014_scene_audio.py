import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('cartoon', '0013_featured_works'),
    ]

    operations = [
        migrations.AddField(
            model_name='cartoonscene',
            name='mixed_video',
            field=models.CharField(blank=True, default='', max_length=512, verbose_name='Видео со звуком'),
        ),
        migrations.AddField(
            model_name='cartoonscene',
            name='sound_volume',
            field=models.FloatField(default=1.0, verbose_name='Громкость звука самой сцены'),
        ),
        migrations.CreateModel(
            name='CartoonAudioTrack',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('kind', models.CharField(choices=[('voice', 'ИИ-голос'), ('own', 'Свой голос'), ('music', 'Музыка'), ('sfx', 'Звуковой эффект')], max_length=8, verbose_name='Тип')),
                ('voice_id', models.CharField(blank=True, default='', max_length=64, verbose_name='Голос (id)')),
                ('voice_name', models.CharField(blank=True, default='', max_length=120, verbose_name='Голос')),
                ('text', models.TextField(blank=True, default='', verbose_name='Текст или описание')),
                ('file', models.CharField(max_length=512, verbose_name='Файл')),
                ('duration', models.FloatField(default=0, verbose_name='Длительность, с')),
                ('start_sec', models.FloatField(default=0, verbose_name='Начало, с')),
                ('volume', models.FloatField(default=1.0, verbose_name='Громкость')),
                ('credits_spent', models.PositiveIntegerField(default=0, verbose_name='Списано кредитов')),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('character', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='audio_tracks', to='cartoon.cartooncharacter', verbose_name='Чья реплика')),
                ('scene', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='audio_tracks', to='cartoon.cartoonscene', verbose_name='Сцена')),
            ],
            options={
                'verbose_name': 'Звуковая дорожка',
                'verbose_name_plural': 'Звуковые дорожки',
                'ordering': ('start_sec', 'id'),
            },
        ),
    ]
