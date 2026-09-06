# -*- coding: utf-8 -*-
"""Второй раунд, группа runtime: ошибка в кнопке, протухший токен, промокод, ключи.

Каждый тест падает на поведении до правки: молчаливая «крутилка» у callback,
401 без повторного обмена, промокод из ссылки без единого слова человеку, ключ
Redis по chat.id и «/START» мимо обработчика.
"""
import datetime

import pytest
from aiogram.types import CallbackQuery, Chat, Message, RefundedPayment, SuccessfulPayment, User

import bot.middlewares.auth as auth_mod
import bot.routers.start as start_mod
from bot.middlewares.auth import AuthMiddleware, ErrorsMiddleware
from bot.services.api import ApiError
from bot.texts import t

TG_ID = 4242
NOW = datetime.datetime(2026, 1, 1, tzinfo=datetime.timezone.utc)


def make_user(user_id: int = TG_ID) -> User:
    return User(id=user_id, is_bot=False, first_name="Вася")


def make_message(text: str | None = None, user: User | None = None, **extra) -> Message:
    user = user or make_user()
    return Message(message_id=1, date=NOW, chat=Chat(id=user.id, type="private"),
                   from_user=user, text=text, **extra)


def make_callback(message: Message | None = None, data: str = "nav:x") -> CallbackQuery:
    return CallbackQuery(id="cb-1", from_user=make_user(), chat_instance="ci",
                         data=data, message=message)


def paid_message() -> Message:
    return make_message(successful_payment=SuccessfulPayment(
        currency="XTR", total_amount=100, invoice_payload="pkg:1",
        telegram_payment_charge_id="charge-1", provider_payment_charge_id=""))


class FakeStore:
    """Redis не нужен: важно, что бот помнит токен и по какому ключу пишет."""

    def __init__(self, token: str | None = None, **prefs):
        self.token = token
        self.prefs = dict(prefs)
        self.dropped_token = False
        self.keys: list[tuple[str, int]] = []

    async def get_token(self, telegram_id: int):
        return self.token

    async def set_token(self, telegram_id: int, token: str) -> None:
        self.token = token

    async def drop_token(self, telegram_id: int) -> None:
        self.token = None
        self.dropped_token = True

    async def get(self, telegram_id: int, key: str, default=None):
        self.keys.append((key, telegram_id))
        return self.prefs.get(key, default)

    async def set(self, telegram_id: int, key: str, value, ttl: int = 0) -> None:
        self.keys.append((key, telegram_id))
        self.prefs[key] = value

    async def drop(self, telegram_id: int, key: str) -> None:
        self.keys.append((key, telegram_id))
        self.prefs.pop(key, None)


class FakeApi:
    """Обмен телеграм-данных на токен; каждый вызов записываем."""

    def __init__(self, tokens=("NEW",), error: Exception | None = None):
        self.tokens = list(tokens)
        self.error = error
        self.calls: list[dict] = []

    async def auth_telegram(self, tg_user, *, chat_id, ref="", promo=""):
        self.calls.append({"chat_id": chat_id, "ref": ref, "promo": promo})
        if self.error:
            raise self.error
        access = self.tokens.pop(0) if self.tokens else "NEW"
        return {"access": access, "created": False, "user": {"lang": "ru"}}


class Handler:
    """Обработчик со сценарием: что вернуть или чем упасть на каждом вызове."""

    def __init__(self, *outcomes):
        self.outcomes = list(outcomes)
        self.calls: list[dict] = []

    async def __call__(self, event, data):
        self.calls.append(dict(data))
        outcome = self.outcomes.pop(0) if self.outcomes else "handled"
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


@pytest.fixture
def open_access(monkeypatch):
    monkeypatch.setattr(auth_mod.settings, "access", "all")


@pytest.fixture
def replies(monkeypatch):
    """Тексты, которые AuthMiddleware сказал человеку."""
    sent: list[str] = []

    async def _reply(event, text):
        sent.append(text)

    monkeypatch.setattr(AuthMiddleware, "_reply", staticmethod(_reply))
    return sent


# --------------------------------------------------------------------- [A] ---

@pytest.fixture
def outgoing(monkeypatch):
    """Всплывашки кнопки и сообщения в чат — раздельно."""
    toasts: list[str] = []
    messages: list[str] = []

    async def cb_answer(self, text=None, **kw):
        toasts.append(text)
        return True

    async def msg_answer(self, text, **kw):
        messages.append(text)
        return self

    monkeypatch.setattr(CallbackQuery, "answer", cb_answer)
    monkeypatch.setattr(Message, "answer", msg_answer)
    return toasts, messages


class TestErrorOnCallbackIsVisible:
    """[A] Упавший callback-обработчик не должен оставлять «крутилку»."""

    async def test_callback_gets_toast_and_message(self, outgoing):
        toasts, messages = outgoing
        call = make_callback(make_message("меню"))

        async def boom(event, data):
            raise RuntimeError("внутри всё сломалось")

        assert await ErrorsMiddleware()(boom, call, {"lang": "ru"}) is None
        # Крутилку сняли — иначе кнопка «думает» до таймаута Telegram.
        assert toasts == [t("ru", "failed")]
        # И оставили след в чате: всплывашка живёт пару секунд.
        assert messages == [t("ru", "failed")]

    async def test_toast_fits_telegram_limit(self, outgoing):
        toasts, _ = outgoing
        call = make_callback(make_message("меню"))

        async def boom(event, data):
            raise RuntimeError

        await ErrorsMiddleware()(boom, call, {"lang": "en"})

        assert toasts and len(toasts[0]) <= 200

    async def test_callback_without_message_still_answered(self, outgoing):
        """Сообщение под кнопкой могли удалить — крутилку снять всё равно обязаны."""
        toasts, messages = outgoing
        call = make_callback(None)

        async def boom(event, data):
            raise RuntimeError

        assert await ErrorsMiddleware()(boom, call, {"lang": "ru"}) is None
        assert toasts == [t("ru", "failed")]
        assert messages == []

    async def test_broken_answer_does_not_hide_the_chat_message(self, monkeypatch, outgoing):
        """Просроченный callback_query нельзя ответить — но чат-то жив."""
        _, messages = outgoing

        async def dead_answer(self, text=None, **kw):
            raise RuntimeError("query is too old")

        monkeypatch.setattr(CallbackQuery, "answer", dead_answer)
        call = make_callback(make_message("меню"))

        async def boom(event, data):
            raise RuntimeError

        assert await ErrorsMiddleware()(boom, call, {"lang": "ru"}) is None
        assert messages == [t("ru", "failed")]

    async def test_message_path_unchanged(self, outgoing):
        _, messages = outgoing

        async def boom(event, data):
            raise RuntimeError

        assert await ErrorsMiddleware()(boom, make_message("привет"), {"lang": "ru"}) is None
        assert messages == [t("ru", "failed")]

    async def test_api_error_still_flies_up(self, outgoing):
        """ApiError разбирают выше — здесь его глотать нельзя."""
        toasts, _ = outgoing

        async def boom(event, data):
            raise ApiError(401)

        with pytest.raises(ApiError):
            await ErrorsMiddleware()(boom, make_callback(make_message("x")), {"lang": "ru"})
        assert toasts == []


# --------------------------------------------------------------------- [B] ---

class TestTokenRefreshOn401:
    """[B] 401 от нашего API — это «токен больше не принимают», а не тупик."""

    async def test_stale_token_is_replaced_and_handler_retried(
            self, monkeypatch, open_access, replies):
        api = FakeApi(tokens=["FRESH"])
        store = FakeStore(token="STALE", lang="ru")
        monkeypatch.setattr(auth_mod, "api", api)
        monkeypatch.setattr(auth_mod, "store", store)
        handler = Handler(ApiError(401, code="token_not_valid"), "handled")
        message = make_message("привет")

        result = await AuthMiddleware()(handler, message,
                                        {"event_from_user": message.from_user})

        assert result == "handled"
        assert store.dropped_token is True
        assert len(api.calls) == 1
        assert handler.calls[0]["token"] == "STALE"
        assert handler.calls[1]["token"] == "FRESH"
        assert store.token == "FRESH"
        assert replies == []

    async def test_refresh_does_not_carry_referral(self, monkeypatch, open_access, replies):
        """Починочный обмен — не создание аккаунта: чужой ref туда не подставляем."""
        api = FakeApi(tokens=["FRESH"])
        monkeypatch.setattr(auth_mod, "api", api)
        monkeypatch.setattr(auth_mod, "store", FakeStore(token="STALE", lang="ru",
                                                         seen_start=True))
        handler = Handler(ApiError(401), "handled")
        message = make_message("/start ref_ABCD1234")

        await AuthMiddleware()(handler, message, {"event_from_user": message.from_user})

        assert api.calls[-1]["ref"] == "" and api.calls[-1]["promo"] == ""

    async def test_second_401_tells_the_person(self, monkeypatch, open_access, replies):
        api = FakeApi(tokens=["FRESH"])
        monkeypatch.setattr(auth_mod, "api", api)
        monkeypatch.setattr(auth_mod, "store", FakeStore(token="STALE", lang="ru"))
        handler = Handler(ApiError(401), ApiError(401))
        message = make_message("привет")

        result = await AuthMiddleware()(handler, message,
                                        {"event_from_user": message.from_user})

        assert result is None
        assert replies == [t("ru", "auth_session_lost")]
        # Ровно один починочный обмен: бесконечно ломиться в закрытую дверь нельзя.
        assert len(api.calls) == 1
        assert len(handler.calls) == 2

    async def test_deactivated_account_gets_blocked_text(self, monkeypatch, open_access, replies):
        """Аккаунт выключили: старый токен уже 401, а новый бэкенд не выдаёт."""
        api = FakeApi(error=ApiError(403, code="inactive"))
        monkeypatch.setattr(auth_mod, "api", api)
        monkeypatch.setattr(auth_mod, "store", FakeStore(token="STALE", lang="ru"))
        handler = Handler(ApiError(401))
        message = make_message("привет")

        assert await AuthMiddleware()(handler, message,
                                      {"event_from_user": message.from_user}) is None
        assert replies == [t("ru", "blocked")]

    async def test_dead_core_on_refresh_says_server_down(self, monkeypatch, open_access, replies):
        api = FakeApi(error=ApiError(503, code="transport"))
        monkeypatch.setattr(auth_mod, "api", api)
        monkeypatch.setattr(auth_mod, "store", FakeStore(token="STALE", lang="ru"))
        handler = Handler(ApiError(401))
        message = make_message("привет")

        assert await AuthMiddleware()(handler, message,
                                      {"event_from_user": message.from_user}) is None
        assert replies == [t("ru", "server_down")]

    async def test_freshly_minted_token_is_not_reminted(self, monkeypatch, open_access, replies):
        """Токен выдали секунду назад: второй такой же ничего не изменит."""
        api = FakeApi(tokens=["FRESH", "FRESH2"])
        monkeypatch.setattr(auth_mod, "api", api)
        monkeypatch.setattr(auth_mod, "store", FakeStore(token=None))
        handler = Handler(ApiError(401))
        message = make_message("привет")

        with pytest.raises(ApiError):
            await AuthMiddleware()(handler, message, {"event_from_user": message.from_user})
        assert len(api.calls) == 1
        assert len(handler.calls) == 1

    async def test_other_api_errors_are_not_touched(self, monkeypatch, open_access, replies):
        api = FakeApi()
        monkeypatch.setattr(auth_mod, "api", api)
        monkeypatch.setattr(auth_mod, "store", FakeStore(token="STALE", lang="ru"))
        handler = Handler(ApiError(402, code="insufficient_balance"))
        message = make_message("привет")

        with pytest.raises(ApiError):
            await AuthMiddleware()(handler, message, {"event_from_user": message.from_user})
        assert api.calls == []
        assert len(handler.calls) == 1

    @pytest.mark.parametrize("lang", ["ru", "en", "kg"])
    async def test_session_lost_text_is_translated(self, lang):
        assert t(lang, "auth_session_lost") != "auth_session_lost"

    async def test_payment_handler_is_never_replayed(self, monkeypatch, open_access, replies):
        """Оплату повторять нельзя ни при каких обстоятельствах."""
        api = FakeApi()
        monkeypatch.setattr(auth_mod, "api", api)
        monkeypatch.setattr(auth_mod, "store", FakeStore(token="STALE", lang="ru"))
        handler = Handler(ApiError(401))
        message = paid_message()

        with pytest.raises(ApiError):
            await AuthMiddleware()(handler, message, {"event_from_user": message.from_user})
        assert len(handler.calls) == 1
        assert api.calls == []


class TestAuthReplyReachesTheUser:
    """[B] Новый текст про потерянный вход бесполезен, если его не видно."""

    async def test_message_gets_the_text(self, outgoing):
        _, messages = outgoing

        await AuthMiddleware._reply(make_message("привет"), t("ru", "auth_session_lost"))

        assert messages == [t("ru", "auth_session_lost")]

    async def test_callback_toast_fits_the_limit(self, monkeypatch, outgoing):
        toasts, _ = outgoing

        await AuthMiddleware._reply(make_callback(make_message("меню")), "я" * 500)

        assert toasts and len(toasts[0]) <= 200

    async def test_already_answered_callback_falls_back_to_chat(self, monkeypatch, outgoing):
        """Обработчик снял «крутилку» и только потом упал с 401.

        Второй ответ на тот же callback_query Telegram не принимает — раньше
        сообщение про потерянный вход на этом и заканчивалось, в логе.
        """
        _, messages = outgoing

        async def dead_answer(self, text=None, **kw):
            raise RuntimeError("query is too old")

        monkeypatch.setattr(CallbackQuery, "answer", dead_answer)

        await AuthMiddleware._reply(make_callback(make_message("меню")),
                                    t("ru", "auth_session_lost"))

        assert messages == [t("ru", "auth_session_lost")]

    async def test_callback_without_message_does_not_crash(self, monkeypatch, outgoing):
        async def dead_answer(self, text=None, **kw):
            raise RuntimeError("query is too old")

        monkeypatch.setattr(CallbackQuery, "answer", dead_answer)

        await AuthMiddleware._reply(make_callback(None), t("ru", "auth_session_lost"))


# --------------------------------------------------------------------- [C] ---

class FakeStartApi:
    """Витрина для start.py: журнал операций и произвольные вызовы."""

    def __init__(self, rows=None, tx_error: Exception | None = None,
                 activate=None, activate_error: Exception | None = None):
        self.rows = rows or []
        self.tx_error = tx_error
        self.activate = activate or {"credited": 0}
        self.activate_error = activate_error
        self.tx_calls = 0
        self.requests: list[dict] = []

    async def transactions(self, token, **kw):
        self.tx_calls += 1
        if self.tx_error:
            raise self.tx_error
        return self.rows

    async def request(self, method, path, **kw):
        self.requests.append({"method": method, "path": path, "body": kw.get("json_body")})
        if self.activate_error:
            raise self.activate_error
        return self.activate

    async def balance(self, token, **kw):
        return {"balance_tokens": 7}


class Answers:
    """Message, у которого нас интересуют только исходящие тексты."""

    def __init__(self, user_id: int = TG_ID, chat_id: int | None = None):
        self.from_user = make_user(user_id)
        self.chat = Chat(id=chat_id if chat_id is not None else user_id, type="private")
        self.sent: list[str] = []

    async def answer(self, text, **_):
        self.sent.append(text)


class Cmd:
    def __init__(self, args: str = ""):
        self.args = args


def promo_row(code: str = "WELCOME", delta: int = 300) -> dict:
    return {"reason": "promo", "delta": delta, "meta": {"code": code}}


def iso_ago(**delta) -> str:
    """Отметка времени в том же виде, в каком её отдаёт DRF (ISO-8601, «Z»)."""
    moment = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(**delta)
    return moment.isoformat().replace("+00:00", "Z")


class TestPromoFromDeepLink:
    """[C] Промокод из ссылки не должен применяться молча."""

    async def test_new_user_sees_how_much_was_credited(self, monkeypatch):
        api = FakeStartApi(rows=[{"reason": "signup_bonus", "delta": 50}, promo_row()])
        monkeypatch.setattr(start_mod, "api", api)
        monkeypatch.setattr(start_mod, "store", FakeStore())
        message = Answers()

        await start_mod.cmd_start(message, command=Cmd("promo_WELCOME"), token="JWT",
                                  lang="ru", auth_payload={"created": True,
                                                           "user": {"balance_tokens": 350}})

        assert t("ru", "promo_ok", credits=300) in message.sent

    async def test_returning_user_sees_it_too(self, monkeypatch):
        api = FakeStartApi(rows=[promo_row(delta=120)])
        monkeypatch.setattr(start_mod, "api", api)
        monkeypatch.setattr(start_mod, "store", FakeStore())
        message = Answers()

        await start_mod.cmd_start(message, command=Cmd("promo_WELCOME"), token="JWT",
                                  lang="ru", auth_payload={"created": False,
                                                           "user": {"balance_tokens": 120}})

        assert t("ru", "promo_ok", credits=120) in message.sent

    async def test_dead_code_gets_an_explanation(self, monkeypatch):
        """В журнале начисления нет — значит код не сработал, и это надо сказать."""
        api = FakeStartApi(rows=[{"reason": "signup_bonus", "delta": 50}])
        monkeypatch.setattr(start_mod, "api", api)
        monkeypatch.setattr(start_mod, "store", FakeStore())
        message = Answers()

        await start_mod.cmd_start(message, command=Cmd("promo_NOPE"), token="JWT",
                                  lang="ru", auth_payload={"created": True,
                                                           "user": {"balance_tokens": 50}})

        assert t("ru", "promo_fail", reason=t("ru", "start_promo_reason_none")) in message.sent

    async def test_another_promo_in_history_is_not_counted(self, monkeypatch):
        """Начисление за прошлый код не должно выдаваться за нынешний."""
        api = FakeStartApi(rows=[promo_row(code="OLDONE", delta=500)])
        monkeypatch.setattr(start_mod, "api", api)
        monkeypatch.setattr(start_mod, "store", FakeStore())
        message = Answers()

        await start_mod.cmd_start(message, command=Cmd("promo_WELCOME"), token="JWT",
                                  lang="ru", auth_payload={"created": True, "user": {}})

        assert t("ru", "promo_ok", credits=500) not in message.sent
        assert t("ru", "promo_fail", reason=t("ru", "start_promo_reason_none")) in message.sent

    async def test_same_code_credited_long_ago_is_not_counted(self, monkeypatch):
        """Повторный переход по той же ссылке: кредитов сейчас не давали.

        Бэкенд применяет код и существующему аккаунту, но второй раз тот же код
        не примет. Старая строка журнала при этом на месте — без проверки
        времени бот писал «+300 кредитов», которых не начисляли.
        """
        api = FakeStartApi(rows=[promo_row(delta=300) | {"created_at": iso_ago(days=2)}])
        monkeypatch.setattr(start_mod, "api", api)
        monkeypatch.setattr(start_mod, "store", FakeStore())
        message = Answers()

        await start_mod.cmd_start(message, command=Cmd("promo_WELCOME"), token="JWT",
                                  lang="ru", auth_payload={"created": False, "user": {}})

        assert t("ru", "promo_ok", credits=300) not in message.sent
        assert t("ru", "promo_fail", reason=t("ru", "start_promo_reason_none")) in message.sent

    async def test_credit_from_this_exchange_is_counted(self, monkeypatch):
        """А начисление секундной давности — это как раз наше."""
        api = FakeStartApi(rows=[promo_row(delta=300) | {"created_at": iso_ago(seconds=2)}])
        monkeypatch.setattr(start_mod, "api", api)
        monkeypatch.setattr(start_mod, "store", FakeStore())
        message = Answers()

        await start_mod.cmd_start(message, command=Cmd("promo_WELCOME"), token="JWT",
                                  lang="ru", auth_payload={"created": True, "user": {}})

        assert t("ru", "promo_ok", credits=300) in message.sent

    async def test_clock_skew_does_not_swallow_the_credit(self, monkeypatch):
        """Часы ядра ушли вперёд — начисление всё равно наше."""
        api = FakeStartApi(rows=[promo_row(delta=300) | {"created_at": iso_ago(seconds=-600)}])
        monkeypatch.setattr(start_mod, "api", api)
        monkeypatch.setattr(start_mod, "store", FakeStore())
        message = Answers()

        await start_mod.cmd_start(message, command=Cmd("promo_WELCOME"), token="JWT",
                                  lang="ru", auth_payload={"created": True, "user": {}})

        assert t("ru", "promo_ok", credits=300) in message.sent

    async def test_promo_is_never_activated_twice(self, monkeypatch):
        """Обмен уже применил код: второй вызов начислил бы кредиты дважды."""
        api = FakeStartApi(rows=[promo_row()])
        monkeypatch.setattr(start_mod, "api", api)
        monkeypatch.setattr(start_mod, "store", FakeStore())
        message = Answers()

        await start_mod.cmd_start(message, command=Cmd("promo_WELCOME"), token="JWT",
                                  lang="ru", auth_payload={"created": True, "user": {}})

        assert api.requests == []

    async def test_unknown_outcome_stays_silent(self, monkeypatch):
        """Журнал не ответил — «не сработал» было бы враньём."""
        api = FakeStartApi(tx_error=ApiError(503, code="transport"))
        monkeypatch.setattr(start_mod, "api", api)
        monkeypatch.setattr(start_mod, "store", FakeStore())
        message = Answers()

        await start_mod.cmd_start(message, command=Cmd("promo_WELCOME"), token="JWT",
                                  lang="ru", auth_payload={"created": True, "user": {}})

        assert not [s for s in message.sent if "ромокод" in s or "romo" in s]

    async def test_cached_token_means_backend_never_saw_the_code(self, monkeypatch):
        """Без обмена бэкенд кода не видел — активируем сами, ровно один раз."""
        api = FakeStartApi(activate={"credited": 90})
        monkeypatch.setattr(start_mod, "api", api)
        monkeypatch.setattr(start_mod, "store", FakeStore())
        message = Answers()

        await start_mod.cmd_start(message, command=Cmd("promo_WELCOME"), token="JWT",
                                  lang="ru", auth_payload=None)

        assert [r["path"] for r in api.requests] == ["/api/users/promo/activate/"]
        assert api.requests[0]["body"] == {"code": "WELCOME"}
        assert api.tx_calls == 0
        assert t("ru", "promo_ok", credits=90) in message.sent

    async def test_activation_refusal_is_explained(self, monkeypatch):
        api = FakeStartApi(activate_error=ApiError(400, code="promo_expired",
                                                   message="Срок действия промокода истёк"))
        monkeypatch.setattr(start_mod, "api", api)
        monkeypatch.setattr(start_mod, "store", FakeStore())
        message = Answers()

        await start_mod.cmd_start(message, command=Cmd("promo_WELCOME"), token="JWT",
                                  lang="ru", auth_payload=None)

        assert t("ru", "promo_fail", reason="Срок действия промокода истёк") in message.sent

    async def test_server_reason_is_escaped(self, monkeypatch):
        """parse_mode=HTML по умолчанию: неэкранированная «<» съела бы отказ целиком."""
        api = FakeStartApi(activate_error=ApiError(400, message="код <b>сгорел</b>"))
        monkeypatch.setattr(start_mod, "api", api)
        monkeypatch.setattr(start_mod, "store", FakeStore())
        message = Answers()

        await start_mod.cmd_start(message, command=Cmd("promo_WELCOME"), token="JWT",
                                  lang="ru", auth_payload=None)

        assert any("&lt;b&gt;" in s for s in message.sent)
        assert not any("<b>сгорел</b>" in s for s in message.sent)

    async def test_plain_start_asks_nothing_about_promo(self, monkeypatch):
        """Без промокода лишних запросов быть не должно."""
        api = FakeStartApi()
        monkeypatch.setattr(start_mod, "api", api)
        monkeypatch.setattr(start_mod, "store", FakeStore())
        message = Answers()

        await start_mod.cmd_start(message, command=Cmd(""), token="JWT", lang="ru",
                                  auth_payload={"created": True, "user": {}})

        assert api.tx_calls == 0 and api.requests == []

    @pytest.mark.parametrize("lang", ["ru", "en", "kg"])
    async def test_reasons_are_translated(self, lang):
        assert t(lang, "start_promo_reason_none") != "start_promo_reason_none"
        assert t(lang, "start_promo_reason_unknown") != "start_promo_reason_unknown"


# --------------------------------------------------------------------- [D] ---

class TestSessionKeyIsTheUser:
    """[D] Ключ состояния — id человека, а не id чата."""

    async def test_new_chat_uses_from_user_id(self, monkeypatch):
        store = FakeStore(model="openai/gpt-4o")
        monkeypatch.setattr(start_mod, "store", store)
        # Группа: id чата и id человека расходятся.
        message = Answers(user_id=TG_ID, chat_id=-100500)

        await start_mod.cmd_new(message, "ru")

        assert ("session", TG_ID) in store.keys
        assert ("model", TG_ID) in store.keys
        assert all(owner == TG_ID for _, owner in store.keys)

    async def test_start_and_new_read_the_same_key(self, monkeypatch):
        """/start показывает модель, /new её же — расходиться они не должны."""
        store = FakeStore(model="openai/gpt-4o")
        monkeypatch.setattr(start_mod, "store", store)
        monkeypatch.setattr(start_mod, "api", FakeStartApi())
        message = Answers(user_id=TG_ID, chat_id=-100500)

        await start_mod.cmd_start(message, command=Cmd(""), token="JWT", lang="ru",
                                  auth_payload={"created": False, "user": {}})
        from_start = [owner for key, owner in store.keys if key == "model"]
        store.keys.clear()
        await start_mod.cmd_new(message, "ru")
        from_new = [owner for key, owner in store.keys if key == "model"]

        assert from_start == from_new == [TG_ID]


# --------------------------------------------------------------------- [E] ---

def _start_filters():
    handlers = [h for h in start_mod.router.message.handlers
                if getattr(h.callback, "callback", h.callback) is start_mod.cmd_start]
    return [f for h in handlers for f in h.filters]


class TestStartInAnyCase:
    """[E] «/START ref_…» middleware уже засчитал — обработчик обязан догнать."""

    async def test_uppercase_start_with_referral_reaches_handler(self):
        message = make_message("/START ref_ABCD1234")
        filters = _start_filters()
        assert filters

        results = [await flt.call(message, bot=object()) for flt in filters]

        assert any(results), "«/START ref_…» не дошло до cmd_start — человек без приветствия"
        command = next(r["command"] for r in results if r)
        assert command.args == "ref_ABCD1234"

    async def test_mixed_case_plain_start_also_works(self):
        message = make_message("/Start")

        results = [await flt.call(message, bot=object()) for flt in _start_filters()]

        assert any(results)

    async def test_lowercase_start_unchanged(self):
        message = make_message("/start promo_WELCOME")

        results = [await flt.call(message, bot=object()) for flt in _start_filters()]

        assert any(results)

    async def test_middleware_and_handler_agree_on_the_command(self):
        """Обе стороны должны опознавать одну и ту же строку, иначе снова разрыв."""
        text = "/START ref_ABCD1234"
        assert auth_mod._command_name(text) == "start"
        results = [await flt.call(make_message(text), bot=object())
                   for flt in _start_filters()]
        assert any(results)


class TestRefundStillPasses:
    """Страховка: возврат — тоже платёж, его обработчик повторять нельзя."""

    async def test_refund_401_is_not_replayed(self, monkeypatch, open_access, replies):
        api = FakeApi()
        monkeypatch.setattr(auth_mod, "api", api)
        monkeypatch.setattr(auth_mod, "store", FakeStore(token="STALE", lang="ru"))
        handler = Handler(ApiError(401))
        message = make_message(refunded_payment=RefundedPayment(
            currency="XTR", total_amount=100, invoice_payload="pkg:1",
            telegram_payment_charge_id="charge-1"))

        with pytest.raises(ApiError):
            await AuthMiddleware()(handler, message, {"event_from_user": message.from_user})
        assert len(handler.calls) == 1
