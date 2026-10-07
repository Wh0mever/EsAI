from django.apps import AppConfig


class VstudioConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "vstudio"
    verbose_name = "Видеостудия"

    def ready(self):
        # Кэш витрины сбрасывают сигналы её модели. Подключаем здесь, а не при
        # загрузке маршрутов: воркер и команды управления маршруты не читают.
        from . import showcase  # noqa: F401
