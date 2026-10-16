# -*- coding: utf-8 -*-
"""manage.py price_preview — таблица legacy → markup на подпись (BUILD_A, решение 12).

Команда ничего не меняет и не ходит в сеть сама: каталог видео и курс — те же
кэши, что у генерации (в тестах — сохранённый каталог и курс 87.4).
"""
from __future__ import annotations

import csv
import io
from decimal import Decimal

from django.core.cache import cache
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase, override_settings

from adminapi.runtime import get_runtime, set_runtime
from ai import pricing
from ai.tests_pricing_golden import (
    GOLDEN_SETTINGS, NANO, create_models, create_packages, create_presets, start_price_mocks)

SEEDANCE = "bytedance/seedance-2.0"
MINI = "bytedance/seedance-2.0-mini"
KLEIN = "black-forest-labs/flux.2-klein-4b"


@override_settings(**GOLDEN_SETTINGS)
class PricePreviewTests(TestCase):
    def setUp(self):
        cache.clear()
        start_price_mocks(self)
        self.models = create_models()
        create_packages()
        create_presets(self.models)
        for orid, cost in ((NANO, "0.039"), (KLEIN, "0.015")):
            model = self.models[orid]
            model.unit_cost_usd = Decimal(cost)
            model.save(update_fields=["unit_cost_usd"])
        set_runtime(pricing.KEY_KGS_PER_USD, "87.4")

    def run_csv(self, *args) -> list[dict]:
        out = io.StringIO()
        call_command("price_preview", "--csv", *args, stdout=out)
        return list(csv.DictReader(io.StringIO(out.getvalue())))

    @staticmethod
    def find(rows, model_id, kind, shape) -> dict:
        return next(r for r in rows if r["model_id"] == model_id and r["kind"] == kind and r["shape"] == shape)

    def test_csv_has_every_active_model_and_kind(self):
        rows = self.run_csv()
        self.assertEqual(list(rows[0]), ["model_id", "model", "kind", "shape", "cost_usd", "legacy", "markup",
                                         "delta_pct", "flags"])
        active = {m.openrouter_id for m in self.models.values()}
        self.assertEqual({r["model_id"] for r in rows}, active)
        self.assertEqual({r["kind"] for r in rows}, {"video", "cartoon", "image", "text"})
        # Группы идут подряд: видео, мультфильм, картинки, текст.
        kinds = [r["kind"] for r in rows]
        self.assertEqual(sorted(kinds, key=["video", "cartoon", "image", "text"].index), kinds)

    def test_video_rows_follow_plan_cells(self):
        rows = self.run_csv()
        row = self.find(rows, SEEDANCE, "video", "5 с · 720p · 16:9")
        self.assertEqual((row["cost_usd"], row["legacy"], row["markup"], row["delta_pct"], row["flags"]),
                         ("0.7623", "145", "122", "-16", ""))
        self.assertEqual(self.find(rows, MINI, "video", "5 с · 480p · 16:9")["markup"], "28")
        # 480p/720p × 5/10/15 с у Mini — шесть строк, 1080p Mini не умеет.
        self.assertEqual(len([r for r in rows if r["model_id"] == MINI and r["kind"] == "video"]), 6)
        # Veo снимает 4/6/8 с: 5/10/15 притягиваются к 4 и 8.
        veo = [r["shape"] for r in rows if r["model_id"] == "google/veo-3.1-lite" and r["kind"] == "video"]
        self.assertEqual(veo, ["4 с · 720p · 16:9", "8 с · 720p · 16:9", "4 с · 1080p · 16:9",
                               "8 с · 1080p · 16:9"])

    def test_model_without_cost_is_flagged_not_priced(self):
        rows = self.run_csv()
        sora = self.find(rows, "openai/sora-2-pro", "video", "5 с · 720p · 16:9")
        self.assertEqual((sora["legacy"], sora["markup"], sora["flags"]), ("310", "", "no_cost"))
        self.assertIn("no_cost", self.find(rows, "openai/sora-2-pro", "cartoon", "сцена 5 с · 720p · 16:9")["flags"])

    def test_image_text_and_cartoon_rows(self):
        rows = self.run_csv()
        klein = self.find(rows, KLEIN, "image", "1 картинка")
        self.assertEqual((klein["cost_usd"], klein["legacy"], klein["markup"], klein["flags"]),
                         ("0.015", "2", "3", "estimate"))
        self.assertEqual(self.find(rows, KLEIN, "image", "1 картинка + 1 фото")["markup"], "3")
        pro = self.find(rows, "black-forest-labs/flux.2-pro", "image", "1 картинка")
        self.assertEqual((pro["legacy"], pro["markup"], pro["flags"]), ("4", "4", "no_cost"))
        gpt = self.find(rows, "openai/gpt-4o", "text", "2000 токенов")
        self.assertEqual((gpt["legacy"], gpt["markup"]), ("34", "34"))
        # Сцена Mini 720p 5 с 16:9: кадр 7 + видео 61 = 68 (PLAN §4.3).
        scene = self.find(rows, MINI, "cartoon", "сцена 5 с · 720p · 16:9")
        self.assertEqual((scene["legacy"], scene["markup"], scene["flags"]), ("77", "68", "estimate"))

    def test_chat_flags_for_images(self):
        # Чат списывает картинку не по строке: Nano Banana — по токенам, правка FLUX Flex — как с 1 фото.
        flex = self.models["black-forest-labs/flux.2-flex"]
        flex.unit_cost_usd, flex.ref_cost_usd = Decimal("0.06"), Decimal("0.06")
        flex.save(update_fields=["unit_cost_usd", "ref_cost_usd"])
        rows = self.run_csv("--kind", "image")
        self.assertEqual(self.find(rows, NANO, "image", "1 картинка")["flags"], "estimate;chat_tokens")
        plain = self.find(rows, flex.openrouter_id, "image", "1 картинка")
        self.assertEqual((plain["markup"], plain["flags"]), ("10", "estimate;chat_one_ref"))
        edit = self.find(rows, flex.openrouter_id, "image", "1 картинка + 1 фото")
        self.assertEqual((edit["markup"], edit["flags"]), ("20", "estimate"))
        self.assertEqual(self.find(rows, KLEIN, "image", "1 картинка")["flags"], "estimate")
        # Тариф из «Пересчитать тариф картинок в чате»: чат берёт цену строки — флага нет.
        nano = self.models[NANO]
        nano.markup_coefficient = pricing.chat_image_tariff(nano).coefficient
        nano.save(update_fields=["markup_coefficient"])
        rows = self.run_csv("--kind", "image", "--model", NANO)
        self.assertEqual(self.find(rows, NANO, "image", "1 картинка")["flags"], "estimate")

    def test_unsaved_settings_and_floor_flag(self):
        rows = self.run_csv("--markup-pct", "60", "--kind", "video", "--model", SEEDANCE)
        self.assertEqual(self.find(rows, SEEDANCE, "video", "5 с · 720p · 16:9")["markup"], "139")
        self.assertEqual({r["kind"] for r in rows}, {"video"})
        model = self.models[SEEDANCE]
        model.markup_pct = Decimal("10")
        model.save(update_fields=["markup_pct"])
        row = self.find(self.run_csv("--model", SEEDANCE), SEEDANCE, "video", "5 с · 720p · 16:9")
        self.assertEqual((row["markup"], row["flags"]), ("109", "floor"))
        # Флаги примеряли настройки, но ничего не сохранили.
        self.assertEqual(get_runtime(pricing.KEY_MARKUP_PCT, ""), "")
        self.assertEqual(pricing.stored_config().mode, pricing.MODE_LEGACY)

    def test_bad_values_are_refused(self):
        with self.assertRaises(CommandError):
            call_command("price_preview", "--markup-pct", "много", stdout=io.StringIO())
        with self.assertRaises(CommandError):
            call_command("price_preview", "--kgs-per-usd", "0", stdout=io.StringIO())

    def test_markdown_report(self):
        out = io.StringIO()
        call_command("price_preview", "--model", SEEDANCE, "--model", NANO, stdout=out)
        text = out.getvalue()
        self.assertIn("# Цены: legacy → markup", text)
        self.assertIn("Сейчас действует: legacy. Наценка 40 %, порог 25 %, курс 87.4 сом/$ (закреплён", text)
        self.assertIn("Кредит: MASTER · 0.76769 сом = $0.0087837.", text)
        self.assertIn("| Seedance 2.0 (`bytedance/seedance-2.0`) | видео | 5 с · 720p · 16:9 | 0.7623 | 145 | "
                      "122 | −16 % |  |", text)
        self.assertIn("| мультфильм | сцена 5 с · 720p · 16:9 |", text)
        self.assertIn("Сцен с ручной ценой: 2 — в режиме markup она не действует.", text)
