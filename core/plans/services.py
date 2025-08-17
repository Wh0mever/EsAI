from __future__ import annotations
import os
import httpx
from decimal import Decimal, InvalidOperation
from typing import Dict, Tuple, Iterable, Optional
from django.db import transaction
from .models import CurrencyRate, Currency
from django.conf import settings
from django.core.cache import cache


API_BASE = settings.EXCHANGE_API_BASE
API_KEY = settings.EXCHANGE_API_KEY

# Returns (rates, source_url)


def fetch_usd_base_rates() -> Tuple[Dict[str, Decimal], str]:
    # API returns conversion from USD -> <CURRENCY>
    url = f"{API_BASE}/{API_KEY}/latest/USD"
    try:
        with httpx.Client(timeout=10.0) as client:
            r = client.get(url)
            r.raise_for_status()
            data = r.json()
    except httpx.HTTPError as e:
        raise RuntimeError(f"Failed to fetch rates: {e}") from e

    if data.get("result") != "success" or "conversion_rates" not in data:
        raise RuntimeError("API returned invalid payload")

    raw = data["conversion_rates"]  # e.g. {"USD":1,"RUB":92.3,"KGS":86.0,...}

    rates: Dict[str, Decimal] = {}
    for code in (Currency.RUB, Currency.KGS):
        if code not in raw:
            continue
        # raw[code] = сколько <code> за 1 USD. Нам нужен rate_to_usd = 1/raw[code].
        try:
            v = Decimal(str(raw[code]))
            if v <= 0:
                continue
            rates[code] = (Decimal("1") / v).quantize(Decimal("0.00000001"))
        except (InvalidOperation, ZeroDivisionError):
            continue

    if not rates:
        raise RuntimeError("No required currencies in response")

    return rates, url


@transaction.atomic
def update_currency_rates() -> Dict[str, Decimal]:
    rates, source = fetch_usd_base_rates()
    for code, rate_to_usd in rates.items():
        CurrencyRate.objects.update_or_create(
            currency=code,
            defaults={"rate_to_usd": rate_to_usd, "source": source},
        )
    return rates


_ONE = Decimal("1")


def get_currency_per_usd_map(codes: Optional[Iterable[str]] = None) -> Dict[str, Decimal]:
    qs = CurrencyRate.objects.all()
    if codes:
        qs = qs.filter(currency__in=list(codes))
    out: Dict[str, Decimal] = {}
    for cr in qs.only("currency", "rate_to_usd"):
        try:
            if cr.rate_to_usd and cr.rate_to_usd > 0:
                out[cr.currency] = _ONE / cr.rate_to_usd  # USD→currency
        except (InvalidOperation, ZeroDivisionError):
            continue
    return out


def get_currency_per_usd_map_cached(codes: Optional[Iterable[str]] = None, timeout: int = 300) -> Dict[str, Decimal]:
    key = "plans:currency_per_usd:" + \
        (",".join(sorted(codes)) if codes else "all")
    data = cache.get(key)
    if data is not None:
        return data
    data = get_currency_per_usd_map(codes)
    cache.set(key, data, timeout=timeout)
    return data
