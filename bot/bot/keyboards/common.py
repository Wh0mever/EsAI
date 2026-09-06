"""Клавиатуры бота."""
from __future__ import annotations

from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
    WebAppInfo,
)

from bot.texts import quick_label, t

QUICK_KEYS = ("article", "image", "translate", "document", "code", "study", "travel", "idea")

# Подписи нижнего меню на трёх языках. По ним же узнаём нажатие: Telegram
# присылает кнопку обычным текстом.
MENU_ROWS = {
    "ru": [["💬 Новый чат", "🧠 Модель"],
           ["🎨 Картинка", "🎬 Видео", "🎞 Студия"],
           ["💳 Баланс", "👤 Профиль", "☰ Ещё"]],
    "en": [["💬 New chat", "🧠 Model"],
           ["🎨 Image", "🎬 Video", "🎞 Studio"],
           ["💳 Balance", "👤 Profile", "☰ More"]],
    "kg": [["💬 Жаңы чат", "🧠 Модель"],
           ["🎨 Сүрөт", "🎬 Видео", "🎞 Студия"],
           ["💳 Баланс", "👤 Профиль", "☰ Дагы"]],
}
_ACTIONS = ["new", "model", "image", "video", "studio", "balance", "profile", "more"]

MENU_ACTIONS: dict[str, str] = {}
for _rows in MENU_ROWS.values():
    for _label, _action in zip([b for row in _rows for b in row], _ACTIONS):
        MENU_ACTIONS[_label] = _action
# Старые подписи из первой версии — чтобы кнопки уже открытых чатов не умерли.
MENU_ACTIONS.update({"❓ Помощь": "help", "❓ Help": "help", "❓ Жардам": "help"})


def main_menu(lang: str = "ru") -> ReplyKeyboardMarkup:
    """Постоянное меню внизу: до главного всегда один тап."""
    rows = MENU_ROWS.get(lang) or MENU_ROWS["ru"]
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text=b) for b in row] for row in rows],
        resize_keyboard=True, is_persistent=True,
    )


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


def paywall(lang: str, site: str = "", *, free_model: bool = False) -> InlineKeyboardMarkup:
    """Кнопки пейвола.

    Внутри бота цифровые товары продаются только за Telegram Stars, поэтому
    «Пополнить» открывает /topup со Stars, а не ссылку на карту.
    """
    rows = [[InlineKeyboardButton(text=t(lang, "btn_topup"), callback_data="b:topup")]]
    if free_model:
        rows.append([InlineKeyboardButton(text=t(lang, "btn_free_model"),
                                          callback_data="m:free")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def close_button(lang: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text=t(lang, "btn_close"), callback_data="nav:x")]])


def webapp_button(text: str, url: str) -> InlineKeyboardButton:
    """Кнопка Mini App: сайт откроется внутри Telegram с автологином."""
    return InlineKeyboardButton(text=text, web_app=WebAppInfo(url=url))


def rows_of(buttons: list[InlineKeyboardButton], per_row: int = 2) -> list[list[InlineKeyboardButton]]:
    return [buttons[i:i + per_row] for i in range(0, len(buttons), per_row)]


def more_menu(lang: str) -> InlineKeyboardMarkup:
    """«☰ Ещё»: всё, чему не хватило места в нижнем меню."""
    labels = {
        "ru": ["📜 История чатов", "🧠 Память", "🤝 Пригласить друзей", "💸 Перевести кредиты",
               "🎟 Промокод", "🌐 Язык", "🔔 Уведомления", "📰 Блог", "❓ FAQ",
               "🆘 Поддержка", "⭐ Оставить отзыв", "🔗 Связать с сайтом"],
        "en": ["📜 Chat history", "🧠 Memory", "🤝 Invite friends", "💸 Transfer credits",
               "🎟 Promo code", "🌐 Language", "🔔 Notifications", "📰 Blog", "❓ FAQ",
               "🆘 Support", "⭐ Leave feedback", "🔗 Link site account"],
        "kg": ["📜 Чат тарыхы", "🧠 Эс", "🤝 Досторду чакыруу", "💸 Кредит которуу",
               "🎟 Промокод", "🌐 Тил", "🔔 Билдирүүлөр", "📰 Блог", "❓ FAQ",
               "🆘 Колдоо", "⭐ Пикир калтыруу", "🔗 Сайт менен байланыштыруу"],
    }.get(lang) or []
    actions = ["history", "memory", "referral", "transfer", "promo", "lang", "notify", "blog",
               "faq", "support", "feedback", "link"]
    buttons = [InlineKeyboardButton(text=label, callback_data=f"more:{action}")
               for label, action in zip(labels, actions)]
    rows = rows_of(buttons, 2)
    rows.append([InlineKeyboardButton(text=t(lang, "btn_close"), callback_data="nav:x")])
    return InlineKeyboardMarkup(inline_keyboard=rows)
