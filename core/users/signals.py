import logging

from django.db.models.signals import post_save
from django.dispatch import receiver

from .models import UserCardBind
from .services import activate_free_plan_for_user


logger = logging.getLogger("users")


@receiver(post_save, sender=UserCardBind)
def auto_activate_free_plan_on_card_bind(sender, instance, created, **kwargs):
    """Activate the free plan when a user binds a card for the first time."""
    if not created:
        return

    user = getattr(instance, "user", None)
    if not user or getattr(user, "free_plan_activated", False):
        return

    try:
        activated, reason = activate_free_plan_for_user(user)
    except Exception:
        logger.exception(
            "auto_activate_free_plan_on_card_bind unexpected error user=%s", getattr(user, "pk", None)
        )
        return

    if not activated:
        logger.info(
            "Free plan not activated on card bind user=%s reason=%s",
            getattr(user, "pk", None),
            reason,
        )
