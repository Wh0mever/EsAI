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
    # отдельной транзакцией). Пригласивший получает % (REFERRAL_PERCENT,
    # runtime-оверрайд в админке) от КУПЛЕННЫХ кредитов — пожизненно, при каждом
    # пополнении. Всё завёрнуто в try/except: сбой реф-выплаты НЕ должен ронять
    # и НЕ должен откатывать зачисление покупателю. Идемпотентно по order_id.
    if credited_now:
        try:
            ref = getattr(payment.user, "referred_by", None)
            if ref and total > 0:
                # Процент: лениво из рантайм-настроек админки, иначе из settings.
                try:
                    from adminapi.runtime import get_runtime
                    percent = int(get_runtime("REFERRAL_PERCENT", getattr(settings, "REFERRAL_PERCENT", 10)))
                except Exception:  # noqa: BLE001
                    percent = int(getattr(settings, "REFERRAL_PERCENT", 10))
                share = (total * percent) // 100
                if share > 0:
                    with transaction.atomic():
                        # Идемпотентность: не платить дважды за один и тот же order_id.
                        paid_already = TokenTransaction.objects.filter(
                            user=ref, reason="referral", meta__order_id=order_id
                        ).exists()
                        if not paid_already:
                            credit_tokens(ref, share, "referral", meta={
                                "order_id": order_id,
                                "from_user_id": payment.user.id,
                                "percent": percent,
                                "base_credits": total,
                            })
        except Exception as exc:  # noqa: BLE001
            logger.exception("referral payout failed order=%s: %s", order_id, exc)

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
            .order_by("-id")[:60]
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
