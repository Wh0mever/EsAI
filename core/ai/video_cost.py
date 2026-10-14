"""Цена видео, которая не уходит ниже стоимости генерации у провайдера.

Цена ролика:
- тариф модели в админке — цена секунды в обычном качестве (720p);
- качество ниже — дешевле во столько раз, во сколько дешевле провайдеру;
- и никогда не ниже себестоимости / (1 − VIDEO_MIN_MARGIN), где себестоимость
  считается по прайсу OpenRouter (/videos/models → pricing_skus) для выбранного
  разрешения, пропорций и длительности, а кредит — по самому дешёвому кредиту
  среди продаваемых пакетов (сомы, доллары, Stars).

Прайс OpenRouter меняется — цена подтягивается сама.
"""
from __future__ import annotations

import logging
import math
import re
from decimal import Decimal

from django.conf import settings
from django.core.cache import cache

logger = logging.getLogger(__name__)

# Площадь кадра 16:9 для класса разрешения — если в каталоге нет размеров.
_PIXELS = {
    "480p": 854 * 480,
    "720p": 1280 * 720,
    "768p": 1366 * 768,
    "1024p": 1792 * 1024,
    "1080p": 1920 * 1080,
    "2k": 2560 * 1440,
    "4k": 3840 * 2160,
}
_RES_SUFFIXES = tuple(_PIXELS)
# Seedance считает видеотокены как ширина × высота × (24·секунды + 1) / 1024.
_TOKEN_FPS = 24

# Без выбранных пропорций модели снимают горизонтальный кадр.
_DEFAULT_ASPECT = "16:9"


def _num(value) -> float | None:
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    return f if f > 0 else None


def _pick(skus: dict, base: str, res: str) -> float | None:
    """Цена одного вида из прайса: вариант под разрешение важнее общего.

    Ключи бывают разные: duration_seconds_1080p, video_tokens_4k,
    duration_seconds_with_audio_4k, cents_per_video_output_second_720p.
    Со звуком и без берём дороже — генерация по умолчанию со звуком.
    """
    res = res.lower()
    exact: list[float] = []
    generic: list[float] = []
    for key, raw in skus.items():
        k = str(key).lower()
        if "with_video_input" in k:
            continue
        suffix = next((s for s in _RES_SUFFIXES if k.endswith("_" + s)), None)
        if suffix:
            k = k[: -(len(suffix) + 1)]
        k = re.sub(r"_(with|without)_audio$", "", k)
        if k != base:
            continue
        value = _num(raw)
        if value is None:
            continue
        if suffix == res:
            exact.append(value)
        elif suffix is None:
            generic.append(value)
    if exact:
        return max(exact)
    return max(generic) if generic else None


def _ratio_of(aspect: str | None) -> float | None:
    m = re.fullmatch(r"\s*(\d+(?:\.\d+)?)\s*[:x/]\s*(\d+(?:\.\d+)?)\s*", str(aspect or ""))
    if not m or float(m.group(2)) == 0:
        return None
    return float(m.group(1)) / float(m.group(2))


def _size_ladders(spec: dict | None) -> list[tuple[float, list[int]]]:
    """Размеры из каталога, сгруппированные по пропорциям: [(w/h, [площади по росту])]."""
    sizes = []
    for raw in (spec or {}).get("supported_sizes") or []:
        m = re.fullmatch(r"\s*(\d+)\s*[x×]\s*(\d+)\s*", str(raw))
        if m and int(m.group(2)):
            w, h = int(m.group(1)), int(m.group(2))
            sizes.append((w / h, w * h))
    sizes.sort()
    groups: list[tuple[float, list[int]]] = []
    for ratio, area in sizes:
        # 752×560 и 1112×834 — одни и те же 4:3, 992×432 и 1470×630 — одни 21:9.
        if groups and abs(ratio - groups[-1][0]) <= 0.05:
            groups[-1][1].append(area)
        else:
            groups.append((ratio, [area]))
    return [(ratio, sorted(set(areas))) for ratio, areas in groups]


def frame_area(spec: dict | None, resolution: str, aspect: str | None) -> int | None:
    """Пикселей в кадре для этого качества и пропорций — по размерам из каталога.

    21:9 у Seedance на треть больше 16:9 (2520×1080 против 1920×1080), квадрат —
    почти вдвое меньше. Размер берём по «лесенке» своих пропорций: у каждой
    пропорции столько размеров, сколько качеств умеет модель, по возрастанию.
    Площадью угадывать нельзя: у Seedance 2.0 квадрат 720p — это 720×720, а у
    2.5 — 960×960. Пропорции не известны — самый большой кадр, чтобы не занизить.
    """
    res = str(resolution or "").lower()
    nominal = _PIXELS.get(res)
    if not nominal:
        return None
    ladders = _size_ladders(spec)
    if not ladders:
        return nominal
    supported = sorted({str(r).lower() for r in ((spec or {}).get("supported_resolutions") or [])
                        if str(r).lower() in _PIXELS}, key=lambda r: _PIXELS[r])

    # Пропорции, чья лесенка ровно совпала с качествами модели, — им верим.
    mapped = [(ratio, areas[supported.index(res)]) for ratio, areas in ladders
              if supported and res in supported and len(areas) == len(supported)]
    wanted = _ratio_of(aspect)
    if wanted and mapped:
        ratio, area = min(mapped, key=lambda p: abs(p[0] - wanted))
        if abs(ratio - wanted) <= 0.08:
            return area
    if mapped:
        # Пропорции не выбраны или их лесенка неполная (у Seedance 2.0 для 9:21
        # в каталоге один размер) — самый большой кадр этого качества.
        return max(area for _, area in mapped)
    # Лесенок нет — ближайший по площади размер, но не меньше обычного кадра.
    near = [a for _, areas in ladders for a in areas if abs(math.log(a / nominal)) <= math.log(1.8)]
    return max([nominal] + [a for a in near if a >= nominal * 0.95])


def provider_cost_usd(spec: dict, resolution: str, duration: int, *, images: int = 0,
                      aspect: str | None = None) -> float | None:
    """Сколько OpenRouter возьмёт за ролик. None — прайс не разобрать."""
    skus = (spec or {}).get("pricing_skus") or {}
    if not isinstance(skus, dict) or not skus:
        return None
    res = str(resolution or "720p").lower()
    seconds = max(1, int(duration or 1))

    # Разные виды цены (за секунду, image→video, text→video, центы) — берём
    # самый дорогой: лучше чуть переоценить, чем снова работать в минус.
    candidates = [_pick(skus, base, res) for base in (
        "duration_seconds", "image_to_video_duration_seconds", "text_to_video_duration_seconds")]
    for cents_base in ("cents_per_video_output_second", "cents_per_second_output"):
        cents = _pick(skus, cents_base, res)
        if cents is not None:
            candidates.append(cents / 100.0)
    candidates = [c for c in candidates if c is not None]
    cost = None
    if candidates:
        cost = max(candidates) * seconds
    else:
        per_token = _pick(skus, "video_tokens", res)
        area = frame_area(spec, res, aspect)
        if per_token is not None and area:
            cost = area * (_TOKEN_FPS * seconds + 1) / 1024.0 * per_token
    if cost is None:
        return None
    if images:
        per_image = (_num(skus.get("reference_images")) or 0) + (_num(skus.get("cents_per_image_input")) or 0) / 100.0
        cost += images * per_image
    minimum = _num(skus.get("minimum_cents_per_generation"))
    if minimum:
        cost = max(cost, minimum / 100.0)
    return cost


def min_margin() -> float:
    try:
        from adminapi.runtime import get_runtime

        value = float(get_runtime("VIDEO_MIN_MARGIN", getattr(settings, "VIDEO_MIN_MARGIN", 0.4)))
    except Exception:
        value = float(getattr(settings, "VIDEO_MIN_MARGIN", 0.4))
    return min(0.9, max(0.0, value))


def cheapest_credit_usd() -> float | None:
    """Самый дешёвый кредит среди продаваемых пакетов, в долларах (кэш 10 мин).

    Считаем все способы купить: сомы (по курсу), доллары, Telegram Stars (по
    курсу вывода Stars и с бонусом за оплату Stars).
    """
    cached = cache.get("video_cost:credit_usd")
    if cached:
        return float(cached) if cached != "none" else None
    best = None
    try:
        from payments.crypto.rates import kgs_to_usd_rate
        from plans.models import TokenPackage

        rate = Decimal(str(kgs_to_usd_rate()))
        try:
            from plans.stars import withdraw_rate as stars_rate

            star_usd = Decimal(str(stars_rate()))
        except Exception:
            star_usd = Decimal("0")
        for p in TokenPackage.objects.filter(is_active=True):
            credits = int(p.tokens or 0) + int(p.bonus_tokens or 0)
            if credits <= 0:
                continue
            options = []
            currency = (p.currency or "KGS").upper()
            if p.price and currency == "KGS" and rate > 0:
                options.append(float(Decimal(str(p.price)) * rate / credits))
            elif p.price and currency == "USD":
                options.append(float(Decimal(str(p.price)) / credits))
            stars = int(getattr(p, "stars_price", 0) or 0)
            if stars and star_usd > 0:
                with_bonus = credits + int(getattr(p, "stars_bonus_tokens", 0) or 0)
                options.append(float(Decimal(stars) * star_usd / with_bonus))
            for usd in options:
                if usd > 0:
                    best = usd if best is None else min(best, usd)
    except Exception:
        logger.exception("video cost: цена кредита не посчиталась")
        best = None
    if best:
        cache.set("video_cost:credit_usd", best, 600)
    else:
        logger.error("video cost: нет ни одного пакета с ценой — нижней границы у цены видео нет")
        cache.set("video_cost:credit_usd", "none", 60)
    return best


def reference_resolution(spec: dict | None) -> str:
    """Качество, в котором задан тариф модели: 720p, если модель его умеет."""
    default = str(getattr(settings, "VIDEO_GEN_RESOLUTION", "720p") or "720p")
    supported = [str(r) for r in ((spec or {}).get("supported_resolutions") or []) if r]
    if not supported:
        return default
    low = {r.lower(): r for r in supported}
    return low.get(default.lower()) or supported[0]


def default_aspect(spec: dict | None) -> str | None:
    """Пропорции, если человек их не выбрал: 16:9, если модель так снимает."""
    allowed = [str(a) for a in ((spec or {}).get("supported_aspect_ratios") or []) if a]
    if not allowed or _DEFAULT_ASPECT in allowed:
        return _DEFAULT_ASPECT
    return None


def resolution_ratio(spec: dict | None, resolution: str, aspect: str | None = None) -> float:
    """Во сколько раз секунда в этом качестве дешевле/дороже, чем в опорном."""
    ref = reference_resolution(spec)
    here = provider_cost_usd(spec or {}, resolution, 1, aspect=aspect)
    there = provider_cost_usd(spec or {}, ref, 1, aspect=aspect)
    if not here or not there:
        return 1.0
    return here / there


def video_credits(model_obj, spec: dict | None, resolution: str, duration: int, *,
                  images: int = 0, aspect: str | None = None) -> int:
    """Итоговая цена ролика в кредитах.

    Тариф модели — это цена секунды в обычном качестве (720p). Качество ниже —
    дешевле ровно во столько раз, во сколько дешевле провайдеру (480p у Seedance
    вдвое дешевле: раньше человек платил за него как за 720p). Качество выше —
    не дешевле себестоимости плюс маржа (1080p у Seedance в 2,5 раза дороже).
    """
    try:
        coeff = float(getattr(model_obj, "markup_coefficient", 1) or 1)
    except Exception:
        coeff = 1.0
    seconds = max(1, int(duration or 1))
    aspect = aspect or default_aspect(spec)
    model_id = getattr(model_obj, "openrouter_id", "?")
    cost = provider_cost_usd(spec or {}, resolution, seconds, images=images, aspect=aspect)
    if cost is None:
        # Прайса нет (каталог недоступен или непонятного вида). Молча брать тариф
        # нельзя: 1080p ушёл бы по цене 720p. Выше опорного качества —
        # дорожаем пропорционально площади кадра, с запасом.
        ref_area = _PIXELS.get(reference_resolution(spec).lower()) or _PIXELS["720p"]
        area = _PIXELS.get(str(resolution or "").lower()) or ref_area
        scale = max(1.0, area / ref_area)
        if spec:
            logger.warning("video price: прайс %s не разобран — цена по тарифу ×%.2f", model_id, scale)
        elif scale > 1:
            logger.error("video price: каталог недоступен, %s %s — цена по тарифу ×%.2f",
                         model_id, resolution, scale)
        return max(1, math.ceil(seconds * coeff * scale))
    base = max(1, math.ceil(seconds * coeff * min(1.0, resolution_ratio(spec, resolution, aspect))))
    credit_usd = cheapest_credit_usd()
    if not credit_usd:
        return base
    floor = math.ceil(cost / (1.0 - min_margin()) / credit_usd)
    if floor > base:
        logger.info("video price: %s %s %s %sс — тариф %s, по себестоимости %s ($%.3f)",
                    model_id, resolution, aspect or "-", seconds, base, floor, cost)
    return max(base, floor)


def price_table(model_obj, spec: dict | None, resolutions: list[str], durations: list[int],
                aspect: str | None = None) -> dict:
    """Цены для витрины: {разрешение: {секунды: кредиты}} — фронт и бот не считают сами."""
    table: dict[str, dict[str, int]] = {}
    for res in resolutions or [str(getattr(settings, "VIDEO_GEN_RESOLUTION", "720p") or "720p")]:
        table[str(res)] = {str(d): video_credits(model_obj, spec, str(res), int(d), aspect=aspect)
                           for d in (durations or [])}
    return table


def price_tables_by_aspect(model_obj, spec: dict | None, resolutions: list[str],
                           durations: list[int]) -> dict:
    """{пропорции: таблица} — только если пропорции влияют на цену (Seedance)."""
    aspects = [str(a) for a in ((spec or {}).get("supported_aspect_ratios") or []) if a]
    if not aspects:
        return {}
    tables = {a: price_table(model_obj, spec, resolutions, durations, aspect=a) for a in aspects}
    first = next(iter(tables.values()))
    if all(t == first for t in tables.values()):
        return {}
    return tables
