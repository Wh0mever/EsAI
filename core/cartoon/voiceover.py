"""«Озвучить весь мультфильм»: ИИ пишет реплики по сценам и озвучивает их.

Клиент: «нажимаешь одну кнопку — система сама распределяет реплики между
персонажами и озвучивает все сцены; итоговую стоимость показываем до запуска».

Поэтому шага два и они разделены нарочно:
1) план — дешёвый вызов текстовой модели, ничего не стоит человеку; он видит
   реплики, может их поправить и видит общую цену;
2) озвучка — очередь, где каждая реплика оплачивается по факту готового звука.

Голоса закрепляются за персонажами: один герой звучит одинаково во всех сценах
и во всех запусках, иначе мультфильм разваливается на куски.
"""
from __future__ import annotations

import json
import logging
import re
import time

import requests
from django.conf import settings
from django.core.cache import cache
from django.db import transaction

from . import audio

logger = logging.getLogger(__name__)

MAX_LINE_CHARS = 200
MAX_LINES = 50
# Сколько сцен просим у модели за один раз: на длинном списке ответ упирается в
# потолок токенов и обрывается на середине JSON.
CHUNK = 12
# Прогресс живёт дольше замка: по нему интерфейс понимает, что озвучка шла.
PROGRESS_TTL = 60 * 30
LOCK_TTL = 300
# Если прогресс не обновлялся столько секунд — считаем, что задача умерла
# (перезапуск воркера, деплой): иначе кнопка висела бы заблокированной.
STALE_AFTER = 180

LANG_NAMES = {"ru": "русском", "en": "английском", "kg": "кыргызском"}

_SYSTEM = (
    "You write dialogue for a short cartoon. You get the scenes in order, each with the "
    "character who appears in it and how many seconds that scene lasts. Write ONE short spoken "
    "line per scene, said by that scene's character, so that all lines together tell one simple, "
    "warm, kid-friendly story.\n"
    "Rules: each line must fit being said aloud within that scene's duration (about 13 characters "
    "per second, never more than the limit given for the scene); spoken words only — no names, no "
    "quotes, no stage directions, no emoji, no narration about what is happening; keep each "
    "character's voice consistent.\n"
    "Write the lines in {language} (the language of the scene descriptions).\n"
    'Return JSON only: {{"lines": [{{"n": 1, "text": "..."}}]}} with exactly one entry per scene, '
    "using the scene numbers given."
)


class PlanFailed(RuntimeError):
    """Модель не смогла написать реплики. Текст — для лога."""


class NoVoices(RuntimeError):
    """Справочник голосов пуст или недоступен — озвучивать нечем."""


# ------------------------------------------------------------- прогресс ---

def progress_key(project_id: int) -> str:
    return f"studio:voiceall:{project_id}"


def lock_key(project_id: int) -> str:
    return f"studio:voiceall:lock:{project_id}"


def get_progress(project_id: int) -> dict | None:
    return cache.get(progress_key(project_id))


def set_progress(project_id: int, **fields) -> dict:
    """Обновить прогресс и заодно отметить, что задача жива."""
    state = cache.get(progress_key(project_id)) or {"done": 0, "total": 0, "error": "", "spent": 0}
    state.update(fields)
    state["at"] = time.time()
    cache.set(progress_key(project_id), state, PROGRESS_TTL)
    return state


def clear_progress(project_id: int) -> None:
    cache.delete(progress_key(project_id))


def is_stale(state: dict | None) -> bool:
    """Прогресс есть, но давно не обновлялся: задачу убили на середине."""
    if not state or state.get("finished"):
        return False
    return (time.time() - float(state.get("at") or 0)) > STALE_AFTER


def touch_lock(project_id: int) -> None:
    """Продлить замок запуска, пока задача действительно работает."""
    value = cache.get(lock_key(project_id))
    if value:
        cache.set(lock_key(project_id), value, LOCK_TTL)


# ------------------------------------------------------------- план ------

def _scene_hero(scene):
    return scene.character or scene.project.character


def scene_label(scene) -> str:
    """Чем сцена является для сценариста: название из библиотеки или своё описание."""
    if scene.custom_text:
        return (scene.custom_title or scene.custom_text)[:200]
    return (scene.preset.title if scene.preset_id else "")[:200]


def scene_seconds(scene) -> int:
    return max(3, min(20, int(getattr(scene.preset, "duration", 5) or 5)))


def known_voices(project) -> dict:
    """Голоса, которыми этого героя уже озвучивали в этом мультфильме.

    Герой обязан звучать одинаково: и между сценами, и когда человек нажмёт
    «озвучить весь мультфильм» во второй раз.
    """
    from .models import CartoonAudioTrack

    out = {}
    tracks = (CartoonAudioTrack.objects
              .filter(scene__project=project, kind=CartoonAudioTrack.KIND_VOICE)
              .exclude(voice_id="").exclude(character__isnull=True)
              .order_by("-id").values("character_id", "voice_id", "voice_name"))
    for t in tracks:
        out.setdefault(t["character_id"], {"voice_id": t["voice_id"], "voice_name": t["voice_name"]})
    return out


def pick_voices(characters: list, voices: list | None = None, fixed: dict | None = None) -> dict:
    """Закрепить голос за каждым персонажем: разные герои — разные голоса.

    Уже звучавшие герои сохраняют свой голос. Остальным раздаём по номеру
    персонажа, а не по месту в списке: тогда при повторном плане (даже если
    сцены удалили или переставили) герой получит тот же голос.
    """
    voices = voices if voices is not None else audio.list_voices()
    if not voices:
        raise NoVoices("список голосов пуст")
    fixed = fixed or {}
    male = [v for v in voices if (v.get("gender") or "").lower().startswith("male")]
    female = [v for v in voices if (v.get("gender") or "").lower().startswith("female")]
    out, taken = {}, set()
    # Раздаём в порядке номеров персонажей, а не в порядке сцен: иначе тот же
    # герой получал бы другой голос, стоило поменять сцены местами.
    characters = sorted({c.pk: c for c in characters}.values(), key=lambda c: c.pk)
    for ch in characters:
        if ch.pk in fixed and fixed[ch.pk].get("voice_id"):
            out[ch.pk] = dict(fixed[ch.pk])
            taken.add(out[ch.pk]["voice_id"])
    for ch in characters:
        if ch.pk in out:
            continue
        # Пола у персонажа студии нет: чередуем мужские и женские по чётности
        # его номера — это стабильно между запусками.
        pool = (female if (ch.pk % 2 and female) else male) or voices
        choice = None
        for i in range(len(pool)):
            candidate = pool[(ch.pk + i) % len(pool)]
            if candidate["id"] not in taken:
                choice = candidate
                break
        choice = choice or pool[ch.pk % len(pool)]
        taken.add(choice["id"])
        out[ch.pk] = {"voice_id": choice["id"], "voice_name": choice["name"]}
    return out


def _ask_model(listing: list, lang: str, numbers: list) -> dict:
    """Одна пачка сцен → {номер: реплика}. Ошибки — PlanFailed."""
    from ai.handlers import _openrouter_config

    cfg = _openrouter_config()
    body = {
        "model": getattr(settings, "STUDIO_SCENE_MODEL", "google/gemini-2.5-flash"),
        "messages": [
            {"role": "system", "content": _SYSTEM.format(language=LANG_NAMES.get(lang, LANG_NAMES["ru"]))},
            {"role": "user", "content": "\n".join(listing)[:4000]},
        ],
        "temperature": 0.7,
        "max_tokens": min(4000, 400 + 160 * len(listing)),
        "response_format": {"type": "json_object"},
    }
    try:
        r = requests.post(
            f"{cfg['base_url'].rstrip('/')}/chat/completions", json=body,
            headers={"Authorization": f"Bearer {cfg['api_key']}", "Content-Type": "application/json"},
            timeout=(10, 90))
    except Exception as exc:  # noqa: BLE001
        raise PlanFailed(f"реплики: сеть: {exc}") from exc
    if not (200 <= r.status_code < 300):
        raise PlanFailed(f"реплики: http {r.status_code}: {r.text[:200]}")
    try:
        payload = r.json() or {}
    except ValueError as exc:
        raise PlanFailed("реплики: ответ не JSON") from exc
    content = (((payload.get("choices") or [{}])[0].get("message") or {}).get("content") or "")
    match = re.search(r"\{.*\}", content, flags=re.S)
    try:
        data = json.loads(match.group(0) if match else content)
    except ValueError as exc:
        raise PlanFailed("реплики: модель ответила не JSON") from exc
    out = {}
    raw = data.get("lines") if isinstance(data, dict) else None
    for item in (raw or []):
        # Модель иногда отвечает списком строк вместо списка объектов.
        if not isinstance(item, dict):
            continue
        try:
            n = int(item.get("n"))
        except (TypeError, ValueError):
            continue
        text = " ".join(str(item.get("text") or "").split())[:MAX_LINE_CHARS]
        if text and n in numbers:
            out[n] = text
    return out


def write_lines(scenes: list, lang: str = "ru") -> dict:
    """Реплики для всех сцен: {номер сцены (с единицы): текст}.

    Просим пачками: на длинном списке ответ обрывается по лимиту токенов, и
    тогда без пачек не было бы вообще ничего.
    """
    if not scenes:
        return {}
    result, failures = {}, 0
    for start in range(0, len(scenes), CHUNK):
        chunk = scenes[start:start + CHUNK]
        numbers = list(range(start + 1, start + len(chunk) + 1))
        listing = []
        for n, scene in zip(numbers, chunk):
            hero = _scene_hero(scene)
            seconds = scene_seconds(scene)
            listing.append(
                f"{n}. Сцена: {scene_label(scene)}. Персонаж: {hero.name if hero else 'герой'}. "
                f"Длительность: {seconds} с, не длиннее {min(MAX_LINE_CHARS, seconds * 13)} символов.")
        try:
            result.update(_ask_model(listing, lang, numbers))
        except PlanFailed:
            logger.exception("реплики: пачка сцен %s-%s не написалась", numbers[0], numbers[-1])
            failures += 1
    if not result:
        raise PlanFailed(f"реплики: ни одной пачки не получилось ({failures})")
    return result


def build_plan(project, lang: str = "ru") -> dict:
    """План озвучки всего мультфильма: реплика и голос на каждую сцену + цена."""
    scenes = list(project.scenes.select_related("preset", "character", "project__character")
                  .order_by("order", "id"))
    scenes = [s for s in scenes if _scene_hero(s)][:MAX_LINES]
    if not scenes:
        return {"lines": [], "total_credits": 0}

    heroes, seen = [], set()
    for scene in scenes:
        hero = _scene_hero(scene)
        if hero.pk not in seen:
            seen.add(hero.pk)
            heroes.append(hero)
    # Голоса спрашиваем ДО платного вызова модели: если их нет, незачем тратить
    # деньги на реплики, которые нечем озвучить.
    voices = pick_voices(heroes, fixed=known_voices(project))

    texts = write_lines(scenes, lang)

    voiced = set(project.scenes.filter(audio_tracks__kind="voice")
                 .values_list("pk", flat=True))
    lines, total = [], 0
    for i, scene in enumerate(scenes, start=1):
        # Сцена без реплики остаётся в списке с пустым текстом: молча пропасть
        # она не должна — человек увидит её и допишет реплику сам.
        text = texts.get(i) or ""
        hero = _scene_hero(scene)
        voice = voices.get(hero.pk) or {}
        price = audio.voice_price(text) if text else 0
        total += price
        lines.append({
            "scene_id": scene.pk,
            "order": scene.order,
            "title": scene_label(scene),
            "seconds": scene_seconds(scene),
            "character": {"id": hero.pk, "name": hero.name},
            "voice_id": voice.get("voice_id", ""),
            "voice_name": voice.get("voice_name", ""),
            "text": text,
            "credits": price,
            "has_voice": scene.pk in voiced,
        })
    return {"lines": lines, "total_credits": total}


# ------------------------------------------------------------- озвучка ---

def voice_line(scene, text: str, voice_id: str, voice_name: str = "", character=None,
               replace: bool = True):
    """Озвучить одну реплику сцены и списать кредиты ПОСЛЕ готового звука.

    replace — убрать прежние ИИ-реплики сцены: повторная озвучка мультфильма не
    должна наслаивать голоса друг на друга.

    Деньги и дорожка пишутся одной транзакцией: иначе обрыв между списанием и
    записью оставил бы человека без звука, но с минусом на балансе.
    """
    from django.core.files.storage import default_storage

    from .models import CartoonAudioTrack
    from .services import charge

    text = " ".join(str(text or "").split())[:MAX_LINE_CHARS]
    if not text or not audio.valid_voice_id(voice_id):
        return None
    price = audio.voice_price(text)
    raw = audio.tts(text, voice_id)
    path, duration = audio.save_audio(raw)
    try:
        with transaction.atomic():
            if replace:
                CartoonAudioTrack.objects.filter(
                    scene=scene, kind=CartoonAudioTrack.KIND_VOICE).delete()
            track = CartoonAudioTrack.objects.create(
                scene=scene, kind=CartoonAudioTrack.KIND_VOICE, character=character,
                voice_id=voice_id, voice_name=voice_name, text=text, file=path,
                duration=duration, start_sec=0, volume=1.0, credits_spent=price)
            charge(scene.project.user, price, "cartoon_voice",
                   meta={"scene": scene.pk, "kind": "voice", "chars": len(text), "all": True})
    except Exception:
        # Звук не достался человеку — и платить за него он не должен.
        default_storage.delete(path)
        raise
    return track


def voice_project(project, plan: list, replace: bool = True) -> dict:
    """Озвучить все реплики плана и свести снятые сцены. Считает прогресс."""
    from celery.exceptions import SoftTimeLimitExceeded

    from plans.wallet import InsufficientTokens

    from .models import CartoonScene

    total = len(plan)
    set_progress(project.pk, done=0, total=total, error="", spent=0, finished=False)
    done, spent, error = 0, 0, ""
    for item in plan:
        try:
            scene_id = int(item.get("scene_id") or 0)
        except (TypeError, ValueError):
            continue
        # Сцену могли удалить из ленты, пока шла озвучка.
        scene = (CartoonScene.objects.select_related("project", "project__user", "character",
                                                     "project__character")
                 .filter(pk=scene_id, project=project).first())
        if not scene:
            continue
        character = scene.character or scene.project.character
        try:
            track = voice_line(scene, item.get("text"), item.get("voice_id"),
                               item.get("voice_name") or "", character, replace)
        except InsufficientTokens:
            error = "not_enough_credits"
            logger.warning("озвучка мультфильма %s: не хватило кредитов на сцене %s",
                           project.pk, scene.pk)
            break
        except SoftTimeLimitExceeded:
            # Мягкий лимит: выходим сами, чтобы сняли замок и записали прогресс.
            error = "timeout"
            logger.warning("озвучка мультфильма %s: не успели за отведённое время", project.pk)
            break
        except Exception:
            logger.exception("озвучка мультфильма %s: сцена %s не озвучилась", project.pk, scene.pk)
            error = "line_failed"
            continue
        if track:
            done += 1
            spent += track.credits_spent
            set_progress(project.pk, done=done, spent=spent, error=error)
            touch_lock(project.pk)
        # Сведение сразу: снятая сцена начинает говорить, пока идут остальные.
        # Состояние сцены перечитывается внутри remix_scene — её могли доснять.
        try:
            audio.remix_scene(scene)
        except Exception:
            logger.exception("озвучка мультфильма %s: сцена %s не свелась", project.pk, scene.pk)
        touch_lock(project.pk)
    set_progress(project.pk, done=done, spent=spent, error=error, finished=True)
    return {"done": done, "total": total, "spent": spent, "error": error}
