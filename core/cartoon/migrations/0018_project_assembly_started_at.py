from django.db import migrations, models


class Migration(migrations.Migration):
    """Склейка в очереди и склейка в работе различаются: уборка не считает
    ожидание в очереди media оборвавшейся склейкой."""

    dependencies = [
        ('cartoon', '0017_audio_track_status'),
    ]

    operations = [
        migrations.AddField(
            model_name='cartoonproject',
            name='assembly_started_at',
            field=models.DateTimeField(blank=True, null=True, verbose_name='Склейка началась'),
        ),
    ]
