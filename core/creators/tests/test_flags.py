"""Рубильник программы: режим off/staff/on, кому она видна, холд и приём выводов.

Режим читается из настроек окружения, а поверх — из админки (runtime-ключ),
поэтому каждое правило проверяется с обоих источников.
"""
from decimal import Decimal

from django.conf import settings
from django.contrib.auth.models import AnonymousUser
from django.test import RequestFactory, override_settings

from adminapi.permissions import IsStaff, IsSuperuser
from adminapi.runtime import KEYS, delete_runtime, set_runtime

from .. import flags
from . import factories as f


class ModeTests(f.CreatorsTestCase):
    def test_base_class_turns_the_program_on(self):
        self.assertEqual(flags.mode(), "on")
        self.assertFalse(flags.is_off())
        self.assertTrue(flags.accrual_enabled())

    def test_mode_from_settings(self):
        for value, expected in (("off", "off"), ("staff", "staff"), ("on", "on"),
                                (" ON ", "on"), ("Staff", "staff")):
            with override_settings(CREATORS_MODE=value):
                self.assertEqual(flags.mode(), expected, value)

    def test_unknown_value_means_off(self):
        for value in ("", "yes", "1", "enabled", None):
            with override_settings(CREATORS_MODE=value):
                self.assertEqual(flags.mode(), "off", value)
                self.assertTrue(flags.is_off())
                self.assertFalse(flags.accrual_enabled())

    def test_runtime_key_wins_over_settings(self):
        set_runtime("creators_mode", "off")
        self.assertEqual(flags.mode(), "off")
        set_runtime("creators_mode", "staff")
        self.assertEqual(flags.mode(), "staff")
        self.assertTrue(flags.accrual_enabled())
        # Мусор в админке выключает программу, а не открывает её.
        set_runtime("creators_mode", "everyone")
        self.assertEqual(flags.mode(), "off")
        delete_runtime("creators_mode")
        self.assertEqual(flags.mode(), "on")

    def test_missing_setting_means_staff(self):
        # Настройки нет вовсе (старый .env без CREATORS_MODE) — программу видят
        # только сотрудники, а не все.
        with override_settings():
            del settings.CREATORS_MODE
            self.assertEqual(flags.mode(), "staff")

    def test_runtime_failure_falls_back_to_settings(self):
        from unittest import mock

        with mock.patch("adminapi.runtime.get_runtime", side_effect=RuntimeError("db down")):
            self.assertEqual(flags.mode(), "on")
            self.assertEqual(flags.hold_days(), 14)
            self.assertTrue(flags.payouts_enabled())

    def test_constants(self):
        self.assertEqual(flags.MODES, ("off", "staff", "on"))
        self.assertEqual((flags.MODE_OFF, flags.MODE_STAFF, flags.MODE_ON), ("off", "staff", "on"))
        self.assertEqual(flags.MIN_PAYOUT_USDT, Decimal("10"))
        self.assertIsInstance(flags.MIN_PAYOUT_USDT, Decimal)
        self.assertEqual(flags.BIND_WINDOW_HOURS, 72)
        self.assertEqual(flags.LINK_WINDOW_MINUTES, 10)


class EnabledForTests(f.CreatorsTestCase):
    def setUp(self):
        super().setUp()
        self.user = f.make_user()
        self.staff = f.make_user(staff=True)
        self.boss = f.make_user(superuser=True)

    def test_on_everyone_including_anonymous(self):
        for who in (None, AnonymousUser(), self.user, self.staff, self.boss):
            self.assertTrue(flags.enabled_for(who), who)

    @override_settings(CREATORS_MODE="staff")
    def test_staff_only_staff_and_superusers(self):
        self.assertFalse(flags.enabled_for(None))
        self.assertFalse(flags.enabled_for(AnonymousUser()))
        self.assertFalse(flags.enabled_for(self.user))
        self.assertTrue(flags.enabled_for(self.staff))
        self.assertTrue(flags.enabled_for(self.boss))

    @override_settings(CREATORS_MODE="off")
    def test_off_nobody(self):
        for who in (None, AnonymousUser(), self.user, self.staff, self.boss):
            self.assertFalse(flags.enabled_for(who), who)


class CreatorUsableTests(f.CreatorsTestCase):
    def setUp(self):
        super().setUp()
        self.ordinary = f.make_creator()
        self.staff = f.make_creator(f.make_user(staff=True))
        self.blocked = f.make_creator(f.make_user(staff=True), status="blocked")

    def test_on_any_active_creator(self):
        self.assertTrue(flags.creator_usable(self.ordinary))
        self.assertTrue(flags.creator_usable(self.staff))
        self.assertFalse(flags.creator_usable(self.blocked))
        self.assertFalse(flags.creator_usable(None))

    def test_creator_on_a_deactivated_account_is_not_usable(self):
        # Аккаунт отключён (администратором, /delete в боте): в кабинет войти
        # некому — код не должен дальше привязывать людей.
        for creator in (self.ordinary, self.staff):
            creator.user.is_active = False
            creator.user.save(update_fields=["is_active"])
            self.assertFalse(flags.creator_usable(creator))
        with override_settings(CREATORS_MODE="staff"):
            self.assertFalse(flags.creator_usable(self.staff))

    @override_settings(CREATORS_MODE="staff")
    def test_staff_mode_only_staff_creators(self):
        self.assertFalse(flags.creator_usable(self.ordinary))
        self.assertTrue(flags.creator_usable(self.staff))
        self.assertTrue(flags.creator_usable(f.make_creator(f.make_user(superuser=True))))
        self.assertFalse(flags.creator_usable(self.blocked))

    @override_settings(CREATORS_MODE="off")
    def test_off_nobody(self):
        for creator in (self.ordinary, self.staff, self.blocked):
            self.assertFalse(flags.creator_usable(creator))


class HoldAndPayoutTests(f.CreatorsTestCase):
    def test_hold_days_default(self):
        self.assertEqual(flags.hold_days(), 14)

    def test_hold_days_from_settings_and_runtime(self):
        with override_settings(CREATORS_HOLD_DAYS=7):
            self.assertEqual(flags.hold_days(), 7)
            set_runtime("creators_hold_days", 30)
            self.assertEqual(flags.hold_days(), 30)
            delete_runtime("creators_hold_days")
            self.assertEqual(flags.hold_days(), 7)

    def test_hold_days_is_clamped(self):
        for raw, expected in ((-5, 0), (0, 0), (1, 1), (90, 90), (91, 90), (10000, 90)):
            set_runtime("creators_hold_days", raw)
            self.assertEqual(flags.hold_days(), expected, raw)
        with override_settings(CREATORS_HOLD_DAYS=365):
            delete_runtime("creators_hold_days")
            self.assertEqual(flags.hold_days(), 90)
        with override_settings(CREATORS_HOLD_DAYS=-1):
            self.assertEqual(flags.hold_days(), 0)

    def test_hold_days_garbage_falls_back(self):
        set_runtime("creators_hold_days", "две недели")
        self.assertEqual(flags.hold_days(), 14)
        delete_runtime("creators_hold_days")
        with override_settings(CREATORS_HOLD_DAYS="oops"):
            self.assertEqual(flags.hold_days(), 14)

    def test_payouts_enabled(self):
        self.assertTrue(flags.payouts_enabled())
        with override_settings(CREATORS_PAYOUTS_ENABLED=False):
            self.assertFalse(flags.payouts_enabled())
            set_runtime("creators_payouts_enabled", True)
            self.assertTrue(flags.payouts_enabled())
            delete_runtime("creators_payouts_enabled")
            self.assertFalse(flags.payouts_enabled())
        set_runtime("creators_payouts_enabled", False)
        self.assertFalse(flags.payouts_enabled())
        # Приём выводов — отдельный рубильник: режим программы он не меняет.
        self.assertEqual(flags.mode(), "on")


class SettingsWiringTests(f.CreatorsTestCase):
    def test_runtime_keys_registered(self):
        for key in ("creators_mode", "creators_hold_days", "creators_payouts_enabled"):
            self.assertIn(key, KEYS)

    def test_settings_declared(self):
        self.assertIn("creators.apps.CreatorsConfig", settings.INSTALLED_APPS)
        self.assertEqual(settings.INSTALLED_APPS[-1], "creators.apps.CreatorsConfig")
        self.assertEqual(settings.CREATORS_HOLD_DAYS, 14)
        self.assertIs(settings.CREATORS_PAYOUTS_ENABLED, True)
        self.assertTrue(settings.CREATORS_LINK_BASE.startswith("http"))

    def test_throttle_scopes_declared(self):
        rates = settings.REST_FRAMEWORK["DEFAULT_THROTTLE_RATES"]
        self.assertEqual(rates["creators_click"], "30/min")
        self.assertEqual(rates["creators_apply"], "5/day")
        self.assertEqual(rates["creators_write"], "30/min")

    def test_beat_schedule_declared(self):
        schedule = settings.CELERY_BEAT_SCHEDULE
        expected = {
            "creators:commission_safety_net": "creators.tasks.commission_safety_net",
            "creators:backfill_commissions": "creators.tasks.backfill_commissions",
            "creators:poll_yookassa_refunds": "creators.tasks.poll_yookassa_refunds",
            "creators:poll_freedompay_refunds": "creators.tasks.poll_freedompay_refunds",
            "creators:nightly_check": "creators.tasks.nightly_check",
        }
        for name, task in expected.items():
            self.assertEqual(schedule[name]["task"], task)
        # Задачи находит autodiscover_tasks по INSTALLED_APPS — список импортов прежний.
        self.assertNotIn("creators.tasks", settings.CELERY_IMPORTS)


class IsSuperuserPermissionTests(f.CreatorsTestCase):
    def _allowed(self, permission, user):
        request = RequestFactory().get("/")
        request.user = user
        return permission().has_permission(request, None)

    def test_only_staff_superuser_passes(self):
        user, staff, boss = f.make_user(), f.make_user(staff=True), f.make_user(superuser=True)
        self.assertFalse(self._allowed(IsSuperuser, AnonymousUser()))
        self.assertFalse(self._allowed(IsSuperuser, user))
        self.assertFalse(self._allowed(IsSuperuser, staff))
        self.assertTrue(self._allowed(IsSuperuser, boss))
        # Суперпользователь без is_staff в админ-панель не входит вовсе.
        odd = f.make_user()
        odd.is_superuser = True
        odd.save(update_fields=["is_superuser"])
        self.assertFalse(self._allowed(IsSuperuser, odd))
        # Прежнее право сотрудника не изменилось.
        self.assertTrue(self._allowed(IsStaff, staff))
        self.assertFalse(self._allowed(IsStaff, user))
