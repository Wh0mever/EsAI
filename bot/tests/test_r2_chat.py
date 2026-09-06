# -*- coding: utf-8 -*-
"""Раунд 2, группа chat-format.

[A] кнопки под ответом привязаны к своему ответу, а не к последнему;
[B] подпись показывает модель, которая РЕАЛЬНО ответила;
[C] ссылка в markdown не экранируется дважды.
"""
import html as _html

import pytest

from bot.routers import chat
from bot.services.tg_format import to_html
from bot.texts import t


# --------------------------------------------------------------- заглушки ---


class FakeStore:
    def __init__(self, data=None):
        self.data = dict(data or {})
        self.dropped = []

    async def take_busy(self, uid):
        return True

    async def warned_recently(self, uid):
        return False

    async def free_busy(self, uid):
        return None

    async def get(self, uid, key, default=None):
        return self.data.get(key, default)

    async def set(self, uid, key, value, ttl=None):
        self.data[key] = value

    async def drop(self, uid, key):
        self.dropped.append(key)
        self.data.pop(key, None)


class FakeApi:
    def __init__(self, frames):
        self.frames = list(frames)
        self.calls = []

    def chat_stream(self, token, body, *, lang="ru", telegram_id=None):
        self.calls.append(dict(body))
        frames = list(self.frames)

        async def gen():
            for frame in frames:
                yield frame

        return gen()


class FakeLive:
    """Живое сообщение стрима: только id, больше от него ничего не нужно."""

    def __init__(self, message_id=4242):
        self.message_id = message_id


class FakeRenderer:
    instance = None
    live_id = 4242

    def __init__(self, message, placeholder=""):
        self.buffer = ""
        self.live = FakeLive(FakeRenderer.live_id)
        self.finished = None
        self.markup = None
        self.footer = ""
        self.failed = None
        FakeRenderer.instance = self

    async def start(self):
        return None

    async def push(self, delta):
        self.buffer += delta or ""

    async def finish(self, text, *, reply_markup=None, footer=""):
        self.finished, self.markup, self.footer = text, reply_markup, footer

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
    """Нажатие кнопки. data — то, что зашито в саму кнопку."""

    def __init__(self, data=None):
        self.data = data
        self.from_user = FakeUser()
        self.message = FakeMessage()
        self.answered = False
        self.toast = None

    async def answer(self, *args, **kwargs):
        self.answered = True
        self.toast = args[0] if args else kwargs.get("text")


def frames(*, text="готово", sources=None, reasoning="", meta=None,
           charged=None, balance=100):
    out = [{"delta": text}]
    if sources:
        out.append({"sources": sources})
    if reasoning:
        out.append({"reasoning": reasoning})
    done = {"done": True,
            "message": {"content": text, "meta": meta if meta is not None else {}},
            "session": {"id": "s-1"}}
    if charged is not None:
        done["tokens_charged"] = charged
        done["balance_tokens"] = balance
    out.append(done)
    return out


@pytest.fixture
def rig(monkeypatch):
    def setup(script, store_data=None):
        store = FakeStore(store_data)
        api = FakeApi(script)
        monkeypatch.setattr(chat, "store", store)
        monkeypatch.setattr(chat, "api", api)
        monkeypatch.setattr(chat, "StreamRenderer", FakeRenderer)
        return store, api, FakeMessage()

    return setup


def buttons(markup):
    return [b.callback_data for row in markup.inline_keyboard for b in row]


# ------------------------------------ [A] кнопки привязаны к своему ответу ---


class TestAnswerAnchoring:
    async def test_data_is_stored_under_the_answer_key(self, rig):
        """Источники/рассуждения/вопрос ложатся под ключ ИМЕННО этого ответа."""
        store, api, message = rig(frames(sources=[{"title": "первый", "url": "https://a.io"}],
                                         reasoning="рассуждаю"))

        await chat.run_chat(message, "tok", "ru", "вопрос", model="openai/gpt-4o")

        assert store.data["src:4242"] == [{"title": "первый", "url": "https://a.io"}]
        assert store.data["rsn:4242"] == "рассуждаю"
        assert store.data["pr:4242"] == "вопрос"
        # Общий ключ остаётся — по нему живут кнопки прежней версии бота.
        assert store.data["sources"] == store.data["src:4242"]
        assert store.data["last_prompt"] == "вопрос"

    async def test_callback_data_carries_message_id(self, rig):
        """Кнопка обязана нести id ответа, иначе она безадресная."""
        store, api, message = rig(frames(sources=[{"title": "s", "url": "https://a.io"}],
                                         reasoning="р"))

        await chat.run_chat(message, "tok", "ru", "вопрос", model="openai/gpt-4o")

        data = buttons(FakeRenderer.instance.markup)
        assert "c:re:4242" in data
        assert "c:src:4242" in data
        assert "c:rs:4242" in data
        # «Продолжить» не привязано к ответу: оно продолжает текущий диалог.
        assert "c:cont" in data

    async def test_callback_data_fits_telegram_limit(self, rig):
        """64 байта — жёсткий предел Telegram; хвост с id должен в него влезать."""
        FakeRenderer.live_id = 999999999
        try:
            store, api, message = rig(frames(sources=[{"title": "s"}], reasoning="р"))
            await chat.run_chat(message, "tok", "ru", "вопрос", model="openai/gpt-4o")
            for data in buttons(FakeRenderer.instance.markup):
                assert len(data.encode()) <= 64
        finally:
            FakeRenderer.live_id = 4242

    async def test_sources_of_the_old_message_not_the_fresh_one(self, monkeypatch):
        """Кнопка под старым ответом показывает СВОИ источники."""
        store = FakeStore({
            "src:100": [{"title": "источник старого ответа"}],
            "sources": [{"title": "источник свежего ответа"}],
        })
        monkeypatch.setattr(chat, "store", store)
        call = FakeCallback("c:src:100")

        await chat.show_sources(call, "ru")

        text = call.message.answers[0]
        assert "источник старого ответа" in text
        assert "источник свежего ответа" not in text

    async def test_reasoning_of_the_old_message_not_the_fresh_one(self, monkeypatch):
        store = FakeStore({"rsn:100": "мысли старого", "reasoning": "мысли свежего"})
        monkeypatch.setattr(chat, "store", store)
        call = FakeCallback("c:rs:100")

        await chat.show_reasoning(call, "ru")

        text = call.message.answers[0]
        assert "мысли старого" in text
        assert "мысли свежего" not in text

    async def test_retry_asks_the_question_of_that_very_message(self, monkeypatch):
        """«Повторить» — платное действие: переспросить чужой вопрос нельзя."""
        store = FakeStore({"pr:100": "старый вопрос", "last_prompt": "свежий вопрос"})
        monkeypatch.setattr(chat, "store", store)
        asked = []

        async def fake_run_chat(message, token, lang, text, **kwargs):
            asked.append(text)

        monkeypatch.setattr(chat, "run_chat", fake_run_chat)
        call = FakeCallback("c:re:100")

        await chat.retry(call, "tok", "ru")

        assert asked == ["старый вопрос"]

    async def test_retry_of_expired_message_spends_nothing(self, monkeypatch):
        """Ключ ответа истёк — молчим, а не переспрашиваем чужое за деньги."""
        store = FakeStore({"last_prompt": "свежий вопрос"})
        monkeypatch.setattr(chat, "store", store)
        asked = []

        async def fake_run_chat(message, token, lang, text, **kwargs):
            asked.append(text)

        monkeypatch.setattr(chat, "run_chat", fake_run_chat)
        call = FakeCallback("c:re:100")

        await chat.retry(call, "tok", "ru")

        assert asked == [], "переспросили не тот вопрос и списали кредиты"
        assert call.answered

    async def test_expired_answer_shows_no_foreign_sources(self, monkeypatch):
        store = FakeStore({"sources": [{"title": "источник свежего ответа"}]})
        monkeypatch.setattr(chat, "store", store)
        call = FakeCallback("c:src:100")

        await chat.show_sources(call, "ru")

        assert call.message.answers == []

    async def test_old_buttons_without_id_still_work(self, monkeypatch):
        """Кнопки, разосланные прежней версией, читают общий ключ как раньше."""
        store = FakeStore({"sources": [{"title": "общий ключ"}],
                           "reasoning": "общие мысли",
                           "last_prompt": "общий вопрос"})
        monkeypatch.setattr(chat, "store", store)

        call = FakeCallback("c:src")
        await chat.show_sources(call, "ru")
        assert "общий ключ" in call.message.answers[0]

        call = FakeCallback("c:rs")
        await chat.show_reasoning(call, "ru")
        assert "общие мысли" in call.message.answers[0]

        asked = []

        async def fake_run_chat(message, token, lang, text, **kwargs):
            asked.append(text)

        monkeypatch.setattr(chat, "run_chat", fake_run_chat)
        call = FakeCallback("c:re")
        await chat.retry(call, "tok", "ru")
        assert asked == ["общий вопрос"]

    async def test_retry_works_under_continued_answer(self, rig, monkeypatch):
        """«Продолжить» не пишет общий ключ — но своя кнопка обязана работать."""
        store, api, message = rig(frames(text="продолжение"))

        await chat.run_chat(message, "tok", "ru", "Продолжи.", remember_prompt=False)

        assert "c:re:4242" in buttons(FakeRenderer.instance.markup)
        assert store.data["pr:4242"] == "Продолжи."
        # Общий ключ по-прежнему не трогаем: под ПРЕДЫДУЩИМ ответом старая
        # кнопка «Повторить» должна переспросить настоящий вопрос.
        assert "last_prompt" not in store.data

        asked = []

        async def fake_run_chat(message, token, lang, text, **kwargs):
            asked.append(text)

        monkeypatch.setattr(chat, "run_chat", fake_run_chat)
        await chat.retry(FakeCallback("c:re:4242"), "tok", "ru")

        assert asked == ["Продолжи."], "кнопка под ответом «Продолжить» мертва"

    async def test_stale_buttons_say_what_happened(self, monkeypatch):
        """Данные ответа истекли — говорим об этом, а не молчим сломанной кнопкой."""
        monkeypatch.setattr(chat, "store", FakeStore())
        monkeypatch.setattr(chat, "run_chat", lambda *a, **k: None)

        for handler, data in ((chat.show_sources, "c:src:100"),
                              (chat.show_reasoning, "c:rs:100")):
            call = FakeCallback(data)
            await handler(call, "ru")
            assert call.toast == t("ru", "answer_stale")
            assert call.message.answers == []

        call = FakeCallback("c:re:100")
        await chat.retry(call, "tok", "ru")
        assert call.toast == t("ru", "answer_stale")

    def test_stale_text_exists_in_three_languages(self):
        """Текст экрана обязан быть на всех трёх языках, а не падать в русский."""
        seen = {lang: t(lang, "answer_stale") for lang in ("ru", "en", "kg")}
        assert len(set(seen.values())) == 3, seen
        assert all(v and v != "answer_stale" for v in seen.values())

    def test_filter_matches_both_shapes(self):
        """Фильтр обязан ловить и новую кнопку с id, и старую без него."""
        flt = chat._pressed("c:re")
        assert flt.resolve(FakeCallback("c:re"))
        assert flt.resolve(FakeCallback("c:re:4242"))
        assert not flt.resolve(FakeCallback("c:rs:4242"))
        assert not flt.resolve(FakeCallback("c:cont"))


# ------------------------------------------ [B] подпись показывает модель ---


class TestFooterModel:
    async def test_shows_model_that_actually_answered(self, rig):
        """Бэкенд увёл «нарисуй …» на image-модель — подпись обязана это показать."""
        store, api, message = rig(frames(meta={"model": "google/gemini-2.5-flash-image"},
                                         charged=7, balance=93))

        await chat.run_chat(message, "tok", "ru", "нарисуй кота", model="openai/gpt-4o")

        footer = FakeRenderer.instance.footer
        assert "gemini-2.5-flash-image" in footer
        assert "gpt-4o" not in footer, "подпись врёт: показана запрошенная модель"

    async def test_falls_back_to_requested_model(self, rig):
        """Старые сообщения без meta — показываем хотя бы запрошенную модель."""
        store, api, message = rig(frames(meta={}, charged=3, balance=50))

        await chat.run_chat(message, "tok", "ru", "вопрос", model="openai/gpt-4o")

        assert "gpt-4o" in FakeRenderer.instance.footer

    async def test_meta_null_does_not_break_footer(self, rig):
        """meta может прийти null — подпись не должна падать."""
        store, api, message = rig(frames(meta=None, charged=3, balance=50))
        api.frames[-1]["message"]["meta"] = None

        await chat.run_chat(message, "tok", "ru", "вопрос", model="openai/gpt-4o")

        assert "gpt-4o" in FakeRenderer.instance.footer

    async def test_footer_shape_matches_text(self, rig):
        store, api, message = rig(frames(meta={"model": "x-ai/grok-4"}, charged=2, balance=8))

        await chat.run_chat(message, "tok", "ru", "вопрос", model="openai/gpt-4o")

        assert FakeRenderer.instance.footer == t("ru", "answer_meta", model="grok-4",
                                                 credits=2, balance=8)


# ------------------------------------------- [C] ссылка не экранируется 2× ---


class TestLinkEscaping:
    def test_two_query_params_escaped_once(self):
        """«&» между параметрами: второй проход давал «&amp;amp;» и ломал адрес."""
        out = to_html("[поиск](https://esai.kg/s?q=кот&page=2)")

        assert out == '<a href="https://esai.kg/s?q=кот&amp;page=2">поиск</a>'
        assert "&amp;amp;" not in out

    def test_browser_gets_the_original_url(self):
        """Telegram декодирует ровно один раз — что после него, туда и уйдёт человек."""
        url = "https://esai.kg/s?a=1&b=2&c=3"
        out = to_html(f"[ссылка]({url})")
        href = out.split('href="', 1)[1].split('"', 1)[0]

        assert _html.unescape(href) == url

    def test_angle_brackets_in_url_still_escaped(self):
        """Одно экранирование убрали, ни одного — оставлять нельзя."""
        out = to_html("[x](https://esai.kg/?a=<b>&c=1)")

        assert "<b>" not in out
        assert "&lt;b&gt;" in out
        assert "&amp;c=1" in out and "&amp;amp;" not in out

    def test_quote_in_url_cannot_break_out_of_attribute(self):
        out = to_html('[x](https://esai.kg/?q="onmouseover=1)')

        assert '"onmouseover' not in out
        assert "&quot;onmouseover" in out
