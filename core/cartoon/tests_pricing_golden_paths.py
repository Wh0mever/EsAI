# -*- coding: utf-8 -*-
"""Золотой снимок цен мультстудии, которых нет в снимке A1 (ai/tests_pricing_golden.py).

Снимок A1 держит формулы (cartoon.pricing.*, резерв, витрина, /pricing/). Здесь —
места, где цена доходит до человека и до кошелька: цена сцены в ленте в каждом
формате, гейт «Снять» и «Переснять с новым кадром», примерка, кадр своей сцены,
герой по описанию, кадры в services, списания задачи съёмки, warm_keyframes,
studio_video_model и колонка цены в Django-админке.

Снят на a23235f (дерево из git archive, до правок A2). В режиме legacy каждое
число обязано совпасть байт в байт. Переснять — только осознанно:
PRICING_PATHS_WRITE=1 python manage.py test cartoon.tests_pricing_golden_paths
--settings=core.settings_sqlitetest
"""
from __future__ import annotations

import io
import json
import os
from contextlib import ExitStack
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.core.management import call_command
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from ai.tests_pricing_golden import (
    GOLDEN_SETTINGS, NANO, SCENE_PRICE_VARIANTS, create_models, create_packages, create_presets,
    normalize, start_price_mocks)

DATA_DIR = Path(__file__).resolve().parent / "tests_data"
GOLDEN_PATH = Path(os.environ.get("PRICING_PATHS_OUT") or (DATA_DIR / "pricing_golden_paths.json"))
WRITE_ENV = "PRICING_PATHS_WRITE"

ASPECTS = ("16:9", "9:16", "1:1")
# Пресеты с другой моделью кадра: плоская цена картинки обрезает дробь (2.9 → 2),
# читает 0 как 1 и берёт дорогую модель как есть.
EXTRA_PRESETS = (
    ("img-schnell", "black-forest-labs/flux.1-schnell"),
    ("img-dev-zero", "black-forest-labs/flux.1-dev"),
    ("img-nano-pro", "google/gemini-3-pro-image"),
)
# Что снимаем задачей render_scene: пресеты разных моделей и длительностей.
RENDER_PRESETS = ("s20-5-720", "s20-4-default", "mini-5-480", "veo-lite-5", "sora-5",
                  "s20-manual-250", "img-schnell")
STUDIO_MODEL_RUNS = (
    ("--model", "bytedance/seedance-2.0-mini"),
    ("--model", "bytedance/seedance-2.0", "--duration", "10", "--resolution", "480p"),
    ("--model", "google/veo-3.1-lite", "--duration", "5"),
    ("--model", "bytedance/seedance-2.5", "--image-model", "black-forest-labs/flux.1-schnell"),
    ("--model", "openai/sora-2-pro"),
)


def _user(email: str, balance: int):
    user = get_user_model().objects.create_user(email=email, password="x-12345678")
    user.token_balance = balance
    user.save(update_fields=["token_balance"])
    return user


def _client(user) -> APIClient:
    client = APIClient()
    client.force_authenticate(user)
    return client


def create_world(models: dict) -> dict:
    """Пресеты A1 + пресеты с другой моделью кадра + библиотечные герои."""
    from cartoon.models import CartoonCharacter, CartoonPreset

    presets = create_presets(models)
    for i, (slug, image) in enumerate(EXTRA_PRESETS):
        presets[slug] = CartoonPreset.objects.create(
            slug=slug, title=slug, is_active=True, scene_prompt="The character waves.",
            image_model=models[image], video_model=models["bytedance/seedance-2.0"], duration=5,
            resolution="720p", sort_order=100 + i, preview_video=f"cartoon/previews/{slug}.mp4")
    heroes = [CartoonCharacter.objects.create(name=f"Герой {i}", image=f"cartoon/characters/h{i}.jpg",
                                              is_public=True, description="a small fox", sort_order=i)
              for i in range(8)]
    return {"presets": presets, "heroes": heroes}


def collect_feed(world: dict, variant: str) -> dict:
    """Лента (scene_json), гейт «Снять» и «Переснять с новым кадром» при нулевом балансе."""
    from cartoon.models import CartoonProject, CartoonScene

    presets, hero = world["presets"], world["heroes"][0]
    user = _user(f"feed-{variant}@example.com", 0)
    client = _client(user)
    feed, gate, retry_new = {}, {}, {}
    for aspect in ASPECTS:
        project = CartoonProject.objects.create(user=user, character=hero, aspect_ratio=aspect)
        keys = {}
        for order, (slug, preset) in enumerate(sorted(presets.items())):
            for keyframe in ("", "cartoon/keyframes/own.png"):
                scene = CartoonScene.objects.create(project=project, preset=preset, order=order,
                                                    keyframe=keyframe)
                keys[scene.pk] = f"{slug}|{aspect}|{'kf' if keyframe else '-'}"
        body = client.get(f"/api/cartoon/projects/{project.pk}/").json()
        for row in body["scenes"]:
            feed[keys[row["id"]]] = [row["preset"]["credits"], row["render_credits"]]
        for scene_id, key in keys.items():
            r = client.post(f"/api/cartoon/scenes/{scene_id}/render/", {}, format="json")
            gate[key] = [r.status_code, r.json().get("required")]
            if key.endswith("|kf"):
                r = client.patch(f"/api/cartoon/scenes/{scene_id}/",
                                 {"retry": True, "new_keyframe": True}, format="json")
                retry_new[key] = [r.status_code, r.json().get("required")]
    return {"feed": feed, "gate": gate, "retry_new_keyframe": retry_new}


def collect_images(world: dict, models: dict) -> dict:
    """Цена кадра везде, где он рисуется: примерка, свой кадр, герой, services."""
    from cartoon import services
    from cartoon.models import CartoonProject, CartoonScene

    presets, heroes = world["presets"], world["heroes"]
    user = _user("images@example.com", 0)
    client = _client(user)
    out: dict = {"try_on": {}, "custom_frame": {}, "character_generate": {}, "services": {}}
    for slug, preset in sorted(presets.items()):
        r = client.post(f"/api/cartoon/presets/{preset.pk}/try-on/",
                        {"character_id": heroes[0].pk, "aspect_ratio": "9:16"}, format="json")
        out["try_on"][slug] = [r.status_code, r.json().get("required")]
    for aspect in ASPECTS:
        project = CartoonProject.objects.create(user=user, character=heroes[0], aspect_ratio=aspect)
        for slug in ("s20-5-720", "img-schnell", "img-dev-zero", "img-nano-pro"):
            scene = CartoonScene.objects.create(project=project, preset=presets[slug],
                                                custom_text="Кот едет на велосипеде")
            r = client.post(f"/api/cartoon/scenes/{scene.pk}/frame/", {}, format="json")
            out["custom_frame"][f"{slug}|{aspect}"] = [r.status_code, r.json().get("required")]
    for coeff in ("4", "12.7", "0"):
        models[NANO].markup_coefficient = Decimal(coeff)
        models[NANO].save(update_fields=["markup_coefficient"])
        r = client.post("/api/cartoon/characters/generate/", {"prompt": "рыжий кот"}, format="json")
        out["character_generate"][coeff] = [r.status_code, r.json().get("required")]
    models[NANO].markup_coefficient = Decimal("4")
    models[NANO].save(update_fields=["markup_coefficient"])

    hero = heroes[1]
    project = CartoonProject.objects.create(user=user, character=hero, aspect_ratio="16:9")
    with patch("cartoon.services.generate_keyframe", return_value="cartoon/keyframes/new.png"), \
            patch("cartoon.services.ensure_custom_prompt"):
        for slug, preset in sorted(presets.items()):
            first = services.get_or_create_keyframe(preset, hero, None, "9:16")[1]
            again = services.get_or_create_keyframe(preset, hero, None, "9:16")[1]
            scene = CartoonScene.objects.create(project=project, preset=preset)
            linked = services.draw_linked_keyframe(scene, hero, None, "cartoon/keyframes/a.png", "16:9")[1]
            custom_scene = CartoonScene.objects.create(project=project, preset=preset,
                                                       custom_text="Кот на крыше")
            custom = services.draw_custom_keyframe(custom_scene, hero, None, "1:1")[1]
            out["services"][slug] = {"pooled_first": first, "pooled_again": again,
                                     "linked": linked, "custom": custom}
    return out


def collect_renders(world: dict, variant: str, hero_index: int) -> dict:
    """Задача съёмки: сколько списано за кадр и за видео (кадр рисуется заново)."""
    from ai.models import GenerationLog
    from cartoon.models import CartoonProject, CartoonScene
    from cartoon.tasks import render_scene

    presets, hero = world["presets"], world["heroes"][hero_index]
    user = _user(f"render-{variant}@example.com", 100000)
    out = {}
    fakes = (
        patch("cartoon.services.generate_keyframe", return_value="cartoon/keyframes/new.png"),
        patch("cartoon.tasks.ensure_video_prompt", return_value={"prompt": "p", "negative": ""}),
        patch("cartoon.tasks.generate_scene_video", return_value="cartoon/scenes/new.mp4"),
        patch("cartoon.tasks.last_frame_of", return_value=""),
        patch("cartoon.tasks._notify_scene"),
        patch("cartoon.tasks.remember_pair_video"),
        patch("cartoon.audio.remix_scene"),
    )
    with ExitStack() as stack:
        for fake in fakes:
            stack.enter_context(fake)
        for aspect in ("16:9", "1:1"):
            project = CartoonProject.objects.create(user=user, character=hero, aspect_ratio=aspect)
            for order, slug in enumerate(RENDER_PRESETS):
                scene = CartoonScene.objects.create(project=project, preset=presets[slug], order=order,
                                                    status=CartoonScene.STATUS_NEW)
                result = render_scene.apply(args=[scene.pk]).get()
                scene.refresh_from_db()
                log = GenerationLog.objects.filter(scene_id=scene.pk).order_by("id").last()
                out[f"{slug}|{aspect}"] = {
                    "status": result.get("status"), "spent": scene.credits_spent,
                    "video_planned": log.credits_planned if log else None,
                    "video_charged": log.credits_charged if log else None,
                }
    user.refresh_from_db()
    out["balance_after"] = user.token_balance
    return out


def collect_commands() -> dict:
    out = {"studio_video_model": {}}
    buf = io.StringIO()
    call_command("warm_keyframes", "--dry-run", stdout=buf, stderr=io.StringIO())
    out["warm_keyframes"] = buf.getvalue()
    buf = io.StringIO()
    call_command("warm_keyframes", "--dry-run", "--limit", "5", stdout=buf, stderr=io.StringIO())
    out["warm_keyframes_limit"] = buf.getvalue()
    for args in STUDIO_MODEL_RUNS:
        buf = io.StringIO()
        call_command("studio_video_model", *args, stdout=buf, stderr=io.StringIO())
        out["studio_video_model"][" ".join(args)] = buf.getvalue()
    return out


def collect_admin(world: dict) -> dict:
    from django.contrib import admin

    from cartoon.admin import CartoonPresetAdmin
    from cartoon.models import CartoonPreset

    model_admin = CartoonPresetAdmin(CartoonPreset, admin.site)
    return {slug: model_admin.price(preset) for slug, preset in sorted(world["presets"].items())}


def collect_all(prepare=None) -> dict:
    from adminapi.runtime import delete_runtime, set_runtime

    models = create_models()
    create_packages()
    if prepare is not None:
        prepare(models)
    world = create_world(models)
    snapshot: dict = {"images": collect_images(world, models)}
    variants: dict = {}
    for i, scene_price in enumerate(SCENE_PRICE_VARIANTS):
        variant = str(scene_price or 0)
        if scene_price is None:
            delete_runtime("studio_scene_credits")
        else:
            set_runtime("studio_scene_credits", scene_price)
        variants[variant] = {
            **collect_feed(world, variant),
            "render": collect_renders(world, variant, 2 + i),
            "commands": collect_commands(),
            "admin_price": collect_admin(world),
        }
    delete_runtime("studio_scene_credits")
    snapshot["variants"] = variants
    return normalize(snapshot)


def write_golden(snapshot: dict) -> None:
    GOLDEN_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(GOLDEN_PATH, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(snapshot, fh, ensure_ascii=False, sort_keys=True, indent=1)
        fh.write("\n")


def read_golden() -> dict:
    with open(GOLDEN_PATH, encoding="utf-8") as fh:
        return json.load(fh)


@override_settings(**GOLDEN_SETTINGS)
class CartoonPathsLegacyGoldenTests(TestCase):
    """Режим legacy: цены мультстудии на всех путях — как на a23235f."""

    def setUp(self):
        cache.clear()
        start_price_mocks(self)

    def assert_golden(self, snapshot: dict) -> None:
        golden = read_golden()
        self.assertEqual(sorted(snapshot), sorted(golden))
        self.assertEqual(snapshot["images"], golden["images"], "кадры разошлись со снимком")
        for variant, sections in golden["variants"].items():
            for name, value in sections.items():
                self.assertEqual(snapshot["variants"][variant][name], value,
                                 f"цена сцены {variant}: раздел {name} разошёлся со снимком")

    def test_default_mode_matches_golden(self):
        snapshot = collect_all()
        if os.environ.get(WRITE_ENV) == "1":
            write_golden(snapshot)
            self.skipTest(f"снимок переписан: {GOLDEN_PATH}")
        self.assert_golden(snapshot)

    def test_explicit_legacy_ignores_markup_settings(self):
        """Наценка, порог, курс и себестоимость заданы, но режим legacy — цены прежние."""
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

        if os.environ.get(WRITE_ENV) == "1":
            self.skipTest("снимок пишет test_default_mode_matches_golden")
        self.assert_golden(collect_all(prepare=prepare))
