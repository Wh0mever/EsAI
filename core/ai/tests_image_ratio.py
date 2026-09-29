# -*- coding: utf-8 -*-
"""Картинки: пропорция доходит до модели, кадр соответствует запросу, запрос без контекста.

Поводом стал скриншот клиента: в боте выбрали 16:9, а пришёл почти квадрат, и
вместо ≈6 кредитов с карточки списалось 12.
"""
import base64
from io import BytesIO
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from PIL import Image

from . import handlers
from .models import AiChatMessage, AiChatSession

TEST_CACHES = {"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache",
                           "LOCATION": "image-ratio-tests"}}


def png(width, height, fmt="PNG") -> bytes:
    out = BytesIO()
    Image.new("RGB", (width, height), (200, 120, 40)).save(out, format=fmt)
    return out.getvalue()


def size_of(raw: bytes) -> tuple[int, int]:
    with Image.open(BytesIO(raw)) as img:
        return img.size


class ConformRatioTests(TestCase):
    def test_square_becomes_widescreen(self):
        """Ровно то, что случилось на скриншоте: просили 16:9, пришёл квадрат."""
        raw, cropped = handlers._conform_ratio(png(1024, 1024), "16:9")
        self.assertTrue(cropped)
        w, h = size_of(raw)
        self.assertAlmostEqual(w / h, 16 / 9, delta=0.02)
        self.assertEqual(w, 1024)  # ширину не теряем — режем лишнюю высоту

    def test_wide_becomes_portrait(self):
        raw, cropped = handlers._conform_ratio(png(1824, 1024), "9:16")
        self.assertTrue(cropped)
        w, h = size_of(raw)
        self.assertAlmostEqual(w / h, 9 / 16, delta=0.02)
        self.assertEqual(h, 1024)

    def test_within_tolerance_untouched(self):
        """Перекодирование зря ухудшило бы картинку: близкое не трогаем."""
        source = png(1344, 768)  # ровно 16:9 c округлением модели
        raw, cropped = handlers._conform_ratio(source, "16:9")
        self.assertFalse(cropped)
        self.assertEqual(raw, source)

    def test_no_ratio_means_no_change(self):
        source = png(1024, 1024)
        for ratio in (None, "", "abc", "16"):
            raw, cropped = handlers._conform_ratio(source, ratio)
            self.assertFalse(cropped)
            self.assertEqual(raw, source)

    def test_garbage_bytes_do_not_crash(self):
        raw, cropped = handlers._conform_ratio(b"not an image", "16:9")
        self.assertFalse(cropped)
        self.assertEqual(raw, b"not an image")

    def test_jpeg_stays_jpeg(self):
        raw, cropped = handlers._conform_ratio(png(1000, 1000, "JPEG"), "16:9")
        self.assertTrue(cropped)
        with Image.open(BytesIO(raw)) as img:
            self.assertEqual(img.format, "JPEG")

    def test_all_button_ratios(self):
        """Каждая пропорция из кнопок бота получается на выходе."""
        from .aspect import IMAGE_ASPECT_RATIOS

        for ratio in IMAGE_ASPECT_RATIOS:
            a, b = (int(x) for x in ratio.split(":"))
            raw, _ = handlers._conform_ratio(png(1024, 1024), ratio)
            w, h = size_of(raw)
            self.assertAlmostEqual(w / h, a / b, delta=0.03, msg=ratio)


@override_settings(CACHES=TEST_CACHES)
class SaveImagesTests(TestCase):
    def _data_url(self, raw: bytes) -> dict:
        return {"image_url": {"url": "data:image/png;base64," + base64.b64encode(raw).decode()}}

    def test_saved_file_has_requested_ratio(self):
        with patch("django.core.files.storage.default_storage.save",
                   side_effect=lambda name, content: (setattr(self, "saved", content.read()), name)[1]), \
                patch("django.core.files.storage.default_storage.url", side_effect=lambda p: "/media/" + p):
            atts = handlers._save_generated_images([self._data_url(png(1024, 1024))], "16:9")
        self.assertEqual(len(atts), 1)
        w, h = size_of(self.saved)
        self.assertAlmostEqual(w / h, 16 / 9, delta=0.02)

    def test_without_ratio_file_is_as_is(self):
        source = png(1024, 1024)
        with patch("django.core.files.storage.default_storage.save",
                   side_effect=lambda name, content: (setattr(self, "saved", content.read()), name)[1]), \
                patch("django.core.files.storage.default_storage.url", side_effect=lambda p: "/media/" + p):
            handlers._save_generated_images([self._data_url(source)])
        self.assertEqual(self.saved, source)


class FakeStream:
    """Поток из одного чанка: хватает, чтобы дойти до конца генератора."""

    def __iter__(self):
        return iter(())


class FakeClient:
    def __init__(self):
        self.calls = []
        self.chat = self
        self.completions = self

    def create(self, **params):
        self.calls.append(params)
        return FakeStream()


class ImageConfigTests(TestCase):
    def _params(self, model, config):
        client = FakeClient()
        gen = handlers._stream_chat_completion(
            client=client, model_name=model, messages=[{"role": "user", "content": "x"}],
            max_tokens_limit=None, allow_temperature=False, requested_temperature=None,
            image_config=config)
        list(gen)
        return client.calls[0]

    def test_aspect_goes_as_model_parameter(self):
        params = self._params("google/gemini-2.5-flash-image", {"aspect_ratio": "16:9"})
        self.assertEqual(params["extra_body"]["image_config"], {"aspect_ratio": "16:9"})
        self.assertEqual(params["extra_body"]["modalities"], ["image", "text"])

    def test_no_config_no_key(self):
        params = self._params("google/gemini-2.5-flash-image", None)
        self.assertNotIn("image_config", params["extra_body"])

    def test_text_model_never_gets_image_config(self):
        """Текстовой модели картиночные параметры не нужны и могут её сломать."""
        params = self._params("google/gemini-2.5-flash", {"aspect_ratio": "16:9"})
        self.assertNotIn("extra_body", params)


class OnlyLastTests(TestCase):
    def setUp(self):
        user = get_user_model().objects.create_user(email="ctx@example.com", password="x")
        self.session = AiChatSession.objects.create(user=user, title="t",
                                                    context_summary="старое резюме")
        for i in range(4):
            AiChatMessage.objects.create(session=self.session, role="user", content=f"вопрос {i}")
            AiChatMessage.objects.create(session=self.session, role="assistant", content=f"ответ {i}")
        AiChatMessage.objects.create(session=self.session, role="user", content="Самарканд")

    def test_default_keeps_whole_dialog(self):
        messages = handlers._build_openai_messages(self.session, "Самарканд", "sys")
        self.assertGreater(len(messages), 5)

    def test_only_last_is_system_plus_one_message(self):
        messages = handlers._build_openai_messages(self.session, "Самарканд", "sys", only_last=True)
        self.assertEqual([m["role"] for m in messages], ["system", "user"])
        self.assertNotIn("старое резюме", str(messages))
        self.assertIn("Самарканд", str(messages[-1]))
