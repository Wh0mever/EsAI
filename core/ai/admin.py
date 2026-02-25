from django.contrib import admin, messages
from django.db import models
from django import forms
from django.http import HttpResponse
from django.utils.timezone import now
from django.urls import path, reverse
from django.shortcuts import redirect
from .actions import get_gpt_models_action, get_topmedia_models_action, ProviderConfigError
import json

from .models import (
    GPTModels,
    TopMediaModels,
    AiProvider,
    AiPromptTemplate,
    AiChatSession,
    AiChatMessage,
    AiGeneratedImage,
)

class JSONTextarea(forms.Textarea):
    def format_value(self, value):
        try:
            if isinstance(value, str):
                parsed = json.loads(value)
            else:
                parsed = value
            return json.dumps(parsed, ensure_ascii=False, indent=2)
        except Exception:
            return value


@admin.register(GPTModels)
class GPTModelsAdmin(admin.ModelAdmin):
    list_display = ('name', 'max_tokens', 'is_active', 'created_at', 'updated_at')

    def get_urls(self):
        urls = super().get_urls()
        app_label = self.model._meta.app_label
        model_name = self.model._meta.model_name
        custom = [
            path(
                "sync-models/",
                self.admin_site.admin_view(self.sync_models_view),
                name=f"{app_label}_{model_name}_sync",
            )
        ]
        return custom + urls

    def changelist_view(self, request, extra_context=None):
        extra_context = extra_context or {}
        app_label = self.model._meta.app_label
        model_name = self.model._meta.model_name
        extra_context["sync_url"] = reverse(f"admin:{app_label}_{model_name}_sync")
        return super().changelist_view(request, extra_context=extra_context)

    def sync_models_view(self, request):
        if not request.user.is_superuser:
            messages.error(request, "Недостаточно прав.")
            return redirect("..")
        if request.method != "POST":
            messages.error(request, "Метод не разрешён.")
            return redirect("..")
        try:
            get_gpt_models_action()
            messages.success(request, "Список GPT-моделей обновлен.")
        except ProviderConfigError as e:
            messages.error(request, str(e))
        except Exception as e:
            messages.error(request, f"Ошибка синхронизации GPT моделей: {e}")
        return redirect("..")


@admin.register(TopMediaModels)
class TopMediaModelsAdmin(admin.ModelAdmin):
    list_display = ('name', 'kind', 'max_tokens', 'is_active', 'created_at', 'updated_at')
    list_filter = ('kind', 'is_active')

    def get_urls(self):
        urls = super().get_urls()
        app_label = self.model._meta.app_label
        model_name = self.model._meta.model_name
        custom = [
            path(
                "sync-models/",
                self.admin_site.admin_view(self.sync_models_view),
                name=f"{app_label}_{model_name}_sync",
            )
        ]
        return custom + urls

    def changelist_view(self, request, extra_context=None):
        extra_context = extra_context or {}
        app_label = self.model._meta.app_label
        model_name = self.model._meta.model_name
        extra_context["sync_url"] = reverse(f"admin:{app_label}_{model_name}_sync")
        return super().changelist_view(request, extra_context=extra_context)

    def sync_models_view(self, request):
        if not request.user.is_superuser:
            messages.error(request, "Недостаточно прав.")
            return redirect("..")
        if request.method != "POST":
            messages.error(request, "Метод не разрешён.")
            return redirect("..")
        try:
            get_topmedia_models_action()
            messages.success(request, "Список TopMedia-моделей обновлен.")
        except ProviderConfigError as e:
            messages.error(request, str(e))
        except Exception as e:
            messages.error(request, f"Ошибка синхронизации TopMedia моделей: {e}")
        return redirect("..")

@admin.register(AiProvider)
class AiProviderAdmin(admin.ModelAdmin):
    list_display = ('name', 'slug', 'base_url', 'is_active', 'created_at', 'updated_at')
    search_fields = ('name', 'slug')
    list_filter = ('is_active',)
    ordering = ('-created_at',)
    readonly_fields = ('created_at', 'updated_at')

    def has_add_permission(self, request):
        return request.user.is_superuser

    def has_change_permission(self, request, obj=None):
        return request.user.is_superuser

    def has_delete_permission(self, request, obj=None):
        return request.user.is_superuser

@admin.register(AiPromptTemplate)
class AiPromptTemplateAdmin(admin.ModelAdmin):
    list_display = ('name', 'provider', 'is_active', 'is_public', 'created_by', 'created_at', 'updated_at')
    search_fields = ('name', 'provider__name')
    list_filter = ('is_active', 'is_public', 'provider')
    ordering = ('-created_at',)
    readonly_fields = ('created_at', 'updated_at')

class AiChatMessageInline(admin.TabularInline):
    model = AiChatMessage
    extra = 0
    can_delete = False
    show_change_link = True
    readonly_fields = ('role', 'content_preview', 'attachments_preview', 'meta_preview', 'created_at')
    fields = ('role', 'content_preview', 'attachments_preview', 'meta_preview', 'created_at')

    def content_preview(self, obj):
        if not obj.content:
            return '—'
        c = obj.content.strip()
        return c[:180] + ('…' if len(c) > 180 else '')

    def attachments_preview(self, obj):
        if not obj.attachments:
            return '—'
        s = json.dumps(obj.attachments, ensure_ascii=False)
        return s[:180] + ('…' if len(s) > 180 else '')

    def meta_preview(self, obj):
        if not obj.meta:
            return '—'
        s = json.dumps(obj.meta, ensure_ascii=False)
        return s[:160] + ('…' if len(s) > 160 else '')

@admin.register(AiChatSession)
class AiChatSessionAdmin(admin.ModelAdmin):
    list_display = ('id', 'uid', 'title', 'user', 'provider', 'messages_count', 'is_active', 'created_at', 'updated_at')
    search_fields = ('uid', 'title', 'user__email', 'user__username')
    list_filter = ('is_active', 'provider', 'created_at')
    ordering = ('-updated_at',)
    date_hierarchy = 'created_at'
    readonly_fields = ('created_at', 'updated_at')
    list_select_related = ('user', 'provider')
    inlines = (AiChatMessageInline,)
    actions = ('archive_sessions', 'unarchive_sessions', 'export_sessions_json')

    def messages_count(self, obj):
        return obj.messages.count()
    messages_count.short_description = 'Сообщений'

    def archive_sessions(self, request, queryset):
        queryset.update(is_active=False, updated_at=now())
    archive_sessions.short_description = 'Архивировать выбранные'

    def unarchive_sessions(self, request, queryset):
        queryset.update(is_active=True, updated_at=now())
    unarchive_sessions.short_description = 'Разархивировать выбранные'

    def export_sessions_json(self, request, queryset):
        payload = []
        qs = queryset.select_related('user', 'provider').prefetch_related('messages')
        for s in qs:
            payload.append({
                'id': s.id,
                'title': s.title,
                'user': {'id': s.user_id, 'email': getattr(s.user, 'email', None)},
                'provider': getattr(s.provider, 'slug', None),
                'created_at': s.created_at.isoformat() if s.created_at else None,
                'updated_at': s.updated_at.isoformat() if s.updated_at else None,
                'is_active': s.is_active,
                'messages': [
                    {
                        'id': m.id,
                        'role': m.role,
                        'content': m.content,
                        'attachments': m.attachments,
                        'meta': m.meta,
                        'created_at': m.created_at.isoformat() if m.created_at else None,
                    }
                    for m in s.messages.all().order_by('created_at')
                ],
            })
        data = json.dumps(payload, ensure_ascii=False, indent=2)
        resp = HttpResponse(data, content_type='application/json; charset=utf-8')
        resp['Content-Disposition'] = 'attachment; filename=ai_chat_sessions.json'
        return resp
    export_sessions_json.short_description = 'Экспортировать в JSON'

@admin.register(AiChatMessage)
class AiChatMessageAdmin(admin.ModelAdmin):
    list_display = ('id', 'session', 'role', 'short_content', 'created_at')
    search_fields = ('content', 'session__title', 'session__user__email')
    list_filter = ('role', 'created_at')
    ordering = ('-created_at',)
    date_hierarchy = 'created_at'
    list_select_related = ('session', 'session__user', 'session__provider')
    readonly_fields = ('created_at',)
    formfield_overrides = {
        models.JSONField: {'widget': JSONTextarea(attrs={'rows': 10, 'style': 'font-family:monospace'})},
    }

    def short_content(self, obj):
        if not obj.content:
            return '—'
        c = obj.content.strip()
        return c[:120] + ('…' if len(c) > 120 else '')
    short_content.short_description = 'Текст'


@admin.register(AiGeneratedImage)
class AiGeneratedImageAdmin(admin.ModelAdmin):
    list_display = ("id", "user", "session", "model_name", "size", "created_at", "preview")
    search_fields = ("prompt", "user__email", "model_name", "uniqid")
    list_filter = ("model_name", "size", "created_at")
    readonly_fields = ("created_at",)

    def preview(self, obj):
        try:
            if not obj.image:
                return "—"
            url = obj.image.url
            return f"<img src='{url}' style='max-height:60px;border-radius:6px'/>"
        except Exception:
            return "—"
    preview.allow_tags = True
    preview.short_description = "Preview"
