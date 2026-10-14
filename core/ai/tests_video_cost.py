# -*- coding: utf-8 -*-
"""Цена видео не ниже себестоимости провайдера с учётом маржи."""
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
        # 4K считается по своей (меньшей за токен) цене, а не по общей;
        # кадров OpenRouter считает 24·секунды + 1.
        self.assertAlmostEqual(provider_cost_usd(SEEDANCE_20, "4K", 1),
                               3840 * 2160 * 25 / 1024 * 0.000004, delta=0.001)

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
        # Пакеты как на проде: самый дешёвый кредит у «Максимума» (1990 / 2800).
        TokenPackage.objects.create(name="Про", tokens=500, price=490, is_active=True)
        TokenPackage.objects.create(name="MASTER", tokens=7000, price=4990, is_active=True)
        TokenPackage.objects.create(name="Максимум", tokens=2800, price=1990, is_active=True)
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
        credit_usd = 1990 * 0.0115 / 2800  # «Максимум» — самый дешёвый кредит
        revenue = price * credit_usd
        cost = provider_cost_usd(SEEDANCE_20, "1080p", 15)
        self.assertGreaterEqual(revenue, cost / 0.6 - credit_usd)  # маржа ≥ 40 %
        self.assertGreater(price, 1000)  # было 480 — работали в минус

    def test_without_price_list_720p_uses_tariff(self):
        self.assertEqual(video_credits(self.seedance, {}, "720p", 15), 480)

    def test_lower_quality_is_cheaper(self):
        # 480p у провайдера вдвое дешевле 720p — и человеку тоже, а не по цене 720p.
        spec = dict(SEEDANCE_20, supported_resolutions=["480p", "720p", "1080p", "4K"])
        p480 = video_credits(self.seedance, spec, "480p", 5)
        p720 = video_credits(self.seedance, spec, "720p", 5)
        self.assertEqual(p720, 160)
        self.assertLess(p480, p720 * 0.6)
        credit_usd = 1990 * 0.0115 / 2800
        self.assertGreaterEqual(p480 * credit_usd, provider_cost_usd(spec, "480p", 5) / 0.6 - credit_usd)

    def test_params_api_shows_what_will_be_charged(self):
        from rest_framework.test import APIClient

        spec = dict(SEEDANCE_20, supported_durations=[5, 15], supported_resolutions=["720p", "1080p"])
        with patch("ai.handlers._openrouter_video_catalog", return_value=spec):
            r = APIClient().get("/api/ai/video-params/", {"model": "bytedance/seedance-2.0"})
        self.assertEqual(r.status_code, 200, r.data)
        table = r.data["price_table"]
        self.assertEqual(table["720p"]["15"], 480)
        self.assertEqual(table["1080p"]["15"], video_credits(self.seedance, spec, "1080p", 15))


SEEDANCE_SIZES = dict(SEEDANCE_20, supported_aspect_ratios=["1:1", "16:9", "21:9", "9:16"],
                      supported_resolutions=["480p", "720p", "1080p", "4K"],
                      # Как в реальном каталоге: у каждой пропорции по размеру на качество.
                      supported_sizes=["480x480", "854x480", "1120x480", "480x854",
                                       "720x720", "1280x720", "1680x720", "720x1280",
                                       "1080x1080", "1920x1080", "2520x1080", "1080x1920",
                                       "2160x2160", "3840x2160", "5040x2160", "2160x3840"])


class AspectAndFallbackTests(TestCase):
    def test_wide_frame_costs_more_square_less(self):
        wide = provider_cost_usd(SEEDANCE_SIZES, "1080p", 15, aspect="21:9")
        normal = provider_cost_usd(SEEDANCE_SIZES, "1080p", 15, aspect="16:9")
        square = provider_cost_usd(SEEDANCE_SIZES, "1080p", 15, aspect="1:1")
        self.assertAlmostEqual(wide / normal, 2520 / 1920, places=3)
        self.assertLess(square, normal * 0.6)
        # Квадрат 720p — это 720×720, а не ближайший по площади 1080×1080.
        self.assertAlmostEqual(provider_cost_usd(SEEDANCE_SIZES, "720p", 5, aspect="1:1")
                               / provider_cost_usd(SEEDANCE_SIZES, "720p", 5, aspect="16:9"),
                               720 * 720 / (1280 * 720), places=3)
        # Пропорции не известны — самый большой кадр класса, чтобы не занизить.
        self.assertAlmostEqual(provider_cost_usd(SEEDANCE_SIZES, "1080p", 15), wide)

    def test_other_price_shapes(self):
        flux = {"pricing_skus": {"cents_per_second_output_720p": "17", "cents_per_second_output_1080p": "29"}}
        self.assertAlmostEqual(provider_cost_usd(flux, "1080p", 5), 1.45)
        aleph = {"pricing_skus": {"cents_per_second_output": "10", "minimum_cents_per_generation": "56"}}
        self.assertAlmostEqual(provider_cost_usd(aleph, "720p", 2), 0.56)


@override_settings(CACHES=TEST_CACHES, VIDEO_MIN_MARGIN=0.4)
class FallbackPricingTests(TestCase):
    def setUp(self):
        cache.clear()
        self.model = GPTModels.objects.create(name="Seedance 2.0", openrouter_id="bytedance/seedance-2.0",
                                              category="video", markup_coefficient=32,
                                              max_tokens=1000, is_active=True)

    def test_no_catalog_does_not_fall_back_to_flat_720p_price(self):
        # Каталог недоступен: 1080p не может стоить как 720p.
        self.assertGreater(video_credits(self.model, {}, "1080p", 15), 480 * 2)
        self.assertEqual(video_credits(self.model, {}, "720p", 15), 480)

    def test_stars_package_counts_for_cheapest_credit(self):
        from ai.video_cost import cheapest_credit_usd

        TokenPackage.objects.create(name="Про", tokens=500, price=490, is_active=True,
                                    stars_price=100, stars_bonus_tokens=500)
        with patch("payments.crypto.rates.kgs_to_usd_rate", return_value=0.0115), \
             patch("plans.stars.withdraw_rate", return_value=0.013):
            self.assertAlmostEqual(cheapest_credit_usd(), 100 * 0.013 / 1000, places=6)

    def test_failed_catalog_is_not_cached_and_last_good_is_used(self):
        from unittest.mock import MagicMock

        from ai.handlers import _load_video_catalog

        good = MagicMock(ok=True)
        good.json.return_value = {"data": [SEEDANCE_20]}
        bad = MagicMock(ok=False)
        bad.json.return_value = {"error": {"code": 429}}
        cfg = {"base_url": "https://openrouter.ai/api/v1", "api_key": "k"}
        with patch("requests.get", return_value=good):
            self.assertEqual(_load_video_catalog(cfg), [SEEDANCE_20])
        cache.delete("or_video_models")  # час прошёл
        with patch("requests.get", return_value=bad):
            self.assertEqual(_load_video_catalog(cfg), [SEEDANCE_20])  # прошлая удачная копия
        self.assertIsNone(cache.get("or_video_models"))
