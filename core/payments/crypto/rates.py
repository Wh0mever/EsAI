"""Курс сом -> доллар для криптосчёта.

Пакеты стоят в сомах, счёт процессору выставляется в долларах. Курс берём в
таком порядке:

1. Значение, зафиксированное админом (AppSetting "currency_kgs_to_usd_rate") —
   ручное всегда главнее, иначе админ не смог бы вмешаться.
2. Живой курс из CurrencyRate (обновляется задачей plans.tasks каждый час),
   если он не протух.
3. settings.CURRENCY_KGS_TO_USD_RATE — чтобы оплата не отвалилась целиком,
   если внешний источник курсов молчит вторые сутки.

Полученная долларовая цена ЗАПОМИНАЕТСЯ в платеже: человек увидел эту сумму и
на неё согласился, пересчитывать её задним числом нельзя.
"""
from __future__ import annotations

import logging
from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP

from django.conf import settings
from django.utils import timezone

from .base import ProviderError

logger = logging.getLogger("payments.crypto")

# Дольше этого живой курс считается протухшим: раз в час его обновляет задача,
# сутки молчания означают, что источник курсов недоступен.
MAX_RATE_AGE = timedelta(hours=24)


def _fallback_rate() -> Decimal:
    return Decimal(str(getattr(settings, "CURRENCY_KGS_TO_USD_RATE", 0.0115)))


def market_rate() -> Decimal | None:
    """Живой курс из CurrencyRate, если он свежий. Иначе None."""
    try:
        from plans.models import CurrencyRate

        row = CurrencyRate.objects.filter(currency="KGS").only(
            "rate_to_usd", "fetched_at").first()
        if not row or not row.rate_to_usd or row.rate_to_usd <= 0:
            return None
        if row.fetched_at and timezone.now() - row.fetched_at > MAX_RATE_AGE:
            return None
        return Decimal(row.rate_to_usd)
    except Exception:  # noqa: BLE001 — курс не должен ронять оплату
        logger.warning("crypto: не удалось прочитать живой курс KGS")
        return None


def kgs_to_usd_rate() -> Decimal:
    """Сколько долларов стоит один сом."""
    try:
        from adminapi.runtime import get_runtime

        manual = Decimal(str(get_runtime("currency_kgs_to_usd_rate", 0.0)))
    except Exception:  # noqa: BLE001
        manual = Decimal("0")
    if manual > 0:
        return manual

    live = market_rate()
    if live and live > 0:
        return live

    return _fallback_rate()


def kgs_to_usd(amount_kgs: Decimal):
    """Цена пакета в долларах и курс, по которому её посчитали."""
    rate = kgs_to_usd_rate()
    # Курс вне разумного коридора означает испорченную настройку. Ошибиться в
    # ту сторону, где человек платит в сто раз больше или меньше, нельзя.
    if not (Decimal("0.0001") <= rate <= Decimal("1")):
        raise ProviderError("курс KGS->USD вне допустимого диапазона",
                            code="currency_rate_invalid")
    usd = (Decimal(amount_kgs) * rate).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    if usd <= 0:
        raise ProviderError("нулевая сумма в долларах", code="amount_invalid")
    return usd, rate
