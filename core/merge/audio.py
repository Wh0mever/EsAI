"""Звук склейки (Build MA): голос за кадром, фоновая музыка, звук самих роликов.

Решения лида: у склейки один голос и одна музыка. Голос — текст и голос
ElevenLabs с выбранного фрагмента, по цене озвучки мультстудии (20 кр за 1000
знаков); музыка — по описанию на всю длину склейки (30 кр за минуту) или свой
трек бесплатно; звук роликов — оставить, тише или выключить. Всё сводится при
«Склеить» (merge.render.mix_cmd), цена склейки та же. Генерация и проверки
файлов — функции мультстудии (cartoon.audio), не копии.

Деньги — правило cartoon.views_audio._generate (списание только за готовый
звук), но с настоящим резервом: заказ ставит строку pending с ценой в
credits_reserved (её видят все гейты сайта через merge.services.reserved_credits),
потом провайдер — вне транзакции и замков, потом списание в той же транзакции,
что делает дорожку готовой; сбой — failed тем же UPDATE, что снимает резерв.
Замок — строка пользователя, как у запуска склейки: два заказа разом встают в
очередь, и второй видит первый (pending) — audio_busy. Повтор того же запроса
(request_id) отвечает той же дорожкой и второй раз не платится — и когда её уже
заменили или убрали (ключ хранит MergeAudioRequest).

Порядок замков один на всё, что трогает звук: строка пользователя → строка
склейки → строки дорожек (LOCK_ORDER). Так их берут заказ, доставка звука,
PATCH audio/, удаление склейки и загрузка трека; удаление дорожки начинает со
склейки — это тот же порядок без первого шага. Два пути, берущие одни и те же
строки в разном порядке, на PostgreSQL могут встать в дедлок: одна из транзакций
падает, и голос, за который провайдер уже взял деньги, теряется.

Голос делается в самом запросе (до 2000 знаков — секунды у провайдера), музыка —
задачей в очереди media: пять минут музыки провайдер делает дольше, чем
Cloudflare ждёт ответа (100 с). Музык разом на весь сайт — не больше
merge_music_concurrency (места в кэше): заказ сверх него получает music_busy до
всякого резерва.
"""
from __future__ import annotations

import logging
import math
import os
import re
import tempfile
import uuid
from datetime import timedelta

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.core.files import File
from django.core.files.storage import FileSystemStorage, default_storage
from django.db import IntegrityError, transaction
from django.db.models import Sum
from django.utils import timezone

from cartoon import audio as studio

from . import render as ffmpeg
from . import services
from .config import (AUDIO_RETENTION_DAYS, AUDIO_UPLOAD_MAX_BYTES, AUDIO_UPLOAD_MAX_CHANNELS,
                     AUDIO_UPLOAD_MAX_RATE, AUDIO_UPLOAD_MAX_S, AUDIO_UPLOAD_TOLERANCE_S, CLIP_SOUNDS,
                     CLIP_VOLUMES, MB, MUSIC_CONCURRENCY_MAX, MUSIC_MAX_S, MUSIC_PROMPT_MAX,
                     MUSIC_PROMPT_MIN, MUSIC_VOLUME_MAX, VOICE_MAX_CHARS, VOICE_VOLUME_MAX, audio_volumes,
                     music_concurrency)
from .models import ACTIVE, EDITABLE, MergeAudio, MergeAudioRequest, MergeProject
from .services import MergeError
from .sources import local_path, media_url
from .storage import delete_files

logger = logging.getLogger(__name__)

VOICE = MergeAudio.KIND_VOICE
MUSIC = MergeAudio.KIND_MUSIC
PENDING = MergeAudio.STATUS_PENDING
READY = MergeAudio.STATUS_READY
FAILED = MergeAudio.STATUS_FAILED

# Причины списания в леджере (plans.TokenTransactionReason).
REASON_VOICE = "merge_voice"
REASON_MUSIC = "merge_music"

# В каком порядке пути звука берут замки строк (см. описание модуля); тесты сверяют с ним запросы.
LOCK_ORDER = ("user", "merge", "audio")

# Голос делается в запросе (до трёх минут ожидания провайдера): строка pending
# старше этого — оборванный запрос (деплой, убитый воркер); её резерв снимает
# уборка раз в пять минут.
VOICE_STALE_AFTER = timedelta(minutes=10)
# Музыка: очередь media общая с мультстудией и склейкой — как у склейки, два
# часа; взятая задача живёт до своего жёсткого лимита.
MUSIC_QUEUE_TIMEOUT = timedelta(hours=2)
MUSIC_SOFT_LIMIT = 10 * 60
MUSIC_HARD_LIMIT = MUSIC_SOFT_LIMIT + 60
# Ожидание ответа провайдера: общие 180 с мультстудии пятиминутной музыке малы
# (около минуты работы на минуту трека); минута запаса до мягкого лимита задачи.
MUSIC_READ_TIMEOUT = (10, MUSIC_SOFT_LIMIT - 60)
MUSIC_STALE_AFTER = timedelta(seconds=MUSIC_HARD_LIMIT) + timedelta(minutes=5)
# Места музыки — ключи кэша merge:music-slot:<n>, значение — uid заказа. Место
# занимает заказ (до резерва), держит его, пока задача стоит в очереди и ждёт
# провайдера, а отпускает задача в finally. Срок ключа дольше жёсткого лимита
# задачи: место умершего воркера или потерянной задачи освобождается само.
MUSIC_SLOT_PREFIX = "merge:music-slot"
MUSIC_SLOT_TTL = MUSIC_HARD_LIMIT + 60
PURGE_BATCH = 500
PURGE_MAX_BATCHES = 20
HEAD_BYTES = 16
# Обёртка multipart поверх самого файла.
UPLOAD_SLACK = MB

_REQUEST_ID = re.compile(r"[A-Za-z0-9_-]{1,64}")
_ASF = bytes.fromhex("3026b2758e66cf11")
# ftyp бывает и у картинок HEIF/AVIF — это не звук.
_NOT_AUDIO_BRANDS = {b"heic", b"heix", b"heim", b"heis", b"mif1", b"msf1", b"avif", b"avis", b"crx "}
# Под каким расширением трек уходит в save_audio: тем же, что показали первые
# байты. Демуксер и декодеры пересборки задаёт не расширение, а input_options
# (render.audio_input_args) — те же, что у строгого разбора.
FORMAT_SUFFIX = {"mp3": ".mp3", "aac": ".aac", "mov": ".m4a", "wav": ".wav", "ogg": ".ogg",
                 "matroska": ".mka", "flac": ".flac", "aiff": ".aiff", "caf": ".caf", "asf": ".wma",
                 "amr": ".amr"}

MSG_NOT_CONFIGURED = "Голос и музыка по описанию пока не подключены. Свой трек можно загрузить."
MSG_READY_LOCKED = ("Звук готовой склейки не меняется. Нажмите «Изменить и склеить заново» — "
                    "звук перейдёт в новую склейку.")
MSG_BUSY = "Звук для этой склейки ещё делается — дождитесь его."
MSG_PENDING = "Голос или музыка ещё делаются — дождитесь их и нажмите «Склеить»."
MSG_PRICE_CHANGED = "Цена изменилась: теперь {credits} кр. Проверьте и нажмите ещё раз."
MSG_NO_TEXT = "Напишите текст для озвучки."
MSG_TEXT_TOO_LONG = "Текст длиннее {max} символов — сократите его."
MSG_NO_VOICE = "Выберите голос."
MSG_BAD_FRAGMENT = "Такого фрагмента в склейке нет — выберите, с какого начать голос."
MSG_NO_PROMPT = "Опишите музыку хотя бы парой слов."
MSG_PROMPT_TOO_LONG = "Описание музыки — не длиннее {max} символов."
MSG_NO_FRAGMENTS = "Сначала добавьте фрагменты: музыка создаётся под длину склейки."
MSG_NO_CREDITS_VOICE = "Недостаточно кредитов для озвучки."
MSG_NO_CREDITS_MUSIC = "Недостаточно кредитов для музыки."
MSG_FAILED = "Не получилось сделать звук — кредиты не списаны, попробуйте ещё раз."
MSG_PROVIDER_DOWN = "Сервис звука временно недоступен — кредиты не списаны, попробуйте позже."
MSG_PROVIDER_BUSY = "Сервис звука перегружен — подождите минуту и попробуйте снова. Кредиты не списаны."
MSG_STALE = "Звук не успел сделаться — кредиты не списаны, попробуйте ещё раз."
MSG_QUEUE_DOWN = "Музыка не запустилась — кредиты не списаны, попробуйте ещё раз."
MSG_MUSIC_BUSY = "Сейчас готовится много музыки — попробуйте через минуту. Кредиты не списаны."
MSG_TRACK_NOT_FOUND = "Дорожка не найдена."
MSG_NO_VOICE_TRACK = "Голоса за кадром пока нет — сначала озвучьте текст."
MSG_BAD_BODY = "Настройки звука не распознаны. Обновите страницу и попробуйте снова."
MSG_BAD_CLIP = "Звук роликов: keep (оставить), quiet (тише) или off (выключить)."
MSG_BAD_MUSIC_VOLUME = f"Громкость музыки — число от 0 до {MUSIC_VOLUME_MAX:g}."
MSG_BAD_VOICE_VOLUME = f"Громкость голоса — число от 0 до {VOICE_VOLUME_MAX:g}."
MSG_NO_FILE = "Выберите аудиофайл."
MSG_TOO_BIG = (f"Файл больше {AUDIO_UPLOAD_MAX_BYTES // MB} МБ. "
               "Выберите трек поменьше или сожмите его.")
MSG_BAD_TYPE = "Этот формат не подходит — загрузите MP3, M4A, WAV, OGG, FLAC или другой аудиофайл."
MSG_UNREADABLE = "Файл не читается — возможно, он повреждён. Выберите другой трек."
MSG_NO_SOUND = "В файле нет звука, который можно использовать. Выберите другой трек."
MSG_TOO_LONG = f"Трек длиннее {AUDIO_UPLOAD_MAX_S // 60} минут. Обрежьте его и загрузите снова."
MSG_UNSUPPORTED = (f"Такой трек не подходит: в нём больше {AUDIO_UPLOAD_MAX_CHANNELS} каналов или частота "
                   f"выше {AUDIO_UPLOAD_MAX_RATE // 1000} кГц. Сохраните его как обычное стерео, например "
                   "в MP3, и загрузите снова.")
MSG_MISSING = ("Звуковая дорожка склейки пропала. Удалите её во вкладке «Звук» и склейте снова — "
               "кредиты не списаны.")


class _Gone(Exception):
    """Дорожку закрыла уборка или склейку удалили, пока делался звук."""


def _bad(field: str, message: str, **extra) -> MergeError:
    return MergeError("bad_request", message, field=field, **extra)


# ---------------------------------------------------------------- состояние

def folder(user_id) -> str:
    return f"merge/audio/{user_id}"


def _ensure_folder(user_id) -> None:
    # Каталог заводит core (root), а пишет в него и воркер media (appuser, музыка):
    # права — chmod через make_dirs видеостудии, а не umask процесса (урок 09.10.2026).
    if not isinstance(default_storage, FileSystemStorage):
        return
    from vstudio.assets import make_dirs

    make_dirs(default_storage.path(folder(user_id)), default_storage.directory_permissions_mode)


def limits() -> dict:
    """Пределы звука для интерфейса: те же числа, что проверяет сервер."""
    extensions = list(studio.UPLOAD_EXTENSIONS)
    return {
        "voice_chars": VOICE_MAX_CHARS,
        "prompt_min_chars": MUSIC_PROMPT_MIN,
        "prompt_chars": MUSIC_PROMPT_MAX,
        "music_min_s": studio.MUSIC_MIN_SEC,
        "music_max_s": MUSIC_MAX_S,
        "upload_max_bytes": AUDIO_UPLOAD_MAX_BYTES,
        "upload_max_mb": AUDIO_UPLOAD_MAX_BYTES // MB,
        "upload_max_s": AUDIO_UPLOAD_MAX_S,
        "extensions": extensions,
        "accept": "audio/*," + ",".join(f".{ext}" for ext in extensions),
        "music_volume_max": MUSIC_VOLUME_MAX,
        "voice_volume_max": VOICE_VOLUME_MAX,
        "clip_sounds": list(CLIP_SOUNDS),
        "clip_volumes": dict(CLIP_VOLUMES),
        "retention_days": AUDIO_RETENTION_DAYS,
    }


def music_seconds(total_s) -> int:
    """Сколько секунд музыки заказать под склейку длиной total_s (0 — фрагментов нет)."""
    total = float(total_s or 0)
    if total <= 0:
        return 0
    return int(min(MUSIC_MAX_S, max(studio.MUSIC_MIN_SEC, math.ceil(total - 0.001))))


def prices() -> dict:
    table = studio.prices()
    return {"voice_per_1k": table["voice_per_1k"], "voice_min": table["voice_min"],
            "music_per_min": table["music_per_min"]}


def _iso(value):
    return value.isoformat() if value else None


def track_json(row: MergeAudio, fragments: int | None = None) -> dict:
    """Дорожка для панели «Звук». fragments — сколько фрагментов в склейке сейчас: голос,
    чей номер за концом списка (фрагменты убрали), звучит с последнего — это и есть
    start_fragment_effective."""
    ready = row.status == READY and bool(row.file)
    effective = None
    if row.kind == VOICE and fragments is not None:
        effective = min(row.start_fragment, max(0, int(fragments) - 1))
    return {
        "id": row.uid,
        "kind": row.kind,
        "source": row.source,
        "status": row.status,
        "url": media_url(row.file) if ready else None,
        "duration_s": row.duration_s,
        "text": row.text,
        "prompt": row.prompt,
        "title": row.title,
        "voice_id": row.voice_id,
        "voice_name": row.voice_name,
        "start_fragment": row.start_fragment if row.kind == VOICE else None,
        "start_fragment_effective": effective,
        "seconds": row.seconds,
        "credits_reserved": row.credits_reserved,
        "credits_charged": row.credits_charged,
        "error": row.error,
        "error_code": row.error_code or None,
        # Ключ нажатия, которым дорожку заказали: клиент, у которого ответ не дошёл, по нему
        # узнаёт свой заказ среди дорожек (не вышел — новый ключ, иначе повтор тем же). Ответы
        # звука видит только владелец склейки; у своего трека и копий ключа нет — null.
        "request_id": row.request_id or None,
        "created_at": _iso(row.created_at),
        "expires_at": _iso(row.expires_at),
    }


def edit_refusal(project: MergeProject) -> MergeError | None:
    """Почему звук этой склейки сейчас менять нельзя (409) или None."""
    if project.status in ACTIVE:
        return MergeError("render_in_progress", services.MSG_IN_PROGRESS, 409)
    if project.status not in EDITABLE:
        return MergeError("audio_ready_locked", MSG_READY_LOCKED, 409)
    return None


def state(project: MergeProject) -> dict:
    """Всё о звуке склейки для панели «Звук»."""
    items = [i for i in project.items or [] if isinstance(i, dict)]
    total = services.total_duration(items)
    seconds = music_seconds(total)
    refusal = edit_refusal(project)
    rows = list(MergeAudio.objects.filter(project=project).order_by("kind", "created_at", "pk"))
    _, music_volume, voice_volume = audio_volumes(project.clip_sound, project.music_volume,
                                                  project.voice_volume)
    return {
        "project_id": project.uid,
        "status": project.status,
        "editable": refusal is None,
        "edit_block": {"error_code": refusal.code, "error": refusal.message} if refusal else None,
        "configured": studio.is_configured(),
        "clip_sound": project.clip_sound,
        "music_volume": music_volume,
        "voice_volume": voice_volume,
        "tracks": [track_json(r, len(items)) for r in rows],
        "fragments": len(items),
        "total_duration_s": total,
        "prices": prices(),
        "music_quote": {"seconds": seconds, "credits": studio.music_price(seconds)} if seconds else None,
        "limits": limits(),
    }


def summary(project: MergeProject) -> dict:
    """Коротко о звуке — для полного JSON склейки (значок «Звук», подсказка у кнопки)."""
    rows = set(MergeAudio.objects.filter(project=project).values_list("kind", "status"))
    _, music_volume, voice_volume = audio_volumes(project.clip_sound, project.music_volume,
                                                  project.voice_volume)
    return {"clip_sound": project.clip_sound, "music_volume": music_volume, "voice_volume": voice_volume,
            "voice": (VOICE, READY) in rows, "music": (MUSIC, READY) in rows,
            "pending": any(status == PENDING for _, status in rows)}


# ---------------------------------------------------------------- общее для заказов

def _check_configured() -> None:
    if not studio.is_configured():
        raise MergeError("audio_not_configured", MSG_NOT_CONFIGURED, 503)


def _request_id(raw) -> str:
    value = str(raw or "").strip() if isinstance(raw, (str, int)) and not isinstance(raw, bool) else ""
    return value if _REQUEST_ID.fullmatch(value) else ""


def _fragment_index(raw) -> int | None:
    """Номер фрагмента (с 0) из запроса или None. Дробное и логическое — не номер."""
    if isinstance(raw, bool):
        return None
    if isinstance(raw, int):
        value = raw
    elif isinstance(raw, str) and raw.strip().isdigit():
        value = int(raw.strip())
    elif raw is None:
        value = 0
    else:
        return None
    return value if 0 <= value <= 32767 else None


def _to_draft(project: MergeProject) -> list[str]:
    """Звук неудачной или истёкшей склейки изменился — она снова черновик (как при
    правке фрагментов): старая ошибка относится к прежнему звуку. Поля для save()."""
    if project.status == MergeProject.STATUS_DRAFT:
        return []
    project.status = MergeProject.STATUS_DRAFT
    project.error = ""
    project.error_code = ""
    project.error_fragment = None
    project.progress_stage = ""
    project.progress_done = 0
    project.progress_total = 0
    return ["status", "error", "error_code", "error_fragment", "progress_stage", "progress_done",
            "progress_total"]


def _touch(project: MergeProject) -> None:
    project.save(update_fields=[*_to_draft(project), "updated_at"])


def _remove(rows) -> None:
    """Стереть дорожки (замена, свой трек, ✕), сохранив ключи их заказов (MergeAudioRequest).

    Ключ живёт в строке дорожки: без этой памяти вкладка, у которой ответ на заказ не
    дошёл, повторила бы его после замены — и сервер заказал и списал бы звук второй раз.
    Снимок — дорожка, какой она ушла, без файла (его стирает сигнал после коммита).
    """
    gone = [MergeAudioRequest(project_id=row.project_id, kind=row.kind, request_id=row.request_id,
                              track={**track_json(row), "url": None})
            for row in rows if row.request_id]
    if gone:
        MergeAudioRequest.objects.bulk_create(gone, ignore_conflicts=True)
    MergeAudio.objects.filter(pk__in=[row.pk for row in rows]).delete()


def _replayed(project: MergeProject, kind: str, request_id: str) -> dict | None:
    """Повтор ключа, чья дорожка уже ушла: снимок той дорожки или None."""
    track = (MergeAudioRequest.objects.filter(project=project, kind=kind, request_id=request_id)
             .values_list("track", flat=True).first())
    return dict(track) if track else None


def _balance_refusal(locked, price: int, kind: str) -> MergeError | None:
    """402 в форме чата (PaywallModal работает без правок): свободный остаток — баланс
    минус все резервы сайта, включая звук и склейки в работе."""
    from ai.generation import video_balance_error
    from vstudio.reserve import total_reserved

    reserved = total_reserved(locked, strict=True)
    refusal = video_balance_error(int(locked.token_balance or 0), reserved, int(price))
    if refusal is None:
        return None
    refusal["error"] = (services.MSG_NO_CREDITS_RESERVED if reserved > 0
                        else MSG_NO_CREDITS_VOICE if kind == VOICE else MSG_NO_CREDITS_MUSIC)
    return MergeError(refusal.pop("error_code"), refusal.pop("error"), 402, **refusal)


def _reserve(user, uid, kind: str, prepare, *, request_id: str, data: dict):
    """Резерв заказа: (склейка, строка, создана ли сейчас). Бросает MergeError.

    Под замком строки пользователя: тот же ключ запроса → та же дорожка, а ушла
    она — её снимок (без второго резерва) → склейку можно менять → своего вида звук не в работе →
    prepare(склейка) проверяет заказ и называет цену → цена из тела против
    текущей → свободный остаток → строка pending с резервом. Прошлую неудачу
    этого вида заменяет новый заказ.
    """
    with transaction.atomic():
        locked = get_user_model().objects.select_for_update().get(pk=user.pk)
        project = services.get_project(locked, uid, lock=True)
        if request_id:
            same = MergeAudio.objects.filter(project=project, kind=kind, request_id=request_id).first()
            if same is not None:
                return project, same, False
            # Дорожку заказа уже заменили или убрали — заказ был, второй раз не заказываем.
            gone = _replayed(project, kind, request_id)
            if gone is not None:
                return project, gone, False
        refusal = edit_refusal(project)
        if refusal:
            raise refusal
        if MergeAudio.objects.filter(project=project, kind=kind, status=PENDING).exists():
            raise MergeError("audio_busy", MSG_BUSY, 409)
        fields, price = prepare(project)
        if "price" in data and data["price"] is not None:
            try:
                expected = int(data["price"])
            except (TypeError, ValueError):
                expected = None
            if expected != price:
                raise MergeError("audio_price_changed", MSG_PRICE_CHANGED.format(credits=price), 409,
                                 credits=price)
        if price > 0:
            refusal = _balance_refusal(locked, price, kind)
            if refusal:
                raise refusal
        _remove(list(MergeAudio.objects.filter(project=project, kind=kind, status=FAILED)))
        try:
            with transaction.atomic():
                row = MergeAudio.objects.create(project=project, kind=kind, status=PENDING,
                                                credits_reserved=price, request_id=request_id, **fields)
        except IntegrityError:
            # Гонка мимо замка: индекс «один в работе на вид».
            raise MergeError("audio_busy", MSG_BUSY, 409) from None
        _touch(project)
    return project, row, True


def _release(pk: int, code: str, message: str) -> bool:
    """Сбой заказа: failed и резерв снят одним условным UPDATE."""
    return bool(MergeAudio.objects.filter(pk=pk, status=PENDING).update(
        status=FAILED, credits_reserved=0, error=str(message)[:300], error_code=code[:40],
        updated_at=timezone.now()))


def _failure(exc: Exception) -> tuple[str, str, int]:
    """Отказ провайдера словами человека: (код, текст, HTTP-статус)."""
    if isinstance(exc, studio.AudioNotConfigured):
        return "audio_not_configured", MSG_NOT_CONFIGURED, 503
    text = str(exc)
    # Тариф ElevenLabs без музыки (случай мультстудии 22.09: 402 paid_plan_required),
    # кончилась квота, отозван ключ — «попробуйте ещё раз» тут не поможет.
    if any(mark in text for mark in ("paid_plan_required", "not available for free users", "http 401",
                                     "http 402")) or "quota" in text.lower():
        return "audio_unavailable", MSG_PROVIDER_DOWN, 502
    if "http 429" in text:
        return "audio_overloaded", MSG_PROVIDER_BUSY, 502
    return "audio_failed", MSG_FAILED, 502


def _deliver(pk: int, user_id: int, *, path: str, duration: float) -> int:
    """Звук готов: списание и запись дорожки одной транзакцией. Бросает _Gone."""
    now = timezone.now()
    with transaction.atomic():
        # LOCK_ORDER: пользователь, склейка, дорожка — по одной строке за шаг. Прежний
        # select_related("project") под FOR UPDATE запирал дорожку и склейку одним запросом
        # и встречался с PATCH audio/ (склейка → дорожки) в обратном порядке.
        user = get_user_model().objects.select_for_update().filter(pk=user_id).first()
        project_id = MergeAudio.objects.filter(pk=pk).values_list("project_id", flat=True).first()
        project = (MergeProject.objects.select_for_update().filter(pk=project_id).first()
                   if project_id is not None else None)
        row = (MergeAudio.objects.select_for_update().filter(pk=pk, project_id=project_id, status=PENDING).first()
               if project is not None else None)
        if user is None or row is None:
            raise _Gone()
        meta = {"merge": project.uid, "audio": row.uid, "kind": row.kind}
        if row.kind == VOICE:
            meta["chars"] = len(row.text)
        else:
            meta["seconds"] = row.seconds
        charged, _partial = services.charge(user, row.credits_reserved, meta,
                                            reason=REASON_VOICE if row.kind == VOICE else REASON_MUSIC)
        # Один голос и одна музыка: прежняя дорожка уходит со своим файлом (сигнал после коммита).
        _remove(list(MergeAudio.objects.filter(project_id=project.pk, kind=row.kind).exclude(pk=row.pk)))
        MergeAudio.objects.filter(pk=row.pk).update(
            status=READY, file=path, duration_s=round(float(duration), 2), credits_charged=charged,
            credits_reserved=0, error="", error_code="", updated_at=now,
            expires_at=now + timedelta(days=AUDIO_RETENTION_DAYS))
        MergeProject.objects.filter(pk=project.pk).update(updated_at=now)
    return charged


def _journal(row: MergeAudio, user):
    from ai import genlog

    return genlog.start(user=user, kind=row.kind, source="studio", provider="elevenlabs",
                        model=row.voice_id or ("music_v1" if row.kind == MUSIC else row.kind),
                        prompt=row.text or row.prompt, credits_planned=row.credits_reserved,
                        params={"merge": row.project.uid, "audio": row.uid, "seconds": row.seconds,
                                "chars": len(row.text)})


def _produce(user, make) -> tuple[str, float]:
    """Вызов провайдера и mp3 в хранилище: (путь, секунды). Бросает исключение провайдера."""
    raw = make()
    _ensure_folder(user.pk)
    return studio.save_audio(raw, ".mp3", folder=folder(user.pk))


def _generate(row: MergeAudio, user, make) -> tuple[int, str]:
    """Сделать заказанный звук и списать за него: (списано, путь). Бросает MergeError."""
    entry = _journal(row, user)
    try:
        path, duration = _produce(user, make)
    except Exception as exc:
        code, message, status = _failure(exc)
        entry.failed(str(exc)[:500])
        logger.warning("склейка: звук %s (%s) не получился: %s", row.uid, row.kind, str(exc)[:300])
        _release(row.pk, code, message)
        raise MergeError(code, message, status) from None
    try:
        charged = _deliver(row.pk, user.pk, path=path, duration=duration)
    except _Gone:
        delete_files(path)
        # Звук провайдер сделал и деньги за него взял, а человек не получил.
        entry.lost("склейку удалили или заказ закрыт, пока делался звук")
        raise services._not_found() from None
    except BaseException:
        # Списание откатилось (мягкий лимит задачи, сбой базы) — файл ничей.
        delete_files(path)
        raise
    entry.delivered(credits=charged, result_url=media_url(path))
    return charged, path


# ---------------------------------------------------------------- голос

def _voice_name(voice_id: str) -> str:
    # Справочник голосов — украшение подписи: его сбой не мешает озвучке (как в мультстудии).
    try:
        return next((str(v.get("name") or "")[:120] for v in (studio.list_voices() or [])
                     if v.get("id") == voice_id), "")
    except Exception:
        logger.warning("склейка: справочник голосов недоступен, голос без названия")
        return ""


def generate_voice(user, uid, data) -> tuple[MergeAudio | dict, bool]:
    """POST <id>/audio/voice/: (дорожка, сделана ли сейчас). Бросает MergeError.
    Повтор ключа, чья дорожка уже ушла, — снимок той дорожки (dict, см. _remove)."""
    data = data if isinstance(data, dict) else {}
    project = services.get_project(user, uid)
    refusal = edit_refusal(project)
    if refusal:
        raise refusal
    _check_configured()
    text = " ".join(str(data.get("text") or "").split())
    if not text:
        raise _bad("text", MSG_NO_TEXT)
    if len(text) > VOICE_MAX_CHARS:
        raise MergeError("voice_too_long", MSG_TEXT_TOO_LONG.format(max=VOICE_MAX_CHARS), max=VOICE_MAX_CHARS)
    voice_id = str(data.get("voice_id") or "").strip()[:64]
    if not studio.valid_voice_id(voice_id):
        raise _bad("voice_id", MSG_NO_VOICE)
    start = _fragment_index(data.get("start_fragment"))
    price = studio.voice_price(text)
    voice_name = _voice_name(voice_id)

    def prepare(locked: MergeProject):
        count = len([i for i in locked.items or [] if isinstance(i, dict)])
        if start is None or start >= max(1, count):
            raise _bad("start_fragment", MSG_BAD_FRAGMENT)
        return dict(source=MergeAudio.SOURCE_GENERATED, text=text, voice_id=voice_id,
                    voice_name=voice_name, start_fragment=start), price

    project, row, created = _reserve(user, uid, VOICE, prepare, request_id=_request_id(data.get("request_id")),
                                     data=data)
    if not created:
        return row, False
    _generate(row, user, lambda: studio.tts(text, voice_id))
    row.refresh_from_db()
    return row, True


# ---------------------------------------------------------------- музыка

def _slot_keys(count: int) -> list[str]:
    return [f"{MUSIC_SLOT_PREFIX}:{n}" for n in range(count)]


def take_music_slot(token: str) -> str | None:
    """Занять свободное место музыки (cache.add — атомарно): ключ места; "" — кэш
    недоступен (заказ идёт без учёта, как загрузки); None — все места заняты."""
    try:
        for key in _slot_keys(music_concurrency()):
            if cache.add(key, token, MUSIC_SLOT_TTL):
                return key
    except Exception:
        logger.warning("склейка: место музыки не проверилось", exc_info=True)
        return ""
    return None


def _hold_music_slot(token: str) -> str | None:
    """Задача взяла заказ: продлить его место на весь свой срок. Место истекло, пока
    задача стояла в очереди, — занять свободное; свободных нет — None. Ищем по всем
    номерам: предел могли уменьшить, пока заказ ждал."""
    try:
        for key, value in cache.get_many(_slot_keys(MUSIC_CONCURRENCY_MAX)).items():
            if value == token and cache.touch(key, MUSIC_SLOT_TTL):
                return key
    except Exception:
        logger.warning("склейка: место музыки не продлилось", exc_info=True)
        return ""
    return take_music_slot(token)


def release_music_slot(key: str, token: str) -> None:
    """Отпустить своё место. Чужое (срок вышел, и место занял другой заказ) не трогаем."""
    if not key:
        return
    try:
        if cache.get(key) == token:
            cache.delete(key)
    except Exception:
        logger.warning("склейка: место музыки не освободилось", exc_info=True)


def drop_music_slot(token: str) -> None:
    """Заказ удалили, пока он стоял в очереди (удалили склейку): его место свободно сразу,
    а не через срок ключа."""
    try:
        for key, value in cache.get_many(_slot_keys(MUSIC_CONCURRENCY_MAX)).items():
            if value == token:
                cache.delete(key)
    except Exception:
        logger.warning("склейка: место музыки не освободилось", exc_info=True)


def queue_music(user, uid, data) -> tuple[MergeAudio | dict, bool]:
    """POST <id>/audio/music/: заказ встаёт в резерв, музыку делает задача make_music.

    Сначала место музыки на весь сайт — мест нет, и music_busy до всякого резерва;
    место держит заказ (uid строки), пока задача его не закончит."""
    data = data if isinstance(data, dict) else {}
    project = services.get_project(user, uid)
    refusal = edit_refusal(project)
    if refusal:
        raise refusal
    _check_configured()
    prompt = " ".join(str(data.get("prompt") or "").split())
    if len(prompt) < MUSIC_PROMPT_MIN:
        raise _bad("prompt", MSG_NO_PROMPT)
    if len(prompt) > MUSIC_PROMPT_MAX:
        raise _bad("prompt", MSG_PROMPT_TOO_LONG.format(max=MUSIC_PROMPT_MAX), max=MUSIC_PROMPT_MAX)
    request_id = _request_id(data.get("request_id"))
    if request_id:
        # Повтор того же нажатия отвечает той же дорожкой — и когда мест нет.
        same = MergeAudio.objects.filter(project=project, kind=MUSIC, request_id=request_id).first()
        if same is not None:
            return same, False
        gone = _replayed(project, MUSIC, request_id)
        if gone is not None:
            return gone, False
    if _music_busy(project):
        raise MergeError("audio_busy", MSG_BUSY, 409)
    token = uuid.uuid4().hex
    slot = take_music_slot(token)
    if slot is None:
        raise MergeError("music_busy", MSG_MUSIC_BUSY, 429)

    def prepare(locked: MergeProject):
        seconds = music_seconds(services.total_duration(locked.items))
        if not seconds:
            raise MergeError("audio_no_fragments", MSG_NO_FRAGMENTS)
        fields = dict(uid=token, source=MergeAudio.SOURCE_GENERATED, prompt=prompt, seconds=float(seconds))
        return fields, studio.music_price(seconds)

    try:
        project, row, created = _reserve(user, uid, MUSIC, prepare, request_id=request_id, data=data)
    except BaseException:
        release_music_slot(slot, token)
        raise
    if not created:
        release_music_slot(slot, token)
        return row, False
    transaction.on_commit(lambda pk=row.pk: _enqueue_music(pk, slot, token))
    return row, True


def _enqueue_music(pk: int, slot: str = "", token: str = "") -> None:
    """Поставить задачу после коммита. Брокер недоступен — заказ закрывается сразу
    (резерв снят, место свободно), а не висит до уборки."""
    from .tasks import make_music

    queue = getattr(settings, "CELERY_MEDIA_QUEUE", "") or ""
    try:
        # Очередь media, как у музыки мультстудии: провайдер делает её минутами.
        make_music.apply_async((pk,), **({"queue": queue} if queue else {}))
    except Exception:
        logger.exception("склейка: задача музыки %s не поставилась", pk)
        _release(pk, "audio_queue_down", MSG_QUEUE_DOWN)
        release_music_slot(slot, token)


def run_music(pk: int) -> dict:
    """Тело задачи make_music. Ошибки не роняют задачу, а пишутся в дорожку."""
    from celery.exceptions import SoftTimeLimitExceeded

    now = timezone.now()
    # Работу забирает одна копия задачи: вторая провайдера не зовёт (он берёт деньги)
    # и место заказа не трогает.
    if not MergeAudio.objects.filter(pk=pk, status=PENDING, kind=MUSIC,
                                     started_at__isnull=True).update(started_at=now, updated_at=now):
        return {"status": "not_pending"}
    row = MergeAudio.objects.select_related("project__user").filter(pk=pk).first()
    if row is None:
        return {"status": "gone"}
    slot = _hold_music_slot(row.uid)
    if slot is None:
        # Место заказа истекло в очереди, и все места заняли другие: провайдера не
        # зовём, заказ закрыт и резерв снят тем же UPDATE — списания не было.
        _release(pk, "music_busy", MSG_MUSIC_BUSY)
        return {"status": "failed", "error_code": "music_busy"}
    user = row.project.user
    try:
        charged, _path = _generate(row, user,
                                   lambda: studio.music(row.prompt, float(row.seconds or 0), instrumental=True,
                                                        timeout=MUSIC_READ_TIMEOUT))
    except SoftTimeLimitExceeded:
        _release(pk, "audio_failed", MSG_FAILED)
        return {"status": "timeout"}
    except MergeError as exc:
        return {"status": "gone" if exc.code == "project_not_found" else "failed", "error_code": exc.code}
    finally:
        release_music_slot(slot, row.uid)
    return {"status": "ready", "charged": charged}


# ---------------------------------------------------------------- свой трек

def sniff(head: bytes) -> str:
    """Демуксер ffmpeg для трека по первым байтам или "" (не звук, плейлист, мусор)."""
    head = bytes(head or b"")
    if head[:3] == b"ID3":
        return "mp3"
    if len(head) >= 2 and head[0] == 0xFF and head[1] & 0xE0 == 0xE0:
        # Синхрослово MPEG: слой 00 — это AAC в ADTS, остальное — mp3.
        return "aac" if head[1] & 0x06 == 0 else "mp3"
    if len(head) >= 12 and head[4:8] == b"ftyp":
        return "" if head[8:12] in _NOT_AUDIO_BRANDS else "mov"
    if head[:4] == b"RIFF" and head[8:12] == b"WAVE":
        return "wav"
    if head[:4] == b"OggS":
        return "ogg"
    if head[:4] == b"\x1a\x45\xdf\xa3":
        return "matroska"
    if head[:4] == b"fLaC":
        return "flac"
    if head[:4] == b"FORM" and head[8:12] in (b"AIFF", b"AIFC"):
        return "aiff"
    if head[:4] == b"caff":
        return "caf"
    if head[:8] == _ASF:
        return "asf"
    if head[:5] == b"#!AMR":
        return "amr"
    return ""


def verdict(info) -> MergeError | None:
    """Подходит ли разобранный трек. None — подходит."""
    if info is None:
        return MergeError("audio_unreadable", MSG_UNREADABLE)
    if not info.audio:
        return MergeError("audio_no_sound", MSG_NO_SOUND)
    if not info.duration:
        return MergeError("audio_unreadable", MSG_UNREADABLE)
    if info.duration > AUDIO_UPLOAD_MAX_S + AUDIO_UPLOAD_TOLERANCE_S:
        return MergeError("audio_too_long", MSG_TOO_LONG, max_s=AUDIO_UPLOAD_MAX_S,
                          duration_s=round(info.duration, 1))
    # Частота и каналы из заголовков: пересборке они обходятся как секунды × частота ×
    # каналы, а потолок длины считает только секунды.
    if (info.sample_rate or 0) > AUDIO_UPLOAD_MAX_RATE or (info.channels or 0) > AUDIO_UPLOAD_MAX_CHANNELS:
        return MergeError("audio_unsupported", MSG_UNSUPPORTED, max_channels=AUDIO_UPLOAD_MAX_CHANNELS,
                          max_sample_rate=AUDIO_UPLOAD_MAX_RATE, channels=info.channels,
                          sample_rate=info.sample_rate)
    return None


def too_big() -> MergeError:
    return MergeError("audio_too_big", MSG_TOO_BIG, max_mb=AUDIO_UPLOAD_MAX_BYTES // MB)


def precheck(content_length) -> None:
    """До разбора тела: заявленный размер. Бросает MergeError."""
    try:
        declared = int(content_length or 0)
    except (TypeError, ValueError):
        declared = 0
    if declared > AUDIO_UPLOAD_MAX_BYTES + UPLOAD_SLACK:
        raise too_big()


def _music_busy(project) -> bool:
    return MergeAudio.objects.filter(project=project, kind=MUSIC, status=PENDING).exists()


def upload_music(user, uid, fileobj) -> MergeAudio:
    """POST <id>/audio/music/upload/: свой трек вместо музыки склейки. Бесплатно.

    Дешёвое — сначала: склейку можно менять → размер → расширение из списка
    мультстудии → первые байты (демуксер) → место на диске; потом файл ложится
    во временную папку под нашим именем и разбирается строго (render.probe_audio:
    протокол file, заданный демуксер, декодеры из списка) → save_audio
    мультстудии пересобирает его в mp3 тем же демуксером и декодерами, не дальше
    потолка длины (-t: длине из заголовка не верим), и ещё раз проверяет длину.
    Строка — под замком, с повторной проверкой состояния; отказ после сохранения
    стирает файл.
    """
    from .uploads import MSG_UNAVAILABLE, _room_for, clean_title

    project = services.get_project(user, uid)
    refusal = edit_refusal(project)
    if refusal:
        raise refusal
    if fileobj is None:
        raise _bad("file", MSG_NO_FILE)
    size = int(getattr(fileobj, "size", 0) or 0)
    if size > AUDIO_UPLOAD_MAX_BYTES:
        raise too_big()
    name = getattr(fileobj, "name", "")
    if not studio.upload_suffix(name):
        raise MergeError("audio_bad_type", MSG_BAD_TYPE, extensions=list(studio.UPLOAD_EXTENSIONS))
    if size <= 0:
        raise MergeError("audio_unreadable", MSG_UNREADABLE)
    try:
        fileobj.seek(0)
        fmt = sniff(fileobj.read(HEAD_BYTES))
        fileobj.seek(0)
    except (OSError, ValueError):
        raise MergeError("audio_unreadable", MSG_UNREADABLE) from None
    if not fmt:
        raise MergeError("audio_bad_type", MSG_BAD_TYPE, extensions=list(studio.UPLOAD_EXTENSIONS))
    if _music_busy(project):
        raise MergeError("audio_busy", MSG_BUSY, 409)
    if not _room_for(size):
        raise MergeError("upload_unavailable", MSG_UNAVAILABLE, 503)
    suffix = FORMAT_SUFFIX[fmt]
    with tempfile.TemporaryDirectory(prefix="merge-audio-") as tmp:
        src = os.path.join(tmp, f"in{suffix}")
        with open(src, "wb") as out:
            for chunk in fileobj.chunks():
                out.write(chunk)
        refusal = verdict(ffmpeg.probe_audio(src, fmt))
        if refusal is not None:
            raise refusal
        with open(src, "rb") as fh:
            raw = fh.read()
    _ensure_folder(user.pk)
    try:
        path, duration = studio.save_audio(raw, suffix, folder=folder(user.pk),
                                           max_seconds=AUDIO_UPLOAD_MAX_S + AUDIO_UPLOAD_TOLERANCE_S,
                                           input_options=ffmpeg.audio_input_args(fmt))
    except studio.AudioTooLong:
        raise MergeError("audio_too_long", MSG_TOO_LONG, max_s=AUDIO_UPLOAD_MAX_S) from None
    except Exception:
        logger.warning("склейка: свой трек не пересобрался", exc_info=True)
        raise MergeError("audio_unreadable", MSG_UNREADABLE) from None
    try:
        with transaction.atomic():
            locked = get_user_model().objects.select_for_update().get(pk=user.pk)
            project = services.get_project(locked, uid, lock=True)
            refusal = edit_refusal(project)
            if refusal:
                raise refusal
            if _music_busy(project):
                raise MergeError("audio_busy", MSG_BUSY, 409)
            # Одна музыка на склейку: прежняя (и прошлая неудача) уходит.
            _remove(list(MergeAudio.objects.filter(project=project, kind=MUSIC)))
            row = MergeAudio.objects.create(project=project, kind=MUSIC, source=MergeAudio.SOURCE_UPLOAD,
                                            status=READY, file=path, duration_s=round(float(duration), 2),
                                            title=clean_title(name))
            _touch(project)
    except BaseException:
        delete_files(path)
        raise
    return row


# ---------------------------------------------------------------- правка

def _volume(raw, top: float, field: str, message: str) -> float:
    if isinstance(raw, bool) or not isinstance(raw, (int, float)):
        raise _bad(field, message)
    value = float(raw)
    if not math.isfinite(value) or not 0 <= value <= top:
        raise _bad(field, message)
    return round(value, 3)


def update_settings(user, uid, data) -> MergeProject:
    """PATCH <id>/audio/: звук роликов, громкости, фрагмент голоса. Всё или ничего."""
    if not isinstance(data, dict):
        raise MergeError("bad_request", MSG_BAD_BODY)
    fields: dict = {}
    if "clip_sound" in data:
        if data["clip_sound"] not in CLIP_SOUNDS:
            raise _bad("clip_sound", MSG_BAD_CLIP)
        fields["clip_sound"] = data["clip_sound"]
    if "music_volume" in data:
        fields["music_volume"] = _volume(data["music_volume"], MUSIC_VOLUME_MAX, "music_volume",
                                         MSG_BAD_MUSIC_VOLUME)
    if "voice_volume" in data:
        fields["voice_volume"] = _volume(data["voice_volume"], VOICE_VOLUME_MAX, "voice_volume",
                                         MSG_BAD_VOICE_VOLUME)
    start = None
    if "voice_start_fragment" in data:
        start = _fragment_index(data["voice_start_fragment"])
        if start is None or data["voice_start_fragment"] is None:
            raise _bad("voice_start_fragment", MSG_BAD_FRAGMENT)
    with transaction.atomic():
        # LOCK_ORDER, как у доставки голоса (_deliver): пользователь, склейка, дорожки — последними
        # (UPDATE ниже). Иначе PATCH, пришедший в момент доставки, мог запереть её, а она — его.
        locked = get_user_model().objects.select_for_update().get(pk=user.pk)
        project = services.get_project(locked, uid, lock=True)
        if not fields and start is None:
            return project
        refusal = edit_refusal(project)
        if refusal:
            raise refusal
        if start is not None:
            count = len([i for i in project.items or [] if isinstance(i, dict)])
            if start >= max(1, count):
                raise _bad("voice_start_fragment", MSG_BAD_FRAGMENT)
            moved = (MergeAudio.objects.filter(project=project, kind=VOICE).exclude(status=FAILED)
                     .update(start_fragment=start))
            if not moved:
                raise _bad("voice_start_fragment", MSG_NO_VOICE_TRACK)
        for name, value in fields.items():
            setattr(project, name, value)
        project.save(update_fields=[*fields, *_to_draft(project), "updated_at"])
    return project


def delete_track(user, uid, track_uid) -> MergeProject:
    """DELETE <id>/audio/<track>/: убрать дорожку (файл стирает сигнал после коммита)."""
    track_uid = str(track_uid or "").strip().lower()
    with transaction.atomic():
        project = services.get_project(user, uid, lock=True)
        refusal = edit_refusal(project)
        if refusal:
            raise refusal
        row = MergeAudio.objects.filter(project=project, uid=track_uid).first()
        if row is None:
            raise MergeError("audio_not_found", MSG_TRACK_NOT_FOUND, 404)
        if row.status == PENDING:
            raise MergeError("audio_busy", MSG_BUSY, 409)
        was_ready = row.status == READY
        _remove([row])
        if was_ready:
            _touch(project)
    return project


# ---------------------------------------------------------------- копия, склейка, уборка

def _copy_file(name: str, user_id) -> str:
    """Своя копия файла дорожки для новой склейки ("" — файла уже нет).

    Копия, а не общий файл: удаление и срок хранения каждой склейки касаются
    только её файлов — без счётчика ссылок и без риска стереть чужой звук.
    """
    _ensure_folder(user_id)
    try:
        with default_storage.open(name, "rb") as fh:
            return default_storage.save(f"{folder(user_id)}/{uuid.uuid4().hex}.mp3",
                                        File(fh, name="audio.mp3"))
    except (FileNotFoundError, OSError):
        logger.warning("склейка: файл дорожки %s не скопировался", name, exc_info=True)
        return ""


def _refs(project: MergeProject) -> list[tuple]:
    return [(i.get("type"), str(i.get("id"))) for i in project.items or [] if isinstance(i, dict)]


def _same_fragment(source: MergeProject, target: MergeProject, index: int) -> int | None:
    """Номер в новой склейке того же ролика, что стоял фрагментом index в старой; None — его там нет.

    Голос пишут под конкретный ролик: убрали пропавшие фрагменты перед ним —
    голос едет за своим роликом, а не остаётся под прежним номером. Один ролик
    бывает в склейке дважды — берём то же его появление по счёту.
    """
    old, new = _refs(source), _refs(target)
    if not old:
        return None
    at = min(max(0, int(index or 0)), len(old) - 1)
    ref, nth = old[at], old[:at].count(old[at])
    found = [i for i, item in enumerate(new) if item == ref]
    return found[min(nth, len(found) - 1)] if found else None


def copy_audio(source: MergeProject, target: MergeProject) -> int:
    """«Изменить и склеить заново»: звук старой склейки — в новую. Сколько дорожек скопировано.

    Готовые дорожки копируются с файлами и бесплатно (за них уже заплачено);
    голос остаётся у своего ролика (_same_fragment), а ролика больше нет — под
    прежним номером (за концом списка — последний).
    """
    target.clip_sound = source.clip_sound
    target.music_volume = source.music_volume
    target.voice_volume = source.voice_volume
    target.save(update_fields=["clip_sound", "music_volume", "voice_volume", "updated_at"])
    last = max(0, len([i for i in target.items or [] if isinstance(i, dict)]) - 1)
    made: list[str] = []
    try:
        for row in (MergeAudio.objects.filter(project=source, status=READY).exclude(file="")
                    .order_by("kind")):
            name = _copy_file(row.file, target.user_id)
            if not name:
                continue
            made.append(name)
            same = _same_fragment(source, target, row.start_fragment) if row.kind == VOICE else None
            MergeAudio.objects.create(
                project=target, kind=row.kind, source=row.source, status=READY, file=name,
                duration_s=row.duration_s, text=row.text, prompt=row.prompt, title=row.title,
                voice_id=row.voice_id, voice_name=row.voice_name,
                start_fragment=min(row.start_fragment, last) if same is None else same, seconds=row.seconds)
    except BaseException:
        delete_files(*made)
        raise
    return len(made)


def pending(project_id) -> bool:
    return MergeAudio.objects.filter(project_id=project_id, status=PENDING).exists()


def hold(project_id, until) -> int:
    """Продлить хранение звука склейки до until (сроки только растут)."""
    return MergeAudio.objects.filter(project_id=project_id, status=READY,
                                     expires_at__lt=until).update(expires_at=until)


def reserved(user_id) -> int:
    """Кредиты в резерве у звука, который делается (для merge.services.reserved_credits)."""
    total = MergeAudio.objects.filter(project__user_id=user_id, status=PENDING).aggregate(
        s=Sum("credits_reserved"))["s"]
    return max(0, int(total or 0))


def drop(project_id) -> int:
    """Стереть звук склейки (срок хранения её ролика вышел): строки и файлы."""
    deleted, _ = MergeAudio.objects.filter(project_id=project_id).exclude(status=PENDING).delete()
    return deleted


def fail_stale(now=None, *, project_id=None) -> int:
    """Закрыть заказы звука, чья работа потерялась: резерв снимает тот же UPDATE.
    project_id — только заказы этой склейки (перед её удалением)."""
    now = now or timezone.now()
    fields = dict(status=FAILED, credits_reserved=0, error=MSG_STALE, error_code="audio_stale",
                  updated_at=now)
    base = MergeAudio.objects.filter(status=PENDING)
    if project_id is not None:
        base = base.filter(project_id=project_id)
    count = base.filter(kind=VOICE, created_at__lt=now - VOICE_STALE_AFTER).update(**fields)
    count += base.filter(kind=MUSIC, started_at__isnull=True,
                         created_at__lt=now - MUSIC_QUEUE_TIMEOUT).update(**fields)
    count += base.filter(kind=MUSIC, started_at__lt=now - MUSIC_STALE_AFTER).update(**fields)
    if count:
        logger.warning("склейка: закрыто оборвавшихся заказов звука %s", count)
    return count


def purge(now=None, *, batch: int = PURGE_BATCH) -> int:
    """Стереть звук, срок которого вышел (30 дней; склейка продлевает до своего), кроме
    звука склеек в очереди и в работе."""
    now = now or timezone.now()
    qs = (MergeAudio.objects.filter(expires_at__lt=now).exclude(status=PENDING)
          .exclude(project__status__in=ACTIVE))
    count = last = 0
    for _ in range(PURGE_MAX_BATCHES):
        rows = list(qs.filter(pk__gt=last).order_by("pk").only("pk", "expires_at")[:batch])
        for row in rows:
            last = row.pk
            # Условно по сроку: склейку могли запустить, и она продлила звук.
            deleted, _ = (MergeAudio.objects.filter(pk=row.pk, expires_at=row.expires_at)
                          .exclude(project__status__in=ACTIVE).delete())
            count += 1 if deleted else 0
        if len(rows) < batch:
            break
    # Ключи ушедших заказов нужны только повтору того же нажатия — столько же, сколько звук.
    MergeAudioRequest.objects.filter(created_at__lt=now - timedelta(days=AUDIO_RETENTION_DAYS)).delete()
    if count:
        logger.info("склейка: стёрто дорожек звука %s", count)
    return count


def _local(row: MergeAudio, workdir: str) -> str:
    path = local_path(row.file)
    if path:
        return path
    target = os.path.join(workdir, f"{row.kind}.mp3")
    try:
        with default_storage.open(row.file, "rb") as src, open(target, "wb") as dst:
            for chunk in iter(lambda: src.read(1024 * 1024), b""):
                dst.write(chunk)
    except Exception:
        raise ffmpeg.RenderError(MSG_MISSING, f"нет файла дорожки {row.file}", code="audio_missing") from None
    return target


def mix_for(project: MergeProject, workdir: str, expected_s: float = 0.0) -> ffmpeg.AudioMix | None:
    """Звук для склейки или None — звука нет и звук роликов как есть (прежняя склейка)."""
    rows = {r.kind: r for r in MergeAudio.objects.filter(project_id=project.pk, status=READY)
            .exclude(file="")}
    clip, music_volume, voice_volume = audio_volumes(project.clip_sound, project.music_volume,
                                                     project.voice_volume)
    if not rows and clip == 1.0:
        return None
    voice, music = rows.get(VOICE), rows.get(MUSIC)
    return ffmpeg.AudioMix(
        clip_volume=clip,
        voice=_local(voice, workdir) if voice else "", voice_volume=voice_volume,
        voice_duration=float(voice.duration_s or 0) if voice else 0.0,
        voice_fragment=int(voice.start_fragment) if voice else 0,
        music=_local(music, workdir) if music else "", music_volume=music_volume,
        expected_s=float(expected_s or 0))


__all__ = ["state", "summary", "track_json", "limits", "music_seconds", "edit_refusal",
           "generate_voice", "queue_music", "run_music", "upload_music", "update_settings",
           "delete_track", "copy_audio", "pending", "hold", "reserved", "drop", "fail_stale", "purge",
           "mix_for", "sniff", "verdict", "precheck", "REASON_VOICE", "REASON_MUSIC"]
