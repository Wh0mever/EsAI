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
        if not ref or base <= 0 or not order_id:
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
