from django.contrib import admin
from .models import User, UserQuestions, Notification
from django.utils import timezone
from django.utils.html import format_html

@admin.register(User)
class UserAdmin(admin.ModelAdmin):
    list_display = (
        'email', 'first_name', 'last_name', 'patronymic', 'tel', 
        'telegram', 'country', 'city', 'is_active', 'is_staff', 
        'is_superuser', 'is_confirmed', 'date_joined', 
        'last_login', 'last_session', 'date_of_birth'
    )
    search_fields = ('email', 'first_name', 'last_name')
    list_filter = ('is_active', 'is_staff', 'is_superuser')
    ordering = ('-date_joined',)
    readonly_fields = ('date_joined', 'last_login', 'last_session')


@admin.register(UserQuestions)
class UserQuestionsAdmin(admin.ModelAdmin):
    list_display = ('email', 'question', 'created_at')
    search_fields = ('email', 'question')
    list_filter = ('created_at',)
    ordering = ('-created_at',)
    readonly_fields = ('created_at',)
    
    
@admin.register(Notification)
class NotificationAdmin(admin.ModelAdmin):
    # Main table columns
    list_display = (
        "id",
        "recipient",
        "title",
        "short_body",
        "is_read",
        "created_at",
        "read_at",
        "status_badge",
    )
    list_display_links = ("id", "title")

    # Filters & search
    list_filter = ("is_read", "created_at", "read_at", "recipient")
    search_fields = ("title", "body", "recipient__username", "recipient__email")

    # UX
    date_hierarchy = "created_at"
    autocomplete_fields = ("recipient",)
    readonly_fields = ("created_at", "read_at")
    ordering = ("-created_at",)
    list_per_page = 50
    actions = ("mark_as_read", "mark_as_unread")

    # Keep related user join efficient
    list_select_related = ("recipient",)

    # --- Custom displays ---
    @admin.display(description="Краткое", ordering="body")
    def short_body(self, obj: Notification) -> str:
        # Show first 80 chars to keep table compact
        return (obj.body[:77] + "…") if obj.body and len(obj.body) > 80 else (obj.body or "")

    @admin.display(description="Статус", boolean=False)
    def status_badge(self, obj: Notification) -> str:
        # Simple colored badge showing read/unread
        color = "#14b8a6" if obj.is_read else "#f59e0b"
        label = "прочитано" if obj.is_read else "новое"
        return format_html(
            '<span style="padding:2px 8px;border-radius:12px;background:{}22;color:{};font-size:12px;">{}</span>',
            color,
            color,
            label,
        )

    # --- Actions ---
    @admin.action(description="Отметить выбранные как прочитанные")
    def mark_as_read(self, request, queryset):
        now = timezone.now()
        # Bulk update for speed; skip already read
        updated = queryset.filter(is_read=False).update(is_read=True, read_at=now)
        self.message_user(request, f"Обновлено: {updated}")

    @admin.action(description="Отметить выбранные как не прочитанные")
    def mark_as_unread(self, request, queryset):
        updated = queryset.filter(is_read=True).update(is_read=False, read_at=None)
        self.message_user(request, f"Обновлено: {updated}")