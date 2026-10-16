"""Резерв кредитов и списание в видеостудии (спецификация §5.2–5.3).

Правило продукта: списываем только за готовый результат. Провайдеру же мы
платим сразу, поэтому между запуском и выдачей кредиты «обещаны» — это резерв.
В студии резерв — сама строка Take (charge_state="reserved"), отдельной таблицы
нет. Свободный остаток = баланс минус ВСЕ резервы сайта:
- видео чата и бота (ai.generation.reserved_video_credits — открытые записи журнала);
- сцены мультстудии, которые снимаются (cartoon.pricing.reserved_credits);
- дубли студии (vstudio_reserved);
- склейки в очереди и в работе (merge.services.reserved_credits).
Иначе две вкладки, чат и студия, или «запустил и перевёл кредиты другу»
проходили бы проверку по одному и тому же балансу, а провайдеру мы платили бы
за всё.

Модуль импортируют чужие гейты (чат, бот, мультстудия) и plans.wallet, поэтому
модели студии здесь только ленивые: импорт не падает, даже если приложение
ещё не подключено.
"""
from __future__ import annotations

import json
import logging
from contextlib import contextmanager
from typing import NamedTuple

from django.conf import settings
from django.db import transaction

logger = logging.getLogger(__name__)

KIND_VIDEO = "video"
KIND_IMAGE = "image"

# Лимиты открытых дублей на человека (решение лида 5): 2 видео и 4 картинки.
DEFAULT_MAX_OPEN = {KIND_VIDEO: 2, KIND_IMAGE: 4}
# Ниже этого остатка на активном аккаунте OpenRouter запуск не принимаем:
# провайдер всё равно откажет, а человек увидит честное «временно недоступно».
DEFAULT_MIN_PROVIDER_USD = 2.0

REASON_BY_KIND = {KIND_VIDEO: "vstudio_video", KIND_IMAGE: "vstudio_image"}

MSG_NO_CREDITS = {
    KIND_VIDEO: "Недостаточно кредитов для генерации видео.",
    KIND_IMAGE: "Недостаточно кредитов для создания картинки.",
}
MSG_NO_CREDITS_RESERVED = ("Недостаточно кредитов: часть баланса ждёт оплаты за генерации, "
                           "которые ещё идут. Дождитесь их или пополните баланс.")
MSG_TOO_MANY_OPEN = {
    KIND_VIDEO: ("Одновременно можно снимать не больше {limit} видео. "
                 "Дождитесь, пока одно из них будет готово."),
    KIND_IMAGE: ("Одновременно можно создавать не больше {limit} картинок. "
                 "Дождитесь, пока одна из них будет готова."),
}
MSG_PROVIDER = "Генерация временно недоступна. Попробуйте через несколько минут — кредиты не списаны."


class SpendRefused(Exception):
    """Запуск отклонён до резерва: HTTP-статус и тело ответа в форме API (§8.4).

    402 insufficient_balance (форма чата — PaywallModal работает без правок),
    409 too_many_open {limit, kind}, 503 provider_unavailable.
    """

    def __init__(self, status: int, payload: dict):
        self.status = int(status)
        self.payload = dict(payload)
        super().__init__(self.payload.get("error_code") or "spend_refused")

    @property
    def error_code(self) -> str:
        return str(self.payload.get("error_code") or "")


class AlreadyStarted(Exception):
    """Этот клик (client_request_id) уже создал дубль — отвечаем им же, 200.

    Нужна для двойного клика «вплотную»: второй запрос прошёл проверку
    идемпотентности до коммита первого, а потом ждал на замке. После замка он
    видит дубль первого и не должен ни получить 402 за «свой же» резерв, ни
    упасть на уникальном индексе vs_take_idem.
    """

    def __init__(self, take):
        self.take = take
        super().__init__(getattr(take, "uid", ""))


class Charge(NamedTuple):
    """Итог списания при выдаче: сколько списано на деле и было ли оно частичным."""

    credits: int
    partial: bool


# ---------------------------------------------------------------- настройки

def max_open(kind: str) -> int:
    name = "VSTUDIO_MAX_OPEN_VIDEO" if kind == KIND_VIDEO else "VSTUDIO_MAX_OPEN_IMAGE"
    default = DEFAULT_MAX_OPEN.get(kind, DEFAULT_MAX_OPEN[KIND_IMAGE])
    try:
        return max(1, int(getattr(settings, name, default)))
    except (TypeError, ValueError):
        return default


def min_provider_usd() -> float:
    try:
        return max(0.0, float(getattr(settings, "VSTUDIO_MIN_PROVIDER_USD", DEFAULT_MIN_PROVIDER_USD)))
    except (TypeError, ValueError):
        return DEFAULT_MIN_PROVIDER_USD


def reason_for(kind: str) -> str:
    """Причина списания в леджере: vstudio_video | vstudio_image."""
    return REASON_BY_KIND[KIND_VIDEO if kind == KIND_VIDEO else KIND_IMAGE]


# ---------------------------------------------------------------- резервы

def _installed() -> bool:
    from django.apps import apps

    return apps.is_installed("vstudio")


def _studio_reserved(user) -> int:
    """Сумма credits_reserved дублей в резерве. Бросает при сбое БД."""
    if not _installed():
        return 0
    from django.db.models import Sum

    from .models import CHARGE_RESERVED, Take

    total = Take.objects.filter(user_id=user.pk, charge_state=CHARGE_RESERVED).aggregate(
        s=Sum("credits_reserved"))["s"]
    return max(0, int(total or 0))


def _chat_reserved(user) -> int:
    from ai.generation import reserved_video_credits

    return max(0, int(reserved_video_credits(user) or 0))


def _cartoon_reserved(user) -> int:
    from cartoon.pricing import reserved_credits

    return max(0, int(reserved_credits(user) or 0))


def _merge_reserved(user) -> int:
    """Склейки в очереди и в работе. Своя функция склейки уже мягкая (сбой → 0 и warning)."""
    from django.apps import apps

    if not apps.is_installed("merge"):
        return 0
    from merge.services import reserved_credits

    return max(0, int(reserved_credits(user) or 0))


def _soft(fn, user, what: str) -> int:
    """Посчитать часть резерва, не роняя чужой запрос: при сбое 0 и warning.

    Savepoint обязателен: упавший запрос внутри транзакции запроса иначе
    сломал бы её целиком на Postgres («current transaction is aborted»).
    """
    try:
        with transaction.atomic():
            return fn(user)
    except Exception:
        logger.warning("vstudio reserve: %s не посчитан, резерв не учтён", what, exc_info=True)
        return 0


def vstudio_reserved(user) -> int:
    """Кредиты в резерве у дублей студии: Sum(credits_reserved), charge_state=reserved.

    Для гейтов чата, бота и мультстудии (однострочные добавки к их резервам).
    Как reserved_video_credits: при сбое — 0 и warning, платящего не блокируем.
    """
    if not getattr(user, "pk", None):
        return 0
    return _soft(_studio_reserved, user, "резерв видеостудии")


def total_reserved(user, *, strict: bool = False) -> int:
    """Все резервы сайта: видео чата и бота + сцены мультстудии + дубли студии + склейки.

    strict=True — для spend_gate студии: сбой не прячется (запрос упадёт и
    откатится, ничего не зарезервировав). По умолчанию — мягко, как в чужих
    гейтах и в plans.wallet.transferable_tokens: при сбое часть считается 0.
    Резерв склеек мягкий и при strict: его считает сама склейка в своём savepoint.
    """
    if not getattr(user, "pk", None):
        return 0
    parts = ((_chat_reserved, "резерв видео чата"), (_cartoon_reserved, "резерв мультстудии"),
             (_studio_reserved, "резерв видеостудии"), (_merge_reserved, "резерв склеек"))
    if strict:
        return sum(fn(user) for fn, _ in parts)
    return sum(_soft(fn, user, what) for fn, what in parts)


def _fresh_balance(user) -> int:
    from django.contrib.auth import get_user_model

    value = get_user_model().objects.filter(pk=user.pk).values_list("token_balance", flat=True).first()
    return int(value or 0)


def balance_snapshot(user, need: int | None = None) -> dict | None:
    """BalanceJSON для quote и ответа запуска: {balance, reserved, available, after}.

    after — сколько останется после запуска ценой need (может быть < 0: тогда
    на кнопке «Пополнить · не хватает N»). Гость → None.
    """
    if not user or not getattr(user, "pk", None) or not getattr(user, "is_authenticated", True):
        return None
    balance = _fresh_balance(user)
    reserved = total_reserved(user)
    available = max(0, balance - reserved)
    return {"balance": balance, "reserved": reserved, "available": available,
            "after": (available - int(need)) if need is not None else None}


# ---------------------------------------------------------------- гейт запуска

def provider_refusal() -> dict | None:
    """Предохранитель по балансу OpenRouter (§5.2): тело 503 или None.

    Смотрим снимок баланса активного аккаунта (обновляет openrouter_autoswitch).
    Нет активного аккаунта (ключ из настроек) или снимка ещё не было — не
    блокируем: судить не по чему. VSTUDIO_MIN_PROVIDER_USD=0 выключает проверку.
    """
    minimum = min_provider_usd()
    if minimum <= 0:
        return None
    try:
        from ai.models import OpenRouterAccount

        with transaction.atomic():
            row = OpenRouterAccount.objects.filter(is_active=True).values("title", "balance_usd").first()
    except Exception:
        logger.warning("vstudio: баланс OpenRouter не прочитан, предохранитель пропущен", exc_info=True)
        return None
    if not row or row.get("balance_usd") is None:
        return None
    if float(row["balance_usd"]) >= minimum:
        return None
    logger.error("vstudio: на аккаунте OpenRouter «%s» $%s (< $%s) — запуски не принимаем",
                 row.get("title"), row["balance_usd"], minimum)
    return {"error": MSG_PROVIDER, "error_code": "provider_unavailable"}


def balance_refusal(balance: int, reserved: int, need: int, kind: str) -> dict | None:
    """Отказ 402 в форме чата (ai.generation.video_balance_error) или None.

    balance_tokens — свободный остаток, required_estimate — цена, reserved_credits —
    если что-то в резерве. Текст — под студию: резерв может быть и картинкой.
    """
    from ai.generation import video_balance_error

    refusal = video_balance_error(int(balance), int(reserved), int(need))
    if refusal is None:
        return None
    refusal["error"] = MSG_NO_CREDITS_RESERVED if reserved > 0 else MSG_NO_CREDITS.get(
        kind, MSG_NO_CREDITS[KIND_VIDEO])
    return refusal


@contextmanager
def spend_gate(user, need: int, *, kind: str, client_request_id: str = ""):
    """Проверка перед резервом; Take создаётся ВНУТРИ блока (§5.2).

        with spend_gate(request.user, price.credits, kind="video",
                        client_request_id=cid) as locked:
            Take.objects.create(user=locked, charge_state="reserved", credits_reserved=..., ...)

    Порядок:
    1. предохранитель OpenRouter → SpendRefused(503, provider_unavailable) ещё до замка;
    2. строка пользователя под select_for_update: два запуска разом (две вкладки,
       двойной клик) выстраиваются в очередь, и второй видит дубль первого;
    3. тот же client_request_id уже создал дубль → AlreadyStarted(take) (ответ 200 с ним);
    4. лимит открытых дублей своего вида → SpendRefused(409, too_many_open);
    5. свободный остаток (баланс − все резервы сайта) < need → SpendRefused(402).

    Блок — transaction.atomic(): внутри транзакции запроса это savepoint, а
    замок строки держится до коммита всего запроса — вместе со вставкой дубля.
    Исключение в теле откатывает всё, что успели создать.
    Дневная квота чата (_reserve_daily_request) здесь не используется.
    """
    if kind not in (KIND_VIDEO, KIND_IMAGE):
        raise ValueError(f"unknown take kind: {kind!r}")
    need = int(need)
    if need <= 0:
        # Цена всегда ≥ 1 кр; ноль здесь — ошибка вызывающего, а не бесплатный запуск.
        raise ValueError("spend_gate: need must be positive")

    refusal = provider_refusal()
    if refusal:
        raise SpendRefused(503, refusal)

    from django.contrib.auth import get_user_model

    from .models import Take

    with transaction.atomic():
        locked = get_user_model().objects.select_for_update().get(pk=user.pk)
        if client_request_id:
            existing = Take.objects.filter(user=locked, client_request_id=client_request_id).first()
            if existing is not None:
                raise AlreadyStarted(existing)
        limit = max_open(kind)
        open_n = Take.objects.filter(user=locked, kind=kind, status__in=Take.OPEN).count()
        if open_n >= limit:
            raise SpendRefused(409, {
                "error": MSG_TOO_MANY_OPEN[kind].format(limit=limit),
                "error_code": "too_many_open", "limit": limit, "kind": kind,
            })
        balance = int(locked.token_balance or 0)
        reserved = total_reserved(locked, strict=True)
        refusal = balance_refusal(balance, reserved, need, kind)
        if refusal:
            raise SpendRefused(402, refusal)
        yield locked


# ---------------------------------------------------------------- списание при выдаче

def _json_meta(meta) -> dict:
    """meta леджера — JSONField без кодировщика: Decimal и даты — строками."""
    if not meta:
        return {}
    from django.core.serializers.json import DjangoJSONEncoder

    try:
        return json.loads(json.dumps(dict(meta), cls=DjangoJSONEncoder))
    except (TypeError, ValueError):
        return {str(k): (v if isinstance(v, (str, int, float, bool)) or v is None else str(v))
                for k, v in dict(meta).items()}


def charge_on_delivery(user, amount: int, reason: str, meta=None) -> Charge:
    """Списать за выданный результат (§5.3). Зовётся В ТРАНЗАКЦИИ finalize,
    сразу после выигранного условного UPDATE saving→done (reserved→charged).

    1. charge_tokens(amount) — обычный случай: резерв гарантировал остаток.
    2. InsufficientTokens (изъятие при возврате платежа, ручная корректировка
       или остаточная гонка с чатом, который проверяет баланс без замка) —
       clawback_tokens «сколько есть» с meta.partial=True. Результат человек
       получает в любом случае: провайдеру уже заплачено.

    Возвращает Charge(credits=фактически списано, partial). partial=True —
    вызывающий ставит журналу needs_review и пишет credits_charged=credits.
    """
    from plans.models import VSTUDIO_SPEND_REASONS
    from plans.wallet import InsufficientTokens, charge_tokens, clawback_tokens

    amount = int(amount or 0)
    if amount < 0:
        raise ValueError("charge_on_delivery: amount must be non-negative")
    if reason not in VSTUDIO_SPEND_REASONS:
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
        logger.warning("vstudio partial charge user=%s take=%s wanted=%s charged=%s",
                       getattr(user, "pk", None), clean.get("take", "?"), amount, got)
        return Charge(int(got or 0), True)


__all__ = [
    "SpendRefused", "AlreadyStarted", "Charge", "spend_gate", "vstudio_reserved", "total_reserved",
    "balance_snapshot", "balance_refusal", "provider_refusal", "charge_on_delivery",
    "reason_for", "max_open", "min_provider_usd", "DEFAULT_MAX_OPEN",
]
