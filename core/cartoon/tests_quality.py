# -*- coding: utf-8 -*-
"""Качество сцены: режиссёрский промпт, реплики, связность, честная цена.

Претензия клиента (17.09): «персонажи плохо отрабатывают действия, сцены почти
не развиваются, диалоги и движения передаются некорректно». Причина была в том,
что видеомодель получала одну строку движения — без героя, без реплик и без
разбивки действия. Эти тесты стерегут новый конвейер.
"""
from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings

from ai.models import GPTModels
from cartoon import director, pricing, voiceover
from cartoon.models import CartoonCharacter, CartoonPreset, CartoonProject, CartoonScene

CACHES = {"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache",
                      "LOCATION": "studio-quality-tests"}}


def _models():
    image = GPTModels.objects.create(name="frame", openrouter_id="test/frame", max_tokens=10,
                                     markup_coefficient=Decimal("4"))
    video = GPTModels.objects.create(name="video", openrouter_id="test/video", max_tokens=10,
                                     markup_coefficient=Decimal("21"))
    return image, video


@override_settings(CACHES=CACHES)
class DirectorTests(TestCase):
    def setUp(self):
        image, video = _models()
        self.preset = CartoonPreset.objects.create(
            slug="hol-graduation", title="Выпускной", is_active=True, duration=5,
            scene_prompt="the character throws a graduation cap into the air",
            motion_prompt="the cap spins upward, the character laughs",
            style_prompt="3D cartoon animation style",
            image_model=image, video_model=video)
        self.hero = CartoonCharacter.objects.create(
            name="Котик", image="cartoon/characters/c.png", is_public=True,
            description="a fluffy grey kitten in a beige suit")
        user = get_user_model().objects.create_user(email="d@example.com", password="x-12345678")
        self.project = CartoonProject.objects.create(user=user, character=self.hero)
        self.scene = CartoonScene.objects.create(project=self.project, preset=self.preset, order=0,
                                                 dialogue="Я хочу вернуть доверенность")

    def test_director_gets_hero_action_length_and_line(self):
        captured = {}

        def fake_ask(payload):
            captured["payload"] = payload
            return {"prompt": "0-2s the kitten stands up ...", "negative": "blurry"}

        with patch("cartoon.director._ask", side_effect=fake_ask):
            data = director.compose(self.scene, self.hero, self.preset, 5)

        payload = captured["payload"]
        self.assertIn("a fluffy grey kitten in a beige suit", payload)
        self.assertIn("throws a graduation cap", payload)
        self.assertIn("5 seconds", payload)
        # Реплика уходит дословно — её играет модель, а не пересказывает.
        self.assertIn("Я хочу вернуть доверенность", payload)
        # И бюджет слов, чтобы реплика не обрывалась на полуслове.
        self.assertIn("12 words", payload)
        self.assertIn("blurry", data["negative"])
        self.assertIn("deformed limbs", data["negative"])

    def test_scene_without_line_says_nobody_speaks(self):
        self.scene.dialogue = ""
        with patch("cartoon.director._ask", return_value={"prompt": "p", "negative": ""}) as ask:
            director.compose(self.scene, self.hero, self.preset, 5)
        self.assertIn("does not speak", ask.call_args[0][0])

    def test_prompt_is_built_once_and_survives_retry(self):
        with patch("cartoon.director._ask", return_value={"prompt": "снято", "negative": "n"}) as ask:
            first = director.ensure_video_prompt(self.scene, self.hero, self.preset, 5)
            second = director.ensure_video_prompt(self.scene, self.hero, self.preset, 5)
        self.assertEqual(ask.call_count, 1)
        self.assertEqual(first["prompt"], second["prompt"])
        self.scene.refresh_from_db()
        self.assertEqual(self.scene.video_prompt, "снято")

    def test_model_failure_still_gives_a_usable_prompt(self):
        """Человек уже нажал «снять» — сцена должна сняться, пусть и проще."""
        with patch("cartoon.director._ask", side_effect=director.DirectorFailed("http 500")):
            data = director.ensure_video_prompt(self.scene, self.hero, self.preset, 5)
        self.assertIn("a fluffy grey kitten in a beige suit", data["prompt"])
        self.assertIn("Я хочу вернуть доверенность", data["prompt"])
        self.assertIn("continuous shot", data["prompt"])


@override_settings(CACHES=CACHES)
class PriceTests(TestCase):
    """Платить надо за то, что реально снимут."""

    def setUp(self):
        self.image, self.video = _models()
        self.preset = CartoonPreset.objects.create(
            slug="p", title="Сцена", is_active=True, duration=5, scene_prompt="x",
            image_model=self.image, video_model=self.video)

    def test_price_follows_the_duration_the_model_can_shoot(self):
        # Модель умеет 4/6/8 секунд: пятисекундный пресет снимется за 4.
        with patch("cartoon.pricing.effective_duration", return_value=4):
            self.assertEqual(pricing.video_credits(self.video, 5), 84)
            self.assertEqual(self.preset.estimated_credits(), 88)

    def test_catalog_outage_falls_back_to_the_asked_duration(self):
        with patch("ai.handlers._video_model_params", side_effect=RuntimeError("нет сети")):
            self.assertEqual(pricing.effective_duration(self.video, 5), 5)


@override_settings(CACHES=CACHES)
class ContinuityTests(TestCase):
    """Герой и обстановка не должны меняться от сцены к сцене."""

    def setUp(self):
        image, video = _models()
        self.preset = CartoonPreset.objects.create(
            slug="p", title="Сцена", is_active=True, duration=5, scene_prompt="x",
            image_model=image, video_model=video)
        hero = CartoonCharacter.objects.create(name="Кот", image="cartoon/characters/c.png",
                                               is_public=True)
        user = get_user_model().objects.create_user(email="c@example.com", password="x-12345678")
        self.project = CartoonProject.objects.create(user=user, character=hero)

    def test_next_scene_leans_on_the_end_of_the_previous_one(self):
        from cartoon.services import previous_anchor

        first = CartoonScene.objects.create(project=self.project, preset=self.preset, order=0,
                                            status=CartoonScene.STATUS_READY,
                                            video="cartoon/scenes/1.mp4",
                                            last_frame="cartoon/keyframes/last/1.jpg")
        second = CartoonScene.objects.create(project=self.project, preset=self.preset, order=1)
        self.assertEqual(previous_anchor(second), "cartoon/keyframes/last/1.jpg")
        # У первой сцены опоры нет — она и есть начало истории.
        self.assertEqual(previous_anchor(first), "")


@override_settings(CACHES=CACHES, ELEVENLABS_API_KEY="k")
class DialogueAndVoiceTests(TestCase):
    """Реплику человека не переписывает ни ИИ-сценарист, ни озвучка."""

    def setUp(self):
        image, video = _models()
        self.preset = CartoonPreset.objects.create(
            slug="p", title="Сцена", is_active=True, duration=5, scene_prompt="x",
            image_model=image, video_model=video)
        self.hero = CartoonCharacter.objects.create(name="Кот", image="cartoon/characters/c.png",
                                                    is_public=True, description="a grey cat")
        user = get_user_model().objects.create_user(email="v@example.com", password="x-12345678")
        self.project = CartoonProject.objects.create(user=user, character=self.hero)
        self.with_line = CartoonScene.objects.create(
            project=self.project, preset=self.preset, order=0, dialogue="Вернуть?")
        self.without = CartoonScene.objects.create(project=self.project, preset=self.preset, order=1)

    def test_scene_with_a_written_line_is_not_voiced_twice(self):
        """Такую реплику персонаж уже говорит в кадре — второй голос поверх лишний."""
        voices = [{"id": "m1", "name": "Георгий", "gender": "male"},
                  {"id": "f1", "name": "Лаура", "gender": "female"}]
        with patch("cartoon.audio.list_voices", return_value=voices), \
             patch("cartoon.voiceover.write_lines", return_value={1: "Придумано ИИ"}) as writer:
            plan = voiceover.build_plan(self.project)
        lines = {l["scene_id"]: l["text"] for l in plan["lines"]}
        self.assertNotIn(self.with_line.pk, lines)
        self.assertEqual(lines[self.without.pk], "Придумано ИИ")
        self.assertEqual(plan["spoken_in_video"], 1)
        # Модель спрашивали только про сцену без реплики.
        self.assertEqual(writer.call_count, 1)
        self.assertEqual([s.pk for s in writer.call_args[0][0]], [self.without.pk])


@override_settings(CACHES=CACHES)
class FormatTests(TestCase):
    """Формат выбирается один на весь мультфильм — иначе сцены не склеятся ровно."""

    def setUp(self):
        image, video = _models()
        self.preset = CartoonPreset.objects.create(
            slug="p", title="Сцена", is_active=True, duration=5, scene_prompt="x",
            aspect_ratio="16:9", image_model=image, video_model=video)
        self.hero = CartoonCharacter.objects.create(name="Кот", image="cartoon/characters/c.png",
                                                    is_public=True)
        self.user = get_user_model().objects.create_user(email="f@example.com", password="x-12345678")

    def test_vertical_movie_does_not_reuse_a_horizontal_frame(self):
        from cartoon.models import CartoonKeyframe
        from cartoon.services import get_or_create_keyframe

        CartoonKeyframe.objects.create(preset=self.preset, character=self.hero,
                                       aspect_ratio="16:9", image="cartoon/keyframes/wide.png")
        with patch("cartoon.services.generate_keyframe", return_value="cartoon/keyframes/tall.png") as draw:
            path, price = get_or_create_keyframe(self.preset, self.hero, self.user, "9:16")
        self.assertEqual(path, "cartoon/keyframes/tall.png")
        self.assertEqual(draw.call_args.kwargs.get("aspect"), "9:16")
        self.assertEqual(price, 4)
        # А горизонтальный по-прежнему отдаётся бесплатно из запаса.
        with patch("cartoon.services.generate_keyframe") as again:
            path, price = get_or_create_keyframe(self.preset, self.hero, self.user, "16:9")
        self.assertEqual(path, "cartoon/keyframes/wide.png")
        self.assertEqual(price, 0)
        self.assertEqual(again.call_count, 0)

    def test_changing_the_format_resets_draft_frames(self):
        from rest_framework.test import APIRequestFactory, force_authenticate

        from cartoon.views import ProjectDetailView

        project = CartoonProject.objects.create(user=self.user, character=self.hero,
                                                aspect_ratio="16:9")
        draft = CartoonScene.objects.create(project=project, preset=self.preset, order=0,
                                            keyframe="cartoon/keyframes/wide.png",
                                            video_prompt="старое задание")
        shot = CartoonScene.objects.create(project=project, preset=self.preset, order=1,
                                           status=CartoonScene.STATUS_READY,
                                           keyframe="cartoon/keyframes/wide2.png",
                                           video="cartoon/scenes/1.mp4")
        request = APIRequestFactory().patch("/x/", {"aspect_ratio": "9:16"}, format="json")
        force_authenticate(request, user=self.user)
        response = ProjectDetailView.as_view()(request, pk=project.pk)

        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["aspect_ratio"], "9:16")
        draft.refresh_from_db()
        shot.refresh_from_db()
        # Черновик перерисуется в новом формате, а снятая сцена остаётся как есть:
        # за неё уже заплачено, и при сборке она впишется в общий кадр.
        self.assertEqual(draft.keyframe, "")
        self.assertEqual(draft.video_prompt, "")
        self.assertEqual(shot.keyframe, "cartoon/keyframes/wide2.png")

    def test_unknown_format_falls_back_to_horizontal(self):
        from cartoon.views import _aspect

        self.assertEqual(_aspect("9:16"), "9:16")
        self.assertEqual(_aspect("9х16"), "9:16")  # кириллическое «х»
        self.assertEqual(_aspect("21:9"), "16:9")  # не из трёх наших
        self.assertEqual(_aspect(None), "16:9")
