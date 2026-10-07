"""Маршруты /api/vstudio/ (спецификация §8.2).

uid в адресе — <str:uid>, а не регулярка: кривой или чужой uid должен давать
тот же JSON-ответ 404 с кодом (project_not_found, take_not_found…), что и
несуществующий, а не HTML-страницу «не найдено» от Django.
«Сжать с ИИ» (assist/condense/) добавляет BE-10 отдельной строкой.
"""
from django.urls import path

from . import views, views_assist

app_name = "vstudio"

urlpatterns = [
    path("models/", views.ModelsView.as_view(), name="models"),
    path("showcase/", views.ShowcaseView.as_view(), name="showcase"),
    path("quote/", views.QuoteView.as_view(), name="quote"),
    path("projects/", views.ProjectsView.as_view(), name="projects"),
    path("projects/<str:uid>/", views.ProjectDetailView.as_view(), name="project"),
    path("projects/<str:uid>/shots/", views.ProjectShotsView.as_view(), name="project-shots"),
    path("assets/", views.AssetsView.as_view(), name="assets"),
    # from-take — раньше assets/<uid>/, иначе адрес «съест» шаблон uid.
    path("assets/from-take/", views.AssetFromTakeView.as_view(), name="asset-from-take"),
    path("assets/<str:uid>/", views.AssetDetailView.as_view(), name="asset"),
    path("shots/", views.ShotsView.as_view(), name="shots"),
    path("shots/<str:uid>/retry/", views.ShotRetryView.as_view(), name="shot-retry"),
    path("takes/", views.TakesView.as_view(), name="takes"),
    path("takes/active/", views.ActiveTakesView.as_view(), name="takes-active"),
    path("takes/<str:uid>/", views.TakeDetailView.as_view(), name="take"),
    path("takes/<str:uid>/cancel/", views.TakeCancelView.as_view(), name="take-cancel"),
    path("assist/condense/", views_assist.CondenseView.as_view(), name="assist-condense"),
]
