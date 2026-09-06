# -*- coding: utf-8 -*-
"""Правки, сделанные поверх группового разбора: общие тексты и оплата в дедупе."""
from types import SimpleNamespace

import pytest

import bot.routers.billing  # noqa: F401 — регистрирует тексты экрана оплаты
import bot.routers.profile  # noqa: F401
from bot.middlewares.auth import DedupMiddleware
from bot.texts import BASE_KEYS, TEXTS, register_texts, t


class TestSharedTexts:
    """Экран не может подменить общий текст: так «История чатов» однажды
    превратилась в «Последние операции» — экран оплаты объявил тот же ключ."""

    def test_screen_cannot_override_shared_key(self, caplog):
        before = t("ru", "history_title")
        register_texts({"ru": {"history_title": "чужое"}})
        assert t("ru", "history_title") == before

    def test_own_key_registers_normally(self):
        register_texts({"ru": {"zzz_probe_key": "своё"}, "en": {"zzz_probe_key": "mine"}})
        assert t("ru", "zzz_probe_key") == "своё"
        assert t("en", "zzz_probe_key") == "mine"
        for lang in ("ru", "en", "kg"):
            TEXTS[lang].pop("zzz_probe_key", None)

    def test_history_screens_do_not_collide(self):
        assert t("ru", "history_title") != t("ru", "tx_history_title")
        assert t("en", "history_title") != t("en", "tx_history_title")
        assert "чаты" in t("ru", "history_title").lower()
        assert "операци" in t("ru", "tx_history_title").lower()

    def test_base_keys_snapshot_is_from_texts_file(self):
        assert "history_title" in BASE_KEYS and "welcome" in BASE_KEYS
        # Ключи экранов в снимок не попадают — иначе защита заблокировала бы их же.
        assert "tx_history_title" not in BASE_KEYS


class FakeStore:
    def __init__(self, seen=False):
        self.seen = seen
        self.asked = []

    async def seen_update(self, update_id):
        self.asked.append(update_id)
        return self.seen


def _update(update_id=1, *, payment=False, refund=False, text="привет"):
    message = SimpleNamespace(
        successful_payment=SimpleNamespace(telegram_payment_charge_id="ch") if payment else None,
        refunded_payment=SimpleNamespace(telegram_payment_charge_id="ch") if refund else None,
        text=text,
    )
    update = SimpleNamespace(update_id=update_id, message=message)
    # DedupMiddleware проверяет isinstance(event, Update) — подменяем сам класс.
    return update


@pytest.mark.asyncio
class TestPaymentsBypassDedup:
    """Апдейт об оплате нельзя терять: Telegram повторяет его только пока мы
    не подтвердили получение, а сервер начисляет кредиты один раз по своему
    идентификатору оплаты."""

    async def _run(self, monkeypatch, update, seen):
        import bot.middlewares.auth as module

        store = FakeStore(seen=seen)
        monkeypatch.setattr(module, "store", store)
        monkeypatch.setattr(module, "Update", type(update))
        called = []

        async def handler(event, data):
            called.append(event)
            return "handled"

        result = await DedupMiddleware()(handler, update, {})
        return result, called, store

    async def test_ordinary_repeat_is_dropped(self, monkeypatch):
        result, called, store = await self._run(monkeypatch, _update(7), seen=True)
        assert result is None and not called
        assert store.asked == [7]

    async def test_ordinary_first_time_passes(self, monkeypatch):
        result, called, _ = await self._run(monkeypatch, _update(8), seen=False)
        assert result == "handled" and len(called) == 1

    async def test_successful_payment_is_never_dropped(self, monkeypatch):
        result, called, store = await self._run(monkeypatch, _update(9, payment=True), seen=True)
        assert result == "handled", "оплату отбросили — деньги человека потерялись бы"
        assert len(called) == 1
        assert store.asked == [], "для оплаты дедуп даже не спрашивается"

    async def test_refund_is_never_dropped(self, monkeypatch):
        result, called, _ = await self._run(monkeypatch, _update(10, refund=True), seen=True)
        assert result == "handled" and len(called) == 1
