"""Первый экран, меню и справка."""
from __future__ import annotations

import logging
import re

from aiogram import F, Router
from aiogram.filters import Command, CommandObject, CommandStart
from aiogram.types import CallbackQuery, Message

from bot.config import settings
from bot.keyboards.common import (
    MENU_ACTIONS,
    language_choice,
    main_menu,
    quick_prompts,
)
from bot.services.api import ApiError, api
from bot.services.state import store
from bot.texts import quick_prompt, t

logger = logging.getLogger(__name__)
router = Router(name="start")

REF_RE = re.compile(r"^ref_([A-Za-z0-9]{4,32})$")
PROMO_RE = re.compile(r"^promo_([A-Za-z0-9_-]{2,48})$")


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


@router.message(CommandStart(deep_link=True))
@router.message(CommandStart())
async def cmd_start(message: Message, command: CommandObject | None = None,
                   token: str = "", lang: str = "ru", auth_payload: dict | None = None) -> None:
    telegram_id = message.from_user.id
    ref, promo = _parse_payload(getattr(command, "args", "") or "")

    # Реферальную ссылку и промокод нужно передать в момент создания аккаунта,
    # поэтому при первом /start токен получаем заново, уже с ними.
    if ref or promo:
        known = await store.get(telegram_id, "seen_start")
        if not known:
            await store.drop_token(telegram_id)
            try:
                auth_payload = await api.auth_telegram(
                    {
                        "id": telegram_id,
                        "first_name": message.from_user.first_name or "",
                        "last_name": message.from_user.last_name or "",
                        "username": message.from_user.username or "",
                        "language_code": message.from_user.language_code or "",
                    },
                    chat_id=message.chat.id, ref=ref, promo=promo,
                )
                token = auth_payload["access"]
                await store.set_token(telegram_id, token)
            except ApiError:
                logger.exception("повторный вход с реф-кодом не удался")

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

    if not user:
        try:
            user = await api.balance(token, lang=lang, telegram_id=telegram_id)
        except ApiError:
            user = {}
    model = (await store.get(telegram_id, "model") or settings.default_model).split("/")[-1]
    await message.answer(
        t(lang, "welcome_back",
          name=message.from_user.first_name or "",
          balance=user.get("balance_tokens", "—"), model=model),
        parse_mode="HTML", reply_markup=main_menu(lang),
    )
    await message.answer("👇", reply_markup=quick_prompts(lang))


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
async def quick_start(call: CallbackQuery, token: str, lang: str) -> None:
    """Быстрая подсказка: подставляем начало фразы, человек дописывает своё."""
    key = call.data.split(":", 1)[1]
    prompt = quick_prompt(lang, key)
    await call.answer()
    await store.set(call.from_user.id, "prefill", prompt, ttl=1800)
    await call.message.answer(f"▸ <i>{prompt}</i>\n\nДопишите и отправьте.",
                              parse_mode="HTML")


@router.message(Command("help"))
async def cmd_help(message: Message, lang: str = "ru") -> None:
    await message.answer(t(lang, "help"), parse_mode="HTML",
                         reply_markup=main_menu(lang))


@router.message(Command("new"))
async def cmd_new(message: Message, lang: str = "ru") -> None:
    await store.drop(message.from_user.id, "session")
    model = (await store.get(message.from_user.id, "model") or settings.default_model)
    await message.answer(t(lang, "new_chat", model=model.split("/")[-1]),
                         parse_mode="HTML", reply_markup=main_menu(lang))
    await message.answer("👇", reply_markup=quick_prompts(lang))


@router.message(Command("balance"))
async def cmd_balance(message: Message, token: str, lang: str = "ru") -> None:
    try:
        data = await api.balance(token, lang=lang, telegram_id=message.from_user.id)
    except ApiError:
        await message.answer(t(lang, "server_down"))
        return
    tier_key = {"paid": "tier_paid", "unlimited": "tier_unlimited"}.get(
        data.get("tier"), "tier_free")
    if data.get("is_unlimited"):
        tier_key = "tier_unlimited"
    await message.answer(
        t(lang, "balance", balance=data.get("balance_tokens", 0), tier=t(lang, tier_key)),
        parse_mode="HTML",
    )
    await message.answer(t(lang, "topup_hint", site=settings.site_base_url),
                         disable_web_page_preview=True)


@router.message(F.text.in_(MENU_ACTIONS.keys()))
async def menu_button(message: Message, token: str, lang: str = "ru") -> None:
    """Кнопки нижнего меню ведут туда же, куда команды."""
    action = MENU_ACTIONS[message.text]
    if action == "new":
        await cmd_new(message, lang)
    elif action == "balance":
        await cmd_balance(message, token, lang)
    elif action == "help":
        await cmd_help(message, lang)
    elif action == "model":
        from bot.routers.models import show_models

        await show_models(message, token, lang)


@router.callback_query(F.data == "nav:x")
async def close(call: CallbackQuery) -> None:
    await call.answer()
    try:
        await call.message.delete()
    except Exception:
        pass
