from django.contrib import admin
from .models import Plan, UserSubscription, GenerationUsage, AddonPurchase, CurrencyRate


@admin.register(CurrencyRate)
class CurrencyRateAdmin(admin.ModelAdmin):
    list_display = ("id", "currency", "rate_to_usd", "usd_in_currency", "fetched_at")

    def usd_in_currency(self, obj):
        if obj.rate_to_usd and obj.rate_to_usd != 0:
            value = 1 / obj.rate_to_usd
            return f"{value:.4f} {obj.currency}"
        return "-"

    usd_in_currency.short_description = "1 USD в валюте"



@admin.register(Plan)
class PlanAdmin(admin.ModelAdmin):
    list_display = (
        "id", "period", "duration_days", "is_free", "is_active",
        "price_amount", "price_base_amount",
        "song_limit", "music_limit", "text_limit", "image_limit",
        "ai_templates_limit", "operations_per_month_limit", "covers_limit",
        "can_purchase_addons",
    )
    list_filter = (
        "period", "is_active", "is_free",
        "ai_chat_enabled", "realtime_chat_enabled", "images_enabled",
        "diffusion_images_enabled", "tts_enabled", "music_enabled", "support_enabled",
    )
    search_fields = ("id",)
    ordering = ("sort_order", "id")
    fieldsets = (
        ("Meta", {"fields": ("is_active", "is_free", "period", "duration_days", "sort_order")}),
        ("Names", {
            "fields": (
                "template_name_ru", "template_name_en", "template_name_kg",
            )
        }),
        ("Pricing", {"fields": ( "price_amount", "price_base_amount")}),
        ("Engine", {"fields": ("llm_engine",)}),
        ("Limits (0 = unlimited)", {
            "fields": (
                "ai_templates_limit", "operations_per_month_limit", "covers_limit",
                "song_limit", "music_limit", "text_limit", "image_limit",
            )
        }),
        ("Sunday Bonuses", {
            "fields": ("sunday_bonus_songs", "sunday_bonus_music", "sunday_bonus_texts", "sunday_bonus_images")
        }),
        ("Features", {
            "fields": (
                "ai_chat_enabled", "realtime_chat_enabled", "rewriter_enabled", "antiplag_enabled",
                "images_enabled", "diffusion_images_enabled", "blog_master_enabled",
                "music_enabled", "tts_enabled", "my_templates_enabled", "manager_enabled", "support_enabled",
            )
        }),
        ("Purchases", {"fields": ("can_purchase_addons",)}),
    )


class GenerationUsageInline(admin.StackedInline):
    model = GenerationUsage
    can_delete = False
    extra = 0
    fields = ("songs_left", "music_left", "texts_left", "images_left", "sunday_bonus_used")


@admin.register(UserSubscription)
class UserSubscriptionAdmin(admin.ModelAdmin):
    list_display = (
        "id", "user", "plan", "status", "payment_status",
        "start_date", "end_date", "payment_date",
    )
    list_filter = ("status", "payment_status", "plan__period")
    search_fields = ("id", "user__username", "user__email")
    date_hierarchy = "start_date"
    inlines = [GenerationUsageInline]


@admin.register(AddonPurchase)
class AddonPurchaseAdmin(admin.ModelAdmin):
    list_display = ("id", "subscription", "addon_type", "purchase_date",
                    "songs_added", "music_added", "texts_added", "images_added")
    list_filter = ("addon_type",)
    search_fields = ("subscription__user__username", "subscription__user__email")
