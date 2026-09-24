"""Гонки вокруг денег в конвейере студии (§2.2, §6.7, §13 «Конвейер»).

Каждый сценарий — «две стороны хотят одного и того же дубля»: вторая копия
задачи, sweep, отмена, «Довезти». Порядок разыгрывается детерминированно:
вторая сторона запускается ИЗНУТРИ подменённого сетевого вызова первой —
ровно в тот момент, когда в жизни и бывает окно. На Postgres дополнительно
проверяется настоящая параллельная выдача двумя потоками.

Итог всегда сверяется по деньгам: одна строка леджера на выданный результат
(или ни одной), charge_state, журнал и файлы на диске.
"""
import base64
import threading
from unittest import mock, skipUnless

from django.db import connection
from django.test import TransactionTestCase
from django.utils import timezone

from ai import media_provider as mp
from ai.models import GenerationLog
from plans.models import TokenTransaction
from vstudio import delivery, pipeline
from vstudio.models import Asset, Take
from vstudio.tests import factories as f
from vstudio.tests.test_pipeline import MP4, PipelineCase, accepted, ready, write_mp4


class RaceCase(PipelineCase):
    def saving(self, **kw):
        take = self.video_take(status="saving", genlog=True, **kw)
        return self.set(take, lease_until=timezone.now(), submitted_at=self.ago(minutes=2),
                        created_at=self.ago(minutes=3))

    def running(self, **kw):
        take = self.video_take(status="running", genlog=True, **kw)
        return self.set(take, submitted_at=self.ago(minutes=1), next_poll_at=self.ago(seconds=1))

    def video_assets(self):
        return list(Asset.objects.filter(kind=Asset.KIND_VIDEO))

    def drain(self, *, limit=20):
        """Выполнить поставленные задачи по очереди, как воркер (countdown — «уже прошёл»)."""
        runners = {"submit_take": pipeline.submit, "poll_take": pipeline.poll,
                   "finalize_take": pipeline.finalize, "run_image_take": pipeline.run_image}
        results = []
        for _ in range(limit):
            if not self.enqueued:
                break
            name, take_id, _countdown, kwargs = self.enqueued.pop(0)
            if name == "poll_take":
                Take.objects.filter(pk=take_id).update(next_poll_at=self.ago(seconds=1))
            results.append((name, runners[name](take_id, **kwargs)))
        return results


# ---------------------------------------------------------------- выдача

class FinalizeRaceTests(RaceCase):
    def test_sweep_closes_the_take_while_finalize_downloads(self):
        take = self.saving()
        self.set(take, attempts=4)

        def stuck_download(url, dest, **kw):
            write_mp4(url, dest, **kw)
            # Воркер «завис» дольше аренды: sweep видит 5 попыток и закрывает дубль.
            Take.objects.filter(pk=take.pk).update(lease_until=self.ago(seconds=1))
            out = pipeline.sweep()
            self.assertEqual(out.get("save_failed"), 1)
            return len(MP4)

        with self.provider(poll=ready(), download=stuck_download):
            self.assertEqual(pipeline.finalize(take.pk), "raced")
        take.refresh_from_db()
        self.assertEqual((take.status, take.error_code, take.charge_state, take.credits_charged),
                         ("lost", "save_failed", "released", 0))
        self.assertEqual(self.video_assets(), [])
        self.assertEqual(self.studio_files(), [])           # проигравший стёр свои файлы
        self.assertEqual(self.ledger(), [])
        row = GenerationLog.objects.get(pk=take.genlog_id)
        self.assertEqual(row.status, "lost")
        self.assertTrue(row.needs_review)
        self.assert_money_invariant()

    def test_two_finalizers_charge_once_and_the_loser_cleans_up(self):
        take = self.saving()
        state = {"inner": None}

        def download(url, dest, **kw):
            write_mp4(url, dest, **kw)
            if state["inner"] is None:
                state["inner"] = "running"
                # Аренда первой копии истекла — sweep завёл вторую, и та успела всё.
                Take.objects.filter(pk=take.pk).update(lease_until=self.ago(seconds=1))
                state["inner"] = pipeline.finalize(take.pk)
            return len(MP4)

        with self.provider(poll=ready(), download=download):
            self.assertEqual(pipeline.finalize(take.pk), "raced")
        self.assertEqual(state["inner"], "done")
        take.refresh_from_db()
        self.assertEqual((take.status, take.charge_state, take.credits_charged, take.attempts),
                         ("done", "charged", 150, 2))
        assets = self.video_assets()
        self.assertEqual([a.pk for a in assets], [take.result_asset_id])
        winner = assets[0]
        self.assertEqual(len(self.studio_files()), 2)       # mp4 и постер победителя
        self.assertTrue(all(winner.uid in path for path in self.studio_files()))
        self.assertEqual([(t.delta, t.reason) for t in self.ledger()], [(-150, "vstudio_video")])
        self.user.refresh_from_db()
        self.assertEqual(self.user.token_balance, 350)
        self.assert_money_invariant()

    def test_finalize_twice_in_a_row(self):
        take = self.saving()
        with self.provider(poll=ready()):
            self.assertEqual(pipeline.finalize(take.pk), "done")
            self.set(take, lease_until=None)  # даже без аренды статус уже не saving
            self.assertEqual(pipeline.finalize(take.pk), "skip")
        self.assertEqual(len(self.ledger()), 1)
        self.assertEqual(len(self.video_assets()), 1)

    def test_crash_then_sweep_retry_charges_once(self):
        take = self.saving()
        with self.provider(poll=ready()), \
                mock.patch("vstudio.delivery.charge_on_delivery",
                           side_effect=RuntimeError("db blinked")):
            self.assertEqual(pipeline.finalize(take.pk), "retry")
        self.assertEqual(self.ledger(), [])
        self.set(take, lease_until=self.ago(seconds=1))
        pipeline.sweep()
        self.assertEqual([e[:2] for e in self.enqueued], [("finalize_take", take.pk)])
        with self.provider(poll=ready()):
            self.assertEqual(self.drain(), [("finalize_take", "done")])
        take.refresh_from_db()
        self.assertEqual((take.status, take.attempts, take.credits_charged), ("done", 2, 150))
        self.assertEqual(len(self.ledger()), 1)
        self.assertEqual(len(self.video_assets()), 1)
        self.assertEqual(len(self.studio_files()), 2)
        self.assert_money_invariant()

    def test_chat_spends_in_the_window_and_charge_becomes_partial(self):
        take = self.saving()

        def download(url, dest, **kw):
            write_mp4(url, dest, **kw)
            # Чат проверяет баланс без замка и успел списать своё посреди выдачи.
            type(self.user).objects.filter(pk=self.user.pk).update(token_balance=40)
            return len(MP4)

        with self.provider(poll=ready(), download=download):
            self.assertEqual(pipeline.finalize(take.pk), "done")
        take.refresh_from_db()
        self.assertEqual((take.status, take.charge_state, take.credits_charged), ("done", "charged", 40))
        self.assertTrue(GenerationLog.objects.get(pk=take.genlog_id).needs_review)
        self.assertEqual([t.delta for t in self.ledger()], [-40])
        self.assert_money_invariant()


# ---------------------------------------------------------------- отправка и опрос

class SubmitPollRaceTests(RaceCase):
    def test_second_submit_inside_the_first_sends_nothing(self):
        take = self.video_take()
        inner = {}

        def slow_submit(body, **kw):
            inner["result"] = pipeline.submit(take.pk)   # вторая копия задачи
            return accepted()

        with self.provider(submit=slow_submit) as p:
            self.assertEqual(pipeline.submit(take.pk), "running")
        self.assertEqual(inner["result"], "skip")
        self.assertEqual(p.mocks["submit"].call_count, 1)
        self.assertEqual(GenerationLog.objects.filter(source="vstudio").count(), 1)

    def test_cancel_before_submit_wins(self):
        take = self.video_take()
        self.assertTrue(pipeline.cancel(take.pk))
        with self.provider(submit=accepted()) as p:
            self.assertEqual(pipeline.submit(take.pk), "skip")
        p.mocks["submit"].assert_not_called()
        take.refresh_from_db()
        self.assertEqual((take.status, take.charge_state), ("canceled", "released"))
        self.assertEqual(GenerationLog.objects.count(), 0)

    def test_cancel_during_submit_loses(self):
        take = self.video_take()
        inner = {}

        def submit(body, **kw):
            inner["cancel"] = pipeline.cancel(take.pk)
            return accepted()

        with self.provider(submit=submit):
            self.assertEqual(pipeline.submit(take.pk), "running")
        self.assertIs(inner["cancel"], False)
        self.assert_money_invariant()

    def test_queue_timeout_then_late_worker(self):
        take = self.set(self.video_take(), created_at=self.ago(minutes=40))
        pipeline.sweep()
        with self.provider(submit=accepted()) as p:
            self.assertEqual(pipeline.submit(take.pk), "skip")
        p.mocks["submit"].assert_not_called()
        self.assertEqual(Take.objects.get(pk=take.pk).status, "failed")

    def test_second_poll_inside_the_first_dies(self):
        take = self.running()
        inner = {}

        def get(url, **kw):
            if "result" not in inner:
                inner["result"] = "…"
                # Копия цепочки (sweep после рестарта) пришла, когда наш захват
                # уже истёк, и захватила строку себе.
                Take.objects.filter(pk=take.pk).update(next_poll_at=self.ago(seconds=1))
                inner["result"] = pipeline.poll(take.pk)
            return mp.Poll(status="in_progress")

        with self.provider(poll=get) as p:
            self.assertEqual(pipeline.poll(take.pk), "skip")
        # Вторая копия продолжила цепочку, первая после GET увидела чужой захват
        # и погасла: цепочка одна, а не две.
        self.assertEqual(inner["result"], "polling")
        self.assertEqual(p.mocks["poll"].call_count, 2)
        self.assertEqual([e[0] for e in self.enqueued], ["poll_take"])
        take.refresh_from_db()
        self.assertEqual(take.poll_count, 1)

    def test_give_up_while_the_last_poll_is_in_flight(self):
        take = self.running()
        self.set(take, submitted_at=self.ago(hours=6, minutes=5))

        def get(url, **kw):
            pipeline.sweep()      # шесть часов вышли, пока шёл GET
            return ready()

        with self.provider(poll=get):
            self.assertEqual(pipeline.poll(take.pk), "skip")
        take.refresh_from_db()
        self.assertEqual((take.status, take.error_code, take.charge_state),
                         ("lost", "provider_timeout", "released"))
        self.assertNotIn("finalize_take", [e[0] for e in self.enqueued])
        self.assertEqual(self.ledger(), [])

    def test_lost_poll_chain_after_worker_restart_is_delivered(self):
        take = self.video_take(status="running", genlog=True)
        self.set(take, submitted_at=self.ago(minutes=5), next_poll_at=self.ago(minutes=3))
        pipeline.sweep()
        self.assertEqual([e[:2] for e in self.enqueued], [("poll_take", take.pk)])
        with self.provider(poll=ready()):
            self.assertEqual(self.drain(), [("poll_take", "saving"), ("finalize_take", "done")])
        take.refresh_from_db()
        self.assertEqual((take.status, take.credits_charged), ("done", 150))
        self.assertEqual(len(self.ledger()), 1)

    def test_whole_path_through_the_queue(self):
        take = self.video_take()
        polls = [mp.Poll(status="queued"), mp.Poll(transient=True, error="http 502"),
                 mp.Poll(status="in_progress"), ready(cost=0.61), ready(cost=0.61)]
        with self.provider(submit=accepted(), poll=polls):
            pipeline.enqueue_start(take)
            results = self.drain()
        self.assertEqual([r for _, r in results],
                         ["running", "polling", "polling", "polling", "saving", "done"])
        take.refresh_from_db()
        self.assertEqual((take.status, take.charge_state, take.credits_charged, take.poll_count),
                         ("done", "charged", 150, 3))
        self.assertEqual(take.provider_cost_usd, delivery.money(0.61))
        row = GenerationLog.objects.get(pk=take.genlog_id)
        self.assertEqual((row.status, row.result_url), ("delivered", take.result_asset.url))
        self.assertEqual([(t.delta, t.reason) for t in self.ledger()], [(-150, "vstudio_video")])
        self.assert_money_invariant()


# ---------------------------------------------------------------- картинка и довоз

class ImageAndRedeliverRaceTests(RaceCase):
    def test_sweep_times_out_the_image_while_it_generates(self):
        take, pending = self.image_take()

        def slow(body, **kw):
            Take.objects.filter(pk=take.pk).update(submitted_at=self.ago(minutes=9))
            pipeline.sweep()
            return mp.Images(items=[mp.ImageItem(b64=base64.b64encode(f.image_bytes(640, 480)).decode(),
                                                 media_type="image/jpeg")], status_code=200)

        with self.provider(image=slow):
            self.assertEqual(pipeline.run_image(take.pk), "raced")
        take.refresh_from_db()
        pending.refresh_from_db()
        self.assertEqual((take.status, take.charge_state), ("lost", "released"))
        self.assertEqual((pending.status, pending.file), ("failed", ""))
        self.assertEqual(self.studio_files(), [])
        self.assertEqual(self.ledger(), [])
        self.assert_money_invariant()

    def test_double_click_on_redeliver_delivers_once_for_free(self):
        take = self.video_take(status="lost", genlog=True, error_code="provider_timeout")
        with self.captureOnCommitCallbacks(execute=True):
            self.assertTrue(pipeline.admin_redeliver(take.pk))
        with self.captureOnCommitCallbacks(execute=True):
            self.assertTrue(pipeline.admin_redeliver(take.pk))  # ещё никто не взял аренду
        self.assertEqual(len(self.enqueued), 2)
        inner = {}

        def download(url, dest, **kw):
            write_mp4(url, dest, **kw)
            if "second" not in inner:
                inner["second"] = pipeline.finalize(take.pk, redeliver=True)
            return len(MP4)

        with self.provider(poll=ready(), download=download):
            self.assertEqual(pipeline.finalize(take.pk, redeliver=True), "done")
        self.assertEqual(inner["second"], "skip")
        take.refresh_from_db()
        self.assertEqual((take.status, take.charge_state, take.credits_charged), ("done", "released", 0))
        self.assertEqual(len(self.video_assets()), 1)
        self.assertEqual(self.ledger(), [])
        self.assert_money_invariant()

    def test_redeliver_cannot_resurrect_a_delivered_take(self):
        take = self.saving()
        with self.provider(poll=ready()):
            pipeline.finalize(take.pk)
        self.assertIs(pipeline.admin_redeliver(take.pk), False)
        with self.provider(poll=ready()) as p:
            self.assertEqual(pipeline.finalize(take.pk, redeliver=True), "skip")
        p.mocks["poll"].assert_not_called()
        self.assertEqual(len(self.ledger()), 1)


# ---------------------------------------------------------------- Postgres: два потока

@skipUnless(connection.vendor == "postgresql", "параллельная выдача проверяется только на Postgres")
class ParallelDeliveryTests(TransactionTestCase):
    """Две выдачи одного дубля одновременно: условный UPDATE пропускает одну."""

    def test_two_threads_commit_the_same_take(self):
        user = f.make_user(balance=500)
        take = f.make_take(f.make_shot(user), status="saving", credits=150, genlog=True)
        take = Take.objects.select_related("user").get(pk=take.pk)
        barrier = threading.Barrier(2)
        results, errors = [], []

        def worker(n):
            try:
                me = Take.objects.select_related("user").get(pk=take.pk)
                saved = delivery.SavedVideo(asset_uid=f"{n:032x}", file=f"vstudio/{user.pk}/{n}.mp4",
                                            thumb="", bytes=10, width=None, height=None,
                                            duration_s=None)
                barrier.wait(timeout=10)
                results.append(delivery.commit_video(me, saved).won)
            except Exception as exc:  # noqa: BLE001 — показать в тесте
                errors.append(exc)
            finally:
                connection.close()

        threads = [threading.Thread(target=worker, args=(n,)) for n in (1, 2)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=30)
        self.assertEqual(errors, [])
        self.assertEqual(sorted(results), [False, True])
        take.refresh_from_db()
        self.assertEqual((take.status, take.charge_state, take.credits_charged), ("done", "charged", 150))
        self.assertEqual(TokenTransaction.objects.filter(user=user).count(), 1)
        self.assertEqual(Asset.objects.filter(kind=Asset.KIND_VIDEO).count(), 1)
