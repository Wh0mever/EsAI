"""Режиссёр сцены: из короткого описания делает подробный промпт для видео.

Претензия клиента (17.09): «персонажи плохо отрабатывают действия, сцены почти
не развиваются, диалоги и движения передаются некорректно».

Причина была в том, что видеомодель получала одну строку движения из пресета —
без героя, без стиля и без реплик. Теперь перед съёмкой дешёвая текстовая модель
раскладывает сцену по секундам: кто в кадре, что он делает, куда идёт камера,
какое выражение лица, что говорит. Результат кэшируется в сцене: пересъёмка не
платит за него второй раз.
"""
from __future__ import annotations

import json
import logging
import re

import requests
from django.conf import settings

logger = logging.getLogger(__name__)

MAX_PROMPT_CHARS = 1800
MAX_NEGATIVE_CHARS = 400

# Что не должно происходить в кадре. Список общий для всех сцен: это типовые
# болячки генерации, а не особенности конкретной истории.
BASE_NEGATIVE = (
    "deformed limbs, extra fingers or paws, morphing face, changing outfit, "
    "duplicated character, text overlay, subtitles, watermark, logo, "
    "camera cut, scene change, frozen still frame, jitter, flicker"
)

_SYSTEM = (
    "You are a storyboard director for short 3D cartoon shots. You receive: who the hero is, "
    "what happens in the shot, how long the shot lasts, and sometimes the line the hero says.\n"
    "Write ONE prompt for an image-to-video model that ALREADY receives the first frame of this "
    "shot, so the look is fixed — your job is the MOVEMENT, the ACTING and the SOUND.\n"
    "Keep the order the model vendors recommend, in plain sentences without headings: camera "
    "work, then the subject, then the action beats, then the context, then light and style, "
    "then audio.\n"
    "Rules:\n"
    "- One continuous shot, no cuts, no scene changes, no new locations.\n"
    "- Break the action into beats with timing inside the shot, e.g. \"0-2s ... 2-4s ... 4-5s ...\" "
    "for a 5-second shot (the shot length and its split are given), and make sure the action "
    "completes within the shot length — one clear action, not three.\n"
    "- Refer to the hero by appearance (\"the grey kitten in a beige suit\"), never by a name.\n"
    "- Say exactly what the hands or paws do with the objects that are in the frame.\n"
    "- Give the facial expression and how it changes, and the camera move (push in, slow orbit, "
    "tilt up, handheld follow) — the camera must never be completely static.\n"
    "- Keep the outfit, the character and the room exactly as in the first frame.\n"
    "- If a line is given, put it in the audio part, VERBATIM and in its own language: "
    "The character says: \"…\" — plus natural lip sync, matching head and jaw movement, calm "
    "clearly audible speech, and short ambient sound that fits the place.\n"
    "- If no line is given, describe only ambient sound; nobody speaks.\n"
    "- No text on screen, no subtitles, no watermark, no captions.\n"
    "Answer JSON only: {\"prompt\": \"...\", \"negative\": \"...\"}. "
    "prompt: at most 1200 characters, English, no line breaks. "
    "negative: short comma-separated list of what must not appear."
)


class DirectorFailed(RuntimeError):
    """Промпт не составился. Текст — для лога: человеку покажем старый путь."""


def _ask(payload: str) -> dict:
    from ai.handlers import _openrouter_config

    cfg = _openrouter_config()
    body = {
        "model": getattr(settings, "STUDIO_SCENE_MODEL", "google/gemini-2.5-flash"),
        "messages": [{"role": "system", "content": _SYSTEM},
                     {"role": "user", "content": payload[:3000]}],
        "temperature": 0.6,
        "max_tokens": 900,
        "response_format": {"type": "json_object"},
    }
    try:
        r = requests.post(
            f"{cfg['base_url'].rstrip('/')}/chat/completions", json=body,
            headers={"Authorization": f"Bearer {cfg['api_key']}", "Content-Type": "application/json"},
            timeout=(10, 90))
    except Exception as exc:  # noqa: BLE001
        raise DirectorFailed(f"режиссёр: сеть: {exc}") from exc
    if not (200 <= r.status_code < 300):
        raise DirectorFailed(f"режиссёр: http {r.status_code}: {r.text[:200]}")
    content = (((r.json() or {}).get("choices") or [{}])[0].get("message") or {}).get("content") or ""
    match = re.search(r"\{.*\}", content, flags=re.S)
    try:
        data = json.loads(match.group(0) if match else content)
    except ValueError as exc:
        raise DirectorFailed("режиссёр: ответ не JSON") from exc
    if not isinstance(data, dict) or not str(data.get("prompt") or "").strip():
        raise DirectorFailed("режиссёр: пустой промпт")
    return data


def _hero_line(character) -> str:
    who = (getattr(character, "description", "") or "").strip()
    return who or "the character shown in the first frame"


def _scene_action(scene, preset) -> str:
    """Что происходит в сцене — словами, понятными режиссёру."""
    if scene.custom_text:
        return (scene.custom_prompt or scene.custom_text).strip()
    parts = [(preset.scene_prompt or "").strip(), (preset.motion_prompt or "").strip()]
    return " ".join(p for p in parts if p)


def beats(duration: int) -> str:
    """Разбивка снимаемой длины на три такта: 5 с → «0-2s ... 2-4s ... 4-5s».

    Пример в системном промпте — для пяти секунд; без разбивки под свою длину
    сцену на 10–15 с режиссёр мог бы уложить в первые пять.
    """
    total = max(1, int(duration or 5))
    first, second = round(total * 0.4), round(total * 0.8)
    if not 0 < first < second < total:
        return f"0-{total}s"
    return f"0-{first}s ... {first}-{second}s ... {second}-{total}s"


def compose(scene, character, preset, duration: int) -> dict:
    """{prompt, negative} для видеомодели. Бросает DirectorFailed при неудаче.

    duration — длина, которую снимет модель (снимок сцены), а не пресета.
    """
    dialogue = (getattr(scene, "dialogue", "") or "").strip()
    # Речь укладывается примерно в 2-3 слова в секунду: реплика длиннее — и
    # модель либо тараторит, либо обрывает её на полуслове.
    budget = max(4, int(duration * 2.5))
    payload = "\n".join([
        f"Hero: {_hero_line(character)}.",
        f"Shot: {_scene_action(scene, preset)}",
        f"Shot length: {duration} seconds, beats like {beats(duration)} "
        f"(a spoken line fits in about {budget} words).",
        (f'Line the hero says (keep verbatim, do not translate, '
         f'{len(dialogue.split())} words): "{dialogue}"') if dialogue
        else "The hero does not speak in this shot.",
        f"Visual style: {(preset.style_prompt or '').strip()}" if preset.style_prompt else "",
    ])
    data = _ask(payload)
    prompt = " ".join(str(data.get("prompt") or "").split())[:MAX_PROMPT_CHARS]
    negative = " ".join(str(data.get("negative") or "").split())[:MAX_NEGATIVE_CHARS]
    negative = f"{BASE_NEGATIVE}, {negative}" if negative else BASE_NEGATIVE
    return {"prompt": prompt, "negative": negative[:MAX_NEGATIVE_CHARS + len(BASE_NEGATIVE) + 2]}


def fallback(scene, character, preset, duration: int) -> dict:
    """Промпт без модели: хуже, но лучше прежней одной строки.

    Нужен, когда текстовая модель недоступна: сцена всё равно должна сняться, а
    не упасть, — человек уже нажал «снять» и ждёт ролик.
    """
    dialogue = (getattr(scene, "dialogue", "") or "").strip()
    bits = [
        f"{_hero_line(character)} — keep this character exactly as in the first frame.",
        _scene_action(scene, preset),
        f"The action unfolds smoothly over {duration} seconds, one continuous shot, "
        "the camera moves slowly (gentle push in), natural facial expression and body movement.",
    ]
    if dialogue:
        bits.append(f'The character says: "{dialogue}" with natural lip sync.')
    if preset.style_prompt:
        bits.append(preset.style_prompt.strip())
    return {"prompt": " ".join(b for b in bits if b)[:MAX_PROMPT_CHARS], "negative": BASE_NEGATIVE}


def ensure_video_prompt(scene, character, preset, duration: int) -> dict:
    """Промпт сцены: из кэша, от модели или запасной. Один раз на сцену."""
    if scene.video_prompt:
        return {"prompt": scene.video_prompt, "negative": scene.video_negative or BASE_NEGATIVE}
    try:
        data = compose(scene, character, preset, duration)
    except Exception:
        logger.exception("сцена %s: режиссёрский промпт не составился, беру запасной", scene.pk)
        data = fallback(scene, character, preset, duration)
    scene.video_prompt = data["prompt"]
    scene.video_negative = data["negative"]
    scene.save(update_fields=["video_prompt", "video_negative", "updated_at"])
    return data
