from django.contrib import admin
from django import forms
from .models import User, UserQuestions, Notification, NotificationDelivery, UserFeedback, UserCardBind
from django.utils import timezone
from django.utils.html import format_html
from .actions import charge_by_current_plan

@admin.register(User)
class UserAdmin(admin.ModelAdmin):
    list_display = (
        'email', 'first_name', 'last_name', 'patronymic', 'tel', 
        'telegram', 'country', 'city', 'is_active', 'is_staff', 
        'is_superuser', 'is_confirmed', 'free_plan_activated', 'date_joined', 
        'last_login', 'last_session', 'date_of_birth',
        'referral_uid', 'bonus_texts', 'bonus_images', 'bonus_songs', 'bonus_music'
    )
    search_fields = ('email', 'first_name', 'last_name', 'tel', 'referral_uid')
    list_filter = ('is_active', 'is_staff', 'is_superuser', 'is_confirmed', 'date_joined')
    ordering = ('-date_joined',)
    readonly_fields = ('date_joined', 'last_login', 'last_session')
    actions = [charge_by_current_plan, 'regenerate_referral_uid']

    @admin.action(description="Сгенерировать новый Referral UID")
    def regenerate_referral_uid(self, request, queryset):
        count = 0
        for user in queryset:
            user.referral_uid = None
            user.save(update_fields=["referral_uid"])  # save() сгенерирует уникальный UID
            count += 1
        self.message_user(request, f"Сгенерировано новых UID: {count}")


@admin.register(UserCardBind)
class UserCardBindAdmin(admin.ModelAdmin):
    list_display = ('user', 'card_mask', 'card_token', 'created_at', 'is_active')
    search_fields = ('user__email', 'card_hash', 'card_token')
    list_filter = ('user__is_active', 'created_at')
    ordering = ('-created_at',)
    # readonly_fields = ('user', 'card_mask', 'card_token', 'created_at', 'is_active')

    @admin.display(description="Card", ordering="card_hash")
    def card_mask(self, obj):
        return obj.card_hash or obj.card_id

    @admin.display(description="User active", boolean=True, ordering="user__is_active")
    def is_active(self, obj):
        return obj.user.is_active


@admin.register(UserQuestions)
class UserQuestionsAdmin(admin.ModelAdmin):
    list_display = ('email', 'question', 'created_at')
    search_fields = ('email', 'question')
    list_filter = ('created_at',)
    ordering = ('-created_at',)
    readonly_fields = ('created_at',)
    
    
class NotificationDeliveryInline(admin.TabularInline):
    model = NotificationDelivery
    extra = 0
    autocomplete_fields = ("recipient",)
    fields = ("recipient", "is_read", "assigned_at", "read_at")
    readonly_fields = ("assigned_at", "read_at")


@admin.register(Notification)
class NotificationAdmin(admin.ModelAdmin):
    class NotificationAdminForm(forms.ModelForm):
        broadcast_all = forms.BooleanField(
            required=False,
            label="Отправить всем пользователям",
            help_text="Создать уведомление для всех активных пользователей",
        )

        class Meta:
            model = Notification
            fields = ("title", "body")

    form = NotificationAdminForm
    list_display = (
        "id",
        "title",
        "short_body",
        "created_at",
        "recipients_count",
    )
    list_display_links = ("id", "title")
    list_filter = ("created_at",)
    search_fields = ("title", "body")
    date_hierarchy = "created_at"
    readonly_fields = ("created_at",)
    ordering = ("-created_at",)
    list_per_page = 50
    inlines = [NotificationDeliveryInline]

    # Explicit fields order including the extra checkbox from the form
    fields = ("title", "body", "created_at", "broadcast_all")

    @admin.display(description="Краткое", ordering="body")
    def short_body(self, obj: Notification) -> str:
        return (obj.body[:77] + "…") if obj.body and len(obj.body) > 80 else (obj.body or "")

    @admin.display(description="Получателей")
    def recipients_count(self, obj: Notification) -> int:
        return obj.deliveries.count()

    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)
        # Broadcast to all active users if requested
        try:
            if form and form.cleaned_data.get("broadcast_all"):
                existing = set(obj.deliveries.values_list("recipient_id", flat=True))
                to_add = (
                    User.objects
                    .filter(is_active=True)
                    .exclude(id__in=existing)
                    .values_list("id", flat=True)
                )
                bulk = [NotificationDelivery(notification=obj, recipient_id=uid) for uid in to_add]
                if bulk:
                    NotificationDelivery.objects.bulk_create(bulk, ignore_conflicts=True)
                    self.message_user(request, f"Добавлено получателей: {len(bulk)}")
        except Exception as e:
            # Don't block admin save if broadcast fails; show message
            try:
                self.message_user(request, f"Не удалось отправить всем: {e}")
            except Exception:
                pass


@admin.register(UserFeedback)
class UserFeedbackAdmin(admin.ModelAdmin):
    list_display = ("id", "created_at", "user", "name", "email", "rating", "short_message")
    list_filter = ("created_at", "rating")
    search_fields = ("name", "email", "message")
    readonly_fields = ("created_at",)
    ordering = ("-created_at",)

    @admin.display(description="Сообщение")
    def short_message(self, obj: UserFeedback) -> str:
        txt = obj.message or ""
        return (txt[:77] + "…") if len(txt) > 80 else txt
