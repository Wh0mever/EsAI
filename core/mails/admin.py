from django.contrib import admin, messages
from django.utils.safestring import mark_safe
from django.utils import timezone
from .models import MailContext, SimpleMail
from .services import render_simple_mail_html
from .tasks import send_simple_mail_task


# legacy admin removed


# ===== Simplified mailer admin =====

@admin.register(MailContext)
class MailContextAdmin(admin.ModelAdmin):
    list_display = ("name", "updated_at")
    search_fields = ("name",)
    readonly_fields = ("updated_at", "preview")
    fields = ("name", "data", "preview", "updated_at")

    @admin.display(description="Preview")
    def preview(self, obj: MailContext):
        # Temporary SimpleMail for preview
        temp = SimpleMail(name="preview", subject="Preview", context=obj)
        html = render_simple_mail_html(temp)
        return mark_safe(f'<div style="border:1px solid #ddd;padding:12px">{html}</div>')


@admin.register(SimpleMail)
class SimpleMailAdmin(admin.ModelAdmin):
    list_display = ("name", "subject", "send_to_all", "recipients_count", "last_sent_at", "created_at")
    list_filter = ("send_to_all",)
    search_fields = ("name", "subject", "recipients__email")
    readonly_fields = ("created_at", "last_sent_at", "rendered_preview")
    filter_horizontal = ("recipients",)
    actions = ("send_now", "send_test_to_me", "send_now_sync", "send_test_to_me_sync")

    fieldsets = (
        (None, {"fields": ("name", "subject", "context", "rendered_preview")}),
        ("Recipients", {"fields": ("send_to_all", "recipients")}),
        ("Meta", {"fields": ("created_at", "last_sent_at")}),
    )

    @admin.display(description="Preview")
    def rendered_preview(self, obj: SimpleMail):
        html = render_simple_mail_html(obj)
        return mark_safe(f'<div style="border:1px solid #ddd;padding:12px">{html}</div>')

    @admin.action(description="Отправить сейчас (асинхронно)")
    def send_now(self, request, queryset):
        queued = 0
        for mail in queryset:
            send_simple_mail_task.delay(mail.id)
            queued += 1
        if queued:
            self.message_user(request, f"Поставлено в очередь задач: {queued}")

    @admin.action(description="Отправить тест себе (асинхронно)")
    def send_test_to_me(self, request, queryset):
        me = getattr(request.user, "email", "")
        if not me:
            self.message_user(request, "У вашего аккаунта нет email", level=messages.ERROR)
            return
        queued = 0
        for mail in queryset:
            send_simple_mail_task.delay(mail.id, test_to=me)
            queued += 1
        if queued:
            self.message_user(request, f"Поставлено в очередь тестовых задач: {queued}")

    @admin.action(description="Отправить сейчас (синхронно)")
    def send_now_sync(self, request, queryset):
        from .services import send_simple_mail
        total = 0
        for mail in queryset:
            try:
                sent = send_simple_mail(mail)
                mail.last_sent_at = timezone.now()
                mail.save(update_fields=["last_sent_at"])
                total += sent
            except Exception as e:
                self.message_user(request, f"Ошибка: {e}", level=messages.ERROR)
        if total:
            self.message_user(request, f"Отправлено: {total}")

    @admin.action(description="Отправить тест себе (синхронно)")
    def send_test_to_me_sync(self, request, queryset):
        from .services import send_simple_mail
        me = getattr(request.user, "email", "")
        if not me:
            self.message_user(request, "У вашего аккаунта нет email", level=messages.ERROR)
            return
        total = 0
        for mail in queryset:
            try:
                sent = send_simple_mail(mail, test_to=me)
                total += sent
            except Exception as e:
                self.message_user(request, f"Ошибка: {e}", level=messages.ERROR)
        if total:
            self.message_user(request, f"Тестовые письма отправлены: {total}")

    @admin.display(description="Получателей")
    def recipients_count(self, obj: SimpleMail) -> int:
        return obj.recipients.count()
