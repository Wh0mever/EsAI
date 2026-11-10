# -*- coding: utf-8 -*-
"""Напоминание о заканчивающихся кредитах: пороги 20 % / 10 %, один раз за цикл, сброс покупкой."""
from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from .low_balance import level_for, mark_shown, pending_notice
from .models import TokenTransaction

TEST_CACHES = {"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache",
                           "LOCATION": "low-balance-tests"}}


def _set_balance(user, value):
    user.token_balance = value
    user.save(update_fields=["token_balance"])


def _buy(user, credits):
    _set_balance(user, user.token_balance + credits)
    return TokenTransaction.objects.create(user=user, delta=credits, reason="purchase",
                                           balance_after=user.token_balance)


@override_settings(CACHES=TEST_CACHES)
class LowBalanceTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(email="low@example.com", password="x")

    def test_levels(self):
        self.assertIsNone(level_for(51, 250))
        self.assertEqual(level_for(50, 250), 20)
        self.assertEqual(level_for(26, 250), 20)
        self.assertEqual(level_for(25, 250), 10)
        self.assertEqual(level_for(0, 250), 10)
        self.assertIsNone(level_for(0, 0))

    def test_no_purchase_no_notice(self):
        _set_balance(self.user, 1)  # бонусные кредиты без покупки — не напоминаем
        TokenTransaction.objects.create(user=self.user, delta=5, reason="daily_bonus", balance_after=1)
        self.assertIsNone(pending_notice(self.user))

    def test_unlimited_no_notice(self):
        _buy(self.user, 250)
        _set_balance(self.user, 10)
        self.user.is_unlimited = True
        self.user.save(update_fields=["is_unlimited"])
        self.assertIsNone(pending_notice(self.user))

    def test_full_cycle(self):
        tx = _buy(self.user, 250)
        self.assertIsNone(pending_notice(self.user))
        _set_balance(self.user, 50)
        self.assertEqual(pending_notice(self.user), {"level": 20, "cycle": tx.id, "base": 250})
        self.assertTrue(mark_shown(self.user, 20, tx.id))
        self.assertIsNone(pending_notice(self.user))  # 20 % второй раз не показываем
        _set_balance(self.user, 20)
        self.assertEqual(pending_notice(self.user)["level"], 10)
        self.assertTrue(mark_shown(self.user, 10, tx.id))
        self.assertIsNone(pending_notice(self.user))
        mark_shown(self.user, 20, tx.id)  # старая вкладка не поднимает порог обратно
        _set_balance(self.user, 0)
        self.assertIsNone(pending_notice(self.user))
        # Пополнение — новый цикл.
        tx2 = _buy(self.user, 500)
        self.assertIsNone(pending_notice(self.user))
        _set_balance(self.user, 90)
        self.assertEqual(pending_notice(self.user), {"level": 20, "cycle": tx2.id, "base": 500})

    def test_drop_straight_to_ten(self):
        tx = _buy(self.user, 250)
        _set_balance(self.user, 5)
        self.assertEqual(pending_notice(self.user)["level"], 10)
        mark_shown(self.user, 10, tx.id)
        self.assertIsNone(pending_notice(self.user))
        _set_balance(self.user, 40)  # бонус поднял до 16 % — 20 % после 10 % не показываем
        self.assertIsNone(pending_notice(self.user))

    def test_stale_cycle_rejected(self):
        tx = _buy(self.user, 250)
        _buy(self.user, 250)
        self.assertFalse(mark_shown(self.user, 20, tx.id))
        self.assertFalse(mark_shown(self.user, 15, tx.id))

    def test_api(self):
        api = APIClient()
        api.credentials(HTTP_AUTHORIZATION=f"Bearer {RefreshToken.for_user(self.user).access_token}")
        tx = _buy(self.user, 250)
        self.assertIsNone(api.get("/api/plans/balance/").json()["low_balance"])
        _set_balance(self.user, 30)
        body = api.get("/api/plans/balance/").json()
        self.assertEqual(body["low_balance"], {"level": 20, "cycle": tx.id, "base": 250})
        r = api.post("/api/plans/balance/low-seen/", {"level": 20, "cycle": tx.id}, format="json")
        self.assertEqual(r.json(), {"ok": True})
        self.assertIsNone(api.get("/api/plans/balance/").json()["low_balance"])
        self.assertEqual(api.post("/api/plans/balance/low-seen/", {"level": "x"}, format="json").status_code, 400)
        self.assertEqual(APIClient().post("/api/plans/balance/low-seen/", {}, format="json").status_code, 401)
