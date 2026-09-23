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
from rest_framework.settings import api_settings
from rest_framework.throttling import SimpleRateThrottle

# Разбег часов между контейнерами и защита от повтора.
MAX_SKEW_SECONDS = 300
REPLAY_TTL_SECONDS = 600
# Лимиты, если в DEFAULT_THROTTLE_RATES не задано своих. Честному человеку
# сервисные вызовы нужны редко: вход раз в 11 часов, счёт и подтверждение при
# оплате. Общий потолок — тот же, что был в настройках (bot_service).
BOT_USER_DEFAULT_RATE = "30/min"
BOT_SERVICE_DEFAULT_RATE = "600/min"


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


# ------------------------------------------------------------ лимиты ---
#
# Раньше здесь стоял ScopedRateThrottle: он считает по request.user.pk, а у
# BotService pk=None — и все люди бота делили ОДИН счётчик на 600 запросов в
# минуту. Всплеск (рассылка, наплыв после рекламы) превращал вход, оплату Stars
# и настройки в 429 для всех сразу: вход показывал «сервер не отвечает», а
# предпроверка Stars отказывала в оплате. Теперь у каждого человека свой
# счётчик по telegram id из ПОДПИСАННОГО тела (подменить его нельзя), а общий
# остаётся высоким потолком на случай, если сам бот зациклится.


def telegram_id_of(request) -> str:
    """Telegram id человека, от имени которого бот пришёл. Пустая строка — не знаем.

    Бот кладёт его либо в telegram_id (настройки, блокировка, Stars), либо в
    telegram_user.id (вход, привязка). У «запомнить сообщение со счётом» и
    «статус счёта» его нет — такие запросы живут только под общим лимитом.
    """
    try:
        data = request.data
    except Exception:  # noqa: BLE001 — кривое тело: лимит тут не судья, решит вью
        return ""
    if not isinstance(data, dict):
        return ""
    raw = data.get("telegram_id")
    if raw in (None, ""):
        tg_user = data.get("telegram_user")
        raw = tg_user.get("id") if isinstance(tg_user, dict) else None
    raw = str(raw if raw is not None else "").strip()
    return raw if raw.isdigit() else ""


class _BotRateThrottle(SimpleRateThrottle):
    default_rate = ""

    def get_rate(self):
        # Ставку читаем на лету, а не из снимка, сделанного при импорте DRF:
        # так её можно задать в DEFAULT_THROTTLE_RATES, а без неё работает
        # дефолт, а не ImproperlyConfigured на каждом запросе.
        rates = api_settings.DEFAULT_THROTTLE_RATES or {}
        return rates.get(self.scope) or self.default_rate


class BotServiceThrottle(_BotRateThrottle):
    """Общий потолок на все сервисные запросы бота (ставка bot_service)."""

    scope = "bot_service"
    default_rate = BOT_SERVICE_DEFAULT_RATE

    def get_cache_key(self, request, view):
        return self.cache_format % {"scope": self.scope, "ident": "all"}


class BotUserThrottle(_BotRateThrottle):
    """Свой счётчик у каждого человека бота (ставка bot_service_user)."""

    scope = "bot_service_user"
    default_rate = BOT_USER_DEFAULT_RATE

    def get_cache_key(self, request, view):
        telegram_id = telegram_id_of(request)
        if not telegram_id:
            return None
        return self.cache_format % {"scope": self.scope, "ident": telegram_id}
