"""Цена и пределы склейки.

Цена — runtime-ключ merge_price_credits (правится в админке без выкладки):
20 кр — цифра клиента из ТЗ 29.09, 0 — склейка бесплатна. Списывается только
за готовый ролик: до него цена лежит в резерве.
"""
from __future__ import annotations

import logging

from django.db import transaction

logger = logging.getLogger(__name__)

PRICE_KEY = "merge_price_credits"
DEFAULT_PRICE = 20
MAX_PRICE = 100000

MIN_FRAGMENTS = 2
MAX_FRAGMENTS = 30
MAX_TOTAL_S = 300
# Сколько дней хранится готовая склейка (ТЗ: «Мои видео → Склейки» 30 дней).
RETENTION_DAYS = 30
# Черновиков и склеек у одного человека — с запасом на любую работу, но не
# бесконечно: строка хранит до тридцати фрагментов со снимком карточки.
# Истёкшие не считаются: файлов у них нет, а новую работу они бы запирали.
MAX_PROJECTS = 100
# Готовых склеек у человека одновременно. Ролик хранится 30 дней и весит до
# ~150 МБ: без предела один аккаунт (при цене 0 — бесплатно) занял бы десятки
# гигабайт, а полный диск — отказ всего сайта, не только склейки.
MAX_READY = 20

# Кадр 720p-класса под каждый формат: 1:1 — 960, чтобы квадрат не был мельче
# горизонтального кадра по площади.
TARGETS = {"16:9": (1280, 720), "9:16": (720, 1280), "1:1": (960, 960)}
ASPECTS = tuple(TARGETS)
FIT_PAD = "pad"
FIT_CROP = "crop"
FITS = (FIT_PAD, FIT_CROP)


def price_credits() -> int:
    """Цена одной склейки в кредитах (0 — бесплатно). Никогда не бросает.

    Чтение — в savepoint: сбой запроса к настройкам на Postgres иначе сломал
    бы всю транзакцию запроса.
    """
    value = DEFAULT_PRICE
    try:
        from adminapi.runtime import get_runtime

        with transaction.atomic():
            value = int(get_runtime(PRICE_KEY, DEFAULT_PRICE))
    except Exception:
        logger.warning("склейка: цена не прочиталась, беру %s", DEFAULT_PRICE, exc_info=True)
        value = DEFAULT_PRICE
    return min(MAX_PRICE, max(0, value))


def limits() -> dict:
    """Пределы для интерфейса: те же числа, что проверяет сервер."""
    return {"min_fragments": MIN_FRAGMENTS, "max_fragments": MAX_FRAGMENTS,
            "max_total_s": MAX_TOTAL_S, "retention_days": RETENTION_DAYS}


# Подпись по умолчанию на языке запроса: сервер подставляет её, когда клиент
# названия не прислал (склейка без названия, ролик без промпта).
DEFAULT_TITLE = {"ru": "Склейка {date}", "en": "Merge {date}", "kg": "Бириктирүү {date}"}


def localized(table: dict, lang: str) -> str:
    return table.get(lang) or table["ru"]
