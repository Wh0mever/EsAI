"""Склейка: проверка фрагментов, запуск с резервом, сама склейка, уборка.

Деньги (решение лида 5–6): при запуске цена встаёт в резерв — это сама строка
склейки (credits_reserved при queued/rendering); списание — только в той же
транзакции, что делает склейку готовой; любой сбой закрывает строку как failed
тем же UPDATE, что обнуляет резерв. Списывать за неудачу нечего — значит, и
возвращать нечего.
"""
from __future__ import annotations

import logging
import os
import shutil
import tempfile
import time
import uuid
from datetime import timedelta

from celery.exceptions import SoftTimeLimitExceeded
from django.contrib.auth import get_user_model
from django.core import signing
from django.core.cache import cache
from django.db import IntegrityError, transaction
from django.db.models import Sum
from django.utils import timezone

from . import render as ffmpeg
from .config import (ASPECTS, DEFAULT_TITLE, FITS, MAX_FRAGMENTS, MAX_PROJECTS, MAX_READY,
                     MAX_TOTAL_S, MIN_FRAGMENTS, RETENTION_DAYS, UPLOAD_MAX_PER_PROJECT,
                     free_daily_limit, localized, price_credits)
from .models import ACTIVE, DELETABLE, EDITABLE, MergeAudio, MergeProject
from .sources import TYPE_UPLOAD, TYPES, local_path, resolve, valid_id
from .storage import (delete_files, ensure_user_dir, result_names, save_file, storage_ready)

logger = logging.getLogger(__name__)

# Причина списания в леджере (plans.TokenTransaction.reason, до 20 символов).
REASON = "merge_video"
# Сумма фрагментов округляется при показе до секунды: 300,4 с на экране — 5:00.
TOTAL_TOLERANCE_S = 0.5
# Длительности в базе и в файле расходятся на доли секунды: задача не роняет
# склейку, которую пропустила проверка при запуске, из-за пары секунд.
RENDER_TOLERANCE_S = 5.0

# Лимиты задачи. Тридцать фрагментов на пять минут ролика на двух ядрах — это
# единицы минут; двадцать — с запасом на очередь ffmpeg и медленный диск.
RENDER_SOFT_LIMIT = 20 * 60
RENDER_HARD_LIMIT = RENDER_SOFT_LIMIT + 60
# Очередь media общая со съёмками мультстудии (до получаса каждая, три места):
# два часа ожидания — уже не очередь, а потерянная задача.
QUEUE_TIMEOUT = timedelta(hours=2)
# Живая склейка не может идти дольше жёсткого лимита задачи.
STALE_RENDER_AFTER = timedelta(seconds=RENDER_HARD_LIMIT) + timedelta(minutes=5)

# Свои видео в запущенной склейке живут не меньше суток: очередь (до 2 ч) и
# работа (до 26 мин) не должны пересечься с уборкой истёкших загрузок.
UPLOAD_RENDER_HOLD = timedelta(days=1)

# Уборка истёкших: пачка и потолок пачек за один запуск (задача — до 5 минут).
PURGE_BATCH = 500
PURGE_MAX_BATCHES = 200

# Счётчик бесплатных склеек: ключ на человека и сутки (по Бишкеку), живёт с запасом
# на смену суток. Он в кэше, а не в строках склеек: удалённая готовая склейка
# иначе возвращала бы попытку, и предел обходился бы «склеил — скачал — удалил».
FREE_USE_PREFIX = "merge:free:"
FREE_USE_TTL = 26 * 3600

DOWNLOAD_SALT = "merge.download"
DOWNLOAD_MAX_AGE = 6 * 3600

MSG_BAD_ITEMS = "Список фрагментов не распознан. Обновите страницу и попробуйте снова."
MSG_BAD_TITLE = "Название — строка не длиннее 140 символов."
MSG_BAD_ASPECT = "Формат склейки: 16:9, 9:16 или 1:1."
MSG_BAD_FIT = "Заполнение кадра: pad (поля) или crop (обрезать)."
MSG_TOO_MANY = "Можно склеить не больше {max} фрагментов."
MSG_TOO_FEW = "Добавьте хотя бы {min} фрагмента, чтобы склеить."
MSG_TOO_MANY_UPLOADS = "В одной склейке — не больше {max} своих видео."
MSG_UNAVAILABLE = ("Фрагмент №{n} недоступен: видео не найдено, удалено или ещё не готово. "
                   "Уберите его из склейки.")
MSG_UNREADABLE = "Фрагмент №{n} не читается — уберите его из склейки."
MSG_TOO_LONG = "Склейка выходит длиннее 5 минут ({total}). Уберите часть фрагментов."
MSG_NOT_FOUND = "Склейка не найдена."
MSG_IN_PROGRESS = "Склейка уже идёт — изменить или удалить её можно после окончания."
MSG_ALREADY_READY = "Эта склейка уже готова. Чтобы изменить фрагменты, начните новую склейку."
MSG_NOT_READY = "Ролик ещё не готов."
MSG_FILE_GONE = "Файл склейки не найден — возможно, истёк срок хранения."
MSG_BUSY = "Уже идёт другая склейка. Дождитесь её окончания и запустите эту."
MSG_PRICE_CHANGED = "Цена изменилась: теперь {credits} кр. Проверьте и нажмите «Склеить» ещё раз."
MSG_FREE_LIMIT = ("Бесплатных склеек на сегодня больше нет: можно {max} в сутки. "
                  "Новую можно будет запустить завтра.")
MSG_STORAGE = ("Склейка сейчас недоступна: на сервере не хватает места. "
               "Попробуйте позже — кредиты не списаны.")
MSG_NO_CREDITS = "Недостаточно кредитов для склейки."
MSG_NO_CREDITS_RESERVED = ("Недостаточно кредитов: часть баланса ждёт оплаты за генерации, "
                           "которые ещё идут. Дождитесь их или пополните баланс.")
MSG_TOO_MANY_PROJECTS = "Слишком много склеек. Удалите ненужные и начните новую."
MSG_TOO_MANY_READY = ("Готовых склеек: {max} — больше хранить нельзя. Скачайте нужные и удалите "
                      "лишние в «Моих склейках», чтобы склеить новую.")
MSG_SOURCE_GONE = ("Фрагмент №{n} пропал, пока склейка ждала очереди. "
                   "Уберите его — кредиты не списаны.")
MSG_RENDER_TOO_LONG = "Склейка выходит длиннее 5 минут. Уберите часть фрагментов — кредиты не списаны."
MSG_FAILED = "Не получилось склеить видео — кредиты не списаны, попробуйте ещё раз."
MSG_QUEUE_DOWN = "Склейка не запустилась — кредиты не списаны, попробуйте ещё раз."
MSG_QUEUE_TIMEOUT = "Склейка не дождалась очереди — кредиты не списаны, попробуйте ещё раз."
MSG_STALE = "Склейка оборвалась — кредиты не списаны, попробуйте ещё раз."


class MergeError(Exception):
    """Отказ API в общем виде {"error", "error_code", …}. Текст — по-русски."""

    def __init__(self, code: str, message: str, status: int = 400, **extra):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = int(status)
        self.extra = extra

    def body(self) -> dict:
        return {"error": self.message, "error_code": self.code, **self.extra}


def _not_found() -> MergeError:
    return MergeError("project_not_found", MSG_NOT_FOUND, 404)


def format_duration(seconds: float) -> str:
    """М:СС, как на экране склейки."""
    total = int(round(float(seconds or 0)))
    return f"{total // 60}:{total % 60:02d}"


def default_title(now=None, lang: str = "ru") -> str:
    date = f"{timezone.localtime(now or timezone.now()):%d.%m}"
    return localized(DEFAULT_TITLE, lang).format(date=date)


# ---------------------------------------------------------------- фрагменты

def parse_items(raw) -> list[tuple[str, str]]:
    """Список [{type, id}] → пары (type, id). Бросает MergeError (400)."""
    if not isinstance(raw, list):
        raise MergeError("bad_request", MSG_BAD_ITEMS, field="items")
    if len(raw) > MAX_FRAGMENTS:
        raise MergeError("too_many_fragments", MSG_TOO_MANY.format(max=MAX_FRAGMENTS),
                         max=MAX_FRAGMENTS)
    refs = []
    for index, item in enumerate(raw):
        if not isinstance(item, dict) or item.get("type") not in TYPES:
            raise MergeError("bad_request", MSG_BAD_ITEMS, field="items", index=index)
        clean = valid_id(item["type"], item.get("id"))
        if clean is None:
            raise MergeError("source_unavailable", MSG_UNAVAILABLE.format(n=index + 1),
                             index=index, type=item["type"], id=str(item.get("id"))[:64])
        refs.append((item["type"], clean))
    return refs


def check_sources(user, refs, *, lang: str = "ru") -> list:
    """Источники по порядку: свои, готовые, с файлом и известной длиной, вместе
    не длиннее MAX_TOTAL_S, своих видео — не больше UPLOAD_MAX_PER_PROJECT.
    Бросает MergeError (400)."""
    if sum(1 for kind, _ in refs if kind == TYPE_UPLOAD) > UPLOAD_MAX_PER_PROJECT:
        # Каждое своё видео — до минуты 4K с телефона: на двух ядрах это минуты работы.
        raise MergeError("too_many_uploads", MSG_TOO_MANY_UPLOADS.format(max=UPLOAD_MAX_PER_PROJECT),
                         max=UPLOAD_MAX_PER_PROJECT)
    found = resolve(user, refs, lang=lang)
    out = []
    for index, key in enumerate(refs):
        source = found.get(key)
        if source is None:
            raise MergeError("source_unavailable", MSG_UNAVAILABLE.format(n=index + 1),
                             index=index, type=key[0], id=key[1])
        if not source.duration_s:
            raise MergeError("source_unreadable", MSG_UNREADABLE.format(n=index + 1),
                             index=index, type=key[0], id=key[1])
        out.append(source)
    total = sum(s.duration_s for s in out)
    if total > MAX_TOTAL_S + TOTAL_TOLERANCE_S:
        raise MergeError("too_long", MSG_TOO_LONG.format(total=format_duration(total)),
                         total_s=round(total, 1), max_s=MAX_TOTAL_S)
    return out


def snapshot(sources) -> list[dict]:
    return [s.snapshot() for s in sources]


def total_duration(items) -> float:
    return round(sum(float(i.get("duration_s") or 0) for i in items or []), 3)


def _clean_title(raw) -> str:
    if raw is None:
        return ""
    if not isinstance(raw, str) or len(raw.strip()) > 140:
        raise MergeError("bad_request", MSG_BAD_TITLE, field="title")
    return raw.strip()


def validate_changes(user, project: MergeProject | None, data: dict, *, lang: str = "ru") -> dict:
    """Проверить правку (title, aspect, fit, items) и вернуть поля для записи.

    Ничего не пишет: отказ любого поля — отказ всей правки. Пустой или
    отсутствующий title у новой склейки — «Склейка DD.MM».
    """
    if not isinstance(data, dict):
        raise MergeError("bad_request", MSG_BAD_ITEMS)
    fields: dict = {}
    if "title" in data:
        fields["title"] = _clean_title(data["title"]) or (project.title if project else "")
    content = any(name in data for name in ("aspect", "fit", "items"))
    if project is not None and content:
        if project.status in ACTIVE:
            raise MergeError("render_in_progress", MSG_IN_PROGRESS, 409)
        if project.status not in EDITABLE:
            raise MergeError("already_ready", MSG_ALREADY_READY, 409)
    if "aspect" in data:
        if data["aspect"] not in ASPECTS:
            raise MergeError("bad_request", MSG_BAD_ASPECT, field="aspect")
        fields["aspect"] = data["aspect"]
    if "fit" in data:
        if data["fit"] not in FITS:
            raise MergeError("bad_request", MSG_BAD_FIT, field="fit")
        fields["fit"] = data["fit"]
    if "items" in data:
        fields["items"] = snapshot(check_sources(user, parse_items(data["items"]), lang=lang))
    if project is not None and content and project.status != MergeProject.STATUS_DRAFT:
        # Изменённая неудачная (или истёкшая) склейка — снова черновик: старая
        # ошибка относится к другому набору фрагментов.
        fields.update(status=MergeProject.STATUS_DRAFT, error="", error_code="",
                      error_fragment=None, progress_stage="", progress_done=0, progress_total=0)
    return fields


def live_sources(user, project: MergeProject, *, lang: str = "ru") -> dict | None:
    """Свежая проверка фрагментов для экрана правки; у готовой и идущей — None
    (показываем снимок, тридцать источников раз в три секунды не перечитываем)."""
    if project.status not in EDITABLE or not project.items:
        return None
    refs = [(i.get("type"), i.get("id")) for i in project.items if isinstance(i, dict)]
    return resolve(user, refs, lang=lang)


def render_block(project: MergeProject, live: dict | None) -> dict | None:
    """Почему эту склейку сейчас нельзя запустить (для кнопки) или None."""
    if project.status not in EDITABLE:
        return None
    items = [i for i in project.items or [] if isinstance(i, dict)]
    if len(items) < MIN_FRAGMENTS:
        return {"error_code": "too_few_fragments", "error": MSG_TOO_FEW.format(min=MIN_FRAGMENTS)}
    total = 0.0
    for index, item in enumerate(items):
        source = live.get((item.get("type"), str(item.get("id")))) if live is not None else None
        if live is not None and source is None:
            return {"error_code": "source_unavailable", "index": index,
                    "error": MSG_UNAVAILABLE.format(n=index + 1)}
        total += float((source.duration_s if source else item.get("duration_s")) or 0)
    if total > MAX_TOTAL_S + TOTAL_TOLERANCE_S:
        return {"error_code": "too_long", "error": MSG_TOO_LONG.format(total=format_duration(total))}
    return None


# ---------------------------------------------------------------- проекты

def get_project(user, uid, *, lock: bool = False) -> MergeProject:
    uid = str(uid or "").strip().lower()
    if len(uid) != 32:
        raise _not_found()
    qs = MergeProject.objects.filter(user=user, uid=uid)
    if lock:
        qs = qs.select_for_update()
    project = qs.first()
    if project is None:
        raise _not_found()
    return project


def create_project(user, data: dict, *, lang: str = "ru") -> MergeProject:
    """Новая склейка. copy_audio_from — uid своей склейки, чей звук перейдёт в новую
    («Изменить и склеить заново», Build MA); чужая или пропавшая — 404."""
    data = data or {}
    kept = MergeProject.objects.filter(user=user).exclude(status=MergeProject.STATUS_EXPIRED)
    if kept.count() >= MAX_PROJECTS:
        raise MergeError("too_many_projects", MSG_TOO_MANY_PROJECTS, 409, max=MAX_PROJECTS)
    source = None
    if isinstance(data, dict) and data.get("copy_audio_from") not in (None, ""):
        source = get_project(user, data["copy_audio_from"])
    fields = validate_changes(user, None, data, lang=lang)
    fields.pop("status", None)
    if not fields.get("title"):
        fields["title"] = default_title(lang=lang)
    project = MergeProject.objects.create(user=user, **fields)
    if source is not None:
        from .audio import copy_audio

        copy_audio(source, project)
    return project


def update_project(user, uid, data: dict, *, lang: str = "ru") -> MergeProject:
    project = get_project(user, uid, lock=True)
    fields = validate_changes(user, project, data or {}, lang=lang)
    if fields:
        for name, value in fields.items():
            setattr(project, name, value)
        project.save(update_fields=[*fields, "updated_at"])
    return project


def delete_project(user, uid) -> None:
    """DELETE <id>/. Нельзя, пока склейка идёт, и пока её голос или музыка делаются
    (в том числе музыка в очереди): провайдер звука уже работает и берёт деньги, а
    заказ удалённой склейки не списался бы — «заказать и удалить» было бы бесплатно
    (MA_FIX4). Заказ не висит вечно: его закрывает его же задача или уборка оборванных."""
    from . import audio

    refusal = None
    with transaction.atomic():
        # Замки — как у запуска и заказа звука (audio.LOCK_ORDER: пользователь, склейка,
        # дорожки): запуск или заказ, пришедшие одновременно, ждут удаления, и проверки
        # ниже не устаревают.
        locked = get_user_model().objects.select_for_update().get(pk=user.pk)
        project = get_project(locked, uid, lock=True)
        # Свой оборванный заказ звука закрываем сразу, а не ждём уборки раз в пять минут.
        # Под замком склейки: дорожки — последние в порядке замков, как у доставки звука.
        audio.fail_stale(project_id=project.pk)
        if project.status not in DELETABLE:
            refusal = MergeError("render_in_progress", MSG_IN_PROGRESS, 409)
        elif audio.pending(project.pk):
            refusal = MergeError("audio_busy", audio.MSG_BUSY, 409)
        else:
            project.delete()
    if refusal is not None:
        # Отказ — уже за блоком: исключение внутри откатило бы и закрытие оборванных заказов
        # выше (их резерв висел бы до уборки). Проверки сделаны под замками, отказу они не нужны.
        raise refusal
    delete_files(project.result_video, project.poster)


# ---------------------------------------------------------------- резерв и списание

def reserved_credits(user) -> int:
    """Кредиты в резерве у склеек человека (в очереди и в работе) и у звука
    склеек, который делается (Build MA).

    Для общих гейтов сайта (vstudio.reserve.total_reserved и все, кто его
    зовёт). Мягко: при сбое 0 и warning, платящего не блокируем.
    """
    if not getattr(user, "pk", None):
        return 0
    try:
        from .audio import reserved as audio_reserved

        with transaction.atomic():
            total = MergeProject.objects.filter(user_id=user.pk, status__in=ACTIVE).aggregate(
                s=Sum("credits_reserved"))["s"]
            total = int(total or 0) + audio_reserved(user.pk)
        return max(0, int(total or 0))
    except Exception:
        logger.warning("склейка: резерв не посчитан, не учтён", exc_info=True)
        return 0


def balance_refusal(balance: int, reserved: int, need: int) -> dict | None:
    """Тело 402 в форме чата (PaywallModal работает без правок) или None."""
    from ai.generation import video_balance_error

    refusal = video_balance_error(int(balance), int(reserved), int(need))
    if refusal is None:
        return None
    refusal["error"] = MSG_NO_CREDITS_RESERVED if reserved > 0 else MSG_NO_CREDITS
    return refusal


def charge(user, amount: int, meta: dict, *, reason: str = REASON) -> tuple[int, bool]:
    """Списать за готовую склейку (или готовый звук склейки — reason merge_voice /
    merge_music): (сколько списано, частично ли).

    Резерв гарантировал остаток, но чат и бот проверяют баланс без замка, а
    возврат платежа может изъять кредиты: тогда берём сколько есть — ролик
    человек получает в любом случае, работа уже сделана.
    """
    from plans.wallet import InsufficientTokens, charge_tokens, clawback_tokens

    amount = int(amount or 0)
    if amount <= 0:
        return 0, False
    try:
        charge_tokens(user, amount, reason, meta=meta)
        return amount, False
    except InsufficientTokens as exc:
        got = clawback_tokens(user, amount, reason=reason,
                              meta={**meta, "partial": True, "wanted": amount,
                                    "balance_before": int(exc.balance or 0)})
        logger.warning("склейка %s: списано частично %s из %s", meta.get("merge"), got, amount)
        return int(got or 0), True


# ---------------------------------------------------------------- бесплатный предел

def _free_key(user_id: int, now=None) -> str:
    return f"{FREE_USE_PREFIX}{user_id}:{timezone.localdate(now).isoformat()}"


def free_used(user_id: int, now=None) -> int:
    """Сколько бесплатных склеек человек запустил сегодня. Кэш недоступен — 0:
    предел — защита сервера, а не деньги, и склейку из-за него не запираем."""
    try:
        return int(cache.get(_free_key(user_id, now)) or 0)
    except Exception:
        logger.warning("склейка: счётчик бесплатных не прочитался user=%s", user_id, exc_info=True)
        return 0


def _count_free_use(user_id: int, now=None) -> None:
    """Засчитать запуск бесплатной склейки. Сбой счёта и неудачная склейка попытку
    не возвращают: работа сервера на неё уже ушла."""
    key = _free_key(user_id, now)
    try:
        cache.add(key, 0, FREE_USE_TTL)
        cache.incr(key)
    except Exception:
        logger.warning("склейка: бесплатный запуск не засчитан user=%s", user_id, exc_info=True)


# ---------------------------------------------------------------- запуск

def fail_stale(user=None, now=None) -> dict:
    """Закрыть склейки, чья задача потерялась (очередь, деплой, убитый воркер).

    Денег не трогаем: списания не было, резерв обнуляет тот же UPDATE.
    Условно по отметке времени: ожившая задача свою склейку не потеряет.
    """
    now = now or timezone.now()
    qs = MergeProject.objects.all() if user is None else MergeProject.objects.filter(user=user)
    out = {"queued": 0, "rendering": 0}
    for row in qs.filter(status=MergeProject.STATUS_QUEUED,
                         queued_at__lt=now - QUEUE_TIMEOUT).only("pk", "queued_at")[:200]:
        out["queued"] += MergeProject.objects.filter(
            pk=row.pk, status=MergeProject.STATUS_QUEUED, queued_at=row.queued_at).update(
            status=MergeProject.STATUS_FAILED, error=MSG_QUEUE_TIMEOUT, error_code="queue_timeout",
            error_fragment=None, credits_reserved=0, progress_stage="", finished_at=now,
            updated_at=now)
    for row in qs.filter(status=MergeProject.STATUS_RENDERING,
                         render_started_at__lt=now - STALE_RENDER_AFTER).only(
            "pk", "render_started_at")[:200]:
        out["rendering"] += MergeProject.objects.filter(
            pk=row.pk, status=MergeProject.STATUS_RENDERING,
            render_started_at=row.render_started_at).update(
            status=MergeProject.STATUS_FAILED, error=MSG_STALE, error_code="stale",
            error_fragment=None, credits_reserved=0, progress_stage="", finished_at=now,
            updated_at=now)
    if out["queued"] or out["rendering"]:
        logger.warning("склейка: закрыты оборвавшиеся %s", out)
    return out


def _enqueue(project_pk: int) -> None:
    """Поставить задачу после коммита. Брокер недоступен — склейка закрывается
    сразу (резерв снят), а не висит два часа до уборки."""
    from .tasks import render_merge

    try:
        render_merge.delay(project_pk)
    except Exception:
        logger.exception("склейка %s: задача не поставилась", project_pk)
        now = timezone.now()
        MergeProject.objects.filter(pk=project_pk, status=MergeProject.STATUS_QUEUED).update(
            status=MergeProject.STATUS_FAILED, error=MSG_QUEUE_DOWN, error_code="queue_down",
            error_fragment=None, credits_reserved=0, progress_stage="", finished_at=now,
            updated_at=now)


def start_render(user, uid, data: dict | None = None, *, lang: str = "ru") -> tuple[MergeProject, bool]:
    """POST <id>/render/: (склейка, поставлена ли сейчас). Бросает MergeError.

    Порядок: уборка своих оборвавшихся → замок строки пользователя (два
    запуска разом выстраиваются в очередь) → склейка → правка из тела, если
    есть → проверка фрагментов заново → «одна склейка в работе» → готовых не
    больше MAX_READY → цена из тела против текущей → бесплатная — не больше
    суточного предела → хранилище → свободный остаток (баланс минус все резервы
    сайта) → queued с резервом. Любой отказ откатывает всё, включая правку.
    Повторный клик по уже идущей склейке — (она же, False), без второго резерва.
    """
    data = data if isinstance(data, dict) else {}
    fail_stale(user=user)
    with transaction.atomic():
        locked = get_user_model().objects.select_for_update().get(pk=user.pk)
        project = get_project(locked, uid, lock=True)
        if project.status in ACTIVE:
            return project, False
        if project.status == MergeProject.STATUS_READY:
            raise MergeError("already_ready", MSG_ALREADY_READY, 409)
        edits = {k: data[k] for k in ("title", "aspect", "fit", "items") if k in data}
        fields = validate_changes(locked, project, edits, lang=lang) if edits else {}
        for name, value in fields.items():
            setattr(project, name, value)

        refs = [(i.get("type"), str(i.get("id"))) for i in project.items or []
                if isinstance(i, dict)]
        if len(refs) < MIN_FRAGMENTS:
            raise MergeError("too_few_fragments", MSG_TOO_FEW.format(min=MIN_FRAGMENTS),
                             min=MIN_FRAGMENTS)
        sources = check_sources(locked, refs, lang=lang)
        from . import audio

        if audio.pending(project.pk):
            # Голос или музыка ещё делаются (и оплачиваются): без них склейка вышла бы не той.
            raise MergeError("audio_pending", audio.MSG_PENDING, 409)

        other = (MergeProject.objects.filter(user=locked, status__in=ACTIVE)
                 .exclude(pk=project.pk).values_list("uid", flat=True).first())
        if other:
            raise MergeError("busy", MSG_BUSY, 409, active_id=other)
        ready = (MergeProject.objects.filter(user=locked, status=MergeProject.STATUS_READY)
                 .exclude(pk=project.pk).count())
        if ready >= MAX_READY:
            raise MergeError("too_many_ready", MSG_TOO_MANY_READY.format(max=MAX_READY), 409,
                             max=MAX_READY)

        price = price_credits()
        if "price" in data and data["price"] is not None:
            try:
                expected = int(data["price"])
            except (TypeError, ValueError):
                expected = None
            if expected != price:
                raise MergeError("price_changed", MSG_PRICE_CHANGED.format(credits=price), 409,
                                 credits=price)
        # Предел — только у бесплатной: платную ограничивает баланс.
        free_limit = free_daily_limit() if price == 0 else 0
        if free_limit and free_used(locked.pk) >= free_limit:
            raise MergeError("free_limit", MSG_FREE_LIMIT.format(max=free_limit), 429,
                             max=free_limit)

        ok, why = storage_ready(locked.pk)
        if not ok:
            logger.error("склейка: хранилище не примет результат user=%s: %s", locked.pk, why)
            raise MergeError("storage_unavailable", MSG_STORAGE, 503)

        if price > 0:
            from vstudio.reserve import total_reserved

            # Склейки total_reserved тоже считает, но своих в резерве здесь нет
            # (одна в работе на человека — выше): цена не войдёт в резерв дважды.
            reserved = total_reserved(locked, strict=True)
            refusal = balance_refusal(int(locked.token_balance or 0), reserved, price)
            if refusal:
                raise MergeError(refusal.pop("error_code"), refusal.pop("error"), 402, **refusal)

        now = timezone.now()
        from .uploads import hold, upload_ids

        project.items = snapshot(sources)
        hold(locked.pk, upload_ids(project.items), now + UPLOAD_RENDER_HOLD)
        audio.hold(project.pk, now + UPLOAD_RENDER_HOLD)
        project.status = MergeProject.STATUS_QUEUED
        project.credits_reserved = price
        project.credits_charged = 0
        project.queued_at = now
        project.render_started_at = None
        project.finished_at = None
        project.error = ""
        project.error_code = ""
        project.error_fragment = None
        project.progress_stage = "queued"
        project.progress_done = 0
        project.progress_total = len(sources)
        try:
            with transaction.atomic():
                project.save()
        except IntegrityError:
            # Гонка мимо замка (другой процесс без него): индекс «одна в работе».
            raise MergeError("busy", MSG_BUSY, 409) from None
        if free_limit:
            # Под замком строки пользователя: два запуска разом не проскочат предел вдвоём.
            _count_free_use(locked.pk, now)
        transaction.on_commit(lambda pk=project.pk: _enqueue(pk))
    return project, True


# ---------------------------------------------------------------- задача

class _Gone(Exception):
    """Склейку удалили или закрыли уборкой, пока шла работа."""


def _progress(mine):
    def report(stage: str, done: int, total: int) -> None:
        try:
            mine.update(progress_stage=stage, progress_done=min(done, 32767),
                        progress_total=min(total, 32767), updated_at=timezone.now())
        except Exception:
            logger.warning("склейка: ход не записался", exc_info=True)

    return report


def _materialize(sources, workdir: str) -> list:
    """Файлы фрагментов: на локальном диске — сами файлы, иначе копия. Своё
    видео человека — render.Input с демуксером: ffmpeg читает его строго."""
    from django.core.files.storage import default_storage

    paths = []
    for index, source in enumerate(sources):
        path = local_path(source.file)
        if path is None:
            ext = os.path.splitext(source.file)[1] or ".mp4"
            path = os.path.join(workdir, f"src{index:03d}{ext}")
            with default_storage.open(source.file, "rb") as src, open(path, "wb") as dst:
                shutil.copyfileobj(src, dst, 1024 * 1024)
        paths.append(ffmpeg.Input(path, source.input_format) if source.input_format else path)
    return paths


def _discard(project_pk: int, names: list[str]) -> None:
    """Стереть файлы прерванной выдачи — кроме тех, что уже записаны в склейку.

    Мягкий лимит Celery может прилететь сразу после коммита _finish: склейка
    уже готова и оплачена, и стереть её ролик — списать за пустоту. Не узнали,
    что записано, — не стираем: лишний файл дешевле оплаченного ролика без файла.
    """
    names = [n for n in names if n]
    if not names:
        return
    try:
        kept = set(MergeProject.objects.filter(pk=project_pk)
                   .values_list("result_video", "poster").first() or ())
    except Exception:
        logger.warning("склейка %s: не проверилось, чьи файлы, не стираю %s", project_pk, names,
                       exc_info=True)
        return
    delete_files(*[n for n in names if n not in kept])


def _fail(mine, message: str, code: str = "failed", fragment: int | None = None) -> bool:
    now = timezone.now()
    return bool(mine.update(status=MergeProject.STATUS_FAILED, error=str(message)[:500],
                            error_code=code[:40], error_fragment=fragment, credits_reserved=0,
                            progress_stage="", finished_at=now, updated_at=now))


def _finish(project_pk: int, user_id: int, started, *, video: str, poster: str,
            duration: float, fragments: int) -> int:
    """Готово: списание и запись итога одной транзакцией. Бросает _Gone."""
    now = timezone.now()
    with transaction.atomic():
        # Тот же порядок замков, что у запуска (пользователь → склейка): иначе
        # клик «Склеить» во время выдачи мог бы встать с ней во взаимную блокировку.
        user = get_user_model().objects.select_for_update().filter(pk=user_id).first()
        row = (MergeProject.objects.select_for_update()
               .filter(pk=project_pk, status=MergeProject.STATUS_RENDERING,
                       render_started_at=started).first())
        if user is None or row is None:
            raise _Gone()
        charged, _partial = charge(user, row.credits_reserved,
                                   {"merge": row.uid, "fragments": fragments,
                                    "duration_s": round(duration, 1)})
        expires = now + timedelta(days=RETENTION_DAYS)
        MergeProject.objects.filter(pk=row.pk).update(
            status=MergeProject.STATUS_READY, result_video=video, poster=poster,
            duration_s=round(duration, 3), credits_charged=charged, credits_reserved=0,
            expires_at=expires, finished_at=now, error="",
            error_code="", error_fragment=None, progress_stage="", progress_done=fragments,
            progress_total=fragments, updated_at=now)
        # Свои видео готовой склейки хранятся, пока хранится она сама: её
        # фрагменты остаются видны, и «склеить заново» не упрётся в пустоту.
        # Звук — так же: «Изменить и склеить заново» копирует его в новую склейку.
        from . import audio
        from .uploads import hold, upload_ids

        hold(user_id, upload_ids(row.items), expires)
        audio.hold(row.pk, expires)
    return charged


def run_render(project_id: int, *, soft_limit: float | None = RENDER_SOFT_LIMIT) -> dict:
    """Тело задачи render_merge. Ошибки не роняют задачу, а пишутся в склейку."""
    started = timezone.now()
    if not MergeProject.objects.filter(pk=project_id, status=MergeProject.STATUS_QUEUED).update(
            status=MergeProject.STATUS_RENDERING, render_started_at=started,
            progress_stage="preparing", progress_done=0, updated_at=started):
        return {"status": "not_queued"}
    project = MergeProject.objects.filter(pk=project_id).first()
    if project is None:
        return {"status": "gone"}
    mine = MergeProject.objects.filter(pk=project_id, status=MergeProject.STATUS_RENDERING,
                                       render_started_at=started)
    # Свой срок чуть раньше мягкого лимита Celery: ffmpeg прервётся сам, и
    # человек прочитает «слишком долго», а не общий сбой.
    deadline = time.monotonic() + soft_limit - 30 if soft_limit else None
    saved: list[str] = []
    try:
        refs = [(i.get("type"), str(i.get("id"))) for i in project.items or [] if isinstance(i, dict)]
        found = resolve(project.user, refs)
        sources = []
        for index, key in enumerate(refs):
            source = found.get(key)
            if source is None:
                raise ffmpeg.RenderError(MSG_SOURCE_GONE.format(n=index + 1), f"нет источника {key}",
                                         code="source_gone", fragment=index + 1)
            sources.append(source)
        if len(sources) < MIN_FRAGMENTS:
            raise ffmpeg.RenderError(MSG_TOO_FEW.format(min=MIN_FRAGMENTS), "мало фрагментов",
                                     code="too_few_fragments")
        if sum(s.duration_s or 0 for s in sources) > MAX_TOTAL_S + RENDER_TOLERANCE_S:
            raise ffmpeg.RenderError(MSG_RENDER_TOO_LONG, "длиннее предела", code="too_long")
        ensure_user_dir(project.user_id)
        with tempfile.TemporaryDirectory(prefix="merge-") as workdir:
            paths = _materialize(sources, workdir)
            from .audio import mix_for

            # Звук (Build MA) — только если он есть: без него вызов тот же, что и раньше.
            mix = mix_for(project, workdir, sum(s.duration_s or 0 for s in sources))
            extra = {"audio": mix} if mix is not None else {}
            result = ffmpeg.render(paths, aspect=project.aspect, fit=project.fit, workdir=workdir,
                                   progress=_progress(mine), deadline=deadline, **extra)
            if result.duration > MAX_TOTAL_S + RENDER_TOLERANCE_S:
                raise ffmpeg.RenderError(MSG_RENDER_TOO_LONG, f"итог {result.duration} с",
                                         code="too_long")
            poster_tmp = os.path.join(workdir, "poster.jpg")
            has_poster = ffmpeg.make_poster(result.path, poster_tmp, result.duration)
            _progress(mine)("saving", len(sources), len(sources))
            video_name, poster_name = result_names(project.user_id, project.uid, uuid.uuid4().hex[:8])
            saved.append(save_file(video_name, result.path))
            if has_poster:
                saved.append(save_file(poster_name, poster_tmp))
        charged = _finish(project.pk, project.user_id, started, video=saved[0],
                          poster=saved[1] if len(saved) > 1 else "", duration=result.duration,
                          fragments=len(sources))
        return {"status": "ready", "charged": charged}
    except _Gone:
        logger.warning("склейка %s: удалена или закрыта до выдачи", project_id)
        _discard(project_id, saved)
        return {"status": "gone"}
    except SoftTimeLimitExceeded:
        _discard(project_id, saved)
        _fail(mine, ffmpeg.MSG_TOO_SLOW, "too_slow")
        return {"status": "timeout"}
    except ffmpeg.RenderError as exc:
        logger.warning("склейка %s не получилась: %s (%s)", project_id, exc.message, exc.detail)
        _discard(project_id, saved)
        _fail(mine, exc.message, exc.code, exc.fragment)
        return {"status": "failed"}
    except Exception:
        logger.exception("склейка %s упала", project_id)
        _discard(project_id, saved)
        _fail(mine, MSG_FAILED)
        return {"status": "failed"}


# ---------------------------------------------------------------- хранение

def purge_expired(now=None, *, batch: int = PURGE_BATCH) -> int:
    """Стереть ролики, чей срок хранения вышел; строка остаётся как «истекла».

    Пачками до пустой: за сутки может истечь больше одной пачки, и без
    повтора файлы жили бы дольше обещанных 30 дней. Звук склейки (Build MA)
    истекает вместе с ней.

    У готовой склейки звук не делается (запуск ждёт звук, а заказ звука делает
    склейку черновиком). Если бы делался — склейку не трогаем до следующего
    запуска: заказ к тому времени закроет его задача или уборка оборванных
    (голос — 10 мин, музыка — до 2 ч в очереди и 16 мин в работе), а под
    работающей задачей ничего не стираем.
    """
    from .audio import drop

    now = now or timezone.now()
    count = 0
    expiring = (MergeProject.objects.filter(status=MergeProject.STATUS_READY)
                .exclude(audio_tracks__status=MergeAudio.STATUS_PENDING))
    for _ in range(PURGE_MAX_BATCHES):
        rows = list(expiring.filter(expires_at__lt=now)
                    .order_by("expires_at").only("pk", "expires_at", "result_video", "poster")[:batch])
        for row in rows:
            if expiring.filter(pk=row.pk, expires_at=row.expires_at).update(
                    status=MergeProject.STATUS_EXPIRED, result_video="", poster="", updated_at=now):
                delete_files(row.result_video, row.poster)
                drop(row.pk)
                count += 1
        if len(rows) < batch:
            break
    if count:
        logger.info("склейка: стёрто истёкших %s", count)
    return count


def download_token(project: MergeProject) -> str:
    return signing.dumps({"p": project.uid, "u": project.user_id}, salt=DOWNLOAD_SALT)


def token_user_id(token: str, uid: str) -> int | None:
    """Владелец из подписанной ссылки скачивания или None (подделка, срок, чужая склейка)."""
    try:
        data = signing.loads(str(token or ""), salt=DOWNLOAD_SALT, max_age=DOWNLOAD_MAX_AGE)
    except signing.BadSignature:
        return None
    if not isinstance(data, dict) or data.get("p") != uid:
        return None
    try:
        return int(data.get("u"))
    except (TypeError, ValueError):
        return None


def download_name(project: MergeProject) -> str:
    when = timezone.localtime(project.finished_at or project.updated_at or timezone.now())
    return f"EsAI-merge-{when:%Y-%m-%d}.mp4"
