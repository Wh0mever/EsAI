# -*- coding: utf-8 -*-
"""Ежедневный бонус: начисление, пуш и рассылка в Telegram.

С 6.09 задача падала сразу после первого начисления: список получателей
рассылки не был заведён. Кредиты доходили, а пуш «бонус зачислен» — нет,
и в логе каждый человек числился ошибкой.
"""
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings

from plans.models import TokenTransaction
from plans.tasks import apply_daily_retention_bonus

TEST_CACHES = {"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache",
                           "LOCATION": "daily-bonus-tests"}}


@override_settings(CACHES=TEST_CACHES, DAILY_RETENTION_TARGET=10,
                   DAILY_RETENTION_THRESHOLD=10, TELEGRAM_NOTIFY_ENABLED=True,
                   TELEGRAM_PRODUCT_BOT_TOKEN="123:abc")
class DailyBonusTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.poor = User.objects.create_user(email="poor@example.com", password="x")
        self.poor.token_balance = 2
        self.poor.save(update_fields=["token_balance"])
        self.rich = User.objects.create_user(email="rich@example.com", password="x")
        self.rich.token_balance = 50
        self.rich.save(update_fields=["token_balance"])
        self.paid = User.objects.create_user(email="paid@example.com", password="x")
        self.paid.token_balance = 0
        self.paid.is_paid = True
        self.paid.save(update_fields=["token_balance", "is_paid"])
        self.gone = User.objects.create_user(email="gone@example.com", password="x")
        self.gone.token_balance = 0
        self.gone.is_active = False
        self.gone.save(update_fields=["token_balance", "is_active"])

    def _run(self):
        with patch("adminapi.runtime.get_runtime", side_effect=lambda key, default=None: default), \
             patch("users.webpush.notify_user") as push, \
             patch("botapi.tasks.broadcast_telegram.delay") as broadcast:
            result = apply_daily_retention_bonus.apply().get()
        return result, push, broadcast

    def test_tops_up_pushes_and_broadcasts_without_errors(self):
        result, push, broadcast = self._run()

        self.assertEqual(result["processed"], 1)
        self.assertEqual(result["failed"], 0)
        self.poor.refresh_from_db()
        self.assertEqual(self.poor.token_balance, 10)
        # Платным и тем, у кого и так много, — ничего.
        self.rich.refresh_from_db()
        self.paid.refresh_from_db()
        self.assertEqual(self.rich.token_balance, 50)
        self.assertEqual(self.paid.token_balance, 0)
        self.gone.refresh_from_db()
        self.assertEqual(self.gone.token_balance, 0)

        push.assert_called_once()
        broadcast.assert_called_once()
        self.assertEqual(broadcast.call_args.args[2], [self.poor.pk])
        self.assertEqual(TokenTransaction.objects.filter(reason="daily_bonus").count(), 1)

    def test_second_run_same_day_adds_nothing(self):
        self._run()
        result, _, broadcast = self._run()
        self.poor.refresh_from_db()
        self.assertEqual(self.poor.token_balance, 10)
        self.assertEqual(result["processed"], 0)
        broadcast.assert_not_called()
