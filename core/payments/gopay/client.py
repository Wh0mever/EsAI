"""Подписанный клиент GoPay: создание, статус, отмена счёта и список банков.

Три правила, на которых всё держится:

* тело запроса сериализуется ОДИН раз, и ровно эти байты и подписываются, и
  отправляются (requests.post(data=...), никогда json=...). Иначе requests
  собрал бы JSON по-своему — с пробелами и \\uXXXX, — и подпись не сошлась бы
  на первом же русском слове в описании;
* клиент ничего не повторяет сам. «Создать» — не идемпотентная операция:
  что делать после обрыва (спросить по номеру заказа), решает service;
* ни ключ, ни секрет, ни подпись, ни одноразовая строка не попадают в текст
  исключений и в журнал. В журнал идут только номера, коды и суммы.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import logging
import re
import uuid
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal, InvalidOperation

import requests

from . import config
from .config import Credentials

logger = logging.getLogger("payments.gopay")

ORDER_ID_MAX = 32          # предел GoPay; длиннее он не примет, а мы не узнаем почему
NONCE_MAX = 64
SYNTHETIC_EMAIL_SUFFIX = "@social.esai.local"   # почта-заглушка аккаунта из Telegram

# Что мы готовы отправить в поле типа uri: https и никаких пробелов и кавычек.
RETURN_URL_RE = re.compile(r'https://[^\s"<>\\^`{|}]{1,1990}')
_SIGNATURE_RE = re.compile(r"[0-9A-Fa-f]{128}")
_DATE_RE = re.compile(r"\d{4}-\d{2}-\d{2}")

# (соединение, чтение), секунды. Статус спрашивают сверка и вебхук — коротко,
# чтобы зависший GoPay не занял общую очередь Celery.
TIMEOUT_CREATE = (5, 15)
TIMEOUT_QUERY = (3, 5)
TIMEOUT_CANCEL = (5, 10)
TIMEOUT_APPS = (5, 8)


# ------------------------------------------------------------- подпись ---

def serialize(data: dict) -> bytes:
    """Тело запроса: компактный JSON в настоящем UTF-8, порядок ключей как собрали."""
    return json.dumps(data, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def new_nonce() -> str:
    return uuid.uuid4().hex


def sign(secret: str, nonce: str, body: bytes) -> str:
    """HMAC-SHA512(секрет, nonce + "\\n" + тело + "\\n"), шестнадцатерично, заглавными."""
    return hmac.new(secret.encode("utf-8"), nonce.encode("utf-8") + b"\n" + body + b"\n",
                    hashlib.sha512).hexdigest().upper()


def verify_signature(secret: str, nonce: str, body: bytes, signature: str) -> bool:
    """Проверить подпись входящего вебхука. body — байты ровно как пришли."""
    if not secret or not nonce or len(nonce) > NONCE_MAX:
        return False
    if not isinstance(signature, str) or not isinstance(body, (bytes, bytearray)):
        return False
    given = signature.strip()
    # Форму проверяем до сравнения: compare_digest на строках с не-ASCII бросает.
    if not _SIGNATURE_RE.fullmatch(given):
        return False
    try:
        return hmac.compare_digest(sign(secret, nonce, bytes(body)), given.upper())
    except Exception:  # noqa: BLE001 — кривой заголовок не должен ронять обработчик
        return False


# -------------------------------------------------------------- ошибки ---

class GoPayError(RuntimeError):
    """Ошибка обмена с GoPay.

    code — наш короткий код (уходит в Payment.error и в журнал), kind — класс
    причины, по которому ветвится вызывающий код, provider_code — код GoPay
    как есть. Денежная логика на provider_code не ветвится: в документации два
    противоречащих списка кодов.
    """

    def __init__(self, message: str = "", *, code: str = "gopay_error", kind: str = "other",
                 provider_code: str = "", http_status: int | None = None):
        self.message = str(message or "")
        self.code = str(code or "gopay_error")
        self.kind = str(kind or "other")
        self.provider_code = str(provider_code or "")
        self.http_status = http_status
        super().__init__(f"{self.code}: {self.message[:160]}")


class GoPayUnavailable(GoPayError):
    """GoPay не ответил или ответил невнятно: исход запроса НЕИЗВЕСТЕН."""

    def __init__(self, message: str = "", *, code: str = "unavailable", kind: str = "unavailable",
                 provider_code: str = "", http_status: int | None = None):
        super().__init__(message, code=code, kind="unavailable",
                         provider_code=provider_code, http_status=http_status)


class GoPayRejected(GoPayError):
    """GoPay ответил и отказал."""


# Точные коды GoPay. Когда код известен, текст ошибки не читаем вовсе: для 0013
# документация кладёт туда «статус банка» — формулировка может быть любой.
_CODE_KINDS = {
    "0013": ("cannot_cancel", "cannot_cancel"),
    "0015": ("cancel_retry", "cancel_retry"),
    "0016": ("org_inactive", "org_inactive"),
    "0004": ("rate_limited", "rate_limited"),
    "4005": ("duplicate", "duplicate_order"),
    "4041": ("not_found", "not_found"),
    "4001": ("auth", "auth"),
    "4002": ("auth", "auth"),
    "4003": ("invalid", "invalid_request"),
    "4004": ("invalid", "invalid_request"),
}
# Внутренняя ошибка на их стороне: исход неизвестен, как при обрыве связи.
_CODES_UNAVAILABLE = ("5001", "9999")
_DUPLICATE_WORDS = ("duplic", "already exist", "дубл", "уже существ")
_AUTH_WORDS = ("signature", "подпис", "api key", "api-ключ")


def _classify(code: str, message: str, http_status: int) -> tuple[str, str]:
    """(kind, наш код) для отказа GoPay."""
    if code in _CODE_KINDS:
        return _CODE_KINDS[code]
    msg = message.lower()
    # «not_found» по тексту не выводим никогда: «API key not found» не должен
    # превратить живой счёт в несуществующий. Только код 4041.
    if any(word in msg for word in _DUPLICATE_WORDS):
        return "duplicate", "duplicate_order"
    if any(word in msg for word in _AUTH_WORDS) or http_status in (401, 403):
        return "auth", "auth"
    if http_status == 400:
        return "invalid", "invalid_request"
    return "other", "rejected"


# ---------------------------------------------------- состояние платежа ---

STATUS_MAP = {"CREATED": "created", "PENDING": "pending", "COMMITTED": "committed",
              "FAILED": "failed", "EXPIRED": "expired", "CANCELLED": "cancelled",
              "CANCELED": "cancelled"}

_RAW_KEYS = ("payment_id", "order_id", "amount", "status", "testing_mode", "created_at",
             "expires_at", "committed_at", "bank_op_date")


def parse_testing_mode(value) -> bool | None:
    """Тестовый ли платёж: True / False / None (непонятно).

    GoPay присылает флаг только у тестовых платежей, а типы в его схеме
    гуляют (числа и булевы объявлены строками). Поэтому «истинное не-булево»
    нельзя молча читать ни как тест, ни как бой: None — это расхождение для
    обеих сред, счёт не создаётся и не зачисляется.
    """
    if value is None or value is False:
        return False
    if value is True:
        return True
    if isinstance(value, int):          # bool разобран выше
        return {0: False, 1: True}.get(value)
    if isinstance(value, str):
        text = value.strip().lower()
        if text in ("false", "0", ""):
            return False
        if text in ("true", "1"):
            return True
    return None


def _text(value, limit: int) -> str:
    if isinstance(value, bool):
        return ""
    if isinstance(value, (str, int)):
        return str(value).strip()[:limit]
    return ""


def _amount(value) -> Decimal | None:
    """Сумма ТОЧНО, без округления: «391.996» — это не 392.00, а повод не зачислять."""
    if isinstance(value, bool) or not isinstance(value, (str, int, float, Decimal)):
        return None
    try:
        amount = Decimal(str(value).strip())
    except (InvalidOperation, ValueError):
        return None
    if not amount.is_finite() or amount < 0:
        return None
    if amount.as_tuple().exponent < -2:
        return None
    return amount


@dataclass(frozen=True)
class PaymentState:
    """Платёж глазами GoPay — из ответа API или из тела вебхука, разбор один."""

    payment_id: str = ""
    order_id: str = ""
    status: str = "unknown"
    provider_status: str = ""
    amount: Decimal | None = None
    testing_mode: bool | None = False
    qr_data: str = ""
    qr_url: str = ""
    checkout_url: str = ""
    app_links: dict = field(default_factory=dict)
    expires_at_raw: str = ""
    committed_at_raw: str = ""
    created_at_raw: str = ""
    bank_op_date: str = ""
    raw: dict = field(default_factory=dict)

    @classmethod
    def from_payload(cls, data) -> "PaymentState":
        """Никогда не бросает: неизвестные ключи игнорируются, мусор даёт пустое состояние."""
        if not isinstance(data, dict):
            return cls()
        try:
            return cls._parse(data)
        except Exception:  # noqa: BLE001 — кривой ответ не должен ронять обработчик
            logger.warning("gopay: не удалось разобрать состояние платежа")
            return cls()

    @classmethod
    def _parse(cls, data: dict) -> "PaymentState":
        provider_status = _text(data.get("status"), 32).upper()
        links = data.get("app_links")
        app_links = ({k: v for k, v in links.items() if isinstance(k, str) and isinstance(v, str)}
                     if isinstance(links, dict) else {})
        op_date = _text(data.get("bank_op_date"), 10)
        if op_date:
            try:
                date.fromisoformat(op_date)
                if not _DATE_RE.fullmatch(op_date):
                    op_date = ""
            except ValueError:
                op_date = ""

        raw = {}
        for key in _RAW_KEYS:
            if key not in data:
                continue
            value = data[key]
            # Только строки и булевы из белого списка: это попадёт в Payment.response.
            if isinstance(value, bool):
                raw[key] = value
            elif isinstance(value, str):
                raw[key] = value[:64]
            elif isinstance(value, (int, float)):
                raw[key] = str(value)[:64]

        def string(key: str, limit: int) -> str:
            value = data.get(key)
            return value.strip()[:limit] if isinstance(value, str) else ""

        qr_data = data.get("qr_data")
        return cls(
            payment_id=_text(data.get("payment_id"), 64),
            order_id=_text(data.get("order_id"), 64),
            status=STATUS_MAP.get(provider_status, "unknown"),
            provider_status=provider_status,
            amount=_amount(data.get("amount")),
            testing_mode=parse_testing_mode(data.get("testing_mode")),
            # Содержимое QR не трогаем вовсе: ни пробелов, ни регистра, ни длины.
            qr_data=qr_data if isinstance(qr_data, str) else "",
            qr_url=string("qr_url", 2000),
            checkout_url=string("checkout_url", 2000),
            app_links=app_links,
            expires_at_raw=string("expires_at", 40),
            committed_at_raw=string("committed_at", 40),
            created_at_raw=string("created_at", 40),
            bank_op_date=op_date,
            raw=raw,
        )


# -------------------------------------------------------------- клиент ---

def _ios_flag(value) -> bool | None:
    """Поддержка iOS: True / False / None (GoPay не сказал).

    bool("false") в Python — True, поэтому строки разбираем руками: банк,
    которого на iPhone нет, нельзя показать там кнопкой.
    """
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        return {0: False, 1: True}.get(value)
    if isinstance(value, str):
        text = value.strip().lower()
        if text in ("true", "1"):
            return True
        if text in ("false", "0", ""):
            return False
    return None


def _app_order(value) -> int:
    if isinstance(value, bool):
        return 999
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        try:
            return int(value.strip())
        except ValueError:
            return 999
    return 999


def _normalize_app(item) -> dict | None:
    if not isinstance(item, dict):
        return None
    code = _text(item.get("code"), 32)
    if not code:
        return None

    def text(key: str, limit: int) -> str:
        value = item.get(key)
        return value.strip()[:limit] if isinstance(value, str) else ""

    return {
        "code": code,
        "name": text("name", 64),
        "order": _app_order(item.get("order")),
        "icon": text("icon", 500),
        "url": text("url", 2000),
        "android_package_name": text("android_package_name", 128),
        "is_active_on_ios": _ios_flag(item.get("is_active_on_ios")),
    }


def _check_order_id(order_id: str) -> None:
    if len(order_id) > ORDER_ID_MAX:
        raise ValueError(f"gopay: order_id длиннее {ORDER_ID_MAX} символов")


class GoPayClient:
    def __init__(self, creds: Credentials, *, base_url: str | None = None):
        self._creds = creds
        self._base = str(base_url if base_url is not None else config.api_base_url()).rstrip("/")

    def __repr__(self) -> str:
        return f"GoPayClient(env={self._creds.env!r})"

    # --- один обмен ---------------------------------------------------------

    def _scrub(self, text: str) -> str:
        """Убрать из текста GoPay наши же ключи, если он их вдруг повторил."""
        for value in (self._creds.api_secret, self._creds.webhook_secret, self._creds.api_key):
            if value and value in text:
                text = text.replace(value, "…")
        return text

    def _post(self, path: str, data: dict, timeout: tuple):
        if not self._base or not self._creds.complete:
            raise GoPayError("GoPay не настроен", code="not_configured", kind="not_configured")
        body = serialize(data)          # сериализуем один раз: эти байты и подписываем, и шлём
        nonce = new_nonce()             # новая на каждый HTTP-запрос, включая повторы
        headers = {
            "Content-Type": "application/json",
            "GoPay-Api-Key": self._creds.api_key,
            "GoPay-Nonce": nonce,
            "GoPay-Signature": sign(self._creds.api_secret, nonce, body),
        }
        try:
            response = requests.post(self._base + path, data=body, headers=headers,
                                     timeout=timeout, allow_redirects=False)
        except requests.RequestException as exc:
            # from None: к исключению requests прицеплен запрос с нашими заголовками.
            raise GoPayUnavailable(type(exc).__name__, code="network") from None

        status = int(getattr(response, "status_code", 0) or 0)
        if status >= 500 or status in (408, 429):
            raise GoPayUnavailable(f"HTTP {status}", code=f"http_{status}", http_status=status)
        ok_http = 200 <= status < 300
        try:
            payload = response.json()
        except Exception:  # noqa: BLE001 — не JSON
            payload = None
        if not isinstance(payload, dict):
            if ok_http:
                raise GoPayUnavailable("ответ не JSON", code="bad_response", http_status=status)
            # 404/405 несуществующего метода, 401/403 от WAF или блокировки по IP.
            raise GoPayRejected(f"HTTP {status}", code=f"http_{status}",
                                kind="auth" if status in (401, 403) else "other",
                                provider_code="", http_status=status)

        code = payload.get("code")
        if ok_http and payload.get("status") == "OK":
            # Не проверка на истинность: пустой список — нормальный ответ
            # (у тестового ключа может не быть ни одного банка).
            if "data" in payload and payload["data"] is not None:
                if code not in ("0000", "", None):
                    logger.warning("gopay %s: status OK с кодом %s", path, _text(code, 16))
                return payload["data"]
            raise GoPayUnavailable("OK без data", code="bad_response", http_status=status)

        provider_code = str(code or "")[:16]
        message = self._scrub(str(payload.get("error_message") or ""))[:300]
        if provider_code in _CODES_UNAVAILABLE:
            raise GoPayUnavailable(message, code="provider_error", provider_code=provider_code,
                                   http_status=status)
        kind, our_code = _classify(provider_code, message, status)
        raise GoPayRejected(message, code=our_code, kind=kind, provider_code=provider_code,
                            http_status=status)

    def _payment_call(self, path: str, timeout: tuple, *, payment_id: str,
                      order_id: str) -> PaymentState:
        payment_id, order_id = str(payment_id or ""), str(order_id or "")
        if not payment_id and not order_id:
            raise ValueError("gopay: нужен payment_id или order_id")
        _check_order_id(order_id)
        # У GoPay приоритет у payment_id — его и шлём, если он есть.
        body = {"payment_id": payment_id} if payment_id else {"order_id": order_id}
        return PaymentState.from_payload(self._post(path, body, timeout))

    # --- методы API ---------------------------------------------------------

    def create_payment(self, *, order_id: str, amount: Decimal, description: str, lifetime: int,
                       buyer_email: str = "", success_url: str = "",
                       failure_url: str = "") -> PaymentState:
        order_id = str(order_id or "")
        if not order_id:
            raise ValueError("gopay: пустой order_id")
        _check_order_id(order_id)
        amount = Decimal(amount)
        if not amount.is_finite() or amount != amount.quantize(Decimal("0.01")):
            # format(".2f") округлил бы молча — а счёт должен быть ровно на сумму заказа.
            raise ValueError("gopay: сумма должна быть с точностью до тыйына")

        body: dict = {"order_id": order_id, "amount": format(amount, ".2f")}
        description = str(description or "")[:255]
        if description:
            body["description"] = description
        body["lifetime"] = int(lifetime)
        success_url, failure_url = str(success_url or ""), str(failure_url or "")
        # Адреса возврата нужны только странице GoPay. Шлём их парой и только
        # годные: из-за адреса, которым на нашем экране никто не пользуется,
        # покупка сорваться не должна.
        if RETURN_URL_RE.fullmatch(success_url) and RETURN_URL_RE.fullmatch(failure_url):
            body["success_url"] = success_url
            body["failure_url"] = failure_url
        email = str(buyer_email or "").strip()
        # Почту шлём, только если это настоящий ящик: у аккаунта из Telegram она
        # заглушка, и чек налоговой ушёл бы в никуда.
        if (email and "@" in email and len(email) <= 254
                and not email.lower().endswith(SYNTHETIC_EMAIL_SUFFIX)):
            body["buyer"] = {"email": email}
        # Никогда: callback_url (старый канал), testing_mode (режим выбирает ключ),
        # items (для услуг не нужны), buyer.phone.
        return PaymentState.from_payload(self._post("/v1/payments", body, TIMEOUT_CREATE))

    def query_payment(self, *, payment_id: str = "", order_id: str = "") -> PaymentState:
        return self._payment_call("/v1/payments/query", TIMEOUT_QUERY,
                                  payment_id=payment_id, order_id=order_id)

    def cancel_payment(self, *, payment_id: str = "", order_id: str = "") -> PaymentState:
        return self._payment_call("/v1/payments/cancel", TIMEOUT_CANCEL,
                                  payment_id=payment_id, order_id=order_id)

    def payment_apps(self, platform: str = "any") -> list[dict]:
        """Банковские приложения с шаблонами ссылок. Пустой список — нормальный ответ."""
        data = self._post("/v1/payment-app", {"platform": str(platform or "any")}, TIMEOUT_APPS)
        if isinstance(data, dict):
            data = [data]
        if not isinstance(data, list):
            return []
        apps = []
        for item in data:
            app = _normalize_app(item)
            if app is not None:
                apps.append(app)
        return apps

    def healthcheck(self) -> dict:
        """Безвредный подписанный запрос для кнопки «Проверить соединение». Не бросает."""
        try:
            return {"ok": True, "apps": len(self.payment_apps("any"))}
        except GoPayError as exc:
            return {"ok": False, "kind": exc.kind, "code": exc.code,
                    "provider_code": exc.provider_code, "http_status": exc.http_status,
                    "provider_message": exc.message[:160]}
        except Exception as exc:  # noqa: BLE001 — кнопка в админке не должна давать 500
            return {"ok": False, "kind": "other", "code": "client_error", "provider_code": "",
                    "http_status": None, "provider_message": type(exc).__name__}


def get_client(env: str) -> GoPayClient:
    """Клиент с ключами ИМЕННО этой среды (а не «выбранной сейчас»)."""
    try:
        creds = config.credentials(env)
    except ValueError:
        creds = None
    if creds is None or not creds.complete or not config.api_base_url():
        raise GoPayError("GoPay не настроен", code="not_configured", kind="not_configured")
    return GoPayClient(creds)
