# -*- coding: utf-8 -*-
"""Второй раунд, группа account-profile.

Здесь проверяется то, что человек видит своими глазами: правильная ли причина
отказа при привязке, дошло ли обращение в поддержку, пришли ли уведомления
целиком, на своём ли языке подсказка про промокод, виден ли только что
начатый чат в истории и отвечает ли кнопка, когда сервер молчит.
"""
from types import SimpleNamespace

import pytest

import bot.routers.account as account
import bot.routers.profile as profile
from bot.services.api import ApiError
from bot.texts import t

HUMAN = 4242
BOT_ID = 999999  # id самого бота: он стоит в from_user у call.message
LANGS = ("ru", "en", "kg")


# ------------------------------------------------------------- заглушки ---

class FakeMessage:
    _next_mid = [5000]

    def __init__(self, chat_id=HUMAN, user_id=HUMAN, text=""):
        FakeMessage._next_mid[0] += 1
        self.chat = SimpleNamespace(id=chat_id)
        self.from_user = SimpleNamespace(id=user_id)
        self.message_id = FakeMessage._next_mid[0]
        self.text = text
        self.answers = []

    async def answer(self, text="", **kwargs):
        sent = FakeMessage(chat_id=self.chat.id, user_id=BOT_ID)
        self.answers.append(SimpleNamespace(text=text, kwargs=kwargs, message=sent))
        return sent

    async def edit_reply_markup(self, **kwargs):
        return None


class FakeCall:
    def __init__(self, data, message, user_id=HUMAN):
        self.data = data
        self.from_user = SimpleNamespace(id=user_id)
        self.message = message
        self.answers = []

    async def answer(self, text=None, **kwargs):
        self.answers.append(SimpleNamespace(text=text, kwargs=kwargs))


class FakeState:
    def __init__(self, data=None):
        self._data = dict(data or {})
        self.state = None

    async def get_data(self):
        return dict(self._data)

    async def update_data(self, **kwargs):
        self._data.update(kwargs)
        return dict(self._data)

    async def set_state(self, state):
        self.state = state

    async def clear(self):
        self._data = {}
        self.state = None


class FakeStore:
    def __init__(self):
        self.values = {}
        self.ttls = {}

    async def get(self, telegram_id, key, default=None):
        return self.values.get((telegram_id, key), default)

    async def set(self, telegram_id, key, value, ttl=None):
        self.values[(telegram_id, key)] = value
        self.ttls[(telegram_id, key)] = ttl

    async def drop(self, telegram_id, key):
        self.values.pop((telegram_id, key), None)

    async def set_token(self, telegram_id, token):
        pass

    async def once(self, key, ttl=86400):
        return True


@pytest.fixture
def store(monkeypatch):
    fake = FakeStore()
    monkeypatch.setattr(account, "store", fake)
    monkeypatch.setattr(profile, "store", fake)
    return fake


def texts(message):
    return [a.text for a in message.answers]


# ------------------------------- [A] причина отказа при привязке ---

async def _fail_link(monkeypatch, code, lang="ru"):
    """Провести человека до link_confirm и уронить его конкретным кодом."""
    async def fake_signin_confirm(email, code_, **kwargs):
        return {"data": {"access": "site-token"}}

    async def fake_link_start(token, **kwargs):
        return {"code": "abc123"}

    async def fake_link_confirm(code_, tg_user, **kwargs):
        raise ApiError(409, code=code, message=code)

    monkeypatch.setattr(account.api, "signin_confirm", fake_signin_confirm)
    monkeypatch.setattr(account.api, "link_start", fake_link_start)
    monkeypatch.setattr(account.api, "link_confirm", fake_link_confirm)
    message = FakeMessage(text="123456")
    await account.link_code(message, lang, FakeState({"email": "a@esai.kg"}),
                            {"id": HUMAN, "first_name": "Аня"})
    return message.answers[-1].text


class TestLinkErrorMeaning:
    """Коды из core/botapi/linking.py значат не то, что писал бот."""

    def test_already_linked_is_about_the_site_account(self):
        """already_linked = Telegram висит у аккаунта САЙТА, а не наоборот.

        И отправлять человека «отвязать в профиле на esai.kg» нельзя: такой
        кнопки нет — сайт ни разу не зовёт /api/users/telegram/link/start/,
        а отвязка (forget_telegram) живёт только под /delete в самом боте.
        Единственный живой выход — поддержка, и она должна быть названа.
        """
        for lang in LANGS:
            text = t(lang, "link_already")
            assert "/support" in text, f"{lang}: не сказано, куда идти"
            assert "esai.kg" not in text, f"{lang}: обещаем кнопку, которой нет"
            # Старая формулировка сваливала вину на Telegram человека.
            assert text != t(lang, "link_done_already")

    @pytest.mark.parametrize("lang", LANGS)
    async def test_already_linked_text_is_shown(self, monkeypatch, lang):
        assert await _fail_link(monkeypatch, "already_linked", lang) == t(lang, "link_already")

    @pytest.mark.parametrize("code,key", [
        ("code_invalid", "link_fail_code"),
        ("too_many_attempts", "link_fail_attempts"),
        ("bad_telegram_user", "link_fail_tg"),
        ("telegram_bound_to_paid_account", "link_fail_paid"),
    ])
    async def test_every_backend_code_has_its_own_text(self, monkeypatch, code, key):
        assert await _fail_link(monkeypatch, code) == t("ru", key)

    async def test_raw_backend_code_never_reaches_the_person(self, monkeypatch):
        """Раньше человек читал «Не получилось связать: code_invalid»."""
        for code in ("code_invalid", "too_many_attempts", "bad_telegram_user"):
            assert code not in await _fail_link(monkeypatch, code)

    @pytest.mark.parametrize("key", ["link_already", "link_fail_code",
                                     "link_fail_attempts", "link_fail_tg"])
    def test_texts_are_translated(self, key):
        assert len({t(lang, key) for lang in LANGS}) == 3

    async def test_server_reason_is_escaped(self, monkeypatch):
        """Причина от сервера уходит в HTML-сообщение: «<» рвёт его целиком."""
        async def fake_signin(email, **kwargs):
            raise ApiError(400, code="bad", message="<b>нет</b>")

        monkeypatch.setattr(account.api, "signin", fake_signin)
        message = FakeMessage(text="a@esai.kg")
        await account.link_email(message, "ru", FakeState())

        assert "&lt;b&gt;" in message.answers[-1].text

    @pytest.mark.parametrize("code,key", [
        ("code_invalid", "link_deep_bad"),
        ("already_linked", "link_already"),
        ("too_many_attempts", "link_fail_attempts"),
        ("telegram_bound_to_paid_account", "link_fail_paid"),
    ])
    async def test_deep_link_codes(self, monkeypatch, store, code, key):
        async def fake_link_confirm(code_, tg_user, **kwargs):
            raise ApiError(409, code=code, message=code)

        monkeypatch.setattr(account.api, "link_confirm", fake_link_confirm)
        message = FakeMessage()
        await account.link_from_deep_link(message, "ru", "xyz", {"id": HUMAN})

        assert message.answers[-1].text == t("ru", key)


# ----------------------------------------------- [B] обращение в поддержку ---

class TestSupportRequest:
    async def _send(self, monkeypatch, tg_user, profile_email=None):
        sent = {}

        async def fake_question(email, name, text, **kwargs):
            sent.update(email=email, name=name, text=text, **kwargs)
            return {"id": 1}

        async def fake_profile(token, **kwargs):
            if profile_email is None:
                raise ApiError(503, code="transport")
            return {"user": {"email": profile_email}}

        monkeypatch.setattr(account.api, "question", fake_question)
        monkeypatch.setattr(account.api, "profile", fake_profile)
        message = FakeMessage(text="Не приходит код на почту, помогите пожалуйста")
        await account.support_text(message, "tok", "ru", FakeState({"topic": "general"}), tg_user)
        return sent, message

    async def test_long_name_is_trimmed_to_model_limit(self, monkeypatch):
        """UserQuestions.name — max_length=50: длинное имя давало 400."""
        long_name = "Алекс" * 13  # 65 символов, как позволяет Telegram
        sent, message = await self._send(monkeypatch, {"id": HUMAN, "first_name": long_name})

        assert len(sent["name"]) <= 50, f"имя длиной {len(sent['name'])} сервер не примет"
        assert sent["name"] == long_name[:50]
        assert message.answers[-1].text == t("ru", "support_sent", id=1)

    async def test_question_goes_with_the_person_token(self, monkeypatch):
        """Без токена обращение анонимное: все люди бота делили один лимит по IP."""
        sent, _ = await self._send(monkeypatch, {"id": HUMAN, "first_name": "Аня"})

        assert sent["token"] == "tok"

    async def test_fallback_email_matches_backend_format(self, monkeypatch):
        """Формат берётся из core/botapi/services.py::fallback_email."""
        sent, _ = await self._send(monkeypatch, {"id": HUMAN, "first_name": "Аня"})

        assert sent["email"] == f"telegram_{HUMAN}@social.esai.local"

    async def test_real_email_wins_over_fallback(self, monkeypatch):
        sent, _ = await self._send(monkeypatch, {"id": HUMAN, "first_name": "Аня"},
                                   profile_email="human@esai.kg")

        assert sent["email"] == "human@esai.kg"

    async def test_nameless_person_gets_username(self, monkeypatch):
        sent, _ = await self._send(monkeypatch, {"id": HUMAN, "username": "anya"})

        assert sent["name"] == "@anya"


# ------------------------------------------ [C] длинный список уведомлений ---

TG_LIMIT = 4096


def _rows(count, title_len=200, body_len=400):
    return [{"title": f"{i}" + "з" * title_len, "body": "т" * body_len, "is_read": False}
            for i in range(count)]


class TestInboxFitsTelegram:
    async def _open(self, monkeypatch, rows):
        async def fake_notifications(token, **kwargs):
            return rows

        monkeypatch.setattr(account.api, "notifications", fake_notifications)
        message = FakeMessage(user_id=BOT_ID)
        await account.inbox(FakeCall("p:inbox", message), "tok", "ru")
        return message

    async def test_ten_long_notifications_are_delivered(self, monkeypatch):
        """Одним сообщением это не влезает — Telegram не принял бы ничего."""
        message = await self._open(monkeypatch, _rows(10))
        parts = texts(message)

        assert sum(len(p) for p in parts) > TG_LIMIT, "тест перестал воспроизводить переполнение"
        assert len(parts) > 1, "всё склеили в одно сообщение — оно не дойдёт"
        for part in parts:
            assert len(part) <= TG_LIMIT
        joined = "".join(parts)
        for i in range(10):
            assert f"{i}зз" in joined, f"уведомление {i} потерялось"

    async def test_short_inbox_stays_one_message(self, monkeypatch):
        message = await self._open(monkeypatch, _rows(2, title_len=10, body_len=20))

        assert len(message.answers) == 1
        assert t("ru", "inbox_title") in message.answers[0].text

    async def test_empty_inbox(self, monkeypatch):
        message = await self._open(monkeypatch, [])

        assert texts(message) == [t("ru", "inbox_empty")]


# ------------------------------------------------------ [D] промокод ---

class TestPromoTexts:
    @pytest.mark.parametrize("lang", LANGS)
    async def test_more_menu_answers_in_person_language(self, monkeypatch, store, lang):
        message = FakeMessage(user_id=BOT_ID)
        await account.more(FakeCall("more:promo", message), token="tok", lang=lang,
                           state=FakeState())

        assert message.answers[-1].text == t(lang, "promo_hint")

    @pytest.mark.parametrize("lang", LANGS)
    async def test_command_without_code_answers_in_person_language(self, lang):
        message = FakeMessage()
        await profile.cmd_promo(message, SimpleNamespace(args=""), "tok", lang)

        assert message.answers[-1].text == t(lang, "promo_hint")

    def test_hint_is_translated_and_keeps_the_command(self):
        assert len({t(lang, "promo_hint") for lang in LANGS}) == 3
        for lang in LANGS:
            assert "/promo" in t(lang, "promo_hint")

    def test_generic_reason_is_translated(self):
        assert len({t(lang, "promo_fail_generic") for lang in LANGS}) == 3

    async def test_server_reason_is_escaped(self, monkeypatch):
        async def fake_request(method, path, **kwargs):
            raise ApiError(400, code="promo_used", message="<b>уже</b>")

        monkeypatch.setattr(profile.api, "request", fake_request)
        message = FakeMessage()
        await profile.cmd_promo(message, SimpleNamespace(args="CODE"), "tok", "ru")

        assert "&lt;b&gt;" in message.answers[-1].text


# -------------------------------------------- [E] кэш списка чатов ---

class TestSessionsCacheFreshness:
    async def test_new_chat_appears_in_history_at_once(self, store, monkeypatch):
        """chat.py завёл новый чат и запомнил его id — кэш обязан протухнуть."""
        calls = []

        async def fake_sessions(token, lang="ru", telegram_id=None):
            calls.append(telegram_id)
            return [{"uid": "new", "title": "Новый чат"}, {"uid": "old", "title": "Старый"}]

        monkeypatch.setattr(profile.api, "sessions", fake_sessions)
        store.values[(HUMAN, "sessions_cache")] = [{"uid": "old", "title": "Старый"}]
        store.values[(HUMAN, "session")] = "new"

        message = FakeMessage()
        await profile.cmd_history(message, "tok", "ru")

        assert calls == [HUMAN], "список взяли из кэша, где нового чата ещё нет"
        titles = " ".join(b.text for row in
                          message.answers[-1].kwargs["reply_markup"].inline_keyboard for b in row)
        assert "Новый чат" in titles

    async def test_cache_is_used_while_it_is_still_valid(self, store, monkeypatch):
        async def fake_sessions(token, lang="ru", telegram_id=None):
            raise AssertionError("сходили на сервер, хотя кэш актуален")

        monkeypatch.setattr(profile.api, "sessions", fake_sessions)
        store.values[(HUMAN, "sessions_cache")] = [{"uid": "old", "title": "Старый"}]
        store.values[(HUMAN, "session")] = "old"

        await profile.cmd_history(FakeMessage(), "tok", "ru")

    async def test_cache_is_used_when_no_chat_is_open(self, store, monkeypatch):
        async def fake_sessions(token, lang="ru", telegram_id=None):
            raise AssertionError("сходили на сервер без причины")

        monkeypatch.setattr(profile.api, "sessions", fake_sessions)
        store.values[(HUMAN, "sessions_cache")] = [{"uid": "old", "title": "Старый"}]

        await profile.cmd_history(FakeMessage(), "tok", "ru")

    async def test_cache_lifetime_is_short(self, store, monkeypatch):
        async def fake_sessions(token, lang="ru", telegram_id=None):
            return [{"uid": "s1", "title": "Чат"}]

        monkeypatch.setattr(profile.api, "sessions", fake_sessions)
        await profile.cmd_history(FakeMessage(), "tok", "ru")

        assert store.ttls[(HUMAN, "sessions_cache")] <= 60


# --------------------------------- [F] сервер молчит, а кнопка нажата ---

class TestHistoryButtonsAnswerOnFailure:
    @pytest.fixture(autouse=True)
    def _broken_api(self, monkeypatch):
        async def fake_sessions(token, lang="ru", telegram_id=None):
            raise ApiError(503, code="transport", message="timeout")

        monkeypatch.setattr(profile.api, "sessions", fake_sessions)

    async def test_page_button_says_what_happened(self, store):
        call = FakeCall("h:p:1", FakeMessage(user_id=BOT_ID))
        await profile.history_page(call, "tok", "ru")

        assert call.answers[-1].text == t("ru", "server_down")

    async def test_open_button_says_what_happened(self, store):
        call = FakeCall("h:o:s1", FakeMessage(user_id=BOT_ID))
        await profile.history_open(call, "tok", "ru")

        assert call.answers[-1].text == t("ru", "server_down")
        assert (HUMAN, "session") not in store.values, "чат «открыли», хотя списка нет"

    async def test_command_still_answers_server_down(self, store):
        message = FakeMessage()
        await profile.cmd_history(message, "tok", "ru")

        assert texts(message) == [t("ru", "server_down")]
