"""Доступ активного креатора к платным моделям без покупки пакета.

Единственное место, которое это решает, — plans.tiers.user_tier: он зовёт
has_paid_access(). Больше нигде проверок «это креатор?» быть не должно.

Поле User.is_paid не меняется: ежедневный бонус, промокоды «только новым» и
отзыв тарифа при возврате смотрят на него и для креатора работают как прежде.
"""
from __future__ import annotations

import logging

from django.db import transaction

from . import flags
from .models import Creator

logger = logging.getLogger("creators")

_MEMO = "_creators_paid_access"


def has_paid_access(user) -> bool:
    """Пользуется ли человек платными моделями как участник программы. Никогда не бросает.

    Ответ запоминается на объекте пользователя: каталог моделей спрашивает тир
    на каждую модель, а объект живёт один запрос.
    """
    try:
        if not user or not getattr(user, "pk", None):
            return False
        memo = getattr(user, _MEMO, None)
        if memo is not None:
            return bool(memo)

        mode = flags.mode()
        staff = bool(getattr(user, "is_staff", False) or getattr(user, "is_superuser", False))
        if mode == flags.MODE_OFF or (mode != flags.MODE_ON and not staff):
            # Программа выключена или открыта только сотрудникам — в базу не идём.
            value = False
        else:
            # Своя точка сохранения: сбой запроса (например, таблицы ещё нет —
            # код выложен раньше миграции) не должен ломать транзакцию чата.
            with transaction.atomic():
                value = Creator.objects.filter(
                    user_id=user.pk, status=Creator.Status.ACTIVE).exists()
        try:
            setattr(user, _MEMO, value)
        except Exception:  # noqa: BLE001 — объект без записи атрибутов: просто не запоминаем
            pass
        return value
    except Exception:  # noqa: BLE001 — доступ к моделям не должен падать из-за программы
        logger.exception("creators.access: has_paid_access(%s) не посчитан",
                         getattr(user, "pk", None))
        return False
