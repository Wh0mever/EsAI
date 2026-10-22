# -*- coding: utf-8 -*-
"""Telegram Stars: название пакета на языке человека, второй платёж по счёту,
возврат чужого платежа, сверка по просроченным счетам и при недоступном журнале.

Сеть не трогаем: Bot API подменяется заглушкой. Кэш — свой.
"""
from unittest.mock import patch

from allauth.socialaccount.models import SocialAccount
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase, override_settings
from django.utils import timezone

from payments.models import Payment, StarInvoice
from plans.models import TokenPackage

from . import stars
from .models import TelegramChat
from .telegram import TelegramError
from .tests import SECRET, signed_post

TEST_CACHES = {"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache",
                           "LOCATION": "stars-edge-tests"}}
TG = 900700


def _user(tg=TG, *, lang="ru", balance=0):
    user = get_user_model().objects.create_user(email=f"tg_{tg}@social.esai.local",
                                                password="x")
    user.token_balance = balance
    user.save(update_fields=["token_balance"])
    SocialAccount.objects.create(user=user, provider="telegram", uid=str(tg))
    if lang:
        TelegramChat.objects.create(user=user, telegram_id=tg, chat_id=tg, lang=lang)
    return user


def _package(**over):
    data = {"name": "Старт", "name_en": "Start", "name_kg": "Баштапкы", "tokens": 150,
            "bonus_tokens": 0, "price": 190, "currency": "KGS", "stars_price": 170,
            "stars_bonus_tokens": 10, "is_active": True}
    data.update(over)
    return TokenPackage.objects.create(**data)


def _tx(payload, tx_id="tx_1", amount=170):
    return {"id": tx_id, "amount": amount, "date": 1,
            "source": {"type": "user", "user": {"id": TG}, "invoice_payload": payload}}


@override_settings(CACHES=TEST_CACHES, STARS_PAYMENTS_MODE="on",
                   TELEGRAM_PRODUCT_BOT_TOKEN="1:x", TELEGRAM_NOTIFY_ENABLED=False)
class PackageNameTests(TestCase):
    def setUp(self):
        cache.clear()
        self.user = _user()
        self.package = _package()

    def test_title_speaks_the_buyers_language(self):
        for lang, title in (("ru", "EsAI · Старт"), ("en", "EsAI · Start"),
                            ("kg", "EsAI · Баштапкы"), ("de", "EsAI · Старт")):
            with self.subTest(lang=lang):
                StarInvoice.objects.all().delete()
                data = stars.create_invoice(self.user, self.package, TG, lang)
                self.assertEqual(data["title"], title)
                self.assertLessEqual(len(data["title"]), 32)

    def test_missing_translation_falls_back_to_russian(self):
        package = _package(name="Про", name_en="", name_kg="  ")
        self.assertEqual(stars.create_invoice(self.user, package, TG, "en")["title"], "EsAI · Про")
        StarInvoice.objects.all().delete()
        self.assertEqual(stars.create_invoice(self.user, package, TG, "kg")["title"], "EsAI · Про")

    def test_resumed_invoice_switches_language(self):
        first = stars.create_invoice(self.user, self.package, TG, "ru")
        second = stars.create_invoice(self.user, self.package, TG, "en")
        self.assertEqual(first["payload"], second["payload"])
        self.assertTrue(second["resumed"])
        self.assertEqual(second["title"], "EsAI · Start")

    def test_deleted_package_keeps_the_snapshot(self):
        data = stars.create_invoice(self.user, self.package, TG, "en")
        invoice = StarInvoice.objects.get(payload=data["payload"])
        TokenPackage.objects.filter(pk=self.package.pk).delete()
        self.assertEqual(stars.package_name_for(invoice, "en"), "Старт")
        invoice.package_name = ""
        self.assertEqual(stars.package_name_for(invoice, "en"), "package")
        self.assertEqual(stars.package_name_for(invoice, "kg"), "пакет")
        self.assertEqual(stars.package_name_for(invoice, "xx"), "пакет")

    def test_paid_message_follows_the_chat_language(self):
        data = stars.create_invoice(self.user, self.package, TG, "ru")
        TelegramChat.objects.filter(telegram_id=TG).update(lang="en")
        result = stars.confirm(TG, data["payload"], "ch_1", total_amount=170)
        self.assertEqual(result["package_name"], "Start")
        TelegramChat.objects.filter(telegram_id=TG).update(lang="kg")
        again = stars.confirm(TG, data["payload"], "ch_1", total_amount=170)
        self.assertEqual((again["status"], again["package_name"]), ("duplicate", "Баштапкы"))

    def test_paid_message_without_chat_uses_the_invoice_language(self):
        user = _user(TG + 1, lang=None)
        data = stars.create_invoice(user, self.package, TG + 1, "kg")
        result = stars.confirm(TG + 1, data["payload"], "ch_kg", total_amount=170)
        self.assertEqual(result["package_name"], "Баштапкы")


@override_settings(CACHES=TEST_CACHES, STARS_PAYMENTS_MODE="on", BOT_SERVICE_SECRET=SECRET,
                   TELEGRAM_PRODUCT_BOT_TOKEN="1:x", TELEGRAM_NOTIFY_ENABLED=False)
class DoubleChargeTests(TestCase):
    """Второй платёж по оплаченному счёту: след остаётся, первый платёж цел."""

    def setUp(self):
        cache.clear()
        self.user = _user(balance=5)
        self.package = _package()
        self.data = stars.create_invoice(self.user, self.package, TG)
        stars.confirm(TG, self.data["payload"], "ch_1", total_amount=170)

    def _invoice(self):
        return StarInvoice.objects.select_related("payment").get(payload=self.data["payload"])

    def _second(self, charge="ch_2"):
        with self.assertRaises(stars.StarsError) as ctx:
            stars.confirm(TG, self.data["payload"], charge, total_amount=170)
        return ctx.exception

    def test_mark_survives_the_rollback(self):
        exc = self._second()
        self.assertEqual(exc.code, "double_payment")
        self.assertNotIn("_invoice_pk", exc.extra)
        invoice = self._invoice()
        self.assertEqual(invoice.status, "paid")
        self.assertEqual(invoice.telegram_payment_charge_id, "ch_1")
        self.assertEqual(invoice.flags["double_charge"], "ch_2")
        self.assertEqual(invoice.flags["double_charges"], ["ch_2"])
        self.assertTrue(invoice.payment.success)
        self.assertIsNone(invoice.payment.error)
        self.assertEqual(invoice.payment.response["double_charge"], "ch_2")
        self.user.refresh_from_db()
        self.assertEqual(self.user.token_balance, 165)

    def test_marks_accumulate_without_repeats(self):
        self._second("ch_2")
        self._second("ch_2")
        self._second("ch_3")
        flags = self._invoice().flags
        self.assertEqual(flags["double_charges"], ["ch_2", "ch_3"])
        self.assertEqual(flags["double_charge"], "ch_3")

    def test_refund_of_the_second_payment_keeps_the_first(self):
        self._second()
        result = stars.mark_refunded(charge_id="ch_2", payload=self.data["payload"],
                                     reason="telegram_refund")
        self.assertEqual(result, {"status": "foreign_charge",
                                  "order_id": self.data["order_id"]})
        self.assertEqual(self._invoice().status, "paid")
        self.user.refresh_from_db()
        self.assertEqual(self.user.token_balance, 165)
        # Возврат самого первого платежа по-прежнему изымает кредиты.
        result = stars.mark_refunded(charge_id="ch_1", payload=self.data["payload"])
        self.assertEqual(result["status"], "refunded")
        self.user.refresh_from_db()
        self.assertEqual(self.user.token_balance, 5)

    def test_http_second_payment_is_refunded_and_internals_stay_inside(self):
        body = {"telegram_id": TG, "payload": self.data["payload"],
                "telegram_payment_charge_id": "ch_2", "total_amount": 170, "currency": "XTR"}
        with patch("botapi.stars.tg_api") as api:
            response = signed_post(body, path="/api/bot/stars/confirm/")
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.data["detail"], "double_payment")
        self.assertTrue(response.data["refunded"])
        self.assertNotIn("_invoice_pk", response.data)
        self.assertEqual(api.call_args.kwargs["telegram_payment_charge_id"], "ch_2")
        self.assertEqual(self._invoice().flags["double_charge"], "ch_2")

        response = signed_post({"telegram_id": TG, "telegram_payment_charge_id": "ch_2",
                                "payload": self.data["payload"]},
                               path="/api/bot/stars/refunded/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["status"], "foreign_charge")
        self.user.refresh_from_db()
        self.assertEqual(self.user.token_balance, 165)


@override_settings(CACHES=TEST_CACHES, STARS_PAYMENTS_MODE="on",
                   TELEGRAM_PRODUCT_BOT_TOKEN="1:x", TELEGRAM_NOTIFY_ENABLED=False)
class ReconcileEdgeTests(TestCase):
    def setUp(self):
        cache.clear()
        self.user = _user()
        self.package = _package()
        self.data = stars.create_invoice(self.user, self.package, TG)

    def test_expired_invoice_paid_in_time_is_credited(self):
        StarInvoice.objects.update(status=StarInvoice.STATUS_EXPIRED,
                                   expires_at=timezone.now() - timezone.timedelta(minutes=5))
        with patch("botapi.stars.tg_api", return_value={"transactions": [_tx(self.data["payload"])]}):
            result = stars.reconcile(limit=100)
        self.assertEqual(result["credited"], 1)
        self.assertEqual(StarInvoice.objects.get(payload=self.data["payload"]).status, "paid")
        self.user.refresh_from_db()
        self.assertEqual(self.user.token_balance, 160)

    def test_failed_and_refunded_invoices_are_not_credited(self):
        for closed in (StarInvoice.STATUS_FAILED, StarInvoice.STATUS_REFUNDED):
            with self.subTest(status=closed):
                StarInvoice.objects.update(status=closed)
                with patch("botapi.stars.tg_api",
                           return_value={"transactions": [_tx(self.data["payload"], f"tx_{closed}")]}):
                    self.assertEqual(stars.reconcile(limit=100)["credited"], 0)
        self.user.refresh_from_db()
        self.assertEqual(self.user.token_balance, 0)

    def test_unreadable_journal_does_not_expire_anything(self):
        StarInvoice.objects.update(expires_at=timezone.now() - timezone.timedelta(hours=1))
        with patch("botapi.stars.tg_api", side_effect=TelegramError("Bad Gateway", 502)):
            result = stars.reconcile()
        self.assertEqual((result["status"], result["expired"]), ("journal_unavailable", 0))
        self.assertEqual(StarInvoice.objects.get(payload=self.data["payload"]).status, "created")
        with patch("botapi.stars.tg_api", return_value={"transactions": []}):
            result = stars.reconcile()
        self.assertEqual((result["status"], result["expired"]), ("ok", 1))

    def test_payment_record_is_untouched_by_reconcile_of_paid_invoice(self):
        stars.confirm(TG, self.data["payload"], "ch_1", total_amount=170)
        with patch("botapi.stars.tg_api",
                   return_value={"transactions": [_tx(self.data["payload"], "ch_other")]}):
            self.assertEqual(stars.reconcile(limit=100)["credited"], 0)
        payment = Payment.objects.get(order_id=self.data["order_id"])
        self.assertNotIn("double_charge", payment.response)
