from django.contrib import admin
from django import forms
from .models import User, UserQuestions, Notification, NotificationDelivery, UserFeedback, UserCardBind, SignupBlock
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
        'referral_uid', 'token_balance',
        'bonus_texts', 'bonus_images', 'bonus_songs', 'bonus_music'
    )
    # Ручная корректировка баланса токенов админом прямо из списка (ТЗ 7.4).
    list_editable = ('token_balance',)
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


@admin.register(SignupBlock)
class SignupBlockAdmin(admin.ModelAdmin):
    """Чёрный список: домены одноразовой почты, IP и подсети.

    Правило начинает действовать сразу после сохранения. Само по себе оно
    закрывает только НОВЫЕ регистрации и (если стоит «Закрыть и вход») вход
    существующих. Уже заведённые аккаунты остаются в базе — отключить их можно
    действием «Отключить аккаунты, попадающие под правило».
    """
    list_display = ("kind", "value", "block_login", "is_active", "matched_users", "hits", "last_hit_at", "reason")
    list_filter = ("kind", "is_active", "block_login")
    search_fields = ("value", "reason")
    list_editable = ("is_active", "block_login")
    readonly_fields = ("hits", "last_hit_at", "created_at")
    ordering = ("-created_at",)
    actions = ("deactivate_matching_users", "activate_matching_users")

    @admin.display(description="Аккаунтов под правилом")
    def matched_users(self, obj: SignupBlock) -> str:
        """Сколько уже заведённых аккаунтов подходит под правило."""
        try:
            return str(self._matching_users(obj).count())
        except Exception:
            return "—"

    @staticmethod
    def _matching_users(obj: SignupBlock):
        """Аккаунты под правилом: по домену почты либо по IP регистрации.

        IP берём из audit.SignupDevice — это единственное место, где он
        сохраняется при регистрации.
        """
        if obj.kind == SignupBlock.KIND_DOMAIN and obj.value:
            # Поддомены тоже: @jmaie.com и @mail.jmaie.com.
            from django.db.models import Q

            return User.objects.filter(
                Q(email__iendswith=f"@{obj.value}") | Q(email__iendswith=f".{obj.value}")
            )

        from audit.models import SignupDevice

        devices = SignupDevice.objects.exclude(ip=None)
        if obj.kind == SignupBlock.KIND_IP:
            ids = devices.filter(ip=obj.value).values_list("user_id", flat=True)
        else:
            # Подсеть: сравнение делаем в питоне — БД про CIDR не знает.
            import ipaddress

            try:
                net = ipaddress.ip_network(obj.value, strict=False)
            except ValueError:
                return User.objects.none()
            ids = [
                d.user_id
                for d in devices.only("user_id", "ip")
                if d.ip and _ip_in(d.ip, net)
            ]
        return User.objects.filter(id__in=list(ids))

    @admin.action(description="Отключить аккаунты, попадающие под правило")
    def deactivate_matching_users(self, request, queryset):
        total = 0
        for obj in queryset:
            total += self._matching_users(obj).update(is_active=False)
        self.message_user(request, f"Отключено аккаунтов: {total}")

    @admin.action(description="Вернуть доступ аккаунтам под правилом")
    def activate_matching_users(self, request, queryset):
        total = 0
        for obj in queryset:
            total += self._matching_users(obj).update(is_active=True)
        self.message_user(request, f"Возвращён доступ: {total}")


def _ip_in(ip: str, net) -> bool:
    import ipaddress

    try:
        return ipaddress.ip_address(str(ip)) in net
    except ValueError:
        return False
