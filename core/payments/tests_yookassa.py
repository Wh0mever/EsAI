# -*- coding: utf-8 -*-
"""ЮKassa: вебхук просит повтор при сбое, сверка дозачисляет пропущенное."""
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from payments.models import Payment
from payments.tasks import reconcile_yookassa_payments
from plans.models import TokenPackage, TokenTransaction

TEST_CACHES = {"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache",
                           "LOCATION": "payments-yookassa-tests"}}


def _fresh(order_id, status="succeeded", paid=True, value="490.00"):
    return {"id": "yk-1", "status": status, "paid": paid,
            "amount": {"value": value, "currency": "RUB"},
            "metadata": {"order_id": order_id}}


@override_settings(CACHES=TEST_CACHES, YOOKASSA_SHOP_ID="shop", YOOKASSA_SECRET_KEY="secret")
class YooKassaTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(email="rub@example.com", password="x")
        self.package = TokenPackage.objects.create(name="Про", tokens=500, price=490, is_active=True)
        self.payment = Payment.objects.create(
            user=self.user, provider="yookassa", amount="490.00", currency="RUB",
            order_id=f"tokpkg-{self.user.pk}-{self.package.pk}-abc",
            request={"provider": "yookassa", "yookassa_payment_id": "yk-1",
                     "token_purchase": {"package_id": self.package.pk, "tokens": 500,
                                        "bonus_tokens": 0}},
        )

    def _credited(self):
        return TokenTransaction.objects.filter(reason="purchase",
                                               meta__order_id=self.payment.order_id).count()

    def test_webhook_asks_for_retry_when_api_is_down(self):
        with patch("payments.yookassa.fetch_payment", side_effect=RuntimeError("down")):
            r = APIClient().post("/api/payments/yookassa/webhook/",
                                 {"event": "payment.succeeded", "object": {"id": "yk-1"}},
                                 format="json")
        self.assertEqual(r.status_code, 503)
        self.assertEqual(self._credited(), 0)

    def test_reconcile_credits_missed_payment_once(self):
        with patch("payments.yookassa.fetch_payment", return_value=_fresh(self.payment.order_id)):
            first = reconcile_yookassa_payments()
            second = reconcile_yookassa_payments()
        self.assertEqual(first["credited"], 1)
        self.assertEqual(second["checked"], 0)
        self.assertEqual(self._credited(), 1)
        self.user.refresh_from_db()
        self.assertEqual(self.user.token_balance, 500)

    def test_reconcile_leaves_pending_and_closes_canceled(self):
        with patch("payments.yookassa.fetch_payment",
                   return_value=_fresh(self.payment.order_id, status="pending", paid=False)):
            self.assertEqual(reconcile_yookassa_payments()["credited"], 0)
        self.payment.refresh_from_db()
        self.assertEqual(self.payment.error or "", "")
        with patch("payments.yookassa.fetch_payment",
                   return_value=_fresh(self.payment.order_id, status="canceled", paid=False)):
            reconcile_yookassa_payments()
        self.payment.refresh_from_db()
        self.assertTrue(self.payment.error.startswith("yookassa_status:"))
        with patch("payments.yookassa.fetch_payment") as fetch:
            reconcile_yookassa_payments()
        fetch.assert_not_called()
