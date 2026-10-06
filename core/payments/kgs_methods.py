"""Способы оплаты в сомах, которые человек выбирает у нас.

Зачем. Нажав «оплатить в сомах», человек попадал на страницу FreedomPay с
десятком способов, терялся и уходил. Теперь выбор делается на нашей стороне.

Способов два вида:

* единый QR («elqr») — это GoPay и наш собственный экран оплаты: свой
  провайдер, своя таблица счетов, свои уведомления и сверка (payments/gopay).
  Кнопка появляется, когда GoPay настроен и включён для этого человека, —
  в списке включённых способов (kgs_methods_enabled) её нет и быть не может;
* всё остальное — FreedomPay: на него уезжает уже готовый ответ, параметр
  init_payment, который сразу открывает нужное приложение банка или форму
  карты. Провайдер, заказ, уведомления и сверка тут прежние.

FreedomPay единый QR дать не смог. Его настройка kgs_elqr_ps_code оставлена
как задел на случай, если код всё же выдадут, но кнопку она не показывает и в
FreedomPay из неё ничего не уходит: второй кнопки QR быть не должно.

Режим намеренно не булев (как у крипты, payments/crypto/registry.py):
  off   — выбора нет ни у кого, оплата идёт как раньше;
  staff — выбор видят только сотрудники: так проверяют боевые коды банков,
          пока обычные люди платят как платили;
  on    — выбор открыт всем.
Выключателей два: этот режим пускает человека к выбору, а режим GoPay
(payments/gopay/config.py) решает, есть ли в выборе единый QR.
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
    # Единый QR — это GoPay и наш экран оплаты: параметров FreedomPay у него нет.
    "elqr":    ("qr",   None),
    "mbank":   ("app",  {"pg_payment_system": "MBANKKGS"}),
    "odengi":  ("app",  {"pg_payment_system": "ODENGIKGSV2"}),
    "balance": ("app",  {"pg_payment_system": "BEELINEKGS"}),
    "megapay": ("app",  {"pg_payment_system": "MEGAPAYKGS"}),
    "card":    ("card", {"pg_payment_method": "bankcard"}),
}
# В этом порядке кнопки показываются человеку: единый QR, банки, карта последней.
ORDER = ("elqr", "mbank", "odengi", "balance", "megapay", "card")

# Из способов FreedomPay по умолчанию включена только карта: банки Кыргызстана
# платят единым QR через GoPay, а за FreedomPay оставлены Visa, Mastercard и
# Элкарт. Кнопки кошельков (MBANK, О!Деньги, MegaPay, Balance.kg) остались в
# коде и включаются галочками в админке.
DEFAULT_ENABLED = "card"
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
    """Код единого QR у FreedomPay (пусто — не выдан или записан с ошибкой).

    Сейчас ни на что не влияет: единый QR идёт через GoPay. Читается только
    админкой — на случай, если FreedomPay код всё же выдаст.
    """
    value = str(_runtime("kgs_elqr_ps_code", "") or "").strip()
    return value if ELQR_CODE_RE.fullmatch(value) else ""


def normalize_enabled(raw) -> tuple[list[str], list[str]]:
    """Разобрать список способов: (известные — в порядке показа, неизвестные).

    Единый QR в список не входит: это не способ FreedomPay, его включает
    настройка GoPay.
    """
    items = raw if isinstance(raw, (list, tuple)) else str(raw or "").split(",")
    picked = [str(item).strip().lower() for item in items if str(item).strip()]
    unknown = [key for key in dict.fromkeys(picked) if key not in METHODS]
    known = [key for key in ORDER if key in picked and key != "elqr"]
    return known, unknown


def enabled_keys() -> list[str]:
    """Способы FreedomPay, включённые в админке, в порядке показа. Единого QR здесь нет."""
    try:
        known, _unknown = normalize_enabled(_runtime("kgs_methods_enabled", DEFAULT_ENABLED))
        return [key for key in ORDER if key in known]
    except Exception:  # noqa: BLE001
        return []


def _is_staff(user) -> bool:
    try:
        return bool(user is not None and getattr(user, "is_authenticated", False)
                    and (getattr(user, "is_staff", False) or getattr(user, "is_superuser", False)))
    except Exception:  # noqa: BLE001 — проверка прав не должна ронять оплату
        return False


def keys_for(is_staff: bool) -> list[str]:
    """Способы для аудитории (сотрудник / все остальные), в порядке показа. Пусто — выбора нет."""
    try:
        current = mode()
        if current == MODE_OFF or (current == MODE_STAFF and not is_staff):
            return []
        keys = enabled_keys()
        from payments.gopay import config as gopay_config

        if gopay_config.enabled_for(bool(is_staff)):
            keys = ["elqr", *keys]
        # Одна кнопка «картой» — это не выбор, а лишний шаг перед той же страницей.
        if not any(METHODS[key][0] != "card" for key in keys):
            return []
        return [key for key in ORDER if key in keys]
    except Exception:  # noqa: BLE001 — витрина и оплата не должны падать из-за выбора
        return []


def available_for(user=None) -> list[dict]:
    """Способы, которые показываем этому человеку. Пусто — выбора нет, платим как раньше."""
    try:
        items = []
        for key in keys_for(_is_staff(user)):
            item = {"key": key, "kind": METHODS[key][0]}
            if key == "elqr":
                from payments.gopay import config as gopay_config

                # Тестовая среда: QR не настоящий, экран оплаты должен это сказать.
                # Ключа нет вовсе, когда среда боевая.
                if gopay_config.env() == gopay_config.ENV_TEST:
                    item["test"] = True
            items.append(item)
        return items
    except Exception:  # noqa: BLE001 — витрина и оплата не должны падать из-за выбора
        return []


def is_available(key, user=None) -> bool:
    """Доступен ли способ этому человеку — для любого провайдера, не только FreedomPay."""
    try:
        return str(key or "").strip().lower() in {item["key"] for item in available_for(user)}
    except Exception:  # noqa: BLE001
        return False


def fp_params(key, user=None) -> dict | None:
    """Добавка к параметрам init_payment для способа; None — способ этому человеку недоступен."""
    try:
        key = str(key or "").strip().lower()
        if key == "elqr":
            # Единый QR параметром FreedomPay не бывает никогда.
            return None
        if key not in {item["key"] for item in available_for(user)}:
            return None
        return dict(METHODS[key][1])
    except Exception:  # noqa: BLE001
        return None
