from django.urls import path

from . import views, views_audio

app_name = "cartoon"

urlpatterns = [
    path("presets/", views.PresetsView.as_view(), name="presets"),
    path("pricing/", views.PricingView.as_view(), name="pricing"),
    # Док: модели с ценой сцены по качеству и длительности.
    path("models/", views.ModelsView.as_view(), name="models"),
    # Админка: что получают новые мультфильмы (модель, качество, длительность).
    path("manage/defaults/", views.DefaultsAdminView.as_view(), name="manage-defaults"),
    # Примерка героя на сцену: показать кадр до съёмки.
    path("presets/<int:pk>/try-on/", views.PresetTryOnView.as_view(), name="preset-try-on"),
    path("keyframes/", views.KeyframesView.as_view(), name="keyframes"),
    # Всё готовое по герою: кадры и движущиеся ролики пар.
    path("previews/", views.PreviewsView.as_view(), name="previews"),
    path("characters/", views.CharactersView.as_view(), name="characters"),
    path("characters/generate/", views.CharacterGenerateView.as_view(), name="character-generate"),
    path("characters/<int:pk>/", views.CharacterDetailView.as_view(), name="character-detail"),
    path("projects/", views.ProjectsView.as_view(), name="projects"),
    # Лента гостя после входа: перенос одним запросом.
    path("projects/import/", views.ProjectImportView.as_view(), name="projects-import"),
    path("projects/<int:pk>/", views.ProjectDetailView.as_view(), name="project-detail"),
    path("projects/<int:pk>/scenes/", views.ProjectScenesView.as_view(), name="project-scenes"),
    path("projects/<int:pk>/assemble/", views.ProjectAssembleView.as_view(), name="project-assemble"),
    path("scenes/<int:pk>/", views.SceneDetailView.as_view(), name="scene-detail"),
    path("scenes/<int:pk>/render/", views.SceneRenderView.as_view(), name="scene-render"),
    # Звук: голоса, музыка, эффекты, свой голос и сведение со сценой.
    path("audio/config/", views_audio.AudioConfigView.as_view(), name="audio-config"),
    path("audio/voices/", views_audio.VoicesView.as_view(), name="audio-voices"),
    path("audio/voices/<str:voice_id>/preview/", views_audio.VoicePreviewView.as_view(),
         name="audio-voice-preview"),
    path("audio/<int:pk>/", views_audio.AudioTrackDetailView.as_view(), name="audio-track"),
    path("scenes/<int:pk>/audio/", views_audio.SceneAudioView.as_view(), name="scene-audio"),
    path("scenes/<int:pk>/audio/voice/", views_audio.SceneVoiceView.as_view(), name="scene-audio-voice"),
    path("scenes/<int:pk>/audio/music/", views_audio.SceneMusicView.as_view(), name="scene-audio-music"),
    path("scenes/<int:pk>/audio/sfx/", views_audio.SceneSfxView.as_view(), name="scene-audio-sfx"),
    path("scenes/<int:pk>/audio/upload/", views_audio.SceneUploadAudioView.as_view(), name="scene-audio-upload"),
    path("scenes/<int:pk>/audio/mix/", views_audio.SceneMixView.as_view(), name="scene-audio-mix"),
    # «Озвучить весь мультфильм»: сначала план с ценой, потом запуск.
    path("projects/<int:pk>/voice-plan/", views_audio.ProjectVoicePlanView.as_view(), name="project-voice-plan"),
    path("projects/<int:pk>/voice-all/", views_audio.ProjectVoiceAllView.as_view(), name="project-voice-all"),
    # Своя сцена: кадр до съёмки.
    path("scenes/<int:pk>/frame/", views.SceneFrameView.as_view(), name="scene-frame"),
]
