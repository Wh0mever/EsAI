# -*- coding: utf-8 -*-
"""seed_presets не откатывает библиотеку, которую владелец ведёт сам в панели."""
from io import StringIO
from unittest.mock import patch

from django.contrib.admin.models import CHANGE, LogEntry
from django.contrib.auth import get_user_model
from django.contrib.contenttypes.models import ContentType
from django.core.management import call_command
from django.test import TestCase, override_settings

from ai.models import GPTModels
from cartoon import panel
from cartoon.models import CartoonCategory, CartoonPreset

CACHES = {"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache",
                      "LOCATION": "seed-guard-tests"}}
COMMAND = "cartoon.management.commands.seed_presets"
CODE_CATEGORIES = [("holidays", "Праздники", "🎉", 10), ("love", "Любовь", "❤️", 20)]
CODE_PRESETS = [
    ("g-one", "Один", "Первая", "the character one", "move one", 5, "holidays"),
    ("g-two", "Два", "Вторая", "the character two", "move two", 5, "holidays"),
    ("g-three", "Три", "Третья", "the character three", "move three", 5, "love"),
    ("g-four", "Четыре", "Четвёртая", "the character four", "move four", 5, "love"),
]


@override_settings(CACHES=CACHES)
class SeedGuardTests(TestCase):
    def setUp(self):
        self.staff = get_user_model().objects.create_user(
            email="admin@example.com", password="x-12345678", is_staff=True)
        GPTModels.objects.create(name="Nano Banana", openrouter_id="google/gemini-2.5-flash-image",
                                 max_tokens=100, markup_coefficient=4, category="image")
        GPTModels.objects.create(name="Seedance 2.0", openrouter_id="bytedance/seedance-2.0",
                                 max_tokens=100, markup_coefficient=32, category="video")
        # Короткая библиотека вместо полутора сотен сцен из кода.
        for name, value in (("CATEGORIES", CODE_CATEGORIES), ("PRESETS", CODE_PRESETS),
                            ("PRESET_TRANSLATIONS", {}), ("CATEGORY_TRANSLATIONS", {}),
                            ("EDITOR_PICKS", {"g-two"})):
            p = patch(f"{COMMAND}.{name}", value)
            p.start()
            self.addCleanup(p.stop)

    def seed(self, **opts):
        call_command("seed_presets", stdout=StringIO(), **opts)

    def preset(self, slug):
        return CartoonPreset.objects.filter(slug=slug).first()

    def test_owner_edits_survive_reruns_even_with_force(self):
        legacy = CartoonCategory.objects.create(title="Старое", slug="old-section")
        self.seed()
        self.assertEqual(CartoonPreset.objects.count(), 4)
        legacy.refresh_from_db()
        self.assertFalse(legacy.is_active)

        holidays = CartoonCategory.objects.get(slug="holidays")
        panel.edit_section(holidays, {"title": "Мои праздники", "is_active": False}, actor=self.staff)
        mine = panel.create_section({"title": "Новый год"}, actor=self.staff)
        panel.edit_scene(self.preset("g-one"), {"title": "Мой заголовок", "audience": "kids",
                                                "is_pick": True}, actor=self.staff)
        panel.delete_scene(self.preset("g-three"), actor=self.staff)
        # Правка в Django-админке тоже считается правкой человека.
        two = self.preset("g-two")
        CartoonPreset.objects.filter(pk=two.pk).update(scene_prompt="hand-tuned prompt")
        LogEntry.objects.create(user=self.staff, content_type=ContentType.objects.get_for_model(two),
                                object_id=str(two.pk), object_repr=two.title, action_flag=CHANGE)
        # Никем не тронутая сцена из кода по-прежнему следует коду.
        CartoonPreset.objects.filter(slug="g-four").update(scene_prompt="drifted", title="Дрейф")

        self.seed(force=True)

        holidays.refresh_from_db()
        self.assertEqual((holidays.title, holidays.is_active), ("Мои праздники", False))
        mine.refresh_from_db()
        self.assertTrue(mine.is_active)
        one = self.preset("g-one")
        self.assertEqual((one.title, one.audience, one.is_pick), ("Мой заголовок", "kids", True))
        self.assertEqual(self.preset("g-two").scene_prompt, "hand-tuned prompt")
        self.assertIsNone(self.preset("g-three"))
        four = self.preset("g-four")
        self.assertEqual((four.scene_prompt, four.title), ("the character four", "Четыре"))

        self.seed()
        self.assertIsNone(self.preset("g-three"))
        self.assertEqual(self.preset("g-one").title, "Мой заголовок")
        mine.refresh_from_db()
        self.assertTrue(mine.is_active)
