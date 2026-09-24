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

# HTTP-код только в контексте «http/status/code»: голое «402»/«429» ловилось
# внутри ID генераций и чисел в тексте ответа (gen-vid-1789…429…) и выдавало
# человеку «сервис перегружен» вместо настоящей причины.
_HTTP_402 = r"(?<![a-z])(?:http|status|code)[\s\"':=_]*402\b"
_HTTP_429 = r"(?<![a-z])(?:http|status|code)[\s\"':=_]*429\b"

# (что искать в теле ответа, без учёта регистра) → (сообщение человеку, код для фронта)
_RULES: list[tuple[str, str, str]] = [
    # \bface\b: без границ слова «face» находилось в «interface»/«surface» —
    # любая ошибка со словом interface превращалась в «фото реальных людей».
    (r"PrivacyInformation|may contain real person|real person|real people|\bfaces?\b",
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
    (r"Insufficient credits|insufficient_quota|quota|" + _HTTP_402,
     "Сервис генерации временно недоступен — мы уже знаем и чиним. "
     "Кредиты не списаны, попробуйте чуть позже.",
     "provider_out_of_credits"),
    (r"rate limit|too many requests|" + _HTTP_429 + r"|overloaded|capacity|busy",
     "Модель сейчас перегружена. Подождите минуту и попробуйте снова — кредиты не списаны.",
     "provider_busy"),
    (r"duration|resolution|aspect|unsupported|invalid (parameter|value|request)|ZodError",
     "Модель не приняла параметры видео (длительность, качество или пропорции). "
     "Выберите другие значения и попробуйте снова.",
     "bad_params"),
]

_DEFAULT = ("Не удалось запустить генерацию видео. Попробуйте ещё раз.", "provider_error")

# Коды, при которых провайдер отверг само ФОТО (модерация входа, реальное лицо,
# битый файл). Видеостудия по ним подсвечивает виноватый материал в ленте
# (Take.error_input): человек сразу видит, какую картинку заменить. Отказ по
# тексту (prompt_rejected) или по параметрам ни на какое фото не указывает.
# Точный текст отказа Seedance на реальное лицо живой пробой ещё не снят
# (P0-2 отложена) — правило выше ловит его по «real person»/PrivacyInformation.
INPUT_ERROR_CODES = frozenset({"image_real_person", "image_sensitive", "image_invalid"})


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


# --- Текстовый чат -----------------------------------------------------------
#
# Раньше любой сбой OpenRouter в чате показывался человеку как «internal_error»
# (сырой код на экране) — и лимит запросов, и кончившиеся деньги на нашем ключе,
# и слишком длинный документ выглядели одинаково. Здесь — те же идеи, что выше:
# понятная причина и совет, код — для фронта и бота.

_CONTEXT_TOO_LONG = (
    "Сообщение вместе с историей чата и документами слишком длинное для этой модели. "
    "Начните новый чат, сократите текст или выберите модель с большим контекстом.",
    "context_too_long",
)
_OUT_OF_CREDITS = (
    "Сервис временно недоступен — мы уже знаем и чиним. "
    "Кредиты не списаны, попробуйте чуть позже.",
    "provider_out_of_credits",
)
_BUSY = (
    "Модель сейчас перегружена. Подождите минуту и попробуйте снова — кредиты не списаны.",
    "provider_busy",
)
_REJECTED = (
    "Модель отказалась отвечать на этот запрос по своим правилам безопасности. "
    "Переформулируйте его — кредиты не списаны.",
    "prompt_rejected",
)
_UNAVAILABLE = (
    "Модель сейчас не отвечает. Попробуйте ещё раз или выберите другую модель — "
    "кредиты не списаны.",
    "provider_unavailable",
)
_NO_VISION = (
    "Выбранная модель не понимает изображения. Выберите модель со зрением — "
    "ChatGPT, Gemini или Claude.",
    "model_no_vision",
)
CHAT_DEFAULT = (
    "Не удалось получить ответ от модели. Попробуйте ещё раз — кредиты не списаны.",
    "internal_error",
)

_CHAT_RULES: list[tuple[str, tuple[str, str]]] = [
    # Модель без зрения, а в запросе картинка: 404 «No endpoints found that
    # support image input» — раньше, чем общее «no endpoints».
    (r"image input|support image", _NO_VISION),
    (r"maximum context length|context length|context window|context_length_exceeded|"
     r"too many tokens|token limit|prompt is too long|input is too long|"
     r"max(?:imum)?[ _]tokens?.{0,40}exceed", _CONTEXT_TOO_LONG),
    (r"insufficient credits|requires more credits|insufficient_quota|can only afford|" + _HTTP_402,
     _OUT_OF_CREDITS),
    (r"rate[ _-]?limit|too many requests|" + _HTTP_429 + r"|overloaded|at capacity", _BUSY),
    (r"moderation|flagged|content[ _-]?(?:policy|filter|management)|violat|prohibited|"
     r"harmful content|safety (?:system|filter|policy)", _REJECTED),
    (r"timed? ?out|timeout|connection (?:error|reset|aborted|refused)|no endpoints|"
     r"provider returned error|bad gateway|service unavailable|upstream|"
     r"(?<![a-z])(?:http|status|code)[\s\"':=_]*(?:502|503|504|524)\b", _UNAVAILABLE),
]

_STATUS_MAP = {402: _OUT_OF_CREDITS, 429: _BUSY, 408: _UNAVAILABLE, 413: _CONTEXT_TOO_LONG,
               502: _UNAVAILABLE, 503: _UNAVAILABLE, 504: _UNAVAILABLE, 524: _UNAVAILABLE}


def explain_chat_error(exc) -> tuple[str, str]:
    """(сообщение человеку, код) для сбоя текстового чата.

    Принимает исключение openai-SDK (у него есть status_code) или строку. Сначала
    смотрим текст — он точнее кода (404 бывает и «нет зрения», и «нет модели»),
    затем HTTP-код; всё незнакомое — общий русский текст, без деталей наружу.
    """
    try:
        text = str(exc or "")
    except Exception:
        text = ""
    for pattern, answer in _CHAT_RULES:
        if re.search(pattern, text, flags=re.IGNORECASE):
            return answer
    status = getattr(exc, "status_code", None)
    if isinstance(status, int):
        if status in _STATUS_MAP:
            return _STATUS_MAP[status]
        if status == 403:
            # OpenRouter отвечает 403, когда модерация провайдера отклонила ввод.
            return _REJECTED
        if status >= 500:
            return _UNAVAILABLE
    # Сетевые сбои SDK (APIConnectionError/APITimeoutError) без status_code.
    name = type(exc).__name__ if not isinstance(exc, str) else ""
    if name in ("APIConnectionError", "APITimeoutError", "ConnectTimeout", "ReadTimeout"):
        return _UNAVAILABLE
    return CHAT_DEFAULT
