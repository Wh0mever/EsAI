"""Операции над готовыми mp4 через ffmpeg: последний кадр и склейка.

Зачем это нужно. Клиент просил «продление и склейку роликов». В API
генерации видео OpenRouter (POST /videos) НЕТ параметра для передачи
исходного ВИДЕО — в теле запроса допустимы только `frame_images`
(first_frame/last_frame) и `input_references` (референс-картинки),
см. docs/guides/overview/multimodal/video-generation. То есть «продлить»
силами самой модели нельзя.

Поэтому продление собирается так:
  1) берём ПОСЛЕДНИЙ кадр уже готового ролика (extract_last_frame);
  2) отдаём его модели как first_frame — новый сегмент начинается ровно
     там, где закончился предыдущий, и картинка не «прыгает»;
  3) склеиваем оба файла в один (concat_videos).

ffmpeg ставится в образ явно (core/Dockerfile: apt-get install ... ffmpeg),
поэтому доступен и после пересборки.
"""
from __future__ import annotations

import json
import logging
import subprocess
import tempfile
from pathlib import Path

logger = logging.getLogger(__name__)

# Потолки времени: ffmpeg не должен подвесить воркер, если файл битый.
_PROBE_TIMEOUT_S = 30
_FRAME_TIMEOUT_S = 60
_CONCAT_TIMEOUT_S = 300


def _run(cmd: list[str], timeout: int) -> subprocess.CompletedProcess:
    return subprocess.run(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=timeout,
        check=False,
    )


def has_audio_stream(video_bytes: bytes) -> bool:
    """Есть ли в файле аудиодорожка (нужно, чтобы собрать верный concat-фильтр)."""
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "probe.mp4"
        p.write_bytes(video_bytes)
        r = _run(
            [
                "ffprobe", "-v", "error",
                "-select_streams", "a",
                "-show_entries", "stream=index",
                "-of", "json", str(p),
            ],
            _PROBE_TIMEOUT_S,
        )
        if r.returncode != 0:
            return False
        try:
            return bool((json.loads(r.stdout or b"{}") or {}).get("streams"))
        except Exception:
            return False


def extract_last_frame(video_bytes: bytes) -> bytes | None:
    """Последний кадр ролика в JPEG. None — если извлечь не удалось.

    -sseof -0.2 перематывает к концу файла: брать кадр именно с конца
    надёжнее, чем считать длительность и вычитать из неё.
    """
    with tempfile.TemporaryDirectory() as td:
        src = Path(td) / "src.mp4"
        out = Path(td) / "last.jpg"
        src.write_bytes(video_bytes)
        r = _run(
            [
                "ffmpeg", "-hide_banner", "-loglevel", "error",
                "-sseof", "-0.2", "-i", str(src),
                "-update", "1", "-frames:v", "1", "-q:v", "2",
                "-y", str(out),
            ],
            _FRAME_TIMEOUT_S,
        )
        if r.returncode != 0 or not out.exists() or out.stat().st_size == 0:
            logger.warning("extract_last_frame failed rc=%s err=%s", r.returncode, (r.stderr or b"")[:300])
            return None
        return out.read_bytes()


def concat_videos(parts: list[bytes]) -> bytes | None:
    """Склеить несколько mp4 в один. None — если склейка не удалась.

    Используется фильтр concat с ПЕРЕКОДИРОВАНИЕМ, а не concat-демуксер:
    сегменты приходят из разных генераций и могут отличаться параметрами
    потока, а демуксер требует полной идентичности и молча выдаёт битый
    файл при расхождении.

    Аудио берётся в фильтр, только если оно есть во ВСЕХ частях: иначе
    concat с a=1 падает на части без звука.
    """
    parts = [p for p in parts if p]
    if len(parts) < 2:
        return parts[0] if parts else None

    with_audio = all(has_audio_stream(p) for p in parts)

    with tempfile.TemporaryDirectory() as td:
        paths = []
        for i, blob in enumerate(parts):
            p = Path(td) / f"part{i}.mp4"
            p.write_bytes(blob)
            paths.append(p)
        out = Path(td) / "joined.mp4"

        cmd: list[str] = ["ffmpeg", "-hide_banner", "-loglevel", "error"]
        for p in paths:
            cmd += ["-i", str(p)]

        n = len(paths)
        if with_audio:
            streams = "".join(f"[{i}:v:0][{i}:a:0]" for i in range(n))
            filt = f"{streams}concat=n={n}:v=1:a=1[v][a]"
            cmd += ["-filter_complex", filt, "-map", "[v]", "-map", "[a]"]
        else:
            streams = "".join(f"[{i}:v:0]" for i in range(n))
            filt = f"{streams}concat=n={n}:v=1:a=0[v]"
            cmd += ["-filter_complex", filt, "-map", "[v]"]

        cmd += [
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
            "-pix_fmt", "yuv420p",
            # +faststart — чтобы видео начинало играть до полной загрузки.
            "-movflags", "+faststart",
            "-y", str(out),
        ]

        r = _run(cmd, _CONCAT_TIMEOUT_S)
        if r.returncode != 0 or not out.exists() or out.stat().st_size == 0:
            logger.warning("concat_videos failed rc=%s err=%s", r.returncode, (r.stderr or b"")[:400])
            return None
        return out.read_bytes()


def probe_video(video_bytes: bytes) -> dict:
    """Ширина/высота/длительность ролика. Пустой словарь — если распознать не вышло.

    Нужно для публичной страницы ролика: Telegram и соцсети берут размеры из
    og:video:width/height и без них показывают превью криво (обрезают или
    растягивают в 16:9, хотя ролик может быть вертикальным).
    """
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "probe.mp4"
        p.write_bytes(video_bytes)
        r = _run(
            [
                "ffprobe", "-v", "error",
                "-select_streams", "v:0",
                "-show_entries", "stream=width,height:format=duration",
                "-of", "json", str(p),
            ],
            _PROBE_TIMEOUT_S,
        )
        if r.returncode != 0:
            return {}
        try:
            data = json.loads(r.stdout or b"{}") or {}
            stream = (data.get("streams") or [{}])[0]
            out: dict = {}
            if stream.get("width"):
                out["width"] = int(stream["width"])
            if stream.get("height"):
                out["height"] = int(stream["height"])
            dur = (data.get("format") or {}).get("duration")
            if dur:
                out["duration"] = round(float(dur), 2)
            return out
        except Exception:
            return {}


def extract_poster(video_bytes: bytes) -> bytes | None:
    """Кадр-обложка ролика в JPEG. None — если извлечь не удалось.

    Берём кадр на 0.5 c, а не самый первый: многие генерации начинаются с
    почти чёрного кадра, и обложка выходила чёрным прямоугольником.
    """
    with tempfile.TemporaryDirectory() as td:
        src = Path(td) / "src.mp4"
        out = Path(td) / "poster.jpg"
        src.write_bytes(video_bytes)
        r = _run(
            [
                "ffmpeg", "-hide_banner", "-loglevel", "error",
                "-ss", "0.5", "-i", str(src),
                "-update", "1", "-frames:v", "1", "-q:v", "3",
                "-y", str(out),
            ],
            _FRAME_TIMEOUT_S,
        )
        if r.returncode != 0 or not out.exists() or out.stat().st_size == 0:
            # Ролик короче 0.5 c — пробуем самый первый кадр.
            r = _run(
                [
                    "ffmpeg", "-hide_banner", "-loglevel", "error",
                    "-i", str(src),
                    "-update", "1", "-frames:v", "1", "-q:v", "3",
                    "-y", str(out),
                ],
                _FRAME_TIMEOUT_S,
            )
        if r.returncode != 0 or not out.exists() or out.stat().st_size == 0:
            logger.warning("extract_poster failed rc=%s err=%s", r.returncode, (r.stderr or b"")[:300])
            return None
        return out.read_bytes()
