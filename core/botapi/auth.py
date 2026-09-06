"""Аутентификация запросов от нашего бота.

Бот — не пользователь: он ходит в сервисные эндпоинты от своего имени, чтобы
обменять данные Telegram на токен человека. Поэтому вместо JWT здесь подпись
общим секретом: тело запроса нельзя подменить, а повторить перехваченный
запрос — нельзя дважды.
"""
import hashlib
import hmac
import time

from django.conf import settings
from django.core.cache import cache
from rest_framework import authentication, exceptions, permissions

# Разбег часов между контейнерами и защита от повтора.
MAX_SKEW_SECONDS = 300
REPLAY_TTL_SECONDS = 600


class BotService:
    """Псевдо-пользователь для DRF: запрос пришёл от нашего бота."""

    is_authenticated = True
    is_anonymous = False
    is_staff = False
    is_active = True
    pk = None

    def __str__(self) -> str:
        return "bot-service"


def sign(secret: str, ts: str, nonce: str, method: str, path: str, body: bytes) -> str:
    """Подпись запроса.

    В неё входит разовый номер: без него два одинаковых запроса в одну
    секунду (два быстрых /start подряд) дали бы одну подпись, и второй
    честный запрос защита от повтора отбила бы как атаку.
    """
    digest = hashlib.sha256(body or b"").hexdigest()
    message = f"{ts}\n{nonce}\n{method.upper()}\n{path}\n{digest}"
    return hmac.new(secret.encode("utf-8"), message.encode("utf-8"), hashlib.sha256).hexdigest()


class BotServiceAuthentication(authentication.BaseAuthentication):
    """Заголовки X-Bot-Ts, X-Bot-Nonce и X-Bot-Sig.

    Подпись считается по времени, методу, пути и хэшу тела — подменить нельзя
    ни адрес, ни содержимое. Пустой секрет в настройках означает «бот не
    подключён»: тогда сервисные эндпоинты просто закрыты.
    """

    def authenticate(self, request):
        signature = (request.META.get("HTTP_X_BOT_SIG") or "").strip().lower()
        if not signature:
            return None  # пусть решают другие классы аутентификации

        secret = (getattr(settings, "BOT_SERVICE_SECRET", "") or "").strip()
        if not secret:
            raise exceptions.AuthenticationFailed("bot_service_disabled")

        nonce = (request.META.get("HTTP_X_BOT_NONCE") or "").strip()
        if not nonce or len(nonce) > 64:
            raise exceptions.AuthenticationFailed("bad_nonce")

        raw_ts = (request.META.get("HTTP_X_BOT_TS") or "").strip()
        try:
            ts = int(raw_ts)
        except (TypeError, ValueError):
            raise exceptions.AuthenticationFailed("bad_timestamp")
        if abs(time.time() - ts) > MAX_SKEW_SECONDS:
            raise exceptions.AuthenticationFailed("stale_request")

        expected = sign(secret, raw_ts, nonce, request.method, request.path, request.body)
        if not hmac.compare_digest(expected, signature):
            raise exceptions.AuthenticationFailed("bad_signature")

        # Один и тот же подписанный запрос принимаем ровно один раз.
        if not cache.add(f"bot:nonce:{nonce}", "1", REPLAY_TTL_SECONDS):
            raise exceptions.AuthenticationFailed("replay")

        return (BotService(), None)

    def authenticate_header(self, request):
        return "Bot"


class IsBotService(permissions.BasePermission):
    message = "Только для сервисных запросов бота."

    def has_permission(self, request, view):
        return isinstance(getattr(request, "user", None), BotService)
