"""Привязка Telegram к аккаунту сайта и отвязка по просьбе человека.

Сценарий «с сайта»: в профиле человек жмёт «Привязать Telegram», получает
ссылку t.me/<бот>?start=link_<код>, бот приносит код сюда. Если у этого
Telegram уже есть свой аккаунт-заглушка (человек писал боту до привязки),
заглушка вливается в аккаунт сайта: чаты, мультфильмы, память и купленные
кредиты переезжают, бонусные — нет. Заглушка гасится, а не удаляется:
леджер и платежи остаются финансовым учётом.
"""
from __future__ import annotations

import logging
import secrets

from allauth.socialaccount.models import SocialAccount
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.db import transaction
from django.utils import timezone

from .models import TelegramChat
from .services import PROVIDER, find_user

logger = logging.getLogger("botapi.link")

LINK_TTL = 600
LINK_MAX_FAILS = 5
STUB_DOMAIN = "@social.esai.local"


class LinkError(Exception):
    def __init__(self, code: str, http: int = 400, **extra):
        super().__init__(code)
        self.code = code
        self.http = http
        self.extra = extra


def is_stub(user) -> bool:
    """Аккаунт, который появился только из Telegram и не имеет своей почты."""
    email = (getattr(user, "email", "") or "").lower()
    return email.endswith(STUB_DOMAIN) and not user.has_usable_password()


def _rename_username(user) -> None:
    """Логин совпадает с почтой и тоже уникален — освобождаем и его."""
    if hasattr(user, "username"):
        user.username = user.email[:150]


def _has_paid(user) -> bool:
    from payments.models import Payment

    return bool(getattr(user, "is_paid", False)) or Payment.objects.filter(
        user=user, success=True).exists()


# ------------------------------------------------------------------ код ---

def start_link(user) -> dict:
    """Код для deep-link: живёт десять минут, срабатывает один раз."""
    if find_telegram_of(user):
        raise LinkError("already_linked", 409)
    code = secrets.token_urlsafe(9).replace("-", "a").replace("_", "b")[:12]
    cache.set(f"tg:link:{code}", int(user.pk), LINK_TTL)
    return {"code": code, "expires_in": LINK_TTL}


def find_telegram_of(user):
    return SocialAccount.objects.filter(user=user, provider=PROVIDER).first()


def _consume_code(code: str, telegram_id) -> int:
    fails_key = f"tg:link:fail:{telegram_id}"
    if int(cache.get(fails_key) or 0) >= LINK_MAX_FAILS:
        raise LinkError("too_many_attempts", 429)
    user_id = cache.get(f"tg:link:{code}") if code else None
    if not user_id:
        try:
            cache.incr(fails_key)
        except ValueError:
            cache.set(fails_key, 1, 3600)
        raise LinkError("code_invalid", 404)
    cache.delete(f"tg:link:{code}")
    return int(user_id)


# -------------------------------------------------------------- слияние ---

BONUS_REASONS = ("welcome", "daily_bonus", "bonus")


def movable_credits(stub) -> int:
    """Сколько кредитов заглушки переезжают: всё, кроме подарочных.

    Бонусы выдаются каждому новому аккаунту, и тащить их в уже существующий
    значило бы раздавать приветственный бонус дважды одним и тем же людям.
    """
    from django.db.models import Sum

    from plans.models import TokenTransaction

    balance = int(getattr(stub, "token_balance", 0) or 0)
    gifted = int(TokenTransaction.objects.filter(
        user=stub, reason__in=BONUS_REASONS, delta__gt=0
    ).aggregate(s=Sum("delta")).get("s") or 0)
    return max(0, min(balance, balance - gifted))


def merge_into(stub, target) -> dict:
    """Перенести всё нажитое из заглушки в аккаунт сайта и погасить заглушку."""
    from ai.models import AiChatSession, GenerationJob
    from cartoon.models import CartoonCharacter, CartoonProject
    from payments.models import Payment
    from plans.wallet import clawback_tokens, credit_tokens
    from users.models import UserMemory

    User = get_user_model()
    with transaction.atomic():
        stub = User.objects.select_for_update().get(pk=stub.pk)
        target = User.objects.select_for_update().get(pk=target.pk)
        moved = movable_credits(stub)
        balance = int(stub.token_balance or 0)
        if balance > 0:
            clawback_tokens(stub, balance, "admin",
                            meta={"kind": "merge_out", "merge_into": target.pk, "moved": moved})
        if moved > 0:
            credit_tokens(target, moved, "admin",
                          meta={"kind": "merge_in", "merge_from": stub.pk})

        counts = {
            "sessions": AiChatSession.objects.filter(user=stub).update(user=target),
            "projects": CartoonProject.objects.filter(user=stub).update(user=target),
            "characters": CartoonCharacter.objects.filter(user=stub).update(user=target),
            "memory": UserMemory.objects.filter(user=stub).update(user=target),
            "payments": Payment.objects.filter(user=stub).update(user=target),
            "jobs": GenerationJob.objects.filter(user=stub).update(user=target),
            "referrals": User.objects.filter(referred_by=stub).update(referred_by=target),
        }
        SocialAccount.objects.filter(user=stub, provider=PROVIDER).update(user=target)
        TelegramChat.objects.filter(user=target).delete()
        TelegramChat.objects.filter(user=stub).update(user=target, source=TelegramChat.SOURCE_LINK)
        if getattr(stub, "is_paid", False) and not getattr(target, "is_paid", False):
            target.is_paid = True
            target.first_paid_at = getattr(stub, "first_paid_at", None) or timezone.now()
            target.save(update_fields=["is_paid", "first_paid_at"])

        stub.is_active = False
        stub.email = f"merged_{stub.pk}_{stub.email}"[:254]
        _rename_username(stub)
        stub.save(update_fields=["is_active", "email", "username"])
    return {"moved_credits": moved, **counts}


def confirm_link(code: str, tg_user: dict, *, chat_id=None) -> tuple[str, object]:
    """Код из ссылки + данные Telegram → (статус, пользователь сайта)."""
    telegram_id = str(tg_user.get("id") or "").strip()
    if not telegram_id.isdigit():
        raise LinkError("bad_telegram_user")
    User = get_user_model()
    user_id = _consume_code(code, telegram_id)
    target = User.objects.filter(pk=user_id, is_active=True).first()
    if not target:
        raise LinkError("code_invalid", 404)

    existing = find_user(telegram_id)
    if existing is not None and existing.pk == target.pk:
        status = "already"
    elif existing is not None:
        if not is_stub(existing) or _has_paid(existing):
            raise LinkError("telegram_bound_to_paid_account", 409)
        merge_into(existing, target)
        status = "merged"
    else:
        if find_telegram_of(target):
            raise LinkError("already_linked", 409)
        SocialAccount.objects.create(
            user=target, provider=PROVIDER, uid=telegram_id,
            extra_data={k: v for k, v in tg_user.items() if k != "_hash"})
        status = "linked"

    TelegramChat.objects.filter(telegram_id=int(telegram_id)).exclude(user=target).delete()
    TelegramChat.objects.filter(user=target).exclude(telegram_id=int(telegram_id)).delete()
    TelegramChat.objects.update_or_create(
        telegram_id=int(telegram_id),
        defaults={"user": target, "chat_id": int(chat_id or telegram_id),
                  "username": (tg_user.get("username") or "").lstrip("@")[:64],
                  "source": TelegramChat.SOURCE_LINK, "is_blocked": False, "blocked_at": None})
    username = (tg_user.get("username") or "").lstrip("@")[:30]
    if username and getattr(target, "telegram", "") != username:
        target.telegram = username
        target.save(update_fields=["telegram"])

    try:
        from audit.services import log_event

        log_event("telegram_linked", message=f"{status}: tg {telegram_id} → user {target.pk}",
                  user=target, meta={"telegram_id": telegram_id, "status": status})
    except Exception:  # noqa: BLE001
        pass
    return status, target


# ------------------------------------------------------------- отвязка ---

def forget_telegram(telegram_id) -> dict:
    """/delete в боте: отвязать Telegram и погасить аккаунт-заглушку.

    Аккаунт с настоящей почтой остаётся — человек просто отвязал Telegram.
    Заглушка гасится и переименовывается, чтобы следующий /start завёл
    новый чистый аккаунт, а не воскресил старый.
    """
    user = find_user(telegram_id)
    if user is None:
        TelegramChat.objects.filter(telegram_id=int(telegram_id)).delete()
        return {"status": "not_linked", "deactivated": False}
    deactivated = False
    with transaction.atomic():
        SocialAccount.objects.filter(user=user, provider=PROVIDER).delete()
        TelegramChat.objects.filter(telegram_id=int(telegram_id)).delete()
        TelegramChat.objects.filter(user=user).delete()
        if is_stub(user):
            user.is_active = False
            user.email = f"deleted_{user.pk}_{int(timezone.now().timestamp())}{STUB_DOMAIN}"
            user.first_name = ""
            user.last_name = ""
            user.telegram = ""
            user.avatar_url = ""
            _rename_username(user)
            user.save(update_fields=["is_active", "email", "first_name", "last_name",
                                     "telegram", "avatar_url", "username"])
            deactivated = True
        elif getattr(user, "telegram", ""):
            user.telegram = ""
            user.save(update_fields=["telegram"])
    try:
        from audit.services import log_event

        log_event("telegram_unlinked", message=f"tg {telegram_id} ← user {user.pk}",
                  user=user, meta={"deactivated": deactivated})
    except Exception:  # noqa: BLE001
        pass
    return {"status": "unlinked", "deactivated": deactivated}
