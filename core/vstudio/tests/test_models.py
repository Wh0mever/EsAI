"""Модели видеостудии: ограничения БД, каскады, условные переходы, фабрики.

Деньги держат не помощники, а сама схема: CheckConstraint не даёт закрыть
дубль с резервом, уникальный client_request_id — дважды запустить один клик.
Эти тесты проверяют, что схема действительно так себя ведёт.
"""
import re
from datetime import timedelta

from django.core.files.storage import default_storage
from django.db import IntegrityError, transaction
from django.db.models import RestrictedError
from django.test import TestCase
from django.utils import timezone

from ai.models import GenerationLog

from ..models import CHARGE_RELEASED, TAKE_CLOSED, TAKE_OPEN, Asset, Project, Shot, ShotInput, Take
from . import factories as f

UID_RE = re.compile(r"^[0-9a-f]{32}$")


class SchemaTests(TestCase):
    def test_uids_are_hex_and_unique(self):
        user = f.make_user()
        a, b = f.make_asset(user), f.make_asset(user)
        take = f.make_take(f.make_shot(user, inputs=[a]))
        for uid in (a.uid, b.uid, take.uid, take.shot.uid, take.project.uid):
            self.assertRegex(uid, UID_RE)
        self.assertNotEqual(a.uid, b.uid)

    def test_choice_values_fit_their_columns(self):
        # Значение длиннее колонки на Postgres — ошибка вставки в проде.
        for model in (Project, Asset, Shot, ShotInput, Take):
            for field in model._meta.concrete_fields:
                for value, _label in field.choices or ():
                    self.assertLessEqual(len(value), field.max_length,
                                         f"{model.__name__}.{field.name}={value}")

    def test_named_indexes_and_constraints(self):
        # Имена из спецификации: на них ссылаются миграции и разбор инцидентов.
        def names(model):
            return {i.name for i in model._meta.indexes} | {c.name for c in model._meta.constraints}

        self.assertEqual(names(Project), {"vs_proj_user_act"})
        self.assertEqual(names(Asset), {"vs_asset_lib", "vs_asset_dedup"})
        self.assertEqual(names(Shot), {"vs_shot_proj"})
        self.assertEqual(names(ShotInput), {"vs_input_pos", "vs_input_once"})
        self.assertEqual(names(Take), {"vs_take_idem", "vs_take_open_reserved", "vs_take_poll",
                                       "vs_take_user_res", "vs_take_shot"})

    def test_open_closed_sets(self):
        self.assertEqual(Take.OPEN, ("queued", "submitting", "running", "saving"))
        self.assertEqual(set(Take.OPEN) | set(Take.CLOSED),
                         {v for v, _ in Take.STATUS_CHOICES})
        self.assertFalse(set(TAKE_OPEN) & set(TAKE_CLOSED))


class TakeMoneyConstraintTests(TestCase):
    """CheckConstraint vs_take_open_reserved: открытый ⇔ reserved."""

    def setUp(self):
        self.shot = f.make_shot()

    def _bad(self, **kw):
        with self.assertRaises(IntegrityError), transaction.atomic():
            f.make_take(self.shot, **kw)

    def test_valid_combinations(self):
        for status in TAKE_OPEN:
            self.assertEqual(f.make_take(self.shot, status=status).charge_state, "reserved")
        self.assertEqual(f.make_take(self.shot, status="done").charge_state, "charged")
        self.assertEqual(f.make_take(self.shot, status="failed").charge_state, "released")
        # Довоз из lost: done, но деньги так и остались снятыми.
        f.make_take(self.shot, status="done", charge_state="released")

    def test_closed_take_cannot_hold_reserve(self):
        for status in TAKE_CLOSED:
            self._bad(status=status, charge_state="reserved")

    def test_open_take_must_hold_reserve(self):
        self._bad(status="queued", charge_state="charged")
        self._bad(status="running", charge_state="released")

    def test_update_that_forgets_release_fails(self):
        take = f.make_take(self.shot, status="running")
        with self.assertRaises(IntegrityError), transaction.atomic():
            Take.objects.filter(pk=take.pk).update(status="failed")
        take.refresh_from_db()
        self.assertEqual((take.status, take.charge_state), ("running", "reserved"))


class IdempotencyTests(TestCase):
    def test_same_click_twice_is_rejected(self):
        shot = f.make_shot()
        f.make_take(shot, client_request_id="click-1")
        with self.assertRaises(IntegrityError), transaction.atomic():
            f.make_take(shot, client_request_id="click-1")

    def test_empty_id_and_other_users_are_free(self):
        shot = f.make_shot()
        f.make_take(shot)
        f.make_take(shot)  # пустой client_request_id не участвует в уникальности
        f.make_take(shot, client_request_id="click-1")
        f.make_take(f.make_shot(), client_request_id="click-1")  # другой человек
        self.assertEqual(Take.objects.count(), 4)


class ShotInputConstraintTests(TestCase):
    def setUp(self):
        self.user = f.make_user()
        self.a, self.b = f.make_asset(self.user), f.make_asset(self.user)
        self.shot = f.make_shot(self.user)

    def test_position_unique_within_slot(self):
        ShotInput.objects.create(shot=self.shot, asset=self.a, slot="reference", position=0)
        with self.assertRaises(IntegrityError), transaction.atomic():
            ShotInput.objects.create(shot=self.shot, asset=self.b, slot="reference", position=0)
        # Та же позиция в другом слоте — можно.
        ShotInput.objects.create(shot=self.shot, asset=self.b, slot="first_frame", position=0)

    def test_asset_once_per_slot(self):
        ShotInput.objects.create(shot=self.shot, asset=self.a, slot="reference", position=0)
        with self.assertRaises(IntegrityError), transaction.atomic():
            ShotInput.objects.create(shot=self.shot, asset=self.a, slot="reference", position=1)
        # Одно фото и референсом, и первым кадром — это решает компилятор, не схема.
        ShotInput.objects.create(shot=self.shot, asset=self.a, slot="first_frame", position=0)


class DeletionTests(TestCase):
    def setUp(self):
        self.user = f.make_user()
        self.asset = f.make_asset(self.user)
        self.shot = f.make_shot(self.user, inputs=[self.asset])
        self.take = f.make_take(self.shot, status="done", genlog=True)
        self.result = f.make_asset(self.user, kind="video", source="generated_video",
                                   origin_take=self.take, project=self.shot.project)
        Take.objects.filter(pk=self.take.pk).update(result_asset=self.result)

    def test_referenced_asset_cannot_be_hard_deleted(self):
        with self.assertRaises(RestrictedError):
            self.asset.delete()

    def test_whole_user_can_be_deleted(self):
        # С PROTECT удаление аккаунта падало бы: ассеты уходят каскадом от
        # пользователя, а ссылающиеся на них ShotInput — от его же запросов.
        log_id = self.take.genlog_id
        self.user.delete()
        for model in (Project, Asset, Shot, ShotInput, Take):
            self.assertFalse(model.objects.exists(), model.__name__)
        # Журнал — аудит: запись остаётся без пользователя.
        self.assertTrue(GenerationLog.objects.filter(pk=log_id, user__isnull=True).exists())

    def test_project_delete_keeps_library(self):
        self.shot.project.delete()
        self.assertFalse(Shot.objects.exists())
        self.assertFalse(Take.objects.exists())
        self.result.refresh_from_db()
        self.assertIsNone(self.result.project_id)
        self.assertIsNone(self.result.origin_take_id)

    def test_genlog_delete_unlinks_take(self):
        self.assertEqual(GenerationLog.objects.get(pk=self.take.genlog_id).vstudio_take, self.take)
        GenerationLog.objects.filter(pk=self.take.genlog_id).delete()
        self.take.refresh_from_db()
        self.assertIsNone(self.take.genlog_id)


class TransitionTests(TestCase):
    """Take.objects.transition — условный UPDATE §2.2."""

    def setUp(self):
        self.take = f.make_take(status="queued")
        old = timezone.now() - timedelta(minutes=20)
        Take.objects.filter(pk=self.take.pk).update(updated_at=old)

    def test_wins_once(self):
        self.assertTrue(Take.objects.transition(self.take.pk, "queued", "submitting"))
        self.assertFalse(Take.objects.transition(self.take.pk, "queued", "submitting"))
        self.take.refresh_from_db()
        self.assertEqual(self.take.status, "submitting")
        # update() не трогает auto_now, а sweep судит о зависших по updated_at.
        self.assertGreater(self.take.updated_at, timezone.now() - timedelta(minutes=1))
        self.assertIsNone(self.take.finished_at)

    def test_failure_releases_reserve_in_same_update(self):
        Take.objects.transition(self.take.pk, "queued", "submitting")
        self.assertTrue(Take.objects.transition(self.take.pk, ("submitting",), "failed",
                                                error_code="bad_request"))
        self.take.refresh_from_db()
        self.assertEqual((self.take.status, self.take.charge_state, self.take.error_code),
                         ("failed", CHARGE_RELEASED, "bad_request"))
        self.assertIsNotNone(self.take.finished_at)

    def test_cancel_and_lost_release_too(self):
        self.assertTrue(Take.objects.transition(self.take.pk, "queued", "canceled"))
        self.assertEqual(Take.objects.get(pk=self.take.pk).charge_state, "released")
        other = f.make_take(status="saving")
        self.assertTrue(Take.objects.transition(other.pk, "saving", "lost"))
        self.assertEqual(Take.objects.get(pk=other.pk).charge_state, "released")

    def test_done_requires_explicit_charge(self):
        take = f.make_take(status="saving")
        with self.assertRaises(IntegrityError), transaction.atomic():
            Take.objects.transition(take.pk, "saving", "done")
        ok = (Take.objects.filter(charge_state="reserved")
              .transition(take.pk, "saving", "done", charge_state="charged", credits_charged=150))
        self.assertTrue(ok)
        # Второй финализатор проигрывает: уже не saving и не reserved.
        self.assertFalse(Take.objects.filter(charge_state="reserved")
                         .transition(take.pk, "saving", "done", charge_state="charged"))

    def test_chained_condition_and_field_only_update(self):
        take = f.make_take(status="running", next_poll_at=timezone.now() + timedelta(seconds=60))
        now = timezone.now()
        # Не пора — ноль строк, цепочка гаснет.
        self.assertFalse(Take.objects.filter(next_poll_at__lte=now)
                         .transition(take.pk, "running", next_poll_at=now + timedelta(seconds=90)))
        Take.objects.filter(pk=take.pk).update(next_poll_at=now - timedelta(seconds=1))
        self.assertTrue(Take.objects.filter(next_poll_at__lte=now)
                        .transition(take.pk, "running", next_poll_at=now + timedelta(seconds=90)))
        take.refresh_from_db()
        self.assertEqual(take.status, "running")

    def test_querysets(self):
        f.make_take(self.take.shot, status="done")
        self.assertEqual(set(Take.objects.open().values_list("pk", flat=True)), {self.take.pk})
        self.assertEqual(Take.objects.reserved().count(), 1)
        self.assertTrue(self.take.is_open)


class AssetAndProjectTests(TestCase):
    def test_urls_and_scopes(self):
        user, other = f.make_user(), f.make_user()
        asset = f.make_asset(user)
        self.assertEqual(asset.url, default_storage.url(asset.file))
        self.assertTrue(asset.thumb_url.endswith(f"{asset.uid}_t.jpg"))
        pending = f.make_asset(user, status="pending")
        self.assertEqual((pending.url, pending.thumb_url), ("", ""))
        gone = f.make_asset(user, deleted_at=timezone.now())
        self.assertTrue(gone.is_deleted)
        self.assertEqual(set(Asset.objects.owned_by(user).alive()), {asset, pending})
        self.assertFalse(Asset.objects.owned_by(other).exists())

    def test_touch_moves_project_without_save(self):
        project = f.make_project(title="Крыша")
        at = timezone.now() + timedelta(hours=1)
        Project.objects.filter(pk=project.pk).update(title="Переименован")
        Project.touch(project.pk, at)
        project.refresh_from_db()
        self.assertEqual((project.title, project.last_activity_at), ("Переименован", at))


class FactoryTests(TestCase):
    def test_shot_numbers_refs_by_tray_order(self):
        user = f.make_user()
        a, b, c = f.make_asset(user), f.make_asset(user), f.make_asset(user)
        shot = f.make_shot(user, inputs=[a, {"asset": b, "included": False}, c,
                                         (f.make_asset(user), "first_frame")])
        self.assertEqual(shot.prompt_text,
                         "Девушка идёт по крыше @Image 1 @Image — @Image 2")
        self.assertEqual(list(shot.inputs.filter(slot="reference").order_by("position")
                              .values_list("position", flat=True)), [0, 1, 2])
        self.assertEqual(shot.inputs.get(slot="first_frame").position, 0)

    def test_prompt_doc_is_valid_for_compiler(self):
        from ..prompt_doc import validate

        user = f.make_user()
        a = f.make_asset(user)
        doc = f.prompt_doc("Героиня ", a, " на кухне", ["Камера отъезжает"])
        self.assertEqual(validate(doc), doc)
        self.assertEqual(len(doc["blocks"]), 2)
        self.assertEqual(validate(f.make_shot(user, inputs=[a]).prompt_doc)["v"], 1)

    def test_take_modes_and_genlog(self):
        user = f.make_user()
        frame = f.make_asset(user)
        self.assertEqual(f.make_take(f.make_shot(user)).mode, "t2v")
        self.assertEqual(f.make_take(f.make_shot(user, inputs=[(frame, "first_frame")])).mode, "i2v")
        self.assertEqual(f.make_take(f.make_shot(user, inputs=[frame])).mode, "r2v")
        image = f.make_take(f.make_shot(user, kind="image"))
        self.assertEqual((image.mode, image.model_ref), ("t2i", f.IMAGE_MODEL_REF))

        lost = f.make_take(f.make_shot(user), status="lost", genlog=True)
        log = GenerationLog.objects.get(pk=lost.genlog_id)
        self.assertEqual((log.source, log.params["take"], log.status, log.needs_review),
                         ("vstudio", lost.uid, "lost", True))

    def test_store_writes_real_image(self):
        with f.media_root():
            asset = f.make_asset(store=True, width=320, height=200)
            self.assertTrue(default_storage.exists(asset.file))
            self.assertGreater(asset.bytes, 0)
            from PIL import Image
            with default_storage.open(asset.file) as fh:
                self.assertEqual(Image.open(fh).size, (320, 200))
