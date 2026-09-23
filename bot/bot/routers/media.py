"""Файлы, фото и голосовые: человек присылает — бот разбирает."""
from __future__ import annotations

import io
import logging
import time

from aiogram import F, Router
from aiogram.enums import ChatAction
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from bot.routers.chat import run_chat, show_paywall
from bot.services.api import ApiError, api
from bot.services.state import store
from bot.services.tg_format import esc
from bot.texts import register_texts, t

logger = logging.getLogger(__name__)
router = Router(name="media")

# Telegram не отдаёт ботам файлы больше 20 МБ, а наш API принимает до 15 МБ.
TELEGRAM_LIMIT = 20 * 1024 * 1024
API_LIMIT = 15 * 1024 * 1024
# Голосовые: предел сервера — две минуты и пять мегабайт.
VOICE_MAX_SECONDS = 120
VOICE_MAX_BYTES = 5 * 1024 * 1024
# Присланный файл бот помнит полчаса: столько же годен снимок в состоянии.
ATTACHMENT_TTL = 1800

DOC_EXTENSIONS = (".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx", ".txt")
IMAGE_EXTENSIONS = (".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp", ".heic", ".heif")

# Что делают с документом и фото чаще всего — теми же словами, что в каталоге
# на сайте. Здесь только порядок кнопок: подписи и промпты живут в текстах,
# потому что зависят от языка (см. doc_prompt/photo_prompt).
DOC_ACTION_KEYS = ("sum", "key", "err", "law", "tr")
PHOTO_ACTION_KEYS = ("see", "edit", "text", "video")
# Эти две кнопки промпта не имеют: они уводят в мастера картинки и видео.
PHOTO_WIZARD_KEYS = frozenset({"edit", "video"})

register_texts({
    "ru": {
        "media_doc_sum": "📝 Пересказать",
        "media_doc_sum_prompt": "Кратко перескажи этот документ.",
        "media_doc_key": "⭐ Выделить главное",
        "media_doc_key_prompt": "Выдели главные мысли из этого документа списком.",
        "media_doc_err": "🔍 Найти ошибки",
        "media_doc_err_prompt": "Найди ошибки и неточности в этом документе.",
        "media_doc_law": "⚖️ Проверить договор",
        "media_doc_law_prompt": "Проверь этот договор: риски, невыгодные пункты, чего не хватает.",
        "media_doc_tr": "🌍 Перевести",
        "media_doc_tr_prompt": "Переведи этот документ на русский язык.",
        "media_doc_ask_btn": "💬 Свой вопрос",
        "media_photo_see": "👁 Что на фото",
        "media_photo_see_prompt": "Опиши, что изображено на этом фото.",
        "media_photo_edit": "✏️ Отредактировать",
        "media_photo_text": "📄 Достать текст",
        "media_photo_text_prompt": "Прочитай и выпиши весь текст с этого изображения.",
        "media_photo_video": "🎬 Видео из фото",
        "media_attachment_gone": (
            "Этот файл бот уже не помнит — вложение живёт полчаса. "
            "Пришлите его ещё раз, и кнопки снова заработают."
        ),
        "media_step_dropped": (
            "Предыдущий шаг отменён: вместо текста пришло фото. Разбираю фото — "
            "а если ждали письмо в поддержку, перевод или код привязки, "
            "начните шаг заново."
        ),
        "media_step_dropped_file": (
            "Предыдущий шаг отменён: вместо ответа пришёл файл. Разбираю файл — "
            "а если ждали письмо в поддержку, перевод или код привязки, "
            "начните шаг заново."
        ),
        "media_step_dropped_voice": (
            "Предыдущий шаг отменён: пришло голосовое. Отвечу на него как на обычный "
            "вопрос — а если ждали письмо в поддержку, перевод или код привязки, "
            "начните шаг заново."
        ),
        "media_send_as_photo": (
            "Этот шаг ждёт фото. Пришлите картинку как фото, а не файлом — "
            "или /cancel, чтобы выйти."
        ),
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
        "media_doc_sum": "📝 Summarise",
        "media_doc_sum_prompt": "Summarise this document briefly.",
        "media_doc_key": "⭐ Key points",
        "media_doc_key_prompt": "List the key points of this document.",
        "media_doc_err": "🔍 Find mistakes",
        "media_doc_err_prompt": "Find mistakes and inaccuracies in this document.",
        "media_doc_law": "⚖️ Check the contract",
        "media_doc_law_prompt": ("Review this contract: risks, unfavourable clauses, "
                                 "what is missing."),
        "media_doc_tr": "🌍 Translate",
        "media_doc_tr_prompt": "Translate this document into English.",
        "media_doc_ask_btn": "💬 My own question",
        "media_photo_see": "👁 What is on the photo",
        "media_photo_see_prompt": "Describe what is shown in this photo.",
        "media_photo_edit": "✏️ Edit",
        "media_photo_text": "📄 Extract the text",
        "media_photo_text_prompt": "Read and write out all the text from this image.",
        "media_photo_video": "🎬 Video from the photo",
        "media_attachment_gone": (
            "I no longer keep this file — an attachment lives for 30 minutes. "
            "Send it again and the buttons will work."
        ),
        "media_step_dropped": (
            "The previous step is cancelled: a photo came instead of text. "
            "I am handling the photo — if you were writing to support, sending "
            "credits or linking an account, start that step again."
        ),
        "media_step_dropped_file": (
            "The previous step is cancelled: a file came instead of an answer. "
            "I am handling the file — if you were writing to support, sending "
            "credits or linking an account, start that step again."
        ),
        "media_step_dropped_voice": (
            "The previous step is cancelled: a voice message came. I will answer it "
            "as a regular question — if you were writing to support, sending "
            "credits or linking an account, start that step again."
        ),
        "media_send_as_photo": (
            "This step needs a photo. Send the picture as a photo, not as a file — "
            "or /cancel to leave."
        ),
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
        "media_doc_sum": "📝 Кыскача айт",
        "media_doc_sum_prompt": "Бул документти кыскача айтып бер.",
        "media_doc_key": "⭐ Негизгисин бөл",
        "media_doc_key_prompt": "Бул документтин негизги ойлорун тизме менен жаз.",
        "media_doc_err": "🔍 Каталарды тап",
        "media_doc_err_prompt": "Бул документтен каталарды жана так эместиктерди тап.",
        "media_doc_law": "⚖️ Келишимди текшер",
        "media_doc_law_prompt": ("Бул келишимди текшер: тобокелдиктер, пайдасыз пункттар, "
                                 "эмне жетишпейт."),
        "media_doc_tr": "🌍 Которуу",
        "media_doc_tr_prompt": "Бул документти кыргыз тилине которуп бер.",
        "media_doc_ask_btn": "💬 Өз суроом",
        "media_photo_see": "👁 Сүрөттө эмне бар",
        "media_photo_see_prompt": "Бул сүрөттө эмне тартылганын сүрөттөп бер.",
        "media_photo_edit": "✏️ Өзгөртүү",
        "media_photo_text": "📄 Текстти чыгар",
        "media_photo_text_prompt": "Бул сүрөттөгү бардык текстти окуп жазып бер.",
        "media_photo_video": "🎬 Сүрөттөн видео",
        "media_attachment_gone": (
            "Бул файлды бот эстебей калды — тиркеме жарым саат сакталат. "
            "Кайра жөнөтүңүз, ошондо баскычтар иштейт."
        ),
        "media_step_dropped": (
            "Мурунку кадам жокко чыгарылды: текст ордуна сүрөт келди. Сүрөттү "
            "карап жатам — эгер колдоого кат, которуу же байланыштыруу коду "
            "керек болсо, кадамды кайра баштаңыз."
        ),
        "media_step_dropped_file": (
            "Мурунку кадам жокко чыгарылды: жооптун ордуна файл келди. Файлды "
            "карап жатам — эгер колдоого кат, которуу же байланыштыруу коду "
            "керек болсо, кадамды кайра баштаңыз."
        ),
        "media_step_dropped_voice": (
            "Мурунку кадам жокко чыгарылды: үн билдирүү келди. Ага кадимки суроо "
            "катары жооп берем — эгер колдоого кат, которуу же байланыштыруу коду "
            "керек болсо, кадамды кайра баштаңыз."
        ),
        "media_send_as_photo": (
            "Бул кадамга сүрөт керек. Сүрөттү файл катары эмес, сүрөт катары "
            "жөнөтүңүз — же чыгуу үчүн /cancel."
        ),
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


class DocAsk(StatesGroup):
    """«Свой вопрос» по документу.

    Без состояния следующее сообщение подхватывал общий обработчик чата — уже
    без вложения, и модель отвечала, не видя файла. Роутер media подключён до
    chat, поэтому хендлер с фильтром состояния забирает текст первым.
    """

    question = State()


def doc_prompt(lang: str, key: str) -> str:
    """Промпт кнопки на языке человека.

    Промпт уходит в модель, поэтому язык здесь не косметика: «Переведи этот
    документ на русский язык» англоязычному человеку переводил документ не туда,
    и он платил за чужой результат.
    """
    return t(lang, f"media_doc_{key}_prompt") if key in DOC_ACTION_KEYS else ""


def photo_prompt(lang: str, key: str) -> str:
    if key not in PHOTO_ACTION_KEYS or key in PHOTO_WIZARD_KEYS:
        return ""
    return t(lang, f"media_photo_{key}_prompt")


# Русский снимок каталога — для проверок и как быстрый справочник по кнопкам.
# Человеку подписи и промпты выдают функции выше, по его языку.
DOC_ACTIONS = {key: (t("ru", f"media_doc_{key}"), doc_prompt("ru", key))
               for key in DOC_ACTION_KEYS}
PHOTO_ACTIONS = {key: (t("ru", f"media_photo_{key}"), photo_prompt("ru", key))
                 for key in PHOTO_ACTION_KEYS}


def _doc_keyboard(lang: str) -> InlineKeyboardMarkup:
    buttons = [InlineKeyboardButton(text=t(lang, f"media_doc_{key}"), callback_data=f"doc:{key}")
               for key in DOC_ACTION_KEYS]
    rows = [buttons[i:i + 2] for i in range(0, len(buttons), 2)]
    rows.append([InlineKeyboardButton(text=t(lang, "media_doc_ask_btn"), callback_data="doc:ask")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _photo_keyboard(lang: str) -> InlineKeyboardMarkup:
    buttons = [InlineKeyboardButton(text=t(lang, f"media_photo_{key}"), callback_data=f"ph:{key}")
               for key in PHOTO_ACTION_KEYS]
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


async def _leave_wizard(message: Message, state: FSMContext | None, lang: str,
                        notice_key: str) -> str | None:
    """Снять ожидание мастера: пришло не то, чего он ждал. Вернуть снятое состояние.

    Раньше так делало только фото. Голосовое и файл проходили мимо, а мастер
    продолжал ждать: нажал «Отредактировать» под фото, спросил голосом, потом
    написал фразу — и она уходила платной правкой старого снимка. Ожидание
    вопроса по документу — наше собственное, о нём строка только шумит.
    """
    if state is None:
        return None
    current = await state.get_state()
    if not current:
        return None
    await state.clear()
    if current != DocAsk.question.state:
        await message.answer(t(lang, notice_key))
    return current


def _doc_snapshot(data: dict) -> dict | None:
    """Документ из состояния «Свой вопрос», если снимок ещё свежий."""
    saved_at = data.get("attachment_at")
    if isinstance(saved_at, (int, float)) and time.time() - saved_at <= ATTACHMENT_TTL:
        return data.get("attachment")
    return None


@router.message(F.document)
async def on_document(message: Message, token: str, lang: str = "ru",
                      state: FSMContext | None = None) -> None:
    document = message.document
    name = document.file_name or "file"
    lowered = name.lower()
    if not lowered.endswith(DOC_EXTENSIONS + IMAGE_EXTENSIONS):
        # Неподдерживаемый файл ничего не меняет: мастер ждёт дальше.
        await message.answer(t(lang, "file_unsupported"))
        return

    current = await state.get_state() if state is not None else None
    if current and current in _photo_wizard_states() and lowered.endswith(IMAGE_EXTENSIONS):
        # Мастер ждёт фото, а картинку прислали файлом: принять её он не
        # умеет, но и бросать шаг незачем — человек прислал ровно то, что просили.
        await message.answer(t(lang, "media_send_as_photo"))
        return
    await _leave_wizard(message, state, lang, "media_step_dropped_file")

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

    await store.set(message.from_user.id, "attachment", attachment, ttl=ATTACHMENT_TTL)

    caption = (message.caption or "").strip()
    if caption:
        await run_chat(message, token, lang, caption, attachments=[attachment])
        return

    if attachment.get("type") == "image":
        await message.answer(t(lang, "photo_ready"), reply_markup=_photo_keyboard(lang))
        return
    # Имя файла придумал не бот: «<» в нём Telegram считает открытым тегом
    # и отвергает сообщение целиком.
    await message.answer(t(lang, "doc_ready", name=esc(name)), parse_mode="HTML",
                         reply_markup=_doc_keyboard(lang))


def _photo_wizard_states() -> frozenset[str]:
    """Состояния, в которых фото ждут ДРУГИЕ роутеры.

    Импорт ленивый: image и studio сами тянут media — на верхнем уровне вышел
    бы круг импортов.
    """
    from bot.routers.image import ImageWizard
    from bot.routers.studio import StudioWizard
    from bot.routers.video import VideoWizard

    return frozenset({ImageWizard.prompt.state,
                      StudioWizard.hero_photo.state,
                      VideoWizard.prompt.state})


@router.message(F.photo)
async def on_photo(message: Message, token: str, lang: str = "ru", state=None) -> None:
    # Мастера, которые сами ждут фото (герой студии, кадр для видео, промпт
    # картинки), забирают сообщение раньше нас — им не мешаем. Все остальные
    # мастера ждут ТЕКСТ, и раньше фото в них просто исчезало без единого
    # слова в ответ: бот выглядел сломанным. Такое ожидание снимаем — раз
    # человек прислал фото, он передумал — и разбираем снимок как обычно.
    if state is not None:
        current = await state.get_state()
        if current:
            if current in _photo_wizard_states():
                return
            await state.clear()
            if current != DocAsk.question.state:
                # Бросили чужой мастер — об этом надо сказать. В поддержке,
                # переводе кредитов и привязке почты человек ждёт, что его
                # заявка идёт дальше; молча сняв состояние, мы бы отправили
                # его следующую фразу платным вопросом в чат. Ожидание вопроса
                # по документу — наше собственное, и меню под фото само по себе
                # продолжение того же разговора: там строка только шумит.
                await message.answer(t(lang, "media_step_dropped"))
    photo = message.photo[-1]  # последний размер — самый большой
    await message.bot.send_chat_action(message.chat.id, ChatAction.UPLOAD_PHOTO)
    content = await download(message, photo.file_id, photo.file_size or 0, lang)
    if content is None:
        return

    attachment = await _upload(message, token, lang, "photo.jpg", content, "image/jpeg")
    if attachment is None:
        return
    await store.set(message.from_user.id, "attachment", attachment, ttl=ATTACHMENT_TTL)

    caption = (message.caption or "").strip()
    if caption:
        await run_chat(message, token, lang, caption, attachments=[attachment])
        return

    await message.answer(t(lang, "photo_ready"), reply_markup=_photo_keyboard(lang))


@router.callback_query(F.data.startswith("doc:"))
async def doc_action(call: CallbackQuery, token: str, lang: str = "ru",
                     state: FSMContext | None = None) -> None:
    key = call.data.split(":", 1)[1]
    attachment = await store.get(call.from_user.id, "attachment")
    await call.answer()
    if not attachment:
        # Вложение бот помнит полчаса. После этого кнопки под старым сообщением
        # молча ничего не делали: человек жал и жал, не понимая, что сломалось.
        await call.message.answer(t(lang, "media_attachment_gone"))
        return
    if key == "ask":
        # Документ держим при себе до самого вопроса — иначе он потеряется.
        if state is not None:
            await state.set_state(DocAsk.question)
            await state.update_data(attachment=attachment, attachment_at=time.time())
        await call.message.answer(t(lang, "doc_ask"))
        return
    # Нажали готовую кнопку вместо обещанного вопроса — ждать его незачем,
    # иначе следующая фраза уйдёт в чат с молча подшитым документом.
    if state is not None and await state.get_state() == DocAsk.question.state:
        await state.clear()
    prompt = doc_prompt(lang, key)
    if prompt:
        await run_chat(call.message, token, lang, prompt, attachments=[attachment])


@router.message(DocAsk.question, F.text & ~F.text.startswith("/"))
async def doc_question(message: Message, token: str, lang: str = "ru",
                       state: FSMContext | None = None) -> None:
    """Вопрос по документу: уходит в чат вместе с самим документом."""
    data = await state.get_data() if state is not None else {}
    if state is not None:
        await state.clear()
    text = (message.text or "").strip()
    if not text:
        return
    # Свежая загрузка важнее снимка из состояния: человек мог прислать другой
    # файл, не нажимая кнопок. Снимок — запасной, когда память бота уже стёрла
    # вложение по TTL. Но и он не вечен: состояние лежит в Redis без срока, и
    # без этой проверки фраза, написанная через сутки после нажатия кнопки,
    # утащила бы с собой вчерашний договор — кредиты за его текст и ответ не о том.
    attachment = await store.get(message.from_user.id, "attachment")
    if attachment is None:
        attachment = _doc_snapshot(data)
    await run_chat(message, token, lang, text,
                   attachments=[attachment] if attachment else None)


@router.callback_query(F.data.startswith("ph:"))
async def photo_action(call: CallbackQuery, token: str, lang: str = "ru", state=None) -> None:
    key = call.data.split(":", 1)[1]
    attachment = await store.get(call.from_user.id, "attachment")
    await call.answer()
    if not attachment:
        # Вложение бот помнит полчаса. После этого кнопки под старым сообщением
        # молча ничего не делали: человек жал и жал, не понимая, что сломалось.
        await call.message.answer(t(lang, "media_attachment_gone"))
        return
    if key == "edit":
        from bot.routers.image import start_edit

        await start_edit(call.message, state, lang, attachment)
        return
    if key == "video":
        from bot.routers.video import start_from_photo

        await start_from_photo(call.message, token, lang, state, attachment)
        return
    prompt = photo_prompt(lang, key)
    if prompt:
        await run_chat(call.message, token, lang, prompt, attachments=[attachment])


@router.message(F.voice | F.video_note | F.audio)
async def on_voice(message: Message, token: str, lang: str = "ru",
                   state: FSMContext | None = None) -> None:
    """Голосовое → текст на сервере → обычный вопрос в чат."""
    media = message.voice or message.audio or message.video_note
    duration = int(getattr(media, "duration", 0) or 0)
    if duration > VOICE_MAX_SECONDS:
        await message.answer(t(lang, "voice_too_long", max=VOICE_MAX_SECONDS))
        return
    # Распознавание стоит кредитов, поэтому занятость проверяем ДО обращения к
    # API: раньше второе голосовое успевало оплатиться, а вопрос не задавался —
    # run_chat упирался в тот же замок и молча выходил. Замок берём тем же
    # публичным take_busy, держим на время распознавания и отпускаем прямо
    # перед run_chat: он возьмёт его сам.
    user_id = message.from_user.id
    if not await store.take_busy(user_id):
        if not await store.warned_recently(user_id):
            await message.answer(t(lang, "busy"))
        return

    text = ""
    doc_attachment = None
    try:
        await message.bot.send_chat_action(message.chat.id, ChatAction.TYPING)
        content = await download(message, media.file_id, getattr(media, "file_size", 0) or 0, lang,
                                 limit=VOICE_MAX_BYTES, too_big_key="voice_too_big")
        if content is None:
            return
        # Мастер снимаем ДО платного распознавания. Исключение — «Свой вопрос»
        # по документу: голосом задали тот самый вопрос, документ едет с ним.
        if state is not None and await state.get_state() == DocAsk.question.state:
            data = await state.get_data()
            await state.clear()
            doc_attachment = (await store.get(user_id, "attachment")) or _doc_snapshot(data)
        else:
            await _leave_wizard(message, state, lang, "media_step_dropped_voice")
        mime = getattr(media, "mime_type", None) or "audio/ogg"
        status = await message.answer(t(lang, "voice_listening"))
        try:
            result = await api.transcribe(token, content, mime, lang=lang,
                                          telegram_id=user_id)
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
        # Расшифровку писали не мы: «<» в ней Telegram считает тегом. И даже
        # если показать её всё-таки не вышло, распознавание уже оплачено —
        # вопрос обязан уйти в чат, иначе деньги списаны впустую.
        try:
            await message.answer(t(lang, "voice_said", text=esc(text[:1500]),
                                   credits=(result or {}).get("tokens_charged", 0)),
                                 parse_mode="HTML")
        except Exception:
            logger.warning("расшифровку показать не удалось, вопрос уходит как есть",
                           exc_info=True)
    finally:
        await store.free_busy(user_id)

    if text:
        await run_chat(message, token, lang, text,
                       attachments=[doc_attachment] if doc_attachment else None)
