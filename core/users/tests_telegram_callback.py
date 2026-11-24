"""Возврат от Telegram: своя страница-«прокладка» и обработчик поверх allauth (users/telegram_callback.py)."""
import base64
import hashlib
import hmac
import json
import time
from unittest import mock

from django.core.exceptions import PermissionDenied
from django.test import TestCase, override_settings

URL = "/api/users/accounts/telegram/login/callback/"
BOT_TOKEN = "123456:TEST-token-for-callback-tests"
PROVIDERS = {
    "telegram": {
        "APP": {"client_id": "123456", "secret": BOT_TOKEN, "key": ""},
        "AUTH_PARAMS": {"auth_date_validity": 30},
    }
}


def signed_result(**extra) -> str:
    """tgAuthResult, подписанный токеном бота так же, как это делает Telegram."""
    data = {"id": 777000111, "first_name": "Probe", "auth_date": int(time.time()), **extra}
    payload = "\n".join(sorted(f"{k}={v}" for k, v in data.items()))
    secret = hashlib.sha256(BOT_TOKEN.encode()).digest()
    data["hash"] = hmac.new(secret, payload.encode(), hashlib.sha256).hexdigest()
    return base64.b64encode(json.dumps(data).encode()).decode().rstrip("=")


@override_settings(SOCIALACCOUNT_PROVIDERS=PROVIDERS)
class TelegramCallbackTests(TestCase):
    def test_get_renders_own_page_without_external_script(self):
        r = self.client.get(URL + "?state=abc")
        self.assertEqual(r.status_code, 200)
        html = r.content.decode()
        self.assertIn('name="tgAuthResult"', html)
        self.assertIn("Входим через Telegram", html)
        # Внешний файл режут блокировщики — его на странице быть не должно.
        self.assertNotIn("/static/telegram/js/telegram.js", html)

    def test_post_without_result_goes_back_to_signin(self):
        # Раньше allauth падал на len(None) — 500.
        r = self.client.post(URL + "?state=abc", {})
        self.assertEqual(r.status_code, 302)
        self.assertTrue(r["Location"].endswith("/auth/signin?error=social_login_failed"), r["Location"])

    def test_used_state_is_not_bare_403(self):
        # Подпись верная, но state не найден в сессии (ссылку открыли повторно) — allauth давал 403.
        r = self.client.post(URL + "?state=not-stashed", {"tgAuthResult": signed_result()})
        self.assertEqual(r.status_code, 302)
        self.assertTrue(r["Location"].endswith("/auth/signin?error=social_login_failed"), r["Location"])

    def test_used_state_right_after_login_sends_tokens(self):
        with mock.patch("users.telegram_callback._just_logged_in_via", return_value=True):
            r = self.client.post(URL + "?state=not-stashed", {"tgAuthResult": signed_result()})
        self.assertEqual(r.status_code, 302)
        self.assertEqual(r["Location"], "/api/users/auth/complete/")

    def test_permission_denied_from_allauth_is_caught(self):
        with mock.patch(
            "allauth.socialaccount.providers.telegram.views.CallbackView.post",
            side_effect=PermissionDenied,
        ):
            r = self.client.post(URL + "?state=x", {"tgAuthResult": "eyJ4IjoxfQ"})
        self.assertEqual(r.status_code, 302)
        self.assertIn("/auth/signin?error=social_login_failed", r["Location"])
