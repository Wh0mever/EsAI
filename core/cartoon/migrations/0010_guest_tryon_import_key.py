from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('cartoon', '0009_cartoonscene_character_cartoonkeyframe'),
    ]

    operations = [
        migrations.AddField(
            model_name='cartoonproject',
            name='import_key',
            field=models.CharField(blank=True, db_index=True, default='', max_length=64, verbose_name='Ключ гостевого черновика'),
        ),
        migrations.CreateModel(
            name='CartoonGuestTryOn',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('device_key', models.CharField(max_length=64, unique=True, verbose_name='Ключ устройства')),
                ('ip', models.GenericIPAddressField(blank=True, db_index=True, null=True, verbose_name='IP')),
                ('created_at', models.DateTimeField(auto_now_add=True, db_index=True)),
                ('character', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='guest_try_ons', to='cartoon.cartooncharacter', verbose_name='Герой')),
                ('preset', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='guest_try_ons', to='cartoon.cartoonpreset', verbose_name='Сцена')),
            ],
            options={
                'verbose_name': 'Бесплатная примерка гостя',
                'verbose_name_plural': 'Бесплатные примерки гостей',
                'ordering': ('-created_at',),
            },
        ),
    ]
