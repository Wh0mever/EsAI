"""Конвейер Creative Studio: машина состояний задачи и короткие шаги (SPEC_B §5).

Каждая функция — тело одной Celery-задачи (creative.tasks), слот воркера
держится не дольше одного сетевого шага:

    submit(job)    queued→submitting → журнал → файлы к поставщику → POST → running
    poll(job)      один GET статуса → перезапуск через countdown | saving | failed | nsfw
    finalize(job)  статус ещё раз → скачать результат к себе → done+charged одной транзакцией
    cancel(job)    отмена человеком: из нашей очереди или из очереди поставщика
    sweep()        страховка раз в минуту: потерянные цепочки, зависшие шаги, аренда выдачи
    purge_uploads() старые загрузки без открытых задач

Правила (как у видеостудии):
- каждый переход — условный UPDATE (CreativeJob.objects.transition); ноль строк —
  работу сделал другой (вторая копия задачи, вебхук, sweep, отмена), выходим;
- Idempotency-Key создаётся и пишется в задачу вместе с телом ДО отправки;
  таймаут, 5xx и 429 — повтор с тем же ключом и тем же телом (поставщик вернёт
  ту же задачу и второй раз не возьмёт денег);
- обучение персонажа идемпотентности не имеет: неизвестный исход — lost и разбор;
- деньги: списание только в транзакции выдачи; failed | nsfw | canceled | lost
  снимают резерв тем же UPDATE, что закрывает задачу;
- журнал генераций (source=creative, provider="cs") создаётся перед первым
  обращением к поставщику; не создался — поставщику ничего не уходит;
- в журнал и в ошибки человеку — только наши коды и тексты: ответы поставщика
  (там может быть его имя) — в лог.
"""
from __future__ import annotations

import logging
import math
import os
import subprocess
import tempfile
import uuid
from datetime import timedelta
from io import BytesIO
from typing import Optional

from django.conf import settings
from django.core.cache import cache
from django.core.files import File
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.db import transaction
from django.db.models import F, Q
from django.utils import timezone

from ai import genlog
from ai.models import GenerationLog

from . import hf, registry
from .models import (
    CHARGE_CHARGED, CHARGE_RESERVED, JOB_CANCELED, JOB_DONE, JOB_FAILED, JOB_LOST, JOB_NSFW,
    JOB_OPEN, JOB_QUEUED, JOB_RUNNING, JOB_SAVING, JOB_SUBMITTING, KIND_CHARACTER, KIND_VIDEO,
    CreativeCharacter, CreativeJob, CreativeUpload,
)
from .storage import delete_files, ensure_dir, results_dir, storage_ready

logger = logging.getLogger(__name__)

PROVIDER_CODE = "cs"

# --- Опрос
FIRST_POLL_S = {"image": 8, "video": 15, "character": 30}
POLL_CLAIM = timedelta(seconds=90)
POLL_STEPS = {"image": ((120, 5), (600, 10)), "video": ((180, 10), (900, 20)),
              "character": ((1800, 20),)}
POLL_STEP_LATE = 60
POLL_NOT_FOUND_MAX = 10
POLL_ERROR_STEP = 30
GIVE_UP = {"image": timedelta(hours=2), "video": timedelta(hours=6), "character": timedelta(hours=6)}

# --- Отправка
SUBMIT_MAX_ATTEMPTS = 6
SUBMIT_RETRY_BASE_S = 15
SUBMIT_RETRY_MAX_S = 300
SLOT_WAIT_S = 15
PROVIDER_URL_TTL = timedelta(hours=6)

# --- Выдача
LEASE = timedelta(minutes=6)
MAX_SAVE_ATTEMPTS = 5
RETRY_BASE_S = 60
IMAGE_MAX_BYTES = 60 * 1024 * 1024
VIDEO_MAX_BYTES = 500 * 1024 * 1024
DOWNLOAD_WALL_S = 240
PROBE_MAX_BYTES = 64 * 1024 * 1024
THUMB_BOX = 480
POSTER_BOX = 720
STRIP_TIMEOUT_S = 120

# --- Страховка
QUEUED_REQUEUE_AFTER = timedelta(minutes=2)
QUEUED_TIMEOUT = timedelta(minutes=30)
SUBMITTING_STALE = timedelta(minutes=10)
POLL_STALE = timedelta(seconds=60)
SWEEP_LOCK_KEY = "creative:sweep"
SWEEP_LOCK_TTL = 55
SWEEP_BATCH = 200
REQUEUE_DEDUP_S = 110

# --- Загрузки
UPLOAD_KEEP_DAYS_DEFAULT = 7
PURGE_BATCH = 500

# Тексты человеку — нейтральные, по коду переводит фронт (namespace creative).
ERRORS = {
    "provider_failed": "Генерация не получилась. Кредиты не списаны — попробуйте ещё раз.",
    "nsfw": "Запрос отклонила модерация. Кредиты не списаны.",
    "provider_unavailable": "Генерация временно недоступна. Кредиты не списаны — попробуйте позже.",
    "bad_params": "Не удалось запустить генерацию с этими параметрами. Кредиты не списаны.",
    "queue_timeout": "Генерация слишком долго ждала очереди. Кредиты не списаны — попробуйте ещё раз.",
    "submit_unknown": "Не удалось подтвердить запуск — кредиты не списаны, мы проверим вручную.",
    "provider_timeout": "Генерация так и не вернула результат. Кредиты не списаны, мы проверим вручную.",
    "provider_unreachable": "Не удалось забрать результат. Кредиты не списаны, мы проверим вручную.",
    "save_failed": "Не удалось сохранить результат. Кредиты не списаны, мы проверим вручную.",
    "journal_unavailable": "Не удалось запустить генерацию. Кредиты не списаны — попробуйте ещё раз.",
    "storage_unavailable": "Сохранение временно недоступно. Кредиты не списаны — попробуйте позже.",
    "upload_failed": "Не удалось передать файлы в генерацию. Кредиты не списаны — попробуйте ещё раз.",
    "canceled": "Отменено. Кредиты не списаны.",
    "internal_error": "Не удалось запустить генерацию. Кредиты не списаны — попробуйте ещё раз.",
}


# ---------------------------------------------------------------- постановка задач

def _enqueue(task_name: str, job_id: int, *, countdown: Optional[float] = None) -> bool:
    """Поставить creative.tasks.<task_name>. Сбой брокера не роняет вызывающего — подберёт sweep."""
    try:
        from . import tasks

        options = {"countdown": countdown} if countdown else {}
        getattr(tasks, task_name).apply_async(args=[job_id], **options)
        return True
    except Exception:
        logger.exception("creative: задача %s не поставилась job_id=%s", task_name, job_id)
        return False


def enqueue_start(job) -> None:
    """Первый шаг задачи. Вьюха зовёт через transaction.on_commit."""
    _enqueue("submit_job", job.pk)


def _once(key: str, ttl: int) -> bool:
    try:
        return bool(cache.add(key, 1, ttl))
    except Exception:
        return True


def max_parallel() -> int:
    try:
        return max(1, int(getattr(settings, "CREATIVE_MAX_PARALLEL", 4) or 4))
    except (TypeError, ValueError):
        return 4


def hook_url() -> str:
    """Адрес вебхука — только если секрет задан (без секрета эндпоинт отвечает 404)."""
    if not str(getattr(settings, "HF_WEBHOOK_SECRET", "") or "").strip():
        return ""
    base = str(getattr(settings, "SITE_BASE_URL", "") or "").rstrip("/")
    if not base.startswith("https://"):
        return ""
    return f"{base}/api/creative/hook/"


# ---------------------------------------------------------------- помощники

def _load(job_id) -> Optional[CreativeJob]:
    return CreativeJob.objects.select_related("user").filter(pk=job_id).first()


def _journal_kind(job) -> str:
    return GenerationLog.KIND_VIDEO if job.kind == KIND_VIDEO else GenerationLog.KIND_IMAGE


def _start_journal(job):
    params = job.params if isinstance(job.params, dict) else {}
    prompt = str(params.get("prompt") or params.get("brief") or params.get("name") or "")
    return genlog.start(user=job.user, kind=_journal_kind(job), source="creative",
                        provider=PROVIDER_CODE, model=f"creative/{job.tool_slug}", prompt=prompt,
                        credits_planned=job.credits_reserved,
                        params={"job": job.uid, "tool": job.tool_slug})


def _journal_close(genlog_id, status: str, *, error: str = "", review: bool = False) -> None:
    from vstudio.delivery import journal_close

    journal_close(genlog_id, status, error=error, review=review)


def _journal_stage(genlog_id, stage: str, note: str = "") -> None:
    from vstudio.delivery import journal_stage

    journal_stage(genlog_id, stage, note)


def notify_later(job_id) -> None:
    try:
        from . import notify

        if notify.wanted(job_id):
            _enqueue("notify_job", job_id)
    except Exception:
        logger.warning("creative: уведомление не поставилось job_id=%s", job_id, exc_info=True)


def _close(job, frm, to: str, code: str, *, qs=None, journal: Optional[str] = None,
           journal_error: str = "", review: bool = False, **fields) -> bool:
    """Закрыть задачу failed | nsfw | canceled | lost (резерв снимается тем же UPDATE)."""
    qs = CreativeJob.objects if qs is None else qs
    if review or to == JOB_LOST:
        fields["needs_review"] = True
    moved = qs.transition(job.pk, frm, to, error=ERRORS.get(code, ERRORS["internal_error"]),
                          error_code=str(code or "")[:40], next_poll_at=None, lease_until=None,
                          **fields)
    if not moved:
        return False
    log = logger.warning if to == JOB_LOST else logger.info
    log("creative job=%s %s→%s code=%s", job.uid, "|".join((frm,) if isinstance(frm, str) else frm),
        to, code)
    if job.kind == KIND_CHARACTER:
        CreativeCharacter.objects.filter(job_id=job.pk, status=CreativeCharacter.STATUS_TRAINING).update(
            status=CreativeCharacter.STATUS_FAILED, updated_at=timezone.now())
    if journal and job.genlog_id:
        _journal_close(job.genlog_id, journal, error=journal_error or code, review=review)
    if to != JOB_CANCELED:
        notify_later(job.pk)
    return True


def _provider_refused(job, frm: str, exc: hf.HFError, *, lost: bool = False) -> None:
    """Поставщик отказал из-за денег или ключа: задача закрыта, резерв снят, сотрудникам — сигнал.

    lost — прошлая попытка могла дойти до поставщика (исход неизвестен): закрываем
    lost с разбором, а не failed — иначе его работу никто не сверит.
    """
    from . import notify
    from .reserve import mark_provider_down

    mark_provider_down()
    code = "provider_key" if exc.status == 401 or "key_" in exc.detail else "provider_unavailable"
    notify.staff_alert(code, note=f"http {exc.status}")
    if lost:
        _close(job, frm, JOB_LOST, "submit_unknown", journal=GenerationLog.STATUS_LOST,
               journal_error=f"повтор отклонён (http {exc.status}), прошлая попытка могла дойти")
        return
    _close(job, frm, JOB_FAILED, "provider_unavailable", journal=GenerationLog.STATUS_FAILED,
           journal_error=f"поставщик отказал: http {exc.status}")


def poll_step(job, now=None) -> int:
    now = now or timezone.now()
    started = job.submitted_at or job.created_at or now
    elapsed = (now - started).total_seconds()
    for limit, step in POLL_STEPS.get(job.kind, POLL_STEPS["image"]):
        if elapsed < limit:
            return step
    return POLL_STEP_LATE


# ---------------------------------------------------------------- submit

def _saved_body(job) -> Optional[dict]:
    """request_body задачи, если тело уже сохранено (значит, могло уходить поставщику)."""
    sent = job.request_body if isinstance(job.request_body, dict) else {}
    return sent if isinstance(sent.get("body"), dict) else None


def _maybe_sent(job) -> bool:
    """Прошлая попытка могла дойти до поставщика (таймаут/5xx после POST, падение в отправке).

    Такую задачу нельзя закрыть «как будто ничего не уходило»: поставщик, возможно,
    уже генерирует и возьмёт деньги. Повтор с тем же ключом безопасен; отмена из
    нашей очереди — нет; конец попыток и таймаут очереди — lost с разбором.
    """
    sent = _saved_body(job)
    return bool(sent and sent.get("maybe_sent"))


def _requeue(job, *, delay: float, stage: str, clear_body: bool = False,
             maybe_sent: bool = False) -> bool:
    """Назад в нашу очередь: повтор отправки позже тем же ключом и тем же телом.

    clear_body — обучение персонажа получило явный отказ «позже» (429): запрос
    не принят, тело можно собрать и отправить заново (идемпотентности там нет,
    поэтому сохранённое тело для обучения означает «исход неизвестен»).
    maybe_sent — попытка могла дойти: отметка ложится рядом с телом и уже не снимается.
    """
    later = timezone.now() + timedelta(seconds=delay)
    extra = {}
    saved = _saved_body(job)
    if clear_body:
        extra = {"request_body": {}}
    elif maybe_sent and saved is not None:
        extra = {"request_body": {**saved, "maybe_sent": True}}
    moved = CreativeJob.objects.transition(job.pk, JOB_SUBMITTING, JOB_QUEUED, next_poll_at=later,
                                           stage=stage[:24], **extra)
    if moved:
        _enqueue("submit_job", job.pk, countdown=delay)
    return moved


def _retry_delay(attempts: int, hint: int = 0) -> int:
    """Пауза перед повтором. Подсказка поставщика (Retry-After) тоже не дольше
    SUBMIT_RETRY_MAX_S: все попытки должны уложиться в QUEUED_TIMEOUT."""
    base = min(SUBMIT_RETRY_MAX_S, SUBMIT_RETRY_BASE_S * 2 ** max(0, attempts - 1))
    return int(min(SUBMIT_RETRY_MAX_S, max(base, hint or 0)))


def _give_up(job, frm, code: str, note: str, *, qs=None) -> str:
    """Отправка так и не удалась (кончились попытки или время).

    Тело ещё не сохранялось — поставщику ничего не уходило: failed, резерв снят.
    Сохранялось — попытка могла дойти: lost с разбором (резерв тоже снят).
    """
    if _saved_body(job) is not None:
        moved = _close(job, frm, JOB_LOST, "submit_unknown", qs=qs, journal=GenerationLog.STATUS_LOST,
                       journal_error=f"{note}; тело уже уходило поставщику")
        return "lost" if moved else "skip"
    moved = _close(job, frm, JOB_FAILED, code, qs=qs, journal=GenerationLog.STATUS_FAILED,
                   journal_error=note)
    return "failed" if moved else "skip"


def _provider_url(upload: CreativeUpload) -> str:
    """Живая ссылка на копию файла у поставщика; нет — загрузить. Бросает hf.HFError."""
    now = timezone.now()
    if upload.provider_url and upload.provider_url_expires_at and upload.provider_url_expires_at > now:
        return upload.provider_url
    path = default_storage.path(upload.path)
    url = hf.upload_file(path, upload.mime or "application/octet-stream")
    CreativeUpload.objects.filter(pk=upload.pk).update(provider_url=url[:2100],
                                                       provider_url_expires_at=now + PROVIDER_URL_TTL)
    return url


def _upload_uids(params: dict) -> list[str]:
    out: list[str] = []
    for name in ("video", "image"):
        if params.get(name):
            out.append(params[name])
    for name in ("images", "product_images", "photos"):
        out.extend(params.get(name) or [])
    return list(dict.fromkeys(out))


def _prepare_body(job, tool: registry.Tool) -> dict:
    """Файлы к поставщику и тело запроса. Бросает hf.HFError, KeyError, ValueError."""
    params = job.params if isinstance(job.params, dict) else {}
    uids = _upload_uids(params)
    rows = {u.uid: u for u in CreativeUpload.objects.filter(user_id=job.user_id, uid__in=uids)}
    missing = [u for u in uids if u not in rows]
    if missing:
        raise KeyError(f"загрузки не найдены: {len(missing)}")
    urls = {uid: _provider_url(rows[uid]) for uid in uids}
    character_id = ""
    if params.get("character"):
        ch = CreativeCharacter.objects.filter(user_id=job.user_id, uid=params["character"],
                                              status=CreativeCharacter.STATUS_READY).first()
        if ch is None or not ch.provider_id:
            raise KeyError("персонаж не готов")
        character_id = ch.provider_id
    ctx = registry.BuildCtx(urls=urls, character_provider_id=character_id,
                            neutral_name=f"esai-{job.uid[:16]}")
    return registry.build_body(tool, params, ctx)


def submit(job_id) -> str:
    now = timezone.now()
    claimed = (CreativeJob.objects.filter(Q(next_poll_at__isnull=True) | Q(next_poll_at__lte=now))
               .transition(job_id, JOB_QUEUED, JOB_SUBMITTING, stage="submitting",
                           attempts=F("attempts") + 1, next_poll_at=None))
    if not claimed:
        return "skip"
    job = _load(job_id)
    if job is None:
        return "skip"
    # Предел попыток и возраста — на каждом захвате: задача, которая падает в
    # отправке мимо HFError (таймаут Celery, неожиданное исключение), иначе вечно
    # ходила бы по кругу sweep → submit и держала резерв.
    if int(job.attempts or 0) > SUBMIT_MAX_ATTEMPTS:
        return _give_up(job, JOB_SUBMITTING, "provider_failed",
                        f"отправка не удалась за {SUBMIT_MAX_ATTEMPTS} попыток")
    if job.created_at and job.created_at < now - QUEUED_TIMEOUT:
        return _give_up(job, JOB_SUBMITTING, "queue_timeout", "очередь дольше 30 минут")
    tool = registry.get(job.tool_slug)
    if tool is None:
        _close(job, JOB_SUBMITTING, JOB_FAILED, "internal_error")
        return "failed"

    # Сколько задач разом у поставщика: остальные ждут у нас. Повтор задачи, которая
    # могла уже дойти, слота не ждёт: тот же ключ нагрузки поставщику не добавит.
    busy = (CreativeJob.objects.filter(status__in=(JOB_SUBMITTING, JOB_RUNNING))
            .exclude(pk=job.pk).count())
    if busy >= max_parallel() and not _maybe_sent(job):
        later = timezone.now() + timedelta(seconds=SLOT_WAIT_S)
        if CreativeJob.objects.transition(job.pk, JOB_SUBMITTING, JOB_QUEUED, next_poll_at=later,
                                          stage="waiting", attempts=F("attempts") - 1):
            _enqueue("submit_job", job.pk, countdown=SLOT_WAIT_S)
        return "waiting"

    if not job.genlog_id:
        entry = _start_journal(job)
        if entry.pk is None:
            logger.error("creative job=%s: журнал недоступен — поставщику не отправляем", job.uid)
            _close(job, JOB_SUBMITTING, JOB_FAILED, "journal_unavailable")
            return "failed"
        if not CreativeJob.objects.transition(job.pk, JOB_SUBMITTING, genlog=entry.pk):
            entry.failed("задача закрыта до отправки")
            return "skip"
        job.genlog_id = entry.pk
    else:
        entry = None

    ok, reason = storage_ready(job.user_id)
    if not ok:
        logger.error("creative job=%s: хранилище недоступно: %s", job.uid, reason)
        _close(job, JOB_SUBMITTING, JOB_FAILED, "storage_unavailable",
               journal=GenerationLog.STATUS_FAILED, journal_error="хранилище недоступно")
        return "failed"

    sent = job.request_body if isinstance(job.request_body, dict) else {}
    body = sent.get("body") if isinstance(sent.get("body"), dict) else None
    hook = str(sent.get("hook") or "")
    key = job.idempotency_key
    if body is None:
        try:
            _journal_stage(job.genlog_id, "uploading")
            body = _prepare_body(job, tool)
        except hf.HFError as exc:
            return _submit_error(job, tool, exc, before_send=True)
        except (KeyError, ValueError) as exc:
            logger.error("creative job=%s: тело не собралось: %s", job.uid, exc)
            _close(job, JOB_SUBMITTING, JOB_FAILED, "upload_failed",
                   journal=GenerationLog.STATUS_FAILED, journal_error="тело запроса не собралось")
            return "failed"
        except Exception as exc:
            # Таймаут Celery посреди загрузки файла, неожиданное исключение: поставщику
            # ещё ничего не уходило — повтор позже (до предела попыток).
            logger.exception("creative job=%s: сбой при подготовке отправки", job.uid)
            return _submit_error(job, tool, hf.HFError("transient",
                                                       detail=f"подготовка: {type(exc).__name__}"),
                                 before_send=True)
        hook = hook_url() if job.kind != KIND_CHARACTER else ""
        key = key or str(uuid.uuid4())
        # Тело и ключ — в задачу ДО отправки: повтор пойдёт тем же ключом и телом.
        if not CreativeJob.objects.transition(job.pk, JOB_SUBMITTING,
                                              request_body={"body": body, "hook": hook},
                                              idempotency_key=key):
            return "skip"
        job.request_body = {"body": body, "hook": hook}
        job.idempotency_key = key
    elif job.kind == KIND_CHARACTER:
        # Тело уже уходило, а идемпотентности у обучения нет: повтор мог бы
        # оплатить второго персонажа. Исход неизвестен — в разбор.
        _close(job, JOB_SUBMITTING, JOB_LOST, "submit_unknown", journal=GenerationLog.STATUS_LOST,
               journal_error="повтор обучения без идемпотентности не отправляем")
        return "lost"

    _journal_stage(job.genlog_id, "sending", f"попытка {job.attempts}")
    try:
        if job.kind == KIND_CHARACTER:
            result = hf.create_character(body)
            request_id = result.id
        else:
            result = hf.submit(tool.model, body, idempotency_key=key, hook_url=hook)
            request_id = result.request_id
    except hf.HFError as exc:
        return _submit_error(job, tool, exc, before_send=False)
    except Exception as exc:
        # Неожиданный сбой во время POST: запрос мог дойти — дальше как с таймаутом.
        logger.exception("creative job=%s: сбой во время отправки", job.uid)
        return _submit_error(job, tool, hf.HFError("transient", detail=f"отправка: {type(exc).__name__}",
                                                   sent=True), before_send=False)

    now = timezone.now()
    logger.info("creative accepted job=%s request=%s", job.uid, request_id)
    moved = CreativeJob.objects.transition(
        job.pk, JOB_SUBMITTING, JOB_RUNNING, provider_request_id=request_id, submitted_at=now,
        next_poll_at=now + timedelta(seconds=FIRST_POLL_S.get(job.kind, 15)), stage="queued",
        poll_errors=0, attempts=0)
    _mark_journal_submitted(job.genlog_id, request_id)
    if job.kind == KIND_CHARACTER:
        CreativeCharacter.objects.filter(job_id=job.pk).update(provider_id=request_id,
                                                               updated_at=now)
    if moved:
        _enqueue("poll_job", job.pk, countdown=FIRST_POLL_S.get(job.kind, 15))
        return "running"
    CreativeJob.objects.filter(pk=job.pk, provider_request_id="").update(
        provider_request_id=request_id, submitted_at=now, needs_review=True, updated_at=now)
    _journal_close(job.genlog_id, GenerationLog.STATUS_LOST,
                   error="поставщик принял работу, но задача уже закрыта", review=True)
    logger.error("creative job=%s: принята поставщиком после закрытия задачи", job.uid)
    return "lost"


def _mark_journal_submitted(genlog_id, request_id: str) -> None:
    if not genlog_id:
        return
    try:
        with transaction.atomic():
            GenerationLog.objects.filter(pk=genlog_id).update(
                status=GenerationLog.STATUS_SUBMITTED, provider_id=str(request_id)[:160],
                updated_at=timezone.now())
    except Exception:
        logger.warning("creative: журнал %s не отмечен submitted", genlog_id, exc_info=True)
    _journal_stage(genlog_id, "submitted", str(request_id)[:64])


def _submit_error(job, tool, exc: hf.HFError, *, before_send: bool) -> str:
    """Отказ или сбой при загрузке файлов / отправке."""
    logger.warning("creative job=%s: отправка: %s %s", job.uid, exc, exc.detail)
    attempts = int(job.attempts or 1)
    # Прошлая попытка могла дойти: явный отказ на ПОВТОРЕ не значит, что поставщик
    # не генерирует по первой. Закрываем lost с разбором, не failed.
    was_sent = _maybe_sent(job) and not before_send
    if exc.code == "provider_unavailable":
        _provider_refused(job, JOB_SUBMITTING, exc, lost=was_sent)
        return "lost" if was_sent else "failed"
    if was_sent and exc.code in ("bad_params", "not_found"):
        _close(job, JOB_SUBMITTING, JOB_LOST, "submit_unknown", journal=GenerationLog.STATUS_LOST,
               journal_error=f"повтор отклонён (http {exc.status}), прошлая попытка могла дойти")
        return "lost"
    if exc.code == "bad_params":
        # Наша ошибка тела (или файл отклонён): поставщик денег не взял, в разбор.
        code = "upload_failed" if before_send else "bad_params"
        _close(job, JOB_SUBMITTING, JOB_FAILED, code, journal=GenerationLog.STATUS_FAILED,
               journal_error=f"поставщик отклонил запрос: http {exc.status}", review=True)
        return "failed"
    if exc.code == "not_found":
        _close(job, JOB_SUBMITTING, JOB_FAILED, "provider_failed", journal=GenerationLog.STATUS_FAILED,
               journal_error="модель недоступна аккаунту (404)", review=True)
        return "failed"
    maybe_sent = was_sent or ((exc.sent or exc.code == "bad_response") and not before_send)
    if maybe_sent and job.kind == KIND_CHARACTER:
        _close(job, JOB_SUBMITTING, JOB_LOST, "submit_unknown", journal=GenerationLog.STATUS_LOST,
               journal_error=f"исход обучения неизвестен: {exc.code}")
        return "lost"
    if attempts >= SUBMIT_MAX_ATTEMPTS:
        if maybe_sent:
            _close(job, JOB_SUBMITTING, JOB_LOST, "submit_unknown", journal=GenerationLog.STATUS_LOST,
                   journal_error=f"исход отправки неизвестен после {attempts} попыток")
            return "lost"
        code = "queue_timeout" if exc.code == "retry_later" else (
            "upload_failed" if before_send else "provider_failed")
        _close(job, JOB_SUBMITTING, JOB_FAILED, code, journal=GenerationLog.STATUS_FAILED,
               journal_error=f"{exc.code} после {attempts} попыток")
        return "failed"
    delay = _retry_delay(attempts, exc.retry_after)
    _journal_stage(job.genlog_id, "retry", f"{exc.code}, через {delay} с")
    _requeue(job, delay=delay, stage="retry", clear_body=job.kind == KIND_CHARACTER,
             maybe_sent=maybe_sent)
    return "retry"


# ---------------------------------------------------------------- poll

def _reschedule(job, claim_until, *, step: int, stage: str = "", errors: int = 0) -> bool:
    later = timezone.now()
    moved = CreativeJob.objects.filter(next_poll_at=claim_until).transition(
        job.pk, JOB_RUNNING, next_poll_at=later + timedelta(seconds=max(1, step - 1)),
        poll_count=F("poll_count") + 1, poll_errors=errors, stage=(stage or job.stage or "")[:24])
    if moved:
        _enqueue("poll_job", job.pk, countdown=step)
    return moved


def _to_saving(job) -> bool:
    if CreativeJob.objects.transition(job.pk, JOB_RUNNING, JOB_SAVING, lease_until=timezone.now(),
                                      stage="saving", attempts=0):
        _journal_stage(job.genlog_id, "completed", f"опросов: {job.poll_count + 1}")
        _enqueue("finalize_job", job.pk)
        return True
    return False


def poll(job_id) -> str:
    now = timezone.now()
    claim_until = now + POLL_CLAIM
    claimed = (CreativeJob.objects.filter(Q(next_poll_at__lte=now) | Q(next_poll_at__isnull=True))
               .transition(job_id, JOB_RUNNING, next_poll_at=claim_until))
    if not claimed:
        return "skip"
    job = _load(job_id)
    if job is None:
        return "skip"
    if not job.provider_request_id:
        _close(job, JOB_RUNNING, JOB_LOST, "submit_unknown", journal=GenerationLog.STATUS_LOST,
               journal_error="у задачи нет id поставщика")
        return "lost"
    try:
        if job.kind == KIND_CHARACTER:
            st = hf.character_status(job.provider_request_id)
            state = {"completed": "completed", "failed": "failed"}.get(st.status, st.status)
        else:
            st = hf.status(job.provider_request_id)
            state = st.status
    except hf.HFError as exc:
        return _poll_error(job, claim_until, exc)

    if state == "completed":
        return "saving" if _to_saving(job) else "skip"
    if state == "failed":
        logger.info("creative job=%s: поставщик: failed %s", job.uid, getattr(st, "error", "") or
                    getattr(st, "fail_reason", ""))
        _close(job, JOB_RUNNING, JOB_FAILED, "provider_failed", journal=GenerationLog.STATUS_FAILED,
               journal_error="генерация не удалась у поставщика", stage="failed")
        return "failed"
    if state == "nsfw":
        _close(job, JOB_RUNNING, JOB_NSFW, "nsfw", journal=GenerationLog.STATUS_FAILED,
               journal_error="отклонено модерацией", stage="nsfw")
        return "nsfw"
    if state == "canceled":
        _close(job, JOB_RUNNING, JOB_CANCELED, "canceled", journal=GenerationLog.STATUS_FAILED,
               journal_error="отменено у поставщика", stage="canceled")
        return "canceled"
    _reschedule(job, claim_until, step=poll_step(job), stage=state or "in_progress")
    if job.genlog_id and _once(f"creative:touch:{job.pk}", 30):
        try:
            GenerationLog.objects.filter(pk=job.genlog_id).update(updated_at=timezone.now())
        except Exception:
            pass
    return "polling"


def _poll_error(job, claim_until, exc: hf.HFError) -> str:
    errors = int(job.poll_errors or 0) + 1
    if exc.code == "not_found" and errors >= POLL_NOT_FOUND_MAX:
        _close(job, JOB_RUNNING, JOB_LOST, "provider_unreachable",
               qs=CreativeJob.objects.filter(next_poll_at=claim_until), poll_errors=errors,
               journal=GenerationLog.STATUS_LOST,
               journal_error=f"задача не видна поставщику {errors} раз подряд")
        return "lost"
    if exc.code == "provider_unavailable":
        from . import notify

        notify.staff_alert("provider_key" if exc.status == 401 else "provider_unavailable",
                           note=f"опрос: http {exc.status}")
    step = max(poll_step(job), POLL_ERROR_STEP if errors > 1 else 0)
    logger.info("creative job=%s: опрос не удался (%s), повтор через %s с", job.uid, exc, step)
    _reschedule(job, claim_until, step=step,
                errors=errors if exc.code in ("not_found", "provider_unavailable") else 0)
    return "polling"


# ---------------------------------------------------------------- finalize

class SaveError(RuntimeError):
    """Попытка выдачи не удалась; свои файлы уже стёрты."""


def _retry_later(job, reason: str) -> None:
    attempts = max(1, int(job.attempts or 1))
    wait = min(LEASE.total_seconds(), RETRY_BASE_S * 2 ** (attempts - 1))
    CreativeJob.objects.transition(job.pk, JOB_SAVING,
                                   lease_until=timezone.now() + timedelta(seconds=wait),
                                   stage="save_retry")
    _journal_stage(job.genlog_id, "save_retry", f"попытка {attempts}: {reason[:200]}")
    logger.warning("creative job=%s: выдача, попытка %s не удалась: %s", job.uid, attempts, reason[:300])


def _looks_like_markup(path: str) -> bool:
    try:
        with open(path, "rb") as fh:
            head = fh.read(64)
    except OSError:
        return True
    return head.lstrip(b"\xef\xbb\xbf \t\r\n")[:1] in (b"<", b"{", b"[")


def _save_image(job, n: int, src_path: str) -> dict:
    """Картинка результата: перезаписать без метаданных (PNG — PNG, иначе JPEG), превью."""
    from PIL import Image

    from cartoon.thumbs import make_thumb

    with Image.open(src_path) as probe_img:
        probe_img.verify()
    with Image.open(src_path) as img:
        img.load()
        fmt = (img.format or "").upper()
        width, height = img.size
        out = BytesIO()
        if fmt == "PNG" or img.mode in ("RGBA", "LA", "P"):
            if img.mode not in ("RGB", "RGBA"):
                img = img.convert("RGBA")
            img.save(out, format="PNG")
            ext, mime = "png", "image/png"
        else:
            if img.mode != "RGB":
                img = img.convert("RGB")
            img.save(out, format="JPEG", quality=95)
            ext, mime = "jpg", "image/jpeg"
    data = out.getvalue()
    base = f"{results_dir(job.user_id, job.uid)}/{n}"
    saved = [default_storage.save(f"{base}.{ext}", ContentFile(data))]
    thumb = ""
    blob = make_thumb(data, THUMB_BOX)
    if blob:
        thumb = default_storage.save(f"{base}_t.jpg", ContentFile(blob))
        saved.append(thumb)
    return {"path": saved[0], "mime": mime, "w": width, "h": height, "bytes": len(data),
            "poster": thumb}


def _strip_video(src: str, dst: str) -> bool:
    """Перепаковать ролик без метаданных (+faststart). False — оставить как есть."""
    cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-nostdin", "-y", "-i", src,
           "-map", "0", "-map_metadata", "-1", "-c", "copy", "-movflags", "+faststart", "-f", "mp4", dst]
    try:
        result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                timeout=STRIP_TIMEOUT_S, check=False)
    except (OSError, subprocess.TimeoutExpired):
        return False
    return result.returncode == 0 and os.path.isfile(dst) and os.path.getsize(dst) > 0


def _save_video(job, n: int, src_path: str, size: int) -> dict:
    from ai import video_edit
    from cartoon.thumbs import make_thumb

    if _looks_like_markup(src_path):
        raise SaveError("вместо ролика пришла разметка")
    clean = src_path + ".clean.mp4"
    path = clean if _strip_video(src_path, clean) else src_path
    try:
        size = os.path.getsize(path)
        info, poster = {}, None
        if size <= PROBE_MAX_BYTES:
            with open(path, "rb") as fh:
                data = fh.read()
            try:
                info = video_edit.probe_video(data) or {}
            except Exception:
                logger.warning("creative job=%s: ffprobe упал", job.uid, exc_info=True)
            try:
                poster = video_edit.extract_poster(data)
            except Exception:
                logger.warning("creative job=%s: кадр не извлёкся", job.uid, exc_info=True)
            del data
        base = f"{results_dir(job.user_id, job.uid)}/{n}"
        saved = []
        with open(path, "rb") as fh:
            saved.append(default_storage.save(f"{base}.mp4", File(fh)))
        thumb = ""
        blob = make_thumb(poster, POSTER_BOX) if poster else None
        if blob:
            thumb = default_storage.save(f"{base}_t.jpg", ContentFile(blob))
        return {"path": saved[0], "mime": "video/mp4", "w": info.get("width"), "h": info.get("height"),
                "bytes": int(size), "poster": thumb,
                "duration": float(info["duration"]) if info.get("duration") else None}
    finally:
        if path == clean:
            try:
                os.remove(clean)
            except OSError:
                pass


def fetch_results(job, urls: list[str]) -> list[dict]:
    """Скачать все файлы результата к себе. Бросает SaveError; при сбое свои файлы стёрты."""
    ensure_dir(results_dir(job.user_id, job.uid))
    files: list[dict] = []
    try:
        for n, url in enumerate(urls, 1):
            fd, tmp = tempfile.mkstemp(prefix="cs-res-")
            os.close(fd)
            try:
                video = job.kind == KIND_VIDEO
                try:
                    size = hf.download(url, tmp, max_bytes=VIDEO_MAX_BYTES if video else IMAGE_MAX_BYTES,
                                       wall_s=DOWNLOAD_WALL_S)
                except hf.HFError as exc:
                    raise SaveError(f"скачивание: {exc}") from None
                files.append(_save_video(job, n, tmp, size) if video else _save_image(job, n, tmp))
            except SaveError:
                raise
            except Exception as exc:
                raise SaveError(f"{type(exc).__name__}: {exc}") from exc
            finally:
                try:
                    os.remove(tmp)
                except OSError:
                    pass
    except SaveError:
        delete_files(*[p for f in files for p in (f.get("path"), f.get("poster"))])
        raise
    return files


def charge_amount(job, delivered: int) -> int:
    """Выдано меньше обещанного (часть партии) — платят за выданное, не меньше 1 кр."""
    reserved = int(job.credits_reserved or 0)
    expected = max(1, int(job.expected_outputs or 1))
    if delivered >= expected or reserved <= 0:
        return reserved
    return max(1, int(math.ceil(reserved * delivered / expected)))


def commit(job, files: list[dict]) -> Optional[object]:
    """Транзакция выдачи: saving→done и reserved→charged одним условным UPDATE + списание
    + журнал. None — выдал кто-то другой (файлы стирает вызывающий)."""
    from .reserve import charge_on_delivery, reason_for

    now = timezone.now()
    amount = charge_amount(job, len(files))
    with transaction.atomic():
        won = CreativeJob.objects.filter(charge_state=CHARGE_RESERVED).transition(
            job.pk, JOB_SAVING, JOB_DONE, charge_state=CHARGE_CHARGED, result_files=files,
            lease_until=None, next_poll_at=None, stage="done", error="", error_code="")
        if not won:
            return None
        charge = charge_on_delivery(job.user, amount, reason_for(job.kind),
                                    meta={"job": job.uid, "tool": job.tool_slug,
                                          "genlog": job.genlog_id, "outputs": len(files)})
        CreativeJob.objects.filter(pk=job.pk).update(credits_charged=charge.credits,
                                                     needs_review=bool(charge.partial),
                                                     updated_at=now)
        if job.genlog_id:
            first = files[0]["path"] if files else ""
            GenerationLog.objects.filter(pk=job.genlog_id).update(
                status=GenerationLog.STATUS_DELIVERED, credits_charged=charge.credits,
                result_url=default_storage.url(first)[:512] if first else "",
                provider_cost_usd=job.cost_usd, needs_review=bool(charge.partial), updated_at=now)
    return charge


def finalize(job_id) -> str:
    now = timezone.now()
    claimed = (CreativeJob.objects.filter(Q(lease_until__isnull=True) | Q(lease_until__lte=now))
               .transition(job_id, JOB_SAVING, lease_until=now + LEASE, attempts=F("attempts") + 1,
                           stage="saving"))
    if not claimed:
        return "skip"
    job = _load(job_id)
    if job is None:
        return "skip"
    if job.kind == KIND_CHARACTER:
        return _finalize_character(job)
    try:
        st = hf.status(job.provider_request_id)
    except hf.HFError as exc:
        if exc.code == "not_found":
            _close(job, JOB_SAVING, JOB_LOST, "save_failed", journal=GenerationLog.STATUS_LOST,
                   journal_error="при выдаче задача не видна поставщику")
            return "lost"
        _retry_later(job, f"статус: {exc}")
        return "retry"
    if st.status != "completed" or not st.urls:
        if st.status in ("failed", "nsfw", "canceled"):
            _close(job, JOB_SAVING, JOB_LOST, "save_failed", journal=GenerationLog.STATUS_LOST,
                   journal_error=f"при выдаче поставщик ответил {st.status}")
            return "lost"
        _retry_later(job, f"нет ссылок на результат ({st.status or 'пусто'})")
        return "retry"
    urls = st.urls
    if job.kind != KIND_VIDEO:
        urls = list(st.images) or urls
    else:
        urls = [st.video] if st.video else urls[:1]
    try:
        files = fetch_results(job, urls)
    except SaveError as exc:
        _retry_later(job, str(exc))
        return "retry"
    try:
        charge = commit(job, files)
    except Exception as exc:
        logger.exception("creative job=%s: транзакция выдачи упала", job.uid)
        landed = CreativeJob.objects.filter(pk=job.pk, status=JOB_DONE).values_list(
            "result_files", flat=True).first()
        if landed and files and landed[0].get("path") == files[0]["path"]:
            _after_delivery(job.pk, note="выдача записана, хотя база ответила ошибкой")
            return "done"
        if landed is None:
            delete_files(*[p for f in files for p in (f.get("path"), f.get("poster"))])
        _retry_later(job, f"транзакция: {type(exc).__name__}")
        return "retry"
    if charge is None:
        delete_files(*[p for f in files for p in (f.get("path"), f.get("poster"))])
        logger.info("creative job=%s: выдачу сделал другой — свои файлы стёрты", job.uid)
        return "raced"
    _after_delivery(job.pk, note=f"списано {charge.credits} кр" + (" (частично)" if charge.partial else ""))
    return "done"


def _after_delivery(job_id, *, note: str) -> None:
    try:
        job = CreativeJob.objects.filter(pk=job_id).only("uid", "genlog_id").first()
        if job is not None:
            logger.info("creative delivered job=%s %s", job.uid, note)
            _journal_stage(job.genlog_id, "delivered", note)
    except Exception:
        logger.warning("creative: шаг журнала после выдачи не записался", exc_info=True)
    notify_later(job_id)


def _finalize_character(job) -> str:
    try:
        st = hf.character_status(job.provider_request_id)
    except hf.HFError as exc:
        _retry_later(job, f"статус персонажа: {exc}")
        return "retry"
    if st.status == "failed":
        _close(job, JOB_SAVING, JOB_FAILED, "provider_failed", journal=GenerationLog.STATUS_FAILED,
               journal_error="обучение персонажа не удалось")
        return "failed"
    if st.status != "completed":
        _retry_later(job, f"персонаж ещё не готов ({st.status})")
        return "retry"
    files: list[dict] = []
    if st.thumbnail_url:
        try:
            files = fetch_results(job, [st.thumbnail_url])
        except SaveError as exc:
            # Превью — оформление: персонаж готов и без него.
            logger.warning("creative job=%s: превью персонажа не скопировалось: %s", job.uid, exc)
            files = []
    from .reserve import charge_on_delivery, reason_for

    now = timezone.now()
    with transaction.atomic():
        won = CreativeJob.objects.filter(charge_state=CHARGE_RESERVED).transition(
            job.pk, JOB_SAVING, JOB_DONE, charge_state=CHARGE_CHARGED, result_files=files,
            lease_until=None, next_poll_at=None, stage="done", error="", error_code="")
        if not won:
            charge = None
        else:
            charge = charge_on_delivery(job.user, int(job.credits_reserved or 0), reason_for(job.kind),
                                        meta={"job": job.uid, "tool": job.tool_slug,
                                              "genlog": job.genlog_id})
            CreativeJob.objects.filter(pk=job.pk).update(credits_charged=charge.credits,
                                                         needs_review=bool(charge.partial),
                                                         updated_at=now)
            CreativeCharacter.objects.filter(job_id=job.pk).update(
                status=CreativeCharacter.STATUS_READY, provider_id=st.id,
                thumb_path=(files[0].get("poster") or files[0]["path"]) if files else "",
                updated_at=now)
            if job.genlog_id:
                GenerationLog.objects.filter(pk=job.genlog_id).update(
                    status=GenerationLog.STATUS_DELIVERED, credits_charged=charge.credits,
                    provider_cost_usd=job.cost_usd, needs_review=bool(charge.partial),
                    updated_at=now)
    if charge is None:
        delete_files(*[p for f in files for p in (f.get("path"), f.get("poster"))])
        return "raced"
    _after_delivery(job.pk, note=f"персонаж готов, списано {charge.credits} кр")
    return "done"


# ---------------------------------------------------------------- отмена

def cancel(job_id) -> bool:
    """Отмена человеком. True — задача отменена, резерв снят.

    Из нашей очереди — сразу. Ушедшую поставщику — только пока она у него в
    очереди (cancel → 202); начатую отменить нельзя (False).
    """
    job = _load(job_id)
    if job is None:
        return False
    if job.status == JOB_QUEUED:
        if _maybe_sent(job):
            # Ждёт повтора после попытки с неизвестным исходом: поставщик, возможно,
            # уже генерирует. Отмена бросила бы его работу без присмотра — 409.
            logger.info("creative job=%s: отмена отклонена — прошлая попытка могла дойти", job.uid)
            return False
        return _close(job, JOB_QUEUED, JOB_CANCELED, "canceled", journal=GenerationLog.STATUS_FAILED,
                      journal_error="отменено человеком", stage="canceled")
    if (job.status == JOB_RUNNING and job.kind != KIND_CHARACTER and job.provider_request_id
            and job.stage in ("queued", "submitted", "")):
        try:
            ok = hf.cancel(job.provider_request_id)
        except hf.HFError as exc:
            logger.info("creative job=%s: отмена у поставщика не удалась: %s", job.uid, exc)
            return False
        if ok:
            return _close(job, JOB_RUNNING, JOB_CANCELED, "canceled",
                          journal=GenerationLog.STATUS_FAILED,
                          journal_error="отменено человеком в очереди поставщика", stage="canceled")
    return False


# ---------------------------------------------------------------- вебхук → опрос

def poke(provider_request_id: str) -> bool:
    """Вебхук сообщил об итоге: опросить задачу сейчас (тело вебхука деньгами не управляет)."""
    job = CreativeJob.objects.filter(provider_request_id=str(provider_request_id)[:64],
                                     status=JOB_RUNNING).only("pk").first()
    if job is None:
        return False
    CreativeJob.objects.filter(pk=job.pk, status=JOB_RUNNING).update(next_poll_at=timezone.now())
    _enqueue("poll_job", job.pk)
    return True


# ---------------------------------------------------------------- sweep

def _rows(qs, *fields):
    return list(qs.order_by("pk").values("pk", "uid", "kind", "genlog_id", *fields)[:SWEEP_BATCH])


def _stub(row) -> CreativeJob:
    return CreativeJob(pk=row["pk"], uid=row["uid"], kind=row["kind"], genlog_id=row["genlog_id"],
                       request_body=row.get("request_body") or {})


def _sweep_queued(now, out) -> None:
    stale = now - QUEUED_REQUEUE_AFTER
    dead = now - QUEUED_TIMEOUT
    due = Q(next_poll_at__isnull=True) | Q(next_poll_at__lte=now - POLL_STALE)
    for row in _rows(CreativeJob.objects.filter(status=JOB_QUEUED, created_at__lt=stale).filter(due),
                     "created_at", "request_body"):
        if row["created_at"] < dead:
            stub = _stub(row)
            if _maybe_sent(stub):
                # Прошлая попытка могла дойти: не «ничего не уходило», а разбор.
                if _close(stub, JOB_QUEUED, JOB_LOST, "submit_unknown",
                          qs=CreativeJob.objects.filter(created_at__lt=dead), stage="queue_timeout",
                          journal=GenerationLog.STATUS_LOST,
                          journal_error="очередь дольше 30 минут после попытки с неизвестным исходом"):
                    out["submit_unknown"] += 1
            elif _close(stub, JOB_QUEUED, JOB_FAILED, "queue_timeout",
                        qs=CreativeJob.objects.filter(created_at__lt=dead), stage="queue_timeout",
                        journal=GenerationLog.STATUS_FAILED, journal_error="очередь дольше 30 минут"):
                out["queue_timeout"] += 1
        elif _once(f"creative:requeue:{row['pk']}", REQUEUE_DEDUP_S):
            _enqueue("submit_job", row["pk"])
            out["requeued"] += 1


def _sweep_submitting(now, out) -> None:
    cutoff = now - SUBMITTING_STALE
    dead = now - QUEUED_TIMEOUT
    for row in _rows(CreativeJob.objects.filter(status=JOB_SUBMITTING, updated_at__lt=cutoff),
                     "request_body", "attempts", "created_at"):
        stub = _stub(row)
        sent = _saved_body(stub)
        stale_qs = CreativeJob.objects.filter(updated_at__lt=cutoff)
        if row["kind"] == KIND_CHARACTER and sent is not None:
            if _close(stub, JOB_SUBMITTING, JOB_LOST, "submit_unknown", qs=stale_qs,
                      journal=GenerationLog.STATUS_LOST, journal_error="обучение зависло на отправке"):
                out["submit_unknown"] += 1
        elif int(row["attempts"] or 0) >= SUBMIT_MAX_ATTEMPTS or row["created_at"] < dead:
            # Отправка падает раз за разом мимо обработчиков: по кругу не возвращаем.
            if _give_up(stub, JOB_SUBMITTING, "provider_failed",
                        f"отправка зависала, попыток {row['attempts']}", qs=stale_qs) != "skip":
                out["submit_gave_up"] += 1
        else:
            # Тело и ключ сохранены (или ещё ничего не уходило): повтор тем же ключом
            # безопасен. Тело сохранено — шаг мог упасть во время POST: отметка.
            extra = {"request_body": {**sent, "maybe_sent": True}} if sent is not None else {}
            if stale_qs.transition(row["pk"], JOB_SUBMITTING, JOB_QUEUED, next_poll_at=None,
                                   stage="requeued", **extra):
                _enqueue("submit_job", row["pk"])
                out["resubmit"] += 1


def _sweep_running(now, out) -> None:
    for kind, limit in GIVE_UP.items():
        cutoff = now - limit
        give_up = Q(submitted_at__lt=cutoff) | Q(submitted_at__isnull=True, created_at__lt=cutoff)
        for row in _rows(CreativeJob.objects.filter(status=JOB_RUNNING, kind=kind).filter(give_up)):
            if _close(_stub(row), JOB_RUNNING, JOB_LOST, "provider_timeout",
                      qs=CreativeJob.objects.filter(give_up), stage="timeout",
                      journal=GenerationLog.STATUS_LOST,
                      journal_error=f"результата нет дольше {limit}"):
                out["provider_timeout"] += 1
    late = now - POLL_STALE
    for row in _rows(CreativeJob.objects.filter(status=JOB_RUNNING).filter(
            Q(next_poll_at__lt=late) | Q(next_poll_at__isnull=True))):
        if _once(f"creative:repoll:{row['pk']}", REQUEUE_DEDUP_S):
            _enqueue("poll_job", row["pk"])
            out["repoll"] += 1


def _sweep_saving(now, out) -> None:
    expired = Q(lease_until__lt=now) | Q(lease_until__isnull=True)
    for row in _rows(CreativeJob.objects.filter(status=JOB_SAVING).filter(expired), "attempts"):
        if row["attempts"] < MAX_SAVE_ATTEMPTS:
            if _once(f"creative:refinalize:{row['pk']}", REQUEUE_DEDUP_S):
                _enqueue("finalize_job", row["pk"])
                out["refinalize"] += 1
        elif _close(_stub(row), JOB_SAVING, JOB_LOST, "save_failed",
                    qs=CreativeJob.objects.filter(expired, attempts__gte=MAX_SAVE_ATTEMPTS),
                    stage="save_failed", journal=GenerationLog.STATUS_LOST,
                    journal_error=f"выдача не удалась за {MAX_SAVE_ATTEMPTS} попыток"):
            out["save_failed"] += 1


def sweep(now=None) -> dict:
    """Страховка конвейера раз в минуту. Замок — чтобы два прогона не шли разом."""
    from collections import Counter

    try:
        locked = cache.add(SWEEP_LOCK_KEY, 1, SWEEP_LOCK_TTL)
    except Exception:
        locked = None
    if locked is False:
        return {"skipped": 1}
    now = now or timezone.now()
    out: Counter = Counter()
    try:
        for rule in (_sweep_queued, _sweep_submitting, _sweep_running, _sweep_saving):
            try:
                rule(now, out)
            except Exception:
                logger.exception("creative sweep: правило %s упало", getattr(rule, "__name__", rule))
                out["errors"] += 1
    finally:
        if locked:
            try:
                cache.delete(SWEEP_LOCK_KEY)
            except Exception:
                pass
    result = dict(out)
    if result:
        logger.info("creative sweep: %s", result)
    return result


# ---------------------------------------------------------------- чистка загрузок

def purge_uploads(now=None) -> int:
    """Загрузки старше CREATIVE_UPLOAD_KEEP_DAYS, которых не ждёт ни одна открытая задача."""
    now = now or timezone.now()
    try:
        days = max(1, int(getattr(settings, "CREATIVE_UPLOAD_KEEP_DAYS", UPLOAD_KEEP_DAYS_DEFAULT)))
    except (TypeError, ValueError):
        days = UPLOAD_KEEP_DAYS_DEFAULT
    busy: set[str] = set()
    for params in CreativeJob.objects.filter(status__in=JOB_OPEN).values_list("params", flat=True):
        if isinstance(params, dict):
            busy.update(_upload_uids(params))
    rows = list(CreativeUpload.objects.filter(created_at__lt=now - timedelta(days=days))
                .order_by("pk")[:PURGE_BATCH])
    count = 0
    for row in rows:
        if row.uid in busy:
            continue
        row.delete()   # файлы стирает сигнал после коммита
        count += 1
    if count:
        logger.info("creative: стёрто загрузок %s", count)
    return count


__all__ = ["submit", "poll", "finalize", "cancel", "sweep", "poke", "purge_uploads",
           "enqueue_start", "commit", "charge_amount", "fetch_results", "ERRORS", "hook_url"]
