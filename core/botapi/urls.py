from django.urls import path

from .views import BotAuthView, BotBlockedView, BotPrefsView

app_name = "botapi"

urlpatterns = [
    path("auth/telegram/", BotAuthView.as_view(), name="auth-telegram"),
    path("prefs/", BotPrefsView.as_view(), name="prefs"),
    path("blocked/", BotBlockedView.as_view(), name="blocked"),
]
