# -*- coding: utf-8 -*-
"""Цена по себестоимости с наценкой (ai/pricing.py, режим markup).

Числа — клетки PLAN §3.1/§3.3/§4.3: закреплённый курс 87.4 сома за доллар,
самый дешёвый кредит — MASTER 4990 сомов / 6500 кредитов, наценка 40 %,
порог 25 %. Каталог OpenRouter — сохранённый 14.10.2026, сети нет.
"""
from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from django.core.cache import cache
from django.test import SimpleTestCase, TestCase, override_settings

from adminapi.runtime import CACHE_PREFIX, get_runtime, set_runtime
from ai import pricing
from ai.model_billing import flux_charge_credits
from ai.models import GPTModels
from ai.tests_pricing_golden import TEST_CACHES, catalog_by_id, create_packages, start_price_mocks
from ai.video_cost import price_table, video_credits
from plans.models import TokenPackage

SEEDANCE = "bytedance/seedance-2.0"
MINI = "bytedance/seedance-2.0-mini"
FAST = "bytedance/seedance-2.0-fast"
S25 = "bytedance/seedance-2.5"
NANO = "google/gemini-2.5-flash-image"


def _video(orid, coeff="0", **kw):
    return GPTModels.objects.create(name=orid, openrouter_id=orid, category="video",
                                    markup_coefficient=Decimal(coeff), max_tokens=4096, is_active=True, **kw)


def _image(orid, coeff, unit=None, ref=None, **kw):
    return GPTModels.objects.create(name=orid, openrouter_id=orid, category="image",
                                    markup_coefficient=Decimal(coeff), max_tokens=4096, is_active=True,
                                    unit_cost_usd=None if unit is None else Decimal(unit),
                                    ref_cost_usd=None if ref is None else Decimal(ref), **kw)


class MarkupBase(TestCase):
    """Режим markup, курс закреплён на 87.4, пакеты прода."""

    rate = "87.4"

    def setUp(self):
        cache.clear()
        start_price_mocks(self)
        create_packages()
        set_runtime(pricing.KEY_MODE, pricing.MODE_MARKUP)
        if self.rate:
            set_runtime(pricing.KEY_KGS_PER_USD, self.rate)
        self.catalog = catalog_by_id()

    def price(self, model, res, seconds, aspect="16:9", images=0):
        return video_credits(model, self.catalog[model.openrouter_id], res, seconds, images=images, aspect=aspect)


@override_settings(CACHES=TEST_CACHES)
class PlanCellsTests(MarkupBase):
    """(b) Клетки таблиц PLAN при +40 % к себестоимости на кредите MASTER."""

    def test_credit_basis_is_master_at_pinned_rate(self):
        basis = pricing.credit_basis()
        self.assertEqual(basis.package_name, "MASTER")
        self.assertEqual(basis.rate_source, "pinned")
        self.assertEqual(basis.kgs_per_usd, Decimal("87.4"))
        self.assertAlmostEqual(float(basis.usd), 4990 / 6500 / 87.4, places=12)
        self.assertEqual(basis.to_dict()["kgs_per_credit"], "0.76769")

    def test_video_cells(self):
        cells = (
            (SEEDANCE, "720p", 5, 122), (SEEDANCE, "480p", 5, 55), (SEEDANCE, "720p", 10, 242),
            (SEEDANCE, "720p", 15, 363), (MINI, "480p", 5, 28), (MINI, "720p", 5, 61), (MINI, "720p", 10, 121),
            (MINI, "720p", 15, 182), (FAST, "480p", 5, 33), (FAST, "720p", 5, 73), (S25, "480p", 5, 83),
            (S25, "720p", 5, 186), (S25, "720p", 15, 555),
        )
        models = {orid: _video(orid) for orid in (SEEDANCE, MINI, FAST, S25)}
        for orid, res, seconds, want in cells:
            with self.subTest(model=orid, res=res, seconds=seconds):
                self.assertEqual(self.price(models[orid], res, seconds), want)

    def test_per_second_models(self):
        cells = (("x-ai/grok-imagine-video", "15", "720p", 5, 56), ("x-ai/grok-imagine-video", "15", "480p", 5, 40),
                 ("kwaivgi/kling-v3.0-std", "26", "720p", 5, 101), ("alibaba/wan-2.7", "21", "720p", 5, 80),
                 ("google/veo-3.1-lite", "17", "720p", 4, 32), ("google/veo-3.1", "83", "720p", 4, 256),
                 ("minimax/hailuo-2.3", "17", "1080p", 6, 79))
        models = {}
        for orid, coeff, res, seconds, want in cells:
            with self.subTest(model=orid, res=res):
                model = models.get(orid) or models.setdefault(orid, _video(orid, coeff))
                # Тариф модели в markup не участвует: Veo 3.1 Lite не 68 (17 кр/с), а 32.
                self.assertEqual(self.price(model, res, seconds, aspect=None), want)

    def test_square_frame_is_priced_by_its_area(self):
        model = _video(SEEDANCE)
        self.assertEqual(self.price(model, "720p", 5, aspect="16:9"), 122)
        self.assertEqual(self.price(model, "720p", 5, aspect="9:16"), 122)
        self.assertEqual(self.price(model, "720p", 5, aspect="1:1"), 69)

    def test_reference_images_are_part_of_the_cost(self):
        model = _video("x-ai/grok-imagine-video", "15")
        # 0.2 цента за фото: 0.35 + 0.002 → ⌈0.352 × 1.4 / credit⌉.
        self.assertEqual(self.price(model, "720p", 5, aspect=None, images=1), 57)

    def test_image_cells(self):
        cells = (("black-forest-labs/flux.2-klein-4b", "2", "0.015", None, 3),
                 ("black-forest-labs/flux.2-pro", "4", "0.03", None, 5),
                 ("black-forest-labs/flux.2-flex", "12", "0.06", "0.06", 10),
                 ("black-forest-labs/flux.2-max", "10", "0.07", None, 12),
                 (NANO, "4", "0.039", None, 7),
                 ("google/gemini-3-pro-image", "12", "0.134", None, 22))
        for orid, coeff, unit, ref, want in cells:
            with self.subTest(model=orid):
                model = _image(orid, coeff, unit, ref)
                self.assertEqual(pricing.image_credits(model), want)
                self.assertEqual(flux_charge_credits(model, refs=0), want)
        flex = GPTModels.objects.get(openrouter_id="black-forest-labs/flux.2-flex")
        # FLUX Flex с одним входным фото: 0.06 + 0.06.
        self.assertEqual(pricing.image_credits(flex, 1), 20)

    def test_cartoon_scene_mini_480p(self):
        # PLAN §4.3: кадр Nano Banana 7 + видео Mini 480p 5 с 28 = 35.
        frame = pricing.image_credits(_image(NANO, "4", "0.039"))
        video = self.price(_video(MINI), "480p", 5)
        self.assertEqual((frame, video, frame + video), (7, 28, 35))

    def test_price_table_follows_markup(self):
        model = _video(MINI)
        table = price_table(model, self.catalog[MINI], ["480p", "720p"], [5, 10])
        self.assertEqual(table, {"480p": {"5": 28, "10": 54}, "720p": {"5": 61, "10": 121}})


@override_settings(CACHES=TEST_CACHES)
class DecimalEdgeTests(TestCase):
    """(b) Ровное число кредитов не округляется вверх из-за float."""

    def setUp(self):
        cache.clear()
        start_price_mocks(self)
        # Кредит ровно $0.01: 1000 сомов / 1000 кредитов по 100 сомов за доллар.
        TokenPackage.objects.create(name="Ровный", tokens=1000, price=1000, currency="KGS", is_active=True)
        set_runtime(pricing.KEY_MODE, pricing.MODE_MARKUP)
        set_runtime(pricing.KEY_KGS_PER_USD, "100")

    def test_exact_integers_stay_exact(self):
        self.assertEqual(pricing.credit_usd(), Decimal("0.01"))
        self.assertEqual(pricing.credits_for_cost("0.5"), 70)        # 0.5 × 1.4 / 0.01 = 70, не 71
        self.assertEqual(pricing.credits_for_cost(0.05), 7)
        self.assertEqual(pricing.credits_for_cost(Decimal("0.0500001")), 8)
        with pricing.override_config(markup_pct=Decimal("0"), floor_pct=Decimal("0")):
            # 0.1 + 0.2 во float = 0.30000000000000004 — всё равно ровно 30.
            self.assertEqual(pricing.credits_for_cost(0.1 + 0.2), 30)
            self.assertEqual(pricing.credits_for_cost(0), 1)            # минимум 1 кредит
            self.assertEqual(pricing.credits_for_cost("0.00001"), 1)

    def test_rounding_is_once_per_unit(self):
        # 0.0101 × 1.4 / 0.01 = 1.414 → 2.
        self.assertEqual(pricing.credits_for_cost("0.0101"), 2)


@override_settings(CACHES=TEST_CACHES)
class RefusalTests(MarkupBase):
    """(c) Себестоимости нет — отказ, а не тариф."""

    def test_video_without_cost_is_refused(self):
        model = _video("openai/sora-2-pro", "62")
        with self.assertRaises(pricing.PriceUnavailable) as ctx:
            video_credits(model, {}, "720p", 5)
        self.assertEqual(str(ctx.exception), "Цена модели сейчас недоступна, попробуйте позже")
        self.assertEqual(ctx.exception.payload(),
                         {"error": "Цена модели сейчас недоступна, попробуйте позже",
                          "error_code": "price_unavailable"})
        self.assertEqual(ctx.exception.model_id, "openai/sora-2-pro")
        # Прайс непонятного вида (апскейл за мегапиксель-секунду) — тоже отказ.
        with self.assertRaises(pricing.PriceUnavailable):
            video_credits(model, self.catalog["black-forest-labs/flux-video-upscale"], "720p", 5)

    def test_legacy_still_falls_back_to_tariff(self):
        model = _video("openai/sora-2-pro", "62")
        set_runtime(pricing.KEY_MODE, pricing.MODE_LEGACY)
        self.assertEqual(video_credits(model, {}, "720p", 5), 310)

    def test_no_priced_package_is_refused(self):
        TokenPackage.objects.update(is_active=False)
        pricing.invalidate_price_caches()
        with self.assertRaises(pricing.PriceUnavailable) as ctx:
            video_credits(_video(SEEDANCE), self.catalog[SEEDANCE], "720p", 5)
        self.assertEqual(ctx.exception.reason, "no_priced_package")

    def test_vstudio_has_no_price_instead_of_tariff(self):
        from vstudio import caps as caps_mod
        from vstudio import pricing as vp

        model = _video(SEEDANCE, vstudio_enabled=True)
        spec = dict(self.catalog[SEEDANCE], pricing_skus={"weird": "1"})
        caps = caps_mod.for_model(model, spec=spec)
        compiled = SimpleNamespace(kind="video", errors=[], billable_images=0, price_aspect="16:9",
                                   effective={"duration": 5, "resolution": "720p", "aspect_ratio": "16:9"})
        self.assertIs(vp.price(compiled, model, caps, spec=spec), vp.NO_PRICE)
        self.assertEqual(vp.model_prices(model, caps, spec=spec),
                         {"price": None, "per_image": None, "price_from": None})

    def test_image_without_cost_keeps_legacy_price_and_is_flagged(self):
        model = _image("black-forest-labs/flux.2-pro", "4")
        self.assertEqual(pricing.image_credits(model), 4)
        info = pricing.image_price(model)
        self.assertEqual((info.credits, info.source, info.cost_usd), (4, "no_cost", None))


@override_settings(CACHES=TEST_CACHES)
class OverrideAndFloorTests(MarkupBase):
    """(d) Своя наценка модели важнее общей, но порог побеждает."""

    def test_model_markup_overrides_global(self):
        model = _video(SEEDANCE, markup_pct=Decimal("60"))
        # ⌈0.7623 × 1.6 / credit⌉ = 139 (при общей 40 % — 122).
        self.assertEqual(self.price(model, "720p", 5), 139)
        self.assertEqual(pricing.markup_for(model), Decimal("60"))

    def test_global_markup_is_editable(self):
        set_runtime(pricing.KEY_MARKUP_PCT, "30")
        model = _video(SEEDANCE)
        self.assertEqual(self.price(model, "720p", 5), 113)

    def test_floor_wins_over_lower_model_markup(self):
        model = _video(SEEDANCE, markup_pct=Decimal("10"))
        # Наценка модели 10 % ниже порога 25 % — цена по порогу: ⌈0.7623 × 1.25 / credit⌉ = 109.
        self.assertEqual(self.price(model, "720p", 5), 109)
        self.assertTrue(pricing.floor_binds(model))
        self.assertEqual(pricing.effective_markup_pct(model), Decimal("25"))
        set_runtime(pricing.KEY_FLOOR_PCT, "0")
        self.assertEqual(self.price(model, "720p", 5), 96)

    def test_floor_also_beats_global_markup(self):
        set_runtime(pricing.KEY_MARKUP_PCT, "5")
        set_runtime(pricing.KEY_FLOOR_PCT, "25")
        self.assertEqual(self.price(_video(SEEDANCE), "720p", 5), 109)

    def test_zero_markup_override_is_not_global(self):
        model = _video(SEEDANCE, markup_pct=Decimal("0"))
        set_runtime(pricing.KEY_FLOOR_PCT, "0")
        # 0 % — своя наценка, а не «пусто»: цена = себестоимость.
        self.assertEqual(self.price(model, "720p", 5), 87)


@override_settings(CACHES=TEST_CACHES)
class SettingsTests(TestCase):
    def setUp(self):
        cache.clear()
        start_price_mocks(self)
        create_packages()

    def test_defaults(self):
        cfg = pricing.current_config()
        self.assertEqual((cfg.mode, cfg.markup_pct, cfg.floor_pct, cfg.kgs_per_usd),
                         ("legacy", Decimal("40"), Decimal("25"), None))
        self.assertFalse(pricing.is_markup())

    def test_validation(self):
        self.assertEqual(pricing.validate_setting("pricing_mode", " Markup "), "markup")
        self.assertEqual(pricing.validate_setting("price_markup_pct", "40"), "40.00")
        self.assertEqual(pricing.validate_setting("price_floor_pct", "0"), "0.00")
        self.assertEqual(pricing.validate_setting("price_kgs_per_usd", "87,5"), "87.5")
        self.assertEqual(pricing.validate_setting("price_kgs_per_usd", ""), "")
        self.assertEqual(pricing.validate_setting("price_kgs_per_usd", "100"), "100")   # не 1E+2
        for key, raw in (("pricing_mode", "cheap"), ("price_markup_pct", "-1"), ("price_markup_pct", "1000.5"),
                         ("price_floor_pct", "abc"), ("price_kgs_per_usd", "0.5"), ("price_kgs_per_usd", "nan"),
                         ("price_unknown", "1")):
            with self.subTest(key=key, raw=raw), self.assertRaises(ValueError):
                pricing.validate_setting(key, raw)

    def test_broken_stored_value_falls_back_to_default(self):
        set_runtime(pricing.KEY_MODE, "maybe")
        set_runtime(pricing.KEY_MARKUP_PCT, "много")
        cfg = pricing.current_config()
        self.assertEqual((cfg.mode, cfg.markup_pct), ("legacy", Decimal("40")))

    def test_live_rate_when_not_pinned(self):
        basis = pricing.credit_basis()
        self.assertEqual(basis.rate_source, "live")
        self.assertEqual(pricing.live_kgs_per_usd(), Decimal("87.4000"))
        self.assertAlmostEqual(float(basis.usd), 4990 / 6500 / 87.4, places=12)

    def test_rate_warning(self):
        set_runtime(pricing.KEY_KGS_PER_USD, "85")     # живой 87.4 слабее на 2.8 %
        self.assertTrue(pricing.rate_warning())
        set_runtime(pricing.KEY_KGS_PER_USD, "86")     # слабее на 1.6 % — в пределах
        self.assertFalse(pricing.rate_warning())
        snap = pricing.settings_snapshot()
        self.assertEqual(snap["kgs_per_usd"], "86")
        self.assertEqual(snap["live_kgs_per_usd"], "87.4")
        self.assertEqual((snap["mode"], snap["markup_pct"], snap["floor_pct"], snap["rate_warning"]),
                         ("legacy", "40", "25", False))
        self.assertEqual(snap["basis"]["kgs_per_usd"], "86")
        self.assertEqual(snap["basis"]["package"], "MASTER")

    def test_cheapest_package_wins_including_usd_and_stars(self):
        set_runtime(pricing.KEY_KGS_PER_USD, "87.4")
        TokenPackage.objects.create(name="USD", tokens=1000, price=Decimal("8"), currency="USD", is_active=True)
        pricing.invalidate_price_caches()
        self.assertEqual(pricing.credit_basis().package_name, "USD")
        TokenPackage.objects.create(name="Stars", tokens=100, price=Decimal("99"), currency="KGS", is_active=True,
                                    stars_price=100, stars_bonus_tokens=900)
        pricing.invalidate_price_caches()
        basis = pricing.credit_basis()
        self.assertEqual((basis.package_name, basis.currency), ("Stars", "STARS"))
        self.assertEqual(basis.usd, Decimal("0.0013"))

    def test_override_config_previews_without_saving(self):
        model = GPTModels.objects.create(name="s", openrouter_id=SEEDANCE, category="video",
                                         markup_coefficient=0, max_tokens=1, is_active=True)
        spec = catalog_by_id()[SEEDANCE]
        self.assertEqual(video_credits(model, spec, "720p", 5), 145)          # legacy
        with pricing.override_config(mode="markup", kgs_per_usd=Decimal("87.4")) as cfg:
            self.assertTrue(cfg.markup)
            self.assertEqual(video_credits(model, spec, "720p", 5), 122)
            with pricing.override_config(markup_pct=Decimal("20")):
                self.assertEqual(video_credits(model, spec, "720p", 5), 109)  # порог 25 % держит
        self.assertEqual(video_credits(model, spec, "720p", 5), 145)
        self.assertEqual(video_credits(model, spec, "720p", 5, cfg=pricing.PricingConfig(mode="markup")), 122)
        self.assertIsNone(get_runtime(pricing.KEY_MODE, None))


@override_settings(CACHES=TEST_CACHES)
class CacheTests(MarkupBase):
    def test_package_edit_is_seen_after_invalidation(self):
        self.assertEqual(pricing.credit_basis().package_name, "MASTER")
        TokenPackage.objects.filter(name="Максимум").update(tokens=10000)
        # До сброса — прежний кредит из кэша (10 мин), после — новый.
        self.assertEqual(pricing.credit_basis().package_name, "MASTER")
        pricing.invalidate_price_caches()
        self.assertEqual(pricing.credit_basis().package_name, "Максимум")

    def test_invalidation_drops_dependent_caches(self):
        keys = ["video_cost:credit_usd", "vstudio:models:v1:guest", "vstudio:models:v1:free",
                "vstudio:models:v1:paid", "credit_value:active_packages_by_price",
                CACHE_PREFIX + "price_markup_pct", "cartoon:models:test"]
        pricing.register_price_cache_key("cartoon:models:test")
        for key in keys:
            cache.set(key, "x", 600)
        versioned = pricing.cache_key("thing")
        cache.set(versioned, "x", 600)
        pricing.invalidate_price_caches()
        for key in keys:
            self.assertIsNone(cache.get(key), key)
        self.assertNotEqual(pricing.cache_key("thing"), versioned)

    def test_runtime_change_after_invalidation_is_immediate(self):
        model = _video(SEEDANCE)
        self.assertEqual(self.price(model, "720p", 5), 122)
        from adminapi.models import AppSetting

        # Запись мимо set_runtime (как bulk-сохранение панели): сброс кэша цен делает её видимой сразу.
        AppSetting.objects.filter(key=pricing.KEY_MARKUP_PCT).delete()
        AppSetting.objects.create(key=pricing.KEY_MARKUP_PCT, value="60")
        pricing.invalidate_price_caches()
        self.assertEqual(self.price(model, "720p", 5), 139)


@override_settings(CACHES=TEST_CACHES)
class MarginCheckTests(MarkupBase):
    def test_markup_threshold_is_floor(self):
        from vstudio import pricing as vp

        def take(charged):
            return SimpleNamespace(uid="t", model_ref=SEEDANCE, genlog_id=None, credits_charged=charged,
                                   provider_cost_usd="0.7623")

        self.assertIs(vp.check_margin(take(122)), True)
        self.assertIs(vp.check_margin(take(109)), True)    # ровно +25 %
        self.assertIs(vp.check_margin(take(108)), False)
        self.assertIsNone(vp.check_margin(take(0)))

    def test_vstudio_image_refs_line(self):
        from vstudio import caps as caps_mod
        from vstudio import pricing as vp

        flex = _image("black-forest-labs/flux.2-flex", "12", "0.06", "0.06", vstudio_enabled=True)
        caps = caps_mod.for_model(flex)
        compiled = SimpleNamespace(kind="image", errors=[], effective={}, billable_images=1, price_aspect=None)
        got = vp.price(compiled, flex, caps).to_dict()
        self.assertEqual(got["credits"], 20)
        self.assertEqual([(line["key"], line["credits"]) for line in got["breakdown"]],
                         [("price.image", 10), ("price.refs", 10)])
        self.assertEqual(vp.model_prices(flex, caps), {"price": None, "per_image": 10, "price_from": 10})


@override_settings(CACHES=TEST_CACHES)
class ChatImageTests(MarkupBase):
    """Картинки в чате (A_FIX): чат зовёт flux_charge_credits без числа фото, а Nano
    Banana списывает по токенам × тариф — ни то ни другое не должно уйти ниже себестоимости."""

    FLEX = "black-forest-labs/flux.2-flex"

    def test_chat_flux_edit_is_not_below_cost(self):
        from ai.handlers import _flux_charge_credits

        # Ровно та функция и тот вызов, что в ai/handlers.py (:2930, :3552): только модель.
        self.assertIs(_flux_charge_credits, flux_charge_credits)
        flex = _image(self.FLEX, "12", "0.06", "0.06")
        self.assertEqual(_flux_charge_credits(flex), 20)
        self.assertEqual(_flux_charge_credits(flex), pricing.image_credits(flex, 1))
        # Правка с одним фото — не дешевле себестоимости 0.06 + 0.06 с порогом 25 %.
        credit = pricing.credit_usd()
        self.assertGreaterEqual(_flux_charge_credits(flex) * credit, Decimal("0.12") * Decimal("1.25"))
        # Когда чат начнёт передавать число фото: без фото 10, с тремя ⌈0.24 × 1.4 / credit⌉ = 39.
        self.assertEqual(flux_charge_credits(flex, refs=0), 10)
        self.assertEqual(flux_charge_credits(flex, refs=3), 39)
        # Модели без платы за фото не дорожают от неизвестного числа фото.
        klein = _image("black-forest-labs/flux.2-klein-4b", "2", "0.015")
        self.assertEqual(flux_charge_credits(klein), flux_charge_credits(klein, refs=0))
        self.assertEqual(flux_charge_credits(klein), 3)

    def test_chat_flux_in_legacy_is_unchanged(self):
        set_runtime(pricing.KEY_MODE, pricing.MODE_LEGACY)
        pricing.invalidate_price_caches()
        flex = _image(self.FLEX, "12", "0.06", "0.06")
        for refs in (None, 0, 1, 8):
            with self.subTest(refs=refs):
                self.assertEqual(flux_charge_credits(flex, refs=refs), 12)

    def test_chat_image_price(self):
        flex = _image(self.FLEX, "12", "0.06", "0.06")
        self.assertEqual(pricing.chat_image_price(flex), pricing.ChatImagePrice("image", 20, 1, None))
        # Nano Banana в чате — токены × тариф в обоих режимах: ⌈1450 × 4 / 1000⌉ = 6 (PLAN §3.3 «≈6 в чате»).
        nano = _image(NANO, "4", "0.039")
        self.assertEqual(pricing.chat_image_tokens(), 1450)
        self.assertEqual(pricing.chat_image_price(nano), pricing.ChatImagePrice("tokens", 6, 0, 1450))
        legacy = pricing.current_config().with_changes(mode=pricing.MODE_LEGACY)
        self.assertEqual(pricing.chat_image_price(nano, cfg=legacy).credits, 6)
        pro = _image("google/gemini-3-pro-image", "12", "0.134")
        self.assertEqual(pricing.chat_image_price(pro).credits, 18)
        with override_settings(CREDIT_CALC_IMAGE_OUTPUT_TOKENS_ESTIMATE=1850):
            self.assertEqual(pricing.chat_image_price(nano).credits, 8)

    def test_chat_image_tariff_gives_the_markup_price(self):
        # Тариф для чата из цены по наценке: 7 × 1000 / 1450 = 4.8275… → 4.827 (вниз).
        cells = ((NANO, "0.039", 7, "4.827"), ("google/gemini-3-pro-image", "0.134", 22, "15.172"),
                 ("google/gemini-3.1-flash-image", "0.067", 11, "7.586"))
        for orid, unit, credits, coeff in cells:
            with self.subTest(model=orid):
                model = _image(orid, "4", unit)
                tariff = pricing.chat_image_tariff(model)
                self.assertEqual((tariff.credits, tariff.coefficient, tariff.tokens, tariff.cost_usd),
                                 (credits, Decimal(coeff), 1450, Decimal(unit)))
                self.assertEqual(tariff.credits, pricing.image_credits(model))
                GPTModels.objects.filter(pk=model.pk).update(markup_coefficient=tariff.coefficient)
                model.refresh_from_db()
                self.assertEqual(pricing.chat_image_price(model).credits, credits)
                # Вверх на 0,001 — уже на кредит больше: потому и вниз.
                self.assertEqual(pricing.chat_token_charge(1450, tariff.coefficient + Decimal("0.001")),
                                 credits + 1)
        # Своя наценка модели и общая доходят до тарифа.
        nano = GPTModels.objects.get(openrouter_id=NANO)
        GPTModels.objects.filter(pk=nano.pk).update(markup_pct=Decimal("100"))
        nano.refresh_from_db()
        self.assertEqual(pricing.chat_image_tariff(nano).credits, 9)
        legacy = pricing.current_config().with_changes(mode=pricing.MODE_LEGACY, markup_pct=Decimal("60"))
        self.assertEqual(pricing.chat_image_tariff(_image("google/x-image", "4", "0.039"), cfg=legacy).credits, 8)

    def test_chat_image_tariff_refusals(self):
        with self.assertRaisesMessage(ValueError, "нет себестоимости картинки"):
            pricing.chat_image_tariff(_image("google/no-cost-image", "4"))
        TokenPackage.objects.update(is_active=False)
        pricing.invalidate_price_caches()
        with self.assertRaisesMessage(ValueError, "нет ни одного пакета с ценой"):
            pricing.chat_image_tariff(_image(NANO, "4", "0.039"))


@override_settings(TOKEN_CREDIT_DIVISOR=1000)
class TariffForCreditsTests(SimpleTestCase):
    """tariff_for_credits: tokens токенов в чате (и Decimal, и float, как ai.handlers) стоят ровно credits."""

    def test_sweep(self):
        from ai.handlers import _compute_charge

        for tokens in (1, 3, 7, 999, 1000, 1290, 1450, 1451, 2000, 4096, 10000, 1_000_000):
            for credits in range(1, 400):
                with self.subTest(tokens=tokens, credits=credits):
                    try:
                        coeff = pricing.tariff_for_credits(credits, tokens)
                    except ValueError:
                        self.assertGreater(Decimal(credits) * 1000 / tokens, pricing.TEXT_COEFF_MAX)
                        continue
                    if Decimal(credits) * 1000 / tokens < pricing.TEXT_COEFF_MIN:
                        continue
                    self.assertEqual(pricing.chat_token_charge(tokens, coeff), credits)
                    self.assertEqual(pricing.text_message_credits(coeff, tokens), credits)
                    if credits % 37 == 0:
                        charged = _compute_charge({"markup_coefficient": float(coeff), "total_tokens": tokens},
                                                  [], "", web_search=False)[0]
                        self.assertEqual(charged, credits)

    def test_exact_values(self):
        self.assertEqual(pricing.tariff_for_credits(7, 1450), Decimal("4.827"))
        self.assertEqual(pricing.tariff_for_credits(29, 1450), Decimal("20"))
        self.assertEqual(pricing.chat_token_charge(1450, "4.828"), 8)
        with self.assertRaises(ValueError):
            pricing.tariff_for_credits(1, 1)


@override_settings(CACHES=TEST_CACHES)
class TextCoefficientTests(MarkupBase):
    """Тариф текста из цен OpenRouter за токен (пересчёт по кнопке в админке)."""

    def test_gpt4o(self):
        # $2.5 / $10 за 1M: (0.31·2.5 + 0.69·10)e-6 × 1000 × 1.4 / credit = 1.2233… → 1.224 (PLAN §3.4).
        self.assertEqual(pricing.derived_text_coeff("0.0000025", "0.00001"), Decimal("1.224"))
        self.assertEqual(pricing.text_message_credits(Decimal("1.224"), 2000), 3)
        self.assertEqual(pricing.text_message_credits(Decimal("0.097"), 2000), 1)

    def test_free_model_is_not_zero_and_too_expensive_is_refused(self):
        self.assertEqual(pricing.derived_text_coeff("0", "0"), Decimal("0.001"))
        with self.assertRaises(ValueError):
            pricing.derived_text_coeff("0.01", "0.01")
        with self.assertRaises(ValueError):
            pricing.derived_text_coeff(None, "0.00001")

    def test_catalog_is_cached_and_survives_failures(self):
        rows = [{"id": "openai/gpt-4o", "pricing": {"prompt": "0.0000025", "completion": "0.00001"}},
                {"id": "x/free", "pricing": {"prompt": "0", "completion": "0"}}]
        good = MagicMock(ok=True)
        good.json.return_value = {"data": rows}
        bad = MagicMock(ok=False)
        bad.json.return_value = {"error": {"code": 502}}
        with patch("requests.get", return_value=good) as get:
            self.assertEqual(pricing.openrouter_models_catalog(), rows)
            self.assertEqual(pricing.openrouter_models_catalog(), rows)
            self.assertEqual(get.call_count, 1)
            self.assertEqual(get.call_args.args[0], "https://openrouter.ai/api/v1/models")
        cache.delete(pricing.TEXT_CATALOG_KEY)
        with patch("requests.get", return_value=bad):
            self.assertEqual(pricing.openrouter_models_catalog(), rows)   # прошлая удачная копия
        price = pricing.text_model_prices("openai/gpt-4o:online")
        self.assertEqual((price.prompt, price.completion), (Decimal("0.0000025"), Decimal("0.00001")))
        self.assertEqual(price.per_million(), (Decimal("2.5000000"), Decimal("10.00000")))
        self.assertIsNone(pricing.text_model_prices("nope/model"))


class MigrationPrefillTests(TestCase):
    def test_only_empty_fields_of_known_models(self):
        import importlib

        from django.apps import apps

        migration = importlib.import_module("ai.migrations.0027_pricing_markup")
        klein = _image("black-forest-labs/flux.2-klein-4b", "2")
        flex = _image("black-forest-labs/flux.2-flex", "12")
        nano = _image(NANO, "4", unit="0.05")                 # владелец уже задал свою
        nano2 = _image("google/gemini-3.1-flash-image-preview", "6")
        other = _image("black-forest-labs/flux.1-dev", "1")
        migration.prefill_image_costs(apps, None)
        for row in (klein, flex, nano, nano2, other):
            row.refresh_from_db()
        self.assertEqual((klein.unit_cost_usd, klein.ref_cost_usd), (Decimal("0.015"), None))
        self.assertEqual((flex.unit_cost_usd, flex.ref_cost_usd), (Decimal("0.06"), Decimal("0.06")))
        self.assertEqual(nano.unit_cost_usd, Decimal("0.05"))
        # Nano Banana 2 (vstudio/caps.py: nano_banana_2) — тоже с себестоимостью, не «нет себестоимости».
        self.assertEqual((nano2.unit_cost_usd, nano2.ref_cost_usd), (Decimal("0.067"), None))
        self.assertIsNone(other.unit_cost_usd)


class PureHelpersTests(SimpleTestCase):
    def test_unknown_cost(self):
        self.assertIsNone(pricing.to_cost(None))
        self.assertIsNone(pricing.to_cost("-1"))
        self.assertIsNone(pricing.to_cost("abc"))
        self.assertEqual(pricing.to_cost(0.7623000000000001), Decimal("0.762300000"))
        with self.assertRaises(pricing.PriceUnavailable):
            pricing.credits_for_cost(None, cfg=pricing.PricingConfig(mode="markup"))

    def test_legacy_image_price(self):
        for coeff, want in (("2.9", 2), ("0", 1), (None, 1), ("12", 12)):
            self.assertEqual(pricing.legacy_image_credits(SimpleNamespace(markup_coefficient=coeff)), want)
        legacy = pricing.PricingConfig()
        self.assertEqual(pricing.image_credits(SimpleNamespace(markup_coefficient="4", unit_cost_usd="0.039"),
                                               cfg=legacy), 4)


@override_settings(CACHES=TEST_CACHES)
class SampleTests(MarkupBase):
    """Цена типичной генерации в обоих режимах — для «Моделей» и превью настроек."""

    def test_video_sample_snaps_to_what_the_model_shoots(self):
        sample = pricing.model_sample(_video(SEEDANCE))
        self.assertEqual(sample.to_dict(), {"kind": "video", "shape": {"seconds": 5, "resolution": "720p",
                                                                       "aspect": "16:9"},
                                            "cost_usd": "0.7623", "legacy": 145, "markup": 122, "flags": []})
        veo = pricing.model_sample(_video("google/veo-3.1-lite", "17"))
        self.assertEqual((veo.shape["seconds"], veo.legacy, veo.markup), (4, 68, 32))
        hailuo = pricing.model_sample(_video("minimax/hailuo-2.3", "17"))
        self.assertEqual((hailuo.shape, hailuo.markup), ({"seconds": 6, "resolution": "1080p", "aspect": "16:9"}, 79))

    def test_video_without_cost(self):
        sample = pricing.model_sample(_video("openai/sora-2-pro", "62"))
        self.assertEqual((sample.cost_usd, sample.legacy, sample.markup, sample.flags), (None, 310, None, ("no_cost",)))

    def test_preview_with_unsaved_settings(self):
        model = _video(SEEDANCE, markup_pct=Decimal("10"))
        sample = pricing.model_sample(model, cfg=pricing.current_config().with_changes(floor_pct=Decimal("0")))
        self.assertEqual((sample.markup, sample.flags), (96, ()))
        self.assertEqual(pricing.model_sample(model).flags, ("floor",))
        self.assertEqual(pricing.model_sample(model).active(), 109)

    def test_image_and_text_samples(self):
        klein = pricing.model_sample(_image("black-forest-labs/flux.2-klein-4b", "2", "0.015"))
        self.assertEqual((klein.legacy, klein.markup, klein.flags, str(klein.cost_usd)), (2, 3, (), "0.015000000"))
        bare = pricing.model_sample(_image("black-forest-labs/flux.2-pro", "4"))
        self.assertEqual((bare.legacy, bare.markup, bare.flags), (4, 4, ("no_cost",)))
        text = GPTModels.objects.create(name="GPT-4o", openrouter_id="openai/gpt-4o", category="chat",
                                        markup_coefficient=Decimal("17"), max_tokens=1)
        self.assertEqual(pricing.model_sample(text).to_dict(),
                         {"kind": "text", "shape": {"tokens": 2000}, "cost_usd": None, "legacy": 34, "markup": 34,
                          "flags": []})
