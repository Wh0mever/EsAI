from django.urls import path
from .views import (
    PlanListView, PlanRetrieveView,
    MeSubscriptionView, MeUsageView, MeAddonsView,
    ActivatePlanView, UnsubscribeView, ResumeSubscriptionView,
    TokenBalanceView, TokenPackageListView, TokenPackageValueListView,
    TokenTransactionListView, PendingPaymentView, TokenPurchaseView, CurrencyRateView,
    PublicBonusSettingsView,
)
from payments.crypto.views import CryptoInvoiceStatusView
from .exit_discount import (
    ExitDiscountStatusView, ExitDiscountShowView, ExitDiscountClaimView, ExitDiscountDismissView,
)



urlpatterns = [
    path("list/", PlanListView.as_view(), name="plan-list"),
    # Token system (pay-as-you-go). Объявлены ДО "<int:pk>/", чтобы не перехватывались.
    path("balance/", TokenBalanceView.as_view(), name="token-balance"),
    path("packages/", TokenPackageListView.as_view(), name="token-packages"),
    path("packages/value/", TokenPackageValueListView.as_view(), name="token-packages-value"),
    path("currency-rate/", CurrencyRateView.as_view(), name="currency-rate"),
    path("bonus-settings/", PublicBonusSettingsView.as_view(), name="public-bonus-settings"),
    path("transactions/", TokenTransactionListView.as_view(), name="token-transactions"),
    path("purchase/", TokenPurchaseView.as_view(), name="token-purchase"),
    # Незавершённая оплата: вернуть человека туда, откуда он ушёл.
    path("purchase/pending/", PendingPaymentView.as_view(), name="token-purchase-pending"),
    # Криптосчёт: экран оплаты опрашивает его, пока идёт перевод.
    path("purchase/crypto/<str:order_id>/", CryptoInvoiceStatusView.as_view(),
         name="token-purchase-crypto-status"),

    # Exit-intent скидка на pricing. Объявлены ДО "<int:pk>/", чтобы не перехватывались.
    path("exit-discount/status/", ExitDiscountStatusView.as_view(), name="exit-discount-status"),
    path("exit-discount/show/", ExitDiscountShowView.as_view(), name="exit-discount-show"),
    path("exit-discount/claim/", ExitDiscountClaimView.as_view(), name="exit-discount-claim"),
    path("exit-discount/dismiss/", ExitDiscountDismissView.as_view(), name="exit-discount-dismiss"),
    path("<int:pk>/", PlanRetrieveView.as_view(), name="plan-detail"),
    path("activate/<int:plan_id>/", ActivatePlanView.as_view(), name="plan-activate"),
    path("me/subscription/", MeSubscriptionView.as_view(), name="me-subscription"),
    path("me/usage/", MeUsageView.as_view(), name="me-usage"),
    path("me/addons/", MeAddonsView.as_view(), name="me-addons"),
    path("me/unsubscribe/", UnsubscribeView.as_view(), name="me-unsubscribe"),
    path("me/resume/", ResumeSubscriptionView.as_view(), name="me-resume"),
]
