from __future__ import annotations
import logging
from datetime import timedelta
import os
from decimal import Decimal
from celery import shared_task
from django.core.cache import cache
from django.utils import timezone
from django.db import transaction

from plans.services import update_currency_rates, plan_cycle_days
from plans.services import BILLING_ISSUE_CARD_MISSING, BILLING_ISSUE_CHARGE_FAILED
from .models import UserSubscription, SubscriptionStatus, GenerationUsage, Plan
from users.models import User, UserCardBind
from payments.freedompay import FreedomPay, FreedomPayError


logger = logging.getLogger(__name__)
_LOCK_KEY = "plans:currency_update:lock"
_RENEW_GLOBAL_LOCK = "plans:renewal:lock"
_SUNDAY_BONUS_LOCK = "plans:sunday_bonus:lock"
_RENEW_GRACE_DAYS = 3

@shared_task(
    name="plans.tasks.refresh_currency_rates",
    bind=True,
    autoretry_for=(RuntimeError, Exception),
    retry_backoff=60,
    retry_jitter=True,
    retry_kwargs={"max_retries": 5},
)
def refresh_currency_rates(self, force: bool = False) -> dict[str, str]:
    # naive lock
    if not force and not cache.add(_LOCK_KEY, "1", timeout=5 * 60):
        logger.info("Currency update skipped due to lock")
        return {}
    try:
        rates = update_currency_rates()
        cache.delete("plans:currency_per_usd:all")
        logger.info("Currency rates updated: %s", {k: str(v) for k, v in rates.items()})
        return {k: str(v) for k, v in rates.items()}
    finally:
        cache.delete(_LOCK_KEY)


def _days(n: int | None, default: int = 30) -> timedelta:
    try:
        return timedelta(days=int(n or default))
    except Exception:
        return timedelta(days=default)


def _now():
    return timezone.now()


def _get_cycle_end(sub: UserSubscription) -> timezone.datetime:
    # Use existing end_date or compute from start_date
    if sub.end_date:
        return sub.end_date
    return sub.start_date + _days(plan_cycle_days(getattr(sub.plan, "period", None)))


def _price_to_int(amount: Decimal | int | float | None) -> int:
    if amount is None:
        return 0
    try:
        return int(Decimal(str(amount)).quantize(Decimal("1")))
    except Exception:
        try:
            return int(amount)  # best-effort
        except Exception:
            return 0


def _rollover_leftovers_to_bonus(sub: UserSubscription):
    plan: Plan = sub.plan
    usage: GenerationUsage
    user = sub.user
    with transaction.atomic():
        usage, _ = GenerationUsage.objects.select_for_update().get_or_create(subscription=sub)
        # Rollover only for limited caps (0 means no included generations).
        if plan.text_limit and usage.texts_left and usage.texts_left > 0:
            user.bonus_texts = (user.bonus_texts or 0) + int(usage.texts_left)
        if plan.image_limit and usage.images_left and usage.images_left > 0:
            user.bonus_images = (user.bonus_images or 0) + int(usage.images_left)
        if plan.song_limit and usage.songs_left and usage.songs_left > 0:
            user.bonus_songs = (user.bonus_songs or 0) + int(usage.songs_left)
        if plan.music_limit and usage.music_left and usage.music_left > 0:
            user.bonus_music = (user.bonus_music or 0) + int(usage.music_left)

        # Reset usage to new cycle amounts
        usage.songs_left = plan.song_limit or 0
        usage.music_left = plan.music_limit or 0
        usage.texts_left = plan.text_limit or 0
        usage.images_left = plan.image_limit or 0
        # Reset Sunday bonus flag; apply immediately if today is Sunday
        is_sunday = timezone.localdate().weekday() == 6
        if is_sunday:
            usage.songs_left += plan.sunday_bonus_songs
            usage.music_left += plan.sunday_bonus_music
            usage.texts_left += plan.sunday_bonus_texts
            usage.images_left += plan.sunday_bonus_images
            usage.sunday_bonus_used = True
        else:
            usage.sunday_bonus_used = False

        user.save(update_fields=["bonus_texts", "bonus_images", "bonus_songs", "bonus_music"])
        usage.save(update_fields=[
            "songs_left", "music_left", "texts_left", "images_left", "sunday_bonus_used"
        ])


def _advance_cycle_dates(sub: UserSubscription):
    end = _get_cycle_end(sub)
    dur = _days(plan_cycle_days(getattr(sub.plan, "period", None)))
    sub.start_date = end
    sub.end_date = end + dur
    sub.save(update_fields=["start_date", "end_date", "payment_status", "payment_date", "status", "grace_until", "billing_issue_code"])


def _renew_one_subscription(sub: UserSubscription) -> bool:
    """Renew one subscription if due; returns True if renewed (charged or free)."""
    plan: Plan = sub.plan
    user = sub.user

    # Prevent concurrent double-processing per sub for a short window
    lock_key = f"plans:renew:sub:{sub.id}"
    if not cache.add(lock_key, "1", timeout=60):
        return False
    try:
        now = _now()
        due_at = _get_cycle_end(sub)
        if now < due_at:
            return False

        # Grace period ended: disable chat access until user pays manually/reactivates.
        if (
            str(getattr(sub, "payment_status", "") or "").lower() == "unpaid"
            and (sub.billing_issue_code or "").strip().lower() in {BILLING_ISSUE_CARD_MISSING, BILLING_ISSUE_CHARGE_FAILED}
            and sub.grace_until
            and now >= sub.grace_until
        ):
            if sub.status != SubscriptionStatus.INACTIVE:
                sub.status = SubscriptionStatus.INACTIVE
                sub.save(update_fields=["status"])
                logger.warning("Grace period ended; set INACTIVE for sub=%s", sub.id)
            return False

        if not getattr(sub, "auto_renew", True) or not getattr(user, "auto_renew", True):
            sub.status = SubscriptionStatus.INACTIVE
            sub.save(update_fields=["status"])
            logger.info("Auto renew disabled; deactivated sub=%s", sub.id)
            return False

        # Free plan: no charge, just rollover and advance
        if plan.is_free or _price_to_int(plan.price_amount) <= 0:
            _rollover_leftovers_to_bonus(sub)
            sub.payment_status = "paid"
            sub.payment_date = now
            sub.grace_until = None
            sub.billing_issue_code = ""
            _advance_cycle_dates(sub)
            logger.info("Renewed free plan for sub=%s", sub.id)
            return True

        # Paid plan: require token
        card = UserCardBind.objects.filter(user=user).order_by("-created_at").first()
        if not (card.card_token or "").strip():
            # No token — start/keep grace window, then disable when grace expires.
            sub.payment_status = "unpaid"
            sub.status = SubscriptionStatus.ACTIVE
            if not sub.grace_until:
                sub.grace_until = due_at + timedelta(days=_RENEW_GRACE_DAYS)
            sub.billing_issue_code = BILLING_ISSUE_CARD_MISSING
            sub.save(update_fields=["status", "payment_status", "grace_until", "billing_issue_code"])
            logger.warning("No token for sub=%s, grace_until=%s", sub.id, sub.grace_until)
            return False

        # Charge via FreedomPay
        amount = _price_to_int(plan.price_amount)
        currency = os.environ.get("FREEDOM_PAY_DEFAULT_CURRENCY", "KGS").upper()
        description = f"Subscription plan #{plan.id} renewal"
        fp_client = FreedomPay(user=user)
        try:
            resp = fp_client.charge(
                amount=amount,
                currency=currency,
                order_id=f"sub-{sub.id}-{int(now.timestamp())}",
                description=description,
            )
        except FreedomPayError as exc:
            sub.payment_status = "unpaid"
            sub.status = SubscriptionStatus.ACTIVE
            if not sub.grace_until:
                sub.grace_until = due_at + timedelta(days=_RENEW_GRACE_DAYS)
            sub.billing_issue_code = BILLING_ISSUE_CHARGE_FAILED
            sub.save(update_fields=["payment_status", "status", "grace_until", "billing_issue_code"])
            logger.warning(
                "Charge declined for sub=%s user=%s amount=%s %s kind=%s code=%s status=%s desc=%s",
                sub.id,
                user.id,
                amount,
                currency,
                exc.kind,
                exc.code,
                exc.status,
                exc.description,
            )
            logging.getLogger("payments").warning(
                "charge_failed sub=%s user=%s amount=%s %s kind=%s code=%s status=%s desc=%s response=%s",
                sub.id,
                user.id,
                amount,
                currency,
                exc.kind,
                exc.code,
                exc.status,
                exc.description,
                exc.response,
            )
            return False

        # FreedomPay client returns JSON dict; check success flag
        status = resp.get("pg_status") if isinstance(resp, dict) else None
        if not isinstance(resp, dict) or (status or "").lower() != "ok":
            sub.payment_status = "unpaid"
            sub.status = SubscriptionStatus.ACTIVE
            if not sub.grace_until:
                sub.grace_until = due_at + timedelta(days=_RENEW_GRACE_DAYS)
            sub.billing_issue_code = BILLING_ISSUE_CHARGE_FAILED
            sub.save(update_fields=["payment_status", "status", "grace_until", "billing_issue_code"])
            logger.error("Charge failed for sub=%s: %s", sub.id, resp)
            logging.getLogger("payments").error(
                "charge_failed sub=%s user=%s amount=%s %s data=%s",
                sub.id,
                user.id,
                amount,
                currency,
                resp,
            )
            return False

        # On success, mark as paid
        sub.payment_status = "paid"
        sub.payment_date = now
        sub.status = SubscriptionStatus.ACTIVE
        sub.grace_until = None
        sub.billing_issue_code = ""

        # On success: rollover leftovers and advance cycle
        _rollover_leftovers_to_bonus(sub)
        _advance_cycle_dates(sub)
        logger.info("Renewed paid plan for sub=%s", sub.id)
        try:
            logging.getLogger("payments").info(
                "charge_success sub=%s user=%s amount=%s %s data=%s",
                sub.id,
                user.id,
                amount,
                currency,
                resp,
            )
        except Exception:
            pass
        return True
    finally:
        cache.delete(lock_key)


@shared_task(
    name="plans.tasks.process_due_subscriptions",
    bind=True,
    autoretry_for=(RuntimeError,),
    retry_backoff=30,
    retry_jitter=True,
    retry_kwargs={"max_retries": 3},
)
def process_due_subscriptions(self) -> dict:
    """Scan active subscriptions and renew those whose period ended.

    Runs frequently (e.g., every 10 minutes) and is idempotent per sub via cache locks.
    """
    if not cache.add(_RENEW_GLOBAL_LOCK, "1", timeout=60):
        return {"status": "busy"}
    try:
        now = _now()
        subs = (UserSubscription.objects
                .select_related("plan", "user")
                .filter(status=SubscriptionStatus.ACTIVE))

        processed = 0
        for sub in subs.iterator():
            try:
                if _renew_one_subscription(sub):
                    processed += 1
            except Exception as e:
                logger.exception("Subscription renewal error sub=%s: %s", sub.id, e)
                continue
        return {"processed": processed, "ts": int(now.timestamp())}
    finally:
        cache.delete(_RENEW_GLOBAL_LOCK)


@shared_task(
    name="plans.tasks.apply_sunday_bonuses",
    bind=True,
    autoretry_for=(RuntimeError,),
    retry_backoff=30,
    retry_jitter=True,
    retry_kwargs={"max_retries": 3},
)
def apply_sunday_bonuses(self) -> dict:
    """
    Apply Sunday bonuses to active subscriptions.

    - If today is Sunday, bonuses are added once per subscription.
    - On non-Sunday days, sunday_bonus_used is reset to allow next Sunday accrual.
    """
    if not cache.add(_SUNDAY_BONUS_LOCK, "1", timeout=60):
        return {"status": "busy"}
    try:
        today = timezone.localdate()
        is_sunday = today.weekday() == 6  # Monday=0 ... Sunday=6

        subs = (
            UserSubscription.objects
            .select_related("plan")
            .filter(status=SubscriptionStatus.ACTIVE)
        )

        applied = 0
        reset = 0
        skipped = 0

        for sub in subs.iterator():
            plan: Plan = sub.plan
            if not plan:
                skipped += 1
                continue

            with transaction.atomic():
                usage, _ = GenerationUsage.objects.select_for_update().get_or_create(subscription=sub)
                has_bonus = any([
                    int(plan.sunday_bonus_songs or 0) > 0,
                    int(plan.sunday_bonus_music or 0) > 0,
                    int(plan.sunday_bonus_texts or 0) > 0,
                    int(plan.sunday_bonus_images or 0) > 0,
                ])
                if not has_bonus:
                    skipped += 1
                    continue

                if is_sunday:
                    if usage.sunday_bonus_used:
                        skipped += 1
                        continue
                    usage.songs_left = int(usage.songs_left or 0) + int(plan.sunday_bonus_songs or 0)
                    usage.music_left = int(usage.music_left or 0) + int(plan.sunday_bonus_music or 0)
                    usage.texts_left = int(usage.texts_left or 0) + int(plan.sunday_bonus_texts or 0)
                    usage.images_left = int(usage.images_left or 0) + int(plan.sunday_bonus_images or 0)
                    usage.sunday_bonus_used = True
                    usage.save(update_fields=["songs_left", "music_left", "texts_left", "images_left", "sunday_bonus_used"])
                    applied += 1
                else:
                    if usage.sunday_bonus_used:
                        usage.sunday_bonus_used = False
                        usage.save(update_fields=["sunday_bonus_used"])
                        reset += 1
                    else:
                        skipped += 1

        return {
            "is_sunday": is_sunday,
            "applied": applied,
            "reset": reset,
            "skipped": skipped,
            "ts": int(timezone.now().timestamp()),
        }
    finally:
        cache.delete(_SUNDAY_BONUS_LOCK)
