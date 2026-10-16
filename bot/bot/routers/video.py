"""Мастер видео: модель → промпт → параметры → очередь → ролик сообщением.

Ролик генерируется на сервере в очереди, а не в открытом соединении: бот
может перезапуститься посреди генерации — результат всё равно придёт
сообщением от ядра. Здесь мы только показываем прогресс и подстраховываем
доставку, если ядро по какой-то причине не отписалось.
"""
from __future__ import annotations

import asyncio
import logging
import time
import weakref

from aiogram import Bot, F, Router
from aiogram.enums import ChatAction
from aiogram.filters import Command, CommandObject
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from bot.config import settings
from bot.keyboards.common import paywall, rows_of
from bot.routers.chat import _session_gone, show_paywall, site_url
from bot.routers.models import _fetch, price_from
from bot.services.api import ApiError, api
from bot.services.state import store
from bot.services.tg_format import esc
from bot.texts import register_texts, t

logger = logging.getLogger(__name__)
router = Router(name="video")

POLL_INTERVAL = 5
POLL_MAX_SECONDS = 15 * 60
# Параметры и цены модели живут 10 минут, как в чате на сайте: курс, режим цен и
# себестоимость меняются сами, а запуск всё равно сверяет цену заново.
PARAMS_TTL = 600
# Ядро само шлёт готовый ролик и отмечает это в задаче, но статус done ставит
# раньше отметки, а при отказе Telegram отметку снимает обратно. Поэтому после
# «done» смотрим на отметку не один раз: ждём её NOTIFY_ATTEMPTS раз по
# NOTIFY_GRACE секунд (≈3 минуты), а увидев — держим NOTIFY_CONFIRM наблюдений
# подряд (≈минуту, дольше таймаута ядра к Telegram 10+30 с), чтобы не уйти за
# секунду до того, как ядро снимет отметку и вернёт доставку нам.
NOTIFY_GRACE = 20
NOTIFY_ATTEMPTS = 9
NOTIFY_CONFIRM = 4

# Telegram режет текст длиннее 4096 символов на несколько сообщений, и части
# приходят отдельными апдейтами почти одновременно. Раньше первая часть
# становилась промптом и закрывала шаг, а остальные уходили в текстовый чат
# (платный ответ модели) — ролик снимался по обрывку сценария. Теперь части
# копятся в данных FSM (Redis) и склеиваются, когда PROMPT_MERGE_WINDOW секунд
# не приходит новых.
PROMPT_MERGE_WINDOW = 1.5
# Буфер, к которому давно не приходило частей, осиротел: бот перезапустился
# посреди окна. К новому промпту его не приклеиваем — вышел бы дубль текста.
# Запас над окном — на ожидание замка и Redis у склейки, которая вот-вот сработает.
PROMPT_BUFFER_STALE = 10
PROMPT_BUFFER_KEY = "vid_prompt_parts"
# Длинную подпись к фото клиент Telegram обрезает молча: 1024 символа, у
# Premium — 2048. Подпись ровно такой длины почти наверняка обрывок.
CAPTION_LIMITS = (1024, 2048)

register_texts({
    "ru": {
        "vid_pick_model": "🎬 <b>Видео</b>\nВыберите модель:",
        "vid_ask_prompt": ("🎬 Модель: <b>{model}</b>{price}\n"
                           "Опишите, что должно происходить в ролике. Можно прислать фото с подписью — "
                           "оно станет первым кадром."),
        "vid_card": ("🎬 <b>{prompt}</b>\n\nМодель: <b>{model}</b>\n"
                     "Длительность: <b>{duration} с</b> · Пропорции: <b>{ar}</b>{res}\n"
                     "{first}Стоимость: <b>{cost} кр</b> · баланс {balance}"),
        "vid_card_no_price": ("🎬 <b>{prompt}</b>\n\nМодель: <b>{model}</b>\n"
                              "Длительность: <b>{duration} с</b> · Пропорции: <b>{ar}</b>{res}\n"
                              "{first}Стоимость: <b>недоступна</b> · баланс {balance}\n"
                              "Цена модели сейчас недоступна, попробуйте позже."),
        "vid_price_from": "от {credits} кр",
        "vid_refresh_price": "🔄 Обновить цену",
        "vid_no_price": "Цена модели сейчас недоступна, попробуйте позже.",
        "vid_price_changed": "Цена обновилась — проверьте и нажмите «Сгенерировать» ещё раз.",
        "vid_first_frame": "Первый кадр: ваше фото\n",
        "vid_extend": "Продолжение вашего ролика\n",
        "vid_go": "🎬 Сгенерировать ({cost} кр)",
        "vid_not_enough": "➕ Пополнить (не хватает {missing} кр)",
        "vid_queued": ("⏳ <b>Видео в очереди</b>\nОбычно занимает 1–8 минут. Можно закрыть чат — "
                       "ролик придёт сюда сообщением. Кредиты спишутся только за готовое видео."),
        "vid_progress": "🎬 <b>Генерирую…</b> {status} · {elapsed}\nМожно закрыть чат — ролик придёт сюда.",
        "vid_status_pending": "в очереди",
        "vid_status_processing": "снимаю",
        "vid_status_downloading": "скачиваю",
        "vid_status_joining": "склеиваю",
        "vid_done": "🎬 Видео готово · −{credits} кр · баланс {balance}",
        "vid_failed": "😕 Видео не получилось. Кредиты не списаны.",
        "vid_delayed": ("⏳ <b>Видео снимается дольше обычного</b>\nЗаказ не потерян: ролик придёт "
                        "сюда сообщением, как только будет готов, — кредиты спишутся только "
                        "тогда. Запускать заново не нужно."),
        "vid_extend_not_owned": ("Продлить можно только своё видео из этого аккаунта. "
                                 "Кредиты не списаны. Новый ролик: /video"),
        "vid_canceled": "⏹ Генерация отменена. Кредиты не списаны.",
        "vid_busy": "Одно видео уже генерируется — дождитесь его.",
        "vid_no_models": "Видео-модели сейчас недоступны.",
        "vid_cancel": "⏹ Отменить",
        "vid_ext": "⏩ Продлить",
        "vid_again": "🔁 Ещё вариант",
        "vid_share": "🔗 Поделиться",
        "vid_share_ready": "🔗 Ссылка на ролик:\n{url}",
        "vid_share_btn": "📤 Отправить другу",
        "vid_no_job": "Этот ролик уже не найти. Начните заново: /video",
        "vid_timeout": "Генерация затянулась. Как только ролик будет готов, он придёт сюда.",
        "vid_watch_offline": "🎬 Ролик придёт сюда сообщением, как только будет готов.",
        "vid_uploading": "⬆️ Загружаю кадр…",
        "vid_caption_cut": ("Подпись к фото ограничена {limit} символами — пришлите текст "
                            "отдельным сообщением. Фото уже стоит первым кадром."),
    },
    "en": {
        "vid_pick_model": "🎬 <b>Video</b>\nPick a model:",
        "vid_ask_prompt": ("🎬 Model: <b>{model}</b>{price}\n"
                           "Describe what should happen in the clip. You can send a photo with a caption — "
                           "it becomes the first frame."),
        "vid_card": ("🎬 <b>{prompt}</b>\n\nModel: <b>{model}</b>\n"
                     "Duration: <b>{duration} s</b> · Aspect: <b>{ar}</b>{res}\n"
                     "{first}Cost: <b>{cost} cr</b> · balance {balance}"),
        "vid_card_no_price": ("🎬 <b>{prompt}</b>\n\nModel: <b>{model}</b>\n"
                              "Duration: <b>{duration} s</b> · Aspect: <b>{ar}</b>{res}\n"
                              "{first}Cost: <b>unavailable</b> · balance {balance}\n"
                              "The model's price is unavailable right now, please try again later."),
        "vid_price_from": "from {credits} cr",
        "vid_refresh_price": "🔄 Refresh price",
        "vid_no_price": "The model's price is unavailable right now, please try again later.",
        "vid_price_changed": "The price has changed — check it and press Generate again.",
        "vid_first_frame": "First frame: your photo\n",
        "vid_extend": "Continuation of your clip\n",
        "vid_go": "🎬 Generate ({cost} cr)",
        "vid_not_enough": "➕ Top up (need {missing} more cr)",
        "vid_queued": ("⏳ <b>Video queued</b>\nUsually takes 1–8 minutes. You can close the chat — "
                       "the clip will arrive here. Credits are charged only for a finished video."),
        "vid_progress": "🎬 <b>Generating…</b> {status} · {elapsed}\nYou can close the chat — the clip will arrive here.",
        "vid_status_pending": "queued",
        "vid_status_processing": "rendering",
        "vid_status_downloading": "downloading",
        "vid_status_joining": "joining",
        "vid_done": "🎬 Video ready · −{credits} cr · balance {balance}",
        "vid_failed": "😕 The video did not come out. No credits were charged.",
        "vid_delayed": ("⏳ <b>The video is taking longer than usual</b>\nYour order is not lost: "
                        "the clip will arrive here as soon as it is ready — credits will be "
                        "charged only then. No need to start it again."),
        "vid_extend_not_owned": ("You can only extend your own video from this account. "
                                 "No credits were charged. New clip: /video"),
        "vid_canceled": "⏹ Generation cancelled. No credits were charged.",
        "vid_busy": "A video is already being generated — please wait for it.",
        "vid_no_models": "Video models are unavailable right now.",
        "vid_cancel": "⏹ Cancel",
        "vid_ext": "⏩ Extend",
        "vid_again": "🔁 Another",
        "vid_share": "🔗 Share",
        "vid_share_ready": "🔗 Link to the clip:\n{url}",
        "vid_share_btn": "📤 Send to a friend",
        "vid_no_job": "This clip can no longer be found. Start over: /video",
        "vid_timeout": "Generation is taking long. The clip will arrive here once ready.",
        "vid_watch_offline": "🎬 The clip will arrive here as soon as it is ready.",
        "vid_uploading": "⬆️ Uploading the frame…",
        "vid_caption_cut": ("Photo captions are limited to {limit} characters — please send "
                            "the text as a separate message. The photo is already set as the "
                            "first frame."),
    },
    "kg": {
        "vid_pick_model": "🎬 <b>Видео</b>\nМоделди тандаңыз:",
        "vid_ask_prompt": ("🎬 Модель: <b>{model}</b>{price}\n"
                           "Роликте эмне болушу керектигин сүрөттөңүз. Сүрөт жөнөтсөңүз — ал биринчи кадр болот."),
        "vid_card": ("🎬 <b>{prompt}</b>\n\nМодель: <b>{model}</b>\n"
                     "Узактыгы: <b>{duration} с</b> · Пропорция: <b>{ar}</b>{res}\n"
                     "{first}Баасы: <b>{cost} кр</b> · баланс {balance}"),
        "vid_card_no_price": ("🎬 <b>{prompt}</b>\n\nМодель: <b>{model}</b>\n"
                              "Узактыгы: <b>{duration} с</b> · Пропорция: <b>{ar}</b>{res}\n"
                              "{first}Баасы: <b>белгисиз</b> · баланс {balance}\n"
                              "Моделдин баасы азыр жеткиликсиз, бир аздан кийин кайра аракет кылыңыз."),
        "vid_price_from": "{credits} кр баштап",
        "vid_refresh_price": "🔄 Баасын жаңыртуу",
        "vid_no_price": "Моделдин баасы азыр жеткиликсиз, бир аздан кийин кайра аракет кылыңыз.",
        "vid_price_changed": "Баасы өзгөрдү — текшерип, «Жаратуу» баскычын кайра басыңыз.",
        "vid_first_frame": "Биринчи кадр: сиздин сүрөт\n",
        "vid_extend": "Роликтин уландысы\n",
        "vid_go": "🎬 Жаратуу ({cost} кр)",
        "vid_not_enough": "➕ Толуктоо ({missing} кр жетишпейт)",
        "vid_queued": ("⏳ <b>Видео кезекте</b>\nАдатта 1–8 мүнөт. Чатты жапсаңыз болот — "
                       "ролик ушул жерге келет. Кредиттер даяр видео үчүн гана алынат."),
        "vid_progress": "🎬 <b>Жаратып жатам…</b> {status} · {elapsed}\nЧатты жапсаңыз болот.",
        "vid_status_pending": "кезекте",
        "vid_status_processing": "тартып жатам",
        "vid_status_downloading": "жүктөп жатам",
        "vid_status_joining": "бириктирип жатам",
        "vid_done": "🎬 Видео даяр · −{credits} кр · баланс {balance}",
        "vid_failed": "😕 Видео чыккан жок. Кредиттер алынган жок.",
        "vid_delayed": ("⏳ <b>Видео адаттагыдан узагыраак тартылып жатат</b>\nБуйрутма жоголгон "
                        "жок: ролик даяр болору менен ушул жерге келет — кредиттер ошондо гана "
                        "алынат. Кайра баштоонун кереги жок."),
        "vid_extend_not_owned": ("Бул аккаунттагы өзүңүздүн видеоңузду гана узарта аласыз. "
                                 "Кредиттер алынган жок. Жаңы ролик: /video"),
        "vid_canceled": "⏹ Жаратуу токтотулду. Кредиттер алынган жок.",
        "vid_busy": "Бир видео жаратылып жатат — күтө туруңуз.",
        "vid_no_models": "Видео моделдери азыр жеткиликсиз.",
        "vid_cancel": "⏹ Токтотуу",
        "vid_ext": "⏩ Узартуу",
        "vid_again": "🔁 Дагы бир вариант",
        "vid_share": "🔗 Бөлүшүү",
        "vid_share_ready": "🔗 Роликке шилтеме:\n{url}",
        "vid_share_btn": "📤 Досуңузга жөнөтүү",
        "vid_no_job": "Бул ролик табылган жок. Кайра баштаңыз: /video",
        "vid_timeout": "Жаратуу узакка созулду. Даяр болгондо ролик ушул жерге келет.",
        "vid_watch_offline": "🎬 Ролик даяр болгондо ушул жерге билдирүү менен келет.",
        "vid_uploading": "⬆️ Кадрды жүктөп жатам…",
        "vid_caption_cut": ("Сүрөттүн жазуусу {limit} белги менен чектелген — текстти өзүнчө "
                            "билдирүү менен жөнөтүңүз. Сүрөт биринчи кадр болуп калды."),
    },
})


class VideoWizard(StatesGroup):
    prompt = State()


async def _video_models(token: str, lang: str, telegram_id: int) -> list:
    models = await _fetch(token, lang, telegram_id)
    return [m for m in models if m.get("category") == "video" and m.get("openrouter_id")]


async def _models_or_report(message: Message, token: str, lang: str, chat_id: int) -> list | None:
    """Каталог видео-моделей; None — API отказал и человеку уже сказано.

    Без этого ApiError (5xx/401/429) улетал из хендлера наружу: /video, выбор
    модели и «Ещё вариант» молча обрывались, кнопка «крутилась», а человек не
    получал ничего.
    """
    try:
        return await _video_models(token, lang, chat_id)
    except ApiError:
        logger.warning("видео: каталог моделей недоступен для %s", chat_id)
        await message.answer(t(lang, "server_down"))
        return None


def _price_label(lang: str, params: dict | None) -> str:
    """«от N кр» из таблицы цен сервера — тех же чисел, по которым спишут ролик.

    Тариф модели (кр/с) ценой ролика не является: у видео нижняя граница по
    себестоимости провайдера, а в режиме цен «наценка» тариф не участвует
    вовсе (у Seedance он 0). Цены нет — нет и подписи, а не «0 кр/с».
    """
    credits = price_from(params)
    return t(lang, "vid_price_from", credits=credits) if credits else ""


def _known(draft: dict) -> bool:
    """Модель черновика найдена в каталоге.

    Раньше признаком служил тариф модели (cps), и тариф 0 у Seedance читался как
    «модели нет»: «Ещё вариант» и «Продлить» отправляли выбирать модель заново.
    cps остался в черновиках, сохранённых до этого, — их тоже считаем.
    """
    return bool(draft.get("known") or draft.get("cps"))


async def _draft(chat_id: int) -> dict:
    return await store.get(chat_id, "vid_draft") or {}


async def _save(chat_id: int, draft: dict) -> None:
    await store.set(chat_id, "vid_draft", draft, ttl=3600)


def result_keyboard(lang: str, uid: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=t(lang, "vid_ext"), callback_data=f"v:ext:{uid}"),
         InlineKeyboardButton(text=t(lang, "vid_again"), callback_data=f"v:re:{uid}")],
        [InlineKeyboardButton(text=t(lang, "vid_share"), callback_data=f"v:sh:{uid}")],
    ])


# ---------------------------------------------------------------- шаги ---

@router.message(Command("video"))
async def cmd_video(message: Message, command: CommandObject, token: str, lang: str,
                    state: FSMContext) -> None:
    await start_wizard(message, token, lang, state, prompt=(command.args or "").strip())


async def start_wizard(message: Message, token: str, lang: str, state: FSMContext, *,
                       prompt: str = "", first_frame: dict | None = None,
                       extend_url: str = "") -> None:
    chat_id = message.chat.id
    await state.clear()
    draft = {"prompt": prompt, "first_frame": first_frame, "extend": extend_url}
    await _save(chat_id, draft)
    await _pick_model(message, token, lang, chat_id)


async def start_from_photo(message: Message, token: str, lang: str, state: FSMContext,
                           attachment: dict) -> None:
    await start_wizard(message, token, lang, state, first_frame=attachment)


async def _pick_model(message: Message, token: str, lang: str, chat_id: int,
                      *, edit: bool = False) -> None:
    models = await _models_or_report(message, token, lang, chat_id)
    if models is None:
        return
    if not models:
        await message.answer(t(lang, "vid_no_models"))
        return
    shown = models[:12]
    # Цены — из таблиц сервера, с тем же кэшем, что у карточки ролика.
    params = await asyncio.gather(*(_params(token, lang, chat_id, str(m.get("openrouter_id")))
                                    for m in shown))
    buttons = []
    for index, (m, p) in enumerate(zip(shown, params)):
        # Части подписи склеиваем по непустым: без цены в подписи иначе
        # повисал разделитель без числа — «Veo ·  · быстрая».
        parts = [f"{'🔒 ' if m.get('locked') else ''}{m.get('name')}",
                 _price_label(lang, p), (m.get("short_label") or "").strip()]
        label = " · ".join(p for p in parts if p)
        buttons.append(InlineKeyboardButton(text=label[:60], callback_data=f"v:m:{index}"))
    rows = rows_of(buttons, 1)
    rows.append([InlineKeyboardButton(text=t(lang, "btn_close"), callback_data="v:x")])
    markup = InlineKeyboardMarkup(inline_keyboard=rows)
    if edit:
        try:
            await message.edit_text(t(lang, "vid_pick_model"), parse_mode="HTML", reply_markup=markup)
            return
        except Exception:
            pass
    await message.answer(t(lang, "vid_pick_model"), parse_mode="HTML", reply_markup=markup)


@router.callback_query(F.data.startswith("v:m:"))
async def pick_model(call: CallbackQuery, token: str, lang: str, state: FSMContext) -> None:
    chat_id = call.message.chat.id
    # Ответ на callback — до похода в API: иначе при медленном или упавшем
    # каталоге кнопка «крутится» и запрос успевает протухнуть.
    await call.answer()
    models = await _models_or_report(call.message, token, lang, chat_id)
    if models is None:
        return
    try:
        chosen = models[int(call.data.split(":")[2])]
    except (IndexError, ValueError):
        return
    if chosen.get("locked"):
        await show_paywall(call.message, lang, ApiError(403, code="premium_locked"))
        return
    draft = await _draft(chat_id)
    if draft.get("model") != chosen.get("openrouter_id"):
        # Цены и качество прошлой модели к новой не относятся: иначе на карточке
        # Veo висела бы цена Seedance 1080p, пока не придут свои параметры.
        for key in ("prices", "prices_ar", "res"):
            draft.pop(key, None)
    draft["model"] = chosen.get("openrouter_id")
    draft["model_name"] = chosen.get("name")
    draft["known"] = True
    await _save(chat_id, draft)
    if draft.get("prompt"):
        await _show_card(call.message, token, lang, chat_id, draft)
        return
    await state.set_state(VideoWizard.prompt)
    label = _price_label(lang, await _params(token, lang, chat_id, str(draft["model"])))
    await call.message.answer(t(lang, "vid_ask_prompt", model=esc(chosen.get("name")),
                                price=f" · {label}" if label else ""), parse_mode="HTML")


# Замки склейки промпта по (чат, человек). Апдейты aiogram обрабатывает
# параллельными задачами в одном процессе (опрос держит ровно один экземпляр,
# см. hold_lock), а данные FSM читаются и пишутся за два похода в Redis — без
# замка две части, пришедшие вместе, перетёрли бы друг друга. Слабые ссылки:
# замок живёт, пока его кто-то держит или ждёт.
_prompt_locks: "weakref.WeakValueDictionary[tuple[int, int], asyncio.Lock]" = (
    weakref.WeakValueDictionary())


def _prompt_lock(key: tuple[int, int]) -> asyncio.Lock:
    lock = _prompt_locks.get(key)
    if lock is None:
        lock = asyncio.Lock()
        _prompt_locks[key] = lock
    return lock


def _author_key(message: Message) -> tuple[int, int]:
    user = getattr(message, "from_user", None)
    return message.chat.id, int(getattr(user, "id", 0) or 0)


_SENTENCE_END = (".", "!", "?", "…", ":", ";", "»", '"', ")")


def _join_parts(parts: list) -> str:
    """Склеить части по порядку сообщений.

    Telegram режет по пробелу или переносу и срезает его по краям частей.
    После конца фразы ставим перенос (скорее всего там был абзац), иначе —
    пробел, чтобы слова на стыке не слиплись.
    """
    by_id: dict[int, str] = {}
    for item in parts or []:
        try:
            by_id[int(item[0])] = str(item[1] or "")
        except (TypeError, ValueError, IndexError):
            continue
    out = ""
    for _, text in sorted(by_id.items()):
        text = text.strip()
        if not text:
            continue
        if out:
            out += ("\n" if out.endswith(_SENTENCE_END) else " ")
        out += text
    return out


def _caption_cut(caption: str | None) -> int:
    """Предел, по которому Telegram обрезал подпись, или 0.

    Длину считаем и в символах, и в единицах UTF-16 (так Telegram меряет
    тексты): иначе подпись с эмодзи проскочила бы проверку.
    """
    raw = caption or ""
    lengths = {len(raw), len(raw.encode("utf-16-le")) // 2}
    return next((limit for limit in CAPTION_LIMITS if limit in lengths), 0)


@router.message(VideoWizard.prompt, F.text & ~F.text.startswith("/"))
async def got_prompt(message: Message, token: str, lang: str, state: FSMContext) -> None:
    from bot.keyboards.common import MENU_ACTIONS

    if message.text in MENU_ACTIONS:
        await state.clear()
        return
    key = _author_key(message)
    now = time.time()
    async with _prompt_lock(key):
        if await state.get_state() != VideoWizard.prompt.state:
            # Соседняя часть уже закрыла окно, или человек ушёл командой, пока
            # это сообщение ждало замка.
            logger.info("видео %s: часть промпта опоздала к склейке", key[0])
            return
        buffer = (await state.get_data()).get(PROMPT_BUFFER_KEY) or {}
        parts = list(buffer.get("parts") or [])
        if parts and now - float(buffer.get("at") or 0) > PROMPT_BUFFER_STALE:
            logger.warning("видео %s: брошенный буфер промпта (%s частей) пропущен",
                           key[0], len(parts))
            parts = []
        # Повтор того же апдейта (AuthMiddleware после 401) не дублирует текст.
        parts = [p for p in parts if p and p[0] != message.message_id]
        parts.append([message.message_id, message.text])
        seq = int(buffer.get("seq") or 0) + 1
        await state.update_data(**{PROMPT_BUFFER_KEY: {"parts": parts, "seq": seq, "at": now}})

    # Ждём прямо в обработчике: aiogram ведёт каждый апдейт своей задачей, так
    # что соседние части в это время обрабатываются, а ошибки показа карточки
    # остаются под ErrorsMiddleware.
    await asyncio.sleep(PROMPT_MERGE_WINDOW)

    chat_id = message.chat.id
    # Черновик правим под тем же замком, что и got_photo: иначе кадр, который
    # догружался вместе с текстом, мог затереться склейкой (и наоборот).
    async with _prompt_lock(key):
        if await state.get_state() != VideoWizard.prompt.state:
            return  # человек ушёл командой или меню — промпт больше не нужен
        buffer = (await state.get_data()).get(PROMPT_BUFFER_KEY) or {}
        if int(buffer.get("seq") or 0) != seq:
            return  # после нас пришла ещё часть — склеит её обработчик
        prompt = _join_parts(buffer.get("parts") or [])
        if not prompt:
            return
        await state.clear()
        draft = await _draft(chat_id)
        draft["prompt"] = prompt
        await _save(chat_id, draft)
    await _show_card(message, token, lang, chat_id, draft)


@router.message(VideoWizard.prompt, F.photo)
async def got_photo(message: Message, token: str, lang: str, state: FSMContext) -> None:
    from bot.routers.media import _upload, download

    chat_id = message.chat.id
    photo = message.photo[-1]
    await message.bot.send_chat_action(chat_id, ChatAction.UPLOAD_PHOTO)
    content = await download(message, photo.file_id, photo.file_size or 0, lang)
    if content is None:
        return
    attachment = await _upload(message, token, lang, "frame.jpg", content, "image/jpeg")
    if attachment is None:
        return
    # Подпись ровно по пределу Telegram — обрывок: ролик по нему был бы
    # оплачен за не то. Кадр принимаем, шаг промпта оставляем открытым —
    # следующий текст станет промптом.
    cut = _caption_cut(message.caption)
    caption = "" if cut else (message.caption or "").strip()
    async with _prompt_lock(_author_key(message)):
        draft = await _draft(chat_id)
        draft["first_frame"] = attachment
        if caption:
            draft["prompt"] = caption
            await state.clear()
        await _save(chat_id, draft)
        text_pending = bool((await state.get_data()).get(PROMPT_BUFFER_KEY))
        # Текст, отправленный вместе с фото, склеился, пока фото загружалось:
        # его карточка ушла без кадра.
        merged_meanwhile = (not caption and bool(draft.get("prompt"))
                            and await state.get_state() != VideoWizard.prompt.state)
    if cut:
        await message.answer(t(lang, "vid_caption_cut", limit=cut))
        return
    if caption or merged_meanwhile:
        await _show_card(message, token, lang, chat_id, draft)
        return
    if text_pending:
        return  # текст ещё копится — карточку с кадром покажет склейка
    await message.answer(t(lang, "vid_ask_prompt", model=esc(draft.get("model_name", "")),
                           price=""), parse_mode="HTML")


async def _params(token: str, lang: str, chat_id: int, model: str) -> dict:
    cached = await store.get(chat_id, f"vparams:{model}")
    if cached:
        return cached
    try:
        params = await api.video_params(token, model, lang=lang, telegram_id=chat_id)
    except ApiError:
        # Сбой не кэшируем: без таблицы цен карточка не даст запустить ролик, и
        # минуты «цена недоступна» из-за одного неудачного ответа — перебор.
        return {}
    params = params if isinstance(params, dict) else {}
    await store.set(chat_id, f"vparams:{model}", params, ttl=PARAMS_TTL)
    return params


def _price_tables(params: dict) -> dict:
    """Таблицы цен из ответа ai/video-params — в том виде, в каком их держит черновик."""
    table = params.get("price_table")
    by_aspect = params.get("price_table_by_aspect")
    return {"prices": table if isinstance(table, dict) else {},
            "prices_ar": by_aspect if isinstance(by_aspect, dict) else {}}


def _cost(draft: dict) -> int | None:
    """Цена ролика из таблицы сервера под длительность, пропорции и разрешение.

    None — ячейки нет: сервер цену не дал (в режиме цен «наценка» у модели нет
    себестоимости) или не ответил. «Секунды × тариф» больше не считаем: у видео
    тариф — не цена, и «1 кр» за ролик Seedance с тарифом 0 было бы неправдой.
    """
    duration = int(draft.get("duration") or 5)
    res = str(draft.get("res") or "")
    # У Seedance цена зависит и от пропорций (21:9 — на треть больше пикселей).
    by_aspect = (draft.get("prices_ar") or {}).get(str(draft.get("ar") or "")) or {}
    plain = draft.get("prices") or {}
    row = by_aspect.get(res) or plain.get(res)
    if row is None and not res:
        # Качество у модели не выбирается: таблица одна — под разрешение по умолчанию.
        rows = by_aspect or plain
        if len(rows) == 1:
            row = next(iter(rows.values()))
    try:
        exact = int((row or {}).get(str(duration)) or 0)
    except (TypeError, ValueError, AttributeError):
        exact = 0
    return exact if exact > 0 else None


async def _show_card(message: Message, token: str, lang: str, chat_id: int, draft: dict,
                     *, edit: bool = False, note: str = "") -> None:
    params = await _params(token, lang, chat_id, draft.get("model", ""))
    durations = params.get("durations") or [5]
    if not draft.get("duration") or int(draft["duration"]) not in durations:
        draft["duration"] = params.get("default_duration") or durations[0]
    ratios = params.get("aspect_ratios") or []
    if ratios and draft.get("ar") not in ratios:
        draft["ar"] = "16:9" if "16:9" in ratios else ratios[0]
    draft.setdefault("ar", "16:9")
    resolutions = params.get("resolutions") or []
    if resolutions and draft.get("res") not in resolutions:
        draft["res"] = params.get("default_resolution") or resolutions[0]
    draft.update(_price_tables(params))
    cost = _cost(draft)
    # Цена, которую человек видит на кнопке: перед запуском её сверяем со свежей.
    draft["shown_cost"] = cost
    await _save(chat_id, draft)

    try:
        balance = int((await api.balance(token, lang=lang, telegram_id=chat_id)).get("balance_tokens", 0))
    except ApiError:
        balance = 0
    first = ""
    if draft.get("extend"):
        first = t(lang, "vid_extend")
    elif draft.get("first_frame"):
        first = t(lang, "vid_first_frame")
    res = f" · {draft['res']}" if draft.get("res") and len(resolutions) > 1 else ""
    # Промпт пишет человек, название модели приходит из каталога: «<» в любом из
    # них Telegram считает открытым тегом и отвергает всё сообщение целиком.
    fields = {"prompt": esc(draft.get("prompt", "")[:300]), "model": esc(draft.get("model_name", "")),
              "duration": draft["duration"], "ar": draft["ar"], "res": res, "first": first,
              "balance": balance}
    text = (t(lang, "vid_card_no_price", **fields) if cost is None
            else t(lang, "vid_card", cost=cost, **fields))
    if note:
        text = f"{text}\n\n{note}"

    rows = []
    if len(durations) > 1:
        rows += rows_of([InlineKeyboardButton(
            text=("• " if d == draft["duration"] else "") + f"{d} с", callback_data=f"v:d:{d}")
            for d in durations[:12]], 4)
    if len(ratios) > 1:
        rows += rows_of([InlineKeyboardButton(
            text=("• " if r == draft["ar"] else "") + r, callback_data=f"v:ar:{r}")
            for r in ratios[:8]], 4)
    if len(resolutions) > 1:
        rows += rows_of([InlineKeyboardButton(
            text=("• " if r == draft.get("res") else "") + r, callback_data=f"v:r:{i}")
            for i, r in enumerate(resolutions[:6])], 3)
    if cost is None:
        # Без цены запуск не предлагаем: списали бы сумму, которой человек не видел.
        rows.append([InlineKeyboardButton(text=t(lang, "vid_refresh_price"), callback_data="v:rf")])
    elif balance < cost:
        rows.append([InlineKeyboardButton(text=t(lang, "vid_not_enough", missing=cost - balance),
                                          callback_data="b:topup")])
    else:
        rows.append([InlineKeyboardButton(text=t(lang, "vid_go", cost=cost), callback_data="v:go")])
    rows.append([InlineKeyboardButton(text=t(lang, "btn_close"), callback_data="v:x")])
    markup = InlineKeyboardMarkup(inline_keyboard=rows)
    if edit:
        try:
            await message.edit_text(text, parse_mode="HTML", reply_markup=markup)
            return
        except Exception:
            pass
    await message.answer(text, parse_mode="HTML", reply_markup=markup)


@router.callback_query(F.data.startswith("v:d:"))
async def pick_duration(call: CallbackQuery, token: str, lang: str) -> None:
    chat_id = call.message.chat.id
    draft = await _draft(chat_id)
    try:
        draft["duration"] = int(call.data.split(":")[2])
    except ValueError:
        await call.answer()
        return
    await call.answer()
    await _show_card(call.message, token, lang, chat_id, draft, edit=True)


@router.callback_query(F.data.startswith("v:ar:"))
async def pick_ratio(call: CallbackQuery, token: str, lang: str) -> None:
    chat_id = call.message.chat.id
    draft = await _draft(chat_id)
    draft["ar"] = call.data.split(":", 2)[2]
    await call.answer()
    await _show_card(call.message, token, lang, chat_id, draft, edit=True)


@router.callback_query(F.data.startswith("v:r:"))
async def pick_resolution(call: CallbackQuery, token: str, lang: str) -> None:
    chat_id = call.message.chat.id
    draft = await _draft(chat_id)
    params = await _params(token, lang, chat_id, draft.get("model", ""))
    try:
        draft["res"] = (params.get("resolutions") or [])[int(call.data.split(":")[2])]
    except (IndexError, ValueError):
        pass
    await call.answer()
    await _show_card(call.message, token, lang, chat_id, draft, edit=True)


@router.callback_query(F.data == "v:x")
async def cancel_wizard(call: CallbackQuery, lang: str, state: FSMContext) -> None:
    await state.clear()
    await store.drop(call.message.chat.id, "vid_draft")
    await call.answer()
    try:
        await call.message.delete()
    except Exception:
        pass


# --------------------------------------------------------------- запуск ---

@router.callback_query(F.data == "v:rf")
async def refresh_price(call: CallbackQuery, token: str, lang: str) -> None:
    """«Обновить цену»: прошлый ответ сервера пришёл без цены — спрашиваем заново."""
    chat_id = call.message.chat.id
    draft = await _draft(chat_id)
    await call.answer()
    if not draft.get("model"):
        return
    await store.drop(chat_id, f"vparams:{draft['model']}")
    await _show_card(call.message, token, lang, chat_id, draft, edit=True)


@router.callback_query(F.data == "v:go")
async def go(call: CallbackQuery, token: str, lang: str) -> None:
    chat_id = call.message.chat.id
    draft = await _draft(chat_id)
    await call.answer()
    if not draft.get("prompt") or not draft.get("model"):
        return
    try:
        await call.message.edit_reply_markup(reply_markup=None)
    except Exception:
        pass
    # Карточка могла провисеть долго: курс, режим цен или себестоимость за это
    # время поменялись, а ядро спишет цену на момент запуска. Сверяем свежую
    # цену с той, что была на кнопке; разошлась — карточка заново, без запуска.
    await store.drop(chat_id, f"vparams:{draft['model']}")
    fresh = _cost({**draft, **_price_tables(await _params(token, lang, chat_id, draft["model"]))})
    if fresh is None or fresh != draft.get("shown_cost"):
        note = t(lang, "vid_price_changed") if fresh is not None else ""
        await _show_card(call.message, token, lang, chat_id, draft, edit=True, note=note)
        return
    await launch(call.message, token, lang, draft)


async def _launch_failed(message: Message, lang: str, exc: ApiError) -> None:
    """Объяснить, почему ролик не встал в очередь (кредиты при отказе не списаны)."""
    if exc.is_paywall:
        await show_paywall(message, lang, exc)
    elif exc.code in ("job_in_progress", "video_in_progress"):
        await message.answer(t(lang, "vid_busy"))
    elif exc.code == "extend_not_owned":
        await message.answer(t(lang, "vid_extend_not_owned"))
    elif exc.code == "price_unavailable":
        # 503 от режима цен «наценка»: у модели нет себестоимости. Это не поломка
        # сервера — «сервер не отвечает» было бы неправдой.
        await message.answer(t(lang, "vid_no_price"))
    elif exc.status == 429:
        # Лимит запросов, а не поломка: «сервер не отвечает» тут было бы неправдой.
        await message.answer(t(lang, "rate_limited"))
    elif exc.is_temporary:
        await message.answer(t(lang, "server_down"))
    else:
        await message.answer(t(lang, "failed"))


async def launch(message: Message, token: str, lang: str, draft: dict) -> None:
    chat_id = message.chat.id
    body = {
        "kind": "video",
        "message": draft.get("prompt", ""),
        "model": draft.get("model"),
        "video_duration": draft.get("duration"),
        "aspect_ratio": draft.get("ar"),
        "lang": lang,
        "notify": "telegram",
    }
    if draft.get("res"):
        body["video_resolution"] = draft["res"]
    if draft.get("first_frame"):
        body["attachments"] = [draft["first_frame"]]
    if draft.get("extend"):
        body["extend_video_url"] = draft["extend"]
    session_id = await store.get(chat_id, "session")
    if session_id:
        body["session_id"] = session_id
    try:
        job = await api.create_job(token, body, lang=lang, telegram_id=chat_id)
    except ApiError as exc:
        # Сохранённый чат мог быть удалён на сайте: ядро отвечает 404 «Session
        # not found», и с протухшим ключом так же падал бы каждый следующий
        # запуск видео. Забываем ключ и повторяем ровно один раз — без него ядро
        # заведёт новый чат. Повтор безопасен: на этом отказе ядро ничего не
        # списало и дневной лимит вернуло само. Опознаём отказ тем же
        # предикатом, что и чат: ключ «session» общий с текстовым чатом, и
        # стирать его на любом чужом 404 (упавший маршрут, ошибка прокси)
        # значило бы молча обрывать человеку ещё и переписку.
        if _session_gone(exc) and body.pop("session_id", None):
            logger.info("видео: сессия %s пропала, начинаю новую для %s", session_id, chat_id)
            await store.drop(chat_id, "session")
            try:
                job = await api.create_job(token, body, lang=lang, telegram_id=chat_id)
            except ApiError as retry_exc:
                await _launch_failed(message, lang, retry_exc)
                return
        else:
            await _launch_failed(message, lang, exc)
            return
    uid = job.get("job_id")
    await store.set(chat_id, f"vjob:{uid}", {**draft, "job": uid}, ttl=7 * 24 * 3600)
    session = job.get("session") or {}
    if session.get("id"):
        await store.set(chat_id, "session", session["id"])
    progress = await message.answer(
        t(lang, "vid_queued"), parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text=t(lang, "vid_cancel"), callback_data=f"v:cancel:{uid}")]]))
    asyncio.create_task(_watch(message.bot, chat_id, progress.message_id, uid, token, lang,
                               notify=body.get("notify", "")))


def _status_label(lang: str, status: str) -> str:
    key = {"pending": "vid_status_pending", "queued": "vid_status_pending",
           "starting": "vid_status_pending", "downloading": "vid_status_downloading",
           "joining": "vid_status_joining"}.get(status, "vid_status_processing")
    return t(lang, key)


async def _watch(bot: Bot, chat_id: int, message_id: int, uid: str, token: str, lang: str,
                 *, notify: str = "telegram") -> None:
    """Следить за задачей и обновлять сообщение-прогресс.

    `notify` — кого мы попросили доставить ролик при постановке задачи. Если
    «telegram», ролик шлёт ядро, и наша отправка — только подстраховка.
    """
    started = time.monotonic()
    last_text = ""
    job: dict = {}
    while time.monotonic() - started < POLL_MAX_SECONDS:
        await asyncio.sleep(POLL_INTERVAL)
        try:
            job = await api.job(token, uid, lang=lang, telegram_id=chat_id)
        except ApiError as exc:
            if exc.status == 401:
                fresh = await store.get_token(chat_id)
                if not fresh or fresh == token:
                    # Токен протух, а нового в хранилище нет (его обновит только
                    # следующее сообщение человека) — опрос будет получать 401 до
                    # самого таймаута. Ядро пришлёт ролик само, поэтому просто
                    # закрываем слежение честной подписью.
                    try:
                        await bot.edit_message_text(t(lang, "vid_watch_offline"),
                                                    chat_id=chat_id, message_id=message_id)
                    except Exception:
                        pass
                    return
                token = fresh
            continue
        status = job.get("status")
        if status in ("done", "failed", "canceled", "delayed"):
            break
        elapsed = int(time.monotonic() - started)
        text = t(lang, "vid_progress", status=_status_label(lang, job.get("progress") or ""),
                 elapsed=f"{elapsed // 60}:{elapsed % 60:02d}")
        if text != last_text:
            last_text = text
            try:
                await bot.edit_message_text(
                    text, chat_id=chat_id, message_id=message_id, parse_mode="HTML",
                    reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
                        InlineKeyboardButton(text=t(lang, "vid_cancel"),
                                             callback_data=f"v:cancel:{uid}")]]))
            except Exception:
                pass
        try:
            await bot.send_chat_action(chat_id, ChatAction.RECORD_VIDEO)
        except Exception:
            pass
    else:
        try:
            await bot.edit_message_text(t(lang, "vid_timeout"), chat_id=chat_id,
                                        message_id=message_id)
        except Exception:
            pass
        return

    status = job.get("status")
    if _is_delayed(job):
        await _report_delayed(bot, chat_id, message_id, job, lang, notify=notify)
        return
    try:
        await bot.delete_message(chat_id, message_id)
    except Exception:
        pass
    if status == "canceled":
        await bot.send_message(chat_id, t(lang, "vid_canceled"))
        return
    if notify != "telegram":
        # Слать ролик некому: ядро об этом не просили — доставляем сразу.
        await deliver(bot, chat_id, job, lang)
        return
    # Отметка ядра означает НАМЕРЕНИЕ отправить, а не доставку: ядро ставит её
    # перед обращением к Telegram и СНИМАЕТ, если тот отказал (ролик тяжелее
    # 20 МБ, ссылка не открылась) — тогда доставить обязаны мы. Выйти по первой
    # же отметке нельзя: ядро ставит её через миллисекунды после статуса done,
    # так что видим мы её почти всегда, а отказ Telegram приходит десятками
    # секунд позже — человек остался бы без ролика, за который уже списаны
    # кредиты. Поэтому отметку нужно не увидеть, а выдержать.
    stale = False
    seen = 0
    for _ in range(NOTIFY_ATTEMPTS):
        if job.get("notified"):
            # Считаем только прочитанное живьём: на неудачном перечитывании
            # job остаётся прежним и ничего не подтверждает.
            seen = 0 if stale else seen + 1
            if seen >= NOTIFY_CONFIRM:
                return
        elif seen:
            logger.warning("видео %s: ядро сняло отметку доставки, шлём сами", uid)
            break
        await asyncio.sleep(NOTIFY_GRACE)
        try:
            job = await api.job(token, uid, lang=lang, telegram_id=chat_id) or job
            stale = False
        except ApiError:
            # Сеть моргнула — это не повод считать, что ядро не отправило.
            stale = True
    if job.get("notified"):
        return
    if stale:
        logger.warning("видео %s: отметку доставки прочитать не удалось, шлём сами", uid)
    await deliver(bot, chat_id, job, lang)


def _is_delayed(job: dict) -> bool:
    """Ролик ещё снимается и придёт позже — это не неудача.

    Ядро отдаёт такую задачу фоновому довозу (core/ai/recovery.py) в статусе
    delayed. Ядро до этого статуса закрывало её как failed с кодом
    video_delayed — понимаем и так, иначе задачи, начатые до выкладки, снова
    получили бы «не получилось» с кнопкой «Повторить».
    """
    return job.get("status") == "delayed" or job.get("error_code") == "video_delayed"


async def _report_delayed(bot: Bot, chat_id: int, message_id: int, job: dict, lang: str,
                          *, notify: str) -> None:
    """Сказать, что ролик снимается дольше обычного, и перестать следить.

    Ролик довезёт, спишет и пришлёт сюда само ядро. Раньше бот статуса delayed
    не знал и до таймаута крутил «Генерирую…» с кнопкой «Отменить», которая
    такую задачу уже не отменяет.
    """
    if notify == "telegram" and job.get("notified"):
        # Ядро уже написало об этом отдельным сообщением — второе такое же лишнее.
        try:
            await bot.delete_message(chat_id, message_id)
        except Exception:
            pass
        return
    try:
        # Правим сам прогресс: без reply_markup уходит и кнопка «Отменить».
        await bot.edit_message_text(t(lang, "vid_delayed"), chat_id=chat_id,
                                    message_id=message_id, parse_mode="HTML")
        return
    except Exception:
        pass
    await bot.send_message(chat_id, t(lang, "vid_delayed"), parse_mode="HTML")


async def deliver(bot: Bot, chat_id: int, job: dict, lang: str) -> None:
    uid = job.get("job_id", "")
    if job.get("status") == "done":
        result = job.get("result") or {}
        atts = (result.get("message") or {}).get("attachments") or []
        video = next((a for a in atts if a.get("type") == "video"), None)
        caption = t(lang, "vid_done", credits=result.get("tokens_charged", 0),
                    balance=result.get("balance_tokens", "—"))
        if video and video.get("url"):
            try:
                await bot.send_video(chat_id, site_url(video["url"]), caption=caption,
                                     supports_streaming=True, reply_markup=result_keyboard(lang, uid))
                return
            except Exception:
                logger.exception("видео не отправилось")
                await bot.send_message(chat_id, site_url(video["url"]),
                                       reply_markup=result_keyboard(lang, uid))
                return
        await bot.send_message(chat_id, caption, reply_markup=result_keyboard(lang, uid))
        return
    if _is_delayed(job):
        # Без «не получилось» и без «Повторить»: повтор запустил бы второй
        # платный ролик, а первый всё равно придёт и спишется.
        await bot.send_message(chat_id, t(lang, "vid_delayed"), parse_mode="HTML")
        return
    error = job.get("error_code") or ""
    if error in ("insufficient_balance", "insufficient_tokens"):
        await bot.send_message(chat_id, t(lang, "paywall_balance",
                                          have=(job.get("result") or {}).get("balance_tokens", 0),
                                          need=(job.get("result") or {}).get("required_estimate", "—")),
                               parse_mode="HTML", reply_markup=paywall(lang, settings.site_base_url))
        return
    if error == "extend_not_owned":
        # Ролик чужой. «Повторить» сбрасывает продление (см. again) и запустил
        # бы новый платный ролик вместо того, о чём просили, — кнопку не даём.
        await bot.send_message(chat_id, t(lang, "vid_extend_not_owned"))
        return
    retry = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text=t(lang, "btn_retry"), callback_data=f"v:re:{uid}")]])
    if error in ("video_in_progress", "job_in_progress"):
        # Ничего не сломалось: снимается другой ролик. Повторить можно после него.
        await bot.send_message(chat_id, t(lang, "vid_busy"), reply_markup=retry)
        return
    await bot.send_message(chat_id, t(lang, "vid_failed"), reply_markup=retry)


@router.callback_query(F.data.startswith("v:cancel:"))
async def cancel_job(call: CallbackQuery, token: str, lang: str) -> None:
    uid = call.data.split(":", 2)[2]
    try:
        await api.cancel_job(token, uid, lang=lang, telegram_id=call.message.chat.id)
    except ApiError:
        pass
    await call.answer(t(lang, "vid_cancel"))


# ------------------------------------------------- кнопки под роликом ---

async def _job_draft(chat_id: int, token: str, lang: str, uid: str) -> dict | None:
    draft = await store.get(chat_id, f"vjob:{uid}")
    if draft:
        return draft
    # Бот перезапускался, черновик протух (7 дней) или это ролик с сайта:
    # восстанавливаем из задачи. Ядро отдаёт только промпт, модель и ссылку —
    # длительности, пропорций и разрешения в ответе нет, поэтому помечаем
    # черновик «restored»: повторять платный запуск вслепую по ним нельзя.
    try:
        job = await api.job(token, uid, lang=lang, telegram_id=chat_id)
    except ApiError:
        return None
    result = job.get("result") or {}
    message = result.get("message") or {}
    video = next((a for a in (message.get("attachments") or []) if a.get("type") == "video"), None)
    return {"prompt": (video or {}).get("prompt") or "", "model": (video or {}).get("model") or "",
            "job": uid, "url": (video or {}).get("url") or "", "duration": None,
            "restored": True}


@router.callback_query(F.data.startswith("v:re:"))
async def again(call: CallbackQuery, token: str, lang: str) -> None:
    chat_id = call.message.chat.id
    await call.answer()
    draft = await _job_draft(chat_id, token, lang, call.data.split(":", 2)[2])
    if not draft or not draft.get("prompt") or not draft.get("model"):
        await call.message.answer(t(lang, "vid_no_job"))
        return
    draft = {**draft, "extend": ""}
    if not _known(draft):
        models = await _models_or_report(call.message, token, lang, chat_id)
        if models is None:
            return
        chosen = next((m for m in models if m.get("openrouter_id") == draft["model"]), None)
        if chosen:
            draft["known"] = True
            draft["model_name"] = chosen.get("name")
    if draft.pop("restored", False):
        # Сообщение с кнопкой живёт вечно, черновик — 7 дней. Исходные параметры
        # (длительность, пропорции, разрешение) восстановить неоткуда, а тихо
        # запустить платную генерацию «по умолчанию» — значит списать кредиты за
        # не то, что человек нажимал. Показываем карточку и ждём подтверждения.
        await _save(chat_id, draft)
        if not _known(draft):
            # Модели уже нет в каталоге: цену взять неоткуда. Как и в «Продлить»,
            # просим выбрать модель заново.
            await _pick_model(call.message, token, lang, chat_id)
            return
        await _show_card(call.message, token, lang, chat_id, draft)
        return
    # Черновик живёт неделю, а цена за это время могла смениться (курс, режим цен)
    # или пропасть. Повторяем молча только по той же цене, иначе — карточка.
    fresh = _cost({**draft, **_price_tables(await _params(token, lang, chat_id, draft["model"]))})
    shown = draft.get("shown_cost")
    if fresh is None or (shown is not None and fresh != shown):
        await _save(chat_id, draft)
        note = t(lang, "vid_price_changed") if fresh is not None else ""
        await _show_card(call.message, token, lang, chat_id, draft, note=note)
        return
    await launch(call.message, token, lang, draft)


@router.callback_query(F.data.startswith("v:ext:"))
async def extend(call: CallbackQuery, token: str, lang: str, state: FSMContext) -> None:
    chat_id = call.message.chat.id
    uid = call.data.split(":", 2)[2]
    await call.answer()  # до похода в API: запрос протухает за секунды
    draft = await _job_draft(chat_id, token, lang, uid)
    url = (draft or {}).get("url")
    if not url:
        try:
            job = await api.job(token, uid, lang=lang, telegram_id=chat_id)
            atts = ((job.get("result") or {}).get("message") or {}).get("attachments") or []
            url = next((a.get("url") for a in atts if a.get("type") == "video"), "")
        except ApiError:
            url = ""
    if not url:
        await call.message.answer(t(lang, "vid_no_job"))
        return
    await state.clear()
    draft = draft or {}
    new = {"prompt": draft.get("prompt", ""), "model": draft.get("model"),
           "model_name": draft.get("model_name", ""), "known": _known(draft),
           "extend": url, "first_frame": None, "duration": draft.get("duration"),
           "ar": draft.get("ar")}
    await _save(chat_id, new)
    if new["model"] and new["known"]:
        await _show_card(call.message, token, lang, chat_id, new)
    else:
        await _pick_model(call.message, token, lang, chat_id)


@router.callback_query(F.data.startswith("v:sh:"))
async def share(call: CallbackQuery, token: str, lang: str) -> None:
    chat_id = call.message.chat.id
    uid = call.data.split(":", 2)[2]
    await call.answer()  # до похода в API: запрос протухает за секунды
    draft = await _job_draft(chat_id, token, lang, uid) or {}
    url = draft.get("url")
    if not url:
        try:
            job = await api.job(token, uid, lang=lang, telegram_id=chat_id)
            atts = ((job.get("result") or {}).get("message") or {}).get("attachments") or []
            url = next((a.get("url") for a in atts if a.get("type") == "video"), "")
        except ApiError:
            url = ""
    if not url:
        await call.message.answer(t(lang, "vid_no_job"))
        return
    try:
        shared = await api.video_share(token, url, prompt=draft.get("prompt", ""),
                                       model=draft.get("model", ""), lang=lang, telegram_id=chat_id)
    except ApiError:
        await call.message.answer(t(lang, "server_down"))
        return
    link = shared.get("share_url") or f"{settings.site_base_url}/v/{shared.get('slug', '')}"
    share_url = f"https://t.me/share/url?url={link}"
    await call.message.answer(
        t(lang, "vid_share_ready", url=link), disable_web_page_preview=False,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text=t(lang, "vid_share_btn"), url=share_url)]]))
