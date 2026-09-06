"""Выбор модели: те же группы и пометки, что на сайте."""
from __future__ import annotations

import logging

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from bot.config import settings
from bot.keyboards.common import paywall
from bot.services.api import ApiError, api
from bot.services.state import store
from bot.texts import t

logger = logging.getLogger(__name__)
router = Router(name="models")

PAGE = 8
# Группы и порядок — как в списке моделей на сайте.
GROUPS = [
    ("free", "🎁 Бесплатные"),
    ("recommended", "⭐ Рекомендуемые"),
    ("chat", "💬 Для общения"),
    ("writing", "✍️ Тексты и SEO"),
    ("coding", "💻 Программирование"),
    ("reasoning", "🧠 Анализ и рассуждения"),
    ("search", "🌐 Поиск в интернете"),
    ("image", "🖼 Изображения"),
    ("video", "🎬 Видео"),
    ("fast", "⚡️ Быстрые"),
    ("budget", "💰 Экономичные"),
]


def _badges(model: dict) -> str:
    marks = []
    if model.get("supports_vision"):
        marks.append("👁")
    if model.get("category") == "image":
        marks.append("🖼")
    if model.get("category") == "video":
        marks.append("🎬")
    if model.get("category") == "search":
        marks.append("🌐")
    return "".join(marks)


def _in_group(model: dict, group: str) -> bool:
    if group == "free":
        return bool(model.get("is_free"))
    if group == "recommended":
        return bool(model.get("recommended"))
    return model.get("category") == group


def _price(model: dict) -> str:
    coefficient = model.get("markup_coefficient")
    if not coefficient:
        return ""
    category = model.get("category")
    if category == "video":
        return f"{coefficient:g} кр/с"
    if category == "image":
        return f"{coefficient:g} кр"
    return f"{coefficient:g} кр/1000"


async def _fetch(token: str, lang: str, telegram_id: int) -> list:
    models = await store.get(telegram_id, "models_cache")
    if models:
        return models
    models = await api.models(token, lang=lang, telegram_id=telegram_id)
    await store.set(telegram_id, "models_cache", models, ttl=600)
    return models


def _groups_keyboard(models: list) -> InlineKeyboardMarkup:
    rows, row = [], []
    for key, title in GROUPS:
        count = sum(1 for m in models if _in_group(m, key))
        if not count:
            continue
        row.append(InlineKeyboardButton(text=f"{title} ({count})",
                                        callback_data=f"m:g:{key}:0"))
        if len(row) == 2:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    rows.append([InlineKeyboardButton(text="✖ Закрыть", callback_data="nav:x")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _list_keyboard(models: list, group: str, page: int) -> InlineKeyboardMarkup:
    selected = [m for m in models if _in_group(m, group)]
    total = max(1, (len(selected) + PAGE - 1) // PAGE)
    page = max(0, min(page, total - 1))
    rows = []
    for model in selected[page * PAGE:(page + 1) * PAGE]:
        lock = "🔒 " if model.get("locked") else ""
        price = _price(model)
        label = f"{lock}{model.get('name')} {_badges(model)}".strip()
        if price and not model.get("locked"):
            label = f"{label} · {price}"
        rows.append([InlineKeyboardButton(text=label[:64],
                                          callback_data=f"m:s:{model.get('id')}")])
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton(text="◀", callback_data=f"m:g:{group}:{page - 1}"))
    nav.append(InlineKeyboardButton(text=f"{page + 1}/{total}", callback_data="nav:noop"))
    if page < total - 1:
        nav.append(InlineKeyboardButton(text="▶", callback_data=f"m:g:{group}:{page + 1}"))
    if len(nav) > 1:
        rows.append(nav)
    rows.append([InlineKeyboardButton(text="↩ Группы", callback_data="m:home")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


async def show_models(message: Message, token: str, lang: str) -> None:
    try:
        models = await _fetch(token, lang, message.from_user.id)
    except ApiError:
        await message.answer(t(lang, "server_down"))
        return
    current = (await store.get(message.from_user.id, "model") or settings.default_model)
    await message.answer(
        t(lang, "models_title", model=current.split("/")[-1]),
        parse_mode="HTML", reply_markup=_groups_keyboard(models),
    )


@router.message(Command("model"))
async def cmd_model(message: Message, token: str, lang: str = "ru") -> None:
    await show_models(message, token, lang)


@router.callback_query(F.data == "m:home")
async def back_to_groups(call: CallbackQuery, token: str, lang: str) -> None:
    models = await _fetch(token, lang, call.from_user.id)
    current = (await store.get(call.from_user.id, "model") or settings.default_model)
    await call.answer()
    await call.message.edit_text(
        t(lang, "models_title", model=current.split("/")[-1]),
        parse_mode="HTML", reply_markup=_groups_keyboard(models))


@router.callback_query(F.data.startswith("m:g:"))
async def open_group(call: CallbackQuery, token: str, lang: str) -> None:
    _, _, group, page = call.data.split(":", 3)
    models = await _fetch(token, lang, call.from_user.id)
    title = dict(GROUPS).get(group, group)
    await call.answer()
    await call.message.edit_text(
        f"<b>{title}</b>\nЦена — за 1000 токенов; у картинок за изображение, у видео за секунду.",
        parse_mode="HTML", reply_markup=_list_keyboard(models, group, int(page)))


@router.callback_query(F.data.startswith("m:s:"))
async def pick_model(call: CallbackQuery, token: str, lang: str) -> None:
    model_id = call.data.split(":")[2]
    models = await _fetch(token, lang, call.from_user.id)
    model = next((m for m in models if str(m.get("id")) == model_id), None)
    if not model:
        await call.answer()
        return

    if model.get("locked"):
        await call.answer(t(lang, "model_locked"), show_alert=True)
        await call.message.answer(t(lang, "paywall_premium"), parse_mode="HTML",
                                  reply_markup=paywall(lang, settings.site_base_url,
                                                       free_model=True))
        return

    identifier = model.get("openrouter_id") or model.get("name")
    await store.set(call.from_user.id, "model", identifier)
    await call.answer(t(lang, "model_set", model=model.get("name")).replace("<b>", "")
                      .replace("</b>", ""))
    description = (model.get("description") or "").strip()
    price = _price(model)
    lines = [t(lang, "model_set", model=model.get("name"))]
    if description:
        lines.append(description[:300])
    if price:
        lines.append(f"Цена: {price}")
    await call.message.edit_text("\n".join(lines), parse_mode="HTML")


@router.callback_query(F.data == "m:free")
async def pick_free(call: CallbackQuery, token: str, lang: str) -> None:
    """Быстрый выход из пейвола: показать только бесплатные модели."""
    models = await _fetch(token, lang, call.from_user.id)
    await call.answer()
    await call.message.answer(
        "🎁 <b>Бесплатные модели</b>", parse_mode="HTML",
        reply_markup=_list_keyboard(models, "free", 0))


@router.callback_query(F.data == "nav:noop")
async def noop(call: CallbackQuery) -> None:
    await call.answer()
