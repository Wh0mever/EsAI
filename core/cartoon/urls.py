from django.urls import path

from . import views

app_name = "cartoon"

urlpatterns = [
    path("presets/", views.PresetsView.as_view(), name="presets"),
    path("pricing/", views.PricingView.as_view(), name="pricing"),
    path("characters/", views.CharactersView.as_view(), name="characters"),
    path("characters/generate/", views.CharacterGenerateView.as_view(), name="character-generate"),
    path("projects/", views.ProjectsView.as_view(), name="projects"),
    path("projects/<int:pk>/", views.ProjectDetailView.as_view(), name="project-detail"),
    path("projects/<int:pk>/scenes/", views.ProjectScenesView.as_view(), name="project-scenes"),
    path("projects/<int:pk>/assemble/", views.ProjectAssembleView.as_view(), name="project-assemble"),
    path("scenes/<int:pk>/", views.SceneDetailView.as_view(), name="scene-detail"),
]
