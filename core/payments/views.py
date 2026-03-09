import logging
import uuid
import xml.etree.ElementTree as ET
from datetime import timedelta
from decimal import Decimal
from urllib.parse import urlencode, urljoin

import requests

from django.urls import reverse
from django.utils import timezone
from django.db import transaction
from rest_framework import permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView
from django.conf import settings
from django.http import HttpResponseRedirect

from users.models import User, UserCardBind
from plans.models import (
    Plan,
    UserSubscription,
    GenerationUsage,
    SubscriptionStatus,
    PaymentStatus,
    CurrencyRate,
    GenerationUnitPrice,
)
from plans.services import plan_cycle_days
from .freedompay import (
    FreedomPayHPPClient,
    FreedomPayError,
    save_freedompay_callback,
    FreedomPay,
    make_api_signature,
)
from .models import Payment


logger = logging.getLogger()

Q2 = Decimal("0.01")


def _topup_unit_prices_usd() -> dict[str, Decimal] | None:
    cfg = GenerationUnitPrice.objects.order_by("id").first()
    if not cfg:
        return None
    return {
        "music": Decimal(str(cfg.music_price or 0)).quantize(Q2),
        "images": Decimal(str(cfg.image_price or 0)).quantize(Q2),
        "texts": Decimal(str(cfg.text_price or 0)).quantize(Q2),
    }


class StartBindCardAPIView(APIView):
    """Generate FreedomPay Hosted Payment Page redirect URL."""

    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        body = request.data or {}
        order_id = f"bind-{request.user.id}-{uuid.uuid4().hex[:8]}"
        callback_url = request.build_absolute_uri(reverse("payments:card-bind-callback"))

        back_link_input = body.get("back_link") or body.get("back_path") or "/profile"
        if isinstance(back_link_input, str) and back_link_input.startswith(("http://", "https://")):
            back_link = back_link_input
        else:
            path = str(back_link_input or "/profile")
            if not path.startswith("/"):
                path = f"/{path}"
            back_link = request.build_absolute_uri(path)

        try:
            client = FreedomPayHPPClient()
        except FreedomPayError as exc:
            logger.warning("FreedomPay client init failed: %s", exc)
            return Response({"detail": str(exc)}, status=status.HTTP_502_BAD_GATEWAY)
        except Exception:
            logger.exception("FreedomPay client init unexpected error")
            return Response({"detail": "freedompay_error"}, status=status.HTTP_502_BAD_GATEWAY)

        logger.info(
            "FreedomPay bind init user=%s order=%s callback=%s back=%s",
            request.user.id,
            order_id,
            callback_url,
            back_link,
        )

        try:
            redirect_url = client.start_card_bind(
                user_id=request.user.id,
                post_link=callback_url,
                back_link=back_link,
            )
        except FreedomPayError as exc:
            logger.warning(
                "FreedomPay bind start failed: %s endpoint=%s request=%s response=%s",
                exc,
                getattr(client, "last_endpoint", ""),
                getattr(client, "last_request", {}),
                getattr(client, "last_response", {}),
            )
            return Response({"detail": str(exc)}, status=status.HTTP_502_BAD_GATEWAY)
        except Exception:
            logger.exception(
                "FreedomPay bind start unexpected error endpoint=%s request=%s response=%s",
                getattr(client, "last_endpoint", ""),
                getattr(client, "last_request", {}),
                getattr(client, "last_response", {}),
            )
            return Response({"detail": "freedompay_error"}, status=status.HTTP_502_BAD_GATEWAY)
        return Response({"redirect_url": redirect_url})


class FreedomPayCallbackAPIView(APIView):
    """Handle POST callback from FreedomPay once card is stored."""

    authentication_classes = []
    permission_classes = []

    def post(self, request):
        is_success = save_freedompay_callback(request.data or {})
        
        if is_success is False:
            return Response({"status": "error"}, status=status.HTTP_400_BAD_REQUEST)
            
        return Response({"status": "ok"})


class RemoveCardAPIView(APIView):
    """Remove bound card from FreedomPay and delete local token."""

    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        card = UserCardBind.objects.filter(user=request.user).order_by("-created_at").first()
        card_token = (card.card_token or "").strip() if card else ""
        if not card_token:
            return Response({"detail": "no_card"}, status=status.HTTP_400_BAD_REQUEST)

        try:
            client = FreedomPay(request.user)
            client.remove_card(card_token)
        except FreedomPayError as exc:
            logger.warning("FreedomPay remove failed: %s", exc)
            return Response({"detail": str(exc)}, status=status.HTTP_502_BAD_GATEWAY)
        except Exception:
            logger.exception("FreedomPay remove unexpected error")
            return Response({"detail": "freedompay_error"}, status=status.HTTP_502_BAD_GATEWAY)

        UserCardBind.objects.filter(user=request.user).delete()
        return Response({"status": "deleted"})


def _normalize_payload(data):
    if hasattr(data, "lists"):
        return {key: values[-1] if values else "" for key, values in data.lists()}
    if isinstance(data, dict):
        return {k: v for k, v in data.items()}
    return {}


def _parse_fp_response(raw: str):
    text = (raw or "").strip()
    if not text:
        return {"raw": raw}
    try:
        root = ET.fromstring(text)
    except Exception:
        return {"raw": raw}
    result = {}
    for child in root:
        result[child.tag] = (child.text or "").strip()
    if not result:
        result[root.tag] = (root.text or "").strip()
    return result


def _frontend_absolute_url(request, path: str, query: dict | None = None) -> str:
    base = (settings.SITE_BASE_URL or "").rstrip("/")
    if not base:
        base = f"{request.scheme}://{request.get_host()}"
    full = urljoin(f"{base}/", path.lstrip("/"))
    if query:
        return f"{full}?{urlencode(query)}"
    return full


def _normalize_positive_int(value, default: int = 0) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return max(parsed, 0)


def _convert_usd_to_user_currency(user: User, amount_usd: Decimal) -> tuple[Decimal, str]:
    selected = (getattr(user, "selected_currency", "") or "USD").strip().upper()
    if selected not in {"USD", "RUB", "KGS"}:
        selected = "USD"
    if selected == "USD":
        return amount_usd, "USD"

    rate_to_usd = CurrencyRate.objects.filter(currency=selected).values_list("rate_to_usd", flat=True).first()
    if not rate_to_usd:
        return amount_usd, "USD"

    try:
        rate_dec = Decimal(str(rate_to_usd))
        if rate_dec <= 0:
            return amount_usd, "USD"
        converted = (amount_usd / rate_dec).quantize(Decimal("0.01"))
        return converted, selected
    except Exception:
        return amount_usd, "USD"


def _convert_usd_to_currency(amount_usd: Decimal, currency: str) -> Decimal | None:
    code = (currency or "").strip().upper()
    if code == "USD":
        return amount_usd.quantize(Q2)
    if code not in {"RUB", "KGS"}:
        return None
    rate_to_usd = CurrencyRate.objects.filter(currency=code).values_list("rate_to_usd", flat=True).first()
    if not rate_to_usd:
        return None
    try:
        rate_dec = Decimal(str(rate_to_usd))
        if rate_dec <= 0:
            return None
        return (amount_usd / rate_dec).quantize(Q2)
    except Exception:
        return None


def _get_user_active_paid_subscription(user: User) -> UserSubscription | None:
    sub = (
        UserSubscription.objects
        .select_related("plan")
        .filter(user=user, status=SubscriptionStatus.ACTIVE)
        .order_by("-start_date")
        .first()
    )
    if not sub or not getattr(sub, "plan", None) or bool(sub.plan.is_free):
        return None
    return sub


def _activate_paid_plan_for_user(user: User, plan: Plan) -> tuple[UserSubscription, str]:
    existing = (
        UserSubscription.objects
        .select_related("plan")
        .filter(user=user, status=SubscriptionStatus.ACTIVE)
        .order_by("-start_date")
        .first()
    )

    with transaction.atomic():
        now = timezone.now()
        if existing and existing.plan_id == plan.id:
            changed_fields = []
            cycle_days = plan_cycle_days(plan.period)
            # Ensure next charge date is always defined and aligned to current activation.
            existing.start_date = now
            existing.end_date = now + timedelta(days=cycle_days)
            changed_fields.extend(["start_date", "end_date"])
            if existing.payment_status != PaymentStatus.PAID:
                existing.payment_status = PaymentStatus.PAID
                changed_fields.append("payment_status")
            existing.payment_date = now
            changed_fields.append("payment_date")
            if existing.auto_renew:
                existing.auto_renew = False
                changed_fields.append("auto_renew")
            if changed_fields:
                existing.save(update_fields=changed_fields)
            if getattr(user, "auto_renew", True):
                user.auto_renew = False
                user.save(update_fields=["auto_renew"])
            return existing, "already_active"

        if existing and existing.plan_id != plan.id:
            user_locked = type(user).objects.select_for_update().get(pk=user.pk)
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
            user_locked.auto_renew = False
            user_locked.save(update_fields=["bonus_texts", "bonus_images", "bonus_songs", "bonus_music", "auto_renew"])
            existing.status = SubscriptionStatus.INACTIVE
            existing.save(update_fields=["status"])

        sub = UserSubscription.objects.create(
            user=user,
            plan=plan,
            start_date=now,
            end_date=now + timedelta(days=plan_cycle_days(plan.period)),
            status=SubscriptionStatus.ACTIVE,
            payment_status=PaymentStatus.PAID,
            payment_date=now,
            auto_renew=False,
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
        if getattr(user, "auto_renew", True):
            user.auto_renew = False
            user.save(update_fields=["auto_renew"])
        return sub, "activated"


class StartOneTimePaymentAPIView(APIView):
    """Initialize one-time FreedomPay payment and return redirect URL."""

    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, plan_id: int):
        try:
            plan = Plan.objects.get(pk=plan_id, is_active=True)
        except Plan.DoesNotExist:
            return Response({"message": "plan_not_found"}, status=status.HTTP_404_NOT_FOUND)

        amount = Decimal(str(plan.price_amount or 0)).quantize(Decimal("0.01"))
        if plan.is_free or amount <= 0:
            return Response({"message": "plan_not_payable"}, status=status.HTTP_400_BAD_REQUEST)

        merchant_id = (settings.FREEDOM_PAY_MERCHANT_ID or settings.FP_MERCHANT_ID or "").strip()
        secret = (settings.FREEDOM_PAY_TOKEN or "").strip()
        init_url = (settings.FREEDOM_PAY_INIT_PAYMENT_URL or "").strip()
        if not (merchant_id and secret and init_url):
            return Response({"detail": "freedompay_config_missing"}, status=status.HTTP_502_BAD_GATEWAY)

        order_id = f"ot-{request.user.id}-{plan.id}-{uuid.uuid4().hex[:10]}"
        currency = "USD"

        payload = {
            "pg_merchant_id": merchant_id,
            "pg_amount": format(amount, "f"),
            "pg_currency": currency,
            "pg_order_id": order_id,
            "pg_user_id": str(request.user.id),
            "pg_description": f"One-time payment for plan #{plan.id}",
            "pg_salt": uuid.uuid4().hex,
            "pg_success_url": request.build_absolute_uri(reverse("payments:freedompay-onetime-success")),
            "pg_failure_url": request.build_absolute_uri(reverse("payments:freedompay-onetime-failure")),
            "pg_post_link": request.build_absolute_uri(reverse("payments:freedompay-onetime-postback")),
            "pg_testing_mode": int(settings.DEBUG),
        }
        payload["pg_sig"] = make_api_signature("init_payment", payload, secret)

        payment = Payment.objects.create(
            user=request.user,
            amount=amount,
            currency=currency,
            order_id=order_id,
            description=f"One-time plan payment #{plan.id}",
            is_test=settings.DEBUG,
            request={"one_time_init": {"plan_id": plan.id, "payload": payload}},
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
            return Response({"detail": "freedompay_request_failed"}, status=status.HTTP_502_BAD_GATEWAY)

        payment.response = {"one_time_init": body}
        if response.status_code >= 400:
            payment.error = body.get("pg_error_description") or body.get("pg_error_message") or "freedompay_http_error"
            payment.save(update_fields=["response", "error"])
            return Response({"detail": payment.error}, status=status.HTTP_502_BAD_GATEWAY)

        redirect_url = body.get("pg_redirect_url") or body.get("redirect_url") or body.get("payment_url")
        if not redirect_url:
            payment.error = "freedompay_redirect_url_missing"
            payment.save(update_fields=["response", "error"])
            return Response({"detail": payment.error}, status=status.HTTP_502_BAD_GATEWAY)

        payment.save(update_fields=["response"])
        return Response({"redirect_url": redirect_url}, status=status.HTTP_200_OK)


def _apply_generation_topup_to_user(user: User, payload: dict) -> None:
    if not _get_user_active_paid_subscription(user):
        raise ValueError("paid_active_subscription_required")

    counts = payload.get("counts") or {}
    music = _normalize_positive_int(counts.get("music"), 0)
    images = _normalize_positive_int(counts.get("images"), 0)
    texts = _normalize_positive_int(counts.get("texts"), 0)

    if music <= 0 and images <= 0 and texts <= 0:
        raise ValueError("no_generations_selected")

    with transaction.atomic():
        user_locked = type(user).objects.select_for_update().get(pk=user.pk)
        user_locked.bonus_music = int(user_locked.bonus_music or 0) + music
        user_locked.bonus_images = int(user_locked.bonus_images or 0) + images
        user_locked.bonus_texts = int(user_locked.bonus_texts or 0) + texts
        user_locked.save(update_fields=["bonus_music", "bonus_images", "bonus_texts"])


class GenerationTopupPricingAPIView(APIView):
    """Unit prices for generation top-up (single source, no DB singleton model)."""

    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        prices = _topup_unit_prices_usd()
        if not prices:
            return Response({"configured": False, "data": None}, status=status.HTTP_200_OK)
        music_usd = prices["music"]
        image_usd = prices["images"]
        text_usd = prices["texts"]
        return Response(
            {
                "configured": True,
                "data": {
                    "music_price": str(music_usd),
                    "image_price": str(image_usd),
                    "text_price": str(text_usd),
                    "music_price_rub": str(_convert_usd_to_currency(music_usd, "RUB") or 0),
                    "music_price_kgs": str(_convert_usd_to_currency(music_usd, "KGS") or 0),
                    "image_price_rub": str(_convert_usd_to_currency(image_usd, "RUB") or 0),
                    "image_price_kgs": str(_convert_usd_to_currency(image_usd, "KGS") or 0),
                    "text_price_rub": str(_convert_usd_to_currency(text_usd, "RUB") or 0),
                    "text_price_kgs": str(_convert_usd_to_currency(text_usd, "KGS") or 0),
                },
            },
            status=status.HTTP_200_OK,
        )


class StartGenerationTopupPaymentAPIView(APIView):
    """Initialize one-time payment for extra generations and return redirect URL."""

    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        subscription = _get_user_active_paid_subscription(request.user)
        if not subscription:
            return Response({"message": "paid_active_subscription_required"}, status=status.HTTP_400_BAD_REQUEST)
        if not bool(getattr(getattr(subscription, "plan", None), "can_purchase_addons", False)):
            return Response({"message": "addons_not_allowed_for_plan"}, status=status.HTTP_400_BAD_REQUEST)

        unit_prices = _topup_unit_prices_usd()
        if not unit_prices:
            return Response({"message": "unit_prices_not_configured"}, status=status.HTTP_400_BAD_REQUEST)

        payload = request.data or {}
        music_count = _normalize_positive_int(payload.get("music"), 0)
        image_count = _normalize_positive_int(payload.get("images"), 0)
        text_count = _normalize_positive_int(payload.get("texts"), 0)
        total_units = music_count + image_count + text_count
        if total_units <= 0:
            return Response({"message": "empty_selection"}, status=status.HTTP_400_BAD_REQUEST)

        total_usd = (
            unit_prices["music"] * music_count
            + unit_prices["images"] * image_count
            + unit_prices["texts"] * text_count
        ).quantize(Decimal("0.01"))
        if total_usd <= 0:
            return Response({"message": "topup_not_payable"}, status=status.HTTP_400_BAD_REQUEST)

        amount, currency = _convert_usd_to_user_currency(request.user, total_usd)

        merchant_id = (settings.FREEDOM_PAY_MERCHANT_ID or settings.FP_MERCHANT_ID or "").strip()
        secret = (settings.FREEDOM_PAY_TOKEN or "").strip()
        init_url = (settings.FREEDOM_PAY_INIT_PAYMENT_URL or "").strip()
        if not (merchant_id and secret and init_url):
            return Response({"detail": "freedompay_config_missing"}, status=status.HTTP_502_BAD_GATEWAY)

        order_id = f"topup-{request.user.id}-{uuid.uuid4().hex[:10]}"
        fp_payload = {
            "pg_merchant_id": merchant_id,
            "pg_amount": format(amount, "f"),
            "pg_currency": currency,
            "pg_order_id": order_id,
            "pg_user_id": str(request.user.id),
            "pg_description": f"Generation top-up for user #{request.user.id}",
            "pg_salt": uuid.uuid4().hex,
            "pg_success_url": request.build_absolute_uri(reverse("payments:freedompay-topup-success")),
            "pg_failure_url": request.build_absolute_uri(reverse("payments:freedompay-topup-failure")),
            "pg_post_link": request.build_absolute_uri(reverse("payments:freedompay-topup-postback")),
            "pg_testing_mode": int(settings.DEBUG),
        }
        fp_payload["pg_sig"] = make_api_signature("init_payment", fp_payload, secret)

        payment = Payment.objects.create(
            user=request.user,
            amount=amount,
            currency=currency,
            order_id=order_id,
            description="Generation top-up payment",
            is_test=settings.DEBUG,
            request={
                "topup_init": {
                    "counts": {"music": music_count, "images": image_count, "texts": text_count},
                    "unit_prices_usd": {
                        "music": str(unit_prices["music"]),
                        "images": str(unit_prices["images"]),
                        "texts": str(unit_prices["texts"]),
                    },
                    "amount_usd": str(total_usd),
                    "amount": str(amount),
                    "currency": currency,
                    "payload": fp_payload,
                }
            },
            response={},
        )

        try:
            response = requests.post(init_url, data=fp_payload, timeout=30)
            try:
                body = response.json()
            except ValueError:
                body = _parse_fp_response(response.text)
            except Exception:
                body = {"raw": response.text}
        except requests.RequestException as exc:
            payment.error = str(exc)
            payment.save(update_fields=["error"])
            return Response({"detail": "freedompay_request_failed"}, status=status.HTTP_502_BAD_GATEWAY)

        payment.response = {"topup_init": body}
        if response.status_code >= 400:
            payment.error = body.get("pg_error_description") or body.get("pg_error_message") or "freedompay_http_error"
            payment.save(update_fields=["response", "error"])
            return Response({"detail": payment.error}, status=status.HTTP_502_BAD_GATEWAY)

        redirect_url = body.get("pg_redirect_url") or body.get("redirect_url") or body.get("payment_url")
        if not redirect_url:
            payment.error = "freedompay_redirect_url_missing"
            payment.save(update_fields=["response", "error"])
            return Response({"detail": payment.error}, status=status.HTTP_502_BAD_GATEWAY)

        payment.save(update_fields=["response"])
        return Response(
            {
                "redirect_url": redirect_url,
                "amount": str(amount),
                "currency": currency,
                "amount_usd": str(total_usd),
                "counts": {"music": music_count, "images": image_count, "texts": text_count},
            },
            status=status.HTTP_200_OK,
        )


class FreedomPayOneTimeResultBaseView(APIView):
    authentication_classes = []
    permission_classes = []
    result_type = "success"

    def get(self, request, *args, **kwargs):
        return self._handle(request, request.query_params)

    def post(self, request, *args, **kwargs):
        return self._handle(request, request.data)

    def _handle(self, request, payload_source):
        payload = _normalize_payload(payload_source)
        order_id = payload.get("pg_order_id") or payload.get("order_id")
        payment = Payment.objects.filter(order_id=order_id).order_by("-id").first() if order_id else None
        plan_id = None
        if payment and isinstance(payment.request, dict):
            plan_id = ((payment.request.get("one_time_init") or {}).get("plan_id"))

        if payment:
            response = payment.response or {}
            callbacks = list(response.get("callbacks") or [])
            callbacks.append({"type": self.result_type, "payload": payload})
            response["callbacks"] = callbacks
            payment.response = response

            if self.result_type == "success":
                error_text = payload.get("pg_error_description") or payload.get("pg_error_message") or ""
                status_text = str(payload.get("pg_status") or "").lower()
                result_flag = str(payload.get("pg_result") or "").strip()
                is_ok_status = (not status_text) or (status_text in {"ok", "success"})
                is_ok_result = (not result_flag) or (result_flag == "1")
                if error_text or (not is_ok_status) or (not is_ok_result):
                    payment.success = False
                    payment.error = str(error_text or f"freedompay_status_error:{status_text or result_flag or 'unknown'}")
                else:
                    payment.success = True
                    payment.error = ""
                    try:
                        if payment.user and plan_id:
                            plan = Plan.objects.get(pk=int(plan_id), is_active=True)
                            _activate_paid_plan_for_user(payment.user, plan)
                    except Exception as exc:
                        payment.success = False
                        payment.error = f"plan_activate_failed:{exc}"
            elif self.result_type == "failure":
                payment.success = False
                payment.error = payload.get("pg_error_description") or payload.get("pg_error_message") or "freedompay_failure"
            payment.save(update_fields=["response", "success", "error"])

        if self.result_type == "post":
            return Response({"status": "ok"}, status=status.HTTP_200_OK)

        if self.result_type == "success":
            success_path = f"/subscribe/{plan_id}/" if plan_id else "/pricing"
            return HttpResponseRedirect(
                _frontend_absolute_url(request, success_path, {"payment": "one_time_success"})
            )

        fallback_path = f"/subscribe/{plan_id}/" if plan_id else "/pricing"
        return HttpResponseRedirect(
            _frontend_absolute_url(request, fallback_path, {"payment": "one_time_failed"})
        )


class FreedomPayOneTimeSuccessView(FreedomPayOneTimeResultBaseView):
    result_type = "success"


class FreedomPayOneTimeFailureView(FreedomPayOneTimeResultBaseView):
    result_type = "failure"


class FreedomPayOneTimePostbackView(FreedomPayOneTimeResultBaseView):
    result_type = "post"


class FreedomPayGenerationTopupResultBaseView(APIView):
    authentication_classes = []
    permission_classes = []
    result_type = "success"

    def get(self, request, *args, **kwargs):
        return self._handle(request, request.query_params)

    def post(self, request, *args, **kwargs):
        return self._handle(request, request.data)

    def _handle(self, request, payload_source):
        payload = _normalize_payload(payload_source)
        order_id = payload.get("pg_order_id") or payload.get("order_id")
        payment = Payment.objects.filter(order_id=order_id).order_by("-id").first() if order_id else None

        if payment:
            response = payment.response or {}
            callbacks = list(response.get("callbacks") or [])
            callbacks.append({"type": self.result_type, "payload": payload})
            response["callbacks"] = callbacks
            payment.response = response

            if self.result_type == "success":
                error_text = payload.get("pg_error_description") or payload.get("pg_error_message") or ""
                status_text = str(payload.get("pg_status") or "").lower()
                result_flag = str(payload.get("pg_result") or "").strip()
                is_ok_status = (not status_text) or (status_text in {"ok", "success"})
                is_ok_result = (not result_flag) or (result_flag == "1")
                if error_text or (not is_ok_status) or (not is_ok_result):
                    payment.success = False
                    payment.error = str(error_text or f"freedompay_status_error:{status_text or result_flag or 'unknown'}")
                else:
                    payment.success = True
                    payment.error = ""
                    try:
                        if not bool(response.get("topup_applied")):
                            topup_init = (payment.request or {}).get("topup_init") or {}
                            if payment.user and topup_init:
                                _apply_generation_topup_to_user(payment.user, topup_init)
                                response["topup_applied"] = True
                                payment.response = response
                    except Exception as exc:
                        payment.success = False
                        payment.error = f"generation_topup_apply_failed:{exc}"
            elif self.result_type == "failure":
                payment.success = False
                payment.error = payload.get("pg_error_description") or payload.get("pg_error_message") or "freedompay_failure"
            payment.save(update_fields=["response", "success", "error"])

        if self.result_type == "post":
            return Response({"status": "ok"}, status=status.HTTP_200_OK)

        if self.result_type == "success":
            return HttpResponseRedirect(
                _frontend_absolute_url(request, "/profile", {"payment": "topup_success"})
            )
        return HttpResponseRedirect(
            _frontend_absolute_url(request, "/profile", {"payment": "topup_failed"})
        )


class FreedomPayGenerationTopupSuccessView(FreedomPayGenerationTopupResultBaseView):
    result_type = "success"


class FreedomPayGenerationTopupFailureView(FreedomPayGenerationTopupResultBaseView):
    result_type = "failure"


class FreedomPayGenerationTopupPostbackView(FreedomPayGenerationTopupResultBaseView):
    result_type = "post"


class FreedomPayChargeResultView(APIView):
    """Record recurring charge redirects/callbacks."""

    authentication_classes = []
    permission_classes = []
    result_type = "success"  # overridden in subclasses

    def get(self, request, *args, **kwargs):
        return self._handle(request.query_params)

    def post(self, request, *args, **kwargs):
        return self._handle(request.data)

    def _handle(self, payload_source):
        payload = self._normalize_payload(payload_source)
        order_id = payload.get("pg_order_id") or payload.get("order_id")
        self._persist_payment(order_id, payload)
        logger.warning(
            "FreedomPay %s callback order=%s payload=%s",
            self.result_type,
            order_id,
            payload,
        )
        message = {"status": "received", "result": self.result_type, "order_id": order_id}
        return Response(message, status=status.HTTP_200_OK)

    def _normalize_payload(self, data):
        if hasattr(data, "lists"):
            return {key: values[-1] if values else "" for key, values in data.lists()}
        if isinstance(data, dict):
            return {k: v for k, v in data.items()}
        return {}

    def _persist_payment(self, order_id, payload):
        if not order_id:
            return
        payment = Payment.objects.filter(order_id=order_id).order_by("-id").first()
        if not payment:
            return
        response = payment.response or {}
        callbacks = list(response.get("callbacks") or [])
        callbacks.append({"type": self.result_type, "payload": payload})
        response["callbacks"] = callbacks
        payment.response = response
        if self.result_type == "success":
            payment.success = True
            payment.error = ""
        elif self.result_type == "failure":
            payment.success = False
            payment.error = payload.get("pg_error_description") or payload.get("pg_error_message") or "freedompay_failure"
        payment.save(update_fields=["response", "success", "error"])


class FreedomPayChargeFailureView(FreedomPayChargeResultView):
    result_type = "failure"


class FreedomPayChargePostbackView(FreedomPayChargeResultView):
    result_type = "post"
