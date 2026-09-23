# -*- coding: utf-8 -*-
"""Раунд 3 (аудит): 429 и лимиты, отказы API без молчания, мастера и голос,
HTML из админки, ответ на то, что бот не разбирает, и срок жизни состояний.

Каждый тест падает на поведении до правки.
"""
import datetime
import json
import time
from types import SimpleNamespace

import httpx
import pytest
from aiogram.types import CallbackQuery, Chat, Message, User

import bot.routers.billing as billing
from bot.middlewares.auth import ErrorsMiddleware
from bot.routers import fallback, media, models
from bot.services import api as api_mod
from bot.services.api import Api, ApiError
from bot.texts import t

SECRET = "bot-service-secret-for-tests"
HUMAN = 5151
NOW = datetime.datetime(2026, 1, 1, tzinfo=datetime.timezone.utc)


@pytest.fixture(autouse=True)
def _settings(monkeypatch):
    from bot.config import settings

    monkeypatch.setattr(settings, "service_secret", SECRET)
    monkeypatch.setattr(settings, "public_host", "esai.kg")


def make_api(handler) -> Api:
    client = Api(base="http://core:8000", host="esai.kg")
    client._client = httpx.AsyncClient(base_url="http://core:8000",
                                       transport=httpx.MockTransport(handler))
    return client


@pytest.fixture
def no_sleep(monkeypatch):
    slept = []

    async def fake_sleep(seconds):
        slept.append(seconds)

    monkeypatch.setattr(api_mod.asyncio, "sleep", fake_sleep)
    return slept


# ------------------------------------------------------ [9] 429 в клиенте ---

class TestThrottledResponses:
    async def test_retry_after_is_parsed_and_error_is_temporary(self):
        api = make_api(lambda r: httpx.Response(429, headers={"Retry-After": "17"},
                                                json={"detail": "throttled"}))
        with pytest.raises(ApiError) as info:
            await api.profile("tok")
        assert info.value.status == 429
        assert info.value.retry_after == 17
        assert info.value.is_temporary
        await api.aclose()

    async def test_short_wait_is_retried_once_with_new_nonce(self, no_sleep):
        seen = []

        def handler(request):
            seen.append(request.headers["X-Bot-Nonce"])
            if len(seen) == 1:
                return httpx.Response(429, headers={"Retry-After": "1"}, json={})
            return httpx.Response(200, json={"access": "t", "user": {}, "created": False})

        api = make_api(handler)
        result = await api.auth_telegram({"id": 5}, chat_id=5)

        assert result["access"] == "t"
        assert no_sleep == [1.0]
        assert len(seen) == 2 and seen[0] != seen[1], "повтор со старым номером — replay"
        await api.aclose()

    async def test_long_wait_is_not_waited_in_handler(self, no_sleep):
        calls = []

        def handler(request):
            calls.append(1)
            return httpx.Response(429, headers={"Retry-After": "45"}, json={})

        api = make_api(handler)
        with pytest.raises(ApiError) as info:
            await api.stars_confirm({"telegram_id": 5})
        assert info.value.status == 429 and len(calls) == 1 and no_sleep == []
        await api.aclose()

    async def test_non_idempotent_calls_are_not_retried(self, no_sleep):
        calls = []

        def handler(request):
            calls.append(1)
            return httpx.Response(429, headers={"Retry-After": "1"}, json={})

        api = make_api(handler)
        with pytest.raises(ApiError):
            await api.transfer("tok", "someone", 5)
        assert len(calls) == 1, "перевод кредитов повторять нельзя"
        await api.aclose()

    async def test_support_question_carries_person_token(self):
        seen = {}

        def handler(request):
            seen["auth"] = request.headers.get("Authorization")
            return httpx.Response(201, json={"id": 3})

        api = make_api(handler)
        await api.question("a@b.c", "Аня", "помогите", token="JWT")
        assert seen["auth"] == "Bearer JWT"
        await api.aclose()


# ------------------------------------------------ [9] оплата Stars и 429 ---

class PendingStore:
    def __init__(self):
        self.queue: list = []
        self.values: dict = {}

    async def once(self, key, ttl=0):
        return True

    async def push_pending(self, name, item):
        self.queue.append(json.loads(json.dumps(item)))

    async def pop_pending(self, name, limit=50):
        items, self.queue = self.queue[:limit], self.queue[limit:]
        return items

    async def drop(self, telegram_id, key):
        self.values.pop((telegram_id, key), None)


def paid_message():
    sent = []

    async def answer(text, **kwargs):
        sent.append(text)

    payment = SimpleNamespace(invoice_payload="p1", telegram_payment_charge_id="ch-1",
                              provider_payment_charge_id="", total_amount=100, currency="XTR")
    return SimpleNamespace(successful_payment=payment, chat=SimpleNamespace(id=HUMAN),
                           from_user=SimpleNamespace(id=HUMAN), message_id=9, date=NOW,
                           answer=answer, sent=sent, bot=None)


class TestStarsConfirmOn429:
    async def test_throttled_confirm_goes_to_retry_queue(self, monkeypatch):
        """Раньше 429 считался отказом: в очередь не попадал, кредиты ждали сверки."""
        store = PendingStore()
        monkeypatch.setattr(billing, "store", store)

        async def confirm(body):
            raise ApiError(429, retry_after=30)

        monkeypatch.setattr(billing.api, "stars_confirm", confirm)
        message = paid_message()

        await billing.on_paid(message, "ru")

        assert len(store.queue) == 1
        item = store.queue[0]
        assert item["telegram_payment_charge_id"] == "ch-1" and item["chat_id"] == HUMAN
        assert item["retry_at"] == pytest.approx(time.time() + 30, abs=5)
        assert message.sent == [t("ru", "paid_pending")]

    async def test_retry_waits_for_retry_after(self, monkeypatch):
        store = PendingStore()
        store.queue = [{"telegram_payment_charge_id": "ch-1", "chat_id": None, "lang": "ru",
                        "retry_at": time.time() + 60}]
        monkeypatch.setattr(billing, "store", store)
        calls = []

        async def confirm(body):
            calls.append(body)
            return {}

        monkeypatch.setattr(billing.api, "stars_confirm", confirm)

        assert await billing.retry_pending(None) == 0
        assert calls == [], "стучались раньше, чем разрешил сервер"
        assert len(store.queue) == 1

    async def test_throttled_retry_keeps_whole_batch(self, monkeypatch):
        """Раньше 429 при повторе выбрасывал подтверждение из очереди навсегда."""
        store = PendingStore()
        store.queue = [{"telegram_payment_charge_id": f"ch-{i}", "chat_id": None, "lang": "ru"}
                       for i in range(3)]
        monkeypatch.setattr(billing, "store", store)
        calls = []

        async def confirm(body):
            calls.append(body["telegram_payment_charge_id"])
            raise ApiError(429, retry_after=20)

        monkeypatch.setattr(billing.api, "stars_confirm", confirm)

        assert await billing.retry_pending(None) == 0
        assert calls == ["ch-0"], "остальные упёрлись бы в тот же лимит"
        assert sorted(i["telegram_payment_charge_id"] for i in store.queue) == \
            ["ch-0", "ch-1", "ch-2"]
        assert "retry_at" in store.queue[0]
        # Ключи очереди не должны утечь в тело подтверждения.
        assert all("chat_id" in i and "lang" in i for i in store.queue)

    async def test_retry_sends_clean_body(self, monkeypatch):
        store = PendingStore()
        store.queue = [{"telegram_payment_charge_id": "ch-1", "chat_id": None, "lang": "ru",
                        "retry_at": time.time() - 1}]
        monkeypatch.setattr(billing, "store", store)
        bodies = []

        async def confirm(body):
            bodies.append(dict(body))
            return {}

        monkeypatch.setattr(billing.api, "stars_confirm", confirm)

        assert await billing.retry_pending(None) == 1
        assert bodies == [{"telegram_payment_charge_id": "ch-1"}]
        assert store.queue == []


# ----------------------------------------- [13] отказ API — не молчание ---

def make_user() -> User:
    return User(id=HUMAN, is_bot=False, first_name="Вася")


def make_message(text="x") -> Message:
    return Message(message_id=1, date=NOW, chat=Chat(id=HUMAN, type="private"),
                   from_user=make_user(), text=text)


@pytest.fixture
def outgoing(monkeypatch):
    toasts, messages = [], []

    async def cb_answer(self, text=None, **kw):
        toasts.append(text)
        return True

    async def msg_answer(self, text, **kw):
        messages.append((text, kw))
        return self

    monkeypatch.setattr(CallbackQuery, "answer", cb_answer)
    monkeypatch.setattr(Message, "answer", msg_answer)
    return toasts, messages


class TestApiErrorIsNotSilent:
    @pytest.mark.parametrize("error, key", [
        (ApiError(429), "rate_limited"),
        (ApiError(503, code="transport"), "server_down"),
        (ApiError(400, code="bad"), "action_failed"),
    ])
    async def test_callback_gets_toast_and_message(self, outgoing, error, key):
        toasts, messages = outgoing
        call = CallbackQuery(id="cb", from_user=make_user(), chat_instance="ci",
                             data="st:sc:1", message=make_message("меню"))

        async def boom(event, data):
            raise error

        assert await ErrorsMiddleware()(boom, call, {"lang": "ru"}) is None
        assert toasts == [t("ru", key)[:200]]
        assert [text for text, _ in messages] == [t("ru", key)]

    async def test_paywall_shows_topup_button(self, outgoing):
        toasts, messages = outgoing

        async def boom(event, data):
            raise ApiError(402, code="insufficient_balance",
                           payload={"balance_tokens": 1, "required": 9})

        await ErrorsMiddleware()(boom, make_message(), {"lang": "ru"})

        text, kwargs = messages[0]
        assert "9" in text
        markup = kwargs["reply_markup"]
        assert any(b.callback_data == "b:topup" for row in markup.inline_keyboard for b in row)

    async def test_toast_has_no_html_tags(self, outgoing):
        toasts, _ = outgoing
        call = CallbackQuery(id="cb", from_user=make_user(), chat_instance="ci",
                             data="x", message=make_message("меню"))

        async def boom(event, data):
            raise ApiError(402, code="premium_locked")

        await ErrorsMiddleware()(boom, call, {"lang": "ru"})
        assert "<b>" not in toasts[0]


# --------------------------- [12] голос и файл выводят из мастера ---

class FakeState:
    def __init__(self, state=None, data=None):
        self.state = state
        self.data = dict(data or {})

    async def get_state(self):
        return self.state

    async def get_data(self):
        return dict(self.data)

    async def clear(self):
        self.state, self.data = None, {}


class MediaStore:
    def __init__(self):
        self.data, self.busy = {}, set()

    async def get(self, telegram_id, key, default=None):
        return self.data.get((telegram_id, key), default)

    async def set(self, telegram_id, key, value, ttl=None):
        self.data[(telegram_id, key)] = value

    async def take_busy(self, telegram_id):
        if telegram_id in self.busy:
            return False
        self.busy.add(telegram_id)
        return True

    async def free_busy(self, telegram_id):
        self.busy.discard(telegram_id)

    async def warned_recently(self, telegram_id):
        return False


class FakeMediaMessage:
    def __init__(self, *, voice=None, document=None):
        self.from_user = SimpleNamespace(id=HUMAN, is_bot=False)
        self.chat = SimpleNamespace(id=HUMAN)
        self.bot = SimpleNamespace(send_chat_action=self._action)
        self.voice, self.audio, self.video_note = voice, None, None
        self.document = document
        self.caption = None
        self.texts: list = []

    async def _action(self, *a, **kw):
        return None

    async def answer(self, text, **kwargs):
        self.texts.append(text)
        return SimpleNamespace(delete=self._action)


@pytest.fixture
def media_env(monkeypatch):
    store = MediaStore()
    monkeypatch.setattr(media, "store", store)
    chats = []

    async def run_chat(message, token, lang, text, **kwargs):
        chats.append({"text": text, **kwargs})
        return {}

    async def download(*a, **kw):
        return b"data"

    async def transcribe(token, content, mime, **kw):
        return {"text": "убери фон", "tokens_charged": 1}

    async def upload(message, token, lang, name, content, mime):
        return {"type": "document", "name": name, "text": "текст"}

    monkeypatch.setattr(media, "run_chat", run_chat)
    monkeypatch.setattr(media, "download", download)
    monkeypatch.setattr(media, "_upload", upload)
    monkeypatch.setattr(media.api, "transcribe", transcribe)
    return SimpleNamespace(store=store, chats=chats)


def _voice():
    return FakeMediaMessage(voice=SimpleNamespace(file_id="v", file_size=10, duration=3,
                                                  mime_type="audio/ogg"))


class TestVoiceLeavesWizard:
    async def test_voice_cancels_photo_edit(self, media_env):
        """Сценарий аудита: «Отредактировать» → голосом вопрос → потом текст."""
        from bot.routers.image import ImageWizard

        state = FakeState(ImageWizard.edit.state, {"attachment": {"type": "image"}})
        message = _voice()

        await media.on_voice(message, "tok", "ru", state=state)

        assert state.state is None, "следующая фраза ушла бы платной правкой фото"
        assert t("ru", "media_step_dropped_voice") in message.texts
        assert media_env.chats[-1]["text"] == "убери фон"
        assert media_env.chats[-1]["attachments"] is None

    async def test_voice_answers_the_document_question(self, media_env):
        """«Свой вопрос» по документу голосом — документ едет вместе с вопросом."""
        doc = {"type": "document", "id": 1}
        state = FakeState(media.DocAsk.question.state,
                          {"attachment": doc, "attachment_at": time.time()})
        message = _voice()

        await media.on_voice(message, "tok", "ru", state=state)

        assert state.state is None
        assert media_env.chats[-1]["attachments"] == [doc]
        assert t("ru", "media_step_dropped_voice") not in message.texts

    async def test_busy_voice_keeps_the_wizard(self, media_env):
        """Голосовое, которое не разбираем, мастер не трогает."""
        media_env.store.busy.add(HUMAN)
        state = FakeState("AccountWizard:support")

        await media.on_voice(_voice(), "tok", "ru", state=state)

        assert state.state == "AccountWizard:support"


class TestDocumentLeavesWizard:
    def _doc(self, name):
        return FakeMediaMessage(document=SimpleNamespace(
            file_id="d", file_size=10, file_name=name, mime_type="application/pdf"))

    async def test_pdf_cancels_image_wizard(self, media_env):
        from bot.routers.image import ImageWizard

        state = FakeState(ImageWizard.prompt.state)
        message = self._doc("отчёт.pdf")

        await media.on_document(message, "tok", "ru", state=state)

        assert state.state is None
        assert message.texts[0] == t("ru", "media_step_dropped_file")

    async def test_image_file_in_photo_wizard_keeps_the_step(self, media_env):
        from bot.routers.studio import StudioWizard

        state = FakeState(StudioWizard.hero_photo.state)
        message = self._doc("герой.png")

        await media.on_document(message, "tok", "ru", state=state)

        assert state.state == StudioWizard.hero_photo.state
        assert message.texts == [t("ru", "media_send_as_photo")]

    async def test_unsupported_file_keeps_the_step(self, media_env):
        state = FakeState("AccountWizard:support")
        message = self._doc("архив.zip")

        await media.on_document(message, "tok", "ru", state=state)

        assert state.state == "AccountWizard:support"
        assert message.texts == [t("ru", "file_unsupported")]

    async def test_new_document_replaces_doc_question_quietly(self, media_env):
        state = FakeState(media.DocAsk.question.state)
        message = self._doc("новый.pdf")

        await media.on_document(message, "tok", "ru", state=state)

        assert state.state is None
        assert t("ru", "media_step_dropped_file") not in message.texts


# ---------------------------------------------- [14] HTML из админки ---

class TestModelCardEscaping:
    async def test_name_and_description_are_escaped(self, monkeypatch):
        model = {"id": 7, "name": "GPT <mini> & co", "openrouter_id": "x/gpt",
                 "description": "Быстрая <b>модель</b> & дешёвая"}

        async def fetch(token, lang, telegram_id):
            return [model]

        async def store_set(*a, **kw):
            return None

        monkeypatch.setattr(models, "_fetch", fetch)
        monkeypatch.setattr(models.store, "set", store_set)
        edited = {}

        async def edit_text(text, **kwargs):
            edited["text"] = text

        async def answer(*a, **kw):
            return None

        call = SimpleNamespace(data="m:s:7", from_user=SimpleNamespace(id=HUMAN),
                               message=SimpleNamespace(edit_text=edit_text), answer=answer)

        await models.pick_model(call, "tok", "ru")

        assert "GPT &lt;mini&gt; &amp; co" in edited["text"]
        assert "&lt;b&gt;модель&lt;/b&gt; &amp; дешёвая" in edited["text"]


# ------------------------------------- [15] ответ на всё непонятное ---

@pytest.fixture
def dispatcher():
    """Роутер цепляется к диспетчеру один раз на процесс — после теста отцепляем."""
    from bot.__main__ import build_dispatcher

    built = build_dispatcher()
    yield built
    for router in built.sub_routers:
        router._parent_router = None


class TestFallback:
    def test_router_is_registered_last(self, dispatcher):
        routers = [r.name for r in dispatcher.sub_routers]
        assert routers[-1] == "fallback"
        assert routers.index("chat") < routers.index("fallback")

    async def test_unknown_command_is_answered_with_menu(self):
        sent = []

        async def answer(text, **kwargs):
            sent.append((text, kwargs))

        message = SimpleNamespace(text="/modle<b>", answer=answer)
        await fallback.unknown_command(message, "ru")

        text, kwargs = sent[0]
        # Команду набрал человек: «<» в ней не должен сломать разметку ответа.
        assert "<code>/modle&lt;b&gt;</code>" in text
        assert kwargs["reply_markup"] is not None

    async def test_sticker_album_is_answered_once(self, monkeypatch):
        seen = set()

        async def once(key, ttl=0):
            if key in seen:
                return False
            seen.add(key)
            return True

        monkeypatch.setattr(fallback.store, "once", once)
        sent = []

        async def answer(text, **kwargs):
            sent.append(text)

        message = SimpleNamespace(from_user=SimpleNamespace(id=HUMAN), answer=answer)
        await fallback.unknown_content(message, "ru")
        await fallback.unknown_content(message, "ru")

        assert sent == [t("ru", "fallback_unknown")]

    @pytest.mark.parametrize("lang", ["ru", "en", "kg"])
    def test_texts_are_translated(self, lang):
        for key in ("fallback_unknown", "fallback_command", "rate_limited", "action_failed",
                    "media_step_dropped_voice", "media_step_dropped_file",
                    "media_send_as_photo"):
            assert t(lang, key) != key
        if lang != "ru":
            assert t(lang, "fallback_unknown") != t("ru", "fallback_unknown")


# ------------------------------------------ срок жизни состояний мастеров ---

def test_fsm_state_expires(dispatcher):
    from bot.__main__ import FSM_TTL

    storage = dispatcher.storage
    assert storage.state_ttl == FSM_TTL and storage.data_ttl == FSM_TTL
    assert 0 < FSM_TTL <= 7 * 24 * 3600
