from django.urls import path, re_path

from . import views, views_audio

app_name = "merge"

# Идентификатор склейки — uid (32 hex): чужая неотличима от несуществующей.
_UID = r"(?P<uid>[0-9a-fA-F]{32})"

urlpatterns = [
    path("", views.ProjectsView.as_view(), name="projects"),
    path("config/", views.ConfigView.as_view(), name="config"),
    path("sources/", views.SourcesView.as_view(), name="sources"),
    # Свои видео: список и загрузка; удаление по uid.
    path("uploads/", views.UploadsView.as_view(), name="uploads"),
    re_path(rf"^uploads/{_UID}/$", views.UploadDetailView.as_view(), name="upload"),
    # Админка: цена склейки (карточка в «Настройках» рядом с мультстудией).
    path("manage/settings/", views.ManageSettingsView.as_view(), name="manage-settings"),
    re_path(rf"^{_UID}/$", views.ProjectDetailView.as_view(), name="project"),
    re_path(rf"^{_UID}/render/$", views.RenderView.as_view(), name="render"),
    re_path(rf"^{_UID}/download/$", views.DownloadView.as_view(), name="download"),
    # Звук склейки (Build MA): голос за кадром, музыка, звук роликов.
    re_path(rf"^{_UID}/audio/$", views_audio.AudioView.as_view(), name="audio"),
    re_path(rf"^{_UID}/audio/voice/$", views_audio.VoiceView.as_view(), name="audio-voice"),
    re_path(rf"^{_UID}/audio/music/$", views_audio.MusicView.as_view(), name="audio-music"),
    re_path(rf"^{_UID}/audio/music/upload/$", views_audio.MusicUploadView.as_view(),
            name="audio-music-upload"),
    re_path(rf"^{_UID}/audio/(?P<track>[0-9a-fA-F]{{32}})/$", views_audio.TrackView.as_view(),
            name="audio-track"),
]
