# -*- coding: utf-8 -*-
"""Напоминание о заканчивающихся кредитах (ТЗ клиента 09.11.2026).

Остаток считается от последнего купленного пакета: сколько начислила
последняя TokenTransaction(reason="purchase") — пакет вместе с бонусом.
Порогов два: 20 % (мягкое напоминание) и 10 % (заметное). Каждое — один раз
за цикл; цикл — от покупки до следующей покупки. Если баланс сразу упал ниже
10 %, показываем только 10 %: двадцатипроцентное после него уже не нужно.

Нехватку при попытке генерации (402 insufficient_balance) это не трогает:
там своё окно, здесь только напоминание заранее.
"""
from __future__ import annotations

from django.db import IntegrityError, transaction

LEVELS = (20, 10)


def _last_purchase(user):
    from .models import TokenTransaction

    return (TokenTransaction.objects
            .filter(user=user, reason="purchase", delta__gt=0)
            .order_by("-created_at", "-id")
            .only("id", "delta")
            .first())


def level_for(balance: int, base: int) -> int | None:
    """Самый низкий порог, до которого опустился баланс: 10, 20 или None."""
    if base <= 0:
        return None
    reached = [lvl for lvl in LEVELS if balance * 100 <= base * lvl]
    return min(reached) if reached else None


def pending_notice(user) -> dict | None:
    """Напоминание, которое пора показать, или None.

    {"level": 20|10, "cycle": id покупки, "base": кредитов в пакете}.
    """
    from .tiers import is_unlimited
    from .models import LowBalanceNotice

    if not user or not user.is_authenticated or is_unlimited(user):
        return None
    purchase = _last_purchase(user)
    if purchase is None:
        return None
    base = int(purchase.delta)
    balance = max(0, int(getattr(user, "token_balance", 0) or 0))
    level = level_for(balance, base)
    if level is None:
        return None
    seen = (LowBalanceNotice.objects.filter(user=user, cycle_tx_id=purchase.id)
            .values_list("shown_level", flat=True).first())
    if seen is not None and seen <= level:
        return None
    return {"level": level, "cycle": purchase.id, "base": base}


def mark_shown(user, level: int, cycle: int) -> bool:
    """Запомнить, что порог показан. False — цикл уже другой (была покупка) или порог неверный."""
    from .models import LowBalanceNotice

    if level not in LEVELS:
        return False
    purchase = _last_purchase(user)
    if purchase is None or purchase.id != cycle:
        return False
    try:
        with transaction.atomic():
            row, created = LowBalanceNotice.objects.select_for_update().get_or_create(
                user=user, defaults={"cycle_tx_id": cycle, "shown_level": level})
            if created:
                return True
            if row.cycle_tx_id != cycle:
                row.cycle_tx_id, row.shown_level = cycle, level
            elif row.shown_level is None or level < row.shown_level:
                row.shown_level = level
            else:
                return True
            row.save(update_fields=["cycle_tx_id", "shown_level", "updated_at"])
    except IntegrityError:
        # Две вкладки отметили показ одновременно — строка уже есть, это и нужно.
        pass
    return True
