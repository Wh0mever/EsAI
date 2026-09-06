# -*- coding: utf-8 -*-
"""Профиль и деньги: чужой кэш, двойной перевод, устаревшая кнопка, экранирование.

Каждый тест здесь описывает поведение, за которое человек платит: чужой список
чатов на экране, второе списание с баланса, сообщение, которое Telegram не
принял из-за «<» в чужом имени.
"""
import asyncio
from types import SimpleNamespace

import pytest

import bot.routers.account as account
import bot.routers.profile as profile
from bot.services.api import ApiError
from bot.texts import t

HUMAN_A = 111111
HUMAN_B = 222222
BOT_ID = 999999  # id самого бота: именно он стоит в from_user у call.message


# ------------------------------------------------------------- заглушки ---

class FakeMessage:
    """Сообщение: только то, чем пользуются обработчики."""

    _next_mid = [1000]

    def __init__(self, chat_id=HUMAN_A, user_id=HUMAN_A, message_id=None, text=""):
        FakeMessage._next_mid[0] += 1
        self.chat = SimpleNamespace(id=chat_id)
        self.from_user = SimpleNamespace(id=user_id)
        self.message_id = message_id if message_id is not None else FakeMessage._next_mid[0]
        self.text = text
        self.answers = []

    async def answer(self, text="", **kwargs):
        # Ответ бота: у него from_user — бот, ровно как в проде.
        sent = FakeMessage(chat_id=self.chat.id, user_id=BOT_ID)
        self.answers.append(SimpleNamespace(text=text, kwargs=kwargs, message=sent))
        return sent

    async def edit_reply_markup(self, **kwargs):
        return None

    async def edit_text(self, text="", **kwargs):
        self.answers.append(SimpleNamespace(text=text, kwargs=kwargs, message=self))
        return self

    async def delete(self):
        return None


class FakeCall:
    def __init__(self, data, user_id, message):
        self.data = data
        self.from_user = SimpleNamespace(id=user_id)
        self.message = message
        self.answers = []

    async def answer(self, text=None, **kwargs):
        self.answers.append(text)


class FakeState:
    """FSM с настоящими точками переключения: без них гонка не воспроизводится."""

    def __init__(self, data=None):
        self._data = dict(data or {})
        self.state = None

    async def get_data(self):
        await asyncio.sleep(0)
        return dict(self._data)

    async def update_data(self, **kwargs):
        await asyncio.sleep(0)
        self._data.update(kwargs)
        return dict(self._data)

    async def set_state(self, state):
        self.state = state

    async def clear(self):
        await asyncio.sleep(0)
        self._data = {}
        self.state = None


class FakeStore:
    def __init__(self):
        self.values = {}
        self.tokens = {}
        self._once = set()

    async def get(self, telegram_id, key, default=None):
        return self.values.get((telegram_id, key), default)

    async def set(self, telegram_id, key, value, ttl=None):
        self.values[(telegram_id, key)] = value

    async def drop(self, telegram_id, key):
        self.values.pop((telegram_id, key), None)

    async def set_token(self, telegram_id, token):
        self.tokens[telegram_id] = token

    async def drop_token(self, telegram_id):
        self.tokens.pop(telegram_id, None)

    async def once(self, key, ttl=86400):
        """Повторяет SET NX: проверка и захват — до любой точки переключения."""
        fresh = key not in self._once
        self._once.add(key)
        await asyncio.sleep(0)
        return fresh


@pytest.fixture
def store(monkeypatch):
    fake = FakeStore()
    monkeypatch.setattr(account, "store", fake)
    monkeypatch.setattr(profile, "store", fake)
    return fake


def buttons(markup):
    return [b for row in markup.inline_keyboard for b in row]


# ---------------------------------------- [A] чужой кэш и чужие данные ---

class TestCallbackIdentity:
    """«☰ Ещё» шлёт call.message — сообщение БОТА. Ключевать по нему нельзя."""

    @pytest.mark.asyncio
    async def test_history_from_more_uses_presser_not_bot(self, store, monkeypatch):
        seen = []

        async def fake_sessions(token, lang="ru", telegram_id=None):
            seen.append(telegram_id)
            return [{"uid": "s1", "title": "Чат Алисы"}]

        monkeypatch.setattr(profile.api, "sessions", fake_sessions)
        message = FakeMessage(chat_id=HUMAN_A, user_id=BOT_ID)
        await account.more(FakeCall("more:history", HUMAN_A, message),
                           token="tok", lang="ru", state=FakeState())

        assert seen == [HUMAN_A]
        assert (HUMAN_A, "sessions_cache") in store.values
        assert (BOT_ID, "sessions_cache") not in store.values, "кэш лёг под id бота"

    @pytest.mark.asyncio
    async def test_second_person_never_sees_first_persons_chats(self, store, monkeypatch):
        by_user = {HUMAN_A: [{"uid": "a1", "title": "Договор аренды"}],
                   HUMAN_B: [{"uid": "b1", "title": "Рецепт плова"}]}
        asked = []

        async def fake_sessions(token, lang="ru", telegram_id=None):
            asked.append(telegram_id)
            return by_user[telegram_id]

        monkeypatch.setattr(profile.api, "sessions", fake_sessions)

        screens = {}
        for user_id in (HUMAN_A, HUMAN_B):
            message = FakeMessage(chat_id=user_id, user_id=BOT_ID)
            await account.more(FakeCall("more:history", user_id, message),
                               token="tok", lang="ru", state=FakeState())
            screens[user_id] = message.answers[-1].kwargs["reply_markup"]

        assert asked == [HUMAN_A, HUMAN_B], "второй запрос взяли из чужого кэша"
        titles_b = " ".join(b.text for b in buttons(screens[HUMAN_B]))
        assert "Рецепт плова" in titles_b
        assert "Договор аренды" not in titles_b

    @pytest.mark.asyncio
    async def test_referral_from_more_uses_presser_not_bot(self, store, monkeypatch):
        seen = []

        async def fake_request(method, path, **kwargs):
            seen.append(kwargs.get("telegram_id"))
            return {"referral_uid": "UID1", "invited_count": 2, "total_earned": 30}

        monkeypatch.setattr(profile.api, "request", fake_request)
        message = FakeMessage(chat_id=HUMAN_A, user_id=BOT_ID)
        await account.more(FakeCall("more:referral", HUMAN_A, message),
                           token="tok", lang="ru", state=FakeState())

        assert seen == [HUMAN_A]

    @pytest.mark.asyncio
    async def test_plain_history_command_still_works(self, store, monkeypatch):
        """Обычный /history: id берётся из самого сообщения, как и раньше."""
        seen = []

        async def fake_sessions(token, lang="ru", telegram_id=None):
            seen.append(telegram_id)
            return [{"uid": "s1", "title": "Чат"}]

        monkeypatch.setattr(profile.api, "sessions", fake_sessions)
        await profile.cmd_history(FakeMessage(chat_id=HUMAN_A, user_id=HUMAN_A), "tok", "ru")
        assert seen == [HUMAN_A]

    @pytest.mark.asyncio
    async def test_open_chat_is_remembered_for_the_person(self, store, monkeypatch):
        async def fake_sessions(token, lang="ru", telegram_id=None):
            return [{"uid": "s1", "title": "Мой чат"}]

        monkeypatch.setattr(profile.api, "sessions", fake_sessions)
        message = FakeMessage(chat_id=HUMAN_A, user_id=BOT_ID)
        await profile.history_open(FakeCall("h:o:s1", HUMAN_A, message), "tok", "ru")

        assert store.values[(HUMAN_A, "session")] == "s1"
        assert (BOT_ID, "session") not in store.values


# ------------------------------------------------ [B] и [C] деньги ---

def _transfer_state(mid, to="bob@esai.kg", amount=5):
    """Состояние сразу после подтверждения: снимок привязан к сообщению mid."""
    return FakeState({"to": to, "amount": amount, "comment": "", "confirm_mid": mid,
                      "confirm_to": to, "confirm_amount": amount, "confirm_comment": ""})


class TestTransferOnce:
    @pytest.mark.asyncio
    async def test_double_tap_charges_exactly_once(self, store, monkeypatch):
        """Два нажатия подряд обрабатываются параллельно — перевод должен быть один."""
        done = []

        async def fake_transfer(token, recipient, amount, comment="", **kwargs):
            done.append((recipient, amount))
            await asyncio.sleep(0)
            return {"balance": 95}

        monkeypatch.setattr(account.api, "transfer", fake_transfer)
        message = FakeMessage(chat_id=HUMAN_A, user_id=BOT_ID, message_id=555)
        state = _transfer_state(555)
        first = FakeCall("tr:go", HUMAN_A, message)
        second = FakeCall("tr:go", HUMAN_A, message)

        await asyncio.gather(account.transfer_go(first, "tok", "ru", state),
                             account.transfer_go(second, "tok", "ru", state))

        assert len(done) == 1, f"списали {len(done)} раза вместо одного"

    @pytest.mark.asyncio
    async def test_repeat_after_success_is_silent(self, store, monkeypatch):
        done = []

        async def fake_transfer(token, recipient, amount, comment="", **kwargs):
            done.append(recipient)
            return {"balance": 95}

        monkeypatch.setattr(account.api, "transfer", fake_transfer)
        message = FakeMessage(chat_id=HUMAN_A, user_id=BOT_ID, message_id=556)
        state = _transfer_state(556)

        await account.transfer_go(FakeCall("tr:go", HUMAN_A, message), "tok", "ru", state)
        await account.transfer_go(FakeCall("tr:go", HUMAN_A, message), "tok", "ru", state)

        assert done == ["bob@esai.kg"]

    @pytest.mark.asyncio
    async def test_two_people_do_not_block_each_other(self, store, monkeypatch):
        """Замок именной: перевод соседа не должен глохнуть."""
        done = []

        async def fake_transfer(token, recipient, amount, comment="", **kwargs):
            done.append(recipient)
            return {"balance": 1}

        monkeypatch.setattr(account.api, "transfer", fake_transfer)
        message = FakeMessage(chat_id=HUMAN_A, user_id=BOT_ID, message_id=777)
        await account.transfer_go(FakeCall("tr:go", HUMAN_A, message), "tok", "ru",
                                  _transfer_state(777, to="a@esai.kg"))
        await account.transfer_go(FakeCall("tr:go", HUMAN_B, message), "tok", "ru",
                                  _transfer_state(777, to="b@esai.kg"))

        assert done == ["a@esai.kg", "b@esai.kg"]


class TestStaleConfirmation:
    @pytest.mark.asyncio
    async def test_old_button_does_not_send_new_amount(self, store, monkeypatch):
        """Кнопка от прошлого подтверждения не должна переводить новые данные."""
        done = []

        async def fake_transfer(token, recipient, amount, comment="", **kwargs):
            done.append((recipient, amount))
            return {"balance": 1}

        monkeypatch.setattr(account.api, "transfer", fake_transfer)
        old_button = FakeMessage(chat_id=HUMAN_A, user_id=BOT_ID, message_id=800)
        state = _transfer_state(900, to="carol@esai.kg", amount=5000)
        call = FakeCall("tr:go", HUMAN_A, old_button)

        await account.transfer_go(call, "tok", "ru", state)

        assert done == []
        assert call.answers[-1] == t("ru", "transfer_stale")
        # Свежее подтверждение осталось рабочим — состояние не затёрли.
        assert (await state.get_data())["to"] == "carol@esai.kg"

    @pytest.mark.asyncio
    async def test_current_button_goes_through(self, store, monkeypatch):
        done = []

        async def fake_transfer(token, recipient, amount, comment="", **kwargs):
            done.append((recipient, amount))
            return {"balance": 1}

        monkeypatch.setattr(account.api, "transfer", fake_transfer)
        button = FakeMessage(chat_id=HUMAN_A, user_id=BOT_ID, message_id=901)
        await account.transfer_go(FakeCall("tr:go", HUMAN_A, button), "tok", "ru",
                                  _transfer_state(901, to="dave@esai.kg", amount=7))

        assert done == [("dave@esai.kg", 7)]

    @pytest.mark.asyncio
    async def test_abandoned_second_wizard_does_not_hijack_old_button(self, store, monkeypatch):
        """Второй перевод, брошенный на полпути, не подменяет получателя.

        Нового подтверждения не появилось, значит confirm_mid прежний — но to в
        состоянии уже чужой. Кнопка обязана переводить то, что написано на
        экране, иначе кредиты уходят тому, кого человек не подтверждал.
        """
        done = []

        async def fake_transfer(token, recipient, amount, comment="", **kwargs):
            done.append((recipient, amount))
            return {"balance": 1}

        async def fake_balance(token, **kwargs):
            return {"balance_tokens": 100}

        monkeypatch.setattr(account.api, "transfer", fake_transfer)
        monkeypatch.setattr(account.api, "balance", fake_balance)

        # Первый перевод доведён до подтверждения: alice, 50.
        human = FakeMessage(chat_id=HUMAN_A, user_id=HUMAN_A, text="-")
        state = FakeState({"to": "alice@esai.kg", "amount": 50})
        await account.transfer_comment(human, "ru", state)
        confirm = human.answers[-1].message

        # Второй перевод: человек ввёл только получателя и бросил мастер.
        await account.transfer_to(FakeMessage(chat_id=HUMAN_A, user_id=HUMAN_A,
                                              text="bob@esai.kg"), "tok", "ru", state)

        # И нажал СТАРУЮ кнопку — её message_id не менялся.
        call = FakeCall("tr:go", HUMAN_A, confirm)
        await account.transfer_go(call, "tok", "ru", state)

        # Кнопка переводит ровно то, что на ней написано, — alice и 50.
        assert done == [("alice@esai.kg", 50)], f"перевод ушёл не тому: {done}"

    @pytest.mark.asyncio
    async def test_confirmation_message_id_is_saved(self, store):
        message = FakeMessage(chat_id=HUMAN_A, user_id=HUMAN_A, text="-")
        state = FakeState({"to": "bob@esai.kg", "amount": 5})

        await account.transfer_comment(message, "ru", state)

        sent = message.answers[-1].message
        assert (await state.get_data())["confirm_mid"] == sent.message_id

    @pytest.mark.parametrize("lang", ["ru", "en", "kg"])
    def test_stale_text_exists(self, lang):
        assert t(lang, "transfer_stale") not in ("", "transfer_stale")

    def test_stale_text_is_translated(self):
        assert len({t(lang, "transfer_stale") for lang in ("ru", "en", "kg")}) == 3


# ------------------------------------------------------------- [D] блог ---

class TestBlog:
    @pytest.mark.asyncio
    async def test_button_per_article(self, monkeypatch):
        async def fake_blog(lang="ru"):
            return [{"slug": "kak-schitat-kredity", "title": "Как считаются кредиты"}]

        monkeypatch.setattr(account.api, "blog", fake_blog)
        message = FakeMessage()
        await account.show_blog(message, "ru")

        button = buttons(message.answers[-1].kwargs["reply_markup"])[0]
        assert button.text == "Как считаются кредиты"
        assert button.url.endswith("/blog/kak-schitat-kredity")

    @pytest.mark.asyncio
    async def test_no_articles_means_no_empty_keyboard(self, monkeypatch):
        async def fake_blog(lang="ru"):
            return []

        monkeypatch.setattr(account.api, "blog", fake_blog)
        message = FakeMessage()
        await account.show_blog(message, "ru")

        answer = message.answers[-1]
        assert answer.text == t("ru", "blog_empty")
        assert answer.kwargs.get("reply_markup") is None

    @pytest.mark.asyncio
    async def test_unusable_articles_do_not_produce_bare_message(self, monkeypatch):
        """Статья без slug — не ссылка: пустая клавиатура выглядит как поломка."""
        async def fake_blog(lang="ru"):
            return [{"title": "Без адреса"}, {"slug": "", "title": "Тоже без"}]

        monkeypatch.setattr(account.api, "blog", fake_blog)
        message = FakeMessage()
        await account.show_blog(message, "ru")

        answer = message.answers[-1]
        assert answer.text == t("ru", "blog_empty")
        assert answer.kwargs.get("reply_markup") is None

    @pytest.mark.asyncio
    async def test_server_down_is_not_a_crash(self, monkeypatch):
        async def fake_blog(lang="ru"):
            raise ApiError(500, "server_error")

        monkeypatch.setattr(account.api, "blog", fake_blog)
        message = FakeMessage()
        await account.show_blog(message, "ru")

        assert message.answers[-1].text == t("ru", "blog_empty")


# ------------------------------------------------- [E] экранирование ---

DANGEROUS = "<b>Ева</b> & <script>"


def _escaped(text):
    return "&lt;b&gt;" in text and "<b>Ева</b>" not in text


class TestEscaping:
    @pytest.mark.asyncio
    async def test_name_and_email_in_profile(self, monkeypatch):
        async def fake_profile(token, **kwargs):
            return {"user": {"id": 7, "first_name": DANGEROUS, "email": "a<b@mail.ru"}}

        async def fake_balance(token, **kwargs):
            return {"balance_tokens": 12, "tier": "free"}

        monkeypatch.setattr(account.api, "profile", fake_profile)
        monkeypatch.setattr(account.api, "balance", fake_balance)
        message = FakeMessage()
        await account.show_profile(message, "tok", "ru")

        text = message.answers[-1].text
        assert _escaped(text)
        assert "a&lt;b@mail.ru" in text

    @pytest.mark.asyncio
    async def test_name_after_rename(self, monkeypatch):
        saved = {}

        async def fake_update(token, **fields):
            saved.update(fields)
            return {}

        monkeypatch.setattr(account.api, "update_profile", fake_update)
        message = FakeMessage(text=DANGEROUS)
        await account.save_name(message, "tok", "ru", FakeState())

        assert saved["first_name"] == DANGEROUS, "на сервер имя должно уйти как есть"
        assert _escaped(message.answers[-1].text)

    @pytest.mark.asyncio
    async def test_recipient_in_confirmation(self, store):
        message = FakeMessage(text="-")
        await account.transfer_comment(message, "ru", FakeState({"to": DANGEROUS, "amount": 3}))

        assert _escaped(message.answers[-1].text)

    @pytest.mark.asyncio
    async def test_email_after_linking(self, store):
        message = FakeMessage()
        await account._apply_link_result(message, "ru", {"access": "new", "status": "linked"},
                                         email="a<b@mail.ru")

        assert "a&lt;b@mail.ru" in message.answers[-1].text

    @pytest.mark.asyncio
    async def test_memory_facts(self, monkeypatch):
        async def fake_memory(token, **kwargs):
            return {"items": [{"id": 1, "content": DANGEROUS}], "memory_enabled": True}

        monkeypatch.setattr(account.api, "memory", fake_memory)
        message = FakeMessage()
        await account.show_memory(message, "tok", "ru")

        assert _escaped(message.answers[-1].text)

    @pytest.mark.asyncio
    async def test_inbox_titles_and_bodies(self, monkeypatch):
        async def fake_notifications(token, **kwargs):
            return [{"title": DANGEROUS, "body": "тело <i>с тегом</i>", "is_read": False}]

        monkeypatch.setattr(account.api, "notifications", fake_notifications)
        message = FakeMessage(chat_id=HUMAN_A, user_id=BOT_ID)
        await account.inbox(FakeCall("p:inbox", HUMAN_A, message), "tok", "ru")

        text = message.answers[-1].text
        assert _escaped(text)
        assert "&lt;i&gt;с тегом" in text

    @pytest.mark.asyncio
    async def test_chat_title_when_opened(self, store, monkeypatch):
        async def fake_sessions(token, lang="ru", telegram_id=None):
            return [{"uid": "s1", "title": DANGEROUS}]

        monkeypatch.setattr(profile.api, "sessions", fake_sessions)
        message = FakeMessage(chat_id=HUMAN_A, user_id=BOT_ID)
        await profile.history_open(FakeCall("h:o:s1", HUMAN_A, message), "tok", "ru")

        assert _escaped(message.answers[-1].text)
