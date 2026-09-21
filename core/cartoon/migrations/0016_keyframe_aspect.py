from django.db import migrations, models


class Migration(migrations.Migration):
    """Формат становится частью ключа общего кадра: вертикальному мультфильму
    горизонтальный кадр не подходит. Уже нарисованные кадры — 16:9."""

    dependencies = [
        ('cartoon', '0015_scene_dialogue'),
    ]

    operations = [
        migrations.AddField(
            model_name='cartoonkeyframe',
            name='aspect_ratio',
            field=models.CharField(default='16:9', max_length=8, verbose_name='Формат'),
        ),
        migrations.AlterUniqueTogether(
            name='cartoonkeyframe',
            unique_together={('preset', 'character', 'aspect_ratio')},
        ),
    ]
