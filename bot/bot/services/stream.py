"""Показ ответа модели по мере его появления.

Telegram разрешает править сообщение примерно раз в секунду на чат. Если
править на каждое слово — половина правок вернётся отказом, и человек увидит
рывки. Поэтому копим текст и обновляем сообщение размеренно, а в конце
отправляем чистовой вариант с разметкой.
"""
from __future__ import annotations

import asyncio
import logging
import time

from aiogram.exceptions import TelegramBadRequest, TelegramRetryAfter
from aiogram.types import Message

from bot.services.tg_format import CHUNK_LIMIT, plain, split_html, to_html

logger = logging.getLogger(__name__)

# Как часто трогаем сообщение и насколько заметным должен быть прирост.
EDIT_INTERVAL = 1.2
MIN_GROWTH = 90
CURSOR = "▌"


class StreamRenderer:
    """Одно живое сообщение, которое растёт вместе с ответом."""

    def __init__(self, message: Message, placeholder: str = "🤔"):
        self.origin = message
        self.placeholder = placeholder
        self.buffer = ""
        self.live: Message | None = None
        self._sent_len = 0
        self._last_edit = 0.0
        self._retry_until = 0.0

    async def start(self) -> None:
        self.live = await self.origin.answer(self.placeholder)

    async def push(self, delta: str) -> None:
        """Добавить кусок ответа и, если пора, обновить сообщение."""
        if not delta:
            return
        self.buffer += delta
        now = time.monotonic()
        if now < self._retry_until:
            return
        if now - self._last_edit < EDIT_INTERVAL:
            return
        if len(self.buffer) - self._sent_len < MIN_GROWTH:
            return
        # Пока текст растёт, показываем его без разметки: незакрытые теги
        # Telegram не принимает, а закрывать их на каждом шаге — лишняя работа.
        await self._edit(self.buffer[-CHUNK_LIMIT:] + CURSOR, parse_mode=None)
        self._last_edit = now
        self._sent_len = len(self.buffer)

    async def _edit(self, text: str, parse_mode: str | None = None) -> None:
        if self.live is None:
            return
        try:
            await self.live.edit_text(text, parse_mode=parse_mode,
                                      link_preview_options=None)
        except TelegramRetryAfter as exc:
            # Слишком часто — молчим указанное время, текст всё равно копится.
            self._retry_until = time.monotonic() + exc.retry_after
        except TelegramBadRequest as exc:
            if "message is not modified" in str(exc).lower():
                return
            logger.debug("правка не прошла: %s", exc)

    async def finish(self, text: str, *, reply_markup=None, footer: str = "") -> Message | None:
        """Выложить готовый ответ: с разметкой и, если нужно, несколькими частями."""
        body = to_html(text or self.buffer)
        if footer:
            body = f"{body}\n\n<i>{footer}</i>" if body else f"<i>{footer}</i>"
        parts = split_html(body) or [self.placeholder]

        last: Message | None = None
        for index, part in enumerate(parts):
            markup = reply_markup if index == len(parts) - 1 else None
            try:
                if index == 0 and self.live is not None:
                    last = await self._replace(self.live, part, markup)
                else:
                    last = await self._send(part, markup)
            except Exception as exc:
                # Кредиты бэкенд списал ещё до кадра done. Если исключение уйдёт
                # наружу, человек увидит «Кредиты не списаны» поверх оплаченного
                # ответа — поэтому теряем оформление, но не сообщение.
                logger.warning("часть ответа не ушла (%s из %s): %s",
                               index + 1, len(parts), exc)
                last = await self._last_resort(part, markup) or last
        return last

    async def _last_resort(self, text: str, markup) -> Message | None:
        """Последняя попытка: обрезанный текст без разметки, ошибки не поднимаем."""
        try:
            return await self.origin.answer((plain(text) or self.placeholder)[:CHUNK_LIMIT],
                                            parse_mode=None, reply_markup=markup)
        except Exception as exc:
            logger.warning("ответ не доставлен вовсе: %s", exc)
            return None

    async def _replace(self, message: Message, text: str, markup) -> Message:
        try:
            return await message.edit_text(text, parse_mode="HTML", reply_markup=markup,
                                           link_preview_options=None)
        except TelegramRetryAfter as exc:
            await asyncio.sleep(exc.retry_after)
            return await self._replace(message, text, markup)
        except TelegramBadRequest as exc:
            if "message is not modified" in str(exc).lower():
                return message
            # Разметка не понравилась — отдаём текстом, лишь бы человек прочитал.
            # parse_mode=None обязателен: без него aiogram подставит глобальный
            # HTML, и сырые < > из plain() отобьются второй ошибкой.
            logger.warning("разметка отклонена, отправляю без неё: %s", exc)
            return await message.edit_text(plain(text), parse_mode=None, reply_markup=markup)

    async def _send(self, text: str, markup) -> Message:
        try:
            return await self.origin.answer(text, parse_mode="HTML", reply_markup=markup,
                                            link_preview_options=None)
        except TelegramRetryAfter as exc:
            await asyncio.sleep(exc.retry_after)
            return await self._send(text, markup)
        except TelegramBadRequest:
            # Тот же случай, что и в _replace: без parse_mode=None aiogram
            # подставит глобальный HTML и уронит уже чистый текст.
            return await self.origin.answer(plain(text), parse_mode=None, reply_markup=markup)

    async def fail(self, text: str, *, reply_markup=None) -> None:
        """Показать ошибку на месте живого сообщения, а не отдельной строкой."""
        if self.live is not None:
            try:
                await self.live.edit_text(text, parse_mode="HTML", reply_markup=reply_markup)
                return
            except Exception:
                pass
        await self.origin.answer(text, parse_mode="HTML", reply_markup=reply_markup)
