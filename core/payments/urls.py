from django.urls import path

from .crypto.views import CryptoCurrenciesView, NowPaymentsIpnView
from .funnel import FunnelEventView
from .views import (
    StartBindCardAPIView,
    FreedomPayCallbackAPIView,
    RemoveCardAPIView,
    FreedomPayChargeResultView,
    FreedomPayChargeFailureView,
    FreedomPayChargePostbackView,
    StartOneTimePaymentAPIView,
    GenerationTopupPricingAPIView,
    FreedomPayOneTimeSuccessView,
    FreedomPayOneTimeFailureView,
    FreedomPayOneTimePostbackView,
    StartGenerationTopupPaymentAPIView,
    FreedomPayGenerationTopupSuccessView,
    FreedomPayGenerationTopupFailureView,
    FreedomPayGenerationTopupPostbackView,
    FreedomPayTokenPurchaseSuccessView,
    FreedomPayTokenPurchaseFailureView,
    FreedomPayTokenPurchasePostbackView,
    YooKassaWebhookView,
    FreedomPayTokenRefundPostbackView,
)

app_name = "payments"

urlpatterns = [
    # Шаги воронки оплаты с фронта (открыт всем: до оплаты человек ещё гость).
    path('funnel/event/', FunnelEventView.as_view(), name='funnel-event'),

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
    path('topup/pricing/', GenerationTopupPricingAPIView.as_view(), name='freedompay-topup-pricing'),
    path('topup/start/', StartGenerationTopupPaymentAPIView.as_view(), name='freedompay-topup-start'),
    path('topup/success/', FreedomPayGenerationTopupSuccessView.as_view(), name='freedompay-topup-success'),
    path('topup/failure/', FreedomPayGenerationTopupFailureView.as_view(), name='freedompay-topup-failure'),
    path('topup/postback/', FreedomPayGenerationTopupPostbackView.as_view(), name='freedompay-topup-postback'),
    # Token package purchase callbacks (pay-as-you-go)
    path('tokens/success/', FreedomPayTokenPurchaseSuccessView.as_view(), name='freedompay-tokens-success'),
    path('tokens/failure/', FreedomPayTokenPurchaseFailureView.as_view(), name='freedompay-tokens-failure'),
    path('tokens/postback/', FreedomPayTokenPurchasePostbackView.as_view(), name='freedompay-tokens-postback'),
    # ЮKassa: уведомление об оплате (рублёвые платежи). Подписи у ЮKassa нет,
    # поэтому вью перезапрашивает статус платежа в их API — см. YooKassaWebhookView.
    path('yookassa/webhook/', YooKassaWebhookView.as_view(), name='yookassa-webhook'),
    path('tokens/refund/', FreedomPayTokenRefundPostbackView.as_view(), name='freedompay-tokens-refund'),

    # Крипта. Список монет открыт всем (витрина показывает способ оплаты и
    # гостю). Уведомление процессора приходит без авторизации — его
    # подлинность проверяется подписью, а суммы всё равно перезапрашиваются.
    path('crypto/currencies/', CryptoCurrenciesView.as_view(), name='crypto-currencies'),
    path('crypto/nowpayments/ipn/', NowPaymentsIpnView.as_view(), name='crypto-nowpayments-ipn'),
]
