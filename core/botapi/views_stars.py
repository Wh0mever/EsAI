"""Сервисные эндпоинты оплаты Telegram Stars (подписанные запросы бота)."""
from __future__ import annotations

import logging

from rest_framework import status
from rest_framework.response import Response

from payments.models import StarInvoice
from plans.models import TokenPackage

from . import stars
from .views import BotServiceView, _user_payload

logger = logging.getLogger("botapi.stars")


def _error(exc: stars.StarsError) -> Response:
    return Response({"detail": exc.code, **exc.extra}, status=exc.http)


def _telegram_id(data) -> int | None:
    raw = str((data or {}).get("telegram_id") or "").strip()
    return int(raw) if raw.isdigit() else None


class StarsInvoiceView(BotServiceView):
    """POST /api/bot/stars/invoice/ {telegram_id, package_id, lang} → данные для sendInvoice."""

    def post(self, request):
        data = request.data or {}
        telegram_id = _telegram_id(data)
        if not telegram_id:
            return Response({"detail": "bad_telegram_id"}, status=status.HTTP_400_BAD_REQUEST)
        user = stars.user_for_telegram(telegram_id)
        if not user:
            return Response({"detail": "user_not_found"}, status=status.HTTP_404_NOT_FOUND)
        try:
            package = TokenPackage.objects.get(pk=int(data.get("package_id")))
        except (TokenPackage.DoesNotExist, TypeError, ValueError):
            return Response({"detail": "package_not_found"}, status=status.HTTP_404_NOT_FOUND)
        lang = str(data.get("lang") or "ru")[:2]
        try:
            payload = stars.create_invoice(user, package, telegram_id, lang)
        except stars.StarsError as exc:
            return _error(exc)
        return Response(payload)


class StarsInvoiceMessageView(BotServiceView):
    """POST /api/bot/stars/invoice/message/ — запомнить id сообщения со счётом."""

    def post(self, request):
        data = request.data or {}
        stars.set_invoice_message(str(data.get("payload") or ""), data.get("message_id"))
        return Response({"ok": True})


class StarsPrecheckView(BotServiceView):
    """POST /api/bot/stars/precheck/ — можно ли отвечать ok на pre_checkout_query."""

    def post(self, request):
        data = request.data or {}
        telegram_id = _telegram_id(data)
        if not telegram_id:
            return Response({"detail": "bad_telegram_id"}, status=status.HTTP_400_BAD_REQUEST)
        try:
            invoice = stars.precheck(telegram_id, str(data.get("payload") or ""),
                                     data.get("total_amount"), data.get("currency"))
        except stars.StarsError as exc:
            return _error(exc)
        return Response({"ok": True, "order_id": invoice.payment.order_id,
                         "stars": invoice.stars_amount, "tokens": invoice.total_tokens})


class StarsConfirmView(BotServiceView):
    """POST /api/bot/stars/confirm/ — successful_payment → кредиты на баланс.

    Если суммы не сошлись или счёт уже оплачен другим платежом, деньги
    возвращаем сами и отвечаем 409: бот покажет человеку, что оплата
    вернулась, а не «зависла».
    """

    def post(self, request):
        data = request.data or {}
        telegram_id = _telegram_id(data)
        if not telegram_id:
            return Response({"detail": "bad_telegram_id"}, status=status.HTTP_400_BAD_REQUEST)
        charge_id = str(data.get("telegram_payment_charge_id") or "").strip()
        try:
            result = stars.confirm(
                telegram_id, str(data.get("payload") or ""), charge_id,
                provider_charge_id=str(data.get("provider_payment_charge_id") or ""),
                total_amount=data.get("total_amount"),
                currency=str(data.get("currency") or stars.CURRENCY),
                raw=data.get("raw") if isinstance(data.get("raw"), dict) else {},
            )
        except stars.StarsError as exc:
            refunded = False
            if exc.code in ("amount_mismatch", "currency_mismatch", "user_mismatch",
                            "double_payment", "package_inactive") and charge_id:
                refunded = stars.auto_refund(telegram_id, charge_id, exc.code)
            return Response({"detail": exc.code, "refunded": refunded,
                             **{k: v for k, v in exc.extra.items() if k != "charge_id"}},
                            status=exc.http)
        user = stars.user_for_telegram(telegram_id)
        return Response({**result, "user": _user_payload(user) if user else None})


class StarsRefundedView(BotServiceView):
    """POST /api/bot/stars/refunded/ — апдейт refunded_payment: изъять кредиты."""

    def post(self, request):
        data = request.data or {}
        try:
            result = stars.mark_refunded(
                charge_id=str(data.get("telegram_payment_charge_id") or ""),
                payload=str(data.get("payload") or ""),
                reason="telegram_refund",
            )
        except stars.StarsError as exc:
            return _error(exc)
        return Response(result)


class StarsStatusView(BotServiceView):
    """POST /api/bot/stars/status/ {payload} — что со счётом (для повторов бота)."""

    def post(self, request):
        payload = str((request.data or {}).get("payload") or "")
        invoice = StarInvoice.objects.filter(payload=payload).select_related("payment").first()
        if not invoice:
            return Response({"detail": "not_found"}, status=status.HTTP_404_NOT_FOUND)
        return Response({"status": invoice.status, "stars": invoice.stars_amount,
                         "tokens": invoice.total_tokens, "order_id": invoice.payment.order_id,
                         "charge_id": invoice.telegram_payment_charge_id or ""})
