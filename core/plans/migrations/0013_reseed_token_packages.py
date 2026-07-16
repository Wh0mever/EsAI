from decimal import Decimal

from django.db import migrations


# Финальная матрица пакетов (ТЗ 2). Валюта KGS, bonus_tokens=0.
# Уникальный признак — name (по нему делаем update_or_create, идемпотентно).
FINAL_PACKAGES = [
    # name, tokens, price, sort_order, description
    (
        "Старт",
        150_000,
        Decimal("190.00"),
        10,
        "Для студентов, школьников и быстрых повседневных задач. Без абонентской платы.",
    ),
    (
        "Про",
        450_000,
        Decimal("490.00"),
        20,
        "Хит продаж. Для копирайтеров, SMM, маркетологов и юристов. Повышенная скорость серверов.",
    ),
    (
        "Бизнес",
        1_200_000,
        Decimal("990.00"),
        30,
        "Максимальный пакет: программисты, командная работа, анализ тяжёлых PDF/Excel.",
    ),
]

FINAL_NAMES = [row[0] for row in FINAL_PACKAGES]


def reseed_packages(apps, schema_editor):
    """Привести TokenPackage ровно к 3 активным пакетам (идемпотентно).

    - По каждому из 3 пакетов делаем update_or_create по name, выставляя
      финальные tokens/price/sort_order/description + currency=KGS, bonus=0.
    - Любой другой существующий пакет → is_active=False (не удаляем, чтобы не
      потерять историю и ссылки из прошлых платежей).
    """
    TokenPackage = apps.get_model("plans", "TokenPackage")

    for name, tokens, price, sort_order, description in FINAL_PACKAGES:
        TokenPackage.objects.update_or_create(
            name=name,
            defaults={
                "tokens": tokens,
                "bonus_tokens": 0,
                "price": price,
                "currency": "KGS",
                "is_active": True,
                "sort_order": sort_order,
                "description": description,
            },
        )

    # Все прочие пакеты деактивируем.
    TokenPackage.objects.exclude(name__in=FINAL_NAMES).update(is_active=False)


def noop_reverse(apps, schema_editor):
    # Откат не предусмотрен: ручная корректировка пакетов не сбрасывается.
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("plans", "0012_seed_token_packages"),
    ]

    operations = [
        migrations.RunPython(reseed_packages, noop_reverse),
    ]
