from decimal import Decimal

from django.db import migrations


SEED_PACKAGES = [
    # (name, tokens, bonus_tokens, price, currency, sort_order)
    ("Старт", 100_000, 0, Decimal("99.00"), "KGS", 10),
    ("Стандарт", 500_000, 50_000, Decimal("399.00"), "KGS", 20),
    ("Про", 1_500_000, 300_000, Decimal("999.00"), "KGS", 30),
]


def seed_packages(apps, schema_editor):
    TokenPackage = apps.get_model("plans", "TokenPackage")
    for name, tokens, bonus, price, currency, sort_order in SEED_PACKAGES:
        TokenPackage.objects.get_or_create(
            name=name,
            defaults={
                "tokens": tokens,
                "bonus_tokens": bonus,
                "price": price,
                "currency": currency,
                "is_active": True,
                "sort_order": sort_order,
                "description": "",
            },
        )


def unseed_packages(apps, schema_editor):
    TokenPackage = apps.get_model("plans", "TokenPackage")
    names = [row[0] for row in SEED_PACKAGES]
    TokenPackage.objects.filter(name__in=names).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("plans", "0011_tokenpackage_tokentransaction"),
    ]

    operations = [
        migrations.RunPython(seed_packages, unseed_packages),
    ]
