"""Баланс креатора. В таблицах его нет — он считается из строк комиссий и выводов.

    earned    — «Заработано всего»: начисленные комиссии (accrued);
    pending   — «Ожидает выплаты»: ещё в холде плюс запрошено и не отправлено;
    available — «Доступно к выводу»;
    paid      — «Выплачено».

Пока долга нет, earned == pending + available + paid. Возврат оплаты после
выплаты уводит available_raw в минус: это долг (debt), его гасят следующие
комиссии. Придержанные комиссии (held) показываются отдельно и в earned не входят.

Любое решение о деньгах принимается по summary(), посчитанному ПОСЛЕ lock().
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_DOWN, Decimal

from django.db.models import Sum
from django.utils import timezone

from .models import Creator, CreatorCommission, CreatorWithdrawal

Q6 = Decimal("0.000001")
Q2 = Decimal("0.01")
ZERO = Decimal("0")

OPEN_WITHDRAWALS = ("review", "approved")


@dataclass(frozen=True)
class Balance:
    earned: Decimal
    pending: Decimal
    held: Decimal
    available: Decimal
    in_withdrawal: Decimal
    paid: Decimal
    debt: Decimal
    available_raw: Decimal


def lock(creator_id) -> Creator:
    """Блокировка строки креатора. Вызывающий уже внутри transaction.atomic()."""
    return Creator.objects.locked(creator_id)


def _sum(qs, field: str) -> Decimal:
    # SQLite отдаёт сумму числом с плавающей точкой — приводим через строку.
    return Decimal(str(qs.aggregate(s=Sum(field))["s"] or 0)).quantize(Q6)


def summary(creator, *, now=None) -> Balance:
    now = now or timezone.now()
    creator_id = getattr(creator, "pk", creator)
    commissions = CreatorCommission.objects.filter(creator_id=creator_id)
    accrued_rows = commissions.filter(status="accrued")
    accrued = _sum(accrued_rows, "amount_usdt")
    matured = _sum(accrued_rows.filter(available_at__lte=now), "amount_usdt")
    held = _sum(commissions.filter(status="held"), "amount_usdt")

    withdrawals = CreatorWithdrawal.objects.filter(creator_id=creator_id)
    w_open = _sum(withdrawals.filter(status__in=OPEN_WITHDRAWALS), "amount_usdt")
    w_paid = _sum(withdrawals.filter(status="paid"), "amount_usdt")

    available_raw = matured - w_open - w_paid
    return Balance(
        earned=accrued,
        pending=(accrued - matured) + w_open,
        held=held,
        available=max(ZERO, available_raw),
        in_withdrawal=w_open,
        paid=w_paid,
        debt=max(ZERO, -available_raw),
        available_raw=available_raw,
    )


def earned_bulk(creator_ids) -> dict[int, Decimal]:
    """«Заработано всего» сразу по списку креаторов — одним запросом."""
    ids = list(creator_ids or [])
    result = {int(pk): ZERO.quantize(Q6) for pk in ids}
    if not ids:
        return result
    rows = (CreatorCommission.objects.filter(creator_id__in=ids, status="accrued")
            .values("creator_id").annotate(s=Sum("amount_usdt")))
    for row in rows:
        result[row["creator_id"]] = Decimal(str(row["s"] or 0)).quantize(Q6)
    return result


def as_json(b: Balance) -> dict:
    """Цифры кабинета строками с двумя знаками. Округляем вниз: больше, чем есть, не показываем."""
    names = ("earned", "pending", "held", "available", "in_withdrawal", "paid", "debt")
    return {name: str(getattr(b, name).quantize(Q2, rounding=ROUND_DOWN)) for name in names}
