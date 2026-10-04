"""Рубильник программы EsAI Creators.

Режим намеренно не булев (как у выбора способа оплаты, payments/kgs_methods.py):
  off   — программы нет: публичные адреса отвечают 404, привязки и начисления
          не делаются, оплаты идут по обычной реферальной программе;
  staff — программу видят и могут быть креаторами только сотрудники: так
          цепочку «код -> оплата -> комиссия -> вывод» проверяют на живом сайте;
  on    — открыто всем.

Отмена комиссий при возврате режим не читает: деньги должны сойтись, даже
если программу выключили.
"""
from __future__ import annotations

from decimal import Decimal

from django.conf import settings

MODE_OFF, MODE_STAFF, MODE_ON = "off", "staff", "on"
MODES = (MODE_OFF, MODE_STAFF, MODE_ON)

# Минимальная сумма вывода (ТЗ п.24). Комиссии с креатора нет.
MIN_PAYOUT_USDT = Decimal("10")
# Сколько после регистрации ещё можно ввести промокод креатора.
BIND_WINDOW_HOURS = 72
# Привязка по ссылке — только при регистрации (то же окно, что у обычной реф-ссылки).
LINK_WINDOW_MINUTES = 10

HOLD_DAYS_MAX = 90


def _runtime(key: str, default):
    try:
        from adminapi.runtime import get_runtime

        return get_runtime(key, default)
    except Exception:  # noqa: BLE001 — настройки не должны ронять оплату
        return default


def _is_staff(user) -> bool:
    return bool(user is not None and (getattr(user, "is_staff", False)
                                      or getattr(user, "is_superuser", False)))


def mode() -> str:
    value = str(_runtime("creators_mode",
                         str(getattr(settings, "CREATORS_MODE", MODE_STAFF)))).strip().lower()
    # Непонятное значение — программа выключена: оплаты идут прежним путём.
    return value if value in MODES else MODE_OFF


def is_off() -> bool:
    return mode() == MODE_OFF


def accrual_enabled() -> bool:
    """Привязки, переходы, начисление и дозачисление работают в staff и on."""
    return mode() != MODE_OFF


def enabled_for(user) -> bool:
    """Видит ли этот человек программу (публичная страница, заявка, кабинет)."""
    current = mode()
    if current == MODE_ON:
        return True
    if current == MODE_STAFF:
        return bool(user is not None and getattr(user, "is_authenticated", False)
                    and _is_staff(user))
    return False


def creator_usable(creator) -> bool:
    """Можно ли привязывать людей к этому креатору и считать его переходы."""
    if creator is None or creator.status != "active":
        return False
    current = mode()
    if current == MODE_OFF:
        return False
    # Аккаунт креатора отключён (администратором или /delete в боте): войти в
    # кабинет некому, значит и новых людей его код не привязывает.
    if not getattr(creator.user, "is_active", True):
        return False
    return current == MODE_ON or _is_staff(creator.user)


def payouts_enabled() -> bool:
    """Принимаются ли заявки на вывод (отдельный рубильник поверх режима)."""
    return bool(_runtime("creators_payouts_enabled",
                         bool(getattr(settings, "CREATORS_PAYOUTS_ENABLED", True))))


def hold_days() -> int:
    """Через сколько дней после начисления комиссия доступна к выводу."""
    try:
        default = int(getattr(settings, "CREATORS_HOLD_DAYS", 14))
    except (TypeError, ValueError):
        default = 14
    value = _runtime("creators_hold_days", default)
    try:
        value = int(value)
    except (TypeError, ValueError):
        value = default
    return max(0, min(HOLD_DAYS_MAX, value))
