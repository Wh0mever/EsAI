from __future__ import annotations

# Сверка «повисших» оплат FreedomPay.
#
# Проблема: кредиты начисляются ТОЛЬКО на подписанном server-to-server постбэке
# FreedomPay (POST /api/payments/tokens/postback/), а для нашего мерчанта этот
# постбэк по факту НЕ приходит (за всю историю — 0 постбэков). Браузерный
# success — презентационный (не начисляет). Итог: после реальной оплаты кредиты
# не поступают сами.
#
# Решение (не зависит от постбэка): сами спрашиваем статус у FreedomPay через их
# API get_status2 (исходящий запрос) и начисляем подтверждённые оплаты. Запускается
# по расписанию (beat, каждые ~2 мин) И мгновенно на возврате пользователя из
# оплаты (см. FreedomPayTokenPurchaseSuccessView). Полностью идемпотентно.

import logging
import xml.etree.ElementTree as ET
from datetime import timedelta
from decimal import Decimal

import requests
from celery import shared_task
from django.conf import settings
from django.core.cache import cache
from django.db import transaction
from django.utils import timezone

logger = logging.getLogger(__name__)

_RECON_LOCK = "payments:reconcile:lock"


def _status_url() -> str:
    """URL get_status2 в той же папке, что и init_payment (https://api.freedompay.kg/get_status2.php)."""
    init = (getattr(settings, "FREEDOM_PAY_INIT_PAYMENT_URL", "") or "").rstrip("/")
    base = init.rsplit("/", 1)[0] if "/" in init else init
    return f"{base}/get_status2.php"


def fetch_payment_status(order_id: str) -> dict:
    """Спросить у FreedomPay статус платежа по order_id. Возвращает распарсенный
    XML как dict или {} при любой ошибке (никогда не бросает)."""
    from .freedompay import make_api_signature

    merchant = str(getattr(settings, "FREEDOM_PAY_MERCHANT_ID", "") or "")
    secret = getattr(settings, "FREEDOM_PAY_TOKEN", "") or ""
    if not (merchant and secret and order_id):
        return {}
    params = {
        "pg_merchant_id": merchant,
        "pg_order_id": order_id,
        "pg_salt": "recon" + str(order_id)[-10:],
    }
    params["pg_sig"] = make_api_signature("get_status2.php", params, secret)
    try:
        r = requests.post(_status_url(), data=params, timeout=25)
        root = ET.fromstring(r.text)
        return {child.tag: (child.text or "").strip() for child in root}
    except Exception as exc:  # noqa: BLE001
        logger.warning("fetch_payment_status failed order=%s: %s", order_id, exc)
        return {}


def _package_id_from_order(order_id: str) -> int | None:
    # tokpkg-<user>-<pkg>-<rand>
    parts = (order_id or "").split("-")
    if len(parts) >= 3 and parts[0] == "tokpkg":
        try:
            return int(parts[2])
        except ValueError:
            return None
    return None


def _verify_and_credit(payment) -> str:
    """Проверить статус у FreedomPay и начислить пакет, если ОПЛАЧЕНО и подтверждено.

    Гейты: pg_status=ok, pg_transaction_status ∈ {ok,success,captured}, сумма и
    валюта совпадают с заказом. Начисление идемпотентно (по TokenTransaction
    reason='purchase' + meta.order_id и флагу token_purchase_applied). Уведомление
    отправляется ПОСЛЕ коммита (best-effort), чтобы сбой почты не откатил кредит.
    """
    from .models import Payment
    from plans.models import TokenPackage, TokenTransaction
    from plans.wallet import credit_tokens

    order_id = payment.order_id
    st = fetch_payment_status(order_id)
    if not st:
        return "no_status"
    ok = str(st.get("pg_status") or "").lower() == "ok"
    tx_ok = str(st.get("pg_transaction_status") or "").lower() in {"ok", "success", "captured"}
    if not (ok and tx_ok):
        return f"not_paid:{st.get('pg_status')}/{st.get('pg_transaction_status')}"

    # Сверка суммы и валюты с заказом (защита от подмены/бага провайдера).
    try:
        amt_ok = Decimal(str(st.get("pg_amount") or "0")) == (payment.amount or Decimal("0"))
    except Exception:
        amt_ok = False
    cur = str(st.get("pg_currency") or "").upper()
    cur_ok = (not cur) or (cur == (payment.currency or "").upper())
    if not (amt_ok and cur_ok):
        logger.warning(
            "reconcile amount/currency mismatch order=%s api_amt=%s api_cur=%s pay=%s %s",
            order_id, st.get("pg_amount"), cur, payment.amount, payment.currency,
        )
        return "amount_mismatch"

    pkg_id = _package_id_from_order(order_id)
    info = (payment.request or {}).get("token_purchase") or {}
    # Начисляем по снапшоту, зафиксированному в момент покупки (см. комментарий
    # в payments/views.py::_credit_token_package_for_payment) — а не по текущей
    # живой конфигурации TokenPackage, которая могла измениться за время между
    # инициацией оплаты и этим reconcile-проходом.
    total = int(info.get("tokens") or 0) + int(info.get("bonus_tokens") or 0)
    if total <= 0:
        try:
            pkg = TokenPackage.objects.get(pk=int(pkg_id))
            total = int(pkg.tokens or 0) + int(pkg.bonus_tokens or 0)
        except Exception:
            total = 0
    if total <= 0:
        return "zero_amount"

    credited_now = False
    with transaction.atomic():
        pp = Payment.objects.select_for_update().get(pk=payment.pk)
        already = TokenTransaction.objects.filter(
            user=pp.user, reason="purchase", meta__order_id=order_id
        ).exists()
        if not already:
            credit_tokens(pp.user, total, "purchase", meta={
                "order_id": order_id, "package_id": pkg_id, "tokens": total,
                "bonus_tokens": 0, "source": "status_reconcile",
            })
            credited_now = True
        resp = pp.response or {}
        cbs = list(resp.get("callbacks") or [])
        cbs.append({"type": "status_reconcile", "payload": st})
        resp["callbacks"] = cbs
        resp["token_purchase_applied"] = True
        pp.response = resp
        pp.success = True
        pp.save(update_fields=["response", "success"])

    # Exit-discount: пометить redeemed_at, если скидка была применена к этому
    # платежу (best-effort, отдельной транзакцией — сбой НЕ должен откатывать
    # или ронять уже совершённое начисление токенов покупателю).
    if credited_now:
        try:
            from .views import _mark_exit_discount_redeemed
            _mark_exit_discount_redeemed(payment)
        except Exception:  # noqa: BLE001
            logger.exception("exit_discount_redeem_mark_failed order=%s", order_id)

    # Реферальная revenue-share выплата пригласившему (ПОСЛЕ коммита покупки,
    # отдельной транзакцией). Пригласивший получает % от КУПЛЕННЫХ кредитов —
    # пожизненно, при каждом пополнении. Сама выплата живёт в payments/referral.py
    # (общая для всех провайдеров), идемпотентна по order_id и не роняет покупку.
    if credited_now:
        from .referral import pay_referral_share

        pay_referral_share(payment.user, order_id, total)

    # После коммита — пометить платным + уведомить (не критично, не роняем кредит).
    if credited_now:
        try:
            from .views import _mark_user_paid, _notify_balance_topup
            _mark_user_paid(payment.user)
            _notify_balance_topup(payment.user, total)
        except Exception as exc:  # noqa: BLE001
            logger.warning("post-credit notify failed order=%s: %s", order_id, exc)
    return "credited" if credited_now else "already"


def _has_payment_marker(p) -> bool:
    for cb in (p.response or {}).get("callbacks") or []:
        if ((cb or {}).get("payload") or {}).get("pg_payment_id"):
            return True
    return False


@shared_task(name="payments.tasks.reconcile_pending_token_payments")
def reconcile_pending_token_payments() -> dict:
    """Сверить оплаченные, но не начисленные token-заказы и начислить подтверждённые.

    Идемпотентно и защищено локом. Дёргаем FreedomPay-статус только для заказов,
    где есть признак оплаты (pg_payment_id) ИЛИ совсем свежих (<2ч) — чтобы не
    молотить API по заброшенным init'ам.
    """
    if not cache.add(_RECON_LOCK, "1", timeout=110):
        return {"status": "busy"}
    try:
        from .models import Payment
        from plans.models import TokenTransaction

        now = timezone.now()
        window = now - timedelta(days=7)
        recent = now - timedelta(hours=2)
        pays = (
            Payment.objects
            .filter(order_id__startswith="tokpkg-", created_at__gte=window)
            .exclude(user=None)
            # Крипту сверяет своя задача: у неё другой процессор, другой смысл
            # статусов и начисление по частям. Спрашивать про неё FreedomPay
            # бессмысленно, а «нет такого заказа» ещё и засоряет журнал.
            .exclude(provider__startswith="crypto_")
            # Рублёвые заказы идут через ЮKassa — у них своя сверка ниже.
            .exclude(provider="yookassa")
            # Уже зачисленные отсекаем в запросе, а не после среза: иначе
            # шестьдесят свежих брошенных заказов выталкивали из окна старый
            # оплаченный, и его больше никто не проверял.
            .exclude(success=True)
            .order_by("-id")[:200]
        )
        checked = credited = 0
        for p in pays:
            if TokenTransaction.objects.filter(
                user=p.user, reason="purchase", meta__order_id=p.order_id
            ).exists():
                continue
            if not (_has_payment_marker(p) or p.created_at >= recent):
                continue
            checked += 1
            try:
                if _verify_and_credit(p) == "credited":
                    credited += 1
            except Exception as exc:  # noqa: BLE001
                logger.warning("reconcile order=%s failed: %s", p.order_id, exc)
        if credited:
            logger.info("reconcile_pending_token_payments checked=%s credited=%s", checked, credited)
        return {"status": "ok", "checked": checked, "credited": credited}
    finally:
        cache.delete(_RECON_LOCK)


# --------------------------------------------------------------- ЮKassa ---

_YK_RECON_LOCK = "payments:yookassa_reconcile:lock"


@shared_task(name="payments.tasks.reconcile_yookassa_payments")
def reconcile_yookassa_payments() -> dict:
    """Досверка рублёвых оплат: спросить ЮKassa про незакрытые заказы.

    Вебхук — основной путь, но он приходит один раз на событие. Если наш сервер
    был недоступен или ответил ошибкой, оплаченный заказ без этой задачи так и
    остался бы без кредитов. Смотрим заказы за последние сутки, которые ещё не
    зачислены и не отменены, и применяем ответ API тем же кодом, что и вебхук.
    """
    if not cache.add(_YK_RECON_LOCK, "1", timeout=240):
        return {"status": "busy"}
    try:
        from . import yookassa as yk
        from .models import Payment
        from .views import apply_yookassa_state

        if not (getattr(settings, "YOOKASSA_SHOP_ID", "") and getattr(settings, "YOOKASSA_SECRET_KEY", "")):
            return {"status": "disabled"}
        since = timezone.now() - timedelta(hours=24)
        pays = (Payment.objects
                .filter(provider="yookassa", success=False, created_at__gte=since)
                .exclude(user=None)
                .order_by("-id")[:100])
        checked = credited = 0
        for p in pays:
            if str(p.error or "").startswith(("yookassa_status:", "amount_mismatch")):
                continue  # отменён или сумма не сошлась — решено окончательно
            yk_id = str((p.request or {}).get("yookassa_payment_id") or "").strip()
            if not yk_id:
                continue
            checked += 1
            try:
                if apply_yookassa_state(p, yk.fetch_payment(yk_id), source="yookassa_reconcile") == "credited":
                    credited += 1
            except Exception as exc:  # noqa: BLE001
                logger.warning("yookassa reconcile order=%s failed: %s", p.order_id, exc)
        if credited:
            logger.info("reconcile_yookassa_payments checked=%s credited=%s", checked, credited)
        return {"status": "ok", "checked": checked, "credited": credited}
    finally:
        cache.delete(_YK_RECON_LOCK)


# --------------------------------------------------------------- крипта ---

_CRYPTO_LOCK = "payments:crypto_reconcile:lock"


@shared_task(name="payments.tasks.check_crypto_invoice", bind=True,
             max_retries=3, default_retry_delay=30)
def check_crypto_invoice(self, invoice_id: int) -> str:
    """Спросить процессор про один счёт и применить ответ.

    Ставится из открытой вкладки (человек смотрит на таймер) и из сверки.
    Недоступность процессора — повод повторить, а не потерять оплату.
    """
    from .crypto import credit as crypto_credit
    from .crypto import registry as crypto_registry
    from .crypto.base import ProviderError, ProviderUnavailable
    from .models import CryptoInvoice

    invoice = CryptoInvoice.objects.select_related("payment").filter(pk=invoice_id).first()
    if invoice is None:
        return "missing"
    try:
        state = crypto_registry.get_adapter(invoice.provider).fetch_invoice(
            invoice.provider_invoice_id)
    except ProviderUnavailable as exc:
        raise self.retry(exc=exc)
    except ProviderError as exc:
        logger.warning("crypto: счёт %s не проверить: %s", invoice.provider_invoice_id, exc)
        return "provider_error"
    return crypto_credit.apply_provider_status(invoice, state, source="reconcile")


@shared_task(name="payments.tasks.reconcile_crypto_invoices")
def reconcile_crypto_invoices() -> dict:
    """Сверка криптосчетов: деньги в блокчейне есть, а вебхук мог не дойти.

    Смотрим живые счета и — редко, раз в несколько часов — те, что закрылись
    без оплаты: перевод, отправленный после таймера, всё равно наш и должен
    быть зачислен.
    """
    from django.db.models import Q

    from .crypto import credit as crypto_credit
    from .models import CryptoInvoice

    if not cache.add(_CRYPTO_LOCK, "1", timeout=110):
        return {"status": "busy"}
    try:
        now = timezone.now()
        window = now - timedelta(days=7)
        slow_sweep = now - timedelta(hours=6)
        invoices = (
            CryptoInvoice.objects
            .select_related("payment")
            .filter(
                Q(status__in=list(CryptoInvoice.OPEN_STATES), created_at__gte=window)
                | Q(status__in=[CryptoInvoice.STATUS_EXPIRED, CryptoInvoice.STATUS_FAILED],
                    credited_tokens=0, created_at__gte=window)
                & (Q(last_checked_at__isnull=True) | Q(last_checked_at__lt=slow_sweep))
            )
            .exclude(payment__user=None)
            .order_by("last_checked_at")[:60]
        )
        checked = credited = 0
        for invoice in invoices:
            # Просроченный и неоплаченный счёт помечаем сами: процессор иногда
            # тянет со статусом, а человек не должен смотреть на таймер,
            # которого уже нет. Перепроверять его это не мешает.
            if (invoice.status == CryptoInvoice.STATUS_WAITING
                    and invoice.actually_paid == 0):
                try:
                    crypto_credit.mark_expired_locally(invoice)
                except Exception as exc:  # noqa: BLE001
                    logger.warning("crypto: не пометить просроченным %s: %s",
                                   invoice.provider_invoice_id, exc)
            try:
                result = check_crypto_invoice(invoice.id)
                checked += 1
                credited += 1 if result == "credited" else 0
            except Exception as exc:  # noqa: BLE001 — один счёт не роняет сверку
                logger.warning("crypto: сверка счёта %s не удалась: %s",
                               invoice.provider_invoice_id, exc)
        if credited:
            logger.info("reconcile_crypto_invoices checked=%s credited=%s", checked, credited)
        return {"status": "ok", "checked": checked, "credited": credited}
    finally:
        cache.delete(_CRYPTO_LOCK)


@shared_task(name="payments.tasks.reconcile_star_transactions")
def reconcile_star_transactions() -> dict:
    """Сверка Telegram Stars: пропущенные апдейты и возвраты. См. botapi/stars.py."""
    from botapi.stars import reconcile

    try:
        result = reconcile()
    except Exception:  # noqa: BLE001
        logger.exception("stars reconcile failed")
        return {"status": "error"}
    if result.get("credited") or result.get("refunded"):
        logger.info("stars reconcile: %s", result)
    return result
