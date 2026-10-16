"""Док мультстудии в API: разбор настроек из запросов и список моделей.

Настройки (модель, качество, длительность) приходят в трёх местах: создание и
правка мультфильма, длительность сцены и цены витрины для гостя. Проверка одна —
по возможностям выбранной модели из каталога OpenRouter (pricing.model_caps), с
русскими текстами отказов. Контракт: vstudio2-notes/pricing/CONTRACT_C.md.
"""
from __future__ import annotations

import logging

from rest_framework import status

from . import pricing

logger = logging.getLogger(__name__)

FIELDS = ("video_model", "resolution", "duration")

# Список моделей дока считается сотнями цен — держим его в кэше. Ключ через
# ai.pricing.cache_key: сохранение цен, моделей или пакетов сбрасывает его сразу.
MODELS_CACHE_NAME = "cartoon:models:v1"
MODELS_CACHE_S = 600
MODELS_CACHE_DEGRADED_S = 60


class SettingsError(Exception):
    """Настройку не принять: HTTP-статус и тело отказа {detail, error, error_code, field}."""

    def __init__(self, message: str, code: str, field: str = "",
                 http_status: int = status.HTTP_400_BAD_REQUEST):
        super().__init__(message)
        self.message = message
        self.code = code
        self.field = field
        self.status = http_status

    def payload(self) -> dict:
        body = {"detail": self.message, "error": self.message, "error_code": self.code}
        if self.field:
            body["field"] = self.field
        return body


def _caps_or_error(model, memo: dict | None):
    caps = pricing.model_caps(model, memo)
    if caps is None:
        raise SettingsError("Не удалось проверить возможности модели — попробуйте через минуту",
                            "caps_unavailable", http_status=status.HTTP_503_SERVICE_UNAVAILABLE)
    return caps


def parse_model(raw):
    """Модель из запроса: строка-ID OpenRouter из дока. Пусто — None (как в пресете)."""
    from ai.models import GPTModels

    if raw is None or raw == "":
        return None
    if not isinstance(raw, str):
        raise SettingsError("Модель — строкой, например bytedance/seedance-2.0-mini",
                            "invalid_model", "video_model")
    model = GPTModels.objects.filter(openrouter_id=raw.strip()[:128]).first()
    if not pricing.is_offered(model):
        raise SettingsError("Эта модель недоступна в мультстудии — выберите другую",
                            "model_unavailable", "video_model")
    return model


def parse_duration_value(raw) -> int | None:
    """Целое число секунд или None (пусто — по умолчанию). Остальное — отказ."""
    if raw is None or raw == "":
        return None
    if isinstance(raw, bool):
        raise SettingsError("Длительность — целое число секунд", "invalid_duration", "duration")
    try:
        value = int(str(raw).strip())
    except (TypeError, ValueError):
        raise SettingsError("Длительность — целое число секунд", "invalid_duration", "duration")
    if not 1 <= value <= pricing.MAX_DURATION:
        raise SettingsError(f"Длительность — от 1 до {pricing.MAX_DURATION} секунд",
                            "invalid_duration", "duration")
    return value


def _parse_resolution_value(raw) -> str | None:
    if raw is None or raw == "":
        return None
    if not isinstance(raw, str) or len(raw.strip()) > 8:
        raise SettingsError("Качество — например 480p или 720p", "invalid_resolution", "resolution")
    return raw.strip()


def check_resolution(model, caps, raw: str) -> str:
    found = pricing.find_resolution(caps.resolutions, raw)
    if found is None:
        raise SettingsError(pricing.resolution_error(model, caps, raw), "unsupported_resolution",
                            "resolution")
    return found


def check_duration(model, caps, value: int) -> int:
    if value not in caps.durations:
        raise SettingsError(pricing.duration_error(model, caps), "unsupported_duration", "duration")
    return value


def _adjust_note(field: str, old, new, model) -> dict:
    name = pricing.short_name(model)
    if field == "resolution":
        text = f"{name} не снимает в качестве {old} — выбрано {new}"
    else:
        text = f"{name} не снимает {old} с — выбрано {new} с"
    return {"field": field, "from": old, "to": new, "message": text}


def _dock_model(project, memo: dict | None):
    """Модель, по которой проверяются качество и длительность мультфильма без своей модели:
    своя модель мультфильма, иначе модель «типичной сцены»."""
    if project is not None and project.video_model_id and pricing.is_offered(project.video_model):
        return project.video_model
    ref = pricing.reference_preset(memo)
    model = ref.video_model if ref is not None else None
    return model if pricing.is_offered(model) else None


def parse_project_settings(data: dict, project=None, *, lenient: bool = False,
                           memo: dict | None = None) -> tuple[dict, list]:
    """Настройки дока из тела запроса → ({поле: значение}, adjusted).

    - video_model: ID модели дока; null или "" — вернуть всё «как в пресете»
      (модель, качество и длительность разом);
    - resolution, duration: проверяются по модели — присланной, иначе модели
      мультфильма, иначе модели «типичной сцены» (тогда она и записывается:
      качество без модели не имеет смысла); null — значение пресета;
    - сменилась модель, а прежние качество/длительность она не умеет — берётся
      ближайшее, и это попадает в adjusted ({field, from, to, message}).
    lenient — черновик гостя: неверное значение не отказ, а ближайшее (adjusted).
    Бросает SettingsError (400 / 503).
    """
    if not isinstance(data, dict) or not any(f in data for f in FIELDS):
        return {}, []
    adjusted: list = []
    if "video_model" in data and data["video_model"] in (None, ""):
        return {"video_model": None, "resolution": None, "duration": None}, []

    model_given = "video_model" in data
    try:
        model = parse_model(data["video_model"]) if model_given else None
    except SettingsError:
        if not lenient:
            raise
        return {}, []
    current_model = (project.video_model if project is not None and project.video_model_id else None)
    if model is None:
        model = _dock_model(project, memo)
        if model is None:
            if lenient:
                return {}, []
            raise SettingsError("Сначала выберите модель", "model_required", "video_model")
    caps = _caps_or_error(model, memo)
    changes: dict = {}
    if model_given or current_model is None or current_model.pk != model.pk:
        changes["video_model"] = model

    for field, parse, check, current in (
            ("resolution", _parse_resolution_value, check_resolution,
             project.resolution if project is not None else None),
            ("duration", parse_duration_value, check_duration,
             project.duration if project is not None else None)):
        if field in data:
            try:
                value = parse(data[field])
            except SettingsError:
                if not lenient:
                    raise
                value = None
            if value is not None:
                try:
                    value = check(model, caps, value)
                except SettingsError:
                    if not lenient:
                        raise
                    fixed = (pricing.clamp_resolution(caps.resolutions, value) if field == "resolution"
                             else pricing.clamp_duration(caps.durations, value))
                    adjusted.append(_adjust_note(field, value, fixed, model))
                    value = fixed
            changes[field] = value
        elif "video_model" in changes and current:
            # Модель сменилась, своё значение мультфильма осталось: годится ли оно новой.
            ok = (pricing.find_resolution(caps.resolutions, current) if field == "resolution"
                  else (current if current in caps.durations else None))
            if ok is None:
                fixed = (pricing.clamp_resolution(caps.resolutions, current) if field == "resolution"
                         else pricing.clamp_duration(caps.durations, current))
                adjusted.append(_adjust_note(field, current, fixed, model))
                changes[field] = fixed
    return changes, adjusted


def parse_scene_duration(raw, scene, *, memo: dict | None = None) -> int | None:
    """Длительность сцены: целое в пределах модели, которой сцена снимется; null — по умолчанию."""
    value = parse_duration_value(raw)
    if value is None:
        return None
    cfg = pricing.scene_config(scene, memo)
    caps = _caps_or_error(cfg.model, memo)
    return check_duration(cfg.model, caps, value)


def feed_settings(params, project=None, *, memo: dict | None = None) -> dict | None:
    """Настройки для цен витрины: из мультфильма (?project=) и/или явных параметров.

    None — ни того, ни другого: цены по пресетам, как раньше (бот, /pricing/studio).
    Явные video_model/resolution/duration проверяются, как в правке мультфильма.
    """
    explicit = {f: params.get(f) for f in FIELDS if params.get(f) not in (None, "")}
    if project is None and not explicit:
        return None
    model = project.video_model if project is not None and project.video_model_id else None
    resolution = project.resolution if project is not None else None
    duration = project.duration if project is not None else None
    if "video_model" in explicit:
        model = parse_model(explicit["video_model"])
    if "resolution" in explicit:
        resolution = _parse_resolution_value(explicit["resolution"])
    if "duration" in explicit:
        duration = parse_duration_value(explicit["duration"])
    if model is not None and ("resolution" in explicit or "duration" in explicit):
        caps = _caps_or_error(model, memo)
        if "resolution" in explicit:
            resolution = check_resolution(model, caps, resolution)
        if "duration" in explicit:
            duration = check_duration(model, caps, duration)
    return {"model": model, "resolution": resolution, "duration": duration}


# ---------------------------------------------------------------- список моделей

def defaults_json(memo: dict | None, *, preset: bool = False) -> dict:
    """Что получит новый мультфильм: настройки админки или (откат) «типичная сцена».

    preset — откат по решению вызывающего (тарифы: у модели по умолчанию нет цены).
    """
    model, res, dur = (None, None, None) if preset else pricing.new_project_settings(memo)
    if model is not None:
        return {"video_model": model.openrouter_id, "resolution": res, "duration": dur,
                "source": "settings"}
    ref = pricing.reference_preset(memo)
    if ref is None:
        return {"video_model": None, "resolution": None, "duration": None, "source": "preset"}
    cfg = pricing.resolve_config(ref, memo=memo)
    return {"video_model": cfg.model_id or None, "resolution": cfg.resolution, "duration": cfg.duration,
            "source": "preset"}


def _model_row(model, ref, memo: dict | None) -> dict | None:
    from vstudio import caps as caps_mod

    caps = pricing.model_caps(model, memo)
    if caps is None or not caps.durations or not caps.resolutions:
        return None
    built = caps_mod.build(model, pricing.model_spec(model, memo))
    base = caps_mod.to_json(built) if built is not None else {}
    base.update({"durations": list(caps.durations), "resolutions": list(caps.resolutions),
                 "aspect_ratios": list(caps.aspects)})
    by_aspect: dict | None = {}
    for aspect in caps.aspects:
        table = pricing.price_table(ref, model, caps, aspect, memo=memo)
        if table is None:
            by_aspect = None
            break
        by_aspect[aspect] = table
    # Значения при выборе модели в доке — настройки новых мультфильмов, в пределах модели.
    wanted = pricing.default_settings_raw()
    row = {
        "id": model.openrouter_id,
        "name": built.name if built is not None else str(model.name),
        "short": pricing.short_name(model),
        "badge": built.badge if built is not None else str(model.short_label or ""),
        "locked": False,
        "eta_s": int(built.eta_s) if built is not None else 150,
        "caps": base,
        "defaults": {"duration": pricing.clamp_duration(caps.durations, wanted["duration"]),
                     "resolution": pricing.clamp_resolution(caps.resolutions, wanted["resolution"]),
                     "aspect_ratio": "16:9" if "16:9" in caps.aspects else (caps.aspects or ("16:9",))[0]},
        "frame_credits": pricing.frame_credits(ref.image_model),
        "by_aspect": by_aspect,
    }
    return row


def _models_base(memo: dict | None) -> dict:
    """Всё, что не зависит от запроса: модели с таблицами цен по каждому формату."""
    from django.core.cache import cache

    from ai.pricing import cache_key

    key = cache_key(MODELS_CACHE_NAME)
    try:
        cached = cache.get(key)
    except Exception:
        cached = None
    if cached is not None:
        return cached
    ref = pricing.reference_preset(memo)
    rows, degraded = [], False
    if ref is not None:
        for model in pricing.offered_models():
            try:
                row = _model_row(model, ref, memo)
            except Exception:
                logger.exception("мультстудия: модель %s не попала в док", model.openrouter_id)
                row = None
            if row is None:
                degraded = True
                continue
            rows.append(row)
    base = {"models": rows, "defaults": defaults_json(memo),
            "frame_credits": pricing.frame_credits(ref.image_model) if ref is not None else None}
    try:
        cache.set(key, base, MODELS_CACHE_DEGRADED_S if degraded else MODELS_CACHE_S)
    except Exception:
        pass
    return base


def models_payload(aspect: str, *, memo: dict | None = None) -> dict:
    """GET cartoon/models/: модели дока в форме ModelJSON видеостудии.

    price.table — цена СЦЕНЫ (кадр + видео) по качеству и секундам в формате
    aspect; price.by_aspect — то же для каждого формата мультстудии, чтобы смена
    формата не требовала нового запроса. Готовый кадр в запасе — минус
    frame_credits. Цены нет (markup без себестоимости) — ключа price нет,
    price_from null и price_unavailable.
    """
    from ai.pricing import pricing_mode

    base = _models_base(memo)
    models = []
    for row in base["models"]:
        out = {k: v for k, v in row.items() if k != "by_aspect"}
        by_aspect = row.get("by_aspect")
        table = (by_aspect or {}).get(aspect)
        if table is None and by_aspect:
            table = next(iter(by_aspect.values()))
        if table:
            cells = [c for r in table.values() for c in r.values()]
            out["price"] = {"table": table, "by_aspect": by_aspect}
            out["price_from"] = min(cells) if cells else None
        else:
            # Как ModelJSON видеостудии: цены нет — нет и ключа price.
            out["price_from"] = None
            out["price_unavailable"] = True
        models.append(out)
    return {"aspect_ratio": aspect, "aspects": list(pricing.STUDIO_ASPECTS), "models": models,
            "defaults": base["defaults"], "frame_credits": base["frame_credits"],
            "pricing_mode": pricing_mode()}


# ---------------------------------------------------------------- настройки по умолчанию (админка)

def defaults_admin_payload() -> dict:
    """GET manage/defaults/: что задано, что реально получат новые мультфильмы и почему."""
    from adminapi.models import AppSetting
    from ai.models import GPTModels
    from vstudio.caps import MODELS

    raw = pricing.default_settings_raw()
    stored = set(AppSetting.objects.filter(key__in=pricing.DEFAULT_KEYS).values_list("key", flat=True))
    effective = defaults_json(None)
    rows = {m.openrouter_id: m for m in GPTModels.objects.filter(
        openrouter_id__in=[mid for mid, (fam, _) in MODELS.items() if fam in pricing.CARTOON_FAMILIES])}
    known = sorted((mid for mid, (fam, _) in MODELS.items() if fam in pricing.CARTOON_FAMILIES),
                   key=lambda mid: (pricing.MODEL_ORDER.index(mid) if mid in pricing.MODEL_ORDER
                                    else len(pricing.MODEL_ORDER), mid))
    models = []
    for mid in known:
        model = rows.get(mid)
        caps = pricing.model_caps(model) if model is not None else None
        models.append({"id": mid, "name": (model.name if model is not None else pricing.SHORT_NAMES.get(mid, mid)),
                       "short": pricing.SHORT_NAMES.get(mid, mid), "exists": model is not None,
                       "active": bool(model is not None and model.is_active),
                       "offered": pricing.is_offered(model),
                       "resolutions": list(caps.resolutions) if caps else [],
                       "durations": list(caps.durations) if caps else []})
    warnings = []
    if effective["source"] != "settings":
        chosen = rows.get(raw["model"])
        name = pricing.SHORT_NAMES.get(raw["model"], raw["model"])
        if chosen is None:
            why = f"модели {name} нет в списке «Модели» — добавьте её через «Добавить модель»"
        elif not pricing.is_offered(chosen):
            why = f"модель {name} выключена — включите её в «Моделях»"
        else:
            why = f"{name} не снимает {raw['resolution']} {raw['duration']} с"
        warnings.append(f"Новые мультфильмы пока снимаются как в сцене библиотеки: {why}")
    return {"model": raw["model"], "resolution": raw["resolution"], "duration": raw["duration"],
            "stored": {"model": pricing.KEY_DEFAULT_MODEL in stored,
                       "resolution": pricing.KEY_DEFAULT_RESOLUTION in stored,
                       "duration": pricing.KEY_DEFAULT_DURATION in stored},
            "code_defaults": {"model": pricing.CODE_DEFAULT_MODEL,
                              "resolution": pricing.CODE_DEFAULT_RESOLUTION,
                              "duration": pricing.CODE_DEFAULT_DURATION},
            "effective": effective, "models": models, "warnings": warnings}
