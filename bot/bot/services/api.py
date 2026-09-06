"""Клиент нашего API.

Бот не считает деньги и не ходит в базу — всё это делает сайт по тем же
адресам, что и его собственный фронт. Так списания, лимиты и антифрод
остаются в одном месте, а бот остаётся тонким.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import logging
import time
import uuid
from typing import Any, AsyncIterator

import httpx

from bot.config import settings

logger = logging.getLogger(__name__)

# Обычные запросы отвечают быстро; загрузка файлов — дольше; поток ответа
# модели не ограничиваем по чтению вовсе, но сторожим паузы между кадрами.
TIMEOUT = httpx.Timeout(connect=5.0, read=60.0, write=30.0, pool=5.0)
UPLOAD_TIMEOUT = httpx.Timeout(connect=5.0, read=180.0, write=180.0, pool=5.0)
STREAM_TIMEOUT = httpx.Timeout(connect=5.0, read=None, write=30.0, pool=5.0)
# Если кадров нет дольше этого — соединение считаем мёртвым.
STREAM_SILENCE_LIMIT = 180.0


class ApiError(Exception):
    """Ошибка нашего API с разобранной причиной."""

    def __init__(self, status: int, code: str = "", payload: Any = None, message: str = ""):
        super().__init__(message or code or f"http_{status}")
        self.status = status
        self.code = code or ""
        self.payload = payload if isinstance(payload, dict) else {}
        self.message = message or ""

    @property
    def is_paywall(self) -> bool:
        return self.code in ("insufficient_balance", "insufficient_tokens",
                             "premium_locked", "daily_limit_reached")


def _service_headers(method: str, path: str, body: bytes) -> dict:
    ts = str(int(time.time()))
    nonce = uuid.uuid4().hex
    digest = hashlib.sha256(body or b"").hexdigest()
    message = f"{ts}\n{nonce}\n{method.upper()}\n{path}\n{digest}"
    signature = hmac.new(settings.service_secret.encode(), message.encode(),
                         hashlib.sha256).hexdigest()
    return {"X-Bot-Ts": ts, "X-Bot-Nonce": nonce, "X-Bot-Sig": signature}


class Api:
    """Один клиент на весь процесс: соединения переиспользуются."""

    def __init__(self, base: str = "", host: str = ""):
        self.base = (base or settings.api_base).rstrip("/")
        self.host = host or settings.public_host
        self._client = httpx.AsyncClient(base_url=self.base, timeout=TIMEOUT,
                                         limits=httpx.Limits(max_connections=100))

    async def aclose(self) -> None:
        await self._client.aclose()

    def _headers(self, token: str = "", lang: str = "ru", telegram_id: int | None = None) -> dict:
        headers = {
            # Хост и протокол: по ним core строит абсолютные ссылки на медиа.
            "Host": self.host,
            "X-Forwarded-Proto": "https",
            "Accept-Language": {"kg": "ky", "en": "en"}.get(lang, "ru"),
        }
        if token:
            headers["Authorization"] = f"Bearer {token}"
        if telegram_id:
            # Тот же отпечаток, что у сайта: по нему работают антифрод и блокировки.
            headers["X-Device-Key"] = f"tg:{telegram_id}"
        return headers

    @staticmethod
    def _raise(response: httpx.Response) -> None:
        if response.status_code < 400:
            return
        payload: Any = {}
        try:
            payload = response.json()
        except ValueError:
            payload = {}
        code = ""
        message = ""
        if isinstance(payload, dict):
            code = str(payload.get("error_code") or payload.get("detail") or "")
            message = str(payload.get("message") or payload.get("detail") or "")
        raise ApiError(response.status_code, code=code, payload=payload, message=message)

    async def request(self, method: str, path: str, *, token: str = "", lang: str = "ru",
                      telegram_id: int | None = None, json_body: Any = None,
                      params: dict | None = None, service: bool = False,
                      files: Any = None, timeout: Any = None) -> Any:
        headers = self._headers(token, lang, telegram_id)
        body = b""
        kwargs: dict = {"params": params}
        if files is not None:
            kwargs["files"] = files
            timeout = timeout or UPLOAD_TIMEOUT
        elif json_body is not None:
            body = json.dumps(json_body).encode()
            headers["Content-Type"] = "application/json"
            kwargs["content"] = body
        if service:
            headers.update(_service_headers(method, path, body))
        response = await self._client.request(method, path, headers=headers,
                                              timeout=timeout or TIMEOUT, **kwargs)
        self._raise(response)
        if not response.content:
            return None
        try:
            return response.json()
        except ValueError:
            return response.text

    # ------------------------------------------------------------- вход ---

    async def auth_telegram(self, tg_user: dict, *, chat_id: int, ref: str = "",
                            promo: str = "") -> dict:
        """Обменять данные Telegram на токен человека."""
        return await self.request(
            "POST", "/api/bot/auth/telegram/", service=True,
            json_body={"telegram_user": tg_user, "chat_id": chat_id,
                       "ref": ref or "", "promo": promo or ""},
        )

    async def set_prefs(self, telegram_id: int, **flags) -> dict:
        return await self.request("POST", "/api/bot/prefs/", service=True,
                                  json_body={"telegram_id": telegram_id, **flags})

    async def mark_blocked(self, telegram_id: int, blocked: bool = True) -> dict:
        return await self.request("POST", "/api/bot/blocked/", service=True,
                                  json_body={"telegram_id": telegram_id, "blocked": blocked})

    # ---------------------------------------------------------- витрина ---

    async def balance(self, token: str, **kw) -> dict:
        return await self.request("GET", "/api/plans/balance/", token=token, **kw)

    async def models(self, token: str, **kw) -> list:
        data = await self.request("GET", "/api/ai/models/", token=token, **kw)
        return data if isinstance(data, list) else []

    async def packages(self, token: str, lang: str = "ru", **kw) -> list:
        data = await self.request("GET", "/api/plans/packages/", token=token, lang=lang,
                                  params={"lang": lang}, **kw)
        return data if isinstance(data, list) else []

    async def transactions(self, token: str, **kw) -> list:
        data = await self.request("GET", "/api/plans/transactions/", token=token, **kw)
        if isinstance(data, dict):
            return data.get("results") or []
        return data if isinstance(data, list) else []

    async def sessions(self, token: str, **kw) -> list:
        data = await self.request("GET", "/api/ai/sessions/", token=token, **kw)
        if isinstance(data, dict):
            return data.get("results") or []
        return data if isinstance(data, list) else []

    async def upload(self, token: str, name: str, content: bytes, mime: str, **kw) -> dict:
        return await self.request(
            "POST", "/api/ai/attachments/upload/", token=token,
            files={"files": (name, content, mime)}, **kw)

    # ------------------------------------------------------------- чат ---

    async def chat_stream(self, token: str, body: dict, *, lang: str = "ru",
                          telegram_id: int | None = None) -> AsyncIterator[dict]:
        """Поток ответа модели.

        Отдаём кадры так же, как их видит сайт: delta, reasoning, sources,
        image_pending, video_progress, done, error. Если до первого кадра
        пришла обычная ошибка (не хватило кредитов, дневной лимит) — она
        приходит JSON-ом, и мы поднимаем её как ApiError, чтобы показать
        человеку понятный экран, а не пустой ответ.
        """
        headers = self._headers(token, lang, telegram_id)
        headers["Content-Type"] = "application/json"
        headers["Accept"] = "text/event-stream"
        payload = json.dumps({**body, "stream": True}).encode()

        async with self._client.stream("POST", "/api/ai/chat/", content=payload,
                                       headers=headers, timeout=STREAM_TIMEOUT) as response:
            if response.status_code >= 400:
                await response.aread()
                self._raise(response)
            if "text/event-stream" not in (response.headers.get("content-type") or ""):
                await response.aread()
                try:
                    data = response.json()
                except ValueError:
                    data = {}
                if isinstance(data, dict) and data.get("error"):
                    raise ApiError(200, code=str(data.get("error_code") or ""),
                                   payload=data, message=str(data.get("error") or ""))
                yield {"done": True, **(data if isinstance(data, dict) else {})}
                return

            last = time.monotonic()
            async for line in response.aiter_lines():
                now = time.monotonic()
                if now - last > STREAM_SILENCE_LIMIT:
                    raise ApiError(504, code="stream_timeout", message="ответ оборвался")
                if not line or not line.startswith("data:"):
                    continue
                last = now
                chunk = line[5:].strip()
                if not chunk:
                    continue
                try:
                    yield json.loads(chunk)
                except ValueError:
                    logger.warning("непонятный кадр потока: %r", chunk[:120])


api = Api()
