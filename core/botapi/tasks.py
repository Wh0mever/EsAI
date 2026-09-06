"""Уведомления в Telegram.

Пишет их ядро, а не бот: событие «кредиты зачислены» или «мультфильм собран»
рождается в Celery-задачах и вебхуках, и ждать, пока человек сам откроет чат,
незачем. Бот для этого не нужен — хватает одного HTTP-запроса к Bot API.
"""
import logging

from celery import shared_task
from django.conf import settings
from django.utils import timezone

from .models import TelegramChat
from .telegram import TelegramError, escape, tg_api

logger = logging.getLogger("botapi")

# Telegram пропускает около 30 сообщений в секунду на бота. Держимся ниже.
BROADCAST_RATE = 20


def _enabled() -> bool:
    return bool(getattr(settings, "TELEGRAM_NOTIFY_ENABLED", False)) and bool(
        (getattr(settings, "TELEGRAM_PRODUCT_BOT_TOKEN", "") or "").strip())


@shared_task(bind=True, name="botapi.tasks.send_telegram_message", max_retries=5,
             rate_limit="20/s", ignore_result=True)
def send_telegram_message(self, chat_id, text, *, reply_markup=None, video_url=None,
                          kind: str = "", parse_mode: str = "HTML"):
    """Отправить сообщение человеку. Молча выходит, если бот не настроен."""
    if not _enabled():
        return "disabled"
    method = "sendVideo" if video_url else "sendMessage"
    params = {"chat_id": chat_id, "reply_markup": reply_markup}
    if video_url:
        params.update({"video": video_url, "caption": text, "parse_mode": parse_mode,
                       "supports_streaming": True})
    else:
        params.update({"text": text, "parse_mode": parse_mode,
                       "link_preview_options": {"is_disabled": True}})
    try:
        tg_api(method, **params)
    except TelegramError as exc:
        if exc.blocked:
            TelegramChat.objects.filter(chat_id=chat_id).update(
                is_blocked=True, blocked_at=timezone.now())
            logger.info("telegram: чат %s закрыт пользователем", chat_id)
            return "blocked"
        if exc.retry_after:
            raise self.retry(countdown=exc.retry_after + 1, exc=exc)
        if exc.code == 400 and "parse" in exc.description.lower():
            # Разметка не понравилась — отправляем как есть, лишь бы дошло.
            try:
                tg_api(method, **{**params, "parse_mode": None})
                return "plain"
            except TelegramError:
                logger.warning("telegram: сообщение не ушло (%s)", exc.description)
                return "failed"
        if exc.code >= 500:
            raise self.retry(countdown=min(60 * (self.request.retries + 1), 600), exc=exc)
        logger.warning("telegram: %s → %s", kind or method, exc.description)
        return "failed"
    TelegramChat.objects.filter(chat_id=chat_id).update(last_sent_at=timezone.now())
    return "sent"


@shared_task(name="botapi.tasks.notify_user_telegram", ignore_result=True)
def notify_user_telegram(user_id, kind, text, *, url=None, url_label=None, video_url=None):
    """Написать пользователю, если он этого ждёт.

    kind — один из bonus/ready/topup/referral/marketing: у каждого свой
    переключатель, чтобы человек мог отключить только то, что ему не нужно.
    """
    if not _enabled():
        return "disabled"
    chat = TelegramChat.objects.filter(user_id=user_id).first()
    if not chat or not chat.wants(kind):
        return "skipped"
    markup = None
    if url and url_label:
        markup = {"inline_keyboard": [[{"text": url_label, "url": url}]]}
    send_telegram_message.delay(chat.chat_id, text, reply_markup=markup,
                                video_url=video_url, kind=kind)
    return "queued"


@shared_task(name="botapi.tasks.broadcast_telegram", ignore_result=True)
def broadcast_telegram(kind, text_by_lang, user_ids=None):
    """Разослать одинаковое сообщение — по одному в секунду на двадцать человек.

    Ежедневный бонус приходит сразу тысячам людей; если поставить всё в очередь
    без разбега, Telegram ответит отказом и часть людей ничего не получит.
    """
    if not _enabled():
        return {"status": "disabled"}
    chats = TelegramChat.objects.filter(is_blocked=False)
    if user_ids:
        chats = chats.filter(user_id__in=list(user_ids))
    chats = chats.filter(**{f"notify_{kind}": True}) if kind in (
        "bonus", "ready", "topup", "referral", "marketing") else chats

    queued = 0
    for index, chat in enumerate(chats.iterator(chunk_size=500)):
        text = text_by_lang.get(chat.lang) or text_by_lang.get("ru") or ""
        if not text:
            continue
        send_telegram_message.apply_async(
            args=[chat.chat_id, text],
            kwargs={"kind": kind},
            countdown=index // BROADCAST_RATE,
        )
        queued += 1
    logger.info("telegram broadcast %s: поставлено %s", kind, queued)
    return {"status": "ok", "queued": queued}


def notify(user, kind, text, **kwargs) -> None:
    """Безопасная точка вызова из чужого кода: никогда не роняет вызвавшего."""
    try:
        if not user or not getattr(user, "pk", None):
            return
        notify_user_telegram.delay(user.pk, kind, text, **kwargs)
    except Exception:
        logger.exception("telegram notify не поставился")


__all__ = ["send_telegram_message", "notify_user_telegram", "broadcast_telegram", "notify", "escape"]
