# -*- coding: utf-8 -*-
"""Заставка EsAI в конце мультфильма выключена по умолчанию (просьба клиента 25.10.2026)."""
from django.test import TestCase, override_settings

from adminapi.runtime import set_runtime, delete_runtime
from cartoon import services

TEST_CACHES = {"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache", "LOCATION": "outro"}}


@override_settings(CACHES=TEST_CACHES)
class OutroToggleTests(TestCase):
    def tearDown(self):
        delete_runtime("cartoon_outro")

    def test_off_by_default(self):
        delete_runtime("cartoon_outro")
        self.assertFalse(services.outro_enabled())

    def test_on_when_switched_on(self):
        set_runtime("cartoon_outro", "on")
        self.assertTrue(services.outro_enabled())

    def test_off_value(self):
        set_runtime("cartoon_outro", "off")
        self.assertFalse(services.outro_enabled())
