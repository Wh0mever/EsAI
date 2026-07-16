"""Tier-логика EsAI (ТЗ клиента, Этап 3) — единый источник правды.

user_tier:
  - guest — неавторизованный посетитель
  - free  — авторизован, но ещё не платил (User.is_paid == False)
  - paid  — есть хотя бы одна успешная оплата (User.is_paid == True)

«Бесплатная» модель = markup_coefficient <= settings.FREE_MODEL_MAX_COEFF (=1).
Гость и free-пользователь могут использовать ТОЛЬКО бесплатные модели;
премиум (×6/×15/×20) — только paid (ТЗ 4.1).
"""
from __future__ import annotations

from decimal import Decimal

from django.conf import settings

TIER_GUEST = "guest"
TIER_FREE = "free"
TIER_PAID = "paid"


def is_unlimited(user) -> bool:
    """Безлимитный тестовый аккаунт (User.is_unlimited): доступ как у paid +
    снятый дневной лимит. Денежный код не обходит — баланс всё равно списывается.
    """
    return bool(user and getattr(user, "is_unlimited", False))


def user_tier(user) -> str:
    """Вернуть тир пользователя: 'guest' | 'free' | 'paid'."""
    if not user or not getattr(user, "is_authenticated", False):
        return TIER_GUEST
    # Безлимитный тест-аккаунт ведёт себя как paid (все модели, без лимитов).
    if is_unlimited(user) or bool(getattr(user, "is_paid", False)):
        return TIER_PAID
    return TIER_FREE


def is_paid_tier(user) -> bool:
    return user_tier(user) == TIER_PAID


def is_free_tier(user) -> bool:
    """guest ИЛИ free — то есть «бесплатный/бонусный аккаунт» в терминах ТЗ."""
    return user_tier(user) in (TIER_GUEST, TIER_FREE)


def free_model_max_coeff() -> Decimal:
    try:
        return Decimal(str(getattr(settings, "FREE_MODEL_MAX_COEFF", 1.0)))
    except Exception:
        return Decimal("1.0")


def model_is_free(model_obj) -> bool:
    """True, если модель доступна на бесплатном тарифе.

    Источник правды — ЯВНЫЙ флаг GPTModels.free_tier (его выставляет админ).
    После нормализации биллинга «бесплатность» расцеплена с тарифом: бесплатная
    модель может иметь markup_coefficient > 1 (напр. Gemini=11). Если поля нет
    (старые объекты/моки) — legacy-фолбэк по коэффициенту (≤ порога).
    """
    if model_obj is None:
        return False
    flag = getattr(model_obj, "free_tier", None)
    if flag is not None:
        return bool(flag)
    # Legacy-фолбэк (поле недоступно): старое правило «коэф. ≤ порога».
    coeff = getattr(model_obj, "markup_coefficient", None)
    if coeff is None:
        return False
    try:
        return Decimal(str(coeff)) <= free_model_max_coeff()
    except Exception:
        return False


def can_use_model(user, model_obj) -> bool:
    """Доступна ли модель данному пользователю по его тиру (ТЗ 4.1).

    paid → любая модель; guest/free → только бесплатные (×1).
    """
    if is_paid_tier(user):
        return True
    return model_is_free(model_obj)


def daily_request_limit(user) -> int:
    """Дневной лимит запросов по тиру (ТЗ 5.1). guest считается отдельно по IP."""
    if is_unlimited(user):
        return 1_000_000_000  # безлимитный тест-аккаунт — лимит фактически снят
    if is_paid_tier(user):
        limit = int(getattr(settings, "PAID_DAILY_REQUESTS", 300) or 300)
        key = "PAID_DAILY_REQUESTS"
    else:
        limit = int(getattr(settings, "FREE_DAILY_REQUESTS", 20) or 20)
        key = "FREE_DAILY_REQUESTS"
    try:
        # Runtime-оверрайд из админки; при любой ошибке остаётся settings-значение.
        from adminapi.runtime import get_runtime
        limit = int(get_runtime(key, limit))
    except Exception:
        pass
    return limit
