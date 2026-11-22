"""Конвейер: отказы снимают резерв, двойная выдача списывает один раз, повтор с тем же ключом,
отказ поставщика из-за денег, видео, частичная партия, страховка."""
from __future__ import annotations

from datetime import timedelta
from decimal import Decimal
from unittest import mock

from django.core.cache import cache
from django.utils import timezone

from creative import pipeline
from creative.models import CreativeJob
from creative.reserve import PROVIDER_DOWN_KEY
from plans.models import TokenTransaction
from users.models import Notification
from vstudio.reserve import total_reserved

from .helpers import CreativeTestCase, make_user


def make_job(user, *, tool="portrait", kind="image", credits=14, params=None, expected=1, **kw):
    params = params or {"prompt": "кот", "aspect": "3:4", "resolution": "720p", "count": 1}
    return CreativeJob.objects.create(user=user, tool_slug=tool, kind=kind, params=params,
                                      credits_quoted=credits, credits_reserved=credits,
                                      cost_usd=Decimal("0.094"), expected_outputs=expected, **kw)


class PipelineTests(CreativeTestCase):
    def setUp(self):
        super().setUp()
        self.user = make_user(balance=100)

    def test_failed_and_nsfw_release_reserve(self):
        for state, status, code in (("failed", "failed", "provider_failed"), ("nsfw", "nsfw", "nsfw")):
            job = make_job(self.user)
            self.drive(job, steps=("submit",))
            self.fake.states[job.provider_request_id] = state
            self.assertEqual(self.drive(job, steps=("poll",)), [status])
            self.assertEqual((job.status, job.charge_state, job.error_code), (status, "released", code))
            self.assertEqual(job.credits_charged, 0)
        self.assertEqual(total_reserved(self.user), 0)
        self.assertFalse(TokenTransaction.objects.exists())
        self.user.refresh_from_db()
        self.assertEqual(self.user.token_balance, 100)

    def test_in_progress_reschedules(self):
        job = make_job(self.user)
        self.drive(job, steps=("submit",))
        self.fake.states[job.provider_request_id] = "in_progress"
        self.assertEqual(self.drive(job, steps=("poll",)), ["polling"])
        self.assertEqual((job.status, job.stage, job.poll_count), ("running", "in_progress", 1))
        self.assertIn(("poll_job", job.pk), self.enqueued)

    def test_duplicate_delivery_charges_once(self):
        """Вебхук и опрос пришли разом: обе выдачи скачали файлы, деньги списывает одна."""
        job = make_job(self.user)
        self.drive(job, steps=("submit", "poll"))
        self.assertEqual(job.status, "saving")
        files_a = pipeline.fetch_results(job, ["https://cdn.provider-files.test/r/x/0.png"])
        files_b = pipeline.fetch_results(job, ["https://cdn.provider-files.test/r/x/0.png"])
        first = pipeline.commit(job, files_a)
        second = pipeline.commit(job, files_b)
        self.assertIsNotNone(first)
        self.assertIsNone(second)
        self.assertEqual(TokenTransaction.objects.filter(user=self.user).count(), 1)
        self.user.refresh_from_db()
        self.assertEqual(self.user.token_balance, 100 - 14)
        # и повторный finalize (вторая копия задачи) ничего не делает
        self.due(job)
        self.assertEqual(pipeline.finalize(job.pk), "skip")
        self.assertEqual(TokenTransaction.objects.filter(user=self.user).count(), 1)

    def test_transient_submit_retries_with_same_key_and_body(self):
        job = make_job(self.user)
        self.fake.submit_responses = [(500, {"detail": "boom"})]
        self.assertEqual(self.drive(job, steps=("submit",)), ["retry"])
        self.assertEqual((job.status, job.stage), ("queued", "retry"))
        key = job.idempotency_key
        self.assertTrue(key)
        self.assertEqual(self.drive(job, steps=("submit",)), ["running"])
        sub = self.fake.submits()
        self.assertEqual(len(sub), 2)
        self.assertEqual(sub[0]["idem"], key)
        self.assertEqual(sub[1]["idem"], key)
        self.assertEqual(sub[0]["body"], sub[1]["body"])

    def test_queue_full_429_retries_later(self):
        job = make_job(self.user)
        self.fake.submit_responses = [(429, {"detail": {"code": "account_queue_full", "retry_after_seconds": 45}})]
        self.assertEqual(self.drive(job, steps=("submit",)), ["retry"])
        self.assertGreater(job.next_poll_at, timezone.now() + timedelta(seconds=30))

    def test_provider_refusal_403_alerts_staff_and_blocks_launches(self):
        staff = make_user(is_staff=True)
        job = make_job(self.user)
        self.fake.submit_responses = [(403, {"detail": "Insufficient balance"})]
        self.assertEqual(self.drive(job, steps=("submit",)), ["failed"])
        self.assertEqual((job.status, job.charge_state, job.error_code),
                         ("failed", "released", "provider_unavailable"))
        self.assertTrue(cache.get(PROVIDER_DOWN_KEY))
        self.assertTrue(Notification.objects.filter(deliveries__recipient=staff).exists())
        self.assertFalse(Notification.objects.filter(deliveries__recipient=self.user).exists())
        # текст человеку — без поставщика и без его ответа
        self.assertNotIn("Insufficient", job.error)
        # следующий запуск — 503 до резерва
        r = self.client_for(self.user).post("/api/creative/run/", {
            "tool": "portrait", "params": {"prompt": "кот"}, "quoted_credits": 14,
            "client_request_id": "after-403"}, format="json")
        self.assertEqual(r.status_code, 503)
        self.assertEqual(r.json()["error_code"], "provider_unavailable")

    def test_bad_params_422_fails_without_charge(self):
        job = make_job(self.user)
        self.fake.submit_responses = [(422, {"detail": [{"msg": "bad"}]})]
        self.assertEqual(self.drive(job, steps=("submit",)), ["failed"])
        self.assertEqual((job.error_code, job.charge_state, job.needs_review), ("bad_params", "released", True))

    def test_parallel_slots(self):
        with self.settings(CREATIVE_MAX_PARALLEL=1):
            busy = make_job(self.user)
            self.drive(busy, steps=("submit",))
            waiting = make_job(self.user)
            self.assertEqual(self.drive(waiting, steps=("submit",)), ["waiting"])
            self.assertEqual((waiting.status, waiting.stage, waiting.attempts), ("queued", "waiting", 0))

    def test_partial_batch_charges_for_delivered(self):
        job = make_job(self.user, credits=20, expected=4,
                       params={"prompt": "кот", "aspect": "1:1", "resolution": "720p", "count": 4},
                       tool="text-to-image")
        self.drive(job, steps=("submit",))
        self.fake.outputs[job.provider_request_id] = 2
        self.drive(job, steps=("poll", "finalize"))
        self.assertEqual(job.status, "done")
        self.assertEqual(len(job.result_files), 2)
        self.assertEqual(job.credits_charged, 10)

    def test_video_job_with_uploads(self):
        video = self.make_video(self.user, duration=4.0)
        image = self.make_image(self.user)
        job = make_job(self.user, tool="motion-transfer", kind="video", credits=9,
                       params={"video": video.uid, "image": image.uid, "resolution": "480p", "consent": True})
        self.drive(job, steps=("submit",))
        sub = self.fake.submits()[-1]["body"]
        self.assertEqual(set(sub), {"video_url", "image_urls", "resolution"})
        self.assertTrue(sub["video_url"].startswith("https://cdn.provider-files.test/in/"))
        uploads = [c for c in self.fake.calls if c["path"] == "/files/generate-upload-url"]
        self.assertEqual([c["body"]["content_type"] for c in uploads], ["video/mp4", "image/jpeg"])
        self.assertFalse(self.fake.auth_leaks)
        video.refresh_from_db()
        self.assertTrue(video.provider_url)
        self.fake.outputs[job.provider_request_id] = "video"
        with mock.patch("creative.pipeline._strip_video", return_value=False), \
                mock.patch("ai.video_edit.probe_video", return_value={"width": 854, "height": 480,
                                                                       "duration": 4.0}), \
                mock.patch("ai.video_edit.extract_poster", return_value=None):
            self.drive(job, steps=("poll", "finalize"))
        self.assertEqual(job.status, "done")
        self.assertEqual(job.result_files[0]["mime"], "video/mp4")
        self.assertTrue(job.result_files[0]["path"].endswith("/1.mp4"))
        self.assertEqual(TokenTransaction.objects.get(user=self.user).reason, "creative_video")
        # повторная задача с тем же файлом не грузит его заново (живая копия)
        job2 = make_job(self.user, tool="motion-transfer", kind="video", credits=9,
                        params={"video": video.uid, "image": image.uid, "resolution": "480p", "consent": True})
        before = len([c for c in self.fake.calls if c["path"] == "/files/generate-upload-url"])
        self.drive(job2, steps=("submit",))
        after = len([c for c in self.fake.calls if c["path"] == "/files/generate-upload-url"])
        self.assertEqual(before, after)

    def test_character_retry_after_unknown_outcome_goes_to_review(self):
        photos = [self.make_image(self.user) for _ in range(3)]
        job = make_job(self.user, tool="consistent-character", kind="character", credits=350,
                       params={"name": "Я", "photos": [p.uid for p in photos], "consent": True})
        with mock.patch("creative.hf.create_character",
                        side_effect=__import__("creative.hf", fromlist=["HFError"]).HFError(
                            "transient", sent=True)):
            self.assertEqual(self.drive(job, steps=("submit",)), ["lost"])
        self.assertEqual((job.status, job.charge_state, job.needs_review), ("lost", "released", True))


class SweepTests(CreativeTestCase):
    def setUp(self):
        super().setUp()
        self.user = make_user(balance=100)

    def test_stale_queue_times_out_and_lost_chain_repolled(self):
        old = make_job(self.user)
        CreativeJob.objects.filter(pk=old.pk).update(created_at=timezone.now() - timedelta(minutes=40))
        running = make_job(self.user)
        self.drive(running, steps=("submit",))
        CreativeJob.objects.filter(pk=running.pk).update(next_poll_at=timezone.now() - timedelta(minutes=5))
        self.enqueued.clear()
        out = pipeline.sweep()
        old.refresh_from_db()
        self.assertEqual((old.status, old.error_code, old.charge_state), ("failed", "queue_timeout", "released"))
        self.assertEqual(out.get("repoll"), 1)
        self.assertIn(("poll_job", running.pk), self.enqueued)

    def test_running_gives_up_after_limit(self):
        job = make_job(self.user)
        self.drive(job, steps=("submit",))
        CreativeJob.objects.filter(pk=job.pk).update(submitted_at=timezone.now() - timedelta(hours=3))
        pipeline.sweep()
        job.refresh_from_db()
        self.assertEqual((job.status, job.error_code, job.needs_review), ("lost", "provider_timeout", True))

    def test_stale_submitting_requeued(self):
        job = make_job(self.user)
        CreativeJob.objects.filter(pk=job.pk).update(status="submitting",
                                                     updated_at=timezone.now() - timedelta(minutes=20))
        self.enqueued.clear()
        pipeline.sweep()
        job.refresh_from_db()
        self.assertEqual(job.status, "queued")
        self.assertIn(("submit_job", job.pk), self.enqueued)


class MaybeSentTests(CreativeTestCase):
    """Попытка, которая могла дойти до поставщика (таймаут/5xx после POST), не закрывается
    «как будто ничего не уходило»: отмена 409, конец попыток / таймаут / отказ повтора — lost."""

    def setUp(self):
        super().setUp()
        self.user = make_user(balance=100)

    def sent_once(self, **kw):
        job = make_job(self.user, **kw)
        self.fake.submit_responses = [(504, {"detail": "gateway"})]
        self.assertEqual(self.drive(job, steps=("submit",)), ["retry"])
        self.assertTrue(job.request_body.get("maybe_sent"))
        self.assertEqual((job.status, job.stage), ("queued", "retry"))
        return job

    def assert_lost(self, job):
        job.refresh_from_db()
        self.assertEqual((job.status, job.charge_state, job.needs_review, job.error_code),
                         ("lost", "released", True, "submit_unknown"))
        self.assertEqual(total_reserved(self.user), 0)
        from ai.models import GenerationLog

        log = GenerationLog.objects.get(pk=job.genlog_id)
        self.assertEqual(log.status, GenerationLog.STATUS_LOST)

    def test_cancel_refused(self):
        job = self.sent_once()
        self.assertFalse(pipeline.cancel(job.pk))
        job.refresh_from_db()
        self.assertEqual((job.status, job.charge_state), ("queued", "reserved"))

    def test_not_sent_answer_does_not_clear_flag(self):
        job = self.sent_once()
        self.fake.submit_responses = [(429, {"detail": {"code": "account_queue_full"}})]
        self.assertEqual(self.drive(job, steps=("submit",)), ["retry"])
        self.assertTrue(job.request_body.get("maybe_sent"))
        self.assertFalse(pipeline.cancel(job.pk))

    def test_queue_timeout_goes_to_lost(self):
        job = self.sent_once()
        CreativeJob.objects.filter(pk=job.pk).update(created_at=timezone.now() - timedelta(minutes=40),
                                                     next_poll_at=None)
        out = pipeline.sweep()
        self.assertEqual(out.get("submit_unknown"), 1)
        self.assert_lost(job)

    def test_final_attempt_with_not_sent_error_goes_to_lost(self):
        job = self.sent_once()
        CreativeJob.objects.filter(pk=job.pk).update(attempts=pipeline.SUBMIT_MAX_ATTEMPTS - 1)
        self.fake.submit_responses = [(429, {"detail": "busy"})]
        self.assertEqual(self.drive(job, steps=("submit",)), ["lost"])
        self.assert_lost(job)

    def test_403_on_replay_goes_to_lost_and_alerts(self):
        job = self.sent_once()
        self.fake.submit_responses = [(403, {"detail": "Insufficient balance"})]
        self.assertEqual(self.drive(job, steps=("submit",)), ["lost"])
        self.assert_lost(job)
        self.assertTrue(cache.get(PROVIDER_DOWN_KEY))

    def test_422_on_replay_goes_to_lost(self):
        job = self.sent_once()
        self.fake.submit_responses = [(422, {"detail": "other body"})]
        self.assertEqual(self.drive(job, steps=("submit",)), ["lost"])
        self.assert_lost(job)

    def test_replay_skips_slot_wait(self):
        job = self.sent_once()
        with self.settings(CREATIVE_MAX_PARALLEL=1):
            busy = make_job(self.user)
            self.drive(busy, steps=("submit",))
            self.assertEqual(busy.status, "running")
            self.assertEqual(self.drive(job, steps=("submit",)), ["running"])
        sub = self.fake.submits()
        self.assertEqual(sub[0]["idem"], sub[-1]["idem"])

    def test_retry_after_hint_is_capped(self):
        job = make_job(self.user)
        self.fake.submit_responses = [(429, {"detail": {"code": "account_queue_full",
                                                        "retry_after_seconds": 3600}})]
        self.assertEqual(self.drive(job, steps=("submit",)), ["retry"])
        self.assertLessEqual(job.next_poll_at,
                             timezone.now() + timedelta(seconds=pipeline.SUBMIT_RETRY_MAX_S + 5))

    def test_crash_during_post_counts_as_maybe_sent(self):
        job = make_job(self.user)
        with mock.patch("creative.hf.submit", side_effect=RuntimeError("boom")):
            self.assertEqual(self.drive(job, steps=("submit",)), ["retry"])
        self.assertTrue(job.request_body.get("maybe_sent"))
        self.assertFalse(pipeline.cancel(job.pk))
        # повтор — тем же ключом и тем же телом
        key = job.idempotency_key
        self.assertEqual(self.drive(job, steps=("submit",)), ["running"])
        self.assertEqual(self.fake.submits()[-1]["idem"], key)


class SubmitCrashLoopTests(CreativeTestCase):
    """Отправка, падающая мимо HFError, не держит резерв вечно."""

    def setUp(self):
        super().setUp()
        self.user = make_user(balance=100)

    def test_crash_before_body_retries_then_fails(self):
        job = make_job(self.user)
        with mock.patch("creative.pipeline._prepare_body", side_effect=RuntimeError("soft time limit")):
            self.assertEqual(self.drive(job, steps=("submit",)), ["retry"])
            self.assertEqual((job.status, job.request_body), ("queued", {}))
            CreativeJob.objects.filter(pk=job.pk).update(attempts=pipeline.SUBMIT_MAX_ATTEMPTS - 1)
            self.assertEqual(self.drive(job, steps=("submit",)), ["failed"])
        self.assertEqual((job.status, job.charge_state, job.needs_review), ("failed", "released", False))
        self.assertEqual(total_reserved(self.user), 0)
        self.assertFalse(self.fake.submits())

    def test_claim_over_limit_closes(self):
        fresh = make_job(self.user, status="queued", attempts=pipeline.SUBMIT_MAX_ATTEMPTS)
        self.assertEqual(self.drive(fresh, steps=("submit",)), ["failed"])
        self.assertEqual((fresh.status, fresh.charge_state), ("failed", "released"))
        sent = make_job(self.user, status="queued", attempts=pipeline.SUBMIT_MAX_ATTEMPTS,
                        request_body={"body": {"prompt": "кот"}, "hook": ""}, idempotency_key="k-1")
        self.assertEqual(self.drive(sent, steps=("submit",)), ["lost"])
        self.assertEqual((sent.status, sent.charge_state, sent.needs_review), ("lost", "released", True))
        self.assertFalse(self.fake.submits())

    def test_claim_of_too_old_job_closes(self):
        job = make_job(self.user)
        CreativeJob.objects.filter(pk=job.pk).update(created_at=timezone.now() - timedelta(minutes=45))
        self.assertEqual(self.drive(job, steps=("submit",)), ["failed"])
        self.assertEqual(job.error_code, "queue_timeout")

    def test_sweep_stops_requeueing_stuck_submit(self):
        old = timezone.now() - timedelta(minutes=20)
        no_body = make_job(self.user)
        with_body = make_job(self.user, request_body={"body": {"prompt": "кот"}, "hook": ""},
                             idempotency_key="k-2")
        fresh_body = make_job(self.user, request_body={"body": {"prompt": "кот"}, "hook": ""},
                              idempotency_key="k-3")
        CreativeJob.objects.filter(pk__in=[no_body.pk, with_body.pk]).update(
            status="submitting", attempts=pipeline.SUBMIT_MAX_ATTEMPTS, updated_at=old)
        CreativeJob.objects.filter(pk=fresh_body.pk).update(status="submitting", attempts=1, updated_at=old)
        self.enqueued.clear()
        out = pipeline.sweep()
        for job in (no_body, with_body, fresh_body):
            job.refresh_from_db()
        self.assertEqual(out.get("submit_gave_up"), 2)
        self.assertEqual((no_body.status, no_body.charge_state, no_body.needs_review),
                         ("failed", "released", False))
        self.assertEqual((with_body.status, with_body.charge_state, with_body.needs_review),
                         ("lost", "released", True))
        # зависла с сохранённым телом и попытки есть: назад в очередь с отметкой «могла дойти»
        self.assertEqual(fresh_body.status, "queued")
        self.assertTrue(fresh_body.request_body.get("maybe_sent"))
        self.assertIn(("submit_job", fresh_body.pk), self.enqueued)
        self.assertFalse(pipeline.cancel(fresh_body.pk))


class PurgeTests(CreativeTestCase):
    def test_old_uploads_without_open_jobs_are_removed(self):
        user = make_user(balance=100)
        old = self.make_image(user)
        busy = self.make_image(user)
        from creative.models import CreativeUpload

        CreativeUpload.objects.filter(pk__in=[old.pk, busy.pk]).update(
            created_at=timezone.now() - timedelta(days=30))
        make_job(user, tool="photo-restyle", params={"image": busy.uid, "prompt": "p", "quality": "medium",
                                                     "resolution": "1k", "aspect": "auto", "consent": True})
        with self.captureOnCommitCallbacks(execute=True):
            self.assertEqual(pipeline.purge_uploads(), 1)
        self.assertFalse(CreativeUpload.objects.filter(pk=old.pk).exists())
        self.assertTrue(CreativeUpload.objects.filter(pk=busy.pk).exists())
