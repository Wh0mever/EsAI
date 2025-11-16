from __future__ import annotations

import logging
from decimal import Decimal
import os
from django.utils import timezone
from django.contrib import messages
from django.db import DatabaseError, connection, transaction

from plans.models import UserSubscription, SubscriptionStatus
from payments.freedompay import FreedomPay


logger = logging.getLogger("payments")


def _price_to_int(amount) -> int:
    try:
        return int(Decimal(str(amount)).quantize(Decimal("1")))
    except Exception:
        try:
            return int(amount)
        except Exception:
            return 0


def _charge_one_user(user) -> tuple[bool, str]:
    sub: UserSubscription | None = (
        UserSubscription.objects
        .select_related("plan")
        .filter(user=user, status=SubscriptionStatus.ACTIVE)
        .order_by("-start_date")
        .first()
    )
    if not sub:
        return False, "no_active_subscription"
    plan = sub.plan
    amount = _price_to_int(plan.price_amount)
    if plan.is_free or amount <= 0:
        return False, "free_plan"
    if not (user.pay_token or "").strip():
        return False, "no_pay_token"

    order_id = f"admin-charge-{user.id}-{int(timezone.now().timestamp())}"
    svc = FreedomPay(user)
    try:
        resp = svc.charge(
            amount=amount,
            currency=os.environ.get("FREEDOM_PAY_DEFAULT_CURRENCY", "KGS").upper(),
            order_id=order_id,
            description=f"Admin action charge for plan #{plan.id}",
            auto_clearing=0,
            test=0,
        )
        # Treat non-success provider response as a failed charge.
        if not isinstance(resp, dict) or resp.get("pg_status") != "success":
            logger.error(
                "charge_failed user=%s amount=%s %s data=%s",
                user.id,
                amount,
                os.environ.get("FREEDOM_PAY_DEFAULT_CURRENCY", "KGS").upper(),
                resp,
            )
            return False, "provider_declined"
    except DatabaseError as e:
        logger.error(
            "charge_db_error user=%s amount=%s %s error=%s",
            user.id,
            amount,
            os.environ.get("FREEDOM_PAY_DEFAULT_CURRENCY", "KGS").upper(),
            str(e),
        )
        # Reset broken transaction so queryset iteration can continue under ATOMIC_REQUESTS.
        try:
            connection.rollback()
        except Exception:
            pass
        return False, "db_error"
    except Exception as e:
        logger.error(
            "charge_failed user=%s amount=%s %s error=%s",
            user.id,
            amount,
            os.environ.get("FREEDOM_PAY_DEFAULT_CURRENCY", "KGS").upper(),
            str(e),
        )
        return False, f"provider_error:{e}"

    # Mark paid for current cycle if applicable (does not shift dates)
    try:
        sub.payment_status = "paid"
        sub.payment_date = timezone.now()
        sub.save(update_fields=["payment_status", "payment_date"])
    except Exception:
        pass
    return True, "ok"


def charge_by_current_plan(modeladmin, request, queryset):
    """Admin action: charge selected users by their current active plan."""

    users = list(queryset)  # важный момент: дочитываем пользователей ДО начала биллинга

    total = len(users)
    ok = 0
    skipped = 0
    failed = 0
    details: dict[str, int] = {}

    for user in users:
        try:
            # изолируем каждого пользователя в отдельной транзакции
            with transaction.atomic():
                success, reason = _charge_one_user(user)
        except DatabaseError:
            logger.exception("DB error while charging user %s", user.pk)
            success = False
            reason = "db_error"
        except Exception:
            logger.exception("Unexpected error while charging user %s", user.pk)
            success = False
            reason = "unexpected_error"

        if success:
            ok += 1
        else:
            if reason in ("no_active_subscription", "free_plan", "no_pay_token"):
                skipped += 1
            else:
                failed += 1
            details[reason] = details.get(reason, 0) + 1

    msg = f"Processed: {total}. Success: {ok}, Skipped: {skipped}, Failed: {failed}."
    try:
        modeladmin.message_user(request, msg, level=messages.INFO)
    except Exception:
        pass

    logger.info(
        "admin_charge_summary total=%s ok=%s skipped=%s failed=%s details=%s",
        total,
        ok,
        skipped,
        failed,
        details,
    )
