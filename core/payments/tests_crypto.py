# -*- coding: utf-8 -*-
"""Тесты криптооплаты: подпись, арифметика начисления, вебхук, покупка.

Ни один тест не ходит в сеть: процессор подменяется заглушкой, поэтому
проверяется именно наша логика — деньги, идемпотентность и отказы.
"""
import hashlib
import hmac
import json
from datetime import timedelta
from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIRequestFactory, force_authenticate

from payments.crypto import base, credit
from payments.crypto.nowpayments import NowPayments
from payments.crypto.views import NowPaymentsIpnView
from payments.models import CryptoInvoice, CryptoWebhookEvent, Payment
from plans.models import TokenPackage, TokenTransaction
from plans.views import TokenPurchaseView

IPN_SECRET = "test-ipn-secret"


# ------------------------------------------------------------- заглушка ---

class FakeAdapter:
    """Процессор, который отвечает то, что ему велели."""

    name = "nowpayments"

    def __init__(self, state=None, invoice=None, fail=None):
        self._state = state
        self._invoice = invoice
        self._fail = fail
        self.fetch_calls = 0

    def is_configured(self):
        return True

    def verify_webhook(self, request):
        return json.loads(request.body or b"{}")

    def fetch_invoice(self, provider_id):
        self.fetch_calls += 1
        if self._fail:
            raise self._fail
        return self._state

    def create_invoice(self, **kwargs):
        if self._fail:
            raise self._fail
        return self._invoice

    def min_amount_usd(self, code):
        return Decimal("1.00")

    def list_currencies(self):
        return ["usdttrc20", "btc", "ton"]

    def healthcheck(self):
        return {"ok": True}


def make_state(**over):
    data = dict(
        provider_id="np-1", order_id="tokpkg-1-1-abc", status=base.FINISHED,
        provider_status="finished", price_amount=Decimal("10.00"), price_currency="USD",
        pay_currency="usdttrc20", pay_amount=Decimal("10.5"),
        actually_paid=Decimal("10.5"), raw={"payment_status": "finished"},
    )
    data.update(over)
    return base.InvoiceState(**data)


# --------------------------------------------------------------- подпись ---

class SignatureTests(TestCase):
    def setUp(self):
        self.adapter = NowPayments(api_key="k", ipn_secret=IPN_SECRET)

    @staticmethod
    def _sign(body: dict, secret: str = IPN_SECRET) -> str:
        message = json.dumps(body, sort_keys=True, separators=(",", ":"))
        return hmac.new(secret.encode(), message.encode(), hashlib.sha512).hexdigest()

    def _request(self, body: dict, signature: str):
        request = APIRequestFactory().post("/ipn/", data=body, format="json")
        request.META["HTTP_X_NOWPAYMENTS_SIG"] = signature
        # DRF-запрос отдаёт тело так же, как настоящий.
        return request

    def test_valid_signature_passes(self):
        body = {"payment_id": "np-1", "payment_status": "finished", "actually_paid": 10.5}
        self.assertEqual(
            self.adapter.verify_webhook(self._request(body, self._sign(body))), body)

    def test_tampered_body_rejected(self):
        body = {"payment_id": "np-1", "payment_status": "waiting"}
        signature = self._sign(body)
        forged = dict(body, payment_status="finished")
        self.assertIsNone(self.adapter.verify_webhook(self._request(forged, signature)))

    def test_wrong_secret_rejected(self):
        body = {"payment_id": "np-1"}
        self.assertIsNone(
            self.adapter.verify_webhook(self._request(body, self._sign(body, "другой"))))

    def test_garbage_signature_rejected(self):
        body = {"payment_id": "np-1"}
        for signature in ("", "не-hex" * 20, "ab" * 10):
            self.assertIsNone(self.adapter.verify_webhook(self._request(body, signature)))

    def test_without_secret_nothing_passes(self):
        adapter = NowPayments(api_key="k", ipn_secret="")
        body = {"payment_id": "np-1"}
        self.assertIsNone(adapter.verify_webhook(self._request(body, self._sign(body))))


# ------------------------------------------------------------ арифметика ---

@override_settings(CRYPTO_FULL_TOLERANCE_PERCENT=0.5, CRYPTO_OVERPAY_CAP_PERCENT=200)
class EntitledCreditsTests(TestCase):
    def check(self, paid, expected_credits, expected_kind, total=1000, expected=Decimal("10")):
        credits, kind = credit.entitled_credits(total, expected, Decimal(str(paid)))
        self.assertEqual((credits, kind), (expected_credits, expected_kind), f"paid={paid}")

    def test_exact_payment(self):
        self.check("10", 1000, "full")

    def test_dust_shortfall_counts_as_full(self):
        # Комиссию сети платит отправитель: копеечная недостача не должна
        # лишать человека всего пакета.
        self.check("9.96", 1000, "full")

    def test_half_payment(self):
        self.check("5", 500, "partial")

    def test_visible_shortfall(self):
        self.check("9", 900, "partial")

    def test_small_overpay(self):
        self.check("12", 1200, "over")

    def test_overpay_capped(self):
        self.check("50", 2000, "over_capped")

    def test_absurd_ratio_gets_nothing(self):
        self.check("2000", 0, "anomaly_ratio")

    def test_nothing_paid(self):
        self.check("0", 0, "nothing_paid")

    def test_tiny_payment_still_gives_one_credit(self):
        credits, kind = credit.entitled_credits(1000, Decimal("10"), Decimal("0.0001"))
        self.assertEqual((credits, kind), (1, "partial"))


# ----------------------------------------------------------- стейт-машина ---

class CreditFlowTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            email="crypto@example.com", password="testpass123")
        self.payment = Payment.objects.create(
            user=self.user, provider="crypto_nowpayments", amount=Decimal("10.00"),
            currency="USD", order_id="tokpkg-1-1-abc",
            request={"token_purchase": {"package_id": 1, "tokens": 900, "bonus_tokens": 100}},
            response={},
        )
        self.invoice = CryptoInvoice.objects.create(
            payment=self.payment, provider="nowpayments", provider_invoice_id="np-1",
            price_amount=Decimal("10.00"), price_currency="USD",
            pay_currency="usdttrc20", pay_coin="USDT", pay_network="TRC-20",
            pay_address="TX-address", pay_amount=Decimal("10.5"),
        )

    def balance(self):
        self.user.refresh_from_db()
        return int(self.user.token_balance or 0)

    def test_full_payment_credits_once(self):
        state = make_state()
        self.assertEqual(credit.apply_provider_status(self.invoice, state), "credited")
        self.assertEqual(self.balance(), 1000)

        # Повтор того же ответа ничего не добавляет.
        self.assertEqual(credit.apply_provider_status(self.invoice, state), "noop")
        self.assertEqual(self.balance(), 1000)
        self.payment.refresh_from_db()
        self.assertTrue(self.payment.success)
        self.assertEqual(
            TokenTransaction.objects.filter(user=self.user, reason="purchase").count(), 1)

    def test_partial_then_topup_gives_exactly_package(self):
        half = make_state(status=base.PARTIALLY_PAID, provider_status="partially_paid",
                          actually_paid=Decimal("5.25"))
        self.assertEqual(credit.apply_provider_status(self.invoice, half), "credited")
        self.assertEqual(self.balance(), 500)
        self.payment.refresh_from_db()
        self.assertFalse(self.payment.success)

        self.invoice.refresh_from_db()
        rest = make_state(actually_paid=Decimal("10.5"))
        self.assertEqual(credit.apply_provider_status(self.invoice, rest), "credited")
        self.assertEqual(self.balance(), 1000)
        self.assertEqual(
            TokenTransaction.objects.filter(user=self.user, reason="purchase").count(), 2)
        self.payment.refresh_from_db()
        self.assertTrue(self.payment.success)

    def test_status_does_not_roll_back(self):
        credit.apply_provider_status(self.invoice, make_state())
        self.invoice.refresh_from_db()
        stale = make_state(status=base.WAITING, provider_status="waiting",
                           actually_paid=Decimal("0"))
        credit.apply_provider_status(self.invoice, stale)
        self.assertEqual(self.balance(), 1000)
        self.invoice.refresh_from_db()
        self.assertEqual(self.invoice.actually_paid, Decimal("10.5"))

    def test_price_mismatch_blocks_credit(self):
        state = make_state(price_amount=Decimal("1.00"))
        self.assertEqual(credit.apply_provider_status(self.invoice, state), "amount_mismatch")
        self.assertEqual(self.balance(), 0)
        self.invoice.refresh_from_db()
        self.assertIn("needs_review", self.invoice.flags)

    def test_foreign_order_blocks_credit(self):
        state = make_state(order_id="tokpkg-99-9-zzz")
        self.assertEqual(credit.apply_provider_status(self.invoice, state), "amount_mismatch")
        self.assertEqual(self.balance(), 0)

    def test_refund_only_flags(self):
        credit.apply_provider_status(self.invoice, make_state())
        self.invoice.refresh_from_db()
        credit.apply_provider_status(
            self.invoice, make_state(status=base.REFUNDED, provider_status="refunded"))
        # Кредиты не изымаются автоматом: крипту назад не вернуть, решает человек.
        self.assertEqual(self.balance(), 1000)
        self.invoice.refresh_from_db()
        self.assertTrue(self.invoice.flags.get("refund_seen"))

    def test_late_payment_after_expiry_is_credited(self):
        state = make_state(status=base.EXPIRED, provider_status="expired")
        self.assertEqual(credit.apply_provider_status(self.invoice, state), "credited")
        self.assertEqual(self.balance(), 1000)

    def test_expired_without_payment_is_closed(self):
        state = make_state(status=base.EXPIRED, provider_status="expired",
                           actually_paid=Decimal("0"))
        credit.apply_provider_status(self.invoice, state)
        self.assertEqual(self.balance(), 0)
        self.payment.refresh_from_db()
        self.assertIn("crypto_status:expired", self.payment.error or "")

    def test_unknown_status_changes_nothing(self):
        state = make_state(status=base.UNKNOWN, provider_status="что-то новое",
                           actually_paid=Decimal("0"))
        credit.apply_provider_status(self.invoice, state)
        self.invoice.refresh_from_db()
        self.assertEqual(self.invoice.status, CryptoInvoice.STATUS_WAITING)
        self.assertIn("unknown_status", self.invoice.flags)


# ----------------------------------------------------------------- вебхук ---

class IpnViewTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            email="ipn@example.com", password="testpass123")
        self.payment = Payment.objects.create(
            user=self.user, provider="crypto_nowpayments", amount=Decimal("10.00"),
            currency="USD", order_id="tokpkg-1-1-abc",
            request={"token_purchase": {"package_id": 1, "tokens": 1000, "bonus_tokens": 0}},
            response={},
        )
        self.invoice = CryptoInvoice.objects.create(
            payment=self.payment, provider="nowpayments", provider_invoice_id="np-1",
            price_amount=Decimal("10.00"), pay_currency="usdttrc20", pay_coin="USDT",
            pay_network="TRC-20", pay_address="TX", pay_amount=Decimal("10.5"),
        )
        self.body = {"payment_id": "np-1", "payment_status": "finished",
                     "actually_paid": 10.5, "updated_at": "2026-09-05T10:00:00Z"}

    def _post(self, adapter, body=None):
        with patch("payments.crypto.registry.get_adapter", return_value=adapter):
            request = APIRequestFactory().post("/ipn/", data=body or self.body, format="json")
            return NowPaymentsIpnView.as_view()(request)

    def balance(self):
        self.user.refresh_from_db()
        return int(self.user.token_balance or 0)

    def test_credits_only_after_refetch(self):
        adapter = FakeAdapter(state=make_state())
        response = self._post(adapter)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(adapter.fetch_calls, 1)
        self.assertEqual(self.balance(), 1000)

    def test_lying_body_cannot_credit(self):
        # Вебхук говорит «оплачено», а процессор — «ждём»: верим процессору.
        adapter = FakeAdapter(state=make_state(status=base.WAITING,
                                               provider_status="waiting",
                                               actually_paid=Decimal("0")))
        self._post(adapter)
        self.assertEqual(self.balance(), 0)

    def test_replay_is_ignored(self):
        adapter = FakeAdapter(state=make_state())
        self._post(adapter)
        second = self._post(adapter)
        self.assertEqual(second.data.get("status"), "duplicate")
        self.assertEqual(self.balance(), 1000)
        self.assertEqual(
            TokenTransaction.objects.filter(user=self.user, reason="purchase").count(), 1)

    def test_bad_signature_returns_400(self):
        class Rejecting(FakeAdapter):
            def verify_webhook(self, request):
                return None

        response = self._post(Rejecting())
        self.assertEqual(response.status_code, 400)
        self.assertEqual(CryptoWebhookEvent.objects.count(), 0)
        self.assertEqual(self.balance(), 0)

    def test_provider_down_asks_to_retry(self):
        adapter = FakeAdapter(fail=base.ProviderUnavailable("timeout"))
        response = self._post(adapter)
        self.assertEqual(response.status_code, 503)
        event = CryptoWebhookEvent.objects.get()
        self.assertFalse(event.processed)

        # Повторная доставка того же уведомления доводит дело до конца.
        ok = self._post(FakeAdapter(state=make_state()))
        self.assertEqual(ok.status_code, 200)
        self.assertEqual(self.balance(), 1000)

    def test_orphan_invoice_is_adopted(self):
        self.invoice.delete()
        adapter = FakeAdapter(state=make_state(pay_address="TX", pay_extra_id=""))
        self._post(adapter)
        self.assertEqual(self.balance(), 1000)
        invoice = CryptoInvoice.objects.get(provider_invoice_id="np-1")
        self.assertTrue(invoice.flags.get("adopted"))

    def test_unknown_payment_is_ignored(self):
        self.invoice.delete()
        self.payment.delete()
        adapter = FakeAdapter(state=make_state())
        response = self._post(adapter)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(CryptoWebhookEvent.objects.get().result, "unknown_invoice")


# ---------------------------------------------------------------- покупка ---

@override_settings(SITE_BASE_URL="https://esai.test", CRYPTO_PAYMENTS_MODE="on",
                   NOWPAYMENTS_API_KEY="k",
                   CRYPTO_ALLOWED_CURRENCIES="usdttrc20,btc,ton")
class PurchaseTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            email="buyer@example.com", password="testpass123")
        self.package = TokenPackage.objects.create(
            name="Про", tokens=1000, bonus_tokens=100, price=Decimal("990"),
            currency="KGS", is_active=True)

    def _buy(self, **payload):
        body = {"package_id": self.package.id, "pay_currency": "USD",
                "crypto_currency": "usdttrc20"}
        body.update(payload)
        request = APIRequestFactory().post("/purchase/", body, format="json")
        force_authenticate(request, user=self.user)
        return TokenPurchaseView.as_view()(request)

    def _adapter(self, **over):
        invoice = base.Invoice(
            provider="nowpayments", provider_id="np-77",
            order_id=over.get("order_id", ""), price_amount=Decimal("11.39"),
            price_currency="USD", pay_currency="usdttrc20", pay_coin="USDT",
            pay_network="TRC-20", pay_address="TX-address", pay_extra_id="",
            pay_amount=Decimal("11.45"), expires_at=None, raw={},
        )
        return FakeAdapter(invoice=invoice, **over)

    def test_creates_invoice(self):
        adapter = self._adapter()
        with patch("payments.crypto.registry.get_adapter", return_value=adapter):
            response = self._buy()
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["kind"], "crypto")
        self.assertEqual(response.data["pay"]["address"], "TX-address")
        payment = Payment.objects.get(order_id=response.data["order_id"])
        self.assertEqual(payment.currency, "USD")
        self.assertEqual(payment.provider, "crypto_nowpayments")

    def test_second_click_returns_same_invoice(self):
        adapter = self._adapter()
        with patch("payments.crypto.registry.get_adapter", return_value=adapter):
            first = self._buy()
            second = self._buy()
        self.assertEqual(first.data["order_id"], second.data["order_id"])
        self.assertTrue(second.data["resumed"])
        self.assertEqual(CryptoInvoice.objects.count(), 1)

    @override_settings(CRYPTO_PAYMENTS_MODE="off")
    def test_disabled_mode_forbids(self):
        response = self._buy()
        self.assertEqual(response.status_code, 403)
        self.assertEqual(CryptoInvoice.objects.count(), 0)

    def test_unknown_currency_rejected(self):
        response = self._buy(crypto_currency="dogecoin-classic")
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data["detail"], "crypto_currency_not_supported")

    def test_below_minimum_is_explained(self):
        class Pricey(FakeAdapter):
            def min_amount_usd(self, code):
                return Decimal("50")

        with patch("payments.crypto.registry.get_adapter", return_value=Pricey()):
            response = self._buy()
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data["detail"], "crypto_amount_below_min")
        self.assertEqual(response.data["min_usd"], "50")

    def test_provider_failure_leaves_no_invoice(self):
        adapter = self._adapter(fail=base.ProviderError("нет монеты", code="http_400"))
        with patch("payments.crypto.registry.get_adapter", return_value=adapter):
            response = self._buy()
        self.assertEqual(response.status_code, 502)
        self.assertEqual(CryptoInvoice.objects.count(), 0)
        payment = Payment.objects.get()
        self.assertEqual(payment.error, "crypto_create_failed:http_400")
        self.assertFalse(payment.success)

    def test_status_of_foreign_order_is_hidden(self):
        adapter = self._adapter()
        with patch("payments.crypto.registry.get_adapter", return_value=adapter):
            created = self._buy()
        stranger = get_user_model().objects.create_user(
            email="stranger@example.com", password="testpass123")

        from payments.crypto.views import CryptoInvoiceStatusView

        request = APIRequestFactory().get("/status/")
        force_authenticate(request, user=stranger)
        response = CryptoInvoiceStatusView.as_view()(request, order_id=created.data["order_id"])
        self.assertEqual(response.status_code, 404)

# ------------------------------------------------------------------ сроки ---

class LocalExpiryTests(TestCase):
    """Счёт закрываем сами, только когда он действительно просрочен.

    Закрыть действующий счёт по ошибке — значит сказать человеку «не успели»,
    когда он ещё успевал, и потерять оплату, которая уже в пути.
    """

    def setUp(self):
        self.user = get_user_model().objects.create_user(
            email="expiry@example.com", password="testpass123")
        payment = Payment.objects.create(
            user=self.user, provider="crypto_nowpayments", amount=Decimal("10.00"),
            currency="USD", order_id="tokpkg-1-1-exp",
            request={"token_purchase": {"package_id": 1, "tokens": 1000, "bonus_tokens": 0}},
            response={},
        )
        self.invoice = CryptoInvoice.objects.create(
            payment=payment, provider="nowpayments", provider_invoice_id="np-exp",
            price_amount=Decimal("10.00"), pay_currency="usdttrc20", pay_coin="USDT",
            pay_network="TRC-20", pay_address="TX", pay_amount=Decimal("10.5"),
            expires_at=timezone.now() + timedelta(minutes=30),
        )

    def test_live_invoice_is_left_alone(self):
        credit.mark_expired_locally(self.invoice)
        self.invoice.refresh_from_db()
        self.assertEqual(self.invoice.status, CryptoInvoice.STATUS_WAITING)

    def test_just_expired_still_waits_out_the_grace(self):
        self.invoice.expires_at = timezone.now() - timedelta(minutes=5)
        self.invoice.save(update_fields=["expires_at"])
        credit.mark_expired_locally(self.invoice)
        self.invoice.refresh_from_db()
        self.assertEqual(self.invoice.status, CryptoInvoice.STATUS_WAITING)

    def test_long_expired_is_closed(self):
        self.invoice.expires_at = timezone.now() - timedelta(hours=2)
        self.invoice.save(update_fields=["expires_at"])
        credit.mark_expired_locally(self.invoice)
        self.invoice.refresh_from_db()
        self.assertEqual(self.invoice.status, CryptoInvoice.STATUS_EXPIRED)

    def test_paid_invoice_is_never_closed_locally(self):
        self.invoice.expires_at = timezone.now() - timedelta(hours=2)
        self.invoice.actually_paid = Decimal("10.5")
        self.invoice.save(update_fields=["expires_at", "actually_paid"])
        credit.mark_expired_locally(self.invoice)
        self.invoice.refresh_from_db()
        self.assertEqual(self.invoice.status, CryptoInvoice.STATUS_WAITING)
