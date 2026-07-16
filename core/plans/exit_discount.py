"""API показа/клейма скидки при уходе со страницы тарифов (exit-intent).

Скидка реализуется как СНИЖЕНИЕ СУММЫ ОПЛАТЫ за тот же пакет токенов (не
бонусные кредиты) — см. plans.models.ExitDiscountOffer. Этот модуль отвечает
ТОЛЬКО за показ/клейм/статус оффера. Применение скидки к payment.amount и
сверка суммы от FreedomPay — зона ответственности payments-агента
(payments/views.py, payments/tasks.py), сюда НЕ входит.

Все эндпоинты AllowAny — работают и для гостя (identity = device_key из
заголовка X-Device-Key / тела запроса), и для авторизованного пользователя
(identity = request.user).
"""
from datetime import timedelta

from django.db import IntegrityError, transaction
from django.utils import timezone
from rest_framework import permissions, status as drf_status
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import ExitDiscountOffer

DEVICE_KEY_MAX_LEN = 64


def _resolve_identity(request) -> dict:
    """identity = {"user": User|None, "device_key": str}.

    user — request.user, если запрос авторизован. device_key — из заголовка
    X-Device-Key, а для POST-запросов ещё и из тела {"device_key": ...} как
    фолбэк (заголовок в приоритете).
    """
    user = request.user if getattr(request.user, "is_authenticated", False) else None

    device_key = (request.headers.get("X-Device-Key") or "").strip()
    if not device_key and request.method in ("POST", "PUT", "PATCH"):
        try:
            data = request.data or {}
        except Exception:  # noqa: BLE001 — битое тело не должно ронять эндпоинт
            data = {}
        device_key = str(data.get("device_key") or "").strip()

    device_key = device_key[:DEVICE_KEY_MAX_LEN]
    return {"user": user, "device_key": device_key}


def _get_percent() -> int:
    from django.conf import settings

    try:
        from adminapi.runtime import get_runtime

        return int(get_runtime("EXIT_DISCOUNT_PERCENT", settings.EXIT_DISCOUNT_PERCENT))
    except Exception:  # noqa: BLE001
        return int(settings.EXIT_DISCOUNT_PERCENT)


def _get_minutes() -> int:
    from django.conf import settings

    try:
        from adminapi.runtime import get_runtime

        return int(get_runtime("EXIT_DISCOUNT_MINUTES", settings.EXIT_DISCOUNT_MINUTES))
    except Exception:  # noqa: BLE001
        return int(settings.EXIT_DISCOUNT_MINUTES)


def _get_enabled() -> bool:
    from django.conf import settings

    try:
        from adminapi.runtime import get_runtime

        return bool(get_runtime("EXIT_DISCOUNT_ENABLED", settings.EXIT_DISCOUNT_ENABLED))
    except Exception:  # noqa: BLE001
        return bool(settings.EXIT_DISCOUNT_ENABLED)


def _find_offer(user, device_key: str):
    """Ищет существующий оффер по user, иначе по device_key.

    Гость мог позже войти в аккаунт, но у него остался тот же device_key в
    localStorage — поэтому оба варианта поиска нужны, чтобы не потерять
    скидку при регистрации. Приоритет — точное совпадение по user (если
    авторизован), иначе поиск по device_key.
    """
    offer = None
    if user is not None:
        offer = ExitDiscountOffer.objects.filter(user=user).first()
    if offer is None and device_key:
        offer = ExitDiscountOffer.objects.filter(device_key=device_key).first()
    return offer


def _get_or_create_offer(user, device_key: str):
    """Возвращает (offer, created). Не создаёт вторую строку, если уже есть
    совпадение по user ИЛИ по device_key (см. _find_offer)."""
    offer = _find_offer(user, device_key)
    if offer is not None:
        return offer, False
    try:
        with transaction.atomic():
            offer = ExitDiscountOffer.objects.create(
                user=user,
                device_key=device_key or "",
            )
        return offer, True
    except IntegrityError:
        # Гонка: параллельный запрос успел создать строку первым.
        offer = _find_offer(user, device_key)
        if offer is not None:
            return offer, False
        raise


def _active_payload(offer: "ExitDiscountOffer", now) -> dict | None:
    if not offer.claimed_at:
        return None
    if offer.redeemed_at:
        return None
    if not offer.expires_at or now > offer.expires_at:
        return None
    return {
        "percent": offer.percent,
        "expires_at": offer.expires_at,
        "seconds_left": max(0, int((offer.expires_at - now).total_seconds())),
    }


class ExitDiscountStatusView(APIView):
    """GET /api/plans/exit-discount/status/

    Ответ: {"eligible_for_popup": bool, "active": null | {percent, expires_at, seconds_left}}
    """
    permission_classes = [permissions.AllowAny]

    def get(self, request):
        identity = _resolve_identity(request)
        user, device_key = identity["user"], identity["device_key"]

        if user is None and not device_key:
            # Гость без device_key — не создаём мусорных строк, просто говорим "не положено".
            return Response({"eligible_for_popup": False, "active": None}, status=drf_status.HTTP_200_OK)

        enabled = _get_enabled()
        offer = _find_offer(user, device_key)

        if offer is None:
            return Response(
                {"eligible_for_popup": bool(enabled), "active": None},
                status=drf_status.HTTP_200_OK,
            )

        now = timezone.now()
        eligible_for_popup = bool(enabled) and offer.shown_at is None
        return Response(
            {"eligible_for_popup": eligible_for_popup, "active": _active_payload(offer, now)},
            status=drf_status.HTTP_200_OK,
        )


class ExitDiscountShowView(APIView):
    """POST /api/plans/exit-discount/show/ {"device_key"?: str}

    Идемпотентно фиксирует показ оффера (первый вызов задаёт shown_at/expires_at/percent,
    повторные вызовы НЕ продлевают таймер — возвращают уже зафиксированные значения).

    Ответ: {"percent": int, "expires_at": datetime}
    """
    permission_classes = [permissions.AllowAny]

    def post(self, request):
        identity = _resolve_identity(request)
        user, device_key = identity["user"], identity["device_key"]

        if user is None and not device_key:
            return Response(
                {"detail": "device_key обязателен для гостя"},
                status=drf_status.HTTP_400_BAD_REQUEST,
            )

        offer, _created = _get_or_create_offer(user, device_key)

        if offer.shown_at is not None:
            # Уже показывали — не сбрасываем таймер повторным триггером exit-intent.
            return Response(
                {"percent": offer.percent, "expires_at": offer.expires_at},
                status=drf_status.HTTP_200_OK,
            )

        now = timezone.now()
        percent = _get_percent()
        minutes = _get_minutes()

        offer.shown_at = now
        offer.expires_at = now + timedelta(minutes=minutes)
        offer.percent = percent
        ip = request.META.get("REMOTE_ADDR")
        if ip:
            offer.ip_address = ip
        offer.save(update_fields=["shown_at", "expires_at", "percent", "ip_address"])

        return Response(
            {"percent": offer.percent, "expires_at": offer.expires_at},
            status=drf_status.HTTP_200_OK,
        )


class ExitDiscountClaimView(APIView):
    """POST /api/plans/exit-discount/claim/

    Ответ 200: {"percent": int, "expires_at": datetime}
    Ответ 404: {"detail": "..."} — оффера нет.
    Ответ 400: {"detail": "Предложение больше не действует"} — уже claimed/dismissed или истёк.
    """
    permission_classes = [permissions.AllowAny]

    def post(self, request):
        identity = _resolve_identity(request)
        user, device_key = identity["user"], identity["device_key"]

        offer = _find_offer(user, device_key)
        if offer is None:
            return Response({"detail": "Оффер не найден"}, status=drf_status.HTTP_404_NOT_FOUND)

        now = timezone.now()
        expired = (not offer.expires_at) or now > offer.expires_at
        if offer.claimed_at is not None or offer.dismissed_at is not None or expired:
            return Response(
                {"detail": "Предложение больше не действует"},
                status=drf_status.HTTP_400_BAD_REQUEST,
            )

        offer.claimed_at = now
        offer.save(update_fields=["claimed_at"])

        return Response(
            {"percent": offer.percent, "expires_at": offer.expires_at},
            status=drf_status.HTTP_200_OK,
        )


class ExitDiscountDismissView(APIView):
    """POST /api/plans/exit-discount/dismiss/ — best-effort, всегда 200.

    Только для аналитики ("закрыл без выбора"). НЕ гейт повторного показа —
    это делает shown_at в show/.
    """
    permission_classes = [permissions.AllowAny]

    def post(self, request):
        identity = _resolve_identity(request)
        user, device_key = identity["user"], identity["device_key"]

        offer = _find_offer(user, device_key)
        if offer is not None and offer.dismissed_at is None:
            offer.dismissed_at = timezone.now()
            offer.save(update_fields=["dismissed_at"])

        return Response({"ok": True}, status=drf_status.HTTP_200_OK)
