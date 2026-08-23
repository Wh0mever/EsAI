"""Пропорции кадра для генерации видео и изображений.

Просьба клиента: выбор 16:9 / 9:16 и прочего должен быть везде — и в видео, и
в картинках, «и даже с промпта».

Что проверено вживую на API OpenRouter (20.08.2026):
  * POST /videos принимает `aspect_ratio` из набора
    16:9, 9:16, 1:1, 4:3, 3:4, 3:2, 2:3, 21:9, 9:21
    (список пришёл из ответа-валидации самого API);
  * POST /images принимает `aspect_ratio` и ДЕЙСТВИТЕЛЬНО меняет размер:
    без параметра 1024x1024, с 16:9 — 1824x1024, с 9:16 — 1024x1824;
  * каталог /images/models пропорции по моделям НЕ отдаёт, поэтому для
    картинок берём общий список ходовых значений;
  * image-модели, работающие через chat-completions (Nano Banana), параметра
    не имеют вовсе — там пропорция дописывается в промпт.
"""
from __future__ import annotations

import re

# Ходовые пропорции для картинок. Все значения из списка, который принимает
# /images; редкие (8:1, 1:8, 19.5:9) намеренно не показываем — они нужны раз в
# год, а ряд кнопок делают нечитаемым.
IMAGE_ASPECT_RATIOS = ["1:1", "16:9", "9:16", "4:3", "3:4", "3:2", "2:3", "4:5"]

# Что вообще может прийти с фронта. Шире, чем список кнопок: у видео-моделей
# встречается 21:9, и его отдаёт каталог модели.
_ALLOWED = {
    "1:1", "16:9", "9:16", "4:3", "3:4", "3:2", "2:3",
    "21:9", "9:21", "5:4", "4:5", "2:1", "1:2",
}


def normalize(value) -> str | None:
    """«16 : 9», «16х9» (кириллическое х) → «16:9». Мусор → None."""
    if not value:
        return None
    v = str(value).strip().lower().replace(" ", "")
    v = v.replace("х", ":").replace("x", ":").replace("×", ":").replace("/", ":")
    return v if v in _ALLOWED else None


# Словами — то, как люди пишут в промпте. Ключи ищем как отдельные слова,
# иначе «вертикаль» нашлась бы внутри «вертикальность» и подобного.
# Корни намеренно ПОЛНЫЕ, а не обрезанные: «верт\w*» ловил бы «вертолёт», а
# «горизонт\w*» — «горизонт событий», и человек получал бы не тот кадр.
_WORDS: list[tuple[str, str]] = [
    (r"вертикальн\w*|вертикально|портретн\w*|сторис\w*|stories|шортс\w*|shorts|reels|рилс\w*|vertical|portrait", "9:16"),
    (r"квадратн\w*|квадрат\b|square", "1:1"),
    (r"горизонтальн\w*|горизонтально|альбомн\w*|широкоэкранн\w*|landscape|horizontal|widescreen", "16:9"),
    (r"кинематографичн\w*|киношн\w*|cinematic|cinemascope", "21:9"),
]


def from_prompt(text: str) -> str | None:
    """Достать пропорцию из текста запроса. None — если человек её не называл.

    Сначала ищем явную запись («16:9», «9х16»), потом словами. Нужно для
    случая, когда пользователь не трогал панель, а написал «вертикальное
    видео» — просьба клиента «и даже с промпта».
    """
    if not text:
        return None
    low = str(text).lower()

    m = re.search(r"\b(\d{1,2}(?:\.\d)?)\s*[:xх×/]\s*(\d{1,2}(?:\.\d)?)\b", low)
    if m:
        got = normalize(f"{m.group(1)}:{m.group(2)}")
        if got:
            return got

    for pattern, ratio in _WORDS:
        if re.search(rf"\b(?:{pattern})", low):
            return ratio
    return None


def resolve(explicit, prompt: str, allowed: list[str] | None = None) -> str | None:
    """Итоговая пропорция: что выбрано в панели, иначе — что сказано в промпте.

    allowed — набор конкретной модели (для видео приходит из каталога). Если
    выбранного значения модель не умеет, лучше не отправлять ничего: провайдер
    возьмёт своё значение по умолчанию, а не отвергнет весь запрос.
    """
    value = normalize(explicit) or from_prompt(prompt)
    if not value:
        return None
    if allowed and value not in allowed:
        return None
    return value


def prompt_suffix(ratio: str | None) -> str:
    """Добавка к промпту для моделей без параметра пропорций (chat-путь).

    По-английски: модели устойчивее реагируют на англоязычную формулировку
    служебных указаний, даже когда сам запрос на русском.
    """
    if not ratio:
        return ""
    hint = {
        "9:16": "vertical portrait orientation",
        "16:9": "horizontal widescreen orientation",
        "1:1": "square format",
        "4:5": "vertical portrait orientation",
        "21:9": "ultra-wide cinematic orientation",
    }.get(ratio, "")
    return f"\n\n(Aspect ratio: {ratio}{', ' + hint if hint else ''}.)"
