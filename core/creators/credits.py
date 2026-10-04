"""Creator Credits — кредиты, которые администратор вручную выдаёт креатору.

Это НЕ комиссия: на них делают контент в EsAI, их нельзя вывести, продать
или перевести другому человеку (ТЗ п.19). Отдельного кошелька нет — кредиты
лежат на общем балансе, а в леджере помечены причиной "creator_credit".

Остаток («сколько Creator Credits ещё не потрачено») нигде не хранится, а
считается по леджеру: выданные кредиты тратятся первыми, переводы их не
трогают. От остатка зависит, сколько человек может перевести другому
(plans.wallet.transferable_tokens), поэтому remaining() никогда не бросает.

Автоматического начисления нет: grant() зовёт только администратор.
"""
from __future__ import annotations

import logging
import uuid
from collections import deque

from django.core.cache import cache
from django.db import transaction
from django.db.models import Q, Sum

from audit.services import log_admin_action
from plans.models import TokenTransaction, TokenTransactionReason
from plans.wallet import credit_tokens

from .errors import CreatorsError
from .models import Creator
from .notify import emit

logger = logging.getLogger("creators")

REASON = "creator_credit"
CATEGORIES = ("start", "activity", "content", "result", "special", "other")
# "merge" пишет не администратор, а слияние аккаунтов (botapi.linking): кредиты
# заглушки Telegram переезжают в аккаунт сайта и остаются Creator Credits.
CATEGORY_LABELS = {"start": "Старт", "activity": "Активность", "content": "За контент",
                   "result": "За результат", "special": "Специальный бонус", "other": "Другое",
                   "merge": "Перенос с аккаунта Telegram"}
MAX_GRANT = 1_000_000

# Сколько секунд такой же запрос (тот же админ, креатор, сумма и причина)
# считается повторным нажатием кнопки.
DUPLICATE_WINDOW = 10
NOTE_MAX = 300

_REASON_LABELS = dict(TokenTransactionReason.choices)


# ------------------------------------------------------------------ выдача

def _as_amount(value) -> int:
    """Целое 1..MAX_GRANT. Дробь не округляем молча: 12.5 — это ошибка ввода."""
    if isinstance(value, bool):
        raise CreatorsError("amount_invalid")
    if isinstance(value, float):
        if value != value or value in (float("inf"), float("-inf")) or value != int(value):
            raise CreatorsError("amount_invalid")
        value = int(value)
    try:
        amount = int(str(value).strip())
    except (TypeError, ValueError):
        raise CreatorsError("amount_invalid") from None
    if not 1 <= amount <= MAX_GRANT:
        raise CreatorsError("amount_invalid")
    return amount


def _guard_key(actor, creator, amount: int, category: str) -> str:
    return f"creators:grant:{actor.pk}:{creator.pk}:{amount}:{category}"


def grant(creator, amount, category: str, *, actor, note: str = "",
          request=None) -> TokenTransaction:
    """Выдать креатору Creator Credits. Только вручную, только администратор.

    Строку креатора не блокирует: баланс USDT не меняется, а кошелёк
    сериализует plans.wallet.credit_tokens по строке пользователя.
    """
    amount = _as_amount(amount)
    category = str(category or "").strip()
    if category not in CATEGORIES:
        raise CreatorsError("category_invalid")
    # Статус и владельца читаем из базы: переданный объект мог устареть
    # (креатора заблокировали, аккаунт слили с другим), а заблокированному
    # кредиты не выдаются.
    fresh = (Creator.objects.filter(pk=getattr(creator, "pk", None))
             .select_related("user").first())
    if fresh is None:
        raise CreatorsError("not_found")
    if fresh.status != Creator.Status.ACTIVE:
        raise CreatorsError("creator_blocked")
    note = str(note or "").replace("\x00", "").strip()[:NOTE_MAX]

    key = _guard_key(actor, fresh, amount, category)
    try:
        first_click = cache.add(key, "1", DUPLICATE_WINDOW)
    except Exception:  # noqa: BLE001 — защита от двойного клика не должна мешать выдаче
        logger.warning("creators.credits: кэш недоступен, выдача без защиты от повтора",
                       exc_info=True)
        first_click = True
    if not first_click:
        raise CreatorsError("duplicate_request")

    try:
        with transaction.atomic():
            grant_id = uuid.uuid4().hex
            credit_tokens(fresh.user, amount, REASON, meta={
                "category": category, "note": note, "by_id": actor.pk, "grant_id": grant_id})
            tx = TokenTransaction.objects.filter(
                user_id=fresh.user_id, reason=REASON, meta__grant_id=grant_id).first()
            if tx is None:
                # Без строки леджера не будет ни истории, ни записи в журнале.
                raise RuntimeError("creator_credit transaction not found")
            log_admin_action(actor, "credits.grant", target=tx, creator=fresh, after={
                "amount": amount, "category": category, "note": note,
                "grant_id": grant_id, "balance_after": int(tx.balance_after)},
                reason=note, request=request)
            emit(fresh, "credits_granted", amount=amount, category=category)
    except Exception:
        # Выдача не состоялась — повторить можно сразу, не дожидаясь 10 секунд.
        try:
            cache.delete(key)
        except Exception:  # noqa: BLE001
            pass
        raise
    return tx


# ------------------------------------------------------------------- суммы

def granted_total(user) -> int:
    """Сколько Creator Credits выдано человеку за всё время."""
    if not user or not getattr(user, "pk", None):
        return 0
    total = TokenTransaction.objects.filter(
        user_id=user.pk, reason=REASON, delta__gt=0).aggregate(s=Sum("delta"))["s"]
    return int(total or 0)


def _fold(user_pk):
    """Пройти леджер от первой выдачи и отдать строки, которые меняют остаток.

    Отдаёт (tx, kind, consumed, remaining_after): kind "grant" — выдача,
    "spend" — списание, которое пришлось на Creator Credits (consumed > 0).
    Одна реализация для remaining() и ledger(): цифра в кабинете и защита
    переводов не могут разойтись.

    Правило: Creator Credits тратятся первыми. Любое списание, кроме перевода,
    уменьшает остаток; перевод его не трогает (переводить эти кредиты нельзя,
    значит ушли другие). Покупки и бонусы остаток не меняют.
    """
    first = (TokenTransaction.objects
             .filter(user_id=user_pk, reason=REASON, delta__gt=0)
             .order_by("created_at", "id").only("id", "created_at").first())
    if first is None:
        return
    rows = (TokenTransaction.objects
            .filter(user_id=user_pk, created_at__gte=first.created_at)
            # Остальные строки свёртка всё равно пропустила бы — не тянем их из базы.
            .filter(Q(reason=REASON, delta__gt=0) | (Q(delta__lt=0) & ~Q(reason="transfer_out")))
            .order_by("created_at", "id")
            .only("id", "created_at", "delta", "reason", "balance_after"))
    rem = 0
    for tx in rows.iterator(chunk_size=2000):
        delta = int(tx.delta)
        if delta > 0:
            rem += delta
            yield tx, "grant", 0, rem
            continue
        consumed = min(rem, -delta)
        if consumed > 0:
            rem -= consumed
            yield tx, "spend", consumed, rem


def remaining(user) -> int:
    """Сколько Creator Credits ещё лежит на балансе. Никогда не бросает (→ 0).

    Для человека без выдач — один запрос. Зовётся из перевода кредитов, поэтому
    считает в своей точке сохранения: сбой запроса не должен ломать транзакцию
    перевода.
    """
    try:
        if not user or not getattr(user, "pk", None):
            return 0
        with transaction.atomic():
            rem, seen = 0, False
            for _tx, _kind, _consumed, rem in _fold(user.pk):
                seen = True
            if not seen or rem <= 0:
                return 0
            from django.contrib.auth import get_user_model

            balance = int(get_user_model().objects.filter(pk=user.pk).values_list(
                "token_balance", flat=True).first() or 0)
            # Больше, чем есть на балансе, остаться не может.
            return max(0, min(int(rem), balance))
    except Exception:  # noqa: BLE001 — от этой цифры зависит перевод кредитов
        logger.exception("creators.credits: remaining(%s) не посчитан",
                         getattr(user, "pk", None))
        return 0


# ----------------------------------------------------------------- история

def _meta(tx) -> dict:
    return tx.meta if isinstance(tx.meta, dict) else {}


def _by_id(tx):
    try:
        return int(_meta(tx).get("by_id"))
    except (TypeError, ValueError):
        return None


def _emails(txs) -> dict:
    """pk администратора -> email, одним запросом."""
    ids = {pk for pk in (_by_id(tx) for tx in txs) if pk}
    if not ids:
        return {}
    from django.contrib.auth import get_user_model

    return dict(get_user_model().objects.filter(pk__in=ids).values_list("pk", "email"))


def _grant_row(tx, *, for_admin: bool, emails: dict) -> dict:
    """Строка выдачи. meta целиком наружу не уходит: в нём id администратора."""
    meta = _meta(tx)
    category = str(meta.get("category") or "")
    row = {
        "id": tx.pk,
        "date": tx.created_at,
        "amount": int(tx.delta),
        "category": category,
        "category_label": CATEGORY_LABELS.get(category, CATEGORY_LABELS["other"]),
        "note": str(meta.get("note") or ""),
        "balance_after": int(tx.balance_after),
    }
    if for_admin:
        by_id = _by_id(tx)
        row["by_id"] = by_id
        row["by_email"] = emails.get(by_id) if by_id else None
    return row


def _limit(value, default: int) -> int:
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return default


def history(user, *, limit: int = 100, for_admin: bool = False) -> list[dict]:
    """Выдачи Creator Credits человеку, новые сверху (ТЗ п.22)."""
    if not user or not getattr(user, "pk", None):
        return []
    txs = list(TokenTransaction.objects
               .filter(user_id=user.pk, reason=REASON, delta__gt=0)
               .order_by("-created_at", "-id")[:_limit(limit, 100)])
    emails = _emails(txs) if for_admin else {}
    return [_grant_row(tx, for_admin=for_admin, emails=emails) for tx in txs]


def ledger(user, *, limit: int = 100, for_admin: bool = False) -> list[dict]:
    """Выдачи И расходы Creator Credits, новые сверху (ТЗ п.31).

    Расход — та часть списания, что пришлась на Creator Credits: если из 50
    списанных кредитов от выдачи оставалось 20, в строке будет −20.
    """
    if not user or not getattr(user, "pk", None):
        return []
    limit = _limit(limit, 100)
    if limit <= 0:
        return []
    # Свёртку надо пройти с начала, но помнить достаточно последние limit строк.
    tail = deque(_fold(user.pk), maxlen=limit)
    if not tail:
        return []
    # Свёртка читает леджер без meta (у списаний чата он большой и не нужен);
    # причины и примечания выдач дочитываем одним запросом.
    grant_ids = [tx.pk for tx, kind, _c, _r in tail if kind == "grant"]
    grants = {tx.pk: tx for tx in TokenTransaction.objects.filter(pk__in=grant_ids)}
    emails = _emails(grants.values()) if for_admin else {}

    rows = []
    for tx, kind, consumed, rem_after in reversed(tail):
        if kind == "grant":
            row = _grant_row(grants.get(tx.pk, tx), for_admin=for_admin, emails=emails)
            row["kind"] = "grant"
        else:
            row = {
                "id": tx.pk,
                "date": tx.created_at,
                "amount": -int(consumed),
                "kind": "spend",
                "reason": tx.reason,
                "reason_label": str(_REASON_LABELS.get(tx.reason, tx.reason)),
            }
        row["remaining_after"] = int(rem_after)
        rows.append(row)
    return rows


def history_all(*, creator_id: int | None = None, offset: int = 0, limit: int = 50,
                for_admin: bool = True) -> tuple[int, list[dict]]:
    """Выдачи всех креаторов для вкладки админки: (всего, страница строк).

    Число запросов от числа строк не зависит: счётчик, страница, карта
    креаторов и (для админа) почты выдавших.
    """
    qs = TokenTransaction.objects.filter(reason=REASON, delta__gt=0)
    if creator_id is not None:
        qs = qs.filter(user_id__in=Creator.objects.filter(pk=creator_id).values("user_id"))
    total = qs.count()
    offset, limit = _limit(offset, 0), _limit(limit, 50)
    txs = list(qs.order_by("-created_at", "-id")[offset:offset + limit])
    if not txs:
        return total, []

    # После слияния аккаунтов выдача может лежать у человека без строки Creator.
    creators = {row["user_id"]: row for row in Creator.objects
                .filter(user_id__in={tx.user_id for tx in txs})
                .values("id", "user_id", "display_name")}
    emails = _emails(txs) if for_admin else {}
    rows = []
    for tx in txs:
        row = _grant_row(tx, for_admin=for_admin, emails=emails)
        owner = creators.get(tx.user_id)
        row["creator_id"] = owner["id"] if owner else None
        row["creator_name"] = owner["display_name"] if owner else None
        rows.append(row)
    return total, rows
