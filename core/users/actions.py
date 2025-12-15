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
    
    card = UserCardBind.objects.filter(user=u).order_by("-created_at").first()
    if not (card.card_token or "").strip():
        return False, "no_pay_token"

    order_id = f"admin-charge-{user.id}-{int(timezone.now().timestamp())}"
    svc = FreedomPay(user)
    try:
        resp = svc.charge(
            amount=amount,
            currency=os.environ.get("FREEDOM_PAY_DEFAULT_CURRENCY", "USD").upper(),
            order_id=order_id,
            description=f"Admin action charge for plan #{plan.id}",
            test=0,
        )
        # Treat non-success provider response as a failed charge.
        if not isinstance(resp, dict) or resp.get("pg_status") != "success":
            logger.error(
                "charge_failed user=%s amount=%s %s data=%s",
                user.id,
                amount,
                os.environ.get("FREEDOM_PAY_DEFAULT_CURRENCY", "USD").upper(),
                resp,
            )
            return False, "provider_declined"
    except DatabaseError as e:
        logger.error(
            "charge_db_error user=%s amount=%s %s error=%s",
            user.id,
            amount,
            os.environ.get("FREEDOM_PAY_DEFAULT_CURRENCY", "USD").upper(),
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
            os.environ.get("FREEDOM_PAY_DEFAULT_CURRENCY", "USD").upper(),
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

    messages.info(request, "Starting to charge selected users...")