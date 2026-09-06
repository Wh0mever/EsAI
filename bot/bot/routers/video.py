"""Мастер видео: модель → промпт → параметры → очередь → ролик сообщением.

Ролик генерируется на сервере в очереди, а не в открытом соединении: бот
может перезапуститься посреди генерации — результат всё равно придёт
сообщением от ядра. Здесь мы только показываем прогресс и подстраховываем
доставку, если ядро по какой-то причине не отписалось.
"""
from __future__ import annotations

import asyncio
import logging

from aiogram import Bot, F, Router
from aiogram.enums import ChatAction
from aiogram.filters import Command, CommandObject
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from bot.config import settings
from bot.keyboards.common import paywall, rows_of
from bot.routers.chat import show_paywall, site_url
from bot.routers.models import _fetch
from bot.services.api import ApiError, api
from bot.services.state import store
from bot.texts import register_texts, t

logger = logging.getLogger(__name__)
router = Router(name="video")

POLL_INTERVAL = 5
POLL_MAX_SECONDS = 15 * 60
# Ядро само шлёт готовый ролик; ждём его отметку столько, прежде чем слать сами.
NOTIFY_GRACE = 20

register_texts({
    "ru": {
        "vid_pick_model": "🎬 <b>Видео</b>\nВыберите модель:",
        "vid_ask_prompt": ("🎬 Модель: <b>{model}</b> · {price}\n"
                           "Опишите, что должно происходить в ролике. Можно прислать фото с подписью — "
                           "оно станет первым кадром."),
        "vid_card": ("🎬 <b>{prompt}</b>\n\nМодель: <b>{model}</b>\n"
                     "Длительность: <b>{duration} с</b> · Пропорции: <b>{ar}</b>{res}\n"
                     "{first}Стоимость: <b>{cost} кр</b> · баланс {balance}"),
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
        "vid_uploading": "⬆️ Загружаю кадр…",
    },
    "en": {
        "vid_pick_model": "🎬 <b>Video</b>\nPick a model:",
        "vid_ask_prompt": ("🎬 Model: <b>{model}</b> · {price}\n"
                           "Describe what should happen in the clip. You can send a photo with a caption — "
                           "it becomes the first frame."),
        "vid_card": ("🎬 <b>{prompt}</b>\n\nModel: <b>{model}</b>\n"
                     "Duration: <b>{duration} s</b> · Aspect: <b>{ar}</b>{res}\n"
                     "{first}Cost: <b>{cost} cr</b> · balance {balance}"),
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
        "vid_uploading": "⬆️ Uploading the frame…",
    },
    "kg": {
        "vid_pick_model": "🎬 <b>Видео</b>\nМоделди тандаңыз:",
        "vid_ask_prompt": ("🎬 Модель: <b>{model}</b> · {price}\n"
                           "Роликте эмне болушу керектигин сүрөттөңүз. Сүрөт жөнөтсөңүз — ал биринчи кадр болот."),
        "vid_card": ("🎬 <b>{prompt}</b>\n\nМодель: <b>{model}</b>\n"
                     "Узактыгы: <b>{duration} с</b> · Пропорция: <b>{ar}</b>{res}\n"
                     "{first}Баасы: <b>{cost} кр</b> · баланс {balance}"),
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
        "vid_uploading": "⬆️ Кадрды жүктөп жатам…",
    },
})


class VideoWizard(StatesGroup):
    prompt = State()


async def _video_models(token: str, lang: str, telegram_id: int) -> list:
    models = await _fetch(token, lang, telegram_id)
    return [m for m in models if m.get("category") == "video" and m.get("openrouter_id")]


def _price_label(model: dict) -> str:
    try:
        return f"{int(float(model.get('markup_coefficient') or 0))} кр/с"
    except (TypeError, ValueError):
        return ""


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
    models = await _video_models(token, lang, chat_id)
    if not models:
        await message.answer(t(lang, "vid_no_models"))
        return
    buttons = []
    for index, m in enumerate(models[:12]):
        label = f"{'🔒 ' if m.get('locked') else ''}{m.get('name')} · {_price_label(m)}"
        short = (m.get("short_label") or "").strip()
        if short:
            label += f" · {short}"
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
    models = await _video_models(token, lang, chat_id)
    try:
        chosen = models[int(call.data.split(":")[2])]
    except (IndexError, ValueError):
        await call.answer()
        return
    if chosen.get("locked"):
        await call.answer()
        await show_paywall(call.message, lang, ApiError(403, code="premium_locked"))
        return
    draft = await _draft(chat_id)
    draft["model"] = chosen.get("openrouter_id")
    draft["model_name"] = chosen.get("name")
    draft["cps"] = float(chosen.get("markup_coefficient") or 0)
    await _save(chat_id, draft)
    await call.answer()
    if draft.get("prompt"):
        await _show_card(call.message, token, lang, chat_id, draft)
        return
    await state.set_state(VideoWizard.prompt)
    await call.message.answer(t(lang, "vid_ask_prompt", model=chosen.get("name"),
                                price=_price_label(chosen)), parse_mode="HTML")


@router.message(VideoWizard.prompt, F.text & ~F.text.startswith("/"))
async def got_prompt(message: Message, token: str, lang: str, state: FSMContext) -> None:
    from bot.keyboards.common import MENU_ACTIONS

    if message.text in MENU_ACTIONS:
        await state.clear()
        return
    await state.clear()
    chat_id = message.chat.id
    draft = await _draft(chat_id)
    draft["prompt"] = message.text.strip()
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
    draft = await _draft(chat_id)
    draft["first_frame"] = attachment
    caption = (message.caption or "").strip()
    if caption:
        draft["prompt"] = caption
        await state.clear()
        await _save(chat_id, draft)
        await _show_card(message, token, lang, chat_id, draft)
        return
    await _save(chat_id, draft)
    await message.answer(t(lang, "vid_ask_prompt", model=draft.get("model_name", ""),
                           price=""), parse_mode="HTML")


async def _params(token: str, lang: str, chat_id: int, model: str) -> dict:
    cached = await store.get(chat_id, f"vparams:{model}")
    if cached:
        return cached
    try:
        params = await api.video_params(token, model, lang=lang, telegram_id=chat_id)
    except ApiError:
        params = {}
    await store.set(chat_id, f"vparams:{model}", params, ttl=1800)
    return params


def _cost(draft: dict) -> int:
    import math

    return max(1, math.ceil(int(draft.get("duration") or 5) * float(draft.get("cps") or 0)))


async def _show_card(message: Message, token: str, lang: str, chat_id: int, draft: dict,
                     *, edit: bool = False) -> None:
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
    if params.get("credits_per_second"):
        draft["cps"] = float(params["credits_per_second"])
    await _save(chat_id, draft)

    try:
        balance = int((await api.balance(token, lang=lang, telegram_id=chat_id)).get("balance_tokens", 0))
    except ApiError:
        balance = 0
    cost = _cost(draft)
    first = ""
    if draft.get("extend"):
        first = t(lang, "vid_extend")
    elif draft.get("first_frame"):
        first = t(lang, "vid_first_frame")
    res = f" · {draft['res']}" if draft.get("res") and len(resolutions) > 1 else ""
    text = t(lang, "vid_card", prompt=draft.get("prompt", "")[:300], model=draft.get("model_name", ""),
             duration=draft["duration"], ar=draft["ar"], res=res, first=first, cost=cost,
             balance=balance)

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
    if balance < cost:
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
    await launch(call.message, token, lang, draft)


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
        if exc.is_paywall:
            await show_paywall(message, lang, exc)
        elif exc.code == "job_in_progress":
            await message.answer(t(lang, "vid_busy"))
        elif exc.status >= 500:
            await message.answer(t(lang, "server_down"))
        else:
            await message.answer(t(lang, "failed"))
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
    asyncio.create_task(_watch(message.bot, chat_id, progress.message_id, uid, token, lang))


def _status_label(lang: str, status: str) -> str:
    key = {"pending": "vid_status_pending", "queued": "vid_status_pending",
           "starting": "vid_status_pending", "downloading": "vid_status_downloading",
           "joining": "vid_status_joining"}.get(status, "vid_status_processing")
    return t(lang, key)


async def _watch(bot: Bot, chat_id: int, message_id: int, uid: str, token: str, lang: str) -> None:
    """Следить за задачей и обновлять сообщение-прогресс."""
    started = asyncio.get_event_loop().time()
    last_text = ""
    job: dict = {}
    while asyncio.get_event_loop().time() - started < POLL_MAX_SECONDS:
        await asyncio.sleep(POLL_INTERVAL)
        try:
            job = await api.job(token, uid, lang=lang, telegram_id=chat_id)
        except ApiError as exc:
            if exc.status == 401:
                token = await store.get_token(chat_id) or token
            continue
        status = job.get("status")
        if status in ("done", "failed", "canceled"):
            break
        elapsed = int(asyncio.get_event_loop().time() - started)
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

    try:
        await bot.delete_message(chat_id, message_id)
    except Exception:
        pass
    status = job.get("status")
    if status == "canceled":
        await bot.send_message(chat_id, t(lang, "vid_canceled"))
        return
    # Ядро шлёт результат само и ставит отметку; если её нет — доставляем сами.
    if not job.get("notified"):
        await asyncio.sleep(NOTIFY_GRACE)
        try:
            job = await api.job(token, uid, lang=lang, telegram_id=chat_id)
        except ApiError:
            pass
    if job.get("notified"):
        return
    await deliver(bot, chat_id, job, lang)


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
    error = job.get("error_code") or ""
    if error in ("insufficient_balance", "insufficient_tokens"):
        await bot.send_message(chat_id, t(lang, "paywall_balance",
                                          have=(job.get("result") or {}).get("balance_tokens", 0),
                                          need=(job.get("result") or {}).get("required_estimate", "—")),
                               parse_mode="HTML", reply_markup=paywall(lang, settings.site_base_url))
        return
    await bot.send_message(chat_id, t(lang, "vid_failed"), reply_markup=InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text=t(lang, "btn_retry"),
                                               callback_data=f"v:re:{uid}")]]))


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
    # Бот перезапускался или это ролик с сайта: восстанавливаем из задачи.
    try:
        job = await api.job(token, uid, lang=lang, telegram_id=chat_id)
    except ApiError:
        return None
    result = job.get("result") or {}
    message = result.get("message") or {}
    video = next((a for a in (message.get("attachments") or []) if a.get("type") == "video"), None)
    return {"prompt": (video or {}).get("prompt") or "", "model": (video or {}).get("model") or "",
            "job": uid, "url": (video or {}).get("url") or "", "duration": None}


@router.callback_query(F.data.startswith("v:re:"))
async def again(call: CallbackQuery, token: str, lang: str) -> None:
    chat_id = call.message.chat.id
    draft = await _job_draft(chat_id, token, lang, call.data.split(":", 2)[2])
    await call.answer()
    if not draft or not draft.get("prompt") or not draft.get("model"):
        await call.message.answer(t(lang, "vid_no_job"))
        return
    if not draft.get("cps"):
        models = await _video_models(token, lang, chat_id)
        chosen = next((m for m in models if m.get("openrouter_id") == draft["model"]), None)
        if chosen:
            draft["cps"] = float(chosen.get("markup_coefficient") or 0)
            draft["model_name"] = chosen.get("name")
    await launch(call.message, token, lang, {**draft, "extend": ""})


@router.callback_query(F.data.startswith("v:ext:"))
async def extend(call: CallbackQuery, token: str, lang: str, state: FSMContext) -> None:
    chat_id = call.message.chat.id
    uid = call.data.split(":", 2)[2]
    draft = await _job_draft(chat_id, token, lang, uid)
    await call.answer()
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
    new = {"prompt": draft.get("prompt", ""), "model": draft.get("model"),
           "model_name": draft.get("model_name", ""), "cps": draft.get("cps"),
           "extend": url, "first_frame": None, "duration": draft.get("duration"),
           "ar": draft.get("ar")}
    await _save(chat_id, new)
    if new["model"] and new.get("cps"):
        await _show_card(call.message, token, lang, chat_id, new)
    else:
        await _pick_model(call.message, token, lang, chat_id)


@router.callback_query(F.data.startswith("v:sh:"))
async def share(call: CallbackQuery, token: str, lang: str) -> None:
    chat_id = call.message.chat.id
    uid = call.data.split(":", 2)[2]
    draft = await _job_draft(chat_id, token, lang, uid) or {}
    url = draft.get("url")
    if not url:
        try:
            job = await api.job(token, uid, lang=lang, telegram_id=chat_id)
            atts = ((job.get("result") or {}).get("message") or {}).get("attachments") or []
            url = next((a.get("url") for a in atts if a.get("type") == "video"), "")
        except ApiError:
            url = ""
    await call.answer()
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
