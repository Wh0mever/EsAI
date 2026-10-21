"""API склейки: права, пределы, тексты отказов, запуск с резервом, скачивание."""
from __future__ import annotations

from datetime import datetime, timedelta
from unittest.mock import patch

from django.core.cache import cache
from django.core.files.storage import default_storage
from django.utils import timezone

from adminapi.runtime import set_runtime
from merge import services
from merge.models import MergeProject
from plans.models import TokenTransaction

from .helpers import MediaTestCase, client_for, store

BASE = "/api/merge/"


class _Api(MediaTestCase):
    def setUp(self):
        super().setUp()
        self.owner = self.user(balance=500)
        self.stranger = self.user(balance=500)
        self.api = client_for(self.owner)
        patcher = patch("merge.services.storage_ready", return_value=(True, ""))
        self.storage = patcher.start()
        self.addCleanup(patcher.stop)

    def two(self, user=None):
        user = user or self.owner
        return [self.take(user), self.scene(user)]


class AccessTests(_Api):
    def test_guest_gets_401_in_studio_shape(self):
        guest = client_for()
        for method, url in (("get", BASE), ("post", BASE), ("get", BASE + "sources/?type=chat")):
            response = getattr(guest, method)(url, {}, format="json") if method == "post" \
                else guest.get(url)
            self.assertEqual(response.status_code, 401, url)
            self.assertEqual(response.json()["error_code"], "unauthorized")
            self.assertEqual(response.json()["error"], "Войдите, чтобы продолжить.")

    def test_config_is_open_to_guests(self):
        body = client_for().get(BASE + "config/").json()
        self.assertEqual(body["price_credits"], 20)
        self.assertEqual(body["limits"], {"min_fragments": 2, "max_fragments": 30,
                                          "max_total_s": 300, "retention_days": 30})
        self.assertEqual(body["aspects"], ["16:9", "9:16", "1:1"])
        self.assertEqual(body["fits"], ["pad", "crop"])
        self.assertFalse(body["authenticated"])
        self.assertIsNone(body["balance"])

    def test_config_for_user_shows_balance(self):
        body = self.api.get(BASE + "config/").json()
        self.assertTrue(body["authenticated"])
        self.assertEqual(body["balance"], {"balance": 500, "reserved": 0, "available": 500,
                                           "after": 480})

    def test_someone_elses_project_is_404(self):
        project = self.project(self.owner)
        other = client_for(self.stranger)
        for method in ("get", "patch", "delete"):
            response = getattr(other, method)(f"{BASE}{project.uid}/", {}, format="json")
            self.assertEqual(response.status_code, 404, method)
            self.assertEqual(response.json(), {"error": "Склейка не найдена.",
                                               "error_code": "project_not_found"})
        response = other.post(f"{BASE}{project.uid}/render/", {}, format="json")
        self.assertEqual(response.status_code, 404)

    def test_sources_endpoint(self):
        take = self.take(self.owner)
        self.take(self.stranger)
        body = self.api.get(BASE + "sources/?type=vstudio&page=1").json()
        self.assertEqual([c["id"] for c in body["results"]], [take.uid])
        bad = self.api.get(BASE + "sources/?type=files")
        self.assertEqual(bad.status_code, 400)
        self.assertEqual(bad.json()["error"], "Неизвестный вид видео.")


class EditTests(_Api):
    def test_create_with_items_and_shape(self):
        take, scene = self.two()
        response = self.api.post(BASE, {"aspect": "9:16", "fit": "crop",
                                        "items": [self.ref(take), self.ref(scene)]}, format="json")
        self.assertEqual(response.status_code, 201)
        body = response.json()
        self.assertEqual(len(body["id"]), 32)
        self.assertTrue(body["title"].startswith("Склейка "))
        self.assertEqual((body["status"], body["aspect"], body["fit"]), ("draft", "9:16", "crop"))
        self.assertEqual(body["fragments"], 2)
        self.assertEqual(body["total_duration_s"], 10.0)
        self.assertTrue(body["can_render"])
        self.assertIsNone(body["render_block"])
        self.assertEqual(body["price_credits"], 20)
        item = body["items"][0]
        self.assertEqual(item["type"], "vstudio")
        self.assertEqual(item["id"], take.uid)
        self.assertTrue(item["available"])
        self.assertEqual(body["items"][1]["id"], str(scene.pk))
        for key in ("progress", "result_url", "download_url", "expires_at"):
            self.assertIsNone(body[key])
        stored = MergeProject.objects.get(uid=body["id"]).items
        self.assertEqual(stored[0]["file"], take.result_asset.file)

    def test_list_newest_first(self):
        first = self.project(self.owner)
        second = self.project(self.owner)
        self.project(self.stranger)
        MergeProject.objects.filter(pk=first.pk).update(updated_at=timezone.now() - timedelta(days=1))
        body = self.api.get(BASE).json()
        self.assertEqual([p["id"] for p in body["results"]], [second.uid, first.uid])
        self.assertIsNone(body["active_id"])
        self.assertEqual(body["price_credits"], 20)

    def test_patch_reorders_full_list(self):
        take, scene = self.two()
        project = self.project(self.owner, [take, scene])
        response = self.api.patch(f"{BASE}{project.uid}/",
                                  {"items": [self.ref(scene), self.ref(take), self.ref(scene)],
                                   "title": "  Отпуск  "}, format="json")
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual([i["type"] for i in body["items"]],
                         ["cartoon_scene", "vstudio", "cartoon_scene"])
        self.assertEqual(body["title"], "Отпуск")

    def test_one_fragment_draft_is_saved_but_cannot_render(self):
        project = self.project(self.owner)
        body = self.api.patch(f"{BASE}{project.uid}/", {"items": [self.ref(self.take(self.owner))]},
                              format="json").json()
        self.assertFalse(body["can_render"])
        self.assertEqual(body["render_block"], {"error_code": "too_few_fragments",
                                                "error": "Добавьте хотя бы 2 фрагмента, чтобы склеить."})

    def test_someone_elses_source_is_refused(self):
        mine = self.take(self.owner)
        theirs = self.scene(self.stranger)
        project = self.project(self.owner)
        response = self.api.patch(f"{BASE}{project.uid}/",
                                  {"items": [self.ref(mine), self.ref(theirs)]}, format="json")
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json(), {
            "error": "Фрагмент №2 недоступен: видео не найдено, удалено или ещё не готово. "
                     "Уберите его из склейки.",
            "error_code": "source_unavailable", "index": 1, "type": "cartoon_scene",
            "id": str(theirs.pk)})
        self.assertEqual(MergeProject.objects.get(pk=project.pk).items, [])

    def test_limits(self):
        project = self.project(self.owner)
        take = self.take(self.owner)
        too_many = self.api.patch(f"{BASE}{project.uid}/", {"items": [self.ref(take)] * 31},
                                  format="json")
        self.assertEqual(too_many.status_code, 400)
        self.assertEqual(too_many.json()["error"], "Можно склеить не больше 30 фрагментов.")
        self.assertEqual(too_many.json()["max"], 30)

        long_movie = self.movie(self.owner)
        self.durations[long_movie.result_video] = 296.0
        too_long = self.api.patch(f"{BASE}{project.uid}/",
                                  {"items": [self.ref(long_movie), self.ref(take)]}, format="json")
        self.assertEqual(too_long.status_code, 400)
        self.assertEqual(too_long.json()["error_code"], "too_long")
        self.assertEqual(too_long.json()["error"],
                         "Склейка выходит длиннее 5 минут (5:01). Уберите часть фрагментов.")
        self.assertEqual(too_long.json()["total_s"], 301.0)

        self.durations[long_movie.result_video] = 295.0
        cache.clear()
        ok = self.api.patch(f"{BASE}{project.uid}/",
                            {"items": [self.ref(long_movie), self.ref(take)]}, format="json")
        self.assertEqual(ok.status_code, 200)
        self.assertEqual(ok.json()["total_duration_s"], 300.0)

    def test_bad_fields(self):
        project = self.project(self.owner)
        url = f"{BASE}{project.uid}/"
        cases = (
            ({"aspect": "4:3"}, "Формат склейки: 16:9, 9:16 или 1:1."),
            ({"fit": "stretch"}, "Заполнение кадра: pad (поля) или crop (обрезать)."),
            ({"items": "1,2"}, "Список фрагментов не распознан. Обновите страницу и попробуйте снова."),
            ({"items": [{"type": "youtube", "id": "1"}]},
             "Список фрагментов не распознан. Обновите страницу и попробуйте снова."),
            # Свой файл — вид известный, но id не uid загрузки: такого видео нет.
            ({"items": [{"type": "upload", "id": "1"}]},
             "Фрагмент №1 недоступен: видео не найдено, удалено или ещё не готово. "
             "Уберите его из склейки."),
            ({"title": "x" * 141}, "Название — строка не длиннее 140 символов."),
        )
        for data, text in cases:
            response = self.api.patch(url, data, format="json")
            self.assertEqual(response.status_code, 400, data)
            self.assertEqual(response.json()["error"], text)

    def test_unreadable_source(self):
        movie = self.movie(self.owner)
        self.durations[movie.result_video] = None
        project = self.project(self.owner)
        response = self.api.patch(f"{BASE}{project.uid}/",
                                  {"items": [self.ref(self.take(self.owner)), self.ref(movie)]},
                                  format="json")
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["error_code"], "source_unreadable")

    def test_ready_project_keeps_its_fragments(self):
        take, scene = self.two()
        project = self.project(self.owner, [take, scene], status="ready", result_video="merge/x.mp4")
        url = f"{BASE}{project.uid}/"
        refused = self.api.patch(url, {"items": [self.ref(scene), self.ref(take)]}, format="json")
        self.assertEqual(refused.status_code, 409)
        self.assertEqual(refused.json()["error_code"], "already_ready")
        renamed = self.api.patch(url, {"title": "Новое имя"}, format="json")
        self.assertEqual(renamed.status_code, 200)
        self.assertEqual(renamed.json()["title"], "Новое имя")

    def test_active_project_cannot_change_or_be_deleted(self):
        project = self.project(self.owner, self.two(), status="rendering", credits_reserved=20)
        url = f"{BASE}{project.uid}/"
        self.assertEqual(self.api.patch(url, {"fit": "crop"}, format="json").status_code, 409)
        response = self.api.delete(url)
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["error"],
                         "Склейка уже идёт — изменить или удалить её можно после окончания.")

    def test_editing_failed_project_returns_it_to_draft(self):
        take, scene = self.two()
        project = self.project(self.owner, [take, scene], status="failed", error="старая ошибка",
                               error_code="fragment_failed", error_fragment=2)
        failed = self.api.get(f"{BASE}{project.uid}/").json()
        self.assertEqual((failed["error_code"], failed["error_fragment"]), ("fragment_failed", 2))
        body = self.api.patch(f"{BASE}{project.uid}/", {"fit": "crop"}, format="json").json()
        self.assertEqual((body["status"], body["error"], body["error_code"], body["error_fragment"]),
                         ("draft", "", None, None))

    def test_deleted_source_shows_unavailable_in_draft(self):
        take, scene = self.two()
        project = self.project(self.owner, [take, scene])
        default_storage.delete(scene.video)
        body = self.api.get(f"{BASE}{project.uid}/").json()
        self.assertEqual([i["available"] for i in body["items"]], [True, False])
        self.assertIsNone(body["items"][1]["url"])
        self.assertFalse(body["can_render"])
        self.assertEqual(body["render_block"]["error_code"], "source_unavailable")
        self.assertEqual(body["render_block"]["index"], 1)

    def test_delete_removes_files(self):
        video = store("merge/1/a.mp4")
        poster = store("merge/1/a.jpg")
        project = self.project(self.owner, status="ready", result_video=video, poster=poster)
        self.assertEqual(self.api.delete(f"{BASE}{project.uid}/").status_code, 204)
        self.assertFalse(MergeProject.objects.filter(pk=project.pk).exists())
        self.assertFalse(default_storage.exists(video))
        self.assertFalse(default_storage.exists(poster))

    def test_project_cap(self):
        with patch("merge.services.MAX_PROJECTS", 2):
            self.project(self.owner)
            self.project(self.owner)
            response = self.api.post(BASE, {}, format="json")
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["error_code"], "too_many_projects")


class RenderStartTests(_Api):
    def render(self, project, data=None, client=None):
        with self.captureOnCommitCallbacks(execute=False):
            return (client or self.api).post(f"{BASE}{project.uid}/render/", data or {},
                                              format="json")

    def test_reserves_and_queues(self):
        project = self.project(self.owner, self.two())
        with patch("merge.tasks.render_merge.delay") as delay, \
                self.captureOnCommitCallbacks(execute=True):
            response = self.api.post(f"{BASE}{project.uid}/render/", {"price": 20}, format="json")
        self.assertEqual(response.status_code, 202)
        body = response.json()
        self.assertEqual(body["status"], "queued")
        self.assertEqual(body["credits_reserved"], 20)
        self.assertEqual(body["progress"], {"stage": "queued", "done": 0, "total": 2})
        self.assertEqual(body["balance"]["reserved"], 20)
        delay.assert_called_once_with(project.pk)
        project.refresh_from_db()
        self.assertEqual((project.status, project.credits_reserved), ("queued", 20))
        self.assertIsNotNone(project.queued_at)
        # Резерв не списание: баланс тот же, леджер пуст.
        self.assertEqual(self.balance(self.owner), 500)
        self.assertFalse(TokenTransaction.objects.filter(user=self.owner).exists())
        self.assertEqual(services.reserved_credits(self.owner), 20)

    def test_repeat_click_is_idempotent(self):
        project = self.project(self.owner, self.two())
        with patch("merge.tasks.render_merge.delay") as delay:
            with self.captureOnCommitCallbacks(execute=True):
                first = self.api.post(f"{BASE}{project.uid}/render/", {}, format="json")
            with self.captureOnCommitCallbacks(execute=True):
                second = self.api.post(f"{BASE}{project.uid}/render/", {}, format="json")
        self.assertEqual((first.status_code, second.status_code), (202, 200))
        self.assertEqual(delay.call_count, 1)
        self.assertEqual(services.reserved_credits(self.owner), 20)

    def test_render_with_edits_saves_and_runs(self):
        take, scene = self.two()
        project = self.project(self.owner)
        response = self.render(project, {"items": [self.ref(scene), self.ref(take)], "aspect": "1:1"})
        self.assertEqual(response.status_code, 202)
        project.refresh_from_db()
        self.assertEqual(project.aspect, "1:1")
        self.assertEqual([i["type"] for i in project.items], ["cartoon_scene", "vstudio"])

    def test_too_few(self):
        project = self.project(self.owner, [self.take(self.owner)])
        response = self.render(project)
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json(), {"error": "Добавьте хотя бы 2 фрагмента, чтобы склеить.",
                                           "error_code": "too_few_fragments", "min": 2})

    def test_source_lost_after_saving_is_caught_at_start(self):
        take, scene = self.two()
        project = self.project(self.owner, [take, scene])
        default_storage.delete(take.result_asset.file)
        response = self.render(project)
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["error_code"], "source_unavailable")
        self.assertEqual(MergeProject.objects.get(pk=project.pk).status, "draft")

    def test_insufficient_balance_is_402_in_chat_shape(self):
        poor = self.user(balance=5)
        project = self.project(poor, self.two(poor))
        response = self.render(project, client=client_for(poor))
        self.assertEqual(response.status_code, 402)
        self.assertEqual(response.json(), {"error": "Недостаточно кредитов для склейки.",
                                           "error_code": "insufficient_balance",
                                           "balance_tokens": 5, "required_estimate": 20})
        project.refresh_from_db()
        self.assertEqual((project.status, project.credits_reserved), ("draft", 0))

    def test_402_counts_other_reserves(self):
        user = self.user(balance=30)
        project = self.project(user, self.two(user))
        with patch("vstudio.reserve.total_reserved", return_value=15):
            response = self.render(project, client=client_for(user))
        self.assertEqual(response.status_code, 402)
        body = response.json()
        self.assertEqual(body["balance_tokens"], 15)
        self.assertEqual(body["reserved_credits"], 15)
        self.assertTrue(body["error"].startswith("Недостаточно кредитов: часть баланса ждёт оплаты"))

    def test_402_rolls_back_edits_from_the_same_request(self):
        poor = self.user(balance=0)
        take, scene = self.two(poor)
        project = self.project(poor, [take, scene])
        response = self.render(project, {"aspect": "9:16"}, client=client_for(poor))
        self.assertEqual(response.status_code, 402)
        self.assertEqual(MergeProject.objects.get(pk=project.pk).aspect, "16:9")

    def test_free_merge_needs_no_balance(self):
        set_runtime("merge_price_credits", 0)
        broke = self.user(balance=0)
        project = self.project(broke, self.two(broke))
        response = self.render(project, client=client_for(broke))
        self.assertEqual(response.status_code, 202)
        self.assertEqual(response.json()["credits_reserved"], 0)

    def test_one_active_render_per_user(self):
        busy = self.project(self.owner, self.two(), status="rendering", credits_reserved=20)
        project = self.project(self.owner, self.two())
        response = self.render(project)
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json(), {
            "error": "Уже идёт другая склейка. Дождитесь её окончания и запустите эту.",
            "error_code": "busy", "active_id": busy.uid})

    def test_stale_render_does_not_block_forever(self):
        stale = self.project(self.owner, self.two(), status="rendering", credits_reserved=20,
                             render_started_at=timezone.now() - timedelta(hours=1))
        project = self.project(self.owner, self.two())
        self.assertEqual(self.render(project).status_code, 202)
        stale.refresh_from_db()
        self.assertEqual((stale.status, stale.credits_reserved), ("failed", 0))
        self.assertEqual(stale.error, "Склейка оборвалась — кредиты не списаны, попробуйте ещё раз.")

    def test_price_changed(self):
        project = self.project(self.owner, self.two())
        set_runtime("merge_price_credits", 25)
        response = self.render(project, {"price": 20})
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json(), {
            "error": "Цена изменилась: теперь 25 кр. Проверьте и нажмите «Склеить» ещё раз.",
            "error_code": "price_changed", "credits": 25})

    def test_storage_refusal(self):
        self.storage.return_value = (False, "мало места")
        project = self.project(self.owner, self.two())
        response = self.render(project)
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()["error_code"], "storage_unavailable")
        self.assertEqual(MergeProject.objects.get(pk=project.pk).credits_reserved, 0)

    def test_ready_cannot_be_rendered_again(self):
        project = self.project(self.owner, self.two(), status="ready", result_video="merge/x.mp4")
        response = self.render(project)
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["error_code"], "already_ready")

    def test_broker_down_releases_reserve_at_once(self):
        project = self.project(self.owner, self.two())
        with patch("merge.tasks.render_merge.delay", side_effect=ConnectionError("no broker")), \
                self.captureOnCommitCallbacks(execute=True):
            self.api.post(f"{BASE}{project.uid}/render/", {}, format="json")
        project.refresh_from_db()
        self.assertEqual((project.status, project.credits_reserved), ("failed", 0))
        self.assertEqual(project.error, "Склейка не запустилась — кредиты не списаны, попробуйте ещё раз.")
        self.assertEqual(project.error_code, "queue_down")


class DownloadTests(_Api):
    def setUp(self):
        super().setUp()
        self.video = store("merge/1/result.mp4", b"MP4DATA")
        self.project_ready = self.project(
            self.owner, status="ready", result_video=self.video,
            finished_at=timezone.make_aware(datetime(2026, 10, 16, 12, 0)),
            expires_at=timezone.now() + timedelta(days=30))

    def _get(self, client, url):
        response = client.get(url)
        if hasattr(response, "streaming_content"):
            body = b"".join(response.streaming_content)
            response.close()
            return response, body
        return response, None

    def test_owner_downloads_attachment(self):
        response, body = self._get(self.api, f"{BASE}{self.project_ready.uid}/download/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(body, b"MP4DATA")
        self.assertEqual(response["Content-Type"], "video/mp4")
        self.assertEqual(response["Content-Disposition"],
                         'attachment; filename="EsAI-merge-2026-10-16.mp4"')

    def test_signed_link_works_without_login(self):
        detail = self.api.get(f"{BASE}{self.project_ready.uid}/").json()
        self.assertTrue(detail["download_url"].startswith(f"/api/merge/{self.project_ready.uid}/download/?t="))
        self.assertEqual(detail["result_url"], "/media/" + self.video)
        response, body = self._get(client_for(), detail["download_url"])
        self.assertEqual(response.status_code, 200)
        self.assertEqual(body, b"MP4DATA")

    def test_guest_without_link_gets_401(self):
        response, _ = self._get(client_for(), f"{BASE}{self.project_ready.uid}/download/")
        self.assertEqual(response.status_code, 401)

    def test_stranger_gets_404(self):
        response, _ = self._get(client_for(self.stranger), f"{BASE}{self.project_ready.uid}/download/")
        self.assertEqual(response.status_code, 404)

    def test_link_of_another_project_does_not_open_this_one(self):
        other = self.project(self.owner, status="ready", result_video=store("merge/1/o.mp4"))
        token = services.download_token(other)
        response, _ = self._get(client_for(), f"{BASE}{self.project_ready.uid}/download/?t={token}")
        self.assertEqual(response.status_code, 404)

    def test_forged_or_expired_link(self):
        url = f"{BASE}{self.project_ready.uid}/download/?t="
        self.assertEqual(self._get(client_for(), url + "forged")[0].status_code, 404)
        token = services.download_token(self.project_ready)
        with patch("merge.services.DOWNLOAD_MAX_AGE", -1):
            self.assertEqual(self._get(client_for(), url + token)[0].status_code, 404)

    def test_not_ready(self):
        draft = self.project(self.owner)
        response, _ = self._get(self.api, f"{BASE}{draft.uid}/download/")
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["error"], "Ролик ещё не готов.")

    def test_file_gone(self):
        default_storage.delete(self.video)
        response, _ = self._get(self.api, f"{BASE}{self.project_ready.uid}/download/")
        self.assertEqual(response.status_code, 410)
        self.assertEqual(response.json()["error_code"], "file_missing")


class ManageSettingsTests(_Api):
    URL = BASE + "manage/settings/"

    def test_staff_only(self):
        self.assertEqual(self.api.get(self.URL).status_code, 403)
        self.assertEqual(client_for().get(self.URL).status_code, 401)

    def test_set_reset_and_validate(self):
        staff = client_for(self.user(is_staff=True))
        self.assertEqual(staff.get(self.URL).json(),
                         {"price_credits": 20, "default_price_credits": 20, "overridden": False})
        body = staff.patch(self.URL, {"price_credits": 35}, format="json").json()
        self.assertEqual(body, {"price_credits": 35, "default_price_credits": 20, "overridden": True})
        self.assertEqual(self.api.get(BASE + "config/").json()["price_credits"], 35)
        self.assertEqual(staff.patch(self.URL, {"price_credits": "0"}, format="json")
                         .json()["price_credits"], 0)
        for bad in (-1, 12.5, "abc", True, 100001):
            response = staff.patch(self.URL, {"price_credits": bad}, format="json")
            self.assertEqual(response.status_code, 400, bad)
        reset = staff.patch(self.URL, {"price_credits": None}, format="json").json()
        self.assertEqual(reset, {"price_credits": 20, "default_price_credits": 20, "overridden": False})
        self.assertEqual(staff.patch(self.URL, {}, format="json").status_code, 400)

    def test_change_is_audited(self):
        from audit.models import AdminActionLog

        staff_user = self.user(is_staff=True)
        client_for(staff_user).patch(self.URL, {"price_credits": 30}, format="json")
        row = AdminActionLog.objects.get(action="settings.edit")
        self.assertEqual(row.before, {"merge_price_credits": 20})
        self.assertEqual(row.after, {"merge_price_credits": 30})
