"""Конвейер видеостудии: машина состояний дубля и короткие шаги (§6.2–6.5).

Каждая функция здесь — тело одной Celery-задачи (vstudio.tasks) и не держит
слот воркера дольше одного сетевого вызова:

    submit(take)   queued→submitting → журнал → POST /videos → running | failed | lost
    poll(take)     один GET по адресу опроса → перезапуск через countdown | saving | failed
    finalize(take) повторный опрос → скачивание → файлы → транзакция done+charged
    run_image(take) queued→running → журнал → POST /images → done+charged | failed
    sweep()        страховка раз в минуту: потерянные цепочки, зависшие шаги, 6 часов
    purge_assets() удалённые материалы старше 30 дней без ссылок

Главные правила:
- Каждый переход — условный UPDATE (Take.objects.transition, §2.2). Ноль
  строк значит, что работу уже сделала другая копия задачи, sweep или отмена:
  вызов тихо выходит. Поэтому двойная постановка любой задачи безопасна.
- Журнал (GenerationLog, source=vstudio) создаётся в submit прямо перед
  вызовом провайдера. Не создался — провайдеру ничего не уходит (fail-closed).
- Провайдер принял работу → сначала строка в логе с provider_id, потом запись
  в БД: если база моргнёт, оплаченный ролик найдётся по логу.
- Деньги: списание только в транзакции выдачи (delivery.commit_*), резерв
  снимается тем же UPDATE, что закрывает дубль (failed | canceled | lost).
- Никакого time.sleep и SSE: ожидание — это countdown следующей задачи.

Логгер «vstudio.pipeline» (дочерний «vstudio»), в каждой строке take=<uid>.
"""
from __future__ import annotations

import base64
import copy
import logging
import mimetypes
import re
import statistics
import uuid
from datetime import timedelta
from typing import Iterable, Optional
from urllib.parse import unquote, urlsplit

from django.conf import settings
from django.core.cache import cache
from django.core.files.storage import default_storage
from django.db import transaction
from django.db.models import F, Q
from django.utils import timezone

from ai import genlog
from ai import media_provider as mp
from ai.models import GenerationLog
from ai.provider_errors import INPUT_ERROR_CODES, explain_image_error, explain_video_error

from . import delivery, notify
from .assets import store_image_bytes
from .models import (
    TAKE_CANCELED, TAKE_CLOSED, TAKE_DONE, TAKE_FAILED, TAKE_LOST, TAKE_QUEUED, TAKE_RUNNING,
    TAKE_SAVING, TAKE_SUBMITTING, Asset, ShotInput, Take,
)

logger = logging.getLogger(__name__)

# --- Опрос (§6.3, шаг 3)
FIRST_POLL_S = 15                       # первый опрос после приёма
POLL_CLAIM = timedelta(seconds=90)      # захват: другая копия цепочки не опросит раньше
POLL_STEPS = ((180, 10), (900, 20))     # до 3 мин — 10 с, до 15 мин — 20 с
POLL_STEP_LATE = 60                     # дальше — раз в минуту
JOURNAL_TOUCH_S = 30                    # пульс журнала не чаще раза в 30 с
# 401/403/404/410 на опросе («работы этим ключом не видно»): не ждём шесть
# часов, а после стольких ответов подряд — lost, резерв снят, «Довезти» в
# админке (там ключ тот же, что при отправке). Пауза между ними не меньше
# 30 с: короткий сбой авторизации у OpenRouter (~5 минут) дубль переживает.
POLL_UNREACHABLE_MAX = 10
POLL_UNREACHABLE_STEP = 30

# --- Выдача (§6.3, шаг 4)
LEASE = timedelta(minutes=6)            # аренда finalize: пока она жива, второй не начнёт
MAX_SAVE_ATTEMPTS = 5
RETRY_BASE_S = 60                       # после сбоя попытки — повтор через 1, 2, 4, 6… мин

# --- Страховка (§6.5)
QUEUED_REQUEUE_AFTER = timedelta(minutes=3)
QUEUED_TIMEOUT = timedelta(minutes=30)
SUBMITTING_STALE = timedelta(minutes=15)    # согласовано с зачисткой ai.recovery
POLL_STALE = timedelta(seconds=60)
IMAGE_TIMEOUT = timedelta(minutes=8)
SWEEP_LOCK_KEY = "vstudio:sweep"
SWEEP_LOCK_TTL = 55
SWEEP_BATCH = 200
REQUEUE_DEDUP_S = 110                   # одна повторная постановка за ~2 прогона sweep

# --- Чистка материалов
PURGE_BATCH = 500

# --- ETA (§9.6): медиана submitted→finished выданных дублей модели за 7 дней
ETA_WINDOW = timedelta(days=7)
ETA_MIN_SAMPLES = 5
ETA_SAMPLE_LIMIT = 500
ETA_CACHE_S = 600
ETA_FALLBACK = {Take.KIND_VIDEO: 150, Take.KIND_IMAGE: 30}

# --- Референсы data-URL (только локальный стенд, VSTUDIO_INLINE_REFS=1)
MAX_INLINE_BYTES = 20 * 1024 * 1024

_UID_RE = re.compile(r"^[0-9a-f]{32}$")

# Тексты ошибок конвейера — те же, что у фронта (lib/vstudio/errors.ts,
# TAKE_ERROR_RU); коды читает отчёт BE-11.
ERRORS = {
    "journal_unavailable": "Не удалось запустить генерацию. Кредиты не списаны — попробуйте ещё раз.",
    "queue_timeout": "Генерация слишком долго ждала очереди. Кредиты не списаны — попробуйте ещё раз.",
    "submit_unknown": "Не удалось подтвердить запуск — кредиты не списаны, мы проверим вручную.",
    "provider_timeout": "Модель так и не вернула результат. Кредиты не списаны, мы проверим вручную.",
    "save_failed": "Не удалось сохранить результат. Кредиты не списаны, мы проверим вручную.",
    "service_misconfigured": "Студия временно недоступна. Мы уже чиним. Кредиты не списаны.",
    "internal_error": "Не удалось запустить генерацию. Кредиты не списаны — попробуйте ещё раз.",
    "bad_result": "Модель вернула файл, который не удалось открыть. Кредиты не списаны — попробуйте ещё раз.",
    "provider_unreachable": "Не удалось забрать результат у модели. Кредиты не списаны, мы проверим вручную.",
}


# ---------------------------------------------------------------- постановка задач

def _enqueue(task_name: str, take_id: int, *, countdown: Optional[float] = None, **kwargs) -> bool:
    """Поставить задачу vstudio.tasks.<task_name>. Сбой брокера не роняет вызывающего:
    потерянный шаг подберёт sweep (§6.5). Очередь задаёт CELERY_TASK_ROUTES."""
    try:
        from . import tasks

        options = {"countdown": countdown} if countdown else {}
        getattr(tasks, task_name).apply_async(args=[take_id], kwargs=kwargs or None, **options)
        return True
    except Exception:
        logger.exception("vstudio: задача %s не поставилась take_id=%s", task_name, take_id)
        return False


def enqueue_start(take) -> None:
    """Первый шаг дубля по его виду: submit_take (видео) или run_image_take.

    Для BE-9: transaction.on_commit(lambda: pipeline.enqueue_start(take)).
    """
    _enqueue("run_image_take" if take.kind == Take.KIND_IMAGE else "submit_take", take.pk)


def _once(key: str, ttl: int) -> bool:
    """Не чаще раза в ttl: True — можно. Кэш недоступен — можно (лишнее безопасно)."""
    try:
        return bool(cache.add(key, 1, ttl))
    except Exception:
        return True


# ---------------------------------------------------------------- помощники

def _load(take_id) -> Optional[Take]:
    return (Take.objects.select_related("user", "project", "shot", "result_asset")
            .filter(pk=take_id).first())


def _journal_params(take: Take) -> dict:
    """params журнала: take=uid (по нему админка находит дубль), режим, число фото."""
    body = take.request_body if isinstance(take.request_body, dict) else {}
    params = {k: v for k, v in (take.effective or {}).items()
              if k not in ("take", "mode", "refs", "frames")}
    params.update({"take": take.uid, "mode": take.mode,
                   "refs": len(body.get("input_references") or []),
                   "frames": len(body.get("frame_images") or [])})
    return params


def _start_journal(take: Take):
    return genlog.start(user=take.user, kind=take.kind, source=GenerationLog.SOURCE_VSTUDIO,
                        model=take.model_ref, prompt=take.serialized_prompt,
                        credits_planned=take.credits_reserved, params=_journal_params(take))


def _uid_from_url(url: str) -> str:
    try:
        name = unquote(urlsplit(str(url or "")).path or "").rsplit("/", 1)[-1]
    except ValueError:
        return ""
    stem = name.split(".", 1)[0]
    return stem if _UID_RE.match(stem) else ""


def sent_asset_uids(body) -> list[str]:
    """uid материалов в порядке тела запроса (= compiled.used): кадры или референсы.

    Путь файла — vstudio/<user_id>/<asset_uid>.<ext>, поэтому uid читается из URL.
    """
    if not isinstance(body, dict):
        return []
    out = []
    for key in ("frame_images", "input_references"):
        for item in body.get(key) or []:
            url = ((item or {}).get("image_url") or {}).get("url") if isinstance(item, dict) else ""
            uid = _uid_from_url(url)
            if uid and uid not in out:
                out.append(uid)
    return out


def blamed_input(take: Take, code: str) -> str:
    """uid виноватого входа при отказе модерации (§6.3): первый отправленный кадр
    или референс. По остальным кодам — пусто (виновато не фото)."""
    if code not in INPUT_ERROR_CODES:
        return ""
    uids = sent_asset_uids(take.request_body)
    if uids:
        return uids[0]
    # Тело без URL (не должно быть) — берём по лотку: кадры, потом референсы.
    rank = {ShotInput.SLOT_FIRST_FRAME: 0, ShotInput.SLOT_LAST_FRAME: 1, ShotInput.SLOT_REFERENCE: 2}
    rows = list(ShotInput.objects.filter(shot_id=take.shot_id, included=True)
                .values_list("slot", "position", "asset__uid"))
    rows.sort(key=lambda r: (rank.get(r[0], 3), r[1]))
    return rows[0][2] if rows else ""


def storage_name(url: str) -> str:
    """URL файла студии → имя в default_storage. Только vstudio/…, без «..»."""
    path = unquote(urlsplit(str(url or "")).path or "")
    media = urlsplit(str(getattr(settings, "MEDIA_URL", "") or "/media/")).path or "/media/"
    if not media.endswith("/"):
        media += "/"
    if not path.startswith(media):
        raise ValueError(f"не файл студии: {str(url)[:120]}")
    name = path[len(media):]
    parts = name.split("/")
    if not name.startswith("vstudio/") or any(p in ("", ".", "..") for p in parts):
        raise ValueError(f"не файл студии: {str(url)[:120]}")
    return name


def _data_url(url: str) -> str:
    if str(url).startswith("data:"):
        return url
    name = storage_name(url)
    with default_storage.open(name, "rb") as fh:
        blob = fh.read(MAX_INLINE_BYTES + 1)
    if not blob or len(blob) > MAX_INLINE_BYTES:
        raise ValueError(f"файл {name} пустой или слишком большой для data-URL")
    mime = mimetypes.guess_type(name)[0] or "image/jpeg"
    return f"data:{mime};base64,{base64.b64encode(blob).decode('ascii')}"


def outgoing_body(body) -> dict:
    """Тело для провайдера. В БД лежит как есть; при VSTUDIO_INLINE_REFS (только
    локальный стенд) URL картинок подменяются data-URL — провайдер не достанет
    localhost. Сбой чтения файла — исключение: молча слать без фото нельзя."""
    out = copy.deepcopy(body) if isinstance(body, dict) else {}
    if not getattr(settings, "VSTUDIO_INLINE_REFS", False):
        return out
    for key in ("frame_images", "input_references"):
        for item in out.get(key) or []:
            image = item.get("image_url") if isinstance(item, dict) else None
            if isinstance(image, dict) and image.get("url"):
                image["url"] = _data_url(image["url"])
    return out


def _fail_asset(take: Take, code: str) -> None:
    """Картинка не получилась: pending-чип в лотке становится красным."""
    if take.kind != Take.KIND_IMAGE or not take.result_asset_id:
        return
    try:
        Asset.objects.filter(pk=take.result_asset_id, status=Asset.STATUS_PENDING).update(
            status=Asset.STATUS_FAILED, error_code=str(code or "")[:40])
    except Exception:
        logger.warning("vstudio take=%s: ассет не помечен failed", take.uid, exc_info=True)


def _close(take: Take, frm, to: str, code: str, *, message: str = "", error_input: str = "",
           qs=None, journal: Optional[str] = None, journal_error: str = "", review: bool = False,
           cost=None, **fields) -> bool:
    """Закрыть дубль failed | lost | canceled условным UPDATE (резерв снимается им же).

    journal — во что перевести открытую запись журнала (failed | lost | None).
    После успеха: ассет картинки → failed, уведомление (§6.6).
    """
    qs = Take.objects if qs is None else qs
    amount = delivery.money(cost)
    if amount is not None:
        fields["provider_cost_usd"] = amount
    moved = qs.transition(
        take.pk, frm, to, error=message or ERRORS.get(code, ERRORS["internal_error"]),
        error_code=str(code or "")[:40], error_input=str(error_input or "")[:32],
        next_poll_at=None, lease_until=None, **fields)
    if not moved:
        return False
    log = logger.warning if to == TAKE_LOST else logger.info
    log("vstudio take=%s %s→%s code=%s", take.uid, "|".join((frm,) if isinstance(frm, str) else frm),
        to, code)
    if to in (TAKE_FAILED, TAKE_LOST, TAKE_CANCELED):
        _fail_asset(take, code)
    if journal and take.genlog_id:
        delivery.journal_close(take.genlog_id, journal, error=journal_error or code,
                               review=review, cost=amount)
    notify_later(take.pk)
    return True


def provider_config(take) -> dict:
    """Конфиг OpenRouter с ключом, которым работа дубля была отправлена.

    Работу видит только принявший её аккаунт: после автопереключения на
    запасной опрос текущим ключом получал бы 401/404 до самого sweep.
    """
    return mp.config_for(getattr(take, "provider_account_id", None),
                         str(getattr(take, "provider_key_fp", "") or ""))


def delivery_landed(take_id, file_name: str) -> Optional[bool]:
    """Записалась ли выдача, хотя транзакция закончилась ошибкой (§6.7).

    Ошибка на COMMIT неоднозначна: сервер мог его применить, а ответ потерялся
    вместе с соединением. Перечитываем дубль (при обрыве — новым соединением):
    True — дубль done и указывает на наш файл, файлы трогать нельзя;
    False — выдача не записалась (дубль открыт или указывает на другой файл),
    свои файлы можно стереть; None — прочитать не удалось: файлы оставляем,
    лишний файл дешевле стёртого оплаченного результата.
    """
    from django.db import connection

    row = None
    for attempt in (1, 2):
        try:
            if not connection.in_atomic_block:
                # Упавшее соединение непригодно — закрыть, запрос ниже откроет новое.
                connection.close_if_unusable_or_obsolete()
            row = Take.objects.filter(pk=take_id).values("status", "result_asset__file").first()
            break
        except Exception:
            logger.warning("vstudio take_id=%s: не перечитался после сбоя выдачи (попытка %s)",
                           take_id, attempt, exc_info=True)
            if attempt == 2 or connection.in_atomic_block:
                return None
            try:
                connection.close()
            except Exception:
                pass
    if row is None:
        return False
    return bool(file_name) and row["status"] == TAKE_DONE and row["result_asset__file"] == file_name


def landed_outcome(take_id) -> "delivery.Delivered":
    """Итог выдачи, которая записалась, хотя транзакция ответила ошибкой (для _after_delivery)."""
    from .reserve import Charge

    try:
        take = Take.objects.select_related("result_asset").filter(pk=take_id).first()
    except Exception:
        take = None
    if take is None:
        return delivery.Delivered(True, None, Charge(0, False))
    credits = int(take.credits_charged or 0)
    partial = take.charge_state == Take.CHARGE_CHARGED and credits < int(take.credits_reserved or 0)
    return delivery.Delivered(True, take.result_asset, Charge(credits, partial))


def notify_later(take_id) -> None:
    """Уведомление по итогу (§6.6) — отдельной задачей, если оно вообще нужно."""
    try:
        if notify.wanted(take_id):
            _enqueue("notify_take", take_id)
    except Exception:
        logger.warning("vstudio: уведомление не поставилось take_id=%s", take_id, exc_info=True)


def poll_step(take: Take, now=None) -> int:
    """Пауза до следующего опроса: 10 с первые 3 минуты, 20 с до 15 минут, дальше 60 с."""
    now = now or timezone.now()
    started = take.submitted_at or take.created_at or now
    elapsed = (now - started).total_seconds()
    for limit, step in POLL_STEPS:
        if elapsed < limit:
            return step
    return POLL_STEP_LATE


# ---------------------------------------------------------------- submit (видео)

def submit(take_id) -> str:
    """queued→submitting → журнал → POST /videos → running | failed | lost (§6.3, шаг 2)."""
    if not Take.objects.transition(take_id, TAKE_QUEUED, TAKE_SUBMITTING, stage="submitting"):
        return "skip"
    take = _load(take_id)
    if take is None:
        return "skip"
    if take.kind != Take.KIND_VIDEO:
        # Картинки идут через run_image_take; сюда попасть не должны.
        _close(take, TAKE_SUBMITTING, TAKE_FAILED, "internal_error")
        return "failed"

    entry = _start_journal(take)
    if entry.pk is None:
        # Fail-closed: без записи в журнале провайдеру ничего не уходит — иначе
        # оплаченный ролик, если что-то пойдёт не так, никто не найдёт.
        logger.error("vstudio take=%s: журнал недоступен — провайдеру не отправляем", take.uid)
        _close(take, TAKE_SUBMITTING, TAKE_FAILED, "journal_unavailable")
        return "failed"
    # Ключ фиксируем ДО отправки и пишем на дубль вместе с журналом: опрос,
    # скачивание и «Довезти» пойдут им же, даже если активный аккаунт
    # переключится посреди съёмки (или адрес опроса довезут из журнала).
    cfg = mp.current_config()
    account = {"provider_account_id": cfg.get("account_id"),
               "provider_key_fp": str(cfg.get("key_fp") or "")[:16]}
    if not Take.objects.transition(take.pk, TAKE_SUBMITTING, genlog=entry.pk, **account):
        entry.failed("дубль закрыт до отправки провайдеру")
        return "skip"
    take.genlog_id = entry.pk

    try:
        body = outgoing_body(take.request_body)
    except Exception as exc:
        logger.exception("vstudio take=%s: тело запроса не собралось", take.uid)
        _close(take, TAKE_SUBMITTING, TAKE_FAILED, "service_misconfigured",
               journal=GenerationLog.STATUS_FAILED, journal_error=f"тело не собралось: {exc}")
        return "failed"

    entry.stage("sending")
    res = mp.submit_video(body, cfg=cfg)

    if res.accepted:
        now = timezone.now()
        # След в логе ДО записи в БД: если база моргнёт, ролик найдётся по этой строке.
        logger.info("vstudio accepted take=%s provider_id=%s polling_url=%s account=%s key=%s",
                    take.uid, res.job_id, res.polling_url, account["provider_account_id"],
                    account["provider_key_fp"])
        ids = {"provider_id": str(res.job_id or "")[:160],
               "polling_url": str(res.polling_url or "")[:512]}
        moved = Take.objects.transition(
            take.pk, TAKE_SUBMITTING, TAKE_RUNNING, submitted_at=now,
            next_poll_at=now + timedelta(seconds=FIRST_POLL_S), stage="submitted", **ids)
        entry.submitted(res.job_id, res.polling_url)
        if moved:
            _enqueue("poll_take", take.pk, countdown=FIRST_POLL_S)
            return "running"
        # Дубль закрыли, пока шла отправка (sweep спустя 15 минут), а провайдер
        # работу принял: адрес опроса сохраняем, чтобы ролик можно было довезти.
        Take.objects.filter(pk=take.pk, provider_id="").update(submitted_at=now, updated_at=now, **ids)
        entry.lost("провайдер принял работу, но дубль уже закрыт — нужен довоз")
        logger.error("vstudio take=%s: принят провайдером после закрытия дубля", take.uid)
        return "lost"

    if res.state == mp.STATE_REJECTED:
        # 4xx: провайдер отказал сам и денег не взял.
        message, code = explain_video_error(res.text)
        _close(take, TAKE_SUBMITTING, TAKE_FAILED, code, message=message,
               error_input=blamed_input(take, code), stage="rejected",
               journal=GenerationLog.STATUS_FAILED, journal_error=res.text or message)
        return "failed"

    # 5xx, таймаут, 2xx без id: запрос мог дойти и быть оплачен — человек не
    # платит, запись уходит в разбор (needs_review).
    _close(take, TAKE_SUBMITTING, TAKE_LOST, "submit_unknown", stage="unknown",
           journal=GenerationLog.STATUS_LOST, journal_error=res.text or "исход отправки неизвестен")
    return "lost"


# ---------------------------------------------------------------- poll

def poll(take_id) -> str:
    """Один опрос провайдера (§6.3, шаг 3). Лишние копии цепочки гаснут на захвате."""
    now = timezone.now()
    # Значение захвата — метка «опрашиваю я»: если, пока шёл GET, строку
    # захватила другая копия цепочки, наш перезапуск ниже ничего не сдвинет.
    claim_until = now + POLL_CLAIM
    claimed = (Take.objects.filter(Q(next_poll_at__lte=now) | Q(next_poll_at__isnull=True))
               .transition(take_id, TAKE_RUNNING, next_poll_at=claim_until))
    if not claimed:
        return "skip"
    take = _load(take_id)
    if take is None or take.kind != Take.KIND_VIDEO:
        return "skip"
    if not take.polling_url:
        _close(take, TAKE_RUNNING, TAKE_LOST, "submit_unknown", journal=GenerationLog.STATUS_LOST,
               journal_error="у дубля нет адреса опроса")
        return "lost"

    res = mp.poll_video(take.polling_url, cfg=provider_config(take))
    cost = delivery.money(res.cost)

    if res.status == mp.VIDEO_COMPLETED:
        # Готово. Ссылки может и не быть — finalize всё равно переспросит за свежей.
        fields = {"lease_until": timezone.now(), "stage": "completed"}
        if cost is not None:
            fields["provider_cost_usd"] = cost
        if Take.objects.transition(take.pk, TAKE_RUNNING, TAKE_SAVING, **fields):
            delivery.journal_stage(take.genlog_id, "completed", f"опросов: {take.poll_count + 1}")
            _enqueue("finalize_take", take.pk)
            return "saving"
        return "skip"

    if res.is_failed:
        message, code = explain_video_error(res.error)
        _close(take, TAKE_RUNNING, TAKE_FAILED, code, message=message,
               error_input=blamed_input(take, code), stage=res.status[:24], cost=cost,
               journal=GenerationLog.STATUS_FAILED, journal_error=res.error or res.status)
        return "failed"

    # Работы этим ключом не видно (чужой/отозванный ключ, работа удалена).
    # Шесть часов ждать такого ответа бессмысленно: после серии подряд — lost,
    # резерв снят, в разбор (ключ дубля остаётся — «Довезти» спросит им же).
    unreachable = res.unreachable
    errors_in_row = int(take.poll_errors or 0) + 1 if unreachable else 0
    if unreachable and errors_in_row >= POLL_UNREACHABLE_MAX:
        logger.error("vstudio take=%s: опрос %s раз подряд http %s — сдаёмся (аккаунт %s, ключ %s)",
                     take.uid, errors_in_row, res.status_code, take.provider_account_id,
                     take.provider_key_fp or "—")
        _close(take, TAKE_RUNNING, TAKE_LOST, "provider_unreachable",
               qs=Take.objects.filter(next_poll_at=claim_until), stage=f"http_{res.status_code}",
               poll_errors=errors_in_row, journal=GenerationLog.STATUS_LOST,
               journal_error=(f"опрос: http {res.status_code} {errors_in_row} раз подряд — "
                              f"работа не видна ключу: {(res.error or '')[:300]}"))
        return "lost"

    # Ещё снимается, или провайдер моргнул (сеть, 5xx) — это не отказ: ролик
    # уже оплачен, спрашиваем дальше. Шесть часов ограничивает sweep.
    later = timezone.now()
    step = poll_step(take, later)
    if unreachable:
        step = max(step, POLL_UNREACHABLE_STEP)
    moved = Take.objects.filter(next_poll_at=claim_until).transition(
        take.pk, TAKE_RUNNING, next_poll_at=later + timedelta(seconds=step - 1),
        poll_count=F("poll_count") + 1, poll_errors=errors_in_row,
        stage=(res.status or take.stage or "")[:24])
    if not moved:
        # Дубль закрыли или цепочку перехватила другая копия — эта гаснет.
        return "skip"
    if res.transient:
        logger.info("vstudio take=%s: опрос не удался (%s%s), повтор через %s с", take.uid,
                    f"http {res.status_code}, подряд {errors_in_row}: " if unreachable else "",
                    (res.error or "")[:120], step)
    if take.genlog_id and _once(f"vstudio:touch:{take.pk}", JOURNAL_TOUCH_S):
        try:
            GenerationLog.objects.filter(pk=take.genlog_id).update(updated_at=later)
        except Exception:
            logger.debug("vstudio take=%s: пульс журнала не записался", take.uid, exc_info=True)
    _enqueue("poll_take", take.pk, countdown=step)
    return "polling"


# ---------------------------------------------------------------- finalize (видео)

def _retry_later(take: Take, *, redeliver: bool, reason: str) -> None:
    """Попытка выдачи не удалась. Дубль остаётся saving: аренда укорачивается,
    sweep повторит (до MAX_SAVE_ATTEMPTS, потом lost). Для «Довезти» — lost как был."""
    now = timezone.now()
    if redeliver:
        Take.objects.transition(take.pk, TAKE_LOST, lease_until=None, stage="redeliver_failed")
        delivery.journal_stage(take.genlog_id, "redeliver_failed", reason)
        logger.warning("vstudio take=%s: довоз не удался: %s", take.uid, reason[:300])
        return
    attempts = max(1, int(take.attempts or 1))
    wait = min(LEASE.total_seconds(), RETRY_BASE_S * 2 ** (attempts - 1))
    Take.objects.transition(take.pk, TAKE_SAVING, lease_until=now + timedelta(seconds=wait),
                            stage="save_retry")
    delivery.journal_stage(take.genlog_id, "save_retry", f"попытка {attempts}: {reason}")
    logger.warning("vstudio take=%s: выдача, попытка %s не удалась: %s", take.uid, attempts,
                   reason[:300])


def finalize(take_id, *, redeliver: bool = False) -> str:
    """Выдача ролика (§6.3, шаг 4). redeliver=True — «Довезти» из админки (lost→done, без списания)."""
    now = timezone.now()
    frm = TAKE_LOST if redeliver else TAKE_SAVING
    claimed = (Take.objects.filter(Q(lease_until__isnull=True) | Q(lease_until__lte=now))
               .transition(take_id, frm, lease_until=now + LEASE, attempts=F("attempts") + 1,
                           stage="redelivering" if redeliver else "saving"))
    if not claimed:
        return "skip"
    take = _load(take_id)
    if take is None or take.kind != Take.KIND_VIDEO:
        return "skip"
    if not take.polling_url:
        if redeliver:
            _retry_later(take, redeliver=True, reason="нет адреса опроса")
        else:
            _close(take, TAKE_SAVING, TAKE_LOST, "save_failed", journal=GenerationLog.STATUS_LOST,
                   journal_error="у дубля нет адреса опроса")
        return "lost"

    cfg = provider_config(take)
    res = mp.poll_video(take.polling_url, cfg=cfg)
    if not res.is_ready:
        if res.is_failed:
            # Провайдер говорил «готово», а теперь — expired/failed: ссылка
            # пропала, оплаченный ролик потерян. Человек не платит, в разбор.
            if redeliver:
                _retry_later(take, redeliver=True, reason=f"провайдер: {res.status} {res.error}")
            else:
                _close(take, TAKE_SAVING, TAKE_LOST, "save_failed",
                       journal=GenerationLog.STATUS_LOST,
                       journal_error=f"при выдаче провайдер ответил {res.status}: {res.error}")
            return "lost"
        _retry_later(take, redeliver=redeliver,
                     reason=f"нет ссылки на ролик ({res.status or res.error or 'пустой ответ'})")
        return "retry"

    cost = delivery.money(res.cost)
    if cost is None:
        cost = take.provider_cost_usd
    try:
        saved = delivery.fetch_video(take, res.urls[0], cfg=cfg)
    except delivery.DeliveryError as exc:
        _retry_later(take, redeliver=redeliver, reason=f"{exc.reason}: {exc}")
        return "retry"

    try:
        outcome = delivery.commit_video(take, saved, cost=cost, free=redeliver)
    except Exception as exc:
        logger.exception("vstudio take=%s: транзакция выдачи упала", take.uid)
        # Ошибка на COMMIT не значит, что COMMIT не прошёл: сервер мог его
        # применить, а ответ потерялся. Стереть файлы оплаченного ролика нельзя.
        landed = delivery_landed(take.pk, saved.file)
        if landed:
            logger.warning("vstudio take=%s: база ответила ошибкой, но выдача записана — "
                           "файлы оставлены", take.uid)
            _after_delivery(take.pk, landed_outcome(take.pk), cost=cost, recovered=redeliver)
            return "done"
        if landed is False:
            delivery.delete_files(*saved.paths)
        _retry_later(take, redeliver=redeliver, reason=f"транзакция: {type(exc).__name__}: {exc}")
        return "retry"
    if not outcome.won:
        # Выдал кто-то другой (вторая копия finalize) или sweep уже закрыл дубль.
        delivery.delete_files(*saved.paths)
        logger.info("vstudio take=%s: выдачу сделал другой — свои файлы стёрты", take.uid)
        return "raced"
    _after_delivery(take.pk, outcome, cost=cost, recovered=redeliver)
    return "done"


def _after_delivery(take_id, outcome, *, cost, recovered: bool) -> None:
    """После коммита: шаг журнала, уведомление, проверка маржи. Никогда не бросает."""
    try:
        take = _load(take_id)
    except Exception:
        logger.warning("vstudio: дубль %s не перечитался после выдачи", take_id, exc_info=True)
        return
    if take is None:
        return
    charge = outcome.charge
    note = ("довезено бесплатно" if recovered
            else f"списано {charge.credits} кр" + (" (частично)" if charge and charge.partial else ""))
    logger.info("vstudio delivered take=%s asset=%s %s", take.uid,
                getattr(outcome.asset, "uid", "?"), note)
    delivery.journal_stage(take.genlog_id, "recovered" if recovered else "delivered", note)
    notify_later(take.pk)
    try:
        from .pricing import check_margin

        check_margin(take, cost_usd=cost)
    except Exception:
        logger.warning("vstudio take=%s: проверка маржи упала", take.uid, exc_info=True)


# ---------------------------------------------------------------- картинка

def run_image(take_id) -> str:
    """Картинка целиком в одной задаче (§6.4): /images синхронный."""
    now = timezone.now()
    if not Take.objects.transition(take_id, TAKE_QUEUED, TAKE_RUNNING, submitted_at=now,
                                   stage="generating"):
        return "skip"
    take = _load(take_id)
    if take is None:
        return "skip"
    if take.kind != Take.KIND_IMAGE:
        _close(take, TAKE_RUNNING, TAKE_FAILED, "internal_error")
        return "failed"

    entry = _start_journal(take)
    if entry.pk is None:
        logger.error("vstudio take=%s: журнал недоступен — провайдеру не отправляем", take.uid)
        _close(take, TAKE_RUNNING, TAKE_FAILED, "journal_unavailable")
        return "failed"
    if not Take.objects.transition(take.pk, TAKE_RUNNING, genlog=entry.pk):
        entry.failed("дубль закрыт до отправки провайдеру")
        return "skip"
    take.genlog_id = entry.pk

    try:
        body = outgoing_body(take.request_body)
    except Exception as exc:
        logger.exception("vstudio take=%s: тело запроса не собралось", take.uid)
        _close(take, TAKE_RUNNING, TAKE_FAILED, "service_misconfigured",
               journal=GenerationLog.STATUS_FAILED, journal_error=f"тело не собралось: {exc}")
        return "failed"

    entry.stage("sending")
    try:
        res = mp.generate_image(body)
    except Exception as exc:  # generate_image не бросает, но исход должен быть всегда
        logger.exception("vstudio take=%s: запрос картинки упал", take.uid)
        res = mp.Images(error=f"{type(exc).__name__}: {exc}")
    cost = delivery.money(res.cost)

    if not res.ok:
        message, code = explain_image_error(res.error)
        # Нет HTTP-ответа или 5xx — провайдер мог и взять деньги: в разбор.
        unknown = res.status_code is None or res.status_code >= 500
        _close(take, TAKE_RUNNING, TAKE_FAILED, code, message=message,
               error_input=blamed_input(take, code), stage="rejected", cost=cost,
               journal=GenerationLog.STATUS_FAILED, journal_error=res.error or message,
               review=unknown)
        return "failed"

    # Файлы — под uid pending-ассета: чип в лотке станет этой картинкой.
    asset_uid = (take.result_asset.uid if take.result_asset_id and take.result_asset
                 else uuid.uuid4().hex)
    try:
        stored = store_image_bytes(take.user_id, asset_uid, res.items[0].decode(), trusted=True)
    except Exception as exc:
        # Провайдер вернул не картинку (битые байты, не тот формат): не выдаём.
        logger.warning("vstudio take=%s: картинка провайдера не читается: %s", take.uid, exc)
        _close(take, TAKE_RUNNING, TAKE_FAILED, "bad_result", stage="bad_result", cost=cost,
               journal=GenerationLog.STATUS_FAILED, journal_error=f"картинка не читается: {exc}")
        return "failed"

    try:
        outcome = delivery.commit_image(take, stored, asset_uid=asset_uid, cost=cost)
    except Exception as exc:
        logger.exception("vstudio take=%s: транзакция выдачи картинки упала", take.uid)
        # Как у видео: COMMIT мог пройти, хотя клиент БД увидел ошибку.
        landed = delivery_landed(take.pk, stored.file)
        if landed:
            logger.warning("vstudio take=%s: база ответила ошибкой, но картинка выдана — "
                           "файлы оставлены", take.uid)
            _after_delivery(take.pk, landed_outcome(take.pk), cost=cost, recovered=False)
            return "done"
        if landed is False:
            delivery.delete_files(*stored.paths)
        _close(take, TAKE_RUNNING, TAKE_FAILED, "save_failed", stage="save_failed", cost=cost,
               message="Не удалось сохранить картинку. Кредиты не списаны — попробуйте ещё раз.",
               journal=GenerationLog.STATUS_FAILED, journal_error=f"выдача упала: {exc}",
               review=True)
        return "failed"
    if not outcome.won:
        delivery.delete_files(*stored.paths)
        logger.info("vstudio take=%s: картинку закрыли раньше (sweep) — файлы стёрты", take.uid)
        return "raced"
    _after_delivery(take.pk, outcome, cost=cost, recovered=False)
    return "done"


# ---------------------------------------------------------------- отмена (для BE-9)

def cancel(take_id) -> bool:
    """queued→canceled (резерв снимается тем же UPDATE). False — уже ушёл в работу.

    Для BE-9 (POST takes/<uid>/cancel/): False → 409 already_submitted.
    """
    take = Take.objects.filter(pk=take_id).first()
    if take is None:
        return False
    moved = Take.objects.transition(take.pk, TAKE_QUEUED, TAKE_CANCELED, stage="canceled")
    if moved:
        _fail_asset(take, "canceled")
        logger.info("vstudio take=%s: отменён в очереди", take.uid)
    return moved


# ---------------------------------------------------------------- «Довезти» (админка)

def admin_redeliver(take_id) -> bool:
    """«Довезти» потерянный ролик: повторный опрос и выдача без списания (lost→done).

    Зовётся из админки внутри точки сохранения её транзакции: только проверяет,
    ставит отметку условным UPDATE и ставит finalize_take после коммита.
    False — отказ (дубль не lost). Исключение с русским текстом — довезти нельзя.
    """
    take = Take.objects.filter(pk=take_id).first()
    if take is None or take.status != TAKE_LOST:
        return False
    if take.kind != Take.KIND_VIDEO:
        raise ValueError("Картинку довезти нельзя: провайдер отдаёт её сразу в ответе, "
                         "забрать повторно нечего.")
    ids = {}
    if not take.polling_url and take.genlog_id:
        # Дубль мог не успеть записать адрес опроса (база моргнула), а журнал — успел.
        row = GenerationLog.objects.filter(pk=take.genlog_id).values("provider_id", "polling_url").first()
        if row and row.get("polling_url"):
            ids = {"polling_url": row["polling_url"][:512],
                   "provider_id": (row.get("provider_id") or take.provider_id or "")[:160]}
    if not (take.polling_url or ids.get("polling_url")):
        raise ValueError("Провайдер не подтвердил приём работы — адреса опроса нет, довозить "
                         "нечего. Найдите генерацию в кабинете OpenRouter по времени и модели.")
    now = timezone.now()
    claimed = (Take.objects.filter(Q(lease_until__isnull=True) | Q(lease_until__lte=now))
               .transition(take.pk, TAKE_LOST, lease_until=now, stage="redeliver", **ids))
    if not claimed:
        raise ValueError("Довоз этого дубля уже идёт — подождите пару минут.")
    pk = take.pk
    transaction.on_commit(lambda: _enqueue("finalize_take", pk, redeliver=True))
    delivery.journal_stage(take.genlog_id, "redeliver", "запрошен довоз из админки")
    logger.warning("vstudio take=%s: запрошен довоз из админки", take.uid)
    return True


# ---------------------------------------------------------------- sweep (§6.5)

def _rows(qs, *fields):
    return list(qs.order_by("pk").values("pk", "uid", "kind", "genlog_id", "result_asset_id",
                                         "shot_id", *fields)[:SWEEP_BATCH])


def _stub(row) -> Take:
    """Лёгкий дубль из values(): _close нужны только pk, uid, вид, журнал и ассет."""
    return Take(pk=row["pk"], uid=row["uid"], kind=row["kind"], genlog_id=row["genlog_id"],
                result_asset_id=row["result_asset_id"], shot_id=row["shot_id"])


def _sweep_queued(now, out) -> None:
    stale = now - QUEUED_REQUEUE_AFTER
    dead = now - QUEUED_TIMEOUT
    for row in _rows(Take.objects.filter(status=TAKE_QUEUED, created_at__lt=stale), "created_at"):
        if row["created_at"] < dead:
            if _close(_stub(row), TAKE_QUEUED, TAKE_FAILED, "queue_timeout",
                      qs=Take.objects.filter(created_at__lt=dead), stage="queue_timeout"):
                out["queue_timeout"] += 1
        elif _once(f"vstudio:requeue:{row['pk']}", REQUEUE_DEDUP_S):
            _enqueue("run_image_take" if row["kind"] == Take.KIND_IMAGE else "submit_take", row["pk"])
            out["requeued"] += 1


def _sweep_submitting(now, out) -> None:
    cutoff = now - SUBMITTING_STALE
    for row in _rows(Take.objects.filter(status=TAKE_SUBMITTING, updated_at__lt=cutoff)):
        if _close(_stub(row), TAKE_SUBMITTING, TAKE_LOST, "submit_unknown",
                  qs=Take.objects.filter(updated_at__lt=cutoff), stage="unknown",
                  journal=GenerationLog.STATUS_LOST,
                  journal_error="отправка зависла дольше 15 минут, исход неизвестен"):
            out["submit_unknown"] += 1


def _give_up_q(cutoff):
    return Q(submitted_at__lt=cutoff) | Q(submitted_at__isnull=True, created_at__lt=cutoff)


def _sweep_running(now, out) -> None:
    hours = max(1, int(getattr(settings, "VSTUDIO_GIVE_UP_HOURS", 6) or 6))
    give_up = now - timedelta(hours=hours)
    video = Take.objects.filter(status=TAKE_RUNNING, kind=Take.KIND_VIDEO)
    # 4. Шесть часов без результата — сдаёмся: lost, человек не платит.
    for row in _rows(video.filter(_give_up_q(give_up))):
        if _close(_stub(row), TAKE_RUNNING, TAKE_LOST, "provider_timeout",
                  qs=Take.objects.filter(_give_up_q(give_up)), stage="timeout",
                  journal=GenerationLog.STATUS_LOST,
                  journal_error=f"провайдер не вернул ролик за {hours} ч"):
            out["provider_timeout"] += 1
    # 3. Цепочка опроса потерялась (рестарт брокера, выкладка) — завести заново.
    late = now - POLL_STALE
    for row in _rows(video.filter(Q(next_poll_at__lt=late) | Q(next_poll_at__isnull=True))):
        if _once(f"vstudio:repoll:{row['pk']}", REQUEUE_DEDUP_S):
            _enqueue("poll_take", row["pk"])
            out["repoll"] += 1
    # 5. Картинка: /images синхронный, дольше 8 минут «идёт» только у умершего воркера.
    image_cutoff = now - IMAGE_TIMEOUT
    images = Take.objects.filter(status=TAKE_RUNNING, kind=Take.KIND_IMAGE).filter(_give_up_q(image_cutoff))
    for row in _rows(images):
        if _close(_stub(row), TAKE_RUNNING, TAKE_LOST, "provider_timeout",
                  qs=Take.objects.filter(_give_up_q(image_cutoff)), stage="timeout",
                  journal=GenerationLog.STATUS_LOST,
                  journal_error="картинка не вернулась за 8 минут (воркер упал?)"):
            out["image_timeout"] += 1


def _sweep_saving(now, out) -> None:
    expired = Q(lease_until__lt=now) | Q(lease_until__isnull=True)
    for row in _rows(Take.objects.filter(status=TAKE_SAVING).filter(expired), "attempts"):
        if row["attempts"] < MAX_SAVE_ATTEMPTS:
            if _once(f"vstudio:refinalize:{row['pk']}", REQUEUE_DEDUP_S):
                _enqueue("finalize_take", row["pk"])
                out["refinalize"] += 1
        elif _close(_stub(row), TAKE_SAVING, TAKE_LOST, "save_failed",
                    qs=Take.objects.filter(expired, attempts__gte=MAX_SAVE_ATTEMPTS),
                    stage="save_failed", journal=GenerationLog.STATUS_LOST,
                    journal_error=f"выдача не удалась за {MAX_SAVE_ATTEMPTS} попыток"):
            out["save_failed"] += 1


_JOURNAL_FOR_TAKE = {
    TAKE_DONE: GenerationLog.STATUS_DELIVERED,
    TAKE_FAILED: GenerationLog.STATUS_FAILED,
    TAKE_CANCELED: GenerationLog.STATUS_FAILED,
    TAKE_LOST: GenerationLog.STATUS_LOST,
}


def _sweep_journal(now, out) -> None:
    """7. Открытые записи журнала студии, чей дубль уже закрыт, — к статусу дубля."""
    rows = list(GenerationLog.objects.filter(
        source=GenerationLog.SOURCE_VSTUDIO, status__in=GenerationLog.OPEN_STATES,
        vstudio_take__status__in=TAKE_CLOSED,
    ).values("pk", "vstudio_take__status", "vstudio_take__credits_charged",
             "vstudio_take__charge_state", "vstudio_take__error_code",
             "vstudio_take__result_asset__file")[:SWEEP_BATCH])
    for row in rows:
        status = _JOURNAL_FOR_TAKE[row["vstudio_take__status"]]
        fields = {"status": status, "updated_at": now}
        if status == GenerationLog.STATUS_DELIVERED:
            if row["vstudio_take__charge_state"] != Take.CHARGE_CHARGED:
                fields["status"] = GenerationLog.STATUS_RECOVERED
            fields["credits_charged"] = int(row["vstudio_take__credits_charged"] or 0)
            path = row["vstudio_take__result_asset__file"]
            if path:
                fields["result_url"] = default_storage.url(path)[:512]
        else:
            fields["error"] = f"сверка с дублем: {row['vstudio_take__error_code'] or status}"
            if status == GenerationLog.STATUS_LOST:
                fields["needs_review"] = True
        if GenerationLog.objects.filter(pk=row["pk"], status__in=GenerationLog.OPEN_STATES).update(**fields):
            delivery.journal_stage(row["pk"], "reconciled", f"дубль: {row['vstudio_take__status']}")
            out["journal_fixed"] += 1


def sweep(now=None) -> dict:
    """Страховка конвейера раз в минуту (§6.5). Замок — чтобы два прогона не шли разом."""
    from collections import Counter

    try:
        locked = cache.add(SWEEP_LOCK_KEY, 1, SWEEP_LOCK_TTL)
    except Exception:
        # Кэш лежит — идём без замка: все переходы условные, двойной прогон безопасен.
        logger.warning("vstudio sweep: замок недоступен, идём без него", exc_info=True)
        locked = None
    if locked is False:
        return {"skipped": 1}
    now = now or timezone.now()
    out: Counter = Counter()
    try:
        for rule in (_sweep_queued, _sweep_submitting, _sweep_running, _sweep_saving, _sweep_journal):
            try:
                rule(now, out)
            except Exception:
                # Одно сломанное правило не должно останавливать остальные.
                logger.exception("vstudio sweep: правило %s упало", getattr(rule, "__name__", rule))
                out["errors"] += 1
    finally:
        if locked:
            try:
                cache.delete(SWEEP_LOCK_KEY)
            except Exception:
                pass
    result = dict(out)
    if result:
        logger.info("vstudio sweep: %s", result)
    return result


# ---------------------------------------------------------------- чистка материалов

def purge_assets(now=None) -> dict:
    """Удалённые больше VSTUDIO_PURGE_DAYS назад и без ссылок — файлы и строка.

    Ссылки — ShotInput (запрос помнит, что ушло модели) и Take.result_asset
    (результат в ленте). Пока они есть, файл живёт: повтор старого кадра и
    «Что ушло модели» должны работать.
    """
    now = now or timezone.now()
    days = max(1, int(getattr(settings, "VSTUDIO_PURGE_DAYS", 30) or 30))
    cutoff = now - timedelta(days=days)
    used_inputs = ShotInput.objects.values("asset_id")
    used_results = Take.objects.filter(result_asset__isnull=False).values("result_asset_id")
    candidates = list(Asset.objects.filter(deleted_at__lt=cutoff)
                      .exclude(pk__in=used_inputs).exclude(pk__in=used_results)
                      .order_by("deleted_at").values("pk", "uid", "file", "thumb")[:PURGE_BATCH])
    purged = kept = 0
    for row in candidates:
        try:
            with transaction.atomic():
                # Ссылка могла появиться между выборкой и удалением (повтор кадра).
                if (ShotInput.objects.filter(asset_id=row["pk"]).exists()
                        or Take.objects.filter(result_asset_id=row["pk"]).exists()):
                    kept += 1
                    continue
                deleted, _ = Asset.objects.filter(pk=row["pk"], deleted_at__lt=cutoff).delete()
        except Exception:
            logger.warning("vstudio purge: материал %s не удалился", row["uid"], exc_info=True)
            kept += 1
            continue
        if deleted:
            # Файлы — после коммита строки: наоборот осталась бы строка без файла.
            delivery.delete_files(row["file"], row["thumb"])
            purged += 1
    if purged or kept:
        logger.info("vstudio purge: удалено %s, оставлено %s", purged, kept)
    return {"purged": purged, "kept": kept}


# ---------------------------------------------------------------- ETA и очередь (§9.6)

def default_eta(model_ref: str, kind: str = Take.KIND_VIDEO) -> int:
    """ETA из реестра caps (семейство модели), пока нет статистики."""
    try:
        from .caps import family_of

        fam = family_of(model_ref)
        if fam is not None and fam.eta_s:
            return int(fam.eta_s)
    except Exception:
        logger.debug("vstudio: ETA семейства не прочиталась для %s", model_ref, exc_info=True)
    return ETA_FALLBACK.get(kind, ETA_FALLBACK[Take.KIND_VIDEO])


def eta_seconds(model_ref: str, kind: str = Take.KIND_VIDEO, *, default: Optional[int] = None,
                now=None) -> int:
    """ETA дубля: медиана submitted→finished выданных дублей модели за 7 дней.

    Не меньше 5 штук, кэш 10 минут; иначе default (BE-9 передаёт caps.eta_s —
    с учётом правки eta_s из админки) или ETA семейства.
    """
    fallback = int(default) if default else default_eta(model_ref, kind)
    key = f"vstudio:eta:{kind}:{model_ref}"
    try:
        cached = cache.get(key)
    except Exception:
        cached = None
    if cached is not None:
        return int(cached) or fallback
    now = now or timezone.now()
    rows = (Take.objects.filter(model_ref=model_ref, kind=kind, status=TAKE_DONE,
                                charge_state=Take.CHARGE_CHARGED, submitted_at__isnull=False,
                                finished_at__gte=now - ETA_WINDOW)
            .order_by("-finished_at").values_list("submitted_at", "finished_at")[:ETA_SAMPLE_LIMIT])
    spans = [max(0.0, (fin - sub).total_seconds()) for sub, fin in rows if sub and fin]
    value = int(round(statistics.median(spans))) if len(spans) >= ETA_MIN_SAMPLES else 0
    try:
        cache.set(key, value, ETA_CACHE_S)
    except Exception:
        pass
    return value or fallback


def _ahead_q(take) -> Q:
    return Q(created_at__lt=take.created_at) | Q(created_at=take.created_at, pk__lt=take.pk)


def queue_position(take) -> Optional[int]:
    """Сколько дублей в очереди впереди (0 — следующий). None — дубль не в очереди."""
    if take is None or take.status != TAKE_QUEUED:
        return None
    return Take.objects.filter(status=TAKE_QUEUED).filter(_ahead_q(take)).count()


def queue_positions(takes: Iterable) -> dict:
    """{uid: позиция} для пачки дублей одним запросом (GET takes/?ids=)."""
    mine = [t for t in takes if getattr(t, "status", None) == TAKE_QUEUED]
    if not mine:
        return {}
    newest = max(t.created_at for t in mine)
    order = list(Take.objects.filter(status=TAKE_QUEUED, created_at__lte=newest)
                 .order_by("created_at", "pk").values_list("pk", flat=True))
    index = {pk: n for n, pk in enumerate(order)}
    return {t.uid: index[t.pk] for t in mine if t.pk in index}


__all__ = [
    "submit", "poll", "finalize", "run_image", "sweep", "purge_assets", "cancel",
    "admin_redeliver", "enqueue_start", "eta_seconds", "default_eta", "queue_position",
    "queue_positions", "blamed_input", "sent_asset_uids", "outgoing_body", "storage_name",
    "poll_step", "ERRORS", "MAX_SAVE_ATTEMPTS", "LEASE", "provider_config", "delivery_landed",
    "POLL_UNREACHABLE_MAX",
]
