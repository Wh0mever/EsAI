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
    """Недостаточно токенов на балансе для списания.

    balance — сколько можно списать прямо сейчас (при respect_reserves — баланс
    минус резервы; этим числом привычный путь «спишем сколько есть» и
    списывает). total — весь баланс: его и показывать человеку.
    """

    def __init__(self, message: str = "insufficient_tokens", *, balance: int = 0, required: int = 0,
                 total: int | None = None):
        super().__init__(message)
        self.balance = balance
        self.required = required
        self.total = balance if total is None else total


def _user_model():
    from django.contrib.auth import get_user_model
    return get_user_model()


def reserved_tokens(user) -> int:
    """Кредиты, обещанные генерациям, которые ещё идут: видео чата и бота,
    сцены мультстудии, дубли видеостудии, склейки (vstudio.reserve.total_reserved).

    Мягко: сбой подсчёта — 0 и warning там же, платящего не блокируем.
    """
    if not user or not getattr(user, "pk", None):
        return 0
    from vstudio.reserve import total_reserved

    return max(0, int(total_reserved(user) or 0))


def available_tokens(user, balance: int | None = None) -> int:
    """Свободный остаток: баланс минус все резервы.

    Им проверяют «хватит ли» мгновенные траты (текст и картинки чата, кадры и
    персонажи мультстудии, распознавание голоса). Иначе кредиты, обещанные
    ролику, который ещё снимается, уходили на чат, и за готовый ролик
    списывать было бы нечего. balance — уже прочитанный баланс (иначе свежий из БД).
    """
    if not user or not getattr(user, "pk", None):
        return 0
    if balance is None:
        balance = int(_user_model().objects.filter(pk=user.pk).values_list(
            "token_balance", flat=True).first() or 0)
    return max(0, int(balance or 0) - reserved_tokens(user))


def charge_tokens(user, amount: int, reason: str, meta=None, *, respect_reserves: bool = False) -> int:
    """Атомарно списать `amount` токенов с баланса пользователя.

    Не уходит ниже 0. Если баланса не хватает — raise InsufficientTokens
    (ничего не списывается). Возвращает новый баланс.

    respect_reserves=True — для мгновенных трат: списать можно только
    свободный остаток (баланс минус резервы идущих генераций, считается под
    замком строки пользователя). Выдача самих резервных генераций (видео,
    сцена, дубль студии) зовёт без флага: её собственный резерв и есть то,
    из чего она платит.
    """
    amount = int(amount or 0)
    if amount < 0:
        raise ValueError("amount must be non-negative for charge_tokens")

    User = _user_model()
    with transaction.atomic():
        locked = User.objects.select_for_update().get(pk=user.pk)
        current = int(locked.token_balance or 0)
        spendable = current
        if respect_reserves and amount > 0:
            spendable = max(0, current - reserved_tokens(locked))
        if amount > spendable:
            raise InsufficientTokens(balance=spendable, required=amount, total=current)

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

    Сумма — settings.WELCOME_BONUS_TOKENS (по умолчанию 3000). Идемпотентно
    И атомарно: проверка «существует ли welcome-транзакция» и само начисление
    выполняются в ОДНОЙ transaction.atomic() под select_for_update по строке
    пользователя. Это сериализует параллельные вызовы (двойной клик/гонка
    сигналов): второй вызов дождётся блокировки и уже УВИДИТ welcome-транзакцию
    первого, поэтому бонус не задвоится.
    """
    from django.conf import settings as dj_settings

    if not user or not getattr(user, "pk", None):
        return 0
    amount = int(getattr(dj_settings, "WELCOME_BONUS_TOKENS", 3000) or 0)
    try:
        # Runtime-оверрайд из админки; при любой ошибке остаётся settings-значение.
        from adminapi.runtime import get_runtime
        amount = int(get_runtime("WELCOME_BONUS_TOKENS", amount))
    except Exception:
        pass
    if amount <= 0:
        return int(getattr(user, "token_balance", 0) or 0)

    User = _user_model()
    with transaction.atomic():
        # Лочим строку пользователя ДО проверки exists — так параллельные вызовы
        # сериализуются, и второй увидит welcome-транзакцию, созданную первым.
        locked = User.objects.select_for_update().get(pk=user.pk)
        if TokenTransaction.objects.filter(user=locked, reason="welcome").exists():
            return int(locked.token_balance or 0)
        # credit_tokens возьмёт select_for_update по тому же пользователю в этой же
        # транзакции (повторный лок той же строки безопасен) и зафиксирует леджер.
        new_balance = credit_tokens(locked, amount, "welcome", meta={"source": "signup"})

    # Синхронизируем in-memory баланс переданного экземпляра для вызывающего.
    try:
        user.token_balance = new_balance
    except Exception:
        pass
    return new_balance


def set_balance_to(user, target: int, reason: str, meta=None) -> int:
    """Атомарно ДОВЕСТИ баланс пользователя до `target` (не суммирует).

    Используется для Daily Retention Bonus (ТЗ 3.3): если баланс ниже порога,
    он доводится до фикс. уровня (а НЕ прибавляется). Если текущий баланс уже
    >= target — ничего не делает и возвращает текущий баланс. Движение
    фиксируется в леджере (delta = target - current).
    """
    target = int(target or 0)
    if not user or not getattr(user, "pk", None):
        return 0

    User = _user_model()
    with transaction.atomic():
        locked = User.objects.select_for_update().get(pk=user.pk)
        current = int(locked.token_balance or 0)
        if current >= target:
            return current
        delta = target - current
        locked.token_balance = target
        locked.save(update_fields=["token_balance"])

        TokenTransaction.objects.create(
            user=locked,
            delta=delta,
            reason=reason,
            balance_after=target,
            meta=meta,
        )

    try:
        user.token_balance = target
    except Exception:
        pass
    return target


def estimated_min_charge(model_obj) -> int:
    """Минимальная пред-оценка списания за ОДИН запрос к модели (ТЗ 1.3).

    estimate = settings.MIN_REQUEST_ESTIMATE_TOKENS * markup_coefficient (>=1).
    Используется для блокировки запроса ДО обращения к OpenRouter, если баланса
    заведомо не хватит даже на минимальный ответ (анти-«кассовый разрыв»).
    """
    import math
    from django.conf import settings as dj_settings

    base = int(getattr(dj_settings, "MIN_REQUEST_ESTIMATE_TOKENS", 600) or 600)
    coeff = getattr(model_obj, "markup_coefficient", None)
    try:
        coeff_f = float(coeff) if coeff is not None else 1.0
    except Exception:
        coeff_f = 1.0
    # coeff = тариф за 1000 токенов → /TOKEN_CREDIT_DIVISOR (нормализация биллинга,
    # тот же делитель, что в ai.handlers — гейт обязан совпадать со списанием).
    try:
        divisor = float(getattr(dj_settings, "TOKEN_CREDIT_DIVISOR", 1000) or 1000)
    except Exception:
        divisor = 1000.0
    if divisor <= 0:
        divisor = 1000.0
    return max(1, math.ceil(base * coeff_f / divisor))


def clawback_tokens(user, amount: int, reason: str = "refund", meta=None) -> int:
    """Атомарно ИЗЪЯТЬ до `amount` токенов (возврат/chargeback).

    Списывает min(amount, текущий баланс) — НИКОГДА не уводит баланс ниже 0
    (если кредиты уже частично потрачены — изымаем сколько осталось). Возвращает
    ФАКТИЧЕСКИ изъятое количество. Движение фиксируется в леджере.
    Используется при реверсе платежа FreedomPay, чтобы не терять и деньги, и токены.
    """
    amount = int(amount or 0)
    if amount <= 0 or not user or not getattr(user, "pk", None):
        return 0

    User = _user_model()
    with transaction.atomic():
        locked = User.objects.select_for_update().get(pk=user.pk)
        current = int(locked.token_balance or 0)
        debited = min(amount, current)
        if debited <= 0:
            return 0
        new_balance = current - debited
        locked.token_balance = new_balance
        locked.save(update_fields=["token_balance"])

        TokenTransaction.objects.create(
            user=locked,
            delta=-debited,
            reason=reason,
            balance_after=new_balance,
            meta=meta,
        )

    try:
        user.token_balance = new_balance
    except Exception:
        pass
    return debited


# Откуда берутся кредиты, которые можно передать другому человеку: куплены,
# заработаны на рефералах или сами получены переводом.
TRANSFERABLE_IN_REASONS = ("purchase", "referral", "transfer_in")


def _creator_credits_left(user) -> int:
    """Creator Credits нельзя переводить: сколько их ещё лежит на балансе."""
    try:
        from creators.credits import remaining
        return int(remaining(user) or 0)
    except Exception:
        return 0


def transferable_tokens(user) -> int:
    """Сколько кредитов человек может перевести другому.

    Подарочные кредиты (ежедневный и приветственный бонусы, промокоды, ручные
    начисления админа) переводить нельзя: иначе десяток бесплатных аккаунтов
    каждый день сливал бы свои бонусы на один основной, а после покупки с
    мгновенным переводом и чарджбэком изымать было бы уже нечего.

    Считаем «платные» поступления минус уже отправленное и изъятое при
    возвратах, и не больше текущего баланса (потрачено в первую очередь
    подарочное — так выгоднее человеку).
    """
    from django.db.models import Q, Sum

    if not user or not getattr(user, "pk", None):
        return 0
    rows = TokenTransaction.objects.filter(user_id=user.pk)
    came_in = rows.filter(reason__in=TRANSFERABLE_IN_REASONS, delta__gt=0).aggregate(
        s=Sum("delta"))["s"] or 0
    went_out = rows.filter(Q(reason="transfer_out") | Q(reason="refund", delta__lt=0),
                           delta__lt=0).aggregate(s=Sum("delta"))["s"] or 0
    balance = int(_user_model().objects.filter(pk=user.pk).values_list(
        "token_balance", flat=True).first() or 0)
    # Обещанное за видео и сцены, которые ещё снимаются (чат, бот, мультстудия,
    # видеостудия), не переводится: «запустил и сразу перевёл другу» — и платить
    # за готовый ролик было бы нечем.
    from vstudio.reserve import total_reserved

    balance = max(0, balance - total_reserved(user))
    # Creator Credits выданы на контент и другому человеку не уходят: без этого
    # «купил 100, потратил 100, получил 100 от EsAI» давало бы 100 к переводу.
    balance = max(0, balance - _creator_credits_left(user))
    return max(0, min(balance, int(came_in) + int(went_out)))
