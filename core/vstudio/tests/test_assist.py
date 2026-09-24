"""«Сжать с ИИ» (спецификация §4.8): vstudio.assist и POST /api/vstudio/assist/condense/.

OpenRouter не трогаем: requests.post подменён сценарием ответов, ключ — заглушка.

Главное, что проверяем:
- теги фото не теряются и не множатся: каждый ⟦n⟧ ровно один раз, иначе одна
  повторная попытка с объяснением, потом 422 condense_failed;
- материал модели передаётся только плейсхолдером — uid и адреса файлов не уходят;
- «было/стало» считаются тем же компилятором, что счётчик под полем;
- бесплатно: ни резерва, ни списания, ни записи в журнале; throttle 20 в час;
- вьюха вне транзакции запроса (долгий внешний вызов).
"""
import copy
import dataclasses
import json
from unittest import mock

import requests
from django.conf import settings
from django.core.cache import cache
from django.db import connection
from django.test import SimpleTestCase, TransactionTestCase, override_settings
from django.urls import resolve, reverse
from rest_framework.test import APIClient
from rest_framework.throttling import SimpleRateThrottle

from ai.models import GenerationLog
from plans.models import TokenTransaction
from vstudio import assist, compiler, views_assist
from vstudio import prompt_doc as pd
from vstudio.models import Take
from vstudio.tests import factories as f
from vstudio.tests.caps_fixtures import SEEDANCE_20, make_caps
from vstudio.tests.test_api import ApiCase

A = "a" * 32
B = "b" * 32
SEEDANCE = "bytedance/seedance-2.0"
NANO = "google/gemini-2.5-flash-image"
CFG = {"base_url": "https://openrouter.test/api/v1", "api_key": "test-key",
       "referer": "https://esai.kg", "title": "EsAI"}
LONG = "медленно идёт по старому двору, камера плавно наезжает, тёплый закатный свет, "  # 11 слов


# ---------------------------------------------------------------- помощники

class FakeResponse:
    def __init__(self, status: int = 200, payload=None, text: str | None = None):
        self.status_code = status
        self._payload = payload
        self.text = text if text is not None else json.dumps(payload, ensure_ascii=False)

    def json(self):
        if self._payload is None:
            raise ValueError("not json")
        return self._payload


def answer(text: str | None = None, *, content: str | None = None, finish: str = "stop") -> FakeResponse:
    """Ответ chat/completions: {"text": text} в content (или свой content как есть)."""
    if content is None:
        content = json.dumps({"text": text}, ensure_ascii=False)
    return FakeResponse(200, {"id": "gen-1", "choices": [
        {"message": {"role": "assistant", "content": content}, "finish_reason": finish}]})


class Provider:
    """Подмена requests.post: отдаёт ответы по очереди и запоминает запросы."""

    def __init__(self, *replies):
        self.replies = list(replies)
        self.calls = []

    def __call__(self, url, json=None, headers=None, timeout=None, **kw):
        self.calls.append({"url": url, "json": copy.deepcopy(json), "headers": dict(headers or {}),
                           "timeout": timeout})
        if not self.replies:
            raise AssertionError("лишний вызов модели")
        reply = self.replies.pop(0)
        if isinstance(reply, BaseException):
            raise reply
        return reply

    def messages(self, i: int = 0) -> list:
        return self.calls[i]["json"]["messages"]

    def sent_text(self, i: int = 0) -> str:
        return "\n".join(str(m["content"]) for m in self.messages(i))


def ref(uid: str, slot: str = "reference", role: str = "", included: bool = True, pos: int = 0,
        **asset) -> compiler.ResolvedInput:
    view = compiler.AssetView(uid, file=f"vstudio/1/{uid}.jpg", **asset)
    return compiler.ResolvedInput(view, slot, pos, role, included)


def doc(*blocks) -> dict:
    """doc(["Девушка ", A, " идёт"], ["Камера"]) — строка → текст, 32 hex → ссылка."""
    out = []
    for block in blocks:
        nodes = []
        for part in block:
            if len(part) == 32 and set(part) <= set("0123456789abcdef"):
                nodes.append({"t": "ref", "asset": part})
            elif nodes and nodes[-1]["t"] == "text":
                nodes[-1]["v"] += part
            else:
                nodes.append({"t": "text", "v": part})
        out.append(nodes)
    return {"v": 1, "blocks": out}


def long_doc(times: int = 15) -> dict:
    """~200 слов с двумя фото: выше мягкого лимита Seedance (150 слов)."""
    return doc(["Девушка ", A, " " + LONG * times + "рядом ", B, " смотрит в окно."])


class ProviderMixin:
    """Ключ OpenRouter и requests.post подменены на время теста."""

    def use_provider(self, *replies) -> Provider:
        provider = Provider(*replies)
        self.enterContext(mock.patch("ai.handlers._openrouter_config", return_value=dict(CFG)))
        self.enterContext(mock.patch("vstudio.assist.requests.post", side_effect=provider))
        return provider


# ---------------------------------------------------------------- плейсхолдеры

class PlaceholderTests(SimpleTestCase):
    def test_refs_become_placeholders_numbered_by_asset(self):
        held = assist.to_placeholders(doc(["Девушка ", A, " и ", B, ", снова ", A], ["Камера ", B]))
        self.assertEqual(held.text, "Девушка ⟦1⟧ и ⟦2⟧, снова ⟦1⟧\nКамера ⟦2⟧")
        self.assertEqual(held.uids, [A, B])
        self.assertEqual(held.counts, {1: 2, 2: 2})

    def test_users_own_brackets_cannot_pose_as_placeholders(self):
        held = assist.to_placeholders(doc(["текст ⟦3⟧ и 〚4〛 ", A]))
        self.assertEqual(held.text, "текст [3] и [4] ⟦1⟧")
        self.assertEqual(assist.check_placeholders(held.text, 1), [])

    def test_exactly_once_is_ok(self):
        self.assertEqual(assist.check_placeholders("⟦2⟧ идёт к ⟦1⟧", 2), [])

    def test_lost_placeholder(self):
        problems = assist.check_placeholders("⟦1⟧ идёт по крыше", 2)
        self.assertEqual(problems, ["missing: ⟦2⟧"])

    def test_duplicated_placeholder(self):
        problems = assist.check_placeholders("⟦1⟧ идёт к ⟦2⟧, ⟦1⟧ смеётся", 2)
        self.assertEqual(problems, ["used more than once: ⟦1⟧ ×2"])

    def test_invented_placeholder(self):
        problems = assist.check_placeholders("⟦1⟧ идёт к ⟦3⟧", 1)
        self.assertEqual(problems, ["not in the source (do not invent placeholders): ⟦3⟧"])

    def test_broken_placeholder(self):
        problems = assist.check_placeholders("⟦1 идёт", 1)
        self.assertIn("missing: ⟦1⟧", problems)
        self.assertTrue(any("broken placeholder" in p for p in problems))

    def test_lookalike_brackets_spaces_and_at_are_accepted(self):
        self.assertEqual(assist.check_placeholders("〚1〛 и @⟦ 2 ⟧", 2), [])
        rebuilt = assist.from_placeholders("Девушка @⟦1⟧ идёт к 〚 2 〛", [A, B])
        self.assertEqual(rebuilt["blocks"], [[
            {"t": "text", "v": "Девушка "}, {"t": "ref", "asset": A},
            {"t": "text", "v": " идёт к "}, {"t": "ref", "asset": B}]])

    def test_rebuild_lines_become_blocks_and_whitespace_is_tidied(self):
        rebuilt = assist.from_placeholders("  ⟦1⟧   идёт\r\n\n\nКамера\tнаезжает ⟦2⟧  ", [A, B])
        self.assertEqual(rebuilt, {"v": 1, "blocks": [
            [{"t": "ref", "asset": A}, {"t": "text", "v": " идёт"}],
            [{"t": "text", "v": "Камера наезжает "}, {"t": "ref", "asset": B}]]})

    def test_round_trip_keeps_the_document(self):
        source = doc(["Девушка ", A, " идёт"], [B, " смотрит, ", A, " машет"])
        held = assist.to_placeholders(source)
        self.assertEqual(assist.from_placeholders(held.text, held.uids), source)


# ---------------------------------------------------------------- бюджет и счётчик

class BudgetTests(SimpleTestCase):
    def test_seedance_budget_leaves_room_for_tags_and_role_lines(self):
        caps = make_caps(SEEDANCE)
        inputs = [ref(A, role="героиня"), ref(B, pos=1)]
        held = assist.to_placeholders(long_doc())
        target = assist.budget(caps, held, inputs)
        # «[Image 1] is героиня.» (+4 слова) и «[Image N]» — два слова вместо одного (+1 и +1).
        self.assertEqual(target.words, 150 - 6)
        self.assertLess(target.chars, 6000)

    def test_image_model_without_soft_limit_gets_default(self):
        caps = make_caps(NANO)
        target = assist.budget(caps, assist.to_placeholders(doc(["текст"])), [])
        self.assertEqual(target.words, assist.DEFAULT_TARGET_WORDS)

    def test_small_hard_limit_caps_the_word_target(self):
        caps = dataclasses.replace(make_caps("minimax/hailuo-2.3"), prompt_hard_chars=1000)
        target = assist.budget(caps, assist.to_placeholders(doc(["текст"])), [])
        self.assertEqual(target.chars, 900)
        self.assertEqual(target.words, 900 // assist.CHARS_PER_WORD)

    def test_stats_match_the_compiler_meter(self):
        caps = make_caps(SEEDANCE)
        inputs = [ref(A, role="героиня"), ref(B, pos=1)]
        source = long_doc()
        meter = compiler.compile(caps, "video", source, inputs, {}, site_base="https://esai.kg").meter
        self.assertEqual(assist.text_stats(caps, source, inputs),
                         {"chars": meter["chars"], "words": meter["words"]})

    def test_detect_lang(self):
        self.assertEqual(assist.detect_lang("Девушка идёт по крыше"), "ru")
        self.assertEqual(assist.detect_lang("Кыз үйдө отурат"), "ky")
        self.assertEqual(assist.detect_lang("A girl walks on the roof"), "en")
        self.assertIsNone(assist.detect_lang("Kız çatıda yürüyor ve gülümsüyor çok güzel"))
        self.assertIsNone(assist.detect_lang("123 !!!"))


# ---------------------------------------------------------------- сжатие

@override_settings(VSTUDIO_ASSIST_MODEL="google/gemini-2.5-flash")
class CondenseTests(ProviderMixin, SimpleTestCase):
    GOOD = "⟦1⟧ медленно идёт по старому двору к ⟦2⟧, камера плавно наезжает, тёплый закатный свет."

    def setUp(self):
        self.caps = make_caps(SEEDANCE)
        self.inputs = [ref(A, role="героиня"), ref(B, pos=1)]
        self.source = long_doc()

    def run_condense(self, *replies, caps=None, source=None, inputs=None, **kw):
        provider = self.use_provider(*replies)
        try:
            result = assist.condense(caps or self.caps, source or self.source,
                                     self.inputs if inputs is None else inputs, **kw)
        finally:
            self.provider = provider
        return result

    def expect_failure(self, *replies, reason: str, calls: int, **kw) -> assist.CondenseError:
        with self.assertRaises(assist.CondenseError) as ctx:
            self.run_condense(*replies, **kw)
        self.assertEqual(ctx.exception.reason, reason)
        self.assertEqual(len(self.provider.calls), calls)
        return ctx.exception

    def test_success_rebuilds_doc_with_the_same_photos(self):
        result = self.run_condense(answer(self.GOOD))
        self.assertEqual(result.doc, doc([
            A, " медленно идёт по старому двору к ", B, ", камера плавно наезжает, тёплый закатный свет."]))
        self.assertEqual(result.attempts, 1)
        self.assertEqual(result.before, assist.text_stats(self.caps, self.source, self.inputs))
        self.assertEqual(result.after, assist.text_stats(self.caps, result.doc, self.inputs))
        self.assertLess(result.after["words"], result.before["words"])
        self.assertEqual(set(result.to_json()), {"prompt_doc", "before", "after"})

    def test_request_to_the_model(self):
        self.run_condense(answer(self.GOOD))
        call = self.provider.calls[0]
        self.assertEqual(call["url"], "https://openrouter.test/api/v1/chat/completions")
        self.assertEqual(call["timeout"], (10, 30))
        self.assertEqual(call["headers"]["Authorization"], "Bearer test-key")
        body = call["json"]
        self.assertEqual(body["model"], "google/gemini-2.5-flash")
        self.assertEqual(body["response_format"], {"type": "json_object"})
        system, user = body["messages"]
        self.assertEqual(system["role"], "system")
        self.assertIn("EXACTLY ONCE", system["content"])
        self.assertIn("At most 144 words", system["content"])
        self.assertIn("Write in Russian", system["content"])
        self.assertIn("subject → action → place → camera → light and style → sound", system["content"])
        self.assertIn("Девушка ⟦1⟧ медленно идёт", user["content"])
        self.assertIn('⟦1⟧ — a reference photo, who/what: "героиня"', user["content"])
        self.assertIn("⟦2⟧ — a reference photo", user["content"])
        # Модели уходит только плейсхолдер: ни uid, ни адреса файлов.
        self.assertNotIn(A, self.provider.sent_text())
        self.assertNotIn("vstudio/1/", self.provider.sent_text())

    @override_settings(VSTUDIO_ASSIST_MODEL="openai/gpt-4o-mini")
    def test_model_comes_from_settings(self):
        self.run_condense(answer(self.GOOD))
        self.assertEqual(self.provider.calls[0]["json"]["model"], "openai/gpt-4o-mini")

    def test_lost_placeholder_retries_once_with_an_explanation(self):
        lost = "⟦1⟧ медленно идёт по старому двору, камера плавно наезжает."
        result = self.run_condense(answer(lost), answer(self.GOOD))
        self.assertEqual(result.attempts, 2)
        self.assertEqual(pd.ref_uids(result.doc), [A, B])
        retry = self.provider.messages(1)
        self.assertEqual(retry[:2], self.provider.messages(0))
        self.assertEqual(retry[2]["role"], "assistant")
        self.assertEqual(json.loads(retry[2]["content"])["text"], lost)
        self.assertEqual(retry[3]["role"], "user")
        self.assertIn("missing: ⟦2⟧", retry[3]["content"])

    def test_lost_placeholder_twice_fails(self):
        lost = "⟦1⟧ медленно идёт по старому двору, камера плавно наезжает."
        err = self.expect_failure(answer(lost), answer(lost), reason="placeholders", calls=2)
        self.assertEqual(err.message, assist.MESSAGE_FAILED)
        self.assertEqual(err.attempts, 2)

    def test_duplicated_placeholder_twice_fails(self):
        dup = "⟦1⟧ идёт к ⟦2⟧, ⟦1⟧ смеётся, камера наезжает."
        self.expect_failure(answer(dup), answer(dup), reason="placeholders", calls=2)
        self.assertIn("used more than once: ⟦1⟧ ×2", self.provider.messages(1)[3]["content"])

    def test_duplicated_then_fixed(self):
        dup = "⟦1⟧ идёт к ⟦2⟧, ⟦1⟧ смеётся, камера наезжает."
        result = self.run_condense(answer(dup), answer(self.GOOD))
        self.assertEqual(result.attempts, 2)
        self.assertEqual([n["asset"] for b in result.doc["blocks"] for n in b if n["t"] == "ref"], [A, B])

    def test_invented_placeholder_fails(self):
        extra = "⟦1⟧ идёт к ⟦2⟧ и ⟦3⟧, камера наезжает."
        self.expect_failure(answer(extra), answer(extra), reason="placeholders", calls=2)

    def test_photo_mentioned_twice_in_source_needs_one_mention(self):
        source = doc(["Девушка ", A, " " + LONG * 15 + "потом ", A, " машет рукой ", B])
        result = self.run_condense(answer(self.GOOD), source=source)
        self.assertEqual(pd.ref_uids(result.doc), [A, B])
        self.assertIn("mentioned 2 times in the source — mention it once", self.provider.sent_text())

    def test_not_json_then_ok(self):
        result = self.run_condense(answer(content="Вот сжатый текст: ⟦1⟧ идёт"), answer(self.GOOD))
        self.assertEqual(result.attempts, 2)
        self.assertIn("not JSON", self.provider.messages(1)[3]["content"])

    def test_json_in_code_fence_is_accepted(self):
        fenced = "```json\n" + json.dumps({"text": self.GOOD}, ensure_ascii=False) + "\n```"
        result = self.run_condense(answer(content=fenced))
        self.assertEqual(pd.ref_uids(result.doc), [A, B])

    def test_cut_off_answer_is_retried(self):
        result = self.run_condense(answer(self.GOOD, finish="length"), answer(self.GOOD))
        self.assertEqual(result.attempts, 2)

    def test_not_shorter_is_rejected(self):
        same = assist.to_placeholders(self.source).text
        self.expect_failure(answer(same), answer(same), reason="not_shorter", calls=2)

    def test_still_over_the_hard_limit_is_rejected(self):
        caps = dataclasses.replace(self.caps, prompt_hard_chars=300)
        long_answer = "⟦1⟧ " + "очень " * 60 + "⟦2⟧"
        self.expect_failure(answer(long_answer), answer(long_answer), reason="too_long", calls=2, caps=caps)

    def test_network_error_is_not_retried(self):
        err = self.expect_failure(requests.ConnectionError("down"), reason="provider", calls=1)
        self.assertIn("Помощник сейчас не отвечает", err.message)

    def test_timeout_is_not_retried(self):
        self.expect_failure(requests.ReadTimeout("slow"), reason="provider", calls=1)

    def test_http_error_is_not_retried(self):
        self.expect_failure(FakeResponse(502, text="bad gateway"), reason="provider", calls=1)

    def test_error_inside_200_is_a_provider_error(self):
        self.expect_failure(FakeResponse(200, {"error": {"message": "no credits"}}), reason="provider", calls=1)

    def test_missing_api_key_sends_nothing(self):
        provider = Provider()
        self.enterContext(mock.patch("ai.handlers._openrouter_config", return_value=dict(CFG, api_key="")))
        self.enterContext(mock.patch("vstudio.assist.requests.post", side_effect=provider))
        with self.assertRaises(assist.CondenseError) as ctx:
            assist.condense(self.caps, self.source, self.inputs)
        self.assertEqual(ctx.exception.reason, "provider")
        self.assertEqual(provider.calls, [])

    def test_no_retry_when_the_deadline_is_near(self):
        lost = "⟦1⟧ идёт по двору."
        clock = iter([0.0, assist.DEADLINE_S - 1])
        self.enterContext(mock.patch("vstudio.assist._clock", side_effect=lambda: next(clock)))
        self.expect_failure(answer(lost), reason="placeholders", calls=1)

    def test_retry_read_timeout_fits_the_deadline(self):
        lost = "⟦1⟧ идёт по двору."
        clock = iter([0.0, assist.DEADLINE_S - 20])
        self.enterContext(mock.patch("vstudio.assist._clock", side_effect=lambda: next(clock)))
        self.run_condense(answer(lost), answer(self.GOOD))
        self.assertEqual(self.provider.calls[1]["timeout"], (10, 20))

    def test_short_text_is_not_sent(self):
        provider = self.use_provider()
        with self.assertRaises(assist.CondenseError) as ctx:
            assist.condense(self.caps, doc([A, " идёт по крыше"]), self.inputs)
        self.assertEqual(ctx.exception.reason, "already_short")
        self.assertEqual(provider.calls, [])

    def test_only_tags_is_empty(self):
        provider = self.use_provider()
        with self.assertRaises(assist.CondenseError) as ctx:
            assist.condense(self.caps, doc([A, " ", B]), self.inputs)
        self.assertEqual(ctx.exception.reason, "empty")
        self.assertEqual(provider.calls, [])

    def test_invalid_doc_raises_prompt_doc_error(self):
        with self.assertRaises(pd.PromptDocError):
            assist.condense(self.caps, {"v": 2, "blocks": []}, [])

    def test_frames_are_described_as_frames(self):
        inputs = [ref(A, role="героиня"), ref(B, slot="first_frame")]
        self.run_condense(answer(self.GOOD), inputs=inputs)
        self.assertIn("⟦2⟧ — the first frame of the video", self.provider.sent_text())

    def test_unattached_photo_keeps_its_tag(self):
        # Фото из текста нет среди своих материалов (чужое или удалённое): тег всё
        # равно возвращается на место, а компилятор потом скажет mention_not_attached.
        result = self.run_condense(answer(self.GOOD), inputs=[ref(A)])
        self.assertEqual(pd.ref_uids(result.doc), [A, B])
        self.assertIn("⟦2⟧ — a photo", self.provider.sent_text())

    def test_image_model(self):
        caps = make_caps(NANO)
        source = doc(["Портрет ", A, " " + LONG * 110])  # > 8000 символов — выше жёсткого лимита
        result = self.run_condense(answer("Портрет ⟦1⟧ в тёплом закатном свете."), caps=caps, source=source,
                                   inputs=[ref(A)])
        self.assertEqual(pd.ref_uids(result.doc), [A])
        system = self.provider.messages(0)[0]["content"]
        self.assertIn("AI image generator", system)
        self.assertNotIn("sound", system)
        self.assertIn("At most 120 words", system)

    def test_no_placeholders(self):
        source = doc(["Девушка " + LONG * 15])
        result = self.run_condense(answer("Девушка идёт по двору, камера наезжает."), source=source, inputs=[])
        self.assertEqual(pd.ref_uids(result.doc), [])
        self.assertIn("never add any ⟦…⟧", self.provider.messages(0)[0]["content"])

    def test_explicit_language(self):
        self.run_condense(answer(self.GOOD), lang="en")
        self.assertIn("Write in English", self.provider.messages(0)[0]["content"])


# ---------------------------------------------------------------- API

class CondenseApiTests(ProviderMixin, ApiCase):
    URL = "/api/vstudio/assist/condense/"
    GOOD = CondenseTests.GOOD

    def setUp(self):
        super().setUp()
        self.a = f.make_asset(self.user)
        self.b = f.make_asset(self.user)

    def payload(self, **extra) -> dict:
        body = {"model": SEEDANCE,
                "prompt_doc": doc(["Девушка ", self.a.uid, " " + LONG * 15 + "рядом ", self.b.uid, " стоит."]),
                "inputs": [{"asset": self.a.uid, "slot": "reference", "position": 0, "role": "героиня",
                            "included": True},
                           {"asset": self.b.uid, "slot": "reference", "position": 1, "role": "",
                            "included": True}]}
        body.update(extra)
        return body

    def post(self, body, client=None):
        return (client or self.api).post(self.URL, body, format="json")

    def test_url(self):
        self.assertEqual(reverse("vstudio:assist-condense"), self.URL)

    def test_ok_shape_and_free(self):
        provider = self.use_provider(answer(self.GOOD))
        balance = self.user.token_balance
        res = self.post(self.payload())
        self.assertEqual(res.status_code, 200, res.content)
        data = res.json()
        self.assertEqual(set(data), {"prompt_doc", "before", "after"})
        self.assertEqual(data["prompt_doc"]["blocks"][0][0], {"t": "ref", "asset": self.a.uid})
        self.assertEqual(pd.ref_uids(data["prompt_doc"]), [self.a.uid, self.b.uid])
        self.assertEqual(set(data["before"]), {"chars", "words"})
        self.assertLess(data["after"]["words"], data["before"]["words"])
        self.assertEqual(len(provider.calls), 1)
        # Бесплатно: ни списания, ни резерва, ни записи в журнале генераций.
        self.user.refresh_from_db()
        self.assertEqual(self.user.token_balance, balance)
        self.assertFalse(TokenTransaction.objects.filter(user=self.user).exists())
        self.assertFalse(Take.objects.exists())
        self.assertFalse(GenerationLog.objects.exists())

    def test_before_matches_the_quote_meter(self):
        self.use_provider(answer(self.GOOD))
        body = self.payload()
        quote = self.quote(dict(body, kind="video", params={"duration": 5, "resolution": "720p",
                                                            "aspect_ratio": "16:9"}, project=None))
        self.assertEqual(quote.status_code, 200, quote.content)
        meter = quote.json()["meter"]
        before = self.post(body).json()["before"]
        self.assertEqual(before, {"chars": meter["chars"], "words": meter["words"]})

    def test_placeholders_lost_twice_is_422(self):
        lost = "⟦1⟧ медленно идёт по старому двору, камера плавно наезжает."
        provider = self.use_provider(answer(lost), answer(lost))
        data = self.assert_error(self.post(self.payload()), 422, "condense_failed")
        self.assertEqual(data["reason"], "placeholders")
        self.assertEqual(data["error"], assist.MESSAGE_FAILED)
        self.assertEqual(len(provider.calls), 2)

    def test_provider_down_is_422(self):
        self.use_provider(requests.ConnectionError("down"))
        data = self.assert_error(self.post(self.payload()), 422, "condense_failed")
        self.assertEqual(data["reason"], "provider")

    def test_prompt_text_is_accepted(self):
        provider = self.use_provider(answer(self.GOOD))
        body = self.payload(prompt_doc=None,
                            prompt_text="Девушка @Image 1 " + LONG * 15 + "рядом [Image 2] стоит.")
        res = self.post(body)
        self.assertEqual(res.status_code, 200, res.content)
        self.assertEqual(pd.ref_uids(res.json()["prompt_doc"]), [self.a.uid, self.b.uid])
        self.assertIn("Девушка ⟦1⟧", provider.sent_text())

    def test_foreign_asset_is_not_resolved_but_its_tag_survives(self):
        stranger = f.make_asset(f.make_user())
        provider = self.use_provider(answer(self.GOOD))
        body = self.payload(
            prompt_doc=doc(["Девушка ", self.a.uid, " " + LONG * 15 + "рядом ", stranger.uid]),
            inputs=[{"asset": self.a.uid, "slot": "reference", "position": 0, "role": "героиня",
                     "included": True},
                    {"asset": stranger.uid, "slot": "reference", "position": 1, "role": "",
                     "included": True}])
        res = self.post(body)
        self.assertEqual(res.status_code, 200, res.content)
        self.assertEqual(pd.ref_uids(res.json()["prompt_doc"]), [self.a.uid, stranger.uid])
        self.assertIn("⟦2⟧ — a photo", provider.sent_text())
        self.assertNotIn(stranger.uid, provider.sent_text())

    def test_bad_doc_is_422_prompt_doc_invalid(self):
        provider = self.use_provider()
        self.assert_error(self.post(self.payload(prompt_doc={"v": 1, "blocks": [[{"t": "html"}]]})),
                          422, "prompt_doc_invalid")
        self.assertEqual(provider.calls, [])

    def test_doc_and_text_together_is_400(self):
        self.use_provider()
        self.assert_error(self.post(self.payload(prompt_text="x")), 400, "bad_request")

    def test_bad_model_is_400(self):
        self.use_provider()
        self.assert_error(self.post(self.payload(model="")), 400, "bad_request")
        self.assert_error(self.post(self.payload(model="x" * 200)), 400, "bad_request")

    def test_unknown_model_is_422_model_unavailable(self):
        provider = self.use_provider()
        self.assert_error(self.post(self.payload(model="acme/unknown-video")), 422, "model_unavailable")
        self.assertEqual(provider.calls, [])

    def test_bad_inputs_is_400(self):
        self.use_provider()
        self.assert_error(self.post(self.payload(inputs=[{"asset": "nope"}])), 400, "bad_request")

    def test_short_text_is_422_without_a_call(self):
        provider = self.use_provider()
        data = self.assert_error(self.post(self.payload(prompt_doc=doc(["Девушка ", self.a.uid, " идёт"]))),
                                 422, "condense_failed")
        self.assertEqual(data["reason"], "already_short")
        self.assertEqual(provider.calls, [])

    def test_guest_gets_401(self):
        self.use_provider()
        self.assert_error(self.post(self.payload(), client=APIClient()), 401, "unauthorized")

    @override_settings(VSTUDIO_MODE="staff")
    def test_staff_mode_blocks_non_staff(self):
        provider = self.use_provider()
        self.assert_error(self.post(self.payload()), 403, "vstudio_disabled")
        self.assertEqual(provider.calls, [])

    def test_throttle_scope_and_rate(self):
        self.assertEqual(settings.REST_FRAMEWORK["DEFAULT_THROTTLE_RATES"]["vstudio_assist"], "20/hour")
        view = views_assist.CondenseView()
        view.request = mock.Mock(method="POST")
        self.assertEqual(view.throttle_scope, "vstudio_assist")

    def test_throttled_after_the_hourly_limit(self):
        self.use_provider(answer(self.GOOD), answer(self.GOOD))
        with mock.patch.dict(SimpleRateThrottle.THROTTLE_RATES, {"vstudio_assist": "2/hour"}):
            for _ in range(2):
                self.assertEqual(self.post(self.payload()).status_code, 200)
            data = self.assert_error(self.post(self.payload()), 429, "throttled")
        self.assertGreater(data["wait"], 0)

    def test_view_runs_outside_the_request_transaction(self):
        match = resolve(self.URL)
        self.assertIn("default", getattr(match.func, "_non_atomic_requests", set()))
        self.assertIs(match.func.view_class, views_assist.CondenseView)


class CondenseOutsideTransactionTests(ProviderMixin, TransactionTestCase):
    """ATOMIC_REQUESTS включён: без @non_atomic_requests вызов модели шёл бы внутри
    открытой транзакции запроса (TestCase сам держит транзакцию — поэтому здесь
    TransactionTestCase)."""

    def setUp(self):
        cache.clear()
        self.enterContext(mock.patch("ai.handlers._openrouter_video_catalog",
                                     side_effect=lambda mid: dict(SEEDANCE_20) if mid == SEEDANCE else {}))
        self.enterContext(override_settings(VSTUDIO_MODE="on"))
        self.user = f.make_user()
        f.make_gpt_model(SEEDANCE, name="Seedance 2.0")
        self.asset = f.make_asset(self.user)

    def test_model_is_called_outside_a_transaction(self):
        seen = []

        def reply(*args, **kwargs):
            seen.append(connection.in_atomic_block)
            return answer("⟦1⟧ медленно идёт по старому двору, камера плавно наезжает.")

        self.enterContext(mock.patch("ai.handlers._openrouter_config", return_value=dict(CFG)))
        self.enterContext(mock.patch("vstudio.assist.requests.post", side_effect=reply))
        client = APIClient()
        client.force_authenticate(self.user)
        res = client.post(CondenseApiTests.URL, {
            "model": SEEDANCE,
            "prompt_doc": doc(["Девушка ", self.asset.uid, " " + LONG * 15]),
            "inputs": [{"asset": self.asset.uid, "slot": "reference", "position": 0, "role": "",
                        "included": True}]}, format="json")
        self.assertEqual(res.status_code, 200, res.content)
        self.assertEqual(seen, [False])
