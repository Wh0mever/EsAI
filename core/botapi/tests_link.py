# -*- coding: utf-8 -*-
"""Привязка Telegram к аккаунту сайта, слияние заглушки, отвязка."""
from unittest.mock import patch

from allauth.socialaccount.models import SocialAccount
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from plans.wallet import credit_tokens

from .linking import LinkError, confirm_link, forget_telegram, is_stub, start_link
from .models import TelegramChat
from .services import authenticate_telegram_user
from .tests import SECRET, signed_post, tg_user

TEST_CACHES = {"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache",
                           "LOCATION": "link-tests"}}
TG = 700100


def _site_user(email="site@example.com"):
    return get_user_model().objects.create_user(email=email, password="secret123")


@override_settings(CACHES=TEST_CACHES, BOT_SERVICE_SECRET=SECRET,
                   TELEGRAM_PRODUCT_BOT_TOKEN="1:x", TELEGRAM_PRODUCT_BOT_USERNAME="esai_bot",
                   WELCOME_BONUS_TOKENS=50)
class LinkTests(TestCase):
    def setUp(self):
        cache.clear()

    def test_fresh_telegram_is_linked(self):
        target = _site_user()
        code = start_link(target)["code"]
        status, user = confirm_link(code, tg_user(TG, username="ivan"), chat_id=TG)
        self.assertEqual(status, "linked")
        self.assertEqual(user.pk, target.pk)
        self.assertTrue(SocialAccount.objects.filter(user=target, provider="telegram", uid=str(TG)).exists())
        chat = TelegramChat.objects.get(user=target)
        self.assertEqual(chat.telegram_id, TG)
        self.assertEqual(chat.source, "link")
        target.refresh_from_db()
        self.assertEqual(target.telegram, "ivan")
        # Код одноразовый.
        with self.assertRaises(LinkError):
            confirm_link(code, tg_user(TG))

    def test_stub_is_merged_without_gifts(self):
        # Человек писал боту раньше: заглушка с приветственным бонусом и покупкой.
        stub, created = authenticate_telegram_user(tg_user(TG), chat_id=TG)
        self.assertTrue(created and is_stub(stub))
        credit_tokens(stub, 100, "purchase", meta={"order_id": "x"})
        from ai.models import AiChatSession

        AiChatSession.objects.create(user=stub, title="старый чат")
        stub.refresh_from_db()
        gifted = stub.token_balance - 100

        target = _site_user()
        target.token_balance = 7
        target.save(update_fields=["token_balance"])
        status, user = confirm_link(start_link(target)["code"], tg_user(TG), chat_id=TG)
        self.assertEqual(status, "merged")
        target.refresh_from_db()
        stub.refresh_from_db()
        self.assertEqual(target.token_balance, 107)
        self.assertEqual(stub.token_balance, 0)
        self.assertFalse(stub.is_active)
        self.assertTrue(stub.email.startswith("merged_"))
        self.assertGreaterEqual(gifted, 0)
        self.assertEqual(AiChatSession.objects.get(title="старый чат").user_id, target.pk)
        self.assertEqual(SocialAccount.objects.get(provider="telegram", uid=str(TG)).user_id, target.pk)
        self.assertEqual(TelegramChat.objects.get(telegram_id=TG).user_id, target.pk)
        # Следующий вход из бота попадает уже в аккаунт сайта.
        again, created = authenticate_telegram_user(tg_user(TG), chat_id=TG)
        self.assertFalse(created)
        self.assertEqual(again.pk, target.pk)

    def test_paid_stub_is_not_merged(self):
        stub, _ = authenticate_telegram_user(tg_user(TG), chat_id=TG)
        stub.is_paid = True
        stub.save(update_fields=["is_paid"])
        target = _site_user()
        with self.assertRaises(LinkError) as ctx:
            confirm_link(start_link(target)["code"], tg_user(TG))
        self.assertEqual(ctx.exception.code, "telegram_bound_to_paid_account")
        self.assertTrue(get_user_model().objects.get(pk=stub.pk).is_active)

    def test_already_linked_same_user(self):
        target = _site_user()
        confirm_link(start_link(target)["code"], tg_user(TG), chat_id=TG)
        with self.assertRaises(LinkError) as ctx:
            start_link(target)
        self.assertEqual(ctx.exception.code, "already_linked")
        cache.set("tg:link:manual", target.pk, 60)
        status, _ = confirm_link("manual", tg_user(TG))
        self.assertEqual(status, "already")

    def test_bad_code_and_lockout(self):
        for _ in range(5):
            with self.assertRaises(LinkError) as ctx:
                confirm_link("nope", tg_user(TG))
            self.assertEqual(ctx.exception.code, "code_invalid")
        with self.assertRaises(LinkError) as ctx:
            confirm_link("nope", tg_user(TG))
        self.assertEqual(ctx.exception.code, "too_many_attempts")

    def test_forget_stub_deactivates_and_frees_id(self):
        stub, _ = authenticate_telegram_user(tg_user(TG), chat_id=TG)
        result = forget_telegram(TG)
        self.assertEqual(result, {"status": "unlinked", "deactivated": True})
        stub.refresh_from_db()
        self.assertFalse(stub.is_active)
        self.assertTrue(stub.email.startswith("deleted_"))
        self.assertFalse(TelegramChat.objects.filter(telegram_id=TG).exists())
        fresh, created = authenticate_telegram_user(tg_user(TG), chat_id=TG)
        self.assertTrue(created)
        self.assertNotEqual(fresh.pk, stub.pk)

    def test_forget_site_account_keeps_it(self):
        target = _site_user()
        confirm_link(start_link(target)["code"], tg_user(TG), chat_id=TG)
        result = forget_telegram(TG)
        self.assertFalse(result["deactivated"])
        target.refresh_from_db()
        self.assertTrue(target.is_active)
        self.assertFalse(SocialAccount.objects.filter(user=target).exists())

    def test_http_flow(self):
        target = _site_user()
        client = APIClient()
        client.force_authenticate(target)
        response = client.post("/api/users/telegram/link/start/")
        self.assertEqual(response.status_code, 200, response.data)
        self.assertTrue(response.data["deep_link"].startswith("https://t.me/esai_bot?start=link_"))
        code = response.data["code"]

        response = signed_post({"code": code, "telegram_user": tg_user(TG), "chat_id": TG},
                               path="/api/bot/link/confirm/")
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["status"], "linked")
        self.assertTrue(response.data["access"])
        self.assertEqual(response.data["user"]["id"], target.pk)

        response = client.get("/api/users/telegram/prefs/")
        self.assertTrue(response.data["linked"])
        self.assertEqual(response.data["telegram_id"], TG)
        response = client.patch("/api/users/telegram/prefs/", {"notify_bonus": False}, format="json")
        self.assertFalse(response.data["notify_bonus"])
        self.assertFalse(TelegramChat.objects.get(user=target).notify_bonus)

        response = signed_post({"telegram_id": TG}, path="/api/bot/delete/")
        self.assertEqual(response.data["status"], "unlinked")

    def test_http_bad_code(self):
        response = signed_post({"code": "zzz", "telegram_user": tg_user(TG)},
                               path="/api/bot/link/confirm/")
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.data["detail"], "code_invalid")

    def test_referral_stats_include_bot_link(self):
        target = _site_user()
        client = APIClient()
        client.force_authenticate(target)
        response = client.get("/api/users/referral/stats/")
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.data["telegram_link"].startswith("https://t.me/esai_bot?start=ref_"))
