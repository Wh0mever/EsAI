"""Свои видео человека в склейке (Build MU): приём, проверка, хранение, уборка.

Файл чужой, поэтому сначала дешёвые проверки, потом тяжёлые: размер по
Content-Length (тело ещё не разобрано) → квота по числу файлов → разбор
multipart → размер файла → расширение → первые байты (MP4/QuickTime — ftyp,
WebM/Matroska — EBML) → квота по объёму и место на диске → файл ложится под
именем, которое придумал сервер (uid) → строгий разбор ffprobe (render.probe с
демуксером) → кадр обложки, он же проверка, что картинка декодируется. Любой
отказ после сохранения стирает файл; отказ из-за самого файла оставляет строку
rejected без файла — видно, что люди пытаются загрузить.

Хранится 30 дней; склейка, в которую видео вошло, продлевает его до своего
срока. Уборка (merge.tasks.purge_expired) не трогает видео идущей склейки.
"""
from __future__ import annotations

import logging
import os
import shutil
import unicodedata
import uuid

from django.contrib.auth import get_user_model
from django.core.files.storage import FileSystemStorage, default_storage
from django.db import transaction
from django.db.models import Count, Sum
from django.utils import timezone

from . import render as ffmpeg
from .config import (MB, UPLOAD_CODECS, UPLOAD_DURATION_TOLERANCE_S, UPLOAD_EXTENSIONS,
                     UPLOAD_FPS_SLACK_FRAMES, UPLOAD_MAX_BYTES, UPLOAD_MAX_DURATION_S,
                     UPLOAD_MAX_FILES, UPLOAD_MAX_FPS, UPLOAD_MAX_SIDE, UPLOAD_MAX_TOTAL_BYTES,
                     UPLOAD_MIN_DURATION_S, upload_limits)
from .models import ACTIVE, MergeProject, MergeUpload
from .services import MergeError
from .sources import TITLE_CHARS, TYPE_UPLOAD, short, upload_source
from .storage import delete_files

logger = logging.getLogger(__name__)

# Обёртка multipart (граница, заголовки части) поверх самого файла.
MULTIPART_SLACK = MB
# Сколько места должно остаться на диске после файла: склейкам и роликам
# видеостудии, за которые уже заплачено, нужен свой гигабайт (storage_check).
MIN_FREE_AFTER = 2 * 1024 * MB
# Уборка: пачка и потолок пачек за один запуск.
PURGE_BATCH = 500
PURGE_MAX_BATCHES = 20
# Отклонённые строки файлов не имеют — их стираем пачками отдельно и первыми:
# иначе под наплывом отказов (до 20 в час на человека) они съели бы потолок
# уборки, и принятые видео жили бы дольше 30 дней.
PURGE_REJECTED_BATCH = 2000
PURGE_REJECTED_MAX_BATCHES = 100
HEAD_BYTES = 16
_EBML = b"\x1a\x45\xdf\xa3"
# ftyp есть и у картинок HEIF/AVIF и у звука M4A: это не видео, отказ сразу.
_NOT_VIDEO_BRANDS = {b"heic", b"heix", b"heim", b"heis", b"mif1", b"msf1", b"avif", b"avis",
                     b"M4A ", b"M4B ", b"M4P ", b"crx "}

MSG_NO_FILE = "Выберите видео для загрузки."
MSG_TOO_BIG = f"Файл больше {UPLOAD_MAX_BYTES // MB} МБ. Сожмите или обрежьте видео и загрузите снова."
MSG_BAD_TYPE = "Подходят только видео MP4, MOV или WebM."
MSG_NO_VIDEO = ("В файле нет подходящего видео: нужна одна видеодорожка "
                "H.264, HEVC, VP8, VP9, AV1 или MPEG-4.")
MSG_TOO_LONG = f"Видео длиннее {UPLOAD_MAX_DURATION_S} секунд. Обрежьте его и загрузите снова."
MSG_TOO_SHORT = "Видео короче полсекунды — такое не склеить."
MSG_RESOLUTION = (f"Кадр больше {UPLOAD_MAX_SIDE} точек по стороне. "
                  "Уменьшите разрешение и загрузите снова.")
MSG_UNREADABLE = "Файл не читается — возможно, он повреждён. Выберите другое видео."
MSG_FRAME_RATE = (f"В видео больше {UPLOAD_MAX_FPS} кадров в секунду — такое не склеить. "
                  "Сохраните его с частотой 30 или 60 кадров и загрузите снова.")
MSG_QUOTA = (f"Место для своих видео занято: хранится до {UPLOAD_MAX_FILES} файлов и до "
             f"{UPLOAD_MAX_TOTAL_BYTES // MB} МБ. Удалите старые в «Моих файлах» и загрузите снова.")
MSG_UNAVAILABLE = "Загрузка сейчас недоступна: на сервере не хватает места. Попробуйте позже."
MSG_NOT_FOUND = "Видео не найдено."
MSG_IN_USE = "Это видео сейчас склеивается — удалить его можно после окончания."

# Отказы из-за самого файла — их строка rejected остаётся для разбора.
FILE_REFUSALS = ("upload_too_big", "upload_bad_type", "upload_no_video", "upload_too_long",
                 "upload_too_short", "upload_resolution", "upload_frame_rate", "upload_unreadable")


def _refuse(code: str, message: str, status: int = 400, **extra) -> MergeError:
    return MergeError(code, message, status, **extra)


def too_big() -> MergeError:
    return _refuse("upload_too_big", MSG_TOO_BIG, max_mb=UPLOAD_MAX_BYTES // MB)


def bad_type() -> MergeError:
    return _refuse("upload_bad_type", MSG_BAD_TYPE, extensions=list(UPLOAD_EXTENSIONS))


def unreadable() -> MergeError:
    return _refuse("upload_unreadable", MSG_UNREADABLE)


# ---------------------------------------------------------------- проверки без ffmpeg

def sniff(head: bytes) -> str:
    """Расширение, под которым файл ляжет, по первым байтам: mp4, webm или ""."""
    head = bytes(head or b"")
    if len(head) >= 12 and head[4:8] == b"ftyp":
        return "" if head[8:12] in _NOT_VIDEO_BRANDS else "mp4"
    if head[:4] == _EBML:
        return "webm"
    return ""


def extension(name) -> str:
    base = str(name or "").replace("\\", "/").rsplit("/", 1)[-1]
    return os.path.splitext(base)[1].lower().lstrip(".")


def clean_title(name) -> str:
    """Подпись из имени файла с телефона: без папок, расширения и невидимых знаков."""
    base = str(name or "").replace("\\", "/").rsplit("/", 1)[-1]
    stem = os.path.splitext(base)[0]
    # Управляющие и форматирующие знаки (переворот строки справа налево,
    # нулевой ширины) превратили бы подпись в ловушку для глаз.
    text = "".join(" " if unicodedata.category(ch)[0] in ("C", "Z") else ch for ch in stem)
    return short(text, TITLE_CHARS)


def verdict(info) -> MergeError | None:
    """Подходит ли разобранный файл для склейки. None — подходит."""
    if info is None:
        return unreadable()
    if info.video_streams != 1 or info.codec not in UPLOAD_CODECS:
        return _refuse("upload_no_video", MSG_NO_VIDEO)
    if not info.duration or not info.width or not info.height:
        return unreadable()
    if info.duration < UPLOAD_MIN_DURATION_S:
        return _refuse("upload_too_short", MSG_TOO_SHORT, min_s=UPLOAD_MIN_DURATION_S,
                       duration_s=info.duration)
    if info.duration > UPLOAD_MAX_DURATION_S + UPLOAD_DURATION_TOLERANCE_S:
        return _refuse("upload_too_long", MSG_TOO_LONG, max_s=UPLOAD_MAX_DURATION_S,
                       duration_s=info.duration)
    if max(info.width, info.height) > UPLOAD_MAX_SIDE:
        return _refuse("upload_resolution", MSG_RESOLUTION, max_side=UPLOAD_MAX_SIDE,
                       width=info.width, height=info.height)
    # Кадры считаны чтением файла, а не из заголовка. Нет счёта — не судим
    # вслепую: такой файл склейке не отдаём.
    if info.frames is None:
        return unreadable()
    if info.frames > info.duration * UPLOAD_MAX_FPS + UPLOAD_FPS_SLACK_FRAMES:
        return _refuse("upload_frame_rate", MSG_FRAME_RATE, max_fps=UPLOAD_MAX_FPS,
                       fps=round(info.frames / info.duration))
    return None


# ---------------------------------------------------------------- квота и место

def _stored(user, now=None):
    """Видео, которые занимают место человека: принятые, не истёкшие."""
    return MergeUpload.objects.filter(user=user, status=MergeUpload.STATUS_READY,
                                      expires_at__gt=now or timezone.now()).exclude(file="")


def usage(user, now=None) -> dict:
    totals = _stored(user, now).aggregate(files=Count("pk"), size=Sum("size"))
    return {"files": int(totals["files"] or 0), "bytes": int(totals["size"] or 0),
            "max_files": UPLOAD_MAX_FILES, "max_bytes": UPLOAD_MAX_TOTAL_BYTES}


def _quota(user, extra_bytes: int = 0, *, files_only: bool = False) -> None:
    used = usage(user)
    over = used["files"] >= UPLOAD_MAX_FILES or (
        not files_only and used["bytes"] + int(extra_bytes) > UPLOAD_MAX_TOTAL_BYTES)
    if over:
        raise _refuse("upload_quota", MSG_QUOTA, 409, max_files=UPLOAD_MAX_FILES,
                      max_mb=UPLOAD_MAX_TOTAL_BYTES // MB, files=used["files"],
                      used_mb=round(used["bytes"] / MB, 1))


def free_bytes(path: str) -> int:
    return shutil.disk_usage(path).free


def _room_for(size: int) -> bool:
    """Ляжет ли файл так, чтобы на диске остался запас для оплаченных роликов."""
    try:
        return free_bytes(default_storage.location) - int(size) >= MIN_FREE_AFTER
    except (OSError, AttributeError):
        logger.warning("склейка: место на диске не измеряется, загрузку не принимаю", exc_info=True)
        return False


def folder(user_id) -> str:
    return f"merge/uploads/{user_id}"


def _ensure_folder(user_id) -> None:
    # Каталог заводит core (root), а читает воркер media (appuser): права —
    # chmod через make_dirs видеостудии, а не umask процесса (урок 09.10.2026).
    from vstudio.assets import make_dirs

    make_dirs(default_storage.path(folder(user_id)), default_storage.directory_permissions_mode)


# ---------------------------------------------------------------- приём

def precheck(user, content_length) -> None:
    """До разбора тела: заявленный размер и число файлов. Бросает MergeError."""
    try:
        declared = int(content_length or 0)
    except (TypeError, ValueError):
        declared = 0
    if declared > UPLOAD_MAX_BYTES + MULTIPART_SLACK:
        raise too_big()
    # Свои истёкшие и ни во что не занятые — освободить сразу, а не ждать ночи.
    purge(user=user)
    _quota(user, files_only=True)


def _reject(user, code: str, title: str, size: int) -> None:
    try:
        with transaction.atomic():
            MergeUpload.objects.create(user=user, status=MergeUpload.STATUS_REJECTED,
                                       error_code=code[:40], title=title, size=max(0, int(size)))
    except Exception:
        logger.warning("склейка: отказ загрузки не записался", exc_info=True)


def accept(user, fileobj, *, lang: str = "ru") -> MergeUpload:
    """Принять своё видео (поле file запроса). Бросает MergeError с кодом отказа."""
    if fileobj is None:
        raise MergeError("bad_request", MSG_NO_FILE, field="file")
    title = clean_title(getattr(fileobj, "name", ""))
    size = int(getattr(fileobj, "size", 0) or 0)
    try:
        return _accept(user, fileobj, title, size)
    except MergeError as exc:
        if exc.code in FILE_REFUSALS:
            _reject(user, exc.code, title, size)
            logger.info("склейка: загрузка user=%s отклонена: %s", user.pk, exc.code)
        raise


def _accept(user, fileobj, title: str, size: int) -> MergeUpload:
    if size > UPLOAD_MAX_BYTES:
        raise too_big()
    if extension(getattr(fileobj, "name", "")) not in UPLOAD_EXTENSIONS:
        raise bad_type()
    if size <= 0:
        raise unreadable()
    try:
        fileobj.seek(0)
        ext = sniff(fileobj.read(HEAD_BYTES))
        fileobj.seek(0)
    except (OSError, ValueError):
        raise unreadable() from None
    if not ext:
        raise bad_type()
    _quota(user, size)
    if not isinstance(default_storage, FileSystemStorage) or not _room_for(size):
        logger.error("склейка: нет места или хранилище не локальное — загрузка user=%s не принята",
                     user.pk)
        raise _refuse("upload_unavailable", MSG_UNAVAILABLE, 503)

    uid = uuid.uuid4().hex
    fmt = "matroska" if ext == "webm" else "mov"
    saved: list[str] = []
    try:
        _ensure_folder(user.pk)
        name = default_storage.save(f"{folder(user.pk)}/{uid}.{ext}", fileobj)
        saved.append(name)
        path = default_storage.path(name)
        info = ffmpeg.probe(path, fmt)
        refusal = verdict(info)
        if info is None:
            # Строгий разбор не открыл файл: если в заголовках есть видео в неподходящем
            # формате (ProRes и т. п.), честнее сказать про формат, чем про поломку.
            codecs = ffmpeg.upload_video_codecs(path, fmt)
            if codecs and any(codec not in UPLOAD_CODECS for codec in codecs):
                refusal = _refuse("upload_no_video", MSG_NO_VIDEO)
        if refusal is not None:
            raise refusal
        poster = f"{folder(user.pk)}/{uid}.jpg"
        saved.append(poster)
        poster_path = default_storage.path(poster)
        if not ffmpeg.make_upload_poster(path, poster_path, fmt=fmt, video_index=info.video_index,
                                         duration=info.duration):
            raise unreadable()
        mode = getattr(default_storage, "file_permissions_mode", None)
        if mode is not None:
            os.chmod(poster_path, mode)
        with transaction.atomic():
            # Замок строки пользователя: две загрузки разом не проскочат квоту
            # вдвоём, а удаление и запуск склейки ждут того же замка.
            get_user_model().objects.select_for_update().filter(pk=user.pk).first()
            _quota(user, size)
            return MergeUpload.objects.create(
                uid=uid, user=user, title=title, file=name, poster=poster, size=size,
                duration_s=info.duration, width=info.width, height=info.height,
                display_width=info.display_width, display_height=info.display_height,
                rotation=info.rotation, has_audio=info.audio, video_codec=info.codec[:16],
                hdr=info.hdr, status=MergeUpload.STATUS_READY)
    except BaseException:
        delete_files(*saved)
        raise


# ---------------------------------------------------------------- список, удаление, уборка

def card(row: MergeUpload, lang: str = "ru") -> dict:
    return upload_source(row, lang).card()


def listing(user, *, lang: str = "ru") -> dict:
    """«Мои файлы»: свои видео (новые сверху), занятое место и пределы."""
    from .sources import _usable

    rows = list(_stored(user).order_by("-created_at", "-pk")[:UPLOAD_MAX_FILES * 5])
    cards = [s.card() for s in _usable([upload_source(r, lang) for r in rows], check_files=True)]
    return {"results": cards, "usage": usage(user), "limits": upload_limits()}


def upload_ids(items) -> list[str]:
    return [str(i.get("id")) for i in items or []
            if isinstance(i, dict) and i.get("type") == TYPE_UPLOAD and i.get("id")]


def in_use(user=None) -> set[str]:
    """uid своих видео в склейках, которые сейчас в очереди или в работе."""
    qs = MergeProject.objects.filter(status__in=ACTIVE)
    if user is not None:
        qs = qs.filter(user=user)
    busy: set[str] = set()
    for items in qs.values_list("items", flat=True):
        busy.update(upload_ids(items))
    return busy


def hold(user_id, uids, until) -> int:
    """Продлить хранение своих видео до until (сроки только растут)."""
    uids = [u for u in uids or [] if u]
    if not uids:
        return 0
    return MergeUpload.objects.filter(user_id=user_id, uid__in=uids, status=MergeUpload.STATUS_READY,
                                      expires_at__lt=until).update(expires_at=until)


def delete_upload(user, uid) -> None:
    """Удалить своё видео. Пока его склеивают — нельзя (409)."""
    uid = str(uid or "").strip().lower()
    with transaction.atomic():
        # Тот же замок, что у запуска склейки: видео не пропадёт между проверкой
        # фрагментов и постановкой в очередь.
        get_user_model().objects.select_for_update().filter(pk=user.pk).first()
        row = MergeUpload.objects.filter(user=user, uid=uid, status=MergeUpload.STATUS_READY).first()
        if row is None:
            raise _refuse("upload_not_found", MSG_NOT_FOUND, 404)
        if uid in in_use(user):
            raise _refuse("upload_in_use", MSG_IN_USE, 409)
        # Файлы стирает сигнал после коммита: откатившееся удаление их не тронет.
        row.delete()


def purge(now=None, *, user=None, batch: int = PURGE_BATCH) -> int:
    """Стереть истёкшие свои видео (файл и строку), если ни одна идущая склейка
    их не использует; до них — отклонённые строки старше срока."""
    now = now or timezone.now()
    count = _purge_rejected(now, user)
    busy = in_use(user)
    qs = MergeUpload.objects.filter(expires_at__lt=now, status=MergeUpload.STATUS_READY)
    if user is not None:
        qs = qs.filter(user=user)
    last = 0
    for _ in range(PURGE_MAX_BATCHES):
        rows = list(qs.filter(pk__gt=last).order_by("pk")
                    .only("pk", "uid", "expires_at", "file", "poster")[:batch])
        for row in rows:
            last = row.pk
            if row.uid in busy:
                continue
            # Условно по сроку: склейку могли запустить, и она продлила видео.
            deleted, _ = MergeUpload.objects.filter(pk=row.pk, expires_at=row.expires_at).delete()
            if deleted:
                delete_files(row.file, row.poster)
                count += 1
        if len(rows) < batch:
            break
    if count:
        logger.info("склейка: стёрто своих видео %s", count)
    return count


def _purge_rejected(now, user=None) -> int:
    """Истёкшие отклонённые строки — пачками по pk, без файлов и без проверки склеек."""
    qs = MergeUpload.objects.filter(status=MergeUpload.STATUS_REJECTED, expires_at__lt=now)
    if user is not None:
        qs = qs.filter(user=user)
    count = 0
    for _ in range(PURGE_REJECTED_MAX_BATCHES):
        pks = list(qs.order_by("pk").values_list("pk", flat=True)[:PURGE_REJECTED_BATCH])
        if not pks:
            break
        deleted, _ = MergeUpload.objects.filter(pk__in=pks).delete()
        count += deleted
        if len(pks) < PURGE_REJECTED_BATCH:
            break
    return count


__all__ = ["accept", "precheck", "verdict", "sniff", "clean_title", "extension", "usage",
           "listing", "card", "delete_upload", "purge", "hold", "in_use", "upload_ids",
           "FILE_REFUSALS"]
