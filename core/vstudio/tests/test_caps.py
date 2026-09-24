"""Реестр возможностей моделей (vstudio/caps.py, спецификация §3)."""
from unittest.mock import patch

from django.core.exceptions import ValidationError
from django.test import SimpleTestCase, override_settings

from vstudio import caps
from vstudio.tests.caps_fixtures import (GROK, HAILUO_23, KLING_STD, SEEDANCE_20, SEEDANCE_MINI, VEO_FAST,
                                         make_caps, model)


class LookupTests(SimpleTestCase):
    def test_every_model_points_to_a_known_family(self):
        for model_id, (family, verified) in caps.MODELS.items():
            self.assertIn(family, caps.FAMILIES, model_id)
            fam = caps.FAMILIES[family]
            if verified:
                # Проба бывает только у тех, у кого вендор вообще заявил референсы.
                self.assertGreater(fam.vendor_max_image_refs, 0, model_id)
            self.assertLessEqual(fam.enabled_refs, fam.vendor_max_image_refs, model_id)
            if fam.frames_with_refs == "soft_pin":
                self.assertIn(caps.FRAME_FIRST, fam.frames, model_id)

    def test_suffixes_and_unknown(self):
        self.assertEqual(caps.lookup("bytedance/seedance-2.0")[0], "seedance2")
        self.assertEqual(caps.lookup("google/gemini-3-pro-image-preview")[0], "nano_banana_2")
        self.assertEqual(caps.lookup("black-forest-labs/flux.2-pro:free")[0], "flux2")
        self.assertEqual(caps.lookup("OpenAI/Sora-2"), (None, None))
        self.assertEqual(caps.lookup(""), (None, None))

    def test_seedance_tag_is_bracketed(self):
        # Решение лида: шаблон тега Seedance — «[Image N]».
        self.assertEqual(caps.FAMILIES["seedance2"].mention_template, "[Image {n}]")
        self.assertEqual(caps.FAMILIES["seedance25"].mention_template, "[Image {n}]")


class ForModelTests(SimpleTestCase):
    def test_seedance_20_merges_catalog_and_overlay(self):
        c = make_caps("bytedance/seedance-2.0")
        self.assertEqual(c.kind, "video")
        self.assertEqual(c.family, "seedance2")
        self.assertEqual(c.name, "Seedance 2.0")
        self.assertEqual(c.durations, tuple(range(4, 16)))
        self.assertEqual(c.resolutions, ("480p", "720p", "1080p", "4K"))
        self.assertIn("21:9", c.aspect_ratios)
        self.assertTrue(c.audio)
        self.assertTrue(c.seed)
        # Негатива у Seedance нет вовсе.
        self.assertIsNone(c.negative_param)
        self.assertFalse(c.negative)
        self.assertEqual(c.frames, frozenset({"first_frame", "last_frame"}))
        # Референсы подтверждены боевыми генерациями — включены все 9.
        self.assertEqual(c.verified, caps.SEEDANCE_20_VERIFIED)
        self.assertEqual(c.max_image_refs, 9)
        self.assertEqual(c.frames_with_refs, "soft_pin")
        self.assertEqual(c.prompt_soft_words, 150)
        self.assertEqual(c.prompt_hard_chars, 6000)
        self.assertEqual(c.prompt_lang, "en")
        self.assertTrue(c.rejects_real_faces)
        self.assertEqual(c.min_ref_px, 300)
        self.assertEqual(c.ref_aspect_range, (0.4, 2.5))

    def test_unprobed_models_have_references_off(self):
        # Всё, кроме Seedance 2.0, — только кадры, пока проба не подтвердила референсы.
        for model_id, spec in (("bytedance/seedance-2.0-mini", SEEDANCE_MINI),
                               ("google/veo-3.1-fast", VEO_FAST), ("kwaivgi/kling-v3.0-std", KLING_STD),
                               ("x-ai/grok-imagine-video", GROK), ("minimax/hailuo-2.3", HAILUO_23)):
            c = make_caps(model_id, spec=spec)
            self.assertEqual(c.max_image_refs, 0, model_id)
            self.assertIsNone(c.verified, model_id)
            self.assertFalse(c.refs_enabled, model_id)

    def test_image_models_need_no_catalog(self):
        with patch.object(caps, "catalog_spec") as cat:
            c = caps.for_model(model("google/gemini-2.5-flash-image"))
        cat.assert_not_called()
        self.assertEqual(c.kind, "image")
        self.assertEqual(c.max_image_refs, 3)
        self.assertEqual(c.mention_template, "image {n}")
        from ai.aspect import IMAGE_ASPECT_RATIOS

        self.assertEqual(c.aspect_ratios, tuple(IMAGE_ASPECT_RATIOS))
        self.assertEqual(c.durations, ())
        self.assertEqual(c.frames, frozenset())
        # Nano Banana 2 держит 14, но уверенно — 6.
        self.assertEqual(caps.for_model(model("google/gemini-3.1-flash-image-preview")).max_image_refs, 6)
        self.assertEqual(caps.for_model(model("black-forest-labs/flux.2-klein-4b")).max_image_refs, 4)

    def test_hidden_models(self):
        spec = SEEDANCE_20
        self.assertIsNone(caps.for_model(model("bytedance/seedance-2.0", vstudio_enabled=False), spec=spec))
        self.assertIsNone(caps.for_model(model("bytedance/seedance-2.0", is_active=False), spec=spec))
        self.assertIsNone(caps.for_model(None))
        # Семейство неизвестно коду (Sora 2 и всё новое).
        self.assertIsNone(caps.for_model(model("openai/sora-2-pro"), spec={"id": "openai/sora-2-pro"}))
        # Видео-модели нет в живом каталоге — скрыта.
        self.assertIsNone(caps.for_model(model("bytedance/seedance-2.0"), spec={}))

    def test_uses_the_shared_catalog_cache(self):
        with patch("ai.handlers._openrouter_video_catalog", return_value=SEEDANCE_20) as cat:
            c = caps.for_model(model("bytedance/seedance-2.0"))
        cat.assert_called_once_with("bytedance/seedance-2.0")
        self.assertEqual(c.durations[0], 4)
        with patch("ai.handlers._openrouter_video_catalog", return_value={}):
            self.assertIsNone(caps.for_model(model("bytedance/seedance-2.0")))
        with patch("ai.handlers._openrouter_video_catalog", side_effect=RuntimeError("boom")):
            self.assertIsNone(caps.for_model(model("bytedance/seedance-2.0")))

    def test_broken_model_row_hides_instead_of_crashing(self):
        with self.assertLogs("vstudio.caps", level="ERROR"):
            with patch.object(caps, "build", side_effect=RuntimeError("boom")):
                self.assertIsNone(caps.for_model(model("bytedance/seedance-2.0"), spec=SEEDANCE_20))
        # Кривой sort_order в строке — не повод падать: порядок по умолчанию.
        c = caps.for_model(model("bytedance/seedance-2.0", sort_order="x"), spec=SEEDANCE_20)
        self.assertEqual(c.sort, 100)

    def test_catalog_can_only_narrow_frames(self):
        c = make_caps("bytedance/seedance-2.0", spec=dict(SEEDANCE_20, supported_frame_images=["first_frame"]))
        self.assertEqual(c.frames, frozenset({"first_frame"}))
        c = make_caps("minimax/hailuo-2.3",
                      spec=dict(HAILUO_23, supported_frame_images=["first_frame", "last_frame"]))
        # Каталог не может добавить то, чего нет в надстройке.
        self.assertEqual(c.frames, frozenset({"first_frame"}))
        c = make_caps("bytedance/seedance-2.0", spec=dict(SEEDANCE_20, supported_frame_images=[]))
        self.assertEqual(c.frames, frozenset())

    def test_negative_only_through_known_passthrough(self):
        veo = make_caps("google/veo-3.1-fast")
        self.assertEqual((veo.negative_param, veo.negative_slug), ("negativePrompt", "google-vertex"))
        self.assertTrue(veo.negative)
        no_pass = make_caps("google/veo-3.1-fast", spec=dict(VEO_FAST, allowed_passthrough_parameters=[]))
        self.assertFalse(no_pass.negative)
        # Kling: имя есть, а slug провайдера не подтверждён пробой — негатив выключен.
        self.assertFalse(make_caps("kwaivgi/kling-v3.0-std").negative)
        # Словарь {slug: [имена]} даёт slug прямо из каталога.
        kling = make_caps("kwaivgi/kling-v3.0-std",
                          spec=dict(KLING_STD, allowed_passthrough_parameters={"kling": ["negative_prompt"]}))
        self.assertEqual((kling.negative_param, kling.negative_slug), ("negative_prompt", "kling"))

    def test_catalog_fields_are_cleaned(self):
        spec = dict(SEEDANCE_20, supported_durations=["5", 10, "x", 10, -1],
                    supported_resolutions=["720p", "", "720p", None], generate_audio=None, seed=None)
        c = make_caps("bytedance/seedance-2.0", spec=spec)
        self.assertEqual(c.durations, (5, 10))
        self.assertEqual(c.resolutions, ("720p",))
        self.assertFalse(c.audio)
        self.assertFalse(c.seed)
        # Нет длительностей в каталоге — запасной список семейства.
        c = make_caps("bytedance/seedance-2.0", spec=dict(SEEDANCE_20, supported_durations=[]))
        self.assertEqual(c.durations, tuple(range(4, 16)))

    def test_badge_and_sort_come_from_the_model_row(self):
        c = caps.for_model(model("bytedance/seedance-2.0", short_label="Лучший баланс", sort_order=7),
                           spec=SEEDANCE_20)
        self.assertEqual((c.badge, c.sort), ("Лучший баланс", 7))

    def test_real_gptmodels_instance(self):
        from ai.models import GPTModels

        m = GPTModels(name="Seedance 2.0", openrouter_id="bytedance/seedance-2.0", category="video",
                      max_tokens=1000, is_active=True, vstudio_enabled=True,
                      vstudio_overrides={"badge": "Новинка"})
        c = caps.for_model(m, spec=SEEDANCE_20)
        self.assertEqual(c.badge, "Новинка")
        self.assertEqual(c.max_image_refs, 9)


class OverrideMergeTests(SimpleTestCase):
    def test_emergency_off(self):
        c = make_caps("bytedance/seedance-2.0", {"refs": "off"})
        self.assertEqual(c.max_image_refs, 0)

    def test_enable_after_probe_within_vendor_limit(self):
        c = make_caps("google/veo-3.1-fast", {"refs_verified": "2026-10-01"})
        self.assertEqual((c.verified, c.max_image_refs), ("2026-10-01", 3))
        c = make_caps("google/veo-3.1-fast", {"refs_verified": "2026-10-01", "max_image_refs": 2})
        self.assertEqual(c.max_image_refs, 2)
        # Мимо формы записали больше лимита — всё равно не выше вендора.
        c = make_caps("google/veo-3.1-fast", {"refs_verified": "2026-10-01", "max_image_refs": 10})
        self.assertEqual(c.max_image_refs, 3)
        # Без пробы max_image_refs ничего не включает.
        self.assertEqual(make_caps("google/veo-3.1-fast", {"max_image_refs": 2}).max_image_refs, 0)

    def test_refs_verified_ignored_where_vendor_has_none(self):
        with self.assertLogs("vstudio.caps", level="WARNING"):
            c = make_caps("kwaivgi/kling-v3.0-std", {"refs_verified": "2026-10-01"})
        self.assertEqual(c.max_image_refs, 0)
        self.assertIsNone(c.verified)

    def test_unknown_and_bad_keys_are_ignored_with_a_warning(self):
        with self.assertLogs("vstudio.caps", level="WARNING") as logs:
            c = make_caps("bytedance/seedance-2.0",
                          {"mention_template": "Image {n}", "frames": ["x"], "badge": 5, "eta_s": "fast"})
        self.assertTrue(any("mention_template" in line for line in logs.output))
        # Что модель умеет в принципе, из админки не меняется.
        self.assertEqual(c.mention_template, "[Image {n}]")
        self.assertEqual(c.badge, "")
        self.assertEqual(c.eta_s, caps.FAMILIES["seedance2"].eta_s)

    def test_badge_sort_eta(self):
        c = make_caps("bytedance/seedance-2.0", {"badge": " Новинка ", "sort": 3, "eta_s": 200})
        self.assertEqual((c.badge, c.sort, c.eta_s), ("Новинка", 3, 200))

    def test_non_dict_overrides(self):
        c = make_caps("bytedance/seedance-2.0", None)
        self.assertEqual(c.max_image_refs, 9)
        m = model("bytedance/seedance-2.0", vstudio_overrides=["refs"])
        self.assertEqual(caps.for_model(m, spec=SEEDANCE_20).max_image_refs, 9)


class ValidateOverridesTests(SimpleTestCase):
    def test_empty(self):
        self.assertEqual(caps.validate_overrides(None), {})
        self.assertEqual(caps.validate_overrides(""), {})
        self.assertEqual(caps.validate_overrides({}), {})

    def test_clean_copy(self):
        got = caps.validate_overrides({"badge": " Хит ", "sort": 1, "refs": "off", "eta_s": 90,
                                       "refs_verified": "2026-10-01", "max_image_refs": 2},
                                      "google/veo-3.1-fast")
        self.assertEqual(got, {"badge": "Хит", "sort": 1, "refs": "off", "eta_s": 90,
                               "refs_verified": "2026-10-01", "max_image_refs": 2})

    def assertInvalid(self, value, model_ref="bytedance/seedance-2.0", needle=""):
        with self.assertRaises(ValidationError) as ctx:
            caps.validate_overrides(value, model_ref)
        if needle:
            self.assertTrue(any(needle in m for m in ctx.exception.messages), ctx.exception.messages)
        return ctx.exception

    def test_rejections(self):
        self.assertInvalid(["badge"], needle="JSON-объект")
        self.assertInvalid({"mention_template": "x"}, needle="Неизвестные ключи")
        self.assertInvalid({"badge": "x" * 41}, needle="badge")
        self.assertInvalid({"sort": True}, needle="sort")
        self.assertInvalid({"refs": "on"}, needle="refs")
        self.assertInvalid({"refs_verified": "01.10.2026"}, needle="refs_verified")
        self.assertInvalid({"refs_verified": "2026-02-30"}, needle="refs_verified")
        self.assertInvalid({"max_image_refs": -1}, needle="max_image_refs")
        self.assertInvalid({"eta_s": 0}, needle="eta_s")

    def test_vendor_limits(self):
        self.assertInvalid({"max_image_refs": 10}, "bytedance/seedance-2.0", needle="(9)")
        self.assertInvalid({"max_image_refs": 4}, "google/veo-3.1-fast", needle="(3)")
        # У Veo Lite и Kling вендор референсов не заявил.
        self.assertInvalid({"refs_verified": "2026-10-01"}, "google/veo-3.1-lite", needle="вендор")
        self.assertInvalid({"refs_verified": "2026-10-01"}, "kwaivgi/kling-v3.0-std", needle="вендор")

    def test_accepts_model_instance_and_unknown_model(self):
        m = model("google/veo-3.1-fast")
        self.assertEqual(caps.validate_overrides({"max_image_refs": 3}, m), {"max_image_refs": 3})
        # Модель, которую код ещё не знает: лимиты не проверить, но и не запрещено.
        self.assertEqual(caps.validate_overrides({"max_image_refs": 50}, "new/model"), {"max_image_refs": 50})

    def test_admin_helper_calls_it(self):
        # Связка с формой админки (BE-1): ai.models.validate_vstudio_overrides(value, model_ref)
        # сначала проверяет белый список, потом зовёт нас за лимитами вендора.
        from ai import models as ai_models

        helper = getattr(ai_models, "validate_vstudio_overrides", None)
        if helper is None:
            self.skipTest("BE-1 ещё не добавил проверку")
        with self.assertRaises(ValidationError) as ctx:
            helper({"max_image_refs": 5}, "google/veo-3.1-fast")
        self.assertTrue(any("(3)" in m for m in ctx.exception.messages), ctx.exception.messages)
        self.assertEqual(helper({"max_image_refs": 3, "badge": " Хит "}, "google/veo-3.1-fast"),
                         {"max_image_refs": 3, "badge": "Хит"})


@override_settings(VIDEO_GEN_DURATION=5, VIDEO_GEN_RESOLUTION="720p")
class JsonTests(SimpleTestCase):
    def test_defaults(self):
        self.assertEqual(caps.defaults(make_caps("bytedance/seedance-2.0")),
                         {"duration": 5, "resolution": "720p", "aspect_ratio": "16:9"})
        self.assertEqual(caps.defaults(make_caps("google/veo-3.1-fast")),
                         {"duration": 4, "resolution": "720p", "aspect_ratio": "16:9"})
        self.assertEqual(caps.defaults(make_caps("minimax/hailuo-2.3")),
                         {"duration": 6, "resolution": "1080p", "aspect_ratio": "16:9"})
        self.assertEqual(caps.defaults(caps.for_model(model("black-forest-labs/flux.2-flex"))),
                         {"aspect_ratio": "auto"})

    def test_to_json(self):
        got = caps.to_json(make_caps("bytedance/seedance-2.0"))
        self.assertEqual(got["frames"], ["first_frame", "last_frame"])
        self.assertEqual(got["refs"], {"image": 9})
        self.assertEqual(got["prompt"], {"soft_words": 150, "hard_chars": 6000, "lang": "en"})
        self.assertEqual(got["frames_with_refs"], "soft_pin")
        self.assertIsNone(got["ref_forces_duration"])
        self.assertTrue(got["rejects_real_faces"])
        self.assertEqual(got["ref_aspect_range"], [0.4, 2.5])
        self.assertFalse(got["negative"])
        import json

        json.dumps(got)  # сериализуется без frozenset и кортежей-сюрпризов
        veo = caps.to_json(make_caps("google/veo-3.1-fast"))
        self.assertEqual(veo["ref_forces_duration"], 8)
        self.assertTrue(veo["negative"])
