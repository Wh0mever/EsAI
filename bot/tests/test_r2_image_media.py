# -*- coding: utf-8 -*-
"""Второй раунд: картинки и вложения.

[A] повторное нажатие уже выбранной пропорции не должно плодить карточки,
[B] «Оригинал» обязан приходить файлом, а не голой ссылкой,
[C] кнопки и промпты по документу/фото — на языке человека,
[D] фото не должно исчезать в мастерах, которые ждут текст,
[E] протухшее вложение — сказать об этом, а не молчать.
"""
from types import SimpleNamespace

import pytest
from aiogram.types import BufferedInputFile

import bot.routers.image as image
import bot.routers.media as media
from bot.texts import BASE_KEYS, TEXTS, t

NANO_ID = "google/gemini-2.5-flash-image"
NANO = {"category": "image", "openrouter_id": NANO_ID, "name": "Nano Banana",
        "markup_coefficient": 4, "supports_vision": True}


class FakeStore:
    """Память бота без Redis."""

    def __init__(self):
        self.data: dict = {}

    async def get(self, telegram_id, key, default=None):
        return self.data.get((telegram_id, key), default)

    async def set(self, telegram_id, key, value, ttl=None):
        self.data[(telegram_id, key)] = value

    async def drop(self, telegram_id, key):
        self.data.pop((telegram_id, key), None)


class FakeBot:
    def __init__(self):
        self.actions: list = []

    async def send_chat_action(self, chat_id, action):
        self.actions.append(action)


class FakeMessage:
    def __init__(self, chat_id: int = 1, user_id: int = 1, caption=None):
        self.chat = SimpleNamespace(id=chat_id)
        self.from_user = SimpleNamespace(id=user_id, is_bot=False)
        self.bot = FakeBot()
        self.text = ""
        self.caption = caption
        self.photo = [SimpleNamespace(file_id="p1", file_size=100)]
        self.sent: list = []
        self.edited: list = []
        self.documents: list = []

    async def answer(self, text, **kwargs):
        self.sent.append((text, kwargs))
        return self

    async def edit_text(self, text, **kwargs):
        self.edited.append((text, kwargs))
        return self

    async def answer_document(self, document, **kwargs):
        self.documents.append(document)
        return self

    @property
    def texts(self) -> list:
        return [text for text, _ in self.sent]


class FakeCall:
    def __init__(self, data: str, message: FakeMessage | None = None, user_id: int = 1):
        self.data = data
        self.message = message or FakeMessage(user_id=user_id)
        self.from_user = SimpleNamespace(id=user_id, is_bot=False)
        self.answers: list = []

    async def answer(self, text: str = "", **kwargs):
        self.answers.append(text)

    @property
    def answered(self) -> bool:
        return bool(self.answers)


class FakeState:
    def __init__(self, state: str | None = None):
        self.state = state
        self.data: dict = {}

    async def get_state(self):
        return self.state

    async def set_state(self, state):
        self.state = getattr(state, "state", state)

    async def update_data(self, **kwargs):
        self.data.update(kwargs)

    async def get_data(self):
        return dict(self.data)

    async def clear(self):
        self.state = None
        self.data = {}


class ChatSpy:
    def __init__(self):
        self.calls: list = []

    async def __call__(self, message, token, lang, text, **kwargs):
        self.calls.append({"text": text, **kwargs})
        return {}

    @property
    def last(self) -> dict:
        return self.calls[-1]


@pytest.fixture
def img_store(monkeypatch):
    fake = FakeStore()
    monkeypatch.setattr(image, "store", fake)
    return fake


@pytest.fixture
def catalog(monkeypatch):
    async def fake_fetch(token, lang, telegram_id):
        return [NANO]

    async def fake_balance(*args, **kwargs):
        return {"balance_tokens": 120}

    monkeypatch.setattr(image, "_fetch", fake_fetch)
    monkeypatch.setattr(image, "api", SimpleNamespace(balance=fake_balance))


@pytest.fixture
def media_store(monkeypatch):
    fake = FakeStore()
    monkeypatch.setattr(media, "store", fake)
    return fake


@pytest.fixture
def chat(monkeypatch):
    spy = ChatSpy()
    monkeypatch.setattr(media, "run_chat", spy)
    return spy


# ------------------------------------------- [A] пропорция уже выбрана ---

class TestSameRatio:
    async def test_pressing_selected_ratio_redraws_nothing(self, img_store, catalog):
        """«• 1:1» уже отмечена: Telegram на тот же текст отвечает ошибкой,
        она глоталась — и человек получал вторую такую же карточку."""
        img_store.data[(1, "img_draft")] = {"prompt": "кот", "ar": "1:1", "model": NANO_ID}
        call = FakeCall("i:ar:1:1")

        await image.pick_ratio(call, "tok", "ru")

        assert call.answers == ["1:1"], "часики снять всё равно надо"
        assert call.message.edited == [], "карточку перерисовывать нечем"
        assert call.message.sent == [], "вторая такая же карточка"

    async def test_another_ratio_still_redraws(self, img_store, catalog):
        img_store.data[(1, "img_draft")] = {"prompt": "кот", "ar": "1:1", "model": NANO_ID}
        call = FakeCall("i:ar:16:9")

        await image.pick_ratio(call, "tok", "ru")

        assert call.message.edited, "смена пропорции обязана обновить карточку"
        assert img_store.data[(1, "img_draft")]["ar"] == "16:9"

    async def test_ratio_from_expired_draft_still_shows_card(self, img_store, catalog):
        """Черновик истёк, но есть последняя картинка: карточку собираем заново,
        даже если пропорция совпадает с той, что была на кнопке."""
        img_store.data[(1, "img_last")] = {"prompt": "кот", "model": NANO_ID, "ar": "1:1"}
        call = FakeCall("i:ar:1:1")

        await image.pick_ratio(call, "tok", "ru")

        assert call.message.edited, "человек остался бы без карточки"


# ------------------------------------------------- [B] «📥 Оригинал» ---

class TestDownloadOriginal:
    async def test_original_goes_as_real_file(self, img_store, monkeypatch):
        """sendDocument по HTTP-ссылке Telegram гарантирует только для GIF/PDF/ZIP:
        png прилетал человеку текстом со ссылкой вместо файла."""
        async def fake_fetch(url):
            return b"\x89PNG-body"

        monkeypatch.setattr(image, "_fetch_original", fake_fetch)
        img_store.data[(1, "img_last")] = {"prompt": "кот",
                                           "url": "https://esai.kg/media/gen/cat_1.png"}
        call = FakeCall("i:dl")

        await image.download_original(call, "ru")

        assert len(call.message.documents) == 1
        document = call.message.documents[0]
        assert isinstance(document, BufferedInputFile), "ссылку строкой Telegram файлом не отдаст"
        assert document.data == b"\x89PNG-body"
        assert document.filename == "cat_1.png", "без имени в галерее просто «file»"
        assert call.message.texts == [], "ссылку слать незачем — файл ушёл"

    async def test_link_when_download_failed(self, img_store, monkeypatch):
        """Не скачалось — честно даём ссылку, а не молчим."""
        async def fake_fetch(url):
            return None

        monkeypatch.setattr(image, "_fetch_original", fake_fetch)
        img_store.data[(1, "img_last")] = {"prompt": "кот",
                                           "url": "https://esai.kg/media/gen/cat_1.png"}
        call = FakeCall("i:dl")

        await image.download_original(call, "ru")

        assert call.message.documents == []
        assert call.message.texts == ["https://esai.kg/media/gen/cat_1.png"]

    async def test_link_when_telegram_rejects_the_file(self, img_store, monkeypatch):
        async def fake_fetch(url):
            return b"body"

        async def boom(document, **kwargs):
            raise RuntimeError("file too big")

        monkeypatch.setattr(image, "_fetch_original", fake_fetch)
        img_store.data[(1, "img_last")] = {"url": "https://esai.kg/media/gen/cat_1.png"}
        call = FakeCall("i:dl")
        call.message.answer_document = boom

        await image.download_original(call, "ru")

        assert call.message.texts == ["https://esai.kg/media/gen/cat_1.png"]

    async def test_no_picture_yet(self, img_store, monkeypatch):
        monkeypatch.setattr(image, "_fetch_original", _never_called)
        call = FakeCall("i:dl")

        await image.download_original(call, "ru")

        assert call.message.texts == [t("ru", "img_no_last")]

    @pytest.mark.parametrize("url, expected", [
        ("https://esai.kg/media/gen/cat_1.png", "cat_1.png"),
        # Кириллица приезжает в процентах, пробелы Telegram в имени не любит.
        ("https://esai.kg/media/%D0%BA%D0%BE%D1%82%201.jpg", "кот_1.jpg"),
        ("https://esai.kg/media/gen/nameless", "image.png"),
        ("https://esai.kg/media/gen/photo.png?token=abc", "photo.png"),
        ("", "image.png"),
    ])
    def test_file_name_from_url(self, url, expected):
        assert image._original_name(url) == expected

    async def test_fetch_refuses_oversized_body(self, monkeypatch):
        """Гигантский ответ документом всё равно не уйдёт — лучше сразу ссылка."""
        monkeypatch.setattr(image, "httpx",
                            SimpleNamespace(AsyncClient=_client_returning(b"x" * 10)))
        monkeypatch.setattr(image, "ORIGINAL_LIMIT", 5)

        assert await image._fetch_original("https://esai.kg/x.png") is None

    async def test_fetch_survives_network_error(self, monkeypatch):
        monkeypatch.setattr(image, "httpx", SimpleNamespace(AsyncClient=_broken_client))

        assert await image._fetch_original("https://esai.kg/x.png") is None

    async def test_fetch_returns_body(self, monkeypatch):
        monkeypatch.setattr(image, "httpx",
                            SimpleNamespace(AsyncClient=_client_returning(b"body")))

        assert await image._fetch_original("https://esai.kg/x.png") == b"body"


async def _never_called(*args, **kwargs):
    raise AssertionError("качать нечего — картинки ещё не было")


def _client_returning(body: bytes):
    class Client:
        def __init__(self, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def get(self, url):
            return SimpleNamespace(content=body, raise_for_status=lambda: None)

    return Client


class _broken_client:
    def __init__(self, **kwargs):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def get(self, url):
        raise RuntimeError("connection reset")


# ------------------------------- [C] кнопки и промпты на языке человека ---

MEDIA_KEYS = (
    [f"media_doc_{key}" for key in media.DOC_ACTION_KEYS]
    + [f"media_doc_{key}_prompt" for key in media.DOC_ACTION_KEYS]
    + [f"media_photo_{key}" for key in media.PHOTO_ACTION_KEYS]
    + [f"media_photo_{key}_prompt" for key in media.PHOTO_ACTION_KEYS
       if key not in media.PHOTO_WIZARD_KEYS]
    + ["media_doc_ask_btn", "media_attachment_gone"]
)


class TestLocalisedActions:
    @pytest.mark.parametrize("lang", ["ru", "en", "kg"])
    @pytest.mark.parametrize("key", MEDIA_KEYS)
    def test_every_language_has_the_text(self, lang, key):
        assert TEXTS[lang].get(key), f"нет перевода {key} на {lang}"

    @pytest.mark.parametrize("key", MEDIA_KEYS)
    def test_screen_keys_do_not_shadow_common_ones(self, key):
        """register_texts игнорирует общие ключи — экран остался бы без текста."""
        assert key not in BASE_KEYS

    def test_translate_prompt_follows_the_language(self):
        """Промпт уходит в модель: англичанину переводили документ на русский."""
        assert "русский" in media.doc_prompt("ru", "tr")
        assert "English" in media.doc_prompt("en", "tr")
        assert "русский" not in media.doc_prompt("en", "tr")
        assert "кыргыз" in media.doc_prompt("kg", "tr")

    def test_doc_buttons_are_translated(self):
        labels = [b.text for row in media._doc_keyboard("en").inline_keyboard for b in row]

        assert labels == [t("en", f"media_doc_{key}") for key in media.DOC_ACTION_KEYS] \
            + [t("en", "media_doc_ask_btn")]
        assert "💬 Свой вопрос" not in labels

    def test_photo_buttons_are_translated(self):
        labels = [b.text for row in media._photo_keyboard("kg").inline_keyboard for b in row]

        assert labels == [t("kg", f"media_photo_{key}") for key in media.PHOTO_ACTION_KEYS]

    def test_callbacks_did_not_change(self):
        """Кнопки из вчерашних сообщений обязаны остаться рабочими."""
        rows = media._doc_keyboard("ru").inline_keyboard
        data = [b.callback_data for row in rows for b in row]

        assert data == [f"doc:{key}" for key in media.DOC_ACTION_KEYS] + ["doc:ask"]

    async def test_doc_action_sends_prompt_in_user_language(self, media_store, chat):
        media_store.data[(1, "attachment")] = {"type": "document", "text": "text"}

        await media.doc_action(FakeCall("doc:tr"), "tok", "en", state=None)

        assert chat.last["text"] == t("en", "media_doc_tr_prompt")

    async def test_photo_action_sends_prompt_in_user_language(self, media_store, chat):
        media_store.data[(1, "attachment")] = {"type": "image"}

        await media.photo_action(FakeCall("ph:see"), "tok", "kg")

        assert chat.last["text"] == t("kg", "media_photo_see_prompt")

    async def test_wizard_buttons_have_no_prompt(self, media_store, chat):
        """«Отредактировать» и «Видео» уводят в мастера — в чат ничего не уходит."""
        media_store.data[(1, "attachment")] = {"type": "image"}
        assert media.photo_prompt("en", "edit") == ""
        assert media.photo_prompt("en", "video") == ""

        await media.photo_action(FakeCall("ph:unknown"), "tok", "en")

        assert chat.calls == [], "неизвестная кнопка не должна ничего списывать"


# ------------------------------------------- [D] фото в мастерах текста ---

class TestPhotoInWizards:
    @pytest.fixture(autouse=True)
    def _upload_ok(self, monkeypatch):
        async def fake_download(message, file_id, size, lang, **kwargs):
            return b"payload"

        async def fake_upload(message, token, lang, name, content, mime):
            return {"type": "image", "id": 1, "name": name}

        monkeypatch.setattr(media, "download", fake_download)
        monkeypatch.setattr(media, "_upload", fake_upload)

    async def test_photo_is_not_lost_in_a_text_wizard(self, media_store, chat):
        """Мастер правки картинки ждёт ТЕКСТ. Раньше фото в нём исчезало молча."""
        from bot.routers.image import ImageWizard

        state = FakeState(ImageWizard.edit.state)
        message = FakeMessage()

        await media.on_photo(message, "tok", "ru", state=state)

        assert message.texts == [t("ru", "media_step_dropped"), t("ru", "photo_ready")], \
            "фото пропало без ответа"
        assert state.state is None, "ожидание текста надо снять"

    @pytest.mark.parametrize("waiting", ["AccountWizard:support",
                                         "AccountWizard:transfer_amount",
                                         "AccountWizard:link_code",
                                         "StudioWizard:hero_prompt"])
    async def test_dropped_wizard_says_so(self, media_store, waiting):
        """Молча снятое состояние = потерянная заявка в поддержку и платный
        вопрос в чат вместо неё: следующую фразу подхватит общий обработчик."""
        state = FakeState(waiting)
        message = FakeMessage()

        await media.on_photo(message, "tok", "ru", state=state)

        assert message.texts[0] == t("ru", "media_step_dropped")
        assert state.state is None

    @pytest.mark.parametrize("lang", ["ru", "en", "kg"])
    def test_dropped_wizard_text_is_translated(self, lang):
        assert "media_step_dropped" not in BASE_KEYS
        assert TEXTS[lang]["media_step_dropped"] != TEXTS["ru"]["media_step_dropped"] or lang == "ru"

    async def test_photo_is_left_to_wizards_that_wait_for_it(self, media_store):
        from bot.routers.image import ImageWizard
        from bot.routers.studio import StudioWizard
        from bot.routers.video import VideoWizard

        for waiting in (ImageWizard.prompt.state, StudioWizard.hero_photo.state,
                        VideoWizard.prompt.state):
            state = FakeState(waiting)
            message = FakeMessage()

            await media.on_photo(message, "tok", "ru", state=state)

            assert message.texts == [], f"{waiting} разбирает фото сам"
            assert state.state == waiting, "чужое состояние сбрасывать нельзя"

    async def test_photo_without_any_state_is_handled(self, media_store):
        message = FakeMessage()

        await media.on_photo(message, "tok", "ru", state=FakeState())

        assert message.texts == [t("ru", "photo_ready")]

    async def test_question_about_document_is_cancelled_by_photo(self, media_store):
        """Старое поведение сохраняем: фото вместо вопроса — человек передумал."""
        state = FakeState(media.DocAsk.question.state)
        message = FakeMessage()

        await media.on_photo(message, "tok", "ru", state=state)

        assert state.state is None
        assert message.texts == [t("ru", "photo_ready")]


# ---------------------------------------------- [E] вложение протухло ---

class TestExpiredAttachment:
    async def test_doc_button_explains_the_silence(self, media_store, chat):
        """Через полчаса кнопки под документом просто переставали работать."""
        call = FakeCall("doc:sum")

        await media.doc_action(call, "tok", "ru", state=FakeState())

        assert call.answered, "часики снять надо в любом случае"
        assert call.message.texts == [t("ru", "media_attachment_gone")]
        assert chat.calls == [], "без файла в чат уходить нечему"

    async def test_own_question_button_explains_the_silence(self, media_store):
        state = FakeState()
        call = FakeCall("doc:ask")

        await media.doc_action(call, "tok", "en", state=state)

        assert call.message.texts == [t("en", "media_attachment_gone")]
        assert state.state is None, "ждать вопрос не о чем — файла нет"

    async def test_photo_button_explains_the_silence(self, media_store, chat):
        call = FakeCall("ph:see")

        await media.photo_action(call, "tok", "kg")

        assert call.message.texts == [t("kg", "media_attachment_gone")]
        assert chat.calls == []
