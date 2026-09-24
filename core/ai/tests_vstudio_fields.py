# -*- coding: utf-8 -*-
"""BE-1: поля видеостудии у существующих моделей ai.

Проверяем то, на что опираются остальные треки: источник журнала «vstudio»
влезает в поле, модель по умолчанию скрыта, а правки из админки проходят
только по белому списку (спецификация §3.3) — и через vstudio.caps, когда он
появится.
"""
import sys
import types
from decimal import Decimal
from unittest.mock import patch

from django.contrib import admin
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import RequestFactory, TestCase

from ai.models import GenerationLog, GPTModels, VSTUDIO_OVERRIDE_KEYS, validate_vstudio_overrides


def _fake_caps(fn):
    """Подменить vstudio.caps модулем с данной validate_overrides."""
    mod = types.ModuleType("vstudio.caps")
    mod.validate_overrides = fn
    return patch.dict(sys.modules, {"vstudio.caps": mod})


# Заглушка: vstudio.caps нет — работает только белый список.
_NO_CAPS = patch.dict(sys.modules, {"vstudio.caps": None})


class GenerationLogSourceTests(TestCase):
    def test_vstudio_source_fits_field_and_has_label(self):
        field = GenerationLog._meta.get_field("source")
        self.assertLessEqual(len(GenerationLog.SOURCE_VSTUDIO), field.max_length)
        self.assertIn(GenerationLog.SOURCE_VSTUDIO, dict(field.choices))
        row = GenerationLog.objects.create(kind=GenerationLog.KIND_VIDEO,
                                           source=GenerationLog.SOURCE_VSTUDIO,
                                           params={"take": "a" * 32})
        row.refresh_from_db()
        self.assertEqual(row.source, "vstudio")
        self.assertEqual(row.get_source_display(), "Видеостудия")

    def test_old_sources_untouched(self):
        choices = dict(GenerationLog.SOURCE_CHOICES)
        self.assertEqual(choices["chat"], "Чат")
        self.assertEqual(choices["studio"], "Студия")
        self.assertEqual(choices["bot"], "Бот")


class GPTModelsVstudioFieldsTests(TestCase):
    def test_defaults_hidden_and_empty(self):
        m = GPTModels.objects.create(name="Seedance", openrouter_id="bytedance/seedance-2.0",
                                     max_tokens=10, category="video")
        m.refresh_from_db()
        self.assertFalse(m.vstudio_enabled)
        self.assertEqual(m.vstudio_overrides, {})


class ValidateOverridesStubTests(TestCase):
    """Без vstudio.caps — только белый список и типы."""

    def test_empty_becomes_dict(self):
        with _NO_CAPS:
            self.assertEqual(validate_vstudio_overrides(None), {})
            self.assertEqual(validate_vstudio_overrides(""), {})
            self.assertEqual(validate_vstudio_overrides({}), {})

    def test_all_allowed_keys_pass(self):
        value = {"badge": "Новинка", "sort": 5, "refs": "off", "refs_verified": "2026-09-24",
                 "max_image_refs": 3, "eta_s": 90}
        self.assertEqual(set(value), set(VSTUDIO_OVERRIDE_KEYS))
        with _NO_CAPS:
            self.assertEqual(validate_vstudio_overrides(value, "bytedance/seedance-2.0"), value)

    def test_unknown_key_rejected(self):
        with _NO_CAPS, self.assertRaises(ValidationError) as ctx:
            validate_vstudio_overrides({"mention_template": "[Image {n}]"})
        self.assertIn("mention_template", " ".join(ctx.exception.messages))

    def test_bad_values_rejected(self):
        bad = [
            {"badge": "x" * 41},
            {"badge": 5},
            {"sort": True},
            {"sort": "1"},
            {"refs": "on"},
            {"refs_verified": "24.09.2026"},
            {"refs_verified": "2026-13-01"},
            {"max_image_refs": -1},
            {"max_image_refs": 2.5},
            {"eta_s": 0},
        ]
        with _NO_CAPS:
            for value in bad:
                with self.subTest(value=value), self.assertRaises(ValidationError):
                    validate_vstudio_overrides(value)

    def test_not_an_object_rejected(self):
        with _NO_CAPS:
            for value in (["badge"], "badge", 5):
                with self.subTest(value=value), self.assertRaises(ValidationError):
                    validate_vstudio_overrides(value)


class ValidateOverridesCapsTests(TestCase):
    """Когда vstudio.caps есть — его ответ главный (лимиты вендора знает он)."""

    def test_caps_receives_model_ref_and_cleans(self):
        seen = {}

        def validate_overrides(overrides, model_ref):
            seen["args"] = (dict(overrides), model_ref)
            return {"max_image_refs": 3}

        with _fake_caps(validate_overrides):
            out = validate_vstudio_overrides({"max_image_refs": 3}, "google/veo-3.1-fast")
        self.assertEqual(out, {"max_image_refs": 3})
        self.assertEqual(seen["args"], ({"max_image_refs": 3}, "google/veo-3.1-fast"))

    def test_caps_value_error_becomes_validation_error(self):
        def validate_overrides(overrides, model_ref):
            raise ValueError("max_image_refs больше лимита вендора (3)")

        with _fake_caps(validate_overrides), self.assertRaises(ValidationError) as ctx:
            validate_vstudio_overrides({"max_image_refs": 9}, "google/veo-3.1-fast")
        self.assertIn("лимита вендора", ctx.exception.messages[0])

    def test_caps_error_list_rejected(self):
        with _fake_caps(lambda overrides, model_ref: ["refs_verified: у семейства нет референсов"]):
            with self.assertRaises(ValidationError):
                validate_vstudio_overrides({"refs_verified": "2026-09-24"}, "google/veo-3.1-lite")
        with _fake_caps(lambda overrides, model_ref: []):
            self.assertEqual(validate_vstudio_overrides({"sort": 1}, "x"), {"sort": 1})

    def test_single_argument_caps_supported(self):
        with _fake_caps(lambda overrides: None):
            self.assertEqual(validate_vstudio_overrides({"sort": 1}, "x"), {"sort": 1})

    def test_caps_without_function_falls_back_to_whitelist(self):
        # BE-3 ещё пишет caps.py, а функции нет — админка не должна падать.
        with patch.dict(sys.modules, {"vstudio.caps": types.ModuleType("vstudio.caps")}):
            self.assertEqual(validate_vstudio_overrides({"sort": 2}, "x"), {"sort": 2})

    def test_whitelist_runs_before_caps(self):
        called = []
        with _fake_caps(lambda overrides, model_ref: called.append(1)):
            with self.assertRaises(ValidationError):
                validate_vstudio_overrides({"family": "seedance"}, "x")
        self.assertEqual(called, [])


class GPTModelsAdminFormTests(TestCase):
    def setUp(self):
        self.admin_user = get_user_model().objects.create_superuser(
            email="root@example.com", password="x-12345678")
        self.request = RequestFactory().get("/admin/ai/gptmodels/add/")
        self.request.user = self.admin_user
        self.model_admin = admin.site._registry[GPTModels]

    def _data(self, overrides_text, **extra):
        data = {
            "name": "Seedance 2.0", "openrouter_id": "bytedance/seedance-2.0",
            "description": "", "short_label": "", "is_active": "on", "sort_order": "100",
            "system_prompt": "", "temperature": "", "top_p": "", "max_tokens": "1000",
            "markup_coefficient": "10", "category": "video", "cartoon_stage": "",
            "vstudio_enabled": "on", "vstudio_overrides": overrides_text,
        }
        data.update(extra)
        return data

    def _form(self, data):
        form_cls = self.model_admin.get_form(self.request)
        return form_cls(data=data)

    def test_fields_present_in_admin(self):
        form_cls = self.model_admin.get_form(self.request)
        self.assertIn("vstudio_enabled", form_cls.base_fields)
        self.assertIn("vstudio_overrides", form_cls.base_fields)
        self.assertIn("vstudio_enabled", self.model_admin.list_filter)

    def test_valid_overrides_saved(self):
        with _NO_CAPS:
            form = self._form(self._data('{"badge": "Новинка", "refs": "off"}'))
            self.assertTrue(form.is_valid(), form.errors)
            obj = form.save()
        obj.refresh_from_db()
        self.assertTrue(obj.vstudio_enabled)
        self.assertEqual(obj.vstudio_overrides, {"badge": "Новинка", "refs": "off"})

    def test_empty_overrides_saved_as_empty_dict(self):
        with _NO_CAPS:
            form = self._form(self._data(""))
            self.assertTrue(form.is_valid(), form.errors)
            obj = form.save()
        obj.refresh_from_db()
        self.assertEqual(obj.vstudio_overrides, {})

    def test_unknown_key_error_under_field(self):
        with _NO_CAPS:
            form = self._form(self._data('{"frames": ["first_frame"]}'))
            self.assertFalse(form.is_valid())
        self.assertIn("vstudio_overrides", form.errors)
        self.assertIn("frames", " ".join(form.errors["vstudio_overrides"]))

    def test_caps_gets_openrouter_id_from_form(self):
        seen = []

        def validate_overrides(overrides, model_ref):
            seen.append(model_ref)
            raise ValueError("refs_verified: у google/veo-3.1-lite референсов нет")

        with _fake_caps(validate_overrides):
            form = self._form(self._data('{"refs_verified": "2026-09-24"}',
                                         openrouter_id="google/veo-3.1-lite"))
            self.assertFalse(form.is_valid())
        self.assertEqual(seen, ["google/veo-3.1-lite"])
        self.assertIn("vstudio_overrides", form.errors)

    def test_admin_pages_render(self):
        m = GPTModels.objects.create(name="Seedance", openrouter_id="bytedance/seedance-2.0",
                                     max_tokens=10, category="video",
                                     vstudio_overrides={"badge": "Новинка"})
        self.client.force_login(self.admin_user)
        add = self.client.get("/admin/ai/gptmodels/add/")
        self.assertEqual(add.status_code, 200)
        self.assertContains(add, 'name="vstudio_overrides"')
        change = self.client.get(f"/admin/ai/gptmodels/{m.pk}/change/")
        self.assertEqual(change.status_code, 200)
        self.assertContains(change, "Новинка")
        listing = self.client.get("/admin/ai/gptmodels/?vstudio_enabled__exact=0")
        self.assertEqual(listing.status_code, 200)

    def test_list_editable_ignores_stored_overrides(self):
        # Список моделей правит только тариф/флаги; даже «плохие» сохранённые
        # правки не должны ронять сохранение строки (раньше так падал бы
        # Model.clean() с ошибкой по полю, которого нет в форме).
        m = GPTModels.objects.create(name="Seedance", openrouter_id="bytedance/seedance-2.0",
                                     max_tokens=10, category="video",
                                     vstudio_overrides={"frames": ["first_frame"]})
        self.client.force_login(self.admin_user)
        res = self.client.post("/admin/ai/gptmodels/", {
            "form-TOTAL_FORMS": "1", "form-INITIAL_FORMS": "1",
            "form-MIN_NUM_FORMS": "0", "form-MAX_NUM_FORMS": "1000",
            "form-0-id": str(m.pk), "form-0-markup_coefficient": "12",
            "form-0-is_active": "on", "form-0-sort_order": "100",
            "_save": "Сохранить",
        })
        self.assertEqual(res.status_code, 302)
        m.refresh_from_db()
        self.assertEqual(m.markup_coefficient, Decimal("12"))

    def test_markup_decimal_kept(self):
        # Сторожим, что проверка правок не ломает сохранение остальных полей.
        with _NO_CAPS:
            form = self._form(self._data("{}"))
            self.assertTrue(form.is_valid(), form.errors)
            obj = form.save()
        self.assertEqual(obj.markup_coefficient, Decimal("10"))
