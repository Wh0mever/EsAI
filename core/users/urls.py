from django.urls import path, include
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView
from django.http import HttpResponseRedirect
from .views import *


def auth_complete(request):
    return HttpResponseRedirect("http://127.0.0.1/users/auth/callback")


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
    path('question/', QuestionAPIView.as_view(), name='question'),
    path("notifications/", NotificationListView.as_view()),
    path("notifications/<int:pk>/read/", NotificationMarkReadView.as_view()),

    path("accounts/", include("allauth.urls")),
    path("auth/complete/", auth_complete, name="auth-complete"),
]
