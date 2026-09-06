"""Первый экран, меню и справка."""
from __future__ import annotations

import logging
import re

from aiogram import F, Router
from aiogram.filters import Command, CommandObject, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from bot.config import settings
from bot.keyboards.common import (
    MENU_ACTIONS,
    language_choice,
    main_menu,
    more_menu,
    quick_prompts,
)
from bot.services.api import ApiError, api
from bot.services.state import store
from bot.services.tg_format import esc
from bot.texts import quick_prompt, register_texts, t

logger = logging.getLogger(__name__)
router = Router(name="start")

REF_RE = re.compile(r"^ref_([A-Za-z0-9]{4,32})$")
PROMO_RE = re.compile(r"^promo_([A-Za-z0-9_-]{2,48})$")
LINK_RE = re.compile(r"^link_([A-Za-z0-9]{6,32})$")
SHORTCUTS = ("studio", "topup", "chat", "video", "image")

register_texts({
    "ru": {"continue_prompt": "Продолжи.", "more_title": "☰ <b>Ещё</b>",},
    "en": {"continue_prompt": "Continue.", "more_title": "☰ <b>More</b>",},
    "kg": {"continue_prompt": "Улант.", "more_title": "☰ <b>Дагы</b>",},
})


def _parse_payload(payload: str) -> tuple[str, str]:
    """Разобрать ссылку t.me/<bot>?start=… → (реферал, промокод)."""
    payload = (payload or "").strip()
    if not payload:
        return "", ""
    match = REF_RE.match(payload)
    if match:
        return match.group(1), ""
    match = PROMO_RE.match(payload)
    if match:
        return "", match.group(1)
    return "", ""


def _parse_link(payload: str) -> str:
    match = LINK_RE.match((payload or "").strip())
    return match.group(1) if match else ""


def _parse_shortcut(payload: str) -> str:
    payload = (payload or "").strip().lower()
    base = payload.split("_", 1)[0]
    return base if base in SHORTCUTS else ""


@router.message(CommandStart(deep_link=True))
@router.message(CommandStart())
async def cmd_start(message: Message, command: CommandObject | None = None,
                    token: str = "", lang: str = "ru", auth_payload: dict | None = None,
                    tg_user: dict | None = None, state: FSMContext | None = None) -> None:
    telegram_id = message.from_user.id
    args = getattr(command, "args", "") or ""
    ref, _promo = _parse_payload(args)
    if state is not None:
        await state.clear()

    link_code = _parse_link(args)
    if link_code:
        from bot.routers.account import link_from_deep_link

        await store.set(telegram_id, "seen_start", True)
        await link_from_deep_link(message, lang, link_code, tg_user or {})
        return

    # Реферальный код и промокод уже ушли в первый обмен — их разобрал
    # AuthMiddleware до создания аккаунта. Повторный обмен здесь только вредил:
    # бэкенд применяет ref лишь при создании, а created=False в ответе прятал
    # от новичка выбор языка и приветствие.
    await store.set(telegram_id, "seen_start", True)
    created = bool((auth_payload or {}).get("created"))
    user = (auth_payload or {}).get("user") or {}

    if created:
        # Новому — сначала язык: дальше все тексты и ответы моделей будут на нём.
        await message.answer(t(lang, "choose_lang"), reply_markup=language_choice())
        if ref:
            await message.answer(t(lang, "from_referral"))
        await _greet_new(message, lang, user)
        return

    shortcut = _parse_shortcut(args)
    if shortcut and token:
        await _open_shortcut(message, token, lang, shortcut, state)
        return

    if not user:
        try:
            user = await api.balance(token, lang=lang, telegram_id=telegram_id)
        except ApiError:
            user = {}
    model = (await store.get(telegram_id, "model") or settings.default_model).split("/")[-1]
    await message.answer(
        t(lang, "welcome_back",
          name=esc(message.from_user.first_name or ""),
          balance=user.get("balance_tokens", "—"), model=model),
        parse_mode="HTML", reply_markup=main_menu(lang),
    )
    await message.answer("👇", reply_markup=quick_prompts(lang))


async def _open_shortcut(message: Message, token: str, lang: str, shortcut: str,
                         state: FSMContext | None) -> None:
    """t.me/<бот>?start=studio — сразу в студию, ?start=topup — в оплату."""
    if shortcut == "studio":
        from bot.routers.studio import show_intro

        await show_intro(message, token, lang)
    elif shortcut == "topup":
        from bot.routers.billing import show_topup

        await show_topup(message, token, lang)
    elif shortcut == "video" and state is not None:
        from bot.routers.video import start_wizard

        await start_wizard(message, token, lang, state)
    elif shortcut == "image" and state is not None:
        from bot.routers.image import start_wizard

        await start_wizard(message, token, lang, state)
    else:
        await cmd_new(message, lang)


async def _greet_new(message: Message, lang: str, user: dict) -> None:
    await message.answer(
        t(lang, "welcome", balance=user.get("balance_tokens", 0)),
        parse_mode="HTML", reply_markup=main_menu(lang),
    )
    await message.answer("👇", reply_markup=quick_prompts(lang))


@router.callback_query(F.data.startswith("lang:"))
async def set_language(call: CallbackQuery) -> None:
    lang = call.data.split(":", 1)[1]
    if lang not in ("ru", "en", "kg"):
        await call.answer()
        return
    await store.set(call.from_user.id, "lang", lang)
    try:
        await api.set_prefs(call.from_user.id, lang=lang)
    except ApiError:
        logger.warning("язык не сохранился на сервере")
    await call.answer(t(lang, "lang_set"))
    await call.message.answer(t(lang, "lang_set"), reply_markup=main_menu(lang))


@router.callback_query(F.data.startswith("q:"))
async def quick_start(call: CallbackQuery, token: str, lang: str, state: FSMContext) -> None:
    """Быстрая подсказка: подставляем начало фразы, человек дописывает своё."""
    key = call.data.split(":", 1)[1]
    await call.answer()
    if key == "image":
        from bot.routers.image import start_wizard

        await start_wizard(call.message, token, lang, state)
        return
    prompt = quick_prompt(lang, key)
    await store.set(call.from_user.id, "prefill", prompt, ttl=1800)
    await call.message.answer(f"▸ <i>{prompt}</i>\n\n{t(lang, 'prefill_hint')}", parse_mode="HTML")


@router.message(Command("help"))
async def cmd_help(message: Message, lang: str = "ru") -> None:
    await message.answer(t(lang, "help"), parse_mode="HTML",
                         reply_markup=main_menu(lang))


@router.message(Command("new"))
async def cmd_new(message: Message, lang: str = "ru", **_) -> None:
    await store.drop(message.chat.id, "session")
    model = (await store.get(message.chat.id, "model") or settings.default_model)
    await message.answer(t(lang, "new_chat", model=model.split("/")[-1]),
                         parse_mode="HTML", reply_markup=main_menu(lang))
    await message.answer("👇", reply_markup=quick_prompts(lang))


@router.message(Command("cancel"))
async def cmd_cancel(message: Message, lang: str, state: FSMContext) -> None:
    await state.clear()
    await message.answer(t(lang, "cancelled"), reply_markup=main_menu(lang))


@router.message(F.text.in_(MENU_ACTIONS.keys()))
async def menu_button(message: Message, token: str, lang: str = "ru",
                      state: FSMContext | None = None) -> None:
    """Кнопки нижнего меню ведут туда же, куда команды."""
    action = MENU_ACTIONS[message.text]
    if state is not None:
        await state.clear()
    if action == "new":
        await cmd_new(message, lang)
    elif action == "balance":
        from bot.routers.billing import show_balance

        await show_balance(message, token, lang)
    elif action == "help":
        await cmd_help(message, lang)
    elif action == "model":
        from bot.routers.models import show_models

        await show_models(message, token, lang)
    elif action == "image":
        from bot.routers.image import start_wizard

        await start_wizard(message, token, lang, state)
    elif action == "video":
        from bot.routers.video import start_wizard

        await start_wizard(message, token, lang, state)
    elif action == "studio":
        from bot.routers.studio import show_intro

        await show_intro(message, token, lang)
    elif action == "profile":
        from bot.routers.account import show_profile

        await show_profile(message, token, lang)
    elif action == "more":
        await message.answer(t(lang, "more_title"), parse_mode="HTML", reply_markup=more_menu(lang))


@router.callback_query(F.data == "nav:x")
async def close(call: CallbackQuery) -> None:
    await call.answer()
    try:
        await call.message.delete()
    except Exception:
        pass
