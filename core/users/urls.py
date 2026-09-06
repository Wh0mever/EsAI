from django.urls import path, include
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView
from django.http import HttpResponseRedirect
from django.conf import settings
import json
from django.utils.http import urlencode
from rest_framework_simplejwt.tokens import RefreshToken
from botapi.views import WebAppAuthView
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
    callback page with tokens in the query string.
    """
    site_base = _frontend_base_from_request(request)

    # If user is not authenticated for some reason, just send back to signin
    if not getattr(request, "user", None) or not request.user.is_authenticated:
        return HttpResponseRedirect(f"{site_base}/auth/signin")

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

    return HttpResponseRedirect(f"{site_base}/auth/callback?{query}")


urlpatterns = [
    path('signin/', SigninApiView.as_view(), name='signin'),
    path('signup/', SignUpApiView.as_view(), name='signup'),
    path('signin/confirm/', VerifyCodeApiView.as_view(), name='confirm'),
    path("reset-password/request/", PasswordResetRequestView.as_view()),
    path("reset-password/verify/", PasswordResetVerifyView.as_view()),
    path("reset-password/complete/", PasswordResetCompleteView.as_view()),
    path('token/', TokenObtainPairView.as_view(), name='token_obtain_pair'),
    path('token/refresh/', TokenRefreshView.as_view(), name='token_refresh'),
    path('profile/', UserProfileView.as_view(), name='profile'),
    # Card management
    # path('card/bind/', BindCardView.as_view(), name='card-bind'),
    # path('card/unbind/', UnbindCardView.as_view(), name='card-unbind'),
    path('telegram-config/', TelegramConfigApiView.as_view(), name='telegram-config'),
    # Вход из Mini App: доверяем данным, подписанным токеном бота.
    path('auth/telegram/webapp/', WebAppAuthView.as_view(), name='telegram-webapp-auth'),
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
    path("accounts/", include("allauth.urls")),
    path("auth/complete/", auth_complete, name="auth-complete"),
]
