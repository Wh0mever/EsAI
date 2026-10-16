# -*- coding: utf-8 -*-
"""Build C, C_POLISH3 (ревью C_R1_polish): N1 и N2 в боте.

N1. Модель по умолчанию предлагается, но цены у неё нет (режим «наценка», себестоимость
неизвестна): /pricing/ отдавал scene_min 0, и вход в студию писал «сцена — от 0 кр».
Теперь 0, пусто и мусор — «цены нет», и вступление идёт без цены сцены.

N2. Готовая сцена без ролика (её так пометили в админке) даёт меню без метки ролика:
хвост кнопки — голое «r». Без метки сервер не отличит «тот же ролик» от «уже пересняли»,
поэтому такая кнопка ведёт себя как кнопка без цены — никогда не снимает.
"""
import pytest

import bot.routers.studio as studio
from bot.texts import TEXTS, t
from tests.test_c_bot_dock import MINI, dock_project, dock_scene
from tests.test_c_fix_quote import QuoteApi, _callbacks
from tests.test_r2_studio import FakeCall, FakeMessage, FakeStore

UNPRICED_MODELS = {
    "defaults": {"video_model": MINI, "resolution": "480p", "duration": 5, "source": "settings"},
    "models": [{"id": MINI, "price_from": None, "price_unavailable": True}],
}


@pytest.fixture
def wire(monkeypatch):
    def _wire(api_data: dict | None = None, store_values: dict | None = None):
        fake, store = QuoteApi(**(api_data or {})), FakeStore(store_values or {"st_project": 1})
        monkeypatch.setattr(studio, "api", fake)
        monkeypatch.setattr(studio, "store", store)
        return fake

    return _wire


def patches(fake) -> list[dict]:
    return [c[2] for c in fake.calls if c[0] == "patch_scene"]


def ready_without_clip(scene_id: int = 10) -> dict:
    scene = dock_scene(scene_id, "ready", credits=35, render=28)
    scene["shot_token"] = ""
    return scene


# ------------------------------------------------------------------ N1 ---

class TestIntroWithoutScenePrice:
    @pytest.mark.parametrize("scene_min", [0, -5, None, "39", True])
    @pytest.mark.parametrize("lang", ["ru", "en", "kg"])
    async def test_unknown_price_is_not_printed(self, wire, scene_min, lang):
        pricing = {"character": 7} if scene_min is None else {"character": 7, "scene_min": scene_min}
        wire({"models": UNPRICED_MODELS, "pricing": pricing}, {})
        message = FakeMessage()
        await studio.show_intro(message, "tok", lang)
        assert message.sent[0].text == t(lang, "st_intro_no_price", character=7)
        assert t(lang, "st_intro", character=7, scene_min=0) != message.sent[0].text

    async def test_server_fallback_price_is_shown(self, wire):
        """Сервер откатился на пресеты (C_POLISH3): его scene_min > 0 — его и пишем."""
        wire({"models": UNPRICED_MODELS, "pricing": {"character": 7, "scene_min": 39}}, {})
        message = FakeMessage()
        await studio.show_intro(message, "tok", "ru")
        assert message.sent[0].text == t("ru", "st_intro", character=7, scene_min=39)

    async def test_default_model_price_still_wins(self, wire):
        models = {"defaults": UNPRICED_MODELS["defaults"],
                  "models": [{"id": MINI, "price": {"table": {"480p": {"5": 35}}}, "price_from": 35}]}
        wire({"models": models, "pricing": {"character": 7, "scene_min": 0}}, {})
        message = FakeMessage()
        await studio.show_intro(message, "tok", "en")
        assert message.sent[0].text == t("en", "st_intro", character=7, scene_min=35)

    @pytest.mark.parametrize("lang", ["ru", "en", "kg"])
    def test_texts(self, lang):
        text = t(lang, "st_intro_no_price", character=7)
        assert TEXTS[lang].get("st_intro_no_price")
        assert "7" in text and "{" not in text and "0 " not in text


# ------------------------------------------------------------------ N2 ---

class TestReadyMenuWithoutClipMark:
    async def test_menu_tail_is_bare(self, wire):
        wire({"project": dock_project([ready_without_clip()])})
        call = FakeCall("st:s:10", FakeMessage())
        await studio.scene_menu(call, "tok", "ru")
        assert {"st:rt:10:0:28:r", "st:rt:10:1:35:r"} <= set(_callbacks(call.message))

    @pytest.mark.parametrize("data", ["st:rt:10:0:28:r", "st:rt:10:1:35:r"])
    @pytest.mark.parametrize("lang", ["ru", "en", "kg"])
    async def test_still_ready_is_never_reshot(self, wire, data, lang):
        fake = wire({"project": dock_project([ready_without_clip()])})
        call = FakeCall(data, FakeMessage())
        await studio.retry_scene(call, "tok", lang)
        assert patches(fake) == []
        assert t(lang, "st_already_shot", title="Сцена") in call.message.texts
        assert t(lang, "st_rendering", title="Сцена") not in call.message.texts

    async def test_failed_since_shows_todays_menu(self, wire):
        fake = wire({"project": dock_project([dock_scene(10, "failed", credits=35, render=28)])})
        call = FakeCall("st:rt:10:0:28:r", FakeMessage())
        await studio.retry_scene(call, "tok", "ru")
        assert patches(fake) == []
        assert t("ru", "st_price_check") in call.message.texts
        assert "st:rt:10:0:28:f" in _callbacks(call.message)

    async def test_scene_not_loaded_does_not_shoot(self, wire):
        """Сцену не прочитать — без метки проверку серверу не доверить: не снимаем."""
        fake = wire({})
        call = FakeCall("st:rt:10:0:28:r", FakeMessage())
        await studio.retry_scene(call, "tok", "ru")
        assert patches(fake) == []
        assert t("ru", "failed") in call.message.texts

    async def test_with_the_mark_still_reshoots(self, wire):
        """Обычное меню готовой сцены (с меткой) по-прежнему переснимает."""
        scene = ready_without_clip()
        scene["shot_token"] = "0badc0de"
        fake = wire({"project": dock_project([scene])})
        call = FakeCall("st:rt:10:0:28:r0badc0de", FakeMessage())
        await studio.retry_scene(call, "tok", "ru")
        assert patches(fake) == [{"retry": True, "new_keyframe": False, "quoted_credits": 28,
                                  "expect_status": "ready", "expect_shot": "0badc0de"}]
