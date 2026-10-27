# -*- coding: utf-8 -*-
"""Академия в панели: права, поля, ссылки, публикация, обложки, порядок, ссылка кнопки, журнал."""
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.files.storage import default_storage
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse
from rest_framework.test import APIClient

from academy.models import Course
from adminapi.models import AppSetting
from adminapi.runtime import KEYS
from audit.models import AdminActionLog

from .helpers import PUBLIC_URL, AcademyCase, image, ready_course


class PanelCase(AcademyCase):
    def setUp(self):
        super().setUp()
        User = get_user_model()
        self.staff = User.objects.create_user(email="admin@example.com", password="x-12345678",
                                              is_staff=True)
        self.user = User.objects.create_user(email="user@example.com", password="x-12345678")
        self.api = APIClient()
        self.api.force_authenticate(self.staff)

    # -- помощники
    def url(self, name, *args):
        return reverse(f"adminapi:{name}", args=args)

    def create(self, **body):
        return self.api.post(self.url("academy-courses"), body, format="json")

    def patch_course(self, pk, **body):
        with self.captureOnCommitCallbacks(execute=True):
            return self.api.patch(self.url("academy-course", pk), body, format="json")

    def upload(self, pk, data=None, name="cover.png", content_type="image/png"):
        upload = SimpleUploadedFile(name, image() if data is None else data,
                                    content_type=content_type)
        with self.captureOnCommitCallbacks(execute=True):
            return self.api.post(self.url("academy-course-cover", pk), {"file": upload},
                                 format="multipart")

    def full_draft(self, **extra):
        body = {"title": "AI-мультфильмы с нуля", "teacher": "Айбек Садыков",
                "description": "От идеи до готового мультфильма", "url": "https://example.com/kurs",
                **extra}
        response = self.create(**body)
        self.assertEqual(response.status_code, 201, response.data)
        pk = response.data["id"]
        self.assertEqual(self.upload(pk).status_code, 200)
        return pk

    def public_ids(self):
        return [row["id"] for row in APIClient().get(PUBLIC_URL).data["results"]]

    def logs(self):
        return AdminActionLog.objects.filter(action="settings.edit")

    def stored_files(self):
        try:
            return default_storage.listdir("academy/covers")[1]
        except Exception:
            return []


class PermissionTests(PanelCase):
    def test_anonymous_and_plain_user_are_refused_everywhere(self):
        course = ready_course(1)
        calls = [
            ("get", self.url("academy-courses")), ("post", self.url("academy-courses")),
            ("post", self.url("academy-courses-order")),
            ("get", self.url("academy-course", course.pk)),
            ("patch", self.url("academy-course", course.pk)),
            ("delete", self.url("academy-course", course.pk)),
            ("post", self.url("academy-course-cover", course.pk)),
            ("get", self.url("academy-settings")), ("patch", self.url("academy-settings")),
        ]
        plain = APIClient()
        plain.force_authenticate(self.user)
        for method, url in calls:
            self.assertEqual(getattr(APIClient(), method)(url, {}, format="json").status_code, 401,
                             url)
            self.assertEqual(getattr(plain, method)(url, {}, format="json").status_code, 403, url)
        self.assertTrue(Course.objects.filter(pk=course.pk).exists())
        self.assertFalse(self.logs().exists())

    def test_runtime_key_is_registered(self):
        self.assertIn("academy_suggest_url", KEYS)


class CreateAndFieldsTests(PanelCase):
    def test_partial_draft_goes_to_the_end_and_is_logged(self):
        ready_course(1, sort_order=70)
        response = self.create(title="  Только   название \n ")
        self.assertEqual(response.status_code, 201, response.data)
        row = response.data
        self.assertEqual(row["title"], "Только название")
        self.assertEqual(row["state"], "draft")
        self.assertFalse(row["is_published"])
        self.assertEqual(row["missing"], ["cover", "teacher", "description", "url"])
        self.assertEqual(row["sort"], 80)
        self.assertIsNone(row["place"])
        self.assertEqual(row["url_host"], "")
        log = self.logs().get(target_type="academy.course")
        self.assertIsNone(log.before["academy_course"])
        self.assertEqual(log.after["academy_course"]["title"], "Только название")

    def test_empty_draft_is_allowed(self):
        response = self.create()
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data["missing"],
                         ["cover", "title", "teacher", "description", "url"])

    def test_cannot_create_published(self):
        response = self.create(title="X", is_published=True)
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data["code"], "create_published")
        self.assertEqual(response.data["detail"], "Сначала сохраните черновик и загрузите обложку")
        response = self.create(title="X", is_published="true")
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data["field"], "is_published")
        self.assertFalse(Course.objects.exists())
        # is_published: false — обычный черновик.
        self.assertEqual(self.create(title="X", is_published=False).status_code, 201)

    def test_text_cleaning_and_limits(self):
        response = self.create(title="Курс‮\x00 о\tнейросетях​", teacher="Имя  Фамилия")
        self.assertEqual(response.data["title"], "Курс о нейросетях")
        self.assertEqual(response.data["teacher"], "Имя Фамилия")
        self.assertEqual(self.create(title="я" * 120).status_code, 201)
        for field, limit, label in (("title", 120, "Название"), ("teacher", 80, "Преподаватель"),
                                    ("description", 400, "Описание")):
            response = self.create(**{field: "я" * (limit + 1)})
            self.assertEqual(response.status_code, 400, field)
            self.assertEqual(response.data["code"], "too_long")
            self.assertEqual(response.data["field"], field)
            self.assertEqual(response.data["detail"], f"{label} длиннее {limit} символов")
        response = self.create(title=["список"])
        self.assertEqual((response.status_code, response.data["detail"]),
                         (400, "Название — строка"))

    def test_bad_links_are_refused_even_on_drafts(self):
        cases = {
            "javascript:alert(1)": "url_scheme", "data:text/html,<b>x</b>": "url_scheme",
            "ftp://x.example.com": "url_scheme", "https://localhost/": "url_local",
            "http://10.0.0.1/": "url_local", "https://u:p@example.com": "url_userinfo",
            "https://exa mple.com": "url_invalid",
            "https://example.com/" + "a" * 1000: "url_too_long",
        }
        for raw, code in cases.items():
            response = self.create(title="X", url=raw)
            self.assertEqual(response.status_code, 400, raw)
            self.assertEqual(response.data["code"], code, raw)
            self.assertEqual(response.data["field"], "url")
        self.assertEqual(self.create(url=123).data["detail"], "Ссылка на курс — строка")
        self.assertFalse(Course.objects.exists())

    def test_link_is_completed_and_host_shown_in_punycode(self):
        response = self.create(url="example.com/kurs")
        self.assertEqual(response.data["url"], "https://example.com/kurs")
        response = self.create(url="https://курсы.рф/x")
        self.assertEqual(response.data["url"], "https://курсы.рф/x")
        self.assertEqual(response.data["url_host"], "xn--j1amdg6b.xn--p1ai")

    def test_course_limit(self):
        with patch("academy.panel.MAX_COURSES", 2):
            self.assertEqual(self.create(title="1").status_code, 201)
            self.assertEqual(self.create(title="2").status_code, 201)
            response = self.create(title="3")
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data["code"], "too_many")


class PublishTests(PanelCase):
    def test_publish_incomplete_is_refused_with_missing(self):
        pk = self.create(title="X", teacher="Y").data["id"]
        response = self.patch_course(pk, is_published=True)
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data["code"], "publish_incomplete")
        self.assertEqual(response.data["missing"], ["cover", "description", "url"])
        self.assertEqual(response.data["detail"],
                         "Чтобы опубликовать, добавьте: обложку, описание, ссылку на курс")
        self.assertFalse(Course.objects.get(pk=pk).is_published)

    def test_full_course_publishes_and_appears_on_the_site(self):
        pk = self.full_draft()
        response = self.patch_course(pk, is_published=True)
        self.assertEqual(response.status_code, 200, response.data)
        row = response.data
        self.assertEqual((row["state"], row["missing"]), ("live", []))
        self.assertEqual(row["place"], {"page": 1, "index": 1})
        self.assertIsNotNone(row["published_at"])
        self.assertEqual(self.public_ids(), [pk])

    def test_fields_in_the_same_body_count_for_publication(self):
        pk = self.create(title="X").data["id"]
        self.upload(pk)
        response = self.patch_course(pk, teacher="Y", description="Z", url="example.com/k",
                                     is_published=True)
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["state"], "live")

    def test_published_course_cannot_be_emptied(self):
        pk = self.full_draft()
        self.patch_course(pk, is_published=True)
        self.logs().delete()
        response = self.patch_course(pk, description="  ")
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data["code"], "published_empty")
        self.assertEqual(response.data["field"], "description")
        self.assertEqual(response.data["detail"],
                         "Курс на сайте: «Описание» не может быть пустым. Сначала скройте курс")
        response = self.patch_course(pk, url="")
        self.assertEqual(response.data["field"], "url")
        self.assertEqual(Course.objects.get(pk=pk).description, "От идеи до готового мультфильма")
        self.assertFalse(self.logs().exists())
        # Скрыть и опустошить одним запросом можно.
        response = self.patch_course(pk, description="", is_published=False)
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["state"], "hidden")

    def test_hide_keeps_published_at_and_leaves_the_site(self):
        pk = self.full_draft()
        published = self.patch_course(pk, is_published=True).data["published_at"]
        response = self.patch_course(pk, is_published=False)
        self.assertEqual(response.data["state"], "hidden")
        self.assertEqual(response.data["published_at"], published)
        self.assertIsNone(response.data["place"])
        self.assertEqual(self.public_ids(), [])

    def test_edit_of_published_course_reaches_the_site_at_once(self):
        pk = self.full_draft()
        self.patch_course(pk, is_published=True)
        self.assertEqual(self.public_ids(), [pk])
        self.patch_course(pk, title="Новое название")
        row = APIClient().get(PUBLIC_URL).data["results"][0]
        self.assertEqual(row["title"], "Новое название")

    def test_same_values_write_nothing_and_empty_body_is_refused(self):
        pk = self.full_draft()
        before = self.logs().count()
        response = self.patch_course(pk, title="AI-мультфильмы с нуля",
                                     url="https://example.com/kurs")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.logs().count(), before)
        response = self.patch_course(pk, unknown="x")
        self.assertEqual((response.status_code, response.data["code"]), (400, "nothing_to_change"))

    def test_patch_log_has_before_and_after(self):
        pk = self.full_draft()
        self.patch_course(pk, title="Другое")
        log = self.logs().filter(target_id=str(pk)).order_by("-id").first()
        self.assertEqual(log.before["academy_course"], {"title": "AI-мультфильмы с нуля"})
        self.assertEqual(log.after["academy_course"], {"title": "Другое"})

    def test_unknown_course(self):
        response = self.api.get(self.url("academy-course", 999))
        self.assertEqual((response.status_code, response.data["detail"]), (404, "Курс не найден"))
        self.assertEqual(self.patch_course(999, title="x").status_code, 404)
        self.assertEqual(self.api.delete(self.url("academy-course", 999)).status_code, 404)
        self.assertEqual(self.upload(999).status_code, 404)

    def test_list_payload(self):
        live = self.full_draft()
        self.patch_course(live, is_published=True)
        self.create(title="Черновик")
        data = self.api.get(self.url("academy-courses")).data
        self.assertEqual([row["state"] for row in data["results"]], ["live", "draft"])
        self.assertEqual(data["counts"], {"live": 1, "draft": 1, "hidden": 0, "incomplete": 0,
                                          "total": 2})
        self.assertEqual(data["suggest_url"], "")
        self.assertEqual(data["limits"]["page_size"], 9)
        self.assertEqual(data["limits"]["cover_min"], [480, 270])
        self.assertEqual(data["limits"]["title"], 120)
        from vstudio import assets

        self.assertEqual(data["limits"]["cover_max_bytes"], assets.max_upload_bytes())

    def test_place_follows_site_pages_and_incomplete_state(self):
        made = [ready_course(n) for n in range(1, 11)]
        broken = ready_course(11, cover="")
        rows = {row["id"]: row for row in self.api.get(self.url("academy-courses")).data["results"]}
        self.assertEqual(rows[made[8].pk]["place"], {"page": 1, "index": 9})
        self.assertEqual(rows[made[9].pk]["place"], {"page": 2, "index": 1})
        self.assertEqual(rows[broken.pk]["state"], "incomplete")
        self.assertIsNone(rows[broken.pk]["place"])


class CoverTests(PanelCase):
    def test_cover_is_normalised_and_replaced_with_new_names(self):
        pk = self.create(title="X").data["id"]
        response = self.upload(pk)
        self.assertEqual(response.status_code, 200, response.data)
        row = response.data
        self.assertEqual((row["cover_width"], row["cover_height"]), (1280, 720))
        self.assertRegex(row["cover"], rf"^/media/academy/covers/{pk}-[0-9a-f]{{8}}\.jpg$")
        self.assertRegex(row["cover_thumb"],
                         rf"^/media/academy/covers/{pk}-[0-9a-f]{{8}}-480\.jpg$")
        first = Course.objects.get(pk=pk)
        old = [first.cover.name, first.cover_thumb.name]
        self.assertTrue(all(default_storage.exists(name) for name in old))
        response = self.upload(pk, image((1280, 720), "JPEG"))
        self.assertEqual(response.status_code, 200)
        second = Course.objects.get(pk=pk)
        self.assertNotIn(second.cover.name, old)
        self.assertTrue(default_storage.exists(second.cover.name))
        self.assertFalse(any(default_storage.exists(name) for name in old))
        self.assertEqual(self.logs().filter(target_id=str(pk)).count(), 3)

    def test_cover_of_published_course_is_replaced_on_the_site(self):
        pk = self.full_draft()
        self.patch_course(pk, is_published=True)
        before = APIClient().get(PUBLIC_URL).data["results"][0]["cover"]
        self.upload(pk, image((1920, 1080), "JPEG"))
        after = APIClient().get(PUBLIC_URL).data["results"][0]["cover"]
        self.assertNotEqual(before, after)

    def test_bad_files_are_refused(self):
        pk = self.create(title="X").data["id"]
        cases = [
            (b"<svg xmlns='http://www.w3.org/2000/svg'/>", "x.svg", "image/svg+xml", 400,
             "cover_type"),
            (b"\x00\x00\x00\x18ftypmp42" + b"x" * 64, "clip.mp4", "video/mp4", 400, "cover_type"),
            (b"<html><script>alert(1)</script></html>", "photo.jpg", "image/jpeg", 422,
             "cover_bad"),
            (image((300, 200)), "small.png", "image/png", 400, "cover_too_small"),
            (image((800, 260)), "flat.png", "image/png", 400, "cover_too_small"),
        ]
        for data, name, ctype, status, code in cases:
            response = self.upload(pk, data, name, ctype)
            self.assertEqual(response.status_code, status, name)
            self.assertEqual(response.data["code"], code, name)
            self.assertEqual(response.data["field"], "cover")
        self.assertEqual(Course.objects.get(pk=pk).cover.name, "")
        self.assertEqual(self.logs().filter(target_id=str(pk)).count(), 1)  # только создание
        self.assertEqual(self.stored_files(), [])

    def test_missing_and_extra_files(self):
        pk = self.create(title="X").data["id"]
        url = self.url("academy-course-cover", pk)
        response = self.api.post(url, {}, format="multipart")
        self.assertEqual((response.status_code, response.data["code"]), (400, "cover_missing"))
        two = {"file": SimpleUploadedFile("a.png", image(), "image/png"),
               "other": SimpleUploadedFile("b.png", image(), "image/png")}
        response = self.api.post(url, two, format="multipart")
        self.assertEqual((response.status_code, response.data["code"]), (400, "cover_many"))

    def test_too_large_and_busy(self):
        pk = self.create(title="X").data["id"]
        with patch("academy.panel._cover_max_bytes", return_value=1000):
            response = self.upload(pk)
        self.assertEqual((response.status_code, response.data["code"]), (413, "cover_too_large"))
        from vstudio.assets import AssetError

        busy = AssetError("throttled", "Сейчас обрабатывается много фото — попробуйте через "
                          "несколько секунд.", status=429)
        with patch("vstudio.assets.normalize_image_bytes", side_effect=busy):
            response = self.upload(pk)
        self.assertEqual((response.status_code, response.data["code"]), (429, "cover_busy"))
        self.assertEqual(self.stored_files(), [])

    def test_files_are_removed_when_the_course_is_not_saved(self):
        pk = self.create(title="X").data["id"]
        with patch("academy.panel.log_admin_action", side_effect=RuntimeError("журнал лёг")):
            with self.assertRaises(RuntimeError):
                self.upload(pk)
        self.assertEqual(Course.objects.get(pk=pk).cover.name, "")
        self.assertEqual(self.stored_files(), [])


class DeleteAndOrderTests(PanelCase):
    def test_delete_removes_row_files_and_site_card(self):
        pk = self.full_draft()
        self.patch_course(pk, is_published=True)
        course = Course.objects.get(pk=pk)
        names = [course.cover.name, course.cover_thumb.name]
        with self.captureOnCommitCallbacks(execute=True):
            response = self.api.delete(self.url("academy-course", pk))
        self.assertEqual(response.status_code, 204)
        self.assertFalse(Course.objects.filter(pk=pk).exists())
        self.assertFalse(any(default_storage.exists(name) for name in names))
        self.assertEqual(self.public_ids(), [])
        log = self.logs().filter(target_id=str(pk)).order_by("-id").first()
        self.assertIsNone(log.after["academy_course"])
        self.assertEqual(log.before["academy_course"]["title"], "AI-мультфильмы с нуля")

    def test_foreign_files_are_not_deleted(self):
        course = ready_course(1, cover="vstudio/1/photo.jpg", cover_thumb="")
        default_storage.save("vstudio/1/photo.jpg", SimpleUploadedFile("p.jpg", b"x"))
        with self.captureOnCommitCallbacks(execute=True):
            self.api.delete(self.url("academy-course", course.pk))
        self.assertTrue(default_storage.exists("vstudio/1/photo.jpg"))

    def test_reorder_changes_site_order(self):
        a, b, c = (ready_course(n) for n in (1, 2, 3))
        with self.captureOnCommitCallbacks(execute=True):
            response = self.api.post(self.url("academy-courses-order"), {"ids": [c.pk, a.pk, b.pk]},
                                     format="json")
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual([row["id"] for row in response.data["results"]], [c.pk, a.pk, b.pk])
        self.assertEqual([row["sort"] for row in response.data["results"]], [10, 20, 30])
        self.assertEqual(self.public_ids(), [c.pk, a.pk, b.pk])
        log = self.logs().get()
        self.assertEqual(log.before["academy_order"], [a.pk, b.pk, c.pk])
        self.assertEqual(log.after["academy_order"], [c.pk, a.pk, b.pk])
        # Тот же порядок — без записи.
        self.api.post(self.url("academy-courses-order"), {"ids": [c.pk, a.pk, b.pk]}, format="json")
        self.assertEqual(self.logs().count(), 1)

    def test_reorder_includes_drafts_and_refuses_stale_lists(self):
        a = ready_course(1)
        draft = ready_course(2, is_published=False)
        url = self.url("academy-courses-order")
        for ids in ([a.pk], [a.pk, draft.pk, 999]):
            response = self.api.post(url, {"ids": ids}, format="json")
            self.assertEqual(response.status_code, 409, ids)
            self.assertEqual(response.data["detail"],
                             "Список курсов изменился — обновите страницу и переставьте ещё раз")
        for body in ({"ids": [a.pk, a.pk]}, {"ids": "1,2"}, {"ids": [a.pk, True]}, {}, {"ids": []}):
            response = self.api.post(url, body, format="json")
            self.assertEqual((response.status_code, response.data["code"]), (400, "invalid"), body)
        self.assertEqual(self.api.post(url, {"ids": [draft.pk, a.pk]}, format="json").status_code,
                         200)
        self.assertEqual(list(Course.objects.values_list("id", flat=True)), [draft.pk, a.pk])


class SuggestSettingsTests(PanelCase):
    def setting(self, value):
        with self.captureOnCommitCallbacks(execute=True):
            return self.api.patch(self.url("academy-settings"), {"suggest_url": value},
                                  format="json")

    def test_telegram_name_is_normalised_and_shown_on_the_site(self):
        self.assertEqual(self.api.get(self.url("academy-settings")).data, {"suggest_url": ""})
        response = self.setting("@my_channel")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data, {"suggest_url": "https://t.me/my_channel"})
        self.assertEqual(APIClient().get(PUBLIC_URL).data["suggest_url"], "https://t.me/my_channel")
        self.assertEqual(self.api.get(self.url("academy-courses")).data["suggest_url"],
                         "https://t.me/my_channel")
        log = self.logs().get()
        self.assertEqual(log.before, {"academy_suggest_url": ""})
        self.assertEqual(log.after, {"academy_suggest_url": "https://t.me/my_channel"})
        # Повтор — без записи.
        self.setting("t.me/my_channel")
        self.assertEqual(self.logs().count(), 1)

    def test_empty_removes_the_button(self):
        self.setting("@my_channel")
        for value in ("", None):
            response = self.setting(value)
            self.assertEqual(response.data, {"suggest_url": ""})
            self.assertFalse(AppSetting.objects.filter(key="academy_suggest_url").exists())
            self.assertEqual(APIClient().get(PUBLIC_URL).data["suggest_url"], "")
        self.assertEqual(self.logs().count(), 2)

    def test_bad_links_are_refused(self):
        for value in ("http://forms.example.com", "javascript:alert(1)", "@ab", 5,
                      "https://localhost/x"):
            response = self.setting(value)
            self.assertEqual(response.status_code, 400, value)
            self.assertEqual(response.data["code"], "suggest_invalid")
            self.assertEqual(response.data["field"], "suggest_url")
            self.assertEqual(response.data["detail"],
                             "Ссылка для кнопки — @имя, t.me/имя или адрес сайта с https://")
        response = self.api.patch(self.url("academy-settings"), {}, format="json")
        self.assertEqual((response.status_code, response.data["code"]), (400, "nothing_to_change"))
        self.assertFalse(self.logs().exists())

    def test_any_https_link_is_allowed(self):
        response = self.setting("https://forms.example.com/academy")
        self.assertEqual(response.data["suggest_url"], "https://forms.example.com/academy")
