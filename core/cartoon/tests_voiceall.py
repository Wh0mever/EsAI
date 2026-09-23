# -*- coding: utf-8 -*-
"""«Озвучить весь мультфильм»: план с ценой до запуска и оплата по факту."""
import shutil
import subprocess
import tempfile
from decimal import Decimal
from pathlib import Path
from unittest import skipUnless
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase, override_settings
from rest_framework.test import APIRequestFactory, force_authenticate

from ai.models import GPTModels
from cartoon import voiceover
from cartoon.models import (CartoonAudioTrack, CartoonCharacter, CartoonPreset, CartoonProject,
                            CartoonScene)
from cartoon.views_audio import ProjectVoiceAllView, ProjectVoicePlanView
from plans.models import TokenTransaction

CACHES = {"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache",
                      "LOCATION": "studio-voiceall-tests"}}
HAS_FFMPEG = bool(shutil.which("ffmpeg") and shutil.which("ffprobe"))

VOICES = [
    {"id": "m1", "name": "Георгий", "gender": "male", "age": "", "accent": "", "description": "",
     "use_case": "", "preview": ""},
    {"id": "f1", "name": "Лаура", "gender": "female", "age": "", "accent": "", "description": "",
     "use_case": "", "preview": ""},
    {"id": "m2", "name": "Каллум", "gender": "male", "age": "", "accent": "", "description": "",
     "use_case": "", "preview": ""},
]


def _mp3() -> bytes:
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "s.mp3"
        subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i",
                        "sine=frequency=440:duration=1", str(out)], check=True)
        return out.read_bytes()


@override_settings(CACHES=CACHES, ELEVENLABS_API_KEY="test-key")
class VoiceAllTests(TestCase):
    def setUp(self):
        # Замок и прогресс лежат в кэше, а номера проектов в SQLite повторяются
        # от теста к тесту: без очистки замок прошлого теста блокировал запуск
        # (те самые два «429 != 202»).
        cache.clear()
        model = GPTModels.objects.create(name="m", openrouter_id="test/m", max_tokens=10,
                                         markup_coefficient=Decimal("4"))
        self.preset = CartoonPreset.objects.create(slug="walk", title="Прогулка", is_active=True,
                                                   scene_prompt="x", image_model=model,
                                                   video_model=model, duration=5)
        self.cat = CartoonCharacter.objects.create(name="Кот", image="cartoon/characters/c.png",
                                                   is_public=True)
        self.dog = CartoonCharacter.objects.create(name="Пёс", image="cartoon/characters/d.png",
                                                   is_public=True)
        self.user = get_user_model().objects.create_user(email="v@example.com", password="x-12345678")
        self.user.token_balance = 100
        self.user.save(update_fields=["token_balance"])
        self.project = CartoonProject.objects.create(user=self.user, character=self.cat)
        self.s1 = CartoonScene.objects.create(project=self.project, preset=self.preset, order=0)
        self.s2 = CartoonScene.objects.create(project=self.project, preset=self.preset, order=1,
                                              character=self.dog, custom_text="герой печёт торт")

    def _post(self, view, body=None, pk=None):
        request = APIRequestFactory().post("/x/", body or {}, format="json")
        force_authenticate(request, user=self.user)
        return view.as_view()(request, pk=pk or self.project.pk)

    def _balance(self):
        self.user.refresh_from_db()
        return self.user.token_balance

    # --- план -------------------------------------------------------------

    def test_plan_gives_line_and_voice_per_scene_without_charging(self):
        lines = {1: "Какой чудесный день для прогулки!", 2: "Торт почти готов, ура!"}
        with patch("cartoon.voiceover.write_lines", return_value=lines) as writer, \
             patch("cartoon.audio.list_voices", return_value=VOICES):
            response = self._post(ProjectVoicePlanView)
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(writer.call_count, 1)
        data = response.data
        self.assertEqual([l["text"] for l in data["lines"]], list(lines.values()))
        self.assertEqual([l["character"]["name"] for l in data["lines"]], ["Кот", "Пёс"])
        # Разные герои — разные голоса, иначе мультфильм звучит одним человеком.
        self.assertNotEqual(data["lines"][0]["voice_id"], data["lines"][1]["voice_id"])
        # Цена показана до запуска и равна сумме реплик; ничего не списано.
        self.assertEqual(data["total_credits"], sum(l["credits"] for l in data["lines"]))
        self.assertEqual(data["total_credits"], 10)  # две короткие реплики по минимуму 5
        self.assertEqual(self._balance(), 100)
        self.assertEqual(data["lines"][1]["title"], "герой печёт торт")

    def test_scene_without_line_stays_visible_and_free(self):
        """Модель ответила не на все сцены: пропавших сцен быть не должно."""
        with patch("cartoon.voiceover.write_lines", return_value={1: "Только первая"}), \
             patch("cartoon.audio.list_voices", return_value=VOICES):
            response = self._post(ProjectVoicePlanView)
        self.assertEqual(response.status_code, 200, response.data)
        lines = response.data["lines"]
        self.assertEqual(len(lines), 2)
        self.assertEqual(lines[1]["text"], "")
        self.assertEqual(lines[1]["credits"], 0)
        self.assertEqual(response.data["total_credits"], 5)

    def test_plan_without_voices_is_refused_before_paying_for_lines(self):
        """Голосов нет — незачем тратить вызов модели на реплики."""
        with patch("cartoon.audio.list_voices", return_value=[]), \
             patch("cartoon.voiceover.write_lines") as writer:
            response = self._post(ProjectVoicePlanView)
        self.assertEqual(response.status_code, 503)
        self.assertEqual(writer.call_count, 0)

    def test_plan_failure_is_not_a_silent_success(self):
        with patch("cartoon.audio.list_voices", return_value=VOICES), \
             patch("cartoon.voiceover.write_lines", side_effect=voiceover.PlanFailed("нет json")):
            response = self._post(ProjectVoicePlanView)
        self.assertEqual(response.status_code, 502)
        self.assertEqual(self._balance(), 100)

    # --- запуск -----------------------------------------------------------

    def test_voice_all_queues_task_and_checks_balance_first(self):
        # Реплика обрезается до 200 символов, поэтому стоит минимальные 5 кредитов.
        body = {"lines": [{"scene_id": self.s1.pk, "text": "а" * 100, "voice_id": "m1"},
                          {"scene_id": self.s2.pk, "text": "б" * 1000, "voice_id": "f1"}]}
        self.user.token_balance = 8
        self.user.save(update_fields=["token_balance"])
        with patch("cartoon.views_audio.voice_movie.delay") as delay:
            response = self._post(ProjectVoiceAllView, body)
        self.assertEqual(response.status_code, 402)
        self.assertEqual(response.data["required"], 10)  # 5 + 5
        self.assertEqual(delay.call_count, 0)

        self.user.token_balance = 100
        self.user.save(update_fields=["token_balance"])
        with patch("cartoon.views_audio.voice_movie.delay") as delay:
            response = self._post(ProjectVoiceAllView, body)
        self.assertEqual(response.status_code, 202, response.data)
        self.assertEqual(response.data["total_credits"], 10)
        self.assertEqual(delay.call_count, 1)
        self.assertEqual(response.data["voicing"]["total"], 2)
        self.assertFalse(response.data["voicing"]["finished"])
        # Пока идёт озвучка, второй запуск не ставится.
        with patch("cartoon.views_audio.voice_movie.delay") as delay:
            again = self._post(ProjectVoiceAllView, body)
        self.assertEqual(again.status_code, 429)
        self.assertEqual(delay.call_count, 0)

    def test_abandoned_run_does_not_block_forever(self):
        """Воркер умер на середине — человек должен смочь запустить заново."""
        body = {"lines": [{"scene_id": self.s1.pk, "text": "Привет", "voice_id": "m1"}]}
        with patch("cartoon.views_audio.voice_movie.delay"):
            self.assertEqual(self._post(ProjectVoiceAllView, body).status_code, 202)
        # Задача начала работу, а потом прогресс перестал обновляться: её больше нет.
        state = voiceover.get_progress(self.project.pk)
        state["queued"] = False
        state["at"] = state["at"] - voiceover.STALE_AFTER - 10
        cache.set(voiceover.progress_key(self.project.pk), state, 60)
        self.assertTrue(voiceover.is_stale(state))
        with patch("cartoon.views_audio.voice_movie.delay") as delay:
            again = self._post(ProjectVoiceAllView, body)
        self.assertEqual(again.status_code, 202, again.data)
        self.assertEqual(delay.call_count, 1)

    def test_duplicate_scene_is_charged_once(self):
        """Дубль сцены в списке не должен оплачиваться дважды."""
        line = {"scene_id": self.s1.pk, "text": "Привет", "voice_id": "m1"}
        with patch("cartoon.views_audio.voice_movie.delay") as delay:
            response = self._post(ProjectVoiceAllView, {"lines": [line, dict(line)]})
        self.assertEqual(response.status_code, 202, response.data)
        self.assertEqual(response.data["count"], 1)
        self.assertEqual(response.data["total_credits"], 5)
        self.assertEqual(len(delay.call_args[0][1]), 1)

    def test_broken_voice_id_is_refused(self):
        """voice_id уходит в адрес запроса к провайдеру — мусор туда попасть не должен."""
        body = {"lines": [{"scene_id": self.s1.pk, "text": "Привет",
                           "voice_id": "../../v1/user"}]}
        with patch("cartoon.views_audio.voice_movie.delay") as delay:
            response = self._post(ProjectVoiceAllView, body)
        self.assertEqual(response.status_code, 400)
        self.assertEqual(delay.call_count, 0)

    def test_foreign_scene_is_ignored(self):
        other = CartoonProject.objects.create(
            user=get_user_model().objects.create_user(email="o@example.com", password="x-12345678"),
            character=self.cat)
        alien = CartoonScene.objects.create(project=other, preset=self.preset, order=0)
        body = {"lines": [{"scene_id": alien.pk, "text": "чужая реплика", "voice_id": "m1"}]}
        with patch("cartoon.views_audio.voice_movie.delay") as delay:
            response = self._post(ProjectVoiceAllView, body)
        self.assertEqual(response.status_code, 400)
        self.assertEqual(delay.call_count, 0)

    # --- сама озвучка -----------------------------------------------------

    @skipUnless(HAS_FFMPEG, "нужен ffmpeg")
    def test_voice_project_charges_per_line_and_replaces_old_voice(self):
        mp3 = _mp3()
        CartoonAudioTrack.objects.create(scene=self.s1, kind="voice", file="cartoon/audio/old.mp3",
                                         text="старая реплика", duration=1)
        plan = [{"scene_id": self.s1.pk, "text": "Привет!", "voice_id": "m1", "voice_name": "Георгий"},
                {"scene_id": self.s2.pk, "text": "Торт готов!", "voice_id": "f1", "voice_name": "Лаура"}]
        with patch("cartoon.audio.tts", return_value=mp3) as tts:
            result = voiceover.voice_project(self.project, plan)
        self.assertEqual(tts.call_count, 2)
        self.assertEqual(result["done"], 2)
        self.assertEqual(result["spent"], 10)
        self.assertEqual(self._balance(), 90)
        self.assertEqual(TokenTransaction.objects.filter(reason="cartoon_voice").count(), 2)
        # Старая реплика заменена, а не добавлена второй дорожкой.
        self.assertEqual(self.s1.audio_tracks.count(), 1)
        self.assertEqual(self.s1.audio_tracks.first().text, "Привет!")
        self.assertEqual(self.s2.audio_tracks.first().voice_name, "Лаура")
        self.assertIsNone(voiceover.get_progress(self.project.pk).get("error") or None)

    @skipUnless(HAS_FFMPEG, "нужен ffmpeg")
    def test_provider_failure_on_one_line_costs_nothing_for_that_line(self):
        mp3 = _mp3()
        calls = {"n": 0}

        def flaky(text, voice_id):
            calls["n"] += 1
            if calls["n"] == 1:
                raise RuntimeError("http 500")
            return mp3

        plan = [{"scene_id": self.s1.pk, "text": "Первая", "voice_id": "m1"},
                {"scene_id": self.s2.pk, "text": "Вторая", "voice_id": "f1"}]
        with patch("cartoon.audio.tts", side_effect=flaky):
            result = voiceover.voice_project(self.project, plan)
        self.assertEqual(result["done"], 1)
        self.assertEqual(self._balance(), 95)
        self.assertFalse(self.s1.audio_tracks.exists())
        self.assertTrue(self.s2.audio_tracks.exists())

    @skipUnless(HAS_FFMPEG, "нужен ffmpeg")
    def test_runs_out_of_credits_mid_way_and_stops(self):
        mp3 = _mp3()
        self.user.token_balance = 5
        self.user.save(update_fields=["token_balance"])
        plan = [{"scene_id": self.s1.pk, "text": "Первая", "voice_id": "m1"},
                {"scene_id": self.s2.pk, "text": "Вторая", "voice_id": "f1"}]
        with patch("cartoon.audio.tts", return_value=mp3):
            result = voiceover.voice_project(self.project, plan)
        self.assertEqual(result["done"], 1)
        self.assertEqual(result["error"], "not_enough_credits")
        self.assertEqual(self._balance(), 0)
        self.assertEqual(CartoonAudioTrack.objects.count(), 1)

    def test_voice_of_a_character_survives_next_run(self):
        """Второй запуск не должен менять герою голос: мультфильм звучал бы рвано."""
        CartoonAudioTrack.objects.create(
            scene=self.s1, kind="voice", character=self.cat, voice_id="m2",
            voice_name="Каллум", file="cartoon/audio/a.mp3", duration=1)
        with patch("cartoon.voiceover.write_lines", return_value={1: "раз", 2: "два"}), \
             patch("cartoon.audio.list_voices", return_value=VOICES):
            plan = voiceover.build_plan(self.project)
        cat_line = next(l for l in plan["lines"] if l["scene_id"] == self.s1.pk)
        self.assertEqual(cat_line["voice_id"], "m2")
        self.assertEqual(cat_line["voice_name"], "Каллум")
        self.assertTrue(cat_line["has_voice"])

    def test_voices_are_shared_per_character_not_per_scene(self):
        third = CartoonScene.objects.create(project=self.project, preset=self.preset, order=2)
        lines = {1: "раз", 2: "два", 3: "три"}
        with patch("cartoon.voiceover.write_lines", return_value=lines), \
             patch("cartoon.audio.list_voices", return_value=VOICES):
            plan = voiceover.build_plan(self.project)
        by_scene = {l["scene_id"]: l["voice_id"] for l in plan["lines"]}
        self.assertEqual(by_scene[self.s1.pk], by_scene[third.pk])  # обе сцены кота
        self.assertNotEqual(by_scene[self.s1.pk], by_scene[self.s2.pk])
