"""JSON склейки для страницы /merge (контракт — pricing/CONTRACT_M.md)."""
from __future__ import annotations

from urllib.parse import quote

from django.utils import timezone

from .config import limits
from .models import EDITABLE, MergeProject, MergeUpload
from .services import download_token, render_block, total_duration
from .sources import TYPE_UPLOAD, media_url


def _iso(value):
    return value.isoformat() if value else None


def item_json(item: dict, live: dict | None, gone: frozenset = frozenset()) -> dict:
    """Фрагмент склейки. live — свежая проверка (у черновика и неудачной), иначе
    снимок; gone — свои видео снимка, которых больше нет (удалены, истекли)."""
    kind, ident = item.get("type"), str(item.get("id"))
    source = live.get((kind, ident)) if live is not None else None
    if source is not None:
        card = source.card()
        card.pop("created_at", None)
        return {**card, "available": True}
    available = live is None and not (kind == TYPE_UPLOAD and ident in gone)
    # Пропавший источник не проигрываем: файла может уже не быть.
    url = media_url(item.get("file") or "") if available else ""
    # Своё видео, которого нет, — и без обложки: её файл стёрт вместе с ним.
    poster = "" if kind == TYPE_UPLOAD and not available else media_url(item.get("poster") or "")
    return {
        "type": kind,
        "id": ident,
        "title": item.get("title") or "",
        "subtitle": item.get("subtitle") or "",
        "poster": poster or None,
        "url": url or None,
        "duration_s": item.get("duration_s"),
        "width": item.get("width"),
        "height": item.get("height"),
        "available": available,
    }


def gone_uploads(project: MergeProject, items: list[dict]) -> frozenset:
    """Свои видео в снимке готовой или идущей склейки, которых больше нет.

    Человек удаляет файлы сам (квота просит), а снимок помнит их ссылки: без
    этой сверки ▶ открывал бы 404, а «Изменить и склеить заново» упиралось бы
    в отказ, который из готовой склейки не исправить. Один запрос на склейку.
    """
    if project.status in EDITABLE:
        return frozenset()
    ids = {str(i.get("id")) for i in items if i.get("type") == TYPE_UPLOAD}
    if not ids:
        return frozenset()
    alive = set(MergeUpload.objects.filter(
        user_id=project.user_id, uid__in=ids, status=MergeUpload.STATUS_READY,
        expires_at__gt=timezone.now()).exclude(file="").values_list("uid", flat=True))
    return frozenset(ids - alive)


def _progress(project: MergeProject) -> dict | None:
    if project.status not in MergeProject.ACTIVE:
        return None
    return {"stage": project.progress_stage or "queued", "done": project.progress_done,
            "total": project.progress_total or len(project.items or [])}


def project_brief(project: MergeProject) -> dict:
    """Строка списка «Мои склейки»."""
    items = [i for i in project.items or [] if isinstance(i, dict)]
    return {
        "id": project.uid,
        "title": project.title,
        "status": project.status,
        "aspect": project.aspect,
        "fit": project.fit,
        "fragments": len(items),
        "total_duration_s": total_duration(items),
        "duration_s": project.duration_s,
        "poster_url": project.poster_url or None,
        "error": project.error,
        "error_code": project.error_code or None,
        "error_fragment": project.error_fragment,
        "expires_at": _iso(project.expires_at),
        "created_at": _iso(project.created_at),
        "updated_at": _iso(project.updated_at),
    }


def project_json(project: MergeProject, *, live: dict | None = None, price: int | None = None) -> dict:
    """Вся склейка: фрагменты, состояние, итог, ссылка на скачивание, коротко о звуке."""
    from .audio import MSG_PENDING, summary

    items = [i for i in project.items or [] if isinstance(i, dict)]
    ready = project.status == MergeProject.STATUS_READY and bool(project.result_video)
    download = None
    if ready:
        download = f"/api/merge/{project.uid}/download/?t={quote(download_token(project))}"
    sound = summary(project)
    block = render_block(project, live)
    if block is None and project.status in EDITABLE and sound["pending"]:
        # Голос или музыка ещё делаются: «Склеить» откажет (audio_pending) — кнопка знает заранее.
        block = {"error_code": "audio_pending", "error": MSG_PENDING}
    gone = gone_uploads(project, items) if live is None else frozenset()
    return {
        **project_brief(project),
        "items": [item_json(i, live, gone) for i in items],
        "progress": _progress(project),
        "result_url": project.result_url if ready else None,
        "download_url": download,
        "credits_reserved": project.credits_reserved,
        "credits_charged": project.credits_charged,
        "price_credits": price,
        "can_render": project.status in EDITABLE and block is None,
        "render_block": block,
        "finished_at": _iso(project.finished_at),
        "limits": limits(),
        "audio": sound,
    }


__all__ = ["project_json", "project_brief", "item_json", "gone_uploads"]
