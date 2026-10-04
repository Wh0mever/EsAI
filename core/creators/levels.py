"""Уровни программы: стартовый набор и поиск.

Пороги ПРЕДВАРИТЕЛЬНЫЕ — таблица клиента ещё не пришла. Они правятся в
админке (каждая правка — в журнале) и только показываются в кабинете:
уровень креатору меняет администратор вручную, автоматики нет.
"""
from __future__ import annotations

from decimal import Decimal

from .errors import CreatorsError
from .models import CreatorLevel

BASE_LEVEL_KEY = "creator"
MAX_PERCENT = Decimal("25")

DEFAULT_LEVELS = [
    {"key": "creator", "title": "CREATOR", "percent": Decimal("10"), "sort": 1,
     "min_publications": 0, "min_registrations": 0, "min_paying": 0},
    {"key": "creator_pro", "title": "CREATOR PRO", "percent": Decimal("15"), "sort": 2,
     "min_publications": 10, "min_registrations": 25, "min_paying": 10},
    {"key": "ambassador", "title": "AMBASSADOR", "percent": Decimal("20"), "sort": 3,
     "min_publications": 25, "min_registrations": 100, "min_paying": 30},
    {"key": "ambassador_pro", "title": "AMBASSADOR PRO", "percent": Decimal("25"), "sort": 4,
     "min_publications": 50, "min_registrations": 300, "min_paying": 100},
]


def ensure_levels() -> None:
    """Создать недостающие уровни. Существующие строки не трогает.

    Нужна тестам (миграции там выключены, 0002_seed_levels не выполняется) и
    проверке цепочки на пустой базе. Правки администратора не перезаписывает.
    """
    for row in DEFAULT_LEVELS:
        defaults = {name: value for name, value in row.items() if name != "key"}
        CreatorLevel.objects.get_or_create(key=row["key"], defaults=defaults)


def get_level(key) -> CreatorLevel:
    level = CreatorLevel.objects.filter(key=str(key or "").strip()).first()
    if level is None:
        raise CreatorsError("level_unknown")
    return level


def next_level(level) -> CreatorLevel | None:
    """Следующий уровень по порядку; у последнего — None."""
    if level is None:
        return None
    return CreatorLevel.objects.filter(sort__gt=level.sort).order_by("sort").first()
