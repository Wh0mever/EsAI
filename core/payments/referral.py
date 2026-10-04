"""Реферальная доля с покупки: пригласивший получает % от купленных кредитов.

Раньше эта выплата жила внутри задачи сверки (tasks._verify_and_credit) и
поэтому доставалась только тем, чей платёж дошёл до сверки. У покупок,
подтверждённых постбэком или вебхуком (обычный путь), пригласивший не получал
ничего — обещание «10% пожизненно» выполнялось не всегда.

Теперь выплата в одном месте, вызывается из общего начисления, идемпотентна по
order_id и никогда не роняет покупку: сбой здесь не должен откатывать уже
зачисленные покупателю кредиты.
"""
from __future__ import annotations

import logging

from django.conf import settings
from django.db import transaction
from django.utils import timezone

logger = logging.getLogger(__name__)


def referral_percent() -> int:
    try:
        from adminapi.runtime import get_runtime

        return int(get_runtime("REFERRAL_PERCENT", int(getattr(settings, "REFERRAL_PERCENT", 10))))
    except Exception:  # noqa: BLE001
        return int(getattr(settings, "REFERRAL_PERCENT", 10))


def pay_referral_share(buyer, order_id: str, base_credits: int, *, idem_suffix: str = "") -> int:
    """Начислить пригласившему его долю. Возвращает сколько начислено.

    idem_suffix нужен крипте: там один заказ может начисляться по частям
    (недоплата, потом доплата), и каждая часть должна оплатиться ровно раз.
    Пусто — обычная разовая покупка картой.
    """
    from plans.models import TokenTransaction
    from plans.wallet import credit_tokens

    try:
        ref = getattr(buyer, "referred_by", None)
        base = int(base_credits or 0)
        # Сам себе пригласивший (след слияния аккаунтов) долю не получает.
        if not ref or getattr(ref, "pk", None) == getattr(buyer, "pk", None) or base <= 0 or not order_id:
            return 0

        percent = referral_percent()
        share = (base * percent) // 100
        if share <= 0:
            return 0

        with transaction.atomic():
            paid = TokenTransaction.objects.filter(
                user=ref, reason="referral", meta__order_id=order_id)
            if idem_suffix:
                paid = paid.filter(meta__idem=str(idem_suffix))
            if paid.exists():
                return 0
            meta = {
                "order_id": order_id,
                "from_user_id": getattr(buyer, "id", None),
                "percent": percent,
                "base_credits": base,
            }
            if idem_suffix:
                meta["idem"] = str(idem_suffix)
            credit_tokens(ref, share, "referral", meta=meta)
        try:
            from botapi.tasks import notify

            notify(
                ref, "referral",
                f"🤝 <b>+{int(share)} кредитов</b>\nВаш друг пополнил баланс — "
                f"вам начислена доля с этой покупки.",
            )
        except Exception:
            logger.exception("telegram referral notify failed order=%s", order_id)
        return share
    except Exception as exc:  # noqa: BLE001 — реферал не важнее покупки
        logger.exception("referral payout failed order=%s: %s", order_id, exc)
        return 0


def settle_referral(payment, order_id: str, credited: int, *, idem: str = "") -> str:
    """Кому причитается с оплаченного заказа: креатору или обычному пригласившему.

    Возвращает "commission" | "referral" | "none". Двух программ сразу не
    бывает: если покупатель закреплён за креатором (программа EsAI Creators),
    тот получает комиссию в USDT, а доля кредитами не платится никому. Все
    остальные заказы идут через pay_referral_share ровно как раньше.

    Привязка проверяется на момент ЗАЧИСЛЕНИЯ, а не создания платежа: строка
    платежа появляется при открытии оплаты и живёт долго (счёт Stars — сутки,
    криптосчёт — до оплаты). Человек, который открыл оплату, ввёл промокод
    креатора и потом оплатил тот же заказ, должен дать креатору комиссию.

    Никогда не бросает исключений: покупка важнее.
    """
    buyer = getattr(payment, "user", None)
    part = str(idem or "")

    referral = None
    has_commission = False
    try:
        # Своя точка сохранения: ошибка базы здесь не должна отравить транзакцию покупки.
        with transaction.atomic():
            from creators import flags
            from creators.models import CreatorCommission, CreatorReferral

            if flags.accrual_enabled() and buyer is not None and getattr(buyer, "pk", None):
                referral = CreatorReferral.objects.covering(buyer.pk, timezone.now())
            if referral is None and getattr(payment, "pk", None):
                # Зеркало правила referral_share_paid в начислении комиссии. Криптосчёт
                # зачисляется частями: если с первой части креатор уже получил
                # комиссию, а привязку потом сняли (или программу выключили), доля
                # кредитами с остатка того же заказа не платится. От рубильника
                # программы проверка не зависит.
                has_commission = CreatorCommission.objects.filter(
                    payment_id=payment.pk, status__in=("accrued", "held")).exists()
    except Exception:  # noqa: BLE001 — обычная реферальная программа должна отработать
        logger.exception("creator coverage lookup failed order=%s", order_id)
        referral = None
        has_commission = False

    if referral is not None:
        try:
            from creators.commission import accrue

            accrue(payment, referral=referral, part=part, credited=int(credited or 0))
        except Exception:  # noqa: BLE001 — дозачислит creators.tasks.backfill_commissions
            logger.exception("creator commission accrual failed order=%s", order_id)
        return "commission"

    if has_commission:
        return "none"

    share = pay_referral_share(buyer, order_id, credited, idem_suffix=part)
    return "referral" if share else "none"


def reverse_creator_commission(payment, reason: str) -> int:
    """Возврат оплаты: отменить комиссию креатора по этому платежу.

    Тонкая обёртка для кода оплаты: ленивый импорт и никаких исключений наружу.
    Возвращает число отменённых строк (0 — комиссии не было или сбой; сбой
    подберёт страховочная задача creators.tasks.commission_safety_net).
    """
    try:
        from creators.commission import reverse_for_payment

        return int(reverse_for_payment(payment, reason) or 0)
    except Exception:  # noqa: BLE001 — возврат не должен падать из-за комиссии
        logger.exception("creator commission reversal failed order=%s",
                         getattr(payment, "order_id", ""))
        return 0


def clawback_referral_share(order_id: str) -> int:
    """Возврат покупки: забрать у пригласившего долю, начисленную с этого заказа.

    Раньше возврат изымал кредиты только у покупателя, а реферер оставлял свои
    10 % — купить через свой второй аккаунт и вернуть деньги было выгодно.
    Идемпотентно: уже изъятое по этому заказу второй раз не изымается.
    Возвращает сколько изъято всего.
    """
    from plans.models import TokenTransaction
    from plans.wallet import clawback_tokens

    if not order_id:
        return 0
    taken = 0
    for share in TokenTransaction.objects.filter(reason="referral", meta__order_id=order_id,
                                                 delta__gt=0).select_related("user"):
        idem = f"{share.pk}"
        if TokenTransaction.objects.filter(user=share.user, reason="refund",
                                           meta__kind="referral_clawback",
                                           meta__share_tx=idem).exists():
            continue
        try:
            taken += clawback_tokens(
                share.user, int(share.delta), "refund",
                meta={"kind": "referral_clawback", "order_id": order_id, "share_tx": idem},
            )
        except Exception:
            logger.exception("referral clawback failed order=%s share=%s", order_id, share.pk)
    return taken
