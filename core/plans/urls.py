from django.urls import path
from .views import (
    PlanListView, PlanRetrieveView,
    MeSubscriptionView, MeUsageView, MeAddonsView,
    ActivatePlanView,
)



urlpatterns = [
    path("list/", PlanListView.as_view(), name="plan-list"),
    path("<int:pk>/", PlanRetrieveView.as_view(), name="plan-detail"),
    path("activate/<int:plan_id>/", ActivatePlanView.as_view(), name="plan-activate"),
    path("me/subscription/", MeSubscriptionView.as_view(), name="me-subscription"),
    path("me/usage/", MeUsageView.as_view(), name="me-usage"),
    path("me/addons/", MeAddonsView.as_view(), name="me-addons"),
]
