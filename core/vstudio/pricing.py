"""Цены видеостудии (спецификация §5.1).

Цену считает только сервер и только отсюда: quote показывает её на кнопке,
запуск пересчитывает и сверяет с тем, что человек видел (409 price_changed),
резерв и списание берут ровно это число. Формулы — те же, что в чате и боте:
- видео — ai.video_cost.video_credits: тариф модели, но не ниже себестоимости
  у OpenRouter плюс маржа (VIDEO_MIN_MARGIN), с учётом разрешения, пропорций и
  отправляемых фото;
- картинка — ai.model_billing.flux_charge_credits: плоская цена за картинку,
  как у FLUX в чате и кадров мультстудии.

Режим markup (ai/pricing.py): видео — себестоимость с наценкой, без
себестоимости цены нет (NO_PRICE → запуск отклоняется); картинка —
себестоимость картинки плюс входные фото, если модель за них берёт.

Считаем по результату компилятора (compiled.effective, billable_images,
price_aspect), а не по сырому запросу: выключенные человеком фото не уходят и
не оплачиваются, а «Veo + референсы → 8 с» уже учтено в effective.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation

logger = logging.getLogger(__name__)

KIND_VIDEO = "video"
KIND_IMAGE = "image"

# Ключи строк раскладки (i18n ns vstudio на фронте, см. lib/vstudio/types.ts).
LINE_VIDEO = "price.video"
LINE_REFS = "price.refs"
LINE_IMAGE = "price.image"

# С такими ошибками компилятора цена была бы не за то, что просил человек:
# effective подставил значения по умолчанию вместо неверных. Лучше «цены нет»,
# чем точная цифра за другой ролик.
_UNPRICEABLE = frozenset({"model_unavailable", "prompt_doc_invalid"})
_PRICE_FIELDS = frozenset({"duration", "resolution", "aspect_ratio"})

# Сколько картинок за один запуск (Фаза 1: одна; варианты n ≤ 4 — Фаза 1.5).
IMAGES_PER_TAKE = 1


@dataclass(frozen=True)
class Price:
    """Цена запуска: credits (None — посчитать нельзя) и раскладка для quote."""

    credits: int | None
    breakdown: list = field(default_factory=list, hash=False, compare=False)

    @property
    def ok(self) -> bool:
        return self.credits is not None

    def to_dict(self) -> dict:
        return {"credits": self.credits, "breakdown": [dict(line) for line in self.breakdown]}


NO_PRICE = Price(None, [])


def _line(key: str, params: dict, credits: int) -> dict:
    return {"key": key, "params": params, "credits": int(credits)}


def _unpriceable(compiled) -> bool:
    for err in getattr(compiled, "errors", None) or []:
        code = err.get("code") if isinstance(err, dict) else None
        if code in _UNPRICEABLE:
            return True
        if code == "invalid_param" and (err.get("params") or {}).get("field") in _PRICE_FIELDS:
            return True
    return False


def image_credits(model_obj, refs: int = 0) -> int:
    """Одна картинка: max(1, int(markup_coefficient)) — как FLUX в чате и кадры мультстудии.

    markup: себестоимость картинки (+ refs входных фото) с наценкой (ai.pricing).
    """
    from ai.pricing import image_credits as priced

    return priced(model_obj, refs)


def _spec_for(model_obj, spec):
    if spec is not None:
        return spec
    from .caps import catalog_spec

    return catalog_spec(str(getattr(model_obj, "openrouter_id", "") or ""))


def price(compiled, model_obj, caps=None, *, spec: dict | None = None) -> Price:
    """Цена по результату компилятора (§5.1). NO_PRICE — посчитать нельзя.

    - compiled — vstudio.compiler.compile(...);
    - model_obj — GPTModels (markup_coefficient — тариф);
    - caps — Caps той же модели; None — модель скрыта, цены нет;
    - spec — спека каталога (caps.catalog_spec), чтобы не читать кэш дважды.

    Видео: total = video_credits(..., images=billable_images, aspect=price_aspect),
    строка «Видео» = video_credits(..., images=0), строка «Фото-референсы ×N» —
    разница, только если она больше нуля. Сумма строк всегда равна credits.
    """
    if compiled is None or model_obj is None or caps is None:
        return NO_PRICE
    kind = getattr(compiled, "kind", "")
    if kind != getattr(caps, "kind", None) or _unpriceable(compiled):
        return NO_PRICE

    if kind == KIND_IMAGE:
        from ai.pricing import is_markup

        per = image_credits(model_obj)
        total = per * IMAGES_PER_TAKE
        lines = [_line(LINE_IMAGE, {"n": IMAGES_PER_TAKE}, total)]
        refs = max(0, int(getattr(compiled, "billable_images", 0) or 0))
        if refs and is_markup():
            # FLUX Flex берёт и за входные фото: строка «Фото-референсы ×N» — разница.
            with_refs = image_credits(model_obj, refs) * IMAGES_PER_TAKE
            if with_refs > total:
                lines.append(_line(LINE_REFS, {"n": refs}, with_refs - total))
                total = with_refs
        return Price(total, lines)

    if kind != KIND_VIDEO:
        return NO_PRICE
    effective = getattr(compiled, "effective", None) or {}
    duration, resolution = effective.get("duration"), effective.get("resolution")
    if not duration or not resolution:
        return NO_PRICE

    from ai.pricing import PriceUnavailable
    from ai.video_cost import video_credits

    spec = _spec_for(model_obj, spec)
    images = max(0, int(getattr(compiled, "billable_images", 0) or 0))
    aspect = getattr(compiled, "price_aspect", None)
    try:
        total = video_credits(model_obj, spec, str(resolution), int(duration), images=images, aspect=aspect)
        base = (video_credits(model_obj, spec, str(resolution), int(duration), images=0, aspect=aspect)
                if images else total)
    except PriceUnavailable:
        # markup без себестоимости: цены нет — запуск отклонится, к тарифу не откатываемся.
        return NO_PRICE
    # Фото только добавляют к себестоимости, поэтому base ≤ total; min — на всякий
    # случай, чтобы строки раскладки никогда не расходились с итогом.
    base = min(base, total)
    params = {"s": int(duration), "res": str(resolution),
              "ar": str(effective.get("aspect_ratio") or "auto"), "price_ar": aspect or ""}
    lines = [_line(LINE_VIDEO, params, base)]
    if total > base:
        lines.append(_line(LINE_REFS, {"n": images}, total - base))
    return Price(total, lines)


def model_prices(model_obj, caps, *, spec: dict | None = None) -> dict:
    """Подсказки «от N кр» для ModelJSON (§8.3): та же формула, images=0.

    Видео: {"price": {"table": {res: {сек: кр}}, "by_aspect": {ar: table}},
    "per_image": None, "price_from": N}; by_aspect — только если пропорции
    меняют цену (Seedance). Картинка: {"price": None, "per_image": N,
    "price_from": N}. Точную цену запуска всё равно даёт только quote.
    """
    if caps is None or model_obj is None:
        return {"price": None, "per_image": None, "price_from": None}
    if caps.kind == KIND_IMAGE:
        per = image_credits(model_obj) * IMAGES_PER_TAKE
        return {"price": None, "per_image": per, "price_from": per}

    from ai.pricing import PriceUnavailable
    from ai.video_cost import price_table, price_tables_by_aspect

    spec = _spec_for(model_obj, spec)
    resolutions = [str(r) for r in caps.resolutions]
    durations = [int(d) for d in caps.durations]
    try:
        table = price_table(model_obj, spec, resolutions, durations)
        by_aspect = price_tables_by_aspect(model_obj, spec, resolutions, durations)
    except PriceUnavailable:
        return {"price": None, "per_image": None, "price_from": None}
    cells = [c for t in [table, *by_aspect.values()] for row in t.values() for c in row.values()]
    return {"price": {"table": table, "by_aspect": by_aspect}, "per_image": None,
            "price_from": min(cells) if cells else None}


def _usd(value) -> Decimal | None:
    if value in (None, ""):
        return None
    try:
        out = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return None
    return out if out > 0 else None


def check_margin(take, *, cost_usd=None) -> bool | None:
    """Контроль маржи после выдачи (§5.1). False — маржа ниже порога.

    Если credits_charged × cheapest_credit_usd() × (1 − min_margin()) < cost —
    logger.warning и шаг журнала low_margin. Цену не трогаем: она уже списана;
    сигнал нужен, чтобы вовремя поднять тариф модели в админке. В режиме
    markup порог — нижний порог наценки: выручка ≥ cost × (1 + floor/100) по
    кредиту ai.pricing.credit_usd().

    None — проверить нечем: себестоимость неизвестна, ничего не списано
    (бесплатный довоз из lost) или нет ни одного пакета с ценой. Никогда не
    бросает: зовётся после коммита выдачи.
    """
    try:
        cost = _usd(cost_usd if cost_usd is not None else getattr(take, "provider_cost_usd", None))
        charged = int(getattr(take, "credits_charged", 0) or 0)
        if cost is None or charged <= 0:
            return None
        from ai import pricing as ai_pricing

        cfg = ai_pricing.current_config()
        if cfg.markup:
            return _check_markup(take, charged, cost, cfg)
        from ai.video_cost import cheapest_credit_usd, min_margin

        credit_usd = cheapest_credit_usd()
        if not credit_usd:
            return None
        margin = min_margin()
        revenue = charged * float(credit_usd)
        if revenue * (1.0 - margin) >= float(cost):
            return True
        real = (1.0 - float(cost) / revenue) if revenue > 0 else -1.0
        note = (f"списано {charged} кр ≈ ${revenue:.4f}, себестоимость ${float(cost):.4f}, "
                f"маржа {real:.0%} при пороге {margin:.0%}")
        logger.warning("vstudio low margin take=%s model=%s %s", getattr(take, "uid", "?"),
                       getattr(take, "model_ref", "?"), note)
        _journal_step(getattr(take, "genlog_id", None), "low_margin", note)
        return False
    except Exception:
        logger.exception("vstudio: проверка маржи упала для %s", getattr(take, "uid", "?"))
        return None


def _check_markup(take, charged: int, cost: Decimal, cfg) -> bool | None:
    from ai import pricing as ai_pricing

    credit = ai_pricing.credit_usd(cfg)
    if not credit:
        return None
    revenue = Decimal(charged) * credit
    need = cost * (1 + cfg.floor_pct / 100)
    if revenue >= need:
        return True
    real = (revenue / cost - 1) if cost > 0 else Decimal("-1")
    note = (f"списано {charged} кр ≈ ${revenue:.4f}, себестоимость ${cost:.4f}, "
            f"наценка {real:.0%} при пороге {cfg.floor_pct / 100:.0%}")
    logger.warning("vstudio low margin take=%s model=%s %s", getattr(take, "uid", "?"),
                   getattr(take, "model_ref", "?"), note)
    _journal_step(getattr(take, "genlog_id", None), "low_margin", note)
    return False


def _journal_step(genlog_id, stage: str, note: str) -> None:
    if not genlog_id:
        return
    try:
        from ai.genlog import Entry
        from ai.models import GenerationLog

        row = GenerationLog.objects.filter(pk=genlog_id).first()
        if row is not None:
            Entry(row).stage(stage, note)
    except Exception:
        logger.warning("vstudio: шаг журнала %s не записался", stage, exc_info=True)


__all__ = [
    "Price", "NO_PRICE", "price", "model_prices", "image_credits", "check_margin",
    "LINE_VIDEO", "LINE_REFS", "LINE_IMAGE", "IMAGES_PER_TAKE",
]
