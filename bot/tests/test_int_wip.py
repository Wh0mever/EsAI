# -*- coding: utf-8 -*-
"""Бот в паре с правками ядра: повторный аккаунт после /delete и автовозврат
второй оплаты.

Ядро теперь не дарит приветственный бонус тому, кто только что ушёл по /delete,
и отвечает foreign_charge на возврат лишнего платежа. Бот не должен говорить
«начислено 0 кредитов» и «кредиты сняты», когда ничего не начисляли и не снимали.
"""
from types import SimpleNamespace

import pytest

import bot.routers.billing as billing
import bot.routers.start as start_mod
from bot.services.api import ApiError
from bot.texts import TEXTS, t

HUMAN = 424242


class FakeMessage:
    def __init__(self, refund=None):
        self.chat = SimpleNamespace(id=HUMAN)
        self.from_user = SimpleNamespace(id=HUMAN, first_name="Тест")
        self.refunded_payment = refund
        self.sent = []

    async def answer(self, text="", **kwargs):
        self.sent.append(text)
        return self


class FakeStore:
    async def drop(self, telegram_id, key):
        return None


class TestGreeting:
    @pytest.mark.parametrize("lang", ["ru", "en", "kg"])
    async def test_zero_balance_does_not_claim_a_gift(self, lang):
        message = FakeMessage()
        await start_mod._greet_new(message, lang, {"balance_tokens": 0})
        assert message.sent[0] == t(lang, "welcome_empty")
        assert "🎁" not in message.sent[0]

    async def test_missing_balance_is_treated_as_zero(self):
        message = FakeMessage()
        await start_mod._greet_new(message, "ru", {})
        assert message.sent[0] == t("ru", "welcome_empty")

    async def test_gift_is_named_when_there_is_one(self):
        message = FakeMessage()
        await start_mod._greet_new(message, "ru", {"balance_tokens": 50})
        assert message.sent[0] == t("ru", "welcome", balance=50)
        assert "50 кредитов" in message.sent[0]

    @pytest.mark.parametrize("lang", ["ru", "en", "kg"])
    def test_texts_exist_in_every_language(self, lang):
        for key in ("welcome_empty", "refunded_extra"):
            assert key in TEXTS[lang], f"нет текста {key} для {lang}"
        assert "{balance}" not in TEXTS[lang]["welcome_empty"]


def _refund():
    return SimpleNamespace(telegram_payment_charge_id="charge-2", invoice_payload="pkg:1",
                           total_amount=100)


class TestRefundMessage:
    @pytest.fixture(autouse=True)
    def _store(self, monkeypatch):
        monkeypatch.setattr(billing, "store", FakeStore())

    async def _run(self, monkeypatch, outcome, lang="ru"):
        async def stars_refunded(*args, **kwargs):
            if isinstance(outcome, Exception):
                raise outcome
            return outcome

        monkeypatch.setattr(billing.api, "stars_refunded", stars_refunded)
        message = FakeMessage(refund=_refund())
        await billing.on_refunded(message, lang=lang)
        return message.sent

    @pytest.mark.parametrize("lang", ["ru", "en", "kg"])
    async def test_our_own_auto_refund_keeps_the_purchase(self, monkeypatch, lang):
        sent = await self._run(monkeypatch, {"status": "foreign_charge", "order_id": "o-1"}, lang)
        assert sent == [t(lang, "refunded_extra", stars=100)]
        assert t(lang, "refunded_extra", stars=100) != t(lang, "refunded", stars=100)

    async def test_real_refund_still_says_credits_were_removed(self, monkeypatch):
        sent = await self._run(monkeypatch, {"status": "refunded", "debited": 500})
        assert sent == [t("ru", "refunded", stars=100)]

    async def test_core_error_keeps_the_old_message(self, monkeypatch):
        sent = await self._run(monkeypatch, ApiError(503, code="transport"))
        assert sent == [t("ru", "refunded", stars=100)]

    async def test_odd_answer_does_not_break_the_handler(self, monkeypatch):
        sent = await self._run(monkeypatch, None)
        assert sent == [t("ru", "refunded", stars=100)]
