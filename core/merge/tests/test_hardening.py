"""Правки после ревью склейки: нагрузка на API, оплаченный ролик, диск, язык подписей."""
from __future__ import annotations

import os
import tempfile
from contextlib import suppress
from datetime import timedelta
from unittest.mock import patch

from celery.exceptions import SoftTimeLimitExceeded
from django.core.files.storage import FileSystemStorage, default_storage
from django.db import transaction
from django.test import SimpleTestCase
from django.utils import timezone

from ai.models import GenerationLog
from cartoon.models import CartoonProject
from merge import render, services, sources, storage, tasks, views
from merge.models import MergeProject
from plans.models import TokenTransaction

from .helpers import MediaTestCase, client_for, store
from .test_tasks import _fake_poster, _fake_render

BASE = "/api/merge/"


def _ready(test, owner, name="r"):
    return test.project(owner, status="ready", result_video=store(f"merge/{owner.pk}/{name}.mp4", b"MP4"),
                        poster=store(f"merge/{owner.pk}/{name}.jpg", b"JPG"), finished_at=timezone.now(),
                        expires_at=timezone.now() + timedelta(days=30))


class DownloadLoadTests(MediaTestCase):
    """Скачивание не должно держать потоки API, общие с чатом, входом и оплатой."""

    def setUp(self):
        super().setUp()
        self.owner = self.user()
        self.ready = _ready(self, self.owner)
        self.url = f"{BASE}{self.ready.uid}/download/"

    def test_nginx_is_asked_to_buffer_the_file(self):
        # /api/ в nginx — proxy_buffering off: без заголовка поток gunicorn занят всё скачивание.
        response = client_for(self.owner).get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["X-Accel-Buffering"], "yes")
        self.assertEqual(b"".join(response.streaming_content), b"MP4")
        response.close()

    def test_at_most_two_downloads_per_owner_at_once(self):
        api = client_for(self.owner)
        first, second = api.get(self.url), api.get(self.url)
        self.assertEqual((first.status_code, second.status_code), (200, 200))
        third = api.get(self.url)
        self.assertEqual(third.status_code, 429)
        self.assertEqual(third.json()["error_code"], "downloads_busy")
        self.assertEqual(third.json()["error"],
                         "Этот ролик уже скачивается. Дождитесь окончания и попробуйте снова.")
        # Ссылка ?t= без входа считается в те же места владельца.
        link = api.get(f"{BASE}{self.ready.uid}/").json()["download_url"]
        self.assertEqual(client_for().get(link).status_code, 429)
        # Закончилась одна отдача — место освободилось.
        b"".join(first.streaming_content)
        first.close()
        fourth = api.get(self.url)
        self.assertEqual(fourth.status_code, 200)
        for response in (second, fourth):
            response.close()
        self.assertEqual(api.get(self.url).status_code, 200)

    def test_owners_are_counted_separately(self):
        other = self.user()
        other_ready = _ready(self, other, "o")
        api = client_for(self.owner)
        held = [api.get(self.url), api.get(self.url)]
        response = client_for(other).get(f"{BASE}{other_ready.uid}/download/")
        self.assertEqual(response.status_code, 200)
        for item in (*held, response):
            item.close()

    def test_place_is_released_when_the_file_is_gone(self):
        default_storage.delete(self.ready.result_video)
        api = client_for(self.owner)
        for _ in range(3):
            self.assertEqual(api.get(self.url).status_code, 410)
        self.assertEqual(views.cache.get(views._slot_key(self.owner.pk)), 0)

    def test_broken_counter_does_not_block_the_owner(self):
        with patch("merge.views.cache") as broken:
            broken.add.side_effect = ConnectionError("redis down")
            response = client_for(self.owner).get(self.url)
        self.assertEqual(response.status_code, 200)
        response.close()


class PaidResultTests(MediaTestCase):
    def setUp(self):
        super().setUp()
        self.owner = self.user(balance=100)
        self.project_ = self.project(self.owner, [self.take(self.owner), self.scene(self.owner)],
                                     status="queued", credits_reserved=20, queued_at=timezone.now())

    def _run(self, finish):
        with patch("merge.services._finish", side_effect=finish), \
                patch("merge.services.ffmpeg.render", side_effect=_fake_render()), \
                patch("merge.services.ffmpeg.make_poster", side_effect=_fake_poster):
            result = tasks.render_merge.run(self.project_.pk)
        self.project_.refresh_from_db()
        return result

    def test_signal_right_after_the_charge_keeps_the_paid_file(self):
        # Мягкий лимит между коммитом _finish и return: ролик оплачен — стирать его нельзя.
        real_finish = services._finish

        def finish_then_signal(*args, **kwargs):
            real_finish(*args, **kwargs)
            raise SoftTimeLimitExceeded()

        self._run(finish_then_signal)
        self.assertEqual((self.project_.status, self.project_.credits_charged), ("ready", 20))
        self.assertTrue(default_storage.exists(self.project_.result_video))
        self.assertTrue(default_storage.exists(self.project_.poster))
        self.assertEqual(self.balance(self.owner), 80)
        self.assertEqual(TokenTransaction.objects.filter(user=self.owner).count(), 1)

    def test_files_of_an_unpaid_delivery_are_still_removed(self):
        self._run(services._Gone())
        folder = os.path.join(self._media, "merge", str(self.owner.pk))
        self.assertEqual(os.listdir(folder), [])
        self.assertEqual(self.balance(self.owner), 100)

    def test_unknown_owner_of_files_keeps_them(self):
        with patch("merge.services.MergeProject.objects.filter", side_effect=RuntimeError("db")):
            services._discard(self.project_.pk, [store("merge/x/keep.mp4")])
        self.assertTrue(default_storage.exists("merge/x/keep.mp4"))


class DiskTests(MediaTestCase):
    def setUp(self):
        super().setUp()
        self.owner = self.user()
        self.api = client_for(self.owner)
        patcher = patch("merge.services.storage_ready", return_value=(True, ""))
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_ready_merges_are_capped(self):
        with patch("merge.services.MAX_READY", 2):
            first = _ready(self, self.owner, "a")
            _ready(self, self.owner, "b")
            draft = self.project(self.owner, [self.take(self.owner), self.scene(self.owner)])
            refused = self.api.post(f"{BASE}{draft.uid}/render/", {"price": 20}, format="json")
            self.assertEqual(refused.status_code, 409)
            body = refused.json()
            self.assertEqual((body["error_code"], body["max"]), ("too_many_ready", 2))
            self.assertEqual(body["error"], "Готовых склеек: 2 — больше хранить нельзя. Скачайте нужные и "
                                            "удалите лишние в «Моих склейках», чтобы склеить новую.")
            draft.refresh_from_db()
            self.assertEqual((draft.status, draft.credits_reserved), ("draft", 0))
            self.assertEqual(self.balance(self.owner), 500)
            self.assertEqual(self.api.delete(f"{BASE}{first.uid}/").status_code, 204)
            with patch("merge.tasks.render_merge.delay"):
                started = self.api.post(f"{BASE}{draft.uid}/render/", {"price": 20}, format="json")
            self.assertEqual(started.status_code, 202)

    def test_expired_merges_do_not_count_toward_the_project_cap(self):
        with patch("merge.services.MAX_PROJECTS", 2):
            self.project(self.owner, status="expired")
            self.project(self.owner, status="expired")
            self.project(self.owner)
            self.assertEqual(self.api.post(BASE, {}, format="json").status_code, 201)
            refused = self.api.post(BASE, {}, format="json")
        self.assertEqual(refused.status_code, 409)
        self.assertEqual(refused.json()["error_code"], "too_many_projects")

    def test_backlog_beyond_one_batch_is_purged_in_one_run(self):
        past = timezone.now() - timedelta(minutes=1)
        names = []
        for i in range(5):
            name = store(f"merge/{self.owner.pk}/old{i}.mp4")
            names.append(name)
            self.project(self.owner, status="ready", result_video=name, expires_at=past)
        self.assertEqual(services.purge_expired(batch=2), 5)
        self.assertFalse(MergeProject.objects.filter(status="ready").exists())
        self.assertFalse(any(default_storage.exists(n) for n in names))

    def test_partial_file_is_removed_when_the_disk_fills_up(self):
        def fill_disk(self_, name, content):
            path = self_.path(name)
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "wb") as fh:
                fh.write(b"half")
            raise OSError(28, "No space left on device")

        src = self._source_file()
        with patch.object(FileSystemStorage, "_save", fill_disk), self.assertRaises(OSError):
            storage.save_file("merge/7/x-1.mp4", src)
        self.assertFalse(default_storage.exists("merge/7/x-1.mp4"))

    def test_failed_save_never_deletes_a_file_it_did_not_write(self):
        store("merge/7/x-1.mp4", b"OLD")

        def broken(self_, name, content):
            raise OSError(28, "No space left on device")

        with patch.object(FileSystemStorage, "_save", broken), self.assertRaises(OSError):
            storage.save_file("merge/7/x-1.mp4", self._source_file())
        self.assertTrue(default_storage.exists("merge/7/x-1.mp4"))

    def _source_file(self) -> str:
        handle, path = tempfile.mkstemp(suffix=".mp4", dir=self._media)
        with os.fdopen(handle, "wb") as fh:
            fh.write(b"MP4")
        return path


class OrphanFileTests(MediaTestCase):
    """Строку склейки удаляют и мимо API — файлы уходят вместе с ней."""

    def setUp(self):
        super().setUp()
        self.owner = self.user()
        self.ready = _ready(self, self.owner)
        self.files = (self.ready.result_video, self.ready.poster)

    def test_delete_in_django_admin_removes_files(self):
        with self.captureOnCommitCallbacks(execute=True):
            MergeProject.objects.filter(pk=self.ready.pk).delete()
        self.assertFalse(any(default_storage.exists(n) for n in self.files))

    def test_account_deletion_removes_files(self):
        with self.captureOnCommitCallbacks(execute=True):
            self.owner.delete()
        self.assertFalse(any(default_storage.exists(n) for n in self.files))

    def test_rolled_back_delete_keeps_files(self):
        with self.captureOnCommitCallbacks(execute=True) as callbacks:
            with suppress(RuntimeError), transaction.atomic():
                MergeProject.objects.filter(pk=self.ready.pk).delete()
                raise RuntimeError("откат")
        self.assertEqual(callbacks, [])
        self.assertTrue(all(default_storage.exists(n) for n in self.files))


class LanguageAndSourceTests(MediaTestCase):
    def setUp(self):
        super().setUp()
        self.owner = self.user()

    def test_fallback_titles_follow_the_language(self):
        chat = self.chat(self.owner)
        GenerationLog.objects.filter(pk=chat.pk).update(prompt="")
        titles = {lang: sources.list_page(self.owner, "chat", lang=lang)["results"][0]["title"]
                  for lang in ("ru", "en", "kg")}
        self.assertEqual(titles, {"ru": "Видео из чата", "en": "Chat video", "kg": "Чаттагы видео"})
        movie = self.movie(self.owner)
        CartoonProject.objects.filter(pk=movie.pk).update(title="")
        card = sources.list_page(self.owner, "cartoon_movie", lang="en")["results"][0]
        self.assertEqual(card["title"], "Cartoon")

    def test_default_merge_title_follows_the_language(self):
        api = client_for(self.owner)
        today = f"{timezone.localtime():%d.%m}"
        self.assertEqual(api.post(f"{BASE}?lang=en", {}, format="json").json()["title"], f"Merge {today}")
        self.assertEqual(api.post(BASE, {}, format="json", HTTP_ACCEPT_LANGUAGE="ky").json()["title"],
                         f"Бириктирүү {today}")
        self.assertEqual(api.post(BASE, {}, format="json").json()["title"], f"Склейка {today}")

    def test_movie_whose_reassembly_failed_keeps_its_previous_video(self):
        # Мультстудия показывает прежний ролик со «Скачать» и «Открыть в склейке» — склейка его принимает.
        movie = self.movie(self.owner, status=CartoonProject.STATUS_FAILED)
        response = client_for(self.owner).post(
            BASE, {"items": [{"type": "cartoon_movie", "id": movie.pk}]}, format="json")
        self.assertEqual(response.status_code, 201)
        self.assertTrue(response.json()["items"][0]["available"])
        cards = sources.list_page(self.owner, "cartoon")["results"]
        self.assertIn(("cartoon_movie", str(movie.pk)), {(c["type"], c["id"]) for c in cards})
        # Пока идёт пересборка, файл вот-вот сменится — такой не берём.
        CartoonProject.objects.filter(pk=movie.pk).update(status=CartoonProject.STATUS_ASSEMBLING)
        self.assertEqual(sources.resolve(self.owner, [("cartoon_movie", str(movie.pk))]), {})


class NiceTests(SimpleTestCase):
    def _commands(self, *, posix=True, nice="/usr/bin/nice"):
        with patch("merge.render.os.name", "posix" if posix else "nt"), \
                patch("merge.render.shutil.which", return_value=nice), \
                patch("merge.render.subprocess.run") as run:
            render._run(["ffmpeg", "-i", "a.mp4", "b.mp4"], 10)
            render._run(["ffprobe", "a.mp4"], 10)
        return [call.args[0] for call in run.call_args_list]

    def test_ffmpeg_runs_with_lower_priority_on_linux(self):
        ffmpeg, ffprobe = self._commands()
        self.assertEqual(ffmpeg, ["/usr/bin/nice", "-n", "10", "ffmpeg", "-i", "a.mp4", "b.mp4"])
        self.assertEqual(ffprobe, ["ffprobe", "a.mp4"])

    def test_without_nice_the_command_is_unchanged(self):
        self.assertEqual(self._commands(nice=None)[0][0], "ffmpeg")
        self.assertEqual(self._commands(posix=False)[0][0], "ffmpeg")
