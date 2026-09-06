"""Файлы, фото и голосовые: человек присылает — бот разбирает."""
from __future__ import annotations

import io
import logging

from aiogram import F, Router
from aiogram.enums import ChatAction
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from bot.routers.chat import run_chat, show_paywall
from bot.services.api import ApiError, api
from bot.services.state import store
from bot.texts import register_texts, t

logger = logging.getLogger(__name__)
router = Router(name="media")

# Telegram не отдаёт ботам файлы больше 20 МБ, а наш API принимает до 15 МБ.
TELEGRAM_LIMIT = 20 * 1024 * 1024
API_LIMIT = 15 * 1024 * 1024
# Голосовые: предел сервера — две минуты и пять мегабайт.
VOICE_MAX_SECONDS = 120
VOICE_MAX_BYTES = 5 * 1024 * 1024

DOC_EXTENSIONS = (".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx", ".txt")
IMAGE_EXTENSIONS = (".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp", ".heic", ".heif")

# Что делают с документом чаще всего — теми же словами, что в каталоге на сайте.
DOC_ACTIONS = {
    "sum": ("📝 Пересказать", "Кратко перескажи этот документ."),
    "key": ("⭐ Выделить главное", "Выдели главные мысли из этого документа списком."),
    "err": ("🔍 Найти ошибки", "Найди ошибки и неточности в этом документе."),
    "law": ("⚖️ Проверить договор", "Проверь этот договор: риски, невыгодные пункты, чего не хватает."),
    "tr": ("🌍 Перевести", "Переведи этот документ на русский язык."),
}

PHOTO_ACTIONS = {
    "see": ("👁 Что на фото", "Опиши, что изображено на этом фото."),
    "edit": ("✏️ Отредактировать", ""),
    "text": ("📄 Достать текст", "Прочитай и выпиши весь текст с этого изображения."),
    "video": ("🎬 Видео из фото", ""),
}

register_texts({
    "ru": {
        "voice_listening": "🎤 Слушаю…",
        "voice_said": "🎤 <b>Вы сказали:</b> {text}\n<i>−{credits} кр за распознавание</i>",
        "voice_empty": "🎤 В записи не разобрать речи. Попробуйте ещё раз или напишите текстом.",
        "voice_too_long": "🎤 Голосовое длиннее {max} секунд — не разберу. Запишите короче или напишите текстом.",
        "voice_too_big": "🎤 Файл слишком большой для распознавания (до 5 МБ).",
        "voice_failed": "🎤 Не удалось распознать. Кредиты не списаны — напишите текстом.",
        "photo_edit_ask": "Что изменить на фото? Например: «убери фон» или «сделай в стиле аниме».",
        "doc_ask": "Напишите вопрос по документу.",
    },
    "en": {
        "voice_listening": "🎤 Listening…",
        "voice_said": "🎤 <b>You said:</b> {text}\n<i>−{credits} cr for transcription</i>",
        "voice_empty": "🎤 No speech recognised. Try again or type your message.",
        "voice_too_long": "🎤 Voice messages longer than {max} seconds are not supported. Please keep it shorter.",
        "voice_too_big": "🎤 The file is too big for transcription (up to 5 MB).",
        "voice_failed": "🎤 Could not transcribe. No credits were charged — please type instead.",
        "photo_edit_ask": "What should change in the photo? E.g. “remove the background”.",
        "doc_ask": "Type your question about the document.",
    },
    "kg": {
        "voice_listening": "🎤 Угуп жатам…",
        "voice_said": "🎤 <b>Сиз айттыңыз:</b> {text}\n<i>−{credits} кр таануу үчүн</i>",
        "voice_empty": "🎤 Жазууда сөз аныкталган жок. Кайра аракет кылыңыз же текст жазыңыз.",
        "voice_too_long": "🎤 Үн билдирүү {max} секунддан узун — таанылбайт. Кыскараак жазыңыз.",
        "voice_too_big": "🎤 Файл өтө чоң (5 МБ чейин).",
        "voice_failed": "🎤 Таануу мүмкүн болгон жок. Кредиттер алынган жок — текст жазыңыз.",
        "photo_edit_ask": "Сүрөттө эмнени өзгөртүү керек? Мисалы: «фонду алып сал».",
        "doc_ask": "Документ боюнча сурооңузду жазыңыз.",
    },
})


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


async def download(message: Message, file_id: str, size: int, lang: str,
                   *, limit: int = API_LIMIT, too_big_key: str = "file_too_big_api") -> bytes | None:
    """Скачать файл, честно объяснив, если это невозможно."""
    if size and size > TELEGRAM_LIMIT:
        await message.answer(t(lang, "file_too_big"))
        return None
    if size and size > limit:
        await message.answer(t(lang, too_big_key))
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
    content = await download(message, document.file_id, document.file_size or 0, lang)
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

    if attachment.get("type") == "image":
        await message.answer(t(lang, "photo_ready"), reply_markup=_photo_keyboard())
        return
    await message.answer(t(lang, "doc_ready", name=name), parse_mode="HTML",
                         reply_markup=_doc_keyboard())


@router.message(F.photo)
async def on_photo(message: Message, token: str, lang: str = "ru", state=None) -> None:
    # Мастера (герой студии, кадр для видео) сами ждут фото — им не мешаем.
    if state is not None and await state.get_state():
        return
    photo = message.photo[-1]  # последний размер — самый большой
    await message.bot.send_chat_action(message.chat.id, ChatAction.UPLOAD_PHOTO)
    content = await download(message, photo.file_id, photo.file_size or 0, lang)
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
        await call.message.answer(t(lang, "doc_ask"))
        return
    prompt = DOC_ACTIONS.get(key, ("", ""))[1]
    if prompt:
        await run_chat(call.message, token, lang, prompt, attachments=[attachment])


@router.callback_query(F.data.startswith("ph:"))
async def photo_action(call: CallbackQuery, token: str, lang: str = "ru", state=None) -> None:
    key = call.data.split(":", 1)[1]
    attachment = await store.get(call.from_user.id, "attachment")
    await call.answer()
    if not attachment:
        return
    if key == "edit":
        from bot.routers.image import start_edit

        await start_edit(call.message, state, lang, attachment)
        return
    if key == "video":
        from bot.routers.video import start_from_photo

        await start_from_photo(call.message, token, lang, state, attachment)
        return
    prompt = PHOTO_ACTIONS.get(key, ("", ""))[1]
    if prompt:
        await run_chat(call.message, token, lang, prompt, attachments=[attachment])


@router.message(F.voice | F.video_note | F.audio)
async def on_voice(message: Message, token: str, lang: str = "ru") -> None:
    """Голосовое → текст на сервере → обычный вопрос в чат."""
    media = message.voice or message.audio or message.video_note
    duration = int(getattr(media, "duration", 0) or 0)
    if duration > VOICE_MAX_SECONDS:
        await message.answer(t(lang, "voice_too_long", max=VOICE_MAX_SECONDS))
        return
    await message.bot.send_chat_action(message.chat.id, ChatAction.TYPING)
    content = await download(message, media.file_id, getattr(media, "file_size", 0) or 0, lang,
                             limit=VOICE_MAX_BYTES, too_big_key="voice_too_big")
    if content is None:
        return
    mime = getattr(media, "mime_type", None) or "audio/ogg"
    status = await message.answer(t(lang, "voice_listening"))
    try:
        result = await api.transcribe(token, content, mime, lang=lang,
                                      telegram_id=message.from_user.id)
    except ApiError as exc:
        try:
            await status.delete()
        except Exception:
            pass
        if exc.is_paywall:
            await show_paywall(message, lang, exc)
        elif exc.code == "too_long":
            await message.answer(t(lang, "voice_too_long", max=VOICE_MAX_SECONDS))
        else:
            await message.answer(t(lang, "voice_failed"))
        return
    text = ((result or {}).get("text") or "").strip()
    try:
        await status.delete()
    except Exception:
        pass
    if not text:
        await message.answer(t(lang, "voice_empty"))
        return
    await message.answer(t(lang, "voice_said", text=text[:1500],
                           credits=(result or {}).get("tokens_charged", 0)),
                         parse_mode="HTML")
    await run_chat(message, token, lang, text)
