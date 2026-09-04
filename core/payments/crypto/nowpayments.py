"""Адаптер NOWPayments.

Работаем в «белом» режиме: просим адрес и точную сумму (POST /payment) и
рисуем свой экран оплаты, а не уводим человека на чужую страницу. Ключей от
денег у нас нет — кошелёк для выплат настроен в кабинете процессора.

Про доверие. Вебхук подписан HMAC-SHA512 по телу с отсортированными ключами,
и подпись мы проверяем строго. Но даже верная подпись доказывает лишь то, что
сообщение прислал процессор, — суммы и статус мы всё равно перезапрашиваем
сами (fetch_invoice), и начисляем только по своему запросу.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import logging
import time
from datetime import datetime, timezone as dt_timezone
from decimal import Decimal, InvalidOperation
from typing import Optional

import requests

from . import currencies
from .base import (
    CONFIRMED, CONFIRMING, EXPIRED, FAILED, FINISHED, Invoice, InvoiceState,
    PARTIALLY_PAID, ProviderError, ProviderUnavailable, REFUNDED, SENDING,
    UNKNOWN, WAITING,
)

logger = logging.getLogger("payments.crypto")

_TIMEOUT = (10, 30)
_LIVE_URL = "https://api.nowpayments.io/v1"
_SANDBOX_URL = "https://api-sandbox.nowpayments.io/v1"

# Их словарь -> наш. Всё незнакомое уходит в UNKNOWN: гадать о статусе денег
# нельзя, счёт останется в прежнем состоянии и попадёт на разбор.
_STATUS_MAP = {
    "waiting": WAITING,
    "confirming": CONFIRMING,
    "confirmed": CONFIRMED,
    "sending": SENDING,
    "partially_paid": PARTIALLY_PAID,
    "finished": FINISHED,
    "failed": FAILED,
    "refunded": REFUNDED,
    "expired": EXPIRED,
}


def _dec(value, default="0") -> Decimal:
    try:
        if value is None or value == "":
            return Decimal(default)
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return Decimal(default)


def _parse_dt(value) -> Optional[datetime]:
    raw = str(value or "").strip()
    if not raw:
        return None
    raw = raw.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=dt_timezone.utc)
    return parsed


def _ascii(text: str, limit: int = 100) -> str:
    """Только ASCII: подпись вебхука считается по телу, которое вернёт нам сам
    процессор, и любая нелатиница в нём — лишний риск разойтись в кодировке."""
    cleaned = "".join(ch for ch in str(text or "") if 32 <= ord(ch) < 127)
    return cleaned[:limit] or "EsAI credits"


class NowPayments:
    name = "nowpayments"

    def __init__(self, *, api_key: str = "", ipn_secret: str = "",
                 api_url: str = "", sandbox: bool = False):
        self._api_key = (api_key or "").strip()
        self._ipn_secret = (ipn_secret or "").strip()
        self._sandbox = bool(sandbox)
        self._api_url = (api_url or "").strip().rstrip("/") or (
            _SANDBOX_URL if sandbox else _LIVE_URL)

    # ------------------------------------------------------------ вспомогательное ---

    @property
    def sandbox(self) -> bool:
        return self._sandbox

    def is_configured(self) -> bool:
        return bool(self._api_key)

    def _headers(self) -> dict:
        return {"x-api-key": self._api_key, "Content-Type": "application/json"}

    def _get(self, path: str, params: dict | None = None, attempts: int = 3) -> dict:
        """GET можно повторять: он ничего не меняет."""
        last = None
        for attempt in range(attempts):
            try:
                r = requests.get(f"{self._api_url}{path}", params=params,
                                 headers=self._headers(), timeout=_TIMEOUT)
            except requests.RequestException as exc:
                last = ProviderUnavailable(str(exc)[:200], code="network_error")
            else:
                if r.status_code < 400:
                    return self._json(r)
                if r.status_code >= 500 or r.status_code == 429:
                    last = ProviderUnavailable(f"http_{r.status_code}",
                                               code=f"http_{r.status_code}")
                else:
                    raise ProviderError(self._error_text(r), code=f"http_{r.status_code}")
            if attempt + 1 < attempts:
                time.sleep(0.7 * (attempt + 1))
        raise last or ProviderUnavailable("нет ответа", code="no_response")

    def _post(self, path: str, body: dict) -> dict:
        """POST не повторяем: у создания счёта нет ключа идемпотентности, и
        второй такой запрос завёл бы у процессора второй счёт."""
        try:
            r = requests.post(f"{self._api_url}{path}", json=body,
                              headers=self._headers(), timeout=_TIMEOUT)
        except requests.RequestException as exc:
            raise ProviderUnavailable(str(exc)[:200], code="network_error")
        if r.status_code >= 500:
            raise ProviderUnavailable(f"http_{r.status_code}", code=f"http_{r.status_code}")
        if r.status_code >= 400:
            raise ProviderError(self._error_text(r), code=f"http_{r.status_code}")
        return self._json(r)

    @staticmethod
    def _json(r) -> dict:
        try:
            data = r.json()
        except ValueError:
            raise ProviderError("не JSON в ответе", code="bad_response")
        return data if isinstance(data, dict) else {"data": data}

    @staticmethod
    def _error_text(r) -> str:
        try:
            data = r.json() or {}
        except ValueError:
            return f"http_{r.status_code}"
        return str(data.get("message") or data.get("error") or f"http_{r.status_code}")[:200]

    # ------------------------------------------------------------------- счета ---

    def create_invoice(self, *, order_id: str, amount_usd: Decimal, pay_currency: str,
                       ipn_url: str, description: str) -> Invoice:
        body = {
            "price_amount": float(amount_usd),
            "price_currency": "usd",
            "pay_currency": str(pay_currency).lower(),
            "order_id": order_id,
            "order_description": _ascii(description),
            "ipn_callback_url": ipn_url,
            # Фиксированный курс: сумма в монете не должна плыть, пока человек
            # копирует адрес и открывает кошелёк.
            "is_fixed_rate": True,
            "is_fee_paid_by_user": False,
        }
        data = self._post("/payment", body)

        # Сверяем, что нам ответили про НАШ счёт: перепутанный order_id или
        # валюта означают, что дальше всё пойдёт не туда.
        if str(data.get("order_id") or "") != order_id:
            raise ProviderError("процессор вернул чужой order_id", code="order_mismatch")
        if str(data.get("price_currency") or "").lower() != "usd":
            raise ProviderError("цена не в долларах", code="price_currency_mismatch")
        address = str(data.get("pay_address") or "").strip()
        provider_id = str(data.get("payment_id") or "").strip()
        pay_amount = _dec(data.get("pay_amount"))
        if not address or not provider_id or pay_amount <= 0:
            raise ProviderError("процессор не дал адрес или сумму", code="incomplete_invoice")

        info = currencies.describe(str(data.get("pay_currency") or pay_currency))
        network = str(data.get("network") or "").strip() or info.network
        return Invoice(
            provider=self.name,
            provider_id=provider_id,
            order_id=order_id,
            price_amount=_dec(data.get("price_amount"), str(amount_usd)),
            price_currency="USD",
            pay_currency=str(data.get("pay_currency") or pay_currency).lower(),
            pay_coin=info.coin,
            pay_network=network,
            pay_address=address,
            pay_extra_id=str(data.get("payin_extra_id") or "").strip(),
            pay_amount=pay_amount,
            expires_at=_parse_dt(data.get("expiration_estimate_date")),
            raw=data,
        )

    def fetch_invoice(self, provider_id: str) -> InvoiceState:
        data = self._get(f"/payment/{provider_id}")
        return self._to_state(data)

    def _to_state(self, data: dict) -> InvoiceState:
        """Единственное место, где чужие поля превращаются в наши.

        Если процессор переименует поле, чинить придётся только здесь.
        """
        provider_status = str(data.get("payment_status") or "").strip().lower()
        return InvoiceState(
            provider_id=str(data.get("payment_id") or "").strip(),
            order_id=str(data.get("order_id") or "").strip(),
            status=_STATUS_MAP.get(provider_status, UNKNOWN),
            provider_status=provider_status,
            price_amount=_dec(data.get("price_amount")),
            price_currency=str(data.get("price_currency") or "").upper(),
            pay_currency=str(data.get("pay_currency") or "").lower(),
            pay_amount=_dec(data.get("pay_amount")),
            actually_paid=_dec(data.get("actually_paid")),
            pay_address=str(data.get("pay_address") or "").strip()[:160],
            pay_extra_id=str(data.get("payin_extra_id") or "").strip()[:160],
            actually_paid_fiat=(_dec(data.get("actually_paid_at_fiat"))
                                if data.get("actually_paid_at_fiat") not in (None, "") else None),
            tx_hash=str(data.get("payin_hash") or "").strip()[:160],
            confirmations=(int(data["confirmations"])
                           if str(data.get("confirmations") or "").isdigit() else None),
            provider_updated_at=str(data.get("updated_at") or "")[:40],
            raw=data,
        )

    # ------------------------------------------------------------------ вебхук ---

    def verify_webhook(self, request) -> Optional[dict]:
        """Проверить подпись вебхука. None — не наш, обрабатывать нельзя.

        Подпись — HMAC-SHA512 от JSON с отсортированными ключами. Сравнение
        только через compare_digest: обычное сравнение строк утекает по
        времени и даёт подобрать подпись побайтно.
        """
        if not self._ipn_secret:
            logger.warning("crypto: вебхук пришёл, а секрет IPN не настроен")
            return None

        signature = (request.headers.get("x-nowpayments-sig") or "").strip().lower()
        raw = request.body or b""
        if len(signature) != 128 or any(c not in "0123456789abcdef" for c in signature):
            return None
        try:
            body = json.loads(raw)
        except (ValueError, TypeError):
            return None
        if not isinstance(body, dict):
            return None

        def ordered(node):
            if isinstance(node, dict):
                return {key: ordered(node[key]) for key in sorted(node)}
            if isinstance(node, list):
                return [ordered(item) for item in node]
            return node

        canonical = ordered(body)
        # Два варианта сериализации: их библиотека может экранировать
        # не-ASCII, а может и нет. Мы всё равно шлём только ASCII, но чужое
        # поле в теле не должно ломать проверку.
        candidates = (
            json.dumps(canonical, separators=(",", ":"), ensure_ascii=True),
            json.dumps(canonical, separators=(",", ":"), ensure_ascii=False),
        )
        secret = self._ipn_secret.encode("utf-8")
        for message in candidates:
            digest = hmac.new(secret, message.encode("utf-8"), hashlib.sha512).hexdigest()
            if hmac.compare_digest(digest, signature):
                return body
        return None

    # ------------------------------------------------------------------ монеты ---

    def list_currencies(self) -> list:
        """Коды монет, включённые в кабинете процессора."""
        data = self._get("/merchant/coins")
        raw = data.get("selectedCurrencies") or data.get("currencies") or []
        return [str(code).lower() for code in raw if str(code).strip()]

    def min_amount_usd(self, pay_currency: str) -> Optional[Decimal]:
        """Минимальная сумма перевода этой монетой, в долларах.

        Ниже неё сеть просто съест платёж комиссией, и процессор его не примет.
        """
        try:
            data = self._get("/min-amount", params={
                "currency_from": str(pay_currency).lower(),
                "currency_to": "usd",
                "fiat_equivalent": "usd",
                "is_fixed_rate": "true",
            }, attempts=2)
        except ProviderError:
            return None
        value = data.get("fiat_equivalent")
        if value in (None, ""):
            return None
        amount = _dec(value)
        return amount if amount > 0 else None

    def healthcheck(self) -> dict:
        """Кнопка «Проверить подключение» в админке."""
        if not self.is_configured():
            return {"ok": False, "error": "API-ключ не задан", "sandbox": self._sandbox}
        try:
            coins = self.list_currencies()
        except ProviderError as exc:
            return {"ok": False, "error": str(exc)[:200], "sandbox": self._sandbox}
        return {
            "ok": True,
            "error": None,
            "sandbox": self._sandbox,
            "coins": len(coins),
            "ipn_secret_set": bool(self._ipn_secret),
        }
