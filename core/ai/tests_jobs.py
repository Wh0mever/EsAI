# -*- coding: utf-8 -*-
"""Видео через очередь: гейты как в чате, результат переживает перезапуск бота."""
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from .models import AiChatMessage, AiChatSession, GenerationJob, GPTModels

TEST_CACHES = {"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache",
                           "LOCATION": "jobs-tests"}}
URL = "/api/ai/jobs/"
PARAMS = {"duration": 5, "resolution": "720p"}


def _user(balance=100, paid=True, email="jobs@example.com"):
    User = get_user_model()
    user = User.objects.create_user(email=email, password="x")
    user.token_balance = balance
    user.is_paid = paid
    user.save(update_fields=["token_balance", "is_paid"])
    return user


def _model():
    return GPTModels.objects.create(name="Test Video", openrouter_id="test/video",
                                    max_tokens=1000, markup_coefficient=4,
                                    category="video", is_active=True, free_tier=False)


def _client(user):
    client = APIClient()
    client.force_authenticate(user)
    return client


def _mocks():
    return (patch("ai.handlers._video_model_params", return_value=PARAMS),
            patch("ai.handlers._openrouter_config", return_value={"api_key": "k", "base_url": "http://x"}),
            patch("ai.tasks.run_generation_job.apply_async"))


@override_settings(CACHES=TEST_CACHES, CELERY_MEDIA_QUEUE="media")
class JobCreateTests(TestCase):
    def setUp(self):
        cache.clear()
        self.model = _model()

    def test_creates_job_session_and_message(self):
        user = _user()
        p1, p2, enqueue = _mocks()
        with p1, p2, enqueue as enqueue:
            # Очередь — только после коммита (ATOMIC_REQUESTS): до него воркер
            # не нашёл бы задачу в базе.
            with self.captureOnCommitCallbacks(execute=False) as callbacks:
                response = _client(user).post(URL, {"message": "кот на скейте",
                                                   "model": "test/video",
                                                   "notify": "telegram", "video_duration": 5},
                                              format="json")
            enqueue.assert_not_called()
            for callback in callbacks:
                callback()
        self.assertEqual(response.status_code, 202, response.data)
        job = GenerationJob.objects.get(uid=response.data["job_id"])
        self.assertEqual(job.status, "queued")
        self.assertEqual(job.need_credits, 20)  # 5 с × 4 кр
        self.assertEqual(job.notify, "telegram")
        self.assertEqual(job.params["model"], "test/video")
        self.assertIsNotNone(job.session)
        self.assertEqual(AiChatMessage.objects.filter(session=job.session, role="user").count(), 1)
        enqueue.assert_called_once()
        self.assertEqual(enqueue.call_args.kwargs.get("queue"), "media")

    def test_queue_failure_after_commit_closes_job_and_returns_slot(self):
        user = _user()
        p1, p2, enqueue = _mocks()
        with p1, p2, enqueue as enqueue, \
                patch("ai.handlers._release_daily_request") as release:
            enqueue.side_effect = RuntimeError("broker down")
            with self.captureOnCommitCallbacks(execute=True):
                response = _client(user).post(URL, {"message": "кот", "model": "test/video"},
                                              format="json")
        self.assertEqual(response.status_code, 202)
        job = GenerationJob.objects.get(uid=response.data["job_id"])
        self.assertEqual(job.status, "failed")
        self.assertEqual(job.error_code, "queue_unavailable")
        release.assert_called_once()

    def test_premium_locked_for_free_user(self):
        user = _user(paid=False)
        p1, p2, enqueue = _mocks()
        with p1, p2, enqueue:
            response = _client(user).post(URL, {"message": "x", "model": "test/video"}, format="json")
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.data["error_code"], "premium_locked")
        self.assertFalse(GenerationJob.objects.exists())

    def test_insufficient_balance(self):
        user = _user(balance=5)
        p1, p2, enqueue = _mocks()
        with p1, p2, enqueue:
            response = _client(user).post(URL, {"message": "x", "model": "test/video"}, format="json")
        self.assertEqual(response.status_code, 402)
        self.assertEqual(response.data["required_estimate"], 20)
        self.assertFalse(GenerationJob.objects.exists())

    def test_one_active_job_per_user(self):
        user = _user()
        GenerationJob.objects.create(user=user, status="running")
        p1, p2, enqueue = _mocks()
        with p1, p2, enqueue:
            response = _client(user).post(URL, {"message": "x", "model": "test/video"}, format="json")
        self.assertEqual(response.status_code, 409)

    def test_non_video_model_rejected(self):
        user = _user()
        GPTModels.objects.create(name="Chat", openrouter_id="test/chat", max_tokens=10,
                                 markup_coefficient=1, category="chat")
        p1, p2, enqueue = _mocks()
        with p1, p2, enqueue:
            response = _client(user).post(URL, {"message": "x", "model": "test/chat"}, format="json")
        self.assertEqual(response.status_code, 400)

    def test_detail_hidden_from_others(self):
        owner = _user(email="o@example.com")
        other = _user(email="p@example.com")
        job = GenerationJob.objects.create(user=owner)
        self.assertEqual(_client(other).get(f"{URL}{job.uid}/").status_code, 404)
        response = _client(owner).get(f"{URL}{job.uid}/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["job_id"], job.uid)
        self.assertFalse(response.data["notified"])

    def test_cancel_queued_job(self):
        user = _user()
        job = GenerationJob.objects.create(user=user, status="queued")
        with patch("ai.handlers._release_daily_request") as release:
            response = _client(user).post(f"{URL}{job.uid}/cancel/")
        self.assertEqual(response.data["status"], "canceled")
        release.assert_called_once()


@override_settings(CACHES=TEST_CACHES, TELEGRAM_NOTIFY_ENABLED=True,
                   TELEGRAM_PRODUCT_BOT_TOKEN="1:x", SITE_BASE_URL="https://esai.kg")
class JobTaskTests(TestCase):
    def setUp(self):
        cache.clear()
        self.model = _model()
        self.user = _user()
        self.session = AiChatSession.objects.create(user=self.user, title="t")

    def _job(self, **params):
        return GenerationJob.objects.create(
            user=self.user, session=self.session, need_credits=20, notify="telegram",
            params={"model": "test/video", "message": "кот", "lang": "ru", **params})

    def _run(self, frames, job):
        from .tasks import run_generation_job

        def fake(**kwargs):
            for frame in frames:
                if callable(frame):
                    frame(kwargs)
                    continue
                yield frame

        with patch("ai.generation.run_video_generation", side_effect=fake), \
                patch("ai.tasks._notify_job_result") as notify:
            run_generation_job(job.pk)
        job.refresh_from_db()
        return job, notify

    def test_done_stores_result(self):
        message = AiChatMessage.objects.create(session=self.session, role="assistant", content="ok",
                                               attachments=[{"type": "video", "url": "/media/v.mp4"}])
        job, notify = self._run([
            {"video_pending": True, "duration": 5},
            {"video_progress": "processing"},
            {"done": True, "message": {"id": message.id, "attachments": message.attachments},
             "tokens_charged": 20, "balance_tokens": 80,
             "session": {"id": self.session.id, "uid": self.session.uid}},
        ], self._job())
        self.assertEqual(job.status, "done")
        self.assertEqual(job.tokens_charged, 20)
        self.assertEqual(job.result["balance_tokens"], 80)
        self.assertEqual(job.result_message_id, message.id)
        notify.assert_called_once()

    def test_error_marks_failed_and_notifies(self):
        job, notify = self._run([
            {"video_progress": "processing"},
            {"error": "Видео не получилось", "done": True},
        ], self._job())
        self.assertEqual(job.status, "failed")
        self.assertEqual(job.error, "Видео не получилось")
        notify.assert_called_once()

    def test_cancel_flag_reaches_generator(self):
        from .views_media import _cancel_key

        job = self._job()
        cache.set(_cancel_key(job.uid), "1", 60)
        seen = {}

        def capture(kwargs):
            seen["canceled"] = kwargs["cancel_check"]()

        job, notify = self._run([capture, {"error": "Отменено", "error_code": "canceled",
                                           "done": True}], job)
        self.assertTrue(seen["canceled"])
        self.assertEqual(job.status, "canceled")
        notify.assert_not_called()

    def test_skips_job_not_queued(self):
        from .tasks import run_generation_job

        job = self._job()
        job.status = "done"
        job.save()
        with patch("ai.generation.run_video_generation") as gen:
            run_generation_job(job.pk)
        gen.assert_not_called()

    def test_notify_sends_video_and_marks(self):
        from botapi.models import TelegramChat

        from .tasks import _notify_job_result

        TelegramChat.objects.create(user=self.user, telegram_id=77, chat_id=77)
        job = self._job()
        job.status = "done"
        job.result = {"message": {"attachments": [{"type": "video", "url": "/media/v.mp4"}]},
                      "tokens_charged": 20, "balance_tokens": 80}
        job.save()
        with patch("botapi.telegram.tg_api") as api:
            _notify_job_result(job)
        method, kwargs = api.call_args.args[0], api.call_args.kwargs
        self.assertEqual(method, "sendVideo")
        self.assertEqual(kwargs["video"], "https://esai.kg/media/v.mp4")
        self.assertEqual(kwargs["chat_id"], 77)
        self.assertIn("v:ext:" + job.uid, str(kwargs["reply_markup"]))
        job.refresh_from_db()
        self.assertIsNotNone(job.notified_at)

    def test_notify_skipped_when_bot_off(self):
        from .tasks import _notify_job_result

        job = self._job()
        job.notify = ""
        job.save()
        with patch("botapi.telegram.tg_api") as api:
            _notify_job_result(job)
        api.assert_not_called()
