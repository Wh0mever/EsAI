# -*- coding: utf-8 -*-
"""Фаза 0: длинный промпт видео больше не рвётся на части.

Telegram делит текст длиннее 4096 символов на несколько сообщений. Раньше
первая часть становилась промптом и закрывала шаг мастера, остальные уходили в
текстовый чат (платный ответ модели), а ролик снимался по обрывку. Теперь
части одного человека склеиваются в окне PROMPT_MERGE_WINDOW.

Подпись к фото клиент Telegram обрезает молча по пределу (1024, у Premium
2048) — такую подпись промптом не берём и просим прислать текст отдельно.
"""
import asyncio
from types import SimpleNamespace

import pytest

from bot.routers import media, video
from bot.texts import t

WINDOW = 0.05
PROMPT = video.VideoWizard.prompt.state


class FakeStore:
    def __init__(self):
        self.data: dict = {}

    async def get(self, chat_id, key, default=None):
        return self.data.get(key, default)

    async def set(self, chat_id, key, value, ttl=None):
        self.data[key] = value

    async def drop(self, chat_id, key):
        self.data.pop(key, None)


class FakeState:
    """Как FSMContext: состояние и данные, clear() стирает оба."""

    def __init__(self, state=PROMPT):
        self.state = state
        self.data: dict = {}

    async def get_state(self):
        return self.state

    async def set_state(self, state):
        self.state = getattr(state, "state", state)

    async def get_data(self):
        return dict(self.data)

    async def update_data(self, data=None, **kwargs):
        self.data.update(data or {}, **kwargs)
        return dict(self.data)

    async def clear(self):
        self.state = None
        self.data = {}


class FakeBot:
    async def send_chat_action(self, chat_id, action):
        pass


class FakeMessage:
    def __init__(self, message_id: int, text: str | None = None, *, caption: str | None = None,
                 photo: bool = False, chat_id: int = 42, user_id: int = 7):
        self.message_id = message_id
        self.text = text
        self.caption = caption
        self.photo = [SimpleNamespace(file_id="f", file_size=10)] if photo else None
        self.chat = SimpleNamespace(id=chat_id)
        self.from_user = SimpleNamespace(id=user_id)
        self.bot = FakeBot()
        self.answers: list[str] = []

    async def answer(self, text, **kw):
        self.answers.append(text)


@pytest.fixture
def cards(monkeypatch):
    """Карточки, которые показал мастер: (chat_id, копия черновика)."""
    shown: list = []

    async def fake_card(message, token, lang, chat_id, draft, **kw):
        shown.append((chat_id, dict(draft)))

    monkeypatch.setattr(video, "_show_card", fake_card)
    monkeypatch.setattr(video, "PROMPT_MERGE_WINDOW", WINDOW)
    return shown


@pytest.fixture
def store(monkeypatch):
    fake = FakeStore()
    fake.data["vid_draft"] = {"model": "bytedance/seedance-2.0", "model_name": "Seedance"}
    monkeypatch.setattr(video, "store", fake)
    return fake


@pytest.fixture
def upload(monkeypatch):
    """Фото качается и грузится мгновенно; delay — имитация медленной загрузки."""
    box = {"delay": 0.0}

    async def download(message, file_id, size, lang):
        return b"jpeg"

    async def _upload(message, token, lang, name, content, mime):
        await asyncio.sleep(box["delay"])
        return {"type": "image", "url": "/media/frame.jpg"}

    monkeypatch.setattr(media, "download", download)
    monkeypatch.setattr(media, "_upload", _upload)
    return box


async def _send(message, state):
    await video.got_prompt(message, "tok", "ru", state)


# ------------------------------------------------------- склейка частей ---

class TestMergeParts:
    async def test_parts_sent_together_become_one_prompt(self, cards, store):
        state = FakeState()
        first, second, third = "а" * 4096, "б" * 4096, "финал сцены."
        await asyncio.gather(_send(FakeMessage(10, first), state),
                             _send(FakeMessage(11, second), state),
                             _send(FakeMessage(12, third), state))
        assert len(cards) == 1, "каждая часть показала свою карточку"
        assert cards[0][1]["prompt"] == f"{first} {second} {third}"
        assert store.data["vid_draft"]["prompt"] == cards[0][1]["prompt"]
        assert state.state is None, "шаг промпта не закрылся"
        assert state.data == {}, "буфер частей остался в FSM"

    async def test_order_follows_message_ids_not_arrival(self, cards, store):
        state = FakeState()
        await asyncio.gather(_send(FakeMessage(21, "вторая"), state),
                             _send(FakeMessage(20, "первая"), state))
        assert cards[0][1]["prompt"] == "первая вторая"

    async def test_part_inside_window_extends_the_prompt(self, cards, store):
        state = FakeState()

        async def late():
            await asyncio.sleep(WINDOW / 2)
            await _send(FakeMessage(31, "продолжение"), state)

        await asyncio.gather(_send(FakeMessage(30, "Начало."), state), late())
        assert [c[1]["prompt"] for c in cards] == ["Начало.\nпродолжение"]

    async def test_short_prompt_still_works(self, cards, store):
        state = FakeState()
        await _send(FakeMessage(1, "  кот идёт по пляжу  "), state)
        assert cards[0][1]["prompt"] == "кот идёт по пляжу"
        assert cards[0][1]["model"] == "bytedance/seedance-2.0"
        assert state.state is None

    async def test_command_inside_window_cancels_the_prompt(self, cards, store):
        """Человек ушёл командой, пока части копились: карточки не будет."""
        state = FakeState()

        async def command():
            await asyncio.sleep(WINDOW / 3)
            await state.clear()  # так делает CommandResetMiddleware и /video

        await asyncio.gather(_send(FakeMessage(40, "кот"), state), command())
        assert cards == []
        assert "prompt" not in store.data["vid_draft"]

    async def test_part_after_window_closed_is_not_glued(self, cards, store):
        """Опоздавшая к замку часть не приклеивается к уже показанной карточке."""
        state = FakeState()
        await _send(FakeMessage(50, "кот"), state)
        await _send(FakeMessage(51, "хвост"), state)  # шаг уже закрыт
        assert [c[1]["prompt"] for c in cards] == ["кот"]

    async def test_orphaned_buffer_after_restart_is_dropped(self, cards, store):
        """Бот упал посреди окна: старые части не дублируют новый промпт."""
        state = FakeState()
        state.data[video.PROMPT_BUFFER_KEY] = {
            "parts": [[5, "старый обрывок"]], "seq": 3,
            "at": video.time.time() - video.PROMPT_BUFFER_STALE - 1}
        await _send(FakeMessage(60, "новый промпт"), state)
        assert cards[0][1]["prompt"] == "новый промпт"

    async def test_redelivered_update_does_not_duplicate_text(self, cards, store):
        """AuthMiddleware после 401 повторяет обработчик с тем же сообщением."""
        state = FakeState()
        again = FakeMessage(70, "кот")
        await asyncio.gather(_send(again, state), _send(again, state))
        assert [c[1]["prompt"] for c in cards] == ["кот"]

    async def test_other_author_in_same_chat_has_own_lock(self, cards, store):
        assert video._author_key(FakeMessage(1, "a", user_id=1)) != \
            video._author_key(FakeMessage(1, "a", user_id=2))

    async def test_menu_button_leaves_the_wizard(self, cards, store):
        from bot.keyboards.common import MENU_ACTIONS

        state = FakeState()
        await _send(FakeMessage(80, next(iter(MENU_ACTIONS))), state)
        assert cards == [] and state.state is None


class TestJoinParts:
    def test_space_between_words_and_newline_after_sentence(self):
        parts = [[3, "три"], [1, "Раз два."], [2, "  четыре пять "]]
        assert video._join_parts(parts) == "Раз два.\nчетыре пять три"

    def test_garbage_is_ignored(self):
        assert video._join_parts([None, ["x"], [1, ""], [2, "ок"]]) == "ок"


# ------------------------------------------------------- подпись к фото ---

class TestCaptionLimit:
    async def test_caption_at_telegram_limit_is_not_used_as_prompt(self, cards, store, upload):
        state = FakeState()
        message = FakeMessage(90, caption="к" * 1024, photo=True)
        await video.got_photo(message, "tok", "ru", state)
        assert message.answers == [t("ru", "vid_caption_cut", limit=1024)]
        assert "1024" in message.answers[0]
        assert cards == []
        assert state.state == PROMPT, "шаг промпта должен остаться открытым"
        draft = store.data["vid_draft"]
        assert draft["first_frame"]["url"] == "/media/frame.jpg"
        assert "prompt" not in draft

        # Следующий текст — промпт, а кадр уже в черновике.
        await _send(FakeMessage(91, "полный сценарий"), state)
        assert cards[0][1]["prompt"] == "полный сценарий"
        assert cards[0][1]["first_frame"]["url"] == "/media/frame.jpg"

    async def test_premium_limit_too(self, cards, store, upload):
        message = FakeMessage(92, caption="к" * 2048, photo=True)
        await video.got_photo(message, "tok", "ru", FakeState())
        assert message.answers == [t("ru", "vid_caption_cut", limit=2048)]

    async def test_limit_counted_in_utf16_units(self, cards, store, upload):
        """Эмодзи — две единицы UTF-16: 512 штук и есть предел в 1024."""
        message = FakeMessage(93, caption="🎬" * 512, photo=True)
        await video.got_photo(message, "tok", "ru", FakeState())
        assert message.answers == [t("ru", "vid_caption_cut", limit=1024)]

    async def test_shorter_caption_is_the_prompt(self, cards, store, upload):
        state = FakeState()
        message = FakeMessage(94, caption="к" * 1023, photo=True)
        await video.got_photo(message, "tok", "ru", state)
        assert message.answers == []
        assert cards[0][1]["prompt"] == "к" * 1023
        assert cards[0][1]["first_frame"]
        assert state.state is None

    async def test_every_language_has_the_text(self):
        for lang in ("ru", "en", "kg"):
            assert "1024" in t(lang, "vid_caption_cut", limit=1024)


class TestPhotoWithText:
    async def test_photo_without_caption_asks_for_prompt(self, cards, store, upload):
        message = FakeMessage(100, photo=True)
        await video.got_photo(message, "tok", "ru", FakeState())
        assert len(message.answers) == 1 and cards == []

    async def test_photo_while_text_is_buffering_joins_the_card(self, cards, store, upload):
        """Текст и фото пришли вместе: одна карточка с кадром, без «Опишите ролик»."""
        state = FakeState()
        photo = FakeMessage(101, photo=True)
        await asyncio.gather(_send(FakeMessage(102, "сценарий"), state),
                             video.got_photo(photo, "tok", "ru", state))
        assert photo.answers == []
        assert [c[1]["prompt"] for c in cards] == ["сценарий"]
        assert cards[-1][1]["first_frame"]["url"] == "/media/frame.jpg"

    async def test_slow_photo_upload_reshows_card_with_frame(self, cards, store, upload):
        """Фото догрузилось после склейки текста: карточку показываем заново, с кадром."""
        upload["delay"] = WINDOW * 3
        state = FakeState()
        photo = FakeMessage(103, photo=True)
        await asyncio.gather(video.got_photo(photo, "tok", "ru", state),
                             _send(FakeMessage(104, "сценарий"), state))
        assert photo.answers == []
        assert len(cards) == 2
        assert "first_frame" not in cards[0][1]
        assert cards[1][1]["prompt"] == "сценарий"
        assert cards[1][1]["first_frame"]["url"] == "/media/frame.jpg"
        assert store.data["vid_draft"]["prompt"] == "сценарий"
        assert store.data["vid_draft"]["first_frame"]
