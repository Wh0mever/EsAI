from django.urls import path
from django.urls import include

urlpatterns = [
    path('api/admin/', include('admin.urls')),
    path('api/users/', include('users.urls')),
    path('api/content/', include('content.urls')),
    path('api/mails/', include('mails.urls')),
    path('api/', include('api.urls')),
]
