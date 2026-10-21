"""Что можно склеивать: свои готовые видео человека в EsAI.

Источник называется парой type + id и всегда ищется на сервере с фильтром по
владельцу — путь к файлу от клиента не принимается никогда (иначе чужой ролик
из /media/ можно было бы вклеить в свой). Чужой, удалённый, недоснятый или
пропавший с диска источник неотличимы: его просто нет.

Виды:
- vstudio        — дубль видеостудии с готовым видео (id — uid дубля);
- cartoon_scene  — снятая сцена мультстудии, со звуком, если он сведён (id сцены);
- cartoon_movie  — собранный мультфильм (id проекта);
- chat           — видео из чата и бота по журналу генераций (id записи журнала).
  Принадлежность видео чата верна только по тому, что записал сервер: журнал
  (с 21.09.2026) хранит владельца и путь выданного ролика. Вложения сообщений
  пишет клиент, им не верим; ролики до журнала в склейку не попадают.
- upload         — своё видео, загруженное в склейку (uid загрузки): принятое,
  не истёкшее. Размеры и длина — из разбора при загрузке, ffprobe не нужен.
"""
from __future__ import annotations

import hashlib
import logging
import os
import re
from collections import defaultdict
from dataclasses import dataclass, field, replace
from datetime import datetime
from urllib.parse import unquote

from django.conf import settings
from django.core.cache import cache
from django.core.files.storage import default_storage

logger = logging.getLogger(__name__)

TYPE_VSTUDIO = "vstudio"
TYPE_SCENE = "cartoon_scene"
TYPE_MOVIE = "cartoon_movie"
TYPE_CHAT = "chat"
TYPE_UPLOAD = "upload"
TYPES = (TYPE_VSTUDIO, TYPE_SCENE, TYPE_MOVIE, TYPE_CHAT, TYPE_UPLOAD)
# Вкладка «Мультстудия» в выборе фрагментов — мультфильмы и сцены вместе.
TAB_CARTOON = "cartoon"
LIST_TYPES = TYPES + (TAB_CARTOON,)

PAGE_SIZE = 24
TITLE_CHARS = 80
# Файлы источников не меняются (имена — uuid), поэтому разбор ffprobe кэшируем
# надолго; неудачу — ненадолго: файл могли дописывать.
PROBE_TTL = 7 * 24 * 3600
PROBE_FAIL_TTL = 10 * 60

# Подпись карточки без промпта и названия — на языке запроса.
FALLBACK_TITLES = {
    TYPE_VSTUDIO: {"ru": "Видео из видеостудии", "en": "Video Studio clip", "kg": "Видеостудиядагы видео"},
    TYPE_SCENE: {"ru": "Сцена", "en": "Scene", "kg": "Көрүнүш"},
    TYPE_MOVIE: {"ru": "Мультфильм", "en": "Cartoon", "kg": "Мультфильм"},
    TYPE_CHAT: {"ru": "Видео из чата", "en": "Chat video", "kg": "Чаттагы видео"},
    TYPE_UPLOAD: {"ru": "Моё видео", "en": "My video", "kg": "Менин видеом"},
}

_HEX32 = re.compile(r"[0-9a-f]{32}")
_DIGITS = re.compile(r"[1-9][0-9]{0,17}")
_SPACES = re.compile(r"\s+")


@dataclass(frozen=True)
class Source:
    """Найденный источник: где лежит файл и что показать на карточке."""

    type: str
    id: str
    title: str
    file: str                       # имя в default_storage
    subtitle: str = ""
    poster: str = ""                # имя в default_storage или ""
    duration_s: float | None = None
    width: int | None = None
    height: int | None = None
    created_at: datetime | None = field(default=None, compare=False)
    # Демуксер для своего видео человека (render.Input); "" — наш файл.
    input_format: str = ""
    # Поля карточки сверх общих (у своих видео — размер и срок хранения).
    extra: dict = field(default_factory=dict, compare=False)

    @property
    def key(self) -> tuple[str, str]:
        return self.type, self.id

    def card(self) -> dict:
        """Карточка для выбора фрагментов (GET sources/)."""
        return {
            "type": self.type,
            "id": self.id,
            "title": self.title,
            "subtitle": self.subtitle,
            "poster": media_url(self.poster) or None,
            "url": media_url(self.file),
            "duration_s": self.duration_s,
            "width": self.width,
            "height": self.height,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            **self.extra,
        }

    def snapshot(self) -> dict:
        """Что хранится в MergeProject.items рядом с type + id."""
        return {"type": self.type, "id": self.id, "title": self.title, "subtitle": self.subtitle,
                "file": self.file, "poster": self.poster, "duration_s": self.duration_s,
                "width": self.width, "height": self.height}


def media_url(name: str) -> str:
    return default_storage.url(name) if name else ""


def valid_id(kind: str, raw) -> str | None:
    """Идентификатор источника в каноническом виде (строка) или None."""
    if isinstance(raw, bool) or raw is None:
        return None
    value = str(raw).strip().lower()
    if kind in (TYPE_VSTUDIO, TYPE_UPLOAD):
        return value if _HEX32.fullmatch(value) else None
    if kind in (TYPE_SCENE, TYPE_MOVIE, TYPE_CHAT):
        return value if _DIGITS.fullmatch(value) else None
    return None


def fallback_title(kind: str, lang: str) -> str:
    table = FALLBACK_TITLES[kind]
    return table.get(lang) or table["ru"]


def short(text: str, limit: int = TITLE_CHARS) -> str:
    """Подпись из промпта: одна строка, без лишних пробелов, не длиннее limit."""
    text = _SPACES.sub(" ", str(text or "")).strip()
    if len(text) <= limit:
        return text
    return text[:limit - 1].rstrip() + "…"


# ---------------------------------------------------------------- файлы и ffprobe

def local_path(name: str) -> str | None:
    """Путь на диске, если хранилище локальное и файл есть."""
    if not name:
        return None
    try:
        path = default_storage.path(name)
    except NotImplementedError:
        return None
    except Exception:
        # Имя вне MEDIA_ROOT (SuspiciousFileOperation) — такого файла для нас нет.
        logger.warning("склейка: путь %s вне хранилища", name, exc_info=True)
        return None
    return path if os.path.isfile(path) else None


def file_exists(name: str) -> bool:
    if not name:
        return False
    try:
        return bool(default_storage.exists(name))
    except Exception:
        logger.warning("склейка: не проверилось наличие %s", name, exc_info=True)
        return False


def _probe_key(name: str) -> str:
    return "merge:probe:" + hashlib.sha1(name.encode("utf-8")).hexdigest()


def media_meta(name: str) -> dict | None:
    """{duration, width, height, audio} файла по ffprobe (с кэшем) или None."""
    key = _probe_key(name)
    hit = cache.get(key)
    if hit is not None:
        return hit or None
    path = local_path(name)
    if not path:
        return None
    from .render import probe

    info = probe(path)
    data = {}
    if info is not None and info.duration and info.video:
        data = {"duration": info.duration, "width": info.width, "height": info.height,
                "audio": info.audio}
    cache.set(key, data, PROBE_TTL if data else PROBE_FAIL_TTL)
    return data or None


def _media_name(url: str, folder: str) -> str:
    """/media/ai_videos/x.mp4 → ai_videos/x.mp4; чужая папка или «..» → ""."""
    url = unquote(str(url or "").split("?", 1)[0])
    prefix = str(getattr(settings, "MEDIA_URL", "/media/") or "/media/")
    if not url.startswith(prefix):
        return ""
    name = url[len(prefix):]
    if not name.startswith(folder) or ".." in name.split("/"):
        return ""
    return name


# ---------------------------------------------------------------- выборки по видам

def _vstudio_qs(user):
    from vstudio.models import Asset, Take

    return (Take.objects.filter(user=user, kind=Take.KIND_VIDEO, status=Take.STATUS_DONE,
                                result_asset__isnull=False,
                                result_asset__kind=Asset.KIND_VIDEO,
                                result_asset__status=Asset.STATUS_READY,
                                result_asset__deleted_at__isnull=True)
            .exclude(result_asset__file="")
            .select_related("result_asset", "shot", "project"))


def _scene_qs(user):
    from cartoon.models import CartoonScene

    return (CartoonScene.objects.filter(project__user=user, status=CartoonScene.STATUS_READY)
            .exclude(video="").select_related("preset", "project"))


def _movie_qs(user):
    from cartoon.models import CartoonProject

    # Неудачная пересборка оставляет прежний готовый ролик (и мультстудия его
    # показывает со «Скачать» и «Открыть в склейке») — это тоже готовое видео.
    # Пока идёт пересборка, файл вот-вот сменится: такой не берём.
    return (CartoonProject.objects.filter(user=user, status__in=(CartoonProject.STATUS_READY,
                                                                 CartoonProject.STATUS_FAILED))
            .exclude(result_video=""))


def _chat_qs(user):
    from ai.models import GenerationLog

    prefix = str(getattr(settings, "MEDIA_URL", "/media/") or "/media/") + "ai_videos/"
    return GenerationLog.objects.filter(
        user=user, kind=GenerationLog.KIND_VIDEO,
        source__in=(GenerationLog.SOURCE_CHAT, GenerationLog.SOURCE_BOT),
        status__in=(GenerationLog.STATUS_DELIVERED, GenerationLog.STATUS_RECOVERED),
        result_url__startswith=prefix)


def _upload_qs(user):
    from django.utils import timezone

    from .models import MergeUpload

    return MergeUpload.objects.filter(user=user, status=MergeUpload.STATUS_READY,
                                      expires_at__gt=timezone.now()).exclude(file="")


def _from_take(take, lang: str) -> Source:
    asset = take.result_asset
    prompt = getattr(take.shot, "prompt_text", "") or ""
    project_title = getattr(take.project, "title", "") or ""
    hint = (take.effective or {}).get("duration") if isinstance(take.effective, dict) else None
    duration = asset.duration_s if asset.duration_s else _number(hint)
    return Source(type=TYPE_VSTUDIO, id=take.uid,
                  title=short(prompt) or short(project_title) or fallback_title(TYPE_VSTUDIO, lang),
                  subtitle=short(project_title), file=asset.file, poster=asset.thumb or "",
                  duration_s=duration, width=asset.width, height=asset.height,
                  created_at=take.finished_at or take.created_at)


def _from_scene(scene, lang: str) -> Source:
    from core.langutils import tr

    title = scene.custom_title or (tr(scene.preset, "title", lang) if scene.preset_id else "")
    return Source(type=TYPE_SCENE, id=str(scene.pk), title=short(title) or fallback_title(TYPE_SCENE, lang),
                  subtitle=short(scene.project.title), file=scene.mixed_video or scene.video,
                  poster=scene.keyframe or "",
                  duration_s=_number(scene.shot_duration or scene.duration),
                  created_at=scene.created_at)


def _from_movie(project, poster: str, lang: str) -> Source:
    return Source(type=TYPE_MOVIE, id=str(project.pk),
                  title=short(project.title) or fallback_title(TYPE_MOVIE, lang),
                  file=project.result_video, poster=poster, created_at=project.updated_at)


def _from_chat(row, poster: str, lang: str) -> Source:
    params = row.params if isinstance(row.params, dict) else {}
    return Source(type=TYPE_CHAT, id=str(row.pk), title=short(row.prompt) or fallback_title(TYPE_CHAT, lang),
                  subtitle=short(row.model, 60), file=_media_name(row.result_url, "ai_videos/"),
                  poster=poster, duration_s=_number(params.get("duration")),
                  created_at=row.created_at)


def _from_upload(row, lang: str) -> Source:
    return Source(type=TYPE_UPLOAD, id=row.uid, title=row.title or fallback_title(TYPE_UPLOAD, lang),
                  file=row.file, poster=row.poster or "", duration_s=row.duration_s,
                  width=row.display_width, height=row.display_height, created_at=row.created_at,
                  input_format=row.container,
                  extra={"size_bytes": row.size, "has_audio": row.has_audio,
                         "expires_at": row.expires_at.isoformat() if row.expires_at else None})


def upload_source(row, lang: str = "ru") -> Source:
    """Карточка своего видео (ответ загрузки и список «Мои файлы»)."""
    return _from_upload(row, lang)


def _number(value) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None


def _movie_posters(project_ids) -> dict:
    """Обложка мультфильма — кадр его первой готовой сцены."""
    from cartoon.models import CartoonScene

    out: dict = {}
    rows = (CartoonScene.objects.filter(project_id__in=list(project_ids),
                                        status=CartoonScene.STATUS_READY)
            .exclude(keyframe="").order_by("project_id", "order", "id")
            .values_list("project_id", "keyframe"))
    for project_id, keyframe in rows:
        out.setdefault(project_id, keyframe)
    return out


def _chat_posters(user, names) -> dict:
    """Обложка видео чата есть, только если им поделились (страница /v/<код>)."""
    from ai.models import SharedVideo

    names = [n for n in names if n]
    if not names:
        return {}
    rows = (SharedVideo.objects.filter(user=user, video_path__in=names)
            .exclude(poster_path="").values_list("video_path", "poster_path"))
    return dict(rows)


def _build(user, kind: str, rows, lang: str) -> list[Source]:
    if kind == TYPE_VSTUDIO:
        return [_from_take(take, lang) for take in rows]
    if kind == TYPE_SCENE:
        return [_from_scene(scene, lang) for scene in rows]
    if kind == TYPE_MOVIE:
        posters = _movie_posters(p.pk for p in rows)
        return [_from_movie(p, posters.get(p.pk, ""), lang) for p in rows]
    if kind == TYPE_UPLOAD:
        return [_from_upload(row, lang) for row in rows]
    names = {row.pk: _media_name(row.result_url, "ai_videos/") for row in rows}
    posters = _chat_posters(user, names.values())
    return [_from_chat(row, posters.get(names[row.pk], ""), lang) for row in rows]


def _qs(user, kind: str):
    return {TYPE_VSTUDIO: _vstudio_qs, TYPE_SCENE: _scene_qs, TYPE_MOVIE: _movie_qs,
            TYPE_CHAT: _chat_qs, TYPE_UPLOAD: _upload_qs}[kind](user)


def _complete(source: Source) -> Source:
    """Длительность и размер — из файла: у сцен и мультфильмов в базе их нет,
    у видео чата длительность в журнале — только нового куска («Продлить»).
    Видеостудия и свои видео знают их из базы (своё — из разбора при загрузке)."""
    if source.type in (TYPE_VSTUDIO, TYPE_UPLOAD):
        if source.duration_s and source.width and source.height:
            return source
        if source.type == TYPE_UPLOAD:
            # Чужой файл без разбора не читаем (разбор при загрузке — строгий).
            return source
    meta = media_meta(source.file)
    if not meta:
        return source
    return replace(source, duration_s=meta.get("duration") or source.duration_s,
                   width=meta.get("width") or source.width,
                   height=meta.get("height") or source.height)


def _usable(sources, check_files: bool) -> list[Source]:
    out = []
    for source in sources:
        if not source.file:
            continue
        if check_files and not file_exists(source.file):
            continue
        out.append(_complete(source))
    return out


# ---------------------------------------------------------------- публичное

def resolve(user, refs, *, lang: str = "ru", check_files: bool = True) -> dict:
    """{(type, id): Source} для доступных человеку источников из refs.

    refs — пары (type, id); недоступные (чужие, удалённые, недоснятые, без
    файла) в ответ не попадают. По одному запросу на вид.
    """
    wanted: dict = defaultdict(set)
    for kind, raw in refs:
        clean = valid_id(kind, raw)
        if clean:
            wanted[kind].add(clean)
    out: dict = {}
    if not getattr(user, "pk", None):
        return out
    for kind, ids in wanted.items():
        qs = _qs(user, kind)
        if kind in (TYPE_VSTUDIO, TYPE_UPLOAD):
            qs = qs.filter(uid__in=ids)
        else:
            qs = qs.filter(pk__in=[int(i) for i in ids])
        for source in _usable(_build(user, kind, list(qs), lang), check_files):
            out[source.key] = source
    return out


def _sort_field(kind: str) -> str:
    return "updated_at" if kind == TYPE_MOVIE else "created_at"


def _window(user, kind: str, stop: int, start: int = 0) -> list:
    field_name = _sort_field(kind)
    return list(_qs(user, kind).order_by(f"-{field_name}", "-pk")[start:stop])


def list_page(user, kind: str, page: int = 1, *, lang: str = "ru",
              page_size: int = PAGE_SIZE) -> dict:
    """Страница карточек для выбора фрагментов, новые сверху.

    has_more считается до проверки файлов: карточка, чей файл пропал с диска,
    просто не показывается, и страница может выйти короче.
    """
    page = max(1, int(page or 1))
    start = (page - 1) * page_size
    stop = start + page_size + 1
    if kind == TAB_CARTOON:
        rows = [(m.updated_at, TYPE_MOVIE, m) for m in _window(user, TYPE_MOVIE, stop)]
        rows += [(s.created_at, TYPE_SCENE, s) for s in _window(user, TYPE_SCENE, stop)]
        rows.sort(key=lambda r: (r[0], r[2].pk), reverse=True)
        chunk = rows[start:stop]
        has_more = len(chunk) > page_size
        chunk = chunk[:page_size]
        built: dict = {}
        for sub in (TYPE_MOVIE, TYPE_SCENE):
            objs = [obj for _, k, obj in chunk if k == sub]
            for source in _build(user, sub, objs, lang):
                built[(sub, source.id)] = source
        ordered = [built[(k, str(obj.pk))] for _, k, obj in chunk]
    else:
        # Одна выборка — срез прямо в базе, а не все строки до нужной страницы.
        objs = _window(user, kind, stop, start)
        has_more = len(objs) > page_size
        ordered = _build(user, kind, objs[:page_size], lang)
    cards = [s.card() for s in _usable(ordered, check_files=True)]
    return {"type": kind, "page": page, "page_size": page_size, "has_more": has_more,
            "results": cards}


__all__ = ["TYPES", "LIST_TYPES", "TAB_CARTOON", "TYPE_VSTUDIO", "TYPE_SCENE", "TYPE_MOVIE",
           "TYPE_CHAT", "TYPE_UPLOAD", "Source", "resolve", "list_page", "valid_id", "media_meta",
           "local_path", "media_url", "short", "file_exists", "upload_source", "fallback_title"]
