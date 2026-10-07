"""Витрина первого экрана: публичный список и управление им из панели.

Главное, что проверяем:
- наружу уходит только включённая строка с готовым, не удалённым результатом
  и только закрытый список полей — без uid, автора и фото, с которыми снято;
- порядок (sort, затем новые) и потолок в 48 работ;
- кэш на 5 минут сбрасывает любая правка — но после фиксации транзакции;
- гостевые запросы первого экрана не тратят общий anon-счётчик сайта;
- панель: только staff, каждая запись — со строкой в журнале действий;
- в витрину ставятся только работы сотрудников: в адресах файлов виден номер
  аккаунта автора;
- лёгкая копия ролика: собирается после фиксации, не ломает ни панель, ни
  сайт, уходит вместе со строкой и с результатом (ffmpeg в тестах подменён).
"""
import json
from datetime import timedelta
from unittest import mock

from django.core.cache import cache
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient
from rest_framework.throttling import ScopedRateThrottle, SimpleRateThrottle

from audit.models import AdminActionLog

from .. import showcase, tasks, views
from ..models import Asset, ShowcaseItem, Take
from . import factories as f

CACHES = {"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache",
                      "LOCATION": "vstudio-showcase"}}
PUBLIC = "/api/vstudio/showcase/"
PANEL = "/api/manage/vstudio/showcase/"
PUBLIC_KEYS = {"id", "title", "category", "kind", "model", "aspect_ratio", "duration_s", "width",
               "height", "video_url", "image_url", "poster_url", "full_url", "prompt", "params"}
TAKE_KEYS = (PUBLIC_KEYS - {"id", "title", "category", "full_url"}) | {
    "uid", "status", "own_photos", "public_ok", "user_email", "user_is_staff", "created_at",
    "finished_at"}
ITEM_KEYS = {"id", "title", "category", "sort", "is_active", "show_prompt", "state",
             "created_by_email", "created_at", "updated_at", "take"}


@override_settings(CACHES=CACHES, VSTUDIO_MODE="on")
class ShowcaseCase(TestCase):
    def setUp(self):
        cache.clear()
        self.staff = f.make_user("boss@example.com", is_staff=True)
        self.author = f.make_user("author@example.com")
        f.make_gpt_model(f.VIDEO_MODEL_REF, name="Seedance 2.0")
        f.make_gpt_model(f.IMAGE_MODEL_REF, name="Nano Banana")
        self.guest = APIClient()
        self.panel = self.client_for(self.staff)
        # Сборку лёгкой копии ставит каждая новая строка — в очередь тесты не ходят.
        self.clip_task = self.enterContext(
            mock.patch("vstudio.tasks.build_showcase_clip.apply_async"))

    def client_for(self, user):
        client = APIClient()
        client.force_authenticate(user)
        return client

    def work(self, user=None, *, kind="video", status="done", inputs=(), asset=None, **kw) -> Take:
        """Дубль с результатом — то, что ставят в витрину."""
        user = user or self.staff
        video = kind == "video"
        if asset is None:
            asset = f.make_asset(
                user, kind=kind, width=1280, height=720, duration_s=5.04 if video else None,
                source=Asset.SOURCE_GENERATED_VIDEO if video else Asset.SOURCE_GENERATED_IMAGE)
        return f.make_take(f.make_shot(user, kind=kind, inputs=inputs), status=status,
                           result_asset=asset, **kw)

    def item(self, take=None, **kw) -> ShowcaseItem:
        return ShowcaseItem.objects.create(take=take or self.work(), **kw)

    def public(self, client=None) -> list:
        res = (client or self.guest).get(PUBLIC)
        self.assertEqual(res.status_code, 200, res.content)
        self.assertEqual(set(res.json()), {"items"})
        return res.json()["items"]

    def ids(self, client=None) -> list:
        return [row["id"] for row in self.public(client)]

    def logs(self):
        return AdminActionLog.objects.filter(target_type="vstudio.showcaseitem").order_by("pk")


# ---------------------------------------------------------------- что уходит наружу

class PublicPayloadTests(ShowcaseCase):
    def test_video_card(self):
        take = self.work()
        item = self.item(take, title="Ночной город", category="film")
        asset = take.result_asset
        self.assertEqual(self.public(), [{
            "id": item.pk, "title": "Ночной город", "category": "film", "kind": "video",
            "model": {"id": f.VIDEO_MODEL_REF, "name": "Seedance 2.0"},
            "aspect_ratio": "16:9", "duration_s": 5, "width": 1280, "height": 720,
            "video_url": asset.url, "image_url": None, "poster_url": asset.thumb_url,
            "full_url": asset.url, "prompt": None, "params": None,
        }])
        self.assertTrue(asset.url.startswith("/media/vstudio/"))

    def test_image_card(self):
        take = self.work(kind="image")   # картинка снята с aspect_ratio=auto
        self.item(take)
        card = self.public()[0]
        asset = take.result_asset
        self.assertEqual((card["kind"], card["video_url"], card["image_url"], card["full_url"]),
                         ("image", None, asset.url, None))
        self.assertEqual(card["poster_url"], asset.thumb_url)
        self.assertEqual(card["model"]["name"], "Nano Banana")
        self.assertIsNone(card["duration_s"])
        # «auto» карточке не поможет — соотношение берём по размеру файла.
        self.assertEqual(card["aspect_ratio"], "16:9")

    def test_image_without_thumb_is_its_own_poster(self):
        take = self.work(kind="image")
        Asset.objects.filter(pk=take.result_asset_id).update(thumb="")
        self.item(take)
        card = self.public()[0]
        self.assertEqual(card["poster_url"], card["image_url"])

    def test_prompt_and_params_only_with_permission(self):
        ref = f.make_asset(self.staff)
        take = self.work(inputs=[ref], effective={
            "duration": 5, "resolution": "720p", "aspect_ratio": "16:9", "generate_audio": True,
            "seed": 7, "negative_prompt": "no text"})
        item = self.item(take)
        card = self.public()[0]
        self.assertIsNone(card["prompt"])
        self.assertIsNone(card["params"])

        cache.clear()
        ShowcaseItem.objects.filter(pk=item.pk).update(show_prompt=True)
        card = self.public()[0]
        # Фото в запросе названо меткой, а не идентификатором.
        self.assertEqual(card["prompt"], "Девушка идёт по крыше @Image 1")
        self.assertEqual(card["params"], {"duration": 5, "resolution": "720p", "aspect_ratio": "16:9"})

    def test_only_active_items_with_a_live_result(self):
        good = self.item()
        self.item(is_active=False)
        for status in ("queued", "running", "failed", "canceled", "lost"):
            self.item(self.work(status=status))
        self.item(self.work(asset=f.make_asset(self.staff, kind="video",
                                               deleted_at=timezone.now())))
        self.item(self.work(asset=f.make_asset(self.staff, kind="image",
                                               status=Asset.STATUS_PENDING), kind="image"))
        self.item(self.work(asset=f.make_asset(self.staff, kind="image",
                                               status=Asset.STATUS_FAILED), kind="image"))
        self.item(self.work(asset=f.make_asset(self.staff, kind="video", file="")))
        lost_file = self.work()
        Take.objects.filter(pk=lost_file.pk).update(result_asset=None)
        self.item(lost_file)
        self.work()   # готовый дубль, которого в витрине нет
        self.assertEqual(self.ids(), [good.pk])

    def test_nothing_personal_leaves(self):
        ref = f.make_asset(self.staff)
        frame = f.make_asset(self.staff)
        take = self.work(inputs=[ref, (frame, "first_frame")])
        self.item(take, show_prompt=True, created_by=self.staff)
        self.work(self.author)   # чужой дубль вне витрины
        cards = self.public()
        self.assertEqual(len(cards), 1)
        card = cards[0]
        self.assertEqual(set(card), PUBLIC_KEYS)
        self.assertEqual(set(card["model"]), {"id", "name"})
        dump = json.dumps(card, ensure_ascii=False)
        asset = take.result_asset
        for secret in (ref.uid, frame.uid, ref.url, ref.thumb_url, take.uid, take.shot.uid,
                       take.project.uid, self.staff.email, self.author.email, "example.com"):
            self.assertNotIn(secret, dump)
        # uid результата есть только внутри адресов его же файлов.
        for name in ("video_url", "full_url", "poster_url"):
            dump = dump.replace(card[name], "")
        self.assertNotIn(asset.uid, dump)

    def test_file_addresses_carry_only_a_staff_account_number(self):
        # Исходник и обложка лежат в папке автора, номер аккаунта виден в адресе —
        # поэтому работа пользователя в витрину не попадает, даже снятая по тексту.
        foreign = self.work(self.author)
        self.assertFalse(showcase.can_publish(foreign))
        res = self.panel.post(PANEL, {"take": foreign.uid}, format="json")
        self.assertEqual(res.status_code, 400, res.content)
        self.item(self.work())
        dump = json.dumps(self.public())
        self.assertIn(f"/vstudio/{self.staff.pk}/", dump)
        self.assertNotIn(f"/vstudio/{self.author.pk}/", dump)


# ---------------------------------------------------------------- порядок и потолок

class OrderAndLimitTests(ShowcaseCase):
    def test_sort_then_newest_first(self):
        last = self.item(sort=5)
        older = self.item(sort=0)
        newer = self.item(sort=0)
        first = self.item(sort=-1)
        ShowcaseItem.objects.filter(pk=older.pk).update(created_at=timezone.now() - timedelta(days=1))
        self.assertEqual(self.ids(), [first.pk, newer.pk, older.pk, last.pk])

    def test_at_most_48_and_hidden_rows_take_no_slot(self):
        take = self.work()
        hidden = [self.item(self.work(asset=take.result_asset), sort=n, is_active=False)
                  for n in range(2)]
        shown = [self.item(self.work(asset=take.result_asset), sort=10 + n)
                 for n in range(showcase.MAX_PUBLIC + 1)]
        self.assertEqual(showcase.MAX_PUBLIC, 48)
        self.assertEqual(self.ids(), [item.pk for item in shown[:48]])
        self.assertNotIn(hidden[0].pk, self.ids())


# ---------------------------------------------------------------- кэш

class CacheTests(ShowcaseCase):
    def test_five_minutes_under_the_agreed_key(self):
        self.item(title="Первая")
        self.assertEqual((showcase.CACHE_KEY, showcase.CACHE_S), ("vstudio:showcase:v1", 300))
        with mock.patch.object(showcase.cache, "set", wraps=showcase.cache.set) as store:
            first = showcase.public_items()
        store.assert_called_once_with(showcase.CACHE_KEY, first, 300)
        with self.assertNumQueries(0):
            self.assertEqual(showcase.public_items(), first)
        self.assertEqual(cache.get(showcase.CACHE_KEY), first)

    def test_panel_change_is_visible_right_after_commit(self):
        item = self.item(title="Было")
        self.assertEqual(self.public()[0]["title"], "Было")
        with self.captureOnCommitCallbacks(execute=False) as callbacks:
            res = self.panel.patch(f"{PANEL}{item.pk}/", {"title": "Стало"}, format="json")
        self.assertEqual(res.status_code, 200, res.content)
        # Транзакция ещё не зафиксирована — кэш прежний: сбросить раньше значило
        # бы дать соседу собрать его из старой базы.
        self.assertEqual(self.public()[0]["title"], "Было")
        self.assertTrue(callbacks)
        for callback in callbacks:
            callback()
        self.assertEqual(self.public()[0]["title"], "Стало")

    def test_every_panel_write_drops_the_cache(self):
        take = self.work()
        self.assertEqual(self.public(), [])
        with self.captureOnCommitCallbacks(execute=True):
            pk = self.panel.post(PANEL, {"take": take.uid}, format="json").json()["id"]
        self.assertEqual(self.ids(), [pk])
        with self.captureOnCommitCallbacks(execute=True):
            self.panel.patch(f"{PANEL}{pk}/", {"is_active": False}, format="json")
        self.assertEqual(self.ids(), [])
        with self.captureOnCommitCallbacks(execute=True):
            self.panel.patch(f"{PANEL}{pk}/", {"is_active": True}, format="json")
        self.assertEqual(self.ids(), [pk])
        with self.captureOnCommitCallbacks(execute=True):
            self.panel.delete(f"{PANEL}{pk}/")
        self.assertEqual(self.ids(), [])

    def test_refused_change_keeps_the_cache(self):
        item = self.item()
        self.public()
        with self.captureOnCommitCallbacks() as callbacks:
            res = self.panel.patch(f"{PANEL}{item.pk}/", {"category": "nonsense"}, format="json")
        self.assertEqual(res.status_code, 400)
        self.assertEqual(callbacks, [])

    def test_changes_outside_the_panel_drop_the_cache_too(self):
        item = self.item(title="Было")
        other = self.item()
        self.assertEqual(len(self.public()), 2)
        with self.captureOnCommitCallbacks(execute=True):
            item.title = "Из Django-админки"
            item.save()
        self.assertEqual({row["title"] for row in self.public()}, {"Из Django-админки", ""})
        # Дубль удалили (вместе с аккаунтом) — строка уходит каскадом.
        with self.captureOnCommitCallbacks(execute=True):
            other.take.delete()
        self.assertEqual(self.ids(), [item.pk])

    def test_result_deleted_by_its_owner_leaves_at_once(self):
        take = self.work()
        self.item(take)
        spare = f.make_asset(self.staff)
        self.assertEqual(len(self.public()), 1)
        owner = self.client_for(self.staff)
        # Материал не из витрины кэш не трогает.
        with self.captureOnCommitCallbacks() as callbacks:
            self.assertEqual(owner.delete(f"/api/vstudio/assets/{spare.uid}/").status_code, 204)
        self.assertEqual(callbacks, [])
        with self.captureOnCommitCallbacks(execute=True):
            res = owner.delete(f"/api/vstudio/assets/{take.result_asset.uid}/")
        self.assertEqual(res.status_code, 204)
        self.assertEqual(self.public(), [])


# ---------------------------------------------------------------- лёгкая копия

class ClipTests(ShowcaseCase):
    def setUp(self):
        super().setUp()
        self.enterContext(f.media_root())
        self.make_clip = self.enterContext(
            mock.patch.object(showcase, "make_clip", return_value=b"light-copy"))

    def stored(self, take: Take) -> Take:
        """Положить исходник дубля на диск — сборке есть что читать."""
        default_storage.save(take.result_asset.file, ContentFile(b"original-bytes"))
        return take

    def built(self, take=None) -> ShowcaseItem:
        item = self.item(self.stored(take or self.work()))
        with self.captureOnCommitCallbacks(execute=True):
            self.assertTrue(showcase.build_clip(item.pk))
        item.refresh_from_db()
        return item

    def clip_files(self) -> list:
        return default_storage.listdir("vstudio/showcase")[1]

    def test_new_video_is_queued_after_commit(self):
        take = self.work()
        with self.captureOnCommitCallbacks() as callbacks:
            res = self.panel.post(PANEL, {"take": take.uid}, format="json")
        self.assertEqual(res.status_code, 201, res.content)
        # До фиксации воркер строку ещё не найдёт — задачи нет.
        self.clip_task.assert_not_called()
        for callback in callbacks:
            callback()
        self.clip_task.assert_called_once_with(args=[res.json()["id"]])

    def test_image_gets_no_clip(self):
        with self.captureOnCommitCallbacks(execute=True):
            res = self.panel.post(PANEL, {"take": self.work(kind="image").uid}, format="json")
        self.assertEqual(res.status_code, 201, res.content)
        self.clip_task.assert_not_called()
        self.assertFalse(showcase.build_clip(res.json()["id"]))
        self.make_clip.assert_not_called()

    def test_site_plays_the_clip_and_keeps_the_original_beside_it(self):
        take = self.stored(self.work())
        asset = take.result_asset
        item = self.item(take)
        # Копии ещё нет — работа видна сразу, с исходником.
        card = self.public()[0]
        self.assertEqual((card["video_url"], card["full_url"]), (asset.url, asset.url))

        stamp = item.updated_at
        with self.captureOnCommitCallbacks(execute=True):
            self.assertTrue(tasks.build_showcase_clip(item.pk))
        self.make_clip.assert_called_once_with(b"original-bytes")
        item.refresh_from_db()
        self.assertRegex(item.clip.name, r"^vstudio/showcase/[0-9a-f]{32}\.mp4$")
        with default_storage.open(item.clip.name) as fh:
            self.assertEqual(fh.read(), b"light-copy")
        # Сборка — не правка человека: «Изменена» в панели не двигается.
        self.assertEqual(item.updated_at, stamp)

        # Кэш сброшен самой сборкой: сайт сразу отдаёт копию.
        card = self.public()[0]
        self.assertEqual(set(card), PUBLIC_KEYS)
        self.assertEqual((card["video_url"], card["full_url"], card["poster_url"]),
                         (item.clip.url, asset.url, asset.thumb_url))
        # В адресе копии нет ни автора, ни материала.
        self.assertTrue(card["video_url"].startswith("/media/vstudio/showcase/"))
        self.assertNotIn(asset.uid, card["video_url"])
        # Панель по-прежнему показывает исходник.
        row = self.panel.get(PANEL).json()["items"][0]
        self.assertEqual(row["take"]["video_url"], asset.url)

    def test_failed_build_keeps_the_original(self):
        take = self.stored(self.work())
        item = self.item(take)
        for outcome in (None, b"", RuntimeError("ffmpeg")):
            with self.subTest(outcome=outcome):
                self.make_clip.reset_mock(side_effect=True)
                if isinstance(outcome, Exception):
                    self.make_clip.side_effect = outcome
                else:
                    self.make_clip.return_value = outcome
                with self.assertLogs("vstudio", level="WARNING"):
                    self.assertFalse(tasks.build_showcase_clip(item.pk))
                self.make_clip.assert_called_once()
        item.refresh_from_db()
        self.assertEqual(item.clip.name, "")
        self.assertFalse(default_storage.exists("vstudio/showcase"))
        self.assertEqual(self.public()[0]["video_url"], take.result_asset.url)

    def test_missing_or_huge_source_is_not_an_error(self):
        lost = self.item(self.work())            # файла исходника на диске нет
        huge = self.item(self.stored(self.work()))
        Asset.objects.filter(pk=huge.take.result_asset_id).update(
            bytes=showcase.CLIP_SOURCE_MAX_BYTES + 1)
        gone = self.item(self.stored(self.work(asset=f.make_asset(
            self.staff, kind="video", deleted_at=timezone.now()))))
        with self.assertLogs("vstudio", level="WARNING"):
            self.assertFalse(showcase.build_clip(lost.pk))
            self.assertFalse(showcase.build_clip(huge.pk))
        self.assertFalse(showcase.build_clip(gone.pk))
        self.assertFalse(showcase.build_clip(10 ** 9))
        self.make_clip.assert_not_called()
        self.assertEqual(len(self.public()), 2)

    def test_broker_down_does_not_break_the_panel(self):
        self.clip_task.side_effect = OSError("брокер недоступен")
        take = self.work()
        with self.assertLogs("vstudio", level="ERROR"), self.captureOnCommitCallbacks(execute=True):
            res = self.panel.post(PANEL, {"take": take.uid}, format="json")
        self.assertEqual(res.status_code, 201, res.content)
        self.assertEqual(self.ids(), [res.json()["id"]])

    def test_rebuild_replaces_the_file(self):
        item = self.built()
        old = item.clip.name
        self.make_clip.return_value = b"second-copy"
        with self.captureOnCommitCallbacks(execute=True):
            self.assertTrue(showcase.build_clip(item.pk))
        item.refresh_from_db()
        self.assertNotEqual(item.clip.name, old)
        self.assertEqual(self.clip_files(), [item.clip.name.rsplit("/", 1)[1]])
        self.assertEqual(self.public()[0]["video_url"], item.clip.url)

    def test_item_removed_during_the_build_leaves_no_file(self):
        item = self.item(self.stored(self.work()))

        def removed_meanwhile(_data):
            ShowcaseItem.objects.filter(pk=item.pk).delete()
            return b"late-copy"

        self.make_clip.side_effect = removed_meanwhile
        self.assertFalse(showcase.build_clip(item.pk))
        self.assertEqual(self.clip_files(), [])

    def test_clip_file_goes_with_the_item(self):
        item = self.built()
        name = item.clip.name
        with self.captureOnCommitCallbacks() as callbacks:
            self.assertEqual(self.panel.delete(f"{PANEL}{item.pk}/").status_code, 204)
        # До фиксации файл на месте: откатится удаление — строка останется с ним.
        self.assertTrue(default_storage.exists(name))
        for callback in callbacks:
            callback()
        self.assertFalse(default_storage.exists(name))
        # Сам результат дубля не трогаем.
        self.assertTrue(default_storage.exists(item.take.result_asset.file))

    def test_clip_file_goes_with_the_take(self):
        item = self.built()
        with self.captureOnCommitCallbacks(execute=True):
            item.take.delete()   # так уходит и удалённый аккаунт: каскадом
        self.assertEqual(self.clip_files(), [])

    def test_deleted_result_takes_the_clip_with_it(self):
        item = self.built()
        name = item.clip.name
        owner = self.client_for(self.staff)
        with self.captureOnCommitCallbacks(execute=True):
            res = owner.delete(f"/api/vstudio/assets/{item.take.result_asset.uid}/")
        self.assertEqual(res.status_code, 204)
        item.refresh_from_db()
        self.assertEqual(item.clip.name, "")
        self.assertFalse(default_storage.exists(name))
        self.assertEqual(self.public(), [])


# ---------------------------------------------------------------- режим и доступ

class ModeTests(ShowcaseCase):
    def test_off_means_no_showcase_and_does_not_poison_the_cache(self):
        item = self.item()
        with override_settings(VSTUDIO_MODE="off"):
            self.assertEqual(self.public(), [])
            self.assertEqual(self.public(self.panel), [])
        self.assertEqual(self.ids(), [item.pk])

    def test_staff_mode_shows_it_to_guests_like_the_catalogue(self):
        item = self.item()
        with override_settings(VSTUDIO_MODE="staff"):
            self.assertEqual(self.ids(), [item.pk])
            self.assertEqual(self.ids(self.client_for(self.author)), [item.pk])

    def test_read_only(self):
        res = self.guest.post(PUBLIC, {}, format="json")
        self.assertEqual(res.status_code, 405)
        self.assertEqual(res.json()["error_code"], "method_not_allowed")


class ThrottleTests(ShowcaseCase):
    def test_guest_requests_do_not_spend_the_shared_anon_bucket(self):
        self.assertEqual(views.ShowcaseView.throttle_classes, [ScopedRateThrottle])
        self.assertEqual(views.ModelsView.throttle_classes, [ScopedRateThrottle])
        self.enterContext(mock.patch("ai.handlers._openrouter_video_catalog", return_value={}))
        with mock.patch.dict(SimpleRateThrottle.THROTTLE_RATES, {"anon": "1/min"}):
            for _ in range(5):
                self.assertEqual(self.guest.get(PUBLIC).status_code, 200)
                self.assertEqual(self.guest.get("/api/vstudio/models/").status_code, 200)
            # Общий счётчик гостя цел: его первый «обычный» запрос проходит,
            # а второй уже упирается в лимит — значит, считали бы и наши десять.
            # Шаг воронки для пробы не годится: у него свой счётчик
            # (payments.tests_vstudio_funnel).
            first = self.guest.get("/api/plans/bonus-settings/")
            second = self.guest.get("/api/plans/bonus-settings/")
        self.assertEqual((first.status_code, second.status_code), (200, 429))

    def test_own_scope_still_limits(self):
        with mock.patch.dict(SimpleRateThrottle.THROTTLE_RATES, {"vstudio_read": "2/min"}):
            codes = [self.guest.get(PUBLIC).status_code for _ in range(3)]
            last = self.guest.get(PUBLIC)
        self.assertEqual(codes, [200, 200, 429])
        self.assertEqual(last.json()["error_code"], "throttled")


# ---------------------------------------------------------------- панель: доступ

class PanelPermissionTests(ShowcaseCase):
    def test_staff_only(self):
        item = self.item()
        take = self.work()
        calls = (("get", PANEL, None), ("post", PANEL, {"take": take.uid}),
                 ("patch", f"{PANEL}{item.pk}/", {"title": "x"}),
                 ("delete", f"{PANEL}{item.pk}/", None))
        for client, code in ((self.guest, 401), (self.client_for(self.author), 403)):
            for method, url, body in calls:
                with self.subTest(code=code, method=method):
                    res = getattr(client, method)(url, body, format="json")
                    self.assertEqual(res.status_code, code)
        item.refresh_from_db()
        self.assertEqual((item.title, ShowcaseItem.objects.count()), ("", 1))
        self.assertEqual(AdminActionLog.objects.count(), 0)

    def test_routes(self):
        self.assertEqual(reverse("adminapi:vstudio-showcase"), PANEL)
        self.assertEqual(reverse("adminapi:vstudio-showcase-item", args=[7]), f"{PANEL}7/")


# ---------------------------------------------------------------- панель: список

class PanelListTests(ShowcaseCase):
    def get(self, **params):
        res = self.panel.get(PANEL, params)
        self.assertEqual(res.status_code, 200, res.content)
        return res.json()

    def test_shape(self):
        take = self.work()
        item = self.item(take, title="Ночной город", category="film", sort=3, show_prompt=True,
                         created_by=self.staff)
        self.work()
        data = self.get()
        self.assertEqual(set(data), {"items", "candidates", "scope", "categories", "public_limit"})
        self.assertEqual((data["scope"], data["public_limit"]), ("staff", 48))
        self.assertEqual([c["key"] for c in data["categories"]],
                         ["film", "ad", "social", "anime", "music", "other"])
        self.assertTrue(all(c["label"] for c in data["categories"]))
        self.assertEqual(set(data["candidates"]), {"count", "page_size", "results"})

        row = data["items"][0]
        self.assertEqual(set(row), ITEM_KEYS)
        self.assertEqual((row["id"], row["title"], row["category"], row["sort"], row["is_active"],
                          row["show_prompt"], row["state"], row["created_by_email"]),
                         (item.pk, "Ночной город", "film", 3, True, True, "live", self.staff.email))
        self.assertEqual(set(row["take"]), TAKE_KEYS)
        self.assertEqual(row["take"]["uid"], take.uid)
        self.assertEqual(row["take"]["video_url"], take.result_asset.url)
        self.assertEqual(row["take"]["prompt"], "Девушка идёт по крыше")
        self.assertEqual((row["take"]["user_email"], row["take"]["user_is_staff"]),
                         (self.staff.email, True))
        self.assertEqual(set(data["candidates"]["results"][0]), TAKE_KEYS)

    def test_state_says_why_a_row_is_not_on_the_site(self):
        live = self.item(sort=0)
        beyond = self.item(sort=1)
        hidden = self.item(is_active=False)
        gone = self.item(self.work(asset=f.make_asset(self.staff, kind="video",
                                                      deleted_at=timezone.now())))
        with mock.patch.object(showcase, "MAX_PUBLIC", 1):
            states = {row["id"]: row["state"] for row in self.get()["items"]}
        self.assertEqual(states, {live.pk: "live", beyond.pk: "over_limit", hidden.pk: "hidden",
                                  gone.pk: "result_gone"})

    def test_candidates_are_finished_works_not_yet_in_the_showcase(self):
        fresh = self.work()
        older = self.work()
        Take.objects.filter(pk=older.pk).update(finished_at=timezone.now() - timedelta(hours=1))
        Take.objects.filter(pk=fresh.pk).update(finished_at=timezone.now())
        self.item()                                    # уже в витрине
        self.work(status="failed")
        self.work(status="running")
        self.work(asset=f.make_asset(self.staff, kind="video", deleted_at=timezone.now()))
        foreign = self.work(self.author)
        Take.objects.filter(pk=foreign.pk).update(finished_at=timezone.now() + timedelta(hours=1))

        staff_only = self.get()["candidates"]
        self.assertEqual([row["uid"] for row in staff_only["results"]], [fresh.uid, older.uid])
        self.assertEqual((staff_only["count"], staff_only["page_size"]), (2, 50))
        everyone = self.get(scope="all")
        self.assertEqual(everyone["scope"], "all")
        self.assertEqual([row["uid"] for row in everyone["candidates"]["results"]],
                         [foreign.uid, fresh.uid, older.uid])
        self.assertEqual(self.get(scope="all", page=2)["candidates"]["results"], [])

    def test_search_by_prompt_author_model_and_uid(self):
        mine = self.work()
        foreign = self.work(self.author)
        type(mine.shot).objects.filter(pk=mine.shot_id).update(prompt_text="Кот в скафандре")

        def found(q, scope="all"):
            return {row["uid"] for row in self.get(scope=scope, q=q)["candidates"]["results"]}

        self.assertEqual(found("скафандр"), {mine.uid})
        self.assertEqual(found("author@"), {foreign.uid})
        self.assertEqual(found("seedance"), {mine.uid, foreign.uid})
        self.assertEqual(found(foreign.uid), {foreign.uid})
        self.assertEqual(found("author@", scope="staff"), set())

    def test_works_with_user_photos_are_marked(self):
        text_only = self.work(self.author)
        with_photo = self.work(self.author, inputs=[f.make_asset(self.author)])
        own = self.work(inputs=[f.make_asset(self.staff)])
        rows = {row["uid"]: row for row in self.get(scope="all")["candidates"]["results"]}
        # Работа пользователя не ставится и без фото: в адресах её файлов — номер аккаунта.
        self.assertEqual((rows[text_only.uid]["own_photos"], rows[text_only.uid]["public_ok"]),
                         (False, False))
        self.assertEqual((rows[with_photo.uid]["own_photos"], rows[with_photo.uid]["public_ok"]),
                         (True, False))
        self.assertEqual((rows[own.uid]["own_photos"], rows[own.uid]["public_ok"]), (True, True))

    def test_unknown_scope(self):
        res = self.panel.get(PANEL, {"scope": "mine"})
        self.assertEqual(res.status_code, 400)
        self.assertIsInstance(res.json()["detail"], str)


# ---------------------------------------------------------------- панель: правки

class PanelWriteTests(ShowcaseCase):
    def post(self, body):
        return self.panel.post(PANEL, body, format="json")

    def patch(self, item, body):
        return self.panel.patch(f"{PANEL}{item.pk}/", body, format="json")

    def refused(self, res, code=400):
        self.assertEqual(res.status_code, code, res.content)
        self.assertEqual(set(res.json()), {"detail"})
        self.assertIsInstance(res.json()["detail"], str)
        self.assertTrue(res.json()["detail"])

    def test_add(self):
        take = self.work()
        res = self.panel.post(PANEL, {"take": take.uid, "title": "  Ночной   город ",
                                      "category": "film", "sort": 2, "show_prompt": True},
                              format="json", HTTP_X_FORWARDED_FOR="203.0.113.7")
        self.assertEqual(res.status_code, 201, res.content)
        row = res.json()
        self.assertEqual(set(row), ITEM_KEYS)
        item = ShowcaseItem.objects.get()
        self.assertEqual((item.pk, item.take_id, item.created_by), (row["id"], take.pk, self.staff))
        self.assertEqual((item.title, item.category, item.sort, item.is_active, item.show_prompt),
                         ("Ночной город", "film", 2, True, True))
        self.assertEqual((row["state"], row["take"]["uid"]), ("live", take.uid))

        log = self.logs().get()
        self.assertEqual((log.actor, log.action, log.target_id, log.ip),
                         (self.staff, "settings.edit", str(item.pk), "203.0.113.7"))
        self.assertEqual(log.before, {"vstudio_showcase": None})
        self.assertEqual(log.after, {"vstudio_showcase": {
            "take": take.uid, "title": "Ночной город", "category": "film", "sort": 2,
            "is_active": True, "show_prompt": True}})

    def test_defaults_keep_the_prompt_private(self):
        row = self.post({"take": self.work().uid}).json()
        self.assertEqual((row["title"], row["category"], row["sort"], row["is_active"],
                          row["show_prompt"]), ("", "other", 0, True, False))

    def test_same_take_twice_is_one_row(self):
        take = self.work()
        first = self.post({"take": take.uid, "title": "Первая"})
        again = self.post({"take": take.uid, "title": "Вторая"})
        self.assertEqual((first.status_code, again.status_code), (201, 200))
        self.assertEqual(again.json()["id"], first.json()["id"])
        self.assertEqual(again.json()["title"], "Первая")
        self.assertEqual((ShowcaseItem.objects.count(), self.logs().count()), (1, 1))

    def test_unknown_take(self):
        for uid in ("0" * 32, "nonsense", None, 7):
            with self.subTest(uid=uid):
                self.refused(self.post({"take": uid}), 404)
        self.refused(self.post({}), 404)

    def test_only_finished_work_with_a_live_result(self):
        deleted = f.make_asset(self.staff, kind="video", deleted_at=timezone.now())
        for take in (self.work(status="running"), self.work(status="failed"),
                     self.work(asset=deleted)):
            with self.subTest(status=take.status):
                self.refused(self.post({"take": take.uid}))
        self.assertEqual((ShowcaseItem.objects.count(), self.logs().count()), (0, 0))

    def test_user_work_is_refused(self):
        with_photo = self.work(self.author, inputs=[f.make_asset(self.author)])
        for take in (with_photo, self.work(self.author)):
            with self.subTest(mode=take.mode):
                res = self.post({"take": take.uid})
                self.refused(res)
                self.assertIn("сотрудников", res.json()["detail"])
        self.assertEqual((ShowcaseItem.objects.count(), self.logs().count()), (0, 0))
        # Работы сотрудников — можно, и со своими фото тоже.
        self.assertEqual(self.post({"take": self.work().uid}).status_code, 201)
        own = self.work(inputs=[f.make_asset(self.staff)])
        self.assertEqual(self.post({"take": own.uid}).status_code, 201)

    def test_bad_fields_write_nothing(self):
        take = self.work()
        item = self.item(title="Было")
        for body in ({"title": "я" * 81}, {"title": 5}, {"category": "nonsense"},
                     {"category": None}, {"sort": "3"}, {"sort": True}, {"sort": 1.5},
                     {"sort": 100_001}, {"is_active": "false"}, {"show_prompt": 1}):
            with self.subTest(body=body):
                self.refused(self.post({"take": take.uid, **body}))
                self.refused(self.patch(item, {"title": "Стало", **body}))
        item.refresh_from_db()
        self.assertEqual((item.title, ShowcaseItem.objects.count(), self.logs().count()),
                         ("Было", 1, 0))

    def test_edit_logs_only_what_changed(self):
        item = self.item(title="Было", category="film")
        res = self.patch(item, {"title": "Стало", "category": "film", "sort": 4,
                                "is_active": False, "show_prompt": True})
        self.assertEqual(res.status_code, 200, res.content)
        row = res.json()
        self.assertEqual((row["title"], row["category"], row["sort"], row["is_active"],
                          row["show_prompt"], row["state"]),
                         ("Стало", "film", 4, False, True, "hidden"))
        item.refresh_from_db()
        self.assertEqual((item.title, item.sort, item.is_active, item.show_prompt),
                         ("Стало", 4, False, True))
        log = self.logs().get()
        self.assertEqual((log.actor, log.action, log.target_id),
                         (self.staff, "settings.edit", str(item.pk)))
        self.assertEqual(log.before, {"vstudio_showcase": {
            "title": "Было", "sort": 0, "is_active": True, "show_prompt": False}})
        self.assertEqual(log.after, {"vstudio_showcase": {
            "title": "Стало", "sort": 4, "is_active": False, "show_prompt": True}})

    def test_same_values_write_no_log(self):
        item = self.item(title="Было")
        stamp = item.updated_at
        self.assertEqual(self.patch(item, {"title": "Было", "sort": 0}).status_code, 200)
        item.refresh_from_db()
        self.assertEqual((item.updated_at, self.logs().count()), (stamp, 0))

    def test_nothing_to_change(self):
        item = self.item()
        other = self.work()
        self.refused(self.patch(item, {}))
        # Работу в строке не подменить: поле take при правке не читается.
        self.refused(self.patch(item, {"take": other.uid}))
        item.refresh_from_db()
        self.assertNotEqual(item.take_id, other.pk)

    def test_remove_keeps_the_work_itself(self):
        take = self.work()
        item = self.item(take, title="Ночной город")
        pk = item.pk
        res = self.panel.delete(f"{PANEL}{pk}/")
        self.assertEqual((res.status_code, res.content), (204, b""))
        self.assertFalse(ShowcaseItem.objects.exists())
        self.assertTrue(Take.objects.filter(pk=take.pk).exists())
        self.assertTrue(Asset.objects.filter(pk=take.result_asset_id, deleted_at__isnull=True).exists())
        log = self.logs().get()
        self.assertEqual((log.actor, log.target_id, log.after), (self.staff, str(pk),
                                                                 {"vstudio_showcase": None}))
        self.assertEqual(log.before["vstudio_showcase"]["title"], "Ночной город")
        self.assertEqual(log.before["vstudio_showcase"]["take"], take.uid)

    def test_missing_row(self):
        self.refused(self.panel.patch(f"{PANEL}999/", {"title": "x"}, format="json"), 404)
        self.refused(self.panel.delete(f"{PANEL}999/"), 404)

    def test_no_log_no_change(self):
        take = self.work()
        item = self.item(title="Было")
        with mock.patch("vstudio.showcase.log_admin_action", side_effect=RuntimeError("журнал")):
            for call in (lambda: self.post({"take": take.uid}),
                         lambda: self.patch(item, {"title": "Стало"}),
                         lambda: self.panel.delete(f"{PANEL}{item.pk}/")):
                with self.assertRaises(RuntimeError):
                    call()
        item.refresh_from_db()
        self.assertEqual((item.title, ShowcaseItem.objects.count()), ("Было", 1))


# ---------------------------------------------------------------- Django-админка

class DjangoAdminTests(ShowcaseCase):
    def setUp(self):
        super().setUp()
        self.admin_user = f.make_user(is_staff=True, is_superuser=True)
        self.client.force_login(self.admin_user)

    def test_pages_open(self):
        item = self.item(title="Ночной город")
        self.item(self.work(kind="image"))
        lost_file = self.item()
        Take.objects.filter(pk=lost_file.take_id).update(result_asset=None)
        for url in (reverse("admin:vstudio_showcaseitem_changelist"),
                    reverse("admin:vstudio_showcaseitem_change", args=[item.pk]),
                    reverse("admin:vstudio_showcaseitem_add")):
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 200)

    def test_add_remembers_who_and_take_is_fixed_afterwards(self):
        take = self.work()
        res = self.client.post(reverse("admin:vstudio_showcaseitem_add"), {
            "take": take.pk, "title": "Из админки", "category": "ad", "sort": 1, "is_active": "on"})
        self.assertEqual(res.status_code, 302)
        item = ShowcaseItem.objects.get()
        self.assertEqual((item.take, item.created_by, item.category), (take, self.admin_user, "ad"))

        other = self.work()
        res = self.client.post(reverse("admin:vstudio_showcaseitem_change", args=[item.pk]), {
            "take": other.pk, "title": "Переименовали", "category": "ad", "sort": 1})
        self.assertEqual(res.status_code, 302)
        item.refresh_from_db()
        self.assertEqual((item.take, item.title, item.is_active), (take, "Переименовали", False))

    def test_user_work_is_refused_here_too(self):
        res = self.client.post(reverse("admin:vstudio_showcaseitem_add"), {
            "take": self.work(self.author).pk, "title": "Чужая", "category": "ad", "sort": 1,
            "is_active": "on"})
        self.assertContains(res, "только работы сотрудников")
        self.assertFalse(ShowcaseItem.objects.exists())

    def test_rebuild_clip_action_skips_images(self):
        video = self.item()
        image = self.item(self.work(kind="image"))
        with self.captureOnCommitCallbacks(execute=True):
            res = self.client.post(reverse("admin:vstudio_showcaseitem_changelist"), {
                "action": "rebuild_clip", "_selected_action": [video.pk, image.pk]})
        self.assertEqual(res.status_code, 302)
        self.clip_task.assert_called_once_with(args=[video.pk])

    def test_asset_actions_reach_the_showcase_at_once(self):
        take = self.work()
        item = self.item(take)
        self.assertEqual(self.ids(), [item.pk])
        for action, expected in (("soft_delete", []), ("restore", [item.pk])):
            with self.subTest(action=action), self.captureOnCommitCallbacks(execute=True):
                res = self.client.post(reverse("admin:vstudio_asset_changelist"), {
                    "action": action, "_selected_action": [take.result_asset_id]})
                self.assertEqual(res.status_code, 302)
            self.assertEqual(self.ids(), expected)
        # Вернули результат — лёгкую копию собираем заново.
        self.clip_task.assert_called_once_with(args=[item.pk])
