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
        total += _reserve_for(scene, ready)
    return total
