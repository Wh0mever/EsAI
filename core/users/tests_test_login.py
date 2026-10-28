# -*- coding: utf-8 -*-
"""Тестовый вход для тестировщиков платёжки (TEST_LOGIN_EMAIL / TEST_LOGIN_CODE).

- верный постоянный код больше не идёт мимо счётчиков: раньше его перебирали без конца;
- замки только по IP: чужие промахи не запирают тестировщиков;
- короткий код выключает тестовый вход — перебор держит длина кода.
"""
import time
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from users import views as user_views

TEST_CACHES = {"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache",
                           "LOCATION": "users-test-login-tests"}}
TEST_EMAIL = "test@esai.kg"
# Заведомо ненастоящий: боевой код генерируется заново и в репозиторий не попадает.
TEST_CODE = "1212121212"


@override_settings(CACHES=TEST_CACHES, TEST_LOGIN_EMAIL=TEST_EMAIL, TEST_LOGIN_CODE=TEST_CODE)
class TestLoginTests(TestCase):
    def setUp(self):
        cache.clear()

    def _guess(self, code, ip="10.0.0.1", email=TEST_EMAIL):
        return APIClient(REMOTE_ADDR=ip).post(
            "/api/users/signin/confirm/", {"email": email, "code": code}, format="json")

    def _new_window(self, ip="10.0.0.1"):
        # Окно «пять попыток» само истекает через 10 минут.
        cache.delete(f"otp_attempts:{TEST_EMAIL}:{ip}")

    def _locked(self, r, message=user_views.OTP_TOO_MANY_MESSAGE):
        self.assertEqual(r.status_code, 429)
        self.assertEqual(r.data.get("error"), message)

    @patch("users.views.send_template_email")
    def test_signin_sends_no_letter(self, send):
        r = APIClient().post("/api/users/signin/", {"email": TEST_EMAIL}, format="json")
        self.assertEqual(r.status_code, 200, r.data)
        send.assert_not_called()

    def test_right_code_logs_in(self):
        r = self._guess(" 12121 21212 ")
        self.assertEqual(r.status_code, 200, r.data)
        self.assertIn("access", r.data["data"])
        self.assertTrue(get_user_model().objects.filter(email=TEST_EMAIL).exists())

    def test_five_guesses_then_even_right_code_waits(self):
        for _ in range(4):
            self.assertEqual(self._guess("0000000000").status_code, 400)
        self._locked(self._guess("0000000000"))
        # Раньше верный код проходил мимо счётчика — перебор не останавливался.
        self._locked(self._guess(TEST_CODE))
        self._new_window()
        self.assertEqual(self._guess(TEST_CODE).status_code, 200)

    def test_other_ips_misses_do_not_lock_testers(self):
        # Общий по email счётчик позволял любому запереть тестировщиков пятью промахами.
        for n in range(6):
            for _ in range(5):
                self._guess("0000000000", f"10.0.1.{n}")
        self.assertEqual(user_views._otp_pause_left(TEST_EMAIL), 0)
        self.assertEqual(self._guess(TEST_CODE, "10.0.0.7").status_code, 200)

    def test_misses_count_per_ip_only(self):
        self._guess("1")
        self.assertEqual(int(cache.get(user_views._otp_day_key(TEST_EMAIL, "10.0.0.1")) or 0), 1)
        self.assertIsNone(cache.get(user_views._otp_email_fails_key(TEST_EMAIL)))
        self.assertIsNone(cache.get(f"otp_attempts:{TEST_EMAIL}"))

    def test_day_cap_locks_only_the_guessing_ip(self):
        for _ in range(3):
            self._new_window("10.0.0.66")
            for _ in range(5):
                self._guess("0000000000", "10.0.0.66")
        self._new_window("10.0.0.66")
        self._locked(self._guess(TEST_CODE, "10.0.0.66"), user_views.OTP_DAY_LIMIT_MESSAGE)
        self.assertEqual(self._guess(TEST_CODE, "10.0.0.2").status_code, 200)

    def test_attempt_is_counted_before_the_compare(self):
        # Параллельный запрос во время сравнения уже видит потраченную попытку.
        cache.set(f"otp_attempts:{TEST_EMAIL}:10.0.0.1", 4, 600)
        real = user_views.secrets.compare_digest
        inner = []

        def hooked(a, b):
            if not inner:
                inner.append(self._guess(TEST_CODE).status_code)
            return real(a, b)

        with patch.object(user_views.secrets, "compare_digest", side_effect=hooked):
            self.assertEqual(self._guess("0000000000").status_code, 429)
        self.assertEqual(inner, [429])

    def test_attempts_window_really_expires(self):
        t0 = time.time()
        with patch("time.time", return_value=t0):
            for _ in range(5):
                self._guess("0000000000")
            self._locked(self._guess(TEST_CODE))
        with patch("time.time", return_value=t0 + 601):
            self.assertEqual(self._guess(TEST_CODE).status_code, 200)

    def test_new_code_request_does_not_reset_attempts(self):
        for _ in range(5):
            self._guess("0000000000")
        APIClient(REMOTE_ADDR="10.0.0.1").post("/api/users/signin/", {"email": TEST_EMAIL}, format="json")
        self._locked(self._guess(TEST_CODE))

    def test_fixed_code_does_not_open_other_accounts(self):
        self.assertEqual(self._guess(TEST_CODE, email="owner@example.com").status_code, 400)
        cache.set("email_code:owner@example.com", "654321", 600)
        self.assertEqual(self._guess("654321", email="owner@example.com").status_code, 200)

    @override_settings(TEST_LOGIN_CODE="123456")
    @patch("users.views.send_template_email")
    def test_short_code_switches_test_login_off(self, send):
        r = APIClient().post("/api/users/signin/", {"email": TEST_EMAIL}, format="json")
        self.assertEqual(r.status_code, 200, r.data)
        send.assert_called_once()
        self.assertEqual(self._guess("123456").status_code, 400)
        self.assertFalse(get_user_model().objects.filter(email=TEST_EMAIL).exists())

    @override_settings(TEST_LOGIN_EMAIL="")
    @patch("users.views.send_template_email")
    def test_blank_email_switches_test_login_off(self, send):
        APIClient().post("/api/users/signin/", {"email": TEST_EMAIL}, format="json")
        send.assert_called_once()
        self.assertEqual(self._guess(TEST_CODE).status_code, 400)
        self.assertFalse(get_user_model().objects.filter(email=TEST_EMAIL).exists())


@override_settings(CACHES=TEST_CACHES)
class CacheIncrTtlTests(TestCase):
    def test_key_recreated_without_ttl_gets_it_back(self):
        # Redis: EXISTS прошёл, ключ истёк, INCR создал его заново без срока → 1.
        with patch.object(user_views.cache, "incr", return_value=1), \
                patch.object(user_views.cache, "touch") as touch:
            self.assertEqual(user_views._cache_incr("k", 600), 1)
        touch.assert_called_once_with("k", 600)
