"""«Голос сцены» склейки: ключи фрагментов, заказ и деньги, правка секунды и громкости,
«потерявшие» ролик голоса, передача в склейку, копия, уборка.

ElevenLabs подменён так же, как в test_audio_api (_Audio): tts отдаёт байты, save_audio
кладёт файл без ffmpeg. Сами команды ffmpeg — в test_scene_lines_render.
"""
from __future__ import annotations

import re
from datetime import timedelta
from unittest.mock import patch

from django.core.files.storage import default_storage
from django.utils import timezone

from cartoon import audio as studio
from merge import audio, render, services, tasks
from ai.models import GenerationLog
from merge.models import MergeAudio, MergeAudioRequest, MergeProject
from plans.models import TokenTransaction
from vstudio.models import Asset, Take

from .helpers import client_for
from .test_audio_api import BASE, TEXT, _Audio, _fake_poster, _fake_render, _Locks

KEY = re.compile(r"^[0-9a-f]{12}$")


class _Lines(_Audio):
    def setUp(self):
        super().setUp()
        # Предел заказов звука (10 в минуту) проверяют свои тесты; здесь запросов больше.
        patcher = patch("merge.views_audio.AudioThrottle.allow_request", return_value=True)
        patcher.start()
        self.addCleanup(patcher.stop)

    def keys(self, project=None) -> list[str]:
        project = project or self.p
        project.refresh_from_db()
        return [i.get("key") for i in project.items]

    def key(self, index: int, project=None) -> str:
        return self.keys(project)[index]

    def line(self, index: int = 0, client=None, project=None, **body):
        project = project or self.p
        payload = {"text": TEXT, "voice_id": "voice1", "fragment_key": self.key(index, project), "start_s": 0.0,
                   **body}
        return (client or self.api).post(self.url("line/", project), payload, format="json")

    def line_row(self, index: int = 0, project=None, *, status="ready", **kw) -> MergeAudio:
        project = project or self.p
        items = services.ensure_keys(project)
        fields = dict(kind="line", fragment_key=self.key(index, project),
                      fragment_ref=services.item_ref(items[index]), start_s=0.0, text=TEXT,
                      voice_id="voice1", voice_name="Rachel", credits_charged=5 if status == "ready" else 0)
        fields.update(kw)
        return self.track(project=project, status=status, **fields)

    def patch_line(self, row, client=None, project=None, **body):
        return (client or self.api).patch(self.url(f"{row.uid}/", project), body, format="json")

    def state(self, project=None) -> dict:
        return self.api.get(self.url(project=project)).json()

    def put_items(self, refs, project=None):
        project = project or self.p
        return self.api.patch(f"{BASE}{project.uid}/", {"items": refs}, format="json")

    def refs_with_keys(self, project=None) -> list[dict]:
        project = project or self.p
        project.refresh_from_db()
        return [{"type": i["type"], "id": i["id"], "key": i["key"]} for i in project.items]


class FragmentKeyTests(_Lines):
    def test_new_merge_gets_unique_keys(self):
        t1, t2 = self.take(self.owner), self.take(self.owner)
        response = self.api.post(BASE, {"items": [self.ref(t1), self.ref(t2), self.ref(t1)]}, format="json")
        self.assertEqual(response.status_code, 201)
        items = response.json()["items"]
        keys = [i["key"] for i in items]
        self.assertTrue(all(KEY.match(k) for k in keys), keys)
        self.assertEqual(len(set(keys)), 3, "один ролик дважды — два разных ключа")
        stored = MergeProject.objects.get(uid=response.json()["id"]).items
        self.assertEqual([i["key"] for i in stored], keys)

    def test_reorder_with_keys_keeps_them(self):
        refs = self.refs_with_keys()
        response = self.put_items([refs[1], refs[0]])
        self.assertEqual(response.status_code, 200)
        self.assertEqual([i["key"] for i in response.json()["items"]], [refs[1]["key"], refs[0]["key"]])
        self.assertEqual(self.keys(), [refs[1]["key"], refs[0]["key"]])

    def test_reorder_without_keys_follows_the_clip(self):
        # Старый клиент шлёт только {type, id}: ключ едет за своим роликом (то же появление по счёту).
        before = self.refs_with_keys()
        plain = [{"type": r["type"], "id": r["id"]} for r in before]
        self.assertEqual(self.put_items([plain[1], plain[0]]).status_code, 200)
        self.assertEqual(self.keys(), [before[1]["key"], before[0]["key"]])

    def test_same_clip_twice_keeps_each_appearance(self):
        t1, t2 = self.take(self.owner), self.take(self.owner)
        project = self.project(self.owner, [t1, t2, t1])
        k = self.keys(project)
        plain = [self.ref(t1), self.ref(t1), self.ref(t2)]
        self.assertEqual(self.put_items(plain, project).status_code, 200)
        self.assertEqual(self.keys(project), [k[0], k[2], k[1]])

    def test_add_and_remove_keep_the_rest(self):
        refs = self.refs_with_keys()
        extra = self.take(self.owner)
        client_key = "abcdef012345"
        response = self.put_items([refs[1], {**self.ref(extra), "key": client_key}])
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.keys(), [refs[1]["key"], client_key])
        # Без ключа новый фрагмент получает новый ключ, прежние — свои.
        response = self.put_items([*self.refs_with_keys(), self.ref(self.take(self.owner))])
        keys = self.keys()
        self.assertEqual(keys[:2], [refs[1]["key"], client_key])
        self.assertTrue(KEY.match(keys[2]))
        self.assertNotIn(keys[2], (refs[0]["key"], refs[1]["key"], client_key))

    def test_bad_and_repeated_client_keys_are_replaced(self):
        refs = self.refs_with_keys()
        for bad in ("f1", "XYZ", 12345, None, "a" * 40, "0123456789abcdefZ"):
            with self.subTest(bad=bad):
                response = self.put_items([refs[0], {"type": refs[1]["type"], "id": refs[1]["id"], "key": bad}])
                self.assertEqual(response.status_code, 200)
                keys = self.keys()
                self.assertEqual(keys[0], refs[0]["key"])
                # Ключа не прислали годного — ключ того же ролика из прежнего списка.
                self.assertEqual(keys[1], refs[1]["key"])
        # Один ключ дважды — второй фрагмент получает свой.
        response = self.put_items([refs[0], {**{k: refs[1][k] for k in ("type", "id")}, "key": refs[0]["key"]}])
        keys = self.keys()
        self.assertEqual(keys[0], refs[0]["key"])
        self.assertNotEqual(keys[1], keys[0])

    def test_legacy_merge_without_keys(self):
        legacy = [{k: v for k, v in i.items() if k != "key"} for i in self.p.items]
        MergeProject.objects.filter(pk=self.p.pk).update(items=legacy)
        first = self.api.get(f"{BASE}{self.p.uid}/").json()["items"]
        second = self.api.get(f"{BASE}{self.p.uid}/").json()["items"]
        keys = [i["key"] for i in first]
        self.assertTrue(all(KEY.match(k) for k in keys))
        self.assertEqual(keys, [i["key"] for i in second], "ключи старой склейки одни и те же при каждом чтении")
        self.p.refresh_from_db()
        self.assertTrue(all("key" not in i for i in self.p.items), "чтение ничего не пишет")
        self.assertEqual(self.state()["fragments"], 2)
        # Сохранение без ключей (старый клиент) записывает те же выведенные ключи — порядок поменяли.
        plain = [{"type": i["type"], "id": i["id"]} for i in first]
        self.assertEqual(self.put_items([plain[1], plain[0]]).status_code, 200)
        self.assertEqual(self.keys(), [keys[1], keys[0]])

    def test_render_start_keeps_the_keys(self):
        keys = self.keys()
        response = self.api.post(f"{BASE}{self.p.uid}/render/", {"price": 20}, format="json")
        self.assertEqual(response.status_code, 202)
        self.assertEqual(self.keys(), keys)
        # Запуск с правкой фрагментов в теле — те же правила.
        MergeProject.objects.filter(pk=self.p.pk).update(status="failed", credits_reserved=0)
        refs = self.refs_with_keys()
        response = self.api.post(f"{BASE}{self.p.uid}/render/", {"price": 20, "items": [refs[1], refs[0]]},
                                 format="json")
        self.assertEqual(response.status_code, 202)
        self.assertEqual(self.keys(), [keys[1], keys[0]])

    def test_helpers(self):
        self.assertEqual(services.valid_key(" ABCDEF012345 "), "abcdef012345")
        self.assertEqual(services.valid_key("abc"), "")
        self.assertEqual(services.parse_keys([{"key": "abcdef01"}, "x", {"type": "chat"}]), ["abcdef01", "", ""])
        items = [{"type": "chat", "id": "1", "key": "abcdef01"}, {"type": "chat", "id": "2", "key": "abcdef01"},
                 "junk", {"type": "chat", "id": "3"}]
        keys = services.item_keys(items, "u" * 32)
        self.assertEqual(len(keys), 3)
        self.assertEqual(keys[0], "abcdef01")
        self.assertEqual(len(set(keys)), 3)


class LineCreateTests(_Lines):
    def test_line_is_made_then_charged(self):
        response = self.line(1, start_s=2.5, volume=1.4, request_id="l-1")
        self.assertEqual(response.status_code, 201)
        body = response.json()
        line = body["line"]
        key = self.key(1)
        self.assertEqual({k: line[k] for k in ("kind", "status", "fragment_key", "fragment_index", "start_s",
                                                "volume", "orphan", "overflow", "credits_charged",
                                                "credits_reserved", "duration_s", "voice_name", "text",
                                                "request_id", "fragment_duration_s", "max_start_s")},
                         {"kind": "line", "status": "ready", "fragment_key": key, "fragment_index": 1,
                          "start_s": 2.5, "volume": 1.4, "orphan": False, "overflow": False, "credits_charged": 5,
                          "credits_reserved": 0, "duration_s": 3.0, "voice_name": "Rachel", "text": TEXT,
                          "request_id": "l-1", "fragment_duration_s": 7.0, "max_start_s": 6.9})
        self.assertTrue(line["url"].startswith(f"/media/merge/audio/{self.owner.pk}/"))
        self.assertEqual(body["balance"]["balance"], 495)
        self.assertEqual(body["tracks"], [], "голос за кадром и музыка — отдельно от голосов сцен")
        self.assertEqual([x["id"] for x in body["lines"]], [line["id"]])
        self.tts.assert_called_once_with(TEXT, "voice1")
        # Метка ролика — по ней голос вернётся, если ролик уберут и добавят снова.
        self.p.refresh_from_db()
        item = self.p.items[1]
        self.assertEqual(MergeAudio.objects.get(uid=line["id"]).fragment_ref, f"{item['type']}:{item['id']}")
        row = TokenTransaction.objects.get(user=self.owner)
        self.assertEqual((row.reason, row.delta), ("merge_voice", -5))
        self.assertEqual((row.meta["kind"], row.meta["chars"], row.meta["fragment"]), ("line", 20, key))
        self.assertEqual(self.balance(self.owner), 495)
        summary = self.api.get(f"{BASE}{self.p.uid}/").json()["audio"]
        self.assertEqual((summary["lines"], summary["voice"], summary["pending"]), (1, False, False))

    def test_price_like_the_voice_and_quoted_in_state(self):
        state = self.state()
        self.assertEqual(state["prices"], {"voice_per_1k": 20, "voice_min": 5, "music_per_min": 30})
        self.assertEqual((state["limits"]["line_chars"], state["limits"]["lines_per_fragment"],
                          state["limits"]["lines_max"], state["limits"]["line_volume_max"],
                          state["limits"]["line_start_step"]), (500, 3, 40, 2.0, 0.1))
        response = self.line(0, text="а" * 500, price=10)
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json()["line"]["credits_charged"], studio.voice_price("а" * 500))
        response = self.line(0, price=7)
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json(), {"error": "Цена изменилась: теперь 5 кр. Проверьте и нажмите ещё раз.",
                                           "error_code": "audio_price_changed", "credits": 5})

    def test_reserve_is_held_while_the_provider_works(self):
        seen = {}

        def tts(text, voice_id):
            seen["reserved"] = services.reserved_credits(self.owner)
            seen["status"] = MergeAudio.objects.get(project=self.p, kind="line").status
            seen["summary"] = audio.summary(self.p)["pending"]
            return b"ID3"

        self.tts.side_effect = tts
        self.assertEqual(self.line(0).status_code, 201)
        self.assertEqual(seen, {"reserved": 5, "status": "pending", "summary": True})
        self.assertEqual(services.reserved_credits(self.owner), 0)

    def test_provider_failure_releases_and_retry_replaces_the_failure(self):
        self.tts.side_effect = studio.AudioProviderError("/v1/tts: http 500: boom")
        response = self.line(0)
        self.assertEqual((response.status_code, response.json()["error_code"]), (502, "audio_failed"))
        row = MergeAudio.objects.get(project=self.p, kind="line")
        self.assertEqual((row.status, row.credits_reserved, row.credits_charged), ("failed", 0, 0))
        self.assertEqual((self.ledger(), self.balance(self.owner)), ([], 500))
        self.assertEqual(self.saved, [])
        failed = self.state()["lines"][0]
        self.assertEqual((failed["status"], failed["error_code"]), ("failed", "audio_failed"))
        # Неудача у другого фрагмента не трогается; новая попытка у этого — заменяет неудачу.
        self.line(1)
        self.tts.side_effect = None
        self.assertEqual(self.line(0).status_code, 201)
        rows = sorted((r.fragment_key == self.key(0), r.status) for r in self.rows(kind="line"))
        self.assertEqual(rows, [(False, "failed"), (True, "ready")])
        self.assertEqual(self.ledger(), [("merge_voice", -5)])

    def test_same_request_id_is_answered_once(self):
        first = self.line(0, request_id="click-1")
        second = self.line(0, request_id="click-1")
        self.assertEqual((first.status_code, second.status_code), (201, 200))
        self.assertEqual(first.json()["line"]["id"], second.json()["line"]["id"])
        self.assertEqual(self.tts.call_count, 1)
        self.assertEqual(self.ledger(), [("merge_voice", -5)])

    def test_removed_line_is_not_ordered_again_by_the_same_click(self):
        first = self.line(1, start_s=1.5, request_id="click-7").json()["line"]
        self.assertEqual(self.api.delete(self.url(f"{first['id']}/")).status_code, 200)
        replay = self.line(1, start_s=1.5, request_id="click-7")
        self.assertEqual(replay.status_code, 200)
        line = replay.json()["line"]
        self.assertEqual((line["id"], line["url"], line["fragment_key"], line["start_s"], line["request_id"]),
                         (first["id"], None, self.key(1), 1.5, "click-7"))
        self.assertEqual(replay.json()["lines"], [])
        self.assertEqual(self.tts.call_count, 1)
        self.assertEqual(self.ledger(), [("merge_voice", -5)])
        self.assertTrue(MergeAudioRequest.objects.filter(project=self.p, kind="line", request_id="click-7").exists())

    def test_insufficient_balance_is_402(self):
        poor = self.user(balance=3)
        project = self.project(poor, [self.take(poor), self.take(poor)])
        response = self.line(0, client=client_for(poor), project=project)
        self.assertEqual(response.status_code, 402)
        self.assertEqual(response.json(), {"error": "Недостаточно кредитов для озвучки.",
                                           "error_code": "insufficient_balance", "balance_tokens": 3,
                                           "required_estimate": 5})
        self.tts.assert_not_called()
        self.assertEqual(self.rows(project), [])

    def test_validation(self):
        k0 = self.key(0)
        cases = (
            ({"text": "  "}, "bad_request", {"field": "text"}, audio.MSG_NO_TEXT),
            ({"text": "a" * 501}, "voice_too_long", {"max": 500}, "Текст длиннее 500 символов — сократите его."),
            ({"voice_id": "../x"}, "bad_request", {"field": "voice_id"}, audio.MSG_NO_VOICE),
            ({"fragment_key": ""}, "bad_request", {"field": "fragment_key"}, audio.MSG_LINE_NO_FRAGMENT),
            ({"fragment_key": "0123456789ab"}, "bad_request", {"field": "fragment_key"}, audio.MSG_LINE_NO_FRAGMENT),
            ({"fragment_key": 5}, "bad_request", {"field": "fragment_key"}, audio.MSG_LINE_NO_FRAGMENT),
            ({"start_s": -0.1}, "bad_request", {"field": "start_s"}, audio.MSG_LINE_BAD_START_ANY),
            ({"start_s": True}, "bad_request", {"field": "start_s"}, audio.MSG_LINE_BAD_START_ANY),
            ({"start_s": "x"}, "bad_request", {"field": "start_s"}, audio.MSG_LINE_BAD_START_ANY),
            ({"start_s": 5.0}, "bad_request",
             {"field": "start_s", "max_start_s": 4.9, "fragment_duration_s": 5.0},
             "Секунда начала — число от 0 до 4.9 (длина фрагмента 5 с)."),
            ({"start_s": 4.96}, "bad_request",
             {"field": "start_s", "max_start_s": 4.9, "fragment_duration_s": 5.0},
             "Секунда начала — число от 0 до 4.9 (длина фрагмента 5 с)."),
            ({"volume": 2.5}, "bad_request", {"field": "volume"}, audio.MSG_LINE_BAD_VOLUME),
            ({"volume": -1}, "bad_request", {"field": "volume"}, audio.MSG_LINE_BAD_VOLUME),
            ({"volume": "1"}, "bad_request", {"field": "volume"}, audio.MSG_LINE_BAD_VOLUME),
        )
        for body, code, extra, text in cases:
            with self.subTest(body=body):
                payload = {"text": TEXT, "voice_id": "voice1", "fragment_key": k0, "start_s": 0, **body}
                response = self.api.post(self.url("line/"), payload, format="json")
                self.assertEqual(response.status_code, 400, response.content)
                self.assertEqual(response.json(), {"error": text, "error_code": code, **extra})
        # Не число в JSON не пришлёшь, но и такое — отказ, а не голос с секунды «nan».
        for raw in (float("nan"), float("inf"), [1], {"s": 1}):
            with self.subTest(raw=raw), self.assertRaises(services.MergeError):
                audio._start_s(raw)
        self.tts.assert_not_called()
        self.assertEqual(self.rows(), [])
        # Граница: 4,9 с во фрагменте 5 с — можно; 4,94 округляется до 4,9; строка-число тоже число.
        for start in (4.9, 4.94, "1.25"):
            with self.subTest(start=start):
                self.assertEqual(self.line(0, start_s=start).status_code, 201)
        self.assertEqual(sorted(r.start_s for r in self.rows(kind="line")), [1.2, 4.9, 4.9])

    def test_limits_per_fragment_and_per_merge(self):
        for _ in range(3):
            self.assertEqual(self.line(0).status_code, 201)
        response = self.line(0)
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json(), {"error": "У этого фрагмента уже 3 голоса — уберите лишний, чтобы "
                                                    "добавить новый.", "error_code": "line_fragment_full", "max": 3})
        # Неудачные не считаются.
        self.line_row(1, status="failed")
        self.line_row(1, status="failed")
        self.line_row(1, status="failed")
        self.assertEqual(self.line(1).status_code, 201)
        with patch("merge.audio.LINES_MAX", 4):
            response = self.line(1)
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json(), {"error": "В склейке уже 4 голосов сцен — уберите лишние, чтобы "
                                                    "добавить новый.", "error_code": "lines_limit", "max": 4})
        self.assertEqual(self.ledger(), [("merge_voice", -5)] * 4)

    def test_one_in_progress_per_fragment(self):
        self.line_row(0, status="pending", credits_reserved=5)
        response = self.line(0)
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json(), {"error": audio.MSG_LINE_BUSY, "error_code": "line_busy"})
        # Другой фрагмент и голос за кадром — можно, пока этот делается.
        self.assertEqual(self.line(1).status_code, 201)
        self.assertEqual(self.voice().status_code, 201)
        self.assertEqual(self.tts.call_count, 2)

    def test_lines_and_the_global_voice_live_together(self):
        self.assertEqual(self.voice(request_id="v").status_code, 201)
        self.assertEqual(self.line(0, request_id="a").status_code, 201)
        self.assertEqual(self.line(1, request_id="b").status_code, 201)
        self.assertEqual(self.line(1, start_s=3, request_id="c").status_code, 201)
        # Новый голос за кадром заменяет только прежний голос за кадром.
        self.assertEqual(self.voice(text="Другой", request_id="v2").status_code, 201)
        state = self.state()
        self.assertEqual([(t["kind"], t["text"]) for t in state["tracks"]], [("voice", "Другой")])
        self.assertEqual([(x["fragment_index"], x["start_s"]) for x in state["lines"]], [(0, 0.0), (1, 0.0), (1, 3.0)])
        self.assertEqual(len(self.ledger()), 5)

    def test_locked_merges(self):
        for status, code in (("ready", "audio_ready_locked"), ("queued", "render_in_progress"),
                             ("rendering", "render_in_progress")):
            with self.subTest(status=status):
                self.set_status(status, credits_reserved=20 if status != "ready" else 0)
                response = self.line(0)
                self.assertEqual((response.status_code, response.json()["error_code"]), (409, code))
        self.tts.assert_not_called()

    def test_failed_merge_returns_to_draft(self):
        self.set_status("failed", error="старое", error_code="join_failed")
        self.assertEqual(self.line(0).status_code, 201)
        self.p.refresh_from_db()
        self.assertEqual((self.p.status, self.p.error_code), ("draft", ""))

    def test_render_waits_for_a_line_in_progress(self):
        self.line_row(0, status="pending", credits_reserved=5)
        response = self.api.post(f"{BASE}{self.p.uid}/render/", {"price": 20}, format="json")
        self.assertEqual((response.status_code, response.json()["error_code"]), (409, "audio_pending"))
        body = self.api.get(f"{BASE}{self.p.uid}/").json()
        self.assertEqual(body["render_block"]["error_code"], "audio_pending")

    def test_legacy_merge_gets_its_keys_written_with_the_first_line(self):
        legacy = [{k: v for k, v in i.items() if k != "key"} for i in self.p.items]
        MergeProject.objects.filter(pk=self.p.pk).update(items=legacy)
        shown = [i["key"] for i in self.api.get(f"{BASE}{self.p.uid}/").json()["items"]]
        response = self.api.post(self.url("line/"), {"text": TEXT, "voice_id": "voice1", "fragment_key": shown[1],
                                                     "start_s": 1}, format="json")
        self.assertEqual(response.status_code, 201)
        self.assertEqual(self.keys(), shown)
        # Переставили старым клиентом — голос остаётся у своего ролика.
        plain = [{"type": i["type"], "id": i["id"]} for i in legacy]
        self.put_items([plain[1], plain[0]])
        self.assertEqual(self.state()["lines"][0]["fragment_index"], 0)

    def test_huge_and_non_finite_numbers_are_400_not_500(self):
        # float(10**400) бросает OverflowError, «1e400» — бесконечность: всё это отказ поля, не 500.
        k0 = self.key(0)
        cases = (({"start_s": 10 ** 400}, "start_s"), ({"start_s": "1e400"}, "start_s"),
                 ({"start_s": "-1e400"}, "start_s"), ({"start_s": "NaN"}, "start_s"),
                 ({"start_s": "Infinity"}, "start_s"), ({"start_s": "9" * 400}, "start_s"),
                 ({"volume": 10 ** 400}, "volume"), ({"volume": -(10 ** 400)}, "volume"))
        for body, field in cases:
            with self.subTest(body=str(body)[:40]):
                payload = {"text": TEXT, "voice_id": "voice1", "fragment_key": k0, "start_s": 0, **body}
                response = self.api.post(self.url("line/"), payload, format="json")
                self.assertEqual(response.status_code, 400, response.content[:200])
                self.assertEqual((response.json()["error_code"], response.json()["field"]), ("bad_request", field))
        for raw in (10 ** 400, "1e400", "nan", "inf"):
            with self.subTest(raw=str(raw)[:20]), self.assertRaises(services.MergeError):
                audio._start_s(raw)
        with self.assertRaises(services.MergeError):
            audio._volume(10 ** 400, 2.0, "volume", audio.MSG_LINE_BAD_VOLUME)
        # Звук роликов и громкости (PATCH audio/) — тот же разбор.
        response = self.api.patch(self.url(), {"music_volume": 10 ** 400}, format="json")
        self.assertEqual((response.status_code, response.json()["field"]), (400, "music_volume"))
        for raw in ("9" * 5000, "²", 10 ** 400):
            with self.subTest(voice_start_fragment=str(raw)[:10]):
                self.assertIsNone(audio._fragment_index(raw))
                response = self.api.patch(self.url(), {"voice_start_fragment": raw}, format="json")
                self.assertEqual((response.status_code, response.json()["field"]), (400, "voice_start_fragment"))
        self.tts.assert_not_called()
        self.assertEqual(self.rows(), [])

    def test_unavailable_fragment_is_refused_before_money(self):
        t1, t2, t3 = self.take(self.owner), self.take(self.owner), self.take(self.owner)
        project = self.project(self.owner, [t1, t2, t3])
        # Ролик удалили, другой вернулся в «не готов» — голос к ним не заказать.
        Asset.objects.filter(pk=t2.result_asset_id).update(deleted_at=timezone.now())
        Take.objects.filter(pk=t3.pk).update(status=Take.STATUS_FAILED)
        for index in (1, 2):
            with self.subTest(index=index):
                response = self.line(index, project=project)
                self.assertEqual(response.status_code, 409, response.content)
                self.assertEqual(response.json(), {"error": audio.MSG_LINE_UNAVAILABLE,
                                                   "error_code": "line_unavailable", "index": index})
        self.tts.assert_not_called()
        self.assertEqual(self.rows(project=project), [])
        self.assertEqual(self.balance(self.owner), 500)
        self.assertEqual(TokenTransaction.objects.filter(user=self.owner).count(), 0)
        # Доступный фрагмент той же склейки — как обычно.
        self.assertEqual(self.line(0, project=project).status_code, 201)

    def test_line_is_journaled_as_voice(self):
        self.assertEqual(self.line(0).status_code, 201)
        log = GenerationLog.objects.get(user=self.owner)
        kinds = {k for k, _ in GenerationLog.KIND_CHOICES}
        self.assertIn(log.kind, kinds)
        self.assertEqual((log.kind, log.status, log.params["track"]), ("voice", "delivered", "line"))
        self.assertEqual(MergeAudio.objects.get(project=self.p).kind, "line")

    def test_guest_and_stranger(self):
        key = self.key(0)
        payload = {"text": TEXT, "voice_id": "voice1", "fragment_key": key}
        response = client_for(self.stranger).post(self.url("line/"), payload, format="json")
        self.assertEqual((response.status_code, response.json()["error_code"]), (404, "project_not_found"))
        response = client_for(self.stranger).patch(self.url(f"{'a' * 32}/"), {"start_s": 1}, format="json")
        self.assertEqual((response.status_code, response.json()["error_code"]), (404, "project_not_found"))
        # Гость — последним: в тестовой базе ответ 401 вне транзакции запроса ломает общую транзакцию
        # теста (так же у голоса за кадром), запросов после него нет.
        self.assertEqual(client_for().post(self.url("line/"), payload, format="json").status_code, 401)

    def test_not_configured(self):
        self.is_configured.return_value = False
        response = self.line(0)
        self.assertEqual((response.status_code, response.json()["error_code"]), (503, "audio_not_configured"))


class LinePatchTests(_Lines):
    def test_start_and_volume_are_saved_for_free(self):
        row = self.line_row(1)
        response = self.patch_line(row, start_s=6.94, volume=0.5)
        self.assertEqual(response.status_code, 200)
        line = response.json()["line"]
        self.assertEqual((line["start_s"], line["volume"], line["overflow"]), (6.9, 0.5, True))
        row.refresh_from_db()
        self.assertEqual((row.start_s, row.volume), (6.9, 0.5))
        self.assertEqual(self.ledger(), [])
        self.assertEqual(self.patch_line(row, start_s=0).json()["line"]["overflow"], False)

    def test_validation_is_all_or_nothing(self):
        row = self.line_row(0, start_s=1.0, volume=1.0)
        cases = (({"start_s": 5.0}, "start_s"), ({"start_s": -1}, "start_s"), ({"start_s": None}, "start_s"),
                 ({"start_s": True}, "start_s"), ({"volume": 2.01}, "volume"), ({"volume": False}, "volume"),
                 ({"start_s": 2.0, "volume": 9}, "volume"), ({"start_s": 10 ** 400}, "start_s"),
                 ({"start_s": "1e400"}, "start_s"), ({"start_s": "NaN"}, "start_s"),
                 ({"start_s": "-Infinity"}, "start_s"), ({"volume": 10 ** 400}, "volume"))
        for body, field in cases:
            with self.subTest(body=body):
                response = self.patch_line(row, **body)
                self.assertEqual(response.status_code, 400)
                self.assertEqual(response.json()["field"], field)
        row.refresh_from_db()
        self.assertEqual((row.start_s, row.volume), (1.0, 1.0))
        response = self.api.patch(self.url(f"{row.uid}/"), [1, 2], format="json")
        self.assertEqual(response.status_code, 400)

    def test_empty_patch_changes_nothing(self):
        row = self.line_row(0)
        self.set_status("failed", error="x", error_code="join_failed")
        response = self.patch_line(row)
        self.assertEqual(response.status_code, 200)
        self.p.refresh_from_db()
        self.assertEqual(self.p.status, "failed")
        # Правка — и склейка снова черновик.
        self.assertEqual(self.patch_line(row, volume=0.7).status_code, 200)
        self.p.refresh_from_db()
        self.assertEqual(self.p.status, "draft")

    def test_refusals(self):
        line = self.line_row(0)
        voice = self.track(kind="voice")
        failed = self.line_row(1, status="failed")
        response = self.patch_line(voice, volume=1.0)
        self.assertEqual((response.status_code, response.json()["field"]), (400, "track"))
        response = self.patch_line(failed, start_s=1)
        self.assertEqual((response.status_code, response.json()["error_code"]), (409, "line_failed"))
        response = self.api.patch(self.url(f"{'f' * 32}/"), {"start_s": 1}, format="json")
        self.assertEqual((response.status_code, response.json()["error_code"]), (404, "audio_not_found"))
        response = self.patch_line(line, client=client_for(self.stranger), start_s=1)
        self.assertEqual((response.status_code, response.json()["error_code"]), (404, "project_not_found"))
        self.set_status("ready")
        response = self.patch_line(line, start_s=1)
        self.assertEqual((response.status_code, response.json()["error_code"]), (409, "audio_ready_locked"))

    def test_pending_line_can_be_moved(self):
        row = self.line_row(0, status="pending", credits_reserved=5)
        self.assertEqual(self.patch_line(row, start_s=2.2).status_code, 200)
        row.refresh_from_db()
        self.assertEqual(row.start_s, 2.2)

    def test_lock_order(self):
        row = self.line_row(0)
        with _Locks() as locks:
            audio.update_line(self.owner, self.p.uid, row.uid, {"start_s": 1.0, "volume": 0.8})
        self.assertEqual(locks.order(), list(audio.LOCK_ORDER))
        self.assertEqual(locks.joined(), [])

    def test_line_order_and_delivery_take_the_agreed_lock_order(self):
        with _Locks() as locks:
            self.assertEqual(self.line(0).status_code, 201)
        self.assertEqual(locks.order(), list(audio.LOCK_ORDER))
        self.assertEqual(locks.joined(), [])

    def test_delete_line_and_its_file(self):
        row = self.line_row(0)
        with self.captureOnCommitCallbacks(execute=True):
            response = self.api.delete(self.url(f"{row.uid}/"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["lines"], [])
        self.assertFalse(default_storage.exists(row.file))


class OrphanTests(_Lines):
    def test_removed_clip_leaves_an_orphan_that_is_not_deleted(self):
        refs = self.refs_with_keys()
        row = self.line_row(1, start_s=2.0)
        extra = self.take(self.owner)
        self.assertEqual(self.put_items([refs[0], self.ref(extra)]).status_code, 200)
        line = self.state()["lines"][0]
        self.assertEqual((line["id"], line["orphan"], line["fragment_index"], line["max_start_s"]),
                         (row.uid, True, None, None))
        self.assertEqual(self.api.get(f"{BASE}{self.p.uid}/").json()["audio"]["lines"], 0)
        self.assertTrue(MergeAudio.objects.filter(pk=row.pk).exists())
        response = self.patch_line(row, start_s=1.0)
        self.assertEqual((response.status_code, response.json()["error_code"]), (409, "line_orphan"))
        # Ролик вернули с его ключом (клиент помнит карточку) — голос снова у него.
        self.assertEqual(self.put_items([refs[0], self.ref(extra), refs[1]]).status_code, 200)
        line = self.state()["lines"][0]
        self.assertEqual((line["orphan"], line["fragment_index"]), (False, 2))

    def test_clip_added_again_with_a_new_key_gets_its_voices_back(self):
        # Ошибочный ✕ и снова «Добавить»: у карточки новый ключ клиента, но голос оплачен —
        # сервер отдаёт карточке ключ голоса, и голос снова у своего ролика.
        refs = self.refs_with_keys()
        row = self.line_row(1, start_s=2.0)
        self.assertEqual(self.put_items([refs[0]]).status_code, 200)
        self.assertTrue(self.state()["lines"][0]["orphan"])
        back = {"type": refs[1]["type"], "id": refs[1]["id"], "key": "abcdef012345"}
        response = self.put_items([back, refs[0]])
        self.assertEqual(response.status_code, 200)
        self.assertEqual([i["key"] for i in response.json()["items"]], [refs[1]["key"], refs[0]["key"]])
        self.assertEqual(self.keys(), [refs[1]["key"], refs[0]["key"]])
        line = self.state()["lines"][0]
        self.assertEqual((line["id"], line["orphan"], line["fragment_index"], line["start_s"]),
                         (row.uid, False, 0, 2.0))
        # Дальше ключ держится как обычно: следующая правка его не меняет.
        self.assertEqual(self.put_items([refs[0], *self.refs_with_keys()[:1]]).status_code, 200)
        self.assertEqual(self.keys(), [refs[0]["key"], refs[1]["key"]])

    def test_clip_added_again_without_a_key_gets_its_voices_back(self):
        # Старый клиент без ключей: новый фрагмент того же ролика — тоже возвращает голос.
        refs = self.refs_with_keys()
        self.line_row(1, start_s=1.0)
        self.put_items([refs[0]])
        self.assertEqual(self.put_items([refs[0], {"type": refs[1]["type"], "id": refs[1]["id"]}]).status_code,
                         200)
        self.assertEqual(self.keys(), [refs[0]["key"], refs[1]["key"]])
        self.assertFalse(self.state()["lines"][0]["orphan"])

    def test_other_clip_and_failed_voice_do_not_take_the_key(self):
        refs = self.refs_with_keys()
        self.line_row(1, start_s=1.0)
        self.line_row(0, status="failed", credits_charged=0)
        self.put_items([])
        other = self.take(self.owner)
        self.assertEqual(self.put_items([{**self.ref(other), "key": "abcdef012345"}]).status_code, 200)
        self.assertEqual(self.keys(), ["abcdef012345"], "чужой ролик — голос не его")
        # Ролик, у которого остался только неудавшийся голос, ключа не забирает.
        self.assertEqual(self.put_items([{"type": refs[0]["type"], "id": refs[0]["id"], "key": "abcdef012346"}])
                         .status_code, 200)
        self.assertEqual(self.keys(), ["abcdef012346"])

    def test_same_clip_twice_gets_each_voice_back_oldest_first(self):
        t1, t2 = self.take(self.owner), self.take(self.owner)
        project = self.project(self.owner, [t1, t2, t1])
        k = self.keys(project)
        first = self.line_row(0, project=project, start_s=1.0)
        second = self.line_row(2, project=project, start_s=2.0)
        self.assertEqual(self.put_items([self.refs_with_keys(project)[1]], project).status_code, 200)
        self.assertEqual(self.put_items([*self.refs_with_keys(project), {**self.ref(t1), "key": "abcdef012345"}],
                                        project).status_code, 200)
        self.assertEqual(self.keys(project), [k[1], k[0]], "первым вернулся голос, заказанный раньше")
        self.assertEqual(self.put_items([*self.refs_with_keys(project), {**self.ref(t1), "key": "abcdef012346"}],
                                        project).status_code, 200)
        self.assertEqual(self.keys(project), [k[1], k[0], k[2]])
        lines = {x["id"]: x["fragment_index"] for x in self.state(project)["lines"]}
        self.assertEqual(lines, {first.uid: 1, second.uid: 2})

    def test_line_follows_its_clip_when_reordered(self):
        refs = self.refs_with_keys()
        self.line_row(0, start_s=1.0)
        self.put_items([refs[1], refs[0]])
        self.assertEqual(self.state()["lines"][0]["fragment_index"], 1)

    def test_orphans_sort_last(self):
        refs = self.refs_with_keys()
        self.line_row(1, start_s=3.0)
        self.line_row(0, start_s=2.0)
        self.line_row(0, start_s=0.5)
        self.put_items([refs[0]])
        lines = self.state()["lines"]
        self.assertEqual([(x["fragment_index"], x["start_s"], x["orphan"]) for x in lines],
                         [(0, 0.5, False), (0, 2.0, False), (None, 3.0, True)])


class LineRenderTests(_Lines):
    def run_task(self, project=None):
        project = project or self.p
        MergeProject.objects.filter(pk=project.pk).update(status="queued", credits_reserved=20,
                                                          queued_at=timezone.now())
        seen = []
        with patch("merge.services.ffmpeg.render", side_effect=_fake_render(seen)), \
                patch("merge.services.ffmpeg.make_poster", side_effect=_fake_poster):
            tasks.render_merge.run(project.pk)
        project.refresh_from_db()
        return project, seen

    def test_lines_go_to_the_mix_with_their_fragment_and_second(self):
        voice = self.track(start_fragment=1, duration_s=3.2)
        b = self.line_row(1, start_s=2.5, volume=1.5, duration_s=2.0)
        a = self.line_row(0, start_s=0.0, volume=1.0, duration_s=1.5)
        self.line_row(1, status="failed")
        self.line_row(0, status="pending", credits_reserved=5)
        MergeAudio.objects.filter(project=self.p, status="pending").update(status="failed", credits_reserved=0)
        MergeProject.objects.filter(pk=self.p.pk).update(voice_volume=1.2)
        project, seen = self.run_task()
        self.assertEqual(project.status, "ready")
        self.assertEqual(seen, [{"audio": render.AudioMix(
            clip_volume=1.0, voice=default_storage.path(voice.file), voice_volume=1.2, voice_duration=3.2,
            voice_fragment=1, music="", music_volume=0.35, expected_s=12.0,
            lines=(render.Line(path=default_storage.path(a.file), fragment=0, start=0.0, duration=1.5, volume=1.0),
                   render.Line(path=default_storage.path(b.file), fragment=1, start=2.5, duration=2.0,
                               volume=1.5)))}])
        self.assertEqual(self.ledger(), [("merge_video", -20)])

    def test_a_line_alone_makes_the_mix(self):
        a = self.line_row(1, start_s=1.0)
        _, seen = self.run_task()
        self.assertEqual(seen, [{"audio": render.AudioMix(
            voice_volume=1.0, music_volume=0.35, expected_s=12.0,
            lines=(render.Line(path=default_storage.path(a.file), fragment=1, start=1.0, duration=3.0, volume=1.0),))}])

    def test_orphans_are_not_mixed_and_reorder_moves_the_fragment(self):
        refs = self.refs_with_keys()
        kept = self.line_row(1, start_s=1.0)
        self.line_row(0, start_s=1.0)
        self.put_items([refs[1], {**self.ref(self.take(self.owner))}])
        self.p.refresh_from_db()
        _, seen = self.run_task()
        self.assertEqual([(x.path, x.fragment) for x in seen[0]["audio"].lines], [(default_storage.path(kept.file), 0)])


class LineCopyTests(_Lines):
    def test_copy_keeps_the_keys_sent_by_the_client(self):
        self.line_row(1, start_s=2.5, volume=0.6, duration_s=2.0)
        refs = self.refs_with_keys()
        MergeProject.objects.filter(pk=self.p.pk).update(status="ready")
        response = self.api.post(BASE, {"items": refs, "copy_audio_from": self.p.uid}, format="json")
        self.assertEqual(response.status_code, 201)
        copy = MergeProject.objects.get(uid=response.json()["id"])
        self.assertEqual([i["key"] for i in copy.items], [r["key"] for r in refs])
        row = MergeAudio.objects.get(project=copy, kind="line")
        self.assertEqual((row.fragment_key, row.start_s, row.volume, row.credits_charged, row.status),
                         (refs[1]["key"], 2.5, 0.6, 0, "ready"))
        self.assertEqual(row.fragment_ref, f"{refs[1]['type']}:{refs[1]['id']}")
        self.assertEqual(response.json()["audio"]["lines"], 1)

    def test_copy_without_keys_follows_the_clip_and_skips_missing_ones(self):
        t1, t2, t3 = self.take(self.owner), self.take(self.owner), self.take(self.owner)
        source = self.project(self.owner, [t1, t2, t3])
        self.line_row(1, project=source, start_s=1.0)
        self.line_row(2, project=source, start_s=2.0)
        MergeProject.objects.filter(pk=source.pk).update(status="ready")
        response = self.api.post(BASE, {"items": [self.ref(t3), self.ref(t1)], "copy_audio_from": source.uid},
                                 format="json")
        self.assertEqual(response.status_code, 201)
        copy = MergeProject.objects.get(uid=response.json()["id"])
        rows = list(MergeAudio.objects.filter(project=copy, kind="line"))
        self.assertEqual([(r.fragment_key, r.start_s) for r in rows], [(copy.items[0]["key"], 2.0)])


class LineCleanupTests(_Lines):
    def test_stale_line_is_closed_and_released(self):
        row = self.line_row(0, status="pending", credits_reserved=5)
        MergeAudio.objects.filter(pk=row.pk).update(created_at=timezone.now() - timedelta(minutes=11))
        self.assertEqual(services.reserved_credits(self.owner), 5)
        self.assertEqual(audio.fail_stale(), 1)
        row.refresh_from_db()
        self.assertEqual((row.status, row.error_code, row.credits_reserved), ("failed", "audio_stale", 0))
        self.assertEqual(services.reserved_credits(self.owner), 0)

    def test_max_start(self):
        for length, expected in ((5.0, 4.9), (5.04, 5.0), (4.04, 4.0), (0.1, 0.0), (0.05, 0.0), (0, 0.0),
                                 (None, 0.0), (7.0, 6.9), (6.999, 6.9), (float("inf"), 0.0)):
            with self.subTest(length=length):
                self.assertEqual(audio.max_start(length), expected)
