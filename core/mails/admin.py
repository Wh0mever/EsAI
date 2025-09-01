from django.contrib import admin, messages
from django.utils.safestring import mark_safe
from django.utils import timezone
from django import forms

from .models import EmailTemplate, EmailCampaign, EmailLog, EmailPreference
from .services import run_campaign_now, render_body_from_db_template, render_subject


class EmailTemplateAdmin(admin.ModelAdmin):
    list_display = ("name", "key", "is_active", "updated_at")
    list_filter = ("is_active",)
    search_fields = ("name", "key", "subject")
    readonly_fields = ("preview_subject", "preview_html")

    class PreviewForm(forms.ModelForm):
        preview_context = forms.JSONField(required=False, initial={}, help_text="Optional preview context")

        class Meta:
            model = EmailTemplate
            fields = "__all__"

    form = PreviewForm

    def preview_subject(self, obj):
        context = self.get_form(request=None).base_fields["preview_context"].initial or {}
        try:
            return render_subject(obj.subject, context)
        except Exception:
            return obj.subject
    preview_subject.short_description = "Preview subject"

    def preview_html(self, obj):
        try:
            html, _ = render_body_from_db_template(obj, {})
        except Exception as e:
            return f"Render error: {e}"
        return mark_safe(f'<div style="border:1px solid #ddd;padding:12px">{html}</div>')
    preview_html.short_description = "Preview HTML"


@admin.register(EmailCampaign)
class EmailCampaignAdmin(admin.ModelAdmin):
    list_display = ("title", "template", "status", "scheduled_at", "last_run_at", "created_at")
    list_filter = ("status", "scheduled_at", "created_at")
    search_fields = ("title",)
    filter_horizontal = ("groups",)
    readonly_fields = ("last_run_at",)
    actions = ["action_send_now", "action_mark_draft"]

    fieldsets = (
        (None, {
            "fields": ("title", "template", "context_json", "from_email"),
        }),
        ("Audience", {
            "fields": ("groups", "extra_recipients"),
        }),
        ("Schedule", {
            "fields": ("status", "scheduled_at", "last_run_at"),
        }),
        ("Meta", {
            "fields": ("created_by",),
        }),
    )

    def save_model(self, request, obj, form, change):
        if not obj.created_by_id:
            obj.created_by = request.user
        super().save_model(request, obj, form, change)

    @admin.action(description="Запустить отправку сейчас (синхронно)")
    def action_send_now(self, request, queryset):
        total = 0
        for campaign in queryset:
            try:
                sent = run_campaign_now(campaign)
                campaign.status = EmailCampaign.Status.SENT
                campaign.last_run_at = timezone.now()
                campaign.save(update_fields=["status", "last_run_at"])
                total += sent
            except Exception as e:
                campaign.status = EmailCampaign.Status.FAILED
                campaign.last_run_at = timezone.now()
                campaign.save(update_fields=["status", "last_run_at"])
                self.message_user(request, f"{campaign.title}: ошибка {e}", level=messages.ERROR)
        if total:
            self.message_user(request, f"Отправлено писем: {total}", level=messages.SUCCESS)

    @admin.action(description="Перевести в черновик")
    def action_mark_draft(self, request, queryset):
        updated = queryset.update(status=EmailCampaign.Status.DRAFT)
        self.message_user(request, f"Обновлено: {updated}", level=messages.SUCCESS)


@admin.register(EmailTemplate)
class _EmailTemplateAdmin(EmailTemplateAdmin):
    pass


@admin.register(EmailLog)
class EmailLogAdmin(admin.ModelAdmin):
    list_display = ("to_email", "subject", "success", "sent_at", "campaign")
    list_filter = ("success", "sent_at")
    search_fields = ("to_email", "subject", "error")


@admin.register(EmailPreference)
class EmailPreferenceAdmin(admin.ModelAdmin):
    list_display = ("user", "is_unsubscribed", "unsubscribed_at")
    list_filter = ("is_unsubscribed",)
    search_fields = ("user__email", "user__username")
