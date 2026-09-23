from django.urls import path, include
from rest_framework_simplejwt.views import TokenRefreshView
from django.http import HttpResponseRedirect
from django.conf import settings
import json
from django.utils.http import urlencode
from rest_framework_simplejwt.tokens import RefreshToken
from botapi.views import TelegramLinkStartView, TelegramPrefsView, WebAppAuthView
from .views import *


def _allowed_frontend_hosts() -> set:
    """Allowlist разрешённых хостов для редиректа с JWT.

    Собираем из доверенных настроек (SITE_BASE_URL, CSRF_TRUSTED_ORIGINS,
    ALLOWED_HOSTS). Хост из запроса (в т.ч. x-forwarded-host) принимается
    ТОЛЬКО если он есть в этом списке — иначе защита от host-poisoning.
    """
    from urllib.parse import urlsplit

    hosts = set()
    configured = (getattr(settings, "SITE_BASE_URL", "") or "").strip().rstrip("/")
    if configured:
        netloc = urlsplit(configured).netloc
        if netloc:
            hosts.add(netloc.lower())
    for origin in (getattr(settings, "CSRF_TRUSTED_ORIGINS", []) or []):
        netloc = urlsplit(origin).netloc
        if netloc:
            hosts.add(netloc.lower())
    for h in (getattr(settings, "ALLOWED_HOSTS", []) or []):
        h = (h or "").strip().lower().lstrip("*.")
        if h and h != "*":
            hosts.add(h)
    return hosts


def _frontend_base_from_request(request) -> str:
    configured = (getattr(settings, "SITE_BASE_URL", "") or "").strip().rstrip("/")
    raw_host = (
        request.headers.get("x-forwarded-host")
        or request.headers.get("host")
        or request.get_host()
    )
    host = (raw_host or "").split(",")[0].strip()
    proto_raw = request.headers.get("x-forwarded-proto") or ""
    proto = (proto_raw.split(",")[0].strip().lower() or ("https" if request.is_secure() else "http"))
    # Защита от host-poisoning: доверяем присланному хосту ТОЛЬКО если он
    # в allowlist. Иначе JWT-редирект мог бы уйти на домен атакующего (ATO).
    if host and host.split(":")[0].lower() in _allowed_frontend_hosts():
        return f"{proto}://{host}"
    return configured or "http://127.0.0.1:3000"


def auth_complete(request):
    """After social login completes, issue JWT and redirect to frontend.

    Expects allauth to have authenticated the session user. We create
    access/refresh tokens and redirect the browser to the frontend
    callback page with tokens in the URL fragment.
    """
    site_base = _frontend_base_from_request(request)

    # If user is not authenticated for some reason, just send back to signin
    if not getattr(request, "user", None) or not request.user.is_authenticated:
        return HttpResponseRedirect(f"{site_base}/auth/signin")

    # Сессия Django нужна только на этот переход: дальше сайт живёт на JWT, а
    # HttpOnly-куку sessionid фронт стереть не может. Раньше она жила две
    # недели, и на общем телефоне следующий человек мог войти в чужой аккаунт.
    # Пять минут хватает, чтобы повторный заход на callback (двойная загрузка
    # в webview) ещё дослал токены.
    try:
        request.session.set_expiry(300)
    except Exception:
        pass

    # Issue JWT tokens
    refresh = RefreshToken.for_user(request.user)
    access = str(refresh.access_token)
    refresh_str = str(refresh)

    # Minimal user payload for the FE cookie (match SignIn response structure)
    user_payload = {
        "id": request.user.id,
        "email": request.user.email,
        "tel": request.user.tel,
    }

    params = {
        "access": access,
        "refresh": refresh_str,
        "user": json.dumps(user_payload),
    }
    # Новый соц-пользователь (save_user поставил флаг) → показать приветственное
    # окно на фронте. Флаг одноразовый: читаем и сразу удаляем.
    try:
        from django.core.cache import cache
        wk = f"welcome_show:{request.user.pk}"
        if cache.get(wk):
            params["welcome"] = "1"
            cache.delete(wk)
    except Exception:
        pass

    query = urlencode(params)

    # Токены — во фрагменте (#), а не в строке запроса: фрагмент браузер никуда
    # не отправляет, а query с access/refresh оседал в логах nginx и Cloudflare.
    return HttpResponseRedirect(f"{site_base}/auth/callback#{query}")


def _to_signin(request, *args, **kwargs):
    """Вход на сайте — только кодом на почту, через Google или Telegram."""
    return HttpResponseRedirect(f"{_frontend_base_from_request(request)}/auth/signin")


def _social_signup_closed(request, *args, **kwargs):
    """Форма allauth «доделайте регистрацию» после соцвхода.

    В ней можно вписать любую почту, и она ложится в аккаунт без проверки —
    тот же захват чужого email, что и через accounts/email/. Соцвход у нас
    создаёт аккаунт сам (is_auto_signup_allowed), так что сюда попадают только
    сбойные случаи: возвращаем на вход с ошибкой.
    """
    try:
        request.session.pop("socialaccount_sociallogin", None)
    except Exception:
        pass
    return HttpResponseRedirect(
        f"{_frontend_base_from_request(request)}/auth/signin?error=social_login_failed")


urlpatterns = [
    # Вход по паролю закрыт целиком. Регистрация с паролем (signup/, token/ и
    # формы allauth) не проверяла владение почтой: можно было заранее завести
    # аккаунт на чужой email, дождаться, пока хозяин войдёт кодом и пополнит
    # баланс, а потом зайти туда же по своему паролю. Сайт и бот пользуются
    # только кодом на почту и соцвходом, поэтому пароли людям не нужны.
    path('signin/', SigninApiView.as_view(), name='signin'),
    path('signin/confirm/', VerifyCodeApiView.as_view(), name='confirm'),
    path('token/refresh/', TokenRefreshView.as_view(), name='token_refresh'),
    path('profile/', UserProfileView.as_view(), name='profile'),
    # Card management
    # path('card/bind/', BindCardView.as_view(), name='card-bind'),
    # path('card/unbind/', UnbindCardView.as_view(), name='card-unbind'),
    path('telegram-config/', TelegramConfigApiView.as_view(), name='telegram-config'),
    # Вход из Mini App: доверяем данным, подписанным токеном бота.
    path('auth/telegram/webapp/', WebAppAuthView.as_view(), name='telegram-webapp-auth'),
    path('telegram/link/start/', TelegramLinkStartView.as_view(), name='telegram-link-start'),
    path('telegram/prefs/', TelegramPrefsView.as_view(), name='telegram-prefs'),
    path('question/', QuestionAPIView.as_view(), name='question'),
    path('feedback/', FeedbackView.as_view(), name='feedback'),
    path('currency/', CurrencyPreferenceView.as_view(), name='currency-preference'),
    path("notifications/", NotificationListView.as_view()),
    path("notifications/<int:pk>/read/", NotificationMarkReadView.as_view()),
    # Память пользователя (как у ChatGPT/Anthropic)
    path("memory/", UserMemoryListView.as_view(), name="memory-list"),
    path("memory/clear/", UserMemoryClearView.as_view(), name="memory-clear"),
    path("memory/toggle/", UserMemoryToggleView.as_view(), name="memory-toggle"),
    path("memory/<int:pk>/", UserMemoryDeleteView.as_view(), name="memory-delete"),
    # Web Push (Push API / VAPID)
    path("push/subscribe/", WebPushSubscribeView.as_view(), name="push-subscribe"),
    path("push/vapid/", WebPushVapidKeyView.as_view(), name="push-vapid"),
    # Реферальная программа / переводы кредитов / промокоды
    path("referral/stats/", ReferralStatsView.as_view(), name="referral-stats"),
    path("transfer/", TransferView.as_view(), name="credit-transfer"),
    path("transfers/", TransferHistoryView.as_view(), name="credit-transfers"),
    path("promo/activate/", PromoActivateView.as_view(), name="promo-activate"),
    # Формы allauth с паролем подменены переходом на страницу входа сайта;
    # соцвход (accounts/google/, accounts/telegram/) работает как раньше.
    path("accounts/login/", _to_signin, name="account_login"),
    path("accounts/login/<path:rest>", _to_signin),
    path("accounts/signup/", _to_signin, name="account_signup"),
    path("accounts/password/", include([path("<path:rest>", _to_signin)])),
    # Управление почтой allauth тоже закрыто: через accounts/email/ вошедший
    # через Telegram добавлял чужой адрес без подтверждения и делал его
    # основным, а хозяин почты потом входил кодом прямо в его аккаунт.
    path("accounts/email/", _to_signin),
    path("accounts/confirm-email/", _to_signin),
    path("accounts/confirm-email/<path:rest>", _to_signin),
    path("accounts/reauthenticate/", _to_signin),
    path("accounts/3rdparty/signup/", _social_signup_closed),
    path("accounts/", include("allauth.urls")),
    path("auth/complete/", auth_complete, name="auth-complete"),
]
