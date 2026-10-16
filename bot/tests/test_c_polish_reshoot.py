# -*- coding: utf-8 -*-
"""Кнопки пересъёмки из старого меню сцены (Build C, ревью C_R1_money_r2: NB1-R и W9).

Меню сцены в состоянии «ошибка» несёт те же кнопки «🔁 С тем же кадром» / «🆕 Новый
кадр», что и меню готовой сцены. Сцену сняли (здесь же, на сайте, в Mini App) — и
кнопка старого меню «ошибки» переснимала готовый ролик и списывала второй раз. То же с
меню готовой сцены: нажали кнопку, пересняли, нажали ту же кнопку ещё раз — снова
пересъёмка. Теперь хвост кнопки помнит меню: «f» — «ошибка» (expect_status failed),
«r<метка>» — готовая сцена и её ролик (expect_status ready + expect_shot). Не совпало
со сценой сейчас — ничего не снимаем и не списываем, показываем сцену как она есть.
"""
import pytest

import bot.routers.studio as studio
from bot.services.api import ApiError
from bot.texts import TEXTS, t
from tests.test_c_bot_dock import SHOT, dock_project, dock_scene
from tests.test_c_fix_quote import QuoteApi, _callbacks
from tests.test_r2_studio import FakeCall, FakeMessage, FakeStore

ALREADY_SHOT = "Сцена уже снята — переснять можно кнопкой «Переснять»"
CHANGED = "Сцену уже переснимали — проверьте её и нажмите ещё раз"


def refusal(code: str, text: str, scene: dict) -> ApiError:
    return ApiError(409, code=code, message=text, payload={"detail": text, "error_code": code, "scene": scene})


@pytest.fixture
def wire(monkeypatch):
    def _wire(api_data: dict | None = None):
        fake, store = QuoteApi(**(api_data or {})), FakeStore({"st_project": 1})
        monkeypatch.setattr(studio, "api", fake)
        monkeypatch.setattr(studio, "store", store)
        return fake

    return _wire


def patches(fake) -> list[dict]:
    return [c[2] for c in fake.calls if c[0] == "patch_scene"]


def ready(scene_id: int = 10, token: str = SHOT) -> dict:
    scene = dock_scene(scene_id, "ready", credits=35, render=28)
    scene["shot_token"] = token
    return scene


class TestMenuTail:
    async def test_failed_menu_buttons_say_failed(self, wire):
        wire({"project": dock_project([dock_scene(10, "failed", credits=35, render=28)])})
        call = FakeCall("st:s:10", FakeMessage())
        await studio.scene_menu(call, "tok", "ru")
        assert {"st:rt:10:0:28:f", "st:rt:10:1:35:f"} <= set(_callbacks(call.message))

    async def test_ready_menu_buttons_carry_the_shot(self, wire):
        wire({"project": dock_project([ready()])})
        call = FakeCall("st:s:10", FakeMessage())
        await studio.scene_menu(call, "tok", "ru")
        assert {f"st:rt:10:0:28:r{SHOT}", f"st:rt:10:1:35:r{SHOT}"} <= set(_callbacks(call.message))

    def test_longest_callback_fits_telegram(self):
        scene = ready(2147483647, "f" * 16)
        scene["render_credits"], scene["preset"]["credits"] = 99999, 99999
        data = f"st:rt:{scene['id']}:1:{studio._price_tag(99999)}:{studio._menu_state(scene)}"
        assert len(data.encode()) <= 64

    # «r» без метки — меню готовой сцены без ролика: кнопка устарела, а не «ready» (C_POLISH3, N2).
    @pytest.mark.parametrize("part,seen", [
        (None, (None, "")), ("", (None, "")), ("f", ("failed", "")), ("r", (None, "")),
        (f"r{SHOT}", ("ready", SHOT)), ("x", (None, "")), ("fz", (None, "")),
        ("r" + "a" * 17, (None, "")), ("rab-cd", (None, "")), ("rаб", (None, "")),
    ])
    def test_tail_parsing(self, part, seen):
        assert studio._menu_seen(part) == seen

    def test_server_token_is_sanitised(self):
        assert studio._menu_state(ready(token="<b>")) == "r"
        assert studio._menu_state(ready(token="")) == "r"
        assert studio._menu_state(dock_scene(10, "failed")) == "f"


class TestFailedMenu:
    """NB1-R: меню «ошибки», а сцену с тех пор сняли."""

    @pytest.mark.parametrize("data", ["st:rt:10:0:28:f", "st:rt:10:1:35:f"])
    @pytest.mark.parametrize("lang", ["ru", "en", "kg"])
    async def test_scene_shot_since_is_not_reshot(self, wire, data, lang):
        fake = wire({"project": dock_project([ready()])})
        call = FakeCall(data, FakeMessage())
        await studio.retry_scene(call, "tok", lang)
        assert patches(fake) == []
        texts = call.message.texts
        assert t(lang, "st_already_shot", title="Сцена") in texts
        assert t(lang, "st_rendering", title="Сцена") not in texts
        # Меню готовой сцены — уже со своим хвостом.
        assert f"st:rt:10:0:28:r{SHOT}" in _callbacks(call.message)

    async def test_still_failed_reshoots_with_expect_status(self, wire):
        fake = wire({"project": dock_project([dock_scene(10, "failed", credits=35, render=28)])})
        call = FakeCall("st:rt:10:0:28:f", FakeMessage())
        await studio.retry_scene(call, "tok", "ru")
        assert patches(fake) == [{"retry": True, "new_keyframe": False, "quoted_credits": 28,
                                  "expect_status": "failed"}]
        assert t("ru", "st_rendering", title="Сцена") in call.message.texts

    async def test_server_refusal_shows_the_ready_scene(self, wire):
        """Сцену сняли между чтением и заявкой: отказ сервера — та же реакция."""
        fake = wire({"project": dock_project([dock_scene(10, "failed")]),
                     "patch_error": refusal("already_shot", ALREADY_SHOT, ready())})
        call = FakeCall("st:rt:10:0:28:f", FakeMessage())
        await studio.retry_scene(call, "tok", "ru")
        assert len(patches(fake)) == 1
        assert t("ru", "st_already_shot", title="Сцена") in call.message.texts
        assert t("ru", "st_rendering", title="Сцена") not in call.message.texts


class TestReadyMenu:
    """W9: меню готовой сцены, кнопку нажали, пересняли — та же кнопка ещё раз."""

    async def test_same_shot_reshoots_with_the_token(self, wire):
        fake = wire({"project": dock_project([ready()])})
        call = FakeCall(f"st:rt:10:1:35:r{SHOT}", FakeMessage())
        await studio.retry_scene(call, "tok", "ru")
        assert patches(fake) == [{"retry": True, "new_keyframe": True, "quoted_credits": 35,
                                  "expect_status": "ready", "expect_shot": SHOT}]

    @pytest.mark.parametrize("lang", ["ru", "en", "kg"])
    async def test_reshot_since_is_not_reshot_again(self, wire, lang):
        fake = wire({"project": dock_project([ready(token="0badc0de")])})
        call = FakeCall(f"st:rt:10:0:28:r{SHOT}", FakeMessage())
        await studio.retry_scene(call, "tok", lang)
        assert patches(fake) == []
        assert t(lang, "st_already_shot", title="Сцена") in call.message.texts
        assert t(lang, "st_rendering", title="Сцена") not in call.message.texts
        # Новое меню — с меткой нового ролика.
        assert "st:rt:10:0:28:r0badc0de" in _callbacks(call.message)

    async def test_reshoot_failed_since_shows_the_menu(self, wire):
        fake = wire({"project": dock_project([dock_scene(10, "failed", credits=35, render=28)])})
        call = FakeCall(f"st:rt:10:0:28:r{SHOT}", FakeMessage())
        await studio.retry_scene(call, "tok", "en")
        assert patches(fake) == []
        assert t("en", "st_menu_stale", title="Сцена") in call.message.texts
        assert "st:rt:10:0:28:f" in _callbacks(call.message)

    async def test_reshooting_now(self, wire):
        fake = wire({"project": dock_project([dock_scene(10, "video")])})
        call = FakeCall(f"st:rt:10:0:28:r{SHOT}", FakeMessage())
        await studio.retry_scene(call, "tok", "ru")
        assert patches(fake) == []
        assert t("ru", "st_already_rendering", title="Сцена") in call.message.texts

    @pytest.mark.parametrize("scene,key", [(ready(token="0badc0de"), "st_already_shot"),
                                           (dock_scene(10, "failed"), "st_menu_stale"),
                                           (dock_scene(10, "new"), "st_already_rendering")])
    async def test_server_refusals(self, wire, scene, key):
        """Проверка у сервера атомарна (expect_shot): его отказ — та же реакция."""
        code, text = ("already_shot", ALREADY_SHOT) if scene["status"] == "ready" else ("scene_changed", CHANGED)
        fake = wire({"project": dock_project([ready()]), "patch_error": refusal(code, text, scene)})
        call = FakeCall(f"st:rt:10:0:28:r{SHOT}", FakeMessage())
        await studio.retry_scene(call, "tok", "ru")
        assert len(patches(fake)) == 1
        assert t("ru", key, title="Сцена") in call.message.texts
        assert t("ru", "st_rendering", title="Сцена") not in call.message.texts

    async def test_scene_not_loaded_leaves_the_check_to_the_server(self, wire):
        fake = wire({})
        call = FakeCall(f"st:rt:10:0:28:r{SHOT}", FakeMessage())
        await studio.retry_scene(call, "tok", "ru")
        assert patches(fake) == [{"retry": True, "new_keyframe": False, "quoted_credits": 28,
                                  "expect_status": "ready", "expect_shot": SHOT}]


class TestButtonsWithoutTail:
    """Кнопка с ценой, но без хвоста меню — из сборки до этой правки: вслепую не снимает."""

    async def test_on_ready_scene_says_already_shot(self, wire):
        fake = wire({"project": dock_project([ready()])})
        call = FakeCall("st:rt:10:0:28", FakeMessage())
        await studio.retry_scene(call, "tok", "ru")
        assert patches(fake) == []
        assert t("ru", "st_already_shot", title="Сцена") in call.message.texts

    async def test_on_failed_scene_shows_the_menu(self, wire):
        fake = wire({"project": dock_project([dock_scene(10, "failed", credits=35, render=28)])})
        call = FakeCall("st:rt:10:1:35", FakeMessage())
        await studio.retry_scene(call, "tok", "ru")
        assert patches(fake) == []
        assert t("ru", "st_price_check") in call.message.texts
        assert "st:rt:10:1:35:f" in _callbacks(call.message)


class TestTexts:
    @pytest.mark.parametrize("lang", ["ru", "en", "kg"])
    def test_translated(self, lang):
        text = t(lang, "st_menu_stale", title="Лес")
        assert TEXTS[lang].get("st_menu_stale")
        assert "Лес" in text and "{" not in text
