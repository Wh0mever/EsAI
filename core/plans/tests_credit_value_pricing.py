# -*- coding: utf-8 -*-
"""Калькулятор «На что хватит?» берёт настоящую цену ролика в обоих режимах цен.

Раньше видео считалось как ceil(секунды × тариф) без нижней границы по
себестоимости: Seedance 2.0 с тарифом 0 стоил «1 кредит», и /models обещал 150
роликов на «Старт». Теперь — ai.video_cost.video_credits, та же функция, что
списывает видео в чате (BUILD_A, решение 11).
"""
from __future__ import annotations

from decimal import Decimal
from unittest.mock import patch

from django.core.cache import cache
from django.test import TestCase, override_settings

from adminapi.runtime import set_runtime
from ai import pricing
from ai.tests_pricing_golden import GOLDEN_SETTINGS, create_models, create_packages, start_price_mocks
from plans import credit_value as cv

SEEDANCE = "bytedance/seedance-2.0"
GROK = "x-ai/grok-imagine-video"
SORA = "openai/sora-2-pro"
KLEIN = "black-forest-labs/flux.2-klein-4b"


@override_settings(**GOLDEN_SETTINGS)
class CreditValueVideoTests(TestCase):
    def setUp(self):
        cache.clear()
        start_price_mocks(self)
        self.models = create_models()
        create_packages()

    def markup(self):
        set_runtime(pricing.KEY_MODE, pricing.MODE_MARKUP)
        set_runtime(pricing.KEY_KGS_PER_USD, "87.4")
        pricing.invalidate_price_caches()

    def test_legacy_video_has_the_cost_floor(self):
        """Тариф 0 больше не значит «1 кредит»: цена — как в чате, не ниже себестоимости."""
        self.assertEqual(cv._video_credits(self.models[SEEDANCE]), Decimal(145))
        self.assertEqual(cv._video_credits(self.models[GROK]), Decimal(75))
        # Sora нет в каталоге — тариф, как и в чате (62 кр/с × 5 с).
        self.assertEqual(cv._video_credits(self.models[SORA]), Decimal(310))
        usage = cv.estimate_model_usage_cost(self.models[SEEDANCE])
        self.assertEqual((usage["count"], usage["package_name"]), (1, "Старт"))

    def test_markup_video_is_cost_with_markup(self):
        self.markup()
        self.assertEqual(cv._video_credits(self.models[SEEDANCE]), Decimal(122))
        self.assertEqual(cv._video_credits(self.models[GROK]), Decimal(56))
        self.assertEqual(cv.credits_per_unit("video"), Decimal(56))

    def test_markup_without_cost_shows_nothing(self):
        """Себестоимости нет — цены нет: категорию не показываем, а не считаем по тарифу."""
        self.markup()
        self.assertIsNone(cv._video_credits(self.models[SORA]))
        self.assertIsNone(cv.estimate_model_usage_cost(self.models[SORA]))

    def test_markup_image_uses_unit_cost(self):
        self.markup()
        klein = self.models[KLEIN]
        klein.unit_cost_usd = Decimal("0.015")
        klein.save(update_fields=["unit_cost_usd"])
        self.assertEqual(cv._image_credits(klein), Decimal(3))

    def test_catalogue_down_does_not_break_the_calculator(self):
        with patch("ai.handlers._video_model_params", side_effect=RuntimeError("down")):
            self.assertEqual(cv._video_credits(self.models[GROK]), Decimal(75))
        self.markup()
        with patch("ai.handlers._openrouter_video_catalog", side_effect=RuntimeError("down")):
            self.assertIsNone(cv._video_credits(self.models[GROK]))

    def test_packages_value_follows_the_mode(self):
        rows = {r["name"]: r["value"] for r in cv.compute_all_packages_value("ru")}
        self.assertEqual(rows["MASTER"]["video"]["count"], 6500 // 75)
        self.markup()
        rows = {r["name"]: r["value"] for r in cv.compute_all_packages_value("ru")}
        self.assertEqual(rows["MASTER"]["video"]["count"], 6500 // 56)
