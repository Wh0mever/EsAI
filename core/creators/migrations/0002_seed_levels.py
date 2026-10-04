# Стартовые уровни программы EsAI Creators. Пороги предварительные: таблица
# клиента ещё не пришла, правятся они в админке.

from decimal import Decimal

from django.db import migrations

# Слепок на момент миграции (не импорт из creators.levels): миграция не должна
# меняться вместе с кодом.
# (key, title, percent, sort, min_publications, min_registrations, min_paying)
SEED_LEVELS = [
    ("creator", "CREATOR", Decimal("10"), 1, 0, 0, 0),
    ("creator_pro", "CREATOR PRO", Decimal("15"), 2, 10, 25, 10),
    ("ambassador", "AMBASSADOR", Decimal("20"), 3, 25, 100, 30),
    ("ambassador_pro", "AMBASSADOR PRO", Decimal("25"), 4, 50, 300, 100),
]


def seed_levels(apps, schema_editor):
    CreatorLevel = apps.get_model("creators", "CreatorLevel")
    for key, title, percent, sort, publications, registrations, paying in SEED_LEVELS:
        # Только недостающие строки: повторный прогон миграции не должен
        # затирать пороги и проценты, которые администратор уже поправил.
        CreatorLevel.objects.get_or_create(
            key=key,
            defaults={
                "title": title,
                "percent": percent,
                "sort": sort,
                "min_publications": publications,
                "min_registrations": registrations,
                "min_paying": paying,
            },
        )


class Migration(migrations.Migration):

    dependencies = [
        ("creators", "0001_initial"),
    ]

    operations = [
        # Обратно — ничего: на уровни ссылаются креаторы (PROTECT), удалять их нельзя.
        migrations.RunPython(seed_levels, migrations.RunPython.noop),
    ]
