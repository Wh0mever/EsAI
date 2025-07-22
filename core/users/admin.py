from django.contrib import admin
from .models import User

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
