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

    def test_music_timeout_is_default_unless_asked(self):
        # Склейка ждёт пятиминутную музыку дольше; мультстудия — прежние 180 с.
        answer = type("R", (), {"status_code": 200, "content": b"mp3", "text": ""})()
        with patch("cartoon.audio.requests.post", return_value=answer) as post:
            audio.music("пианино", 30)
            audio.music("пианино", 300, timeout=(10, 540))
        self.assertEqual([c.kwargs["timeout"] for c in post.call_args_list], [audio.TIMEOUT, (10, 540)])
        self.assertEqual(post.call_args.kwargs["json"]["music_length_ms"], 300000)


class SaveAudioCommandTests(TestCase):
    """Пересборка чужого файла ограничена потолком длины: заголовку файла не верим."""

    def _convert(self, duration=6.0, **kw):
        calls = []

        def run(cmd, timeout=180):
            calls.append(cmd)
            Path(cmd[-1]).write_bytes(b"ID3OUT")
            return True

        with tempfile.TemporaryDirectory() as media, override_settings(MEDIA_ROOT=media), \
                patch("cartoon.audio._run", side_effect=run), \
                patch("cartoon.audio.probe", return_value={"duration": duration, "audio": True}):
            try:
                result = audio.save_audio(b"RIFF", ".wav", folder="t", **kw)
            except audio.AudioTooLong:
                result = None
        return calls[0], result

    def test_ceiling_caps_the_conversion_itself(self):
        cmd, result = self._convert(max_seconds=301.0)
        i = cmd.index("-i")
        self.assertTrue(cmd[i + 1].startswith("file:") and cmd[i + 1].endswith("in.wav"))
        # -t — после входа: ffmpeg перестаёт читать на 302-й секунде, что бы ни писал заголовок.
        self.assertEqual(cmd[i + 2:i + 4], ["-t", "302"])
        # Часы потолка — по счёту сэмплов: метки времени файла могут врать так же, как заголовок.
        self.assertEqual(cmd[i + 4:i + 6], ["-af", "asetpts=N/SR/TB"])
        self.assertEqual(cmd.count("-af") + cmd.count("-filter:a") + cmd.count("-filter_complex"), 1)
        # Байтовый потолок: счётчик asetpts обнуляется, когда граф собирается заново
        # (смена частоты посреди файла), а размер готового mp3 — нет.
        self.assertEqual(cmd[i + 6:i + 8], ["-fs", str(audio.output_cap(301.0))])
        # Теги и главы файла в mp3 не переносятся: иначе их байты съедали бы -fs, и
        # честный трек у предела с большими тегами молча обрезался бы.
        self.assertEqual(cmd[i + 8:i + 12], ["-map_metadata", "-1", "-map_chapters", "-1"])
        # Это опции выхода: после входа и до имени готового файла.
        self.assertTrue(cmd[-1].endswith("out.mp3") and cmd.index("-map_chapters") < len(cmd) - 1)
        self.assertEqual(cmd[cmd.index("-protocol_whitelist") + 1], "file")
        self.assertIn("-nostdin", cmd)
        self.assertEqual(result[1], 6.0)

    def test_lying_header_is_refused_at_bounded_cost(self):
        # Файл «на 10 секунд» оказался часами: ffmpeg остановился на 302 с, и потолок отказал.
        _cmd, result = self._convert(duration=302.0, max_seconds=301.0)
        self.assertIsNone(result)

    def test_input_options_go_before_the_input(self):
        cmd, _ = self._convert(max_seconds=300, input_options=["-codec_whitelist", "pcm_s16le", "-f", "wav"])
        i = cmd.index("-i")
        self.assertEqual(cmd[i - 6:i], ["-protocol_whitelist", "file", "-codec_whitelist", "pcm_s16le", "-f", "wav"])
        self.assertEqual(cmd[i + 2:i + 12], ["-t", "301", "-af", "asetpts=N/SR/TB",
                                             "-fs", str(audio.output_cap(300)),
                                             "-map_metadata", "-1", "-map_chapters", "-1"])

    def test_byte_cap_leaves_room_for_an_honest_track(self):
        # 160 кбит/с — 20 000 Б/с: честные max+1 секунд с заголовками влезают с запасом,
        # а дальше — не больше пары секунд и тегов сверх потолка.
        for top in (300, 301.0):
            cap = audio.output_cap(top)
            self.assertGreater(cap, (top + 1) * 20_000 + 64 * 1024)
            self.assertLess(cap, (top + 20) * 20_000)
        self.assertEqual(audio.output_cap(301.0), 303 * 20_000 + 256 * 1024)

    def test_without_ceiling_nothing_is_cut(self):
        # Голос и музыка провайдера (мультстудия) — как раньше: без -t и без чужих опций.
        cmd, _ = self._convert()
        self.assertNotIn("-t", cmd)
        self.assertNotIn("-af", cmd)
        self.assertNotIn("-fs", cmd)
        self.assertNotIn("-map_metadata", cmd)
        self.assertNotIn("-map_chapters", cmd)
        self.assertFalse(any("asetpts" in arg for arg in cmd))
        self.assertEqual(cmd[cmd.index("-i") - 2:cmd.index("-i")], ["-protocol_whitelist", "file"])

    def test_nice_on_linux(self):
        with patch("cartoon.audio.os.name", "posix"), patch("cartoon.audio.shutil.which", return_value="/usr/bin/nice"):
            self.assertEqual(audio._nice(), ["/usr/bin/nice", "-n", "10"])
        with patch("cartoon.audio.os.name", "posix"), patch("cartoon.audio.shutil.which", return_value=None):
            self.assertEqual(audio._nice(), [])
        with patch("cartoon.audio.os.name", "nt"):
            self.assertEqual(audio._nice(), [])
        with patch("cartoon.audio._nice", return_value=["/usr/bin/nice", "-n", "10"]):
            cmd, _ = self._convert(max_seconds=301.0)
        self.assertEqual(cmd[:4], ["/usr/bin/nice", "-n", "10", "ffmpeg"])


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


@override_settings(CACHES=CACHES, ELEVENLABS_API_KEY="test-key")
@skipUnless(HAS_FFMPEG, "нужен ffmpeg")
class BackgroundAudioTests(TestCase):
    """Музыка делается в фоне: веб-запрос не ждёт провайдера по две минуты.

    Жалоба клиента (21.09): при создании музыки Cloudflare отвечал «origin
    returned an invalid or incomplete response» — генерация шла внутри запроса
    и не укладывалась в лимит.
    """

    def setUp(self):
        model = GPTModels.objects.create(name="m", openrouter_id="test/m", max_tokens=10,
                                         markup_coefficient=Decimal("4"))
        preset = CartoonPreset.objects.create(slug="bg-scene", title="Сцена", is_active=True,
                                              scene_prompt="x", image_model=model, video_model=model)
        hero = CartoonCharacter.objects.create(name="Кот", image="cartoon/characters/c.png", is_public=True)
        self.user = get_user_model().objects.create_user(email="bg@example.com", password="x-12345678")
        self.user.token_balance = 100
        self.user.save(update_fields=["token_balance"])
        project = CartoonProject.objects.create(user=self.user, character=hero)
        self.scene = CartoonScene.objects.create(project=project, preset=preset, order=0)
        self.mp3 = _silent_mp3()

    def _post(self, view, body):
        request = APIRequestFactory().post("/x/", body, format="json")
        force_authenticate(request, user=self.user)
        return view.as_view()(request, pk=self.scene.pk)

    def _balance(self):
        self.user.refresh_from_db()
        return self.user.token_balance

    def test_music_answers_at_once_and_is_charged_when_ready(self):
        from cartoon.tasks import make_audio

        with patch("cartoon.tasks.make_audio.delay") as delay, \
             patch("cartoon.audio.music") as provider:
            response = self._post(SceneMusicView, {"prompt": "весёлая мелодия", "seconds": 30})
        self.assertEqual(response.status_code, 202, response.data)
        self.assertEqual(response.data["status"], "pending")
        self.assertEqual(response.data["credits_planned"], 15)
        # Запрос ответил сразу: провайдера никто не ждал, кредиты не тронуты.
        self.assertEqual(provider.call_count, 0)
        self.assertEqual(self._balance(), 100)
        track_id = delay.call_args[0][0]

        with patch("cartoon.audio.music", return_value=self.mp3):
            result = make_audio.apply(args=[track_id]).get()
        self.assertEqual(result["status"], "ready")
        track = CartoonAudioTrack.objects.get(pk=track_id)
        self.assertEqual(track.status, "ready")
        self.assertTrue(track.file)
        self.assertEqual(track.credits_spent, 15)
        self.assertEqual(self._balance(), 85)

    def test_provider_failure_in_background_costs_nothing(self):
        from cartoon.tasks import make_audio

        with patch("cartoon.tasks.make_audio.delay") as delay:
            response = self._post(SceneSfxView, {"prompt": "стук в дверь"})
        self.assertEqual(response.status_code, 202, response.data)
        with patch("cartoon.audio.sound_effect", side_effect=audio.AudioProviderError("http 500")):
            result = make_audio.apply(args=[delay.call_args[0][0]]).get()
        self.assertEqual(result["status"], "failed")
        track = CartoonAudioTrack.objects.get()
        self.assertEqual(track.status, "failed")
        self.assertTrue(track.error)
        self.assertEqual(self._balance(), 100)

    def test_double_click_does_not_order_two_sounds(self):
        with patch("cartoon.tasks.make_audio.delay") as delay:
            first = self._post(SceneMusicView, {"prompt": "весёлая мелодия", "seconds": 30})
            second = self._post(SceneMusicView, {"prompt": "весёлая мелодия", "seconds": 30})
        self.assertEqual(first.status_code, 202)
        self.assertEqual(second.status_code, 429)
        self.assertEqual(delay.call_count, 1)

    def test_pending_track_is_not_mixed_into_the_scene(self):
        CartoonAudioTrack.objects.create(scene=self.scene, kind="music", status="pending",
                                         text="мелодия", credits_planned=15)
        self.scene.video = "cartoon/scenes/whatever.mp4"
        self.assertEqual(audio.mix_scene(self.scene), "")


@override_settings(CACHES=CACHES, ELEVENLABS_API_KEY="test-key")
@skipUnless(HAS_FFMPEG, "нужен ffmpeg")
class VoicePreviewTests(TestCase):
    """Пример голоса звучит на языке человека и делается один раз."""

    def test_russian_sample_is_generated_once_and_reused(self):
        voices = [{"id": "voice01", "name": "Bella"}]
        mp3 = _silent_mp3()
        with patch("cartoon.audio.list_voices", return_value=voices), \
             patch("cartoon.audio.tts", return_value=mp3) as tts:
            first = audio.voice_preview("voice01", "ru")
            second = audio.voice_preview("voice01", "ru")
        self.assertEqual(first, second)
        self.assertEqual(tts.call_count, 1)
        self.assertIn("Привет", tts.call_args[0][0])
        default_storage.delete(first)

    def test_unknown_voice_is_refused(self):
        with patch("cartoon.audio.list_voices", return_value=[{"id": "voice01", "name": "Bella"}]), \
             patch("cartoon.audio.tts") as tts:
            with self.assertRaises(audio.AudioProviderError):
                audio.voice_preview("stranger9", "ru")
        self.assertEqual(tts.call_count, 0)
