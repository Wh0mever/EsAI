from django.apps import AppConfig


class MailsConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'mails'

    def ready(self):
        # Ensure Celery tasks are imported/registered
        try:
            from . import tasks  # noqa: F401
        except Exception:
            # Do not break Django startup if Celery not configured
            pass
