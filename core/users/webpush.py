"""Отправка Web Push уведомлений (Push API / VAPID) через pywebpush.

Держит две функции:
  * send_web_push — послать одну подписку (с обработкой протухших endpoint'ов);
  * notify_user — разослать всем подпискам пользователя и вернуть счётчики.

Импорт pywebpush ЛЕНИВЫЙ (внутри функции): отсутствие библиотеки не должно
ронять импорт модуля / старт приложения — просто вернём "error".
"""

from __future__ import annotations

import json
import logging

from django.conf import settings
from django.utils import timezone

from .models import WebPushSubscription

logger = logging.getLogger(__name__)


def send_web_push(
    sub: WebPushSubscription,
    title: str,
    body: str,
    url: str = "/",
    tag: str = "esai",
) -> str:
    """Послать одну web-push подписку.

    Возвращает:
      * "ok"      — доставлено (обновляем last_ok_at);
      * "expired" — подписка протухла (404/410) → удалена из БД;
      * "error"   — прочая ошибка (в т.ч. нет библиотеки) → залогировано.
    """
    # Ленивый импорт: отсутствие pywebpush не должно ронять импорт модуля/старт.
    try:
        from pywebpush import webpush, WebPushException
    except ImportError:
        logger.error("pywebpush не установлен — web-push не отправлен")
        return "error"

    subscription_info = {
        "endpoint": sub.endpoint,
        "keys": {"p256dh": sub.p256dh, "auth": sub.auth},
    }
    data = json.dumps({
        "title": title,
        "body": body,
        "url": url,
        "tag": tag,
        "icon": "/icon-192.png",
        "badge": "/icon-192.png",
    })

    try:
        webpush(
            subscription_info,
            data,
            vapid_private_key=settings.VAPID_PRIVATE_KEY,
            vapid_claims={"sub": settings.VAPID_SUBJECT},
        )
    except WebPushException as exc:
        status_code = getattr(getattr(exc, "response", None), "status_code", None)
        if status_code in (404, 410):
            # Подписка мертва (браузер отписался / endpoint удалён) — чистим.
            sub.delete()
            return "expired"
        logger.warning("web-push error sub=%s: %s", sub.pk, exc)
        return "error"
    except Exception as exc:  # noqa: BLE001 — любой сбой не должен ронять вызывающего
        logger.warning("web-push unexpected error sub=%s: %s", sub.pk, exc)
        return "error"

    sub.last_ok_at = timezone.now()
    sub.save(update_fields=["last_ok_at"])
    return "ok"


def notify_user(user, title: str, body: str, url: str = "/") -> dict:
    """Разослать пуш всем подпискам пользователя. Возвращает счётчики.

    Пустой набор подписок → {"sent": 0, "expired": 0, "error": 0}.
    """
    counters = {"sent": 0, "expired": 0, "error": 0}
    for sub in user.push_subs.all():
        result = send_web_push(sub, title, body, url=url)
        if result == "ok":
            counters["sent"] += 1
        elif result == "expired":
            counters["expired"] += 1
        else:
            counters["error"] += 1
    return counters
