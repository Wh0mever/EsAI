# -*- coding: utf-8 -*-
"""Тесты бота: подпись сервисных запросов, общий аккаунт с сайтом, уведомления.

Сеть не трогаем — Telegram подменяется заглушкой. Кэш у тестов свой: прогон в
боевом контейнере однажды положил в общий Redis тестовые данные, и люди
десять минут видели их вместо настоящих.
"""
import hashlib
import hmac
import json
import time
import uuid
from unittest.mock import patch

from allauth.socialaccount.models import SocialAccount
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from .auth import sign
from .models import TelegramChat
from .telegram import verify_webapp_init_data

TEST_CACHES = {"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache",
                           "LOCATION": "botapi-tests"}}
SECRET = "bot-service-secret-for-tests"
BOT_TOKEN = "123456789:TEST-TOKEN-VALUE"
AUTH_PATH = "/api/bot/auth/telegram/"


def tg_user(uid=555001, **over):
    data = {"id": uid, "first_name": "Иван", "last_name": "Петров",
            "username": "ivan", "language_code": "ru"}
    data.update(over)
    return data


def signed_post(body, *, secret=SECRET, ts=None, path=AUTH_PATH, tamper=False,
                client=None, nonce=None):
    raw = json.dumps(body).encode()
    ts = str(ts if ts is not None else int(time.time()))
    nonce = nonce or uuid.uuid4().hex
    signature = sign(secret, ts, nonce, "POST", path, raw)
    if tamper:
        signature = ("0" if signature[0] != "0" else "1") + signature[1:]
    return (client or APIClient()).post(
        path, data=raw, content_type="application/json",
        HTTP_X_BOT_TS=ts, HTTP_X_BOT_NONCE=nonce, HTTP_X_BOT_SIG=signature)


@override_settings(CACHES=TEST_CACHES, BOT_SERVICE_SECRET=SECRET,
                   TELEGRAM_PRODUCT_BOT_TOKEN=BOT_TOKEN)
class ServiceSignatureTests(TestCase):
    """Подписанный запрос принимается один раз, подделанный — никогда."""

    def setUp(self):
        cache.clear()

    def test_valid_signature_passes(self):
        response = signed_post({"telegram_user": tg_user()})
        self.assertEqual(response.status_code, 200, response.data)

    def test_tampered_signature_rejected(self):
        self.assertEqual(
            signed_post({"telegram_user": tg_user()}, tamper=True).status_code, 401)

    def test_wrong_secret_rejected(self):
        self.assertEqual(
            signed_post({"telegram_user": tg_user()}, secret="chuzhoy").status_code, 401)

    def test_stale_request_rejected(self):
        old = int(time.time()) - 3600
        self.assertEqual(
            signed_post({"telegram_user": tg_user()}, ts=old).status_code, 401)

    def test_body_cannot_be_swapped(self):
        """Подпись считается по телу: чужое тело с чужой подписью не пройдёт."""
        raw = json.dumps({"telegram_user": tg_user()}).encode()
        ts = str(int(time.time()))
        nonce = uuid.uuid4().hex
        signature = sign(SECRET, ts, nonce, "POST", AUTH_PATH, raw)
        other = json.dumps({"telegram_user": tg_user(999)}).encode()
        response = APIClient().post(
            AUTH_PATH, data=other, content_type="application/json",
            HTTP_X_BOT_TS=ts, HTTP_X_BOT_NONCE=nonce, HTTP_X_BOT_SIG=signature)
        self.assertEqual(response.status_code, 401)

    def test_replay_rejected(self):
        """Перехваченный запрос нельзя повторить, а честный повтор — можно."""
        raw = json.dumps({"telegram_user": tg_user()}).encode()
        ts = str(int(time.time()))
        nonce = uuid.uuid4().hex
        signature = sign(SECRET, ts, nonce, "POST", AUTH_PATH, raw)
        kwargs = dict(data=raw, content_type="application/json",
                      HTTP_X_BOT_TS=ts, HTTP_X_BOT_NONCE=nonce, HTTP_X_BOT_SIG=signature)
        self.assertEqual(APIClient().post(AUTH_PATH, **kwargs).status_code, 200)
        self.assertEqual(APIClient().post(AUTH_PATH, **kwargs).status_code, 401)

    def test_same_request_twice_is_fine_with_new_nonce(self):
        """Два быстрых /start подряд — обычное дело, а не атака."""
        body = {"telegram_user": tg_user()}
        self.assertEqual(signed_post(body).status_code, 200)
        self.assertEqual(signed_post(body).status_code, 200)

    @override_settings(BOT_SERVICE_SECRET="")
    def test_without_secret_endpoint_is_closed(self):
        self.assertEqual(signed_post({"telegram_user": tg_user()}).status_code, 401)


@override_settings(CACHES=TEST_CACHES, BOT_SERVICE_SECRET=SECRET,
                   TELEGRAM_PRODUCT_BOT_TOKEN=BOT_TOKEN, WELCOME_BONUS_TOKENS=3)
class TelegramAccountTests(TestCase):
    """Бот и сайт видят одного человека и один баланс."""

    def setUp(self):
        cache.clear()

    def _auth(self, user_data=None, **extra):
        return signed_post({"telegram_user": user_data or tg_user(), **extra})

    def test_new_user_gets_account_and_welcome_bonus(self):
        response = self._auth()
        self.assertEqual(response.status_code, 200, response.data)
        self.assertTrue(response.data["created"])
        self.assertTrue(response.data["access"])

        user = get_user_model().objects.get(email="telegram_555001@social.esai.local")
        self.assertEqual(user.telegram, "ivan")
        self.assertTrue(
            SocialAccount.objects.filter(provider="telegram", uid="555001").exists())
        self.assertEqual(response.data["user"]["balance_tokens"], user.token_balance)
        self.assertGreater(user.token_balance, 0, "приветственный бонус не начислен")

    def test_same_telegram_id_is_same_account(self):
        """Второй /start не заводит второго человека — иначе балансы разъедутся."""
        first = self._auth()
        second = self._auth()
        self.assertTrue(first.data["created"])
        self.assertFalse(second.data["created"])
        self.assertEqual(first.data["user"]["id"], second.data["user"]["id"])
        self.assertEqual(get_user_model().objects.count(), 1)

    def test_account_from_site_login_is_reused(self):
        """Кто входил на сайте через Telegram — в боте тот же, с тем же балансом."""
        user = get_user_model().objects.create_user(
            email="telegram_555001@social.esai.local", password="x")
        user.token_balance = 250
        user.save(update_fields=["token_balance"])
        SocialAccount.objects.create(
            user=user, provider="telegram", uid="555001", extra_data={})

        response = self._auth()
        self.assertFalse(response.data["created"])
        self.assertEqual(response.data["user"]["id"], user.pk)
        self.assertEqual(response.data["user"]["balance_tokens"], 250)

    def test_chat_is_remembered_for_notifications(self):
        self._auth(chat_id=777)
        chat = TelegramChat.objects.get(telegram_id=555001)
        self.assertEqual(chat.chat_id, 777)
        self.assertEqual(chat.lang, "ru")
        self.assertTrue(chat.notify_bonus)

    def test_language_comes_from_telegram_but_user_choice_wins(self):
        self._auth(tg_user(language_code="ky-KG"))
        chat = TelegramChat.objects.get(telegram_id=555001)
        self.assertEqual(chat.lang, "kg")
        chat.lang = "en"
        chat.save(update_fields=["lang"])
        self._auth(tg_user(language_code="ky-KG"))
        chat.refresh_from_db()
        self.assertEqual(chat.lang, "en", "выбор человека затёрли настройками телефона")

    def test_referrer_is_linked_from_deep_link(self):
        referrer = get_user_model().objects.create_user(email="ref@example.com", password="x")
        referrer.referral_uid = "AB12CD34"
        referrer.save(update_fields=["referral_uid"])

        self._auth(ref="AB12CD34")
        invited = get_user_model().objects.get(email="telegram_555001@social.esai.local")
        self.assertEqual(invited.referred_by_id, referrer.pk)

    def test_referrer_cannot_be_attached_to_old_account(self):
        """Разослать ссылку старым пользователям и снимать с них процент нельзя."""
        from datetime import timedelta

        from django.utils import timezone

        user = get_user_model().objects.create_user(
            email="telegram_555001@social.esai.local", password="x")
        get_user_model().objects.filter(pk=user.pk).update(
            date_joined=timezone.now() - timedelta(days=30))
        SocialAccount.objects.create(
            user=user, provider="telegram", uid="555001", extra_data={})
        referrer = get_user_model().objects.create_user(email="ref@example.com", password="x")
        referrer.referral_uid = "AB12CD34"
        referrer.save(update_fields=["referral_uid"])

        self._auth(ref="AB12CD34")
        user.refresh_from_db()
        self.assertIsNone(user.referred_by_id)

    def test_blocked_user_cannot_enter(self):
        from users.models import SignupBlock

        SignupBlock.objects.create(kind="device", value="tg:555001", block_login=True)
        self.assertEqual(self._auth().status_code, 403)

    def test_inactive_account_cannot_enter(self):
        user = get_user_model().objects.create_user(
            email="telegram_555001@social.esai.local", password="x", is_active=False)
        SocialAccount.objects.create(
            user=user, provider="telegram", uid="555001", extra_data={})
        self.assertEqual(self._auth().status_code, 403)

    def test_bad_payload_rejected(self):
        self.assertEqual(self._auth({"first_name": "bez id"}).status_code, 400)


@override_settings(CACHES=TEST_CACHES, TELEGRAM_PRODUCT_BOT_TOKEN=BOT_TOKEN)
class WebAppInitDataTests(TestCase):
    """Mini App: доверяем только тому, что подписано токеном бота."""

    def setUp(self):
        cache.clear()

    @staticmethod
    def _init_data(token=BOT_TOKEN, auth_date=None, user=None):
        payload = {
            "auth_date": str(auth_date or int(time.time())),
            "query_id": "AAF",
            "user": json.dumps(user or tg_user(), separators=(",", ":")),
        }
        check = "\n".join(f"{k}={payload[k]}" for k in sorted(payload))
        secret = hmac.new(b"WebAppData", token.encode(), hashlib.sha256).digest()
        payload["hash"] = hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()
        return "&".join(f"{k}={v}" for k, v in payload.items())

    def test_valid_init_data_accepted(self):
        parsed = verify_webapp_init_data(self._init_data())
        self.assertIsNotNone(parsed)
        self.assertEqual(parsed["id"], 555001)

    def test_foreign_token_rejected(self):
        self.assertIsNone(verify_webapp_init_data(self._init_data(token="1:CHUZHOY")))

    def test_expired_init_data_rejected(self):
        old = int(time.time()) - 7200
        self.assertIsNone(verify_webapp_init_data(self._init_data(auth_date=old), max_age=3600))

    def test_tampered_user_rejected(self):
        data = self._init_data()
        self.assertIsNone(verify_webapp_init_data(data.replace("555001", "555002")))

    def test_login_endpoint_gives_tokens_once(self):
        url = "/api/users/auth/telegram/webapp/"
        data = self._init_data()
        first = APIClient().post(url, {"init_data": data}, format="json")
        self.assertEqual(first.status_code, 200, first.data)
        self.assertTrue(first.data["access"] and first.data["refresh"])
        second = APIClient().post(url, {"init_data": data}, format="json")
        self.assertEqual(second.status_code, 401, "один и тот же initData принят дважды")


@override_settings(CACHES=TEST_CACHES, TELEGRAM_PRODUCT_BOT_TOKEN=BOT_TOKEN,
                   TELEGRAM_NOTIFY_ENABLED=True, CELERY_TASK_ALWAYS_EAGER=True)
class NotifyTests(TestCase):
    """Сообщения уходят тем, кто их ждёт, и не уходят заблокировавшим бота."""

    def setUp(self):
        self.user = get_user_model().objects.create_user(email="tg@example.com", password="x")
        self.chat = TelegramChat.objects.create(
            user=self.user, telegram_id=555001, chat_id=555001, lang="ru")

    def test_message_is_sent(self):
        from .tasks import notify_user_telegram

        with patch("botapi.tasks.tg_api") as api:
            notify_user_telegram(self.user.pk, "topup", "gotovo")
        self.assertEqual(api.call_args.args[0], "sendMessage")
        self.assertEqual(api.call_args.kwargs["chat_id"], 555001)

    def test_disabled_kind_is_skipped(self):
        self.chat.notify_bonus = False
        self.chat.save(update_fields=["notify_bonus"])
        from .tasks import notify_user_telegram

        with patch("botapi.tasks.tg_api") as api:
            result = notify_user_telegram(self.user.pk, "bonus", "bonus")
        self.assertEqual(result, "skipped")
        api.assert_not_called()

    def test_blocked_chat_is_marked_and_not_retried(self):
        from .tasks import send_telegram_message
        from .telegram import TelegramError

        with patch("botapi.tasks.tg_api",
                   side_effect=TelegramError("Forbidden: bot was blocked by the user",
                                             code=403, blocked=True)):
            result = send_telegram_message(555001, "privet")
        self.assertEqual(result, "blocked")
        self.chat.refresh_from_db()
        self.assertTrue(self.chat.is_blocked)

    def test_nothing_is_sent_without_token(self):
        from .tasks import notify_user_telegram

        with override_settings(TELEGRAM_PRODUCT_BOT_TOKEN=""):
            with patch("botapi.tasks.tg_api") as api:
                result = notify_user_telegram(self.user.pk, "topup", "gotovo")
        self.assertEqual(result, "disabled")
        api.assert_not_called()

    def test_broadcast_skips_blocked_and_paces_sending(self):
        from .tasks import broadcast_telegram

        other = get_user_model().objects.create_user(email="tg2@example.com", password="x")
        TelegramChat.objects.create(user=other, telegram_id=555002, chat_id=555002,
                                    lang="ru", is_blocked=True)
        with patch("botapi.tasks.send_telegram_message.apply_async") as send:
            result = broadcast_telegram("bonus", {"ru": "bonus"}, None)
        self.assertEqual(result["queued"], 1)
        self.assertEqual(send.call_args.kwargs["countdown"], 0)
