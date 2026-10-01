"""Способы оплаты в сомах, которые человек выбирает у нас до ухода на FreedomPay.

Зачем. Нажав «оплатить в сомах», человек попадал на страницу FreedomPay с
десятком способов, терялся и уходил. Теперь выбор делается на нашей стороне,
а на FreedomPay уезжает уже готовый ответ: параметр init_payment, который
сразу открывает нужное приложение банка или форму карты.

Провайдер, заказ, уведомления и сверка остаются прежними: меняются только
параметры init_payment, поэтому ни новой таблицы, ни миграции здесь нет.

Режим намеренно не булев (как у крипты, payments/crypto/registry.py):
  off   — выбора нет ни у кого, оплата идёт как раньше;
  staff — выбор видят только сотрудники: так проверяют боевые коды банков,
          пока обычные люди платят как платили;
  on    — выбор открыт всем.
"""
from __future__ import annotations

import re

from django.conf import settings

MODE_OFF = "off"
MODE_STAFF = "staff"
MODE_ON = "on"
MODES = (MODE_OFF, MODE_STAFF, MODE_ON)

# ключ -> (вид кнопки, добавка к параметрам init_payment)
METHODS = {
    # Код единого QR FreedomPay выдаёт каждому магазину отдельно — он лежит в
    # настройках (kgs_elqr_ps_code), а не в коде.
    "elqr":    ("qr",   None),
    "mbank":   ("app",  {"pg_payment_system": "MBANKKGS"}),
    "odengi":  ("app",  {"pg_payment_system": "ODENGIKGSV2"}),
    "balance": ("app",  {"pg_payment_system": "BEELINEKGS"}),
    "megapay": ("app",  {"pg_payment_system": "MEGAPAYKGS"}),
    "card":    ("card", {"pg_payment_method": "bankcard"}),
}
# В этом порядке кнопки показываются человеку: сначала банки, карта последней.
ORDER = ("elqr", "mbank", "odengi", "balance", "megapay", "card")

# Balance.kg по умолчанию выключен: у магазина он не подключён (страница оплаты
# FreedomPay 02.10.2026 отдаёт только MBANK, О!Деньги, MegaPay и карту), и кнопка
# вела бы в ошибку. Подключат — включается галочкой в админке.
DEFAULT_ENABLED = "mbank,odengi,megapay,card"
# Код уходит в FreedomPay как есть и попадает под подпись — пускаем только то,
# что похоже на код платёжной системы, а не произвольную строку из админки.
ELQR_CODE_RE = re.compile(r"[A-Za-z0-9_]{3,32}")


def _runtime(key: str, default):
    try:
        from adminapi.runtime import get_runtime

        return get_runtime(key, default)
    except Exception:  # noqa: BLE001 — настройки не должны ронять оплату
        return default


def mode() -> str:
    value = str(_runtime("kgs_methods_mode",
                         str(getattr(settings, "KGS_METHODS_MODE", MODE_STAFF)))).strip().lower()
    # Непонятное значение — выбора нет: оплата идёт проверенным прежним путём.
    return value if value in MODES else MODE_OFF


def elqr_code() -> str:
    """Код единого QR у FreedomPay (пусто — не выдан или записан с ошибкой)."""
    value = str(_runtime("kgs_elqr_ps_code", "") or "").strip()
    return value if ELQR_CODE_RE.fullmatch(value) else ""


def normalize_enabled(raw) -> tuple[list[str], list[str]]:
    """Разобрать список способов: (известные — в порядке показа, неизвестные).

    Единый QR в список не входит: он включается сам, когда задан его код,
    и без кода всё равно не работает.
    """
    items = raw if isinstance(raw, (list, tuple)) else str(raw or "").split(",")
    picked = [str(item).strip().lower() for item in items if str(item).strip()]
    unknown = [key for key in dict.fromkeys(picked) if key not in METHODS]
    known = [key for key in ORDER if key in picked and key != "elqr"]
    return known, unknown


def enabled_keys() -> list[str]:
    """Способы, включённые в админке, в порядке показа."""
    try:
        known, _unknown = normalize_enabled(_runtime("kgs_methods_enabled", DEFAULT_ENABLED))
        if elqr_code():
            known.append("elqr")
        return [key for key in ORDER if key in known]
    except Exception:  # noqa: BLE001
        return []


def available_for(user=None) -> list[dict]:
    """Способы, которые показываем этому человеку. Пусто — выбора нет, платим как раньше."""
    try:
        current = mode()
        if current == MODE_OFF:
            return []
        if current == MODE_STAFF and not (
                user is not None and getattr(user, "is_authenticated", False)
                and (user.is_staff or user.is_superuser)):
            return []
        keys = enabled_keys()
        # Одна кнопка «картой» — это не выбор, а лишний шаг перед той же страницей.
        if not any(METHODS[key][0] != "card" for key in keys):
            return []
        return [{"key": key, "kind": METHODS[key][0]} for key in keys]
    except Exception:  # noqa: BLE001 — витрина и оплата не должны падать из-за выбора
        return []


def fp_params(key, user=None) -> dict | None:
    """Добавка к параметрам init_payment для способа; None — способ этому человеку недоступен."""
    try:
        key = str(key or "").strip().lower()
        if key not in {item["key"] for item in available_for(user)}:
            return None
        if key == "elqr":
            code = elqr_code()
            return {"pg_payment_system": code} if code else None
        return dict(METHODS[key][1])
    except Exception:  # noqa: BLE001
        return None
