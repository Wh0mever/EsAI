# -*- coding: utf-8 -*-
"""Имитатор Telegram и сервера для сквозных проверок бота.

Юнит-тесты вызывают обработчики по одному и подменяют всё вокруг, поэтому не
видят ошибок связки: порядок роутеров, внедрение аргументов aiogram, middleware,
состояния мастеров. Здесь через НАСТОЯЩИЙ Dispatcher проходят настоящие апдейты,
а Telegram изображает объект, который проверяет то, на чём бот падал в проде:

  * разметка HTML принимается по правилам Telegram (одна «<» — и сообщение отвергнуто);
  * длины: текст 4096, подпись 1024, callback_data 64 байта, медиа-группа 2..10;
  * правка сообщения тем же текстом — ошибка «message is not modified»;
  * счёт Stars: заголовок ≤ 32, описание ≤ 255, ровно одна цена.

Сервер изображает httpx.MockTransport с правдоподобными ответами и записывает
все обращения — по ним тесты проверяют, что ушло в API (stateless, пропорции,
ровно один платный запуск и т.д.).
"""
from __future__ import annotations

import html as html_lib
import json
import re
import time
from datetime import datetime, timezone
from typing import Any

import httpx
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.client.session.base import BaseSession
from aiogram.exceptions import TelegramBadRequest
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.methods import (
    AnswerCallbackQuery,
    AnswerPreCheckoutQuery,
    DeleteMessage,
    DeleteWebhook,
    EditMessageReplyMarkup,
    EditMessageText,
    GetFile,
    GetMe,
    SendChatAction,
    SendDocument,
    SendInvoice,
    SendMediaGroup,
    SendMessage,
    SendPhoto,
    SendVideo,
    SetMyCommands,
    SetMyDescription,
    SetMyShortDescription,
    TelegramMethod,
)
from aiogram.types import (
    CallbackQuery,
    Chat,
    File,
    Message,
    MessageEntity,
    PreCheckoutQuery,
    Update,
    User,
    Voice,
)

# Заведомо выдуманные id и имена: репозиторий открытый.
UID = 123456789
BOT_ID = 987654321
BOT_USERNAME = "esai_test_bot"
MAX_TEXT = 4096
MAX_CAPTION = 1024

ALLOWED_TAGS = {"b", "strong", "i", "em", "u", "ins", "s", "strike", "del", "a", "code", "pre",
                "blockquote", "tg-spoiler", "span", "tg-emoji"}
_TAG_RE = re.compile(r"<(/?)([a-zA-Z][\w-]*)((?:\s+[\w-]+(?:=(?:\"[^\"]*\"|'[^']*'|[^\s>]*))?)*)\s*>|<")


class HtmlError(ValueError):
    pass


def validate_html(text: str) -> str:
    """Разбор по правилам Telegram. Возвращает текст без тегов, иначе HtmlError."""
    stack: list[str] = []
    out: list[str] = []
    pos = 0
    for match in _TAG_RE.finditer(text):
        out.append(text[pos:match.start()])
        pos = match.end()
        if match.group(0) == "<":
            raise HtmlError(f"Can't parse entities: лишний символ '<' на позиции {match.start()}")
        closing, name, attrs = match.group(1), match.group(2).lower(), match.group(3) or ""
        if name not in ALLOWED_TAGS:
            raise HtmlError(f"Can't parse entities: неизвестный тег <{name}>")
        if closing:
            if not stack or stack[-1] != name:
                raise HtmlError(f"Can't parse entities: закрывающий </{name}> не на месте (стек {stack})")
            stack.pop()
        else:
            if name == "a" and "href" not in attrs:
                raise HtmlError("Can't parse entities: <a> без href")
            stack.append(name)
    out.append(text[pos:])
    if stack:
        raise HtmlError(f"Can't parse entities: не закрыты теги {stack}")
    return html_lib.unescape("".join(out))


# ------------------------------------------------------------------ Redis ---

class FakeRedis:
    """Ровно те команды, что использует services/state.Store."""

    def __init__(self):
        self.kv: dict[str, str] = {}
        self.lists: dict[str, list[str]] = {}
        self.expire_at: dict[str, float] = {}

    def _alive(self, key: str) -> bool:
        until = self.expire_at.get(key)
        if until is not None and until <= time.monotonic():
            self.kv.pop(key, None)
            self.lists.pop(key, None)
            self.expire_at.pop(key, None)
            return False
        return key in self.kv or key in self.lists

    async def get(self, key):
        return self.kv.get(key) if self._alive(key) else None

    async def set(self, key, value, ex=None, px=None, nx=False):
        if nx and self._alive(key):
            return None
        self.kv[key] = str(value)
        if ex:
            self.expire_at[key] = time.monotonic() + ex
        elif px:
            self.expire_at[key] = time.monotonic() + px / 1000
        else:
            self.expire_at.pop(key, None)
        return True

    async def delete(self, *keys):
        n = 0
        for key in keys:
            n += int(self._alive(key))
            self.kv.pop(key, None)
            self.lists.pop(key, None)
            self.expire_at.pop(key, None)
        return n

    async def pexpire(self, key, ms):
        if self._alive(key):
            self.expire_at[key] = time.monotonic() + ms / 1000
        return True

    async def rpush(self, key, value):
        self.lists.setdefault(key, []).append(value)
        return len(self.lists[key])

    async def lpop(self, key):
        items = self.lists.get(key) or []
        return items.pop(0) if items else None

    async def llen(self, key):
        return len(self.lists.get(key) or [])

    async def rpoplpush(self, src, dst):
        items = self.lists.get(src) or []
        if not items:
            return None
        value = items.pop()
        self.lists.setdefault(dst, []).insert(0, value)
        return value

    async def lrem(self, key, count, value):
        items = self.lists.get(key) or []
        if value in items:
            items.remove(value)
            return 1
        return 0

    async def aclose(self):
        return None


# --------------------------------------------------------------- Telegram ---

class SentRecord:
    """Что бот отправил или правил — для проверок в тестах."""

    def __init__(self, kind: str, chat_id: int, message_id: int, text: str = "", markup=None,
                 parse_mode: str | None = None, extra: dict | None = None):
        self.kind = kind
        self.chat_id = chat_id
        self.message_id = message_id
        self.text = text
        self.markup = markup
        self.parse_mode = parse_mode
        self.extra = extra or {}

    def buttons(self) -> list:
        markup = self.markup
        if markup is None:
            return []
        rows = getattr(markup, "inline_keyboard", None) or getattr(markup, "keyboard", None) or []
        return [b for row in rows for b in row]

    def button(self, needle: str):
        for b in self.buttons():
            if needle in (getattr(b, "text", "") or ""):
                return b
        return None

    def __repr__(self):
        return f"<{self.kind} #{self.message_id} {self.text[:60]!r}>"


class TelegramSim(BaseSession):
    """Сессия aiogram, которая ведёт себя как Bot API с его придирками."""

    def __init__(self):
        super().__init__()
        self.sent: list[SentRecord] = []
        self.log: list[tuple[str, dict]] = []
        self.answers: list[tuple[str, dict]] = []
        self.messages: dict[tuple[int, int], SentRecord] = {}
        self.deleted: set[tuple[int, int]] = set()
        self._next_id = 5000
        self.fail_next: dict[str, Exception] = {}
        self.pre_checkout: list[dict] = []
        self.files: dict[str, bytes] = {}

    async def close(self) -> None:
        return None

    async def stream_content(self, url, headers=None, timeout=30, chunk_size=65536, raise_for_status=True):
        name = url.rsplit("/", 1)[-1]
        yield self.files.get(name, b"x" * 2048)

    # ---- проверки ----
    def _check_markup(self, markup) -> None:
        if markup is None:
            return
        rows = getattr(markup, "inline_keyboard", None)
        if rows is not None:
            for row in rows:
                for b in row:
                    if not (b.text or "").strip():
                        raise TelegramBadRequest(None, "Bad Request: text buttons are unallowed / empty button text")
                    if b.callback_data is not None and len(b.callback_data.encode()) > 64:
                        raise TelegramBadRequest(None, f"Bad Request: BUTTON_DATA_INVALID ({b.callback_data!r} > 64 байт)")
                    if b.url and not re.match(r"^(https?|tg)://", b.url):
                        raise TelegramBadRequest(None, f"Bad Request: wrong url {b.url!r}")
                    if b.web_app and not b.web_app.url.startswith("https://"):
                        raise TelegramBadRequest(None, "Bad Request: web_app url must be https")
                    if not (b.callback_data or b.url or b.web_app or b.switch_inline_query is not None
                            or b.switch_inline_query_current_chat is not None or b.pay):
                        raise TelegramBadRequest(None, "Bad Request: inline button must have an action")

    def _check_text(self, text: str | None, parse_mode, limit: int, what: str) -> str:
        if text is None:
            return ""
        mode = parse_mode
        if mode is not None and str(getattr(mode, "value", mode)).upper() == "HTML":
            try:
                plain = validate_html(text)
            except HtmlError as exc:
                raise TelegramBadRequest(None, f"Bad Request: {exc}")
        else:
            plain = text
        if len(plain) > limit:
            raise TelegramBadRequest(None, f"Bad Request: {what} is too long ({len(plain)} > {limit})")
        if not plain.strip() and what == "message text":
            raise TelegramBadRequest(None, "Bad Request: message text is empty")
        return plain

    def _mode(self, bot: Bot, method: TelegramMethod) -> Any:
        mode = getattr(method, "parse_mode", None)
        # Default(...) означает «взять из настроек бота» (там HTML).
        if mode is not None and mode.__class__.__name__ == "Default":
            return bot.default.parse_mode
        return mode

    def _new_message(self, bot: Bot, chat_id, text=None, caption=None, **kw) -> Message:
        self._next_id += 1
        return Message(
            message_id=self._next_id,
            date=datetime.now(timezone.utc),
            chat=Chat(id=int(chat_id), type="private"),
            from_user=User(id=BOT_ID, is_bot=True, first_name="EsAI", username=BOT_USERNAME),
            text=text, caption=caption,
        )

    async def make_request(self, bot: Bot, method: TelegramMethod, timeout: int | None = None):
        name = type(method).__name__
        self.log.append((name, method.model_dump(exclude_none=True, exclude={"reply_markup"}) if False else {}))
        if name in self.fail_next:
            raise self.fail_next.pop(name)

        if isinstance(method, GetMe):
            return User(id=BOT_ID, is_bot=True, first_name="EsAI", username=BOT_USERNAME)
        if isinstance(method, (SendChatAction, DeleteWebhook, SetMyCommands, SetMyDescription,
                               SetMyShortDescription)):
            return True
        if isinstance(method, AnswerCallbackQuery):
            if method.text and len(method.text) > 200:
                raise TelegramBadRequest(method, "Bad Request: MESSAGE_TOO_LONG в ответе на нажатие (> 200)")
            self.answers.append(("callback", {"text": method.text, "alert": method.show_alert}))
            return True
        if isinstance(method, AnswerPreCheckoutQuery):
            self.pre_checkout.append({"ok": method.ok, "error": method.error_message})
            return True
        if isinstance(method, DeleteMessage):
            self.deleted.add((int(method.chat_id), int(method.message_id)))
            return True
        if isinstance(method, GetFile):
            return File(file_id=method.file_id, file_unique_id="u", file_size=2048,
                        file_path=f"files/{method.file_id}")

        mode = self._mode(bot, method)

        if isinstance(method, SendMessage):
            self._check_markup(method.reply_markup)
            plain = self._check_text(method.text, mode, MAX_TEXT, "message text")
            msg = self._new_message(bot, method.chat_id, text=plain)
            self._record("text", method, msg, method.text, mode)
            return msg
        if isinstance(method, EditMessageText):
            self._check_markup(method.reply_markup)
            plain = self._check_text(method.text, mode, MAX_TEXT, "message text")
            key = (int(method.chat_id), int(method.message_id))
            old = self.messages.get(key)
            if old is not None and old.text == method.text and \
                    self._same_markup(old.markup, method.reply_markup):
                raise TelegramBadRequest(method, "Bad Request: message is not modified")
            rec = SentRecord("edit", key[0], key[1], method.text, method.reply_markup, str(mode), {})
            self.messages[key] = rec
            self.sent.append(rec)
            return self._new_message(bot, method.chat_id, text=plain)
        if isinstance(method, EditMessageReplyMarkup):
            self._check_markup(method.reply_markup)
            key = (int(method.chat_id), int(method.message_id))
            old = self.messages.get(key)
            if old is not None and self._same_markup(old.markup, method.reply_markup):
                raise TelegramBadRequest(method, "Bad Request: message is not modified")
            if old is not None:
                old.markup = method.reply_markup
            return True
        if isinstance(method, (SendPhoto, SendVideo, SendDocument)):
            self._check_markup(method.reply_markup)
            caption = getattr(method, "caption", None)
            plain = self._check_text(caption, mode, MAX_CAPTION, "caption")
            kind = {"SendPhoto": "photo", "SendVideo": "video", "SendDocument": "document"}[name]
            msg = self._new_message(bot, method.chat_id, caption=plain)
            media = getattr(method, kind if kind != "document" else "document", None)
            self._record(kind, method, msg, caption or "", mode, {"media": str(media)[:200]})
            return msg
        if isinstance(method, SendMediaGroup):
            n = len(method.media)
            if n < 2 or n > 10:
                raise TelegramBadRequest(method, f"Bad Request: media group must have 2..10 items (получено {n})")
            out = []
            for item in method.media:
                msg = self._new_message(bot, method.chat_id)
                self._record("media", method, msg, getattr(item, "caption", "") or "", mode)
                out.append(msg)
            return out
        if isinstance(method, SendInvoice):
            self._check_markup(method.reply_markup)
            if len(method.title) > 32:
                raise TelegramBadRequest(method, "Bad Request: title is too long (max 32)")
            if len(method.description) > 255:
                raise TelegramBadRequest(method, "Bad Request: description is too long (max 255)")
            if len(method.payload.encode()) > 128:
                raise TelegramBadRequest(method, "Bad Request: payload is too long (max 128 bytes)")
            if method.currency != "XTR" or len(method.prices) != 1:
                raise TelegramBadRequest(method, "Bad Request: Stars invoice needs XTR and exactly one price")
            msg = self._new_message(bot, method.chat_id, text=method.title)
            self._record("invoice", method, msg, method.title, None,
                         {"payload": method.payload, "prices": method.prices})
            return msg
        return True

    @staticmethod
    def _same_markup(a, b) -> bool:
        def norm(m):
            return json.dumps(m.model_dump(exclude_none=True), sort_keys=True, default=str) if m else ""
        return norm(a) == norm(b)

    def _record(self, kind, method, msg, text, mode, extra=None):
        rec = SentRecord(kind, msg.chat.id, msg.message_id, text, getattr(method, "reply_markup", None),
                         str(mode), extra)
        self.sent.append(rec)
        self.messages[(msg.chat.id, msg.message_id)] = rec


# ---------------------------------------------------------------- сервер ---

def sse(*frames: dict) -> bytes:
    return "".join(f"data: {json.dumps(f, ensure_ascii=False)}\n\n" for f in frames).encode()


DEFAULT_MODELS = [
    {"id": 1, "name": "Gemini Flash", "openrouter_id": "google/gemini-2.5-flash", "category": "chat",
     "markup_coefficient": 1, "free_tier": True, "locked": False, "supports_vision": True, "recommended": True},
    {"id": 2, "name": "GPT-5", "openrouter_id": "openai/gpt-5", "category": "chat",
     "markup_coefficient": 6, "locked": False, "supports_vision": True},
    {"id": 3, "name": "Nano Banana", "openrouter_id": "google/gemini-2.5-flash-image", "category": "image",
     "markup_coefficient": 4, "locked": False, "supports_vision": True},
    {"id": 4, "name": "FLUX Pro", "openrouter_id": "black-forest-labs/flux.2-pro", "category": "image",
     "markup_coefficient": 4, "locked": False, "supports_vision": False},
    {"id": 5, "name": "Seedance", "openrouter_id": "bytedance/seedance-2.0", "category": "video",
     "markup_coefficient": 32, "locked": False, "supports_vision": False},
]


class FakeBackend:
    """Сервер EsAI: ответы по контракту, запись всех обращений."""

    def __init__(self):
        self.calls: list[dict] = []
        self.balance = 116
        self.tier = "paid"
        self.models = [dict(m) for m in DEFAULT_MODELS]
        self.chat_reply = "Привет! Чем помочь?"
        self.image_url = "/media/ai_images/test.png"
        self.jobs: dict[str, dict] = {}
        self.overrides: dict[tuple[str, str], Any] = {}  # (METHOD, path) -> (status, json) или callable

    # ---- служебное ----
    def requests(self, method: str | None = None, path: str | None = None) -> list[dict]:
        return [c for c in self.calls
                if (method is None or c["method"] == method) and (path is None or c["path"].startswith(path))]

    def body_of(self, path: str) -> dict:
        found = self.requests("POST", path)
        return found[-1]["json"] if found else {}

    async def handle(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        body: Any = None
        raw = request.content or b""
        if raw and "json" in (request.headers.get("content-type") or ""):
            try:
                body = json.loads(raw)
            except ValueError:
                body = None
        self.calls.append({"method": request.method, "path": path, "json": body or {},
                           "query": dict(request.url.params), "headers": dict(request.headers)})
        key = (request.method, path)
        if key in self.overrides:
            value = self.overrides[key]
            if callable(value):
                value = value(request, body)
            status, payload = value
            return httpx.Response(status, json=payload)
        return self.route(request.method, path, body or {}, request)

    def route(self, method, path, body, request) -> httpx.Response:
        ok = lambda data, status=200: httpx.Response(status, json=data)  # noqa: E731
        if path == "/api/bot/auth/telegram/":
            return ok({"access": "tok", "expires_in": 43200, "created": False,
                       "user": {"id": 1, "balance_tokens": self.balance, "tier": self.tier,
                                "is_paid": self.tier == "paid", "lang": "ru", "telegram_id": UID}})
        if path == "/api/bot/prefs/":
            return ok({"ok": True, "lang": "ru", "notify_bonus": True, "notify_ready": True,
                       "notify_topup": True, "notify_referral": True, "notify_marketing": False})
        if path in ("/api/bot/blocked/", "/api/bot/delete/"):
            return ok({"ok": True})
        if path == "/api/plans/balance/":
            return ok({"balance_tokens": self.balance, "tier": self.tier, "is_paid": self.tier == "paid"})
        if path == "/api/plans/bonus-settings/":
            return ok({"welcome_bonus": 150, "daily_free_credits": 20})
        if path == "/api/ai/models/":
            return ok(self.models)
        if path == "/api/plans/packages/":
            return ok([{"id": 1, "name": "Старт", "tokens": 150, "bonus_tokens": 0, "price": "190.00",
                        "currency": "KGS", "description": "Попробуйте EsAI", "badge": "", "featured": False,
                        "stars_price": 170, "stars_bonus_tokens": 0},
                       {"id": 3, "name": "Про", "tokens": 500, "bonus_tokens": 0, "price": "490.00",
                        "currency": "KGS", "description": "Для работы", "badge": "Хит", "featured": True,
                        "stars_price": 435, "stars_bonus_tokens": 0}])
        if path == "/api/plans/packages/value/":
            return ok({"packages": [{"id": 1, "name": "Старт", "tokens": 150, "bonus_tokens": 0,
                                     "value": {"text": {"count": 75}, "image": {"count": 24},
                                               "video": {"count": 2}, "document": {"count": 150}}}]})
        if path == "/api/plans/transactions/":
            return ok([{"id": 1, "delta": -1, "reason": "chat", "balance_after": 115, "created_at": "2026-09-30T10:00:00Z",
                        "meta": {"model": "google/gemini-2.5-flash"}}])
        if path == "/api/ai/sessions/":
            return ok([{"id": 7, "uid": "abc", "title": "Первый чат", "chat_mode": "text-chat"}])
        if path == "/api/ai/chat/":
            return self.chat(body)
        if path == "/api/ai/video-params/":
            return ok({"model": request.url.params.get("model"), "durations": [4, 6, 8], "default_duration": 4,
                       "resolutions": ["720p", "1080p"], "default_resolution": "720p",
                       "aspect_ratios": ["16:9", "9:16"], "credits_per_second": 32})
        if path == "/api/ai/jobs/" and method == "POST":
            uid = f"job{len(self.jobs) + 1:028d}"
            self.jobs[uid] = {"job_id": uid, "status": "queued", "need_credits": 128}
            return ok({**self.jobs[uid], "session": {"id": 9, "uid": "vid", "title": "Видео"},
                       "duration": 4, "eta_seconds": 150}, 202)
        if path.startswith("/api/ai/jobs/") and method == "GET":
            uid = path.strip("/").split("/")[-1]
            job = self.jobs.get(uid) or {"job_id": uid, "status": "queued"}
            return ok({**job, "progress": "processing", "notified": False, "result": None})
        if path == "/api/cartoon/presets/":
            return ok({"categories": [{"slug": "city", "title": "Город", "emoji": "🏙"}],
                       "presets": [{"id": 1, "slug": "walk", "title": "Прогулка", "subtitle": "", "credits": 90,
                                    "duration": 5, "category": "city", "audience": "all", "is_pick": True,
                                    "preview_poster": "/media/p.jpg", "preview_video": "/media/p.mp4"}],
                       "popular": []})
        if path == "/api/cartoon/pricing/":
            return ok({"character": 4, "scene_min": 88, "scene_typical": 109, "scene_max": 109, "assembly": 0})
        if path == "/api/cartoon/characters/":
            return ok([{"id": 39, "name": "Молодая мама", "image": "/media/c.jpg", "source": "library",
                        "is_mine": False, "category": "", "audience": "all"}])
        if path == "/api/cartoon/projects/":
            return ok([])
        if path == "/api/users/profile/":
            return ok({"user": {"id": 1, "email": f"telegram_{UID}@social.esai.local",
                                "first_name": "Тест", "username": "user"}})
        if path == "/api/users/referral/stats/":
            return ok({"referral_uid": "AB12CD34", "link": "https://esai.kg/auth/signup?ref=AB12CD34",
                       "telegram_link": f"https://t.me/{BOT_USERNAME}?start=ref_AB12CD34",
                       "invited_count": 3, "total_earned": 120, "percent": 10, "history": []})
        if path in ("/api/users/notifications/", "/api/users/transfers/"):
            return ok([])
        if path == "/api/users/memory/":
            return ok({"memory_enabled": True, "items": []})
        if path == "/api/content/articles/":
            return ok([{"slug": "post", "title_ru": "Статья", "title_en": "Post", "title_kg": "Макала"}])
        return ok({"detail": f"not found in fake: {method} {path}"}, 404)

    def chat(self, body: dict) -> httpx.Response:
        model = body.get("model") or ""
        message = body.get("message") or ""
        wants_image = "image" in model.split("/")[-1]
        headers = {"content-type": "text/event-stream"}
        if wants_image:
            frames = [{"image_pending": True},
                      {"done": True, "session": {"id": 11, "uid": "img", "title": message[:40]},
                       "message": {"id": 1, "role": "assistant", "content": "Готово — изображение сгенерировано ✨",
                                   "attachments": [{"type": "image", "url": self.image_url, "name": "i.png"}],
                                   "meta": {"model": model}},
                       "tokens_charged": 6, "balance_tokens": self.balance - 6}]
        else:
            frames = [{"delta": self.chat_reply[:6]}, {"delta": self.chat_reply[6:]},
                      {"done": True, "session": {"id": 10, "uid": "chat", "title": message[:40]},
                       "message": {"id": 2, "role": "assistant", "content": self.chat_reply, "attachments": [],
                                   "meta": {"model": model}},
                       "tokens_charged": 1, "balance_tokens": self.balance - 1}]
        return httpx.Response(200, content=sse(*frames), headers=headers)


# ------------------------------------------------------------------ стенд ---

class Harness:
    """Собирает бота целиком: Dispatcher, память, «сервер», «Telegram»."""

    def __init__(self, uid: int = UID, lang: str = "ru"):
        self.uid = uid
        self.lang = lang
        self.sim = TelegramSim()
        self.backend = FakeBackend()
        self.bot: Bot | None = None
        self.dp: Dispatcher | None = None
        self._update_id = 100
        self._msg_id = 1

    async def start(self, monkeypatch) -> "Harness":
        import bot.__main__ as main
        from bot.config import settings
        from bot.services import api as api_module
        from bot.services import state as state_module

        monkeypatch.setattr(settings, "access", "all")
        monkeypatch.setattr(settings, "service_secret", "test-secret")
        monkeypatch.setattr(settings, "bot_token", f"{BOT_ID}:TEST")
        monkeypatch.setattr(settings, "bot_username", BOT_USERNAME)

        redis = FakeRedis()
        monkeypatch.setattr(state_module.store, "_redis", redis)
        self.redis = redis

        client = httpx.AsyncClient(base_url="http://core:8000",
                                   transport=httpx.MockTransport(self.backend.handle))
        monkeypatch.setattr(api_module.api, "_client", client)
        self._client = client

        class _Memory:
            @staticmethod
            def from_url(*a, **k):
                return MemoryStorage()

        monkeypatch.setattr(main, "RedisStorage", _Memory)
        self._detach_routers(main)
        self.dp = main.build_dispatcher()
        self.bot = Bot(f"{BOT_ID}:TEST", session=self.sim,
                       default=DefaultBotProperties(parse_mode=ParseMode.HTML))
        return self

    @staticmethod
    def _detach_routers(main) -> None:
        """Роутеры бота — глобальные объекты, а aiogram пускает их лишь в один
        Dispatcher. Каждому тесту нужен свежий Dispatcher, поэтому отвязываем."""
        import importlib
        import pkgutil

        import bot.routers as routers_pkg

        seen = [getattr(main, "system_router", None)]
        for info in pkgutil.iter_modules(routers_pkg.__path__):
            module = importlib.import_module(f"bot.routers.{info.name}")
            seen.append(getattr(module, "router", None))
        for router in seen:
            if router is not None:
                router._parent_router = None

    async def stop(self):
        await self._client.aclose()

    # ---- апдейты ----
    def _user(self) -> User:
        return User(id=self.uid, is_bot=False, first_name="Тест", username="test_user", language_code=self.lang)

    def _next(self) -> int:
        self._update_id += 1
        return self._update_id

    async def say(self, text: str) -> list[SentRecord]:
        """Человек пишет боту. Возвращает всё, что бот отправил в ответ."""
        start = len(self.sim.sent)
        self._msg_id += 1
        entities = None
        if text.startswith("/"):
            cmd = text.split()[0]
            entities = [MessageEntity(type="bot_command", offset=0, length=len(cmd))]
        message = Message(message_id=self._msg_id, date=datetime.now(timezone.utc),
                          chat=Chat(id=self.uid, type="private"), from_user=self._user(),
                          text=text, entities=entities)
        await self.dp.feed_update(self.bot, Update(update_id=self._next(), message=message))
        return self.sim.sent[start:]

    async def send_photo(self, caption: str | None = None) -> list[SentRecord]:
        from aiogram.types import PhotoSize

        start = len(self.sim.sent)
        self._msg_id += 1
        message = Message(message_id=self._msg_id, date=datetime.now(timezone.utc),
                          chat=Chat(id=self.uid, type="private"), from_user=self._user(),
                          photo=[PhotoSize(file_id="ph1", file_unique_id="u", width=800, height=600, file_size=2048)],
                          caption=caption)
        await self.dp.feed_update(self.bot, Update(update_id=self._next(), message=message))
        return self.sim.sent[start:]

    async def send_voice(self, seconds: int = 3) -> list[SentRecord]:
        start = len(self.sim.sent)
        self._msg_id += 1
        message = Message(message_id=self._msg_id, date=datetime.now(timezone.utc),
                          chat=Chat(id=self.uid, type="private"), from_user=self._user(),
                          voice=Voice(file_id="v1", file_unique_id="u", duration=seconds, mime_type="audio/ogg",
                                      file_size=4096))
        await self.dp.feed_update(self.bot, Update(update_id=self._next(), message=message))
        return self.sim.sent[start:]

    async def press(self, record: SentRecord, needle: str) -> list[SentRecord]:
        """Нажать инлайн-кнопку сообщения по фрагменту подписи."""
        button = record.button(needle)
        assert button is not None, f"нет кнопки «{needle}» у {record!r}; есть {[b.text for b in record.buttons()]}"
        assert button.callback_data, f"у кнопки «{button.text}» нет callback_data (url/web_app)"
        return await self.tap_data(record, button.callback_data)

    async def tap_data(self, record: SentRecord, data: str) -> list[SentRecord]:
        start = len(self.sim.sent)
        origin = Message(message_id=record.message_id, date=datetime.now(timezone.utc),
                         chat=Chat(id=record.chat_id, type="private"),
                         from_user=User(id=BOT_ID, is_bot=True, first_name="EsAI"),
                         text=record.text or None)
        query = CallbackQuery(id=str(self._next()), from_user=self._user(), chat_instance="ci",
                              message=origin, data=data)
        await self.dp.feed_update(self.bot, Update(update_id=self._next(), callback_query=query))
        return self.sim.sent[start:]

    async def pre_checkout(self, payload: str, amount: int) -> None:
        query = PreCheckoutQuery(id=str(self._next()), from_user=self._user(), currency="XTR",
                                 total_amount=amount, invoice_payload=payload)
        await self.dp.feed_update(self.bot, Update(update_id=self._next(), pre_checkout_query=query))

    # ---- удобства ----
    def texts(self, records: list[SentRecord]) -> str:
        return "\n".join(r.text for r in records if r.text)

    def last(self, kind: str | None = None) -> SentRecord:
        for rec in reversed(self.sim.sent):
            if kind is None or rec.kind == kind:
                return rec
        raise AssertionError(f"нет сообщений вида {kind}")
