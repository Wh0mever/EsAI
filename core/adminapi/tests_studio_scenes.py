# -*- coding: utf-8 -*-
"""Сцены мультстудии в панели: права, проверка полей, публикация, превью, разделы."""
from io import BytesIO
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse
from rest_framework.test import APIClient

from ai.models import GPTModels
from audit.models import AdminActionLog
from cartoon import panel
from cartoon.library import ADULT_STYLE, STYLE
from cartoon.models import CartoonCategory, CartoonCharacter, CartoonPreset, CartoonProject, CartoonScene
from cartoon.services import CUSTOM_PRESET_SLUG

CACHES = {"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache",
                      "LOCATION": "studio-scenes-tests"}}
IN_MEMORY = {"default": {"BACKEND": "django.core.files.storage.InMemoryStorage"},
             "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"}}
MP4_HEAD = b"\x00\x00\x00\x18ftypmp42\x00\x00\x00\x00"
PROBE_OK = {"width": 1280, "height": 720, "duration": 5.0}


def png() -> bytes:
    from PIL import Image

    out = BytesIO()
    Image.new("RGB", (900, 500), (200, 120, 40)).save(out, "PNG")
    return out.getvalue()


def mp4(name="clip.mp4", body=b"x" * 2048):
    return SimpleUploadedFile(name, MP4_HEAD + body, content_type="video/mp4")


@override_settings(CACHES=CACHES, STORAGES=IN_MEMORY)
class ScenesCase(TestCase):
    def setUp(self):
        cache.clear()
        User = get_user_model()
        self.staff = User.objects.create_user(email="admin@example.com", password="x-12345678",
                                              is_staff=True)
        self.user = User.objects.create_user(email="author@example.com", password="x-12345678")
        self.image = GPTModels.objects.create(
            name="Nano Banana", openrouter_id="google/gemini-2.5-flash-image", max_tokens=100,
            markup_coefficient=4, category="image")
        self.video = GPTModels.objects.create(
            name="Seedance 2.0", openrouter_id="bytedance/seedance-2.0", max_tokens=100,
            markup_coefficient=32, category="video")
        self.section = CartoonCategory.objects.create(title="Приключения", slug="adventure",
                                                      sort_order=20)
        # Готовая сцена библиотеки: у неё новые сцены берут модели и качество.
        self.lib = CartoonPreset.objects.create(
            slug="lib-scene", title="Крыша", scene_prompt="the character on a roof",
            image_model=self.image, video_model=self.video, resolution="720p",
            category=self.section, sort_order=30, preview_video="cartoon/previews/lib.mp4")
        self.service = CartoonPreset.objects.create(
            slug=CUSTOM_PRESET_SLUG, title="Своя сцена", scene_prompt="the character",
            image_model=self.image, video_model=self.video, style_prompt=STYLE)
        # Цена сцены считается по каталогу провайдера — в тестах его нет.
        for target, value in (("ai.handlers._video_model_params",
                               lambda model, cfg, dur, res: {"duration": dur, "resolution": res}),
                              ("ai.handlers._openrouter_video_catalog", lambda model: {}),
                              ("ai.handlers._openrouter_config",
                               lambda: {"base_url": "x", "api_key": "k"})):
            p = patch(target, side_effect=value)
            p.start()
            self.addCleanup(p.stop)
        self.api = APIClient()
        self.api.force_authenticate(self.staff)

    # -- помощники
    def url(self, name, *args):
        return reverse(f"adminapi:{name}", args=args)

    def create(self, **extra):
        body = {"title": "Прыжок в воду", "scene_prompt": "the character dives into a lake",
                **extra}
        return self.api.post(self.url("studio-scenes"), body, format="json")

    def public(self):
        return {p["slug"] for p in APIClient().get("/api/cartoon/presets/").data["presets"]}

    def logs(self, model="cartoonpreset"):
        return AdminActionLog.objects.filter(target_type=f"cartoon.{model}")


class PermissionTests(ScenesCase):
    def test_anonymous_and_plain_user_are_refused_everywhere(self):
        calls = [
            ("get", self.url("studio-scenes")), ("post", self.url("studio-scenes")),
            ("get", self.url("studio-scene", self.lib.pk)),
            ("patch", self.url("studio-scene", self.lib.pk)),
            ("delete", self.url("studio-scene", self.lib.pk)),
            ("post", self.url("studio-scene-preview", self.lib.pk)),
            ("post", self.url("studio-scene-preview-rebuild", self.lib.pk)),
            ("get", self.url("studio-sections")), ("post", self.url("studio-sections")),
            ("patch", self.url("studio-section", self.section.pk)),
            ("post", self.url("studio-work-publish-scene", 1)),
        ]
        plain = APIClient()
        plain.force_authenticate(self.user)
        for method, url in calls:
            self.assertEqual(getattr(APIClient(), method)(url, {}, format="json").status_code, 401,
                             url)
            self.assertEqual(getattr(plain, method)(url, {}, format="json").status_code, 403, url)
        self.assertTrue(CartoonPreset.objects.filter(pk=self.lib.pk).exists())


class ListTests(ScenesCase):
    def test_list_hides_service_scene_and_carries_form_data(self):
        data = self.api.get(self.url("studio-scenes")).data
        self.assertEqual([r["slug"] for r in data["results"]], ["lib-scene"])
        row = data["results"][0]
        self.assertEqual(row["state"], "live")
        self.assertEqual(row["section_id"], self.section.pk)
        self.assertEqual(row["used_in"], 0)
        self.assertTrue(row["can_delete"])
        self.assertIsInstance(row["credits"], int)
        self.assertEqual(row["preview"]["state"], "partial")
        self.assertEqual([s["slug"] for s in data["sections"]], ["adventure"])
        self.assertEqual(data["sections"][0]["scenes"], 1)
        self.assertEqual(data["sections"][0]["published"], 1)
        self.assertEqual({a["key"] for a in data["audiences"]}, {"kids", "adults"})
        self.assertEqual(data["aspects"], ["16:9", "9:16", "1:1"])
        self.assertEqual(data["limits"]["duration_default"], 5)
        self.assertEqual(self.api.get(self.url("studio-scene", self.service.pk)).status_code, 404)

    def test_filters(self):
        kids = self.create(audience="kids", is_pick=True, section_id=None).data
        get = lambda q: [r["id"] for r in self.api.get(self.url("studio-scenes") + q).data["results"]]
        self.assertEqual(get(f"?section={self.section.pk}"), [self.lib.pk])
        self.assertEqual(get("?section=none"), [kids["id"]])
        self.assertEqual(get("?audience=kids"), [kids["id"]])
        self.assertEqual(get("?published=0"), [kids["id"]])
        self.assertEqual(get("?published=1"), [self.lib.pk])
        self.assertEqual(get("?pick=1"), [kids["id"]])
        # Без заглавной буквы: SQLite сравнивает кириллицу с учётом регистра.
        self.assertEqual(get("?q=рыша"), [self.lib.pk])
        self.assertEqual(get("?q=lake"), [kids["id"]])
        for bad in ("?section=abc", "?audience=pets", "?published=yes"):
            self.assertEqual(self.api.get(self.url("studio-scenes") + bad).status_code, 400, bad)


class CreateTests(ScenesCase):
    def test_validation_in_russian(self):
        cases = [
            ({"title": ""}, "Название"),
            ({"scene_prompt": "  "}, "Промпт сцены"),
            ({"audience": "pets"}, "kids или adults"),
            ({"is_pick": "true"}, "true или false"),
            ({"is_active": 1}, "true или false"),
            ({"duration": 40}, "от 2 до 15"),
            ({"duration": "5"}, "целое число"),
            ({"sort_order": -1}, "Порядок"),
            ({"aspect_ratio": "4:3"}, "16:9"),
            ({"section_id": 9999}, "Раздел не найден"),
            ({"section_id": "1"}, "Раздел"),
            ({"title": "Я" * 121}, "длиннее 120"),
            ({"subtitle_kg": "ж" * 161}, "длиннее 160"),
            ({"scene_prompt": "x" * 2001}, "длиннее 2000"),
            ({"slug": "Bad Slug"}, "латиница"),
            ({"slug": "lib-scene"}, "уже занят"),
            ({"slug": CUSTOM_PRESET_SLUG}, "уже занят"),
        ]
        for extra, words in cases:
            response = self.create(**extra)
            self.assertEqual(response.status_code, 400, extra)
            self.assertIn(words, response.data["detail"], extra)
        self.assertEqual(self.api.post(self.url("studio-scenes"), {"scene_prompt": "x"},
                                       format="json").status_code, 400)
        self.assertEqual(CartoonPreset.objects.count(), 2)
        self.assertFalse(self.logs().exists())

    def test_create_takes_models_from_library_and_stays_unpublished(self):
        response = self.create(title="Прыжок в воду!", title_en="Dive", audience="kids",
                               section_id=self.section.pk, motion_prompt="splash")
        self.assertEqual(response.status_code, 201, response.data)
        row = response.data
        self.assertEqual(row["slug"], "pryzhok-v-vodu")
        self.assertFalse(row["is_active"])
        self.assertEqual(row["state"], "unpublished")
        self.assertEqual(row["duration"], 5)
        self.assertEqual(row["aspect_ratio"], "16:9")
        self.assertEqual(row["preview"]["state"], "none")
        # В конец своего раздела, а не в середину.
        self.assertEqual(row["sort_order"], 40)
        preset = CartoonPreset.objects.get(pk=row["id"])
        self.assertEqual((preset.image_model_id, preset.video_model_id, preset.resolution),
                         (self.image.pk, self.video.pk, "720p"))
        self.assertEqual(preset.style_prompt, STYLE)
        self.assertNotIn(row["slug"], self.public())
        log = self.logs().get()
        self.assertEqual((log.action, log.actor_id, log.target_id),
                         ("settings.edit", self.staff.pk, str(preset.pk)))
        self.assertIsNone(log.before["cartoon_preset"])
        self.assertEqual(log.after["cartoon_preset"]["title"], "Прыжок в воду!")
        # Тот же заголовок ещё раз — код с номером.
        self.assertEqual(self.create(title="Прыжок в воду!").data["slug"], "pryzhok-v-vodu-2")
        self.assertEqual(self.create(title="🙂").data["slug"][:6], "scene-")

    def test_empty_library_has_nowhere_to_take_models(self):
        CartoonPreset.objects.all().delete()
        response = self.create()
        self.assertEqual(response.status_code, 400)
        self.assertIn("seed_presets", response.data["detail"])


class EditTests(ScenesCase):
    def setUp(self):
        super().setUp()
        self.row = self.create(section_id=self.section.pk).data
        self.preset = CartoonPreset.objects.get(pk=self.row["id"])
        self.preset.preview_video = "cartoon/previews/new.mp4"
        self.preset.save(update_fields=["preview_video"])

    def patch(self, body, pk=None):
        return self.api.patch(self.url("studio-scene", pk or self.preset.pk), body, format="json")

    def test_publish_and_unpublish_drive_the_public_library(self):
        self.assertNotIn(self.preset.slug, self.public())
        response = self.patch({"is_active": True})
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["state"], "live")
        self.assertIn(self.preset.slug, self.public())
        self.assertEqual(self.patch({"is_active": False}).data["state"], "unpublished")
        self.assertNotIn(self.preset.slug, self.public())

    def test_published_scene_without_preview_is_not_shown(self):
        CartoonPreset.objects.filter(pk=self.preset.pk).update(preview_video="")
        self.assertEqual(self.patch({"is_active": True}).data["state"], "no_preview")
        self.assertNotIn(self.preset.slug, self.public())

    def test_hidden_section_hides_its_scenes(self):
        self.patch({"is_active": True})
        response = self.api.patch(self.url("studio-section", self.section.pk),
                                  {"is_active": False}, format="json")
        self.assertEqual(response.status_code, 200, response.data)
        self.assertFalse(response.data["is_active"])
        row = self.api.get(self.url("studio-scene", self.preset.pk)).data
        self.assertEqual(row["state"], "section_hidden")
        public = self.public()
        self.assertNotIn(self.preset.slug, public)
        self.assertNotIn("lib-scene", public)
        # Без раздела — видна.
        self.assertEqual(self.patch({"section_id": None}).data["state"], "live")
        self.assertIn(self.preset.slug, self.public())

    def test_edit_logs_only_real_changes(self):
        before = self.logs().count()
        response = self.patch({"title": "  Новое   имя ", "title_kg": "Жаңы", "sort_order": 5,
                               "duration": 8, "aspect_ratio": "9:16", "is_pick": True,
                               "id": 1, "state": "live"})
        self.assertEqual(response.status_code, 200, response.data)
        self.preset.refresh_from_db()
        self.assertEqual((self.preset.title, self.preset.title_kg, self.preset.sort_order,
                          self.preset.duration, self.preset.aspect_ratio, self.preset.is_pick),
                         ("Новое имя", "Жаңы", 5, 8, "9:16", True))
        log = self.logs().latest("id")
        self.assertEqual(log.before["cartoon_preset"]["title"], "Прыжок в воду")
        self.assertEqual(log.after["cartoon_preset"]["duration"], 8)
        self.assertEqual(self.logs().count(), before + 1)
        # Те же значения — ни записи, ни строки в журнале.
        self.assertEqual(self.patch({"title": "Новое имя"}).status_code, 200)
        self.assertEqual(self.logs().count(), before + 1)
        self.assertIn("Нечего менять", self.patch({}).data["detail"])
        self.assertIn("не меняется", self.patch({"slug": "other"}).data["detail"])
        self.assertEqual(self.patch({"slug": self.preset.slug, "title": "Ок"}).status_code, 200)
        self.assertIn("не может быть пустым", self.patch({"title": ""}).data["detail"])
        self.assertEqual(self.patch({"title": "x"}, pk=999999).status_code, 404)

    def test_audience_switches_library_style_but_keeps_a_custom_one(self):
        self.patch({"audience": "kids"})
        self.preset.refresh_from_db()
        self.assertEqual(self.preset.style_prompt, STYLE)
        self.patch({"audience": "adults"})
        self.preset.refresh_from_db()
        self.assertEqual(self.preset.style_prompt, ADULT_STYLE)
        CartoonPreset.objects.filter(pk=self.preset.pk).update(style_prompt="noir comic")
        self.patch({"audience": "kids"})
        self.preset.refresh_from_db()
        self.assertEqual(self.preset.style_prompt, "noir comic")


class DeleteTests(ScenesCase):
    def test_unused_scene_is_deleted_used_one_is_refused(self):
        project = CartoonProject.objects.create(user=self.user)
        CartoonScene.objects.create(project=project, preset=self.lib, order=0)
        response = self.api.delete(self.url("studio-scene", self.lib.pk))
        self.assertEqual(response.status_code, 409)
        self.assertIn("Снимите её с публикации", response.data["detail"])
        self.assertTrue(CartoonPreset.objects.filter(pk=self.lib.pk).exists())
        self.assertFalse(self.api.get(self.url("studio-scene", self.lib.pk)).data["can_delete"])

        fresh = self.create().data
        response = self.api.delete(self.url("studio-scene", fresh["id"]))
        self.assertEqual(response.status_code, 204)
        self.assertFalse(CartoonPreset.objects.filter(pk=fresh["id"]).exists())
        log = self.logs().latest("id")
        self.assertIsNone(log.after["cartoon_preset"])
        self.assertEqual(log.before["cartoon_preset"]["slug"], fresh["slug"])
        self.assertEqual(panel.deleted_preset_slugs(), {fresh["slug"]})

    def test_deleted_scene_takes_its_panel_files_along(self):
        fresh = self.create().data
        video = default_storage.save(f"cartoon/previews/{fresh['slug']}-0123abcd.mp4", ContentFile(b"v"))
        clip = default_storage.save("cartoon/previews/clips/c.mp4", ContentFile(b"c"))
        thumb = default_storage.save("cartoon/posters/thumbs/t.jpg", ContentFile(b"t"))
        # Кадр сцены пользователя («Сделать превью сцены») — его файл, не панели.
        frame = default_storage.save("cartoon/keyframes/k.png", ContentFile(b"k"))
        CartoonPreset.objects.filter(pk=fresh["id"]).update(
            preview_video=video, preview_clip=clip, preview_thumb=thumb, preview_poster=frame)
        with self.captureOnCommitCallbacks(execute=True):
            self.assertEqual(self.api.delete(self.url("studio-scene", fresh["id"])).status_code, 204)
        self.assertEqual([default_storage.exists(n) for n in (video, clip, thumb, frame)],
                         [False, False, False, True])


def stored(folder) -> set:
    try:
        return set(default_storage.listdir(folder)[1])
    except FileNotFoundError:
        return set()


class PreviewTests(ScenesCase):
    def setUp(self):
        super().setUp()
        self.row = self.create(is_active=True).data
        self.preset = CartoonPreset.objects.get(pk=self.row["id"])
        self.poster = png()

    def upload(self, file, probe=PROBE_OK):
        with patch("ai.video_edit.probe_video", return_value=probe):
            return self.api.post(self.url("studio-scene-preview", self.preset.pk), {"file": file},
                                 format="multipart")

    def test_upload_limits(self):
        logged = self.logs().count()
        cases = [
            (None, "Приложите ролик"),
            (SimpleUploadedFile("clip.mov", MP4_HEAD + b"x"), "Это не MP4"),
            (SimpleUploadedFile("clip.mp4", b"<html>" * 10), "Это не MP4"),
        ]
        for file, words in cases:
            data = {"file": file} if file else {}
            with patch("ai.video_edit.probe_video", return_value=PROBE_OK):
                response = self.api.post(self.url("studio-scene-preview", self.preset.pk), data,
                                         format="multipart")
            self.assertEqual(response.status_code, 400)
            self.assertIn(words, response.data["detail"])
        self.assertIn("не читается", self.upload(mp4(), probe={}).data["detail"])
        self.assertIn("от 1 до 20", self.upload(mp4(), probe={**PROBE_OK, "duration": 31.5}).data["detail"])
        with patch.object(panel, "PREVIEW_MAX_BYTES", 1024):
            self.assertIn("больше", self.upload(mp4()).data["detail"])
        self.preset.refresh_from_db()
        self.assertFalse(self.preset.preview_video)
        self.assertEqual(self.logs().count(), logged)

    def test_upload_builds_clip_poster_and_thumb_in_the_background(self):
        with patch("cartoon.clips.make_clip", return_value=b"light") as clip, \
                patch("ai.video_edit.extract_poster", return_value=self.poster):
            with self.captureOnCommitCallbacks(execute=False) as callbacks:
                response = self.upload(mp4())
                self.assertEqual(response.status_code, 202, response.data)
                # Ответ приходит до сборки: ролик уже на месте, копии собираются.
                self.assertEqual(response.data["preview"]["state"], "building")
                self.assertEqual(response.data["state"], "live")
                self.assertIn(self.preset.slug, self.public())
            clip.assert_not_called()
            self.assertEqual(len(callbacks), 1)
            for callback in callbacks:
                callback()
        row = self.api.get(self.url("studio-scene", self.preset.pk)).data
        self.assertEqual(row["preview"]["state"], "ready", row["preview"])
        self.assertEqual(row["preview"]["notes"], [])
        self.preset.refresh_from_db()
        self.assertTrue(self.preset.preview_video.name.startswith("cartoon/previews/"))
        with default_storage.open(self.preset.preview_clip.name) as fh:
            self.assertEqual(fh.read(), b"light")
        self.assertTrue(self.preset.preview_poster.name.startswith("cartoon/posters/"))
        self.assertTrue(self.preset.preview_thumb.name.startswith("cartoon/posters/thumbs/"))
        # Сайт отдаёт лёгкую копию и миниатюру.
        item = next(p for p in APIClient().get("/api/cartoon/presets/").data["presets"]
                    if p["slug"] == self.preset.slug)
        self.assertEqual(item["preview_video"], self.preset.preview_clip.url)
        self.assertEqual(item["preview_poster"], self.preset.preview_thumb.url)
        log = self.logs().latest("id")
        self.assertEqual(log.after["cartoon_preset"], {"preview_video": self.preset.preview_video.name})

    def test_failed_build_leaves_the_video_and_says_why(self):
        with patch("cartoon.clips.make_clip", return_value=None), \
                patch("ai.video_edit.extract_poster", return_value=None), \
                self.captureOnCommitCallbacks(execute=True):
            self.upload(mp4())
        row = self.api.get(self.url("studio-scene", self.preset.pk)).data
        self.assertEqual(row["preview"]["state"], "partial")
        self.assertEqual(len(row["preview"]["notes"]), 2)
        self.assertTrue(row["preview"]["video"])
        self.assertEqual(row["state"], "live")
        # Пересборка — тот же путь, отметка «собирается».
        with patch("cartoon.clips.make_clip", return_value=b"light"), \
                patch("ai.video_edit.extract_poster", return_value=self.poster), \
                self.captureOnCommitCallbacks(execute=True):
            response = self.api.post(self.url("studio-scene-preview-rebuild", self.preset.pk))
        self.assertEqual(response.status_code, 202)
        self.assertEqual(response.data["preview"]["state"], "building")
        self.assertEqual(self.api.get(self.url("studio-scene", self.preset.pk)).data["preview"]["state"],
                         "ready")

    def test_rebuild_needs_a_video(self):
        response = self.api.post(self.url("studio-scene-preview-rebuild", self.preset.pk))
        self.assertEqual(response.status_code, 400)
        self.assertIn("Сначала загрузите", response.data["detail"])

    def test_build_of_a_replaced_video_is_thrown_away(self):
        name = default_storage.save("cartoon/previews/old.mp4", ContentFile(b"old"))
        CartoonPreset.objects.filter(pk=self.preset.pk).update(preview_video=name)

        def replaced_meanwhile(blob):
            # Пока ffmpeg работал, владелец загрузил другой ролик.
            CartoonPreset.objects.filter(pk=self.preset.pk).update(
                preview_video="cartoon/previews/other.mp4")
            return b"light"

        with patch("cartoon.clips.make_clip", side_effect=replaced_meanwhile), \
                patch("ai.video_edit.extract_poster", return_value=self.poster):
            self.assertFalse(panel.build_preview(self.preset.pk, name))
        self.preset.refresh_from_db()
        self.assertFalse(self.preset.preview_clip)
        self.assertFalse(self.preset.preview_thumb)
        # Собранное ничьё — в хранилище его не осталось.
        self.assertEqual(default_storage.listdir("cartoon/previews/clips")[1], [])
        self.assertEqual(default_storage.listdir("cartoon/posters/thumbs")[1], [])
        # Сборка заведомо прежнего ролика не начинается вовсе.
        with patch("cartoon.clips.make_clip") as clip:
            self.assertFalse(panel.build_preview(self.preset.pk, name))
        clip.assert_not_called()

    def files(self) -> list:
        self.preset.refresh_from_db()
        return [getattr(self.preset, field).name for field in panel.PREVIEW_FIELDS]

    def test_reupload_drops_old_panel_files_but_not_a_users_scene_files(self):
        with patch("cartoon.clips.make_clip", return_value=b"light"), \
                patch("ai.video_edit.extract_poster", return_value=self.poster):
            with self.captureOnCommitCallbacks(execute=True):
                self.upload(mp4())
            first = self.files()
            self.assertTrue(all(first), first)
            with self.captureOnCommitCallbacks(execute=True):
                self.upload(mp4())
            second = self.files()
            self.assertTrue(all(default_storage.exists(n) for n in second), second)
            self.assertEqual([default_storage.exists(n) for n in first], [False] * 4)

            # «Сделать превью сцены» ставит ролик и кадр сцены пользователя: это его
            # файлы. И миниатюру, на которую смотрит другая сцена, не трогаем.
            video = default_storage.save("cartoon/scenes/v.mp4", ContentFile(b"video"))
            frame = default_storage.save("cartoon/keyframes/k.png", ContentFile(self.poster))
            CartoonPreset.objects.filter(pk=self.preset.pk).update(preview_video=video,
                                                                   preview_poster=frame)
            CartoonPreset.objects.filter(pk=self.lib.pk).update(preview_thumb=second[3])
            with self.captureOnCommitCallbacks(execute=True):
                self.upload(mp4())
        self.assertEqual([default_storage.exists(n) for n in (video, frame, second[1], second[3])],
                         [True, True, False, True])

    def test_two_builds_of_one_video_leave_one_set_of_files(self):
        name = default_storage.save(f"cartoon/previews/{self.preset.slug}-0123abcd.mp4",
                                    ContentFile(b"video"))
        CartoonPreset.objects.filter(pk=self.preset.pk).update(preview_video=name)
        folders = ("cartoon/previews/clips", "cartoon/posters", "cartoon/posters/thumbs")
        before = {folder: stored(folder) for folder in folders}
        tabs = []

        def second_tab(blob):
            # Пока первая сборка шла, «Пересобрать» нажали во второй вкладке.
            if not tabs:
                tabs.append(1)
                self.assertTrue(panel.build_preview(self.preset.pk, name))
            return b"light"

        with patch("cartoon.clips.make_clip", side_effect=second_tab), \
                patch("ai.video_edit.extract_poster", return_value=self.poster), \
                self.captureOnCommitCallbacks(execute=True):
            self.assertTrue(panel.build_preview(self.preset.pk, name))
        _video, clip, poster, thumb = self.files()
        left = {folder: stored(folder) - before[folder] for folder in folders}
        self.assertEqual(left, {"cartoon/previews/clips": {clip.rsplit("/", 1)[1]},
                                "cartoon/posters": {poster.rsplit("/", 1)[1]},
                                "cartoon/posters/thumbs": {thumb.rsplit("/", 1)[1]}})

    def test_existing_poster_is_kept_and_only_shrunk(self):
        poster = default_storage.save("cartoon/posters/kept.png", ContentFile(self.poster))
        video = default_storage.save("cartoon/previews/kept.mp4", ContentFile(b"video"))
        CartoonPreset.objects.filter(pk=self.preset.pk).update(preview_video=video,
                                                               preview_poster=poster)
        with patch("cartoon.clips.make_clip", return_value=b"light"), \
                patch("ai.video_edit.extract_poster") as extract:
            self.assertTrue(panel.build_preview(self.preset.pk, video))
        extract.assert_not_called()
        self.preset.refresh_from_db()
        self.assertEqual(self.preset.preview_poster.name, poster)
        self.assertTrue(self.preset.preview_thumb)


class SectionTests(ScenesCase):
    def test_create_edit_and_validation(self):
        url = self.url("studio-sections")
        response = self.api.post(url, {"title": "Новый год", "emoji": "🎄", "title_en": "New Year"},
                                 format="json")
        self.assertEqual(response.status_code, 201, response.data)
        row = response.data
        self.assertEqual((row["slug"], row["sort_order"], row["is_active"], row["scenes"]),
                         ("novyy-god", 30, True, 0))
        for body, words in (({"title": ""}, "обязательно"), ({"title": "x", "emoji": "1" * 9}, "Значок"),
                            ({"title": "x", "sort_order": "1"}, "Порядок"),
                            ({"title": "x", "is_active": "false"}, "true или false"),
                            ({"title": "x", "slug": "adventure"}, "уже занят")):
            response = self.api.post(url, body, format="json")
            self.assertEqual(response.status_code, 400, body)
            self.assertIn(words, response.data["detail"], body)
        detail = self.url("studio-section", row["id"])
        response = self.api.patch(detail, {"title_kg": "Жаңы жыл", "sort_order": 5}, format="json")
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual((response.data["title_kg"], response.data["sort_order"]), ("Жаңы жыл", 5))
        self.assertIn("не меняется", self.api.patch(detail, {"slug": "x"}, format="json").data["detail"])
        self.assertEqual(self.api.patch(self.url("studio-section", 9999), {"title": "x"},
                                        format="json").status_code, 404)
        listed = self.api.get(url).data["results"]
        self.assertEqual([s["slug"] for s in listed], ["novyy-god", "adventure"])
        self.assertEqual(self.logs("cartooncategory").count(), 2)


class PublishFromWorkTests(ScenesCase):
    """«Опубликовать как новую сцену» из «Работ»: только то, где нет личного."""

    def setUp(self):
        super().setUp()
        from plans.models import TokenTransaction

        self.TokenTransaction = TokenTransaction
        self.hero = CartoonCharacter.objects.create(name="Кот", image="cartoon/characters/c.png",
                                                    is_public=True, audience="kids")
        self.mine = CartoonCharacter.objects.create(name="Мой сын", image="cartoon/characters/m.png",
                                                    user=self.user)
        self.video_file = default_storage.save("cartoon/scenes/v.mp4", ContentFile(b"video"))
        self.frame_file = default_storage.save("cartoon/keyframes/k.png", ContentFile(png()))

    def scene(self, hero=None, *, frame_meta=None, **kw):
        project = CartoonProject.objects.create(user=self.user, character=self.hero, aspect_ratio="9:16")
        values = dict(project=project, preset=self.service, character=hero, order=0,
                      status=CartoonScene.STATUS_READY, video=self.video_file, keyframe=self.frame_file,
                      custom_text="кот прыгает в бассейн", custom_title="Кот прыгает",
                      custom_prompt="The character jumps into a pool", custom_motion="splash, camera follows",
                      # Промпт съёмки пишет только сама съёмка: у снятой сцены он есть.
                      video_prompt="0-5s: the character jumps into a pool, splash")
        values.update(kw)
        scene = CartoonScene.objects.create(**values)
        meta = {"scene": scene.pk, "custom": True, "character": (hero or self.hero).pk}
        if frame_meta is not False:
            self.TokenTransaction.objects.create(user=self.user, delta=-4, reason="cartoon_keyframe",
                                                 balance_after=0, meta={**meta, **(frame_meta or {})})
        return scene

    def publish(self, scene):
        return self.api.post(self.url("studio-work-publish-scene", scene.pk), {}, format="json")

    def test_publishes_unpublished_copy_and_second_click_returns_it(self):
        scene = self.scene()
        with patch("cartoon.clips.make_clip", return_value=b"light"), \
                self.captureOnCommitCallbacks(execute=True):
            response = self.publish(scene)
        self.assertEqual(response.status_code, 201, response.data)
        self.assertTrue(response.data["created"])
        row = response.data["preset"]
        self.assertEqual((row["title"], row["is_active"], row["state"], row["audience"], row["aspect_ratio"]),
                         ("Кот прыгает", False, "unpublished", "kids", "9:16"))
        self.assertEqual(row["scene_prompt"], "The character jumps into a pool")
        self.assertEqual(row["motion_prompt"], "splash, camera follows")
        self.assertTrue(row["slug"].startswith("scene-"))
        preset = CartoonPreset.objects.get(pk=row["id"])
        self.assertEqual(preset.style_prompt, STYLE)
        # Копии файлов, а не ссылки на файлы автора.
        self.assertNotEqual(preset.preview_video.name, self.video_file)
        self.assertTrue(preset.preview_video.name.startswith("cartoon/previews/scene-"))
        self.assertTrue(preset.preview_poster.name.startswith("cartoon/posters/scene-"))
        self.assertTrue(preset.preview_clip)
        self.assertTrue(preset.preview_thumb)
        log = self.logs().latest("id")
        self.assertEqual(log.after["cartoon_preset"]["from_scene"], scene.pk)
        self.assertNotIn(row["slug"], self.public())

        again = self.publish(scene)
        self.assertEqual(again.status_code, 200)
        self.assertFalse(again.data["created"])
        self.assertEqual(again.data["preset"]["id"], row["id"])
        self.assertEqual(CartoonPreset.objects.exclude(slug__in=["lib-scene", CUSTOM_PRESET_SLUG]).count(), 1)

    def works_row(self, scene):
        return next(r for r in self.api.get(self.url("studio-works")).data["results"] if r["id"] == scene.pk)

    def test_second_click_finds_the_copy_after_its_prompts_were_edited(self):
        scene = self.scene()
        self.assertIsNone(self.works_row(scene)["library_scene_id"])
        with patch("cartoon.clips.make_clip", return_value=b"light"), \
                self.captureOnCommitCallbacks(execute=True):
            first = self.publish(scene).data["preset"]["id"]
        # Владелец поправил английские промпты новой сцены в «Сценах мультстудии».
        edited = self.api.patch(self.url("studio-scene", first),
                                {"scene_prompt": "The cat jumps into a blue pool", "motion_prompt": "splash"},
                                format="json")
        self.assertEqual(edited.status_code, 200, edited.data)
        # После перезагрузки «Работ» (или у другого сотрудника) кнопки уже нет — есть ссылка.
        self.assertEqual(self.works_row(scene)["library_scene_id"], first)
        again = self.publish(scene)
        self.assertEqual((again.status_code, again.data["created"], again.data["preset"]["id"]),
                         (200, False, first))
        copies = CartoonPreset.objects.exclude(slug__in=["lib-scene", CUSTOM_PRESET_SLUG])
        self.assertEqual(list(copies.values_list("pk", flat=True)), [first])

        # Копию удалили — из сцены можно сделать новую.
        with self.captureOnCommitCallbacks(execute=True):
            self.assertEqual(self.api.delete(self.url("studio-scene", first)).status_code, 204)
        self.assertIsNone(self.works_row(scene)["library_scene_id"])
        with patch("cartoon.clips.make_clip", return_value=b"light"), \
                self.captureOnCommitCallbacks(execute=True):
            self.assertEqual(self.publish(scene).status_code, 201)

    def test_failed_publish_leaves_no_copies(self):
        before = stored("cartoon/previews") | stored("cartoon/posters")
        # Кадр не читается: ролик уже скопирован и должен уйти.
        response = self.publish(self.scene(keyframe="cartoon/keyframes/missing.png"))
        self.assertEqual(response.status_code, 400)
        self.assertIn("не читаются", response.data["detail"])
        with patch.object(panel, "log_admin_action", side_effect=RuntimeError("журнал лёг")), \
                self.assertRaises(RuntimeError):
            panel.publish_from_scene(self.scene().pk, actor=self.staff)
        self.assertEqual(stored("cartoon/previews") | stored("cartoon/posters"), before)
        self.assertEqual(CartoonPreset.objects.count(), 2)

    def test_refusals(self):
        library_scene = self.scene(custom_text="", custom_prompt="")
        CartoonScene.objects.filter(pk=library_scene.pk).update(preset=self.lib)
        cases = [
            (library_scene, "из библиотеки"),
            (self.scene(self.mine), "своим персонажем"),
            (self.scene(dialogue="Привет, мама!"), "реплика"),
            (self.scene(frame_meta={"linked": True, "custom": None}), "прошлую сцену"),
            (self.scene(frame_meta=False), "Не видно"),
            (self.scene(frame_meta={"character": self.mine.pk}), "своим персонажем"),
            (self.scene(custom_prompt=""), "промпт"),
        ]
        for scene, words in cases:
            response = self.publish(scene)
            self.assertEqual(response.status_code, 400, words)
            self.assertIn(words, response.data["detail"])
        self.assertEqual(self.publish(self.scene(status=CartoonScene.STATUS_FAILED)).status_code, 404)
        self.assertEqual(CartoonPreset.objects.count(), 2)

    def test_line_cleared_after_the_shoot_still_blocks(self):
        # Реплику сняли, потом стёрли: ролик тот же и по-прежнему говорит её.
        scene = self.scene(dialogue="Аня, тебе шесть")
        author = APIClient()
        author.force_authenticate(self.user)
        response = author.patch(f"/api/cartoon/scenes/{scene.pk}/", {"dialogue": ""}, format="json")
        self.assertEqual(response.status_code, 200, response.data)
        scene.refresh_from_db()
        self.assertEqual((scene.status, scene.dialogue, scene.video),
                         (CartoonScene.STATUS_READY, "", self.video_file))
        row = next(r for r in self.api.get(self.url("studio-works")).data["results"] if r["id"] == scene.pk)
        self.assertFalse(row["can_publish_scene"])
        self.assertIn("после съёмки", row["publish_scene_note"])
        response = self.publish(scene)
        self.assertEqual(response.status_code, 400)
        self.assertIn("после съёмки", response.data["detail"])
        self.assertEqual(CartoonPreset.objects.count(), 2)

    def test_scene_shot_without_a_line_publishes(self):
        scene = self.scene(dialogue="")
        with patch("cartoon.clips.make_clip", return_value=b"light"), \
                self.captureOnCommitCallbacks(execute=True):
            self.assertEqual(self.publish(scene).status_code, 201)

    def test_a_later_linked_redraw_also_blocks(self):
        scene = self.scene()
        self.TokenTransaction.objects.create(
            user=self.user, delta=-4, reason="cartoon_keyframe", balance_after=0,
            meta={"scene": scene.pk, "linked": True, "character": self.hero.pk})
        self.assertEqual(self.publish(scene).status_code, 400)
