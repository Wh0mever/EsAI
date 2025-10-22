from django.urls import path
from .views import (
    PlanListView, PlanRetrieveView,
    MeSubscriptionView, MeUsageView, MeAddonsView,
    ChargeBySavedCardView,
)



urlpatterns = [
    path("list/", PlanListView.as_view(), name="plan-list"),
    path("<int:pk>/", PlanRetrieveView.as_view(), name="plan-detail"),
    path("me/subscription/", MeSubscriptionView.as_view(), name="me-subscription"),
    path("me/usage/", MeUsageView.as_view(), name="me-usage"),
    path("me/addons/", MeAddonsView.as_view(), name="me-addons"),
    # Test/utility endpoint to trigger безакцептный платеж by saved token
    path("me/charge/auto/", ChargeBySavedCardView.as_view(), name="me-charge-auto"),
]
