# -*- coding: utf-8 -*-
"""Цена сцены мультфильма из админки (просьба владельца продукта: 164 → 200 кредитов).

Тариф видеомодели — это ещё и цена видео в чате, поэтому у мультфильмов своя
цена: studio_scene_credits за пятисекундную сцену, короткие — пропорционально.
"""
from unittest.mock import patch

from django.test import TestCase, override_settings

from ai.models import GPTModels
from cartoon.models import CartoonPreset
from cartoon.pricing import scene_credits

CACHES = {"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache",
                      "LOCATION": "scene-price-tests"}}


@override_settings(CACHES=CACHES)
class ScenePriceTests(TestCase):
    def setUp(self):
        self.image = GPTModels.objects.create(name="Nano Banana", openrouter_id="google/gemini-2.5-flash-image",
                                              max_tokens=100, markup_coefficient=4, category="image")
        self.video = GPTModels.objects.create(name="Seedance 2.0", openrouter_id="bytedance/seedance-2.0",
                                              max_tokens=100, markup_coefficient=32, category="video")
        # Каталог провайдера не нужен: длительность и качество — как попросили,
        # себестоимость неизвестна (граница проверяется в ai.tests_video_cost).
        for target, value in (("ai.handlers._video_model_params",
                               lambda model, cfg, dur, res: {"duration": dur, "resolution": res}),
                              ("ai.handlers._openrouter_video_catalog", lambda model: {}),
                              ("ai.handlers._openrouter_config", lambda: {"base_url": "x", "api_key": "k"})):
            p = patch(target, side_effect=value)
            p.start()
            self.addCleanup(p.stop)

    def _preset(self, duration):
        return CartoonPreset.objects.create(
            slug=f"s{duration}", title="Сцена", is_active=True, scene_prompt="x", duration=duration,
            image_model=self.image, video_model=self.video)

    @override_settings(STUDIO_SCENE_CREDITS=0)
    def test_without_setting_price_is_model_tariff(self):
        self.assertEqual(scene_credits(self._preset(5)), 164)

    @override_settings(STUDIO_SCENE_CREDITS=200)
    def test_scene_costs_exactly_what_admin_set(self):
        preset = self._preset(5)
        self.assertEqual(scene_credits(preset), 200)
        # Кадр уже готов — платится только видео.
        self.assertEqual(scene_credits(preset, keyframe_ready=True), 196)

    @override_settings(STUDIO_SCENE_CREDITS=200)
    def test_shorter_scene_is_proportionally_cheaper(self):
        self.assertEqual(scene_credits(self._preset(4)), 4 + round(4 * 196 / 5))

    @override_settings(STUDIO_SCENE_CREDITS=200)
    def test_manual_preset_price_still_wins(self):
        preset = self._preset(5)
        preset.credits_override = 250
        preset.save(update_fields=["credits_override"])
        self.assertEqual(scene_credits(preset), 250)
