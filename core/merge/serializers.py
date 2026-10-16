"""JSON склейки для страницы /merge (контракт — pricing/CONTRACT_M.md)."""
from __future__ import annotations

from urllib.parse import quote

from .config import limits
from .models import EDITABLE, MergeProject
from .services import download_token, render_block, total_duration
from .sources import media_url


def _iso(value):
    return value.isoformat() if value else None


def item_json(item: dict, live: dict | None) -> dict:
    """Фрагмент склейки. live — свежая проверка (у черновика и неудачной), иначе снимок."""
    kind, ident = item.get("type"), str(item.get("id"))
    source = live.get((kind, ident)) if live is not None else None
    if source is not None:
        card = source.card()
        card.pop("created_at", None)
        return {**card, "available": True}
    # Пропавший источник не проигрываем: файла может уже не быть.
    url = media_url(item.get("file") or "") if live is None else ""
    return {
        "type": kind,
        "id": ident,
        "title": item.get("title") or "",
        "subtitle": item.get("subtitle") or "",
        "poster": media_url(item.get("poster") or "") or None,
        "url": url or None,
        "duration_s": item.get("duration_s"),
        "width": item.get("width"),
        "height": item.get("height"),
        "available": live is None,
    }


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
    """Вся склейка: фрагменты, состояние, итог, ссылка на скачивание."""
    items = [i for i in project.items or [] if isinstance(i, dict)]
    ready = project.status == MergeProject.STATUS_READY and bool(project.result_video)
    download = None
    if ready:
        download = f"/api/merge/{project.uid}/download/?t={quote(download_token(project))}"
    block = render_block(project, live)
    return {
        **project_brief(project),
        "items": [item_json(i, live) for i in items],
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
    }


__all__ = ["project_json", "project_brief", "item_json"]
