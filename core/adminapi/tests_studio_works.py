# -*- coding: utf-8 -*-
"""Работы пользователей: свои персонажи не пускаются ни в рекламу, ни в библиотеку."""
from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from rest_framework.test import APIRequestFactory, force_authenticate

from adminapi.studio_works import StudioWorkFeatureView, StudioWorkSetPreviewView, StudioWorksView
from ai.models import GPTModels
from cartoon.models import CartoonCharacter, CartoonPreset, CartoonProject, CartoonScene

CACHES = {"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache",
                      "LOCATION": "studio-works-tests"}}


@override_settings(CACHES=CACHES)
class StudioWorksTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.staff = User.objects.create_user(email="admin@example.com", password="x-12345678", is_staff=True)
        self.user = User.objects.create_user(email="author@example.com", password="x-12345678")
        model = GPTModels.objects.create(name="m", openrouter_id="test/m", max_tokens=10,
                                         markup_coefficient=Decimal("4"))
        self.preset = CartoonPreset.objects.create(
            slug="w-scene", title="Сцена", is_active=True, scene_prompt="x",
            image_model=model, video_model=model, preview_video="cartoon/previews/old.mp4")
        self.lib = CartoonCharacter.objects.create(name="Кот", image="cartoon/characters/c.png", is_public=True)
        self.mine = CartoonCharacter.objects.create(name="Мой сын", image="cartoon/characters/m.png",
                                                    user=self.user)

    def _scene(self, hero, **kw):
        project = CartoonProject.objects.create(user=self.user, character=self.lib)
        return CartoonScene.objects.create(project=project, preset=self.preset, character=hero, order=0,
                                           status=CartoonScene.STATUS_READY, video="cartoon/scenes/v.mp4",
                                           keyframe="cartoon/keyframes/k.png", **kw)

    def _call(self, view, method="post", path="/x/", data=None, **kwargs):
        factory = APIRequestFactory()
        request = getattr(factory, method)(path, data or {}, format="json")
        force_authenticate(request, user=self.staff)
        return view.as_view()(request, **kwargs)

    def test_list_marks_own_characters_as_not_public(self):
        self._scene(self.lib)
        self._scene(self.mine)
        data = self._call(StudioWorksView, "get", "/w/").data
        self.assertEqual(data["count"], 2)
        by_hero = {r["hero"]["name"]: r for r in data["results"]}
        self.assertTrue(by_hero["Кот"]["public_ok"])
        self.assertFalse(by_hero["Мой сын"]["public_ok"])
        public = self._call(StudioWorksView, "get", "/w/?show=public").data
        self.assertEqual([r["hero"]["name"] for r in public["results"]], ["Кот"])

    def test_feature_refuses_own_character(self):
        ok = self._scene(self.lib)
        own = self._scene(self.mine)
        self.assertEqual(self._call(StudioWorkFeatureView, kind="scene", pk=ok.pk).status_code, 200)
        self.assertEqual(self._call(StudioWorkFeatureView, kind="scene", pk=own.pk).status_code, 400)
        ok.refresh_from_db(); own.refresh_from_db()
        self.assertIsNotNone(ok.featured_at)
        self.assertIsNone(own.featured_at)

    def test_movie_with_any_own_scene_is_refused(self):
        project = CartoonProject.objects.create(user=self.user, character=self.lib,
                                                result_video="cartoon/movies/m.mp4")
        CartoonScene.objects.create(project=project, preset=self.preset, character=self.mine, order=0,
                                    status=CartoonScene.STATUS_READY, video="cartoon/scenes/v.mp4")
        response = self._call(StudioWorkFeatureView, kind="movie", pk=project.pk)
        self.assertEqual(response.status_code, 400)

    def test_set_preview_swaps_library_video_only_for_library_hero(self):
        own = self._scene(self.mine)
        self.assertEqual(self._call(StudioWorkSetPreviewView, pk=own.pk).status_code, 400)
        custom = self._scene(self.lib, custom_text="прыгает")
        self.assertEqual(self._call(StudioWorkSetPreviewView, pk=custom.pk).status_code, 400)

        ok = self._scene(self.lib)
        with patch("django.core.files.storage.default_storage.open", side_effect=FileNotFoundError):
            response = self._call(StudioWorkSetPreviewView, pk=ok.pk)
        self.assertEqual(response.status_code, 200, response.data)
        self.preset.refresh_from_db()
        self.assertEqual(self.preset.preview_video.name, "cartoon/scenes/v.mp4")
        self.assertEqual(self.preset.preview_poster.name, "cartoon/keyframes/k.png")
