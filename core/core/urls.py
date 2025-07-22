from django.urls import path
from django.urls import include
from django.contrib import admin    

urlpatterns = [
    path('admin/', admin.site.urls),
    path('api/users/', include('users.urls')),
    path('api/content/', include('content.urls')),
    path('api/mails/', include('mails.urls')),
    path('api/ai/', include('ai.urls')),
]
