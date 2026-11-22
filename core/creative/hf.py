"""Тонкий клиент API поставщика генераций Creative Studio (SPEC_B §1).

Только HTTP: в базу не ходит, деньги не трогает. Возвращает простые объекты,
ошибки — HFError с нашим кодом:

    provider_unavailable  401/403 (нет денег у поставщика, ключ отключён или не задан)
    retry_later           429 account_queue_full, 423, 503 — повторить позже ТЕМ ЖЕ ключом
    bad_params            400/422 — ошибка нашего тела (в лог, человеку bad_params)
    not_found             404 — задачи или модели нет у аккаунта
    transient             5xx, таймаут, обрыв — исход неизвестен, повтор тем же ключом
    bad_response          2xx без нужных полей

Правила:
- ключ HF_KEY уходит только заголовком Authorization и только на хост
  API (ALLOWED_HOST, https). Ссылки на файлы (CDN, адрес загрузки) получают
  запрос без ключа. Ключ не попадает ни в лог, ни в текст ошибки;
- текст ответа поставщика (detail) только в лог и обрезанным: в нём может
  быть название поставщика, человеку его не показываем;
- тесты подменяют транспорт (creative.hf.set_transport(httpx.MockTransport(...))) —
  настоящих сетевых вызовов в тестах нет.
"""
from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from typing import Optional
from urllib.parse import quote, urlsplit

import httpx
from django.conf import settings

logger = logging.getLogger(__name__)

BASE_URL = "https://api.higgsfield.ai"
ALLOWED_HOST = "api.higgsfield.ai"

TIMEOUT_SUBMIT = httpx.Timeout(60.0, connect=10.0)
TIMEOUT_SHORT = httpx.Timeout(20.0, connect=10.0)
TIMEOUT_UPLOAD = httpx.Timeout(180.0, connect=15.0)
DOWNLOAD_WALL_S = 180
DETAIL_LOG_CHARS = 300

# Подмена транспорта для тестов (httpx.MockTransport). None — настоящая сеть.
_transport: Optional[httpx.BaseTransport] = None


def set_transport(transport: Optional[httpx.BaseTransport]) -> None:
    global _transport
    _transport = transport


class HFError(Exception):
    """Отказ поставщика нашим кодом. detail — короткий текст для лога (без ключа)."""

    def __init__(self, code: str, *, status: int = 0, detail: str = "", retry_after: int = 0,
                 sent: bool = False):
        super().__init__(code)
        self.code = code
        self.status = int(status or 0)
        self.detail = str(detail or "")[:DETAIL_LOG_CHARS]
        self.retry_after = int(retry_after or 0)
        # sent=True — запрос мог дойти до поставщика (исход неизвестен).
        self.sent = bool(sent)

    def __str__(self):
        return f"{self.code} (http {self.status})" if self.status else self.code


@dataclass(frozen=True)
class Submitted:
    request_id: str
    status: str
    correlation_id: str = ""


@dataclass(frozen=True)
class Status:
    status: str                     # queued | in_progress | completed | failed | nsfw | canceled
    request_id: str = ""
    images: tuple = ()              # ссылки на картинки (CDN поставщика — только сервер)
    video: str = ""
    error: str = ""                 # текст поставщика — только в лог

    @property
    def done(self) -> bool:
        return self.status in ("completed", "failed", "nsfw", "canceled")

    @property
    def urls(self) -> list[str]:
        return list(self.images) + ([self.video] if self.video else [])


@dataclass(frozen=True)
class Character:
    id: str
    status: str                     # not_ready | queued | in_progress | completed | failed
    thumbnail_url: str = ""
    fail_reason: str = ""


@dataclass
class Upload:
    public_url: str
    extra: dict = field(default_factory=dict)


# ---------------------------------------------------------------- низ

def _key() -> str:
    return str(getattr(settings, "HF_KEY", "") or "").strip()


def configured() -> bool:
    return bool(_key())


def _auth_allowed(url: str) -> bool:
    """Ключ — только на https://<ALLOWED_HOST>: CDN и адрес загрузки его не видят."""
    try:
        parts = urlsplit(url)
    except ValueError:
        return False
    return parts.scheme == "https" and (parts.hostname or "").lower() == ALLOWED_HOST


# Откуда разрешено скачивать результаты и превью каталогов (B0 23.11: CDN поставщика на его
# поддоменах и CloudFront). Иначе ссылка из ответа поставщика могла бы увести воркер на любой
# хост, в том числе внутренний. Дополнительные хосты — settings.CREATIVE_MEDIA_EXTRA_HOSTS.
MEDIA_HOST_SUFFIXES = (".higgsfield.ai", ".cloudfront.net")


def media_host_allowed(url: str) -> bool:
    try:
        parts = urlsplit(url)
    except ValueError:
        return False
    host = (parts.hostname or "").lower().rstrip(".")
    if parts.scheme != "https" or not host:
        return False
    extra = {h.strip().lower() for h in getattr(settings, "CREATIVE_MEDIA_EXTRA_HOSTS", ()) if h and h.strip()}
    return host == ALLOWED_HOST or host in extra or any(host.endswith(s) for s in MEDIA_HOST_SUFFIXES)


def _client(timeout) -> httpx.Client:
    kwargs = {"timeout": timeout, "follow_redirects": False}
    if _transport is not None:
        kwargs["transport"] = _transport
    return httpx.Client(**kwargs)


def _headers(url: str, extra: dict | None = None) -> dict:
    headers = {"Accept": "application/json"}
    if _auth_allowed(url):
        key = _key()
        if not key:
            raise HFError("provider_unavailable", detail="HF_KEY не задан")
        headers["Authorization"] = f"Key {key}"
    if extra:
        headers.update(extra)
    return headers


def _safe(text: str) -> str:
    """Текст ответа для лога: без ключа и коротко."""
    text = str(text or "")
    key = _key()
    if key:
        text = text.replace(key, "<key>")
        if ":" in key:
            for part in key.split(":"):
                if len(part) >= 8:
                    text = text.replace(part, "<key>")
    return text[:DETAIL_LOG_CHARS]


def _retry_after(resp: httpx.Response) -> int:
    raw = resp.headers.get("Retry-After")
    try:
        if raw:
            return max(1, int(float(raw)))
    except (TypeError, ValueError):
        pass
    try:
        detail = (resp.json() or {}).get("detail")
        if isinstance(detail, dict) and detail.get("retry_after_seconds"):
            return max(1, int(detail["retry_after_seconds"]))
    except Exception:
        pass
    return 30


def _raise_for(resp: httpx.Response, *, sent: bool) -> None:
    """Ответ не 2xx → HFError с нашим кодом."""
    status = resp.status_code
    detail = _safe(resp.text)
    if status in (401, 403):
        disabled = "no-store" in str(resp.headers.get("Cache-Control", "")).lower()
        reason = "key_invalid" if status == 401 else ("key_disabled" if disabled else "balance")
        raise HFError("provider_unavailable", status=status, detail=f"{reason}: {detail}")
    if status in (423, 429, 503):
        raise HFError("retry_later", status=status, detail=detail, retry_after=_retry_after(resp))
    if status in (400, 422):
        raise HFError("bad_params", status=status, detail=detail)
    if status == 404:
        raise HFError("not_found", status=status, detail=detail)
    if status >= 500:
        raise HFError("transient", status=status, detail=detail, sent=sent)
    raise HFError("bad_params", status=status, detail=detail)


def _request(method: str, path_or_url: str, *, json=None, timeout=TIMEOUT_SHORT,
             headers: dict | None = None, sent_on_error: bool = False) -> httpx.Response:
    url = path_or_url if path_or_url.startswith("https://") else f"{BASE_URL}/{path_or_url.lstrip('/')}"
    hdrs = _headers(url, headers)
    try:
        with _client(timeout) as client:
            resp = client.request(method, url, json=json, headers=hdrs)
    except httpx.TimeoutException as exc:
        raise HFError("transient", detail=f"timeout: {type(exc).__name__}", sent=sent_on_error) from None
    except httpx.HTTPError as exc:
        raise HFError("transient", detail=f"network: {type(exc).__name__}", sent=sent_on_error) from None
    if resp.status_code >= 300:
        _raise_for(resp, sent=sent_on_error)
    return resp


def _json(resp: httpx.Response):
    try:
        return resp.json()
    except ValueError:
        raise HFError("bad_response", status=resp.status_code, detail=_safe(resp.text)) from None


# ---------------------------------------------------------------- генерации

def submit(model: str, body: dict, *, idempotency_key: str, hook_url: str = "") -> Submitted:
    """POST /<model> с Idempotency-Key. Повтор с тем же ключом и телом — та же задача."""
    path = model
    if hook_url:
        path = f"{model}?hf_webhook={quote(hook_url, safe='')}"
    resp = _request("POST", path, json=body, timeout=TIMEOUT_SUBMIT,
                    headers={"Idempotency-Key": idempotency_key, "Content-Type": "application/json"},
                    sent_on_error=True)
    data = _json(resp)
    request_id = str((data or {}).get("request_id") or "") if isinstance(data, dict) else ""
    if not request_id:
        raise HFError("bad_response", status=resp.status_code, detail="нет request_id", sent=True)
    return Submitted(request_id=request_id[:64], status=str(data.get("status") or "queued"),
                     correlation_id=str(resp.headers.get("X-Correlation-ID") or "")[:64])


def _media_urls(data: dict) -> tuple[tuple, str]:
    """Ссылки результата: в опросе — в корне, в вебхуке — внутри payload."""
    src = data
    if isinstance(data.get("payload"), dict):
        src = data["payload"]
    images = []
    for item in src.get("images") or []:
        url = item.get("url") if isinstance(item, dict) else None
        if isinstance(url, str) and url.startswith("https://"):
            images.append(url)
    video = ""
    raw_video = src.get("video")
    if isinstance(raw_video, dict) and isinstance(raw_video.get("url"), str):
        if raw_video["url"].startswith("https://"):
            video = raw_video["url"]
    return tuple(images), video


def parse_status(data) -> Status:
    if not isinstance(data, dict):
        raise HFError("bad_response", detail="ответ статуса не объект")
    images, video = _media_urls(data)
    return Status(status=str(data.get("status") or ""), request_id=str(data.get("request_id") or ""),
                  images=images, video=video, error=_safe(data.get("error") or ""))


def status(request_id: str) -> Status:
    resp = _request("GET", f"requests/{quote(str(request_id), safe='')}/status")
    return parse_status(_json(resp))


def cancel(request_id: str) -> bool:
    """True — поставщик снял задачу из очереди (202). 400 — уже идёт: False."""
    try:
        resp = _request("POST", f"requests/{quote(str(request_id), safe='')}/cancel")
    except HFError as exc:
        if exc.status == 400:
            return False
        raise
    return resp.status_code in (200, 202, 204)


def estimate(model: str, body: dict) -> Optional[Decimal]:
    """Оценка поставщика ($) — только для сверки в админке/тестах. None — описание вместо цены."""
    resp = _request("POST", f"estimate/{model}", json=body)
    data = _json(resp)
    raw = data.get("usd") if isinstance(data, dict) else None
    if raw in (None, ""):
        return None
    try:
        return Decimal(str(raw))
    except (InvalidOperation, ValueError):
        return None


# ---------------------------------------------------------------- персонажи (Soul ID)

def _character(data) -> Character:
    if not isinstance(data, dict) or not data.get("id"):
        raise HFError("bad_response", detail="нет id персонажа")
    thumb = data.get("thumbnail_url")
    return Character(id=str(data["id"])[:64], status=str(data.get("status") or ""),
                     thumbnail_url=thumb if isinstance(thumb, str) and thumb.startswith("https://") else "",
                     fail_reason=_safe(data.get("fail_reason") or ""))


def create_character(body: dict) -> Character:
    """POST /v1/custom-references. Идемпотентности у этого адреса нет — повторять нельзя."""
    resp = _request("POST", "v1/custom-references", json=body, timeout=TIMEOUT_SUBMIT,
                    headers={"Content-Type": "application/json"}, sent_on_error=True)
    return _character(_json(resp))


def character_status(provider_id: str) -> Character:
    resp = _request("GET", f"v1/custom-references/{quote(str(provider_id), safe='')}")
    return _character(_json(resp))


# ---------------------------------------------------------------- файлы

def upload_file(path: str, content_type: str) -> str:
    """Положить файл к поставщику: адрес загрузки → PUT со всеми upload_headers → public_url."""
    resp = _request("POST", "files/generate-upload-url", json={"content_type": content_type},
                    headers={"Content-Type": "application/json"})
    data = _json(resp)
    if not isinstance(data, dict):
        raise HFError("bad_response", detail="ответ загрузки не объект")
    upload_url = data.get("upload_url")
    public_url = data.get("public_url")
    if not (isinstance(upload_url, str) and upload_url.startswith("https://")
            and isinstance(public_url, str) and public_url.startswith("https://")):
        raise HFError("bad_response", detail="нет адреса загрузки")
    headers = data.get("upload_headers") if isinstance(data.get("upload_headers"), dict) else {}
    headers = {str(k): str(v) for k, v in headers.items()} or {"Content-Type": content_type}
    try:
        size = os.path.getsize(path)
        with open(path, "rb") as fh, _client(TIMEOUT_UPLOAD) as client:
            # Ключ сюда не уходит: адрес загрузки — чужой хост (_headers не зовём).
            put = client.put(upload_url, content=fh, headers={**headers, "Content-Length": str(size)})
    except httpx.TimeoutException:
        raise HFError("transient", detail="upload timeout") from None
    except (httpx.HTTPError, OSError) as exc:
        raise HFError("transient", detail=f"upload: {type(exc).__name__}") from None
    if put.status_code not in (200, 201, 204):
        raise HFError("transient" if put.status_code >= 500 else "bad_params",
                      status=put.status_code, detail="PUT загрузки отклонён")
    return public_url


def download(url: str, dest: str, *, max_bytes: int, wall_s: float = DOWNLOAD_WALL_S) -> int:
    """Скачать результат во временный файл. Ключ уходит только на хост API.

    Бросает HFError(transient | bad_response); недокачанный файл стирается.
    """
    if not isinstance(url, str) or not url.startswith("https://"):
        raise HFError("bad_response", detail="ссылка не https")
    if not media_host_allowed(url):
        logger.error("creative: скачивание с неразрешённого хоста отклонено: %s", urlsplit(url).hostname)
        raise HFError("bad_response", detail="хост не разрешён")
    headers = {"Authorization": f"Key {_key()}"} if _auth_allowed(url) and _key() else {}
    started = time.monotonic()
    size = 0
    try:
        with _client(httpx.Timeout(60.0, connect=15.0)) as client:
            with client.stream("GET", url, headers=headers) as resp:
                if resp.status_code != 200:
                    raise HFError("transient" if resp.status_code >= 500 or resp.status_code == 429
                                  else "bad_response", status=resp.status_code, detail="скачивание")
                with open(dest, "wb") as fh:
                    for chunk in resp.iter_bytes(1024 * 256):
                        size += len(chunk)
                        if size > max_bytes:
                            raise HFError("bad_response", detail=f"файл больше {max_bytes} байт")
                        if time.monotonic() - started > wall_s:
                            raise HFError("transient", detail="скачивание дольше лимита")
                        fh.write(chunk)
    except HFError:
        _rm(dest)
        raise
    except (httpx.HTTPError, OSError) as exc:
        _rm(dest)
        raise HFError("transient", detail=f"download: {type(exc).__name__}") from None
    if size <= 0:
        _rm(dest)
        raise HFError("bad_response", detail="пустой файл")
    return size


def _rm(path: str) -> None:
    try:
        os.remove(path)
    except OSError:
        pass


# ---------------------------------------------------------------- каталоги

def get_json(path: str, params: dict | None = None):
    """GET каталога (стили, пресеты, опции) с ключом."""
    if params:
        from urllib.parse import urlencode

        path = f"{path}?{urlencode(params)}"
    return _json(_request("GET", path))


__all__ = ["HFError", "Submitted", "Status", "Character", "submit", "status", "cancel",
           "estimate", "create_character", "character_status", "upload_file", "download",
           "get_json", "parse_status", "configured", "set_transport", "BASE_URL", "ALLOWED_HOST"]
