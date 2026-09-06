"""История чатов, приглашения и промокод."""
from __future__ import annotations

import logging

from aiogram import F, Router
from aiogram.filters import Command, CommandObject
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from bot.config import settings
from bot.services.api import ApiError, api
from bot.services.state import store
from bot.services.tg_format import esc
from bot.texts import t

logger = logging.getLogger(__name__)
router = Router(name="profile")

PAGE = 8


def _title(session: dict) -> str:
    title = (session.get("title") or "").strip()
    return (title or "Без названия")[:48]


def _history_keyboard(sessions: list, page: int) -> InlineKeyboardMarkup:
    total = max(1, (len(sessions) + PAGE - 1) // PAGE)
    page = max(0, min(page, total - 1))
    rows = [[InlineKeyboardButton(text=f"💬 {_title(s)}",
                                  callback_data=f"h:o:{s.get('uid') or s.get('id')}")]
            for s in sessions[page * PAGE:(page + 1) * PAGE]]
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton(text="◀", callback_data=f"h:p:{page - 1}"))
    nav.append(InlineKeyboardButton(text=f"{page + 1}/{total}", callback_data="nav:noop"))
    if page < total - 1:
        nav.append(InlineKeyboardButton(text="▶", callback_data=f"h:p:{page + 1}"))
    if len(nav) > 1:
        rows.append(nav)
    rows.append([InlineKeyboardButton(text="✖ Закрыть", callback_data="nav:x")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


async def _sessions(token: str, lang: str, telegram_id: int) -> list:
    cached = await store.get(telegram_id, "sessions_cache")
    if cached:
        return cached
    sessions = await api.sessions(token, lang=lang, telegram_id=telegram_id)
    await store.set(telegram_id, "sessions_cache", sessions, ttl=120)
    return sessions


@router.message(Command("history"))
async def cmd_history(message: Message, token: str, lang: str = "ru",
                      telegram_id: int | None = None) -> None:
    # telegram_id обязателен, когда сюда зовут из callback («☰ Ещё → История»):
    # там message принадлежит боту, и его from_user — бот. Без явного id список
    # чатов лёг бы в кэш под id бота и достался бы следующему человеку.
    try:
        sessions = await _sessions(token, lang, telegram_id or message.from_user.id)
    except ApiError:
        await message.answer(t(lang, "server_down"))
        return
    if not sessions:
        await message.answer(t(lang, "history_empty"))
        return
    await message.answer(t(lang, "history_title"), parse_mode="HTML",
                         reply_markup=_history_keyboard(sessions, 0))


@router.callback_query(F.data.startswith("h:p:"))
async def history_page(call: CallbackQuery, token: str, lang: str = "ru") -> None:
    page = int(call.data.split(":")[2])
    sessions = await _sessions(token, lang, call.from_user.id)
    await call.answer()
    await call.message.edit_reply_markup(reply_markup=_history_keyboard(sessions, page))


@router.callback_query(F.data.startswith("h:o:"))
async def history_open(call: CallbackQuery, token: str, lang: str = "ru") -> None:
    """Открыть старый чат: следующий вопрос продолжит именно его."""
    session_id = call.data.split(":", 2)[2]
    # У callback_query from_user — тот, кто нажал (человек), а не бот: и кэш,
    # и «текущий чат» ключуются верно. Брать call.message.from_user здесь нельзя.
    user_id = call.from_user.id
    sessions = await _sessions(token, lang, user_id)
    session = next((s for s in sessions
                    if str(s.get("uid")) == session_id or str(s.get("id")) == session_id), None)
    await store.set(user_id, "session", session_id)
    await call.answer()
    await call.message.answer(
        t(lang, "history_opened", title=esc(_title(session or {}))), parse_mode="HTML")


@router.message(Command("referral"))
async def cmd_referral(message: Message, token: str, lang: str = "ru",
                       telegram_id: int | None = None) -> None:
    # Как и в cmd_history: из «☰ Ещё» приходит сообщение бота, id человека
    # передаётся явно — иначе статистика запрашивается от имени бота.
    try:
        stats = await api.request("GET", "/api/users/referral/stats/", token=token,
                                  lang=lang, telegram_id=telegram_id or message.from_user.id)
    except ApiError:
        await message.answer(t(lang, "server_down"))
        return

    uid = (stats or {}).get("referral_uid") or ""
    bot_name = settings.bot_username or ""
    link = f"https://t.me/{bot_name}?start=ref_{uid}" if bot_name and uid else (
        (stats or {}).get("link") or "")

    text = (
        "🤝 <b>Приглашайте друзей</b>\n"
        "С каждого их пополнения вам начисляются кредиты — пожизненно.\n\n"
        f"Ваша ссылка:\n<code>{esc(link)}</code>\n\n"
        f"Приглашено: <b>{stats.get('invited_count', 0)}</b>\n"
        f"Заработано: <b>{stats.get('total_earned', 0)} кредитов</b>"
    )
    share = f"https://t.me/share/url?url={link}&text=" + (
        "Пользуюсь EsAI — ChatGPT, Claude, Gemini, картинки и видео в одном боте")
    keyboard = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="📤 Поделиться", url=share)]]) if link else None
    await message.answer(text, parse_mode="HTML", reply_markup=keyboard,
                         disable_web_page_preview=True)


@router.message(Command("promo"))
async def cmd_promo(message: Message, command: CommandObject, token: str,
                    lang: str = "ru") -> None:
    code = (command.args or "").strip()
    if not code:
        await message.answer("Введите промокод так: <code>/promo КОД</code>",
                             parse_mode="HTML")
        return
    try:
        result = await api.request("POST", "/api/users/promo/activate/", token=token,
                                   lang=lang, telegram_id=message.from_user.id,
                                   json_body={"code": code})
    except ApiError as exc:
        reason = exc.message or exc.code or "код не подошёл"
        await message.answer(t(lang, "promo_fail", reason=reason))
        return
    await message.answer(t(lang, "promo_ok", credits=(result or {}).get("credited", 0)),
                         parse_mode="HTML")
