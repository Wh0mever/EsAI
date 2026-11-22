"""Цена инструмента в кредитах (SPEC_B §3).

credits = ai.pricing.credits_for_cost(cost_usd, …) с наценкой:
своя наценка инструмента (CreativeTool.use_own_markup + markup_pct), иначе
общая runtime «creative_markup_pct» (по умолчанию 40 %). Нижний порог
price_floor_pct из общих настроек цен действует и здесь (его держит ai.pricing).
Минимум 1 кредит. quote и run зовут одну и ту же функцию price().
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from types import SimpleNamespace

from ai import pricing as ai_pricing

from . import access, registry

logger = logging.getLogger(__name__)

RUNTIME_MARKUP_KEY = "creative_markup_pct"
DEFAULT_MARKUP_PCT = Decimal("40")
PCT_MIN = Decimal("0")
PCT_MAX = Decimal("1000")


def _pct(value) -> Decimal | None:
    if value in (None, ""):
        return None
    try:
        out = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return None
    if not out.is_finite():
        return None
    return min(PCT_MAX, max(PCT_MIN, out))


def global_markup_pct() -> Decimal:
    try:
        from adminapi.runtime import get_runtime

        raw = get_runtime(RUNTIME_MARKUP_KEY, "")
    except Exception:
        raw = ""
    value = _pct(raw)
    return DEFAULT_MARKUP_PCT if value is None else value


def own_markup_pct(slug: str, rows: dict | None = None) -> Decimal | None:
    rows = access.tool_rows() if rows is None else rows
    row = rows.get(slug)
    if row is None or not row.use_own_markup:
        return None
    return _pct(row.markup_pct)


def markup_pct(slug: str, rows: dict | None = None) -> Decimal:
    own = own_markup_pct(slug, rows)
    return own if own is not None else global_markup_pct()


@dataclass(frozen=True)
class Price:
    credits: int
    cost_usd: Decimal
    markup_pct: Decimal     # наценка, с которой реально посчитано (с учётом порога)


def credits_for(cost_usd: Decimal, slug: str, pct: Decimal) -> int:
    """Кредиты по себестоимости и наценке. PriceUnavailable — нет пакета с ценой."""
    model_like = SimpleNamespace(markup_pct=pct, openrouter_id=f"creative/{slug}")
    return max(1, int(ai_pricing.credits_for_cost(cost_usd, model_like)))


def price(tool: registry.Tool, params: dict, inputs: dict | None = None, *,
          rows: dict | None = None) -> Price:
    """Цена задачи. Бросает ai.pricing.PriceUnavailable."""
    cost = registry.cost_usd(tool, params, inputs or {})
    pct = markup_pct(tool.id, rows)
    credits = credits_for(cost, tool.id, pct)
    effective = max(pct, ai_pricing.current_config().floor_pct)
    return Price(credits=credits, cost_usd=cost, markup_pct=effective)


def hint_price(tool: registry.Tool, *, rows: dict | None = None) -> Price | None:
    """Цена «от …» по параметрам по умолчанию (видео — 5 с). None — цены нет."""
    params, inputs = registry.hint_params(tool)
    try:
        return price(tool, params, inputs, rows=rows)
    except Exception:
        return None


__all__ = ["Price", "price", "hint_price", "markup_pct", "global_markup_pct", "own_markup_pct",
           "credits_for", "RUNTIME_MARKUP_KEY", "DEFAULT_MARKUP_PCT"]
