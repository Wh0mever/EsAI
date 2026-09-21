# -*- coding: utf-8 -*-
"""Журнал генераций и довоз оплаченных роликов.

Случай 21.09.2026: провайдер принял запрос, снял видео и взял $1.17, а человек
увидел «не удалось запустить генерацию» и ушёл без ролика и без списания.
Эти тесты стерегут, чтобы такое больше не терялось бесследно.
"""
from datetime import timedelta
from unittest.mock import MagicMock, patch

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase, override_settings
from django.utils import timezone

from . import recovery
from .generation import run_video_generation
from .models import AiChatMessage, AiChatSession, GenerationLog, GPTModels

TEST_CACHES = {"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache",
                           "LOCATION": "genlog-tests"}}
CFG = {"api_key": "k", "base_url": "http://provider/api/v1"}
PARAMS = {"duration": 5, "resolution": "720p"}


def _resp(status=200, payload=None, content=b""):
    r = MagicMock(status_code=status, content=content, text=str(payload or ""))
    r.json.return_value = payload or {}
    r.__enter__ = lambda self: self
    r.__exit__ = lambda self, *a: False
    r.iter_content = lambda chunk_size=0: iter([content])
    return r


@override_settings(CACHES=TEST_CACHES)
class VideoLogTests(TestCase):
    def setUp(self):
        cache.clear()
        self.user = get_user_model().objects.create_user(email="gen@example.com", password="x")
        self.user.token_balance = 500
        self.user.save(update_fields=["token_balance"])
        self.model = GPTModels.objects.create(
            name="Seedance", openrouter_id="bytedance/seedance-2.5", max_tokens=1000,
            markup_coefficient=42, category="video", is_active=True)
        self.session = AiChatSession.objects.create(user=self.user, title="Видео")

    def _run(self):
        return list(run_video_generation(
            user=self.user, model_obj=self.model, selected_model_name=self.model.openrouter_id,
            message="кот идёт по пляжу", attachments=[], origin_base="https://esai.kg",
            session=self.session, client_ip="10.0.0.7"))

    def _patches(self, post, get=None):
        return (patch("ai.handlers._video_model_params", return_value=PARAMS),
                patch("ai.handlers._openrouter_config", return_value=CFG),
                patch("ai.handlers._openrouter_video_catalog", return_value={}),
                patch("requests.post", side_effect=post),
                patch("requests.get", side_effect=get or (lambda *a, **kw: _resp())),
                patch("time.sleep", return_value=None))

    def test_silence_on_submit_is_recorded_as_lost_not_as_a_plain_failure(self):
        """Ответа нет — исход неизвестен: провайдер мог принять и взять деньги."""
        def post(*args, **kwargs):
            raise TimeoutError("read timed out")

        p = self._patches(post)
        with p[0], p[1], p[2], p[3], p[4], p[5]:
            frames = self._run()
        self.assertTrue(frames[-1].get("error"))
        row = GenerationLog.objects.get()
        self.assertEqual(row.status, GenerationLog.STATUS_LOST)
        self.assertTrue(row.needs_review)
        self.assertEqual(row.user, self.user)
        self.assertEqual(row.model, "bytedance/seedance-2.5")
        self.assertEqual(row.ip, "10.0.0.7")
        self.assertEqual(row.credits_planned, 210)
        self.user.refresh_from_db()
        self.assertEqual(self.user.token_balance, 500)

    def test_provider_refusal_costs_nothing_and_needs_no_review(self):
        p = self._patches(lambda *a, **kw: _resp(400, {"error": "bad image"}))
        with p[0], p[1], p[2], p[3], p[4], p[5]:
            self._run()
        row = GenerationLog.objects.get()
        self.assertEqual(row.status, GenerationLog.STATUS_FAILED)
        self.assertFalse(row.needs_review)
        self.assertIn("400", row.error)

    def test_accepted_job_without_polling_url_is_not_thrown_away(self):
        """Адрес опроса не пришёл, но есть ID — строим адрес сами и снимаем ролик."""
        polled = []

        def get(url, **kwargs):
            polled.append(url)
            if url.endswith("/videos/gen-vid-1"):
                return _resp(200, {"status": "completed", "unsigned_urls": ["http://cdn/v.mp4"],
                                   "usage": {"cost": 1.1652}})
            return _resp(200, content=b"mp4-bytes")

        p = self._patches(lambda *a, **kw: _resp(200, {"id": "gen-vid-1"}), get)
        with p[0], p[1], p[2], p[3], p[4], p[5]:
            frames = self._run()
        self.assertTrue(frames[-1].get("done"))
        self.assertFalse(frames[-1].get("error"), frames[-1])
        row = GenerationLog.objects.get()
        self.assertEqual(row.status, GenerationLog.STATUS_DELIVERED)
        self.assertEqual(row.provider_id, "gen-vid-1")
        self.assertEqual(str(row.provider_cost_usd), "1.1652")
        self.assertEqual(row.credits_charged, 210)
        self.assertIsNotNone(row.message)
        stages = [s["stage"] for s in row.stages]
        self.assertEqual(stages[:3], ["started", "submitting", "submitted"])
        self.assertIn("delivered", stages)
        self.user.refresh_from_db()
        self.assertEqual(self.user.token_balance, 290)


@override_settings(CACHES=TEST_CACHES)
class RecoveryTests(TestCase):
    """Соединение с человеком оборвалось, а ролик у провайдера готов и оплачен."""

    def setUp(self):
        cache.clear()
        self.user = get_user_model().objects.create_user(email="lost@example.com", password="x")
        self.user.token_balance = 500
        self.user.save(update_fields=["token_balance"])
        self.session = AiChatSession.objects.create(user=self.user, title="Видео")
        self.row = GenerationLog.objects.create(
            user=self.user, kind="video", source="chat", model="bytedance/seedance-2.5",
            status=GenerationLog.STATUS_SUBMITTED, provider_id="gen-vid-1789973061",
            polling_url="http://provider/api/v1/videos/gen-vid-1789973061",
            prompt="кот идёт по пляжу", credits_planned=168, session=self.session)
        GenerationLog.objects.filter(pk=self.row.pk).update(
            updated_at=timezone.now() - timedelta(minutes=10))

    def _get(self, status="completed"):
        def get(url, **kwargs):
            if "videos/" in url:
                return _resp(200, {"status": status, "unsigned_urls": ["http://cdn/v.mp4"],
                                   "usage": {"cost": 1.1652}})
            return _resp(200, content=b"mp4-bytes")
        return get

    def test_finished_video_reaches_the_chat_and_is_charged_once(self):
        with patch("ai.handlers._openrouter_config", return_value=CFG), \
             patch("requests.get", side_effect=self._get()), \
             patch("users.webpush.notify_user"):
            first = recovery.recover_open_videos()
            second = recovery.recover_open_videos()
        self.assertEqual(first, {"delivered": 1})
        self.assertEqual(second, {})
        self.row.refresh_from_db()
        self.assertEqual(self.row.status, GenerationLog.STATUS_RECOVERED)
        self.assertEqual(self.row.credits_charged, 168)
        self.assertFalse(self.row.needs_review)
        message = AiChatMessage.objects.get(session=self.session, role="assistant")
        self.assertEqual(message.attachments[0]["type"], "video")
        self.assertTrue(message.meta["recovered"])
        self.user.refresh_from_db()
        self.assertEqual(self.user.token_balance, 332)

    def test_live_generation_is_left_alone(self):
        """Запись отмечалась полминуты назад — поток жив, довозить рано."""
        GenerationLog.objects.filter(pk=self.row.pk).update(updated_at=timezone.now())
        with patch("ai.handlers._openrouter_config", return_value=CFG), \
             patch("requests.get", side_effect=self._get()) as get:
            outcome = recovery.recover_open_videos()
        self.assertEqual(outcome, {})
        self.assertEqual(get.call_count, 0)

    def test_still_rendering_stays_open(self):
        with patch("ai.handlers._openrouter_config", return_value=CFG), \
             patch("requests.get", side_effect=self._get("processing")):
            outcome = recovery.recover_open_videos()
        self.assertEqual(outcome, {"pending": 1})
        self.row.refresh_from_db()
        self.assertEqual(self.row.status, GenerationLog.STATUS_SUBMITTED)

    def test_provider_failure_closes_the_record_without_charging(self):
        with patch("ai.handlers._openrouter_config", return_value=CFG), \
             patch("requests.get", side_effect=self._get("failed")):
            recovery.recover_open_videos()
        self.row.refresh_from_db()
        self.assertEqual(self.row.status, GenerationLog.STATUS_FAILED)
        self.user.refresh_from_db()
        self.assertEqual(self.user.token_balance, 500)

    def test_request_that_never_got_an_answer_goes_to_review(self):
        stuck = GenerationLog.objects.create(user=self.user, kind="video", model="m",
                                             status=GenerationLog.STATUS_SUBMITTING)
        GenerationLog.objects.filter(pk=stuck.pk).update(
            updated_at=timezone.now() - timedelta(minutes=30))
        with patch("ai.handlers._openrouter_config", return_value=CFG), \
             patch("requests.get", side_effect=self._get("processing")):
            recovery.recover_open_videos()
        stuck.refresh_from_db()
        self.assertEqual(stuck.status, GenerationLog.STATUS_LOST)
        self.assertTrue(stuck.needs_review)
