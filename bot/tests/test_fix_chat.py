# -*- coding: utf-8 -*-
"""Чат: протухшая сессия и экранирование источников."""
import pytest

from bot.routers import chat
from bot.services.api import ApiError
from bot.texts import t


# --------------------------------------------------------------- заглушки ---


class FakeStore:
    """Redis бота: помним, что положили, и что удалили."""

    def __init__(self, data=None):
        self.data = dict(data or {})
        self.dropped = []
        self.freed = 0

    async def take_busy(self, uid):
        return True

    async def warned_recently(self, uid):
        return False

    async def free_busy(self, uid):
        self.freed += 1

    async def get(self, uid, key, default=None):
        return self.data.get(key, default)

    async def set(self, uid, key, value, ttl=None):
        self.data[key] = value

    async def drop(self, uid, key):
        self.dropped.append(key)
        self.data.pop(key, None)


class FakeApi:
    """Каждый элемент сценария — либо список кадров, либо исключение."""

    def __init__(self, script):
        self.script = list(script)
        self.calls = []

    def chat_stream(self, token, body, *, lang="ru", telegram_id=None):
        # Копия: run_chat правит тело между попытками.
        self.calls.append(dict(body))
        step = self.script.pop(0) if self.script else []

        async def gen():
            if isinstance(step, Exception):
                raise step
                yield {}  # pragma: no cover — делает функцию генератором
            for frame in step:
                yield frame

        return gen()


class FakeRenderer:
    instance = None

    def __init__(self, message, placeholder=""):
        self.buffer = ""
        self.placeholder = placeholder
        self.failed = None
        self.finished = None
        self.starts = 0
        FakeRenderer.instance = self

    async def start(self):
        self.starts += 1

    async def push(self, delta):
        self.buffer += delta or ""

    async def finish(self, text, *, reply_markup=None, footer=""):
        self.finished = text

    async def fail(self, text, *, reply_markup=None):
        self.failed = text


class FakeBot:
    async def send_chat_action(self, *args, **kwargs):
        return True


class FakeUser:
    def __init__(self, uid=77):
        self.id = uid
        self.is_bot = False


class FakeChat:
    def __init__(self, cid=77):
        self.id = cid


class FakeMessage:
    def __init__(self):
        self.chat = FakeChat()
        self.from_user = FakeUser()
        self.bot = FakeBot()
        self.answers = []

    async def answer(self, text="", **kwargs):
        self.answers.append(text)
        return self

    async def answer_photo(self, url, **kwargs):
        self.answers.append(url)
        return self

    async def answer_video(self, url, **kwargs):
        self.answers.append(url)
        return self


class FakeCallback:
    def __init__(self):
        self.from_user = FakeUser()
        self.message = FakeMessage()
        self.answered = False

    async def answer(self, *args, **kwargs):
        self.answered = True


def session_gone_error(status=400):
    """Ровно то, что отдаёт бэкенд: {"error": "Session not found"}, без error_code."""
    payload = {"error": "Session not found"}
    return ApiError(status, code="", payload=payload, message="Session not found")


def answer_frames(session_id="new-uid", text="готово"):
    return [{"delta": text},
            {"done": True, "message": {"content": text}, "session": {"id": session_id}}]


@pytest.fixture
def rig(monkeypatch):
    """Подменяем всё, что ходит наружу; возвращаем фабрику прогона."""
    def setup(script, store_data=None):
        store = FakeStore(store_data)
        api = FakeApi(script)
        monkeypatch.setattr(chat, "store", store)
        monkeypatch.setattr(chat, "api", api)
        monkeypatch.setattr(chat, "StreamRenderer", FakeRenderer)
        return store, api, FakeMessage()

    return setup


# ------------------------------------------- [A] протухший session_id ---


class TestStaleSession:
    async def test_session_not_found_resets_key_and_retries(self, rig):
        """Чат удалили на сайте — бот забывает id и отвечает с первого раза."""
        store, api, message = rig([session_gone_error(400), answer_frames()],
                                  {"session": "old-uid", "model": "openai/gpt-4o"})

        done = await chat.run_chat(message, "tok", "ru", "вопрос")

        assert len(api.calls) == 2, "повтор без session_id не произошёл"
        assert api.calls[0]["session_id"] == "old-uid"
        assert "session_id" not in api.calls[1], "повтор ушёл со старой сессией"
        assert "session" in store.dropped, "протухший ключ остался в Redis"
        assert store.data["session"] == "new-uid"
        assert FakeRenderer.instance.failed is None
        assert FakeRenderer.instance.finished == "готово"
        assert done and done.get("done") is True

    async def test_retry_happens_exactly_once(self, rig):
        """Если и повтор упал так же — показываем ошибку, а не крутим цикл."""
        store, api, message = rig([session_gone_error(400), session_gone_error(400)],
                                  {"session": "old-uid"})

        result = await chat.run_chat(message, "tok", "ru", "вопрос")

        assert len(api.calls) == 2, "повторов должно быть ровно два запроса"
        assert result is None
        assert FakeRenderer.instance.failed == t("ru", "failed")

    async def test_404_from_site_views_also_resets(self, rig):
        """Тот же текст приходит с 404 из остальных вью сайта."""
        store, api, message = rig([session_gone_error(404), answer_frames()],
                                  {"session": "old-uid"})

        await chat.run_chat(message, "tok", "ru", "вопрос")

        assert len(api.calls) == 2
        assert "session" in store.dropped

    async def test_without_session_no_retry(self, rig):
        """Сессии не было — повторять нечего, иначе это лишний платный запрос."""
        store, api, message = rig([session_gone_error(400)], {})

        await chat.run_chat(message, "tok", "ru", "вопрос")

        assert len(api.calls) == 1
        assert store.dropped == []
        assert FakeRenderer.instance.failed == t("ru", "failed")

    async def test_other_400_keeps_session(self, rig):
        """Чужая ошибка 400 не должна стирать живой чат."""
        store, api, message = rig(
            [ApiError(400, payload={"error": "No message provided"},
                      message="No message provided")],
            {"session": "old-uid"})

        await chat.run_chat(message, "tok", "ru", "вопрос")

        assert len(api.calls) == 1
        assert store.dropped == []
        assert store.data["session"] == "old-uid"

    async def test_transport_errors_are_not_session_errors(self, rig):
        """503/504 из api.py — это сеть, а не удалённый чат."""
        store, api, message = rig(
            [ApiError(503, code="transport", message="transport")],
            {"session": "old-uid"})

        await chat.run_chat(message, "tok", "ru", "вопрос")

        assert len(api.calls) == 1
        assert store.dropped == []
        assert FakeRenderer.instance.failed == t("ru", "server_down")

    async def test_paywall_survives_retry_logic(self, rig):
        """Отказ по деньгам показывает свой экран, а не общий «не удалось»."""
        store, api, message = rig(
            [ApiError(402, code="insufficient_balance",
                      payload={"balance_tokens": 0, "required": 10})],
            {"session": "old-uid"})

        await chat.run_chat(message, "tok", "ru", "вопрос")

        assert len(api.calls) == 1
        assert store.dropped == []
        assert FakeRenderer.instance.failed and FakeRenderer.instance.failed != t("ru", "failed")

    async def test_busy_lock_released_after_retry(self, rig):
        """Замок снимается один раз даже при повторе — иначе человек залипнет."""
        store, api, message = rig([session_gone_error(400), answer_frames()],
                                  {"session": "old-uid"})

        await chat.run_chat(message, "tok", "ru", "вопрос")

        assert store.freed == 1


class TestSessionGoneDetector:
    @pytest.mark.parametrize("status", [400, 404])
    def test_detects_backend_wording(self, status):
        assert chat._session_gone(session_gone_error(status))

    def test_reads_detail_field(self):
        exc = ApiError(404, payload={"detail": "Session not found."}, message="")
        assert chat._session_gone(exc)

    @pytest.mark.parametrize("exc", [
        ApiError(500, payload={"error": "Session not found"}, message="Session not found"),
        ApiError(504, code="stream_timeout", message="ответ оборвался"),
        ApiError(400, payload={"error": "No message provided"}, message="No message provided"),
        ApiError(402, code="insufficient_balance"),
    ])
    def test_ignores_everything_else(self, exc):
        assert not chat._session_gone(exc)


# ------------------------------------------------- [B] кнопка «Источники» ---


class TestSourcesEscaping:
    async def test_title_and_url_are_escaped(self, monkeypatch):
        """«<» в заголовке и «&» в ссылке ломали сообщение целиком."""
        store = FakeStore({"sources": [
            {"title": "A < B & C \"кавычки\"", "url": "https://x.io/?a=1&b=2<x>"},
        ]})
        monkeypatch.setattr(chat, "store", store)
        call = FakeCallback()

        await chat.show_sources(call, "ru")

        text = call.message.answers[0]
        assert "A &lt; B &amp; C" in text
        assert "A < B" not in text
        assert "?a=1&amp;b=2&lt;x&gt;" in text
        assert text.count("<a href=") == 1

    async def test_source_without_url_is_escaped(self, monkeypatch):
        store = FakeStore({"sources": [{"title": "<b>жирный</b>"}]})
        monkeypatch.setattr(chat, "store", store)
        call = FakeCallback()

        await chat.show_sources(call, "ru")

        text = call.message.answers[0]
        assert "&lt;b&gt;жирный&lt;/b&gt;" in text
        assert "<b>" not in text

    async def test_plain_string_source_is_escaped(self, monkeypatch):
        store = FakeStore({"sources": ["чистый <текст> & ссылка"]})
        monkeypatch.setattr(chat, "store", store)
        call = FakeCallback()

        await chat.show_sources(call, "ru")

        text = call.message.answers[0]
        assert "&lt;текст&gt; &amp; ссылка" in text

    async def test_long_sources_split_into_messages(self, monkeypatch):
        """Переполнение лимита Telegram гасит сообщение так же, как «<» в тексте."""
        from bot.services.tg_format import CHUNK_LIMIT

        store = FakeStore({"sources": [
            {"title": "з" * 300, "url": "https://x.io/" + "u" * 600} for _ in range(10)
        ]})
        monkeypatch.setattr(chat, "store", store)
        call = FakeCallback()

        await chat.show_sources(call, "ru")

        assert len(call.message.answers) > 1, "всё уехало одним сообщением"
        for text in call.message.answers:
            assert len(text) <= CHUNK_LIMIT
            assert text.count("<a href=") == text.count("</a>")
        # Ни один источник не потерялся и заголовок обрезан до читаемого.
        assert sum(t.count("</a>") for t in call.message.answers) == 10
        assert "з" * 201 not in "".join(call.message.answers)

    async def test_empty_sources_send_nothing(self, monkeypatch):
        monkeypatch.setattr(chat, "store", FakeStore({}))
        call = FakeCallback()

        await chat.show_sources(call, "ru")

        assert call.answered and call.message.answers == []


# --------------------------------------------------- [C] кнопка «Мысли» ---


class TestReasoningEscaping:
    async def test_reasoning_goes_through_to_html(self, monkeypatch):
        """Проверка [C]: to_html уже экранирует, отдельная защита не нужна."""
        monkeypatch.setattr(chat, "store", FakeStore({"reasoning": "если a < b & b > c"}))
        call = FakeCallback()

        await chat.show_reasoning(call, "ru")

        text = call.message.answers[0]
        assert "a &lt; b &amp; b &gt; c" in text
        assert text.startswith("<blockquote expandable>")
