# -*- coding: utf-8 -*-
"""Золотой снимок цен: в режиме legacy каждая цена ровно такая, как до наценки.

Снимок снят на HEAD a23235f, до правок цен (BUILD_A, решение 1). Один и тот же
набор моделей, пакетов, курса и каталога OpenRouter прогоняется через все
функции цены и публичные ответы API: чат, бот, видеостудия, мультстудия,
калькулятор «На что хватит?». Переключатель pricing_mode=legacy обязан давать
те же числа байт в байт — иначе владелец не сможет мгновенно откатиться.

Переснять снимок можно только осознанно, когда legacy-цена должна поменяться:
PRICING_GOLDEN_WRITE=1 python manage.py test ai.tests_pricing_golden
--settings=core.settings_sqlitetest

16.10.2026 (сборка C): /api/cartoon/pricing/ считает сцену нового мультфильма — с
настройками по умолчанию (Mini 480p 5 с), как её и снимут; снимок переснят осознанно,
поменялись только числа cartoon_pricing и добавился блок settings.
"""
from __future__ import annotations

import json
import os
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from ai.models import GPTModels
from plans.models import TokenPackage

DATA_DIR = Path(__file__).resolve().parent / "tests_data"
GOLDEN_PATH = DATA_DIR / "pricing_golden_legacy.json"
CATALOG_PATH = DATA_DIR / "or_video_models_fixture.json"
WRITE_ENV = "PRICING_GOLDEN_WRITE"

# Курс как на проде 14.10 (он и даёт наблюдённые 149): 87.4 сома за доллар.
KGS_PER_USD = 87.4
STAR_USD = 0.013

# Пакеты как на проде: (имя, сомы, кредиты).
PACKAGES = (("MASTER", 4990, 6500), ("Максимум", 1990, 2500), ("Премиум", 990, 1200),
            ("Про", 490, 500), ("Старт", 199, 150))

# (openrouter_id, имя, тариф): тарифы прода (PLAN §3.1), Seedance 2.0/2.5 — 0.
VIDEO_MODELS = (
    ("bytedance/seedance-2.0", "Seedance 2.0", "0"),
    ("bytedance/seedance-2.0-mini", "Seedance 2.0 Mini", "1"),
    ("bytedance/seedance-2.0-fast", "Seedance 2.0 Fast", "1"),
    ("bytedance/seedance-2.5", "Seedance 2.5", "0"),
    ("x-ai/grok-imagine-video", "Grok Video", "15"),
    ("x-ai/grok-imagine-video-1.5-lite", "Grok 1.5 Lite", "32"),
    ("kwaivgi/kling-v3.0-std", "Kling 3.0", "26"),
    ("alibaba/wan-2.7", "Wan 2.7", "21"),
    ("google/veo-3.1-lite", "Veo 3.1 Lite", "17"),
    ("google/veo-3.1", "Veo 3.1", "83"),
    ("minimax/hailuo-2.3", "Hailuo 2.3", "17"),
    ("runway/aleph-2", "Runway Aleph", "5"),
    ("heygen/heygen-video-1", "HeyGen", "3"),
    ("openai/sora-2-pro", "Sora 2 Pro", "62"),  # нет в каталоге — путь «прайс не разобран»
)
# Картинки: плоская цена за штуку (FLUX), токены в чате (Nano Banana).
IMAGE_MODELS = (
    ("black-forest-labs/flux.2-klein-4b", "FLUX Klein", "2"),
    ("black-forest-labs/flux.2-pro", "FLUX Pro", "4"),
    ("black-forest-labs/flux.2-flex", "FLUX Flex", "12"),
    ("black-forest-labs/flux.2-max", "FLUX Max", "10"),
    ("google/gemini-2.5-flash-image", "Nano Banana", "4"),
    ("google/gemini-3-pro-image", "Nano Banana Pro", "12"),
    ("black-forest-labs/flux.1-schnell", "FLUX Schnell", "2.9"),  # int() обрезает до 2
    ("black-forest-labs/flux.1-dev", "FLUX Dev", "0"),            # 0 читается как 1
)
# Текст: тариф = кредитов за 1000 токенов.
TEXT_MODELS = (
    ("openai/gpt-4o", "GPT-4o", "17", "chat"),
    ("google/gemini-2.5-flash", "Gemini 2.5 Flash", "0.232", "fast"),
    ("deepseek/deepseek-chat", "DeepSeek V3", "0.078", "budget"),
    ("openai/gpt-5.4-mini", "GPT-5.4 mini", "0.5", "chat"),
    ("anthropic/claude-sonnet-4.5", "Claude Sonnet 4.5", "0", "reasoning"),
)
NANO = "google/gemini-2.5-flash-image"

# Пресеты мультстудии: (slug, видео-модель, секунды, качество, ручная цена).
PRESETS = (
    ("s20-5-720", "bytedance/seedance-2.0", 5, "720p", None),
    ("s20-4-default", "bytedance/seedance-2.0", 4, "", None),
    ("s20-15-720", "bytedance/seedance-2.0", 15, "720p", None),
    ("s20-5-1080", "bytedance/seedance-2.0", 5, "1080p", None),
    ("mini-5-480", "bytedance/seedance-2.0-mini", 5, "480p", None),
    ("s25-10-720", "bytedance/seedance-2.5", 10, "720p", None),
    ("veo-lite-5", "google/veo-3.1-lite", 5, "720p", None),
    ("hailuo-5-720", "minimax/hailuo-2.3", 5, "720p", None),
    ("sora-5", "openai/sora-2-pro", 5, "720p", None),
    ("s20-manual-250", "bytedance/seedance-2.0", 5, "720p", 250),
    ("s20-manual-100", "bytedance/seedance-2.0", 5, "720p", 100),
)
# «Мультфильм: цена сцены 5 с» из админки: не задана, 200, 100.
SCENE_PRICE_VARIANTS = (None, 200, 100)

TEST_CACHES = {"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache",
                           "LOCATION": "pricing-golden"}}
GOLDEN_SETTINGS = dict(
    CACHES=TEST_CACHES, VIDEO_MIN_MARGIN=0.4, VIDEO_GEN_DURATION=5, VIDEO_GEN_RESOLUTION="720p",
    TOKEN_CREDIT_DIVISOR=1000, STUDIO_SCENE_CREDITS=0, VSTUDIO_MODE="on",
    CREDIT_CALC_TEXT_MODEL_ID="openai/gpt-5.4-mini", CREDIT_CALC_IMAGE_MODEL_ID="black-forest-labs/flux.2-pro",
    CREDIT_CALC_VIDEO_MODEL_ID="x-ai/grok-imagine-video", CREDIT_CALC_DOCUMENT_MODEL_ID="openai/gpt-5.4-mini",
    CREDIT_CALC_DOCUMENT_TOKENS_PER_PAGE=650, CREDIT_CALC_TEXT_TOKENS_PER_REPLY=2500,
    CREDIT_CALC_IMAGE_OUTPUT_TOKENS_ESTIMATE=1300, CREDIT_CALC_IMAGE_PROMPT_TOKENS_ESTIMATE=150,
    CREDIT_CALC_TEXT_MIN_COUNT=200, CREDIT_CALC_IMAGE_MIN_COUNT=100, CREDIT_CALC_VIDEO_MIN_COUNT=5,
    CREDIT_CALC_DOCUMENT_MIN_COUNT=200,
)


def load_catalog() -> list:
    with open(CATALOG_PATH, encoding="utf-8") as fh:
        return json.load(fh)["data"]


def catalog_by_id() -> dict:
    return {m["id"]: m for m in load_catalog()}


def start_price_mocks(test, catalog: list | None = None) -> None:
    """Курс, Stars и каталог OpenRouter — без сети и без чужих настроек окружения."""
    catalog = load_catalog() if catalog is None else catalog
    for target, kwargs in (
        ("payments.crypto.rates.kgs_to_usd_rate", {"return_value": 1 / KGS_PER_USD}),
        ("plans.stars.withdraw_rate", {"return_value": STAR_USD}),
        ("ai.handlers._load_video_catalog", {"side_effect": lambda cfg=None: catalog}),
        ("ai.handlers._openrouter_config",
         {"return_value": {"base_url": "https://openrouter.ai/api/v1", "api_key": "test"}}),
        ("requests.get", {"side_effect": AssertionError("сеть в тестах цен запрещена")}),
    ):
        p = patch(target, **kwargs)
        p.start()
        test.addCleanup(p.stop)


def create_packages() -> None:
    for i, (name, price, credits) in enumerate(PACKAGES):
        TokenPackage.objects.create(name=name, tokens=credits, price=price, currency="KGS",
                                    is_active=True, sort_order=i)


def create_models() -> dict:
    from vstudio.caps import lookup

    out = {}
    order = 10
    for orid, name, coeff in VIDEO_MODELS:
        out[orid] = GPTModels.objects.create(
            name=name, openrouter_id=orid, category="video", markup_coefficient=Decimal(coeff),
            max_tokens=4096, is_active=True, cartoon_stage="video", sort_order=order,
            vstudio_enabled=lookup(orid)[0] is not None)
        order += 1
    for orid, name, coeff in IMAGE_MODELS:
        out[orid] = GPTModels.objects.create(
            name=name, openrouter_id=orid, category="image", markup_coefficient=Decimal(coeff),
            max_tokens=4096, is_active=True, cartoon_stage="image", sort_order=order,
            vstudio_enabled=lookup(orid)[0] is not None)
        order += 1
    for orid, name, coeff, category in TEXT_MODELS:
        out[orid] = GPTModels.objects.create(
            name=name, openrouter_id=orid, category=category, markup_coefficient=Decimal(coeff),
            max_tokens=4096, is_active=True, sort_order=order)
        order += 1
    return out


def create_presets(models: dict) -> dict:
    from cartoon.models import CartoonPreset

    out = {}
    for i, (slug, video, seconds, res, manual) in enumerate(PRESETS):
        out[slug] = CartoonPreset.objects.create(
            slug=slug, title=slug, is_active=True, scene_prompt="The character waves.",
            image_model=models[NANO], video_model=models[video], duration=seconds,
            resolution=res, credits_override=manual, sort_order=i,
            preview_video=f"cartoon/previews/{slug}.mp4")
    return out


def create_scenes(presets: dict):
    """Сцены, которые сейчас снимаются: из них складывается резерв мультстудии."""
    from cartoon.models import CartoonProject, CartoonScene

    user = get_user_model().objects.create_user(email="golden@example.com", password="x")
    user.token_balance = 5000
    user.save(update_fields=["token_balance"])
    project = CartoonProject.objects.create(user=user, aspect_ratio="16:9")
    rows = (("s20-5-720", "new", ""), ("s20-5-720", "keyframe", ""), ("s20-15-720", "video", ""),
            ("mini-5-480", "new", "cartoon/keyframes/k.png"), ("s20-manual-250", "new", ""),
            ("s25-10-720", "ready", ""), ("veo-lite-5", "draft", ""))
    for order, (slug, status, keyframe) in enumerate(rows):
        CartoonScene.objects.create(project=project, preset=presets[slug], order=order,
                                    status=status, keyframe=keyframe)
    return user


# ---------------------------------------------------------------- сбор снимка

def _durations(spec: dict) -> list[int]:
    supported = [int(d) for d in (spec.get("supported_durations") or []) if str(d).isdigit()]
    picked = sorted({d for d in supported if d in (4, 5, 6, 8, 10, 15)} | {5})
    return picked


def _resolutions(spec: dict) -> list[str]:
    supported = [str(r) for r in (spec.get("supported_resolutions") or []) if r]
    out = list(supported) or ["720p"]
    # Качество, которого модель не умеет: цена не должна от этого падать.
    if "1080p" not in [r.lower() for r in out]:
        out.append("1080p")
    return out


def collect_functions(models: dict, catalog: dict) -> dict:
    from ai.model_billing import flux_charge_credits
    from ai.video_cost import (
        cheapest_credit_usd, price_table, price_tables_by_aspect, provider_cost_usd, video_credits)

    out: dict = {"cheapest_credit_usd": cheapest_credit_usd()}

    costs, prices, tables = {}, {}, {}
    for orid, _, _ in VIDEO_MODELS:
        model = models[orid]
        spec = catalog.get(orid, {})
        aspects = [None] + [str(a) for a in (spec.get("supported_aspect_ratios") or [])]
        resolutions = _resolutions(spec)
        durations = _durations(spec)
        for res in resolutions:
            for seconds in durations:
                for aspect in aspects:
                    key = f"{orid}|{res}|{seconds}|{aspect or '-'}"
                    prices[key + "|0"] = video_credits(model, spec, res, seconds, aspect=aspect)
                    costs[key] = provider_cost_usd(spec, res, seconds, aspect=aspect)
            for images in (1, 2):
                prices[f"{orid}|{res}|5|-|{images}"] = video_credits(model, spec, res, 5, images=images)
        # Без каталога вовсе (OpenRouter не ответил): тариф с поправкой на площадь.
        for res in ("720p", "1080p"):
            prices[f"{orid}|{res}|5|-|0|no-catalog"] = video_credits(model, {}, res, 5)
        tables[orid] = {
            "table": price_table(model, spec, [str(r) for r in (spec.get("supported_resolutions") or [])],
                                 [int(d) for d in (spec.get("supported_durations") or [])]),
            "by_aspect": price_tables_by_aspect(
                model, spec, [str(r) for r in (spec.get("supported_resolutions") or [])],
                [int(d) for d in (spec.get("supported_durations") or [])]),
        }
    out["provider_cost_usd"] = costs
    out["video_credits"] = prices
    out["price_tables"] = tables
    out["flux_charge_credits"] = {orid: flux_charge_credits(models[orid])
                                  for orid in [m[0] for m in IMAGE_MODELS + VIDEO_MODELS + TEXT_MODELS]}
    return out


def collect_vstudio(models: dict, catalog: dict) -> dict:
    from vstudio import caps as caps_mod
    from vstudio import pricing

    out: dict = {"model_prices": {}, "price": {}, "image_credits": {}, "check_margin": {}}
    for orid, model in models.items():
        fam = caps_mod.family_of(orid)
        if fam is None:
            continue
        spec = catalog.get(orid) if fam.kind == caps_mod.KIND_VIDEO else None
        caps = caps_mod.for_model(model, spec=spec) if fam.kind == caps_mod.KIND_VIDEO else caps_mod.for_model(model)
        if caps is None:
            continue
        out["model_prices"][orid] = pricing.model_prices(model, caps, spec=spec)
        if caps.kind == caps_mod.KIND_IMAGE:
            out["image_credits"][orid] = pricing.image_credits(model)
            for images in (0, 1, 2):
                compiled = SimpleNamespace(kind="image", errors=[], effective={}, billable_images=images,
                                           price_aspect=None)
                out["price"][f"{orid}|image|{images}"] = pricing.price(compiled, model, caps, spec=spec).to_dict()
            continue
        aspects = (None,) + tuple(a for a in caps.aspect_ratios if a in ("16:9", "9:16", "1:1", "21:9"))
        for res in caps.resolutions:
            for seconds in sorted({int(d) for d in caps.durations if int(d) in (4, 5, 6, 10)}):
                for aspect in aspects:
                    for images in (0, 1):
                        compiled = SimpleNamespace(
                            kind="video", errors=[], billable_images=images, price_aspect=aspect,
                            effective={"duration": seconds, "resolution": res, "aspect_ratio": aspect or "auto"})
                        key = f"{orid}|{res}|{seconds}|{aspect or '-'}|{images}"
                        out["price"][key] = pricing.price(compiled, model, caps, spec=spec).to_dict()
    cases = ((145, "0.7623"), (122, "0.7623"), (100, "0.7623"), (87, "0.7623"), (0, "1"), (10, None),
             (3, "0.015"), (2, "0.015"), (7, "0.039"))
    for charged, cost in cases:
        take = SimpleNamespace(uid="golden", model_ref="m", genlog_id=None, credits_charged=charged,
                               provider_cost_usd=cost)
        out["check_margin"][f"{charged}|{cost}"] = pricing.check_margin(take)
    return out


def collect_cartoon(presets: dict, user) -> dict:
    from cartoon import pricing as cp
    from vstudio.reserve import balance_snapshot, total_reserved

    out: dict = {}
    for slug, preset in presets.items():
        out[slug] = {
            "scene_credits": cp.scene_credits(preset),
            "scene_credits_keyframe_ready": cp.scene_credits(preset, keyframe_ready=True),
            "scene_video_credits": cp.scene_video_credits(preset),
            "frame_credits": cp.frame_credits(preset.image_model),
            "estimated_credits": preset.estimated_credits(),
            "effective_duration": cp.effective_duration(preset.video_model, preset.duration),
            "video_credits": cp.video_credits(preset.video_model, preset.duration, preset.resolution or "720p"),
            "video_credits_rate_19_2": cp.video_credits(preset.video_model, preset.duration,
                                                        preset.resolution or "720p", per_second=19.2),
        }
    out["reserved_credits"] = cp.reserved_credits(user)
    out["vstudio_total_reserved"] = total_reserved(user)
    out["balance_snapshot"] = balance_snapshot(user, 100)
    return out


def collect_credit_value(models: dict) -> dict:
    from plans import credit_value as cv

    packages = cv.compute_all_packages_value("ru")
    for row in packages:
        row.pop("id", None)  # id из базы зависит от порядка тестов
    return {
        "packages": packages,
        "credits_per_unit": {c: cv.credits_per_unit(c) for c in ("text", "image", "video", "document")},
        "estimate_model_usage_cost": {orid: cv.estimate_model_usage_cost(m) for orid, m in models.items()},
    }


def _strip_ids(rows: list) -> list:
    for row in rows:
        if isinstance(row, dict):
            row.pop("id", None)
    return rows


def collect_api(models: dict, *, cartoon_only: bool = False) -> dict:
    client = APIClient()
    out: dict = {}
    r = client.get("/api/cartoon/pricing/")
    out["cartoon_pricing"] = {"status": r.status_code, "data": r.json()}
    r = client.get("/api/cartoon/presets/")
    data = r.json()
    out["cartoon_presets"] = {"status": r.status_code,
                              "credits": {p["slug"]: [p["credits"], p["tryon_credits"], p["duration"]]
                                          for p in data.get("presets", [])}}
    if cartoon_only:
        return out
    params = {}
    for orid, _, _ in VIDEO_MODELS:
        r = client.get("/api/ai/video-params/", {"model": orid})
        body = r.json()
        params[orid] = {"status": r.status_code,
                        **{k: body.get(k) for k in ("credits_per_second", "price_table", "price_table_by_aspect",
                                                    "durations", "resolutions", "default_duration",
                                                    "default_resolution")}}
    out["video_params"] = params
    r = client.get("/api/vstudio/models/")
    body = r.json()
    out["vstudio_models"] = {
        "status": r.status_code,
        "video": [{k: m.get(k) for k in ("id", "price_from", "price", "per_image")} for m in body.get("video", [])],
        "image": [{k: m.get(k) for k in ("id", "price_from", "price", "per_image")} for m in body.get("image", [])],
    }
    r = client.get("/api/plans/packages/value/")
    body = r.json()
    rows = body.get("packages", body.get("results", [])) if isinstance(body, dict) else body
    out["packages_value"] = {"status": r.status_code, "rows": _strip_ids(list(rows or []))}
    r = client.get("/api/ai/models/")
    body = r.json()
    rows = body.get("results", body) if isinstance(body, dict) else body
    out["ai_models"] = {"status": r.status_code,
                        "rows": {m.get("openrouter_id") or m.get("name"): [m.get("markup_coefficient"),
                                                                           m.get("estimated_usage")]
                                 for m in (rows or [])}}
    return out


def collect_all(test, prepare=None) -> dict:
    from adminapi.runtime import delete_runtime, set_runtime

    catalog = catalog_by_id()
    models = create_models()
    create_packages()
    if prepare is not None:
        prepare(models)
    presets = create_presets(models)
    user = create_scenes(presets)

    snapshot: dict = {"functions": collect_functions(models, catalog),
                      "vstudio": collect_vstudio(models, catalog),
                      "credit_value": collect_credit_value(models),
                      "api": collect_api(models)}
    cartoon: dict = {}
    for scene_price in SCENE_PRICE_VARIANTS:
        if scene_price is None:
            delete_runtime("studio_scene_credits")
        else:
            set_runtime("studio_scene_credits", scene_price)
        cartoon[str(scene_price or 0)] = {"pricing": collect_cartoon(presets, user),
                                          "api": collect_api(models, cartoon_only=True)}
    delete_runtime("studio_scene_credits")
    snapshot["cartoon"] = cartoon
    return normalize(snapshot)


def normalize(value):
    """JSON-форма снимка: Decimal — строкой, кортежи — списками, ключи — строками."""
    return json.loads(json.dumps(value, ensure_ascii=False, sort_keys=True, default=str))


def write_golden(snapshot: dict) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with open(GOLDEN_PATH, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(snapshot, fh, ensure_ascii=False, sort_keys=True, indent=1)
        fh.write("\n")


def read_golden() -> dict:
    with open(GOLDEN_PATH, encoding="utf-8") as fh:
        return json.load(fh)


@override_settings(**GOLDEN_SETTINGS)
class LegacyGoldenTests(TestCase):
    """Режим legacy (по умолчанию) — те же цены, что на a23235f."""

    def setUp(self):
        cache.clear()
        start_price_mocks(self)

    def assert_golden(self, snapshot: dict) -> None:
        golden = read_golden()
        self.assertEqual(sorted(snapshot), sorted(golden))
        for section in golden:
            # По разделам — чтобы при расхождении было видно, где именно.
            self.assertEqual(snapshot[section], golden[section], f"раздел {section} разошёлся со снимком")

    def test_default_mode_matches_golden(self):
        snapshot = collect_all(self)
        if os.environ.get(WRITE_ENV) == "1":
            write_golden(snapshot)
            self.skipTest(f"снимок переписан: {GOLDEN_PATH}")
        self.assert_golden(snapshot)

    def test_explicit_legacy_ignores_markup_settings(self):
        """Наценка, порог, курс и поля моделей заданы, но режим legacy — цены прежние."""
        from adminapi.runtime import set_runtime

        def prepare(models):
            set_runtime("pricing_mode", "legacy")
            set_runtime("price_markup_pct", "5")
            set_runtime("price_floor_pct", "0")
            set_runtime("price_kgs_per_usd", "50")
            for i, model in enumerate(models.values()):
                model.markup_pct = Decimal(i % 3)
                model.unit_cost_usd = Decimal("0.001")
                model.ref_cost_usd = Decimal("0.002")
                model.save(update_fields=["markup_pct", "unit_cost_usd", "ref_cost_usd"])

        self.assert_golden(collect_all(self, prepare=prepare))

    def test_markup_mode_really_changes_prices(self):
        """Обратная проверка: те же входы в режиме markup дают другие числа."""
        from adminapi.runtime import set_runtime
        from ai.video_cost import video_credits

        models = create_models()
        create_packages()
        spec = catalog_by_id()["bytedance/seedance-2.0"]
        key = "bytedance/seedance-2.0|720p|5|16:9|0"
        self.assertEqual(read_golden()["functions"]["video_credits"][key], 145)
        set_runtime("pricing_mode", "markup")
        self.assertEqual(video_credits(models["bytedance/seedance-2.0"], spec, "720p", 5, aspect="16:9"), 122)
