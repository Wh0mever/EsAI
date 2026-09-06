"""Клавиатуры бота."""
from __future__ import annotations

from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
)

from bot.texts import quick_label, t

QUICK_KEYS = ("article", "image", "translate", "document", "code", "study", "travel", "idea")


def main_menu(lang: str = "ru") -> ReplyKeyboardMarkup:
    """Постоянное меню внизу: до главного всегда один тап."""
    rows = {
        "ru": [["💬 Новый чат", "🧠 Модель"], ["💳 Баланс", "❓ Помощь"]],
        "en": [["💬 New chat", "🧠 Model"], ["💳 Balance", "❓ Help"]],
        "kg": [["💬 Жаңы чат", "🧠 Модель"], ["💳 Баланс", "❓ Жардам"]],
    }.get(lang) or [["💬 Новый чат", "🧠 Модель"], ["💳 Баланс", "❓ Помощь"]]
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text=b) for b in row] for row in rows],
        resize_keyboard=True, is_persistent=True,
    )


# Подписи меню на всех языках — по ним узнаём нажатие, не завися от языка.
MENU_ACTIONS = {
    "💬 Новый чат": "new", "💬 New chat": "new", "💬 Жаңы чат": "new",
    "🧠 Модель": "model", "🧠 Model": "model",
    "💳 Баланс": "balance", "💳 Balance": "balance",
    "❓ Помощь": "help", "❓ Help": "help", "❓ Жардам": "help",
}


def language_choice() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="🇷🇺 Русский", callback_data="lang:ru"),
        InlineKeyboardButton(text="🇬🇧 English", callback_data="lang:en"),
        InlineKeyboardButton(text="🇰🇬 Кыргызча", callback_data="lang:kg"),
    ]])


def quick_prompts(lang: str = "ru") -> InlineKeyboardMarkup:
    """Восемь стартовых подсказок — те же, что на сайте."""
    buttons = [InlineKeyboardButton(text=quick_label(lang, key), callback_data=f"q:{key}")
               for key in QUICK_KEYS]
    rows = [buttons[i:i + 2] for i in range(0, len(buttons), 2)]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def answer_actions(lang: str, *, has_sources: bool = False,
                   has_reasoning: bool = False) -> InlineKeyboardMarkup:
    rows = [[
        InlineKeyboardButton(text=t(lang, "btn_retry"), callback_data="c:re"),
        InlineKeyboardButton(text=t(lang, "btn_continue"), callback_data="c:cont"),
    ]]
    extra = []
    if has_sources:
        extra.append(InlineKeyboardButton(text=t(lang, "btn_sources"), callback_data="c:src"))
    if has_reasoning:
        extra.append(InlineKeyboardButton(text=t(lang, "btn_reasoning"), callback_data="c:rs"))
    if extra:
        rows.append(extra)
    return InlineKeyboardMarkup(inline_keyboard=rows)


def paywall(lang: str, site: str, *, free_model: bool = False) -> InlineKeyboardMarkup:
    """Кнопки пейвола.

    Внутри бота цифровые товары можно продавать только за Telegram Stars —
    поэтому здесь не кнопка оплаты, а обычная ссылка на сайт, где у человека
    тот же аккаунт и тот же баланс.
    """
    rows = [[InlineKeyboardButton(text=t(lang, "btn_topup"), url=f"{site}/pricing")]]
    if free_model:
        rows.append([InlineKeyboardButton(text=t(lang, "btn_free_model"),
                                          callback_data="m:free")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def close_button(lang: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text=t(lang, "btn_close"), callback_data="nav:x")]])
