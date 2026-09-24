"""HTTP-клиент OpenRouter для медиа: видео (/videos) и картинки (/images).

Чистые функции без записей в БД: только запрос, разбор ответа и понятный итог.
Что делать с итогом (журнал, деньги, статусы) — решает вызывающий. Так один и
тот же клиент годится и для короткой Celery-задачи видеостудии, и (в Фазе 1.5)
для чата, довоза и мультстудии.

Логика перенесена из ai/generation.py (отправка, опрос, скачивание) и
ai/recovery.py:deliver без изменения поведения чата: чат и довоз в Фазе 1 этот
модуль НЕ вызывают, их путь денег не трогаем.

Главное правило отправки видео: исход бывает трёх видов, а не двух.
- accepted — провайдер принял работу и вернул id/адрес опроса;
- rejected — провайдер отказал сам (4xx): денег он за это не берёт;
- unknown — ответа нет, 5xx или 2xx без id: запрос мог дойти и быть оплачен.
Путать unknown с rejected нельзя — так 21.09.2026 потерялся оплаченный ролик.

Второе правило: опрос и скачивание — ключом того аккаунта, что принял работу.
Работу видит только аккаунт, который её отправил. Автопереключение на запасной
аккаунт (ai.tasks.openrouter_autoswitch) посреди съёмки иначе давало 401/404 на
каждом опросе, и оплаченный ролик до выдачи не доезжал. Поэтому submit
отдаёт, чей ключ ушёл (current_config: account_id и отпечаток), вызывающий
хранит это рядом с адресом опроса, а poll_video / download_to_file получают
cfg=config_for(account_id, key_fp).
"""
from __future__ import annotations

import base64
import binascii
import hashlib
import logging
import os
import time
from dataclasses import dataclass, field
from typing import Any, Optional, Tuple, Union
from urllib.parse import urlsplit

import requests

logger = logging.getLogger(__name__)

Timeout = Union[float, Tuple[float, float]]

# Отправка ждёт долго: провайдер до ответа сам скачивает приложенные картинки,
# с тяжёлыми фото это больше полуминуты (см. generation.SUBMIT_READ_TIMEOUT).
SUBMIT_TIMEOUT: Tuple[float, float] = (10, 150)
# Опрос — один короткий GET: зависший ответ не должен держать слот воркера.
POLL_TIMEOUT: Tuple[float, float] = (5, 20)
# /images синхронный: картинка генерируется, пока висит соединение.
IMAGE_TIMEOUT: Tuple[float, float] = (10, 180)
# Пауза между чтениями при скачивании; общий потолок задаёт wall_s.
DOWNLOAD_READ_TIMEOUT = 60
DOWNLOAD_CHUNK = 1024 * 1024

# Текст ответа провайдера держим с запасом для разбора ошибок и журнала;
# вызывающий обрезает его под своё поле сам.
MAX_TEXT = 4000

STATE_ACCEPTED = "accepted"
STATE_REJECTED = "rejected"
STATE_UNKNOWN = "unknown"

VIDEO_COMPLETED = "completed"
# Итоговые отказы провайдера. «canceled» и «error» встречались у довоза
# (recovery.deliver), «cancelled» и «expired» — в документации OpenRouter.
VIDEO_FAILED_STATES = frozenset({"failed", "error", "cancelled", "canceled", "expired"})
# Ответы опроса «работа этому ключу не видна»: не сбой сети, а чужой или
# отозванный ключ, удалённая работа. Повторять их шесть часов бессмысленно —
# вызывающий считает их подряд и сдаётся раньше (Poll.unreachable).
UNREACHABLE_CODES = frozenset({401, 403, 404, 410})


# --- Итоги ------------------------------------------------------------------


@dataclass(frozen=True)
class Submit:
    """Итог POST /videos.

    state: accepted | rejected | unknown (см. docstring модуля).
    status_code: None, если HTTP-ответа не было (таймаут, сеть, нет ключа).
    text: сырой ответ провайдера или текст исключения — для explain_video_error
    и журнала (до MAX_TEXT символов).
    """

    state: str
    job_id: str = ""
    polling_url: str = ""
    status_code: Optional[int] = None
    text: str = ""

    @property
    def accepted(self) -> bool:
        return self.state == STATE_ACCEPTED


@dataclass(frozen=True)
class Poll:
    """Итог одного GET по адресу опроса.

    status: статус провайдера в нижнем регистре (queued, in_progress,
    completed, failed…); "" — неизвестен.
    transient: ответа по существу нет (сеть, не-2xx, не JSON) — это не отказ,
    опрашивать дальше.
    """

    status: str = ""
    urls: list = field(default_factory=list)
    cost: Optional[float] = None
    error: str = ""
    transient: bool = False
    status_code: Optional[int] = None

    @property
    def is_ready(self) -> bool:
        """Готово и есть что скачать."""
        return self.status == VIDEO_COMPLETED and bool(self.urls)

    @property
    def is_failed(self) -> bool:
        """Провайдер окончательно отказал (денег не берёт)."""
        return self.status in VIDEO_FAILED_STATES

    @property
    def unreachable(self) -> bool:
        """401/403/404/410: работа не видна этому ключу. Пока transient, но
        вызывающий не должен ждать такого ответа часами (см. UNREACHABLE_CODES)."""
        return self.status_code in UNREACHABLE_CODES


@dataclass(frozen=True)
class ImageItem:
    b64: str
    media_type: str

    def decode(self) -> bytes:
        """Байты картинки (для нормализатора загрузок)."""
        return base64.b64decode(self.b64)


@dataclass(frozen=True)
class Images:
    """Итог POST /images.

    error: сырой текст отказа (для explain_image_error) — пусто при успехе.
    status_code: None, если HTTP-ответа не было.
    """

    items: list = field(default_factory=list)
    cost: Optional[float] = None
    error: str = ""
    status_code: Optional[int] = None

    @property
    def ok(self) -> bool:
        return bool(self.items) and not self.error


class DownloadError(RuntimeError):
    """Скачать результат не удалось.

    reason: bad_url | network | http | too_large | timeout | empty | io.
    Частичный файл к этому моменту уже удалён.
    """

    def __init__(self, reason: str, message: str = "", status_code: Optional[int] = None):
        super().__init__(message or reason)
        self.reason = reason
        self.status_code = status_code


# --- Общие помощники ---------------------------------------------------------


def _config() -> dict:
    # Ленивый импорт: handlers — большой модуль, и он сам тянет генерацию.
    from .handlers import _openrouter_config

    return _openrouter_config()


def key_fingerprint(api_key) -> str:
    """Отпечаток ключа (sha256, 16 hex): по нему находим ключ, не храня его рядом с работой."""
    key = str(api_key or "").strip()
    return hashlib.sha256(key.encode("utf-8")).hexdigest()[:16] if key else ""


def _accounts() -> list:
    """[(id, ключ, активный)] аккаунтов OpenRouter; сбой БД — пустой список."""
    try:
        from .models import OpenRouterAccount

        return list(OpenRouterAccount.objects.order_by("-is_active", "pk")
                    .values_list("pk", "api_key", "is_active"))
    except Exception:  # noqa: BLE001 — нет БД (тесты без базы, моргнула) — ищем без неё
        logger.debug("media_provider: аккаунты OpenRouter не прочитаны", exc_info=True)
        return []


def _fallback_keys() -> list:
    """Ключи вне аккаунтов — из настроек и окружения, как в handlers._openrouter_config."""
    keys = []
    try:
        from adminapi.runtime import get_runtime

        keys.append(str(get_runtime("OPENROUTER_API_KEY", "") or "").strip())
    except Exception:  # noqa: BLE001
        pass
    keys.append(str(os.environ.get("OPENROUTER_API_KEY") or "").strip())
    return [k for k in keys if k]


def current_config() -> dict:
    """Конфиг, которым сейчас уйдёт отправка, и чей это ключ.

    Кроме полей _config(): account_id (id OpenRouterAccount или None — ключ из
    настроек/окружения) и key_fp (отпечаток). Вызывающий хранит их рядом с
    адресом опроса и потом опрашивает тем же ключом (config_for).
    """
    cfg = dict(_config())
    fp = key_fingerprint(cfg.get("api_key"))
    account_id = None
    if fp:
        for pk, key, _active in _accounts():
            if key_fingerprint(key) == fp:
                account_id = pk
                break
    cfg["key_fp"] = fp
    cfg["account_id"] = account_id
    return cfg


def config_for(account_id=None, key_fp: str = "") -> dict:
    """Конфиг с ключом, которым работа была отправлена (опрос, скачивание, довоз).

    Порядок: аккаунт по id (если его ключ не меняли) → любой известный ключ с
    тем же отпечатком → текущий активный (старые записи без отметки, ключ
    удалён). В последнем случае провайдер может ответить 401/404 — это видно
    в логе, а опрос сдастся по Poll.unreachable, а не через шесть часов.
    """
    cfg = dict(_config())
    fp = str(key_fp or "")
    if not account_id and not fp:
        return cfg
    accounts = _accounts()
    if account_id:
        for pk, key, _active in accounts:
            if pk == account_id and key and (not fp or key_fingerprint(key) == fp):
                cfg["api_key"] = str(key).strip()
                return cfg
    if fp:
        for key in [k for _pk, k, _a in accounts] + _fallback_keys():
            if key and key_fingerprint(key) == fp:
                cfg["api_key"] = str(key).strip()
                return cfg
    if key_fingerprint(cfg.get("api_key")) != fp:
        logger.warning("media_provider: ключ, которым отправлена работа (аккаунт %s, отпечаток %s), "
                       "не найден — опрашиваем текущим", account_id, fp or "—")
    return cfg


def _base(cfg: dict) -> str:
    return str(cfg.get("base_url") or "").rstrip("/")


def _post_headers(cfg: dict) -> dict:
    headers = {
        "Authorization": f"Bearer {cfg.get('api_key') or ''}",
        "Content-Type": "application/json",
    }
    # Подпись приложения для OpenRouter — как у FLUX (handlers._flux_generate_image).
    if cfg.get("referer"):
        headers["HTTP-Referer"] = cfg["referer"]
    if cfg.get("title"):
        headers["X-Title"] = cfg["title"]
    return headers


def _host(url: str) -> str:
    try:
        return (urlsplit(url).hostname or "").lower()
    except ValueError:
        return ""


def _is_http(url: str) -> bool:
    try:
        return urlsplit(str(url or "")).scheme in ("http", "https")
    except ValueError:
        return False


def _bearer_allowed(url: str, cfg: dict) -> bool:
    """Ключ уходит только самому OpenRouter.

    Адрес опроса и ссылки на ролик приходят из ответа провайдера и лежат в БД;
    ключ к чужому хосту — это утечка ключа, если адрес когда-нибудь окажется
    не тем. Контент-эндпоинт OpenRouter без Bearer отвечает 401, поэтому
    к своему хосту (и к openrouter.ai, если base_url — прокси) ключ шлём.
    """
    host = _host(url)
    if not host:
        return False
    if host == _host(_base(cfg)):
        return True
    return host == "openrouter.ai" or host.endswith(".openrouter.ai")


def _get_headers(url: str, cfg: dict) -> dict:
    if _bearer_allowed(url, cfg) and cfg.get("api_key"):
        return {"Authorization": f"Bearer {cfg['api_key']}"}
    return {}


def _text(resp) -> str:
    try:
        return str(resp.text or "")[:MAX_TEXT]
    except Exception:  # noqa: BLE001 — битая кодировка тела не должна ронять разбор
        return ""


def _json(resp) -> Any:
    try:
        return resp.json()
    except Exception:  # noqa: BLE001 — requests кидает ValueError-наследников
        return None


def _cost(data: dict) -> Optional[float]:
    usage = data.get("usage")
    if not isinstance(usage, dict):
        return None
    try:
        value = usage.get("cost")
        return None if value is None else float(value)
    except (TypeError, ValueError):
        return None


def _error_text(value: Any) -> str:
    """Ошибка провайдера бывает строкой или объектом {message, code, …}."""
    if not value:
        return ""
    if isinstance(value, dict):
        msg = value.get("message") or value.get("error") or ""
        code = value.get("code")
        text = str(msg) if msg else str(value)
        if code and str(code) not in text:
            text = f"{text} (code {code})"
        return text[:MAX_TEXT]
    return str(value)[:MAX_TEXT]


# --- Видео -------------------------------------------------------------------


def submit_video(body: dict, *, timeout: Timeout = SUBMIT_TIMEOUT, cfg: Optional[dict] = None) -> Submit:
    """POST {base}/videos. Тело уходит как есть и не меняется.

    Никогда не бросает: любой сбой превращается в state=unknown (исход
    неизвестен — провайдер мог принять и взять деньги) или rejected.
    cfg — current_config() вызывающего: тот ключ, который он запомнит для опроса.
    """
    cfg = cfg or _config()
    base = _base(cfg)
    if not cfg.get("api_key"):
        # Без ключа запрос точно не будет принят — и точно не оплачен.
        logger.error("media_provider: нет ключа OpenRouter, видео не отправлено")
        return Submit(state=STATE_REJECTED, text="OpenRouter API key is not configured")
    model = str((body or {}).get("model") or "")
    try:
        resp = requests.post(f"{base}/videos", json=body, headers=_post_headers(cfg),
                             timeout=timeout)
    except Exception as exc:  # noqa: BLE001 — таймаут, сеть, DNS: исход неизвестен
        logger.error("media_provider: видео %s — нет ответа на отправку: %s", model, exc)
        return Submit(state=STATE_UNKNOWN, text=f"{type(exc).__name__}: {exc}"[:MAX_TEXT])

    code = int(resp.status_code)
    text = _text(resp)
    if code >= 500:
        # Ошибка шлюза (502/504/524): запрос мог дойти и быть принят.
        logger.error("media_provider: видео %s — http %s на отправке, исход неизвестен: %s",
                     model, code, text[:300])
        return Submit(state=STATE_UNKNOWN, status_code=code, text=text)
    if not 200 <= code < 300:
        # Провайдер отказал сам — денег за это не берёт.
        logger.warning("media_provider: видео %s — отказ http %s: %s", model, code, text[:300])
        return Submit(state=STATE_REJECTED, status_code=code, text=text)

    data = _json(resp)
    if not isinstance(data, dict):
        logger.error("media_provider: видео %s — 2xx без JSON, исход неизвестен: %s",
                     model, text[:300])
        return Submit(state=STATE_UNKNOWN, status_code=code, text=text)
    job_id = str(data.get("id") or data.get("generation_id") or "").strip()
    polling_url = str(data.get("polling_url") or "").strip()
    if not polling_url and job_id:
        # Адрес опроса не пришёл, но работа принята: строим его сами, иначе
        # потеряли бы уже оплаченный ролик.
        polling_url = f"{base}/videos/{job_id}"
    if not polling_url:
        logger.error("media_provider: видео %s — принято без id и адреса опроса: %s",
                     model, text[:300])
        return Submit(state=STATE_UNKNOWN, status_code=code, text=text)
    # След в логе ещё до того, как вызывающий запишет id в БД: если база моргнёт,
    # оплаченный ролик можно найти по этой строке.
    logger.info("media_provider: видео %s принято provider_id=%s polling_url=%s",
                model, job_id, polling_url)
    return Submit(state=STATE_ACCEPTED, job_id=job_id, polling_url=polling_url,
                  status_code=code, text=text)


def poll_video(url: str, *, timeout: Timeout = POLL_TIMEOUT, cfg: Optional[dict] = None) -> Poll:
    """Один GET по адресу опроса. Никогда не бросает.

    Сеть, не-2xx и не-JSON — transient (не отказ): провайдер мог просто
    моргнуть, а ролик уже оплачен — решать «провал» по такому ответу нельзя.
    401/403/404/410 — тоже transient, но с Poll.unreachable: вызывающий сдаётся
    после нескольких таких ответов подряд.
    cfg — config_for(...) ключа, которым работа отправлена (иначе — текущий).
    """
    if not _is_http(url):
        return Poll(transient=True, error=f"bad polling url: {str(url)[:200]}")
    cfg = cfg or _config()
    try:
        resp = requests.get(url, headers=_get_headers(url, cfg), timeout=timeout)
    except Exception as exc:  # noqa: BLE001
        logger.warning("media_provider: опрос не удался: %s", exc)
        return Poll(transient=True, error=f"{type(exc).__name__}: {exc}"[:MAX_TEXT])

    code = int(resp.status_code)
    if not 200 <= code < 300:
        text = _text(resp)
        logger.warning("media_provider: опрос http %s: %s", code, text[:300])
        return Poll(transient=True, error=text, status_code=code)
    data = _json(resp)
    if not isinstance(data, dict):
        return Poll(transient=True, error=_text(resp) or "poll: ответ не JSON", status_code=code)

    status = str(data.get("status") or "").strip().lower()
    urls = [str(u) for u in (data.get("unsigned_urls") or [])
            if isinstance(u, str) and _is_http(u)]
    return Poll(status=status, urls=urls, cost=_cost(data), error=_error_text(data.get("error")),
                transient=False, status_code=code)


def download_to_file(url: str, dest: Union[str, os.PathLike], *, max_bytes: int,
                     wall_s: float, cfg: Optional[dict] = None) -> int:
    """Потоково скачать результат в dest. Возвращает число записанных байт.

    content-endpoint OpenRouter требует Bearer (unsigned_urls без подписи),
    без заголовка — 401. timeout у requests — между чтениями, а не общий,
    поэтому общий потолок wall_s проверяем сами. При любой ошибке бросает
    DownloadError, а недокачанный файл удаляет. cfg — как у poll_video.
    """
    if not _is_http(url):
        raise DownloadError("bad_url", f"bad download url: {str(url)[:200]}")
    cfg = cfg or _config()
    deadline = time.monotonic() + float(wall_s)
    read_timeout = max(1.0, min(float(DOWNLOAD_READ_TIMEOUT), float(wall_s)))
    written = 0
    # Удаляем только то, что начали писать сами: файл вызывающего до открытия
    # (например, заранее созданный временный) не наш.
    opened = False
    try:
        try:
            resp = requests.get(url, headers=_get_headers(url, cfg), stream=True,
                                timeout=(10, read_timeout))
        except Exception as exc:  # noqa: BLE001
            raise DownloadError("network", f"download: {type(exc).__name__}: {exc}") from exc
        with resp:
            code = int(resp.status_code)
            if not 200 <= code < 300:
                raise DownloadError("http", f"download http {code}", status_code=code)
            declared = _content_length(resp)
            if declared is not None and declared > max_bytes:
                raise DownloadError("too_large",
                                    f"download: {declared} байт больше лимита {max_bytes}",
                                    status_code=code)
            try:
                with open(dest, "wb") as fh:
                    opened = True
                    for chunk in resp.iter_content(chunk_size=DOWNLOAD_CHUNK):
                        if chunk:
                            written += len(chunk)
                            if written > max_bytes:
                                raise DownloadError(
                                    "too_large", f"download: больше лимита {max_bytes} байт",
                                    status_code=code)
                            fh.write(chunk)
                        if time.monotonic() > deadline:
                            raise DownloadError("timeout",
                                                f"download: дольше {wall_s} с", status_code=code)
            except DownloadError:
                raise
            except requests.RequestException as exc:
                # Ловим до OSError: исключения requests — наследники IOError,
                # иначе обрыв сети выглядел бы как сбой записи на диск.
                raise DownloadError("network", f"download: {type(exc).__name__}: {exc}",
                                    status_code=code) from exc
            except OSError as exc:
                raise DownloadError("io", f"download: запись не удалась: {exc}",
                                    status_code=code) from exc
            except Exception as exc:  # noqa: BLE001 — обрыв посреди потока
                raise DownloadError("network", f"download: {type(exc).__name__}: {exc}",
                                    status_code=code) from exc
        if written == 0:
            raise DownloadError("empty", "download: пустой файл", status_code=code)
    except DownloadError:
        if opened:
            _remove(dest)
        raise
    return written


def _content_length(resp) -> Optional[int]:
    try:
        raw = (resp.headers or {}).get("Content-Length")
        return int(raw) if raw not in (None, "") else None
    except (TypeError, ValueError, AttributeError):
        return None


def _remove(path) -> None:
    try:
        os.remove(path)
    except FileNotFoundError:
        pass
    except OSError:
        logger.warning("media_provider: недокачанный файл не удалился: %s", path, exc_info=True)


# --- Картинки ----------------------------------------------------------------


def _media_type(value: Any) -> str:
    mt = str(value or "").split(";", 1)[0].strip().lower() or "image/png"
    return "image/jpeg" if mt == "image/jpg" else mt


def _looks_like_markup(b64: str) -> bool:
    """SVG/HTML под видом PNG: смотрим на первые байты, не декодируя всё.

    SVG — это скрипт в картинке: раздавать его с нашего /media нельзя, а
    handlers._save_generated_images сохранил бы его как .png.
    """
    head = "".join(b64[:96].split())[:64]
    head = head[: len(head) - len(head) % 4]
    if not head:
        return False
    try:
        raw = base64.b64decode(head)
    except (binascii.Error, ValueError):
        return False
    return raw.lstrip(b"\xef\xbb\xbf \t\r\n").startswith(b"<")


def _image_item(item: Any) -> Tuple[Optional[ImageItem], str]:
    """(картинка, причина отказа). Причина пуста, если элемент просто пустой."""
    if not isinstance(item, dict):
        return None, ""
    b64 = str(item.get("b64_json") or item.get("b64") or "").strip()
    media_type = item.get("media_type")
    if b64.startswith("data:"):
        # Некоторые провайдеры отдают data-URL целиком.
        header, _, b64 = b64.partition(",")
        media_type = media_type or header[5:].split(";", 1)[0]
    if not b64:
        return None, ""
    mt = _media_type(media_type)
    if "svg" in mt or not mt.startswith("image/"):
        return None, f"unsupported media_type {mt}"
    if _looks_like_markup(b64):
        return None, f"markup instead of image ({mt})"
    return ImageItem(b64=b64, media_type=mt), ""


def generate_image(body: dict, *, timeout: Timeout = IMAGE_TIMEOUT) -> Images:
    """POST {base}/images. Никогда не бросает: итог — Images с items или error.

    Ответ image/svg+xml (и разметка под видом картинки) отклоняется.
    """
    cfg = _config()
    if not cfg.get("api_key"):
        logger.error("media_provider: нет ключа OpenRouter, картинка не отправлена")
        return Images(error="OpenRouter API key is not configured")
    model = str((body or {}).get("model") or "")
    try:
        resp = requests.post(f"{_base(cfg)}/images", json=body, headers=_post_headers(cfg),
                             timeout=timeout)
    except Exception as exc:  # noqa: BLE001
        logger.error("media_provider: картинка %s — нет ответа: %s", model, exc)
        return Images(error=f"{type(exc).__name__}: {exc}"[:MAX_TEXT])

    code = int(resp.status_code)
    if not 200 <= code < 300:
        text = _text(resp)
        logger.warning("media_provider: картинка %s — http %s: %s", model, code, text[:300])
        return Images(error=text or f"http {code}", status_code=code)
    data = _json(resp)
    if not isinstance(data, dict):
        return Images(error=_text(resp) or "images: ответ не JSON", status_code=code)

    cost = _cost(data)
    items, rejected = [], []
    for raw in data.get("data") or []:
        item, why = _image_item(raw)
        if item is not None:
            items.append(item)
        elif why:
            rejected.append(why)
    if items:
        if rejected:
            logger.warning("media_provider: картинка %s — отброшено: %s", model, rejected)
        return Images(items=items, cost=cost, status_code=code)
    if rejected:
        logger.error("media_provider: картинка %s — только неподходящие форматы: %s",
                     model, rejected)
        error = "provider returned no raster image: " + "; ".join(rejected)
    else:
        error = _error_text(data.get("error")) or "images: в ответе нет изображения"
    return Images(cost=cost, error=error[:MAX_TEXT], status_code=code)
