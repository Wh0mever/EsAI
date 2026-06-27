from django.apps import AppConfig


class AuditConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "audit"
    verbose_name = "Аудит и логи"

    def ready(self):
        # Register login/auth signal handlers.
        from . import signals  # noqa: F401
