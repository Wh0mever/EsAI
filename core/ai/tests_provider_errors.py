# -*- coding: utf-8 -*-
"""Отказ провайдера объясняется человеку, а не «попробуйте ещё раз».

Случай 21.09.2026: шесть попыток подряд с фото реального человека, шесть
одинаковых отказов Seedance и шесть раз «попробуйте ещё раз» на экране.
"""
from django.test import SimpleTestCase

from .provider_errors import explain_image_error, explain_video_error

SEEDANCE_REAL_PERSON = (
    'video submit http 400: {"error":{"message":"HTTP 400: {\\"error\\":{\\"code\\":'
    '\\"InputImageSensitiveContentDetected.PrivacyInformation\\",\\"message\\":\\"The request '
    'failed because the input image \'content[1]\' may contain real person. Request id: 0217\\"}}"}}'
)
SORA_NO_FRAMES = ('video submit http 400: {"error":{"message":"the provider integration for model '
                  '\\"openai/sora-2-pro\\" does not support first_frame frame_images","code":400}}')
OUT_OF_CREDITS = ('video submit http 402: {"error":{"message":"Insufficient credits. Add more using '
                  'https://openrouter.ai/settings/credits","code":402}}')


class ProviderErrorTests(SimpleTestCase):
    def test_real_person_photo_is_explained(self):
        shown, code = explain_video_error(SEEDANCE_REAL_PERSON)
        self.assertEqual(code, "image_real_person")
        self.assertIn("реальных людей", shown)
        self.assertIn("рисунок", shown)

    def test_model_without_image_to_video(self):
        shown, code = explain_video_error(SORA_NO_FRAMES)
        self.assertEqual(code, "no_image_to_video")
        self.assertIn("не умеет делать видео из картинки", shown)

    def test_provider_out_of_credits_is_our_problem_not_the_users(self):
        shown, code = explain_video_error(OUT_OF_CREDITS)
        self.assertEqual(code, "provider_out_of_credits")
        self.assertIn("Кредиты не списаны", shown)
        self.assertNotIn("openrouter", shown.lower())

    def test_unknown_error_keeps_the_generic_text(self):
        shown, code = explain_video_error("video submit http 400: something odd")
        self.assertEqual(code, "provider_error")
        self.assertEqual(shown, "Не удалось запустить генерацию видео. Попробуйте ещё раз.")

    def test_image_path_has_its_own_wording(self):
        shown, code = explain_image_error(SEEDANCE_REAL_PERSON)
        self.assertEqual(code, "image_real_person")
        shown, code = explain_image_error("flux images http 500: boom")
        self.assertEqual(code, "provider_error")
        self.assertIn("изображение", shown)
