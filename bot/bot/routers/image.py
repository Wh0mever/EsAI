"""Мастер картинок: промпт → модель и пропорции → результат с кнопками.

«Нарисуй …» прямо в чате работает и без мастера — бэкенд сам переключает
image-модель. Мастер нужен, когда человек хочет выбрать пропорции или модель
и не хочет угадывать слова.
"""
from __future__ import annotations

import logging
import re

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command, CommandObject
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from bot.keyboards.common import rows_of
from bot.routers.chat import run_chat, site_url
from bot.routers.models import _fetch, _price
from bot.services.api import ApiError, api
from bot.services.state import store
from bot.services.tg_format import esc, plain
from bot.texts import register_texts, t

logger = logging.getLogger(__name__)
router = Router(name="image")

ASPECT_RATIOS = ["1:1", "16:9", "9:16", "4:3", "3:4", "3:2", "2:3", "4:5"]
DEFAULT_EDIT_MODEL = "google/gemini-2.5-flash-image"

register_texts({
    "ru": {
        "img_ask": "🎨 Опишите картинку одной фразой — или пришлите фото с подписью, что изменить.",
        "img_card": ("🎨 <b>{prompt}</b>\n\nМодель: <b>{model}</b> · {price}\n"
                     "Пропорции: <b>{ar}</b>\nБаланс: {balance} кр"),
        "img_go": "🎨 Нарисовать",
        "img_change_model": "🧠 Модель",
        "img_again": "🔁 Ещё вариант",
        "img_other_ar": "📐 Другие пропорции",
        "img_edit": "✏️ Изменить",
        "img_download": "📥 Оригинал",
        "img_edit_ask": "✏️ Что изменить? Например: «убери фон», «добавь снег», «сделай ярче».",
        "img_no_models": "Модели для картинок сейчас недоступны.",
        "img_cancelled": "Отменено.",
        "img_pick_ar": "📐 Выберите пропорции:",
        "img_pick_model": "🧠 Выберите модель:",
        "img_result_caption": "{prompt} · {model} · {ar}",
        "img_no_last": "Сначала нарисуйте картинку: /image",
        "img_no_vision": ("Сейчас нет модели, которая умеет менять готовое фото. "
                          "Опишите картинку словами — нарисую заново: /image"),
    },
    "en": {
        "img_ask": "🎨 Describe the image in one phrase — or send a photo with a caption saying what to change.",
        "img_card": ("🎨 <b>{prompt}</b>\n\nModel: <b>{model}</b> · {price}\n"
                     "Aspect ratio: <b>{ar}</b>\nBalance: {balance} cr"),
        "img_go": "🎨 Draw",
        "img_change_model": "🧠 Model",
        "img_again": "🔁 Another one",
        "img_other_ar": "📐 Other ratio",
        "img_edit": "✏️ Edit",
        "img_download": "📥 Original",
        "img_edit_ask": "✏️ What should change? E.g. “remove background”, “add snow”, “make it brighter”.",
        "img_no_models": "Image models are unavailable right now.",
        "img_cancelled": "Cancelled.",
        "img_pick_ar": "📐 Pick an aspect ratio:",
        "img_pick_model": "🧠 Pick a model:",
        "img_result_caption": "{prompt} · {model} · {ar}",
        "img_no_last": "Draw an image first: /image",
        "img_no_vision": ("No model that can edit an existing photo is available right now. "
                          "Describe the image in words and I will draw a new one: /image"),
    },
    "kg": {
        "img_ask": "🎨 Сүрөттү бир сүйлөм менен сүрөттөңүз — же эмнени өзгөртүү керектигин жазып сүрөт жөнөтүңүз.",
        "img_card": ("🎨 <b>{prompt}</b>\n\nМодель: <b>{model}</b> · {price}\n"
                     "Пропорция: <b>{ar}</b>\nБаланс: {balance} кр"),
        "img_go": "🎨 Тартуу",
        "img_change_model": "🧠 Модель",
        "img_again": "🔁 Дагы бир вариант",
        "img_other_ar": "📐 Башка пропорция",
        "img_edit": "✏️ Өзгөртүү",
        "img_download": "📥 Оригинал",
        "img_edit_ask": "✏️ Эмнени өзгөртөлү? Мисалы: «фонду алып сал», «кар кош».",
        "img_no_models": "Сүрөт моделдери азыр жеткиликсиз.",
        "img_cancelled": "Жокко чыгарылды.",
        "img_pick_ar": "📐 Пропорцияны тандаңыз:",
        "img_pick_model": "🧠 Моделди тандаңыз:",
        "img_result_caption": "{prompt} · {model} · {ar}",
        "img_no_last": "Адегенде сүрөт тартыңыз: /image",
        "img_no_vision": ("Даяр сүрөттү өзгөртө турган модель азыр жок. "
                          "Сүрөттү сөз менен сүрөттөңүз — жаңысын тартам: /image"),
    },
})


class ImageWizard(StatesGroup):
    prompt = State()
    edit = State()


async def _image_models(token: str, lang: str, telegram_id: int) -> list:
    models = await _fetch(token, lang, telegram_id)
    return [m for m in models if (m.get("category") == "image") and m.get("openrouter_id")]


async def _models_or_none(message: Message, token: str, lang: str,
                          telegram_id: int) -> list | None:
    """Image-модели для экрана. None — человеку уже сказано, дальше идти нельзя.

    Раньше ApiError (429/401/5xx) улетал наружу из мастера: на /image человек не
    видел ничего, на кнопке — тишина и вечные часики.
    """
    try:
        models = await _image_models(token, lang, telegram_id)
    except ApiError:
        logger.warning("картинки: список моделей недоступен для %s", telegram_id)
        await message.answer(t(lang, "server_down"))
        return None
    if not models:
        await message.answer(t(lang, "img_no_models"))
        return None
    return models


def _default_model(models: list) -> dict | None:
    for m in models:
        if DEFAULT_EDIT_MODEL in (m.get("openrouter_id") or "") and not m.get("locked"):
            return m
    for m in models:
        if not m.get("locked"):
            return m
    return models[0] if models else None


def _vision_model(models: list) -> dict | None:
    """Модель для РЕДАКТИРОВАНИЯ фото — только та, что реально видит картинку.

    Без supports_vision бэкенд молча выбрасывает вложение и рисует новое
    изображение по тексту: человек платит за «редактирование», которого не было.
    Лучше отказать заранее, чем списать за не тот результат.
    """
    vision = [m for m in models if m.get("supports_vision")]
    if not vision:
        return None
    preferred = [m for m in vision
                 if DEFAULT_EDIT_MODEL in (m.get("openrouter_id") or "") and not m.get("locked")]
    unlocked = [m for m in vision if not m.get("locked")]
    # Заблокированную берём последней: пусть бэкенд покажет пейвол, а не тишину.
    return (preferred or unlocked or vision)[0]


async def _edit_model(message: Message, token: str, lang: str,
                      telegram_id: int) -> str | None:
    """openrouter_id модели для правки фото; None — генерацию не запускаем."""
    models = await _models_or_none(message, token, lang, telegram_id)
    if models is None:
        return None
    chosen = _vision_model(models)
    if chosen is None:
        await message.answer(t(lang, "img_no_vision"))
        return None
    return chosen.get("openrouter_id") or DEFAULT_EDIT_MODEL


def _card_keyboard(lang: str, ar: str) -> InlineKeyboardMarkup:
    ratios = [InlineKeyboardButton(text=("• " if r == ar else "") + r, callback_data=f"i:ar:{r}")
              for r in ASPECT_RATIOS]
    rows = rows_of(ratios, 4)
    rows.append([InlineKeyboardButton(text=t(lang, "img_go"), callback_data="i:go"),
                 InlineKeyboardButton(text=t(lang, "img_change_model"), callback_data="i:models")])
    rows.append([InlineKeyboardButton(text=t(lang, "btn_close"), callback_data="i:x")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def result_keyboard(lang: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=t(lang, "img_again"), callback_data="i:again"),
         InlineKeyboardButton(text=t(lang, "img_other_ar"), callback_data="i:pickar")],
        [InlineKeyboardButton(text=t(lang, "img_edit"), callback_data="i:edit"),
         InlineKeyboardButton(text=t(lang, "img_download"), callback_data="i:dl")],
    ])


async def _draft(telegram_id: int) -> dict:
    return await store.get(telegram_id, "img_draft") or {}


async def _save_draft(telegram_id: int, draft: dict) -> None:
    await store.set(telegram_id, "img_draft", draft, ttl=3600)


async def _show_card(message: Message, token: str, lang: str, telegram_id: int,
                     draft: dict, *, edit: bool = False) -> None:
    models = await _models_or_none(message, token, lang, telegram_id)
    if models is None:
        return
    chosen = next((m for m in models if m.get("openrouter_id") == draft.get("model")), None) \
        or _default_model(models)
    draft["model"] = chosen.get("openrouter_id")
    draft.setdefault("ar", "1:1")
    await _save_draft(telegram_id, draft)
    try:
        balance = (await api.balance(token, lang=lang, telegram_id=telegram_id)).get("balance_tokens", "—")
    except ApiError:
        balance = "—"
    # Промпт и имя модели — чужой текст: «<» в нём Telegram считает тегом и
    # отвергает СООБЩЕНИЕ ЦЕЛИКОМ (на Message-пути человек видел ложное «не
    # удалось получить ответ», на callback-пути — тишину).
    text = t(lang, "img_card", prompt=esc(draft.get("prompt", "")[:300]),
             model=esc(chosen.get("name", "")),
             price=_price(chosen) or "", ar=draft["ar"], balance=esc(balance))
    markup = _card_keyboard(lang, draft["ar"])
    if edit:
        try:
            await message.edit_text(text, parse_mode="HTML", reply_markup=markup)
            return
        except Exception:
            # Под фото/уже удалённым сообщением редактировать нечего — шлём новое.
            pass
    try:
        await message.answer(text, parse_mode="HTML", reply_markup=markup)
    except TelegramBadRequest:
        # Разметка всё равно не понравилась — карточка важнее оформления.
        # parse_mode=None обязателен: у бота глобальный HTML
        # (DefaultBotProperties), и без явного None aiogram подставит его снова,
        # а сырые «<» из plain() отобьются второй ошибкой — уже непойманной.
        logger.warning("картинки: карточка не прошла как HTML, шлю без разметки")
        await message.answer(plain(text), parse_mode=None, reply_markup=markup)


@router.message(Command("image"))
async def cmd_image(message: Message, command: CommandObject, token: str, lang: str,
                    state: FSMContext) -> None:
    await start_wizard(message, token, lang, state, (command.args or "").strip())


async def start_wizard(message: Message, token: str, lang: str, state: FSMContext,
                       prompt: str = "") -> None:
    telegram_id = message.chat.id
    if prompt:
        await state.clear()
        draft = await _draft(telegram_id)
        draft.update({"prompt": prompt, "attachment": None})
        await _show_card(message, token, lang, telegram_id, draft)
        return
    await state.set_state(ImageWizard.prompt)
    await message.answer(t(lang, "img_ask"))


async def start_edit(message: Message, state: FSMContext, lang: str, attachment: dict) -> None:
    """Из меню под фото: «Отредактировать» — ждём, что именно изменить."""
    await state.set_state(ImageWizard.edit)
    await state.update_data(attachment=attachment)
    await message.answer(t(lang, "img_edit_ask"))


@router.message(ImageWizard.prompt, F.text & ~F.text.startswith("/"))
async def got_prompt(message: Message, token: str, lang: str, state: FSMContext) -> None:
    from bot.keyboards.common import MENU_ACTIONS

    if message.text in MENU_ACTIONS:
        await state.clear()
        return
    await state.clear()
    telegram_id = message.chat.id
    draft = await _draft(telegram_id)
    draft.update({"prompt": message.text.strip(), "attachment": None})
    await _show_card(message, token, lang, telegram_id, draft)


@router.message(ImageWizard.prompt, F.photo)
async def got_photo_prompt(message: Message, token: str, lang: str, state: FSMContext) -> None:
    """Фото с подписью в мастере — это редактирование."""
    from bot.routers.media import _upload, download

    await state.clear()
    photo = message.photo[-1]
    content = await download(message, photo.file_id, photo.file_size or 0, lang)
    if content is None:
        return
    attachment = await _upload(message, token, lang, "photo.jpg", content, "image/jpeg")
    if attachment is None:
        return
    caption = (message.caption or "").strip()
    if caption:
        model = await _edit_model(message, token, lang, message.chat.id)
        if not model:
            return
        await _generate(message, token, lang, {"prompt": caption, "attachment": attachment,
                                              "model": model, "ar": ""})
        return
    await state.set_state(ImageWizard.edit)
    await state.update_data(attachment=attachment)
    await message.answer(t(lang, "img_edit_ask"))


@router.message(ImageWizard.edit, F.text & ~F.text.startswith("/"))
async def got_edit_prompt(message: Message, token: str, lang: str, state: FSMContext) -> None:
    data = await state.get_data()
    await state.clear()
    attachment = data.get("attachment")
    if not attachment:
        return
    model = await _edit_model(message, token, lang, message.chat.id)
    if not model:
        return
    await _generate(message, token, lang, {"prompt": message.text.strip(), "attachment": attachment,
                                          "model": model, "ar": ""})


INTENT_RE = re.compile(r"^\s*(?:пере)?(?:нарисуй|сгенерируй|создай|сделай|draw|paint|generate|create|make|сүрөт|тарт)",
                       re.IGNORECASE)
ONE_IMAGE = {
    "ru": "Нарисуй одну картинку, без текста: {prompt}",
    "en": "Draw one image, no text: {prompt}",
    "kg": "Бир сүрөт тарт, текстсиз: {prompt}",
}


def wizard_prompt(lang: str, prompt: str, *, editing: bool) -> str:
    """Голая тема («Самарканд») для модели — повод для рассказа с тремя
    картинками за тройную цену. В мастере просим ровно одну картинку."""
    prompt = (prompt or "").strip()
    if editing or INTENT_RE.match(prompt):
        return prompt
    return ONE_IMAGE.get(lang, ONE_IMAGE["ru"]).format(prompt=prompt)


async def _generate(message: Message, token: str, lang: str, draft: dict) -> None:
    telegram_id = message.chat.id
    extra = {}
    if draft.get("ar"):
        extra["aspect_ratio"] = draft["ar"]
    attachments = [draft["attachment"]] if draft.get("attachment") else None
    text = wizard_prompt(lang, draft.get("prompt", ""), editing=bool(attachments))
    done = await run_chat(message, token, lang, text,
                          attachments=attachments, model=draft.get("model") or DEFAULT_EDIT_MODEL,
                          extra=extra, placeholder=t(lang, "drawing"),
                          result_markup=result_keyboard(lang), remember_prompt=False)
    if not done:
        # Отказ (пейвол, сбой) — черновик оставляем: с ним человек повторит попытку.
        return
    # Мастер отработал: черновик жил час и после генерации подменял собой
    # последнюю картинку — кнопки под результатом уводили обратно в карточку,
    # иногда со старым промптом.
    await store.drop(telegram_id, "img_draft")
    atts = ((done.get("message") or {}).get("attachments") or [])
    image = next((a for a in atts if a.get("type") == "image"), None)
    if image:
        last = {**draft, "url": image.get("url"), "attachment": None}
        await store.set(telegram_id, "img_last", last, ttl=6 * 3600)
        # Готовую картинку можно тут же редактировать дальше.
        await store.set(telegram_id, "attachment", {"type": "image", "url": image.get("url"),
                                                   "name": image.get("name") or "image.png"}, ttl=1800)


# ------------------------------------------------------------ callbacks ---

@router.callback_query(F.data.startswith("i:ar:"))
async def pick_ratio(call: CallbackQuery, token: str, lang: str) -> None:
    """Пропорции на карточке мастера: только меняем карточку, кредитов не тратим."""
    ar = call.data.split(":", 2)[2]
    if ar not in ASPECT_RATIOS:
        await call.answer()
        return
    telegram_id = call.message.chat.id
    draft = await _draft(telegram_id)
    if not draft.get("prompt"):
        # Карточка из прошлой сессии (черновик истёк или уже отрисован): берём
        # промпт последней картинки, но рисовать человек подтверждает сам —
        # молча списывать за нажатие на старой карточке нельзя.
        last = await store.get(telegram_id, "img_last") or {}
        if not last.get("prompt"):
            await call.answer(t(lang, "img_no_last"), show_alert=True)
            return
        draft = {"prompt": last.get("prompt"), "model": last.get("model")}
    draft["ar"] = ar
    await _save_draft(telegram_id, draft)
    await call.answer(ar)
    await _show_card(call.message, token, lang, telegram_id, draft, edit=True)


@router.callback_query(F.data.startswith("i:rar:"))
async def redraw_ratio(call: CallbackQuery, token: str, lang: str) -> None:
    """Пропорции ПОД ГОТОВОЙ картинкой — всегда перерисовать последнюю.

    Отдельный префикс нужен, чтобы не зависеть от того, жив ли ещё черновик
    мастера: с общим «i:ar:» кнопка уводила в карточку вместо новой картинки.
    """
    ar = call.data.split(":", 2)[2]
    await call.answer()
    if ar not in ASPECT_RATIOS:
        return
    last = await store.get(call.message.chat.id, "img_last") or {}
    if not last.get("prompt"):
        await call.message.answer(t(lang, "img_no_last"))
        return
    await _generate(call.message, token, lang, {**last, "ar": ar, "attachment": None})


@router.callback_query(F.data == "i:models")
async def pick_model_menu(call: CallbackQuery, token: str, lang: str) -> None:
    telegram_id = call.message.chat.id
    await call.answer()
    models = await _models_or_none(call.message, token, lang, telegram_id)
    if models is None:
        return
    buttons = [InlineKeyboardButton(
        text=f"{'🔒 ' if m.get('locked') else ''}{m.get('name')} · {_price(m)}",
        callback_data=f"i:m:{index}") for index, m in enumerate(models[:12])]
    rows = rows_of(buttons, 1)
    rows.append([InlineKeyboardButton(text=t(lang, "btn_back"), callback_data="i:back")])
    await call.message.edit_text(t(lang, "img_pick_model"),
                                 reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))


@router.callback_query(F.data.startswith("i:m:"))
async def pick_model(call: CallbackQuery, token: str, lang: str) -> None:
    from bot.routers.chat import show_paywall

    telegram_id = call.message.chat.id
    try:
        models = await _image_models(token, lang, telegram_id)
    except ApiError:
        # Отвечаем ровно один раз: ниже call.answer() уже с именем модели.
        await call.answer()
        await call.message.answer(t(lang, "server_down"))
        return
    try:
        chosen = models[int(call.data.split(":")[2])]
    except (IndexError, ValueError):
        await call.answer()
        return
    if chosen.get("locked"):
        await call.answer()
        await show_paywall(call.message, lang, ApiError(403, code="premium_locked"))
        return
    draft = await _draft(telegram_id)
    draft["model"] = chosen.get("openrouter_id")
    await _save_draft(telegram_id, draft)
    await call.answer(chosen.get("name", ""))
    await _show_card(call.message, token, lang, telegram_id, draft, edit=True)


@router.callback_query(F.data == "i:back")
async def back_to_card(call: CallbackQuery, token: str, lang: str) -> None:
    telegram_id = call.message.chat.id
    await call.answer()
    await _show_card(call.message, token, lang, telegram_id, await _draft(telegram_id), edit=True)


@router.callback_query(F.data == "i:go")
async def go(call: CallbackQuery, token: str, lang: str) -> None:
    telegram_id = call.message.chat.id
    draft = await _draft(telegram_id)
    await call.answer()
    if not draft.get("prompt"):
        await call.message.answer(t(lang, "img_ask"))
        return
    try:
        await call.message.edit_reply_markup(reply_markup=None)
    except Exception:
        pass
    await _generate(call.message, token, lang, draft)


@router.callback_query(F.data == "i:x")
async def cancel(call: CallbackQuery, lang: str, state: FSMContext) -> None:
    await state.clear()
    await store.drop(call.message.chat.id, "img_draft")
    await call.answer(t(lang, "img_cancelled"))
    try:
        await call.message.delete()
    except Exception:
        pass


@router.callback_query(F.data == "i:again")
async def again(call: CallbackQuery, token: str, lang: str) -> None:
    telegram_id = call.message.chat.id
    last = await store.get(telegram_id, "img_last") or {}
    await call.answer()
    if not last.get("prompt"):
        await call.message.answer(t(lang, "img_no_last"))
        return
    await _generate(call.message, token, lang, {**last, "attachment": None})


@router.callback_query(F.data == "i:pickar")
async def pick_ar_again(call: CallbackQuery, lang: str) -> None:
    await call.answer()
    ratios = [InlineKeyboardButton(text=r, callback_data=f"i:rar:{r}") for r in ASPECT_RATIOS]
    await call.message.answer(t(lang, "img_pick_ar"),
                              reply_markup=InlineKeyboardMarkup(inline_keyboard=rows_of(ratios, 4)))


@router.callback_query(F.data == "i:edit")
async def edit_last(call: CallbackQuery, lang: str, state: FSMContext) -> None:
    telegram_id = call.message.chat.id
    last = await store.get(telegram_id, "img_last") or {}
    await call.answer()
    if not last.get("url"):
        await call.message.answer(t(lang, "img_no_last"))
        return
    await start_edit(call.message, state, lang,
                     {"type": "image", "url": last["url"], "name": "image.png"})


@router.callback_query(F.data == "i:dl")
async def download_original(call: CallbackQuery, lang: str) -> None:
    telegram_id = call.message.chat.id
    last = await store.get(telegram_id, "img_last") or {}
    await call.answer()
    if not last.get("url"):
        await call.message.answer(t(lang, "img_no_last"))
        return
    try:
        # Документом Telegram отдаёт файл без пережатия.
        await call.message.answer_document(site_url(last["url"]))
    except Exception:
        await call.message.answer(site_url(last["url"]))
