"""Django-админка Creative Studio — только просмотр.

Служебные поля (тело запроса поставщику, его ссылки на файлы) здесь не
показываем: в них временные адреса поставщика, а страница админки — тоже браузер.
"""
from django.contrib import admin

from .models import CreativeCharacter, CreativeJob, CreativeTool, CreativeUpload, CreativeWebhookEvent


@admin.register(CreativeTool)
class CreativeToolAdmin(admin.ModelAdmin):
    list_display = ("slug", "enabled", "use_own_markup", "markup_pct", "updated_at")
    list_filter = ("enabled", "use_own_markup")


@admin.register(CreativeJob)
class CreativeJobAdmin(admin.ModelAdmin):
    list_display = ("uid", "user", "tool_slug", "status", "charge_state", "credits_reserved",
                    "credits_charged", "cost_usd", "needs_review", "created_at")
    list_filter = ("status", "charge_state", "tool_slug", "needs_review")
    search_fields = ("uid", "user__email", "provider_request_id", "client_request_id")
    exclude = ("request_body",)
    readonly_fields = [f.name for f in CreativeJob._meta.fields if f.name != "request_body"]
    raw_id_fields = ("user", "genlog")

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(CreativeUpload)
class CreativeUploadAdmin(admin.ModelAdmin):
    list_display = ("uid", "user", "kind", "w", "h", "duration_s", "bytes", "created_at")
    list_filter = ("kind",)
    search_fields = ("uid", "user__email")
    exclude = ("provider_url",)
    readonly_fields = [f.name for f in CreativeUpload._meta.fields if f.name != "provider_url"]
    raw_id_fields = ("user",)

    def has_add_permission(self, request):
        return False


@admin.register(CreativeCharacter)
class CreativeCharacterAdmin(admin.ModelAdmin):
    list_display = ("uid", "user", "name", "status", "deleted_at", "created_at")
    list_filter = ("status",)
    search_fields = ("uid", "user__email", "name")
    raw_id_fields = ("user", "job")

    def has_add_permission(self, request):
        return False


@admin.register(CreativeWebhookEvent)
class CreativeWebhookEventAdmin(admin.ModelAdmin):
    list_display = ("provider_request_id", "status", "processed", "received_at")
    readonly_fields = ("event_key", "provider_request_id", "status", "payload", "processed", "received_at")

    def has_add_permission(self, request):
        return False
