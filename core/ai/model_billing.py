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


# Сколько входных фото считать, когда вызывающий их не назвал (refs=None). Чат
# (ai/handlers.py) пока зовёт без refs, хотя отдаёт FLUX все приложенные фото, а
# FLUX Flex берёт деньги за каждое: по нулю фото правка в режиме «наценка» шла
# дешевле себестоимости. Обычная правка — одно фото; моделям без платы за фото
# (ref_cost_usd пуст) это ничего не меняет.
UNKNOWN_REFS = 1

# Больше фото ai.handlers._flux_generate_image провайдеру не шлёт.
FLUX_MAX_REFS = 8


def flux_ref_count(references: Any) -> int:
    """Сколько приложенных фото на самом деле уйдёт в FLUX — за столько и берём деньги.

    Тот же отбор, что в ai.handlers._flux_generate_image: только абсолютные
    http(s)-URL и не больше FLUX_MAX_REFS. Иначе девятое фото или битая ссылка
    попали бы в цену, хотя провайдер их не получает.
    """
    urls = [u for u in (references or []) if isinstance(u, str) and u.startswith("http")]
    return min(len(urls), FLUX_MAX_REFS)


def flux_charge_credits(model_obj: Any, refs: int | None = None) -> int:
    """Списание за ОДНУ FLUX-картинку.

    legacy: max(1, int(markup_coefficient)) — у image-моделей тариф задан как
    КРЕДИТОВ ЗА КАРТИНКУ (в сиде). markup: себестоимость картинки и refs входных
    фото с наценкой (ai.pricing.image_credits; без unit_cost_usd — прежняя плоская
    цена). refs=None — число фото неизвестно, считаем UNKNOWN_REFS; без фото — 0.
    Чату число фото даёт flux_ref_count(список URL, которые уйдут в FLUX).
    Токенов у images-API нет — токенный биллинг тут неприменим.

    ai.pricing импортируется лениво: этот модуль подключают на уровне модуля и
    plans, и ai.handlers (см. докстринг модуля).
    """
    from ai.pricing import image_credits

    return image_credits(model_obj, UNKNOWN_REFS if refs is None else refs)
