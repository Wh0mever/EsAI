"""Возврат с oauth.telegram.org (вход через Telegram, allauth) — надёжнее штатного.

Штатный CallbackView allauth:
  GET  — страница-«прокладка»: скрипт /static/telegram/js/telegram.js переносит
         tgAuthResult из #фрагмента в POST-форму;
  POST — проверка подписи, вход.

Что меняем (замечание клиента 24.11 «вход через ТГ поломался»):
  1) Страница своя (templates/telegram/callback.html): скрипт прямо в странице.
     Файл с «telegram» в адресе режут блокировщики — в Chrome у клиента вход
     висел на пустой белой странице 7 раз из 7, POST до сервера не доходил.
     Плюс видимый текст «Входим…» и кнопка «Продолжить», если не ушло само.
  2) Telegram вернул без tgAuthResult (вход отменили) — allauth падал на len(None)
     с 500. Теперь — назад ко входу с ошибкой.
  3) Ссылка уже использована (назад/обновили после входа, webview грузит дважды)
     — allauth отвечал голым «403 Forbidden» (state не найден). Теперь — как в
     SocialAccountAdapter.on_authentication_error: если эта сессия только что
     вошла через Telegram, досылаем токены (auth-complete), иначе — ко входу.
"""
from allauth.socialaccount.providers.telegram.views import CallbackView
from django.core.exceptions import PermissionDenied
from django.http import HttpResponseRedirect
from django.urls import reverse

from .adapters import _frontend_base_from_request, _just_logged_in_via

PROVIDER_ID = "telegram"


def _back_to_signin(request):
    return HttpResponseRedirect(f"{_frontend_base_from_request(request)}/auth/signin?error=social_login_failed")


class TelegramCallbackView(CallbackView):
    """GET — страница из templates/telegram/callback.html (шаблон проекта перекрывает allauth)."""

    def post(self, request):
        if not (request.POST.get("tgAuthResult") or "").strip():
            return _back_to_signin(request)
        try:
            return super().post(request)
        except PermissionDenied:
            if _just_logged_in_via(request, PROVIDER_ID):
                return HttpResponseRedirect(reverse("auth-complete"))
            return _back_to_signin(request)


telegram_callback = TelegramCallbackView.as_view()
