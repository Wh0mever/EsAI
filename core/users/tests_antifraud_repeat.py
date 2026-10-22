# -*- coding: utf-8 -*-
"""Антифрод приветственного бонуса: повторный аккаунт того же Telegram.

Правило одно на все входы: бот, Mini App и вход через Telegram на сайте
(allauth) зовут maybe_grant_welcome_bonus у только что заведённого аккаунта.
"""
from datetime import timedelta
from unittest.mock import patch

from allauth.socialaccount.adapter import DefaultSocialAccountAdapter
from allauth.socialaccount.models import SocialAccount
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import RequestFactory, TestCase, override_settings
from django.utils import timezone

from audit.models import EventLog, SignupDevice
from plans.models import TokenTransaction

from .adapters import SocialAccountAdapter
from .antifraud import maybe_grant_welcome_bonus

TEST_CACHES = {"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache",
                           "LOCATION": "antifraud-repeat-tests"}}
TG = 700950


def _user(email, *, provider="telegram", uid=TG):
    user = get_user_model().objects.create_user(email=email, password="x")
    if provider:
        SocialAccount.objects.create(user=user, provider=provider, uid=str(uid), extra_data={})
    return user


def _deleted(uid=TG, *, hours_ago=0):
    """След /delete, как его пишет botapi.linking.forget_telegram."""
    old = get_user_model().objects.create_user(email=f"deleted_{uid}_old@social.esai.local",
                                               password="x", is_active=False)
    row = EventLog.objects.create(type="other", user=old, message=f"tg {uid} ← user {old.pk}",
                                  meta={"deactivated": True, "telegram_id": str(uid)})
    if hours_ago:
        EventLog.objects.filter(pk=row.pk).update(
            created_at=timezone.now() - timedelta(hours=hours_ago))
    return old


def _reasons(user):
    return sorted(TokenTransaction.objects.filter(user=user).values_list("reason", flat=True))


@override_settings(CACHES=TEST_CACHES, WELCOME_BONUS_TOKENS=50, DAILY_RETENTION_TARGET=5)
class RepeatTelegramSignupTests(TestCase):
    def setUp(self):
        cache.clear()

    def test_new_telegram_gets_the_welcome(self):
        user = _user(f"telegram_{TG}@social.esai.local")
        self.assertEqual(maybe_grant_welcome_bonus(user, None)["status"], "approved")
        self.assertEqual(_reasons(user), ["welcome"])

    def test_site_telegram_login_right_after_delete_gets_nothing(self):
        # allauth завёл новую заглушку тому, кто только что сделал /delete в боте.
        _deleted()
        user = _user(f"telegram_{TG}@social.esai.local")
        self.assertEqual(maybe_grant_welcome_bonus(user, None), {"status": "repeat_signup"})
        self.assertEqual(_reasons(user), [])
        # Слепок устройства пишется и повторному: он нужен для следующих оценок.
        self.assertTrue(SignupDevice.objects.filter(user=user).exists())

    def test_return_after_a_day_gets_only_the_daily_norm(self):
        _deleted(hours_ago=25)
        user = _user(f"telegram_{TG}@social.esai.local")
        self.assertEqual(maybe_grant_welcome_bonus(user, None),
                         {"status": "daily_granted", "amount": 5})
        self.assertEqual(_reasons(user), ["daily_bonus"])

    def test_explicit_repeat_flag_without_a_trace_is_still_a_repeat(self):
        user = _user("someone@example.com", provider=None)
        self.assertEqual(maybe_grant_welcome_bonus(user, None, allow_welcome=False),
                         {"status": "repeat_signup"})
        self.assertEqual(_reasons(user), [])

    @override_settings(WELCOME_BONUS_TOKENS=0)
    def test_disabled_welcome_still_gives_the_norm_to_newcomers(self):
        user = _user(f"telegram_{TG}@social.esai.local")
        self.assertEqual(maybe_grant_welcome_bonus(user, None),
                         {"status": "daily_granted", "amount": 5})

    @override_settings(WELCOME_BONUS_TOKENS=0)
    def test_disabled_welcome_does_not_open_a_norm_loop(self):
        _deleted(hours_ago=1)
        user = _user(f"telegram_{TG}@social.esai.local")
        self.assertEqual(maybe_grant_welcome_bonus(user, None), {"status": "repeat_signup"})
        self.assertEqual(_reasons(user), [])

    def test_other_providers_and_other_ids_are_untouched(self):
        _deleted()
        google = _user("g@example.com", provider="google", uid=TG)
        self.assertEqual(maybe_grant_welcome_bonus(google, None)["status"], "approved")
        other = _user(f"telegram_{TG + 1}@social.esai.local", uid=TG + 1)
        self.assertEqual(maybe_grant_welcome_bonus(other, None)["status"], "approved")
        email_only = _user("mail@example.com", provider=None)
        self.assertEqual(maybe_grant_welcome_bonus(email_only, None)["status"], "approved")

    def test_unreadable_journal_does_not_cost_a_newcomer_the_bonus(self):
        _deleted()
        user = _user(f"telegram_{TG}@social.esai.local")
        with patch("botapi.services.last_deleted_at", side_effect=RuntimeError("boom")):
            self.assertEqual(maybe_grant_welcome_bonus(user, None)["status"], "approved")
        self.assertEqual(_reasons(user), ["welcome"])


@override_settings(CACHES=TEST_CACHES, WELCOME_BONUS_TOKENS=50, DAILY_RETENTION_TARGET=5)
class SiteWelcomeWindowTests(TestCase):
    """Окно «бонусные кредиты уже начислены» после входа через Telegram на сайте."""

    def setUp(self):
        cache.clear()

    def _site_login(self):
        # allauth к этому моменту уже сохранил пользователя и его привязку Telegram.
        user = _user(f"telegram_{TG}@social.esai.local")
        with patch.object(DefaultSocialAccountAdapter, "save_user", return_value=user):
            SocialAccountAdapter().save_user(RequestFactory().get("/"), None)
        return user

    def test_newcomer_sees_the_window(self):
        user = self._site_login()
        self.assertEqual(_reasons(user), ["welcome"])
        self.assertEqual(cache.get(f"welcome_show:{user.pk}"), "1")

    def test_repeat_telegram_is_not_told_about_a_bonus_it_did_not_get(self):
        _deleted()
        user = self._site_login()
        self.assertEqual(_reasons(user), [])
        self.assertIsNone(cache.get(f"welcome_show:{user.pk}"))

    def test_return_after_a_day_still_sees_the_window(self):
        # Дневную норму сразу дали — кредиты на балансе есть, окно не врёт.
        _deleted(hours_ago=25)
        user = self._site_login()
        self.assertEqual(_reasons(user), ["daily_bonus"])
        self.assertEqual(cache.get(f"welcome_show:{user.pk}"), "1")
