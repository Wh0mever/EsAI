"""Единственное место, где криптосчёт меняет состояние и начисляет кредиты.

Правила, на которых всё держится:

* начисляем ТОЛЬКО по состоянию, которое сами запросили у процессора
  (InvoiceState), — телу вебхука не верим никогда;
* начисляем ДЕЛЬТУ: положено минус уже начислено. Поэтому повтор вебхука,
  ручная перепроверка и сверка по расписанию не могут заплатить дважды, а
  недоплата с последующей доплатой закрывается сама;
* пришло меньше — даём пропорционально, счёт остаётся открытым;
* пришло больше — тоже пропорционально, но не выше потолка: перевод в десять
  раз больше суммы разбирает человек, а не автомат;
* возврат крипты автоматом не делаем — её нельзя отозвать, и клавбэк кредитов
  тут только пометка для ручного разбора.
"""
from __future__ import annotations

import logging
from datetime import timedelta
from decimal import Decimal, ROUND_FLOOR

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from . import base

logger = logging.getLogger("payments.crypto")

# Расхождение цены, которое считаем округлением процессора, а не подменой.
PRICE_EPS = Decimal("0.01")


def _tolerance() -> Decimal:
    return Decimal(str(getattr(settings, "CRYPTO_FULL_TOLERANCE_PERCENT", 0.5))) / Decimal(100)


def _overpay_cap() -> Decimal:
    return Decimal(str(getattr(settings, "CRYPTO_OVERPAY_CAP_PERCENT", 200))) / Decimal(100)


def entitled_credits(total: int, expected: Decimal, paid: Decimal):
    """Сколько кредитов положено за фактически пришедшую сумму.

    total    — кредиты за пакет (снимок на момент покупки);
    expected — сумма, которую мы просили перевести;
    paid     — сколько реально пришло.

    Возвращает (кредиты, вид): full / partial / over / over_capped /
    nothing_paid / anomaly_ratio. Статус счёта здесь не смотрим — какие
    статусы вообще дают право на начисление, решает вызывающий.
    """
    total = int(total or 0)
    expected = Decimal(expected or 0)
    paid = Decimal(paid or 0)
    if total <= 0:
        return 0, "no_package"
    if paid <= 0 or expected <= 0:
        return 0, "nothing_paid"

    ratio = paid / expected
    # Стократная переплата — это не щедрость, а ошибка на нашей или их стороне.
    if ratio > Decimal(100):
        return 0, "anomaly_ratio"

    tol = _tolerance()
    if ratio < (Decimal(1) - tol):
        # Недоплата: комиссию сети часто не учитывают. Даём пропорционально и
        # оставляем счёт открытым — доплата дозачислит остальное.
        credits = int((Decimal(total) * ratio).to_integral_value(rounding=ROUND_FLOOR))
        return max(credits, 1), "partial"

    if ratio <= (Decimal(1) + tol):
        # Копеечная недостача или ровная сумма — считаем полной оплатой.
        return total, "full"

    cap = _overpay_cap()
    capped = min(ratio, cap)
    credits = int((Decimal(total) * capped).to_integral_value(rounding=ROUND_FLOOR))
    return credits, ("over" if ratio <= cap else "over_capped")


def _package_total(payment) -> int:
    info = (payment.request or {}).get("token_purchase") or {}
    return int(info.get("tokens") or 0) + int(info.get("bonus_tokens") or 0)


def _append_callback(payment, source: str, state) -> None:
    response = payment.response or {}
    callbacks = list(response.get("callbacks") or [])
    callbacks.append({"type": f"crypto_{source}", "payload": state.raw})
    # История нужна для разбора, но она не должна разрастаться без предела.
    response["callbacks"] = callbacks[-40:]
    payment.response = response


def apply_provider_status(invoice, state, source: str = "ipn") -> str:
    """Применить состояние счёта у процессора. Возвращает что произошло.

    Итоги: credited / noop / flagged / amount_mismatch / no_user.
    Вызывается с вебхука, из сверки и из админской перепроверки — код один и
    тот же, разница только в source (он попадает в журнал и в meta начисления).
    """
    from ..models import CryptoInvoice, Payment
    from ..views import _apply_purchase_credit, _log_payment_event

    result = "noop"
    log_kind = ""
    with transaction.atomic():
        inv = (CryptoInvoice.objects.select_for_update()
               .select_related("payment").get(pk=invoice.pk))
        pay = Payment.objects.select_for_update().get(pk=inv.payment_id)

        # --- сверка: точно ли это наш счёт и наша сумма ---------------------
        mismatch = ""
        if state.order_id and state.order_id != (pay.order_id or ""):
            mismatch = "order_id"
        elif state.price_currency and state.price_currency.upper() != (inv.price_currency or "USD").upper():
            mismatch = "price_currency"
        elif state.price_amount > 0 and abs(state.price_amount - inv.price_amount) > PRICE_EPS:
            mismatch = "price_amount"
        elif state.pay_currency and state.pay_currency != inv.pay_currency:
            mismatch = "pay_currency"

        if mismatch:
            # Ничего не начисляем и ничего не переписываем: расхождение здесь
            # означает либо подмену, либо сломанный маппинг полей — и то и
            # другое чинится руками, а не автоматом.
            inv.flags = {**(inv.flags or {}), "needs_review": f"amount_mismatch:{mismatch}"}
            inv.last_checked_at = timezone.now()
            inv.save(update_fields=["flags", "last_checked_at", "updated_at"])
            pay.error = f"crypto_amount_mismatch:{mismatch}"
            pay.save(update_fields=["error"])
            logger.warning("crypto mismatch %s order=%s invoice=%s", mismatch,
                           pay.order_id, inv.provider_invoice_id)
            result, log_kind = "amount_mismatch", "crypto_amount_mismatch"
            payment_for_log = pay
        else:
            changed = (
                (state.status != base.UNKNOWN and state.status != inv.status)
                or state.actually_paid != inv.actually_paid
                or (state.tx_hash and state.tx_hash != inv.tx_hash)
            )

            if state.status == base.UNKNOWN:
                # Неизвестный статус не двигает счёт, но должен быть замечен.
                inv.flags = {**(inv.flags or {}),
                             "unknown_status": state.provider_status[:40]}
            else:
                inv.status = state.status
            # Оплаченное только растёт: «стало меньше» означало бы, что часть
            # денег исчезла из сети, — так не бывает, это старый ответ.
            inv.actually_paid = max(inv.actually_paid or Decimal(0), state.actually_paid)
            if state.actually_paid_fiat is not None:
                inv.actually_paid_fiat = state.actually_paid_fiat
            if state.tx_hash:
                inv.tx_hash = state.tx_hash
            if state.confirmations is not None:
                inv.confirmations = state.confirmations
            if state.provider_updated_at:
                inv.provider_updated_at = state.provider_updated_at
            if state.pay_amount > 0 and abs(state.pay_amount - inv.pay_amount) > (
                    inv.pay_amount * Decimal("0.01")):
                # Сумма к переводу зафиксирована при создании счёта; расхождение
                # только записываем — пересчитывать её задним числом нельзя.
                inv.flags = {**(inv.flags or {}), "pay_amount_drift": str(state.pay_amount)}
            inv.last_checked_at = timezone.now()
            if source == "ipn":
                inv.last_webhook_at = timezone.now()
            if changed:
                _append_callback(pay, source, state)

            # --- начисление -------------------------------------------------
            total = _package_total(pay)
            creditable = (
                inv.status in CryptoInvoice.CREDIT_STATES
                # Оплата после таймера: процессор оставит статус expired, но
                # деньги-то пришли, и человек должен получить своё.
                or (inv.status == CryptoInvoice.STATUS_EXPIRED and inv.actually_paid > 0)
            )
            if not pay.user_id:
                result = "no_user"
            elif creditable and inv.actually_paid > 0:
                entitled, kind = entitled_credits(total, inv.pay_amount, inv.actually_paid)
                if kind == "anomaly_ratio":
                    inv.flags = {**(inv.flags or {}), "needs_review": "anomaly_ratio"}
                    result = "flagged"
                elif kind == "over_capped":
                    inv.flags = {**(inv.flags or {}), "needs_review": "overpaid_beyond_cap"}

                delta = entitled - int(inv.credited_tokens or 0)
                if delta > 0:
                    cumulative = int(inv.credited_tokens or 0) + delta
                    if not _already_credited(pay, cumulative):
                        _apply_purchase_credit(pay, pay.order_id, delta, meta_extra={
                            "source": f"crypto_{source}",
                            "idem": str(cumulative),
                            "crypto": {
                                "paid": str(inv.actually_paid),
                                "expected": str(inv.pay_amount),
                                "delta": delta,
                                "cumulative": cumulative,
                                "kind": kind,
                                "coin": inv.pay_coin,
                                "network": inv.pay_network,
                            },
                        })
                    inv.credited_tokens = cumulative
                    inv.credited_paid_amount = inv.actually_paid
                    inv.credit_events = list(inv.credit_events or [])[-40:] + [{
                        "at": timezone.now().isoformat(),
                        "paid": str(inv.actually_paid),
                        "delta": delta,
                        "cumulative": cumulative,
                        "kind": kind,
                        "source": source,
                    }]
                    result = "credited"
                    logger.info("crypto credited order=%s +%s (всего %s из %s) %s",
                                pay.order_id, delta, cumulative, total, kind)

                if int(inv.credited_tokens or 0) >= total > 0:
                    pay.success = True
                    pay.error = ""
                    response = pay.response or {}
                    response["token_purchase_applied"] = True
                    pay.response = response
                    inv.finalized_at = inv.finalized_at or timezone.now()

            # --- закрытые без денег -----------------------------------------
            if inv.status in (CryptoInvoice.STATUS_FAILED, CryptoInvoice.STATUS_EXPIRED) \
                    and int(inv.credited_tokens or 0) == 0:
                pay.success = False
                pay.error = f"crypto_status:{inv.status}"
                inv.finalized_at = inv.finalized_at or timezone.now()
            if inv.status == CryptoInvoice.STATUS_REFUNDED:
                # Возврат делает магазин руками; кредиты автоматом не изымаем —
                # решение об этом принимает человек, глядя на конкретный случай.
                inv.flags = {**(inv.flags or {}), "refund_seen": True,
                             "needs_review": "refunded"}
                # Комиссия креатора с возвращённой оплаты отменяется сразу и целиком.
                from ..referral import reverse_creator_commission

                reverse_creator_commission(pay, "refund:crypto")

            inv.save()
            pay.save(update_fields=["response", "success", "error"])
            log_kind = f"crypto_{source}_{result}"
            payment_for_log = pay

    try:
        _log_payment_event(payment_for_log, log_kind)
    except Exception:  # noqa: BLE001 — журнал не важнее денег
        logger.exception("crypto: не удалось записать событие оплаты")
    return result


def _already_credited(payment, cumulative: int) -> bool:
    """Подстраховка поверх блокировки строки: вдруг такая дельта уже в леджере."""
    from plans.models import TokenTransaction

    return TokenTransaction.objects.filter(
        user=payment.user, reason="purchase", meta__order_id=payment.order_id,
        meta__crypto__cumulative=cumulative,
    ).exists()


# Сколько ждём после истечения счёта, прежде чем закрыть его самим: перевод
# мог уйти в последнюю секунду и ещё не показаться процессору.
LOCAL_EXPIRY_GRACE = timedelta(minutes=30)


def mark_expired_locally(invoice) -> None:
    """Счёт, по которому никто не заплатил и время вышло.

    Процессор тоже пометит его просроченным, но иногда с задержкой, а человек
    не должен смотреть на живой таймер, которого уже нет.

    Срок проверяется здесь же, а не только у вызывающего: закрыть действующий
    счёт по ошибке — значит сказать человеку «не успели», когда он ещё успевал.
    """
    from ..models import CryptoInvoice

    with transaction.atomic():
        inv = CryptoInvoice.objects.select_for_update().get(pk=invoice.pk)
        if inv.status != CryptoInvoice.STATUS_WAITING or inv.actually_paid > 0:
            return
        if not inv.expires_at or timezone.now() < inv.expires_at + LOCAL_EXPIRY_GRACE:
            return
        inv.status = CryptoInvoice.STATUS_EXPIRED
        inv.finalized_at = inv.finalized_at or timezone.now()
        inv.save(update_fields=["status", "finalized_at", "updated_at"])


def adopt_orphan_invoice(provider_name: str, state):
    """Принять счёт, который завёлся у процессора, но не сохранился у нас.

    Так бывает, когда наш запрос на создание счёта оборвался по таймауту уже
    после того, как процессор его создал: у него счёт есть, у нас — только
    платёж без счёта. Человек в это время уже мог отправить деньги, поэтому
    молча выбрасывать такой вебхук нельзя.
    """
    from ..models import CryptoInvoice, Payment

    if not state.order_id or not state.provider_id:
        return None
    payment = (Payment.objects
               .filter(order_id=state.order_id, provider=f"crypto_{provider_name}",
                       crypto_invoice__isnull=True)
               .first())
    if payment is None:
        return None
    if state.price_amount > 0 and abs(state.price_amount - payment.amount) > PRICE_EPS:
        logger.warning("crypto: осиротевший счёт с чужой суммой order=%s", state.order_id)
        return None

    from . import currencies

    info = currencies.describe(state.pay_currency)
    # Точка сохранения: одновременно пришедшие вебхуки по одному счёту не
    # должны ронять транзакцию запроса нарушением уникальности.
    with transaction.atomic():
        invoice = CryptoInvoice.objects.create(
            payment=payment,
            provider=provider_name,
            provider_invoice_id=state.provider_id,
            status=state.status if state.status != base.UNKNOWN else CryptoInvoice.STATUS_WAITING,
            price_amount=payment.amount,
            price_currency=(state.price_currency or "USD").upper(),
            pay_currency=state.pay_currency,
            pay_coin=info.coin,
            pay_network=info.network,
            pay_address=state.pay_address,
            pay_extra_id=state.pay_extra_id,
            pay_amount=state.pay_amount,
            flags={"adopted": True},
        )
    logger.info("crypto: принят осиротевший счёт order=%s invoice=%s",
                state.order_id, state.provider_id)
    return invoice
