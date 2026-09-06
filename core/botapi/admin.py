from django.contrib import admin

from .models import TelegramChat


@admin.register(TelegramChat)
class TelegramChatAdmin(admin.ModelAdmin):
    list_display = ("telegram_id", "username", "user", "lang", "is_blocked", "last_seen_at")
    list_filter = ("is_blocked", "lang", "source", "notify_bonus")
    search_fields = ("telegram_id", "username", "user__email")
    raw_id_fields = ("user",)
    readonly_fields = ("created_at", "last_seen_at", "last_sent_at")
