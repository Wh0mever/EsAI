"""Цены и наценка в панели (BUILD_A, решение 9).

  GET   pricing/                       настройки цен, курс, база кредита, примеры, предупреждения
  PATCH pricing/                       сохранить {mode, markup_pct, floor_pct, kgs_per_usd, pin_live_rate}
  PATCH pricing/?preview=1             проверить и посчитать примеры с присланным, ничего не сохраняя
  POST  pricing/preview/               то же, что PATCH ?preview=1
  GET   models/catalog/?q=&kind=       каталог OpenRouter для «Добавить модель»
  POST  models/                        добавить модель по openrouter_id — выключенной
  GET   models/text-recompute/[?ids=]  пересчёт тарифов текста: было → станет
  POST  models/text-recompute/         применить {confirm: true, items: [{id, coefficient}]}
  GET   models/chat-image-recompute/[?ids=]  тариф картинок Nano Banana в чате по наценке: было → станет
  POST  models/chat-image-recompute/   применить {confirm: true, items: [{id, coefficient}]}

Только staff. Формулы цены живут только в ai.pricing (CONTRACT_A): здесь
разбор запроса, примеры для карточки «Цены и наценка» и колонок «Моделей»,
журнал действий и сброс кэшей цен. Отказы — телом {"detail": "<текст>"},
как у остальной панели; у формы настроек рядом errors {поле: текст}.
Полный контракт для страницы — vstudio2-notes/pricing/CONTRACT_A_admin.md.
"""
from __future__ import annotations

import logging
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from types import SimpleNamespace

from django.db import IntegrityError, transaction
from django.db.models import Max, Q
from rest_framework import status
from rest_framework.response import Response

from ai import pricing
from ai.model_billing import is_flux_image_model
from ai.models import GPTModels
from audit.services import log_admin_action

from .models import AppSetting
from .runtime import delete_runtime, set_runtime
from .views import StaffAPIView

logger = logging.getLogger(__name__)

# Своего кода у цен в журнале нет: список закрытый (audit.models.ADMIN_ACTIONS).
# Как витрина и сцены мультстудии, пишем settings.edit, а что меняли — по ключу.
LOG_ACTION = "settings.edit"
LOG_PRICING = "pricing"
LOG_MODEL = "model"
LOG_MODEL_ADD = "model_add"
LOG_TEXT_TARIFF = "text_tariff"
LOG_CHAT_IMAGE_TARIFF = "chat_image_tariff"
CHAT_IMAGE_BUTTON = "«Пересчитать тариф картинок в чате»"

# Поля формы → runtime-ключи ai.pricing.
SETTING_FIELDS = (
    ("mode", pricing.KEY_MODE),
    ("markup_pct", pricing.KEY_MARKUP_PCT),
    ("floor_pct", pricing.KEY_FLOOR_PCT),
    ("kgs_per_usd", pricing.KEY_KGS_PER_USD),
)
PIN_LIVE = "pin_live_rate"
FIELD_NAMES = tuple(name for name, _key in SETTING_FIELDS) + (PIN_LIVE,)

SEEDANCE = "bytedance/seedance-2.0"
MINI = "bytedance/seedance-2.0-mini"
KLING = "kwaivgi/kling-v3.0-std"
VEO_LITE = "google/veo-3.1-lite"
FLUX_KLEIN = "black-forest-labs/flux.2-klein-4b"
FLUX_FLEX = "black-forest-labs/flux.2-flex"
NANO = "google/gemini-2.5-flash-image"
GPT4O = "openai/gpt-4o"

# Примеры карточки «Цены и наценка» (решение 9): (ключ, вид, openrouter_id, имя
# на случай, если строки модели в базе нет, параметры генерации).
SAMPLES = (
    ("seedance_720_5", "video", SEEDANCE, "Seedance 2.0", {"seconds": 5, "resolution": "720p"}),
    ("mini_480_5", "video", MINI, "Seedance 2.0 Mini", {"seconds": 5, "resolution": "480p"}),
    ("mini_720_5", "video", MINI, "Seedance 2.0 Mini", {"seconds": 5, "resolution": "720p"}),
    ("kling_720_5", "video", KLING, "Kling 3.0", {"seconds": 5, "resolution": "720p"}),
    ("veo_lite_720_4", "video", VEO_LITE, "Veo 3.1 Lite", {"seconds": 4, "resolution": "720p"}),
    ("flux_klein", "image", FLUX_KLEIN, "FLUX Klein", {"refs": 0}),
    ("flux_flex_edit", "image", FLUX_FLEX, "FLUX Flex", {"refs": 1}),
    ("nano_frame", "image", NANO, "Nano Banana", {"refs": 0}),
    ("cartoon_scene", "cartoon", SEEDANCE, "Seedance 2.0",
     {"seconds": 5, "resolution": "720p", "aspect": "16:9"}),
    ("gpt4o_message", "text", GPT4O, "GPT-4o", {"tokens": 2000}),
)

TEXT_TOKENS = 2000
CATALOG_LIMIT = 40
QUERY_MAX = 200
ID_MAX = GPTModels._meta.get_field("openrouter_id").max_length
NAME_MAX = GPTModels._meta.get_field("name").max_length
DESCRIPTION_MAX = 240
RECOMPUTE_MAX_ITEMS = 200
# Как у моделей из сидов (seed_cartoon): лимит ответа, который правят уже в Django-админке.
NEW_MODEL_MAX_TOKENS = 4096
SORT_STEP = 10
KINDS = ("video", "image", "text")
KIND_ORDER = {"video": 0, "image": 1, "text": 2}
CATEGORIES = tuple(key for key, _label in GPTModels.CATEGORY_CHOICES)
NON_TEXT = ("image", "video")
TEXT_STATUSES_OK = ("ok", "unchanged")


def _body(request) -> dict:
    data = getattr(request, "data", None)
    return data if hasattr(data, "get") else {}


def _bad(detail: str, code: int = status.HTTP_400_BAD_REQUEST, **extra) -> Response:
    return Response({"detail": detail, **extra}, status=code)


def invalidate() -> None:
    """Сбросить кэши цен сейчас и ещё раз после фиксации транзакции запроса.

    Запрос идёт в транзакции (ATOMIC_REQUESTS): до фиксации другой воркер ещё
    читает старые значения и может снова положить в кэш старую цену.
    """
    pricing.invalidate_price_caches()
    transaction.on_commit(pricing.invalidate_price_caches)


# ---------------------------------------------------------------- формат чисел

def _ru(value: Decimal) -> str:
    return format(value, "f").replace(".", ",")


def usd_text(value) -> str | None:
    """$ по-русски: от 10 центов — до цента ($0,76), меньше — три значащие цифры ($0,039)."""
    cost = pricing.to_cost(value)
    if cost is None:
        return None
    if cost == 0:
        return "$0"
    if cost >= Decimal("0.1"):
        return "$" + _ru(cost.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))
    step = Decimal(1).scaleb(cost.adjusted() - 2)
    return "$" + _ru(cost.quantize(step, rounding=ROUND_HALF_UP).normalize())


def _str_cost(value) -> str | None:
    cost = pricing.to_cost(value)
    return None if cost is None else pricing.plain(cost)


def shape_text(kind: str, shape: dict) -> str:
    if kind in ("video", "cartoon"):
        return f"{shape.get('seconds')} с {shape.get('resolution')}"
    if kind == "image":
        refs = int(shape.get("refs") or 0)
        return f"картинка + {refs} фото" if refs else "1 картинка"
    return f"{shape.get('tokens') or TEXT_TOKENS} токенов"


def _delta_pct(legacy, markup) -> float | None:
    if not legacy or markup is None:
        return None
    return float((Decimal(markup - legacy) * 100 / Decimal(legacy)).quantize(Decimal("0.1"),
                                                                              rounding=ROUND_HALF_UP))


def _unique(flags) -> list:
    out = []
    for flag in flags:
        if flag not in out:
            out.append(flag)
    return out


def basis_line(basis: dict | None) -> str:
    """«MASTER · 0,768 сом = $0,00878» — что стоит один кредит самого дешёвого пакета."""
    if not basis:
        return "Нет активного пакета с ценой"
    usd = usd_text(Decimal(basis["credit_usd"]))
    if basis.get("currency") == "KGS" and basis.get("kgs_per_credit"):
        kgs = Decimal(basis["kgs_per_credit"]).quantize(Decimal("0.001"), rounding=ROUND_HALF_UP)
        return f"{basis['package']} · {_ru(kgs)} сом = {usd}"
    if basis.get("currency") == "STARS":
        return f"{basis['package']} (Stars) · {usd} за кредит"
    return f"{basis['package']} · {usd} за кредит"


# ---------------------------------------------------------------- настройки цен

def parse_settings(body, *, allow_empty: bool = False) -> tuple[dict, dict]:
    """Присланная форма → ({runtime-ключ: строка; "" — удалить}, {поле: ошибка}).

    Сначала проверяется всё, потом пишется всё: ошибка в одном поле не должна
    оставить уже переключённый режим.
    """
    if not isinstance(body, dict):
        return {}, {"__all__": "Нужен объект с полями: " + ", ".join(FIELD_NAMES)}
    errors: dict = {}
    unknown = sorted(str(key) for key in body if key not in FIELD_NAMES)
    if unknown:
        errors["__all__"] = (f"Неизвестное поле: {', '.join(unknown)}. "
                             f"Можно: {', '.join(FIELD_NAMES)}")
    changes: dict = {}
    for name, key in SETTING_FIELDS:
        if name not in body:
            continue
        try:
            changes[key] = pricing.validate_setting(key, body[name])
        except ValueError as exc:
            errors[name] = str(exc)
    if PIN_LIVE in body:
        flag = body[PIN_LIVE]
        if not isinstance(flag, bool):
            errors[PIN_LIVE] = "«Закрепить текущий курс»: true или false."
        elif flag and "kgs_per_usd" in body:
            errors[PIN_LIVE] = "Либо курс, либо «Закрепить текущий» — не оба сразу."
        elif flag:
            live = pricing.live_kgs_per_usd()
            if live is None:
                errors[PIN_LIVE] = "Живой курс сейчас недоступен — введите курс вручную."
            else:
                try:
                    changes[pricing.KEY_KGS_PER_USD] = pricing.validate_setting(pricing.KEY_KGS_PER_USD, live)
                except ValueError as exc:
                    errors[PIN_LIVE] = str(exc)
    if not errors and not changes and not allow_empty:
        errors["__all__"] = "Нечего менять."
    return changes, errors


def _errors_response(errors: dict) -> Response:
    return _bad(" ".join(dict.fromkeys(errors.values())), errors=errors)


def config_with(base: pricing.PricingConfig, changes: dict) -> pricing.PricingConfig:
    """Настройки с присланными значениями поверх сохранённых (для превью)."""
    values: dict = {}
    if pricing.KEY_MODE in changes:
        values["mode"] = changes[pricing.KEY_MODE]
    if pricing.KEY_MARKUP_PCT in changes:
        values["markup_pct"] = Decimal(changes[pricing.KEY_MARKUP_PCT])
    if pricing.KEY_FLOOR_PCT in changes:
        values["floor_pct"] = Decimal(changes[pricing.KEY_FLOOR_PCT])
    if pricing.KEY_KGS_PER_USD in changes:
        rate = changes[pricing.KEY_KGS_PER_USD]
        values["kgs_per_usd"] = Decimal(rate) if rate else None
    return base.with_changes(**values) if values else base


def save_settings(changes: dict, *, actor, request) -> dict:
    """Записать настройки и журнал одной транзакцией; вернуть {поле: новое значение}."""
    stored = dict(AppSetting.objects.filter(key__in=pricing.RUNTIME_KEYS).values_list("key", "value"))
    before: dict = {}
    after: dict = {}
    with transaction.atomic():
        for name, key in SETTING_FIELDS:
            if key not in changes:
                continue
            new = changes[key] or None
            old = stored.get(key) or None
            if new == old:
                continue
            if new is None:
                # Пустой курс — «живой»: строку удаляем, а не храним пустой.
                delete_runtime(key)
            else:
                set_runtime(key, new)
            before[name], after[name] = old, new
        if after:
            log_admin_action(actor, LOG_ACTION, before={LOG_PRICING: before},
                             after={LOG_PRICING: after}, request=request)
    if after:
        invalidate()
    return after


def _models_by_id(ids) -> dict:
    """openrouter_id → строка модели; «-preview» у провайдера — та же модель."""
    ids = set(ids)
    wanted = ids | {orid + "-preview" for orid in ids}
    rows = {m.openrouter_id: m for m in GPTModels.objects.filter(openrouter_id__in=wanted)}
    return {orid: rows.get(orid) or rows.get(orid + "-preview") for orid in ids}


def _stand_in(orid: str, name: str) -> GPTModels:
    # Строки ещё нет (Mini до «Добавить модель»): цена видео всё равно известна из
    # каталога. Тариф 1 — как у добавленной кнопкой модели.
    return GPTModels(openrouter_id=orid, name=name, category="video", markup_coefficient=Decimal("1"))


def _model_ref(model, *, saved: bool) -> dict:
    return {"id": model.pk if saved else None, "openrouter_id": model.openrouter_id, "name": model.name,
            "is_active": bool(model.is_active) if saved else None}


def _sample_row(key, kind, label, model_ref, shape, cost, legacy, markup, flags, cfg,
                after_recompute=None) -> dict:
    return {
        "key": key, "kind": kind, "label": label, "model": model_ref, "shape": dict(shape),
        "cost_usd": _str_cost(cost), "cost_text": usd_text(cost),
        "legacy": legacy, "markup": markup,
        "active": markup if cfg.markup else legacy,
        "delta_pct": _delta_pct(legacy, markup),
        # Только текст: цена сообщения после «Пересчитать тарифы текста» с этими настройками.
        "after_recompute": after_recompute,
        "flags": _unique(flags),
    }


def _text_preview(model, tokens: int, cfg, state: dict) -> tuple:
    """(себестоимость сообщения, цена после пересчёта тарифа) по каталогу OpenRouter."""
    price = pricing.text_model_prices(model.openrouter_id, _state_catalog(state))
    if price is None:
        return None, None
    cost = (pricing.TEXT_INPUT_SHARE * price.prompt + pricing.TEXT_OUTPUT_SHARE * price.completion) * tokens
    try:
        coeff = pricing.derived_text_coeff(price.prompt, price.completion, model, cfg=cfg)
    except ValueError:
        return cost, None
    return cost, pricing.text_message_credits(coeff, tokens)


def _preview_row(key, kind, orid, name, shape, found, cfg, state: dict) -> dict:
    model = found.get(orid)
    flags: list = []
    saved = model is not None
    if model is None:
        if kind not in ("video", "cartoon"):
            label = f"{name} · {shape_text(kind, shape)}"
            return _sample_row(key, kind, label, {"id": None, "openrouter_id": orid, "name": name,
                                                  "is_active": None},
                               shape, None, None, None, ["not_in_db"], cfg)
        model = _stand_in(orid, name)
        flags.append("not_in_db")
    elif not model.is_active:
        flags.append("inactive")
    ref = _model_ref(model, saved=saved)

    if kind == "video":
        sample = pricing.model_sample(model, cfg=cfg, seconds=shape["seconds"], resolution=shape["resolution"])
        return _sample_row(key, kind, f"{model.name} · {shape_text(kind, sample.shape)}", ref, sample.shape,
                           sample.cost_usd, sample.legacy, sample.markup, flags + list(sample.flags), cfg)
    if kind == "image":
        sample = pricing.model_sample(model, cfg=cfg, refs=shape["refs"])
        what = {"flux_flex_edit": "правка с 1 фото", "nano_frame": "кадр сцены"}.get(key, "1 картинка")
        return _sample_row(key, kind, f"{model.name} · {what}", ref, sample.shape, sample.cost_usd,
                           sample.legacy, sample.markup, flags + list(sample.flags), cfg)
    if kind == "text":
        # Тариф текста режим не меняет (решение 5): «станет» — та же цена, а
        # after_recompute показывает, что даст кнопка пересчёта.
        sample = pricing.model_sample(model, cfg=cfg, tokens=shape["tokens"])
        cost, after = _text_preview(model, shape["tokens"], cfg, state)
        return _sample_row(key, kind, f"{model.name} · сообщение {shape['tokens']} токенов", ref,
                           sample.shape, cost, sample.legacy, sample.markup, flags + list(sample.flags), cfg,
                           after_recompute=after)

    # Сцена мультфильма — той же функцией, что manage.py price_preview: кадр + видео
    # с пропорциями кадра и входными фото, ровно как спишет мультстудия.
    frame = found.get(NANO)
    label = f"Сцена мультфильма · {model.name} · {shape['seconds']} с {shape['resolution']}"
    if frame is None:
        return _sample_row(key, kind, label, ref, shape, None, None, None, flags + ["not_in_db"], cfg)
    from cartoon.pricing import scene_sample

    sample = scene_sample(model, frame, seconds=shape["seconds"], resolution=shape["resolution"],
                          aspect=shape["aspect"], cfg=cfg)
    label = f"Сцена мультфильма · {model.name} · {shape_text(kind, sample.shape)}"
    return _sample_row(key, kind, label, ref, sample.shape, sample.cost_usd, sample.legacy, sample.markup,
                       flags + list(sample.flags), cfg)


def preview_samples(cfg: pricing.PricingConfig) -> list:
    """Цены примеров «было (legacy) → станет (наценка)» с настройками cfg."""
    found = _models_by_id({orid for _key, _kind, orid, _name, _shape in SAMPLES} | {NANO})
    state = {"cfg": cfg}
    rows = []
    for key, kind, orid, name, shape in SAMPLES:
        try:
            rows.append(_preview_row(key, kind, orid, name, shape, found, cfg, state))
        except Exception:
            logger.exception("цены: пример %s не посчитался", key)
            rows.append(_sample_row(key, kind, f"{name} · {shape_text(kind, shape)}",
                                    {"id": None, "openrouter_id": orid, "name": name, "is_active": None},
                                    shape, None, None, None, ["error"], cfg))
    return rows


def models_without_cost() -> list:
    """Включённые модели без себестоимости: видео в режиме «наценка» не продаётся,
    картинка остаётся по прежней плоской цене."""
    out = []
    for model in GPTModels.objects.filter(is_active=True, category__in=NON_TEXT).order_by("sort_order", "id"):
        if model.category == "image":
            if pricing.to_cost(model.unit_cost_usd) is None:
                out.append({"id": model.pk, "name": model.name, "openrouter_id": model.openrouter_id,
                            "category": "image",
                            "reason": "Нет себестоимости картинки: в режиме «наценка» остаётся прежняя цена."})
            continue
        try:
            cost = pricing.model_sample(model).cost_usd
        except Exception:
            logger.exception("цены: себестоимость %s не посчиталась", model.openrouter_id)
            cost = None
        if cost is None:
            out.append({"id": model.pk, "name": model.name, "openrouter_id": model.openrouter_id,
                        "category": "video",
                        "reason": "OpenRouter не сообщает цену этой модели: в режиме «наценка» она не продаётся."})
    return out


def _below_floor(credits, cost, basis, floor_pct) -> bool:
    """Цена в кредитах ниже себестоимости с нижним порогом — продаём себе в убыток."""
    if credits is None or cost is None or basis is None:
        return False
    return Decimal(credits) * basis.usd < cost * (100 + floor_pct) / 100


def _chat_cost(model, refs: int):
    """Себестоимость картинки в чате: картинка и refs входных фото (None — не задана)."""
    unit = pricing.to_cost(model.unit_cost_usd)
    if unit is None:
        return None
    return unit + refs * (pricing.to_cost(model.ref_cost_usd) or Decimal("0"))


def chat_image_target(model, cfg: pricing.PricingConfig, basis=None):
    """Тариф картинки в чате по наценке (pricing.chat_image_tariff); None — не посчитать:
    нет себестоимости, нет пакета с ценой или тариф не помещается в поле."""
    try:
        return pricing.chat_image_tariff(model, cfg=cfg, basis=basis)
    except ValueError:
        return None


def is_chat_token_image(model) -> bool:
    """Картинку модели чат списывает по токенам × тариф (Nano Banana и др., не FLUX)."""
    return model.category == "image" and not is_flux_image_model(model.openrouter_id)


def chat_image_notes(cfg: pricing.PricingConfig) -> dict:
    """Включённые модели картинок, которые чат списывает не так, как студии.

    tokens — Nano Banana и др.: в чате токены × тариф модели в обоих режимах;
    target — цена картинки по наценке, к которой тариф подгоняет кнопка
    «Пересчитать тариф картинок в чате». FLUX здесь нет: чат берёт с него ту же
    цену, что студии, по числу приложенных фото (model_billing.flux_ref_count).
    """
    basis = pricing.credit_basis(cfg)
    out: dict = {"tokens": [], "tokens_per_image": pricing.chat_image_tokens(), "markup": cfg.markup}
    for model in GPTModels.objects.filter(is_active=True, category="image").order_by("sort_order", "id"):
        if is_flux_image_model(model.openrouter_id):
            continue
        chat = pricing.chat_image_price(model, cfg=cfg)
        target = chat_image_target(model, cfg, basis)
        out["tokens"].append({"id": model.pk, "name": model.name, "credits": chat.credits,
                              "target": None if target is None else target.credits,
                              "below_cost": _below_floor(chat.credits, _chat_cost(model, 0), basis,
                                                         cfg.floor_pct)})
    return out


def _chat_warnings(chat: dict) -> list:
    out = []
    rows = chat["tokens"]
    stale = [row for row in rows if row["target"] is not None and row["target"] != row["credits"]]
    below = [row["name"] for row in rows if row["below_cost"]]
    if stale or below:
        # Цена в чате уже равна цене по наценке и не в убыток — говорить не о чем.
        names = ", ".join(row["name"] for row in rows)
        examples = ", ".join(f"{row['name']} ≈{row['credits']} кр" for row in rows)
        text = (f"Картинки в чате у {names} списываются по токенам — тариф модели × ~{chat['tokens_per_image']} "
                f"токенов (сейчас {examples}).")
        if stale:
            targets = ", ".join(f"{row['name']} — {row['target']} кр" for row in stale)
            when = "" if chat["markup"] else " после переключения"
            text += (f" По наценке картинка стоит: {targets}. Наценка сама тариф не меняет: выровняйте его{when} "
                     f"кнопкой {CHAT_IMAGE_BUTTON} в «Моделях».")
        if below:
            text += f" Ниже себестоимости с порогом: {', '.join(below)}."
        out.append({"code": "chat_image_tokens", "text": text})
    return out


def _warnings(cfg, snapshot: dict, without_cost: list, chat: dict | None = None) -> list:
    out = []
    if snapshot.get("rate_warning"):
        out.append({"code": "rate_weaker", "text": (
            f"Живой курс {_ru(Decimal(snapshot['live_kgs_per_usd']))} сом/$ слабее закреплённого "
            f"{_ru(Decimal(snapshot['kgs_per_usd']))} больше чем на 2 %: кредит в долларах дешевле, "
            "чем считают цены. Перезакрепите курс.")})
    if snapshot.get("basis") is None:
        out.append({"code": "no_basis", "text": (
            "Нет ни одного активного пакета с ценой: в режиме «наценка» видео не продаётся.")})
    if cfg.markup_pct < cfg.floor_pct:
        out.append({"code": "floor_above_markup", "text": (
            f"Общая наценка {_ru(cfg.markup_pct.normalize())} % ниже порога "
            f"{_ru(cfg.floor_pct.normalize())} % — действует порог.")})
    if without_cost:
        names = ", ".join(row["name"] for row in without_cost[:8])
        tail = " и другие" if len(without_cost) > 8 else ""
        out.append({"code": "no_cost", "text": (
            f"Моделей без себестоимости: {len(without_cost)} ({names}{tail}). В режиме «наценка» видео "
            "без себестоимости не продаётся, картинки остаются по прежней цене.")})
    if chat:
        out += _chat_warnings(chat)
    return out


def settings_payload(cfg: pricing.PricingConfig, *, preview: bool) -> dict:
    """Карточка «Цены и наценка»: настройки (или присланные в превью), следствия, примеры."""
    from cartoon.pricing import studio_scene_price

    snapshot = pricing.settings_snapshot(cfg)
    without_cost = models_without_cost()
    try:
        scene_price = studio_scene_price()
    except Exception:
        scene_price = None
    try:
        chat = chat_image_notes(cfg)
    except Exception:
        logger.exception("цены: картинки в чате не посчитались")
        chat = None
    return {
        **snapshot,
        "preview": preview,
        "effective_markup_pct": pricing.plain(max(cfg.markup_pct, cfg.floor_pct)),
        "basis_line": basis_line(snapshot.get("basis")),
        "defaults": {"mode": pricing.DEFAULT_MODE, "markup_pct": pricing.plain(pricing.DEFAULT_MARKUP_PCT),
                     "floor_pct": pricing.plain(pricing.DEFAULT_FLOOR_PCT)},
        "limits": {"pct_min": pricing.plain(pricing.PCT_MIN), "pct_max": pricing.plain(pricing.PCT_MAX),
                   "rate_min": pricing.plain(pricing.RATE_MIN), "rate_max": pricing.plain(pricing.RATE_MAX)},
        # Только режим legacy: в режиме «наценка» не читается (правится через settings/).
        "studio_scene_credits": scene_price,
        "samples": preview_samples(cfg),
        "models_without_cost": without_cost,
        "warnings": _warnings(cfg, snapshot, without_cost, chat),
    }


def _is_preview(request) -> bool:
    return str(request.query_params.get("preview") or "").strip().lower() in ("1", "true", "yes")


def _preview_response(request) -> Response:
    changes, errors = parse_settings(request.data, allow_empty=True)
    if errors:
        return _errors_response(errors)
    return Response(settings_payload(config_with(pricing.stored_config(), changes), preview=True))


class PricingView(StaffAPIView):
    """GET — карточка «Цены и наценка»; PATCH — сохранить (с ?preview=1 — только посчитать)."""

    def get(self, request):
        return Response(settings_payload(pricing.stored_config(), preview=False))

    def patch(self, request):
        if _is_preview(request):
            return _preview_response(request)
        changes, errors = parse_settings(request.data)
        if errors:
            return _errors_response(errors)
        changed = save_settings(changes, actor=request.user, request=request)
        return Response({**settings_payload(pricing.stored_config(), preview=False), "changed": changed})


class PricingPreviewView(StaffAPIView):
    """POST — примеры цен с несохранёнными значениями формы (то же, что PATCH ?preview=1)."""

    def post(self, request):
        return _preview_response(request)


# ---------------------------------------------------------------- «Модели»: колонки цены

def _price_state(context: dict) -> dict:
    state = context.get("_price_state")
    if state is None:
        state = context["_price_state"] = {"cfg": pricing.current_config()}
    return state


def _state_catalog(state: dict) -> list:
    if "catalog" not in state:
        state["catalog"] = _text_catalog()
    return state["catalog"]


def _state_basis(state: dict):
    if "basis" not in state:
        state["basis"] = pricing.credit_basis(state["cfg"])
    return state["basis"]


def _text_info(model, state: dict) -> dict:
    cfg = state["cfg"]
    info = {"prompt_per_m": None, "completion_per_m": None, "message_cost_usd": None,
            "derived_coefficient": None, "derived_message_credits": None}
    price = pricing.text_model_prices(model.openrouter_id, _state_catalog(state))
    if price is None:
        return info
    per_in, per_out = price.per_million()
    cost = (pricing.TEXT_INPUT_SHARE * price.prompt + pricing.TEXT_OUTPUT_SHARE * price.completion) * TEXT_TOKENS
    info.update(prompt_per_m=pricing.plain(per_in), completion_per_m=pricing.plain(per_out),
                message_cost_usd=_str_cost(cost))
    basis = _state_basis(state)
    if basis is None:
        return info
    try:
        derived = pricing.derived_text_coeff(price.prompt, price.completion, model, cfg=cfg, basis=basis)
    except ValueError:
        return info
    info.update(derived_coefficient=f"{derived:.3f}",
                derived_message_credits=pricing.text_message_credits(derived, TEXT_TOKENS))
    try:
        # Тариф ниже себестоимости с порогом — продаём себе в убыток.
        at_floor = pricing.derived_text_coeff(price.prompt, price.completion,
                                              SimpleNamespace(markup_pct=cfg.floor_pct), cfg=cfg, basis=basis)
        info["below_cost"] = Decimal(str(model.markup_coefficient or 0)) < at_floor
    except (ValueError, InvalidOperation):
        pass
    return info


def _image_below_cost(model, state: dict, credits: int | None) -> bool:
    return _below_floor(credits, _chat_cost(model, 0), _state_basis(state), state["cfg"].floor_pct)


def _chat_image(model, state: dict) -> dict:
    """Картинка в чате: как списывается, сколько сейчас и в режиме «наценка», в убыток ли сейчас.

    У токенных (Nano Banana) ещё target — цена по наценке и tariff — тариф, который
    поставит кнопка «Пересчитать тариф картинок в чате» (None — не посчитать).
    """
    cfg = state["cfg"]
    chat = pricing.chat_image_price(model, cfg=cfg)
    markup = chat if cfg.markup else pricing.chat_image_price(model, cfg=cfg.with_changes(mode=pricing.MODE_MARKUP))
    below = _below_floor(chat.credits, _chat_cost(model, chat.refs), _state_basis(state), cfg.floor_pct)
    target = chat_image_target(model, cfg, _state_basis(state)) if chat.billing == "tokens" else None
    return {"billing": chat.billing, "credits": chat.credits, "credits_markup": markup.credits,
            "refs": chat.refs, "tokens": chat.tokens, "below_cost": below,
            "target": None if target is None else target.credits,
            "tariff": None if target is None else f"{target.coefficient:.3f}"}


def _chat_note(chat: dict | None, sample_markup, markup_mode: bool) -> str | None:
    """Хвост колонки «Цена»: что спишет чат, если не то же, что студии.

    Nano Banana — по токенам в обоих режимах (и цена по наценке, если тариф её не
    даёт). FLUX с доплатой за фото — для справки цена правки с UNKNOWN_REFS фото:
    строка «1 картинка» считает без фото, а чат берёт за каждое приложенное.
    """
    if not chat:
        return None
    if chat["billing"] == "tokens":
        note = f" · в чате ≈{chat['credits']} кр по токенам"
        if chat["target"] is not None and chat["target"] != chat["credits"]:
            note += f" (по наценке {chat['target']} кр)"
        return note
    if chat["credits_markup"] != sample_markup:
        sep = " · " if markup_mode else ", "
        return f"{sep}в чате {chat['credits_markup']} кр (как правка с {chat['refs']} фото)"
    return None


def _model_info(model, context: dict) -> dict:
    state = _price_state(context)
    cfg = state["cfg"]
    sample = pricing.model_sample(model, cfg=cfg)
    own = pricing.model_markup_pct(model)
    info = {**sample.to_dict(), "mode": cfg.mode, "active": sample.active(cfg),
            "markup_source": "model" if own is not None else "global",
            "effective_markup_pct": pricing.plain(pricing.effective_markup_pct(model, cfg)),
            "text": None, "chat": None}
    flags = list(sample.flags)
    kind = sample.kind
    if kind == "text":
        info["text"] = _text_info(model, state)
        info["cost_usd"] = info["text"]["message_cost_usd"]
        if info["text"].pop("below_cost", False):
            flags.append("below_cost")
    elif kind == "image":
        if _image_below_cost(model, state, info["active"]):
            flags.append("below_cost")
        info["chat"] = _chat_image(model, state)
        if info["chat"].pop("below_cost"):
            flags.append("chat_below_cost")
        chat = info["chat"]
        if cfg.markup and chat["target"] is not None and chat["target"] != chat["credits"]:
            # Наценка не дошла до чата: тариф ждёт кнопки «Пересчитать тариф картинок в чате».
            flags.append("chat_tariff_stale")
    info["flags"] = _unique(flags)

    shape = shape_text(kind, sample.shape)
    if kind == "video":
        cost_sample = (f"{usd_text(sample.cost_usd)} · {shape}" if sample.cost_usd is not None
                       else "нет себестоимости")
    elif kind == "image":
        unit = pricing.to_cost(model.unit_cost_usd)
        ref = pricing.to_cost(model.ref_cost_usd)
        cost_sample = "нет себестоимости" if unit is None else f"{usd_text(unit)} за картинку"
        if unit is not None and ref:
            cost_sample += f" + {usd_text(ref)} за фото"
    else:
        text = info["text"]
        cost_sample = (f"{usd_text(Decimal(text['prompt_per_m']))} / "
                       f"{usd_text(Decimal(text['completion_per_m']))} за 1M"
                       if text["prompt_per_m"] is not None else None)

    active = info["active"]
    price_sample = f"{active} кр · {shape}" if active is not None else f"цены нет · {shape}"
    if kind == "text":
        derived = info["text"]["derived_message_credits"]
        other = f"после пересчёта: {derived} кр" if derived is not None else None
    else:
        label, value = ("по-старому", sample.legacy) if cfg.markup else ("при наценке", sample.markup)
        other = f"{label}: {value} кр" if value is not None else f"{label}: цены нет"
        note = _chat_note(info["chat"], sample.markup, cfg.markup)
        if note:
            other += note
    return {"pricing": info, "cost_sample": cost_sample, "price_sample": price_sample,
            "price_sample_other": other}


def model_info(model, context: dict) -> dict | None:
    """Вычисляемые колонки «Моделей» (себестоимость и цена типичной генерации в обоих
    режимах); один расчёт на модель за запрос. None — не посчиталось (в лог)."""
    store = context.setdefault("_model_prices", {})
    key = id(model)
    if key not in store:
        try:
            store[key] = _model_info(model, context)
        except Exception:
            logger.exception("цены: колонки модели %s не посчитались", getattr(model, "openrouter_id", "?"))
            store[key] = None
    return store[key]


def vstudio_supported(model) -> bool:
    """Код видеостудии знает семейство модели (vstudio/caps.py) — тумблер имеет смысл."""
    try:
        from vstudio.caps import lookup

        return lookup(getattr(model, "openrouter_id", ""))[0] is not None
    except Exception:
        return False


def save_model(ser, *, actor, request) -> list:
    """Сохранить правку строки «Моделей», записать журнал, сбросить кэши цен.

    Сбрасываем на любую правку: цену меняют и наценка, и себестоимость, и тариф,
    и включение модели или показ в видеостудии.
    """
    obj = ser.instance
    fields = list(ser.validated_data)
    before = {field: getattr(obj, field) for field in fields}
    with transaction.atomic():
        ser.save()
        changed = [field for field in fields if before[field] != getattr(obj, field)]
        if changed:
            log_admin_action(actor, LOG_ACTION, target=obj,
                             before={LOG_MODEL: {field: before[field] for field in changed}},
                             after={LOG_MODEL: {field: getattr(obj, field) for field in changed}},
                             request=request)
    if changed:
        invalidate()
    return changed


# ---------------------------------------------------------------- каталог OpenRouter

def _video_catalog() -> list:
    try:
        from ai.handlers import _load_video_catalog

        rows = _load_video_catalog()
    except Exception:
        logger.exception("цены: каталог видео OpenRouter не прочитался")
        rows = []
    return [row for row in rows or [] if isinstance(row, dict) and row.get("id")]


def _text_catalog() -> list:
    try:
        rows = pricing.openrouter_models_catalog()
    except Exception:
        logger.exception("цены: каталог моделей OpenRouter не прочитался")
        rows = []
    return [row for row in rows or [] if isinstance(row, dict) and row.get("id")]


def _kind_of(row: dict) -> str | None:
    arch = row.get("architecture") or {}
    outputs = [str(x).lower() for x in (arch.get("output_modalities") or [])]
    if not outputs:
        modality = str(arch.get("modality") or "")
        outputs = modality.split("->", 1)[1].split("+") if "->" in modality else ["text"]
    if "image" in outputs:
        return "image"
    if "text" in outputs:
        return "text"
    return None


def catalog_entries(kind: str = "") -> tuple[list, dict]:
    """[(вид, строка каталога)] и {"video"|"text": "ok"|"unavailable"}.

    Видео — из /videos/models (тот же кэш, что у цены видео), текст и картинки —
    из /models. Если модель есть в обоих, она видео.
    """
    entries: list = []
    catalogs: dict = {}
    seen: set = set()
    if kind in ("", "video"):
        rows = _video_catalog()
        catalogs["video"] = "ok" if rows else "unavailable"
        for row in rows:
            entries.append(("video", row))
            seen.add(row["id"])
    if kind in ("", "image", "text"):
        rows = _text_catalog()
        catalogs["text"] = "ok" if rows else "unavailable"
        for row in rows:
            row_kind = _kind_of(row)
            if row_kind and kind in ("", row_kind) and row["id"] not in seen:
                entries.append((row_kind, row))
                seen.add(row["id"])
    return entries, catalogs


def _short_name(row: dict) -> str:
    # «ByteDance: Seedance 2.0 Mini» → «Seedance 2.0 Mini»: вендор виден по ID.
    name = str(row.get("name") or "").strip() or str(row["id"]).split("/")[-1]
    return name.split(": ", 1)[1].strip() if ": " in name else name


def _input_has_image(row: dict) -> bool:
    arch = row.get("architecture") or {}
    inputs = [str(x).lower() for x in (arch.get("input_modalities") or [])]
    return "image" in inputs or "image" in str(arch.get("modality") or "").split("->", 1)[0]


def _video_estimate(row: dict, cfg) -> dict:
    """Себестоимость и цена при общей наценке на 5 с 720p (притянутые к модели)."""
    from ai import video_cost
    from ai.handlers import _openrouter_config, _video_model_params

    snapped = _video_model_params(row["id"], _openrouter_config(), 5, "720p")
    seconds, resolution = int(snapped["duration"]), str(snapped["resolution"])
    aspect = video_cost.default_aspect(row)
    cost = pricing.to_cost(video_cost.provider_cost_usd(row, resolution, seconds, aspect=aspect))
    shape = {"seconds": seconds, "resolution": resolution, "aspect": aspect}
    price = None
    if cost is not None:
        try:
            price = pricing.credits_for_cost(cost, None, cfg=cfg)
        except pricing.PriceUnavailable:
            price = None
    return {"shape": shape, "cost_usd": _str_cost(cost),
            "cost_text": f"{usd_text(cost)} · {shape_text('video', shape)}" if cost is not None else None,
            "price_markup": price}


def _text_estimate(row: dict, cfg) -> dict:
    price = pricing.text_model_prices(row["id"], [row])
    out = {"shape": {"tokens": TEXT_TOKENS}, "cost_usd": None, "cost_text": None, "price_markup": None,
           "coefficient": None}
    if price is None:
        return out
    per_in, per_out = price.per_million()
    out["cost_text"] = f"{usd_text(per_in)} / {usd_text(per_out)} за 1M"
    out["cost_usd"] = _str_cost((pricing.TEXT_INPUT_SHARE * price.prompt
                                 + pricing.TEXT_OUTPUT_SHARE * price.completion) * TEXT_TOKENS)
    try:
        coeff = pricing.derived_text_coeff(price.prompt, price.completion, None, cfg=cfg)
    except ValueError:
        return out
    out["coefficient"] = f"{coeff:.3f}"
    out["price_markup"] = pricing.text_message_credits(coeff, TEXT_TOKENS)
    return out


def _catalog_row(kind: str, row: dict, existing, cfg) -> dict:
    out = {
        "openrouter_id": row["id"],
        "name": _short_name(row),
        "full_name": str(row.get("name") or ""),
        "kind": kind,
        "category": kind if kind in NON_TEXT else "chat",
        "exists": existing is not None,
        "model_id": existing.pk if existing is not None else None,
        "is_active": bool(existing.is_active) if existing is not None else None,
        "vstudio_supported": vstudio_supported(SimpleNamespace(openrouter_id=row["id"])),
        "supports_vision": kind != "video" and _input_has_image(row),
        "description": str(row.get("description") or "")[:DESCRIPTION_MAX],
        "shape": None, "cost_usd": None, "cost_text": None, "price_markup": None, "coefficient": None,
    }
    try:
        if kind == "video":
            out.update(_video_estimate(row, cfg))
        elif kind == "text":
            out.update(_text_estimate(row, cfg))
    except Exception:
        logger.exception("цены: оценка %s из каталога не посчиталась", row["id"])
    return out


def search_catalog(query: str, kind: str) -> dict:
    entries, catalogs = catalog_entries(kind)
    q = query.strip().lower()
    matched = [(k, row) for k, row in entries
               if not q or q in str(row["id"]).lower() or q in str(row.get("name") or "").lower()]
    # Точное совпадение ID — первым, дальше видео, картинки, текст — по имени.
    matched.sort(key=lambda item: (str(item[1]["id"]).lower() != q, KIND_ORDER[item[0]],
                                   _short_name(item[1]).lower()))
    page = matched[:CATALOG_LIMIT]
    existing = {m.openrouter_id: m for m in GPTModels.objects.filter(openrouter_id__in=[r["id"] for _k, r in page])}
    cfg = pricing.current_config()
    return {"results": [_catalog_row(k, row, existing.get(row["id"]), cfg) for k, row in page],
            "count": len(matched), "truncated": len(matched) > CATALOG_LIMIT, "catalogs": catalogs}


class ModelsCatalogView(StaffAPIView):
    """GET ?q=&kind= — модели OpenRouter, которые можно добавить кнопкой «Добавить модель»."""

    def get(self, request):
        query = str(request.query_params.get("q") or "")
        kind = str(request.query_params.get("kind") or "").strip().lower()
        if len(query) > QUERY_MAX:
            return _bad(f"Запрос длиннее {QUERY_MAX} символов.")
        if kind and kind not in KINDS:
            return _bad("kind: video, image или text (пусто — все).")
        return Response(search_catalog(query, kind))


# ---------------------------------------------------------------- «Добавить модель»

def _category_for(kind: str, raw) -> tuple[str | None, str | None]:
    """(категория, ошибка) для новой строки: видео и картинки — только в своей категории."""
    if raw is None or (isinstance(raw, str) and not raw.strip()):
        return (kind if kind in NON_TEXT else "chat"), None
    value = str(raw).strip().lower() if isinstance(raw, str) else ""
    if value not in CATEGORIES:
        return None, "Категория: одна из " + ", ".join(CATEGORIES) + "."
    if kind == "video" and value != "video":
        return None, "Видео-модель встаёт только в категорию «Видео» (video)."
    if kind == "image" and value != "image":
        return None, "Модель картинок встаёт только в категорию «Изображения» (image)."
    if kind == "text" and value in NON_TEXT:
        return None, "Текстовая модель не может стоять в категории картинок или видео."
    return value, None


def _unique_name(base: str) -> str:
    base = base[:NAME_MAX].strip() or "Модель"
    taken = set(GPTModels.objects.filter(name__startswith=base[:NAME_MAX - 6]).values_list("name", flat=True))
    if base not in taken:
        return base
    for n in range(2, 100):
        candidate = f"{base[:NAME_MAX - 5]} ({n})"
        if candidate not in taken:
            return candidate
    return f"{base[:NAME_MAX - 12]} ({GPTModels.objects.count() + 1})"


def _add_warnings(model, kind: str, row: dict) -> list:
    out = ["Модель добавлена выключенной: включите её, когда проверите цену."]
    if kind == "text":
        hint = ""
        estimate = _text_estimate(row, pricing.current_config())
        if estimate["coefficient"]:
            hint = f" По себестоимости с наценкой выходит {estimate['coefficient'].replace('.', ',')}."
        out.append("Тариф 1 кр за 1000 токенов. Перед включением задайте тариф или нажмите "
                   "«Пересчитать тарифы текста»." + hint)
    elif kind == "image":
        out.append("Себестоимость картинки не задана: в режиме «наценка» цена будет по тарифу 1 кр. "
                   "Введите себестоимость перед включением.")
        if not is_flux_image_model(model.openrouter_id):
            chat = pricing.chat_image_price(model)
            out.append(f"В чате такая модель списывается по токенам: при тарифе 1 картинка стоит около "
                       f"{chat.credits} кр. Тариф по наценке ставит кнопка {CHAT_IMAGE_BUTTON} "
                       "(в режиме «наценка», когда задана себестоимость) — или задайте его вручную.")
    else:
        try:
            unknown = _video_estimate(row, pricing.current_config())["cost_usd"] is None
        except Exception:
            unknown = True
        if unknown:
            out.append("OpenRouter не сообщает цену этой модели в понятном виде: в режиме «наценка» "
                       "она не продаётся.")
        if not vstudio_supported(model):
            out.append("Видеостудия пока не знает эту модель: показать её можно только в чате.")
    return out


def add_model(request) -> Response:
    """POST models/ {openrouter_id, name?, category?} — новая строка, выключенная."""
    from .serializers import GPTModelAdminSerializer

    body = _body(request)
    raw_id = body.get("openrouter_id")
    orid = raw_id.strip() if isinstance(raw_id, str) else ""
    if not orid:
        return _bad("Укажите ID модели OpenRouter, например bytedance/seedance-2.0-mini.")
    if len(orid) > ID_MAX:
        return _bad(f"ID модели длиннее {ID_MAX} символов.")
    existing = GPTModels.objects.filter(openrouter_id=orid).first()
    if existing is not None:
        return _bad(f"Модель «{existing.name}» уже есть в списке.", status.HTTP_409_CONFLICT,
                    model_id=existing.pk)

    entries, catalogs = catalog_entries()
    found = next(((kind, row) for kind, row in entries if row["id"] == orid), None)
    if found is None:
        # Не нашли, а один из каталогов не ответил: модель может быть как раз там.
        if any(value == "unavailable" for value in catalogs.values()):
            return _bad("Каталог OpenRouter сейчас недоступен — попробуйте позже.",
                        status.HTTP_503_SERVICE_UNAVAILABLE)
        return _bad(f"Модели «{orid}» нет в каталоге OpenRouter. Проверьте ID: как на openrouter.ai.")
    kind, row = found

    category, error = _category_for(kind, body.get("category"))
    if error:
        return _bad(error)
    raw_name = body.get("name")
    if raw_name is not None and not isinstance(raw_name, str):
        return _bad("Название — строка.")
    name = (raw_name or "").strip()
    if name:
        if len(name) > NAME_MAX:
            return _bad(f"Название длиннее {NAME_MAX} символов.")
        if GPTModels.objects.filter(name=name).exists():
            return _bad(f"Модель с названием «{name}» уже есть.")
    else:
        name = _unique_name(_short_name(row))

    with transaction.atomic():
        last = GPTModels.objects.aggregate(m=Max("sort_order"))["m"] or 0
        try:
            with transaction.atomic():
                model = GPTModels.objects.create(
                    name=name, openrouter_id=orid, category=category, description="", short_label="",
                    max_tokens=NEW_MODEL_MAX_TOKENS,
                    # 1, а не 0: бот принимает тариф 0 за «модели нет» (PLAN §5(b)).
                    markup_coefficient=Decimal("1"),
                    is_active=False, recommended=False, free_tier=False, cartoon_stage="",
                    supports_vision=kind != "video" and _input_has_image(row),
                    vstudio_enabled=False, sort_order=last + SORT_STEP)
        except IntegrityError:
            return _bad("Модель с таким ID или названием уже есть.", status.HTTP_409_CONFLICT)
        log_admin_action(request.user, LOG_ACTION, target=model, before={LOG_MODEL_ADD: None},
                         after={LOG_MODEL_ADD: {"openrouter_id": orid, "name": name, "category": category,
                                                "kind": kind, "is_active": False, "markup_coefficient": "1"}},
                         request=request)
    invalidate()
    row_json = GPTModelAdminSerializer(model, context={"request": request}).data
    return Response({"model": row_json, "warnings": _add_warnings(model, kind, row)},
                    status=status.HTTP_201_CREATED)


# ---------------------------------------------------------------- пересчёт тарифов текста

def _recompute_row(model, cfg, basis, catalog) -> dict:
    old = Decimal(str(model.markup_coefficient or 0)).quantize(Decimal("0.001"))
    own = pricing.model_markup_pct(model)
    row = {
        "id": model.pk, "name": model.name, "openrouter_id": model.openrouter_id,
        "category": model.category, "is_active": bool(model.is_active),
        "old_coefficient": f"{old:.3f}", "new_coefficient": None,
        "old_message_credits": pricing.text_message_credits(old, TEXT_TOKENS), "new_message_credits": None,
        "delta_pct": None, "prompt_per_m": None, "completion_per_m": None, "price_text": None,
        "markup_pct": pricing.plain(pricing.effective_markup_pct(model, cfg)),
        "markup_source": "model" if own is not None else "global",
        "status": "no_price",
    }
    price = pricing.text_model_prices(model.openrouter_id, catalog)
    if price is None:
        return row
    per_in, per_out = price.per_million()
    row.update(prompt_per_m=pricing.plain(per_in), completion_per_m=pricing.plain(per_out),
               price_text=f"{usd_text(per_in)} / {usd_text(per_out)} за 1M")
    if basis is None:
        row["status"] = "no_basis"
        return row
    try:
        new = pricing.derived_text_coeff(price.prompt, price.completion, model, cfg=cfg, basis=basis)
    except ValueError:
        row["status"] = "too_expensive"
        return row
    new_credits = pricing.text_message_credits(new, TEXT_TOKENS)
    row.update(new_coefficient=f"{new:.3f}", new_message_credits=new_credits,
               delta_pct=_delta_pct(row["old_message_credits"], new_credits),
               status="unchanged" if new == old else "ok")
    return row


def recompute_preview(ids=()) -> dict:
    """Тарифы текста «было → станет» по ценам OpenRouter. Включённые текстовые модели
    и, если переданы, ещё ids (например, только что добавленная выключенная)."""
    cfg = pricing.current_config()
    basis = pricing.credit_basis(cfg)
    catalog = _text_catalog()
    qs = (GPTModels.objects.exclude(category__in=NON_TEXT)
          .filter(Q(is_active=True) | Q(pk__in=list(ids))).order_by("sort_order", "id"))
    rows = [_recompute_row(model, cfg, basis, catalog) for model in qs]
    summary: dict = {}
    for row in rows:
        summary[row["status"]] = summary.get(row["status"], 0) + 1
    basis_dict = basis.to_dict() if basis is not None else None
    return {
        "kind": "text",
        "mode": cfg.mode,
        "can_apply": cfg.markup,
        "apply_blocked": None if cfg.markup else (
            "Тарифы текста пересчитываются в режиме «наценка». Сейчас режим legacy: "
            "переключите режим в «Настройках → Цены и наценка»."),
        "markup_pct": pricing.plain(cfg.markup_pct), "floor_pct": pricing.plain(cfg.floor_pct),
        "basis": basis_dict, "basis_line": basis_line(basis_dict),
        "tokens": TEXT_TOKENS,
        "catalog": "ok" if catalog else "unavailable",
        "rows": rows,
        "summary": summary,
    }


def _parse_ids(raw) -> list | None:
    if raw is None or not str(raw).strip():
        return []
    out = []
    for part in str(raw).split(","):
        part = part.strip()
        if not part.isdigit():
            return None
        out.append(int(part))
    return out


def _parse_items(items) -> tuple[list, str | None]:
    if not isinstance(items, list) or not items:
        return [], "items: список {id, coefficient} из предпросмотра."
    if len(items) > RECOMPUTE_MAX_ITEMS:
        return [], f"items: не больше {RECOMPUTE_MAX_ITEMS} моделей за раз."
    out, seen = [], set()
    for n, item in enumerate(items, 1):
        if not isinstance(item, dict):
            return [], f"items, строка {n}: нужен объект {{id, coefficient}}."
        pk = item.get("id")
        if isinstance(pk, bool) or not isinstance(pk, int):
            return [], f"items, строка {n}: id — номер модели."
        raw = item.get("coefficient")
        try:
            if isinstance(raw, bool) or raw is None:
                raise InvalidOperation
            coeff = Decimal(str(raw).strip().replace(",", ".")).quantize(Decimal("0.001"))
        except (InvalidOperation, ValueError):
            return [], f"items, строка {n}: coefficient — тариф из предпросмотра, например 1.224."
        if pk in seen:
            return [], f"Модель {pk} указана дважды."
        seen.add(pk)
        out.append((pk, coeff))
    return out, None


def not_text_reason(model) -> str:
    """Почему пересчёт по ценам текста не трогает эту модель."""
    name = model.name
    if model.category == "video":
        return f"«{name}» — видеомодель: её цена считается по себестоимости ролика, а не тарифом текста."
    if is_flux_image_model(model.openrouter_id):
        return f"«{name}» — модель картинок FLUX: она списывается за картинку, а не тарифом текста."
    # Nano Banana и др.: в чате тариф действует (токены × тариф), но токены картинки
    # OpenRouter берёт дороже текстовых — пересчёт по ценам текста занизил бы цену.
    return (f"У «{name}» картинка в чате списывается по токенам × тариф модели, но токены картинки "
            "OpenRouter берёт дороже текстовых: пересчёт по ценам текста занизил бы её цену. Тариф этой "
            f"модели по себестоимости картинки ставит кнопка {CHAT_IMAGE_BUTTON}.")


TEXT_BLOCKED = ("Тарифы текста пересчитываются в режиме «наценка». Сейчас режим legacy: "
                "переключите режим в «Настройках → Цены и наценка».")


def _text_refusal(model) -> str | None:
    return not_text_reason(model) if model.category in NON_TEXT else None


def _text_not_ready(row: dict) -> str:
    return f"У «{row['name']}» сейчас нет цены по себестоимости — обновите предпросмотр."


def _apply_tariffs(request, *, preview_fn, refusal, blocked: str, not_ready, log_key: str) -> Response:
    """Записать тарифы из подтверждённого предпросмотра (текст и картинки в чате).

    Сервер считает предпросмотр заново: что-то сдвинулось (цена OpenRouter, наценка,
    курс, пакет) — 409 со свежим предпросмотром, и не пишется ничего. Каждая
    запись — в журнал действий; кэши цен сбрасываются.
    """
    body = _body(request)
    if body.get("confirm") is not True:
        return _bad("Подтвердите пересчёт: confirm: true.")
    if not pricing.current_config().markup:
        return _bad(blocked, status.HTTP_409_CONFLICT)
    items, error = _parse_items(body.get("items"))
    if error:
        return _bad(error)
    models = {m.pk: m for m in GPTModels.objects.filter(pk__in=[pk for pk, _c in items])}
    for pk, _coeff in items:
        model = models.get(pk)
        if model is None:
            return _bad(f"Модель {pk} не найдена.", status.HTTP_404_NOT_FOUND)
        reason = refusal(model)
        if reason:
            return _bad(reason)

    preview = preview_fn([pk for pk, _c in items])
    rows = {row["id"]: row for row in preview["rows"]}
    for pk, _coeff in items:
        row = rows[pk]
        if row["status"] not in TEXT_STATUSES_OK:
            return _bad(not_ready(row), status.HTTP_409_CONFLICT, preview=preview)
    if any(Decimal(rows[pk]["new_coefficient"]) != coeff for pk, coeff in items):
        return _bad("Цены изменились с момента предпросмотра — проверьте новые значения и примените ещё раз.",
                    status.HTTP_409_CONFLICT, preview=preview)

    updated = []
    with transaction.atomic():
        for pk, coeff in items:
            model = models[pk]
            old = Decimal(str(model.markup_coefficient or 0)).quantize(Decimal("0.001"))
            if old == coeff:
                continue
            model.markup_coefficient = coeff
            model.save(update_fields=["markup_coefficient", "updated_at"])
            log_admin_action(request.user, LOG_ACTION, target=model,
                             before={log_key: f"{old:.3f}"}, after={log_key: f"{coeff:.3f}"},
                             request=request)
            updated.append({"id": pk, "name": model.name, "old_coefficient": f"{old:.3f}",
                            "new_coefficient": f"{coeff:.3f}"})
    if updated:
        invalidate()
    return Response({"updated": updated, "preview": preview_fn([pk for pk, _c in items])})


def apply_recompute(request) -> Response:
    return _apply_tariffs(request, preview_fn=recompute_preview, refusal=_text_refusal, blocked=TEXT_BLOCKED,
                          not_ready=_text_not_ready, log_key=LOG_TEXT_TARIFF)


class TextRecomputeView(StaffAPIView):
    """GET — предпросмотр «Пересчитать тарифы текста»; POST — применить подтверждённое."""

    def get(self, request):
        ids = _parse_ids(request.query_params.get("ids"))
        if ids is None:
            return _bad("ids: номера моделей через запятую.")
        return Response(recompute_preview(ids))

    def post(self, request):
        return apply_recompute(request)


# ---------------------------------------------------------------- тариф картинок в чате

# Клиент 4.1: наценка — для всех моделей. Картинку Nano Banana чат списывает токенами
# × тариф (ai/handlers.py), не за картинку, и наценка до неё не доходит. Кнопка
# ставит тариф, при котором картинка в чате стоит столько же, сколько в студиях
# по наценке (pricing.chat_image_tariff). Как и тарифы текста — только по кнопке.
CHAT_IMAGE_BLOCKED = (
    "Тариф картинок в чате выравнивается в режиме «наценка»: в режиме legacy этот же тариф — ещё и цена "
    "картинки в студиях. Переключите режим в «Настройках → Цены и наценка».")


def _chat_image_row(model, cfg, basis, tokens: int) -> dict:
    old = Decimal(str(model.markup_coefficient or 0)).quantize(Decimal("0.001"))
    own = pricing.model_markup_pct(model)
    unit = pricing.to_cost(model.unit_cost_usd)
    row = {
        "id": model.pk, "name": model.name, "openrouter_id": model.openrouter_id,
        "category": model.category, "is_active": bool(model.is_active),
        "old_coefficient": f"{old:.3f}", "new_coefficient": None,
        # Картинка в чате на ~tokens токенов — сейчас и с новым тарифом (имена полей — как у текста).
        "old_message_credits": pricing.text_message_credits(old, tokens), "new_message_credits": None,
        "delta_pct": None, "prompt_per_m": None, "completion_per_m": None,
        "price_text": None if unit is None else f"{usd_text(unit)} за картинку",
        "cost_usd": _str_cost(unit),
        "studio_credits": None,
        # В режиме legacy студии берут этот же тариф за картинку: вернут режим — будет эта цена.
        "legacy_studio_old": pricing.legacy_image_credits(model), "legacy_studio_new": None,
        "markup_pct": pricing.plain(pricing.effective_markup_pct(model, cfg)),
        "markup_source": "model" if own is not None else "global",
        "status": "no_cost",
    }
    if unit is None:
        return row
    if basis is None:
        row["status"] = "no_basis"
        return row
    try:
        tariff = pricing.chat_image_tariff(model, cfg=cfg, basis=basis, tokens=tokens)
    except ValueError:
        row["status"] = "too_expensive"
        return row
    new = tariff.coefficient
    new_credits = pricing.text_message_credits(new, tokens)
    row.update(new_coefficient=f"{new:.3f}", new_message_credits=new_credits, studio_credits=tariff.credits,
               legacy_studio_new=pricing.legacy_image_credits(SimpleNamespace(markup_coefficient=new)),
               price_text=f"{usd_text(unit)} за картинку · по наценке {tariff.credits} кр",
               delta_pct=_delta_pct(row["old_message_credits"], new_credits),
               status="unchanged" if new == old else "ok")
    return row


def chat_image_recompute_preview(ids=()) -> dict:
    """Тариф картинок в чате «было → станет»: включённые модели картинок, которые чат
    списывает по токенам (не FLUX), и, если переданы, ещё ids."""
    cfg = pricing.current_config()
    basis = pricing.credit_basis(cfg)
    tokens = pricing.chat_image_tokens()
    qs = (GPTModels.objects.filter(category="image").filter(Q(is_active=True) | Q(pk__in=list(ids)))
          .order_by("sort_order", "id"))
    rows = [_chat_image_row(model, cfg, basis, tokens) for model in qs if is_chat_token_image(model)]
    summary: dict = {}
    for row in rows:
        summary[row["status"]] = summary.get(row["status"], 0) + 1
    basis_dict = basis.to_dict() if basis is not None else None
    return {
        "kind": "chat_image",
        "mode": cfg.mode,
        "can_apply": cfg.markup,
        "apply_blocked": None if cfg.markup else CHAT_IMAGE_BLOCKED,
        "markup_pct": pricing.plain(cfg.markup_pct), "floor_pct": pricing.plain(cfg.floor_pct),
        "basis": basis_dict, "basis_line": basis_line(basis_dict),
        "tokens": tokens,
        "rows": rows,
        "summary": summary,
    }


def chat_image_refusal(model) -> str | None:
    """Почему тариф картинок в чате не про эту модель (None — про неё)."""
    if is_chat_token_image(model):
        return None
    if model.category == "image":
        return (f"«{model.name}» — модель картинок FLUX: чат списывает её за картинку по себестоимости, "
                "тариф за токены ей не нужен.")
    if model.category == "video":
        return f"«{model.name}» — видеомодель: её цена считается по себестоимости ролика, а не этим тарифом."
    return f"«{model.name}» — текстовая модель: её тариф пересчитывает «Пересчитать тарифы текста»."


def _chat_image_not_ready(row: dict) -> str:
    if row["status"] == "no_cost":
        return f"У «{row['name']}» не задана себестоимость картинки — введите её в строке модели."
    return f"У «{row['name']}» сейчас нет цены по себестоимости — обновите предпросмотр."


def apply_chat_image_recompute(request) -> Response:
    return _apply_tariffs(request, preview_fn=chat_image_recompute_preview, refusal=chat_image_refusal,
                          blocked=CHAT_IMAGE_BLOCKED, not_ready=_chat_image_not_ready,
                          log_key=LOG_CHAT_IMAGE_TARIFF)


class ChatImageRecomputeView(StaffAPIView):
    """GET — предпросмотр «Пересчитать тариф картинок в чате»; POST — применить подтверждённое."""

    def get(self, request):
        ids = _parse_ids(request.query_params.get("ids"))
        if ids is None:
            return _bad("ids: номера моделей через запятую.")
        return Response(chat_image_recompute_preview(ids))

    def post(self, request):
        return apply_chat_image_recompute(request)
