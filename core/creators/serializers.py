"""Форма ответов API программы Creators: строки списков для кабинета и админки.

Обычные функции, а не DRF-сериализаторы: почти каждое поле здесь — формат
(деньги строкой, маска пользователя) или готовая цифра из сервисов, а не
колонка модели. Одни и те же функции собирают ответы кабинета
(creators/views.py) и админки (adminapi/creators.py).

Правила формата (контракт с фронтендом):
- деньги — строки; балансы, продажи и выводы — два знака, округление вниз;
  сумма комиссии — шесть знаков; процент — два знака;
- кабинет никогда не отдаёт id, почту или «сырое» имя реферала — только маску.
"""
from __future__ import annotations

from decimal import ROUND_DOWN, Decimal

from django.db.models import Count, Q, Sum

from .models import CreatorCommission

Q2 = Decimal("0.01")
Q6 = Decimal("0.000001")

# Комиссии, за которыми стоят настоящие деньги покупателя (как в creators.stats).
_LIVE = ("accrued", "held")


# ------------------------------------------------------------------- формат

def usdt2(value) -> str:
    """Сумма для показа: два знака, вниз — больше, чем есть, не показываем."""
    return str(Decimal(str(value or 0)).quantize(Q2, rounding=ROUND_DOWN))


def usdt6(value) -> str:
    return str(Decimal(str(value or 0)).quantize(Q6, rounding=ROUND_DOWN))


def pct(value) -> str:
    return str(Decimal(str(value or 0)).quantize(Q2))


def mask(user) -> str:
    """Маска пользователя для кабинета креатора."""
    # Лениво: users.views тянет за собой половину проекта.
    from users.views import _mask_user_label

    return _mask_user_label(user)


def _email(user):
    return getattr(user, "email", None) if user is not None else None


# ------------------------------------------------------------------- уровни

def level_row(level) -> dict:
    return {
        "key": level.key,
        "title": level.title,
        "percent": pct(level.percent),
        "sort": level.sort,
        "min_publications": level.min_publications,
        "min_registrations": level.min_registrations,
        "min_paying": level.min_paying,
    }


def level_brief(level) -> dict:
    return {"key": level.key, "title": level.title, "percent": pct(level.percent)}


# ------------------------------------------------------------------- заявки

def application_row(application, *, admin: bool = False) -> dict:
    row = {
        "id": application.pk,
        "status": application.status,
        "created_at": application.created_at,
        "decided_at": application.decided_at,
        "reject_reason": application.reject_reason,
        "name": application.name,
        "telegram": application.telegram,
        "country": application.country,
        "instagram_url": application.instagram_url,
        "tiktok_url": application.tiktok_url,
        "youtube_url": application.youtube_url,
        "other_links": list(application.other_links or []),
        "followers": application.followers,
        "occupation": application.occupation,
        "motivation": application.motivation,
        "samples": list(application.samples or []),
    }
    if admin:
        row.update({
            "lang": application.lang,
            "ip": application.ip,
            "user_id": application.user_id,
            "email": _email(application.user),
            "decided_by_id": application.decided_by_id,
            "decided_by_email": _email(application.decided_by),
        })
    return row


# --------------------------------------------------------------- публикации

def publication_row(publication, *, admin: bool = False) -> dict:
    row = {
        "id": publication.pk,
        "network": publication.network,
        "url": publication.url,
        "description": publication.description,
        "status": publication.status,
        "created_at": publication.created_at,
        "decided_at": publication.decided_at,
        "reject_reason": publication.reject_reason,
    }
    if admin:
        row.update({
            "creator_id": publication.creator_id,
            "creator_name": publication.creator.display_name,
            "decided_by_email": _email(publication.decided_by),
        })
    return row


# ----------------------------------------------------------------- комиссии

def public_reason(commission) -> str:
    """Причина статуса комиссии словами для креатора.

    Внутренние коды (referral_suspect, buyer_staff, fraud, merge_self…) —
    сигналы антифрода и сведения о сотрудниках; в кабинет уходит только общий
    смысл: на проверке, возврат, отменена.
    """
    if commission.status == "accrued":
        return ""
    if commission.status == "held":
        return "review"
    if str(commission.reason or "").startswith("refund"):
        return "refund"
    return "cancelled"


def commission_row(commission) -> dict:
    """Строка комиссии для кабинета: покупатель только маской, причина — общим словом."""
    return {
        "id": commission.pk,
        "date": commission.created_at,
        "buyer": mask(commission.buyer),
        "provider": commission.provider,
        "base_usdt": usdt2(commission.base_usd),
        "percent": pct(commission.percent),
        "amount_usdt": usdt6(commission.amount_usdt),
        "status": commission.status,
        "reason": public_reason(commission),
        "available_at": commission.available_at,
    }


def commission_admin_row(commission) -> dict:
    return {
        "id": commission.pk,
        "created_at": commission.created_at,
        "creator_id": commission.creator_id,
        "creator_name": commission.creator.display_name,
        "buyer_pk": commission.buyer_pk,
        "buyer_email": _email(commission.buyer),
        "payment_id": commission.payment_id,
        "order_id": commission.order_id,
        "part": commission.part,
        "provider": commission.provider,
        "paid_amount": str(commission.paid_amount),
        "paid_currency": commission.paid_currency,
        "rate_to_usd": str(commission.rate_to_usd),
        "rate_source": commission.rate_source,
        "base_usd": usdt6(commission.base_usd),
        "level_key": commission.level_key,
        "percent": pct(commission.percent),
        "amount_usdt": usdt6(commission.amount_usdt),
        "status": commission.status,
        "reason": commission.reason,
        "available_at": commission.available_at,
        "reversed_at": commission.reversed_at,
    }


# ------------------------------------------------------------------ выводы

def withdrawal_row(withdrawal) -> dict:
    """Строка вывода для кабинета. TXID креатор видит (ТЗ п.26, 28)."""
    return {
        "id": withdrawal.pk,
        "created_at": withdrawal.created_at,
        "amount_usdt": usdt2(withdrawal.amount_usdt),
        "address": withdrawal.address,
        "network": withdrawal.network,
        "status": withdrawal.status,
        "txid": withdrawal.txid,
        "reject_reason": withdrawal.reject_reason,
        "approved_at": withdrawal.approved_at,
        "paid_at": withdrawal.paid_at,
    }


def withdrawal_admin_row(withdrawal, *, balance_json: dict, covered: bool) -> dict:
    """Строка вывода для админки.

    covered=False — после заявки пришёл возврат: выплатив её, отдали бы деньги,
    которых креатору уже не должны.
    """
    creator = withdrawal.creator
    return {
        "id": withdrawal.pk,
        "creator_id": withdrawal.creator_id,
        "creator_name": creator.display_name,
        "creator_status": creator.status,
        "email": _email(creator.user),
        "amount_usdt": usdt2(withdrawal.amount_usdt),
        "address": withdrawal.address,
        "network": withdrawal.network,
        "status": withdrawal.status,
        "txid": withdrawal.txid,
        "created_at": withdrawal.created_at,
        "approved_at": withdrawal.approved_at,
        "approved_by_email": _email(withdrawal.approved_by),
        "paid_at": withdrawal.paid_at,
        "paid_by_email": _email(withdrawal.paid_by),
        "rejected_at": withdrawal.rejected_at,
        "reject_reason": withdrawal.reject_reason,
        "address_changed_at": creator.payout_address_changed_at,
        "balance": balance_json,
        "covered": bool(covered),
    }


# ----------------------------------------------------------------- рефералы

def referral_totals(referral_ids) -> dict[int, dict]:
    """Заказы, продажи и комиссия по привязкам — одним запросом на весь список."""
    ids = [pk for pk in referral_ids if pk]
    empty = {"orders": 0, "sales": Decimal("0"), "commission": Decimal("0")}
    out = {pk: dict(empty) for pk in ids}
    if not ids:
        return out
    live = Q(status__in=_LIVE)
    rows = (CreatorCommission.objects.filter(referral_id__in=ids)
            .values("referral_id")
            .annotate(orders=Count("payment_id", distinct=True, filter=live),
                      sales=Sum("base_usd", filter=live),
                      # В «заработано» идут только начисленные: придержанные — ещё нет.
                      commission=Sum("amount_usdt", filter=Q(status="accrued"))))
    for row in rows:
        out[row["referral_id"]] = {
            "orders": int(row["orders"] or 0),
            # SQLite отдаёт сумму числом с плавающей точкой — приводим через строку.
            "sales": Decimal(str(row["sales"] or 0)),
            "commission": Decimal(str(row["commission"] or 0)),
        }
    return out


def _referral_money(totals: dict) -> dict:
    return {
        "is_paying": totals["orders"] > 0,
        "orders": totals["orders"],
        "sales_usdt": usdt2(totals["sales"]),
        "commission_usdt": usdt2(totals["commission"]),
    }


def referral_row(referral, totals: dict) -> dict:
    """Строка реферала для кабинета: id здесь — номер привязки, не пользователя."""
    row = {
        "id": referral.pk,
        "user": mask(referral.user),
        "bound_at": referral.bound_at,
        "source": referral.source,
    }
    row.update(_referral_money(totals))
    return row


def referral_admin_row(referral, totals: dict) -> dict:
    user = referral.user
    row = {
        "id": referral.pk,
        "user_id": referral.user_id,
        "email": _email(user),
        "user_label": mask(user),
        "creator_id": referral.creator_id,
        "creator_name": referral.creator.display_name,
        "source": referral.source,
        "code_used": referral.code_used,
        "bound_at": referral.bound_at,
        "bound_by_email": _email(referral.bound_by),
        "ended_at": referral.ended_at,
        "end_reason": referral.end_reason,
        "suspect": referral.suspect,
        "flags": referral.flags or {},
    }
    row.update(_referral_money(totals))
    row["referred_by_id"] = getattr(user, "referred_by_id", None)
    return row


# ------------------------------------------------------------------- журнал

def log_row(entry) -> dict:
    return {
        "id": entry.pk,
        "created_at": entry.created_at,
        "actor_id": entry.actor_id,
        "actor_email": _email(entry.actor),
        "action": entry.action,
        "target_type": entry.target_type,
        "target_id": entry.target_id,
        "creator_id": entry.creator_id,
        "before": entry.before or {},
        "after": entry.after or {},
        "reason": entry.reason,
        "ip": entry.ip,
    }


# ------------------------------------------------------------------ кредиты

# Что кабинет показывает из истории Creator Credits. Остальное (остаток общего
# кошелька после операции, кто выдал) креатору не отдаём.
_GRANT_KEYS = ("id", "date", "amount", "category", "category_label", "note")
_SPEND_KEYS = ("id", "date", "amount", "kind", "reason", "reason_label", "remaining_after")


def credit_row(row: dict) -> dict:
    """Строка истории кредитов для кабинета — только перечисленные в контракте поля."""
    if row.get("kind") == "spend":
        return {key: row.get(key) for key in _SPEND_KEYS}
    out = {key: row.get(key) for key in _GRANT_KEYS}
    if "kind" in row:
        # Полная история (выдачи и расходы вместе): вид строки и остаток после неё.
        out["kind"] = row["kind"]
        out["remaining_after"] = row.get("remaining_after")
    return out
