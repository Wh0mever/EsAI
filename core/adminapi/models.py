"""Runtime-настройки приложения (правятся из админки без рестарта).

AppSetting — плоское key/value хранилище. Значения читаются через
adminapi.runtime.get_runtime (кэш 30с) и переопределяют env/django settings.
"""
from django.db import models


class AppSetting(models.Model):
    key = models.CharField(max_length=64, unique=True)
    value = models.TextField(blank=True, default="")
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.key

    class Meta:
        verbose_name = "Runtime-настройка"
        verbose_name_plural = "Runtime-настройки"
