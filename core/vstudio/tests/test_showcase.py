"""Витрина первого экрана: публичный список и управление им из панели.

Главное, что проверяем:
- наружу уходит только включённая строка с готовым, не удалённым результатом
  и только закрытый список полей — без uid, автора и фото, с которыми снято;
- сценарии карусели: 12 ключей по порядку и «Другое», прежние разделы
  переносит миграция 0004 (её шаг данных проверяем напрямую);
- первый кадр работы «Image → Video» выходит наружу только с галочкой
  «Показывать запрос» и только если он один, готов, не удалён и принадлежит
  тому же сотруднику; всё остальное из присланного человеком — никогда;
- порядок (sort, затем новые) и потолок в 48 работ;
- «Тренды» (placement=trends): отдельный список trends рядом с items — в
  items только карусель, как у прежнего фронта; та же карточка и те же
  правила показа, свой потолок в 24 работы, только ролики;
- кэш на 5 минут сбрасывает любая правка — но после фиксации транзакции;
- гостевые запросы первого экрана не тратят общий anon-счётчик сайта;
- панель: только staff, каждая запись — со строкой в журнале действий;
- в витрину ставятся только работы сотрудников: в адресах файлов виден номер
  аккаунта автора;
- лёгкая копия ролика: собирается после фиксации, не ломает ни панель, ни
  сайт, уходит вместе со строкой и с результатом (ffmpeg в тестах подменён);
- размер карусели (reel_size): настройка панели от 5 до 48, сайт получает её
  рядом со списком, а не из его кэша; мусор в базе не роняет первый экран;
  правка — только целым числом в границах, со строкой в журнале.
"""
import importlib
import json
from datetime import timedelta
from unittest import mock

from django.apps import apps as django_apps
from django.core.cache import cache
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.db import DatabaseError, connection, migrations
from django.test import TestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient
from rest_framework.throttling import ScopedRateThrottle, SimpleRateThrottle

from adminapi.models import AppSetting
from adminapi.runtime import CACHE_PREFIX, KEYS, set_runtime
from audit.models import AdminActionLog

from .. import showcase, tasks, views
from ..models import Asset, ShowcaseItem, Take
from . import factories as f

CACHES = {"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache",
                      "LOCATION": "vstudio-showcase"}}
PUBLIC = "/api/vstudio/showcase/"
PANEL = "/api/manage/vstudio/showcase/"
PUBLIC_KEYS = {"id", "title", "category", "kind", "model", "aspect_ratio", "duration_s", "width",
               "height", "video_url", "image_url", "poster_url", "full_url", "prompt", "params",
               "needs_photo", "start_frame_url"}
# В панели «свои фото» называются own_photos и видны без галочки — needs_photo там нет.
TAKE_KEYS = (PUBLIC_KEYS - {"id", "title", "category", "full_url", "needs_photo"}) | {
    "uid", "status", "own_photos", "public_ok", "user_email", "user_is_staff", "created_at",
    "finished_at"}
ITEM_KEYS = {"id", "title", "category", "placement", "sort", "is_active", "show_prompt", "state",
             "created_by_email", "created_at", "updated_at", "take"}
RESPONSE_KEYS = {"items", "trends", "reel_size"}
# Порядок карусели — тот же список у фронта (home/scenarios.ts).
SCENARIOS = ["film", "ad", "person", "car", "action", "scifi", "fashion", "music", "i2v", "anim",
             "real", "vertical"]
SCENARIO_NAMES = {
    "film": "Киносцена", "ad": "Реклама товара", "person": "Персонаж", "car": "Автомобиль",
    "action": "Экшен", "scifi": "Фантастика", "fashion": "Fashion", "music": "Музыкальный клип",
    "i2v": "Image → Video", "anim": "Анимация", "real": "Реалистичная сцена",
    "vertical": "Reels / TikTok", "other": "Другое"}
OLD_CATEGORIES = ["film", "ad", "social", "anime", "music", "other"]
FIRST, LAST = "first_frame", "last_frame"
REEL_KEY = "vstudio_reel_size"
REEL_RANGE = "Роликов в карусели — целое число от 5 до 48"


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
        self.assertEqual(set(res.json()), RESPONSE_KEYS)
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
            "needs_photo": False, "start_frame_url": None,
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
        # Без галочки сайт не знает и того, что работа снята со своим фото.
        self.assertIs(card["needs_photo"], False)

        cache.clear()
        ShowcaseItem.objects.filter(pk=item.pk).update(show_prompt=True)
        card = self.public()[0]
        # Фото в запросе названо меткой, а не идентификатором.
        self.assertEqual(card["prompt"], "Девушка идёт по крыше @Image 1")
        self.assertEqual(card["params"], {"duration": 5, "resolution": "720p", "aspect_ratio": "16:9"})
        # Референс — не первый кадр: известно только, что своё фото понадобится.
        self.assertEqual((card["needs_photo"], card["start_frame_url"]), (True, None))

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
        # Референс и кадр вместе — режим референсов: кадр здесь лишь подсказка модели.
        take = self.work(inputs=[ref, (frame, FIRST)])
        self.item(take, show_prompt=True, created_by=self.staff)
        self.work(self.author)   # чужой дубль вне витрины
        cards = self.public()
        self.assertEqual(len(cards), 1)
        card = cards[0]
        self.assertEqual(set(card), PUBLIC_KEYS)
        self.assertEqual(set(card["model"]), {"id", "name"})
        self.assertEqual((take.mode, card["needs_photo"], card["start_frame_url"]),
                         ("r2v", True, None))
        dump = json.dumps(card, ensure_ascii=False)
        asset = take.result_asset
        for secret in (ref.uid, frame.uid, ref.url, ref.thumb_url, frame.url, frame.thumb_url,
                       take.uid, take.shot.uid, take.project.uid, self.staff.email,
                       self.author.email, "example.com"):
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


# ---------------------------------------------------------------- первый кадр

class StartFrameTests(ShowcaseCase):
    """Первый кадр — единственный материал запроса, который может уйти наружу."""

    def photo(self, user=None) -> Asset:
        return f.make_asset(user or self.staff)

    def frame_work(self, **kw):
        """Работа «первый кадр → видео» и сам кадр."""
        frame = self.photo()
        return self.work(inputs=[(frame, FIRST)], **kw), frame

    def card(self, take, *, show_prompt=True) -> dict:
        """Карточка работы на сайте — по умолчанию с галочкой «Показывать запрос»."""
        item = self.item(take, show_prompt=show_prompt)
        cache.clear()
        return next(row for row in self.public() if row["id"] == item.pk)

    def frame_of(self, take, **kw):
        return self.card(take, **kw)["start_frame_url"]

    def test_image_to_video_shows_what_it_started_from(self):
        take, frame = self.frame_work()
        self.assertEqual(take.mode, "i2v")
        card = self.card(take)
        self.assertEqual(set(card), PUBLIC_KEYS)
        # Наружу идёт лёгкая копия кадра, а не оригинал.
        self.assertEqual((card["needs_photo"], card["start_frame_url"]), (True, frame.thumb_url))
        self.assertTrue(card["start_frame_url"].startswith(f"/media/vstudio/{self.staff.pk}/"))
        # uid кадра есть только внутри его же адреса.
        dump = json.dumps(card, ensure_ascii=False).replace(card["start_frame_url"], "")
        self.assertNotIn(frame.uid, dump)

    def test_frame_without_a_light_copy_goes_as_is(self):
        take, frame = self.frame_work()
        Asset.objects.filter(pk=frame.pk).update(thumb="")
        self.assertEqual(self.frame_of(take), frame.url)

    def test_not_without_the_owner_permission(self):
        take, frame = self.frame_work()
        card = self.card(take, show_prompt=False)
        self.assertEqual((card["needs_photo"], card["start_frame_url"]), (False, None))
        self.assertNotIn(frame.uid, json.dumps(card))

    def test_first_and_last_frame_shows_only_the_first(self):
        first, last = self.photo(), self.photo()
        take = self.work(inputs=[(first, FIRST), (last, LAST)])
        self.assertEqual(take.mode, "flf2v")
        card = self.card(take)
        self.assertEqual(card["start_frame_url"], first.thumb_url)
        self.assertNotIn(last.uid, json.dumps(card))

    def test_other_modes_keep_their_pictures(self):
        cases = {
            "t2v": (self.work(), False),
            "r2v": (self.work(inputs=[self.photo()]), True),
            "r2v_pin": (self.work(inputs=[self.photo(), (self.photo(), FIRST)], mode="r2v_pin"),
                        True),
            "flf2v": (self.work(inputs=[(self.photo(), LAST)]), True),   # только последний кадр
            "t2i": (self.work(kind="image"), False),
            "i2i": (self.work(kind="image", inputs=[self.photo()]), True),
        }
        for mode, (take, needs_photo) in cases.items():
            with self.subTest(mode=mode):
                self.assertEqual(take.mode, mode)
                card = self.card(take)
                self.assertEqual((card["needs_photo"], card["start_frame_url"]),
                                 (needs_photo, None))

    def test_frame_that_is_not_safe_to_show_stays_private(self):
        changes = {
            "удалён человеком": {"deleted_at": timezone.now()},
            "ещё создаётся": {"status": Asset.STATUS_PENDING},
            "не получился": {"status": Asset.STATUS_FAILED},
            "файла нет": {"file": ""},
            "не картинка": {"kind": Asset.KIND_VIDEO},
            "чужой материал": {"user": self.author},
        }
        for name, change in changes.items():
            with self.subTest(frame=name):
                take, frame = self.frame_work()
                Asset.objects.filter(pk=frame.pk).update(**change)
                card = self.card(take)
                # Работа остаётся на сайте и по-прежнему просит своё фото — но без кадра.
                self.assertEqual((card["needs_photo"], card["start_frame_url"]), (True, None))
                self.assertNotIn(frame.uid, json.dumps(card))

    def test_only_a_staff_work(self):
        # Строку поставили в обход панели…
        foreign = self.work(self.author, inputs=[(self.photo(self.author), FIRST)])
        self.assertFalse(showcase.can_publish(foreign))
        self.assertIsNone(self.frame_of(foreign))
        # …или автор перестал быть сотрудником уже после публикации.
        take, _frame = self.frame_work()
        type(self.staff).objects.filter(pk=self.staff.pk).update(is_staff=False)
        self.assertIsNone(self.frame_of(take))

    def test_exactly_one_frame_went_to_the_model(self):
        first, second = self.photo(), self.photo()

        def gone(asset, reason):
            return {"asset": asset.uid, "slot": FIRST, "reason": reason}

        off = {"asset": second, "slot": FIRST, "included": False}
        # Кадр выключен человеком: модели он не ушёл — не уходит и на сайт.
        self.assertIsNone(self.frame_of(self.work(inputs=[off], mode="i2v")))
        # Два включённых кадра, и нигде не сказано, какой лишний, — двоякий случай.
        self.assertIsNone(self.frame_of(self.work(inputs=[(first, FIRST), (second, FIRST)])))
        # Единственный кадр значится неотправленным.
        self.assertIsNone(self.frame_of(self.work(inputs=[(first, FIRST)],
                                                  dropped=[gone(first, "duplicate_frame")])))
        # Лишний записан в «не отправлено» — остаётся тот, что ушёл модели.
        take = self.work(inputs=[(first, FIRST), (second, FIRST)],
                         dropped=[gone(second, "duplicate_frame")])
        self.assertEqual(self.frame_of(take), first.thumb_url)
        take = self.work(inputs=[off, (first, FIRST)], dropped=[gone(second, "excluded_by_user")])
        self.assertEqual((take.mode, self.frame_of(take)), ("i2v", first.thumb_url))

    def test_odd_dropped_list_is_not_an_error(self):
        # Take.dropped — JSON: мусор в нём не должен ронять первый экран.
        for dropped in ({"asset": "x"}, [None, "x", 7, {"slot": FIRST}], None):
            with self.subTest(dropped=dropped):
                take, frame = self.frame_work()
                take.dropped = dropped
                self.assertEqual(showcase.start_frame_url(take), frame.thumb_url)

    def test_deleted_frame_leaves_the_site_at_once(self):
        take, frame = self.frame_work()
        item = self.item(take, show_prompt=True)
        self.assertEqual(self.public()[0]["start_frame_url"], frame.thumb_url)
        with self.captureOnCommitCallbacks(execute=True):
            res = self.client_for(self.staff).delete(f"/api/vstudio/assets/{frame.uid}/")
        self.assertEqual(res.status_code, 204)
        # Без ожидания кэша. Сама работа остаётся: удалён не результат.
        card = self.public()[0]
        self.assertEqual((card["id"], card["needs_photo"], card["start_frame_url"]),
                         (item.pk, True, None))

    def test_list_reads_all_frames_in_one_go(self):
        def queries() -> int:
            cache.clear()
            with CaptureQueriesContext(connection) as ctx:
                cards = showcase.public_items()
            self.assertTrue(cards and all(card["start_frame_url"] for card in cards))
            return len(ctx)

        self.item(self.frame_work()[0], show_prompt=True)
        # Карусель, «Тренды» и материалы запросов обоих — сколько бы работ ни было.
        self.assertEqual(queries(), 3)
        for _ in range(3):
            self.item(self.frame_work()[0], show_prompt=True)
        self.item(self.frame_work()[0], show_prompt=True, placement="trends")
        self.assertEqual(queries(), 3)

    def test_panel_sees_the_frame_before_it_goes_public(self):
        take, frame = self.frame_work()
        self.item(take)   # галочки «Показывать запрос» нет
        spare, spare_frame = self.frame_work()
        users = self.work(self.author, inputs=[(self.photo(self.author), FIRST)])
        data = self.panel.get(PANEL, {"scope": "all"}).json()
        self.assertEqual(data["items"][0]["take"]["start_frame_url"], frame.thumb_url)
        rows = {row["uid"]: row for row in data["candidates"]["results"]}
        self.assertEqual(rows[spare.uid]["start_frame_url"], spare_frame.thumb_url)
        # Работу пользователя в витрину не поставить — и его кадр панель здесь не показывает.
        self.assertEqual((rows[users.uid]["own_photos"], rows[users.uid]["start_frame_url"]),
                         (True, None))
        self.assertIsNone(self.public()[0]["start_frame_url"])


# ---------------------------------------------------------------- сценарии

class ScenarioTests(ShowcaseCase):
    def test_list_is_the_carousel_order(self):
        self.assertEqual(list(ShowcaseItem.SCENARIOS), SCENARIOS)
        self.assertEqual(showcase.SCENARIOS, ShowcaseItem.SCENARIOS)
        self.assertEqual(list(showcase.CATEGORIES), SCENARIOS + ["other"])
        self.assertEqual(dict(showcase.CATEGORY_CHOICES), SCENARIO_NAMES)
        field = ShowcaseItem._meta.get_field("category")
        self.assertEqual((field.max_length, field.default, field.verbose_name),
                         (8, "other", "Сценарий"))
        # Поле не расширяли: длиннее ключ в базу PostgreSQL не запишется.
        self.assertTrue(all(len(key) <= field.max_length for key in showcase.CATEGORIES))

    def test_panel_takes_every_scenario(self):
        for key in showcase.CATEGORIES:
            with self.subTest(key=key):
                res = self.panel.post(PANEL, {"take": self.work().uid, "category": key},
                                      format="json")
                self.assertEqual(res.status_code, 201, res.content)
                self.assertEqual(res.json()["category"], key)
        item = ShowcaseItem.objects.get(category="other")
        res = self.panel.patch(f"{PANEL}{item.pk}/", {"category": "vertical"}, format="json")
        self.assertEqual((res.status_code, res.json()["category"]), (200, "vertical"))
        cache.clear()
        self.assertEqual(sorted(row["category"] for row in self.public()),
                         sorted(SCENARIOS + ["vertical"]))

    def test_old_sections_are_refused(self):
        item = self.item(category="film")
        for key in ("social", "anime", "Film", "", "verticals"):
            with self.subTest(key=key):
                for res in (self.panel.post(PANEL, {"take": self.work().uid, "category": key},
                                            format="json"),
                            self.panel.patch(f"{PANEL}{item.pk}/", {"category": key},
                                             format="json")):
                    self.assertEqual(res.status_code, 400, res.content)
                    self.assertEqual(res.json()["detail"],
                                     "Сценарий: " + ", ".join(SCENARIOS + ["other"]))
        item.refresh_from_db()
        self.assertEqual((item.category, ShowcaseItem.objects.count()), ("film", 1))


class ScenarioMigrationTests(ShowcaseCase):
    """Шаг данных миграции 0004: «Соцсети» → Reels / TikTok, «Аниме» → «Анимация».

    Тестовая база строится прямо из моделей, миграции в ней не идут — функции
    шага вызываем сами, на настоящих моделях.
    """

    def setUp(self):
        super().setUp()
        self.migration = importlib.import_module("vstudio.migrations.0004_showcase_scenarios")

    def rows(self, keys) -> list:
        return [self.item(category=key).pk for key in keys]

    def categories(self, pks) -> list:
        found = dict(ShowcaseItem.objects.filter(pk__in=pks).values_list("pk", "category"))
        return [found[pk] for pk in pks]

    def test_forwards_moves_the_two_old_keys(self):
        pks = self.rows(OLD_CATEGORIES)
        stamps = list(ShowcaseItem.objects.order_by("pk").values_list("updated_at", flat=True))
        self.migration.forwards(django_apps, None)
        self.assertEqual(self.categories(pks), ["film", "ad", "vertical", "anim", "music", "other"])
        self.assertTrue(set(self.categories(pks)) <= set(showcase.CATEGORIES))
        # Перенос — не правка человека: «Изменена» в панели не двигается.
        self.assertEqual(
            list(ShowcaseItem.objects.order_by("pk").values_list("updated_at", flat=True)), stamps)
        # Повторный запуск ничего не портит.
        self.migration.forwards(django_apps, None)
        self.assertEqual(self.categories(pks), ["film", "ad", "vertical", "anim", "music", "other"])

    def test_backwards_leaves_only_what_the_old_list_knew(self):
        pks = self.rows(SCENARIOS + ["other"])
        self.migration.backwards(django_apps, None)
        self.assertEqual(self.categories(pks), [
            "film", "ad", "other", "other", "other", "other", "other", "music", "other", "anime",
            "other", "social", "other"])
        self.assertTrue(set(self.categories(pks)) <= set(OLD_CATEGORIES))

    def test_there_and_back(self):
        pks = self.rows(OLD_CATEGORIES)
        self.migration.forwards(django_apps, None)
        self.migration.backwards(django_apps, None)
        self.assertEqual(self.categories(pks), OLD_CATEGORIES)

    def test_wired_into_the_migration(self):
        migration = self.migration.Migration
        self.assertEqual(migration.dependencies, [("vstudio", "0003_showcaseitem")])
        alter, data = migration.operations
        self.assertIsInstance(alter, migrations.AlterField)
        self.assertEqual((alter.model_name, alter.name), ("showcaseitem", "category"))
        # Список в миграции — тот же, что у модели: makemigrations нечего добавить.
        self.assertEqual(alter.field.choices, ShowcaseItem.CATEGORY_CHOICES)
        self.assertEqual((alter.field.max_length, alter.field.default, alter.field.verbose_name),
                         (8, "other", "Сценарий"))
        self.assertIsInstance(data, migrations.RunPython)
        self.assertEqual((data.code, data.reverse_code, data.reversible),
                         (self.migration.forwards, self.migration.backwards, True))
        # Каждый новый ключ знает дорогу назад, каждый прежний — вперёд.
        self.assertEqual(set(self.migration.RESTORED), set(SCENARIOS) - set(OLD_CATEGORIES))
        self.assertEqual(set(self.migration.RENAMED),
                         set(OLD_CATEGORIES) - set(SCENARIOS + ["other"]))


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
        self.item(title="Тренд", placement="trends")
        # v2: в кэше оба списка; прежний ключ со списком одной карусели не читается.
        self.assertEqual((showcase.CACHE_KEY, showcase.CACHE_S), ("vstudio:showcase:v2", 300))
        cache.set("vstudio:showcase:v1", [{"id": 0}], 300)
        with mock.patch.object(showcase.cache, "set", wraps=showcase.cache.set) as store:
            first = showcase.public_showcase()
        store.assert_called_once_with(showcase.CACHE_KEY, first, 300)
        self.assertEqual(set(first), {"items", "trends"})
        self.assertEqual(([row["title"] for row in first["items"]],
                          [row["title"] for row in first["trends"]]), (["Первая"], ["Тренд"]))
        with self.assertNumQueries(0):
            self.assertEqual(showcase.public_showcase(), first)
            self.assertEqual(showcase.public_items(), first["items"])
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
                 ("patch", PANEL, {"reel_size": 24}),
                 ("patch", f"{PANEL}{item.pk}/", {"title": "x"}),
                 ("delete", f"{PANEL}{item.pk}/", None))
        for client, code in ((self.guest, 401), (self.client_for(self.author), 403)):
            for method, url, body in calls:
                with self.subTest(code=code, method=method, url=url):
                    res = getattr(client, method)(url, body, format="json")
                    self.assertEqual(res.status_code, code)
        item.refresh_from_db()
        self.assertEqual((item.title, ShowcaseItem.objects.count()), ("", 1))
        self.assertEqual((showcase.reel_size(), AppSetting.objects.filter(key=REEL_KEY).exists()),
                         (12, False))
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
        self.assertEqual(set(data), {"items", "candidates", "scope", "categories", "placements",
                                     "public_limit", "trends_limit", "reel_size", "reel_size_min",
                                     "reel_size_max"})
        self.assertEqual((data["scope"], data["public_limit"], data["trends_limit"]),
                         ("staff", 48, 24))
        self.assertEqual(data["placements"], [{"key": "reel", "label": "Карусель"},
                                              {"key": "trends", "label": "Тренды"}])
        self.assertEqual((data["reel_size"], data["reel_size_min"], data["reel_size_max"]),
                         (12, 5, 48))
        # Сценарии — в порядке карусели, «Другое» последним; подписи — как на сайте.
        self.assertEqual([c["key"] for c in data["categories"]], SCENARIOS + ["other"])
        self.assertEqual({c["key"]: c["label"] for c in data["categories"]}, SCENARIO_NAMES)
        self.assertEqual(set(data["candidates"]), {"count", "page_size", "results"})

        row = data["items"][0]
        self.assertEqual(set(row), ITEM_KEYS)
        self.assertEqual((row["id"], row["title"], row["category"], row["placement"], row["sort"],
                          row["is_active"], row["show_prompt"], row["state"],
                          row["created_by_email"]),
                         (item.pk, "Ночной город", "film", "reel", 3, True, True, "live",
                          self.staff.email))
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
            "take": take.uid, "title": "Ночной город", "category": "film", "placement": "reel",
            "sort": 2, "is_active": True, "show_prompt": True}})

    def test_defaults_keep_the_prompt_private(self):
        row = self.post({"take": self.work().uid}).json()
        self.assertEqual((row["title"], row["category"], row["placement"], row["sort"],
                          row["is_active"], row["show_prompt"]),
                         ("", "other", "reel", 0, True, False))

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
                     {"category": None}, {"placement": "Trends"}, {"placement": None},
                     {"placement": ["trends"]}, {"sort": "3"}, {"sort": True}, {"sort": 1.5},
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


# ---------------------------------------------------------------- размер карусели

class ReelSizeCase(ShowcaseCase):
    def stored(self):
        """Что лежит в настройках: строка значения или None, если её не писали."""
        return AppSetting.objects.filter(key=REEL_KEY).values_list("value", flat=True).first()

    def store(self, raw: str) -> None:
        """Положить значение в обход панели — так мусор и попадает в базу."""
        AppSetting.objects.update_or_create(key=REEL_KEY, defaults={"value": raw})
        cache.clear()

    def site(self, client=None) -> int:
        res = (client or self.guest).get(PUBLIC)
        self.assertEqual(res.status_code, 200, res.content)
        return res.json()["reel_size"]

    def reel_logs(self):
        # Настройка — не строка витрины: у записи журнала нет объекта.
        return AdminActionLog.objects.filter(target_type="").order_by("pk")


class ReelSizeTests(ReelSizeCase):
    def test_agreed_key_and_bounds(self):
        self.assertEqual((showcase.REEL_SIZE_KEY, showcase.REEL_SIZE_MIN, showcase.REEL_SIZE_MAX,
                          showcase.REEL_SIZE_DEFAULT), (REEL_KEY, 5, 48, 12))
        # Больше, чем сайт получает работ, карусели взять неоткуда.
        self.assertEqual(showcase.REEL_SIZE_MAX, showcase.MAX_PUBLIC)
        self.assertIn(REEL_KEY, KEYS)

    def test_default_until_the_owner_sets_it(self):
        self.assertEqual((showcase.reel_size(), self.stored()), (12, None))
        self.assertEqual(self.site(), 12)
        # Так поле ищет проверка после выкладки (docs/UPDATE.md).
        self.assertIn(b'"reel_size":12', self.guest.get(PUBLIC).content)

    def test_stored_value_is_clamped_and_garbage_falls_back(self):
        cases = {
            "24": 24, "5": 5, "48": 48, " 36 ": 36,
            # Вне границ — ближайшая граница.
            "4": 5, "0": 5, "-7": 5, "49": 48, "100000": 48,
            # Не целое число — размер по умолчанию.
            "": 12, "abc": 12, "12.5": 12, "24.0": 12, "1e2": 12, "True": 12, "None": 12,
            "[24]": 12, "9" * 5000: 12,
        }
        for raw, expected in cases.items():
            with self.subTest(raw=raw[:12]):
                self.store(raw)
                self.assertEqual(showcase.reel_size(), expected)
                self.assertEqual(self.site(), expected)

    def test_wrong_type_from_the_settings_layer(self):
        cases = ((True, 12), (False, 12), ("24", 12), (None, 12), (24.0, 12), ([24], 12),
                 (7, 7), (3, 5), (500, 48))
        for value, expected in cases:
            with self.subTest(value=value), \
                    mock.patch("adminapi.runtime.get_runtime", return_value=value):
                self.assertEqual(showcase.reel_size(), expected)

    def test_never_raises(self):
        with mock.patch("adminapi.runtime.get_runtime", side_effect=RuntimeError("настройки")):
            self.assertEqual(showcase.reel_size(), 12)
        with mock.patch.object(showcase.cache, "get", side_effect=OSError("кэш недоступен")):
            self.assertEqual(showcase.reel_size(), 12)
        with mock.patch.object(showcase.transaction, "atomic", side_effect=DatabaseError("база")):
            self.assertEqual(showcase.reel_size(), 12)

    def test_site_survives_an_unreadable_settings_table(self):
        item = self.item()
        self.store("24")
        with mock.patch.object(AppSetting.objects, "filter",
                               side_effect=DatabaseError("таблицы настроек нет")):
            res = self.guest.get(PUBLIC)
        self.assertEqual(res.status_code, 200, res.content)
        # Работы на месте, размер — по умолчанию: настройки первый экран не роняют.
        self.assertEqual(([row["id"] for row in res.json()["items"]], res.json()["reel_size"]),
                         ([item.pk], 12))

    def test_settings_read_is_fenced_and_cached(self):
        self.store("24")
        with CaptureQueriesContext(connection) as cold:
            self.assertEqual(showcase.reel_size(), 24)
        sql = [query["sql"] for query in cold]
        # Чтение настроек — внутри savepoint: в PostgreSQL упавший запрос иначе
        # оставил бы транзакцию запроса сломанной до конца.
        self.assertEqual(len(sql), 3, sql)
        self.assertTrue(sql[0].startswith("SAVEPOINT") and sql[2].startswith("RELEASE"), sql)
        self.assertIn("adminapi_appsetting", sql[1])
        self.assertIn(REEL_KEY, sql[1])
        # Дальше полминуты значение отдаёт кэш настроек: за ним в таблицу не ходят.
        with CaptureQueriesContext(connection) as warm:
            self.assertEqual(showcase.reel_size(), 24)
            self.assertEqual(self.site(), 24)
        self.assertFalse([query["sql"] for query in warm if REEL_KEY in query["sql"]])

    def test_site_gets_it_beside_the_list_not_from_its_cache(self):
        item = self.item()
        self.assertEqual((self.ids(), self.site()), ([item.pk], 12))
        cached = cache.get(showcase.CACHE_KEY)
        set_runtime(REEL_KEY, 24)
        # Список по-прежнему из кэша на пять минут, а размер уже новый.
        self.assertEqual(self.site(), 24)
        self.assertEqual(cache.get(showcase.CACHE_KEY), cached)
        self.assertEqual(set(cached["items"][0]), PUBLIC_KEYS)

    def test_every_visitor_gets_it_in_every_mode(self):
        self.item()
        set_runtime(REEL_KEY, 36)
        for mode in views.MODES:
            for client in (self.guest, self.client_for(self.author), self.panel):
                with self.subTest(mode=mode), override_settings(VSTUDIO_MODE=mode):
                    res = client.get(PUBLIC)
                    self.assertEqual(res.status_code, 200, res.content)
                    self.assertEqual(set(res.json()), RESPONSE_KEYS)
                    self.assertEqual(res.json()["reel_size"], 36)
                    # Студия выключена — витрины нет, но ответ той же формы.
                    self.assertEqual(bool(res.json()["items"]), mode != "off")


class ReelSizePanelTests(ReelSizeCase):
    def patch(self, body, **extra):
        return self.panel.patch(PANEL, body, format="json", **extra)

    def panel_size(self) -> tuple:
        data = self.panel.get(PANEL).json()
        return data["reel_size"], data["reel_size_min"], data["reel_size_max"]

    def test_panel_shows_the_value_and_its_bounds(self):
        self.assertEqual(self.panel_size(), (12, 5, 48))
        self.store("1000")
        # Панель видит то же, что сайт: зажатое в границы значение.
        self.assertEqual(self.panel_size(), (48, 5, 48))

    def test_set(self):
        res = self.patch({"reel_size": 24}, HTTP_X_FORWARDED_FOR="203.0.113.7")
        self.assertEqual((res.status_code, res.json()), (200, {"reel_size": 24}))
        self.assertEqual((self.stored(), showcase.reel_size()), ("24", 24))
        self.assertEqual((self.panel_size(), self.site()), ((24, 5, 48), 24))

        log = self.reel_logs().get()
        self.assertEqual((log.actor, log.action, log.target_type, log.target_id, log.ip),
                         (self.staff, "settings.edit", "", "", "203.0.113.7"))
        self.assertEqual((log.before, log.after), ({REEL_KEY: 12}, {REEL_KEY: 24}))
        self.assertEqual(AdminActionLog.objects.count(), 1)

    def test_both_bounds_are_allowed(self):
        for size, before in ((5, 12), (48, 5)):
            with self.subTest(size=size):
                res = self.patch({"reel_size": size})
                self.assertEqual((res.status_code, res.json()), (200, {"reel_size": size}))
                self.assertEqual((showcase.reel_size(), self.site()), (size, size))
                log = self.reel_logs().last()
                self.assertEqual((log.before, log.after), ({REEL_KEY: before}, {REEL_KEY: size}))
        self.assertEqual(self.reel_logs().count(), 2)

    def test_only_a_real_integer_in_range(self):
        self.patch({"reel_size": 24})
        bodies = ({"reel_size": True}, {"reel_size": False}, {"reel_size": "24"},
                  {"reel_size": " 24"}, {"reel_size": 4}, {"reel_size": 49}, {"reel_size": 0},
                  {"reel_size": -12}, {"reel_size": 10 ** 9}, {"reel_size": 24.0},
                  {"reel_size": 12.5}, {"reel_size": None}, {"reel_size": [36]},
                  {"reel_size": {"value": 36}})
        for body in bodies:
            with self.subTest(body=body):
                res = self.patch(body)
                self.assertEqual(res.status_code, 400, res.content)
                self.assertEqual(res.json(), {"detail": REEL_RANGE})
        # Форма шлёт числа строками — строка числом не считается.
        res = self.panel.patch(PANEL, {"reel_size": "36"}, format="multipart")
        self.assertEqual((res.status_code, res.json()), (400, {"detail": REEL_RANGE}))
        self.assertEqual((self.stored(), showcase.reel_size(), self.reel_logs().count()),
                         ("24", 24, 1))

    def test_unknown_or_missing_fields_are_refused(self):
        item = self.item(title="Было")
        unknown = ({"reel_size": 24, "title": "Стало"}, {"reel_size": 24, "public_limit": 12},
                   {"size": 24}, {REEL_KEY: 24}, {"title": "Стало"}, {"reel_size_max": 96})
        for body in unknown:
            with self.subTest(body=body):
                res = self.patch(body)
                self.assertEqual(res.status_code, 400, res.content)
                self.assertEqual(set(res.json()), {"detail"})
                self.assertIn("reel_size", res.json()["detail"])
        for body in ({}, [24], 24, "24", None):
            with self.subTest(body=body):
                res = self.patch(body)
                self.assertEqual((res.status_code, res.json()), (400, {"detail": "Нечего менять"}))
        item.refresh_from_db()
        self.assertEqual((item.title, self.stored(), showcase.reel_size(),
                          AdminActionLog.objects.count()), ("Было", None, 12, 0))

    def test_same_value_writes_nothing(self):
        # Значение по умолчанию «поставить» тоже нечем: оно и так действует.
        res = self.patch({"reel_size": 12})
        self.assertEqual((res.status_code, res.json()), (200, {"reel_size": 12}))
        self.assertEqual((self.stored(), self.reel_logs().count()), (None, 0))

        self.patch({"reel_size": 24})
        stamp = AppSetting.objects.get(key=REEL_KEY).updated_at
        with self.captureOnCommitCallbacks() as callbacks:
            res = self.patch({"reel_size": 24})
        self.assertEqual((res.status_code, res.json()), (200, {"reel_size": 24}))
        self.assertEqual(callbacks, [])
        self.assertEqual((AppSetting.objects.get(key=REEL_KEY).updated_at,
                          self.reel_logs().count()), (stamp, 1))

    def test_no_log_no_change(self):
        with mock.patch("vstudio.showcase.log_admin_action", side_effect=RuntimeError("журнал")):
            with self.assertRaises(RuntimeError):
                self.patch({"reel_size": 24})
            self.assertEqual((self.stored(), showcase.reel_size()), (None, 12))
            self.store("36")
            with self.assertRaises(RuntimeError):
                self.patch({"reel_size": 24})
            self.assertEqual((self.stored(), showcase.reel_size()), ("36", 36))
            # То же без транзакции запроса вокруг: настройка и журнал — одно целое
            # и для того, кто зовёт правку не из вьюхи.
            with self.assertRaises(RuntimeError):
                showcase.set_reel_size({"reel_size": 24}, actor=self.staff)
        self.assertEqual((self.stored(), showcase.reel_size(), self.site()), ("36", 36, 36))
        self.assertEqual(AdminActionLog.objects.count(), 0)

    def test_stale_settings_cache_does_not_hide_a_real_change(self):
        self.store("24")
        # В кэше настроек осталось прежнее значение: по нему «12» сошло бы за повтор.
        cache.set(CACHE_PREFIX + REEL_KEY, "12", 30)
        res = self.patch({"reel_size": 12})
        self.assertEqual((res.status_code, res.json()), (200, {"reel_size": 12}))
        self.assertEqual((self.stored(), showcase.reel_size()), ("12", 12))
        log = self.reel_logs().get()
        self.assertEqual((log.before, log.after), ({REEL_KEY: 24}, {REEL_KEY: 12}))

    def test_settings_cache_is_dropped_again_after_commit(self):
        with self.captureOnCommitCallbacks() as callbacks:
            self.assertEqual(self.patch({"reel_size": 24}).status_code, 200)
        # Сосед прочитал базу до фиксации и положил в кэш прежнее значение.
        cache.set(CACHE_PREFIX + REEL_KEY, "12", 30)
        self.assertEqual(showcase.reel_size(), 12)
        self.assertTrue(callbacks)
        for callback in callbacks:
            callback()
        self.assertEqual((showcase.reel_size(), self.site()), (24, 24))

    def test_cache_failure_after_commit_is_not_an_error(self):
        with self.captureOnCommitCallbacks() as callbacks:
            self.assertEqual(self.patch({"reel_size": 24}).status_code, 200)
        with mock.patch.object(showcase.cache, "delete", side_effect=OSError("кэш недоступен")), \
                self.assertLogs("vstudio", level="WARNING"):
            for callback in callbacks:
                callback()
        self.assertEqual(showcase.reel_size(), 24)

    def test_garbage_in_the_table_can_be_fixed_from_the_panel(self):
        self.store("сорок")
        self.assertEqual(self.panel_size(), (12, 5, 48))
        res = self.patch({"reel_size": 18})
        self.assertEqual((res.status_code, self.stored(), showcase.reel_size()), (200, "18", 18))
        log = self.reel_logs().get()
        self.assertEqual((log.before, log.after), ({REEL_KEY: 12}, {REEL_KEY: 18}))

    def test_list_cache_and_items_are_untouched(self):
        item = self.item(title="Ночной город")
        self.assertEqual(self.ids(), [item.pk])
        cached = cache.get(showcase.CACHE_KEY)
        stamp = item.updated_at
        with self.captureOnCommitCallbacks(execute=True):
            self.assertEqual(self.patch({"reel_size": 5}).status_code, 200)
        # Размер — не часть списка: кэш работ ради него не пересобирается.
        self.assertEqual(cache.get(showcase.CACHE_KEY), cached)
        item.refresh_from_db()
        self.assertEqual((item.updated_at, self.logs().count()), (stamp, 0))


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
            "take": take.pk, "title": "Из админки", "placement": "reel", "category": "ad",
            "sort": 1, "is_active": "on"})
        self.assertEqual(res.status_code, 302)
        item = ShowcaseItem.objects.get()
        self.assertEqual((item.take, item.created_by, item.category), (take, self.admin_user, "ad"))

        other = self.work()
        res = self.client.post(reverse("admin:vstudio_showcaseitem_change", args=[item.pk]), {
            "take": other.pk, "title": "Переименовали", "placement": "reel", "category": "ad",
            "sort": 1})
        self.assertEqual(res.status_code, 302)
        item.refresh_from_db()
        self.assertEqual((item.take, item.title, item.is_active), (take, "Переименовали", False))

    def test_user_work_is_refused_here_too(self):
        res = self.client.post(reverse("admin:vstudio_showcaseitem_add"), {
            "take": self.work(self.author).pk, "title": "Чужая", "placement": "reel",
            "category": "ad", "sort": 1, "is_active": "on"})
        self.assertContains(res, "только работы сотрудников")
        self.assertFalse(ShowcaseItem.objects.exists())

    def test_form_offers_scenarios_and_refuses_old_sections(self):
        add = reverse("admin:vstudio_showcaseitem_add")
        page = self.client.get(add)
        for key, name in SCENARIO_NAMES.items():
            self.assertContains(page, f'<option value="{key}"', msg_prefix=name)
        self.assertNotContains(page, '<option value="social"')
        self.assertContains(page, "станет виден и этот кадр")

        res = self.client.post(add, {"take": self.work().pk, "placement": "reel",
                                     "category": "vertical", "sort": 0, "is_active": "on"})
        self.assertEqual(res.status_code, 302)
        item = ShowcaseItem.objects.get()
        self.assertEqual(item.category, "vertical")
        for key in ("social", "anime"):
            with self.subTest(key=key):
                res = self.client.post(
                    reverse("admin:vstudio_showcaseitem_change", args=[item.pk]),
                    {"title": "x", "placement": "reel", "category": key, "sort": 0})
                self.assertEqual(res.status_code, 200)   # форма с ошибкой, а не сохранение
                self.assertTrue(res.context["adminform"].form.errors["category"])
        item.refresh_from_db()
        self.assertEqual((item.category, item.title), ("vertical", ""))
        # Фильтр списка — по тем же сценариям.
        listed = self.client.get(reverse("admin:vstudio_showcaseitem_changelist"),
                                 {"category__exact": "vertical"})
        self.assertEqual(list(listed.context["cl"].result_list), [item])

    def test_change_page_shows_the_frame_that_would_go_public(self):
        frame, ref = f.make_asset(self.staff), f.make_asset(self.staff)
        from_frame = self.item(self.work(inputs=[(frame, FIRST)]))
        from_ref = self.item(self.work(inputs=[ref]))
        page = self.client.get(reverse("admin:vstudio_showcaseitem_change", args=[from_frame.pk]))
        self.assertContains(page, frame.thumb_url)
        page = self.client.get(reverse("admin:vstudio_showcaseitem_change", args=[from_ref.pk]))
        self.assertEqual(page.status_code, 200)
        self.assertNotContains(page, ref.thumb_url)

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


# ---------------------------------------------------------------- «Тренды»

TRENDS = "trends"
VIDEO_ONLY = "В «Тренды» ставятся только ролики"
BAD_PLACEMENT = "Куда: reel (карусель) или trends (тренды)"


class TrendsPublicTests(ShowcaseCase):
    def lists(self, client=None) -> tuple[list, list]:
        res = (client or self.guest).get(PUBLIC)
        self.assertEqual(res.status_code, 200, res.content)
        self.assertEqual(set(res.json()), RESPONSE_KEYS)
        data = res.json()
        return [row["id"] for row in data["items"]], [row["id"] for row in data["trends"]]

    def test_items_stay_the_reel_and_trends_go_beside_it(self):
        reel = self.item(title="Карусель", category="film")
        trend = self.item(title="Тренд", placement=TRENDS)
        self.assertEqual(self.lists(), ([reel.pk], [trend.pk]))
        data = self.guest.get(PUBLIC).json()
        # Карточка карусели — та же, что до «Трендов»: прежний фронт её не отличит.
        take = reel.take
        self.assertEqual(data["items"], [{
            "id": reel.pk, "title": "Карусель", "category": "film", "kind": "video",
            "model": {"id": f.VIDEO_MODEL_REF, "name": "Seedance 2.0"},
            "aspect_ratio": "16:9", "duration_s": 5, "width": 1280, "height": 720,
            "video_url": take.result_asset.url, "image_url": None,
            "poster_url": take.result_asset.thumb_url, "full_url": take.result_asset.url,
            "prompt": None, "params": None, "needs_photo": False, "start_frame_url": None,
        }])
        # У тренда та же карточка; места в ней нет — сайт знает его по списку.
        self.assertEqual(set(data["trends"][0]), PUBLIC_KEYS)
        self.assertEqual((data["trends"][0]["title"], data["trends"][0]["category"]),
                         ("Тренд", "other"))

    def test_same_privacy_rules(self):
        frame = f.make_asset(self.staff)
        take = self.work(inputs=[(frame, FIRST)])
        item = self.item(take, placement=TRENDS)
        card = self.guest.get(PUBLIC).json()["trends"][0]
        self.assertEqual((card["prompt"], card["params"], card["needs_photo"],
                          card["start_frame_url"]), (None, None, False, None))
        self.assertNotIn(frame.uid, json.dumps(card))
        ShowcaseItem.objects.filter(pk=item.pk).update(show_prompt=True)
        cache.clear()
        card = self.guest.get(PUBLIC).json()["trends"][0]
        self.assertEqual((card["prompt"], card["needs_photo"], card["start_frame_url"]),
                         ("Девушка идёт по крыше", True, frame.thumb_url))
        dump = json.dumps(card, ensure_ascii=False)
        for secret in (take.uid, take.shot.uid, self.staff.email):
            self.assertNotIn(secret, dump)

    def test_only_active_items_with_a_live_result(self):
        good = self.item(placement=TRENDS)
        self.item(placement=TRENDS, is_active=False)
        self.item(self.work(status="failed"), placement=TRENDS)
        self.item(self.work(asset=f.make_asset(self.staff, kind="video",
                                               deleted_at=timezone.now())), placement=TRENDS)
        self.assertEqual(self.lists(), ([], [good.pk]))

    def test_sort_then_newest_first_at_most_24(self):
        take = self.work()
        older = self.item(self.work(asset=take.result_asset), placement=TRENDS, sort=0)
        newer = self.item(self.work(asset=take.result_asset), placement=TRENDS, sort=0)
        first = self.item(self.work(asset=take.result_asset), placement=TRENDS, sort=-1)
        ShowcaseItem.objects.filter(pk=older.pk).update(created_at=timezone.now() - timedelta(days=1))
        self.assertEqual(self.lists()[1], [first.pk, newer.pk, older.pk])

        rest = [self.item(self.work(asset=take.result_asset), placement=TRENDS, sort=10 + n)
                for n in range(showcase.TRENDS_MAX)]
        cache.clear()
        self.assertEqual(showcase.TRENDS_MAX, 24)
        self.assertEqual(self.lists()[1],
                         [first.pk, newer.pk, older.pk] + [item.pk for item in rest[:21]])

    def test_each_place_has_its_own_limit(self):
        take = self.work()
        reel = [self.item(self.work(asset=take.result_asset), sort=n) for n in range(3)]
        trends = [self.item(self.work(asset=take.result_asset), placement=TRENDS, sort=n)
                  for n in range(3)]
        with mock.patch.object(showcase, "MAX_PUBLIC", 2), \
                mock.patch.object(showcase, "TRENDS_MAX", 2):
            # «Тренды» стоят выше по порядку, но мест карусели не занимают — и наоборот.
            self.assertEqual(self.lists(), ([reel[0].pk, reel[1].pk],
                                            [trends[0].pk, trends[1].pk]))

    def test_off_means_both_empty_staff_mode_shows_both(self):
        reel = self.item()
        trend = self.item(placement=TRENDS)
        with override_settings(VSTUDIO_MODE="off"):
            self.assertEqual(self.lists(), ([], []))
            self.assertEqual(self.lists(self.panel), ([], []))
        with override_settings(VSTUDIO_MODE="staff"):
            self.assertEqual(self.lists(self.client_for(self.author)), ([reel.pk], [trend.pk]))
        self.assertEqual(self.lists(), ([reel.pk], [trend.pk]))

    def test_moving_a_work_is_visible_right_after_commit(self):
        item = self.item()
        self.assertEqual(self.lists(), ([item.pk], []))
        with self.captureOnCommitCallbacks(execute=False) as callbacks:
            res = self.panel.patch(f"{PANEL}{item.pk}/", {"placement": TRENDS}, format="json")
        self.assertEqual(res.status_code, 200, res.content)
        self.assertEqual(self.lists(), ([item.pk], []))   # до фиксации — прежний кэш
        for callback in callbacks:
            callback()
        self.assertEqual(self.lists(), ([], [item.pk]))


class TrendsPanelTests(ShowcaseCase):
    def post(self, body):
        return self.panel.post(PANEL, body, format="json")

    def patch(self, item, body):
        return self.panel.patch(f"{PANEL}{item.pk}/", body, format="json")

    def refused(self, res, detail):
        self.assertEqual(res.status_code, 400, res.content)
        self.assertEqual(res.json(), {"detail": detail})

    def test_add_to_trends_without_a_scenario(self):
        take = self.work()
        res = self.post({"take": take.uid, "placement": TRENDS, "title": "Тренд"})
        self.assertEqual(res.status_code, 201, res.content)
        row = res.json()
        self.assertEqual(set(row), ITEM_KEYS)
        self.assertEqual((row["placement"], row["category"], row["state"]),
                         (TRENDS, "other", "live"))
        item = ShowcaseItem.objects.get()
        self.assertEqual(item.placement, TRENDS)
        log = self.logs().get()
        self.assertEqual(log.after["vstudio_showcase"]["placement"], TRENDS)

    def test_move_logs_the_place(self):
        item = self.item(title="Было")
        res = self.patch(item, {"placement": TRENDS})
        self.assertEqual((res.status_code, res.json()["placement"]), (200, TRENDS))
        log = self.logs().get()
        self.assertEqual((log.before, log.after), ({"vstudio_showcase": {"placement": "reel"}},
                                                   {"vstudio_showcase": {"placement": TRENDS}}))
        # Тот же ответ ещё раз — ни записи, ни строки в журнале.
        self.assertEqual(self.patch(item, {"placement": TRENDS}).status_code, 200)
        self.assertEqual(self.logs().count(), 1)
        res = self.patch(item, {"placement": "reel"})
        self.assertEqual((res.status_code, res.json()["placement"]), (200, "reel"))

    def test_unknown_place_is_refused(self):
        item = self.item()
        take = self.work()
        for value in ("Trends", "trend", "", None, 1, ["trends"], {"key": "trends"}):
            with self.subTest(value=value):
                self.refused(self.post({"take": take.uid, "placement": value}), BAD_PLACEMENT)
                self.refused(self.patch(item, {"placement": value}), BAD_PLACEMENT)
        item.refresh_from_db()
        self.assertEqual((item.placement, ShowcaseItem.objects.count(), self.logs().count()),
                         ("reel", 1, 0))

    def test_only_videos_go_to_trends(self):
        picture = self.work(kind="image")
        self.refused(self.post({"take": picture.uid, "placement": TRENDS}), VIDEO_ONLY)
        self.assertFalse(ShowcaseItem.objects.exists())
        # В карусель картинку поставить можно, как и раньше, — но не перенести в «Тренды».
        res = self.post({"take": picture.uid})
        self.assertEqual(res.status_code, 201, res.content)
        item = ShowcaseItem.objects.get()
        self.refused(self.patch(item, {"placement": TRENDS, "title": "Стало"}), VIDEO_ONLY)
        item.refresh_from_db()
        self.assertEqual((item.placement, item.title, self.logs().count()), ("reel", "", 1))

    def test_state_counts_each_place_in_its_own_limit(self):
        reel = self.item(sort=5)
        live = self.item(placement=TRENDS, sort=0)
        beyond = self.item(placement=TRENDS, sort=1)
        hidden = self.item(placement=TRENDS, is_active=False)
        with mock.patch.object(showcase, "TRENDS_MAX", 1):
            data = self.panel.get(PANEL).json()
        rows = {row["id"]: (row["placement"], row["state"]) for row in data["items"]}
        self.assertEqual(rows, {reel.pk: ("reel", "live"), live.pk: (TRENDS, "live"),
                                beyond.pk: (TRENDS, "over_limit"), hidden.pk: (TRENDS, "hidden")})


class TrendsDjangoAdminTests(ShowcaseCase):
    def setUp(self):
        super().setUp()
        self.client.force_login(f.make_user(is_staff=True, is_superuser=True))
        self.add_url = reverse("admin:vstudio_showcaseitem_add")

    def form(self, take, **kw):
        return {"take": take.pk, "title": "", "placement": TRENDS, "category": "other", "sort": 0,
                "is_active": "on", **kw}

    def test_column_and_filter(self):
        reel = self.item(title="Карусель")
        trend = self.item(title="Тренд", placement=TRENDS)
        changelist = reverse("admin:vstudio_showcaseitem_changelist")
        page = self.client.get(changelist)
        self.assertContains(page, "Куда")
        for value, expected in ((TRENDS, [trend]), ("reel", [reel])):
            with self.subTest(value=value):
                listed = self.client.get(changelist, {"placement__exact": value})
                self.assertEqual(list(listed.context["cl"].result_list), expected)
        page = self.client.get(reverse("admin:vstudio_showcaseitem_change", args=[trend.pk]))
        self.assertContains(page, '<option value="trends" selected')

    def test_add_to_trends_and_pictures_are_refused(self):
        res = self.client.post(self.add_url, self.form(self.work()))
        self.assertEqual(res.status_code, 302)
        self.assertEqual(ShowcaseItem.objects.get().placement, TRENDS)

        res = self.client.post(self.add_url, self.form(self.work(kind="image")))
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.context["adminform"].form.errors["placement"], [VIDEO_ONLY + "."])
        self.assertEqual(ShowcaseItem.objects.count(), 1)

        picture = self.item(self.work(kind="image"))
        change = reverse("admin:vstudio_showcaseitem_change", args=[picture.pk])
        res = self.client.post(change, {"title": "", "placement": TRENDS, "category": "other",
                                        "sort": 0, "is_active": "on"})
        self.assertEqual(res.status_code, 200)
        self.assertTrue(res.context["adminform"].form.errors["placement"])
        picture.refresh_from_db()
        self.assertEqual(picture.placement, "reel")


class PlacementMigrationTests(ShowcaseCase):
    def test_wired_into_the_migration(self):
        module = importlib.import_module("vstudio.migrations.0005_showcaseitem_placement")
        migration = module.Migration
        self.assertEqual(migration.dependencies, [("vstudio", "0004_showcase_scenarios")])
        (add,) = migration.operations
        self.assertIsInstance(add, migrations.AddField)
        self.assertEqual((add.model_name, add.name), ("showcaseitem", "placement"))
        # Прежние строки встают в карусель: так они и стояли.
        self.assertEqual((add.field.default, add.field.max_length, add.field.verbose_name),
                         ("reel", 8, "Куда"))
        self.assertEqual(add.field.choices, ShowcaseItem.PLACEMENT_CHOICES)
        self.assertEqual(showcase.PLACEMENTS, ("reel", "trends"))
        self.assertEqual(ShowcaseItem().placement, "reel")
