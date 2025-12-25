from decimal import Decimal

from django.db import migrations, models


def convert_amounts_to_major(apps, schema_editor):
    Payment = apps.get_model("payments", "Payment")
    for payment in Payment.objects.all().only("id", "amount"):
        if payment.amount is None:
            continue
        payment.amount = (Decimal(payment.amount) / Decimal("100")).quantize(Decimal("0.01"))
        payment.save(update_fields=["amount"])


def convert_amounts_to_minor(apps, schema_editor):
    Payment = apps.get_model("payments", "Payment")
    for payment in Payment.objects.all().only("id", "amount"):
        if payment.amount is None:
            continue
        payment.amount = (Decimal(payment.amount) * Decimal("100")).quantize(Decimal("1"))
        payment.save(update_fields=["amount"])


class Migration(migrations.Migration):

    dependencies = [
        ("payments", "0001_initial"),
    ]

    operations = [
        migrations.AlterField(
            model_name="payment",
            name="amount",
            field=models.DecimalField(decimal_places=2, max_digits=12),
        ),
        migrations.RunPython(convert_amounts_to_major, reverse_code=convert_amounts_to_minor),
    ]
