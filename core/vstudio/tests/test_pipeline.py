"""Конвейер видеостудии: submit → poll → finalize, картинка, sweep, «Довезти» (§6).

Провайдер подменён (ai.media_provider.*), ffmpeg — тоже (ai.video_edit.*),
постановка задач записывается через pipeline._enqueue и никуда не уходит.
Файлы пишутся во временный MEDIA_ROOT.

После каждого сценария проверяем главное правило денег: у открытого дубля
резерв, у закрытого — никогда; списание — только за выданный результат,
только причиной vstudio_* и ровно один раз.
"""
import base64
import os
from contextlib import ExitStack
from datetime import timedelta
from decimal import Decimal
from unittest import mock

from django.contrib.messages import get_messages
from django.core.cache import cache
from django.db import IntegrityError, OperationalError, transaction
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from ai import media_provider as mp
from ai.models import AiChatMessage, GenerationLog
from plans.models import TokenTransaction
from users.models import Notification
from vstudio import notify, pipeline, tasks
from vstudio.models import Asset, Take, TakeQuerySet
from vstudio.tests import factories as f

SITE = "https://esai.kg"
MP4 = b"\x00\x00\x00\x18ftypmp42" + b"\x00" * 4096
POLL_URL = "https://openrouter.ai/api/v1/videos/gen-1"
CONTENT_URL = "https://openrouter.ai/api/v1/videos/gen-1/content?index=0"


def accepted(job="gen-1"):
    return mp.Submit(state=mp.STATE_ACCEPTED, job_id=job,
                     polling_url=f"https://openrouter.ai/api/v1/videos/{job}", status_code=200)


def ready(cost=0.5, urls=(CONTENT_URL,)):
    return mp.Poll(status="completed", urls=list(urls), cost=cost, status_code=200)


def png_b64(w=800, h=600):
    return base64.b64encode(f.image_bytes(w, h)).decode()


def write_mp4(url, dest, *, max_bytes, wall_s, **_kw):
    with open(dest, "wb") as fh:
        fh.write(MP4)
    return len(MP4)


class PipelineCase(TestCase):
    """Общая обвязка: чистый кэш, временный MEDIA_ROOT, запись постановок задач."""

    def setUp(self):
        cache.clear()
        self.media = self.enterContext(f.media_root())
        self.enqueued = []
        self.notified = []
        patcher = mock.patch("vstudio.pipeline._enqueue", side_effect=self._record)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.push = self.enterContext(mock.patch("users.webpush.notify_user", return_value={}))
        # Сколько места на машине, где идут тесты, на исход влиять не должно:
        # проба хранилища перед отправкой отказывает при остатке меньше 1 ГБ.
        self.enterContext(mock.patch("vstudio.storage_check._free_bytes", return_value=1 << 40))
        self.user = f.make_user(balance=500)
        self.model = f.make_gpt_model()

    def _record(self, name, take_id, countdown=None, **kwargs):
        if name == "notify_take":
            # Уведомление — своя задача; здесь «воркер» выполняет её сразу.
            self.notified.append(take_id)
            tasks.notify_take(take_id)
            return True
        self.enqueued.append((name, take_id, countdown, kwargs))
        return True

    # --- фабрики

    def body_for(self, shot, assets, slot="reference"):
        body = {"model": shot.model_ref, "prompt": "Image 1 идёт по крыше", "duration": 5,
                "resolution": "720p", "aspect_ratio": "16:9"}
        items = [{"type": "image_url", "image_url": {"url": f"{SITE}{a.url}"}} for a in assets]
        if assets and slot == "reference":
            body["input_references"] = items
        elif assets:
            for item, a in zip(items, assets):
                item["frame_type"] = slot if len(assets) == 1 else None
            if len(assets) == 2:
                items[0]["frame_type"], items[1]["frame_type"] = "first_frame", "last_frame"
            body["frame_images"] = items
        return body

    def video_take(self, *, status="queued", assets=None, slot="reference", credits=150, **kw):
        assets = [f.make_asset(self.user)] if assets is None else assets
        if slot == "reference":
            inputs = assets
        elif len(assets) == 2:
            inputs = [(assets[0], "first_frame"), (assets[1], "last_frame")]
        else:
            inputs = [(a, slot) for a in assets]
        shot = f.make_shot(self.user, model=self.model, inputs=inputs)
        kw.setdefault("request_body", self.body_for(shot, assets, slot))
        return f.make_take(shot, status=status, credits=credits, **kw)

    def image_take(self, *, credits=6, **kw):
        model = f.make_gpt_model(f.IMAGE_MODEL_REF)
        shot = f.make_shot(self.user, kind="image", model=model, prompt="Рыжий кот")
        pending = f.make_asset(self.user, project=shot.project, source=Asset.SOURCE_GENERATED_IMAGE,
                               status=Asset.STATUS_PENDING, width=None, height=None)
        kw.setdefault("request_body", {"model": model.openrouter_id, "prompt": "Рыжий кот",
                                       "aspect_ratio": "1:1"})
        take = f.make_take(shot, status=kw.pop("status", "queued"), credits=credits,
                           result_asset=pending, **kw)
        return take, pending

    def set(self, take, **fields):
        Take.objects.filter(pk=take.pk).update(**fields)
        take.refresh_from_db()
        return take

    def ago(self, **kw):
        return timezone.now() - timedelta(**kw)

    # --- проверки

    def assert_money_invariant(self):
        for t in Take.objects.all():
            self.assertEqual(t.status in Take.OPEN, t.charge_state == Take.CHARGE_RESERVED,
                             f"{t.uid}: {t.status}/{t.charge_state}")
            if t.charge_state != Take.CHARGE_CHARGED:
                self.assertEqual(t.credits_charged, 0, t.uid)
        self.assertFalse(TokenTransaction.objects.filter(reason="chat").exists())
        self.assertEqual(AiChatMessage.objects.count(), 0)

    def ledger(self, user=None):
        return list(TokenTransaction.objects.filter(user=user or self.user).order_by("id"))

    def studio_files(self):
        out = []
        for root, _dirs, files in os.walk(os.path.join(self.media, "vstudio")):
            out += [os.path.join(root, name) for name in files]
        return sorted(out)

    def provider(self, *, submit=None, poll=None, download=write_mp4, image=None,
                 probe=None, poster=b"poster"):
        """Подмена провайдера и ffmpeg одним ExitStack.

        Значение — ответ провайдера; функция, исключение или список — side_effect.
        """
        def how(value):
            if callable(value) or isinstance(value, (BaseException, list)):
                return {"side_effect": value}
            return {"return_value": value}

        stack = ExitStack()
        mocks = {}
        if submit is not None:
            mocks["submit"] = stack.enter_context(mock.patch("ai.media_provider.submit_video",
                                                             **how(submit)))
        if poll is not None:
            mocks["poll"] = stack.enter_context(mock.patch("ai.media_provider.poll_video", **how(poll)))
        mocks["download"] = stack.enter_context(mock.patch(
            "ai.media_provider.download_to_file", side_effect=download))
        if image is not None:
            mocks["image"] = stack.enter_context(mock.patch("ai.media_provider.generate_image",
                                                            **how(image)))
        mocks["probe"] = stack.enter_context(mock.patch(
            "ai.video_edit.probe_video",
            return_value={"width": 1280, "height": 720, "duration": 5.04} if probe is None else probe))
        poster_bytes = f.image_bytes(1280, 720) if poster == b"poster" else poster
        mocks["poster"] = stack.enter_context(mock.patch("ai.video_edit.extract_poster",
                                                         return_value=poster_bytes))
        stack.mocks = mocks
        return stack


# ---------------------------------------------------------------- submit

class SubmitTests(PipelineCase):
    def test_accepted_take_runs_with_ids_on_the_take(self):
        take = self.video_take()
        before = timezone.now()
        with self.provider(submit=accepted()) as p, self.assertLogs("vstudio", "INFO") as logs:
            self.assertEqual(pipeline.submit(take.pk), "running")
        take.refresh_from_db()
        self.assertEqual(take.status, Take.STATUS_RUNNING)
        self.assertEqual(take.charge_state, Take.CHARGE_RESERVED)
        self.assertEqual(take.provider_id, "gen-1")
        self.assertEqual(take.polling_url, POLL_URL)
        self.assertGreaterEqual(take.submitted_at, before)
        self.assertAlmostEqual((take.next_poll_at - take.submitted_at).total_seconds(), 15, delta=1)
        self.assertEqual(self.enqueued, [("poll_take", take.pk, 15, {})])
        # Тело уходит ровно то, что показано в «Что ушло модели».
        self.assertEqual(p.mocks["submit"].call_args.args[0], take.request_body)
        row = GenerationLog.objects.get(pk=take.genlog_id)
        self.assertEqual((row.source, row.kind, row.status), ("vstudio", "video", "submitted"))
        self.assertEqual(row.params["take"], take.uid)
        self.assertEqual((row.params["mode"], row.params["refs"], row.params["frames"]), ("r2v", 1, 0))
        self.assertEqual(row.params["duration"], 5)
        self.assertEqual((row.provider_id, row.polling_url), ("gen-1", POLL_URL))
        self.assertEqual(row.credits_planned, 150)
        self.assertEqual(row.prompt, take.serialized_prompt)
        self.assertIsNone(row.session_id)
        self.assertTrue(any(f"vstudio accepted take={take.uid} provider_id=gen-1" in m
                            for m in logs.output), logs.output)
        self.assert_money_invariant()

    def test_accepted_log_line_is_written_before_the_database(self):
        take = self.video_take()
        real = TakeQuerySet.transition

        def blink(qs, pk, frm, to=None, **fields):
            if to == Take.STATUS_RUNNING:
                raise OperationalError("db blinked")
            return real(qs, pk, frm, to, **fields)

        with self.provider(submit=accepted("gen-lost")), \
                mock.patch.object(TakeQuerySet, "transition", blink), \
                self.assertLogs("vstudio", "INFO") as logs:
            with self.assertRaises(OperationalError):
                pipeline.submit(take.pk)
        self.assertTrue(any("provider_id=gen-lost" in m for m in logs.output), logs.output)

    def test_second_copy_of_the_task_sends_nothing(self):
        take = self.video_take()
        with self.provider(submit=accepted()) as p:
            self.assertEqual(pipeline.submit(take.pk), "running")
            self.assertEqual(pipeline.submit(take.pk), "skip")
            self.assertEqual(tasks.submit_take(take.pk), "skip")
        self.assertEqual(p.mocks["submit"].call_count, 1)
        self.assertEqual(GenerationLog.objects.count(), 1)

    def test_fail_closed_when_journal_is_unavailable(self):
        take = self.video_take()
        with self.provider(submit=accepted()) as p, \
                mock.patch.object(GenerationLog.objects, "create",
                                  side_effect=OperationalError("journal down")):
            self.assertEqual(pipeline.submit(take.pk), "failed")
        p.mocks["submit"].assert_not_called()
        take.refresh_from_db()
        self.assertEqual((take.status, take.error_code), ("failed", "journal_unavailable"))
        self.assertEqual(take.charge_state, Take.CHARGE_RELEASED)
        self.assertIsNone(take.genlog_id)
        self.assertIn("не списаны", take.error)
        self.assertEqual(self.enqueued, [])
        # Внешняя транзакция цела: savepoint в genlog.start.
        self.assertEqual(GenerationLog.objects.count(), 0)
        self.assert_money_invariant()

    def test_rejection_fails_without_charge_and_points_at_the_photo(self):
        photo = f.make_asset(self.user)
        take = self.video_take(assets=[photo])
        res = mp.Submit(state=mp.STATE_REJECTED, status_code=400,
                        text='{"error":{"message":"The image may contain real person"}}')
        with self.provider(submit=res):
            self.assertEqual(pipeline.submit(take.pk), "failed")
        take.refresh_from_db()
        self.assertEqual((take.status, take.error_code), ("failed", "image_real_person"))
        self.assertEqual(take.error_input, photo.uid)
        self.assertIn("реальных людей", take.error)
        self.assertEqual((take.charge_state, take.credits_charged), ("released", 0))
        row = GenerationLog.objects.get(pk=take.genlog_id)
        self.assertEqual(row.status, "failed")
        self.assertIn("real person", row.error)
        self.assertFalse(row.needs_review)
        self.assertEqual(self.ledger(), [])
        self.assertEqual(self.enqueued, [])
        self.assert_money_invariant()

    def test_frames_blame_the_first_frame(self):
        first, last = f.make_asset(self.user), f.make_asset(self.user)
        take = self.video_take(assets=[first, last], slot="frames")
        res = mp.Submit(state=mp.STATE_REJECTED, status_code=400,
                        text="InputImageSensitiveContentDetected")
        with self.provider(submit=res):
            pipeline.submit(take.pk)
        take.refresh_from_db()
        self.assertEqual((take.error_code, take.error_input), ("image_sensitive", first.uid))

    def test_text_rejection_blames_no_photo(self):
        take = self.video_take()
        res = mp.Submit(state=mp.STATE_REJECTED, status_code=400, text="content policy violation")
        with self.provider(submit=res):
            pipeline.submit(take.pk)
        take.refresh_from_db()
        self.assertEqual((take.error_code, take.error_input), ("prompt_rejected", ""))

    def test_unknown_outcome_is_lost_for_review_and_free(self):
        take = self.video_take()
        res = mp.Submit(state=mp.STATE_UNKNOWN, status_code=502, text="bad gateway")
        with self.provider(submit=res):
            self.assertEqual(pipeline.submit(take.pk), "lost")
        take.refresh_from_db()
        self.assertEqual((take.status, take.error_code), ("lost", "submit_unknown"))
        self.assertEqual(take.charge_state, "released")
        row = GenerationLog.objects.get(pk=take.genlog_id)
        self.assertEqual(row.status, "lost")
        self.assertTrue(row.needs_review)
        self.assertEqual(self.ledger(), [])
        self.assert_money_invariant()

    def test_journal_lives_in_submitting_only_while_sending(self):
        take = self.video_take()
        seen = {}

        def spy(body, **kw):
            row = GenerationLog.objects.get(source="vstudio")
            seen["status"] = row.status
            return accepted()

        with self.provider(submit=spy):
            pipeline.submit(take.pk)
        self.assertEqual(seen["status"], "submitting")
        self.assertEqual(GenerationLog.objects.get(source="vstudio").status, "submitted")

    @override_settings(VSTUDIO_INLINE_REFS=True)
    def test_inline_refs_send_data_urls_but_keep_the_stored_body(self):
        photo = f.make_asset(self.user, store=True, width=640, height=480)
        take = self.video_take(assets=[photo])
        stored_url = take.request_body["input_references"][0]["image_url"]["url"]
        with self.provider(submit=accepted()) as p:
            pipeline.submit(take.pk)
        sent = p.mocks["submit"].call_args.args[0]["input_references"][0]["image_url"]["url"]
        self.assertTrue(sent.startswith("data:image/jpeg;base64,"), sent[:40])
        with open(os.path.join(self.media, photo.file), "rb") as fh:
            self.assertEqual(base64.b64decode(sent.split(",", 1)[1]), fh.read())
        take.refresh_from_db()
        self.assertEqual(take.request_body["input_references"][0]["image_url"]["url"], stored_url)

    @override_settings(VSTUDIO_INLINE_REFS=True)
    def test_inline_refs_with_missing_file_fail_loudly(self):
        take = self.video_take()  # файла на диске нет
        with self.provider(submit=accepted()) as p:
            self.assertEqual(pipeline.submit(take.pk), "failed")
        p.mocks["submit"].assert_not_called()
        take.refresh_from_db()
        self.assertEqual((take.status, take.error_code), ("failed", "service_misconfigured"))
        self.assertEqual(GenerationLog.objects.get(pk=take.genlog_id).status, "failed")

    def test_storage_name_accepts_only_studio_files(self):
        self.assertEqual(pipeline.storage_name(f"{SITE}/media/vstudio/1/{'a' * 32}.jpg"),
                         f"vstudio/1/{'a' * 32}.jpg")
        self.assertEqual(pipeline.storage_name("/media/vstudio/1/x.png"), "vstudio/1/x.png")
        for bad in ("/media/ai_images/x.png", "/media/vstudio/../settings.py", "https://evil/x.jpg",
                    "/static/vstudio/1/x.jpg"):
            with self.assertRaises(ValueError, msg=bad):
                pipeline.storage_name(bad)

    def test_accepted_after_take_was_closed_keeps_ids_for_redelivery(self):
        take = self.video_take()
        real = TakeQuerySet.transition

        def closed_meanwhile(qs, pk, frm, to=None, **fields):
            if to == Take.STATUS_RUNNING:
                real(Take.objects.all(), pk, Take.STATUS_SUBMITTING, Take.STATUS_LOST,
                     error_code="submit_unknown")
            return real(qs, pk, frm, to, **fields)

        with self.provider(submit=accepted("gen-late")), \
                mock.patch.object(TakeQuerySet, "transition", closed_meanwhile):
            self.assertEqual(pipeline.submit(take.pk), "lost")
        take.refresh_from_db()
        self.assertEqual((take.status, take.provider_id), ("lost", "gen-late"))
        self.assertTrue(take.polling_url.endswith("/gen-late"))
        row = GenerationLog.objects.get(pk=take.genlog_id)
        self.assertEqual(row.status, "lost")
        self.assertTrue(row.needs_review)
        self.assertEqual(self.enqueued, [])


# ---------------------------------------------------------------- poll

class PollTests(PipelineCase):
    def running(self, **kw):
        take = self.video_take(status="running", genlog=True, **kw)
        return self.set(take, submitted_at=self.ago(seconds=30), next_poll_at=self.ago(seconds=1))

    def test_not_due_yet_is_skipped(self):
        take = self.set(self.running(), next_poll_at=timezone.now() + timedelta(seconds=30))
        with self.provider(poll=mp.Poll(status="in_progress")) as p:
            self.assertEqual(pipeline.poll(take.pk), "skip")
        p.mocks["poll"].assert_not_called()

    def test_in_progress_reschedules_with_countdown(self):
        take = self.running()
        with self.provider(poll=mp.Poll(status="in_progress", status_code=200)):
            self.assertEqual(pipeline.poll(take.pk), "polling")
        take.refresh_from_db()
        self.assertEqual((take.status, take.stage, take.poll_count), ("running", "in_progress", 1))
        self.assertAlmostEqual((take.next_poll_at - timezone.now()).total_seconds(), 9, delta=2)
        self.assertEqual(self.enqueued, [("poll_take", take.pk, 10, {})])
        self.assert_money_invariant()

    def test_step_grows_with_time(self):
        now = timezone.now()
        take = self.running()
        for elapsed, step in ((timedelta(seconds=30), 10), (timedelta(minutes=5), 20),
                              (timedelta(minutes=20), 60), (timedelta(hours=2), 60)):
            take.submitted_at = now - elapsed
            self.assertEqual(pipeline.poll_step(take, now), step)

    def test_network_blip_keeps_polling(self):
        take = self.set(self.running(), stage="in_progress")
        with self.provider(poll=mp.Poll(transient=True, error="http 502", status_code=502)):
            self.assertEqual(pipeline.poll(take.pk), "polling")
        take.refresh_from_db()
        self.assertEqual((take.status, take.stage), ("running", "in_progress"))
        self.assertEqual(self.enqueued[0][0], "poll_take")

    def test_completed_goes_to_saving_and_finalize(self):
        take = self.running()
        with self.provider(poll=ready(cost=0.42)):
            self.assertEqual(pipeline.poll(take.pk), "saving")
        take.refresh_from_db()
        self.assertEqual((take.status, take.charge_state), ("saving", "reserved"))
        self.assertLessEqual(take.lease_until, timezone.now())
        self.assertEqual(take.provider_cost_usd, Decimal("0.4200"))
        self.assertEqual(self.enqueued, [("finalize_take", take.pk, None, {})])
        self.assert_money_invariant()

    def test_completed_without_link_still_goes_to_finalize(self):
        take = self.running()
        with self.provider(poll=mp.Poll(status="completed", urls=[])):
            self.assertEqual(pipeline.poll(take.pk), "saving")
        self.assertEqual(self.enqueued[0][0], "finalize_take")

    def test_provider_failure_fails_and_releases(self):
        photo = f.make_asset(self.user)
        take = self.running(assets=[photo])
        with self.provider(poll=mp.Poll(status="failed", error="may contain real person")):
            self.assertEqual(pipeline.poll(take.pk), "failed")
        take.refresh_from_db()
        self.assertEqual((take.status, take.error_code, take.error_input),
                         ("failed", "image_real_person", photo.uid))
        self.assertEqual(take.charge_state, "released")
        self.assertEqual(GenerationLog.objects.get(pk=take.genlog_id).status, "failed")
        self.assertEqual(self.enqueued, [])
        self.assert_money_invariant()

    def test_second_chain_dies_on_claim(self):
        take = self.running()
        with self.provider(poll=mp.Poll(status="in_progress")) as p:
            self.assertEqual(pipeline.poll(take.pk), "polling")
            self.assertEqual(pipeline.poll(take.pk), "skip")
            self.assertEqual(tasks.poll_take(take.pk), "skip")
        self.assertEqual(p.mocks["poll"].call_count, 1)
        self.assertEqual(len(self.enqueued), 1)

    def test_completed_twice_enqueues_one_finalize(self):
        take = self.running()
        with self.provider(poll=ready()):
            self.assertEqual(pipeline.poll(take.pk), "saving")
            self.set(take, next_poll_at=self.ago(seconds=5))
            self.assertEqual(pipeline.poll(take.pk), "skip")
        self.assertEqual([e[0] for e in self.enqueued], ["finalize_take"])

    def test_closed_take_is_not_polled(self):
        take = self.video_take(status="failed")
        with self.provider(poll=ready()) as p:
            self.assertEqual(pipeline.poll(take.pk), "skip")
        p.mocks["poll"].assert_not_called()

    def test_journal_pulse_is_throttled(self):
        take = self.running()
        GenerationLog.objects.filter(pk=take.genlog_id).update(updated_at=self.ago(minutes=5))
        with self.provider(poll=mp.Poll(status="in_progress")):
            pipeline.poll(take.pk)
        first = GenerationLog.objects.get(pk=take.genlog_id).updated_at
        self.assertGreater(first, self.ago(seconds=5))
        GenerationLog.objects.filter(pk=take.genlog_id).update(updated_at=self.ago(minutes=5))
        self.set(take, next_poll_at=self.ago(seconds=1))
        with self.provider(poll=mp.Poll(status="in_progress")):
            pipeline.poll(take.pk)
        self.assertLess(GenerationLog.objects.get(pk=take.genlog_id).updated_at, self.ago(minutes=4))


# ---------------------------------------------------------------- finalize

class FinalizeTests(PipelineCase):
    def saving(self, credits=150, **kw):
        take = self.video_take(status="saving", genlog=True, credits=credits, **kw)
        return self.set(take, lease_until=timezone.now(), submitted_at=self.ago(minutes=2),
                        created_at=self.ago(minutes=3))

    def test_delivers_charges_once_and_links_everything(self):
        take = self.saving()
        project_before = self.ago(hours=1)
        type(take.project).objects.filter(pk=take.project_id).update(last_activity_at=project_before)
        with self.provider(poll=ready(cost=0.5)):
            self.assertEqual(pipeline.finalize(take.pk), "done")
        take.refresh_from_db()
        self.assertEqual((take.status, take.charge_state, take.credits_charged), ("done", "charged", 150))
        self.assertEqual(take.provider_cost_usd, Decimal("0.5000"))
        self.assertIsNone(take.lease_until)
        self.assertIsNotNone(take.finished_at)
        self.assertEqual(take.attempts, 1)
        asset = take.result_asset
        self.assertEqual((asset.kind, asset.source, asset.status),
                         ("video", "generated_video", "ready"))
        self.assertEqual((asset.user_id, asset.project_id, asset.origin_take_id),
                         (self.user.pk, take.project_id, take.pk))
        self.assertEqual((asset.width, asset.height, asset.duration_s, asset.mime),
                         (1280, 720, 5.04, "video/mp4"))
        self.assertEqual(asset.bytes, len(MP4))
        self.assertTrue(asset.file.startswith(f"vstudio/{self.user.pk}/{asset.uid}"))
        self.assertTrue(asset.thumb.endswith("_t.jpg"))
        with open(os.path.join(self.media, asset.file), "rb") as fh:
            self.assertEqual(fh.read(), MP4)
        self.assertTrue(os.path.exists(os.path.join(self.media, asset.thumb)))
        self.assertEqual(asset.meta["take"], take.uid)
        # Журнал: прямой UPDATE, result_url — для «Поделиться».
        row = GenerationLog.objects.get(pk=take.genlog_id)
        self.assertEqual((row.status, row.credits_charged, row.needs_review), ("delivered", 150, False))
        self.assertEqual(row.result_url, asset.url)
        self.assertEqual(row.provider_cost_usd, Decimal("0.5000"))
        self.assertIn("delivered", [s["stage"] for s in row.stages])
        from ai.handlers import _user_owns_video

        self.assertTrue(_user_owns_video(self.user, asset.url))
        # Деньги: одна строка леджера с причиной студии.
        ledger = self.ledger()
        self.assertEqual([(t.delta, t.reason) for t in ledger], [(-150, "vstudio_video")])
        self.assertEqual(ledger[0].meta["take"], take.uid)
        self.user.refresh_from_db()
        self.assertEqual(self.user.token_balance, 350)
        take.project.refresh_from_db()
        self.assertGreater(take.project.last_activity_at, project_before)
        self.assert_money_invariant()

    def test_quote_reserve_and_charge_are_the_same_number(self):
        take = self.saving(credits=164)
        with self.provider(poll=ready()):
            pipeline.finalize(take.pk)
        take.refresh_from_db()
        self.assertEqual({take.credits_quoted, take.credits_reserved, take.credits_charged}, {164})
        self.assertEqual(self.ledger()[0].delta, -164)

    def test_second_copy_waits_for_the_lease(self):
        take = self.saving()
        self.set(take, lease_until=timezone.now() + timedelta(minutes=3))
        with self.provider(poll=ready()) as p:
            self.assertEqual(pipeline.finalize(take.pk), "skip")
            self.assertEqual(tasks.finalize_take(take.pk), "skip")
        p.mocks["poll"].assert_not_called()

    def test_download_failure_keeps_saving_and_retries_soon(self):
        take = self.saving()

        def broken(url, dest, **kw):
            raise mp.DownloadError("timeout", "download: дольше 180 с")

        with self.provider(poll=ready(), download=broken):
            self.assertEqual(pipeline.finalize(take.pk), "retry")
        take.refresh_from_db()
        self.assertEqual((take.status, take.charge_state, take.attempts), ("saving", "reserved", 1))
        self.assertAlmostEqual((take.lease_until - timezone.now()).total_seconds(), 60, delta=3)
        self.assertEqual(Asset.objects.filter(kind="video").count(), 0)
        self.assertEqual(self.studio_files(), [])
        self.assertEqual(self.ledger(), [])
        row = GenerationLog.objects.get(pk=take.genlog_id)
        self.assertEqual(row.status, "submitted")
        self.assertIn("save_retry", [s["stage"] for s in row.stages])
        self.assert_money_invariant()

    def test_retry_backoff_grows(self):
        take = self.saving()
        self.set(take, attempts=2)
        with self.provider(poll=mp.Poll(status="completed", urls=[])):
            self.assertEqual(pipeline.finalize(take.pk), "retry")
        take.refresh_from_db()
        self.assertEqual(take.attempts, 3)
        self.assertAlmostEqual((take.lease_until - timezone.now()).total_seconds(), 240, delta=3)

    def test_failure_inside_the_transaction_rolls_back_and_deletes_files(self):
        take = self.saving()
        with self.provider(poll=ready()), \
                mock.patch("vstudio.delivery.charge_on_delivery", side_effect=RuntimeError("wallet")):
            self.assertEqual(pipeline.finalize(take.pk), "retry")
        take.refresh_from_db()
        self.assertEqual((take.status, take.charge_state), ("saving", "reserved"))
        self.assertIsNone(take.result_asset_id)
        self.assertEqual(Asset.objects.filter(kind="video").count(), 0)
        self.assertEqual(self.studio_files(), [])
        self.assertEqual(GenerationLog.objects.get(pk=take.genlog_id).status, "submitted")
        self.assertEqual(self.ledger(), [])
        self.assert_money_invariant()

    def test_partial_charge_takes_what_is_left_and_flags_review(self):
        take = self.saving()
        type(self.user).objects.filter(pk=self.user.pk).update(token_balance=100)
        with self.provider(poll=ready()):
            self.assertEqual(pipeline.finalize(take.pk), "done")
        take.refresh_from_db()
        self.assertEqual((take.status, take.charge_state, take.credits_charged), ("done", "charged", 100))
        row = GenerationLog.objects.get(pk=take.genlog_id)
        self.assertEqual(row.credits_charged, 100)
        self.assertTrue(row.needs_review)
        ledger = self.ledger()
        self.assertEqual([(t.delta, t.reason) for t in ledger], [(-100, "vstudio_video")])
        self.assertTrue(ledger[0].meta["partial"])
        self.user.refresh_from_db()
        self.assertEqual(self.user.token_balance, 0)
        self.assert_money_invariant()

    def test_expired_on_repoll_is_lost_and_free(self):
        take = self.saving()
        with self.provider(poll=mp.Poll(status="expired")):
            self.assertEqual(pipeline.finalize(take.pk), "lost")
        take.refresh_from_db()
        self.assertEqual((take.status, take.error_code, take.charge_state),
                         ("lost", "save_failed", "released"))
        row = GenerationLog.objects.get(pk=take.genlog_id)
        self.assertEqual(row.status, "lost")
        self.assertTrue(row.needs_review)
        self.assertEqual(self.ledger(), [])

    def test_markup_instead_of_video_is_not_delivered(self):
        take = self.saving()

        def html(url, dest, **kw):
            with open(dest, "wb") as fh:
                fh.write(b"  <html><body>error</body></html>")
            return 33

        with self.provider(poll=ready(), download=html):
            self.assertEqual(pipeline.finalize(take.pk), "retry")
        self.assertEqual(Asset.objects.filter(kind="video").count(), 0)
        self.assertEqual(self.studio_files(), [])

    def test_missing_ffmpeg_still_delivers(self):
        take = self.saving()
        with self.provider(poll=ready(), probe={}, poster=None):
            self.assertEqual(pipeline.finalize(take.pk), "done")
        asset = Take.objects.get(pk=take.pk).result_asset
        self.assertEqual((asset.width, asset.thumb), (None, ""))

    def test_huge_video_is_delivered_without_reading_it_into_memory(self):
        take = self.saving()
        with self.provider(poll=ready()) as p, mock.patch("vstudio.delivery.PROBE_MAX_BYTES", 100):
            self.assertEqual(pipeline.finalize(take.pk), "done")
        p.mocks["probe"].assert_not_called()
        p.mocks["poster"].assert_not_called()
        asset = Take.objects.get(pk=take.pk).result_asset
        self.assertEqual((asset.bytes, asset.width, asset.thumb), (len(MP4), None, ""))

    def test_cost_from_earlier_poll_is_kept(self):
        take = self.set(self.saving(), provider_cost_usd=Decimal("0.3100"))
        with self.provider(poll=ready(cost=None)):
            pipeline.finalize(take.pk)
        take.refresh_from_db()
        self.assertEqual(take.provider_cost_usd, Decimal("0.3100"))
        self.assertEqual(GenerationLog.objects.get(pk=take.genlog_id).provider_cost_usd,
                         Decimal("0.3100"))

    def test_low_margin_is_checked_after_commit(self):
        take = self.saving()
        with self.provider(poll=ready(cost=9.9)), \
                mock.patch("vstudio.pricing.check_margin", return_value=False) as check:
            pipeline.finalize(take.pk)
        check.assert_called_once()
        self.assertEqual(check.call_args.args[0].pk, take.pk)
        self.assertEqual(check.call_args.kwargs["cost_usd"], Decimal("9.9000"))

    def test_notifies_when_the_page_is_closed(self):
        take = self.saving()
        with self.provider(poll=ready()):
            pipeline.finalize(take.pk)
        self.assertEqual(self.notified, [take.pk])       # отдельной задачей
        self.push.assert_called_once()
        args, kwargs = self.push.call_args
        self.assertEqual(args[1], "Видео готово")
        self.assertEqual(kwargs["url"], f"/video-studio/{take.project.uid}?take={take.uid}")
        self.assertTrue(Notification.objects.filter(title="Видео готово",
                                                    recipients=self.user).exists())

    def test_journal_row_is_restored_if_missing(self):
        take = self.saving()
        GenerationLog.objects.filter(pk=take.genlog_id).delete()
        with self.provider(poll=ready()):
            self.assertEqual(pipeline.finalize(take.pk), "done")
        take.refresh_from_db()
        row = take.genlog
        self.assertIsNotNone(row)
        self.assertEqual((row.status, row.source, row.params["take"]), ("delivered", "vstudio", take.uid))
        self.assertEqual(row.result_url, take.result_asset.url)


# ---------------------------------------------------------------- картинка

class ImageTests(PipelineCase):
    def ok(self, cost=0.039):
        return mp.Images(items=[mp.ImageItem(b64=png_b64(), media_type="image/jpeg")], cost=cost,
                         status_code=200)

    def test_image_is_delivered_and_charged(self):
        take, pending = self.image_take()
        with self.provider(image=self.ok()):
            self.assertEqual(pipeline.run_image(take.pk), "done")
        take.refresh_from_db()
        pending.refresh_from_db()
        self.assertEqual((take.status, take.charge_state, take.credits_charged), ("done", "charged", 6))
        self.assertIsNotNone(take.submitted_at)
        self.assertEqual(take.result_asset_id, pending.pk)
        self.assertEqual((pending.status, pending.width, pending.height), ("ready", 800, 600))
        self.assertEqual(pending.mime, "image/jpeg")
        self.assertTrue(os.path.exists(os.path.join(self.media, pending.file)))
        self.assertTrue(os.path.exists(os.path.join(self.media, pending.thumb)))
        self.assertTrue(pending.file.startswith(f"vstudio/{self.user.pk}/{pending.uid}."))
        self.assertEqual(pending.meta["take"], take.uid)
        row = GenerationLog.objects.get(pk=take.genlog_id)
        self.assertEqual((row.kind, row.source, row.status, row.credits_charged),
                         ("image", "vstudio", "delivered", 6))
        self.assertEqual(row.params["take"], take.uid)
        self.assertEqual(row.result_url, pending.url)
        self.assertEqual(row.provider_cost_usd, Decimal("0.0390"))
        self.assertEqual([(t.delta, t.reason) for t in self.ledger()], [(-6, "vstudio_image")])
        self.assert_money_invariant()

    def test_rejection_fails_asset_and_releases(self):
        take, pending = self.image_take()
        res = mp.Images(error='{"error":{"message":"content policy"}}', status_code=400)
        with self.provider(image=res):
            self.assertEqual(pipeline.run_image(take.pk), "failed")
        take.refresh_from_db()
        pending.refresh_from_db()
        self.assertEqual((take.status, take.error_code, take.charge_state),
                         ("failed", "prompt_rejected", "released"))
        self.assertEqual((pending.status, pending.error_code), ("failed", "prompt_rejected"))
        row = GenerationLog.objects.get(pk=take.genlog_id)
        self.assertEqual(row.status, "failed")
        self.assertFalse(row.needs_review)
        self.assertEqual(self.ledger(), [])
        self.assert_money_invariant()

    def test_no_answer_is_failed_but_reviewed(self):
        take, pending = self.image_take()
        with self.provider(image=mp.Images(error="ReadTimeout: read timed out")):
            self.assertEqual(pipeline.run_image(take.pk), "failed")
        self.assertTrue(GenerationLog.objects.get(pk=Take.objects.get(pk=take.pk).genlog_id).needs_review)

    def test_exception_is_a_failure_too(self):
        take, pending = self.image_take()
        with self.provider(image=RuntimeError("boom")):
            self.assertEqual(pipeline.run_image(take.pk), "failed")
        take.refresh_from_db()
        pending.refresh_from_db()
        self.assertEqual((take.status, pending.status), ("failed", "failed"))
        self.assertNotIn(GenerationLog.objects.get(pk=take.genlog_id).status,
                         GenerationLog.OPEN_STATES)

    def test_fail_closed(self):
        take, pending = self.image_take()
        with self.provider(image=self.ok()) as p, \
                mock.patch.object(GenerationLog.objects, "create", side_effect=OperationalError("x")):
            self.assertEqual(pipeline.run_image(take.pk), "failed")
        p.mocks["image"].assert_not_called()
        take.refresh_from_db()
        pending.refresh_from_db()
        self.assertEqual((take.status, take.error_code), ("failed", "journal_unavailable"))
        self.assertEqual(pending.status, "failed")
        self.assert_money_invariant()

    def test_garbage_bytes_are_not_delivered(self):
        take, pending = self.image_take()
        junk = mp.Images(items=[mp.ImageItem(b64=base64.b64encode(b"not an image").decode(),
                                             media_type="image/png")], cost=0.04, status_code=200)
        with self.provider(image=junk):
            self.assertEqual(pipeline.run_image(take.pk), "failed")
        take.refresh_from_db()
        self.assertEqual((take.status, take.error_code), ("failed", "bad_result"))
        self.assertEqual(take.provider_cost_usd, Decimal("0.0400"))
        self.assertEqual(self.studio_files(), [])
        self.assertEqual(self.ledger(), [])

    def test_second_copy_does_nothing(self):
        take, _ = self.image_take()
        with self.provider(image=self.ok()) as p:
            self.assertEqual(pipeline.run_image(take.pk), "done")
            self.assertEqual(pipeline.run_image(take.pk), "skip")
            self.assertEqual(tasks.run_image_take(take.pk), "skip")
        self.assertEqual(p.mocks["image"].call_count, 1)
        self.assertEqual(len(self.ledger()), 1)

    def test_reference_moderation_blames_the_photo(self):
        photo = f.make_asset(self.user)
        take, _ = self.image_take(request_body={
            "model": f.IMAGE_MODEL_REF, "prompt": "p",
            "input_references": [{"type": "image_url", "image_url": {"url": f"{SITE}{photo.url}"}}]})
        with self.provider(image=mp.Images(error="PrivacyInformation", status_code=400)):
            pipeline.run_image(take.pk)
        self.assertEqual(Take.objects.get(pk=take.pk).error_input, photo.uid)

    def test_image_without_pending_asset_gets_a_new_one(self):
        take, pending = self.image_take()
        self.set(take, result_asset=None)
        with self.provider(image=self.ok()):
            self.assertEqual(pipeline.run_image(take.pk), "done")
        take.refresh_from_db()
        self.assertNotEqual(take.result_asset_id, pending.pk)
        self.assertEqual((take.result_asset.source, take.result_asset.status),
                         ("generated_image", "ready"))


# ---------------------------------------------------------------- sweep

class SweepTests(PipelineCase):
    def test_old_queued_take_is_requeued_once(self):
        take = self.set(self.video_take(), created_at=self.ago(minutes=4))
        image, _ = self.image_take()
        self.set(image, created_at=self.ago(minutes=4))
        fresh = self.video_take()
        out = pipeline.sweep()
        self.assertEqual(out["requeued"], 2)
        self.assertCountEqual([e[:2] for e in self.enqueued],
                              [("submit_take", take.pk), ("run_image_take", image.pk)])
        self.enqueued.clear()
        pipeline.sweep()
        self.assertEqual(self.enqueued, [])  # не чаще раза в ~2 минуты
        self.assertEqual(Take.objects.get(pk=fresh.pk).status, "queued")

    def test_queued_for_half_an_hour_fails_and_releases(self):
        take = self.set(self.video_take(), created_at=self.ago(minutes=31))
        image, pending = self.image_take()
        self.set(image, created_at=self.ago(minutes=31))
        out = pipeline.sweep()
        self.assertEqual(out["queue_timeout"], 2)
        take.refresh_from_db()
        pending.refresh_from_db()
        self.assertEqual((take.status, take.error_code, take.charge_state),
                         ("failed", "queue_timeout", "released"))
        self.assertEqual(pending.status, "failed")
        self.assert_money_invariant()

    def test_submitting_for_15_minutes_is_lost(self):
        take = self.video_take(status="submitting", genlog=True)
        self.set(take, updated_at=self.ago(minutes=16))
        recent = self.set(self.video_take(status="submitting"), updated_at=self.ago(minutes=5))
        pipeline.sweep()
        take.refresh_from_db()
        self.assertEqual((take.status, take.error_code, take.charge_state),
                         ("lost", "submit_unknown", "released"))
        row = GenerationLog.objects.get(pk=take.genlog_id)
        self.assertEqual(row.status, "lost")
        self.assertTrue(row.needs_review)
        self.assertEqual(Take.objects.get(pk=recent.pk).status, "submitting")

    def test_lost_poll_chain_is_restarted(self):
        stale = self.video_take(status="running")
        self.set(stale, submitted_at=self.ago(minutes=10), next_poll_at=self.ago(minutes=2))
        alive = self.video_take(status="running")
        self.set(alive, submitted_at=self.ago(minutes=10),
                 next_poll_at=timezone.now() + timedelta(seconds=20))
        pipeline.sweep()
        self.assertEqual([e[:2] for e in self.enqueued], [("poll_take", stale.pk)])

    def test_six_hours_without_result_is_lost(self):
        take = self.video_take(status="running", genlog=True)
        self.set(take, submitted_at=self.ago(hours=6, minutes=1), next_poll_at=self.ago(minutes=5))
        younger = self.video_take(status="running")
        self.set(younger, submitted_at=self.ago(hours=5, minutes=50),
                 next_poll_at=timezone.now() + timedelta(seconds=30))
        out = pipeline.sweep()
        self.assertEqual(out["provider_timeout"], 1)
        take.refresh_from_db()
        self.assertEqual((take.status, take.error_code, take.charge_state),
                         ("lost", "provider_timeout", "released"))
        self.assertTrue(GenerationLog.objects.get(pk=take.genlog_id).needs_review)
        self.assertNotIn(("poll_take", take.pk), [e[:2] for e in self.enqueued])
        self.assertEqual(Take.objects.get(pk=younger.pk).status, "running")
        self.assert_money_invariant()

    @override_settings(VSTUDIO_GIVE_UP_HOURS=1)
    def test_give_up_hours_come_from_settings(self):
        take = self.video_take(status="running")
        self.set(take, submitted_at=self.ago(minutes=61), next_poll_at=timezone.now())
        pipeline.sweep()
        self.assertEqual(Take.objects.get(pk=take.pk).status, "lost")

    def test_image_running_for_8_minutes_is_lost(self):
        take, pending = self.image_take(status="running")
        self.set(take, submitted_at=self.ago(minutes=9))
        pipeline.sweep()
        take.refresh_from_db()
        pending.refresh_from_db()
        self.assertEqual((take.status, take.error_code), ("lost", "provider_timeout"))
        self.assertEqual(pending.status, "failed")

    def test_saving_with_expired_lease_is_finalized_again(self):
        take = self.video_take(status="saving")
        self.set(take, lease_until=self.ago(seconds=5), attempts=2)
        busy = self.video_take(status="saving")
        self.set(busy, lease_until=timezone.now() + timedelta(minutes=2), attempts=1)
        pipeline.sweep()
        self.assertEqual([e[:2] for e in self.enqueued], [("finalize_take", take.pk)])

    def test_saving_after_five_attempts_is_lost(self):
        take = self.video_take(status="saving", genlog=True)
        self.set(take, lease_until=self.ago(seconds=5), attempts=5)
        pipeline.sweep()
        take.refresh_from_db()
        self.assertEqual((take.status, take.error_code, take.charge_state),
                         ("lost", "save_failed", "released"))
        self.assertTrue(GenerationLog.objects.get(pk=take.genlog_id).needs_review)
        self.assertEqual(self.enqueued, [])

    def test_open_journal_rows_follow_closed_takes(self):
        failed = self.video_take(status="failed", genlog={"status": "submitted"})
        lost = self.video_take(status="lost", genlog={"status": "submitted", "needs_review": False})
        done = self.video_take(status="done", genlog={"status": "submitting"})
        video = f.make_asset(self.user, kind="video", source="generated_video")
        self.set(done, result_asset=video)
        running = self.video_take(status="running", genlog=True)
        self.set(running, next_poll_at=timezone.now() + timedelta(seconds=30))
        out = pipeline.sweep()
        self.assertEqual(out["journal_fixed"], 3)
        self.assertEqual(GenerationLog.objects.get(pk=failed.genlog_id).status, "failed")
        row = GenerationLog.objects.get(pk=lost.genlog_id)
        self.assertEqual(row.status, "lost")
        self.assertTrue(row.needs_review)
        row = GenerationLog.objects.get(pk=done.genlog_id)
        self.assertEqual((row.status, row.credits_charged, row.result_url), ("delivered", 150, video.url))
        self.assertEqual(GenerationLog.objects.get(pk=running.genlog_id).status, "submitted")

    def test_concurrent_sweep_is_skipped(self):
        cache.add(pipeline.SWEEP_LOCK_KEY, 1, 55)
        take = self.set(self.video_take(), created_at=self.ago(minutes=31))
        self.assertEqual(tasks.sweep_takes(), {"skipped": 1})
        self.assertEqual(Take.objects.get(pk=take.pk).status, "queued")

    def test_one_broken_rule_does_not_stop_the_others(self):
        take = self.set(self.video_take(), created_at=self.ago(minutes=31))
        with mock.patch("vstudio.pipeline._sweep_submitting", side_effect=RuntimeError("x")):
            out = pipeline.sweep()
        self.assertEqual(out["errors"], 1)
        self.assertEqual(Take.objects.get(pk=take.pk).status, "failed")

    def test_closed_takes_notify_the_owner(self):
        take = self.video_take(status="running")
        self.set(take, submitted_at=self.ago(hours=7), created_at=self.ago(hours=7))
        pipeline.sweep()
        self.push.assert_called_once()
        self.assertEqual(self.push.call_args.args[1], "Видео не получилось")


# ---------------------------------------------------------------- «Довезти», отмена

class RedeliverTests(PipelineCase):
    def lost(self, **kw):
        take = self.video_take(status="lost", genlog=True, error_code="save_failed",
                               error="Не удалось сохранить результат.", **kw)
        return self.set(take, created_at=self.ago(hours=1))

    def test_redeliver_is_free_and_enqueued_after_commit(self):
        take = self.lost()
        with self.captureOnCommitCallbacks(execute=True):
            self.assertIs(pipeline.admin_redeliver(take.pk), True)
        self.assertEqual(self.enqueued, [("finalize_take", take.pk, None, {"redeliver": True})])
        with self.provider(poll=ready(cost=0.5)):
            self.assertEqual(pipeline.finalize(take.pk, redeliver=True), "done")
        take.refresh_from_db()
        self.assertEqual((take.status, take.charge_state, take.credits_charged), ("done", "released", 0))
        self.assertEqual((take.error_code, take.error), ("", ""))
        self.assertIsNotNone(take.result_asset_id)
        row = GenerationLog.objects.get(pk=take.genlog_id)
        self.assertEqual((row.status, row.credits_charged, row.needs_review), ("recovered", 0, False))
        self.assertEqual(row.result_url, take.result_asset.url)
        self.assertEqual(self.ledger(), [])
        self.user.refresh_from_db()
        self.assertEqual(self.user.token_balance, 500)
        self.assertIn("бесплатно", self.push.call_args.args[2])
        self.assert_money_invariant()

    def test_task_passes_the_redeliver_flag(self):
        take = self.set(self.lost(), stage="redeliver", lease_until=timezone.now())
        with self.provider(poll=ready()):
            self.assertEqual(tasks.finalize_take(take.pk, redeliver=True), "done")
        self.assertEqual(Take.objects.get(pk=take.pk).charge_state, "released")

    def test_plain_finalize_never_touches_a_lost_take(self):
        take = self.lost()
        with self.provider(poll=ready()) as p:
            self.assertEqual(pipeline.finalize(take.pk), "skip")
        p.mocks["poll"].assert_not_called()

    def test_refusals(self):
        done = self.video_take(status="done")
        self.assertIs(pipeline.admin_redeliver(done.pk), False)
        self.assertIs(pipeline.admin_redeliver(10 ** 9), False)
        image, _ = self.image_take(status="lost")
        with self.assertRaisesMessage(ValueError, "Картинку довезти нельзя"):
            pipeline.admin_redeliver(image.pk)
        no_url = self.set(self.lost(), polling_url="", provider_id="")
        GenerationLog.objects.filter(pk=no_url.genlog_id).update(polling_url="")
        with self.assertRaisesMessage(ValueError, "адреса опроса нет"):
            pipeline.admin_redeliver(no_url.pk)
        busy = self.set(self.lost(), lease_until=timezone.now() + timedelta(minutes=3))
        with self.assertRaisesMessage(ValueError, "уже идёт"):
            pipeline.admin_redeliver(busy.pk)
        self.assertEqual(self.enqueued, [])

    def test_polling_url_is_recovered_from_the_journal(self):
        take = self.set(self.lost(), polling_url="", provider_id="")
        GenerationLog.objects.filter(pk=take.genlog_id).update(provider_id="gen-j", polling_url=POLL_URL)
        with self.captureOnCommitCallbacks(execute=True):
            self.assertTrue(pipeline.admin_redeliver(take.pk))
        take.refresh_from_db()
        self.assertEqual((take.polling_url, take.provider_id), (POLL_URL, "gen-j"))

    def test_failed_redelivery_leaves_it_lost_for_another_try(self):
        take = self.lost()
        with self.captureOnCommitCallbacks(execute=True):
            pipeline.admin_redeliver(take.pk)
        with self.provider(poll=mp.Poll(transient=True, error="http 500")):
            self.assertEqual(pipeline.finalize(take.pk, redeliver=True), "retry")
        take.refresh_from_db()
        self.assertEqual((take.status, take.stage, take.lease_until), ("lost", "redeliver_failed", None))
        self.assertEqual(self.ledger(), [])
        with self.captureOnCommitCallbacks(execute=True):
            self.assertTrue(pipeline.admin_redeliver(take.pk))

    def test_admin_action_with_the_real_pipeline(self):
        admin = f.make_user(is_staff=True, is_superuser=True)
        self.client.force_login(admin)
        take = self.lost()
        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.post(reverse("admin:vstudio_take_changelist"),
                                        {"action": "redeliver", "index": 0,
                                         "_selected_action": [take.pk]}, follow=True)
        msgs = [str(m) for m in get_messages(response.wsgi_request)]
        self.assertTrue(any("Довоз запущен: 1" in m for m in msgs), msgs)
        self.assertEqual(self.enqueued, [("finalize_take", take.pk, None, {"redeliver": True})])


class CancelTests(PipelineCase):
    def test_cancel_in_queue_releases(self):
        take, pending = self.image_take()
        self.assertTrue(pipeline.cancel(take.pk))
        take.refresh_from_db()
        pending.refresh_from_db()
        self.assertEqual((take.status, take.charge_state), ("canceled", "released"))
        self.assertEqual(pending.status, "failed")
        self.push.assert_not_called()

    def test_cancel_after_submit_is_refused(self):
        take = self.video_take()
        with self.provider(submit=accepted()):
            pipeline.submit(take.pk)
        self.assertFalse(pipeline.cancel(take.pk))
        self.assertEqual(Take.objects.get(pk=take.pk).status, "running")

    def test_enqueue_start_picks_the_task_by_kind(self):
        video = self.video_take()
        image, _ = self.image_take()
        pipeline.enqueue_start(video)
        pipeline.enqueue_start(image)
        self.assertEqual([e[:2] for e in self.enqueued],
                         [("submit_take", video.pk), ("run_image_take", image.pk)])


# ---------------------------------------------------------------- уведомления

class NotifyTests(PipelineCase):
    def closed(self, status, **kw):
        take = self.video_take(status=status, **kw)
        return self.set(take, created_at=self.ago(minutes=5))

    def test_done_sends_push_and_bell(self):
        take = self.closed("done")
        self.assertTrue(notify.notify_take_id(take.pk))
        title, body = self.push.call_args.args[1:3]
        self.assertEqual(title, "Видео готово")
        self.assertIn("Девушка идёт по крыше", body)
        self.assertEqual(self.push.call_args.kwargs["url"],
                         f"/video-studio/{take.project.uid}?take={take.uid}")
        note = Notification.objects.get()
        self.assertEqual((note.title, list(note.recipients.all())), ("Видео готово", [self.user]))

    def test_silent_while_the_page_is_open_or_right_after_start(self):
        take = self.closed("done")
        notify.mark_seen(self.user.pk)
        self.assertFalse(notify.notify_take_id(take.pk))
        cache.clear()
        young = self.video_take(status="done")
        self.assertFalse(notify.notify_take_id(young.pk))
        canceled = self.closed("canceled")
        self.assertFalse(notify.notify_take_id(canceled.pk))
        running = self.closed("running")
        self.assertFalse(notify.notify_take_id(running.pk))
        self.push.assert_not_called()

    def test_failure_texts_say_credits_are_safe(self):
        failed = self.closed("failed", error="Модель перегружена.")
        title, body = notify.texts(failed)
        self.assertEqual(title, "Видео не получилось")
        self.assertIn("Кредиты не списаны", body)
        lost = self.closed("lost")
        self.assertIn("мы проверим вручную", notify.texts(lost)[1])
        image, _ = self.image_take(status="done")
        self.assertEqual(notify.texts(image)[0], "Картинка готова")

    def test_task_is_queued_only_when_needed(self):
        young = self.video_take(status="done")
        pipeline.notify_later(young.pk)
        old = self.closed("failed")
        notify.mark_seen(self.user.pk)
        pipeline.notify_later(old.pk)
        self.assertEqual(self.notified, [])
        cache.clear()
        pipeline.notify_later(old.pk)
        self.assertEqual(self.notified, [old.pk])
        self.assertFalse(notify.wanted(10 ** 9))

    def test_push_failure_is_swallowed(self):
        take = self.closed("failed")
        self.push.side_effect = RuntimeError("vapid")
        self.assertTrue(notify.notify_take_id(take.pk))


# ---------------------------------------------------------------- ETA и очередь

class EtaAndQueueTests(PipelineCase):
    def finished(self, seconds, *, charge_state="charged", age=timedelta(hours=1)):
        take = self.video_take(status="done", charge_state=charge_state)
        end = timezone.now() - age
        return self.set(take, submitted_at=end - timedelta(seconds=seconds), finished_at=end)

    def test_median_of_recent_deliveries(self):
        for s in (60, 90, 120, 150, 600):
            self.finished(s)
        self.finished(9999, charge_state="released")      # бесплатный довоз не в счёт
        self.finished(9999, age=timedelta(days=8))         # старше недели
        self.assertEqual(pipeline.eta_seconds(f.VIDEO_MODEL_REF), 120)

    def test_too_few_samples_fall_back(self):
        for s in (60, 90, 120, 150):
            self.finished(s)
        self.assertEqual(pipeline.eta_seconds(f.VIDEO_MODEL_REF, default=222), 222)
        cache.clear()
        # Без default — ETA семейства из caps (Seedance 2.0 — 150 с).
        self.assertEqual(pipeline.eta_seconds(f.VIDEO_MODEL_REF), 150)
        self.assertEqual(pipeline.default_eta("unknown/model", "image"), 30)

    def test_eta_is_cached_for_ten_minutes(self):
        for s in (60, 60, 60, 60, 60):
            self.finished(s)
        self.assertEqual(pipeline.eta_seconds(f.VIDEO_MODEL_REF), 60)
        for s in (900, 900, 900, 900, 900, 900):
            self.finished(s)
        self.assertEqual(pipeline.eta_seconds(f.VIDEO_MODEL_REF), 60)
        cache.clear()
        self.assertEqual(pipeline.eta_seconds(f.VIDEO_MODEL_REF), 900)

    def test_queue_position(self):
        a, b, c = self.video_take(), self.video_take(), self.video_take()
        now = timezone.now()
        self.set(a, created_at=now - timedelta(seconds=30))
        self.set(b, created_at=now - timedelta(seconds=20))
        self.set(c, created_at=now - timedelta(seconds=10))
        running = self.video_take(status="running")
        self.assertEqual([pipeline.queue_position(t) for t in (a, b, c)], [0, 1, 2])
        self.assertIsNone(pipeline.queue_position(running))
        self.assertEqual(pipeline.queue_positions([c, a, running]), {a.uid: 0, c.uid: 2})


# ---------------------------------------------------------------- чистка материалов

class PurgeTests(PipelineCase):
    def gone(self, days, **kw):
        asset = f.make_asset(self.user, store=True, **kw)
        return Asset.objects.filter(pk=asset.pk).update(deleted_at=self.ago(days=days)) and asset

    def test_old_unreferenced_assets_are_purged_with_files(self):
        old = self.gone(31)
        recent = self.gone(5)
        used_by_shot = self.gone(40)
        f.make_shot(self.user, inputs=[used_by_shot])
        result = self.gone(40)
        take = self.video_take(status="done")
        self.set(take, result_asset=result)
        alive = f.make_asset(self.user, store=True)
        out = tasks.purge_assets()
        self.assertEqual(out, {"purged": 1, "kept": 0})
        self.assertFalse(Asset.objects.filter(pk=old.pk).exists())
        self.assertFalse(os.path.exists(os.path.join(self.media, old.file)))
        for keep in (recent, used_by_shot, result, alive):
            self.assertTrue(Asset.objects.filter(pk=keep.pk).exists())
            self.assertTrue(os.path.exists(os.path.join(self.media, keep.file)))

    @override_settings(VSTUDIO_PURGE_DAYS=3)
    def test_days_come_from_settings(self):
        asset = self.gone(4)
        pipeline.purge_assets()
        self.assertFalse(Asset.objects.filter(pk=asset.pk).exists())


# ---------------------------------------------------------------- соседи

class NeighboursTests(PipelineCase):
    def test_chat_recovery_does_not_touch_studio_rows(self):
        from ai import recovery

        take = self.video_take(status="running", genlog=True)
        GenerationLog.objects.filter(pk=take.genlog_id).update(updated_at=self.ago(minutes=10))
        with mock.patch("ai.recovery.deliver") as deliver:
            recovery.recover_open_videos()
        deliver.assert_not_called()
        self.assertEqual(GenerationLog.objects.get(pk=take.genlog_id).status, "submitted")

    def test_studio_journal_rows_do_not_hold_the_chat_reserve(self):
        from ai.generation import reserved_video_credits

        self.video_take(status="running", genlog=True)
        self.assertEqual(reserved_video_credits(self.user), 0)

    def test_constraint_catches_a_forgotten_release(self):
        take = self.video_take(status="running")
        with self.assertRaises(IntegrityError), transaction.atomic():
            Take.objects.filter(pk=take.pk).update(status="failed")

    def test_every_pipeline_outcome_keeps_the_money_rule(self):
        # Прогон всех исходов подряд на одном пользователе и сверка правила.
        outcomes = [
            (mp.Submit(state=mp.STATE_ACCEPTED, job_id="a", polling_url=POLL_URL), "running"),
            (mp.Submit(state=mp.STATE_REJECTED, status_code=422, text="duration"), "failed"),
            (mp.Submit(state=mp.STATE_UNKNOWN, text="timeout"), "lost"),
        ]
        for res, expected in outcomes:
            take = self.video_take()
            with self.provider(submit=res):
                self.assertEqual(pipeline.submit(take.pk), expected)
            self.assert_money_invariant()

    def test_task_names_match_the_routes(self):
        names = {t.name for t in (tasks.submit_take, tasks.poll_take, tasks.finalize_take,
                                  tasks.run_image_take, tasks.notify_take, tasks.sweep_takes,
                                  tasks.purge_assets)}
        self.assertEqual(names, {f"vstudio.tasks.{n}" for n in (
            "submit_take", "poll_take", "finalize_take", "run_image_take", "notify_take",
            "sweep_takes", "purge_assets")})
        self.assertEqual((tasks.notify_take.soft_time_limit, tasks.notify_take.time_limit), (30, 40))
        self.assertEqual((tasks.submit_take.soft_time_limit, tasks.submit_take.time_limit), (200, 230))
        self.assertEqual((tasks.poll_take.soft_time_limit, tasks.poll_take.time_limit), (45, 60))
        self.assertEqual((tasks.finalize_take.soft_time_limit, tasks.finalize_take.time_limit), (280, 300))
        self.assertEqual((tasks.run_image_take.soft_time_limit, tasks.run_image_take.time_limit),
                         (220, 250))
        self.assertEqual((tasks.sweep_takes.soft_time_limit, tasks.sweep_takes.time_limit), (50, 60))
