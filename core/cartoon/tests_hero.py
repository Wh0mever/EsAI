# -*- coding: utf-8 -*-
"""Герой остаётся собой: описание по картинке и перерисовка кадра.

Жалоба клиента: загрузил кота, примерил на сцену «Выпускной» — а в кадре
оказался мужчина в мантии. Причина была в промпте: у загруженного героя нет
описания, и в текст уходило «the main character», то есть «человек вообще».
"""
from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from rest_framework.test import APIRequestFactory, force_authenticate

from ai.models import GPTModels
from cartoon import services
from cartoon.models import (CartoonCharacter, CartoonKeyframe, CartoonPreset, CartoonProject,
                            CartoonScene)
from cartoon.views import SceneDetailView

CACHES = {"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache",
                      "LOCATION": "studio-hero-tests"}}

GRADUATION = ("the character throws a graduation cap into the air, diploma in hand, "
              "classmates cheering, university building behind, bright day")


@override_settings(CACHES=CACHES)
class ScenePromptTests(TestCase):
    def setUp(self):
        model = GPTModels.objects.create(name="m", openrouter_id="test/m", max_tokens=10,
                                         markup_coefficient=Decimal("4"))
        self.preset = CartoonPreset.objects.create(
            slug="hol-graduation", title="Выпускной", is_active=True, duration=5,
            scene_prompt=GRADUATION, style_prompt="3D cartoon animation style",
            image_model=model, video_model=model)

    def test_described_hero_replaces_the_word_character(self):
        cat = CartoonCharacter.objects.create(
            name="Котик", image="cartoon/characters/c.png", is_public=True,
            description="a fluffy grey kitten with green eyes")
        prompt = services.build_scene_prompt(self.preset, cat)
        self.assertIn("a fluffy grey kitten with green eyes throws a graduation cap", prompt)
        # В описании сцены слова «character» остаться не должно.
        self.assertNotIn("character", prompt.split("3D cartoon animation style")[0].lower())

    def test_hero_without_description_points_at_the_reference(self):
        """Иначе модель рисует «человека вообще» вместо загруженного героя."""
        hero = CartoonCharacter.objects.create(name="13209910", image="cartoon/characters/u.png")
        prompt = services.build_scene_prompt(self.preset, hero)
        self.assertIn("the character from the reference image throws", prompt)
        self.assertIn("Never replace the character with a human", prompt)


@override_settings(CACHES=CACHES)
class DescribeHeroTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(email="h@example.com", password="x-12345678")
        self.hero = CartoonCharacter.objects.create(
            user=self.user, name="13209910", image="cartoon/characters/u.png",
            source=CartoonCharacter.SOURCE_UPLOAD)
        model = GPTModels.objects.create(name="m", openrouter_id="test/m", max_tokens=10,
                                         markup_coefficient=Decimal("4"))
        self.preset = CartoonPreset.objects.create(
            slug="hol-graduation", title="Выпускной", is_active=True, duration=5,
            scene_prompt=GRADUATION, image_model=model, video_model=model)

    def test_description_is_written_once_and_file_name_becomes_a_name(self):
        described = {"description": "a fluffy grey kitten in a red scarf", "name": "Котик"}
        stale = CartoonKeyframe.objects.create(preset=self.preset, character=self.hero,
                                               image="cartoon/keyframes/old.png")
        with patch("cartoon.services.describe_character", return_value=described) as ask:
            services.ensure_description(self.hero)
        self.hero.refresh_from_db()
        self.assertEqual(self.hero.description, described["description"])
        self.assertEqual(self.hero.name, "Котик")
        # Кадры, нарисованные без описания, неправильные — их больше нет.
        self.assertFalse(CartoonKeyframe.objects.filter(pk=stale.pk).exists())

        # Второй раз модель не спрашиваем: описание уже есть.
        with patch("cartoon.services.describe_character", return_value=described) as again:
            services.ensure_description(self.hero)
        self.assertEqual(ask.call_count, 1)
        self.assertEqual(again.call_count, 0)

    def test_human_name_is_kept(self):
        hero = CartoonCharacter.objects.create(
            user=self.user, name="Кот-супергерой", image="cartoon/characters/x.png")
        with patch("cartoon.services.describe_character",
                   return_value={"description": "a ginger cat", "name": "Рыжик"}):
            services.ensure_description(hero)
        hero.refresh_from_db()
        self.assertEqual(hero.name, "Кот-супергерой")
        self.assertEqual(hero.description, "a ginger cat")

    def test_failure_to_describe_does_not_break_anything(self):
        with patch("cartoon.services.describe_character", side_effect=RuntimeError("http 500")):
            services.ensure_description(self.hero)
        self.hero.refresh_from_db()
        self.assertEqual(self.hero.description, "")


@override_settings(CACHES=CACHES)
class RedrawFrameTests(TestCase):
    """Неудачный кадр раньше нельзя было заменить, не удалив сцену."""

    def setUp(self):
        model = GPTModels.objects.create(name="m", openrouter_id="test/m", max_tokens=10,
                                         markup_coefficient=Decimal("4"))
        self.preset = CartoonPreset.objects.create(
            slug="hol-graduation", title="Выпускной", is_active=True, duration=5,
            scene_prompt=GRADUATION, image_model=model, video_model=model)
        self.user = get_user_model().objects.create_user(email="r@example.com", password="x-12345678")
        self.hero = CartoonCharacter.objects.create(user=self.user, name="Котик",
                                                    image="cartoon/characters/u.png")
        self.project = CartoonProject.objects.create(user=self.user, character=self.hero)
        self.scene = CartoonScene.objects.create(project=self.project, preset=self.preset, order=0,
                                                 keyframe="cartoon/keyframes/wrong.png")

    def _patch(self, body):
        request = APIRequestFactory().patch("/x/", body, format="json")
        force_authenticate(request, user=self.user)
        return SceneDetailView.as_view()(request, pk=self.scene.pk)

    def test_new_keyframe_clears_the_frame_and_the_shared_cache(self):
        cached = CartoonKeyframe.objects.create(preset=self.preset, character=self.hero,
                                                image="cartoon/keyframes/wrong.png")
        with patch("cartoon.views.render_scene.delay") as render:
            response = self._patch({"new_keyframe": True})
        self.assertEqual(response.status_code, 200, response.data)
        self.scene.refresh_from_db()
        self.assertEqual(self.scene.keyframe, "")
        self.assertEqual(self.scene.status, CartoonScene.STATUS_DRAFT)
        self.assertFalse(CartoonKeyframe.objects.filter(pk=cached.pk).exists())
        # Перерисовка кадра не запускает съёмку и ничего не списывает.
        self.assertEqual(render.call_count, 0)

    def test_frame_of_a_scene_being_filmed_is_not_touched(self):
        self.scene.status = CartoonScene.STATUS_VIDEO
        self.scene.save(update_fields=["status"])
        response = self._patch({"new_keyframe": True})
        self.assertEqual(response.status_code, 400)
        self.scene.refresh_from_db()
        self.assertEqual(self.scene.keyframe, "cartoon/keyframes/wrong.png")
