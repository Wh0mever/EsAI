"""Цены пакетов в Telegram Stars.

Разработчик получает $0.013 за Star (Bot Developer Terms), поэтому цена
в Stars считается так, чтобы владелец сайта получал столько же, сколько
с оплаты в сомах: stars = ceil5(цена_в_сомах × курс_сом→$ / 0.013).

Итоговую цену задаёт человек в админке — она должна быть стабильной, а курс
сома обновляется каждый час. Формула здесь только подсказывает и предупреждает,
если подсказка и цена разошлись.
"""
from __future__ import annotations

import math
from decimal import Decimal

from django.conf import settings

STARS_USD_WITHDRAW_RATE = Decimal("0.013")
STARS_ROUNDING = 5
STARS_MIN = 1
STARS_MAX = 9999


def _runtime(key: str, default):
    try:
        from adminapi.runtime import get_runtime

        return get_runtime(key, default)
    except Exception:  # noqa: BLE001
        return default


def stars_mode() -> str:
    """off — Stars не продаём; staff — только сотрудникам; on — всем."""
    value = str(_runtime("stars_payments_mode",
                         getattr(settings, "STARS_PAYMENTS_MODE", "on")) or "on").lower()
    return value if value in ("off", "staff", "on") else "on"


def withdraw_rate() -> Decimal:
    try:
        rate = Decimal(str(_runtime("stars_usd_withdraw_rate", float(STARS_USD_WITHDRAW_RATE))))
    except Exception:  # noqa: BLE001
        rate = STARS_USD_WITHDRAW_RATE
    return rate if rate > 0 else STARS_USD_WITHDRAW_RATE


def rounding() -> int:
    try:
        step = int(_runtime("stars_price_rounding", STARS_ROUNDING))
    except Exception:  # noqa: BLE001
        step = STARS_ROUNDING
    return step if step > 0 else 1


def kgs_to_usd_rate() -> Decimal:
    try:
        from payments.crypto.rates import kgs_to_usd_rate as _rate

        rate = Decimal(str(_rate()))
        return rate if rate > 0 else Decimal("0")
    except Exception:  # noqa: BLE001
        return Decimal("0")


def suggest_stars_price(package) -> int | None:
    """Сколько Stars стоит пакет, чтобы выручка совпала с оплатой в сомах."""
    price = Decimal(str(getattr(package, "price", 0) or 0))
    currency = str(getattr(package, "currency", "KGS") or "KGS").upper()
    if price <= 0:
        return None
    if currency == "USD":
        usd = price
    elif currency == "KGS":
        rate = kgs_to_usd_rate()
        if rate <= 0:
            return None
        usd = price * rate
    else:
        return None
    raw = usd / withdraw_rate()
    step = rounding()
    stars = int(math.ceil(float(raw) / step) * step)
    return max(STARS_MIN, min(STARS_MAX, stars))


def price_drift(package) -> float | None:
    """На сколько процентов цена в Stars разошлась с подсказкой."""
    current = getattr(package, "stars_price", None)
    suggested = suggest_stars_price(package)
    if not current or not suggested:
        return None
    return round((current - suggested) / suggested * 100.0, 1)
