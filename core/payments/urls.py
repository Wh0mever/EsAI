from django.urls import path

from .views import (
    StartBindCardAPIView,
    FreedomPayCallbackAPIView,
    RemoveCardAPIView,
    FreedomPayChargeResultView,
    FreedomPayChargeFailureView,
    FreedomPayChargePostbackView,
    StartOneTimePaymentAPIView,
    FreedomPayOneTimeSuccessView,
    FreedomPayOneTimeFailureView,
    FreedomPayOneTimePostbackView,
    StartGenerationTopupPaymentAPIView,
    FreedomPayGenerationTopupSuccessView,
    FreedomPayGenerationTopupFailureView,
    FreedomPayGenerationTopupPostbackView,
)

app_name = "payments"

urlpatterns = [
    path('card/bind/start/', StartBindCardAPIView.as_view(), name='card-bind-start'),
    path('card/bind/callback/', FreedomPayCallbackAPIView.as_view(), name='card-bind-callback'),
    path('card/remove/', RemoveCardAPIView.as_view(), name='card-remove'),
    path('card/charge/success/', FreedomPayChargeResultView.as_view(), name='freedompay-charge-success'),
    path('card/charge/failure/', FreedomPayChargeFailureView.as_view(), name='freedompay-charge-failure'),
    path('card/charge/postback/', FreedomPayChargePostbackView.as_view(), name='freedompay-charge-postback'),
    path('one-time/start/<int:plan_id>/', StartOneTimePaymentAPIView.as_view(), name='freedompay-onetime-start'),
    path('one-time/success/', FreedomPayOneTimeSuccessView.as_view(), name='freedompay-onetime-success'),
    path('one-time/failure/', FreedomPayOneTimeFailureView.as_view(), name='freedompay-onetime-failure'),
    path('one-time/postback/', FreedomPayOneTimePostbackView.as_view(), name='freedompay-onetime-postback'),
    path('topup/start/', StartGenerationTopupPaymentAPIView.as_view(), name='freedompay-topup-start'),
    path('topup/success/', FreedomPayGenerationTopupSuccessView.as_view(), name='freedompay-topup-success'),
    path('topup/failure/', FreedomPayGenerationTopupFailureView.as_view(), name='freedompay-topup-failure'),
    path('topup/postback/', FreedomPayGenerationTopupPostbackView.as_view(), name='freedompay-topup-postback'),
]
