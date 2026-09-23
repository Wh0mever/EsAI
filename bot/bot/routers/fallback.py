"""Последний рубеж: сообщения, которые не разобрал ни один экран.

Стикер, гифка, обычное видео, геолокация, контакт или команда с опечаткой
раньше проходили мимо всех роутеров, и бот молчал — человек не понимал,
сломался он или просто не услышал. Роутер подключается ПОСЛЕДНИМ: всё, что
умеют другие экраны, до него не доходит.
"""
from __future__ import annotations

import logging

from aiogram import F, Router
from aiogram.enums import ChatType
from aiogram.types import Message

from bot.keyboards.common import main_menu
from bot.middlewares.auth import COMMAND_RE
from bot.services.state import store
from bot.services.tg_format import esc
from bot.texts import register_texts, t

logger = logging.getLogger(__name__)
router = Router(name="fallback")
# Только личка: в группе бот не должен отзываться на каждый чужой стикер.
router.message.filter(F.chat.type == ChatType.PRIVATE)

# Альбом из пяти видео — это пять апдейтов подряд; отвечаем один раз.
REPLY_EVERY = 10

# Что показываем, когда содержимое непонятное. Служебные апдейты (закреп,
# участники группы, данные Mini App) сюда не относятся — на них не отвечаем.
UNHANDLED = (F.sticker | F.animation | F.video | F.video_note | F.location | F.venue
             | F.contact | F.dice | F.poll | F.game | F.story)

register_texts({
    "ru": {
        "fallback_unknown": (
            "Такое сообщение я пока не разбираю 🙂\n"
            "Пишите вопрос текстом, присылайте фото, документы (PDF, Word, Excel) "
            "или голосовые — или выберите действие в меню ниже. Все команды: /help"
        ),
        "fallback_command": (
            "Не знаю команды <code>{cmd}</code>. Все команды — в /help, главное — "
            "в меню ниже.\nЕсли это вопрос для нейросети, напишите его без «/» в начале."
        ),
    },
    "en": {
        "fallback_unknown": (
            "I can't handle this kind of message yet 🙂\n"
            "Type your question, send a photo, a document (PDF, Word, Excel) or a voice "
            "message — or pick an action in the menu below. All commands: /help"
        ),
        "fallback_command": (
            "I don't know the command <code>{cmd}</code>. All commands are in /help, "
            "the main ones are in the menu below.\n"
            "If this is a question for the AI, send it without the «/» at the start."
        ),
    },
    "kg": {
        "fallback_unknown": (
            "Мындай билдирүүнү азырынча түшүнбөйм 🙂\n"
            "Суроону текст менен жазыңыз, сүрөт, документ (PDF, Word, Excel) же үн "
            "билдирүү жөнөтүңүз — же төмөнкү менюдан аракет тандаңыз. "
            "Бардык командалар: /help"
        ),
        "fallback_command": (
            "<code>{cmd}</code> командасын билбейм. Бардык командалар — /help ичинде, "
            "негиздери — төмөнкү менюда.\n"
            "Эгер бул нейросетке суроо болсо, аны башына «/» койбой жазыңыз."
        ),
    },
})


def _first_word(text: str) -> str:
    match = COMMAND_RE.match((text or "").lstrip())
    word = f"/{match.group(1)}" if match else (text or "").split(maxsplit=1)[0]
    return word[:40]


@router.message(F.text.startswith("/"))
async def unknown_command(message: Message, lang: str = "ru") -> None:
    """Команда, которую не знает ни один экран: опечатка или «/путь/к/файлу»."""
    await message.answer(t(lang, "fallback_command", cmd=esc(_first_word(message.text))),
                         parse_mode="HTML", reply_markup=main_menu(lang))


@router.message(UNHANDLED)
async def unknown_content(message: Message, lang: str = "ru") -> None:
    """Стикер, гифка, видео, геолокация, контакт и прочее, что бот не разбирает."""
    try:
        first = await store.once(f"fallback:{message.from_user.id}", ttl=REPLY_EVERY)
    except Exception:
        # Redis задумался — лучше ответить лишний раз, чем промолчать.
        logger.warning("fallback: Redis недоступен", exc_info=True)
        first = True
    if not first:
        return
    await message.answer(t(lang, "fallback_unknown"), reply_markup=main_menu(lang))
