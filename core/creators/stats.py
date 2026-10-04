"""Счётчики креатора и прогресс до следующего уровня.

Всё считается из строк, отдельных полей-счётчиков нет. Что не считается:
- подозрительная привязка (то же устройство, повторная регистрация) и
  погашенный аккаунт — не «регистрация»: цикл «/delete -> /start» и
  мультиаккаунты не поднимают ни счётчик, ни прогресс уровня;
- отменённые и аннулированные комиссии, а также комиссии подозрительных
  привязок — не «платящие», не «заказы» и не «продажи».

Пороги уровня только показываются. Уровень меняет администратор:
check_next_level шлёт уведомление, но поле level не трогает никогда.
"""
from __future__ import annotations

import logging
from decimal import ROUND_DOWN, Decimal

from django.db import transaction
from django.db.models import Count, Q, Sum

from . import notify
from .models import (
    Creator,
    CreatorClick,
    CreatorCommission,
    CreatorLevel,
    CreatorPublication,
    CreatorReferral,
)

logger = logging.getLogger("creators")

Q2 = Decimal("0.01")

# Комиссии, за которыми стоят настоящие деньги покупателя.
_LIVE = (CreatorCommission.Status.ACCRUED, CreatorCommission.Status.HELD)


def _empty() -> dict:
    return {"clicks": 0, "registrations": 0, "suspect_referrals": 0, "paying": 0, "orders": 0,
            "sales_usdt": Decimal("0.00"), "publications_approved": 0}


def counters_bulk(creator_ids: list[int]) -> dict[int, dict]:
    """Счётчики сразу для списка креаторов: число запросов от длины списка не зависит."""
    ids = [int(pk) for pk in dict.fromkeys(creator_ids or []) if pk]
    out = {pk: _empty() for pk in ids}
    if not ids:
        return out

    for row in (CreatorClick.objects.filter(creator_id__in=ids)
                .values("creator_id").annotate(n=Count("id"))):
        out[row["creator_id"]]["clicks"] = int(row["n"] or 0)

    referrals = (CreatorReferral.objects.filter(creator_id__in=ids, ended_at__isnull=True)
                 .values("creator_id")
                 .annotate(reg=Count("id", filter=Q(suspect=False, user__is_active=True)),
                           sus=Count("id", filter=Q(suspect=True))))
    for row in referrals:
        out[row["creator_id"]]["registrations"] = int(row["reg"] or 0)
        out[row["creator_id"]]["suspect_referrals"] = int(row["sus"] or 0)

    # is_active покупателя здесь намеренно не требуется: деньги действительно заплачены.
    commissions = (CreatorCommission.objects.filter(creator_id__in=ids, status__in=_LIVE)
                   .filter(Q(referral__isnull=True) | Q(referral__suspect=False))
                   .values("creator_id")
                   .annotate(paying=Count("buyer_pk", distinct=True),
                             orders=Count("payment_id", distinct=True),
                             sales=Sum("base_usd")))
    for row in commissions:
        entry = out[row["creator_id"]]
        entry["paying"] = int(row["paying"] or 0)
        entry["orders"] = int(row["orders"] or 0)
        entry["sales_usdt"] = Decimal(str(row["sales"] or 0)).quantize(Q2, rounding=ROUND_DOWN)

    for row in (CreatorPublication.objects
                .filter(creator_id__in=ids, status=CreatorPublication.Status.APPROVED)
                .values("creator_id").annotate(n=Count("id"))):
        out[row["creator_id"]]["publications_approved"] = int(row["n"] or 0)
    return out


def counters(creator) -> dict:
    return counters_bulk([creator.pk])[creator.pk]


def _progress(have: dict, nxt) -> dict:
    """Прогресс по готовым счётчикам; nxt — следующий уровень или None (уровень последний)."""

    def part(count, need) -> dict:
        count, need = int(count or 0), int(need or 0)
        return {"have": count, "need": need, "done": count >= need}

    publications = part(have["publications_approved"], getattr(nxt, "min_publications", 0))
    registrations = part(have["registrations"], getattr(nxt, "min_registrations", 0))
    paying = part(have["paying"], getattr(nxt, "min_paying", 0))
    return {
        "next_level": ({"key": nxt.key, "title": nxt.title,
                        "percent": str(Decimal(nxt.percent).quantize(Q2))}
                       if nxt is not None else None),
        "publications": publications,
        "registrations": registrations,
        "paying": paying,
        "conditions_met": bool(nxt is not None and publications["done"]
                               and registrations["done"] and paying["done"]),
    }


def progress(creator, *, counters: dict | None = None) -> dict:
    """Что осталось до следующего уровня. С готовыми counters счётчики заново не считаются."""
    have = counters if counters is not None else counters_bulk([creator.pk])[creator.pk]
    current = creator.level
    nxt = CreatorLevel.objects.filter(sort__gt=current.sort).order_by("sort").first()
    return _progress(have, nxt)


def progress_bulk(creators: list) -> dict[int, dict]:
    """creator.pk -> progress. Счётчики одной пачкой и один запрос уровней."""
    creators = list(creators or [])
    if not creators:
        return {}
    have = counters_bulk([creator.pk for creator in creators])
    levels = list(CreatorLevel.objects.order_by("sort"))
    sort_of = {level.pk: level.sort for level in levels}
    out = {}
    for creator in creators:
        current = sort_of.get(creator.level_id)
        nxt = None
        if current is not None:
            nxt = next((level for level in levels if level.sort > current), None)
        out[creator.pk] = _progress(have[creator.pk], nxt)
    return out


def check_next_level(creator) -> bool:
    """Сообщить креатору, что условия следующего уровня выполнены. Никогда не бросает.

    Уведомление одно на уровень: отметка ставится условным UPDATE, и из двух
    одновременных вызовов (две оплаты разом) напишет только один. Сам уровень
    не меняется — его подтверждает администратор.
    """
    try:
        with transaction.atomic():
            state = progress(creator)
            nxt = state["next_level"]
            if not state["conditions_met"] or not nxt:
                return False
            key = nxt["key"]
            if creator.next_level_notified == key:
                return False
            updated = (Creator.objects.filter(pk=creator.pk)
                       .exclude(next_level_notified=key).update(next_level_notified=key))
            if updated != 1:
                return False
            # Объект в руках вызывающего не должен затереть отметку при save().
            creator.next_level_notified = key
            notify.emit(creator, "next_level_ready", next_title=nxt["title"],
                        next_percent=nxt["percent"])
            return True
    except Exception:  # noqa: BLE001 — зовут из начисления комиссии
        logger.exception("creators.stats: check_next_level для креатора %s",
                         getattr(creator, "pk", None))
        return False
