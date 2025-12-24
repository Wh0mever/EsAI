import logging
from django.utils.decorators import method_decorator
from django.views.decorators.cache import cache_page
from rest_framework import generics, permissions
from rest_framework.response import Response
from django.views.decorators.vary import vary_on_headers
from rest_framework.exceptions import NotFound

from .models import Plan, UserSubscription, AddonPurchase, SubscriptionStatus, PaymentStatus
from .serializers import (
    PlanSerializer, UserSubscriptionSerializer,
    GenerationUsageSerializer, AddonPurchaseSerializer
)
from .services import get_currency_per_usd_map_cached
from rest_framework.views import APIView
from rest_framework_simplejwt.authentication import JWTAuthentication
from django.utils import timezone
import uuid
from datetime import timedelta
from users.models import User, UserCardBind
from django.db import transaction
from payments.freedompay import FreedomPay
from decimal import Decimal


@method_decorator(cache_page(60), name="dispatch")               # page cache
@method_decorator(vary_on_headers("Accept-Language"), name="dispatch")  # vary by i18n header (если нужно)
class PlanListView(generics.ListAPIView):
    """Public plans for pricing page."""
    permission_classes = [permissions.AllowAny]
    serializer_class = PlanSerializer

    ALLOWED_PERIODS = {"monthly", "yearly"}

    def get_queryset(self):
        qs = (
            Plan.objects
            .filter(is_active=True)
            .order_by("sort_order", "id")
            .select_related(None)
        )
        period = self.request.query_params.get("period")
        if period in self.ALLOWED_PERIODS:
            qs = qs.filter(period=period)
        return qs

    def get_serializer_context(self):
        ctx = super().get_serializer_context()
        # Preload RUB/KGS once; serializer не дергает БД повторно
        ctx["currency_per_usd"] = get_currency_per_usd_map_cached(["RUB", "KGS"], timeout=300)
        return ctx


class PlanRetrieveView(generics.RetrieveAPIView):
    permission_classes = [permissions.AllowAny]
    serializer_class = PlanSerializer
    queryset = Plan.objects.filter(is_active=True).order_by("sort_order", "id")


class MeSubscriptionView(generics.GenericAPIView):
    """Current active subscription for the authenticated user."""
    permission_classes = [permissions.IsAuthenticated]
    serializer_class = UserSubscriptionSerializer

    def get(self, request, *args, **kwargs):
        sub = (UserSubscription.objects
               .select_related("plan")
               .select_related("usage")
               .filter(user=request.user, status=SubscriptionStatus.ACTIVE)
               .order_by("-start_date")
               .first())
        if not sub:
            raise NotFound("Active subscription not found.")
        return Response(self.get_serializer(sub).data)


class MeUsageView(generics.GenericAPIView):
    """Only usage counters for the current active subscription."""
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, *args, **kwargs):
        sub = (UserSubscription.objects
               .select_related("plan", "usage")
               .filter(user=request.user, status=SubscriptionStatus.ACTIVE)
               .order_by("-start_date")
               .first())
        if not sub or not hasattr(sub, "usage"):
            raise NotFound("Usage not found.")
        return Response(GenerationUsageSerializer(sub.usage).data)


class MeAddonsView(generics.ListAPIView):
    """Add-on purchases of the current active subscription."""
    permission_classes = [permissions.IsAuthenticated]
    serializer_class = AddonPurchaseSerializer

    def get_queryset(self):
        sub = (UserSubscription.objects
               .filter(user=self.request.user, status=SubscriptionStatus.ACTIVE)
               .order_by("-start_date")
               .first())
        if not sub:
            return AddonPurchase.objects.none()
        return (AddonPurchase.objects
                .filter(subscription=sub)
                .order_by("-purchase_date"))


class UnsubscribeView(APIView):
    """Disable auto-renew for the current active subscription."""

    authentication_classes = [JWTAuthentication]
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, *args, **kwargs):
        sub = (UserSubscription.objects
               .select_related("plan", "usage", "user")
               .filter(user=request.user, status=SubscriptionStatus.ACTIVE)
               .order_by("-start_date")
               .first())
        if not sub:
            raise NotFound("Active subscription not found.")
        if sub.auto_renew:
            sub.auto_renew = False
            sub.save(update_fields=["auto_renew"])
        if getattr(request.user, "auto_renew", True):
            request.user.auto_renew = False
            request.user.save(update_fields=["auto_renew"])
        return Response(UserSubscriptionSerializer(sub).data, status=200)


class ResumeSubscriptionView(APIView):
    """Re-enable auto-renew for the current active subscription."""

    authentication_classes = [JWTAuthentication]
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, *args, **kwargs):
        sub = (UserSubscription.objects
               .select_related("plan", "usage", "user")
               .filter(user=request.user, status=SubscriptionStatus.ACTIVE)
               .order_by("-start_date")
               .first())
        if not sub:
            raise NotFound("Active subscription not found.")
        if not sub.auto_renew:
            sub.auto_renew = True
            sub.save(update_fields=["auto_renew"])
        if not getattr(request.user, "auto_renew", True):
            request.user.auto_renew = True
            request.user.save(update_fields=["auto_renew"])
        return Response(UserSubscriptionSerializer(sub).data, status=200)


class ActivatePlanView(APIView):
    """Activate a plan for the current user if prerequisites are met.

    Conditions:
    - User must be authenticated
    - Plan must exist and be active
    - User must NOT have an active subscription
    - User must have a saved payment token (pay_token) and basic card meta

    On success, creates an ACTIVE subscription with UNPAID status and initializes usage.
    """

    authentication_classes = [JWTAuthentication]
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, plan_id: int):
        # Current active subscription (may be for a different plan)
        existing = (UserSubscription.objects
                    .select_related("plan")
                    .filter(user=request.user, status=SubscriptionStatus.ACTIVE)
                    .order_by("-start_date")
                    .first())

        # Plan must exist and be active
        try:
            plan = Plan.objects.get(pk=plan_id, is_active=True)
        except Plan.DoesNotExist:
            return Response({"message": "plan_not_found"}, status=404)

        # Must have saved card token
        u: User = request.user
        card = UserCardBind.objects.filter(user=u).order_by("-created_at").first()
        if not card:
            return Response({"message": "no_card"}, status=400)

        # Switch and activate new plan in a transaction
        from .models import GenerationUsage
        with transaction.atomic():
            # If already on this plan, keep behavior as 'already_active'
            if existing and existing.plan_id == plan.id:
                return Response({"message": "already_active"}, status=400)

            # If switching from another active plan: rollover leftovers to bonus and deactivate old
            if existing and existing.plan_id != plan.id:
                user_locked = type(u).objects.select_for_update().get(pk=u.pk)
                usage, _ = GenerationUsage.objects.select_for_update().get_or_create(subscription=existing)
                old_plan = existing.plan
                if old_plan.text_limit and (usage.texts_left or 0) > 0:
                    user_locked.bonus_texts = (user_locked.bonus_texts or 0) + int(usage.texts_left)
                if old_plan.image_limit and (usage.images_left or 0) > 0:
                    user_locked.bonus_images = (user_locked.bonus_images or 0) + int(usage.images_left)
                if old_plan.song_limit and (usage.songs_left or 0) > 0:
                    user_locked.bonus_songs = (user_locked.bonus_songs or 0) + int(usage.songs_left)
                if old_plan.music_limit and (usage.music_left or 0) > 0:
                    user_locked.bonus_music = (user_locked.bonus_music or 0) + int(usage.music_left)
                user_locked.save(update_fields=["bonus_texts", "bonus_images", "bonus_songs", "bonus_music"])
                existing.status = SubscriptionStatus.INACTIVE
                existing.save(update_fields=["status"])
                logging.getLogger("plans").info(
                    "subscription_switched user=%s from_sub=%s from_plan=%s to_plan=%s",
                    u.id, existing.id, old_plan.id, plan.id,
                )

            # Create subscription and initialize usage counters for the new plan
            now = timezone.now()
            sub = UserSubscription.objects.create(
                user=u,
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
        
        resp = UserSubscriptionSerializer(sub).data
        logging.getLogger("plans").info(
            "subscription_created user=%s sub_id=%s plan_id=%s end_date=%s",
            request.user.id, sub.id, plan.id, sub.end_date)
        return Response(resp, status=200)
