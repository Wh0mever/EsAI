"""Файлы и фото: человек присылает документ — бот его читает."""
from __future__ import annotations

import io
import logging

from aiogram import F, Router
from aiogram.enums import ChatAction
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from bot.routers.chat import run_chat
from bot.services.api import ApiError, api
from bot.services.state import store
from bot.texts import t

logger = logging.getLogger(__name__)
router = Router(name="media")

# Telegram не отдаёт ботам файлы больше 20 МБ, а наш API принимает до 15 МБ.
TELEGRAM_LIMIT = 20 * 1024 * 1024
API_LIMIT = 15 * 1024 * 1024

DOC_EXTENSIONS = (".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx", ".txt")
IMAGE_EXTENSIONS = (".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp", ".heic", ".heif")

# Что делают с документом чаще всего — теми же словами, что в каталоге на сайте.
DOC_ACTIONS = {
    "sum": ("📝 Пересказать", "Кратко перескажи этот документ."),
    "key": ("⭐ Выделить главное", "Выдели главные мысли из этого документа списком."),
    "err": ("🔍 Найти ошибки", "Найди ошибки и неточности в этом документе."),
    "law": ("⚖️ Проверить договор", "Проверь этот договор: risks, невыгодные пункты, чего не хватает."),
    "tr": ("🌍 Перевести", "Переведи этот документ на русский язык."),
}

PHOTO_ACTIONS = {
    "see": ("👁 Что на фото", "Опиши, что изображено на этом фото."),
    "edit": ("✏️ Отредактировать", ""),
    "text": ("📄 Достать текст", "Прочитай и выпиши весь текст с этого изображения."),
}


def _doc_keyboard() -> InlineKeyboardMarkup:
    buttons = [InlineKeyboardButton(text=label, callback_data=f"doc:{key}")
               for key, (label, _) in DOC_ACTIONS.items()]
    rows = [buttons[i:i + 2] for i in range(0, len(buttons), 2)]
    rows.append([InlineKeyboardButton(text="💬 Свой вопрос", callback_data="doc:ask")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _photo_keyboard() -> InlineKeyboardMarkup:
    buttons = [InlineKeyboardButton(text=label, callback_data=f"ph:{key}")
               for key, (label, _) in PHOTO_ACTIONS.items()]
    return InlineKeyboardMarkup(inline_keyboard=[buttons[:2], buttons[2:]])


async def _download(message: Message, file_id: str, size: int, lang: str) -> bytes | None:
    """Скачать файл, честно объяснив, если это невозможно."""
    if size and size > TELEGRAM_LIMIT:
        await message.answer(t(lang, "file_too_big"))
        return None
    if size and size > API_LIMIT:
        await message.answer(t(lang, "file_too_big_api"))
        return None
    buffer = io.BytesIO()
    file = await message.bot.get_file(file_id)
    await message.bot.download_file(file.file_path, destination=buffer)
    return buffer.getvalue()


async def _upload(message: Message, token: str, lang: str, name: str,
                  content: bytes, mime: str) -> dict | None:
    try:
        result = await api.upload(token, name, content, mime,
                                  lang=lang, telegram_id=message.from_user.id)
    except ApiError as exc:
        logger.warning("файл не загрузился: %s", exc)
        await message.answer(t(lang, "server_down"))
        return None
    attachments = (result or {}).get("attachments") or []
    return attachments[0] if attachments else None


@router.message(F.document)
async def on_document(message: Message, token: str, lang: str = "ru") -> None:
    document = message.document
    name = document.file_name or "file"
    lowered = name.lower()
    if not lowered.endswith(DOC_EXTENSIONS + IMAGE_EXTENSIONS):
        await message.answer(t(lang, "file_unsupported"))
        return

    await message.bot.send_chat_action(message.chat.id, ChatAction.UPLOAD_DOCUMENT)
    content = await _download(message, document.file_id, document.file_size or 0, lang)
    if content is None:
        return

    attachment = await _upload(message, token, lang, name, content,
                               document.mime_type or "application/octet-stream")
    if attachment is None:
        return

    if attachment.get("type") == "document" and not (attachment.get("text") or "").strip():
        await message.answer(t(lang, "file_no_text"))
        return

    await store.set(message.from_user.id, "attachment", attachment, ttl=1800)

    caption = (message.caption or "").strip()
    if caption:
        await run_chat(message, token, lang, caption, attachments=[attachment])
        return

    await message.answer(t(lang, "doc_ready", name=name), parse_mode="HTML",
                         reply_markup=_doc_keyboard())


@router.message(F.photo)
async def on_photo(message: Message, token: str, lang: str = "ru") -> None:
    photo = message.photo[-1]  # последний размер — самый большой
    await message.bot.send_chat_action(message.chat.id, ChatAction.UPLOAD_PHOTO)
    content = await _download(message, photo.file_id, photo.file_size or 0, lang)
    if content is None:
        return

    attachment = await _upload(message, token, lang, "photo.jpg", content, "image/jpeg")
    if attachment is None:
        return
    await store.set(message.from_user.id, "attachment", attachment, ttl=1800)

    caption = (message.caption or "").strip()
    if caption:
        await run_chat(message, token, lang, caption, attachments=[attachment])
        return

    await message.answer(t(lang, "photo_ready"), reply_markup=_photo_keyboard())


@router.callback_query(F.data.startswith("doc:"))
async def doc_action(call: CallbackQuery, token: str, lang: str = "ru") -> None:
    key = call.data.split(":", 1)[1]
    attachment = await store.get(call.from_user.id, "attachment")
    await call.answer()
    if not attachment:
        return
    if key == "ask":
        await call.message.answer("Напишите вопрос по документу.")
        return
    prompt = DOC_ACTIONS.get(key, ("", ""))[1]
    if prompt:
        await run_chat(call.message, token, lang, prompt, attachments=[attachment])


@router.callback_query(F.data.startswith("ph:"))
async def photo_action(call: CallbackQuery, token: str, lang: str = "ru") -> None:
    key = call.data.split(":", 1)[1]
    attachment = await store.get(call.from_user.id, "attachment")
    await call.answer()
    if not attachment:
        return
    if key == "edit":
        await call.message.answer("Что изменить на фото? Например: «убери фон».")
        return
    prompt = PHOTO_ACTIONS.get(key, ("", ""))[1]
    if prompt:
        await run_chat(call.message, token, lang, prompt, attachments=[attachment])


@router.message(F.voice | F.video_note | F.audio)
async def on_voice(message: Message, lang: str = "ru") -> None:
    await message.answer(t(lang, "voice_soon"))
