"""Звук студии: голоса, музыка и эффекты ElevenLabs и сведение с видео сцены.

Клиент: «каждая сцена должна иметь возможность озвучки» — ИИ-голос по тексту,
свой голос, фоновая музыка и эффекты, у каждой дорожки громкость и момент
начала, а на выходе всё само собирается в сцену и мультфильм.

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


class AudioNotConfigured(RuntimeError):
    """Ключ ElevenLabs не задан."""


class AudioProviderError(RuntimeError):
    """Провайдер ответил ошибкой. Текст — для лога, не для человека."""


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
        raise AudioProviderError(f"{path}: http {r.status_code}: {r.text[:300]}")
    if not r.content:
        raise AudioProviderError(f"{path}: пустой ответ")
    return r.content


def valid_voice_id(voice_id: str) -> bool:
    return bool(VOICE_ID_RE.match(str(voice_id or "")))


def tts(text: str, voice_id: str) -> bytes:
    if not valid_voice_id(voice_id):
        raise AudioProviderError("недопустимый идентификатор голоса")
    model = getattr(settings, "ELEVENLABS_TTS_MODEL", "eleven_multilingual_v2")
    return _post_audio(f"/v1/text-to-speech/{voice_id}", {"text": text, "model_id": model})


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


def mix_scene(scene) -> str:
    """Свести видео сцены со всеми её дорожками. Путь сведённого ролика или "".

    Звук самой сцены остаётся (с громкостью сцены), дорожки ложатся со своими
    задержкой и громкостью. Длина — ровно как у видео: реплика, вылезшая за
    конец сцены, обрезается (интерфейс об этом предупреждает).
    """
    tracks = list(scene.audio_tracks.exclude(file="").filter(status="ready")
                  .order_by("start_sec", "id"))
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
        if vinfo["audio"]:
            vol = min(VOLUME_MAX, max(VOLUME_MIN, float(scene.sound_volume)))
            parts.append(f"[0:a]volume={vol:.2f}[s0]")
            labels.append("[s0]")
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
            delay = max(0, int(float(track.start_sec) * 1000))
            vol = min(VOLUME_MAX, max(VOLUME_MIN, float(track.volume)))
            parts.append(f"[{idx}:a]adelay={delay}:all=1,volume={vol:.2f}[t{i}]")
            labels.append(f"[t{i}]")
        if not labels:
            return ""
        base_len = duration if duration > 0 else max(
            (float(t.start_sec) + float(t.duration) for t in tracks), default=5.0)
        parts.append(f"anullsrc=r=44100:cl=stereo,atrim=0:{base_len:.3f}[base]")
        mix = "[base]" + "".join(labels) + (
            f"amix=inputs={len(labels) + 1}:duration=first:dropout_transition=0:normalize=0[aout]")
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


def remix_scene(scene, wait: bool = True) -> None:
    """Пересобрать сведённый ролик сцены (или убрать, если дорожек нет).

    Под общим замком: сцену сводит и окно звука, и озвучка всего мультфильма,
    а два ffmpeg разом затирают работу друг друга. Ждём чужое сведение и
    делаем своё — дорожки читаются заново, поэтому ничего не теряется.

    wait=False — не ждать, а сразу MixBusy: так отвечает окно звука («сцена уже
    сводится»), не держа веб-воркер. Замок берёт только эта функция: раньше
    вьюха брала его сама, а здесь ждала саму себя минуту на каждое сведение.
    Снимаем только свой замок — чужой принадлежит идущему сведению.
    """
    import time

    lock, token = mix_lock_key(scene.pk), uuid.uuid4().hex
    owned = cache.add(lock, token, timeout=180)
    if not owned and not wait:
        raise MixBusy(f"сцена {scene.pk} уже сводится")
    if not owned:
        for _ in range(20):
            time.sleep(3)
            if cache.add(lock, token, timeout=180):
                owned = True
                break
        else:
            logger.warning("сведение сцены %s: замок занят, свожу без него", scene.pk)
    try:
        # Сцену могли переснять, пока мы ждали.
        scene.refresh_from_db(fields=["video", "mixed_video"])
        path = mix_scene(scene) if scene.video else ""
        if path != scene.mixed_video:
            scene.mixed_video = path
            scene.save(update_fields=["mixed_video", "updated_at"])
    finally:
        if owned and cache.get(lock) == token:
            cache.delete(lock)


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
