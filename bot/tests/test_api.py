# -*- coding: utf-8 -*-
"""Клиент API: подпись, заголовки, разбор потока и ошибок."""
import hashlib
import hmac
import json

import httpx
import pytest

from bot.services.api import Api, ApiError

SECRET = "bot-service-secret-for-tests"


@pytest.fixture(autouse=True)
def _settings(monkeypatch):
    from bot.config import settings

    monkeypatch.setattr(settings, "service_secret", SECRET)
    monkeypatch.setattr(settings, "public_host", "esai.kg")
    return settings


def make_api(handler) -> Api:
    client = Api(base="http://core:8000", host="esai.kg")
    client._client = httpx.AsyncClient(base_url="http://core:8000",
                                       transport=httpx.MockTransport(handler))
    return client


def expected_signature(ts: str, nonce: str, method: str, path: str, body: bytes) -> str:
    """Независимый повтор формулы бэкенда — если разойдутся, тест это поймает."""
    digest = hashlib.sha256(body or b"").hexdigest()
    message = "\n".join([ts, nonce, method.upper(), path, digest])
    return hmac.new(SECRET.encode(), message.encode(), hashlib.sha256).hexdigest()


class TestServiceSignature:
    @pytest.mark.asyncio
    async def test_signature_matches_backend_formula(self):
        seen = {}

        def handler(request: httpx.Request) -> httpx.Response:
            seen["request"] = request
            return httpx.Response(200, json={"access": "t", "user": {}, "created": False})

        api = make_api(handler)
        await api.auth_telegram({"id": 5}, chat_id=5)
        request = seen["request"]

        ts = request.headers["X-Bot-Ts"]
        nonce = request.headers["X-Bot-Nonce"]
        assert request.headers["X-Bot-Sig"] == expected_signature(
            ts, nonce, "POST", "/api/bot/auth/telegram/", request.content)
        await api.aclose()

    @pytest.mark.asyncio
    async def test_every_request_has_new_nonce(self):
        """Иначе два быстрых /start подряд второй раз отобьются как повтор."""
        nonces = []

        def handler(request: httpx.Request) -> httpx.Response:
            nonces.append(request.headers["X-Bot-Nonce"])
            return httpx.Response(200, json={"access": "t", "user": {}, "created": False})

        api = make_api(handler)
        await api.auth_telegram({"id": 5}, chat_id=5)
        await api.auth_telegram({"id": 5}, chat_id=5)
        assert nonces[0] != nonces[1]
        await api.aclose()

    @pytest.mark.asyncio
    async def test_user_requests_are_not_signed(self):
        """Обычные запросы идут от имени человека — там подпись не нужна."""
        seen = {}

        def handler(request: httpx.Request) -> httpx.Response:
            seen["headers"] = request.headers
            return httpx.Response(200, json={"balance_tokens": 10})

        api = make_api(handler)
        await api.balance("user-token", telegram_id=42)
        assert "X-Bot-Sig" not in seen["headers"]
        assert seen["headers"]["Authorization"] == "Bearer user-token"
        await api.aclose()


class TestHeaders:
    @pytest.mark.asyncio
    async def test_public_host_and_device_key(self):
        """Хост нужен, чтобы ссылки на медиа были внешними; ключ — для антифрода."""
        seen = {}

        def handler(request: httpx.Request) -> httpx.Response:
            seen["headers"] = request.headers
            return httpx.Response(200, json={})

        api = make_api(handler)
        await api.balance("token", telegram_id=777)
        assert seen["headers"]["Host"] == "esai.kg"
        assert seen["headers"]["X-Forwarded-Proto"] == "https"
        assert seen["headers"]["X-Device-Key"] == "tg:777"
        await api.aclose()

    @pytest.mark.asyncio
    async def test_language_header(self):
        seen = {}

        def handler(request: httpx.Request) -> httpx.Response:
            seen["lang"] = request.headers.get("Accept-Language")
            return httpx.Response(200, json={})

        api = make_api(handler)
        await api.balance("token", lang="kg")
        assert seen["lang"] == "ky"
        await api.aclose()


class TestErrors:
    @pytest.mark.asyncio
    @pytest.mark.parametrize("code", ["insufficient_balance", "premium_locked",
                                      "daily_limit_reached", "insufficient_tokens"])
    async def test_paywall_codes_recognised(self, code):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(402, json={"error_code": code, "balance_tokens": 3})

        api = make_api(handler)
        with pytest.raises(ApiError) as info:
            await api.balance("token")
        assert info.value.is_paywall
        assert info.value.code == code
        await api.aclose()

    @pytest.mark.asyncio
    async def test_server_error_is_not_paywall(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(500, json={"detail": "boom"})

        api = make_api(handler)
        with pytest.raises(ApiError) as info:
            await api.balance("token")
        assert not info.value.is_paywall
        assert info.value.status == 500
        await api.aclose()


class TestStream:
    @staticmethod
    def _sse(frames) -> bytes:
        return b"".join(b"data: " + json.dumps(f).encode() + b"\n\n" for f in frames)

    @pytest.mark.asyncio
    async def test_frames_are_parsed_in_order(self):
        frames = [
            {"delta": "При"}, {"delta": "вет"},
            {"sources": [{"url": "https://esai.kg", "title": "EsAI"}]},
            {"done": True, "tokens_charged": 3, "balance_tokens": 97,
             "message": {"content": "Привет"}},
        ]

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, content=self._sse(frames),
                                  headers={"content-type": "text/event-stream"})

        api = make_api(handler)
        got = [f async for f in api.chat_stream("token", {"message": "привет"})]
        assert [f.get("delta") for f in got[:2]] == ["При", "вет"]
        assert got[-1]["done"] is True
        assert got[-1]["tokens_charged"] == 3
        await api.aclose()

    @pytest.mark.asyncio
    async def test_paywall_before_stream_is_raised(self):
        """Отказ приходит обычным JSON — человеку нужен понятный экран, не пустота."""
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(402, json={"error_code": "insufficient_balance",
                                             "balance_tokens": 1})

        api = make_api(handler)
        with pytest.raises(ApiError) as info:
            async for _ in api.chat_stream("token", {"message": "привет"}):
                pass
        assert info.value.code == "insufficient_balance"
        await api.aclose()

    @pytest.mark.asyncio
    async def test_error_frame_inside_stream(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, content=self._sse([
                {"delta": "нача"},
                {"error": "модель отвалилась", "error_code": "provider_error", "done": True},
            ]), headers={"content-type": "text/event-stream"})

        api = make_api(handler)
        frames = [f async for f in api.chat_stream("token", {"message": "привет"})]
        assert frames[-1]["error_code"] == "provider_error"
        await api.aclose()

    @pytest.mark.asyncio
    async def test_broken_frame_does_not_kill_stream(self):
        frames = ['data: {"delta": "ок"}', 'data: {not json}', 'data: {"done": true}']
        body = ("\n\n".join(frames) + "\n\n").encode()

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, content=body,
                                  headers={"content-type": "text/event-stream"})

        api = make_api(handler)
        frames = [f async for f in api.chat_stream("token", {"message": "привет"})]
        assert frames[0]["delta"] == "ок"
        assert frames[-1]["done"] is True
        await api.aclose()

    @pytest.mark.asyncio
    async def test_stream_flag_is_sent(self):
        seen = {}

        def handler(request: httpx.Request) -> httpx.Response:
            seen["body"] = json.loads(request.content)
            return httpx.Response(200, content=b"data: {\"done\": true}\n\n",
                                  headers={"content-type": "text/event-stream"})

        api = make_api(handler)
        async for _ in api.chat_stream("token", {"message": "привет", "model": "m"}):
            pass
        assert seen["body"]["stream"] is True
        assert seen["body"]["model"] == "m"
        await api.aclose()


class TestStreamAccept:
    @pytest.mark.asyncio
    async def test_stream_accept_is_negotiable_by_drf(self):
        """DRF отвечает 406 на один text/event-stream — так упал первый /image на проде."""

        def handler(request: httpx.Request) -> httpx.Response:
            accept = request.headers.get("Accept", "")
            if "application/json" not in accept and "*/*" not in accept:
                return httpx.Response(406, json={"detail": "Not Acceptable"})
            body = 'data: {"delta": "ok"}

data: {"done": true}

'
            return httpx.Response(200, content=body.encode(),
                                  headers={"content-type": "text/event-stream"})

        api = make_api(handler)
        frames = [f async for f in api.chat_stream("t", {"message": "x", "model": "m"})]
        assert frames[0] == {"delta": "ok"} and frames[-1] == {"done": True}
        await api.aclose()
