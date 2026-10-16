"""Цена по себестоимости OpenRouter с наценкой (BUILD_A, PLAN §2).

Два режима, переключатель — runtime-настройка pricing_mode:
- legacy (по умолчанию) — всё как было: тариф модели, нижняя граница видео
  «себестоимость / 0,6» (ai/video_cost.py), плоская цена картинки. Каждое
  число совпадает со снимком ai/tests_data/pricing_golden_legacy.json;
- markup — цена = max(1, ⌈cost × (1 + pct/100) / credit_usd⌉,
  ⌈cost × (1 + floor/100) / credit_usd⌉). pct — наценка модели
  (GPTModels.markup_pct) или общая (price_markup_pct), floor — общий порог
  (price_floor_pct): ниже него не опускает никакая наценка модели.

credit_usd — самый дешёвый кредит из продаваемых (как video_cost.cheapest_credit_usd),
но сомы переводятся по закреплённому курсу price_kgs_per_usd, если он задан:
живой курс двигал цены на ±1 кредит каждый час.

Арифметика — Decimal и одно деление на шаг: ровно 122 кредита не должны
превратиться в 123 из-за 122,00000000001 во float.
"""
from __future__ import annotations

import logging
import math
import os
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, replace
from decimal import ROUND_CEILING, ROUND_FLOOR, ROUND_HALF_EVEN, Decimal, InvalidOperation

from django.core.cache import cache

logger = logging.getLogger(__name__)

MODE_LEGACY = "legacy"
MODE_MARKUP = "markup"
MODES = (MODE_LEGACY, MODE_MARKUP)

KEY_MODE = "pricing_mode"
KEY_MARKUP_PCT = "price_markup_pct"
KEY_FLOOR_PCT = "price_floor_pct"
KEY_KGS_PER_USD = "price_kgs_per_usd"
RUNTIME_KEYS = (KEY_MODE, KEY_MARKUP_PCT, KEY_FLOOR_PCT, KEY_KGS_PER_USD)

DEFAULT_MODE = MODE_LEGACY
DEFAULT_MARKUP_PCT = Decimal("40")
DEFAULT_FLOOR_PCT = Decimal("25")
PCT_MIN = Decimal("0")
PCT_MAX = Decimal("1000")
RATE_MIN = Decimal("1")
RATE_MAX = Decimal("100000")
# Живой курс слабее закреплённого больше чем на 2 % — кредит в долларах дешевле,
# чем считают цены: пора перезакрепить.
RATE_WARN_SHARE = Decimal("0.02")

UNAVAILABLE_MESSAGE = "Цена модели сейчас недоступна, попробуйте позже"
UNAVAILABLE_CODE = "price_unavailable"

# Текст: доли входа и выхода в типичном сообщении (PLAN §2.4) и делитель тарифа.
TEXT_INPUT_SHARE = Decimal("0.31")
TEXT_OUTPUT_SHARE = Decimal("0.69")
TOKENS_PER_COEFF = Decimal("1000")
TEXT_COEFF_MIN = Decimal("0.001")
TEXT_COEFF_MAX = Decimal("999.999")  # GPTModels.markup_coefficient: max_digits=6, decimal_places=3

CREDIT_CACHE_S = 600
CREDIT_NONE_CACHE_S = 60
VERSION_KEY = "pricing:ver"
# Кэши цен вне этого модуля: invalidate_price_caches удаляет их явно.
VSTUDIO_MODELS_KEYS = ("vstudio:models:v1:guest", "vstudio:models:v1:free", "vstudio:models:v1:paid")
LEGACY_CREDIT_KEY = "video_cost:credit_usd"
PACKAGES_KEY = "credit_value:active_packages_by_price"
_extra_keys: set[str] = set()

# Себестоимость в долларах округляется до наноцента: остаток float (0.7623000000000001)
# иначе мог бы перескочить через целое число кредитов.
_COST_QUANT = Decimal("0.000000001")
_HUNDRED = Decimal("100")

OR_MODELS_URL_DEFAULT = "https://openrouter.ai/api/v1"
TEXT_CATALOG_KEY = "or_text_models"
TEXT_CATALOG_TTL = 3600
TEXT_CATALOG_LAST_GOOD_TTL = 7 * 24 * 3600


class PriceUnavailable(Exception):
    """Цену посчитать нельзя (режим markup): себестоимость неизвестна или нет ни
    одного пакета с ценой. Запуск отклоняется, к тарифу не откатываемся."""

    error_code = UNAVAILABLE_CODE

    def __init__(self, model_id: str = "", reason: str = ""):
        self.model_id = str(model_id or "")
        self.reason = str(reason or "")
        super().__init__(UNAVAILABLE_MESSAGE)

    @property
    def message(self) -> str:
        return UNAVAILABLE_MESSAGE

    def payload(self) -> dict:
        """Тело ответа в форме остальных отказов: {error, error_code}."""
        return {"error": UNAVAILABLE_MESSAGE, "error_code": UNAVAILABLE_CODE}


# ---------------------------------------------------------------- настройки

@dataclass(frozen=True)
class PricingConfig:
    """Настройки цены на один расчёт. kgs_per_usd=None — живой курс."""

    mode: str = DEFAULT_MODE
    markup_pct: Decimal = DEFAULT_MARKUP_PCT
    floor_pct: Decimal = DEFAULT_FLOOR_PCT
    kgs_per_usd: Decimal | None = None

    @property
    def markup(self) -> bool:
        return self.mode == MODE_MARKUP

    def with_changes(self, **changes) -> "PricingConfig":
        return replace(self, **changes)


_override: ContextVar[PricingConfig | None] = ContextVar("pricing_override", default=None)


def _dec(value) -> Decimal | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, Decimal):
        out = value
    else:
        text = str(value).strip().replace(",", ".")
        if not text:
            return None
        try:
            out = Decimal(text)
        except (InvalidOperation, ValueError):
            return None
    return out if out.is_finite() else None


def plain(value: Decimal | None) -> str | None:
    """Decimal строкой без экспоненты и лишних нулей: 100, а не 1E+2."""
    if value is None:
        return None
    return format(value.normalize(), "f")


def parse_mode(raw) -> str:
    value = str(raw or "").strip().lower()
    if value not in MODES:
        raise ValueError("Режим цен: legacy или markup.")
    return value


def parse_pct(raw, *, what: str = "Наценка") -> Decimal:
    value = _dec(raw)
    if value is None:
        raise ValueError(f"{what}: нужно число от 0 до 1000.")
    if value < PCT_MIN or value > PCT_MAX:
        raise ValueError(f"{what}: от 0 до 1000 %.")
    return value.quantize(Decimal("0.01"))


def parse_rate(raw) -> Decimal | None:
    """Курс сом/$: пусто — живой курс (None), иначе число от 1 до 100000."""
    if raw is None or not str(raw).strip():
        return None
    value = _dec(raw)
    if value is None or value < RATE_MIN or value > RATE_MAX:
        raise ValueError("Курс: сколько сомов за доллар, например 87.5. Пусто — живой курс.")
    return Decimal(plain(value.quantize(Decimal("0.0001"))))


def validate_setting(key: str, raw) -> str:
    """Проверить значение настройки цен и вернуть строку для AppSetting.

    Пустая строка у price_kgs_per_usd значит «живой курс»: такую настройку
    удаляют (adminapi.runtime.delete_runtime), а не сохраняют.
    """
    if key == KEY_MODE:
        return parse_mode(raw)
    if key == KEY_MARKUP_PCT:
        return str(parse_pct(raw, what="Наценка"))
    if key == KEY_FLOOR_PCT:
        return str(parse_pct(raw, what="Нижний порог"))
    if key == KEY_KGS_PER_USD:
        rate = parse_rate(raw)
        return "" if rate is None else plain(rate)
    raise ValueError(f"Неизвестная настройка цен: {key}")


def _runtime_raw(key: str) -> str:
    try:
        from adminapi.runtime import get_runtime

        return str(get_runtime(key, "") or "")
    except Exception:
        return ""


def _read(key: str, parser, default):
    raw = _runtime_raw(key)
    if not raw.strip():
        return default
    try:
        value = parser(raw)
    except ValueError:
        logger.warning("pricing: настройка %s=%r не разобрана — берём %s", key, raw, default)
        return default
    return default if value is None else value


def stored_config() -> PricingConfig:
    """Настройки из админки (runtime, кэш 30 с) без учёта override_config."""
    return PricingConfig(
        mode=_read(KEY_MODE, parse_mode, DEFAULT_MODE),
        markup_pct=_read(KEY_MARKUP_PCT, parse_pct, DEFAULT_MARKUP_PCT),
        floor_pct=_read(KEY_FLOOR_PCT, lambda r: parse_pct(r, what="Нижний порог"), DEFAULT_FLOOR_PCT),
        kgs_per_usd=_read(KEY_KGS_PER_USD, parse_rate, None),
    )


def current_config() -> PricingConfig:
    """Действующие настройки: временные из override_config, иначе из админки."""
    return _override.get() or stored_config()


@contextmanager
def override_config(cfg: PricingConfig | None = None, **changes):
    """Посчитать цены с несохранёнными настройками (превью в админке, price_preview).

        with override_config(mode="markup", markup_pct=Decimal("30")):
            scene_credits(...)   # любая функция цены внутри видит эти настройки
    """
    base = cfg or current_config()
    value = base.with_changes(**changes) if changes else base
    token = _override.set(value)
    try:
        yield value
    finally:
        _override.reset(token)


def pricing_mode(cfg: PricingConfig | None = None) -> str:
    return (cfg or current_config()).mode


def is_markup(cfg: PricingConfig | None = None) -> bool:
    return (cfg or current_config()).markup


# ---------------------------------------------------------------- кэш

def _version() -> int:
    try:
        value = cache.get(VERSION_KEY)
        if value is None:
            cache.set(VERSION_KEY, 1, None)
            return 1
        return int(value)
    except Exception:
        return 0


def cache_key(name: str) -> str:
    """Ключ кэша, который сбрасывает любое сохранение цен (invalidate_price_caches).

    Всё, что кэширует цены, строит ключ отсюда — тогда правка наценки, курса,
    пакета или модели видна сразу, а не через 10 минут.
    """
    return f"pricing:v{_version()}:{name}"


def register_price_cache_key(key: str) -> None:
    """Постоянный (неверсионный) ключ чужого кэша цен — сбрасывать вместе с ценами."""
    _extra_keys.add(str(key))


def invalidate_price_caches() -> None:
    """Сбросить всё, что помнит цены: после сохранения настроек цен, модели или пакета.

    Сам каталог OpenRouter (себестоимость) не трогаем — он меняется у провайдера.
    """
    try:
        try:
            cache.incr(VERSION_KEY)
        except ValueError:
            cache.set(VERSION_KEY, 2, None)
        keys = [LEGACY_CREDIT_KEY, PACKAGES_KEY, *VSTUDIO_MODELS_KEYS, *sorted(_extra_keys)]
        try:
            from adminapi.runtime import CACHE_PREFIX

            keys += [CACHE_PREFIX + key for key in RUNTIME_KEYS]
        except Exception:
            pass
        cache.delete_many(keys)
    except Exception:
        logger.exception("pricing: кэш цен не сбросился")


# ---------------------------------------------------------------- кредит

@dataclass(frozen=True)
class CreditBasis:
    """Самый дешёвый кредит: usd = numer / denom (делим один раз, в самом конце)."""

    numer: Decimal
    denom: Decimal
    package_name: str
    currency: str            # KGS | USD | STARS
    price: Decimal           # цена пакета в его валюте (сомы, доллары, звёзды)
    credits: int             # кредиты + бонус (+ бонус за Stars)
    kgs_per_usd: Decimal | None
    rate_source: str         # pinned | live | ""

    @property
    def usd(self) -> Decimal:
        return self.numer / self.denom

    @property
    def kgs_per_credit(self) -> Decimal | None:
        if self.currency != "KGS" or not self.credits:
            return None
        return self.price / Decimal(self.credits)

    def to_dict(self) -> dict:
        kgs = self.kgs_per_credit
        return {
            "package": self.package_name,
            "currency": self.currency,
            "price": str(self.price),
            "credits": self.credits,
            "kgs_per_credit": None if kgs is None else str(kgs.quantize(Decimal("0.00001"))),
            "credit_usd": str(self.usd.quantize(Decimal("0.0000001"))),
            "kgs_per_usd": plain(self.kgs_per_usd),
            "rate_source": self.rate_source,
        }


def live_kgs_per_usd() -> Decimal | None:
    """Живой курс: сколько сомов за доллар (payments.crypto.rates — как сегодня)."""
    try:
        from payments.crypto.rates import kgs_to_usd_rate

        usd_per_kgs = Decimal(str(kgs_to_usd_rate()))
    except Exception:
        logger.exception("pricing: живой курс сома не прочитался")
        return None
    if usd_per_kgs <= 0:
        return None
    return (Decimal(1) / usd_per_kgs).quantize(Decimal("0.0001"))


def rate_warning(cfg: PricingConfig | None = None) -> bool:
    """Живой курс слабее закреплённого больше чем на 2 %: цены занижены."""
    cfg = cfg or current_config()
    return _rate_warns(cfg.kgs_per_usd, live_kgs_per_usd() if cfg.kgs_per_usd is not None else None)


def _rate_warns(pinned: Decimal | None, live: Decimal | None) -> bool:
    return bool(pinned is not None and live and live > pinned * (1 + RATE_WARN_SHARE))


def _compute_basis(cfg: PricingConfig) -> CreditBasis | None:
    from plans.models import TokenPackage

    pinned = cfg.kgs_per_usd
    usd_per_kgs = None
    if pinned is None:
        from payments.crypto.rates import kgs_to_usd_rate

        usd_per_kgs = Decimal(str(kgs_to_usd_rate()))
    try:
        from plans.stars import withdraw_rate as stars_rate

        star_usd = Decimal(str(stars_rate()))
    except Exception:
        star_usd = Decimal("0")

    best: CreditBasis | None = None
    for p in TokenPackage.objects.filter(is_active=True).order_by("sort_order", "id"):
        credits = int(p.tokens or 0) + int(p.bonus_tokens or 0)
        if credits <= 0:
            continue
        options = []
        currency = (p.currency or "KGS").upper()
        price = Decimal(str(p.price)) if p.price else Decimal("0")
        if price and currency == "KGS":
            if pinned is not None:
                options.append(CreditBasis(price, Decimal(credits) * pinned, p.name, "KGS", price, credits,
                                           pinned, "pinned"))
            elif usd_per_kgs and usd_per_kgs > 0:
                options.append(CreditBasis(price * usd_per_kgs, Decimal(credits), p.name, "KGS", price, credits,
                                           (Decimal(1) / usd_per_kgs).quantize(Decimal("0.0001")), "live"))
        elif price and currency == "USD":
            options.append(CreditBasis(price, Decimal(credits), p.name, "USD", price, credits, None, ""))
        stars = int(getattr(p, "stars_price", 0) or 0)
        if stars and star_usd > 0:
            with_bonus = credits + int(getattr(p, "stars_bonus_tokens", 0) or 0)
            options.append(CreditBasis(Decimal(stars) * star_usd, Decimal(with_bonus), p.name, "STARS",
                                       Decimal(stars), with_bonus, None, ""))
        for option in options:
            if option.numer > 0 and (best is None or option.usd < best.usd):
                best = option
    return best


def credit_basis(cfg: PricingConfig | None = None) -> CreditBasis | None:
    """Самый дешёвый кредит из продаваемых (кэш 10 мин). None — ни одного пакета с ценой."""
    cfg = cfg or current_config()
    key = cache_key(f"credit_basis:{plain(cfg.kgs_per_usd) or 'live'}")
    try:
        cached = cache.get(key)
    except Exception:
        cached = None
    if cached is not None:
        return cached if isinstance(cached, CreditBasis) else None
    try:
        best = _compute_basis(cfg)
    except Exception:
        logger.exception("pricing: цена кредита не посчиталась")
        best = None
    try:
        if best is not None:
            cache.set(key, best, CREDIT_CACHE_S)
        else:
            logger.error("pricing: нет ни одного пакета с ценой — цену по себестоимости не посчитать")
            cache.set(key, "none", CREDIT_NONE_CACHE_S)
    except Exception:
        pass
    return best


def credit_usd(cfg: PricingConfig | None = None) -> Decimal | None:
    """Доллары за один кредит (самый дешёвый пакет). None — пакетов с ценой нет."""
    basis = credit_basis(cfg)
    return basis.usd if basis is not None else None


# ---------------------------------------------------------------- формула

def model_markup_pct(model) -> Decimal | None:
    """Своя наценка модели; None — общая из настроек."""
    value = _dec(getattr(model, "markup_pct", None)) if model is not None else None
    if value is None:
        return None
    return min(PCT_MAX, max(PCT_MIN, value))


def markup_for(model, cfg: PricingConfig | None = None) -> Decimal:
    """Наценка модели в процентах: своя или общая (до сравнения с порогом)."""
    cfg = cfg or current_config()
    own = model_markup_pct(model)
    return own if own is not None else cfg.markup_pct


def effective_markup_pct(model, cfg: PricingConfig | None = None) -> Decimal:
    """Наценка, с которой реально считается цена: не ниже порога (порог побеждает)."""
    cfg = cfg or current_config()
    return max(markup_for(model, cfg), cfg.floor_pct)


def floor_binds(model, cfg: PricingConfig | None = None) -> bool:
    """Наценка модели ниже порога — цену держит порог (флаг для превью)."""
    cfg = cfg or current_config()
    return markup_for(model, cfg) < cfg.floor_pct


def _ceil(value: Decimal) -> int:
    return int(value.to_integral_value(rounding=ROUND_CEILING))


def to_cost(cost_usd) -> Decimal | None:
    """Себестоимость в долларах как Decimal (до наноцента); None — неизвестна."""
    value = _dec(cost_usd)
    if value is None or value < 0:
        return None
    return value.quantize(_COST_QUANT, rounding=ROUND_HALF_EVEN)


def credits_for_cost(cost_usd, model=None, *, cfg: PricingConfig | None = None,
                     basis: CreditBasis | None = None) -> int:
    """Кредиты за генерацию с себестоимостью cost_usd (режим markup, PLAN §2.1).

    max(1, ⌈cost·(1+pct/100)/credit⌉, ⌈cost·(1+floor/100)/credit⌉) — то же, что
    одна формула с max(pct, floor). PriceUnavailable — себестоимость неизвестна
    или нет ни одного пакета с ценой.
    """
    cfg = cfg or current_config()
    model_id = str(getattr(model, "openrouter_id", "") or "")
    cost = to_cost(cost_usd)
    if cost is None:
        raise PriceUnavailable(model_id, "cost_unknown")
    basis = basis or credit_basis(cfg)
    if basis is None:
        raise PriceUnavailable(model_id, "no_priced_package")
    pct = effective_markup_pct(model, cfg)
    credits = _ceil(cost * (_HUNDRED + pct) * basis.denom / (_HUNDRED * basis.numer))
    return max(1, credits)


# ---------------------------------------------------------------- картинки

def legacy_image_credits(model) -> int:
    """Плоская цена картинки legacy: max(1, int(markup_coefficient)), 0 читается как 1."""
    try:
        coeff = float(getattr(model, "markup_coefficient", 1) or 1)
    except Exception:
        coeff = 1.0
    return max(1, int(coeff))


@dataclass(frozen=True)
class ImagePrice:
    credits: int
    source: str              # legacy | markup | no_cost (markup, но себестоимости нет)
    cost_usd: Decimal | None


def image_price(model, refs: int = 0, *, cfg: PricingConfig | None = None) -> ImagePrice:
    """Цена одной картинки и откуда она взялась (для превью и флагов админки)."""
    cfg = cfg or current_config()
    if not cfg.markup:
        return ImagePrice(legacy_image_credits(model), "legacy", None)
    unit = to_cost(getattr(model, "unit_cost_usd", None))
    if unit is None:
        # Себестоимость не заведена: прежняя цена, админка показывает «нет себестоимости».
        return ImagePrice(legacy_image_credits(model), "no_cost", None)
    per_ref = to_cost(getattr(model, "ref_cost_usd", None)) or Decimal("0")
    cost = unit + max(0, int(refs or 0)) * per_ref
    try:
        return ImagePrice(credits_for_cost(cost, model, cfg=cfg), "markup", cost)
    except PriceUnavailable:
        # Пакетов с ценой нет — картинку не отклоняем, считаем как раньше.
        logger.error("pricing: картинка %s — нет пакета с ценой, берём прежнюю цену",
                     getattr(model, "openrouter_id", "?"))
        return ImagePrice(legacy_image_credits(model), "no_cost", cost)


def image_credits(model, refs: int = 0, *, cfg: PricingConfig | None = None) -> int:
    """Кредиты за одну картинку (+ refs входных фото у моделей, которые за них берут).

    legacy — плоская цена; markup — credits_for_cost(unit_cost_usd + refs × ref_cost_usd),
    а без unit_cost_usd — прежняя цена (решение 4).
    """
    return image_price(model, refs, cfg=cfg).credits


# ---------------------------------------------------------------- текст

def derived_text_coeff(prompt_usd_per_token, completion_usd_per_token, model=None, *,
                       cfg: PricingConfig | None = None, basis: CreditBasis | None = None) -> Decimal:
    """Тариф текста (кредитов за 1000 токенов) из цен OpenRouter за токен.

    (0,31·вход + 0,69·выход) × 1000 × (1 + наценка/100) / credit_usd, вверх до
    0,001 (меньше — значило бы «бесплатно»). Наценка — как у видео: своя модели
    или общая, не ниже порога. ValueError — цены нет или тариф не помещается в поле.
    """
    cfg = cfg or current_config()
    p_in, p_out = _dec(prompt_usd_per_token), _dec(completion_usd_per_token)
    if p_in is None or p_out is None or p_in < 0 or p_out < 0:
        raise ValueError("нет цены модели за токен")
    basis = basis or credit_basis(cfg)
    if basis is None:
        raise ValueError("нет ни одного пакета с ценой")
    pct = effective_markup_pct(model, cfg)
    blended = TEXT_INPUT_SHARE * p_in + TEXT_OUTPUT_SHARE * p_out
    raw = blended * TOKENS_PER_COEFF * (_HUNDRED + pct) * basis.denom / (_HUNDRED * basis.numer)
    coeff = max(TEXT_COEFF_MIN, raw.quantize(Decimal("0.001"), rounding=ROUND_CEILING))
    if coeff > TEXT_COEFF_MAX:
        raise ValueError("тариф больше 999.999 кр/1000 токенов")
    return coeff


def text_message_credits(coeff, tokens: int = 2000) -> int:
    """Списание за сообщение в tokens токенов: max(1, ⌈tokens × тариф / 1000⌉) — как в чате."""
    value = _dec(coeff) or Decimal("0")
    return max(1, _ceil(Decimal(int(tokens)) * value / TOKENS_PER_COEFF))


# ---------------------------------------------------------------- картинки в чате

@dataclass(frozen=True)
class ChatImagePrice:
    """Что спишет чат за одну картинку — для админки (само списание в ai/handlers.py).

    billing: image — FLUX, цена за картинку (как flux_charge_credits без числа фото);
    tokens — остальные модели картинок (Nano Banana): токены × тариф модели в обоих
    режимах; credits тогда — оценка на tokens токенов. Наценка доходит до этой цены
    только через тариф: его выставляет кнопка «Пересчитать тариф картинок в чате»
    (chat_image_tariff).
    """

    billing: str
    credits: int
    refs: int
    tokens: int | None


def chat_image_tokens() -> int:
    """Токенов на одну картинку Nano Banana в чате — та же оценка, что у калькулятора
    пакетов (CREDIT_CALC_IMAGE_PROMPT/OUTPUT_TOKENS_ESTIMATE, 150 + 1300)."""
    from django.conf import settings

    try:
        prompt = int(getattr(settings, "CREDIT_CALC_IMAGE_PROMPT_TOKENS_ESTIMATE", 150) or 150)
        output = int(getattr(settings, "CREDIT_CALC_IMAGE_OUTPUT_TOKENS_ESTIMATE", 1300) or 1300)
    except (TypeError, ValueError):
        prompt, output = 150, 1300
    return max(1, prompt + output)


def chat_image_price(model, *, cfg: PricingConfig | None = None) -> ChatImagePrice:
    """Цена одной картинки модели в чате при настройках cfg."""
    from .model_billing import UNKNOWN_REFS, is_flux_image_model

    cfg = cfg or current_config()
    if is_flux_image_model(getattr(model, "openrouter_id", "")):
        return ChatImagePrice("image", image_credits(model, UNKNOWN_REFS, cfg=cfg), UNKNOWN_REFS, None)
    tokens = chat_image_tokens()
    return ChatImagePrice("tokens", text_message_credits(getattr(model, "markup_coefficient", 0), tokens),
                          0, tokens)


def chat_token_charge(tokens: int, coeff) -> int:
    """Списание чата за tokens токенов при тарифе coeff — во float, как
    ai.handlers._compute_charge: max(1, ⌈tokens × тариф / 1000⌉)."""
    value = _dec(coeff) or Decimal("0")
    return max(1, math.ceil(int(tokens) * float(value) / float(TOKENS_PER_COEFF)))


@dataclass(frozen=True)
class ChatImageTariff:
    """Тариф картинки в чате, при котором чат берёт за неё столько же, сколько студии."""

    credits: int             # цена картинки по наценке (image_credits, без входных фото)
    coefficient: Decimal     # тариф: кредитов за 1000 токенов
    tokens: int              # на сколько токенов картинки рассчитан тариф
    cost_usd: Decimal        # себестоимость картинки


def chat_image_tariff(model, *, cfg: PricingConfig | None = None, basis: CreditBasis | None = None,
                      tokens: int | None = None) -> ChatImageTariff:
    """Тариф Nano Banana и др. для чата по цене картинки с наценкой.

    Чат списывает такую картинку токенами × тариф (ai/handlers.py), а не за
    картинку. Тариф = цена по наценке × 1000 ÷ токены картинки (chat_image_tokens),
    ВНИЗ до 0,001: картинка в 1450 токенов тогда стоит ровно цену по наценке
    (7 кр → 4,827 → ⌈6,999⌉ = 7), а вверх (4,828) дала бы 8. Картинка в другое
    число токенов стоит пропорционально больше или меньше: это оценка, как у
    калькулятора пакетов. ValueError — нет себестоимости, нет пакета с ценой или
    тариф не помещается в поле.
    """
    cfg = (cfg or current_config()).with_changes(mode=MODE_MARKUP)
    unit = to_cost(getattr(model, "unit_cost_usd", None))
    if unit is None:
        raise ValueError("нет себестоимости картинки")
    try:
        credits = credits_for_cost(unit, model, cfg=cfg, basis=basis)
    except PriceUnavailable as exc:
        raise ValueError("нет ни одного пакета с ценой") from exc
    tokens = max(1, int(tokens or chat_image_tokens()))
    return ChatImageTariff(credits, tariff_for_credits(credits, tokens), tokens, unit)


def tariff_for_credits(credits: int, tokens: int) -> Decimal:
    """Тариф (кр за 1000 токенов), при котором tokens токенов в чате стоят ровно credits:
    credits × 1000 ÷ tokens вниз до 0,001. ValueError — больше 999.999 (поле не вместит)."""
    tokens = max(1, int(tokens))
    raw = Decimal(int(credits)) * TOKENS_PER_COEFF / Decimal(tokens)
    coeff = raw.quantize(TEXT_COEFF_MIN, rounding=ROUND_FLOOR)
    if coeff > TEXT_COEFF_MAX:
        raise ValueError("тариф больше 999.999 кр/1000 токенов")
    # Чат считает во float: если там вышло на кредит больше — шаг вниз.
    while coeff > TEXT_COEFF_MIN and chat_token_charge(tokens, coeff) > credits:
        coeff -= TEXT_COEFF_MIN
    return max(TEXT_COEFF_MIN, coeff)


@dataclass(frozen=True)
class TextPrice:
    prompt: Decimal          # $ за токен входа
    completion: Decimal      # $ за токен выхода

    def per_million(self) -> tuple[Decimal, Decimal]:
        million = Decimal(1_000_000)
        return self.prompt * million, self.completion * million


def _models_url() -> str:
    base = (os.environ.get("OPENROUTER_API_BASE") or OR_MODELS_URL_DEFAULT).strip().rstrip("/")
    return f"{base}/models"


def openrouter_models_catalog() -> list:
    """Каталог моделей OpenRouter /api/v1/models (публичный, без ключа).

    Кэш 1 ч и последняя удачная копия на неделю; сбой помним минуту, чтобы не
    долбить API. Нужен только админке (пересчёт тарифов текста, «Добавить модель»):
    списание его не читает. В тестах — только мок.
    """
    catalog = cache.get(TEXT_CATALOG_KEY)
    if catalog:
        return catalog
    if cache.get(TEXT_CATALOG_KEY + ":failed"):
        return cache.get(TEXT_CATALOG_KEY + ":last_good") or []
    data = None
    try:
        import requests

        r = requests.get(_models_url(), timeout=(10, 20))
        data = (r.json() or {}).get("data") if r.ok else None
    except Exception as exc:  # noqa: BLE001
        logger.warning("pricing: каталог моделей OpenRouter не ответил: %s", exc)
    if isinstance(data, list) and data:
        cache.set(TEXT_CATALOG_KEY, data, TEXT_CATALOG_TTL)
        cache.set(TEXT_CATALOG_KEY + ":last_good", data, TEXT_CATALOG_LAST_GOOD_TTL)
        return data
    cache.set(TEXT_CATALOG_KEY + ":failed", 1, 60)
    return cache.get(TEXT_CATALOG_KEY + ":last_good") or []


def text_model_prices(model_id: str, catalog: list | None = None) -> TextPrice | None:
    """Цены модели за токен из каталога; суффиксы «:free»/«:online» — та же модель."""
    wanted = str(model_id or "").strip()
    if not wanted:
        return None
    rows = openrouter_models_catalog() if catalog is None else catalog
    by_id = {str(m.get("id") or ""): m for m in rows if isinstance(m, dict)}
    row = by_id.get(wanted) or by_id.get(wanted.split(":", 1)[0])
    pricing = (row or {}).get("pricing") or {}
    p_in, p_out = _dec(pricing.get("prompt")), _dec(pricing.get("completion"))
    if p_in is None or p_out is None or p_in < 0 or p_out < 0:
        return None
    return TextPrice(p_in, p_out)


# ---------------------------------------------------------------- для админки

@dataclass(frozen=True)
class Sample:
    """Цена модели на типичной генерации в обоих режимах — для «Моделей» и превью.

    flags: no_cost — себестоимости нет (видео в markup не продаётся, картинка
    остаётся по прежней цене); floor — наценка модели ниже порога, цену держит порог.
    """

    kind: str                # video | image | text
    shape: dict              # {"seconds", "resolution", "aspect"} | {"images", "refs"} | {"tokens"}
    cost_usd: Decimal | None
    legacy: int | None
    markup: int | None
    flags: tuple = ()

    def active(self, cfg: PricingConfig | None = None) -> int | None:
        return self.markup if (cfg or current_config()).markup else self.legacy

    def to_dict(self) -> dict:
        return {"kind": self.kind, "shape": dict(self.shape),
                "cost_usd": None if self.cost_usd is None else str(self.cost_usd.normalize()),
                "legacy": self.legacy, "markup": self.markup, "flags": list(self.flags)}


def model_sample(model, *, cfg: PricingConfig | None = None, spec: dict | None = None, seconds: int = 5,
                 resolution: str = "720p", aspect: str | None = None, refs: int = 0,
                 tokens: int = 2000) -> Sample:
    """Цена одной типичной генерации: видео 5 с 720p (притянутые к тому, что умеет
    модель), одна картинка, текстовое сообщение в 2000 токенов.

    Обе цены — legacy и markup — с настройками cfg (несохранёнными в превью).
    Текст в markup по-прежнему списывается тарифом: он меняется только кнопкой
    «Пересчитать тарифы текста», поэтому обе цены текста равны.
    """
    cfg = cfg or current_config()
    legacy_cfg, markup_cfg = cfg.with_changes(mode=MODE_LEGACY), cfg.with_changes(mode=MODE_MARKUP)
    category = str(getattr(model, "category", "") or "")
    flags = ("floor",) if floor_binds(model, cfg) else ()

    if category == "video":
        from . import video_cost

        model_id = str(getattr(model, "openrouter_id", "") or "")
        if spec is None:
            try:
                from .handlers import _openrouter_config, _openrouter_video_catalog, _video_model_params

                spec = _openrouter_video_catalog(model_id) or {}
                snapped = _video_model_params(model_id, _openrouter_config(), seconds, resolution)
                seconds, resolution = int(snapped["duration"]), str(snapped["resolution"])
            except Exception:
                logger.exception("pricing: каталог видео не прочитался для %s", model_id)
                spec = {}
        aspect = aspect or video_cost.default_aspect(spec)
        shape = {"seconds": int(seconds), "resolution": str(resolution), "aspect": aspect}
        cost = to_cost(video_cost.provider_cost_usd(spec or {}, resolution, seconds, aspect=aspect))
        legacy = video_cost.video_credits(model, spec, resolution, seconds, aspect=aspect, cfg=legacy_cfg)
        try:
            markup = video_cost.video_credits(model, spec, resolution, seconds, aspect=aspect, cfg=markup_cfg)
        except PriceUnavailable:
            markup, flags = None, flags + ("no_cost",)
        return Sample("video", shape, cost, legacy, markup, flags)

    if category == "image":
        info = image_price(model, refs, cfg=markup_cfg)
        if info.source == "no_cost":
            flags += ("no_cost",)
        return Sample("image", {"images": 1, "refs": int(refs)}, info.cost_usd,
                      legacy_image_credits(model), info.credits, flags)

    credits = text_message_credits(getattr(model, "markup_coefficient", 0), tokens)
    return Sample("text", {"tokens": int(tokens)}, None, credits, credits, ())


def settings_snapshot(cfg: PricingConfig | None = None) -> dict:
    """Настройки цен и их следствия для карточки «Цены и наценка» (только чтение)."""
    cfg = cfg or current_config()
    basis = credit_basis(cfg)
    live = live_kgs_per_usd()
    return {
        "mode": cfg.mode,
        "markup_pct": plain(cfg.markup_pct),
        "floor_pct": plain(cfg.floor_pct),
        "kgs_per_usd": plain(cfg.kgs_per_usd),
        "live_kgs_per_usd": plain(live),
        "rate_warning": _rate_warns(cfg.kgs_per_usd, live),
        "basis": basis.to_dict() if basis is not None else None,
    }


__all__ = [
    "MODE_LEGACY", "MODE_MARKUP", "MODES", "plain", "KEY_MODE", "KEY_MARKUP_PCT", "KEY_FLOOR_PCT", "KEY_KGS_PER_USD",
    "RUNTIME_KEYS", "DEFAULT_MARKUP_PCT", "DEFAULT_FLOOR_PCT", "UNAVAILABLE_MESSAGE", "UNAVAILABLE_CODE",
    "PriceUnavailable", "PricingConfig", "CreditBasis", "ImagePrice", "TextPrice",
    "parse_mode", "parse_pct", "parse_rate", "validate_setting", "stored_config", "current_config",
    "override_config", "pricing_mode", "is_markup", "cache_key", "register_price_cache_key",
    "invalidate_price_caches", "live_kgs_per_usd", "rate_warning", "credit_basis", "credit_usd",
    "model_markup_pct", "markup_for", "effective_markup_pct", "floor_binds", "to_cost", "credits_for_cost",
    "legacy_image_credits", "image_price", "image_credits", "derived_text_coeff", "text_message_credits",
    "ChatImagePrice", "chat_image_tokens", "chat_image_price", "chat_token_charge", "ChatImageTariff",
    "chat_image_tariff", "tariff_for_credits",
    "openrouter_models_catalog", "text_model_prices", "Sample", "model_sample", "settings_snapshot",
]
