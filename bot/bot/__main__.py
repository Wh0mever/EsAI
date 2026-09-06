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

from aiogram import Bot, Dispatcher, F, Router
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import ChatMemberUpdatedFilter, KICKED, MEMBER
from aiogram.fsm.storage.redis import DefaultKeyBuilder, RedisStorage
from aiogram.types import BotCommand, ChatMemberUpdated

from bot.config import settings
from bot.middlewares.auth import AuthMiddleware, DedupMiddleware, ErrorsMiddleware
from bot.routers import account as account_router
from bot.routers import billing as billing_router
from bot.routers import chat as chat_router
from bot.routers import image as image_router
from bot.routers import media as media_router
from bot.routers import models as models_router
from bot.routers import profile as profile_router
from bot.routers import start as start_router
from bot.routers import studio as studio_router
from bot.routers import video as video_router
from bot.services.api import ApiError, api
from bot.services.state import store

logger = logging.getLogger("bot")

TOKEN_RE = re.compile(r"\b\d{6,}:[A-Za-z0-9_-]{30,}\b")
ALLOWED_UPDATES = ["message", "callback_query", "pre_checkout_query", "my_chat_member"]


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


# Команды — по языкам: Telegram показывает список на языке клиента.
COMMANDS = {
    "ru": [
        ("start", "Начать"), ("new", "Новый чат"), ("model", "Выбрать модель"),
        ("image", "Создать картинку"), ("video", "Создать видео"), ("studio", "Студия мультфильмов"),
        ("balance", "Баланс и кредиты"), ("topup", "Пополнить баланс"), ("profile", "Профиль"),
        ("referral", "Пригласить друзей"), ("transfer", "Перевести кредиты"), ("promo", "Промокод"),
        ("memory", "Память"), ("history", "История чатов"), ("notify", "Уведомления"),
        ("lang", "Язык"), ("help", "Помощь"), ("terms", "Условия покупки"),
        ("paysupport", "Поддержка по оплате"), ("cancel", "Отменить действие"),
        ("delete", "Удалить мои данные"),
    ],
    "en": [
        ("start", "Start"), ("new", "New chat"), ("model", "Choose a model"),
        ("image", "Create an image"), ("video", "Create a video"), ("studio", "Cartoon studio"),
        ("balance", "Balance and credits"), ("topup", "Top up"), ("profile", "Profile"),
        ("referral", "Invite friends"), ("transfer", "Transfer credits"), ("promo", "Promo code"),
        ("memory", "Memory"), ("history", "Chat history"), ("notify", "Notifications"),
        ("lang", "Language"), ("help", "Help"), ("terms", "Purchase terms"),
        ("paysupport", "Payment support"), ("cancel", "Cancel"), ("delete", "Delete my data"),
    ],
}


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


async def pending_loop(bot: Bot, stop: asyncio.Event) -> None:
    """Раз в минуту довести до сервера оплаты, которые он не принял сразу."""
    from bot.routers.billing import retry_pending

    while not stop.is_set():
        with contextlib.suppress(asyncio.TimeoutError):
            await asyncio.wait_for(stop.wait(), timeout=60)
        if stop.is_set():
            break
        try:
            done = await retry_pending(bot)
            if done:
                logger.info("отложенных оплат подтверждено: %s", done)
        except Exception:
            logger.exception("повтор отложенных оплат упал")


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


system_router = Router(name="system")


@system_router.my_chat_member(ChatMemberUpdatedFilter(member_status_changed=KICKED))
async def on_blocked(event: ChatMemberUpdated) -> None:
    """Человек нажал «стоп»: больше ему не пишем, пока не вернётся."""
    try:
        await api.mark_blocked(event.from_user.id, True)
    except ApiError:
        logger.warning("блокировка не записалась для %s", event.from_user.id)


@system_router.my_chat_member(ChatMemberUpdatedFilter(member_status_changed=MEMBER))
async def on_unblocked(event: ChatMemberUpdated) -> None:
    try:
        await api.mark_blocked(event.from_user.id, False)
    except ApiError:
        pass


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

    # Порядок важен: команды и меню — первыми, состояния мастеров — до общего
    # текстового обработчика чата, чат — последним (он ловит всё остальное).
    dispatcher.include_router(system_router)
    dispatcher.include_router(start_router.router)
    dispatcher.include_router(billing_router.router)
    dispatcher.include_router(account_router.router)
    dispatcher.include_router(image_router.router)
    dispatcher.include_router(video_router.router)
    dispatcher.include_router(studio_router.router)
    dispatcher.include_router(models_router.router)
    dispatcher.include_router(profile_router.router)
    dispatcher.include_router(media_router.router)
    dispatcher.include_router(chat_router.router)
    return dispatcher


async def set_commands(bot: Bot) -> None:
    for lang, items in COMMANDS.items():
        commands = [BotCommand(command=c, description=d) for c, d in items]
        try:
            if lang == "ru":
                await bot.set_my_commands(commands)  # по умолчанию — русский
            await bot.set_my_commands(commands, language_code=lang)
        except Exception:
            logger.exception("set_my_commands(%s) не удался", lang)


async def run_polling(bot: Bot, dispatcher: Dispatcher) -> None:
    # Опрос и вебхук одновременно невозможны — снимаем вебхук на всякий случай.
    await bot.delete_webhook(drop_pending_updates=False)
    await dispatcher.start_polling(bot, allowed_updates=ALLOWED_UPDATES, handle_signals=False)


async def run_webhook(bot: Bot, dispatcher: Dispatcher, stop: asyncio.Event) -> None:
    """Вебхук: nginx проксирует https://<host><path> на порт бота."""
    from aiohttp import web
    from aiogram.webhook.aiohttp_server import SimpleRequestHandler, setup_application

    if not settings.webhook_base or not settings.webhook_secret:
        raise RuntimeError("для вебхука нужны BOT_WEBHOOK_BASE и BOT_WEBHOOK_SECRET")
    url = settings.webhook_base.rstrip("/") + settings.webhook_path
    app = web.Application()
    SimpleRequestHandler(dispatcher=dispatcher, bot=bot,
                         secret_token=settings.webhook_secret).register(app, path=settings.webhook_path)
    setup_application(app, dispatcher, bot=bot)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", settings.webhook_port)
    await site.start()
    await bot.set_webhook(url, secret_token=settings.webhook_secret,
                          allowed_updates=ALLOWED_UPDATES, drop_pending_updates=False)
    logger.info("вебхук установлен: %s (порт %s)", url, settings.webhook_port)
    try:
        await stop.wait()
    finally:
        await runner.cleanup()


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
    asyncio.create_task(pending_loop(bot, stop))

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        with contextlib.suppress(NotImplementedError):
            loop.add_signal_handler(sig, stop.set)

    me = await bot.get_me()
    logger.info("бот @%s запущен, режим доступа: %s, режим: %s",
                me.username, settings.access, settings.mode)
    await set_commands(bot)

    try:
        if (settings.mode or "polling").lower() == "webhook":
            await run_webhook(bot, dispatcher, stop)
        else:
            await run_polling(bot, dispatcher)
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
