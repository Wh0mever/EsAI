from django.urls import path

from .views import StartBindCardAPIView, FreedomPayCallbackAPIView

urlpatterns = [
    path('card/bind/start/', StartBindCardAPIView.as_view(), name='card-bind-start'),
    path('card/bind/callback/', FreedomPayCallbackAPIView.as_view(), name='card-bind-callback'),
]
