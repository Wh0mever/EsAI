# -*- coding: utf-8 -*-
"""Telegram Stars: счёт, оплата, повторы, возвраты, сверка.

Сеть не трогаем: Bot API подменяется заглушкой. Кэш — свой.
"""
from unittest.mock import patch

from allauth.socialaccount.models import SocialAccount
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase, override_settings
from django.utils import timezone

from botapi import stars
from botapi.models import TelegramChat
from botapi.tests import SECRET, signed_post
from plans.models import TokenPackage, TokenTransaction

from .models import Payment, StarInvoice

TEST_CACHES = {"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache",
                           "LOCATION": "stars-tests"}}
TG = 900100


def _user(tg=TG, email=None, balance=0, staff=False):
    User = get_user_model()
    user = User.objects.create_user(email=email or f"tg_{tg}@social.esai.local", password="x")
    user.token_balance = balance
    user.is_staff = staff
    user.save(update_fields=["token_balance", "is_staff"])
    SocialAccount.objects.create(user=user, provider="telegram", uid=str(tg))
    TelegramChat.objects.create(user=user, telegram_id=tg, chat_id=tg)
    return user


def _package(stars_price=170, tokens=150, bonus=0, stars_bonus=10, active=True):
    return TokenPackage.objects.create(name="Старт", tokens=tokens, bonus_tokens=bonus,
                                       price=190, currency="KGS", stars_price=stars_price,
                                       stars_bonus_tokens=stars_bonus, is_active=active)


@override_settings(CACHES=TEST_CACHES, STARS_PAYMENTS_MODE="on",
                   TELEGRAM_PRODUCT_BOT_TOKEN="1:x", TELEGRAM_NOTIFY_ENABLED=False)
class InvoiceTests(TestCase):
    def setUp(self):
        cache.clear()
        self.user = _user()
        self.package = _package()

    def test_invoice_snapshot(self):
        data = stars.create_invoice(self.user, self.package, TG, "ru")
        self.assertTrue(data["payload"].startswith("i1."))
        self.assertTrue(data["order_id"].startswith("tgs-"))
        self.assertEqual(data["currency"], "XTR")
        self.assertEqual(data["stars"], 170)
        self.assertEqual(data["tokens_total"], 160)  # 150 + 10 бонуса за бота
        self.assertEqual(data["prices"], [{"label": "160 кредитов", "amount": 170}])
        self.assertLessEqual(len(data["title"]), 32)
        self.assertLessEqual(len(data["description"]), 255)
        payment = Payment.objects.get(order_id=data["order_id"])
        self.assertEqual(payment.provider, "telegram_stars")
        self.assertEqual(payment.request["token_purchase"]["bonus_tokens"], 10)
        self.assertFalse(payment.success)

    def test_same_package_within_hour_is_resumed(self):
        first = stars.create_invoice(self.user, self.package, TG)
        second = stars.create_invoice(self.user, self.package, TG)
        self.assertEqual(first["payload"], second["payload"])
        self.assertTrue(second["resumed"])
        self.assertEqual(StarInvoice.objects.count(), 1)

    def test_package_without_stars_price(self):
        package = _package(stars_price=None)
        with self.assertRaises(stars.StarsError) as ctx:
            stars.create_invoice(self.user, package, TG)
        self.assertEqual(ctx.exception.code, "package_not_available")

    def test_mode_off(self):
        with patch("botapi.stars.stars_mode", return_value="off"):
            with self.assertRaises(stars.StarsError) as ctx:
                stars.create_invoice(self.user, self.package, TG)
        self.assertEqual(ctx.exception.code, "stars_disabled")

    def test_mode_staff_only(self):
        with patch("botapi.stars.stars_mode", return_value="staff"):
            with self.assertRaises(stars.StarsError):
                stars.create_invoice(self.user, self.package, TG)
            staff = _user(tg=TG + 1, staff=True)
            self.assertTrue(stars.create_invoice(staff, self.package, TG + 1)["payload"])

    def test_precheck(self):
        data = stars.create_invoice(self.user, self.package, TG)
        stars.precheck(TG, data["payload"], 170, "XTR")
        for args, code in [
            ((TG, data["payload"], 100, "XTR"), "amount_mismatch"),
            ((TG + 5, data["payload"], 170, "XTR"), "user_mismatch"),
            ((TG, data["payload"], 170, "USD"), "currency_mismatch"),
            ((TG, "i1.nope", 170, "XTR"), "not_found"),
        ]:
            with self.assertRaises(stars.StarsError) as ctx:
                stars.precheck(*args)
            self.assertEqual(ctx.exception.code, code)

    def test_precheck_expired_and_inactive_package(self):
        data = stars.create_invoice(self.user, self.package, TG)
        self.package.is_active = False
        self.package.save()
        with self.assertRaises(stars.StarsError) as ctx:
            stars.precheck(TG, data["payload"], 170, "XTR")
        self.assertEqual(ctx.exception.code, "package_inactive")
        self.package.is_active = True
        self.package.save()
        StarInvoice.objects.update(expires_at=timezone.now() - timezone.timedelta(minutes=1))
        with self.assertRaises(stars.StarsError) as ctx:
            stars.precheck(TG, data["payload"], 170, "XTR")
        self.assertEqual(ctx.exception.code, "expired")


@override_settings(CACHES=TEST_CACHES, STARS_PAYMENTS_MODE="on",
                   TELEGRAM_PRODUCT_BOT_TOKEN="1:x", TELEGRAM_NOTIFY_ENABLED=True)
class ConfirmTests(TestCase):
    def setUp(self):
        cache.clear()
        self.user = _user(balance=5)
        self.package = _package()
        self.data = stars.create_invoice(self.user, self.package, TG)

    def _confirm(self, charge="ch_1", amount=170, tg=TG, currency="XTR"):
        return stars.confirm(tg, self.data["payload"], charge, provider_charge_id="p1",
                             total_amount=amount, currency=currency, raw={"x": 1})

    def test_confirm_credits_and_marks_paid(self):
        with patch("botapi.tasks.notify") as tg_notify:
            result = self._confirm()
        self.assertEqual(result["status"], "paid")
        self.assertEqual(result["credited"], 160)
        self.assertEqual(result["balance_tokens"], 165)
        self.user.refresh_from_db()
        self.assertTrue(self.user.is_paid)
        self.assertEqual(self.user.token_balance, 165)
        payment = Payment.objects.get(order_id=self.data["order_id"])
        self.assertTrue(payment.success)
        self.assertTrue(payment.response["token_purchase_applied"])
        invoice = payment.star_invoice
        self.assertEqual(invoice.status, "paid")
        self.assertEqual(invoice.telegram_payment_charge_id, "ch_1")
        tx = TokenTransaction.objects.get(user=self.user, reason="purchase")
        self.assertEqual(tx.delta, 160)
        self.assertEqual(tx.meta["order_id"], self.data["order_id"])
        # Бот сам подтверждает оплату — второе сообщение о пополнении не шлём.
        kinds = [c.args[1] for c in tg_notify.call_args_list]
        self.assertNotIn("topup", kinds)

    def test_repeat_same_charge_is_duplicate(self):
        self._confirm()
        result = self._confirm()
        self.assertEqual(result["status"], "duplicate")
        self.assertEqual(TokenTransaction.objects.filter(user=self.user, reason="purchase").count(), 1)
        self.user.refresh_from_db()
        self.assertEqual(self.user.token_balance, 165)

    def test_second_charge_on_paid_invoice(self):
        self._confirm()
        with self.assertRaises(stars.StarsError) as ctx:
            self._confirm(charge="ch_2")
        self.assertEqual(ctx.exception.code, "double_payment")
        self.assertEqual(ctx.exception.extra["charge_id"], "ch_2")
        self.user.refresh_from_db()
        self.assertEqual(self.user.token_balance, 165)

    def test_amount_mismatch_credits_nothing(self):
        with self.assertRaises(stars.StarsError) as ctx:
            self._confirm(amount=100)
        self.assertEqual(ctx.exception.code, "amount_mismatch")
        self.user.refresh_from_db()
        self.assertEqual(self.user.token_balance, 5)
        invoice = StarInvoice.objects.get(payload=self.data["payload"])
        self.assertEqual(invoice.status, "failed")
        self.assertEqual(invoice.flags["mismatch"], "amount_mismatch")

    def test_referrer_gets_share(self):
        User = get_user_model()
        referrer = User.objects.create_user(email="ref@example.com", password="x")
        self.user.referred_by = referrer
        self.user.save(update_fields=["referred_by"])
        self._confirm()
        share = TokenTransaction.objects.filter(user=referrer, reason="referral").first()
        self.assertIsNotNone(share)
        self.assertGreater(share.delta, 0)

    def test_refund_claws_back(self):
        self._confirm()
        with patch("botapi.stars.tg_api") as api:
            result = stars.refund(StarInvoice.objects.get(payload=self.data["payload"]),
                                  reason="test")
        self.assertEqual(api.call_args.args[0], "refundStarPayment")
        self.assertEqual(api.call_args.kwargs["telegram_payment_charge_id"], "ch_1")
        self.assertEqual(result["status"], "refunded")
        self.assertEqual(result["debited"], 160)
        self.user.refresh_from_db()
        self.assertEqual(self.user.token_balance, 5)
        invoice = StarInvoice.objects.get(payload=self.data["payload"])
        self.assertEqual(invoice.status, "refunded")
        self.assertEqual(invoice.payment.error, "stars_refunded")
        # Повторный возврат ничего не изымает второй раз.
        again = stars.mark_refunded(charge_id="ch_1")
        self.assertEqual(again["status"], "already_refunded")
        self.user.refresh_from_db()
        self.assertEqual(self.user.token_balance, 5)

    def test_refund_refused_when_credits_spent(self):
        self._confirm()
        self.user.token_balance = 10
        self.user.save(update_fields=["token_balance"])
        invoice = StarInvoice.objects.get(payload=self.data["payload"])
        with patch("botapi.stars.tg_api") as api:
            with self.assertRaises(stars.StarsError) as ctx:
                stars.refund(invoice, reason="x")
            self.assertEqual(ctx.exception.code, "credits_spent")
            api.assert_not_called()
            result = stars.refund(invoice, reason="x", force=True)
        self.assertEqual(result["debited"], 10)  # изъяли что осталось

    def test_telegram_refund_update_is_idempotent(self):
        self._confirm()
        first = stars.mark_refunded(charge_id="ch_1", reason="telegram_refund")
        second = stars.mark_refunded(charge_id="ch_1", reason="telegram_refund")
        self.assertEqual(first["status"], "refunded")
        self.assertEqual(second["status"], "already_refunded")


@override_settings(CACHES=TEST_CACHES, STARS_PAYMENTS_MODE="on",
                   TELEGRAM_PRODUCT_BOT_TOKEN="1:x", TELEGRAM_NOTIFY_ENABLED=False)
class ReconcileTests(TestCase):
    def setUp(self):
        cache.clear()
        self.user = _user()
        self.package = _package()
        self.data = stars.create_invoice(self.user, self.package, TG)

    def test_missed_payment_is_credited(self):
        rows = [{"id": "tx_1", "amount": 170, "date": 1,
                 "source": {"type": "user", "user": {"id": TG},
                            "invoice_payload": self.data["payload"]}},
                {"id": "tx_other", "amount": 5, "date": 1,
                 "source": {"type": "fragment"}}]
        with patch("botapi.stars.tg_api", return_value={"transactions": rows}):
            result = stars.reconcile(limit=100)
        self.assertEqual(result["credited"], 1)
        self.assertEqual(result["offset"], 2)
        invoice = StarInvoice.objects.get(payload=self.data["payload"])
        self.assertEqual(invoice.status, "paid")
        self.assertEqual(invoice.telegram_payment_charge_id, "tx_1")
        self.user.refresh_from_db()
        self.assertEqual(self.user.token_balance, 160)
        # Второй прогон читает с сохранённого смещения и ничего не начисляет.
        with patch("botapi.stars.tg_api", return_value={"transactions": []}) as api:
            result = stars.reconcile(limit=100)
        self.assertEqual(api.call_args.kwargs["offset"], 2)
        self.assertEqual(result["credited"], 0)

    def test_outgoing_transfer_marks_refund(self):
        stars.confirm(TG, self.data["payload"], "tx_1", total_amount=170)
        rows = [{"id": "tx_1", "amount": 170, "date": 1,
                 "receiver": {"type": "user", "user": {"id": TG}}}]
        with patch("botapi.stars.tg_api", return_value={"transactions": rows}):
            result = stars.reconcile(limit=100)
        self.assertEqual(result["refunded"], 1)
        self.assertEqual(StarInvoice.objects.get(payload=self.data["payload"]).status, "refunded")

    def test_stale_invoices_expire(self):
        StarInvoice.objects.update(expires_at=timezone.now() - timezone.timedelta(hours=1))
        with patch("botapi.stars.tg_api", return_value={"transactions": []}):
            result = stars.reconcile()
        self.assertEqual(result["expired"], 1)

    def test_card_reconcile_ignores_stars_orders(self):
        from .tasks import reconcile_pending_token_payments

        Payment.objects.filter(order_id=self.data["order_id"]).update(success=True)
        with patch("payments.tasks._verify_and_credit") as verify:
            reconcile_pending_token_payments()
        verify.assert_not_called()


@override_settings(CACHES=TEST_CACHES, STARS_PAYMENTS_MODE="on", BOT_SERVICE_SECRET=SECRET,
                   TELEGRAM_PRODUCT_BOT_TOKEN="1:x", TELEGRAM_NOTIFY_ENABLED=False)
class StarsHttpTests(TestCase):
    def setUp(self):
        cache.clear()
        self.user = _user(balance=0)
        self.package = _package()

    def test_full_flow_over_http(self):
        response = signed_post({"telegram_id": TG, "package_id": self.package.id, "lang": "en"},
                               path="/api/bot/stars/invoice/")
        self.assertEqual(response.status_code, 200, response.data)
        payload = response.data["payload"]
        self.assertEqual(response.data["prices"][0]["label"], "160 credits")

        response = signed_post({"payload": payload, "message_id": 4242},
                               path="/api/bot/stars/invoice/message/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(StarInvoice.objects.get(payload=payload).invoice_message_id, 4242)

        response = signed_post({"telegram_id": TG, "payload": payload, "total_amount": 170,
                                "currency": "XTR"}, path="/api/bot/stars/precheck/")
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.data["ok"])

        body = {"telegram_id": TG, "payload": payload, "telegram_payment_charge_id": "ch_http",
                "provider_payment_charge_id": "p", "total_amount": 170, "currency": "XTR",
                "raw": {"k": "v"}}
        response = signed_post(body, path="/api/bot/stars/confirm/")
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["status"], "paid")
        self.assertEqual(response.data["user"]["balance_tokens"], 160)
        self.assertEqual(response.data["invoice_message_id"], 4242)

        response = signed_post(body, path="/api/bot/stars/confirm/")
        self.assertEqual(response.data["status"], "duplicate")

        response = signed_post({"telegram_id": TG, "telegram_payment_charge_id": "ch_http"},
                               path="/api/bot/stars/refunded/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["status"], "refunded")
        self.user.refresh_from_db()
        self.assertEqual(self.user.token_balance, 0)

    def test_mismatch_triggers_auto_refund(self):
        payload = stars.create_invoice(self.user, self.package, TG)["payload"]
        with patch("botapi.stars.tg_api") as api:
            response = signed_post({"telegram_id": TG, "payload": payload,
                                    "telegram_payment_charge_id": "ch_bad",
                                    "total_amount": 1, "currency": "XTR"},
                                   path="/api/bot/stars/confirm/")
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.data["detail"], "amount_mismatch")
        self.assertTrue(response.data["refunded"])
        self.assertEqual(api.call_args.args[0], "refundStarPayment")
        self.user.refresh_from_db()
        self.assertEqual(self.user.token_balance, 0)

    def test_unsigned_request_rejected(self):
        from rest_framework.test import APIClient

        response = APIClient().post("/api/bot/stars/invoice/",
                                    {"telegram_id": TG, "package_id": self.package.id},
                                    format="json")
        self.assertEqual(response.status_code, 401)

    def test_admin_refund_endpoint(self):
        from rest_framework.test import APIClient

        data = stars.create_invoice(self.user, self.package, TG)
        stars.confirm(TG, data["payload"], "ch_adm", total_amount=170)
        admin = _user(tg=TG + 9, email="admin@example.com", staff=True)
        client = APIClient()
        client.force_authenticate(admin)
        payment = Payment.objects.get(order_id=data["order_id"])
        with patch("botapi.stars.tg_api"):
            response = client.post(f"/api/manage/payments/{payment.pk}/refund-stars/",
                                   {"reason": "просьба"}, format="json")
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["payment"]["stars"]["status"], "refunded")
        self.assertEqual(response.data["payment"]["stars"]["refund_reason"], "просьба")


@override_settings(CACHES=TEST_CACHES)
class PriceSuggestionTests(TestCase):
    def test_formula_matches_plan(self):
        from decimal import Decimal

        from plans.stars import suggest_stars_price

        package = TokenPackage(name="Про", tokens=500, price=490, currency="KGS")
        with patch("plans.stars.kgs_to_usd_rate", return_value=Decimal("0.01142")):
            self.assertEqual(suggest_stars_price(package), 435)
        package.price = 190
        with patch("plans.stars.kgs_to_usd_rate", return_value=Decimal("0.01142")):
            self.assertEqual(suggest_stars_price(package), 170)

    def test_no_rate_no_suggestion(self):
        from decimal import Decimal

        from plans.stars import suggest_stars_price

        package = TokenPackage(name="x", tokens=1, price=100, currency="KGS")
        with patch("plans.stars.kgs_to_usd_rate", return_value=Decimal("0")):
            self.assertIsNone(suggest_stars_price(package))
