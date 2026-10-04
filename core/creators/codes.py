"""Промокоды креаторов: формат, общее пространство имён, создание и замена.

Код креатора — одновременно и промокод, и хвост ссылки ?ref=CODE. Он делит
одно пространство имён с реферальными UID пользователей и обычными
промокодами: иначе одна и та же строка вела бы к двум разным людям.

Креатор создаёт код один раз сам; меняет его только главный администратор.
Старый код после замены остаётся псевдонимом того же креатора — старые
ссылки в соцсетях продолжают работать, а код не достаётся никому другому.
"""
from __future__ import annotations

import logging
import re

from django.conf import settings
from django.db import IntegrityError, transaction

from audit.services import log_admin_action

from .errors import CreatorsError
from .models import Creator, CreatorCode

logger = logging.getLogger("creators")

CODE_RE = re.compile(r"^[A-Z][A-Z0-9]{3,15}$")
RESERVED = frozenset({"ESAI", "ADMIN", "ADMINISTRATOR", "SUPPORT", "HELP", "TEST", "PROMO", "FREE", "BONUS",
                      "CREATOR", "CREATORS", "AMBASSADOR", "OFFICIAL", "STAFF", "MODERATOR", "SYSTEM",
                      "ROOT", "NULL", "NONE", "PAYMENT", "REFUND", "USDT", "TRC20", "TELEGRAM"})


def normalize(raw) -> str:
    return str(raw or "").strip().upper()


def validate_format(code: str) -> None:
    """Формат и запрещённые слова. Код уже нормализован (normalize)."""
    code = str(code or "")
    if not CODE_RE.match(code):
        raise CreatorsError("code_format")
    # Всё, что начинается с ESAI, выглядит как официальный код сервиса.
    if code in RESERVED or code.startswith("ESAI"):
        raise CreatorsError("code_reserved")


def taken_by(code: str) -> str:
    """Кем занят код: "" | "creator_code" | "referral_uid" | "promo_code"."""
    from django.contrib.auth import get_user_model

    from plans.models import PromoCode

    code = normalize(code)
    if not code:
        return ""
    # Погашенные коды тоже считаются: код не переиздаётся никогда.
    if CreatorCode.objects.filter(code=code).exists():
        return "creator_code"
    if get_user_model().objects.filter(referral_uid__iexact=code).exists():
        return "referral_uid"
    if PromoCode.objects.filter(code__iexact=code).exists():
        return "promo_code"
    return ""


def check_available(code: str) -> None:
    owner = taken_by(code)
    if owner:
        raise CreatorsError("code_taken", taken_by=owner)


def creator_code_exists(code) -> bool:
    """Есть ли ЛЮБАЯ строка кода креатора (действующая или нет).

    Зовут чужие пути — создание пользователя и промокода, — поэтому никогда не
    бросает: при любой ошибке ответ «нет», своя точка сохранения не ломает
    транзакцию вызывающего.
    """
    try:
        norm = normalize(code)
        if not norm:
            return False
        with transaction.atomic():
            return CreatorCode.objects.filter(code=norm).exists()
    except Exception:  # noqa: BLE001
        logger.exception("creators.codes: проверка кода не удалась")
        return False


def primary_code(creator) -> str:
    """Основной код креатора; "" — код ещё не создан."""
    pk = getattr(creator, "pk", None)
    if not pk:
        return ""
    return (CreatorCode.objects.filter(creator_id=pk, is_primary=True)
            .values_list("code", flat=True).first() or "")


def link_for(code: str) -> str:
    return f"{settings.CREATORS_LINK_BASE.rstrip('/')}/?ref={code}"


def telegram_link_for(code: str) -> str:
    """Ссылка в бота; "" — бот не настроен."""
    bot = str(getattr(settings, "TELEGRAM_PRODUCT_BOT_USERNAME", "") or "").lstrip("@")
    if not bot or not code:
        return ""
    return f"https://t.me/{bot}?start=ref_{code}"


def _insert_primary(creator, code: str, created_by) -> CreatorCode:
    """Вставка основного кода в своей точке сохранения.

    Гонку двух креаторов за один код ловит уникальный индекс; без вложенного
    atomic IntegrityError на Postgres сломал бы внешнюю транзакцию.
    """
    try:
        with transaction.atomic():
            return CreatorCode.objects.create(code=code, creator=creator, is_primary=True,
                                              is_active=True, created_by=created_by)
    except IntegrityError:
        raise CreatorsError("code_taken", taken_by="creator_code")


def create_code(creator, raw, *, actor=None) -> CreatorCode:
    """Первый и единственный код, который креатор задаёт сам."""
    code = normalize(raw)
    with transaction.atomic():
        creator = Creator.objects.locked(creator.pk)
        if creator.status != Creator.Status.ACTIVE:
            raise CreatorsError("creator_blocked")
        if CreatorCode.objects.filter(creator=creator).exists():
            raise CreatorsError("code_already_set")
        validate_format(code)
        check_available(code)
        row = _insert_primary(creator, code, actor or creator.user)
        # Код за креатора задал администратор — это уже действие для журнала.
        if actor is not None and actor.pk != creator.user_id:
            log_admin_action(actor, "creator.code_set", target=row, creator=creator,
                             before={"code": None}, after={"code": code})
    return row


def change_code(creator, raw, *, actor, reason: str, request=None) -> CreatorCode:
    """Замена кода администратором. Старый код остаётся рабочим псевдонимом."""
    reason = str(reason or "").strip()
    if not reason:
        raise CreatorsError("reason_required")
    code = normalize(raw)
    with transaction.atomic():
        creator = Creator.objects.locked(creator.pk)
        validate_format(code)
        old = CreatorCode.objects.filter(creator=creator, is_primary=True).first()
        own = CreatorCode.objects.filter(creator=creator, code=code).first()
        if own is not None and own.is_primary:
            raise CreatorsError("code_unchanged")
        if own is None:
            check_available(code)
        # Сначала снимаем признак со старого: частичный уникальный индекс
        # не допускает двух основных кодов даже на мгновение.
        if old is not None:
            old.is_primary = False
            old.save(update_fields=["is_primary"])
        if own is not None:
            # Возврат к прежнему коду: он уже принадлежит этому креатору.
            own.is_primary = True
            own.is_active = True
            own.save(update_fields=["is_primary", "is_active"])
            row = own
        else:
            row = _insert_primary(creator, code, actor)
        log_admin_action(actor, "creator.code_change" if old is not None else "creator.code_set",
                         target=row, creator=creator,
                         before={"code": old.code if old is not None else None},
                         after={"code": code}, reason=reason, request=request)
    return row
