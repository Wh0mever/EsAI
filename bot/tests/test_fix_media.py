# -*- coding: utf-8 -*-
"""Файлы и голосовые: документ не должен теряться, а кредиты — сгорать зря."""
import time
from types import SimpleNamespace

import pytest

from bot.routers import media
from bot.services.api import ApiError
from bot.texts import t


class FakeStore:
    """Память бота без Redis: те же публичные методы, что у Store."""

    def __init__(self):
        self.data: dict = {}
        self.busy: set = set()
        self.calls: list = []

    async def get(self, telegram_id, key, default=None):
        return self.data.get((telegram_id, key), default)

    async def set(self, telegram_id, key, value, ttl=None):
        self.data[(telegram_id, key)] = value

    async def drop(self, telegram_id, key):
        self.data.pop((telegram_id, key), None)

    async def take_busy(self, telegram_id):
        self.calls.append("take_busy")
        if telegram_id in self.busy:
            return False
        self.busy.add(telegram_id)
        return True

    async def free_busy(self, telegram_id):
        self.calls.append("free_busy")
        self.busy.discard(telegram_id)

    async def warned_recently(self, telegram_id):
        return False


class FakeSent:
    def __init__(self):
        self.deleted = False

    async def delete(self):
        self.deleted = True


class FakeBot:
    def __init__(self):
        self.actions = []

    async def send_chat_action(self, chat_id, action):
        self.actions.append(action)


class FakeMessage:
    def __init__(self, *, user_id=77, text="", caption=None, document=None, voice=None):
        self.from_user = SimpleNamespace(id=user_id, is_bot=False)
        self.chat = SimpleNamespace(id=user_id)
        self.bot = FakeBot()
        self.text = text
        self.caption = caption
        self.document = document
        self.voice = voice
        self.audio = None
        self.video_note = None
        self.sent: list = []
        self.fail_html = False

    async def answer(self, text, **kwargs):
        if self.fail_html and kwargs.get("parse_mode") == "HTML":
            # Так ведёт себя Telegram, когда в HTML попал неэкранированный «<».
            raise RuntimeError("can't parse entities")
        self.sent.append((text, kwargs))
        return FakeSent()

    @property
    def texts(self):
        return [text for text, _ in self.sent]


class FakeCall:
    def __init__(self, data, *, user_id=77):
        self.data = data
        self.from_user = SimpleNamespace(id=user_id, is_bot=False)
        self.message = FakeMessage(user_id=user_id)
        self.answered = False

    async def answer(self, *args, **kwargs):
        self.answered = True


class FakeState:
    def __init__(self):
        self.state = None
        self.data: dict = {}

    async def set_state(self, state):
        self.state = getattr(state, "state", state)

    async def get_state(self):
        return self.state

    async def update_data(self, **kwargs):
        self.data.update(kwargs)

    async def get_data(self):
        return dict(self.data)

    async def clear(self):
        self.state = None
        self.data = {}


class ChatSpy:
    """Подменяет run_chat: запоминает, с чем его позвали."""

    def __init__(self, store=None, user_id=77):
        self.calls: list = []
        self._store = store
        self._user_id = user_id
        self.busy_while_running = None

    async def __call__(self, message, token, lang, text, **kwargs):
        if self._store is not None:
            self.busy_while_running = self._user_id in self._store.busy
        self.calls.append({"text": text, **kwargs})
        return {}

    @property
    def last(self):
        return self.calls[-1]


ATTACHMENT = {"type": "document", "id": 5, "name": "договор.pdf", "text": "текст"}


@pytest.fixture
def store(monkeypatch):
    fake = FakeStore()
    monkeypatch.setattr(media, "store", fake)
    return fake


@pytest.fixture
def chat(monkeypatch, store):
    spy = ChatSpy(store)
    monkeypatch.setattr(media, "run_chat", spy)
    return spy


# --------------------------------------------------- [A] свой вопрос по документу ---

class TestDocOwnQuestion:
    async def test_ask_remembers_document_in_state(self, store):
        """Кнопка «Свой вопрос» обязана удержать документ до самого вопроса."""
        store.data[(77, "attachment")] = ATTACHMENT
        state = FakeState()
        call = FakeCall("doc:ask")

        await media.doc_action(call, "tok", "ru", state=state)

        assert state.state == media.DocAsk.question.state
        assert state.data["attachment"] == ATTACHMENT
        assert state.data["attachment_at"] == pytest.approx(time.time(), abs=5)
        assert call.message.texts == [t("ru", "doc_ask")]

    async def test_ready_button_cancels_waiting_for_question(self, store, chat):
        """Нажали «Пересказать» вместо обещанного вопроса — ожидание снимается."""
        store.data[(77, "attachment")] = ATTACHMENT
        state = FakeState()
        state.state = media.DocAsk.question.state
        state.data = {"attachment": ATTACHMENT, "attachment_at": time.time()}

        await media.doc_action(FakeCall("doc:sum"), "tok", "ru", state=state)

        assert state.state is None, "иначе следующая фраза уйдёт с подшитым документом"
        assert chat.last["attachments"] == [ATTACHMENT]

    async def test_question_goes_to_chat_with_the_document(self, store, chat):
        store.data[(77, "attachment")] = ATTACHMENT
        state = FakeState()
        state.state = media.DocAsk.question.state
        state.data = {"attachment": ATTACHMENT}
        message = FakeMessage(text="Сколько стоит расторжение?")

        await media.doc_question(message, "tok", "ru", state=state)

        assert chat.last["text"] == "Сколько стоит расторжение?"
        assert chat.last["attachments"] == [ATTACHMENT], "вопрос ушёл без документа"
        assert state.state is None, "состояние должно сниматься после вопроса"

    async def test_question_uses_snapshot_when_memory_expired(self, store, chat):
        """Вложение в Redis живёт полчаса — снимок в состоянии его подстрахует."""
        state = FakeState()
        state.state = media.DocAsk.question.state
        state.data = {"attachment": ATTACHMENT, "attachment_at": time.time()}

        await media.doc_question(FakeMessage(text="а что по срокам?"), "tok", "ru", state=state)

        assert chat.last["attachments"] == [ATTACHMENT]

    async def test_stale_snapshot_is_not_attached(self, store, chat):
        """Состояние в Redis живёт вечно: вчерашний документ подшивать нельзя."""
        state = FakeState()
        state.state = media.DocAsk.question.state
        state.data = {"attachment": ATTACHMENT,
                      "attachment_at": time.time() - media.ATTACHMENT_TTL - 60}

        await media.doc_question(FakeMessage(text="напиши стих про осень"), "tok", "ru",
                                 state=state)

        assert chat.last["text"] == "напиши стих про осень"
        assert chat.last["attachments"] is None, "к постороннему вопросу подшили старый файл"

    async def test_snapshot_without_timestamp_is_ignored(self, store, chat):
        """Состояния, записанные прошлой версией бота, отметки времени не имеют."""
        state = FakeState()
        state.state = media.DocAsk.question.state
        state.data = {"attachment": ATTACHMENT}

        await media.doc_question(FakeMessage(text="привет"), "tok", "ru", state=state)

        assert chat.last["attachments"] is None

    async def test_question_handler_is_bound_to_the_state(self):
        """Хендлер должен стоять в роутере media — он подключён раньше чата."""
        callbacks = [h.callback for h in media.router.message.handlers]
        assert media.doc_question in callbacks

    async def test_photo_cancels_waiting_for_question(self, store, chat, monkeypatch):
        """Фото вместо вопроса — человек передумал; молчать в ответ нельзя."""
        monkeypatch.setattr(media, "download", _fake_download)
        monkeypatch.setattr(media, "_upload", _fake_upload)
        state = FakeState()
        state.state = media.DocAsk.question.state
        message = FakeMessage()
        message.photo = [SimpleNamespace(file_id="p1", file_size=100)]

        await media.on_photo(message, "tok", "ru", state=state)

        assert state.state is None
        assert message.texts == [t("ru", "photo_ready")]


async def _fake_download(message, file_id, size, lang, **kwargs):
    return b"payload"


async def _fake_upload(message, token, lang, name, content, mime):
    return {"type": "image", "id": 1, "name": name}


# ------------------------------------------------------- [B] имя файла в HTML ---

class TestFileNameEscaping:
    async def test_angle_bracket_in_name_does_not_break_message(self, store, monkeypatch):
        monkeypatch.setattr(media, "download", _fake_download)

        async def upload(message, token, lang, name, content, mime):
            return {"type": "document", "name": name, "text": "текст"}

        monkeypatch.setattr(media, "_upload", upload)
        message = FakeMessage(document=SimpleNamespace(
            file_id="d1", file_size=1000, file_name="акт <черновик>.pdf",
            mime_type="application/pdf"))

        await media.on_document(message, "tok", "ru")

        text, kwargs = message.sent[-1]
        assert kwargs.get("parse_mode") == "HTML"
        assert "&lt;черновик&gt;" in text
        assert "<черновик>" not in text


# ------------------------------------------------ [C] расшифровка и [D] занятость ---

def _voice_message(**kwargs):
    message = FakeMessage(voice=SimpleNamespace(file_id="v1", file_size=1000, duration=5,
                                                mime_type="audio/ogg"), **kwargs)
    return message


@pytest.fixture
def transcribe(monkeypatch):
    """Подменяет платное распознавание и считает обращения к нему."""
    box = SimpleNamespace(calls=0, result={"text": "привет", "tokens_charged": 3}, error=None)

    async def fake(token, content, mime, *, lang="ru", **kw):
        box.calls += 1
        if box.error is not None:
            raise box.error
        return box.result

    monkeypatch.setattr(media.api, "transcribe", fake)
    monkeypatch.setattr(media, "download", _fake_download)
    return box


class TestVoice:
    async def test_transcript_is_escaped(self, store, chat, transcribe):
        transcribe.result = {"text": "если 5 < 6, то <b> не тег", "tokens_charged": 2}
        message = _voice_message()

        await media.on_voice(message, "tok", "ru")

        said = [text for text, kw in message.sent if kw.get("parse_mode") == "HTML"][0]
        assert "&lt;b&gt;" in said and "5 &lt; 6" in said
        assert chat.calls, "вопрос всё равно должен уйти в чат"

    async def test_chat_runs_even_if_transcript_render_fails(self, store, chat, transcribe):
        """Распознавание уже оплачено — терять вопрос из-за разметки нельзя."""
        message = _voice_message()
        message.fail_html = True

        await media.on_voice(message, "tok", "ru")

        assert chat.calls and chat.last["text"] == "привет"

    async def test_busy_is_checked_before_paying(self, store, chat, transcribe):
        store.busy.add(77)  # первое голосовое ещё обрабатывается
        message = _voice_message()

        await media.on_voice(message, "tok", "ru")

        assert transcribe.calls == 0, "второе голосовое оплачено впустую"
        assert message.texts == [t("ru", "busy")]
        assert not chat.calls

    async def test_lock_is_released_before_chat(self, store, chat, transcribe):
        message = _voice_message()

        await media.on_voice(message, "tok", "ru")

        assert store.calls[0] == "take_busy", "замок берём до обращения к API"
        assert chat.busy_while_running is False, "run_chat возьмёт замок сам"
        assert 77 not in store.busy

    @pytest.mark.parametrize("error", [
        ApiError(500, message="boom"),
        ApiError(402, code="insufficient_balance"),
    ])
    async def test_lock_is_released_on_failure(self, store, chat, transcribe, error):
        """После неудачи следующее голосовое должно проходить, а не упираться в замок."""
        transcribe.error = error

        await media.on_voice(_voice_message(), "tok", "ru")

        assert 77 not in store.busy
        assert not chat.calls

    async def test_empty_transcript_releases_lock(self, store, chat, transcribe):
        transcribe.result = {"text": "   ", "tokens_charged": 1}
        message = _voice_message()

        await media.on_voice(message, "tok", "ru")

        assert message.texts[-1] == t("ru", "voice_empty")
        assert 77 not in store.busy
        assert not chat.calls
