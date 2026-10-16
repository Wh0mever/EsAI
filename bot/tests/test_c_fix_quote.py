# -*- coding: utf-8 -*-
"""«Снять» в боте сверяет цену с кнопкой (Build C, ревью C_R1_money B1).

Цена сцены теперь зависит от настроек мультфильма, а их меняют и на сайте;
кнопки в Telegram живут днями. Поэтому цена с кнопки едет в callback_data и
уходит на сервер как quoted_credits: выросла — сервер не снимает (409), бот
называет новую цену и шлёт меню сцены заново. Кнопка без цены (старая) не
снимает вслепую, а «Снять все» с устаревшей суммой сперва спрашивает.
"""
import pytest

import bot.routers.studio as studio
from bot.services.api import ApiError, api
from bot.texts import TEXTS, t
from tests.test_c_bot_dock import SHOT, DockApi, dock_project, dock_scene
from tests.test_r2_studio import FakeCall, FakeMessage, FakeStore


def price_changed(scene_id: int, credits: int, status: str = "draft") -> ApiError:
    """Ответ сервера: цена выросла, ничего не снято; новая цена и сцена — в теле."""
    detail = f"Цена изменилась: теперь {credits} кр. Проверьте и нажмите «Снять» ещё раз."
    return ApiError(409, code="price_changed", message=detail,
                    payload={"detail": detail, "error_code": "price_changed", "credits": credits,
                             "scene": dock_scene(scene_id, status, credits=credits, render=credits)})


class QuoteApi(DockApi):
    """Запоминает цену с кнопки; отказ — по id сцены (render_errors)."""

    async def render_scene(self, token, scene_id, quoted_credits=None, **kw):
        self.calls.append(("render_scene", scene_id, quoted_credits))
        error = (self.data.get("render_errors") or {}).get(scene_id) or self.data.get("render_error")
        if error is not None:
            raise error
        return {"id": scene_id, "preset": {"title": "Сцена"}}

    @property
    def quotes(self) -> list[tuple]:
        return [(c[1], c[2]) for c in self.calls if c[0] == "render_scene"]


@pytest.fixture
def wire(monkeypatch):
    def _wire(api_data: dict | None = None, store_values: dict | None = None):
        fake, store = QuoteApi(**(api_data or {})), FakeStore(store_values or {"st_project": 1})
        monkeypatch.setattr(studio, "api", fake)
        monkeypatch.setattr(studio, "store", store)
        return fake, store

    return _wire


def _callbacks(message) -> list[str]:
    return [b.callback_data for b in message.buttons]


# ------------------------------------------------------------ кнопки ---

class TestButtonsCarryThePrice:
    async def test_scene_menu(self, wire):
        wire({"project": dock_project([dock_scene(10, "failed", credits=35, render=28)])})
        call = FakeCall("st:s:10", FakeMessage())
        await studio.scene_menu(call, "tok", "ru")
        data = _callbacks(call.message)
        assert {"st:r:10:28", "st:rt:10:0:28:f", "st:rt:10:1:35:f"} <= set(data)
        assert all(len(d.encode()) <= 64 for d in data)

    async def test_unpriced_scene_has_no_price_in_callback(self, wire):
        wire({"project": dock_project([dock_scene(10, credits=None, render=None)])})
        call = FakeCall("st:s:10", FakeMessage())
        await studio.scene_menu(call, "tok", "ru")
        assert "st:r:10:" in _callbacks(call.message)

    async def test_timeline_render_all(self, wire):
        scenes = [dock_scene(10, render=28), dock_scene(11, "failed", render=35)]
        wire({"project": dock_project(scenes)})
        message = FakeMessage()
        await studio.show_timeline(message, "tok", "ru")
        assert "st:ra:63" in _callbacks(message)

    async def test_timeline_render_all_without_total(self, wire):
        scenes = [dock_scene(10, render=28), dock_scene(11, credits=None, render=None)]
        wire({"project": dock_project(scenes)})
        message = FakeMessage()
        await studio.show_timeline(message, "tok", "ru")
        assert "st:ra" in _callbacks(message)


# ------------------------------------------------------------ «Снять» ---

class TestRender:
    async def test_sends_the_shown_price(self, wire):
        fake, _ = wire()
        call = FakeCall("st:r:10:28", FakeMessage())
        await studio.render(call, "tok", "ru")
        assert fake.quotes == [(10, 28)]
        assert t("ru", "st_rendering", title="Сцена") in call.message.texts

    async def test_price_went_up_shows_new_price_and_menu(self, wire):
        fake, _ = wire({"render_error": price_changed(10, 905)})
        call = FakeCall("st:r:10:35", FakeMessage())
        await studio.render(call, "tok", "en")
        assert fake.quotes == [(10, 35)]
        assert t("en", "st_price_changed", credits=t("en", "st_cr", n=905)) in call.message.texts
        assert t("en", "st_rendering", title="Сцена") not in call.message.texts
        # Меню сцены — с новой ценой на кнопке и в callback_data.
        assert "st:r:10:905" in _callbacks(call.message)
        assert t("en", "st_render", credits=t("en", "st_cr", n=905)) in [b.text for b in call.message.buttons]

    async def test_old_button_without_price_does_not_shoot(self, wire):
        fake, _ = wire({"project": dock_project([dock_scene(10, credits=905, render=905)])})
        call = FakeCall("st:r:10", FakeMessage())
        await studio.render(call, "tok", "ru")
        assert fake.quotes == []
        assert t("ru", "st_price_check") in call.message.texts
        assert "st:r:10:905" in _callbacks(call.message)

    @pytest.mark.parametrize("data", ["st:r:10:", "st:r:10:abc", "st:r:10:-5", "st:r:10:²"])
    async def test_odd_price_is_an_old_button(self, wire, data):
        fake, _ = wire({"project": dock_project([dock_scene(10, render=28)])})
        call = FakeCall(data, FakeMessage())
        await studio.render(call, "tok", "ru")
        assert fake.quotes == []
        assert "st:r:10:28" in _callbacks(call.message)

    async def test_old_button_on_unpriced_scene(self, wire):
        fake, _ = wire({"project": dock_project([dock_scene(10, credits=None, render=None)])})
        call = FakeCall("st:r:10:", FakeMessage())
        await studio.render(call, "tok", "kg")
        assert fake.quotes == []
        assert call.message.texts == t("kg", "st_no_price_render")

    async def test_old_button_on_busy_scene(self, wire):
        fake, _ = wire({"project": dock_project([dock_scene(10, "video")])})
        call = FakeCall("st:r:10", FakeMessage())
        await studio.render(call, "tok", "ru")
        assert fake.quotes == []
        assert t("ru", "st_already_rendering", title="Сцена") in call.message.texts

    async def test_old_button_on_missing_scene(self, wire):
        fake, _ = wire({"project": dock_project([])})
        call = FakeCall("st:r:10", FakeMessage())
        await studio.render(call, "tok", "ru")
        assert fake.quotes == []
        assert call.message.texts == t("ru", "failed")


# ---------------------------------------------------------- «Переснять» ---

class TestRetry:
    @pytest.mark.parametrize("data,new_frame,quoted", [(f"st:rt:10:0:28:r{SHOT}", False, 28),
                                                      (f"st:rt:10:1:35:r{SHOT}", True, 35)])
    async def test_sends_the_shown_price(self, wire, data, new_frame, quoted):
        fake, _ = wire({"project": dock_project([dock_scene(10, "ready")])})
        call = FakeCall(data, FakeMessage())
        await studio.retry_scene(call, "tok", "ru")
        patches = [c[2] for c in fake.calls if c[0] == "patch_scene"]
        # Хвост кнопки — меню готовой сцены и метка её ролика: сервер сверит обе.
        assert patches == [{"retry": True, "new_keyframe": new_frame, "quoted_credits": quoted,
                            "expect_status": "ready", "expect_shot": SHOT}]

    async def test_price_went_up(self, wire):
        fake, _ = wire({"project": dock_project([dock_scene(10, "ready")]),
                        "patch_error": price_changed(10, 128, "ready")})
        call = FakeCall(f"st:rt:10:0:28:r{SHOT}", FakeMessage())
        await studio.retry_scene(call, "tok", "ru")
        assert t("ru", "st_price_changed", credits=t("ru", "st_cr", n=128)) in call.message.texts
        assert t("ru", "st_rendering", title="Сцена") not in call.message.texts
        assert f"st:rt:10:0:128:r{SHOT}" in _callbacks(call.message)

    @pytest.mark.parametrize("data,price", [("st:rt:10:0", 28), ("st:rt:10:1", 35)])
    async def test_old_button_shows_menu(self, wire, data, price):
        fake, _ = wire({"project": dock_project([dock_scene(10, "ready", credits=35, render=28)])})
        call = FakeCall(data, FakeMessage())
        await studio.retry_scene(call, "tok", "ru")
        assert not [c for c in fake.calls if c[0] == "patch_scene"]
        assert t("ru", "st_price_check") in call.message.texts
        assert f"st:rt:10:{data[-1]}:{price}:r{SHOT}" in _callbacks(call.message)


# --------------------------------------------------------- «Снять все» ---

class TestRenderAll:
    SCENES = [dock_scene(10, render=28), dock_scene(11, "failed", render=35)]

    async def test_label_matches(self, wire):
        fake, _ = wire({"project": dock_project(list(self.SCENES)), "balance": {"balance_tokens": 500}})
        call = FakeCall("st:ra:63", FakeMessage())
        await studio.render_all(call, "tok", "ru")
        assert fake.quotes == [(10, 28), (11, 35)]
        assert t("ru", "st_render_all_done", n=2) in call.message.texts

    async def test_cheaper_than_label_renders(self, wire):
        fake, _ = wire({"project": dock_project(list(self.SCENES)), "balance": {"balance_tokens": 500}})
        call = FakeCall("st:ra:90", FakeMessage())
        await studio.render_all(call, "tok", "ru")
        assert fake.quotes == [(10, 28), (11, 35)]

    async def test_total_went_up_asks_first(self, wire):
        fake, _ = wire({"project": dock_project(list(self.SCENES)), "balance": {"balance_tokens": 500}})
        call = FakeCall("st:ra:40", FakeMessage())
        await studio.render_all(call, "tok", "ru")
        assert fake.quotes == []
        assert t("ru", "st_render_all_changed", credits=t("ru", "st_cr", n=63),
                 was=t("ru", "st_cr", n=40)) in call.message.texts
        assert _callbacks(call.message) == ["st:ra:63", "st:tl"]
        # «Да» с новой суммой — снимает.
        confirm = FakeCall("st:ra:63", FakeMessage())
        await studio.render_all(confirm, "tok", "ru")
        assert fake.quotes == [(10, 28), (11, 35)]

    async def test_old_button_without_total_asks(self, wire):
        fake, _ = wire({"project": dock_project(list(self.SCENES)), "balance": {"balance_tokens": 500}})
        call = FakeCall("st:ra", FakeMessage())
        await studio.render_all(call, "tok", "kg")
        assert fake.quotes == []
        assert t("kg", "st_render_all_confirm", credits=t("kg", "st_cr", n=63)) in call.message.texts
        assert t("kg", "st_render_all_ok", credits=t("kg", "st_cr", n=63)) in [b.text for b in call.message.buttons]

    async def test_price_went_up_mid_batch(self, wire):
        scenes = [dock_scene(10, render=28), dock_scene(11, render=28), dock_scene(12, render=28)]
        fake, _ = wire({"project": dock_project(scenes), "balance": {"balance_tokens": 500},
                        "render_errors": {11: price_changed(11, 62)}})
        call = FakeCall("st:ra:84", FakeMessage())
        await studio.render_all(call, "tok", "ru")
        # 11-я подорожала между ответом и заявкой: дальше не ставим.
        assert fake.quotes == [(10, 28), (11, 28)]
        texts = call.message.texts
        assert t("ru", "st_render_all_done", n=1) in texts
        assert t("ru", "st_render_all_stopped") in texts
        assert t("ru", "failed") not in texts
        # Лента с новой суммой на «Снять все».
        assert any(d.startswith("st:ra") for d in _callbacks(call.message))


# --------------------------------------------------------- клиент API ---

class TestApiClient:
    @pytest.fixture
    def seen(self, monkeypatch):
        calls = []

        async def request(method, path, **kw):
            calls.append((method, path, kw.get("json_body")))
            return {}

        monkeypatch.setattr(api, "request", request)
        return calls

    async def test_render_sends_the_quote(self, seen):
        await api.render_scene("tok", 10, quoted_credits=35, lang="ru")
        await api.render_scene("tok", 10, lang="ru")
        assert seen == [("POST", "/api/cartoon/scenes/10/render/", {"quoted_credits": 35}),
                        ("POST", "/api/cartoon/scenes/10/render/", {})]


# --------------------------------------------------------------- тексты ---

class TestTexts:
    @pytest.mark.parametrize("lang", ["ru", "en", "kg"])
    def test_translated(self, lang):
        price, was = t(lang, "st_cr", n=905), t(lang, "st_cr", n=35)
        for key in ("st_price_changed", "st_render_all_confirm", "st_render_all_ok"):
            assert key in TEXTS[lang]
            text = t(lang, key, credits=price)
            assert "905" in text and "{" not in text
        changed = t(lang, "st_render_all_changed", credits=price, was=was)
        assert "905" in changed and "35" in changed and "{" not in changed
        for key in ("st_price_check", "st_render_all_stopped"):
            assert TEXTS[lang].get(key)
