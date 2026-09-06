# -*- coding: utf-8 -*-
"""Распознавание голоса: цена по минутам, списание только за успех."""
import io
import shutil
import struct
import wave
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from plans.models import TokenTransaction

from . import stt

TEST_CACHES = {"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache",
                           "LOCATION": "stt-tests"}}
URL = "/api/ai/transcribe/"


def _user(balance=10):
    User = get_user_model()
    user = User.objects.create_user(email=f"stt{balance}@example.com", password="x")
    user.token_balance = balance
    user.save(update_fields=["token_balance"])
    return user


def _post(user, content=b"ogg-bytes", name="voice.ogg"):
    client = APIClient()
    client.force_authenticate(user)
    return client.post(URL, {"file": io.BytesIO(content) and _file(content, name), "lang": "ru"},
                       format="multipart")


def _file(content, name):
    from django.core.files.uploadedfile import SimpleUploadedFile

    return SimpleUploadedFile(name, content, content_type="audio/ogg")


@override_settings(CACHES=TEST_CACHES, STT_CREDITS_PER_MINUTE=2, STT_MAX_SECONDS=120)
class PriceTests(TestCase):
    def test_price_is_per_minute_rounded_up(self):
        with patch.object(stt, "credits_per_minute", return_value=2):
            self.assertEqual(stt.price_for(10), 1)
            self.assertEqual(stt.price_for(60), 2)
            self.assertEqual(stt.price_for(61), 3)
            self.assertEqual(stt.price_for(120), 4)

    def test_zero_rate_means_free(self):
        with patch.object(stt, "credits_per_minute", return_value=0):
            self.assertEqual(stt.price_for(90), 0)


@override_settings(CACHES=TEST_CACHES, STT_CREDITS_PER_MINUTE=2, STT_MAX_SECONDS=120)
class TranscribeApiTests(TestCase):
    def setUp(self):
        cache.clear()

    def test_requires_file(self):
        user = _user()
        client = APIClient()
        client.force_authenticate(user)
        self.assertEqual(client.post(URL, {}, format="multipart").status_code, 400)

    def test_requires_auth(self):
        response = APIClient().post(URL, {"file": _file(b"x", "a.ogg")}, format="multipart")
        self.assertEqual(response.status_code, 401)

    def test_insufficient_balance_before_model_call(self):
        user = _user(balance=0)
        with patch.object(stt, "convert_to_mp3", return_value=(b"mp3", 30.0, -20.0)), \
                patch.object(stt, "transcribe_audio") as model:
            response = _post(user)
        self.assertEqual(response.status_code, 402)
        self.assertEqual(response.data["error_code"], "insufficient_balance")
        model.assert_not_called()

    def test_success_charges_once(self):
        user = _user(balance=10)
        with patch.object(stt, "convert_to_mp3", return_value=(b"mp3", 30.0, -20.0)), \
                patch.object(stt, "transcribe_audio", return_value="привет мир"):
            response = _post(user)
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["text"], "привет мир")
        self.assertEqual(response.data["tokens_charged"], 1)
        self.assertEqual(response.data["balance_tokens"], 9)
        tx = TokenTransaction.objects.get(user=user, reason="stt")
        self.assertEqual(tx.delta, -1)
        self.assertEqual(tx.meta["seconds"], 30.0)

    def test_failure_costs_nothing(self):
        user = _user(balance=10)
        with patch.object(stt, "convert_to_mp3", return_value=(b"mp3", 30.0, -20.0)), \
                patch.object(stt, "transcribe_audio", side_effect=stt.SttError("boom")):
            response = _post(user)
        self.assertEqual(response.status_code, 502)
        user.refresh_from_db()
        self.assertEqual(user.token_balance, 10)
        self.assertFalse(TokenTransaction.objects.filter(user=user).exists())

    def test_empty_speech_is_free(self):
        user = _user(balance=10)
        with patch.object(stt, "convert_to_mp3", return_value=(b"mp3", 5.0, -20.0)), \
                patch.object(stt, "transcribe_audio", return_value=""):
            response = _post(user)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["tokens_charged"], 0)

    def test_silence_is_free_and_skips_model(self):
        """2 секунды тишины на проде превратились в выдуманную фразу за 1 кредит."""
        user = _user(balance=10)
        with patch.object(stt, "convert_to_mp3", return_value=(b"mp3", 2.0, -91.0)), \
                patch.object(stt, "transcribe_audio") as model:
            response = _post(user)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["text"], "")
        self.assertEqual(response.data["tokens_charged"], 0)
        self.assertTrue(response.data["silent"])
        model.assert_not_called()

    def test_is_silent_rules(self):
        self.assertTrue(stt.is_silent(-60.0, 3.0))
        self.assertFalse(stt.is_silent(-20.0, 3.0))
        self.assertTrue(stt.is_silent(-20.0, 0.2))
        self.assertFalse(stt.is_silent(None, 3.0))

    def test_too_long_rejected(self):
        user = _user(balance=10)
        with patch.object(stt, "convert_to_mp3", return_value=(b"mp3", 500.0, -20.0)):
            response = _post(user)
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data["detail"], "too_long")

    def test_bad_audio(self):
        user = _user(balance=10)
        with patch.object(stt, "convert_to_mp3", side_effect=stt.SttError("no")):
            response = _post(user)
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data["detail"], "bad_audio")

    def test_too_big_rejected(self):
        user = _user(balance=10)
        with patch.object(stt, "max_bytes", return_value=10):
            response = _post(user, content=b"x" * 100)
        self.assertEqual(response.status_code, 413)


class FfmpegTests(TestCase):
    """Настоящая конвертация — только там, где стоит ffmpeg (в образе он есть)."""

    def test_wav_to_mp3_reports_duration(self):
        if not shutil.which("ffmpeg"):
            self.skipTest("ffmpeg не установлен")
        buffer = io.BytesIO()
        with wave.open(buffer, "wb") as wav:
            wav.setnchannels(1)
            wav.setsampwidth(2)
            wav.setframerate(8000)
            wav.writeframes(b"".join(struct.pack("<h", 0) for _ in range(8000 * 2)))
        mp3, seconds, volume = stt.convert_to_mp3(buffer.getvalue())
        self.assertTrue(mp3.startswith(b"ID3") or mp3[:2] == b"\xff\xfb" or len(mp3) > 100)
        self.assertAlmostEqual(seconds, 2.0, delta=0.3)
        # Тишина: ffmpeg показывает очень низкую среднюю громкость.
        self.assertIsNotNone(volume)
        self.assertTrue(stt.is_silent(volume, seconds))
