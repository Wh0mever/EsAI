"""Режиссёр сцены: из короткого описания делает подробный промпт для видео.

Претензия клиента (17.09): «персонажи плохо отрабатывают действия, сцены почти
не развиваются, диалоги и движения передаются некорректно».

Причина была в том, что видеомодель получала одну строку движения из пресета —
без героя, без стиля и без реплик. Теперь перед съёмкой дешёвая текстовая модель
раскладывает сцену по секундам: кто в кадре, что он делает, куда идёт камера,
какое выражение лица, что говорит. Результат кэшируется в сцене: пересъёмка не
платит за него второй раз.

Голос героя в готовой сцене — не модели, а ElevenLabs (cartoon/audio.py): модель
только двигает ртом и даёт окно речи. Поэтому реплика ставится в предсказуемое
место снимка и идёт без музыки: глушение окна срезало бы и её. И поэтому режиссёр
решает, слова ли это героя: люди пишут в поле реплики и описания сцены.
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
JUDGE_CHUNK = 12            # столько реплик за один вызов: длинный ответ обрывается
JUDGE_LIMIT = 12000         # 12 строк: описание героя 200, действие 300, реплика 300, подписи
JUDGE_TIMEOUT = (5, 20)     # проверка идёт внутри запроса человека и не обязательна
# Живая речь — около 13 знаков в секунду (та же норма, что у озвучки мультфильма).
LINE_CHARS_PER_SEC = 13
VOICE_GENDERS = ("female", "male")
VOICE_AGES = ("child", "young", "adult", "old")
LINE_LANGS = ("ky", "other")

# Что не должно происходить в кадре. Список общий для всех сцен: это типовые
# болячки генерации, а не особенности конкретной истории.
BASE_NEGATIVE = (
    "deformed limbs, extra fingers or paws, morphing face, changing outfit, "
    "duplicated character, text overlay, subtitles, watermark, logo, "
    "camera cut, scene change, frozen still frame, jitter, flicker"
)

# Одно правило на режиссёра сцены и на проверку реплик уже снятых сцен.
_SPEECH_RULE = (
    "It is false ONLY when the text plainly describes events or retells the plot about the hero in the "
    "third person, or tells the hero what to do, and nobody would say it aloud; when in doubt it is true. "
    "Speech: \"Ура! Спасибо всем за поздравления!\", \"Какое прекрасное и чудесное кофе\", "
    "\"кандайсыз тая ата тай эне\", \"Кандайсынар кыздар. Менин атым Жылдыз\", \"Он украл мою "
    "игрушку!\". Not speech: \"Он герой играет потом ищет свою маму не найдёт плакать после этого\", "
    "\"Ал ойноп жатат анан апасын издейт\", \"Пусть он скажет привет и помашет рукой\"."
)
_LANG_RULE = "line_lang: ky when the line is in Kyrgyz, even without the letters ң ө ү, otherwise other. "
_VOICE_RULE = ("voice: how the hero would sound, judging by the hero description and name; "
               "unknown when you cannot tell. ")

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
    "- If a line is given, first decide whether it is speech (line_is_speech). " + _SPEECH_RULE + "\n"
    "- If the line is speech, put it in the audio part, VERBATIM and in its own language: "
    "The character says: \"…\" — plus natural lip sync, matching head and jaw movement, calm "
    "clearly audible speech. The line starts 0.5-1 second after the beginning of the shot and "
    "ends 0.5 second before the end of the shot. Then add: no background music, quiet ambient "
    "sound only.\n"
    "- If the line is not speech, it must NOT appear in the audio part: treat it as the action "
    "of the shot and write that nobody speaks, ambient sound only.\n"
    "- If no line is given, describe only ambient sound; nobody speaks.\n"
    "- No text on screen, no subtitles, no watermark, no captions.\n"
    "Answer JSON only, in this key order: {\"line_is_speech\": true, \"line_lang\": \"ky|other\", "
    "\"voice\": {\"gender\": \"female|male|unknown\", \"age\": \"child|young|adult|old\"}, "
    "\"prompt\": \"...\", \"negative\": \"...\"}. "
    "line_is_speech: true or false, as decided above. " + _LANG_RULE + _VOICE_RULE +
    "prompt: at most 1200 characters, English, no line breaks. "
    "negative: short comma-separated list of what must not appear."
)


_JUDGE_SYSTEM = (
    "You check lines written for the heroes of short cartoon scenes. You get numbered lines, each with "
    "the hero and what happens in the scene. For each line decide whether it is speech (line_is_speech). "
    + _SPEECH_RULE + "\n"
    "Answer JSON only: {\"lines\": [{\"n\": 1, \"line_is_speech\": true, \"line_lang\": \"ky|other\", "
    "\"voice\": {\"gender\": \"female|male|unknown\", \"age\": \"child|young|adult|old\"}}]} with exactly "
    "one entry per line, using the numbers given. " + _LANG_RULE + _VOICE_RULE
)


class DirectorFailed(RuntimeError):
    """Промпт не составился. Текст — для лога: человеку покажем старый путь."""


def _call(system: str, payload: str, *, max_tokens: int, temperature: float, limit: int = 3000,
          timeout: tuple = (10, 90)) -> dict:
    from ai.handlers import _openrouter_config

    cfg = _openrouter_config()
    body = {
        "model": getattr(settings, "STUDIO_SCENE_MODEL", "google/gemini-2.5-flash"),
        "messages": [{"role": "system", "content": system},
                     {"role": "user", "content": payload[:limit]}],
        "temperature": temperature,
        "max_tokens": max_tokens,
        "response_format": {"type": "json_object"},
    }
    try:
        r = requests.post(
            f"{cfg['base_url'].rstrip('/')}/chat/completions", json=body,
            headers={"Authorization": f"Bearer {cfg['api_key']}", "Content-Type": "application/json"},
            timeout=timeout)
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
    if not isinstance(data, dict):
        raise DirectorFailed("режиссёр: ответ не объект")
    return data


def _ask(payload: str) -> dict:
    data = _call(_SYSTEM, payload, max_tokens=900, temperature=0.6)
    if not str(data.get("prompt") or "").strip():
        raise DirectorFailed("режиссёр: пустой промпт")
    return data


def _ask_lines(payload: str) -> dict:
    return _call(_JUDGE_SYSTEM, payload, max_tokens=120 + 60 * JUDGE_CHUNK, temperature=0.2,
                 limit=JUDGE_LIMIT, timeout=JUDGE_TIMEOUT)


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


def _is_speech(raw) -> bool:
    """Ответ режиссёра «это речь?». Описанием считаем только явное «нет»: при
    сомнении реплику озвучиваем — именно этого человек и ждёт."""
    return not (raw is False or str(raw).strip().lower() == "false")


def _voice_hint(raw, lang=None) -> dict:
    """Подсказка о голосе героя и языке реплики: только значения из списка.

    lang есть только у прочитанной режиссёром реплики (см. unjudged), поэтому
    непонятный язык — не пропуск, а "other".
    """
    raw = raw if isinstance(raw, dict) else {}
    gender = str(raw.get("gender") or "").strip().lower()
    age = str(raw.get("age") or "").strip().lower()
    lang = str(lang or "").strip().lower()
    hint = {}
    if gender in VOICE_GENDERS:
        hint["gender"] = gender
    if age in VOICE_AGES:
        hint["age"] = age
    if lang:
        hint["lang"] = lang if lang in LINE_LANGS else "other"
    return hint


def _line_lang(raw, dialogue: str) -> str:
    """Язык реплики из ответа режиссёра; не ответил — по буквам, как для непрочитанных слов."""
    from .audio import line_lang

    lang = str(raw or "").strip().lower()
    if lang in LINE_LANGS:
        return lang
    return "ky" if line_lang(dialogue) else "other"


def unjudged(scene) -> bool:
    """Режиссёр не читал нынешние слова сцены. Пол и возраст он даёт и без реплики,
    поэтому признак — язык: его ставит только чтение реплики, а правка слов снимает."""
    return bool((scene.dialogue or "").strip()) and "lang" not in (scene.voice_hint or {})


_QUOTED = re.compile(r'["«“][^"»”]*["»”]')
_SPEECH_WORDS = (r"says?|said|saying|speaks?|speaking|whispers?|whispering|shouts?|shouting|asks?|asking"
                 r"|exclaims?|narrat\w*|voice-?over|lip[- ]sync\w*|audible speech")
_SPEECH_LABEL = r"\b(?:audio|voice|dialogue)\s*:"
_CYRILLIC = r"[\u0400-\u04FF]"
_SPOKEN = re.compile(rf'"|{_SPEECH_LABEL}|\b(?:{_SPEECH_WORDS})\b|{_CYRILLIC}', re.I)
# Речь внутри такта: от глагола до конца оборота, соседние такты остаются.
_SPOKEN_PHRASE = re.compile(rf"(?:\s+(?:and|then|while|as))?\s*(?:{_SPEECH_LABEL}|\b(?:{_SPEECH_WORDS})\b|"
                            rf'""|{_CYRILLIC})[^,;.!?]*', re.I)
_BEAT = re.compile(r"\b\d+\s*[-–—]\s*\d+\s*s\b", re.I)
# В такте «says nothing and runs» — действие. Резать можно только то, что и правда звучит.
_REAL_SPEECH = re.compile(rf'""|{_SPEECH_LABEL}|{_CYRILLIC}|lip[- ]sync|audible speech'
                          r"|\b(?:says?|said)\s*[:'‘’]", re.I)
_ONLY_BEATS = re.compile(r"\W*(?:\d+\s*[-–—]\s*\d+\s*s\b\W*)+", re.I)


def _unspoken(sentence: str) -> str:
    """Предложение без речи. Без тактов это целиком реплика, с тактами — ещё и действие."""
    calm = "nobody speaks" in sentence.lower() and not re.search(_CYRILLIC, sentence)
    if calm or not _SPOKEN.search(sentence):
        return sentence
    if not _BEAT.search(sentence):
        return ""
    if not _REAL_SPEECH.search(sentence):
        return sentence
    cleaned = re.sub(r"\s+([,.;!?])", r"\1", _SPOKEN_PHRASE.sub("", sentence)).strip()
    return "" if _ONLY_BEATS.fullmatch(cleaned) else cleaned


def _unsaid(prompt: str, action: str = "") -> str:
    """Убрать описание из звуковой части, даже если модель его туда поставила.

    Проверка кодом, а не только правило в промпте: цена ошибки здесь — та самая
    сцена, где видеомодель читает вслух «он герой играет потом ищет маму». Промпт
    английский, поэтому кириллица в нём — это сама реплика, даже без кавычек, а
    такты с английским действием остаются. Убрали предложение, а тактов нет — ставим
    действие сцены: иначе снялся бы ролик, где ничего не происходит.
    """
    sentences = re.split(r"(?<=[.!?])\s+", _QUOTED.sub('""', prompt))
    kept = [_unspoken(part) for part in sentences]
    text = " ".join(" ".join(kept).split())
    if action and "" in kept and not _BEAT.search(text):
        text = f"{action} {text}".strip()
    return text if "nobody speaks" in text.lower() else f"{text} Nobody speaks, ambient sound only."


def compose(scene, character, preset, duration: int, judge: bool = True) -> dict:
    """{prompt, negative, line_is_speech, voice} для видеомодели. Бросает DirectorFailed.

    duration — длина, которую снимет модель (снимок сцены), а не пресета.
    judge — разбирать, слова это или описание. False (автоозвучка выключена): реплику
    произнесёт сама модель, и ошибочное «описание» оставило бы сцену без слов.
    """
    dialogue = (getattr(scene, "dialogue", "") or "").strip()
    # Реплика длиннее бюджета не влезает в окно речи: голос героя придётся
    # ускорять, а потом и выпускать за окно.
    budget = max(12, int(duration * LINE_CHARS_PER_SEC))
    name = (getattr(character, "name", "") or "").strip()
    payload = "\n".join([
        f"Hero: {_hero_line(character)}.",
        f"Hero name, only to judge the voice, never write it: {name}" if name else "",
        f"Shot: {_scene_action(scene, preset)}",
        f"Shot length: {duration} seconds, beats like {beats(duration)} "
        f"(a spoken line fits in about {budget} characters).",
        (f'Line the hero says (keep verbatim, do not translate, '
         f'{len(dialogue)} characters): "{dialogue}"') if dialogue
        else "The hero does not speak in this shot.",
        ("The line is speech: line_is_speech must be true. The model in the video says it itself, "
         "so ignore the timing rule, and background music is allowed.") if dialogue and not judge else "",
        f"Visual style: {(preset.style_prompt or '').strip()}" if preset.style_prompt else "",
    ])
    data = _ask("\n".join(row for row in payload.split("\n") if row))
    speech = _is_speech(data.get("line_is_speech", True)) if dialogue and judge else True
    prompt = " ".join(str(data.get("prompt") or "").split())
    if dialogue and not speech:
        prompt = _unsaid(prompt, _scene_action(scene, preset))
    negative = " ".join(str(data.get("negative") or "").split())[:MAX_NEGATIVE_CHARS]
    negative = f"{BASE_NEGATIVE}, {negative}" if negative else BASE_NEGATIVE
    return {"prompt": prompt[:MAX_PROMPT_CHARS],
            "negative": negative[:MAX_NEGATIVE_CHARS + len(BASE_NEGATIVE) + 2],
            "line_is_speech": speech,
            "voice": _voice_hint(data.get("voice"), _line_lang(data.get("line_lang"), dialogue) if dialogue else None)}


def fallback(scene, character, preset, duration: int, speech: bool = True) -> dict:
    """Промпт без модели: хуже, но лучше прежней одной строки.

    Нужен, когда текстовая модель недоступна: сцена всё равно должна сняться, а
    не упасть, — человек уже нажал «снять» и ждёт ролик. speech=False — режиссёр уже
    признал реплику описанием: его решение не забываем и вслух её не читаем.
    """
    dialogue = (getattr(scene, "dialogue", "") or "").strip()
    bits = [
        f"{_hero_line(character)} — keep this character exactly as in the first frame.",
        _scene_action(scene, preset),
        f"The action unfolds smoothly over {duration} seconds, one continuous shot, "
        "the camera moves slowly (gentle push in), natural facial expression and body movement.",
    ]
    if dialogue and speech:
        bits.append(f'The character says: "{dialogue}" with natural lip sync, starting about one '
                    "second into the shot and finishing half a second before its end, "
                    "no background music, quiet ambient sound only.")
    elif dialogue:
        bits.append("Nobody speaks, ambient sound only.")
    if preset.style_prompt:
        bits.append(preset.style_prompt.strip())
    # Без модели разобрать, описание это или речь, нечем: считаем речью, как и раньше.
    return {"prompt": " ".join(b for b in bits if b)[:MAX_PROMPT_CHARS], "negative": BASE_NEGATIVE,
            "line_is_speech": speech or not dialogue, "voice": {}}


def ensure_video_prompt(scene, character, preset, duration: int, judge: bool = True) -> dict:
    """Промпт сцены: из кэша, от модели или запасной. Один раз на сцену.

    Режиссёр не читал нынешние слова (unjudged): сцена снята до автоозвучки, на запасном
    промпте или слова поправили. Такой кэш собираем заново, иначе описание снова прочли
    бы вслух. Режиссёр недоступен — остаётся то, что было.

    judge=False (автоозвучка выключена) — реплику говорит сама модель. Описание,
    которое режиссёр нашёл раньше, возвращаем в промпт: выключатель нужен как раз на
    случай его ошибки. Подсказку не храним: в такой сцене реплику никто не оценивал.
    """
    cached = {"prompt": scene.video_prompt, "negative": scene.video_negative or BASE_NEGATIVE}
    fresh_words = judge and unjudged(scene)
    silenced = not judge and bool((scene.dialogue or "").strip()) and not scene.dialogue_is_speech
    if scene.video_prompt and not fresh_words and not silenced:
        return cached
    try:
        data = compose(scene, character, preset, duration, judge=judge)
    except Exception:
        if scene.video_prompt and not silenced:
            logger.warning("сцена %s: режиссёр недоступен, остаётся прежний промпт", scene.pk)
            return cached
        logger.exception("сцена %s: режиссёрский промпт не составился, беру запасной", scene.pk)
        data = fallback(scene, character, preset, duration, speech=scene.dialogue_is_speech or not judge)
        if judge:
            data["voice"] = scene.voice_hint or {}
    scene.video_prompt = data["prompt"]
    scene.video_negative = data["negative"]
    # Решение о реплике живёт вместе с промптом: то, что сделало его таким, и нужно
    # при выдаче ролика — и при пересъёмке, где промпт уже не собирается.
    scene.dialogue_is_speech = bool(data.get("line_is_speech", True))
    scene.voice_hint = (data.get("voice") or {}) if judge else {}
    scene.save(update_fields=["video_prompt", "video_negative", "dialogue_is_speech", "voice_hint",
                              "updated_at"])
    return data


def _judge_row(n: int, scene) -> str:
    hero = scene.character or scene.project.character
    name = (getattr(hero, "name", "") or "").strip()
    action = _scene_action(scene, scene.preset) if scene.preset_id else (scene.custom_text or "")
    return f'{n}. Hero: {_hero_line(hero)[:200]} ({name}). Scene: {action[:300]} Line: "{scene.dialogue.strip()}"'


def judge_lines(scenes: list) -> None:
    """Режиссёр читает реплики уже снятых сцен: без съёмки он их не видел.

    Сцены, снятые до автоозвучки, и снятые при выключенной озвучке. Без этого кнопка и
    «Озвучить весь мультфильм» прочли бы вслух описание, а кыргызская реплика пошла бы
    на общую модель. Дёшево: один вызов текстовой модели на пачку, человеку бесплатно.
    Сбой оставляет сцены как есть: при сомнении реплика считается речью. Дальше после
    него не идём: всё это внутри запроса человека, а модель, похоже, недоступна.
    """
    for start in range(0, len(scenes), JUDGE_CHUNK):
        chunk = scenes[start:start + JUDGE_CHUNK]
        try:
            data = _ask_lines("\n".join(_judge_row(n, s) for n, s in enumerate(chunk, start=1)))
        except Exception:
            logger.exception("режиссёр: реплики сцен %s не проверены", [s.pk for s in chunk])
            break
        raw = data.get("lines")
        for item in raw if isinstance(raw, list) else []:
            try:
                scene = chunk[int(item.get("n")) - 1] if int(item.get("n")) > 0 else None
            except (AttributeError, IndexError, TypeError, ValueError):
                continue
            # Пустая запись — не решение: такая сцена осталась бы «прочитанной» навсегда.
            if scene is None or ("line_is_speech" not in item and not item.get("line_lang")):
                continue
            scene.dialogue_is_speech = _is_speech(item.get("line_is_speech", True))
            scene.voice_hint = {**(scene.voice_hint or {}),
                                **_voice_hint(item.get("voice"), _line_lang(item.get("line_lang"), scene.dialogue))}
            fields = ["dialogue_is_speech", "voice_hint", "updated_at"]
            if not scene.dialogue_is_speech and scene.video_prompt:
                # Промпт собран, когда реплику считали речью: пересъёмка снова прочла бы её.
                action = _scene_action(scene, scene.preset) if scene.preset_id else ""
                scene.video_prompt = _unsaid(scene.video_prompt, action)[:MAX_PROMPT_CHARS]
                fields.append("video_prompt")
            scene.save(update_fields=fields)
