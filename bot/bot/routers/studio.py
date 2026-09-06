"""Студия мультфильмов: герой → сцены → лента → съёмка → сборка.

Тот же конвейер, что на сайте, теми же словами. Экран с кнопками всегда
последнее сообщение, превью уходят медиа-группой перед ним. Готовность сцен
и мультфильма приходит пушем от ядра — опрашивать ничего не нужно.
"""
from __future__ import annotations

import logging

from aiogram import F, Router
from aiogram.enums import ChatAction
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    InputMediaPhoto,
    Message,
)

from bot.config import settings
from bot.keyboards.common import rows_of, webapp_button
from bot.routers.chat import show_paywall, site_url
from bot.services.api import ApiError, api
from bot.services.state import store
from bot.texts import register_texts, t

logger = logging.getLogger(__name__)
router = Router(name="studio")

PAGE = 8

register_texts({
    "ru": {
        "st_intro": ("🎞 <b>EsAI Cartoon Studio</b>\n"
                     "Выберите героя, наберите сцены — и студия соберёт готовый ролик. "
                     "Промпты писать не нужно.\n\n"
                     "Герой из библиотеки — бесплатно · свой герой — {character} кр · "
                     "сцена — от {scene_min} кр · склейка — бесплатно"),
        "st_continue": "▶ Продолжить «{title}» · сцен: {scenes}",
        "st_new": "▶ Начать новый мультфильм",
        "st_my": "🎬 Мои мультфильмы ({n})",
        "st_webapp": "📱 Открыть полную студию",
        "st_audience": "Для кого мультфильм?",
        "st_aud_all": "👨‍👩‍👧 Для всех", "st_aud_kids": "🧒 Для детей", "st_aud_adults": "🧑 Для взрослых",
        "st_heroes": "🦸 <b>Выберите героя</b> (стр. {page}/{pages})\n{lines}",
        "st_hero_upload": "📷 Загрузить своё фото",
        "st_hero_draw": "✏️ Нарисовать героя ({price} кр)",
        "st_hero_upload_ask": "📷 Пришлите фото героя. Подпись станет его именем.",
        "st_hero_draw_ask": "✏️ Опишите героя: кто он, как выглядит, в каком стиле. Спишется {price} кр.",
        "st_hero_drawing": "✏️ Рисую героя…",
        "st_hero_take": "✅ Взять этого", "st_hero_redraw": "🔁 Ещё раз ({price} кр)",
        "st_hero_saved": "Герой «{name}» добавлен в вашу библиотеку.",
        "st_project_started": "🎬 Мультфильм создан. Герой: <b>{hero}</b>. Теперь выберите сцены.",
        "st_cats": "🗂 <b>Разделы сцен</b>", "st_cat_popular": "🔥 Популярное", "st_cat_picks": "⭐ Выбор EsAI",
        "st_cat_all": "🗂 Все", "st_to_timeline": "🎞 К ленте ({n})",
        "st_scenes": "🎬 <b>{category}</b> (стр. {page}/{pages})\n{lines}",
        "st_scene_line": "{n} — {title} · {credits} кр · {duration} с{ready}",
        "st_scene_card": "🎬 <b>{title}</b>\n{subtitle}\n{credits} кр · {duration} с",
        "st_add": "➕ В ленту", "st_try": "🪄 Примерить героя", "st_kf": "👁 Кадр с вашим героем",
        "st_added": "Сцена «{title}» в ленте. Снять её можно из ленты.",
        "st_try_free": "Кадр уже был — бесплатно.", "st_try_paid": "Списано {credits} кр.",
        "st_timeline": ("🎞 <b>{title}</b> · герой: {hero}\n{lines}\n\n"
                        "Готово {ready} из {total} · потрачено {spent} кр"),
        "st_tl_line": "{n}. {icon} {title} — {status} · {credits} кр",
        "st_status_draft": "в ленте, не снята", "st_status_new": "в очереди",
        "st_status_keyframe": "рисую кадр", "st_status_video": "оживляю",
        "st_status_ready": "готова", "st_status_failed": "не получилась",
        "st_render_all": "🎬 Снять все не снятые ({credits} кр)", "st_add_scene": "➕ Добавить сцену",
        "st_assemble": "🎞 Собрать мультфильм", "st_refresh": "🔄 Обновить", "st_delete": "🗑 Удалить проект",
        "st_scene_menu": "⚙️ {n}", "st_render": "🎬 Снять сцену ({credits} кр)",
        "st_up": "🔼 Раньше", "st_down": "🔽 Позже", "st_retry": "🔁 Переснять",
        "st_retry_same": "🔁 С тем же кадром", "st_retry_new": "🆕 Новый кадр",
        "st_download": "📥 Скачать сцену", "st_remove": "🗑 Убрать",
        "st_rendering": "🎬 Снимаю «{title}»… Пришлю сюда, как будет готово. Кредиты спишутся за готовое видео.",
        "st_render_all_done": "Поставил в очередь сцен: {n}.",
        "st_paywall_studio": ("Сцена стоит {need} кр, на балансе {have}. Мультфильм и уже снятые сцены "
                              "никуда не денутся — пополните и продолжайте."),
        "st_assembling": "🎞 Собираю мультфильм… В конце добавим заставку EsAI. Пришлю, как будет готов.",
        "st_no_ready": "Пока нет готовых сцен — сначала снимите хотя бы одну.",
        "st_assemble_partial": "Не все сцены сняты. Собрать только готовые?",
        "st_yes": "✅ Да", "st_no": "✖ Нет",
        "st_delete_confirm": "Удалить проект «{title}»? Снятые сцены пропадут.",
        "st_deleted": "Проект удалён.",
        "st_my_title": "🎬 <b>Мои мультфильмы</b>", "st_my_empty": "Мультфильмов пока нет.",
        "st_my_line": "{icon} {title} · сцен {n}",
        "st_no_project": "Сначала начните мультфильм: /studio",
        "st_empty_heroes": "Библиотека героев пуста — загрузите своё фото.",
        "st_empty_scenes": "В этом разделе пока нет сцен.",
        "st_back": "↩ Разделы",
        "st_result": "🎞 Мультфильм «{title}» · сцен {n}",
        "st_removed": "Сцена убрана из ленты.",
    },
    "en": {
        "st_intro": ("🎞 <b>EsAI Cartoon Studio</b>\n"
                     "Pick a hero, collect scenes — and the studio assembles the film. "
                     "No prompts needed.\n\n"
                     "Library hero — free · your own hero — {character} cr · "
                     "scene — from {scene_min} cr · assembly — free"),
        "st_continue": "▶ Continue “{title}” · scenes: {scenes}",
        "st_new": "▶ Start a new cartoon",
        "st_my": "🎬 My cartoons ({n})",
        "st_webapp": "📱 Open the full studio",
        "st_audience": "Who is the cartoon for?",
        "st_aud_all": "👨‍👩‍👧 Everyone", "st_aud_kids": "🧒 Kids", "st_aud_adults": "🧑 Adults",
        "st_heroes": "🦸 <b>Pick a hero</b> (page {page}/{pages})\n{lines}",
        "st_hero_upload": "📷 Upload my photo",
        "st_hero_draw": "✏️ Draw a hero ({price} cr)",
        "st_hero_upload_ask": "📷 Send the hero's photo. The caption becomes its name.",
        "st_hero_draw_ask": "✏️ Describe the hero: who they are, how they look, the style. {price} cr will be charged.",
        "st_hero_drawing": "✏️ Drawing the hero…",
        "st_hero_take": "✅ Take this one", "st_hero_redraw": "🔁 Again ({price} cr)",
        "st_hero_saved": "Hero “{name}” added to your library.",
        "st_project_started": "🎬 Cartoon created. Hero: <b>{hero}</b>. Now pick the scenes.",
        "st_cats": "🗂 <b>Scene sections</b>", "st_cat_popular": "🔥 Popular", "st_cat_picks": "⭐ EsAI picks",
        "st_cat_all": "🗂 All", "st_to_timeline": "🎞 Timeline ({n})",
        "st_scenes": "🎬 <b>{category}</b> (page {page}/{pages})\n{lines}",
        "st_scene_line": "{n} — {title} · {credits} cr · {duration} s{ready}",
        "st_scene_card": "🎬 <b>{title}</b>\n{subtitle}\n{credits} cr · {duration} s",
        "st_add": "➕ Add to timeline", "st_try": "🪄 Try the hero", "st_kf": "👁 Frame with your hero",
        "st_added": "Scene “{title}” is in the timeline. Render it from there.",
        "st_try_free": "The frame already existed — free.", "st_try_paid": "{credits} cr charged.",
        "st_timeline": ("🎞 <b>{title}</b> · hero: {hero}\n{lines}\n\n"
                        "Ready {ready} of {total} · spent {spent} cr"),
        "st_tl_line": "{n}. {icon} {title} — {status} · {credits} cr",
        "st_status_draft": "in timeline, not rendered", "st_status_new": "queued",
        "st_status_keyframe": "drawing the frame", "st_status_video": "animating",
        "st_status_ready": "ready", "st_status_failed": "failed",
        "st_render_all": "🎬 Render all pending ({credits} cr)", "st_add_scene": "➕ Add a scene",
        "st_assemble": "🎞 Assemble the cartoon", "st_refresh": "🔄 Refresh", "st_delete": "🗑 Delete project",
        "st_scene_menu": "⚙️ {n}", "st_render": "🎬 Render scene ({credits} cr)",
        "st_up": "🔼 Earlier", "st_down": "🔽 Later", "st_retry": "🔁 Re-render",
        "st_retry_same": "🔁 Same frame", "st_retry_new": "🆕 New frame",
        "st_download": "📥 Download scene", "st_remove": "🗑 Remove",
        "st_rendering": "🎬 Rendering “{title}”… I will send it here when ready. Credits are charged for the finished video.",
        "st_render_all_done": "Queued scenes: {n}.",
        "st_paywall_studio": ("The scene costs {need} cr, you have {have}. The cartoon and rendered scenes "
                              "stay — top up and continue."),
        "st_assembling": "🎞 Assembling… An EsAI outro is added at the end. I will send it when ready.",
        "st_no_ready": "No rendered scenes yet — render at least one first.",
        "st_assemble_partial": "Not all scenes are rendered. Assemble only the ready ones?",
        "st_yes": "✅ Yes", "st_no": "✖ No",
        "st_delete_confirm": "Delete project “{title}”? Rendered scenes will be lost.",
        "st_deleted": "Project deleted.",
        "st_my_title": "🎬 <b>My cartoons</b>", "st_my_empty": "No cartoons yet.",
        "st_my_line": "{icon} {title} · scenes {n}",
        "st_no_project": "Start a cartoon first: /studio",
        "st_empty_heroes": "The hero library is empty — upload your photo.",
        "st_empty_scenes": "No scenes in this section yet.",
        "st_back": "↩ Sections",
        "st_result": "🎞 Cartoon “{title}” · scenes {n}",
        "st_removed": "Scene removed from the timeline.",
    },
    "kg": {
        "st_intro": ("🎞 <b>EsAI Cartoon Studio</b>\n"
                     "Каарманды тандаңыз, сценаларды чогултуңуз — студия даяр роликти чогултат. "
                     "Промпт жазуунун кереги жок.\n\n"
                     "Китепканадагы каарман — бекер · өз каарманыңыз — {character} кр · "
                     "сцена — {scene_min} кр баштап · бириктирүү — бекер"),
        "st_continue": "▶ «{title}» улантуу · сцена: {scenes}",
        "st_new": "▶ Жаңы мультфильм баштоо",
        "st_my": "🎬 Менин мультфильмдерим ({n})",
        "st_webapp": "📱 Толук студияны ачуу",
        "st_audience": "Мультфильм кимге?",
        "st_aud_all": "👨‍👩‍👧 Баарына", "st_aud_kids": "🧒 Балдарга", "st_aud_adults": "🧑 Чоңдорго",
        "st_heroes": "🦸 <b>Каарманды тандаңыз</b> ({page}/{pages}-бет)\n{lines}",
        "st_hero_upload": "📷 Өз сүрөтүмдү жүктөө",
        "st_hero_draw": "✏️ Каарман тартуу ({price} кр)",
        "st_hero_upload_ask": "📷 Каармандын сүрөтүн жөнөтүңүз. Подпись анын аты болот.",
        "st_hero_draw_ask": "✏️ Каарманды сүрөттөңүз: ким, кандай көрүнөт, стили. {price} кр алынат.",
        "st_hero_drawing": "✏️ Каарманды тартып жатам…",
        "st_hero_take": "✅ Ушуну алуу", "st_hero_redraw": "🔁 Дагы ({price} кр)",
        "st_hero_saved": "«{name}» каарманы китепканаңызга кошулду.",
        "st_project_started": "🎬 Мультфильм түзүлдү. Каарман: <b>{hero}</b>. Эми сценаларды тандаңыз.",
        "st_cats": "🗂 <b>Сцена бөлүмдөрү</b>", "st_cat_popular": "🔥 Популярдуу", "st_cat_picks": "⭐ EsAI тандоосу",
        "st_cat_all": "🗂 Баары", "st_to_timeline": "🎞 Лентага ({n})",
        "st_scenes": "🎬 <b>{category}</b> ({page}/{pages}-бет)\n{lines}",
        "st_scene_line": "{n} — {title} · {credits} кр · {duration} с{ready}",
        "st_scene_card": "🎬 <b>{title}</b>\n{subtitle}\n{credits} кр · {duration} с",
        "st_add": "➕ Лентага", "st_try": "🪄 Каарманды текшерүү", "st_kf": "👁 Каарманыңыз менен кадр",
        "st_added": "«{title}» сценасы лентада. Аны лентадан тартсаңыз болот.",
        "st_try_free": "Кадр мурда эле бар — бекер.", "st_try_paid": "{credits} кр алынды.",
        "st_timeline": ("🎞 <b>{title}</b> · каарман: {hero}\n{lines}\n\n"
                        "Даяр {ready}/{total} · сарпталды {spent} кр"),
        "st_tl_line": "{n}. {icon} {title} — {status} · {credits} кр",
        "st_status_draft": "лентада, тартыла элек", "st_status_new": "кезекте",
        "st_status_keyframe": "кадр тартылууда", "st_status_video": "жандандырылууда",
        "st_status_ready": "даяр", "st_status_failed": "чыккан жок",
        "st_render_all": "🎬 Баарын тартуу ({credits} кр)", "st_add_scene": "➕ Сцена кошуу",
        "st_assemble": "🎞 Мультфильмди чогултуу", "st_refresh": "🔄 Жаңыртуу", "st_delete": "🗑 Долбоорду өчүрүү",
        "st_scene_menu": "⚙️ {n}", "st_render": "🎬 Сценаны тартуу ({credits} кр)",
        "st_up": "🔼 Мурда", "st_down": "🔽 Кийин", "st_retry": "🔁 Кайра тартуу",
        "st_retry_same": "🔁 Ошол эле кадр", "st_retry_new": "🆕 Жаңы кадр",
        "st_download": "📥 Сценаны жүктөө", "st_remove": "🗑 Алып салуу",
        "st_rendering": "🎬 «{title}» тартып жатам… Даяр болгондо ушул жерге жөнөтөм.",
        "st_render_all_done": "Кезекке коюлган сценалар: {n}.",
        "st_paywall_studio": ("Сцена {need} кр турат, балансыңызда {have}. Мультфильм жана тартылган сценалар "
                              "сакталат — толуктап, улантыңыз."),
        "st_assembling": "🎞 Мультфильмди чогултуп жатам… Даяр болгондо жөнөтөм.",
        "st_no_ready": "Даяр сценалар жок — адегенде бирөөнү тартыңыз.",
        "st_assemble_partial": "Бардык сценалар тартылган жок. Даярларын гана чогултайлыбы?",
        "st_yes": "✅ Ооба", "st_no": "✖ Жок",
        "st_delete_confirm": "«{title}» долбоорун өчүрөбүзбү? Тартылган сценалар жоголот.",
        "st_deleted": "Долбоор өчүрүлдү.",
        "st_my_title": "🎬 <b>Менин мультфильмдерим</b>", "st_my_empty": "Азырынча мультфильм жок.",
        "st_my_line": "{icon} {title} · сцена {n}",
        "st_no_project": "Адегенде мультфильм баштаңыз: /studio",
        "st_empty_heroes": "Каармандар китепканасы бош — өз сүрөтүңүздү жүктөңүз.",
        "st_empty_scenes": "Бул бөлүмдө азырынча сцена жок.",
        "st_back": "↩ Бөлүмдөр",
        "st_result": "🎞 «{title}» мультфильми · сцена {n}",
        "st_removed": "Сцена лентадан алынды.",
    },
})

STATUS_ICON = {"draft": "▫️", "new": "⏳", "keyframe": "🖌", "video": "⏳", "ready": "✅", "failed": "❌"}


class StudioWizard(StatesGroup):
    hero_photo = State()
    hero_prompt = State()


def _tid(obj) -> int:
    return obj.message.chat.id if isinstance(obj, CallbackQuery) else obj.chat.id


async def _pricing(token: str, lang: str, chat_id: int) -> dict:
    cached = await store.get(chat_id, "st_pricing")
    if cached:
        return cached
    try:
        pricing = await api.pricing(token, lang=lang, telegram_id=chat_id)
    except ApiError:
        pricing = {}
    await store.set(chat_id, "st_pricing", pricing, ttl=1800)
    return pricing


async def _presets(token: str, lang: str, chat_id: int) -> dict:
    cached = await store.get(chat_id, "st_presets")
    if cached:
        return cached
    data = await api.presets(token, lang=lang, telegram_id=chat_id)
    await store.set(chat_id, "st_presets", data, ttl=900)
    return data


async def _project_id(chat_id: int) -> int | None:
    value = await store.get(chat_id, "st_project")
    return int(value) if value else None


def _webapp_url(project_id: int | None = None) -> str:
    base = f"{settings.site_base_url}/tg/studio"
    return f"{base}?project={project_id}" if project_id else base


async def _send_media_group(message: Message, urls: list[str]) -> None:
    media = [InputMediaPhoto(media=site_url(u)) for u in urls if u][:10]
    if not media:
        return
    try:
        await message.answer_media_group(media)
    except Exception:
        logger.exception("медиа-группа не отправилась")


# ------------------------------------------------------------- вход ---

@router.message(Command("studio"))
async def cmd_studio(message: Message, token: str, lang: str = "ru") -> None:
    await show_intro(message, token, lang)


async def show_intro(message: Message, token: str, lang: str) -> None:
    chat_id = message.chat.id
    pricing = await _pricing(token, lang, chat_id)
    try:
        projects = await api.projects(token, lang=lang, telegram_id=chat_id)
    except ApiError:
        projects = []
    rows = []
    current = await _project_id(chat_id)
    draft = next((p for p in projects if p.get("id") == current), None) if current else None
    if draft is None:
        draft = next((p for p in projects if p.get("status") == "draft"), None)
    if draft:
        await store.set(chat_id, "st_project", draft["id"])
        rows.append([InlineKeyboardButton(
            text=t(lang, "st_continue", title=draft.get("title", "")[:30],
                   scenes=len(draft.get("scenes") or [])), callback_data="st:tl")])
    rows.append([InlineKeyboardButton(text=t(lang, "st_new"), callback_data="st:new")])
    rows.append([InlineKeyboardButton(text=t(lang, "st_my", n=len(projects)), callback_data="st:my")])
    rows.append([webapp_button(t(lang, "st_webapp"), _webapp_url(draft["id"] if draft else None))])
    await message.answer(
        t(lang, "st_intro", character=pricing.get("character", 4),
          scene_min=pricing.get("scene_min", 22)),
        parse_mode="HTML", reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))


@router.callback_query(F.data == "st:new")
async def new_project(call: CallbackQuery, lang: str) -> None:
    await call.answer()
    rows = [[InlineKeyboardButton(text=t(lang, "st_aud_all"), callback_data="st:aud:all")],
            [InlineKeyboardButton(text=t(lang, "st_aud_kids"), callback_data="st:aud:kids"),
             InlineKeyboardButton(text=t(lang, "st_aud_adults"), callback_data="st:aud:adults")]]
    await call.message.answer(t(lang, "st_audience"),
                              reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))


# ------------------------------------------------------------- герой ---

@router.callback_query(F.data.startswith("st:aud:"))
async def pick_audience(call: CallbackQuery, token: str, lang: str) -> None:
    chat_id = _tid(call)
    audience = call.data.split(":")[2]
    await store.set(chat_id, "st_audience", audience, ttl=6 * 3600)
    await call.answer()
    await show_heroes(call.message, token, lang, 0)


async def _heroes(token: str, lang: str, chat_id: int) -> list:
    audience = await store.get(chat_id, "st_audience") or "all"
    heroes = await api.characters(token, lang=lang, telegram_id=chat_id)
    if audience != "all":
        filtered = [h for h in heroes if (h.get("audience") or "all") in (audience, "all")]
        heroes = filtered or heroes
    # Свои герои первыми — так же, как на сайте.
    heroes.sort(key=lambda h: (not h.get("is_mine"), 0))
    return heroes


async def show_heroes(message: Message, token: str, lang: str, page: int) -> None:
    chat_id = message.chat.id
    try:
        heroes = await _heroes(token, lang, chat_id)
    except ApiError:
        await message.answer(t(lang, "server_down"))
        return
    pricing = await _pricing(token, lang, chat_id)
    pages = max(1, (len(heroes) + PAGE - 1) // PAGE)
    page = max(0, min(page, pages - 1))
    chunk = heroes[page * PAGE:(page + 1) * PAGE]
    await store.set(chat_id, "st_heroes", [{"id": h["id"], "name": h.get("name")} for h in heroes],
                    ttl=3600)
    if chunk:
        await message.bot.send_chat_action(chat_id, ChatAction.UPLOAD_PHOTO)
        await _send_media_group(message, [h.get("image") for h in chunk])
    lines = "\n".join(f"{i} — {h.get('name')}{' 👤' if h.get('is_mine') else ''}"
                      for i, h in enumerate(chunk, 1)) or t(lang, "st_empty_heroes")
    buttons = [InlineKeyboardButton(text=str(i), callback_data=f"st:h:{h['id']}")
               for i, h in enumerate(chunk, 1)]
    rows = rows_of(buttons, 4)
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton(text="◀", callback_data=f"st:hp:{page - 1}"))
    if page < pages - 1:
        nav.append(InlineKeyboardButton(text="▶", callback_data=f"st:hp:{page + 1}"))
    if nav:
        rows.append(nav)
    rows.append([InlineKeyboardButton(text=t(lang, "st_hero_upload"), callback_data="st:hu")])
    rows.append([InlineKeyboardButton(text=t(lang, "st_hero_draw", price=pricing.get("character", 4)),
                                      callback_data="st:hd")])
    await message.answer(t(lang, "st_heroes", page=page + 1, pages=pages, lines=lines),
                         parse_mode="HTML", reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))


@router.callback_query(F.data.startswith("st:hp:"))
async def heroes_page(call: CallbackQuery, token: str, lang: str) -> None:
    await call.answer()
    await show_heroes(call.message, token, lang, int(call.data.split(":")[2]))


@router.callback_query(F.data.startswith("st:h:"))
async def pick_hero(call: CallbackQuery, token: str, lang: str) -> None:
    chat_id = _tid(call)
    hero_id = int(call.data.split(":")[2])
    try:
        project = await api.create_project(token, hero_id, lang=lang, telegram_id=chat_id)
    except ApiError as exc:
        await call.answer()
        await call.message.answer(exc.message or t(lang, "failed"))
        return
    await store.set(chat_id, "st_project", project["id"])
    await store.set(chat_id, "st_char", hero_id)
    await store.drop(chat_id, "st_keyframes")
    await call.answer()
    hero = (project.get("character") or {}).get("name", "")
    await call.message.answer(t(lang, "st_project_started", hero=hero), parse_mode="HTML")
    await show_categories(call.message, token, lang)


@router.callback_query(F.data == "st:hu")
async def hero_upload(call: CallbackQuery, lang: str, state: FSMContext) -> None:
    await state.set_state(StudioWizard.hero_photo)
    await call.answer()
    await call.message.answer(t(lang, "st_hero_upload_ask"))


@router.message(StudioWizard.hero_photo, F.photo)
async def hero_photo(message: Message, token: str, lang: str, state: FSMContext) -> None:
    from bot.routers.media import download

    await state.clear()
    chat_id = message.chat.id
    photo = message.photo[-1]
    content = await download(message, photo.file_id, photo.file_size or 0, lang)
    if content is None:
        return
    name = (message.caption or "").strip()[:60] or {"en": "My hero", "kg": "Менин каарманым"}.get(lang, "Мой герой")
    try:
        hero = await api.character_upload(token, name, content, lang=lang, telegram_id=chat_id)
    except ApiError:
        await message.answer(t(lang, "server_down"))
        return
    await message.answer(t(lang, "st_hero_saved", name=hero.get("name", name)))
    await _use_hero(message, token, lang, hero["id"])


async def _use_hero(message: Message, token: str, lang: str, hero_id: int) -> None:
    chat_id = message.chat.id
    try:
        project = await api.create_project(token, hero_id, lang=lang, telegram_id=chat_id)
    except ApiError as exc:
        await message.answer(exc.message or t(lang, "failed"))
        return
    await store.set(chat_id, "st_project", project["id"])
    await store.set(chat_id, "st_char", hero_id)
    await store.drop(chat_id, "st_keyframes")
    await message.answer(t(lang, "st_project_started",
                           hero=(project.get("character") or {}).get("name", "")), parse_mode="HTML")
    await show_categories(message, token, lang)


@router.callback_query(F.data == "st:hd")
async def hero_draw(call: CallbackQuery, token: str, lang: str, state: FSMContext) -> None:
    pricing = await _pricing(token, lang, _tid(call))
    await state.set_state(StudioWizard.hero_prompt)
    await call.answer()
    await call.message.answer(t(lang, "st_hero_draw_ask", price=pricing.get("character", 4)))


@router.message(StudioWizard.hero_prompt, F.text & ~F.text.startswith("/"))
async def hero_prompt(message: Message, token: str, lang: str, state: FSMContext) -> None:
    from bot.keyboards.common import MENU_ACTIONS

    if message.text in MENU_ACTIONS:
        await state.clear()
        return
    await state.clear()
    chat_id = message.chat.id
    status = await message.answer(t(lang, "st_hero_drawing"))
    await message.bot.send_chat_action(chat_id, ChatAction.UPLOAD_PHOTO)
    try:
        hero = await api.character_generate(token, message.text.strip(), lang=lang, telegram_id=chat_id)
    except ApiError as exc:
        try:
            await status.delete()
        except Exception:
            pass
        if exc.status == 402:
            await show_paywall(message, lang, ApiError(402, code="insufficient_balance",
                                                       payload={"balance_tokens": exc.payload.get("balance"),
                                                                "required": exc.payload.get("required")}))
        else:
            await message.answer(exc.message or t(lang, "failed"))
        return
    try:
        await status.delete()
    except Exception:
        pass
    pricing = await _pricing(token, lang, chat_id)
    rows = [[InlineKeyboardButton(text=t(lang, "st_hero_take"), callback_data=f"st:h:{hero['id']}"),
             InlineKeyboardButton(text=t(lang, "st_hero_redraw", price=pricing.get("character", 4)),
                                  callback_data="st:hd")]]
    await message.answer_photo(site_url(hero.get("image", "")), caption=hero.get("name", ""),
                               reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))


# ------------------------------------------------------------- сцены ---

async def show_categories(message: Message, token: str, lang: str) -> None:
    chat_id = message.chat.id
    try:
        data = await _presets(token, lang, chat_id)
    except ApiError:
        await message.answer(t(lang, "server_down"))
        return
    cats = data.get("categories") or []
    buttons = [InlineKeyboardButton(text=f"{c.get('emoji', '')} {c.get('title')}".strip(),
                                    callback_data=f"st:cat:{c['slug']}:0") for c in cats]
    rows = []
    top = [InlineKeyboardButton(text=t(lang, "st_cat_all"), callback_data="st:cat:all:0")]
    if data.get("popular"):
        top.insert(0, InlineKeyboardButton(text=t(lang, "st_cat_popular"), callback_data="st:cat:popular:0"))
    if any(p.get("is_pick") for p in data.get("presets") or []):
        top.insert(-1, InlineKeyboardButton(text=t(lang, "st_cat_picks"), callback_data="st:cat:picks:0"))
    rows.append(top)
    rows += rows_of(buttons, 2)
    project_id = await _project_id(chat_id)
    n = 0
    if project_id:
        try:
            project = await api.project(token, project_id, lang=lang, telegram_id=chat_id)
            n = len(project.get("scenes") or [])
        except ApiError:
            pass
    rows.append([InlineKeyboardButton(text=t(lang, "st_to_timeline", n=n), callback_data="st:tl")])
    await message.answer(t(lang, "st_cats"), parse_mode="HTML",
                         reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))


@router.callback_query(F.data == "st:cats")
async def categories(call: CallbackQuery, token: str, lang: str) -> None:
    await call.answer()
    await show_categories(call.message, token, lang)


def _filter_presets(data: dict, slug: str) -> tuple[str, list]:
    presets = data.get("presets") or []
    if slug == "all":
        return "🗂", presets
    if slug == "popular":
        popular = data.get("popular") or []
        return "🔥", [p for p in presets if p.get("slug") in popular]
    if slug == "picks":
        return "⭐", [p for p in presets if p.get("is_pick")]
    cat = next((c for c in data.get("categories") or [] if c.get("slug") == slug), None)
    title = f"{cat.get('emoji', '')} {cat.get('title')}".strip() if cat else slug
    return title, [p for p in presets if p.get("category") == slug]


async def _ready_keyframes(token: str, lang: str, chat_id: int) -> dict:
    cached = await store.get(chat_id, "st_keyframes")
    if cached is not None:
        return cached
    char_id = await store.get(chat_id, "st_char")
    result = {}
    if char_id:
        try:
            result = await api.keyframes(token, int(char_id), lang=lang, telegram_id=chat_id)
        except ApiError:
            result = {}
    await store.set(chat_id, "st_keyframes", result, ttl=600)
    return result


@router.callback_query(F.data.startswith("st:cat:"))
async def scenes(call: CallbackQuery, token: str, lang: str) -> None:
    _, _, slug, page = call.data.split(":")
    await call.answer()
    await show_scenes(call.message, token, lang, slug, int(page))


async def show_scenes(message: Message, token: str, lang: str, slug: str, page: int) -> None:
    chat_id = message.chat.id
    try:
        data = await _presets(token, lang, chat_id)
    except ApiError:
        await message.answer(t(lang, "server_down"))
        return
    title, presets = _filter_presets(data, slug)
    if not presets:
        await message.answer(t(lang, "st_empty_scenes"))
        return
    ready = await _ready_keyframes(token, lang, chat_id)
    pages = max(1, (len(presets) + PAGE - 1) // PAGE)
    page = max(0, min(page, pages - 1))
    chunk = presets[page * PAGE:(page + 1) * PAGE]
    await message.bot.send_chat_action(chat_id, ChatAction.UPLOAD_PHOTO)
    await _send_media_group(message, [p.get("preview_poster") for p in chunk])
    lines = "\n".join(t(lang, "st_scene_line", n=i, title=p.get("title"), credits=p.get("credits"),
                        duration=p.get("duration"), ready=" ✅" if str(p.get("id")) in ready else "")
                      for i, p in enumerate(chunk, 1))
    buttons = [InlineKeyboardButton(text=str(i), callback_data=f"st:sc:{p['id']}")
               for i, p in enumerate(chunk, 1)]
    rows = rows_of(buttons, 4)
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton(text="◀", callback_data=f"st:cat:{slug}:{page - 1}"))
    if page < pages - 1:
        nav.append(InlineKeyboardButton(text="▶", callback_data=f"st:cat:{slug}:{page + 1}"))
    if nav:
        rows.append(nav)
    rows.append([InlineKeyboardButton(text=t(lang, "st_back"), callback_data="st:cats"),
                 InlineKeyboardButton(text=t(lang, "st_to_timeline", n="…"), callback_data="st:tl")])
    await message.answer(t(lang, "st_scenes", category=title, page=page + 1, pages=pages, lines=lines),
                         parse_mode="HTML", reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))


@router.callback_query(F.data.startswith("st:sc:"))
async def scene_card(call: CallbackQuery, token: str, lang: str) -> None:
    chat_id = _tid(call)
    preset_id = int(call.data.split(":")[2])
    await call.answer()
    data = await _presets(token, lang, chat_id)
    preset = next((p for p in data.get("presets") or [] if p.get("id") == preset_id), None)
    if not preset:
        return
    ready = await _ready_keyframes(token, lang, chat_id)
    rows = [[InlineKeyboardButton(text=t(lang, "st_add"), callback_data=f"st:add:{preset_id}")]]
    if str(preset_id) in ready:
        rows.append([InlineKeyboardButton(text=t(lang, "st_kf"), callback_data=f"st:try:{preset_id}")])
    else:
        rows.append([InlineKeyboardButton(text=t(lang, "st_try"), callback_data=f"st:try:{preset_id}")])
    rows.append([InlineKeyboardButton(text=t(lang, "st_back"), callback_data="st:cats")])
    caption = t(lang, "st_scene_card", title=preset.get("title"), subtitle=preset.get("subtitle") or "",
                credits=preset.get("credits"), duration=preset.get("duration"))
    markup = InlineKeyboardMarkup(inline_keyboard=rows)
    video = preset.get("preview_video")
    if video:
        try:
            await call.message.answer_video(site_url(video), caption=caption, parse_mode="HTML",
                                            reply_markup=markup)
            return
        except Exception:
            logger.exception("превью сцены не отправилось")
    await call.message.answer(caption, parse_mode="HTML", reply_markup=markup)


@router.callback_query(F.data.startswith("st:add:"))
async def add_scene(call: CallbackQuery, token: str, lang: str) -> None:
    chat_id = _tid(call)
    preset_id = int(call.data.split(":")[2])
    project_id = await _project_id(chat_id)
    if not project_id:
        await call.answer()
        await call.message.answer(t(lang, "st_no_project"))
        return
    try:
        scene = await api.add_scene(token, project_id, preset_id, lang=lang, telegram_id=chat_id)
    except ApiError as exc:
        await call.answer()
        await call.message.answer(exc.message or t(lang, "failed"))
        return
    await call.answer(t(lang, "st_added", title=(scene.get("preset") or {}).get("title", "")),
                      show_alert=False)
    await call.message.answer(
        t(lang, "st_added", title=(scene.get("preset") or {}).get("title", "")),
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text=t(lang, "st_to_timeline", n="…"), callback_data="st:tl"),
            InlineKeyboardButton(text=t(lang, "st_add_scene"), callback_data="st:cats")]]))


@router.callback_query(F.data.startswith("st:try:"))
async def try_on(call: CallbackQuery, token: str, lang: str) -> None:
    chat_id = _tid(call)
    preset_id = int(call.data.split(":")[2])
    char_id = await store.get(chat_id, "st_char")
    if not char_id:
        await call.answer()
        await call.message.answer(t(lang, "st_no_project"))
        return
    await call.answer()
    await call.message.bot.send_chat_action(chat_id, ChatAction.UPLOAD_PHOTO)
    try:
        result = await api.try_on(token, preset_id, int(char_id), lang=lang, telegram_id=chat_id)
    except ApiError as exc:
        if exc.status == 402:
            await show_paywall(call.message, lang, ApiError(402, code="insufficient_balance",
                                                            payload={"balance_tokens": exc.payload.get("balance"),
                                                                     "required": exc.payload.get("required")}))
        else:
            await call.message.answer(exc.message or t(lang, "failed"))
        return
    await store.drop(chat_id, "st_keyframes")
    charged = int(result.get("charged") or 0)
    caption = t(lang, "st_try_paid", credits=charged) if charged else t(lang, "st_try_free")
    await call.message.answer_photo(
        site_url(result.get("image", "")), caption=caption,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text=t(lang, "st_add"), callback_data=f"st:add:{preset_id}")]]))


# ------------------------------------------------------------- лента ---

def _status(lang: str, status: str) -> str:
    return t(lang, f"st_status_{status}") if status in STATUS_ICON else status


async def show_timeline(message: Message, token: str, lang: str) -> None:
    chat_id = message.chat.id
    project_id = await _project_id(chat_id)
    if not project_id:
        await message.answer(t(lang, "st_no_project"))
        return
    try:
        project = await api.project(token, project_id, lang=lang, telegram_id=chat_id)
    except ApiError as exc:
        if exc.status == 404:
            await store.drop(chat_id, "st_project")
            await message.answer(t(lang, "st_no_project"))
        else:
            await message.answer(t(lang, "server_down"))
        return
    scenes = project.get("scenes") or []
    lines = "\n".join(t(lang, "st_tl_line", n=i, icon=STATUS_ICON.get(s.get("status"), "▫️"),
                        title=(s.get("preset") or {}).get("title", ""),
                        status=_status(lang, s.get("status", "")),
                        credits=(s.get("preset") or {}).get("credits", 0))
                      for i, s in enumerate(scenes, 1)) or "—"
    ready = sum(1 for s in scenes if s.get("status") == "ready")
    pending = [s for s in scenes if s.get("status") in ("draft", "failed")]
    pending_cost = sum((s.get("preset") or {}).get("credits", 0) for s in pending)
    text = t(lang, "st_timeline", title=project.get("title", ""),
             hero=(project.get("character") or {}).get("name", ""), lines=lines,
             ready=ready, total=len(scenes), spent=project.get("credits_spent", 0))
    rows = []
    if pending:
        rows.append([InlineKeyboardButton(text=t(lang, "st_render_all", credits=pending_cost),
                                          callback_data="st:ra")])
    rows += rows_of([InlineKeyboardButton(text=t(lang, "st_scene_menu", n=i),
                                          callback_data=f"st:s:{s['id']}")
                     for i, s in enumerate(scenes, 1)], 4)
    rows.append([InlineKeyboardButton(text=t(lang, "st_add_scene"), callback_data="st:cats"),
                 InlineKeyboardButton(text=t(lang, "st_assemble"), callback_data="st:as")])
    rows.append([InlineKeyboardButton(text=t(lang, "st_refresh"), callback_data="st:tl"),
                 InlineKeyboardButton(text=t(lang, "st_delete"), callback_data="st:del")])
    rows.append([webapp_button(t(lang, "st_webapp"), _webapp_url(project_id))])
    await message.answer(text, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))
    if project.get("status") == "ready" and project.get("result_video"):
        try:
            await message.answer_video(site_url(project["result_video"]),
                                       caption=t(lang, "st_result", title=project.get("title", ""),
                                                 n=ready), supports_streaming=True)
        except Exception:
            await message.answer(site_url(project["result_video"]))


@router.callback_query(F.data == "st:tl")
async def timeline(call: CallbackQuery, token: str, lang: str) -> None:
    await call.answer()
    await show_timeline(call.message, token, lang)


async def _scene(token: str, lang: str, chat_id: int, scene_id: int) -> tuple[dict | None, dict | None]:
    project_id = await _project_id(chat_id)
    if not project_id:
        return None, None
    try:
        project = await api.project(token, project_id, lang=lang, telegram_id=chat_id)
    except ApiError:
        return None, None
    scene = next((s for s in project.get("scenes") or [] if s.get("id") == scene_id), None)
    return project, scene


@router.callback_query(F.data.startswith("st:s:"))
async def scene_menu(call: CallbackQuery, token: str, lang: str) -> None:
    chat_id = _tid(call)
    scene_id = int(call.data.split(":")[2])
    await call.answer()
    project, scene = await _scene(token, lang, chat_id, scene_id)
    if not scene:
        return
    preset = scene.get("preset") or {}
    status = scene.get("status")
    rows = []
    if status in ("draft", "failed"):
        rows.append([InlineKeyboardButton(text=t(lang, "st_render", credits=preset.get("credits", 0)),
                                          callback_data=f"st:r:{scene_id}")])
    if status in ("ready", "failed"):
        rows.append([InlineKeyboardButton(text=t(lang, "st_retry_same"), callback_data=f"st:rt:{scene_id}:0"),
                     InlineKeyboardButton(text=t(lang, "st_retry_new"), callback_data=f"st:rt:{scene_id}:1")])
    rows.append([InlineKeyboardButton(text=t(lang, "st_up"), callback_data=f"st:up:{scene_id}"),
                 InlineKeyboardButton(text=t(lang, "st_down"), callback_data=f"st:dn:{scene_id}")])
    extra = [InlineKeyboardButton(text=t(lang, "st_remove"), callback_data=f"st:rm:{scene_id}")]
    if scene.get("video"):
        extra.insert(0, InlineKeyboardButton(text=t(lang, "st_download"), callback_data=f"st:sdl:{scene_id}"))
    rows.append(extra)
    rows.append([InlineKeyboardButton(text=t(lang, "btn_back"), callback_data="st:tl")])
    caption = f"{STATUS_ICON.get(status, '▫️')} <b>{preset.get('title', '')}</b> — {_status(lang, status)}"
    if scene.get("error"):
        caption += f"\n{scene['error'][:200]}"
    markup = InlineKeyboardMarkup(inline_keyboard=rows)
    frame = scene.get("keyframe") or preset.get("poster")
    if frame:
        try:
            await call.message.answer_photo(site_url(frame), caption=caption, parse_mode="HTML",
                                            reply_markup=markup)
            return
        except Exception:
            pass
    await call.message.answer(caption, parse_mode="HTML", reply_markup=markup)


async def _render(call: CallbackQuery, token: str, lang: str, scene_id: int, *, quiet: bool = False) -> bool:
    chat_id = _tid(call)
    try:
        scene = await api.render_scene(token, scene_id, lang=lang, telegram_id=chat_id)
    except ApiError as exc:
        if exc.status == 402:
            await call.message.answer(
                t(lang, "st_paywall_studio", need=exc.payload.get("required", "?"),
                  have=exc.payload.get("balance", 0)),
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
                    InlineKeyboardButton(text=t(lang, "btn_topup"), callback_data="b:topup")]]))
        elif not quiet:
            await call.message.answer(exc.message or t(lang, "failed"))
        return False
    if not quiet:
        await call.message.answer(t(lang, "st_rendering", title=(scene.get("preset") or {}).get("title", "")))
    return True


@router.callback_query(F.data.startswith("st:r:"))
async def render(call: CallbackQuery, token: str, lang: str) -> None:
    await call.answer()
    await _render(call, token, lang, int(call.data.split(":")[2]))


@router.callback_query(F.data == "st:ra")
async def render_all(call: CallbackQuery, token: str, lang: str) -> None:
    chat_id = _tid(call)
    await call.answer()
    project_id = await _project_id(chat_id)
    if not project_id:
        return
    try:
        project = await api.project(token, project_id, lang=lang, telegram_id=chat_id)
    except ApiError:
        await call.message.answer(t(lang, "server_down"))
        return
    queued = 0
    for scene in project.get("scenes") or []:
        if scene.get("status") in ("draft", "failed"):
            if not await _render(call, token, lang, scene["id"], quiet=True):
                break
            queued += 1
    await call.message.answer(t(lang, "st_render_all_done", n=queued))


@router.callback_query(F.data.startswith("st:rt:"))
async def retry_scene(call: CallbackQuery, token: str, lang: str) -> None:
    chat_id = _tid(call)
    _, _, scene_id, new_frame = call.data.split(":")
    await call.answer()
    try:
        scene = await api.patch_scene(token, int(scene_id), {"retry": True, "new_keyframe": new_frame == "1"},
                                      lang=lang, telegram_id=chat_id)
    except ApiError as exc:
        await call.message.answer(exc.message or t(lang, "failed"))
        return
    await call.message.answer(t(lang, "st_rendering", title=(scene.get("preset") or {}).get("title", "")))


@router.callback_query(F.data.startswith("st:up:") | F.data.startswith("st:dn:"))
async def move_scene(call: CallbackQuery, token: str, lang: str) -> None:
    chat_id = _tid(call)
    direction, scene_id = call.data.split(":")[1], int(call.data.split(":")[2])
    project, scene = await _scene(token, lang, chat_id, scene_id)
    await call.answer()
    if not scene:
        return
    order = int(scene.get("order") or 0) + (-1 if direction == "up" else 1)
    try:
        await api.patch_scene(token, scene_id, {"order": max(0, order)}, lang=lang, telegram_id=chat_id)
    except ApiError:
        pass
    await show_timeline(call.message, token, lang)


@router.callback_query(F.data.startswith("st:rm:"))
async def remove_scene(call: CallbackQuery, token: str, lang: str) -> None:
    chat_id = _tid(call)
    try:
        await api.delete_scene(token, int(call.data.split(":")[2]), lang=lang, telegram_id=chat_id)
    except ApiError:
        pass
    await call.answer(t(lang, "st_removed"))
    await show_timeline(call.message, token, lang)


@router.callback_query(F.data.startswith("st:sdl:"))
async def download_scene(call: CallbackQuery, token: str, lang: str) -> None:
    chat_id = _tid(call)
    _, scene = await _scene(token, lang, chat_id, int(call.data.split(":")[2]))
    await call.answer()
    if scene and scene.get("video"):
        try:
            await call.message.answer_document(site_url(scene["video"]))
        except Exception:
            await call.message.answer(site_url(scene["video"]))


@router.callback_query(F.data == "st:as")
async def assemble(call: CallbackQuery, token: str, lang: str) -> None:
    chat_id = _tid(call)
    await call.answer()
    project_id = await _project_id(chat_id)
    if not project_id:
        return
    try:
        project = await api.project(token, project_id, lang=lang, telegram_id=chat_id)
    except ApiError:
        await call.message.answer(t(lang, "server_down"))
        return
    scenes = project.get("scenes") or []
    ready = [s for s in scenes if s.get("status") == "ready"]
    if not ready:
        await call.message.answer(t(lang, "st_no_ready"))
        return
    if len(ready) < len(scenes):
        await call.message.answer(t(lang, "st_assemble_partial"), reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[[InlineKeyboardButton(text=t(lang, "st_yes"), callback_data="st:asok"),
                              InlineKeyboardButton(text=t(lang, "st_no"), callback_data="nav:x")]]))
        return
    await _assemble(call, token, lang, project_id)


@router.callback_query(F.data == "st:asok")
async def assemble_ok(call: CallbackQuery, token: str, lang: str) -> None:
    await call.answer()
    project_id = await _project_id(_tid(call))
    if project_id:
        await _assemble(call, token, lang, project_id)


async def _assemble(call: CallbackQuery, token: str, lang: str, project_id: int) -> None:
    try:
        await api.assemble(token, project_id, lang=lang, telegram_id=_tid(call))
    except ApiError as exc:
        await call.message.answer(exc.message or t(lang, "failed"))
        return
    await call.message.answer(t(lang, "st_assembling"))


@router.callback_query(F.data == "st:del")
async def delete_confirm(call: CallbackQuery, token: str, lang: str) -> None:
    chat_id = _tid(call)
    project_id = await _project_id(chat_id)
    await call.answer()
    if not project_id:
        return
    try:
        project = await api.project(token, project_id, lang=lang, telegram_id=chat_id)
    except ApiError:
        return
    await call.message.answer(
        t(lang, "st_delete_confirm", title=project.get("title", "")),
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text=t(lang, "st_yes"), callback_data="st:delok"),
            InlineKeyboardButton(text=t(lang, "st_no"), callback_data="nav:x")]]))


@router.callback_query(F.data == "st:delok")
async def delete_ok(call: CallbackQuery, token: str, lang: str) -> None:
    chat_id = _tid(call)
    project_id = await _project_id(chat_id)
    await call.answer()
    if project_id:
        try:
            await api.delete_project(token, project_id, lang=lang, telegram_id=chat_id)
        except ApiError:
            pass
    await store.drop(chat_id, "st_project")
    await call.message.answer(t(lang, "st_deleted"))


@router.callback_query(F.data == "st:my")
async def my_projects(call: CallbackQuery, token: str, lang: str) -> None:
    chat_id = _tid(call)
    await call.answer()
    try:
        projects = await api.projects(token, lang=lang, telegram_id=chat_id)
    except ApiError:
        await call.message.answer(t(lang, "server_down"))
        return
    if not projects:
        await call.message.answer(t(lang, "st_my_empty"))
        return
    icons = {"ready": "✅", "assembling": "⏳", "failed": "❌"}
    buttons = [InlineKeyboardButton(
        text=t(lang, "st_my_line", icon=icons.get(p.get("status"), "▫️"),
               title=p.get("title", "")[:30], n=len(p.get("scenes") or [])),
        callback_data=f"st:op:{p['id']}") for p in projects[:PAGE]]
    await call.message.answer(t(lang, "st_my_title"), parse_mode="HTML",
                              reply_markup=InlineKeyboardMarkup(inline_keyboard=rows_of(buttons, 1)))


@router.callback_query(F.data.startswith("st:op:"))
async def open_project(call: CallbackQuery, token: str, lang: str) -> None:
    chat_id = _tid(call)
    project_id = int(call.data.split(":")[2])
    await store.set(chat_id, "st_project", project_id)
    try:
        project = await api.project(token, project_id, lang=lang, telegram_id=chat_id)
        char = (project.get("character") or {}).get("id")
        if char:
            await store.set(chat_id, "st_char", char)
            await store.drop(chat_id, "st_keyframes")
    except ApiError:
        pass
    await call.answer()
    await show_timeline(call.message, token, lang)
