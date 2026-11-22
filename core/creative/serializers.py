"""Ответы API Creative Studio. Только наши поля: ни имени поставщика, ни его ссылок,
ни тела запроса (request_body), ни себестоимости."""
from __future__ import annotations

import re

from django.core.files.storage import default_storage

from .models import JOB_OPEN, CreativeCharacter, CreativeJob

UID_RE = re.compile(r"^[0-9a-f]{32}$")
CLIENT_REQUEST_ID_RE = re.compile(r"^[A-Za-z0-9_.:\-]{1,64}$")

# Какие параметры показываем в «Моих работах» (наши имена полей формы).
PUBLIC_PARAM_KEYS = (
    "prompt", "brief", "name", "style", "preset", "resolution", "quality", "aspect", "count",
    "duration", "audio", "genre", "era", "light", "pacing", "camera_movement", "niche",
    "audience", "language", "options", "video", "image", "images", "product_images", "photos",
    "character",
)


def is_uid(value) -> bool:
    return isinstance(value, str) and bool(UID_RE.match(value))


def _url(path) -> str | None:
    return default_storage.url(path) if path else None


def _iso(value):
    return value.isoformat() if value else None


def params_public(params) -> dict:
    if not isinstance(params, dict):
        return {}
    return {k: params[k] for k in PUBLIC_PARAM_KEYS if k in params}


def results_json(files) -> list[dict]:
    out = []
    for item in files or []:
        if not isinstance(item, dict) or not item.get("path"):
            continue
        out.append({"url": _url(item["path"]), "mime": item.get("mime") or "",
                    "w": item.get("w"), "h": item.get("h"), "poster": _url(item.get("poster")),
                    "duration": item.get("duration")})
    return out


def job_json(job: CreativeJob) -> dict:
    return {
        "uid": job.uid,
        "tool": job.tool_slug,
        "kind": job.kind,
        "status": job.status,
        "stage": job.stage if job.status in JOB_OPEN else "",
        "credits_quoted": job.credits_quoted,
        "credits_reserved": job.credits_reserved if job.status in JOB_OPEN else 0,
        "credits_charged": job.credits_charged,
        "created_at": _iso(job.created_at),
        "finished_at": _iso(job.finished_at),
        "error_code": job.error_code or None,
        "error": job.error or None,
        "results": results_json(job.result_files) if job.status == "done" else [],
        "params_public": params_public(job.params),
    }


def character_json(ch: CreativeCharacter) -> dict:
    return {"uid": ch.uid, "name": ch.name, "status": ch.status, "thumb": _url(ch.thumb_path),
            "created_at": _iso(ch.created_at)}


__all__ = ["job_json", "character_json", "params_public", "results_json", "is_uid",
           "CLIENT_REQUEST_ID_RE"]
