"""Задача склейки и уборка: списание только за готовый ролик, сбой снимает резерв."""
from __future__ import annotations

import os
from datetime import timedelta
from unittest.mock import patch

from celery.exceptions import SoftTimeLimitExceeded
from celery.schedules import crontab
from django.conf import settings
from django.core.files.storage import default_storage
from django.test import SimpleTestCase
from django.utils import timezone

from merge import render, services, tasks
from merge.models import MergeProject
from plans.models import TokenTransaction

from .helpers import MediaTestCase, store


def _fake_render(duration=10.0, fail=None):
    def run(paths, *, aspect, fit, workdir, progress=None, deadline=None):
        if fail is not None:
            raise fail
        if progress:
            progress("normalizing", 0, len(paths))
            progress("joining", len(paths), len(paths))
        out = os.path.join(workdir, "merged.mp4")
        with open(out, "wb") as fh:
            fh.write(b"MERGED")
        return render.Rendered(path=out, duration=duration)

    return run


def _fake_poster(src, dst, duration=None):
    with open(dst, "wb") as fh:
        fh.write(b"JPG")
    return True


class RenderTaskTests(MediaTestCase):
    def setUp(self):
        super().setUp()
        self.owner = self.user(balance=100)
        self.take_ = self.take(self.owner)
        self.scene_ = self.scene(self.owner)

    def queued(self, user=None, reserve=20, **kw):
        user = user or self.owner
        sources = [self.take_, self.scene_] if user == self.owner else [self.take(user), self.scene(user)]
        return self.project(user, sources, status="queued", credits_reserved=reserve,
                            queued_at=timezone.now(), **kw)

    def run_task(self, project, **fake):
        with patch("merge.services.ffmpeg.render", side_effect=_fake_render(**fake)) as rendered, \
                patch("merge.services.ffmpeg.make_poster", side_effect=_fake_poster):
            result = tasks.render_merge.run(project.pk)
        project.refresh_from_db()
        return result, rendered

    def test_success_charges_once_and_keeps_30_days(self):
        project = self.queued(error="старое", error_code="stale")
        result, rendered = self.run_task(project)
        self.assertEqual(result, {"status": "ready", "charged": 20})
        self.assertEqual(project.status, "ready")
        self.assertEqual((project.error, project.error_code), ("", ""))
        self.assertEqual((project.credits_reserved, project.credits_charged), (0, 20))
        self.assertEqual(project.duration_s, 10.0)
        self.assertAlmostEqual((project.expires_at - project.finished_at).days, 30)
        self.assertTrue(project.result_video.startswith(f"merge/{self.owner.pk}/{project.uid}-"))
        self.assertTrue(project.result_video.endswith(".mp4"))
        self.assertTrue(project.poster.endswith(".jpg"))
        with default_storage.open(project.result_video, "rb") as fh:
            self.assertEqual(fh.read(), b"MERGED")
        self.assertEqual(self.balance(self.owner), 80)
        row = TokenTransaction.objects.get(user=self.owner)
        self.assertEqual((row.delta, row.reason), (-20, "merge_video"))
        self.assertEqual(row.meta["merge"], project.uid)
        # Источники ушли в ffmpeg файлами с диска — по порядку фрагментов.
        paths = rendered.call_args.args[0]
        self.assertTrue(paths[0].replace("\\", "/").endswith(self.take_.result_asset.file))
        self.assertTrue(paths[1].replace("\\", "/").endswith(self.scene_.video))
        self.assertEqual(rendered.call_args.kwargs["aspect"], project.aspect)

    def test_second_copy_of_the_task_does_nothing(self):
        project = self.queued()
        self.run_task(project)
        again, rendered = self.run_task(project)
        self.assertEqual(again, {"status": "not_queued"})
        rendered.assert_not_called()
        self.assertEqual(TokenTransaction.objects.filter(user=self.owner).count(), 1)

    def test_ffmpeg_failure_releases_reserve(self):
        project = self.queued()
        result, _ = self.run_task(project, fail=render.RenderError(
            "Фрагмент №2 не читается — уберите его из склейки и попробуйте снова.", "rc=1",
            code="fragment_unreadable", fragment=2))
        self.assertEqual(result, {"status": "failed"})
        self.assertEqual(project.status, "failed")
        self.assertEqual((project.error_code, project.error_fragment), ("fragment_unreadable", 2))
        self.assertEqual(project.credits_reserved, 0)
        self.assertEqual(project.error,
                         "Фрагмент №2 не читается — уберите его из склейки и попробуйте снова.")
        self.assertEqual(self.balance(self.owner), 100)
        self.assertFalse(TokenTransaction.objects.exists())

    def test_soft_time_limit_releases_reserve(self):
        project = self.queued()
        result, _ = self.run_task(project, fail=SoftTimeLimitExceeded())
        self.assertEqual(result, {"status": "timeout"})
        self.assertEqual((project.status, project.credits_reserved), ("failed", 0))
        self.assertEqual(project.error_code, "too_slow")
        self.assertEqual(project.error,
                         "Склейка заняла слишком долго — кредиты не списаны, попробуйте ещё раз.")
        self.assertEqual(self.balance(self.owner), 100)

    def test_unexpected_crash_releases_reserve(self):
        project = self.queued()
        result, _ = self.run_task(project, fail=RuntimeError("disk"))
        self.assertEqual(result, {"status": "failed"})
        self.assertEqual(project.error,
                         "Не получилось склеить видео — кредиты не списаны, попробуйте ещё раз.")
        self.assertEqual(project.error_code, "failed")
        self.assertEqual(project.credits_reserved, 0)

    def test_source_deleted_while_queued(self):
        project = self.queued()
        default_storage.delete(self.scene_.video)
        result, rendered = self.run_task(project)
        self.assertEqual(result, {"status": "failed"})
        rendered.assert_not_called()
        self.assertEqual(project.error, "Фрагмент №2 пропал, пока склейка ждала очереди. "
                                        "Уберите его — кредиты не списаны.")
        self.assertEqual((project.error_code, project.error_fragment), ("source_gone", 2))
        self.assertEqual(project.credits_reserved, 0)

    def test_result_longer_than_limit_is_not_charged(self):
        project = self.queued()
        result, _ = self.run_task(project, duration=320.0)
        self.assertEqual(result, {"status": "failed"})
        self.assertEqual(self.balance(self.owner), 100)
        self.assertFalse(os.listdir(os.path.join(self._media, "merge", str(self.owner.pk))))

    def test_project_closed_by_sweep_during_render_is_not_charged(self):
        project = self.queued()

        def sweep_mid_render(paths, **kw):
            MergeProject.objects.filter(pk=project.pk).update(
                status="failed", credits_reserved=0, error="оборвалась")
            return _fake_render()(paths, **kw)

        with patch("merge.services.ffmpeg.render", side_effect=sweep_mid_render), \
                patch("merge.services.ffmpeg.make_poster", side_effect=_fake_poster):
            result = tasks.render_merge.run(project.pk)
        self.assertEqual(result, {"status": "gone"})
        self.assertEqual(self.balance(self.owner), 100)
        # Файлы проигравшей выдачи стёрты.
        self.assertEqual(os.listdir(os.path.join(self._media, "merge", str(self.owner.pk))), [])

    def test_partial_charge_when_balance_was_spent_meanwhile(self):
        project = self.queued()
        type(self.owner).objects.filter(pk=self.owner.pk).update(token_balance=7)
        result, _ = self.run_task(project)
        self.assertEqual(result, {"status": "ready", "charged": 7})
        self.assertEqual((project.status, project.credits_charged), ("ready", 7))
        self.assertEqual(self.balance(self.owner), 0)
        self.assertTrue(TokenTransaction.objects.get(user=self.owner).meta["partial"])

    def test_free_merge_charges_nothing(self):
        project = self.queued(reserve=0)
        result, _ = self.run_task(project)
        self.assertEqual(result, {"status": "ready", "charged": 0})
        self.assertFalse(TokenTransaction.objects.exists())

    def test_progress_is_written(self):
        project = self.queued()
        seen = []

        def spy(paths, *, progress=None, **kw):
            progress("normalizing", 1, 2)
            seen.append(MergeProject.objects.values_list(
                "status", "progress_stage", "progress_done", "progress_total").get(pk=project.pk))
            return _fake_render()(paths, progress=None, **kw)

        with patch("merge.services.ffmpeg.render", side_effect=spy), \
                patch("merge.services.ffmpeg.make_poster", side_effect=_fake_poster):
            tasks.render_merge.run(project.pk)
        self.assertEqual(seen, [("rendering", "normalizing", 1, 2)])


class SweepTests(MediaTestCase):
    def setUp(self):
        super().setUp()
        self.owner = self.user(balance=100)
        self.now = timezone.now()

    def test_lost_queue_and_dead_render_are_closed(self):
        lost = self.project(self.owner, status="queued", credits_reserved=20,
                            queued_at=self.now - timedelta(hours=3))
        other = self.user()
        dead = self.project(other, status="rendering", credits_reserved=20,
                            render_started_at=self.now - timedelta(minutes=40))
        self.assertEqual(tasks.fail_stale_renders.run(), {"queued": 1, "rendering": 1, "audio": 0})
        for row, text, code in (
                (lost, "Склейка не дождалась очереди — кредиты не списаны, попробуйте ещё раз.",
                 "queue_timeout"),
                (dead, "Склейка оборвалась — кредиты не списаны, попробуйте ещё раз.", "stale")):
            row.refresh_from_db()
            self.assertEqual((row.status, row.credits_reserved, row.error, row.error_code),
                             ("failed", 0, text, code))

    def test_live_work_is_left_alone(self):
        waiting = self.project(self.owner, status="queued", credits_reserved=20,
                               queued_at=self.now - timedelta(minutes=30))
        other = self.user()
        working = self.project(other, status="rendering", credits_reserved=20,
                               render_started_at=self.now - timedelta(minutes=10))
        self.assertEqual(tasks.fail_stale_renders.run(), {"queued": 0, "rendering": 0, "audio": 0})
        waiting.refresh_from_db()
        working.refresh_from_db()
        self.assertEqual((waiting.status, working.status), ("queued", "rendering"))

    def test_late_task_after_sweep_does_not_run(self):
        project = self.project(self.owner, status="queued", credits_reserved=20,
                               queued_at=self.now - timedelta(hours=3))
        tasks.fail_stale_renders.run()
        with patch("merge.services.ffmpeg.render") as rendered:
            self.assertEqual(tasks.render_merge.run(project.pk), {"status": "not_queued"})
        rendered.assert_not_called()


class ExpiryTests(MediaTestCase):
    def test_expired_results_are_deleted(self):
        owner = self.user()
        video, poster = store("merge/1/old.mp4"), store("merge/1/old.jpg")
        old = self.project(owner, status="ready", result_video=video, poster=poster,
                           expires_at=timezone.now() - timedelta(minutes=1))
        fresh_video = store("merge/1/new.mp4")
        fresh = self.project(owner, status="ready", result_video=fresh_video,
                             expires_at=timezone.now() + timedelta(days=1))
        self.assertEqual(tasks.purge_expired.run(), {"merges": 1, "uploads": 0, "audio": 0})
        old.refresh_from_db()
        fresh.refresh_from_db()
        self.assertEqual((old.status, old.result_video, old.poster), ("expired", "", ""))
        self.assertFalse(default_storage.exists(video))
        self.assertFalse(default_storage.exists(poster))
        self.assertEqual(fresh.status, "ready")
        self.assertTrue(default_storage.exists(fresh_video))

    def test_expired_can_be_merged_again(self):
        owner = self.user()
        project = self.project(owner, [self.take(owner), self.scene(owner)], status="expired")
        with patch("merge.services.storage_ready", return_value=(True, "")):
            started, fresh = services.start_render(owner, project.uid)
        self.assertTrue(fresh)
        self.assertEqual(started.status, "queued")


class WiringTests(SimpleTestCase):
    def test_render_goes_to_media_queue(self):
        from core.celery import app

        queue = app.amqp.router.route({}, "merge.tasks.render_merge")["queue"].name
        self.assertEqual(queue, settings.CELERY_MEDIA_QUEUE or "celery")
        self.assertEqual(app.amqp.router.route({}, "merge.tasks.purge_expired")["queue"].name,
                         "celery")

    def test_beat_entries(self):
        schedule = settings.CELERY_BEAT_SCHEDULE
        self.assertEqual(schedule["merge:fail_stale_renders"]["task"], "merge.tasks.fail_stale_renders")
        self.assertEqual(schedule["merge:fail_stale_renders"]["schedule"], timedelta(minutes=5))
        purge = schedule["merge:purge_expired"]
        self.assertEqual(purge["task"], "merge.tasks.purge_expired")
        self.assertIsInstance(purge["schedule"], crontab)

    def test_task_limits(self):
        self.assertEqual(tasks.render_merge.soft_time_limit, services.RENDER_SOFT_LIMIT)
        self.assertEqual(tasks.render_merge.time_limit, services.RENDER_HARD_LIMIT)
        self.assertGreater(services.STALE_RENDER_AFTER.total_seconds(), services.RENDER_HARD_LIMIT)

    def test_media_worker_waits_for_the_longest_merge(self):
        # Выкладка пересоздаёт celery_media: docker ждёт stop_grace_period и
        # убивает воркер. Меньше лимита склейки — идущая склейка обрывается.
        import re
        from pathlib import Path

        compose = Path(settings.BASE_DIR).parent / "compose.yaml"
        if not compose.exists():
            self.skipTest("нет compose.yaml (копия без корня репозитория)")
        text = compose.read_text(encoding="utf-8")
        block = text[text.index("\n  celery_media:"):]
        block = block[:block.index("\n  # ", 1)] if "\n  # " in block[1:] else block
        found = re.search(r"\n    stop_grace_period: (\d+)(m|s)\b", block)
        self.assertIsNotNone(found, "у celery_media нет stop_grace_period")
        grace = int(found.group(1)) * (60 if found.group(2) == "m" else 1)
        self.assertGreaterEqual(grace, services.RENDER_HARD_LIMIT + 180)

    def test_runtime_key_registered(self):
        from adminapi.runtime import KEYS

        self.assertIn("merge_price_credits", KEYS)
