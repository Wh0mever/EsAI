"""Сверка программы Creators: инварианты, которые обязаны выполняться всегда.

Только читает. Запускается командой creators_check и ночной задачей. Каждое
нарушение — либо ошибка в коде, либо правка мимо сервисов (SQL, Django admin):

    I1  одна комиссия на (платёж, часть)
    I2  сумма и база комиссии сходятся с независимыми данными платежа
    I3  с заказа не заплачено сразу и по обычной рефералке, и креатору
    I4  нет комиссии с собственной покупки креатора
    I5  выведено не больше, чем было доступно
    I6  у каждой выплаты есть TXID, TXID не повторяются
    I7  у возвращённого платежа не осталось живой комиссии
    I8  ручные действия покрыты журналом
    I9  уровень, статус и код креатора совпадают с журналом
    I10 у каждой покупки привязанного пользователя есть строка комиссии
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import timedelta
from decimal import ROUND_DOWN, Decimal

from django.conf import settings
from django.contrib.auth import get_user_model
from django.db.models import Count, F
from django.utils import timezone

from audit.models import AdminActionLog
from payments.models import Payment

from . import balance, commission, flags
from .models import (
    Creator,
    CreatorApplication,
    CreatorCode,
    CreatorCommission,
    CreatorReferral,
    CreatorWithdrawal,
)

Q6 = Decimal("0.000001")
ZERO = Decimal("0")
OPEN = commission.OPEN

CODES = ("I1", "I2", "I3", "I4", "I5", "I6", "I7", "I8", "I9", "I10")

# Во сколько раз база комиссии в сомах может превышать сумму оплаты по курсу из
# настроек окружения. Курс для начисления администратор вводит руками; опечатка
# на порядок (0.115 вместо 0.0115) укладывается в «сом не дороже доллара», но
# не в этот коридор.
KGS_RATE_TOLERANCE = Decimal("2")

# Сколько идентификаторов показывать в описании нарушения.
SAMPLE = 5


@dataclass(frozen=True)
class Violation:
    code: str
    level: str      # "fail" | "warn"
    detail: str
    count: int


def _violation(code: str, level: str, what: str, items) -> list[Violation]:
    items = list(items)
    if not items:
        return []
    sample = ", ".join(str(item) for item in items[:SAMPLE])
    more = f" и ещё {len(items) - SAMPLE}" if len(items) > SAMPLE else ""
    return [Violation(code, level, f"{what}: {sample}{more}", len(items))]


def _dec(value) -> Decimal:
    try:
        return Decimal(str(value if value is not None else "0"))
    except Exception:  # noqa: BLE001
        return ZERO


def _chunks(items, size=500):
    items = list(items)
    for start in range(0, len(items), size):
        yield items[start:start + size]


# ------------------------------------------------------------------- I1 ---

def _commission_keys():
    """(платёж, часть), встречающиеся больше одного раза."""
    return list(CreatorCommission.objects.values("payment_id", "part")
                .annotate(n=Count("id")).filter(n__gt=1)
                .values_list("payment_id", "part"))


def _i1() -> list[Violation]:
    return _violation("I1", "fail", "несколько комиссий на один платёж и часть",
                      [f"платёж {pid} часть «{part}»" for pid, part in _commission_keys()])


# ------------------------------------------------------------------- I2 ---

def _kgs_ceiling(payment) -> Decimal | None:
    """Сумма оплаты в сомах — потолок базы: сом никогда не дороже доллара."""
    if payment.provider == "freedompay":
        return _dec(payment.amount)
    req = payment.request or {}
    kgs = _dec(req.get("kgs_price"))
    if kgs > 0:
        return kgs
    rate = _dec(req.get("rate_kgs_to_rub"))
    return _dec(payment.amount) / rate if rate > 0 else None


def _i2() -> list[Violation]:
    bad_rows, bad_rates, over_base, over_reference, over_stars = [], [], [], [], []
    by_payment = defaultdict(list)
    reference_rate = _dec(settings.CURRENCY_KGS_TO_USD_RATE)

    rows = (CreatorCommission.objects.exclude(status="void")
            .select_related("payment", "payment__crypto_invoice").order_by("id"))
    for row in rows.iterator(chunk_size=500):
        by_payment[row.payment_id].append(row)
        if row.amount_usdt > 0:
            expected = (row.base_usd * row.percent / 100).quantize(Q6, rounding=ROUND_DOWN)
            if not (0 < row.percent <= 25) or row.amount_usdt != expected:
                bad_rows.append(row.pk)

    stars_rate = None
    for payment_id, items in by_payment.items():
        payment = items[0].payment
        provider = str(payment.provider or "")
        total_base = sum((row.base_usd for row in items), ZERO)
        amount = _dec(payment.amount)

        kgs_based = (provider == "freedompay" and str(payment.currency or "").upper() == "KGS") \
            or provider == "yookassa"
        if kgs_based:
            if any(row.base_usd > 0 and not (commission.RATE_MIN <= row.rate_to_usd <= commission.RATE_MAX)
                   for row in items):
                bad_rates.append(payment_id)
            ceiling = _kgs_ceiling(payment)
            if ceiling is None or total_base > ceiling:
                over_base.append(payment_id)
            elif reference_rate > 0 and total_base > ceiling * reference_rate * KGS_RATE_TOLERANCE:
                over_reference.append(payment_id)
        elif provider == "freedompay":
            if total_base > amount:
                over_base.append(payment_id)
        elif provider.startswith("crypto_"):
            invoice = commission._related(payment, "crypto_invoice")
            ceiling = amount
            if invoice is not None:
                info = (payment.request or {}).get("token_purchase") or {}
                total = int(info.get("tokens") or 0) + int(info.get("bonus_tokens") or 0)
                ceiling = (amount * int(invoice.credited_tokens or 0) / total) if total > 0 else ZERO
                # Каждая часть округлена вниз отдельно; запас — на округление деления.
                ceiling += Q6 * len(items)
            if total_base > ceiling:
                over_base.append(payment_id)
        elif provider == "telegram_stars":
            if stars_rate is None:
                from plans.stars import withdraw_rate

                stars_rate = withdraw_rate()
            if total_base > amount * stars_rate + Q6:
                over_stars.append(payment_id)

    return (_violation("I2", "fail", "сумма комиссии не равна база × процент (комиссии)", bad_rows)
            + _violation("I2", "fail", "курс к доллару вне допустимого коридора (платежи)", bad_rates)
            + _violation("I2", "fail", "база комиссии больше суммы оплаты (платежи)", over_base)
            + _violation("I2", "fail", "база комиссии в сомах больше чем вдвое выше курса из "
                                       "настроек (платежи)", over_reference)
            # Курс Stars — настройка: он мог измениться после начисления.
            + _violation("I2", "warn", "база комиссии Stars выше текущего курса (платежи)", over_stars))


# ------------------------------------------------------------------- I3 ---

def _program_start():
    """С какого момента смотреть леджер: раньше первого креатора программы не было.

    По причине и по JSON в леджере индексов нет, а в нём каждое списание за
    чат — без границы по дате сверка перебирала бы его целиком.
    """
    first = Creator.objects.order_by("created_at").values_list("created_at", flat=True).first()
    return (first - timedelta(days=1)) if first else timezone.now()


def _i3() -> list[Violation]:
    from plans.models import TokenTransaction

    order_ids = set(CreatorCommission.objects.filter(status__in=OPEN).exclude(order_id="")
                    .values_list("order_id", flat=True))
    since = _program_start()
    both = set()
    for chunk in _chunks(sorted(order_ids)):
        metas = (TokenTransaction.objects
                 .filter(reason="referral", delta__gt=0, created_at__gte=since,
                         meta__order_id__in=chunk)
                 .values_list("meta", flat=True))
        both.update((meta or {}).get("order_id") for meta in metas)
    both.discard(None)
    return _violation("I3", "fail", "заказ оплачен по обеим программам сразу", sorted(both))


# ------------------------------------------------------------------- I4 ---

def _i4() -> list[Violation]:
    own = CreatorCommission.objects.filter(buyer_pk=F("creator__user_id")).order_by("id")
    # Начисление собственную покупку аннулирует сразу, поэтому придержанная
    # строка здесь — только след слияния аккаунтов (заглушка-реферал влита в
    # аккаунт самого креатора): заработком она не считается и ждёт решения
    # администратора. Это не нарушение, а напоминание; нарушение — когда такая
    # строка стала заработком.
    earned = own.filter(status="accrued").values_list("pk", flat=True)
    waiting = own.filter(status="held").values_list("pk", flat=True)
    return (_violation("I4", "fail", "комиссия с собственной покупки креатора", earned)
            + _violation("I4", "warn", "придержанная комиссия с собственной покупки креатора "
                                       "ждёт решения (комиссии)", waiting))


# ------------------------------------------------------------------- I5 ---

def _i5() -> list[Violation]:
    now = timezone.now()
    over, uncovered = [], []
    creator_ids = (CreatorWithdrawal.objects.filter(status__in=("review", "approved", "paid"))
                   .values_list("creator_id", flat=True).distinct())
    for creator_id in creator_ids:
        withdrawals = CreatorWithdrawal.objects.filter(
            creator_id=creator_id, status__in=("review", "approved", "paid"))
        first = withdrawals.order_by("created_at", "id").first()
        w_open = balance._sum(withdrawals.filter(status__in=balance.OPEN_WITHDRAWALS), "amount_usdt")
        w_paid = balance._sum(withdrawals.filter(status="paid"), "amount_usdt")

        rows = CreatorCommission.objects.filter(creator_id=creator_id)
        matured = balance._sum(rows.filter(status="accrued", available_at__lte=now), "amount_usdt")
        # Что было доступно на момент вывода и ушло позже: возврат после
        # первой заявки, ручное аннулирование, слияние аккаунтов.
        left = balance._sum(
            rows.filter(status="reversed", reversed_at__gt=first.created_at,
                        available_at__isnull=False, available_at__lte=F("reversed_at")),
            "amount_usdt")
        left += balance._sum(rows.filter(reason__in=("admin_void", "merge_self")), "amount_usdt")

        if w_open + w_paid > matured + left:
            over.append(creator_id)
        elif w_open > 0 and matured - w_open - w_paid < 0:
            uncovered.append(creator_id)
    return (_violation("I5", "fail", "выведено больше, чем было доступно (креаторы)", over)
            + _violation("I5", "warn", "открытая заявка на вывод при долге (креаторы)", uncovered))


# ------------------------------------------------------------------- I6 ---

def _paid_without_txid():
    return list(CreatorWithdrawal.objects.filter(status="paid", txid="")
                .values_list("pk", flat=True))


def _repeated_txids():
    return list(CreatorWithdrawal.objects.exclude(txid="").values("txid")
                .annotate(n=Count("id")).filter(n__gt=1).values_list("txid", flat=True))


def _i6() -> list[Violation]:
    return (_violation("I6", "fail", "выплата без TXID (выводы)", _paid_without_txid())
            + _violation("I6", "fail", "один TXID у нескольких выплат", _repeated_txids()))


# ------------------------------------------------------------------- I7 ---

def _callback_says_refund(payment) -> bool:
    """След возврата в истории уведомлений — независимо от refund_marker."""
    from payments.views import _is_refund_signal

    for callback in (payment.response or {}).get("callbacks") or []:
        if not isinstance(callback, dict):
            continue
        kind = callback.get("type")
        if kind == "refund":
            return True
        payload = callback.get("payload")
        if kind == "post" and isinstance(payload, dict) and _is_refund_signal(payload):
            return True
    return False


def _i7() -> list[Violation]:
    from plans.models import TokenTransaction

    clawed_orders = {
        (meta or {}).get("order_id")
        for meta in TokenTransaction.objects
        .filter(reason="refund", created_at__gte=_program_start(),
                meta__kind="chargeback_clawback").values_list("meta", flat=True)
    }
    clawed_orders.discard(None)

    refunded = []
    payments = (Payment.objects.filter(creator_commissions__status__in=OPEN).distinct()
                .select_related("star_invoice", "crypto_invoice").order_by("id"))
    for payment in payments.iterator(chunk_size=500):
        if (commission.refund_marker(payment) or _callback_says_refund(payment)
                or (payment.order_id and payment.order_id in clawed_orders)):
            refunded.append(payment.pk)
    return _violation("I7", "fail", "возвращённый платёж с живой комиссией (платежи)", refunded)


# ------------------------------------------------------------------- I8 ---

def _latest_logs(target_type: str, actions=None) -> dict:
    """Последняя запись журнала по каждому объекту: target_id -> запись."""
    logs = AdminActionLog.objects.filter(target_type=target_type)
    if actions:
        logs = logs.filter(action__in=actions)
    latest = {}
    for log in logs.order_by("created_at", "id").iterator(chunk_size=500):
        latest[log.target_id] = log
    return latest


def _logged_ids(target_type: str, action: str) -> set:
    return set(AdminActionLog.objects.filter(target_type=target_type, action=action)
               .values_list("target_id", flat=True))


_WITHDRAWAL_LOGS = {
    "approved": ("withdrawal.approve", "withdrawal.reopen"),
    "paid": ("withdrawal.mark_paid", "withdrawal.fix_txid"),
    "rejected": ("withdrawal.reject",),
}
_COMMISSION_LOGS = {
    "admin_void": "commission.void",
    "released": "commission.release",
    "restored": "commission.restore",
}


def _i8() -> list[Violation]:
    from plans.models import TokenTransaction

    result = []

    latest = _latest_logs("creators.creatorwithdrawal")
    bad = []
    for row in CreatorWithdrawal.objects.filter(status__in=tuple(_WITHDRAWAL_LOGS)).iterator():
        log = latest.get(str(row.pk))
        if log is None or log.action not in _WITHDRAWAL_LOGS[row.status]:
            bad.append(row.pk)
        elif row.status == "paid" and (log.after or {}).get("txid") != row.txid:
            bad.append(row.pk)
    result += _violation("I8", "fail", "статус вывода не подтверждён журналом (выводы)", bad)

    granted = {(after or {}).get("grant_id") for after in
               AdminActionLog.objects.filter(action="credits.grant").values_list("after", flat=True)}
    bad = []
    for pk, meta in (TokenTransaction.objects
                     .filter(reason="creator_credit", created_at__gte=_program_start())
                     .values_list("pk", "meta").iterator()):
        grant_id = (meta or {}).get("grant_id")
        if grant_id and grant_id not in granted:
            bad.append(pk)
    result += _violation("I8", "fail", "Creator Credits начислены без записи в журнале (операции)", bad)

    # Запись журнала указывает на пользователя, которого привязывали. Слияние
    # аккаунтов переносит привязку заглушки на аккаунт сайта, а журнал не
    # переписывается — поэтому привязку узнаём ещё и по тому, что при слиянии
    # не меняется: по её id (если он записан) или по паре «кто привязал — к кому».
    user_meta = get_user_model()._meta
    rebound_users, rebound_referrals, rebound_pairs = set(), set(), set()
    for target_id, actor_id, after in (
            AdminActionLog.objects
            .filter(target_type=f"{user_meta.app_label}.{user_meta.model_name}",
                    action="referral.rebind")
            .values_list("target_id", "actor_id", "after").iterator(chunk_size=500)):
        after = after if isinstance(after, dict) else {}
        rebound_users.add(target_id)
        if after.get("referral_id") is not None:
            rebound_referrals.add(str(after["referral_id"]))
        if after.get("creator_id") is not None:
            rebound_pairs.add((actor_id, str(after["creator_id"])))
    bad = [pk for pk, user_id, creator_id, bound_by_id in CreatorReferral.objects
           .filter(source="admin").values_list("pk", "user_id", "creator_id", "bound_by_id")
           if str(user_id) not in rebound_users and str(pk) not in rebound_referrals
           and not (bound_by_id is not None and (bound_by_id, str(creator_id)) in rebound_pairs)]
    result += _violation("I8", "fail", "ручная привязка без записи в журнале (рефералы)", bad)

    bad = []
    for reason, action in _COMMISSION_LOGS.items():
        logged = _logged_ids("creators.creatorcommission", action)
        bad += [pk for pk in CreatorCommission.objects.filter(reason=reason)
                .values_list("pk", flat=True) if str(pk) not in logged]
    result += _violation("I8", "fail", "ручное действие с комиссией без записи в журнале (комиссии)",
                         sorted(bad))

    blocked = _logged_ids("creators.creatorapplication", "application.block")
    bad = [pk for pk in CreatorApplication.objects.filter(status="blocked")
           .values_list("pk", flat=True) if str(pk) not in blocked]
    result += _violation("I8", "fail", "заявка заблокирована без записи в журнале (заявки)", bad)
    return result


# ------------------------------------------------------------------- I9 ---

def _i9() -> list[Violation]:
    level_log, status_log, code_log = {}, {}, {}
    logs = (AdminActionLog.objects
            .filter(creator__isnull=False,
                    action__in=("creator.level_change", "application.approve", "creator.block",
                                "creator.unblock", "creator.code_change"))
            .order_by("created_at", "id")
            .values_list("creator_id", "action", "after"))
    for creator_id, action, after in logs.iterator(chunk_size=500):
        if action in ("creator.level_change", "application.approve"):
            level_log[creator_id] = (after or {}).get("level")
        elif action in ("creator.block", "creator.unblock"):
            status_log[creator_id] = "blocked" if action == "creator.block" else "active"
        else:
            code_log[creator_id] = (after or {}).get("code")

    primary = dict(CreatorCode.objects.filter(is_primary=True).values_list("creator_id", "code"))
    bad_level, bad_status, bad_code = [], [], []
    for creator in Creator.objects.select_related("level").order_by("id").iterator(chunk_size=500):
        if level_log.get(creator.pk) != creator.level.key:
            bad_level.append(creator.pk)
        if status_log.get(creator.pk, "active") != creator.status:
            bad_status.append(creator.pk)
        if creator.pk in code_log and code_log[creator.pk] != primary.get(creator.pk):
            bad_code.append(creator.pk)
    return (_violation("I9", "fail", "уровень не совпадает с журналом (креаторы)", bad_level)
            + _violation("I9", "fail", "статус не совпадает с журналом (креаторы)", bad_status)
            + _violation("I9", "fail", "промокод не совпадает с журналом (креаторы)", bad_code))


# ------------------------------------------------------------------ I10 ---

def _covered(bindings, at) -> bool:
    return any(bound_at <= at and (ended_at is None or ended_at > at)
               for bound_at, ended_at in bindings)


def _i10() -> list[Violation]:
    if not flags.accrual_enabled():
        return []
    from plans.models import TokenTransaction

    now = timezone.now()
    since, until = now - timedelta(days=30), now - timedelta(hours=1)

    bindings = defaultdict(list)
    for user_id, bound_at, ended_at in CreatorReferral.objects.values_list(
            "user_id", "bound_at", "ended_at"):
        bindings[user_id].append((bound_at, ended_at))
    if not bindings:
        return []

    # Комиссия создаётся не раньше покупки — хватает строк за то же окно.
    have = set(CreatorCommission.objects.filter(created_at__gte=since)
               .values_list("order_id", "part"))
    missing = []
    purchases = (TokenTransaction.objects
                 .filter(reason="purchase", delta__gt=0, created_at__gte=since,
                         created_at__lte=until, user_id__in=list(bindings))
                 .order_by("id"))
    for tx in purchases.iterator(chunk_size=500):
        meta = tx.meta or {}
        order_id = meta.get("order_id")
        part = str(meta.get("idem") or "")
        if not order_id or (order_id, part) in have:
            continue
        if not _covered(bindings[tx.user_id], tx.created_at):
            continue
        payment = (Payment.objects.filter(order_id=order_id)
                   .select_related("star_invoice", "crypto_invoice").order_by("-id").first())
        # Те же пропуски, что у дозачисления: без платежа, платёж другого
        # человека (слияние аккаунтов), уже возвращённый — начислять там нечего.
        if payment is None or payment.user_id != tx.user_id or commission.refund_marker(payment):
            continue
        if CreatorCommission.objects.filter(payment=payment, part=part).exists():
            continue
        missing.append(order_id if not part else f"{order_id}#{part}")
    return _violation("I10", "fail", "покупка привязанного пользователя без комиссии (заказы)",
                      missing)


_CHECKS = (_i1, _i2, _i3, _i4, _i5, _i6, _i7, _i8, _i9, _i10)


def run() -> list[Violation]:
    """Все нарушения. Пустой список — программа сходится. Ничего не меняет."""
    violations: list[Violation] = []
    for check in _CHECKS:
        violations += check()
    return violations
