"""Гео-детект страны по IP — только для ПОДСКАЗКИ валюты витрины (KGS/RUB).

НЕ используется для платежей, авторизации или любых денежных решений —
единственный потребитель: CurrencyRateView (plans/views.py), результат
`suggested_currency` только предзаполняет переключатель валют, ручной выбор
пользователя (см. next/src/lib/currency.ts) всегда имеет приоритет.

Страну по IP определяем внешним geo-IP сервисом (ip-api.com, без ключа) с
коротким кэшем на IP, чтобы не бомбить сервис повторными запросами.
"""
import logging

import requests as http_requests
from django.core.cache import cache

logger = logging.getLogger(__name__)

GEO_CACHE_PREFIX = "geoip:"
GEO_CACHE_TTL = 60 * 60 * 24  # 24 часа — страна пользователя не меняется каждую минуту
GEO_REQUEST_TIMEOUT = 3  # секунд; при таймауте/ошибке — тихо None (фолбэк на KGS)

# Сентинел «уже проверяли этот IP и сервис не смог определить страну» — чтобы
# не долбить ip-api.com повторно теми же безуспешными IP (localhost в dev и т.п.)
_UNKNOWN = "?"


def detect_country_code(ip: str | None) -> str | None:
    """ISO country code ("RU", "KG", ...) по IP через ip-api.com, либо None.

    Кэшируется в Redis на GEO_CACHE_TTL по ключу IP. Любая ошибка (сеть,
    таймаут, невалидный ответ, приватный/локальный IP) -> None молча — вызывающий
    код (CurrencyRateView) обязан фолбэчиться на KGS, а не падать.
    """
    ip = (ip or "").strip()
    if not ip:
        return None

    cache_key = GEO_CACHE_PREFIX + ip
    cached = cache.get(cache_key)
    if cached is not None:
        return None if cached == _UNKNOWN else cached

    country = None
    try:
        resp = http_requests.get(
            f"http://ip-api.com/json/{ip}",
            params={"fields": "status,countryCode"},
            timeout=GEO_REQUEST_TIMEOUT,
        )
        data = resp.json() or {}
        if data.get("status") == "success":
            code = str(data.get("countryCode") or "").strip().upper()
            country = code or None
    except Exception:  # noqa: BLE001 — geo-подсказка не должна ронять запрос
        logger.warning("detect_country_code: ip-api lookup failed for %s", ip, exc_info=True)
        country = None

    cache.set(cache_key, country or _UNKNOWN, GEO_CACHE_TTL)
    return country
