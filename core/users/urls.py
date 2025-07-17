from django.urls import path
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView
from .views import *

urlpatterns = [
    path('signin/', SigninApiView.as_view(), name='signin'),
    path('signup/', SignUpApiView.as_view(), name='signup'),
    path('signin/confirm/', VerifyCodeApiView.as_view(), name='confirm'),
    path("reset-password/request/", PasswordResetRequestView.as_view()),
    path("reset-password/verify/", PasswordResetVerifyView.as_view()),
    path("reset-password/complete/", PasswordResetCompleteView.as_view()),
    path('token/', TokenObtainPairView.as_view(), name='token_obtain_pair'),
    path('token/refresh/', TokenRefreshView.as_view(), name='token_refresh'),
]
