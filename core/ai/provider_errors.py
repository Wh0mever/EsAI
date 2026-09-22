"""Отказ провайдера — человеческими словами.

Случай 21.09.2026: пользовательница шесть раз подряд получала «Не удалось
запустить генерацию. Попробуйте ещё раз» и честно пробовала ещё раз. А провайдер
все шесть раз отвечал одно и то же: «на картинке, похоже, реальный человек» —
Seedance такие фото не принимает. Скажи мы это сразу, она бы взяла другую
картинку с первой попытки.

Здесь код или текст ошибки провайдера превращается в объяснение и совет. Всё
незнакомое остаётся общим «попробуйте ещё раз».
"""
from __future__ import annotations

import re

# (что искать в теле ответа, без учёта регистра) → (сообщение человеку, код для фронта)
_RULES: list[tuple[str, str, str]] = [
    (r"PrivacyInformation|may contain real person|real person|real people|face",
     "Модель не принимает фото реальных людей. Используйте рисунок, аватар, "
     "мультяшного героя или картинку без лица — и попробуйте снова.",
     "image_real_person"),
    (r"InputImageSensitiveContentDetected|SensitiveContent|sensitive content|nsfw",
     "Модель отказалась от этой картинки: на ней что-то из запрещённого "
     "(обнажённость, насилие, кровь). Возьмите другую картинку.",
     "image_sensitive"),
    (r"InputTextSensitiveContent|OutputTextSensitiveContent|content policy|content_policy|moderation|"
     r"violat|prohibited|not allowed|unsafe",
     "Модель отказалась от этого запроса: в описании есть то, что она считает "
     "запрещённым. Перефразируйте — без насилия, взрослых тем и реальных известных людей.",
     "prompt_rejected"),
    (r"does not support (first_frame|last_frame|frame_images)|frame_images.*not support",
     "Эта модель не умеет делать видео из картинки. Уберите картинку или "
     "выберите другую модель видео.",
     "no_image_to_video"),
    (r"invalid image|image (format|size|resolution|dimension)|unsupported image|"
     r"too (large|small)|image url|failed to (download|fetch)|could not (load|fetch)",
     "Картинка не подошла: слишком большая, необычного формата или не загрузилась. "
     "Попробуйте JPG или PNG до 10 МБ.",
     "image_invalid"),
    (r"Insufficient credits|insufficient_quota|quota|402",
     "Сервис генерации временно недоступен — мы уже знаем и чиним. "
     "Кредиты не списаны, попробуйте чуть позже.",
     "provider_out_of_credits"),
    (r"rate limit|too many requests|429|overloaded|capacity|busy",
     "Модель сейчас перегружена. Подождите минуту и попробуйте снова — кредиты не списаны.",
     "provider_busy"),
    (r"duration|resolution|aspect|unsupported|invalid (parameter|value|request)|ZodError",
     "Модель не приняла параметры видео (длительность, качество или пропорции). "
     "Выберите другие значения и попробуйте снова.",
     "bad_params"),
]

_DEFAULT = ("Не удалось запустить генерацию видео. Попробуйте ещё раз.", "provider_error")


def explain_video_error(raw: str) -> tuple[str, str]:
    """(сообщение человеку, код) по тексту ответа провайдера."""
    text = str(raw or "")
    for pattern, message, code in _RULES:
        if re.search(pattern, text, flags=re.IGNORECASE):
            return message, code
    return _DEFAULT


def explain_image_error(raw: str) -> tuple[str, str]:
    """То же для картинок: у них те же причины, кроме видеопараметров."""
    message, code = explain_video_error(raw)
    if code == "provider_error":
        return "Не удалось сгенерировать изображение. Кредиты не списаны.", code
    if code == "no_image_to_video":
        return ("Эта модель не умеет работать с приложенной картинкой. Уберите её "
                "или выберите другую модель."), "no_image_input"
    if code == "bad_params":
        return "Модель не приняла параметры картинки. Попробуйте другие пропорции.", code
    return message, code
