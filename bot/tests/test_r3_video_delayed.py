# -*- coding: utf-8 -*-
"""Раунд 3, видео: статус delayed и понятные отказы ядра.

Ядро больше не закрывает задачу как failed, когда ролик снимается дольше, чем
ждёт воркер: задача уходит в delayed, ролик довозит и присылает фоновый довоз.
Бот не должен говорить на это «не получилось» и предлагать «Повторить» —
повтор запустил бы второй платный ролик, а первый всё равно пришёл бы и
списался. Коды extend_not_owned и video_in_progress — не поломка, у них свой
человеческий текст.
"""
from types import SimpleNamespace

import pytest

from bot.routers import chat, video
from bot.services.api import ApiError
from bot.texts import TEXTS, t


class FakeStore:
    def __init__(self):
        self.data: dict = {}

    async def get(self, chat_id, key, default=None):
        return self.data.get(key, default)

    async def set(self, chat_id, key, value, ttl=None):
        self.data[key] = value

    async def drop(self, chat_id, key):
        self.data.pop(key, None)

    async def get_token(self, chat_id):
        return None


class FakeBot:
    def __init__(self, *, edit_fails: bool = False):
        self.edits: list[tuple] = []
        self.sent: list[tuple] = []
        self.videos: list[str] = []
        self.deleted = 0
        self.edit_fails = edit_fails

    async def edit_message_text(self, text, chat_id=None, message_id=None, **kw):
        if self.edit_fails:
            raise RuntimeError("message to edit not found")
        self.edits.append((text, kw))

    async def send_message(self, chat_id, text, **kw):
        self.sent.append((text, kw))

    async def send_video(self, chat_id, url, **kw):
        self.videos.append(url)

    async def send_chat_action(self, chat_id, action):
        pass

    async def delete_message(self, chat_id, message_id):
        self.deleted += 1


class FakeMessage:
    def __init__(self):
        self.chat = SimpleNamespace(id=42)
        self.answers: list[tuple] = []

    async def answer(self, text, **kw):
        self.answers.append((text, kw))
        return SimpleNamespace(message_id=len(self.answers))


@pytest.fixture(autouse=True)
def _fast(monkeypatch):
    monkeypatch.setattr(video, "store", FakeStore())
    monkeypatch.setattr(video, "POLL_INTERVAL", 0)
    monkeypatch.setattr(video, "POLL_MAX_SECONDS", 5)
    monkeypatch.setattr(video, "NOTIFY_GRACE", 0)


def _api(monkeypatch, answer: dict) -> list:
    calls: list = []

    async def job(token, uid, **kw):
        calls.append(uid)
        return answer

    monkeypatch.setattr(video, "api", SimpleNamespace(job=job))
    return calls


def _callbacks(markup) -> list[str]:
    if markup is None:
        return []
    return [getattr(b, "callback_data", "") for row in markup.inline_keyboard for b in row]


def _all_text(bot: FakeBot) -> list[str]:
    return [e[0] for e in bot.edits] + [s[0] for s in bot.sent]


def _delayed(*, notified: bool) -> dict:
    return {"job_id": "abc", "status": "delayed", "progress": "delayed",
            "error_code": "video_delayed", "notified": notified, "result": None}


# ------------------------------------------------------- слежение (_watch) ---

class TestWatchDelayed:
    async def test_progress_turns_into_honest_notice(self, monkeypatch):
        """Ядро ещё не написало — прогресс сам становится честным сообщением."""
        calls = _api(monkeypatch, _delayed(notified=False))
        bot = FakeBot()

        await video._watch(bot, 42, 7, "abc", "tok", "ru")

        assert len(calls) == 1, "бот продолжил опрашивать задачу, которую довезёт ядро"
        assert bot.edits == [(t("ru", "vid_delayed"), {"parse_mode": "HTML"})]
        # Без reply_markup Telegram убирает и кнопку «Отменить» — отменять уже нечего.
        assert "reply_markup" not in bot.edits[0][1]
        assert t("ru", "vid_failed") not in _all_text(bot)
        assert bot.sent == [] and bot.videos == []

    async def test_core_already_told_the_person(self, monkeypatch):
        """Ядро прислало своё «снимается дольше» — второе такое же не шлём."""
        _api(monkeypatch, _delayed(notified=True))
        bot = FakeBot()

        await video._watch(bot, 42, 7, "abc", "tok", "ru")

        assert bot.deleted == 1, "прогресс «Генерирую…» остался висеть"
        assert bot.sent == [] and bot.edits == [] and bot.videos == []

    async def test_notice_is_sent_when_progress_is_gone(self, monkeypatch):
        """Прогресс не отредактировать (удалён) — человек всё равно узнаёт."""
        _api(monkeypatch, _delayed(notified=False))
        bot = FakeBot(edit_fails=True)

        await video._watch(bot, 42, 7, "abc", "tok", "ru")

        assert bot.sent == [(t("ru", "vid_delayed"), {"parse_mode": "HTML"})]

    async def test_nobody_else_sends_still_no_failure(self, monkeypatch):
        """notify="" — ядро слать не будет, но и «не получилось» здесь неправда."""
        _api(monkeypatch, _delayed(notified=False))
        bot = FakeBot()

        await video._watch(bot, 42, 7, "abc", "tok", "ru", notify="")

        assert _all_text(bot) == [t("ru", "vid_delayed")]

    async def test_old_core_failed_with_delayed_code(self, monkeypatch):
        """Задачи, начатые до выкладки: ядро закрыло их failed с кодом video_delayed."""
        _api(monkeypatch, {"job_id": "abc", "status": "failed",
                           "error_code": "video_delayed", "notified": False})
        bot = FakeBot()

        await video._watch(bot, 42, 7, "abc", "tok", "ru")

        assert _all_text(bot) == [t("ru", "vid_delayed")]


# -------------------------------------------------------------- deliver() ---

class TestDeliver:
    async def test_delayed_has_no_retry_button(self):
        bot = FakeBot()

        await video.deliver(bot, 42, _delayed(notified=False), "ru")

        text, kw = bot.sent[0]
        assert text == t("ru", "vid_delayed")
        assert "v:re:abc" not in _callbacks(kw.get("reply_markup")), \
            "«Повторить» на ещё снимающемся ролике — второй платный ролик"

    async def test_extend_not_owned_is_explained_without_retry(self):
        bot = FakeBot()

        await video.deliver(bot, 42, {"job_id": "abc", "status": "failed",
                                      "error_code": "extend_not_owned"}, "ru")

        text, kw = bot.sent[0]
        assert text == t("ru", "vid_extend_not_owned")
        assert _callbacks(kw.get("reply_markup")) == []

    async def test_video_in_progress_says_busy(self):
        bot = FakeBot()

        await video.deliver(bot, 42, {"job_id": "abc", "status": "failed",
                                      "error_code": "video_in_progress"}, "ru")

        text, kw = bot.sent[0]
        assert text == t("ru", "vid_busy")
        assert "v:re:abc" in _callbacks(kw.get("reply_markup"))

    async def test_real_failure_keeps_retry(self):
        bot = FakeBot()

        await video.deliver(bot, 42, {"job_id": "abc", "status": "failed",
                                      "error_code": "provider_failed"}, "ru")

        text, kw = bot.sent[0]
        assert text == t("ru", "vid_failed")
        assert "v:re:abc" in _callbacks(kw.get("reply_markup"))


# ---------------------------------------------------------- _launch_failed ---

class TestLaunchFailed:
    @pytest.mark.parametrize("exc,key", [
        (ApiError(409, code="job_in_progress"), "vid_busy"),
        (ApiError(409, code="video_in_progress"), "vid_busy"),
        (ApiError(403, code="extend_not_owned"), "vid_extend_not_owned"),
        (ApiError(429, code="Request was throttled."), "rate_limited"),
        (ApiError(503, code="transport"), "server_down"),
        (ApiError(502), "server_down"),
        (ApiError(400, code="bad_model"), "failed"),
    ])
    async def test_code_is_explained(self, exc, key):
        message = FakeMessage()

        await video._launch_failed(message, "ru", exc)

        assert [a[0] for a in message.answers] == [t("ru", key)]


# ------------------------------------------------ видео-модель в обычном чате ---

class TestChatVideoCodes:
    """Видео-модель можно выбрать и для чата — там те же коды приходят кадром."""

    @pytest.fixture
    def rig(self, monkeypatch):
        failed: list = []

        class Store:
            async def take_busy(self, uid):
                return True

            async def warned_recently(self, uid):
                return False

            async def free_busy(self, uid):
                return None

            async def get(self, uid, key, default=None):
                return default

            async def set(self, uid, key, value, ttl=None):
                return None

            async def drop(self, uid, key):
                return None

        class Renderer:
            def __init__(self, message, placeholder=""):
                self.buffer = ""
                self.live = None

            async def start(self):
                return None

            async def push(self, delta):
                return None

            async def fail(self, text, *, reply_markup=None):
                failed.append(text)

        def setup(frame: dict | None = None, exc: ApiError | None = None):
            def chat_stream(token, body, **kw):
                async def gen():
                    if exc is not None:
                        raise exc
                    yield frame

                return gen()

            monkeypatch.setattr(chat, "store", Store())
            monkeypatch.setattr(chat, "api", SimpleNamespace(chat_stream=chat_stream))
            monkeypatch.setattr(chat, "StreamRenderer", Renderer)
            message = SimpleNamespace(
                chat=SimpleNamespace(id=7), from_user=SimpleNamespace(id=7, is_bot=False),
                bot=SimpleNamespace(send_chat_action=lambda *a, **k: _none()))
            return message, failed

        return setup

    @pytest.mark.parametrize("code,key", [
        ("video_delayed", "chat_video_delayed"),
        ("video_in_progress", "chat_video_busy"),
        ("extend_not_owned", "chat_extend_not_owned"),
    ])
    async def test_video_codes_are_not_a_generic_failure(self, rig, code, key):
        message, failed = rig({"error": "…", "error_code": code, "done": True})

        await chat.run_chat(message, "tok", "ru", "кот в очках", model="veo")

        assert failed == [t("ru", key)]
        assert t("ru", "failed") not in failed

    async def test_throttle_is_not_a_failure(self, rig):
        message, failed = rig(exc=ApiError(429, code="Request was throttled."))

        await chat.run_chat(message, "tok", "ru", "вопрос", model="gpt")

        assert failed == [t("ru", "rate_limited")]


async def _none():
    return None


@pytest.mark.parametrize("lang", ["ru", "en", "kg"])
@pytest.mark.parametrize("key", ["vid_delayed", "vid_extend_not_owned", "chat_video_delayed",
                                 "chat_video_busy", "chat_extend_not_owned"])
def test_new_texts_translated(lang, key):
    assert TEXTS[lang].get(key)
