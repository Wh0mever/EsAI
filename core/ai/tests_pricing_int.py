# -*- coding: utf-8 -*-
"""Сшивка режима цен «наценка» с путями вне ai/pricing (интеграция Build A).

Чат и очередь бота отказывают, когда цены нет, а не снимают по тарифу; публичный
список моделей отдаёт цену картинки FLUX в действующем режиме; правки в
Django-админке сбрасывают кэши цен; отчёт видеостудии считает «низкую маржу»
тем же порогом, что и check_margin.
"""
from __future__ import annotations

from decimal import Decimal
from unittest.mock import patch

from django.contrib import admin
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from adminapi.runtime import set_runtime
from ai import pricing
from ai.generation import run_video_generation
from ai.models import AiChatSession, GenerationJob, GenerationLog, GPTModels
from ai.tests_pricing_golden import TEST_CACHES, create_packages, start_price_mocks
from plans.models import TokenPackage

REFUSAL = {"error": "Цена модели сейчас недоступна, попробуйте позже", "error_code": "price_unavailable"}
PARAMS = {"duration": 5, "resolution": "720p"}
CFG = {"api_key": "k", "base_url": "http://provider/api/v1"}
FLUX_KLEIN = "black-forest-labs/flux.2-klein-4b"


def _user(balance=500):
    user = get_user_model().objects.create_user(email="int@example.com", password="x")
    user.token_balance = balance
    user.is_paid = True
    user.save(update_fields=["token_balance", "is_paid"])
    return user


def _video_model():
    # Модели нет в каталоге OpenRouter: в режиме «наценка» себестоимость неизвестна.
    return GPTModels.objects.create(name="Unknown video", openrouter_id="test/unknown-video",
                                    max_tokens=1000, markup_coefficient=4, category="video",
                                    is_active=True)


def _no_catalog():
    return [patch("ai.handlers._video_model_params", return_value=PARAMS),
            patch("ai.handlers._openrouter_config", return_value=CFG),
            patch("ai.handlers._openrouter_video_catalog", return_value={})]


class _Patched:
    def __init__(self, patches):
        self.patches = patches

    def __enter__(self):
        for p in self.patches:
            p.start()
        return self

    def __exit__(self, *exc):
        for p in reversed(self.patches):
            p.stop()
        return False


@override_settings(CACHES=TEST_CACHES, CELERY_MEDIA_QUEUE="media")
class VideoRefusalTests(TestCase):
    """Режим «наценка» без себестоимости: отказ, ни тарифа, ни списания, ни задачи."""

    def setUp(self):
        cache.clear()
        self.user = _user()
        self.model = _video_model()
        set_runtime(pricing.KEY_MODE, pricing.MODE_MARKUP)

    def test_queue_submit_answers_503_and_creates_nothing(self):
        client = APIClient()
        client.force_authenticate(self.user)
        with _Patched(_no_catalog() + [patch("ai.tasks.run_generation_job.apply_async")]) as _p, \
                patch("ai.handlers._reserve_daily_request") as reserve:
            response = client.post("/api/ai/jobs/", {"message": "кот", "model": self.model.openrouter_id,
                                                     "video_duration": 5}, format="json")
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.data, REFUSAL)
        reserve.assert_not_called()
        self.assertFalse(GenerationJob.objects.exists())
        self.assertFalse(AiChatSession.objects.exists())

    def test_legacy_mode_still_prices_by_tariff(self):
        set_runtime(pricing.KEY_MODE, pricing.MODE_LEGACY)
        client = APIClient()
        client.force_authenticate(self.user)
        with _Patched(_no_catalog() + [patch("ai.tasks.run_generation_job.apply_async")]):
            response = client.post("/api/ai/jobs/", {"message": "кот", "model": self.model.openrouter_id,
                                                     "video_duration": 5}, format="json")
        self.assertEqual(response.status_code, 202, response.data)
        self.assertEqual(GenerationJob.objects.get().need_credits, 20)  # 5 с × 4 кр, как раньше

    def test_chat_generator_refuses_and_returns_the_daily_slot(self):
        session = AiChatSession.objects.create(user=self.user, title="Видео")
        with _Patched(_no_catalog() + [patch("requests.post"), patch("requests.get")]) as _p, \
                patch("ai.handlers._release_daily_request") as release:
            frames = list(run_video_generation(
                user=self.user, model_obj=self.model, selected_model_name=self.model.openrouter_id,
                message="кот на пляже", attachments=[], origin_base="https://esai.kg", session=session))
        self.assertEqual(frames, [{**REFUSAL, "done": True}])
        release.assert_called_once()
        self.assertFalse(GenerationLog.objects.exists())
        self.user.refresh_from_db(fields=["token_balance"])
        self.assertEqual(self.user.token_balance, 500)


@override_settings(CACHES=TEST_CACHES)
class CreditsPerImageTests(TestCase):
    """/api/ai/models/: цена картинки FLUX — та, что спишет чат, в обоих режимах."""

    def setUp(self):
        cache.clear()
        start_price_mocks(self)
        create_packages()
        set_runtime(pricing.KEY_KGS_PER_USD, "87.4")
        GPTModels.objects.create(name="FLUX Klein", openrouter_id=FLUX_KLEIN, category="image",
                                 markup_coefficient=Decimal("2"), unit_cost_usd=Decimal("0.015"),
                                 max_tokens=4096, is_active=True)
        GPTModels.objects.create(name="Nano", openrouter_id="google/gemini-2.5-flash-image",
                                 category="image", markup_coefficient=Decimal("4"),
                                 unit_cost_usd=Decimal("0.039"), max_tokens=4096, is_active=True)
        GPTModels.objects.create(name="GPT", openrouter_id="openai/gpt-4o", category="chat",
                                 markup_coefficient=Decimal("17"), max_tokens=4096, is_active=True)

    def prices(self):
        response = APIClient().get("/api/ai/models/")
        self.assertEqual(response.status_code, 200)
        return {row["openrouter_id"]: row["credits_per_image"] for row in response.json()}

    def test_legacy_is_the_flat_tariff(self):
        self.assertEqual(self.prices(), {FLUX_KLEIN: 2, "google/gemini-2.5-flash-image": None,
                                         "openai/gpt-4o": None})

    def test_markup_is_the_cost_with_markup(self):
        set_runtime(pricing.KEY_MODE, pricing.MODE_MARKUP)
        # 0.015 $ × 1.4 на кредите MASTER при 87.4 сома за доллар → 3 кр (PLAN §3.3).
        self.assertEqual(self.prices()[FLUX_KLEIN], 3)


@override_settings(CACHES=TEST_CACHES)
class DjangoAdminInvalidationTests(TestCase):
    """Правки модели и пакета в Django-админке идут мимо /api/manage/ — кэши цен сбрасывают сами."""

    def stale(self):
        cache.set("vstudio:models:v1:paid", ["stale"], 600)
        cache.set("video_cost:credit_usd", "stale", 600)

    def assert_dropped(self):
        self.assertIsNone(cache.get("vstudio:models:v1:paid"))
        self.assertIsNone(cache.get("video_cost:credit_usd"))

    def test_model_save_and_delete(self):
        model_admin = admin.site._registry[GPTModels]
        obj = GPTModels(name="X", openrouter_id="x/y", category="video", max_tokens=10)
        self.stale()
        with self.captureOnCommitCallbacks(execute=True):
            model_admin.save_model(None, obj, None, False)
        self.assert_dropped()
        self.stale()
        model_admin.delete_model(None, obj)
        self.assert_dropped()

    def test_package_save_and_bulk_delete(self):
        package_admin = admin.site._registry[TokenPackage]
        obj = TokenPackage(name="P", tokens=100, price=100, currency="KGS", is_active=True)
        self.stale()
        package_admin.save_model(None, obj, None, False)
        self.assert_dropped()
        self.stale()
        package_admin.delete_queryset(None, TokenPackage.objects.filter(pk=obj.pk))
        self.assert_dropped()


@override_settings(CACHES=TEST_CACHES)
class ReportMarginTests(TestCase):
    """Отчёт видеостудии: в режиме «наценка» порог «низкой маржи» = нижний порог наценки."""

    def setUp(self):
        cache.clear()
        start_price_mocks(self)
        create_packages()

    def test_legacy_keeps_video_cost_basis(self):
        from ai.video_cost import cheapest_credit_usd, min_margin
        from vstudio.reports import _credit_usd, _min_margin

        self.assertEqual(_min_margin(), float(min_margin()))
        self.assertEqual(_credit_usd(), float(cheapest_credit_usd()))

    def test_markup_uses_floor_and_pinned_credit(self):
        from vstudio.reports import _credit_usd, _min_margin

        set_runtime(pricing.KEY_MODE, pricing.MODE_MARKUP)
        set_runtime(pricing.KEY_FLOOR_PCT, "25")
        set_runtime(pricing.KEY_KGS_PER_USD, "90")
        # Выручка ≥ cost × 1.25 ⇔ маржа ≥ 25/125.
        self.assertAlmostEqual(_min_margin(), 0.2)
        self.assertEqual(_credit_usd(), float(pricing.credit_usd()))
        self.assertAlmostEqual(_credit_usd(), 4990 / 6500 / 90, places=12)
