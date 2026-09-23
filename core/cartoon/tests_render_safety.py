# -*- coding: utf-8 -*-
"""Съёмка без потерь: резерв баланса, удаление во время съёмки, зависшие сцены,
склейка, сведение без самоожидания, озвучка без двойного списания.

Каждый тест — случай, где раньше терялись деньги (наши или человека) или сцена
навсегда оставалась «в работе». Модели и ffmpeg подменены: проверяем деньги,
состояния и замки.
"""
from datetime import timedelta
from decimal import Decimal
from unittest.mock import MagicMock, patch

from celery.exceptions import SoftTimeLimitExceeded
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from ai.models import GenerationLog, GPTModels
from cartoon import audio, voiceover
from cartoon.models import (CartoonCharacter, CartoonKeyframe, CartoonPreset, CartoonProject,
                            CartoonScene)
from plans.models import TokenTransaction

CACHES = {"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache",
                      "LOCATION": "studio-render-safety-tests"}}

# Кадр — 4 кр, видео — 5 с × 3 = 15 кр.
FRAME = 4
VIDEO = 15
FULL = FRAME + VIDEO


def _user(balance: int, email: str = "r@example.com"):
    user = get_user_model().objects.create_user(email=email, password="x-12345678")
    user.token_balance = balance
    user.save(update_fields=["token_balance"])
    return user


def _client(user):
    client = APIClient()
    client.force_authenticate(user)
    return client


class _Base(TestCase):
    def setUp(self):
        cache.clear()
        self.image_model = GPTModels.objects.create(
            name="Frame", openrouter_id="test/frame", max_tokens=100,
            markup_coefficient=Decimal(FRAME), category="image")
        self.video_model = GPTModels.objects.create(
            name="Video", openrouter_id="test/video", max_tokens=100,
            markup_coefficient=Decimal(3), category="video")
        self.preset = CartoonPreset.objects.create(
            title="Крыша", slug="roof", scene_prompt="The character on a roof",
            image_model=self.image_model, video_model=self.video_model, duration=5)
        self.hero = CartoonCharacter.objects.create(
            name="Кот", image="cartoon/characters/cat.jpg", is_public=True)

    def _balance(self, user):
        user.refresh_from_db()
        return user.token_balance

    def _project(self, user, **extra):
        return CartoonProject.objects.create(user=user, character=self.hero, **extra)

    def _scene(self, project, order=0, **extra):
        return CartoonScene.objects.create(project=project, preset=self.preset, order=order, **extra)

    def _render(self, user, scene):
        with patch("cartoon.views.render_scene.delay") as delay, \
             self.captureOnCommitCallbacks(execute=True):
            response = _client(user).post(f"/api/cartoon/scenes/{scene.pk}/render/", {},
                                          format="json")
        scene.refresh_from_db()
        return response, delay


def _fake_video_env(on_video=None):
    """Подмена всего внешнего в съёмке: промпт, модель видео, последний кадр."""
    def video(*args, **kwargs):
        if on_video:
            on_video()
        return "cartoon/scenes/new.mp4"

    return [
        patch("cartoon.tasks.ensure_video_prompt", return_value={"prompt": "p", "negative": ""}),
        patch("cartoon.tasks.generate_scene_video", side_effect=video),
        patch("cartoon.tasks.last_frame_of", return_value=""),
        patch("cartoon.tasks._notify_scene"),
    ]


def _run_render(scene_id, on_video=None, extra=()):
    from contextlib import ExitStack

    from cartoon.tasks import render_scene

    with ExitStack() as stack:
        for p in list(_fake_video_env(on_video)) + list(extra):
            stack.enter_context(p)
        return render_scene.apply(args=[scene_id]).get()


# --- 2) параллельные съёмки не уводят в минус ------------------------------

@override_settings(CACHES=CACHES)
class ReserveTests(_Base):
    def test_second_scene_sees_balance_taken_by_the_first(self):
        """Баланс на одну сцену — вторую не запустить, пока снимается первая."""
        user = _user(FULL)
        project = self._project(user)
        first, second = self._scene(project, 0), self._scene(project, 1)

        response, delay = self._render(user, first)
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(first.status, CartoonScene.STATUS_NEW)
        delay.assert_called_once_with(first.pk)

        response, delay = self._render(user, second)
        self.assertEqual(response.status_code, 402, response.data)
        self.assertEqual(response.data["required"], FULL)
        self.assertEqual(response.data["balance"], 0)
        self.assertEqual(response.data["reserved"], FULL)
        delay.assert_not_called()
        self.assertEqual(second.status, CartoonScene.STATUS_DRAFT)

    def test_scene_on_video_stage_reserves_only_the_video(self):
        user = _user(VIDEO + FULL)
        project = self._project(user)
        self._scene(project, 0, status=CartoonScene.STATUS_VIDEO, keyframe="cartoon/k/1.jpg")
        response, delay = self._render(user, self._scene(project, 1))
        self.assertEqual(response.status_code, 200, response.data)
        delay.assert_called_once()

    def test_double_click_queues_one_task(self):
        user = _user(1000)
        scene = self._scene(self._project(user))
        _, first = self._render(user, scene)
        _, second = self._render(user, scene)
        self.assertEqual(first.call_count + second.call_count, 1)

    def test_drained_balance_at_the_end_is_a_clear_error_not_a_charge(self):
        """Баланс ушёл на другое, пока шла съёмка: понятный текст, кадр цел, минуса нет."""
        user = _user(1000)
        scene = self._scene(self._project(user), status=CartoonScene.STATUS_NEW,
                            keyframe="cartoon/k/1.jpg")

        def drain():
            get_user_model().objects.filter(pk=user.pk).update(token_balance=3)

        result = _run_render(scene.pk, on_video=drain)
        self.assertEqual(result["status"], "no_credits")
        scene.refresh_from_db()
        self.assertEqual(scene.status, CartoonScene.STATUS_FAILED)
        self.assertIn("Не хватило кредитов на видео", scene.error)
        self.assertEqual(scene.keyframe, "cartoon/k/1.jpg")
        self.assertEqual(self._balance(user), 3)
        self.assertFalse(TokenTransaction.objects.filter(reason="cartoon_scene").exists())
        # Провайдеру ролик оплачен, человеку не выдан — это в разбор.
        self.assertEqual(GenerationLog.objects.get(scene_id=scene.pk).status, GenerationLog.STATUS_LOST)


# --- 3) удаление во время съёмки --------------------------------------------

@override_settings(CACHES=CACHES)
class DeleteWhileRenderingTests(_Base):
    def test_working_scene_and_its_project_are_not_deleted(self):
        user = _user(1000)
        project = self._project(user)
        for working in (CartoonScene.STATUS_NEW, CartoonScene.STATUS_KEYFRAME,
                        CartoonScene.STATUS_VIDEO):
            with self.subTest(status=working):
                scene = self._scene(project, status=working)
                response = _client(user).delete(f"/api/cartoon/scenes/{scene.pk}/")
                self.assertEqual(response.status_code, 400)
                self.assertIn("снимается", response.data["detail"])
                self.assertEqual(_client(user).delete(f"/api/cartoon/projects/{project.pk}/").status_code, 400)
                scene.delete()
        self.assertEqual(_client(user).delete(f"/api/cartoon/projects/{project.pk}/").status_code, 204)

    def test_assembling_project_is_not_deleted(self):
        user = _user(1000)
        project = self._project(user, status=CartoonProject.STATUS_ASSEMBLING)
        self.assertEqual(_client(user).delete(f"/api/cartoon/projects/{project.pk}/").status_code, 400)
        self.assertTrue(CartoonProject.objects.filter(pk=project.pk).exists())

    def test_finished_scene_is_deleted(self):
        user = _user(1000)
        scene = self._scene(self._project(user), status=CartoonScene.STATUS_READY)
        self.assertEqual(_client(user).delete(f"/api/cartoon/scenes/{scene.pk}/").status_code, 204)

    def test_scene_removed_mid_render_is_not_charged(self):
        """Сцену снесли (каскадом, из админки), пока снималось видео: не списываем и не падаем."""
        user = _user(1000)
        scene = self._scene(self._project(user), status=CartoonScene.STATUS_NEW,
                            keyframe="cartoon/k/1.jpg")
        result = _run_render(scene.pk,
                             on_video=lambda: CartoonScene.objects.filter(pk=scene.pk).delete())
        self.assertEqual(result["status"], "gone")
        self.assertEqual(self._balance(user), 1000)
        self.assertFalse(TokenTransaction.objects.exists())
        self.assertEqual(GenerationLog.objects.get(scene_id=scene.pk).status, GenerationLog.STATUS_LOST)

    def test_full_render_charges_frame_and_video_once(self):
        user = _user(1000)
        scene = self._scene(self._project(user), status=CartoonScene.STATUS_NEW)
        result = _run_render(scene.pk, extra=[
            patch("cartoon.services.generate_keyframe", return_value="cartoon/keyframes/new.png")])
        self.assertEqual(result["status"], "ready", result)
        scene.refresh_from_db()
        self.assertEqual(scene.credits_spent, FULL)
        self.assertEqual(self._balance(user), 1000 - FULL)
        # Вторая доставка той же задачи ничего не снимает и не списывает.
        self.assertEqual(_run_render(scene.pk)["status"], "not_queued")
        self.assertEqual(self._balance(user), 1000 - FULL)


# --- 4) зависшие сцены и склейки --------------------------------------------

@override_settings(CACHES=CACHES)
class StaleWorkTests(_Base):
    def _age(self, obj, minutes):
        type(obj).objects.filter(pk=obj.pk).update(updated_at=timezone.now() - timedelta(minutes=minutes))

    def test_sweeper_fails_silent_work_and_spares_live_one(self):
        from cartoon.tasks import STALE_MOVIE_ERROR, STALE_SCENE_ERROR, fail_stale_work

        user = _user(1000)
        project = self._project(user)
        dead_video = self._scene(project, 0, status=CartoonScene.STATUS_VIDEO)
        dead_frame = self._scene(project, 1, status=CartoonScene.STATUS_KEYFRAME)
        live_video = self._scene(project, 2, status=CartoonScene.STATUS_VIDEO)
        queued = self._scene(project, 3, status=CartoonScene.STATUS_NEW)
        lost_in_queue = self._scene(project, 4, status=CartoonScene.STATUS_NEW)
        done = self._scene(project, 5, status=CartoonScene.STATUS_READY)
        for scene, minutes in ((dead_video, 30), (dead_frame, 25), (live_video, 3),
                               (queued, 30), (lost_in_queue, 60), (done, 300)):
            self._age(scene, minutes)
        entry = GenerationLog.objects.create(user=user, kind="video", source="studio",
                                             scene_id=dead_video.pk,
                                             status=GenerationLog.STATUS_SUBMITTED)
        started = timezone.now() - timedelta(minutes=30)
        stuck = self._project(user, status=CartoonProject.STATUS_ASSEMBLING,
                              assembly_started_at=started)
        busy = self._project(user, status=CartoonProject.STATUS_ASSEMBLING,
                             assembly_started_at=timezone.now())
        # Склейка ещё в очереди media — полчаса ожидания не обрыв.
        waiting = self._project(user, status=CartoonProject.STATUS_ASSEMBLING)
        self._age(stuck, 30)
        self._age(busy, 2)
        self._age(waiting, 30)

        with patch("cartoon.tasks._notify_scene") as notify:
            result = fail_stale_work.apply().get()
        self.assertEqual(result, {"scenes": 3, "projects": 1})
        self.assertEqual(notify.call_count, 3)
        for scene in (dead_video, dead_frame, lost_in_queue):
            scene.refresh_from_db()
            self.assertEqual(scene.status, CartoonScene.STATUS_FAILED)
            self.assertEqual(scene.error, STALE_SCENE_ERROR)
        for scene, st in ((live_video, "video"), (queued, "new"), (done, "ready")):
            scene.refresh_from_db()
            self.assertEqual(scene.status, st)
        stuck.refresh_from_db()
        busy.refresh_from_db()
        waiting.refresh_from_db()
        self.assertEqual((stuck.status, stuck.error), ("failed", STALE_MOVIE_ERROR))
        self.assertEqual(busy.status, "assembling")
        self.assertEqual(waiting.status, "assembling")
        entry.refresh_from_db()
        self.assertEqual(entry.status, GenerationLog.STATUS_LOST)
        self.assertFalse(TokenTransaction.objects.exists())

    def _sweep(self):
        from cartoon.tasks import fail_stale_work

        with patch("cartoon.tasks._notify_scene"):
            return fail_stale_work.apply().get()

    def test_queued_work_waits_longer_behind_a_busy_media_queue(self):
        """В общей очереди media впереди получасовые съёмки: ожидание — не обрыв."""
        from cartoon import tasks

        user = _user(1000)
        project = self._project(user)
        # Живые съёмки заняли все места очереди.
        for i in range(tasks.MEDIA_SLOTS):
            self._age(self._scene(project, i, status=CartoonScene.STATUS_VIDEO), 1)
        waiting_scene = self._scene(project, 5, status=CartoonScene.STATUS_NEW)
        waiting_movie = self._project(user, status=CartoonProject.STATUS_ASSEMBLING)
        self._age(waiting_scene, 60)
        self._age(waiting_movie, 60)
        self.assertEqual(self._sweep(), {"scenes": 0, "projects": 0})

        # Дольше, чем очередь могла бы продержать, — задача потерялась.
        self._age(waiting_scene, 80)
        self._age(waiting_movie, 80)
        self.assertEqual(self._sweep(), {"scenes": 1, "projects": 1})
        waiting_movie.refresh_from_db()
        self.assertEqual(waiting_movie.status, CartoonProject.STATUS_FAILED)

    def test_lost_queued_work_on_an_idle_queue_is_closed(self):
        user = _user(1000)
        scene = self._scene(self._project(user), status=CartoonScene.STATUS_NEW)
        movie = self._project(user, status=CartoonProject.STATUS_ASSEMBLING)
        self._age(scene, 50)
        self._age(movie, 50)
        self.assertEqual(self._sweep(), {"scenes": 1, "projects": 1})

    def test_task_that_wakes_up_after_the_sweep_does_not_deliver(self):
        """Воркер ожил после уборки: сцена уже «не получилась», ролик не выдаём и не списываем."""
        user = _user(1000)
        scene = self._scene(self._project(user), status=CartoonScene.STATUS_NEW,
                            keyframe="cartoon/k/1.jpg")

        def swept():
            CartoonScene.objects.filter(pk=scene.pk).update(status=CartoonScene.STATUS_FAILED)

        self.assertEqual(_run_render(scene.pk, on_video=swept)["status"], "gone")
        self.assertEqual(self._balance(user), 1000)

    def test_live_render_heartbeat_keeps_the_scene_fresh(self):
        from cartoon import tasks

        user = _user(1000)
        scene = self._scene(self._project(user), status=CartoonScene.STATUS_VIDEO)
        self._age(scene, 30)
        clock = iter([0.0, 30.0, 120.0])
        beat = tasks._heartbeat(scene.pk, clock=lambda: next(clock))
        beat()  # 30 с — рано
        scene.refresh_from_db()
        self.assertLess(scene.updated_at, timezone.now() - timedelta(minutes=20))
        beat()  # 120 с — отметка
        scene.refresh_from_db()
        self.assertGreater(scene.updated_at, timezone.now() - timedelta(minutes=1))

    def test_poll_loop_does_not_swallow_the_soft_time_limit(self):
        """Широкий except в опросе глотал SoftTimeLimitExceeded — задачу потом убивал жёсткий лимит."""
        from cartoon import services

        submit = MagicMock(status_code=200)
        submit.json.return_value = {"id": "gen-1", "polling_url": "http://x/videos/gen-1"}
        beats = []
        with patch("cartoon.services._openrouter_config", return_value={"base_url": "http://x", "api_key": "k"}), \
             patch("cartoon.services._video_model_params", return_value={"duration": 5, "resolution": "720p"}), \
             patch("cartoon.services.supported_aspect", return_value="16:9"), \
             patch("cartoon.services.requests.post", return_value=submit), \
             patch("cartoon.services.requests.get", side_effect=SoftTimeLimitExceeded()), \
             patch("time.sleep"):
            with self.assertRaises(SoftTimeLimitExceeded):
                services.generate_scene_video(self.preset, "cartoon/k/1.jpg",
                                              heartbeat=lambda: beats.append(1))
        self.assertEqual(len(beats), 1)

    def test_render_limits_cover_the_poll_budget(self):
        from cartoon import services, tasks

        self.assertGreater(tasks.render_scene.soft_time_limit, services.VIDEO_POLL_SECONDS + 10 * 60)
        self.assertGreater(tasks.render_scene.time_limit, tasks.render_scene.soft_time_limit)
        # Уборка не должна ловить живую съёмку: молчание дольше отметки пульса.
        self.assertGreater(tasks.STALE_WORK_AFTER.total_seconds(), tasks.HEARTBEAT_EVERY * 10)


# --- 5) «Собрать мультфильм» ------------------------------------------------

@override_settings(CACHES=CACHES)
class AssembleTests(_Base):
    def _assemble(self, user, project):
        with patch("cartoon.views.assemble_movie.delay") as delay, \
             self.captureOnCommitCallbacks(execute=True):
            response = _client(user).post(f"/api/cartoon/projects/{project.pk}/assemble/", {},
                                          format="json")
        return response, delay

    def test_status_is_assembling_at_once_and_second_click_queues_nothing(self):
        user = _user(0)
        project = self._project(user)
        self._scene(project, status=CartoonScene.STATUS_READY, video="cartoon/scenes/1.mp4")
        response, delay = self._assemble(user, project)
        self.assertEqual(response.status_code, 202, response.data)
        self.assertEqual(response.data["status"], "assembling")
        delay.assert_called_once_with(project.pk)
        again, delay = self._assemble(user, project)
        self.assertEqual(again.data["status"], "assembling")
        delay.assert_not_called()

    def test_nothing_to_assemble(self):
        user = _user(0)
        project = self._project(user)
        response, delay = self._assemble(user, project)
        self.assertEqual(response.status_code, 400)
        delay.assert_not_called()

    def test_failed_assembly_shows_words_not_the_exception(self):
        from cartoon.tasks import assemble_movie

        user = _user(0)
        project = self._project(user, status=CartoonProject.STATUS_ASSEMBLING)
        with patch("cartoon.tasks.assemble_project", side_effect=OSError("[Errno 2] /tmp/x.mp4")), \
             patch("cartoon.tasks._notify_movie"):
            assemble_movie.apply(args=[project.pk]).get()
        project.refresh_from_db()
        self.assertEqual(project.status, "failed")
        self.assertNotIn("Errno", project.error)
        self.assertIn("склеить", project.error)

    def _run_assembly(self, project, video="cartoon/movies/m.mp4", during=None):
        from cartoon.tasks import assemble_movie

        def fake(p):
            if during:
                during()
            return video

        with patch("cartoon.tasks.assemble_project", side_effect=fake) as work, \
             patch("cartoon.tasks._notify_movie") as notify:
            result = assemble_movie.apply(args=[project.pk]).get()
        project.refresh_from_db()
        return result, work, notify

    def test_click_then_task_marks_start_and_finishes(self):
        user = _user(0)
        project = self._project(user, status=CartoonProject.STATUS_READY,
                                assembly_started_at=timezone.now() - timedelta(days=1))
        self._scene(project, status=CartoonScene.STATUS_READY, video="cartoon/scenes/1.mp4")
        self._assemble(user, project)
        project.refresh_from_db()
        # Новый запуск стоит в очереди: отметка прошлого сброшена.
        self.assertIsNone(project.assembly_started_at)
        result, work, notify = self._run_assembly(project)
        self.assertEqual(result["status"], "ready")
        self.assertEqual((project.status, project.result_video), ("ready", "cartoon/movies/m.mp4"))
        self.assertIsNotNone(project.assembly_started_at)
        notify.assert_called_once()

    def test_task_does_not_revive_a_project_the_sweeper_closed(self):
        """Задача дождалась очереди после уборки: «ошибка» не превращается обратно в «собирается»."""
        from cartoon.tasks import STALE_MOVIE_ERROR

        user = _user(0)
        project = self._project(user, status=CartoonProject.STATUS_FAILED, error=STALE_MOVIE_ERROR)
        result, work, notify = self._run_assembly(project)
        self.assertEqual(result["status"], "not_queued")
        work.assert_not_called()
        notify.assert_not_called()
        self.assertEqual((project.status, project.error), ("failed", STALE_MOVIE_ERROR))

    def test_second_queued_task_does_not_assemble_alongside(self):
        """Старая задача и задача нового нажатия: склеивает только первая взявшаяся."""
        user = _user(0)
        project = self._project(user, status=CartoonProject.STATUS_ASSEMBLING,
                                assembly_started_at=timezone.now())
        result, work, notify = self._run_assembly(project)
        self.assertEqual(result["status"], "not_queued")
        work.assert_not_called()
        self.assertEqual(project.status, CartoonProject.STATUS_ASSEMBLING)

    def test_late_result_does_not_overwrite_a_closed_run(self):
        user = _user(0)
        project = self._project(user, status=CartoonProject.STATUS_ASSEMBLING)

        def swept():
            CartoonProject.objects.filter(pk=project.pk).update(
                status=CartoonProject.STATUS_FAILED, error="оборвалась")

        result, work, notify = self._run_assembly(project, during=swept)
        self.assertEqual(result["status"], "gone")
        notify.assert_not_called()
        self.assertEqual((project.status, project.result_video), ("failed", ""))


# --- 6) сведение без самоожидания -------------------------------------------

@override_settings(CACHES=CACHES)
class MixLockTests(_Base):
    def setUp(self):
        super().setUp()
        self.user = _user(0)
        self.scene = self._scene(self._project(self.user), status=CartoonScene.STATUS_READY,
                                 video="cartoon/scenes/1.mp4")

    def _mix(self):
        return _client(self.user).post(f"/api/cartoon/scenes/{self.scene.pk}/audio/mix/", {},
                                       format="json")

    def test_mix_request_does_not_wait_for_itself(self):
        with patch("cartoon.audio.mix_scene", return_value="cartoon/scenes/mixed/1.mp4") as mix, \
             patch("time.sleep", side_effect=AssertionError("сведение ждало само себя")):
            response = self._mix()
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(mix.call_count, 1)
        self.assertIsNone(cache.get(audio.mix_lock_key(self.scene.pk)))

    def test_busy_scene_answers_at_once_and_keeps_the_other_lock(self):
        cache.add(audio.mix_lock_key(self.scene.pk), "other", 60)
        with patch("cartoon.audio.mix_scene") as mix, \
             patch("time.sleep", side_effect=AssertionError("веб-запрос не должен ждать")):
            response = self._mix()
        self.assertEqual(response.status_code, 429)
        self.assertEqual(mix.call_count, 0)
        self.assertEqual(cache.get(audio.mix_lock_key(self.scene.pk)), "other")

    def test_background_mix_waits_and_never_drops_someone_elses_lock(self):
        cache.add(audio.mix_lock_key(self.scene.pk), "other", 60)
        with patch("cartoon.audio.mix_scene", return_value=""), patch("time.sleep"):
            audio.remix_scene(self.scene)
        self.assertEqual(cache.get(audio.mix_lock_key(self.scene.pk)), "other")


# --- 7) оплаченный кадр идёт в съёмку ---------------------------------------

@override_settings(CACHES=CACHES)
class PooledFrameTests(_Base):
    def test_second_scene_uses_the_frame_the_user_saw(self):
        """Раньше вторая сцена рисовала кадр «с оглядкой» и брала за него ещё раз."""
        user = _user(1000)
        project = self._project(user)
        self._scene(project, 0, status=CartoonScene.STATUS_READY, last_frame="cartoon/k/last.jpg")
        CartoonKeyframe.objects.create(preset=self.preset, character=self.hero, aspect_ratio="16:9",
                                       image="cartoon/keyframes/tryon.png")
        second = self._scene(project, 1)

        response, delay = self._render(user, second)
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(second.keyframe, "cartoon/keyframes/tryon.png")

        with patch("cartoon.services.generate_keyframe") as draw:
            result = _run_render(second.pk)
        self.assertEqual(result["status"], "ready", result)
        self.assertEqual(draw.call_count, 0)
        self.assertEqual(self._balance(user), 1000 - VIDEO)
        self.assertFalse(TokenTransaction.objects.filter(reason="cartoon_keyframe").exists())

    def test_task_prefers_the_pooled_frame_over_a_linked_one(self):
        user = _user(1000)
        project = self._project(user)
        self._scene(project, 0, status=CartoonScene.STATUS_READY, last_frame="cartoon/k/last.jpg")
        second = self._scene(project, 1, status=CartoonScene.STATUS_NEW)
        CartoonKeyframe.objects.create(preset=self.preset, character=self.hero, aspect_ratio="16:9",
                                       image="cartoon/keyframes/tryon.png")
        with patch("cartoon.services.generate_keyframe") as draw:
            self.assertEqual(_run_render(second.pk)["status"], "ready")
        second.refresh_from_db()
        self.assertEqual(second.keyframe, "cartoon/keyframes/tryon.png")
        self.assertEqual(draw.call_count, 0)
        self.assertEqual(second.credits_spent, VIDEO)

    def test_first_filmed_scene_links_the_next_frame_when_pool_is_empty(self):
        user = _user(1000)
        project = self._project(user)
        self._scene(project, 0, status=CartoonScene.STATUS_READY, last_frame="cartoon/k/last.jpg")
        second = self._scene(project, 1, status=CartoonScene.STATUS_NEW)
        with patch("cartoon.services.generate_keyframe", return_value="cartoon/k/linked.png") as draw:
            self.assertEqual(_run_render(second.pk)["status"], "ready")
        self.assertEqual(draw.call_args.kwargs["refs"], ["cartoon/k/last.jpg"])
        self.assertEqual(self._balance(user), 1000 - FULL)
        # Кадр с оглядкой на личную сцену в общий запас не попадает.
        self.assertFalse(CartoonKeyframe.objects.exists())


# --- 11) цена на витрине = цена списания ------------------------------------

@override_settings(CACHES=CACHES)
class PriceOverrideTests(_Base):
    def test_manual_price_is_what_is_charged(self):
        from cartoon.pricing import scene_credits, scene_video_credits

        self.preset.credits_override = 100
        self.preset.save(update_fields=["credits_override"])
        self.assertEqual(self.preset.estimated_credits(), 100)
        self.assertEqual(scene_credits(self.preset), 100)
        self.assertEqual(scene_video_credits(self.preset), 100 - FRAME)

        user = _user(1000)
        scene = self._scene(self._project(user), status=CartoonScene.STATUS_NEW)
        result = _run_render(scene.pk, extra=[
            patch("cartoon.services.generate_keyframe", return_value="cartoon/keyframes/new.png")])
        self.assertEqual(result["status"], "ready", result)
        self.assertEqual(self._balance(user), 900)


# --- 10) озвучка всего мультфильма: без двойного списания --------------------

@override_settings(CACHES=CACHES, ELEVENLABS_API_KEY="test-key")
class VoiceAllRestartTests(_Base):
    def setUp(self):
        super().setUp()
        self.user = _user(100)
        self.project = self._project(self.user)
        self.scene = self._scene(self.project)
        self.plan = [{"scene_id": self.scene.pk, "text": "Привет!", "voice_id": "m1"}]

    def test_queued_run_is_not_declared_dead_after_three_minutes(self):
        body = {"lines": self.plan}
        client = _client(self.user)
        with patch("cartoon.views_audio.voice_movie.delay") as delay:
            self.assertEqual(client.post(f"/api/cartoon/projects/{self.project.pk}/voice-all/",
                                         body, format="json").status_code, 202)
            state = voiceover.get_progress(self.project.pk)
            self.assertTrue(state["queued"])
            state["at"] -= voiceover.STALE_AFTER + 60
            cache.set(voiceover.progress_key(self.project.pk), state, 600)
            self.assertFalse(voiceover.is_stale(state))
            again = client.post(f"/api/cartoon/projects/{self.project.pk}/voice-all/", body,
                                format="json")
        self.assertEqual(again.status_code, 429)
        self.assertEqual(delay.call_count, 1)

    def test_superseded_run_stops_before_paying(self):
        cache.set(voiceover.lock_key(self.project.pk), "new-run", 600)
        voiceover.set_progress(self.project.pk, done=0, total=1, finished=False)
        with patch("cartoon.audio.tts") as tts:
            result = voiceover.voice_project(self.project, self.plan, token="old-run")
        self.assertEqual(result["error"], "superseded")
        self.assertEqual(tts.call_count, 0)
        self.assertEqual(self._balance(self.user), 100)
        # Прогресс нового запуска не тронут.
        self.assertFalse(voiceover.get_progress(self.project.pk)["finished"])

    def test_lock_taken_over_during_synthesis_means_no_charge(self):
        cache.set(voiceover.lock_key(self.project.pk), "old-run", 600)

        def tts(text, voice_id):
            cache.set(voiceover.lock_key(self.project.pk), "new-run", 600)
            return b"mp3"

        with patch("cartoon.audio.tts", side_effect=tts), \
             patch("cartoon.audio.save_audio", return_value=("cartoon/audio/x.mp3", 1.0)):
            result = voiceover.voice_project(self.project, self.plan, token="old-run")
        self.assertEqual(result["error"], "superseded")
        self.assertEqual(self._balance(self.user), 100)
        self.assertFalse(self.scene.audio_tracks.exists())
        self.assertEqual(cache.get(voiceover.lock_key(self.project.pk)), "new-run")

    def test_own_run_is_charged_per_line(self):
        cache.set(voiceover.lock_key(self.project.pk), "run", 600)
        with patch("cartoon.audio.tts", return_value=b"mp3"), \
             patch("cartoon.audio.save_audio", return_value=("cartoon/audio/x.mp3", 1.0)):
            result = voiceover.voice_project(self.project, self.plan, token="run")
        self.assertEqual((result["done"], result["error"]), (1, ""))
        self.assertEqual(self._balance(self.user), 95)


# --- отказ модели картинок и загрузка звука ---------------------------------

@override_settings(CACHES=CACHES)
class ImageRefusalTests(_Base):
    BLOCKED = ('http 400: {"error":{"message":"Gemini blocked this request through content '
               'moderation.","metadata":{"block_reason":"PROHIBITED_CONTENT",'
               '"finish_reason":"IMAGE_PROHIBITED_CONTENT"}}}')

    def test_mapping(self):
        from cartoon.services import IMAGE_BLOCKED_HERO, IMAGE_EMPTY, human_error

        self.assertEqual(human_error(RuntimeError(self.BLOCKED), "hero"), IMAGE_BLOCKED_HERO)
        self.assertEqual(human_error(RuntimeError('{"block_reason":"SAFETY"}'), "hero"),
                         IMAGE_BLOCKED_HERO)
        self.assertIn("кадр", human_error(RuntimeError(self.BLOCKED), "image"))
        self.assertEqual(human_error(RuntimeError("Gemini could not generate an image (STOP)"), "hero"),
                         IMAGE_EMPTY)
        self.assertEqual(human_error(RuntimeError("keyframe: в ответе нет изображения"), "image"), IMAGE_EMPTY)

    def test_hero_drawing_refusal_is_422_and_free(self):
        user = _user(100)
        GPTModels.objects.create(name="NB", openrouter_id="google/gemini-2.5-flash-image",
                                 max_tokens=10, markup_coefficient=Decimal(4), is_active=True)
        refused = MagicMock(status_code=400, text=self.BLOCKED)
        with patch("ai.handlers._openrouter_config", return_value={"base_url": "http://x", "api_key": "k"}), \
             patch("requests.post", return_value=refused):
            response = _client(user).post("/api/cartoon/characters/generate/",
                                          {"prompt": "кто-то"}, format="json")
        self.assertEqual(response.status_code, 422, response.data)
        self.assertTrue(response.data["refused"])
        self.assertIn("Опишите героя по-другому", response.data["detail"])
        self.assertEqual(self._balance(user), 100)

    def test_try_on_refusal_is_422_and_free(self):
        user = _user(100)
        with patch("cartoon.services.get_or_create_keyframe", side_effect=RuntimeError(self.BLOCKED)):
            response = _client(user).post(f"/api/cartoon/presets/{self.preset.pk}/try-on/",
                                          {"character_id": self.hero.pk}, format="json")
        self.assertEqual(response.status_code, 422, response.data)
        self.assertEqual(self._balance(user), 100)

    def test_custom_frame_is_drawn_in_the_movie_format(self):
        user = _user(100)
        project = self._project(user, aspect_ratio="9:16")
        scene = self._scene(project, custom_text="катается на скейте")
        with patch("cartoon.services.draw_custom_keyframe", return_value=("cartoon/k/c.png", FRAME)) as draw:
            response = _client(user).post(f"/api/cartoon/scenes/{scene.pk}/frame/", {}, format="json")
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(draw.call_args[0][3], "9:16")


class UploadSuffixTests(TestCase):
    def test_only_plain_audio_extensions(self):
        self.assertEqual(audio.upload_suffix("voice.webm"), ".webm")
        self.assertEqual(audio.upload_suffix("Запись.M4A"), ".m4a")
        # Диктофоны телефонов: Android — amr/3gp, iPhone — caf; и обычный flac.
        for name, ext in (("rec.amr", ".amr"), ("Voice 001.3gpp", ".3gpp"), ("a.3gp", ".3gp"),
                          ("memo.caf", ".caf"), ("song.flac", ".flac")):
            self.assertEqual(audio.upload_suffix(name), ext, name)
        for bad in ("list.m3u8", "x.ffconcat", "a.txt", "noext", "evil.mp3.hls", ""):
            self.assertEqual(audio.upload_suffix(bad), "", bad)
