"""Сервисные эндпоинты для бота и Mini App."""
import logging

from django.conf import settings
from rest_framework import status
from rest_framework.response import Response
from rest_framework.throttling import AnonRateThrottle, ScopedRateThrottle
from rest_framework.views import APIView
from rest_framework_simplejwt.tokens import AccessToken, RefreshToken

from .auth import BotServiceAuthentication, IsBotService
from .models import TelegramChat
from .services import TelegramBlocked, authenticate_telegram_user, mark_blocked
from .telegram import verify_webapp_init_data

logger = logging.getLogger("botapi")


def _user_payload(user) -> dict:
    from plans.tiers import user_tier

    chat = getattr(user, "telegram_chat", None)
    return {
        "id": user.pk,
        "email": user.email,
        "first_name": user.first_name or "",
        "balance_tokens": int(getattr(user, "token_balance", 0) or 0),
        "tier": user_tier(user),
        "is_paid": bool(getattr(user, "is_paid", False)),
        "is_unlimited": bool(getattr(user, "is_unlimited", False)),
        "lang": getattr(chat, "lang", "ru") if chat else "ru",
        "telegram_id": getattr(chat, "telegram_id", None) if chat else None,
    }


class BotServiceView(APIView):
    """Базовый класс: только подписанные запросы от нашего бота."""

    authentication_classes = [BotServiceAuthentication]
    permission_classes = [IsBotService]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "bot_service"


class BotAuthView(BotServiceView):
    """POST /api/bot/auth/telegram/ — обменять данные Telegram на токен человека.

    Тот же пользователь, что и при входе через Telegram на сайте: ищем по
    SocialAccount с этим telegram id, а нового заводим по тем же правилам —
    с приветственным бонусом, реферером и промокодом.
    """

    def post(self, request):
        data = request.data or {}
        tg_user = data.get("telegram_user") or {}
        if not isinstance(tg_user, dict) or not str(tg_user.get("id") or "").isdigit():
            return Response({"detail": "bad_telegram_user"}, status=status.HTTP_400_BAD_REQUEST)

        try:
            user, created = authenticate_telegram_user(
                tg_user,
                request=request,
                chat_id=data.get("chat_id"),
                source=TelegramChat.SOURCE_BOT,
                ref=str(data.get("ref") or "").strip()[:32],
                promo=str(data.get("promo") or "").strip()[:64],
            )
        except TelegramBlocked as exc:
            return Response({"detail": exc.reason}, status=status.HTTP_403_FORBIDDEN)
        except ValueError:
            return Response({"detail": "bad_telegram_user"}, status=status.HTTP_400_BAD_REQUEST)

        token = AccessToken.for_user(user)
        return Response({
            "access": str(token),
            "expires_in": int(settings.SIMPLE_JWT["ACCESS_TOKEN_LIFETIME"].total_seconds()),
            "user": _user_payload(user),
            "created": created,
        })


class BotPrefsView(BotServiceView):
    """POST /api/bot/prefs/ — настройки уведомлений и язык из бота."""

    FLAGS = ("notify_bonus", "notify_ready", "notify_topup", "notify_referral", "notify_marketing")

    def post(self, request):
        data = request.data or {}
        telegram_id = str(data.get("telegram_id") or "").strip()
        if not telegram_id.isdigit():
            return Response({"detail": "bad_telegram_id"}, status=status.HTTP_400_BAD_REQUEST)
        chat = TelegramChat.objects.filter(telegram_id=int(telegram_id)).first()
        if not chat:
            return Response({"detail": "chat_not_found"}, status=status.HTTP_404_NOT_FOUND)

        fields = []
        for flag in self.FLAGS:
            if flag in data:
                setattr(chat, flag, bool(data[flag]))
                fields.append(flag)
        lang = str(data.get("lang") or "").strip().lower()
        if lang in ("ru", "en", "kg"):
            chat.lang = lang
            fields.append("lang")
        if data.get("consent_terms"):
            from django.utils import timezone

            chat.consent_terms_at = timezone.now()
            fields.append("consent_terms_at")
        if fields:
            chat.save(update_fields=fields)
        return Response({
            "ok": True,
            "lang": chat.lang,
            **{f: getattr(chat, f) for f in self.FLAGS},
        })


class BotBlockedView(BotServiceView):
    """POST /api/bot/blocked/ — человек заблокировал бота, писать ему нельзя."""

    def post(self, request):
        telegram_id = str((request.data or {}).get("telegram_id") or "").strip()
        if not telegram_id.isdigit():
            return Response({"detail": "bad_telegram_id"}, status=status.HTTP_400_BAD_REQUEST)
        blocked = bool((request.data or {}).get("blocked", True))
        if blocked:
            mark_blocked(telegram_id)
        else:
            TelegramChat.objects.filter(telegram_id=int(telegram_id)).update(
                is_blocked=False, blocked_at=None)
        return Response({"ok": True})


class WebAppAuthView(APIView):
    """POST /api/users/auth/telegram/webapp/ — вход Mini App по initData.

    Подпись проверяем токеном бота: подделать данные о пользователе нельзя.
    Здесь отдаём и refresh — фронт умеет продлевать сессию сам.
    """

    authentication_classes = []
    permission_classes = []
    throttle_classes = [AnonRateThrottle]

    def post(self, request):
        init_data = str((request.data or {}).get("init_data") or "")
        tg_user = verify_webapp_init_data(init_data, max_age=3600)
        if not tg_user:
            return Response({"detail": "bad_init_data"}, status=status.HTTP_401_UNAUTHORIZED)

        # Один и тот же initData обменивается на токены ровно один раз.
        from django.core.cache import cache

        if not cache.add(f"tg:initdata:{tg_user.get('_hash')}", "1", 3600):
            return Response({"detail": "init_data_reused"}, status=status.HTTP_401_UNAUTHORIZED)

        try:
            user, created = authenticate_telegram_user(
                tg_user,
                request=request,
                source=TelegramChat.SOURCE_WEBAPP,
                ref=str((request.data or {}).get("ref") or "").strip()[:32],
                promo=str((request.data or {}).get("promo") or "").strip()[:64],
            )
        except TelegramBlocked as exc:
            return Response({"detail": exc.reason}, status=status.HTTP_403_FORBIDDEN)
        except ValueError:
            return Response({"detail": "bad_telegram_user"}, status=status.HTTP_400_BAD_REQUEST)

        refresh = RefreshToken.for_user(user)
        return Response({
            "access": str(refresh.access_token),
            "refresh": str(refresh),
            "user": _user_payload(user),
            "created": created,
        })
