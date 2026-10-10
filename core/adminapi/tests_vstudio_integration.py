# -*- coding: utf-8 -*-
"""Интеграция видеостудии в админку: режим студии из настроек и правки модели."""
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from rest_framework.test import APIRequestFactory, force_authenticate

from adminapi.serializers import GPTModelAdminSerializer
from adminapi.views import SettingsView
from ai.models import GPTModels

CACHES = {"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache",
                      "LOCATION": "vstudio-integration-adminapi"}}


@override_settings(CACHES=CACHES, VSTUDIO_MODE="staff")
class VstudioModeSettingTests(TestCase):
    def setUp(self):
        from django.core.cache import cache

        cache.clear()
        self.staff = get_user_model().objects.create_user(
            email="admin@example.com", password="x-12345678", is_staff=True)

    def _call(self, method, body=None):
        factory = APIRequestFactory()
        request = (factory.patch("/s/", body, format="json") if method == "PATCH"
                   else factory.get("/s/"))
        force_authenticate(request, user=self.staff)
        return SettingsView.as_view()(request)

    def test_snapshot_shows_effective_and_env_mode(self):
        data = self._call("GET").data
        self.assertEqual(data["vstudio_mode"], "staff")
        self.assertEqual(data["vstudio_mode_env"], "staff")
        self.assertEqual(data["vstudio_mode_override"], "")

    def test_override_changes_studio_mode_and_empty_value_returns_env(self):
        from vstudio.views import studio_mode

        res = self._call("PATCH", {"vstudio_mode": "on"})
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.data["vstudio_mode"], "on")
        self.assertEqual(res.data["vstudio_mode_override"], "on")
        self.assertEqual(studio_mode(), "on")

        res = self._call("PATCH", {"vstudio_mode": ""})
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.data["vstudio_mode_override"], "")
        self.assertEqual(studio_mode(), "staff")

    def test_unknown_mode_is_refused(self):
        res = self._call("PATCH", {"vstudio_mode": "everyone"})
        self.assertEqual(res.status_code, 400)
        self.assertEqual(self._call("GET").data["vstudio_mode_override"], "")

    def test_carousel_size_is_not_a_general_setting(self):
        # Размер карусели меняет панель витрины (PATCH vstudio/showcase/) — там
        # проверка границ и журнал. Общий PATCH настроек про ключ не знает:
        # иначе через него прошли бы и «2», и «500».
        from adminapi.models import AppSetting
        from adminapi.runtime import KEYS
        from vstudio import showcase

        self.assertIn(showcase.REEL_SIZE_KEY, KEYS)
        res = self._call("PATCH", {showcase.REEL_SIZE_KEY: 2, "reel_size": 500})
        self.assertEqual(res.status_code, 200)
        self.assertFalse(AppSetting.objects.filter(key=showcase.REEL_SIZE_KEY).exists())
        self.assertEqual(showcase.reel_size(), showcase.REEL_SIZE_DEFAULT)
        snapshot = self._call("GET").data
        self.assertNotIn(showcase.REEL_SIZE_KEY, snapshot)
        self.assertNotIn("reel_size", snapshot)


class GPTModelAdminSerializerVstudioTests(TestCase):
    def setUp(self):
        self.model = GPTModels.objects.create(
            name="Seedance 2.0", openrouter_id="bytedance/seedance-2.0", max_tokens=100,
            markup_coefficient=Decimal("32"), category="video")

    def test_fields_exposed(self):
        data = GPTModelAdminSerializer(self.model).data
        self.assertIn("vstudio_enabled", data)
        self.assertEqual(data["vstudio_overrides"], {})

    def test_overrides_validated_like_django_admin(self):
        ok = GPTModelAdminSerializer(self.model, data={"vstudio_enabled": True,
                                                       "vstudio_overrides": {"badge": "Новинка"}},
                                     partial=True)
        self.assertTrue(ok.is_valid(), ok.errors)
        ok.save()
        self.model.refresh_from_db()
        self.assertTrue(self.model.vstudio_enabled)
        self.assertEqual(self.model.vstudio_overrides, {"badge": "Новинка"})

        bad = GPTModelAdminSerializer(self.model, data={"vstudio_overrides": {"price": 1}},
                                      partial=True)
        self.assertFalse(bad.is_valid())
        self.assertIn("vstudio_overrides", bad.errors)


@override_settings(CACHES=CACHES)
class TransferMessageWithReserveTests(TestCase):
    """Перевод: резерв идущей генерации тоже уменьшает «можно перевести» — текст говорит об этом."""

    def setUp(self):
        from rest_framework.test import APIClient

        User = get_user_model()
        self.sender = User.objects.create_user(email="s@example.com", password="x")
        User.objects.create_user(email="r@example.com", password="x")
        self.client = APIClient()
        self.client.force_authenticate(self.sender)

    def _send(self, amount):
        return self.client.post("/api/users/transfer/", {"recipient": "r@example.com", "amount": amount},
                                format="json")

    def test_reserve_named_in_refusal(self):
        from plans.wallet import credit_tokens, transferable_tokens
        from vstudio.tests import factories as f

        credit_tokens(self.sender, 100, "purchase", meta={"order_id": "vs-o1"})
        shot = f.make_shot(self.sender)
        f.make_take(shot, status="running", credits=60)
        self.assertEqual(transferable_tokens(self.sender), 40)
        r = self._send(80)
        self.assertEqual(r.status_code, 400)
        self.assertEqual(r.data["transferable"], 40)
        self.assertIn("ждёт оплаты за генерации", r.data["message"])

    def test_without_reserve_old_text_kept(self):
        from plans.wallet import credit_tokens

        credit_tokens(self.sender, 30, "daily_bonus")
        credit_tokens(self.sender, 10, "purchase", meta={"order_id": "vs-o2"})
        r = self._send(20)
        self.assertEqual(r.status_code, 400)
        self.assertIn("подарочные", r.data["message"])
        self.assertNotIn("ждёт оплаты", r.data["message"])
