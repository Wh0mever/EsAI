"""Что Академия показывает на сайте: курсы и «Предложить курс» (ссылка, e-mail или текст).

Курсов десятки, поэтому API отдаёт все опубликованные разом, а по 9 на
страницу их режет Next: один адрес — один ключ кэша, и перебор ?page=1…10⁶
не плодит ни запросов в базу, ни записей в кэше fetch (замечание критика A2).
"""
from __future__ import annotations

import logging

from django.core.cache import cache
from django.db import transaction

from . import links
from .models import Course

logger = logging.getLogger(__name__)

PAGE_SIZE = 9
# Потолок и списка на сайте, и числа курсов в панели (panel.MAX_COURSES).
MAX_PUBLIC = 500
CACHE_KEY = "academy:courses:v1"
# Короткий: правка в панели сбрасывает кэш сразу, а правка мимо панели
# (shell) видна через минуту.
CACHE_S = 60
REQUIRED = ("cover", "title", "teacher", "description", "url")


def _url(field) -> str:
    try:
        return field.url if field else ""
    except Exception:
        return ""


def missing(course: Course, overrides: dict | None = None) -> list[str]:
    """Чего не хватает для публикации, в порядке формы. overrides — значения после правки."""
    values = {name: getattr(course, name) for name in ("title", "teacher", "description", "url")}
    values.update(overrides or {})
    out = [] if course.cover else ["cover"]
    out += [name for name in ("title", "teacher", "description")
            if not str(values[name] or "").strip()]
    if not links.valid_course_url(values["url"]):
        out.append("url")
    return out


def public_qs():
    return (Course.objects.filter(is_published=True)
            .exclude(title="").exclude(teacher="").exclude(description="")
            .exclude(url="").exclude(cover="")
            .order_by("sort_order", "id"))


def public_courses() -> list[Course]:
    """Опубликованные и полные курсы в порядке панели — то, что видит сайт."""
    return [course for course in public_qs()[:MAX_PUBLIC] if not missing(course)]


def public_json(course: Course) -> dict:
    # Адреса обложек относительные: SSR ходит в core по http://core:8000, и
    # абсолютный адрес указал бы туда.
    return {
        "id": course.pk,
        "title": course.title,
        "teacher": course.teacher,
        "description": course.description,
        "url": course.url,
        "cover": _url(course.cover),
        "cover_thumb": _url(course.cover_thumb),
        "cover_width": course.cover_width,
        "cover_height": course.cover_height,
    }


def suggest() -> links.Suggest | None:
    """«Предложить курс»: ссылка, e-mail или текст; None — на сайте ничего. Не бросает никогда.

    Чтение — в savepoint, как у витрины видеостудии: сбой запроса к настройкам
    не должен ломать транзакцию запроса. Значение разбирается заново: строку
    в базе могли поправить мимо панели.
    """
    try:
        from adminapi.runtime import get_runtime

        with transaction.atomic():
            raw = get_runtime(links.SUGGEST_KEY, "")
    except Exception:
        logger.debug("academy: «Предложить курс» не прочиталось", exc_info=True)
        return None
    return links.safe_suggest(raw)


def suggest_fields(item: links.Suggest | None) -> dict:
    """suggest — сайту; suggest_url (href или "") — страницам, собранным до появления suggest."""
    return {"suggest_url": (item.href or "") if item else "",
            "suggest": item.as_json() if item else None}


def public_payload() -> dict:
    """Ответ публичного API. Список курсов — из кэша; «Предложить курс» — у настроек свой кэш."""
    try:
        results = cache.get(CACHE_KEY)
    except Exception:
        results = None
    if not isinstance(results, list):
        results = [public_json(course) for course in public_courses()]
        try:
            cache.set(CACHE_KEY, results, CACHE_S)
        except Exception:
            pass
    return {"count": len(results), "page_size": PAGE_SIZE, "results": results,
            **suggest_fields(suggest())}


def _forget() -> None:
    try:
        cache.delete(CACHE_KEY)
    except Exception:
        logger.warning("academy: кэш курсов не сбросился, сайт обновится сам через %s с",
                       CACHE_S, exc_info=True)


def drop_cache() -> None:
    """Забыть список после фиксации: раньше сосед собрал бы кэш из ещё не изменённой базы."""
    transaction.on_commit(_forget)
