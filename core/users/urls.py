from django.urls import path, include
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView
from django.http import HttpResponseRedirect
from django.conf import settings
import json
from django.utils.http import urlencode
from rest_framework_simplejwt.tokens import RefreshToken
from .views import *


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
    if host:
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

    query = urlencode({
        "access": access,
        "refresh": refresh_str,
        "user": json.dumps(user_payload),
    })

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
    path('question/', QuestionAPIView.as_view(), name='question'),
    path('feedback/', FeedbackView.as_view(), name='feedback'),
    path('currency/', CurrencyPreferenceView.as_view(), name='currency-preference'),
    path("notifications/", NotificationListView.as_view()),
    path("notifications/<int:pk>/read/", NotificationMarkReadView.as_view()),
    path("accounts/", include("allauth.urls")),
    path("auth/complete/", auth_complete, name="auth-complete"),
]
