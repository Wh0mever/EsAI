from __future__ import annotations

import logging
from decimal import Decimal
import os
from django.utils import timezone
from django.contrib import messages

from plans.models import UserSubscription, SubscriptionStatus
from payments.freedompay import FreedomPay, FreedomPayError


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
        svc.charge(
            amount=amount,
            currency=os.environ.get("FREEDOM_PAY_DEFAULT_CURRENCY", "KGS").upper(),
            order_id=order_id,
            description=f"Admin action charge for plan #{plan.id}",
            auto_clearing=0,
            test=0,
        )
    except FreedomPayError as e:
        logger.error(
            "charge_failed user=%s amount=%s %s error=%s",
            user.id,
            amount,
            os.environ.get("FREEDOM_PAY_DEFAULT_CURRENCY", "KGS").upper(),
            str(e),
        )
        return False, f"provider_error:{e}"
    except Exception as e:
        logger.exception("charge_exception user=%s", user.id)
        return False, f"exception:{e}"

    # Mark paid for current cycle if applicable (does not shift dates)
    try:
        sub.payment_status = "paid"
        sub.payment_date = timezone.now()
        sub.save(update_fields=["payment_status", "payment_date"])
    except Exception:
        pass
    return True, "ok"


def charge_by_current_plan(modeladmin, request, queryset):
    """Admin action: charge selected users by their current active plan.

    - Skips users without active subscription, free plans, or missing pay_token.
    - Uses FreedomPay via env token + user's saved token.
    - Logs to payments logger and records PaymentLog automatically.
    """
    total = queryset.count()
    ok = 0
    skipped = 0
    failed = 0
    details: dict[str, int] = {}

    for user in queryset.iterator():
        success, reason = _charge_one_user(user)
        if success:
            ok += 1
        else:
            if reason in ("no_active_subscription", "free_plan", "no_pay_token"):
                skipped += 1
            else:
                failed += 1
        details[reason] = details.get(reason, 0) + (0 if success else 1)

    msg = f"Processed: {total}. Success: {ok}, Skipped: {skipped}, Failed: {failed}."
    try:
        modeladmin.message_user(request, msg, level=messages.INFO)
    except Exception:
        pass
    logger.info("admin_charge_summary total=%s ok=%s skipped=%s failed=%s details=%s", total, ok, skipped, failed, details)
