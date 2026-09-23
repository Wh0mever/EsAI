from django.http import HttpResponse
from django.urls import path

from .crypto.views import CryptoCurrenciesView, NowPaymentsIpnView
from .funnel import FunnelEventView
from .views import (
    StartBindCardAPIView,
    FreedomPayCallbackAPIView,
    RemoveCardAPIView,
    FreedomPayTokenPurchaseSuccessView,
    FreedomPayTokenPurchaseFailureView,
    FreedomPayTokenPurchasePostbackView,
    YooKassaWebhookView,
    FreedomPayTokenRefundPostbackView,
)

app_name = "payments"


def _legacy_callback(request, *args, **kwargs):
    """Колбэк без подписи: принимаем, чтобы FreedomPay не повторял, и не трогаем базу."""
    return HttpResponse("OK", content_type="text/plain")


urlpatterns = [
    # Шаги воронки оплаты с фронта (открыт всем: до оплаты человек ещё гость).
    path('funnel/event/', FunnelEventView.as_view(), name='funnel-event'),

    path('card/bind/start/', StartBindCardAPIView.as_view(), name='card-bind-start'),
    path('card/bind/callback/', FreedomPayCallbackAPIView.as_view(), name='card-bind-callback'),
    path('card/remove/', RemoveCardAPIView.as_view(), name='card-remove'),
    # Маршруты эпохи подписок (разовая оплата тарифа, докупка генераций) сняты:
    # сайт ими не пользуется, а их success/failure/postback принимали запросы
    # без подписи — любой мог пометить свой неоплаченный заказ «успешным» и
    # накрутить выручку в админке. Колбэки списания с привязанной карты
    # оставлены по имени (их адрес уходит в FreedomPay из FreedomPay.charge),
    # но ничего не меняют: результат списания приходит прямо в ответе API.
    path('card/charge/success/', _legacy_callback, name='freedompay-charge-success'),
    path('card/charge/failure/', _legacy_callback, name='freedompay-charge-failure'),
    path('card/charge/postback/', _legacy_callback, name='freedompay-charge-postback'),
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
