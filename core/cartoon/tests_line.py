# -*- coding: utf-8 -*-
"""Голос героя вместо голоса модели (F30, раздел V): реплика, деньги, сведение.

Главное, что держат эти тесты. Голос входит в цену на кнопке и в резерв; списывается
только за готовый и уже сведённый звук, вместе с видео, и не больше показанного;
второй раз за те же слова не берётся; любой сбой голоса оставляет готовую сцену и
оплаченное видео. Описание вслух не читается и голоса не стоит.
Цены — как в tests_dock_api (markup 40 %): Mini 480p 5 с = 35 (кадр 7 + видео 28), голос 5.
Платных вызовов нет: TTS и ffmpeg подменены, настоящий ffmpeg — в RealFfmpegTests.
"""
from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest import skipUnless
from unittest.mock import MagicMock, patch

from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.db import IntegrityError, transaction
from django.db import connection
from django.test import SimpleTestCase, TestCase, override_settings
from django.test.utils import CaptureQueriesContext

from adminapi.runtime import set_runtime
from ai.models import GenerationLog
from cartoon import audio, director, voiceover
from cartoon import pricing as cp
from cartoon.models import CartoonAudioTrack, CartoonCharacter, CartoonProject, CartoonScene
from cartoon.tasks import _planned_frame
from cartoon.tests_dock_api import MINI, _client, _user
from cartoon.tests_pipeline_dock import _Pipeline

HAS_FFMPEG = bool(shutil.which("ffmpeg") and shutil.which("ffprobe"))

VOICES = [
    {"id": "voice-f1", "name": "Bella", "gender": "female", "age": "young"},
    {"id": "voice-m1", "name": "George", "gender": "male", "age": "middle_aged"},
    {"id": "voice-f2", "name": "Lily", "gender": "female", "age": "middle_aged"},
    {"id": "voice-m2", "name": "Bill", "gender": "male", "age": "old"},
]
LINE = "Ура, получилось!"
DESCRIPTION = "Он герой играет потом ищет свою маму не найдёт плакать после этого"
LINE_FILE = "cartoon/audio/line.mp3"
MIXED = "cartoon/scenes/mixed/line.mp4"
SPEECH = {"prompt": "directed", "negative": "blur", "line_is_speech": True,
          "voice": {"gender": "female", "age": "young"}}
NOT_SPEECH = {**SPEECH, "line_is_speech": False}


def _place(scene, line=None):
    """Как настоящий mix_scene: реплика встаёт на начало окна."""
    if line is not None:
        line.start_sec = scene.speech_start if scene.speech_start is not None else audio.LINE_START_SEC
    return MIXED


@override_settings(ELEVENLABS_API_KEY="test-key")
class LineBase(_Pipeline):
    """Съёмка целиком: подменён ещё и звук — TTS, файл, окно и сведение."""

    def setUp(self):
        super().setUp()
        # Проверка реплик старых сцен — текстовая модель: по умолчанию она «ничего не ответила».
        judge = patch("cartoon.director._ask_lines", return_value={"lines": []})
        self.ask_lines = judge.start()
        self.addCleanup(judge.stop)

    def voiced(self, scene, *, tts=None, mix=None, window=(1.0, 3.0), director_answer=None):
        self.tts = tts if tts is not None else MagicMock(return_value=b"mp3")
        self.mix = mix if mix is not None else MagicMock(side_effect=_place)
        self.dropped = []
        with patch("cartoon.audio.tts", self.tts), \
             patch("cartoon.audio.save_audio", return_value=(LINE_FILE, 2.0)), \
             patch("cartoon.audio.scene_window", return_value=window), \
             patch("cartoon.audio.mix_scene", self.mix), \
             patch("cartoon.audio.list_voices", return_value=VOICES), \
             patch("django.core.files.storage.default_storage.delete", side_effect=self.dropped.append):
            return self.shoot(scene, director_answer=director_answer or SPEECH)

    def fresh(self, dialogue=LINE, project=None, **extra):
        project = project or self.project(model=MINI, resolution="480p", duration=5)
        return self.scene(project, dialogue=dialogue, **extra)

    def ready(self, dialogue=LINE, project=None, **extra):
        """Уже снятая сцена с репликой, как после прошлой съёмки."""
        return self.fresh(dialogue, project, status=CartoonScene.STATUS_READY,
                          video="cartoon/scenes/s.mp4", keyframe="cartoon/k/1.png", video_prompt="p",
                          video_negative="n", shot_model=self.models[MINI], shot_resolution="480p",
                          shot_duration=5, shot_aspect="16:9", credits_planned=35, shot_video_credits=28,
                          **extra)

    def line_row(self, scene):
        return CartoonAudioTrack.objects.filter(scene=scene, kind=CartoonAudioTrack.KIND_LINE)

    def row(self, scene):
        body = self.client.get(f"/api/cartoon/projects/{scene.project_id}/").json()
        return next(s for s in body["scenes"] if s["id"] == scene.pk)

    def voice_log(self, scene):
        return GenerationLog.objects.filter(scene_id=scene.pk, kind="voice")

    def balance(self):
        self.user.refresh_from_db()
        return self.user.token_balance


class ShotPriceTests(LineBase):
    def test_button_price_and_reserve_include_the_voice(self):
        scene = self.fresh()
        row = self.row(scene)
        self.assertEqual((row["render_credits"], row["preset"]["credits"]), (40, 40))
        self.assertEqual((row["render_voice_credits"], row["line_voice_price"]), (5, 5))
        response, _ = self.render(scene)
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual((scene.credits_planned, scene.shot_video_credits, scene.shot_voice_credits),
                         (40, 28, 5))
        self.assertEqual(cp.reserved_credits(self.user), 40)
        # Кадр готов — в резерве видео и голос, а не цена целиком.
        CartoonScene.objects.filter(pk=scene.pk).update(keyframe="cartoon/k/1.png", status="video")
        self.assertEqual(cp.reserved_credits(self.user), 33)

    def test_voice_counts_towards_the_balance_check(self):
        scene = self.fresh()
        self.user.token_balance = 39
        self.user.save(update_fields=["token_balance"])
        response, delay = self.render(scene)
        self.assertEqual(response.status_code, 402, response.content)
        self.assertEqual(response.json()["required"], 40)
        delay.assert_not_called()

    def test_scene_without_a_line_costs_as_before(self):
        scene = self.fresh(dialogue="")
        row = self.row(scene)
        self.assertEqual((row["render_credits"], row["render_voice_credits"]), (35, 0))
        self.assertIsNone(row["line_voice_price"])
        self.render(scene)
        self.assertEqual((scene.credits_planned, scene.shot_voice_credits), (35, 0))

    def test_frame_part_does_not_swallow_the_voice(self):
        """Кадр считается как «цена запуска минус видео»: без голоса в вычитании
        человек заплатил бы за кадр 12 вместо 7."""
        scene = self.fresh()
        self.render(scene)
        self.assertEqual(_planned_frame(scene, cp.shot_config(scene), 7), 7)

    def test_working_scene_shows_the_snapshot_with_voice(self):
        scene = self.fresh()
        self.render(scene)
        row = self.row(scene)
        self.assertEqual((row["render_credits"], row["render_voice_credits"]), (40, 5))


class RenderVoiceTests(LineBase):
    def test_voice_is_charged_with_the_video_after_the_sound_is_ready(self):
        scene = self.fresh()
        self.render(scene)
        seen = self.voiced(scene)
        self.assertEqual(seen["result"]["status"], "ready", seen["result"])
        self.assertEqual((self.charges("cartoon_keyframe"), self.charges("cartoon_scene"),
                          self.charges("cartoon_voice")), ([7], [28], [5]))
        self.assertEqual(self.balance(), 10000 - 40)
        # Голос лежит в дорожке, а не в scene.credits_spent: проект суммирует оба.
        self.assertEqual(scene.credits_spent, 35)
        track = self.line_row(scene).get()
        self.assertEqual((track.text, track.voice_id, track.voice_name, track.credits_spent, track.start_sec),
                         (LINE, "voice-f1", "Bella", 5, 1.0))
        self.assertEqual(track.character_id, self.hero.pk)
        self.assertEqual((scene.mixed_video, scene.speech_start, scene.speech_end), (MIXED, 1.0, 3.0))
        self.assertEqual(self.tts.call_args.args, (LINE, "voice-f1"))
        log = self.voice_log(scene).get()
        self.assertEqual((log.status, log.credits_charged, log.provider, log.source),
                         (GenerationLog.STATUS_DELIVERED, 5, "elevenlabs", "studio"))
        project = CartoonProject.objects.get(pk=scene.project_id)
        self.assertEqual(project.hero_voices, {str(self.hero.pk): {"voice_id": "voice-f1", "voice_name": "Bella"}})
        row = self.row(scene)
        self.assertEqual(row["speech_window"], [1.0, 3.0])
        self.assertEqual(row["line_voice"], {"voice_id": "voice-f1", "voice_name": "Bella",
                                             "track_id": track.pk, "credits": 5, "start_sec": 1.0,
                                             "text": LINE, "stale": False})
        self.assertEqual(row["render_credits"], 28)     # пересъёмка: кадр есть, голос уже оплачен

    def test_mix_comes_before_the_transaction_and_only_once(self):
        scene = self.fresh()
        self.render(scene)
        statuses = []

        def mix(sc, line=None):
            statuses.append((CartoonScene.objects.get(pk=sc.pk).status, line.pk))
            return MIXED

        self.voiced(scene, mix=MagicMock(side_effect=mix))
        # Сцена ещё не готова (фронт её опрашивает), дорожки в базе ещё нет, денег нет.
        self.assertEqual(statuses, [(CartoonScene.STATUS_VIDEO, None)])

    def test_tts_failure_leaves_a_ready_scene_and_the_video_charge(self):
        scene = self.fresh()
        self.render(scene)
        seen = self.voiced(scene, tts=MagicMock(side_effect=audio.AudioProviderError("http 500", status=500)))
        self.assertEqual(seen["result"]["status"], "ready", seen["result"])
        self.assertEqual((self.charges("cartoon_scene"), self.charges("cartoon_voice")), ([28], []))
        self.assertEqual(self.balance(), 10000 - 35)
        self.assertFalse(self.line_row(scene).exists())
        self.assertEqual((scene.status, scene.mixed_video), (CartoonScene.STATUS_READY, ""))
        self.assertEqual(self.voice_log(scene).get().status, GenerationLog.STATUS_FAILED)
        row = self.row(scene)
        self.assertIsNone(row["line_voice"])
        self.assertEqual(row["line_voice_price"], 5)    # на карточке кнопка «Озвучить»

    def test_mix_failure_costs_nothing_and_removes_the_file(self):
        scene = self.fresh()
        self.render(scene)
        seen = self.voiced(scene, mix=MagicMock(side_effect=audio.AudioProviderError("сведение не удалось")))
        self.assertEqual(seen["result"]["status"], "ready", seen["result"])
        self.assertEqual((self.charges("cartoon_scene"), self.charges("cartoon_voice")), ([28], []))
        self.assertFalse(self.line_row(scene).exists())
        self.assertIn(LINE_FILE, self.dropped)
        self.assertEqual(self.voice_log(scene).get().status, GenerationLog.STATUS_FAILED)

    def test_voice_write_failure_rolls_back_the_voice_only(self):
        from cartoon import services

        real = services.charge

        def picky(user, amount, reason, *a, **kw):
            if reason == "cartoon_voice":
                raise RuntimeError("база моргнула")
            return real(user, amount, reason, *a, **kw)

        scene = self.fresh()
        self.render(scene)
        with patch("cartoon.services.charge", side_effect=picky):
            seen = self.voiced(scene)
        self.assertEqual(seen["result"]["status"], "ready", seen["result"])
        self.assertEqual((self.charges("cartoon_scene"), self.charges("cartoon_voice")), ([28], []))
        self.assertFalse(self.line_row(scene).exists())
        self.assertEqual(scene.mixed_video, "")
        self.assertIn(LINE_FILE, self.dropped)
        self.assertIn(MIXED, self.dropped)
        self.assertEqual(self.voice_log(scene).get().status, GenerationLog.STATUS_LOST)

    def test_not_enough_for_the_voice_skips_the_paid_synthesis(self):
        scene = self.fresh()
        self.render(scene)
        self.user.token_balance = 35    # кадр и видео есть, голос — нет
        self.user.save(update_fields=["token_balance"])
        seen = self.voiced(scene)
        self.assertEqual(seen["result"]["status"], "ready", seen["result"])
        self.assertEqual(self.tts.call_count, 0)
        self.assertEqual(self.charges("cartoon_voice"), [])
        self.assertEqual(self.balance(), 0)
        self.assertFalse(self.line_row(scene).exists())

    def test_credits_gone_at_the_last_moment_keep_the_video(self):
        from plans.wallet import InsufficientTokens

        scene = self.fresh()
        self.render(scene)
        from cartoon import services

        real = services.charge

        def short(user, amount, reason, *a, **kw):
            if reason == "cartoon_voice":
                raise InsufficientTokens(balance=0, required=amount)
            return real(user, amount, reason, *a, **kw)

        with patch("cartoon.services.charge", side_effect=short):
            seen = self.voiced(scene)
        self.assertEqual(seen["result"]["status"], "ready", seen["result"])
        self.assertEqual((self.charges("cartoon_scene"), self.charges("cartoon_voice")), ([28], []))
        self.assertFalse(self.line_row(scene).exists())
        self.assertEqual(self.voice_log(scene).get().status, GenerationLog.STATUS_LOST)

    def test_scene_deleted_during_the_voice_charges_nothing(self):
        scene = self.fresh()
        self.render(scene)

        def gone(*a, **kw):
            CartoonScene.objects.filter(pk=scene.pk).update(status=CartoonScene.STATUS_FAILED)
            return b"mp3"

        seen = self.voiced(scene, tts=MagicMock(side_effect=gone))
        self.assertEqual(seen["result"]["status"], "gone")
        self.assertEqual((self.charges("cartoon_scene"), self.charges("cartoon_voice")), ([], []))
        self.assertFalse(self.line_row(scene).exists())
        self.assertIn(LINE_FILE, self.dropped)
        self.assertEqual(self.voice_log(scene).get().status, GenerationLog.STATUS_LOST)

    def test_soft_time_limit_in_the_voice_still_delivers_the_video(self):
        from celery.exceptions import SoftTimeLimitExceeded

        scene = self.fresh()
        self.render(scene)
        seen = self.voiced(scene, tts=MagicMock(side_effect=SoftTimeLimitExceeded()))
        self.assertEqual(seen["result"]["status"], "ready", seen["result"])
        self.assertEqual(self.charges("cartoon_scene"), [28])

    def test_heartbeat_keeps_going_while_the_voice_is_made(self):
        scene = self.fresh()
        self.render(scene)
        beat = MagicMock()
        with patch("cartoon.tasks._heartbeat", return_value=beat):
            self.voiced(scene)
        self.assertGreaterEqual(beat.call_count, 4)     # окно, TTS, файл, сведение

    def test_catalog_failure_is_journalled_too(self):
        scene = self.fresh()
        self.render(scene)
        with patch("cartoon.voiceover.hero_voice", side_effect=voiceover.NoVoices("пусто")):
            seen = self.voiced(scene)
        self.assertEqual(seen["result"]["status"], "ready", seen["result"])
        self.assertEqual(self.tts.call_count, 0)
        self.assertEqual(self.voice_log(scene).get().status, GenerationLog.STATUS_FAILED)

    def test_no_line_means_no_new_work(self):
        scene = self.fresh(dialogue="")
        self.render(scene)
        window = MagicMock()
        with patch("cartoon.audio.scene_window", window):
            seen = self.shoot(scene)
        self.assertEqual(seen["result"]["status"], "ready")
        window.assert_not_called()
        self.assertEqual(self.charges("cartoon_voice"), [])

    def test_mode_off_is_exactly_the_old_behaviour(self):
        set_runtime(audio.LINE_MODE_KEY, "off")
        scene = self.fresh()
        row = self.row(scene)
        self.assertEqual((row["render_credits"], row["render_voice_credits"]), (35, 0))
        self.assertIsNone(row["line_voice_price"])
        self.render(scene)
        self.assertEqual(scene.credits_planned, 35)
        seen = self.voiced(scene)
        self.assertEqual(seen["result"]["status"], "ready")
        self.assertEqual((self.tts.call_count, self.mix.call_count), (0, 0))
        self.assertEqual(self.charges("cartoon_voice"), [])

    def test_mode_staff_is_for_staff_only(self):
        set_runtime(audio.LINE_MODE_KEY, "staff")
        self.assertFalse(audio.line_enabled(self.user))
        self.assertTrue(audio.line_enabled(_user("boss@example.com", 0, staff=True)))
        set_runtime(audio.LINE_MODE_KEY, "что-то странное")
        self.assertEqual(audio.line_mode(), "off")

    def test_queued_before_the_feature_is_not_charged_for_what_was_not_shown(self):
        """Цена запуска не содержала голоса — голоса и не будет: только показанное."""
        scene = self.fresh()
        self.render(scene)
        CartoonScene.objects.filter(pk=scene.pk).update(shot_voice_credits=None, credits_planned=35)
        scene.refresh_from_db()
        seen = self.voiced(scene)
        self.assertEqual(seen["result"]["status"], "ready")
        self.assertEqual((self.tts.call_count, self.charges("cartoon_voice")), (0, []))


class DescriptionTests(LineBase):
    def test_description_is_neither_voiced_nor_charged(self):
        scene = self.fresh(DESCRIPTION)
        self.render(scene)
        self.assertEqual(scene.shot_voice_credits, 5)   # до режиссёра считаем как за голос
        seen = self.voiced(scene, director_answer=NOT_SPEECH)
        self.assertEqual(seen["result"]["status"], "ready", seen["result"])
        self.assertEqual((self.tts.call_count, self.charges("cartoon_voice")), (0, []))
        self.assertEqual(self.balance(), 10000 - 35)
        self.assertFalse(scene.dialogue_is_speech)
        row = self.row(scene)
        self.assertFalse(row["dialogue_is_speech"])
        self.assertIsNone(row["line_voice"])
        self.assertIsNone(row["line_voice_price"])
        self.assertEqual(row["render_credits"], 28)     # решение уже известно — голоса в цене нет

    def test_changing_the_text_forgets_the_decision(self):
        scene = self.ready(DESCRIPTION, dialogue_is_speech=False)
        response = self.client.patch(f"/api/cartoon/scenes/{scene.pk}/", {"dialogue": "Мама, ты где?"},
                                     format="json")
        self.assertEqual(response.status_code, 200, response.content)
        body = response.json()
        self.assertTrue(body["dialogue_is_speech"])
        self.assertEqual(body["line_voice_price"], 5)

    def test_hint_is_kept_for_the_voice_choice_on_reshoot(self):
        scene = self.fresh()
        self.render(scene)
        self.voiced(scene, tts=MagicMock(side_effect=audio.AudioProviderError("x", status=500)),
                    director_answer={**SPEECH, "voice": {"gender": "male", "age": "old"}})
        self.assertEqual(scene.voice_hint, {"gender": "male", "age": "old", "lang": "other"})


class ReshootTests(LineBase):
    def shot_scene(self, dialogue=LINE, window=(1.0, 3.0)):
        scene = self.fresh(dialogue)
        self.render(scene)
        self.voiced(scene, window=window)
        return scene

    def test_same_words_same_voice_are_reused_for_free(self):
        scene = self.shot_scene()
        first = self.line_row(scene).get()
        response, _ = self.reshoot(scene)
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual((scene.credits_planned, scene.shot_voice_credits), (28, 0))
        seen = self.voiced(scene, window=(2.0, 4.0))
        self.assertEqual(seen["result"]["status"], "ready", seen["result"])
        self.assertEqual(self.tts.call_count, 0)
        self.assertEqual(self.charges("cartoon_voice"), [5])
        self.assertEqual(self.charges("cartoon_scene"), [28, 28])
        track = self.line_row(scene).get()
        # Та же дорожка, новое окно: иначе голос поехал бы относительно рта.
        self.assertEqual((track.pk, track.start_sec), (first.pk, 2.0))
        self.assertEqual((scene.mixed_video, scene.speech_start), (MIXED, 2.0))

    def test_changed_words_are_a_new_voice_at_a_new_price(self):
        scene = self.shot_scene()
        r = self.client.patch(f"/api/cartoon/scenes/{scene.pk}/", {"dialogue": "Новая реплика"}, format="json")
        self.assertEqual(r.json()["line_voice"]["stale"], True)
        self.assertEqual(r.json()["render_credits"], 33)
        self.reshoot(scene)
        self.assertEqual((scene.credits_planned, scene.shot_voice_credits), (33, 5))
        self.voiced(scene)
        self.assertEqual(self.charges("cartoon_voice"), [5, 5])
        self.assertEqual(self.tts.call_args.args[0], "Новая реплика")
        self.assertEqual(self.line_row(scene).get().text, "Новая реплика")

    def test_changed_voice_is_a_new_voice_at_a_new_price(self):
        scene = self.shot_scene()
        with patch("cartoon.audio.list_voices", return_value=VOICES):
            r = self.client.patch(f"/api/cartoon/projects/{scene.project_id}/hero-voice/",
                                  {"character_id": self.hero.pk, "voice_id": "voice-m1"}, format="json")
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(self.row(scene)["render_credits"], 33)
        self.reshoot(scene)
        self.voiced(scene)
        self.assertEqual(self.tts.call_args.args, (LINE, "voice-m1"))
        self.assertEqual(self.charges("cartoon_voice"), [5, 5])
        track = self.line_row(scene).get()
        self.assertEqual((track.voice_id, track.voice_name), ("voice-m1", "George"))

    def test_stale_line_does_not_outlive_the_failed_voice(self):
        """Реплику поменяли, голос не вышел: старые слова на новом ролике не нужны."""
        scene = self.shot_scene()
        self.client.patch(f"/api/cartoon/scenes/{scene.pk}/", {"dialogue": "Новая реплика"}, format="json")
        self.reshoot(scene)
        self.voiced(scene, tts=MagicMock(side_effect=audio.AudioProviderError("x", status=500)))
        self.assertFalse(self.line_row(scene).exists())
        self.assertEqual(scene.mixed_video, "")

    def test_failed_voice_keeps_the_same_words_in_the_old_voice(self):
        scene = self.shot_scene()
        with patch("cartoon.audio.list_voices", return_value=VOICES):
            self.client.patch(f"/api/cartoon/projects/{scene.project_id}/hero-voice/",
                              {"character_id": self.hero.pk, "voice_id": "voice-m1"}, format="json")
        self.reshoot(scene)
        self.voiced(scene, tts=MagicMock(side_effect=audio.AudioProviderError("x", status=500)))
        self.assertEqual(self.line_row(scene).get().voice_id, "voice-f1")
        self.assertEqual(self.charges("cartoon_voice"), [5])

    def test_cleared_line_leaves_with_the_reshoot(self):
        scene = self.shot_scene()
        self.client.patch(f"/api/cartoon/scenes/{scene.pk}/", {"dialogue": ""}, format="json")
        self.reshoot(scene)
        self.voiced(scene)
        self.assertFalse(self.line_row(scene).exists())

    def test_people_tracks_are_not_touched(self):
        scene = self.shot_scene()
        own = CartoonAudioTrack.objects.create(scene=scene, kind="voice", file="cartoon/audio/own.mp3",
                                               text="своя озвучка", voice_id="voice-f2", duration=1)
        self.client.patch(f"/api/cartoon/scenes/{scene.pk}/", {"dialogue": "Новая реплика"}, format="json")
        self.reshoot(scene)
        self.voiced(scene)
        self.assertTrue(CartoonAudioTrack.objects.filter(pk=own.pk).exists())

    def test_line_voiced_by_voice_all_while_shooting_is_not_paid_twice(self):
        scene = self.fresh()
        self.render(scene)

        def rival(*a, **kw):
            # Пока шёл синтез, реплику озвучил запуск «Озвучить весь мультфильм».
            CartoonAudioTrack.objects.create(scene=scene, kind="line", text=LINE, voice_id="voice-f1",
                                             file="cartoon/audio/rival.mp3", duration=2, credits_spent=5)
            return b"mp3"

        self.voiced(scene, tts=MagicMock(side_effect=rival))
        self.assertEqual(self.charges("cartoon_voice"), [])
        self.assertEqual(self.line_row(scene).get().file, "cartoon/audio/rival.mp3")
        self.assertEqual(self.voice_log(scene).get().status, GenerationLog.STATUS_LOST)


class HeroVoiceTests(LineBase):
    def hero2(self):
        return CartoonCharacter.objects.create(name="Пёс", image="cartoon/characters/d.png", is_public=True)

    def test_one_voice_for_the_hero_across_the_movie(self):
        project = self.project(model=MINI, resolution="480p", duration=5)
        first, second = self.fresh(project=project), self.fresh("Ещё реплика", project=project)
        self.render(first)
        self.render(second)
        self.voiced(first)
        self.voiced(second, director_answer={**SPEECH, "voice": {"gender": "male", "age": "old"}})
        self.assertEqual({t.voice_id for t in CartoonAudioTrack.objects.filter(kind="line")}, {"voice-f1"})

    def test_two_heroes_get_two_voices(self):
        project = self.project(model=MINI, resolution="480p", duration=5)
        first = self.fresh(project=project)
        second = self.fresh("А это я", project=project, character=self.hero2())
        self.render(first)
        self.render(second)
        self.voiced(first)
        self.voiced(second)
        voices = {t.character_id: t.voice_id for t in CartoonAudioTrack.objects.filter(kind="line")}
        self.assertEqual(len(set(voices.values())), 2)
        project.refresh_from_db()
        self.assertEqual(len(project.hero_voices), 2)

    def test_first_scene_wins_when_two_choose_at_once(self):
        project = self.project()
        chosen = voiceover.set_hero_voice(project, self.hero, {"voice_id": "voice-f1", "voice_name": "Bella"},
                                          keep=True)
        again = voiceover.set_hero_voice(project, self.hero, {"voice_id": "voice-m1", "voice_name": "George"},
                                         keep=True)
        self.assertEqual(again, chosen)
        self.assertEqual(project.hero_voices[str(self.hero.pk)]["voice_id"], "voice-f1")

    def test_hint_chooses_gender_and_age(self):
        pick = voiceover.pick_voices([self.hero], VOICES, hints={self.hero.pk: {"gender": "male", "age": "old"}})
        self.assertEqual(pick[self.hero.pk]["voice_id"], "voice-m2")
        pick = voiceover.pick_voices([self.hero], VOICES, hints={self.hero.pk: {"gender": "female", "age": "child"}})
        self.assertEqual(pick[self.hero.pk]["voice_id"], "voice-f1")

    def test_voice_of_another_hero_is_not_given_out(self):
        fixed = {999: {"voice_id": "voice-m2", "voice_name": "Bill"}}
        pick = voiceover.pick_voices([self.hero], VOICES, fixed=fixed,
                                     hints={self.hero.pk: {"gender": "male", "age": "old"}})
        self.assertEqual(pick[self.hero.pk]["voice_id"], "voice-m1")

    def test_chosen_voice_beats_the_last_track(self):
        project = self.project()
        project.hero_voices = {str(self.hero.pk): {"voice_id": "voice-f2", "voice_name": "Lily"}}
        project.save()
        scene = self.fresh(project=project)
        CartoonAudioTrack.objects.create(scene=scene, kind="voice", character=self.hero, voice_id="voice-m1",
                                         file="cartoon/audio/a.mp3", duration=1)
        self.assertEqual(voiceover.known_voices(project)[self.hero.pk]["voice_id"], "voice-f2")


class LineApiTests(LineBase):
    """POST/DELETE scenes/<id>/audio/line/ и PATCH projects/<id>/hero-voice/."""

    def post(self, scene, body=None, *, tts=None, mix=None, user=None, window=(1.0, 3.0)):
        self.tts = tts if tts is not None else MagicMock(return_value=b"mp3")
        self.mix = mix if mix is not None else MagicMock(side_effect=_place)
        self.dropped = []
        with patch("cartoon.audio.tts", self.tts), \
             patch("cartoon.audio.save_audio", return_value=(LINE_FILE, 2.0)), \
             patch("cartoon.audio.scene_window", return_value=window), \
             patch("cartoon.audio.mix_scene", self.mix), \
             patch("cartoon.audio.list_voices", return_value=VOICES), \
             patch("django.core.files.storage.default_storage.delete", side_effect=self.dropped.append):
            return _client(user or self.user).post(f"/api/cartoon/scenes/{scene.pk}/audio/line/", body or {},
                                                   format="json")

    def test_ready_scene_is_voiced_and_charged_after_the_sound(self):
        scene = self.ready(voice_hint=SPEECH["voice"])
        response = self.post(scene)
        self.assertEqual(response.status_code, 201, response.content)
        body = response.json()
        self.assertEqual(self.charges("cartoon_voice"), [5])
        self.assertEqual((body["kind"], body["start_sec"], body["credits_spent"]), ("line", 1.0, 5))
        self.assertEqual(body["scene"]["line_voice"]["voice_name"], "Bella")
        self.assertEqual(body["scene"]["speech_window"], [1.0, 3.0])
        self.assertEqual(body["hero_voices"][str(self.hero.pk)]["voice_id"], "voice-f1")
        scene.refresh_from_db()
        self.assertEqual((scene.mixed_video, scene.speech_start), (MIXED, 1.0))
        self.assertEqual(self.voice_log(scene).get().status, GenerationLog.STATUS_DELIVERED)

    def test_change_of_voice_replaces_the_line_and_the_hero_voice(self):
        scene = self.ready(voice_hint=SPEECH["voice"])
        self.post(scene)
        response = self.post(scene, {"voice_id": "voice-m1"})
        self.assertEqual(response.status_code, 201, response.content)
        self.assertEqual(self.charges("cartoon_voice"), [5, 5])
        self.assertEqual(self.line_row(scene).get().voice_id, "voice-m1")
        self.assertEqual(response.json()["hero_voices"][str(self.hero.pk)]["voice_name"], "George")

    def test_double_click_is_not_paid_twice(self):
        scene = self.ready()
        self.post(scene)
        response = self.post(scene)
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(self.tts.call_count, 0)
        self.assertEqual(self.charges("cartoon_voice"), [5])

    def test_old_text_is_voiced_again_after_an_edit(self):
        scene = self.ready()
        self.post(scene)
        CartoonScene.objects.filter(pk=scene.pk).update(dialogue="Другие слова")
        response = self.post(scene)
        self.assertEqual(response.status_code, 201, response.content)
        self.assertEqual(self.line_row(scene).get().text, "Другие слова")

    def test_provider_failure_costs_nothing(self):
        scene = self.ready()
        response = self.post(scene, tts=MagicMock(side_effect=audio.AudioProviderError("http 500", status=500)))
        self.assertEqual(response.status_code, 502, response.content)
        self.assertEqual(self.charges("cartoon_voice"), [])
        self.assertFalse(self.line_row(scene).exists())
        self.assertEqual(self.voice_log(scene).get().status, GenerationLog.STATUS_FAILED)

    def test_mix_failure_costs_nothing(self):
        scene = self.ready()
        response = self.post(scene, mix=MagicMock(side_effect=audio.AudioProviderError("сведение не удалось")))
        self.assertEqual(response.status_code, 502, response.content)
        self.assertEqual(self.charges("cartoon_voice"), [])
        self.assertFalse(self.line_row(scene).exists())
        self.assertIn(LINE_FILE, self.dropped)

    def test_not_enough_credits_is_refused_before_the_provider(self):
        scene = self.ready()
        self.user.token_balance = 4
        self.user.save(update_fields=["token_balance"])
        response = self.post(scene)
        self.assertEqual(response.status_code, 402, response.content)
        self.assertEqual(response.json()["required"], 5)
        self.assertEqual(self.tts.call_count, 0)

    def test_credits_spent_while_synthesising(self):
        scene = self.ready()

        def spent(*a, **kw):
            type(self.user).objects.filter(pk=self.user.pk).update(token_balance=1)
            return b"mp3"

        response = self.post(scene, tts=MagicMock(side_effect=spent))
        self.assertEqual(response.status_code, 402, response.content)
        self.assertFalse(self.line_row(scene).exists())
        self.assertIn(LINE_FILE, self.dropped)
        self.assertEqual(self.voice_log(scene).get().status, GenerationLog.STATUS_LOST)

    def test_reshoot_started_while_synthesising_is_not_charged(self):
        scene = self.ready()

        def moved(*a, **kw):
            CartoonScene.objects.filter(pk=scene.pk).update(status=CartoonScene.STATUS_NEW)
            return b"mp3"

        response = self.post(scene, tts=MagicMock(side_effect=moved))
        self.assertEqual(response.status_code, 409, response.content)
        self.assertEqual(self.charges("cartoon_voice"), [])
        self.assertFalse(self.line_row(scene).exists())

    def test_refusals(self):
        draft = self.fresh()
        self.assertEqual(self.post(draft).json()["error_code"], "scene_not_ready")
        self.assertEqual(self.post(self.ready(dialogue="")).json()["error_code"], "no_dialogue")
        described = self.ready(DESCRIPTION, dialogue_is_speech=False)
        self.assertEqual(self.post(described).json()["error_code"], "not_speech")
        self.assertEqual(self.post(self.ready(), {"voice_id": "../../v1/user"}).status_code, 400)
        self.assertEqual(self.post(self.ready(), {"voice_id": "stranger1"}).status_code, 400)
        self.assertEqual(self.charges("cartoon_voice"), [])

    def test_foreign_scene_is_404(self):
        scene = self.ready()
        response = self.post(scene, user=_user("stranger@example.com", 100))
        self.assertEqual(response.status_code, 404)
        self.assertEqual(self.tts.call_count, 0)

    def test_mode_off_refuses(self):
        set_runtime(audio.LINE_MODE_KEY, "off")
        self.assertEqual(self.post(self.ready()).status_code, 403)

    @override_settings(ELEVENLABS_API_KEY="")
    def test_not_configured(self):
        with patch("cartoon.audio._runtime", side_effect=lambda k, d: d):
            self.assertEqual(self.post(self.ready()).status_code, 503)

    def test_busy_mix_is_refused_without_paying(self):
        scene = self.ready()
        with patch("cartoon.audio.mix_lock", side_effect=audio.MixBusy("x")):
            response = self.post(scene)
        self.assertEqual(response.status_code, 429)
        self.assertEqual(self.tts.call_count, 0)

    def delete(self, scene, user=None, **patches):
        with patch("cartoon.audio.remix_scene", **patches) as remix:
            response = _client(user or self.user).delete(f"/api/cartoon/scenes/{scene.pk}/audio/line/")
        return response, remix

    def test_back_to_the_model_voice(self):
        scene = self.ready()
        self.post(scene)
        response, remix = self.delete(scene)
        self.assertEqual(response.status_code, 200, response.content)
        self.assertFalse(self.line_row(scene).exists())
        remix.assert_called_once()
        self.assertIsNone(response.json()["scene"]["line_voice"])
        self.assertEqual(response.json()["scene"]["line_voice_price"], 5)
        self.assertEqual(self.charges("cartoon_voice"), [5])    # не возврат денег, а выбор голоса

    def test_failed_remix_falls_back_to_the_clean_video(self):
        scene = self.ready()
        self.post(scene)
        response, _ = self.delete(scene, side_effect=audio.AudioProviderError("x"))
        self.assertEqual(response.status_code, 200, response.content)
        scene.refresh_from_db()
        self.assertEqual(scene.mixed_video, "")     # глушить модель больше некому

    def test_delete_is_refused_while_shooting(self):
        scene = self.ready()
        self.post(scene)
        CartoonScene.objects.filter(pk=scene.pk).update(status=CartoonScene.STATUS_VIDEO)
        response, _ = self.delete(scene)
        self.assertEqual(response.status_code, 400)
        self.assertTrue(self.line_row(scene).exists())

    def test_delete_of_foreign_scene_is_404(self):
        scene = self.ready()
        response, _ = self.delete(scene, user=_user("stranger@example.com", 100))
        self.assertEqual(response.status_code, 404)

    def hero_voice(self, project, body, voices=VOICES):
        with patch("cartoon.audio.list_voices", return_value=voices):
            return self.client.patch(f"/api/cartoon/projects/{project.pk}/hero-voice/", body, format="json")

    def test_hero_voice(self):
        project = self.project()
        response = self.hero_voice(project, {"character_id": self.hero.pk, "voice_id": "voice-f2"})
        self.assertEqual(response.status_code, 200, response.content)
        expected = {str(self.hero.pk): {"voice_id": "voice-f2", "voice_name": "Lily"}}
        self.assertEqual(response.json(), {"hero_voices": expected})
        body = self.client.get(f"/api/cartoon/projects/{project.pk}/").json()
        self.assertEqual(body["hero_voices"], expected)

    def test_hero_voice_refusals(self):
        project = self.project()
        self.assertEqual(self.hero_voice(project, {"character_id": self.hero.pk, "voice_id": "x/y"}).status_code, 400)
        self.assertEqual(self.hero_voice(project, {"character_id": self.hero.pk, "voice_id": "nobody1"}).status_code, 400)
        self.assertEqual(self.hero_voice(project, {"character_id": 0, "voice_id": "voice-f1"}).status_code, 400)
        self.assertEqual(self.hero_voice(project, {"character_id": self.hero.pk, "voice_id": "voice-f1"},
                                         voices=[]).status_code, 503)
        project.refresh_from_db()
        self.assertEqual(project.hero_voices, {})

    def test_hero_voice_of_someone_elses_project_is_404(self):
        other = self.project(user=_user("other@example.com", 0))
        self.assertEqual(self.hero_voice(other, {"character_id": self.hero.pk, "voice_id": "voice-f1"}).status_code, 404)

    def test_someone_elses_private_hero_is_refused(self):
        stranger = _user("owner@example.com", 0)
        private = CartoonCharacter.objects.create(name="Чужой", image="cartoon/characters/x.png", user=stranger)
        response = self.hero_voice(self.project(), {"character_id": private.pk, "voice_id": "voice-f1"})
        self.assertEqual(response.status_code, 400)

    def test_second_line_on_a_scene_is_impossible(self):
        scene = self.ready()
        CartoonAudioTrack.objects.create(scene=scene, kind="line", file="a.mp3")
        with self.assertRaises(IntegrityError), transaction.atomic():
            CartoonAudioTrack.objects.create(scene=scene, kind="line", file="b.mp3")
        # Другие виды — сколько угодно.
        CartoonAudioTrack.objects.create(scene=scene, kind="voice", file="c.mp3")
        CartoonAudioTrack.objects.create(scene=scene, kind="voice", file="d.mp3")

    def test_movie_list_does_not_ask_for_lines_scene_by_scene(self):
        project = self.project(model=MINI, resolution="480p", duration=5)
        for i in range(2):
            self.ready(f"реплика {i}", project=project)

        def tracks():
            with CaptureQueriesContext(connection) as ctx:
                self.client.get(f"/api/cartoon/projects/{project.pk}/")
            return sum('"cartoon_cartoonaudiotrack"' in q["sql"] and "kind" in q["sql"]
                       for q in ctx.captured_queries)

        before = tracks()
        for i in range(2, 6):
            self.ready(f"реплика {i}", project=project)
        self.assertEqual(tracks(), before)


class AdminModeTests(LineBase):
    URL = "/api/manage/settings/"

    def test_mode_is_a_setting(self):
        staff = _client(_user("staff@example.com", 0, staff=True))
        self.assertEqual(staff.get(self.URL).json()["studio_line_voice_mode"], "on")
        response = staff.patch(self.URL, {"studio_line_voice_mode": "staff"}, format="json")
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(audio.line_mode(), "staff")
        self.assertEqual(staff.patch(self.URL, {"studio_line_voice_mode": "всем"}, format="json").status_code, 400)
        self.assertEqual(audio.line_mode(), "staff")


class ProjectMoneyTests(LineBase):
    def test_spent_counts_the_voice_once(self):
        scene = self.fresh()
        self.render(scene)
        self.voiced(scene)
        body = self.client.get(f"/api/cartoon/projects/{scene.project_id}/").json()
        self.assertEqual(body["credits_spent"], 40)


class DirectorLineTests(LineBase):
    def compose(self, answer, dialogue=LINE):
        scene = self.fresh(dialogue)
        preset = scene.preset
        with patch("cartoon.director._ask", return_value=answer) as ask:
            data = director.compose(scene, self.hero, preset, 5)
        return data, ask.call_args.args[0]

    def test_system_prompt_places_the_line_and_forbids_music(self):
        for words in ("0.5-1 second", "no background music, quiet ambient sound only", "line_is_speech",
                      "кандайсыз тая ата тай эне", "Он герой играет", '"voice"'):
            self.assertIn(words, director._SYSTEM)

    def test_budget_is_in_characters(self):
        _data, payload = self.compose({"prompt": "p"})
        self.assertIn("about 65 characters", payload)
        self.assertIn(f"{len(LINE)} characters", payload)

    def test_doubt_means_speech(self):
        self.assertTrue(self.compose({"prompt": "p"})[0]["line_is_speech"])
        self.assertTrue(self.compose({"prompt": "p", "line_is_speech": "maybe"})[0]["line_is_speech"])
        self.assertFalse(self.compose({"prompt": "p", "line_is_speech": False})[0]["line_is_speech"])
        self.assertFalse(self.compose({"prompt": "p", "line_is_speech": "false"})[0]["line_is_speech"])

    def test_voice_hint_is_cleaned(self):
        self.assertEqual(self.compose({"prompt": "p", "voice": {"gender": "Female", "age": "child"}})[0]["voice"],
                         {"gender": "female", "age": "child", "lang": "other"})
        self.assertEqual(self.compose({"prompt": "p", "voice": {"gender": "robot", "age": 5}})[0]["voice"],
                         {"lang": "other"})
        self.assertEqual(self.compose({"prompt": "p", "voice": "female"})[0]["voice"], {"lang": "other"})

    def test_description_cannot_stay_in_the_audio_part(self):
        """Режиссёр ответил «описание», но слова в промпт вписал: их прочла бы модель."""
        prompt = f'Hero walks. Audio: The character says: "{DESCRIPTION}" with natural lip sync. Birds sing.'
        data, _ = self.compose({"prompt": prompt, "line_is_speech": False}, DESCRIPTION)
        self.assertNotIn(DESCRIPTION, data["prompt"])
        self.assertNotIn("says", data["prompt"])
        self.assertIn("Birds sing.", data["prompt"])
        self.assertIn("Nobody speaks", data["prompt"])

    def test_description_retold_by_the_model_goes_too(self):
        data, _ = self.compose({"prompt": 'Hero walks. The character says: "Он ищет маму. Потом плачет." with lip sync. Rain.',
                                "line_is_speech": False}, DESCRIPTION)
        self.assertNotIn("ищет маму", data["prompt"])
        self.assertIn("Rain.", data["prompt"])

    def test_clean_prompt_is_left_alone(self):
        data, _ = self.compose({"prompt": "Hero walks. Nobody speaks, ambient only.", "line_is_speech": False},
                               DESCRIPTION)
        self.assertEqual(data["prompt"], "Hero walks. Nobody speaks, ambient only.")

    def test_fallback_treats_the_text_as_speech_without_music(self):
        scene = self.fresh()
        data = director.fallback(scene, self.hero, scene.preset, 5)
        self.assertTrue(data["line_is_speech"])
        self.assertEqual(data["voice"], {})
        self.assertIn("no background music", data["prompt"])
        self.assertIn(LINE, data["prompt"])

    def test_decision_is_cached_with_the_prompt(self):
        scene = self.fresh(DESCRIPTION)
        with patch("cartoon.director._ask", return_value={"prompt": "p", "line_is_speech": False,
                                                          "voice": {"gender": "male"}}) as ask:
            director.ensure_video_prompt(scene, self.hero, scene.preset, 5)
            director.ensure_video_prompt(scene, self.hero, scene.preset, 5)
        self.assertEqual(ask.call_count, 1)
        scene.refresh_from_db()
        self.assertFalse(scene.dialogue_is_speech)
        self.assertEqual(scene.voice_hint, {"gender": "male", "lang": "other"})


class TtsTests(TestCase):
    def _post(self, *statuses):
        answers = [SimpleNamespace(status_code=s, content=b"mp3", text="x") for s in statuses]
        return patch("cartoon.audio.requests.post", side_effect=answers)

    @override_settings(ELEVENLABS_API_KEY="k", ELEVENLABS_TTS_MODEL="eleven_multilingual_v2")
    def test_russian_goes_to_the_usual_model(self):
        with self._post(200) as post:
            audio.tts("Привет, мир", "v1")
        self.assertEqual(post.call_args.kwargs["json"], {"text": "Привет, мир",
                                                         "model_id": "eleven_multilingual_v2"})

    def test_kyrgyz_is_recognised_in_any_case(self):
        self.assertEqual(audio.line_lang("Менин атым Жылдыз, өзүң кандайсың"), "ky")
        self.assertEqual(audio.line_lang("ҮЙГӨ КЕЛ"), "ky")
        self.assertEqual(audio.line_lang("кандайсыз тая ата тай эне"), "")
        self.assertEqual(audio.line_lang(""), "")

    @override_settings(ELEVENLABS_API_KEY="k", ELEVENLABS_KY_MODEL="eleven_v3")
    def test_kyrgyz_goes_to_v3_with_language(self):
        with self._post(200) as post:
            audio.tts("Өзүң кандайсың", "v1")
        body = post.call_args.kwargs["json"]
        self.assertEqual((body["model_id"], body["language_code"]), ("eleven_v3", "ky"))

    @override_settings(ELEVENLABS_API_KEY="k", ELEVENLABS_KY_MODEL="eleven_v3",
                       ELEVENLABS_TTS_MODEL="eleven_multilingual_v2")
    def test_refused_v3_falls_back_to_the_usual_model_without_language(self):
        with self._post(400, 200) as post:
            self.assertEqual(audio.tts("Өзүң кандайсың", "v1"), b"mp3")
        self.assertEqual(post.call_count, 2)
        self.assertEqual(post.call_args.kwargs["json"], {"text": "Өзүң кандайсың",
                                                         "model_id": "eleven_multilingual_v2"})

    @override_settings(ELEVENLABS_API_KEY="k", ELEVENLABS_KY_MODEL="eleven_v3")
    def test_server_error_is_not_retried(self):
        with self._post(500, 200) as post, self.assertRaises(audio.AudioProviderError) as caught:
            audio.tts("Өзүң кандайсың", "v1")
        self.assertEqual(post.call_count, 1)
        self.assertEqual(caught.exception.status, 500)

    @override_settings(ELEVENLABS_API_KEY="k", ELEVENLABS_KY_MODEL="")
    def test_empty_setting_turns_v3_off(self):
        with self._post(200) as post:
            audio.tts("Өзүң кандайсың", "v1")
        self.assertNotIn("language_code", post.call_args.kwargs["json"])

    @override_settings(ELEVENLABS_API_KEY="k")
    def test_explicit_model_language_and_speed_win(self):
        with self._post(200) as post:
            audio.tts("Өзүң", "v1", model="m", language_code="ru", speed=1.1)
        self.assertEqual(post.call_args.kwargs["json"], {"text": "Өзүң", "model_id": "m", "language_code": "ru",
                                                         "voice_settings": {"speed": 1.1}})

    def test_bad_voice_id_never_reaches_the_provider(self):
        with self._post(200) as post, self.assertRaises(audio.AudioProviderError):
            audio.tts("Привет", "../../v1/user")
        self.assertEqual(post.call_count, 0)


class ReviewMoneyTests(LineApiTests):
    """Находки ревью F30: двойная оплата, резервы, журнал, мягкий лимит."""

    def line_call(self, scene, *, charge_ok=True, **kw):
        with patch("cartoon.audio.tts", kw.pop("tts", MagicMock(return_value=b"mp3"))), \
             patch("cartoon.audio.save_audio", return_value=(LINE_FILE, 2.0)), \
             patch("cartoon.audio.scene_window", return_value=(1.0, 3.0)), \
             patch("cartoon.audio.mix_scene", MagicMock(side_effect=_place)), \
             patch("django.core.files.storage.default_storage.delete"):
            return voiceover.voice_line(scene, LINE, "voice-f1", "Bella", self.hero, line=True, **kw)

    def test_card_button_during_voice_all_is_not_paid_twice(self):
        scene = self.ready(voice_hint=SPEECH["voice"])

        def rival_voices_first(*a, **kw):
            CartoonAudioTrack.objects.create(scene=scene, kind="line", text=LINE, voice_id="voice-f1",
                                             file="cartoon/audio/rival.mp3", duration=2.0, credits_spent=5)
            return b"mp3"

        self.assertIsNone(self.line_call(scene, tts=MagicMock(side_effect=rival_voices_first)))
        self.assertEqual(self.charges("cartoon_voice"), [])
        self.assertEqual(self.line_row(scene).get().file, "cartoon/audio/rival.mp3")
        self.assertEqual(self.voice_log(scene).get().status, GenerationLog.STATUS_LOST)

    def test_post_during_voice_all_is_not_paid_twice(self):
        scene = self.ready(voice_hint=SPEECH["voice"])

        def rival_voices_first(*a, **kw):
            CartoonAudioTrack.objects.create(scene=scene, kind="line", text=LINE, voice_id="voice-f1",
                                             file="cartoon/audio/rival.mp3", duration=2.0, credits_spent=5)
            return b"mp3"

        response = self.post(scene, tts=MagicMock(side_effect=rival_voices_first))
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(self.charges("cartoon_voice"), [])
        self.assertIn("scene", response.json())
        self.assertEqual(self.voice_log(scene).get().status, GenerationLog.STATUS_LOST)

    def test_voice_all_leaves_the_reserve_of_a_running_shot(self):
        scene = self.ready(voice_hint=SPEECH["voice"])
        from plans.wallet import InsufficientTokens

        with patch("cartoon.services.charge_tokens", side_effect=InsufficientTokens("мало")) as charge:
            with self.assertRaises(InsufficientTokens):
                self.line_call(scene)
        self.assertTrue(charge.call_args.kwargs["respect_reserves"])
        self.assertFalse(self.line_row(scene).exists())
        self.assertEqual(self.voice_log(scene).get().status, GenerationLog.STATUS_LOST)

    def test_voice_all_is_in_the_journal(self):
        scene = self.ready(voice_hint=SPEECH["voice"])
        self.line_call(scene)
        row = self.voice_log(scene).get()
        self.assertEqual((row.status, row.credits_charged), (GenerationLog.STATUS_DELIVERED, 5))

    def test_failed_voice_all_is_in_the_journal(self):
        scene = self.ready(voice_hint=SPEECH["voice"])
        with self.assertRaises(audio.AudioProviderError):
            self.line_call(scene, tts=MagicMock(side_effect=audio.AudioProviderError("http 500", status=500)))
        self.assertEqual(self.voice_log(scene).get().status, GenerationLog.STATUS_FAILED)
        self.assertEqual(self.charges("cartoon_voice"), [])

    def test_soft_limit_after_the_draft_means_no_charge(self):
        from celery.exceptions import SoftTimeLimitExceeded

        scene = self.fresh(shot_voice_credits=5)
        scene.video = "cartoon/scenes/v.mp4"
        beats = []

        def beat():
            beats.append(1)
            if len(beats) == 4:
                raise SoftTimeLimitExceeded()

        line = voiceover.RenderLine(scene, self.hero, 0)
        with patch("cartoon.audio.tts", return_value=b"mp3"), \
             patch("cartoon.audio.save_audio", return_value=(LINE_FILE, 2.0)), \
             patch("cartoon.audio.scene_window", return_value=(1.0, 3.0)), \
             patch("cartoon.audio.mix_scene", MagicMock(side_effect=_place)), \
             patch("cartoon.audio.list_voices", return_value=VOICES), \
             patch("django.core.files.storage.default_storage.delete") as delete:
            line.prepare(beat)
            line.commit()
            line.finish()
        self.assertEqual(line.paid, 0)
        self.assertIsNone(line.draft)
        self.assertEqual(self.charges("cartoon_voice"), [])
        self.assertTrue(delete.called)

    def test_storage_error_on_drop_does_not_spoil_the_scene(self):
        track = SimpleNamespace(file=LINE_FILE)
        draft = voiceover.LineDraft(SimpleNamespace(pk=1), track, MIXED)
        with patch("django.core.files.storage.default_storage.delete", side_effect=OSError("диск")) as delete:
            draft.drop()
        self.assertEqual(delete.call_count, 2)

    def test_window_failure_is_in_the_journal(self):
        scene = self.fresh(shot_voice_credits=5)
        scene.video = "cartoon/scenes/v.mp4"
        with patch("cartoon.audio.scene_window", side_effect=OSError("диск")):
            voiceover.RenderLine(scene, self.hero, 0).prepare()
        self.assertEqual(self.voice_log(scene).get().status, GenerationLog.STATUS_FAILED)

    def test_new_hero_does_not_inherit_a_paid_voice(self):
        other = CartoonCharacter.objects.create(name="Пёс", image="cartoon/characters/o.png", is_public=True)
        scene = self.fresh(status=CartoonScene.STATUS_FAILED)
        CartoonAudioTrack.objects.create(scene=scene, kind="line", text=LINE, voice_id="voice-f1",
                                         character=self.hero, file=LINE_FILE, duration=2.0)
        response = _client(self.user).patch(f"/api/cartoon/scenes/{scene.pk}/", {"character_id": other.pk},
                                            format="json")
        self.assertEqual(response.status_code, 200, response.content)
        self.assertFalse(self.line_row(scene).exists())

    def test_going_back_to_the_voice_of_the_scene_pins_it(self):
        scene = self.ready(voice_hint=SPEECH["voice"])
        self.post(scene)
        self.project_of(scene).hero_voices = {str(self.hero.pk): {"voice_id": "voice-m1", "voice_name": "George"}}
        self.project_of(scene).save(update_fields=["hero_voices"])
        response = self.post(scene, {"voice_id": "voice-f1"})
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.json()["hero_voices"][str(self.hero.pk)]["voice_id"], "voice-f1")
        self.assertEqual(self.charges("cartoon_voice"), [5])

    def project_of(self, scene):
        return scene.project

    def test_voice_chosen_in_the_plan_is_pinned(self):
        scene = self.ready(voice_hint=SPEECH["voice"])
        project = scene.project
        project.hero_voices = {str(self.hero.pk): {"voice_id": "voice-f2", "voice_name": "Lily"}}
        project.save(update_fields=["hero_voices"])
        plan = [{"scene_id": scene.pk, "text": LINE, "voice_id": "voice-f1", "voice_name": "Bella", "line": True}]
        with patch("cartoon.audio.tts", return_value=b"mp3"), \
             patch("cartoon.audio.save_audio", return_value=(LINE_FILE, 2.0)), \
             patch("cartoon.audio.scene_window", return_value=(1.0, 3.0)), \
             patch("cartoon.audio.mix_scene", MagicMock(side_effect=_place)):
            voiceover.voice_project(project, plan)
        project.refresh_from_db()
        self.assertEqual(project.hero_voices[str(self.hero.pk)]["voice_id"], "voice-f1")
        scene = CartoonScene.objects.get(pk=scene.pk)
        self.assertEqual(cp.line_voice_credits(scene), 0)

    def plan_item(self, scene, text=LINE, voice_id="voice-f1"):
        return {"scene_id": scene.pk, "text": text, "voice_id": voice_id, "voice_name": "Bella", "line": True}

    def run_plan(self, project, plan):
        tts = MagicMock(return_value=b"mp3")
        with patch("cartoon.audio.tts", tts), \
             patch("cartoon.audio.save_audio", return_value=(LINE_FILE, 2.0)), \
             patch("cartoon.audio.scene_window", return_value=(1.0, 3.0)), \
             patch("cartoon.audio.mix_scene", MagicMock(side_effect=_place)):
            return voiceover.voice_project(project, plan), tts

    def test_queued_run_does_not_undo_a_voice_chosen_on_the_card(self):
        scene = self.ready(voice_hint=SPEECH["voice"])
        self.post(scene, {"voice_id": "voice-m1"})
        result, tts = self.run_plan(scene.project, [self.plan_item(scene)])
        self.assertEqual((result["done"], tts.call_count), (0, 0))
        self.assertEqual(self.charges("cartoon_voice"), [5])
        self.assertEqual(self.line_row(scene).get().voice_id, "voice-m1")
        scene.project.refresh_from_db()
        self.assertEqual(scene.project.hero_voices[str(self.hero.pk)]["voice_id"], "voice-m1")

    def test_queued_run_does_not_undo_new_words(self):
        scene = self.ready(voice_hint=SPEECH["voice"])
        CartoonScene.objects.filter(pk=scene.pk).update(dialogue="Новые слова")
        scene.refresh_from_db()
        result, tts = self.run_plan(scene.project, [self.plan_item(scene, LINE)])
        self.assertEqual((result["done"], tts.call_count), (0, 0))
        self.assertEqual(self.charges("cartoon_voice"), [])

    def test_queued_run_does_not_read_a_new_description(self):
        scene = self.ready(voice_hint=SPEECH["voice"])
        CartoonScene.objects.filter(pk=scene.pk).update(dialogue_is_speech=False)
        result, tts = self.run_plan(scene.project, [self.plan_item(scene)])
        self.assertEqual((result["done"], tts.call_count), (0, 0))

    def test_old_description_is_refused_by_the_button_without_money(self):
        scene = self.ready(dialogue=DESCRIPTION)
        answer = {"lines": [{"n": 1, "line_is_speech": False, "line_lang": "other", "voice": {}}]}
        with patch("cartoon.director._ask_lines", return_value=answer):
            response = self.post(scene)
        self.assertEqual(response.status_code, 400, response.content)
        self.assertEqual(response.json()["error_code"], "not_speech")
        self.assertEqual((self.tts.call_count, self.charges("cartoon_voice")), (0, []))

    def test_old_kyrgyz_line_goes_to_the_kyrgyz_model_from_the_button(self):
        scene = self.ready(dialogue="кандайсыз тая ата тай эне")
        answer = {"lines": [{"n": 1, "line_is_speech": True, "line_lang": "ky", "voice": {"gender": "female"}}]}
        with patch("cartoon.director._ask_lines", return_value=answer):
            response = self.post(scene)
        self.assertEqual(response.status_code, 201, response.content)
        self.assertEqual(self.tts.call_args.kwargs["lang"], "ky")

    def test_judged_scene_is_not_asked_again(self):
        scene = self.ready(voice_hint={**SPEECH["voice"], "lang": "other"})
        self.post(scene)
        self.assertEqual(self.ask_lines.call_count, 0)

    def test_words_added_to_a_shot_scene_go_to_the_director(self):
        """Режиссёр дал пол и возраст ещё без реплики: слова он при этом не читал."""
        scene = self.ready(dialogue="", voice_hint={"gender": "male", "age": "child"})
        patched = _client(self.user).patch(f"/api/cartoon/scenes/{scene.pk}/", {"dialogue": DESCRIPTION}, format="json")
        self.assertEqual(patched.status_code, 200, patched.content)
        answer = {"lines": [{"n": 1, "line_is_speech": False, "line_lang": "other", "voice": {}}]}
        with patch("cartoon.director._ask_lines", return_value=answer) as ask:
            response = self.post(scene)
        self.assertEqual(ask.call_count, 1)
        self.assertEqual(response.status_code, 400, response.content)
        self.assertEqual((self.tts.call_count, self.charges("cartoon_voice")), (0, []))
        scene.refresh_from_db()
        self.assertEqual(scene.voice_hint, {"gender": "male", "age": "child", "lang": "other"})

    def test_same_words_with_a_stray_space_keep_the_decision(self):
        scene = self.ready(dialogue=DESCRIPTION, dialogue_is_speech=False, voice_hint={"lang": "other"})
        CartoonScene.objects.filter(pk=scene.pk).update(video_prompt="p")
        body = {"dialogue": DESCRIPTION.replace(" ", "  ", 1)}
        response = _client(self.user).patch(f"/api/cartoon/scenes/{scene.pk}/", body, format="json")
        self.assertEqual(response.status_code, 200, response.content)
        scene.refresh_from_db()
        self.assertEqual((scene.dialogue_is_speech, scene.video_prompt, scene.voice_hint),
                         (False, "p", {"lang": "other"}))

    def test_voice_changed_during_the_run_stays_the_voice_of_the_hero(self):
        project = self.project(model=MINI, resolution="480p", duration=5)
        first = self.scene(project, dialogue=LINE, status=CartoonScene.STATUS_READY, video="v/1.mp4",
                           voice_hint={"lang": "other"})
        second = self.scene(project, dialogue="Другие слова", status=CartoonScene.STATUS_READY, video="v/2.mp4",
                            voice_hint={"lang": "other"})
        plan = [self.plan_item(first), self.plan_item(second, "Другие слова")]

        def on_the_way(text, voice_id, **kw):
            # Пока идёт первая реплика, человек сменил голос героя на карточке.
            if text == LINE:
                voiceover.set_hero_voice(project, self.hero, {"voice_id": "voice-m1", "voice_name": "George"})
            return b"mp3"

        with patch("cartoon.audio.tts", side_effect=on_the_way), \
             patch("cartoon.audio.save_audio", return_value=(LINE_FILE, 2.0)), \
             patch("cartoon.audio.scene_window", return_value=(1.0, 3.0)), \
             patch("cartoon.audio.mix_scene", MagicMock(side_effect=_place)):
            voiceover.voice_project(project, plan)
        project.refresh_from_db()
        self.assertEqual(project.hero_voices[str(self.hero.pk)]["voice_id"], "voice-m1")

    def test_erased_line_does_not_get_a_second_voice_from_the_plan(self):
        scene = self.ready(dialogue="", voice_hint={"lang": "other"})
        CartoonAudioTrack.objects.create(scene=scene, kind="line", text="Прежние слова", voice_id="voice-f1",
                                         file=LINE_FILE, duration=2.0)
        with patch("cartoon.voiceover.write_lines", return_value={1: "Новые слова"}) as writer, \
             patch("cartoon.audio.list_voices", return_value=VOICES):
            plan = voiceover.build_plan(scene.project)
        self.assertEqual(plan["lines"], [])
        self.assertEqual(writer.call_count, 0)

    def test_plan_judges_old_scenes_in_one_call(self):
        project = self.project(model=MINI, resolution="480p", duration=5)
        first = self.scene(project, dialogue=DESCRIPTION, status=CartoonScene.STATUS_READY, video="v/1.mp4")
        second = self.scene(project, dialogue=LINE, status=CartoonScene.STATUS_READY, video="v/2.mp4")
        answer = {"lines": [{"n": 1, "line_is_speech": False, "line_lang": "other", "voice": {}},
                            {"n": 2, "line_is_speech": True, "line_lang": "other", "voice": {}}]}
        with patch("cartoon.director._ask_lines", return_value=answer) as ask, \
             patch("cartoon.audio.list_voices", return_value=VOICES):
            plan = voiceover.build_plan(project)
        self.assertEqual(ask.call_count, 1)
        self.assertEqual(plan["descriptions"], 1)
        self.assertEqual([l["scene_id"] for l in plan["lines"]], [second.pk])
        self.assertNotEqual(first.pk, second.pk)

    def empty_plan(self, scene):
        with patch("cartoon.audio.list_voices", return_value=VOICES):
            return _client(self.user).post(f"/api/cartoon/projects/{scene.project_id}/voice-plan/", {}, format="json")

    def test_empty_plan_says_why(self):
        for fields, code in (({"status": CartoonScene.STATUS_DRAFT, "video": ""}, "unshot"),
                             ({"status": CartoonScene.STATUS_VIDEO}, "working"),
                             ({"status": CartoonScene.STATUS_READY, "dialogue_is_speech": False}, "descriptions")):
            scene = self.fresh(voice_hint={"lang": "other"}, video="v/1.mp4", **{"status": CartoonScene.STATUS_READY})
            CartoonScene.objects.filter(pk=scene.pk).update(**fields)
            response = self.empty_plan(scene)
            self.assertEqual((response.status_code, response.json().get("error_code")), (400, code), fields)

    def test_failed_new_voice_still_moves_the_old_line_to_the_new_window(self):
        scene = self.ready(voice_hint=SPEECH["voice"])
        self.post(scene)
        CartoonScene.objects.filter(pk=scene.pk).update(shot_voice_credits=5)
        scene.refresh_from_db()
        project = scene.project
        project.hero_voices = {str(self.hero.pk): {"voice_id": "voice-m1", "voice_name": "George"}}
        project.save(update_fields=["hero_voices"])
        line = voiceover.RenderLine(scene, self.hero, 0)
        with patch("cartoon.audio.tts", side_effect=audio.AudioProviderError("http 500", status=500)), \
             patch("cartoon.audio.scene_window", return_value=(4.0, 6.0)), \
             patch("cartoon.audio.mix_scene", MagicMock(side_effect=_place)):
            line.prepare()
            line.commit()
            line.finish()
        track = self.line_row(scene).get()
        self.assertEqual((track.voice_id, track.start_sec), ("voice-f1", 4.0))
        self.assertEqual(scene.mixed_video, MIXED)
        self.assertEqual(self.charges("cartoon_voice"), [5])

    def test_button_repairs_a_line_that_is_not_mixed(self):
        scene = self.ready(voice_hint=SPEECH["voice"])
        self.post(scene)
        CartoonScene.objects.filter(pk=scene.pk).update(mixed_video="")
        scene.refresh_from_db()
        response = self.post(scene)
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(self.tts.call_count, 0)
        self.assertEqual(self.mix.call_count, 1)
        self.assertEqual(self.charges("cartoon_voice"), [5])

    def test_unexpected_charge_failure_costs_nothing_and_is_journalled(self):
        scene = self.ready(voice_hint=SPEECH["voice"])
        with patch("cartoon.services.charge_tokens", side_effect=RuntimeError("база")):
            response = self.post(scene)
        self.assertEqual(response.status_code, 502, response.content)
        self.assertFalse(self.line_row(scene).exists())
        self.assertIn(LINE_FILE, self.dropped)

    def test_guest_sees_the_voice_in_the_price_only_when_it_is_on(self):
        self.assertTrue(_client(self.user).get("/api/cartoon/audio/config/").json()["line_voice"])
        set_runtime(audio.LINE_MODE_KEY, "staff")
        self.addCleanup(set_runtime, audio.LINE_MODE_KEY, "on")
        self.assertFalse(_client(self.user).get("/api/cartoon/audio/config/").json()["line_voice"])


class ReviewDirectorTests(LineBase):
    """Находки ревью F30: режиссёр и выбор голоса."""

    def ensure(self, scene, answer=None, *, judge=True, fail=False):
        side = {"side_effect": director.DirectorFailed("http 500")} if fail else {"return_value": answer or SPEECH}
        with patch("cartoon.director._ask", **side) as ask:
            data = director.ensure_video_prompt(scene, self.hero, scene.preset, 5, judge=judge)
        return data, ask

    def test_old_scene_is_judged_at_the_reshoot(self):
        scene = self.fresh(DESCRIPTION, video_prompt=f'The character says: "{DESCRIPTION}"')
        data, ask = self.ensure(scene, {"prompt": "A boy looks around.", "line_is_speech": False,
                                        "line_lang": "other", "voice": {"gender": "male"}})
        self.assertEqual(ask.call_count, 1)
        self.assertFalse(data["line_is_speech"])
        scene.refresh_from_db()
        self.assertFalse(scene.dialogue_is_speech)
        self.assertNotIn(DESCRIPTION, scene.video_prompt)

    def test_judged_scene_stays_cached(self):
        scene = self.fresh(video_prompt="p", voice_hint={"lang": "other"})
        _data, ask = self.ensure(scene)
        self.assertEqual(ask.call_count, 0)

    def test_failed_director_keeps_the_old_prompt(self):
        scene = self.fresh(video_prompt="старый", dialogue_is_speech=False)
        data, _ask = self.ensure(scene, fail=True)
        self.assertEqual(data["prompt"], "старый")
        scene.refresh_from_db()
        self.assertEqual((scene.video_prompt, scene.dialogue_is_speech), ("старый", False))

    def test_scene_without_a_line_is_not_judged_again(self):
        scene = self.fresh("", video_prompt="p")
        _data, ask = self.ensure(scene)
        self.assertEqual(ask.call_count, 0)

    def test_off_never_turns_a_line_into_a_description(self):
        scene = self.fresh("Он украл мою игрушку!")
        data, ask = self.ensure(scene, {"prompt": 'p', "line_is_speech": False}, judge=False)
        self.assertTrue(data["line_is_speech"])
        self.assertIn("line_is_speech must be true", ask.call_args.args[0])

    def test_off_keeps_the_cache(self):
        scene = self.fresh(video_prompt="p")
        _data, ask = self.ensure(scene, judge=False)
        self.assertEqual(ask.call_count, 0)

    def test_shoot_passes_the_mode_to_the_director(self):
        set_runtime(audio.LINE_MODE_KEY, "off")
        self.addCleanup(set_runtime, audio.LINE_MODE_KEY, "on")
        scene = self.fresh("Он украл мою игрушку!")
        self.voiced(scene, director_answer=NOT_SPEECH)
        scene.refresh_from_db()
        self.assertTrue(scene.dialogue_is_speech)

    def test_any_form_of_speech_leaves_the_prompt(self):
        for form in (f'The character says, "{DESCRIPTION}".', f'She says softly: "{DESCRIPTION}".',
                     f'The hero speaks: "{DESCRIPTION}".', f'Saying "{DESCRIPTION}" with lip sync.',
                     f'Audio: voice-over reads «{DESCRIPTION}». Natural lip sync, calm audible speech.'):
            cleaned = director._unsaid(f"Hero walks to the door. {form} Birds sing.")
            self.assertNotIn("Он герой", cleaned, form)
            self.assertIn("Hero walks to the door.", cleaned)
            self.assertIn("Birds sing.", cleaned)
            self.assertIn("Nobody speaks", cleaned)

    def test_action_with_the_same_words_stays(self):
        text = "0-2s He plays then looks for his mother with worried eyes"
        self.assertIn(text, director._unsaid(text))

    def test_multi_sentence_quote_leaves_as_a_whole(self):
        cleaned = director._unsaid('Hero waits. The character says: "Раз. Два. Три." Birds sing.')
        self.assertNotIn("Два", cleaned)

    def test_beats_in_one_sentence_with_speech_keep_the_action(self):
        prompt = (f'Slow push in on the small fox, 0-2s it plays with a red ball, 2-4s it looks around for its '
                  f'mother and says: "{DESCRIPTION}", 4-5s tears roll down and it sits on the grass.')
        cleaned = director._unsaid(prompt)
        self.assertNotIn("Он герой", cleaned)
        self.assertNotIn("says", cleaned)
        for words in ("0-2s it plays with a red ball", "2-4s it looks around for its mother",
                      "4-5s tears roll down and it sits on the grass"):
            self.assertIn(words, cleaned)
        self.assertIn("Nobody speaks", cleaned)

    def test_description_without_quotes_leaves_the_prompt(self):
        for label in ("Audio:", "Voice:", "The fox whispers"):
            cleaned = director._unsaid(f"0-2s fox looks around. {label} {DESCRIPTION}. Soft wind.")
            self.assertNotIn("Он герой", cleaned, label)
            self.assertIn("0-2s fox looks around.", cleaned)
            self.assertIn("Soft wind.", cleaned)

    def test_cyrillic_is_cut_inside_a_beat(self):
        cleaned = director._unsaid(f"0-2s fox runs, 2-4s {DESCRIPTION}, 4-5s fox sits.")
        self.assertNotIn("Он герой", cleaned)
        self.assertIn("0-2s fox runs", cleaned)
        self.assertIn("4-5s fox sits", cleaned)

    def test_action_of_the_scene_returns_when_nothing_is_left(self):
        cleaned = director._unsaid(f'The character says: "{DESCRIPTION}".', "Fox looks for its mother.")
        self.assertTrue(cleaned.startswith("Fox looks for its mother."), cleaned)
        self.assertIn("Nobody speaks", cleaned)

    def test_off_gives_back_a_line_the_director_called_a_description(self):
        scene = self.fresh("Он украл мою игрушку!", video_prompt="Fox runs. Nobody speaks, ambient sound only.",
                           dialogue_is_speech=False, voice_hint={"lang": "other"})
        answer = {"prompt": 'Fox says: "Он украл мою игрушку!"', "line_is_speech": False}
        data, ask = self.ensure(scene, answer, judge=False)
        self.assertEqual(ask.call_count, 1)
        self.assertTrue(data["line_is_speech"])
        scene.refresh_from_db()
        self.assertTrue(scene.dialogue_is_speech)
        self.assertIn("Он украл", scene.video_prompt)

    def test_off_gives_back_the_line_even_without_the_director(self):
        scene = self.fresh("Он украл мою игрушку!", video_prompt="Fox runs. Nobody speaks, ambient sound only.",
                           dialogue_is_speech=False, voice_hint={"lang": "other"})
        data, _ask = self.ensure(scene, judge=False, fail=True)
        self.assertIn("Он украл", data["prompt"])
        scene.refresh_from_db()
        self.assertTrue(scene.dialogue_is_speech)

    def test_scene_shot_while_off_is_judged_after_on(self):
        scene = self.fresh(DESCRIPTION)
        self.ensure(scene, SPEECH, judge=False)
        scene.refresh_from_db()
        self.assertEqual(scene.voice_hint, {})
        _data, ask = self.ensure(scene, {**NOT_SPEECH, "prompt": "Boy looks around."})
        self.assertEqual(ask.call_count, 1)
        scene.refresh_from_db()
        self.assertFalse(scene.dialogue_is_speech)

    def test_off_allows_music_for_the_voice_of_the_model(self):
        scene = self.fresh(LINE)
        _data, ask = self.ensure(scene, judge=False)
        self.assertIn("background music is allowed", ask.call_args.args[0])

    def judge(self, scene, answer):
        with patch("cartoon.director._ask_lines", return_value=answer) as ask:
            director.judge_lines([scene])
        scene.refresh_from_db()
        return ask

    def test_old_description_is_found_and_leaves_the_prompt(self):
        scene = self.fresh(DESCRIPTION, video_prompt=f'0-2s boy runs. The character says: "{DESCRIPTION}".')
        ask = self.judge(scene, {"lines": [{"n": 1, "line_is_speech": False, "line_lang": "other",
                                            "voice": {"gender": "male"}}]})
        self.assertIn(DESCRIPTION, ask.call_args.args[0])
        self.assertFalse(scene.dialogue_is_speech)
        self.assertEqual(scene.voice_hint, {"gender": "male", "lang": "other"})
        self.assertNotIn("Он герой", scene.video_prompt)
        self.assertIn("0-2s boy runs.", scene.video_prompt)

    def test_twelve_lines_fit_into_one_request(self):
        project = self.project(model=MINI, resolution="480p", duration=5)
        scenes = [self.scene(project, dialogue=f"Реплика номер {i} " + "и ещё слова " * 18) for i in range(12)]
        self.hero.description = "a very long description of the hero " * 30
        self.hero.save(update_fields=["description"])
        for scene in scenes:
            scene.refresh_from_db()
        sent = []

        def fake_post(url, json=None, **kw):
            sent.append(json["messages"][1]["content"])
            return MagicMock(status_code=200, json=lambda: {"choices": [{"message": {"content": '{"lines": []}'}}]})

        with patch("cartoon.director._ask_lines", side_effect=lambda payload: director._call(
                director._JUDGE_SYSTEM, payload, max_tokens=100, temperature=0.2, limit=director.JUDGE_LIMIT,
                timeout=director.JUDGE_TIMEOUT)), \
             patch("cartoon.director.requests.post", side_effect=fake_post), \
             patch("ai.handlers._openrouter_config", return_value={"base_url": "http://x", "api_key": "k"}):
            director.judge_lines(scenes)
        self.assertEqual(len(sent), 1)
        for i in range(12):
            self.assertIn(f"Реплика номер {i} ", sent[0])
        self.assertTrue(sent[0].rstrip().endswith('"'))

    def test_check_stops_after_a_failure(self):
        project = self.project(model=MINI, resolution="480p", duration=5)
        scenes = [self.scene(project, dialogue=f"Реплика {i}") for i in range(25)]
        with patch("cartoon.director._ask_lines", side_effect=director.DirectorFailed("тайм-аут")) as ask:
            director.judge_lines(scenes)
        self.assertEqual(ask.call_count, 1)

    def test_explicit_no_counts_even_without_a_voice(self):
        scene = self.fresh(DESCRIPTION)
        self.judge(scene, {"lines": [{"n": 1, "line_is_speech": False}]})
        self.assertFalse(scene.dialogue_is_speech)
        self.assertEqual(scene.voice_hint, {"lang": "other"})

    def test_words_of_speech_inside_an_action_stay(self):
        for text in ("0-2s The boy says nothing and runs to the door, 2-4s he stops.",
                     "0-2s Without saying a word the boy runs to the door and pulls it open, 2-4s he waits.",
                     "0-2s The girl raises her hand to ask a question, 2-4s she smiles.",
                     "0-2s The boy speaks to a vast glowing screen and reaches for the light, 2-4s he turns."):
            self.assertIn(text, director._unsaid(text), text)

    def test_long_dash_in_a_beat_counts_as_a_beat(self):
        cleaned = director._unsaid(f'0–2s fox runs, 2–4s it stops and says: "{DESCRIPTION}", 4–5s it sits.')
        self.assertIn("0–2s fox runs", cleaned)
        self.assertIn("4–5s it sits", cleaned)

    def test_cyrillic_next_to_nobody_speaks_leaves_too(self):
        cleaned = director._unsaid(f"0-2s fox runs. Audio: {DESCRIPTION}, nobody speaks, ambient sound only.")
        self.assertNotIn("Он герой", cleaned)
        self.assertIn("0-2s fox runs.", cleaned)

    def test_beats_without_words_give_way_to_the_action_of_the_scene(self):
        cleaned = director._unsaid("Slow push in. 0-2s Он герой играет, 2-4s потом ищет маму, 4-5s плачет. Warm light.",
                                   "Fox looks for its mother.")
        self.assertIn("Fox looks for its mother.", cleaned)
        self.assertNotIn("0-2s", cleaned)

    def test_failed_director_keeps_a_known_description(self):
        scene = self.fresh(DESCRIPTION, dialogue_is_speech=False, voice_hint={"gender": "male", "lang": "other"})
        data, _ask = self.ensure(scene, fail=True)
        self.assertNotIn("Он герой", data["prompt"])
        self.assertFalse(data["line_is_speech"])
        scene.refresh_from_db()
        self.assertFalse(scene.dialogue_is_speech)
        self.assertEqual(scene.voice_hint, {"gender": "male", "lang": "other"})

    def test_old_kyrgyz_line_gets_its_language(self):
        scene = self.fresh("кандайсыз тая ата тай эне")
        self.judge(scene, {"lines": [{"n": 1, "line_is_speech": True, "line_lang": "ky", "voice": {}}]})
        self.assertTrue(scene.dialogue_is_speech)
        self.assertEqual(scene.voice_hint, {"lang": "ky"})

    def test_failed_check_leaves_the_scene_alone(self):
        scene = self.fresh(DESCRIPTION)
        with patch("cartoon.director._ask_lines", side_effect=director.DirectorFailed("http 500")):
            director.judge_lines([scene])
        scene.refresh_from_db()
        self.assertTrue(scene.dialogue_is_speech)
        self.assertEqual(scene.voice_hint, {})

    def test_strange_answers_do_not_break_the_check(self):
        scene = self.fresh(DESCRIPTION)
        for answer in ({"lines": "нет"}, {"lines": [1, {"n": "x"}, {"n": 0}, {"n": 9}]}, {}):
            self.judge(scene, answer)
        self.assertEqual(scene.voice_hint, {})

    def test_line_language_comes_from_the_director(self):
        answer = {"prompt": "p", "line_lang": "ky", "voice": {"gender": "female"}}
        scene = self.fresh("кандайсыз тая ата тай эне")
        data, _ask = self.ensure(scene, answer)
        self.assertEqual(data["voice"], {"gender": "female", "lang": "ky"})

    def test_kyrgyz_without_special_letters_goes_to_the_kyrgyz_model(self):
        scene = self.fresh("кандайсыз тая ата тай эне", voice_hint={"lang": "ky"}, video_prompt="p")
        self.render(scene)
        self.voiced(scene)
        self.assertEqual(self.tts.call_args.kwargs["lang"], "ky")

    def test_new_words_forget_the_language_of_the_old_ones(self):
        scene = self.fresh("кандайсыз тая", voice_hint={"lang": "ky", "gender": "female"}, video_prompt="p")
        response = _client(self.user).patch(f"/api/cartoon/scenes/{scene.pk}/", {"dialogue": "Привет, мама!"},
                                            format="json")
        self.assertEqual(response.status_code, 200, response.content)
        scene.refresh_from_db()
        self.assertEqual(scene.voice_hint, {"gender": "female"})

    def test_unknown_gender_is_dropped(self):
        self.assertEqual(director._voice_hint({"gender": "unknown", "age": "child"}), {"age": "child"})

    def test_hero_name_helps_with_the_voice(self):
        scene = self.fresh(LINE)
        hero = SimpleNamespace(description="", name="Жылдыз")
        with patch("cartoon.director._ask", return_value=SPEECH) as ask:
            director.compose(scene, hero, scene.preset, 5)
        self.assertIn("Жылдыз", ask.call_args.args[0])

    def test_description_gives_the_gender(self):
        girl = SimpleNamespace(description="a little girl in a pink knitted hat")
        self.assertEqual(voiceover.description_hint(girl), {"gender": "female", "age": "child"})
        self.assertEqual(voiceover.description_hint(SimpleNamespace(description="an old man with a cane")),
                         {"gender": "male", "age": "old"})
        self.assertEqual(voiceover.description_hint(SimpleNamespace(description="бабушка в платке")),
                         {"gender": "female", "age": "old"})
        self.assertEqual(voiceover.description_hint(SimpleNamespace(description="a ginger cat")), {})
        # «woman» не содержит мужского слова как отдельного, «female» — тоже.
        self.assertEqual(voiceover.description_hint(SimpleNamespace(description="a woman, female"))["gender"], "female")

    def test_description_does_not_confuse_age(self):
        for text, hint in (("a 5-year-old boy in a blue hoodie", {"gender": "male", "age": "child"}),
                           ("a little girl in an old-fashioned dress", {"gender": "female", "age": "child"}),
                           ("a seven-year-old girl with pigtails", {"gender": "female", "age": "child"}),
                           ("a boy with an old teddy bear", {"gender": "male", "age": "child"}),
                           ("a 30-year-old woman in a suit", {"gender": "female"}),
                           ("an old woman in a shawl", {"gender": "female", "age": "old"}),
                           ("принцесса в розовом платье", {"gender": "female"}),
                           ("маленькая принцесса", {"gender": "female"}),
                           ("принц на белом коне", {"gender": "male"})):
            self.assertEqual(voiceover.description_hint(SimpleNamespace(description=text)), hint, text)

    def test_old_scene_of_a_girl_gets_a_female_voice_whatever_the_number(self):
        for pk in (100, 101):
            girl = SimpleNamespace(pk=pk, description="a little girl in a pink hat")
            voice = voiceover.pick_voices([girl], VOICES)[pk]
            self.assertIn(voice["voice_id"], ("voice-f1", "voice-f2"), pk)

    def test_hint_of_another_scene_of_the_hero_is_used(self):
        project = self.project(model=MINI, resolution="480p", duration=5)
        self.scene(project, voice_hint={"gender": "female", "age": "young"})
        with patch("cartoon.audio.list_voices", return_value=VOICES):
            voice = voiceover.hero_voice(project, self.hero, {})
        self.assertEqual(voice["voice_id"], "voice-f1")

    def test_old_character_prefers_a_mature_voice(self):
        grandma = SimpleNamespace(pk=102, description="")
        voice = voiceover.pick_voices([grandma], VOICES, hints={102: {"gender": "female", "age": "old"}})[102]
        self.assertEqual(voice["voice_id"], "voice-f2")


def _levels(*spans):
    """Огибающая: [(секунды, dBFS), ...] → значения по окнам 50 мс."""
    out = []
    for seconds, level in spans:
        out += [level] * round(seconds / audio.SPEECH_STEP)
    return out


class WindowTests(SimpleTestCase):
    def test_finds_first_to_last_piece(self):
        levels = _levels((1, -50), (1, -20), (1, -50), (1, -20), (1, -50))
        self.assertEqual(audio.window_from_levels(levels), (1.0, 4.25))

    def test_short_pause_is_one_phrase_and_a_click_is_not_speech(self):
        levels = _levels((1, -50), (1, -20), (0.2, -50), (1, -20), (1.5, -50), (0.1, -20), (1, -50))
        self.assertEqual(audio.window_from_levels(levels), (1.0, 3.45))

    def test_silent_model_has_no_window(self):
        self.assertIsNone(audio.window_from_levels(_levels((5, -60))))
        self.assertIsNone(audio.window_from_levels([]))

    def test_threshold_follows_the_bed_within_limits(self):
        # Фон −30: порог −24 (потолок), а не −16: музыка на −27 речью не считается.
        levels = _levels((3, -30), (1, -27), (1, -18), (3, -30))
        self.assertEqual(audio.window_from_levels(levels), (4.0, 5.25))
        # Цифровая тишина: порог −45 (пол), а не −106.
        levels = _levels((3, -120), (1, -50), (1, -30), (3, -120))
        self.assertEqual(audio.window_from_levels(levels), (4.0, 5.25))

    def test_tail_of_a_vowel_is_inside_the_window(self):
        """Голос стихает ниже порога ещё до конца: без запаса хвост модели вернулся бы."""
        levels = _levels((1, -50), (2, -20), (0.15, -38), (1, -50))
        self.assertEqual(audio.window_from_levels(levels), (1.0, 3.25))

    def test_pause_of_half_a_second_is_one_phrase(self):
        levels = _levels((1, -50), (1, -20), (0.45, -50), (1, -20), (2, -50))
        self.assertEqual(audio.window_from_levels(levels), (1.0, 3.7))

    def test_lips_are_the_longest_group_of_pieces(self):
        """Свист в начале тоже кусок окна, но слова начинаются там, где длинная группа."""
        levels = _levels((1, -50), (1, -20), (2, -50), (2.5, -20), (1, -50))
        self.assertEqual(audio.window_from_levels(levels), (1.0, 6.75))
        self.assertEqual(audio.lips_from_levels(levels), 4.0)

    def test_lips_of_one_group_are_the_window_start(self):
        levels = _levels((1, -50), (1, -20), (0.3, -50), (1, -20), (1, -50))
        self.assertEqual(audio.lips_from_levels(levels), 1.0)
        self.assertIsNone(audio.lips_from_levels(_levels((5, -60))))

    def test_quiet_piece_is_the_longest_and_away_from_speech(self):
        levels = _levels((0.5, -50), (1, -20), (2, -50), (1, -20), (0.8, -50))
        self.assertEqual(audio.quiet_from_levels(levels), (1.55, 3.45))

    def test_quiet_piece_is_capped_and_has_a_minimum(self):
        self.assertEqual(audio.quiet_from_levels(_levels((1, -20), (6, -50), (1, -20))), (1.05, 4.05))
        self.assertIsNone(audio.quiet_from_levels(_levels((1, -20), (0.3, -50), (1, -20))))

    def test_tail_of_a_vowel_is_not_quiet(self):
        """Ниже порога речи, но заметно выше фона: петля из такого куска снова говорила бы."""
        levels = _levels((1, -60), (3, -20), (1, -38), (0.5, -60))
        self.assertEqual(audio.quiet_from_levels(levels), (0.05, 0.95))

    def test_clip_full_of_speech_gives_no_piece(self):
        """Фон ролика и есть речь: брать нечего, лучше тихий провал, чем голос модели."""
        self.assertIsNone(audio.quiet_from_levels(_levels((5, -20))))


class FitTests(SimpleTestCase):
    def test_shorter_line_starts_with_the_window(self):
        self.assertEqual(audio.fit_line(2.0, (1.0, 4.0), 5.0), (1.0, 1.0))

    def test_longer_line_is_sped_up_to_fit(self):
        self.assertEqual(audio.fit_line(2.2, (1.0, 3.0), 5.0), (1.0, 1.1))

    def test_never_faster_than_1_15_and_runs_past_the_window(self):
        self.assertEqual(audio.fit_line(3.0, (1.0, 2.0), 5.0), (1.0, 1.15))

    def test_end_of_the_clip_moves_the_start_rather_than_cuts_a_word(self):
        start, tempo = audio.fit_line(4.6, (1.0, 2.0), 5.0)
        self.assertEqual(tempo, 1.15)
        self.assertEqual(start, 1.0)        # 4,0 с от 1,0 — ровно до конца ролика
        start, _ = audio.fit_line(4.6, (2.0, 3.0), 5.0)
        self.assertEqual(start, 1.0)

    def test_line_longer_than_the_clip_starts_at_zero(self):
        self.assertEqual(audio.fit_line(9.0, (1.0, 2.0), 5.0), (0.0, 1.15))

    def test_no_window_starts_at_half_a_second(self):
        self.assertEqual(audio.fit_line(2.0, None, 5.0), (0.5, 1.0))
        self.assertEqual(audio.fit_line(2.0, None, 0), (0.5, 1.0))

    def test_unknown_clip_length_does_not_move_anything(self):
        self.assertEqual(audio.fit_line(3.0, (1.0, 3.0), 0), (1.0, 1.15))

    def test_line_goes_to_the_lips_when_it_has_room(self):
        self.assertEqual(audio.fit_line(1.3, (1.7, 8.25), 10.0, 5.5), (5.5, 1.0))

    def test_line_longer_than_the_room_after_the_lips_goes_as_close_as_it_fits(self):
        self.assertEqual(audio.fit_line(6.0, (1.7, 8.25), 10.0, 5.5), (4.783, 1.15))

    def test_line_longer_than_the_clip_starts_at_zero_even_with_lips(self):
        self.assertEqual(audio.fit_line(13.0, (1.7, 8.25), 10.0, 5.5), (0.0, 1.15))

    def test_window_tail_past_the_end_of_the_clip_gives_no_extra_room(self):
        """Запас на хвост гласной уводит окно за конец ролика: места от этого не прибавляется."""
        self.assertEqual(audio.fit_line(4.639, (0.05, 4.75), 4.625), (0.05, 1.014))


class LineLengthTests(SimpleTestCase):
    def test_silence_at_the_end_is_not_speech(self):
        self.assertEqual(audio._spoken_length(2.32, [(0.6, 0.8), (2.06, 2.32)]), 2.06)

    def test_pause_in_the_middle_changes_nothing(self):
        self.assertEqual(audio._spoken_length(2.32, [(0.6, 0.8)]), 2.32)
        self.assertEqual(audio._spoken_length(2.32, []), 2.32)

    def test_rounding_is_not_a_cut(self):
        start, tempo = audio.fit_line(4.6396, (1.7, 3.0), 5.088)
        self.assertEqual((start, tempo), (1.054, 1.15))
        self.assertGreater(start + 4.6396 / tempo, 5.088)
        self.assertFalse(audio._cut_needed(start, 4.6396, tempo, 5.088))

    def test_rounding_of_the_tempo_on_a_long_line_is_not_a_cut(self):
        self.assertFalse(audio._cut_needed(0.5, 14.877, 1.005, 15.296))

    def test_real_overrun_is_a_cut(self):
        self.assertTrue(audio._cut_needed(1.1, 4.64, 1.15, 5.088))
        self.assertTrue(audio._cut_needed(0.0, 9.0, 1.15, 5.0))
        self.assertFalse(audio._cut_needed(0.0, 9.0, 1.15, 0))

    def test_end_of_the_silence_may_stop_short_of_the_file(self):
        """Конец тишины в mp3 раньше длины файла: сдвиг кодера и округление длины."""
        self.assertEqual(audio._spoken_length(2.32, [(2.0, 2.265)]), 2.0)

    def test_all_silent_file_keeps_its_length(self):
        self.assertEqual(audio._spoken_length(2.0, [(0.0, 2.0)]), 2.0)

    def test_cut_goes_to_the_last_pause_inside_the_clip(self):
        self.assertEqual(audio._cut_at(3.0, 1.0, [(1.0, 1.2), (2.2, 2.4), (3.5, 3.7)]), 2.2)

    def test_pause_time_is_after_the_tempo(self):
        self.assertAlmostEqual(audio._cut_at(3.0, 1.15, [(2.3, 2.5)]), 2.0)

    def test_without_a_near_pause_the_cut_is_at_the_end(self):
        self.assertEqual(audio._cut_at(3.0, 1.0, []), 2.88)
        # Пауза слишком рано: она съела бы большую часть реплики.
        self.assertEqual(audio._cut_at(3.0, 1.0, [(0.4, 0.6)]), 2.88)


class MixGraphTests(TestCase):
    """Строка filter_complex без ffmpeg: настоящий запуск — в RealFfmpegTests и scratch/F30/mix_check.py."""

    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        ctx = override_settings(MEDIA_ROOT=self.dir.name)
        ctx.enable()
        self.addCleanup(ctx.disable)
        default_storage.save("clip.mp4", ContentFile(b"v"))
        default_storage.save("line.mp3", ContentFile(b"a"))

    def graph(self, *, tracks=(), line=None, window=(1.0, 3.0), levels=None, audio_in_clip=True, gone=False):
        scene = SimpleNamespace(pk=1, video="clip.mp4", sound_volume=1.0,
                                speech_start=window[0] if window else None,
                                speech_end=window[1] if window else None,
                                audio_tracks=_Tracks(tracks))
        seen = {}

        def run(cmd, timeout=180):
            seen["cmd"] = cmd
            Path(cmd[-1]).write_bytes(b"mp4")
            return True

        with patch("cartoon.audio._run", side_effect=run), \
             patch("cartoon.audio.probe", return_value={"duration": 5.0, "audio": audio_in_clip}), \
             patch("cartoon.audio._loudness", return_value=-23.5), \
             patch("cartoon.audio._band_levels", return_value=levels if levels is not None
                   else _levels((1, -50), (2, -20), (2, -50))):
            result = audio.mix_scene(scene, line=line)
        self.assertTrue(result)
        return seen["cmd"][seen["cmd"].index("-filter_complex") + 1]

    def line(self, **kw):
        fields = {"pk": None, "kind": "line", "file": "line.mp3", "duration": 1.5, "start_sec": 0.5, "volume": 1.0}
        return SimpleNamespace(**{**fields, **kw})

    def test_model_speech_is_muted_and_filled_and_the_line_goes_on_top(self):
        track = self.line()
        graph = self.graph(line=track)
        self.assertIn("volume='max(0,min(1,max((1.000-t)/0.08,(t-3.000)/0.08)))':eval=frame", graph)
        self.assertIn("aloop=loop=-1:size=", graph)
        self.assertIn("atrim=start=3.050:end=", graph)      # заполнитель — тихий кусок после речи
        self.assertIn("adelay=920:all=1[bed]", graph)       # с запасом на спуск: окно − 80 мс
        self.assertIn("volume=7.50dB", graph)               # −23,5 LUFS → −16
        self.assertIn("adelay=1000:all=1", graph)           # реплика — на начало окна
        self.assertEqual(track.start_sec, 1.0)
        self.assertIn("alimiter=limit=0.89", graph)
        self.assertIn("level=0", graph)
        self.assertNotIn("atempo", graph)

    def test_long_line_is_sped_up_in_the_graph(self):
        graph = self.graph(line=self.line(duration=2.2))
        self.assertIn("atempo=1.100", graph)

    def test_line_reaching_the_end_of_the_clip_fades_instead_of_stopping(self):
        graph = self.graph(line=self.line(duration=8.0))
        self.assertIn("atempo=1.150", graph)
        self.assertIn("afade=t=out:st=4.880:d=0.12", graph)

    def test_no_window_means_nothing_to_mute(self):
        track = self.line()
        graph = self.graph(line=track, window=None)
        self.assertNotIn("eval=frame", graph)
        self.assertNotIn("aloop", graph)
        self.assertIn("[0:a]volume=1.00[s0]", graph)
        self.assertEqual(track.start_sec, 0.5)
        self.assertIn("adelay=500:all=1", graph)

    def test_no_quiet_piece_still_mutes_without_a_fill(self):
        graph = self.graph(line=self.line(), levels=_levels((5, -20)))
        self.assertIn("eval=frame", graph)
        self.assertNotIn("aloop", graph)

    def test_clip_without_sound_gets_just_the_line(self):
        graph = self.graph(line=self.line(), audio_in_clip=False)
        self.assertNotIn("[0:a]", graph)
        self.assertIn("alimiter", graph)

    def test_saved_line_keeps_the_moment_the_person_chose(self):
        graph = self.graph(tracks=[self.line(pk=5, start_sec=2.0)])
        self.assertIn("adelay=2000:all=1", graph)
        self.assertIn("eval=frame", graph)

    def test_new_line_replaces_the_saved_one(self):
        old = self.line(pk=5, file="old.mp3")
        with patch.object(default_storage, "open", wraps=default_storage.open) as opened:
            self.graph(tracks=[old], line=self.line())
        self.assertNotIn("old.mp3", [c.args[0] for c in opened.call_args_list])

    def test_other_tracks_mix_as_before(self):
        music = self.line(pk=6, kind="music", start_sec=1.5, volume=0.5)
        graph = self.graph(tracks=[music], line=self.line())
        self.assertIn("adelay=1500:all=1,volume=0.50", graph)

    def test_without_a_line_nothing_changes(self):
        graph = self.graph(tracks=[self.line(pk=6, kind="voice", start_sec=1.5)])
        self.assertIn("[0:a]volume=1.00[s0]", graph)
        self.assertIn("adelay=1500:all=1,volume=1.00", graph)
        self.assertNotIn("alimiter", graph)
        self.assertNotIn("eval=frame", graph)

    def test_unreadable_line_does_not_mute_the_scene(self):
        music = self.line(pk=6, kind="music")
        graph = self.graph(tracks=[music], line=self.line(file="missing.mp3"))
        self.assertNotIn("eval=frame", graph)
        self.assertNotIn("alimiter", graph)


class _Tracks(list):
    """Вместо менеджера дорожек сцены."""

    def exclude(self, **kw):
        return self

    def filter(self, **kw):
        return self

    def order_by(self, *a):
        return self


@override_settings(ELEVENLABS_API_KEY="test-key")
@skipUnless(HAS_FFMPEG, "нужен ffmpeg")
class RealFfmpegTests(TestCase):
    """Настоящий ffmpeg на синтетическом ролике: тихий шум, а с 1 по 3 с — громкий «голос»."""

    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        ctx = override_settings(MEDIA_ROOT=self.dir.name)
        ctx.enable()
        self.addCleanup(ctx.disable)
        self.tmp = Path(self.dir.name)
        clip = self.tmp / "clip.mp4"
        subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i",
                        "testsrc=size=160x90:rate=10:duration=5", "-f", "lavfi", "-i",
                        "aevalsrc='0.002*random(0)+if(between(t,1,3),0.3*sin(2*PI*700*t),0)':s=32000:d=5",
                        "-shortest", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", str(clip)],
                       check=True)
        self.clip = clip
        voice = self.tmp / "voice.mp3"
        subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i",
                        "sine=frequency=330:duration=1.5", str(voice)], check=True)
        self.voice = voice

    def _rms(self, path, start, end):
        res = subprocess.run(["ffmpeg", "-hide_banner", "-nostats", "-ss", str(start), "-t", str(end - start),
                              "-i", str(path), "-vn", "-ac", "1", "-af",
                              "highpass=f=600,lowpass=f=800,astats=measure_overall=RMS_level:measure_perchannel=none",
                              "-f", "null", "-"], capture_output=True)
        import re

        return float(re.search(rb"RMS level dB: (-?[0-9.]+)", res.stderr).group(1))

    def test_window_and_mix_on_a_real_clip(self):
        window = audio.speech_window(self.clip)
        self.assertIsNotNone(window)
        self.assertAlmostEqual(window[0], 1.0, delta=0.15)
        self.assertAlmostEqual(window[1], 3.25, delta=0.15)
        scene = SimpleNamespace(pk=1, video=default_storage.save("clip.mp4", ContentFile(self.clip.read_bytes())),
                                sound_volume=1.0, speech_start=window[0], speech_end=window[1],
                                audio_tracks=_Tracks())
        line = SimpleNamespace(pk=None, kind="line", file=default_storage.save("v.mp3", ContentFile(self.voice.read_bytes())),
                               duration=1.5, start_sec=0.5, volume=1.0)
        path = audio.mix_scene(scene, line=line)
        self.assertTrue(path)
        self.assertEqual(line.start_sec, window[0])
        out = self.tmp / path
        info = audio.probe(out)
        self.assertTrue(info["audio"])
        self.assertAlmostEqual(info["duration"], 5.0, delta=0.3)
        # «Голос модели» (тон 700 Гц) был до конца окна; реплика 330 Гц кончилась раньше —
        # остаток окна слышен отдельно, и там только тихий фон.
        self.assertGreater(self._rms(self.clip, 2.6, 2.9), -20)
        self.assertLess(self._rms(out, 2.6, 2.9), -40)


    def test_window_does_not_depend_on_the_sample_rate(self):
        """Seedance даёт 32 кГц, но старые сцены бывают и другими: окно обязано совпасть."""
        base = audio.speech_window(self.clip)
        for rate in (44100, 48000):
            other = self.tmp / f"clip_{rate}.mp4"
            subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-i", str(self.clip), "-c:v", "copy",
                            "-c:a", "aac", "-ar", str(rate), str(other)], check=True)
            window = audio.speech_window(other)
            self.assertAlmostEqual(window[0], base[0], delta=0.1)
            self.assertAlmostEqual(window[1], base[1], delta=0.1)

    def test_line_moved_to_the_end_is_not_cut_by_rounding(self):
        """Начало и темп округлены: перебор в доли миллисекунды — не повод гасить конец реплики."""
        from django.core.files.base import ContentFile as CF

        line_file = self.tmp / "long.mp3"
        subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i",
                        "aevalsrc='if(between(t,2,2.3),0,0.3*sin(2*PI*330*t))':s=44100:d=4.6",
                        str(line_file)], check=True)
        scene = SimpleNamespace(pk=1, video=default_storage.save("clip2.mp4", CF(self.clip.read_bytes())),
                                sound_volume=1.0, speech_start=2.0, speech_end=3.0, audio_tracks=_Tracks())
        line = SimpleNamespace(pk=None, kind="line", file=default_storage.save("l.mp3", CF(line_file.read_bytes())),
                               duration=4.6, start_sec=0.5, volume=1.0)
        with patch("cartoon.audio._run", wraps=audio._run) as run:
            self.assertTrue(audio.mix_scene(scene, line=line))
        graph = next(c[0][0] for c in run.call_args_list if "-filter_complex" in c[0][0])
        graph = graph[graph.index("-filter_complex") + 1]
        self.assertNotIn("afade=t=out:st=2.", graph.split(";")[0])
        self.assertAlmostEqual(line.start_sec + 4.6 / 1.15, 5.0, delta=0.15)

    def test_short_line_is_measured_too(self):
        short = self.tmp / "short.mp3"
        subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i",
                        "sine=frequency=330:duration=0.3", str(short)], check=True)
        self.assertIsNotNone(audio._loudness(short))

    def test_pauses_of_a_line(self):
        line = self.tmp / "pause.mp3"
        subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i",
                        "aevalsrc='if(between(t,0.5,0.8)+between(t,1.5,2),0,0.3*sin(2*PI*330*t))':s=44100:d=2",
                        str(line)], check=True)
        pauses = audio._pauses(line)
        self.assertEqual(len(pauses), 2)
        self.assertAlmostEqual(pauses[0][0], 0.5, delta=0.06)
        self.assertAlmostEqual(audio._spoken_length(2.0, pauses), 1.5, delta=0.06)


@override_settings(ELEVENLABS_API_KEY="test-key")
@skipUnless(HAS_FFMPEG, "нужен ffmpeg")
class RealFlowTests(LineBase):
    """Весь путь на настоящем ffmpeg и настоящем файловом хранилище: подменены только провайдеры."""

    def setUp(self):
        super().setUp()
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        ctx = override_settings(MEDIA_ROOT=self.dir.name)
        ctx.enable()
        self.addCleanup(ctx.disable)
        tmp = Path(self.dir.name)
        subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i",
                        "testsrc=size=160x90:rate=10:duration=5", "-f", "lavfi", "-i",
                        "aevalsrc='0.002*random(0)+if(between(t,1,3),0.3*sin(2*PI*700*t),0)':s=32000:d=5",
                        "-shortest", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac",
                        str(tmp / "clip.mp4")], check=True)
        self.clip_path = default_storage.save("cartoon/scenes/clip.mp4",
                                              ContentFile((tmp / "clip.mp4").read_bytes()))
        subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i",
                        "sine=frequency=330:duration=1.5", str(tmp / "voice.mp3")], check=True)
        self.mp3 = (tmp / "voice.mp3").read_bytes()

    def _played(self, path):
        with default_storage.open(path, "rb") as fh:
            local = Path(self.dir.name) / "played.mp4"
            local.write_bytes(fh.read())
        return audio.probe(local)

    def test_button_on_a_ready_scene(self):
        project = self.project(model=MINI, resolution="480p", duration=5)
        scene = self.scene(project, dialogue=LINE, status=CartoonScene.STATUS_READY, video=self.clip_path,
                           keyframe="cartoon/k/1.png", video_prompt="p", voice_hint=SPEECH["voice"])
        with patch("cartoon.audio.tts", return_value=self.mp3), \
             patch("cartoon.audio.list_voices", return_value=VOICES):
            response = self.client.post(f"/api/cartoon/scenes/{scene.pk}/audio/line/", {}, format="json")
        self.assertEqual(response.status_code, 201, response.content)
        scene.refresh_from_db()
        self.assertTrue(scene.mixed_video)
        self.assertAlmostEqual(scene.speech_start, 1.0, delta=0.15)
        info = self._played(scene.mixed_video)
        self.assertTrue(info["audio"])
        self.assertAlmostEqual(info["duration"], 5.0, delta=0.3)
        self.assertEqual(self.charges("cartoon_voice"), [5])
        track = self.line_row(scene).get()
        self.assertAlmostEqual(track.duration, 1.5, delta=0.2)
        self.assertEqual(track.start_sec, scene.speech_start)
        # Вернуть голос модели: дорожек больше нет — играет исходный ролик.
        response = self.client.delete(f"/api/cartoon/scenes/{scene.pk}/audio/line/")
        self.assertEqual(response.status_code, 200, response.content)
        scene.refresh_from_db()
        self.assertEqual(scene.mixed_video, "")

    def test_shoot_with_a_line(self):
        project = self.project(model=MINI, resolution="480p", duration=5)
        scene = self.fresh(project=project)
        self.render(scene)
        with patch("cartoon.audio.tts", return_value=self.mp3), \
             patch("cartoon.audio.list_voices", return_value=VOICES), \
             patch("cartoon.tests_pipeline_dock.NEW_VIDEO", self.clip_path):
            seen = self.shoot(scene, director_answer=SPEECH)
        self.assertEqual(seen["result"]["status"], "ready", seen["result"])
        self.assertTrue(scene.mixed_video)
        self.assertEqual((self.charges("cartoon_scene"), self.charges("cartoon_voice")), ([28], [5]))
        self.assertTrue(self._played(scene.mixed_video)["audio"])
