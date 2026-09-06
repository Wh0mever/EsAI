"""Профиль и всё вокруг: язык, уведомления, привязка, переводы, память, поддержка."""
from __future__ import annotations

import logging
import re

from aiogram import F, Router
from aiogram.filters import Command, CommandObject
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from bot.config import settings
from bot.keyboards.common import language_choice, main_menu, more_menu, rows_of
from bot.services.api import ApiError, api
from bot.services.state import store
from bot.texts import register_texts, t

logger = logging.getLogger(__name__)
router = Router(name="account")

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
NOTIFY_FLAGS = ("notify_bonus", "notify_ready", "notify_topup", "notify_referral", "notify_marketing")

register_texts({
    "ru": {
        "profile": ("👤 <b>Профиль</b>\n"
                    "Имя: {name}\nID для переводов: <code>{id}</code>\n"
                    "Почта: {email}\nТариф: {tier}\nБаланс: {balance} кр\n"
                    "Telegram: {linked}"),
        "profile_linked": "привязан к аккаунту сайта", "profile_stub": "аккаунт создан из бота",
        "btn_name": "✏️ Имя", "btn_link": "🔗 Связать с аккаунтом сайта", "btn_lang": "🌐 Язык",
        "btn_notify": "🔔 Уведомления", "btn_memory": "🧠 Память", "btn_inbox": "📥 Уведомления сайта",
        "btn_feedback": "⭐ Оставить отзыв", "btn_support": "🆘 Поддержка", "btn_delete": "🗑 Удалить данные",
        "name_ask": "Как вас называть? Напишите имя.", "name_saved": "Готово: {name}.",
        "notify_title": "🔔 <b>Уведомления в Telegram</b>\nНажмите, чтобы включить или выключить:",
        "notify_bonus": "🎁 Ежедневный бонус", "notify_ready": "🎬 Готовность видео и мультфильмов",
        "notify_topup": "💳 Пополнение баланса", "notify_referral": "🤝 Реферальные начисления",
        "notify_marketing": "📣 Новости и акции",
        "inbox_empty": "Новых уведомлений нет.", "inbox_title": "📥 <b>Уведомления</b>",
        "link_intro": ("🔗 <b>Связать с аккаунтом сайта</b>\n"
                       "Введите почту, которой входите на esai.kg. Пришлём код, а после проверки "
                       "объединим аккаунты: чаты, мультфильмы и купленные кредиты переедут в один."),
        "link_bad_email": "Похоже, это не почта. Попробуйте ещё раз.",
        "link_code_sent": "Код отправлен на {email}. Введите его сюда.",
        "link_code_bad": "Код не подошёл: {reason}",
        "link_done_linked": "✅ Готово: этот Telegram привязан к аккаунту {email}.",
        "link_done_merged": "✅ Аккаунты объединены. Теперь и на сайте, и в боте — один баланс.",
        "link_done_already": "Этот Telegram уже привязан к аккаунту {email}.",
        "link_fail_paid": ("Не получилось объединить: у аккаунта из бота есть платежи. "
                           "Напишите в поддержку — разберём вручную."),
        "link_fail": "Не получилось связать: {reason}",
        "link_already": "Этот Telegram уже связан с аккаунтом сайта.",
        "link_deep_ok": "✅ Telegram привязан к вашему аккаунту сайта. Баланс и чаты общие.",
        "link_deep_merged": "✅ Аккаунты объединены: всё из бота переехало в аккаунт сайта.",
        "link_deep_bad": "Ссылка для привязки устарела. Откройте профиль на сайте и создайте новую.",
        "transfer_intro": ("💸 <b>Перевод кредитов</b>\n"
                           "Кому переводим? Введите почту, логин или ID получателя (он виден в /profile)."),
        "transfer_amount": "Сколько кредитов перевести? На балансе {balance}.",
        "transfer_bad_amount": "Введите целое число не меньше 1.",
        "transfer_comment": "Комментарий получателю (или «-», чтобы без него):",
        "transfer_confirm": ("Перевести <b>{amount} кредитов</b> → <b>{to}</b>?\n"
                             "Без комиссии, отменить нельзя."),
        "transfer_go": "✅ Перевести", "transfer_done": "✅ Переведено {amount} кр. Баланс: {balance}.",
        "transfer_fail": "Не переведено: {reason}",
        "memory_title": "🧠 <b>Память</b> ({state})\n{lines}",
        "memory_on": "включена", "memory_off": "выключена", "memory_empty": "Пока ничего не запомнил. Напишите «запомни …».",
        "memory_toggle_off": "🔕 Выключить память", "memory_toggle_on": "🔔 Включить память",
        "memory_clear": "🧹 Очистить всё", "memory_del": "🗑 {n}", "memory_cleared": "Память очищена.",
        "memory_clear_confirm": "Удалить все факты из памяти?",
        "support_ask": "Опишите вопрос одним сообщением — ответим здесь.",
        "support_sent": "Спасибо, обращение №{id} принято. Ответим в ближайшее время.",
        "support_short": "Слишком коротко — напишите чуть подробнее (от 10 символов).",
        "feedback_ask": "Как вам EsAI? Оцените от 1 до 5:",
        "feedback_text": "Спасибо! Напишите пару слов — что понравилось или что улучшить (или «-»).",
        "feedback_sent": "⭐ Спасибо за отзыв!",
        "faq_title": "❓ <b>Частые вопросы</b>",
        "faq": [
            ("Что такое кредиты?", "Единая валюта EsAI: за них работают чат, картинки, видео и студия. Не сгорают."),
            ("Как пополнить в боте?", "Кнопка «Пополнить» → пакет → оплата Telegram Stars. На сайте — картой, Элкарт или криптой; аккаунт общий."),
            ("Почему модель заблокирована?", "Премиум-модели доступны после первой покупки любого пакета. Бесплатные — всегда."),
            ("Аккаунт в боте и на сайте один?", "Да, если на сайте входить через Telegram. Другой аккаунт можно привязать: Профиль → «Связать с аккаунтом сайта»."),
            ("Как вернуть деньги?", "В течение 14 дней, если кредиты не потрачены: /paysupport."),
            ("Сколько стоит видео?", "Цена за секунду у каждой модели своя — она показана до запуска. Списание только за готовый ролик."),
            ("Как удалить данные?", "Команда /delete отвяжет Telegram и отключит аккаунт, созданный из бота."),
        ],
        "blog_title": "📰 <b>Блог EsAI</b>", "blog_empty": "Статей пока нет.",
        "delete_confirm": ("🗑 <b>Удалить данные</b>\nОтвяжем Telegram от аккаунта. Если аккаунт создан "
                           "только из бота, он будет отключён. Продолжить?"),
        "delete_yes": "🗑 Да, удалить", "delete_done": "Готово. Следующий /start заведёт чистый аккаунт.",
        "lang_pick": "🌐 Выберите язык:",
        "cancelled": "Отменено.",
    },
    "en": {
        "profile": ("👤 <b>Profile</b>\n"
                    "Name: {name}\nID for transfers: <code>{id}</code>\n"
                    "Email: {email}\nPlan: {tier}\nBalance: {balance} cr\n"
                    "Telegram: {linked}"),
        "profile_linked": "linked to a site account", "profile_stub": "account created from the bot",
        "btn_name": "✏️ Name", "btn_link": "🔗 Link site account", "btn_lang": "🌐 Language",
        "btn_notify": "🔔 Notifications", "btn_memory": "🧠 Memory", "btn_inbox": "📥 Site notifications",
        "btn_feedback": "⭐ Leave feedback", "btn_support": "🆘 Support", "btn_delete": "🗑 Delete data",
        "name_ask": "What should I call you? Type a name.", "name_saved": "Done: {name}.",
        "notify_title": "🔔 <b>Telegram notifications</b>\nTap to toggle:",
        "notify_bonus": "🎁 Daily bonus", "notify_ready": "🎬 Video and cartoon ready",
        "notify_topup": "💳 Balance top-ups", "notify_referral": "🤝 Referral rewards",
        "notify_marketing": "📣 News and offers",
        "inbox_empty": "No new notifications.", "inbox_title": "📥 <b>Notifications</b>",
        "link_intro": ("🔗 <b>Link a site account</b>\n"
                       "Enter the email you use at esai.kg. We will send a code; after checking it "
                       "the accounts merge: chats, cartoons and purchased credits move into one."),
        "link_bad_email": "That does not look like an email. Try again.",
        "link_code_sent": "Code sent to {email}. Enter it here.",
        "link_code_bad": "Code rejected: {reason}",
        "link_done_linked": "✅ Done: this Telegram is linked to {email}.",
        "link_done_merged": "✅ Accounts merged. Site and bot now share one balance.",
        "link_done_already": "This Telegram is already linked to {email}.",
        "link_fail_paid": ("Could not merge: the bot account has payments. "
                           "Contact support — we will sort it out manually."),
        "link_fail": "Could not link: {reason}",
        "link_already": "This Telegram is already linked to a site account.",
        "link_deep_ok": "✅ Telegram linked to your site account. Balance and chats are shared.",
        "link_deep_merged": "✅ Accounts merged: everything from the bot moved to the site account.",
        "link_deep_bad": "The link has expired. Open your profile on the site and create a new one.",
        "transfer_intro": ("💸 <b>Transfer credits</b>\n"
                           "To whom? Enter the recipient's email, username or ID (shown in /profile)."),
        "transfer_amount": "How many credits? Your balance is {balance}.",
        "transfer_bad_amount": "Enter a whole number, at least 1.",
        "transfer_comment": "A note for the recipient (or “-” for none):",
        "transfer_confirm": ("Transfer <b>{amount} credits</b> → <b>{to}</b>?\n"
                             "No fee, cannot be undone."),
        "transfer_go": "✅ Transfer", "transfer_done": "✅ Sent {amount} cr. Balance: {balance}.",
        "transfer_fail": "Not sent: {reason}",
        "memory_title": "🧠 <b>Memory</b> ({state})\n{lines}",
        "memory_on": "on", "memory_off": "off", "memory_empty": "Nothing remembered yet. Say “remember …”.",
        "memory_toggle_off": "🔕 Turn memory off", "memory_toggle_on": "🔔 Turn memory on",
        "memory_clear": "🧹 Clear all", "memory_del": "🗑 {n}", "memory_cleared": "Memory cleared.",
        "memory_clear_confirm": "Delete all facts from memory?",
        "support_ask": "Describe your question in one message — we will answer here.",
        "support_sent": "Thanks, request #{id} received. We will reply soon.",
        "support_short": "Too short — please add some detail (10+ characters).",
        "feedback_ask": "How do you like EsAI? Rate from 1 to 5:",
        "feedback_text": "Thanks! A few words — what you liked or what to improve (or “-”).",
        "feedback_sent": "⭐ Thank you for the feedback!",
        "faq_title": "❓ <b>FAQ</b>",
        "faq": [
            ("What are credits?", "EsAI's single currency for chat, images, video and the studio. They never expire."),
            ("How do I top up in the bot?", "“Top up” → package → Telegram Stars. On the site — card or crypto; one shared account."),
            ("Why is a model locked?", "Premium models unlock after the first purchase of any package. Free ones are always available."),
            ("Is the account the same as on the site?", "Yes, if you sign in on the site via Telegram. Another account can be linked: Profile → “Link site account”."),
            ("How do refunds work?", "Within 14 days if the credits are unused: /paysupport."),
            ("How much does video cost?", "Each model has its own per-second price shown before you start. Charged only for a finished clip."),
            ("How do I delete my data?", "/delete unlinks Telegram and deactivates an account created from the bot."),
        ],
        "blog_title": "📰 <b>EsAI blog</b>", "blog_empty": "No articles yet.",
        "delete_confirm": ("🗑 <b>Delete data</b>\nWe will unlink Telegram from the account. An account created "
                           "only from the bot will be deactivated. Continue?"),
        "delete_yes": "🗑 Yes, delete", "delete_done": "Done. The next /start creates a fresh account.",
        "lang_pick": "🌐 Choose a language:",
        "cancelled": "Cancelled.",
    },
    "kg": {
        "profile": ("👤 <b>Профиль</b>\n"
                    "Аты: {name}\nКоторуу үчүн ID: <code>{id}</code>\n"
                    "Почта: {email}\nТариф: {tier}\nБаланс: {balance} кр\n"
                    "Telegram: {linked}"),
        "profile_linked": "сайт аккаунтуна байланышкан", "profile_stub": "аккаунт боттон түзүлгөн",
        "btn_name": "✏️ Аты", "btn_link": "🔗 Сайт аккаунту менен байланыштыруу", "btn_lang": "🌐 Тил",
        "btn_notify": "🔔 Билдирүүлөр", "btn_memory": "🧠 Эс", "btn_inbox": "📥 Сайт билдирүүлөрү",
        "btn_feedback": "⭐ Пикир калтыруу", "btn_support": "🆘 Колдоо", "btn_delete": "🗑 Маалыматты өчүрүү",
        "name_ask": "Сизди кантип атайлы? Атыңызды жазыңыз.", "name_saved": "Даяр: {name}.",
        "notify_title": "🔔 <b>Telegram билдирүүлөрү</b>\nКүйгүзүү же өчүрүү үчүн басыңыз:",
        "notify_bonus": "🎁 Күнүмдүк бонус", "notify_ready": "🎬 Видео жана мультфильм даярдыгы",
        "notify_topup": "💳 Балансты толуктоо", "notify_referral": "🤝 Реферал сыйлыктары",
        "notify_marketing": "📣 Жаңылыктар жана акциялар",
        "inbox_empty": "Жаңы билдирүү жок.", "inbox_title": "📥 <b>Билдирүүлөр</b>",
        "link_intro": ("🔗 <b>Сайт аккаунту менен байланыштыруу</b>\n"
                       "esai.kg сайтына кирген почтаңызды жазыңыз. Код жөнөтөбүз, текшерүүдөн кийин "
                       "аккаунттар биригет: чаттар, мультфильмдер жана сатып алынган кредиттер бирге болот."),
        "link_bad_email": "Бул почтага окшобойт. Кайра аракет кылыңыз.",
        "link_code_sent": "Код {email} дарегине жөнөтүлдү. Ушул жерге жазыңыз.",
        "link_code_bad": "Код туура эмес: {reason}",
        "link_done_linked": "✅ Даяр: бул Telegram {email} аккаунтуна байланышты.",
        "link_done_merged": "✅ Аккаунттар бириктирилди. Эми сайтта да, ботто да — бир баланс.",
        "link_done_already": "Бул Telegram мурда эле {email} аккаунтуна байланышкан.",
        "link_fail_paid": ("Бириктирүү мүмкүн эмес: боттогу аккаунтта төлөмдөр бар. "
                           "Колдоо кызматына жазыңыз."),
        "link_fail": "Байланыштыруу мүмкүн болгон жок: {reason}",
        "link_already": "Бул Telegram мурда эле сайт аккаунтуна байланышкан.",
        "link_deep_ok": "✅ Telegram сайт аккаунтуңузга байланышты. Баланс жана чаттар жалпы.",
        "link_deep_merged": "✅ Аккаунттар бириктирилди.",
        "link_deep_bad": "Шилтеме эскирди. Сайттагы профилден жаңысын түзүңүз.",
        "transfer_intro": ("💸 <b>Кредит которуу</b>\n"
                           "Кимге? Алуучунун почтасын, логинин же ID-син жазыңыз (/profile ичинде көрүнөт)."),
        "transfer_amount": "Канча кредит которобуз? Балансыңызда {balance}.",
        "transfer_bad_amount": "1ден кем эмес бүтүн сан жазыңыз.",
        "transfer_comment": "Алуучуга комментарий (же «-»):",
        "transfer_confirm": ("<b>{amount} кредит</b> → <b>{to}</b> которобузбу?\n"
                             "Комиссиясыз, жокко чыгарууга болбойт."),
        "transfer_go": "✅ Которуу", "transfer_done": "✅ {amount} кр которулду. Баланс: {balance}.",
        "transfer_fail": "Которулган жок: {reason}",
        "memory_title": "🧠 <b>Эс</b> ({state})\n{lines}",
        "memory_on": "күйүк", "memory_off": "өчүк", "memory_empty": "Азырынча эч нерсе эстелген жок. «Эстеп кал …» деп жазыңыз.",
        "memory_toggle_off": "🔕 Эсти өчүрүү", "memory_toggle_on": "🔔 Эсти күйгүзүү",
        "memory_clear": "🧹 Баарын тазалоо", "memory_del": "🗑 {n}", "memory_cleared": "Эс тазаланды.",
        "memory_clear_confirm": "Эстеги бардык фактыларды өчүрөбүзбү?",
        "support_ask": "Сурооңузду бир билдирүү менен жазыңыз — ушул жерде жооп беребиз.",
        "support_sent": "Рахмат, №{id} кайрылуу кабыл алынды. Жакында жооп беребиз.",
        "support_short": "Өтө кыска — кененирээк жазыңыз (10 белгиден).",
        "feedback_ask": "EsAI сизге кандай? 1ден 5ке чейин баалаңыз:",
        "feedback_text": "Рахмат! Бир-эки сөз жазыңыз — эмне жакты же эмнени жакшыртуу керек (же «-»).",
        "feedback_sent": "⭐ Пикириңиз үчүн рахмат!",
        "faq_title": "❓ <b>Көп берилүүчү суроолор</b>",
        "faq": [
            ("Кредит деген эмне?", "EsAI бирдиктүү валютасы: чат, сүрөт, видео жана студия. Күйбөйт."),
            ("Ботто кантип толуктайм?", "«Толуктоо» → пакет → Telegram Stars. Сайтта — карта же крипто; аккаунт жалпы."),
            ("Эмне үчүн модель жабык?", "Премиум моделдер кайсы бир пакетти биринчи сатып алгандан кийин ачылат."),
            ("Ботто жана сайтта аккаунт бирби?", "Ооба, эгер сайтка Telegram аркылуу кирсеңиз. Башка аккаунтту байланыштырса болот: Профиль → «Байланыштыруу»."),
            ("Акчаны кантип кайтарам?", "Кредиттер сарпталбаса, 14 күн ичинде: /paysupport."),
            ("Видео канча турат?", "Ар бир моделде секундасына өз баасы бар — башталганга чейин көрсөтүлөт."),
            ("Маалыматты кантип өчүрөм?", "/delete командасы Telegram-ды ажыратып, боттон түзүлгөн аккаунтту өчүрөт."),
        ],
        "blog_title": "📰 <b>EsAI блогу</b>", "blog_empty": "Азырынча макала жок.",
        "delete_confirm": ("🗑 <b>Маалыматты өчүрүү</b>\nTelegram аккаунттан ажыратылат. Боттон гана түзүлгөн "
                           "аккаунт өчүрүлөт. Улантабызбы?"),
        "delete_yes": "🗑 Ооба, өчүрүү", "delete_done": "Даяр. Кийинки /start жаңы аккаунт түзөт.",
        "lang_pick": "🌐 Тилди тандаңыз:",
        "cancelled": "Жокко чыгарылды.",
    },
})


class AccountWizard(StatesGroup):
    name = State()
    link_email = State()
    link_code = State()
    transfer_to = State()
    transfer_amount = State()
    transfer_comment = State()
    support = State()
    feedback_text = State()


# --------------------------------------------------------------- профиль ---

async def show_profile(message: Message, token: str, lang: str) -> None:
    chat_id = message.chat.id
    try:
        profile = await api.profile(token, lang=lang, telegram_id=chat_id)
        balance = await api.balance(token, lang=lang, telegram_id=chat_id)
    except ApiError:
        await message.answer(t(lang, "server_down"))
        return
    user = profile.get("user") or {}
    email = user.get("email") or ""
    stub = email.endswith("@social.esai.local")
    tier_key = {"paid": "tier_paid", "unlimited": "tier_unlimited"}.get(balance.get("tier"), "tier_free")
    text = t(lang, "profile", name=user.get("first_name") or "—", id=user.get("id"),
             email="—" if stub else email, tier=t(lang, tier_key),
             balance=balance.get("balance_tokens", 0),
             linked=t(lang, "profile_stub" if stub else "profile_linked"))
    rows = [[InlineKeyboardButton(text=t(lang, "btn_name"), callback_data="p:name"),
             InlineKeyboardButton(text=t(lang, "btn_lang"), callback_data="more:lang")],
            [InlineKeyboardButton(text=t(lang, "btn_notify"), callback_data="more:notify"),
             InlineKeyboardButton(text=t(lang, "btn_memory"), callback_data="more:memory")],
            [InlineKeyboardButton(text=t(lang, "btn_inbox"), callback_data="p:inbox")]]
    if stub:
        rows.append([InlineKeyboardButton(text=t(lang, "btn_link"), callback_data="more:link")])
    rows.append([InlineKeyboardButton(text=t(lang, "btn_feedback"), callback_data="more:feedback"),
                 InlineKeyboardButton(text=t(lang, "btn_support"), callback_data="more:support")])
    rows.append([InlineKeyboardButton(text=t(lang, "btn_delete"), callback_data="p:delete")])
    await message.answer(text, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))


@router.message(Command("profile"))
async def cmd_profile(message: Message, token: str, lang: str = "ru") -> None:
    await show_profile(message, token, lang)


@router.callback_query(F.data == "p:name")
async def ask_name(call: CallbackQuery, lang: str, state: FSMContext) -> None:
    await state.set_state(AccountWizard.name)
    await call.answer()
    await call.message.answer(t(lang, "name_ask"))


@router.message(AccountWizard.name, F.text & ~F.text.startswith("/"))
async def save_name(message: Message, token: str, lang: str, state: FSMContext) -> None:
    await state.clear()
    name = message.text.strip()[:30]
    try:
        await api.update_profile(token, first_name=name)
    except ApiError:
        await message.answer(t(lang, "server_down"))
        return
    await message.answer(t(lang, "name_saved", name=name))


@router.callback_query(F.data == "p:inbox")
async def inbox(call: CallbackQuery, token: str, lang: str) -> None:
    await call.answer()
    try:
        rows = await api.notifications(token, lang=lang, telegram_id=call.message.chat.id)
    except ApiError:
        await call.message.answer(t(lang, "server_down"))
        return
    rows = [r for r in rows if not r.get("is_read")][:10] or rows[:5]
    if not rows:
        await call.message.answer(t(lang, "inbox_empty"))
        return
    lines = [t(lang, "inbox_title")]
    for r in rows:
        lines.append(f"• <b>{r.get('title', '')}</b>\n{(r.get('body') or '')[:300]}")
    await call.message.answer("\n\n".join(lines), parse_mode="HTML")


# ------------------------------------------------------------ «☰ Ещё» ---

@router.callback_query(F.data.startswith("more:"))
async def more(call: CallbackQuery, token: str, lang: str, state: FSMContext) -> None:
    action = call.data.split(":", 1)[1]
    await call.answer()
    message = call.message
    if action == "history":
        from bot.routers.profile import cmd_history

        await cmd_history(message, token, lang)
    elif action == "memory":
        await show_memory(message, token, lang)
    elif action == "referral":
        from bot.routers.profile import cmd_referral

        await cmd_referral(message, token, lang)
    elif action == "transfer":
        await start_transfer(message, token, lang, state)
    elif action == "promo":
        await message.answer("Введите промокод так: <code>/promo КОД</code>", parse_mode="HTML")
    elif action == "lang":
        await message.answer(t(lang, "lang_pick"), reply_markup=language_choice())
    elif action == "notify":
        await show_notify(message, lang, call.from_user.id)
    elif action == "blog":
        await show_blog(message, lang)
    elif action == "faq":
        await show_faq(message, lang)
    elif action == "support":
        await message.answer(t(lang, "support_ask"))
        await start_support(state)
    elif action == "feedback":
        await ask_feedback(message, lang)
    elif action == "link":
        await start_link(message, lang, state)


@router.message(Command("lang"))
async def cmd_lang(message: Message, lang: str = "ru") -> None:
    await message.answer(t(lang, "lang_pick"), reply_markup=language_choice())


# ---------------------------------------------------------- уведомления ---

async def show_notify(message: Message, lang: str, telegram_id: int, *, edit: bool = False) -> None:
    try:
        prefs = await api.set_prefs(telegram_id)
    except ApiError:
        await message.answer(t(lang, "server_down"))
        return
    buttons = [InlineKeyboardButton(
        text=f"{'✅' if prefs.get(flag) else '☐'} {t(lang, flag)}", callback_data=f"n:{flag}")
        for flag in NOTIFY_FLAGS]
    rows = rows_of(buttons, 1)
    rows.append([InlineKeyboardButton(text=t(lang, "btn_close"), callback_data="nav:x")])
    markup = InlineKeyboardMarkup(inline_keyboard=rows)
    if edit:
        try:
            await message.edit_reply_markup(reply_markup=markup)
            return
        except Exception:
            pass
    await message.answer(t(lang, "notify_title"), parse_mode="HTML", reply_markup=markup)


@router.message(Command("notify"))
async def cmd_notify(message: Message, lang: str = "ru") -> None:
    await show_notify(message, lang, message.from_user.id)


@router.callback_query(F.data.startswith("n:notify_"))
async def toggle_notify(call: CallbackQuery, lang: str) -> None:
    flag = call.data.split(":", 1)[1]
    if flag not in NOTIFY_FLAGS:
        await call.answer()
        return
    try:
        prefs = await api.set_prefs(call.from_user.id)
        await api.set_prefs(call.from_user.id, **{flag: not prefs.get(flag)})
    except ApiError:
        await call.answer(t(lang, "server_down"))
        return
    await call.answer()
    await show_notify(call.message, lang, call.from_user.id, edit=True)


# ------------------------------------------------------------- привязка ---

async def start_link(message: Message, lang: str, state: FSMContext) -> None:
    await state.set_state(AccountWizard.link_email)
    await message.answer(t(lang, "link_intro"), parse_mode="HTML")


@router.message(Command("link"))
async def cmd_link(message: Message, lang: str, state: FSMContext) -> None:
    await start_link(message, lang, state)


@router.message(AccountWizard.link_email, F.text & ~F.text.startswith("/"))
async def link_email(message: Message, lang: str, state: FSMContext) -> None:
    email = message.text.strip().lower()
    if not EMAIL_RE.match(email):
        await message.answer(t(lang, "link_bad_email"))
        return
    try:
        await api.signin(email, telegram_id=message.from_user.id)
    except ApiError as exc:
        await state.clear()
        await message.answer(t(lang, "link_fail", reason=exc.message or exc.code))
        return
    await state.update_data(email=email)
    await state.set_state(AccountWizard.link_code)
    await message.answer(t(lang, "link_code_sent", email=email))


@router.message(AccountWizard.link_code, F.text & ~F.text.startswith("/"))
async def link_code(message: Message, lang: str, state: FSMContext, tg_user: dict) -> None:
    data = await state.get_data()
    email = data.get("email", "")
    code = message.text.strip().replace(" ", "")
    try:
        auth = await api.signin_confirm(email, code, telegram_id=message.from_user.id)
    except ApiError as exc:
        await message.answer(t(lang, "link_code_bad", reason=exc.message or exc.code))
        return
    await state.clear()
    site_token = ((auth or {}).get("data") or {}).get("access") or ""
    if not site_token:
        await message.answer(t(lang, "link_fail", reason="no_token"))
        return
    try:
        start = await api.link_start(site_token, telegram_id=message.from_user.id)
        result = await api.link_confirm(start["code"], tg_user, chat_id=message.chat.id)
    except ApiError as exc:
        if exc.code == "already_linked":
            await message.answer(t(lang, "link_already"))
        elif exc.code == "telegram_bound_to_paid_account":
            await message.answer(t(lang, "link_fail_paid"))
        else:
            await message.answer(t(lang, "link_fail", reason=exc.message or exc.code))
        return
    await _apply_link_result(message, lang, result, email)


async def _apply_link_result(message: Message, lang: str, result: dict, email: str = "") -> None:
    """После привязки бот должен ходить от имени объединённого аккаунта."""
    chat_id = message.chat.id
    await store.set_token(chat_id, result["access"])
    for key in ("session", "models_cache", "sessions_cache", "st_project", "st_char"):
        await store.drop(chat_id, key)
    status = result.get("status")
    email = email or (result.get("user") or {}).get("email", "")
    key = {"linked": "link_done_linked", "merged": "link_done_merged"}.get(status, "link_done_already")
    await message.answer(t(lang, key, email=email), reply_markup=main_menu(lang))


async def link_from_deep_link(message: Message, lang: str, code: str, tg_user: dict) -> None:
    """/start link_<код> с сайта."""
    try:
        result = await api.link_confirm(code, tg_user, chat_id=message.chat.id)
    except ApiError as exc:
        if exc.code == "telegram_bound_to_paid_account":
            await message.answer(t(lang, "link_fail_paid"))
        elif exc.code == "already_linked":
            await message.answer(t(lang, "link_already"))
        else:
            await message.answer(t(lang, "link_deep_bad"))
        return
    chat_id = message.chat.id
    await store.set_token(chat_id, result["access"])
    for key in ("session", "models_cache", "sessions_cache", "st_project", "st_char"):
        await store.drop(chat_id, key)
    key = "link_deep_merged" if result.get("status") == "merged" else "link_deep_ok"
    await message.answer(t(lang, key), reply_markup=main_menu(lang))


# -------------------------------------------------------------- перевод ---

async def start_transfer(message: Message, token: str, lang: str, state: FSMContext) -> None:
    await state.set_state(AccountWizard.transfer_to)
    await message.answer(t(lang, "transfer_intro"), parse_mode="HTML")


@router.message(Command("transfer"))
async def cmd_transfer(message: Message, token: str, lang: str, state: FSMContext) -> None:
    await start_transfer(message, token, lang, state)


@router.message(AccountWizard.transfer_to, F.text & ~F.text.startswith("/"))
async def transfer_to(message: Message, token: str, lang: str, state: FSMContext) -> None:
    await state.update_data(to=message.text.strip()[:150])
    try:
        balance = (await api.balance(token, lang=lang, telegram_id=message.chat.id)).get("balance_tokens", 0)
    except ApiError:
        balance = "—"
    await state.set_state(AccountWizard.transfer_amount)
    await message.answer(t(lang, "transfer_amount", balance=balance))


@router.message(AccountWizard.transfer_amount, F.text & ~F.text.startswith("/"))
async def transfer_amount(message: Message, lang: str, state: FSMContext) -> None:
    raw = message.text.strip().replace(" ", "")
    if not raw.isdigit() or int(raw) < 1:
        await message.answer(t(lang, "transfer_bad_amount"))
        return
    await state.update_data(amount=int(raw))
    await state.set_state(AccountWizard.transfer_comment)
    await message.answer(t(lang, "transfer_comment"))


@router.message(AccountWizard.transfer_comment, F.text & ~F.text.startswith("/"))
async def transfer_comment(message: Message, lang: str, state: FSMContext) -> None:
    comment = message.text.strip()
    comment = "" if comment in ("-", "—") else comment[:200]
    await state.update_data(comment=comment)
    data = await state.get_data()
    await state.set_state(None)
    await message.answer(
        t(lang, "transfer_confirm", amount=data["amount"], to=data["to"]), parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text=t(lang, "transfer_go"), callback_data="tr:go"),
            InlineKeyboardButton(text=t(lang, "btn_close"), callback_data="tr:x")]]))


@router.callback_query(F.data == "tr:go")
async def transfer_go(call: CallbackQuery, token: str, lang: str, state: FSMContext) -> None:
    data = await state.get_data()
    await state.clear()
    await call.answer()
    if not data.get("to") or not data.get("amount"):
        return
    try:
        await call.message.edit_reply_markup(reply_markup=None)
    except Exception:
        pass
    try:
        result = await api.transfer(token, data["to"], int(data["amount"]), data.get("comment", ""),
                                    lang=lang, telegram_id=call.message.chat.id)
    except ApiError as exc:
        await call.message.answer(t(lang, "transfer_fail", reason=exc.message or exc.code))
        return
    await call.message.answer(t(lang, "transfer_done", amount=data["amount"],
                                balance=result.get("balance", "—")))


@router.callback_query(F.data == "tr:x")
async def transfer_cancel(call: CallbackQuery, lang: str, state: FSMContext) -> None:
    await state.clear()
    await call.answer(t(lang, "cancelled"))
    try:
        await call.message.delete()
    except Exception:
        pass


# --------------------------------------------------------------- память ---

async def show_memory(message: Message, token: str, lang: str, *, edit: bool = False) -> None:
    try:
        data = await api.memory(token, lang=lang, telegram_id=message.chat.id)
    except ApiError:
        await message.answer(t(lang, "server_down"))
        return
    items = data.get("items") or []
    enabled = bool(data.get("memory_enabled", True))
    lines = "\n".join(f"{i}. {m.get('content', '')[:120]}" for i, m in enumerate(items[:20], 1)) \
        or t(lang, "memory_empty")
    rows = []
    if items:
        rows += rows_of([InlineKeyboardButton(text=t(lang, "memory_del", n=i),
                                              callback_data=f"mem:del:{m['id']}")
                         for i, m in enumerate(items[:20], 1)], 5)
        rows.append([InlineKeyboardButton(text=t(lang, "memory_clear"), callback_data="mem:clear")])
    rows.append([InlineKeyboardButton(
        text=t(lang, "memory_toggle_off" if enabled else "memory_toggle_on"), callback_data="mem:toggle")])
    rows.append([InlineKeyboardButton(text=t(lang, "btn_close"), callback_data="nav:x")])
    text = t(lang, "memory_title", state=t(lang, "memory_on" if enabled else "memory_off"), lines=lines)
    markup = InlineKeyboardMarkup(inline_keyboard=rows)
    if edit:
        try:
            await message.edit_text(text, parse_mode="HTML", reply_markup=markup)
            return
        except Exception:
            pass
    await message.answer(text, parse_mode="HTML", reply_markup=markup)


@router.message(Command("memory"))
async def cmd_memory(message: Message, token: str, lang: str = "ru") -> None:
    await show_memory(message, token, lang)


@router.callback_query(F.data.startswith("mem:"))
async def memory_action(call: CallbackQuery, token: str, lang: str) -> None:
    parts = call.data.split(":")
    action = parts[1]
    chat_id = call.message.chat.id
    try:
        if action == "del":
            await api.memory_delete(token, int(parts[2]), lang=lang, telegram_id=chat_id)
        elif action == "toggle":
            data = await api.memory(token, lang=lang, telegram_id=chat_id)
            await api.memory_toggle(token, not bool(data.get("memory_enabled", True)),
                                    lang=lang, telegram_id=chat_id)
        elif action == "clear":
            await call.answer()
            await call.message.answer(t(lang, "memory_clear_confirm"), reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[[InlineKeyboardButton(text="🧹 OK", callback_data="mem:clearok"),
                                  InlineKeyboardButton(text=t(lang, "btn_close"), callback_data="nav:x")]]))
            return
        elif action == "clearok":
            await api.memory_clear(token, lang=lang, telegram_id=chat_id)
            await call.answer(t(lang, "memory_cleared"))
            await show_memory(call.message, token, lang)
            return
    except ApiError:
        await call.answer(t(lang, "server_down"))
        return
    await call.answer()
    await show_memory(call.message, token, lang, edit=True)


# ------------------------------------------------------------ поддержка ---

async def start_support(state: FSMContext, topic: str = "general") -> None:
    await state.set_state(AccountWizard.support)
    await state.update_data(topic=topic)


@router.message(Command("support"))
async def cmd_support(message: Message, lang: str, state: FSMContext) -> None:
    await message.answer(t(lang, "support_ask"))
    await start_support(state)


@router.message(AccountWizard.support, F.text & ~F.text.startswith("/"))
async def support_text(message: Message, token: str, lang: str, state: FSMContext, tg_user: dict) -> None:
    text = message.text.strip()
    if len(text) < 10:
        await message.answer(t(lang, "support_short"))
        return
    data = await state.get_data()
    await state.clear()
    try:
        profile = await api.profile(token, lang=lang, telegram_id=message.chat.id)
        email = (profile.get("user") or {}).get("email") or ""
    except ApiError:
        email = ""
    who = f"@{tg_user.get('username')}" if tg_user.get("username") else f"tg:{tg_user.get('id')}"
    body = f"[Telegram {who}, тема: {data.get('topic', 'general')}]\n{text}"
    try:
        result = await api.question(email or f"tg_{tg_user.get('id')}@social.esai.local",
                                    tg_user.get("first_name") or who, body[:4000])
    except ApiError:
        await message.answer(t(lang, "server_down"))
        return
    await message.answer(t(lang, "support_sent", id=(result or {}).get("id", "")))


# ---------------------------------------------------------------- отзыв ---

async def ask_feedback(message: Message, lang: str) -> None:
    stars = [InlineKeyboardButton(text="⭐" * n, callback_data=f"fb:{n}") for n in range(1, 6)]
    await message.answer(t(lang, "feedback_ask"),
                         reply_markup=InlineKeyboardMarkup(inline_keyboard=rows_of(stars, 5)))


@router.message(Command("feedback"))
async def cmd_feedback(message: Message, lang: str = "ru") -> None:
    await ask_feedback(message, lang)


@router.callback_query(F.data.startswith("fb:"))
async def feedback_rating(call: CallbackQuery, lang: str, state: FSMContext) -> None:
    rating = int(call.data.split(":")[1])
    await state.set_state(AccountWizard.feedback_text)
    await state.update_data(rating=rating)
    await call.answer()
    await call.message.answer(t(lang, "feedback_text"))


@router.message(AccountWizard.feedback_text, F.text & ~F.text.startswith("/"))
async def feedback_text(message: Message, token: str, lang: str, state: FSMContext) -> None:
    data = await state.get_data()
    await state.clear()
    text = message.text.strip()
    text = "" if text in ("-", "—") else text[:2000]
    try:
        await api.feedback(token, int(data.get("rating", 5)), text or "—",
                           lang=lang, telegram_id=message.chat.id)
    except ApiError:
        await message.answer(t(lang, "server_down"))
        return
    await message.answer(t(lang, "feedback_sent"))


# ------------------------------------------------------------ FAQ и блог ---

async def show_faq(message: Message, lang: str) -> None:
    items = t(lang, "faq")
    if not isinstance(items, list):
        items = t("ru", "faq")
    lines = [t(lang, "faq_title")]
    for q, a in items:
        lines.append(f"<b>{q}</b>\n{a}")
    await message.answer("\n\n".join(lines), parse_mode="HTML")


@router.message(Command("faq"))
async def cmd_faq(message: Message, lang: str = "ru") -> None:
    await show_faq(message, lang)


async def show_blog(message: Message, lang: str) -> None:
    try:
        posts = await api.blog(lang)
    except ApiError:
        posts = []
    if not posts:
        await message.answer(t(lang, "blog_empty"))
        return
    buttons = [InlineKeyboardButton(text=(p.get("title") or p.get("title_ru") or "…")[:60],
                                    url=f"{settings.site_base_url}/blog/{p.get('slug')}")
               for p in posts[:10] if p.get("slug")]
    await message.answer(t(lang, "blog_title"), parse_mode="HTML",
                         reply_markup=InlineKeyboardMarkup(inline_keyboard=rows_of(buttons, 1)))


# -------------------------------------------------------------- удаление ---

@router.message(Command("delete"))
async def cmd_delete(message: Message, lang: str = "ru") -> None:
    await _delete_confirm(message, lang)


@router.callback_query(F.data == "p:delete")
async def delete_button(call: CallbackQuery, lang: str) -> None:
    await call.answer()
    await _delete_confirm(call.message, lang)


async def _delete_confirm(message: Message, lang: str) -> None:
    await message.answer(t(lang, "delete_confirm"), parse_mode="HTML", reply_markup=InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text=t(lang, "delete_yes"), callback_data="p:delok"),
                          InlineKeyboardButton(text=t(lang, "btn_close"), callback_data="nav:x")]]))


@router.callback_query(F.data == "p:delok")
async def delete_ok(call: CallbackQuery, lang: str, state: FSMContext) -> None:
    chat_id = call.message.chat.id
    await state.clear()
    try:
        await api.delete_account(call.from_user.id)
    except ApiError:
        await call.answer(t(lang, "server_down"))
        return
    await store.drop_token(chat_id)
    for key in ("session", "models_cache", "sessions_cache", "st_project", "st_char", "seen_start",
                "terms_ok", "lang", "model"):
        await store.drop(chat_id, key)
    await call.answer()
    await call.message.answer(t(lang, "delete_done"))
