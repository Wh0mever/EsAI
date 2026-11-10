# Напоминание о заканчивающихся кредитах: какой порог человек уже видел в цикле.

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('plans', '0026_reason_merge_audio'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='LowBalanceNotice',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('cycle_tx_id', models.BigIntegerField(verbose_name='Покупка, с которой идёт цикл')),
                ('shown_level', models.PositiveSmallIntegerField(blank=True, null=True, verbose_name='Показан порог, %')),
                ('updated_at', models.DateTimeField(auto_now=True, verbose_name='Обновлено')),
                ('user', models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name='low_balance_notice', to=settings.AUTH_USER_MODEL, verbose_name='Пользователь')),
            ],
            options={
                'verbose_name': 'Напоминание об остатке',
                'verbose_name_plural': 'Напоминания об остатке',
            },
        ),
    ]
