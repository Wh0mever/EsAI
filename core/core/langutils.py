"""Язык витрины и выбор переведённого поля.

Контент, который правит клиент, хранится в базе по образцу статей блога —
отдельным полем на язык (`title_en`, `name_kg` и т.п.). Логика «какой язык
показать и что делать, если перевода нет» одна и та же для библиотеки студии
и для пакетов кредитов, поэтому живёт здесь, а не копией в каждом приложении.
"""
from __future__ import annotations

SUPPORTED = ("ru", "en", "kg")


def request_lang(request) -> str:
    """Язык витрины: сначала явный ?lang= с фронта, потом Accept-Language.

    Фронт знает выбранный язык лучше браузера — человек мог переключить его
    руками, — поэтому параметр важнее заголовка.
    """
    raw = ""
    params = getattr(request, "query_params", None)
    if params is not None:
        raw = (params.get("lang") or "").strip().lower()
    elif hasattr(request, "GET"):
        raw = (request.GET.get("lang") or "").strip().lower()

    if raw in SUPPORTED:
        return raw

    header = (request.META.get("HTTP_ACCEPT_LANGUAGE") or "").lower()
    if header.startswith(("ky", "kg")):
        return "kg"
    if header.startswith("en"):
        return "en"
    return "ru"


def tr(obj, field: str, lang: str) -> str:
    """Перевод поля с откатом на русский.

    Пустой перевод хуже родного текста: незаполненное поле в админке не должно
    оборачиваться пустой строкой на витрине.
    """
    if lang in ("en", "kg"):
        value = (getattr(obj, f"{field}_{lang}", "") or "").strip()
        if value:
            return value
    return getattr(obj, field, "") or ""
