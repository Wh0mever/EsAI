from django.apps import AppConfig


class CreativeConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "creative"
    verbose_name = "Creative Studio"

    def ready(self):
        # Файлы результатов и загрузок уходят вместе со строкой — откуда бы её ни удалили.
        from . import signals  # noqa: F401
