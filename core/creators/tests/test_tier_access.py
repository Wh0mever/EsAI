"""Активный креатор пользуется платными моделями без покупки пакета.

Решение принимается в одном месте — plans.tiers.user_tier. Поле User.is_paid
при этом не меняется: на него смотрят ежедневный бонус и промокоды.
"""
from types import SimpleNamespace
from unittest import mock

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.models import AnonymousUser
from django.db import OperationalError, connection
from django.test import override_settings
from django.test.utils import CaptureQueriesContext

from plans import tiers
from plans.tiers import can_use_model, daily_request_limit, is_paid_tier, user_tier

from .. import access, flags
from ..models import Creator
from . import factories as f

PREMIUM = SimpleNamespace(free_tier=False, markup_coefficient=15)
FREE = SimpleNamespace(free_tier=True, markup_coefficient=1)


def _fresh(user):
    """Новый объект пользователя — как в следующем запросе (без запомненного ответа)."""
    return get_user_model().objects.get(pk=user.pk)


def _data_queries(ctx) -> list:
    return [q["sql"] for q in ctx.captured_queries if "SAVEPOINT" not in q["sql"].upper()]


def _db_blinks_on(table):
    def wrapper(execute, sql, params, many, context):
        if table in sql:
            raise OperationalError("db blinked")
        return execute(sql, params, many, context)
    return wrapper


class TierAccessTests(f.CreatorsTestCase):
    def setUp(self):
        super().setUp()
        # Режим программы читается из настроек админки с кэшем на 30 секунд:
        # первый запрос за ним — не тот, который здесь считаем.
        flags.mode()

    def test_active_creator_who_never_paid_is_paid_tier(self):
        user = f.make_creator().user
        self.assertFalse(user.is_paid)
        self.assertEqual(user_tier(user), "paid")
        self.assertTrue(is_paid_tier(user))
        self.assertTrue(can_use_model(user, PREMIUM))
        self.assertEqual(daily_request_limit(user), int(settings.PAID_DAILY_REQUESTS))
        self.assertNotEqual(daily_request_limit(user), int(settings.FREE_DAILY_REQUESTS))

    def test_is_paid_field_is_not_touched(self):
        user = f.make_creator().user
        user_tier(user)
        user.refresh_from_db()
        self.assertFalse(user.is_paid)
        self.assertIsNone(user.first_paid_at)

    def test_blocked_creator_is_free(self):
        user = f.make_creator(status="blocked").user
        self.assertEqual(user_tier(user), "free")
        self.assertFalse(can_use_model(user, PREMIUM))
        self.assertTrue(can_use_model(user, FREE))
        self.assertEqual(daily_request_limit(user), int(settings.FREE_DAILY_REQUESTS))

    def test_block_takes_the_access_away_on_the_next_request(self):
        creator = f.make_creator()
        self.assertEqual(user_tier(_fresh(creator.user)), "paid")
        Creator.objects.filter(pk=creator.pk).update(status="blocked")
        self.assertEqual(user_tier(_fresh(creator.user)), "free")
        Creator.objects.filter(pk=creator.pk).update(status="active")
        self.assertEqual(user_tier(_fresh(creator.user)), "paid")

    def test_ordinary_user_is_free(self):
        user = f.make_user()
        self.assertEqual(user_tier(user), "free")
        self.assertFalse(can_use_model(user, PREMIUM))
        self.assertFalse(access.has_paid_access(_fresh(user)))

    def test_guest_is_unaffected(self):
        with self.assertNumQueries(0):
            self.assertEqual(user_tier(AnonymousUser()), "guest")
            self.assertEqual(user_tier(None), "guest")
            self.assertFalse(access.has_paid_access(None))
            self.assertFalse(access.has_paid_access(AnonymousUser()))
        self.assertFalse(can_use_model(AnonymousUser(), PREMIUM))

    def test_paying_user_never_reaches_the_creators_check(self):
        user = f.make_user(paid=True)
        with mock.patch("creators.access.has_paid_access") as check, self.assertNumQueries(0):
            self.assertEqual(user_tier(user), "paid")
        check.assert_not_called()

    def test_mode_off_gives_no_access(self):
        creator = f.make_creator(f.make_user(staff=True))
        with override_settings(CREATORS_MODE="off"):
            user = _fresh(creator.user)
            with self.assertNumQueries(0):
                self.assertFalse(access.has_paid_access(user))
            self.assertEqual(user_tier(user), "free")
            # Купивший пакет остаётся paid и при выключенной программе.
            self.assertEqual(user_tier(f.make_user(paid=True)), "paid")
        self.assertEqual(user_tier(_fresh(creator.user)), "paid")

    def test_mode_staff_only_staff_creators(self):
        staff = f.make_creator(f.make_user(staff=True)).user
        boss = f.make_creator(f.make_user(superuser=True)).user
        plain = f.make_creator().user
        with override_settings(CREATORS_MODE="staff"):
            self.assertEqual(user_tier(_fresh(staff)), "paid")
            self.assertEqual(user_tier(_fresh(boss)), "paid")
            fresh = _fresh(plain)
            # Не сотрудник в режиме staff: ответ ясен без обращения к базе.
            with self.assertNumQueries(0):
                self.assertEqual(user_tier(fresh), "free")
            # Сотрудник, который не креатор, доступа не получает.
            self.assertEqual(user_tier(f.make_user(staff=True)), "free")
            self.assertEqual(user_tier(_fresh(f.make_creator(
                f.make_user(staff=True), status="blocked").user)), "free")

    def test_answer_is_remembered_on_the_user_object(self):
        user = _fresh(f.make_creator().user)
        with CaptureQueriesContext(connection) as ctx:
            self.assertTrue(access.has_paid_access(user))
        self.assertEqual(len(_data_queries(ctx)), 1)
        self.assertIs(user._creators_paid_access, True)
        with self.assertNumQueries(0):
            # Каталог моделей спрашивает тир на каждую модель.
            for _ in range(20):
                self.assertTrue(can_use_model(user, PREMIUM))

        plain = _fresh(f.make_user())
        self.assertFalse(access.has_paid_access(plain))
        self.assertIs(plain._creators_paid_access, False)
        with self.assertNumQueries(0):
            self.assertEqual(user_tier(plain), "free")

    def test_failing_creators_import_means_free(self):
        user = _fresh(f.make_creator().user)
        with mock.patch.dict("sys.modules", {"creators.access": None}):
            self.assertFalse(tiers._creator_access(user))
            self.assertEqual(user_tier(user), "free")
            self.assertFalse(can_use_model(user, PREMIUM))
        self.assertEqual(user_tier(user), "paid")

    def test_has_paid_access_never_raises(self):
        user = _fresh(f.make_creator().user)
        with mock.patch("creators.access.flags.mode", side_effect=RuntimeError("boom")), \
                self.assertLogs("creators", level="ERROR"):
            self.assertFalse(access.has_paid_access(user))
        # Сбой не запоминается: следующий вызов считает заново.
        self.assertTrue(access.has_paid_access(user))

    def test_db_failure_keeps_the_callers_transaction_alive(self):
        user = _fresh(f.make_creator().user)
        with connection.execute_wrapper(_db_blinks_on("creators_creator")), \
                self.assertLogs("creators", level="ERROR"):
            self.assertEqual(user_tier(user), "free")
        # Точка сохранения: запрос чата после сбоя продолжает работать.
        self.assertEqual(get_user_model().objects.filter(pk=user.pk).count(), 1)
        self.assertEqual(user_tier(user), "paid")

    def test_raising_check_inside_tiers_is_swallowed(self):
        user = f.make_user()
        with mock.patch("creators.access.has_paid_access", side_effect=RuntimeError("boom")):
            self.assertEqual(user_tier(user), "free")
