# -*- coding: utf-8 -*-
"""Раунд 2: безлимитный аккаунт в /api/plans/balance/ и опознание человека
в анонимном /api/users/question/.

Кэш у тестов свой (LocMem): счётчики троттлинга DRF живут в кэше, и прогон в
боевом контейнере иначе выел бы лимиты живым людям.

Про соседа по файлу: тест QuestionAPIView лежит здесь, потому что во втором
раунде на группу выделены ровно два новых тест-файла, а users/tests.py правит
другой агент.
"""
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase, override_settings
from rest_framework.test import APIClient
from rest_framework.throttling import SimpleRateThrottle
from rest_framework_simplejwt.tokens import RefreshToken

TEST_CACHES = {"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache",
                           "LOCATION": "balance-unlimited-tests"}}
BALANCE_URL = "/api/plans/balance/"
QUESTION_URL = "/api/users/question/"


def _user(email, **flags):
    User = get_user_model()
    user = User.objects.create_user(email=email, password="x")
    for name, value in flags.items():
        setattr(user, name, value)
    if flags:
        user.save(update_fields=list(flags))
    return user


@override_settings(CACHES=TEST_CACHES)
class BalanceUnlimitedTests(TestCase):
    """Безлимитный аккаунт не должен выглядеть «платным»."""

    def setUp(self):
        cache.clear()

    def _get(self, user):
        client = APIClient()
        client.force_authenticate(user)
        return client.get(BALANCE_URL)

    def test_unlimited_user_gets_own_tier_and_flag(self):
        user = _user("unlim@example.com", is_unlimited=True, token_balance=5)
        response = self._get(user)
        self.assertEqual(response.status_code, 200)
        # До правки здесь приходил "paid" — и бот, и сайт подписывали безлимит
        # платным тарифом.
        self.assertEqual(response.data["tier"], "unlimited")
        self.assertTrue(response.data["is_unlimited"])

    def test_paid_user_unchanged(self):
        user = _user("paid@example.com", is_paid=True, token_balance=40)
        response = self._get(user)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["tier"], "paid")
        self.assertFalse(response.data["is_unlimited"])
        self.assertTrue(response.data["is_paid"])
        self.assertEqual(response.data["balance_tokens"], 40)

    def test_free_user_unchanged(self):
        user = _user("free@example.com", token_balance=3)
        response = self._get(user)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["tier"], "free")
        self.assertFalse(response.data["is_unlimited"])

    def test_model_access_for_unlimited_still_paid_grade(self):
        """Витринный тир поменялся, допуск к премиум-моделям — нет.

        Значение "unlimited" собирается только во вьюхе; plans/tiers.py по-
        прежнему считает такой аккаунт платным, иначе безлимитному человеку
        молча закрылись бы все платные модели.
        """
        from .tiers import is_free_tier, is_paid_tier, user_tier

        user = _user("unlim2@example.com", is_unlimited=True)
        self.assertTrue(is_paid_tier(user))
        self.assertFalse(is_free_tier(user))
        self.assertEqual(user_tier(user), "paid")


# Ставки троттлинга DRF читает один раз при импорте (SimpleRateThrottle.
# THROTTLE_RATES — атрибут класса), поэтому override_settings(REST_FRAMEWORK)
# на них уже не влияет: правим сам словарь, patch.dict вернёт его обратно.
@patch.dict(SimpleRateThrottle.THROTTLE_RATES, {"anon": "1/min"})
@override_settings(CACHES=TEST_CACHES)
class QuestionThrottleIdentityTests(TestCase):
    """Обращение в поддержку из бота не должно упираться в лимит по IP.

    Бот ходит из одного контейнера, поэтому анонимный лимит (по IP) он делит
    на всех людей сразу: десяток активных — и поддержка отвечает 429. Если
    запрос принёс токен, лимит должен считаться по человеку.
    """

    def setUp(self):
        cache.clear()
        self.payload = {"email": "q@example.com", "name": "Иван",
                        "question": "Не приходит письмо со входом, помогите."}

    def test_anonymous_limit_still_enforced(self):
        client = APIClient()
        first = client.post(QUESTION_URL, self.payload, format="json")
        second = client.post(QUESTION_URL, self.payload, format="json")
        self.assertEqual(first.status_code, 201)
        # Аноним с сайта защищён ровно как раньше.
        self.assertEqual(second.status_code, 429)

    def test_authenticated_request_is_counted_per_user(self):
        user = _user("support@example.com")
        token = str(RefreshToken.for_user(user).access_token)
        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")
        first = client.post(QUESTION_URL, self.payload, format="json")
        second = client.post(QUESTION_URL, self.payload, format="json")
        self.assertEqual(first.status_code, 201)
        # До правки эндпоинт вообще не смотрел на токен: оба запроса считались
        # анонимными и второй ловил 429.
        self.assertEqual(second.status_code, 201)

    def test_broken_token_falls_back_to_anonymous(self):
        """Протухший токен в старой вкладке — не повод отвечать 401."""
        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION="Bearer not-a-real-token")
        response = client.post(QUESTION_URL, self.payload, format="json")
        self.assertEqual(response.status_code, 201)
