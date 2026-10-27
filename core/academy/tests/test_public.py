# -*- coding: utf-8 -*-
"""Публичный API Академии: что видит сайт, порядок, кэш, лимит запросов."""
from django.core.cache import cache
from rest_framework.test import APIClient

from academy import public
from academy.models import Course
from academy.views import AcademyReadThrottle, CoursesView
from adminapi.runtime import set_runtime

from .helpers import PUBLIC_URL, AcademyCase, ready_course


class PublicCoursesTests(AcademyCase):
    def get(self, url=PUBLIC_URL):
        response = APIClient().get(url)
        self.assertEqual(response.status_code, 200)
        return response

    def test_only_published_and_complete_courses_are_listed(self):
        live = ready_course(1)
        ready_course(2, is_published=False)                       # черновик
        ready_course(3, is_published=False, published_at="2026-10-01T10:00:00+06:00")  # скрыт
        ready_course(4, cover="")                                  # обложку стёрли мимо панели
        ready_course(5, title="   ")
        ready_course(6, teacher="")
        ready_course(7, description="")
        ready_course(8, url="javascript:alert(1)")
        ready_course(9, url="example.com/not-normalised")
        data = self.get().data
        self.assertEqual([row["id"] for row in data["results"]], [live.pk])
        self.assertEqual(data["count"], 1)
        self.assertEqual(data["page_size"], 9)

    def test_all_courses_in_admin_order_in_one_answer(self):
        made = [ready_course(n, sort_order=(13 - n) * 10) for n in range(1, 13)]
        tie = ready_course(20, sort_order=10)
        data = self.get().data
        expected = sorted(made + [tie], key=lambda c: (c.sort_order, c.pk))
        self.assertEqual([row["id"] for row in data["results"]], [c.pk for c in expected])
        self.assertEqual(data["count"], 13)
        # ?page не влияет: страницы режет Next, ключ кэша один.
        self.assertEqual(self.get(PUBLIC_URL + "?page=2").data, data)
        self.assertEqual(self.get(PUBLIC_URL + "?page=999999").data, data)

    def test_card_shape_with_relative_media_paths(self):
        course = ready_course(1, title="Длинное название", url="https://курсы.рф/x")
        row = self.get().data["results"][0]
        self.assertEqual(row, {
            "id": course.pk, "title": "Длинное название", "teacher": "Преподаватель 1",
            "description": "Описание курса 1", "url": "https://курсы.рф/x",
            "cover": "/media/academy/covers/1-00000001.jpg",
            "cover_thumb": "/media/academy/covers/1-00000001-480.jpg",
            "cover_width": 1280, "cover_height": 720,
        })

    def test_empty_catalogue(self):
        data = self.get().data
        self.assertEqual(data, {"count": 0, "page_size": 9, "results": [], "suggest_url": "",
                                "suggest": None})

    def suggest(self):
        data = self.get().data
        return data["suggest_url"], data["suggest"]

    def test_suggest_url_comes_from_runtime_setting_and_is_rechecked(self):
        self.assertEqual(self.suggest(), ("", None))
        set_runtime("academy_suggest_url", "https://t.me/esai_academy")
        self.assertEqual(self.suggest(), ("https://t.me/esai_academy",
                                          {"kind": "url", "text": "https://t.me/esai_academy",
                                           "href": "https://t.me/esai_academy"}))
        # Значение поправили мимо панели — на сайт оно не попадёт.
        for bad in ("javascript:alert(1)", "https://u:p@example.com", "a\u202eb"):
            set_runtime("academy_suggest_url", bad)
            self.assertEqual(self.suggest(), ("", None), bad)
        # Неприведённое значение мимо панели сайт показывает приведённым.
        set_runtime("academy_suggest_url", "@esai_academy")
        self.assertEqual(self.suggest()[0], "https://t.me/esai_academy")

    def test_suggest_email_and_text(self):
        set_runtime("academy_suggest_url", "academy@курсы.рф")
        self.assertEqual(self.suggest(), (
            "mailto:academy@xn--j1amdg6b.xn--p1ai",
            {"kind": "email", "text": "academy@курсы.рф", "href": "mailto:academy@xn--j1amdg6b.xn--p1ai"}))
        # У текста кнопки нет: прежнее поле пустое, чтобы старые страницы ничего не показали.
        set_runtime("academy_suggest_url", "Пишите на academy@esai.kg\nили в Telegram @esai_academy")
        self.assertEqual(self.suggest(), (
            "", {"kind": "text", "text": "Пишите на academy@esai.kg\nили в Telegram @esai_academy",
                 "href": None}))
        set_runtime("academy_suggest_url", "http://localhost:3000/form")
        self.assertEqual(self.suggest()[1]["href"], "http://localhost:3000/form")

    def test_list_is_cached_and_cacheable(self):
        ready_course(1)
        response = self.get()
        self.assertEqual(response["Cache-Control"], "public, max-age=60")
        Course.objects.update(title="Поправили мимо панели")
        self.assertEqual(self.get().data["results"][0]["title"], "Курс 1")
        public._forget()
        self.assertEqual(self.get().data["results"][0]["title"], "Поправили мимо панели")

    def test_cap_on_public_list(self):
        Course.objects.bulk_create([
            Course(title=f"Курс {n}", teacher="Автор", description="Текст",
                   url="https://example.com/k", cover=f"academy/covers/{n}-00000000.jpg",
                   is_published=True, sort_order=n)
            for n in range(public.MAX_PUBLIC + 1)])
        data = self.get().data
        self.assertEqual(data["count"], public.MAX_PUBLIC)

    def test_no_login_and_own_generous_throttle(self):
        self.assertEqual(CoursesView.authentication_classes, [])
        self.assertEqual(CoursesView.throttle_classes, [AcademyReadThrottle])
        self.assertEqual(AcademyReadThrottle().rate, "600/min")
        self.assertEqual(AcademyReadThrottle.scope, "academy_read")
        # Общий анонимный лимит (30 в минуту) сюда не действует: SSR идёт с одного адреса.
        client = APIClient()
        for _ in range(40):
            self.assertEqual(client.get(PUBLIC_URL).status_code, 200)

    def test_throttle_answers_429_past_its_rate(self):
        cache.clear()
        throttle = AcademyReadThrottle()
        throttle.rate = "2/min"
        throttle.num_requests, throttle.duration = throttle.parse_rate("2/min")

        class Request:
            META = {"REMOTE_ADDR": "203.0.113.5"}
            user = None

        self.assertTrue(throttle.allow_request(Request(), None))
        self.assertTrue(throttle.allow_request(Request(), None))
        self.assertFalse(throttle.allow_request(Request(), None))
