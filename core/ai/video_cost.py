"""Цена видео, которая не уходит ниже себестоимости.

Случай 22.09.2026: цена видео была «кредитов за секунду» без оглядки на
разрешение. Коэффициент Seedance 2.0 (32 кр/с) рассчитан на 720p, а человек
выбирал 1080p × 15 с — OpenRouter брал $5.63 за ролик, мы списывали 480
кредитов (≈ $4–5.4 в зависимости от пакета). Четыре ролика — минус на
балансе OpenRouter и ноль маржи.

Теперь цена = max(тариф модели × секунды, себестоимость / (1 − маржа)).
Себестоимость считается по прайсу OpenRouter (/videos/models → pricing_skus)
для выбранного разрешения, а «сколько стоит кредит» — по самому дешёвому
кредиту среди продаваемых пакетов: так маржа держится даже у того, кто
купил самый большой пакет. Прайс OpenRouter меняется — цена подтягивается
сама, тариф в админке остаётся нижней границей.
"""
from __future__ import annotations

import logging
import math
import re
from decimal import Decimal

from django.conf import settings
from django.core.cache import cache

logger = logging.getLogger(__name__)

# Пикселей в кадре при данном разрешении (вертикаль и квадрат того же класса
# дают столько же пикселей). Нужны моделям, которые берут плату за видеотокены.
_PIXELS = {
    "480p": 854 * 480,
    "720p": 1280 * 720,
    "768p": 1366 * 768,
    "1024p": 1792 * 1024,
    "1080p": 1920 * 1080,
    "2k": 2560 * 1440,
    "4k": 3840 * 2160,
}
# Seedance считает видеотокены как ширина × высота × кадры / 1024.
_TOKEN_FPS = 24


def _num(value) -> float | None:
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    return f if f > 0 else None


_RES_SUFFIXES = tuple(_PIXELS)


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


def provider_cost_usd(spec: dict, resolution: str, duration: int, *, images: int = 0) -> float | None:
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
    cents = _pick(skus, "cents_per_video_output_second", res)
    if cents is not None:
        candidates.append(cents / 100.0)
    candidates = [c for c in candidates if c is not None]
    per_second = max(candidates) if candidates else None
    cost = None
    if per_second is not None:
        cost = per_second * seconds
    else:
        per_token = _pick(skus, "video_tokens", res)
        pixels = _PIXELS.get(res)
        if per_token is not None and pixels:
            cost = pixels * _TOKEN_FPS * seconds / 1024.0 * per_token
    if cost is None:
        return None
    per_image = _num(skus.get("reference_images"))
    per_image_cents = _num(skus.get("cents_per_image_input"))
    if images:
        cost += images * ((per_image or 0) + (per_image_cents or 0) / 100.0)
    return cost


def min_margin() -> float:
    try:
        from adminapi.runtime import get_runtime

        value = float(get_runtime("VIDEO_MIN_MARGIN", getattr(settings, "VIDEO_MIN_MARGIN", 0.4)))
    except Exception:
        value = float(getattr(settings, "VIDEO_MIN_MARGIN", 0.4))
    return min(0.9, max(0.0, value))


def cheapest_credit_usd() -> float | None:
    """Самый дешёвый кредит среди продаваемых пакетов, в долларах (кэш 10 мин)."""
    cached = cache.get("video_cost:credit_usd")
    if cached:
        return float(cached)
    try:
        from payments.crypto.rates import kgs_to_usd_rate
        from plans.models import TokenPackage

        rate = Decimal(str(kgs_to_usd_rate()))
        best = None
        for p in TokenPackage.objects.filter(is_active=True):
            credits = int(p.tokens or 0) + int(p.bonus_tokens or 0)
            if credits <= 0 or not p.price:
                continue
            if (p.currency or "KGS").upper() != "KGS":
                continue
            usd = float(Decimal(str(p.price)) * rate / credits)
            best = usd if best is None else min(best, usd)
    except Exception:
        logger.exception("video cost: цена кредита не посчиталась")
        return None
    if best:
        cache.set("video_cost:credit_usd", best, 600)
    return best


def reference_resolution(spec: dict | None) -> str:
    """Качество, в котором задан тариф модели: 720p, если модель его умеет."""
    default = str(getattr(settings, "VIDEO_GEN_RESOLUTION", "720p") or "720p")
    supported = [str(r) for r in ((spec or {}).get("supported_resolutions") or []) if r]
    if not supported:
        return default
    low = {r.lower(): r for r in supported}
    return low.get(default.lower()) or supported[0]


def resolution_ratio(spec: dict | None, resolution: str) -> float:
    """Во сколько раз секунда в этом качестве дешевле/дороже, чем в опорном."""
    ref = reference_resolution(spec)
    here = provider_cost_usd(spec or {}, resolution, 1)
    there = provider_cost_usd(spec or {}, ref, 1)
    if not here or not there:
        return 1.0
    return here / there


def video_credits(model_obj, spec: dict | None, resolution: str, duration: int, *, images: int = 0) -> int:
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
    base = max(1, math.ceil(seconds * coeff * min(1.0, resolution_ratio(spec, resolution))))
    cost = provider_cost_usd(spec or {}, resolution, seconds, images=images)
    credit_usd = cheapest_credit_usd()
    if not cost or not credit_usd:
        return base
    floor = math.ceil(cost / (1.0 - min_margin()) / credit_usd)
    if floor > base:
        logger.info("video price: %s %s %sс — тариф %s, по себестоимости %s ($%.3f)",
                    getattr(model_obj, "openrouter_id", "?"), resolution, seconds, base, floor, cost)
    return max(base, floor)


def price_table(model_obj, spec: dict | None, resolutions: list[str], durations: list[int]) -> dict:
    """Цены для витрины: {разрешение: {секунды: кредиты}} — фронт и бот не считают сами."""
    table: dict[str, dict[str, int]] = {}
    for res in resolutions or [str(getattr(settings, "VIDEO_GEN_RESOLUTION", "720p") or "720p")]:
        table[str(res)] = {str(d): video_credits(model_obj, spec, str(res), int(d)) for d in (durations or [])}
    return table
