"""Формы данных API видеостудии (спецификация §8.3) и разбор тел запросов.

Выход — простые функции, а не DRF-сериализаторы: формы фиксированы контрактом
фронта (next/src/lib/vstudio/types.ts), многие поля считаются пачкой (позиция
в очереди, ETA), и так проще не наделать лишних запросов на каждый дубль.

Вход разбирается строго: кривое тело — 400 bad_request сразу, а не «что-то
подставили по умолчанию». Смысловые проверки (теги, режимы, лимиты модели)
делает компилятор — они приходят человеку списком с исправлениями.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import datetime

from django.core.files.storage import default_storage
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from rest_framework import serializers as drf_serializers

from . import prompt_doc as pd
from .errors import StudioError
from .models import TAKE_OPEN, Asset, Project, Shot, ShotInput, Take

UID_RE = re.compile(r"^[0-9a-f]{32}$")
# client_request_id: фронт шлёт 32 hex, но API-клиентам оставляем запас
# (≤64 символа, без пробелов и управляющих символов).
CLIENT_REQUEST_ID_RE = re.compile(r"^[A-Za-z0-9_.:\-]{1,64}$")

KINDS = (Shot.KIND_VIDEO, Shot.KIND_IMAGE)
ORIGINS = (Shot.ORIGIN_COMPOSER, Shot.ORIGIN_TRAY)
PARAM_KEYS = ("duration", "resolution", "aspect_ratio", "generate_audio", "seed", "negative_prompt")
SLOT_ORDER = {ShotInput.SLOT_REFERENCE: 0, ShotInput.SLOT_FIRST_FRAME: 1, ShotInput.SLOT_LAST_FRAME: 2}

# Защита от мусорных тел: компилятор всё равно скажет too_many_inputs (>16) и
# отрежет длинные роли словами, но разбирать мегабайты мы не обязаны.
MAX_INPUT_ROWS = 64
MAX_ROLE_RAW = 500
MAX_POSITION = 10_000
MAX_NEGATIVE_RAW = 10_000
MAX_PARAM_STR = 64
MAX_PROMPT_TEXT_RAW = 100_000
MAX_TITLE = 140
MAX_SETTINGS_JSON = 20_000
MAX_MODEL_REF = 128

_DT = drf_serializers.DateTimeField()


# ---------------------------------------------------------------- мелочи

def iso(value) -> str | None:
    """Время в ISO 8601 (как у DRF): так же его принимает курсор before."""
    return _DT.to_representation(value) if value else None


def is_uid(value) -> bool:
    return isinstance(value, str) and bool(UID_RE.match(value))


def bad(field_name: str, message: str | None = None) -> StudioError:
    """400 bad_request с именем поля — чтобы по логу фронта было видно, что не так."""
    return StudioError("bad_request", message=message, field=field_name)


def parse_before(raw) -> datetime | None:
    """Курсор before=<ISO>: пусто → None, кривое → 400.

    «+» в зоне без кодирования в адресе превращается в пробел — чиним: иначе
    вторая страница истории у части клиентов молча не открылась бы.
    """
    if raw in (None, ""):
        return None
    text = str(raw).strip().replace(" ", "+")
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        value = parse_datetime(text)
    except ValueError:
        value = None
    if value is None:
        raise bad("before")
    if timezone.is_naive(value):
        value = timezone.make_aware(value, timezone.get_current_timezone())
    return value


def parse_limit(raw, *, default: int, maximum: int) -> int:
    if raw in (None, ""):
        return default
    try:
        value = int(str(raw))
    except (TypeError, ValueError):
        raise bad("limit") from None
    return max(1, min(maximum, value))


def parse_bool_flag(raw, *, default: bool = False) -> bool:
    if raw in (None, ""):
        return default
    text = str(raw).strip().lower()
    if text in ("1", "true", "yes", "on"):
        return True
    if text in ("0", "false", "no", "off"):
        return False
    raise bad("archived")


def _int_like(value) -> int | None:
    """Целое из JSON: 164 и 164.0 — да, «164», True и 1.5 — нет."""
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    return None


def parse_client_request_id(data: dict) -> str:
    cid = data.get("client_request_id")
    if not isinstance(cid, str) or not CLIENT_REQUEST_ID_RE.match(cid.strip()):
        raise bad("client_request_id")
    return cid.strip()


def parse_quoted(data: dict) -> int:
    value = _int_like(data.get("quoted_credits"))
    if value is None or value < 0:
        raise bad("quoted_credits")
    return value


def body_dict(request) -> dict:
    data = request.data
    if not isinstance(data, dict):
        raise bad("body")
    return data


# ---------------------------------------------------------------- запрос кадра

@dataclass
class ShotRequest:
    """QuoteBody после разбора (§8.3). Ровно одно из doc/text задано."""

    kind: str
    model_ref: str
    doc: object = None
    text: str | None = None
    inputs: list = field(default_factory=list)   # [{asset, slot, position, role, included}]
    params: dict = field(default_factory=dict)
    project_uid: str | None = None


def parse_inputs(raw) -> list[dict]:
    if raw is None:
        return []
    if not isinstance(raw, list) or len(raw) > MAX_INPUT_ROWS:
        raise bad("inputs")
    out = []
    for row in raw:
        if not isinstance(row, dict):
            raise bad("inputs")
        asset = row.get("asset")
        if not is_uid(asset):
            raise bad("inputs.asset")
        slot = row.get("slot", ShotInput.SLOT_REFERENCE)
        # Неизвестный слот — не 400: компилятор объяснит его словами (invalid_param).
        if not isinstance(slot, str) or not slot or len(slot) > 20:
            raise bad("inputs.slot")
        position = row.get("position", 0)
        position = 0 if position is None else _int_like(position)
        if position is None or not 0 <= position <= MAX_POSITION:
            raise bad("inputs.position")
        role = row.get("role")
        role = "" if role is None else role
        if not isinstance(role, str) or len(role) > MAX_ROLE_RAW:
            raise bad("inputs.role")
        included = row.get("included", True)
        if not isinstance(included, bool):
            raise bad("inputs.included")
        out.append({"asset": asset, "slot": slot, "position": position, "role": role,
                    "included": included})
    return out


def parse_params(raw) -> dict:
    """Только известные ключи; значения проверяет компилятор (invalid_param)."""
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise bad("params")
    out = {}
    for key in PARAM_KEYS:
        if key not in raw:
            continue
        value = raw[key]
        if value is None:
            out[key] = None
            continue
        if key == "negative_prompt":
            if not isinstance(value, str) or len(value) > MAX_NEGATIVE_RAW:
                raise bad("params.negative_prompt")
        elif isinstance(value, str):
            if len(value) > MAX_PARAM_STR:
                raise bad(f"params.{key}")
        elif not isinstance(value, (int, float, bool)):
            raise bad(f"params.{key}")
        out[key] = value
    return out


def parse_shot_request(data: dict) -> ShotRequest:
    """QuoteBody → ShotRequest или 400 bad_request."""
    kind = data.get("kind")
    if kind not in KINDS:
        raise bad("kind")
    model_ref = data.get("model")
    if not isinstance(model_ref, str) or not model_ref.strip() or len(model_ref) > MAX_MODEL_REF:
        raise bad("model")
    has_doc = data.get("prompt_doc") is not None
    has_text = data.get("prompt_text") is not None
    if has_doc == has_text:
        # Ровно одно из двух: документ редактора или текст запасной textarea.
        raise bad("prompt_doc")
    text = None
    if has_text:
        text = data.get("prompt_text")
        if not isinstance(text, str) or len(text) > MAX_PROMPT_TEXT_RAW:
            raise bad("prompt_text")
    project = data.get("project")
    if project in (None, ""):
        project = None
    elif not is_uid(project):
        raise bad("project")
    return ShotRequest(kind=kind, model_ref=model_ref.strip(), doc=data.get("prompt_doc") if has_doc else None,
                       text=text, inputs=parse_inputs(data.get("inputs")),
                       params=parse_params(data.get("params")), project_uid=project)


def request_from_shot(shot: Shot) -> ShotRequest:
    """Сохранённый кадр → тот же запрос: «Повторить» считает цену и тело заново."""
    inputs = [{"asset": i.asset.uid, "slot": i.slot, "position": i.position, "role": i.role,
               "included": i.included}
              for i in sorted(shot.inputs.all(), key=lambda i: (SLOT_ORDER.get(i.slot, 9), i.position))]
    return ShotRequest(kind=shot.kind, model_ref=shot.model_ref, doc=shot.prompt_doc, text=None,
                       inputs=inputs, params=dict(shot.params or {}), project_uid=shot.project.uid)


def parse_origin(data: dict, kind: str) -> str:
    origin = data.get("origin") or Shot.ORIGIN_COMPOSER
    if origin not in ORIGINS:
        raise bad("origin")
    if origin == Shot.ORIGIN_TRAY and kind != Shot.KIND_IMAGE:
        # «Создать картинку» для лотка — только картинка: видео в лоток не кладём.
        raise bad("origin")
    return origin


def parse_title(value) -> str:
    if value is None:
        return ""
    if not isinstance(value, str):
        raise bad("title")
    value = re.sub(r"\s+", " ", pd.normalize_text(value)).strip()
    if len(value) > MAX_TITLE:
        raise bad("title", f"Название длиннее {MAX_TITLE} символов.")
    return value


def parse_settings(value) -> dict:
    if not isinstance(value, dict):
        raise bad("settings")
    try:
        size = len(json.dumps(value, ensure_ascii=False))
    except (TypeError, ValueError):
        raise bad("settings") from None
    if size > MAX_SETTINGS_JSON:
        raise bad("settings")
    return value


def auto_title(prompt_text: str) -> str:
    """Название нового проекта — начало первого промпта (как увидит человек, с @Image N)."""
    text = re.sub(r"\s+", " ", str(prompt_text or "")).strip()
    if len(text) <= Project.AUTO_TITLE_CHARS:
        return text
    return text[: Project.AUTO_TITLE_CHARS].rstrip() + "…"


# ---------------------------------------------------------------- выход: ассет и проект

_MISSING = object()
RESULT_SOURCES = (Asset.SOURCE_GENERATED_VIDEO, Asset.SOURCE_GENERATED_IMAGE)


def asset_json(asset: Asset | None) -> dict | None:
    """AssetJSON (§8.3). url — ровно default_storage.url(file): по нему «Поделиться»
    проверяет владение (_user_owns_video сверяет с GenerationLog.result_url)."""
    if asset is None:
        return None
    return {
        "uid": asset.uid,
        "kind": asset.kind,
        "source": asset.source,
        "status": asset.status,
        "url": asset.url or None,
        "thumb_url": asset.thumb_url or None,
        "width": asset.width,
        "height": asset.height,
        "duration_s": asset.duration_s,
        "label": asset.label or "",
        "flags": asset.flags or {},
        "error_code": asset.error_code or "",
        "created_at": iso(asset.created_at),
        # Сверх §8.3: удалённый материал в старом кадре — красный чип на фронте.
        "deleted": asset.deleted_at is not None,
    }


def project_json(project: Project) -> dict:
    """ProjectJSON (§8.3). open_takes и превью — из аннотаций списка, иначе считаем тут."""
    open_n = getattr(project, "open_n", None)
    if open_n is None:
        open_n = Take.objects.filter(project=project, status__in=TAKE_OPEN).count()
    thumb = getattr(project, "thumb_path", _MISSING)
    if thumb is _MISSING:
        thumb = project_thumb_qs(project.pk).first()
    return {
        "uid": project.uid,
        "title": project.title or "",
        "kind": project.kind,
        "settings": project.settings or {},
        "is_archived": bool(project.is_archived),
        "last_activity_at": iso(project.last_activity_at),
        "thumb_url": default_storage.url(thumb) if thumb else None,
        "open_takes": int(open_n or 0),
    }



def project_thumb_qs(project_ref):
    """Превью проекта — последний готовый результат (видео или картинка) с превью."""
    return (Asset.objects.filter(project=project_ref, status=Asset.STATUS_READY,
                                 deleted_at__isnull=True, source__in=RESULT_SOURCES)
            .exclude(thumb="").order_by("-created_at").values_list("thumb", flat=True))


# ---------------------------------------------------------------- выход: дубль

class TakeContext:
    """Пачка данных для TakeLite: позиции в очереди и ETA — одним заходом на страницу."""

    def __init__(self, takes, *, now=None):
        from . import pipeline

        self.now = now or timezone.now()
        takes = list(takes)
        try:
            self.positions = pipeline.queue_positions(takes)
        except Exception:
            self.positions = {}
        self._eta: dict[tuple[str, str], int] = {}
        self._overrides = _eta_overrides({t.model_ref for t in takes})

    def eta(self, model_ref: str, kind: str) -> int:
        from . import pipeline

        key = (model_ref, kind)
        if key not in self._eta:
            try:
                self._eta[key] = int(pipeline.eta_seconds(model_ref, kind,
                                                          default=self._overrides.get(model_ref)))
            except Exception:
                self._eta[key] = int(pipeline.default_eta(model_ref, kind))
        return self._eta[key]


def _eta_overrides(model_refs) -> dict:
    """eta_s из правок админки (GPTModels.vstudio_overrides) — тот же ETA, что в caps."""
    refs = [r for r in model_refs if r]
    if not refs:
        return {}
    from ai.models import GPTModels

    from .caps import ETA_MAX_S, ETA_MIN_S

    out = {}
    for ref, ov in GPTModels.objects.filter(openrouter_id__in=refs).values_list(
            "openrouter_id", "vstudio_overrides"):
        eta = (ov or {}).get("eta_s") if isinstance(ov, dict) else None
        if isinstance(eta, int) and not isinstance(eta, bool) and ETA_MIN_S <= eta <= ETA_MAX_S:
            out[ref] = eta
    return out


def _elapsed(take: Take, now) -> int:
    """Сколько идёт дубль, с. Для running/saving — от отправки (с ней сравнивается
    ETA: медиана submitted→finished), до отправки — от создания."""
    if take.status in TAKE_OPEN:
        running = take.status in (Take.STATUS_RUNNING, Take.STATUS_SAVING)
        start = take.submitted_at if (running and take.submitted_at) else take.created_at
        end = now
    else:
        start = take.submitted_at or take.created_at
        end = take.finished_at or now
    if not start or not end:
        return 0
    return max(0, int((end - start).total_seconds()))


def _take_error(take: Take) -> dict | None:
    if take.status in TAKE_OPEN or take.status == Take.STATUS_DONE:
        return None
    if not (take.error_code or take.error):
        return None
    return {"code": take.error_code or "", "message": take.error or "",
            "input": take.error_input or None}


def take_lite(take: Take, ctx: TakeContext, *, shot_uid: str | None = None) -> dict:
    """TakeLite (§8.3)."""
    return {
        "uid": take.uid,
        "shot": shot_uid or take.shot.uid,
        "kind": take.kind,
        "status": take.status,
        "stage": take.stage or "",
        "mode": take.mode,
        "charge_state": take.charge_state,
        "credits": {"quoted": int(take.credits_quoted or 0), "reserved": int(take.credits_reserved or 0),
                    "charged": int(take.credits_charged or 0)},
        "effective": take.effective or {},
        "warnings": take.warnings or [],
        "dropped": take.dropped or [],
        "result": asset_json(take.result_asset) if take.result_asset_id else None,
        "error": _take_error(take),
        "eta_s": ctx.eta(take.model_ref, take.kind),
        "elapsed_s": _elapsed(take, ctx.now),
        "queue_position": ctx.positions.get(take.uid) if take.status == Take.STATUS_QUEUED else None,
        "created_at": iso(take.created_at),
        "submitted_at": iso(take.submitted_at),
        "finished_at": iso(take.finished_at),
    }


def take_json(take: Take, ctx: TakeContext) -> dict:
    """TakeJSON = TakeLite + «Что ушло модели» (serialized_prompt, request_body)."""
    out = take_lite(take, ctx)
    out["serialized_prompt"] = take.serialized_prompt or ""
    out["request_body"] = take.request_body or {}
    return out


def take_lites(takes, *, with_project: bool = False) -> list[dict]:
    takes = list(takes)
    ctx = TakeContext(takes)
    out = []
    for t in takes:
        row = take_lite(t, ctx)
        if with_project:
            row["project_uid"] = t.project.uid
        out.append(row)
    return out


# ---------------------------------------------------------------- выход: кадр

def input_labels(inputs) -> dict:
    """{(slot, uid): метка} по тем же правилам, что компилятор и фронт (§4.2):
    «Image N» — номер среди включённых референсов в порядке лотка, кадры — по слоту,
    выключенное — без метки."""
    rows = [{"asset": i.asset.uid, "slot": i.slot, "position": i.position, "included": i.included,
             "kind": i.asset.kind} for i in inputs]
    numbers = pd.number_refs(rows)
    frames = pd.frame_uids(rows)
    out = {}
    for i in inputs:
        uid = i.asset.uid
        if not i.included:
            label = None
        elif i.slot == ShotInput.SLOT_REFERENCE:
            label = f"Image {numbers[uid]}" if uid in numbers else None
        else:
            label = i.slot if frames.get(i.slot) == uid else None
        out[(i.slot, uid)] = label
    return out


def shot_json(shot: Shot, takes: list[dict]) -> dict:
    """ShotJSON (§8.3); takes — уже готовые TakeLite по возрастанию created_at."""
    inputs = sorted(shot.inputs.all(), key=lambda i: (SLOT_ORDER.get(i.slot, 9), i.position))
    labels = input_labels(inputs)
    model = shot.model if shot.model_id else None
    return {
        "uid": shot.uid,
        "project": shot.project.uid,
        "kind": shot.kind,
        "origin": shot.origin,
        "model": {"id": shot.model_ref, "name": model.name} if model is not None else None,
        "prompt_doc": shot.prompt_doc,
        "prompt_text": shot.prompt_text or "",
        "params": shot.params or {},
        "inputs": [{"asset": asset_json(i.asset), "slot": i.slot, "position": i.position,
                    "role": i.role or "", "included": bool(i.included),
                    "label": labels.get((i.slot, i.asset.uid))} for i in inputs],
        "forked_from": shot.forked_from.uid if shot.forked_from_id and shot.forked_from else None,
        "created_at": iso(shot.created_at),
        "takes": takes,
    }


def shots_json(shots) -> list[dict]:
    """Страница кадров с дублями: TakeLite всех дублей считаются одной пачкой."""
    shots = list(shots)
    all_takes = [t for s in shots for t in s.takes.all()]
    ctx = TakeContext(all_takes)
    out = []
    for s in shots:
        takes = sorted(s.takes.all(), key=lambda t: (t.created_at, t.pk))
        out.append(shot_json(s, [take_lite(t, ctx, shot_uid=s.uid) for t in takes]))
    return out


__all__ = [
    "UID_RE", "ShotRequest", "TakeContext", "iso", "is_uid", "bad", "parse_before", "parse_limit",
    "parse_bool_flag", "parse_client_request_id", "parse_quoted", "body_dict", "parse_inputs",
    "parse_params", "parse_shot_request",
    "request_from_shot", "parse_origin", "parse_title", "parse_settings", "auto_title",
    "asset_json", "project_json", "project_thumb_qs", "take_lite", "take_json", "take_lites",
    "input_labels", "shot_json", "shots_json",
]
