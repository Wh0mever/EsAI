# -*- coding: utf-8 -*-
"""Повторная регистрация после /delete, обрезка профиля, гонка первого /start.

Сеть не трогаем. Кэш у тестов свой (см. botapi/tests.py).
"""
from datetime import timedelta
from unittest.mock import patch

from allauth.socialaccount.models import SocialAccount
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.db import DataError, IntegrityError, connection
from django.test import TestCase, override_settings
from django.utils import timezone

from audit.models import EventLog
from plans.models import TokenTransaction

from . import services
from .linking import confirm_link, forget_telegram, start_link
from .models import TelegramChat
from .services import (authenticate_telegram, authenticate_telegram_user, find_user,
                       last_deleted_at, was_deleted_before)
from .tests import SECRET, signed_post, tg_user

TEST_CACHES = {"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache",
                           "LOCATION": "repeat-signup-tests"}}
TG = 700900


def _site_user(email="site@example.com"):
    return get_user_model().objects.create_user(email=email, password="secret123")


def _reasons(user):
    return sorted(TokenTransaction.objects.filter(user=user).values_list("reason", flat=True))


def _balance(user):
    user.refresh_from_db(fields=["token_balance"])
    return int(user.token_balance or 0)


@override_settings(CACHES=TEST_CACHES, BOT_SERVICE_SECRET=SECRET,
                   TELEGRAM_PRODUCT_BOT_TOKEN="1:x", TELEGRAM_PRODUCT_BOT_USERNAME="esai_bot",
                   WELCOME_BONUS_TOKENS=50, DAILY_RETENTION_TARGET=5)
class WasDeletedBeforeTests(TestCase):
    """След /delete живёт только в журнале отвязок — по нему и узнаём."""

    def setUp(self):
        cache.clear()

    def test_fresh_telegram_is_not_a_repeat(self):
        self.assertFalse(was_deleted_before(TG))
        self.assertIsNone(last_deleted_at(TG))

    def test_deleted_stub_is_remembered(self):
        stub, _ = authenticate_telegram_user(tg_user(TG), chat_id=TG)
        self.assertEqual(forget_telegram(TG)["deactivated"], True)
        self.assertTrue(was_deleted_before(TG))
        self.assertTrue(was_deleted_before(str(TG)))
        self.assertFalse(was_deleted_before(TG + 1))
        # Почта погашенной заглушки id не хранит: искать по ней бесполезно.
        stub.refresh_from_db()
        self.assertNotIn(str(TG), stub.email)

    def test_unlink_written_before_october_is_found_by_its_text(self):
        # До 05.10 forget_telegram писал id только в текст записи.
        old = _site_user("old@example.com")
        EventLog.objects.create(type="other", user=old, message=f"tg {TG} ← user {old.pk}",
                                meta={"deactivated": True})
        self.assertTrue(was_deleted_before(TG))
        # Id-префикс и id-продолжение — другие люди.
        self.assertFalse(was_deleted_before(str(TG)[:-1]))
        self.assertFalse(was_deleted_before(f"{TG}0"))

    def test_link_log_is_not_a_delete(self):
        target = _site_user()
        confirm_link(start_link(target)["code"], tg_user(TG), chat_id=TG)
        self.assertTrue(EventLog.objects.filter(meta__telegram_id=str(TG)).exists())
        self.assertFalse(was_deleted_before(TG))

    def test_unlinking_a_site_account_counts_too(self):
        target = _site_user()
        confirm_link(start_link(target)["code"], tg_user(TG), chat_id=TG)
        self.assertEqual(forget_telegram(TG)["deactivated"], False)
        self.assertTrue(was_deleted_before(TG))

    def test_garbage_never_reaches_the_database(self):
        for bad in ("", None, "abc", "12a", ".*", "1|1", "²", "١٢٣", "1 2", "-5", "５"):
            with self.subTest(bad=bad), self.assertNumQueries(0):
                self.assertFalse(was_deleted_before(bad))

    def test_unreadable_journal_means_no_trace_and_a_usable_transaction(self):
        with patch.object(EventLog.objects, "filter", side_effect=RuntimeError("boom")):
            self.assertFalse(was_deleted_before(TG))
        self.assertEqual(get_user_model().objects.count(), 0)

    def test_creators_see_the_same_trace(self):
        from creators import attribution

        authenticate_telegram_user(tg_user(TG), chat_id=TG)
        forget_telegram(TG)
        self.assertTrue(attribution._was_deleted_before(str(TG)))


@override_settings(CACHES=TEST_CACHES, BOT_SERVICE_SECRET=SECRET,
                   TELEGRAM_PRODUCT_BOT_TOKEN="1:x", TELEGRAM_PRODUCT_BOT_USERNAME="esai_bot",
                   WELCOME_BONUS_TOKENS=50, DAILY_RETENTION_TARGET=5)
class RepeatSignupTests(TestCase):
    """/delete → /start не превращается в кнопку «ещё кредитов»."""

    def setUp(self):
        cache.clear()

    def _start(self, **over):
        return authenticate_telegram_user(tg_user(TG, **over), chat_id=TG)

    def test_first_start_gets_the_welcome_bonus(self):
        user, created = self._start()
        self.assertTrue(created)
        self.assertEqual(_reasons(user), ["welcome"])
        self.assertEqual(_balance(user), 50)

    def test_delete_and_start_loop_gives_nothing_new(self):
        first, _ = self._start()
        accounts = {first.pk}
        for _ in range(3):
            forget_telegram(TG)
            again, created = self._start()
            self.assertTrue(created)
            self.assertNotIn(again.pk, accounts)
            accounts.add(again.pk)
            self.assertEqual(_reasons(again), [])
            self.assertEqual(_balance(again), 0)

    def test_return_after_a_day_gets_the_daily_norm_but_not_the_welcome(self):
        self._start()
        forget_telegram(TG)
        EventLog.objects.update(created_at=timezone.now() - timedelta(hours=25))
        again, created = self._start()
        self.assertTrue(created)
        self.assertEqual(_reasons(again), ["daily_bonus"])
        self.assertEqual(_balance(again), 5)

    def test_site_account_unlinked_then_start_is_a_repeat(self):
        # Привязать к сайту → /delete → /start: заглушка без приветственного бонуса.
        target = _site_user()
        confirm_link(start_link(target)["code"], tg_user(TG), chat_id=TG)
        forget_telegram(TG)
        stub, created = self._start()
        self.assertTrue(created)
        self.assertNotEqual(stub.pk, target.pk)
        self.assertEqual(_reasons(stub), [])

    def test_loop_over_the_bot_endpoints(self):
        body = {"telegram_user": tg_user(TG), "chat_id": TG}
        first = signed_post(body)
        self.assertEqual(first.status_code, 200, first.data)
        self.assertTrue(first.data["created"])
        self.assertEqual(first.data["user"]["balance_tokens"], 50)

        gone = signed_post({"telegram_id": TG}, path="/api/bot/delete/")
        self.assertEqual(gone.data, {"status": "unlinked", "deactivated": True})

        again = signed_post(body)
        self.assertEqual(again.status_code, 200, again.data)
        self.assertTrue(again.data["created"])
        self.assertNotEqual(again.data["user"]["id"], first.data["user"]["id"])
        self.assertEqual(again.data["user"]["balance_tokens"], 0)


@override_settings(CACHES=TEST_CACHES, BOT_SERVICE_SECRET=SECRET,
                   TELEGRAM_PRODUCT_BOT_TOKEN="1:x", WELCOME_BONUS_TOKENS=50)
class AuthenticateTelegramTests(TestCase):
    """Профиль из Telegram, гонка первого апдейта, язык нового чата."""

    def setUp(self):
        cache.clear()

    def test_long_telegram_profile_fits_the_columns(self):
        long_name = "Я" * 64
        user, _ = authenticate_telegram_user(
            tg_user(TG, first_name=long_name, last_name=long_name, username="@" + "u" * 32,
                    photo_url="https://t.me/i/userpic/320/" + "a" * 600),
            chat_id=TG)
        user.refresh_from_db()
        model = get_user_model()
        for field in ("first_name", "last_name", "telegram", "avatar_url"):
            limit = model._meta.get_field(field).max_length
            self.assertLessEqual(len(getattr(user, field)), limit, field)
        self.assertEqual(user.first_name, "Я" * model._meta.get_field("first_name").max_length)
        self.assertFalse(user.telegram.startswith("@"))

    def test_long_name_is_cut_on_sync_too(self):
        user, _ = authenticate_telegram_user(tg_user(TG, first_name=""), chat_id=TG)
        self.assertEqual(user.first_name, "")
        again, created = authenticate_telegram_user(tg_user(TG, first_name="Ж" * 64), chat_id=TG)
        self.assertFalse(created)
        again.refresh_from_db()
        self.assertEqual(again.first_name,
                         "Ж" * get_user_model()._meta.get_field("first_name").max_length)

    def test_failed_profile_sync_does_not_break_login(self):
        user, _ = authenticate_telegram_user(tg_user(TG, username="old_nick"), chat_id=TG)
        with patch.object(get_user_model(), "save", side_effect=DataError("value too long")):
            again, created = authenticate_telegram_user(tg_user(TG, username="new_nick"),
                                                        chat_id=TG)
        self.assertFalse(created)
        self.assertEqual(again.pk, user.pk)

    def test_parallel_first_updates_share_one_account(self):
        real = services._create_user

        def neighbour_was_first(tg, **kwargs):
            real(tg, **kwargs)
            raise IntegrityError("duplicate key value violates unique constraint")

        with patch.object(services, "_create_user", side_effect=neighbour_was_first):
            user, created = authenticate_telegram_user(tg_user(TG), chat_id=TG)
        self.assertFalse(created)
        self.assertEqual(get_user_model().objects.count(), 1)
        self.assertEqual(user.pk, find_user(TG).pk)
        self.assertEqual(TelegramChat.objects.get(telegram_id=TG).user_id, user.pk)
        # Подарки новичку выдаёт тот запрос, который аккаунт создал.
        self.assertEqual(_reasons(user), [])

    def test_integrity_error_without_an_account_is_not_swallowed(self):
        with patch.object(services, "_create_user", side_effect=IntegrityError("other")):
            with self.assertRaises(IntegrityError):
                authenticate_telegram_user(tg_user(TG), chat_id=TG)

    def test_failing_signup_step_keeps_the_account(self):
        def broken_plan(user):
            # Настоящая ошибка БД, а не исключение Python.
            with connection.cursor() as cursor:
                cursor.execute("SELECT * FROM no_such_table_rv2")

        with patch("users.services.activate_free_plan_for_user", side_effect=broken_plan):
            user, created = authenticate_telegram_user(tg_user(TG), chat_id=TG)
        self.assertTrue(created)
        self.assertEqual(_reasons(user), ["welcome"])
        self.assertTrue(TelegramChat.objects.filter(telegram_id=TG, user=user).exists())

    def test_site_account_new_in_bot_gets_the_phone_language(self):
        site = _site_user()
        SocialAccount.objects.create(user=site, provider="telegram", uid=str(TG), extra_data={})
        user, created, chat_created = authenticate_telegram(tg_user(TG, language_code="en"),
                                                            chat_id=TG)
        self.assertEqual((user.pk, created, chat_created), (site.pk, False, True))
        chat = TelegramChat.objects.get(telegram_id=TG)
        self.assertEqual(chat.lang, "en")
        # Дальше язык — выбор человека, настройки телефона его не перетирают.
        chat.lang = "kg"
        chat.save(update_fields=["lang"])
        _, _, chat_created = authenticate_telegram(tg_user(TG, language_code="en"), chat_id=TG)
        self.assertFalse(chat_created)
        chat.refresh_from_db()
        self.assertEqual(chat.lang, "kg")

    def test_old_entry_point_keeps_its_contract(self):
        result = authenticate_telegram_user(tg_user(TG), chat_id=TG,
                                            source=TelegramChat.SOURCE_WEBAPP)
        self.assertEqual(len(result), 2)
        self.assertEqual(TelegramChat.objects.get(telegram_id=TG).source,
                         TelegramChat.SOURCE_WEBAPP)
        # Всё, кроме данных Telegram, — только по имени, как и раньше.
        with self.assertRaises(TypeError):
            authenticate_telegram_user(tg_user(TG), None)
        with self.assertRaises(TypeError):
            authenticate_telegram_user(tg_user(TG), unknown=1)
