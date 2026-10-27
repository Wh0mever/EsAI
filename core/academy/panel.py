"""EsAI Академия в панели (admin-new «Академия»): курсы и ссылка «Предложить курс».

ТЗ клиента (27.10.2026): курсы ведут без правок кода — добавление, правка,
удаление, обложки, публикация и скрытие, порядок, черновики. Для публикации
нужны обложка, название, преподаватель, описание и корректная ссылка; у
опубликованного курса поле не опустошить — на сайте вышла бы сломанная
карточка.

Как у сцен мультстудии (cartoon.panel), правила живут здесь, а не во вьюхах:
тексты отказов по-русски, журнал действий в одной транзакции с правкой, новое
имя обложки на каждую загрузку и удаление прежней после фиксации. После правки
публичный список сбрасывается.
"""
from __future__ import annotations

import logging
import re
import uuid
from functools import partial

from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.db import transaction
from django.db.models import Max, Q
from django.utils import timezone
from rest_framework import status as http
from rest_framework.exceptions import APIException

from audit.services import log_admin_action

from . import links, public
from .models import Course

logger = logging.getLogger(__name__)

# Своего кода у Академии в журнале нет (список audit.models.ADMIN_ACTIONS
# закрытый): как витрина и сцены, правки идут кодом settings.edit, а что
# меняли — видно по ключу снимка.
LOG_ACTION = "settings.edit"
COURSE_KEY = "academy_course"
ORDER_KEY = "academy_order"

TITLE_MAX = Course._meta.get_field("title").max_length
TEACHER_MAX = Course._meta.get_field("teacher").max_length
DESCRIPTION_MAX = Course._meta.get_field("description").max_length
URL_MAX = Course._meta.get_field("url").max_length
PAGE_SIZE = public.PAGE_SIZE
MAX_COURSES = public.MAX_PUBLIC
SORT_STEP = 10
# Обложка: карточка на телефоне во всю ширину (до ~1290 px на 3x), на
# компьютере треть от 1200 — 1280 по длинной стороне хватает, превью 480.
COVER_MAX_SIDE = 1280
COVER_MIN = (480, 270)
COVER_MAX_BYTES_FALLBACK = 15 * 1024 * 1024

TEXTS = (
    ("title", "Название", TITLE_MAX),
    ("teacher", "Преподаватель", TEACHER_MAX),
    ("description", "Описание", DESCRIPTION_MAX),
)
LABELS = {"title": "Название", "teacher": "Преподаватель", "description": "Описание",
          "url": "Ссылка на курс", "cover": "Обложка"}
# «Чтобы опубликовать, добавьте: …» — в винительном падеже.
ADD_WORDS = {"cover": "обложку", "title": "название", "teacher": "имя преподавателя",
             "description": "описание", "url": "ссылку на курс"}
LOG_FIELDS = ("title", "teacher", "description", "url", "cover", "cover_thumb", "cover_width",
              "cover_height", "is_published", "sort_order")

_WHITESPACE = re.compile(r"\s+")
# Управляющие символы (Postgres не примет NUL) и переключатели направления
# текста: ими в карточке подменяют, что видно, а что нет.
_INVISIBLE = re.compile(r"[\x00-\x1f\x7f-\x9f​‪-‮⁦-⁩﻿]")
_SPACES = re.compile(r" {2,}")


class PanelError(APIException):
    """Отказ панели: {"detail": текст, "code": код, …поля}. DRF откатывает транзакцию запроса."""

    def __init__(self, detail: str, *, code: str = "invalid",
                 status: int = http.HTTP_400_BAD_REQUEST, **extra):
        super().__init__(detail={"detail": detail, "code": code, **extra})
        self.status_code = status


# ---------------------------------------------------------------- что видит панель

def _url(field) -> str:
    try:
        return field.url if field else ""
    except Exception:
        return ""


def _iso(value) -> str | None:
    return value.isoformat() if value else None


def course_state(course: Course, miss: list[str]) -> str:
    """live — на сайте; draft — ни разу не публиковался; hidden — скрыт;
    incomplete — опубликован, но неполон (поправили мимо панели), на сайте его нет."""
    if course.is_published:
        return "incomplete" if miss else "live"
    return "hidden" if course.published_at else "draft"


def _places(courses) -> dict:
    """Где курс стоит на сайте: страница и место на ней (с единицы)."""
    places, n = {}, 0
    for course in courses:
        if course.is_published and not public.missing(course):
            places[course.pk] = {"page": n // PAGE_SIZE + 1, "index": n % PAGE_SIZE + 1}
            n += 1
    return places


def _published_places() -> dict:
    return _places(Course.objects.filter(is_published=True).order_by("sort_order", "id"))


def course_row(course: Course, places: dict | None = None) -> dict:
    if places is None:
        places = _published_places()
    miss = public.missing(course)
    return {
        "id": course.pk,
        "title": course.title,
        "teacher": course.teacher,
        "description": course.description,
        "url": course.url,
        "url_host": links.ascii_host(course.url),
        "cover": _url(course.cover),
        "cover_thumb": _url(course.cover_thumb),
        "cover_width": course.cover_width,
        "cover_height": course.cover_height,
        "is_published": course.is_published,
        "state": course_state(course, miss),
        "missing": miss,
        "sort": course.sort_order,
        "place": places.get(course.pk),
        "published_at": _iso(course.published_at),
        "created_at": _iso(course.created_at),
        "updated_at": _iso(course.updated_at),
    }


def course_rows(courses: list[Course]) -> list[dict]:
    places = _places(courses)
    return [course_row(course, places) for course in courses]


def _cover_max_bytes() -> int:
    try:
        from vstudio import assets

        return int(assets.max_upload_bytes())
    except Exception:
        return COVER_MAX_BYTES_FALLBACK


def limits() -> dict:
    """Границы полей — форме панели, чтобы она проверяла то же, что сервер."""
    return {
        "title": TITLE_MAX, "teacher": TEACHER_MAX, "description": DESCRIPTION_MAX,
        "url": URL_MAX, "suggest_url": links.SUGGEST_MAX,
        "cover_max_bytes": _cover_max_bytes(), "cover_min": list(COVER_MIN),
        "cover_max_side": COVER_MAX_SIDE, "page_size": PAGE_SIZE, "max_courses": MAX_COURSES,
    }


def list_payload() -> dict:
    courses = list(Course.objects.order_by("sort_order", "id"))
    rows = course_rows(courses)
    counts = {"live": 0, "draft": 0, "hidden": 0, "incomplete": 0}
    for row in rows:
        counts[row["state"]] += 1
    return {"results": rows, "suggest_url": public.suggest_url(), "limits": limits(),
            "counts": {**counts, "total": len(rows)}}


def get_course(pk, *, lock: bool = False) -> Course:
    qs = Course.objects.select_for_update() if lock else Course.objects.all()
    course = qs.filter(pk=pk).first()
    if course is None:
        raise PanelError("Курс не найден", code="not_found", status=http.HTTP_404_NOT_FOUND)
    return course


# ---------------------------------------------------------------- проверка полей

def _text(value, name: str, label: str, limit: int) -> str:
    if value is None:
        value = ""
    if not isinstance(value, str):
        raise PanelError(f"{label} — строка", field=name)
    value = _WHITESPACE.sub(" ", value)
    value = _SPACES.sub(" ", _INVISIBLE.sub("", value)).strip()
    if len(value) > limit:
        raise PanelError(f"{label} длиннее {limit} символов", code="too_long", field=name)
    return value


def _link(value) -> str:
    if value is None:
        return ""
    if not isinstance(value, str):
        raise PanelError("Ссылка на курс — строка", field="url")
    try:
        return links.clean_url(value, limit=URL_MAX)
    except links.LinkError as err:
        raise PanelError(err.message, code=err.code, field="url") from None


def clean_fields(data) -> dict:
    """Поля курса из тела запроса. Все проверки — до первой записи; незнакомые ключи не мешают."""
    out: dict = {}
    for name, label, limit in TEXTS:
        if name in data:
            out[name] = _text(data[name], name, label, limit)
    if "url" in data:
        out["url"] = _link(data["url"])
    if "is_published" in data:
        value = data["is_published"]
        # Только настоящий булев: строка "false" из формы не должна опубликовать курс.
        if not isinstance(value, bool):
            raise PanelError("Публикация: true или false", field="is_published")
        out["is_published"] = value
    return out


def _snapshot(course: Course) -> dict:
    out = {}
    for name in LOG_FIELDS:
        value = getattr(course, name)
        out[name] = value.name if hasattr(value, "storage") else value
    return out


# ---------------------------------------------------------------- правки курсов

def create_course(data, *, actor, request=None) -> Course:
    """Новый курс — всегда черновик в конце списка: обложки у него ещё нет."""
    fields = clean_fields(data)
    if fields.pop("is_published", False):
        raise PanelError("Сначала сохраните черновик и загрузите обложку",
                         code="create_published", field="is_published")
    with transaction.atomic():
        if Course.objects.count() >= MAX_COURSES:
            raise PanelError(f"Курсов уже {MAX_COURSES} — удалите ненужные, прежде чем "
                             "добавлять новые", code="too_many")
        top = Course.objects.aggregate(top=Max("sort_order"))["top"] or 0
        course = Course.objects.create(sort_order=top + SORT_STEP, **fields)
        # В журнал — в той же транзакции: не записалось, откатится и курс.
        log_admin_action(actor, LOG_ACTION, target=course, before={COURSE_KEY: None},
                         after={COURSE_KEY: _snapshot(course)}, request=request)
    return course


def edit_course(pk, data, *, actor, request=None) -> Course:
    """Поправить, опубликовать или скрыть. Те же значения — ни записи, ни строки в журнале."""
    new = clean_fields(data)
    if not new:
        raise PanelError("Нечего менять", code="nothing_to_change")
    with transaction.atomic():
        course = get_course(pk, lock=True)
        changed = {name: value for name, value in new.items() if getattr(course, name) != value}
        if not changed:
            return course
        if changed.get("is_published", course.is_published):
            # Проверяется итоговое состояние: поля из того же тела уже применены.
            miss = public.missing(course, {k: v for k, v in changed.items() if k != "is_published"})
            if miss:
                emptied = [name for name in miss if name in changed]
                if course.is_published and emptied:
                    raise PanelError(f"Курс на сайте: «{LABELS[emptied[0]]}» не может быть "
                                     "пустым. Сначала скройте курс",
                                     code="published_empty", field=emptied[0])
                raise PanelError("Чтобы опубликовать, добавьте: "
                                 + ", ".join(ADD_WORDS[name] for name in miss),
                                 code="publish_incomplete", missing=miss)
        if changed.get("is_published") is True:
            changed["published_at"] = timezone.now()
        before = {name: getattr(course, name) for name in changed}
        for name, value in changed.items():
            setattr(course, name, value)
        course.save(update_fields=[*changed, "updated_at"])
        log_admin_action(actor, LOG_ACTION, target=course, before={COURSE_KEY: before},
                         after={COURSE_KEY: changed}, request=request)
    public.drop_cache()
    return course


def delete_course(pk, *, actor, request=None) -> None:
    """Удалить курс; файлы обложки — после фиксации."""
    with transaction.atomic():
        course = get_course(pk, lock=True)
        files = [course.cover.name or "", course.cover_thumb.name or ""]
        # Журнал — до удаления: после него у строки уже нет номера.
        log_admin_action(actor, LOG_ACTION, target=course, before={COURSE_KEY: _snapshot(course)},
                         after={COURSE_KEY: None}, request=request)
        course.delete()
        _drop_later(pk, files)
    public.drop_cache()


def reorder(data, *, actor, request=None) -> list[Course]:
    """Новый порядок всех курсов одним запросом: sort_order = 10, 20, 30…"""
    ids = data.get("ids") if hasattr(data, "get") else None
    if (not isinstance(ids, list) or not ids
            or any(isinstance(i, bool) or not isinstance(i, int) for i in ids)
            or len(set(ids)) != len(ids)):
        raise PanelError("ids — список номеров курсов без повторов", field="ids")
    with transaction.atomic():
        courses = list(Course.objects.select_for_update().order_by("sort_order", "id"))
        before = [course.pk for course in courses]
        if set(before) != set(ids):
            # Курс добавили или удалили, пока список был открыт.
            raise PanelError("Список курсов изменился — обновите страницу и переставьте ещё раз",
                             code="order_stale", status=http.HTTP_409_CONFLICT)
        by_id = {course.pk: course for course in courses}
        if before == ids:
            return courses
        dirty = []
        for n, pk in enumerate(ids, start=1):
            course = by_id[pk]
            if course.sort_order != n * SORT_STEP:
                course.sort_order = n * SORT_STEP
                dirty.append(course)
        Course.objects.bulk_update(dirty, ["sort_order"])
        log_admin_action(actor, LOG_ACTION, before={ORDER_KEY: before}, after={ORDER_KEY: ids},
                         request=request)
    public.drop_cache()
    return [by_id[pk] for pk in ids]


# ---------------------------------------------------------------- обложка

def _own_file(pk, name: str) -> bool:
    # Стираем только то, что дала эта панель этому курсу.
    pattern = rf"academy/covers/{int(pk)}-[0-9a-f]{{8}}(?:-480)?(?:_[A-Za-z0-9]{{7}})?\.(?:jpg|png)"
    return bool(re.fullmatch(pattern, name or ""))


def _delete(names) -> None:
    for name in names:
        try:
            default_storage.delete(name)
        except Exception:
            logger.warning("academy: лишний файл %s не удалился", name, exc_info=True)


def _drop_later(pk, names) -> None:
    """Стереть файлы, на которые курс больше не смотрит, — после фиксации.

    Откатится правка — строка всё ещё смотрит на прежние файлы. Файл, на
    который смотрит другой курс (поправили мимо панели), остаётся.
    """
    names = [name for name in names if _own_file(pk, name)]
    if not names:
        return
    used = set()
    for row in (Course.objects.exclude(pk=pk)
                .filter(Q(cover__in=names) | Q(cover_thumb__in=names))
                .values_list("cover", "cover_thumb")):
        used.update(row)
    names = [name for name in names if name not in used]
    if names:
        transaction.on_commit(partial(_delete, names))


def _single_file(files):
    # Считаем файлы во всех полях: второй под другим именем не должен потеряться молча.
    if hasattr(files, "lists"):
        items = [f for _key, group in files.lists() for f in group]
    else:
        items = [f for f in (files or []) if f is not None]
    if not items:
        raise PanelError("Приложите обложку: картинка JPG, PNG, WebP или HEIC",
                         code="cover_missing", field="cover")
    if len(items) > 1:
        raise PanelError("Загружайте одну обложку за раз", code="cover_many", field="cover")
    return items[0]


def _too_large(limit: int) -> PanelError:
    mb = max(1, round(limit / (1024 * 1024)))
    return PanelError(f"Обложка больше {mb} МБ — уменьшите её", code="cover_too_large",
                      status=http.HTTP_413_REQUEST_ENTITY_TOO_LARGE, field="cover")


def _read_capped(upload, limit: int) -> bytes:
    """Прочитать загрузку, не веря заявленному размеру."""
    size = getattr(upload, "size", None)
    if size is not None and size > limit:
        raise _too_large(limit)
    buf = bytearray()
    for chunk in upload.chunks():
        buf += chunk
        if len(buf) > limit:
            raise _too_large(limit)
    return bytes(buf)


def _cover_error(err) -> PanelError:
    """Отказ нормализатора видеостудии — словами обложки (его тексты — про референсы)."""
    if err.code in ("unsupported_type", "video_refs_unsupported"):
        return PanelError("Обложка — картинка JPG, PNG, WebP или HEIC", code="cover_type",
                          field="cover")
    if err.code == "file_too_large":
        return _too_large(_cover_max_bytes())
    if err.code == "too_many_pixels":
        return PanelError(err.message, code="cover_too_many_pixels",
                          status=http.HTTP_422_UNPROCESSABLE_ENTITY, field="cover")
    if err.code == "throttled":
        return PanelError(err.message, code="cover_busy",
                          status=http.HTTP_429_TOO_MANY_REQUESTS, field="cover")
    return PanelError("Не удалось открыть картинку — файл повреждён или это не изображение",
                      code="cover_bad", status=http.HTTP_422_UNPROCESSABLE_ENTITY, field="cover")


def upload_cover(pk, files, *, actor, request=None) -> Course:
    """Новая обложка: перекодирование без метаданных, новое имя файла, прежняя — после фиксации."""
    # Импорт ленивый: Академия не должна ронять загрузку модулей из-за студии.
    from vstudio import assets

    get_course(pk)
    upload = _single_file(files)
    try:
        assets.upload_extension(getattr(upload, "name", ""), getattr(upload, "content_type", ""))
        blob = _read_capped(upload, _cover_max_bytes())
        image = assets.normalize_image_bytes(blob, max_side=COVER_MAX_SIDE)
    except assets.AssetError as err:
        raise _cover_error(err) from None
    if image.width < COVER_MIN[0] or image.height < COVER_MIN[1]:
        raise PanelError("Обложка слишком маленькая: нужно не меньше 480×270, лучше 1280×720 "
                         "(16:9)", code="cover_too_small", field="cover")
    # Имя всякий раз новое: /media/ кэшируют nginx и Cloudflare на неделю, и
    # под старым адресом сайт показывал бы прежнюю картинку.
    stem = f"academy/covers/{int(pk)}-{uuid.uuid4().hex[:8]}"
    written: list[str] = []
    try:
        cover = default_storage.save(f"{stem}.{image.ext}", ContentFile(image.data))
        written.append(cover)
        thumb = ""
        if image.thumb:
            thumb = default_storage.save(f"{stem}-480.jpg", ContentFile(image.thumb))
            written.append(thumb)
        with transaction.atomic():
            course = get_course(pk, lock=True)
            old = {"cover": course.cover.name or "", "cover_thumb": course.cover_thumb.name or "",
                   "cover_width": course.cover_width, "cover_height": course.cover_height}
            new = {"cover": cover, "cover_thumb": thumb, "cover_width": image.width,
                   "cover_height": image.height}
            for name, value in new.items():
                setattr(course, name, value)
            course.save(update_fields=[*new, "updated_at"])
            log_admin_action(actor, LOG_ACTION, target=course, before={COURSE_KEY: old},
                             after={COURSE_KEY: new}, request=request)
            _drop_later(pk, [old["cover"], old["cover_thumb"]])
    except Exception:
        # Обложка в курс не встала — записанные файлы ничьи.
        _delete(written)
        raise
    public.drop_cache()
    return course


# ---------------------------------------------------------------- ссылка «Предложить курс»

def _forget_suggest() -> None:
    """Забыть ссылку в кэше настроек: следующее чтение пойдёт в базу."""
    try:
        from django.core.cache import cache

        from adminapi.runtime import CACHE_PREFIX

        cache.delete(CACHE_PREFIX + links.SUGGEST_KEY)
    except Exception:
        logger.warning("academy: кэш ссылки «Предложить курс» не сбросился, она обновится "
                       "сама в течение полминуты", exc_info=True)


def set_suggest_url(data, *, actor, request=None) -> str:
    """Записать ссылку кнопки (пусто — кнопки нет). То же значение — без записи и журнала."""
    from adminapi.runtime import delete_runtime, get_runtime, set_runtime

    if not hasattr(data, "get") or "suggest_url" not in data:
        raise PanelError("Нечего менять", code="nothing_to_change")
    try:
        value = links.clean_suggest_url(data["suggest_url"])
    except links.LinkError as err:
        raise PanelError(err.message, code="suggest_invalid", field="suggest_url") from None
    # «Было» читаем мимо кэша настроек: по устаревшему значению настоящая
    # правка сошла бы за повтор и не записалась.
    _forget_suggest()
    before = get_runtime(links.SUGGEST_KEY, "")
    if before == value:
        return value
    with transaction.atomic():
        if value:
            set_runtime(links.SUGGEST_KEY, value)
        else:
            delete_runtime(links.SUGGEST_KEY)
        log_admin_action(actor, LOG_ACTION, before={links.SUGGEST_KEY: before},
                         after={links.SUGGEST_KEY: value}, request=request)
    # Пока транзакция запроса открыта, сосед мог положить в кэш прежнее значение.
    transaction.on_commit(_forget_suggest)
    return value

