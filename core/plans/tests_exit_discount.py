# -*- coding: utf-8 -*-
"""Скидка при уходе срабатывает один раз.

Пока скидочная ссылка на оплату жива, скидка не переезжает на другой платёж:
иначе обе ссылки оставались оплачиваемыми со скидкой.
"""
from datetime import timedelta
from decimal import Decimal
from unittest.mock import MagicMock, patch

import requests
from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from audit.models import EventLog
from payments.models import Payment
from payments.views import _mark_exit_discount_redeemed
from plans.models import ExitDiscountOffer, TokenPackage

TEST_CACHES = {"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache",
                           "LOCATION": "plans-exit-discount-tests"}}


def _fp_ok(*args, **kwargs):
    resp = MagicMock(status_code=200)
    order_id = (kwargs.get("data") or {}).get("pg_order_id")
    resp.json.return_value = {"pg_status": "ok", "pg_redirect_url": f"https://pay.example/{order_id}"}
    return resp


@override_settings(CACHES=TEST_CACHES, FREEDOM_PAY_MERCHANT_ID="m1", FREEDOM_PAY_TOKEN="secret",
                   FREEDOM_PAY_INIT_PAYMENT_URL="https://fp.example/init_payment.php")
class ExitDiscountSingleUseTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(email="buyer@example.com", password="x")
        self.pkg_a = TokenPackage.objects.create(name="A", tokens=500, price=Decimal("490"))
        self.pkg_b = TokenPackage.objects.create(name="B", tokens=1000, price=Decimal("990"))
        now = timezone.now()
        self.offer = ExitDiscountOffer.objects.create(
            user=self.user, shown_at=now, claimed_at=now, percent=20,
            expires_at=now + timedelta(hours=2))
        self.client = APIClient()
        self.client.force_authenticate(self.user)

    def _buy(self, pkg):
        return self.client.post("/api/plans/purchase/", {"package_id": pkg.id}, format="json")

    @patch("plans.views.requests.post", side_effect=_fp_ok)
    def test_second_package_pays_full_price_while_discount_link_alive(self, post):
        r = self._buy(self.pkg_a)
        self.assertEqual(r.data["amount"], "392.00")
        first = Payment.objects.get(order_id=r.data["order_id"])
        # Скидочная ссылка живёт ограниченно, а не сутки по умолчанию.
        self.assertEqual(first.request["token_purchase"]["payload"]["pg_lifetime"], "1800")

        r = self._buy(self.pkg_b)
        self.assertEqual(r.data["amount"], "990.00")
        self.offer.refresh_from_db()
        self.assertEqual(self.offer.applied_to_payment_id, first.pk)

        # Возврат к пакету A — та же скидочная ссылка, третьей не появляется.
        r = self._buy(self.pkg_a)
        self.assertTrue(r.data.get("resumed"))
        self.assertEqual(r.data["order_id"], first.order_id)
        self.assertEqual(Payment.objects.filter(request__exit_discount__isnull=False).count(), 1)

    def test_offer_moves_when_first_link_never_appeared(self):
        with patch("plans.views.requests.post", side_effect=requests.RequestException("timeout")):
            self.assertEqual(self._buy(self.pkg_a).status_code, 502)
        with patch("plans.views.requests.post", side_effect=_fp_ok):
            r = self._buy(self.pkg_b)
        self.assertEqual(r.data["amount"], "792.00")
        self.offer.refresh_from_db()
        self.assertEqual(self.offer.applied_to_payment.order_id, r.data["order_id"])

    @patch("plans.views.requests.post", side_effect=_fp_ok)
    def test_offer_moves_after_discount_link_expired(self, post):
        first = self._buy(self.pkg_a).data
        Payment.objects.filter(order_id=first["order_id"]).update(
            created_at=timezone.now() - timedelta(minutes=32))
        r = self._buy(self.pkg_b)
        self.assertEqual(r.data["amount"], "792.00")

    @patch("plans.views.requests.post", side_effect=_fp_ok)
    def test_offer_stays_while_paid_link_awaits_confirmation(self, post):
        first = Payment.objects.get(order_id=self._buy(self.pkg_a).data["order_id"])
        response = dict(first.response)
        response["callbacks"] = [{"type": "success", "payload": {}, "presentational": True}]
        Payment.objects.filter(pk=first.pk).update(
            response=response, created_at=timezone.now() - timedelta(minutes=40))
        self.assertEqual(self._buy(self.pkg_b).data["amount"], "990.00")

    def test_paid_link_without_the_offer_is_credited_but_flagged(self):
        now = timezone.now()
        holder = Payment.objects.create(user=self.user, amount=392, currency="KGS",
                                        order_id="tokpkg-hold", request={}, response={})
        stray = Payment.objects.create(
            user=self.user, amount=792, currency="KGS", order_id="tokpkg-stray", success=True,
            request={"exit_discount": {"offer_id": self.offer.pk, "percent": 20}}, response={})
        self.offer.applied_to_payment = holder
        self.offer.save(update_fields=["applied_to_payment"])

        _mark_exit_discount_redeemed(stray)

        self.offer.refresh_from_db()
        self.assertIsNotNone(self.offer.redeemed_at)
        self.assertGreaterEqual(self.offer.redeemed_at, now)
        self.assertTrue(EventLog.objects.filter(message__startswith="exit_discount_reused",
                                                meta__needs_review=True).exists())

    def test_own_payment_redeems_without_flag(self):
        own = Payment.objects.create(
            user=self.user, amount=392, currency="KGS", order_id="tokpkg-own", success=True,
            request={"exit_discount": {"offer_id": self.offer.pk, "percent": 20}}, response={})
        self.offer.applied_to_payment = own
        self.offer.save(update_fields=["applied_to_payment"])
        _mark_exit_discount_redeemed(own)
        self.offer.refresh_from_db()
        self.assertIsNotNone(self.offer.redeemed_at)
        self.assertFalse(EventLog.objects.filter(message__startswith="exit_discount_reused").exists())
