# -*- coding: utf-8 -*-
"""BE-1: шаги воронки видеостудии (спецификация §11) и строки отчёта."""
from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from payments.funnel import funnel_report, studio_report, vstudio_report
from payments.models import FunnelEvent, Payment

CACHES = {"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache",
                      "LOCATION": "vstudio-be1-funnel"}}

VSTUDIO_STEPS = ("vstudio_view", "vstudio_upload", "vstudio_mention", "vstudio_imagegen",
                 "vstudio_blocked", "vstudio_run_click", "vstudio_paywall",
                 "vstudio_auth_prompt", "vstudio_condense", "vstudio_share")


@override_settings(CACHES=CACHES)
class FunnelEventWhitelistTests(TestCase):
    def setUp(self):
        cache.clear()

    def test_all_vstudio_steps_accepted(self):
        client = APIClient()
        for name in VSTUDIO_STEPS:
            with self.subTest(name=name):
                self.assertIn(name, FunnelEvent.NAMES)
                self.assertLessEqual(len(name), FunnelEvent._meta.get_field("name").max_length)
                res = client.post("/api/payments/funnel/event/",
                                  {"name": name, "meta": {"ok": True}}, format="json",
                                  HTTP_X_DEVICE_KEY="dev-1")
                self.assertEqual(res.status_code, 201)
        self.assertEqual(FunnelEvent.objects.filter(name__startswith="vstudio_").count(),
                         len(VSTUDIO_STEPS))

    def test_unknown_vstudio_step_rejected(self):
        res = APIClient().post("/api/payments/funnel/event/", {"name": "vstudio_done"}, format="json")
        self.assertEqual(res.status_code, 400)


class VstudioReportTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(email="u@example.com", password="x-12345678")
        self.since = timezone.now() - timedelta(days=30)

    def _ev(self, name, device, user=None, **meta):
        FunnelEvent.objects.create(name=name, device_key=device, user=user, meta=meta)

    def _paid(self, return_to):
        Payment.objects.create(user=self.user, amount=Decimal("10"), success=True,
                               request={"token_purchase": {"package_id": 1}, "return_to": return_to})

    def _row(self, rows, key):
        return next(r for r in rows if r["key"] == key)

    def test_rows_counted_by_device(self):
        # Два устройства открыли студию гостями, одно из них потом вошло.
        self._ev("vstudio_view", "d1")
        self._ev("vstudio_view", "d1")          # повтор того же устройства — один человек
        self._ev("vstudio_view", "d2")
        self._ev("vstudio_auth_prompt", "d1")
        self._ev("vstudio_run_click", "d1", user=self.user, model="bytedance/seedance-2.0")
        self._ev("vstudio_upload", "d1", user=self.user, ok=True)
        self._ev("vstudio_upload", "d2", ok=False, code="unsupported_image")
        self._ev("vstudio_mention", "d1", user=self.user, via="at")
        self._ev("vstudio_share", "d1", user=self.user)
        # Шаги мультстудии в эту воронку не попадают.
        self._ev("studio_view", "d3")

        rows = vstudio_report(self.since)
        self.assertEqual(rows[0]["key"], "vstudio_view")
        self.assertEqual(self._row(rows, "vstudio_view")["count"], 2)
        self.assertEqual(self._row(rows, "vstudio_view")["share"], 100)
        self.assertEqual(self._row(rows, "vstudio_auth_prompt")["count"], 1)
        self.assertEqual(self._row(rows, "registered")["count"], 1)
        self.assertEqual(self._row(rows, "vstudio_upload")["count"], 1)
        self.assertEqual(self._row(rows, "vstudio_upload_failed")["count"], 1)
        self.assertEqual(self._row(rows, "vstudio_run_click")["count"], 1)
        self.assertEqual(self._row(rows, "vstudio_run_click")["share"], 50)
        self.assertEqual(self._row(rows, "vstudio_mention")["count"], 1)
        self.assertEqual(self._row(rows, "vstudio_share")["count"], 1)
        self.assertEqual(self._row(rows, "vstudio_paywall")["count"], 0)
        for row in rows:
            self.assertTrue(row["label"])

    def test_empty_period_has_no_shares(self):
        rows = vstudio_report(self.since)
        self.assertTrue(all(r["count"] == 0 and r["share"] is None for r in rows))

    def test_paid_split_between_studios(self):
        # «/video-studio» содержит «studio» — оплата отсюда не должна
        # засчитываться мультстудии.
        self._paid("/video-studio/0123456789abcdef0123456789abcdef")
        self._paid("/video-studio")
        self._paid("/studio")
        self._paid("/profile")
        self.assertEqual(self._row(vstudio_report(self.since), "paid")["count"], 2)
        self.assertEqual(self._row(studio_report(self.since), "paid")["count"], 1)

    def test_funnel_report_has_vstudio_section(self):
        self._ev("vstudio_view", "d1")
        report = funnel_report(30)
        self.assertIn("vstudio", report)
        self.assertEqual(report["vstudio"][0]["count"], 1)
        self.assertIn("studio", report)
