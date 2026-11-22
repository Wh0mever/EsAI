"""Доступ к Creative Studio: режим off|staff|on и рубильник инструмента.

CREATIVE_MODE из окружения (по умолчанию staff), сверху — правка из админки
(runtime «creative_mode»): закрыть или открыть раздел без выкладки. Чтение
правки — в savepoint: сбой запроса к настройкам не ломает транзакцию запроса.
"""
from __future__ import annotations

import logging

from django.conf import settings
from django.db import transaction
from rest_framework.permissions import BasePermission

from .errors import CreativeError

logger = logging.getLogger(__name__)

MODES = ("off", "staff", "on")
RUNTIME_MODE_KEY = "creative_mode"


def settings_mode() -> str:
    mode = str(getattr(settings, "CREATIVE_MODE", "staff") or "staff").strip().lower()
    return mode if mode in MODES else "staff"


def runtime_mode() -> str:
    """Правка из админки или "" (не задана / не прочиталась)."""
    try:
        from adminapi.runtime import get_runtime

        with transaction.atomic():
            value = str(get_runtime(RUNTIME_MODE_KEY, "") or "").strip().lower()
        return value if value in MODES else ""
    except Exception:
        logger.debug("creative: правка creative_mode не прочиталась", exc_info=True)
        return ""


def creative_mode() -> str:
    return runtime_mode() or settings_mode()


def can_use(user, mode: str | None = None) -> bool:
    """on — все вошедшие; staff — только сотрудники; off — никто."""
    mode = mode or creative_mode()
    if not user or not getattr(user, "is_authenticated", False):
        return False
    if mode == "on":
        return True
    if mode == "staff":
        return bool(getattr(user, "is_staff", False))
    return False


class CreativeOpen(BasePermission):
    """403 creative_disabled, если режим не пускает этого человека."""

    def has_permission(self, request, view):
        if not can_use(request.user):
            raise CreativeError("creative_disabled")
        return True


def tool_rows() -> dict:
    """slug → CreativeTool (только существующие строки). Сбой — пусто (все включены)."""
    try:
        from .models import CreativeTool

        with transaction.atomic():
            return {row.slug: row for row in CreativeTool.objects.all()}
    except Exception:
        logger.warning("creative: настройки инструментов не прочитались", exc_info=True)
        return {}


def tool_enabled(slug: str, rows: dict | None = None) -> bool:
    rows = tool_rows() if rows is None else rows
    row = rows.get(slug)
    return True if row is None else bool(row.enabled)


__all__ = ["MODES", "creative_mode", "settings_mode", "runtime_mode", "can_use", "CreativeOpen",
           "tool_rows", "tool_enabled", "RUNTIME_MODE_KEY"]
