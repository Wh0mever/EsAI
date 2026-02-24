from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("payments", "0002_payment_amount_decimal"),
    ]

    operations = [
        migrations.AlterModelOptions(
            name="payment",
            options={"ordering": ("-created_at", "-id"), "verbose_name": "Платеж", "verbose_name_plural": "Платежи"},
        ),
    ]
