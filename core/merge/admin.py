from django.contrib import admin

from .models import MergeAudio, MergeProject, MergeUpload


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


@admin.register(MergeUpload)
class MergeUploadAdmin(admin.ModelAdmin):
    """Свои видео людей: смотреть и разбирать отказы; файлы живут по правилам уборки."""

    list_display = ("uid", "user", "title", "status", "error_code", "size", "duration_s",
                    "display_width", "display_height", "video_codec", "created_at", "expires_at")
    list_filter = ("status", "error_code", "video_codec", "hdr")
    search_fields = ("uid", "title", "user__email")
    raw_id_fields = ("user",)
    readonly_fields = [f.name for f in MergeUpload._meta.fields]

    def has_add_permission(self, request):
        return False


@admin.register(MergeAudio)
class MergeAudioAdmin(admin.ModelAdmin):
    """Звук склеек: смотреть; деньги и файлы меняют заказ, задача и уборка."""

    list_display = ("uid", "project", "kind", "source", "status", "error_code", "duration_s",
                    "credits_reserved", "credits_charged", "created_at", "expires_at")
    list_filter = ("kind", "source", "status")
    search_fields = ("uid", "project__uid", "project__user__email")
    raw_id_fields = ("project",)
    readonly_fields = [f.name for f in MergeAudio._meta.fields]

    def has_add_permission(self, request):
        return False
