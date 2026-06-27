"""Сигналы аудита: фиксируем вход пользователя в систему.

Используем django.contrib.auth signal `user_logged_in`, который шлёт и
обычный Django-логин, и allauth (allauth логинит через Django login()).
"""

from django.contrib.auth.signals import user_logged_in
from django.dispatch import receiver

from .services import log_event


def _client_ip(request):
    if request is None:
        return ""
    xff = request.META.get("HTTP_X_FORWARDED_FOR", "")
    if xff:
        return xff.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR", "") or ""


@receiver(user_logged_in)
def on_user_logged_in(sender, request, user, **kwargs):
    meta = {}
    try:
        meta = {
            "ip": _client_ip(request),
            "user_agent": (request.META.get("HTTP_USER_AGENT", "") if request else "")[:512],
            "email": getattr(user, "email", "") or "",
        }
    except Exception:
        meta = {}
    log_event(
        "login",
        message=f"Вход пользователя {getattr(user, 'email', user)}",
        user=user,
        meta=meta,
        level="info",
    )
