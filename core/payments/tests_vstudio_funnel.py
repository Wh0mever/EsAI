# -*- coding: utf-8 -*-
"""BE-1: шаги воронки видеостудии (спецификация §11) и строки отчёта."""
from datetime import timedelta
from decimal import Decimal
from unittest import mock

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient
from rest_framework.throttling import AnonRateThrottle, SimpleRateThrottle

from payments import funnel
from payments.funnel import FunnelEventView, funnel_report, studio_report, vstudio_report
from payments.models import FunnelEvent, Payment

CACHES = {"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache",
                      "LOCATION": "vstudio-be1-funnel"}}

VSTUDIO_STEPS = ("vstudio_view", "vstudio_upload", "vstudio_mention", "vstudio_imagegen",
                 "vstudio_blocked", "vstudio_run_click", "vstudio_paywall",
                 "vstudio_auth_prompt", "vstudio_condense", "vstudio_share",
                 "vstudio_home_pick")


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

    def test_home_pick_keeps_what_was_clicked(self):
        meta = {"what": "template", "id": "film"}
        res = APIClient().post("/api/payments/funnel/event/",
                               {"name": "vstudio_home_pick", "meta": meta}, format="json",
                               HTTP_X_DEVICE_KEY="dev-1")
        self.assertEqual(res.status_code, 201)
        event = FunnelEvent.objects.get(name="vstudio_home_pick")
        self.assertEqual((event.meta, event.device_key, event.user), (meta, "dev-1", None))

    def test_home_pick_from_carousel_is_accepted(self):
        # Карусель шлёт what="reel" и id работы витрины. "showcase" слал блок под
        # ней: блока больше нет, но вкладка, открытая до выкладки, ещё пришлёт.
        for what in ("reel", "showcase"):
            with self.subTest(what=what):
                meta = {"what": what, "id": "vs:12"}
                res = APIClient().post("/api/payments/funnel/event/",
                                       {"name": "vstudio_home_pick", "meta": meta}, format="json",
                                       HTTP_X_DEVICE_KEY="dev-1")
                self.assertEqual(res.status_code, 201)
                self.assertEqual(FunnelEvent.objects.filter(name="vstudio_home_pick").latest("pk").meta, meta)


@override_settings(CACHES=CACHES)
class FunnelThrottleTests(TestCase):
    """Клики первого экрана не должны съедать лимит, из которого берёт вход по почте."""

    URL = "/api/payments/funnel/event/"
    EVENT = {"name": "vstudio_home_pick", "meta": {"what": "template", "id": "film"}}

    def setUp(self):
        cache.clear()
        self.guest = APIClient()

    def test_events_do_not_spend_the_shared_anon_bucket(self):
        self.assertEqual(FunnelEventView.throttle_classes, [funnel._FunnelThrottle])
        self.assertNotEqual(funnel._FunnelThrottle.scope, AnonRateThrottle.scope)
        with mock.patch.dict(SimpleRateThrottle.THROTTLE_RATES, {"anon": "1/min"}):
            for _ in range(5):
                res = self.guest.post(self.URL, self.EVENT, format="json")
                self.assertEqual(res.status_code, 201)
            # Общий счётчик гостя цел: первый обычный запрос проходит, второй
            # упирается в лимит — значит, пять шагов выше в него не попали.
            first = self.guest.get("/api/plans/bonus-settings/")
            second = self.guest.get("/api/plans/bonus-settings/")
        self.assertEqual((first.status_code, second.status_code), (200, 429))

    def test_own_limit_still_holds(self):
        with mock.patch.object(funnel._FunnelThrottle, "rate", "2/min"):
            codes = [self.guest.post(self.URL, self.EVENT, format="json").status_code
                     for _ in range(3)]
        self.assertEqual(codes, [201, 201, 429])
        self.assertEqual(FunnelEvent.objects.count(), 2)


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
        # Первый экран: одно устройство нажало дважды — это один человек.
        self._ev("vstudio_home_pick", "d1", what="template", id="film")
        self._ev("vstudio_home_pick", "d1", what="model", id="bytedance/seedance-2.0")
        # Шаги мультстудии в эту воронку не попадают.
        self._ev("studio_view", "d3")

        rows = vstudio_report(self.since)
        self.assertEqual(rows[0]["key"], "vstudio_view")
        self.assertEqual(self._row(rows, "vstudio_view")["count"], 2)
        self.assertEqual(self._row(rows, "vstudio_view")["share"], 100)
        # Клик на первом экране — сразу за открытием: с него путь и начинается.
        self.assertEqual((rows[1]["key"], rows[1]["label"]),
                         ("vstudio_home_pick", "Нажали на первом экране"))
        self.assertEqual((rows[1]["count"], rows[1]["share"]), (1, 50))
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
