# -*- coding: utf-8 -*-
"""Съёмка по снимку дока (BUILD_C, задача C2): модель, качество, длительность.

Что проверяем: задача съёмки снимает и списывает ровно то, что человек видел
на «Снять» (снимок сцены), а не текущий док; режиссёр и реплики мерятся длиной
снимка; отказ модели принять фото героя виден в логе и журнале с моделью; ролик
пары запоминается только со съёмки по настройкам пресета и в своём формате.
Цены — как в tests_dock_api (markup 40 %, MASTER, 87.4, кадр Nano 7).
"""
from __future__ import annotations

import io
import re
from contextlib import ExitStack
from unittest.mock import MagicMock, patch

from adminapi.runtime import set_runtime
from ai import pricing
from ai.models import GenerationLog
from cartoon import director, services, voiceover
from cartoon import pricing as cp
from cartoon.models import CartoonKeyframe, CartoonPairVideo, CartoonScene
from cartoon.tasks import _planned_frame, render_scene
from cartoon.tests_dock_api import FAST, MINI, S20, S25, DockBase
from plans.models import TokenTransaction

NEW_FRAME = "cartoon/keyframes/new.png"
NEW_VIDEO = "cartoon/scenes/new.mp4"


class _Pipeline(DockBase):
    """Съёмка целиком, с подменой всего внешнего: модели, ffmpeg, уведомлений."""

    def shoot(self, scene, *, director_answer=None, remember=False):
        seen = {"video": [], "frame": [], "director": []}

        def video(preset, keyframe, **kwargs):
            seen["video"].append({"keyframe": keyframe, **kwargs})
            return NEW_VIDEO

        def frame(preset, character, refs=None, aspect=""):
            seen["frame"].append(aspect)
            return NEW_FRAME

        def ask(payload):
            seen["director"].append(payload)
            if isinstance(director_answer, Exception):
                raise director_answer
            return director_answer or {"prompt": "directed", "negative": "blur"}

        fakes = [
            patch("cartoon.services.generate_keyframe", side_effect=frame),
            patch("cartoon.tasks.generate_scene_video", side_effect=video),
            patch("cartoon.director._ask", side_effect=ask),
            patch("cartoon.tasks.last_frame_of", return_value=""),
            patch("cartoon.tasks._notify_scene"),
            patch("cartoon.audio.remix_scene"),
        ]
        if remember:
            fakes += _pair_storage()
        else:
            fakes.append(patch("cartoon.tasks.remember_pair_video"))
        with ExitStack() as stack:
            for fake in fakes:
                stack.enter_context(fake)
            result = render_scene.apply(args=[scene.pk]).get()
        scene.refresh_from_db()
        self.user.refresh_from_db()
        seen["result"] = result
        return seen

    def charges(self, reason):
        return [-t.delta for t in TokenTransaction.objects.filter(user=self.user, reason=reason).order_by("id")]


def _pair_storage():
    """Ролик пары без файлов и ffmpeg: лёгкой копии нет — в запас ложится оригинал."""
    return [patch("django.core.files.storage.default_storage.open", return_value=io.BytesIO(b"mp4")),
            patch("cartoon.clips.make_clip", return_value=b"")]


class RenderSnapshotTests(_Pipeline):
    def test_dock_change_after_queue_shoots_and_charges_the_snapshot(self):
        project = self.project(model=MINI, resolution="480p", duration=5)
        scene = self.scene(project)
        response, _ = self.render(scene)
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual((scene.credits_planned, scene.shot_video_credits), (35, 28))
        # Док сменили, пока сцена стояла в очереди.
        r = self.client.patch(f"/api/cartoon/projects/{project.pk}/",
                              {"video_model": S20, "resolution": "720p", "duration": 10,
                               "aspect_ratio": "1:1"}, format="json")
        self.assertEqual(r.status_code, 200, r.content)

        seen = self.shoot(scene)
        self.assertEqual(seen["result"]["status"], "ready", seen["result"])
        shot = seen["video"][0]
        self.assertEqual((shot["model"].openrouter_id, shot["duration"], shot["resolution"], shot["aspect"]),
                         (MINI, 5, "480p", "16:9"))
        self.assertEqual(seen["frame"], ["16:9"])
        self.assertIn("Shot length: 5 seconds", seen["director"][0])
        # Списано ровно то, что было на кнопке: кадр 7 + видео 28.
        self.assertEqual((self.charges("cartoon_keyframe"), self.charges("cartoon_scene")), ([7], [28]))
        self.assertEqual((scene.credits_spent, self.user.token_balance), (35, 10000 - 35))
        log = GenerationLog.objects.get(scene_id=scene.pk)
        self.assertEqual(log.model, MINI)
        self.assertEqual(log.params, {"duration": 5, "resolution": "480p", "aspect_ratio": "16:9",
                                      "project": project.pk})
        self.assertEqual((log.credits_planned, log.credits_charged), (28, 28))

    def test_frame_is_charged_from_the_snapshot_not_the_live_price(self):
        scene = self.scene(self.project(model=MINI, resolution="480p", duration=5))
        self.render(scene)
        # Наценку подняли, пока сцена ждала очереди: живая цена кадра уже другая.
        set_runtime(pricing.KEY_MARKUP_PCT, "100")
        pricing.invalidate_price_caches()
        self.assertNotEqual(cp.frame_credits(self.models["google/gemini-2.5-flash-image"]), 7)
        self.assertEqual(self.shoot(scene)["result"]["status"], "ready")
        self.assertEqual((self.charges("cartoon_keyframe"), self.charges("cartoon_scene")), ([7], [28]))
        self.assertEqual(scene.credits_spent, scene.credits_planned)

    def test_pooled_frame_at_shoot_time_is_free(self):
        scene = self.scene(self.project(model=MINI, resolution="480p", duration=5))
        self.render(scene)
        # Пока сцена стояла в очереди, кадр пары нарисовала чья-то примерка.
        CartoonKeyframe.objects.create(preset=scene.preset, character=self.hero, aspect_ratio="16:9",
                                       image="cartoon/keyframes/pool.png")
        seen = self.shoot(scene)
        self.assertEqual(seen["result"]["status"], "ready")
        self.assertEqual(seen["frame"], [])
        self.assertEqual(scene.keyframe, "cartoon/keyframes/pool.png")
        self.assertEqual((scene.credits_spent, self.charges("cartoon_keyframe")), (28, []))

    def test_reshoot_takes_the_new_snapshot(self):
        project = self.project(model=MINI, resolution="480p", duration=5)
        scene = self.scene(project, status=CartoonScene.STATUS_READY, video="cartoon/scenes/old.mp4",
                           keyframe="cartoon/k/1.png", shot_model=self.models[MINI], shot_resolution="480p",
                           shot_duration=5, shot_aspect="16:9", credits_planned=35, shot_video_credits=28)
        r = self.client.patch(f"/api/cartoon/projects/{project.pk}/",
                              {"video_model": S20, "resolution": "720p", "duration": 5}, format="json")
        self.assertEqual(r.status_code, 200, r.content)
        response, _ = self.reshoot(scene)
        self.assertEqual(response.status_code, 200, response.content)
        seen = self.shoot(scene)
        shot = seen["video"][0]
        self.assertEqual((shot["model"].openrouter_id, shot["resolution"], shot["duration"]), (S20, "720p", 5))
        # Кадр уже был — платится только видео по новой цене.
        self.assertEqual((self.charges("cartoon_keyframe"), self.charges("cartoon_scene")), ([], [122]))

    def test_scene_queued_before_the_dock_shoots_like_before(self):
        """Снимка нет (поставили до выкладки): пресет в формате мультфильма, док не читается."""
        project = self.project(model=MINI, resolution="480p", duration=5)
        scene = self.scene(project, slug="s20-15-720", status=CartoonScene.STATUS_NEW)
        seen = self.shoot(scene)
        self.assertEqual(seen["result"]["status"], "ready", seen["result"])
        shot = seen["video"][0]
        self.assertEqual((shot["model"].openrouter_id, shot["duration"], shot["resolution"], shot["aspect"]),
                         (S20, 15, "720p", "16:9"))
        video = cp.scene_video_credits(self.presets["s20-15-720"], aspect="16:9")
        self.assertEqual((self.charges("cartoon_keyframe"), self.charges("cartoon_scene")), ([7], [video]))

    def test_unknown_cost_without_snapshot_fails_before_the_frame(self):
        scene = self.scene(self.project(), slug="sora-5", status=CartoonScene.STATUS_NEW)
        seen = self.shoot(scene)
        self.assertEqual(seen["result"]["status"], "price_unavailable")
        self.assertEqual((seen["frame"], seen["video"]), ([], []))
        self.assertEqual(self.user.token_balance, 10000)


class LegacyRenderSnapshotTests(_Pipeline):
    markup = False

    def test_admin_price_change_after_queue_does_not_change_the_charge(self):
        scene = self.scene(self.project(model=FAST, resolution="720p", duration=5))
        self.render(scene)
        planned = (scene.credits_planned, scene.shot_video_credits)
        # «Цена сцены» в админке поменялась, пока сцена ждала.
        set_runtime("studio_scene_credits", "500")
        pricing.invalidate_price_caches()
        self.assertNotEqual(cp.scene_price(scene.preset, model=self.models[FAST], resolution="720p",
                                           duration=5, aspect="16:9"), planned[0])
        seen = self.shoot(scene)
        self.assertEqual(seen["video"][0]["model"].openrouter_id, FAST)
        self.assertEqual(sum(self.charges("cartoon_keyframe") + self.charges("cartoon_scene")), planned[0])
        self.assertEqual(self.charges("cartoon_scene"), [planned[1]])


class PlannedFrameTests(DockBase):
    def test_frame_part_of_the_snapshot(self):
        scene = self.scene(self.project(), credits_planned=35, shot_video_credits=28, shot_duration=5,
                           shot_model=self.models[MINI], shot_resolution="480p", shot_aspect="16:9")
        shot = cp.shot_config(scene)
        self.assertEqual(_planned_frame(scene, shot, 9), 7)
        self.assertEqual(_planned_frame(scene, shot, 0), 0)
        # Кадр не входил в цену запуска (был готов), а к съёмке пропал — не берём.
        scene.credits_planned = 28
        with self.assertLogs("cartoon.tasks", "WARNING"):
            self.assertEqual(_planned_frame(scene, cp.shot_config(scene), 7), 0)
        # Без снимка — живая цена, как раньше.
        bare = self.scene(self.project())
        self.assertEqual(_planned_frame(bare, cp.shot_config(bare), 7), 7)


class DirectorDurationTests(_Pipeline):
    def test_beats_follow_the_shot_length(self):
        self.assertEqual(director.beats(5), "0-2s ... 2-4s ... 4-5s")
        self.assertEqual(director.beats(4), "0-2s ... 2-3s ... 3-4s")
        self.assertEqual(director.beats(10), "0-4s ... 4-8s ... 8-10s")
        self.assertEqual(director.beats(15), "0-6s ... 6-12s ... 12-15s")
        self.assertEqual(director.beats(2), "0-2s")

    def test_director_gets_the_snapshot_duration(self):
        scene = self.scene(self.project(model=MINI, resolution="480p", duration=10))
        self.render(scene)
        seen = self.shoot(scene)
        self.assertEqual(seen["video"][0]["duration"], 10)
        self.assertIn("Shot length: 10 seconds, beats like 0-4s ... 4-8s ... 8-10s", seen["director"][0])
        self.assertIn("about 25 words", seen["director"][0])
        self.assertEqual(scene.video_prompt, "directed")

    def test_fallback_prompt_uses_the_snapshot_duration(self):
        scene = self.scene(self.project(model=MINI, resolution="480p", duration=12))
        self.render(scene)
        seen = self.shoot(scene, director_answer=director.DirectorFailed("нет сети"))
        self.assertEqual(seen["result"]["status"], "ready")
        self.assertIn("over 12 seconds", seen["video"][0]["prompt"])

    def test_duration_change_rebuilds_the_prompt_before_the_reshoot(self):
        """Готовая сцена 5 с → своя длительность 10 с → «Переснять»: режиссёр — под 10 с."""
        project = self.project(model=MINI, resolution="480p", duration=5)
        scene = self.scene(project, status=CartoonScene.STATUS_READY, video="cartoon/scenes/old.mp4",
                           keyframe="cartoon/k/1.png", video_prompt="beats for 5 s", video_negative="n",
                           shot_model=self.models[MINI], shot_resolution="480p", shot_duration=5,
                           shot_aspect="16:9", credits_planned=35, shot_video_credits=28)
        r = self.client.patch(f"/api/cartoon/scenes/{scene.pk}/", {"duration": 10}, format="json")
        self.assertEqual(r.status_code, 200, r.content)
        scene.refresh_from_db()
        self.assertEqual(scene.video_prompt, "beats for 5 s")  # готовая хранит промпт до пересъёмки
        self.reshoot(scene)
        seen = self.shoot(scene)
        self.assertEqual(len(seen["director"]), 1)
        self.assertIn("Shot length: 10 seconds", seen["director"][0])
        self.assertEqual((seen["video"][0]["duration"], seen["video"][0]["prompt"]), (10, "directed"))

    def test_same_length_keeps_the_cached_prompt(self):
        scene = self.scene(self.project(model=MINI, resolution="480p", duration=5),
                           status=CartoonScene.STATUS_FAILED, keyframe="cartoon/k/1.png",
                           video_prompt="cached 5 s", video_negative="n")
        self.render(scene)
        seen = self.shoot(scene)
        self.assertEqual((seen["director"], seen["video"][0]["prompt"]), ([], "cached 5 s"))


def _http(status_code=200, payload=None, content=b""):
    resp = MagicMock(status_code=status_code, text=str(payload or ""), content=content)
    resp.json.return_value = payload or {}
    return resp


class GenerateSceneVideoTests(DockBase):
    """Запрос к модели видео: снимок сцены и запасной путь без фото героя."""

    def call(self, posts, **kwargs):
        sent = []

        def post(url, json=None, **_kw):
            sent.append(dict(json))
            return posts.pop(0)

        poll = _http(200, {"status": "completed", "unsigned_urls": ["https://or.test/v.mp4"]})
        blob = _http(200, content=b"mp4")
        with patch("cartoon.services.requests.post", side_effect=post), \
                patch("cartoon.services.requests.get", side_effect=[poll, blob]), \
                patch("time.sleep"), \
                patch("cartoon.services._save_bytes", return_value="cartoon/scenes/x.mp4"):
            path = services.generate_scene_video(self.presets["s20-5-720"], "cartoon/k/1.png", prompt="p",
                                                 negative="n", character=self.hero, **kwargs)
        self.assertEqual(path, "cartoon/scenes/x.mp4")
        return sent

    def accepted(self):
        return _http(200, {"id": "job-1", "polling_url": "https://or.test/videos/job-1"})

    def test_request_carries_the_snapshot(self):
        sent = self.call([self.accepted()], aspect="9:16", model=self.models[MINI], duration=10,
                         resolution="480p")
        body = sent[0]
        self.assertEqual((body["model"], body["duration"], body["resolution"], body["aspect_ratio"]),
                         (MINI, 10, "480p", "9:16"))
        self.assertEqual(body["frame_images"][0]["frame_type"], "first_frame")
        self.assertIn("input_references", body)

    def test_without_settings_it_is_the_preset(self):
        """render_previews и прочие вызовы без снимка снимают как пресет."""
        body = self.call([self.accepted()])[0]
        self.assertEqual((body["model"], body["duration"], body["resolution"], body["aspect_ratio"]),
                         (S20, 5, "720p", "16:9"))
        # Модель можно передать и строкой.
        body = self.call([self.accepted()], model=S25, duration=20)[0]
        self.assertEqual((body["model"], body["duration"]), (S25, 20))

    def test_refused_hero_reference_is_logged_with_the_model(self):
        from ai import genlog

        entry = genlog.start(user=self.user, kind="video", source="studio", model=MINI)
        refused = _http(400, {"error": "input_references not supported"})
        with self.assertLogs("cartoon.services", "WARNING") as logs:
            sent = self.call([refused, self.accepted()], model=self.models[MINI], duration=5, resolution="480p",
                             entry=entry)
        self.assertTrue(any(MINI in line and "фото героя" in line for line in logs.output), logs.output)
        first, retry = sent
        self.assertIn("input_references", first)
        self.assertNotIn("input_references", retry)
        self.assertNotIn("negative_prompt", retry)
        # Первый кадр остаётся опорой и в повторе.
        self.assertEqual(retry["frame_images"], first["frame_images"])
        self.assertEqual(retry["model"], MINI)
        row = GenerationLog.objects.get(pk=entry.pk)
        dropped = [s for s in row.stages if s["stage"] == "refs_dropped"]
        self.assertEqual(len(dropped), 1)
        self.assertIn(MINI, dropped[0]["note"])


class VoiceSecondsTests(DockBase):
    def test_lines_are_measured_by_the_scene_duration(self):
        project = self.project(model=MINI, resolution="480p", duration=10)
        draft = self.scene(project)
        own = self.scene(project, duration=12)
        working = self.scene(project, status=CartoonScene.STATUS_VIDEO, keyframe="cartoon/k/1.png",
                             shot_model=self.models[MINI], shot_resolution="480p", shot_duration=5,
                             shot_aspect="16:9", credits_planned=35, shot_video_credits=28)
        self.assertEqual([voiceover.scene_seconds(s) for s in (draft, own, working)], [10, 12, 5])
        # Без настроек дока — длина пресета.
        self.assertEqual(voiceover.scene_seconds(self.scene(self.project(), slug="s20-15-720")), 15)
        # Длинные сцены Seedance 2.5 больше не режутся до 20 с.
        self.assertEqual(voiceover.scene_seconds(self.scene(self.project(model=S25, resolution="720p",
                                                                        duration=25))), 25)

    def test_plan_asks_for_lines_of_the_right_length(self):
        project = self.project(model=MINI, resolution="480p", duration=10)
        self.scene(project)
        asked = []

        def ask(listing, lang, numbers):
            asked.extend(listing)
            return {n: "Привет" for n in numbers}

        with patch("cartoon.voiceover._ask_model", side_effect=ask), \
                patch("cartoon.voiceover.pick_voices", return_value={}):
            plan = voiceover.build_plan(project)
        self.assertIn("Длительность: 10 с, не длиннее 130 символов", asked[0])
        self.assertEqual(plan["lines"][0]["seconds"], 10)


class CustomSceneWordingTests(DockBase):
    def test_custom_scene_prompt_names_no_duration(self):
        self.assertIsNone(re.search(r"\d+\s*seconds?", services._FORM_SYSTEM), services._FORM_SYSTEM)


class PairVideoRuleTests(_Pipeline):
    def ready(self, project, slug="s20-5-720", frame_aspect=None, **shot):
        preset = self.presets[slug]
        aspect = frame_aspect or project.aspect_ratio
        frame, _ = CartoonKeyframe.objects.get_or_create(
            preset=preset, character=self.hero, aspect_ratio=aspect,
            defaults={"image": f"cartoon/keyframes/pool-{preset.pk}-{aspect.replace(':', 'x')}.png"})
        if shot:
            shot = {"shot_aspect": project.aspect_ratio, "credits_planned": 1, "shot_video_credits": 1, **shot}
            shot["shot_model"] = self.models[shot["shot_model"]]
        return self.scene(project, slug=slug, status=CartoonScene.STATUS_READY,
                          video=f"cartoon/scenes/{preset.pk}-{project.pk}.mp4", keyframe=frame.image, **shot)

    def remember(self, scene):
        with ExitStack() as stack:
            for fake in _pair_storage():
                stack.enter_context(fake)
            return services.remember_pair_video(scene)

    def test_reference_shot_is_remembered_once_per_format(self):
        wide = self.ready(self.project("16:9"), shot_model=S20, shot_resolution="720p", shot_duration=5)
        self.assertTrue(self.remember(wide))
        tall = self.ready(self.project("9:16"), shot_model=S20, shot_resolution="720p", shot_duration=5)
        self.assertTrue(self.remember(tall))
        # Первый ролик формата остаётся: второй такой же его не вытесняет.
        self.assertFalse(self.remember(self.ready(self.project("16:9"))))
        rows = {r.aspect_ratio: r.source_scene_id for r in CartoonPairVideo.objects.all()}
        self.assertEqual(rows, {"16:9": wide.pk, "9:16": tall.pk})

    def test_shot_off_the_preset_config_is_not_remembered(self):
        for shot in ({"shot_model": MINI, "shot_resolution": "480p", "shot_duration": 5},
                     {"shot_model": S20, "shot_resolution": "480p", "shot_duration": 5},
                     {"shot_model": S20, "shot_resolution": "720p", "shot_duration": 10}):
            self.assertFalse(self.remember(self.ready(self.project("16:9"), **shot)), shot)
        self.assertFalse(CartoonPairVideo.objects.exists())

    def test_frame_of_another_format_is_not_remembered(self):
        scene = self.ready(self.project("16:9"), frame_aspect="9:16", shot_model=S20, shot_resolution="720p",
                           shot_duration=5)
        self.assertFalse(self.remember(scene))

    def test_format_the_model_cannot_shoot_is_not_remembered(self):
        """Veo не снимает квадрат: ролик был бы не того формата, что ключ."""
        self.assertFalse(self.remember(self.ready(self.project("1:1"), slug="veo-lite-5")))
        self.assertTrue(self.remember(self.ready(self.project("16:9"), slug="veo-lite-5")))

    def test_render_on_the_dock_model_leaves_no_preview_and_reference_render_does(self):
        mini = self.scene(self.project("16:9", model=MINI, resolution="480p", duration=5))
        CartoonKeyframe.objects.create(preset=mini.preset, character=self.hero, aspect_ratio="16:9",
                                       image="cartoon/keyframes/pool.png")
        self.render(mini)
        self.assertEqual(self.shoot(mini, remember=True)["result"]["status"], "ready")
        self.assertFalse(CartoonPairVideo.objects.exists())

        tall_project = self.project("9:16")
        reference = self.scene(tall_project)
        self.render(reference)
        self.assertTrue(cp.shot_config(reference).preset_default)
        self.assertEqual(self.shoot(reference, remember=True)["result"]["status"], "ready")
        row = CartoonPairVideo.objects.get()
        self.assertEqual((row.aspect_ratio, row.source_scene_id, row.video), ("9:16", reference.pk, NEW_VIDEO))
