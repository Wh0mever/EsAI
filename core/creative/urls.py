"""Маршруты /api/creative/ (SPEC_B §7).

uid — <str:uid>, а не регулярка: кривой или чужой uid получает тот же JSON 404
с кодом (job_not_found, character_not_found), что и несуществующий.
Вебхук — в двух написаниях: POST не умеет идти за APPEND_SLASH.
"""
from django.urls import path

from . import views

app_name = "creative"

urlpatterns = [
    path("tools/", views.ToolsView.as_view(), name="tools"),
    path("catalog/<str:kind>/", views.CatalogView.as_view(), name="catalog"),
    path("uploads/", views.UploadsView.as_view(), name="uploads"),
    path("quote/", views.QuoteView.as_view(), name="quote"),
    path("run/", views.RunView.as_view(), name="run"),
    path("jobs/", views.JobsView.as_view(), name="jobs"),
    path("jobs/<str:uid>/", views.JobDetailView.as_view(), name="job"),
    path("jobs/<str:uid>/cancel/", views.JobCancelView.as_view(), name="job-cancel"),
    path("characters/", views.CharactersView.as_view(), name="characters"),
    path("characters/<str:uid>/hide/", views.CharacterHideView.as_view(), name="character-hide"),
    path("hook/", views.HookView.as_view(), name="hook"),
    path("hook", views.HookView.as_view(), name="hook-noslash"),
]
