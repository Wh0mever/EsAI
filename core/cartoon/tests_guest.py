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
