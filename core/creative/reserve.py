"""Резерв кредитов и списание Creative Studio (SPEC_B §4).

Как у видеостудии: резерв — сама строка CreativeJob (charge_state="reserved"),
списываем только за выданный результат. Свободный остаток = баланс минус ВСЕ
резервы сайта (vstudio.reserve.total_reserved, куда добавлен и резерв Creative).

Модуль импортирует vstudio.reserve (общая сумма резервов), а тот — лениво —
нас (creative_reserved), поэтому модели здесь тоже ленивые.
"""
from __future__ import annotations

import json
import logging
from contextlib import contextmanager
from typing import NamedTuple

from django.conf import settings
from django.core.cache import cache
from django.db import transaction

logger = logging.getLogger(__name__)

DEFAULT_MAX_OPEN = 3
# После 403 поставщика (нет денег, ключ отключён) новые запуски не принимаем
# столько секунд: человек сразу видит «временно недоступно», а резерв не держится.
PROVIDER_DOWN_KEY = "creative:provider_down"
PROVIDER_DOWN_S = 300

MSG_NO_CREDITS = {
    "video": "Недостаточно кредитов для создания видео.",
    "image": "Недостаточно кредитов для создания картинки.",
    "character": "Недостаточно кредитов для создания персонажа.",
}
MSG_NO_CREDITS_RESERVED = ("Недостаточно кредитов: часть баланса ждёт оплаты за генерации, "
                           "которые ещё идут. Дождитесь их или пополните баланс.")
MSG_TOO_MANY_OPEN = ("Одновременно можно запускать не больше {limit} работ. "
                     "Дождитесь, пока одна из них будет готова.")
MSG_PROVIDER = "Генерация временно недоступна. Попробуйте через несколько минут — кредиты не списаны."
MSG_STORAGE = "Сохранение результатов временно недоступно. Попробуйте позже — кредиты не списаны."


class SpendRefused(Exception):
    """Запуск отклонён до резерва: HTTP-статус и тело ответа ({error, error_code, …})."""

    def __init__(self, status: int, payload: dict):
        self.status = int(status)
        self.payload = dict(payload)
        super().__init__(self.payload.get("error_code") or "spend_refused")


class AlreadyStarted(Exception):
    """Этот клик (client_request_id) уже создал задачу — отвечаем ею, 200."""

    def __init__(self, job):
        self.job = job
        super().__init__(getattr(job, "uid", ""))


class Charge(NamedTuple):
    credits: int
    partial: bool


def max_open() -> int:
    try:
        return max(1, int(getattr(settings, "CREATIVE_MAX_OPEN_PER_USER", DEFAULT_MAX_OPEN)))
    except (TypeError, ValueError):
        return DEFAULT_MAX_OPEN


def reason_for(kind: str) -> str:
    from .registry import REASON_BY_KIND

    return REASON_BY_KIND.get(kind, REASON_BY_KIND["image"])


# ---------------------------------------------------------------- резерв

def reserved_credits(user) -> int:
    """Sum(credits_reserved) задач в резерве. Бросает при сбое БД (для strict)."""
    from django.db.models import Sum

    from .models import CHARGE_RESERVED, CreativeJob

    total = CreativeJob.objects.filter(user_id=user.pk, charge_state=CHARGE_RESERVED).aggregate(
        s=Sum("credits_reserved"))["s"]
    return max(0, int(total or 0))


def balance_snapshot(user, need: int | None = None) -> dict | None:
    from vstudio.reserve import balance_snapshot as studio_snapshot

    return studio_snapshot(user, need)


def provider_down() -> bool:
    try:
        return bool(cache.get(PROVIDER_DOWN_KEY))
    except Exception:
        return False


def mark_provider_down() -> None:
    try:
        cache.set(PROVIDER_DOWN_KEY, 1, PROVIDER_DOWN_S)
    except Exception:
        pass


def balance_refusal(balance: int, reserved: int, need: int, kind: str) -> dict | None:
    """402 в форме чата (ai.generation.video_balance_error): PaywallModal работает без правок."""
    from ai.generation import video_balance_error

    refusal = video_balance_error(int(balance), int(reserved), int(need))
    if refusal is None:
        return None
    refusal["error"] = MSG_NO_CREDITS_RESERVED if reserved > 0 else MSG_NO_CREDITS.get(
        kind, MSG_NO_CREDITS["image"])
    return refusal


@contextmanager
def spend_gate(user, need: int, *, kind: str, client_request_id: str = ""):
    """Проверки перед резервом; CreativeJob создаётся ВНУТРИ блока.

        with spend_gate(request.user, credits, kind="image", client_request_id=cid) as locked:
            CreativeJob.objects.create(user=locked, charge_state="reserved", ...)

    Порядок (как vstudio.reserve.spend_gate):
    1. проба хранилища и «поставщик недоступен» → 503 (до замка);
    2. строка пользователя под select_for_update — два запуска выстраиваются в очередь;
    3. тот же client_request_id уже создал задачу → AlreadyStarted(job);
    4. открытых задач ≥ CREATIVE_MAX_OPEN_PER_USER → 409 too_many_open;
    5. баланс − все резервы сайта (strict) < need → 402 (форма чата).
    """
    need = int(need)
    if need <= 0:
        raise ValueError("spend_gate: need must be positive")
    if provider_down():
        raise SpendRefused(503, {"error": MSG_PROVIDER, "error_code": "provider_unavailable"})
    from .storage import storage_ready

    ok, reason = storage_ready(user.pk)
    if not ok:
        logger.error("creative: хранилище недоступно user=%s: %s", user.pk, reason)
        raise SpendRefused(503, {"error": MSG_STORAGE, "error_code": "storage_unavailable"})

    from django.contrib.auth import get_user_model

    from vstudio.reserve import total_reserved

    from .models import JOB_OPEN, CreativeJob

    with transaction.atomic():
        locked = get_user_model().objects.select_for_update().get(pk=user.pk)
        if client_request_id:
            existing = CreativeJob.objects.filter(user=locked, client_request_id=client_request_id).first()
            if existing is not None:
                raise AlreadyStarted(existing)
        limit = max_open()
        open_n = CreativeJob.objects.filter(user=locked, status__in=JOB_OPEN).count()
        if open_n >= limit:
            raise SpendRefused(409, {"error": MSG_TOO_MANY_OPEN.format(limit=limit),
                                     "error_code": "too_many_open", "limit": limit})
        balance = int(locked.token_balance or 0)
        reserved = total_reserved(locked, strict=True)
        refusal = balance_refusal(balance, reserved, need, kind)
        if refusal:
            raise SpendRefused(402, refusal)
        yield locked


# ---------------------------------------------------------------- списание при выдаче

def _json_meta(meta) -> dict:
    if not meta:
        return {}
    from django.core.serializers.json import DjangoJSONEncoder

    try:
        return json.loads(json.dumps(dict(meta), cls=DjangoJSONEncoder))
    except (TypeError, ValueError):
        return {str(k): (v if isinstance(v, (str, int, float, bool)) or v is None else str(v))
                for k, v in dict(meta).items()}


def charge_on_delivery(user, amount: int, reason: str, meta=None) -> Charge:
    """Списать за выданный результат — В ТРАНЗАКЦИИ выдачи, сразу после выигранного
    условного UPDATE saving→done (reserved→charged).

    Не хватает (изъятие, ручная правка, гонка с чатом) — clawback «сколько есть»
    с meta.partial=True: результат человек получает в любом случае, поставщику
    уже заплачено.
    """
    from plans.models import CREATIVE_SPEND_REASONS
    from plans.wallet import InsufficientTokens, charge_tokens, clawback_tokens

    amount = int(amount or 0)
    if amount < 0:
        raise ValueError("charge_on_delivery: amount must be non-negative")
    if reason not in CREATIVE_SPEND_REASONS:
        raise ValueError(f"charge_on_delivery: unexpected reason {reason!r}")
    if amount == 0:
        return Charge(0, False)
    clean = _json_meta(meta)
    try:
        charge_tokens(user, amount, reason, meta=clean)
        return Charge(amount, False)
    except InsufficientTokens as exc:
        got = clawback_tokens(user, amount, reason=reason,
                              meta={**clean, "partial": True, "wanted": amount,
                                    "balance_before": int(exc.balance or 0)})
        logger.warning("creative partial charge user=%s job=%s wanted=%s charged=%s",
                       getattr(user, "pk", None), clean.get("job", "?"), amount, got)
        return Charge(int(got or 0), True)


__all__ = ["SpendRefused", "AlreadyStarted", "Charge", "spend_gate", "charge_on_delivery",
           "reserved_credits", "balance_snapshot", "balance_refusal", "max_open", "reason_for",
           "provider_down", "mark_provider_down"]
