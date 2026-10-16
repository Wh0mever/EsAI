# -*- coding: utf-8 -*-
"""«Снять» у готовой сцены (Build C, ревью C_R1_money_r1).

Кнопка «🎬 Снять сцену (35 кр)» живёт в старом меню днями. Нажали её после того,
как сцена снялась, — бот отвечал «Снимаю…», сервер переснимал готовую сцену и
списывал ещё раз (у готовой сцены есть кадр, «Снять» стоит только видео — меньше
цены на кнопке, сверка цены не спасала). Теперь сервер отвечает 409 already_shot,
а бот показывает готовую сцену с кнопками пересъёмки и их ценами.
"""
import pytest

import bot.routers.studio as studio
from bot.services.api import ApiError
from bot.texts import TEXTS, t
from tests.test_c_bot_dock import SHOT, dock_project, dock_scene
from tests.test_c_fix_quote import QuoteApi, _callbacks
from tests.test_r2_studio import FakeCall, FakeMessage, FakeStore

ALREADY_SHOT = "Сцена уже снята — переснять можно кнопкой «Переснять»"


def already_shot(scene_id: int, credits: int = 35, render: int = 28) -> ApiError:
    """Ответ сервера: сцена уже снята, ничего не снято и не списано; сцена — в теле."""
    return ApiError(409, code="already_shot", message=ALREADY_SHOT,
                    payload={"detail": ALREADY_SHOT, "error_code": "already_shot",
                             "scene": dock_scene(scene_id, "ready", credits=credits, render=render)})


@pytest.fixture
def wire(monkeypatch):
    def _wire(api_data: dict | None = None):
        fake, store = QuoteApi(**(api_data or {})), FakeStore({"st_project": 1})
        monkeypatch.setattr(studio, "api", fake)
        monkeypatch.setattr(studio, "store", store)
        return fake

    return _wire


class TestRender:
    @pytest.mark.parametrize("lang", ["ru", "en", "kg"])
    async def test_old_menu_button_on_ready_scene_shows_the_menu(self, wire, lang):
        fake = wire({"render_error": already_shot(10, credits=35, render=28)})
        call = FakeCall("st:r:10:35", FakeMessage())
        await studio.render(call, "tok", lang)
        assert fake.quotes == [(10, 35)]
        texts = call.message.texts
        assert t(lang, "st_already_shot", title="Сцена") in texts
        assert t(lang, "st_rendering", title="Сцена") not in texts
        assert t(lang, "failed") not in texts
        # Меню готовой сцены: «Снять» нет, пересъёмка — с ценами на сейчас.
        data = _callbacks(call.message)
        assert not [d for d in data if d.startswith("st:r:")]
        assert {f"st:rt:10:0:28:r{SHOT}", f"st:rt:10:1:35:r{SHOT}"} <= set(data)

    async def test_old_priceless_button_on_ready_scene_does_not_shoot(self, wire):
        fake = wire({"project": dock_project([dock_scene(10, "ready", credits=35, render=28)])})
        call = FakeCall("st:r:10", FakeMessage())
        await studio.render(call, "tok", "ru")
        assert fake.quotes == []
        assert t("ru", "st_already_shot", title="Сцена") in call.message.texts
        assert f"st:rt:10:0:28:r{SHOT}" in _callbacks(call.message)

    async def test_title_is_escaped(self, wire):
        error = already_shot(10)
        error.payload["scene"]["preset"]["title"] = "<b>Лес</b>"
        wire({"render_error": error})
        call = FakeCall("st:r:10:35", FakeMessage())
        await studio.render(call, "tok", "ru")
        assert t("ru", "st_already_shot", title="&lt;b&gt;Лес&lt;/b&gt;") in call.message.texts


class TestRetry:
    async def test_already_shot_from_retry_shows_the_menu(self, wire):
        fake = wire({"project": dock_project([dock_scene(10, "failed")]),
                     "patch_error": already_shot(10)})
        call = FakeCall("st:rt:10:0:28:f", FakeMessage())
        await studio.retry_scene(call, "tok", "ru")
        assert [c[0] for c in fake.calls].count("patch_scene") == 1
        assert t("ru", "st_already_shot", title="Сцена") in call.message.texts
        assert t("ru", "st_rendering", title="Сцена") not in call.message.texts
        assert f"st:rt:10:0:28:r{SHOT}" in _callbacks(call.message)


class TestRenderAll:
    async def test_scene_shot_meanwhile_is_skipped_not_a_failure(self, wire):
        scenes = [dock_scene(10, render=28), dock_scene(11, render=28), dock_scene(12, render=28)]
        fake = wire({"project": dock_project(scenes), "balance": {"balance_tokens": 500},
                     "render_errors": {11: already_shot(11)}})
        call = FakeCall("st:ra:84", FakeMessage())
        await studio.render_all(call, "tok", "ru")
        # 11-ю сняли между ответом и заявкой: её пропускаем, остальные ставим.
        assert fake.quotes == [(10, 28), (11, 28), (12, 28)]
        texts = call.message.texts
        assert t("ru", "st_render_all_done", n=2) in texts
        assert t("ru", "failed") not in texts

    async def test_everything_shot_meanwhile_shows_the_timeline(self, wire):
        scenes = [dock_scene(10, render=28)]
        fake = wire({"project": dock_project(scenes), "balance": {"balance_tokens": 500},
                     "render_errors": {10: already_shot(10)}})
        call = FakeCall("st:ra:28", FakeMessage())
        await studio.render_all(call, "tok", "ru")
        assert fake.quotes == [(10, 28)]
        assert t("ru", "failed") not in call.message.texts
        # Молчать нельзя: лента со статусами вместо «не получилось».
        assert "st:tl" in _callbacks(call.message)

    async def test_refusal_after_a_skip_is_still_reported(self, wire):
        scenes = [dock_scene(10, render=28), dock_scene(11, render=28)]
        wire({"project": dock_project(scenes), "balance": {"balance_tokens": 500},
              "render_errors": {10: already_shot(10), 11: ApiError(502, message="boom")}})
        call = FakeCall("st:ra:56", FakeMessage())
        await studio.render_all(call, "tok", "ru")
        assert t("ru", "failed") in call.message.texts


class TestTexts:
    @pytest.mark.parametrize("lang", ["ru", "en", "kg"])
    def test_translated(self, lang):
        text = t(lang, "st_already_shot", title="Лес")
        assert TEXTS[lang].get("st_already_shot")
        assert "Лес" in text and "{" not in text
