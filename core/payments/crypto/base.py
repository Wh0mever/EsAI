"""Контракт крипто-процессора: чем бы ни платили, наружу одно и то же.

Здесь нет ни сетевых вызовов, ни Django — только формы данных и исключения.
Благодаря этому логика начисления (credit.py) тестируется на подставном
адаптере, без единого обращения к чужому API.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Optional, Protocol

# Статусы счёта. Строки те же, что у CryptoInvoice.STATUS_* — модель здесь
# намеренно не импортируется, чтобы контракт оставался без Django.
WAITING = "waiting"
CONFIRMING = "confirming"
CONFIRMED = "confirmed"
SENDING = "sending"
PARTIALLY_PAID = "partially_paid"
FINISHED = "finished"
FAILED = "failed"
REFUNDED = "refunded"
EXPIRED = "expired"
# Процессор прислал статус, которого мы не знаем: не гадаем, оставляем прежний
# и помечаем счёт на разбор.
UNKNOWN = "unknown"

ALL_STATUSES = (WAITING, CONFIRMING, CONFIRMED, SENDING, PARTIALLY_PAID,
                FINISHED, FAILED, REFUNDED, EXPIRED, UNKNOWN)


class ProviderError(RuntimeError):
    """Процессор отказал осмысленно: кривые параметры, монета выключена.

    Повторять такой запрос бессмысленно — ответ будет тем же.
    """

    def __init__(self, message: str = "", code: str = "provider_error"):
        super().__init__(message or code)
        self.code = code


class ProviderUnavailable(ProviderError):
    """Процессор не ответил: таймаут, 5xx, разрыв связи.

    Повторить можно и нужно: на вебхуке отвечаем 503 (процессор доставит
    ещё раз), в задаче — обычный retry.
    """

    def __init__(self, message: str = "", code: str = "provider_unavailable"):
        super().__init__(message, code)


@dataclass(frozen=True)
class Invoice:
    """Только что созданный счёт: куда, сколько и до какого времени платить."""
    provider: str
    provider_id: str
    order_id: str
    price_amount: Decimal
    price_currency: str
    pay_currency: str
    pay_coin: str
    pay_network: str
    pay_address: str
    pay_extra_id: str
    pay_amount: Decimal
    expires_at: Optional[datetime]
    raw: dict = field(default_factory=dict)


@dataclass(frozen=True)
class InvoiceState:
    """Состояние счёта у процессора — единственный источник правды о деньгах.

    Собирается ТОЛЬКО из ответа на наш собственный запрос (fetch_invoice).
    Тело вебхука сюда не превращается никогда: подпись подтверждает, что
    сообщение от процессора, но не то, что в нём написана правда.
    """
    provider_id: str
    order_id: str
    status: str
    provider_status: str
    price_amount: Decimal
    price_currency: str
    pay_currency: str
    pay_amount: Decimal
    actually_paid: Decimal
    # Адрес и memo приходят и в состоянии: по ним восстанавливается счёт,
    # который у процессора создался, а до нашей базы не доехал.
    pay_address: str = ""
    pay_extra_id: str = ""
    actually_paid_fiat: Optional[Decimal] = None
    tx_hash: str = ""
    confirmations: Optional[int] = None
    provider_updated_at: str = ""
    raw: dict = field(default_factory=dict)


@dataclass(frozen=True)
class CurrencyInfo:
    """Монета в том виде, в каком её показывает витрина."""
    code: str
    coin: str
    network: str
    label: str
    extra_id_required: bool = False
    min_amount_usd: Optional[Decimal] = None
    # low / medium / high — насколько дорого стоит перевод в этой сети.
    # Числа не выдумываем: комиссия плавает, а обманутое ожидание дороже.
    network_cost: str = "medium"
    popular: bool = False


class CryptoProvider(Protocol):
    """Что должен уметь процессор, чтобы его можно было подключить."""

    name: str

    def is_configured(self) -> bool:
        """Ключи на месте — можно работать."""

    def create_invoice(self, *, order_id: str, amount_usd: Decimal, pay_currency: str,
                       ipn_url: str, description: str) -> Invoice:
        ...

    def fetch_invoice(self, provider_id: str) -> InvoiceState:
        ...

    def verify_webhook(self, request) -> Optional[dict]:
        """None — подпись не сошлась. dict — тело вебхука (всё ещё НЕ доверенное)."""

    def list_currencies(self) -> list:
        ...

    def min_amount_usd(self, pay_currency: str) -> Optional[Decimal]:
        ...

    def healthcheck(self) -> dict:
        """{'ok': bool, 'error': str} — для кнопки «Проверить подключение»."""
