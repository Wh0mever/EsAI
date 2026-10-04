"""Вывод заработка креатора: USDT TRC20, минимум 10, без комиссии, выплата ручная.

Путь заявки: review -> approved -> paid, либо rejected. Код ничего не
отправляет в сеть: перевод делает человек и вводит TXID. Каждый переход идёт
под блокировкой строки креатора и пишется в журнал действий администратора.

Сумма в заявке не «списывается» с баланса — баланс считается из строк
(creators.balance), поэтому отклонённая заявка возвращает деньги сама.
"""
from __future__ import annotations

import ipaddress
from decimal import ROUND_DOWN, Decimal

from django.db import IntegrityError, transaction
from django.utils import timezone

from audit.services import log_admin_action

from . import balance, flags, notify
from .errors import CreatorsError
from .models import CreatorWithdrawal
from .trc20 import is_valid_address, normalize_txid

OPEN = ("review", "approved")


def _ip(request):
    """IP запроса для заявки; мусор в заголовке — None (Postgres не примет его в поле адреса)."""
    meta = getattr(request, "META", None) or {}
    forwarded = str(meta.get("HTTP_X_FORWARDED_FOR") or "").split(",")[0].strip()
    for candidate in (forwarded, str(meta.get("REMOTE_ADDR") or "").strip()):
        if not candidate:
            continue
        try:
            return str(ipaddress.ip_address(candidate))
        except ValueError:
            continue
    return None


def _required(reason) -> str:
    reason = str(reason or "").strip()
    if not reason:
        raise CreatorsError("reason_required")
    return reason


def _money(value) -> str:
    return str(Decimal(value).quantize(balance.Q2))


def _amount(raw) -> Decimal:
    """Сумма заявки: конечное положительное число, не больше двух знаков после запятой."""
    if raw is None or isinstance(raw, bool):
        raise CreatorsError("amount_invalid")
    try:
        # Через строку: число из JSON не должно пройти через двоичную дробь.
        amount = raw if isinstance(raw, Decimal) else Decimal(str(raw).strip())
        if not amount.is_finite() or amount <= 0:
            raise CreatorsError("amount_invalid")
        # quantize внутри try: у числа длиннее 28 значащих цифр («1e30») он
        # бросает InvalidOperation — это неверная сумма, а не ошибка сервера.
        rounded = amount.quantize(balance.Q2)
    except Exception:  # noqa: BLE001
        raise CreatorsError("amount_invalid")
    if amount != rounded:
        raise CreatorsError("amount_invalid")
    return rounded


def _save_address(creator, address: str, request) -> None:
    """Записать новый адрес выплат. Вызывающий держит блокировку креатора."""
    old = creator.payout_address
    creator.payout_address = address
    creator.payout_address_changed_at = timezone.now()
    creator.save(update_fields=["payout_address", "payout_address_changed_at", "updated_at"])
    # Смена адреса — самое опасное действие в кабинете (угнанный аккаунт уводит
    # выплату), поэтому она в журнале, хотя делает её сам креатор.
    log_admin_action(creator.user, "creator.payout_address_change", target=creator,
                     creator=creator, before={"payout_address": old},
                     after={"payout_address": address}, request=request)


def set_payout_address(creator, address, *, request=None):
    address = str(address or "").strip()
    with transaction.atomic():
        c = balance.lock(creator.pk)
        if c.status != "active":
            raise CreatorsError("creator_blocked")
        if not is_valid_address(address):
            raise CreatorsError("address_invalid")
        if address != c.payout_address:
            _save_address(c, address, request)
    return c


def request_withdrawal(creator, amount, *, address=None, request=None) -> CreatorWithdrawal:
    """Заявка креатора на вывод. Сколько запрошено — столько и будет отправлено."""
    with transaction.atomic():
        c = balance.lock(creator.pk)
        if not flags.enabled_for(c.user):
            raise CreatorsError("disabled")
        if not flags.payouts_enabled():
            raise CreatorsError("payouts_disabled")
        if c.status != "active":
            raise CreatorsError("creator_blocked")
        addr = str(address or c.payout_address or "").strip()
        if not addr:
            raise CreatorsError("address_required")
        if not is_valid_address(addr):
            raise CreatorsError("address_invalid")
        amount = _amount(amount)
        if amount < flags.MIN_PAYOUT_USDT:
            raise CreatorsError("amount_below_min")
        if CreatorWithdrawal.objects.filter(creator=c, status__in=OPEN).exists():
            raise CreatorsError("withdrawal_open")
        available = balance.summary(c).available
        if amount > available:
            raise CreatorsError("insufficient_available",
                                available=str(available.quantize(balance.Q2, rounding=ROUND_DOWN)))

        if addr != c.payout_address:
            _save_address(c, addr, request)
        try:
            with transaction.atomic():
                return CreatorWithdrawal.objects.create(
                    creator=c, amount_usdt=amount, address=addr, status="review",
                    ip=_ip(request) if request is not None else None)
        except IntegrityError:
            # Вторую заявку «в работе» не даёт создать индекс creators_wd_one_open.
            raise CreatorsError("withdrawal_open")


# ------------------------------------------------- действия администратора ---

def _locked(withdrawal_id):
    """Креатор и заявка под блокировкой. Вызывающий внутри transaction.atomic()."""
    probe = CreatorWithdrawal.objects.filter(pk=withdrawal_id).values("id", "creator_id").first()
    if probe is None:
        raise CreatorsError("not_found")
    c = balance.lock(probe["creator_id"])
    row = CreatorWithdrawal.objects.select_for_update(of=("self",)).get(pk=probe["id"])
    return c, row


def _check_still_owed(c) -> None:
    """Можно ли сейчас двигать заявку к выплате.

    Между заявкой и выплатой мог прийти возврат или ручная отмена комиссии, а
    баланс заблокированного креатора заморожен.
    """
    if c.status != "active":
        raise CreatorsError("creator_blocked")
    if balance.summary(c).available_raw < 0:
        raise CreatorsError("insufficient_available")


def _txid_taken(txid: str, row) -> bool:
    return CreatorWithdrawal.objects.filter(txid=txid).exclude(pk=row.pk).exists()


def approve(withdrawal_id, *, actor, request=None) -> CreatorWithdrawal:
    with transaction.atomic():
        c, row = _locked(withdrawal_id)
        if row.status != "review":
            raise CreatorsError("bad_state")
        _check_still_owed(c)
        row.status = "approved"
        row.approved_by, row.approved_at = actor, timezone.now()
        row.save(update_fields=["status", "approved_by", "approved_at"])
        log_admin_action(actor, "withdrawal.approve", target=row, creator=c,
                         before={"status": "review"}, after={"status": "approved"},
                         request=request)
        notify.emit(c, "payout_approved", amount_usdt=_money(row.amount_usdt))
    return row


def reject(withdrawal_id, *, actor, reason: str, request=None) -> CreatorWithdrawal:
    reason = _required(reason)
    with transaction.atomic():
        c, row = _locked(withdrawal_id)
        if row.status not in OPEN:
            raise CreatorsError("bad_state")
        before = {"status": row.status}
        row.status = "rejected"
        row.rejected_by, row.rejected_at, row.reject_reason = actor, timezone.now(), reason
        row.save(update_fields=["status", "rejected_by", "rejected_at", "reject_reason"])
        log_admin_action(actor, "withdrawal.reject", target=row, creator=c,
                         before=before, after={"status": "rejected"}, reason=reason,
                         request=request)
        notify.emit(c, "payout_rejected", amount_usdt=_money(row.amount_usdt), reason=reason)
    return row


def mark_paid(withdrawal_id, *, actor, txid, force: bool = False, reason: str = "",
              request=None) -> CreatorWithdrawal:
    """Отметить выплату отправленной: TXID обязателен.

    force — только когда деньги УЖЕ ушли в сеть, а баланс за это время ушёл в
    минус или креатора заблокировали: отметка нужна, чтобы учёт сошёлся.
    """
    force = bool(force)
    reason = _required(reason) if force else str(reason or "").strip()
    with transaction.atomic():
        c, row = _locked(withdrawal_id)
        if row.status != "approved":
            raise CreatorsError("bad_state")
        if not force:
            _check_still_owed(c)
        txid = normalize_txid(txid)
        if _txid_taken(txid, row):
            raise CreatorsError("txid_duplicate")
        row.status, row.txid = "paid", txid
        row.paid_by, row.paid_at = actor, timezone.now()
        try:
            with transaction.atomic():
                row.save(update_fields=["status", "txid", "paid_by", "paid_at"])
        except IntegrityError:
            raise CreatorsError("txid_duplicate")
        after = {"status": "paid", "txid": txid}
        if force:
            after["forced"] = True
        log_admin_action(actor, "withdrawal.mark_paid", target=row, creator=c,
                         before={"status": "approved"}, after=after, reason=reason,
                         request=request)
        notify.emit(c, "payout_sent", amount_usdt=_money(row.amount_usdt), txid=txid)
    return row


def fix_txid(withdrawal_id, *, actor, txid, reason: str, request=None) -> CreatorWithdrawal:
    """Исправить опечатку в TXID выплаченной заявки.

    Без этого неверный, но правильный по форме хеш навсегда остался бы у
    креатора «подтверждением» и мог занять настоящий TXID другой выплаты.
    """
    reason = _required(reason)
    with transaction.atomic():
        c, row = _locked(withdrawal_id)
        if row.status != "paid":
            raise CreatorsError("bad_state")
        txid = normalize_txid(txid)
        if txid == row.txid:
            raise CreatorsError("bad_state")
        if _txid_taken(txid, row):
            raise CreatorsError("txid_duplicate")
        old, row.txid = row.txid, txid
        try:
            with transaction.atomic():
                row.save(update_fields=["txid"])
        except IntegrityError:
            raise CreatorsError("txid_duplicate")
        log_admin_action(actor, "withdrawal.fix_txid", target=row, creator=c,
                         before={"txid": old}, after={"txid": txid}, reason=reason,
                         request=request)
    return row


def reopen(withdrawal_id, *, actor, reason: str, request=None) -> CreatorWithdrawal:
    """Перевод не прошёл в сети после ввода TXID: paid -> approved."""
    reason = _required(reason)
    with transaction.atomic():
        c, row = _locked(withdrawal_id)
        if row.status != "paid":
            raise CreatorsError("bad_state")
        if CreatorWithdrawal.objects.filter(creator=c, status__in=OPEN).exclude(pk=row.pk).exists():
            raise CreatorsError("withdrawal_open")
        before = {"status": "paid", "txid": row.txid, "paid_at": row.paid_at}
        row.status, row.txid, row.paid_at, row.paid_by = "approved", "", None, None
        try:
            with transaction.atomic():
                row.save(update_fields=["status", "txid", "paid_at", "paid_by"])
        except IntegrityError:
            raise CreatorsError("withdrawal_open")
        log_admin_action(actor, "withdrawal.reopen", target=row, creator=c,
                         before=before, after={"status": "approved"}, reason=reason,
                         request=request)
    return row
