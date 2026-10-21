# -*- coding: utf-8 -*-
"""BE-1: видеостудия в журнале генераций и в метриках трат админки."""
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import NoReverseMatch
from rest_framework.test import APIRequestFactory, force_authenticate

from adminapi.generations import GenerationsView
from adminapi.views import SummaryView
from ai.models import GenerationLog
from plans.models import TokenTransaction

CACHES = {"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache",
                      "LOCATION": "vstudio-be1-adminapi"}}
TAKE = "0123456789abcdef0123456789abcdef"


class _StaffCall:
    def setUp(self):
        User = get_user_model()
        self.staff = User.objects.create_user(email="admin@example.com", password="x-12345678",
                                              is_staff=True)
        self.user = User.objects.create_user(email="author@example.com", password="x-12345678")

    def _get(self, view, path):
        request = APIRequestFactory().get(path)
        force_authenticate(request, user=self.staff)
        return view.as_view()(request)


@override_settings(CACHES=CACHES)
class GenerationsVstudioTests(_StaffCall, TestCase):
    def setUp(self):
        super().setUp()
        self.vs = GenerationLog.objects.create(
            user=self.user, kind=GenerationLog.KIND_VIDEO, source=GenerationLog.SOURCE_VSTUDIO,
            model="bytedance/seedance-2.0", params={"take": TAKE, "project": "p" * 32})
        self.chat = GenerationLog.objects.create(
            user=self.user, kind=GenerationLog.KIND_VIDEO, source=GenerationLog.SOURCE_CHAT,
            model="bytedance/seedance-2.0", params={"take": TAKE})

    def test_source_filter(self):
        data = self._get(GenerationsView, "/g/?source=vstudio").data
        self.assertEqual(data["count"], 1)
        self.assertEqual(data["results"][0]["id"], self.vs.pk)
        self.assertEqual(data["results"][0]["source_label"], "Видеостудия")
        all_rows = self._get(GenerationsView, "/g/").data
        self.assertEqual(all_rows["count"], 2)

    def test_sources_listed_for_filter(self):
        data = self._get(GenerationsView, "/g/").data
        self.assertIn({"key": "vstudio", "label": "Видеостудия"}, data["sources"])

    def test_take_link_only_for_vstudio_rows(self):
        with patch("adminapi.generations.reverse", return_value="/admin/vstudio/take/"):
            data = self._get(GenerationsView, "/g/").data
        rows = {r["id"]: r for r in data["results"]}
        self.assertEqual(rows[self.vs.pk]["take_uid"], TAKE)
        self.assertEqual(rows[self.vs.pk]["take_admin_url"], f"/admin/vstudio/take/?uid={TAKE}")
        # У чата params.take ничего не значит — ссылки нет.
        self.assertEqual(rows[self.chat.pk]["take_uid"], "")
        self.assertEqual(rows[self.chat.pk]["take_admin_url"], "")

    def test_take_link_without_vstudio_admin(self):
        # Приложение vstudio ещё не подключено — uid виден, ссылка пустая.
        with patch("adminapi.generations.reverse", side_effect=NoReverseMatch("nope")):
            row = self._get(GenerationsView, "/g/?source=vstudio").data["results"][0]
        self.assertEqual(row["take_uid"], TAKE)
        self.assertEqual(row["take_admin_url"], "")

    def test_take_link_real_reverse_is_safe(self):
        # Как бы ни был собран URLconf (с vstudio или без) — ответ не падает.
        row = self._get(GenerationsView, "/g/?source=vstudio").data["results"][0]
        self.assertEqual(row["take_uid"], TAKE)
        self.assertTrue(row["take_admin_url"] == "" or row["take_admin_url"].endswith(f"?uid={TAKE}"))

    def test_garbage_take_uid_not_linked(self):
        self.vs.params = {"take": "../../x?y=1"}
        self.vs.save(update_fields=["params"])
        with patch("adminapi.generations.reverse", return_value="/admin/vstudio/take/"):
            row = self._get(GenerationsView, "/g/?source=vstudio").data["results"][0]
        self.assertEqual((row["take_uid"], row["take_admin_url"]), ("", ""))

    def test_non_dict_params_tolerated(self):
        self.vs.params = ["take", TAKE]
        self.vs.save(update_fields=["params"])
        row = self._get(GenerationsView, "/g/?source=vstudio").data["results"][0]
        self.assertEqual(row["take_uid"], "")

    def test_search_by_take_uid(self):
        data = self._get(GenerationsView, f"/g/?q={TAKE}").data
        # Чатовая запись тоже несёт params.take в этом тесте — ищем точно по
        # params.take, без учёта источника; фильтр источника сужает.
        self.assertEqual({r["id"] for r in data["results"]}, {self.vs.pk, self.chat.pk})
        data = self._get(GenerationsView, f"/g/?q={TAKE}&source=vstudio").data
        self.assertEqual([r["id"] for r in data["results"]], [self.vs.pk])


@override_settings(CACHES=CACHES)
class SummarySpendTests(_StaffCall, TestCase):
    def _tx(self, reason, delta):
        TokenTransaction.objects.create(user=self.user, delta=delta, reason=reason, balance_after=0)

    @patch("adminapi.views._openrouter_summary", return_value={})
    def test_vstudio_reasons_counted_in_spend(self, _or):
        self._tx("chat", -10)
        self._tx("vstudio_video", -40)
        self._tx("vstudio_image", -2)
        self._tx("cartoon_scene", -100)   # мультстудия в этой цифре не считалась и не считается
        self._tx("purchase", 500)
        data = self._get(SummaryView, "/s/").data
        self.assertEqual(data["credits_spent_total"], 52)
        self.assertEqual(data["credits_spent_today"], 52)
        self.assertEqual(data["credits_spent_vstudio_total"], 42)
        self.assertEqual(data["credits_spent_vstudio_today"], 42)
        self.assertEqual(data["requests_total"], 3)
        self.assertEqual(data["requests_today"], 3)

    @patch("adminapi.views._openrouter_summary", return_value={})
    def test_merge_counted_in_spend(self, _or):
        self._tx("chat", -10)
        self._tx("merge_video", -20)
        data = self._get(SummaryView, "/s/").data
        self.assertEqual((data["credits_spent_total"], data["credits_spent_today"]), (30, 30))
        self.assertEqual((data["requests_total"], data["requests_today"]), (2, 2))
        # Склейка — не видеостудия: её строка не меняется.
        self.assertEqual(data["credits_spent_vstudio_total"], 0)


class ResultUrlTests(TestCase):
    """«Результат» из журнала открывается: путь файла превращается в адрес /media/."""

    def test_storage_path_becomes_media_url(self):
        from adminapi.generations import _media_url

        self.assertTrue(_media_url("cartoon/scenes/abc.mp4").endswith("/media/cartoon/scenes/abc.mp4"))
        self.assertTrue(_media_url("cartoon/scenes/abc.mp4").startswith("/"))
        self.assertEqual(_media_url("/media/ai_videos/x.mp4"), "/media/ai_videos/x.mp4")
        self.assertEqual(_media_url("https://esai.kg/media/x.mp4"), "https://esai.kg/media/x.mp4")
        self.assertEqual(_media_url(""), "")
