from django.urls import path, re_path
from rest_framework.routers import DefaultRouter
from .views import UniversalModelViewSet, UniversalFieldsOptionsApiView, AppsMapApiView

# router = DefaultRouter()
# router.register(r'model/(?P<app_name>\w+)/(?P<model_name>\w+)', UniversalModelViewSet, basename='admin-api')
# urlpatterns = router.urls

urlpatterns = [
    path(
        '<str:app_name>/<str:model_name>/',
        UniversalModelViewSet.as_view({
            'get': 'list',
            'post': 'create',
        }),
        name='admin-api'
    ),

    path(
        '<str:app_name>/<str:model_name>/<int:pk>/',
        UniversalModelViewSet.as_view({
            'get': 'retrieve',
            'put': 'update',
            'patch': 'partial_update',
            'delete': 'destroy'
        }),
        name='admin-api-detail'
    ),

    path('apps/', AppsMapApiView.as_view(), name='admin-apps'),
    path('fields/<str:app_name>/<str:model_name>/', UniversalFieldsOptionsApiView.as_view(), name='fields-options'),
]
