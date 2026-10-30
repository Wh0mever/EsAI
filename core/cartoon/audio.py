"""Звук студии: голоса, музыка и эффекты ElevenLabs и сведение с видео сцены.

Клиент: «каждая сцена должна иметь возможность озвучки» — ИИ-голос по тексту,
свой голос, фоновая музыка и эффекты, у каждой дорожки громкость и момент
начала, а на выходе всё само собирается в сцену и мультфильм.

Реплика героя (дорожка line, F30): голос сцены синтезирует сама видеомодель, и
у одного героя он каждый раз другой. Поэтому при реплике речь модели глушится
в её окне (speech_window), провал заполняется тихим фоном этого же ролика, а
сверху ложится реплика ElevenLabs постоянным голосом героя.

Цены — настройки админки (просьба клиента зафиксировать их так): озвучка
20 кредитов за 1000 символов и не меньше 5 за генерацию, музыка 30 за минуту
по фактической длительности, эффект 10 за штуку. Списываем только после
успешной генерации: провайдер берёт деньги за готовый звук, и отказ его API
не должен стоить человеку кредитов.

Ключ ElevenLabs живёт в админке (write-only) с запасным значением из окружения.
"""
from __future__ import annotations

import json
import logging
import math
import os
import re
import shutil
import subprocess
import tempfile
import uuid
from contextlib import contextmanager
from pathlib import Path

import requests
from django.conf import settings
from django.core.cache import cache
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage

logger = logging.getLogger(__name__)

API_URL = "https://api.elevenlabs.io"
TIMEOUT = (10, 180)

MAX_VOICE_CHARS = 1000
MUSIC_MIN_SEC, MUSIC_MAX_SEC = 3, 120
SFX_MIN_SEC, SFX_MAX_SEC = 0.5, 30
UPLOAD_MAX_BYTES = 15 * 1024 * 1024
UPLOAD_MAX_SECONDS = 300
# Формат идентификатора голоса у ElevenLabs. Проверяем строго: id подставляется
# в адрес запроса, и «../» в нём увёл бы наш ключ на чужую ручку провайдера.
VOICE_ID_RE = re.compile(r"^[A-Za-z0-9_-]{2,64}$")
VOLUME_MIN, VOLUME_MAX = 0.0, 2.0
VOICES_CACHE_KEY = "studio:voices:v1"

# Автоозвучка реплики: on — всем, staff — только сотрудникам, off — как было до неё.
LINE_MODE_KEY = "studio_line_voice_mode"
LINE_MODES = ("off", "staff", "on")
# Окно речи ищем в звуке ролика: полоса голоса, RMS по 50 мс (F27/voice/window_proto.py).
SPEECH_RATE = 32000
SPEECH_STEP = 0.05
SPEECH_LOW_HZ, SPEECH_HIGH_HZ = 250, 3800
# Порог — фон ролика плюс 14 дБ, но не тише −45 и не громче −24 dBFS.
SPEECH_OVER_BED_DB = 14.0
SPEECH_FLOOR_DB, SPEECH_CEIL_DB = -45.0, -24.0
SPEECH_GAP_SEC = 0.5        # паузы короче — одна фраза
SPEECH_MIN_SEC = 0.2        # короче — щелчок, а не речь
SPEECH_TAIL_SEC = 0.25      # хвост гласной тише порога: глушим с запасом
SPEECH_EVENT_GAP_SEC = 1.0  # разрыв больше — другое событие: речь и свист падения
# Тихо — значит близко к фону, а не просто ниже порога речи: хвост гласной ниже
# порога, и петля из него снова произносила бы голос модели.
QUIET_OVER_BED_DB = 6.0
QUIET_MIN_SEC = 0.25        # короче не набрать ровного фона
QUIET_MAX_SEC = 3.0         # больше не нужно: это только заполнение провала
# Сведение реплики.
LINE_START_SEC = 0.5        # модель промолчала: реплика идёт с начала такта
LINE_MAX_TEMPO = 1.15       # быстрее — голос становится мультяшно-чужим
LINE_RAMP_SEC = 0.08        # спуск и подъём звука модели на краях окна
LINE_TAIL_SEC = 0.12        # затухание, если реплика упёрлась в конец ролика
LINE_PAUSE_DB = -38         # тише — пауза в озвучке
LINE_PAUSE_SEC = 0.1        # короче — смычка внутри слова, а не пауза
LINE_CUT_KEEP = 0.5         # пауза ради обрезки не должна съедать больше половины реплики
LINE_END_SLACK_SEC = 0.08   # конец тишины в mp3 стоит раньше длины файла: сдвиг кодера и округление
LINE_FIT_SLACK_SEC = 0.005  # начало округлено до 1 мс, такой перебор — не обрезка
LINE_TEMPO_SLACK = 0.0005   # темп округлён до 0,001: ошибка растёт с длиной реплики
LINE_LUFS = -16.0           # громкость реплики в итоге: как у диалога в роликах
LINE_GAIN_LIMIT_DB = 12.0   # битый замер не должен превратить голос в рёв
LINE_LIMIT = 0.89           # −1 dBFS: без клиппинга после суммы с фоном


class AudioNotConfigured(RuntimeError):
    """Ключ ElevenLabs не задан."""


class AudioProviderError(RuntimeError):
    """Провайдер ответил ошибкой. Текст — для лога, не для человека.

    status — код ответа (0, если до ответа не дошло): запасной путь кыргызской
    озвучки срабатывает только на отказ 4xx.
    """

    def __init__(self, *args, status: int = 0):
        super().__init__(*args)
        self.status = int(status or 0)


class AudioTooLong(RuntimeError):
    """Запись длиннее допустимого. Текст — для человека."""


# ------------------------------------------------------------ настройки ---

def _runtime(key: str, default):
    try:
        from adminapi.runtime import get_runtime

        return get_runtime(key, default)
    except Exception:  # noqa: BLE001 — настройки не должны ронять звук
        return default


def api_key() -> str:
    return str(_runtime("ELEVENLABS_API_KEY", getattr(settings, "ELEVENLABS_API_KEY", "")) or "").strip()


def is_configured() -> bool:
    return bool(api_key())


def line_mode() -> str:
    """Режим автоозвучки реплики. Непонятное значение — выключено: как было до неё."""
    value = str(_runtime(LINE_MODE_KEY, "on") or "on").strip().lower()
    return value if value in LINE_MODES else "off"


def line_enabled(user) -> bool:
    """Включена ли автоозвучка реплики для этого человека."""
    mode = line_mode()
    if mode == "on":
        return True
    return mode == "staff" and bool(getattr(user, "is_staff", False)
                                    or getattr(user, "is_superuser", False))


def line_ready(user) -> bool:
    """Озвучка реплики реально сработает: режим включён и ключ провайдера есть."""
    return line_enabled(user) and is_configured()


def _int_setting(key: str, setting: str, default: int) -> int:
    try:
        return max(0, int(float(_runtime(key, getattr(settings, setting, default)))))
    except (TypeError, ValueError):
        return default


def prices() -> dict:
    return {
        "voice_per_1k": _int_setting("studio_voice_credits_per_1k", "STUDIO_VOICE_CREDITS_PER_1K", 20),
        "voice_min": _int_setting("studio_voice_min_credits", "STUDIO_VOICE_MIN_CREDITS", 5),
        "music_per_min": _int_setting("studio_music_credits_per_min", "STUDIO_MUSIC_CREDITS_PER_MIN", 30),
        "sfx": _int_setting("studio_sfx_credits", "STUDIO_SFX_CREDITS", 10),
    }


def voice_price(text: str) -> int:
    p = prices()
    return max(p["voice_min"], math.ceil(len(text or "") * p["voice_per_1k"] / 1000))


def music_price(seconds: float) -> int:
    """По фактической длительности: 30 секунд — половина минутной цены."""
    return max(1, math.ceil(float(seconds) * prices()["music_per_min"] / 60))


def sfx_price() -> int:
    return prices()["sfx"]


# --------------------------------------------------------------- провайдер ---

def _headers() -> dict:
    key = api_key()
    if not key:
        raise AudioNotConfigured("ключ ElevenLabs не задан")
    return {"xi-api-key": key, "Content-Type": "application/json"}


def _post_audio(path: str, body: dict, timeout=None) -> bytes:
    r = requests.post(f"{API_URL}{path}", json=body, headers=_headers(),
                      params={"output_format": "mp3_44100_128"}, timeout=timeout or TIMEOUT)
    if not (200 <= r.status_code < 300):
        raise AudioProviderError(f"{path}: http {r.status_code}: {r.text[:300]}", status=r.status_code)
    if not r.content:
        raise AudioProviderError(f"{path}: пустой ответ")
    return r.content


def valid_voice_id(voice_id: str) -> bool:
    return bool(VOICE_ID_RE.match(str(voice_id or "")))


# Буквы, которых нет в русском: по ним видно кыргызскую реплику. Без них текст
# неотличим от русского, и читать его кыргызской моделью незачем.
_KY_LETTERS = frozenset("ңөү")


def line_lang(text: str) -> str:
    """Язык реплики для синтеза: "ky" — кыргызский, "" — решает модель."""
    return "ky" if _KY_LETTERS & set(str(text or "").lower()) else ""


def ky_model() -> str:
    """Модель для кыргызского (ELEVENLABS_KY_MODEL). Пусто — кыргызский читает общая.

    Только eleven_v3 знает кыргызский, и живьём она ещё не проверена: поэтому
    настройка, а не жёсткое имя, и запасной путь в tts.
    """
    default = os.environ.get("ELEVENLABS_KY_MODEL", "eleven_v3")
    return str(getattr(settings, "ELEVENLABS_KY_MODEL", default) or "").strip()


def _speak(text: str, voice_id: str, model: str, language_code: str | None, speed: float | None) -> bytes:
    body = {"text": text, "model_id": model}
    if language_code:
        body["language_code"] = language_code
    if speed:
        body["voice_settings"] = {"speed": float(speed)}
    return _post_audio(f"/v1/text-to-speech/{voice_id}", body)


def tts(text: str, voice_id: str, model: str | None = None, language_code: str | None = None,
        speed: float | None = None, lang: str | None = None) -> bytes:
    """Озвучить текст. Модель и язык не заданы — кыргызскую реплику читает ky_model().

    lang — язык реплики по мнению режиссёра ("ky" или "other"): он читал текст и
    узнает кыргызский и без букв ң ө ү. Нет его (ручная озвучка, старые сцены) — по буквам.

    Отказ 4xx на кыргызском (модель не поддержала голос или текст) — повтор на
    общей модели без языка: с акцентом лучше, чем без звука. 5xx и сеть — обычная
    ошибка: тут второй вызов помог бы только случайно.
    """
    if not valid_voice_id(voice_id):
        raise AudioProviderError("недопустимый идентификатор голоса")
    default = getattr(settings, "ELEVENLABS_TTS_MODEL", "eleven_multilingual_v2")
    kyrgyz = lang == "ky" if lang else bool(line_lang(text))
    special = ky_model() if model is None and language_code is None and kyrgyz else ""
    if special:
        try:
            return _speak(text, voice_id, special, "ky", speed)
        except AudioProviderError as exc:
            if not 400 <= exc.status < 500:
                raise
            logger.warning("кыргызская озвучка: %s отказала (%s), беру общую модель", special, exc.status)
    return _speak(text, voice_id, model or default, language_code, speed)


def sound_effect(prompt: str, seconds: float | None = None) -> bytes:
    body = {"text": prompt, "model_id": "eleven_text_to_sound_v2"}
    if seconds:
        body["duration_seconds"] = float(seconds)
    return _post_audio("/v1/sound-generation", body)


def music(prompt: str, seconds: float, instrumental: bool = True, timeout=None) -> bytes:
    """timeout — свой (connect, read) для длинной музыки: /v1/music отвечает, только
    когда трек готов, а пять минут склейки делаются дольше общих 180 с."""
    return _post_audio("/v1/music", {"prompt": prompt, "music_length_ms": int(float(seconds) * 1000),
                                     "force_instrumental": bool(instrumental)}, timeout=timeout)


def list_voices() -> list:
    """Готовые голоса ElevenLabs. Кэш на час: список меняется редко."""
    cached = cache.get(VOICES_CACHE_KEY)
    if cached is not None:
        return cached
    if not is_configured():
        return []
    r = requests.get(f"{API_URL}/v2/voices", headers=_headers(),
                     params={"page_size": 100, "voice_type": "default"}, timeout=(10, 30))
    if not (200 <= r.status_code < 300):
        raise AudioProviderError(f"voices: http {r.status_code}: {r.text[:200]}")
    out = []
    for v in (r.json() or {}).get("voices") or []:
        labels = v.get("labels") or {}
        out.append({
            "id": v.get("voice_id"),
            "name": v.get("name") or "",
            "gender": labels.get("gender") or "",
            "age": labels.get("age") or "",
            "accent": labels.get("accent") or "",
            "description": labels.get("descriptive") or labels.get("description") or "",
            "use_case": labels.get("use_case") or "",
            "preview": v.get("preview_url") or "",
        })
    out = [v for v in out if v["id"]]
    cache.set(VOICES_CACHE_KEY, out, 3600)
    return out


# Фраза для примера голоса — на языке человека. Клиент: «при нажатии ▶ пример
# должен звучать на русском»: родной образец ElevenLabs английский, и по нему не
# понять, как голос прозвучит в мультфильме.
PREVIEW_LINES = {
    "ru": "Привет! Я могу озвучить вашего героя. Вот так я звучу в мультфильме.",
    "en": "Hi! I can voice your hero. This is how I sound in a cartoon.",
    "kg": "Салам! Мен сиздин каарманыңызды үндөй алам. Мультфильмде мен ушундай угулам.",
}


def voice_preview(voice_id: str, lang: str = "ru") -> str:
    """Путь к примеру голоса на нужном языке. Делается один раз и хранится.

    Один пример — около семидесяти символов, то есть доли цента, и на каждый
    голос он генерируется единожды за всё время.
    """
    lang = lang if lang in PREVIEW_LINES else "ru"
    if not valid_voice_id(voice_id):
        raise AudioProviderError("недопустимый идентификатор голоса")
    path = f"cartoon/audio/previews/{voice_id}-{lang}.mp3"
    if default_storage.exists(path):
        return path
    # Чужих голосов не озвучиваем: только те, что есть в нашем списке.
    if voice_id not in {v["id"] for v in (list_voices() or [])}:
        raise AudioProviderError("голоса нет в списке")
    lock = f"studio:voice-preview:{voice_id}:{lang}"
    if not cache.add(lock, "1", timeout=120):
        raise AudioProviderError("пример уже готовится")
    try:
        raw = tts(PREVIEW_LINES[lang], voice_id)
        with tempfile.TemporaryDirectory() as tmp:
            src, dst = Path(tmp) / "in.mp3", Path(tmp) / "out.mp3"
            src.write_bytes(raw)
            ok = _run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", str(src),
                       "-vn", "-ac", "1", "-ar", "44100", "-b:a", "96k", str(dst)])
            data = dst.read_bytes() if ok and dst.exists() else raw
        # Имя фиксированное: второй раз не генерируем. Если хранилище добавило
        # суффикс (файл успел появиться) — берём уже лежащий.
        saved = default_storage.save(path, ContentFile(data))
        if saved != path:
            default_storage.delete(saved)
        return path
    finally:
        cache.delete(lock)


def healthcheck() -> dict:
    if not is_configured():
        return {"ok": False, "error": "Ключ ElevenLabs не задан."}
    try:
        cache.delete(VOICES_CACHE_KEY)
        return {"ok": True, "error": None, "voices": len(list_voices())}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": str(exc)[:200]}


# ------------------------------------------------------------------ ffmpeg ---

def _run(cmd: list, timeout: int = 180) -> bool:
    try:
        res = subprocess.run(cmd, capture_output=True, timeout=timeout)
    except Exception:
        logger.exception("звук: ffmpeg не запустился")
        return False
    if res.returncode != 0:
        logger.warning("звук: ffmpeg rc=%s err=%s", res.returncode, res.stderr[-500:])
        return False
    return True


def probe(path: Path) -> dict:
    """Длительность и наличие звука."""
    try:
        out = subprocess.run(["ffprobe", "-v", "error", "-print_format", "json", "-show_format",
                              "-show_streams", str(path)], capture_output=True, timeout=60).stdout
        data = json.loads(out or b"{}") or {}
    except Exception:
        return {"duration": 0.0, "audio": False}
    streams = data.get("streams") or []
    try:
        duration = float((data.get("format") or {}).get("duration") or 0)
    except (TypeError, ValueError):
        duration = 0.0
    return {"duration": duration, "audio": any(s.get("codec_type") == "audio" for s in streams)}


def _band_levels(path: Path) -> list[float]:
    """RMS полосы голоса по окнам 50 мс, dBFS. Только ffmpeg, без новых зависимостей.

    Частоту приводим первым фильтром, а не опцией -ar: она сработала бы уже после
    нарезки, и на звуке 48 кГц окно длилось бы 33 мс, а время уезжало бы в полтора раза.
    """
    size = int(SPEECH_RATE * SPEECH_STEP)
    chain = (f"aresample={SPEECH_RATE},aformat=channel_layouts=mono,"
             f"highpass=f={SPEECH_LOW_HZ},lowpass=f={SPEECH_HIGH_HZ},asetnsamples=n={size}:p=0,"
             "astats=metadata=1:reset=1:measure_overall=RMS_level:measure_perchannel=none,"
             "ametadata=print:key=lavfi.astats.Overall.RMS_level:file=-")
    cmd = ["ffmpeg", "-hide_banner", "-nostats", "-nostdin", "-i", str(path), "-vn",
           "-af", chain, "-f", "null", "-"]
    try:
        res = subprocess.run(cmd, capture_output=True, timeout=120)
    except Exception:
        logger.exception("звук: окно речи — ffmpeg не запустился")
        return []
    if res.returncode != 0:
        logger.warning("звук: окно речи rc=%s err=%s", res.returncode, res.stderr[-300:])
        return []
    found = re.findall(rb"RMS_level=(-?[0-9.]+|-?inf|nan)", res.stdout)
    return [float(v) if v not in (b"-inf", b"inf", b"nan") else -120.0 for v in found]


def _bed_level(levels: list[float]) -> float:
    """Тихий фон ролика: 20-й перцентиль."""
    return sorted(levels)[len(levels) // 5]


def _speech_limit(bed: float) -> float:
    return min(SPEECH_CEIL_DB, max(SPEECH_FLOOR_DB, bed + SPEECH_OVER_BED_DB))


def _speech_marks(levels: list[float]) -> list[bool]:
    """Где звук громче порога: фон ролика плюс 14 дБ."""
    if not levels:
        return []
    limit = _speech_limit(_bed_level(levels))
    return [value > limit for value in levels]


def _runs(marks: list[bool], wanted: bool = True) -> list[list[float]]:
    """Непрерывные куски со значением wanted, секунды."""
    runs, start = [], None
    for i, flag in enumerate([*marks, not wanted]):
        if flag == wanted and start is None:
            start = i
        elif flag != wanted and start is not None:
            runs.append([start * SPEECH_STEP, i * SPEECH_STEP])
            start = None
    return runs


def _speech_pieces(marks: list[bool]) -> list[list[float]]:
    """Куски речи: короткие паузы склеены, щелчки выброшены."""
    merged: list[list[float]] = []
    for run in _runs(marks):
        if merged and run[0] - merged[-1][1] < SPEECH_GAP_SEC:
            merged[-1][1] = run[1]
        else:
            merged.append(run)
    return [run for run in merged if run[1] - run[0] >= SPEECH_MIN_SEC]


def window_from_levels(levels: list[float]) -> tuple[float, float] | None:
    """Окно речи: от начала первого куска до конца последнего с запасом на хвост
    гласной. None — модель молчала.

    Глушим всё, что может быть голосом модели: потерять свист падения не страшно,
    а второй голос поверх реплики — именно то, на что жаловался клиент.
    """
    pieces = _speech_pieces(_speech_marks(levels))
    if not pieces:
        return None
    return round(pieces[0][0], 2), round(pieces[-1][1] + SPEECH_TAIL_SEC, 2)


def lips_from_levels(levels: list[float]) -> float | None:
    """Где ставить реплику: начало самой длинной группы кусков окна.

    Модель заказывает и эффекты: свист за четыре секунды до слов — тоже кусок окна.
    Если поставить реплику на него, она прозвучит задолго до того, как герой
    откроет рот. Настоящая речь обычно самая длинная из групп.
    """
    pieces = _speech_pieces(_speech_marks(levels))
    if not pieces:
        return None
    groups = [list(pieces[0])]
    for piece in pieces[1:]:
        if piece[0] - groups[-1][1] < SPEECH_EVENT_GAP_SEC:
            groups[-1][1] = piece[1]
        else:
            groups.append(list(piece))
    return round(max(groups, key=lambda group: group[1] - group[0])[0], 2)


def quiet_from_levels(levels: list[float]) -> tuple[float, float] | None:
    """Самый длинный тихий кусок ролика — из него заполняем провал под репликой.

    От краёв отступаем на окно: там ещё хвост соседней речи. Нет такого куска —
    провал остаётся тихим: это лучше петли из голоса модели.
    """
    if not levels:
        return None
    bed = _bed_level(levels)
    limit = min(_speech_limit(bed), bed + QUIET_OVER_BED_DB)
    runs = [(a + SPEECH_STEP, b - SPEECH_STEP) for a, b in _runs([value < limit for value in levels])]
    runs = [run for run in runs if run[1] - run[0] >= QUIET_MIN_SEC]
    if not runs:
        return None
    start, end = max(runs, key=lambda run: run[1] - run[0])
    return round(start, 2), round(min(end, start + QUIET_MAX_SEC), 2)


def speech_window(path) -> tuple[float, float] | None:
    """Где в ролике говорит модель: (начало, конец) в секундах или None. Бесплатно."""
    return window_from_levels(_band_levels(Path(path)))


def scene_window(scene) -> tuple[float, float] | None:
    """Окно речи снятой сцены. Файл ролика может лежать не на этом диске."""
    if not scene.video:
        return None
    with tempfile.TemporaryDirectory() as tmp:
        video = Path(tmp) / "scene.mp4"
        with default_storage.open(scene.video, "rb") as fh:
            video.write_bytes(fh.read())
        return speech_window(video)


def stored_window(scene) -> tuple[float, float] | None:
    """Окно речи, записанное в сцене."""
    start, end = getattr(scene, "speech_start", None), getattr(scene, "speech_end", None)
    if start is None or end is None or end <= start:
        return None
    return float(start), float(end)


def window_json(scene) -> list | None:
    """Окно речи для API: [начало, конец] или null."""
    window = stored_window(scene)
    return list(window) if window else None


def fit_line(duration: float, window: tuple[float, float] | None, clip: float,
             lips: float | None = None) -> tuple[float, float]:
    """Куда поставить реплику длиной duration и как её ускорить: (начало, темп).

    Короче окна — на начало окна. Длиннее — ускоряем до ×1,15. Всё равно длиннее —
    пусть выходит за окно до конца ролика; а чтобы конец ролика не отрезал слово,
    сдвигаем начало раньше окна. clip — длина ролика, 0 — неизвестна.
    lips — где в окне начинается настоящая речь (lips_from_levels): реплика встаёт
    туда, а если до конца ролика не хватает места — так близко к губам, как влезет.
    """
    duration = max(0.0, float(duration or 0))
    start, end = window if window else (LINE_START_SEC, clip or LINE_START_SEC + duration)
    if clip:
        end = min(end, clip)
    if lips is not None and start < lips:
        start = max(start, min(lips, (clip or end) - duration / LINE_MAX_TEMPO))
    room = max(0.0, end - start)
    tempo = 1.0
    if room and duration > room:
        tempo = min(LINE_MAX_TEMPO, duration / room)
    spoken = duration / tempo
    if clip and start + spoken > clip:
        start = max(0.0, clip - spoken)
    return round(start, 3), round(tempo, 3)


def _loudness(path: Path) -> float | None:
    """Интегральная громкость файла, LUFS. None — не измерилась.

    Короче 0,4 с ebur128 не набирает блока: «Да!» меряем с тишиной на хвосте.
    """
    for chain in ("ebur128", "apad=pad_dur=0.6,ebur128"):
        try:
            res = subprocess.run(["ffmpeg", "-hide_banner", "-nostats", "-nostdin", "-i", str(path), "-vn",
                                  "-af", chain, "-f", "null", "-"], capture_output=True, timeout=60)
        except Exception:
            logger.exception("звук: громкость — ffmpeg не запустился")
            return None
        found = re.findall(rb"I:\s+(-?[0-9.]+) LUFS", res.stderr)
        value = float(found[-1]) if found else None
        if value is not None and value > -60:
            return value
    return None


def _pauses(path: Path) -> list[tuple[float, float]]:
    """Паузы в озвучке, секунды: нужны, чтобы не считать хвост тишины речью и резать по паузе."""
    try:
        res = subprocess.run(["ffmpeg", "-hide_banner", "-nostats", "-nostdin", "-i", str(path), "-vn",
                              "-af", f"silencedetect=noise={LINE_PAUSE_DB}dB:d={LINE_PAUSE_SEC}",
                              "-f", "null", "-"], capture_output=True, timeout=60)
    except Exception:
        logger.exception("звук: паузы — ffmpeg не запустился")
        return []
    starts = [float(v) for v in re.findall(rb"silence_start: (-?[0-9.]+)", res.stderr)]
    ends = [float(v) for v in re.findall(rb"silence_end: (-?[0-9.]+)", res.stderr)]
    return [(max(0.0, a), b) for a, b in zip(starts, ends)]


def _spoken_length(duration: float, pauses: list) -> float:
    """Длина озвучки без тишины в конце: из-за неё реплику ускоряли бы зря."""
    if pauses and pauses[-1][1] >= duration - LINE_END_SLACK_SEC and pauses[-1][0] > 0:
        return pauses[-1][0]
    return duration


def _cut_needed(start: float, duration: float, tempo: float, clip: float) -> bool:
    """Реплика правда не влезла в ролик, а не перебрала на округлении начала и темпа."""
    slack = LINE_FIT_SLACK_SEC + duration * LINE_TEMPO_SLACK
    return bool(clip) and start + duration / tempo > clip + slack


def _cut_at(room: float, tempo: float, pauses: list) -> float:
    """Где гасить реплику, которая не влезла в ролик: на последней паузе в пределах
    room, а если её нет или она слишком рано — перед самым концом ролика."""
    last = max(0.0, room - LINE_TAIL_SEC)
    fits = [start / tempo for start, _ in pauses if start / tempo <= last]
    return fits[-1] if fits and fits[-1] >= room * LINE_CUT_KEEP else last


def _line_chain(index: int, label: str, track, local: Path, window, clip: float, *, place: bool,
                lips: float | None = None) -> str:
    """Цепочка фильтров реплики: темп, громкость −16 LUFS, обрезка у конца ролика, место.

    place — поставить по окну и запомнить в track.start_sec (новая реплика или
    пересъёмка). Иначе остаётся момент дорожки: его мог поправить человек.
    """
    pauses = _pauses(local)
    duration = _spoken_length(float(track.duration or 0), pauses)
    start, tempo = fit_line(duration, window, clip, lips)
    if place:
        track.start_sec = start
    start = max(0.0, float(track.start_sec))
    chain = [f"[{index}:a]aresample=44100"]
    if tempo > 1.001:
        chain.append(f"atempo={tempo:.3f}")
    loudness = _loudness(local)
    if loudness is not None:
        gain = max(-LINE_GAIN_LIMIT_DB, min(LINE_GAIN_LIMIT_DB, LINE_LUFS - loudness))
        chain.append(f"volume={gain:.2f}dB")
    if _cut_needed(start, duration, tempo, clip):
        chain.append(f"afade=t=out:st={_cut_at(clip - start, tempo, pauses):.3f}:d={LINE_TAIL_SEC}")
    volume = min(VOLUME_MAX, max(VOLUME_MIN, float(track.volume)))
    chain.append(f"adelay={int(start * 1000)}:all=1")
    chain.append(f"volume={volume:.2f}{label}")
    return ",".join(chain)


def _muted_scene_sound(volume: float, window: tuple[float, float], quiet, clip: float) -> tuple[list, list]:
    """Звук ролика с заглушённой речью модели и заполненным провалом.

    Спуски по 80 мс, чтобы не щёлкало; asetnsamples дробит кадры, иначе громкость
    менялась бы ступеньками по 23 мс. Заполнение — петля тихого куска этого же
    ролика на его же уровне: совсем без фона сцена проваливалась бы в тишину.
    Петля туда-обратно: на стыке волна продолжается сама, и гасить края не нужно.
    """
    start, end = window
    if clip:
        end = min(end, clip)
    mute = (f"volume='max(0,min(1,max(({start:.3f}-t)/{LINE_RAMP_SEC},(t-{end:.3f})/{LINE_RAMP_SEC})))'"
            ":eval=frame")
    head = f"[0:a]aresample=44100,volume={volume:.2f}"
    if not quiet:
        return [f"{head},asetnsamples=n=256:p=0,{mute}[s0]"], ["[s0]"]
    q_start, q_end = quiet
    piece = q_end - q_start
    fill_at = max(0.0, start - LINE_RAMP_SEC)
    fill = end + LINE_RAMP_SEC - fill_at
    parts = [
        f"{head},asplit=2[scene][bedsrc]",
        f"[scene]asetnsamples=n=256:p=0,{mute}[s0]",
        f"[bedsrc]atrim=start={q_start:.3f}:end={q_end:.3f},asetpts=PTS-STARTPTS,asplit=2[bedfw][bedrev]",
        "[bedrev]areverse[bedback]",
        f"[bedfw][bedback]concat=n=2:v=0:a=1,aloop=loop=-1:size={int(piece * 44100) * 2},"
        f"atrim=end={fill:.3f},asetpts=PTS-STARTPTS,"
        f"afade=t=in:d={LINE_RAMP_SEC},afade=t=out:st={fill - LINE_RAMP_SEC:.3f}:d={LINE_RAMP_SEC},"
        f"adelay={int(fill_at * 1000)}:all=1[bed]",
    ]
    return parts, ["[s0]", "[bed]"]


# Что принимаем загрузкой «свой голос»: диктофон браузера (webm, ogg, m4a) и
# обычные аудиофайлы. Расширение приходит от человека и уходит в имя файла для
# ffmpeg, а по расширению ffmpeg выбирает разборщик — плейлисты (.m3u8) и
# списки склейки (.ffconcat) умеют читать чужие файлы и ходить в сеть.
# Диктофоны телефонов пишут ещё в amr/3gp (Android), caf (iPhone), встречаются
# flac, aiff и wma — это обычные контейнеры звука, ffmpeg их просто декодирует.
UPLOAD_EXTENSIONS = ("mp3", "m4a", "aac", "wav", "ogg", "oga", "opus", "webm", "mp4", "mov",
                     "amr", "awb", "3gp", "3gpp", "3ga", "3g2", "flac", "aif", "aiff", "aifc",
                     "caf", "wma", "mka")


def upload_suffix(filename: str) -> str:
    """Расширение загрузки из белого списка (".mp3") или пусто — такой файл не берём."""
    name = str(filename or "").strip().lower()
    ext = name.rsplit(".", 1)[-1] if "." in name else ""
    return f".{ext}" if ext in UPLOAD_EXTENSIONS else ""


def _nice() -> list[str]:
    """«nice -n 10» перед пересборкой на Linux: она идёт и в потоке API (загрузки),
    и чужой файл не должен отнимать процессор у сайта."""
    if os.name != "posix":
        return []
    path = shutil.which("nice")
    return [path, "-n", "10"] if path else []


# Пересборка пишет mp3 160 кбит/с с постоянным битрейтом: 20 000 байт на секунду.
OUTPUT_BYTES_PER_S = 160_000 // 8
# Запас сверх потолка длины: две секунды звука и место под теги и заголовок Xing.
OUTPUT_SLACK_S = 2
OUTPUT_SLACK_BYTES = 256 * 1024


def output_cap(max_seconds: float) -> int:
    """Потолок байтов пересобранного mp3 для потолка длины max_seconds."""
    return int((float(max_seconds) + OUTPUT_SLACK_S) * OUTPUT_BYTES_PER_S) + OUTPUT_SLACK_BYTES


def save_audio(raw: bytes, suffix: str = ".mp3", folder: str = "cartoon/audio",
               max_seconds: float | None = None, input_options: list[str] | tuple = ()) -> tuple[str, float]:
    """Любой звук (mp3, webm с диктофона, m4a) → mp3 в хранилище. (путь, секунды).

    input_options — опции чтения перед -i (склейка: тот же демуксер и те же
    декодеры, что у её строгого разбора).
    """
    ext = suffix.lstrip(".").lower() if suffix else ""
    suffix = f".{ext}" if ext in UPLOAD_EXTENSIONS else ".bin"
    # Длину в заголовке пишет кто угодно: «10 секунд» могут оказаться часами
    # звука, и без -t ffmpeg честно декодировал бы их все, а потолок ниже
    # отказал бы только потом. С -t работа ограничена потолком + секундой.
    # -t ffmpeg меряет по меткам времени кадров, а их тоже пишет файл (Matroska,
    # Ogg, ASF): метки по кругу 0–5 с, и -t не наступал бы никогда. asetpts
    # переставляет метки по счёту декодированных сэмплов — потолок считает звук.
    # Но счётчик asetpts живёт в графе фильтров, а граф ffmpeg собирает заново при
    # каждой смене частоты или раскладки посреди файла — и метки снова с нуля.
    # -fs — потолок байтов готового mp3 (160 кбит/с = 20 000 Б/с): от меток и от
    # графа он не зависит, а обрезанный по нему файл длиннее потолка — его
    # отклонит проверка длины ниже.
    # Теги и главы чужого файла ffmpeg иначе переносит в ID3 готового mp3, и они
    # тоже съедают -fs: честный трек на пять минут с мегабайтом текста в тегах
    # молча обрезался бы. Нам они не нужны — в mp3 только звук. Звук провайдера
    # (без потолка) пересобирается как раньше: теги там крошечные, а -fs нет.
    limit = (["-t", f"{float(max_seconds) + 1:g}", "-af", "asetpts=N/SR/TB",
              "-fs", str(output_cap(max_seconds)), "-map_metadata", "-1", "-map_chapters", "-1"]
             if max_seconds else [])
    with tempfile.TemporaryDirectory() as tmp:
        src = Path(tmp) / f"in{suffix}"
        dst = Path(tmp) / "out.mp3"
        src.write_bytes(raw)
        # Вход — только локальный файл: даже если внутри окажется плейлист,
        # ffmpeg не пойдёт по ссылкам из него ни в сеть, ни в другие протоколы.
        if not _run([*_nice(), "ffmpeg", "-hide_banner", "-loglevel", "error", "-nostdin", "-y",
                     "-protocol_whitelist", "file", *input_options, "-i", f"file:{src}", *limit,
                     "-vn", "-ac", "2", "-ar", "44100", "-b:a", "160k", str(dst)]):
            raise AudioProviderError("звук не читается")
        info = probe(dst)
        if info["duration"] <= 0:
            raise AudioProviderError("пустая запись")
        # 15 МБ сильно сжатого звука — это часы: без потолка по длительности
        # такая дорожка растягивала бы сведение и хранилище.
        if max_seconds and info["duration"] > max_seconds:
            raise AudioTooLong(f"звук длиннее {int(max_seconds)} секунд")
        path = default_storage.save(f"{folder}/{uuid.uuid4().hex}.mp3", ContentFile(dst.read_bytes()))
        return path, round(info["duration"], 2)


def mix_scene(scene, line=None) -> str:
    """Свести видео сцены со всеми её дорожками. Путь сведённого ролика или "".

    Звук самой сцены остаётся (с громкостью сцены), дорожки ложатся со своими
    задержкой и громкостью. Длина — ровно как у видео: реплика, вылезшая за
    конец сцены, обрезается (интерфейс об этом предупреждает).

    line — реплика, которая в базу ещё не записана: голос сводят до списания, а
    дорожку пишут с деньгами одной транзакцией (ffmpeg дольше замка строки). Она
    заменяет дорожку line сцены; start_sec ставится здесь — тут известна длина.

    Дорожка line заменяет речь модели: в окне звук ролика глушится (если окна
    нет — модель молчала, глушить нечего), сверху на −16 LUFS идёт реплика.
    """
    tracks = list(scene.audio_tracks.exclude(file="").filter(status="ready")
                  .order_by("start_sec", "id"))
    if line is not None:
        tracks = [t for t in tracks if t.kind != "line"] + [line]
    if not scene.video or not tracks:
        return ""
    with tempfile.TemporaryDirectory() as tmp:
        tmpdir = Path(tmp)
        video = tmpdir / "scene.mp4"
        with default_storage.open(scene.video, "rb") as fh:
            video.write_bytes(fh.read())
        vinfo = probe(video)
        # Длительность неизвестна (битый контейнер) — тогда не режем вовсе:
        # обрезка «на глазок» в 5 секунд молча испортила бы длинную сцену.
        duration = vinfo["duration"]

        inputs = ["-i", str(video)]
        parts, labels = [], []
        window = stored_window(scene)
        levels = _band_levels(video) if window and any(t.kind == "line" for t in tracks) else []
        has_line = False
        for i, track in enumerate(tracks, start=1):
            local = tmpdir / f"t{i}.mp3"
            try:
                with default_storage.open(track.file, "rb") as fh:
                    local.write_bytes(fh.read())
            except Exception:
                logger.warning("сведение: дорожка %s не читается, пропускаю", track.pk)
                continue
            inputs += ["-i", str(local)]
            idx = len(inputs) // 2 - 1
            if track.kind == "line":
                has_line = True
                parts.append(_line_chain(idx, f"[t{i}]", track, local, window, duration,
                                         place=track is line, lips=lips_from_levels(levels)))
            else:
                delay = max(0, int(float(track.start_sec) * 1000))
                vol = min(VOLUME_MAX, max(VOLUME_MIN, float(track.volume)))
                parts.append(f"[{idx}:a]adelay={delay}:all=1,volume={vol:.2f}[t{i}]")
            labels.append(f"[t{i}]")
        # Глушим, только если реплика действительно легла: дорожка могла не прочитаться.
        if vinfo["audio"]:
            vol = min(VOLUME_MAX, max(VOLUME_MIN, float(scene.sound_volume)))
            if has_line and window:
                own, own_labels = _muted_scene_sound(vol, window, quiet_from_levels(levels), duration)
                parts += own
                labels += own_labels
            else:
                parts.append(f"[0:a]volume={vol:.2f}[s0]")
                labels.append("[s0]")
        if not labels:
            return ""
        base_len = duration if duration > 0 else max(
            (float(t.start_sec) + float(t.duration) for t in tracks), default=5.0)
        parts.append(f"anullsrc=r=44100:cl=stereo,atrim=0:{base_len:.3f}[base]")
        # Лимитер — только с репликой: голос подняли до −16 LUFS, и сумма с фоном
        # не должна клиппить. Сведение без реплики остаётся как было.
        tail = f"[sum];[sum]alimiter=limit={LINE_LIMIT}:attack=5:release=50:level=0[aout]" if has_line else "[aout]"
        mix = "[base]" + "".join(labels) + (
            f"amix=inputs={len(labels) + 1}:duration=first:dropout_transition=0:normalize=0{tail}")
        out = tmpdir / "mixed.mp4"
        cmd = (["ffmpeg", "-hide_banner", "-loglevel", "error", "-y"] + inputs
               + ["-filter_complex", ";".join(parts + [mix]), "-map", "0:v", "-map", "[aout]",
                  "-c:v", "copy", "-c:a", "aac", "-b:a", "192k"]
               + (["-t", f"{duration:.3f}"] if duration > 0 else ["-shortest"])
               + ["-movflags", "+faststart", str(out)])
        if not _run(cmd):
            raise AudioProviderError("сведение не удалось")
        return default_storage.save(f"cartoon/scenes/mixed/{uuid.uuid4().hex}.mp4",
                                    ContentFile(out.read_bytes()))


class MixBusy(RuntimeError):
    """Сцену уже сводит другой запрос."""


def mix_lock_key(scene_id: int) -> str:
    return f"studio:mix:{scene_id}"


@contextmanager
def mix_lock(scene_id: int, wait: bool = True):
    """Замок сведения сцены: два ffmpeg разом затирают работу друг друга.

    wait=False — не ждать, а сразу MixBusy. Снимаем только свой замок: чужой
    принадлежит идущему сведению.
    """
    import time

    lock, token = mix_lock_key(scene_id), uuid.uuid4().hex
    owned = cache.add(lock, token, timeout=180)
    if not owned and not wait:
        raise MixBusy(f"сцена {scene_id} уже сводится")
    if not owned:
        for _ in range(20):
            time.sleep(3)
            if cache.add(lock, token, timeout=180):
                owned = True
                break
        else:
            logger.warning("сведение сцены %s: замок занят, свожу без него", scene_id)
    try:
        yield
    finally:
        if owned and cache.get(lock) == token:
            cache.delete(lock)


def remix_scene(scene, wait: bool = True) -> None:
    """Пересобрать сведённый ролик сцены (или убрать, если дорожек нет).

    Под общим замком: сцену сводит и окно звука, и озвучка всего мультфильма.
    Ждём чужое сведение и делаем своё — дорожки читаются заново, поэтому ничего
    не теряется.

    wait=False — не ждать, а сразу MixBusy: так отвечает окно звука («сцена уже
    сводится»), не держа веб-воркер. Замок берёт только эта функция: раньше
    вьюха брала его сама, а здесь ждала саму себя минуту на каждое сведение.
    """
    with mix_lock(scene.pk, wait=wait):
        # Сцену могли переснять, пока мы ждали: вместе с роликом сменилось и окно речи.
        scene.refresh_from_db(fields=["video", "mixed_video", "speech_start", "speech_end"])
        path = mix_scene(scene) if scene.video else ""
        if path != scene.mixed_video:
            scene.mixed_video = path
            scene.save(update_fields=["mixed_video", "updated_at"])


def has_audio(raw: bytes) -> bool:
    """Есть ли звуковая дорожка в готовом ролике."""
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "part.mp4"
        path.write_bytes(raw)
        return bool(probe(path)["audio"])


def add_silence(raw: bytes) -> bytes:
    """Добавить немому ролику тихую дорожку. При осечке — вернуть как есть."""
    with tempfile.TemporaryDirectory() as tmp:
        src, dst = Path(tmp) / "in.mp4", Path(tmp) / "out.mp4"
        src.write_bytes(raw)
        ok = _run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", str(src),
                   "-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo", "-c:v", "copy",
                   "-c:a", "aac", "-b:a", "128k", "-shortest", "-movflags", "+faststart",
                   str(dst)])
        return dst.read_bytes() if ok and dst.exists() and dst.stat().st_size else raw


def align_audio(parts: list) -> list:
    """Уравнять части перед склейкой: со звуком — либо все, либо никто.

    Склейка берёт звук, только если он есть во ВСЕХ частях. Без этого одна
    неозвученная сцена делала немым весь мультфильм — вместе со сценами, за
    озвучку которых человек заплатил.
    """
    if len(parts) < 2:
        return parts
    flags = [has_audio(p) for p in parts]
    if all(flags) or not any(flags):
        return parts
    return [p if ok else add_silence(p) for p, ok in zip(parts, flags)]
