from django.contrib import admin

from .models import MergeProject


@admin.register(MergeProject)
class MergeProjectAdmin(admin.ModelAdmin):
    """Только смотреть: деньги и состояния меняют запуск, задача и уборка."""

    list_display = ("uid", "user", "title", "status", "aspect", "fit", "duration_s",
                    "credits_reserved", "credits_charged", "created_at", "expires_at")
    list_filter = ("status", "aspect", "fit")
    search_fields = ("uid", "title", "user__email")
    raw_id_fields = ("user",)
    readonly_fields = [f.name for f in MergeProject._meta.fields]

    def has_add_permission(self, request):
        return False
