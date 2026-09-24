"""Реестр возможностей моделей видеостудии (спецификация §3).

Что модель умеет, складывается из двух источников:
- живой каталог OpenRouter /videos/models (длительности, качества, пропорции,
  звук, seed, passthrough-параметры) — он меняется без нас, поэтому берём его
  «как есть» через тот же кэш, что у чата (ai.handlers._openrouter_video_catalog);
- надстройка по семействам в этом файле: кадры, референсы, шаблон тега, лимиты
  промпта. Этого в каталоге нет вовсе, а ошибка тут стоит денег: провайдер либо
  отвергнет тело, либо молча проигнорирует оплаченные референсы.

Референсы у видео-модели выключены (max_image_refs = 0), пока живая проба не
подтвердила их (verified). Из админки (GPTModels.vstudio_overrides) можно только
скрыть модель, аварийно выключить референсы или включить их после пробы в
пределах лимита вендора — см. validate_overrides.

Модуль чистый: сеть трогает только catalog_spec (через кэш каталога), в БД
ничего не пишет.
"""
from __future__ import annotations

import datetime
import logging
import re
from dataclasses import dataclass
from typing import Literal

from django.conf import settings
from django.core.exceptions import ValidationError

logger = logging.getLogger(__name__)

KIND_VIDEO = "video"
KIND_IMAGE = "image"

FRAME_FIRST = "first_frame"
FRAME_LAST = "last_frame"
FRAME_ORDER = (FRAME_FIRST, FRAME_LAST)

# Ключи, которые админка может менять (§3.3). Всё остальное — только кодом.
OVERRIDE_KEYS = ("badge", "sort", "refs", "refs_verified", "max_image_refs", "eta_s")
BADGE_MAX = 40
ETA_MIN_S, ETA_MAX_S = 5, 6 * 3600

_ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

# Дата, когда референсы подтверждены боевыми генерациями (решение лида 1):
# 44 сцены мультстудии на Seedance 2.0 с input_references + first_frame, ни
# одного отката 400. Для картинок референсы давно работают в чате (FLUX) и
# мультстудии (Nano Banana) — там проба не нужна (§3.2).
SEEDANCE_20_VERIFIED = "2026-09-24"
IMAGE_REFS_VERIFIED = "2026-09-24"


@dataclass(frozen=True)
class Caps:
    """Что модель умеет в видеостудии — единственный источник для UI, цены и компилятора."""

    model: str
    kind: Literal["video", "image"]
    family: str
    name: str
    badge: str
    sort: int
    # Из живого каталога (у картинок — статично).
    durations: tuple[int, ...]
    resolutions: tuple[str, ...]
    aspect_ratios: tuple[str, ...]
    audio: bool
    seed: bool
    negative_param: str | None
    negative_slug: str | None
    # Надстройка в коде.
    frames: frozenset[str]
    vendor_max_image_refs: int
    max_image_refs: int
    frames_with_refs: Literal["soft_pin", "block", "none"]
    ref_forces_duration: int | None
    mention_template: str
    mention_style: Literal["indexed", "natural", "none"]
    prompt_soft_words: int | None
    prompt_hard_chars: int
    prompt_lang: Literal["en", "any"]
    rejects_real_faces: bool
    min_ref_px: int
    ref_aspect_range: tuple[float, float] | None
    eta_s: int
    verified: str | None
    # Сверх §3.1: как компилятор пишет заголовок привязки и кадры (§4.5).
    # Держим рядом с шаблоном тега, чтобы семейство описывалось в одном месте.
    bind_template: str | None = None
    frame_words: tuple[str, str] = ("the first frame", "the last frame")

    @property
    def negative(self) -> bool:
        return bool(self.negative_param and self.negative_slug)

    @property
    def refs_enabled(self) -> bool:
        return self.max_image_refs > 0


@dataclass(frozen=True)
class Family:
    """Надстройка семейства: то, чего нет в каталоге OpenRouter."""

    kind: str
    frames: frozenset
    vendor_max_image_refs: int
    # Сколько референсов включаем после пробы (может быть меньше, чем у вендора:
    # Nano Banana 2 держит 14, но уверенно — около 6).
    enabled_refs: int
    frames_with_refs: str
    mention_template: str
    mention_style: str
    prompt_soft_words: int | None
    prompt_hard_chars: int
    prompt_lang: str
    ref_forces_duration: int | None = None
    bind_template: str | None = None
    frame_words: tuple[str, str] = ("the first frame", "the last frame")
    rejects_real_faces: bool = False
    min_ref_px: int = 0
    ref_aspect_range: tuple[float, float] | None = None
    eta_s: int = 120
    # Негатив — только через provider.options.<slug>.parameters.<param> и только
    # если имя есть в allowed_passthrough_parameters каталога. Slug провайдера у
    # Kling и Wan не подтверждён пробой — пока None, негатив у них выключен.
    negative_param: str | None = None
    negative_slug: str | None = None
    # Если в каталоге нет длительностей — берём эти (иначе модель без выбора).
    fallback_durations: tuple[int, ...] = ()


_BOTH = frozenset({FRAME_FIRST, FRAME_LAST})
_FIRST = frozenset({FRAME_FIRST})
_NONE = frozenset()

# Таблица §3.2. Значения из документации вендоров; «после пробы» уточнит P0-2.
FAMILIES: dict[str, Family] = {
    # Seedance: шаблон тега «[Image N]» (решение лида 1), до 9 фото,
    # кадр вместе с референсами — soft pin «Image k is the first frame».
    "seedance2": Family(
        kind=KIND_VIDEO, frames=_BOTH, vendor_max_image_refs=9, enabled_refs=9,
        frames_with_refs="soft_pin", mention_template="[Image {n}]", mention_style="indexed",
        bind_template="{tag} is {who}.", prompt_soft_words=150, prompt_hard_chars=6000,
        prompt_lang="en", rejects_real_faces=True, min_ref_px=300, ref_aspect_range=(0.4, 2.5),
        eta_s=150, fallback_durations=tuple(range(4, 16))),
    "seedance25": Family(
        kind=KIND_VIDEO, frames=_BOTH, vendor_max_image_refs=30, enabled_refs=9,
        frames_with_refs="soft_pin", mention_template="[Image {n}]", mention_style="indexed",
        bind_template="{tag} is {who}.", prompt_soft_words=150, prompt_hard_chars=6000,
        prompt_lang="en", rejects_real_faces=True, min_ref_px=300, ref_aspect_range=(0.4, 2.5),
        eta_s=180, fallback_durations=tuple(range(4, 31))),
    # Veo: у индексов нет синтаксиса — пишем словами; с референсами только 8 с.
    "veo": Family(
        kind=KIND_VIDEO, frames=_BOTH, vendor_max_image_refs=3, enabled_refs=3,
        frames_with_refs="block", mention_template="reference image {n}", mention_style="natural",
        ref_forces_duration=8, frame_words=("the starting frame", "the ending frame"),
        prompt_soft_words=120, prompt_hard_chars=2500, prompt_lang="en", eta_s=120,
        negative_param="negativePrompt", negative_slug="google-vertex",
        fallback_durations=(4, 6, 8)),
    "veo_lite": Family(
        kind=KIND_VIDEO, frames=_BOTH, vendor_max_image_refs=0, enabled_refs=0,
        frames_with_refs="none", mention_template="reference image {n}", mention_style="none",
        prompt_soft_words=120, prompt_hard_chars=2500, prompt_lang="en", eta_s=90,
        negative_param="negativePrompt", negative_slug="google-vertex",
        fallback_durations=(4, 6, 8)),
    "kling": Family(
        kind=KIND_VIDEO, frames=_BOTH, vendor_max_image_refs=0, enabled_refs=0,
        frames_with_refs="none", mention_template="reference image {n}", mention_style="none",
        prompt_soft_words=150, prompt_hard_chars=2500, prompt_lang="any", eta_s=180,
        negative_param="negative_prompt", negative_slug=None, fallback_durations=(5, 10)),
    "hailuo23": Family(
        kind=KIND_VIDEO, frames=_FIRST, vendor_max_image_refs=0, enabled_refs=0,
        frames_with_refs="none", mention_template="reference image {n}", mention_style="none",
        prompt_soft_words=150, prompt_hard_chars=2000, prompt_lang="any", eta_s=150,
        fallback_durations=(6, 10)),
    "hailuo3": Family(
        kind=KIND_VIDEO, frames=_BOTH, vendor_max_image_refs=9, enabled_refs=9,
        frames_with_refs="soft_pin", mention_template="reference image {n}", mention_style="indexed",
        bind_template="{tag} is {who}.", prompt_soft_words=150, prompt_hard_chars=7000,
        prompt_lang="any", eta_s=180, fallback_durations=tuple(range(5, 16))),
    "wan27": Family(
        kind=KIND_VIDEO, frames=_BOTH, vendor_max_image_refs=5, enabled_refs=5,
        frames_with_refs="block", mention_template="Image {n}", mention_style="indexed",
        bind_template="{tag} is {who}.", prompt_soft_words=150, prompt_hard_chars=5000,
        prompt_lang="any", eta_s=150, negative_param="negative_prompt", negative_slug=None,
        fallback_durations=tuple(range(2, 11))),
    "wan30": Family(
        kind=KIND_VIDEO, frames=_FIRST, vendor_max_image_refs=0, enabled_refs=0,
        frames_with_refs="none", mention_template="Image {n}", mention_style="none",
        prompt_soft_words=150, prompt_hard_chars=5000, prompt_lang="any", eta_s=180,
        fallback_durations=tuple(range(2, 31))),
    "grok": Family(
        kind=KIND_VIDEO, frames=_FIRST, vendor_max_image_refs=7, enabled_refs=7,
        frames_with_refs="block", mention_template="<IMAGE_{n}>", mention_style="indexed",
        bind_template="{tag} is {who}.", frame_words=("the starting image", "the last frame"),
        prompt_soft_words=150, prompt_hard_chars=4000, prompt_lang="any", eta_s=90,
        fallback_durations=tuple(range(1, 16))),
    "runway": Family(
        kind=KIND_VIDEO, frames=_FIRST, vendor_max_image_refs=0, enabled_refs=0,
        frames_with_refs="none", mention_template="reference image {n}", mention_style="none",
        prompt_soft_words=150, prompt_hard_chars=1000, prompt_lang="any", eta_s=120,
        fallback_durations=(5, 10)),
    # Картинки (/images): «image N», заголовок «Image 1: Анна.».
    "nano_banana": Family(
        kind=KIND_IMAGE, frames=_NONE, vendor_max_image_refs=3, enabled_refs=3,
        frames_with_refs="none", mention_template="image {n}", mention_style="indexed",
        bind_template="{tag}: {who}.", prompt_soft_words=None, prompt_hard_chars=8000,
        prompt_lang="any", eta_s=30),
    "nano_banana_2": Family(
        kind=KIND_IMAGE, frames=_NONE, vendor_max_image_refs=14, enabled_refs=6,
        frames_with_refs="none", mention_template="image {n}", mention_style="indexed",
        bind_template="{tag}: {who}.", prompt_soft_words=None, prompt_hard_chars=8000,
        prompt_lang="any", eta_s=40),
    "flux2": Family(
        kind=KIND_IMAGE, frames=_NONE, vendor_max_image_refs=8, enabled_refs=8,
        frames_with_refs="none", mention_template="image {n}", mention_style="indexed",
        bind_template="{tag}: {who}.", prompt_soft_words=None, prompt_hard_chars=8000,
        prompt_lang="any", eta_s=30),
    "flux2_klein": Family(
        kind=KIND_IMAGE, frames=_NONE, vendor_max_image_refs=4, enabled_refs=4,
        frames_with_refs="none", mention_template="image {n}", mention_style="indexed",
        bind_template="{tag}: {who}.", prompt_soft_words=None, prompt_hard_chars=8000,
        prompt_lang="any", eta_s=20),
}

# openrouter_id → (семейство, дата пробы референсов). Точное совпадение: новая
# модель (Sora 2, Wan 3.x и т. п.) без строки здесь скрыта — код её не знает.
MODELS: dict[str, tuple[str, str | None]] = {
    "bytedance/seedance-2.0": ("seedance2", SEEDANCE_20_VERIFIED),
    "bytedance/seedance-2.0-fast": ("seedance2", None),
    "bytedance/seedance-2.0-mini": ("seedance2", None),
    "bytedance/seedance-2.5": ("seedance25", None),
    "google/veo-3.1": ("veo", None),
    "google/veo-3.1-fast": ("veo", None),
    "google/veo-3.1-lite": ("veo_lite", None),
    "kwaivgi/kling-v3.0-std": ("kling", None),
    "kwaivgi/kling-v3.0-pro": ("kling", None),
    "kwaivgi/kling-video-o1": ("kling", None),
    "minimax/hailuo-2.3": ("hailuo23", None),
    "minimax/hailuo-3": ("hailuo3", None),
    "alibaba/wan-2.7": ("wan27", None),
    "alibaba/wan-3.0": ("wan30", None),
    "alibaba/wan-3.0-prime": ("wan30", None),
    "x-ai/grok-imagine-video": ("grok", None),
    "runway/gen-4.5": ("runway", None),
    "google/gemini-2.5-flash-image": ("nano_banana", IMAGE_REFS_VERIFIED),
    "google/gemini-3.1-flash-image": ("nano_banana_2", IMAGE_REFS_VERIFIED),
    "google/gemini-3-pro-image": ("nano_banana_2", IMAGE_REFS_VERIFIED),
    "black-forest-labs/flux.2-pro": ("flux2", IMAGE_REFS_VERIFIED),
    "black-forest-labs/flux.2-flex": ("flux2", IMAGE_REFS_VERIFIED),
    "black-forest-labs/flux.2-max": ("flux2", IMAGE_REFS_VERIFIED),
    "black-forest-labs/flux.2-klein-4b": ("flux2_klein", IMAGE_REFS_VERIFIED),
}

_MISSING = object()


def lookup(model_id: str) -> tuple[str | None, str | None]:
    """openrouter_id → (семейство, verified). Неизвестная модель → (None, None).

    Суффиксы вида «:free» и «-preview» — та же модель у провайдера
    (gemini-3-pro-image-preview), поэтому их отбрасываем.
    """
    mid = str(model_id or "").strip().lower()
    if not mid:
        return None, None
    mid = mid.split(":", 1)[0]
    for candidate in (mid, mid[: -len("-preview")] if mid.endswith("-preview") else None):
        if candidate and candidate in MODELS:
            return MODELS[candidate]
    return None, None


def family_of(model_id: str) -> Family | None:
    key, _ = lookup(model_id)
    return FAMILIES.get(key) if key else None


def catalog_spec(model_id: str) -> dict:
    """Спека видео-модели из живого каталога (кэш 1 ч + последняя удачная копия).

    Тот же кэш, что у чата и цены (video_cost): цена и возможности сходятся.
    Пустой словарь — модели в каталоге нет (или каталог не ответил ни разу).
    """
    try:
        from ai.handlers import _openrouter_video_catalog

        return _openrouter_video_catalog(model_id) or {}
    except Exception:
        logger.exception("vstudio caps: каталог не прочитался для %s", model_id)
        return {}


# ---------------------------------------------------------------- каталог

def _durations(spec: dict, fam: Family) -> tuple[int, ...]:
    out = set()
    for raw in (spec.get("supported_durations") or []):
        try:
            d = int(str(raw).strip())
        except (TypeError, ValueError):
            continue
        if d > 0:
            out.add(d)
    return tuple(sorted(out)) or fam.fallback_durations


def _strings(values) -> tuple[str, ...]:
    seen: list[str] = []
    for raw in values or []:
        s = str(raw or "").strip()
        if s and s not in seen:
            seen.append(s)
    return tuple(seen)


def _frames(spec: dict, fam: Family) -> frozenset:
    """Кадры из надстройки; каталог может только сузить набор.

    В документации OpenRouter поля supported_frame_images нет (проба 9 ответит,
    есть ли оно вживую). Нет поля — верим надстройке.
    """
    raw = spec.get("supported_frame_images")
    if raw is None:
        return fam.frames
    got = {str(x).strip() for x in (raw or []) if x}
    return frozenset(fam.frames & got)


def _negative(spec: dict, fam: Family) -> tuple[str | None, str | None]:
    """Негатив — только если имя параметра есть в allowed_passthrough_parameters.

    Поле встречается и списком имён, и словарём {slug: [имена]} — во втором
    случае slug провайдера берём прямо из каталога.
    """
    param = fam.negative_param
    if not param:
        return None, None
    allowed = spec.get("allowed_passthrough_parameters")
    if isinstance(allowed, dict):
        for slug, names in allowed.items():
            if isinstance(names, (list, tuple)) and param in [str(n) for n in names]:
                return param, str(slug)
        return None, None
    if isinstance(allowed, (list, tuple)) and param in [str(n) for n in allowed]:
        return (param, fam.negative_slug) if fam.negative_slug else (None, None)
    return None, None


def _image_aspects() -> tuple[str, ...]:
    from ai.aspect import IMAGE_ASPECT_RATIOS

    return tuple(IMAGE_ASPECT_RATIOS)


# ---------------------------------------------------------------- правки из админки

def _is_int(value) -> bool:
    # bool — подкласс int, но «sort: true» — опечатка, а не число.
    return isinstance(value, int) and not isinstance(value, bool)


def _valid_date(value) -> bool:
    if not isinstance(value, str) or not _ISO_DATE.match(value):
        return False
    try:
        datetime.date.fromisoformat(value)
    except ValueError:
        return False
    return True


def _model_ref(model) -> str:
    if model is None:
        return ""
    if isinstance(model, str):
        return model
    return str(getattr(model, "openrouter_id", "") or "")


def validate_overrides(overrides, model=None) -> dict:
    """Проверить GPTModels.vstudio_overrides (белый список §3.3) и вернуть чистую копию.

    model — openrouter_id строкой или сама GPTModels: по ней узнаём лимит
    вендора. Бросает django ValidationError со списком русских сообщений —
    форма админки покажет их под полем.
    """
    if overrides is None or overrides == "":
        return {}
    if not isinstance(overrides, dict):
        raise ValidationError('Нужен JSON-объект, например {"badge": "Новинка"}.')

    errors: list[str] = []
    unknown = sorted(str(k) for k in overrides if k not in OVERRIDE_KEYS)
    if unknown:
        errors.append(f"Неизвестные ключи: {', '.join(unknown)}. "
                      f"Разрешены только: {', '.join(OVERRIDE_KEYS)}.")

    clean: dict = {}
    if "badge" in overrides:
        badge = overrides["badge"]
        if isinstance(badge, str) and len(badge.strip()) <= BADGE_MAX:
            clean["badge"] = badge.strip()
        else:
            errors.append(f"badge — строка не длиннее {BADGE_MAX} символов.")
    if "sort" in overrides:
        if _is_int(overrides["sort"]):
            clean["sort"] = overrides["sort"]
        else:
            errors.append("sort — целое число.")
    if "refs" in overrides:
        if overrides["refs"] == "off":
            clean["refs"] = "off"
        else:
            errors.append('refs принимает только значение "off" (аварийно выключить референсы).')
    if "eta_s" in overrides:
        eta = overrides["eta_s"]
        if _is_int(eta) and ETA_MIN_S <= eta <= ETA_MAX_S:
            clean["eta_s"] = eta
        else:
            errors.append(f"eta_s — целое число секунд от {ETA_MIN_S} до {ETA_MAX_S}.")

    fam = family_of(_model_ref(model))
    vendor = fam.vendor_max_image_refs if fam else None
    if "refs_verified" in overrides:
        raw = overrides["refs_verified"]
        if not _valid_date(raw):
            errors.append('refs_verified — дата живой пробы в формате "ГГГГ-ММ-ДД".')
        elif vendor == 0:
            errors.append("У этой модели вендор не заявил фото-референсов — refs_verified не применить.")
        else:
            clean["refs_verified"] = raw
    if "max_image_refs" in overrides:
        raw = overrides["max_image_refs"]
        if not (_is_int(raw) and raw >= 0):
            errors.append("max_image_refs — целое число от 0.")
        elif vendor is not None and raw > vendor:
            errors.append(f"max_image_refs — не больше лимита вендора ({vendor}).")
        else:
            clean["max_image_refs"] = raw

    if errors:
        raise ValidationError(errors)
    return clean


def _merge_overrides(model_id: str, fam: Family, verified: str | None, raw) -> dict:
    """Применить правки админки. Кривые значения игнорируются с warning в лог.

    Форма админки их не пропустит, но строку могли поправить мимо формы (shell,
    старая версия) — модель от этого не должна падать или получать лишнее.
    """
    ov = raw if isinstance(raw, dict) else {}
    for key in ov:
        if key not in OVERRIDE_KEYS:
            logger.warning("vstudio caps: %s — неизвестная правка %r проигнорирована", model_id, key)
    out: dict = {}
    badge = ov.get("badge")
    if isinstance(badge, str) and len(badge.strip()) <= BADGE_MAX:
        out["badge"] = badge.strip()
    if _is_int(ov.get("sort")):
        out["sort"] = ov["sort"]
    eta = ov.get("eta_s")
    if _is_int(eta) and ETA_MIN_S <= eta <= ETA_MAX_S:
        out["eta_s"] = eta

    vendor = fam.vendor_max_image_refs
    rv = ov.get("refs_verified")
    if rv is not None:
        if _valid_date(rv) and vendor > 0:
            verified = rv
        else:
            logger.warning("vstudio caps: %s — refs_verified=%r проигнорировано", model_id, rv)
    max_refs = 0
    if verified and vendor > 0:
        max_refs = min(fam.enabled_refs, vendor)
        want = ov.get("max_image_refs")
        if want is not None:
            if _is_int(want) and want >= 0:
                max_refs = min(want, vendor)
            else:
                logger.warning("vstudio caps: %s — max_image_refs=%r проигнорировано", model_id, want)
    if ov.get("refs") == "off":
        max_refs = 0
    out["verified"] = verified
    out["max_image_refs"] = max_refs
    return out


# ---------------------------------------------------------------- сборка

def build(model_obj, spec: dict | None = None) -> Caps | None:
    """Caps модели без проверок показа (vstudio_enabled, is_active).

    Нужна там, где модель уже выбрана раньше (повтор старого кадра), и в
    тестах. spec — спека каталога; у видео без неё возвращается None.
    """
    model_id = _model_ref(model_obj).strip()
    fam_key, verified = lookup(model_id)
    if not fam_key:
        return None
    fam = FAMILIES[fam_key]
    ov = _merge_overrides(model_id, fam, verified, getattr(model_obj, "vstudio_overrides", None))

    if fam.kind == KIND_VIDEO:
        spec = spec or {}
        if not spec:
            return None
        durations = _durations(spec, fam)
        resolutions = _strings(spec.get("supported_resolutions"))
        aspects = _strings(spec.get("supported_aspect_ratios"))
        audio = bool(spec.get("generate_audio"))
        seed = bool(spec.get("seed") or spec.get("supports_seed"))
        negative_param, negative_slug = _negative(spec, fam)
        frames = _frames(spec, fam)
    else:
        durations, resolutions = (), ()
        aspects = _image_aspects()
        audio = seed = False
        negative_param = negative_slug = None
        frames = frozenset()

    badge = ov.get("badge")
    if badge is None:
        badge = str(getattr(model_obj, "short_label", "") or "").strip()
    sort = ov.get("sort")
    if sort is None:
        try:
            sort = int(getattr(model_obj, "sort_order", 100) or 0)
        except (TypeError, ValueError):
            sort = 100

    return Caps(
        model=model_id,
        kind=fam.kind,
        family=fam_key,
        name=str(getattr(model_obj, "name", "") or model_id),
        badge=badge,
        sort=sort,
        durations=durations,
        resolutions=resolutions,
        aspect_ratios=aspects,
        audio=audio,
        seed=seed,
        negative_param=negative_param,
        negative_slug=negative_slug,
        frames=frames,
        vendor_max_image_refs=fam.vendor_max_image_refs,
        max_image_refs=ov["max_image_refs"],
        frames_with_refs=fam.frames_with_refs,
        ref_forces_duration=fam.ref_forces_duration,
        mention_template=fam.mention_template,
        mention_style=fam.mention_style,
        prompt_soft_words=fam.prompt_soft_words,
        prompt_hard_chars=fam.prompt_hard_chars,
        prompt_lang=fam.prompt_lang,
        rejects_real_faces=fam.rejects_real_faces,
        min_ref_px=fam.min_ref_px,
        ref_aspect_range=fam.ref_aspect_range,
        eta_s=ov.get("eta_s", fam.eta_s),
        verified=ov["verified"],
        bind_template=fam.bind_template,
        frame_words=fam.frame_words,
    )


def for_model(model_obj, *, spec=_MISSING) -> Caps | None:
    """Caps модели для видеостудии или None — модель скрыта.

    Скрыта, если: не vstudio_enabled или не is_active; семейство неизвестно
    коду; видео-модели нет в живом каталоге (так сама уйдёт Sora 2, которую
    снимают 24.09). spec можно передать заранее, чтобы не читать каталог дважды.
    Любой сбой — тоже None: одна сломанная модель не должна ронять список.
    """
    try:
        if model_obj is None:
            return None
        if not getattr(model_obj, "vstudio_enabled", False) or not getattr(model_obj, "is_active", False):
            return None
        model_id = _model_ref(model_obj).strip()
        fam = family_of(model_id)
        if fam is None:
            return None
        if fam.kind == KIND_VIDEO:
            if spec is _MISSING:
                spec = catalog_spec(model_id)
            if not spec:
                return None
        else:
            spec = None
        return build(model_obj, spec)
    except Exception:
        logger.exception("vstudio caps: не собрались для %s", getattr(model_obj, "openrouter_id", "?"))
        return None


# ---------------------------------------------------------------- для API

def defaults(caps: Caps) -> dict:
    """Значения по умолчанию для правой панели и для запроса без параметров."""
    if caps.kind == KIND_IMAGE:
        return {"aspect_ratio": "auto"}
    want_d = int(getattr(settings, "VIDEO_GEN_DURATION", 5) or 5)
    duration = min(caps.durations, key=lambda d: (abs(d - want_d), d)) if caps.durations else want_d
    want_r = str(getattr(settings, "VIDEO_GEN_RESOLUTION", "720p") or "720p")
    low = {r.lower(): r for r in caps.resolutions}
    resolution = low.get(want_r.lower()) or (caps.resolutions[0] if caps.resolutions else want_r)
    aspect = "16:9" if "16:9" in caps.aspect_ratios else "auto"
    return {"duration": duration, "resolution": resolution, "aspect_ratio": aspect}


def to_json(caps: Caps) -> dict:
    """Часть ModelJSON["caps"] (§8.3) — что умеет модель, в форме для фронта."""
    return {
        "durations": list(caps.durations),
        "resolutions": list(caps.resolutions),
        "aspect_ratios": list(caps.aspect_ratios),
        "audio": caps.audio,
        "seed": caps.seed,
        "negative": caps.negative,
        "frames": [f for f in FRAME_ORDER if f in caps.frames],
        "refs": {"image": caps.max_image_refs},
        "frames_with_refs": caps.frames_with_refs,
        "ref_forces_duration": caps.ref_forces_duration,
        "prompt": {"soft_words": caps.prompt_soft_words, "hard_chars": caps.prompt_hard_chars,
                   "lang": caps.prompt_lang},
        "rejects_real_faces": caps.rejects_real_faces,
        "min_ref_px": caps.min_ref_px,
        "ref_aspect_range": list(caps.ref_aspect_range) if caps.ref_aspect_range else None,
        "mention_style": caps.mention_style,
        "verified": caps.verified,
    }


__all__ = [
    "Caps", "Family", "FAMILIES", "MODELS", "OVERRIDE_KEYS", "KIND_VIDEO", "KIND_IMAGE",
    "FRAME_FIRST", "FRAME_LAST", "lookup", "family_of", "catalog_spec", "validate_overrides",
    "build", "for_model", "defaults", "to_json",
]
