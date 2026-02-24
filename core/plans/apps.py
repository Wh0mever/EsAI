from django.apps import AppConfig


class PlansConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "plans"
    verbose_name = "Тарифы"

    def ready(self):
        # Ensure signals are registered
        from . import signals  # noqa: F401

        # Avoid hitting the DB directly during app initialization.
        # Instead, create / update Celery Beat periodic tasks after migrations.
        from django.db.models.signals import post_migrate
        from django_celery_beat.models import IntervalSchedule, PeriodicTask

        def ensure_periodic_tasks(sender, **kwargs):
            try:
                # Every 10 minutes: process due subscriptions
                interval_10m, _ = IntervalSchedule.objects.get_or_create(
                    every=10,
                    period=IntervalSchedule.MINUTES,
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
                    every=1,
                    period=IntervalSchedule.HOURS,
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
                # Database or django_celery_beat might be unavailable in some contexts; ignore.
                pass

        post_migrate.connect(ensure_periodic_tasks, sender=self)
