"""Загрузки Creative Studio: фото и видео человека для инструментов.

Фото (jpeg/png/webp): нормализатор видеостудии (vstudio.assets.normalize_image_bytes) —
EXIF-поворот, sRGB, без метаданных, большие уменьшаются до 2048 px по стороне.

Видео (mp4/mov/webm): сначала дешёвые проверки (размер, расширение, первые
байты), потом файл ложится под именем сервера и разбирается строгим ffprobe
склейки (merge.render.probe с демуксером и списком декодеров). Длина 4–30 с.
Поставщик принимает только MP4, поэтому:
- H.264 — перепаковка без перекодирования картинки (звук → AAC, +faststart);
- остальное (HEVC, VP8/VP9, AV1, MPEG-4) — перекодирование в H.264.
Предел кадра для «Замены объекта» (409 600 пикселей) проверяется при цене и
запуске (registry.validate): загрузка одна на все инструменты.

Ограничения (загрузки бесплатны, диск общий с оплаченными выдачами):
- квота человека: не больше CREATIVE_UPLOAD_MAX_FILES файлов и CREATIVE_UPLOAD_MAX_MB
  за срок хранения (как _quota у склейки) → upload_quota (409);
- запас свободного места проверяется и для фото, и для видео;
- видео до 90 МБ (Cloudflare Free пропускает тело до 100 МБ);
- обработка видео идёт в запросе, поэтому: одно видео человека за раз, одно
  перекодирование на процесс без ожидания (занято — сразу upload_busy, поток
  gunicorn не висит), и вся обработка укладывается в CONVERT_BUDGET_S — меньше
  100 с, которые Cloudflare ждёт ответа сервера.

Любой отказ после сохранения стирает свои файлы.
"""
from __future__ import annotations

import logging
import os
import shutil
import subprocess
import threading
import time
import uuid
from datetime import timedelta
from typing import Optional

from django.conf import settings
from django.core.cache import cache
from django.core.files.base import ContentFile
from django.core.files.storage import FileSystemStorage, default_storage
from django.db.models import Count, Sum
from django.utils import timezone

from .errors import CreativeError
from .models import CreativeUpload
from .storage import delete_files, ensure_dir, uploads_dir

logger = logging.getLogger(__name__)

MB = 1024 * 1024
IMAGE_MAX_BYTES = 20 * MB
IMAGE_MAX_SIDE = 2048
IMAGE_FORMATS = ("JPEG", "MPO", "PNG", "WEBP")
VIDEO_EXTENSIONS = ("mp4", "mov", "m4v", "webm")
VIDEO_CODECS = ("h264", "hevc", "vp8", "vp9", "av1", "mpeg4")
VIDEO_MIN_S = 4.0
VIDEO_MAX_S = 30.0
VIDEO_TOLERANCE_S = 0.5
VIDEO_MAX_SIDE = 4096
# При перекодировании длинная сторона не больше 1920: поставщик всё равно
# приводит кадр к 480p/720p/1080p, а 4K только раздувает файл и время.
TRANSCODE_MAX_SIDE = 1920
MULTIPART_SLACK = MB
HEAD_BYTES = 16
MIN_FREE_AFTER = 2 * 1024 * MB
# Предел видео: тело больше 100 МБ Cloudflare Free отрезает своей HTML-страницей 413
# (до nginx и core оно не доходит). Как у склейки (merge.config.UPLOAD_MAX_BYTES).
VIDEO_MAX_MB_CAP = 90
# Вся обработка видео (перепаковка, при неудаче перекодирование) — не дольше бюджета:
# Cloudflare ждёт ответа сервера 100 с, дальше 524, а загрузка без адресата.
CONVERT_BUDGET_S = 75
REMUX_TIMEOUT_S = 30
# Перекодирование тяжёлое и идёт в запросе: одно на процесс и БЕЗ ожидания —
# занято, значит сразу upload_busy (иначе ждущие запросы держат потоки gunicorn).
_convert_slots = threading.BoundedSemaphore(1)
# Одно видео человека за раз (замок в кэше; срок — с запасом над бюджетом).
USER_LOCK_TTL_S = 180
# Квота человека за срок хранения загрузок (как _quota у склейки).
UPLOAD_MAX_FILES_DEFAULT = 60
UPLOAD_MAX_MB_DEFAULT = 2048

_EBML = b"\x1a\x45\xdf\xa3"
_NOT_VIDEO_BRANDS = {b"heic", b"heix", b"heim", b"heis", b"mif1", b"msf1", b"avif", b"avis",
                     b"M4A ", b"M4B ", b"M4P ", b"crx "}


def video_max_bytes() -> int:
    try:
        mb = int(getattr(settings, "CREATIVE_VIDEO_MAX_MB", VIDEO_MAX_MB_CAP) or VIDEO_MAX_MB_CAP)
    except (TypeError, ValueError):
        mb = VIDEO_MAX_MB_CAP
    return max(1, min(mb, VIDEO_MAX_MB_CAP)) * MB


def _refuse(code: str, **extra) -> CreativeError:
    return CreativeError(code, **extra)


def _setting_int(name: str, default: int) -> int:
    try:
        return max(1, int(getattr(settings, name, default) or default))
    except (TypeError, ValueError):
        return default


def usage(user) -> dict:
    """Сколько места занимают загрузки человека за срок хранения."""
    days = _setting_int("CREATIVE_UPLOAD_KEEP_DAYS", 7)
    totals = (CreativeUpload.objects.filter(user=user, created_at__gt=timezone.now() - timedelta(days=days))
              .aggregate(files=Count("pk"), size=Sum("bytes")))
    return {"files": int(totals["files"] or 0), "bytes": int(totals["size"] or 0),
            "max_files": _setting_int("CREATIVE_UPLOAD_MAX_FILES", UPLOAD_MAX_FILES_DEFAULT),
            "max_bytes": _setting_int("CREATIVE_UPLOAD_MAX_MB", UPLOAD_MAX_MB_DEFAULT) * MB}


def _quota(user, extra_bytes: int) -> None:
    """Загрузки бесплатны: без квоты один человек занял бы общий диск (как _quota склейки)."""
    used = usage(user)
    if used["files"] >= used["max_files"] or used["bytes"] + int(extra_bytes) > used["max_bytes"]:
        raise _refuse("upload_quota", max_files=used["max_files"], max_mb=used["max_bytes"] // MB,
                      files=used["files"], used_mb=round(used["bytes"] / MB, 1))


def _user_lock(user) -> Optional[str]:
    """Замок «одно видео человека за раз». None — уже идёт другое. Кэш недоступен — не мешаем."""
    key = f"creative:upload:video:{user.pk}"
    try:
        return key if cache.add(key, 1, USER_LOCK_TTL_S) else None
    except Exception:
        logger.warning("creative: замок загрузки не взялся (кэш)", exc_info=True)
        return ""


def _user_unlock(key: Optional[str]) -> None:
    if key:
        try:
            cache.delete(key)
        except Exception:
            pass


def precheck(content_length) -> None:
    """До разбора тела: заявленный размер запроса."""
    try:
        declared = int(content_length or 0)
    except (TypeError, ValueError):
        declared = 0
    if declared > video_max_bytes() + MULTIPART_SLACK:
        raise _refuse("too_big", max_mb=video_max_bytes() // MB)


def _extension(name) -> str:
    base = str(name or "").replace("\\", "/").rsplit("/", 1)[-1]
    return os.path.splitext(base)[1].lower().lstrip(".")


def sniff(head: bytes) -> str:
    """Контейнер по первым байтам: mp4 | mov | webm | ""."""
    head = bytes(head or b"")
    if len(head) >= 12 and head[4:8] == b"ftyp":
        brand = head[8:12]
        if brand in _NOT_VIDEO_BRANDS:
            return ""
        return "mov" if brand == b"qt  " else "mp4"
    if head[:4] == _EBML:
        return "webm"
    return ""


# ---------------------------------------------------------------- фото

def accept_image(user, fileobj) -> CreativeUpload:
    from vstudio.assets import AssetError, _read_capped, normalize_image_bytes, sha256_hex

    if fileobj is None:
        raise _refuse("bad_request", field="file")
    try:
        blob = _read_capped(fileobj, IMAGE_MAX_BYTES)
    except AssetError:
        raise _refuse("too_big", max_mb=IMAGE_MAX_BYTES // MB) from None
    try:
        norm = normalize_image_bytes(blob, max_side=IMAGE_MAX_SIDE)
    except AssetError as exc:
        if exc.code == "throttled":
            raise _refuse("upload_busy") from None
        if exc.code == "too_many_pixels":
            raise _refuse("too_big") from None
        raise _refuse("unreadable") from None
    if str(norm.source_format or "").upper() not in IMAGE_FORMATS:
        raise _refuse("bad_type", formats=["jpeg", "png", "webp"])
    _quota(user, norm.size)
    if not _room_for(norm.size * 2):
        logger.error("creative: нет места — фото user=%s не принято", user.pk)
        raise _refuse("storage_unavailable")
    uid = uuid.uuid4().hex
    folder = uploads_dir(user.pk)
    ensure_dir(folder)
    saved: list[str] = []
    try:
        saved.append(default_storage.save(f"{folder}/{uid}.{norm.ext}", ContentFile(norm.data)))
        thumb = ""
        if norm.thumb:
            thumb = default_storage.save(f"{folder}/{uid}_t.jpg", ContentFile(norm.thumb))
            saved.append(thumb)
        return CreativeUpload.objects.create(
            uid=uid, user=user, kind=CreativeUpload.KIND_IMAGE, path=saved[0], thumb_path=thumb,
            mime=norm.mime, bytes=norm.size, w=norm.width, h=norm.height, sha256=sha256_hex(blob))
    except BaseException:
        delete_files(*saved)
        raise


# ---------------------------------------------------------------- видео

def _room_for(size: int) -> bool:
    try:
        return shutil.disk_usage(default_storage.location).free - int(size) >= MIN_FREE_AFTER
    except (OSError, AttributeError):
        logger.warning("creative: место на диске не измеряется, загрузку не принимаю", exc_info=True)
        return False


def probe(path: str, fmt: str):
    """Строгий разбор чужого файла (merge.render.probe). None — не читается."""
    from merge import render

    return render.probe(path, fmt)


def _scale_filter() -> str:
    m = TRANSCODE_MAX_SIDE
    return (f"scale='if(gte(iw,ih),min({m},trunc(iw/2)*2),-2)'"
            f":'if(gte(iw,ih),-2,min({m},trunc(ih/2)*2))',format=yuv420p")


def convert_cmd(src: str, dst: str, *, fmt: str, video_index, audio_index, remux: bool) -> list[str]:
    """Команда ffmpeg: перепаковка H.264 или перекодирование в H.264 — всегда MP4 без метаданных."""
    from merge import render

    cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-nostdin", "-y",
           *render.input_args(fmt), "-i", render.input_path(src, fmt)]
    cmd += ["-map", f"0:{video_index}" if video_index is not None else "0:v:0"]
    if audio_index is not None:
        cmd += ["-map", f"0:{audio_index}"]
    if remux:
        cmd += ["-c:v", "copy"]
    else:
        cmd += ["-vf", _scale_filter(), "-c:v", "libx264", "-preset", "veryfast", "-crf", "21",
                "-pix_fmt", "yuv420p", "-threads", "2"]
    if audio_index is not None:
        cmd += ["-c:a", "aac", "-b:a", "128k", "-ar", "48000", "-ac", "2"]
    cmd += ["-map_metadata", "-1", "-movflags", "+faststart", "-f", "mp4", dst]
    return cmd


def _run(cmd: list[str], timeout: float) -> bool:
    """ffmpeg с пределом времени. Не уложился — too_heavy (процесс убит subprocess.run)."""
    from merge import render

    try:
        result = render._run(cmd, timeout)
    except subprocess.TimeoutExpired:
        logger.warning("creative: ffmpeg не уложился в %s с", int(timeout))
        raise _refuse("too_heavy") from None
    except OSError:
        logger.warning("creative: ffmpeg не отработал", exc_info=True)
        return False
    if result.returncode != 0:
        logger.warning("creative: ffmpeg rc=%s: %s", result.returncode,
                       (result.stderr or b"")[-300:].decode("utf-8", "replace"))
        return False
    return True


def convert(src: str, dst: str, info, *, fmt: str) -> bool:
    """В MP4: H.264 — перепаковка, остальное — перекодирование. True — dst готов.

    Слот процесса берётся без ожидания (занято — upload_busy), всё вместе — не
    дольше CONVERT_BUDGET_S (не уложилось — too_heavy).
    """
    remux = info.codec == "h264"
    if not _convert_slots.acquire(blocking=False):
        raise _refuse("upload_busy")
    started = time.monotonic()
    try:
        ok = _run(convert_cmd(src, dst, fmt=fmt, video_index=info.video_index,
                              audio_index=info.audio_index, remux=remux),
                  min(REMUX_TIMEOUT_S, CONVERT_BUDGET_S) if remux else CONVERT_BUDGET_S)
        if not ok and remux:
            # Перепаковка не вышла (кривой поток) — честное перекодирование в остаток бюджета.
            left = CONVERT_BUDGET_S - (time.monotonic() - started)
            if left < 5:
                raise _refuse("too_heavy")
            ok = _run(convert_cmd(src, dst, fmt=fmt, video_index=info.video_index,
                                  audio_index=info.audio_index, remux=False), left)
        return ok and os.path.isfile(dst) and os.path.getsize(dst) > 0
    finally:
        _convert_slots.release()


def make_poster(path: str, poster_path: str, info) -> bool:
    from merge import render

    return render.make_upload_poster(path, poster_path, fmt="mov", video_index=info.video_index,
                                     duration=info.duration)


def _verdict(info) -> Optional[CreativeError]:
    if info is None:
        return _refuse("unreadable")
    if info.video_streams != 1 or info.codec not in VIDEO_CODECS:
        return _refuse("bad_type", codecs=list(VIDEO_CODECS))
    if not info.duration or not info.width or not info.height:
        return _refuse("unreadable")
    if info.duration < VIDEO_MIN_S:
        return _refuse("too_short", min_s=VIDEO_MIN_S, duration_s=info.duration)
    if info.duration > VIDEO_MAX_S + VIDEO_TOLERANCE_S:
        return _refuse("too_long", max_s=VIDEO_MAX_S, duration_s=info.duration)
    if max(info.width, info.height) > VIDEO_MAX_SIDE:
        return _refuse("too_big", max_side=VIDEO_MAX_SIDE)
    return None


def accept_video(user, fileobj) -> CreativeUpload:
    if fileobj is None:
        raise _refuse("bad_request", field="file")
    size = int(getattr(fileobj, "size", 0) or 0)
    limit = video_max_bytes()
    if size > limit:
        raise _refuse("too_big", max_mb=limit // MB)
    if _extension(getattr(fileobj, "name", "")) not in VIDEO_EXTENSIONS:
        raise _refuse("bad_type", extensions=list(VIDEO_EXTENSIONS))
    if size <= 0:
        raise _refuse("unreadable")
    try:
        fileobj.seek(0)
        container = sniff(fileobj.read(HEAD_BYTES))
        fileobj.seek(0)
    except (OSError, ValueError):
        raise _refuse("unreadable") from None
    if not container:
        raise _refuse("bad_type", extensions=list(VIDEO_EXTENSIONS))
    _quota(user, size)
    if not isinstance(default_storage, FileSystemStorage) or not _room_for(size * 2):
        logger.error("creative: нет места или хранилище не локальное — видео user=%s не принято",
                     user.pk)
        raise _refuse("storage_unavailable")
    lock = _user_lock(user)
    if lock is None:
        raise _refuse("upload_busy")
    try:
        return _store_video(user, fileobj, container)
    finally:
        _user_unlock(lock)


def _store_video(user, fileobj, container: str) -> CreativeUpload:
    uid = uuid.uuid4().hex
    folder = uploads_dir(user.pk)
    fmt = "matroska" if container == "webm" else "mov"
    saved: list[str] = []
    try:
        ensure_dir(folder)
        src_name = default_storage.save(f"{folder}/{uid}.src.{container}", fileobj)
        saved.append(src_name)
        src_path = default_storage.path(src_name)
        info = probe(src_path, fmt)
        refusal = _verdict(info)
        if refusal is not None:
            raise refusal
        final_name = f"{folder}/{uid}.mp4"
        final_path = default_storage.path(final_name)
        saved.append(final_name)
        if not convert(src_path, final_path, info, fmt=fmt):
            raise _refuse("unreadable")
        delete_files(src_name)
        saved.remove(src_name)
        final = probe(final_path, "mov")
        refusal = _verdict(final)
        if refusal is not None:
            raise refusal
        poster = f"{folder}/{uid}_t.jpg"
        saved.append(poster)
        if not make_poster(final_path, default_storage.path(poster), final):
            raise _refuse("unreadable")
        mode = getattr(default_storage, "file_permissions_mode", None)
        for name in (final_name, poster):
            if mode is not None:
                try:
                    os.chmod(default_storage.path(name), mode)
                except OSError:
                    pass
        return CreativeUpload.objects.create(
            uid=uid, user=user, kind=CreativeUpload.KIND_VIDEO, path=final_name, thumb_path=poster,
            mime="video/mp4", bytes=os.path.getsize(final_path),
            w=final.display_width or final.width, h=final.display_height or final.height,
            duration_s=float(final.duration))
    except BaseException:
        delete_files(*saved)
        raise


def accept(user, fileobj, kind: str) -> CreativeUpload:
    if kind == CreativeUpload.KIND_VIDEO:
        return accept_video(user, fileobj)
    if kind == CreativeUpload.KIND_IMAGE:
        return accept_image(user, fileobj)
    raise _refuse("bad_request", field="kind")


def upload_json(row: CreativeUpload) -> dict:
    return {"uid": row.uid, "kind": row.kind, "w": row.w, "h": row.h,
            "duration": round(float(row.duration_s), 2) if row.duration_s else None,
            "preview": row.thumb_url or (row.url if row.kind == CreativeUpload.KIND_IMAGE else "")}


__all__ = ["accept", "accept_image", "accept_video", "precheck", "sniff", "upload_json",
           "convert_cmd", "video_max_bytes", "usage"]
