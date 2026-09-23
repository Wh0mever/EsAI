# -*- coding: utf-8 -*-
"""Вход и деньги: то, что нашёл аудит 23.09.

- регистрации по паролю больше нет (можно было занять чужой email заранее);
- чужой email не вписать и через управление почтой allauth;
- код из письма нельзя перебирать бесконечно, но и чужие промахи не
  запирают вход хозяину почты;
- отменённый соцвход не отдаёт токены чужой недобитой сессии;
- переводить можно только купленные кредиты, подарочные остаются у человека.
"""
import time
from unittest.mock import patch

from allauth.account.models import EmailAddress
from allauth.socialaccount.models import SocialAccount
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import Client, TestCase, override_settings
from rest_framework.test import APIClient

from plans.wallet import credit_tokens, transferable_tokens
from users import views as user_views

TEST_CACHES = {"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache",
                           "LOCATION": "users-security-tests"}}


@override_settings(CACHES=TEST_CACHES)
class PasswordAuthClosedTests(TestCase):
    def test_password_signup_and_token_are_gone(self):
        client = APIClient()
        r = client.post("/api/users/signup/", {"email": "victim@example.com", "tel": "+996700000000",
                                               "password": "Abc12345", "name": "x"}, format="json")
        self.assertEqual(r.status_code, 404)
        r = client.post("/api/users/token/", {"email": "victim@example.com", "password": "Abc12345"},
                        format="json")
        self.assertEqual(r.status_code, 404)
        self.assertFalse(get_user_model().objects.filter(email="victim@example.com").exists())

    def test_allauth_password_forms_redirect_to_site_signin(self):
        client = APIClient()
        for url in ("/api/users/accounts/login/", "/api/users/accounts/signup/",
                    "/api/users/accounts/password/reset/"):
            r = client.post(url, {"email": "victim@example.com", "password1": "Abc12345",
                                  "password2": "Abc12345"})
            self.assertEqual(r.status_code, 302, url)
            self.assertTrue(r["Location"].endswith("/auth/signin"), r["Location"])
        self.assertFalse(get_user_model().objects.filter(email="victim@example.com").exists())


@override_settings(CACHES=TEST_CACHES, TEST_LOGIN_EMAIL="", TEST_LOGIN_CODE="")
class OtpBruteForceTests(TestCase):
    email = "owner@example.com"

    def setUp(self):
        cache.clear()

    def _guess(self, code):
        return APIClient().post("/api/users/signin/confirm/", {"email": self.email, "code": code},
                                format="json")

    def test_five_guesses_per_code_then_code_dies(self):
        cache.set(f"email_code:{self.email}", "123456", 600)
        for _ in range(4):
            self.assertEqual(self._guess("000000").status_code, 400)
        self.assertEqual(self._guess("000000").status_code, 429)
        # Даже верный код после пяти промахов уже не работает.
        self.assertEqual(self._guess("123456").status_code, 429)

    def test_daily_cap_survives_new_codes(self):
        # Раньше новый код обнулял счётчик — и перебор шёл без конца.
        for _ in range(3):
            cache.set(f"email_code:{self.email}", "123456", 600)
            cache.delete(f"otp_attempts:{self.email}")  # так делает отправка нового кода
            for _ in range(5):
                self._guess("000000")
        cache.set(f"email_code:{self.email}", "123456", 600)
        cache.delete(f"otp_attempts:{self.email}")
        r = self._guess("123456")
        self.assertEqual(r.status_code, 429)

    def test_right_code_logs_in(self):
        cache.set(f"email_code:{self.email}", "654321", 600)
        self.assertEqual(self._guess("111111").status_code, 400)
        r = self._guess("654321")
        self.assertEqual(r.status_code, 200, r.data)
        self.assertIn("access", r.data["data"])

    def test_non_ascii_code_is_a_plain_miss(self):
        cache.set(f"email_code:{self.email}", "654321", 600)
        self.assertEqual(self._guess("６５４３２１").status_code, 400)


@override_settings(CACHES=TEST_CACHES, TEST_LOGIN_EMAIL="", TEST_LOGIN_CODE="")
class OtpLockoutTests(TestCase):
    """Чужие промахи не запирают вход хозяину почты на сутки."""
    email = "admin@example.com"

    def setUp(self):
        cache.clear()

    def _new_code(self, code="123456"):
        # Так делает отправка нового письма.
        cache.set(f"email_code:{self.email}", code, 600)
        cache.delete(f"otp_attempts:{self.email}")

    def _guess(self, code, ip):
        return APIClient(REMOTE_ADDR=ip).post(
            "/api/users/signin/confirm/", {"email": self.email, "code": code}, format="json")

    def test_day_cap_locks_only_the_guessing_ip(self):
        with patch.object(user_views, "OTP_EMAIL_FAILS_PER_PAUSE", 1000):
            for _ in range(3):
                self._new_code()
                for _ in range(5):
                    self._guess("000000", "10.0.0.66")
            self._new_code()
            self.assertEqual(self._guess("123456", "10.0.0.66").status_code, 429)
            r = self._guess("123456", "10.0.0.1")
            self.assertEqual(r.status_code, 200, r.data)

    def test_many_ips_get_a_short_pause_not_a_day(self):
        for n in range(3):
            self._new_code()
            for _ in range(5):
                self._guess("000000", f"10.0.1.{n}")
        self._new_code()
        r = self._guess("123456", "10.0.0.1")
        self.assertEqual(r.status_code, 429)
        self.assertIn("мин", r.data["error"])
        left = user_views._otp_pause_left(self.email)
        self.assertTrue(0 < left <= 15 * 60, left)
        # Пауза кончилась — хозяин входит.
        cache.delete(user_views._otp_pause_key(self.email))
        self._new_code()
        self.assertEqual(self._guess("123456", "10.0.0.1").status_code, 200)

    def test_guesses_without_live_code_cost_nothing(self):
        for _ in range(4):
            cache.delete(f"otp_attempts:{self.email}")
            for _ in range(5):
                self._guess("000000", "10.0.0.66")
        self.assertEqual(user_views._otp_pause_left(self.email), 0)
        self._new_code()
        self.assertEqual(self._guess("123456", "10.0.0.66").status_code, 200)

    @patch("users.views.send_template_email")
    def test_code_is_always_sent_to_owner(self, send):
        for n in range(3):
            self._new_code()
            for _ in range(5):
                self._guess("000000", f"10.0.1.{n}")
        r = APIClient(REMOTE_ADDR="10.0.0.1").post(
            "/api/users/signin/", {"email": self.email}, format="json")
        self.assertEqual(r.status_code, 200, r.data)
        send.assert_called_once()


@override_settings(CACHES=TEST_CACHES, TEST_LOGIN_EMAIL="", TEST_LOGIN_CODE="")
class EmailClaimTests(TestCase):
    """Чужой адрес нельзя вписать в свой аккаунт и дождаться хозяина."""
    victim = "victim@example.com"
    stub = "telegram_42@social.esai.local"

    def setUp(self):
        cache.clear()
        self.attacker = get_user_model().objects.create_user(email=self.stub)
        self.attacker.set_unusable_password()
        self.attacker.save()
        SocialAccount.objects.create(user=self.attacker, provider="telegram", uid="42")
        EmailAddress.objects.create(user=self.attacker, email=self.stub, verified=False, primary=True)

    def _confirm(self):
        cache.set(f"email_code:{self.victim}", "123456", 600)
        return APIClient().post("/api/users/signin/confirm/",
                                {"email": self.victim, "code": "123456"}, format="json")

    def test_allauth_email_management_is_closed(self):
        client = Client()
        client.force_login(self.attacker)
        r = client.post("/api/users/accounts/email/", {"action_add": "", "email": self.victim})
        self.assertEqual(r.status_code, 302)
        self.assertTrue(r["Location"].endswith("/auth/signin"), r["Location"])
        r = client.post("/api/users/accounts/email/", {"action_primary": "", "email": self.victim})
        self.assertEqual(r.status_code, 302)
        self.attacker.refresh_from_db()
        self.assertEqual(self.attacker.email, self.stub)
        self.assertFalse(EmailAddress.objects.filter(email=self.victim).exists())
        for url in ("/api/users/accounts/confirm-email/", "/api/users/accounts/confirm-email/abc/",
                    "/api/users/accounts/reauthenticate/", "/api/users/accounts/login/code/confirm/",
                    "/api/users/accounts/3rdparty/signup/"):
            r = client.get(url)
            self.assertEqual(r.status_code, 302, url)
            self.assertIn("/auth/signin", r["Location"], url)

    def test_owner_does_not_land_in_account_that_claimed_email_unverified(self):
        # Так выглядит захват, сделанный, пока accounts/email/ был открыт.
        EmailAddress.objects.filter(user=self.attacker).update(primary=False)
        EmailAddress.objects.create(user=self.attacker, email=self.victim, verified=False, primary=True)
        self.attacker.email = self.victim
        self.attacker.save(update_fields=["email"])
        credit_tokens(self.attacker, 100, "purchase", meta={"order_id": "x"})

        r = self._confirm()
        self.assertEqual(r.status_code, 200, r.data)
        self.assertNotEqual(r.data["data"]["user"]["id"], self.attacker.pk)
        self.assertTrue(r.data["data"]["is_new"])
        self.attacker.refresh_from_db()
        self.assertEqual(self.attacker.email, self.stub)
        self.assertEqual(self.attacker.token_balance, 100)
        self.assertFalse(EmailAddress.objects.filter(user=self.attacker, email=self.victim).exists())
        self.assertTrue(EmailAddress.objects.get(user=self.attacker, email=self.stub).primary)

    def test_proven_accounts_still_log_in(self):
        User = get_user_model()
        by_code = User.objects.create_user(email=self.victim)
        r = self._confirm()
        self.assertEqual(r.data["data"]["user"]["id"], by_code.pk)
        by_code.delete()
        google = User.objects.create_user(email=self.victim)
        EmailAddress.objects.create(user=google, email=self.victim, verified=True, primary=True)
        r = self._confirm()
        self.assertEqual(r.data["data"]["user"]["id"], google.pk)
        google.delete()
        # Старая регистрация формой allauth без соцвхода: пароль закрыт, кроме
        # хозяина почты войти туда некому — его и пускаем.
        old_form = User.objects.create_user(email=self.victim, password="x")
        EmailAddress.objects.create(user=old_form, email=self.victim, verified=False, primary=True)
        r = self._confirm()
        self.assertEqual(r.data["data"]["user"]["id"], old_form.pk)


@override_settings(CACHES=TEST_CACHES)
class SocialErrorDoesNotReuseStaleSessionTests(TestCase):
    """Отменённый соцвход не впускает в аккаунт, оставшийся в сессии."""
    callback = "/api/users/accounts/google/login/callback/"

    def setUp(self):
        self.owner = get_user_model().objects.create_user(email="a@example.com")
        self.client = Client()
        self.client.force_login(self.owner)

    def _record_login(self, provider="google", ago=0):
        session = self.client.session
        session["account_authentication_methods"] = [
            {"method": "socialaccount", "at": time.time() - ago, "provider": provider, "uid": "1"}]
        session.save()

    def _assert_failed(self, r):
        self.assertEqual(r.status_code, 302)
        self.assertIn("error=social_login_failed", r["Location"])

    def _cancel(self):
        # Настоящая отмена: человек начал вход (state в сессии) и нажал «Отмена» у Google.
        from urllib.parse import parse_qs, urlsplit

        r = self.client.get("/api/users/accounts/google/login/", {"process": "login"})
        state = parse_qs(urlsplit(r["Location"]).query)["state"][0]
        return self.client.get(self.callback, {"error": "access_denied", "state": state})

    def test_stale_session_gets_no_tokens(self):
        self._assert_failed(self._cancel())
        self._assert_failed(self.client.get(self.callback, {"error": "server_error"}))

    def test_cancel_right_after_login_gets_no_tokens(self):
        self._record_login()
        self._assert_failed(self._cancel())

    def test_old_or_other_provider_login_gets_no_tokens(self):
        self._record_login(ago=3600)
        self._assert_failed(self.client.get(self.callback, {"error": "server_error"}))
        self._record_login(provider="telegram")
        self._assert_failed(self.client.get(self.callback, {"error": "server_error"}))

    def test_double_callback_right_after_login_still_recovers(self):
        self._record_login()
        r = self.client.get(self.callback, {"error": "server_error"})
        self.assertEqual(r.status_code, 302)
        self.assertTrue(r["Location"].endswith("/api/users/auth/complete/"), r["Location"])

    def test_auth_complete_shortens_session(self):
        r = self.client.get("/api/users/auth/complete/")
        self.assertEqual(r.status_code, 302)
        self.assertIn("/auth/callback#", r["Location"])
        self.assertLessEqual(self.client.session.get_expiry_age(), 300)


@override_settings(CACHES=TEST_CACHES)
class TransferPurchasedOnlyTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.sender = User.objects.create_user(email="a@example.com", password="x")
        self.friend = User.objects.create_user(email="b@example.com", password="x")
        self.client = APIClient()
        self.client.force_authenticate(self.sender)

    def _send(self, amount):
        return self.client.post("/api/users/transfer/", {"recipient": "b@example.com",
                                                         "amount": amount}, format="json")

    def test_gifted_credits_cannot_be_transferred(self):
        credit_tokens(self.sender, 50, "daily_bonus")
        credit_tokens(self.sender, 30, "promo")
        r = self._send(10)
        self.assertEqual(r.status_code, 400)
        self.assertEqual(r.data["transferable"], 0)
        self.friend.refresh_from_db()
        self.assertEqual(self.friend.token_balance, 0)

    def test_purchased_credits_can_be_transferred_up_to_the_pool(self):
        credit_tokens(self.sender, 40, "daily_bonus")
        credit_tokens(self.sender, 100, "purchase", meta={"order_id": "o1"})
        self.assertEqual(transferable_tokens(self.sender), 100)
        self.assertEqual(self._send(60).status_code, 200)
        self.assertEqual(transferable_tokens(self.sender), 40)
        self.assertEqual(self._send(41).status_code, 400)
        self.assertEqual(self._send(40).status_code, 200)
        self.friend.refresh_from_db()
        self.assertEqual(self.friend.token_balance, 100)
        # Полученное переводом можно передать дальше.
        self.assertEqual(transferable_tokens(self.friend), 100)

    def test_get_reports_pool(self):
        credit_tokens(self.sender, 25, "purchase", meta={"order_id": "o2"})
        r = self.client.get("/api/users/transfer/")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.data["transferable"], 25)

    def test_not_enough_balance_keeps_old_message(self):
        credit_tokens(self.sender, 5, "purchase", meta={"order_id": "o3"})
        r = self._send(10)
        self.assertEqual(r.status_code, 400)
        self.assertEqual(r.data["message"], "Недостаточно кредитов")
