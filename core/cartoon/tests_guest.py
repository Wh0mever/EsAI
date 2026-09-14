# -*- coding: utf-8 -*-
"""Гостевой режим студии: бесплатная примерка и перенос ленты после входа.

Рисование кадра подменено: проверяем лимиты, деньги и перенос, а не модель.
"""
from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase, override_settings
from rest_framework.test import APIRequestFactory, force_authenticate

from ai.models import GPTModels
from cartoon.models import (CartoonCharacter, CartoonGuestTryOn, CartoonKeyframe,
                            CartoonPreset, CartoonProject)
from cartoon.views import PresetTryOnView, ProjectImportView

CACHES = {"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache",
                      "LOCATION": "studio-guest-tests"}}
DEVICE = "d" * 32


def _model(name):
    return GPTModels.objects.create(name=name, openrouter_id=f"test/{name}", max_tokens=1000,
                                    markup_coefficient=Decimal("4"))


@override_settings(CACHES=CACHES, STUDIO_GUEST_TRYON_DAILY_CAP=100,
                   STUDIO_GUEST_TRYON_PER_IP_DAY=3)
class GuestTryOnTests(TestCase):
    def setUp(self):
        cache.clear()
        self.image_model = _model("img")
        video_model = _model("vid")
        self.presets = [
            CartoonPreset.objects.create(
                slug=f"scene-{i}", title=f"Сцена {i}", is_active=True, scene_prompt="x",
                image_model=self.image_model, video_model=video_model)
            for i in range(4)
        ]
        self.hero = CartoonCharacter.objects.create(
            name="Кот", image="cartoon/characters/cat.png", is_public=True)

    def _post(self, preset, *, device=DEVICE, ip="10.0.0.1", user=None):
        request = APIRequestFactory().post(
            f"/try-on/", {"character_id": self.hero.pk}, format="json",
            HTTP_X_DEVICE_KEY=device, REMOTE_ADDR=ip)
        if user:
            force_authenticate(request, user=user)
        return PresetTryOnView.as_view()(request, pk=preset.pk)

    def _fake_draw(self):
        def draw(preset, character, user=None):
            path = f"cartoon/keyframes/{preset.pk}-{character.pk}.png"
            CartoonKeyframe.objects.get_or_create(
                preset=preset, character=character, defaults={"image": path})
            return path, (0 if user is None else 4)
        return patch("cartoon.services.get_or_create_keyframe", side_effect=draw)

    def test_first_try_is_free_second_needs_login(self):
        with self._fake_draw() as draw:
            first = self._post(self.presets[0])
            second = self._post(self.presets[1])
        self.assertEqual(first.status_code, 200, first.data)
        self.assertTrue(first.data["free"])
        self.assertEqual(first.data["charged"], 0)
        self.assertEqual(second.status_code, 403)
        self.assertTrue(second.data["need_auth"])
        self.assertEqual(second.data["reason"], "used")
        self.assertEqual(draw.call_count, 1)
        # Бесплатный кадр рисуется без пользователя — ни с кого не списывается.
        self.assertIsNone(draw.call_args.kwargs.get("user"))

    def test_ready_pair_is_free_and_does_not_spend_the_try(self):
        CartoonKeyframe.objects.create(preset=self.presets[0], character=self.hero,
                                       image="cartoon/keyframes/ready.png")
        with self._fake_draw() as draw:
            ready = self._post(self.presets[0])
            fresh = self._post(self.presets[1])
        self.assertEqual(ready.status_code, 200)
        self.assertNotIn("free", ready.data)
        self.assertEqual(fresh.status_code, 200)
        self.assertTrue(fresh.data["free"])
        self.assertEqual(draw.call_count, 1)

    def test_without_device_key_nothing_is_free(self):
        with self._fake_draw() as draw:
            response = self._post(self.presets[0], device="")
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.data["reason"], "no_device")
        self.assertEqual(draw.call_count, 0)

    def test_ip_limit_per_day(self):
        # Сцены разные: уже нарисованная пара отдаётся даром и лимит не тратит.
        with self._fake_draw():
            codes = [self._post(self.presets[i], device=f"{i}" * 32).status_code
                     for i in range(4)]
        self.assertEqual(codes, [200, 200, 200, 403])

    @override_settings(STUDIO_GUEST_TRYON_DAILY_CAP=2)
    def test_daily_cap_for_everyone(self):
        with self._fake_draw():
            codes = [self._post(self.presets[i % 3], device=f"{i}" * 32, ip=f"10.0.0.{i}").status_code
                     for i in range(3)]
        self.assertEqual(codes, [200, 200, 403])

    def test_failed_draw_does_not_spend_the_try(self):
        with patch("cartoon.services.get_or_create_keyframe", side_effect=RuntimeError("модель легла")):
            failed = self._post(self.presets[0])
        self.assertEqual(failed.status_code, 502)
        self.assertFalse(CartoonGuestTryOn.objects.exists())
        with self._fake_draw():
            retry = self._post(self.presets[0])
        self.assertEqual(retry.status_code, 200)

    def test_logged_in_user_still_pays(self):
        user = get_user_model().objects.create_user(email="u@example.com", password="x-12345678")
        user.token_balance = 0
        user.save(update_fields=["token_balance"])
        with self._fake_draw() as draw:
            response = self._post(self.presets[0], user=user)
        self.assertEqual(response.status_code, 402)
        self.assertEqual(draw.call_count, 0)


@override_settings(CACHES=CACHES)
class PairVideoTests(TestCase):
    """Ролик пары: библиотечный герой — в общий запас, свой персонаж — нет."""

    def setUp(self):
        image_model = _model("img3")
        video_model = _model("vid3")
        self.preset = CartoonPreset.objects.create(
            slug="pair-scene", title="Сцена", is_active=True, scene_prompt="x",
            image_model=image_model, video_model=video_model)
        self.hero = CartoonCharacter.objects.create(
            name="Кот", image="cartoon/characters/cat.png", is_public=True)
        self.user = get_user_model().objects.create_user(email="p@example.com", password="x-12345678")
        self.mine = CartoonCharacter.objects.create(
            name="Мой", image="cartoon/characters/mine.png", user=self.user)

    def _ready_scene(self, character):
        from cartoon.models import CartoonScene

        project = CartoonProject.objects.create(user=self.user, character=character)
        return CartoonScene.objects.create(
            project=project, preset=self.preset, order=0,
            status=CartoonScene.STATUS_READY, video="cartoon/scenes/x.mp4")

    def _remember(self, scene):
        from cartoon.services import remember_pair_video

        with patch("django.core.files.storage.default_storage.open",
                   side_effect=FileNotFoundError("в тесте файлов нет")):
            return remember_pair_video(scene)

    def test_library_hero_goes_to_shared_stock_once(self):
        from cartoon.models import CartoonPairVideo

        self.assertTrue(self._remember(self._ready_scene(self.hero)))
        self.assertFalse(self._remember(self._ready_scene(self.hero)))
        row = CartoonPairVideo.objects.get()
        self.assertEqual((row.preset_id, row.character_id), (self.preset.pk, self.hero.pk))
        # Лёгкая копия не сделалась — ролик всё равно в запасе, покажется оригинал.
        self.assertEqual(row.clip, "")

    def test_users_own_character_never_shared(self):
        from cartoon.models import CartoonPairVideo

        self.assertFalse(self._remember(self._ready_scene(self.mine)))
        self.assertFalse(CartoonPairVideo.objects.exists())

    def test_previews_endpoint_and_scene_json_show_the_video(self):
        from cartoon.models import CartoonPairVideo, CartoonScene
        from cartoon.views import PreviewsView, project_json

        CartoonPairVideo.objects.create(preset=self.preset, character=self.hero,
                                        video="cartoon/scenes/x.mp4", clip="cartoon/pairs/x.mp4")
        CartoonKeyframe.objects.create(preset=self.preset, character=self.hero,
                                       image="cartoon/keyframes/k.png")
        request = APIRequestFactory().get(f"/previews/?character_id={self.hero.pk}")
        data = PreviewsView.as_view()(request).data
        self.assertTrue(data[str(self.preset.pk)]["video"].endswith("pairs/x.mp4"))
        self.assertTrue(data[str(self.preset.pk)]["frame"].endswith("k.png"))

        project = CartoonProject.objects.create(user=self.user, character=self.hero)
        CartoonScene.objects.create(project=project, preset=self.preset, order=0)
        scene = project_json(project)["scenes"][0]
        self.assertTrue(scene["preview_video"].endswith("pairs/x.mp4"))


@override_settings(CACHES=CACHES)
class CustomSceneTests(TestCase):
    """Своя сцена: описание → служебный пресет, отдельный кадр, мимо общих запасов."""

    def setUp(self):
        self.image_model = _model("img4")
        self.video_model = _model("vid4")
        self.library = CartoonPreset.objects.create(
            slug="lib-scene", title="Библиотека", is_active=True, scene_prompt="x",
            image_model=self.image_model, video_model=self.video_model,
            preview_video="cartoon/previews/lib.mp4")
        self.hero = CartoonCharacter.objects.create(
            name="Кот", image="cartoon/characters/cat.png", is_public=True,
            description="a ginger cat in a blue cape")
        self.user = get_user_model().objects.create_user(email="c@example.com", password="x-12345678")
        self.user.token_balance = 1000
        self.user.save(update_fields=["token_balance"])
        self.project = CartoonProject.objects.create(user=self.user, character=self.hero)

    def _add(self, body):
        from cartoon.views import ProjectScenesView

        request = APIRequestFactory().post("/scenes/", body, format="json")
        force_authenticate(request, user=self.user)
        return ProjectScenesView.as_view()(request, pk=self.project.pk)

    def test_text_scene_lands_as_draft_on_hidden_preset(self):
        from cartoon.services import CUSTOM_PRESET_SLUG
        from cartoon.views import PresetsView

        response = self._add({"custom_text": "катается на скейте по ночному городу",
                              "character_id": self.hero.pk})
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(response.data["status"], "draft")
        self.assertEqual(response.data["custom_text"], "катается на скейте по ночному городу")
        self.assertEqual(response.data["preview_video"], "")
        self.assertEqual(response.data["keyframe"], "")
        slugs = [p["slug"] for p in PresetsView.as_view()(APIRequestFactory().get("/p/")).data["presets"]]
        self.assertNotIn(CUSTOM_PRESET_SLUG, slugs)
        # Служебный пресет нельзя добавить как обычную сцену.
        from cartoon.models import CartoonPreset as P
        base = P.objects.get(slug=CUSTOM_PRESET_SLUG)
        self.assertEqual(self._add({"preset_id": base.pk}).status_code, 400)

    def test_too_short_or_long_description_refused(self):
        self.assertEqual(self._add({"custom_text": "ы"}).status_code, 400)
        self.assertEqual(self._add({"custom_text": "а" * 301}).status_code, 400)

    def _fake_llm(self, payload):
        import json as _json
        from unittest.mock import MagicMock

        resp = MagicMock(status_code=200)
        resp.json.return_value = {"choices": [{"message": {"content": _json.dumps(payload)}}]}
        return patch("cartoon.services.requests.post", return_value=resp)

    def test_render_uses_formed_prompt_and_skips_shared_stock(self):
        from cartoon.models import CartoonPairVideo, CartoonScene
        from cartoon.tasks import render_scene

        scene = CartoonScene.objects.get(pk=self._add({
            "custom_text": "катается на скейте", "character_id": self.hero.pk}).data["id"])
        seen = {}

        def fake_frame(preset, character):
            seen["frame_prompt"] = preset.scene_prompt
            return "cartoon/keyframes/custom.png"

        def fake_video(preset, keyframe):
            seen["motion"] = preset.motion_prompt
            return "cartoon/scenes/custom.mp4"

        with self._fake_llm({"ok": True, "title": "Скейт", "scene": "The character rides a skateboard at night.",
                             "motion": "Camera follows the character."}), \
             patch("cartoon.services.generate_keyframe", side_effect=fake_frame), \
             patch("cartoon.tasks.generate_scene_video", side_effect=fake_video):
            result = render_scene.apply(args=[scene.pk]).get()
        self.assertEqual(result["status"], "ready", result)
        scene.refresh_from_db()
        self.assertEqual(seen["frame_prompt"], "The character rides a skateboard at night.")
        self.assertEqual(seen["motion"], "Camera follows the character.")
        self.assertEqual(scene.custom_title, "Скейт")
        self.assertGreater(scene.credits_spent, 0)
        # Ни общего кадра, ни ролика пары у своей сцены быть не должно.
        self.assertFalse(CartoonKeyframe.objects.filter(preset=scene.preset).exists())
        self.assertFalse(CartoonPairVideo.objects.exists())

    def test_rejected_description_costs_nothing(self):
        from cartoon.models import CartoonScene
        from cartoon.tasks import render_scene

        scene = CartoonScene.objects.get(pk=self._add({
            "custom_text": "что-то недопустимое", "character_id": self.hero.pk}).data["id"])
        with self._fake_llm({"ok": False, "reason": "Такую сцену снять нельзя"}), \
             patch("cartoon.services.generate_keyframe") as frame:
            result = render_scene.apply(args=[scene.pk]).get()
        self.assertEqual(result["status"], "custom_rejected")
        scene.refresh_from_db()
        self.assertEqual(scene.status, "failed")
        self.assertEqual(scene.credits_spent, 0)
        self.assertEqual(frame.call_count, 0)

    def test_import_keeps_text_scene(self):
        response = ProjectImportView.as_view()(self._import_request({
            "draft_id": "custom-draft", "character_id": self.hero.pk,
            "scenes": [{"preset_id": 0, "custom_text": "прыгает с парашютом", "character_id": self.hero.pk},
                       {"preset_id": self.library.pk}]}))
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual([s["custom_text"] for s in response.data["scenes"]], ["прыгает с парашютом", ""])

    def _import_request(self, body):
        request = APIRequestFactory().post("/import/", body, format="json")
        force_authenticate(request, user=self.user)
        return request


@override_settings(CACHES=CACHES)
class DraftImportTests(TestCase):
    def setUp(self):
        image_model = _model("img2")
        video_model = _model("vid2")
        self.presets = [
            CartoonPreset.objects.create(
                slug=f"s-{i}", title=f"С {i}", is_active=True, scene_prompt="x",
                image_model=image_model, video_model=video_model)
            for i in range(3)
        ]
        self.hero = CartoonCharacter.objects.create(
            name="Кот", image="cartoon/characters/cat.png", is_public=True)
        self.dog = CartoonCharacter.objects.create(
            name="Пёс", image="cartoon/characters/dog.png", is_public=True)
        self.user = get_user_model().objects.create_user(email="g@example.com", password="x-12345678")
        CartoonKeyframe.objects.create(preset=self.presets[1], character=self.dog,
                                       image="cartoon/keyframes/dog-1.png")

    def _import(self, body, user=None):
        request = APIRequestFactory().post("/import/", body, format="json")
        force_authenticate(request, user=user or self.user)
        return ProjectImportView.as_view()(request)

    def test_draft_becomes_project_with_scenes_in_order(self):
        body = {"draft_id": "draft-1", "character_id": self.hero.pk, "scenes": [
            {"preset_id": self.presets[2].pk, "character_id": None},
            {"preset_id": self.presets[1].pk, "character_id": self.dog.pk},
            {"preset_id": 999999},
        ]}
        response = self._import(body)
        self.assertEqual(response.status_code, 201, response.data)
        scenes = response.data["scenes"]
        self.assertEqual([s["preset"]["id"] for s in scenes],
                         [self.presets[2].pk, self.presets[1].pk])
        self.assertTrue(all(s["status"] == "draft" and s["credits_spent"] == 0 for s in scenes))
        self.assertEqual(scenes[1]["character"]["id"], self.dog.pk)
        # Готовый кадр пары «пёс + сцена» подставился сразу.
        self.assertTrue(scenes[1]["keyframe"].endswith("dog-1.png"))

    def test_repeated_import_returns_same_project(self):
        body = {"draft_id": "draft-2", "character_id": self.hero.pk,
                "scenes": [{"preset_id": self.presets[0].pk}]}
        first = self._import(body)
        second = self._import(body)
        self.assertEqual(second.status_code, 200)
        self.assertEqual(first.data["id"], second.data["id"])
        self.assertEqual(CartoonProject.objects.filter(user=self.user).count(), 1)

    def test_someone_elses_character_is_not_taken(self):
        stranger = get_user_model().objects.create_user(email="s@example.com", password="x-12345678")
        private = CartoonCharacter.objects.create(
            name="Чужой", image="cartoon/characters/x.png", user=stranger)
        response = self._import({"draft_id": "d3", "character_id": private.pk,
                                 "scenes": [{"preset_id": self.presets[0].pk}]})
        self.assertEqual(response.status_code, 400)
