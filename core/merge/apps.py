from django.apps import AppConfig


class MergeConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "merge"
    verbose_name = "Склейка видео"

    def ready(self):
        # Файлы склейки удаляются вместе со строкой и из админки, и с аккаунтом.
        from . import signals  # noqa: F401
