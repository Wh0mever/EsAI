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
from .models import User, UserCardBind


logger = logging.getLogger("plans")


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
            end_date=now + timedelta(days=int(plan.duration_days or 30)),
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
