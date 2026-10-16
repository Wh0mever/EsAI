# -*- coding: utf-8 -*-
"""Мультстудия в режиме цен markup (BUILD_A, решение 6).

Сцена = кадр (себестоимость картинки с наценкой; 0, если кадр уже в запасе) +
видео по себестоимости в формате мультфильма. Ручная цена пресета и «цена
сцены» из админки не действуют. Без себестоимости — отказ, а не тариф.

Числа — PLAN §4.3: курс закреплён на 87.4, кредит — MASTER 4990/6500, наценка
40 %, порог 25 %, Nano Banana $0.039. Каталог OpenRouter — сохранённый, сети нет.
"""
from __future__ import annotations

import io
from contextlib import ExitStack
from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.core.management import call_command
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from adminapi.runtime import set_runtime
from ai import pricing
from ai.models import GenerationLog
from ai.tests_pricing_golden import (
    GOLDEN_SETTINGS, NANO, catalog_by_id, create_models, create_packages, create_presets, start_price_mocks)
from ai.video_cost import video_credits as chat_video_credits
from cartoon import pricing as cp
from cartoon.models import (CartoonCharacter, CartoonKeyframe, CartoonPreset, CartoonProject,
                            CartoonScene)

GROK = "x-ai/grok-imagine-video"


def _user(email: str, balance: int):
    user = get_user_model().objects.create_user(email=email, password="x-12345678")
    user.token_balance = balance
    user.save(update_fields=["token_balance"])
    return user


def _client(user) -> APIClient:
    client = APIClient()
    client.force_authenticate(user)
    return client


@override_settings(**GOLDEN_SETTINGS)
class CartoonMarkupBase(TestCase):
    def setUp(self):
        cache.clear()
        start_price_mocks(self)
        self.models = create_models()
        create_packages()
        nano = self.models[NANO]
        nano.unit_cost_usd = Decimal("0.039")
        nano.save(update_fields=["unit_cost_usd"])
        self.presets = create_presets(self.models)
        self.hero = CartoonCharacter.objects.create(name="Лис", image="cartoon/characters/fox.jpg",
                                                    is_public=True, description="a small fox")
        set_runtime(pricing.KEY_MODE, pricing.MODE_MARKUP)
        set_runtime(pricing.KEY_KGS_PER_USD, "87.4")
        pricing.invalidate_price_caches()

    def project(self, user, aspect="16:9"):
        return CartoonProject.objects.create(user=user, character=self.hero, aspect_ratio=aspect)

    def scene(self, project, slug, **extra):
        return CartoonScene.objects.create(project=project, preset=self.presets[slug], **extra)


class ScenePriceTests(CartoonMarkupBase):
    def test_mini_480p_5s_widescreen_scene_is_35(self):
        preset = self.presets["mini-5-480"]
        self.assertEqual(cp.frame_credits(preset.image_model), 7)
        self.assertEqual(cp.scene_video_credits(preset, aspect="16:9"), 28)
        self.assertEqual(cp.scene_credits(preset, aspect="16:9"), 35)
        self.assertEqual(preset.estimated_credits(), 35)

    def test_square_is_cheaper_than_widescreen(self):
        """1:1 у Seedance 2.0 720p — 720×720: почти вдвое меньше кадра, чем 16:9."""
        preset = self.presets["s20-5-720"]
        self.assertEqual(cp.scene_credits(preset, aspect="16:9"), 7 + 122)
        self.assertEqual(cp.scene_credits(preset, aspect="9:16"), 7 + 122)
        self.assertEqual(cp.scene_credits(preset, aspect="1:1"), 7 + 69)
        self.assertLess(cp.scene_credits(self.presets["mini-5-480"], aspect="1:1"),
                        cp.scene_credits(self.presets["mini-5-480"], aspect="16:9"))

    def test_pooled_keyframe_pays_video_only(self):
        self.assertEqual(cp.scene_credits(self.presets["mini-5-480"], keyframe_ready=True, aspect="16:9"), 28)
        self.assertEqual(cp.scene_credits(self.presets["s20-5-720"], keyframe_ready=True, aspect="1:1"), 69)

    def test_manual_price_and_studio_scene_price_do_not_apply(self):
        set_runtime("studio_scene_credits", 100)
        for slug in ("s20-5-720", "s20-manual-250", "s20-manual-100"):
            self.assertEqual(cp.scene_credits(self.presets[slug], aspect="16:9"), 129, slug)
        # В legacy те же пресеты стоят по-старому: переключатель — единственная разница.
        set_runtime(pricing.KEY_MODE, pricing.MODE_LEGACY)
        self.assertEqual(cp.scene_credits(self.presets["s20-manual-250"]), 250)
        self.assertEqual(cp.scene_credits(self.presets["s20-manual-100"]), 100)

    def test_no_aspect_means_preset_aspect(self):
        preset = self.presets["s20-5-720"]
        preset.aspect_ratio = "1:1"
        self.assertEqual(cp.scene_credits(preset), 76)
        self.assertEqual(cp.scene_credits(preset, aspect="16:9"), 129)

    def test_video_inputs_are_part_of_the_cost(self):
        """Первый кадр и фото героя уходят в модель: Grok берёт за входные картинки."""
        grok = self.models[GROK]
        spec = catalog_by_id()[GROK]
        with_inputs = chat_video_credits(grok, spec, "720p", 5, images=cp.SCENE_INPUT_IMAGES, aspect="16:9")
        self.assertEqual(cp.video_credits(grok, 5, "720p", aspect="16:9"), with_inputs)
        self.assertEqual(with_inputs, 57)
        self.assertEqual(chat_video_credits(grok, spec, "720p", 5, aspect="16:9"), 56)

    def test_unsaved_settings_preview_through_override(self):
        set_runtime(pricing.KEY_MODE, pricing.MODE_LEGACY)
        preset = self.presets["mini-5-480"]
        self.assertEqual(cp.scene_credits(preset), 37)
        with pricing.override_config(mode=pricing.MODE_MARKUP):
            self.assertEqual(cp.scene_credits(preset, aspect="16:9"), 35)
        with pricing.override_config(mode=pricing.MODE_MARKUP, markup_pct=Decimal("100")):
            self.assertEqual(cp.scene_credits(preset, aspect="16:9"), 9 + 39)
        self.assertEqual(cp.scene_credits(preset), 37)

    def test_scene_sample_for_previews(self):
        """Одна «типичная сцена» для превью админки и price_preview: обе цены и флаги."""
        set_runtime(pricing.KEY_MODE, pricing.MODE_LEGACY)
        nano = self.models[NANO]
        sample = cp.scene_sample(self.models["bytedance/seedance-2.0"], nano)
        self.assertEqual((sample.kind, sample.legacy, sample.markup, sample.flags),
                         ("cartoon", 149, 129, ("estimate",)))
        self.assertEqual(sample.shape, {"seconds": 5, "resolution": "720p", "aspect": "16:9"})
        self.assertEqual(sample.cost_usd, Decimal("0.8013"))
        self.assertEqual(cp.scene_sample(self.models["bytedance/seedance-2.0"], nano, aspect="1:1").markup, 76)
        veo = cp.scene_sample(self.models["google/veo-3.1-lite"], nano)
        self.assertEqual((veo.shape["seconds"], veo.markup), (4, 7 + 32))
        sora = cp.scene_sample(self.models["openai/sora-2-pro"], nano)
        self.assertEqual((sora.legacy, sora.markup, sora.cost_usd), (314, None, None))
        self.assertIn("no_cost", sora.flags)
        # Настройки превью не сохраняются и не утекают в действующие цены.
        self.assertEqual(cp.scene_credits(self.presets["s20-5-720"]), 149)

    def test_frame_without_cost_keeps_flat_price(self):
        nano = self.models[NANO]
        nano.unit_cost_usd = None
        nano.save(update_fields=["unit_cost_usd"])
        self.assertEqual(cp.frame_credits(nano), 4)
        self.assertEqual(cp.scene_credits(self.presets["mini-5-480"], aspect="16:9"), 4 + 28)


class RefusalTests(CartoonMarkupBase):
    """Sora нет в каталоге: себестоимость неизвестна — цены нет, съёмки нет."""

    def test_price_functions_refuse(self):
        preset = self.presets["sora-5"]
        with self.assertRaises(pricing.PriceUnavailable):
            cp.scene_credits(preset)
        with self.assertRaises(pricing.PriceUnavailable):
            cp.scene_video_credits(preset, aspect="16:9")
        self.assertIsNone(cp.scene_credits_or_none(preset))

    def test_catalogue_failure_refuses_instead_of_tariff(self):
        with patch("ai.handlers._openrouter_video_catalog", side_effect=RuntimeError("down")):
            with self.assertRaises(pricing.PriceUnavailable):
                cp.scene_credits(self.presets["s20-5-720"])

    def test_showcase_and_feed_show_no_price(self):
        body = APIClient().get("/api/cartoon/presets/").json()
        by_slug = {p["slug"]: p for p in body["presets"]}
        self.assertIsNone(by_slug["sora-5"]["credits"])
        self.assertTrue(by_slug["sora-5"]["price_unavailable"])
        self.assertEqual(by_slug["s20-5-720"]["credits"], 129)
        self.assertNotIn("price_unavailable", by_slug["s20-5-720"])

        user = _user("feed@example.com", 1000)
        project = self.project(user)
        self.scene(project, "sora-5")
        row = _client(user).get(f"/api/cartoon/projects/{project.pk}/").json()["scenes"][0]
        self.assertIsNone(row["preset"]["credits"])
        self.assertIsNone(row["render_credits"])
        self.assertTrue(row["price_unavailable"])

    def test_pricing_page_shows_the_new_cartoon_price(self):
        """Тарифы — цена сцены НОВОГО мультфильма: Mini 480p 5 с 16:9 у каждой сцены
        (у Sora своей себестоимости нет, но снимется она тоже на Mini)."""
        body = APIClient().get("/api/cartoon/pricing/").json()
        self.assertEqual((body["scene_min"], body["scene_typical"], body["scene_max"]), (35, 35, 35))
        self.assertEqual(body["settings"], {"video_model": "bytedance/seedance-2.0-mini",
                                            "model_name": "Seedance Mini", "resolution": "480p",
                                            "duration": 5, "source": "settings", "aspect_ratio": "16:9"})
        self.assertEqual(body["character"], 7)

    def test_pricing_page_skips_unpriced_scenes(self):
        """Mini выключена: новый мультфильм снимается по пресетам — и тарифы тоже,
        а сцены без себестоимости в диапазон «от и до» не входят."""
        self.models["bytedance/seedance-2.0-mini"].is_active = False
        self.models["bytedance/seedance-2.0-mini"].save(update_fields=["is_active"])
        pricing.invalidate_price_caches()
        body = APIClient().get("/api/cartoon/pricing/").json()
        priced = [cp.scene_credits_or_none(p) for p in self.presets.values()]
        priced = sorted(p for p in priced if p is not None)
        self.assertEqual(body["scene_min"], priced[0])
        self.assertEqual(body["scene_max"], priced[-1])
        self.assertEqual(body["settings"]["source"], "preset")
        self.assertEqual(body["character"], 7)

    def test_gate_refuses_and_charges_nothing(self):
        user = _user("gate@example.com", 1000)
        scene = self.scene(self.project(user), "sora-5")
        with patch("cartoon.views.render_scene.delay") as delay:
            r = _client(user).post(f"/api/cartoon/scenes/{scene.pk}/render/", {}, format="json")
        self.assertEqual(r.status_code, 503)
        self.assertEqual(r.json()["error_code"], "price_unavailable")
        self.assertEqual(r.json()["detail"], pricing.UNAVAILABLE_MESSAGE)
        delay.assert_not_called()
        scene.refresh_from_db()
        self.assertEqual(scene.status, CartoonScene.STATUS_DRAFT)

    def test_render_task_fails_before_drawing_the_frame(self):
        user = _user("task@example.com", 1000)
        scene = self.scene(self.project(user), "sora-5", status=CartoonScene.STATUS_NEW)
        with patch("cartoon.services.generate_keyframe") as draw, patch("cartoon.tasks._notify_scene"), \
                patch("cartoon.tasks.generate_scene_video") as shoot:
            from cartoon.tasks import render_scene

            result = render_scene.apply(args=[scene.pk]).get()
        self.assertEqual(result["status"], "price_unavailable")
        draw.assert_not_called()
        shoot.assert_not_called()
        scene.refresh_from_db()
        user.refresh_from_db()
        self.assertEqual(scene.status, CartoonScene.STATUS_FAILED)
        self.assertEqual(scene.error, pricing.UNAVAILABLE_MESSAGE)
        self.assertEqual(scene.credits_spent, 0)
        self.assertEqual(user.token_balance, 1000)

    def test_reserve_keeps_the_old_price_when_cost_vanishes(self):
        """Сцена уже снимается, а цены нет: резерв не обнуляется (legacy-цена)."""
        user = _user("reserve@example.com", 1000)
        project = self.project(user)
        self.scene(project, "sora-5", status=CartoonScene.STATUS_VIDEO, keyframe="cartoon/k/1.png")
        with pricing.override_config(mode=pricing.MODE_LEGACY):
            legacy_video = cp.scene_video_credits(self.presets["sora-5"])
        self.assertEqual(cp.reserved_credits(user), legacy_video)


class StudioPathsTests(CartoonMarkupBase):
    """Цена в формате мультфильма проходит через ленту, гейт и списание."""

    def test_feed_gate_and_showcase_follow_project_aspect(self):
        user = _user("aspect@example.com", 0)
        client = _client(user)
        square = self.project(user, "1:1")
        wide = self.project(user, "16:9")
        s_square = self.scene(square, "s20-5-720")
        s_wide = self.scene(wide, "s20-5-720")
        rows = {row["id"]: row for p in (square, wide)
                for row in client.get(f"/api/cartoon/projects/{p.pk}/").json()["scenes"]}
        self.assertEqual(rows[s_square.pk]["preset"]["credits"], 76)
        self.assertEqual(rows[s_square.pk]["render_credits"], 76)
        self.assertEqual(rows[s_wide.pk]["preset"]["credits"], 129)
        r = client.post(f"/api/cartoon/scenes/{s_square.pk}/render/", {}, format="json")
        self.assertEqual((r.status_code, r.json()["required"]), (402, 76))

        presets = APIClient().get("/api/cartoon/presets/", {"aspect_ratio": "1:1"}).json()["presets"]
        self.assertEqual({p["slug"]: p["credits"] for p in presets}["s20-5-720"], 76)

    def test_gate_with_pooled_keyframe_asks_for_video_only(self):
        user = _user("pool@example.com", 0)
        project = self.project(user, "16:9")
        scene = self.scene(project, "mini-5-480")
        CartoonKeyframe.objects.create(preset=scene.preset, character=self.hero, aspect_ratio="16:9",
                                       image="cartoon/keyframes/pool.png")
        r = _client(user).post(f"/api/cartoon/scenes/{scene.pk}/render/", {}, format="json")
        self.assertEqual((r.status_code, r.json()["required"]), (402, 28))
        scene.refresh_from_db()
        self.assertEqual(scene.keyframe, "cartoon/keyframes/pool.png")

    def test_render_charges_markup_prices_in_project_aspect(self):
        user = _user("render@example.com", 1000)
        scene = self.scene(self.project(user, "1:1"), "s20-5-720", status=CartoonScene.STATUS_NEW)
        fakes = (
            patch("cartoon.services.generate_keyframe", return_value="cartoon/keyframes/new.png"),
            patch("cartoon.tasks.ensure_video_prompt", return_value={"prompt": "p", "negative": ""}),
            patch("cartoon.tasks.generate_scene_video", return_value="cartoon/scenes/new.mp4"),
            patch("cartoon.tasks.last_frame_of", return_value=""),
            patch("cartoon.tasks._notify_scene"),
            patch("cartoon.tasks.remember_pair_video"),
            patch("cartoon.audio.remix_scene"),
        )
        from cartoon.tasks import render_scene

        with ExitStack() as stack:
            for fake in fakes:
                stack.enter_context(fake)
            self.assertEqual(render_scene.apply(args=[scene.pk]).get()["status"], "ready")
        scene.refresh_from_db()
        user.refresh_from_db()
        self.assertEqual(scene.credits_spent, 7 + 69)
        self.assertEqual(user.token_balance, 1000 - 76)
        self.assertEqual(GenerationLog.objects.get(scene_id=scene.pk).credits_planned, 69)

    def test_reserve_uses_project_aspect(self):
        user = _user("reserve2@example.com", 1000)
        self.scene(self.project(user, "1:1"), "s20-5-720", status=CartoonScene.STATUS_NEW)
        self.scene(self.project(user, "16:9"), "mini-5-480", status=CartoonScene.STATUS_VIDEO,
                   keyframe="cartoon/k/2.png")
        self.assertEqual(cp.reserved_credits(user), 76 + 28)

    def test_frame_price_everywhere(self):
        user = _user("frames@example.com", 0)
        client = _client(user)
        preset = self.presets["s20-5-720"]
        r = client.post(f"/api/cartoon/presets/{preset.pk}/try-on/",
                        {"character_id": self.hero.pk, "aspect_ratio": "16:9"}, format="json")
        self.assertEqual((r.status_code, r.json()["required"]), (402, 7))
        r = client.post("/api/cartoon/characters/generate/", {"prompt": "рыжий лис"}, format="json")
        self.assertEqual((r.status_code, r.json()["required"]), (402, 7))
        custom = self.scene(self.project(user), "s20-5-720", custom_text="Лис катается на коньках")
        r = client.post(f"/api/cartoon/scenes/{custom.pk}/frame/", {}, format="json")
        self.assertEqual((r.status_code, r.json()["required"]), (402, 7))
        presets = APIClient().get("/api/cartoon/presets/").json()["presets"]
        self.assertEqual({p["tryon_credits"] for p in presets}, {7})

        from cartoon import services

        with patch("cartoon.services.generate_keyframe", return_value="cartoon/keyframes/x.png"), \
                patch("cartoon.services.ensure_custom_prompt"):
            self.assertEqual(services.get_or_create_keyframe(preset, self.hero, None, "1:1")[1], 7)
            self.assertEqual(services.draw_linked_keyframe(custom, self.hero, None, "a.png", "1:1")[1], 7)
            self.assertEqual(services.draw_custom_keyframe(custom, self.hero, None, "1:1")[1], 7)

    def test_admin_price_column_marks_ignored_manual_price(self):
        from django.contrib import admin

        from cartoon.admin import CartoonPresetAdmin

        column = CartoonPresetAdmin(CartoonPreset, admin.site).price
        self.assertEqual(column(self.presets["s20-manual-250"]), "129 (ручная цена не действует)")
        self.assertEqual(column(self.presets["s20-5-720"]), "129")
        self.assertEqual(column(self.presets["sora-5"]), "—")
        set_runtime(pricing.KEY_MODE, pricing.MODE_LEGACY)
        self.assertEqual(column(self.presets["s20-manual-250"]), "250 (вручную)")


class CommandsTests(CartoonMarkupBase):
    def test_warm_keyframes_counts_markup_frame_price(self):
        out = io.StringIO()
        call_command("warm_keyframes", "--dry-run", "--limit", "3", stdout=out, stderr=io.StringIO())
        self.assertIn("Нарисовать: 3 кадров ≈ 21 кредитов.", out.getvalue())

    def test_studio_video_model_shows_markup_price(self):
        out = io.StringIO()
        call_command("studio_video_model", "--model", "bytedance/seedance-2.0-mini", "--resolution", "480p",
                     stdout=out, stderr=io.StringIO())
        text = out.getvalue()
        self.assertIn("Станет 35 кр (кадр 7 + видео 28 за 5 с)", text)
        self.assertIn("ручная цена и «цена сцены» из админки не действуют", text)

    def test_studio_video_model_refuses_model_without_cost(self):
        out, err = io.StringIO(), io.StringIO()
        call_command("studio_video_model", "--model", "openai/sora-2-pro", "--apply", stdout=out, stderr=err)
        self.assertIn("цены нет", out.getvalue())
        self.assertIn("Не переключаю", err.getvalue())
        self.assertFalse(CartoonPreset.objects.filter(
            video_model__openrouter_id="openai/sora-2-pro").exclude(slug="sora-5").exists())
