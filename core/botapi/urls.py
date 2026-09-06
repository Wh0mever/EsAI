from django.urls import path

from .views import (
    BotAuthView, BotBlockedView, BotDeleteView, BotLinkConfirmView, BotPrefsView,
)
from .views_stars import (
    StarsConfirmView, StarsInvoiceMessageView, StarsInvoiceView,
    StarsPrecheckView, StarsRefundedView, StarsStatusView,
)

app_name = "botapi"

urlpatterns = [
    path("auth/telegram/", BotAuthView.as_view(), name="auth-telegram"),
    path("prefs/", BotPrefsView.as_view(), name="prefs"),
    path("blocked/", BotBlockedView.as_view(), name="blocked"),
    path("link/confirm/", BotLinkConfirmView.as_view(), name="link-confirm"),
    path("delete/", BotDeleteView.as_view(), name="delete"),
    # Оплата Telegram Stars: счёт → проверка → начисление → возврат.
    path("stars/invoice/", StarsInvoiceView.as_view(), name="stars-invoice"),
    path("stars/invoice/message/", StarsInvoiceMessageView.as_view(),
         name="stars-invoice-message"),
    path("stars/precheck/", StarsPrecheckView.as_view(), name="stars-precheck"),
    path("stars/confirm/", StarsConfirmView.as_view(), name="stars-confirm"),
    path("stars/refunded/", StarsRefundedView.as_view(), name="stars-refunded"),
    path("stars/status/", StarsStatusView.as_view(), name="stars-status"),
]
