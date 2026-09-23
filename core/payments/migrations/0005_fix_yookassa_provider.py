"""Рублёвые заказы ЮKassa, созданные после 0003, лежали с provider=freedompay.

Создание платежа не заполняло поле провайдера, и оно оставалось значением по
умолчанию. Из-за этого автосверка FreedomPay спрашивала о них не ту платёжку,
а в админке ЮKassa терялась среди карт. Возвращаем правильный провайдер.
"""
from django.db import migrations


def forwards(apps, schema_editor):
    Payment = apps.get_model("payments", "Payment")
    Payment.objects.filter(request__provider="yookassa").exclude(
        provider="yookassa").update(provider="yookassa")


class Migration(migrations.Migration):

    dependencies = [
        ("payments", "0004_alter_payment_provider_starinvoice"),
    ]

    operations = [
        migrations.RunPython(forwards, migrations.RunPython.noop),
    ]
