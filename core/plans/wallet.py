"""Сервис атомарного списания/начисления токенов (pay-as-you-go).

Все мутации баланса проходят через эти функции, чтобы гарантировать:
- атомарность (transaction.atomic + select_for_update по строке пользователя);
- баланс не уходит ниже 0;
- каждое движение фиксируется в леджере TokenTransaction (для аудита).
"""
from __future__ import annotations

from django.db import transaction

from .models import TokenTransaction


class InsufficientTokens(Exception):
    """Недостаточно токенов на балансе для списания."""

    def __init__(self, message: str = "insufficient_tokens", *, balance: int = 0, required: int = 0):
        super().__init__(message)
        self.balance = balance
        self.required = required


def _user_model():
    from django.contrib.auth import get_user_model
    return get_user_model()


def charge_tokens(user, amount: int, reason: str, meta=None) -> int:
    """Атомарно списать `amount` токенов с баланса пользователя.

    Не уходит ниже 0. Если баланса не хватает — raise InsufficientTokens
    (ничего не списывается). Возвращает новый баланс.
    """
    amount = int(amount or 0)
    if amount < 0:
        raise ValueError("amount must be non-negative for charge_tokens")

    User = _user_model()
    with transaction.atomic():
        locked = User.objects.select_for_update().get(pk=user.pk)
        current = int(locked.token_balance or 0)
        if amount > current:
            raise InsufficientTokens(balance=current, required=amount)

        new_balance = current - amount
        locked.token_balance = new_balance
        locked.save(update_fields=["token_balance"])

        TokenTransaction.objects.create(
            user=locked,
            delta=-amount,
            reason=reason,
            balance_after=new_balance,
            meta=meta,
        )

    # Keep the in-memory instance in sync for the caller.
    try:
        user.token_balance = new_balance
    except Exception:
        pass
    return new_balance


def credit_tokens(user, amount: int, reason: str, meta=None) -> int:
    """Атомарно начислить `amount` токенов на баланс пользователя.

    Возвращает новый баланс.
    """
    amount = int(amount or 0)
    if amount < 0:
        raise ValueError("amount must be non-negative for credit_tokens")

    User = _user_model()
    with transaction.atomic():
        locked = User.objects.select_for_update().get(pk=user.pk)
        current = int(locked.token_balance or 0)
        new_balance = current + amount
        locked.token_balance = new_balance
        locked.save(update_fields=["token_balance"])

        TokenTransaction.objects.create(
            user=locked,
            delta=amount,
            reason=reason,
            balance_after=new_balance,
            meta=meta,
        )

    try:
        user.token_balance = new_balance
    except Exception:
        pass
    return new_balance


def has_tokens(user) -> bool:
    """True, если у пользователя положительный баланс токенов."""
    if not user or not getattr(user, "pk", None):
        return False
    try:
        return int(getattr(user, "token_balance", 0) or 0) > 0
    except Exception:
        return False


def grant_welcome_bonus(user) -> int:
    """Начислить приветственный бонус новому пользователю ОДИН раз.

    Сумма — settings.WELCOME_BONUS_TOKENS (по умолчанию 3000). Идемпотентно:
    повторно не начисляет (по наличию TokenTransaction reason='welcome').
    """
    from django.conf import settings as dj_settings

    if not user or not getattr(user, "pk", None):
        return 0
    amount = int(getattr(dj_settings, "WELCOME_BONUS_TOKENS", 3000) or 0)
    if amount <= 0:
        return int(getattr(user, "token_balance", 0) or 0)
    if TokenTransaction.objects.filter(user=user, reason="welcome").exists():
        return int(getattr(user, "token_balance", 0) or 0)
    return credit_tokens(user, amount, "welcome", meta={"source": "signup"})
