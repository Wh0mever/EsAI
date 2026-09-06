from django.urls import path
from django.urls import include
from django.contrib import admin
from django.conf import settings
from django.conf.urls.static import static
urlpatterns = [
    path('admin/', admin.site.urls),
    path('api/users/', include('users.urls')),
    path('api/content/', include('content.urls')),
    path('api/mails/', include('mails.urls')),
    path('api/ai/', include('ai.urls')),
    path('api/plans/', include('plans.urls')),
    path('api/payments/', include('payments.urls')),
    path('api/manage/', include('adminapi.urls')),
    path('api/bot/', include('botapi.urls')),
    path('api/cartoon/', include('cartoon.urls')),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL,
                          document_root=settings.MEDIA_ROOT)
