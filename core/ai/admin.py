from django.contrib import admin
from .models import AiProvider, AiPromptTemplate


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

    
    