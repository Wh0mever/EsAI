from django.urls import path

from . import views

app_name = "cartoon"

urlpatterns = [
    path("presets/", views.PresetsView.as_view(), name="presets"),
    path("pricing/", views.PricingView.as_view(), name="pricing"),
    # Примерка героя на сцену: показать кадр до съёмки.
    path("presets/<int:pk>/try-on/", views.PresetTryOnView.as_view(), name="preset-try-on"),
    path("keyframes/", views.KeyframesView.as_view(), name="keyframes"),
    # Всё готовое по герою: кадры и движущиеся ролики пар.
    path("previews/", views.PreviewsView.as_view(), name="previews"),
    path("characters/", views.CharactersView.as_view(), name="characters"),
    path("characters/generate/", views.CharacterGenerateView.as_view(), name="character-generate"),
    path("projects/", views.ProjectsView.as_view(), name="projects"),
    # Лента гостя после входа: перенос одним запросом.
    path("projects/import/", views.ProjectImportView.as_view(), name="projects-import"),
    path("projects/<int:pk>/", views.ProjectDetailView.as_view(), name="project-detail"),
    path("projects/<int:pk>/scenes/", views.ProjectScenesView.as_view(), name="project-scenes"),
    path("projects/<int:pk>/assemble/", views.ProjectAssembleView.as_view(), name="project-assemble"),
    path("scenes/<int:pk>/", views.SceneDetailView.as_view(), name="scene-detail"),
    path("scenes/<int:pk>/render/", views.SceneRenderView.as_view(), name="scene-render"),
    # Своя сцена: кадр до съёмки.
    path("scenes/<int:pk>/frame/", views.SceneFrameView.as_view(), name="scene-frame"),
]
