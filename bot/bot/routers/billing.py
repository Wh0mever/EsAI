"""Баланс и оплата Telegram Stars.

Внутри бота цифровые товары продаются только за Stars — так требует Telegram.
Про карту и крипту говорим текстом («на сайте, аккаунт общий»), без кнопок и
ссылок на оплату. Деньги считает сервер: бот лишь передаёт ему то, что
прислал Telegram, и повторяет попытку, если сервер был недоступен.
"""
from __future__ import annotations

import asyncio
import logging
import time

from aiogram import Bot, F, Router
from aiogram.filters import Command
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    LabeledPrice,
    Message,
    PreCheckoutQuery,
)

from bot.config import settings
from bot.services.api import ApiError, api
from bot.services.state import store
from bot.services.tg_format import esc, split_html
from bot.texts import register_texts, t

logger = logging.getLogger(__name__)
router = Router(name="billing")

PENDING = "stars_confirm"
# Telegram отменяет платёж, если ответа на pre_checkout нет 10 секунд, а
# обычный read-таймаут API — 60: при медленном ядре человек получает ошибку
# оплаты, а бот об этом даже не узнаёт. Ждём ядро не дольше этого срока —
# остаток десяти секунд оставляем на сам ответ Telegram.
PRECHECK_TIMEOUT = 5.0
# Язык человека лежит в Redis. Если Redis задумался, платёж от этого зависеть
# не должен: подождём секунду и ответим по-русски.
LANG_TIMEOUT = 1.0

register_texts({
    "ru": {
        "topup_title": "💳 <b>Пополнение баланса</b>\nОплата в боте — Telegram Stars ⭐",
        "topup_pkg": ("<b>{name}</b> — {tokens} кр{bonus} · <b>{stars} ⭐</b>{badge}\n"
                      "{desc}{value}"),
        "topup_value": "Примерно хватит на: {items}",
        "topup_footer": ("Картой, Элкарт или криптовалютой можно пополнить на сайте esai.kg — "
                         "аккаунт и баланс общие с ботом."),
        "topup_none": "Пакеты для оплаты в боте пока не настроены. Пополнить можно на сайте esai.kg.",
        "topup_btn": "{name} · {stars} ⭐",
        "terms": ("📄 <b>Условия покупки</b>\n\n"
                  "• Кредиты зачисляются на ваш баланс EsAI сразу после оплаты и не сгорают.\n"
                  "• Возврат возможен в течение 14 дней, если кредиты не потрачены: /paysupport.\n"
                  "• Оплата в боте идёт через Telegram Stars; на сайте — картой, Элкарт или криптой.\n"
                  "• Полные условия: {site}/terms-conditions"),
        "terms_ok": "✅ Принимаю условия",
        "terms_accepted": "Спасибо! Теперь можно выбрать пакет.",
        "paysupport": ("🆘 <b>Поддержка по оплате</b>\n\n"
                       "Опишите проблему одним сообщением — мы ответим здесь же. "
                       "Укажите, какой пакет покупали и когда.\n"
                       "Возврат Stars возможен в течение 14 дней, если кредиты не потрачены."),
        "paid": ("✅ <b>Оплата прошла</b>\n+{credits} кредитов · пакет «{package}»\n"
                 "Баланс: <b>{balance}</b>\nТеперь доступны все премиум-модели."),
        "paid_duplicate": "Эта оплата уже зачислена. Баланс: <b>{balance}</b>",
        "paid_pending": ("Оплата получена, зачисляем… Если кредиты не появятся в течение "
                         "10 минут — напишите в /paysupport."),
        "paid_refunded": "⚠️ Оплата не совпала со счётом — Stars возвращены на ваш счёт Telegram.",
        "refunded": "↩️ Возврат {stars} ⭐ выполнен. Кредиты за эту покупку сняты с баланса.",
        "refunded_extra": ("↩️ Повторная оплата возвращена: {stars} ⭐. "
                           "Кредиты за покупку остаются на балансе."),
        "stars_disabled": "Оплата Stars сейчас недоступна. Пополнить можно на сайте esai.kg.",
        "stars_region": "Оплата Stars недоступна в вашем регионе.",
        "precheck_fail": "Счёт устарел — откройте /topup и выберите пакет заново.",
        "precheck_slow": ("Сервер не ответил вовремя. Stars не списаны — "
                          "попробуйте оплатить ещё раз через минуту."),
        "btn_to_chat": "💬 В чат",
        "btn_premium": "🧠 Выбрать премиум-модель",
        "btn_history": "📜 История операций",
        "btn_promo": "🎟 Промокод",
        "btn_transfer": "💸 Перевести",
        "tx_history_title": "📜 <b>Последние операции</b>",
        "tx_history_empty": "Операций пока нет.",
        "balance_full": ("💳 <b>Баланс: {balance} кредитов</b>\nТариф: {tier}\n"
                         "Кредиты не сгорают и работают везде: чат, картинки, видео и студия."),
        "reason_chat": "чат", "reason_purchase": "покупка", "reason_bonus": "бонус",
        "reason_welcome": "приветственный бонус", "reason_daily_bonus": "ежедневный бонус",
        "reason_refund": "возврат", "reason_referral": "реферальное", "reason_transfer_in": "перевод вам",
        "reason_transfer_out": "перевод от вас", "reason_promo": "промокод", "reason_stt": "голос",
        "reason_cartoon_scene": "студия: сцена", "reason_cartoon_keyframe": "студия: кадр",
        "reason_cartoon_character": "студия: герой", "reason_admin": "корректировка",
    },
    "en": {
        "topup_title": "💳 <b>Top up</b>\nPayments in the bot — Telegram Stars ⭐",
        "topup_pkg": ("<b>{name}</b> — {tokens} cr{bonus} · <b>{stars} ⭐</b>{badge}\n"
                      "{desc}{value}"),
        "topup_value": "Roughly enough for: {items}",
        "topup_footer": ("You can also top up by card or crypto at esai.kg — "
                         "the account and balance are shared with the bot."),
        "topup_none": "No packages are available in the bot yet. You can top up at esai.kg.",
        "topup_btn": "{name} · {stars} ⭐",
        "terms": ("📄 <b>Purchase terms</b>\n\n"
                  "• Credits are added to your EsAI balance right after payment and never expire.\n"
                  "• Refunds within 14 days if credits are unused: /paysupport.\n"
                  "• In the bot you pay with Telegram Stars; on the site — by card or crypto.\n"
                  "• Full terms: {site}/terms-conditions"),
        "terms_ok": "✅ I accept the terms",
        "terms_accepted": "Thank you! Now pick a package.",
        "paysupport": ("🆘 <b>Payment support</b>\n\n"
                       "Describe the problem in one message — we will reply here. "
                       "Mention which package you bought and when.\n"
                       "Stars can be refunded within 14 days if the credits are unused."),
        "paid": ("✅ <b>Payment received</b>\n+{credits} credits · “{package}”\n"
                 "Balance: <b>{balance}</b>\nAll premium models are now available."),
        "paid_duplicate": "This payment is already credited. Balance: <b>{balance}</b>",
        "paid_pending": ("Payment received, crediting… If the credits do not appear within "
                         "10 minutes, write to /paysupport."),
        "paid_refunded": "⚠️ The payment did not match the invoice — Stars were returned to you.",
        "refunded": "↩️ Refund of {stars} ⭐ completed. Credits from this purchase were removed.",
        "refunded_extra": ("↩️ The duplicate payment was refunded: {stars} ⭐. "
                           "Your purchased credits stay on your balance."),
        "stars_disabled": "Stars payments are unavailable right now. You can top up at esai.kg.",
        "stars_region": "Stars payments are not available in your region.",
        "precheck_fail": "The invoice is outdated — open /topup and pick a package again.",
        "precheck_slow": ("The server did not answer in time. No Stars were charged — "
                          "please try to pay again in a minute."),
        "btn_to_chat": "💬 To chat",
        "btn_premium": "🧠 Pick a premium model",
        "btn_history": "📜 History",
        "btn_promo": "🎟 Promo code",
        "btn_transfer": "💸 Transfer",
        "tx_history_title": "📜 <b>Recent operations</b>",
        "tx_history_empty": "No operations yet.",
        "balance_full": ("💳 <b>Balance: {balance} credits</b>\nPlan: {tier}\n"
                         "Credits never expire and work everywhere: chat, images, video and studio."),
        "reason_chat": "chat", "reason_purchase": "purchase", "reason_bonus": "bonus",
        "reason_welcome": "welcome bonus", "reason_daily_bonus": "daily bonus",
        "reason_refund": "refund", "reason_referral": "referral", "reason_transfer_in": "transfer in",
        "reason_transfer_out": "transfer out", "reason_promo": "promo code", "reason_stt": "voice",
        "reason_cartoon_scene": "studio: scene", "reason_cartoon_keyframe": "studio: frame",
        "reason_cartoon_character": "studio: hero", "reason_admin": "adjustment",
    },
    "kg": {
        "topup_title": "💳 <b>Балансты толуктоо</b>\nБотто төлөм — Telegram Stars ⭐",
        "topup_pkg": ("<b>{name}</b> — {tokens} кр{bonus} · <b>{stars} ⭐</b>{badge}\n"
                      "{desc}{value}"),
        "topup_value": "Болжол менен жетет: {items}",
        "topup_footer": ("Карта же криптовалюта менен esai.kg сайтында толуктасаңыз болот — "
                         "аккаунт жана баланс бот менен жалпы."),
        "topup_none": "Ботто пакеттер азырынча жок. esai.kg сайтында толуктаңыз.",
        "topup_btn": "{name} · {stars} ⭐",
        "terms": ("📄 <b>Сатып алуу шарттары</b>\n\n"
                  "• Кредиттер төлөмдөн кийин дароо балансыңызга түшөт жана күйбөйт.\n"
                  "• Кредиттер сарпталбаса, 14 күн ичинде кайтарууга болот: /paysupport.\n"
                  "• Ботто төлөм Telegram Stars аркылуу; сайтта — карта же крипто.\n"
                  "• Толук шарттар: {site}/terms-conditions"),
        "terms_ok": "✅ Шарттарды кабыл алам",
        "terms_accepted": "Рахмат! Эми пакет тандаңыз.",
        "paysupport": ("🆘 <b>Төлөм боюнча колдоо</b>\n\n"
                       "Көйгөйдү бир билдирүү менен жазыңыз — ушул жерде жооп беребиз. "
                       "Кайсы пакетти качан сатып алганыңызды көрсөтүңүз.\n"
                       "Кредиттер сарпталбаса, Stars 14 күн ичинде кайтарылат."),
        "paid": ("✅ <b>Төлөм өттү</b>\n+{credits} кредит · «{package}» пакети\n"
                 "Баланс: <b>{balance}</b>\nЭми бардык премиум моделдер жеткиликтүү."),
        "paid_duplicate": "Бул төлөм мурда эле эсептелген. Баланс: <b>{balance}</b>",
        "paid_pending": ("Төлөм алынды, эсептеп жатабыз… Кредиттер 10 мүнөт ичинде "
                         "келбесе — /paysupport жазыңыз."),
        "paid_refunded": "⚠️ Төлөм эсеп менен дал келген жок — Stars сизге кайтарылды.",
        "refunded": "↩️ {stars} ⭐ кайтарылды. Бул сатып алуунун кредиттери баланстан алынды.",
        "refunded_extra": ("↩️ Кайталанган төлөм кайтарылды: {stars} ⭐. "
                           "Сатып алган кредиттериңиз балансыңызда калат."),
        "stars_disabled": "Stars төлөмү азыр жеткиликсиз. esai.kg сайтында толуктаңыз.",
        "stars_region": "Сиздин аймакта Stars төлөмү жеткиликсиз.",
        "precheck_fail": "Эсеп эскирди — /topup ачып, пакетти кайра тандаңыз.",
        "precheck_slow": ("Сервер өз убагында жооп берген жок. Stars алынган жок — "
                          "бир мүнөттөн кийин кайра төлөп көрүңүз."),
        "btn_to_chat": "💬 Чатка",
        "btn_premium": "🧠 Премиум модель тандоо",
        "btn_history": "📜 Тарых",
        "btn_promo": "🎟 Промокод",
        "btn_transfer": "💸 Которуу",
        "tx_history_title": "📜 <b>Акыркы операциялар</b>",
        "tx_history_empty": "Азырынча операциялар жок.",
        "balance_full": ("💳 <b>Баланс: {balance} кредит</b>\nТариф: {tier}\n"
                         "Кредиттер күйбөйт: чат, сүрөт, видео жана студия."),
        "reason_chat": "чат", "reason_purchase": "сатып алуу", "reason_bonus": "бонус",
        "reason_welcome": "кош келүү бонусу", "reason_daily_bonus": "күнүмдүк бонус",
        "reason_refund": "кайтаруу", "reason_referral": "реферал", "reason_transfer_in": "сизге которуу",
        "reason_transfer_out": "сизден которуу", "reason_promo": "промокод", "reason_stt": "үн",
        "reason_cartoon_scene": "студия: сцена", "reason_cartoon_keyframe": "студия: кадр",
        "reason_cartoon_character": "студия: каарман", "reason_admin": "оңдоо",
    },
})


# --------------------------------------------------------------- баланс ---

def balance_keyboard(lang: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=t(lang, "btn_topup"), callback_data="b:topup"),
         InlineKeyboardButton(text=t(lang, "btn_history"), callback_data="b:hist")],
        [InlineKeyboardButton(text=t(lang, "btn_promo"), callback_data="more:promo"),
         InlineKeyboardButton(text=t(lang, "btn_transfer"), callback_data="more:transfer")],
    ])


async def show_balance(message: Message, token: str, lang: str) -> None:
    try:
        data = await api.balance(token, lang=lang, telegram_id=message.chat.id)
    except ApiError:
        await message.answer(t(lang, "server_down"))
        return
    # Безлимит сервер отдаёт двумя способами (tier="unlimited" и флаг
    # is_unlimited) — читаем оба. Ни одного из полей может и не быть: пустой
    # ответ и старая версия ядра не должны ронять экран, тогда тариф обычный.
    if not isinstance(data, dict):
        data = {}
    tier_key = {"paid": "tier_paid", "unlimited": "tier_unlimited"}.get(
        str(data.get("tier") or ""), "tier_free")
    if data.get("is_unlimited"):
        tier_key = "tier_unlimited"
    await message.answer(
        t(lang, "balance_full", balance=data.get("balance_tokens") or 0, tier=t(lang, tier_key)),
        parse_mode="HTML", reply_markup=balance_keyboard(lang))


@router.message(Command("balance"))
async def cmd_balance(message: Message, token: str, lang: str = "ru") -> None:
    await show_balance(message, token, lang)


def _reason(lang: str, reason: str) -> str:
    key = f"reason_{reason}"
    label = t(lang, key)
    return reason if label == key else label


@router.callback_query(F.data == "b:hist")
async def history(call: CallbackQuery, token: str, lang: str) -> None:
    await call.answer()
    try:
        rows = await api.transactions(token, lang=lang, telegram_id=call.message.chat.id)
    except ApiError:
        await call.message.answer(t(lang, "server_down"))
        return
    if not rows:
        await call.message.answer(t(lang, "tx_history_empty"))
        return
    lines = [t(lang, "tx_history_title")]
    for tx in rows[:20]:
        delta = int(tx.get("delta") or 0)
        date = str(tx.get("created_at") or "")[:10]
        date = f"{date[8:10]}.{date[5:7]}" if len(date) == 10 else date
        meta = tx.get("meta") or {}
        model = str(meta.get("model") or "").split("/")[-1]
        # Название модели и причина приходят с сервера: «<» в них ломает разбор
        # HTML, и Telegram отвергает всё сообщение целиком.
        extra = f" · {esc(model)}" if model else ""
        lines.append(f"{esc(date)} <b>{'+' if delta > 0 else ''}{delta}</b> "
                     f"{esc(_reason(lang, tx.get('reason', '')))}"
                     f"{extra} · {esc(tx.get('balance_after', ''))}")
    # 20 строк с длинными названиями моделей могут перевалить за лимит 4096 —
    # тогда не отправится вообще ничего; режем по границам строк.
    for part in split_html("\n".join(lines)):
        await call.message.answer(part, parse_mode="HTML")


# ---------------------------------------------------------------- topup ---

def _value_line(lang: str, value: dict) -> str:
    if not isinstance(value, dict) or not value:
        return ""
    icons = {"text": "💬", "image": "🎨", "video": "🎬", "document": "📄"}
    parts = []
    for key in ("text", "image", "video", "document"):
        item = value.get(key) or {}
        count = item.get("count")
        if count:
            parts.append(f"{icons[key]} {count}")
    return ("\n" + t(lang, "topup_value", items=" · ".join(parts))) if parts else ""


async def show_topup(message: Message, token: str, lang: str) -> None:
    chat_id = message.chat.id
    try:
        packages = await api.packages(token, lang=lang, telegram_id=chat_id)
    except ApiError:
        await message.answer(t(lang, "server_down"))
        return
    try:
        values = {p.get("id"): p.get("value") for p in await api.packages_value(token, lang=lang,
                                                                                telegram_id=chat_id)}
    except ApiError:
        values = {}
    sellable = [p for p in packages if p.get("stars_price")]
    if not sellable:
        await message.answer(t(lang, "topup_none"))
        return
    blocks = [t(lang, "topup_title")]
    buttons = []
    for p in sellable:
        bonus_total = int(p.get("bonus_tokens") or 0) + int(p.get("stars_bonus_tokens") or 0)
        bonus = f" +{bonus_total}" if bonus_total else ""
        # Название, бейдж и описание пакета — свободный текст из админки. Один
        # «<» в них — и Telegram не принимает ВЕСЬ экран пополнения: человек
        # остаётся без списка пакетов и без кнопок оплаты.
        badge = f" · {esc(p['badge'])}" if p.get("badge") else ""
        desc = (p.get("description") or "").strip()
        desc = (esc(desc[:120]) + "\n") if desc else ""
        blocks.append(t(lang, "topup_pkg", name=esc(p.get("name")), tokens=esc(p.get("tokens")),
                        bonus=bonus, stars=esc(p["stars_price"]), badge=badge, desc=desc,
                        value=_value_line(lang, values.get(p.get("id")))))
        # В подписи кнопки разметки нет — там текст идёт как есть, без esc().
        buttons.append(InlineKeyboardButton(
            text=t(lang, "topup_btn", name=("🔥 " if p.get("featured") else "") + str(p.get("name")),
                   stars=p["stars_price"]),
            callback_data=f"b:buy:{p['id']}"))
    blocks.append(t(lang, "topup_footer"))
    rows = [buttons[i:i + 2] for i in range(0, len(buttons), 2)]
    markup = InlineKeyboardMarkup(inline_keyboard=rows)
    # Пакетов с описаниями и «на что хватит» бывает столько, что текст не лезет
    # в лимит 4096 — тогда Telegram не отправит ничего. Режем на части, кнопки
    # вешаем на последнюю: без них экран бесполезен.
    parts = split_html("\n\n".join(blocks))
    for index, part in enumerate(parts):
        await message.answer(part, parse_mode="HTML",
                             reply_markup=markup if index == len(parts) - 1 else None,
                             disable_web_page_preview=True)


@router.message(Command("topup"))
async def cmd_topup(message: Message, token: str, lang: str = "ru") -> None:
    await show_topup(message, token, lang)


@router.callback_query(F.data == "b:topup")
async def topup_button(call: CallbackQuery, token: str, lang: str) -> None:
    await call.answer()
    await show_topup(call.message, token, lang)


@router.message(Command("terms"))
async def cmd_terms(message: Message, lang: str = "ru") -> None:
    await message.answer(t(lang, "terms", site=settings.site_base_url), parse_mode="HTML",
                         disable_web_page_preview=True)


@router.message(Command("paysupport"))
async def cmd_paysupport(message: Message, lang: str = "ru", state=None) -> None:
    from bot.routers.account import start_support

    await message.answer(t(lang, "paysupport"), parse_mode="HTML")
    if state is not None:
        await start_support(state, topic="payment")


async def _terms_accepted(chat_id: int) -> bool:
    return bool(await store.get(chat_id, "terms_ok"))


@router.callback_query(F.data.startswith("b:buy:"))
async def buy(call: CallbackQuery, token: str, lang: str) -> None:
    chat_id = call.message.chat.id
    package_id = call.data.split(":")[2]
    if not await _terms_accepted(chat_id):
        await call.answer()
        await call.message.answer(
            t(lang, "terms", site=settings.site_base_url), parse_mode="HTML",
            disable_web_page_preview=True,
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
                InlineKeyboardButton(text=t(lang, "terms_ok"), callback_data=f"b:terms:{package_id}")]]))
        return
    await call.answer()
    await send_invoice(call.message, lang, int(package_id))


@router.callback_query(F.data.startswith("b:terms:"))
async def accept_terms(call: CallbackQuery, lang: str) -> None:
    chat_id = call.message.chat.id
    package_id = call.data.split(":")[2]
    await store.set(chat_id, "terms_ok", True)
    try:
        await api.set_prefs(call.from_user.id, consent_terms=True)
    except ApiError:
        pass
    await call.answer(t(lang, "terms_accepted"))
    try:
        await call.message.edit_reply_markup(reply_markup=None)
    except Exception:
        pass
    if package_id.isdigit():
        await send_invoice(call.message, lang, int(package_id))


async def send_invoice(message: Message, lang: str, package_id: int) -> None:
    chat_id = message.chat.id
    try:
        invoice = await api.stars_invoice(chat_id, package_id, lang)
    except ApiError as exc:
        if exc.code == "stars_disabled":
            await message.answer(t(lang, "stars_disabled"))
        elif exc.status == 429:
            # Раньше 429 падал в «пакеты не настроены» — неправда, которая
            # отправляла человека на сайт вместо простого «подождите минуту».
            await message.answer(t(lang, "rate_limited"))
        elif exc.is_temporary:
            await message.answer(t(lang, "server_down"))
        else:
            await message.answer(t(lang, "topup_none"))
        return
    try:
        sent = await message.bot.send_invoice(
            chat_id=chat_id,
            title=invoice["title"],
            description=invoice["description"],
            payload=invoice["payload"],
            currency="XTR",
            prices=[LabeledPrice(label=p["label"], amount=int(p["amount"]))
                    for p in invoice["prices"]],
            provider_token="",
        )
    except Exception as exc:
        text = str(exc)
        logger.warning("sendInvoice не прошёл: %s", text[:200])
        if "STARS" in text.upper() and "BLOCK" in text.upper():
            await message.answer(t(lang, "stars_region"))
        else:
            await message.answer(t(lang, "failed"))
        return
    try:
        await api.stars_invoice_message(invoice["payload"], sent.message_id)
    except ApiError:
        pass


# ------------------------------------------------------------- Telegram ---

@router.pre_checkout_query()
async def pre_checkout(query: PreCheckoutQuery) -> None:
    """Telegram ждёт ответ 10 секунд; проверяем счёт у сервера и отвечаем."""
    # Язык читаем заранее: в ветках ошибки времени на лишний поход уже нет.
    # Этот поход стоит на пути УСПЕШНОЙ оплаты, поэтому он не может её сорвать:
    # упавший или зависший Redis даёт русский текст, а не молчание бота.
    try:
        lang = await asyncio.wait_for(store.get(query.from_user.id, "lang"),
                                      timeout=LANG_TIMEOUT) or "ru"
    except Exception:
        logger.warning("precheck %s: язык не прочитан", query.invoice_payload)
        lang = "ru"
    try:
        await asyncio.wait_for(
            api.stars_precheck(query.from_user.id, query.invoice_payload,
                               query.total_amount, query.currency),
            timeout=PRECHECK_TIMEOUT)
    except asyncio.TimeoutError:
        # Ядро думает дольше, чем Telegram готов ждать. Отвечаем отказом сами:
        # так человек видит причину, а мы — строку в логе. Деньги не списаны.
        logger.warning("precheck %s: ядро не ответило за %s с", query.invoice_payload,
                       PRECHECK_TIMEOUT)
        await query.answer(ok=False, error_message=t(lang, "precheck_slow"))
        return
    except ApiError as exc:
        # Упавшее ядро и обрыв связи — не «счёт устарел»: советовать открыть
        # /topup заново бессмысленно, помогает повторная попытка.
        if exc.code == "stars_disabled":
            # Оплату Stars выключили мы сами: заново открытый /topup приведёт
            # человека ровно к этому же отказу — честнее сказать про сайт.
            logger.warning("precheck %s: оплата Stars выключена", query.invoice_payload)
            await query.answer(ok=False, error_message=t(lang, "stars_disabled"))
        elif exc.is_temporary:
            logger.warning("precheck %s: ядро недоступно (%s)", query.invoice_payload, exc.code)
            await query.answer(ok=False, error_message=t(lang, "precheck_slow"))
        else:
            logger.warning("precheck %s отклонён: %s", query.invoice_payload, exc.code)
            await query.answer(ok=False, error_message=t(lang, "precheck_fail"))
        return
    except Exception:
        logger.exception("precheck: сервер недоступен")
        await query.answer(ok=False, error_message=t(lang, "server_down"))
        return
    await query.answer(ok=True)


def _confirm_body(message: Message) -> dict:
    payment = message.successful_payment
    return {
        "telegram_id": message.from_user.id,
        "payload": payment.invoice_payload,
        "telegram_payment_charge_id": payment.telegram_payment_charge_id,
        "provider_payment_charge_id": payment.provider_payment_charge_id or "",
        "total_amount": payment.total_amount,
        "currency": payment.currency,
        "raw": {"message_id": message.message_id, "date": message.date.isoformat()},
    }


def _pending_item(body: dict, lang: str, chat_id, exc: ApiError | None = None) -> dict:
    """Подтверждение оплаты для очереди повторов.

    На 429 сервер сам говорит, когда приходить (Retry-After): раньше стучаться
    бесполезно — это только продлит отказ.
    """
    item = {**body, "lang": lang, "chat_id": chat_id}
    if exc is not None and exc.retry_after:
        item["retry_at"] = time.time() + float(exc.retry_after)
    return item


async def _after_paid(bot: Bot, chat_id: int, lang: str, result: dict) -> None:
    await store.drop(chat_id, "models_cache")
    if result.get("invoice_message_id"):
        try:
            await bot.delete_message(chat_id, int(result["invoice_message_id"]))
        except Exception:
            pass
    if result.get("status") == "duplicate":
        await bot.send_message(chat_id, t(lang, "paid_duplicate", balance=result.get("balance_tokens")),
                               parse_mode="HTML")
        return
    await bot.send_message(
        chat_id,
        # Название пакета задаёт админка: «<» в нём не должен превратить
        # сообщение об успешной оплате в ошибку разбора HTML.
        t(lang, "paid", credits=result.get("credited"), package=esc(result.get("package_name", "")),
          balance=result.get("balance_tokens")),
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text=t(lang, "btn_to_chat"), callback_data="nav:x"),
            InlineKeyboardButton(text=t(lang, "btn_premium"), callback_data="m:home"),
        ]]))


@router.message(F.successful_payment)
async def on_paid(message: Message, lang: str = "ru", **_) -> None:
    payment = message.successful_payment
    chat_id = message.chat.id
    # Замок короткий и только против гонки двух одновременных апдейтов: если
    # процесс упал на полпути, Telegram повторит сообщение через минуту, и оно
    # должно дойти до сервера. Кредиты дважды не начислятся — сервер узнаёт
    # оплату по её идентификатору и отвечает «уже зачислено».
    if not await store.once(f"paid:{payment.telegram_payment_charge_id}", ttl=60):
        return
    body = _confirm_body(message)
    try:
        result = await api.stars_confirm(body)
    except ApiError as exc:
        # 429 — тот же «сервер сейчас не может», что и 5xx. Раньше он уходил в
        # ветку «отклонено»: в очередь повторов не попадал, и кредиты за уже
        # списанные Stars ждали ночной сверки.
        if exc.is_temporary:
            await store.push_pending(PENDING, _pending_item(body, lang, chat_id, exc))
            await message.answer(t(lang, "paid_pending"))
            return
        if exc.payload.get("refunded"):
            await message.answer(t(lang, "paid_refunded"))
            return
        logger.error("подтверждение оплаты отклонено: %s %s", exc.code, exc.payload)
        await message.answer(t(lang, "paid_pending"))
        return
    except Exception:
        logger.exception("подтверждение оплаты: сервер недоступен")
        await store.push_pending(PENDING, {**body, "lang": lang, "chat_id": chat_id})
        await message.answer(t(lang, "paid_pending"))
        return
    await _after_paid(message.bot, chat_id, lang, result)


@router.message(F.refunded_payment)
async def on_refunded(message: Message, lang: str = "ru", **_) -> None:
    refund = message.refunded_payment
    key = "refunded"
    try:
        result = await api.stars_refunded(message.from_user.id, refund.telegram_payment_charge_id,
                                          refund.invoice_payload or "")
        # foreign_charge — это наш же автовозврат второй оплаты того же счёта:
        # кредиты первой, законной покупки сервер не трогал.
        if isinstance(result, dict) and result.get("status") == "foreign_charge":
            key = "refunded_extra"
    except ApiError as exc:
        logger.warning("возврат не отмечен: %s", exc.code)
    await store.drop(message.chat.id, "models_cache")
    await message.answer(t(lang, key, stars=refund.total_amount))


async def retry_pending(bot: Bot) -> int:
    """Довести до сервера подтверждения, которые не прошли с первого раза."""
    items = await store.pop_pending(PENDING)
    done = 0
    for index, item in enumerate(items):
        retry_at = item.pop("retry_at", None)
        if isinstance(retry_at, (int, float)) and retry_at > time.time():
            # Сервер просил подождать — ещё рано, пусть лежит до следующего круга.
            await store.push_pending(PENDING, {**item, "retry_at": retry_at})
            continue
        chat_id = item.pop("chat_id", None)
        lang = item.pop("lang", "ru")
        try:
            result = await api.stars_confirm(item)
        except ApiError as exc:
            if exc.is_temporary:
                await store.push_pending(PENDING, _pending_item(item, lang, chat_id, exc))
                if exc.status == 429:
                    # Упёрлись в лимит — остальные из этой пачки упрутся туда же.
                    # Возвращаем их в очередь как есть, до следующего круга.
                    for rest in items[index + 1:]:
                        await store.push_pending(PENDING, rest)
                    break
            else:
                logger.error("отложенное подтверждение отклонено: %s", exc.code)
            continue
        except Exception:
            await store.push_pending(PENDING, {**item, "chat_id": chat_id, "lang": lang})
            continue
        done += 1
        if chat_id:
            try:
                await _after_paid(bot, chat_id, lang, result)
            except Exception:
                logger.exception("сообщение об оплате не ушло")
    return done
