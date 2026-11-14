# -*- coding: utf-8 -*-
"""Онлайн на сайте: отметки вкладок, счёт гостей/вошедших, разделы, доступ к цифрам только сотрудникам."""
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase, override_settings
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from . import presence

TEST_CACHES = {"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache",
                           "LOCATION": "presence-tests"}}
PING = "/api/users/presence/"
ONLINE = "/api/manage/online/"


def _auth(user):
    api = APIClient()
    api.credentials(HTTP_AUTHORIZATION=f"Bearer {RefreshToken.for_user(user).access_token}")
    return api


@override_settings(CACHES=TEST_CACHES)
class PresenceTests(TestCase):
    def setUp(self):
        cache.clear()
        User = get_user_model()
        self.user = User.objects.create_user(email="p@example.com", password="x")
        self.staff = User.objects.create_user(email="s@example.com", password="x")
        self.staff.is_staff = True
        self.staff.save(update_fields=["is_staff"])

    def test_guests_users_sections(self):
        anon = APIClient()
        self.assertEqual(anon.post(PING, {"vid": "a" * 20, "section": "chat"}, format="json").status_code, 204)
        anon.post(PING, {"vid": "a" * 20, "section": "video_studio"}, format="json")  # тот же человек ушёл в студию
        anon.post(PING, {"vid": "b" * 20, "section": "nonsense"}, format="json")
        _auth(self.user).post(PING, {"vid": "c" * 20, "section": "studio"}, format="json")
        snap = presence.snapshot()
        self.assertEqual((snap["online"], snap["users"], snap["guests"]), (3, 1, 2))
        self.assertEqual(snap["by_section"]["video_studio"], 1)
        self.assertEqual(snap["by_section"]["chat"], 0)
        self.assertEqual(snap["by_section"]["other"], 1)
        self.assertEqual(snap["by_section"]["studio"], 1)
        self.assertEqual(snap["peak_today"], 3)

    def test_window_expires(self):
        presence.touch("x" * 20, None, "chat")
        with patch("users.presence.time.time", return_value=presence.time.time() + presence.ONLINE_WINDOW_SEC + 5):
            snap = presence.snapshot()
        self.assertEqual(snap["online"], 0)
        self.assertEqual(snap["peak_today"], 1)  # пик за день остаётся

    def test_bad_vid(self):
        self.assertEqual(APIClient().post(PING, {"vid": "short"}, format="json").status_code, 400)
        self.assertEqual(APIClient().post(PING, {"vid": "a b" * 10}, format="json").status_code, 400)

    def test_online_staff_only(self):
        presence.touch("y" * 20, self.user.id, "pricing")
        self.assertEqual(APIClient().get(ONLINE).status_code, 401)
        self.assertEqual(_auth(self.user).get(ONLINE).status_code, 403)
        body = _auth(self.staff).get(ONLINE).json()
        self.assertEqual(body["online"], 1)
        self.assertEqual(body["by_section"]["pricing"], 1)
