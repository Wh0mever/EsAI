"""Лёгкие ролики для ленты библиотеки.

Зачем. Клиент попросил, чтобы превью в сетке играли сами, без звука, — как в
популярных мини-приложениях. Но снятый ролик весит 3.5 МБ: шесть таких,
запущенных разом, съедают двадцать мегабайт мобильного трафика на одном
экране. Поэтому в ленте играет облегчённая копия — 480 пикселей по ширине, без
звуковой дорожки, — а исходник остаётся для скачивания и склейки.

Звук убираем не только ради веса: в ленте всё равно всё играет молча, а
дорожка, которую никто не услышит, — чистые килобайты.
"""
from __future__ import annotations

import logging
import subprocess
import tempfile
from pathlib import Path

logger = logging.getLogger(__name__)

# Карточка в сетке — от 160 до 320 точек по ширине. 480 даёт запас на плотные
# экраны, дальше растёт только вес.
CLIP_WIDTH = 480
CLIP_FPS = 24
CLIP_CRF = 32


def make_clip(video_bytes: bytes) -> bytes | None:
    """Облегчённая копия ролика для автопроигрывания в ленте."""
    if not video_bytes:
        return None
    with tempfile.TemporaryDirectory() as td:
        src = Path(td) / "in.mp4"
        out = Path(td) / "out.mp4"
        src.write_bytes(video_bytes)
        cmd = [
            "ffmpeg", "-hide_banner", "-loglevel", "error", "-i", str(src),
            "-an",  # звук в ленте не нужен
            "-vf", f"scale={CLIP_WIDTH}:-2:flags=lanczos,fps={CLIP_FPS}",
            "-c:v", "libx264", "-preset", "veryfast", "-crf", str(CLIP_CRF),
            "-pix_fmt", "yuv420p",
            # Без faststart браузер ждёт конца файла, прежде чем начать играть.
            "-movflags", "+faststart",
            "-y", str(out),
        ]
        try:
            r = subprocess.run(cmd, capture_output=True, timeout=300)
        except Exception:
            logger.exception("лёгкая копия: ffmpeg не запустился")
            return None
        if r.returncode != 0 or not out.exists() or out.stat().st_size == 0:
            logger.warning("лёгкая копия: ffmpeg rc=%s err=%s",
                           r.returncode, (r.stderr or b"")[:300])
            return None
        return out.read_bytes()
