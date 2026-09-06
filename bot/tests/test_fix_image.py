# -*- coding: utf-8 -*-
"""Мастер картинок: чужой текст в карточке, честная цена, кнопки под результатом,
отказ API и проверка зрения перед платным «редактированием»."""
from types import SimpleNamespace

import pytest
from aiogram.exceptions import TelegramBadRequest

import bot.routers.image as image
import bot.routers.models as models_router
from bot.services.api import ApiError
from bot.texts import TEXTS, t

NANO_ID = "google/gemini-2.5-flash-image"
FLUX_ID = "black-forest-labs/flux.2-pro"

NANO = {"category": "image", "openrouter_id": NANO_ID, "name": "Nano <Banana>",
        "markup_coefficient": 4, "supports_vision": True}
FLUX = {"category": "image", "openrouter_id": FLUX_ID, "name": "FLUX.2 Pro",
        "markup_coefficient": 4, "supports_vision": False}


class FakeStore:
    """Redis мастера в памяти: ключи те же, поведение то же."""

    def __init__(self):
        self.data = {}

    async def get(self, telegram_id, key, default=None):
        return self.data.get((telegram_id, key), default)

    async def set(self, telegram_id, key, value, ttl=None):
        self.data[(telegram_id, key)] = value

    async def drop(self, telegram_id, key):
        self.data.pop((telegram_id, key), None)


class FakeMessage:
    def __init__(self, chat_id: int = 1, text: str = "", reject_html: bool = False):
        self.chat = SimpleNamespace(id=chat_id)
        self.text = text
        self.caption = ""
        self.sent: list = []
        self.edited: list = []
        self._reject_html = reject_html

    async def answer(self, text, **kwargs):
        if self._reject_html and kwargs.get("parse_mode") == "HTML":
            raise TelegramBadRequest(method=None, message="can't parse entities")
        self.sent.append((text, kwargs))
        return self

    async def edit_text(self, text, **kwargs):
        self.edited.append((text, kwargs))
        return self

    @property
    def last_text(self) -> str:
        return self.sent[-1][0] if self.sent else ""


class FakeCall:
    def __init__(self, data: str, message: FakeMessage):
        self.data = data
        self.message = message
        self.answers: list = []

    async def answer(self, text: str = "", **kwargs):
        self.answers.append(text)

    @property
    def answered(self) -> bool:
        return bool(self.answers)


class FakeState:
    def __init__(self, data: dict | None = None):
        self._data = data or {}
        self.cleared = False

    async def get_data(self):
        return dict(self._data)

    async def clear(self):
        self.cleared = True

    async def set_state(self, state):
        self._state = state

    async def update_data(self, **kwargs):
        self._data.update(kwargs)


@pytest.fixture
def store(monkeypatch):
    fake = FakeStore()
    monkeypatch.setattr(image, "store", fake)
    return fake


@pytest.fixture
def catalog(monkeypatch):
    """Список моделей мастера; тест кладёт в него то, что нужно."""
    box = {"models": [NANO, FLUX], "error": None}

    async def fake_fetch(token, lang, telegram_id):
        if box["error"] is not None:
            raise box["error"]
        return box["models"]

    monkeypatch.setattr(image, "_fetch", fake_fetch)
    monkeypatch.setattr(image, "api", SimpleNamespace(
        balance=lambda *a, **kw: _balance()))
    return box


async def _balance():
    return {"balance_tokens": 120}


@pytest.fixture
def generated(monkeypatch):
    """Перехват генерации: тест видит, за что и по какой модели платили бы."""
    calls: list = []

    async def fake_generate(message, token, lang, draft):
        calls.append(draft)

    monkeypatch.setattr(image, "_generate", fake_generate)
    return calls


class TestCardEscaping:
    """[A] «<» в промпте ломал карточку целиком."""

    async def test_prompt_and_model_are_escaped(self, store, catalog):
        message = FakeMessage()
        await image._show_card(message, "tok", "ru", 1,
                               {"prompt": "<b>кот</b> & пёс", "model": NANO_ID})
        text, kwargs = message.sent[-1]
        assert kwargs["parse_mode"] == "HTML"
        assert "&lt;b&gt;кот" in text and "<b>кот" not in text
        assert "&amp;" in text
        # Имя модели тоже приходит с сервера и тоже может содержать «<».
        assert "Nano &lt;Banana&gt;" in text

    async def test_falls_back_to_plain_text(self, store, catalog):
        """Если Telegram всё равно отверг разметку — карточка важнее оформления."""
        message = FakeMessage(reject_html=True)
        await image._show_card(message, "tok", "ru", 1, {"prompt": "кот", "model": NANO_ID})
        text, kwargs = message.sent[-1]
        # Именно явный None: у бота глобальный parse_mode=HTML, и без него
        # aiogram подставит HTML заново — сырые «<» упадут второй раз.
        assert "parse_mode" in kwargs and kwargs["parse_mode"] is None
        assert "<b>" not in text and "кот" in text
        assert kwargs["reply_markup"] is not None


class TestPrice:
    """[B] Цена картинки = то, что реально спишет бэкенд."""

    def test_flux_is_flat_coefficient(self):
        assert models_router.image_credits(FLUX) == 4
        assert models_router.is_flux_image_model("black-forest-labs/flux.2-max")
        assert models_router.is_flux_image_model("something/flux.2-pro:free")

    def test_token_billed_model_costs_more_than_coefficient(self):
        # ceil(1450 * 4 / 1000) = 6 — как core/plans/credit_value._image_credits.
        assert models_router.image_credits(NANO) == 6
        assert not models_router.is_flux_image_model(NANO_ID)

    def test_credits_never_below_one(self):
        assert models_router.image_credits({"openrouter_id": NANO_ID,
                                            "markup_coefficient": 0.1}) == 1
        assert models_router.image_credits({"openrouter_id": FLUX_ID,
                                            "markup_coefficient": 0.5}) == 1

    def test_no_coefficient_no_price(self):
        assert models_router.image_credits({"openrouter_id": NANO_ID}) is None
        assert models_router._price({"category": "image"}) == ""

    def test_price_labels(self):
        assert models_router._price(FLUX) == "4 кр"
        assert models_router._price(NANO) == "≈6 кр"

    def test_wizard_and_catalog_use_one_function(self):
        assert image._price is models_router._price

    async def test_card_shows_charged_price(self, store, catalog):
        message = FakeMessage()
        await image._show_card(message, "tok", "ru", 1, {"prompt": "кот", "model": NANO_ID})
        assert "≈6 кр" in message.last_text


class TestRedraw:
    """[C] «Другие пропорции» под готовой картинкой должны рисовать заново."""

    def test_result_menu_has_its_own_prefix(self, store):
        # Кнопки карточки мастера остаются на i:ar: — они только меняют карточку.
        card = [b.callback_data for row in image._card_keyboard("ru", "1:1").inline_keyboard
                for b in row]
        assert any(d.startswith("i:ar:") for d in card)

    async def test_ratio_under_result_regenerates_last(self, store, generated):
        store.data[(1, "img_draft")] = {"prompt": "старый черновик", "ar": "1:1"}
        store.data[(1, "img_last")] = {"prompt": "кот в шляпе", "model": NANO_ID, "ar": "1:1"}
        call = FakeCall("i:rar:16:9", FakeMessage())
        await image.redraw_ratio(call, "tok", "ru")
        assert call.answered
        assert generated == [{"prompt": "кот в шляпе", "model": NANO_ID,
                              "ar": "16:9", "attachment": None}]

    async def test_ratio_menu_buttons_point_to_redraw(self, store):
        message = FakeMessage()
        await image.pick_ar_again(FakeCall("i:pickar", message), "ru")
        markup = message.sent[-1][1]["reply_markup"]
        data = [b.callback_data for row in markup.inline_keyboard for b in row]
        assert data and all(d.startswith("i:rar:") for d in data)
        assert all(len(d.encode()) <= 64 for d in data)

    async def test_draft_dies_after_generation(self, store, catalog, monkeypatch):
        async def fake_run_chat(message, token, lang, text, **kwargs):
            return {"message": {"attachments": [{"type": "image", "url": "/media/a.png"}]}}

        monkeypatch.setattr(image, "run_chat", fake_run_chat)
        store.data[(1, "img_draft")] = {"prompt": "кот", "ar": "1:1"}
        await image._generate(FakeMessage(), "tok", "ru", {"prompt": "кот", "ar": "1:1"})
        assert (1, "img_draft") not in store.data
        assert store.data[(1, "img_last")]["prompt"] == "кот"

    async def test_draft_survives_failed_generation(self, store, monkeypatch):
        """Отказ (пейвол/сбой) — черновик нужен, чтобы повторить без набора заново."""
        async def fake_run_chat(message, token, lang, text, **kwargs):
            return None

        monkeypatch.setattr(image, "run_chat", fake_run_chat)
        store.data[(1, "img_draft")] = {"prompt": "кот", "ar": "1:1"}
        await image._generate(FakeMessage(), "tok", "ru", {"prompt": "кот", "ar": "1:1"})
        assert (1, "img_draft") in store.data

    async def test_card_ratio_never_charges(self, store, catalog, generated):
        """Кнопка пропорций на КАРТОЧКЕ не должна списывать кредиты сама по себе."""
        store.data[(1, "img_last")] = {"prompt": "кот", "model": NANO_ID}
        call = FakeCall("i:ar:9:16", FakeMessage())
        await image.pick_ratio(call, "tok", "ru")
        assert generated == []
        assert store.data[(1, "img_draft")]["ar"] == "9:16"


class TestApiFailure:
    """[D] 429/401/5xx в мастере — человек должен получить ответ."""

    async def test_card_reports_server_down(self, store, catalog):
        catalog["error"] = ApiError(429, code="throttled")
        message = FakeMessage()
        await image._show_card(message, "tok", "ru", 1, {"prompt": "кот"})
        assert message.last_text == t("ru", "server_down")

    async def test_model_menu_answers_callback_first(self, store, catalog):
        catalog["error"] = ApiError(500)
        message = FakeMessage()
        call = FakeCall("i:models", message)
        await image.pick_model_menu(call, "tok", "ru")
        assert call.answered, "callback без ответа — у человека вечные часики"
        assert message.last_text == t("ru", "server_down")

    async def test_model_pick_reports_server_down(self, store, catalog):
        catalog["error"] = ApiError(401)
        message = FakeMessage()
        call = FakeCall("i:m:0", message)
        await image.pick_model(call, "tok", "ru")
        assert call.answered and message.last_text == t("ru", "server_down")

    async def test_empty_catalog_still_speaks(self, store, catalog):
        catalog["models"] = []
        message = FakeMessage()
        await image._show_card(message, "tok", "ru", 1, {"prompt": "кот"})
        assert message.last_text == t("ru", "img_no_models")


class TestVisionBeforeEdit:
    """[E] Без supports_vision «редактирование» — это платная новая картинка."""

    def test_no_vision_model_at_all(self):
        assert image._vision_model([FLUX]) is None

    def test_prefers_default_editor(self):
        other = {"openrouter_id": "some/other-image", "supports_vision": True,
                 "category": "image"}
        assert image._vision_model([other, NANO])["openrouter_id"] == NANO_ID

    def test_locked_is_last_resort(self):
        locked = {**NANO, "locked": True}
        seeing = {"openrouter_id": "some/other-image", "supports_vision": True}
        assert image._vision_model([locked, seeing])["openrouter_id"] == "some/other-image"
        assert image._vision_model([locked])["openrouter_id"] == NANO_ID

    async def test_edit_without_vision_does_not_charge(self, store, catalog, generated):
        catalog["models"] = [FLUX]  # ни одна image-модель не видит картинку
        message = FakeMessage(text="убери фон")
        state = FakeState({"attachment": {"type": "image", "url": "/media/a.png"}})
        await image.got_edit_prompt(message, "tok", "ru", state)
        assert generated == [], "запустили платную генерацию вместо отказа"
        assert message.last_text == t("ru", "img_no_vision")

    async def test_edit_uses_seeing_model(self, store, catalog, generated):
        message = FakeMessage(text="добавь снег")
        state = FakeState({"attachment": {"type": "image", "url": "/media/a.png"}})
        await image.got_edit_prompt(message, "tok", "ru", state)
        assert generated[-1]["model"] == NANO_ID
        assert generated[-1]["attachment"]["url"] == "/media/a.png"

    @pytest.mark.parametrize("lang", ["ru", "en", "kg"])
    def test_refusal_is_translated(self, lang):
        assert TEXTS[lang].get("img_no_vision"), f"нет перевода img_no_vision для {lang}"
        assert t(lang, "img_no_vision") != t("ru", "img_no_vision") or lang == "ru"
