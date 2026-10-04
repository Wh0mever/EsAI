"""Фоновые задачи программы Creators: страховка возвратов, дозачисление, опрос провайдеров.

Хуки в оплате — основной путь. Задачи здесь нужны на случай, когда хук не
отработал: уведомление о возврате не дошло, начисление упало, возврат сделали
в кабинете провайдера. Каждая задача защищена замком в кэше, возвращает
словарь и никогда не бросает исключений.
"""
from __future__ import annotations

import logging
from datetime import timedelta

from celery import shared_task
from django.conf import settings
from django.core.cache import cache
from django.db.models import F, Q
from django.utils import timezone

from audit.services import log_event
from payments.models import Payment

from . import commission, flags
from .models import CreatorCommission, CreatorReferral, CreatorWithdrawal

logger = logging.getLogger(__name__)

_LOCK = "creators:{}:lock"

SAFETY_NET_BATCH = 500
BACKFILL_DAYS = 7
BACKFILL_DAYS_MAX = 90
POLL_PER_RUN = 200
POLL_URGENT_MAX = 300
POLL_WINDOW = timedelta(days=180)
POLL_RECHECK = timedelta(hours=6)
POLL_MATURING = timedelta(hours=24)


def _safety_reason(marker: str) -> str:
    return "fraud" if marker == "admin_fraud" else f"refund:{marker}"


@shared_task(name="creators.tasks.commission_safety_net")
def commission_safety_net() -> dict:
    """Отменить комиссии по платежам, которые уже помечены возвращёнными любым путём.

    Работает в любом режиме программы. Нужна там, где хук не достаёт: возврат
    Stars у платежа без пользователя, упавшее изъятие кредитов, чужой код,
    который пометил платёж и не позвал отмену.
    """
    key = _LOCK.format("commission_safety_net")
    if not cache.add(key, "1", timeout=840):
        return {"status": "busy"}
    try:
        # Набор сам сжимается: отменённые комиссии из него выпадают, поэтому
        # ограничение выборки никого не оставляет без проверки.
        payments = (
            Payment.objects
            .filter(creator_commissions__status__in=commission.OPEN)
            .filter(Q(error__in=["refunded", "stars_refunded"])
                    | Q(error__startswith="token_clawback_failed")
                    | Q(star_invoice__status="refunded")
                    | Q(crypto_invoice__status="refunded")
                    | Q(crypto_invoice__flags__refund_seen=True)
                    | Q(response__token_purchase_clawed_back=True)
                    | Q(response__has_key="yookassa_refunded")
                    | Q(response__has_key="freedompay_refunded")
                    | Q(response__has_key="admin_refund"))
            .distinct().order_by("id")[:SAFETY_NET_BATCH]
        )
        checked = reversed_rows = 0
        for payment in payments:
            checked += 1
            try:
                marker = commission.refund_marker(payment)
                if marker:
                    reversed_rows += commission.reverse_for_payment(payment, _safety_reason(marker))
            except Exception:  # noqa: BLE001 — один платёж не останавливает страховку
                logger.exception("creators safety net: платёж %s не обработан", payment.pk)
        if reversed_rows:
            logger.warning("creators safety net: отменено комиссий %s (платежей %s)",
                           reversed_rows, checked)
        return {"status": "ok", "checked": checked, "reversed": reversed_rows}
    except Exception:  # noqa: BLE001
        logger.exception("creators safety net failed")
        return {"status": "error"}
    finally:
        cache.delete(key)


@shared_task(name="creators.tasks.backfill_commissions")
def backfill_commissions(days: int = BACKFILL_DAYS) -> dict:
    """Доначислить комиссии по покупкам, у которых начисление не состоялось.

    days — глубина окна (1..90): после сбоя оператор может один раз пройти
    окно шире обычного. Привязка берётся на момент зачисления кредитов.
    """
    key = _LOCK.format("backfill_commissions")
    if not cache.add(key, "1", timeout=840):
        return {"status": "busy"}
    try:
        if not flags.accrual_enabled():
            return {"status": "disabled"}
        from plans.models import TokenTransaction

        try:
            days = int(days)
        except (TypeError, ValueError):
            days = BACKFILL_DAYS
        days = max(1, min(BACKFILL_DAYS_MAX, days))
        since = timezone.now() - timedelta(days=days)

        # Всё окно целиком, без среза «последние N»: такой срез почти весь
        # состоял бы из покупок, у которых комиссия уже есть, и до старого
        # пропуска очередь не дошла бы никогда.
        purchases = (TokenTransaction.objects
                     .filter(reason="purchase", delta__gt=0, created_at__gte=since,
                             user_id__in=CreatorReferral.objects.values("user_id"))
                     .order_by("id"))
        checked = accrued = 0
        for tx in purchases.iterator(chunk_size=500):
            checked += 1
            try:
                meta = tx.meta or {}
                order_id = meta.get("order_id")
                if not order_id:
                    continue
                payment = Payment.objects.filter(order_id=order_id).order_by("-id").first()
                # Платёж другого человека (след слияния аккаунтов) не трогаем.
                if payment is None or payment.user_id != tx.user_id:
                    continue
                part = str(meta.get("idem") or "")
                if CreatorCommission.objects.filter(payment=payment, part=part).exists():
                    continue
                if commission.refund_marker(payment):
                    continue
                referral = CreatorReferral.objects.covering(tx.user_id, tx.created_at)
                if referral is None:
                    continue
                if commission.accrue(payment, referral=referral, part=part,
                                     credited=int(tx.delta)) is not None:
                    accrued += 1
            except Exception:  # noqa: BLE001 — одна покупка не останавливает проход
                logger.exception("creators backfill: покупка %s не обработана", tx.pk)
        if accrued:
            logger.warning("creators backfill: доначислено комиссий %s из %s покупок",
                           accrued, checked)
        return {"status": "ok", "checked": checked, "accrued": accrued}
    except Exception:  # noqa: BLE001
        logger.exception("creators backfill failed")
        return {"status": "error"}
    finally:
        cache.delete(key)


# ---------------------------------------------------- опрос возвратов ---

def _poll_candidates(provider: str, per_run: int | None = None) -> "list[CreatorCommission]":
    """Какие комиссии провайдера спросить в этот проход (по умолчанию до POLL_PER_RUN).

    Сначала срочные: вот-вот выйдут из холда или креатор уже подал заявку на
    вывод. Потом остальные — давно не проверявшиеся первыми, чтобы очередь
    шла по кругу и ни одна строка не оставалась без проверки.
    """
    per_run = POLL_PER_RUN if per_run is None else per_run
    now = timezone.now()
    base = (CreatorCommission.objects
            .filter(provider=provider, status__in=commission.OPEN, created_at__gte=now - POLL_WINDOW)
            .select_related("payment"))
    oldest_first = (F("refund_checked_at").asc(nulls_first=True), "id")

    not_checked_lately = (Q(refund_checked_at__isnull=True)
                          | Q(refund_checked_at__lt=now - POLL_RECHECK))
    maturing = Q(available_at__gt=now, available_at__lte=now + POLL_MATURING)
    payout_requested = Q(creator_id__in=CreatorWithdrawal.objects
                         .filter(status__in=("review", "approved")).values("creator_id"))
    urgent = list(base.filter(not_checked_lately).filter(maturing | payout_requested)
                  .order_by(*oldest_first)[:POLL_URGENT_MAX])

    rest = max(0, int(per_run) - len(urgent))
    if not rest:
        return urgent
    return urgent + list(base.exclude(pk__in=[row.pk for row in urgent])
                         .order_by(*oldest_first)[:rest])


def _poll(provider: str, ask) -> dict:
    """Общий цикл опроса. ask(payment) -> "refunded" | что угодно другое."""
    checked = refunded = 0
    asked: dict[int, str] = {}
    for row in _poll_candidates(provider):
        try:
            # У одного платежа может быть несколько строк — провайдера спрашиваем один раз.
            if row.payment_id not in asked:
                asked[row.payment_id] = ""
                checked += 1
                asked[row.payment_id] = ask(row.payment) or ""
                if asked[row.payment_id] == "refunded":
                    refunded += 1
        except Exception:  # noqa: BLE001 — один сбой не останавливает очередь
            logger.warning("creators refund poll %s: платёж %s не проверен",
                           provider, row.payment_id, exc_info=True)
        finally:
            # Отметка ставится при любом исходе: сломанный платёж не должен
            # вечно стоять первым в очереди.
            CreatorCommission.objects.filter(pk=row.pk).update(refund_checked_at=timezone.now())
    if refunded:
        logger.warning("creators refund poll %s: найдено возвратов %s", provider, refunded)
    return {"status": "ok", "checked": checked, "refunded": refunded}


@shared_task(name="creators.tasks.poll_yookassa_refunds")
def poll_yookassa_refunds() -> dict:
    """Спросить ЮKassa о возвратах: вебхук refund.succeeded может быть не настроен."""
    key = _LOCK.format("poll_yookassa_refunds")
    if not cache.add(key, "1", timeout=3000):
        return {"status": "busy"}
    try:
        if not (getattr(settings, "YOOKASSA_SHOP_ID", "") and getattr(settings, "YOOKASSA_SECRET_KEY", "")):
            return {"status": "disabled"}
        from payments import views as payment_views
        from payments import yookassa as yk

        def ask(payment):
            if (payment.response or {}).get("yookassa_refunded"):
                return "already"
            yk_id = str((payment.request or {}).get("yookassa_payment_id") or "").strip()
            if not yk_id:
                return "skipped"
            return payment_views.apply_yookassa_refund(
                payment, yk.fetch_payment(yk_id), source="yookassa_refund_poll")

        return _poll("yookassa", ask)
    except Exception:  # noqa: BLE001
        logger.exception("creators yookassa refund poll failed")
        return {"status": "error"}
    finally:
        cache.delete(key)


@shared_task(name="creators.tasks.poll_freedompay_refunds")
def poll_freedompay_refunds() -> dict:
    """Спросить FreedomPay о возвратах, сделанных в кабинете (уведомления о них может не быть)."""
    key = _LOCK.format("poll_freedompay_refunds")
    if not cache.add(key, "1", timeout=3000):
        return {"status": "busy"}
    try:
        if not (getattr(settings, "FREEDOM_PAY_MERCHANT_ID", "") and getattr(settings, "FREEDOM_PAY_TOKEN", "")):
            return {"status": "disabled"}
        from payments import tasks as payment_tasks
        from payments import views as payment_views

        def ask(payment):
            if (payment.response or {}).get("freedompay_refunded"):
                return "already"
            # Через атрибут модуля: тесты и проверка цепочки подменяют запрос к FreedomPay.
            status = payment_tasks.fetch_payment_status(payment.order_id)
            return payment_views.apply_freedompay_refund(
                payment, status, source="freedompay_refund_poll")

        return _poll("freedompay", ask)
    except Exception:  # noqa: BLE001
        logger.exception("creators freedompay refund poll failed")
        return {"status": "error"}
    finally:
        cache.delete(key)


@shared_task(name="creators.tasks.nightly_check")
def nightly_check() -> dict:
    """Ночная сверка инвариантов программы (creators_check). Только читает."""
    key = _LOCK.format("nightly_check")
    if not cache.add(key, "1", timeout=3000):
        return {"status": "busy"}
    try:
        from . import checks

        violations = checks.run()
        failed = [v for v in violations if v.level == "fail"]
        if failed:
            log_event("other", level="error",
                      message=f"creators_check: {len(failed)} нарушений",
                      meta={"codes": sorted({v.code for v in failed})})
        return {"status": "ok", "fail": len(failed),
                "warn": len([v for v in violations if v.level == "warn"])}
    except Exception:  # noqa: BLE001
        logger.exception("creators nightly check failed")
        return {"status": "error"}
    finally:
        cache.delete(key)
