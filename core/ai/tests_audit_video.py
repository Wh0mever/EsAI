# -*- coding: utf-8 -*-
"""Видео: один ролик за раз в чате, одна выдача на двоих (поток и довоз),
задержка в боте — не «не получилось» (аудит 22.09.2026)."""
import shutil
import tempfile
from datetime import timedelta
from unittest.mock import MagicMock, patch

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase, override_settings
from django.utils import timezone

from plans.models import TokenTransaction

from . import recovery
from .generation import VIDEO_BUSY_ERROR, _video_lock_key, run_video_generation
from .models import AiChatMessage, AiChatSession, GenerationJob, GenerationLog, GPTModels

TEST_CACHES = {"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache",
                           "LOCATION": "audit-video-tests"}}
CFG = {"api_key": "k", "base_url": "http://provider/api/v1"}
PARAMS = {"duration": 5, "resolution": "720p"}


def _resp(status=200, payload=None, content=b""):
    r = MagicMock(status_code=status, content=content, text=str(payload or ""))
    r.json.return_value = payload or {}
    r.__enter__ = lambda self: self
    r.__exit__ = lambda self, *a: False
    r.iter_content = lambda chunk_size=0: iter([content])
    return r


class _MediaMixin:
    def setUp(self):
        super().setUp()
        self._media = tempfile.mkdtemp()
        self._media_override = override_settings(MEDIA_ROOT=self._media)
        self._media_override.enable()
        cache.clear()
        self.user = get_user_model().objects.create_user(email="vid@example.com", password="x")
        self.user.token_balance = 500
        self.user.is_paid = True
        self.user.save(update_fields=["token_balance", "is_paid"])
        self.model = GPTModels.objects.create(
            name="Seedance", openrouter_id="bytedance/seedance-2.5", max_tokens=1000,
            markup_coefficient=42, category="video", is_active=True)
        self.session = AiChatSession.objects.create(user=self.user, title="Видео")

    def tearDown(self):
        self._media_override.disable()
        shutil.rmtree(self._media, ignore_errors=True)
        super().tearDown()

    def _balance(self):
        self.user.refresh_from_db(fields=["token_balance"])
        return self.user.token_balance


def _patches(post, get):
    return [patch("ai.handlers._video_model_params", return_value=PARAMS),
            patch("ai.handlers._openrouter_config", return_value=CFG),
            patch("ai.handlers._openrouter_video_catalog", return_value={}),
            patch("requests.post", side_effect=post),
            patch("requests.get", side_effect=get),
            patch("time.sleep", return_value=None)]


class _Patched:
    def __init__(self, patches):
        self.patches = patches

    def __enter__(self):
        for p in self.patches:
            p.start()

    def __exit__(self, *exc):
        for p in reversed(self.patches):
            p.stop()
        return False


@override_settings(CACHES=TEST_CACHES)
class VideoLockTests(_MediaMixin, TestCase):
    def _run(self, **kw):
        return list(run_video_generation(
            user=self.user, model_obj=self.model, selected_model_name=self.model.openrouter_id,
            message="кот на пляже", attachments=[], origin_base="https://esai.kg",
            session=self.session, **kw))

    def test_second_video_in_chat_is_refused_while_first_runs(self):
        cache.set(_video_lock_key(self.user), "1", 60)
        with patch("ai.handlers._release_daily_request") as release:
            frames = self._run()
        self.assertEqual(frames, [{"error": VIDEO_BUSY_ERROR, "error_code": "video_in_progress",
                                   "done": True}])
        release.assert_called_once()
        self.assertFalse(GenerationLog.objects.exists())
        self.assertEqual(self._balance(), 500)

    def test_lock_is_held_during_generation_and_released_after(self):
        seen = []

        def post(*a, **kw):
            seen.append(cache.get(_video_lock_key(self.user)))
            return _resp(400, {"error": "bad image"})

        with _Patched(_patches(post, lambda *a, **kw: _resp())):
            self._run()
        self.assertEqual(seen, ["1"])
        self.assertIsNone(cache.get(_video_lock_key(self.user)))

    def test_bot_jobs_are_not_blocked_by_the_chat_lock(self):
        cache.set(_video_lock_key(self.user), "1", 60)
        with _Patched(_patches(lambda *a, **kw: _resp(400, {"error": "bad"}),
                               lambda *a, **kw: _resp())):
            frames = self._run(source="bot")
        self.assertNotEqual(frames[-1].get("error_code"), "video_in_progress")

    def test_extending_someone_elses_video_is_refused(self):
        with patch("ai.handlers._release_daily_request") as release, \
                _Patched(_patches(lambda *a, **kw: _resp(200, {"id": "x"}),
                                  lambda *a, **kw: _resp())):
            frames = self._run(extend_video="/media/ai_videos/not-mine.mp4")
        self.assertEqual(frames[-1]["error_code"], "extend_not_owned")
        release.assert_called_once()
        self.assertEqual(self._balance(), 500)


@override_settings(CACHES=TEST_CACHES)
class VideoReserveTests(_MediaMixin, TestCase):
    """Принятый, но не выданный ролик держит свою цену (закрыл вкладку — не лазейка)."""

    NEED = 210  # 5 с × 42 кр

    def _run(self, **kw):
        return run_video_generation(
            user=self.user, model_obj=self.model, selected_model_name=self.model.openrouter_id,
            message="кот на пляже", attachments=[], origin_base="https://esai.kg",
            session=self.session, **kw)

    def _open_row(self, credits=NEED, **kw):
        fields = dict(user=self.user, kind="video", source="chat", model="m",
                      status=GenerationLog.STATUS_SUBMITTED, polling_url="http://p/videos/x",
                      credits_planned=credits, session=self.session)
        fields.update(kw)
        return GenerationLog.objects.create(**fields)

    def test_closed_tab_does_not_free_the_money_for_a_second_video(self):
        # Баланса ровно на один ролик.
        self.user.token_balance = 300
        self.user.save(update_fields=["token_balance"])
        posts = []

        def post(*a, **kw):
            posts.append(kw.get("json"))
            return _resp(200, {"id": "gen-1"})

        with _Patched(_patches(post, lambda *a, **kw: _resp(200, {"status": "processing"}))):
            first = self._run()
            for frame in first:
                if frame.get("video_progress") == "processing":
                    break
            first.close()  # вкладку закрыли: замок снят, ролик у провайдера снимается
            self.assertIsNone(cache.get(_video_lock_key(self.user)))
            with patch("ai.handlers._release_daily_request") as release:
                second = list(self._run())
        self.assertEqual(len(posts), 1, "второй ролик не должен уйти провайдеру")
        self.assertEqual(second[-1]["error_code"], "insufficient_balance")
        self.assertEqual(second[-1]["balance_tokens"], 300 - self.NEED)
        self.assertEqual(second[-1]["reserved_credits"], self.NEED)
        release.assert_called_once()
        self.assertEqual(GenerationLog.objects.count(), 1)
        self.assertEqual(self._balance(), 300)

    def test_bot_refuses_too(self):
        self._open_row(source="bot")
        self.user.token_balance = 300
        self.user.save(update_fields=["token_balance"])
        with patch("ai.handlers._release_daily_request"), \
                _Patched(_patches(lambda *a, **kw: self.fail("не должно уйти провайдеру"),
                                  lambda *a, **kw: _resp())):
            frames = list(self._run(source="bot"))
        self.assertEqual(frames[-1]["error_code"], "insufficient_balance")

    def test_enough_for_both_passes(self):
        self._open_row()
        # 500 − 210 = 290 ≥ 210: второй ролик разрешён.
        with _Patched(_patches(lambda *a, **kw: _resp(400, {"error": "bad"}),
                               lambda *a, **kw: _resp())):
            frames = list(self._run())
        self.assertNotEqual(frames[-1].get("error_code"), "insufficient_balance")

    def test_closed_old_and_foreign_rows_are_not_reserved(self):
        from .generation import reserved_video_credits

        other = get_user_model().objects.create_user(email="other@example.com", password="x")
        self._open_row(status=GenerationLog.STATUS_DELIVERED)
        self._open_row(status=GenerationLog.STATUS_LOST)
        self._open_row(source="studio")  # студия списывает сама, довоз её не трогает
        self._open_row(kind="image")
        self._open_row(user=other)
        old = self._open_row()
        GenerationLog.objects.filter(pk=old.pk).update(
            created_at=timezone.now() - recovery.GIVE_UP_AFTER - timedelta(minutes=1))
        self.assertEqual(reserved_video_credits(self.user), 0)
        self._open_row(status=GenerationLog.STATUS_SUBMITTING, credits=100)
        self._open_row(credits=50)
        self.assertEqual(reserved_video_credits(self.user), 150)

    def test_job_create_view_refuses_early(self):
        from rest_framework.test import APIClient

        self._open_row(source="bot")
        self.user.token_balance = 300
        self.user.save(update_fields=["token_balance"])
        api = APIClient()
        api.force_authenticate(self.user)
        with patch("ai.handlers._video_model_params", return_value=PARAMS), \
                patch("ai.handlers._openrouter_config", return_value=CFG), \
                patch("ai.tasks.run_generation_job.apply_async") as enqueue:
            response = api.post("/api/ai/jobs/", {"message": "кот", "model": self.model.openrouter_id},
                                format="json")
        self.assertEqual(response.status_code, 402, response.data)
        self.assertEqual(response.data["error_code"], "insufficient_balance")
        self.assertEqual(response.data["reserved_credits"], self.NEED)
        enqueue.assert_not_called()
        self.assertFalse(GenerationJob.objects.exists())


@override_settings(CACHES=TEST_CACHES)
class SingleDeliveryTests(_MediaMixin, TestCase):
    """Живой поток и довоз не выдают один ролик дважды (#6)."""

    def test_live_stream_loses_to_recovery_without_second_charge(self):
        recovered = {}

        def get(url, **kwargs):
            if url.endswith("/videos/gen-1"):
                return _resp(200, {"status": "completed", "unsigned_urls": ["http://cdn/v.mp4"]})
            # Пока поток скачивает ролик, довоз успел выдать его и списать.
            row = GenerationLog.objects.get()
            msg = AiChatMessage.objects.create(
                session=self.session, role="assistant", content="довезено",
                attachments=[{"type": "video", "url": "/media/ai_videos/r.mp4"}],
                meta={"video": True, "recovered": True})
            GenerationLog.objects.filter(pk=row.pk).update(
                status=GenerationLog.STATUS_RECOVERED, message=msg, credits_charged=210)
            recovered["msg"] = msg
            return _resp(200, content=b"mp4")

        with _Patched(_patches(lambda *a, **kw: _resp(200, {"id": "gen-1"}), get)):
            frames = list(run_video_generation(
                user=self.user, model_obj=self.model, selected_model_name=self.model.openrouter_id,
                message="кот", attachments=[], origin_base="https://esai.kg", session=self.session))
        last = frames[-1]
        self.assertTrue(last.get("done"))
        self.assertTrue(last.get("already_delivered"))
        self.assertEqual(last["message"]["id"], recovered["msg"].id)
        self.assertEqual(AiChatMessage.objects.filter(role="assistant").count(), 1)
        self.assertFalse(TokenTransaction.objects.exists())
        self.assertEqual(self._balance(), 500)

    def test_recovery_loses_to_live_stream_without_second_charge(self):
        row = GenerationLog.objects.create(
            user=self.user, kind="video", source="chat", model="bytedance/seedance-2.5",
            status=GenerationLog.STATUS_SUBMITTED, provider_id="gen-2",
            polling_url="http://provider/api/v1/videos/gen-2", credits_planned=168,
            session=self.session)
        GenerationLog.objects.filter(pk=row.pk).update(
            updated_at=timezone.now() - timedelta(minutes=10))

        def get(url, **kwargs):
            if "videos/" in url:
                return _resp(200, {"status": "completed", "unsigned_urls": ["http://cdn/v.mp4"]})
            # Пока довоз качает, живой поток выдал ролик сам.
            GenerationLog.objects.filter(pk=row.pk).update(status=GenerationLog.STATUS_DELIVERED)
            return _resp(200, content=b"mp4")

        with patch("ai.handlers._openrouter_config", return_value=CFG), \
                patch("requests.get", side_effect=get), patch("users.webpush.notify_user"):
            outcome = recovery.recover_open_videos()
        self.assertEqual(outcome, {"skipped": 1})
        self.assertFalse(AiChatMessage.objects.filter(role="assistant").exists())
        self.assertEqual(self._balance(), 500)
        row.refresh_from_db()
        self.assertEqual(row.status, GenerationLog.STATUS_DELIVERED)


@override_settings(CACHES=TEST_CACHES, TELEGRAM_NOTIFY_ENABLED=True,
                   TELEGRAM_PRODUCT_BOT_TOKEN="1:x", SITE_BASE_URL="https://esai.kg")
class DelayedBotJobTests(_MediaMixin, TestCase):
    """«Снимается дольше обычного» в боте — не неудача (#5)."""

    def _job(self, **kw):
        return GenerationJob.objects.create(
            user=self.user, session=self.session, need_credits=168, notify="telegram",
            params={"model": "bytedance/seedance-2.5", "message": "кот", "lang": "ru"}, **kw)

    def _run(self, frames, job):
        from .tasks import run_generation_job

        seen = {}

        def fake(**kwargs):
            seen.update(kwargs)
            yield from frames

        with patch("ai.generation.run_video_generation", side_effect=fake), \
                patch("ai.tasks._notify_job_result") as notify:
            run_generation_job(job.pk)
        job.refresh_from_db()
        return job, notify, seen

    def test_delayed_video_is_not_a_failure(self):
        job, notify, seen = self._run([
            {"video_progress": "processing"},
            {"error": "Видео снимается дольше обычного.", "error_code": "video_delayed",
             "done": True},
        ], self._job())
        self.assertEqual(job.status, GenerationJob.STATUS_DELAYED)
        self.assertEqual(job.error_code, "video_delayed")
        self.assertEqual(seen["log_params"], {"job": job.uid})
        notify.assert_called_once()

    def test_delayed_notice_is_honest_and_has_no_retry(self):
        from botapi.models import TelegramChat

        from .tasks import _notify_job_result

        TelegramChat.objects.create(user=self.user, telegram_id=77, chat_id=77)
        job = self._job(status=GenerationJob.STATUS_DELAYED)
        with patch("botapi.telegram.tg_api") as api:
            _notify_job_result(job)
        method, kwargs = api.call_args.args[0], api.call_args.kwargs
        self.assertEqual(method, "sendMessage")
        self.assertIn("дольше обычного", kwargs["text"])
        self.assertNotIn("не получилось", kwargs["text"])
        self.assertNotIn("reply_markup", kwargs)

    def test_recovery_closes_delayed_job_and_sends_the_video(self):
        job = self._job(status=GenerationJob.STATUS_DELAYED, error_code="video_delayed")
        row = GenerationLog.objects.create(
            user=self.user, kind="video", source="bot", model="bytedance/seedance-2.5",
            status=GenerationLog.STATUS_SUBMITTED, provider_id="gen-3",
            polling_url="http://provider/api/v1/videos/gen-3", credits_planned=168,
            session=self.session, params={"job": job.uid})
        GenerationLog.objects.filter(pk=row.pk).update(
            updated_at=timezone.now() - timedelta(minutes=10))

        def get(url, **kwargs):
            if "videos/" in url:
                return _resp(200, {"status": "completed", "unsigned_urls": ["http://cdn/v.mp4"]})
            return _resp(200, content=b"mp4")

        with patch("ai.handlers._openrouter_config", return_value=CFG), \
                patch("requests.get", side_effect=get), patch("users.webpush.notify_user"), \
                patch("ai.tasks._notify_job_result") as notify, \
                patch("ai.recovery._send_to_telegram") as send:
            outcome = recovery.recover_open_videos()
        self.assertEqual(outcome, {"delivered": 1})
        job.refresh_from_db()
        self.assertEqual(job.status, GenerationJob.STATUS_DONE)
        self.assertEqual(job.tokens_charged, 168)
        self.assertEqual(job.result["message"]["attachments"][0]["type"], "video")
        notify.assert_called_once()
        send.assert_not_called()
        self.assertEqual(self._balance(), 500 - 168)

    def test_recovery_failure_closes_delayed_job_as_failed(self):
        job = self._job(status=GenerationJob.STATUS_DELAYED, error_code="video_delayed")
        row = GenerationLog.objects.create(
            user=self.user, kind="video", source="bot", model="m",
            status=GenerationLog.STATUS_SUBMITTED, polling_url="http://provider/api/v1/videos/g",
            credits_planned=168, session=self.session, params={"job": job.uid})
        GenerationLog.objects.filter(pk=row.pk).update(
            updated_at=timezone.now() - timedelta(minutes=10))
        with patch("ai.handlers._openrouter_config", return_value=CFG), \
                patch("requests.get", side_effect=lambda url, **kw: _resp(200, {"status": "failed"})), \
                patch("ai.tasks._notify_job_result") as notify:
            recovery.recover_open_videos()
        job.refresh_from_db()
        self.assertEqual(job.status, GenerationJob.STATUS_FAILED)
        notify.assert_called_once()
        self.assertEqual(self._balance(), 500)

    def test_video_already_delivered_by_recovery_is_done_without_second_message(self):
        job, notify, _ = self._run([
            {"done": True, "already_delivered": True, "message": {"id": None, "attachments": []},
             "tokens_charged": 168, "balance_tokens": 332},
        ], self._job())
        self.assertEqual(job.status, GenerationJob.STATUS_DONE)
        self.assertIsNotNone(job.notified_at)
        notify.assert_not_called()
