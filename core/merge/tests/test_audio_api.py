"""Звук склейки (Build MA): API, деньги, правила состояния, загрузка трека, склейка, копия, уборка.

ElevenLabs всегда подменён: tts/music отдают байты, save_audio мультстудии кладёт файл без ffmpeg.
"""
from __future__ import annotations

import itertools
import os
import time
import uuid
from datetime import timedelta
from unittest.mock import Mock, patch

from celery.exceptions import SoftTimeLimitExceeded
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db.models.sql import compiler as sql_compiler
from django.test import override_settings
from django.utils import timezone

from ai.models import GenerationLog
from cartoon import audio as studio
from merge import audio, render, services, tasks, views_audio
from merge.config import MUSIC_CONCURRENCY_KEY, MUSIC_CONCURRENCY_MAX, music_concurrency
from merge.models import MergeAudio, MergeAudioRequest, MergeProject
from plans.models import MERGE_SPEND_REASONS, TokenTransaction, TokenTransactionReason

from .helpers import MediaTestCase, client_for, store

BASE = "/api/merge/"
TEXT = "Привет, это проверка"   # 20 символов → 5 кр (минимум озвучки)
_seq = itertools.count(1)
WAV = b"RIFF\x24\x00\x00\x00WAVEfmt " + b"\x00" * 64
# Настоящая save_audio мультстудии — до подмены в setUp (там она кладёт файл без ffmpeg).
REAL_SAVE_AUDIO = studio.save_audio


class _Audio(MediaTestCase):
    def setUp(self):
        super().setUp()
        self.owner = self.user(balance=500)
        self.stranger = self.user(balance=500)
        self.api = client_for(self.owner)
        self.p = self.project(self.owner, [self.take(self.owner), self.take(self.owner, duration=7.0)])
        self.saved_duration = 3.0
        self.saved = []
        for target, kw in (("cartoon.audio.is_configured", {"return_value": True}),
                           ("cartoon.audio.tts", {"return_value": b"ID3VOICE"}),
                           ("cartoon.audio.music", {"return_value": b"ID3MUSIC"}),
                           ("cartoon.audio.list_voices", {"return_value": [{"id": "voice1", "name": "Rachel"}]}),
                           ("cartoon.audio.save_audio", {"side_effect": self._save}),
                           ("merge.services.storage_ready", {"return_value": (True, "")})):
            patcher = patch(target, **kw)
            setattr(self, target.rsplit(".", 1)[-1], patcher.start())
            self.addCleanup(patcher.stop)

    def _save(self, raw, suffix=".mp3", folder="cartoon/audio", max_seconds=None, input_options=()):
        if max_seconds and self.saved_duration > max_seconds:
            raise studio.AudioTooLong("long")
        name = default_storage.save(f"{folder}/{uuid.uuid4().hex}.mp3", ContentFile(raw or b"MP3"))
        self.saved.append(name)
        return name, self.saved_duration

    def url(self, tail: str = "", project=None) -> str:
        return f"{BASE}{(project or self.p).uid}/audio/{tail}"

    def voice(self, client=None, project=None, **body):
        payload = {"text": TEXT, "voice_id": "voice1", "start_fragment": 0, **body}
        return (client or self.api).post(self.url("voice/", project), payload, format="json")

    def order_music(self, client=None, project=None, execute=True, **body):
        with self.captureOnCommitCallbacks(execute=execute):
            response = (client or self.api).post(self.url("music/", project),
                                                 {"prompt": "спокойное пианино", **body}, format="json")
        return response

    def track(self, project=None, kind="voice", *, status="ready", with_file=True, **kw) -> MergeAudio:
        project = project or self.p
        name = ""
        if with_file and status == "ready":
            name = store(f"merge/audio/{project.user_id}/t{next(_seq)}.mp3", b"ID3TRACK")
        fields = dict(project=project, kind=kind, status=status, file=name, duration_s=3.0)
        fields.update(kw)
        return MergeAudio.objects.create(**fields)

    def rows(self, project=None, **kw):
        return list(MergeAudio.objects.filter(project=project or self.p, **kw))

    def ledger(self, user=None):
        return list(TokenTransaction.objects.filter(user=user or self.owner).values_list("reason", "delta"))

    def set_status(self, status, project=None, **kw):
        project = project or self.p
        MergeProject.objects.filter(pk=project.pk).update(status=status, **kw)
        project.refresh_from_db()


class StateTests(_Audio):
    def test_state_shape(self):
        data = self.api.get(self.url()).json()
        self.assertEqual({k: data[k] for k in ("project_id", "status", "editable", "edit_block", "configured",
                                                "clip_sound", "music_volume", "voice_volume", "tracks",
                                                "fragments", "total_duration_s", "prices", "music_quote")},
                         {"project_id": self.p.uid, "status": "draft", "editable": True, "edit_block": None,
                          "configured": True, "clip_sound": "keep", "music_volume": 0.35, "voice_volume": 1.0,
                          "tracks": [], "fragments": 2, "total_duration_s": 12.0,
                          "prices": {"voice_per_1k": 20, "voice_min": 5, "music_per_min": 30},
                          "music_quote": {"seconds": 12, "credits": 6}})
        limits = data["limits"]
        self.assertEqual((limits["voice_chars"], limits["prompt_chars"], limits["music_max_s"],
                          limits["upload_max_mb"], limits["upload_max_s"], limits["voice_volume_max"]),
                         (2000, 400, 300, 20, 300, 2.0))
        # Голос склейки — на всю склейку: 2000 знаков, у сцены мультстудии — по-прежнему 1000.
        self.assertEqual((limits["voice_chars"], studio.MAX_VOICE_CHARS), (audio.VOICE_MAX_CHARS, 1000))
        self.assertEqual(limits["clip_sounds"], ["keep", "quiet", "off"])
        self.assertIn("wav", limits["extensions"])
        self.assertTrue(limits["accept"].startswith("audio/*,.mp3"))

    def test_track_shape(self):
        row = self.track(text=TEXT, voice_id="voice1", voice_name="Rachel", start_fragment=1, credits_charged=5)
        track = self.api.get(self.url()).json()["tracks"][0]
        self.assertEqual({k: track[k] for k in ("id", "kind", "source", "status", "duration_s", "text",
                                                 "voice_id", "voice_name", "start_fragment", "credits_charged",
                                                 "credits_reserved", "error", "error_code")},
                         {"id": row.uid, "kind": "voice", "source": "generated", "status": "ready",
                          "duration_s": 3.0, "text": TEXT, "voice_id": "voice1", "voice_name": "Rachel",
                          "start_fragment": 1, "credits_charged": 5, "credits_reserved": 0, "error": "",
                          "error_code": None})
        self.assertEqual(track["url"], default_storage.url(row.file))
        self.assertEqual(track["start_fragment_effective"], 1)
        self.assertIsNone(track["request_id"], "заказан без ключа нажатия")
        # Фрагменты убрали — голос звучит с последнего оставшегося.
        MergeProject.objects.filter(pk=self.p.pk).update(items=self.p.items[:1])
        track = self.api.get(self.url()).json()["tracks"][0]
        self.assertEqual((track["start_fragment"], track["start_fragment_effective"]), (1, 0))

    def test_empty_project_has_no_music_quote(self):
        empty = self.project(self.owner)
        data = self.api.get(self.url(project=empty)).json()
        self.assertEqual((data["fragments"], data["music_quote"]), (0, None))

    def test_guest_and_stranger(self):
        self.assertEqual(client_for().get(self.url()).status_code, 401)
        other = client_for(self.stranger)
        track = self.track()
        for method, tail, body in (("get", "", None), ("patch", "", {"clip_sound": "off"}),
                                   ("post", "voice/", {"text": TEXT, "voice_id": "voice1"}),
                                   ("post", "music/", {"prompt": "пианино"}),
                                   ("delete", f"{track.uid}/", None)):
            with self.subTest(method=method, tail=tail):
                response = getattr(other, method)(self.url(tail), body, format="json")
                self.assertEqual(response.status_code, 404)
                self.assertEqual(response.json()["error_code"], "project_not_found")
        upload = other.post(self.url("music/upload/"), {"file": SimpleUploadedFile("a.wav", WAV)},
                            format="multipart")
        self.assertEqual(upload.status_code, 404)
        self.assertTrue(MergeAudio.objects.filter(pk=track.pk).exists())

    def test_project_json_has_audio_summary(self):
        data = self.api.get(f"{BASE}{self.p.uid}/").json()
        self.assertEqual(data["audio"], {"clip_sound": "keep", "music_volume": 0.35, "voice_volume": 1.0,
                                         "voice": False, "music": False, "pending": False})
        self.track()
        self.track(kind="music", status="pending", credits_reserved=6)
        data = self.api.get(f"{BASE}{self.p.uid}/").json()
        self.assertEqual((data["audio"]["voice"], data["audio"]["music"], data["audio"]["pending"]),
                         (True, False, True))
        # Музыка ещё делается: кнопка «Склеить» знает заранее, почему нельзя.
        self.assertEqual(data["render_block"], {"error_code": "audio_pending", "error": audio.MSG_PENDING})
        self.assertFalse(data["can_render"])

    def test_not_configured(self):
        self.is_configured.return_value = False
        self.assertFalse(self.api.get(self.url()).json()["configured"])
        for response in (self.voice(), self.order_music()):
            self.assertEqual(response.status_code, 503)
            self.assertEqual(response.json(), {"error": audio.MSG_NOT_CONFIGURED,
                                               "error_code": "audio_not_configured"})
        self.assertEqual(audio.MSG_NOT_CONFIGURED,
                         "Голос и музыка по описанию пока не подключены. Свой трек можно загрузить.")
        self.tts.assert_not_called()
        self.assertEqual(self.rows(), [])


class VoiceTests(_Audio):
    def test_voice_is_made_then_charged(self):
        response = self.voice(start_fragment=1)
        self.assertEqual(response.status_code, 201)
        body = response.json()
        track = body["track"]
        self.assertEqual((track["status"], track["voice_name"], track["start_fragment"], track["credits_charged"],
                          track["credits_reserved"], track["duration_s"]), ("ready", "Rachel", 1, 5, 0, 3.0))
        self.assertTrue(track["url"].startswith(f"/media/merge/audio/{self.owner.pk}/"))
        self.assertEqual(body["balance"]["balance"], 495)
        self.assertEqual(self.balance(self.owner), 495)
        self.tts.assert_called_once_with(TEXT, "voice1")
        row = TokenTransaction.objects.get(user=self.owner)
        self.assertEqual((row.reason, row.delta), ("merge_voice", -5))
        self.assertEqual((row.meta["merge"], row.meta["audio"], row.meta["chars"]), (self.p.uid, track["id"], 20))
        self.assertTrue(default_storage.exists(self.rows()[0].file))
        log = GenerationLog.objects.get(user=self.owner)
        self.assertEqual((log.kind, log.provider, log.status), ("voice", "elevenlabs", "delivered"))

    def test_price_by_length_like_the_cartoon_studio(self):
        response = self.voice(text="а" * 1000)
        self.assertEqual(response.json()["track"]["credits_charged"], 20)
        self.assertEqual(self.ledger(), [("merge_voice", -20)])

    def test_up_to_2000_chars_at_the_same_rate(self):
        # Предел склейки — 2000 знаков (после чистки пробелов), цена — та же формула: 2000 → 40 кр.
        text = "а" * 1998
        response = self.voice(text=f"  {text}\n\n\tб  ", price=40)
        self.assertEqual(response.status_code, 201)
        track = response.json()["track"]
        self.assertEqual((len(track["text"]), track["credits_charged"]), (2000, 40))
        self.assertEqual(self.ledger(), [("merge_voice", -40)])
        self.assertEqual(self.tts.call_args.args[0], f"{text} б")
        self.assertEqual(studio.voice_price("а" * 2000), 40)
        # Знаком больше — отказ до провайдера и до резерва.
        response = self.voice(text="а" * 2001)
        self.assertEqual((response.status_code, response.json()["max"]), (400, 2000))
        self.assertEqual(self.tts.call_count, 1)

    def test_reserve_is_held_while_the_provider_works(self):
        from vstudio.reserve import total_reserved

        seen = {}

        def tts(text, voice_id):
            seen["merge"] = services.reserved_credits(self.owner)
            seen["site"] = total_reserved(self.owner)
            seen["status"] = MergeAudio.objects.get(project=self.p).status
            return b"ID3"

        self.tts.side_effect = tts
        self.assertEqual(self.voice().status_code, 201)
        self.assertEqual(seen, {"merge": 5, "site": 5, "status": "pending"})
        self.assertEqual(services.reserved_credits(self.owner), 0)

    def test_provider_error_charges_nothing(self):
        for error, code, text in (
                (studio.AudioProviderError("/v1/tts: http 500: boom"), "audio_failed", audio.MSG_FAILED),
                (studio.AudioProviderError("http 429: too many"), "audio_overloaded", audio.MSG_PROVIDER_BUSY),
                (studio.AudioProviderError("http 402: paid_plan_required"), "audio_unavailable",
                 audio.MSG_PROVIDER_DOWN)):
            with self.subTest(code=code):
                self.tts.side_effect = error
                response = self.voice()
                self.assertEqual(response.status_code, 502)
                self.assertEqual(response.json(), {"error": text, "error_code": code})
                row = MergeAudio.objects.get(project=self.p, kind="voice")
                self.assertEqual((row.status, row.error_code, row.credits_reserved), ("failed", code, 0))
        self.assertEqual(self.balance(self.owner), 500)
        self.assertEqual(self.ledger(), [])
        self.assertEqual(self.saved, [])
        self.assertEqual(audio.MSG_FAILED, "Не получилось сделать звук — кредиты не списаны, попробуйте ещё раз.")

    def test_key_removed_meanwhile_is_503(self):
        self.tts.side_effect = studio.AudioNotConfigured("нет ключа")
        response = self.voice()
        self.assertEqual((response.status_code, response.json()["error_code"]), (503, "audio_not_configured"))
        self.assertEqual(self.ledger(), [])

    def test_unreadable_provider_audio_charges_nothing(self):
        self.save_audio.side_effect = studio.AudioProviderError("звук не читается")
        response = self.voice()
        self.assertEqual((response.status_code, response.json()["error_code"]), (502, "audio_failed"))
        self.assertEqual(self.balance(self.owner), 500)

    def test_insufficient_balance_is_402_in_chat_shape(self):
        poor = self.user(balance=3)
        project = self.project(poor, [self.take(poor), self.take(poor)])
        response = self.voice(client=client_for(poor), project=project)
        self.assertEqual(response.status_code, 402)
        self.assertEqual(response.json(), {"error": "Недостаточно кредитов для озвучки.",
                                           "error_code": "insufficient_balance", "balance_tokens": 3,
                                           "required_estimate": 5})
        self.tts.assert_not_called()
        self.assertEqual(self.rows(project), [])

    def test_402_counts_other_reserves(self):
        with patch("vstudio.reserve.total_reserved", return_value=498):
            response = self.voice()
        self.assertEqual(response.status_code, 402)
        body = response.json()
        self.assertEqual((body["balance_tokens"], body["reserved_credits"], body["error"]),
                         (2, 498, services.MSG_NO_CREDITS_RESERVED))

    def test_price_changed(self):
        response = self.voice(price=7)
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json(), {"error": "Цена изменилась: теперь 5 кр. Проверьте и нажмите ещё раз.",
                                           "error_code": "audio_price_changed", "credits": 5})
        self.assertEqual(self.voice(price=5).status_code, 201)

    def test_validation(self):
        cases = (({"text": "   "}, "bad_request", {"field": "text"}, audio.MSG_NO_TEXT),
                 ({"text": "a" * 2001}, "voice_too_long", {"max": 2000}, "Текст длиннее 2000 символов — сократите его."),
                 ({"voice_id": "../x"}, "bad_request", {"field": "voice_id"}, "Выберите голос."),
                 ({"start_fragment": 2}, "bad_request", {"field": "start_fragment"}, audio.MSG_BAD_FRAGMENT),
                 ({"start_fragment": 1.5}, "bad_request", {"field": "start_fragment"}, audio.MSG_BAD_FRAGMENT),
                 ({"start_fragment": True}, "bad_request", {"field": "start_fragment"}, audio.MSG_BAD_FRAGMENT))
        for body, code, extra, text in cases:
            with self.subTest(body=list(body)):
                response = self.voice(**body)
                self.assertEqual(response.status_code, 400)
                self.assertEqual(response.json(), {"error": text, "error_code": code, **extra})
        self.tts.assert_not_called()
        self.assertEqual(self.rows(), [])
        self.assertEqual(self.voice(start_fragment="1").status_code, 201)

    def test_same_request_id_is_answered_once(self):
        first = self.voice(request_id="click-1")
        second = self.voice(request_id="click-1")
        self.assertEqual((first.status_code, second.status_code), (201, 200))
        self.assertEqual(first.json()["track"]["id"], second.json()["track"]["id"])
        self.assertEqual(self.tts.call_count, 1)
        self.assertEqual(self.ledger(), [("merge_voice", -5)])

    def test_second_order_while_one_is_made_is_busy(self):
        self.track(status="pending", credits_reserved=5)
        response = self.voice()
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json(), {"error": audio.MSG_BUSY, "error_code": "audio_busy"})
        self.tts.assert_not_called()
        # Музыка — другой вид: её можно заказать, пока делается голос.
        self.assertEqual(self.order_music().status_code, 202)

    def test_new_voice_replaces_the_old_one_with_its_file(self):
        with self.captureOnCommitCallbacks(execute=True):
            self.voice(request_id="a")
        old = self.rows()[0]
        with self.captureOnCommitCallbacks(execute=True):
            self.voice(text="Второй вариант", request_id="b")
        rows = self.rows()
        self.assertEqual([(r.kind, r.status, r.text) for r in rows], [("voice", "ready", "Второй вариант")])
        self.assertFalse(default_storage.exists(old.file))
        self.assertEqual(self.ledger(), [("merge_voice", -5), ("merge_voice", -5)])

    def test_failed_attempt_keeps_the_previous_voice(self):
        ready = self.track()
        self.tts.side_effect = studio.AudioProviderError("http 500")
        self.voice()
        self.assertEqual(sorted(r.status for r in self.rows()), ["failed", "ready"])
        self.tts.side_effect = None
        self.voice()
        rows = self.rows()
        self.assertEqual([r.status for r in rows], ["ready"])
        self.assertNotEqual(rows[0].pk, ready.pk)

    def test_ready_and_running_merges_are_locked(self):
        for status, code in (("ready", "audio_ready_locked"), ("queued", "render_in_progress"),
                             ("rendering", "render_in_progress")):
            with self.subTest(status=status):
                self.set_status(status, credits_reserved=20 if status != "ready" else 0)
                for response in (self.voice(), self.order_music(),
                                 self.api.patch(self.url(), {"clip_sound": "off"}, format="json")):
                    self.assertEqual(response.status_code, 409)
                    self.assertEqual(response.json()["error_code"], code)
                state = self.api.get(self.url()).json()
                self.assertEqual((state["editable"], state["edit_block"]["error_code"]), (False, code))
        self.assertEqual(audio.MSG_READY_LOCKED, "Звук готовой склейки не меняется. Нажмите «Изменить и "
                                                 "склеить заново» — звук перейдёт в новую склейку.")
        self.tts.assert_not_called()

    def test_failed_merge_returns_to_draft(self):
        self.set_status("failed", error="старое", error_code="join_failed")
        self.assertEqual(self.voice().status_code, 201)
        self.p.refresh_from_db()
        self.assertEqual((self.p.status, self.p.error, self.p.error_code), ("draft", "", ""))


class MusicTests(_Audio):
    def test_music_is_queued_then_made_and_charged(self):
        response = self.order_music(price=6)
        self.assertEqual(response.status_code, 202)
        track = response.json()["track"]
        self.assertEqual((track["status"], track["seconds"], track["credits_reserved"]), ("pending", 12.0, 6))
        self.assertEqual(self.music.call_args.args, ("спокойное пианино", 12.0))
        self.assertEqual(self.music.call_args.kwargs, {"instrumental": True, "timeout": (10, 540)})
        row = MergeAudio.objects.get(project=self.p)
        self.assertEqual((row.status, row.credits_charged, row.credits_reserved, row.source),
                         ("ready", 6, 0, "generated"))
        self.assertEqual(self.ledger(), [("merge_music", -6)])
        self.assertEqual(TokenTransaction.objects.get(user=self.owner).meta["seconds"], 12.0)
        self.assertEqual(GenerationLog.objects.get(user=self.owner).status, "delivered")

    def test_reserve_counts_until_the_task_runs(self):
        response = self.order_music(execute=False)
        self.assertEqual(response.status_code, 202)
        self.assertEqual(services.reserved_credits(self.owner), 6)
        config = self.api.get(f"{BASE}config/").json()
        self.assertEqual(config["balance"]["reserved"], 6)
        self.music.assert_not_called()

    def test_provider_failure_charges_nothing(self):
        self.music.side_effect = studio.AudioProviderError("/v1/music: http 402: paid_plan_required")
        self.order_music()
        row = MergeAudio.objects.get(project=self.p)
        self.assertEqual((row.status, row.error_code, row.error, row.credits_reserved),
                         ("failed", "audio_unavailable", audio.MSG_PROVIDER_DOWN, 0))
        self.assertEqual(self.ledger(), [])

    def test_soft_time_limit_releases(self):
        self.music.side_effect = SoftTimeLimitExceeded()
        self.order_music()
        row = MergeAudio.objects.get(project=self.p)
        self.assertEqual((row.status, row.credits_reserved), ("failed", 0))
        self.assertEqual(self.ledger(), [])

    def test_needs_fragments_and_a_prompt(self):
        empty = self.project(self.owner)
        response = self.order_music(project=empty)
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json(), {"error": audio.MSG_NO_FRAGMENTS, "error_code": "audio_no_fragments"})
        for prompt, extra in (("ab", {}), ("п" * 401, {"max": 400})):
            response = self.order_music(prompt=prompt)
            self.assertEqual(response.status_code, 400)
            self.assertEqual(response.json()["field"], "prompt")
            for key, value in extra.items():
                self.assertEqual(response.json()[key], value)

    def test_length_is_the_merge_capped_at_five_minutes(self):
        long = self.project(self.owner, [self.take(self.owner, duration=200.0),
                                         self.take(self.owner, duration=100.4)])
        response = self.order_music(project=long)
        self.assertEqual(response.json()["track"]["seconds"], 300.0)
        self.assertEqual(self.ledger(), [("merge_music", -150)])
        self.assertEqual((audio.music_seconds(0), audio.music_seconds(1.2), audio.music_seconds(14.02)), (0, 3, 15))

    def test_second_task_copy_does_not_call_the_provider(self):
        self.order_music(execute=False)
        row = MergeAudio.objects.get(project=self.p)
        self.assertEqual(tasks.make_music.run(row.pk)["status"], "ready")
        self.assertEqual(tasks.make_music.run(row.pk), {"status": "not_pending"})
        self.assertEqual(self.music.call_count, 1)
        self.assertEqual(self.ledger(), [("merge_music", -6)])

    def test_broker_down_releases_at_once(self):
        with patch("merge.tasks.make_music.apply_async", side_effect=OSError("broker")):
            self.order_music()
        row = MergeAudio.objects.get(project=self.p)
        self.assertEqual((row.status, row.error_code, row.credits_reserved), ("failed", "audio_queue_down", 0))

    def test_media_queue(self):
        with self.settings(CELERY_MEDIA_QUEUE="media"), \
                patch("merge.tasks.make_music.apply_async") as apply:
            self.order_music()
        self.assertEqual(apply.call_args.kwargs, {"queue": "media"})

    def test_merge_waits_for_its_sound(self):
        self.order_music(execute=False)
        response = self.api.post(f"{BASE}{self.p.uid}/render/", {"price": 20}, format="json")
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json(), {"error": "Голос или музыка ещё делаются — дождитесь их и нажмите «Склеить».",
                                           "error_code": "audio_pending"})
        self.p.refresh_from_db()
        self.assertEqual(self.p.status, "draft")


class MusicSlotTests(_Audio):
    """Музык разом на весь сайт — не больше merge_music_concurrency (2): очередь media общая
    с видео чата, сценами мультстудии и склейками, а музыка ждёт ElevenLabs до 540 с."""

    def slots(self) -> dict:
        return cache.get_many(audio._slot_keys(MUSIC_CONCURRENCY_MAX))

    def fill(self, *numbers):
        for n in numbers:
            self.assertTrue(cache.add(f"{audio.MUSIC_SLOT_PREFIX}:{n}", f"other{n}", audio.MUSIC_SLOT_TTL))

    def other_project(self):
        return self.project(self.owner, [self.take(self.owner), self.take(self.owner)])

    def test_cap_reached_refuses_before_any_reserve(self):
        self.fill(0, 1)
        response = self.order_music(price=6)
        self.assertEqual(response.status_code, 429)
        self.assertEqual(response.json(), {
            "error": "Сейчас готовится много музыки — попробуйте через минуту. Кредиты не списаны.",
            "error_code": "music_busy"})
        self.assertEqual(self.rows(), [])
        self.assertEqual((services.reserved_credits(self.owner), self.balance(self.owner), self.ledger()), (0, 500, []))
        self.music.assert_not_called()
        self.assertEqual(GenerationLog.objects.count(), 0)
        self.assertEqual(self.slots(), {f"{audio.MUSIC_SLOT_PREFIX}:0": "other0",
                                        f"{audio.MUSIC_SLOT_PREFIX}:1": "other1"})
        # Место освободилось — тот же заказ проходит.
        cache.delete(f"{audio.MUSIC_SLOT_PREFIX}:1")
        self.assertEqual(self.order_music(price=6).status_code, 202)
        self.assertEqual(self.ledger(), [("merge_music", -6)])

    def test_slot_is_held_from_the_order_until_the_task_ends(self):
        first = self.order_music(execute=False).json()["track"]["id"]
        self.assertEqual(list(self.slots().values()), [first])
        second_project = self.other_project()
        second = self.order_music(project=second_project, execute=False).json()["track"]["id"]
        self.assertEqual(sorted(self.slots().values()), sorted([first, second]))
        # Третий заказ, пока две музыки ждут очереди или провайдера, — отказ без резерва.
        third = self.order_music(project=self.other_project(), execute=False)
        self.assertEqual((third.status_code, third.json()["error_code"]), (429, "music_busy"))
        self.assertEqual(services.reserved_credits(self.owner), 6 + 5)
        row = MergeAudio.objects.get(uid=first)
        self.assertEqual(tasks.make_music.run(row.pk)["status"], "ready")
        self.assertEqual(list(self.slots().values()), [second])

    def test_slot_outlives_the_task(self):
        # Срок места дольше жёсткого лимита задачи: убитый воркер не держит место вечно,
        # а живой не теряет его посреди работы.
        self.assertGreaterEqual(audio.MUSIC_SLOT_TTL, audio.MUSIC_HARD_LIMIT)
        self.assertEqual(audio.MUSIC_SLOT_TTL, 720)

    def test_slot_released_on_success_failure_and_exception(self):
        self.assertEqual(self.order_music().json()["track"]["status"], "pending")
        self.assertEqual(MergeAudio.objects.get(project=self.p).status, "ready")
        self.assertEqual(self.slots(), {})
        for error in (studio.AudioProviderError("/v1/music: http 500: boom"), SoftTimeLimitExceeded()):
            with self.subTest(error=type(error).__name__):
                self.music.side_effect = error
                self.order_music(project=self.other_project())
                self.assertEqual(self.slots(), {})
        self.assertEqual(MergeAudio.objects.filter(status="failed", credits_reserved=0).count(), 2)
        # Неожиданный сбой (база, списание) роняет задачу — место всё равно отпущено.
        self.music.side_effect = None
        project = self.other_project()
        self.order_music(project=project, execute=False)
        row = MergeAudio.objects.get(project=project)
        with patch("merge.audio._generate", side_effect=RuntimeError("db down")):
            with self.assertRaises(RuntimeError):
                tasks.make_music.run(row.pk)
        self.assertEqual(self.slots(), {})

    def test_stale_slot_expires_by_itself(self):
        # Воркер умер посреди музыки: finally не выполнился, место держит только срок ключа.
        self.fill(0, 1)
        self.assertEqual(self.order_music().status_code, 429)
        later = time.time() + audio.MUSIC_SLOT_TTL + 1
        with patch("time.time", return_value=later):
            response = self.order_music(execute=False)
        self.assertEqual(response.status_code, 202)
        self.assertEqual(self.slots()[f"{audio.MUSIC_SLOT_PREFIX}:0"], response.json()["track"]["id"])

    def test_queued_task_that_finds_the_cap_taken_charges_nothing(self):
        track = self.order_music(execute=False).json()["track"]
        row = MergeAudio.objects.get(uid=track["id"])
        # Задача простояла в очереди дольше срока места, и места заняли другие заказы.
        cache.clear()
        self.fill(0, 1)
        self.assertEqual(tasks.make_music.run(row.pk), {"status": "failed", "error_code": "music_busy"})
        row.refresh_from_db()
        self.assertEqual((row.status, row.error_code, row.error, row.credits_reserved),
                         ("failed", "music_busy", audio.MSG_MUSIC_BUSY, 0))
        self.music.assert_not_called()
        self.assertEqual((self.ledger(), services.reserved_credits(self.owner), self.balance(self.owner)),
                         ([], 0, 500))
        self.assertEqual(set(self.slots().values()), {"other0", "other1"})
        # Вторая копия задачи ничего не делает и второй раз не платится.
        self.assertEqual(tasks.make_music.run(row.pk), {"status": "not_pending"})
        self.assertEqual(self.ledger(), [])
        # Место истекло, но свободное есть — задача занимает его и делает музыку.
        cache.clear()
        project = self.other_project()
        self.order_music(project=project, execute=False)
        late = MergeAudio.objects.get(project=project)
        cache.clear()
        self.fill(1)
        self.assertEqual(tasks.make_music.run(late.pk)["status"], "ready")
        self.assertEqual(self.slots(), {f"{audio.MUSIC_SLOT_PREFIX}:1": "other1"})

    def test_refusals_after_the_slot_give_it_back(self):
        cases = ((dict(price=7), 409, "audio_price_changed"),
                 (dict(), 402, "insufficient_balance"))
        for body, status, code in cases:
            with self.subTest(code=code), patch("vstudio.reserve.total_reserved",
                                                return_value=498 if status == 402 else 0):
                response = self.order_music(**body)
                self.assertEqual((response.status_code, response.json()["error_code"]), (status, code))
                self.assertEqual(self.slots(), {})
        with patch("merge.tasks.make_music.apply_async", side_effect=OSError("broker")):
            self.order_music()
        self.assertEqual(self.slots(), {})
        self.assertEqual(MergeAudio.objects.get(project=self.p).error_code, "audio_queue_down")

    def test_this_merges_music_is_busy_before_the_cap(self):
        self.track(kind="music", status="pending", credits_reserved=6)
        self.fill(0, 1)
        response = self.order_music()
        self.assertEqual((response.status_code, response.json()["error_code"]), (409, "audio_busy"))

    def test_same_click_is_answered_when_the_cap_is_full(self):
        first = self.order_music(execute=False, request_id="click-1")
        self.fill(1)
        again = self.order_music(execute=False, request_id="click-1")
        self.assertEqual((first.status_code, again.status_code), (202, 200))
        self.assertEqual(again.json()["track"]["id"], first.json()["track"]["id"])
        self.assertEqual(sorted(self.slots().values()), sorted([first.json()["track"]["id"], "other1"]))
        self.assertEqual(services.reserved_credits(self.owner), 6)

    def test_deleting_a_queued_order_frees_its_slot_at_once(self):
        # API такую склейку не удаляет (DeleteGuardTests); удаляют мимо него — админка,
        # удаление аккаунта (CASCADE).
        track = self.order_music(execute=False).json()["track"]
        self.assertEqual(self.api.delete(f"{BASE}{self.p.uid}/").status_code, 409)
        self.assertEqual(list(self.slots().values()), [track["id"]])
        with self.captureOnCommitCallbacks(execute=True):
            MergeProject.objects.get(pk=self.p.pk).delete()
        self.assertEqual(self.slots(), {})
        self.assertFalse(MergeAudio.objects.filter(uid=track["id"]).exists())
        # Начатую музыку провайдер ещё делает: её место отпустит только её задача.
        project = self.other_project()
        started = self.order_music(project=project, execute=False).json()["track"]["id"]
        MergeAudio.objects.filter(uid=started).update(started_at=timezone.now())
        with self.captureOnCommitCallbacks(execute=True):
            self.owner.delete()
        self.assertEqual(list(self.slots().values()), [started])

    def test_cache_down_lets_the_order_through(self):
        broken = Mock(**{f"{name}.side_effect": ConnectionError("redis") for name in ("add", "get", "get_many",
                                                                                         "touch", "delete")})
        with patch("merge.audio.cache", broken):
            response = self.order_music(price=6)
        self.assertEqual(response.status_code, 202)
        self.assertEqual(MergeAudio.objects.get(project=self.p).status, "ready")
        self.assertEqual(self.ledger(), [("merge_music", -6)])

    def test_cap_is_a_runtime_key_over_settings(self):
        from adminapi.runtime import KEYS, set_runtime

        self.assertIn(MUSIC_CONCURRENCY_KEY, KEYS)
        self.assertEqual(music_concurrency(), 2)
        with self.settings(MERGE_MUSIC_CONCURRENCY=3):
            self.assertEqual(music_concurrency(), 3)
            for value, expected in (("1", 1), ("0", 1), ("100", MUSIC_CONCURRENCY_MAX), ("junk", 3)):
                with self.subTest(value=value):
                    set_runtime("merge_music_concurrency", value)
                    self.assertEqual(music_concurrency(), expected)
        set_runtime("merge_music_concurrency", "1")
        self.assertEqual(self.order_music(execute=False).status_code, 202)
        response = self.order_music(project=self.other_project(), execute=False)
        self.assertEqual((response.status_code, response.json()["error_code"]), (429, "music_busy"))


class RequestIdTests(_Audio):
    """MA_FIX6: дорожка несёт ключ нажатия (request_id), которым её заказали. Клиент, у которого
    ответ не дошёл, узнаёт по нему свой заказ: не вышел именно он — следующее нажатие новый заказ,
    иначе повтор тем же ключом (200, второго списания нет)."""

    def keys(self, project=None):
        tracks = self.api.get(self.url(project=project)).json()["tracks"]
        return [(t["kind"], t["status"], t["request_id"]) for t in tracks]

    def test_voice_track_carries_its_key_also_when_failed_and_replayed(self):
        first = self.voice(request_id="click-1")
        self.assertEqual((first.status_code, first.json()["track"]["request_id"]), (201, "click-1"))
        again = self.voice(request_id="click-1")
        self.assertEqual((again.status_code, again.json()["track"]["request_id"]), (200, "click-1"))
        self.assertEqual(self.keys(), [("voice", "ready", "click-1")])
        # Следующий заказ не вышел: у неудачной свой ключ, у прежнего голоса — свой.
        self.tts.side_effect = studio.AudioProviderError("http 500")
        self.assertEqual(self.voice(text="Второй вариант", request_id="click-2").status_code, 502)
        self.assertEqual(self.keys(), [("voice", "ready", "click-1"), ("voice", "failed", "click-2")])
        replay = self.voice(text="Второй вариант", request_id="click-2").json()["track"]
        self.assertEqual((replay["status"], replay["request_id"]), ("failed", "click-2"))
        self.assertEqual(self.ledger(), [("merge_voice", -5)])
        # Без ключа — null.
        self.tts.side_effect = None
        with self.captureOnCommitCallbacks(execute=True):
            plain = self.voice(text="Третий вариант")
        self.assertEqual((plain.status_code, plain.json()["track"]["request_id"]), (201, None))

    def test_music_track_carries_its_key_while_made_and_when_ready(self):
        queued = self.order_music(execute=False, request_id="m-1")
        self.assertEqual((queued.status_code, queued.json()["track"]["request_id"]), (202, "m-1"))
        self.assertEqual(self.keys(), [("music", "pending", "m-1")])
        row = MergeAudio.objects.get(project=self.p, kind="music")
        self.assertEqual(tasks.make_music.run(row.pk)["status"], "ready")
        self.assertEqual(self.keys(), [("music", "ready", "m-1")])

    def test_own_track_and_copies_have_no_key(self):
        self.track(kind="music", source="upload", title="Мой трек")
        self.track(request_id="click-9", credits_charged=5)
        self.assertEqual(self.keys(), [("music", "ready", None), ("voice", "ready", "click-9")])
        MergeProject.objects.filter(pk=self.p.pk).update(status="ready")
        response = self.api.post(BASE, {"items": [self.ref(self.take(self.owner))], "copy_audio_from": self.p.uid},
                                 format="json")
        self.assertEqual(response.status_code, 201)
        copy = MergeProject.objects.get(uid=response.json()["id"])
        # Ключ — у заказа своей склейки: копия ничего не заказывала.
        self.assertEqual(self.keys(copy), [("music", "ready", None), ("voice", "ready", None)])


class ReplacedKeyTests(_Audio):
    """MA_FIX6-REFIX1 (MA_V6 B3): ключ заказа переживает его дорожку. Новый звук того же вида,
    свой трек или ✕ стирают строку, а вместе с ней ключ; вкладка, у которой ответ не дошёл,
    повторяла заказ, сервер его не находил — и заказывал и списывал второй раз (E3: −5 ×3 за два
    намерения). Теперь повтор отвечает 200 снимком ушедшей дорожки и текущим звуком."""

    def test_voice_replaced_by_another_tab_is_not_ordered_again(self):
        first = self.voice(request_id="tab-1")                 # ответ во вкладке 1 потерян
        self.assertEqual(first.status_code, 201)
        second = self.voice(text="Вторая вкладка", request_id="tab-2")
        self.assertEqual(second.status_code, 201)              # её голос заменил голос вкладки 1
        retry = self.voice(request_id="tab-1")
        self.assertEqual(retry.status_code, 200)
        body = retry.json()
        self.assertEqual((body["track"]["status"], body["track"]["request_id"], body["track"]["url"],
                          body["track"]["text"], body["track"]["credits_charged"]),
                         ("ready", "tab-1", None, TEXT, 5))
        self.assertEqual([(t["status"], t["request_id"]) for t in body["tracks"]], [("ready", "tab-2")])
        self.assertEqual(self.ledger(), [("merge_voice", -5), ("merge_voice", -5)])
        self.assertEqual(self.tts.call_count, 2)
        self.assertEqual(audio.reserved(self.owner.pk), 0)

    def test_music_replaced_by_another_tab_is_not_ordered_again(self):
        # Задача музыки в тестах идёт сразу после коммита: каждая музыка готова и оплачена.
        self.assertEqual(self.order_music(request_id="tab-1").status_code, 202)
        self.assertEqual(self.order_music(prompt="бодрый рок", request_id="tab-2").status_code, 202)
        self.assertEqual([(r.status, r.request_id) for r in self.rows(kind="music")], [("ready", "tab-2")])
        with patch.object(tasks.make_music, "apply_async") as enqueue:
            retry = self.order_music(request_id="tab-1")
        self.assertEqual((retry.status_code, retry.json()["track"]["status"], retry.json()["track"]["request_id"]),
                         (200, "ready", "tab-1"))
        enqueue.assert_not_called()
        self.assertEqual(self.ledger(), [("merge_music", -6), ("merge_music", -6)])
        self.assertEqual(audio.reserved(self.owner.pk), 0)

    def test_replayed_music_is_answered_also_when_every_place_is_taken(self):
        self.assertEqual(self.order_music(request_id="tab-1").status_code, 202)
        self.assertEqual(self.order_music(prompt="бодрый рок", request_id="tab-2").status_code, 202)
        with patch.object(audio, "take_music_slot", return_value=None):
            self.assertEqual(self.order_music(request_id="tab-1").status_code, 200)
            self.assertEqual(self.order_music(request_id="tab-3").status_code, 429)

    def test_a_failed_order_replaced_by_the_next_replays_its_failure(self):
        self.tts.side_effect = studio.AudioProviderError("http 500")
        self.assertEqual(self.voice(request_id="click-1").status_code, 502)
        self.tts.side_effect = None
        self.assertEqual(self.voice(text="Второй вариант", request_id="click-2").status_code, 201)
        retry = self.voice(request_id="click-1")
        track = retry.json()["track"]
        self.assertEqual((retry.status_code, track["status"], track["error_code"], track["request_id"]),
                         (200, "failed", "audio_failed", "click-1"))
        self.assertEqual(self.ledger(), [("merge_voice", -5)])
        self.assertEqual(self.tts.call_count, 2)

    def test_own_track_and_a_removed_track_keep_the_key(self):
        self.assertEqual(self.order_music(request_id="m-1").status_code, 202)
        with patch("merge.render.probe_audio", return_value=render.AudioProbe(6.0, True, "pcm_s16le")):
            with self.captureOnCommitCallbacks(execute=True):
                uploaded = self.api.post(self.url("music/upload/"), {"file": SimpleUploadedFile("t.wav", WAV)},
                                         format="multipart")
        self.assertEqual(uploaded.status_code, 201)
        with patch.object(tasks.make_music, "apply_async") as enqueue:
            retry = self.order_music(request_id="m-1")
        self.assertEqual((retry.status_code, retry.json()["track"]["status"]), (200, "ready"))
        enqueue.assert_not_called()
        self.assertEqual([t["source"] for t in retry.json()["tracks"]], ["upload"])
        voice = self.voice(request_id="v-1").json()["track"]
        with self.captureOnCommitCallbacks(execute=True):
            self.assertEqual(self.api.delete(self.url(f"{voice['id']}/")).status_code, 200)
        retry = self.voice(request_id="v-1")
        self.assertEqual((retry.status_code, retry.json()["track"]["status"]), (200, "ready"))
        self.assertEqual([t["kind"] for t in retry.json()["tracks"]], ["music"])
        self.assertEqual(sorted(self.ledger()), [("merge_music", -6), ("merge_voice", -5)])

    def test_keys_are_per_merge_and_kind_and_live_as_long_as_the_sound(self):
        self.assertEqual(self.voice(request_id="same").status_code, 201)
        self.assertEqual(self.voice(text="Вторая вкладка", request_id="tab-2").status_code, 201)
        self.assertEqual(list(MergeAudioRequest.objects.values_list("kind", "request_id")), [("voice", "same")])
        # Тот же ключ у музыки и у другой склейки — другой заказ.
        self.assertEqual(self.order_music(request_id="same").status_code, 202)
        other = self.project(self.owner, [self.take(self.owner)])
        self.assertEqual(self.voice(project=other, request_id="same").status_code, 201)
        # Уборка: ключ живёт столько же, сколько звук (30 дней), и уходит вместе со склейкой.
        MergeAudioRequest.objects.update(created_at=timezone.now() - timedelta(days=31))
        audio.purge()
        self.assertFalse(MergeAudioRequest.objects.exists())
        self.assertEqual(self.voice(text="Третий", request_id="tab-3").status_code, 201)
        self.assertTrue(MergeAudioRequest.objects.filter(request_id="tab-2").exists())
        MergeProject.objects.filter(pk=self.p.pk).delete()
        self.assertFalse(MergeAudioRequest.objects.exists())


class DeleteGuardTests(_Audio):
    """Склейку не удалить, пока её голос или музыка делаются (MA_FIX4): провайдер уже
    работает и берёт деньги, а заказ удалённой склейки не списался бы — «заказать музыку
    и удалить склейку» было бы бесплатным для человека и платным для EsAI."""

    BUSY = {"error": "Звук для этой склейки ещё делается — дождитесь его.", "error_code": "audio_busy"}

    def delete(self, project=None):
        with self.captureOnCommitCallbacks(execute=True):
            return self.api.delete(f"{BASE}{(project or self.p).uid}/")

    def test_queued_music_refuses_and_is_paid_when_made(self):
        track = self.order_music(execute=False).json()["track"]
        response = self.delete()
        self.assertEqual((response.status_code, response.json()), (409, self.BUSY))
        self.assertTrue(MergeProject.objects.filter(pk=self.p.pk).exists())
        self.assertEqual(MergeAudio.objects.get(uid=track["id"]).status, "pending")
        self.assertEqual(services.reserved_credits(self.owner), 6)
        self.assertEqual(list(cache.get_many(audio._slot_keys(MUSIC_CONCURRENCY_MAX)).values()), [track["id"]])
        row = MergeAudio.objects.get(uid=track["id"])
        self.assertEqual(tasks.make_music.run(row.pk)["status"], "ready")
        self.assertEqual(self.ledger(), [("merge_music", -6)])
        row.refresh_from_db()
        self.assertEqual(self.delete().status_code, 204)
        self.assertFalse(MergeProject.objects.filter(pk=self.p.pk).exists())
        self.assertFalse(default_storage.exists(row.file))

    def test_started_music_cannot_be_dropped_for_free(self):
        # MA_V3_money W4: заказать, дождаться начала и удалить склейку — раньше ElevenLabs делал
        # музыку, а человеку не списывалось ничего (_Gone → GenerationLog lost).
        self.order_music(execute=False)
        row = MergeAudio.objects.get(project=self.p)
        seen = []

        def provider(*args, **kwargs):
            seen.append(self.delete())
            return b"ID3MUSIC"

        self.music.side_effect = provider
        self.assertEqual(tasks.make_music.run(row.pk)["status"], "ready")
        self.assertEqual([(r.status_code, r.json()) for r in seen], [(409, self.BUSY)])
        self.assertEqual(self.ledger(), [("merge_music", -6)])
        self.assertEqual(self.balance(self.owner), 494)
        self.assertEqual(GenerationLog.objects.get(user=self.owner).status, "delivered")
        self.assertEqual(self.delete().status_code, 204)

    def test_voice_in_flight_refuses_delete_from_another_tab(self):
        seen = []

        def provider(*args, **kwargs):
            seen.append(self.delete())
            return b"ID3VOICE"

        self.tts.side_effect = provider
        self.assertEqual(self.voice().status_code, 201)
        self.assertEqual([(r.status_code, r.json()) for r in seen], [(409, self.BUSY)])
        self.assertEqual(self.ledger(), [("merge_voice", -5)])
        self.assertEqual(self.delete().status_code, 204)

    def test_ready_and_failed_sound_do_not_block(self):
        ready = self.track()
        self.track(kind="music", status="failed", error_code="audio_failed")
        self.assertEqual(self.delete().status_code, 204)
        self.assertEqual(MergeAudio.objects.count(), 0)
        self.assertFalse(default_storage.exists(ready.file))

    def test_a_running_merge_still_refuses_first(self):
        self.set_status("rendering", credits_reserved=20, render_started_at=timezone.now())
        response = self.delete()
        self.assertEqual((response.status_code, response.json()["error_code"]), (409, "render_in_progress"))

    def test_a_stale_order_is_closed_and_the_merge_deleted(self):
        # Заказ оборвался (деплой, убитый воркер): удаление не ждёт уборки раз в пять минут.
        now = timezone.now()
        voice = self.track(status="pending", credits_reserved=5)
        MergeAudio.objects.filter(pk=voice.pk).update(created_at=now - timedelta(minutes=11))
        other = self.project(self.owner, [self.take(self.owner)])
        started = self.track(project=other, kind="music", status="pending", credits_reserved=6,
                             started_at=now - timedelta(minutes=20))
        alive_project = self.project(self.owner, [self.take(self.owner)])
        alive = self.track(project=alive_project, kind="music", status="pending", credits_reserved=6,
                           started_at=now - timedelta(minutes=3))
        self.assertEqual(self.delete().status_code, 204)
        self.assertEqual(self.delete(other).status_code, 204)
        self.assertFalse(MergeAudio.objects.filter(pk__in=[voice.pk, started.pk]).exists())
        # Живой заказ уборка перед удалением не тронула.
        self.assertEqual(self.delete(alive_project).status_code, 409)
        alive.refresh_from_db()
        self.assertEqual((alive.status, alive.credits_reserved), ("pending", 6))
        self.assertEqual(self.ledger(), [])

    def test_a_refused_delete_still_closes_its_overdue_order(self):
        # MA_V5 W1: отказ поднимался внутри транзакции удаления, и откат точки сохранения снимал
        # и закрытие оборванного заказа — его резерв висел до уборки раз в пять минут.
        now = timezone.now()
        voice = self.track(status="pending", credits_reserved=5)
        MergeAudio.objects.filter(pk=voice.pk).update(created_at=now - timedelta(minutes=11))
        music = self.track(kind="music", status="pending", credits_reserved=6, prompt="спокойное пианино",
                           seconds=12.0)
        self.assertEqual(services.reserved_credits(self.owner), 11)
        response = self.delete()
        self.assertEqual((response.status_code, response.json()), (409, self.BUSY))
        voice.refresh_from_db()
        music.refresh_from_db()
        self.assertEqual((voice.status, voice.credits_reserved, voice.error_code), ("failed", 0, "audio_stale"))
        self.assertEqual((music.status, music.credits_reserved), ("pending", 6))
        self.assertEqual(services.reserved_credits(self.owner), 6)
        self.assertTrue(MergeProject.objects.filter(pk=self.p.pk).exists())
        self.assertEqual(self.ledger(), [])
        # Музыка сделалась (и оплачена) — теперь удаляется.
        self.assertEqual(tasks.make_music.run(music.pk)["status"], "ready")
        self.assertEqual(self.ledger(), [("merge_music", -6)])
        self.assertEqual(self.delete().status_code, 204)

    def test_a_refused_delete_keeps_the_lock_order_and_the_sweep(self):
        # Тот же отказ без запроса (служебный вызов) и отказ «склейка идёт»: оборванный заказ
        # закрыт, замки — пользователь, склейка, дорожки (audio.LOCK_ORDER).
        now = timezone.now()
        cases = (("audio_busy", "draft"), ("render_in_progress", "rendering"))
        for code, status in cases:
            with self.subTest(code=code):
                project = self.project(self.owner, [self.take(self.owner)])
                stale = self.track(project=project, status="pending", credits_reserved=5)
                MergeAudio.objects.filter(pk=stale.pk).update(created_at=now - timedelta(minutes=11))
                if status == "draft":
                    self.track(project=project, kind="music", status="pending", credits_reserved=6,
                               started_at=now - timedelta(minutes=3))
                else:
                    self.set_status(status, project=project, credits_reserved=20, render_started_at=now)
                with _Locks() as locks, self.assertRaises(services.MergeError) as refused:
                    services.delete_project(self.owner, project.uid)
                self.assertEqual((refused.exception.code, refused.exception.status), (code, 409))
                self.assertEqual(locks.order(), list(audio.LOCK_ORDER), locks.events)
                stale.refresh_from_db()
                self.assertEqual((stale.status, stale.credits_reserved), ("failed", 0))
                self.assertTrue(MergeProject.objects.filter(pk=project.pk).exists())
        # Чужой: 404 до всякой уборки (как раньше).
        mine = self.project(self.owner, [self.take(self.owner)])
        stale = self.track(project=mine, status="pending", credits_reserved=5)
        MergeAudio.objects.filter(pk=stale.pk).update(created_at=now - timedelta(minutes=11))
        with self.assertRaises(services.MergeError) as refused:
            services.delete_project(self.stranger, mine.uid)
        self.assertEqual(refused.exception.status, 404)
        stale.refresh_from_db()
        self.assertEqual((stale.status, stale.credits_reserved), ("pending", 5))

    def test_expiry_never_deletes_under_a_sound_order(self):
        # У готовой склейки звук не делается (запуск ждёт звук, заказ делает склейку черновиком);
        # если бы делался — уборка ждёт, пока заказ закроется, и истекает её на следующем запуске.
        past = timezone.now() - timedelta(hours=1)
        self.set_status("ready", expires_at=past, result_video=store(f"merge/{self.owner.pk}/r.mp4"))
        voice = self.track()
        making = self.track(kind="music", status="pending", credits_reserved=6, expires_at=past)
        plain = self.project(self.owner, [self.take(self.owner)], status="ready", expires_at=past)
        draft = self.project(self.owner, [self.take(self.owner)])
        queued = self.track(project=draft, kind="music", status="pending", credits_reserved=6, expires_at=past)
        with self.captureOnCommitCallbacks(execute=True):
            self.assertEqual(tasks.purge_expired.run(), {"merges": 1, "uploads": 0, "audio": 0})
        self.p.refresh_from_db()
        plain.refresh_from_db()
        self.assertEqual((self.p.status, plain.status), ("ready", "expired"))
        self.assertTrue(default_storage.exists(self.p.result_video))
        self.assertEqual(set(MergeAudio.objects.values_list("pk", flat=True)), {voice.pk, making.pk, queued.pk})
        # Заказ закрылся (здесь — не вышел) — следующий запуск истекает склейку вместе со звуком.
        self.assertTrue(audio._release(making.pk, "audio_failed", audio.MSG_FAILED))
        result = self.p.result_video
        with self.captureOnCommitCallbacks(execute=True):
            self.assertEqual(services.purge_expired(), 1)
        self.p.refresh_from_db()
        self.assertEqual((self.p.status, self.p.result_video), ("expired", ""))
        self.assertFalse(default_storage.exists(result))
        self.assertEqual(set(MergeAudio.objects.values_list("pk", flat=True)), {queued.pk})


class UploadTests(_Audio):
    def setUp(self):
        super().setUp()
        patcher = patch("merge.render.probe_audio", return_value=render.AudioProbe(6.0, True, "pcm_s16le"))
        self.probe_audio = patcher.start()
        self.addCleanup(patcher.stop)
        self.saved_duration = 6.0

    def upload(self, name="Мой трек.wav", body=WAV, project=None, **kw):
        files = {"file": SimpleUploadedFile(name, body)} if name else {}
        with self.captureOnCommitCallbacks(execute=True):
            return self.api.post(self.url("music/upload/", project), files, format="multipart", **kw)

    def assertNoFiles(self):
        folder = default_storage.path(audio.folder(self.owner.pk))
        names = os.listdir(folder) if os.path.isdir(folder) else []
        self.assertEqual(names, [])

    def test_own_track_is_free_and_replaces_the_music(self):
        generated = self.track(kind="music", credits_charged=6)
        response = self.upload()
        self.assertEqual(response.status_code, 201)
        body = response.json()
        self.assertEqual((body["track"]["source"], body["track"]["title"], body["track"]["status"],
                          body["track"]["duration_s"], body["track"]["credits_charged"]),
                         ("upload", "Мой трек", "ready", 6.0, 0))
        self.assertEqual([t["kind"] for t in body["tracks"]], ["music"])
        self.assertFalse(default_storage.exists(generated.file))
        self.assertEqual(self.balance(self.owner), 500)
        self.assertEqual(self.ledger(), [])
        path, fmt = self.probe_audio.call_args.args
        self.assertEqual((os.path.basename(path), fmt), ("in.wav", "wav"))
        _raw, suffix = self.save_audio.call_args.args[:2]
        self.assertEqual(suffix, ".wav")
        self.assertEqual(self.save_audio.call_args.kwargs, {"folder": f"merge/audio/{self.owner.pk}",
                                                            "max_seconds": 301.0,
                                                            "input_options": render.audio_input_args("wav")})

    def _convert_for_real(self, converted_s):
        """Загрузка с настоящей save_audio: ffmpeg подменён, «пересобранный» трек длится converted_s."""
        calls = []

        def run(cmd, timeout=180):
            calls.append(cmd)
            with open(cmd[-1], "wb") as fh:
                fh.write(b"ID3OUT")
            return True

        with patch("cartoon.audio.save_audio", REAL_SAVE_AUDIO), patch("cartoon.audio._run", side_effect=run), \
                patch("cartoon.audio.probe", return_value={"duration": converted_s, "audio": True}):
            response = self.upload()
        self.assertEqual(len(calls), 1)
        return response, calls[0]

    def test_conversion_reads_like_the_strict_probe_and_stops_at_the_ceiling(self):
        response, cmd = self._convert_for_real(6.0)
        self.assertEqual(response.status_code, 201)
        path, fmt = self.probe_audio.call_args.args
        strict = render.audio_probe_cmd(path, fmt)
        i = cmd.index("-i")
        # Тот же протокол, те же декодеры и тот же демуксер, что у строгого разбора, — не угадывание по файлу.
        self.assertEqual(cmd[i - 6:i], strict[strict.index("-protocol_whitelist"):strict.index("-show_streams")])
        self.assertEqual(cmd[i - 2:i], ["-f", "wav"])
        self.assertTrue(cmd[i + 1].startswith("file:") and cmd[i + 1].endswith("in.wav"))
        # Потолок самой пересборки: 300 с + 1 с допуска + 1 с — дальше ffmpeg не читает.
        self.assertEqual(cmd[i + 2:i + 4], ["-t", "302"])
        # И потолок байтов готового mp3: он держится, даже когда счёт сэмплов обнуляется.
        self.assertEqual(cmd[cmd.index("-fs") + 1], str(studio.output_cap(301.0)))
        # Теги и главы трека в mp3 не идут: потолок байтов считает только звук.
        self.assertEqual(cmd[cmd.index("-fs") + 2:cmd.index("-fs") + 6],
                         ["-map_metadata", "-1", "-map_chapters", "-1"])

    def test_lying_header_costs_at_most_the_ceiling(self):
        # Заголовок сказал «6 секунд», а пересборка дошла до потолка: внутри часы звука — отказ, файла нет.
        response, cmd = self._convert_for_real(302.0)
        self.assertEqual((response.status_code, response.json()["error_code"]), (400, "audio_too_long"))
        self.assertIn("-t", cmd)
        self.assertEqual(self.rows(), [])
        self.assertNoFiles()

    def test_upload_slot_outlives_the_longest_request(self):
        # Разбор 20 с + пересборка до 180 с + её проверка до 60 с: место не истекает посреди запроса.
        self.assertGreater(views_audio.AUDIO_UPLOAD_SLOT_TTL, render.UPLOAD_PROBE_TIMEOUT_S + 180 + 60)
        with patch("merge.views.cache.add", return_value=True) as add:
            self.assertEqual(self.upload().status_code, 201)
        self.assertEqual(add.call_args.args, (f"merge:audio-upload:{self.owner.pk}", 1,
                                              views_audio.AUDIO_UPLOAD_SLOT_TTL))

    def test_sample_rate_and_channels_are_capped(self):
        # Потолок длины считает секунды, а пересборка стоит секунды × частота × каналы:
        # крошечный FLAC на 16 каналов и 768 кГц — отказ до пересборки.
        self.assertEqual(audio.MSG_UNSUPPORTED,
                         "Такой трек не подходит: в нём больше 8 каналов или частота выше 192 кГц. "
                         "Сохраните его как обычное стерео, например в MP3, и загрузите снова.")
        for rate, channels in ((192001, 2), (768000, 2), (48000, 9), (44100, 16)):
            with self.subTest(rate=rate, channels=channels):
                self.probe_audio.return_value = render.AudioProbe(6.0, True, "flac", rate, channels)
                response = self.upload(name="hi.flac")
                self.assertEqual(response.status_code, 400)
                self.assertEqual(response.json(), {"error": audio.MSG_UNSUPPORTED, "error_code": "audio_unsupported",
                                                   "max_channels": 8, "max_sample_rate": 192000,
                                                   "channels": channels, "sample_rate": rate})
        self.save_audio.assert_not_called()
        self.assertEqual(self.rows(), [])
        self.assertNoFiles()
        # Студийные 192 кГц и 7.1 — ещё честная музыка; частоту и каналы не назвали — не отказываем.
        for rate, channels in ((192000, 8), (None, None)):
            with self.subTest(rate=rate, channels=channels):
                self.probe_audio.return_value = render.AudioProbe(6.0, True, "flac", rate, channels)
                self.assertEqual(self.upload(name="ok.flac").status_code, 201)

    def test_upload_works_without_elevenlabs(self):
        self.is_configured.return_value = False
        self.assertEqual(self.upload().status_code, 201)

    def test_sniff(self):
        cases = {b"ID3\x04\x00" + b"\x00" * 11: "mp3", b"\xff\xfb\x90\x00" + b"\x00" * 12: "mp3",
                 b"\xff\xf1\x50\x80" + b"\x00" * 12: "aac", b"\x00\x00\x00\x20ftypM4A \x00\x00": "mov",
                 b"\x00\x00\x00\x20ftypisom\x00\x00": "mov", b"\x00\x00\x00\x20ftypheic\x00\x00": "",
                 b"RIFF\x00\x00\x00\x00WAVEfmt ": "wav", b"RIFF\x00\x00\x00\x00AVI LIST": "",
                 b"OggS\x00\x02" + b"\x00" * 10: "ogg", b"\x1a\x45\xdf\xa3\x01" + b"\x00" * 11: "matroska",
                 b"fLaC\x00\x00\x00\x22" + b"\x00" * 8: "flac", b"FORM\x00\x00\x00\x00AIFFCOMM": "aiff",
                 b"caff\x00\x01\x00\x00" + b"\x00" * 8: "caf",
                 bytes.fromhex("3026b2758e66cf11a6d900aa0062ce6c"): "asf", b"#!AMR\n" + b"\x00" * 10: "amr",
                 b"#EXTM3U\n#EXTINF:1,\n": "", b"ffconcat version 1.0": "", b"\x89PNG\r\n\x1a\n" + b"\x00" * 8: "",
                 b"": ""}
        for head, fmt in cases.items():
            with self.subTest(head=head[:8]):
                self.assertEqual(audio.sniff(head), fmt)
        self.assertTrue(set(audio.FORMAT_SUFFIX) == set(render.AUDIO_FORMATS))
        self.assertTrue(all(s.lstrip(".") in studio.UPLOAD_EXTENSIONS for s in audio.FORMAT_SUFFIX.values()))

    def test_refusals(self):
        png = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64
        cases = (
            ({"name": None}, 400, "bad_request", "Выберите аудиофайл."),
            ({"name": "track.exe"}, 400, "audio_bad_type", audio.MSG_BAD_TYPE),
            ({"name": "track.mp3", "body": png}, 400, "audio_bad_type", audio.MSG_BAD_TYPE),
            ({"name": "list.mp3", "body": b"#EXTM3U\nfile:///etc/passwd\n"}, 400, "audio_bad_type",
             audio.MSG_BAD_TYPE),
        )
        for kw, status, code, text in cases:
            with self.subTest(kw=kw.get("name")):
                response = self.upload(**kw)
                self.assertEqual(response.status_code, status)
                self.assertEqual((response.json()["error_code"], response.json()["error"]), (code, text))
        self.probe_audio.assert_not_called()
        for info, code in ((None, "audio_unreadable"), (render.AudioProbe(5.0, False), "audio_no_sound"),
                           (render.AudioProbe(None, True), "audio_unreadable"),
                           (render.AudioProbe(301.5, True), "audio_too_long")):
            with self.subTest(code=code, info=info):
                self.probe_audio.return_value = info
                response = self.upload()
                self.assertEqual((response.status_code, response.json()["error_code"]), (400, code))
        self.assertEqual(response.json(), {"error": "Трек длиннее 5 минут. Обрежьте его и загрузите снова.",
                                           "error_code": "audio_too_long", "max_s": 300, "duration_s": 301.5})
        self.save_audio.assert_not_called()
        self.assertEqual(self.rows(), [])
        self.assertNoFiles()

    def test_size_limits(self):
        with patch("merge.audio.AUDIO_UPLOAD_MAX_BYTES", 10):
            response = self.upload(body=WAV)
        self.assertEqual(response.status_code, 400)
        self.assertEqual((response.json()["error_code"], response.json()["error"]),
                         ("audio_too_big", "Файл больше 20 МБ. Выберите трек поменьше или сожмите его."))
        self.assertEqual(audio.too_big().body(), {"error": audio.MSG_TOO_BIG, "error_code": "audio_too_big",
                                                  "max_mb": 20})
        with self.assertRaises(services.MergeError) as ctx:
            audio.precheck(str(22 * 1024 * 1024))
        self.assertEqual(ctx.exception.code, "audio_too_big")
        audio.precheck(str(20 * 1024 * 1024))
        audio.precheck("junk")

    def test_conversion_failures(self):
        self.save_audio.side_effect = studio.AudioTooLong("long")
        self.assertEqual(self.upload().json()["error_code"], "audio_too_long")
        self.save_audio.side_effect = studio.AudioProviderError("звук не читается")
        self.assertEqual(self.upload().json()["error_code"], "audio_unreadable")
        self.assertEqual(self.rows(), [])

    def test_low_disk(self):
        with patch("merge.uploads._room_for", return_value=False):
            response = self.upload()
        self.assertEqual((response.status_code, response.json()["error_code"]), (503, "upload_unavailable"))

    def test_busy_while_music_is_made(self):
        self.track(kind="music", status="pending", credits_reserved=6)
        response = self.upload()
        self.assertEqual((response.status_code, response.json()["error_code"]), (409, "audio_busy"))
        self.save_audio.assert_not_called()

    def test_one_upload_at_a_time(self):
        with patch("merge.views_audio.take_upload_slot", return_value=None):
            response = self.upload()
        self.assertEqual(response.status_code, 429)
        self.assertEqual(response.json(), {"error": "Уже загружается другой трек — дождитесь окончания.",
                                           "error_code": "audio_upload_busy"})

    def test_merge_started_during_conversion_deletes_the_file(self):
        def save(raw, suffix, folder, max_seconds=None, input_options=()):
            name, duration = self._save(raw, suffix, folder, max_seconds, input_options)
            MergeProject.objects.filter(pk=self.p.pk).update(status="queued", credits_reserved=20)
            return name, duration

        self.save_audio.side_effect = save
        response = self.upload()
        self.assertEqual((response.status_code, response.json()["error_code"]), (409, "render_in_progress"))
        self.assertEqual(self.rows(), [])
        self.assertFalse(default_storage.exists(self.saved[0]))

    def test_ready_merge_is_locked(self):
        self.set_status("ready")
        response = self.upload()
        self.assertEqual((response.status_code, response.json()["error_code"]), (409, "audio_ready_locked"))


class SettingsTests(_Audio):
    def patch_(self, body, project=None):
        return self.api.patch(self.url(project=project), body, format="json")

    def test_settings_are_saved(self):
        response = self.patch_({"clip_sound": "quiet", "music_volume": 0.5, "voice_volume": 1.5})
        self.assertEqual(response.status_code, 200)
        self.assertEqual({k: response.json()[k] for k in ("clip_sound", "music_volume", "voice_volume")},
                         {"clip_sound": "quiet", "music_volume": 0.5, "voice_volume": 1.5})
        self.p.refresh_from_db()
        self.assertEqual((self.p.clip_sound, self.p.music_volume, self.p.voice_volume), ("quiet", 0.5, 1.5))

    def test_validation_is_all_or_nothing(self):
        for body, field in (({"clip_sound": "loud"}, "clip_sound"), ({"music_volume": 1.2}, "music_volume"),
                            ({"music_volume": "0.5"}, "music_volume"), ({"music_volume": True}, "music_volume"),
                            ({"voice_volume": 2.5}, "voice_volume"), ({"voice_volume": -1}, "voice_volume"),
                            ({"clip_sound": "off", "music_volume": 3}, "music_volume")):
            with self.subTest(body=body):
                response = self.patch_(body)
                self.assertEqual(response.status_code, 400)
                self.assertEqual(response.json()["field"], field)
        self.p.refresh_from_db()
        self.assertEqual((self.p.clip_sound, self.p.music_volume), ("keep", 0.35))
        self.assertEqual(self.patch_(["x"]).status_code, 400)

    def test_voice_start_fragment(self):
        response = self.patch_({"voice_start_fragment": 1})
        self.assertEqual((response.status_code, response.json()["error"]), (400, audio.MSG_NO_VOICE_TRACK))
        row = self.track()
        self.assertEqual(self.patch_({"voice_start_fragment": 1}).status_code, 200)
        row.refresh_from_db()
        self.assertEqual(row.start_fragment, 1)
        for bad in (2, None, -1, "x"):
            with self.subTest(bad=bad):
                response = self.patch_({"voice_start_fragment": bad})
                self.assertEqual((response.status_code, response.json()["field"]), (400, "voice_start_fragment"))

    def test_failed_merge_returns_to_draft_and_empty_patch_is_free(self):
        self.set_status("failed", error="x", error_code="stale")
        self.patch_({"clip_sound": "off"})
        self.p.refresh_from_db()
        self.assertEqual((self.p.status, self.p.error_code), ("draft", ""))
        self.set_status("ready")
        self.assertEqual(self.patch_({}).status_code, 200)


class _Locks:
    """Какие строки запирает код и в каком порядке: SELECT … FOR UPDATE, UPDATE и DELETE.

    На SQLite FOR UPDATE в SQL не попадает, но флаг запроса тот же — порядок замков виден и здесь;
    на PostgreSQL эти же запросы и есть замки строк.
    """

    def __enter__(self):
        self.events: list[tuple[str, str, tuple, bool]] = []
        self._patches = [self._watch(sql_compiler.SQLCompiler, "lock"),
                         self._watch(sql_compiler.SQLUpdateCompiler, "update"),
                         self._watch(sql_compiler.SQLDeleteCompiler, "delete")]
        for p in self._patches:
            p.start()
        return self

    def __exit__(self, *exc):
        for p in self._patches:
            p.stop()
        return False

    def _watch(self, cls, verb):
        original = cls.as_sql
        events = self.events

        def as_sql(compiler, *args, **kwargs):
            query = compiler.query
            if verb != "lock" or query.select_for_update:
                events.append((verb, query.model._meta.db_table, tuple(query.select_for_update_of),
                               bool(query.select_related)))
            return original(compiler, *args, **kwargs)

        return patch.object(cls, "as_sql", as_sql)

    def order(self) -> list[str]:
        """Таблицы в порядке первого замка — именами audio.LOCK_ORDER."""
        names = {get_user_model()._meta.db_table: "user", MergeProject._meta.db_table: "merge",
                 MergeAudio._meta.db_table: "audio"}
        seen: list[str] = []
        for _verb, table, _of, _joined in self.events:
            name = names.get(table)
            if name and name not in seen:
                seen.append(name)
        return seen

    def joined(self) -> list:
        """FOR UPDATE по нескольким таблицам сразу (select_related без of=): запирает все разом."""
        return [e for e in self.events if e[0] == "lock" and e[3] and not e[2]]


class LockOrderTests(_Audio):
    """MA_V4 W4: доставка голоса и PATCH audio/ берут замки в одном порядке (audio.LOCK_ORDER) —
    на PostgreSQL они не могут запереть друг друга; заказ и удаление склейки — тот же порядок."""

    def assertLockOrder(self, locks: _Locks, *, full: bool = True):
        order = locks.order()
        expected = list(audio.LOCK_ORDER) if full else list(audio.LOCK_ORDER[:len(order)])
        self.assertEqual(order, expected, locks.events)
        self.assertEqual(locks.joined(), [])

    def test_agreed_order(self):
        self.assertEqual(audio.LOCK_ORDER, ("user", "merge", "audio"))

    def test_voice_delivery_locks_user_then_merge_then_track(self):
        row = self.track(status="pending", credits_reserved=5, text=TEXT, voice_id="voice1")
        old = self.track(status="ready")
        path = store(f"merge/audio/{self.owner.pk}/new.mp3", b"ID3VOICE")
        with _Locks() as locks:
            charged = audio._deliver(row.pk, self.owner.pk, path=path, duration=3.0)
        self.assertEqual(charged, 5)
        self.assertLockOrder(locks)
        # Дорожка запирается своим запросом, без JOIN со склейкой под FOR UPDATE.
        audio_locks = [e for e in locks.events if e[0] == "lock" and e[1] == MergeAudio._meta.db_table]
        self.assertEqual([e[3] for e in audio_locks], [False])
        row.refresh_from_db()
        self.assertEqual((row.status, row.credits_charged, row.credits_reserved), ("ready", 5, 0))
        self.assertFalse(MergeAudio.objects.filter(pk=old.pk).exists())
        self.assertEqual(self.ledger(), [("merge_voice", -5)])

    def test_delivery_to_a_deleted_merge_is_gone(self):
        row = self.track(status="pending", credits_reserved=5, text=TEXT, voice_id="voice1")
        MergeProject.objects.filter(pk=self.p.pk).delete()
        with self.assertRaises(audio._Gone):
            audio._deliver(row.pk, self.owner.pk, path="merge/audio/x.mp3", duration=3.0)
        self.assertEqual(self.ledger(), [])

    def test_settings_patch_takes_the_same_order(self):
        # Сценарий W4: голос ещё делается, а человек двигает его начало (PATCH обновляет и pending-строку).
        row = self.track(status="pending", credits_reserved=5, text=TEXT, voice_id="voice1")
        with _Locks() as locks:
            audio.update_settings(self.owner, self.p.uid, {"voice_start_fragment": 1, "music_volume": 0.5})
        self.assertLockOrder(locks)
        row.refresh_from_db()
        self.assertEqual(row.start_fragment, 1)
        with _Locks() as volume_only:
            audio.update_settings(self.owner, self.p.uid, {"voice_volume": 1.2})
        self.assertLockOrder(volume_only, full=False)
        self.assertEqual(volume_only.order(), ["user", "merge"])

    def test_orders_and_delete_take_the_same_order(self):
        with self.subTest("голос: заказ и доставка"):
            with _Locks() as locks:
                self.assertEqual(self.voice().status_code, 201)
            self.assertLockOrder(locks)
        with self.subTest("музыка: заказ"):
            with _Locks() as locks:
                self.assertEqual(self.order_music(execute=False).status_code, 202)
            self.assertLockOrder(locks, full=False)
        MergeAudio.objects.filter(project=self.p, kind=audio.MUSIC).delete()
        with self.subTest("удаление склейки: свои оборванные заказы закрывает уже под замком склейки"):
            with _Locks() as locks:
                services.delete_project(self.owner, self.p.uid)
            self.assertLockOrder(locks)
            self.assertFalse(MergeProject.objects.filter(pk=self.p.pk).exists())


class DeleteTests(_Audio):
    def test_delete_ready_track_and_its_file(self):
        row = self.track()
        with self.captureOnCommitCallbacks(execute=True):
            response = self.api.delete(self.url(f"{row.uid}/"))
        self.assertEqual((response.status_code, response.json()["tracks"]), (200, []))
        self.assertFalse(default_storage.exists(row.file))

    def test_refusals(self):
        pending = self.track(kind="music", status="pending", credits_reserved=6)
        response = self.api.delete(self.url(f"{pending.uid}/"))
        self.assertEqual((response.status_code, response.json()["error_code"]), (409, "audio_busy"))
        response = self.api.delete(self.url(f"{'a' * 32}/"))
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json(), {"error": "Дорожка не найдена.", "error_code": "audio_not_found"})
        other = self.project(self.owner, [self.take(self.owner)])
        foreign_track = self.track(project=other)
        self.assertEqual(self.api.delete(self.url(f"{foreign_track.uid}/")).status_code, 404)

    def test_failed_track_is_dismissed_without_touching_the_merge(self):
        self.set_status("failed", error="x", error_code="stale")
        row = self.track(status="failed", error_code="audio_failed")
        self.assertEqual(self.api.delete(self.url(f"{row.uid}/")).status_code, 200)
        self.p.refresh_from_db()
        self.assertEqual(self.p.status, "failed")


def _fake_render(seen):
    def run(paths, *, aspect, fit, workdir, progress=None, deadline=None, **kw):
        seen.append(kw)
        out = os.path.join(workdir, "merged.mp4")
        with open(out, "wb") as fh:
            fh.write(b"MERGED")
        return render.Rendered(path=out, duration=12.0)

    return run


def _fake_poster(src, dst, duration=None):
    with open(dst, "wb") as fh:
        fh.write(b"JPG")
    return True


class RenderTests(_Audio):
    def run_task(self, project=None, fake=None):
        project = project or self.p
        MergeProject.objects.filter(pk=project.pk).update(status="queued", credits_reserved=20,
                                                          queued_at=timezone.now())
        seen = []
        with patch("merge.services.ffmpeg.render", side_effect=fake or _fake_render(seen)), \
                patch("merge.services.ffmpeg.make_poster", side_effect=_fake_poster):
            tasks.render_merge.run(project.pk)
        project.refresh_from_db()
        return project, seen

    def test_sound_is_passed_to_the_render(self):
        voice = self.track(start_fragment=1, duration_s=3.2)
        music = self.track(kind="music")
        MergeProject.objects.filter(pk=self.p.pk).update(clip_sound="quiet", music_volume=0.5, voice_volume=1.4)
        project, seen = self.run_task()
        self.assertEqual(project.status, "ready")
        self.assertEqual(seen, [{"audio": render.AudioMix(
            clip_volume=0.3, voice=default_storage.path(voice.file), voice_volume=1.4, voice_duration=3.2,
            voice_fragment=1, music=default_storage.path(music.file), music_volume=0.5, expected_s=12.0)}])
        self.assertEqual(self.ledger(), [("merge_video", -20)])

    def test_without_sound_the_render_call_is_the_old_one(self):
        project, seen = self.run_task()
        self.assertEqual(project.status, "ready")
        self.assertEqual(seen, [{}])

    def test_quieter_clips_alone_still_mix(self):
        MergeProject.objects.filter(pk=self.p.pk).update(clip_sound="off")
        _, seen = self.run_task()
        self.assertEqual(seen, [{"audio": render.AudioMix(clip_volume=0.0, voice_volume=1.0, music_volume=0.35,
                                                          expected_s=12.0)}])

    def test_failed_and_pending_tracks_are_not_mixed(self):
        self.track(status="failed")
        _, seen = self.run_task()
        self.assertEqual(seen, [{}])

    def test_missing_track_file_fails_without_charge(self):
        voice = self.track()
        default_storage.delete(voice.file)
        project, _ = self.run_task()
        self.assertEqual((project.status, project.error_code, project.error, project.credits_reserved),
                         ("failed", "audio_missing", audio.MSG_MISSING, 0))
        self.assertEqual(self.ledger(), [])

    def test_mix_failure_releases_the_reserve(self):
        def broken(paths, **kw):
            raise render.RenderError(render.MSG_MIX_FAILED, "rc=1", code="mix_failed")

        self.track()
        project, _ = self.run_task(fake=broken)
        self.assertEqual((project.status, project.error_code, project.credits_reserved), ("failed", "mix_failed", 0))
        self.assertEqual(self.ledger(), [])

    def test_ready_merge_keeps_its_sound_as_long_as_itself(self):
        voice = self.track()
        project, _ = self.run_task()
        voice.refresh_from_db()
        self.assertEqual(voice.expires_at, project.expires_at)

    def test_start_holds_the_sound_for_a_day(self):
        voice = self.track(expires_at=timezone.now() + timedelta(hours=1))
        response = self.api.post(f"{BASE}{self.p.uid}/render/", {"price": 20}, format="json")
        self.assertEqual(response.status_code, 202)
        voice.refresh_from_db()
        self.assertGreater(voice.expires_at, timezone.now() + timedelta(hours=23))


class CopyTests(_Audio):
    def test_copy_takes_the_sound_with_own_files(self):
        voice = self.track(start_fragment=1, text=TEXT, voice_id="voice1", voice_name="Rachel", credits_charged=5)
        music = self.track(kind="music", source="upload", title="Мой трек")
        MergeProject.objects.filter(pk=self.p.pk).update(status="ready", clip_sound="off", music_volume=0.6,
                                                         voice_volume=1.2)
        before = self.balance(self.owner)
        response = self.api.post(BASE, {"items": [self.ref(self.take(self.owner))], "copy_audio_from": self.p.uid},
                                 format="json")
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json()["audio"], {"clip_sound": "off", "music_volume": 0.6, "voice_volume": 1.2,
                                                    "voice": True, "music": True, "pending": False})
        copy = MergeProject.objects.get(uid=response.json()["id"])
        rows = {r.kind: r for r in MergeAudio.objects.filter(project=copy)}
        self.assertEqual(set(rows), {"voice", "music"})
        self.assertEqual((rows["voice"].text, rows["voice"].voice_name, rows["voice"].start_fragment,
                          rows["voice"].credits_charged), (TEXT, "Rachel", 0, 0))
        self.assertEqual((rows["music"].source, rows["music"].title), ("upload", "Мой трек"))
        for old, new in ((voice, rows["voice"]), (music, rows["music"])):
            self.assertNotEqual(old.file, new.file)
            with default_storage.open(new.file, "rb") as fh:
                self.assertEqual(fh.read(), b"ID3TRACK")
        self.assertEqual(self.balance(self.owner), before)
        self.assertEqual(MergeAudio.objects.filter(project=self.p).count(), 2)

    def test_copied_voice_stays_with_its_clip(self):
        t1, t2, t3 = self.take(self.owner), self.take(self.owner), self.take(self.owner)
        cases = (
            # Пропавший фрагмент перед голосом убран — голос едет за своим роликом (было: под №3 — чужой ролик).
            ([t1, t2, t3], 2, [t1, t3], 1),
            # Убран сам ролик голоса — прежний номер, на нём теперь следующий ролик.
            ([t1, t2, t3], 1, [t1, t3], 1),
            # Ролик дважды: голос под вторым его появлением остаётся под вторым.
            ([t1, t2, t1], 2, [t2, t1, t1], 2),
            # Номер старше списка (фрагменты убирали после озвучки) — как у сервера: последний.
            ([t1, t2], 5, [t2, t1], 0),
        )
        for old, start, new, expected in cases:
            with self.subTest(start=start):
                source = self.project(self.owner, old)
                self.track(project=source, start_fragment=start, credits_charged=5)
                response = self.api.post(BASE, {"items": [self.ref(t) for t in new], "copy_audio_from": source.uid},
                                         format="json")
                self.assertEqual(response.status_code, 201)
                row = MergeAudio.objects.get(project__uid=response.json()["id"], kind="voice")
                self.assertEqual(row.start_fragment, expected)

    def test_copy_skips_unfinished_and_lost_tracks(self):
        lost = self.track()
        default_storage.delete(lost.file)
        self.track(kind="music", status="pending", credits_reserved=6)
        response = self.api.post(BASE, {"items": [], "copy_audio_from": self.p.uid}, format="json")
        self.assertEqual(response.status_code, 201)
        self.assertFalse(MergeAudio.objects.filter(project__uid=response.json()["id"]).exists())

    def test_copy_from_someone_elses_merge_is_404(self):
        other = self.project(self.stranger, [self.take(self.stranger)])
        for source in (other.uid, "f" * 32, "junk", 12):
            with self.subTest(source=source):
                response = self.api.post(BASE, {"items": [], "copy_audio_from": source}, format="json")
                self.assertEqual((response.status_code, response.json()["error_code"]), (404, "project_not_found"))
        self.assertEqual(MergeProject.objects.filter(user=self.owner).count(), 1)


class CleanupTests(_Audio):
    def test_deleting_the_merge_deletes_its_sound(self):
        row = self.track()
        with self.captureOnCommitCallbacks(execute=True):
            self.assertEqual(self.api.delete(f"{BASE}{self.p.uid}/").status_code, 204)
        self.assertFalse(MergeAudio.objects.filter(pk=row.pk).exists())
        self.assertFalse(default_storage.exists(row.file))

    def test_sound_expires_with_the_merge(self):
        row = self.track()
        MergeProject.objects.filter(pk=self.p.pk).update(status="ready", expires_at=timezone.now() - timedelta(hours=1))
        with self.captureOnCommitCallbacks(execute=True):
            self.assertEqual(services.purge_expired(), 1)
        self.assertFalse(MergeAudio.objects.filter(pk=row.pk).exists())
        self.assertFalse(default_storage.exists(row.file))

    def test_daily_purge_of_expired_sound(self):
        past = timezone.now() - timedelta(days=1)
        old = self.track(expires_at=past)
        fresh = self.track(kind="music")
        busy = self.project(self.owner, [self.take(self.owner)], status="queued", credits_reserved=20,
                            queued_at=timezone.now())
        held = self.track(project=busy, expires_at=past)
        making = self.track(kind="music", project=busy, status="pending", credits_reserved=6, expires_at=past)
        with self.captureOnCommitCallbacks(execute=True):
            self.assertEqual(tasks.purge_expired.run(), {"merges": 0, "uploads": 0, "audio": 1})
        self.assertFalse(MergeAudio.objects.filter(pk=old.pk).exists())
        self.assertFalse(default_storage.exists(old.file))
        self.assertEqual(set(MergeAudio.objects.values_list("pk", flat=True)), {fresh.pk, held.pk, making.pk})

    def test_stale_orders_are_closed_and_released(self):
        now = timezone.now()
        voice = self.track(status="pending", credits_reserved=5)
        other = self.project(self.owner, [self.take(self.owner)])
        queued = self.track(project=other, kind="music", status="pending", credits_reserved=6)
        third = self.project(self.owner, [self.take(self.owner)])
        started = self.track(project=third, kind="music", status="pending", credits_reserved=6,
                             started_at=now - timedelta(minutes=20))
        fourth = self.project(self.owner, [self.take(self.owner)])
        alive = self.track(project=fourth, kind="music", status="pending", credits_reserved=6,
                           started_at=now - timedelta(minutes=3))
        MergeAudio.objects.filter(pk=voice.pk).update(created_at=now - timedelta(minutes=11))
        MergeAudio.objects.filter(pk=queued.pk).update(created_at=now - timedelta(hours=3))
        self.assertEqual(services.reserved_credits(self.owner), 23)
        self.assertEqual(tasks.fail_stale_renders.run(), {"queued": 0, "rendering": 0, "audio": 3})
        for row in (voice, queued, started):
            row.refresh_from_db()
            self.assertEqual((row.status, row.error_code, row.credits_reserved), ("failed", "audio_stale", 0))
        alive.refresh_from_db()
        self.assertEqual(alive.status, "pending")
        self.assertEqual(services.reserved_credits(self.owner), 6)

    def test_account_deletion_removes_the_files(self):
        row = self.track()
        with self.captureOnCommitCallbacks(execute=True):
            self.owner.delete()
        self.assertFalse(default_storage.exists(row.file))


class LedgerTests(_Audio):
    def test_reasons(self):
        self.assertEqual(TokenTransactionReason.MERGE_VOICE.label, "Склейка: голос")
        self.assertEqual(TokenTransactionReason.MERGE_MUSIC.label, "Склейка: музыка")
        self.assertEqual(MERGE_SPEND_REASONS, ("merge_video", "merge_voice", "merge_music"))
        self.assertEqual((audio.REASON_VOICE, audio.REASON_MUSIC), ("merge_voice", "merge_music"))

    @override_settings(CACHES={"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}})
    def test_admin_spend_counts_the_sound(self):
        staff = self.user(balance=0, is_staff=True)
        for reason, delta in (("chat", -1), ("merge_video", -20), ("merge_voice", -5), ("merge_music", -6),
                              ("cartoon_voice", -9), ("purchase", 100)):
            TokenTransaction.objects.create(user=self.owner, delta=delta, reason=reason, balance_after=0)
        with patch("adminapi.views._openrouter_summary", return_value={}):
            data = client_for(staff).get("/api/manage/summary/").json()
        self.assertEqual((data["credits_spent_total"], data["requests_total"], data["credits_spent_vstudio_total"]),
                         (32, 4, 0))
