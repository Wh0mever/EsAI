from .models import (
    Plan, UserSubscription, GenerationUsage, CurrencyRate, GenerationUnitPrice,
    TokenPackage, TokenTransaction,
)
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
    FIELD_LABELS = {
        "is_active": "Активен",
        "is_free": "Бесплатный",
        "period": "Период",
        "sort_order": "Порядок сортировки",
        "price_amount": "Цена",
        "price_base_amount": "Базовая цена (до скидки)",
        "llm_engine": "LLM модель",
        "template_name_ru": "Название шаблона (RU)",
        "template_name_en": "Название шаблона (EN)",
        "template_name_kg": "Название шаблона (KG)",
        "song_limit": "Лимит песен",
        "music_limit": "Лимит музыки",
        "text_limit": "Лимит текстов",
        "image_limit": "Лимит изображений",
        "sunday_bonus_songs": "Воскресный бонус: песни",
        "sunday_bonus_music": "Воскресный бонус: музыка",
        "sunday_bonus_texts": "Воскресный бонус: тексты",
        "sunday_bonus_images": "Воскресный бонус: изображения",
        "can_purchase_addons": "Разрешить докупку генераций",
        "ai_chat_enabled": "AI-чат",
        "realtime_chat_enabled": "Чат в реальном времени",
        "images_enabled": "Изображения",
        "music_enabled": "Музыка",
        "mp4_enabled": "MP4",
        "support_enabled": "Поддержка",
    }

    list_display = (
        "id", "period", "is_free", "is_active",
        "price_amount", "price_base_amount",
        "song_limit", "music_limit", "text_limit", "image_limit",
        "can_purchase_addons",
    )
    list_filter = (
        "period", "is_active", "is_free",
        "ai_chat_enabled", "realtime_chat_enabled", "images_enabled",
        "music_enabled", "mp4_enabled", "support_enabled",
    )
    search_fields = ("id",)
    ordering = ("sort_order", "id")
    fieldsets = (
        ("Основное", {"fields": ("is_active", "is_free", "period", "sort_order")}),
        ("Названия", {
            "fields": (
                "template_name_ru", "template_name_en", "template_name_kg",
            )
        }),
        ("Цены", {"fields": ( "price_amount", "price_base_amount")}),
        ("Модель", {"fields": ("llm_engine",)}),
        ("Лимиты (0 = без включённых генераций)", {
            "fields": (
                "song_limit", "music_limit", "text_limit", "image_limit",
            )
        }),
        ("Воскресные бонусы", {
            "fields": ("sunday_bonus_songs", "sunday_bonus_music", "sunday_bonus_texts", "sunday_bonus_images")
        }),
        ("Функции", {
            "fields": (
                "ai_chat_enabled", "realtime_chat_enabled",
                "images_enabled", "music_enabled", "mp4_enabled", "support_enabled",
            )
        }),
        ("Покупки", {
            "description": "Только для платных тарифов. Нельзя включать вместе с «is free».",
            "fields": ("can_purchase_addons",),
        }),
    )

    def formfield_for_dbfield(self, db_field, request, **kwargs):
        formfield = super().formfield_for_dbfield(db_field, request, **kwargs)
        if db_field.name in self.FIELD_LABELS and formfield is not None:
            formfield.label = self.FIELD_LABELS[db_field.name]
        return formfield


@admin.register(GenerationUnitPrice)
class GenerationUnitPriceAdmin(admin.ModelAdmin):
    list_display = ("id", "music_price", "image_price", "text_price")
    fields = ("music_price", "image_price", "text_price")

    def has_add_permission(self, request):
        if GenerationUnitPrice.objects.exists():
            return False
        return super().has_add_permission(request)


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


@admin.register(TokenPackage)
class TokenPackageAdmin(admin.ModelAdmin):
    list_display = (
        "id", "name", "tokens", "bonus_tokens", "price", "currency",
        "badge", "featured", "is_active", "sort_order",
    )
    list_editable = ("tokens", "bonus_tokens", "price", "badge", "featured", "is_active", "sort_order")
    list_filter = ("is_active", "featured", "currency")
    search_fields = ("id", "name")
    ordering = ("sort_order", "id")


@admin.register(TokenTransaction)
class TokenTransactionAdmin(admin.ModelAdmin):
    list_display = ("id", "user", "delta", "reason", "balance_after", "created_at")
    list_filter = ("reason", "created_at")
    search_fields = ("id", "user__email", "user__username")
    date_hierarchy = "created_at"
    ordering = ("-created_at",)
    readonly_fields = ("user", "delta", "reason", "balance_after", "created_at", "meta")

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        # Read-only ledger: allow viewing detail page, forbid edits.
        return False

    def has_delete_permission(self, request, obj=None):
        return False
