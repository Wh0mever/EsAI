from __future__ import annotations

import logging
from datetime import timedelta
from typing import Tuple

from django.db import transaction
from django.utils import timezone

from plans.models import (
    Plan,
    UserSubscription,
    SubscriptionStatus,
    PaymentStatus,
    GenerationUsage,
)
from plans.services import plan_cycle_days
from .models import User, UserCardBind, Notification, NotificationDelivery


logger = logging.getLogger("plans")

FREE_TRIGGER_FIRST_GEN = "Хочешь ещё? В платных тарифах больше лимитов"
FREE_TRIGGER_LOW_LIMIT = "Лимиты почти закончились"
FREE_TRIGGER_LAST_DAY = "Сегодня последний день бесплатного доступа"


def activate_free_plan_for_user(user: User) -> Tuple[bool, str]:
    """
    Attempt to auto-activate a free plan for the given user if:
    - user has at least one saved card
    - user has no active subscription yet
    - free plan exists and user has not activated it previously
    """
    if user is None:
        return False, "no_user"

    user_pk = getattr(user, "pk", None)
    if not user_pk:
        return False, "no_user"

    if getattr(user, "free_plan_activated", False):
        return False, "flag_set"

    if not UserCardBind.objects.filter(user_id=user_pk).exists():
        return False, "no_card"

    plan = (
        Plan.objects.filter(is_active=True, is_free=True)
        .order_by("sort_order", "id")
        .first()
    )
    if not plan:
        return False, "no_free_plan"

    activated_sub_id = None
    with transaction.atomic():
        locked_user = User.objects.select_for_update().get(pk=user_pk)
        if locked_user.free_plan_activated:
            return False, "flag_set"

        existing = (
            UserSubscription.objects.select_for_update()
            .filter(user=locked_user, status=SubscriptionStatus.ACTIVE)
            .order_by("-start_date")
            .first()
        )
        if existing:
            return False, "has_active_subscription"

        now = timezone.now()
        sub = UserSubscription.objects.create(
            user=locked_user,
            plan=plan,
            start_date=now,
            end_date=now + timedelta(days=plan_cycle_days(plan.period)),
            status=SubscriptionStatus.ACTIVE,
            payment_status=PaymentStatus.UNPAID,
            payment_date=None,
        )
        GenerationUsage.objects.get_or_create(
            subscription=sub,
            defaults={
                "songs_left": int(plan.song_limit or 0),
                "music_left": int(plan.music_limit or 0),
                "texts_left": int(plan.text_limit or 0),
                "images_left": int(plan.image_limit or 0),
            },
        )
        locked_user.free_plan_activated = True
        locked_user.save(update_fields=["free_plan_activated"])
        activated_sub_id = sub.id

    logger.info(
        "free_plan_auto_activated user=%s plan=%s subscription=%s",
        user_pk,
        plan.id if plan else None,
        activated_sub_id,
    )
    return True, "activated"


def _notify_user_once(user: User, title: str) -> bool:
    if not user or not title:
        return False
    exists = NotificationDelivery.objects.filter(
        recipient=user,
        notification__title=title,
    ).exists()
    if exists:
        return False
    n = Notification.objects.create(title=title, body="")
    NotificationDelivery.objects.get_or_create(notification=n, recipient=user)
    return True


def _calc_plan_initial_and_left(sub: UserSubscription, usage: GenerationUsage) -> tuple[int, int, int]:
    plan = sub.plan
    resources = (
        ("text_limit", "texts_left"),
        ("image_limit", "images_left"),
        ("song_limit", "songs_left"),
        ("music_limit", "music_left"),
    )
    initial_total = 0
    left_total = 0
    consumed_total = 0
    for limit_attr, left_attr in resources:
        limit = int(getattr(plan, limit_attr, 0) or 0)
        if limit <= 0:
            continue
        left = int(getattr(usage, left_attr, 0) or 0)
        initial_total += limit
        left_total += max(left, 0)
        consumed_total += max(limit - left, 0)
    return initial_total, left_total, consumed_total


def process_free_plan_triggers(sub: UserSubscription) -> dict[str, bool]:
    """
    Emit one-time notifications for free-plan milestones:
    1) first successful generation
    2) 20% limits remaining
    3) last day of free access
    """
    result = {"first_gen": False, "low_limits": False, "last_day": False}
    if not sub or not getattr(sub, "plan", None) or not sub.plan.is_free:
        return result
    if str(sub.status or "").lower() != SubscriptionStatus.ACTIVE:
        return result

    usage, _ = GenerationUsage.objects.get_or_create(subscription=sub)
    initial_total, left_total, consumed_total = _calc_plan_initial_and_left(sub, usage)

    if consumed_total >= 1:
        result["first_gen"] = _notify_user_once(sub.user, FREE_TRIGGER_FIRST_GEN)

    if initial_total > 0 and (left_total / initial_total) <= 0.2:
        result["low_limits"] = _notify_user_once(sub.user, FREE_TRIGGER_LOW_LIMIT)

    if sub.end_date and sub.end_date.date() == timezone.localdate():
        result["last_day"] = _notify_user_once(sub.user, FREE_TRIGGER_LAST_DAY)

    return result
