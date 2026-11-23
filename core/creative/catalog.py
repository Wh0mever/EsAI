"""Каталоги поставщика для форм: стили, пресеты, опции виртуального блогера.

Списки тянем с сервера поставщика (бесплатные GET), кэшируем у себя на 6 часов,
превью копируем к себе (media/creative/catalog/<kind>/…, JPEG без метаданных),
названия прогоняем через «чистку бренда». В браузер уходят только наши поля
{id, name, preview} и наши адреса превью; ссылки CDN поставщика остаются в
кэше сервера.

Если кэша нет (первый запрос после выкладки), список берётся сразу одним
запросом, а превью докачивает задача sync_catalog — до тех пор preview=null.
"""
from __future__ import annotations

import hashlib
import logging
import os
import re
import tempfile
import time

from django.core.cache import cache
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage

from . import hf
from .storage import catalog_dir, ensure_dir

logger = logging.getLogger(__name__)

KINDS = ("styles-v2", "styles-v1", "restyle", "ms-presets", "influencer")
CACHE_KEY = "creative:catalog:v2:{kind}"   # v2: имя без запасного текста + номер n
CACHE_TTL = 6 * 3600
CACHE_TTL_PARTIAL = 300          # без превью — недолго: задача докачает и перезапишет
SYNC_LOCK_KEY = "creative:catalog:sync:{kind}"
SYNC_LOCK_TTL = 600
PREVIEW_BOX = 480
PREVIEW_MAX_BYTES = 8 * 1024 * 1024
MS_PAGE = 100
MS_MAX_PAGES = 10
INFLUENCER_TIER = "normal"

# Слова-бренды поставщика и его моделей: в названиях стилей их не показываем.
_BRAND_RE = re.compile(
    r"(?i)\b(higgs\s*field|higgsfield|soul\s*id|soul|genjutsu|cinema\s*studio|marketing\s*studio|"
    r"ads\s*studio|ai\s*influencer|gpt\s*image|flare|sunburst|seedance|kling)\b")
_SPACES = re.compile(r"\s+")


def _source(kind: str) -> tuple[str, dict | None]:
    """Путь каталога у поставщика (только сервер)."""
    return {
        "styles-v2": ("v1/text2image/soul-styles/v2", None),
        "styles-v1": ("v1/text2image/soul-styles", None),
        "restyle": ("models/higgsfield/genjutsu/restyle/v1.0/presets", None),
        "ms-presets": ("marketing-studio/image/presets", {"size": MS_PAGE, "cursor": 0}),
        "influencer": ("models/higgsfield/ai-influencer/options", None),
    }[kind]


def clean_name(name, fallback: str = "") -> str:
    text = _BRAND_RE.sub(" ", str(name or ""))
    text = _SPACES.sub(" ", text).strip(" -–—:·,._/|")
    return text[:80] or fallback


def _https(url) -> str:
    return url if isinstance(url, str) and url.startswith("https://") else ""


# ---------------------------------------------------------------- разбор ответов

def _list_items(kind: str, data) -> list[dict]:
    rows = data.get("items") if isinstance(data, dict) else data
    out = []
    for n, row in enumerate(rows or [], 1):
        if not isinstance(row, dict) or not row.get("id"):
            continue
        if kind == "ms-presets":
            cover = row.get("cover_image") if isinstance(row.get("cover_image"), dict) else {}
            src = _https(cover.get("url"))
            meta = row.get("metadata") if isinstance(row.get("metadata"), dict) else {}
            extra = {"aspect": str(meta.get("aspect_ratio") or "")[:8],
                     "group": clean_name(meta.get("group_name"))}
        else:
            src = _https(row.get("preview_url"))
            extra = {}
        # Без имени — пустая строка и номер: подпись «Стиль N» собирает фронт на языке человека.
        out.append({"id": str(row["id"])[:64], "name": clean_name(row.get("name")), "n": n,
                    "src": src, "preview_path": "", **extra})
    return out


def _influencer(data) -> list[dict]:
    cats = data.get("categories") if isinstance(data, dict) else None
    out = []
    for cat in cats or []:
        if not isinstance(cat, dict) or not cat.get("key"):
            continue
        tiers = cat.get("tiers") or []
        if INFLUENCER_TIER not in tiers:
            continue
        options = []
        for opt in cat.get("options") or []:
            if not isinstance(opt, dict) or not opt.get("key"):
                continue
            opt_tiers = opt.get("tiers")
            if opt_tiers and INFLUENCER_TIER not in opt_tiers:
                continue
            color = opt.get("color") if isinstance(opt.get("color"), str) else None
            options.append({"key": str(opt["key"])[:60], "label": clean_name(opt.get("label"), opt["key"]),
                            "color": color if color and re.match(r"^#[0-9a-fA-F]{6}$", color) else None,
                            "exclusive": bool(opt.get("exclusive")), "src": _https(opt.get("img")),
                            "preview_path": ""})
        out.append({"key": str(cat["key"])[:60], "label": clean_name(cat.get("label"), cat["key"]),
                    "max": max(1, int(cat.get("max") or 1)), "options": options})
    return out


def fetch(kind: str):
    """Каталог с сервера поставщика в нашем виде (с src, без превью). Бросает hf.HFError."""
    path, params = _source(kind)
    if kind == "influencer":
        return _influencer(hf.get_json(path))
    if kind == "ms-presets":
        items: list = []
        cursor = 0
        for _ in range(MS_MAX_PAGES):
            data = hf.get_json(path, {**(params or {}), "cursor": cursor})
            items += _list_items(kind, data)
            nxt = data.get("cursor") if isinstance(data, dict) else None
            if nxt in (None, "", cursor):
                break
            cursor = nxt
        return items
    return _list_items(kind, hf.get_json(path, params))


# ---------------------------------------------------------------- превью

def _preview_name(kind: str, src: str) -> str:
    digest = hashlib.sha1(src.encode("utf-8")).hexdigest()[:20]
    return f"{catalog_dir(kind)}/{digest}.jpg"


def copy_preview(kind: str, src: str) -> str:
    """Скопировать превью к себе (JPEG без метаданных). "" — не вышло или ссылки нет."""
    if not src:
        return ""
    name = _preview_name(kind, src)
    try:
        if default_storage.exists(name):
            return name
    except Exception:
        return ""
    from cartoon.thumbs import make_thumb

    fd, tmp = tempfile.mkstemp(prefix="cs-cat-")
    os.close(fd)
    try:
        hf.download(src, tmp, max_bytes=PREVIEW_MAX_BYTES, wall_s=30)
        with open(tmp, "rb") as fh:
            blob = make_thumb(fh.read(), PREVIEW_BOX, quality=82)
        if not blob:
            return ""
        ensure_dir(catalog_dir(kind))
        return default_storage.save(name, ContentFile(blob))
    except Exception:
        logger.info("creative: превью каталога %s не скопировалось", kind, exc_info=True)
        return ""
    finally:
        try:
            os.remove(tmp)
        except OSError:
            pass


def _existing(kind: str, src: str) -> str:
    if not src:
        return ""
    name = _preview_name(kind, src)
    try:
        return name if default_storage.exists(name) else ""
    except Exception:
        return ""


def _fill_previews(kind: str, data, *, download: bool):
    get = (lambda src: copy_preview(kind, src)) if download else (lambda src: _existing(kind, src))
    if kind == "influencer":
        for cat in data:
            for opt in cat["options"]:
                opt["preview_path"] = get(opt.get("src", ""))
    else:
        for item in data:
            item["preview_path"] = get(item.get("src", ""))
    return data


# ---------------------------------------------------------------- кэш

def _key(kind: str) -> str:
    return CACHE_KEY.format(kind=kind)


def cached(kind: str):
    try:
        value = cache.get(_key(kind))
    except Exception:
        return None
    return value.get("data") if isinstance(value, dict) else None


def _store(kind: str, data, ttl: int) -> None:
    try:
        cache.set(_key(kind), {"data": data, "at": int(time.time())}, ttl)
    except Exception:
        logger.warning("creative: каталог %s не лёг в кэш", kind, exc_info=True)


def sync(kind: str) -> int:
    """Задача: свежий каталог + копии превью → кэш на 6 часов. Возвращает число элементов."""
    if kind not in KINDS:
        return 0
    try:
        if not cache.add(SYNC_LOCK_KEY.format(kind=kind), 1, SYNC_LOCK_TTL):
            return 0
    except Exception:
        pass
    try:
        data = _fill_previews(kind, fetch(kind), download=True)
        _store(kind, data, CACHE_TTL)
        return len(data)
    except hf.HFError as exc:
        logger.warning("creative: каталог %s не обновился: %s", kind, exc)
        return 0
    finally:
        try:
            cache.delete(SYNC_LOCK_KEY.format(kind=kind))
        except Exception:
            pass


def get(kind: str):
    """Каталог для формы/проверки: из кэша, иначе сразу с сервера (без скачивания превью).

    None — каталог недоступен. Задача sync_catalog докачает превью.
    """
    if kind not in KINDS:
        return None
    data = cached(kind)
    if data is not None:
        return data
    try:
        data = _fill_previews(kind, fetch(kind), download=False)
    except hf.HFError as exc:
        logger.warning("creative: каталог %s недоступен: %s", kind, exc)
        return None
    _store(kind, data, CACHE_TTL_PARTIAL)
    try:
        from . import tasks

        tasks.sync_catalog.delay(kind)
    except Exception:
        logger.debug("creative: синхронизация каталога не поставилась", exc_info=True)
    return data


def lookup(kind: str):
    """Для registry.validate: множество id (списки) или категории (influencer); None — не знаем."""
    data = get(kind)
    if data is None:
        return None
    if kind == "influencer":
        return data
    return {item["id"] for item in data}


def _url(path: str):
    return default_storage.url(path) if path else None


def public(kind: str) -> dict | None:
    """Каталог для браузера: только наши поля и наши адреса превью."""
    data = get(kind)
    if data is None:
        return None
    if kind == "influencer":
        return {"kind": kind, "categories": [
            {"key": c["key"], "label": c["label"], "max": c["max"],
             "options": [{"key": o["key"], "label": o["label"], "color": o["color"],
                          "exclusive": o["exclusive"], "preview": _url(o["preview_path"])}
                         for o in c["options"]]}
            for c in data]}
    items = []
    for item in data:
        row = {"id": item["id"], "name": item["name"], "preview": _url(item["preview_path"])}
        if not item["name"]:
            row["n"] = item.get("n") or 0
        if kind == "ms-presets":
            row["aspect"] = item.get("aspect") or None
            row["group"] = item.get("group") or None
        items.append(row)
    return {"kind": kind, "items": items}


__all__ = ["KINDS", "get", "lookup", "public", "sync", "fetch", "clean_name", "copy_preview"]
