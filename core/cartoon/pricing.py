"""Цена сцены считается по той же длительности, которую снимет модель.

Мина, которую это закрывает: списание брало `preset.duration` буквально, а
генерация «примагничивает» длительность к тому, что модель умеет (Veo — 4/6/8 с,
Sora — 4/8/12). С нынешней Wan 2.7 пятисекундные сцены случайно совпадали, но при
переходе на качественную модель человек платил бы за 5 секунд, а получал 4.

Два режима цен (ai/pricing.py, переключатель pricing_mode в админке):
- legacy — как было: тариф модели или «цена сцены» из админки, не ниже
  себестоимости / 0,6; ручная цена пресета; формат мультфильма цену не меняет;
- markup — кадр и видео по себестоимости с наценкой, видео — в формате
  мультфильма (квадрат у Seedance почти вдвое дешевле 16:9). Ручная цена и
  «цена сцены» — тарифы старого режима, здесь они не действуют. Себестоимость
  не посчитать — сцену не продаём (PriceUnavailable), к тарифу не откатываемся.
"""
from __future__ import annotations

import logging

from django.conf import settings

logger = logging.getLogger(__name__)

# Что уходит видеомодели вместе с промптом (services.generate_scene_video): первый
# кадр и фото героя. Модели, которые берут деньги за входные картинки (Grok),
# включают их в себестоимость.
SCENE_INPUT_IMAGES = 2


def _markup() -> bool:
    from ai.pricing import is_markup

    return is_markup()


def effective_duration(video_model, want_duration: int) -> int:
    """Сколько секунд реально снимет эта модель, если попросить want_duration."""
    want = max(1, int(want_duration or 5))
    model_id = getattr(video_model, "openrouter_id", "") or ""
    if not model_id:
        return want
    try:
        from ai.handlers import _openrouter_config, _video_model_params

        params = _video_model_params(model_id, _openrouter_config(), want, "720p")
        return max(1, int(params.get("duration") or want))
    except Exception:
        # Каталог недоступен — считаем по запрошенному: лучше честная попытка,
        # чем падение на подсчёте цены.
        logger.exception("цена сцены: длительность модели %s не выяснилась", model_id)
        return want


# Цена сцены в админке задаётся для обычной пятисекундной сцены: так её видит
# человек на карточке («200 кр · 5 с»). Сцены другой длины — пропорционально.
STUDIO_SCENE_SECONDS = 5


class _Rate:
    """Видео-модель с тарифом студии вместо тарифа из каталога моделей."""

    def __init__(self, model, per_second: float):
        self.openrouter_id = getattr(model, "openrouter_id", "") or ""
        self.markup_coefficient = per_second


def studio_scene_price() -> int:
    """Цена сцены мультфильма (5 с) из админки; 0 — считать по тарифу модели.

    Просьба владельца продукта: сцена 164 → 200 кредитов. Тариф Seedance в каталоге
    трогать нельзя — он же цена видео в чате, — поэтому у студии своя цена.
    Действует только в режиме цен legacy.
    """
    default = int(getattr(settings, "STUDIO_SCENE_CREDITS", 0) or 0)
    try:
        from adminapi.runtime import get_runtime

        return max(0, int(get_runtime("studio_scene_credits", default)))
    except Exception:
        return max(0, default)


def _shot_aspect(spec: dict, want: str | None) -> str | None:
    """Формат, в котором модель снимет: так же, как services.supported_aspect при съёмке."""
    want = str(want or "").strip()
    if not want:
        return None
    from ai.aspect import resolve

    return resolve(want, "", spec.get("supported_aspect_ratios") or []) or want


def markup_video_credits(video_model, want_duration: int, resolution: str = "720p",
                         aspect: str | None = None) -> int:
    """Видео-часть сцены в режиме markup: себестоимость ролика с наценкой.

    Длительность, качество и формат — те, что реально уйдут в съёмку, плюс
    входные картинки (SCENE_INPUT_IMAGES). Себестоимость не посчитать (модели нет
    в каталоге, каталог недоступен) — PriceUnavailable.
    """
    from ai.pricing import MODE_MARKUP, PriceUnavailable, current_config
    from ai.video_cost import video_credits as price_video

    model_id = getattr(video_model, "openrouter_id", "") or ""
    if not model_id:
        raise PriceUnavailable("", "cost_unknown")
    cfg = current_config()
    if not cfg.markup:
        cfg = cfg.with_changes(mode=MODE_MARKUP)
    seconds = effective_duration(video_model, want_duration)
    try:
        from ai.handlers import _openrouter_config, _openrouter_video_catalog, _video_model_params

        spec = _openrouter_video_catalog(model_id) or {}
        snapped = _video_model_params(model_id, _openrouter_config(), seconds,
                                      resolution or "720p").get("resolution") or resolution or "720p"
    except Exception as exc:
        logger.exception("цена сцены: каталог модели %s не прочитался", model_id)
        raise PriceUnavailable(model_id, "cost_unknown") from exc
    return price_video(video_model, spec, str(snapped), seconds, images=SCENE_INPUT_IMAGES,
                       aspect=_shot_aspect(spec, aspect), cfg=cfg)


def video_credits(video_model, want_duration: int, resolution: str = "720p",
                  per_second: float | None = None, *, aspect: str | None = None) -> int:
    """Во сколько обойдётся видео-часть сцены.

    Тариф модели (или тариф студии per_second), но не ниже себестоимости у
    провайдера плюс маржа — та же граница, что у видео в чате (ai/video_cost.py).
    Граница — страховка на случай, если в админке поставят другую модель,
    разрешение или слишком низкую цену.

    Режим markup: себестоимость с наценкой в формате aspect, тариф и per_second
    не участвуют (markup_video_credits).
    """
    if _markup():
        return markup_video_credits(video_model, want_duration, resolution, aspect)
    seconds = effective_duration(video_model, want_duration)
    rate = (float(per_second) if per_second is not None
            else float(getattr(video_model, "markup_coefficient", 1) or 1))
    base = max(1, round(seconds * rate))
    model_id = getattr(video_model, "openrouter_id", "") or ""
    if not model_id:
        return base
    try:
        from ai.handlers import _openrouter_config, _openrouter_video_catalog, _video_model_params
        from ai.video_cost import video_credits as cost_floor

        # Цена — в том качестве, в котором модель реально снимет (съёмка тоже
        # «примагничивает» разрешение к поддерживаемому): иначе 1080p в пресете
        # у модели, умеющей только 720p, стоил бы как 1080p.
        snapped = _video_model_params(model_id, _openrouter_config(), seconds,
                                      resolution or "720p").get("resolution") or resolution or "720p"
        priced = video_model if per_second is None else _Rate(video_model, rate)
        return max(base, cost_floor(priced, _openrouter_video_catalog(model_id),
                                    str(snapped), seconds))
    except Exception:
        logger.exception("цена сцены: себестоимость модели %s не посчиталась", model_id)
        return base


def frame_credits(image_model) -> int:
    """Цена одного кадра: legacy — плоская цена модели, markup — себестоимость
    картинки с наценкой (без себестоимости — прежняя цена, см. ai.pricing.image_credits)."""
    from ai.pricing import image_credits

    return image_credits(image_model)


def scene_video_credits(preset, *, aspect: str | None = None) -> int:
    """Видео-часть сцены — ровно то, что списывается после готового ролика.

    Ручная цена пресета — это цена всей сцены (её человек и видит), значит видео
    стоит её за вычетом кадра. Раньше ручная цена меняла только витрину, а
    списание шло по моделям: показывали одно, списывали другое.

    aspect — формат мультфильма (пусто — формат пресета). Влияет на цену только
    в режиме markup; там же ручная цена и «цена сцены» из админки не действуют.
    """
    if _markup():
        return video_credits(preset.video_model, preset.duration,
                             getattr(preset, "resolution", "") or "720p",
                             aspect=aspect or getattr(preset, "aspect_ratio", "") or None)
    override = getattr(preset, "credits_override", None)
    if override:
        return max(1, int(override) - frame_credits(preset.image_model))
    resolution = getattr(preset, "resolution", "") or "720p"
    scene_price = studio_scene_price()
    if scene_price:
        # Цена сцены из админки: видео = цена − кадр, за пять секунд.
        per_second = max(0.0, scene_price - frame_credits(preset.image_model)) / STUDIO_SCENE_SECONDS
        return video_credits(preset.video_model, preset.duration, resolution, per_second=per_second)
    return video_credits(preset.video_model, preset.duration, resolution)


def scene_credits(preset, *, keyframe_ready: bool = False, aspect: str | None = None) -> int:
    """Во сколько обойдётся съёмка сцены. Одна формула на витрину, гейт и списание.

    Готовый кадр заново не рисуется, поэтому с ним платится только видео.
    В режиме markup без себестоимости — PriceUnavailable (гейт отвечает отказом).
    """
    video = scene_video_credits(preset, aspect=aspect)
    return video if keyframe_ready else frame_credits(preset.image_model) + video


def scene_credits_or_none(preset, *, keyframe_ready: bool = False, aspect: str | None = None) -> int | None:
    """Цена сцены для показа: None — цены сейчас нет (режим markup, себестоимость
    неизвестна). Гейт и списание зовут scene_credits и получают отказ."""
    from ai.pricing import PriceUnavailable

    try:
        return scene_credits(preset, keyframe_ready=keyframe_ready, aspect=aspect)
    except PriceUnavailable:
        return None


def scene_sample(video_model, frame_model, *, seconds: int = 5, resolution: str = "720p",
                 aspect: str = "16:9", cfg=None):
    """Сцена на этой видеомодели в обоих режимах — для превью цен (админка,
    manage.py price_preview). Кадр + видео, без ручной цены пресета.

    Возвращает ai.pricing.Sample(kind="cartoon"). flags: no_cost — у видео нет
    себестоимости (в markup сцена не продаётся); frame_no_cost — у кадра нет
    себестоимости (прежняя цена); estimate — себестоимость кадра задана в
    «Моделях» по прайсу; floor — наценка видеомодели ниже порога.
    """
    from types import SimpleNamespace

    from ai import pricing
    from ai.video_cost import provider_cost_usd

    cfg = cfg or pricing.current_config()
    preset = SimpleNamespace(video_model=video_model, image_model=frame_model, duration=seconds,
                             resolution=resolution, aspect_ratio=aspect, credits_override=None)
    with pricing.override_config(cfg.with_changes(mode=pricing.MODE_LEGACY)):
        legacy = scene_credits(preset, aspect=aspect)
    flags = []
    markup_cfg = cfg.with_changes(mode=pricing.MODE_MARKUP)
    with pricing.override_config(markup_cfg):
        try:
            markup = scene_credits(preset, aspect=aspect)
        except pricing.PriceUnavailable:
            markup = None
            flags.append("no_cost")
    if pricing.floor_binds(video_model, cfg):
        flags.append("floor")
    frame = pricing.image_price(frame_model, cfg=markup_cfg)
    if frame.source == "no_cost":
        flags.append("frame_no_cost")
    if frame.cost_usd is not None:
        flags.append("estimate")

    real_seconds, real_res, spec = effective_duration(video_model, seconds), resolution, {}
    model_id = getattr(video_model, "openrouter_id", "") or ""
    try:
        from ai.handlers import _openrouter_config, _openrouter_video_catalog, _video_model_params

        spec = _openrouter_video_catalog(model_id) or {}
        real_res = str(_video_model_params(model_id, _openrouter_config(), real_seconds,
                                           resolution)["resolution"])
    except Exception:
        logger.exception("превью цены сцены: каталог модели %s не прочитался", model_id)
    shot_aspect = _shot_aspect(spec, aspect) or aspect
    video_cost = pricing.to_cost(provider_cost_usd(spec, real_res, real_seconds, images=SCENE_INPUT_IMAGES,
                                                   aspect=shot_aspect))
    cost = None if video_cost is None else video_cost + (frame.cost_usd or 0)
    shape = {"seconds": real_seconds, "resolution": real_res, "aspect": shot_aspect}
    return pricing.Sample("cartoon", shape, cost, legacy, markup, tuple(flags))


# ---------------------------------------------------------------- док: модель, качество, длительность
#
# Человек выбирает модель, качество и длительность в доке мультстудии (BUILD_C).
# Настройки живут на мультфильме (и длительность — ещё и на сцене); пусто —
# как в пресете сцены, то есть как было до дока (старые мультфильмы и бот).

STUDIO_ASPECTS = ("16:9", "9:16", "1:1")

# Семейства vstudio/caps.py, которые предлагает мультстудия: всё, что шлёт сцена
# (первый кадр, фото героя, звук, 16:9 / 9:16 / 1:1), у них есть. Veo (4/6/8 с,
# без 1:1), Hailuo (6/10 с) и Kling (без звука) потребовали бы своих ограничений.
CARTOON_FAMILIES = ("seedance2", "seedance25")
# Порядок в доке: от дешёвой к дорогой.
MODEL_ORDER = ("bytedance/seedance-2.0-mini", "bytedance/seedance-2.0-fast",
               "bytedance/seedance-2.0", "bytedance/seedance-2.5")
# Короткие имена для кнопки дока — названия продуктов, не переводятся.
SHORT_NAMES = {
    "bytedance/seedance-2.0-mini": "Seedance Mini",
    "bytedance/seedance-2.0-fast": "Seedance Fast",
    "bytedance/seedance-2.0": "Seedance 2.0",
    "bytedance/seedance-2.5": "Seedance 2.5",
}

# Что получают новые мультфильмы (runtime, «Настройки» админки). Mini 480p — самая
# дешёвая сцена (просьба клиента 15.10); пока строки Mini нет или она выключена,
# новые мультфильмы молча снимаются как в пресете.
KEY_DEFAULT_MODEL = "cartoon_default_model"
KEY_DEFAULT_RESOLUTION = "cartoon_default_resolution"
KEY_DEFAULT_DURATION = "cartoon_default_duration"
DEFAULT_KEYS = (KEY_DEFAULT_MODEL, KEY_DEFAULT_RESOLUTION, KEY_DEFAULT_DURATION)
CODE_DEFAULT_MODEL = "bytedance/seedance-2.0-mini"
CODE_DEFAULT_RESOLUTION = "480p"
CODE_DEFAULT_DURATION = 5
MAX_DURATION = 60

# Высота кадра — чтобы «ближайшее качество» было ближайшим по картинке.
_RES_HEIGHT = {"1k": 1080, "2k": 1440, "4k": 2160}


def _model_id(model) -> str:
    return str(getattr(model, "openrouter_id", "") or "").strip()


def _family(model_id: str) -> str | None:
    from vstudio.caps import lookup

    return lookup(model_id)[0]


def cartoon_family(model_id: str) -> bool:
    """Знает ли мультстудия эту модель (Seedance 2.0 Mini / Fast / 2.0 / 2.5)."""
    return _family(model_id) in CARTOON_FAMILIES


def is_offered(model) -> bool:
    """Предлагается ли модель в доке.

    Активная строка «Моделей» из семейств Seedance (vstudio/caps.py), видео:
    этап мультстудии «Видео» или категория «Видео». Второе — потому что
    «Добавить модель» заводит строку без этапа, и владелец не должен помнить
    про ещё одну галочку, чтобы Mini появилась в мультстудии.
    """
    if model is None or not getattr(model, "is_active", False):
        return False
    if not cartoon_family(_model_id(model)):
        return False
    return (getattr(model, "cartoon_stage", "") == "video"
            or getattr(model, "category", "") == "video")


def _order_key(model) -> tuple:
    mid = _model_id(model).lower().split(":", 1)[0]
    if mid.endswith("-preview"):
        mid = mid[: -len("-preview")]
    rank = MODEL_ORDER.index(mid) if mid in MODEL_ORDER else len(MODEL_ORDER)
    return (rank, int(getattr(model, "sort_order", 100) or 0), getattr(model, "pk", 0) or 0)


def offered_models() -> list:
    """Модели дока в порядке Mini, Fast, 2.0, 2.5 (остальные семейства — следом)."""
    from django.db.models import Q

    from ai.models import GPTModels

    rows = GPTModels.objects.filter(is_active=True).filter(Q(cartoon_stage="video") | Q(category="video"))
    return sorted((m for m in rows if is_offered(m)), key=_order_key)


def short_name(model) -> str:
    mid = _model_id(model)
    return SHORT_NAMES.get(mid) or str(getattr(model, "name", "") or mid)


def model_spec(model, memo: dict | None = None) -> dict:
    """Спека модели из каталога OpenRouter (кэш 1 ч). memo — на один запрос."""
    mid = _model_id(model)
    if not mid:
        return {}
    if memo is not None and ("spec", mid) in memo:
        return memo[("spec", mid)]
    try:
        from ai.handlers import _openrouter_video_catalog

        spec = _openrouter_video_catalog(mid) or {}
    except Exception:
        logger.exception("мультстудия: каталог модели %s не прочитался", mid)
        spec = {}
    if memo is not None:
        memo[("spec", mid)] = spec
    return spec


class ModelCaps:
    """Что модель умеет для мультстудии: из живого каталога OpenRouter."""

    __slots__ = ("durations", "resolutions", "aspects")

    def __init__(self, durations, resolutions, aspects):
        self.durations = tuple(durations)
        self.resolutions = tuple(resolutions)
        self.aspects = tuple(aspects)


def model_caps(model, memo: dict | None = None) -> ModelCaps | None:
    """Длительности, качества и форматы (из 16:9 / 9:16 / 1:1). None — каталог не знает модель."""
    spec = model_spec(model, memo)
    if not spec:
        return None
    durations = sorted({int(str(d).strip()) for d in (spec.get("supported_durations") or [])
                        if str(d).strip().isdigit() and int(str(d).strip()) > 0})
    if not durations:
        from vstudio.caps import family_of

        fam = family_of(_model_id(model))
        durations = list(fam.fallback_durations) if fam else []
    resolutions = []
    for raw in spec.get("supported_resolutions") or []:
        value = str(raw or "").strip()
        if value and value not in resolutions:
            resolutions.append(value)
    allowed = [str(a) for a in (spec.get("supported_aspect_ratios") or []) if a]
    aspects = [a for a in STUDIO_ASPECTS if not allowed or a in allowed]
    return ModelCaps(durations, resolutions, aspects)


def _height(resolution: str) -> int:
    value = str(resolution or "").strip().lower()
    if value in _RES_HEIGHT:
        return _RES_HEIGHT[value]
    digits = value[:-1] if value.endswith("p") else value
    return int(digits) if digits.isdigit() else 0


def clamp_duration(durations, want) -> int:
    """Ближайшая длительность, которую модель снимает; при равенстве — короче (дешевле)."""
    want = max(1, int(want or CODE_DEFAULT_DURATION))
    if not durations:
        return want
    return min(durations, key=lambda d: (abs(d - want), d))


def clamp_resolution(resolutions, want: str) -> str:
    """То же качество (без регистра) или ближайшее по высоте кадра; при равенстве — ниже."""
    want = str(want or "720p")
    if not resolutions:
        return want
    exact = next((r for r in resolutions if r.lower() == want.lower()), None)
    if exact:
        return exact
    target = _height(want) or 720
    return min(resolutions, key=lambda r: (abs(_height(r) - target), _height(r)))


def find_resolution(resolutions, want) -> str | None:
    """Качество из списка модели без учёта регистра («4k» → «4K») или None."""
    want = str(want or "").strip().lower()
    return next((r for r in resolutions if r.lower() == want), None) if want else None


class ShotConfig:
    """Чем снимется сцена: модель, качество, длительность и формат.

    resolution и duration уже «примагничены» к тому, что модель умеет — это
    ровно то, что уйдёт в съёмку и в цену. preset_default — совпадает с
    собственными настройками пресета (так снимали до дока: в режиме legacy
    тогда действует и ручная цена пресета). snapshot — прочитано из снимка
    сцены (pricing.snapshot_fields), а не из текущих настроек.
    """

    __slots__ = ("model", "resolution", "duration", "aspect", "preset_default", "model_available",
                 "snapshot", "credits_planned", "video_credits")

    def __init__(self, model, resolution: str, duration: int, aspect: str, *, preset_default: bool,
                 model_available: bool = True, snapshot: bool = False, credits_planned=None,
                 video_credits=None):
        self.model = model
        self.resolution = resolution
        self.duration = int(duration)
        self.aspect = aspect
        self.preset_default = preset_default
        self.model_available = model_available
        self.snapshot = snapshot
        self.credits_planned = credits_planned
        self.video_credits = video_credits

    @property
    def model_id(self) -> str:
        return _model_id(self.model)

    def key(self) -> tuple:
        return (self.model_id, self.resolution, self.duration, self.aspect)

    def to_json(self) -> dict:
        return {"video_model": self.model_id or None,
                "model_name": short_name(self.model) if self.model is not None else "",
                "resolution": self.resolution, "duration": self.duration,
                "aspect_ratio": self.aspect}

    def __repr__(self) -> str:
        return f"ShotConfig({self.key()}, preset_default={self.preset_default}, snapshot={self.snapshot})"


def _snap(model, resolution: str, duration: int, memo: dict | None = None) -> tuple[str, int]:
    caps = model_caps(model, memo)
    if caps is None:
        return str(resolution or "720p"), max(1, int(duration or CODE_DEFAULT_DURATION))
    return clamp_resolution(caps.resolutions, resolution), clamp_duration(caps.durations, duration)


def resolve_config(preset, *, model=None, resolution=None, duration=None, aspect=None,
                   memo: dict | None = None) -> ShotConfig:
    """Чем снимется сцена этого пресета при таких настройках дока.

    Пустое значение — значение пресета. Модель, которой больше нет в доке
    (выключили), заменяется моделью пресета: model_available=False, док
    покажет это человеку. Качество и длительность примагничиваются к модели.
    """
    chosen = model if (model is not None and is_offered(model)) else None
    video_model = chosen or preset.video_model
    want_res = resolution or getattr(preset, "resolution", "") or "720p"
    want_dur = duration or getattr(preset, "duration", None) or CODE_DEFAULT_DURATION
    res, dur = _snap(video_model, want_res, want_dur, memo)
    own_res, own_dur = (res, dur)
    if chosen is not None or resolution or duration:
        own_res, own_dur = _snap(preset.video_model, getattr(preset, "resolution", "") or "720p",
                                 getattr(preset, "duration", None) or CODE_DEFAULT_DURATION, memo)
    preset_default = (getattr(video_model, "pk", None) == getattr(preset, "video_model_id", None)
                      and res == own_res and dur == own_dur)
    return ShotConfig(video_model, res, dur, aspect or getattr(preset, "aspect_ratio", "") or "16:9",
                      preset_default=preset_default,
                      model_available=model is None or chosen is not None)


def scene_config(scene, memo: dict | None = None) -> ShotConfig:
    """Текущие настройки сцены: для «Снять» сейчас и для цены в ленте.

    Длительность сцены, иначе мультфильма, иначе пресета; модель и качество —
    мультфильма, иначе пресета; формат — мультфильма.
    """
    project = scene.project
    return resolve_config(scene.preset, model=project.video_model if project.video_model_id else None,
                          resolution=project.resolution or None,
                          duration=scene.duration or project.duration or None,
                          aspect=project.aspect_ratio or "16:9", memo=memo)


def has_snapshot(scene) -> bool:
    return scene.credits_planned is not None and bool(scene.shot_duration)


def shot_config(scene, memo: dict | None = None) -> ShotConfig:
    """Чем снимается (или снята) сцена: снимок, сделанный при «Снять».

    Для задачи съёмки (модель, качество, длительность, формат), значка снятой
    сцены и длины реплик. Снимка нет — сцену поставили или сняли до дока: тогда
    её снимали по пресету в формате мультфильма, так и считаем (а не по доку,
    который могли поменять потом). Никогда не бросает.
    """
    if not has_snapshot(scene):
        return resolve_config(scene.preset, aspect=scene.project.aspect_ratio or "16:9", memo=memo)
    preset = scene.preset
    model = scene.shot_model if scene.shot_model_id else preset.video_model
    res = scene.shot_resolution or getattr(preset, "resolution", "") or "720p"
    dur = int(scene.shot_duration)
    own_res, own_dur = _snap(preset.video_model, getattr(preset, "resolution", "") or "720p",
                             getattr(preset, "duration", None) or CODE_DEFAULT_DURATION, memo)
    preset_default = (getattr(model, "pk", None) == preset.video_model_id
                      and res == own_res and dur == own_dur)
    return ShotConfig(model, res, dur, scene.shot_aspect or scene.project.aspect_ratio or "16:9",
                      preset_default=preset_default, snapshot=True,
                      credits_planned=scene.credits_planned, video_credits=scene.shot_video_credits)


def scene_duration(scene) -> int:
    """Длительность сцены в секундах: снятой или запущенной — по снимку, иначе по доку.

    Для озвучки (длина реплик) и таймлайна."""
    working_or_shot = scene.status in WORKING_STATES or scene.status == "ready"
    return (shot_config(scene) if working_or_shot else scene_config(scene)).duration


class ScenePrice:
    """Цена сцены: кадр и видео, каждое округлено отдельно (PLAN §2.4)."""

    __slots__ = ("frame", "video")

    def __init__(self, frame: int, video: int):
        self.frame = int(frame)
        self.video = int(video)

    @property
    def total(self) -> int:
        return self.frame + self.video

    def __repr__(self) -> str:
        return f"ScenePrice(frame={self.frame}, video={self.video})"


def _legacy_video_part(preset, cfg: ShotConfig) -> int:
    """legacy: сегодняшняя формула для выбранных модели, качества и длительности."""
    if cfg.preset_default:
        # Настройки пресета: ровно прежний путь, с ручной ценой и «ценой сцены».
        return scene_video_credits(preset, aspect=cfg.aspect)
    scene_price_rt = studio_scene_price()
    if scene_price_rt:
        per_second = max(0.0, scene_price_rt - frame_credits(preset.image_model)) / STUDIO_SCENE_SECONDS
        return video_credits(cfg.model, cfg.duration, cfg.resolution, per_second=per_second)
    return video_credits(cfg.model, cfg.duration, cfg.resolution)


def config_price(preset, cfg: ShotConfig, *, keyframe_ready: bool = False) -> ScenePrice:
    """Цена сцены этого пресета при этих настройках. markup без себестоимости — PriceUnavailable."""
    if _markup():
        video = video_credits(cfg.model, cfg.duration, cfg.resolution, aspect=cfg.aspect)
    else:
        video = _legacy_video_part(preset, cfg)
    return ScenePrice(0 if keyframe_ready else frame_credits(preset.image_model), video)


def _table_video_part(preset, cfg: ShotConfig, spec: dict, pricing_cfg) -> int:
    """Видео-часть клетки таблицы цен: та же формула, что config_price, но по уже
    прочитанной спеке. В таблице только то, что модель умеет, поэтому
    «примагничивать» нечего, а сотни клеток не ходят в каталог по три раза.
    Сверку с config_price держит тест (tests_dock_api)."""
    from ai.video_cost import video_credits as price_video

    if pricing_cfg.markup:
        return price_video(cfg.model, spec, cfg.resolution, cfg.duration, images=SCENE_INPUT_IMAGES,
                           aspect=_shot_aspect(spec, cfg.aspect), cfg=pricing_cfg)
    if cfg.preset_default:
        return scene_video_credits(preset, aspect=cfg.aspect)
    scene_price_rt = studio_scene_price()
    per_second = None
    if scene_price_rt:
        per_second = max(0.0, scene_price_rt - frame_credits(preset.image_model)) / STUDIO_SCENE_SECONDS
    rate = per_second if per_second is not None else float(getattr(cfg.model, "markup_coefficient", 1) or 1)
    base = max(1, round(cfg.duration * rate))
    if not cfg.model_id:
        return base
    try:
        priced = cfg.model if per_second is None else _Rate(cfg.model, rate)
        return max(base, price_video(priced, spec, cfg.resolution, cfg.duration))
    except Exception:
        logger.exception("цена сцены: себестоимость модели %s не посчиталась", cfg.model_id)
        return base


def price_table(preset, model, caps: ModelCaps, aspect: str, *, memo: dict | None = None) -> dict | None:
    """{качество: {секунды: цена СЦЕНЫ}} для дока: кадр + видео, формат aspect.

    preset — «типичная сцена» (reference_preset): от неё модель кадра. None —
    в markup у модели нет себестоимости (как price_table видео: вся таблица).
    """
    from ai.pricing import PriceUnavailable, current_config

    pricing_cfg = current_config()
    spec = model_spec(model, memo)
    frame = frame_credits(preset.image_model)
    table: dict = {}
    try:
        for res in caps.resolutions:
            row = {}
            for seconds in caps.durations:
                cfg = resolve_config(preset, model=model, resolution=res, duration=seconds, aspect=aspect,
                                     memo=memo)
                row[str(seconds)] = frame + _table_video_part(preset, cfg, spec, pricing_cfg)
            table[str(res)] = row
    except PriceUnavailable:
        return None
    return table


def scene_price(preset, *, model, resolution, duration, aspect, keyframe_ready: bool = False) -> int:
    """Во сколько обойдётся сцена этого пресета на выбранных модели/качестве/длительности.

    Одна формула на витрину, док, ленту, гейт «Снять» и списание (через снимок):
    - markup — кадр (0, если готов) + себестоимость видео с наценкой в формате aspect;
      себестоимости нет — PriceUnavailable;
    - legacy — сегодняшняя формула для выбранной модели; совпали с пресетом —
      ровно прежний путь (с ручной ценой пресета).
    Пустые model/resolution/duration — значения пресета.
    """
    cfg = resolve_config(preset, model=model, resolution=resolution, duration=duration, aspect=aspect)
    return config_price(preset, cfg, keyframe_ready=keyframe_ready).total


def price_or_none(preset, cfg: ShotConfig, *, keyframe_ready: bool = False,
                  memo: dict | None = None) -> ScenePrice | None:
    """Цена для показа: None — цены сейчас нет (markup без себестоимости). memo — кэш на запрос."""
    from ai.pricing import PriceUnavailable

    key = None
    if memo is not None:
        manual = bool(cfg.preset_default and getattr(preset, "credits_override", None))
        key = ("price", cfg.key(), cfg.preset_default, getattr(preset, "image_model_id", None),
               preset.pk if manual else None, bool(keyframe_ready))
        if key in memo:
            return memo[key]
    try:
        price = config_price(preset, cfg, keyframe_ready=keyframe_ready)
    except PriceUnavailable:
        price = None
    if key is not None:
        memo[key] = price
    return price


def snapshot_fields(cfg: ShotConfig, price: ScenePrice, *, keyframe_ready: bool) -> dict:
    """Поля снимка для условного UPDATE при «Снять» (views._queue_render).

    credits_planned — то, что человек видел на кнопке; shot_video_credits — его
    видео-часть: её спишет готовый ролик, а резерв после кадра держит только её.
    """
    planned = price.video if keyframe_ready else price.total
    return {"shot_model": cfg.model, "shot_resolution": cfg.resolution, "shot_duration": cfg.duration,
            "shot_aspect": cfg.aspect, "credits_planned": planned, "shot_video_credits": price.video}


def shot_video_credits(scene, cfg: ShotConfig | None = None) -> int:
    """Сколько спишет готовый ролик сцены: видео-часть цены из снимка.

    Снимка нет (сцену поставили до снимков) — по пресету в формате мультфильма,
    как раньше; в markup без себестоимости тогда PriceUnavailable.
    """
    if has_snapshot(scene) and scene.shot_video_credits is not None:
        return int(scene.shot_video_credits)
    cfg = cfg or shot_config(scene)
    return config_price(scene.preset, cfg, keyframe_ready=True).video


# ---------------------------------------------------------------- настройки новых мультфильмов

def default_settings_raw() -> dict:
    """Что задано в админке (или в коде): {"model", "resolution", "duration"}."""
    from adminapi.runtime import get_runtime

    model = str(get_runtime(KEY_DEFAULT_MODEL, CODE_DEFAULT_MODEL) or "").strip() or CODE_DEFAULT_MODEL
    resolution = (str(get_runtime(KEY_DEFAULT_RESOLUTION, CODE_DEFAULT_RESOLUTION) or "").strip()
                  or CODE_DEFAULT_RESOLUTION)
    try:
        duration = int(get_runtime(KEY_DEFAULT_DURATION, CODE_DEFAULT_DURATION))
    except (TypeError, ValueError):
        duration = CODE_DEFAULT_DURATION
    return {"model": model, "resolution": resolution, "duration": duration}


def new_project_settings(memo: dict | None = None) -> tuple:
    """(модель, качество, длительность) для нового мультфильма или (None, None, None).

    Только если строка модели активна, предлагается в доке и умеет это качество
    и длительность. Иначе — молча «как в пресете»: прод продолжает снимать, пока
    владелец не добавит Mini через «Добавить модель».
    """
    from ai.models import GPTModels

    raw = default_settings_raw()
    model = GPTModels.objects.filter(openrouter_id=raw["model"]).first()
    if not is_offered(model):
        return None, None, None
    caps = model_caps(model, memo)
    res = find_resolution(caps.resolutions, raw["resolution"]) if caps else None
    if caps is None or res is None or raw["duration"] not in caps.durations:
        return None, None, None
    return model, res, raw["duration"]


def validate_defaults(values: dict) -> dict:
    """Проверить настройки по умолчанию для админки. {"model","resolution","duration"} → то же, чистое.

    Модель — только из семейств дока (её строки может ещё не быть: владелец
    заведёт её позже). Если строка есть и каталог её знает — качество и
    длительность сверяются с моделью. ValueError — русский текст для формы.
    """
    from ai.models import GPTModels

    model_id = str(values.get("model") or "").strip()
    if not model_id or len(model_id) > 128 or not cartoon_family(model_id):
        raise ValueError("Модель мультстудии — одна из Seedance: 2.0 Mini, 2.0 Fast, 2.0 или 2.5")
    resolution = str(values.get("resolution") or "").strip()
    if not resolution or len(resolution) > 8 or not _height(resolution):
        raise ValueError("Качество — например 480p или 720p")
    raw_duration = values.get("duration")
    if isinstance(raw_duration, bool):
        raise ValueError("Длительность — целое число секунд")
    try:
        duration = int(str(raw_duration).strip())
    except (TypeError, ValueError):
        raise ValueError("Длительность — целое число секунд")
    if not 1 <= duration <= MAX_DURATION:
        raise ValueError(f"Длительность — от 1 до {MAX_DURATION} секунд")
    model = GPTModels.objects.filter(openrouter_id=model_id).first()
    caps = model_caps(model) if model is not None else None
    if caps is not None:
        found = find_resolution(caps.resolutions, resolution)
        if found is None:
            raise ValueError(resolution_error(model, caps, resolution))
        resolution = found
        if duration not in caps.durations:
            raise ValueError(duration_error(model, caps))
    return {"model": model_id, "resolution": resolution, "duration": duration}


def duration_error(model, caps: ModelCaps) -> str:
    durations = list(caps.durations)
    name = short_name(model)
    if not durations:
        return f"{name}: длительность сейчас не проверить — попробуйте позже"
    if durations == list(range(durations[0], durations[-1] + 1)):
        return f"{name} снимает от {durations[0]} до {durations[-1]} секунд"
    return f"{name} снимает {', '.join(str(d) for d in durations)} секунд"


def resolution_error(model, caps: ModelCaps, resolution: str) -> str:
    return (f"{short_name(model)} не снимает в качестве {resolution}. "
            f"Доступно: {', '.join(caps.resolutions)}")


def reference_preset(memo: dict | None = None):
    """Пресет «типичной сцены»: служебный пресет своих сцен или первая сцена с превью
    (та же, с которой custom_base_preset копирует модели).

    По нему док показывает модель мультфильма без своих настроек, а список
    моделей — цену кадра. None — библиотека пуста.
    """
    from .models import CartoonPreset
    from .services import CUSTOM_PRESET_SLUG

    if memo is not None and "reference_preset" in memo:
        return memo["reference_preset"]
    qs = CartoonPreset.objects.select_related("image_model", "video_model")
    preset = (qs.filter(slug=CUSTOM_PRESET_SLUG).first()
              or qs.filter(is_active=True).exclude(preview_video="").order_by("id").first())
    if memo is not None:
        memo["reference_preset"] = preset
    return preset


# ---------------------------------------------------------------- резерв

WORKING_STATES = ("new", "keyframe", "video")


def _reserve_for(scene, keyframe_ready: bool) -> int:
    from ai.pricing import MODE_LEGACY, PriceUnavailable, override_config

    aspect = scene.project.aspect_ratio
    try:
        return scene_credits(scene.preset, keyframe_ready=keyframe_ready, aspect=aspect)
    except PriceUnavailable:
        # Сцена уже снимается, а цены сейчас нет (каталог пропал на ходу). Резерв
        # не обнуляем — иначе баланс ушёл бы на другие траты: держим прежнюю цену,
        # она не ниже цены по наценке.
        logger.warning("резерв сцены %s: цены по себестоимости нет, держим прежнюю", scene.pk)
        with override_config(mode=MODE_LEGACY):
            return scene_credits(scene.preset, keyframe_ready=keyframe_ready, aspect=aspect)


def reserved_credits(user, exclude_scene_id: int | None = None) -> int:
    """Сколько кредитов уже обещано сценам этого человека, которые сейчас снимаются.

    Списание идёт по факту, в конце съёмки, а провайдеру мы платим сразу. Две
    сцены, запущенные при балансе на одну, раньше обе проходили проверку: вторая
    снималась за наш счёт и падала на списании. Теперь запуск видит, что часть
    баланса уже занята.

    Сцена со снимком держит цену запуска (credits_planned), а не живую цену:
    смена дока, наценки или курса во время съёмки резерв не двигает. Сцены без
    снимка (поставлены до него) считаются по-старому.
    """
    from .models import CartoonScene

    qs = (CartoonScene.objects.filter(project__user=user, status__in=WORKING_STATES)
          .select_related("project", "preset__image_model", "preset__video_model"))
    if exclude_scene_id:
        qs = qs.exclude(pk=exclude_scene_id)
    total = 0
    for scene in qs:
        # На этапе видео кадр уже оплачен (или взят бесплатно из запаса).
        ready = scene.status == CartoonScene.STATUS_VIDEO or bool(scene.keyframe)
        if has_snapshot(scene):
            video = scene.shot_video_credits
            total += int(video if ready and video is not None else scene.credits_planned)
            continue
        total += _reserve_for(scene, ready)
    return total
