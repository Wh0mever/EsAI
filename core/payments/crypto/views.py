"""Эндпоинты криптооплаты: список монет, состояние счёта, вебхук процессора."""
from __future__ import annotations

import hashlib
import logging
from decimal import Decimal

from django.core.cache import cache
from django.db import IntegrityError, transaction
from django.utils import timezone
from rest_framework import status as drf_status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.throttling import AnonRateThrottle, ScopedRateThrottle
from rest_framework.views import APIView
from rest_framework_simplejwt.authentication import JWTAuthentication

from . import base, credit, currencies, rates, registry

logger = logging.getLogger("payments.crypto")

# Больше этого тело вебхука быть не может: всё, что крупнее, даже не разбираем.
MAX_IPN_BODY = 64 * 1024

CURRENCIES_CACHE_KEY = "crypto:currencies:v1"
CURRENCIES_CACHE_TTL = 600
MIN_AMOUNT_CACHE_TTL = 1800

# Куда смотреть транзакцию. Сеть -> шаблон ссылки.
EXPLORERS = {
    "Bitcoin": "https://mempool.space/tx/{tx}",
    "ERC-20": "https://etherscan.io/tx/{tx}",
    "TRC-20": "https://tronscan.org/#/transaction/{tx}",
    "BEP-20": "https://bscscan.com/tx/{tx}",
    "TON": "https://tonviewer.com/transaction/{tx}",
    "Litecoin": "https://blockchair.com/litecoin/transaction/{tx}",
    "Dogecoin": "https://blockchair.com/dogecoin/transaction/{tx}",
    "Solana": "https://solscan.io/tx/{tx}",
    "XRP Ledger": "https://xrpscan.com/tx/{tx}",
}


def explorer_url(network: str, tx_hash: str) -> str:
    template = EXPLORERS.get(str(network or "").strip())
    return template.format(tx=tx_hash) if (template and tx_hash) else ""


def amount_str(value) -> str:
    """Сумма монеты строкой, без экспоненты и без хвоста нулей.

    Человек это число копирует в кошелёк, поэтому «1E-7» здесь недопустимо.
    """
    d = Decimal(value or 0)
    text = f"{d:f}"
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text or "0"


def ui_state(invoice) -> str:
    """Состояние для экрана оплаты — короткое и без внутренней кухни."""
    from ..models import CryptoInvoice

    info = (invoice.payment.request or {}).get("token_purchase") or {}
    total = int(info.get("tokens") or 0) + int(info.get("bonus_tokens") or 0)
    if invoice.payment.success or (total and invoice.credited_tokens >= total):
        return "paid"
    if invoice.status == CryptoInvoice.STATUS_PARTIALLY_PAID or (
            invoice.credited_tokens > 0 and invoice.status in CryptoInvoice.OPEN_STATES):
        return "partially_paid"
    if invoice.status in (CryptoInvoice.STATUS_CONFIRMING, CryptoInvoice.STATUS_CONFIRMED,
                          CryptoInvoice.STATUS_SENDING):
        return "confirming"
    if invoice.status in (CryptoInvoice.STATUS_FAILED, CryptoInvoice.STATUS_REFUNDED):
        return "failed"
    if invoice.status == CryptoInvoice.STATUS_EXPIRED:
        return "expired"
    if invoice.expires_at and invoice.expires_at <= timezone.now():
        return "expired"
    return "awaiting_payment"


def invoice_json(invoice, *, resumed: bool = False) -> dict:
    """Счёт в том виде, в каком его показывает экран оплаты."""
    payment = invoice.payment
    info_pkg = (payment.request or {}).get("token_purchase") or {}
    total = int(info_pkg.get("tokens") or 0) + int(info_pkg.get("bonus_tokens") or 0)
    coin = currencies.describe(invoice.pay_currency)
    remaining = max(Decimal(0), Decimal(invoice.pay_amount) - Decimal(invoice.actually_paid))
    seconds_left = 0
    if invoice.expires_at:
        seconds_left = max(0, int((invoice.expires_at - timezone.now()).total_seconds()))

    return {
        "kind": "crypto",
        "resumed": bool(resumed),
        "order_id": payment.order_id,
        "provider": invoice.provider,
        "status": invoice.status,
        "ui_state": ui_state(invoice),
        "package": {
            "id": info_pkg.get("package_id"),
            "tokens": int(info_pkg.get("tokens") or 0),
            "bonus_tokens": int(info_pkg.get("bonus_tokens") or 0),
        },
        "price": {
            "kgs": str((payment.request or {}).get("kgs_price") or ""),
            "usd": str(invoice.price_amount),
            "currency": invoice.price_currency,
            "rate_kgs_to_usd": str((payment.request or {}).get("rate_kgs_to_usd") or ""),
        },
        "pay": {
            "currency": invoice.pay_currency,
            "coin": invoice.pay_coin or coin.coin,
            "network": invoice.pay_network or coin.network,
            "label": coin.label,
            "address": invoice.pay_address,
            "extra_id": invoice.pay_extra_id or None,
            "extra_id_required": bool(invoice.pay_extra_id),
            "amount": amount_str(invoice.pay_amount),
            "amount_paid": amount_str(invoice.actually_paid),
            "amount_remaining": amount_str(remaining),
        },
        "credits": {"total": total, "credited": int(invoice.credited_tokens or 0)},
        "tx_hash": invoice.tx_hash or None,
        "explorer_url": explorer_url(invoice.pay_network, invoice.tx_hash) or None,
        "confirmations": invoice.confirmations,
        "created_at": invoice.created_at.isoformat() if invoice.created_at else None,
        "expires_at": invoice.expires_at.isoformat() if invoice.expires_at else None,
        "seconds_left": seconds_left,
        "last_checked_at": invoice.last_checked_at.isoformat() if invoice.last_checked_at else None,
        "return_to": (payment.request or {}).get("return_to") or "",
    }


def currencies_payload(user=None) -> dict:
    """Список монет для витрины. Кэшируется: он одинаковый для всех."""
    if not registry.is_enabled_for(user):
        return {"enabled": False, "currencies": []}

    cached = cache.get(CURRENCIES_CACHE_KEY)
    if cached is None:
        allowed = currencies.allowed_codes()
        enabled_at_provider = None
        try:
            adapter = registry.get_adapter()
            enabled_at_provider = set(adapter.list_currencies())
        except base.ProviderError as exc:
            # Процессор недоступен — показываем то, что включил админ. Хуже
            # будет, если витрина опустеет из-за чужого таймаута.
            logger.warning("crypto: список монет процессора недоступен: %s", exc)

        rows = []
        for code in allowed:
            if enabled_at_provider is not None and code not in enabled_at_provider:
                continue
            info = currencies.describe(code, min_amount_usd=_min_amount(code))
            rows.append({
                "code": info.code,
                "coin": info.coin,
                "network": info.network,
                "label": info.label,
                "extra_id_required": info.extra_id_required,
                "network_cost": info.network_cost,
                "popular": info.popular,
                "min_usd": str(info.min_amount_usd) if info.min_amount_usd else None,
            })
        cached = rows
        cache.set(CURRENCIES_CACHE_KEY, cached, CURRENCIES_CACHE_TTL)

    return {
        "enabled": True,
        "rate_kgs_to_usd": str(rates.kgs_to_usd_rate()),
        "currencies": cached,
    }


def _min_amount(code: str):
    """Минимальная сумма для монеты — с кэшем: она меняется медленно."""
    key = f"crypto:min:{code}"
    value = cache.get(key)
    if value is not None:
        return Decimal(value) if value != "" else None
    try:
        amount = registry.get_adapter().min_amount_usd(code)
    except base.ProviderError:
        return None
    cache.set(key, str(amount) if amount else "", MIN_AMOUNT_CACHE_TTL)
    return amount


class CryptoCurrenciesView(APIView):
    """GET /api/payments/crypto/currencies/ — какие монеты принимаем.

    Открыт всем: витрина показывает способ оплаты и гостю, который ещё не
    вошёл. Ничего чувствительного тут нет — только список монет и курс.
    """
    authentication_classes = [JWTAuthentication]
    permission_classes = [AllowAny]
    throttle_classes = [AnonRateThrottle]

    def get(self, request):
        user = request.user if request.user.is_authenticated else None
        return Response(currencies_payload(user))


class CryptoInvoiceStatusView(APIView):
    """GET /api/plans/purchase/crypto/<order_id>/ — что со счётом прямо сейчас.

    Вкладка опрашивает этот адрес, пока человек платит. Сама она у процессора
    ничего не спрашивает: если наши данные подустарели, ставим задачу на
    перепроверку (не чаще раза в 45 секунд на счёт) и отвечаем тем, что есть.
    """
    authentication_classes = [JWTAuthentication]
    permission_classes = [IsAuthenticated]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "crypto_status"

    def get(self, request, order_id: str):
        from ..models import CryptoInvoice

        invoice = (CryptoInvoice.objects
                   .select_related("payment")
                   .filter(payment__order_id=order_id, payment__user=request.user)
                   .first())
        if invoice is None:
            # Именно 404, а не 403: по ответу нельзя перебрать чужие заказы.
            return Response({"detail": "not_found"}, status=drf_status.HTTP_404_NOT_FOUND)

        self._maybe_refresh(invoice)
        invoice.refresh_from_db()
        return Response(invoice_json(invoice))

    @staticmethod
    def _maybe_refresh(invoice) -> None:
        from ..models import CryptoInvoice
        from ..tasks import check_crypto_invoice

        if invoice.status not in CryptoInvoice.OPEN_STATES:
            return
        stale = (invoice.last_checked_at is None
                 or (timezone.now() - invoice.last_checked_at).total_seconds() > 45)
        if not stale:
            return
        if not cache.add(f"crypto:poll:{invoice.id}", "1", 45):
            return
        try:
            check_crypto_invoice.delay(invoice.id)
        except Exception:  # noqa: BLE001 — очередь недоступна, сверка догонит
            logger.warning("crypto: не удалось поставить задачу перепроверки")


class NowPaymentsIpnView(APIView):
    """POST /api/payments/crypto/nowpayments/ipn/ — уведомление процессора.

    Тело уведомления НЕ доверенное. Подпись доказывает, что письмо от
    процессора, дальше берём из него только идентификатор счёта, а суммы и
    статус читаем своим запросом к их API. Прислать «оплачено» и получить
    кредиты бесплатно так нельзя.

    Повторы процессора безвредны: каждое уведомление записывается с уникальным
    ключом, а начисление всё равно идёт по дельте.
    """
    authentication_classes = []
    permission_classes = []
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "crypto_ipn"

    def post(self, request, *args, **kwargs):
        from ..models import CryptoInvoice, CryptoWebhookEvent

        if len(request.body or b"") > MAX_IPN_BODY:
            return Response({"status": "too_large"}, status=drf_status.HTTP_400_BAD_REQUEST)

        adapter = registry.get_adapter()
        body = adapter.verify_webhook(request)
        if body is None:
            logger.warning("crypto: вебхук с неверной подписью")
            return Response({"status": "invalid_signature"},
                            status=drf_status.HTTP_400_BAD_REQUEST)

        provider_id = str(body.get("payment_id") or "").strip()
        if not provider_id:
            return Response({"status": "ok"}, status=drf_status.HTTP_200_OK)

        raw_status = str(body.get("payment_status") or "")
        raw_paid = str(body.get("actually_paid") or "0")
        event_key = hashlib.sha256(
            f"{adapter.name}|{provider_id}|{raw_status}|{raw_paid}|{body.get('updated_at')}"
            .encode("utf-8")).hexdigest()

        try:
            # Точка сохранения обязательна: запросы обёрнуты в транзакцию
            # (ATOMIC_REQUESTS), и без неё нарушение уникальности сломало бы
            # всю транзакцию — повтор вебхука падал бы с ошибкой вместо
            # тихого «уже обработано».
            with transaction.atomic():
                event = CryptoWebhookEvent.objects.create(
                    provider=adapter.name, provider_invoice_id=provider_id,
                    event_key=event_key, status=raw_status[:24],
                    actually_paid=Decimal(raw_paid or 0), payload=body, signature_ok=True,
                )
        except (IntegrityError, ValueError, TypeError):
            event = CryptoWebhookEvent.objects.filter(event_key=event_key).first()
            if event is not None and event.processed:
                return Response({"status": "duplicate"}, status=drf_status.HTTP_200_OK)
            if event is None:
                return Response({"status": "ok"}, status=drf_status.HTTP_200_OK)

        # Единственный доверенный источник — ответ процессора на НАШ запрос.
        try:
            state = adapter.fetch_invoice(provider_id)
        except base.ProviderUnavailable as exc:
            logger.warning("crypto: не удалось перезапросить счёт %s: %s", provider_id, exc)
            # 503 — процессор доставит уведомление ещё раз; плюс догонит сверка.
            return Response({"status": "retry_later"},
                            status=drf_status.HTTP_503_SERVICE_UNAVAILABLE)
        except base.ProviderError as exc:
            event.result = f"fetch_failed:{exc.code}"
            event.save(update_fields=["result"])
            return Response({"status": "ok"}, status=drf_status.HTTP_200_OK)

        invoice = (CryptoInvoice.objects.select_related("payment")
                   .filter(provider_invoice_id=provider_id).first())
        if invoice is None:
            invoice = credit.adopt_orphan_invoice(adapter.name, state)
        if invoice is None:
            event.processed = True
            event.result = "unknown_invoice"
            event.save(update_fields=["processed", "result"])
            return Response({"status": "ok"}, status=drf_status.HTTP_200_OK)

        result = credit.apply_provider_status(invoice, state, source="ipn")
        event.processed = True
        event.result = result[:64]
        event.save(update_fields=["processed", "result"])
        return Response({"status": "ok"}, status=drf_status.HTTP_200_OK)
