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
        return share
    except Exception as exc:  # noqa: BLE001 — реферал не важнее покупки
        logger.exception("referral payout failed order=%s: %s", order_id, exc)
        return 0
