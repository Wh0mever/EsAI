# -*- coding: utf-8 -*-
"""Чат: признаки итогового кадра, кадр без разрывов строк, FLUX без токенного гейта.

Правки ai/handlers.py от 30.09: бот выбирает свои тексты по флагам done (image,
image_missing, free_truncated), а не по русским подписям; U+2028 в ответе модели
не рвёт кадр у построчного читателя бота; у FLUX цена картинки плоская, поэтому
токенный гейт по истории чата его больше не отклоняет, а «без контекста»
действует и на него. Сети нет.
"""
from __future__ import annotations

import json
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import SimpleTestCase, TestCase, override_settings
from rest_framework.test import APIClient

from ai import handlers
from ai.models import AiChatMessage, AiChatSession, AiProvider, GPTModels
from ai.tests_audit_chat import FakeClient, FakeStream
from ai.tests_pricing_chat import CFG, PICTURE, _Client, _ImageStream, _frames

CHAT_URL = "/api/ai/chat/"
NANO = "google/gemini-2.5-flash-image"
FLEX = "black-forest-labs/flux.2-flex"
TEXT = "test/chat"
TEST_CACHES = {"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache",
                           "LOCATION": "chat-done-flags"}}
FLAGS = ("image", "image_missing", "free_truncated")


def _model(orid, coeff, category, **extra):
    return GPTModels.objects.create(
        name=orid, openrouter_id=orid, category=category, markup_coefficient=Decimal(coeff),
        max_tokens=4096, is_active=True, **extra)


def _completion(text, images=None, total_tokens=100):
    """Ответ OpenRouter без потока (chat completions)."""
    message = SimpleNamespace(content=text, images=images)
    usage = SimpleNamespace(prompt_tokens=total_tokens - 10, completion_tokens=10, total_tokens=total_tokens)
    return SimpleNamespace(choices=[SimpleNamespace(message=message)], usage=usage)


def _flags(frame) -> dict:
    return {key: frame[key] for key in FLAGS if key in frame}


class SseFrameTests(SimpleTestCase):
    def test_unicode_line_breaks_do_not_split_the_frame(self):
        # Бот читает поток httpx aiter_lines, а тот режет строки как str.splitlines.
        text = "до\u2028после\u2029конец\x85хвост\nновая строка"
        frame = handlers._sse({"delta": text})
        lines = frame.splitlines()
        self.assertEqual(len(lines), 2, lines)
        self.assertEqual(lines[1], "")
        self.assertEqual(json.loads(lines[0][len("data: "):]), {"delta": text})

    def test_plain_frame_is_unchanged(self):
        self.assertEqual(handlers._sse({"delta": "Привет", "done": True}),
                         'data: {"delta": "Привет", "done": true}\n\n')


@override_settings(CACHES=TEST_CACHES, TOKEN_CREDIT_DIVISOR=1000, FREE_MAX_OUTPUT_CHARS=40)
class ChatFlagsBase(TestCase):
    def setUp(self):
        cache.clear()
        AiProvider.objects.create(name="GPT", token="x")
        self.user = self.make_user("flags@example.com", paid=True)
        self.api = APIClient()
        self.api.force_authenticate(self.user)
        for target, kwargs in (("users.tasks.extract_user_memory.delay", {}),
                               ("ai.tasks.summarize_session_context.delay", {}),
                               ("ai.handlers._openrouter_config", {"return_value": CFG})):
            p = patch(target, **kwargs)
            p.start()
            self.addCleanup(p.stop)

    @staticmethod
    def make_user(email, *, paid, balance=10_000):
        user = get_user_model().objects.create_user(email=email, password="x-12345678")
        user.token_balance = balance
        user.is_paid = paid
        user.save(update_fields=["token_balance", "is_paid"])
        return user

    def set_balance(self, value):
        self.user.token_balance = value
        self.user.save(update_fields=["token_balance"])

    def balance(self):
        self.user.refresh_from_db(fields=["token_balance"])
        return self.user.token_balance

    def post(self, client, *, api=None, **body):
        with patch("ai.handlers._make_openai_client", return_value=client):
            response = (api or self.api).post(CHAT_URL, body, format="json")
            if body.get("stream"):
                return _frames(response)[-1]
            return response.json()


class ImageFlagsTests(ChatFlagsBase):
    def setUp(self):
        super().setUp()
        _model(NANO, "4", "image")
        _model(FLEX, "12", "image")

    def test_picture_sets_image_flag(self):
        for stream in (True, False):
            client = (_Client(_ImageStream(1450)) if stream else FakeClient(_completion(
                "", images=[{"type": "image_url", "image_url": {"url": "data:image/png;base64,AAAA"}}])))
            with patch("ai.handlers._save_generated_images", return_value=list(PICTURE)):
                done = self.post(client, message="нарисуй кота", model=NANO, stream=stream)
            self.assertIsNone(done.get("error"), done)
            self.assertEqual(_flags(done), {"image": True})
            self.assertGreater(done["tokens_charged"], 0)
            msg = AiChatMessage.objects.filter(role="assistant").order_by("-id").first()
            self.assertTrue(msg.meta["image"])

    def test_text_instead_of_picture_sets_image_missing_and_is_free(self):
        for stream in (True, False):
            before = self.balance()
            client = FakeClient(FakeStream(["<image>"]) if stream else _completion("<image>"))
            done = self.post(client, message="нарисуй кота", model=NANO, stream=stream)
            self.assertIsNone(done.get("error"), done)
            self.assertEqual(_flags(done), {"image_missing": True})
            self.assertEqual((done["tokens_charged"], self.balance()), (0, before))

    def test_flux_picture_sets_image_flag(self):
        for stream in (True, False):
            with patch("ai.handlers._flux_generate_image", return_value=(list(PICTURE), 0.06)):
                done = self.post(None, message="нарисуй кота", model=FLEX, stream=stream)
            self.assertIsNone(done.get("error"), done)
            self.assertEqual((_flags(done), done["tokens_charged"]), ({"image": True}, 12))


class FreeTruncatedTests(ChatFlagsBase):
    """Бесплатный тариф: ответ режется по FREE_MAX_OUTPUT_CHARS (40), признак — free_truncated."""

    def setUp(self):
        super().setUp()
        _model(TEXT, "1", "chat", free_tier=True)
        self.free = self.make_user("free@example.com", paid=False)
        self.free_api = APIClient()
        self.free_api.force_authenticate(self.free)

    def test_long_answer_is_flagged(self):
        long_pieces = ["а" * 30, "б" * 30]
        done = self.post(FakeClient(FakeStream(long_pieces)), api=self.free_api,
                         message="расскажи", model=TEXT, stream=True)
        self.assertEqual(_flags(done), {"free_truncated": True})
        done = self.post(FakeClient(_completion("".join(long_pieces))), api=self.free_api,
                         message="расскажи", model=TEXT, stream=False)
        self.assertEqual(_flags(done), {"free_truncated": True})

    def test_short_answer_has_no_flags(self):
        for stream in (True, False):
            client = FakeClient(FakeStream(["коротко"]) if stream else _completion("коротко"))
            done = self.post(client, api=self.free_api, message="расскажи", model=TEXT, stream=stream)
            self.assertIsNone(done.get("error"), done)
            self.assertEqual(_flags(done), {})

    def test_paid_answer_is_never_flagged(self):
        done = self.post(FakeClient(FakeStream(["я" * 100])), message="расскажи", model=TEXT, stream=True)
        self.assertEqual(_flags(done), {})
        self.assertEqual(len(done["message"]["content"]), 100)

    def test_guest_long_answer_is_flagged(self):
        done = self.post(FakeClient(FakeStream(["г" * 30, "д" * 30])), api=APIClient(),
                         message="расскажи", model=TEXT, stream=True)
        self.assertTrue(done.get("guest"), done)
        self.assertEqual(_flags(done), {"free_truncated": True})


class FluxBalanceGateTests(ChatFlagsBase):
    """FLUX Flex по-старому стоит 12 кр за картинку — столько и должно хватать при любой истории."""

    def setUp(self):
        super().setUp()
        self.flex = _model(FLEX, "12", "image")
        self.session = AiChatSession.objects.create(user=self.user, title="t")
        for i in range(6):
            AiChatMessage.objects.create(session=self.session, role="user" if i % 2 == 0 else "assistant",
                                         content=f"{i} " + "длинная история " * 200)

    def draw(self, stream, **extra):
        with patch("ai.handlers._flux_generate_image", return_value=(list(PICTURE), 0.06)) as generate:
            done = self.post(None, message="нарисуй кота", model=FLEX, stream=stream,
                             chat_id=self.session.uid, **extra)
        return done, generate

    def test_exact_price_is_enough_despite_long_history(self):
        # Токенный гейт по этой истории отказал бы: ему нужно больше 12.
        messages = [{"role": "user", "content": "длинная история " * 1200}]
        self.set_balance(12)
        self.assertIsNotNone(handlers._precise_balance_gate(
            self.user, self.flex, messages, limited=False, web_search=False, model_max_tokens=4096))
        for stream in (True, False):
            self.set_balance(12)
            done, generate = self.draw(stream)
            self.assertIsNone(done.get("error"), done)
            self.assertEqual((done["tokens_charged"], self.balance()), (12, 0))
            generate.assert_called_once()

    def test_short_balance_is_still_refused_before_the_provider(self):
        for stream in (True, False):
            self.set_balance(11)
            done, generate = self.draw(stream)
            self.assertEqual((done["error_code"], done["required_estimate"]), ("insufficient_balance", 12))
            self.assertEqual(self.balance(), 11)
            generate.assert_not_called()

    def test_stateless_flux_skips_memory(self):
        self.set_balance(100)
        for stateless, calls in ((True, 0), (False, 1)):
            with patch("ai.handlers.parse_explicit_commands") as commands, \
                    patch("ai.handlers.get_memory_block", return_value="") as memory:
                done, _ = self.draw(True, stateless=stateless)
            self.assertIsNone(done.get("error"), done)
            self.assertEqual((commands.call_count, memory.call_count), (calls, calls))
