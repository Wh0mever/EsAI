from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('cartoon', '0012_scene_custom_text'),
    ]

    operations = [
        migrations.AddField(
            model_name='cartoonproject',
            name='featured_at',
            field=models.DateTimeField(blank=True, db_index=True, null=True, verbose_name='Отмечен для рекламы'),
        ),
        migrations.AddField(
            model_name='cartoonscene',
            name='featured_at',
            field=models.DateTimeField(blank=True, db_index=True, null=True, verbose_name='Отмечена для рекламы'),
        ),
    ]
