# -*- coding: utf-8 -*-
"""F27: событие «Скачать» (media_save) — белый список полей и просмотр в админке."""
import json

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from payments.funnel import MEDIA_SAVE_FIELDS, media_save_meta
from payments.models import FunnelEvent

CACHES = {"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache",
                      "LOCATION": "f27-media-save"}}
URL = "/api/payments/funnel/event/"

# То, что шлёт фронт (next/src/tools/saveEnv.ts, saveDiagMeta), — Telegram на iPhone.
GOOD = {
    "v": "s3", "where": "vstudio", "kind": "video", "step": "share", "result": "sheet",
    "err": "NotAllowedError", "stage": "share", "os": "ios", "os_ver": "26.0", "browser": "safari",
    "inapp": "telegram", "standalone": False, "frozen": False, "has_share": True,
    "has_can_share": True, "can_share_file": True, "wait_ms": 6200, "prefetch_hit": False,
    "size_kb": 3072, "type_ok": True, "http": 200, "n": 1, "diag": "K7Q2XM", "vis": True,
}


@override_settings(CACHES=CACHES)
class MediaSaveEventTests(TestCase):
    def setUp(self):
        cache.clear()
        self.client = APIClient()

    def _post(self, meta, **extra):
        return self.client.post(URL, {"name": "media_save", "meta": meta}, format="json",
                                HTTP_X_DEVICE_KEY="dev-ios", **extra)

    def test_frontend_meta_is_stored_as_is(self):
        self.assertIn("media_save", FunnelEvent.NAMES)
        self.assertEqual(set(GOOD), MEDIA_SAVE_FIELDS, "белый список совпадает с полями фронта")
        res = self._post(GOOD)
        self.assertEqual(res.status_code, 201)
        event = FunnelEvent.objects.get(name="media_save")
        self.assertEqual((event.meta, event.device_key, event.user), (GOOD, "dev-ios", None))

    def test_unknown_keys_nested_objects_and_urls_are_dropped(self):
        meta = dict(GOOD)
        meta.update({
            "url": "https://esai.kg/media/vstudio/secret.mp4",
            "ua": "Mozilla/5.0 (iPhone; CPU iPhone OS 18_6 like Mac OS X)",
            "nested": {"a": 1},
            "where": "https://esai.kg/video-studio/3f9c1d2e",   # не из перечисления → other
            "browser": ["safari"],                              # не строка → выброшено
            "err": "Load failed https://esai.kg/media/x.mp4",   # сообщение вместо имени → other
            "os_ver": "26.0; Mozilla",
            "diag": "k7q2xm/../x",
            "v": {"x": 1},
            "http": True,                                       # bool — не код ответа
            "wait_ms": 10 ** 9,
            "n": -5,
            "vis": "yes",
        })
        self.assertEqual(self._post(meta).status_code, 201)
        stored = FunnelEvent.objects.get(name="media_save").meta
        self.assertTrue(set(stored) <= MEDIA_SAVE_FIELDS, stored)
        for key in ("url", "ua", "nested", "browser", "os_ver", "diag", "v", "http", "vis"):
            self.assertNotIn(key, stored, key)
        self.assertEqual((stored["where"], stored["err"]), ("other", "other"))
        self.assertEqual((stored["wait_ms"], stored["n"]), (60_000, 1))
        dumped = json.dumps(stored, ensure_ascii=False)
        for leak in ("https", "media", "Mozilla", "secret"):
            self.assertNotIn(leak, dumped)

    def test_empty_values_and_nulls_survive(self):
        meta = {"err": "", "stage": "", "inapp": "", "os_ver": "", "can_share_file": None,
                "wait_ms": None, "type_ok": None}
        self._post(meta)
        self.assertEqual(FunnelEvent.objects.get(name="media_save").meta, meta)

    def test_meta_not_an_object(self):
        for meta in (None, "x", [1, 2], 5):
            with self.subTest(meta=meta):
                self.assertEqual(media_save_meta(meta), {})
        self.assertEqual(self._post(["a"]).status_code, 201)
        self.assertEqual(FunnelEvent.objects.get(name="media_save").meta, {})

    def test_beacon_body_without_header(self):
        # sendBeacon не умеет заголовки: ключ устройства приходит в теле.
        body = json.dumps({"name": "media_save", "meta": GOOD, "device_key": "dev-beacon"})
        res = self.client.post(URL, data=body, content_type="application/json")
        self.assertEqual(res.status_code, 201)
        self.assertEqual(FunnelEvent.objects.get(name="media_save").device_key, "dev-beacon")

    def test_other_steps_keep_their_meta_untouched(self):
        # Белый список — только для media_save: у шагов оплаты meta пишется как
        # прежде, без потолка размера (иначе тихо терялась бы аналитика оплат).
        big = {"package_id": 7, "resumed": False, "note": "x" * 6000, "nested": {"a": [1, 2]}}
        res = self.client.post(URL, {"name": "kgs_qr_shown", "meta": big}, format="json",
                               HTTP_X_DEVICE_KEY="dev-pay")
        self.assertEqual(res.status_code, 201)
        self.assertEqual(FunnelEvent.objects.get(name="kgs_qr_shown").meta, big)


@override_settings(CACHES=CACHES)
class FunnelEventAdminTests(TestCase):
    def setUp(self):
        cache.clear()
        self.admin = get_user_model().objects.create_superuser(email="root@example.com",
                                                               password="x-12345678")
        self.client.force_login(self.admin)
        FunnelEvent.objects.create(name="media_save", device_key="dev-ios", meta=GOOD)
        FunnelEvent.objects.create(name="media_save", device_key="dev-other",
                                   meta=dict(GOOD, diag="ZZZZ22"))

    def test_search_by_support_code(self):
        res = self.client.get("/admin/payments/funnelevent/", {"q": "K7Q2XM"})
        self.assertEqual(res.status_code, 200)
        self.assertContains(res, "dev-ios")
        self.assertNotContains(res, "dev-other")

    def test_filter_by_name_and_read_only(self):
        res = self.client.get("/admin/payments/funnelevent/", {"name": "media_save"})
        self.assertEqual(res.status_code, 200)
        event = FunnelEvent.objects.get(device_key="dev-ios")
        self.assertEqual(self.client.get("/admin/payments/funnelevent/add/").status_code, 403)
        res = self.client.post(f"/admin/payments/funnelevent/{event.pk}/delete/", {"post": "yes"})
        self.assertEqual(res.status_code, 403)
        self.assertTrue(FunnelEvent.objects.filter(pk=event.pk).exists())
