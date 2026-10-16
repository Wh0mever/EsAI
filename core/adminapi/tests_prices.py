# -*- coding: utf-8 -*-
"""Цены и наценка в панели (adminapi/prices.py, BUILD_A решение 9).

Курс 87.4 сома за доллар (живой, замокан), пакеты прода (самый дешёвый кредит —
MASTER), каталоги OpenRouter — сохранённый видео-каталог и маленький
текстовый; сети нет: requests.get падает, если его кто-то позовёт.
"""
from __future__ import annotations

from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase, override_settings
from django.urls import reverse
from rest_framework.test import APIClient

from adminapi.models import AppSetting
from adminapi.runtime import set_runtime
from ai import pricing
from ai.models import GPTModels
from ai.tests_pricing_golden import TEST_CACHES, create_packages, start_price_mocks
from audit.models import AdminActionLog
from plans.models import TokenPackage

SEEDANCE = "bytedance/seedance-2.0"
MINI = "bytedance/seedance-2.0-mini"
NANO = "google/gemini-2.5-flash-image"

TEXT_CATALOG = [
    {"id": "openai/gpt-4o", "name": "OpenAI: GPT-4o", "description": "Флагман OpenAI.",
     "architecture": {"input_modalities": ["text", "image"], "output_modalities": ["text"]},
     "pricing": {"prompt": "0.0000025", "completion": "0.00001"}},
    {"id": "deepseek/deepseek-chat", "name": "DeepSeek: DeepSeek V3",
     "architecture": {"input_modalities": ["text"], "output_modalities": ["text"]},
     "pricing": {"prompt": "0.0000003", "completion": "0.00000088"}},
    {"id": "anthropic/claude-opus-x", "name": "Anthropic: Claude Opus X",
     "architecture": {"modality": "text+image->text"},
     "pricing": {"prompt": "0.000015", "completion": "0.000075"}},
    {"id": NANO, "name": "Google: Gemini 2.5 Flash Image (Nano Banana)",
     "architecture": {"input_modalities": ["image", "text"], "output_modalities": ["image", "text"]},
     "pricing": {"prompt": "0.0000003", "completion": "0.0000025"}},
    {"id": "black-forest-labs/flux.2-klein-9b", "name": "Black Forest Labs: FLUX.2 Klein 9B",
     "architecture": {"input_modalities": ["text", "image"], "output_modalities": ["image"]},
     "pricing": {"prompt": "0", "completion": "0"}},
    {"id": "openai/text-embedding-3-small", "name": "OpenAI: Embeddings",
     "architecture": {"input_modalities": ["text"], "output_modalities": ["embeddings"]},
     "pricing": {"prompt": "0.00000002", "completion": "0"}},
    # Есть и в видео-каталоге: остаётся видео.
    {"id": MINI, "name": "ByteDance: Seedance 2.0 Mini",
     "architecture": {"input_modalities": ["text", "image"], "output_modalities": ["video"]},
     "pricing": {}},
]


def _model(orid, name, category, coeff, **extra):
    return GPTModels.objects.create(name=name, openrouter_id=orid, category=category,
                                    markup_coefficient=Decimal(coeff), max_tokens=4096,
                                    is_active=extra.pop("is_active", True), **extra)


@override_settings(CACHES=TEST_CACHES, STUDIO_SCENE_CREDITS=0, VIDEO_MIN_MARGIN=0.4)
class PricesCase(TestCase):
    def setUp(self):
        cache.clear()
        start_price_mocks(self)
        net = patch("requests.get", side_effect=AssertionError("сеть в тестах панели запрещена"))
        self.net = net.start()
        self.addCleanup(net.stop)
        text = patch("ai.pricing.openrouter_models_catalog", return_value=TEXT_CATALOG)
        self.text_catalog = text.start()
        self.addCleanup(text.stop)
        create_packages()
        User = get_user_model()
        self.staff = User.objects.create_user(email="admin@example.com", password="x-12345678", is_staff=True)
        self.user = User.objects.create_user(email="user@example.com", password="x-12345678")
        self.seedance = _model(SEEDANCE, "Seedance 2.0", "video", "0", cartoon_stage="video",
                               vstudio_enabled=True, sort_order=10)
        self.kling = _model("kwaivgi/kling-v3.0-std", "Kling 3.0", "video", "26", sort_order=11)
        self.veo_lite = _model("google/veo-3.1-lite", "Veo 3.1 Lite", "video", "17", sort_order=12)
        self.sora = _model("openai/sora-2-pro", "Sora 2 Pro", "video", "62", sort_order=13)
        self.klein = _model("black-forest-labs/flux.2-klein-4b", "FLUX Klein", "image", "2",
                            unit_cost_usd=Decimal("0.015"), sort_order=20)
        self.flex = _model("black-forest-labs/flux.2-flex", "FLUX Flex", "image", "12",
                           unit_cost_usd=Decimal("0.06"), ref_cost_usd=Decimal("0.06"), sort_order=21)
        self.pro = _model("black-forest-labs/flux.2-pro", "FLUX Pro", "image", "4", sort_order=22)
        self.nano = _model(NANO, "Nano Banana", "image", "4", unit_cost_usd=Decimal("0.039"),
                           cartoon_stage="image", sort_order=23)
        self.gpt4o = _model("openai/gpt-4o", "GPT-4o", "chat", "17", supports_vision=True, sort_order=30)
        self.deepseek = _model("deepseek/deepseek-chat", "DeepSeek V3", "budget", "0.078", sort_order=31)
        self.no_price = _model("acme/no-price", "Без цены", "chat", "2", sort_order=32)
        self.sleeping = _model("acme/sleeping", "Выключенная", "chat", "5", is_active=False, sort_order=33)
        self.api = APIClient()
        self.api.force_authenticate(self.staff)

    def tearDown(self):
        self.assertFalse(self.net.called, "панель полезла в сеть")

    def url(self, name, *args):
        return reverse(f"adminapi:{name}", args=args)

    def markup_mode(self, **runtime):
        set_runtime(pricing.KEY_MODE, pricing.MODE_MARKUP)
        for key, value in runtime.items():
            set_runtime(key, value)
        pricing.invalidate_price_caches()

    def log(self):
        return AdminActionLog.objects.order_by("-id").first()


class PermissionsTests(PricesCase):
    ENDPOINTS = (("get", "pricing"), ("patch", "pricing"), ("post", "pricing-preview"),
                 ("get", "models-catalog"), ("post", "models-list"), ("get", "models-text-recompute"),
                 ("post", "models-text-recompute"), ("get", "models-chat-image-recompute"),
                 ("post", "models-chat-image-recompute"))

    def test_staff_only(self):
        anonymous = APIClient()
        member = APIClient()
        member.force_authenticate(self.user)
        for method, name in self.ENDPOINTS:
            with self.subTest(endpoint=name, method=method):
                self.assertEqual(getattr(anonymous, method)(self.url(name), {}, format="json").status_code, 401)
                self.assertEqual(getattr(member, method)(self.url(name), {}, format="json").status_code, 403)
        self.assertFalse(AppSetting.objects.exists())
        self.assertEqual(GPTModels.objects.count(), 12)


class PricingSettingsTests(PricesCase):
    def get_samples(self, body):
        return {row["key"]: row for row in body["samples"]}

    def test_get_defaults_basis_and_samples(self):
        res = self.api.get(self.url("pricing"))
        self.assertEqual(res.status_code, 200)
        body = res.json()
        self.assertEqual((body["mode"], body["markup_pct"], body["floor_pct"], body["kgs_per_usd"]),
                         ("legacy", "40", "25", None))
        self.assertEqual(body["live_kgs_per_usd"], "87.4")
        self.assertFalse(body["rate_warning"])
        self.assertFalse(body["preview"])
        self.assertEqual(body["effective_markup_pct"], "40")
        self.assertEqual(body["basis"]["package"], "MASTER")
        self.assertEqual(body["basis"]["kgs_per_credit"], "0.76769")
        self.assertEqual(body["basis"]["rate_source"], "live")
        self.assertEqual(body["basis_line"], "MASTER · 0,768 сом = $0,00878")
        self.assertEqual(body["defaults"], {"mode": "legacy", "markup_pct": "40", "floor_pct": "25"})
        self.assertEqual(body["limits"], {"pct_min": "0", "pct_max": "1000", "rate_min": "1",
                                          "rate_max": "100000"})
        self.assertEqual(body["studio_scene_credits"], 0)

        samples = self.get_samples(body)
        cells = {"seedance_720_5": (145, 122), "mini_480_5": (33, 28), "mini_720_5": (73, 61),
                 "kling_720_5": (130, 101), "veo_lite_720_4": (68, 32), "flux_klein": (2, 3),
                 "flux_flex_edit": (12, 20), "nano_frame": (4, 7), "cartoon_scene": (149, 129),
                 "gpt4o_message": (34, 34)}
        self.assertEqual(list(samples), list(cells))
        for key, (legacy, markup) in cells.items():
            with self.subTest(sample=key):
                self.assertEqual((samples[key]["legacy"], samples[key]["markup"]), (legacy, markup))
                self.assertEqual(samples[key]["active"], legacy)
        seedance = samples["seedance_720_5"]
        self.assertEqual(seedance["label"], "Seedance 2.0 · 5 с 720p")
        self.assertEqual(seedance["cost_usd"], "0.7623")
        self.assertEqual(seedance["cost_text"], "$0,76")
        self.assertEqual(seedance["delta_pct"], -15.9)
        self.assertEqual(seedance["model"], {"id": self.seedance.pk, "openrouter_id": SEEDANCE,
                                             "name": "Seedance 2.0", "is_active": True})
        # Mini ещё не заведена: цена из каталога, тариф 1, отметка not_in_db.
        self.assertEqual(samples["mini_480_5"]["flags"], ["not_in_db"])
        self.assertIsNone(samples["mini_480_5"]["model"]["id"])
        self.assertEqual(samples["veo_lite_720_4"]["shape"], {"seconds": 4, "resolution": "720p",
                                                              "aspect": "16:9"})
        self.assertEqual(samples["flux_flex_edit"]["label"], "FLUX Flex · правка с 1 фото")
        self.assertEqual(samples["cartoon_scene"]["label"], "Сцена мультфильма · Seedance 2.0 · 5 с 720p")
        self.assertEqual(samples["cartoon_scene"]["cost_usd"], "0.8013")
        self.assertEqual(samples["nano_frame"]["label"], "Nano Banana · кадр сцены")
        gpt = samples["gpt4o_message"]
        self.assertEqual(gpt["label"], "GPT-4o · сообщение 2000 токенов")
        # Режим тариф текста не меняет; что даст «Пересчитать тарифы текста» — рядом.
        self.assertEqual((gpt["cost_usd"], gpt["cost_text"], gpt["after_recompute"]), ("0.01535", "$0,0154", 3))
        self.assertIsNone(seedance["after_recompute"])

        without = {row["openrouter_id"]: row for row in body["models_without_cost"]}
        self.assertEqual(set(without), {"openai/sora-2-pro", "black-forest-labs/flux.2-pro"})
        warnings = {w["code"]: w["text"] for w in body["warnings"]}
        self.assertEqual(list(warnings), ["no_cost", "flux_chat_refs", "chat_image_tokens"])
        self.assertIn("Моделей без себестоимости: 2", warnings["no_cost"])
        # Чат не передаёт число фото: правка Flex в режиме «наценка» — как с одним фото.
        self.assertIn("правка в чате идёт как с 1 фото (FLUX Flex — 20 кр). С 2 фото и больше",
                      warnings["flux_chat_refs"])
        # Чат Nano Banana — 6 кр по тарифу, по наценке картинка 7 кр: кнопка выравнивает (в legacy — после
        # переключения).
        self.assertEqual(warnings["chat_image_tokens"],
                         "Картинки в чате у Nano Banana списываются по токенам — тариф модели × ~1450 токенов "
                         "(сейчас Nano Banana ≈6 кр). По наценке картинка стоит: Nano Banana — 7 кр. Наценка сама "
                         "тариф не меняет: выровняйте его после переключения кнопкой «Пересчитать тариф картинок "
                         "в чате» в «Моделях».")

    def test_missing_models_are_flagged_not_invented(self):
        self.klein.delete()
        self.gpt4o.delete()
        samples = self.get_samples(self.api.get(self.url("pricing")).json())
        for key in ("flux_klein", "gpt4o_message"):
            with self.subTest(sample=key):
                self.assertEqual((samples[key]["legacy"], samples[key]["markup"], samples[key]["flags"]),
                                 (None, None, ["not_in_db"]))

    def test_flux_edit_preview_is_what_the_chat_charges(self):
        from ai.handlers import _flux_charge_credits

        self.markup_mode()
        row = self.get_samples(self.api.get(self.url("pricing")).json())["flux_flex_edit"]
        self.flex.refresh_from_db()
        # Чат зовёт списание только с моделью — превью «правка с 1 фото» равно ему.
        self.assertEqual((row["active"], _flux_charge_credits(self.flex)), (20, 20))

    def test_patch_saves_audits_and_invalidates(self):
        cache.set("vstudio:models:v1:paid", ["stale"], 600)
        cache.set("video_cost:credit_usd", 0.5, 600)
        version = cache.get("pricing:ver") or 1
        with self.captureOnCommitCallbacks(execute=True) as callbacks:
            res = self.api.patch(self.url("pricing"), {"mode": "markup", "markup_pct": "35,5", "floor_pct": 20,
                                                       "kgs_per_usd": "87,5"}, format="json")
        self.assertEqual(res.status_code, 200, res.content)
        self.assertTrue(callbacks, "сброс кэша после фиксации не зарегистрирован")
        stored = dict(AppSetting.objects.values_list("key", "value"))
        self.assertEqual(stored, {"pricing_mode": "markup", "price_markup_pct": "35.50",
                                  "price_floor_pct": "20.00", "price_kgs_per_usd": "87.5"})
        body = res.json()
        self.assertEqual((body["mode"], body["markup_pct"], body["floor_pct"], body["kgs_per_usd"]),
                         ("markup", "35.5", "20", "87.5"))
        self.assertEqual(body["basis"]["rate_source"], "pinned")
        self.assertEqual(body["changed"], {"mode": "markup", "markup_pct": "35.50", "floor_pct": "20.00",
                                           "kgs_per_usd": "87.5"})
        self.assertEqual(self.get_samples(body)["seedance_720_5"]["active"],
                         self.get_samples(body)["seedance_720_5"]["markup"])
        log = self.log()
        self.assertEqual((log.action, log.actor_id, log.target_type), ("settings.edit", self.staff.pk, ""))
        self.assertEqual(log.before, {"pricing": {"mode": None, "markup_pct": None, "floor_pct": None,
                                                  "kgs_per_usd": None}})
        self.assertEqual(log.after["pricing"]["mode"], "markup")
        self.assertIsNone(cache.get("vstudio:models:v1:paid"))
        self.assertIsNone(cache.get("video_cost:credit_usd"))
        self.assertGreater(cache.get("pricing:ver"), version)
        self.assertEqual(pricing.current_config().mode, "markup")

    def test_blank_rate_means_live_and_pin_live(self):
        set_runtime(pricing.KEY_KGS_PER_USD, "90")
        res = self.api.patch(self.url("pricing"), {"kgs_per_usd": ""}, format="json")
        self.assertEqual(res.status_code, 200, res.content)
        self.assertFalse(AppSetting.objects.filter(key="price_kgs_per_usd").exists())
        self.assertIsNone(res.json()["kgs_per_usd"])
        res = self.api.patch(self.url("pricing"), {"pin_live_rate": True}, format="json")
        self.assertEqual(res.status_code, 200, res.content)
        self.assertEqual(AppSetting.objects.get(key="price_kgs_per_usd").value, "87.4")
        self.assertEqual(res.json()["changed"], {"kgs_per_usd": "87.4"})

    def test_same_values_write_nothing(self):
        set_runtime(pricing.KEY_MARKUP_PCT, "40.00")
        res = self.api.patch(self.url("pricing"), {"markup_pct": "40"}, format="json")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json()["changed"], {})
        self.assertFalse(AdminActionLog.objects.exists())

    def test_validation_is_all_or_nothing(self):
        cases = (
            ({"mode": "markup", "markup_pct": 1001}, "markup_pct", "Наценка: от 0 до 1000 %."),
            ({"floor_pct": "много"}, "floor_pct", "Нижний порог: нужно число от 0 до 1000."),
            ({"mode": "cheap"}, "mode", "Режим цен: legacy или markup."),
            ({"kgs_per_usd": "0.5"}, "kgs_per_usd",
             "Курс: сколько сомов за доллар, например 87.5. Пусто — живой курс."),
            ({"markup_pct": True}, "markup_pct", "Наценка: нужно число от 0 до 1000."),
            ({"pin_live_rate": "да"}, "pin_live_rate", "«Закрепить текущий курс»: true или false."),
            ({"pin_live_rate": True, "kgs_per_usd": "88"}, "pin_live_rate",
             "Либо курс, либо «Закрепить текущий» — не оба сразу."),
            ({"mode": "markup", "margin": 5}, "__all__",
             "Неизвестное поле: margin. Можно: mode, markup_pct, floor_pct, kgs_per_usd, pin_live_rate"),
            ({}, "__all__", "Нечего менять."),
        )
        for body, field, message in cases:
            with self.subTest(body=body):
                res = self.api.patch(self.url("pricing"), body, format="json")
                self.assertEqual(res.status_code, 400)
                self.assertEqual(res.json()["errors"][field], message)
                self.assertIn(message, res.json()["detail"])
        res = self.api.patch(self.url("pricing"), [1, 2], format="json")
        self.assertEqual(res.status_code, 400)
        self.assertFalse(AppSetting.objects.exists())
        self.assertFalse(AdminActionLog.objects.exists())

    def test_preview_uses_unsaved_values(self):
        for res in (self.api.patch(self.url("pricing") + "?preview=1", {"mode": "markup", "markup_pct": 30},
                                   format="json"),
                    self.api.post(self.url("pricing-preview"), {"mode": "markup", "markup_pct": 30},
                                  format="json")):
            self.assertEqual(res.status_code, 200, res.content)
            body = res.json()
            self.assertTrue(body["preview"])
            self.assertEqual((body["mode"], body["markup_pct"]), ("markup", "30"))
            seedance = self.get_samples(body)["seedance_720_5"]
            self.assertEqual((seedance["legacy"], seedance["markup"], seedance["active"]), (145, 113, 113))
        self.assertFalse(AppSetting.objects.exists())
        self.assertFalse(AdminActionLog.objects.exists())
        self.assertEqual(pricing.current_config().mode, "legacy")
        # Пустое превью — сохранённые настройки.
        res = self.api.post(self.url("pricing-preview"), {}, format="json")
        self.assertEqual((res.status_code, res.json()["mode"]), (200, "legacy"))
        res = self.api.post(self.url("pricing-preview"), {"markup_pct": -1}, format="json")
        self.assertEqual(res.status_code, 400)

    def test_floor_beats_lower_markup_and_warns(self):
        res = self.api.post(self.url("pricing-preview"), {"markup_pct": 10, "floor_pct": 25}, format="json")
        body = res.json()
        self.assertEqual(body["effective_markup_pct"], "25")
        seedance = self.get_samples(body)["seedance_720_5"]
        self.assertEqual(seedance["markup"], 109)
        self.assertIn("floor", seedance["flags"])
        codes = [w["code"] for w in body["warnings"]]
        self.assertIn("floor_above_markup", codes)
        warning = next(w for w in body["warnings"] if w["code"] == "floor_above_markup")
        self.assertEqual(warning["text"], "Общая наценка 10 % ниже порога 25 % — действует порог.")

    def test_pinned_rate_preview_and_weaker_live_rate_warning(self):
        body = self.api.post(self.url("pricing-preview"), {"kgs_per_usd": "85"}, format="json").json()
        self.assertEqual(body["basis"]["rate_source"], "pinned")
        self.assertTrue(body["rate_warning"])
        warning = next(w for w in body["warnings"] if w["code"] == "rate_weaker")
        self.assertEqual(warning["text"], "Живой курс 87,4 сом/$ слабее закреплённого 85 больше чем на 2 %: "
                                          "кредит в долларах дешевле, чем считают цены. Перезакрепите курс.")

    def test_no_priced_package(self):
        TokenPackage.objects.update(is_active=False)
        pricing.invalidate_price_caches()
        body = self.api.get(self.url("pricing")).json()
        self.assertIsNone(body["basis"])
        self.assertEqual(body["basis_line"], "Нет активного пакета с ценой")
        self.assertIn("no_basis", [w["code"] for w in body["warnings"]])
        self.assertIsNone(self.get_samples(body)["seedance_720_5"]["markup"])

    def test_package_edit_moves_prices_at_once(self):
        before = self.api.get(self.url("pricing")).json()["basis"]["credit_usd"]
        master = TokenPackage.objects.get(name="MASTER")
        res = self.api.patch(self.url("packages-detail", master.pk), {"price": 3990}, format="json")
        self.assertEqual(res.status_code, 200)
        after = self.api.get(self.url("pricing")).json()["basis"]
        self.assertEqual(after["package"], "MASTER")
        self.assertNotEqual(after["credit_usd"], before)

    def test_settings_patch_of_scene_price_drops_price_caches(self):
        cache.set("vstudio:models:v1:paid", ["stale"], 600)
        res = self.api.patch(self.url("settings"), {"studio_scene_credits": 100}, format="json")
        self.assertEqual(res.status_code, 200)
        self.assertIsNone(cache.get("vstudio:models:v1:paid"))
        samples = self.get_samples(self.api.get(self.url("pricing")).json())
        # Цена сцены из админки (legacy) не опускает ниже себестоимости: 4 + 145.
        self.assertEqual(samples["cartoon_scene"]["legacy"], 149)


class ModelsColumnsTests(PricesCase):
    def rows(self):
        res = self.api.get(self.url("models-list"))
        self.assertEqual(res.status_code, 200)
        return {row["openrouter_id"]: row for row in res.json()}

    def test_columns_in_legacy_mode(self):
        rows = self.rows()
        seedance = rows[SEEDANCE]
        self.assertEqual((seedance["markup_pct"], seedance["unit_cost_usd"], seedance["ref_cost_usd"]),
                         (None, None, None))
        self.assertEqual(seedance["cost_sample"], "$0,76 · 5 с 720p")
        self.assertEqual(seedance["price_sample"], "145 кр · 5 с 720p")
        self.assertEqual(seedance["price_sample_other"], "при наценке: 122 кр")
        self.assertTrue(seedance["vstudio_supported"])
        self.assertEqual(seedance["pricing"]["kind"], "video")
        self.assertEqual((seedance["pricing"]["legacy"], seedance["pricing"]["markup"],
                          seedance["pricing"]["active"], seedance["pricing"]["mode"]), (145, 122, 145, "legacy"))
        self.assertEqual((seedance["pricing"]["markup_source"], seedance["pricing"]["effective_markup_pct"]),
                         ("global", "40"))

        flex = rows["black-forest-labs/flux.2-flex"]
        self.assertEqual((flex["unit_cost_usd"], flex["ref_cost_usd"]), (0.06, 0.06))
        self.assertEqual(flex["cost_sample"], "$0,06 за картинку + $0,06 за фото")
        self.assertEqual(flex["price_sample"], "12 кр · 1 картинка")
        # После переключения чат возьмёт за правку как с одним фото, а не как за «1 картинку».
        self.assertEqual(flex["price_sample_other"], "при наценке: 10 кр, в чате 20 кр (как правка с 1 фото)")
        self.assertEqual(flex["pricing"]["chat"], {"billing": "image", "credits": 12, "credits_markup": 20,
                                                   "refs": 1, "tokens": None, "target": None, "tariff": None})
        # Сегодня (legacy) правка с фото в чате — 12 кр при себестоимости 0.12: в убыток.
        self.assertIn("chat_below_cost", flex["pricing"]["flags"])
        klein = rows["black-forest-labs/flux.2-klein-4b"]
        self.assertEqual(klein["price_sample_other"], "при наценке: 3 кр")
        nano = rows[NANO]
        self.assertEqual(nano["price_sample_other"],
                         "при наценке: 7 кр · в чате ≈6 кр по токенам (по наценке 7 кр)")
        # target/tariff — что поставит «Пересчитать тариф картинок в чате»: 7 × 1000 / 1450 вниз до 0,001.
        self.assertEqual(nano["pricing"]["chat"], {"billing": "tokens", "credits": 6, "credits_markup": 6,
                                                   "refs": 0, "tokens": 1450, "target": 7, "tariff": "4.827"})
        self.assertNotIn("chat_below_cost", nano["pricing"]["flags"])
        # В legacy кнопка не работает — и флаг «ждёт пересчёта» не ставим.
        self.assertNotIn("chat_tariff_stale", nano["pricing"]["flags"])
        pro = rows["black-forest-labs/flux.2-pro"]
        self.assertEqual(pro["cost_sample"], "нет себестоимости")
        self.assertIn("no_cost", pro["pricing"]["flags"])
        # Кадр Nano Banana по 4 кр и FLUX Klein по 2 кр продаются дешевле себестоимости с порогом.
        self.assertIn("below_cost", rows[NANO]["pricing"]["flags"])
        self.assertIn("below_cost", rows["black-forest-labs/flux.2-klein-4b"]["pricing"]["flags"])
        self.assertNotIn("below_cost", flex["pricing"]["flags"])

        sora = rows["openai/sora-2-pro"]
        self.assertEqual((sora["cost_sample"], sora["price_sample"], sora["price_sample_other"]),
                         ("нет себестоимости", "310 кр · 5 с 720p", "при наценке: цены нет"))

        gpt = rows["openai/gpt-4o"]
        self.assertEqual(gpt["cost_sample"], "$2,50 / $10,00 за 1M")
        self.assertEqual(gpt["price_sample"], "34 кр · 2000 токенов")
        self.assertEqual(gpt["price_sample_other"], "после пересчёта: 3 кр")
        self.assertEqual(gpt["pricing"]["text"], {"prompt_per_m": "2.5", "completion_per_m": "10",
                                                  "message_cost_usd": "0.01535", "derived_coefficient": "1.224",
                                                  "derived_message_credits": 3})
        self.assertEqual(gpt["pricing"]["cost_usd"], "0.01535")
        self.assertFalse(gpt["vstudio_supported"])
        # Тариф DeepSeek 0.078 ниже себестоимости с порогом 25 % (≈0.100).
        self.assertIn("below_cost", rows["deepseek/deepseek-chat"]["pricing"]["flags"])
        self.assertIsNone(rows["acme/no-price"]["cost_sample"])
        self.assertIsNone(rows["acme/no-price"]["price_sample_other"])

    def test_columns_in_markup_mode(self):
        self.markup_mode()
        rows = self.rows()
        self.assertEqual(rows[SEEDANCE]["price_sample"], "122 кр · 5 с 720p")
        self.assertEqual(rows[SEEDANCE]["price_sample_other"], "по-старому: 145 кр")
        self.assertEqual(rows["openai/sora-2-pro"]["price_sample"], "цены нет · 5 с 720p")
        self.assertEqual(rows[NANO]["price_sample"], "7 кр · 1 картинка")
        self.assertNotIn("below_cost", rows[NANO]["pricing"]["flags"])
        # Чат Nano Banana по-прежнему по токенам × тариф: 6 кр, а не 7 — до кнопки пересчёта.
        self.assertEqual(rows[NANO]["price_sample_other"],
                         "по-старому: 4 кр · в чате ≈6 кр по токенам (по наценке 7 кр)")
        self.assertIn("chat_tariff_stale", rows[NANO]["pricing"]["flags"])
        flex = rows["black-forest-labs/flux.2-flex"]
        self.assertEqual(flex["price_sample"], "10 кр · 1 картинка")
        self.assertEqual(flex["price_sample_other"], "по-старому: 12 кр · в чате 20 кр (как правка с 1 фото)")
        self.assertNotIn("chat_below_cost", flex["pricing"]["flags"])

    def test_chat_image_tariff_below_cost_is_flagged(self):
        # Тариф Nano Banana обнулили: в чате картинка по 1 кр при себестоимости $0.039.
        self.markup_mode()
        GPTModels.objects.filter(pk=self.nano.pk).update(markup_coefficient=Decimal("0"))
        pricing.invalidate_price_caches()
        nano = self.rows()[NANO]
        self.assertEqual(nano["pricing"]["chat"]["credits"], 1)
        self.assertIn("chat_below_cost", nano["pricing"]["flags"])
        self.assertEqual(nano["price_sample_other"], "по-старому: 1 кр · в чате ≈1 кр по токенам (по наценке 7 кр)")
        warnings = {w["code"]: w["text"] for w in self.api.get(self.url("pricing")).json()["warnings"]}
        self.assertIn("По наценке картинка стоит: Nano Banana — 7 кр. Наценка сама тариф не меняет: выровняйте "
                      "его кнопкой «Пересчитать тариф картинок в чате» в «Моделях».", warnings["chat_image_tokens"])
        self.assertTrue(warnings["chat_image_tokens"].endswith("Ниже себестоимости с порогом: Nano Banana."))

    def test_patch_pricing_fields_audits_and_changes_price(self):
        self.markup_mode()
        cache.set("vstudio:models:v1:paid", ["stale"], 600)
        res = self.api.patch(self.url("models-detail", self.seedance.pk), {"markup_pct": "60"}, format="json")
        self.assertEqual(res.status_code, 200, res.content)
        body = res.json()
        self.assertEqual(body["markup_pct"], 60.0)
        self.assertEqual(body["pricing"]["markup"], 139)
        self.assertEqual(body["price_sample"], "139 кр · 5 с 720p")
        self.assertEqual(body["pricing"]["markup_source"], "model")
        self.seedance.refresh_from_db()
        self.assertEqual(self.seedance.markup_pct, Decimal("60"))
        self.assertIsNone(cache.get("vstudio:models:v1:paid"))
        log = self.log()
        self.assertEqual((log.action, log.target_type, log.target_id),
                         ("settings.edit", "ai.gptmodels", str(self.seedance.pk)))
        self.assertEqual((log.before, log.after), ({"model": {"markup_pct": None}}, {"model": {"markup_pct": "60.00"}}))
        # Пусто — снова общая наценка.
        res = self.api.patch(self.url("models-detail", self.seedance.pk), {"markup_pct": ""}, format="json")
        self.assertEqual((res.status_code, res.json()["markup_pct"], res.json()["pricing"]["markup"]),
                         (200, None, 122))

    def test_image_cost_accepts_comma(self):
        self.markup_mode()
        res = self.api.patch(self.url("models-detail", self.pro.pk), {"unit_cost_usd": "0,03"}, format="json")
        self.assertEqual(res.status_code, 200, res.content)
        self.assertEqual((res.json()["unit_cost_usd"], res.json()["pricing"]["markup"]), (0.03, 5))
        self.assertEqual(res.json()["cost_sample"], "$0,03 за картинку")

    def test_patch_validation(self):
        cases = (
            (self.seedance, {"markup_pct": 1001}, "markup_pct", "Наценка: от 0 до 1000 %; пусто — общая наценка"),
            (self.seedance, {"markup_pct": "abc"}, "markup_pct", "Наценка: от 0 до 1000 %; пусто — общая наценка"),
            (self.seedance, {"markup_pct": "12.345"}, "markup_pct", "Наценка: не больше 2 знаков после запятой"),
            (self.seedance, {"markup_pct": -1}, "markup_pct", "Наценка: от 0 до 1000 %; пусто — общая наценка"),
            (self.pro, {"unit_cost_usd": "-0.01"}, "unit_cost_usd",
             "Себестоимость картинки: сумма в долларах от 0 до 1000, например 0.039; пусто — не задана"),
            (self.pro, {"ref_cost_usd": "0.0000001"}, "ref_cost_usd",
             "Себестоимость входного фото: не больше 6 знаков после запятой"),
            (self.seedance, {"unit_cost_usd": "0.5"}, "unit_cost_usd",
             "Себестоимость за картинку задаётся только у моделей картинок (категория «Изображения»)"),
            (self.pro, {"unit_cost_usd": "0.5", "category": "chat"}, "unit_cost_usd",
             "Себестоимость за картинку задаётся только у моделей картинок (категория «Изображения»)"),
        )
        for model, body, field, message in cases:
            with self.subTest(body=body):
                res = self.api.patch(self.url("models-detail", model.pk), body, format="json")
                self.assertEqual(res.status_code, 400)
                self.assertEqual(res.json()["detail"][field], [message])
        self.assertFalse(AdminActionLog.objects.exists())
        self.seedance.refresh_from_db()
        self.assertIsNone(self.seedance.markup_pct)

    def test_vstudio_toggle_is_logged(self):
        res = self.api.patch(self.url("models-detail", self.kling.pk), {"vstudio_enabled": True}, format="json")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(self.log().after, {"model": {"vstudio_enabled": True}})


class CatalogAndAddTests(PricesCase):
    def test_search(self):
        res = self.api.get(self.url("models-catalog"), {"q": "mini"})
        self.assertEqual(res.status_code, 200)
        body = res.json()
        self.assertEqual(body["catalogs"], {"video": "ok", "text": "ok"})
        rows = {row["openrouter_id"]: row for row in body["results"]}
        mini = rows[MINI]
        self.assertEqual((mini["kind"], mini["category"], mini["name"], mini["exists"], mini["model_id"]),
                         ("video", "video", "Seedance 2.0 Mini", False, None))
        self.assertEqual((mini["cost_usd"], mini["cost_text"], mini["price_markup"]),
                         ("0.38115", "$0,38 · 5 с 720p", 61))
        self.assertTrue(mini["vstudio_supported"])
        self.assertEqual(sum(1 for row in body["results"] if row["openrouter_id"] == MINI), 1)

        res = self.api.get(self.url("models-catalog"), {"q": SEEDANCE})
        first = res.json()["results"][0]
        self.assertEqual((first["openrouter_id"], first["exists"], first["model_id"], first["is_active"]),
                         (SEEDANCE, True, self.seedance.pk, True))

        text = self.api.get(self.url("models-catalog"), {"kind": "text"}).json()
        self.assertEqual({row["kind"] for row in text["results"]}, {"text"})
        ids = {row["openrouter_id"] for row in text["results"]}
        self.assertNotIn("openai/text-embedding-3-small", ids)
        self.assertNotIn(MINI, ids)
        opus = next(row for row in text["results"] if row["openrouter_id"] == "anthropic/claude-opus-x")
        self.assertEqual((opus["cost_text"], opus["supports_vision"]), ("$15,00 / $75,00 за 1M", True))
        self.assertEqual((opus["coefficient"], opus["price_markup"]), ("8.990", 18))
        image = self.api.get(self.url("models-catalog"), {"kind": "image"}).json()["results"]
        self.assertEqual({row["openrouter_id"] for row in image}, {NANO, "black-forest-labs/flux.2-klein-9b"})

        self.assertEqual(self.api.get(self.url("models-catalog"), {"kind": "audio"}).status_code, 400)
        self.assertEqual(self.api.get(self.url("models-catalog"), {"q": "x" * 201}).status_code, 400)

    def test_add_video_model_inactive_with_tariff_one(self):
        top = GPTModels.objects.order_by("-sort_order").first().sort_order
        cache.set("vstudio:models:v1:paid", ["stale"], 600)
        res = self.api.post(self.url("models-list"), {"openrouter_id": MINI}, format="json")
        self.assertEqual(res.status_code, 201, res.content)
        body = res.json()
        row = body["model"]
        self.assertEqual((row["name"], row["category"], row["is_active"], row["vstudio_enabled"],
                          row["markup_coefficient"], row["markup_pct"], row["sort_order"], row["cartoon_stage"]),
                         ("Seedance 2.0 Mini", "video", False, False, 1.0, None, top + 10, ""))
        self.assertEqual(row["pricing"]["markup"], 61)
        self.assertTrue(row["vstudio_supported"])
        self.assertEqual(body["warnings"], ["Модель добавлена выключенной: включите её, когда проверите цену."])
        model = GPTModels.objects.get(openrouter_id=MINI)
        self.assertEqual((model.max_tokens, model.recommended, model.free_tier), (4096, False, False))
        log = self.log()
        self.assertEqual((log.action, log.target_id), ("settings.edit", str(model.pk)))
        self.assertEqual(log.after["model_add"]["kind"], "video")
        self.assertIsNone(cache.get("vstudio:models:v1:paid"))

        again = self.api.post(self.url("models-list"), {"openrouter_id": MINI}, format="json")
        self.assertEqual(again.status_code, 409)
        self.assertEqual(again.json(), {"detail": "Модель «Seedance 2.0 Mini» уже есть в списке.",
                                        "model_id": model.pk})

    def test_add_text_and_image_models(self):
        res = self.api.post(self.url("models-list"), {"openrouter_id": "anthropic/claude-opus-x"}, format="json")
        self.assertEqual(res.status_code, 201, res.content)
        row = res.json()["model"]
        self.assertEqual((row["name"], row["category"], row["supports_vision"], row["markup_coefficient"]),
                         ("Claude Opus X", "chat", True, 1.0))
        self.assertIn("Тариф 1 кр за 1000 токенов. Перед включением задайте тариф или нажмите "
                      "«Пересчитать тарифы текста». По себестоимости с наценкой выходит 8,990.",
                      res.json()["warnings"])
        res = self.api.post(self.url("models-list"), {"openrouter_id": "black-forest-labs/flux.2-klein-9b",
                                                      "name": "FLUX Klein 9B"}, format="json")
        self.assertEqual(res.status_code, 201, res.content)
        row = res.json()["model"]
        self.assertEqual((row["name"], row["category"], row["unit_cost_usd"]), ("FLUX Klein 9B", "image", None))
        self.assertIn("no_cost", row["pricing"]["flags"])

    def test_add_chat_token_image_model_warns_about_tariff(self):
        self.text_catalog.return_value = TEXT_CATALOG + [
            {"id": "google/gemini-3-pro-image", "name": "Google: Nano Banana Pro",
             "architecture": {"input_modalities": ["image", "text"], "output_modalities": ["image", "text"]},
             "pricing": {"prompt": "0.000002", "completion": "0.000012"}}]
        res = self.api.post(self.url("models-list"), {"openrouter_id": "google/gemini-3-pro-image"}, format="json")
        self.assertEqual(res.status_code, 201, res.content)
        self.assertIn("В чате такая модель списывается по токенам: при тарифе 1 картинка стоит около 2 кр. "
                      "Тариф по наценке ставит кнопка «Пересчитать тариф картинок в чате» (в режиме «наценка», "
                      "когда задана себестоимость) — или задайте его вручную.", res.json()["warnings"])
        # FLUX чат берёт за картинку — про токены ни слова.
        res = self.api.post(self.url("models-list"), {"openrouter_id": "black-forest-labs/flux.2-klein-9b"},
                            format="json")
        self.assertEqual(res.status_code, 201, res.content)
        self.assertFalse(any("по токенам" in w for w in res.json()["warnings"]))

    def test_add_with_category_for_text(self):
        res = self.api.post(self.url("models-list"), {"openrouter_id": "anthropic/claude-opus-x",
                                                      "category": "reasoning"}, format="json")
        self.assertEqual((res.status_code, res.json()["model"]["category"]), (201, "reasoning"))

    def test_name_clash_gets_a_suffix(self):
        _model("acme/other", "Seedance 2.0 Mini", "video", "1")
        res = self.api.post(self.url("models-list"), {"openrouter_id": MINI}, format="json")
        self.assertEqual((res.status_code, res.json()["model"]["name"]), (201, "Seedance 2.0 Mini (2)"))

    def test_add_refusals(self):
        cases = (
            ({}, 400, "Укажите ID модели OpenRouter, например bytedance/seedance-2.0-mini."),
            ({"openrouter_id": "  "}, 400, "Укажите ID модели OpenRouter, например bytedance/seedance-2.0-mini."),
            ({"openrouter_id": "x" * 129}, 400, "ID модели длиннее 128 символов."),
            ({"openrouter_id": "acme/unknown"}, 400,
             "Модели «acme/unknown» нет в каталоге OpenRouter. Проверьте ID: как на openrouter.ai."),
            ({"openrouter_id": MINI, "category": "chat"}, 400,
             "Видео-модель встаёт только в категорию «Видео» (video)."),
            ({"openrouter_id": NANO.replace("2.5", "9"), "category": "x"}, 400,
             "Модели «google/gemini-9-flash-image» нет в каталоге OpenRouter. Проверьте ID: как на openrouter.ai."),
            ({"openrouter_id": "black-forest-labs/flux.2-klein-9b", "category": "chat"}, 400,
             "Модель картинок встаёт только в категорию «Изображения» (image)."),
            ({"openrouter_id": "anthropic/claude-opus-x", "category": "video"}, 400,
             "Текстовая модель не может стоять в категории картинок или видео."),
            ({"openrouter_id": "anthropic/claude-opus-x", "category": "misc"}, 400,
             "Категория: одна из chat, writing, coding, reasoning, search, image, fast, budget, video."),
            ({"openrouter_id": MINI, "name": "GPT-4o"}, 400, "Модель с названием «GPT-4o» уже есть."),
            ({"openrouter_id": MINI, "name": 5}, 400, "Название — строка."),
        )
        for body, code, message in cases:
            with self.subTest(body=body):
                res = self.api.post(self.url("models-list"), body, format="json")
                self.assertEqual((res.status_code, res.json()["detail"]), (code, message))
        self.assertFalse(GPTModels.objects.filter(openrouter_id=MINI).exists())
        self.assertFalse(AdminActionLog.objects.exists())

    def test_catalogue_down(self):
        with patch("ai.handlers._load_video_catalog", return_value=[]), \
                patch("ai.pricing.openrouter_models_catalog", return_value=[]):
            res = self.api.post(self.url("models-list"), {"openrouter_id": MINI}, format="json")
            self.assertEqual((res.status_code, res.json()["detail"]),
                             (503, "Каталог OpenRouter сейчас недоступен — попробуйте позже."))
            body = self.api.get(self.url("models-catalog")).json()
            self.assertEqual((body["results"], body["catalogs"]), ([], {"video": "unavailable",
                                                                        "text": "unavailable"}))


class TextRecomputeTests(PricesCase):
    def preview(self, **params):
        res = self.api.get(self.url("models-text-recompute"), params)
        self.assertEqual(res.status_code, 200, res.content)
        return res.json()

    def test_preview_in_legacy_cannot_apply(self):
        body = self.preview()
        self.assertEqual((body["mode"], body["can_apply"], body["catalog"], body["tokens"]),
                         ("legacy", False, "ok", 2000))
        self.assertIn("режиме «наценка»", body["apply_blocked"])
        rows = {row["openrouter_id"]: row for row in body["rows"]}
        self.assertEqual(set(rows), {"openai/gpt-4o", "deepseek/deepseek-chat", "acme/no-price"})
        gpt = rows["openai/gpt-4o"]
        self.assertEqual((gpt["old_coefficient"], gpt["new_coefficient"], gpt["old_message_credits"],
                          gpt["new_message_credits"], gpt["delta_pct"], gpt["status"]),
                         ("17.000", "1.224", 34, 3, -91.2, "ok"))
        self.assertEqual((gpt["price_text"], gpt["markup_pct"], gpt["markup_source"]),
                         ("$2,50 / $10,00 за 1M", "40", "global"))
        self.assertEqual(rows["acme/no-price"]["status"], "no_price")
        self.assertEqual(body["summary"], {"ok": 2, "no_price": 1})
        # Выключенную модель можно взять в пересчёт явно.
        with_sleeping = {row["openrouter_id"] for row in self.preview(ids=str(self.sleeping.pk))["rows"]}
        self.assertIn("acme/sleeping", with_sleeping)
        self.assertEqual(self.api.get(self.url("models-text-recompute"), {"ids": "1,x"}).status_code, 400)

        res = self.api.post(self.url("models-text-recompute"),
                            {"confirm": True, "items": [{"id": self.gpt4o.pk, "coefficient": "1.224"}]},
                            format="json")
        self.assertEqual(res.status_code, 409)
        self.gpt4o.refresh_from_db()
        self.assertEqual(self.gpt4o.markup_coefficient, Decimal("17"))

    def test_apply_in_markup(self):
        self.markup_mode()
        cache.set("vstudio:models:v1:paid", ["stale"], 600)
        res = self.api.post(self.url("models-text-recompute"),
                            {"confirm": True, "items": [{"id": self.gpt4o.pk, "coefficient": "1,224"},
                                                        {"id": self.deepseek.pk, "coefficient": 0.112}]},
                            format="json")
        self.assertEqual(res.status_code, 200, res.content)
        body = res.json()
        self.assertEqual(body["updated"], [
            {"id": self.gpt4o.pk, "name": "GPT-4o", "old_coefficient": "17.000", "new_coefficient": "1.224"},
            {"id": self.deepseek.pk, "name": "DeepSeek V3", "old_coefficient": "0.078",
             "new_coefficient": "0.112"}])
        self.gpt4o.refresh_from_db()
        self.assertEqual(self.gpt4o.markup_coefficient, Decimal("1.224"))
        self.assertIsNone(cache.get("vstudio:models:v1:paid"))
        rows = {row["id"]: row for row in body["preview"]["rows"]}
        self.assertEqual(rows[self.gpt4o.pk]["status"], "unchanged")
        logs = list(AdminActionLog.objects.order_by("id"))
        self.assertEqual([(log.target_id, log.before, log.after) for log in logs], [
            (str(self.gpt4o.pk), {"text_tariff": "17.000"}, {"text_tariff": "1.224"}),
            (str(self.deepseek.pk), {"text_tariff": "0.078"}, {"text_tariff": "0.112"})])

    def test_stale_preview_and_refusals(self):
        self.markup_mode()
        stale = self.api.post(self.url("models-text-recompute"),
                              {"confirm": True, "items": [{"id": self.gpt4o.pk, "coefficient": "1.5"}]},
                              format="json")
        self.assertEqual(stale.status_code, 409)
        self.assertEqual(stale.json()["detail"],
                         "Цены изменились с момента предпросмотра — проверьте новые значения и примените ещё раз.")
        self.assertIn("preview", stale.json())
        cases = (
            ({"items": [{"id": self.gpt4o.pk, "coefficient": "1.224"}]}, 400, "Подтвердите пересчёт: confirm: true."),
            ({"confirm": "yes", "items": [{"id": self.gpt4o.pk, "coefficient": "1.224"}]}, 400,
             "Подтвердите пересчёт: confirm: true."),
            ({"confirm": True, "items": []}, 400, "items: список {id, coefficient} из предпросмотра."),
            ({"confirm": True, "items": [{"id": "1", "coefficient": "1"}]}, 400, "items, строка 1: id — номер модели."),
            ({"confirm": True, "items": [{"id": self.gpt4o.pk, "coefficient": "abc"}]}, 400,
             "items, строка 1: coefficient — тариф из предпросмотра, например 1.224."),
            ({"confirm": True, "items": [{"id": self.gpt4o.pk, "coefficient": "1.224"},
                                         {"id": self.gpt4o.pk, "coefficient": "1.224"}]}, 400,
             f"Модель {self.gpt4o.pk} указана дважды."),
            ({"confirm": True, "items": [{"id": self.nano.pk, "coefficient": "1"}]}, 400,
             "У «Nano Banana» картинка в чате списывается по токенам × тариф модели, но токены картинки "
             "OpenRouter берёт дороже текстовых: пересчёт по ценам текста занизил бы её цену. Тариф этой "
             "модели по себестоимости картинки ставит кнопка «Пересчитать тариф картинок в чате»."),
            ({"confirm": True, "items": [{"id": self.flex.pk, "coefficient": "1"}]}, 400,
             "«FLUX Flex» — модель картинок FLUX: она списывается за картинку, а не тарифом текста."),
            ({"confirm": True, "items": [{"id": self.seedance.pk, "coefficient": "1"}]}, 400,
             "«Seedance 2.0» — видеомодель: её цена считается по себестоимости ролика, а не тарифом текста."),
            ({"confirm": True, "items": [{"id": 99999, "coefficient": "1"}]}, 404, "Модель 99999 не найдена."),
            ({"confirm": True, "items": [{"id": self.no_price.pk, "coefficient": "1"}]}, 409,
             "У «Без цены» сейчас нет цены по себестоимости — обновите предпросмотр."),
        )
        for body, code, message in cases:
            with self.subTest(body=body):
                res = self.api.post(self.url("models-text-recompute"), body, format="json")
                self.assertEqual((res.status_code, res.json()["detail"]), (code, message))
        self.gpt4o.refresh_from_db()
        self.assertEqual(self.gpt4o.markup_coefficient, Decimal("17"))
        self.assertFalse(AdminActionLog.objects.exists())

    def test_own_markup_and_no_basis(self):
        self.markup_mode()
        GPTModels.objects.filter(pk=self.gpt4o.pk).update(markup_pct=Decimal("100"))
        rows = {row["openrouter_id"]: row for row in self.preview()["rows"]}
        self.assertEqual((rows["openai/gpt-4o"]["markup_pct"], rows["openai/gpt-4o"]["markup_source"]),
                         ("100", "model"))
        self.assertEqual(rows["openai/gpt-4o"]["new_coefficient"], "1.748")
        TokenPackage.objects.update(is_active=False)
        pricing.invalidate_price_caches()
        body = self.preview()
        self.assertIsNone(body["basis"])
        self.assertEqual({row["status"] for row in body["rows"]}, {"no_basis", "no_price"})


class ChatImageRecomputeTests(PricesCase):
    """«Пересчитать тариф картинок в чате» (A_FIX, раунд 2): клиент 4.1 для Nano Banana в чате."""

    URL = "models-chat-image-recompute"

    def setUp(self):
        super().setUp()
        self.nano_pro = _model("google/gemini-3-pro-image", "Nano Banana Pro", "image", "12",
                               unit_cost_usd=Decimal("0.134"), sort_order=24)
        self.nano2 = _model("google/gemini-3.1-flash-image-preview", "Nano Banana 2", "image", "6", sort_order=25)
        self.nano_off = _model("google/gemini-2.5-flash-image-preview", "Nano Banana (старая)", "image", "4",
                               unit_cost_usd=Decimal("0.039"), is_active=False, sort_order=26)

    def preview(self, **params):
        res = self.api.get(self.url(self.URL), params)
        self.assertEqual(res.status_code, 200, res.content)
        return res.json()

    def post(self, *items, confirm=True):
        body = {"items": [{"id": model.pk, "coefficient": coeff} for model, coeff in items]}
        if confirm is not None:
            body["confirm"] = confirm
        return self.api.post(self.url(self.URL), body, format="json")

    def rows_by_id(self):
        res = self.api.get(self.url("models-list"))
        self.assertEqual(res.status_code, 200)
        return {row["openrouter_id"]: row for row in res.json()}

    def warnings(self):
        return {w["code"]: w["text"] for w in self.api.get(self.url("pricing")).json()["warnings"]}

    def test_preview_in_legacy_cannot_apply(self):
        body = self.preview()
        self.assertEqual((body["kind"], body["mode"], body["can_apply"], body["tokens"]),
                         ("chat_image", "legacy", False, 1450))
        self.assertEqual(body["apply_blocked"],
                         "Тариф картинок в чате выравнивается в режиме «наценка»: в режиме legacy этот же тариф — "
                         "ещё и цена картинки в студиях. Переключите режим в «Настройках → Цены и наценка».")
        rows = {row["openrouter_id"]: row for row in body["rows"]}
        # Только картинки, которые чат списывает по токенам: без FLUX, текста, видео и выключенных.
        self.assertEqual(list(rows), [NANO, "google/gemini-3-pro-image", "google/gemini-3.1-flash-image-preview"])
        nano = rows[NANO]
        self.assertEqual((nano["old_coefficient"], nano["new_coefficient"], nano["old_message_credits"],
                          nano["new_message_credits"], nano["studio_credits"], nano["delta_pct"], nano["status"]),
                         ("4.000", "4.827", 6, 7, 7, 16.7, "ok"))
        self.assertEqual((nano["price_text"], nano["cost_usd"], nano["markup_pct"], nano["markup_source"]),
                         ("$0,039 за картинку · по наценке 7 кр", "0.039", "40", "global"))
        # Вернут режим legacy — студии возьмут этот же тариф за картинку: int(4.827) = 4, как было.
        self.assertEqual((nano["legacy_studio_old"], nano["legacy_studio_new"]), (4, 4))
        pro = rows["google/gemini-3-pro-image"]
        self.assertEqual((pro["new_coefficient"], pro["old_message_credits"], pro["new_message_credits"],
                          pro["studio_credits"], pro["legacy_studio_old"], pro["legacy_studio_new"]),
                         ("15.172", 18, 22, 22, 12, 15))
        self.assertEqual(rows["google/gemini-3.1-flash-image-preview"]["status"], "no_cost")
        self.assertEqual(body["summary"], {"ok": 2, "no_cost": 1})
        with_off = {row["openrouter_id"] for row in self.preview(ids=str(self.nano_off.pk))["rows"]}
        self.assertIn("google/gemini-2.5-flash-image-preview", with_off)
        self.assertEqual(self.api.get(self.url(self.URL), {"ids": "1,x"}).status_code, 400)

        res = self.post((self.nano, "4.827"))
        self.assertEqual((res.status_code, res.json()["detail"]), (409, body["apply_blocked"]))
        self.nano.refresh_from_db()
        self.assertEqual(self.nano.markup_coefficient, Decimal("4"))
        self.assertFalse(AdminActionLog.objects.exists())

    def test_apply_in_markup_audits_invalidates_and_syncs_the_chat(self):
        self.markup_mode()
        self.assertIn("chat_image_tokens", self.warnings())
        self.assertIn("chat_tariff_stale", self.rows_by_id()[NANO]["pricing"]["flags"])
        cache.set("vstudio:models:v1:paid", ["stale"], 600)

        res = self.post((self.nano, "4.827"), (self.nano_pro, "15,172"))
        self.assertEqual(res.status_code, 200, res.content)
        body = res.json()
        self.assertEqual(body["updated"], [
            {"id": self.nano.pk, "name": "Nano Banana", "old_coefficient": "4.000", "new_coefficient": "4.827"},
            {"id": self.nano_pro.pk, "name": "Nano Banana Pro", "old_coefficient": "12.000",
             "new_coefficient": "15.172"}])
        self.assertEqual({row["id"]: row["status"] for row in body["preview"]["rows"]},
                         {self.nano.pk: "unchanged", self.nano_pro.pk: "unchanged", self.nano2.pk: "no_cost"})
        self.nano.refresh_from_db()
        self.assertEqual(self.nano.markup_coefficient, Decimal("4.827"))
        self.assertIsNone(cache.get("vstudio:models:v1:paid"))
        self.assertEqual([(log.action, log.target_id, log.before, log.after)
                          for log in AdminActionLog.objects.order_by("id")], [
            ("settings.edit", str(self.nano.pk), {"chat_image_tariff": "4.000"}, {"chat_image_tariff": "4.827"}),
            ("settings.edit", str(self.nano_pro.pk), {"chat_image_tariff": "12.000"},
             {"chat_image_tariff": "15.172"})])

        # Чат теперь берёт цену по наценке; предупреждение и флаг ушли.
        rows = self.rows_by_id()
        self.assertEqual(rows[NANO]["price_sample_other"], "по-старому: 4 кр · в чате ≈7 кр по токенам")
        self.assertEqual(rows["google/gemini-3-pro-image"]["price_sample_other"],
                         "по-старому: 15 кр · в чате ≈22 кр по токенам")
        self.assertNotIn("chat_tariff_stale", rows[NANO]["pricing"]["flags"])
        self.assertNotIn("chat_image_tokens", self.warnings())
        # Наценку подняли — чат сам не следует: снова предупреждение и флаг.
        set_runtime(pricing.KEY_MARKUP_PCT, "60")
        pricing.invalidate_price_caches()
        self.assertIn("chat_tariff_stale", self.rows_by_id()[NANO]["pricing"]["flags"])
        self.assertIn("Nano Banana — 8 кр", self.warnings()["chat_image_tokens"])

    def test_refusals_change_nothing(self):
        self.markup_mode()
        stale = self.post((self.nano, "4.828"))
        self.assertEqual((stale.status_code, stale.json()["detail"]), (
            409, "Цены изменились с момента предпросмотра — проверьте новые значения и примените ещё раз."))
        self.assertEqual(stale.json()["preview"]["kind"], "chat_image")
        cases = (
            (self.post((self.nano, "4.827"), confirm=None), 400, "Подтвердите пересчёт: confirm: true."),
            (self.post((self.flex, "1")), 400, "«FLUX Flex» — модель картинок FLUX: чат списывает её за картинку "
                                                "по себестоимости, тариф за токены ей не нужен."),
            (self.post((self.gpt4o, "1")), 400,
             "«GPT-4o» — текстовая модель: её тариф пересчитывает «Пересчитать тарифы текста»."),
            (self.post((self.seedance, "1")), 400,
             "«Seedance 2.0» — видеомодель: её цена считается по себестоимости ролика, а не этим тарифом."),
            (self.post((self.nano2, "1")), 409,
             "У «Nano Banana 2» не задана себестоимость картинки — введите её в строке модели."),
            (self.api.post(self.url(self.URL), {"confirm": True, "items": [{"id": 99999, "coefficient": "1"}]},
                           format="json"), 404, "Модель 99999 не найдена."),
        )
        for res, code, message in cases:
            with self.subTest(message=message):
                self.assertEqual((res.status_code, res.json()["detail"]), (code, message))
        self.nano.refresh_from_db()
        self.assertEqual(self.nano.markup_coefficient, Decimal("4"))
        self.assertFalse(AdminActionLog.objects.exists())

    def test_no_basis(self):
        self.markup_mode()
        TokenPackage.objects.update(is_active=False)
        pricing.invalidate_price_caches()
        body = self.preview()
        self.assertIsNone(body["basis"])
        self.assertEqual({row["status"] for row in body["rows"]}, {"no_basis", "no_cost"})
