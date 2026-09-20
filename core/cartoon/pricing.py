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


def video_credits(video_model, want_duration: int) -> int:
    """Во сколько обойдётся видео-часть сцены."""
    seconds = effective_duration(video_model, want_duration)
    return max(1, round(seconds * float(getattr(video_model, "markup_coefficient", 1) or 1)))


def frame_credits(image_model) -> int:
    return max(1, int(float(getattr(image_model, "markup_coefficient", 1) or 1)))
