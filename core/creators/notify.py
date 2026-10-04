"""Уведомления креатору: колокольчик на сайте и сообщение в Telegram.

Двенадцать событий — список клиента (ТЗ п.36); payout_rejected добавлен, чтобы
отклонённая заявка на вывод не оставалась без ответа.

emit() зовут изнутри денежных операций, поэтому он:
- никогда не бросает исключений;
- ничего не отправляет сразу, а откладывает до фиксации транзакции
  (ATOMIC_REQUESTS=True): откатилась операция — не ушло и уведомление.

Почты и веб-пушей здесь нет.
"""
from __future__ import annotations

import logging

from django.conf import settings
from django.db import transaction

logger = logging.getLogger("creators")

EVENTS = ("application_approved", "application_rejected", "level_changed", "credits_granted",
          "new_referral", "new_paying_user", "commission_accrued", "payout_approved",
          "payout_sent", "publication_approved", "publication_rejected", "next_level_ready",
          "payout_rejected")

LANGS = ("ru", "en", "kg")
DEFAULT_LANG = "ru"
# Вид сообщения для бота. Своего переключателя у него нет (TelegramChat.wants
# вернёт True), поэтому выключенные «реферальные» уведомления выплаты не прячут.
TELEGRAM_KIND = "creator"

# event -> lang -> (заголовок, текст с {подстановками})
TEXTS: dict[str, dict[str, tuple[str, str]]] = {
    "application_approved": {
        "ru": ("Заявка одобрена",
               "Вы участник EsAI Creators. Уровень: {level_title}, комиссия {percent}%. "
               "Создайте свой промокод в кабинете."),
        "en": ("Application approved",
               "You are now an EsAI Creator. Level: {level_title}, commission {percent}%. "
               "Create your promo code in the dashboard."),
        "kg": ("Өтүнмө жактырылды",
               "Сиз EsAI Creators катышуучусусуз. Деңгээл: {level_title}, комиссия {percent}%. "
               "Кабинетте өз промокодуңузду түзүңүз."),
    },
    "application_rejected": {
        "ru": ("Заявка отклонена",
               "К сожалению, заявка в EsAI Creators отклонена. {reason}"),
        "en": ("Application rejected",
               "Unfortunately, your EsAI Creators application was rejected. {reason}"),
        "kg": ("Өтүнмө четке кагылды",
               "Тилекке каршы, EsAI Creators программасына өтүнмөңүз четке кагылды. {reason}"),
    },
    "level_changed": {
        "ru": ("Уровень изменён", "Ваш уровень: {level_title}. Комиссия: {percent}%."),
        "en": ("Level changed", "Your level: {level_title}. Commission: {percent}%."),
        "kg": ("Деңгээл өзгөртүлдү", "Сиздин деңгээл: {level_title}. Комиссия: {percent}%."),
    },
    "credits_granted": {
        "ru": ("Получены Creator Credits", "Вам начислено {amount} Creator Credits."),
        "en": ("Creator Credits received", "You have received {amount} Creator Credits."),
        "kg": ("Creator Credits алынды", "Сизге {amount} Creator Credits чегерилди."),
    },
    "new_referral": {
        "ru": ("Новый реферал", "По вашей ссылке зарегистрировался {user_label}."),
        "en": ("New referral", "{user_label} signed up with your link."),
        "kg": ("Жаңы реферал", "Сиздин шилтеме аркылуу {user_label} катталды."),
    },
    "new_paying_user": {
        "ru": ("Новый платящий пользователь", "{user_label} сделал первую оплату."),
        "en": ("New paying user", "{user_label} made their first payment."),
        "kg": ("Жаңы төлөөчү колдонуучу", "{user_label} биринчи төлөмүн жасады."),
    },
    "commission_accrued": {
        "ru": ("Начислена комиссия",
               "+{amount_usdt} USDT ({percent}% с оплаты {base_usdt} USDT)."),
        "en": ("Commission accrued",
               "+{amount_usdt} USDT ({percent}% of a {base_usdt} USDT payment)."),
        "kg": ("Комиссия чегерилди",
               "+{amount_usdt} USDT ({base_usdt} USDT төлөмдөн {percent}%)."),
    },
    "payout_approved": {
        "ru": ("Выплата одобрена", "Заявка на {amount_usdt} USDT одобрена и ждёт отправки."),
        "en": ("Payout approved",
               "Your request for {amount_usdt} USDT is approved and awaits sending."),
        "kg": ("Төлөм жактырылды",
               "{amount_usdt} USDT өтүнмөсү жактырылды жана жөнөтүүнү күтүүдө."),
    },
    "payout_sent": {
        "ru": ("Выплата отправлена", "{amount_usdt} USDT отправлены. TXID: {txid}"),
        "en": ("Payout sent", "{amount_usdt} USDT has been sent. TXID: {txid}"),
        "kg": ("Төлөм жөнөтүлдү", "{amount_usdt} USDT жөнөтүлдү. TXID: {txid}"),
    },
    "publication_approved": {
        "ru": ("Публикация подтверждена", "Публикация засчитана: {url}"),
        "en": ("Publication approved", "The publication has been counted: {url}"),
        "kg": ("Жарыя ырасталды", "Жарыя эсепке алынды: {url}"),
    },
    "publication_rejected": {
        "ru": ("Публикация отклонена", "Публикация не засчитана: {url}. {reason}"),
        "en": ("Publication rejected", "The publication was not counted: {url}. {reason}"),
        "kg": ("Жарыя четке кагылды", "Жарыя эсепке алынган жок: {url}. {reason}"),
    },
    "next_level_ready": {
        "ru": ("Условия уровня выполнены",
               "Условия уровня {next_title} выполнены. Ожидает подтверждения EsAI."),
        "en": ("Level conditions met",
               "The conditions for {next_title} are met. Awaiting confirmation from EsAI."),
        "kg": ("Деңгээлдин шарттары аткарылды",
               "{next_title} деңгээлинин шарттары аткарылды. EsAI ырастоосун күтүүдө."),
    },
    "payout_rejected": {
        "ru": ("Выплата отклонена", "Заявка на {amount_usdt} USDT отклонена. {reason}"),
        "en": ("Payout rejected", "Your request for {amount_usdt} USDT was rejected. {reason}"),
        "kg": ("Төлөм четке кагылды", "{amount_usdt} USDT өтүнмөсү четке кагылды. {reason}"),
    },
}

# Кнопка под сообщением в Telegram: (подпись, путь на сайте).
_CABINET_BUTTON = {"ru": "Открыть кабинет", "en": "Open dashboard", "kg": "Кабинетти ачуу"}
# У человека без кабинета (отклонённая заявка) кнопка ведёт на страницу программы.
_PROGRAM_BUTTON = {"ru": "О программе", "en": "About the program", "kg": "Программа жөнүндө"}


class _Blank(dict):
    """Подстановки шаблона: чего не передали — то пустая строка, а не KeyError."""

    def __missing__(self, key):
        return ""


def _lang(lang) -> str:
    value = str(lang or "").strip().lower()
    return value if value in LANGS else DEFAULT_LANG


def _ctx(ctx: dict) -> dict:
    """Значения подстановок — строками (в задачу бота уходит JSON); None — пусто."""
    return {str(key): ("" if value is None else str(value)) for key, value in (ctx or {}).items()}


def render(event: str, lang: str, ctx: dict) -> tuple[str, str]:
    """(заголовок, текст) события на языке lang; незнакомый язык — русский."""
    by_lang = TEXTS[event]
    title, template = by_lang.get(_lang(lang)) or by_lang[DEFAULT_LANG]
    body = template.format_map(_Blank(_ctx(ctx)))
    # Пустая причина оставляла бы хвостовой пробел («…отклонена. »).
    return title, body.strip()


def emit(creator, event: str, **ctx) -> None:
    """Уведомить креатора о событии. Никогда не бросает исключений."""
    try:
        if event not in EVENTS:
            logger.warning("creators.notify: неизвестное событие %r", event)
            return
        creator_pk = getattr(creator, "pk", None)
        if not creator_pk:
            return
        payload = _ctx(ctx)
        transaction.on_commit(lambda: _deliver(creator_pk, event, payload), robust=True)
    except Exception:  # noqa: BLE001 — уведомление не должно ронять денежную операцию
        logger.exception("creators.notify: emit %s не поставился", event)


def emit_to_user(user, lang: str, event: str, **ctx) -> None:
    """То же для человека без строки Creator (отклонённая заявка). Никогда не бросает."""
    try:
        if event not in EVENTS:
            logger.warning("creators.notify: неизвестное событие %r", event)
            return
        user_pk = getattr(user, "pk", None)
        if not user_pk:
            return
        payload = _ctx(ctx)
        language = _lang(lang)
        transaction.on_commit(lambda: _deliver_to_user(user_pk, language, event, payload),
                              robust=True)
    except Exception:  # noqa: BLE001
        logger.exception("creators.notify: emit_to_user %s не поставился", event)


def _deliver(creator_pk, event: str, ctx: dict) -> None:
    """Доставка после фиксации транзакции. Никогда не бросает исключений."""
    try:
        from .models import Creator

        creator = Creator.objects.select_related("user").filter(pk=creator_pk).first()
        if creator is None:
            return
        _send(creator.user, creator.lang, event, ctx, has_cabinet=True)
    except Exception:  # noqa: BLE001
        logger.exception("creators.notify: доставка %s креатору %s не удалась", event, creator_pk)


def _deliver_to_user(user_pk, lang: str, event: str, ctx: dict) -> None:
    try:
        from django.contrib.auth import get_user_model

        user = get_user_model().objects.filter(pk=user_pk).first()
        if user is None:
            return
        _send(user, lang, event, ctx, has_cabinet=False)
    except Exception:  # noqa: BLE001
        logger.exception("creators.notify: доставка %s пользователю %s не удалась", event, user_pk)


def _send(user, lang: str, event: str, ctx: dict, *, has_cabinet: bool) -> None:
    """Оба канала. Каждый в своём try: отказ одного не отменяет другой."""
    language = _lang(lang)
    title, body = render(event, language, ctx)

    try:
        from users.models import Notification

        # Колокольчик: уведомление и его адресат — одной транзакцией, иначе при
        # сбое между ними осталось бы уведомление без получателя.
        with transaction.atomic():
            notification = Notification.objects.create(title=title[:200], body=body)
            notification.add_recipients([user])
    except Exception:  # noqa: BLE001
        logger.exception("creators.notify: колокольчик %s для %s не записан", event, user.pk)

    try:
        from botapi import tasks as bot_tasks
        from botapi.telegram import escape

        base = str(getattr(settings, "CREATORS_LINK_BASE", "") or "").rstrip("/")
        if has_cabinet:
            url, label = f"{base}/creators/dashboard", _CABINET_BUTTON[language]
        else:
            url, label = f"{base}/creators", _PROGRAM_BUTTON[language]
        # Бот шлёт с parse_mode=HTML: причина отказа и ссылка публикации — чужой
        # текст, знак «<» или «&» в нём сломал бы разметку всего сообщения.
        bot_tasks.notify(user, TELEGRAM_KIND, f"<b>{escape(title)}</b>\n{escape(body)}",
                         url=url, url_label=label)
    except Exception:  # noqa: BLE001
        logger.exception("creators.notify: Telegram %s для %s не поставлен", event, user.pk)
