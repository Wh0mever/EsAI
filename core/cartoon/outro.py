"""Заставка EsAI в конце готового мультфильма.

Зачем. Клиент: «каждый опубликованный мультфильм должен работать ещё и как
реклама Studio». Ссылка, которой делятся, ведёт на нашу страницу с призывом,
но человек часто скачивает mp4 и заливает его к себе — в Instagram, TikTok,
статус. Там от страницы не остаётся ничего, и единственное, что переживает
перезалив, — то, что впечатано в сам кадр.

Кликабельной ссылки в видео быть не может, поэтому в кадре стоит адрес: его
набирают руками, и он же читается в превью.

Карточка рисуется, а не лежит картинкой в репозитории: ролики бывают разных
размеров, и подгонять одну картинку под каждый — хуже, чем отрисовать под
нужный кадр сразу.
"""
from __future__ import annotations

import logging
import subprocess
import tempfile
from io import BytesIO
from pathlib import Path

logger = logging.getLogger(__name__)

# Секунды. Меньше — не успеть прочитать, больше — раздражает в коротком ролике.
OUTRO_SECONDS = 2.5

_BG = (11, 11, 15)
_ACCENT = (244, 63, 94)
_WHITE = (255, 255, 255)
_MUTED = (168, 168, 178)

_FONTS = (
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
)


def _font(bold: bool, size: int):
    from PIL import ImageFont

    path = _FONTS[0] if bold else _FONTS[1]
    try:
        return ImageFont.truetype(path, size)
    except Exception:
        # Без шрифта надпись всё равно нужна — падать из-за неё нельзя.
        return ImageFont.load_default()


def build_card(width: int, height: int) -> bytes:
    """PNG-заставка под конкретный размер кадра."""
    from PIL import Image, ImageDraw

    img = Image.new("RGB", (width, height), _BG)
    draw = ImageDraw.Draw(img)

    # Мягкое пятно света по центру: ровная заливка на фоне живого кадра
    # выглядит как обрыв файла, а не как финал.
    glow = Image.new("RGB", (width, height), _BG)
    gd = ImageDraw.Draw(glow)
    gd.ellipse(
        [width * 0.15, height * 0.05, width * 0.85, height * 0.95],
        fill=(26, 18, 28),
    )
    from PIL import ImageFilter

    img = Image.blend(img, glow.filter(ImageFilter.GaussianBlur(width // 12)), 0.9)
    draw = ImageDraw.Draw(img)

    unit = height / 100.0

    def centered(text: str, y: float, font, fill):
        box = draw.textbbox((0, 0), text, font=font)
        draw.text(((width - (box[2] - box[0])) / 2, y), text, font=font, fill=fill)
        return box[3] - box[1]

    centered("EsAI", unit * 28, _font(True, int(unit * 13)), _WHITE)
    centered("Cartoon Studio", unit * 44, _font(False, int(unit * 6)), _ACCENT)
    centered("Создайте свой мультфильм", unit * 58, _font(True, int(unit * 7)), _WHITE)
    centered("esai.kg/studio", unit * 72, _font(False, int(unit * 5.5)), _MUTED)

    buf = BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _probe(path: Path) -> dict:
    """Размер, кадровая частота и наличие звука у ролика."""
    cmd = [
        "ffprobe", "-v", "error", "-print_format", "json",
        "-show_streams", "-show_entries",
        "stream=codec_type,width,height,r_frame_rate", str(path),
    ]
    try:
        import json

        out = subprocess.run(cmd, capture_output=True, timeout=60).stdout
        streams = (json.loads(out or b"{}") or {}).get("streams") or []
    except Exception:
        return {}

    info = {"audio": any(s.get("codec_type") == "audio" for s in streams)}
    video = next((s for s in streams if s.get("codec_type") == "video"), None)
    if not video:
        return {}
    info["width"] = int(video.get("width") or 0)
    info["height"] = int(video.get("height") or 0)
    raw = str(video.get("r_frame_rate") or "25/1")
    try:
        num, den = raw.split("/")
        info["fps"] = max(1.0, float(num) / float(den or 1))
    except Exception:
        info["fps"] = 25.0
    return info


def append_outro(video_bytes: bytes) -> bytes:
    """Дописать заставку в конец ролика. При любой осечке вернуть исходник.

    Мультфильм уже оплачен и собран — потерять его из-за неудавшейся заставки
    недопустимо, поэтому любая ошибка здесь означает «отдать как есть».

    Всё сводится в один проход ffmpeg: карточка растягивается до размера кадра,
    звук обеих частей приводится к одному формату. Без выравнивания фильтр
    concat отказывается склеивать потоки с разными параметрами.
    """
    if not video_bytes:
        return video_bytes

    with tempfile.TemporaryDirectory() as td:
        src = Path(td) / "in.mp4"
        src.write_bytes(video_bytes)
        info = _probe(src)
        w, h = info.get("width") or 0, info.get("height") or 0
        if not w or not h:
            logger.warning("outro: не удалось прочитать размер ролика — отдаю без заставки")
            return video_bytes

        card = Path(td) / "card.png"
        try:
            card.write_bytes(build_card(w, h))
        except Exception:
            logger.exception("outro: карточка не нарисовалась")
            return video_bytes

        out = Path(td) / "out.mp4"
        fps = info.get("fps") or 25.0
        has_audio = bool(info.get("audio"))
        # Плавное появление и уход — резкая врезка после сцены читается как брак.
        vfilter = (
            f"scale={w}:{h},fps={fps},format=yuv420p,setsar=1,"
            f"fade=t=in:st=0:d=0.4,fade=t=out:st={OUTRO_SECONDS - 0.4:.2f}:d=0.4"
        )

        cmd = [
            "ffmpeg", "-hide_banner", "-loglevel", "error",
            "-i", str(src),
            "-loop", "1", "-t", str(OUTRO_SECONDS), "-i", str(card),
        ]
        if has_audio:
            afmt = "aformat=sample_fmts=fltp:sample_rates=48000:channel_layouts=stereo"
            cmd += [
                "-f", "lavfi", "-t", str(OUTRO_SECONDS),
                "-i", "anullsrc=channel_layout=stereo:sample_rate=48000",
                "-filter_complex",
                f"[0:v]fps={fps},format=yuv420p,setsar=1[v0];"
                f"[1:v]{vfilter}[v1];"
                f"[0:a]{afmt}[a0];[2:a]{afmt}[a1];"
                f"[v0][a0][v1][a1]concat=n=2:v=1:a=1[v][a]",
                "-map", "[v]", "-map", "[a]", "-c:a", "aac", "-b:a", "128k",
            ]
        else:
            cmd += [
                "-filter_complex",
                f"[0:v]fps={fps},format=yuv420p,setsar=1[v0];"
                f"[1:v]{vfilter}[v1];"
                f"[v0][v1]concat=n=2:v=1:a=0[v]",
                "-map", "[v]",
            ]
        cmd += [
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
            "-pix_fmt", "yuv420p", "-movflags", "+faststart",
            "-y", str(out),
        ]

        try:
            r = subprocess.run(cmd, capture_output=True, timeout=600)
        except Exception:
            logger.exception("outro: ffmpeg не запустился")
            return video_bytes

        if r.returncode != 0 or not out.exists() or out.stat().st_size == 0:
            logger.warning("outro: ffmpeg rc=%s err=%s", r.returncode, (r.stderr or b"")[:400])
            return video_bytes
        return out.read_bytes()
