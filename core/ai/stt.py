"""Распознавание голосовых сообщений.

На сайте голос распознаёт браузер (Web Speech API), и серверу это ничего не
стоит. В Telegram голосовое приходит файлом, поэтому распознаём его сами —
той же моделью через OpenRouter, что отвечает в чате, и берём за это
кредиты по минутам. Цена плоская и известна заранее: человек видит её до
того, как что-то спишется.
"""
from __future__ import annotations

import base64
import logging
import math
import re
import subprocess

from django.conf import settings

logger = logging.getLogger(__name__)


class SttError(RuntimeError):
    """Распознать не получилось. Кредиты в этом случае не списываются."""


def _setting(name: str, default):
    value = getattr(settings, name, default)
    return default if value in (None, "") else value


def max_seconds() -> int:
    return int(_setting("STT_MAX_SECONDS", 120))


def max_bytes() -> int:
    return int(_setting("STT_MAX_BYTES", 5 * 1024 * 1024))


def credits_per_minute() -> int:
    try:
        from adminapi.runtime import get_runtime

        return max(0, int(get_runtime("STT_CREDITS_PER_MINUTE",
                                      _setting("STT_CREDITS_PER_MINUTE", 2))))
    except Exception:
        return int(_setting("STT_CREDITS_PER_MINUTE", 2))


def model_id() -> str:
    try:
        from adminapi.runtime import get_runtime

        return str(get_runtime("STT_MODEL", _setting("STT_MODEL", "google/gemini-2.5-flash-lite")))
    except Exception:
        return str(_setting("STT_MODEL", "google/gemini-2.5-flash-lite"))


def price_for(seconds: float) -> int:
    """Сколько кредитов стоит запись такой длины. Минимум один."""
    per_minute = credits_per_minute()
    if per_minute <= 0:
        return 0
    return max(1, math.ceil(max(0.0, float(seconds)) / 60.0 * per_minute))


_DURATION_RE = re.compile(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)")
_MEAN_VOLUME_RE = re.compile(r"mean_volume:\s*(-?\d+(?:\.\d+)?)\s*dB")

# Тише этого — тишина или шум микрофона: модели на такое отвечают выдуманным
# текстом (проверено: 2 секунды тишины → «Привет, это я, я не смогу прийти»),
# а человек платит за распознавание того, чего не говорил.
SILENCE_DB = -45.0


def silence_threshold_db() -> float:
    try:
        return float(_setting("STT_SILENCE_DB", SILENCE_DB))
    except (TypeError, ValueError):
        return SILENCE_DB


def convert_to_mp3(raw: bytes) -> tuple[bytes, float, float | None]:
    """Любой формат Telegram (ogg/opus, m4a, mp4) → mp3 16 кГц моно.

    Возвращает (mp3, секунды, средняя громкость в дБ). Длительность и
    громкость читаем из отчёта самого ffmpeg за один проход — ни ffprobe, ни
    второго прогона не нужно. Если длительности нет, оцениваем по битрейту.
    """
    try:
        proc = subprocess.run(
            ["ffmpeg", "-hide_banner", "-nostdin", "-i", "pipe:0", "-vn", "-ac", "1",
             "-ar", "16000", "-af", "volumedetect", "-b:a", "48k", "-f", "mp3", "pipe:1"],
            input=raw, capture_output=True, timeout=60, check=False,
        )
    except FileNotFoundError as exc:
        raise SttError("ffmpeg отсутствует") from exc
    except subprocess.TimeoutExpired as exc:
        raise SttError("ffmpeg не уложился в минуту") from exc
    if proc.returncode != 0 or not proc.stdout:
        raise SttError(f"ffmpeg: {proc.stderr.decode('utf-8', 'ignore')[-200:]}")

    report = proc.stderr.decode("utf-8", "ignore")
    seconds = 0.0
    match = _DURATION_RE.search(report)
    if match:
        hours, minutes, secs = match.groups()
        seconds = int(hours) * 3600 + int(minutes) * 60 + float(secs)
    if seconds <= 0:
        seconds = len(proc.stdout) * 8 / 48000.0
    volume = None
    match = _MEAN_VOLUME_RE.search(report)
    if match:
        volume = float(match.group(1))
    return proc.stdout, seconds, volume


def is_silent(volume: float | None, seconds: float) -> bool:
    """Нечего распознавать: тишина или запись короче полсекунды."""
    if seconds < 0.5:
        return True
    return volume is not None and volume <= silence_threshold_db()


_LANG_NAMES = {"ru": "Russian", "en": "English", "kg": "Kyrgyz", "ky": "Kyrgyz"}


def transcribe_audio(mp3: bytes, *, lang: str = "ru") -> str:
    """Отдать запись модели и вернуть текст без обёрток."""
    from .handlers import _make_openai_client

    client = _make_openai_client()
    hint = _LANG_NAMES.get((lang or "ru").lower(), "the speaker's language")
    instruction = (
        "Transcribe this voice message verbatim. Reply with the transcription only, "
        "without quotes, comments or translation. Keep the original language "
        f"(most likely {hint}). If there is no intelligible speech (silence, noise, music), "
        "reply with exactly: NO_SPEECH"
    )
    try:
        result = client.chat.completions.create(
            model=model_id(),
            messages=[{
                "role": "user",
                "content": [
                    {"type": "text", "text": instruction},
                    {"type": "input_audio",
                     "input_audio": {"data": base64.b64encode(mp3).decode("ascii"),
                                     "format": "mp3"}},
                ],
            }],
            max_tokens=2000,
            temperature=0,
            timeout=90,
        )
    except Exception as exc:  # noqa: BLE001 — любая ошибка провайдера
        raise SttError(str(exc)[:200]) from exc

    try:
        text = (result.choices[0].message.content or "").strip()
    except Exception as exc:  # noqa: BLE001
        raise SttError("пустой ответ модели") from exc
    text = text.strip().strip('"').strip()
    if text.upper().replace(" ", "_").strip("[]") == "NO_SPEECH":
        return ""
    return text
