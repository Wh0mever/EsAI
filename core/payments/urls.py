from django.urls import path, include

from .views import StartBindCardAPIView, FreedomPayCallbackAPIView

urlpatterns = [
    path('api/card/bind/start/', StartBindCardAPIView.as_view(), name='card-bind-start'),
    path('api/card/bind/callback/', FreedomPayCallbackAPIView.as_view(), name='card-bind-callback'),
]
