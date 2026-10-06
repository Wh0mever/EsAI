# -*- coding: utf-8 -*-
"""Покупка пакета единым QR (GoPay): создание счёта, возврат к нему, скидка.

Сеть закрыта: GoPay подменён «банком» с памятью (payments/tests_gopay_flow.py),
FreedomPay — заглушкой. Ключи — заведомые пустышки.

Главное, что здесь проверяется:
* способ доступен ровно тем, кому должен (и в тестовой среде — только сотруднику);
* повторный клик не плодит счета, а живой QR у покупателя один;
* одноразовая скидка не удваивается между QR и картой и не пропадает молча;
* сбой GoPay не оставляет ни замков, ни занятой скидки.
"""
import uuid
from datetime import timedelta
from decimal import Decimal
from unittest.mock import MagicMock, patch

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from payments.gopay import service
from payments.gopay.client import sign
from payments.models import CryptoInvoice, GoPayInvoice, Payment
from payments.tests_gopay_core import (
    API_KEY, API_SECRET, BASE, LIVE_API_KEY, LIVE_API_SECRET, QR_DATA, fail, html, ok,
)
from payments.tests_gopay_flow import FLOW_SETTINGS, NETWORK_DOWN, Bank
from plans.models import ExitDiscountOffer, TokenPackage, TokenTransaction
from plans.views import _offer_free_for_new_payment

INVOICE_KEYS = {
    "kind", "provider", "resumed", "order_id", "status", "ui_state", "amount", "currency",
    "original_amount", "discount_percent", "package", "credits", "qr", "apps", "checkout_url",
    "created_at", "expires_at", "server_time", "seconds_left", "lifetime_seconds", "is_test",
    "can_cancel", "return_to"}
CREATE, QUERY, CANCEL = "/v1/payments", "/v1/payments/query", "/v1/payments/cancel"


def _fp_ok(*args, **kwargs):
    resp = MagicMock(status_code=200)
    order_id = (kwargs.get("data") or {}).get("pg_order_id")
    resp.json.return_value = {"pg_status": "ok", "pg_redirect_url": f"https://pay.example/{order_id}"}
    return resp


@override_settings(**FLOW_SETTINGS)
class PurchaseCase(TestCase):
    def setUp(self):
        cache.clear()
        self.addCleanup(cache.clear)
        self.bank = Bank()
        self.fp = MagicMock(side_effect=_fp_ok)

        def network(url, *args, **kwargs):
            # requests.post у GoPay и у FreedomPay — один и тот же объект, поэтому
            # подмена одна, а разводим по адресу: GoPay — «банку», остальное — FreedomPay.
            if str(url).startswith(BASE):
                return self.bank(url, *args, **kwargs)
            return self.fp(url, *args, **kwargs)

        self._start(patch("payments.gopay.client.requests.post", side_effect=network))
        self.check_task = self._start(patch("payments.tasks.check_gopay_invoice.apply_async"))
        self.cancel_task = self._start(patch("payments.tasks.cancel_gopay_invoice.delay"))
        users = get_user_model().objects
        self.user = users.create_user(email="buyer@example.com", password="x-pass-123")
        self.staff = users.create_user(email="staff@example.com", password="x-pass-123",
                                       is_staff=True)
        self.pkg = TokenPackage.objects.create(name="Про", tokens=500, bonus_tokens=20,
                                               price=Decimal("490"))
        self.pkg_b = TokenPackage.objects.create(name="Макс", tokens=1000, price=Decimal("990"))
        self.client = APIClient()
        self.client.force_authenticate(self.user)
        self.staff_client = APIClient()
        self.staff_client.force_authenticate(self.staff)

    def _start(self, patcher):
        mock = patcher.start()
        self.addCleanup(patcher.stop)
        return mock

    def buy(self, method="elqr", pkg=None, client=None, **extra):
        body = {"package_id": (pkg or self.pkg).id, **extra}
        if method is not None:
            body["method"] = method
        # Как в жизни: запрос завершился — отложенные действия (снять замок,
        # поставить отмену вытесненного QR) выполнены.
        with self.captureOnCommitCallbacks(execute=True):
            return (client or self.client).post("/api/plans/purchase/", body, format="json")

    def cancel(self, order_id, **body):
        with self.captureOnCommitCallbacks(execute=True):
            return self.client.post(f"/api/plans/purchase/qr/{order_id}/cancel/", body, format="json")

    def invoice(self, order_id):
        return GoPayInvoice.objects.select_related("payment").get(payment__order_id=order_id)

    def offer(self, user=None, **over):
        now = timezone.now()
        fields = dict(user=user or self.user, shown_at=now, claimed_at=now, percent=20,
                      expires_at=now + timedelta(hours=2))
        fields.update(over)
        return ExitDiscountOffer.objects.create(**fields)

    def free(self, offer):
        offer = ExitDiscountOffer.objects.select_related("applied_to_payment").get(pk=offer.pk)
        return _offer_free_for_new_payment(offer)

    def expire(self, order_id, seconds_ago=5):
        """Наш срок счёта вышел seconds_ago секунд назад."""
        GoPayInvoice.objects.filter(payment__order_id=order_id).update(
            expires_at=timezone.now() - timedelta(seconds=seconds_ago))

    def live(self):
        return list(service.open_invoices_for(self.user))


# ======================================================== доступность ===

class AvailabilityTests(PurchaseCase):
    def assert_unavailable(self, client=None):
        r = self.buy(client=client)
        self.assertEqual(r.status_code, 400)
        self.assertEqual(r.data, {"detail": "method_unavailable"})

    def test_method_unavailable(self):
        cases = {
            "GoPay выключен": dict(GOPAY_MODE="off"),
            "нет ключей": dict(GOPAY_LIVE_API_KEY="", GOPAY_LIVE_API_SECRET=""),
            "нет секрета": dict(GOPAY_LIVE_API_SECRET=""),
            "только сотрудникам": dict(GOPAY_MODE="staff"),
            "тестовая среда": dict(GOPAY_ENV="test"),
            "выбор способа выключен": dict(KGS_METHODS_MODE="off"),
        }
        for name, settings_ in cases.items():
            with self.subTest(case=name), override_settings(**settings_):
                cache.clear()
                self.assert_unavailable()
        self.assertEqual(Payment.objects.count(), 0)
        self.assertEqual(self.bank.calls, [])
        self.fp.assert_not_called()

    @override_settings(GOPAY_ENV="test")
    def test_test_env_is_refused_to_a_normal_user_even_if_the_chooser_let_him_in(self):
        # Два чтения настроек в одном запросе могут разойтись: выбор способа
        # «увидел» боевую среду, а покупка — тестовую. Правило «тест только
        # сотрудникам» покупка проверяет сама.
        with patch("payments.kgs_methods.is_available", return_value=True):
            self.assert_unavailable()
        self.assertEqual(Payment.objects.count(), 0)
        self.assertEqual(self.bank.calls, [])

    @override_settings(GOPAY_ENV="test")
    def test_staff_in_test_env_gets_a_test_invoice(self):
        r = self.buy(client=self.staff_client)
        self.assertEqual(r.status_code, 200)
        self.assertIs(r.data["is_test"], True)
        self.assertEqual(r.data["apps"], [])            # тестовый QR не оплачивается банком
        payment = Payment.objects.get(order_id=r.data["order_id"])
        self.assertTrue(payment.is_test)
        self.assertEqual(payment.request["gopay"]["env"], "test")
        self.assertEqual(self.invoice(payment.order_id).env, "test")
        # Запрос подписан тестовой парой ключей.
        call = self.bank.calls[0]
        self.assertEqual(call.headers["GoPay-Api-Key"], API_KEY)
        self.assertEqual(call.headers["GoPay-Signature"],
                         sign(API_SECRET, call.headers["GoPay-Nonce"], call.data))

    def test_normal_user_in_live_gets_a_real_invoice(self):
        r = self.buy()
        self.assertEqual(r.status_code, 200)
        self.assertIs(r.data["is_test"], False)
        payment = Payment.objects.get(order_id=r.data["order_id"])
        self.assertFalse(payment.is_test)
        self.assertEqual(self.invoice(payment.order_id).env, "live")
        call = self.bank.calls[0]
        self.assertEqual(call.headers["GoPay-Api-Key"], LIVE_API_KEY)
        self.assertEqual(call.headers["GoPay-Signature"],
                         sign(LIVE_API_SECRET, call.headers["GoPay-Nonce"], call.data))

    @override_settings(GOPAY_MODE="staff")
    def test_staff_mode_lets_staff_pay_for_real(self):
        self.assertEqual(self.buy(client=self.staff_client).status_code, 200)
        self.assertFalse(Payment.objects.get().is_test)

    def test_non_kgs_package_and_too_large_price(self):
        usd = TokenPackage.objects.create(name="USD", tokens=100, price=Decimal("10"),
                                          currency="USD")
        huge = TokenPackage.objects.create(name="Huge", tokens=100, price=Decimal("1000000.00"))
        for pkg in (usd, huge):
            r = self.buy(pkg=pkg)
            self.assertEqual((r.status_code, r.data), (400, {"detail": "method_unavailable"}))
        edge = TokenPackage.objects.create(name="Edge", tokens=100, price=Decimal("999999.99"))
        self.assertEqual(self.buy(pkg=edge).status_code, 200)
        self.assertEqual(Payment.objects.count(), 1)

    def test_roubles_ignore_the_method(self):
        r = self.buy(pay_currency="RUB")
        self.assertEqual((r.status_code, r.data), (502, {"detail": "yookassa_config_missing"}))
        self.assertEqual(self.bank.calls, [])


# ====================================================== создание счёта ===

class CreateTests(PurchaseCase):
    def test_payment_and_response_shape(self):
        r = self.buy(return_to="/studio/42")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(set(r.data), INVOICE_KEYS)
        self.assertEqual((r.data["kind"], r.data["provider"], r.data["resumed"]),
                         ("qr", "gopay", False))
        self.assertEqual((r.data["status"], r.data["ui_state"]), ("created", "awaiting_payment"))
        self.assertEqual((r.data["amount"], r.data["currency"]), ("490.00", "KGS"))
        self.assertEqual((r.data["original_amount"], r.data["discount_percent"]), (None, None))
        self.assertEqual(r.data["package"], {"id": self.pkg.id, "name": "Про", "tokens": 500,
                                             "bonus_tokens": 20})
        self.assertEqual(r.data["credits"], {"total": 520, "credited": 0})
        self.assertEqual(r.data["qr"]["data"], QR_DATA)
        self.assertTrue(r.data["checkout_url"].startswith("https://pay.gopay.kg/p/"))
        self.assertEqual((r.data["lifetime_seconds"], r.data["can_cancel"], r.data["return_to"]),
                         (900, True, "/studio/42"))
        self.assertTrue(895 <= r.data["seconds_left"] <= 900)
        self.assertEqual(r.data["apps"][0]["code"], "mbank")
        self.assertLessEqual(len(r.data["order_id"]), 32)
        self.assertRegex(r.data["order_id"], rf"^tokpkg-{self.user.id}-{self.pkg.id}-[0-9a-f]{{10}}$")

        payment = Payment.objects.get(order_id=r.data["order_id"])
        self.assertEqual((payment.provider, payment.currency, payment.amount, payment.success),
                         ("gopay", "KGS", Decimal("490.00"), False))
        self.assertEqual(payment.user_id, self.user.id)
        self.assertEqual(set(payment.request),
                         {"provider", "pay_method", "token_purchase", "return_to", "gopay"})
        self.assertEqual((payment.request["provider"], payment.request["pay_method"]),
                         ("gopay", "elqr"))
        self.assertEqual(payment.request["token_purchase"],
                         {"package_id": self.pkg.id, "tokens": 500, "bonus_tokens": 20})
        self.assertNotIn("payload", payment.request["token_purchase"])
        self.assertEqual(payment.request["gopay"],
                         {"env": "live", "lifetime": 900, "package_name": "Про"})
        self.assertEqual(payment.request["return_to"], "/studio/42")
        # Ни одной ссылки там, где карточный код принял бы счёт за страницу банка.
        self.assertEqual(set(payment.response), {"gopay_create"})
        for blob in (r.data, payment.response, payment.request):
            self.assertNotIn("redirect_url", str(blob))
        self.assertFalse(payment.error)

        invoice = self.invoice(payment.order_id)
        self.assertEqual((invoice.status, invoice.amount, invoice.lifetime_seconds),
                         ("created", Decimal("490.00"), 900))
        # Что ушло в GoPay.
        self.assertEqual(self.bank.paths()[0], CREATE)
        sent = self.bank.calls[0].body
        self.assertEqual((sent["order_id"], sent["amount"], sent["lifetime"]),
                         (payment.order_id, "490.00", 900))
        self.assertEqual(sent["description"], "EsAI: Про — 500 кредитов")
        self.assertEqual(sent["success_url"], "https://esai.test/studio/42?payment=tokens_success")
        self.assertEqual(sent["failure_url"], "https://esai.test/studio/42?payment=tokens_failed")
        for key in ("callback_url", "testing_mode", "items"):
            self.assertNotIn(key, sent)
        self.fp.assert_not_called()
        self.cancel_task.assert_not_called()

    def test_lifetime_comes_from_the_setting(self):
        with override_settings(GOPAY_LIFETIME_MINUTES=30):
            r = self.buy()
        self.assertEqual(self.bank.calls[0].body["lifetime"], 1800)
        self.assertEqual(r.data["lifetime_seconds"], 1800)
        self.assertEqual(Payment.objects.get().request["gopay"]["lifetime"], 1800)

    def test_buyer_email_is_sent_only_for_a_real_mailbox(self):
        # Решение ведущего R2: настоящая почта уходит, заглушка аккаунта из
        # Telegram и пустая — никогда; выключатель в админке отключает совсем.
        self.buy()
        self.assertEqual(self.bank.bodies(CREATE)[-1]["buyer"], {"email": "buyer@example.com"})

        users = get_user_model().objects
        for email in ("tg_555@social.esai.local", "TG_777@Social.ESAI.Local"):
            with self.subTest(email=email):
                user = users.create_user(email=email, password="x-pass-123")
                client = APIClient()
                client.force_authenticate(user)
                self.assertEqual(self.buy(client=client).status_code, 200)
                self.assertNotIn("buyer", self.bank.bodies(CREATE)[-1])

        with override_settings(GOPAY_SEND_BUYER_EMAIL=False):
            cache.clear()
            self.assertEqual(self.buy(pkg=self.pkg_b).status_code, 200)
        self.assertNotIn("buyer", self.bank.bodies(CREATE)[-1])
        self.assertEqual(self.bank.count(CREATE), 4)

    def test_buyer_email_helper(self):
        from types import SimpleNamespace

        from plans.views import _gopay_buyer_email

        self.assertEqual(_gopay_buyer_email(SimpleNamespace(email=" a@b.kg ")), "a@b.kg")
        for bad in ("", None, "no-at-sign", "x@social.esai.local", "a" * 250 + "@b.kg"):
            self.assertEqual(_gopay_buyer_email(SimpleNamespace(email=bad)), "")
        self.assertEqual(_gopay_buyer_email(None), "")

    def test_return_path_is_encoded_and_the_body_still_verifies(self):
        r = self.buy(return_to="/chat/my project")
        self.assertEqual(r.status_code, 200)
        call = self.bank.calls[0]
        self.assertEqual(call.body["success_url"],
                         "https://esai.test/chat/my%20project?payment=tokens_success")
        self.assertEqual(call.body["failure_url"],
                         "https://esai.test/chat/my%20project?payment=tokens_failed")
        self.assertEqual(call.headers["GoPay-Signature"],
                         sign(LIVE_API_SECRET, call.headers["GoPay-Nonce"], call.data))
        self.assertEqual(Payment.objects.get().request["return_to"], "/chat/my project")

    def test_return_urls(self):
        from plans.views import _gopay_return_url

        self.assertEqual(_gopay_return_url("/profile", "tokens_success"),
                         "https://esai.test/profile?payment=tokens_success")
        self.assertEqual(_gopay_return_url("/чат/«проект»", "tokens_failed"),
                         "https://esai.test/%D1%87%D0%B0%D1%82/%C2%AB%D0%BF%D1%80%D0%BE%D0%B5%D0%BA%D1%82%C2%BB"
                         "?payment=tokens_failed")
        with override_settings(SITE_BASE_URL="http://esai.test"):
            self.assertEqual(_gopay_return_url("/profile", "tokens_success"), "")
        with override_settings(SITE_BASE_URL=""):
            self.assertEqual(_gopay_return_url("/profile", "tokens_success"), "")

    @override_settings(SITE_BASE_URL="")
    def test_purchase_works_without_return_urls(self):
        self.assertEqual(self.buy().status_code, 200)
        self.assertNotIn("success_url", self.bank.calls[0].body)
        self.assertNotIn("failure_url", self.bank.calls[0].body)

    def test_rejected_return_urls_do_not_fail_the_purchase(self):
        self.bank.script(CREATE, fail("4003", "success_url is not a valid uri"))
        r = self.buy()
        self.assertEqual(r.status_code, 200)
        first, second = self.bank.calls[0].body, self.bank.calls[1].body
        self.assertIn("success_url", first)
        self.assertNotIn("success_url", second)
        self.assertNotIn("failure_url", second)
        self.assertEqual(first["order_id"], second["order_id"])
        self.assertEqual(Payment.objects.count(), 1)
        self.assertFalse(Payment.objects.get().error)


# ====================================================== возврат к счёту ===

class ResumeTests(PurchaseCase):
    def test_second_click_resumes_the_same_invoice(self):
        first = self.buy().data
        again = self.buy()
        self.assertEqual(again.status_code, 200)
        self.assertEqual(set(again.data), INVOICE_KEYS)
        self.assertIs(again.data["resumed"], True)
        self.assertEqual(again.data["order_id"], first["order_id"])
        self.assertEqual(again.data["qr"], first["qr"])
        self.assertEqual(Payment.objects.count(), 1)
        self.assertEqual(self.bank.count(CREATE), 1)
        # full_price на возврат не влияет: скидки тут нет вовсе.
        self.assertEqual(self.buy(full_price=True).data["order_id"], first["order_id"])

    def test_nearly_expired_invoice_is_replaced(self):
        first = self.buy().data
        GoPayInvoice.objects.filter(payment__order_id=first["order_id"]).update(
            expires_at=timezone.now() + timedelta(seconds=80))
        second = self.buy()
        self.assertEqual(second.status_code, 200)
        self.assertIs(second.data["resumed"], False)
        self.assertNotEqual(second.data["order_id"], first["order_id"])
        old = self.invoice(first["order_id"])
        # Прежний QR вытеснен: оставлен и поставлен на отмену у GoPay.
        self.assertEqual(old.flags["abandoned"], "superseded")
        self.assertIsNotNone(old.cancel_requested_at)
        self.cancel_task.assert_called_once_with(old.id, "superseded")
        self.assertEqual([inv.payment.order_id for inv in self.live()], [second.data["order_id"]])

    def test_closed_paid_and_abandoned_invoices_are_not_resumed(self):
        def never_resumed(change):
            cache.clear()
            first = self.buy().data
            change(self.invoice(first["order_id"]))
            second = self.buy()
            self.assertEqual(second.status_code, 200)
            self.assertIs(second.data["resumed"], False)
            self.assertNotEqual(second.data["order_id"], first["order_id"])
            # Закрываем и второй, чтобы следующий случай начинал с чистого листа.
            self.cancel(second.data["order_id"])

        def expire(invoice):
            GoPayInvoice.objects.filter(pk=invoice.pk).update(status="expired")

        def cancel(invoice):
            GoPayInvoice.objects.filter(pk=invoice.pk).update(status="cancelled")

        def pay(invoice):
            self.bank.pay(invoice)
            self.assertEqual(service.refresh_invoice(invoice, source="reconcile"), "credited")

        def abandon(invoice):
            self.assertTrue(service.mark_abandoned(invoice, "user"))

        def other_env(invoice):
            GoPayInvoice.objects.filter(pk=invoice.pk).update(env="test")

        for name, change in (("просрочен", expire), ("отменён", cancel), ("оплачен", pay),
                             ("оставлен", abandon), ("другая среда", other_env)):
            with self.subTest(case=name):
                never_resumed(change)

    def test_four_packages_in_a_row_leave_one_live_qr(self):
        packages = [self.pkg, self.pkg_b,
                    TokenPackage.objects.create(name="C", tokens=100, price=Decimal("100")),
                    TokenPackage.objects.create(name="D", tokens=200, price=Decimal("200"))]
        orders = []
        for pkg in packages:
            r = self.buy(pkg=pkg)
            self.assertEqual(r.status_code, 200)
            self.assertIs(r.data["resumed"], False)
            orders.append(r.data["order_id"])
        self.assertEqual([inv.payment.order_id for inv in self.live()], [orders[-1]])
        abandoned = [self.invoice(order) for order in orders[:-1]]
        self.assertTrue(all(inv.flags.get("abandoned") == "superseded" for inv in abandoned))
        self.assertEqual(sorted(c.args for c in self.cancel_task.call_args_list),
                         sorted((inv.id, "superseded") for inv in abandoned))
        self.assertEqual(self.bank.count(CREATE), 4)
        # Счета остаются в сверке: статус и платёж не тронуты.
        self.assertTrue(all(inv.status == "created" and not inv.payment.error
                            for inv in abandoned))

    def test_backstop_when_gopay_refuses_cancels(self):
        # Шесть счетов, которые у GoPay всё ещё открыты (оставленные считаются).
        for n in range(6):
            pkg = TokenPackage.objects.create(name=f"P{n}", tokens=100, price=Decimal("100"))
            self.assertEqual(self.buy(pkg=pkg).status_code, 200)
        self.assertEqual(service.open_at_provider_count(self.user), 6)
        r = self.buy(pkg=self.pkg_b)
        self.assertEqual((r.status_code, r.data), (429, {"detail": "qr_too_many_open_invoices"}))
        self.assertEqual(Payment.objects.count(), 6)
        # Возврат к живому QR при этом работает.
        self.assertIs(self.buy(pkg=TokenPackage.objects.get(name="P5")).data["resumed"], True)

    def test_other_users_invoices_do_not_count(self):
        other = get_user_model().objects.create_user(email="o@example.com", password="x-pass-123")
        client = APIClient()
        client.force_authenticate(other)
        mine = self.buy().data
        theirs = self.buy(client=client)
        self.assertEqual(theirs.status_code, 200)
        self.assertNotEqual(theirs.data["order_id"], mine["order_id"])
        self.assertIsNone(self.invoice(mine["order_id"]).cancel_requested_at)
        self.cancel_task.assert_not_called()


# ============================================================== лимиты ===

class LimitTests(PurchaseCase):
    def test_eleventh_click_in_a_minute(self):
        for _ in range(10):
            self.assertEqual(self.buy().status_code, 200)
        r = self.buy()
        self.assertEqual((r.status_code, r.data), (429, {"detail": "qr_too_often"}))
        self.assertEqual(Payment.objects.count(), 1)

    def test_creations_per_ip(self):
        cache.set("gopay:purchase:ip:203.0.113.7", 60, 600)
        r = self.client.post("/api/plans/purchase/", {"package_id": self.pkg.id, "method": "elqr"},
                             format="json", HTTP_X_FORWARDED_FOR="203.0.113.7, 10.0.0.1")
        self.assertEqual((r.status_code, r.data), (429, {"detail": "qr_too_often"}))
        self.assertEqual(Payment.objects.count(), 0)
        # С другого адреса — можно; считаются только создания, возврат к счёту — нет.
        first = self.buy()
        self.assertEqual(first.status_code, 200)
        self.assertEqual(cache.get("gopay:purchase:ip:127.0.0.1"), 1)
        self.buy()
        self.assertEqual(cache.get("gopay:purchase:ip:127.0.0.1"), 1)

    def test_global_bucket(self):
        cache.set("gopay:purchase:all", 200, 60)
        with self.assertLogs("payments.gopay", level="ERROR") as logs:
            r = self.buy()
            self.assertEqual((r.status_code, r.data), (429, {"detail": "qr_too_often"}))
            self.assertEqual(self.buy(pkg=self.pkg_b).status_code, 429)
        self.assertEqual(len(logs.records), 1)      # одна запись в минуту, а не на каждый отказ
        self.assertEqual(Payment.objects.count(), 0)
        self.assertEqual(self.bank.calls, [])

    def test_in_flight_guard(self):
        key = f"gopay:create:{self.user.id}:{self.pkg.id}"
        cache.set(key, "1", 90)                     # создание этого пакета уже идёт
        r = self.buy()
        self.assertEqual((r.status_code, r.data), (429, {"detail": "qr_too_often"}))
        self.assertEqual(self.bank.calls, [])
        # Другой пакет замок не держит.
        self.assertEqual(self.buy(pkg=self.pkg_b).status_code, 200)
        self.assertIsNone(cache.get(f"gopay:create:{self.user.id}:{self.pkg_b.id}"))

    def test_guard_is_released_after_a_failed_create(self):
        self.bank.script(CREATE, fail("4001", "Invalid signature"))
        self.assertEqual(self.buy().status_code, 502)
        self.assertIsNone(cache.get(f"gopay:create:{self.user.id}:{self.pkg.id}"))
        self.assertEqual(self.buy().status_code, 200)

    def test_guard_is_released_when_the_request_crashes(self):
        with patch("payments.gopay.service.create_invoice", side_effect=RuntimeError("сбой")):
            with self.assertRaises(RuntimeError):
                self.buy()
        self.assertIsNone(cache.get(f"gopay:create:{self.user.id}:{self.pkg.id}"))

    def test_guard_is_released_when_superseding_the_old_qr_crashes(self):
        # Счёт у GoPay уже создан, а вытеснение прежнего QR упало (на PostgreSQL —
        # взаимной блокировкой с зачислением того QR). Запрос откатывается, и
        # снятие замка «после коммита» не сработает: без немедленного снятия
        # следующий клик полторы минуты получал бы «слишком часто».
        self.assertEqual(self.buy(pkg=self.pkg_b).status_code, 200)
        with patch("payments.gopay.service.mark_abandoned",
                   side_effect=RuntimeError("deadlock detected")):
            with self.assertRaises(RuntimeError):
                self.buy()
        self.assertEqual(self.bank.count(CREATE), 2)        # до GoPay запрос дошёл
        self.assertIsNone(cache.get(f"gopay:create:{self.user.id}:{self.pkg.id}"))
        self.assertEqual(self.buy().status_code, 200)

    def test_guard_is_released_when_the_answer_cannot_be_built(self):
        with patch("payments.gopay.service.invoice_json", side_effect=RuntimeError("сбой")):
            with self.assertRaises(RuntimeError):
                self.buy()
        self.assertIsNone(cache.get(f"gopay:create:{self.user.id}:{self.pkg.id}"))

    def test_create_cancel_create_gives_a_new_qr(self):
        first = self.buy().data
        r = self.cancel(first["order_id"])
        self.assertEqual((r.data["result"], r.data["released"]), ("cancelled", True))
        second = self.buy()
        self.assertEqual(second.status_code, 200)
        self.assertIs(second.data["resumed"], False)
        self.assertNotEqual(second.data["order_id"], first["order_id"])
        self.assertEqual(self.bank.count(CREATE), 2)


# ===================================================== сбой при создании ===

class CreateFailureTests(PurchaseCase):
    def test_gopay_unreachable(self):
        self.bank.script(CREATE, NETWORK_DOWN)
        self.bank.script(QUERY, NETWORK_DOWN)       # и узнать по номеру заказа не удалось
        r = self.buy()
        self.assertEqual((r.status_code, r.data), (502, {"detail": "qr_request_failed"}))
        payment = Payment.objects.get()
        self.assertEqual(payment.error, "gopay_create_failed:network")
        self.assertEqual(payment.response, {})
        self.assertEqual(GoPayInvoice.objects.count(), 0)

    def test_timeout_is_adopted_by_order_id(self):
        # Запрос оборвался, но счёт у GoPay создался: находим его по номеру заказа.
        def created_then_lost(body):
            self.bank.add("f" * 32, body["order_id"], body["amount"])
            raise NETWORK_DOWN

        self.bank.script(CREATE, created_then_lost)
        r = self.buy()
        self.assertEqual(r.status_code, 200)
        self.assertEqual(self.invoice(r.data["order_id"]).provider_payment_id, "f" * 32)
        self.assertEqual(self.bank.calls[1].body, {"order_id": r.data["order_id"]})

    def test_config_errors(self):
        cases = {
            "auth": fail("4001", "Invalid signature"),
            "org_inactive": fail("0016", "Organization is not active"),
            # Ключи вставлены не в те поля: боевая среда, а платёж тестовый.
            "mode_mismatch": lambda body: ok({
                "payment_id": uuid.uuid4().hex, "order_id": body["order_id"],
                "amount": body["amount"], "status": "CREATED", "qr_data": QR_DATA,
                "testing_mode": True}),
        }
        for code, answer in cases.items():
            with self.subTest(code=code):
                cache.clear()
                Payment.objects.all().delete()
                self.bank.script(CREATE, answer)
                r = self.buy()
                self.assertEqual((r.status_code, r.data), (502, {"detail": "qr_config_error"}))
                self.assertEqual(Payment.objects.get().error, f"gopay_create_failed:{code}")
                self.assertEqual(GoPayInvoice.objects.count(), 0)

    def test_rate_limit_and_unknown_rejection(self):
        self.bank.script(CREATE, fail("0004", "Too many requests"))
        r = self.buy()
        self.assertEqual((r.status_code, r.data), (429, {"detail": "qr_too_often"}))
        self.assertEqual(Payment.objects.get().error, "gopay_create_failed:rate_limited")

    def test_breaker_fails_fast_without_a_call(self):
        cache.set("gopay:down:live", 1, 45)
        r = self.buy()
        self.assertEqual((r.status_code, r.data), (502, {"detail": "qr_request_failed"}))
        self.assertEqual(self.bank.calls, [])
        self.assertEqual(Payment.objects.get().error, "gopay_create_failed:circuit_open")

    def test_error_text_never_carries_provider_text_or_keys(self):
        self.bank.script(CREATE, fail("4001", f"bad key {LIVE_API_KEY} / {LIVE_API_SECRET}"))
        r = self.buy()
        payment = Payment.objects.get()
        for blob in (str(r.data), payment.error, str(payment.response), str(payment.request)):
            self.assertNotIn(LIVE_API_KEY, blob)
            self.assertNotIn(LIVE_API_SECRET, blob)
        self.assertEqual(payment.error, "gopay_create_failed:auth")

    def test_previous_qr_stays_live_when_the_new_one_fails(self):
        first = self.buy().data
        self.bank.script(CREATE, fail("9999", "internal error"))
        self.bank.script(QUERY, fail("4041", "Payment not found"))
        r = self.buy(pkg=self.pkg_b)
        self.assertEqual(r.status_code, 502)
        old = self.invoice(first["order_id"])
        self.assertIsNone(old.cancel_requested_at)
        self.assertEqual(old.flags, {})
        self.cancel_task.assert_not_called()
        self.assertIs(self.buy().data["resumed"], True)

    def test_discount_is_free_at_once_after_a_failed_create(self):
        offer = self.offer()
        self.bank.script(CREATE, NETWORK_DOWN)
        self.bank.script(QUERY, NETWORK_DOWN)
        self.assertEqual(self.buy().status_code, 502)
        failed = Payment.objects.get()
        self.assertEqual(failed.amount, Decimal("392.00"))
        offer.refresh_from_db()
        self.assertEqual(offer.applied_to_payment_id, failed.pk)
        # Платёж с ошибкой и без счёта скидку не держит.
        self.assertTrue(self.free(offer))
        cache.clear()
        again = self.buy()
        self.assertEqual((again.status_code, again.data["amount"]), (200, "392.00"))

    def test_discount_returns_to_the_previous_qr_after_a_failed_create(self):
        offer = self.offer()
        first = self.buy().data
        self.assertEqual(first["amount"], "392.00")
        held = Payment.objects.get(order_id=first["order_id"])
        self.bank.script(CREATE, NETWORK_DOWN)
        self.bank.script(QUERY, NETWORK_DOWN)
        self.assertEqual(self.buy(pkg=self.pkg_b).status_code, 502)
        # Новый QR не создан — скидка осталась за прежним, живым.
        offer.refresh_from_db()
        self.assertEqual(offer.applied_to_payment_id, held.pk)
        self.assertFalse(self.free(offer))
        self.assertIsNone(self.invoice(first["order_id"]).cancel_requested_at)
        failed = Payment.objects.exclude(pk=held.pk).get()
        self.assertEqual((failed.amount, failed.error),
                         (Decimal("792.00"), "gopay_create_failed:network"))


# ======================================================= скидка при уходе ===

class ExitDiscountTests(PurchaseCase):
    def setUp(self):
        super().setUp()
        self.discount = self.offer()

    def holder_id(self):
        self.discount.refresh_from_db()
        return self.discount.applied_to_payment_id

    def test_qr_gets_the_discount(self):
        r = self.buy()
        self.assertEqual(r.status_code, 200)
        self.assertEqual((r.data["amount"], r.data["original_amount"], r.data["discount_percent"]),
                         ("392.00", "490.00", 20))
        payment = Payment.objects.get(order_id=r.data["order_id"])
        self.assertEqual(payment.amount, Decimal("392.00"))
        self.assertEqual(payment.request["exit_discount"],
                         {"offer_id": self.discount.id, "percent": 20, "original_amount": "490.00"})
        self.assertEqual(self.holder_id(), payment.pk)
        self.assertEqual(self.bank.calls[0].body["amount"], "392.00")
        self.assertEqual(self.invoice(payment.order_id).amount, Decimal("392.00"))
        # Кредитов столько же, сколько по полной цене.
        self.assertEqual(r.data["credits"]["total"], 520)

    def test_credit_of_a_discounted_qr_redeems_the_offer(self):
        r = self.buy()
        invoice = self.invoice(r.data["order_id"])
        self.bank.pay(invoice)
        self.assertEqual(service.refresh_invoice(invoice, source="reconcile"), "credited")
        self.discount.refresh_from_db()
        self.assertIsNotNone(self.discount.redeemed_at)
        self.assertEqual(TokenTransaction.objects.get(user=self.user, reason="purchase").delta, 520)
        self.assertNotIn("needs_review", self.invoice(r.data["order_id"]).flags)
        # Скидка использована: следующий QR — по полной цене.
        self.assertEqual(self.buy(pkg=self.pkg_b).data["amount"], "990.00")

    # --- матрица «за кем скидка — что нажали» ----------------------------------

    def test_qr_click_resumes_the_discounted_qr_whatever_time_is_left(self):
        first = self.buy().data
        GoPayInvoice.objects.filter(payment__order_id=first["order_id"]).update(
            expires_at=timezone.now() + timedelta(seconds=20))
        again = self.buy()
        # Никакого 409: «скидка занята единым QR, оплатите единым QR без скидки»
        # покупателю не объяснить.
        self.assertEqual(again.status_code, 200)
        self.assertIs(again.data["resumed"], True)
        self.assertEqual(again.data["order_id"], first["order_id"])
        self.assertEqual(again.data["amount"], "392.00")
        self.assertEqual(Payment.objects.count(), 1)

    def test_qr_for_another_package_takes_the_discount_along(self):
        first = self.buy().data
        second = self.buy(pkg=self.pkg_b)
        self.assertEqual(second.status_code, 200)
        self.assertEqual((second.data["amount"], second.data["original_amount"]),
                         ("792.00", "990.00"))
        self.assertEqual(self.holder_id(), Payment.objects.get(order_id=second.data["order_id"]).pk)
        old = self.invoice(first["order_id"])
        self.assertEqual(old.flags["abandoned"], "superseded")
        self.cancel_task.assert_called_once_with(old.id, "superseded")
        self.assertEqual(Payment.objects.filter(request__exit_discount__isnull=False).count(), 2)

    def test_card_click_is_asked_about_the_discount_held_by_a_qr(self):
        first = self.buy().data
        r = self.buy("card")
        self.assertEqual(r.status_code, 409)
        self.assertEqual(r.data, {
            "detail": "discount_held", "amount": "490.00", "currency": "KGS",
            "held": {"method": "elqr", "order_id": first["order_id"], "redirect_url": "",
                     "amount": "392.00", "kind": "qr"}})
        self.assertEqual(Payment.objects.count(), 1)
        self.fp.assert_not_called()
        self.assertEqual(self.bank.count(CANCEL), 0)

        # Согласился платить картой без скидки: скидка остаётся за QR.
        full = self.buy("card", full_price=True)
        self.assertEqual((full.status_code, full.data["amount"]), (200, "490.00"))
        self.assertEqual(self.holder_id(), Payment.objects.get(order_id=first["order_id"]).pk)
        self.assertEqual(self.fp.call_args.kwargs["data"]["pg_amount"], "490.00")

    def test_cancel_the_qr_then_card_gets_the_discount(self):
        first = self.buy().data
        r = self.cancel(first["order_id"])
        self.assertIs(r.data["released"], True)
        card = self.buy("card")
        self.assertEqual((card.status_code, card.data["amount"]), (200, "392.00"))
        self.assertEqual(self.holder_id(), Payment.objects.get(order_id=card.data["order_id"]).pk)

    def test_cancel_refused_by_gopay_still_frees_the_discount_for_the_card(self):
        # У GoPay нет метода отмены: QR оставлен, а не закрыт — но покупателя
        # это не держит, и «незавершённой оплаты» от него не остаётся.
        first = self.buy().data
        self.bank.always(CANCEL, html(404))
        r = self.cancel(first["order_id"])
        self.assertEqual((r.data["result"], r.data["released"]), ("retry", True))
        self.assertIsNone(self.client.get("/api/plans/purchase/pending/").data["pending"])
        card = self.buy("card")
        self.assertEqual((card.status_code, card.data["amount"]), (200, "392.00"))

    def test_qr_click_is_asked_about_the_discount_held_by_a_card_link(self):
        card = self.buy("card").data
        self.assertEqual(card["amount"], "392.00")
        r = self.buy()
        self.assertEqual(r.status_code, 409)
        # Держатель — карточная ссылка: прежние четыре ключа, без «kind».
        self.assertEqual(r.data, {
            "detail": "discount_held", "amount": "490.00", "currency": "KGS",
            "held": {"method": "card", "order_id": card["order_id"],
                     "redirect_url": card["redirect_url"], "amount": "392.00"}})
        self.assertEqual(self.bank.calls, [])
        for flag in ("true", 1):
            self.assertEqual(self.buy(full_price=flag).status_code, 409)

        full = self.buy(full_price=True)
        self.assertEqual((full.status_code, full.data["amount"]), (200, "490.00"))
        self.assertEqual((full.data["original_amount"], full.data["discount_percent"]),
                         (None, None))
        self.assertEqual(self.holder_id(), Payment.objects.get(order_id=card["order_id"]).pk)
        # Вопрос задаётся при каждом клике без согласия, даже когда QR по полной цене уже есть.
        self.assertEqual(self.buy().status_code, 409)
        self.assertIs(self.buy(full_price=True).data["resumed"], True)

    def test_discount_claimed_after_a_full_price_qr(self):
        ExitDiscountOffer.objects.filter(pk=self.discount.pk).update(claimed_at=None)
        first = self.buy().data
        self.assertEqual(first["amount"], "490.00")
        ExitDiscountOffer.objects.filter(pk=self.discount.pk).update(claimed_at=timezone.now())
        second = self.buy()
        self.assertEqual(second.status_code, 200)
        self.assertIs(second.data["resumed"], False)
        self.assertEqual(second.data["amount"], "392.00")
        self.assertEqual(self.invoice(first["order_id"]).flags["abandoned"], "superseded")

    def test_expired_offer_changes_nothing(self):
        first = self.buy().data
        ExitDiscountOffer.objects.filter(pk=self.discount.pk).update(
            expires_at=timezone.now() - timedelta(minutes=1))
        # Скидки на витрине уже нет — карта идёт по полной цене без вопросов.
        card = self.buy("card")
        self.assertEqual((card.status_code, card.data["amount"]), (200, "490.00"))
        self.assertIs(self.buy().data["resumed"], True)
        self.assertEqual(self.buy().data["order_id"], first["order_id"])

    # --- QR, чей срок по нашим часам вышел, а GoPay закрытие ещё не подтвердил ---

    def test_new_qr_cancels_the_stale_one_and_gets_the_discount(self):
        first = self.buy().data
        self.expire(first["order_id"], 5)
        second = self.buy()
        self.assertEqual(second.status_code, 200)
        self.assertIs(second.data["resumed"], False)
        self.assertEqual(second.data["amount"], "392.00")
        old = self.invoice(first["order_id"])
        self.assertEqual((old.status, old.flags["cancel_reason"]), ("cancelled", "expired"))
        # Сначала отмена старого у GoPay, потом создание нового.
        self.assertEqual(self.bank.paths()[-2:], [CANCEL, CREATE])
        self.assertEqual(self.holder_id(), Payment.objects.get(order_id=second.data["order_id"]).pk)

    def test_bank_still_processing_the_stale_qr_makes_the_buyer_wait(self):
        first = self.buy().data
        self.expire(first["order_id"], 5)
        self.bank.always(CANCEL, fail("0013", "bank is processing"))
        for method in ("elqr", "card"):
            with self.subTest(method=method):
                r = self.buy(method)
                self.assertEqual((r.status_code, r.data), (429, {"detail": "qr_busy"}))
        self.assertEqual(Payment.objects.count(), 1)
        self.fp.assert_not_called()
        old = self.invoice(first["order_id"])
        self.assertEqual((old.status, old.cancel_requested_at), ("created", None))
        self.assertEqual(self.holder_id(), old.payment_id)

    def test_gopay_unreachable_abandons_the_stale_qr(self):
        first = self.buy().data
        self.expire(first["order_id"], 5)
        self.bank.script(CANCEL, NETWORK_DOWN)
        second = self.buy()
        self.assertEqual(second.status_code, 200)
        self.assertEqual(second.data["amount"], "392.00")
        old = self.invoice(first["order_id"])
        self.assertEqual((old.status, old.flags["abandoned"]), ("created", "expired"))
        self.cancel_task.assert_called_once_with(old.id, "expired")

    def test_breaker_abandons_the_stale_qr_without_waiting(self):
        first = self.buy().data
        self.expire(first["order_id"], 5)
        cache.set("gopay:down:live", 1, 45)
        calls = len(self.bank.calls)
        card = self.buy("card")
        self.assertEqual((card.status_code, card.data["amount"]), (200, "392.00"))
        self.assertEqual(len(self.bank.calls), calls)
        self.assertEqual(self.invoice(first["order_id"]).flags["abandoned"], "expired")

    def test_stale_qr_that_turns_out_paid_is_shown_as_paid(self):
        first = self.buy().data
        self.expire(first["order_id"], 5)
        self.bank.pay(self.invoice(first["order_id"]))      # отмена -> 0013, статус -> COMMITTED
        r = self.buy()
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.data["order_id"], first["order_id"])
        self.assertEqual((r.data["ui_state"], r.data["resumed"]), ("paid", True))
        self.assertEqual(r.data["credits"]["credited"], 520)
        self.assertEqual(Payment.objects.count(), 1)
        self.assertEqual(self.bank.count(CREATE), 1)
        self.assertEqual(TokenTransaction.objects.filter(user=self.user, reason="purchase").count(), 1)

    def test_stale_paid_qr_and_a_click_on_another_package(self):
        first = self.buy().data
        self.expire(first["order_id"], 5)
        self.bank.pay(self.invoice(first["order_id"]))
        r = self.buy(pkg=self.pkg_b)
        # Оплачен был другой пакет — этот создаётся как обычно, уже без скидки.
        self.assertEqual((r.status_code, r.data["amount"]), (200, "990.00"))
        self.assertTrue(Payment.objects.get(order_id=first["order_id"]).success)

    def test_card_click_on_a_stale_qr_that_turns_out_paid_does_not_charge_again(self):
        # Заплатил в последние секунды QR, вкладка уже показала «истёк», нажал
        # «картой». Сервер в этом же запросе узнаёт об оплате и зачисляет её —
        # отправить человека на страницу банка платить за тот же пакет второй
        # раз нельзя: возврата через API у GoPay нет.
        for method in ("card", None):
            with self.subTest(method=method):
                cache.clear()
                self.fp.reset_mock()
                Payment.objects.all().delete()
                TokenTransaction.objects.all().delete()
                ExitDiscountOffer.objects.all().delete()
                self.discount = self.offer()
                first = self.buy().data
                self.expire(first["order_id"], 5)
                self.bank.pay(self.invoice(first["order_id"]))  # отмена -> 0013, статус -> COMMITTED
                r = self.buy(method)
                self.assertEqual(r.status_code, 200)
                self.assertEqual(set(r.data), INVOICE_KEYS)
                self.assertEqual((r.data["kind"], r.data["order_id"]), ("qr", first["order_id"]))
                self.assertEqual((r.data["ui_state"], r.data["resumed"]), ("paid", True))
                self.assertEqual(r.data["credits"]["credited"], 520)
                self.assertNotIn("redirect_url", r.data)
                self.fp.assert_not_called()
                self.assertEqual(Payment.objects.count(), 1)
                self.assertEqual(
                    TokenTransaction.objects.filter(user=self.user, reason="purchase").count(), 1)
                # Следующий клик — уже осознанная вторая покупка: обычная оплата
                # картой по полной цене (скидка использована).
                again = self.buy(method)
                self.assertEqual((again.status_code, again.data["amount"]), (200, "490.00"))
                self.assertTrue(again.data["redirect_url"])
                self.fp.assert_called_once()

    def test_card_click_when_the_paid_stale_qr_is_under_review(self):
        # Деньги пришли, но сумма не сошлась: счёт «оплачен, на разборе». Вести
        # человека платить картой второй раз всё равно нельзя.
        first = self.buy().data
        self.expire(first["order_id"], 5)
        self.bank.pay(self.invoice(first["order_id"]), amount="1.00")
        r = self.buy("card")
        self.assertEqual(r.status_code, 200)
        self.assertEqual((r.data["kind"], r.data["order_id"], r.data["ui_state"]),
                         ("qr", first["order_id"], "processing"))
        self.fp.assert_not_called()
        self.assertEqual(Payment.objects.count(), 1)

    def test_stale_paid_qr_and_a_card_click_on_another_package(self):
        first = self.buy().data
        self.expire(first["order_id"], 5)
        self.bank.pay(self.invoice(first["order_id"]))
        r = self.buy("card", pkg=self.pkg_b)
        # Оплачен был другой пакет — этот оплачивается картой как обычно, уже без скидки.
        self.assertEqual((r.status_code, r.data["amount"]), (200, "990.00"))
        self.assertTrue(r.data["redirect_url"])
        self.assertTrue(Payment.objects.get(order_id=first["order_id"]).success)

    def test_paid_stale_qr_never_blocks_the_card_when_the_answer_cannot_be_built(self):
        first = self.buy().data
        self.expire(first["order_id"], 5)
        self.bank.pay(self.invoice(first["order_id"]))
        with patch("payments.gopay.service.invoice_json", side_effect=RuntimeError("сбой")):
            r = self.buy("card")
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.data["redirect_url"])

    def test_expired_qr_is_not_a_live_holder_even_when_gopay_was_not_asked(self):
        # Обычно истёкший скидочный QR закрывает _release_stale_qr_discount. Но он
        # глотает любую ошибку и тогда ничего не делает — и держателем скидки
        # такой QR считаться не должен: срок по нашим часам вышел.
        first = self.buy().data
        self.expire(first["order_id"], 5)
        with patch("plans.views._release_stale_qr_discount", return_value=("", None)):
            card = self.buy("card")
            # Не 409 «скидка занята»: платить по истёкшему QR человеку не предложить.
            self.assertEqual(card.status_code, 200)
            self.assertTrue(card.data["redirect_url"])
            qr = self.buy()
            # И не возврат к истёкшему счёту: создан новый.
            self.assertEqual(qr.status_code, 200)
            self.assertIs(qr.data["resumed"], False)
            self.assertNotEqual(qr.data["order_id"], first["order_id"])
            self.assertEqual(qr.data["ui_state"], "awaiting_payment")
        self.assertEqual(self.bank.count(CANCEL), 0)
        old = self.invoice(first["order_id"])
        self.assertEqual((old.status, old.cancel_requested_at), ("created", None))
        # GoPay закрытие не подтвердил — скидка по-прежнему за старым QR.
        self.assertEqual(self.holder_id(), old.payment_id)
        self.assertEqual((card.data["amount"], qr.data["amount"]), ("490.00", "490.00"))

    def test_card_click_in_the_same_window(self):
        first = self.buy().data
        self.expire(first["order_id"], 5)
        card = self.buy("card")
        self.assertEqual((card.status_code, card.data["amount"]), (200, "392.00"))
        self.assertEqual(self.invoice(first["order_id"]).status, "cancelled")
        self.assertEqual(self.fp.call_args.kwargs["data"]["pg_amount"], "392.00")

    def test_locally_expired_qr_is_resolved_on_the_next_click(self):
        first = self.buy().data
        self.expire(first["order_id"], 3600)
        self.assertTrue(service.mark_expired_locally(self.invoice(first["order_id"])))
        self.assertFalse(self.free(self.discount))
        second = self.buy()
        self.assertEqual((second.status_code, second.data["amount"]), (200, "392.00"))
        old = self.invoice(first["order_id"])
        self.assertNotIn("local_expiry", old.flags)

    def test_helper_never_blocks_a_card_purchase(self):
        self.buy()
        with patch("payments.gopay.service.invoice_of", side_effect=RuntimeError("сбой")):
            r = self.buy("card", full_price=True)
        self.assertEqual(r.status_code, 200)

    # --- когда скидка свободна -----------------------------------------------------

    def test_when_the_discount_is_released(self):
        first = self.buy().data
        order = first["order_id"]

        def invoice():
            return self.invoice(order)

        def reset(**fields):
            base = dict(status="created", cancel_requested_at=None, flags={}, finalized_at=None,
                        expires_at=timezone.now() + timedelta(minutes=15))
            base.update(fields)
            GoPayInvoice.objects.filter(payment__order_id=order).update(**base)
            Payment.objects.filter(order_id=order).update(error="", success=False)

        # Открытый QR держит скидку. Две минуты после создания — не повод её
        # отпустить (у карточного пути это «оборванный старт», у QR ссылки нет вовсе).
        Payment.objects.filter(order_id=order).update(
            created_at=timezone.now() - timedelta(minutes=3))
        self.assertFalse(self.free(self.discount))
        # Наш срок вышел больше минуты назад, GoPay молчит — всё ещё держит.
        reset(expires_at=timezone.now() - timedelta(seconds=61))
        self.assertFalse(self.free(self.discount))
        # Закрыт только нашими часами — держит.
        reset(expires_at=timezone.now() - timedelta(minutes=11))
        self.assertTrue(service.mark_expired_locally(invoice()))
        self.assertEqual(invoice().flags, {"local_expiry": True})
        self.assertFalse(self.free(self.discount))

        # GoPay подтвердил закрытие — свободна.
        for status in ("EXPIRED", "CANCELLED", "FAILED"):
            with self.subTest(status=status):
                reset()
                self.bank.set_status(invoice(), status)
                self.assertEqual(service.refresh_invoice(invoice(), source="reconcile"), "closed")
                self.assertTrue(self.free(self.discount))
        # Успешная отмена — свободна.
        reset()
        self.bank.set_status(invoice(), "CREATED")
        self.assertEqual(service.cancel_invoice(invoice(), reason="user"), "cancelled")
        self.assertTrue(self.free(self.discount))
        # Оставлен покупателем — свободна.
        reset()
        self.assertTrue(service.mark_abandoned(invoice(), "user"))
        self.assertTrue(self.free(self.discount))

        # Оплачен и на разборе (сумма не сошлась) — держит: это оплаченный платёж.
        reset()
        self.bank.pay(invoice(), amount="1.00")
        self.assertEqual(service.refresh_invoice(invoice(), source="reconcile"), "mismatch")
        self.assertEqual(invoice().status, "committed")
        self.assertFalse(self.free(self.discount))
        # И своими часами такой счёт уже не закрыть.
        self.assertFalse(service.mark_expired_locally(invoice()))

        # Оставлен покупателем, а потом оплачен, и сумма не сошлась: «оставлен»
        # скидку отпустил бы, но деньги пришли — платёж её держит.
        reset()
        self.bank.set_status(invoice(), "CREATED", amount="392.00")
        self.assertTrue(service.mark_abandoned(invoice(), "user"))
        self.assertTrue(self.free(self.discount))
        self.bank.pay(invoice(), amount="1.00")
        self.assertEqual(service.refresh_invoice(invoice(), source="reconcile"), "mismatch")
        self.assertIsNotNone(invoice().cancel_requested_at)
        self.assertFalse(self.free(self.discount))

    def test_buyer_without_a_qr_makes_no_gopay_call_on_a_card_purchase(self):
        card = self.buy("card")
        self.assertEqual((card.status_code, card.data["amount"]), (200, "392.00"))
        self.assertEqual(self.buy("mbank").status_code, 400)      # кошельки по умолчанию выключены
        ExitDiscountOffer.objects.all().delete()
        self.assertEqual(self.buy("card", pkg=self.pkg_b).status_code, 200)
        self.assertEqual(self.buy(None).status_code, 200)
        self.assertEqual(self.bank.calls, [])

    def test_card_to_card_conflict_body_is_unchanged(self):
        with patch("payments.kgs_methods.DEFAULT_ENABLED", "mbank,odengi,megapay,card"):
            first = self.buy("mbank").data
            r = self.buy("card")
        self.assertEqual(r.status_code, 409)
        self.assertEqual(r.data, {
            "detail": "discount_held", "amount": "490.00", "currency": "KGS",
            "held": {"method": "mbank", "order_id": first["order_id"],
                     "redirect_url": first["redirect_url"], "amount": "392.00"}})
        self.assertEqual(self.bank.calls, [])


# ================================================ незавершённая оплата ===

class PendingTests(PurchaseCase):
    def pending(self):
        return self.client.get("/api/plans/purchase/pending/").data["pending"]

    def test_pending_returns_the_qr(self):
        self.assertIsNone(self.pending())
        qr = self.buy().data
        pending = self.pending()
        self.assertEqual(set(pending), {"kind", "order_id", "amount", "currency", "package",
                                        "created_at", "redirect_url", "status_url", "expires_at",
                                        "server_time"})
        # Часы сервера нужны плашке: по ним она считает остаток, а не по часам телефона.
        from django.utils.dateparse import parse_datetime
        server_time = parse_datetime(pending["server_time"])
        self.assertIsNotNone(server_time.tzinfo)
        self.assertLess(abs((timezone.now() - server_time).total_seconds()), 5)
        self.assertLess(server_time, parse_datetime(pending["expires_at"]))
        self.assertEqual((pending["kind"], pending["order_id"], pending["amount"],
                          pending["currency"], pending["package"]),
                         ("qr", qr["order_id"], "490.00", "KGS", "Про"))
        self.assertIsNone(pending["redirect_url"])
        self.assertEqual(pending["status_url"], f"/api/plans/purchase/qr/{qr['order_id']}/")
        self.assertEqual(pending["expires_at"], qr["expires_at"])
        # По этому адресу экран и открывается.
        self.assertEqual(self.client.get(pending["status_url"]).data["order_id"], qr["order_id"])

    def test_newest_of_card_crypto_and_qr_wins(self):
        qr = self.buy().data
        card = self.buy("card", full_price=True).data
        self.assertEqual((self.pending()["kind"], self.pending()["order_id"]),
                         ("card", card["order_id"]))
        # QR новее карты.
        Payment.objects.filter(order_id=card["order_id"]).update(
            created_at=timezone.now() - timedelta(minutes=5))
        self.assertEqual((self.pending()["kind"], self.pending()["order_id"]),
                         ("qr", qr["order_id"]))
        # Криптосчёт новее обоих.
        Payment.objects.filter(order_id=qr["order_id"]).update(
            created_at=timezone.now() - timedelta(minutes=2))
        crypto_payment = Payment.objects.create(
            user=self.user, provider="crypto_nowpayments", amount=Decimal("5.64"), currency="USD",
            order_id="tokpkg-crypto-1",
            request={"pay_method": "crypto", "token_purchase": {"package_id": self.pkg.id}})
        CryptoInvoice.objects.create(
            payment=crypto_payment, provider="nowpayments", provider_invoice_id="np-1",
            status=CryptoInvoice.STATUS_WAITING, price_amount=Decimal("5.64"),
            price_currency="USD", pay_currency="usdttrc20", pay_coin="USDT", pay_network="TRC-20",
            pay_address="addr", pay_amount=Decimal("5.7"),
            expires_at=timezone.now() + timedelta(minutes=30))
        self.assertEqual(self.pending()["kind"], "crypto")

    def test_closed_paid_abandoned_and_almost_expired_qr_are_not_pending(self):
        def gone(change):
            cache.clear()
            Payment.objects.all().delete()
            order = self.buy().data["order_id"]
            self.assertEqual(self.pending()["order_id"], order)
            change(order)
            self.assertIsNone(self.pending())

        gone(lambda order: service.mark_abandoned(self.invoice(order), "user"))
        gone(lambda order: self.cancel(order))
        gone(lambda order: GoPayInvoice.objects.filter(payment__order_id=order).update(
            status="expired"))
        gone(lambda order: GoPayInvoice.objects.filter(payment__order_id=order).update(
            expires_at=timezone.now() + timedelta(seconds=20)))

        def pay(order):
            invoice = self.invoice(order)
            self.bank.pay(invoice)
            service.refresh_invoice(invoice, source="reconcile")

        gone(pay)

    def test_other_users_qr_is_not_my_pending(self):
        self.buy(client=self.staff_client)
        self.assertIsNone(self.pending())


# ============================================ карта осталась прежней ===

class CardPathUnchangedTests(PurchaseCase):
    """GoPay включён для всех, а в FreedomPay уходит ровно то же, что до него.

    Значения сверены с кодом до сборки: тот же запрос к прежнему и к новому
    plans/views.py дал одинаковые поля, подпись и запись платежа.
    """

    def assert_freedompay_request(self, method, extra):
        from payments.freedompay import make_api_signature

        r = self.buy(method)
        self.assertEqual(r.status_code, 200)
        order_id = r.data["order_id"]
        self.assertEqual(r.data, {
            "redirect_url": f"https://pay.example/{order_id}", "order_id": order_id,
            "amount": "490.00", "currency": "KGS", "package_id": self.pkg.id})

        self.fp.assert_called_once()
        self.assertEqual(self.fp.call_args.args, ("https://fp.example/init_payment.php",))
        self.assertEqual(set(self.fp.call_args.kwargs), {"data", "timeout"})
        self.assertEqual(self.fp.call_args.kwargs["timeout"], 30)
        sent = dict(self.fp.call_args.kwargs["data"])
        salt, signature = sent.pop("pg_salt"), sent.pop("pg_sig")
        self.assertRegex(salt, r"^[0-9a-f]{32}$")
        self.assertRegex(order_id, rf"^tokpkg-{self.user.id}-{self.pkg.id}-[0-9a-f]{{10}}$")
        self.assertEqual(sent, {
            "pg_merchant_id": "m1",
            "pg_amount": "490.00",
            "pg_currency": "KGS",
            "pg_order_id": order_id,
            "pg_user_id": str(self.user.id),
            "pg_description": "EsAI: Про — 500 кредитов",
            "pg_language": "ru",
            "pg_user_contact_email": "buyer@example.com",
            "pg_success_url": "http://testserver/api/payments/tokens/success/",
            "pg_failure_url": "http://testserver/api/payments/tokens/failure/",
            "pg_result_url": "http://testserver/api/payments/tokens/postback/",
            "pg_request_method": "POST",
            "pg_testing_mode": 0,
            **extra})
        self.assertEqual(signature, make_api_signature(
            "init_payment", {**sent, "pg_salt": salt}, "secret"))

        payment = Payment.objects.get(order_id=order_id)
        self.assertEqual((payment.provider, payment.amount, payment.currency, payment.is_test),
                         ("freedompay", Decimal("490.00"), "KGS", False))
        self.assertEqual(payment.description, f"Token package purchase #{self.pkg.id}")
        expected_request = {
            "token_purchase": {"package_id": self.pkg.id, "tokens": 500, "bonus_tokens": 20,
                               "payload": {**sent, "pg_salt": salt, "pg_sig": signature}},
            "return_to": "/profile"}
        if method:
            expected_request["pay_method"] = method
        self.assertEqual(payment.request, expected_request)
        # Ни одного запроса к GoPay и ни одного счёта QR.
        self.assertEqual(self.bank.calls, [])
        self.assertEqual(GoPayInvoice.objects.count(), 0)

    def test_no_method_sends_the_old_request(self):
        self.assert_freedompay_request(None, {})

    def test_card_sends_the_old_request(self):
        self.assert_freedompay_request("card", {"pg_payment_method": "bankcard"})
