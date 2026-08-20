from django.urls import path

from . import blocks, views

app_name = "adminapi"

urlpatterns = [
    path("login/", views.AdminLoginAPIView.as_view(), name="login"),
    path("summary/", views.SummaryView.as_view(), name="summary"),
    path("models/", views.ModelsListView.as_view(), name="models-list"),
    path("models/<int:pk>/", views.ModelDetailView.as_view(), name="models-detail"),
    path("packages/", views.PackagesListView.as_view(), name="packages-list"),
    path("packages/<int:pk>/", views.PackageDetailView.as_view(), name="packages-detail"),
    path("users/", views.UsersListView.as_view(), name="users-list"),
    path("users/<int:pk>/credit/", views.UserCreditView.as_view(), name="users-credit"),
    path("users/<int:pk>/transactions/", views.UserTransactionsView.as_view(), name="users-transactions"),
    path("payments/", views.PaymentsListView.as_view(), name="payments-list"),
    path("blog/", views.BlogListCreateView.as_view(), name="blog-list"),
    path("blog/<int:pk>/", views.BlogDetailView.as_view(), name="blog-detail"),
    path("promo-codes/", views.PromoCodesListView.as_view(), name="promo-codes-list"),
    path("promo-codes/<int:pk>/", views.PromoCodeDetailView.as_view(), name="promo-codes-detail"),
    path("config/", views.ConfigView.as_view(), name="config"),
    path("exit-discount/stats/", views.ExitDiscountStatsView.as_view(), name="exit-discount-stats"),
    # Блокировки: домены одноразовой почты, IP, подсети, устройства.
    path("blocks/", blocks.BlocksListView.as_view(), name="blocks-list"),
    path("blocks/suspects/", blocks.BlockSuspectsView.as_view(), name="blocks-suspects"),
    path("blocks/<int:pk>/", blocks.BlockDetailView.as_view(), name="blocks-detail"),
    path("blocks/<int:pk>/accounts/", blocks.BlockAccountsView.as_view(), name="blocks-accounts"),
    path("settings/", views.SettingsView.as_view(), name="settings"),
    path("settings/test-openrouter/", views.SettingsTestOpenRouterView.as_view(), name="settings-test-openrouter"),
]
