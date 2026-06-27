from django.contrib import admin
from django.template.response import TemplateResponse
from django.urls import path

from .metrics import collect_dashboard_metrics
from .models import EventLog


@admin.register(EventLog)
class EventLogAdmin(admin.ModelAdmin):
    """Read-only журнал событий. Без add/change/delete."""

    list_display = ("created_at", "type", "level", "user", "short_message")
    list_filter = ("type", "level", "created_at")
    search_fields = ("message", "user__email")
    date_hierarchy = "created_at"
    ordering = ("-created_at",)
    list_per_page = 50
    list_select_related = ("user",)

    @admin.display(description="Сообщение")
    def short_message(self, obj):
        msg = obj.message or ""
        return (msg[:120] + "…") if len(msg) > 120 else msg

    # ---- read-only enforcement ----
    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        # Запрещаем удаление, чтобы журнал оставался append-only.
        return False

    def get_readonly_fields(self, request, obj=None):
        return [f.name for f in self.model._meta.fields]


# ---------------------------------------------------------------------------
# Дашборд бизнес-аналитики: кастомная страница в админке.
# Подключаем URL к стандартному admin.site без подмены AdminSite.
# ---------------------------------------------------------------------------

def dashboard_view(request):
    # Доступ ограничен через admin.site.admin_view() при регистрации URL
    # (требует залогиненного staff-пользователя).
    metrics = collect_dashboard_metrics()
    context = {
        **admin.site.each_context(request),
        "title": "Дашборд бизнес-аналитики",
        "metrics": metrics,
    }
    return TemplateResponse(request, "admin/audit/dashboard.html", context)


_original_get_urls = admin.site.get_urls


def _get_urls_with_dashboard():
    custom = [
        path(
            "audit-dashboard/",
            admin.site.admin_view(dashboard_view),
            name="audit_dashboard",
        ),
    ]
    return custom + _original_get_urls()


# Идемпотентно: не оборачиваем повторно при авто-перезагрузке.
if not getattr(admin.site.get_urls, "_audit_patched", False):
    admin.site.get_urls = _get_urls_with_dashboard
    admin.site.get_urls._audit_patched = True
