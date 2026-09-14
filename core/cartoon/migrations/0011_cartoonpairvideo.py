from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('cartoon', '0010_guest_tryon_import_key'),
    ]

    operations = [
        migrations.CreateModel(
            name='CartoonPairVideo',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('video', models.CharField(max_length=512, verbose_name='Ролик')),
                ('clip', models.CharField(blank=True, default='', help_text='480p без звука — для автозапуска в витрине и ленте на телефоне.', max_length=512, verbose_name='Лёгкая копия')),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('character', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='pair_videos', to='cartoon.cartooncharacter', verbose_name='Герой')),
                ('preset', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='pair_videos', to='cartoon.cartoonpreset', verbose_name='Сцена')),
                ('source_scene', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='+', to='cartoon.cartoonscene', verbose_name='Из какой съёмки')),
            ],
            options={
                'verbose_name': 'Ролик героя в сцене',
                'verbose_name_plural': 'Ролики героев в сценах',
                'unique_together': {('preset', 'character')},
            },
        ),
    ]
