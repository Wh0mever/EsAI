"""Цена сцены считается по той же длительности, которую снимет модель.

Мина, которую это закрывает: списание брало `preset.duration` буквально, а
генерация «примагничивает» длительность к тому, что модель умеет (Veo — 4/6/8 с,
Sora — 4/8/12). С нынешней Wan 2.7 пятисекундные сцены случайно совпадали, но при
переходе на качественную модель человек платил бы за 5 секунд, а получал 4.
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


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


def video_credits(video_model, want_duration: int, resolution: str = "720p") -> int:
    """Во сколько обойдётся видео-часть сцены.

    Тариф модели, но не ниже себестоимости у провайдера плюс маржа — та же
    граница, что у видео в чате (ai/video_cost.py). Сейчас студия снимает в
    720p, где тариф её и так покрывает; граница — страховка на случай, если в
    админке поставят другую модель, разрешение или слишком низкую цену.
    """
    seconds = effective_duration(video_model, want_duration)
    base = max(1, round(seconds * float(getattr(video_model, "markup_coefficient", 1) or 1)))
    model_id = getattr(video_model, "openrouter_id", "") or ""
    if not model_id:
        return base
    try:
        from ai.handlers import _openrouter_video_catalog
        from ai.video_cost import video_credits as cost_floor

        return max(base, cost_floor(video_model, _openrouter_video_catalog(model_id),
                                    resolution or "720p", seconds))
    except Exception:
        logger.exception("цена сцены: себестоимость модели %s не посчиталась", model_id)
        return base


def frame_credits(image_model) -> int:
    return max(1, int(float(getattr(image_model, "markup_coefficient", 1) or 1)))


def scene_video_credits(preset) -> int:
    """Видео-часть сцены — ровно то, что списывается после готового ролика.

    Ручная цена пресета — это цена всей сцены (её человек и видит), значит видео
    стоит её за вычетом кадра. Раньше ручная цена меняла только витрину, а
    списание шло по моделям: показывали одно, списывали другое.
    """
    override = getattr(preset, "credits_override", None)
    if override:
        return max(1, int(override) - frame_credits(preset.image_model))
    return video_credits(preset.video_model, preset.duration,
                         getattr(preset, "resolution", "") or "720p")


def scene_credits(preset, *, keyframe_ready: bool = False) -> int:
    """Во сколько обойдётся съёмка сцены. Одна формула на витрину, гейт и списание.

    Готовый кадр заново не рисуется, поэтому с ним платится только видео.
    """
    video = scene_video_credits(preset)
    return video if keyframe_ready else frame_credits(preset.image_model) + video


WORKING_STATES = ("new", "keyframe", "video")


def reserved_credits(user, exclude_scene_id: int | None = None) -> int:
    """Сколько кредитов уже обещано сценам этого человека, которые сейчас снимаются.

    Списание идёт по факту, в конце съёмки, а провайдеру мы платим сразу. Две
    сцены, запущенные при балансе на одну, раньше обе проходили проверку: вторая
    снималась за наш счёт и падала на списании. Теперь запуск видит, что часть
    баланса уже занята.
    """
    from .models import CartoonScene

    qs = (CartoonScene.objects.filter(project__user=user, status__in=WORKING_STATES)
          .select_related("preset__image_model", "preset__video_model"))
    if exclude_scene_id:
        qs = qs.exclude(pk=exclude_scene_id)
    total = 0
    for scene in qs:
        # На этапе видео кадр уже оплачен (или взят бесплатно из запаса).
        ready = scene.status == CartoonScene.STATUS_VIDEO or bool(scene.keyframe)
        total += scene_credits(scene.preset, keyframe_ready=ready)
    return total
