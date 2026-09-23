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
    verify_freedompay_signature,
)
from .models import Payment

from audit.services import log_event


logger = logging.getLogger()


def _log_payment_event(payment, kind: str) -> None:
    """Записать событие оплаты в централизованный журнал (audit.EventLog).

    Безопасно: log_event сам проглатывает ошибки. kind — тип callback'а
    (success/failure/post/onetime/topup/tokens), используется в meta/level.
    """
    if not payment:
        return
    success = bool(getattr(payment, "success", False))
    log_event(
        "payment",
        message=(
            f"{kind}: order={getattr(payment, 'order_id', '')} "
            f"amount={getattr(payment, 'amount', '')} "
            f"{getattr(payment, 'currency', '')} "
            f"{'OK' if success else 'FAIL'}"
        ),
        user=getattr(payment, "user", None),
        meta={
            "kind": kind,
            "order_id": getattr(payment, "order_id", ""),
            "amount": str(getattr(payment, "amount", "")),
            "currency": getattr(payment, "currency", ""),
            "success": success,
            "error": getattr(payment, "error", "") or "",
        },
        level="info" if success else "warning",
    )

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
            # Абсолютный back_link принимаем ТОЛЬКО для доверенного домена: после
            # привязки карты FreedomPay редиректит браузер на этот URL, поэтому
            # чужой домен = open-redirect (увод на фишинг). Аллоулист — общий с
            # соц-редиректом (users.adapters). Иначе — безопасный фолбэк /profile.
            from urllib.parse import urlsplit
            from users.adapters import _allowed_frontend_hosts
            host = urlsplit(back_link_input).netloc.split(":")[0].lower()
            allowed = {h.split(":")[0].lower() for h in _allowed_frontend_hosts()}
            if host and host in allowed:
                back_link = back_link_input
            else:
                back_link = request.build_absolute_uri("/profile")
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
        # Проверка подписи pg_sig: без неё любой POST с чужим pg_user_id
        # создаёт привязку карты и активирует free-план (подделка). Подделать
        # подпись без секрета FREEDOM_PAY_TOKEN невозможно.
        if not verify_freedompay_signature(request, request.data or {}, settings.FREEDOM_PAY_TOKEN):
            return Response({"status": "invalid_signature"}, status=status.HTTP_400_BAD_REQUEST)

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
        # Легаси one-time активация платного плана относится к снятой подписочной
        # модели Vokalo. Эндпоинт деактивирован — текущий флоу токенный
        # (plans/purchase). Возвращаем 410 Gone, не трогая остальную логику.
        return Response({"detail": "deprecated"}, status=status.HTTP_410_GONE)

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
        # Легаси generation-topup относится к снятой подписочной модели Vokalo.
        # Эндпоинт деактивирован — текущий флоу токенный (plans/purchase).
        # Возвращаем 410 Gone, не трогая остальную логику.
        return Response({"detail": "deprecated"}, status=status.HTTP_410_GONE)

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

        # План активируется ТОЛЬКО на подписанном server-to-server postback.
        # Браузерные success/failure — презентационные (без активации),
        # т.к. их может открыть кто угодно с pg_status=success (подделка оплаты).
        if self.result_type == "post":
            if not payment:
                return Response({"status": "ok"}, status=status.HTTP_200_OK)
            secret = (settings.FREEDOM_PAY_TOKEN or "").strip()
            if not verify_freedompay_signature(request, payload, secret):
                _log_payment_event(payment, "one_time_postback_bad_signature")
                return Response({"status": "invalid_signature"}, status=status.HTTP_400_BAD_REQUEST)

            response = payment.response or {}
            callbacks = list(response.get("callbacks") or [])
            callbacks.append({"type": "post", "payload": payload})
            response["callbacks"] = callbacks
            payment.response = response

            error_text = payload.get("pg_error_description") or payload.get("pg_error_message") or ""
            status_text = str(payload.get("pg_status") or "").lower()
            result_flag = str(payload.get("pg_result") or "").strip()
            is_ok_status = (not status_text) or (status_text in {"ok", "success"})
            is_ok_result = (not result_flag) or (result_flag == "1")
            if error_text or (not is_ok_status) or (not is_ok_result):
                payment.success = False
                payment.error = str(error_text or f"freedompay_status_error:{status_text or result_flag or 'unknown'}")
            else:
                # Сверка суммы и валюты с заказом до активации: подпись валидна,
                # но баг провайдера/подмена может прислать другую сумму.
                amount_ok = Decimal(str(payload.get("pg_amount") or "0")) == (payment.amount or 0)
                currency_ok = (payload.get("pg_currency") or "").upper() == (payment.currency or "").upper()
                if not (amount_ok and currency_ok):
                    payment.success = False
                    payment.error = "amount_mismatch"
                    payment.save(update_fields=["response", "success", "error"])
                    _log_payment_event(payment, "one_time_amount_mismatch")
                    return Response({"status": "ok"}, status=status.HTTP_200_OK)

                payment.success = True
                payment.error = ""
                try:
                    # _activate_paid_plan_for_user сама идемпотентна (already_active),
                    # повторный подписанный postback не создаёт дубль подписки.
                    if payment.user and plan_id:
                        plan = Plan.objects.get(pk=int(plan_id), is_active=True)
                        _activate_paid_plan_for_user(payment.user, plan)
                except Exception as exc:
                    payment.success = False
                    payment.error = f"plan_activate_failed:{exc}"
            payment.save(update_fields=["response", "success", "error"])
            _log_payment_event(payment, "post")
            return Response({"status": "ok"}, status=status.HTTP_200_OK)

        # Браузерный редирект — только сохранить факт обращения + редирект (без активации).
        if payment:
            response = payment.response or {}
            callbacks = list(response.get("callbacks") or [])
            callbacks.append({"type": self.result_type, "payload": payload, "presentational": True})
            response["callbacks"] = callbacks
            payment.response = response
            payment.save(update_fields=["response"])

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

        # Генерации начисляются ТОЛЬКО на подписанном server-to-server postback.
        # Браузерные success/failure — презентационные (без начисления),
        # т.к. их может открыть кто угодно с pg_status=success (подделка оплаты).
        if self.result_type == "post":
            if not payment:
                return Response({"status": "ok"}, status=status.HTTP_200_OK)
            secret = (settings.FREEDOM_PAY_TOKEN or "").strip()
            if not verify_freedompay_signature(request, payload, secret):
                _log_payment_event(payment, "topup_postback_bad_signature")
                return Response({"status": "invalid_signature"}, status=status.HTTP_400_BAD_REQUEST)

            error_text = payload.get("pg_error_description") or payload.get("pg_error_message") or ""
            status_text = str(payload.get("pg_status") or "").lower()
            result_flag = str(payload.get("pg_result") or "").strip()
            is_ok_status = (not status_text) or (status_text in {"ok", "success"})
            is_ok_result = (not result_flag) or (result_flag == "1")

            # Лочим Payment на весь разбор постбэка: два параллельных ретрая
            # сериализуются, и флаг topup_applied гарантирует ровно одно начисление.
            with transaction.atomic():
                payment = Payment.objects.select_for_update().get(pk=payment.pk)
                response = payment.response or {}
                callbacks = list(response.get("callbacks") or [])
                callbacks.append({"type": "post", "payload": payload})
                response["callbacks"] = callbacks
                payment.response = response

                if error_text or (not is_ok_status) or (not is_ok_result):
                    payment.success = False
                    payment.error = str(error_text or f"freedompay_status_error:{status_text or result_flag or 'unknown'}")
                else:
                    # Сверка суммы и валюты с заказом до начисления: подпись валидна,
                    # но баг провайдера/подмена может прислать другую сумму.
                    amount_ok = Decimal(str(payload.get("pg_amount") or "0")) == (payment.amount or 0)
                    currency_ok = (payload.get("pg_currency") or "").upper() == (payment.currency or "").upper()
                    if not (amount_ok and currency_ok):
                        payment.success = False
                        payment.error = "amount_mismatch"
                        payment.save(update_fields=["response", "success", "error"])
                        _log_payment_event(payment, "topup_amount_mismatch")
                        return Response({"status": "ok"}, status=status.HTTP_200_OK)

                    payment.success = True
                    payment.error = ""
                    try:
                        # Идемпотентность активации: флаг topup_applied не даст начислить дважды.
                        if not bool(response.get("topup_applied")):
                            topup_init = (payment.request or {}).get("topup_init") or {}
                            if payment.user and topup_init:
                                _apply_generation_topup_to_user(payment.user, topup_init)
                                response["topup_applied"] = True
                                payment.response = response
                    except Exception as exc:
                        payment.success = False
                        payment.error = f"generation_topup_apply_failed:{exc}"
                payment.save(update_fields=["response", "success", "error"])
            _log_payment_event(payment, "post")
            return Response({"status": "ok"}, status=status.HTTP_200_OK)

        # Браузерный редирект — только сохранить факт обращения + редирект (без начисления).
        if payment:
            response = payment.response or {}
            callbacks = list(response.get("callbacks") or [])
            callbacks.append({"type": self.result_type, "payload": payload, "presentational": True})
            response["callbacks"] = callbacks
            payment.response = response
            payment.save(update_fields=["response"])

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


def _mark_exit_discount_redeemed(payment: "Payment") -> None:
    """Пометить ExitDiscountOffer.redeemed_at, если exit-intent скидка была
    применена к оплате ЭТОГО платежа (снижение суммы, а не бонусные кредиты).

    Ищет оффер по applied_to_payment=payment, при промахе — по offer_id из
    payment.request["exit_discount"] (см. точку старта покупки). Идемпотентно
    (redeemed_at ставится один раз). Ничего не делает, если ключ exit_discount
    в request отсутствует (обычная покупка без скидки).

    ВАЖНО: вызывающий код обязан оборачивать вызов в try/except — сбой этой
    пометки НЕ должен ронять/откатывать уже совершённое начисление кредитов
    покупателю (та же дисциплина, что реферальная выплата в payments/tasks.py).
    """
    exit_discount = (payment.request or {}).get("exit_discount") or {}
    if not exit_discount:
        return

    from plans.models import ExitDiscountOffer

    with transaction.atomic():
        offer = (
            ExitDiscountOffer.objects.select_for_update()
            .filter(applied_to_payment_id=payment.pk)
            .first()
        )
        if not offer:
            offer_id = exit_discount.get("offer_id")
            if offer_id:
                offer = (
                    ExitDiscountOffer.objects.select_for_update()
                    .filter(pk=offer_id)
                    .first()
                )
        if not offer:
            return
        # Заплачено со скидкой, которую этот платёж уже не держал: её погасила
        # другая оплата или она переехала на другой платёж. Кредиты человек
        # получает (деньги уже списаны), но такой случай нужно разобрать руками.
        foreign = offer.applied_to_payment_id != payment.pk and (
            offer.applied_to_payment_id is not None or offer.redeemed_at is not None)
        if foreign:
            logger.warning(
                "exit_discount: повторное использование скидки offer=%s order=%s applied=%s redeemed=%s",
                offer.pk, payment.order_id, offer.applied_to_payment_id, offer.redeemed_at,
            )
            log_event(
                "payment",
                message=(f"exit_discount_reused: order={payment.order_id} offer={offer.pk} "
                         f"applied_to={offer.applied_to_payment_id} — проверить вручную"),
                user=payment.user,
                meta={"order_id": payment.order_id, "offer_id": offer.pk,
                      "applied_to_payment_id": offer.applied_to_payment_id,
                      "needs_review": True},
                level="warning",
            )
        if not offer.redeemed_at:
            offer.redeemed_at = timezone.now()
            offer.save(update_fields=["redeemed_at"])


def _mark_user_paid(user: User) -> None:
    """Пометить пользователя платным при ПЕРВОЙ успешной оплате (ТЗ 2).

    Идемпотентно: first_paid_at проставляется один раз и не перезаписывается.
    Вызывается внутри той же атомарной транзакции, что и начисление токенов.
    """
    if not user:
        return
    update_fields = []
    if not bool(getattr(user, "is_paid", False)):
        user.is_paid = True
        update_fields.append("is_paid")
    if getattr(user, "first_paid_at", None) is None:
        user.first_paid_at = timezone.now()
        update_fields.append("first_paid_at")
    if update_fields:
        user.save(update_fields=update_fields)


def _notify_balance_topup(user: User, credited: int, *, notify_telegram: bool = True) -> None:
    """Уведомить пользователя об успешном пополнении баланса (ТЗ 2).

    1) in-app Notification (модель users.Notification, доставка через add_recipients);
    2) email через общий механизм рассылки (mails.sender.send_template_email).

    Email завёрнут в try/except, чтобы сбой почты НЕ ломал начисление токенов.
    """
    title = "Баланс пополнен"
    body = f"Ваш баланс пополнен на {int(credited)} токенов. Спасибо за покупку!"

    # Сообщение в Telegram: человеку, который пришёл из бота, письмо на
    # почту-заглушку @social.esai.local не дойдёт никогда.
    if notify_telegram:
        try:
            from botapi.tasks import notify

            notify(
                user, "topup",
                f"✅ <b>Баланс пополнен</b>\n+{int(credited)} кредитов уже на счету.",
            )
        except Exception:
            logger.exception("telegram topup notify failed user=%s", getattr(user, "id", None))

    # in-app уведомление
    try:
        from users.models import Notification
        notification = Notification.objects.create(title=title, body=body)
        notification.add_recipients([user])
    except Exception:
        logger.exception("token_topup_notification_failed user=%s", getattr(user, "id", None))

    # email — best-effort, не должен ронять транзакцию начисления
    email = (getattr(user, "email", "") or "").strip()
    # Почта-заглушка аккаунта из Telegram: писем на неё не существует.
    if not email or email.lower().endswith("@social.esai.local"):
        return
    try:
        from mails.sender import send_template_email
        send_template_email(
            subject="EsAI — баланс пополнен",
            raw_html=f"<p>{body}</p>",
            raw_text=body,
            recipient_list=[email],
        )
    except Exception:
        logger.exception("token_topup_email_failed user=%s", getattr(user, "id", None))


def _apply_purchase_credit(payment: "Payment", order_id: str, total: int,
                           *, meta_extra: dict | None = None,
                           notify_telegram: bool = True) -> None:
    """Начислить кредиты за оплаченный заказ и сделать всё, что идёт следом.

    Вынесено из _credit_token_package_for_payment, чтобы крипта начисляла тем
    же кодом. Отличие крипты одно: она может звать это несколько раз за один
    заказ (недоплата, потом доплата), передавая ДЕЛЬТУ и подробности в
    meta_extra. Проверку «не начисляли ли уже» делает вызывающий — здесь
    только само начисление.
    """
    from plans.wallet import credit_tokens
    from .referral import pay_referral_share

    info = (payment.request or {}).get("token_purchase") or {}
    meta = {
        "order_id": order_id,
        "package_id": info.get("package_id"),
        "tokens": int(info.get("tokens") or 0),
        "bonus_tokens": int(info.get("bonus_tokens") or 0),
    }
    if meta_extra:
        meta.update(meta_extra)

    credit_tokens(payment.user, total, "purchase", meta=meta)

    # Exit-discount: пометить redeemed_at, если скидка была применена к этому
    # платежу. Best-effort — сбой НЕ должен ронять уже совершённое начисление.
    try:
        _mark_exit_discount_redeemed(payment)
    except Exception:
        logger.exception("exit_discount_redeem_mark_failed order=%s", order_id)

    # Первая оплата → пользователь становится платным (ТЗ 2). Идемпотентно.
    _mark_user_paid(payment.user)

    # Уведомление пользователю об успешном пополнении (in-app + email).
    # Оплата в боте подтверждается самим ботом: второе сообщение о том же
    # пополнении выглядело бы как двойное начисление.
    _notify_balance_topup(payment.user, total,
                          notify_telegram=notify_telegram and payment.provider != "telegram_stars")

    # Доля пригласившего. Раньше платилась только на пути сверки, поэтому
    # покупки, подтверждённые постбэком, реферера обходили стороной. Здесь
    # она достаётся всем провайдерам сразу; идемпотентна по order_id.
    pay_referral_share(payment.user, order_id, total,
                       idem_suffix=str((meta_extra or {}).get("idem") or ""))


def _credit_token_package_for_payment(payment: "Payment", order_id: str) -> None:
    """Начислить токены за оплаченный пакет. Идемпотентно по order_id.

    Защита от двойного начисления:
    1) флаг response["token_purchase_applied"];
    2) проверка существующей TokenTransaction(reason="purchase") с этим order_id в meta.

    После успешного начисления (в той же атомарной транзакции) помечает юзера
    платным (ТЗ 2) и отправляет уведомление/email о пополнении.
    """
    from plans.models import TokenPackage, TokenTransaction
    from plans.wallet import credit_tokens

    response = payment.response or {}
    if bool(response.get("token_purchase_applied")):
        return

    info = (payment.request or {}).get("token_purchase") or {}
    package_id = info.get("package_id")
    if not payment.user or not package_id:
        raise ValueError("token_purchase_info_missing")

    # Idempotency: did we already credit for this order?
    already = TokenTransaction.objects.filter(
        user=payment.user,
        reason="purchase",
        meta__order_id=order_id,
    ).exists()
    if already:
        response["token_purchase_applied"] = True
        payment.response = response
        return

    # Начисляем по снапшоту цены/объёма, зафиксированному в момент ПОКУПКИ
    # (info.tokens/bonus_tokens — то, что пользователь видел и оплатил), а не
    # по текущей конфигурации TokenPackage: если админ поменяет объём пакета
    # между инициацией оплаты и её подтверждением (постбэк может не прийти
    # вовсе — основной путь начисления — периодический reconcile), пользователь
    # должен получить ровно то, что было продано за уплаченную сумму.
    snapshot_total = int(info.get("tokens") or 0) + int(info.get("bonus_tokens") or 0)
    if snapshot_total > 0:
        total = snapshot_total
    else:
        # Старые платежи без снапшота (до введения этого поля) — fallback
        # на текущий TokenPackage, если он ещё существует.
        try:
            package = TokenPackage.objects.get(pk=int(package_id))
            total = int(package.tokens or 0) + int(package.bonus_tokens or 0)
        except (TokenPackage.DoesNotExist, TypeError, ValueError):
            total = 0

    if total <= 0:
        raise ValueError("token_package_zero_amount")

    _apply_purchase_credit(payment, order_id, total)

    response["token_purchase_applied"] = True
    payment.response = response


def _is_refund_signal(payload: dict) -> bool:
    """Определить, что postback — это ВОЗВРАТ/реверс/chargeback (а не оплата).

    FreedomPay может присылать реверс с разным набором полей у разных мерчантов,
    поэтому проверяем несколько признаков. Нормальный успешный платёж сюда не
    попадает (pg_status = ok/success/пусто).
    """
    status_text = str(payload.get("pg_status") or "").lower()
    # ВНИМАНИЕ: canceled/cancelled здесь намеренно НЕТ — отмена платежа это не
    # возврат уже начисленного, иначе обычная отмена ошибочно изъяла бы токены.
    if status_text in {
        "refunded", "refund", "revoke", "revoked",
        "reversed", "reversal", "chargeback",
    }:
        return True
    if str(payload.get("pg_refund") or "").strip().lower() in {"1", "true", "yes"}:
        return True
    if payload.get("pg_refund_payment_id") or payload.get("pg_revoked_payment_id"):
        return True
    return False


def _clawback_token_package_for_payment(payment: "Payment", order_id: str, payload: dict) -> None:
    """Изъять начисленные за заказ кредиты при возврате/chargeback. Идемпотентно.

    Защита от двойного клавбэка: флаг response['token_purchase_clawed_back'].
    Изымаем столько, сколько было начислено purchase-транзакцией (или сколько
    осталось — баланс не уходит ниже 0). Пишем audit-событие.
    """
    from plans.models import TokenTransaction
    from plans.wallet import clawback_tokens

    response = payment.response or {}
    if bool(response.get("token_purchase_clawed_back")):
        return
    if not payment.user:
        return

    purchase = (
        TokenTransaction.objects
        .filter(user=payment.user, reason="purchase", meta__order_id=order_id)
        .order_by("created_at")
        .first()
    )
    if not purchase:
        # Начисления по заказу не было (или ещё не применялось) — клавбэк не нужен.
        response["token_purchase_clawed_back"] = True
        payment.response = response
        return

    credited = int(purchase.delta or 0)  # delta положительная при начислении
    debited = clawback_tokens(
        payment.user,
        credited,
        "refund",
        meta={"kind": "chargeback_clawback", "order_id": order_id, "credited": credited},
    )
    response["token_purchase_clawed_back"] = True
    response["clawback_debited"] = debited
    payment.response = response

    # Доля пригласившего с этой покупки тоже возвращается.
    from payments.referral import clawback_referral_share

    referral_taken = clawback_referral_share(order_id)
    if referral_taken:
        response["referral_clawback"] = referral_taken

    # Платный тариф держится на оплатах. Если других успешных, не возвращённых
    # покупок нет — человек снова на бесплатном (премиум-модели, лимиты).
    try:
        # Флаг возврата лежит в JSON: exclude() по ключу выкинул бы и оплаты
        # без этого ключа (NULL), поэтому проверяем в Python — оплат у человека мало.
        others = [p for p in Payment.objects.filter(user=payment.user, success=True)
                  .exclude(pk=payment.pk).only("response")
                  if not (p.response or {}).get("token_purchase_clawed_back")]
        # Одного success мало: крипто-счёт с недоплатой остаётся success=False,
        # хотя кредиты по нему начислены. Смотрим и в леджер покупок — без
        # этого заказа и без уже возвращённых.
        clawed = {p.order_id for p in Payment.objects.filter(user=payment.user)
                  .only("order_id", "response")
                  if (p.response or {}).get("token_purchase_clawed_back")}
        clawed.add(order_id)
        ledger_paid = any(
            (meta or {}).get("order_id") not in clawed
            for meta in TokenTransaction.objects.filter(
                user=payment.user, reason="purchase", delta__gt=0).values_list("meta", flat=True)
        )
        if getattr(payment.user, "is_paid", False) and not others and not ledger_paid:
            payment.user.is_paid = False
            payment.user.save(update_fields=["is_paid"])
            response["paid_tier_revoked"] = True
    except Exception:
        logger.exception("clawback: не удалось пересчитать тариф order=%s", order_id)
    try:
        log_event(
            "payment",
            message=f"chargeback_clawback: order={order_id} credited={credited} debited={debited}",
            user=payment.user,
            meta={"order_id": order_id, "credited": credited, "debited": debited},
            level="warning",
        )
    except Exception:
        pass


class FreedomPayTokenPurchaseResultBaseView(APIView):
    """Обработка success/failure/postback оплаты пакета токенов.

    На успешный платёж начисляет токены через credit_tokens (идемпотентно).
    Старая подписочная/topup-ветка не затрагивается.
    """

    authentication_classes = []
    permission_classes = []
    result_type = "success"

    def get(self, request, *args, **kwargs):
        return self._handle(request, request.query_params)

    def post(self, request, *args, **kwargs):
        return self._handle(request, request.data)

    def _handle(self, request, payload_source):
        from django.conf import settings as dj_settings
        from .freedompay import verify_freedompay_signature

        payload = _normalize_payload(payload_source)
        order_id = payload.get("pg_order_id") or payload.get("order_id")
        payment = Payment.objects.filter(order_id=order_id).order_by("-id").first() if order_id else None

        # Токены начисляются ТОЛЬКО на подписанном server-to-server postback.
        # Браузерные success/failure — презентационные (никаких начислений),
        # т.к. их может открыть кто угодно с pg_status=success (подделка оплаты).
        if self.result_type == "post":
            if not payment:
                return Response({"status": "ok"}, status=status.HTTP_200_OK)
            secret = (dj_settings.FREEDOM_PAY_TOKEN or "").strip()
            if not verify_freedompay_signature(request, payload, secret):
                _log_payment_event(payment, "tokens_postback_bad_signature")
                return Response({"status": "invalid_signature"}, status=status.HTTP_400_BAD_REQUEST)

            # Возврат/chargeback: изъять начисленные кредиты (идемпотентно), НЕ начислять.
            if _is_refund_signal(payload):
                try:
                    # Лочим Payment перед клавбэком: параллельные реверсы
                    # сериализуются, флаг token_purchase_clawed_back не даст изъять дважды.
                    with transaction.atomic():
                        payment = Payment.objects.select_for_update().get(pk=payment.pk)
                        response = payment.response or {}
                        callbacks = list(response.get("callbacks") or [])
                        callbacks.append({"type": "post", "payload": payload})
                        response["callbacks"] = callbacks
                        payment.response = response
                        _clawback_token_package_for_payment(payment, order_id, payload)
                        payment.success = False
                        if not payment.error:
                            payment.error = "refunded"
                        payment.save(update_fields=["response", "success", "error"])
                except Exception as exc:
                    payment.error = f"token_clawback_failed:{exc}"
                    payment.save(update_fields=["response", "success", "error"])
                _log_payment_event(payment, "tokens_refund")
                return Response({"status": "ok"}, status=status.HTTP_200_OK)

            error_text = payload.get("pg_error_description") or payload.get("pg_error_message") or ""
            status_text = str(payload.get("pg_status") or "").lower()
            result_flag = str(payload.get("pg_result") or "").strip()
            is_ok = (status_text in {"ok", "success"} or not status_text) and (result_flag in {"1", ""})

            # Лочим Payment на весь разбор постбэка: два параллельных ретрая
            # постбэка сериализуются, и идемпотентность (флаг token_purchase_applied
            # + существующая TokenTransaction) гарантирует ровно одно начисление.
            with transaction.atomic():
                payment = Payment.objects.select_for_update().get(pk=payment.pk)
                response = payment.response or {}
                callbacks = list(response.get("callbacks") or [])
                callbacks.append({"type": "post", "payload": payload})
                response["callbacks"] = callbacks
                payment.response = response

                if error_text or not is_ok:
                    payment.success = False
                    payment.error = str(error_text or f"freedompay_status:{status_text or result_flag or 'unknown'}")
                else:
                    # Сверка суммы и валюты с заказом до начисления: подпись валидна,
                    # но баг провайдера/подмена может прислать другую сумму.
                    amount_ok = Decimal(str(payload.get("pg_amount") or "0")) == (payment.amount or 0)
                    currency_ok = (payload.get("pg_currency") or "").upper() == (payment.currency or "").upper()
                    if not (amount_ok and currency_ok):
                        payment.success = False
                        payment.error = "amount_mismatch"
                        payment.save(update_fields=["response", "success", "error"])
                        _log_payment_event(payment, "tokens_amount_mismatch")
                        return Response({"status": "ok"}, status=status.HTTP_200_OK)

                    payment.success = True
                    payment.error = ""
                    try:
                        _credit_token_package_for_payment(payment, order_id)
                    except Exception as exc:
                        payment.success = False
                        payment.error = f"token_purchase_apply_failed:{exc}"
                payment.save(update_fields=["response", "success", "error"])
            _log_payment_event(payment, "tokens_postback")
            return Response({"status": "ok"}, status=status.HTTP_200_OK)

        # Браузерный редирект — только сохранить факт обращения + редирект.
        if payment:
            response = payment.response or {}
            callbacks = list(response.get("callbacks") or [])
            callbacks.append({"type": self.result_type, "payload": payload, "presentational": True})
            response["callbacks"] = callbacks
            payment.response = response
            payment.save(update_fields=["response"])

        # Куда возвращать, решено при создании платежа (студия платит прямо из
        # проекта). Путь там уже проверен, здесь только читаем.
        back = "/profile"
        if payment:
            back = ((payment.request or {}).get("return_to") or "/profile")

        if self.result_type == "success":
            # Постбэк FreedomPay ненадёжен → мгновенно сверяем статус и начисляем
            # (идемпотентно), не блокируя редирект. Плюс beat-задача подстрахует.
            try:
                from .tasks import reconcile_pending_token_payments
                reconcile_pending_token_payments.delay()
            except Exception:
                pass
            return HttpResponseRedirect(
                _frontend_absolute_url(request, back, {"payment": "tokens_success"})
            )
        return HttpResponseRedirect(
            _frontend_absolute_url(request, back, {"payment": "tokens_failed"})
        )


class FreedomPayTokenPurchaseSuccessView(FreedomPayTokenPurchaseResultBaseView):
    result_type = "success"


class FreedomPayTokenPurchaseFailureView(FreedomPayTokenPurchaseResultBaseView):
    result_type = "failure"


class FreedomPayTokenPurchasePostbackView(FreedomPayTokenPurchaseResultBaseView):
    result_type = "post"


class FreedomPayTokenRefundPostbackView(APIView):
    """Выделенный signed-эндпоинт возврата/chargeback пакета токенов.

    Страховка на случай, если FreedomPay шлёт реверс на отдельный URL (а не на
    основной postback). Изымает ранее начисленные кредиты (идемпотентно).
    Требует валидную подпись pg_sig — подделать без секрета нельзя.
    """

    authentication_classes = []
    permission_classes = []

    def get(self, request, *args, **kwargs):
        return self._handle(request, request.query_params)

    def post(self, request, *args, **kwargs):
        return self._handle(request, request.data)

    def _handle(self, request, payload_source):
        from django.conf import settings as dj_settings
        from .freedompay import verify_freedompay_signature

        payload = _normalize_payload(payload_source)
        order_id = payload.get("pg_order_id") or payload.get("order_id")
        payment = Payment.objects.filter(order_id=order_id).order_by("-id").first() if order_id else None
        if not payment:
            return Response({"status": "ok"}, status=status.HTTP_200_OK)

        secret = (dj_settings.FREEDOM_PAY_TOKEN or "").strip()
        if not verify_freedompay_signature(request, payload, secret):
            _log_payment_event(payment, "tokens_refund_bad_signature")
            return Response({"status": "invalid_signature"}, status=status.HTTP_400_BAD_REQUEST)

        try:
            # Лочим Payment перед клавбэком: параллельные реверсы сериализуются,
            # флаг token_purchase_clawed_back не даст изъять кредиты дважды.
            with transaction.atomic():
                payment = Payment.objects.select_for_update().get(pk=payment.pk)
                response = payment.response or {}
                callbacks = list(response.get("callbacks") or [])
                callbacks.append({"type": "refund", "payload": payload})
                response["callbacks"] = callbacks
                payment.response = response
                _clawback_token_package_for_payment(payment, order_id, payload)
                payment.success = False
                if not payment.error:
                    payment.error = "refunded"
                payment.save(update_fields=["response", "success", "error"])
        except Exception as exc:
            payment.error = f"token_clawback_failed:{exc}"
            payment.save(update_fields=["response", "success", "error"])
        _log_payment_event(payment, "tokens_refund")
        return Response({"status": "ok"}, status=status.HTTP_200_OK)


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
        _log_payment_event(payment, f"charge_{self.result_type}")


class FreedomPayChargeFailureView(FreedomPayChargeResultView):
    result_type = "failure"


class FreedomPayChargePostbackView(FreedomPayChargeResultView):
    result_type = "post"


class YooKassaWebhookView(APIView):
    """POST /api/payments/yookassa/webhook/ — уведомление ЮKassa об оплате.

    Тело уведомления НЕ является доверенным: подписи у ЮKassa нет, поэтому
    из него берём ТОЛЬКО идентификатор платежа, а статус и сумму читаем
    перезапросом в API по HTTP Basic. Прислать нам «оплачено» и получить
    кредиты бесплатно так нельзя.

    Начисление идёт через тот же _credit_token_package_for_payment, что и у
    FreedomPay: идемпотентность по order_id гарантирует ровно одно
    зачисление, сколько бы ретраев ни прислала ЮKassa.
    """

    authentication_classes = []
    permission_classes = []

    def post(self, request, *args, **kwargs):
        from . import yookassa as yk

        body = request.data if isinstance(request.data, dict) else {}
        obj = (body.get("object") or {}) if isinstance(body.get("object"), dict) else {}
        yk_payment_id = str(obj.get("id") or "").strip()
        if not yk_payment_id:
            return Response({"status": "ignored"}, status=status.HTTP_200_OK)

        # Единственный доверенный источник — ответ API ЮKassa.
        try:
            fresh = yk.fetch_payment(yk_payment_id)
        except Exception as exc:
            logger.warning("yookassa webhook: fetch failed id=%s err=%s", yk_payment_id, exc)
            # Не 200: ЮKassa повторяет уведомление, только если ответ не 200.
            # Раньше здесь был 200 «повторит сама» — и не повторяла, а один
            # сбой связи оставлял оплаченный рублёвый заказ без кредитов.
            return Response({"status": "retry_later"}, status=status.HTTP_503_SERVICE_UNAVAILABLE)

        order_id = str(((fresh.get("metadata") or {}).get("order_id") or "")).strip()
        payment = Payment.objects.filter(order_id=order_id).order_by("-id").first() if order_id else None
        if not payment:
            logger.warning("yookassa webhook: заказ не найден order_id=%s", order_id)
            return Response({"status": "ok"}, status=status.HTTP_200_OK)

        apply_yookassa_state(payment, fresh, source="yookassa_webhook")
        return Response({"status": "ok"}, status=status.HTTP_200_OK)


def apply_yookassa_state(payment, fresh: dict, *, source: str) -> str:
    """Применить ответ API ЮKassa к нашему заказу. Идемпотентно.

    Общий путь для вебхука и для сверки (payments.tasks.reconcile_yookassa_payments).
    Возвращает "credited" / "not_paid" / "pending" / "mismatch" / "failed".
    """
    order_id = payment.order_id
    status_text = str(fresh.get("status") or "").lower()
    paid = bool(fresh.get("paid")) and status_text == "succeeded"
    if not paid and status_text in ("pending", "waiting_for_capture", ""):
        # Человек ещё на странице оплаты — рано что-то решать.
        return "pending"

    with transaction.atomic():
        payment = Payment.objects.select_for_update().get(pk=payment.pk)
        response = payment.response or {}
        callbacks = list(response.get("callbacks") or [])
        callbacks.append({"type": source, "payload": fresh})
        response["callbacks"] = callbacks
        payment.response = response

        if not paid:
            payment.success = False
            payment.error = f"yookassa_status:{fresh.get('status') or 'unknown'}"
            payment.save(update_fields=["response", "success", "error"])
            _log_payment_event(payment, "yookassa_not_paid")
            return "not_paid"

        # Сверка суммы и валюты с нашим заказом до начисления.
        amt = (fresh.get("amount") or {})
        try:
            amount_ok = Decimal(str(amt.get("value") or "0")) == (payment.amount or 0)
        except Exception:
            amount_ok = False
        currency_ok = str(amt.get("currency") or "").upper() == (payment.currency or "").upper()
        if not (amount_ok and currency_ok):
            payment.success = False
            payment.error = "amount_mismatch"
            payment.save(update_fields=["response", "success", "error"])
            _log_payment_event(payment, "yookassa_amount_mismatch")
            return "mismatch"

        payment.success = True
        payment.error = ""
        result = "credited"
        try:
            _credit_token_package_for_payment(payment, order_id)
        except Exception as exc:
            payment.success = False
            payment.error = f"token_purchase_apply_failed:{exc}"
            result = "failed"
        payment.save(update_fields=["response", "success", "error"])

    _log_payment_event(payment, source)
    return result
