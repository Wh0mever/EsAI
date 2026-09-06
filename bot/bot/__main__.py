"""Запуск бота."""
from __future__ import annotations

import asyncio
import contextlib
import logging
import logging.handlers
import os
import re
import signal
import sys
import time

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.redis import DefaultKeyBuilder, RedisStorage
from aiogram.types import BotCommand

from bot.config import settings
from bot.middlewares.auth import AuthMiddleware, DedupMiddleware, ErrorsMiddleware
from bot.routers import chat as chat_router
from bot.routers import media as media_router
from bot.routers import models as models_router
from bot.routers import start as start_router
from bot.services.api import api
from bot.services.state import store

logger = logging.getLogger("bot")

TOKEN_RE = re.compile(r"\b\d{6,}:[A-Za-z0-9_-]{30,}\b")


class SecretFilter(logging.Filter):
    """Токен бота не должен попасть в логи: он приходит в URL при ошибках сети."""

    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.msg, str):
            record.msg = TOKEN_RE.sub("bot<токен скрыт>", record.msg)
        if record.args:
            record.args = tuple(
                TOKEN_RE.sub("bot<токен скрыт>", a) if isinstance(a, str) else a
                for a in (record.args if isinstance(record.args, tuple) else (record.args,))
            )
        return True


def setup_logging() -> None:
    handlers: list[logging.Handler] = [logging.StreamHandler(sys.stdout)]
    try:
        os.makedirs(os.path.dirname(settings.log_file), exist_ok=True)
        handlers.append(logging.handlers.RotatingFileHandler(
            settings.log_file, maxBytes=5 * 1024 * 1024, backupCount=5, encoding="utf-8"))
    except OSError:
        pass
    fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    for handler in handlers:
        handler.setFormatter(fmt)
        handler.addFilter(SecretFilter())
    logging.basicConfig(level=getattr(logging, settings.log_level.upper(), logging.INFO),
                        handlers=handlers, force=True)
    logging.getLogger("httpx").setLevel(logging.WARNING)


COMMANDS = [
    BotCommand(command="start", description="Начать"),
    BotCommand(command="new", description="Новый чат"),
    BotCommand(command="model", description="Выбрать модель"),
    BotCommand(command="balance", description="Баланс и кредиты"),
    BotCommand(command="help", description="Помощь"),
]


async def heartbeat(stop: asyncio.Event) -> None:
    """Пульс для healthcheck: пока бот жив, файл свежий."""
    while not stop.is_set():
        try:
            with open(settings.alive_file, "w") as handle:
                handle.write(str(int(time.time())))
        except OSError:
            pass
        with contextlib.suppress(asyncio.TimeoutError):
            await asyncio.wait_for(stop.wait(), timeout=30)


async def hold_lock(stop: asyncio.Event) -> bool:
    """Опрос Telegram ведёт ровно один процесс.

    Второй с тем же токеном получил бы от Telegram отказ и молча не работал —
    лучше сразу сказать об этом в лог и не запускаться.
    """
    if not await store.acquire_lock("polling"):
        logger.error("другой экземпляр бота уже работает — выходим")
        return False

    async def keeper() -> None:
        while not stop.is_set():
            await store.refresh_lock("polling")
            with contextlib.suppress(asyncio.TimeoutError):
                await asyncio.wait_for(stop.wait(), timeout=10)

    asyncio.create_task(keeper())
    return True


def build_dispatcher() -> Dispatcher:
    storage = RedisStorage.from_url(
        settings.redis_url,
        key_builder=DefaultKeyBuilder(prefix="esai_fsm", with_bot_id=True),
    )
    dispatcher = Dispatcher(storage=storage)

    dispatcher.update.outer_middleware(DedupMiddleware())
    for observer in (dispatcher.message, dispatcher.callback_query):
        observer.outer_middleware(AuthMiddleware())
        observer.middleware(ErrorsMiddleware())

    dispatcher.include_router(start_router.router)
    dispatcher.include_router(models_router.router)
    dispatcher.include_router(media_router.router)
    dispatcher.include_router(chat_router.router)
    return dispatcher


async def main() -> int:
    setup_logging()
    if not settings.configured:
        logger.error("нет токена бота или сервисного секрета — запускаться нечем")
        return 1

    stop = asyncio.Event()
    if not await hold_lock(stop):
        return 1

    bot = Bot(settings.bot_token,
              default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dispatcher = build_dispatcher()
    asyncio.create_task(heartbeat(stop))

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        with contextlib.suppress(NotImplementedError):
            loop.add_signal_handler(sig, stop.set)

    me = await bot.get_me()
    logger.info("бот @%s запущен, режим доступа: %s", me.username, settings.access)
    await bot.set_my_commands(COMMANDS)
    # Опрос и вебхук одновременно невозможны — снимаем вебхук на всякий случай.
    await bot.delete_webhook(drop_pending_updates=False)

    try:
        await dispatcher.start_polling(
            bot,
            allowed_updates=["message", "callback_query", "my_chat_member"],
            handle_signals=False,
        )
    finally:
        stop.set()
        await store.release_lock("polling")
        await api.aclose()
        await store.aclose()
        await bot.session.close()
        logger.info("бот остановлен")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
