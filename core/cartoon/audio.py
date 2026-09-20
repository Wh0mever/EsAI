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
import re
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
VOICE_ID_RE = re.compile(r"^[A-Za-z0-9_-]{4,64}$")
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


def _post_audio(path: str, body: dict) -> bytes:
    r = requests.post(f"{API_URL}{path}", json=body, headers=_headers(),
                      params={"output_format": "mp3_44100_128"}, timeout=TIMEOUT)
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


def music(prompt: str, seconds: float, instrumental: bool = True) -> bytes:
    return _post_audio("/v1/music", {"prompt": prompt, "music_length_ms": int(float(seconds) * 1000),
                                     "force_instrumental": bool(instrumental)})


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


def save_audio(raw: bytes, suffix: str = ".mp3", folder: str = "cartoon/audio",
               max_seconds: float | None = None) -> tuple[str, float]:
    """Любой звук (mp3, webm с диктофона, m4a) → mp3 в хранилище. (путь, секунды)."""
    with tempfile.TemporaryDirectory() as tmp:
        src = Path(tmp) / f"in{suffix or '.bin'}"
        dst = Path(tmp) / "out.mp3"
        src.write_bytes(raw)
        if not _run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", str(src),
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
    tracks = list(scene.audio_tracks.exclude(file="").order_by("start_sec", "id"))
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


def remix_scene(scene) -> None:
    """Пересобрать сведённый ролик сцены (или убрать, если дорожек нет).

    Под общим замком: сцену сводит и окно звука, и озвучка всего мультфильма,
    а два ffmpeg разом затирают работу друг друга. Ждём чужое сведение и
    делаем своё — дорожки читаются заново, поэтому ничего не теряется.
    """
    import time

    lock = f"studio:mix:{scene.pk}"
    for _ in range(20):
        if cache.add(lock, "1", timeout=180):
            break
        time.sleep(3)
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
