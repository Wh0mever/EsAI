"""Выбор модели: те же группы и пометки, что на сайте."""
from __future__ import annotations

import asyncio
import logging
import math

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from bot.config import settings
from bot.keyboards.common import paywall
from bot.services.api import ApiError, api
from bot.services.state import store
from bot.services.tg_format import esc
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


# Токены→кредиты: те же числа, что у бэкенда (settings.TOKEN_CREDIT_DIVISOR и
# CREDIT_CALC_IMAGE_{PROMPT,OUTPUT}_TOKENS_ESTIMATE, см. core/plans/credit_value).
TOKEN_CREDIT_DIVISOR = 1000
IMAGE_TOKENS_ESTIMATE = 150 + 1300


def is_flux_image_model(model_ref) -> bool:
    """FLUX идёт через images-API и билится плоско — зеркало ai/model_billing."""
    name = str(model_ref or "").lower().split(":")[0]
    return name.startswith("black-forest-labs/") or "flux.2" in name


def _server_credits(value) -> int | None:
    """Целая цена с сервера или None, если цены нет."""
    if value in (None, "") or isinstance(value, bool):
        return None
    try:
        credits = int(float(value))
    except (TypeError, ValueError):
        return None
    return credits if credits >= 1 else None


def price_from(params: dict | None) -> int | None:
    """«от N кр»: самая дешёвая ячейка таблиц цен ролика с сервера (общей и по
    пропорциям) — как price_from у видеостудии.

    None — сервер цены не дал: в режиме цен «наценка» у модели нет
    себестоимости, или таблица не посчиталась. «Секунды × тариф» не считаем:
    у видео тариф — не цена (у Seedance он вовсе 0).
    """
    params = params or {}
    tables = [params.get("price_table")]
    by_aspect = params.get("price_table_by_aspect")
    if isinstance(by_aspect, dict):
        tables += list(by_aspect.values())
    best = None
    for table in tables:
        for row in (table.values() if isinstance(table, dict) else ()):
            for cell in (row.values() if isinstance(row, dict) else ()):
                credits = _server_credits(cell)
                if credits and (best is None or credits < best):
                    best = credits
    return best


async def video_prices(token: str, lang: str, chat_id: int, models: list) -> dict:
    """«от N» для видео-моделей списка: {openrouter_id: кредиты или None}.

    Цену ролика знает только таблица сервера (ai/video-params) — её же берёт
    мастер видео, с тем же ключом кэша: в списке и на карточке одно число.
    Закрытым моделям цену не показываем, поэтому и не спрашиваем.
    """
    from bot.routers.video import _params  # video сам импортирует этот модуль

    ids = [str(m.get("openrouter_id")) for m in models
           if m.get("category") == "video" and m.get("openrouter_id") and not m.get("locked")]
    if not ids:
        return {}
    found = await asyncio.gather(*(_params(token, lang, chat_id, i) for i in ids))
    return {i: price_from(p) for i, p in zip(ids, found)}


def image_credits(model: dict) -> int | None:
    """Сколько кредитов реально спишет бэкенд за ОДНУ картинку этой моделью.

    markup_coefficient у image-моделей задан «за картинку», но плоско по нему
    списываются только FLUX (core/ai/model_billing.flux_charge_credits).
    Остальные (Nano Banana: google/gemini-*-image) идут через chat-completions и
    билятся токенной формулой — показывать им coeff значило врать почти вдвое
    (coeff=4 → списывается 6). Формула — как в core/plans/credit_value.

    У FLUX главнее цена сервера (credits_per_image): в режиме цен «наценка» она
    считается от себестоимости и из коэффициента не выводится. Без неё —
    legacy-формула: сервер без этого поля режима «наценка» не знает.
    """
    if is_flux_image_model(model.get("openrouter_id")):
        server = _server_credits(model.get("credits_per_image"))
        if server:
            return server
    coeff = model.get("markup_coefficient")
    if not coeff:
        return None
    try:
        coeff = float(coeff)
    except (TypeError, ValueError):
        return None
    if coeff <= 0:
        coeff = 1.0
    if is_flux_image_model(model.get("openrouter_id")):
        return max(1, int(coeff))
    return max(1, math.ceil(IMAGE_TOKENS_ESTIMATE * coeff / TOKEN_CREDIT_DIVISOR))


def _price(model: dict, video_from: int | None = None) -> str:
    category = model.get("category")
    if category == "video":
        # Тариф видео — не цена ролика: у ролика нижняя граница по себестоимости,
        # а в режиме цен «наценка» тариф не участвует вовсе. Только «от N кр» из
        # таблицы сервера (video_prices); нет её — нет и подписи.
        return f"от {video_from} кр" if video_from else ""
    if category == "image":
        credits = image_credits(model)
        if not credits:
            return ""
        # У токенных image-моделей точная цена зависит от ответа провайдера,
        # поэтому «≈» — иначе обещаем ровное число, которого не будет.
        return f"{credits} кр" if is_flux_image_model(model.get("openrouter_id")) \
            else f"≈{credits} кр"
    coefficient = model.get("markup_coefficient")
    if not coefficient:
        return ""
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


def _page_models(models: list, group: str, page: int) -> tuple[list, int, int]:
    """Модели страницы группы, номер страницы (в пределах) и число страниц."""
    selected = [m for m in models if _in_group(m, group)]
    total = max(1, (len(selected) + PAGE - 1) // PAGE)
    page = max(0, min(page, total - 1))
    return selected[page * PAGE:(page + 1) * PAGE], page, total


def _list_keyboard(models: list, group: str, page: int,
                   prices: dict | None = None) -> InlineKeyboardMarkup:
    """prices — «от N» видео-моделей страницы (video_prices)."""
    on_page, page, total = _page_models(models, group, page)
    rows = []
    for model in on_page:
        lock = "🔒 " if model.get("locked") else ""
        price = _price(model, (prices or {}).get(model.get("openrouter_id")))
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
        t(lang, "models_title", model=esc(current.split("/")[-1])),
        parse_mode="HTML", reply_markup=_groups_keyboard(models),
    )


@router.message(Command("model"))
async def cmd_model(message: Message, token: str, lang: str = "ru") -> None:
    await show_models(message, token, lang)


async def _fetch_or_report(call: CallbackQuery, token: str, lang: str) -> list | None:
    """Список моделей для кнопки. None — API отказал и человеку уже сказано.

    Без этого ApiError (429/401/5xx) улетает наружу: кнопка «крутится» и человек
    не получает вообще ничего. Ответ на callback даём ДО похода в API.
    """
    try:
        return await _fetch(token, lang, call.from_user.id)
    except ApiError:
        await call.message.answer(t(lang, "server_down"))
        return None


@router.callback_query(F.data == "m:home")
async def back_to_groups(call: CallbackQuery, token: str, lang: str) -> None:
    await call.answer()
    models = await _fetch_or_report(call, token, lang)
    if models is None:
        return
    current = (await store.get(call.from_user.id, "model") or settings.default_model)
    await call.message.edit_text(
        t(lang, "models_title", model=esc(current.split("/")[-1])),
        parse_mode="HTML", reply_markup=_groups_keyboard(models))


@router.callback_query(F.data.startswith("m:g:"))
async def open_group(call: CallbackQuery, token: str, lang: str) -> None:
    _, _, group, page = call.data.split(":", 3)
    await call.answer()
    models = await _fetch_or_report(call, token, lang)
    if models is None:
        return
    title = dict(GROUPS).get(group, group)
    page = int(page)
    prices = await video_prices(token, lang, call.from_user.id, _page_models(models, group, page)[0])
    await call.message.edit_text(
        f"<b>{title}</b>\nЦена — за 1000 токенов; у картинок за изображение; у видео — «от»: "
        "самый дешёвый ролик.",
        parse_mode="HTML", reply_markup=_list_keyboard(models, group, page, prices))


@router.callback_query(F.data.startswith("m:s:"))
async def pick_model(call: CallbackQuery, token: str, lang: str) -> None:
    model_id = call.data.split(":")[2]
    try:
        models = await _fetch(token, lang, call.from_user.id)
    except ApiError:
        # Отвечаем ровно один раз: ниже call.answer() уже с именем модели.
        await call.answer()
        await call.message.answer(t(lang, "server_down"))
        return
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
    prices = await video_prices(token, lang, call.from_user.id, [model])
    price = _price(model, prices.get(str(model.get("openrouter_id"))))
    # Имя и описание пишут в админке: «<» или «&» в них Telegram считал
    # разметкой и отвергал сообщение целиком — модель выбиралась, а карточка
    # не менялась. Режем ДО экранирования, чтобы не разрубить «&amp;».
    lines = [t(lang, "model_set", model=esc(model.get("name")))]
    if description:
        lines.append(esc(description[:300]))
    if price:
        lines.append(f"Цена: {price}")
    await call.message.edit_text("\n".join(lines), parse_mode="HTML")


@router.callback_query(F.data == "m:free")
async def pick_free(call: CallbackQuery, token: str, lang: str) -> None:
    """Быстрый выход из пейвола: показать только бесплатные модели."""
    await call.answer()
    models = await _fetch_or_report(call, token, lang)
    if models is None:
        return
    prices = await video_prices(token, lang, call.from_user.id, _page_models(models, "free", 0)[0])
    await call.message.answer(
        "🎁 <b>Бесплатные модели</b>", parse_mode="HTML",
        reply_markup=_list_keyboard(models, "free", 0, prices))


@router.callback_query(F.data == "nav:noop")
async def noop(call: CallbackQuery) -> None:
    await call.answer()
