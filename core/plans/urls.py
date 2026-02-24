from django.urls import path
from .views import (
    PlanListView, PlanRetrieveView,
    MeSubscriptionView, MeUsageView, MeAddonsView,
    ActivatePlanView, UnsubscribeView, ResumeSubscriptionView, GenerationUnitPriceView,
)



urlpatterns = [
    path("list/", PlanListView.as_view(), name="plan-list"),
    path("<int:pk>/", PlanRetrieveView.as_view(), name="plan-detail"),
    path("activate/<int:plan_id>/", ActivatePlanView.as_view(), name="plan-activate"),
    path("me/subscription/", MeSubscriptionView.as_view(), name="me-subscription"),
    path("me/usage/", MeUsageView.as_view(), name="me-usage"),
    path("me/addons/", MeAddonsView.as_view(), name="me-addons"),
    path("me/unsubscribe/", UnsubscribeView.as_view(), name="me-unsubscribe"),
    path("me/resume/", ResumeSubscriptionView.as_view(), name="me-resume"),
    path("unit-prices/", GenerationUnitPriceView.as_view(), name="unit-prices"),
]
