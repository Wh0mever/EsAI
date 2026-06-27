import logging
from django.utils.decorators import method_decorator
from django.views.decorators.cache import cache_page
from rest_framework import generics, permissions
from rest_framework.response import Response
from django.views.decorators.vary import vary_on_headers
from rest_framework.exceptions import NotFound

from .models import (
    Plan, UserSubscription, AddonPurchase, SubscriptionStatus, PaymentStatus,
    TokenPackage, TokenTransaction,
)
from .serializers import (
    PlanSerializer, UserSubscriptionSerializer,
    GenerationUsageSerializer, AddonPurchaseSerializer,
    TokenPackageSerializer, TokenTransactionSerializer,
)
from .services import get_currency_per_usd_map_cached
from .services import plan_cycle_days
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status as drf_status
from rest_framework_simplejwt.authentication import JWTAuthentication
from django.utils import timezone
from django.conf import settings
import uuid
import requests
from datetime import timedelta
from users.models import User, UserCardBind
from django.db import transaction
from payments.freedompay import FreedomPay, FreedomPayError, make_api_signature
from decimal import Decimal


@method_decorator(cache_page(60), name="dispatch")               # page cache
@method_decorator(vary_on_headers("Accept-Language"), name="dispatch")  # vary by i18n header (если нужно)
class PlanListView(generics.ListAPIView):
    """Public plans for pricing page."""
    permission_classes = [permissions.AllowAny]
    serializer_class = PlanSerializer

    ALLOWED_PERIODS = {"weekly", "monthly", "yearly"}

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
    """Add-on purchases of the current user profile."""
    permission_classes = [permissions.IsAuthenticated]
    serializer_class = AddonPurchaseSerializer

    def get_queryset(self):
        return (AddonPurchase.objects
                .filter(user=self.request.user)
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

        u: User = request.user
        now = timezone.now()

        # Paid plan + linked card => charge first, then switch/activate.
        # This prevents granting new limits without successful payment.
        charged_now = False
        price_amount = Decimal(str(getattr(plan, "price_amount", 0) or 0))
        is_paid_plan = (not plan.is_free) and price_amount > 0
        card = UserCardBind.objects.filter(user=u).order_by("-created_at").first()
        if is_paid_plan and card:
            card_token = (card.card_token or "").strip()
            if not card_token:
                return Response({"message": "no_pay_token"}, status=400)
            try:
                fp = FreedomPay(u)
                order_id = f"plan-switch-{u.id}-{uuid.uuid4().hex[:10]}"
                charge_resp = fp.charge(
                    amount=price_amount,
                    currency="USD",
                    order_id=order_id,
                    description=f"Plan switch to #{plan.id} for user #{u.id}",
                    card_token=card_token,
                    test=False,
                )
                status_text = str((charge_resp or {}).get("pg_status") or "").lower()
                if status_text != "ok":
                    return Response({"message": "provider_declined"}, status=400)
                charged_now = True
            except FreedomPayError as exc:
                log = logging.getLogger("plans")
                if exc.is_provider_decline:
                    log.warning(
                        "plan_switch_charge_declined user=%s plan=%s order=%s code=%s status=%s desc=%s response=%s",
                        u.id,
                        plan.id,
                        order_id,
                        exc.code,
                        exc.status,
                        exc.description,
                        exc.response,
                    )
                    return Response({"message": "provider_declined"}, status=400)
                log.exception(
                    "plan_switch_charge_failed user=%s plan=%s order=%s",
                    u.id,
                    plan.id,
                    order_id,
                )
                return Response({"message": "provider_error"}, status=502)
            except Exception:
                logging.getLogger("plans").exception(
                    "plan_switch_charge_failed user=%s plan=%s", u.id, plan.id
                )
                return Response({"message": "provider_error"}, status=502)

        # Switch and activate new plan in a transaction
        from .models import GenerationUsage
        with transaction.atomic():
            # If already on this plan, keep behavior as 'already_active'
            if existing and existing.plan_id == plan.id:
                if not existing.end_date:
                    existing.start_date = now
                    existing.end_date = now + timedelta(days=plan_cycle_days(plan.period))
                    existing.save(update_fields=["start_date", "end_date"])
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
                end_date=now + timedelta(days=plan_cycle_days(plan.period)),
                status=SubscriptionStatus.ACTIVE,
                payment_status=PaymentStatus.PAID if charged_now else PaymentStatus.UNPAID,
                payment_date=now if charged_now else None,
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


# =========================================================================
# Pay-as-you-go токен-эндпоинты
# =========================================================================


class TokenBalanceView(APIView):
    """GET /api/plans/balance/ — текущий баланс токенов пользователя."""
    authentication_classes = [JWTAuthentication]
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        balance = int(getattr(request.user, "token_balance", 0) or 0)
        return Response({"balance_tokens": balance}, status=200)


class TokenPackageListView(generics.ListAPIView):
    """GET /api/plans/packages/ — публичный список активных пакетов токенов."""
    permission_classes = [permissions.AllowAny]
    serializer_class = TokenPackageSerializer

    def get_queryset(self):
        return TokenPackage.objects.filter(is_active=True).order_by("sort_order", "id")


class TokenTransactionListView(generics.ListAPIView):
    """GET /api/plans/transactions/ — последние ~50 транзакций токенов юзера."""
    authentication_classes = [JWTAuthentication]
    permission_classes = [permissions.IsAuthenticated]
    serializer_class = TokenTransactionSerializer

    def get_queryset(self):
        return (
            TokenTransaction.objects
            .filter(user=self.request.user)
            .order_by("-created_at")[:50]
        )


class TokenPurchaseView(APIView):
    """POST /api/plans/purchase/ {"package_id"} — инициировать оплату пакета токенов.

    Переиспользует FreedomPay init_payment flow (как payments.StartOneTimePaymentAPIView).
    Связь пакет↔платёж хранится в Payment.request["token_purchase"] и в order_id (tokpkg-...).
    Callback (payments.FreedomPayTokenPurchase*View) начислит токены по успешной оплате.
    """
    authentication_classes = [JWTAuthentication]
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        from payments.views import _parse_fp_response
        from payments.models import Payment
        from django.urls import reverse

        package_id = (request.data or {}).get("package_id")
        try:
            package = TokenPackage.objects.get(pk=int(package_id), is_active=True)
        except (TokenPackage.DoesNotExist, TypeError, ValueError):
            return Response({"message": "package_not_found"}, status=drf_status.HTTP_404_NOT_FOUND)

        amount = Decimal(str(package.price or 0)).quantize(Decimal("0.01"))
        if amount <= 0:
            return Response({"message": "package_not_payable"}, status=drf_status.HTTP_400_BAD_REQUEST)
        currency = (package.currency or "KGS").strip().upper()

        merchant_id = (settings.FREEDOM_PAY_MERCHANT_ID or settings.FP_MERCHANT_ID or "").strip()
        secret = (settings.FREEDOM_PAY_TOKEN or "").strip()
        init_url = (settings.FREEDOM_PAY_INIT_PAYMENT_URL or "").strip()
        if not (merchant_id and secret and init_url):
            return Response({"detail": "freedompay_config_missing"}, status=drf_status.HTTP_502_BAD_GATEWAY)

        order_id = f"tokpkg-{request.user.id}-{package.id}-{uuid.uuid4().hex[:10]}"
        payload = {
            "pg_merchant_id": merchant_id,
            "pg_amount": format(amount, "f"),
            "pg_currency": currency,
            "pg_order_id": order_id,
            "pg_user_id": str(request.user.id),
            "pg_description": f"Token package #{package.id} for user #{request.user.id}",
            "pg_salt": uuid.uuid4().hex,
            "pg_success_url": request.build_absolute_uri(reverse("payments:freedompay-tokens-success")),
            "pg_failure_url": request.build_absolute_uri(reverse("payments:freedompay-tokens-failure")),
            "pg_post_link": request.build_absolute_uri(reverse("payments:freedompay-tokens-postback")),
            "pg_testing_mode": int(settings.DEBUG),
        }
        payload["pg_sig"] = make_api_signature("init_payment", payload, secret)

        payment = Payment.objects.create(
            user=request.user,
            amount=amount,
            currency=currency,
            order_id=order_id,
            description=f"Token package purchase #{package.id}",
            is_test=settings.DEBUG,
            request={
                "token_purchase": {
                    "package_id": package.id,
                    "tokens": int(package.tokens or 0),
                    "bonus_tokens": int(package.bonus_tokens or 0),
                    "payload": payload,
                }
            },
            response={},
        )

        try:
            response = requests.post(init_url, data=payload, timeout=30)
            try:
                body = response.json()
            except ValueError:
                body = _parse_fp_response(response.text)
            except Exception:
                body = {"raw": response.text}
        except requests.RequestException as exc:
            payment.error = str(exc)
            payment.save(update_fields=["error"])
            return Response({"detail": "freedompay_request_failed"}, status=drf_status.HTTP_502_BAD_GATEWAY)

        payment.response = {"token_purchase_init": body}
        if response.status_code >= 400:
            payment.error = body.get("pg_error_description") or body.get("pg_error_message") or "freedompay_http_error"
            payment.save(update_fields=["response", "error"])
            return Response({"detail": payment.error}, status=drf_status.HTTP_502_BAD_GATEWAY)

        redirect_url = body.get("pg_redirect_url") or body.get("redirect_url") or body.get("payment_url")
        if not redirect_url:
            payment.error = "freedompay_redirect_url_missing"
            payment.save(update_fields=["response", "error"])
            return Response({"detail": payment.error}, status=drf_status.HTTP_502_BAD_GATEWAY)

        payment.save(update_fields=["response"])
        return Response(
            {
                "redirect_url": redirect_url,
                "order_id": order_id,
                "amount": str(amount),
                "currency": currency,
                "package_id": package.id,
            },
            status=drf_status.HTTP_200_OK,
        )
