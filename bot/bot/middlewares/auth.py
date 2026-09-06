"""Middleware: узнаём человека до того, как до него доберётся обработчик."""
from __future__ import annotations

import logging
from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, Message, TelegramObject, Update

from bot.config import settings
from bot.services.api import ApiError, api
from bot.services.state import store
from bot.texts import t

logger = logging.getLogger(__name__)


def _tg_user_dict(user) -> dict:
    return {
        "id": user.id,
        "first_name": user.first_name or "",
        "last_name": user.last_name or "",
        "username": user.username or "",
        "language_code": user.language_code or "",
        "is_premium": bool(getattr(user, "is_premium", False)),
    }


class DedupMiddleware(BaseMiddleware):
    """Один и тот же апдейт обрабатываем один раз.

    После перезапуска Telegram присылает необработанные апдейты заново — без
    этой проверки человек получил бы второй ответ и второе списание.
    """

    async def __call__(self, handler, event: TelegramObject, data: dict) -> Any:
        update: Update | None = data.get("event_update")
        if update is not None and await store.seen_update(update.update_id):
            logger.info("апдейт %s уже обработан, пропускаем", update.update_id)
            return None
        return await handler(event, data)


class AuthMiddleware(BaseMiddleware):
    """Токен человека и его язык — в каждый обработчик.

    Токен кэшируется: обменивать данные Telegram на него при каждом сообщении
    незачем. Если токен протух, молча берём новый — человек этого не замечает.
    """

    async def __call__(self, handler: Callable[[TelegramObject, dict], Awaitable[Any]],
                       event: TelegramObject, data: dict) -> Any:
        user = data.get("event_from_user")
        if user is None or user.is_bot:
            return None

        if not settings.allowed(user.id):
            lang = user.language_code or "ru"
            lang = "ru" if lang.startswith("ru") else ("kg" if lang.startswith("ky") else "en")
            await self._reply(event, t(lang, "not_allowed"))
            return None

        lang = await store.get(user.id, "lang") or None
        token = await store.get_token(user.id)
        if not token:
            try:
                payload = await api.auth_telegram(
                    _tg_user_dict(user),
                    chat_id=self._chat_id(event) or user.id,
                    ref=data.get("ref") or "",
                )
            except ApiError as exc:
                if exc.status == 403:
                    await self._reply(event, t(lang or "ru", "blocked"))
                    return None
                logger.exception("не удалось получить токен для %s", user.id)
                await self._reply(event, t(lang or "ru", "server_down"))
                return None
            token = payload["access"]
            await store.set_token(user.id, token)
            data["auth_payload"] = payload
            if not lang:
                lang = (payload.get("user") or {}).get("lang") or "ru"
                await store.set(user.id, "lang", lang)

        data["token"] = token
        data["lang"] = lang or "ru"
        data["tg_user"] = _tg_user_dict(user)
        return await handler(event, data)

    @staticmethod
    def _chat_id(event: TelegramObject) -> int | None:
        if isinstance(event, Message):
            return event.chat.id
        if isinstance(event, CallbackQuery) and event.message:
            return event.message.chat.id
        return None

    @staticmethod
    async def _reply(event: TelegramObject, text: str) -> None:
        try:
            if isinstance(event, Message):
                await event.answer(text)
            elif isinstance(event, CallbackQuery):
                await event.answer(text, show_alert=True)
        except Exception:
            logger.exception("не удалось ответить пользователю")


class ErrorsMiddleware(BaseMiddleware):
    """Ни одна ошибка не должна выглядеть как молчание бота."""

    async def __call__(self, handler, event: TelegramObject, data: dict) -> Any:
        try:
            return await handler(event, data)
        except ApiError:
            raise
        except Exception:
            logger.exception("обработчик упал")
            lang = data.get("lang", "ru")
            if isinstance(event, Message):
                try:
                    await event.answer(t(lang, "failed"))
                except Exception:
                    pass
            return None
