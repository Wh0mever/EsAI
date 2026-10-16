# -*- coding: utf-8 -*-
"""Мастер видео: экранирование, протухший чат и слежение за задачей."""
import asyncio
from types import SimpleNamespace

import pytest

from bot.routers import video
from bot.services.api import ApiError
from bot.texts import TEXTS, t


class FakeStore:
    """Redis-заглушка: те же четыре метода, что зовёт роутер."""

    def __init__(self, data: dict | None = None, token: str | None = None):
        self.data = dict(data or {})
        self.token = token

    async def get(self, chat_id, key, default=None):
        return self.data.get(key, default)

    async def set(self, chat_id, key, value, ttl=None):
        self.data[key] = value

    async def drop(self, chat_id, key):
        self.data.pop(key, None)

    async def get_token(self, chat_id):
        return self.token


class FakeBot:
    def __init__(self):
        self.edits: list[tuple] = []
        self.sent: list[str] = []
        self.deleted = 0

    async def edit_message_text(self, text, chat_id=None, message_id=None, **kw):
        self.edits.append((text, kw))

    async def send_message(self, chat_id, text, **kw):
        self.sent.append(text)

    async def send_video(self, chat_id, url, **kw):
        self.sent.append(url)

    async def send_chat_action(self, chat_id, action):
        pass

    async def delete_message(self, chat_id, message_id):
        self.deleted += 1


class FakeMessage:
    def __init__(self, chat_id: int = 42):
        self.chat = SimpleNamespace(id=chat_id)
        self.bot = FakeBot()
        self.answers: list[tuple] = []
        self.edited: list[str] = []

    async def answer(self, text, **kw):
        self.answers.append((text, kw))
        return SimpleNamespace(message_id=len(self.answers))

    async def edit_text(self, text, **kw):
        self.edited.append(text)


class FakeCall:
    def __init__(self, data: str, message: FakeMessage):
        self.data = data
        self.message = message
        self.answered = 0

    async def answer(self, *args, **kw):
        self.answered += 1


class FakeState:
    def __init__(self):
        self.state = None

    async def set_state(self, state):
        self.state = state

    async def clear(self):
        self.state = None


@pytest.fixture
def store(monkeypatch):
    fake = FakeStore()
    monkeypatch.setattr(video, "store", fake)
    return fake


# ------------------------------------------------------- экранирование ---

class TestEscaping:
    """«<» в промпте или названии модели ломает разбор HTML целиком."""

    async def test_card_escapes_prompt_and_model(self, store, monkeypatch):
        monkeypatch.setattr(video, "api", SimpleNamespace(
            video_params=lambda *a, **kw: _async({"durations": [5], "aspect_ratios": ["16:9"]}),
            balance=lambda *a, **kw: _async({"balance_tokens": 500}),
        ))
        message = FakeMessage()
        draft = {"prompt": "кот в очках <b>смотрит</b> в окно",
                 "model_name": "Veo <3>", "cps": 4, "model": "veo"}

        await video._show_card(message, "tok", "ru", 42, draft)

        text = message.answers[0][0]
        assert "&lt;b&gt;смотрит&lt;/b&gt;" in text
        assert "<b>смотрит</b>" not in text
        assert "Veo &lt;3&gt;" in text
        # Наша собственная разметка карточки при этом остаётся живой.
        assert text.startswith("🎬 <b>")

    async def test_ask_prompt_escapes_model_name(self, store, monkeypatch):
        monkeypatch.setattr(video, "_video_models", lambda *a, **kw: _async(
            [{"openrouter_id": "veo", "name": "Veo <3>", "markup_coefficient": 4}]))
        monkeypatch.setattr(video, "api", SimpleNamespace(
            video_params=lambda *a, **kw: _async({"price_table": {"720p": {"5": 20}}})))
        message = FakeMessage()
        call = FakeCall("v:m:0", message)

        await video.pick_model(call, "tok", "ru", FakeState())

        assert "Veo &lt;3&gt;" in message.answers[0][0]
        assert "Veo <3>" not in message.answers[0][0]


# ------------------------------------------------- протухший session_id ---

class TestStaleSession:
    """Чат удалили на сайте — ядро отвечает 404 «Session not found»."""

    def _api(self, calls: list, results: list):
        async def create_job(token, body, **kw):
            calls.append(dict(body))
            outcome = results.pop(0)
            if isinstance(outcome, Exception):
                raise outcome
            return outcome

        return SimpleNamespace(create_job=create_job)

    async def test_retries_once_without_session(self, store, monkeypatch):
        store.data["session"] = "dead-chat"
        calls: list = []
        monkeypatch.setattr(video, "api", self._api(calls, [
            ApiError(404, message="Session not found"),
            {"job_id": "abc", "session": {"id": "fresh-chat"}},
        ]))
        monkeypatch.setattr(video, "_watch", lambda *a, **kw: _async(None))
        message = FakeMessage()

        await video.launch(message, "tok", "ru", {"prompt": "кот", "model": "veo", "duration": 5})
        await asyncio.sleep(0)  # даём фоновой слежке-заглушке завершиться

        assert len(calls) == 2, "повтор без session_id не состоялся"
        assert calls[0]["session_id"] == "dead-chat"
        assert "session_id" not in calls[1]
        # Ключ заменён новым чатом, а не оставлен протухшим.
        assert store.data["session"] == "fresh-chat"
        assert message.answers[0][0] == t("ru", "vid_queued")

    async def test_second_failure_is_reported_once(self, store, monkeypatch):
        store.data["session"] = "dead-chat"
        calls: list = []
        monkeypatch.setattr(video, "api", self._api(calls, [
            ApiError(404, message="Session not found"),
            ApiError(500, message="boom"),
        ]))
        message = FakeMessage()

        await video.launch(message, "tok", "ru", {"prompt": "кот", "model": "veo", "duration": 5})

        assert len(calls) == 2
        assert store.data.get("session") is None
        assert [a[0] for a in message.answers] == [t("ru", "server_down")]

    async def test_other_errors_keep_session_and_do_not_retry(self, store, monkeypatch):
        store.data["session"] = "live-chat"
        calls: list = []
        monkeypatch.setattr(video, "api", self._api(calls, [
            ApiError(409, code="job_in_progress"),
        ]))
        message = FakeMessage()

        await video.launch(message, "tok", "ru", {"prompt": "кот", "model": "veo", "duration": 5})

        assert len(calls) == 1
        assert store.data["session"] == "live-chat"
        assert [a[0] for a in message.answers] == [t("ru", "vid_busy")]

    async def test_foreign_404_keeps_session(self, store, monkeypatch):
        """Чужой 404 (упавший маршрут, прокси) не должен стирать общий с чатом ключ."""
        store.data["session"] = "live-chat"
        calls: list = []
        monkeypatch.setattr(video, "api", self._api(calls, [
            ApiError(404, payload={"detail": "Not found."}, message="Not found."),
        ]))
        message = FakeMessage()

        await video.launch(message, "tok", "ru", {"prompt": "кот", "model": "veo", "duration": 5})

        assert len(calls) == 1, "повтор на чужом 404 — лишний запрос"
        assert store.data["session"] == "live-chat", "переписка человека обнулена зря"
        assert [a[0] for a in message.answers] == [t("ru", "failed")]

    async def test_404_without_session_is_not_retried(self, store, monkeypatch):
        calls: list = []
        monkeypatch.setattr(video, "api", self._api(calls, [ApiError(404, message="not_found")]))
        message = FakeMessage()

        await video.launch(message, "tok", "ru", {"prompt": "кот", "model": "veo", "duration": 5})

        assert len(calls) == 1
        assert [a[0] for a in message.answers] == [t("ru", "failed")]


# ------------------------------------------------------ слежение за job ---

class TestWatchAuth:
    @pytest.fixture(autouse=True)
    def _fast_poll(self, monkeypatch):
        # Без пауз, но с реальным окном: старое поведение успело бы «накрутить»
        # десятки бесполезных запросов, новое обрывается на первом.
        monkeypatch.setattr(video, "POLL_INTERVAL", 0)
        monkeypatch.setattr(video, "POLL_MAX_SECONDS", 0.3)
        # Здесь проверяется только токен: окно подтверждения доставки (его
        # разбирает test_r2_video.TestDoubleDelivery) не должно тормозить прогон.
        monkeypatch.setattr(video, "NOTIFY_GRACE", 0)

    async def test_dead_token_stops_the_loop(self, store, monkeypatch):
        store.token = None
        calls: list = []

        async def job(token, uid, **kw):
            calls.append(token)
            raise ApiError(401, code="token_not_valid")

        monkeypatch.setattr(video, "api", SimpleNamespace(job=job))
        bot = FakeBot()

        await video._watch(bot, 42, 7, "abc", "old-token", "ru")

        assert len(calls) == 1, "цикл продолжил стучаться протухшим токеном"
        assert bot.edits and bot.edits[-1][0] == t("ru", "vid_watch_offline")

    async def test_same_token_in_store_is_not_reused(self, store, monkeypatch):
        store.token = "old-token"  # middleware ещё не перевыпускал
        calls: list = []

        async def job(token, uid, **kw):
            calls.append(token)
            raise ApiError(401, code="token_not_valid")

        monkeypatch.setattr(video, "api", SimpleNamespace(job=job))
        bot = FakeBot()

        await video._watch(bot, 42, 7, "abc", "old-token", "ru")

        assert len(calls) == 1
        assert bot.edits[-1][0] == t("ru", "vid_watch_offline")

    async def test_fresh_token_continues_watching(self, store, monkeypatch):
        store.token = "new-token"
        calls: list = []

        async def job(token, uid, **kw):
            calls.append(token)
            if len(calls) == 1:
                raise ApiError(401, code="token_not_valid")
            return {"job_id": "abc", "status": "done", "notified": True}

        monkeypatch.setattr(video, "api", SimpleNamespace(job=job))
        bot = FakeBot()

        await video._watch(bot, 42, 7, "abc", "old-token", "ru")

        # Отметку доставки бот теперь не только видит, но и выдерживает (ядро
        # снимает её при отказе Telegram), поэтому перечитываний больше одного —
        # важно, что все они идут свежим токеном, а не протухшим.
        assert calls[0] == "old-token"
        assert set(calls[1:]) == {"new-token"}
        assert bot.deleted == 1  # прогресс убран, ролик прислало ядро
        assert not bot.sent


class TestTexts:
    @pytest.mark.parametrize("lang", ["ru", "en", "kg"])
    def test_new_key_translated(self, lang):
        assert TEXTS[lang].get("vid_watch_offline")


def _async(value):
    """Готовая корутина с ответом — заглушкам не нужен отдельный класс."""
    async def coro():
        return value

    return coro()
