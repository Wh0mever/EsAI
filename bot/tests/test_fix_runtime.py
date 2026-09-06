# -*- coding: utf-8 -*-
"""Рантайм бота: дедупликация апдейтов, вход по реф-ссылке, оплата и остановка."""
import asyncio
import datetime

import pytest
from aiogram.types import (
    Chat,
    Message,
    RefundedPayment,
    SuccessfulPayment,
    Update,
    User,
)

import bot.middlewares.auth as auth_mod
import bot.routers.start as start_mod
from bot.__main__ import run_polling
from bot.middlewares.auth import AuthMiddleware, CommandResetMiddleware, DedupMiddleware
from bot.services.api import ApiError

TG_ID = 777
NOW = datetime.datetime(2026, 1, 1, tzinfo=datetime.timezone.utc)


def make_user(user_id: int = TG_ID, first_name: str = "Вася") -> User:
    return User(id=user_id, is_bot=False, first_name=first_name)


def make_message(text: str | None = None, user: User | None = None, **extra) -> Message:
    user = user or make_user()
    return Message(message_id=1, date=NOW, chat=Chat(id=user.id, type="private"),
                   from_user=user, text=text, **extra)


def paid_message(user: User | None = None) -> Message:
    return make_message(user=user, successful_payment=SuccessfulPayment(
        currency="XTR", total_amount=100, invoice_payload="pkg:1",
        telegram_payment_charge_id="charge-1", provider_payment_charge_id=""))


def refund_message(user: User | None = None) -> Message:
    return make_message(user=user, refunded_payment=RefundedPayment(
        currency="XTR", total_amount=100, invoice_payload="pkg:1",
        telegram_payment_charge_id="charge-1"))


class FakeStore:
    """Redis тут не нужен — важно лишь, что бот помнит между вызовами."""

    def __init__(self, token: str | None = None, **prefs):
        self.token = token
        self.prefs = dict(prefs)
        self.seen: set[int] = set()

    async def seen_update(self, update_id: int) -> bool:
        if update_id in self.seen:
            return True
        self.seen.add(update_id)
        return False

    async def get_token(self, telegram_id: int):
        return self.token

    async def set_token(self, telegram_id: int, token: str) -> None:
        self.token = token

    async def drop_token(self, telegram_id: int) -> None:
        self.token = None

    async def get(self, telegram_id: int, key: str, default=None):
        return self.prefs.get(key, default)

    async def set(self, telegram_id: int, key: str, value, ttl: int = 0) -> None:
        self.prefs[key] = value

    async def drop(self, telegram_id: int, key: str) -> None:
        self.prefs.pop(key, None)


class FakeState:
    """Мини-FSMContext: помнит состояние и факт очистки."""

    def __init__(self, state=None):
        self.state = state
        self.cleared = False

    async def get_state(self):
        return self.state

    async def clear(self) -> None:
        self.state = None
        self.cleared = True


class Recorder:
    """Обработчик, до которого middleware должен (или не должен) дойти."""

    def __init__(self):
        self.calls: list[dict] = []

    async def __call__(self, event, data):
        self.calls.append(data)
        return "handled"


@pytest.fixture
def open_access(monkeypatch):
    """Тесты про рантайм не про режим доступа — открываем его всем."""
    monkeypatch.setattr(auth_mod.settings, "access", "all")


class TestDedup:
    """[A] Апдейт обрабатывается ровно один раз — иначе второе списание."""

    async def test_second_time_same_update_is_dropped(self, monkeypatch):
        store = FakeStore()
        monkeypatch.setattr(auth_mod, "store", store)
        handler = Recorder()
        update = Update(update_id=42, message=make_message("привет"))

        # data пустая: "event_update" на уровне dispatcher.update ещё не кладут.
        assert await DedupMiddleware()(handler, update, {}) == "handled"
        assert await DedupMiddleware()(handler, update, {}) is None
        assert len(handler.calls) == 1
        assert store.seen == {42}

    async def test_different_updates_pass(self, monkeypatch):
        store = FakeStore()
        monkeypatch.setattr(auth_mod, "store", store)
        handler = Recorder()

        for update_id in (1, 2, 3):
            await DedupMiddleware()(handler, Update(update_id=update_id,
                                                    message=make_message("x")), {})
        assert len(handler.calls) == 3

    async def test_non_update_event_passes(self, monkeypatch):
        """На других обозревателях event — не Update, мешать им нельзя."""
        store = FakeStore()
        monkeypatch.setattr(auth_mod, "store", store)
        handler = Recorder()

        assert await DedupMiddleware()(handler, make_message("привет"), {}) == "handled"
        assert store.seen == set()


class FakeApi:
    def __init__(self, payload=None, error: Exception | None = None):
        self.payload = payload or {"access": "JWT", "created": True, "user": {"lang": "ru"}}
        self.error = error
        self.calls: list[dict] = []

    async def auth_telegram(self, tg_user, *, chat_id, ref="", promo=""):
        self.calls.append({"tg_user": tg_user, "chat_id": chat_id, "ref": ref, "promo": promo})
        if self.error:
            raise self.error
        return self.payload


class TestReferralOnFirstAuth:
    """[B] Реф-код должен уйти в тот самый вызов, который создаёт аккаунт."""

    async def test_ref_goes_into_first_exchange(self, monkeypatch, open_access):
        api = FakeApi()
        monkeypatch.setattr(auth_mod, "api", api)
        monkeypatch.setattr(auth_mod, "store", FakeStore())
        handler = Recorder()
        message = make_message("/start ref_ABCD1234")

        await AuthMiddleware()(handler, message, {"event_from_user": message.from_user})

        assert len(api.calls) == 1
        assert api.calls[0]["ref"] == "ABCD1234"
        assert handler.calls[0]["auth_payload"]["created"] is True

    async def test_promo_goes_into_first_exchange(self, monkeypatch, open_access):
        api = FakeApi()
        monkeypatch.setattr(auth_mod, "api", api)
        monkeypatch.setattr(auth_mod, "store", FakeStore())
        message = make_message("/start@EsAI_Bot promo_WELCOME")

        await AuthMiddleware()(Recorder(), message, {"event_from_user": message.from_user})

        assert api.calls[0]["promo"] == "WELCOME"
        assert api.calls[0]["ref"] == ""
        assert api.calls[0]["chat_id"] == TG_ID

    async def test_ref_reexchanges_even_with_cached_token(self, monkeypatch, open_access):
        """Токен из прошлой сессии не должен съедать приглашение."""
        api = FakeApi()
        monkeypatch.setattr(auth_mod, "api", api)
        monkeypatch.setattr(auth_mod, "store", FakeStore(token="OLD"))
        message = make_message("/start ref_ABCD1234")

        await AuthMiddleware()(Recorder(), message, {"event_from_user": message.from_user})

        assert api.calls[0]["ref"] == "ABCD1234"

    async def test_second_start_does_not_reexchange(self, monkeypatch, open_access):
        """Человек уже видел /start — повторный обмен ему ничего не даёт."""
        api = FakeApi()
        monkeypatch.setattr(auth_mod, "api", api)
        monkeypatch.setattr(auth_mod, "store", FakeStore(token="OLD", seen_start=True))
        message = make_message("/start ref_ABCD1234")

        await AuthMiddleware()(Recorder(), message, {"event_from_user": message.from_user})

        assert api.calls == []

    @pytest.mark.parametrize("text", [
        "/start link_abc123XYZ", "/start studio", "/start topup", "/start", "привет",
        "/startle ref_ABCD1234",
    ])
    async def test_other_payloads_are_not_referrals(self, monkeypatch, open_access, text):
        api = FakeApi()
        monkeypatch.setattr(auth_mod, "api", api)
        monkeypatch.setattr(auth_mod, "store", FakeStore())
        message = make_message(text)

        await AuthMiddleware()(Recorder(), message, {"event_from_user": message.from_user})

        assert api.calls[0]["ref"] == "" and api.calls[0]["promo"] == ""


class FakeAnswers:
    """Message, у которого нас интересуют только исходящие тексты."""

    def __init__(self, first_name: str = "Вася"):
        self.from_user = make_user(first_name=first_name)
        self.chat = Chat(id=TG_ID, type="private")
        self.sent: list[str] = []

    async def answer(self, text, **_):
        self.sent.append(text)


class TestStartHandler:
    """[B]/[F] Хендлер /start: без повторного обмена и с экранированием имени."""

    async def test_no_second_exchange(self, monkeypatch):
        api = FakeApi()
        monkeypatch.setattr(start_mod, "api", api)
        monkeypatch.setattr(start_mod, "store", FakeStore())

        class Cmd:
            args = "ref_ABCD1234"

        message = FakeAnswers()
        await start_mod.cmd_start(message, command=Cmd(), token="JWT", lang="ru",
                                  auth_payload={"created": True, "user": {"balance_tokens": 10}})

        assert api.calls == []

    async def test_new_user_sees_language_choice(self, monkeypatch):
        monkeypatch.setattr(start_mod, "api", FakeApi())
        monkeypatch.setattr(start_mod, "store", FakeStore())

        class Cmd:
            args = "ref_ABCD1234"

        message = FakeAnswers()
        await start_mod.cmd_start(message, command=Cmd(), token="JWT", lang="ru",
                                  auth_payload={"created": True, "user": {"balance_tokens": 10}})

        from bot.texts import t

        assert message.sent[0] == t("ru", "choose_lang")

    async def test_name_is_escaped_in_welcome_back(self, monkeypatch):
        monkeypatch.setattr(start_mod, "api", FakeApi())
        monkeypatch.setattr(start_mod, "store", FakeStore())

        class Cmd:
            args = ""

        message = FakeAnswers(first_name="<b>Вася</b>")
        await start_mod.cmd_start(message, command=Cmd(), token="JWT", lang="ru",
                                  auth_payload={"created": False, "user": {"balance_tokens": 10}})

        greeting = message.sent[0]
        assert "&lt;b&gt;Вася&lt;/b&gt;" in greeting
        assert "<b>Вася</b>" not in greeting


class TestPaymentSurvivesDeadCore:
    """[C] Заплатил — обязан получить кредиты, даже если core лежит."""

    @pytest.mark.parametrize("factory", [paid_message, refund_message])
    async def test_payment_passes_without_token(self, monkeypatch, open_access, factory):
        api = FakeApi(error=ApiError(503, code="transport"))
        monkeypatch.setattr(auth_mod, "api", api)
        monkeypatch.setattr(auth_mod, "store", FakeStore())
        handler = Recorder()
        message = factory()

        result = await AuthMiddleware()(handler, message,
                                        {"event_from_user": message.from_user})

        assert result == "handled"
        assert handler.calls[0]["token"] == ""
        assert handler.calls[0]["lang"] == "ru"

    async def test_ordinary_message_still_stops(self, monkeypatch, open_access):
        """Обычному сообщению без токена по-прежнему отвечаем «сервер недоступен»."""
        monkeypatch.setattr(auth_mod, "api", FakeApi(error=ApiError(503, code="transport")))
        monkeypatch.setattr(auth_mod, "store", FakeStore())
        handler = Recorder()
        message = make_message("привет")
        sent: list[str] = []
        monkeypatch.setattr(AuthMiddleware, "_reply",
                            staticmethod(lambda event, text: _collect(sent, text)))

        assert await AuthMiddleware()(handler, message,
                                      {"event_from_user": message.from_user}) is None
        assert handler.calls == []
        assert sent


async def _collect(bucket: list, text: str) -> None:
    bucket.append(text)


class TestCommandResetsWizard:
    """[E] Команда закрывает незаконченный мастер."""

    @pytest.mark.parametrize("text", ["/new", "/balance", "/profile@EsAI_Bot", "/help меня"])
    async def test_plain_command_clears_state(self, text):
        state = FakeState("ImageWizard:edit")
        handler = Recorder()

        await CommandResetMiddleware()(handler, make_message(text), {"state": state})

        assert state.cleared is True
        assert len(handler.calls) == 1

    @pytest.mark.parametrize("text", ["/image", "/video котик", "/studio", "/cancel", "/start"])
    async def test_wizard_commands_keep_state(self, text):
        """Мастера сами решают, что делать со своим состоянием."""
        state = FakeState("ImageWizard:prompt")

        await CommandResetMiddleware()(Recorder(), make_message(text), {"state": state})

        assert state.cleared is False

    async def test_wizard_input_is_not_touched(self):
        """Обычный текст — это и есть ответ мастеру, его трогать нельзя."""
        state = FakeState("ImageWizard:prompt")

        await CommandResetMiddleware()(Recorder(), make_message("кот в скафандре"),
                                       {"state": state})

        assert state.cleared is False

    async def test_no_state_no_clear(self):
        state = FakeState(None)

        await CommandResetMiddleware()(Recorder(), make_message("/new"), {"state": state})

        assert state.cleared is False


class FakeDispatcher:
    """Опрос, который крутится, пока его не попросят остановиться."""

    def __init__(self):
        self.stopped = asyncio.Event()
        self.stop_polling_called = False

    async def start_polling(self, bot, **kwargs):
        await self.stopped.wait()

    async def stop_polling(self) -> None:
        self.stop_polling_called = True
        self.stopped.set()


class FakeBot:
    def __init__(self):
        self.webhook_deleted = False

    async def delete_webhook(self, drop_pending_updates: bool = False) -> None:
        self.webhook_deleted = True


class TestPollingStopsOnSignal:
    """[D] SIGTERM ставит Event — опрос обязан на него отреагировать."""

    async def test_stop_event_stops_polling(self):
        dispatcher = FakeDispatcher()
        stop = asyncio.Event()
        task = asyncio.create_task(run_polling(FakeBot(), dispatcher, stop))
        await asyncio.sleep(0)
        assert not task.done()

        stop.set()
        await asyncio.wait_for(task, timeout=5)

        assert dispatcher.stop_polling_called is True

    async def test_normal_exit_does_not_leak_stopper(self):
        """Если опрос кончился сам, сторож не должен висеть вечно."""
        dispatcher = FakeDispatcher()
        dispatcher.stopped.set()
        await asyncio.wait_for(run_polling(FakeBot(), dispatcher, asyncio.Event()), timeout=5)

        assert dispatcher.stop_polling_called is False
