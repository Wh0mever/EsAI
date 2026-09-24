"""Материалы видеостудии: приём фото, нормализация, последний кадр (§7).

Почему не сохраняем файл как есть, как в чате:
- телефонные фото тяжёлые (HEIC, 4000+ px), а референсы провайдер скачивает
  сам: 21.09 тяжёлые фото растянули отправку до таймаута, и ролик потерялся;
- HEIC не открывают ни браузеры (кроме Safari), ни провайдеры, а nginx отдаёт
  его вложением;
- в EXIF лежат GPS и модель телефона — провайдеру это уходить не должно;
- файл-«полиглот» (JPEG, у которого в хвосте или в комментарии HTML/ZIP) после
  перекодирования становится обычной картинкой.

Поэтому каждое фото декодируется и пишется заново: JPEG q90 (PNG — только если
есть прозрачность), длинная сторона до 2048 px, без метаданных, плюс превью
480 px. Через тот же нормализатор проходят созданные моделью картинки (BE-7,
store_image_bytes) и кадры из готовых видео (from_take_last_frame).

Ошибки — AssetError с кодом §8.4; view отдаёт err.response_data() и err.status.
"""
from __future__ import annotations

import hashlib
import io
import logging
import math
import os
import re
import threading
from dataclasses import dataclass, field
from typing import NamedTuple

from django.core.files.base import ContentFile
from django.core.files.storage import default_storage

from .models import Asset, Take

logger = logging.getLogger("vstudio.assets")

# Потолок пикселей по заголовку — до декодирования. Провайдеру всё равно уйдёт
# 2048 px, а память тратится на полный кадр, и сжатый однотонный файл весит
# десятки килобайт при любом разрешении (PNG 7070×7070 — 200 КБ, а старая
# цепочка «декодирование + копия в convert + копия в premultiplied-альфу при
# ресайзе» съедала на нём +455 МБ). Потолки — по тому, как формат декодируется
# (замер пика RSS на потолке, после правок ниже):
# - JPEG/MPO декодируются сразу уменьшенными (draft, 1/2…1/8): 50 Мп → ~100 МБ;
# - HEIF (фото iPhone: 12 или 24 Мп) draft не умеет, а pillow-heif держит
#   второй буфер: 25 Мп → ~180 МБ (48 Мп «MAX» — ~345 МБ, такое не берём);
# - WebP Pillow декодирует через второй полный буфер: 10 Мп → ~205 МБ;
# - PNG/GIF/BMP декодируются целиком, часто с альфой: 16 Мп → ~180 МБ.
# Сверх того одновременно нормализуются не больше NORMALIZE_SLOTS фото на
# процесс: итог — не больше ~0.4 ГБ на процесс gunicorn при любом наплыве.
MAX_PIXELS = 50_000_000              # JPEG/MPO и общий верхний предел
MAX_PIXELS_HEIF = 25_000_000
MAX_PIXELS_WEBP = 10_000_000
MAX_PIXELS_FULL_DECODE = 16_000_000  # PNG, GIF, BMP
_DRAFT_FORMATS = frozenset({"JPEG", "MPO"})
# Сколько фото один процесс (gunicorn — 8 потоков) нормализует одновременно,
# и сколько секунд ждём свободного слота, прежде чем ответить «подождите».
NORMALIZE_SLOTS = 2
NORMALIZE_WAIT_S = 15
# Длинная сторона после нормализации: хватает всем моделям, и провайдер
# скачивает референс за доли секунды.
MAX_SIDE = 2048
THUMB_BOX = 480
JPEG_QUALITY = 90
# Отметки для подсказок в лотке (сами ограничения по модели проверяет компилятор).
MIN_SIDE_PX = 300
ASPECT_RANGE = (0.4, 2.5)
# Готовый ролик читаем целиком (video_edit работает с байтами); больше
# finalize всё равно не скачивает.
MAX_FRAME_VIDEO_BYTES = 300 * 1024 * 1024

# Какие декодеры Pillow вообще пробуем. Формат Pillow определяет по
# содержимому, поэтому без этого списка «photo.jpg» с EPS внутри ушёл бы в
# Ghostscript, а TIFF/PSD/ICO — в редкие декодеры. Тип файла — по содержимому,
# расширение только отсеивает явно чужое.
_DECODERS = ("JPEG", "MPO", "PNG", "GIF", "WEBP", "BMP", "HEIF")
# Где бывает анимация (MPO — это стереопара/карта глубины, а не анимация).
_ANIMATED_FORMATS = frozenset({"GIF", "WEBP", "PNG"})

# Видео и звук как референсы — Фаза 1.5: для них отдельный код и текст.
_VIDEO_AUDIO_EXTENSIONS = frozenset({
    ".mp4", ".m4v", ".mov", ".qt", ".webm", ".mkv", ".avi", ".wmv", ".flv", ".3gp", ".3g2",
    ".mpg", ".mpeg", ".ts", ".mts", ".m2ts", ".ogv",
    ".mp3", ".m4a", ".aac", ".wav", ".ogg", ".oga", ".opus", ".flac", ".amr", ".wma", ".aiff",
    ".aif", ".weba",
})
_JPEG_ALIASES = (".jfif", ".jpe")
_CONTROL_CHARS = re.compile(r"[\x00-\x1f\x7f]+")

_EXIF_ORIENTATION = 0x0112


# ---------------------------------------------------------------- ошибки

class AssetError(Exception):
    """Отказ с кодом §8.4. Текст — по-русски, его показывает интерфейс."""

    def __init__(self, code: str, message: str, *, status: int = 422, **params):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status
        self.params = params

    def response_data(self) -> dict:
        """Тело ответа в общем формате API: {"error", "error_code", …}."""
        return {"error": self.message, "error_code": self.code, **self.params}


def _too_large(limit: int) -> AssetError:
    mb = max(1, round(limit / (1024 * 1024)))
    return AssetError("file_too_large", f"Файл слишком большой: максимум {mb} МБ.",
                      status=413, max_bytes=limit)


def _unsupported() -> AssetError:
    return AssetError("unsupported_type",
                      "Этот формат не подходит. Загрузите фото: JPG, PNG, WebP или HEIC.")


def _video_refs() -> AssetError:
    return AssetError("video_refs_unsupported",
                      "Видео и звук как референсы появятся позже. Сейчас можно добавить только фото.")


def _bad_image() -> AssetError:
    return AssetError("bad_image", "Не удалось открыть фото — файл повреждён или это не картинка.")


def _too_many_pixels(limit: int | None = None) -> AssetError:
    limit = int(limit or MAX_PIXELS)
    mp = max(1, round(limit / 1_000_000))
    return AssetError("too_many_pixels",
                      f"Фото слишком большое по разрешению (больше {mp} Мп). "
                      "Уменьшите его и загрузите снова.",
                      max_pixels=limit)


def _busy() -> AssetError:
    return AssetError("throttled", "Сейчас обрабатывается много фото — попробуйте через несколько секунд.",
                      status=429)


def pixel_limit(fmt: str) -> int:
    """Потолок пикселей для формата: без уменьшенного декодирования — ниже."""
    fmt = (fmt or "").upper()
    if fmt in _DRAFT_FORMATS:
        return MAX_PIXELS
    if fmt == "HEIF":
        return min(MAX_PIXELS, MAX_PIXELS_HEIF)
    if fmt == "WEBP":
        return min(MAX_PIXELS, MAX_PIXELS_WEBP)
    return min(MAX_PIXELS, MAX_PIXELS_FULL_DECODE)


def _frame_failed() -> AssetError:
    return AssetError("frame_failed", "Не удалось взять последний кадр из видео. Попробуйте ещё раз.")


# ---------------------------------------------------------------- правила загрузки

def _chat_rules() -> tuple[frozenset, dict, int]:
    """Белый список и лимит — те же, что у вложений чата (сам чат не трогаем).

    Импорт ленивый: модуль нужен и воркеру (картинки BE-7), а ai.views тянет
    за собой весь чат. Лимит читается при каждом вызове — его можно подменить.
    """
    from ai import views as ai_views

    view = ai_views.ChatAttachmentUploadAPIView
    return (frozenset(view._IMAGE_EXTENSIONS), dict(view._IMAGE_CTYPE_EXT),
            int(ai_views.MAX_ATTACHMENT_SIZE))


def max_upload_bytes() -> int:
    return _chat_rules()[2]


def upload_extension(name: str, content_type: str = "") -> str:
    """Расширение, с которым принимаем файл (шаг 2 §7), иначе AssetError.

    .jfif/.jpe — это JPEG (так сохраняет Windows). Файл без расширения
    (вставка из буфера приходит как «blob») типизируем по content_type — как
    чат. Итоговый формат всё равно решает содержимое: расширение лишь
    отсекает документы, SVG, видео и звук до декодирования.
    """
    image_exts, ctype_ext, _ = _chat_rules()
    base = os.path.basename((name or "").replace("\\", "/")).strip().lower()
    ext = os.path.splitext(base)[1]
    ctype = (content_type or "").lower().split(";")[0].strip()
    if ext in _JPEG_ALIASES:
        return ".jpg"
    if ext in image_exts:
        return ext
    if ext in _VIDEO_AUDIO_EXTENSIONS or ctype.startswith(("video/", "audio/")):
        raise _video_refs()
    if not ext and ctype in ctype_ext:
        return ctype_ext[ctype]
    raise _unsupported()


def single_upload(files):
    """Ровно один файл из request.FILES (§7: один файл на запрос).

    Считаем файлы во всех полях, а не только в «file»: иначе второй файл под
    другим именем поля молча потерялся бы.
    """
    if hasattr(files, "lists"):
        items = [f for _key, group in files.lists() for f in group]
    else:
        items = [f for f in (files or []) if f is not None]
    if not items:
        raise AssetError("bad_request", "Файл не получен — выберите фото ещё раз.", status=400)
    if len(items) > 1:
        raise AssetError("bad_request", "Загружайте по одному фото за раз.", status=400)
    return items[0]


def _read_capped(file, limit: int) -> bytes:
    """Прочитать загрузку, не веря заявленному размеру: обрыв — сразу за лимитом."""
    size = getattr(file, "size", None)
    if size is not None and size > limit:
        raise _too_large(limit)
    buf = bytearray()
    if hasattr(file, "chunks"):
        chunks = file.chunks()
    else:
        try:
            file.seek(0)
        except Exception:
            pass
        chunks = iter(lambda: file.read(1024 * 1024), b"")
    for chunk in chunks:
        buf += chunk
        if len(buf) > limit:
            raise _too_large(limit)
    return bytes(buf)


def sha256_hex(blob: bytes) -> str:
    return hashlib.sha256(blob).hexdigest()


def _clean_name(name: str) -> str:
    base = os.path.basename((name or "").replace("\\", "/"))
    return _CONTROL_CHARS.sub("", base).strip()[:120]


# ---------------------------------------------------------------- нормализация

_heif_ready = False


def _ensure_heif() -> bool:
    """Подключить HEIC/HEIF к Pillow (один раз на процесс).

    Без pillow-heif фото с iPhone не откроются, но и падать при импорте не
    будем: такие файлы получат bad_image, а в логе будет причина.
    """
    global _heif_ready
    if _heif_ready:
        return True
    try:
        import pillow_heif

        # Миниатюры, карты глубины и служебные слои HEIC нам не нужны —
        # не тратим на них память и время.
        pillow_heif.register_heif_opener(thumbnails=False, depth_images=False, aux_images=False)
    except Exception:
        logger.error("pillow-heif недоступен: HEIC/HEIF не будут открываться", exc_info=True)
        return False
    _heif_ready = True
    return True


def _decoders() -> list[str]:
    from PIL import Image

    Image.init()
    # HEIF есть в списке, только если pillow-heif подключился: Image.open
    # падает KeyError на незарегистрированном формате.
    return [fmt for fmt in _DECODERS if fmt in Image.OPEN]


def _open(blob: bytes, formats: list[str], trusted: bool = False):
    """Открыть только заголовок (без декодирования) и проверить число пикселей."""
    from PIL import Image

    try:
        img = Image.open(io.BytesIO(blob), formats=formats)
    except Image.DecompressionBombError:
        # Больше ~178 Мп Pillow отказывает сам, ещё до нашей проверки.
        raise _too_many_pixels() from None
    except Exception:
        raise _bad_image() from None
    width, height = img.size
    if width <= 0 or height <= 0:
        raise _bad_image()
    # trusted — картинка от провайдера (4K у Nano Banana Pro): за неё уже
    # заплачено, отказывать ей по потолку загрузок нельзя; общий предел остаётся.
    limit = MAX_PIXELS if trusted else pixel_limit(img.format)
    if width * height > limit:
        raise _too_many_pixels(limit)
    return img


def _orientation(img, fmt: str) -> int:
    """EXIF-ориентация 1–8. У HEIF libheif уже повернул кадр сам (irot/imir),
    а pillow-heif оставил исходное значение в info["original_orientation"]."""
    try:
        if fmt == "HEIF":
            value = img.info.get("original_orientation")
        else:
            value = img.getexif().get(_EXIF_ORIENTATION)
        value = int(value or 1)
    except Exception:
        return 1
    return value if 1 <= value <= 8 else 1


def _cms_to_srgb(img, icc: bytes, output_mode: str):
    """Перевести цвета из встроенного профиля в sRGB. None — если не вышло.

    Профиль мы выбрасываем вместе с остальными метаданными, а без перевода
    фото iPhone (Display P3) выглядели бы блёклыми: провайдер читает пиксели
    как sRGB.
    """
    try:
        from PIL import ImageCms

        src = ImageCms.ImageCmsProfile(io.BytesIO(icc))
        dst = ImageCms.createProfile("sRGB")
        return ImageCms.profileToProfile(img, src, dst, outputMode=output_mode)
    except Exception:
        logger.info("цветовой профиль не применился, оставляем пиксели как есть", exc_info=True)
        return None


def _to_rgb_or_rgba(img, icc: bytes | None):
    """Любой режим Pillow → RGB или RGBA (прозрачность решим после уменьшения).

    Возвращает (картинка, профиль, который ещё осталось применить). Профиль
    RGB применяем уже после уменьшения — так дешевле; CMYK переводим сразу,
    иначе его цвета потом не восстановить. Профиль серой картинки к RGB не
    подходит — отбрасываем.
    """
    mode = img.mode
    if mode.startswith("I;16") or mode in ("I", "F"):
        # 16-битный серый PNG: простое convert("L") обрезает всё выше 255 в белое.
        img = img.convert("I") if mode != "I" else img
        img = img.point(lambda v: v * (1 / 256)).convert("L")
        mode = "L"
    if mode == "CMYK":
        converted = _cms_to_srgb(img, icc, "RGB") if icc else None
        return (converted if converted is not None else img.convert("RGB")), None
    rest = None if mode in ("1", "L", "LA", "La") else icc
    if mode in ("RGBA", "LA", "PA", "RGBa", "La") or "transparency" in img.info:
        # convert() в тот же режим — полная копия кадра (+200 МБ на 50 Мп RGBA):
        # уже RGBA отдаём как есть.
        return (img if mode == "RGBA" else img.convert("RGBA")), rest
    return (img if mode == "RGB" else img.convert("RGB")), rest


@dataclass(frozen=True)
class NormalizedImage:
    """Готовая к хранению картинка: байты файла, превью и отметки для лотка."""

    data: bytes
    ext: str                 # "jpg" | "png"
    mime: str                # "image/jpeg" | "image/png"
    width: int
    height: int
    thumb: bytes | None      # JPEG, вписан в 480 px; None — если не сделалось
    flags: dict = field(default_factory=dict)
    source_format: str = ""  # как распознал Pillow: JPEG, PNG, HEIF, …

    @property
    def size(self) -> int:
        return len(self.data)


# Слоты нормализации на процесс: 24 загрузки разом (3 процесса × 8 потоков)
# по сотне мегабайт каждая — это OOM всего контейнера вместе с чатом и оплатой.
_normalize_slots = threading.BoundedSemaphore(NORMALIZE_SLOTS)


def normalize_image_bytes(blob: bytes, *, max_side: int = MAX_SIDE, trusted: bool = False) -> NormalizedImage:
    """Декодировать и записать картинку заново (шаги 4–9 §7).

    Бросает AssetError: bad_image (не картинка, битый файл, чужой формат),
    too_many_pixels (больше pixel_limit формата), throttled (429 — все слоты
    нормализации заняты дольше NORMALIZE_WAIT_S). Файлы не пишет — это
    store_image_bytes / ingest_upload. trusted=True — результат провайдера:
    потолок MAX_PIXELS для любого формата (загрузкам — pixel_limit).
    """
    if not blob:
        raise _bad_image()
    if not _normalize_slots.acquire(timeout=NORMALIZE_WAIT_S):
        logger.warning("нормализация фото: все %s слота заняты дольше %s с — отказ",
                       NORMALIZE_SLOTS, NORMALIZE_WAIT_S)
        raise _busy()
    try:
        return _normalize(blob, max_side=max_side, trusted=trusted)
    finally:
        _normalize_slots.release()


def _normalize(blob: bytes, *, max_side: int, trusted: bool = False) -> NormalizedImage:
    _ensure_heif()
    from PIL import Image, ImageOps

    formats = _decoders()
    img = _open(blob, formats, trusted)
    try:
        # verify() ловит битые PNG (CRC) без полного декодирования;
        # после него объект непригоден — открываем заново.
        img.verify()
    except Exception:
        raise _bad_image() from None
    img = _open(blob, formats, trusted)
    fmt = (img.format or "").upper()

    flags: dict = {}
    if fmt == "HEIF":
        flags["heic"] = True
    try:
        if fmt in _ANIMATED_FORMATS and getattr(img, "is_animated", False):
            # Модель ждёт одну картинку: берём первый кадр.
            flags["animated"] = True
            img.seek(0)
    except Exception:
        raise _bad_image() from None

    raw_width, raw_height = img.size   # до draft: он уменьшает size
    long0 = max(raw_width, raw_height)
    if fmt in ("JPEG", "MPO") and long0 >= 2 * max_side:
        # JPEG умеет декодироваться сразу в 1/2, 1/4, 1/8: 48 Мп не
        # разворачиваем в память целиком. Масштаб выбирается так, чтобы
        # длинная сторона осталась не меньше max_side.
        k = max_side / long0
        try:
            img.draft(None, (max(1, math.ceil(raw_width * k)), max(1, math.ceil(raw_height * k))))
        except Exception:
            logger.debug("draft не применился", exc_info=True)

    try:
        img.load()
    except Exception:
        raise _bad_image() from None

    # Ориентацию читаем после load(): у PNG getexif() сам декодирует файл,
    # и ошибка битого файла ушла бы мимо bad_image.
    orientation = _orientation(img, fmt)
    width0, height0 = raw_width, raw_height
    if orientation != 1 and fmt != "HEIF":
        try:
            ImageOps.exif_transpose(img, in_place=True)
        except Exception:
            # Кривой EXIF — не повод отказать в фото: оставляем как лежит.
            logger.warning("EXIF-поворот не применился (ориентация %s)", orientation, exc_info=True)
            orientation = 1
        else:
            if orientation in (5, 6, 7, 8):
                width0, height0 = height0, width0   # размеры «как видит человек»
    if orientation != 1:
        flags["exif_rotated"] = True
    icc = img.info.get("icc_profile") or None

    try:
        img, icc = _to_rgb_or_rgba(img, icc)
        if img.mode == "RGBA" and max(img.size) > max_side and img.getextrema()[3][0] == 255:
            # Альфа есть, но везде непрозрачная (обычный скриншот) — это JPEG.
            # Убираем её ДО уменьшения: RGBA Pillow уменьшает через полную
            # копию кадра в premultiplied-альфе (+4 байта на пиксель), а RGB —
            # без неё. getextrema() считает по каналам без копии (getchannel копирует).
            img = img.convert("RGB")
        if max(img.size) > max_side:
            k = max_side / max(img.size)
            size = (max(1, round(img.width * k)), max(1, round(img.height * k)))
            # Для RGBA Pillow сам уменьшает в premultiplied-альфе — без тёмных ореолов.
            img = img.resize(size, Image.LANCZOS, reducing_gap=3.0)
        if long0 > max_side:
            flags["downscaled_from"] = [width0, height0]

        alpha = False
        if img.mode == "RGBA":
            lowest = img.getextrema()[3][0]
            if lowest < 255:
                alpha = True
            else:
                # Альфа есть, но везде непрозрачная (обычный скриншот) — это JPEG.
                img = img.convert("RGB")
        if icc and img.mode in ("RGB", "RGBA"):
            converted = _cms_to_srgb(img, icc, img.mode)
            if converted is not None:
                img = converted

        # Метаданные не переносим НИКАКИЕ: Pillow при сохранении подхватывает
        # из info комментарий JPEG (а там бывает HTML) и ICC для PNG.
        img.info = {}
        out = io.BytesIO()
        if alpha:
            img.save(out, format="PNG", compress_level=6)
            ext, mime = "png", "image/png"
        else:
            if img.mode != "RGB":
                img = img.convert("RGB")
                img.info = {}
            img.save(out, format="JPEG", quality=JPEG_QUALITY, optimize=True)
            ext, mime = "jpg", "image/jpeg"
    except Exception:
        logger.warning("нормализация фото не удалась (формат %s)", fmt, exc_info=True)
        raise _bad_image() from None

    data = out.getvalue()
    width, height = img.size
    if min(width, height) < MIN_SIDE_PX:
        flags["too_small"] = True
    ratio = width / height
    if not ASPECT_RANGE[0] <= ratio <= ASPECT_RANGE[1]:
        flags["aspect"] = True

    from cartoon.thumbs import make_thumb

    return NormalizedImage(data=data, ext=ext, mime=mime, width=width, height=height,
                           thumb=make_thumb(data, THUMB_BOX), flags=flags, source_format=fmt)


# ---------------------------------------------------------------- хранение

def asset_paths(user_id, asset_uid: str, ext: str) -> tuple[str, str]:
    """vstudio/<user_id>/<uid>.<ext> и превью <uid>_t.jpg (§2.1)."""
    base = f"vstudio/{user_id}/{asset_uid}"
    return f"{base}.{ext}", f"{base}_t.jpg"


def delete_files(*paths: str) -> None:
    """Стереть файлы, не падая: зовётся из отката и у проигравшего гонку."""
    for path in paths:
        if not path:
            continue
        try:
            default_storage.delete(path)
        except Exception:
            logger.warning("не удалось удалить %s", path, exc_info=True)


@dataclass(frozen=True)
class StoredImage:
    """Сохранённая картинка: пути в default_storage и поля для строки Asset."""

    norm: NormalizedImage
    file: str
    thumb: str
    sha256: str

    @property
    def paths(self) -> list[str]:
        return [p for p in (self.file, self.thumb) if p]

    def asset_fields(self) -> dict:
        """Поля Asset — для Asset(**…) или Asset.objects.filter(…).update(**…)."""
        return {
            "file": self.file,
            "thumb": self.thumb,
            "mime": self.norm.mime,
            "bytes": self.norm.size,
            "width": self.norm.width,
            "height": self.norm.height,
            "flags": dict(self.norm.flags),
            "sha256": self.sha256,
        }


def store_image_bytes(user_id, asset_uid: str, blob: bytes, *, sha256: str | None = None,
                      max_side: int = MAX_SIDE, trusted: bool = False) -> StoredImage:
    """Нормализовать и записать файл с превью. Строку Asset не трогает.

    Для BE-7 (картинка от модели): файлы пишутся ДО транзакции done+charged;
    если условный переход проигран или транзакция упала —
    delete_files(*stored.paths).
    """
    norm = normalize_image_bytes(blob, max_side=max_side, trusted=trusted)
    file_path, thumb_path = asset_paths(user_id, asset_uid, norm.ext)
    saved: list[str] = []
    try:
        saved.append(default_storage.save(file_path, ContentFile(norm.data)))
        thumb = ""
        if norm.thumb:
            thumb = default_storage.save(thumb_path, ContentFile(norm.thumb))
            saved.append(thumb)
        else:
            logger.warning("превью не сделалось: %s", saved[0])
    except Exception:
        delete_files(*saved)
        raise
    return StoredImage(norm=norm, file=saved[0], thumb=thumb, sha256=sha256 or sha256_hex(blob))


class Ingested(NamedTuple):
    """Итог приёма: created=False — это уже загруженное раньше фото (ответ 200)."""

    asset: Asset
    created: bool


def _save_new(asset: Asset, stored: StoredImage) -> Asset:
    for key, value in stored.asset_fields().items():
        setattr(asset, key, value)
    try:
        asset.save()
    except Exception:
        delete_files(*stored.paths)
        raise
    return asset


def ingest_upload(user, file, project=None) -> Ingested:
    """Принять одно фото в «Мои материалы» (§7).

    Порядок: размер → расширение → sha256 и дубль → декодирование и
    перекодирование → файлы → строка Asset. Бросает AssetError; при отказе
    ничего не пишет. project — уже проверенный проект этого человека или None.
    """
    if project is not None and project.user_id != user.pk:
        raise ValueError("ingest_upload: проект принадлежит другому пользователю")
    limit = max_upload_bytes()
    size = getattr(file, "size", None)
    if size is not None and size > limit:
        raise _too_large(limit)
    name = getattr(file, "name", "") or ""
    upload_extension(name, getattr(file, "content_type", "") or "")
    blob = _read_capped(file, limit)
    if not blob:
        raise _bad_image()

    digest = sha256_hex(blob)
    # То же фото второй раз — тот же материал: не плодим копии в библиотеке.
    # Гонка двух одинаковых загрузок даст два материала — это безвредно.
    duplicate = (Asset.objects.owned_by(user).alive()
                 .filter(kind=Asset.KIND_IMAGE, source=Asset.SOURCE_UPLOAD,
                         status=Asset.STATUS_READY, sha256=digest)
                 .order_by("-created_at").first())
    if duplicate is not None:
        return Ingested(duplicate, False)

    asset = Asset(user=user, project=project, kind=Asset.KIND_IMAGE, source=Asset.SOURCE_UPLOAD,
                  status=Asset.STATUS_READY)
    stored = store_image_bytes(user.pk, asset.uid, blob, sha256=digest)
    asset.meta = {
        "original_name": _clean_name(name),
        "original_bytes": len(blob),
        "original_format": stored.norm.source_format.lower(),
    }
    return Ingested(_save_new(asset, stored), True)


# ---------------------------------------------------------------- последний кадр

def from_take_last_frame(take: Take) -> Ingested:
    """Последний кадр готового видео → Asset(source=frame) (POST assets/from-take/).

    Владельца проверяет view (дубль ищется по user=request.user). Повторный
    вызов для того же дубля отдаёт уже созданный кадр (created=False).
    """
    if take.kind != Take.KIND_VIDEO:
        raise AssetError("take_not_found", "Генерация не найдена.", status=404)
    if take.status != Take.STATUS_DONE:
        raise AssetError("take_not_ready",
                         "Видео ещё не готово — кадр можно взять, когда ролик появится.",
                         status=409)

    existing = (Asset.objects.filter(user_id=take.user_id, origin_take=take,
                                     source=Asset.SOURCE_FRAME, kind=Asset.KIND_IMAGE,
                                     status=Asset.STATUS_READY)
                .alive().order_by("-created_at").first())
    if existing is not None:
        return Ingested(existing, False)

    video = take.result_asset
    if video is None or not video.file:
        logger.error("кадр: у готового дубля %s нет файла видео", take.uid)
        raise _frame_failed()
    try:
        with default_storage.open(video.file, "rb") as fh:
            data = fh.read(MAX_FRAME_VIDEO_BYTES + 1)
    except Exception:
        logger.error("кадр: не прочитался файл %s (дубль %s)", video.file, take.uid, exc_info=True)
        raise _frame_failed() from None
    if not data or len(data) > MAX_FRAME_VIDEO_BYTES:
        raise _frame_failed()

    from ai import video_edit

    jpeg = video_edit.extract_last_frame(data)
    del data
    if not jpeg:
        raise _frame_failed()

    asset = Asset(user_id=take.user_id, project_id=take.project_id, kind=Asset.KIND_IMAGE,
                  source=Asset.SOURCE_FRAME, status=Asset.STATUS_READY, origin_take=take,
                  meta={"at": "last_frame", "take": take.uid})
    try:
        stored = store_image_bytes(take.user_id, asset.uid, jpeg)
    except AssetError:
        logger.error("кадр дубля %s не прошёл нормализацию", take.uid, exc_info=True)
        raise _frame_failed() from None
    return Ingested(_save_new(asset, stored), True)
