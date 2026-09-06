# -*- coding: utf-8 -*-
"""Деньги при пересъёмке сцены: баланс проверяется ДО задачи, задача — одна.

Провайдеру за генерацию мы платим сразу, а списание идёт в Celery уже после.
Поэтому всё, что стоит денег, обязано отбиваться в самом запросе: и нулевой
баланс, и второе нажатие «Переснять» по той же сцене.
"""
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from ai.models import GPTModels

from .models import CartoonCharacter, CartoonPreset, CartoonProject, CartoonScene

TEST_CACHES = {"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache",
                           "LOCATION": "cartoon-money-tests"}}

# Кадр — 4 кр (коэффициент модели картинки), видео — 5 с × 3 = 15 кр.
FRAME_PRICE = 4
VIDEO_PRICE = 15
FULL_PRICE = FRAME_PRICE + VIDEO_PRICE


def _user(balance: int, email="studio@example.com"):
    User = get_user_model()
    user = User.objects.create_user(email=email, password="x")
    user.token_balance = balance
    user.is_paid = True
    user.save(update_fields=["token_balance", "is_paid"])
    return user


def _client(user):
    client = APIClient()
    client.force_authenticate(user)
    return client


@override_settings(CACHES=TEST_CACHES)
class SceneRetryMoneyTests(TestCase):
    def setUp(self):
        cache.clear()
        image_model = GPTModels.objects.create(
            name="Frame", openrouter_id="test/frame", max_tokens=100,
            markup_coefficient=FRAME_PRICE, category="image")
        video_model = GPTModels.objects.create(
            name="Video", openrouter_id="test/video", max_tokens=100,
            markup_coefficient=3, category="video")
        self.preset = CartoonPreset.objects.create(
            title="Крыша", slug="roof", scene_prompt="The character on a roof",
            image_model=image_model, video_model=video_model, duration=5)
        self.character = CartoonCharacter.objects.create(
            name="Кот", image="cartoon/characters/cat.jpg", is_public=True)

    def _scene(self, user, *, keyframe="", status=CartoonScene.STATUS_FAILED):
        project = CartoonProject.objects.create(user=user, character=self.character)
        return CartoonScene.objects.create(
            project=project, preset=self.preset, keyframe=keyframe, status=status)

    def _retry(self, user, scene, **body):
        with patch("cartoon.views.render_scene.delay") as delay:
            response = _client(user).patch(f"/api/cartoon/scenes/{scene.pk}/",
                                           {"retry": True, **body}, format="json")
        scene.refresh_from_db()
        return response, delay

    def test_price_is_video_only_when_keyframe_is_reused(self):
        """Кадр уже есть — он не перерисовывается, значит и платить за него не за что."""
        user = _user(VIDEO_PRICE)
        scene = self._scene(user, keyframe="cartoon/frames/1.jpg")
        response, delay = self._retry(user, scene)
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(scene.status, CartoonScene.STATUS_NEW)
        delay.assert_called_once_with(scene.pk)

    def test_retry_with_zero_balance_is_rejected_before_the_task(self):
        user = _user(0)
        scene = self._scene(user, keyframe="cartoon/frames/1.jpg")
        response, delay = self._retry(user, scene)
        self.assertEqual(response.status_code, 402, response.data)
        self.assertEqual(response.data["required"], VIDEO_PRICE)
        self.assertEqual(response.data["balance"], 0)
        delay.assert_not_called()
        # Сцена не должна уйти в «Ожидает»: снимать её никто не будет.
        self.assertEqual(scene.status, CartoonScene.STATUS_FAILED)

    def test_new_keyframe_costs_the_full_price(self):
        """Кадр перерисовывается — платится и он: на видео-цену баланса мало."""
        user = _user(VIDEO_PRICE)
        scene = self._scene(user, keyframe="cartoon/frames/1.jpg")
        response, delay = self._retry(user, scene, new_keyframe=True)
        self.assertEqual(response.status_code, 402, response.data)
        self.assertEqual(response.data["required"], FULL_PRICE)
        delay.assert_not_called()
        # Кадр стирать нельзя: съёмка не началась, а без него сцена подорожает.
        self.assertEqual(scene.keyframe, "cartoon/frames/1.jpg")

    def test_scene_without_keyframe_costs_the_full_price(self):
        user = _user(VIDEO_PRICE)
        scene = self._scene(user)
        response, delay = self._retry(user, scene)
        self.assertEqual(response.status_code, 402, response.data)
        self.assertEqual(response.data["required"], FULL_PRICE)
        delay.assert_not_called()

    def test_second_retry_does_not_queue_a_second_task(self):
        """Повторное нажатие по снимающейся сцене — две генерации и два списания."""
        user = _user(1000)
        for status_in_flight in (CartoonScene.STATUS_NEW, CartoonScene.STATUS_KEYFRAME,
                                 CartoonScene.STATUS_VIDEO):
            with self.subTest(status=status_in_flight):
                scene = self._scene(user, keyframe="cartoon/frames/1.jpg",
                                    status=status_in_flight)
                response, delay = self._retry(user, scene)
                self.assertEqual(response.status_code, 200, response.data)
                delay.assert_not_called()
                self.assertEqual(scene.status, status_in_flight)

    def test_in_flight_scene_keeps_its_keyframe(self):
        """«Новый кадр» по снимающейся сцене не должен выбить кадр из-под задачи."""
        user = _user(1000)
        scene = self._scene(user, keyframe="cartoon/frames/1.jpg",
                            status=CartoonScene.STATUS_VIDEO)
        response, delay = self._retry(user, scene, new_keyframe=True)
        self.assertEqual(response.status_code, 200, response.data)
        delay.assert_not_called()
        self.assertEqual(scene.keyframe, "cartoon/frames/1.jpg")

    def test_ready_scene_can_be_re_rendered(self):
        user = _user(1000)
        scene = self._scene(user, keyframe="cartoon/frames/1.jpg",
                            status=CartoonScene.STATUS_READY)
        response, delay = self._retry(user, scene)
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(scene.status, CartoonScene.STATUS_NEW)
        delay.assert_called_once_with(scene.pk)

    def test_other_users_scene_is_not_touched(self):
        owner = _user(1000)
        stranger = _user(1000, email="stranger@example.com")
        scene = self._scene(owner, keyframe="cartoon/frames/1.jpg")
        response, delay = self._retry(stranger, scene)
        self.assertEqual(response.status_code, 404)
        delay.assert_not_called()
