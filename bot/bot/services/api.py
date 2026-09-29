"""Клиент нашего API.

Бот не считает деньги и не ходит в базу — всё это делает сайт по тем же
адресам, что и его собственный фронт. Так списания, лимиты и антифрод
остаются в одном месте, а бот остаётся тонким.
"""
from __future__ import annotations

import asyncio
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

# Обычные запросы отвечают быстро; загрузка файлов — дольше.
TIMEOUT = httpx.Timeout(connect=5.0, read=60.0, write=30.0, pool=5.0)
UPLOAD_TIMEOUT = httpx.Timeout(connect=5.0, read=180.0, write=180.0, pool=5.0)
# Если кадров нет дольше этого — соединение считаем мёртвым.
STREAM_SILENCE_LIMIT = 180.0
# read в httpx — это пауза МЕЖДУ чтениями, а не общее время ответа, поэтому
# длинный поток он не рвёт, зато зависший сервер отваливается сам. С read=None
# сторожить паузы было некому: строк нет — цикл по строкам не крутится.
STREAM_TIMEOUT = httpx.Timeout(connect=5.0, read=STREAM_SILENCE_LIMIT, write=30.0, pool=5.0)
# 429 с коротким Retry-After переживаем сами: подождать секунду дешевле, чем
# отказать человеку во входе или отложить зачисление оплаты. Дольше ждать в
# обработчике нельзя — такие повторы уходят в очередь (см. billing).
INLINE_RETRY_MAX = 2.0


_BONUS_CACHE: dict = {}


class ApiError(Exception):
    """Ошибка нашего API с разобранной причиной."""

    def __init__(self, status: int, code: str = "", payload: Any = None, message: str = "",
                 retry_after: float | None = None):
        super().__init__(message or code or f"http_{status}")
        self.status = status
        self.code = code or ""
        self.payload = payload if isinstance(payload, dict) else {}
        self.message = message or ""
        # Сколько секунд сервер просит подождать (заголовок Retry-After у 429).
        self.retry_after = retry_after

    @property
    def is_paywall(self) -> bool:
        return self.code in ("insufficient_balance", "insufficient_tokens",
                             "premium_locked", "daily_limit_reached")

    @property
    def is_temporary(self) -> bool:
        """Сервер не смог сейчас, но сможет позже: 5xx, 429 и обрыв связи.

        429 — это «приходите позже», а не отказ по существу: оплату с таким
        ответом нужно повторить, как и при упавшем сервере, а не бросать.
        """
        return (self.status >= 500 or self.status == 429
                or self.code in ("stream_timeout", "transport"))


def _service_headers(method: str, path: str, body: bytes) -> dict:
    ts = str(int(time.time()))
    nonce = uuid.uuid4().hex
    digest = hashlib.sha256(body or b"").hexdigest()
    message = f"{ts}\n{nonce}\n{method.upper()}\n{path}\n{digest}"
    signature = hmac.new(settings.service_secret.encode(), message.encode(),
                         hashlib.sha256).hexdigest()
    return {"X-Bot-Ts": ts, "X-Bot-Nonce": nonce, "X-Bot-Sig": signature}


def _transport_error(exc: httpx.HTTPError) -> ApiError:
    """Сетевую ошибку httpx переводим в свою.

    Вызывающий код ловит только ApiError: без перевода рестарт core или обрыв
    потока улетают мимо, и «🤔 Думаю…» висит у человека навсегда. Коды выбраны
    под chat.py — он показывает «сервер недоступен» при status>=500 и
    code="stream_timeout". ReadTimeout — подкласс TimeoutException.
    """
    if isinstance(exc, httpx.TimeoutException):
        return ApiError(504, code="stream_timeout", message=str(exc) or "timeout")
    return ApiError(503, code="transport", message=str(exc) or exc.__class__.__name__)


def _retry_after(response: httpx.Response) -> float | None:
    """Retry-After в секундах; DRF отдаёт его целым числом."""
    raw = (response.headers.get("Retry-After") or "").strip()
    try:
        value = float(raw)
    except ValueError:
        return None
    return value if value >= 0 else None


def _list(data: Any) -> list:
    if isinstance(data, dict):
        return data.get("results") or data.get("items") or []
    return data if isinstance(data, list) else []


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
            message = str(payload.get("message") or payload.get("detail") or
                          payload.get("error") or "")
        raise ApiError(response.status_code, code=code, payload=payload, message=message,
                       retry_after=_retry_after(response) if response.status_code == 429 else None)

    async def request(self, method: str, path: str, *, token: str = "", lang: str = "ru",
                      telegram_id: int | None = None, json_body: Any = None,
                      params: dict | None = None, service: bool = False,
                      files: Any = None, data: dict | None = None, timeout: Any = None,
                      retry_throttled: bool = False) -> Any:
        """Запрос к API.

        retry_throttled — только там, где повтор безопасен (вход, проверка и
        подтверждение оплаты по её id, настройки): на 429 с коротким
        Retry-After ждём и повторяем один раз. Подпись собирается заново —
        старый разовый номер сервер второй раз не примет.
        """
        headers = self._headers(token, lang, telegram_id)
        body = b""
        kwargs: dict = {"params": params}
        if files is not None:
            kwargs["files"] = files
            if data:
                kwargs["data"] = data
            timeout = timeout or UPLOAD_TIMEOUT
        elif json_body is not None:
            body = json.dumps(json_body).encode()
            headers["Content-Type"] = "application/json"
            kwargs["content"] = body
        attempts = 2 if retry_throttled and files is None else 1
        for attempt in range(attempts):
            if service:
                headers.update(_service_headers(method, path, body))
            try:
                response = await self._client.request(method, path, headers=headers,
                                                      timeout=timeout or TIMEOUT, **kwargs)
            except httpx.HTTPError as exc:
                raise _transport_error(exc) from exc
            if response.status_code == 429 and attempt + 1 < attempts:
                wait = _retry_after(response)
                if wait is not None and wait <= INLINE_RETRY_MAX:
                    logger.info("%s %s: 429, повтор через %.1f с", method, path, wait)
                    await asyncio.sleep(wait)
                    continue
            break
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
            "POST", "/api/bot/auth/telegram/", service=True, retry_throttled=True,
            json_body={"telegram_user": tg_user, "chat_id": chat_id,
                       "ref": ref or "", "promo": promo or ""},
        )

    async def set_prefs(self, telegram_id: int, **flags) -> dict:
        return await self.request("POST", "/api/bot/prefs/", service=True, retry_throttled=True,
                                  json_body={"telegram_id": telegram_id, **flags})

    async def mark_blocked(self, telegram_id: int, blocked: bool = True) -> dict:
        return await self.request("POST", "/api/bot/blocked/", service=True, retry_throttled=True,
                                  json_body={"telegram_id": telegram_id, "blocked": blocked})

    async def link_confirm(self, code: str, tg_user: dict, *, chat_id: int) -> dict:
        return await self.request("POST", "/api/bot/link/confirm/", service=True,
                                  json_body={"code": code, "telegram_user": tg_user,
                                             "chat_id": chat_id})

    async def delete_account(self, telegram_id: int) -> dict:
        return await self.request("POST", "/api/bot/delete/", service=True,
                                  json_body={"telegram_id": telegram_id})

    # ---------------------------------------------------------- витрина ---

    async def balance(self, token: str, **kw) -> dict:
        return await self.request("GET", "/api/plans/balance/", token=token, **kw)

    async def models(self, token: str, **kw) -> list:
        return _list(await self.request("GET", "/api/ai/models/", token=token, **kw))

    async def packages(self, token: str, lang: str = "ru", **kw) -> list:
        return _list(await self.request("GET", "/api/plans/packages/", token=token, lang=lang,
                                        params={"lang": lang}, **kw))

    async def packages_value(self, token: str, lang: str = "ru", **kw) -> list:
        data = await self.request("GET", "/api/plans/packages/value/", token=token, lang=lang,
                                  params={"lang": lang}, **kw)
        return (data or {}).get("packages") or [] if isinstance(data, dict) else []

    async def bonus_settings(self) -> dict:
        """Размеры бонусов из админки: приветственный и ежедневный.

        Публичный эндпоинт, поэтому идёт без токена; ответ держим в памяти
        десять минут — числа меняются раз в месяц, а анонимные запросы бота
        делят один общий лимит по IP.
        """
        now = time.monotonic()
        cached = _BONUS_CACHE.get("value")
        if cached is not None and now - _BONUS_CACHE.get("at", 0.0) < 600:
            return cached
        try:
            data = await self.request("GET", "/api/plans/bonus-settings/")
        except Exception:  # noqa: BLE001 — витрина не должна падать из-за бонусов
            return cached or {}
        data = data if isinstance(data, dict) else {}
        _BONUS_CACHE.update(value=data, at=now)
        return data

    async def transactions(self, token: str, **kw) -> list:
        return _list(await self.request("GET", "/api/plans/transactions/", token=token, **kw))

    async def sessions(self, token: str, **kw) -> list:
        return _list(await self.request("GET", "/api/ai/sessions/", token=token, **kw))

    async def upload(self, token: str, name: str, content: bytes, mime: str, **kw) -> dict:
        return await self.request(
            "POST", "/api/ai/attachments/upload/", token=token,
            files={"files": (name, content, mime)}, **kw)

    async def video_params(self, token: str, model: str, **kw) -> dict:
        return await self.request("GET", "/api/ai/video-params/", token=token,
                                  params={"model": model}, **kw) or {}

    async def video_share(self, token: str, url: str, *, prompt: str = "", model: str = "",
                          **kw) -> dict:
        return await self.request("POST", "/api/ai/video/share/", token=token,
                                  json_body={"url": url, "prompt": prompt, "model": model}, **kw)

    # ------------------------------------------------------------- голос ---

    async def transcribe(self, token: str, content: bytes, mime: str, *, lang: str = "ru",
                         **kw) -> dict:
        return await self.request(
            "POST", "/api/ai/transcribe/", token=token, lang=lang,
            files={"file": ("voice.ogg", content, mime)}, data={"lang": lang}, **kw)

    # ------------------------------------------------------------ очередь ---

    async def create_job(self, token: str, body: dict, **kw) -> dict:
        return await self.request("POST", "/api/ai/jobs/", token=token, json_body=body, **kw)

    async def job(self, token: str, uid: str, **kw) -> dict:
        return await self.request("GET", f"/api/ai/jobs/{uid}/", token=token, **kw)

    async def cancel_job(self, token: str, uid: str, **kw) -> dict:
        return await self.request("POST", f"/api/ai/jobs/{uid}/cancel/", token=token, **kw)

    # -------------------------------------------------------------- Stars ---

    async def stars_invoice(self, telegram_id: int, package_id: int, lang: str = "ru") -> dict:
        return await self.request("POST", "/api/bot/stars/invoice/", service=True,
                                  json_body={"telegram_id": telegram_id,
                                             "package_id": package_id, "lang": lang})

    async def stars_invoice_message(self, payload: str, message_id: int) -> dict:
        return await self.request("POST", "/api/bot/stars/invoice/message/", service=True,
                                  json_body={"payload": payload, "message_id": message_id})

    async def stars_precheck(self, telegram_id: int, payload: str, total_amount: int,
                             currency: str) -> dict:
        # Проверка только читает счёт — повтор безопасен.
        return await self.request("POST", "/api/bot/stars/precheck/", service=True,
                                  retry_throttled=True,
                                  json_body={"telegram_id": telegram_id, "payload": payload,
                                             "total_amount": total_amount,
                                             "currency": currency})

    async def stars_confirm(self, body: dict) -> dict:
        # Сервер узнаёт оплату по её id и дважды не начисляет — повтор безопасен.
        return await self.request("POST", "/api/bot/stars/confirm/", service=True,
                                  retry_throttled=True,
                                  json_body=body, timeout=httpx.Timeout(30.0))

    async def stars_refunded(self, telegram_id: int, charge_id: str, payload: str = "") -> dict:
        return await self.request("POST", "/api/bot/stars/refunded/", service=True,
                                  json_body={"telegram_id": telegram_id,
                                             "telegram_payment_charge_id": charge_id,
                                             "payload": payload})

    # ------------------------------------------------------------ профиль ---

    async def profile(self, token: str, **kw) -> dict:
        return await self.request("GET", "/api/users/profile/", token=token, **kw) or {}

    async def update_profile(self, token: str, **fields) -> Any:
        return await self.request("PUT", "/api/users/profile/", token=token, json_body=fields)

    async def notifications(self, token: str, **kw) -> list:
        return _list(await self.request("GET", "/api/users/notifications/", token=token, **kw))

    async def memory(self, token: str, **kw) -> dict:
        return await self.request("GET", "/api/users/memory/", token=token, **kw) or {}

    async def memory_delete(self, token: str, pk: int, **kw) -> Any:
        return await self.request("DELETE", f"/api/users/memory/{pk}/", token=token, **kw)

    async def memory_clear(self, token: str, **kw) -> Any:
        return await self.request("POST", "/api/users/memory/clear/", token=token, **kw)

    async def memory_toggle(self, token: str, enabled: bool, **kw) -> Any:
        return await self.request("PATCH", "/api/users/memory/toggle/", token=token,
                                  json_body={"enabled": enabled}, **kw)

    async def transfer(self, token: str, recipient: str, amount: int, comment: str = "",
                       **kw) -> dict:
        return await self.request("POST", "/api/users/transfer/", token=token,
                                  json_body={"recipient": recipient, "amount": amount,
                                             "comment": comment}, **kw)

    async def transfers(self, token: str, **kw) -> Any:
        return await self.request("GET", "/api/users/transfers/", token=token, **kw)

    async def question(self, email: str, name: str, text: str, *, token: str = "",
                       **kw) -> Any:
        """Обращение в поддержку.

        С токеном сервер узнаёт человека и считает его обращения отдельно; без
        него запрос анонимный, и все обращения из бота делили один анонимный
        лимит по IP контейнера — всплеск у одних отказывал в поддержке другим.
        """
        return await self.request("POST", "/api/users/question/", token=token,
                                  json_body={"email": email, "name": name, "question": text},
                                  **kw)

    async def feedback(self, token: str, rating: int, message: str, **kw) -> Any:
        return await self.request("POST", "/api/users/feedback/", token=token,
                                  json_body={"rating": rating, "message": message,
                                             "source": "telegram"}, **kw)

    async def blog(self, lang: str = "ru") -> list:
        """Опубликованные статьи блога.

        Ходим в /articles/, а не в /blog/: только там есть slug, без которого
        не собрать ссылку на статью. Заголовок в сериализаторе разложен по
        языкам (title_ru/title_en/title_kg) — сводим его к одному ключу
        "title", чтобы роутеру не пришлось знать про эти поля. Записи без
        slug или заголовка выбрасываем: показывать в списке нечего.
        """
        data = await self.request("GET", "/api/content/articles/", lang=lang,
                                  params={"lang": lang, "page_size": 10})
        items: list[dict] = []
        for row in _list(data):
            if not isinstance(row, dict):
                continue
            slug = str(row.get("slug") or "").strip()
            title = ""
            for key in (f"title_{lang}", "title", "title_ru", "title_en", "title_kg"):
                title = str(row.get(key) or "").strip()
                if title:
                    break
            if not slug or not title:
                continue
            items.append({**row, "slug": slug, "title": title})
        return items

    async def signin(self, email: str, **kw) -> Any:
        return await self.request("POST", "/api/users/signin/", json_body={"email": email}, **kw)

    async def signin_confirm(self, email: str, code: str, **kw) -> dict:
        return await self.request("POST", "/api/users/signin/confirm/",
                                  json_body={"email": email, "code": code}, **kw) or {}

    async def link_start(self, token: str, **kw) -> dict:
        return await self.request("POST", "/api/users/telegram/link/start/", token=token, **kw)

    # ------------------------------------------------------------- студия ---

    async def presets(self, token: str, **kw) -> dict:
        return await self.request("GET", "/api/cartoon/presets/", token=token, **kw) or {}

    async def pricing(self, token: str, **kw) -> dict:
        return await self.request("GET", "/api/cartoon/pricing/", token=token, **kw) or {}

    async def characters(self, token: str, **kw) -> list:
        return _list(await self.request("GET", "/api/cartoon/characters/", token=token, **kw))

    async def character_upload(self, token: str, name: str, content: bytes, **kw) -> dict:
        return await self.request("POST", "/api/cartoon/characters/", token=token,
                                  files={"image": ("hero.jpg", content, "image/jpeg")},
                                  data={"name": name}, **kw)

    async def character_generate(self, token: str, prompt: str, **kw) -> dict:
        return await self.request("POST", "/api/cartoon/characters/generate/", token=token,
                                  json_body={"prompt": prompt},
                                  timeout=httpx.Timeout(200.0), **kw)

    async def projects(self, token: str, **kw) -> list:
        return _list(await self.request("GET", "/api/cartoon/projects/", token=token, **kw))

    async def project(self, token: str, pk: int, **kw) -> dict:
        return await self.request("GET", f"/api/cartoon/projects/{pk}/", token=token, **kw)

    async def create_project(self, token: str, character_id: int, title: str = "", **kw) -> dict:
        body = {"character_id": character_id}
        if title:
            body["title"] = title
        return await self.request("POST", "/api/cartoon/projects/", token=token, json_body=body, **kw)

    async def delete_project(self, token: str, pk: int, **kw) -> Any:
        return await self.request("DELETE", f"/api/cartoon/projects/{pk}/", token=token, **kw)

    async def add_scene(self, token: str, project_id: int, preset_id: int, **kw) -> dict:
        return await self.request("POST", f"/api/cartoon/projects/{project_id}/scenes/",
                                  token=token, json_body={"preset_id": preset_id}, **kw)

    async def try_on(self, token: str, preset_id: int, character_id: int, **kw) -> dict:
        return await self.request("POST", f"/api/cartoon/presets/{preset_id}/try-on/",
                                  token=token, json_body={"character_id": character_id},
                                  timeout=httpx.Timeout(200.0), **kw)

    async def keyframes(self, token: str, character_id: int, **kw) -> dict:
        return await self.request("GET", "/api/cartoon/keyframes/", token=token,
                                  params={"character_id": character_id}, **kw) or {}

    async def render_scene(self, token: str, scene_id: int, **kw) -> dict:
        return await self.request("POST", f"/api/cartoon/scenes/{scene_id}/render/",
                                  token=token, json_body={}, **kw)

    async def patch_scene(self, token: str, scene_id: int, body: dict, **kw) -> dict:
        return await self.request("PATCH", f"/api/cartoon/scenes/{scene_id}/", token=token,
                                  json_body=body, **kw)

    async def delete_scene(self, token: str, scene_id: int, **kw) -> Any:
        return await self.request("DELETE", f"/api/cartoon/scenes/{scene_id}/", token=token, **kw)

    async def assemble(self, token: str, project_id: int, **kw) -> dict:
        return await self.request("POST", f"/api/cartoon/projects/{project_id}/assemble/",
                                  token=token, json_body={}, **kw)

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
        # DRF договаривается о формате по Accept ещё до вызова вью: один только
        # text/event-stream он обслужить не умеет и отвечает 406. Сайт шлёт
        # такую же пару, поток при этом всё равно приходит SSE.
        headers["Accept"] = "text/event-stream, application/json"
        payload = json.dumps({**body, "stream": True}).encode()

        try:
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
                    # Страховка на случай потока «пустых» строк: read-таймаут их
                    # считает за жизнь, а кадров человек всё равно не видит.
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
        except httpx.HTTPError as exc:
            # Обрыв потока и рестарт core выглядят для человека одинаково —
            # ответ просто перестал приходить; показываем «сервер недоступен».
            raise _transport_error(exc) from exc


api = Api()
