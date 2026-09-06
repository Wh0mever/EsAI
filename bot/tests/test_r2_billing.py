# -*- coding: utf-8 -*-
"""Раунд 2, экран оплаты: молчащее ядро на pre_checkout, «<» из админки,
безлимитный тариф и лимит длины сообщения.

Каждый тест здесь про деньги или про экран, который человек видит вместо них:
Telegram отменяет платёж, если бот молчит 10 секунд; одно «<» в названии
пакета обрушивает весь /topup; длинный список пакетов не отправляется вовсе.
"""
import asyncio
import time
from types import SimpleNamespace

import pytest

import bot.routers.billing as billing
from bot.services.api import ApiError
from bot.texts import t

HUMAN = 424242


# ------------------------------------------------------------- заглушки ---

class FakeMessage:
    def __init__(self, chat_id=HUMAN, user_id=HUMAN):
        self.chat = SimpleNamespace(id=chat_id)
        self.from_user = SimpleNamespace(id=user_id)
        self.message_id = 1
        self.answers = []

    async def answer(self, text="", **kwargs):
        self.answers.append(SimpleNamespace(text=text, kwargs=kwargs))
        return self


class FakeCall:
    def __init__(self, data, message):
        self.data = data
        self.from_user = SimpleNamespace(id=HUMAN)
        self.message = message

    async def answer(self, text=None, **kwargs):
        return None


class FakeQuery:
    """pre_checkout_query: важно только то, чем пользуется обработчик."""

    def __init__(self, payload="pkg:1", amount=100, currency="XTR"):
        self.from_user = SimpleNamespace(id=HUMAN)
        self.invoice_payload = payload
        self.total_amount = amount
        self.currency = currency
        self.replies = []

    async def answer(self, ok=True, error_message=None, **kwargs):
        self.replies.append(SimpleNamespace(ok=ok, error_message=error_message))


class FakeStore:
    def __init__(self, values=None):
        self.values = dict(values or {})

    async def get(self, telegram_id, key, default=None):
        await asyncio.sleep(0)
        return self.values.get((telegram_id, key), default)

    async def set(self, telegram_id, key, value, ttl=None):
        self.values[(telegram_id, key)] = value

    async def drop(self, telegram_id, key):
        self.values.pop((telegram_id, key), None)


@pytest.fixture
def store(monkeypatch):
    fake = FakeStore()
    monkeypatch.setattr(billing, "store", fake)
    return fake


def buttons(markup):
    return [b for row in markup.inline_keyboard for b in row]


# ------------------------------------- [A] pre_checkout: 10 секунд Telegram ---

class TestPreCheckoutDeadline:
    """Молчание дороже отказа: Telegram отменит платёж и не скажет об этом."""

    @pytest.mark.asyncio
    async def test_slow_core_answers_before_telegram_gives_up(self, store, monkeypatch):
        monkeypatch.setattr(billing, "PRECHECK_TIMEOUT", 0.05)

        async def slow_precheck(*args, **kwargs):
            await asyncio.sleep(2.0)  # «медленное ядро»
            return {"ok": True}

        monkeypatch.setattr(billing.api, "stars_precheck", slow_precheck)
        query = FakeQuery()
        started = time.monotonic()
        await billing.pre_checkout(query)
        elapsed = time.monotonic() - started

        assert elapsed < 1.0, "ждали ядро дольше, чем Telegram ждёт нас"
        assert query.replies and query.replies[0].ok is False
        assert query.replies[0].error_message == t("ru", "precheck_slow")

    @pytest.mark.asyncio
    async def test_timeout_message_is_localized_and_fits_telegram(self, store, monkeypatch):
        monkeypatch.setattr(billing, "PRECHECK_TIMEOUT", 0.05)
        store.values[(HUMAN, "lang")] = "en"

        async def slow_precheck(*args, **kwargs):
            await asyncio.sleep(2.0)

        monkeypatch.setattr(billing.api, "stars_precheck", slow_precheck)
        query = FakeQuery()
        await billing.pre_checkout(query)

        message = query.replies[0].error_message
        assert message == t("en", "precheck_slow")
        assert 0 < len(message) <= 255, "Telegram обрежет error_message длиннее 255"

    @pytest.mark.asyncio
    async def test_dead_core_is_not_reported_as_stale_invoice(self, store, monkeypatch):
        """500 от ядра — «повторите», а не «откройте /topup заново»."""
        async def broken(*args, **kwargs):
            raise ApiError(502, code="bad_gateway")

        monkeypatch.setattr(billing.api, "stars_precheck", broken)
        query = FakeQuery()
        await billing.pre_checkout(query)

        assert query.replies[0].ok is False
        assert query.replies[0].error_message == t("ru", "precheck_slow")

    @pytest.mark.asyncio
    async def test_transport_error_is_not_reported_as_stale_invoice(self, store, monkeypatch):
        async def broken(*args, **kwargs):
            raise ApiError(504, code="stream_timeout")

        monkeypatch.setattr(billing.api, "stars_precheck", broken)
        query = FakeQuery()
        await billing.pre_checkout(query)

        assert query.replies[0].error_message == t("ru", "precheck_slow")

    @pytest.mark.asyncio
    async def test_real_rejection_still_says_invoice_is_stale(self, store, monkeypatch):
        async def rejected(*args, **kwargs):
            raise ApiError(400, code="payload_mismatch")

        monkeypatch.setattr(billing.api, "stars_precheck", rejected)
        query = FakeQuery()
        await billing.pre_checkout(query)

        assert query.replies[0].ok is False
        assert query.replies[0].error_message == t("ru", "precheck_fail")

    @pytest.mark.asyncio
    async def test_fast_core_confirms_payment(self, store, monkeypatch):
        seen = []

        async def ok(telegram_id, payload, amount, currency):
            seen.append((telegram_id, payload, amount, currency))
            return {"ok": True}

        monkeypatch.setattr(billing.api, "stars_precheck", ok)
        query = FakeQuery(payload="pkg:7", amount=250)
        await billing.pre_checkout(query)

        assert seen == [(HUMAN, "pkg:7", 250, "XTR")]
        assert query.replies[0].ok is True

    @pytest.mark.asyncio
    async def test_broken_store_does_not_break_a_good_payment(self, monkeypatch):
        """Язык лежит в Redis, но платёж от Redis зависеть не должен."""
        class BrokenStore:
            async def get(self, *args, **kwargs):
                raise ConnectionError("redis умер")

        monkeypatch.setattr(billing, "store", BrokenStore())

        async def ok(*args, **kwargs):
            return {"ok": True}

        monkeypatch.setattr(billing.api, "stars_precheck", ok)
        query = FakeQuery()
        await billing.pre_checkout(query)

        assert query.replies and query.replies[0].ok is True

    @pytest.mark.asyncio
    async def test_hanging_store_does_not_eat_the_telegram_deadline(self, monkeypatch):
        """Зависший Redis — это молчание бота, а молчание Telegram считает отказом."""
        class HangingStore:
            async def get(self, *args, **kwargs):
                await asyncio.sleep(2.0)
                return "en"

        monkeypatch.setattr(billing, "store", HangingStore())
        monkeypatch.setattr(billing, "LANG_TIMEOUT", 0.05)

        async def ok(*args, **kwargs):
            return {"ok": True}

        monkeypatch.setattr(billing.api, "stars_precheck", ok)
        query = FakeQuery()
        started = time.monotonic()
        await billing.pre_checkout(query)

        assert time.monotonic() - started < 1.0
        assert query.replies[0].ok is True

    @pytest.mark.asyncio
    async def test_disabled_stars_do_not_send_the_human_back_to_topup(self, store, monkeypatch):
        """Stars выключены нами: /topup приведёт к тому же отказу."""
        async def disabled(*args, **kwargs):
            raise ApiError(403, code="stars_disabled")

        monkeypatch.setattr(billing.api, "stars_precheck", disabled)
        query = FakeQuery()
        await billing.pre_checkout(query)

        assert query.replies[0].ok is False
        assert query.replies[0].error_message == t("ru", "stars_disabled")
        assert len(query.replies[0].error_message) <= 255

    @pytest.mark.asyncio
    async def test_rate_limit_asks_to_retry(self, store, monkeypatch):
        async def throttled(*args, **kwargs):
            raise ApiError(429, code="")

        monkeypatch.setattr(billing.api, "stars_precheck", throttled)
        query = FakeQuery()
        await billing.pre_checkout(query)

        assert query.replies[0].error_message == t("ru", "precheck_slow")


# ------------------------------------------ [B] чужой текст в HTML-экранах ---

ATTACK = '<b>СКИДКА</b> <script>alert(1)</script>'


def _packages(count=1, name=ATTACK, description="", badge=""):
    return [{"id": i + 1, "name": f"{name}", "tokens": 1000, "stars_price": 100,
             "description": description, "badge": badge}
            for i in range(count)]


class TestAdminTextIsEscaped:
    """Название/бейдж/описание приходят из админки — это чужой текст."""

    @pytest.mark.asyncio
    async def test_topup_screen_survives_angle_bracket_in_name(self, store, monkeypatch):
        async def packages(token, lang="ru", telegram_id=None):
            return _packages(1, description="Тариф <самый> выгодный", badge="ХИТ <2026>")

        async def values(token, lang="ru", telegram_id=None):
            return []

        monkeypatch.setattr(billing.api, "packages", packages)
        monkeypatch.setattr(billing.api, "packages_value", values)
        message = FakeMessage()
        await billing.show_topup(message, "tok", "ru")

        text = "\n".join(a.text for a in message.answers)
        assert "<script>" not in text, "Telegram отвергнет такое сообщение целиком"
        assert "&lt;script&gt;" in text
        assert "&lt;самый&gt;" in text
        assert "&lt;2026&gt;" in text
        # Наша собственная разметка при этом на месте.
        assert "<b>" in text

    @pytest.mark.asyncio
    async def test_buy_button_keeps_raw_name(self, store, monkeypatch):
        """В подписи кнопки разметки нет: экранирование там показало бы «&lt;»."""
        async def packages(token, lang="ru", telegram_id=None):
            return _packages(1, name="Пакет <PRO>")

        async def values(token, lang="ru", telegram_id=None):
            return []

        monkeypatch.setattr(billing.api, "packages", packages)
        monkeypatch.setattr(billing.api, "packages_value", values)
        message = FakeMessage()
        await billing.show_topup(message, "tok", "ru")

        labels = [b.text for b in buttons(message.answers[-1].kwargs["reply_markup"])]
        assert any("Пакет <PRO>" in label for label in labels)

    @pytest.mark.asyncio
    async def test_paid_message_escapes_package_name(self, store):
        sent = []

        class FakeBot:
            async def send_message(self, chat_id, text, **kwargs):
                sent.append(text)

            async def delete_message(self, *args, **kwargs):
                return None

        await billing._after_paid(FakeBot(), HUMAN, "ru",
                                  {"credited": 1000, "package_name": "Пакет <PRO>",
                                   "balance_tokens": 5000})

        assert sent and "<PRO>" not in sent[0]
        assert "&lt;PRO&gt;" in sent[0]

    @pytest.mark.asyncio
    async def test_history_escapes_model_and_reason(self, store, monkeypatch):
        async def transactions(token, lang="ru", telegram_id=None):
            return [{"delta": -12, "created_at": "2026-09-06T10:00:00Z",
                     "reason": "chat <hack>", "balance_after": "1<2",
                     "meta": {"model": "openai/gpt-<x>"}}]

        monkeypatch.setattr(billing.api, "transactions", transactions)
        message = FakeMessage()
        await billing.history(FakeCall("b:hist", message), "tok", "ru")

        text = "\n".join(a.text for a in message.answers)
        assert "<hack>" not in text and "<x>" not in text
        assert "&lt;hack&gt;" in text and "gpt-&lt;x&gt;" in text


# ---------------------------------------------- [C] безлимитный тариф ---

class TestUnlimitedTier:
    @staticmethod
    def _balance(monkeypatch, payload):
        async def balance(token, lang="ru", telegram_id=None):
            return payload

        monkeypatch.setattr(billing.api, "balance", balance)

    @pytest.mark.asyncio
    async def test_tier_unlimited_is_shown(self, store, monkeypatch):
        self._balance(monkeypatch, {"balance_tokens": 10, "tier": "unlimited"})
        message = FakeMessage()
        await billing.show_balance(message, "tok", "ru")
        assert t("ru", "tier_unlimited") in message.answers[0].text

    @pytest.mark.asyncio
    async def test_is_unlimited_flag_wins_over_paid_tier(self, store, monkeypatch):
        self._balance(monkeypatch, {"balance_tokens": 10, "tier": "paid", "is_unlimited": True})
        message = FakeMessage()
        await billing.show_balance(message, "tok", "ru")
        assert t("ru", "tier_unlimited") in message.answers[0].text

    @pytest.mark.asyncio
    async def test_old_core_without_new_fields_still_renders(self, store, monkeypatch):
        """Пока бэкенд не отдаёт новых полей, экран показывает обычный тариф."""
        self._balance(monkeypatch, {"balance_tokens": 10, "tier": "free", "is_paid": False})
        message = FakeMessage()
        await billing.show_balance(message, "tok", "ru")
        assert t("ru", "tier_free") in message.answers[0].text

    @pytest.mark.asyncio
    async def test_empty_answer_does_not_break_the_screen(self, store, monkeypatch):
        """Пустой ответ ядра — не повод показать человеку ошибку."""
        self._balance(monkeypatch, None)
        message = FakeMessage()
        await billing.show_balance(message, "tok", "ru")
        assert message.answers and t("ru", "tier_free") in message.answers[0].text
        assert message.answers[0].kwargs.get("reply_markup") is not None


# ------------------------------------------------- [D] лимит 4096 символов ---

TG_LIMIT = 4096


class TestMessageLength:
    @pytest.mark.asyncio
    async def test_long_package_list_is_split_and_keeps_buttons(self, store, monkeypatch):
        many = [{"id": i, "name": f"Пакет номер {i}", "tokens": 1000 * i,
                 "stars_price": 100 * i, "description": "Очень подробное описание пакета. " * 5,
                 "badge": "выгодно"} for i in range(1, 31)]

        async def packages(token, lang="ru", telegram_id=None):
            return many

        async def values(token, lang="ru", telegram_id=None):
            return [{"id": p["id"], "value": {"text": {"count": 1200}, "image": {"count": 40},
                                              "video": {"count": 3}}} for p in many]

        monkeypatch.setattr(billing.api, "packages", packages)
        monkeypatch.setattr(billing.api, "packages_value", values)
        message = FakeMessage()
        await billing.show_topup(message, "tok", "ru")

        assert len(message.answers) > 1, "такой текст Telegram не принял бы одним сообщением"
        for answer in message.answers:
            assert len(answer.text) <= TG_LIMIT, "сообщение длиннее лимита не дойдёт совсем"
        # Кнопки не потеряны и висят на последнем сообщении.
        assert message.answers[-1].kwargs.get("reply_markup") is not None
        assert all(a.kwargs.get("reply_markup") is None for a in message.answers[:-1])
        data = [b.callback_data for b in buttons(message.answers[-1].kwargs["reply_markup"])]
        assert data == [f"b:buy:{p['id']}" for p in many]

    @pytest.mark.asyncio
    async def test_short_list_stays_one_message(self, store, monkeypatch):
        async def packages(token, lang="ru", telegram_id=None):
            return _packages(2, name="Пакет")

        async def values(token, lang="ru", telegram_id=None):
            return []

        monkeypatch.setattr(billing.api, "packages", packages)
        monkeypatch.setattr(billing.api, "packages_value", values)
        message = FakeMessage()
        await billing.show_topup(message, "tok", "ru")

        assert len(message.answers) == 1
        assert message.answers[0].kwargs.get("reply_markup") is not None

    @pytest.mark.asyncio
    async def test_history_with_long_model_names_fits(self, store, monkeypatch):
        async def transactions(token, lang="ru", telegram_id=None):
            return [{"delta": -5, "created_at": "2026-09-06T10:00:00Z", "reason": "chat",
                     "balance_after": 1000,
                     "meta": {"model": "provider/" + "очень-длинное-имя-модели-" * 12}}
                    for _ in range(20)]

        monkeypatch.setattr(billing.api, "transactions", transactions)
        message = FakeMessage()
        await billing.history(FakeCall("b:hist", message), "tok", "ru")

        assert message.answers
        for answer in message.answers:
            assert len(answer.text) <= TG_LIMIT
