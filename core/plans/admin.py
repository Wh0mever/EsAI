from .models import Plan, UserSubscription, GenerationUsage, AddonPurchase, CurrencyRate
from django.contrib import admin, messages
from django.core.management import call_command
from django.urls import path, reverse
from django.shortcuts import redirect
from django.utils.translation import gettext_lazy as _
from django.utils.decorators import method_decorator
from django.views.decorators.http import require_POST

@admin.register(CurrencyRate)
class CurrencyRateAdmin(admin.ModelAdmin):
    list_display = ("id", "currency", "rate_to_usd", "usd_in_currency", "fetched_at")
    list_filter = ("currency", "fetched_at")
    search_fields = ("currency__code", "currency__name")
    date_hierarchy = "fetched_at"
    ordering = ("-fetched_at",)
    list_per_page = 50

    # отображение: сколько стоит 1 USD в этой валюте
    @admin.display(description="1 USD в валюте")
    def usd_in_currency(self, obj):
        if obj.rate_to_usd:
            try:
                value = 1 / obj.rate_to_usd
                return f"{value:.4f} {obj.currency}"
            except ZeroDivisionError:
                return "-"
        return "-"

    # --- кнопка "получить курсы" ---
    def get_urls(self):
        urls = super().get_urls()
        app, model = self.model._meta.app_label, self.model._meta.model_name
        custom_urls = [
            path(
                "fetch-rates/",
                self.admin_site.admin_view(self.fetch_rates_view),
                name=f"{app}_{model}_fetch_rates",
            ),
        ]
        return custom_urls + urls

    def changelist_view(self, request, extra_context=None):
        extra_context = extra_context or {}
        app, model = self.model._meta.app_label, self.model._meta.model_name
        extra_context["sync_url"] = reverse(f"{self.admin_site.name}:{app}_{model}_fetch_rates")
        return super().changelist_view(request, extra_context=extra_context)

    @method_decorator(require_POST)
    def fetch_rates_view(self, request):
        if not self.has_change_permission(request):
            self.message_user(request, _("Недостаточно прав"), messages.ERROR)
            return redirect("..")

        try:
            call_command("fetch_rates")
            self.message_user(request, _("Курсы валют успешно обновлены"), messages.SUCCESS)
        except Exception as e:
            self.message_user(request, f"Ошибка при обновлении: {e}", messages.ERROR)

        return redirect("..")


@admin.register(Plan)
class PlanAdmin(admin.ModelAdmin):
    list_display = (
        "id", "period", "duration_days", "is_free", "is_active",
        "price_amount", "price_base_amount",
        "song_limit", "music_limit", "text_limit", "image_limit",
        "chat_output_tokens_limit",
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
        ("Chat", {"fields": ("chat_output_tokens_limit",)}),
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
