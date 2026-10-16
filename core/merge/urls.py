from django.urls import path, re_path

from . import views

app_name = "merge"

# Идентификатор склейки — uid (32 hex): чужая неотличима от несуществующей.
_UID = r"(?P<uid>[0-9a-fA-F]{32})"

urlpatterns = [
    path("", views.ProjectsView.as_view(), name="projects"),
    path("config/", views.ConfigView.as_view(), name="config"),
    path("sources/", views.SourcesView.as_view(), name="sources"),
    # Админка: цена склейки (карточка в «Настройках» рядом с мультстудией).
    path("manage/settings/", views.ManageSettingsView.as_view(), name="manage-settings"),
    re_path(rf"^{_UID}/$", views.ProjectDetailView.as_view(), name="project"),
    re_path(rf"^{_UID}/render/$", views.RenderView.as_view(), name="render"),
    re_path(rf"^{_UID}/download/$", views.DownloadView.as_view(), name="download"),
]
