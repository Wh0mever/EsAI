from django.apps import AppConfig


class PlansConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'plans'

    def ready(self):
        # Ensure signals are registered
        from . import signals  # noqa: F401
        # Optionally ensure Celery Beat periodic tasks exist when using DatabaseScheduler
        try:
            from django_celery_beat.models import PeriodicTask, IntervalSchedule
            # Every 10 minutes: process due subscriptions
            interval_10m, _ = IntervalSchedule.objects.get_or_create(
                every=10, period=IntervalSchedule.MINUTES
            )
            PeriodicTask.objects.update_or_create(
                name="plans:process_due_subscriptions",
                defaults={
                    "task": "plans.tasks.process_due_subscriptions",
                    "interval": interval_10m,
                    "enabled": True,
                },
            )

            # Hourly: refresh currency rates
            interval_1h, _ = IntervalSchedule.objects.get_or_create(
                every=1, period=IntervalSchedule.HOURS
            )
            PeriodicTask.objects.update_or_create(
                name="plans:refresh_currency_rates",
                defaults={
                    "task": "plans.tasks.refresh_currency_rates",
                    "interval": interval_1h,
                    "enabled": True,
                },
            )
        except Exception:
            # Database might be unavailable during migrations or in certain contexts; ignore.
            pass
