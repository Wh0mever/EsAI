from django.contrib import admin
from .models import BlogPost


@admin.register(BlogPost)
class BlogAdmin(admin.ModelAdmin):
    list_display = ('title_ru', 'title_kg', 'title_en')
    
    
admin.site.site_header = "Vokalo Admin"
admin.site.site_title = "Панель управления"
