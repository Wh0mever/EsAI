"""Студия мультфильмов: герой → сцены → лента → съёмка → сборка.

Тот же конвейер, что на сайте, теми же словами. Экран с кнопками всегда
последнее сообщение, превью уходят лентой картинок перед ним. Готовность сцен
и мультфильма приходит пушем от ядра — опрашивать ничего не нужно.
"""
from __future__ import annotations

import logging
import time

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
from bot.services.tg_format import esc
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
        "st_intro_no_price": ("🎞 <b>EsAI Cartoon Studio</b>\n"
                              "Выберите героя, наберите сцены — и студия соберёт готовый ролик. "
                              "Промпты писать не нужно.\n\n"
                              "Герой из библиотеки — бесплатно · свой герой — {character} кр · "
                              "склейка — бесплатно"),
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
        "st_hero_ready": "✏️ Герой «{name}» готов, кредиты уже списаны. Картинка: {url}",
        "st_project_started": "🎬 Мультфильм создан. Герой: <b>{hero}</b>. Теперь выберите сцены.",
        "st_cats": "🗂 <b>Разделы сцен</b>", "st_cat_popular": "🔥 Популярное", "st_cat_picks": "⭐ Выбор EsAI",
        "st_cat_all": "🗂 Все", "st_to_timeline": "🎞 К ленте ({n})",
        "st_scenes": "🎬 <b>{category}</b> (стр. {page}/{pages})\n{lines}",
        "st_scene_line": "{n} — {title} · {credits} · {duration} с{ready}",
        "st_scene_card": "🎬 <b>{title}</b>\n{subtitle}\n{credits} · {duration} с",
        "st_cr": "{n} кр", "st_no_price": "цена недоступна",
        "st_no_price_render": "Цена сцены сейчас недоступна, попробуйте позже.",
        "st_add": "➕ В ленту", "st_try": "🪄 Примерить героя", "st_kf": "👁 Кадр с вашим героем",
        "st_added": "Сцена «{title}» в ленте. Снять её можно из ленты.",
        "st_try_free": "Кадр уже был — бесплатно.", "st_try_paid": "Списано {credits} кр.",
        "st_timeline": ("🎞 <b>{title}</b> · герой: {hero}\n{lines}\n\n"
                        "Готово {ready} из {total} · потрачено {spent} кр"),
        "st_tl_line": "{n}. {icon} {title} — {status} · {credits}",
        "st_status_draft": "в ленте, не снята", "st_status_new": "в очереди",
        "st_status_keyframe": "рисую кадр", "st_status_video": "оживляю",
        "st_status_ready": "готова", "st_status_failed": "не получилась",
        "st_render_all": "🎬 Снять все не снятые ({credits})", "st_add_scene": "➕ Добавить сцену",
        "st_assemble": "🎞 Собрать мультфильм", "st_refresh": "🔄 Обновить", "st_delete": "🗑 Удалить проект",
        "st_scene_menu": "⚙️ {n}", "st_render": "🎬 Снять сцену ({credits})",
        "st_up": "🔼 Раньше", "st_down": "🔽 Позже", "st_retry": "🔁 Переснять",
        "st_retry_same": "🔁 С тем же кадром ({credits})", "st_retry_new": "🆕 Новый кадр ({credits})",
        "st_download": "📥 Скачать сцену", "st_remove": "🗑 Убрать",
        "st_rendering": "🎬 Снимаю «{title}»… Пришлю сюда, как будет готово. Кредиты спишутся за готовое видео.",
        "st_already_rendering": "🎬 «{title}» уже снимается — дождитесь результата. Второй раз платить не нужно.",
        "st_render_all_done": "Поставил в очередь сцен: {n}.",
        "st_paywall_studio": ("Сцена стоит {need} кр, на балансе {have}. Мультфильм и уже снятые сцены "
                              "никуда не денутся — пополните и продолжайте."),
        "st_paywall_studio_all": ("Все не снятые сцены стоят {need} кр, на балансе {have}. Снимаю те, "
                                  "на которые хватает; остальные подождут пополнения."),
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
        "st_empty_audience": "В этом разделе нет сцен для выбранной аудитории.",
        "st_audience_off": "👨‍👩‍👧 Показать сцены для всех",
        "st_wait_photo": "📷 Жду фото героя — пришлите картинку. Текст здесь не подойдёт.",
        "st_wizard_cancel": "✖ Отмена",
        "st_wizard_cancelled": "Загрузка героя отменена.",
        "st_wizard_expired": ("📷 Я слишком долго ждал фото героя и больше его не жду. "
                              "Начните заново: /studio"),
        "st_back": "↩ Разделы",
        "st_result": "🎞 Мультфильм «{title}» · сцен {n}",
        "st_removed": "Сцена убрана из ленты.",
        "st_price_changed": ("💡 Цена сцены изменилась: теперь {credits}. Ничего не списано — "
                             "проверьте и нажмите «Снять» ещё раз."),
        "st_price_check": "🔄 Кнопка устарела — вот сцена с ценой на сейчас.",
        "st_render_all_confirm": "Все не снятые сцены сейчас стоят {credits}. Снимаем?",
        "st_render_all_changed": ("💡 Цена изменилась: все не снятые сцены теперь стоят {credits} "
                                  "(на кнопке было {was}). Снимаем?"),
        "st_render_all_ok": "🎬 Снять за {credits}",
        "st_render_all_stopped": ("💡 Цена изменилась, пока сцены вставали в очередь, — остальные не "
                                  "поставлены, лишнего не списано. Вот лента с новыми ценами."),
        "st_already_shot": ("✅ Сцена «{title}» уже снята — второй раз не снимаю, ничего не списано. "
                            "Переснять можно кнопками ниже."),
        "st_menu_stale": ("🔄 Это меню устарело: сцену «{title}» с тех пор уже переснимали. Ничего не "
                          "снято и не списано — вот она сейчас."),
    },
    "en": {
        "st_intro": ("🎞 <b>EsAI Cartoon Studio</b>\n"
                     "Pick a hero, collect scenes — and the studio assembles the film. "
                     "No prompts needed.\n\n"
                     "Library hero — free · your own hero — {character} cr · "
                     "scene — from {scene_min} cr · assembly — free"),
        "st_intro_no_price": ("🎞 <b>EsAI Cartoon Studio</b>\n"
                              "Pick a hero, collect scenes — and the studio assembles the film. "
                              "No prompts needed.\n\n"
                              "Library hero — free · your own hero — {character} cr · "
                              "assembly — free"),
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
        "st_hero_ready": "✏️ Hero “{name}” is ready, credits are already charged. Image: {url}",
        "st_project_started": "🎬 Cartoon created. Hero: <b>{hero}</b>. Now pick the scenes.",
        "st_cats": "🗂 <b>Scene sections</b>", "st_cat_popular": "🔥 Popular", "st_cat_picks": "⭐ EsAI picks",
        "st_cat_all": "🗂 All", "st_to_timeline": "🎞 Timeline ({n})",
        "st_scenes": "🎬 <b>{category}</b> (page {page}/{pages})\n{lines}",
        "st_scene_line": "{n} — {title} · {credits} · {duration} s{ready}",
        "st_scene_card": "🎬 <b>{title}</b>\n{subtitle}\n{credits} · {duration} s",
        "st_cr": "{n} cr", "st_no_price": "price unavailable",
        "st_no_price_render": "The scene price is unavailable right now, please try again later.",
        "st_add": "➕ Add to timeline", "st_try": "🪄 Try the hero", "st_kf": "👁 Frame with your hero",
        "st_added": "Scene “{title}” is in the timeline. Render it from there.",
        "st_try_free": "The frame already existed — free.", "st_try_paid": "{credits} cr charged.",
        "st_timeline": ("🎞 <b>{title}</b> · hero: {hero}\n{lines}\n\n"
                        "Ready {ready} of {total} · spent {spent} cr"),
        "st_tl_line": "{n}. {icon} {title} — {status} · {credits}",
        "st_status_draft": "in timeline, not rendered", "st_status_new": "queued",
        "st_status_keyframe": "drawing the frame", "st_status_video": "animating",
        "st_status_ready": "ready", "st_status_failed": "failed",
        "st_render_all": "🎬 Render all pending ({credits})", "st_add_scene": "➕ Add a scene",
        "st_assemble": "🎞 Assemble the cartoon", "st_refresh": "🔄 Refresh", "st_delete": "🗑 Delete project",
        "st_scene_menu": "⚙️ {n}", "st_render": "🎬 Render scene ({credits})",
        "st_up": "🔼 Earlier", "st_down": "🔽 Later", "st_retry": "🔁 Re-render",
        "st_retry_same": "🔁 Same frame ({credits})", "st_retry_new": "🆕 New frame ({credits})",
        "st_download": "📥 Download scene", "st_remove": "🗑 Remove",
        "st_rendering": "🎬 Rendering “{title}”… I will send it here when ready. Credits are charged for the finished video.",
        "st_already_rendering": "🎬 “{title}” is already rendering — wait for the result. No need to pay twice.",
        "st_render_all_done": "Queued scenes: {n}.",
        "st_paywall_studio": ("The scene costs {need} cr, you have {have}. The cartoon and rendered scenes "
                              "stay — top up and continue."),
        "st_paywall_studio_all": ("All the unrendered scenes cost {need} cr, you have {have}. I will render "
                                  "the ones you can afford; the rest wait for a top-up."),
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
        "st_empty_audience": "No scenes in this section for the chosen audience.",
        "st_audience_off": "👨‍👩‍👧 Show scenes for everyone",
        "st_wait_photo": "📷 I'm waiting for the hero's photo — send an image. Text won't do here.",
        "st_wizard_cancel": "✖ Cancel",
        "st_wizard_cancelled": "Hero upload cancelled.",
        "st_wizard_expired": ("📷 I waited too long for the hero's photo and stopped waiting. "
                              "Start again: /studio"),
        "st_back": "↩ Sections",
        "st_result": "🎞 Cartoon “{title}” · scenes {n}",
        "st_removed": "Scene removed from the timeline.",
        "st_price_changed": ("💡 The scene price has changed: it is now {credits}. Nothing was charged — "
                             "check it and tap “Render” again."),
        "st_price_check": "🔄 That button is out of date — here is the scene at today's price.",
        "st_render_all_confirm": "All pending scenes now cost {credits}. Render them?",
        "st_render_all_changed": ("💡 The price has changed: all pending scenes now cost {credits} "
                                  "(the button said {was}). Render them?"),
        "st_render_all_ok": "🎬 Render for {credits}",
        "st_render_all_stopped": ("💡 The price changed while the scenes were being queued — the rest "
                                  "were not queued and nothing extra was charged. Here is the timeline "
                                  "with the new prices."),
        "st_already_shot": ("✅ Scene “{title}” is already rendered — I won't render it again and nothing "
                            "was charged. You can re-render it with the buttons below."),
        "st_menu_stale": ("🔄 This menu is out of date: “{title}” has been re-rendered since. Nothing was "
                          "rendered or charged — here is the scene now."),
    },
    "kg": {
        "st_intro": ("🎞 <b>EsAI Cartoon Studio</b>\n"
                     "Каарманды тандаңыз, сценаларды чогултуңуз — студия даяр роликти чогултат. "
                     "Промпт жазуунун кереги жок.\n\n"
                     "Китепканадагы каарман — бекер · өз каарманыңыз — {character} кр · "
                     "сцена — {scene_min} кр баштап · бириктирүү — бекер"),
        "st_intro_no_price": ("🎞 <b>EsAI Cartoon Studio</b>\n"
                              "Каарманды тандаңыз, сценаларды чогултуңуз — студия даяр роликти чогултат. "
                              "Промпт жазуунун кереги жок.\n\n"
                              "Китепканадагы каарман — бекер · өз каарманыңыз — {character} кр · "
                              "бириктирүү — бекер"),
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
        "st_hero_ready": "✏️ «{name}» каарманы даяр, кредиттер алынып койду. Сүрөт: {url}",
        "st_project_started": "🎬 Мультфильм түзүлдү. Каарман: <b>{hero}</b>. Эми сценаларды тандаңыз.",
        "st_cats": "🗂 <b>Сцена бөлүмдөрү</b>", "st_cat_popular": "🔥 Популярдуу", "st_cat_picks": "⭐ EsAI тандоосу",
        "st_cat_all": "🗂 Баары", "st_to_timeline": "🎞 Лентага ({n})",
        "st_scenes": "🎬 <b>{category}</b> ({page}/{pages}-бет)\n{lines}",
        "st_scene_line": "{n} — {title} · {credits} · {duration} с{ready}",
        "st_scene_card": "🎬 <b>{title}</b>\n{subtitle}\n{credits} · {duration} с",
        "st_cr": "{n} кр", "st_no_price": "баасы жеткиликсиз",
        "st_no_price_render": "Сценанын баасы азыр жеткиликсиз, бир аздан кийин кайра аракет кылыңыз.",
        "st_add": "➕ Лентага", "st_try": "🪄 Каарманды текшерүү", "st_kf": "👁 Каарманыңыз менен кадр",
        "st_added": "«{title}» сценасы лентада. Аны лентадан тартсаңыз болот.",
        "st_try_free": "Кадр мурда эле бар — бекер.", "st_try_paid": "{credits} кр алынды.",
        "st_timeline": ("🎞 <b>{title}</b> · каарман: {hero}\n{lines}\n\n"
                        "Даяр {ready}/{total} · сарпталды {spent} кр"),
        "st_tl_line": "{n}. {icon} {title} — {status} · {credits}",
        "st_status_draft": "лентада, тартыла элек", "st_status_new": "кезекте",
        "st_status_keyframe": "кадр тартылууда", "st_status_video": "жандандырылууда",
        "st_status_ready": "даяр", "st_status_failed": "чыккан жок",
        "st_render_all": "🎬 Баарын тартуу ({credits})", "st_add_scene": "➕ Сцена кошуу",
        "st_assemble": "🎞 Мультфильмди чогултуу", "st_refresh": "🔄 Жаңыртуу", "st_delete": "🗑 Долбоорду өчүрүү",
        "st_scene_menu": "⚙️ {n}", "st_render": "🎬 Сценаны тартуу ({credits})",
        "st_up": "🔼 Мурда", "st_down": "🔽 Кийин", "st_retry": "🔁 Кайра тартуу",
        "st_retry_same": "🔁 Ошол эле кадр ({credits})", "st_retry_new": "🆕 Жаңы кадр ({credits})",
        "st_download": "📥 Сценаны жүктөө", "st_remove": "🗑 Алып салуу",
        "st_rendering": "🎬 «{title}» тартып жатам… Даяр болгондо ушул жерге жөнөтөм.",
        "st_already_rendering": "🎬 «{title}» мурунтан тартылып жатат — натыйжаны күтүңүз. Экинчи жолу төлөөнүн кереги жок.",
        "st_render_all_done": "Кезекке коюлган сценалар: {n}.",
        "st_paywall_studio": ("Сцена {need} кр турат, балансыңызда {have}. Мультфильм жана тартылган сценалар "
                              "сакталат — толуктап, улантыңыз."),
        "st_paywall_studio_all": ("Тартылбаган сценалардын баары {need} кр турат, балансыңызда {have}. "
                                  "Жеткендерин тартам, калгандары толуктаганды күтөт."),
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
        "st_empty_audience": "Бул бөлүмдө тандалган аудитория үчүн сцена жок.",
        "st_audience_off": "👨‍👩‍👧 Баары үчүн сценаларды көрсөтүү",
        "st_wait_photo": "📷 Каармандын сүрөтүн күтүп жатам — сүрөт жөнөтүңүз. Текст бул жерде жарабайт.",
        "st_wizard_cancel": "✖ Жокко чыгаруу",
        "st_wizard_cancelled": "Каарманды жүктөө жокко чыгарылды.",
        "st_wizard_expired": ("📷 Каармандын сүрөтүн өтө көп күттүм, эми күтпөйм. "
                              "Кайра баштаңыз: /studio"),
        "st_back": "↩ Бөлүмдөр",
        "st_result": "🎞 «{title}» мультфильми · сцена {n}",
        "st_removed": "Сцена лентадан алынды.",
        "st_price_changed": ("💡 Сценанын баасы өзгөрдү: эми {credits}. Эч нерсе алынган жок — "
                             "текшерип, «Тартуу» баскычын кайра басыңыз."),
        "st_price_check": "🔄 Бул баскыч эскирип калды — сцена азыркы баасы менен.",
        "st_render_all_confirm": "Тартылбаган сценалардын баары азыр {credits} турат. Тартабызбы?",
        "st_render_all_changed": ("💡 Баа өзгөрдү: тартылбаган сценалардын баары эми {credits} турат "
                                  "(баскычта {was} болчу). Тартабызбы?"),
        "st_render_all_ok": "🎬 {credits} төлөп тартуу",
        "st_render_all_stopped": ("💡 Сценалар кезекке коюлуп жатканда баа өзгөрдү — калгандары коюлган "
                                  "жок, ашыкча эч нерсе алынган жок. Жаңы баалар менен лента."),
        "st_already_shot": ("✅ «{title}» сценасы тартылып бүткөн — экинчи жолу тартпайм, эч нерсе "
                            "алынган жок. Кайра тартуу үчүн төмөнкү баскычтарды басыңыз."),
        "st_menu_stale": ("🔄 Бул меню эскирип калды: «{title}» сценасы андан бери кайра тартылган. Эч "
                          "нерсе тартылган жок, эч нерсе алынган жок — сцена азыр мындай."),
    },
})

STATUS_ICON = {"draft": "▫️", "new": "⏳", "keyframe": "🖌", "video": "⏳", "ready": "✅", "failed": "❌"}
# Сцена уже в работе: очередь, кадр или видео. Повторная заявка на такую сцену
# оплачивается второй раз, а результат человек получает один.
BUSY_STATUSES = ("new", "keyframe", "video")


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


def _default_scene_price(models: dict) -> int | None:
    """Цена сцены нового мультфильма из списка моделей дока, или None.

    Новый мультфильм получает настройки по умолчанию из админки (сейчас Seedance
    Mini 480p 5 с), если модель включена; source="preset" — откат на пресеты, и
    тогда верна прежняя цифра /pricing/. Клетка таблицы — цена сцены целиком
    (кадр + видео) — та самая, что увидит человек в ленте.
    """
    defaults = models.get("defaults") or {}
    if defaults.get("source") != "settings":
        return None
    row = next((m for m in models.get("models") or []
                if isinstance(m, dict) and m.get("id") == defaults.get("video_model")), None)
    table = ((row or {}).get("price") or {}).get("table") or {}
    value = (table.get(str(defaults.get("resolution") or "")) or {}).get(str(defaults.get("duration") or ""))
    return value if isinstance(value, int) and value > 0 else None


async def _scene_from(token: str, lang: str, chat_id: int, pricing: dict) -> int | None:
    """«Сцена — от N кр» на входе в студию: цена сцены нового мультфильма; None — цены нет.

    Сначала — клетка таблицы модели по умолчанию (GET models/, та же цена, что в ленте).
    Её нет (модели недоступны, по умолчанию стоят пресеты, у модели нет цены) — scene_min
    из /pricing/: сервер считает его так же, по настройкам нового мультфильма, а без них —
    по пресетам. 0, пусто или мусор — цены нет: «от 0 кр» было бы враньём.
    """
    cached = await store.get(chat_id, "st_scene_from")
    if isinstance(cached, dict):
        value = cached.get("n")
    else:
        try:
            value = _default_scene_price(await api.cartoon_models(token, lang=lang, telegram_id=chat_id))
        except ApiError:
            # Сбой не запоминаем: следующий вход спросит снова.
            value = None
        else:
            await store.set(chat_id, "st_scene_from", {"n": value}, ttl=1800)
    if value is not None:
        return value
    fallback = pricing.get("scene_min")
    return fallback if isinstance(fallback, int) and not isinstance(fallback, bool) and fallback > 0 else None


async def _presets(token: str, lang: str, chat_id: int) -> dict:
    # Цена сцены — по настройкам открытого мультфильма: модель, качество,
    # длительность и формат. Новые мультфильмы снимаются на Seedance Mini 480p,
    # и цена пресета (Seedance 2.0 720p) в библиотеке была бы враньём, поэтому
    # спрашиваем витрину для мультфильма (?project=). Кэш свой у каждого
    # мультфильма и набора его настроек: сменили их на сайте — цены другие.
    aspect = str(await store.get(chat_id, "st_aspect") or "")
    project_id = await _project_id(chat_id)
    if project_id:
        dock = str(await store.get(chat_id, "st_dock") or "")
        key = f"st_presets:p{project_id}:{aspect}:{dock}"
        cached = await store.get(chat_id, key)
        if cached:
            return cached
        try:
            data = await api.presets(token, project=project_id, lang=lang, telegram_id=chat_id)
        except ApiError as exc:
            # Мультфильм удалили на сайте — библиотека всё равно нужна, просто
            # с ценами пресетов, как без мультфильма.
            if exc.status != 404:
                raise
        else:
            await store.set(chat_id, key, data, ttl=900)
            return data
    key = f"st_presets:{aspect}" if aspect else "st_presets"
    cached = await store.get(chat_id, key)
    if cached:
        return cached
    data = await api.presets(token, aspect_ratio=aspect, lang=lang, telegram_id=chat_id)
    await store.set(chat_id, key, data, ttl=900)
    return data


async def _note_project(chat_id: int, project: dict | None) -> None:
    """Запомнить формат и настройки открытого мультфильма — по ним считаются цены
    библиотеки, и по ним же видно, что кэш витрины устарел."""
    project = project or {}
    await store.set(chat_id, "st_aspect", str(project.get("aspect_ratio") or ""), ttl=6 * 3600)
    dock = "|".join(str(project.get(field) or "") for field in ("video_model", "resolution", "duration"))
    await store.set(chat_id, "st_dock", dock, ttl=6 * 3600)


async def _project_id(chat_id: int) -> int | None:
    value = await store.get(chat_id, "st_project")
    return int(value) if value else None


def _webapp_url(project_id: int | None = None) -> str:
    base = f"{settings.site_base_url}/tg/studio"
    return f"{base}?project={project_id}" if project_id else base


async def _send_media_group(message: Message, urls: list[str]) -> None:
    """Показать превью списка одной лентой картинок.

    Telegram принимает медиа-группу только из 2–10 элементов. На группе из
    одного он отвечает Bad Request, и превью пропадали молча — в лог, а не
    человеку. Ловилось это ровно там, где обиднее всего: на последней странице
    героев или сцен, где часто остаётся один элемент.
    """
    media = [InputMediaPhoto(media=site_url(u)) for u in urls if u]
    if not media:
        return
    for start in range(0, len(media), 10):
        batch = media[start:start + 10]
        try:
            if len(batch) == 1:
                await message.answer_photo(batch[0].media)
            else:
                await message.answer_media_group(batch)
        except Exception:
            logger.exception("превью не отправились")


def _cr(lang: str, credits) -> str:
    """«N кр» или «цена недоступна»: в режиме цен «наценка» у сцены на модели без
    себестоимости цены нет (null), и «None кр» человеку показывать нельзя."""
    return t(lang, "st_no_price") if credits is None else t(lang, "st_cr", n=credits)


def _render_price(scene: dict):
    """Сколько спишет «Снять» эту сцену прямо сейчас — число сервера.

    render_credits посчитан по настройкам мультфильма (модель, качество, своя
    длительность сцены), и с готовым кадром это только видео — ровно то, что
    проверит баланс. Старый сервер его не присылает: тогда цена сцены, как
    раньше. None — цены нет, такую сцену сервер не снимет.
    """
    if "render_credits" in scene:
        return scene.get("render_credits")
    return (scene.get("preset") or {}).get("credits", 0)


def _price_tag(credits) -> str:
    """Цена с кнопки для callback_data: число; цены нет — пусто.

    Сервер снимает, только если цена не выросла с тех пор, как её показали
    (настройки мультфильма меняют и на сайте, а кнопки в Telegram живут днями).
    """
    if isinstance(credits, bool):
        return ""
    try:
        value = int(credits)
    except (TypeError, ValueError):
        return ""
    return str(value) if value >= 0 else ""


def _quoted(part: str | None) -> int | None:
    """Цена из callback_data; None — кнопка без цены (старая или цены тогда не было)."""
    return int(part) if part and part.isascii() and part.isdigit() else None


def _menu_state(scene: dict) -> str:
    """Какое меню видел человек — хвост кнопки пересъёмки: «f» — сцена не получилась,
    «r<метка>» — готовая сцена и метка её ролика (shot_token сервера, 8 hex). Метки нет
    (готовая сцена без ролика) — голое «r»: _menu_seen примет его за устаревшую кнопку."""
    if scene.get("status") != "ready":
        return "f"
    token = str(scene.get("shot_token") or "")
    return "r" + (token if len(token) <= 16 and token.isascii() and token.isalnum() else "")


def _menu_seen(part: str | None) -> tuple[str | None, str]:
    """(состояние меню, метка ролика) из хвоста кнопки; (None, "") — хвоста нет или он
    непонятный: кнопка из сборки без хвоста.

    Меню готовой сцены без метки ролика — тоже (None, ""): без метки сервер не отличит
    «тот же ролик» от «уже пересняли», и второе нажатие переснимало бы и списывало ещё
    раз (C_R1_polish N2). Такая кнопка, как и кнопка без цены, никогда не снимает.
    """
    if part == "f":
        return "failed", ""
    if not part or part[0] != "r":
        return None, ""
    token = part[1:]
    if not token or len(token) > 16 or not all(c.isascii() and c.isalnum() for c in token):
        return None, ""
    return "ready", token


async def _stale_scene(message: Message, lang: str, scene: dict | None) -> None:
    """Кнопка пересъёмки из устаревшего меню: сцену с тех пор сняли, переснимают или
    пересъёмка не удалась. Ничего не снято и не списано — показываем сцену как есть."""
    if not isinstance(scene, dict) or not scene.get("id"):
        await message.answer(t(lang, "failed"))
        return
    title = esc((scene.get("preset") or {}).get("title", ""))
    if scene.get("status") == "ready":
        await _already_shot(message, lang, scene)
    elif scene.get("status") in BUSY_STATUSES:
        await message.answer(t(lang, "st_already_rendering", title=title))
    else:
        await message.answer(t(lang, "st_menu_stale", title=title))
        await _send_scene_menu(message, lang, scene)


def _row_price(scene: dict):
    """Цена в строке ленты: у не снятой сцены — сколько спишет «Снять» (их и
    складывает «Снять все»), у остальных — цена сцены, как раньше."""
    if scene.get("status") in ("draft", "failed"):
        return _render_price(scene)
    return (scene.get("preset") or {}).get("credits", 0)


def _fail(lang: str, exc: ApiError) -> str:
    """Текст ошибки бэкенда, безопасный для HTML-режима.

    В detail прилетает сырой ответ провайдера — вплоть до HTML-страницы от
    прокси. Без экранирования первый же «<» ломает СООБЩЕНИЕ ЦЕЛИКОМ, и
    человек не узнаёт даже того, что именно не получилось. Длину режем: экран
    ошибки не место для чужой вёрстки.
    """
    if exc.code == "price_unavailable":
        # Отказ «цены нет» сервер присылает по-русски — говорим на языке человека.
        return t(lang, "st_no_price_render")
    return esc(str(exc.message)[:300]) if exc.message else t(lang, "failed")


# Состояние FSM живёт в Redis без срока, поэтому мастер героя надо закрывать
# самим: иначе фото, присланное на следующий день, молча становится героем.
WIZARD_TTL = 3600


async def _wizard_started(chat_id: int) -> None:
    """Запомнить момент входа в мастер героя."""
    await store.set(chat_id, "st_wizard_at", int(time.time()), ttl=24 * 3600)


async def _wizard_stale(chat_id: int) -> bool:
    """Мастер уже не ждёт? Отметки нет — значит, состояние осталось от прошлого раза."""
    started = await store.get(chat_id, "st_wizard_at")
    try:
        return (time.time() - float(started)) > WIZARD_TTL
    except (TypeError, ValueError):
        return True


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
    scene_min = await _scene_from(token, lang, chat_id, pricing)
    # Цены сцены нет — вступление без неё, а не «от 0 кр» и не выдуманное число.
    intro = (t(lang, "st_intro", character=pricing.get("character", 4), scene_min=scene_min)
             if scene_min is not None else t(lang, "st_intro_no_price", character=pricing.get("character", 4)))
    await message.answer(intro, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))


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
    # Имя героя придумывает человек: без esc герой «Кот <3» ломает весь экран,
    # и такого героя уже не выбрать и не удалить из бота.
    lines = "\n".join(f"{i} — {esc(h.get('name'))}{' 👤' if h.get('is_mine') else ''}"
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
        await call.message.answer(_fail(lang, exc))
        return
    await store.set(chat_id, "st_project", project["id"])
    await store.set(chat_id, "st_char", hero_id)
    await store.drop(chat_id, "st_keyframes")
    await _note_project(chat_id, project)
    await call.answer()
    hero = (project.get("character") or {}).get("name", "")
    await call.message.answer(t(lang, "st_project_started", hero=esc(hero)), parse_mode="HTML")
    await show_categories(call.message, token, lang)


def _wizard_kb(lang: str) -> InlineKeyboardMarkup:
    """Из ожидания фото должен быть выход, и он должен быть виден."""
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text=t(lang, "st_wizard_cancel"), callback_data="st:wx")]])


@router.callback_query(F.data == "st:hu")
async def hero_upload(call: CallbackQuery, lang: str, state: FSMContext) -> None:
    await _wizard_started(_tid(call))
    await state.set_state(StudioWizard.hero_photo)
    await call.answer()
    await call.message.answer(t(lang, "st_hero_upload_ask"), reply_markup=_wizard_kb(lang))


@router.callback_query(F.data == "st:wx")
async def hero_upload_cancel(call: CallbackQuery, lang: str, state: FSMContext) -> None:
    # Кнопка остаётся в старом сообщении: нажатие через час не должно обрывать
    # ДРУГОЙ мастер, в котором человек уже успел оказаться (описание картинки,
    # промпт видео) — иначе отмена героя молча съедает чужой ввод.
    if await state.get_state() == StudioWizard.hero_photo.state:
        await state.clear()
    await store.drop(_tid(call), "st_wizard_at")
    await call.answer()
    await call.message.answer(t(lang, "st_wizard_cancelled"))


@router.message(StudioWizard.hero_photo, F.text & ~F.text.startswith("/"))
async def hero_photo_text(message: Message, lang: str, state: FSMContext) -> None:
    """Текст вместо фото: подсказать, а не молча ронять его в общий чат.

    Раньше такое сообщение уходило мимо, состояние оставалось висеть, и
    человек не понимал, почему студия его не слышит.
    """
    if await _wizard_stale(message.chat.id):
        await state.clear()
        await store.drop(message.chat.id, "st_wizard_at")
        await message.answer(t(lang, "st_wizard_expired"))
        return
    await message.answer(t(lang, "st_wait_photo"), reply_markup=_wizard_kb(lang))


@router.message(StudioWizard.hero_photo, F.photo)
async def hero_photo(message: Message, token: str, lang: str, state: FSMContext) -> None:
    from bot.routers.media import download

    chat_id = message.chat.id
    # Просроченный мастер не должен превращать случайную картинку в героя и
    # заводить под неё проект — тем более через сутки после входа.
    if await _wizard_stale(chat_id):
        await state.clear()
        await store.drop(chat_id, "st_wizard_at")
        await message.answer(t(lang, "st_wizard_expired"))
        return
    await state.clear()
    await store.drop(chat_id, "st_wizard_at")
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
    await message.answer(t(lang, "st_hero_saved", name=esc(hero.get("name", name))))
    await _use_hero(message, token, lang, hero["id"])


async def _use_hero(message: Message, token: str, lang: str, hero_id: int) -> None:
    chat_id = message.chat.id
    try:
        project = await api.create_project(token, hero_id, lang=lang, telegram_id=chat_id)
    except ApiError as exc:
        await message.answer(_fail(lang, exc))
        return
    await store.set(chat_id, "st_project", project["id"])
    await store.set(chat_id, "st_char", hero_id)
    await store.drop(chat_id, "st_keyframes")
    await _note_project(chat_id, project)
    await message.answer(t(lang, "st_project_started",
                           hero=esc((project.get("character") or {}).get("name", ""))),
                         parse_mode="HTML")
    await show_categories(message, token, lang)


@router.callback_query(F.data == "st:hd")
async def hero_draw(call: CallbackQuery, token: str, lang: str, state: FSMContext) -> None:
    pricing = await _pricing(token, lang, _tid(call))
    await state.set_state(StudioWizard.hero_prompt)
    await _wizard_started(_tid(call))
    await call.answer()
    await call.message.answer(t(lang, "st_hero_draw_ask", price=pricing.get("character", 4)))


@router.message(StudioWizard.hero_prompt, F.text & ~F.text.startswith("/"))
async def hero_prompt(message: Message, token: str, lang: str, state: FSMContext) -> None:
    from bot.keyboards.common import MENU_ACTIONS

    if message.text in MENU_ACTIONS:
        await state.clear()
        return
    chat_id = message.chat.id
    # Рисование героя платное. Забытый со вчера мастер не должен превращать
    # обычную фразу в списание: просроченное состояние закрываем молча.
    if await _wizard_stale(chat_id):
        await state.clear()
        await store.drop(chat_id, "st_wizard_at")
        await message.answer(t(lang, "st_wizard_expired"))
        return
    await state.clear()
    await store.drop(chat_id, "st_wizard_at")
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
            await message.answer(_fail(lang, exc))
        return
    try:
        await status.delete()
    except Exception:
        pass
    pricing = await _pricing(token, lang, chat_id)
    rows = [[InlineKeyboardButton(text=t(lang, "st_hero_take"), callback_data=f"st:h:{hero['id']}"),
             InlineKeyboardButton(text=t(lang, "st_hero_redraw", price=pricing.get("character", 4)),
                                  callback_data="st:hd")]]
    markup = InlineKeyboardMarkup(inline_keyboard=rows)
    image = site_url(hero.get("image", ""))
    name = hero.get("name", "")
    # Кредиты за героя уже списаны. Если отправка сорвётся (имя из описания
    # человека ломает HTML, Telegram не забрал картинку), человек обязан всё
    # равно получить результат — иначе он заплатил и не увидел ничего.
    try:
        await message.answer_photo(image, caption=esc(name), reply_markup=markup)
    except Exception:
        logger.exception("фото нарисованного героя не отправилось")
        await message.answer(t(lang, "st_hero_ready", name=name, url=image),
                             parse_mode=None, reply_markup=markup)


# ------------------------------------------------------------- сцены ---

async def show_categories(message: Message, token: str, lang: str) -> None:
    chat_id = message.chat.id
    # Мультфильм — до витрины: его формат и настройки могли смениться на сайте,
    # а цены библиотеки считаются именно по ним.
    project_id = await _project_id(chat_id)
    n = 0
    if project_id:
        try:
            project = await api.project(token, project_id, lang=lang, telegram_id=chat_id)
            n = len(project.get("scenes") or [])
            await _note_project(chat_id, project)
        except ApiError:
            pass
    try:
        data = await _presets(token, lang, chat_id)
    except ApiError:
        await message.answer(t(lang, "server_down"))
        return
    cats = data.get("categories") or []
    # Slug раздела в базе — до 90 символов, а вся callback_data ограничена 64
    # байтами. Телеграм на длинной кнопке отвергает не её одну, а ВЕСЬ набор:
    # один раздел с длинным кодом убивал экран разделов целиком. Поэтому в
    # кнопке едет номер раздела, а сами коды лежат в памяти бота.
    await store.set(chat_id, "st_cats", [c.get("slug", "") for c in cats], ttl=6 * 3600)
    buttons = [InlineKeyboardButton(text=f"{c.get('emoji', '')} {c.get('title')}".strip(),
                                    callback_data=f"st:cat:c{i}:0")
               for i, c in enumerate(cats)]
    rows = []
    top = [InlineKeyboardButton(text=t(lang, "st_cat_all"), callback_data="st:cat:all:0")]
    if data.get("popular"):
        top.insert(0, InlineKeyboardButton(text=t(lang, "st_cat_popular"), callback_data="st:cat:popular:0"))
    if any(p.get("is_pick") for p in data.get("presets") or []):
        top.insert(-1, InlineKeyboardButton(text=t(lang, "st_cat_picks"), callback_data="st:cat:picks:0"))
    rows.append(top)
    rows += rows_of(buttons, 2)
    rows.append([InlineKeyboardButton(text=t(lang, "st_to_timeline", n=n), callback_data="st:tl")])
    await message.answer(t(lang, "st_cats"), parse_mode="HTML",
                         reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))


@router.callback_query(F.data == "st:cats")
async def categories(call: CallbackQuery, token: str, lang: str) -> None:
    await call.answer()
    await show_categories(call.message, token, lang)


async def _cat_slug(chat_id: int, code: str) -> str:
    """Развернуть код из callback_data в настоящий slug раздела.

    Виртуальные разделы (all/popular/picks) и кнопки из старых сообщений, где
    ещё лежал сам slug, проходят как есть.
    """
    if not (code.startswith("c") and code[1:].isdigit()):
        return code
    slugs = await store.get(chat_id, "st_cats") or []
    index = int(code[1:])
    # Список мог протухнуть в Redis — тогда честнее показать всё, чем пустоту.
    return slugs[index] if 0 <= index < len(slugs) else "all"


def _for_audience(item: dict, audience: str) -> bool:
    """Сцена подходит выбранной аудитории или помечена универсальной."""
    return audience == "all" or (item.get("audience") or "all") in (audience, "all")


def _filter_presets(data: dict, slug: str, audience: str = "all") -> tuple[str, list]:
    presets = [p for p in (data.get("presets") or []) if _for_audience(p, audience)]
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
    _, _, code, page = call.data.split(":")
    await call.answer()
    await show_scenes(call.message, token, lang, code, int(page))


@router.callback_query(F.data.startswith("st:audoff:"))
async def scenes_any_audience(call: CallbackQuery, token: str, lang: str) -> None:
    """Снять фильтр аудитории и вернуться в тот же раздел."""
    await store.set(_tid(call), "st_audience", "all", ttl=6 * 3600)
    await call.answer()
    await show_scenes(call.message, token, lang, call.data.split(":")[2], 0)


async def show_scenes(message: Message, token: str, lang: str, code: str, page: int) -> None:
    chat_id = message.chat.id
    try:
        data = await _presets(token, lang, chat_id)
    except ApiError:
        await message.answer(t(lang, "server_down"))
        return
    # Из кода раздела мы соберём ещё и кнопки этого экрана, а на всю
    # callback_data дано 64 байта. Слишком длинный код (сырой slug из кнопки
    # старого сообщения) откатываем на «все разделы» — иначе клавиатура
    # уедет за лимит и Телеграм не покажет экран вовсе.
    if len(code.encode()) > 24:
        code = "all"
    slug = await _cat_slug(chat_id, code)
    # Аудиторию человек выбирал в начале мастера, и раньше она резала только
    # героев: ребёнку в тех же разделах показывались взрослые сцены.
    audience = await store.get(chat_id, "st_audience") or "all"
    title, presets = _filter_presets(data, slug, audience)
    if not presets:
        # Раздел пуст сам по себе или это фильтр отсёк всё? Во втором случае
        # молчать нечестно — предлагаем снять фильтр, а не гадать.
        if audience != "all" and _filter_presets(data, slug)[1]:
            await message.answer(
                t(lang, "st_empty_audience"),
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text=t(lang, "st_audience_off"),
                                          callback_data=f"st:audoff:{code}")],
                    [InlineKeyboardButton(text=t(lang, "st_back"), callback_data="st:cats")]]))
        else:
            await message.answer(t(lang, "st_empty_scenes"))
        return
    ready = await _ready_keyframes(token, lang, chat_id)
    pages = max(1, (len(presets) + PAGE - 1) // PAGE)
    page = max(0, min(page, pages - 1))
    chunk = presets[page * PAGE:(page + 1) * PAGE]
    await message.bot.send_chat_action(chat_id, ChatAction.UPLOAD_PHOTO)
    await _send_media_group(message, [p.get("preview_poster") for p in chunk])
    lines = "\n".join(t(lang, "st_scene_line", n=i, title=esc(p.get("title")),
                        credits=_cr(lang, p.get("credits")), duration=p.get("duration"),
                        ready=" ✅" if str(p.get("id")) in ready else "")
                      for i, p in enumerate(chunk, 1))
    buttons = [InlineKeyboardButton(text=str(i), callback_data=f"st:sc:{p['id']}")
               for i, p in enumerate(chunk, 1)]
    rows = rows_of(buttons, 4)
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton(text="◀", callback_data=f"st:cat:{code}:{page - 1}"))
    if page < pages - 1:
        nav.append(InlineKeyboardButton(text="▶", callback_data=f"st:cat:{code}:{page + 1}"))
    if nav:
        rows.append(nav)
    rows.append([InlineKeyboardButton(text=t(lang, "st_back"), callback_data="st:cats"),
                 InlineKeyboardButton(text=t(lang, "st_to_timeline", n="…"), callback_data="st:tl")])
    # Заголовок раздела из каталога — та же чужая строка, что и названия сцен.
    await message.answer(t(lang, "st_scenes", category=esc(title), page=page + 1, pages=pages, lines=lines),
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
    caption = t(lang, "st_scene_card", title=esc(preset.get("title")),
                subtitle=esc(preset.get("subtitle") or ""),
                credits=_cr(lang, preset.get("credits")), duration=preset.get("duration"))
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
        await call.message.answer(_fail(lang, exc))
        return
    title = (scene.get("preset") or {}).get("title", "")
    # Всплывашка — обычный текст, разметку там не разбирают; сообщение — HTML.
    await call.answer(t(lang, "st_added", title=title), show_alert=False)
    await call.message.answer(
        t(lang, "st_added", title=esc(title)),
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
            await call.message.answer(_fail(lang, exc))
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
    await _note_project(chat_id, project)
    scenes = project.get("scenes") or []
    lines = "\n".join(t(lang, "st_tl_line", n=i, icon=STATUS_ICON.get(s.get("status"), "▫️"),
                        title=esc((s.get("preset") or {}).get("title", "")),
                        status=_status(lang, s.get("status", "")),
                        credits=_cr(lang, _row_price(s)))
                      for i, s in enumerate(scenes, 1)) or "—"
    ready = sum(1 for s in scenes if s.get("status") == "ready")
    pending = [s for s in scenes if s.get("status") in ("draft", "failed")]
    # Сумма — того, что спишут «Снять»: с готовым кадром сцена стоит только видео.
    prices = [_render_price(s) for s in pending]
    # Хоть у одной сцены цены нет — честной суммы тоже нет.
    pending_cost = None if None in prices else sum(prices)
    # Название проекта и имя героя пришли от человека — в HTML только через esc.
    text = t(lang, "st_timeline", title=esc(project.get("title", "")),
             hero=esc((project.get("character") or {}).get("name", "")), lines=lines,
             ready=ready, total=len(scenes), spent=project.get("credits_spent", 0))
    rows = []
    if pending:
        # Сумма — и в callback: «Снять все» сверит её со свежей (без суммы — спросит).
        tag = _price_tag(pending_cost)
        rows.append([InlineKeyboardButton(text=t(lang, "st_render_all", credits=_cr(lang, pending_cost)),
                                          callback_data=f"st:ra:{tag}" if tag else "st:ra")])
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
                                       caption=t(lang, "st_result",
                                                 title=esc(project.get("title", "")),
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
    _, scene = await _scene(token, lang, chat_id, scene_id)
    if not scene:
        return
    await _send_scene_menu(call.message, lang, scene)


async def _send_scene_menu(message: Message, lang: str, scene: dict) -> None:
    """Меню сцены: цены на кнопках — сейчас, и они же уходят в callback_data."""
    scene_id = scene.get("id")
    preset = scene.get("preset") or {}
    status = scene.get("status")
    render_price = _render_price(scene)
    new_frame_price = preset.get("credits", 0)
    rows = []
    if status in ("draft", "failed"):
        rows.append([InlineKeyboardButton(text=t(lang, "st_render", credits=_cr(lang, render_price)),
                                          callback_data=f"st:r:{scene_id}:{_price_tag(render_price)}")])
    if status in ("ready", "failed"):
        # Пересъёмка идёт по ТЕКУЩИМ настройкам мультфильма и по текущей цене —
        # она могла смениться на сайте, поэтому цена на кнопке до нажатия: с тем
        # же кадром платится только видео, новый кадр — кадр и видео. Каждая
        # кнопка в своём ряду: вдвоём в ряду Telegram обрезает хвост с ценой.
        # Хвост — какое меню видел человек: f — «ошибка», r — готовая сцена и метка
        # её ролика. Кнопки живут в чате днями: сцену с тех пор могли снять или
        # переснять (здесь же, на сайте), и старая кнопка не должна снимать второй раз.
        state = _menu_state(scene)
        rows.append([InlineKeyboardButton(
            text=t(lang, "st_retry_same", credits=_cr(lang, render_price)),
            callback_data=f"st:rt:{scene_id}:0:{_price_tag(render_price)}:{state}")])
        rows.append([InlineKeyboardButton(
            text=t(lang, "st_retry_new", credits=_cr(lang, new_frame_price)),
            callback_data=f"st:rt:{scene_id}:1:{_price_tag(new_frame_price)}:{state}")])
    rows.append([InlineKeyboardButton(text=t(lang, "st_up"), callback_data=f"st:up:{scene_id}"),
                 InlineKeyboardButton(text=t(lang, "st_down"), callback_data=f"st:dn:{scene_id}")])
    extra = [InlineKeyboardButton(text=t(lang, "st_remove"), callback_data=f"st:rm:{scene_id}")]
    if scene.get("video"):
        extra.insert(0, InlineKeyboardButton(text=t(lang, "st_download"), callback_data=f"st:sdl:{scene_id}"))
    rows.append(extra)
    rows.append([InlineKeyboardButton(text=t(lang, "btn_back"), callback_data="st:tl")])
    caption = (f"{STATUS_ICON.get(status, '▫️')} <b>{esc(preset.get('title', ''))}</b>"
               f" — {_status(lang, status)}")
    if scene.get("error"):
        # Текст ошибки приходит от генератора и может содержать что угодно.
        caption += f"\n{esc(scene['error'][:200])}"
    markup = InlineKeyboardMarkup(inline_keyboard=rows)
    frame = scene.get("keyframe") or preset.get("poster")
    if frame:
        try:
            await message.answer_photo(site_url(frame), caption=caption, parse_mode="HTML",
                                       reply_markup=markup)
            return
        except Exception:
            pass
    await message.answer(caption, parse_mode="HTML", reply_markup=markup)


def _cost(scene: dict) -> int | None:
    """Цена «Снять» числом для счёта пачки; None — цены нет."""
    price = _render_price(scene)
    if price is None:
        return None
    try:
        return int(price or 0)
    except (TypeError, ValueError):
        return 0


async def _balance(token: str, lang: str, chat_id: int) -> int | None:
    """Сколько кредитов у человека; None — если баланс узнать не удалось.

    None означает «не знаю», а не «ноль»: молча урезать очередь из-за сетевой
    осечки нельзя, пусть в таком случае решает бэкенд.
    """
    try:
        data = await api.balance(token, lang=lang, telegram_id=chat_id)
        return int((data or {}).get("balance_tokens", 0) or 0)
    except (ApiError, TypeError, ValueError):
        return None


# Итог одной заявки «Снять»: в очереди / цена выросла (409, ничего не снято) /
# сцена уже снята (409, ничего не снято) / другой отказ.
QUEUED, PRICE_CHANGED, ALREADY_SHOT, REFUSED = "queued", "price_changed", "already_shot", "refused"


async def _price_changed(message: Message, lang: str, exc: ApiError) -> None:
    """Сервер не снял: цена выросла с тех пор, как её показали. Новая цена — и меню
    сцены с ней (сцену сервер прислал в том же ответе)."""
    await message.answer(t(lang, "st_price_changed", credits=_cr(lang, exc.payload.get("credits"))))
    scene = exc.payload.get("scene")
    if isinstance(scene, dict) and scene.get("id"):
        await _send_scene_menu(message, lang, scene)


async def _already_shot(message: Message, lang: str, scene: dict | None) -> None:
    """«Снять» из старого меню, а сцена уже готова: второй раз не снимаем. Меню готовой
    сцены — с кнопками пересъёмки и их ценами на сейчас."""
    title = esc(((scene or {}).get("preset") or {}).get("title", ""))
    await message.answer(t(lang, "st_already_shot", title=title))
    if isinstance(scene, dict) and scene.get("id"):
        await _send_scene_menu(message, lang, scene)


async def _render(call: CallbackQuery, token: str, lang: str, scene_id: int, *,
                  quoted: int | None = None, quiet: bool = False) -> str:
    chat_id = _tid(call)
    try:
        scene = await api.render_scene(token, scene_id, quoted_credits=quoted, lang=lang, telegram_id=chat_id)
    except ApiError as exc:
        if exc.status == 402:
            await call.message.answer(
                t(lang, "st_paywall_studio", need=exc.payload.get("required", "?"),
                  have=exc.payload.get("balance", 0)),
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
                    InlineKeyboardButton(text=t(lang, "btn_topup"), callback_data="b:topup")]]))
        elif exc.code == "price_changed":
            if not quiet:
                await _price_changed(call.message, lang, exc)
            return PRICE_CHANGED
        elif exc.code == "already_shot":
            # Старая кнопка «Снять», а сцену уже сняли (здесь же или на сайте):
            # сервер не переснял и не списал — показываем готовую сцену.
            if not quiet:
                await _already_shot(call.message, lang, exc.payload.get("scene"))
            return ALREADY_SHOT
        elif not quiet:
            await call.message.answer(_fail(lang, exc))
        return REFUSED
    if not quiet:
        await call.message.answer(
            t(lang, "st_rendering", title=esc((scene.get("preset") or {}).get("title", ""))))
    return QUEUED


async def _priceless_button(call: CallbackQuery, lang: str, scene: dict | None, price) -> None:
    """Кнопка «Снять» без цены: старая (до сверки цен) или цены тогда не было.

    Снимать вслепую нельзя: цена зависит от настроек мультфильма, их меняют и на
    сайте. Показываем меню сцены с ценой на сейчас — снимет следующее нажатие.
    """
    if scene is None:
        await call.message.answer(t(lang, "failed"))
    elif scene.get("status") in BUSY_STATUSES:
        await call.message.answer(
            t(lang, "st_already_rendering", title=esc((scene.get("preset") or {}).get("title", ""))))
    elif price is None:
        # Цены нет и сейчас — снимать сервер не станет, меню было бы кругом.
        await call.message.answer(t(lang, "st_no_price_render"))
    else:
        await call.message.answer(t(lang, "st_price_check"))
        await _send_scene_menu(call.message, lang, scene)


@router.callback_query(F.data.startswith("st:r:"))
async def render(call: CallbackQuery, token: str, lang: str) -> None:
    await call.answer()
    parts = call.data.split(":")
    scene_id = int(parts[2])
    quoted = _quoted(parts[3] if len(parts) > 3 else None)
    if quoted is None:
        _, scene = await _scene(token, lang, _tid(call), scene_id)
        if scene is not None and scene.get("status") == "ready":
            await _already_shot(call.message, lang, scene)
            return
        await _priceless_button(call, lang, scene, _render_price(scene) if scene else None)
        return
    await _render(call, token, lang, scene_id, quoted=quoted)


@router.callback_query((F.data == "st:ra") | F.data.startswith("st:ra:"))
async def render_all(call: CallbackQuery, token: str, lang: str) -> None:
    chat_id = _tid(call)
    parts = call.data.split(":")
    # Сумма с кнопки «Снять все (N)»; нет — кнопка старая или суммы тогда не было.
    label = _quoted(parts[2] if len(parts) > 2 else None)
    await call.answer()
    project_id = await _project_id(chat_id)
    if not project_id:
        return
    try:
        project = await api.project(token, project_id, lang=lang, telegram_id=chat_id)
    except ApiError:
        await call.message.answer(t(lang, "server_down"))
        return
    pending = [s for s in project.get("scenes") or [] if s.get("status") in ("draft", "failed")]
    # Сцену без цены (режим «наценка», себестоимость модели неизвестна) сервер не
    # снимет. В пачку её не берём — её отказ обрывал бы очередь остальных, — а
    # почему она осталась, говорим в конце.
    unpriced = [s for s in pending if _cost(s) is None]
    pending = [s for s in pending if _cost(s) is not None]
    need = sum(_cost(s) or 0 for s in pending)
    if pending and (label is None or need > label):
        # Сумма на кнопке устарела (настройки мультфильма сменили на сайте) или её
        # не было: всю пачку вслепую не снимаем — называем сумму сейчас и ждём «да».
        # Дешевле, чем на кнопке, — снимаем сразу: это в пользу человека.
        key = "st_render_all_confirm" if label is None else "st_render_all_changed"
        await call.message.answer(
            t(lang, key, credits=_cr(lang, need), was=_cr(lang, label)),
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text=t(lang, "st_render_all_ok", credits=_cr(lang, need)),
                                      callback_data=f"st:ra:{need}")],
                [InlineKeyboardButton(text=t(lang, "st_no"), callback_data="st:tl")]]))
        return
    # Бэкенд сверяет КАЖДУЮ сцену с одним и тем же, ещё не уменьшенным балансом,
    # поэтому при нехватке он принимает всю пачку, а часть сцен падает уже
    # после генерации — деньги за них человек считает потраченными зря. Считаем
    # сумму заранее и ставим в очередь ровно то, на что хватает.
    have = await _balance(token, lang, chat_id)
    paywalled = have is not None and have < need
    if paywalled:
        # Здесь {need} — сумма за ВСЕ не снятые сцены, а не за одну: обычный
        # пейвол студии сказал бы «сцена стоит 90 кр» и назвал бы цену впятеро
        # выше настоящей.
        await call.message.answer(
            t(lang, "st_paywall_studio_all", need=need, have=have),
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
                InlineKeyboardButton(text=t(lang, "btn_topup"), callback_data="b:topup")]]))
        affordable, left = [], have
        for scene in pending:
            cost = _cost(scene) or 0
            if cost > left:
                break
            left -= cost
            affordable.append(scene)
        pending = affordable
    queued = skipped = 0
    outcome = QUEUED
    for scene in pending:
        # Каждая сцена — со своей ценой из того же ответа, что и сумма выше.
        outcome = await _render(call, token, lang, scene["id"], quoted=_cost(scene), quiet=True)
        if outcome == ALREADY_SHOT:
            # Сцену успели снять между ответом и заявкой (сайт, второе нажатие): это
            # не сбой и не повод останавливать остальные — её просто не трогаем.
            skipped += 1
            continue
        if outcome != QUEUED:
            break
        queued += 1
    if queued:
        await call.message.answer(t(lang, "st_render_all_done", n=queued))
    if outcome == PRICE_CHANGED:
        # Цена сцены выросла между ответом и заявкой: остальные не ставим, а ленту —
        # с новыми ценами и новой суммой на «Снять все».
        await call.message.answer(t(lang, "st_render_all_stopped"))
        await show_timeline(call.message, token, lang)
    elif skipped and not queued and outcome == ALREADY_SHOT:
        # Снимать оказалось нечего: молчать нельзя, «не получилось» — неправда.
        await show_timeline(call.message, token, lang)
    elif outcome == REFUSED and not queued and pending and not paywalled:
        # «Поставил в очередь: 0» после пейвола — издевательство: человеку уже
        # сказали, что денег не хватает. А вот молча проглотить сбой нельзя:
        # тихие попытки _render ничего не показывают сами.
        # Пустой pending — это не сбой: кнопка живёт в старом сообщении, и
        # второе нажатие приходит, когда снимать уже нечего. Сказать там «не
        # получилось» — соврать про деньги, которые как раз списались.
        await call.message.answer(t(lang, "failed"))
    if unpriced:
        await call.message.answer(t(lang, "st_no_price_render"))


@router.callback_query(F.data.startswith("st:rt:"))
async def retry_scene(call: CallbackQuery, token: str, lang: str) -> None:
    chat_id = _tid(call)
    parts = call.data.split(":")
    scene_id = int(parts[2])
    new_frame = len(parts) > 3 and parts[3] == "1"
    # Цена с кнопки (st:rt:<id>:<0|1>:<цена>:<меню>); у старых кнопок её нет.
    quoted = _quoted(parts[4] if len(parts) > 4 else None)
    # Какое меню видел человек: «ошибка» (f) или готовая сцена с меткой ролика (r…).
    seen, seen_shot = _menu_seen(parts[5] if len(parts) > 5 else None)
    await call.answer()
    # Кнопки остаются в старом сообщении, поэтому «Переснять» легко нажать
    # дважды: первый запрос уже поставил задачу, второй поставил бы ещё одну и
    # человек заплатил бы дважды за один результат. Сверяемся со свежим статусом.
    _, fresh = await _scene(token, lang, chat_id, scene_id)
    if fresh is not None and fresh.get("status") in BUSY_STATUSES:
        await call.message.answer(
            t(lang, "st_already_rendering", title=esc((fresh.get("preset") or {}).get("title", ""))))
        return
    if quoted is None or seen is None:
        # Без цены — старая кнопка; с ценой, но без хвоста меню — кнопка сборки, где
        # меню ещё не помечалось, или меню готовой сцены без метки ролика. Вслепую не
        # снимаем: готовую сцену — «уже снята», остальное — меню с ценой на сейчас.
        if quoted is not None and fresh is not None and fresh.get("status") == "ready":
            await _already_shot(call.message, lang, fresh)
            return
        price = None
        if fresh is not None:
            price = (fresh.get("preset") or {}).get("credits") if new_frame else _render_price(fresh)
        await _priceless_button(call, lang, fresh, price)
        return
    if fresh is not None and (fresh.get("status") != seen
                              or (seen_shot and fresh.get("shot_token") not in (None, seen_shot))):
        # Меню «ошибки», а сцену с тех пор сняли; меню готовой сцены, а её с тех пор
        # пересняли (этой же кнопкой, на сайте) или пересъёмка не удалась. Сервер
        # отказал бы и сам — сказать об этом можно и без запроса.
        await _stale_scene(call.message, lang, fresh)
        return
    body = {"retry": True, "new_keyframe": new_frame, "quoted_credits": quoted, "expect_status": seen}
    if seen_shot:
        body["expect_shot"] = seen_shot
    try:
        scene = await api.patch_scene(token, scene_id, body, lang=lang, telegram_id=chat_id)
    except ApiError as exc:
        if exc.code == "price_changed":
            await _price_changed(call.message, lang, exc)
        elif exc.code in ("already_shot", "scene_changed"):
            await _stale_scene(call.message, lang, exc.payload.get("scene"))
        else:
            await call.message.answer(_fail(lang, exc))
        return
    await call.message.answer(
        t(lang, "st_rendering", title=esc((scene.get("preset") or {}).get("title", ""))))


async def _swap_scene(token: str, lang: str, chat_id: int, project: dict, scene_id: int,
                      step: int) -> bool:
    """Поменять сцену местами с соседом по ленте.

    Бэкенд по PATCH просто записывает присланный order этой сцене и никого не
    двигает, а лента сортируется по (order, id). Поэтому абсолютный order±1 либо
    давал двум сценам одинаковый номер (и лента оставалась как была), либо
    перепрыгивал сцену, не сдвигая её. Переставляем сами: строим ленту такой,
    какой человек ждёт её увидеть, и раздаём order по позициям.

    Номера именно РАЗДАЁМ, а не обмениваем: старый баг оставил в проектах сцены
    с одинаковым order, и обмен двух равных значений сдвигал заодно чужие сцены
    (при трёх нулях «Позже» на второй сцене уносило четвёртую в середину).
    Запрос уходит только к тем, у кого номер разошёлся с позицией, — в здоровой
    ленте это ровно двое, своя сцена и сосед.
    """
    def order_of(scene: dict) -> int:
        try:
            return int(scene.get("order") or 0)
        except (TypeError, ValueError):
            return -1  # номер испорчен — перепишем в любом случае

    scenes = project.get("scenes") or []
    index = next((i for i, s in enumerate(scenes) if s.get("id") == scene_id), -1)
    neighbour_index = index + step
    if index < 0 or not 0 <= neighbour_index < len(scenes):
        return False
    lane = list(scenes)
    lane[index], lane[neighbour_index] = lane[neighbour_index], lane[index]
    changed = [(s, position) for position, s in enumerate(lane) if order_of(s) != position]
    # Свою сцену и соседа переписываем первыми: если следующий запрос сорвётся,
    # человек увидит хотя бы тот сдвиг, о котором просил.
    first = {scene_id: 0, scenes[neighbour_index].get("id"): 1}
    changed.sort(key=lambda pair: first.get(pair[0].get("id"), 2))
    try:
        for scene, position in changed:
            await api.patch_scene(token, int(scene["id"]), {"order": position},
                                  lang=lang, telegram_id=chat_id)
    except ApiError:
        return False
    return True


@router.callback_query(F.data.startswith("st:up:") | F.data.startswith("st:dn:"))
async def move_scene(call: CallbackQuery, token: str, lang: str) -> None:
    chat_id = _tid(call)
    direction, scene_id = call.data.split(":")[1], int(call.data.split(":")[2])
    project, scene = await _scene(token, lang, chat_id, scene_id)
    await call.answer()
    if not project or not scene:
        return
    await _swap_scene(token, lang, chat_id, project, scene_id, -1 if direction == "up" else 1)
    await show_timeline(call.message, token, lang)


@router.callback_query(F.data.startswith("st:rm:"))
async def remove_scene(call: CallbackQuery, token: str, lang: str) -> None:
    chat_id = _tid(call)
    try:
        await api.delete_scene(token, int(call.data.split(":")[2]), lang=lang, telegram_id=chat_id)
    except ApiError as exc:
        # 404 — сцены уже нет, это тот же успех. Остальное (например, сцена
        # ещё снимается и сервер её не отдаёт) — честно говорим, а не «удалено».
        if exc.status != 404:
            await call.answer()
            await call.message.answer(_fail(lang, exc))
            return
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
        await call.message.answer(_fail(lang, exc))
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
        t(lang, "st_delete_confirm", title=esc(project.get("title", ""))),
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
        except ApiError as exc:
            if exc.status != 404:
                # Мультфильм снимается или склеивается — сервер его не удалил.
                await call.message.answer(_fail(lang, exc))
                return
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
