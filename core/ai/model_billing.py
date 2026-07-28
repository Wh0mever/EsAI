"""FLUX (Black Forest Labs) image-billing: детекция модели + формула списания.

ЕДИНЫЙ источник истины, переиспользуемый:
  * ai/handlers.py       — для РЕАЛЬНОГО списания при генерации картинки;
  * plans/credit_value.py — для ОЦЕНКИ ("на что хватит") в калькуляторе пакетов.

Вынесено из ai/handlers.py в отдельный модуль намеренно: сам этот файл НЕ
импортирует ничего из plans (и вообще ничего из Django ORM/settings), поэтому
plans.credit_value может импортировать его на уровне модуля БЕЗ риска
циклического импорта — ai/handlers.py, в отличие от этого файла, тянет
plans.models/plans.wallet/plans.tiers на верхнем уровне, а plans импортирует
ai только лениво (внутри функций) именно из-за этого. model_billing.py не
имеет этой проблемы: он ничего не знает про plans и может подключаться сразу
с обеих сторон.

Если реальная логика здесь когда-нибудь изменится — она меняется РОВНО в
одном месте, и calculator (credit_value.py) не может тихо разъехаться с
реальным списанием.
"""
from __future__ import annotations

from typing import Any


def is_flux_image_model(model_ref: Any) -> bool:
    """FLUX (Black Forest Labs) image-модель — доступна ТОЛЬКО через images-API
    (POST /api/v1/images), в /v1/models и chat-modalities её нет.

    Определяем по openrouter_id: вендор 'black-forest-labs/' ИЛИ содержит 'flux.2'
    (black-forest-labs/flux.2-{klein-4b,pro,flex,max}). Такие модели идут отдельным
    путём генерации (см. ai.handlers._flux_generate_image), а не через
    chat-completions.
    """
    name = str(model_ref or "").lower().split(":")[0]
    return name.startswith("black-forest-labs/") or ("flux.2" in name)


def flux_charge_credits(model_obj: Any) -> int:
    """Плоское списание за ОДНУ FLUX-картинку = max(1, int(markup_coefficient)).

    У image-моделей markup_coefficient задан как КРЕДИТОВ ЗА КАРТИНКУ (в сиде),
    поэтому за генерацию списываем ровно столько (минимум 1). Токенов у images-API
    нет — токенный биллинг тут неприменим.
    """
    try:
        coeff = float(getattr(model_obj, "markup_coefficient", 1) or 1)
    except Exception:
        coeff = 1.0
    return max(1, int(coeff))
