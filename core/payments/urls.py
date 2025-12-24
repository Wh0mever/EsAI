from django.urls import path

from .views import (
    StartBindCardAPIView,
    FreedomPayCallbackAPIView,
    RemoveCardAPIView,
    FreedomPayChargeResultView,
    FreedomPayChargeFailureView,
    FreedomPayChargePostbackView,
)

app_name = "payments"

urlpatterns = [
    path('card/bind/start/', StartBindCardAPIView.as_view(), name='card-bind-start'),
    path('card/bind/callback/', FreedomPayCallbackAPIView.as_view(), name='card-bind-callback'),
    path('card/remove/', RemoveCardAPIView.as_view(), name='card-remove'),
    path('card/charge/success/', FreedomPayChargeResultView.as_view(), name='freedompay-charge-success'),
    path('card/charge/failure/', FreedomPayChargeFailureView.as_view(), name='freedompay-charge-failure'),
    path('card/charge/postback/', FreedomPayChargePostbackView.as_view(), name='freedompay-charge-postback'),
]
