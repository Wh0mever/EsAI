# -*- coding: utf-8 -*-
"""Возврат покупки забирает и долю пригласившего, и платный тариф."""
from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings

from payments.models import Payment
from payments.views import _clawback_token_package_for_payment
from plans.models import TokenTransaction
from plans.wallet import credit_tokens

TEST_CACHES = {"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache",
                           "LOCATION": "payments-refund-tests"}}


@override_settings(CACHES=TEST_CACHES)
class RefundClawbackTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.referrer = User.objects.create_user(email="ref@example.com", password="x")
        self.buyer = User.objects.create_user(email="buyer@example.com", password="x")
        self.buyer.referred_by = self.referrer
        self.buyer.is_paid = True
        self.buyer.save(update_fields=["referred_by", "is_paid"])
        self.payment = Payment.objects.create(user=self.buyer, amount=490, currency="KGS",
                                              order_id="tokpkg-1", success=True)
        credit_tokens(self.buyer, 500, "purchase", meta={"order_id": "tokpkg-1"})
        credit_tokens(self.referrer, 50, "referral", meta={"order_id": "tokpkg-1"})

    def _refund(self):
        _clawback_token_package_for_payment(self.payment, "tokpkg-1", {})
        self.payment.save(update_fields=["response"])

    def test_refund_takes_back_referral_share_and_paid_tier(self):
        self._refund()
        self.buyer.refresh_from_db()
        self.referrer.refresh_from_db()
        self.assertEqual(self.buyer.token_balance, 0)
        self.assertFalse(self.buyer.is_paid)
        self.assertEqual(self.referrer.token_balance, 0)
        self.assertTrue(self.payment.response.get("paid_tier_revoked"))

    def test_repeat_refund_changes_nothing(self):
        self._refund()
        credit_tokens(self.referrer, 30, "purchase", meta={"order_id": "own"})
        self._refund()
        self.referrer.refresh_from_db()
        self.assertEqual(self.referrer.token_balance, 30)
        self.assertEqual(TokenTransaction.objects.filter(
            reason="refund", meta__kind="referral_clawback").count(), 1)

    def test_other_paid_purchase_keeps_tier(self):
        Payment.objects.create(user=self.buyer, amount=990, currency="KGS",
                               order_id="tokpkg-2", success=True)
        self._refund()
        self.buyer.refresh_from_db()
        self.assertTrue(self.buyer.is_paid)

    def test_partly_paid_crypto_invoice_keeps_tier(self):
        # Недоплаченный крипто-счёт: success=False, но кредиты по нему начислены.
        Payment.objects.create(user=self.buyer, amount=11, currency="USD",
                               order_id="tokpkg-crypto", success=False,
                               provider="crypto_nowpayments")
        credit_tokens(self.buyer, 900, "purchase", meta={"order_id": "tokpkg-crypto"})
        self._refund()
        self.buyer.refresh_from_db()
        self.assertTrue(self.buyer.is_paid)
        self.assertFalse(self.payment.response.get("paid_tier_revoked"))

    def test_earlier_refunded_purchase_does_not_keep_tier(self):
        Payment.objects.create(user=self.buyer, amount=990, currency="KGS", order_id="tokpkg-0",
                               success=True, response={"token_purchase_clawed_back": True})
        credit_tokens(self.buyer, 1000, "purchase", meta={"order_id": "tokpkg-0"})
        self._refund()
        self.buyer.refresh_from_db()
        self.assertFalse(self.buyer.is_paid)
