# -*- coding: utf-8 -*-
"""Транспорт: фолбэк без разметки, сторож пауз, сетевые ошибки, блог."""
import httpx
import pytest
from aiogram.exceptions import TelegramBadRequest

from bot.services import api as api_module
from bot.services.api import Api, ApiError
from bot.services.stream import StreamRenderer


@pytest.fixture(autouse=True)
def _settings(monkeypatch):
    from bot.config import settings

    monkeypatch.setattr(settings, "service_secret", "secret-for-tests")
    monkeypatch.setattr(settings, "public_host", "esai.kg")
    return settings


def make_api(handler) -> Api:
    client = Api(base="http://core:8000", host="esai.kg")
    client._client = httpx.AsyncClient(base_url="http://core:8000",
                                       transport=httpx.MockTransport(handler))
    return client


# --------------------------------------------------------------- [A] поток ---

class Recorder:
    def __init__(self):
        self.edits: list[tuple[str, dict]] = []
        self.answers: list[tuple[str, dict]] = []


class FakeMessage:
    """Сообщение Telegram, которое отбивает HTML-разметку.

    Главное здесь — повторить поведение aiogram: отсутствие parse_mode это не
    «без разметки», а Default → глобальный ParseMode.HTML из __main__.py.
    """

    def __init__(self, rec: Recorder, reject_html: bool = True, reject_all: bool = False):
        self.rec = rec
        self.reject_html = reject_html
        self.reject_all = reject_all

    @staticmethod
    def _mode(kwargs: dict):
        return kwargs["parse_mode"] if "parse_mode" in kwargs else "HTML"

    def _check(self, kwargs: dict) -> None:
        if self.reject_all or (self.reject_html and self._mode(kwargs) == "HTML"):
            raise TelegramBadRequest(method=None, message="can't parse entities")

    async def edit_text(self, text, **kwargs):
        self.rec.edits.append((text, kwargs))
        self._check(kwargs)
        return self

    async def answer(self, text, **kwargs):
        self.rec.answers.append((text, kwargs))
        self._check(kwargs)
        return FakeMessage(self.rec, reject_html=False)


class TestPlainFallback:
    @pytest.mark.asyncio
    async def test_replace_fallback_disables_parse_mode(self):
        """Иначе plain-текст с < > уходит в HTML-режиме и падает второй раз."""
        rec = Recorder()
        origin = FakeMessage(rec, reject_html=False)
        renderer = StreamRenderer(origin)
        renderer.live = FakeMessage(rec, reject_html=True)

        result = await renderer.finish("Сравни 1 < 2 и `a<b`")

        assert result is not None
        assert len(rec.edits) == 2, "должна быть вторая попытка без разметки"
        text, kwargs = rec.edits[-1]
        assert kwargs.get("parse_mode", "MISSING") is None
        assert "<" in text and "&lt;" not in text

    @pytest.mark.asyncio
    async def test_send_fallback_disables_parse_mode(self):
        rec = Recorder()
        origin = FakeMessage(rec, reject_html=True)
        renderer = StreamRenderer(origin)
        renderer.live = None  # первая часть уйдёт через answer(), а не edit_text()

        await renderer.finish("1 < 2")

        assert len(rec.answers) == 2
        assert rec.answers[-1][1].get("parse_mode", "MISSING") is None

    @pytest.mark.asyncio
    async def test_finish_survives_total_failure(self):
        """Кредиты уже списаны — исключение из finish() наврало бы человеку."""
        rec = Recorder()
        origin = FakeMessage(rec, reject_all=True)
        renderer = StreamRenderer(origin)
        renderer.live = FakeMessage(rec, reject_all=True)

        result = await renderer.finish("любой ответ")

        assert result is None
        assert rec.answers, "должна остаться попытка отправить хоть что-то"
        assert rec.answers[-1][1].get("parse_mode", "MISSING") is None

    @pytest.mark.asyncio
    async def test_finish_truncates_last_resort(self):
        rec = Recorder()
        origin = FakeMessage(rec, reject_html=True)
        renderer = StreamRenderer(origin)
        renderer.live = FakeMessage(rec, reject_all=True)

        await renderer.finish("Ответ")

        assert all(len(text) <= 4096 for text, _ in rec.answers + rec.edits)


# ------------------------------------------------------- [B] сторож пауз ---

class TestStreamTimeout:
    def test_read_timeout_is_silence_limit(self):
        """read в httpx = пауза между чтениями: с None зависший core никто не рвёт."""
        assert api_module.STREAM_TIMEOUT.read is not None
        assert api_module.STREAM_TIMEOUT.read == api_module.STREAM_SILENCE_LIMIT
        assert api_module.STREAM_TIMEOUT.connect == 5.0


# --------------------------------------------- [C] сетевые ошибки → ApiError ---

def _raiser(exc: Exception):
    def handler(request: httpx.Request) -> httpx.Response:
        raise exc

    return handler


class TestTransportErrors:
    @pytest.mark.asyncio
    async def test_request_connect_error(self):
        api = make_api(_raiser(httpx.ConnectError("core перезапускается")))
        with pytest.raises(ApiError) as info:
            await api.balance("token")
        assert info.value.status == 503
        assert info.value.code == "transport"
        assert "core" in info.value.message
        await api.aclose()

    @pytest.mark.asyncio
    async def test_request_read_timeout(self):
        api = make_api(_raiser(httpx.ReadTimeout("молчит")))
        with pytest.raises(ApiError) as info:
            await api.balance("token")
        assert info.value.status == 504
        assert info.value.code == "stream_timeout"
        await api.aclose()

    @pytest.mark.asyncio
    async def test_stream_connect_error(self):
        api = make_api(_raiser(httpx.ConnectError("нет связи")))
        with pytest.raises(ApiError) as info:
            async for _ in api.chat_stream("token", {"message": "привет"}):
                pass
        assert info.value.status == 503
        assert info.value.code == "transport"
        await api.aclose()

    @pytest.mark.asyncio
    async def test_stream_read_timeout(self):
        api = make_api(_raiser(httpx.ReadTimeout("нет кадров")))
        with pytest.raises(ApiError) as info:
            async for _ in api.chat_stream("token", {"message": "привет"}):
                pass
        assert info.value.status == 504
        assert info.value.code == "stream_timeout"
        await api.aclose()

    @pytest.mark.asyncio
    async def test_stream_broken_mid_flight(self):
        """Обрыв уже начавшегося потока: половина ответа есть, дальше тишина."""

        async def body():
            yield 'data: {"delta": "прив"}\n\n'.encode()
            raise httpx.RemoteProtocolError("поток оборван")

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, headers={"content-type": "text/event-stream"},
                                  content=body())

        api = make_api(handler)
        seen = []
        with pytest.raises(ApiError) as info:
            async for frame in api.chat_stream("token", {"message": "привет"}):
                seen.append(frame)
        assert seen == [{"delta": "прив"}]
        assert info.value.status == 503
        assert info.value.code == "transport"
        await api.aclose()

    @pytest.mark.asyncio
    async def test_chat_router_shows_server_down(self):
        """Повторяем условие chat.py: обе ошибки должны попасть в «сервер недоступен»."""
        for exc, expect in ((httpx.ConnectError("x"), 503), (httpx.ReadTimeout("x"), 504)):
            api = make_api(_raiser(exc))
            with pytest.raises(ApiError) as info:
                async for _ in api.chat_stream("token", {"message": "?"}):
                    pass
            error = info.value
            assert error.status == expect
            assert error.status >= 500 or error.code == "stream_timeout"
            assert not error.is_paywall
            await api.aclose()


# ------------------------------------------------------------- [D] блог ---

ARTICLES = [
    {"id": 1, "slug": "pro-esai", "title_ru": "Про EsAI", "title_en": "About EsAI",
     "title_kg": "EsAI жөнүндө", "excerpt": "анонс"},
    {"id": 2, "slug": "", "title_ru": "Без адреса"},          # ссылку не собрать
    {"id": 3, "slug": "empty", "title_ru": "", "title_en": ""},  # показывать нечего
    "мусор",                                                   # не словарь
    {"id": 4, "slug": "vtoraya", "title_ru": "Вторая", "title_en": "Second",
     "title_kg": "Экинчи"},
]


class TestBlog:
    @pytest.mark.asyncio
    async def test_uses_articles_endpoint_and_contract(self):
        seen = {}

        def handler(request: httpx.Request) -> httpx.Response:
            seen["path"] = request.url.path
            return httpx.Response(200, json=ARTICLES)

        api = make_api(handler)
        items = await api.blog("ru")

        assert seen["path"] == "/api/content/articles/", "у /blog/ нет slug"
        assert [i["slug"] for i in items] == ["pro-esai", "vtoraya"]
        assert [i["title"] for i in items] == ["Про EsAI", "Вторая"]
        assert all(i["slug"] and i["title"] for i in items)
        await api.aclose()

    @pytest.mark.asyncio
    async def test_title_follows_language(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json=ARTICLES)

        api = make_api(handler)
        assert [i["title"] for i in await api.blog("en")] == ["About EsAI", "Second"]
        assert [i["title"] for i in await api.blog("kg")] == ["EsAI жөнүндө", "Экинчи"]
        await api.aclose()

    @pytest.mark.asyncio
    async def test_paginated_answer(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"count": 1, "results": ARTICLES[:1]})

        api = make_api(handler)
        items = await api.blog("ru")
        assert len(items) == 1 and items[0]["slug"] == "pro-esai"
        assert items[0]["excerpt"] == "анонс", "остальные поля должны доезжать"
        await api.aclose()

    @pytest.mark.asyncio
    async def test_empty_answer(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json=[])

        api = make_api(handler)
        assert await api.blog("ru") == []
        await api.aclose()
