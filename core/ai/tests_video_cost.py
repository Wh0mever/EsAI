# -*- coding: utf-8 -*-
"""Цена видео не ниже себестоимости (жалоба 23.09: 4 ролика 1080p — минус $22 на OpenRouter)."""
from unittest.mock import patch

from django.core.cache import cache
from django.test import TestCase, override_settings

from ai.models import GPTModels
from ai.video_cost import provider_cost_usd, video_credits
from plans.models import TokenPackage

TEST_CACHES = {"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache",
                           "LOCATION": "video-cost-tests"}}

# Прайс OpenRouter /videos/models на 24.09.2026.
SEEDANCE_20 = {"id": "bytedance/seedance-2.0", "pricing_skus": {
    "video_tokens": "0.000007", "video_tokens_4k": "0.000004", "video_tokens_1080p": "0.0000077",
    "video_tokens_without_audio": "0.000007", "video_tokens_with_video_input": "0.0000043"}}
VEO_31 = {"id": "google/veo-3.1", "pricing_skus": {
    "duration_seconds_with_audio": "0.40", "duration_seconds_with_audio_4k": "0.60",
    "duration_seconds_without_audio": "0.20", "duration_seconds_without_audio_4k": "0.40"}}
VEO_LITE = {"id": "google/veo-3.1-lite", "pricing_skus": {
    "duration_seconds_with_audio": "0.08", "duration_seconds_without_audio": "0.05",
    "duration_seconds_with_audio_720p": "0.05", "duration_seconds_without_audio_720p": "0.03"}}
KLING = {"id": "kwaivgi/kling-v3.0-std", "pricing_skus": {
    "duration_seconds": "0.084", "duration_seconds_with_audio": "0.126",
    "image_to_video_duration_seconds_720p": "0.084"}}
GROK = {"id": "x-ai/grok-imagine-video", "pricing_skus": {
    "cents_per_image_input": "0.2", "cents_per_video_output_second_480p": "5",
    "cents_per_video_output_second_720p": "7"}}


class ProviderCostTests(TestCase):
    def test_seedance_matches_the_real_bill(self):
        # Журнал генераций: 15 с 1080p — $5.6289, 8 с 720p — $1.2159.
        self.assertAlmostEqual(provider_cost_usd(SEEDANCE_20, "1080p", 15), 5.63, delta=0.05)
        self.assertAlmostEqual(provider_cost_usd(SEEDANCE_20, "720p", 8), 1.216, delta=0.02)
        # 4K считается по своей (меньшей за токен) цене, а не по общей.
        self.assertAlmostEqual(provider_cost_usd(SEEDANCE_20, "4K", 1), 0.7776, delta=0.001)

    def test_per_second_prices_pick_resolution_and_audio(self):
        self.assertAlmostEqual(provider_cost_usd(VEO_31, "1080p", 8), 3.2)   # со звуком 0.40
        self.assertAlmostEqual(provider_cost_usd(VEO_31, "4K", 8), 4.8)      # 0.60 за 4K
        self.assertAlmostEqual(provider_cost_usd(VEO_LITE, "720p", 4), 0.2)  # своя цена 720p
        self.assertAlmostEqual(provider_cost_usd(KLING, "720p", 10), 1.26)   # со звуком дороже
        self.assertAlmostEqual(provider_cost_usd(GROK, "720p", 5, images=1), 0.352)

    def test_unknown_price_is_none(self):
        self.assertIsNone(provider_cost_usd({}, "720p", 5))
        self.assertIsNone(provider_cost_usd({"pricing_skus": {"weird": "1"}}, "720p", 5))


@override_settings(CACHES=TEST_CACHES, VIDEO_MIN_MARGIN=0.4)
class VideoCreditsTests(TestCase):
    def setUp(self):
        cache.clear()
        # Самый дешёвый кредит — как у MASTER: 4990 сом / 7000 кредитов.
        TokenPackage.objects.create(name="Про", tokens=500, price=490, is_active=True)
        TokenPackage.objects.create(name="MASTER", tokens=7000, price=4990, is_active=True)
        self.seedance = GPTModels.objects.create(name="Seedance 2.0", openrouter_id="bytedance/seedance-2.0",
                                                 category="video", markup_coefficient=32,
                                                 max_tokens=1000, is_active=True)
        rate = patch("payments.crypto.rates.kgs_to_usd_rate", return_value=0.0115)
        rate.start()
        self.addCleanup(rate.stop)

    def test_720p_keeps_the_admin_tariff(self):
        self.assertEqual(video_credits(self.seedance, SEEDANCE_20, "720p", 15), 480)

    def test_1080p_is_never_below_cost_plus_margin(self):
        price = video_credits(self.seedance, SEEDANCE_20, "1080p", 15)
        credit_usd = 4990 * 0.0115 / 7000
        revenue = price * credit_usd
        cost = provider_cost_usd(SEEDANCE_20, "1080p", 15)
        self.assertGreaterEqual(revenue, cost / 0.6 - credit_usd)  # маржа ≥ 40 %
        self.assertGreater(price, 1000)  # было 480 — работали в минус

    def test_without_price_list_falls_back_to_tariff(self):
        self.assertEqual(video_credits(self.seedance, {}, "1080p", 15), 480)

    def test_params_api_shows_what_will_be_charged(self):
        from rest_framework.test import APIClient

        spec = dict(SEEDANCE_20, supported_durations=[5, 15], supported_resolutions=["720p", "1080p"])
        with patch("ai.handlers._openrouter_video_catalog", return_value=spec):
            r = APIClient().get("/api/ai/video-params/", {"model": "bytedance/seedance-2.0"})
        self.assertEqual(r.status_code, 200, r.data)
        table = r.data["price_table"]
        self.assertEqual(table["720p"]["15"], 480)
        self.assertEqual(table["1080p"]["15"], video_credits(self.seedance, spec, "1080p", 15))
