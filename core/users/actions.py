from __future__ import annotations

import logging
from decimal import Decimal
import os
from django.utils import timezone
from django.contrib import messages
from django.db import DatabaseError, connection, transaction

from plans.models import UserSubscription, SubscriptionStatus
from payments.freedompay import FreedomPay, FreedomPayError
from .models import UserCardBind


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
        # Fallback to the latest subscription if status is not ACTIVE after manual attachment.
        sub = (
            UserSubscription.objects
            .select_related("plan")
            .filter(user=user)
            .order_by("-start_date")
            .first()
        )
    if not sub:
        return False, "no_subscription"
    plan = sub.plan
    amount = _price_to_int(plan.price_amount)
    if plan.is_free or amount <= 0:
        return False, "free_plan"

    card = UserCardBind.objects.filter(user=user).order_by("-created_at").first()
    card_token = (card.card_token or "").strip() if card else ""
    if not card_token:
        logger.warning(
            "admin_charge_skip_no_token user=%s plan=%s sub=%s",
            user.id,
            plan.id,
            sub.id,
        )
        return False, "no_pay_token"

    currency = os.environ.get("FREEDOM_PAY_DEFAULT_CURRENCY", "USD").upper()
    order_id = f"admin-charge-{user.id}-{int(timezone.now().timestamp())}"
    logger.warning(
        "admin_charge_start user=%s plan=%s sub=%s amount=%s currency=%s order=%s",
        user.id,
        plan.id,
        sub.id,
        amount,
        currency,
        order_id,
    )
    svc = FreedomPay(user)
    try:
        resp = svc.charge(
            amount=amount,
            currency=currency,
            order_id=order_id,
            description=f"Admin action charge for plan #{plan.id}",
            card_token=card_token,
            test=False,
        )
        status = resp.get("pg_status") if isinstance(resp, dict) else None
        if not isinstance(resp, dict) or (status or "").lower() != "ok":
            logger.warning(
                "admin_charge_declined user=%s plan=%s order=%s response=%s",
                user.id,
                plan.id,
                order_id,
                resp,
            )
            return False, "provider_declined"
        logger.warning(
            "admin_charge_success user=%s plan=%s order=%s response=%s",
            user.id,
            plan.id,
            order_id,
            resp,
        )
    except DatabaseError as e:
        logger.warning(
            "admin_charge_db_error user=%s plan=%s order=%s error=%s",
            user.id,
            plan.id,
            order_id,
            str(e),
        )
        try:
            connection.rollback()
        except Exception:
            pass
        return False, "db_error"
    except FreedomPayError as e:
        logger.warning(
            "admin_charge_exception user=%s plan=%s order=%s kind=%s code=%s status=%s error=%s",
            user.id,
            plan.id,
            order_id,
            e.kind,
            e.code,
            e.status,
            str(e),
        )
        if e.is_provider_decline:
            return False, "provider_declined"
        return False, f"provider_error:{e}"
    except Exception as e:
        logger.warning(
            "admin_charge_exception user=%s plan=%s order=%s error=%s",
            user.id,
            plan.id,
            order_id,
            str(e),
        )
        return False, f"provider_error:{e}"

    # Mark paid for current cycle if applicable (does not shift dates)
    try:
        sub.payment_status = "paid"
        sub.payment_date = timezone.now()
        if sub.status != SubscriptionStatus.ACTIVE:
            sub.status = SubscriptionStatus.ACTIVE
            sub.save(update_fields=["payment_status", "payment_date", "status"])
        else:
            sub.save(update_fields=["payment_status", "payment_date"])
    except Exception:
        pass
    return True, "ok"


def charge_by_current_plan(modeladmin, request, queryset):
    """Admin action: charge selected users by their current active plan."""

    messages.warning(request, "Starting to charge selected users...")
    total = queryset.count()
    success = 0
    failures: list[tuple[int, str]] = []
    for user in queryset:
        ok, reason = _charge_one_user(user)
        if ok:
            success += 1
        else:
            failures.append((user.id, reason))
            logger.warning("admin_charge_failed user=%s reason=%s", user.id, reason)

    summary = f"Charges completed: {success}/{total} succeeded"
    if failures:
        summary += f"; failed users: {', '.join(f'{uid}:{reason}' for uid, reason in failures)}"
    messages.info(request, summary)
    logger.warning("admin_charge_summary total=%s success=%s failures=%s", total, success, len(failures))
