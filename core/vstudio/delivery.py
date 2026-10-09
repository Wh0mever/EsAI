"""Выдача результата дубля: файлы, одна транзакция done+charged и журнал (§6.3–6.4).

Порядок у видео (finalize_take):
1. fetch_video — скачать ролик во временный файл, снять размеры и постер,
   положить mp4 и превью в default_storage. Всё это ДО транзакции: скачивание
   идёт до 3 минут, держать столько открытую транзакцию и замок строки нельзя.
2. commit_video — одна транзакция: условный UPDATE saving→done и
   reserved→charged, строка Asset, списание, ссылки на дубле, прямой UPDATE
   журнала, подъём проекта в «Истории».
3. Проиграли условный UPDATE (параллельная выдача, sweep уже закрыл дубль) —
   транзакция ничего не пишет, а вызывающий стирает СВОИ файлы.

Картинка (run_image_take) — то же, только файлы готовит нормализатор загрузок
(vstudio.assets.store_image_bytes), а ассет уже есть в pending.

Журнал в транзакции выдачи обновляется прямым UPDATE, без fail-open помощников
genlog.Entry: result_url нужен ai.handlers._user_owns_video, иначе «Поделиться»
ответит 403 на собственный ролик человека. Если UPDATE упадёт, откатится вся
выдача — дубль останется в saving, и её повторят.
"""
from __future__ import annotations

import logging
import os
import tempfile
import uuid
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import NamedTuple, Optional

from django.core.files import File
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.db import transaction
from django.utils import timezone

from ai import media_provider as mp
from ai.models import GenerationLog

from .assets import delete_files, user_dir
from .models import (
    CHARGE_CHARGED, CHARGE_RESERVED, TAKE_DONE, TAKE_LOST, TAKE_RUNNING, TAKE_SAVING, Asset,
    Project, Take,
)
from .reserve import Charge, charge_on_delivery, reason_for

logger = logging.getLogger(__name__)

# Потолки скачивания ролика (§6.2): дольше 3 минут или больше 300 МБ — сбой
# попытки, а не бесконечно занятый слот воркера.
MAX_VIDEO_BYTES = 300 * 1024 * 1024
DOWNLOAD_WALL_S = 180
# Постер ролика: карточка ленты шире плитки библиотеки, 480 px на ретине мылит.
POSTER_BOX = 720
# ffprobe и постер берут ролик байтами (ai.video_edit). Больше этого в память
# не читаем: четыре слота воркера × 300 МБ — это гигабайт ОЗУ. Такой ролик
# выдаём без размеров и постера — плеер справится и так.
PROBE_MAX_BYTES = 64 * 1024 * 1024
VIDEO_MIME = "video/mp4"
PROMPT_META_CHARS = 2000


class DeliveryError(RuntimeError):
    """Попытка выдачи не удалась, файлов после неё не осталось.

    reason: download_<причина media_provider> | not_video | save.
    """

    def __init__(self, reason: str, message: str = ""):
        super().__init__(message or reason)
        self.reason = reason


@dataclass(frozen=True)
class SavedVideo:
    """Ролик уже лежит в default_storage, строки Asset ещё нет."""

    asset_uid: str
    file: str
    thumb: str
    bytes: int
    width: Optional[int]
    height: Optional[int]
    duration_s: Optional[float]

    @property
    def paths(self) -> list[str]:
        return [p for p in (self.file, self.thumb) if p]


class Delivered(NamedTuple):
    """Итог транзакции выдачи. won=False — выдал кто-то другой, файлы стереть."""

    won: bool
    asset: Optional[Asset] = None
    charge: Optional[Charge] = None


NOT_WON = Delivered(False)


def money(value) -> Optional[Decimal]:
    """usage.cost провайдера → Decimal(10,4) для provider_cost_usd; мусор → None."""
    if value in (None, ""):
        return None
    try:
        out = Decimal(str(value)).quantize(Decimal("0.0001"))
    except (InvalidOperation, ValueError, TypeError):
        return None
    return out if out >= 0 else None


# ---------------------------------------------------------------- журнал

def journal_close(genlog_id, status: str, *, error: str = "", review: bool = False, cost=None,
                  stage: str = "", note: str = "") -> bool:
    """Закрыть ОТКРЫТУЮ запись журнала (failed | lost) условным UPDATE.

    Для путей отказа: запись уже могли закрыть (общий довоз чата помечает
    зависшие SUBMITTING как lost через 15 минут) — второй раз не трогаем.
    Никогда не бросает: сбой журнала на пути отказа подберёт sweep (§6.5, п. 7).
    """
    if not genlog_id:
        return False
    fields = {"status": status, "error": str(error or "")[:2000], "updated_at": timezone.now()}
    if review or status == GenerationLog.STATUS_LOST:
        fields["needs_review"] = True
    amount = money(cost)
    if amount is not None:
        fields["provider_cost_usd"] = amount
    try:
        with transaction.atomic():
            closed = GenerationLog.objects.filter(
                pk=genlog_id, status__in=GenerationLog.OPEN_STATES).update(**fields)
    except Exception:
        logger.warning("vstudio: журнал %s не закрылся (%s)", genlog_id, status, exc_info=True)
        return False
    if closed:
        journal_stage(genlog_id, stage or status, note or error)
    return bool(closed)


def journal_stage(genlog_id, stage: str, note: str = "") -> None:
    """Шаг в ходе записи журнала (stages, как genlog.Entry.stage). Никогда не бросает.

    Своя точка сохранения, а не Entry._save: зовётся и внутри транзакции
    админки («Довезти»), где проглоченная ошибка запроса сломала бы на
    Postgres всю транзакцию («current transaction is aborted»).
    """
    if not genlog_id:
        return
    try:
        now = timezone.now()
        with transaction.atomic():
            row = GenerationLog.objects.filter(pk=genlog_id).values("stages").first()
            if row is None:
                return
            steps = list(row["stages"] or [])
            steps.append({"at": now.isoformat(timespec="seconds"), "stage": str(stage)[:40],
                          "note": str(note or "")[:300]})
            GenerationLog.objects.filter(pk=genlog_id).update(stages=steps[-40:], updated_at=now)
    except Exception:
        logger.debug("vstudio: шаг журнала %s не записался", stage, exc_info=True)


def _deliver_journal(take: Take, *, result_url: str, credits: int, cost, review: bool,
                     recovered: bool, now) -> None:
    """Прямой UPDATE журнала внутри транзакции выдачи (бросает — откатит выдачу)."""
    status = GenerationLog.STATUS_RECOVERED if recovered else GenerationLog.STATUS_DELIVERED
    fields = {"status": status, "credits_charged": max(0, int(credits or 0)),
              "result_url": str(result_url or "")[:512], "needs_review": bool(review),
              "updated_at": now}
    amount = money(cost)
    if amount is not None:
        fields["provider_cost_usd"] = amount
    if take.genlog_id and GenerationLog.objects.filter(pk=take.genlog_id).update(**fields):
        return
    # Записи нет (журнал удалили руками или она не привязалась) — без неё не
    # сработает «Поделиться»: владение роликом проверяется по result_url.
    row = GenerationLog.objects.create(
        user_id=take.user_id, kind=take.kind, source=GenerationLog.SOURCE_VSTUDIO,
        model=str(take.model_ref or "")[:120], prompt=str(take.serialized_prompt or "")[:20000],
        params={"take": take.uid, "mode": take.mode}, credits_planned=take.credits_reserved,
        provider_id=take.provider_id, polling_url=take.polling_url,
        stages=[{"at": now.isoformat(timespec="seconds"), "stage": "restored",
                 "note": "запись журнала пересоздана при выдаче"}],
        **fields)
    Take.objects.filter(pk=take.pk).update(genlog=row, updated_at=now)
    take.genlog_id = row.pk


def _charge(take: Take, cost) -> Charge:
    return charge_on_delivery(
        take.user, take.credits_reserved, reason_for(take.kind),
        meta={"take": take.uid, "genlog": take.genlog_id, "model": take.model_ref,
              "provider_cost_usd": money(cost)})


# ---------------------------------------------------------------- видео

def _looks_like_markup(path: str) -> bool:
    """HTML/JSON вместо ролика (страница ошибки с кодом 200): не выдаём и не берём денег."""
    try:
        with open(path, "rb") as fh:
            head = fh.read(64)
    except OSError:
        return True
    return head.lstrip(b"\xef\xbb\xbf \t\r\n")[:1] in (b"<", b"{", b"[")


def fetch_video(take: Take, url: str, *, max_bytes: int = MAX_VIDEO_BYTES,
                wall_s: float = DOWNLOAD_WALL_S, cfg: Optional[dict] = None) -> SavedVideo:
    """Скачать ролик и положить в default_storage: vstudio/<user_id>/<uid>.mp4 и <uid>_t.jpg.

    cfg — ключ, которым работа отправлена (pipeline.provider_config): контент
    OpenRouter отдаёт только принявшему работу аккаунту.
    Бросает DeliveryError; при любом сбое свои файлы уже стёрты.
    """
    from ai import video_edit
    from cartoon.thumbs import make_thumb

    asset_uid = uuid.uuid4().hex
    fd, tmp = tempfile.mkstemp(prefix="vstudio-", suffix=".mp4")
    os.close(fd)
    saved: list[str] = []
    try:
        try:
            size = mp.download_to_file(url, tmp, max_bytes=max_bytes, wall_s=wall_s, cfg=cfg)
        except mp.DownloadError as exc:
            raise DeliveryError(f"download_{exc.reason}", str(exc)) from exc
        if _looks_like_markup(tmp):
            raise DeliveryError("not_video", "вместо ролика пришла разметка")
        # ffprobe/ffmpeg: размеры для плеера и постер. Без них ролик всё равно
        # выдаём — это оформление, а не сам результат.
        info = {}
        poster = None
        if size <= PROBE_MAX_BYTES:
            with open(tmp, "rb") as fh:
                data = fh.read()
            try:
                info = video_edit.probe_video(data) or {}
            except Exception:
                logger.warning("vstudio take=%s: ffprobe упал", take.uid, exc_info=True)
            try:
                poster = video_edit.extract_poster(data)
            except Exception:
                logger.warning("vstudio take=%s: постер не извлёкся", take.uid, exc_info=True)
            del data
        else:
            logger.warning("vstudio take=%s: ролик %s байт — без размеров и постера", take.uid, size)
        thumb_blob = make_thumb(poster, POSTER_BOX) if poster else None

        base = f"{user_dir(take.user_id)}/{asset_uid}"
        with open(tmp, "rb") as fh:
            saved.append(default_storage.save(f"{base}.mp4", File(fh)))
        thumb = ""
        if thumb_blob:
            thumb = default_storage.save(f"{base}_t.jpg", ContentFile(thumb_blob))
            saved.append(thumb)
        duration = info.get("duration")
        return SavedVideo(asset_uid=asset_uid, file=saved[0], thumb=thumb, bytes=int(size),
                          width=info.get("width"), height=info.get("height"),
                          duration_s=float(duration) if duration else None)
    except DeliveryError:
        delete_files(*saved)
        raise
    except Exception as exc:
        delete_files(*saved)
        raise DeliveryError("save", f"{type(exc).__name__}: {exc}") from exc
    finally:
        try:
            os.remove(tmp)
        except OSError:
            pass


def commit_video(take: Take, saved: SavedVideo, *, cost=None, free: bool = False) -> Delivered:
    """Транзакция выдачи ролика (§6.3, шаг 5).

    free=False — обычная выдача: saving→done только при charge_state=reserved,
    списание credits_reserved (или «сколько есть», partial → needs_review).
    free=True — «Довезти» из админки: lost→done, резерв уже снят, списания нет
    (credits_charged=0), журнал — recovered.

    Проиграли условный UPDATE → Delivered(won=False), в БД ничего не записано;
    файлы стирает вызывающий. Любое исключение откатывает всё.
    """
    now = timezone.now()
    amount = money(cost)
    done = {"lease_until": None, "next_poll_at": None, "stage": "done",
            "error": "", "error_code": "", "error_input": ""}
    if amount is not None:
        done["provider_cost_usd"] = amount
    with transaction.atomic():
        if free:
            won = Take.objects.transition(take.pk, TAKE_LOST, TAKE_DONE, credits_charged=0, **done)
        else:
            won = Take.objects.filter(charge_state=CHARGE_RESERVED).transition(
                take.pk, TAKE_SAVING, TAKE_DONE, charge_state=CHARGE_CHARGED, **done)
        if not won:
            return NOT_WON
        asset = Asset.objects.create(
            uid=saved.asset_uid, user_id=take.user_id, project_id=take.project_id,
            kind=Asset.KIND_VIDEO, source=Asset.SOURCE_GENERATED_VIDEO, status=Asset.STATUS_READY,
            file=saved.file, thumb=saved.thumb, mime=VIDEO_MIME, bytes=saved.bytes,
            width=saved.width, height=saved.height, duration_s=saved.duration_s,
            origin_take_id=take.pk,
            meta={"prompt": str(take.serialized_prompt or "")[:PROMPT_META_CHARS],
                  "model": take.model_ref, "take": take.uid})
        charge = Charge(0, False) if free else _charge(take, amount)
        Take.objects.filter(pk=take.pk).update(result_asset=asset, credits_charged=charge.credits,
                                               updated_at=now)
        _deliver_journal(take, result_url=asset.url, credits=charge.credits, cost=amount,
                         review=charge.partial, recovered=free, now=now)
        Project.touch(take.project_id, now)
    return Delivered(True, asset, charge)


# ---------------------------------------------------------------- картинка

class _AssetMoved(RuntimeError):
    """Ассет картинки уже не pending — выдачу откатываем (не должно случаться)."""


def commit_image(take: Take, stored, *, asset_uid: str, cost=None) -> Delivered:
    """Транзакция выдачи картинки (§6.4, шаг 5): running→done и reserved→charged,
    Asset pending→ready, списание vstudio_image, прямой UPDATE журнала.

    stored — vstudio.assets.StoredImage (файлы уже записаны). asset_uid — uid
    pending-ассета дубля (или новый, если ассета почему-то нет).
    """
    now = timezone.now()
    amount = money(cost)
    done = {"lease_until": None, "stage": "done", "error": "", "error_code": "", "error_input": ""}
    if amount is not None:
        done["provider_cost_usd"] = amount
    meta_extra = {"prompt": str(take.serialized_prompt or "")[:PROMPT_META_CHARS],
                  "model": take.model_ref, "take": take.uid}
    with transaction.atomic():
        won = Take.objects.filter(charge_state=CHARGE_RESERVED).transition(
            take.pk, TAKE_RUNNING, TAKE_DONE, charge_state=CHARGE_CHARGED, **done)
        if not won:
            return NOT_WON
        fields = stored.asset_fields()
        if take.result_asset_id:
            current = Asset.objects.filter(pk=take.result_asset_id).values("meta").first() or {}
            meta = {**(current.get("meta") or {}), **meta_extra}
            updated = Asset.objects.filter(pk=take.result_asset_id, status=Asset.STATUS_PENDING).update(
                status=Asset.STATUS_READY, error_code="", meta=meta, **fields)
            if not updated:
                raise _AssetMoved(f"ассет дубля {take.uid} уже не pending")
            asset = Asset.objects.get(pk=take.result_asset_id)
        else:
            asset = Asset.objects.create(
                uid=asset_uid, user_id=take.user_id, project_id=take.project_id,
                kind=Asset.KIND_IMAGE, source=Asset.SOURCE_GENERATED_IMAGE,
                status=Asset.STATUS_READY, origin_take_id=take.pk, meta=meta_extra, **fields)
        charge = _charge(take, amount)
        Take.objects.filter(pk=take.pk).update(result_asset=asset, credits_charged=charge.credits,
                                               updated_at=now)
        _deliver_journal(take, result_url=asset.url, credits=charge.credits, cost=amount,
                         review=charge.partial, recovered=False, now=now)
        Project.touch(take.project_id, now)
    return Delivered(True, asset, charge)


__all__ = [
    "DeliveryError", "SavedVideo", "Delivered", "fetch_video", "commit_video", "commit_image",
    "journal_close", "journal_stage", "money", "MAX_VIDEO_BYTES", "DOWNLOAD_WALL_S", "POSTER_BOX",
]
