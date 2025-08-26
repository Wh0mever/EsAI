from django.contrib import admin
from .models import User, UserQuestions

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