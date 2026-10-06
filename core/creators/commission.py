"""Комиссия креатора: начисление, отмена при возврате, ручные действия администратора.

Главное:
- база комиссии — реально уплаченные деньги в долларах (1 USD = 1 USDT). Курс и
  его источник записываются в строку: смена курса старые комиссии не трогает;
- процент и уровень — слепки на момент начисления;
- одна строка на (платёж, часть): повтор уведомления, сверка и дозачисление
  второй раз не начислят — это держит уникальный индекс, а не проверка в коде;
- любой возврат отменяет комиссию целиком. Отмена не смотрит на рубильник
  программы: деньги должны сойтись, даже если программу выключили;
- то, что вызывается из оплаты (accrue, reverse_for_payment), никогда не бросает
  исключений: сбой комиссии не должен откатывать кредиты покупателя.

Порядок блокировок: платёж -> покупатель -> креатор. Креатор блокируется только
через Creator.objects.locked().
"""
from __future__ import annotations

import logging
from datetime import timedelta
from decimal import ROUND_DOWN, Decimal

from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
from django.utils import timezone

from audit.services import log_admin_action, log_event
from payments.models import Payment

from . import flags, notify
from .errors import CreatorsError
from .models import Creator, CreatorCommission, CreatorReferral

logger = logging.getLogger(__name__)

Q6 = Decimal("0.000001")
Q2 = Decimal("0.01")
Q8 = Decimal("0.00000001")
ZERO = Decimal("0")

# Комиссии, которые ещё «живые»: их отменяет возврат и считает баланс.
OPEN = ("accrued", "held")

# Коридор курса сом -> доллар: вне его настройка испорчена (тот же, что у криптосчёта).
RATE_MIN = Decimal("0.0001")
RATE_MAX = Decimal("1")

# Запас на расхождение часов серверов, когда записи леджера ищут «не раньше платежа».
LEDGER_CLOCK_SKEW = timedelta(hours=1)


def _dec(value) -> Decimal:
    """Число из JSON платежа; мусор — ноль, а не исключение."""
    try:
        result = Decimal(str(value if value is not None else "0"))
    except Exception:  # noqa: BLE001
        return ZERO
    return result if result.is_finite() else ZERO


def _money2(value) -> str:
    return str(Decimal(value).quantize(Q2, rounding=ROUND_DOWN))


def _trim(value: Decimal, quantum: Decimal) -> str:
    """Число без хвостовых нулей: 0.115000 -> 0.115, 15.00 -> 15."""
    text = format(Decimal(value).quantize(quantum, rounding=ROUND_DOWN), "f")
    return text.rstrip("0").rstrip(".") if "." in text else text


def _required(reason) -> str:
    reason = str(reason or "").strip()
    if not reason:
        raise CreatorsError("reason_required")
    return reason


# ------------------------------------------------------------------ база ---

def kgs_rate() -> tuple[Decimal, str]:
    """Курс сом -> доллар и откуда он взят: manual / live / settings / settings_fallback.

    Порядок тот же, что у криптосчёта (payments/crypto/rates.py): ручное
    значение администратора, живой курс, настройка из окружения.
    """
    fallback = Decimal(str(settings.CURRENCY_KGS_TO_USD_RATE))
    try:
        from adminapi.runtime import get_runtime

        manual = Decimal(str(get_runtime("currency_kgs_to_usd_rate", 0.0)))
    except Exception:  # noqa: BLE001
        manual = ZERO

    if manual > 0:
        rate, source = manual, "manual"
    else:
        from payments.crypto.rates import market_rate

        live = market_rate()
        if live:
            rate, source = Decimal(str(live)), "live"
        else:
            rate, source = fallback, "settings"
    if not (RATE_MIN <= rate <= RATE_MAX):
        # Испорченный курс завысил бы комиссию в разы — берём значение из настроек.
        return fallback, "settings_fallback"
    return rate, source


def compute_base(payment, *, credited: int | None) -> tuple[Decimal, str, Decimal, str, Decimal]:
    """(paid_amount, paid_currency, rate_to_usd, rate_source, base_usd) для платежа.

    Бросает CreatorsError: no_base, unsupported_currency, unsupported_provider.
    Payment.success не читается: недоплаченный криптосчёт остаётся
    «неуспешным», хотя деньги по нему пришли.
    """
    req = payment.request or {}
    provider = str(payment.provider or "")
    amount = _dec(payment.amount)

    if provider in ("freedompay", "gopay"):
        # Единый QR (GoPay) — те же сомы, что и карта: база = сумма × курс сома.
        currency = str(payment.currency or "").upper()
        if currency == "KGS":
            rate, source = kgs_rate()
            base, rate_source = amount * rate, f"kgs:{source}"
        elif currency == "USD" and provider == "freedompay":
            # В долларах принимает только FreedomPay; у GoPay всё в сомах.
            base, rate_source = amount, "usd"
        else:
            raise CreatorsError("unsupported_currency")
        paid_amount, paid_currency = amount, currency
    elif provider == "yookassa":
        # Цена пакета в сомах: рублёвая сумма получена из неё по витринному курсу.
        kgs = _dec(req.get("kgs_price"))
        if kgs <= 0:
            rub_rate = _dec(req.get("rate_kgs_to_rub"))
            if rub_rate <= 0:
                raise CreatorsError("no_base")
            kgs = amount / rub_rate
        rate, source = kgs_rate()
        base, rate_source = kgs * rate, f"kgs_price:{source}"
        paid_amount, paid_currency = amount, "RUB"
    elif provider.startswith("crypto_"):
        # Крипта начисляется по частям: база части — доля цены, равная доле кредитов.
        info = req.get("token_purchase") or {}
        total = int(info.get("tokens") or 0) + int(info.get("bonus_tokens") or 0)
        part = int(credited or 0)
        if total <= 0 or part <= 0:
            raise CreatorsError("no_base")
        base, rate_source = amount * part / total, "usd"
        paid_amount, paid_currency = base.quantize(Q2, rounding=ROUND_DOWN), "USD"
    elif provider == "telegram_stars":
        from plans.stars import withdraw_rate

        # Stars стоят столько, сколько за них отдаёт Telegram при выводе.
        base, rate_source = amount * withdraw_rate(), "stars_withdraw_rate"
        paid_amount, paid_currency = amount, "XTR"
    else:
        raise CreatorsError("unsupported_provider")

    base = base.quantize(Q6, rounding=ROUND_DOWN)
    rate_to_usd = (base / paid_amount).quantize(Q8) if paid_amount > 0 else ZERO
    return paid_amount, paid_currency, rate_to_usd, rate_source, base


# --------------------------------------------------------------- возвраты ---

def _related(payment, name):
    """Счёт Stars / криптосчёт платежа или None (обратная связь бросает, когда строки нет)."""
    try:
        return getattr(payment, name)
    except Exception:  # noqa: BLE001 — RelatedObjectDoesNotExist
        return None


def refund_markers(payment) -> list[str]:
    """Все признаки того, что оплата возвращена. Порядок — от явного к косвенному."""
    resp = payment.response or {}
    markers: list[str] = []

    admin = resp.get("admin_refund")
    if admin:
        markers.append("admin_" + str((admin.get("kind") if isinstance(admin, dict) else "") or "refund"))
    if resp.get("token_purchase_clawed_back"):
        markers.append("clawback")
    star = _related(payment, "star_invoice")
    if star is not None and star.status == "refunded":
        markers.append("stars")
    crypto = _related(payment, "crypto_invoice")
    if crypto is not None and (crypto.status == "refunded" or (crypto.flags or {}).get("refund_seen")):
        markers.append("crypto")
    if resp.get("yookassa_refunded"):
        markers.append("yookassa")
    if resp.get("freedompay_refunded"):
        markers.append("freedompay")
    error = str(payment.error or "")
    if error in ("refunded", "stars_refunded"):
        markers.append("error_flag")
    if error.startswith("token_clawback_failed"):
        # Подписанный сигнал о возврате пришёл, но изъятие кредитов упало и
        # откатило вместе с собой отмену комиссии. Комиссия всё равно уходит.
        markers.append("clawback_failed")
    return markers


def refund_marker(payment) -> str:
    markers = refund_markers(payment)
    return markers[0] if markers else ""


def credited_at(payment, part: str = ""):
    """Когда по заказу (или его части) начислили кредиты. Записи нет — сейчас."""
    from plans.models import TokenTransaction

    if not payment.user_id or not payment.order_id:
        return timezone.now()
    rows = TokenTransaction.objects.filter(
        user_id=payment.user_id, reason="purchase", delta__gt=0,
        meta__order_id=payment.order_id)
    if part:
        rows = rows.filter(meta__idem=str(part))
    at = rows.order_by("created_at", "id").values_list("created_at", flat=True).first()
    return at or timezone.now()


def open_for_payment(payment_id) -> "list[CreatorCommission]":
    """Живые комиссии платежа (accrued | held). Только чтение."""
    return list(CreatorCommission.objects
                .filter(payment_id=payment_id, status__in=OPEN)
                .select_related("creator").order_by("id"))


# ------------------------------------------------------------- начисление ---

def _user_label(user) -> str:
    try:
        from users.views import _mask_user_label

        return _mask_user_label(user)
    except Exception:  # noqa: BLE001
        return "—"


def _announce(creator, row) -> None:
    """«Начислена комиссия» — когда строка стала заработком креатора."""
    notify.emit(creator, "commission_accrued",
                amount_usdt=_trim(row.amount_usdt, Q6),
                base_usdt=_money2(row.base_usd),
                percent=_trim(row.percent, Q2))


def _insert(fields: dict) -> CreatorCommission:
    # Своя точка сохранения: нарушение уникальности (платёж, часть) не должно
    # ломать транзакцию начисления кредитов.
    with transaction.atomic():
        return CreatorCommission.objects.create(**fields)


def _share_paid(payment) -> bool:
    """Заплачена ли с этого заказа обычная реферальная доля (кому угодно)."""
    from plans.models import TokenTransaction

    shares = TokenTransaction.objects.filter(reason="referral", delta__gt=0,
                                             meta__order_id=payment.order_id)
    if payment.created_at:
        # Доля платится не раньше, чем создан платёж. Без этой границы запрос
        # перебирал бы весь леджер (по причине и JSON индекса нет) — и делал бы
        # это на каждой оплате, держа блокировку креатора.
        shares = shares.filter(created_at__gte=payment.created_at - LEDGER_CLOCK_SKEW)
    return shares.exists()


def _owner_active(creator) -> bool:
    """Включён ли аккаунт, которому принадлежит креатор (строку User не блокируем)."""
    return bool(getattr(creator.user, "is_active", True))


def _decide(payment, buyer, creator, referral, credited):
    """(status, reason, база | None) — первое подходящее правило."""
    req = payment.request or {}
    if not req.get("token_purchase"):
        # Старое списание с сохранённой карты: это не покупка пакета.
        return "void", "no_token_purchase", None
    if payment.is_test:
        return "void", "test_payment", None
    if creator.user_id == buyer.pk:
        return "void", "self_purchase", None
    if buyer.is_staff or buyer.is_superuser:
        return "void", "buyer_staff", None
    if getattr(buyer, "is_unlimited", False):
        return "void", "buyer_unlimited", None
    if payment.order_id and _share_paid(payment):
        # С этого заказа уже заплачена обычная реферальная доля: двух программ сразу не бывает.
        return "void", "referral_share_paid", None
    try:
        base = compute_base(payment, credited=credited)
    except CreatorsError as exc:
        return "void", exc.code, None
    if base[4] <= 0:
        return "void", "zero_base", base
    marker = refund_marker(payment)
    if marker:
        # Оплату успели вернуть раньше, чем дошло начисление.
        return "reversed", f"refund:{marker}", base
    if creator.status == "blocked":
        return "held", "creator_blocked", base
    if not _owner_active(creator):
        # Аккаунт креатора отключён: войти в кабинет некому. Комиссии копятся
        # придержанными, пока администратор не разберётся, чьи это деньги.
        return "held", "creator_inactive", base
    if referral.suspect:
        return "held", "referral_suspect", base
    return "accrued", "", base


def _accrue(payment, referral, part: str, credited):
    if not flags.accrual_enabled() or not getattr(payment, "pk", None):
        return None
    buyer = getattr(payment, "user", None)
    if buyer is None or not getattr(buyer, "pk", None):
        return None

    existing = CreatorCommission.objects.filter(payment=payment, part=part).first()
    if existing is not None:
        return existing

    referral = referral or CreatorReferral.objects.covering(buyer.pk, credited_at(payment, part))
    if referral is None:
        return None

    creator = Creator.objects.locked(referral.creator_id)
    # Под блокировкой смотрим ещё раз: хук оплаты и дозачисление идут параллельно.
    existing = CreatorCommission.objects.filter(payment=payment, part=part).first()
    if existing is not None:
        return existing

    status, reason, base = _decide(payment, buyer, creator, referral, credited)
    now = timezone.now()
    percent = creator.level.percent
    if base is None:
        paid_amount, paid_currency = _dec(payment.amount), str(payment.currency or "")[:10]
        rate_to_usd, rate_source, base_usd = ZERO, "", ZERO
    else:
        paid_amount, paid_currency, rate_to_usd, rate_source, base_usd = base
    amount_usdt = ZERO
    if status != "void":
        amount_usdt = (base_usd * percent / 100).quantize(Q6, rounding=ROUND_DOWN)

    fields = dict(
        creator=creator, referral=referral, buyer=buyer, buyer_pk=buyer.pk, payment=payment,
        part=part, order_id=str(payment.order_id or "")[:64], provider=str(payment.provider or ""),
        paid_amount=paid_amount, paid_currency=paid_currency, rate_to_usd=rate_to_usd,
        rate_source=rate_source, base_usd=base_usd, level_key=creator.level.key,
        percent=percent, amount_usdt=amount_usdt, status=status, reason=reason,
        available_at=(now + timedelta(days=flags.hold_days())) if status in OPEN else None,
        reversed_at=now if status == "reversed" else None,
    )
    try:
        row = _insert(fields)
    except IntegrityError:
        # Строку (платёж, часть) успел создать параллельный вызов — она и есть результат.
        return CreatorCommission.objects.filter(payment=payment, part=part).first()

    if status in OPEN:
        _after_accrual(creator, row, buyer)
    return row


def _announce_earning(creator, row, buyer=None) -> None:
    """Сообщить креатору о строке, ставшей заработком: «новый платящий» и «начислена комиссия».

    Придержанная строка (подозрительный реферал, заблокированный креатор)
    креатору не объявляется вовсе: подозрительный реферал для него невидим,
    пока администратор не снимет пометку, а счётчик «Платящие» такую оплату не
    считает. О платящем сообщаем, когда его первая комиссия стала заработком.
    """
    first_for_buyer = not (CreatorCommission.objects
                           .filter(creator=creator, buyer_pk=row.buyer_pk, status="accrued")
                           .exclude(pk=row.pk).exists())
    if first_for_buyer:
        notify.emit(creator, "new_paying_user", user_label=_user_label(buyer or row.buyer))
    _announce(creator, row)


def _after_accrual(creator, row, buyer) -> None:
    """Уведомления и прогресс уровня. Сбой здесь начисление не отменяет."""
    try:
        if row.status == "accrued":
            _announce_earning(creator, row, buyer)
    except Exception:  # noqa: BLE001
        logger.exception("creators: уведомление о комиссии %s не поставлено", row.pk)
    try:
        from .stats import check_next_level

        # Точка сохранения: ошибка базы внутри не должна отравить транзакцию оплаты.
        with transaction.atomic():
            check_next_level(creator)
    except Exception:  # noqa: BLE001
        logger.exception("creators: проверка следующего уровня не выполнена creator=%s", creator.pk)


def accrue(payment, *, referral=None, part: str = "", credited: int | None = None):
    """Начислить комиссию за оплаченный заказ (или его часть). Никогда не бросает.

    Идемпотентно по (платёж, часть): повторный вызов возвращает ту же строку.
    Возвращает строку комиссии (в любом статусе) или None, когда начислять
    некому или начисление сорвалось — тогда его доделает backfill_commissions.
    """
    part = str(part or "")
    try:
        with transaction.atomic():
            return _accrue(payment, referral, part, credited)
    except Exception:  # noqa: BLE001 — комиссия не важнее покупки
        order_id = getattr(payment, "order_id", "")
        logger.exception("creator commission failed order=%s part=%s", order_id, part)
        try:
            # Точка сохранения: запись в журнал событий не должна отравить транзакцию оплаты.
            with transaction.atomic():
                log_event("payment", level="error",
                          message=f"creator_commission_failed order={order_id} part={part}",
                          user=getattr(payment, "user", None),
                          meta={"order_id": order_id, "part": part})
        except Exception:  # noqa: BLE001
            pass
        return None


# ----------------------------------------------------------------- отмена ---

def reverse_for_payment(payment, reason: str) -> int:
    """Отменить все живые комиссии платежа. Возвращает число отменённых строк.

    Режим программы не читает. Идемпотентно: отменённое второй раз не трогается.
    Никогда не бросает (сбой — 0; такой платёж подберёт commission_safety_net).
    """
    try:
        payment_id = getattr(payment, "pk", None)
        if not payment_id:
            return 0
        with transaction.atomic():
            rows = CreatorCommission.objects.filter(payment_id=payment_id, status__in=OPEN)
            creator_ids = sorted(set(rows.values_list("creator_id", flat=True)))
            if not creator_ids:
                # Обычный платёж без комиссии: ни одной блокировки не берём.
                return 0
            # Покупатель раньше креатора. Возврат попадает сюда ДО того, как
            # изъятие кредитов заблокирует покупателя, а покупка блокирует
            # покупателя первым и креатора вторым — без этой строки возврат
            # одного заказа и оплата другого того же человека встали бы намертво.
            if payment.user_id:
                get_user_model().objects.select_for_update().filter(pk=payment.user_id).first()
            for creator_id in creator_ids:
                Creator.objects.locked(creator_id)
            now = timezone.now()
            return rows.update(status="reversed", reversed_at=now,
                               reason=str(reason or "")[:64], updated_at=now)
    except Exception:  # noqa: BLE001 — возврат покупки не должен падать из-за комиссии
        logger.exception("creator commission reversal failed payment=%s",
                         getattr(payment, "pk", None))
        return 0


# ------------------------------------------------- действия администратора ---

def _locked_row(commission_id):
    """Креатор и комиссия под блокировкой. Вызывающий внутри transaction.atomic()."""
    probe = (CreatorCommission.objects.filter(pk=commission_id)
             .values("id", "creator_id").first())
    if probe is None:
        raise CreatorsError("not_found")
    creator = Creator.objects.locked(probe["creator_id"])
    row = CreatorCommission.objects.select_for_update(of=("self",)).get(pk=probe["id"])
    return creator, row


def _state(row) -> dict:
    return {"status": row.status, "reason": row.reason}


def void(commission_id, *, actor, reason: str, request=None) -> CreatorCommission:
    """Аннулировать комиссию вручную. Сумма в строке остаётся — её можно вернуть restore()."""
    reason = _required(reason)
    with transaction.atomic():
        creator, row = _locked_row(commission_id)
        if row.status not in OPEN:
            raise CreatorsError("bad_state")
        before = _state(row)
        row.status, row.reason = "void", "admin_void"
        row.save(update_fields=["status", "reason", "updated_at"])
        log_admin_action(actor, "commission.void", target=row, creator=creator,
                         before=before, after=_state(row), reason=reason, request=request)
    return row


def release(commission_id, *, actor, reason: str = "", request=None) -> CreatorCommission:
    """Снять удержание: held -> accrued. Срок холда не меняется."""
    with transaction.atomic():
        creator, row = _locked_row(commission_id)
        if row.status != "held":
            raise CreatorsError("bad_state")
        if refund_marker(row.payment):
            raise CreatorsError("payment_refunded")
        before = _state(row)
        row.status, row.reason = "accrued", "released"
        row.save(update_fields=["status", "reason", "updated_at"])
        log_admin_action(actor, "commission.release", target=row, creator=creator,
                         before=before, after=_state(row), reason=str(reason or ""),
                         request=request)
        # Придержанную строку креатору не объявляли ни как заработок, ни как
        # оплату нового пользователя — сообщаем сейчас.
        _announce_earning(creator, row)
    return row


def restore(commission_id, *, actor, reason: str, clear_admin_refund: bool = False,
            request=None) -> CreatorCommission:
    """Вернуть комиссию после ошибочной отмены или ручного аннулирования.

    Платёж, возвращённый по данным провайдера, восстановить нельзя — страховка
    отменила бы комиссию снова. Единственное исключение — ручная отметка
    администратора (mark_payment_refunded без изъятия кредитов): с
    clear_admin_refund=True она снимается здесь же, с записью в журнале.

    Строка возвращается заработком (accrued / restored), только если её больше
    не за что придерживать: у заблокированного креатора, у креатора с отключённым
    аккаунтом, у собственной покупки креатора и у подозрительного реферала она
    остаётся held со своей причиной.
    """
    reason = _required(reason)
    with transaction.atomic():
        probe = (CreatorCommission.objects.filter(pk=commission_id)
                 .values("id", "payment_id").first())
        if probe is None:
            raise CreatorsError("not_found")
        payment = None
        if clear_admin_refund:
            # Порядок блокировок: платёж раньше креатора.
            payment = Payment.objects.select_for_update().get(pk=probe["payment_id"])
        creator, row = _locked_row(commission_id)
        if not (row.status == "reversed" or (row.status == "void" and row.reason == "admin_void")):
            # Аннулированное самим начислением (нулевая сумма) возвращать нечем.
            raise CreatorsError("bad_state")
        payment = payment or row.payment

        markers = refund_markers(payment)
        if markers:
            only_admin = all(marker.startswith("admin_") for marker in markers)
            if not (clear_admin_refund and only_admin):
                raise CreatorsError("payment_refunded")
            response = payment.response or {}
            cleared = dict(response.pop("admin_refund") or {})
            cleared.update(cleared_by_id=actor.pk, cleared_at=timezone.now().isoformat())
            response["admin_refund_cleared"] = cleared
            payment.response = response
            payment.save(update_fields=["response"])
            log_admin_action(actor, "payment.mark_refunded", target=payment, creator=creator,
                             before={"admin_refund": cleared.get("kind")},
                             after={"cleared": True}, reason=reason, request=request)

        before = _state(row)
        now = timezone.now()
        matured = row.available_at or (row.created_at + timedelta(days=flags.hold_days()))
        # Возврат строки не снимает причину, по которой её придерживали: иначе
        # «аннулировать и вернуть» превращало бы придержанное в заработок в обход
        # снятия пометки с реферала.
        if creator.status == "blocked":
            row.status, row.reason = "held", "creator_blocked"
        elif not _owner_active(creator):
            row.status, row.reason = "held", "creator_inactive"
        elif creator.user_id == row.buyer_pk:
            row.status, row.reason = "held", "merge_self"
        elif row.referral_id and row.referral.suspect:
            row.status, row.reason = "held", "referral_suspect"
        else:
            row.status, row.reason = "accrued", "restored"
        row.reversed_at = None
        row.available_at = max(matured, now)
        row.save(update_fields=["status", "reason", "reversed_at", "available_at", "updated_at"])
        log_admin_action(actor, "commission.restore", target=row, creator=creator,
                         before=before, after=_state(row), reason=reason, request=request)
    return row


def _clawback_credits(payment) -> None:
    """Изъять кредиты заказа прежним кодом возврата (кредиты, обычная доля, тариф)."""
    from payments import views as payment_views

    payment_views._clawback_token_package_for_payment(payment, payment.order_id, {})
    payment.success = False
    payment.error = payment.error or "refunded"


def mark_payment_refunded(payment_id, *, kind: str, actor, reason: str,
                          clawback_credits: bool = False, request=None) -> dict:
    """Ручная отметка «платёж возвращён» (refund) или «мошенничество» (fraud).

    Отменяет комиссию; кредиты покупателя изымает только по явной просьбе
    (clawback_credits). Повторить можно один раз — чтобы изъять кредиты, если
    при первой отметке их оставили.
    """
    kind = str(kind or "")
    if kind not in ("refund", "fraud"):
        raise CreatorsError("kind_invalid")
    reason = _required(reason)
    clawback_credits = bool(clawback_credits)

    with transaction.atomic():
        payment = Payment.objects.select_for_update().filter(pk=payment_id).first()
        if payment is None:
            raise CreatorsError("not_found")
        response = payment.response or {}
        prev = response.get("admin_refund")
        before = {"success": payment.success, "error": payment.error}
        reversed_count = 0

        if not prev:
            rows = open_for_payment(payment.pk)
            creator = rows[0].creator if rows else None
            # Отметку кладём ДО изъятия: оно делает `payment.response or {}`, и
            # при пустом ответе собрало бы новый словарь — отметка потерялась бы.
            response["admin_refund"] = {"kind": kind, "by_id": actor.pk,
                                        "at": timezone.now().isoformat(), "reason": reason,
                                        "clawback": clawback_credits}
            payment.response = response
            # Отмена раньше изъятия: в комиссии остаётся причина администратора,
            # а не «refund:<провайдер>» из общего кода возврата.
            reversed_count = reverse_for_payment(payment, "fraud" if kind == "fraud" else "refund:admin")
            if clawback_credits:
                _clawback_credits(payment)
            after = {"kind": kind, "reversed": reversed_count, "clawback_credits": clawback_credits}
        else:
            if not clawback_credits or prev.get("clawback"):
                raise CreatorsError("already_marked")
            first = CreatorCommission.objects.filter(payment=payment).select_related("creator").first()
            creator = first.creator if first else None
            _clawback_credits(payment)
            response = payment.response or {}
            response["admin_refund"] = {**prev, "clawback": True}
            payment.response = response
            after = {"kind": prev.get("kind"), "followup": True, "reversed": 0,
                     "clawback_credits": True}

        payment.save(update_fields=["response", "success", "error"])
        after.update(success=payment.success, error=payment.error)
        log_admin_action(actor, "payment.mark_refunded", target=payment, creator=creator,
                         before=before, after=after, reason=reason, request=request)
        debited = int((payment.response or {}).get("clawback_debited") or 0)
    return {"reversed": reversed_count, "clawback_debited": debited}
