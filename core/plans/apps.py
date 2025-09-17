from django.apps import AppConfig


class PlansConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'plans'

    def ready(self):
        # Ensure signals are registered
        from . import signals  # noqa: F401
