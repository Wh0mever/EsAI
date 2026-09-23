# -*- coding: utf-8 -*-
"""Загрузка вложений, список чатов, «поделиться» роликом, журнал (аудит 22.09.2026)."""
import os
import shutil
import tempfile
from datetime import timedelta
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import connection
from django.test import TestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.utils import timezone
from rest_framework.test import APIClient

from . import genlog
from .models import AiChatMessage, AiChatSession, GenerationLog

TEST_CACHES = {"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache",
                           "LOCATION": "audit-views-tests"}}


class _Base(TestCase):
    def setUp(self):
        super().setUp()
        cache.clear()
        self._media = tempfile.mkdtemp()
        self._media_override = override_settings(MEDIA_ROOT=self._media, CACHES=TEST_CACHES)
        self._media_override.enable()
        self.user = get_user_model().objects.create_user(email="views@example.com", password="x")
        self.api = APIClient()
        self.api.force_authenticate(self.user)

    def tearDown(self):
        self._media_override.disable()
        shutil.rmtree(self._media, ignore_errors=True)
        super().tearDown()


class AttachmentUploadTests(_Base):
    URL = "/api/ai/attachments/upload/"

    def _upload(self, name, content=b"data", ctype="application/octet-stream"):
        return self.api.post(self.URL, {"files": [SimpleUploadedFile(name, content, ctype)]},
                             format="multipart")

    def test_html_svg_and_scripts_are_refused(self):
        for name, ctype in (("page.html", "text/html"), ("logo.svg", "image/svg+xml"),
                            ("x.js", "text/javascript"), ("photo.png.html", "text/html"),
                            ("blob", "text/html")):
            with self.subTest(name=name):
                response = self._upload(name, b"<script>alert(1)</script>", ctype)
                self.assertEqual(response.status_code, 400)
                self.assertEqual(response.data["error_code"], "unsupported_file_type")
                self.assertIn("нельзя прикрепить", response.data["detail"])
        self.assertEqual(os.listdir(self._media), [])

    def test_image_is_stored_under_generated_name(self):
        response = self._upload("Моё фото.PNG", b"\x89PNG....", "image/png")
        self.assertEqual(response.status_code, 200)
        item = response.data["attachments"][0]
        self.assertEqual(item["type"], "image")
        self.assertEqual(item["name"], "Моё_фото.PNG")
        self.assertTrue(item["url"].endswith(".png"))
        self.assertNotIn("фото", item["url"])

    def test_jfif_photo_is_accepted_as_jpeg(self):
        # На проде такие фото уже прикладывали: Windows сохраняет JPEG как .jfif.
        for name in ("фото.jfif", "IMG.JPE"):
            with self.subTest(name=name):
                response = self._upload(name, bytes([0xFF, 0xD8, 0xFF]) + b"....", "image/jpeg")
                self.assertEqual(response.status_code, 200, response.data)
                item = response.data["attachments"][0]
                self.assertEqual(item["type"], "image")
                self.assertTrue(item["url"].endswith(".jpg"))

    def test_document_text_is_still_extracted(self):
        response = self._upload("notes.txt", "Привет, документ".encode("utf-8"), "text/plain")
        item = response.data["attachments"][0]
        self.assertEqual(item["type"], "document")
        self.assertEqual(item["text"], "Привет, документ")
        self.assertTrue(item["url"].endswith(".txt"))

    def test_pasted_image_without_extension_uses_content_type(self):
        response = self._upload("blob", b"\x89PNG....", "image/png")
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.data["attachments"][0]["url"].endswith(".png"))


class SessionListTests(_Base):
    URL = "/api/ai/sessions/"

    def _session(self, title, texts, age_minutes):
        session = AiChatSession.objects.create(user=self.user, title=title)
        for text in texts:
            msg = AiChatMessage.objects.create(session=session, role="user", content=text)
            AiChatMessage.objects.filter(pk=msg.pk).update(
                created_at=timezone.now() - timedelta(minutes=age_minutes))
        return session

    def test_shape_and_order_by_latest_message(self):
        old = self._session("старый", ["раз", "два"], age_minutes=60)
        fresh = self._session("свежий", ["д" * 250], age_minutes=1)
        empty = AiChatSession.objects.create(user=self.user, title="пустой")
        AiChatSession.objects.filter(pk=empty.pk).update(
            updated_at=timezone.now() - timedelta(days=1))
        # Старый чат создан позже — раньше он был бы первым по updated_at.
        AiChatSession.objects.filter(pk=old.pk).update(updated_at=timezone.now())

        data = self.api.get(self.URL).data
        self.assertEqual([row["title"] for row in data], ["свежий", "старый", "пустой"])
        first = data[0]
        self.assertEqual(set(first), {"id", "uid", "title", "provider_id", "created_at",
                                      "updated_at", "is_active", "messages_count",
                                      "last_message", "chat_mode"})
        self.assertEqual(first["messages_count"], 1)
        self.assertEqual(first["last_message"]["role"], "user")
        self.assertEqual(first["last_message"]["content"], "д" * 200 + "…")
        self.assertEqual(data[1]["messages_count"], 2)
        self.assertIsNone(data[2]["last_message"])
        self.assertEqual(data[2]["messages_count"], 0)
        self.assertEqual(fresh.uid, first["uid"])

    def test_query_count_does_not_grow_with_sessions(self):
        self._session("a", ["1"], 5)
        with CaptureQueriesContext(connection) as few:
            self.api.get(self.URL)
        for i in range(6):
            self._session(f"s{i}", ["x", "y"], i)
        with CaptureQueriesContext(connection) as many:
            self.api.get(self.URL)
        self.assertEqual(len(few.captured_queries), len(many.captured_queries))

    def test_new_message_bumps_session_activity(self):
        session = AiChatSession.objects.create(user=self.user, title="t")
        stale = timezone.now() - timedelta(days=3)
        AiChatSession.objects.filter(pk=session.pk).update(updated_at=stale)
        AiChatMessage.objects.create(session=session, role="user", content="снова тут")
        session.refresh_from_db()
        self.assertGreater(session.updated_at, stale + timedelta(days=1))


class VideoShareOwnershipTests(_Base):
    URL = "/api/ai/video/share/"

    def setUp(self):
        super().setUp()
        self.name = default_storage.save("ai_videos/clip.mp4", ContentFile(b"mp4"))
        self.url = default_storage.url(self.name)

    def _share(self):
        with patch("ai.video_edit.extract_poster", return_value=None), \
                patch("ai.video_edit.probe_video", return_value={}):
            return self.api.post(self.URL, {"url": self.url}, format="json")

    def test_link_pasted_into_own_message_is_not_ownership(self):
        session = AiChatSession.objects.create(user=self.user, title="t")
        AiChatMessage.objects.create(session=session, role="user", content="смотри",
                                     attachments=[{"type": "video", "url": self.url}])
        self.assertEqual(self._share().status_code, 403)

    def test_imported_assistant_message_is_not_ownership(self):
        session = AiChatSession.objects.create(user=self.user, title="t")
        AiChatMessage.objects.create(session=session, role="assistant", content="видео",
                                     attachments=[{"type": "video", "url": self.url}],
                                     meta={"imported": True})
        self.assertEqual(self._share().status_code, 403)

    def test_generated_video_can_be_shared(self):
        GenerationLog.objects.create(user=self.user, kind="video", model="m",
                                     status=GenerationLog.STATUS_DELIVERED, result_url=self.url)
        self.assertEqual(self._share().status_code, 201)

    def test_video_answer_from_before_the_journal_can_be_shared(self):
        session = AiChatSession.objects.create(user=self.user, title="t")
        AiChatMessage.objects.create(session=session, role="assistant", content="Готово",
                                     attachments=[{"type": "video", "url": self.url}],
                                     meta={"endpoint": "video", "video": True})
        self.assertEqual(self._share().status_code, 201)

    def test_someone_elses_generation_is_refused(self):
        other = get_user_model().objects.create_user(email="other@example.com", password="x")
        GenerationLog.objects.create(user=other, kind="video", model="m",
                                     status=GenerationLog.STATUS_DELIVERED, result_url=self.url)
        self.assertEqual(self._share().status_code, 403)


class GenlogIpTests(TestCase):
    def test_junk_ip_does_not_break_the_journal(self):
        user = get_user_model().objects.create_user(email="ip@example.com", password="x")
        for raw in ("unknown", "1.2.3.4:5678", "<script>", "999.1.1.1"):
            with self.subTest(raw=raw):
                entry = genlog.start(user=user, kind="video", ip=raw)
                self.assertIsNotNone(entry.pk)
                self.assertIsNone(GenerationLog.objects.get(pk=entry.pk).ip)
        entry = genlog.start(user=user, kind="video", ip=" 10.0.0.7 ")
        self.assertEqual(GenerationLog.objects.get(pk=entry.pk).ip, "10.0.0.7")
