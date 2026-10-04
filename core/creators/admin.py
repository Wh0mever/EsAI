"""Django-админка программы Creators — только просмотр.

Любая правка здесь прошла бы мимо журнала действий (audit.AdminActionLog) и
мимо блокировки строки креатора, под которой считаются деньги. Все изменения
делаются в /admin-new/creators, где каждое действие пишется в журнал.
"""
from django.contrib import admin

from .models import (
    Creator,
    CreatorApplication,
    CreatorClick,
    CreatorCode,
    CreatorCommission,
    CreatorLevel,
    CreatorPublication,
    CreatorReferral,
    CreatorWithdrawal,
)


class ReadOnlyAdmin(admin.ModelAdmin):
    """Без add/change/delete — как журнал событий (audit.admin.EventLogAdmin)."""

    list_per_page = 50

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def get_readonly_fields(self, request, obj=None):
        return [f.name for f in self.model._meta.fields]


@admin.register(CreatorLevel)
class CreatorLevelAdmin(ReadOnlyAdmin):
    list_display = ("sort", "key", "title", "percent", "min_publications", "min_registrations",
                    "min_paying", "updated_at")
    ordering = ("sort",)


@admin.register(CreatorApplication)
class CreatorApplicationAdmin(ReadOnlyAdmin):
    list_display = ("id", "created_at", "user", "name", "telegram", "country", "followers",
                    "status", "decided_at")
    list_filter = ("status", "created_at")
    search_fields = ("name", "telegram", "user__email")
    list_select_related = ("user",)
    ordering = ("-created_at",)


@admin.register(Creator)
class CreatorAdmin(ReadOnlyAdmin):
    list_display = ("id", "display_name", "user", "level", "status", "payout_address", "created_at")
    list_filter = ("status", "level")
    search_fields = ("display_name", "user__email", "codes__code")
    list_select_related = ("user", "level")
    ordering = ("-created_at",)


@admin.register(CreatorCode)
class CreatorCodeAdmin(ReadOnlyAdmin):
    list_display = ("code", "creator", "is_primary", "is_active", "created_at")
    list_filter = ("is_primary", "is_active")
    search_fields = ("code", "creator__display_name")
    list_select_related = ("creator",)
    ordering = ("-created_at",)


@admin.register(CreatorReferral)
class CreatorReferralAdmin(ReadOnlyAdmin):
    list_display = ("id", "bound_at", "user", "creator", "source", "code_used", "suspect",
                    "ended_at", "end_reason")
    list_filter = ("source", "suspect", "bound_at")
    search_fields = ("user__email", "creator__display_name", "code_used", "telegram_uid")
    list_select_related = ("user", "creator")
    ordering = ("-bound_at",)


@admin.register(CreatorClick)
class CreatorClickAdmin(ReadOnlyAdmin):
    list_display = ("id", "day", "creator", "code", "device_key")
    list_filter = ("day",)
    search_fields = ("code", "creator__display_name")
    list_select_related = ("creator",)
    ordering = ("-day", "-id")


@admin.register(CreatorPublication)
class CreatorPublicationAdmin(ReadOnlyAdmin):
    list_display = ("id", "created_at", "creator", "network", "url", "status", "decided_at")
    list_filter = ("status", "network", "created_at")
    search_fields = ("url", "creator__display_name")
    list_select_related = ("creator",)
    ordering = ("-created_at",)


@admin.register(CreatorCommission)
class CreatorCommissionAdmin(ReadOnlyAdmin):
    list_display = ("id", "created_at", "creator", "buyer_pk", "order_id", "provider", "base_usd",
                    "percent", "amount_usdt", "status", "reason", "available_at")
    list_filter = ("status", "provider", "created_at")
    search_fields = ("order_id", "creator__display_name")
    list_select_related = ("creator",)
    ordering = ("-created_at",)


@admin.register(CreatorWithdrawal)
class CreatorWithdrawalAdmin(ReadOnlyAdmin):
    list_display = ("id", "created_at", "creator", "amount_usdt", "address", "network", "status",
                    "txid", "paid_at")
    list_filter = ("status", "created_at")
    search_fields = ("address", "txid", "creator__display_name")
    list_select_related = ("creator",)
    ordering = ("-created_at",)
