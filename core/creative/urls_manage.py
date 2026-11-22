"""Маршруты админки Creative Studio: /api/manage/creative/ (только сотрудники)."""
from django.urls import path

from . import views_manage

app_name = "creative_manage"

urlpatterns = [
    path("settings/", views_manage.CreativeSettingsView.as_view(), name="settings"),
    path("log/", views_manage.CreativeLogView.as_view(), name="log"),
    path("summary/", views_manage.CreativeSummaryView.as_view(), name="summary"),
]
