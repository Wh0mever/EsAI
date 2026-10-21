"""Резерв идущей склейки видят и гейты, которые складывают резервы сами:
съёмка сцены мультстудии, видео в чате и в боте, задача медиа (/api/ai/jobs/).

Без этого склейка (20 кр в резерве) и съёмка проходили проверку по одному и
тому же балансу: сцена списывала своё, а склейке оставался огрызок.
"""
from __future__ import annotations

from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from ai.models import AiChatSession, GPTModels
from ai.tests_audit_video import CFG, PARAMS, TEST_CACHES, _Patched, _patches, _resp
from cartoon.models import CartoonCharacter, CartoonPreset, CartoonProject, CartoonScene
from merge.models import MergeProject
from vstudio.reserve import merge_reserved

MERGE_RESERVE = 20


def _user(balance: int, email: str):
    user = get_user_model().objects.create_user(email=email, password="x")
    user.token_balance = balance
    user.is_paid = True
    user.save(update_fields=["token_balance", "is_paid"])
    return user


def _running_merge(user, credits: int = MERGE_RESERVE) -> MergeProject:
    return MergeProject.objects.create(user=user, title="Склейка", status=MergeProject.STATUS_RENDERING,
                                       credits_reserved=credits)


def _client(user) -> APIClient:
    client = APIClient()
    client.force_authenticate(user)
    return client


class MergeReservedHelperTests(TestCase):
    def test_counts_only_active_merges_of_this_user(self):
        user, other = _user(100, "a@example.com"), _user(100, "b@example.com")
        _running_merge(user)
        MergeProject.objects.create(user=user, title="Готовая", status=MergeProject.STATUS_READY,
                                    credits_reserved=0, credits_charged=20)
        _running_merge(other, 50)
        self.assertEqual(merge_reserved(user), MERGE_RESERVE)
        self.assertEqual(merge_reserved(None), 0)


@override_settings(CACHES=TEST_CACHES)
class CartoonSceneGateTests(TestCase):
    """cartoon.views._queue_render: кадр есть — сцена стоит 15 кр (5 с × 3)."""

    VIDEO_PRICE = 15

    def setUp(self):
        cache.clear()
        image = GPTModels.objects.create(name="Frame", openrouter_id="test/frame", max_tokens=100,
                                         markup_coefficient=4, category="image")
        video = GPTModels.objects.create(name="Video", openrouter_id="test/video", max_tokens=100,
                                         markup_coefficient=3, category="video")
        self.preset = CartoonPreset.objects.create(title="Крыша", slug="roof", scene_prompt="x",
                                                   image_model=image, video_model=video, duration=5)
        self.character = CartoonCharacter.objects.create(name="Кот", image="cartoon/characters/cat.jpg",
                                                         is_public=True)

    def _retry(self, user):
        project = CartoonProject.objects.create(user=user, character=self.character)
        scene = CartoonScene.objects.create(project=project, preset=self.preset,
                                            keyframe="cartoon/frames/1.jpg",
                                            status=CartoonScene.STATUS_FAILED)
        with patch("cartoon.views.render_scene.delay") as delay, \
                self.captureOnCommitCallbacks(execute=True):
            response = _client(user).patch(f"/api/cartoon/scenes/{scene.pk}/", {"retry": True},
                                           format="json")
        return response, delay

    def test_running_merge_holds_its_price(self):
        user = _user(self.VIDEO_PRICE + MERGE_RESERVE - 1, "scene@example.com")
        _running_merge(user)
        response, delay = self._retry(user)
        self.assertEqual(response.status_code, 402, response.data)
        delay.assert_not_called()

    def test_enough_for_both_passes(self):
        user = _user(self.VIDEO_PRICE + MERGE_RESERVE, "scene2@example.com")
        _running_merge(user)
        response, delay = self._retry(user)
        self.assertEqual(response.status_code, 200, response.data)
        delay.assert_called_once()


@override_settings(CACHES=TEST_CACHES)
class ChatVideoGateTests(TestCase):
    """ai.generation (чат, бот) и /api/ai/jobs/: ролик стоит 210 кр (5 с × 42)."""

    NEED = 210

    def setUp(self):
        cache.clear()
        self.user = _user(self.NEED + MERGE_RESERVE - 1, "chat@example.com")
        self.model = GPTModels.objects.create(
            name="Seedance", openrouter_id="bytedance/seedance-2.5", max_tokens=1000,
            markup_coefficient=42, category="video", is_active=True)
        self.session = AiChatSession.objects.create(user=self.user, title="Видео")
        _running_merge(self.user)

    def _generate(self, source: str):
        from ai.generation import run_video_generation

        with patch("ai.handlers._release_daily_request") as release, \
                _Patched(_patches(lambda *a, **kw: self.fail("не должно уйти провайдеру"),
                                  lambda *a, **kw: _resp())):
            frames = list(run_video_generation(
                user=self.user, model_obj=self.model, selected_model_name=self.model.openrouter_id,
                message="кот на пляже", attachments=[], origin_base="https://esai.kg",
                session=self.session, source=source))
        release.assert_called_once()
        return frames[-1]

    def test_chat_and_bot_refuse(self):
        for source in ("chat", "bot"):
            with self.subTest(source=source):
                last = self._generate(source)
                self.assertEqual(last["error_code"], "insufficient_balance")
                self.assertEqual(last["reserved_credits"], MERGE_RESERVE)

    def test_job_create_view_refuses(self):
        from ai.models import GenerationJob

        with patch("ai.handlers._video_model_params", return_value=PARAMS), \
                patch("ai.handlers._openrouter_config", return_value=CFG), \
                patch("ai.tasks.run_generation_job.apply_async") as enqueue:
            response = _client(self.user).post("/api/ai/jobs/", {"message": "кот",
                                                                 "model": self.model.openrouter_id},
                                               format="json")
        self.assertEqual(response.status_code, 402, response.data)
        self.assertEqual(response.data["error_code"], "insufficient_balance")
        self.assertEqual(response.data["reserved_credits"], MERGE_RESERVE)
        enqueue.assert_not_called()
        self.assertFalse(GenerationJob.objects.exists())
