# -*- coding: utf-8 -*-
"""Док мультстудии (BUILD_C, задача C1): модель, качество, длительность и снимок сцены.

Числа — PLAN §4.3 в режиме markup: курс закреплён на 87.4, кредит — MASTER
4990/6500, наценка 40 %, Nano Banana $0.039 (кадр 7). Каталог OpenRouter —
сохранённый, сети нет. legacy — прежняя формула для выбранной модели.
"""
from __future__ import annotations

from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from adminapi.runtime import delete_runtime, get_runtime, set_runtime
from ai import pricing
from ai.tests_pricing_golden import (GOLDEN_SETTINGS, NANO, create_models, create_packages, create_presets,
                                     start_price_mocks)
from cartoon import pricing as cp
from cartoon.models import CartoonCharacter, CartoonPairVideo, CartoonProject, CartoonScene

MINI = "bytedance/seedance-2.0-mini"
FAST = "bytedance/seedance-2.0-fast"
S20 = "bytedance/seedance-2.0"
S25 = "bytedance/seedance-2.5"


def _user(email: str, balance: int, staff: bool = False):
    user = get_user_model().objects.create_user(email=email, password="x-12345678")
    user.token_balance = balance
    user.is_staff = staff
    user.save(update_fields=["token_balance", "is_staff"])
    return user


def _client(user=None) -> APIClient:
    client = APIClient()
    if user is not None:
        client.force_authenticate(user)
    return client


@override_settings(**GOLDEN_SETTINGS)
class DockBase(TestCase):
    markup = True

    def setUp(self):
        cache.clear()
        start_price_mocks(self)
        self.models = create_models()
        create_packages()
        nano = self.models[NANO]
        nano.unit_cost_usd = Decimal("0.039")
        nano.save(update_fields=["unit_cost_usd"])
        self.presets = create_presets(self.models)
        self.hero = CartoonCharacter.objects.create(name="Лис", image="cartoon/characters/fox.jpg",
                                                    is_public=True, description="a small fox")
        set_runtime(pricing.KEY_MODE, pricing.MODE_MARKUP if self.markup else pricing.MODE_LEGACY)
        set_runtime(pricing.KEY_KGS_PER_USD, "87.4")
        pricing.invalidate_price_caches()
        self.user = _user("dock@example.com", 10000)
        self.client = _client(self.user)

    def project(self, aspect="16:9", model=None, resolution=None, duration=None, user=None):
        return CartoonProject.objects.create(
            user=user or self.user, character=self.hero, aspect_ratio=aspect,
            video_model=self.models[model] if model else None, resolution=resolution, duration=duration)

    def scene(self, project, slug="s20-5-720", **extra):
        return CartoonScene.objects.create(project=project, preset=self.presets[slug], **extra)

    def render(self, scene, user=None):
        with patch("cartoon.views.render_scene.delay") as delay, \
                self.captureOnCommitCallbacks(execute=True):
            response = _client(user or self.user).post(f"/api/cartoon/scenes/{scene.pk}/render/", {},
                                                       format="json")
        scene.refresh_from_db()
        return response, delay

    def reshoot(self, scene, user=None):
        """Пересъёмка готовой сцены — PATCH {retry}: POST render/ только для первой съёмки."""
        with patch("cartoon.views.render_scene.delay") as delay, \
                self.captureOnCommitCallbacks(execute=True):
            response = _client(user or self.user).patch(f"/api/cartoon/scenes/{scene.pk}/", {"retry": True},
                                                        format="json")
        scene.refresh_from_db()
        return response, delay


class ScenePriceTests(DockBase):
    def price(self, model, res, dur, aspect="16:9", slug="s20-5-720", keyframe_ready=False):
        return cp.scene_price(self.presets[slug], model=self.models[model], resolution=res, duration=dur,
                              aspect=aspect, keyframe_ready=keyframe_ready)

    def test_plan_table_at_40_percent(self):
        """PLAN §4.3: кадр 7 + видео, каждое округлено отдельно."""
        cases = {
            (MINI, "480p", 5, "16:9"): 35, (MINI, "480p", 10, "16:9"): 61, (MINI, "480p", 15, "16:9"): 88,
            (MINI, "480p", 5, "1:1"): 23, (MINI, "720p", 5, "16:9"): 68, (MINI, "720p", 5, "1:1"): 42,
            (FAST, "720p", 5, "16:9"): 80, (FAST, "720p", 15, "9:16"): 225,
            (S20, "480p", 5, "16:9"): 62, (S20, "720p", 5, "16:9"): 129, (S20, "720p", 5, "1:1"): 76,
            (S20, "720p", 10, "16:9"): 249, (S25, "720p", 5, "16:9"): 193, (S25, "720p", 5, "1:1"): 193,
        }
        for (model, res, dur, aspect), want in cases.items():
            self.assertEqual(self.price(model, res, dur, aspect), want, (model, res, dur, aspect))

    def test_pooled_keyframe_pays_video_only(self):
        self.assertEqual(self.price(MINI, "480p", 5, keyframe_ready=True), 28)
        parts = cp.config_price(self.presets["s20-5-720"],
                                cp.resolve_config(self.presets["s20-5-720"], model=self.models[MINI],
                                                  resolution="480p", duration=5, aspect="16:9"))
        self.assertEqual((parts.frame, parts.video, parts.total), (7, 28, 35))

    def test_empty_settings_are_the_preset_price(self):
        preset = self.presets["s20-5-720"]
        cfg = cp.resolve_config(preset, aspect="16:9")
        self.assertTrue(cfg.preset_default)
        self.assertEqual((cfg.model_id, cfg.resolution, cfg.duration), (S20, "720p", 5))
        self.assertEqual(cp.scene_price(preset, model=None, resolution=None, duration=None, aspect="16:9"),
                         cp.scene_credits(preset, aspect="16:9"))

    def test_unknown_cost_refuses(self):
        """Модель, которой нет в каталоге, в доке не предлагается и цены у неё нет."""
        self.assertFalse(cp.is_offered(self.models["openai/sora-2-pro"]))
        with patch("ai.handlers._openrouter_video_catalog", return_value={}):
            with self.assertRaises(pricing.PriceUnavailable):
                self.price(MINI, "480p", 5)


class LegacyPriceTests(DockBase):
    markup = False

    def test_preset_config_keeps_manual_price(self):
        """Настройки совпали с пресетом — ровно прежний путь, с ручной ценой."""
        preset = self.presets["s20-manual-250"]
        self.assertEqual(cp.scene_price(preset, model=self.models[S20], resolution="720p", duration=5,
                                        aspect="16:9"), 250)
        # Другая модель — ручная цена (цена пресета на Seedance 2.0) не действует.
        self.assertEqual(cp.scene_price(preset, model=self.models[MINI], resolution="480p", duration=5,
                                        aspect="16:9"), 37)

    def test_chosen_model_uses_todays_formula(self):
        preset = self.presets["s20-5-720"]
        mini = self.presets["mini-5-480"]
        # Mini 480p 5 с на пресете Seedance 2.0 = пресет Mini 480p 5 с.
        self.assertEqual(cp.scene_price(preset, model=self.models[MINI], resolution="480p", duration=5,
                                        aspect="1:1"), cp.scene_credits(mini))
        self.assertEqual(cp.scene_credits(mini), 37)

    def test_studio_scene_price_applies_per_second(self):
        set_runtime("studio_scene_credits", 100)
        preset = self.presets["s20-5-720"]
        got = cp.scene_price(preset, model=self.models[MINI], resolution="480p", duration=10, aspect="16:9")
        rate = (100 - 4) / 5
        self.assertEqual(got, 4 + cp.video_credits(self.models[MINI], 10, "480p", per_second=rate))


class ModelsEndpointTests(DockBase):
    def get(self, **params):
        response = _client().get("/api/cartoon/models/", params)
        self.assertEqual(response.status_code, 200, response.content)
        return response.json()

    def test_offered_models_in_dock_order(self):
        body = self.get()
        self.assertEqual([m["id"] for m in body["models"]], [MINI, FAST, S20, S25])
        self.assertEqual([m["short"] for m in body["models"]],
                         ["Seedance Mini", "Seedance Fast", "Seedance 2.0", "Seedance 2.5"])
        self.assertEqual(body["aspects"], ["16:9", "9:16", "1:1"])
        self.assertEqual(body["frame_credits"], 7)
        self.assertEqual(body["pricing_mode"], "markup")

    def test_caps_come_from_the_catalogue(self):
        by_id = {m["id"]: m for m in self.get()["models"]}
        self.assertEqual(by_id[MINI]["caps"]["resolutions"], ["480p", "720p"])
        self.assertEqual(by_id[MINI]["caps"]["durations"], list(range(4, 16)))
        self.assertEqual(by_id[S20]["caps"]["resolutions"], ["480p", "720p", "1080p", "4K"])
        self.assertEqual(by_id[S25]["caps"]["durations"], list(range(4, 31)))
        # Выбор модели в доке — с настройками новых мультфильмов (Mini 480p 5 с), в её пределах.
        self.assertEqual(by_id[MINI]["defaults"], {"duration": 5, "resolution": "480p", "aspect_ratio": "16:9"})
        set_runtime(cp.KEY_DEFAULT_DURATION, 30)
        pricing.invalidate_price_caches()
        by_id = {m["id"]: m for m in self.get()["models"]}
        self.assertEqual((by_id[MINI]["defaults"]["duration"], by_id[S25]["defaults"]["duration"]), (15, 30))
        for row in by_id.values():
            self.assertEqual(row["caps"]["aspect_ratios"], ["16:9", "9:16", "1:1"])
            # Форма ModelJSON видеостудии: пикеры рисуют её как есть.
            for key in ("id", "name", "badge", "locked", "eta_s", "price_from", "caps", "defaults", "price"):
                self.assertIn(key, row)

    def test_table_is_the_scene_price_for_the_aspect(self):
        body = self.get(aspect_ratio="1:1")
        mini = next(m for m in body["models"] if m["id"] == MINI)
        self.assertEqual(body["aspect_ratio"], "1:1")
        self.assertEqual(mini["price"]["table"]["480p"]["5"], 23)
        self.assertEqual(mini["price"]["by_aspect"]["16:9"]["480p"]["5"], 35)
        self.assertEqual(mini["price"]["by_aspect"]["9:16"]["720p"]["5"], 68)
        self.assertEqual(mini["price_from"], min(c for r in mini["price"]["table"].values() for c in r.values()))

    def test_every_cell_matches_scene_price_in_both_modes(self):
        """Таблица считается по прочитанной спеке — сверка с полной формулой."""
        ref = cp.reference_preset()
        for mode in (pricing.MODE_MARKUP, pricing.MODE_LEGACY):
            set_runtime(pricing.KEY_MODE, mode)
            set_runtime("studio_scene_credits", 100 if mode == pricing.MODE_LEGACY else 0)
            pricing.invalidate_price_caches()
            for row in self.get()["models"]:
                model = self.models[row["id"]]
                for aspect, table in row["price"]["by_aspect"].items():
                    for res, cells in table.items():
                        for sec in ("4", "5", "11", "15"):
                            want = cp.scene_price(ref, model=model, resolution=res, duration=int(sec),
                                                  aspect=aspect)
                            self.assertEqual(cells[sec], want, (mode, row["id"], aspect, res, sec))

    def test_inactive_and_foreign_models_are_not_offered(self):
        self.models[FAST].is_active = False
        self.models[FAST].save(update_fields=["is_active"])
        pricing.invalidate_price_caches()
        ids = [m["id"] for m in self.get()["models"]]
        self.assertNotIn(FAST, ids)
        self.assertNotIn("google/veo-3.1-lite", ids)
        self.assertNotIn("x-ai/grok-imagine-video", ids)

    def test_project_aspect_is_used(self):
        project = self.project("9:16")
        body = _client(self.user).get("/api/cartoon/models/", {"project": project.pk}).json()
        self.assertEqual(body["aspect_ratio"], "9:16")
        self.assertEqual(_client().get("/api/cartoon/models/", {"project": project.pk}).status_code, 404)

    def test_price_unavailable_when_cost_unknown(self):
        with patch("ai.video_cost.provider_cost_usd", return_value=None):
            pricing.invalidate_price_caches()
            body = self.get()
        self.assertTrue(body["models"])
        for row in body["models"]:
            self.assertNotIn("price", row)
            self.assertIsNone(row["price_from"])
            self.assertTrue(row["price_unavailable"])

    def test_defaults_say_what_new_projects_get(self):
        self.assertEqual(self.get()["defaults"],
                         {"video_model": MINI, "resolution": "480p", "duration": 5, "source": "settings"})
        self.models[MINI].is_active = False
        self.models[MINI].save(update_fields=["is_active"])
        pricing.invalidate_price_caches()
        self.assertEqual(self.get()["defaults"],
                         {"video_model": S20, "resolution": "720p", "duration": 5, "source": "preset"})


class NewProjectDefaultsTests(DockBase):
    def create(self, **body):
        response = self.client.post("/api/cartoon/projects/", {"character_id": self.hero.pk, **body},
                                    format="json")
        return response

    def test_new_project_gets_mini_480p_5s(self):
        r = self.create()
        self.assertEqual(r.status_code, 201, r.content)
        body = r.json()
        self.assertEqual((body["video_model"], body["resolution"], body["duration"]), (MINI, "480p", 5))
        self.assertEqual(body["effective"]["video_model"], MINI)
        self.assertTrue(body["effective"]["model_available"])

    def test_falls_back_to_preset_when_mini_is_absent_or_off(self):
        self.models[MINI].is_active = False
        self.models[MINI].save(update_fields=["is_active"])
        body = self.create().json()
        self.assertEqual((body["video_model"], body["resolution"], body["duration"]), (None, None, None))
        self.presets.pop("mini-5-480").delete()
        self.models[MINI].delete()
        body = self.create().json()
        self.assertEqual((body["video_model"], body["resolution"], body["duration"]), (None, None, None))
        self.assertEqual(body["effective"]["video_model"], S20)

    def test_falls_back_when_default_combination_is_unsupported(self):
        set_runtime(cp.KEY_DEFAULT_RESOLUTION, "1080p")
        self.assertEqual(self.create().json()["video_model"], None)
        set_runtime(cp.KEY_DEFAULT_RESOLUTION, "720p")
        set_runtime(cp.KEY_DEFAULT_DURATION, 3)
        self.assertEqual(self.create().json()["video_model"], None)
        set_runtime(cp.KEY_DEFAULT_DURATION, 10)
        body = self.create().json()
        self.assertEqual((body["video_model"], body["resolution"], body["duration"]), (MINI, "720p", 10))

    def test_explicit_settings_on_create(self):
        body = self.create(video_model=S25, resolution="720p", duration=12).json()
        self.assertEqual((body["video_model"], body["resolution"], body["duration"]), (S25, "720p", 12))
        # Только модель — качество и длительность по умолчанию, если она их умеет.
        body = self.create(video_model=FAST).json()
        self.assertEqual((body["video_model"], body["resolution"], body["duration"]), (FAST, "480p", 5))
        r = self.create(video_model=MINI, duration=20)
        self.assertEqual(r.status_code, 400)
        self.assertEqual(r.json()["error_code"], "unsupported_duration")
        self.assertEqual(r.json()["detail"], "Seedance Mini снимает от 4 до 15 секунд")

    def test_guest_draft_import_keeps_and_clamps_settings(self):
        body = self.client.post("/api/cartoon/projects/import/", {
            "draft_id": "draft-1", "character_id": self.hero.pk, "aspect_ratio": "9:16",
            "video_model": MINI, "resolution": "1080p", "duration": 5,
            "scenes": [{"preset_id": self.presets["s20-5-720"].pk, "duration": 30},
                       {"preset_id": self.presets["s20-15-720"].pk}]}, format="json").json()
        self.assertEqual((body["video_model"], body["resolution"], body["duration"]), (MINI, "720p", 5))
        fields = [a["field"] for a in body["adjusted"]]
        self.assertEqual(fields, ["resolution", "duration"])
        first, second = body["scenes"]
        self.assertEqual((first["duration"], first["config"]["duration"]), (15, 15))
        # Своей длительности нет — длительность мультфильма.
        self.assertEqual((second["duration"], second["config"]["duration"]), (None, 5))


class ProjectPatchTests(DockBase):
    def patch(self, project, **body):
        return self.client.patch(f"/api/cartoon/projects/{project.pk}/", body, format="json")

    def test_patch_sets_all_three(self):
        project = self.project()
        r = self.patch(project, video_model=S20, resolution="1080p", duration=10)
        self.assertEqual(r.status_code, 200, r.content)
        project.refresh_from_db()
        self.assertEqual((project.video_model.openrouter_id, project.resolution, project.duration),
                         (S20, "1080p", 10))
        self.assertNotIn("adjusted", r.json())

    def test_validation_errors_are_russian_and_change_nothing(self):
        project = self.project(model=MINI, resolution="480p", duration=5)
        cases = (
            ({"video_model": "openai/sora-2-pro"}, "model_unavailable",
             "Эта модель недоступна в мультстудии — выберите другую"),
            ({"video_model": 5}, "invalid_model", "Модель — строкой, например bytedance/seedance-2.0-mini"),
            ({"resolution": "1080p"}, "unsupported_resolution",
             "Seedance Mini не снимает в качестве 1080p. Доступно: 480p, 720p"),
            ({"duration": 16}, "unsupported_duration", "Seedance Mini снимает от 4 до 15 секунд"),
            ({"duration": "пять"}, "invalid_duration", "Длительность — целое число секунд"),
            ({"duration": True}, "invalid_duration", "Длительность — целое число секунд"),
            ({"title": "Новое", "duration": 99}, "invalid_duration", "Длительность — от 1 до 60 секунд"),
        )
        for body, code, text in cases:
            r = self.patch(project, **body)
            self.assertEqual(r.status_code, 400, body)
            self.assertEqual((r.json()["error_code"], r.json()["detail"]), (code, text), body)
        project.refresh_from_db()
        self.assertEqual((project.video_model.openrouter_id, project.resolution, project.duration, project.title),
                         (MINI, "480p", 5, "Мой мультфильм"))

    def test_model_change_clamps_and_tells(self):
        project = self.project(model=S20, resolution="1080p", duration=5)
        scene = self.scene(project, duration=20)
        scene.duration = 20
        scene.save(update_fields=["duration"])
        r = self.patch(project, video_model=MINI)
        self.assertEqual(r.status_code, 200, r.content)
        project.refresh_from_db()
        scene.refresh_from_db()
        self.assertEqual(project.resolution, "720p")
        self.assertEqual(scene.duration, 15)
        adjusted = r.json()["adjusted"]
        self.assertEqual([(a["field"], a["from"], a["to"]) for a in adjusted],
                         [("resolution", "1080p", "720p"), ("duration", 20, 15)])
        self.assertEqual(adjusted[0]["message"], "Seedance Mini не снимает в качестве 1080p — выбрано 720p")

    def test_resolution_without_model_takes_the_reference_model(self):
        project = self.project()
        r = self.patch(project, resolution="480p")
        self.assertEqual(r.status_code, 200, r.content)
        project.refresh_from_db()
        self.assertEqual((project.video_model.openrouter_id, project.resolution), (S20, "480p"))

    def test_null_model_resets_to_preset(self):
        project = self.project(model=MINI, resolution="480p", duration=5)
        body = self.patch(project, video_model=None).json()
        self.assertEqual((body["video_model"], body["resolution"], body["duration"]), (None, None, None))

    def test_duration_change_resets_draft_prompts_only(self):
        project = self.project(model=MINI, resolution="480p", duration=5)
        draft = self.scene(project, video_prompt="0-2s ...", video_negative="n")
        ready = self.scene(project, status=CartoonScene.STATUS_READY, video_prompt="old", video="v.mp4")
        own = self.scene(project, video_prompt="own", duration=5)
        self.patch(project, duration=10)
        for s in (draft, ready, own):
            s.refresh_from_db()
        self.assertEqual((draft.video_prompt, draft.video_negative), ("", ""))
        self.assertEqual(ready.video_prompt, "old")
        # Своя длительность сцены не изменилась — и промпт верен.
        self.assertEqual(own.video_prompt, "own")

    def test_scene_prices_follow_the_dock(self):
        project = self.project(model=MINI, resolution="480p", duration=5)
        self.scene(project)
        row = self.client.get(f"/api/cartoon/projects/{project.pk}/").json()["scenes"][0]
        self.assertEqual((row["preset"]["credits"], row["render_credits"], row["preset"]["duration"]),
                         (35, 35, 5))
        self.assertEqual(row["config"], {"video_model": MINI, "model_name": "Seedance Mini",
                                         "resolution": "480p", "duration": 5, "aspect_ratio": "16:9"})
        self.assertIsNone(row["shot"])
        self.patch(project, duration=10)
        row = self.client.get(f"/api/cartoon/projects/{project.pk}/").json()["scenes"][0]
        self.assertEqual((row["preset"]["credits"], row["preset"]["duration"]), (61, 10))


class ScenePatchTests(DockBase):
    def patch(self, scene, **body):
        return self.client.patch(f"/api/cartoon/scenes/{scene.pk}/", body, format="json")

    def test_scene_duration_within_the_model(self):
        project = self.project(model=MINI, resolution="480p", duration=5)
        scene = self.scene(project, video_prompt="5 s beats")
        r = self.patch(scene, duration=15)
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual((r.json()["duration"], r.json()["render_credits"]), (15, 88))
        scene.refresh_from_db()
        self.assertEqual(scene.video_prompt, "")
        r = self.patch(scene, duration=16)
        self.assertEqual((r.status_code, r.json()["error_code"]), (400, "unsupported_duration"))
        self.assertEqual(r.json()["detail"], "Seedance Mini снимает от 4 до 15 секунд")
        r = self.patch(scene, duration=None)
        self.assertEqual((r.status_code, r.json()["duration"], r.json()["config"]["duration"]), (200, None, 5))

    def test_scene_on_preset_model_validates_against_it(self):
        scene = self.scene(self.project(), slug="s25-10-720")
        self.assertEqual(self.patch(scene, duration=30).status_code, 200)
        self.assertEqual(self.patch(scene, duration=31).status_code, 400)

    def test_working_scene_duration_is_locked(self):
        scene = self.scene(self.project(model=MINI), status=CartoonScene.STATUS_VIDEO)
        r = self.patch(scene, duration=10)
        self.assertEqual(r.status_code, 400)
        self.assertEqual(r.json()["detail"], "Сцена уже снимается — длительность не поменять")

    def test_ready_scene_keeps_prompt_until_reshoot(self):
        project = self.project(model=MINI, resolution="480p", duration=5)
        scene = self.scene(project, status=CartoonScene.STATUS_READY, video="v.mp4", video_prompt="5 s",
                           keyframe="cartoon/k/1.png", shot_model=self.models[MINI], shot_resolution="480p",
                           shot_duration=5, shot_aspect="16:9", credits_planned=35, shot_video_credits=28)
        self.patch(scene, duration=10)
        scene.refresh_from_db()
        self.assertEqual(scene.video_prompt, "5 s")
        response, _ = self.reshoot(scene)
        self.assertEqual(response.status_code, 200, response.content)
        scene.refresh_from_db()
        self.assertEqual((scene.video_prompt, scene.shot_duration, scene.credits_planned), ("", 10, 54))


class SnapshotTests(DockBase):
    def test_queue_snapshots_settings_and_price(self):
        project = self.project(model=MINI, resolution="480p", duration=5)
        scene = self.scene(project)
        response, delay = self.render(scene)
        self.assertEqual(response.status_code, 200, response.content)
        delay.assert_called_once_with(scene.pk)
        self.assertEqual((scene.shot_model.openrouter_id, scene.shot_resolution, scene.shot_duration,
                          scene.shot_aspect, scene.credits_planned, scene.shot_video_credits),
                         (MINI, "480p", 5, "16:9", 35, 28))
        self.assertEqual(response.json()["shot"]["credits_planned"], 35)

    def test_dock_change_after_queue_does_not_touch_the_queued_scene(self):
        project = self.project(model=MINI, resolution="480p", duration=5)
        scene = self.scene(project)
        self.render(scene)
        r = self.client.patch(f"/api/cartoon/projects/{project.pk}/",
                              {"video_model": S20, "resolution": "720p", "duration": 10, "aspect_ratio": "1:1"},
                              format="json")
        self.assertEqual(r.status_code, 200, r.content)
        scene.refresh_from_db()
        cfg = cp.shot_config(scene)
        self.assertEqual((cfg.model_id, cfg.resolution, cfg.duration, cfg.aspect, cfg.snapshot),
                         (MINI, "480p", 5, "16:9", True))
        # Резерв и списание — по снимку, а не по новой цене дока.
        self.assertEqual(cp.reserved_credits(self.user), 35)
        self.assertEqual(cp.shot_video_credits(scene), 28)
        row = next(s for s in r.json()["scenes"] if s["id"] == scene.pk)
        self.assertEqual(row["config"]["video_model"], MINI)
        self.assertEqual(row["shot"]["credits_planned"], 35)
        # Сцена, ещё не поставленная в съёмку, уже по новым настройкам.
        project.refresh_from_db()
        other = self.scene(project)
        self.assertEqual(cp.scene_config(other).key(), (S20, "720p", 10, "1:1"))

    def test_reshoot_takes_current_settings_and_price(self):
        project = self.project(model=MINI, resolution="480p", duration=5)
        scene = self.scene(project, status=CartoonScene.STATUS_READY, video="v.mp4",
                           keyframe="cartoon/k/1.png", shot_model=self.models[MINI], shot_resolution="480p",
                           shot_duration=5, shot_aspect="16:9", credits_planned=35, shot_video_credits=28)
        project.video_model = self.models[S20]
        project.resolution = "720p"
        project.save()
        response, _ = self.reshoot(scene)
        self.assertEqual(response.status_code, 200, response.content)
        # Кадр готов — платится только видео: Seedance 2.0 720p 5 с = 122.
        self.assertEqual((scene.shot_model.openrouter_id, scene.shot_resolution, scene.credits_planned,
                          scene.shot_video_credits), (S20, "720p", 122, 122))

    def test_reserve_is_the_sum_of_planned_prices(self):
        project = self.project(model=MINI, resolution="480p", duration=5)
        queued = self.scene(project, status=CartoonScene.STATUS_NEW, shot_model=self.models[MINI],
                            shot_resolution="480p", shot_duration=5, shot_aspect="16:9",
                            credits_planned=35, shot_video_credits=28)
        filming = self.scene(project, status=CartoonScene.STATUS_VIDEO, keyframe="cartoon/k/1.png",
                             shot_model=self.models[MINI], shot_resolution="480p", shot_duration=10,
                             shot_aspect="16:9", credits_planned=61, shot_video_credits=54)
        self.scene(project, status=CartoonScene.STATUS_READY, credits_planned=500, shot_duration=5,
                   shot_video_credits=500)
        self.assertEqual(cp.reserved_credits(self.user), 35 + 54)
        self.assertEqual(cp.reserved_credits(self.user, exclude_scene_id=queued.pk), 54)
        # Наценка поменялась во время съёмки — резерв не двигается.
        set_runtime(pricing.KEY_MARKUP_PCT, "100")
        pricing.invalidate_price_caches()
        self.assertEqual(cp.reserved_credits(self.user), 35 + 54)
        del filming

    def test_gate_sees_planned_reserve(self):
        user = _user("gate@example.com", 60)
        project = self.project(model=MINI, resolution="480p", duration=5, user=user)
        first, second = self.scene(project), self.scene(project)
        response, _ = self.render(first, user)
        self.assertEqual(response.status_code, 200, response.content)
        response, delay = self.render(second, user)
        self.assertEqual(response.status_code, 402)
        self.assertEqual((response.json()["required"], response.json()["reserved"]), (35, 35))
        delay.assert_not_called()

    def test_scene_without_snapshot_reads_the_preset(self):
        """Сцена, поставленная до снимков (выкладка во время съёмки), — как раньше."""
        project = self.project()
        scene = self.scene(project, slug="s20-15-720", status=CartoonScene.STATUS_NEW)
        cfg = cp.shot_config(scene)
        self.assertFalse(cfg.snapshot)
        self.assertEqual(cfg.key(), (S20, "720p", 15, "16:9"))
        self.assertTrue(cfg.preset_default)
        self.assertEqual(cp.shot_video_credits(scene), cp.scene_video_credits(self.presets["s20-15-720"],
                                                                              aspect="16:9"))
        self.assertEqual(cp.scene_duration(scene), 15)

    def test_switched_off_model_falls_back_to_the_preset(self):
        project = self.project(model=MINI, resolution="480p", duration=5)
        self.models[MINI].is_active = False
        self.models[MINI].save(update_fields=["is_active"])
        scene = self.scene(project)
        cfg = cp.scene_config(scene)
        self.assertEqual((cfg.model_id, cfg.resolution, cfg.model_available), (S20, "480p", False))
        body = self.client.get(f"/api/cartoon/projects/{project.pk}/").json()
        self.assertFalse(body["effective"]["model_available"])

    def test_queue_resets_prompt_built_for_another_length(self):
        project = self.project(model=MINI, resolution="480p", duration=10)
        scene = self.scene(project, status=CartoonScene.STATUS_FAILED, video_prompt="5 s beats",
                           video_negative="n", keyframe="cartoon/k/1.png")
        self.render(scene)
        self.assertEqual((scene.video_prompt, scene.video_negative, scene.shot_duration), ("", "", 10))
        same = self.scene(self.project(model=MINI, resolution="480p", duration=5),
                          status=CartoonScene.STATUS_FAILED, video_prompt="5 s beats",
                          keyframe="cartoon/k/1.png")
        self.render(same)
        self.assertEqual(same.video_prompt, "5 s beats")


class FeedTests(DockBase):
    def feed(self, client=None, **params):
        response = (client or _client()).get("/api/cartoon/presets/", params)
        self.assertEqual(response.status_code, 200, response.content)
        return response.json()

    def test_without_settings_cards_stay_as_before(self):
        body = self.feed()
        self.assertNotIn("settings", body)
        by_slug = {p["slug"]: p for p in body["presets"]}
        self.assertEqual((by_slug["s20-5-720"]["credits"], by_slug["s20-5-720"]["duration"]), (129, 5))
        self.assertEqual(by_slug["s20-15-720"]["duration"], 15)

    def test_project_settings_price_every_card(self):
        project = self.project("16:9", model=MINI, resolution="480p", duration=5)
        body = self.feed(self.client, project=project.pk)
        by_slug = {p["slug"]: p for p in body["presets"]}
        for slug in ("s20-5-720", "s20-15-720", "s25-10-720", "mini-5-480"):
            self.assertEqual((by_slug[slug]["credits"], by_slug[slug]["duration"]), (35, 5), slug)
        self.assertEqual(body["settings"], {"video_model": MINI, "resolution": "480p", "duration": 5,
                                            "aspect_ratio": "16:9"})
        # Без своей длительности у мультфильма — длительность пресета, в пределах модели.
        project.duration = None
        project.save(update_fields=["duration"])
        by_slug = {p["slug"]: p for p in self.feed(self.client, project=project.pk)["presets"]}
        self.assertEqual((by_slug["s20-15-720"]["credits"], by_slug["s20-15-720"]["duration"]), (88, 15))

    def test_explicit_params_for_guests(self):
        body = self.feed(video_model=MINI, resolution="720p", duration="10", aspect_ratio="9:16")
        self.assertEqual({p["credits"] for p in body["presets"] if p["slug"].startswith("s20")}, {128})
        response = _client().get("/api/cartoon/presets/", {"video_model": MINI, "resolution": "1080p"})
        self.assertEqual((response.status_code, response.json()["error_code"]), (400, "unsupported_resolution"))

    def test_foreign_project_is_not_found(self):
        stranger = _user("other@example.com", 0)
        project = self.project(user=stranger)
        self.assertEqual(self.client.get("/api/cartoon/presets/", {"project": project.pk}).status_code, 404)


class PairVideoTests(DockBase):
    def test_pair_video_is_per_aspect(self):
        preset = self.presets["s20-5-720"]
        CartoonPairVideo.objects.create(preset=preset, character=self.hero, aspect_ratio="9:16",
                                        video="cartoon/scenes/v.mp4")
        CartoonPairVideo.objects.create(preset=preset, character=self.hero, aspect_ratio="16:9",
                                        video="cartoon/scenes/w.mp4")
        tall = _client().get("/api/cartoon/previews/", {"character_id": self.hero.pk,
                                                        "aspect_ratio": "9:16"}).json()
        square = _client().get("/api/cartoon/previews/", {"character_id": self.hero.pk,
                                                          "aspect_ratio": "1:1"}).json()
        self.assertTrue(tall[str(preset.pk)]["video"].endswith("v.mp4"))
        self.assertNotIn(str(preset.pk), square)
        wide = self.project("16:9")
        self.scene(wide)
        row = self.client.get(f"/api/cartoon/projects/{wide.pk}/").json()["scenes"][0]
        self.assertTrue(row["preview_video"].endswith("w.mp4"))
        square_project = self.project("1:1")
        self.scene(square_project)
        row = self.client.get(f"/api/cartoon/projects/{square_project.pk}/").json()["scenes"][0]
        self.assertEqual(row["preview_video"], "")

    def test_preset_default_flag_for_the_pair_rule(self):
        """C2 запоминает ролик пары только со съёмки по настройкам самого пресета."""
        own = self.scene(self.project("16:9"))
        mini = self.scene(self.project("16:9", model=MINI, resolution="480p", duration=5))
        self.assertTrue(cp.scene_config(own).preset_default)
        self.assertFalse(cp.scene_config(mini).preset_default)


class DefaultsAdminTests(DockBase):
    url = "/api/cartoon/manage/defaults/"

    def setUp(self):
        super().setUp()
        self.staff = _client(_user("staff@example.com", 0, staff=True))

    def test_staff_only(self):
        self.assertIn(_client().get(self.url).status_code, (401, 403))
        self.assertEqual(self.client.get(self.url).status_code, 403)
        self.assertEqual(self.client.patch(self.url, {"duration": 10}, format="json").status_code, 403)

    def test_get_shows_effective_and_models(self):
        body = self.staff.get(self.url).json()
        self.assertEqual((body["model"], body["resolution"], body["duration"]), (MINI, "480p", 5))
        self.assertEqual(body["effective"]["source"], "settings")
        self.assertEqual([m["id"] for m in body["models"]][:4], [MINI, FAST, S20, S25])
        self.assertEqual(body["warnings"], [])
        self.assertEqual(body["stored"], {"model": False, "resolution": False, "duration": False})

    def test_patch_validates_saves_and_resets(self):
        r = self.staff.patch(self.url, {"model": S20, "resolution": "1080p", "duration": 8}, format="json")
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual((get_runtime(cp.KEY_DEFAULT_MODEL, ""), get_runtime(cp.KEY_DEFAULT_RESOLUTION, ""),
                          get_runtime(cp.KEY_DEFAULT_DURATION, 0)), (S20, "1080p", 8))
        self.assertEqual(r.json()["effective"], {"video_model": S20, "resolution": "1080p", "duration": 8,
                                                 "source": "settings"})
        r = self.staff.patch(self.url, {"model": MINI}, format="json")
        self.assertEqual(r.status_code, 400)
        self.assertEqual(r.json()["detail"], "Seedance Mini не снимает в качестве 1080p. Доступно: 480p, 720p")
        r = self.staff.patch(self.url, {"model": "google/veo-3.1"}, format="json")
        self.assertEqual(r.status_code, 400)
        r = self.staff.patch(self.url, {"model": "", "resolution": None, "duration": ""}, format="json")
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual((r.json()["model"], r.json()["resolution"], r.json()["duration"]), (MINI, "480p", 5))
        self.assertEqual(r.json()["stored"], {"model": False, "resolution": False, "duration": False})

    def test_warning_when_the_model_is_off(self):
        self.models[MINI].is_active = False
        self.models[MINI].save(update_fields=["is_active"])
        body = self.staff.get(self.url).json()
        self.assertEqual(body["effective"]["source"], "preset")
        self.assertEqual(body["warnings"], ["Новые мультфильмы пока снимаются как в сцене библиотеки: "
                                            "модель Seedance Mini выключена — включите её в «Моделях»"])

    def test_saving_drops_the_models_cache(self):
        _client().get("/api/cartoon/models/")
        self.staff.patch(self.url, {"duration": 10}, format="json")
        self.assertEqual(_client().get("/api/cartoon/models/").json()["defaults"]["duration"], 10)

    def tearDown(self):
        for key in cp.DEFAULT_KEYS:
            delete_runtime(key)


class SceneJsonShotTests(DockBase):
    """C_POLISH: строка ленты показывает то, что спишется, и длину настоящего ролика."""

    def row(self, project, scene) -> dict:
        body = self.client.get(f"/api/cartoon/projects/{project.pk}/").json()
        return next(s for s in body["scenes"] if s["id"] == scene.pk)

    def test_working_scene_shows_the_snapshot_price(self):
        """Ревью R2 W4 / R1 W5: поставлена за 35, потом наценку подняли — лента и бот
        показывали живую цену (48), а спишется снимок (35)."""
        project = self.project(model=MINI, resolution="480p", duration=5)
        scene = self.scene(project)
        response, _ = self.render(scene)
        self.assertEqual(response.status_code, 200, response.content)
        set_runtime("price_markup_pct", "100")
        pricing.invalidate_price_caches()
        row = self.row(project, scene)
        self.assertEqual((row["preset"]["credits"], row["render_credits"], row["shot"]["credits_planned"]),
                         (35, 35, 35))
        self.assertNotIn("price_unavailable", row)
        # Кадр нарисован, идёт видео — всё равно цена снимка.
        CartoonScene.objects.filter(pk=scene.pk).update(status=CartoonScene.STATUS_VIDEO,
                                                        keyframe="cartoon/k/1.png")
        row = self.row(project, scene)
        self.assertEqual((row["preset"]["credits"], row["render_credits"]), (35, 35))
        # Не снимающаяся сцена — по нынешней цене дока.
        other = self.scene(project)
        self.assertGreater(self.row(project, other)["render_credits"], 35)

    def test_ready_scene_shot_before_the_dock_reports_its_clip(self):
        """Ревью R2 W5/W6: снята до дока (снимка нет) — shot по пресету, как её и сняли,
        а не по нынешнему доку."""
        project = self.project(model=MINI, resolution="480p", duration=10)
        scene = self.scene(project, status=CartoonScene.STATUS_READY, video="cartoon/scenes/old.mp4")
        row = self.row(project, scene)
        self.assertEqual(row["config"]["duration"], 10)
        self.assertEqual(row["shot"], {"video_model": S20, "model_name": "Seedance 2.0", "resolution": "720p",
                                       "duration": 5, "aspect_ratio": "16:9", "credits_planned": None})
        draft = self.scene(project)
        self.assertIsNone(self.row(project, draft)["shot"])


class PricingPageTests(DockBase):
    """W8: тарифы — цена сцены нового мультфильма, «от N кр» по настройкам по умолчанию."""

    def test_defaults_in_force(self):
        body = _client().get("/api/cartoon/pricing/").json()
        self.assertEqual((body["scene_min"], body["scene_typical"], body["scene_max"]), (35, 35, 35))
        self.assertEqual((body["settings"]["video_model"], body["settings"]["resolution"],
                          body["settings"]["duration"], body["settings"]["source"]),
                         (MINI, "480p", 5, "settings"))
        # Ровно то, что стоит сцена нового мультфильма в ленте.
        project_id = self.client.post("/api/cartoon/projects/", {"character_id": self.hero.pk},
                                      format="json").json()["id"]
        feed = self.client.get("/api/cartoon/presets/", {"project": project_id}).json()["presets"]
        self.assertEqual(min(p["credits"] for p in feed), body["scene_min"])

    def test_admin_defaults_change_the_page(self):
        set_runtime(cp.KEY_DEFAULT_RESOLUTION, "720p")
        set_runtime(cp.KEY_DEFAULT_DURATION, 10)
        pricing.invalidate_price_caches()
        body = _client().get("/api/cartoon/pricing/").json()
        self.assertEqual(body["scene_min"], cp.scene_price(self.presets["s20-5-720"], model=self.models[MINI],
                                                           resolution="720p", duration=10, aspect="16:9"))
        self.assertEqual((body["settings"]["resolution"], body["settings"]["duration"]), ("720p", 10))

    def test_fallback_when_mini_is_off(self):
        self.models[MINI].is_active = False
        self.models[MINI].save(update_fields=["is_active"])
        pricing.invalidate_price_caches()
        body = _client().get("/api/cartoon/pricing/").json()
        priced = sorted(p for p in (cp.scene_credits_or_none(x) for x in self.presets.values()) if p is not None)
        self.assertEqual((body["scene_min"], body["scene_max"]), (priced[0], priced[-1]))
        self.assertEqual(body["settings"]["source"], "preset")


class LegacyPricingPageTests(PricingPageTests):
    markup = False

    def test_defaults_in_force(self):
        body = _client().get("/api/cartoon/pricing/").json()
        self.assertEqual((body["scene_min"], body["scene_typical"], body["scene_max"]), (37, 37, 37))


class UnpricedDefaultPricingTests(DockBase):
    """C_R1_polish N1: модель по умолчанию предлагается, но себестоимости у неё нет (markup).

    Раньше тарифы отдавали 0/0/0, и бот писал «сцена — от 0 кр». Теперь — цены по
    пресетам, как до настроек по умолчанию, и source=preset.
    """

    def test_unpriced_default_falls_back_to_presets(self):
        from ai import video_cost
        from ai.pricing import PriceUnavailable

        real = video_cost.video_credits

        def mini_unpriced(model, *args, **kwargs):
            ids = {getattr(model, "openrouter_id", ""), getattr(getattr(model, "model", None), "openrouter_id", "")}
            if MINI in ids:
                raise PriceUnavailable(MINI, "cost_unknown")
            return real(model, *args, **kwargs)

        with patch("ai.video_cost.video_credits", side_effect=mini_unpriced):
            pricing.invalidate_price_caches()
            body = _client().get("/api/cartoon/pricing/").json()
            # Модель по умолчанию и правда без цены: иначе тест проверял бы не откат.
            self.assertIsNone(cp.price_or_none(self.presets["s20-5-720"], cp.resolve_config(
                self.presets["s20-5-720"], model=self.models[MINI], resolution="480p", duration=5, aspect="16:9")))
            priced = sorted(p for p in (cp.scene_credits_or_none(x) for x in self.presets.values()) if p is not None)
        self.assertTrue(priced)
        self.assertGreater(body["scene_min"], 0)
        self.assertEqual((body["scene_min"], body["scene_max"]), (priced[0], priced[-1]))
        self.assertEqual((body["settings"]["source"], body["settings"]["model_name"]), ("preset", ""))
        self.assertNotEqual(body["settings"]["video_model"], MINI)

    def test_priced_default_is_not_a_fallback(self):
        body = _client().get("/api/cartoon/pricing/").json()
        self.assertEqual((body["scene_min"], body["settings"]["source"]), (35, "settings"))
