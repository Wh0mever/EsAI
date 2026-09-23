"""Middleware: узнаём человека до того, как до него доберётся обработчик."""
from __future__ import annotations

import logging
import re
from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, Message, TelegramObject, Update

from bot.config import settings
from bot.keyboards.common import paywall
from bot.services.api import ApiError, api
from bot.services.state import store
from bot.services.tg_format import plain
from bot.texts import register_texts, t

logger = logging.getLogger(__name__)

# Свой текст на случай, когда даже свежий токен API не принимает: «сервер не
# отвечает» тут врёт (сервер как раз ответил), а «доступ закрыт» обещает больше,
# чем мы знаем. Имя с префиксом auth_ — чтобы не спорить с общими ключами.
register_texts({
    "ru": {"auth_session_lost": (
        "Не удалось подтвердить вход. Попробуйте /start, а если не поможет — "
        "напишите в поддержку: /help")},
    "en": {"auth_session_lost": (
        "Could not confirm your sign-in. Try /start, and if that does not help — "
        "contact support: /help")},
    "kg": {"auth_session_lost": (
        "Кирүүнү ырастоо мүмкүн болгон жок. /start аракет кылыңыз, жардам бербесе — "
        "колдоого жазыңыз: /help")},
})

COMMAND_RE = re.compile(r"^/([A-Za-z0-9_]{1,32})(?:@[A-Za-z0-9_]+)?(?:\s|$)")

# Эти команды сами распоряжаются мастером — входят в него или гасят его.
# Все остальные команды означают «человек ушёл на другой экран».
WIZARD_COMMANDS = frozenset({"start", "image", "video", "studio", "cancel"})


def _command_name(text: str) -> str:
    """«/new@EsAI_Bot ещё» → «new»; обычный текст → пустая строка."""
    match = COMMAND_RE.match((text or "").lstrip())
    return match.group(1).lower() if match else ""


def _start_args(text: str) -> str:
    """Хвост «/start ref_КОД» — он нужен ДО обработчика, при создании аккаунта."""
    if _command_name(text) != "start":
        return ""
    parts = (text or "").strip().split(maxsplit=1)
    return parts[1].strip() if len(parts) > 1 else ""


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

    Исключение — сообщения об оплате. Если процесс упал между отметкой
    «апдейт увиден» и подтверждением оплаты на сервере, отметка навсегда
    похоронила бы деньги: Telegram больше не повторит. Повтор же безопасен —
    сервер узнаёт оплату по её идентификатору и второй раз кредиты не начисляет.
    """

    @staticmethod
    def _is_payment(event: TelegramObject) -> bool:
        message = getattr(event, "message", None) if isinstance(event, Update) else None
        return bool(message and (message.successful_payment or message.refunded_payment))

    async def __call__(self, handler, event: TelegramObject, data: dict) -> Any:
        # Живём на dispatcher.update, а там сам event и есть Update: ключ
        # "event_update" кладётся в data глубже, уже за outer-middleware, и
        # раньше его тут не было никогда — защита просто не работала.
        if isinstance(event, Update) and not self._is_payment(event):
            if await store.seen_update(event.update_id):
                logger.info("апдейт %s уже обработан, пропускаем", event.update_id)
                return None
        return await handler(event, data)


class AuthMiddleware(BaseMiddleware):
    """Токен человека и его язык — в каждый обработчик.

    Токен кэшируется: обменивать данные Telegram на него при каждом сообщении
    незачем. Если токен перестал приниматься (401), молча берём новый и
    повторяем обработчик — человек этого не замечает.
    """

    async def __call__(self, handler: Callable[[TelegramObject, dict], Awaitable[Any]],
                       event: TelegramObject, data: dict) -> Any:
        user = data.get("event_from_user")
        if user is None or user.is_bot:
            return None

        if not settings.allowed(user.id):
            # В режиме «только свои» id стучащегося нужен в логе: так его
            # можно добавить в BOT_STAFF_IDS, не спрашивая человека.
            logger.info("доступ закрыт: telegram id %s (@%s)", user.id, user.username or "-")
            lang = user.language_code or "ru"
            lang = "ru" if lang.startswith("ru") else ("kg" if lang.startswith("ky") else "en")
            await self._reply(event, t(lang, "not_allowed"))
            return None

        lang = await store.get(user.id, "lang") or None
        token = await store.get_token(user.id)

        # Реферальный код и промокод бэкенд применяет в момент СОЗДАНИЯ
        # аккаунта, а аккаунт создаётся здесь — до обработчика. Поэтому код из
        # ссылки разбираем сами и отдаём в тот самый первый обмен: повторный
        # вызов из cmd_start уже попадал в ветку «существующий пользователь»,
        # где ref игнорируется, а created=False скрывал онбординг новичка.
        ref, promo = self._deep_link(event)
        if (ref or promo) and not await store.get(user.id, "seen_start"):
            token = None

        payment = self._is_payment(event)
        # Токен, добытый прямо сейчас: если API отвергнет и его, менять не на что.
        minted_now = False
        if not token:
            try:
                payload = await api.auth_telegram(
                    _tg_user_dict(user),
                    chat_id=self._chat_id(event) or user.id,
                    ref=ref or data.get("ref") or "",
                    promo=promo,
                )
            except ApiError as exc:
                if payment:
                    # Человек уже заплатил. DedupMiddleware пометил апдейт
                    # обработанным, второй раз Telegram его не пришлёт, а
                    # обработчик Stars токеном не пользуется (ходит на сервер
                    # сервисным ключом и складывает подтверждение в очередь
                    # повторов). Отказать здесь — значит забрать деньги и не
                    # выдать кредиты, поэтому пускаем дальше без токена.
                    logger.warning("оплата от %s без токена (%s) — пропускаем дальше",
                                   user.id, exc.code or exc.status)
                else:
                    if exc.status == 403:
                        await self._reply(event, t(lang or "ru", "blocked"))
                        return None
                    if exc.status == 429:
                        # Сервер жив и просит не частить: «не отвечает» тут врёт.
                        logger.warning("вход %s упёрся в лимит (Retry-After %s)",
                                       user.id, exc.retry_after)
                        await self._reply(event, t(lang or "ru", "rate_limited"))
                        return None
                    logger.exception("не удалось получить токен для %s", user.id)
                    await self._reply(event, t(lang or "ru", "server_down"))
                    return None
            else:
                token = payload["access"]
                minted_now = True
                await store.set_token(user.id, token)
                data["auth_payload"] = payload
                if not lang:
                    lang = (payload.get("user") or {}).get("lang") or "ru"
                    await store.set(user.id, "lang", lang)

        data["token"] = token or ""
        data["lang"] = lang or "ru"
        data["tg_user"] = _tg_user_dict(user)

        try:
            return await handler(event, data)
        except ApiError as exc:
            if exc.status != 401 or payment:
                raise
            if minted_now or not token:
                # Токен выдали в этом же апдейте, а API его не принял: второй
                # такой же ничего не изменит. Раньше ошибка уходила наружу, и
                # человек не получал вообще ничего.
                logger.warning("токен для %s отвергнут сразу после выдачи", user.id)
                await self._reply(event, t(lang or "ru", "auth_session_lost"))
                return None
            return await self._retry_with_fresh_token(handler, event, data, user,
                                                      lang or "ru")

    async def _retry_with_fresh_token(self, handler, event: TelegramObject, data: dict,
                                      user, lang: str) -> Any:
        """401 из обработчика — кэшированный токен API больше не принимает.

        Кэш в Redis живёт 11 часов, а JWT — 12, поэтому «просто протух» почти не
        бывает; 401 означает, что токен отозван: сменили SECRET_KEY, аккаунт
        деактивировали, токен пришёл из другого стенда. Раньше такой ответ никто
        не превращал в новый обмен — человек до конца TTL получал ошибку на любое
        действие, а лечилось это только ожиданием.

        Повтор обработчика безопасен для денег: 401 отдаёт аутентификация, до
        бизнес-логики и до списания запрос не доходит. Токен, полученный в этом
        же апдейте, не обновляем — второй такой же ничего не изменит.
        """
        await store.drop_token(user.id)
        try:
            payload = await api.auth_telegram(
                _tg_user_dict(user), chat_id=self._chat_id(event) or user.id)
        except ApiError as exc:
            if exc.status == 403:
                await self._reply(event, t(lang, "blocked"))
            elif exc.status == 429:
                logger.warning("обновление токена %s упёрлось в лимит", user.id)
                await self._reply(event, t(lang, "rate_limited"))
            else:
                logger.exception("не удалось обновить токен для %s", user.id)
                await self._reply(event, t(lang, "server_down"))
            return None

        token = payload["access"]
        await store.set_token(user.id, token)
        data["token"] = token
        # auth_payload намеренно не трогаем: по нему cmd_start понимает, что
        # обмен в этом апдейте был и код из ссылки бэкенд уже видел. Починочный
        # обмен ни ref, ни промокода не нёс — выдавать его за первый нельзя.
        try:
            return await handler(event, data)
        except ApiError as exc:
            if exc.status != 401:
                raise
            # Свежий токен тоже не приняли — дело не в токене, и молчать нельзя.
            logger.warning("свежий токен для %s тоже отвергнут API", user.id)
            await self._reply(event, t(lang, "auth_session_lost"))
            return None

    @staticmethod
    def _deep_link(event: TelegramObject) -> tuple[str, str]:
        """(реферал, промокод) из «/start …», если это он."""
        if not isinstance(event, Message):
            return "", ""
        args = _start_args(event.text or "")
        if not args:
            return "", ""
        from bot.routers.start import _parse_payload

        return _parse_payload(args)

    @staticmethod
    def _is_payment(event: TelegramObject) -> bool:
        return isinstance(event, Message) and bool(
            event.successful_payment or event.refunded_payment)

    @staticmethod
    def _chat_id(event: TelegramObject) -> int | None:
        if isinstance(event, Message):
            return event.chat.id
        if isinstance(event, CallbackQuery) and event.message:
            return event.message.chat.id
        return None

    @staticmethod
    async def _reply(event: TelegramObject, text: str) -> None:
        if isinstance(event, Message):
            try:
                await event.answer(text)
            except Exception:
                logger.exception("не удалось ответить пользователю")
            return
        if not isinstance(event, CallbackQuery):
            return
        try:
            # У всплывашки лимит 200 символов; длиннее Telegram не примет вовсе.
            await event.answer(text[:200], show_alert=True)
            return
        except Exception:
            # Всплывашка полагается одна на нажатие. В починочной ветке
            # обработчик уже успел ответить на кнопку до того, как упал, —
            # значит про потерянный вход человек не узнал бы вообще ничего.
            logger.warning("всплывашка не прошла — пишем в чат", exc_info=True)
        if event.message is not None:
            try:
                await event.message.answer(text)
            except Exception:
                logger.exception("не удалось ответить пользователю")


class CommandResetMiddleware(BaseMiddleware):
    """Любая команда закрывает незаконченный мастер.

    Мастера пропускают текст с «/» мимо себя (~F.text.startswith("/")), но
    состояние при этом остаётся. Человек нажал «🎨 Картинка», передумал,
    написал /new — и следующая обычная фраза всё равно уходила в мастер, а из
    состояния редактирования — сразу в платную генерацию. Команды самих
    мастеров исключены: они распоряжаются состоянием сами.
    """

    async def __call__(self, handler, event: TelegramObject, data: dict) -> Any:
        state = data.get("state")
        if state is not None and isinstance(event, Message):
            command = _command_name(event.text or event.caption or "")
            if command and command not in WIZARD_COMMANDS and await state.get_state():
                await state.clear()
        return await handler(event, data)


def api_error_reply(lang: str, exc: ApiError) -> tuple[str, InlineKeyboardMarkup | None]:
    """Что сказать человеку об отказе API, который обработчик не разобрал сам."""
    if exc.is_paywall:
        # Ленивый импорт: chat — роутер, а роутеры грузятся после middleware.
        from bot.routers.chat import _paywall_text

        return (_paywall_text(lang, exc.code, exc.payload),
                paywall(lang, settings.site_base_url, free_model=exc.code == "premium_locked"))
    if exc.status == 429:
        return t(lang, "rate_limited"), None
    if exc.is_temporary:
        return t(lang, "server_down"), None
    return t(lang, "action_failed"), None


class ErrorsMiddleware(BaseMiddleware):
    """Ни одна ошибка не должна выглядеть как молчание бота."""

    async def __call__(self, handler, event: TelegramObject, data: dict) -> Any:
        try:
            return await handler(event, data)
        except ApiError as exc:
            if exc.status == 401:
                # 401 разбирает AuthMiddleware: меняет токен и повторяет обработчик.
                raise
            # Раньше любой ApiError улетал отсюда мимо всех: AuthMiddleware знает
            # только 401, и на неразобранный отказ (429 в студии, 5xx в меню)
            # человек получал тишину, а кнопка — вечные «часики».
            logger.warning("обработчик: отказ API — http %s %s %s", exc.status,
                           exc.code or "-", (exc.message or "")[:200])
            text, markup = api_error_reply(data.get("lang", "ru"), exc)
            await self._notify(event, text, reply_markup=markup)
            return None
        except Exception:
            logger.exception("обработчик упал")
            await self._notify(event, t(data.get("lang", "ru"), "failed"))
            return None

    @staticmethod
    async def _notify(event: TelegramObject, text: str,
                      reply_markup: InlineKeyboardMarkup | None = None) -> None:
        """Сказать об ошибке и тому, кто нажал кнопку.

        Раньше отвечали только на Message: упавший callback-обработчик оставлял
        нажатую кнопку в состоянии «часики» до таймаута Telegram, и человек не
        понимал, услышал его бот или нет. Сначала гасим «крутилку» коротким
        всплывающим текстом (у него лимит 200 символов), потом пишем в чат —
        всплывашка пропадает через пару секунд, а ошибку нужно иметь возможность
        перечитать. Каждый шаг отдельно: сообщение могло быть удалено, но
        крутилку снять всё равно обязаны.
        """
        if isinstance(event, Message):
            try:
                await event.answer(text, reply_markup=reply_markup)
            except Exception:
                logger.exception("не удалось сообщить об ошибке")
            return
        if isinstance(event, CallbackQuery):
            try:
                # Во всплывашке разметки нет — теги показались бы как есть.
                await event.answer(plain(text)[:200])
            except Exception:
                # Обычно обработчик уже ответил на кнопку сам — это не авария.
                logger.warning("не удалось погасить «крутилку» кнопки", exc_info=True)
            if event.message is not None:
                try:
                    await event.message.answer(text, reply_markup=reply_markup)
                except Exception:
                    logger.exception("не удалось сообщить об ошибке")
