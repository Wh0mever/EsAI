"""Уменьшённые копии картинок библиотеки.

Зачем. Витрина студии показывает разом два десятка героев и полторы сотни
сцен. Оригиналы у них тяжёлые: кадр от модели — это PNG на 1.3 МБ, портрет
героя — JPEG под мегабайт. В сетке они выводятся размером с ноготь, но
браузер всё равно тянет полный файл, и на телефоне картинки просто не
доезжают — вместо героев остаются серые «?» (жалоба пользователя 29.08.2026).

Поэтому в базе рядом с оригиналом лежит миниатюра: её отдаёт витрина, а
оригинал остаётся для генерации — кадр-раскадровку и референс персонажа
нельзя ужимать, от них зависит качество ролика.
"""
from __future__ import annotations

import logging
from io import BytesIO

logger = logging.getLogger(__name__)

# Ширина плитки героя на десктопе — около 160 px, у сцены — около 320 px.
# Берём с запасом на плотные экраны, дальше расти незачем.
CHARACTER_BOX = 320
POSTER_BOX = 560


def make_thumb(blob: bytes, box: int, quality: int = 78) -> bytes | None:
    """JPEG-миниатюра, вписанная в квадрат `box`. None — если не вышло."""
    if not blob:
        return None
    try:
        from PIL import Image

        img = Image.open(BytesIO(blob))
        # PNG от моделей приходит с альфой, а JPEG её не умеет: без белой
        # подложки Pillow падает на «cannot write mode RGBA as JPEG».
        if img.mode in ("RGBA", "LA", "P"):
            img = img.convert("RGBA")
            bg = Image.new("RGB", img.size, (255, 255, 255))
            bg.paste(img, mask=img.split()[-1])
            img = bg
        elif img.mode != "RGB":
            img = img.convert("RGB")

        img.thumbnail((box, box), Image.LANCZOS)
        out = BytesIO()
        img.save(out, format="JPEG", quality=quality, optimize=True, progressive=True)
        return out.getvalue()
    except Exception:
        logger.exception("миниатюра не сделалась")
        return None
