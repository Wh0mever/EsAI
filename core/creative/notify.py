"""Уведомления Creative Studio.

1. Человеку — «готово» / «не получилось»: веб-пуш и колокольчик (как
   vstudio.notify). Не шлём, если работе меньше 60 с, если страница раздела
   открыта (опрос jobs/ ставит creative:seen:<user_id> на 30 с) и если человек
   сам отменил работу.
2. Сотрудникам — сигнал, что поставщик отказал (нет денег на счёте, ключ
   отключён): колокольчик всем is_staff и сообщение в Telegram сотрудникам, у
   которых привязан бот. Не чаще раза в 15 минут на код.

Тексты нейтральные: поставщика не называем (уведомления видят в браузере).
Любой сбой глотается — это вежливость, а не часть денег.
"""
from __future__ import annotations

import logging
from datetime import timedelta

from django.core.cache import cache
from django.utils import timezone

from .models import JOB_DONE, JOB_FAILED, JOB_LOST, JOB_NSFW, CreativeJob

logger = logging.getLogger(__name__)

MIN_AGE = timedelta(seconds=60)
SEEN_TTL_S = 30
NOTIFY_STATUSES = (JOB_DONE, JOB_FAILED, JOB_NSFW, JOB_LOST)
ALERT_TTL_S = 15 * 60
ALERT_KEY = "creative:alert:{code}"

TITLE_DONE = {"video": "Видео готово", "image": "Картинка готова", "character": "Персонаж готов"}
TITLE_FAILED = {"video": "Видео не получилось", "image": "Картинка не получилась",
                "character": "Персонаж не получился"}
BODY_DONE = "Откройте Creative Studio, чтобы посмотреть."
BODY_FAILED = "Кредиты не списаны."
BODY_NSFW = "Запрос отклонила модерация. Кредиты не списаны."

ALERT_TEXTS = {
    "provider_unavailable": ("Creative Studio: генерации остановлены",
                             "Поставщик генераций отказал (нет денег на счёте или ключ отключён). "
                             "Новые запуски временно отклоняются, резервы людей сняты."),
    "provider_key": ("Creative Studio: ключ не принят",
                     "Поставщик генераций не принял ключ доступа. Проверьте ключ на сервере."),
}


def seen_key(user_id) -> str:
    return f"creative:seen:{user_id}"


def mark_seen(user_id) -> None:
    if not user_id:
        return
    try:
        cache.set(seen_key(user_id), 1, SEEN_TTL_S)
    except Exception:
        pass


def is_seen(user_id) -> bool:
    try:
        return bool(cache.get(seen_key(user_id)))
    except Exception:
        return False


def job_url(job) -> str:
    return f"/creative/{job.tool_slug}?job={job.uid}"


def texts(job) -> tuple[str, str]:
    kind = job.kind if job.kind in TITLE_DONE else "image"
    if job.status == JOB_DONE:
        return TITLE_DONE[kind], BODY_DONE
    if job.status == JOB_NSFW:
        return TITLE_FAILED[kind], BODY_NSFW
    body = str(job.error or "").strip() or BODY_FAILED
    if "не списан" not in body:
        body = f"{body} {BODY_FAILED}"
    return TITLE_FAILED[kind], body[:180]


def should_notify(job, *, now=None) -> bool:
    if job is None or job.status not in NOTIFY_STATUSES:
        return False
    now = now or timezone.now()
    created = getattr(job, "created_at", None)
    if created is not None and now - created < MIN_AGE:
        return False
    return not is_seen(job.user_id)


def wanted(job_id, *, now=None) -> bool:
    try:
        row = CreativeJob.objects.filter(pk=job_id).values("status", "created_at", "user_id").first()
    except Exception:
        return False
    if not row:
        return False
    return should_notify(CreativeJob(status=row["status"], created_at=row["created_at"],
                                     user_id=row["user_id"]), now=now)


def notify_job(job, *, now=None) -> bool:
    try:
        if not should_notify(job, now=now):
            return False
        title, body = texts(job)
        url = job_url(job)
        user = job.user
    except Exception:
        logger.exception("creative: уведомление не собралось job=%s", getattr(job, "uid", "?"))
        return False
    try:
        from users.models import Notification

        note = Notification.objects.create(title=title, body=body)
        note.add_recipients([user])
    except Exception:
        logger.exception("creative: уведомление не записалось job=%s", job.uid)
    try:
        from users.webpush import notify_user

        notify_user(user, title, body, url=url)
    except Exception:
        logger.warning("creative: пуш не ушёл job=%s", job.uid, exc_info=True)
    return True


def notify_job_id(job_id, *, now=None) -> bool:
    try:
        job = CreativeJob.objects.select_related("user").filter(pk=job_id).first()
    except Exception:
        return False
    return notify_job(job, now=now) if job is not None else False


# ---------------------------------------------------------------- сигнал сотрудникам

def staff_alert(code: str, *, note: str = "") -> bool:
    """Колокольчик всем сотрудникам + Telegram (если бот включён). Раз в 15 минут на код."""
    try:
        if not cache.add(ALERT_KEY.format(code=code), 1, ALERT_TTL_S):
            return False
    except Exception:
        pass
    title, body = ALERT_TEXTS.get(code, ("Creative Studio: сбой", "Проверьте журнал генераций."))
    if note:
        body = f"{body} ({note[:120]})"
    logger.error("creative: сигнал сотрудникам %s: %s", code, note[:200])
    try:
        from django.contrib.auth import get_user_model

        from users.models import Notification

        staff = list(get_user_model().objects.filter(is_staff=True, is_active=True))
        if staff:
            alert = Notification.objects.create(title=title, body=body)
            alert.add_recipients(staff)
    except Exception:
        logger.exception("creative: колокольчик сотрудникам не записался")
    try:
        from botapi.models import TelegramChat
        from botapi.tasks import _enabled, send_telegram_message
        from botapi.telegram import escape

        if _enabled():
            chats = TelegramChat.objects.filter(user__is_staff=True, user__is_active=True,
                                                is_blocked=False).values_list("chat_id", flat=True)
            text = f"<b>{escape(title)}</b>\n{escape(body)}"
            for chat_id in chats:
                send_telegram_message.delay(chat_id, text, kind="staff")
    except Exception:
        logger.warning("creative: Telegram сотрудникам не ушёл", exc_info=True)
    return True


__all__ = ["mark_seen", "is_seen", "notify_job", "notify_job_id", "wanted", "staff_alert",
           "texts", "should_notify", "job_url"]
