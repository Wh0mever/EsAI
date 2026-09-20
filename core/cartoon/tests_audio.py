# -*- coding: utf-8 -*-
"""Звук студии: цены, списание только после удачи, сведение настоящим ffmpeg."""
import shutil
import subprocess
import tempfile
from decimal import Decimal
from pathlib import Path
from unittest import skipUnless
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.test import TestCase, override_settings
from rest_framework.test import APIRequestFactory, force_authenticate

from ai.models import GPTModels
from cartoon import audio
from cartoon.models import (CartoonAudioTrack, CartoonCharacter, CartoonPreset, CartoonProject,
                            CartoonScene)
from cartoon.views_audio import SceneMixView, SceneMusicView, SceneSfxView, SceneVoiceView
from plans.models import TokenTransaction

CACHES = {"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache",
                      "LOCATION": "studio-audio-tests"}}
HAS_FFMPEG = bool(shutil.which("ffmpeg") and shutil.which("ffprobe"))


def _silent_mp3() -> bytes:
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "s.mp3"
        subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i",
                        "sine=frequency=440:duration=1", str(out)], check=True)
        return out.read_bytes()


@override_settings(CACHES=CACHES, ELEVENLABS_API_KEY="test-key", STUDIO_VOICE_CREDITS_PER_1K=20,
                   STUDIO_VOICE_MIN_CREDITS=5, STUDIO_MUSIC_CREDITS_PER_MIN=30, STUDIO_SFX_CREDITS=10)
class AudioPriceTests(TestCase):
    def test_prices_follow_client_rules(self):
        self.assertEqual(audio.voice_price("а" * 100), 5)       # минимум
        self.assertEqual(audio.voice_price("а" * 1000), 20)
        self.assertEqual(audio.voice_price("а" * 1001), 21)     # вверх до целого
        self.assertEqual(audio.music_price(30), 15)
        self.assertEqual(audio.music_price(120), 60)
        self.assertEqual(audio.sfx_price(), 10)


@override_settings(CACHES=CACHES, ELEVENLABS_API_KEY="test-key")
@skipUnless(HAS_FFMPEG, "нужен ffmpeg")
class AudioFlowTests(TestCase):
    def setUp(self):
        model = GPTModels.objects.create(name="m", openrouter_id="test/m", max_tokens=10,
                                         markup_coefficient=Decimal("4"))
        self.preset = CartoonPreset.objects.create(slug="a-scene", title="Сцена", is_active=True,
                                                   scene_prompt="x", image_model=model, video_model=model)
        hero = CartoonCharacter.objects.create(name="Кот", image="cartoon/characters/c.png", is_public=True)
        self.user = get_user_model().objects.create_user(email="a@example.com", password="x-12345678")
        self.user.token_balance = 100
        self.user.save(update_fields=["token_balance"])
        project = CartoonProject.objects.create(user=self.user, character=hero)
        self.scene = CartoonScene.objects.create(project=project, preset=self.preset, order=0)
        self.mp3 = _silent_mp3()

    def _post(self, view, body):
        request = APIRequestFactory().post("/x/", body, format="json")
        force_authenticate(request, user=self.user)
        return view.as_view()(request, pk=self.scene.pk)

    def _balance(self):
        self.user.refresh_from_db()
        return self.user.token_balance

    def test_voice_charged_after_success(self):
        with patch("cartoon.audio.tts", return_value=self.mp3) as tts, \
             patch("cartoon.audio.list_voices", return_value=[{"id": "v1", "name": "Аня"}]):
            response = self._post(SceneVoiceView, {"text": "Привет, я кот!", "voice_id": "v1", "start_sec": 1.5})
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(tts.call_count, 1)
        self.assertEqual(self._balance(), 95)
        self.assertEqual(response.data["voice_name"], "Аня")
        self.assertEqual(response.data["start_sec"], 1.5)
        self.assertGreater(response.data["duration"], 0.5)
        self.assertTrue(TokenTransaction.objects.filter(reason="cartoon_voice", delta=-5).exists())

    def test_provider_failure_costs_nothing(self):
        with patch("cartoon.audio.tts", side_effect=audio.AudioProviderError("http 500")), \
             patch("cartoon.audio.list_voices", return_value=[]):
            response = self._post(SceneVoiceView, {"text": "Привет", "voice_id": "v1"})
        self.assertEqual(response.status_code, 502)
        self.assertEqual(self._balance(), 100)
        self.assertFalse(CartoonAudioTrack.objects.exists())

    def test_not_enough_credits_before_generation(self):
        self.user.token_balance = 3
        self.user.save(update_fields=["token_balance"])
        with patch("cartoon.audio.music") as music:
            response = self._post(SceneMusicView, {"prompt": "весёлая мелодия", "seconds": 30})
        self.assertEqual(response.status_code, 402)
        self.assertEqual(response.data["required"], 15)
        self.assertEqual(music.call_count, 0)

    @override_settings(ELEVENLABS_API_KEY="")
    def test_not_configured(self):
        with patch("cartoon.audio._runtime", side_effect=lambda k, d: d):
            response = self._post(SceneSfxView, {"prompt": "стук в дверь"})
        self.assertEqual(response.status_code, 503)

    def test_mix_puts_tracks_onto_scene_video(self):
        with tempfile.TemporaryDirectory() as tmp:
            video = Path(tmp) / "v.mp4"
            subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i",
                            "testsrc=size=160x90:rate=10:duration=2", "-f", "lavfi", "-i",
                            "sine=frequency=220:duration=2", "-shortest", "-c:v", "libx264",
                            "-c:a", "aac", str(video)], check=True)
            self.scene.video = default_storage.save("cartoon/scenes/test-mix.mp4", ContentFile(video.read_bytes()))
        self.scene.status = CartoonScene.STATUS_READY
        self.scene.save()
        path, duration = audio.save_audio(self.mp3)
        CartoonAudioTrack.objects.create(scene=self.scene, kind="voice", file=path, duration=duration,
                                         start_sec=0.5, volume=1.2)
        response = self._post(SceneMixView, {})
        self.assertEqual(response.status_code, 200, response.data)
        self.scene.refresh_from_db()
        self.assertTrue(self.scene.mixed_video)
        with tempfile.TemporaryDirectory() as tmp:
            local = Path(tmp) / "m.mp4"
            with default_storage.open(self.scene.mixed_video, "rb") as fh:
                local.write_bytes(fh.read())
            info = audio.probe(local)
        self.assertTrue(info["audio"])
        self.assertAlmostEqual(info["duration"], 2.0, delta=0.3)


@override_settings(CACHES=CACHES)
@skipUnless(HAS_FFMPEG, "нужен ffmpeg")
class MovieSoundTests(TestCase):
    """Одна неозвученная сцена не должна делать немым весь мультфильм."""

    def _clip(self, tmp: Path, name: str, sound: bool) -> bytes:
        path = tmp / name
        cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i",
               "testsrc=size=160x90:rate=10:duration=1"]
        if sound:
            cmd += ["-f", "lavfi", "-i", "sine=frequency=330:duration=1", "-c:a", "aac"]
        cmd += ["-c:v", "libx264", "-pix_fmt", "yuv420p", "-shortest", str(path)]
        subprocess.run(cmd, check=True)
        return path.read_bytes()

    def test_silent_scene_gets_silence_and_movie_keeps_sound(self):
        from ai.video_edit import concat_videos

        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            voiced = self._clip(tmp, "a.mp4", sound=True)
            silent = self._clip(tmp, "b.mp4", sound=False)
            self.assertTrue(audio.has_audio(voiced))
            self.assertFalse(audio.has_audio(silent))

            parts = audio.align_audio([voiced, silent])
            self.assertTrue(all(audio.has_audio(p) for p in parts))

            joined = concat_videos(parts)
            self.assertTrue(joined)
            out = tmp / "joined.mp4"
            out.write_bytes(joined)
            self.assertTrue(audio.probe(out)["audio"])

    def test_all_silent_parts_are_left_alone(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            parts = [self._clip(tmp, "a.mp4", sound=False), self._clip(tmp, "b.mp4", sound=False)]
            self.assertEqual(audio.align_audio(parts), parts)
