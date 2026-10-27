# -*- coding: utf-8 -*-
"""Общее для тестов Академии: кэш и хранилище в памяти, готовые курсы, картинки."""
from io import BytesIO

from django.core.cache import cache
from django.core.files.storage import default_storage
from django.test import TestCase, override_settings

from academy.models import Course

CACHES = {"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache",
                      "LOCATION": "academy-tests"}}
IN_MEMORY = {"default": {"BACKEND": "django.core.files.storage.InMemoryStorage"},
             "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"}}
PUBLIC_URL = "/api/academy/courses/"


def image(size=(1600, 900), fmt="PNG", color=(200, 120, 40)) -> bytes:
    from PIL import Image

    out = BytesIO()
    Image.new("RGB", size, color).save(out, fmt)
    return out.getvalue()


def ready_course(n: int = 1, **extra) -> Course:
    """Полный опубликованный курс (обложка — имя файла, самого файла может и не быть)."""
    fields = {
        "title": f"Курс {n}",
        "teacher": f"Преподаватель {n}",
        "description": f"Описание курса {n}",
        "url": f"https://example.com/kurs-{n}",
        "cover": f"academy/covers/{n}-0000000{n % 10}.jpg",
        "cover_thumb": f"academy/covers/{n}-0000000{n % 10}-480.jpg",
        "cover_width": 1280,
        "cover_height": 720,
        "is_published": True,
        "sort_order": n * 10,
        **extra,
    }
    return Course.objects.create(**fields)


@override_settings(CACHES=CACHES, STORAGES=IN_MEMORY)
class AcademyCase(TestCase):
    def setUp(self):
        cache.clear()
        # Хранилище в памяти живёт весь класс, а номера курсов повторяются: чистим.
        try:
            names = default_storage.listdir("academy/covers")[1]
        except Exception:
            names = []
        for name in names:
            default_storage.delete(f"academy/covers/{name}")
