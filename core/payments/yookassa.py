"""Интеграция с ЮKassa (оплата пакетов кредитов в рублях).

Зачем отдельный провайдер: FreedomPay работает в сомах (KGS). Клиент
подключил ЮKassa под рубли, поэтому валюта, выбранная пользователем на
/pricing, определяет платёжный путь: KGS -> FreedomPay, RUB -> ЮKassa.

⚠️ Главное решение по безопасности. У ЮKassa вебхук НЕ подписан HMAC:
проверять подлинность предлагается по списку IP либо перезапросом платежа
через API. Мы выбрали ПЕРЕЗАПРОС: на вебхук берём только id платежа, а
статус и сумму читаем из ответа API по HTTP Basic (shopId:secret). Тело
вебхука само по себе ничего не решает — подделать начисление кредитов,
прислав нам «оплачено», нельзя.
"""
from __future__ import annotations

import logging
import uuid

import requests
from django.conf import settings

logger = logging.getLogger(__name__)

_TIMEOUT = (10, 30)


def is_configured() -> bool:
    return bool((settings.YOOKASSA_SHOP_ID or "").strip() and (settings.YOOKASSA_SECRET_KEY or "").strip())


def _auth() -> tuple[str, str]:
    return (str(settings.YOOKASSA_SHOP_ID).strip(), str(settings.YOOKASSA_SECRET_KEY).strip())


def create_payment(*, amount: str, currency: str, description: str, return_url: str,
                   metadata: dict | None = None, idempotence_key: str | None = None) -> dict:
    """Создать платёж. Возвращает объект платежа ЮKassa (в т.ч. confirmation_url).

    Idempotence-Key обязателен по контракту ЮKassa: повторный запрос с тем же
    ключом не создаёт второй платёж (защита от дабл-клика и ретраев сети).
    """
    url = f"{str(settings.YOOKASSA_API_URL).rstrip('/')}/payments"
    headers = {
        "Idempotence-Key": idempotence_key or uuid.uuid4().hex,
        "Content-Type": "application/json",
    }
    body = {
        "amount": {"value": amount, "currency": currency},
        # Деньги списываются сразу, без двухстадийного холда: у нас цифровой
        # товар, кредиты начисляются мгновенно после оплаты.
        "capture": True,
        "confirmation": {"type": "redirect", "return_url": return_url},
        "description": description[:128],
    }
    if metadata:
        body["metadata"] = metadata

    r = requests.post(url, json=body, headers=headers, auth=_auth(), timeout=_TIMEOUT)
    data = {}
    try:
        data = r.json() or {}
    except ValueError:
        data = {"raw": r.text[:500]}
    if r.status_code >= 400:
        logger.warning("yookassa create_payment http %s: %s", r.status_code, str(data)[:400])
        raise RuntimeError(str(data.get("description") or data.get("code") or f"http_{r.status_code}"))
    return data


def fetch_payment(payment_id: str) -> dict:
    """Актуальное состояние платежа из API — единственный доверенный источник."""
    url = f"{str(settings.YOOKASSA_API_URL).rstrip('/')}/payments/{payment_id}"
    r = requests.get(url, auth=_auth(), timeout=_TIMEOUT)
    try:
        data = r.json() or {}
    except ValueError:
        data = {}
    if r.status_code >= 400:
        raise RuntimeError(f"yookassa_fetch_http_{r.status_code}")
    return data
