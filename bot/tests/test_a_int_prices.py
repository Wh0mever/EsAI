# -*- coding: utf-8 -*-
"""Цены мультстудии и отказ «цена недоступна» в боте (интеграция «Цены и наценка»).

В режиме цен «наценка» сервер отдаёт у сцены credits: null, если себестоимость
модели неизвестна. Бот не пишет «None кр», не складывает null в сумму и просит
библиотеку в формате текущего мультфильма. Отказ очереди 503 price_unavailable —
своими словами, а не «сервер не отвечает».
"""
import pytest

import bot.routers.studio as studio
from bot.routers import video
from bot.services.api import ApiError, api
from bot.texts import t
from tests.test_r2_studio import FakeApi, FakeCall, FakeMessage, FakeStore, preset, scene
from tests.test_r2_video import FakeMessage as VideoMessage


class AspectApi(FakeApi):
    """Запоминает, в каком формате бот просил библиотеку."""

    async def presets(self, token, aspect_ratio="", **kw):
        self.calls.append(("presets", aspect_ratio))
        return await super().presets(token, **kw)


@pytest.fixture
def wire(monkeypatch):
    def _wire(api_data: dict | None = None, store_values: dict | None = None, api_cls=FakeApi):
        fake, store = api_cls(**(api_data or {})), FakeStore(store_values)
        monkeypatch.setattr(studio, "api", fake)
        monkeypatch.setattr(studio, "store", store)
        return fake, store

    return _wire


def _texts(message) -> str:
    return message.texts + "\n" + "\n".join(b.text for b in message.buttons)


class TestNullScenePrice:
    async def test_library_shows_unavailable_not_none(self, wire):
        data = {"categories": [], "popular": [],
                "presets": [preset(1), dict(preset(2), credits=None, price_unavailable=True)]}
        wire({"presets": data})
        message = FakeMessage()
        await studio.show_scenes(message, "tok", "ru", "all", 0)
        assert "None" not in message.texts
        assert f"Сцена 1 · {t('ru', 'st_cr', n=30)}" in message.texts
        assert f"Сцена 2 · {t('ru', 'st_no_price')}" in message.texts

    async def test_card_shows_unavailable(self, wire):
        data = {"categories": [], "popular": [], "presets": [dict(preset(2), credits=None)]}
        wire({"presets": data})
        call = FakeCall("st:sc:2", FakeMessage())
        await studio.scene_card(call, "tok", "en")
        assert "None" not in call.message.texts
        assert t("en", "st_no_price") in call.message.texts

    async def test_timeline_sum_is_not_a_crash(self, wire):
        """sum() по null падал TypeError — лента не открывалась вовсе."""
        project = {"id": 1, "title": "Мульт", "character": {"name": "Герой"}, "aspect_ratio": "1:1",
                   "scenes": [scene(10, credits=30), scene(11, credits=None)]}
        wire({"project": project}, {"st_project": 1})
        message = FakeMessage()
        await studio.show_timeline(message, "tok", "ru")
        text = _texts(message)
        assert "None" not in text
        assert t("ru", "st_render_all", credits=t("ru", "st_no_price")) in text

    async def test_timeline_sum_when_all_priced(self, wire):
        project = {"id": 1, "title": "Мульт", "character": {"name": "Герой"},
                   "scenes": [scene(10, credits=30), scene(11, credits=40)]}
        wire({"project": project}, {"st_project": 1})
        message = FakeMessage()
        await studio.show_timeline(message, "tok", "ru")
        assert t("ru", "st_render_all", credits=t("ru", "st_cr", n=70)) in _texts(message)
        # Строка сцены в прежнем виде: «… · 30 кр».
        assert "· 30 кр" in message.texts

    async def test_scene_menu_render_button_without_price(self, wire):
        project = {"id": 1, "scenes": [scene(11, credits=None)]}
        wire({"project": project}, {"st_project": 1})
        call = FakeCall("st:s:11", FakeMessage())
        await studio.scene_menu(call, "tok", "kg")
        labels = [b.text for b in call.message.buttons]
        assert t("kg", "st_render", credits=t("kg", "st_no_price")) in labels


class TestLibraryAspect:
    async def test_library_is_priced_in_project_aspect(self, wire):
        fake, store = wire({"project": {"id": 1, "aspect_ratio": "1:1", "scenes": []}},
                           {"st_project": 1}, api_cls=AspectApi)
        await studio.show_timeline(FakeMessage(), "tok", "ru")
        assert store.values["st_aspect"] == "1:1"
        await studio.show_scenes(FakeMessage(), "tok", "ru", "all", 0)
        assert ("presets", "1:1") in fake.calls
        # Свой кэш на каждый формат: 16:9-цены не подменяют 1:1.
        assert "st_presets:1:1" in store.values and "st_presets" not in store.values

    async def test_no_project_keeps_plain_request(self, wire):
        fake, store = wire(api_cls=AspectApi)
        await studio.show_scenes(FakeMessage(), "tok", "ru", "all", 0)
        assert ("presets", "") in fake.calls
        assert "st_presets" in store.values

    async def test_api_sends_aspect_only_when_known(self, monkeypatch):
        seen = []

        async def request(method, path, **kw):
            seen.append((path, kw.get("params")))
            return {}

        monkeypatch.setattr(api, "request", request)
        await api.presets("tok", aspect_ratio="9:16", lang="ru")
        await api.presets("tok", lang="ru")
        assert seen == [("/api/cartoon/presets/", {"aspect_ratio": "9:16"}),
                        ("/api/cartoon/presets/", None)]


class TestQueueRefusal:
    async def test_price_unavailable_is_explained(self):
        message = VideoMessage()
        await video._launch_failed(message, "en", ApiError(503, code="price_unavailable"))
        assert [a[0] for a in message.answers] == [t("en", "vid_no_price")]

    async def test_plain_503_is_still_server_down(self):
        message = VideoMessage()
        await video._launch_failed(message, "ru", ApiError(503))
        assert [a[0] for a in message.answers] == [t("ru", "server_down")]
