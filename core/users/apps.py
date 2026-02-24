from django.apps import AppConfig


class UsersConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "users"
    verbose_name = "Пользователи"

    def ready(self):
        # Runtime labels for third-party models in Django admin.
        try:
            from django.apps import apps
            social_cfg = apps.get_app_config("socialaccount")
            social_cfg.verbose_name = "Социальные аккаунты"

            SocialAccount = apps.get_model("socialaccount", "SocialAccount")
            SocialToken = apps.get_model("socialaccount", "SocialToken")
            SocialApp = apps.get_model("socialaccount", "SocialApp")

            SocialAccount._meta.verbose_name = "Социальный аккаунт"
            SocialAccount._meta.verbose_name_plural = "Социальные аккаунты"
            SocialToken._meta.verbose_name = "Токен социального приложения"
            SocialToken._meta.verbose_name_plural = "Токены социальных приложений"
            SocialApp._meta.verbose_name = "Социальное приложение"
            SocialApp._meta.verbose_name_plural = "Социальные приложения"
        except Exception:
            pass

        # Celery Beat labels
        try:
            from django.apps import apps
            beat_cfg = apps.get_app_config("django_celery_beat")
            beat_cfg.verbose_name = "Периодические задачи"

            PeriodicTask = apps.get_model("django_celery_beat", "PeriodicTask")
            IntervalSchedule = apps.get_model("django_celery_beat", "IntervalSchedule")
            CrontabSchedule = apps.get_model("django_celery_beat", "CrontabSchedule")
            SolarSchedule = apps.get_model("django_celery_beat", "SolarSchedule")
            ClockedSchedule = apps.get_model("django_celery_beat", "ClockedSchedule")

            PeriodicTask._meta.verbose_name = "Периодическая задача"
            PeriodicTask._meta.verbose_name_plural = "Периодические задачи"
            IntervalSchedule._meta.verbose_name = "Интервальное расписание"
            IntervalSchedule._meta.verbose_name_plural = "Интервальные расписания"
            CrontabSchedule._meta.verbose_name = "Расписание cron"
            CrontabSchedule._meta.verbose_name_plural = "Расписания cron"
            SolarSchedule._meta.verbose_name = "Солнечное расписание"
            SolarSchedule._meta.verbose_name_plural = "Солнечные расписания"
            ClockedSchedule._meta.verbose_name = "Запланированное время"
            ClockedSchedule._meta.verbose_name_plural = "Запланированные времена"
        except Exception:
            pass

        # Celery Results labels
        try:
            from django.apps import apps
            results_cfg = apps.get_app_config("django_celery_results")
            results_cfg.verbose_name = "Результаты задач"

            TaskResult = apps.get_model("django_celery_results", "TaskResult")
            GroupResult = apps.get_model("django_celery_results", "GroupResult")

            TaskResult._meta.verbose_name = "Результат выполнения задачи"
            TaskResult._meta.verbose_name_plural = "Результаты выполнения задач"
            GroupResult._meta.verbose_name = "Результат группы задач"
            GroupResult._meta.verbose_name_plural = "Результаты групп задач"
        except Exception:
            pass

        # Optional model (present in some django-celery-results versions)
        try:
            from django.apps import apps
            ChordCounter = apps.get_model("django_celery_results", "ChordCounter")
            ChordCounter._meta.verbose_name = "Счетчик chord-задачи"
            ChordCounter._meta.verbose_name_plural = "Счетчики chord-задач"
        except Exception:
            pass
