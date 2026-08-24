"""Админка студии мультфильмов.

Главное здесь — пресеты. Клиент должен добавлять новые сцены сам, не трогая
код: залил видео-превью, написал скрытый промпт, выбрал модели и длительность —
сцена появилась в студии. Цена считается автоматически по моделям, но её можно
назначить вручную.
"""
from django.contrib import admin
from django.utils.html import format_html

from .models import CartoonCharacter, CartoonPreset, CartoonProject, CartoonScene


@admin.register(CartoonPreset)
class CartoonPresetAdmin(admin.ModelAdmin):
    list_display = ("title", "slug", "video_model", "duration", "aspect_ratio",
                    "price", "is_active", "sort_order")
    list_filter = ("is_active", "video_model", "aspect_ratio")
    list_editable = ("is_active", "sort_order")
    search_fields = ("title", "slug", "scene_prompt")
    prepopulated_fields = {"slug": ("title",)}
    ordering = ("sort_order", "id")
    fieldsets = (
        ("Что видит пользователь", {
            "fields": ("title", "subtitle", "slug", "preview_video", "preview_poster",
                       "is_active", "sort_order"),
            "description": "Промпты и модели пользователю не показываются — он выбирает сцену по превью.",
        }),
        ("Что уходит моделям", {
            "fields": ("scene_prompt", "motion_prompt", "style_prompt"),
            "description": (
                "Слово «character» в промпте заменяется описанием персонажа. "
                "Стиль лучше держать одинаковым у всех пресетов набора — тогда сцены "
                "выглядят одним мультфильмом, а не нарезкой из разных."
            ),
        }),
        ("Модели и настройки", {
            "fields": ("image_model", "video_model", "duration", "aspect_ratio",
                       "resolution", "credits_override"),
            "description": (
                "Модель кадра ОБЯЗАНА поддерживать референс — иначе персонаж не перенесётся "
                "в сцену. Проверено: Nano Banana подходит, FLUX Flex слишком медленный."
            ),
        }),
    )

    @admin.display(description="Цена, кр")
    def price(self, obj: CartoonPreset) -> str:
        try:
            base = obj.estimated_credits()
        except Exception:
            return "—"
        return f"{base}" + (" (вручную)" if obj.credits_override else "")


@admin.register(CartoonCharacter)
class CartoonCharacterAdmin(admin.ModelAdmin):
    list_display = ("preview", "name", "source", "user", "is_public", "sort_order", "created_at")
    list_filter = ("source", "is_public")
    list_editable = ("is_public", "sort_order")
    search_fields = ("name", "description", "user__email")
    ordering = ("sort_order", "-created_at")

    @admin.display(description="Вид")
    def preview(self, obj: CartoonCharacter):
        if not obj.image:
            return "—"
        return format_html('<img src="{}" style="height:44px;border-radius:6px" />', obj.image.url)


class CartoonSceneInline(admin.TabularInline):
    model = CartoonScene
    extra = 0
    fields = ("order", "preset", "status", "credits_spent", "keyframe", "video", "error")
    readonly_fields = ("keyframe", "video", "credits_spent", "error")
    ordering = ("order",)


@admin.register(CartoonProject)
class CartoonProjectAdmin(admin.ModelAdmin):
    list_display = ("title", "user", "character", "status", "scenes_count", "created_at")
    list_filter = ("status", "created_at")
    search_fields = ("title", "user__email")
    readonly_fields = ("result_video", "error", "created_at", "updated_at")
    inlines = (CartoonSceneInline,)
    ordering = ("-created_at",)

    @admin.display(description="Сцен")
    def scenes_count(self, obj: CartoonProject) -> int:
        return obj.scenes.count()
