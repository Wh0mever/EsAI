from django.contrib import admin
from .models import BlogPost, SiteSettings, PageSeo


@admin.register(BlogPost)
class BlogAdmin(admin.ModelAdmin):
    list_display = ('title_ru', 'slug', 'author', 'is_published', 'published_at', 'updated_at')
    list_filter = ('is_published', 'created_at', 'author')
    search_fields = ('title_ru', 'title_en', 'title_kg', 'slug', 'content_ru')
    list_editable = ('is_published',)
    prepopulated_fields = {'slug': ('title_en',)}
    readonly_fields = ('created_at', 'updated_at')
    date_hierarchy = 'created_at'
    actions = ('make_published', 'make_unpublished')
    fieldsets = (
        ('Заголовки', {
            'fields': ('title_ru', 'title_en', 'title_kg', 'slug'),
        }),
        ('Контент', {
            'fields': ('excerpt', 'content_ru', 'content_en', 'content_kg'),
        }),
        ('Медиа', {
            'fields': ('image', 'cover', 'cover_url'),
        }),
        ('SEO', {
            'fields': ('meta_title', 'meta_description'),
        }),
        ('Публикация', {
            'fields': ('author', 'is_published', 'published_at', 'created_at', 'updated_at'),
        }),
    )

    def make_published(self, request, queryset):
        for post in queryset:
            post.is_published = True
            post.save()
    make_published.short_description = 'Опубликовать выбранные'

    def make_unpublished(self, request, queryset):
        queryset.update(is_published=False)
    make_unpublished.short_description = 'Снять с публикации'


@admin.register(SiteSettings)
class SiteSettingsAdmin(admin.ModelAdmin):
    list_display = ('site_name', 'contact_email', 'contact_phone', 'updated_at')
    readonly_fields = ('created_at', 'updated_at')
    fieldsets = (
        ('Общее', {
            'fields': ('site_name', 'logo', 'favicon'),
        }),
        ('Контакты', {
            'fields': ('contact_email', 'contact_phone', 'social_links'),
        }),
        ('Тексты', {
            'fields': ('footer_text', 'support_text', 'error_text'),
        }),
        ('Служебное', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',),
        }),
    )

    def has_add_permission(self, request):
        # Синглтон: запретить создание второй записи.
        return not SiteSettings.objects.exists()

    def has_delete_permission(self, request, obj=None):
        return False

    def changelist_view(self, request, extra_context=None):
        # Гарантируем существование единственной записи для редактирования.
        SiteSettings.get_solo()
        return super().changelist_view(request, extra_context=extra_context)


@admin.register(PageSeo)
class PageSeoAdmin(admin.ModelAdmin):
    list_display = ('path', 'title', 'robots', 'updated_at')
    search_fields = ('path', 'title', 'description', 'keywords')
    readonly_fields = ('created_at', 'updated_at')
    fieldsets = (
        (None, {
            'fields': ('path', 'title', 'description', 'keywords'),
        }),
        ('Open Graph', {
            'fields': ('og_title', 'og_description', 'og_image'),
        }),
        ('Прочее', {
            'fields': ('canonical', 'robots', 'created_at', 'updated_at'),
        }),
    )


admin.site.site_header = "EsAI Admin"
admin.site.site_title = "EsAI"
admin.site.index_title = "EsAI"
