"""Криптооплата: счёт, журнал вебхуков и разметка провайдера у платежей.

Миграция только добавляет: две новые таблицы и расширенный список провайдеров.
Ничего не удаляет и не переписывает, поэтому откат кода не требует отката базы.
"""

import django.db.models.deletion
from django.db import migrations, models


def mark_yookassa_payments(apps, schema_editor):
    """Проставить провайдера рублёвым платежам.

    До появления этого поля ЮKassa писала себя только в request["provider"],
    и в списке платежей все они выглядели как FreedomPay. Данные не портим:
    трогаем ровно те строки, которые сами себя пометили ЮKassa.
    """
    Payment = apps.get_model("payments", "Payment")
    Payment.objects.filter(request__provider="yookassa").update(provider="yookassa")


def unmark_yookassa_payments(apps, schema_editor):
    Payment = apps.get_model("payments", "Payment")
    Payment.objects.filter(provider="yookassa").update(provider="freedompay")


class Migration(migrations.Migration):

    dependencies = [
        ('payments', '0002_funnelevent'),
    ]

    operations = [
        migrations.CreateModel(
            name='CryptoWebhookEvent',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('provider', models.CharField(max_length=32, verbose_name='Процессор')),
                ('provider_invoice_id', models.CharField(db_index=True, max_length=64, verbose_name='Счёт у процессора')),
                ('event_key', models.CharField(max_length=64, unique=True, verbose_name='Ключ события')),
                ('status', models.CharField(blank=True, default='', max_length=24, verbose_name='Статус')),
                ('actually_paid', models.DecimalField(decimal_places=18, default=0, max_digits=36, verbose_name='Пришло')),
                ('payload', models.JSONField(blank=True, default=dict, verbose_name='Тело')),
                ('signature_ok', models.BooleanField(default=False, verbose_name='Подпись верна')),
                ('processed', models.BooleanField(default=False, verbose_name='Обработан')),
                ('result', models.CharField(blank=True, default='', max_length=64, verbose_name='Итог')),
                ('received_at', models.DateTimeField(auto_now_add=True, db_index=True)),
            ],
            options={
                'verbose_name': 'Вебхук криптоплатежа',
                'verbose_name_plural': 'Вебхуки криптоплатежей',
                'ordering': ('-received_at', '-id'),
            },
        ),
        migrations.AlterField(
            model_name='payment',
            name='provider',
            field=models.CharField(choices=[('freedompay', 'FreedomPay'), ('yookassa', 'ЮKassa'), ('crypto_nowpayments', 'NOWPayments (крипта)')], default='freedompay', max_length=32),
        ),
        migrations.CreateModel(
            name='CryptoInvoice',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('provider', models.CharField(db_index=True, default='nowpayments', max_length=32, verbose_name='Процессор')),
                ('provider_invoice_id', models.CharField(max_length=64, unique=True, verbose_name='Счёт у процессора')),
                ('status', models.CharField(choices=[('waiting', 'Ждём перевод'), ('confirming', 'Перевод найден, подтверждается'), ('confirmed', 'Подтверждён сетью'), ('sending', 'Уходит на наш кошелёк'), ('partially_paid', 'Пришло меньше суммы'), ('finished', 'Оплачен'), ('failed', 'Не прошёл'), ('refunded', 'Возвращён'), ('expired', 'Просрочен')], db_index=True, default='waiting', max_length=24, verbose_name='Статус')),
                ('price_amount', models.DecimalField(decimal_places=2, max_digits=12, verbose_name='Цена')),
                ('price_currency', models.CharField(default='USD', max_length=8, verbose_name='Валюта цены')),
                ('pay_currency', models.CharField(max_length=24, verbose_name='Код монеты у процессора')),
                ('pay_coin', models.CharField(blank=True, default='', max_length=16, verbose_name='Монета')),
                ('pay_network', models.CharField(blank=True, default='', max_length=32, verbose_name='Сеть')),
                ('pay_address', models.CharField(max_length=160, verbose_name='Адрес перевода')),
                ('pay_extra_id', models.CharField(blank=True, default='', max_length=160, verbose_name='Memo / tag')),
                ('pay_amount', models.DecimalField(decimal_places=18, max_digits=36, verbose_name='Сумма к переводу')),
                ('actually_paid', models.DecimalField(decimal_places=18, default=0, max_digits=36, verbose_name='Пришло')),
                ('actually_paid_fiat', models.DecimalField(blank=True, decimal_places=2, max_digits=12, null=True, verbose_name='Пришло, в валюте цены')),
                ('tx_hash', models.CharField(blank=True, default='', max_length=160, verbose_name='Транзакция')),
                ('confirmations', models.IntegerField(blank=True, null=True, verbose_name='Подтверждений')),
                ('credited_tokens', models.BigIntegerField(default=0, verbose_name='Начислено кредитов')),
                ('credited_paid_amount', models.DecimalField(decimal_places=18, default=0, max_digits=36, verbose_name='Оплачено на момент начисления')),
                ('credit_events', models.JSONField(blank=True, default=list, verbose_name='Начисления')),
                ('flags', models.JSONField(blank=True, default=dict, verbose_name='Пометки')),
                ('expires_at', models.DateTimeField(blank=True, db_index=True, null=True, verbose_name='Действителен до')),
                ('last_checked_at', models.DateTimeField(blank=True, null=True, verbose_name='Последняя сверка')),
                ('last_webhook_at', models.DateTimeField(blank=True, null=True, verbose_name='Последний вебхук')),
                ('finalized_at', models.DateTimeField(blank=True, null=True, verbose_name='Закрыт')),
                ('provider_updated_at', models.CharField(blank=True, default='', max_length=40, verbose_name='Обновлён у процессора')),
                ('created_at', models.DateTimeField(auto_now_add=True, db_index=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('payment', models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name='crypto_invoice', to='payments.payment', verbose_name='Платёж')),
            ],
            options={
                'verbose_name': 'Криптосчёт',
                'verbose_name_plural': 'Криптосчета',
                'ordering': ('-created_at', '-id'),
                'indexes': [models.Index(fields=['status', 'created_at'], name='payments_cr_status_a5cd91_idx')],
            },
        ),
        migrations.RunPython(mark_yookassa_payments, unmark_yookassa_payments),
    ]
