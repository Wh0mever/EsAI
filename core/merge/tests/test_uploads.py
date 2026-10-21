"""Свои видео в склейке (Build MU): приём и все отказы, квота, права, удаление,
уборка, сроки хранения и запуск склейки с загрузкой. ffprobe и ffmpeg подменены."""
from __future__ import annotations

import os
from datetime import timedelta
from unittest.mock import patch

from django.core.files.storage import default_storage
from django.core.files.uploadedfile import SimpleUploadedFile
from django.utils import timezone

from merge import services, tasks, uploads
from merge.models import MergeProject, MergeUpload
from merge.render import Input

from .helpers import MediaTestCase, client_for, probe_ok
from .test_tasks import _fake_poster, _fake_render

BASE = "/api/merge/"
URL = BASE + "uploads/"
MP4 = b"\x00\x00\x00\x18ftypisom\x00\x00\x02\x00isomiso2avc1mp41" + b"\x00" * 200
MOV = b"\x00\x00\x00\x14ftypqt  \x00\x00\x00\x00qt  " + b"\x00" * 200
WEBM = b"\x1a\x45\xdf\xa3\x9f\x42\x86\x81\x01" + b"\x00" * 200
PNG = b"\x89PNG\r\n\x1a\n\x00\x00\x00\x0dIHDR" + b"\x00" * 200


def _poster_ok(src, dst, *, fmt, video_index, duration=None):
    with open(dst, "wb") as fh:
        fh.write(b"JPG")
    return True


class _Uploads(MediaTestCase):
    def setUp(self):
        super().setUp()
        self.owner = self.user(balance=500)
        self.stranger = self.user(balance=500)
        self.api = client_for(self.owner)
        for target, kwargs in (("merge.uploads.free_bytes", {"return_value": 10 ** 13}),
                               ("merge.render.make_upload_poster", {"side_effect": _poster_ok}),
                               ("merge.services.storage_ready", {"return_value": (True, "")})):
            patcher = patch(target, **kwargs)
            setattr(self, target.rsplit(".", 1)[-1], patcher.start())
            self.addCleanup(patcher.stop)

    def send(self, name="IMG_1234.MOV", body=MOV, client=None, query=""):
        upload = SimpleUploadedFile(name, body, content_type="video/quicktime")
        return (client or self.api).post(URL + query, {"file": upload}, format="multipart")

    def folder_files(self, user=None) -> list:
        path = os.path.join(self._media, "merge", "uploads", str((user or self.owner).pk))
        return sorted(os.listdir(path)) if os.path.isdir(path) else []

    def probe_returns(self, **fields):
        self.probe.side_effect = lambda path, fmt="": probe_ok(**fields)

    def refused(self, response, code, status=400):
        self.assertEqual(response.status_code, status, response.content)
        self.assertEqual(response.json()["error_code"], code)
        self.assertEqual(self.folder_files(), [], "отказ не должен оставлять файлов")
        self.assertFalse(MergeUpload.objects.filter(status="ready").exists())
        return response.json()


class UploadAcceptTests(_Uploads):
    def test_upload_returns_a_source_card(self):
        response = self.send()
        self.assertEqual(response.status_code, 201, response.content)
        body = response.json()
        row = MergeUpload.objects.get()
        self.assertEqual(set(body), {"type", "id", "title", "subtitle", "poster", "url", "duration_s",
                                     "width", "height", "created_at", "size_bytes", "has_audio",
                                     "expires_at"})
        self.assertEqual((body["type"], body["id"], body["title"]), ("upload", row.uid, "IMG_1234"))
        folder = f"/media/merge/uploads/{self.owner.pk}/{row.uid}"
        # Имя файла придумывает сервер; QuickTime ложится как .mp4 (тот же ISO-BMFF).
        self.assertEqual((body["url"], body["poster"]), (folder + ".mp4", folder + ".jpg"))
        self.assertEqual((body["duration_s"], body["width"], body["height"]), (5.0, 1280, 720))
        self.assertEqual((body["size_bytes"], body["has_audio"]), (len(MOV), True))
        self.assertAlmostEqual((row.expires_at - row.created_at).total_seconds(), 30 * 86400, delta=5)
        self.assertEqual((row.status, row.video_codec, row.rotation, row.hdr), ("ready", "h264", 0, False))
        self.assertEqual(self.folder_files(), [f"{row.uid}.jpg", f"{row.uid}.mp4"])
        # Разбор строгий: демуксер задан по первым байтам файла.
        path, fmt = self.probe.call_args.args
        self.assertTrue(path.endswith(f"{row.uid}.mp4"))
        self.assertEqual(fmt, "mov")
        self.assertEqual(self.make_upload_poster.call_args.kwargs["fmt"], "mov")

    def test_body_above_memory_limit_streams_through_a_temp_file(self):
        # Файл больше FILE_UPLOAD_MAX_MEMORY_SIZE (2,5 МБ) идёт через временный файл,
        # а DATA_UPLOAD_MAX_MEMORY_SIZE файлы не считает: настройки менять не нужно.
        from django.conf import settings

        body = MOV + b"\x00" * (3 * 1024 * 1024)
        self.assertGreater(len(body), settings.FILE_UPLOAD_MAX_MEMORY_SIZE)
        self.assertGreater(len(body), settings.DATA_UPLOAD_MAX_MEMORY_SIZE)
        response = self.send(body=body)
        self.assertEqual(response.status_code, 201, response.content)
        row = MergeUpload.objects.get()
        self.assertEqual((row.size, default_storage.size(row.file)), (len(body), len(body)))

    def test_webm_bytes_are_read_as_matroska(self):
        # Расширение — лишь первый фильтр: тип решают байты.
        response = self.send("clip.mp4", WEBM)
        self.assertEqual(response.status_code, 201)
        row = MergeUpload.objects.get()
        self.assertTrue(row.file.endswith(".webm"))
        self.assertEqual((row.container, self.probe.call_args.args[1]), ("matroska", "matroska"))

    def test_rotated_phone_clip_has_display_size(self):
        self.probe_returns(width=1920, height=1080, rotation=90)
        body = self.send().json()
        self.assertEqual((body["width"], body["height"]), (1080, 1920))
        row = MergeUpload.objects.get()
        self.assertEqual((row.width, row.height, row.display_width, row.display_height, row.rotation),
                         (1920, 1080, 1080, 1920, 90))

    def test_silent_hdr_clip(self):
        self.probe_returns(audio=False, codec="hevc", hdr=True)
        body = self.send().json()
        self.assertFalse(body["has_audio"])
        row = MergeUpload.objects.get()
        self.assertEqual((row.video_codec, row.hdr, row.has_audio), ("hevc", True, False))

    def test_title_is_only_a_sanitized_label(self):
        body = self.send("Отпуск на море " + "x" * 200 + ".mp4", MP4).json()
        self.assertTrue(body["title"].startswith("Отпуск на море xx"))
        self.assertEqual(len(body["title"]), 80)
        self.assertTrue(body["title"].endswith("…"))
        self.assertNotIn("Отпуск", MergeUpload.objects.get().file)
        # Папки, расширение, переворот строки, нулевая ширина и табуляция — прочь.
        rtl, zero_width = chr(0x202E), chr(0x200B)
        name = "C:/fakepath/Отпуск" + rtl + "\tна" + zero_width + " море.MOV"
        self.assertEqual(uploads.clean_title(name), "Отпуск на море")
        self.assertEqual(uploads.clean_title("..\\..\\etc\\passwd"), "passwd")

    def test_nameless_file_gets_a_title_in_the_page_language(self):
        body = self.send("   .mp4", MP4, query="?lang=en").json()
        self.assertEqual(body["title"], "My video")
        self.assertEqual(MergeUpload.objects.get().title, "")

    def test_guest_is_401(self):
        response = self.send(client=client_for())
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json()["error_code"], "unauthorized")

    def test_config_lists_upload_limits(self):
        body = client_for().get(BASE + "config/").json()
        self.assertIn("upload", body["source_types"])
        self.assertEqual(body["uploads"]["max_bytes"], 90 * 1024 * 1024)
        self.assertEqual((body["uploads"]["max_duration_s"], body["uploads"]["max_per_project"],
                          body["uploads"]["max_files"], body["uploads"]["max_total_mb"]), (60, 3, 10, 600))
        self.assertEqual(body["uploads"]["extensions"], ["mp4", "mov", "m4v", "webm"])
        self.assertEqual(body["uploads"]["max_fps"], 120)


class UploadRefusalTests(_Uploads):
    def test_no_file_field(self):
        response = self.api.post(URL, {"video": "x"}, format="multipart")
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json(), {"error": "Выберите видео для загрузки.",
                                           "error_code": "bad_request", "field": "file"})

    def test_declared_body_too_big_is_refused_before_reading_it(self):
        with patch("merge.uploads.UPLOAD_MAX_BYTES", 100), patch("merge.uploads.MULTIPART_SLACK", 0):
            body = self.refused(self.send(), "upload_too_big")
        self.assertEqual(body["error"], "Файл больше 90 МБ. Сожмите или обрежьте видео и загрузите снова.")
        self.probe.assert_not_called()
        self.assertFalse(MergeUpload.objects.exists())

    def test_file_too_big(self):
        with patch("merge.uploads.UPLOAD_MAX_BYTES", 100):
            self.refused(self.send(), "upload_too_big")
        self.probe.assert_not_called()
        rejected = MergeUpload.objects.get()
        self.assertEqual((rejected.status, rejected.error_code, rejected.file, rejected.title),
                         ("rejected", "upload_too_big", "", "IMG_1234"))

    def test_wrong_extension(self):
        body = self.refused(self.send("clip.avi", MP4), "upload_bad_type")
        self.assertEqual(body["error"], "Подходят только видео MP4, MOV или WebM.")
        self.assertEqual(body["extensions"], ["mp4", "mov", "m4v", "webm"])
        self.probe.assert_not_called()

    def test_png_renamed_to_mp4(self):
        self.refused(self.send("photo.mp4", PNG), "upload_bad_type")
        self.probe.assert_not_called()
        self.assertEqual(MergeUpload.objects.get().error_code, "upload_bad_type")

    def test_heic_photo_and_m4a_audio_are_not_videos(self):
        for brand in (b"heic", b"mif1", b"avif", b"M4A "):
            body = b"\x00\x00\x00\x18ftyp" + brand + b"\x00" * 200
            self.refused(self.send("clip.mov", body), "upload_bad_type")
        self.probe.assert_not_called()

    def test_empty_file(self):
        self.refused(self.send("clip.mp4", b""), "upload_unreadable")

    def test_unreadable_file_is_deleted(self):
        self.probe.side_effect = lambda path, fmt="": None
        body = self.refused(self.send(), "upload_unreadable")
        self.assertEqual(body["error"], "Файл не читается — возможно, он повреждён. Выберите другое видео.")
        self.assertEqual(MergeUpload.objects.get().error_code, "upload_unreadable")

    def test_no_video_stream(self):
        self.probe_returns(video_streams=0, codec="", video_index=None)
        body = self.refused(self.send(), "upload_no_video")
        self.assertEqual(body["error"], "В файле нет подходящего видео: нужна одна видеодорожка "
                                        "H.264, HEVC, VP8, VP9, AV1 или MPEG-4.")

    def test_several_video_tracks(self):
        self.probe_returns(video_streams=2)
        self.refused(self.send(), "upload_no_video")

    def test_unknown_codec(self):
        for codec in ("prores", "mjpeg", ""):
            self.probe_returns(codec=codec)
            self.refused(self.send(), "upload_no_video")

    def test_too_long(self):
        self.probe_returns(duration=61.0)
        body = self.refused(self.send(), "upload_too_long")
        self.assertEqual(body["error"], "Видео длиннее 60 секунд. Обрежьте его и загрузите снова.")
        self.assertEqual((body["max_s"], body["duration_s"]), (60, 61.0))

    def test_one_minute_trim_is_still_a_minute(self):
        self.probe_returns(duration=60.4)
        self.assertEqual(self.send().status_code, 201)

    def test_too_short(self):
        self.probe_returns(duration=0.3)
        body = self.refused(self.send(), "upload_too_short")
        self.assertEqual(body["error"], "Видео короче полсекунды — такое не склеить.")

    def test_frame_too_big(self):
        self.probe_returns(width=4100, height=2000)
        body = self.refused(self.send(), "upload_resolution")
        self.assertEqual((body["max_side"], body["width"], body["height"]), (4096, 4100, 2000))

    def test_4k_is_fine(self):
        self.probe_returns(width=4096, height=2160)
        self.assertEqual(self.send().status_code, 201)

    def test_frame_rate_above_120_is_refused(self):
        # MU_R1 B1: 6,7 МБ на 60 с и тысячи кадров в секунду держали слот media 600 с — бесплатно.
        self.probe_returns(duration=60.0, frames=60 * 6000)
        body = self.refused(self.send(), "upload_frame_rate")
        self.assertEqual(body["error"], "В видео больше 120 кадров в секунду — такое не склеить. "
                                        "Сохраните его с частотой 30 или 60 кадров и загрузите снова.")
        self.assertEqual((body["max_fps"], body["fps"]), (120, 6000))
        self.assertEqual(MergeUpload.objects.get().error_code, "upload_frame_rate")
        self.probe_returns(duration=3.0, frames=3 * 120 + 31)
        self.assertEqual(self.refused(self.send(), "upload_frame_rate")["fps"], 130)

    def test_slow_motion_at_120_fps_is_fine(self):
        for duration, frames in ((60.0, 60 * 120), (3.0, 3 * 120 + 30), (0.5, 90)):
            with self.subTest(duration=duration, frames=frames):
                self.probe_returns(duration=duration, frames=frames)
                self.assertEqual(self.send().status_code, 201)

    def test_frames_not_counted_is_unreadable(self):
        # Нет счёта пакетов — судить о цене файла не по чему: в склейку не берём.
        self.probe_returns(frames=None)
        self.refused(self.send(), "upload_unreadable")

    def test_frame_that_does_not_decode(self):
        self.make_upload_poster.side_effect = None
        self.make_upload_poster.return_value = False
        self.refused(self.send(), "upload_unreadable")

    def test_low_disk(self):
        self.free_bytes.return_value = 1024 ** 3
        body = self.refused(self.send(), "upload_unavailable", 503)
        self.assertEqual(body["error"], "Загрузка сейчас недоступна: на сервере не хватает места. "
                                        "Попробуйте позже.")
        self.probe.assert_not_called()
        self.assertFalse(MergeUpload.objects.exists())

    def test_twenty_uploads_an_hour(self):
        for _ in range(20):
            self.assertEqual(self.send("clip.avi", MP4).status_code, 400)
        response = self.send("clip.avi", MP4)
        self.assertEqual(response.status_code, 429)
        self.assertEqual(response.json()["error_code"], "throttled")
        # Чужой счётчик свой.
        self.assertEqual(self.send(client=client_for(self.stranger)).status_code, 201)


class UploadSlotAndDrainTests(_Uploads):
    """Одна загрузка за раз у человека; тело отказа дочитывается (иначе nginx отдаёт 502)."""

    def raw(self, user=None, size=3 * 1024 * 1024):
        from rest_framework.test import APIRequestFactory, force_authenticate

        upload = SimpleUploadedFile("clip.mov", MOV + b"\x00" * size, content_type="video/quicktime")
        request = APIRequestFactory().post(URL, {"file": upload}, format="multipart")
        if user is not None:
            force_authenticate(request, user)
        return request

    def test_second_upload_while_the_first_runs_is_refused(self):
        from django.core.cache import cache

        key = f"merge:upload:{self.owner.pk}"
        cache.add(key, 1, 60)
        response = self.send()
        self.assertEqual(response.status_code, 429)
        self.assertEqual(response.json(), {"error": "Уже загружается другое видео. Дождитесь окончания "
                                                    "и загрузите следующее.", "error_code": "upload_busy"})
        self.probe.assert_not_called()
        self.assertFalse(MergeUpload.objects.exists())
        # Другой человек грузит своё; первая загрузка закончилась — место свободно.
        self.assertEqual(self.send(client=client_for(self.stranger)).status_code, 201)
        cache.delete(key)
        self.assertEqual(self.send().status_code, 201)
        self.assertIsNone(cache.get(key))
        self.assertEqual(self.send("clip.avi", MP4).status_code, 400)
        self.assertIsNone(cache.get(key), "отказ тоже освобождает место")

    def test_cache_failure_does_not_block_uploads(self):
        with patch("merge.views.cache.add", side_effect=RuntimeError("redis down")), \
                self.assertLogs("merge.views", level="WARNING"):
            self.assertEqual(self.send().status_code, 201)

    def test_refusals_read_the_body_to_the_end(self):
        from django.db import transaction

        from merge.views import UploadsView

        def view(request):
            # Как у настоящего запроса (ATOMIC_REQUESTS): отказ откатывает только свой savepoint.
            with transaction.atomic():
                return UploadsView.as_view()(request)

        guest = self.raw()
        self.assertEqual(view(guest).status_code, 401)
        self.assertEqual(guest.read(), b"")
        for _ in range(10):
            self.upload(self.owner)
        full = self.raw(self.owner)
        self.assertEqual(view(full).status_code, 409)
        self.assertEqual(full.read(), b"")
        # Без дочитывания тело так и осталось бы в сокете — проверка не пустая.
        with patch("merge.views.drain_body"):
            kept = self.raw()
            self.assertEqual(view(kept).status_code, 401)
        self.assertGreater(len(kept.read()), 3 * 1024 * 1024)

    def test_drain_stops_at_its_limit(self):
        from merge.views import drain_body

        request = self.raw(size=3 * 1024 * 1024)
        self.assertEqual(drain_body(request, limit=1024 * 1024 + 5), 1024 * 1024 + 5)
        self.assertGreater(len(request.read()), 1024 * 1024)


class UploadQuotaTests(_Uploads):
    def test_ten_files_are_refused_before_reading_the_body(self):
        for _ in range(10):
            self.upload(self.owner)
        response = self.send()
        self.assertEqual(response.status_code, 409)
        body = response.json()
        self.assertEqual(body["error_code"], "upload_quota")
        self.assertEqual(body["error"], "Место для своих видео занято: хранится до 10 файлов и до 600 МБ. "
                                        "Удалите старые в «Моих файлах» и загрузите снова.")
        self.assertEqual((body["max_files"], body["max_mb"], body["files"]), (10, 600, 10))
        self.probe.assert_not_called()
        self.assertEqual(MergeUpload.objects.count(), 10)

    def test_total_size(self):
        self.upload(self.owner, size=600 * 1024 * 1024 - 100)
        response = self.send()
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["error_code"], "upload_quota")
        self.assertEqual(MergeUpload.objects.count(), 1)

    def test_expired_rejected_and_strangers_do_not_count(self):
        for _ in range(10):
            self.upload(self.stranger)
        expired = [self.upload(self.owner, expires_in=-60) for _ in range(9)]
        for _ in range(5):
            MergeUpload.objects.create(user=self.owner, status="rejected", error_code="upload_bad_type")
        self.upload(self.owner)
        self.assertEqual(self.send().status_code, 201)
        # Свои истёкшие стёрты сразу при загрузке — вместе с файлами.
        self.assertFalse(MergeUpload.objects.filter(pk__in=[u.pk for u in expired]).exists())
        self.assertFalse(default_storage.exists(expired[0].file))

    def test_quota_is_checked_again_under_the_lock(self):
        # Пока файл разбирался, вторая загрузка заняла последнее место.
        def probe(path, fmt=""):
            for _ in range(10):
                self.upload(self.owner)
            return probe_ok()

        self.probe.side_effect = probe
        response = self.send()
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["error_code"], "upload_quota")
        self.assertEqual(len(self.folder_files()), 20, "остались только файлы десяти занявших место")
        self.assertFalse(MergeUpload.objects.filter(status="rejected").exists())


class UploadListTests(_Uploads):
    def test_my_files_lists_only_own_live_uploads(self):
        old = self.upload(self.owner)
        new = self.upload(self.owner, has_audio=False)
        self.upload(self.owner, expires_in=-1)
        self.upload(self.owner, with_file=False)
        self.upload(self.stranger)
        MergeUpload.objects.create(user=self.owner, status="rejected", error_code="upload_too_long")
        MergeUpload.objects.filter(pk=old.pk).update(created_at=timezone.now() - timedelta(hours=1))
        body = self.api.get(URL).json()
        self.assertEqual([c["id"] for c in body["results"]], [new.uid, old.uid])
        self.assertFalse(body["results"][0]["has_audio"])
        self.assertEqual(body["usage"]["max_files"], 10)
        self.assertEqual(body["limits"]["max_per_project"], 3)
        picker = self.api.get(BASE + "sources/?type=upload").json()
        self.assertEqual([c["id"] for c in picker["results"]], [new.uid, old.uid])
        self.assertEqual(picker["results"][0]["type"], "upload")
        self.assertEqual(client_for(self.stranger).get(URL).json()["usage"]["files"], 1)


class UploadInMergeTests(_Uploads):
    def test_upload_goes_into_a_merge_like_any_fragment(self):
        clip = self.upload(self.owner, display_width=1080, display_height=1920, rotation=90)
        take = self.take(self.owner)
        response = self.api.post(BASE, {"items": [self.ref(clip), self.ref(take)]}, format="json")
        self.assertEqual(response.status_code, 201, response.content)
        first = response.json()["items"][0]
        self.assertEqual((first["type"], first["id"], first["available"]), ("upload", clip.uid, True))
        self.assertEqual((first["width"], first["height"], first["size_bytes"]), (1080, 1920, 1000))
        self.assertTrue(response.json()["can_render"])

    def test_someone_elses_upload_is_not_available(self):
        theirs = self.upload(self.stranger)
        response = self.api.post(BASE, {"items": [self.ref(theirs)]}, format="json")
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["error_code"], "source_unavailable")

    def test_expired_upload_is_not_available(self):
        clip = self.upload(self.owner, expires_in=-1)
        response = self.api.post(BASE, {"items": [self.ref(clip)]}, format="json")
        self.assertEqual(response.json()["error_code"], "source_unavailable")

    def test_at_most_three_uploads_per_merge(self):
        clips = [self.upload(self.owner) for _ in range(4)]
        ok = self.api.post(BASE, {"items": [self.ref(c) for c in clips[:3]]}, format="json")
        self.assertEqual(ok.status_code, 201)
        project = ok.json()["id"]
        for items in ([self.ref(c) for c in clips], [self.ref(clips[0])] * 4):
            response = self.api.patch(f"{BASE}{project}/", {"items": items}, format="json")
            self.assertEqual(response.status_code, 400)
            self.assertEqual(response.json(), {"error": "В одной склейке — не больше 3 своих видео.",
                                               "error_code": "too_many_uploads", "max": 3})

    def test_deleted_upload_shows_as_unavailable_in_a_draft(self):
        clip = self.upload(self.owner)
        project = self.project(self.owner, [clip, self.take(self.owner)])
        with self.captureOnCommitCallbacks(execute=True):
            self.assertEqual(self.api.delete(f"{URL}{clip.uid}/").status_code, 204)
        body = self.api.get(f"{BASE}{project.uid}/").json()
        self.assertEqual((body["items"][0]["available"], body["items"][0]["url"]), (False, None))
        self.assertEqual(body["render_block"]["error_code"], "source_unavailable")

    def test_ready_merge_shows_a_deleted_upload_as_unavailable(self):
        # MU_R2 W1: удалили своё видео из готовой склейки — ▶ не должен вести на 404, а
        # «склеить заново» видит, что фрагмента больше нет.
        clip, kept, take = self.upload(self.owner), self.upload(self.owner), self.take(self.owner)
        project = self.project(self.owner, [clip, take, kept], status="ready")
        body = self.api.get(f"{BASE}{project.uid}/").json()
        self.assertEqual([i["available"] for i in body["items"]], [True, True, True])
        self.assertTrue(body["items"][0]["url"].endswith(clip.file))
        with self.captureOnCommitCallbacks(execute=True):
            self.assertEqual(self.api.delete(f"{URL}{clip.uid}/").status_code, 204)
        MergeUpload.objects.filter(pk=kept.pk).update(expires_at=timezone.now() - timedelta(minutes=1))
        body = self.api.get(f"{BASE}{project.uid}/").json()
        gone, ours, expired = body["items"]
        self.assertEqual((gone["available"], gone["url"], gone["poster"]), (False, None, None))
        self.assertEqual((gone["title"], gone["duration_s"]), (clip.title, clip.duration_s))
        self.assertTrue(ours["available"])
        self.assertFalse(expired["available"])
        self.assertIsNone(body["render_block"])

    def test_render_holds_the_uploads(self):
        clip = self.upload(self.owner, expires_in=60)
        later = self.upload(self.owner, expires_in=timedelta(days=20))
        project = self.project(self.owner, [clip, later])
        started, fresh = services.start_render(self.owner, project.uid)
        self.assertTrue(fresh)
        clip.refresh_from_db()
        later.refresh_from_db()
        self.assertGreater(clip.expires_at, timezone.now() + timedelta(hours=23))
        self.assertGreater(later.expires_at, timezone.now() + timedelta(days=19), "сроки не укорачиваются")

    def test_finished_merge_keeps_its_uploads_as_long_as_itself(self):
        clip = self.upload(self.owner)
        project = self.project(self.owner, [clip, self.take(self.owner)], status="queued",
                               credits_reserved=20, queued_at=timezone.now())
        seen = []

        def spy(paths, **kw):
            seen.extend(paths)
            return _fake_render()(paths, **kw)

        with patch("merge.services.ffmpeg.render", side_effect=spy), \
                patch("merge.services.ffmpeg.make_poster", side_effect=_fake_poster):
            self.assertEqual(tasks.render_merge.run(project.pk)["status"], "ready")
        project.refresh_from_db()
        clip.refresh_from_db()
        self.assertEqual(clip.expires_at, project.expires_at)
        # Своё видео уходит в ffmpeg со строгим чтением, наше — просто путём.
        self.assertIsInstance(seen[0], Input)
        self.assertEqual(seen[0].fmt, "mov")
        self.assertTrue(seen[0].path.endswith(clip.file.rsplit("/", 1)[-1]))
        self.assertIsInstance(seen[1], str)

    def test_webm_upload_is_read_as_matroska_in_the_render(self):
        clip = self.upload(self.owner, ext="webm")
        project = self.project(self.owner, [self.take(self.owner), clip], status="queued",
                               credits_reserved=20, queued_at=timezone.now())
        seen = []

        def spy(paths, **kw):
            seen.extend(paths)
            return _fake_render()(paths, **kw)

        with patch("merge.services.ffmpeg.render", side_effect=spy), \
                patch("merge.services.ffmpeg.make_poster", side_effect=_fake_poster):
            tasks.render_merge.run(project.pk)
        self.assertEqual(seen[1].fmt, "matroska")


class UploadDeleteTests(_Uploads):
    def test_owner_deletes_file_and_row(self):
        clip = self.upload(self.owner)
        with self.captureOnCommitCallbacks(execute=True):
            response = self.api.delete(f"{URL}{clip.uid}/")
        self.assertEqual(response.status_code, 204)
        self.assertFalse(MergeUpload.objects.exists())
        self.assertFalse(default_storage.exists(clip.file))
        self.assertFalse(default_storage.exists(clip.poster))

    def test_someone_elses_upload_is_404(self):
        theirs = self.upload(self.stranger)
        response = self.api.delete(f"{URL}{theirs.uid}/")
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json(), {"error": "Видео не найдено.", "error_code": "upload_not_found"})
        self.assertTrue(MergeUpload.objects.filter(pk=theirs.pk).exists())
        rejected = MergeUpload.objects.create(user=self.owner, status="rejected")
        self.assertEqual(self.api.delete(f"{URL}{rejected.uid}/").status_code, 404)

    def test_not_while_it_is_being_merged(self):
        clip = self.upload(self.owner)
        project = self.project(self.owner, [clip, self.take(self.owner)], status="rendering",
                               credits_reserved=20)
        response = self.api.delete(f"{URL}{clip.uid}/")
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json(), {"error": "Это видео сейчас склеивается — удалить его можно "
                                                    "после окончания.", "error_code": "upload_in_use"})
        self.assertTrue(default_storage.exists(clip.file))
        # Черновик и готовая склейка удалению не мешают.
        MergeProject.objects.filter(pk=project.pk).update(status="ready", credits_reserved=0)
        self.assertEqual(self.api.delete(f"{URL}{clip.uid}/").status_code, 204)

    def test_account_deletion_removes_the_files(self):
        clip = self.upload(self.owner)
        with self.captureOnCommitCallbacks(execute=True):
            self.owner.delete()
        self.assertFalse(default_storage.exists(clip.file))
        self.assertFalse(default_storage.exists(clip.poster))


class UploadCleanupTests(_Uploads):
    def expire(self, *clips):
        MergeUpload.objects.filter(pk__in=[c.pk for c in clips]).update(
            expires_at=timezone.now() - timedelta(minutes=1))

    def test_daily_task_deletes_expired_unused_uploads(self):
        gone, in_draft, merging = (self.upload(self.owner) for _ in range(3))
        fresh = self.upload(self.owner, expires_in=3600)
        self.project(self.owner, [in_draft, self.take(self.owner)])
        self.project(self.owner, [merging, self.take(self.owner)], status="rendering", credits_reserved=20)
        self.expire(gone, in_draft, merging)
        old_reject = MergeUpload.objects.create(user=self.stranger, status="rejected",
                                                expires_at=timezone.now() - timedelta(minutes=1))
        self.assertEqual(tasks.purge_expired.run(), {"merges": 0, "uploads": 3})
        left = set(MergeUpload.objects.values_list("pk", flat=True))
        self.assertEqual(left, {merging.pk, fresh.pk})
        self.assertNotIn(old_reject.pk, left)
        for clip in (gone, in_draft):
            self.assertFalse(default_storage.exists(clip.file))
            self.assertFalse(default_storage.exists(clip.poster))
        self.assertTrue(default_storage.exists(merging.file))
        self.assertTrue(default_storage.exists(fresh.file))

    def test_cleanup_goes_through_every_batch(self):
        for _ in range(5):
            self.upload(self.owner, expires_in=-60)
        busy = self.upload(self.owner)
        self.project(self.owner, [busy, self.take(self.owner)], status="queued", credits_reserved=20,
                     queued_at=timezone.now())
        self.expire(busy)
        self.assertEqual(uploads.purge(batch=2), 5)
        self.assertEqual(list(MergeUpload.objects.values_list("pk", flat=True)), [busy.pk])

    def test_rejected_rows_do_not_eat_the_budget_of_accepted_ones(self):
        # MU_R1 W7: отказы (до 20 в час на человека) стираются отдельно и первыми.
        old = timezone.now() - timedelta(minutes=1)
        for _ in range(7):
            MergeUpload.objects.create(user=self.stranger, status="rejected", expires_at=old)
        live_reject = MergeUpload.objects.create(user=self.stranger, status="rejected")
        clips = [self.upload(self.owner, expires_in=-60) for _ in range(3)]
        with patch("merge.uploads.PURGE_REJECTED_BATCH", 2), patch("merge.uploads.PURGE_MAX_BATCHES", 1):
            self.assertEqual(uploads.purge(batch=3), 10)
        self.assertEqual(list(MergeUpload.objects.values_list("pk", flat=True)), [live_reject.pk])
        for clip in clips:
            self.assertFalse(default_storage.exists(clip.file))
