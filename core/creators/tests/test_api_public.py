"""Публичные адреса программы: условия, переход по ссылке, «кто меня пригласил».

Здесь же общая база тестов API (ApiTestCase) и помощники — остальные модули
test_api_*, test_permissions и test_admin_log_coverage берут их отсюда.
"""
from types import SimpleNamespace
from unittest.mock import patch

from django.test import override_settings
from rest_framework.test import APIClient
from rest_framework.throttling import AnonRateThrottle, ScopedRateThrottle

from adminapi.runtime import set_runtime

from .. import views
from ..models import CreatorApplication, CreatorClick
from . import factories as f

API = "/api/creators/"
MANAGE = "/api/manage/"

# Заявка, которая проходит проверку целиком.
APPLY = {
    "name": "Тора",
    "telegram": "@tora",
    "country": "Кыргызстан",
    "instagram_url": "https://instagram.com/tora",
    "followers": 1200,
    "occupation": "Снимаю ролики про нейросети",
    "motivation": "Хочу зарабатывать на своей аудитории",
    "samples": ["https://youtube.com/watch?v=abc"],
    "lang": "en",
}


def make_application(user=None, *, status="new", **extra):
    """Заявка напрямую через ORM (в фабриках её нет)."""
    fields = {"name": "Тора", "telegram": "@tora", "country": "KG",
              "instagram_url": "https://instagram.com/tora", "followers": 1000,
              "occupation": "Блогер", "motivation": "Аудитория", "lang": "ru"}
    fields.update(extra)
    return CreatorApplication.objects.create(user=user or f.make_user(), status=status, **fields)


class ApiTestCase(f.CreatorsTestCase):
    """База тестов API: клиент с готовым входом, бот и письма заглушены."""

    def setUp(self):
        super().setUp()
        # Уведомления уходят после фиксации транзакции; наружу из тестов — никогда.
        self.tg = self.patch("botapi.tasks.notify")

    def patch(self, target, **kwargs):
        patcher = patch(target, **kwargs)
        mock = patcher.start()
        self.addCleanup(patcher.stop)
        return mock

    def client_for(self, user=None) -> APIClient:
        client = APIClient()
        if user is not None:
            client.force_authenticate(user)
        return client

    def assertError(self, response, http: int, code: str):
        self.assertEqual(response.status_code, http, getattr(response, "data", None))
        self.assertEqual(response.data.get("code"), code, response.data)
        # detail — всегда строка и равен message.
        self.assertIsInstance(response.data.get("detail"), str)
        self.assertEqual(response.data["detail"], response.data["message"])


# ------------------------------------------------------------------ program/

class ProgramTests(ApiTestCase):
    def test_anonymous_sees_program_and_levels(self):
        response = self.client_for().get(API + "program/")
        self.assertEqual(response.status_code, 200, response.data)
        data = response.data
        self.assertEqual(set(data), {"mode", "min_payout_usdt", "hold_days", "network",
                                     "levels", "me"})
        self.assertEqual(data["mode"], "on")
        self.assertEqual(data["min_payout_usdt"], "10.00")
        self.assertEqual(data["hold_days"], 14)
        self.assertEqual(data["network"], "TRC20")
        self.assertEqual([level["key"] for level in data["levels"]],
                         ["creator", "creator_pro", "ambassador", "ambassador_pro"])
        self.assertEqual(set(data["levels"][0]),
                         {"key", "title", "percent", "sort", "min_publications",
                          "min_registrations", "min_paying"})
        self.assertEqual([level["percent"] for level in data["levels"]],
                         ["10.00", "15.00", "20.00", "25.00"])
        self.assertEqual(data["me"], {"is_authenticated": False, "is_creator": False,
                                      "creator_status": None, "application_status": None})

    def test_me_block_for_user_applicant_and_creator(self):
        user = f.make_user()
        me = self.client_for(user).get(API + "program/").data["me"]
        self.assertEqual(me, {"is_authenticated": True, "is_creator": False,
                              "creator_status": None, "application_status": None})

        make_application(user, status="rejected")
        make_application(user, status="new")
        me = self.client_for(user).get(API + "program/").data["me"]
        self.assertEqual(me["application_status"], "new")
        self.assertFalse(me["is_creator"])

        creator = f.make_creator(user)
        me = self.client_for(user).get(API + "program/").data["me"]
        self.assertTrue(me["is_creator"])
        self.assertEqual(me["creator_status"], "active")

        type(creator).objects.filter(pk=creator.pk).update(status="blocked")
        me = self.client_for(user).get(API + "program/").data["me"]
        self.assertTrue(me["is_creator"])
        self.assertEqual(me["creator_status"], "blocked")

    def test_hold_days_follow_runtime_setting(self):
        set_runtime("creators_hold_days", 30)
        self.assertEqual(self.client_for().get(API + "program/").data["hold_days"], 30)

    @override_settings(CREATORS_MODE="staff")
    def test_staff_mode_hides_program_from_everyone_but_staff(self):
        self.assertError(self.client_for().get(API + "program/"), 404, "disabled")
        self.assertError(self.client_for(f.make_user()).get(API + "program/"), 404, "disabled")
        response = self.client_for(f.make_user(staff=True)).get(API + "program/")
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["mode"], "staff")

    @override_settings(CREATORS_MODE="off")
    def test_off_mode_is_404_even_for_staff(self):
        self.assertError(self.client_for().get(API + "program/"), 404, "disabled")
        self.assertError(self.client_for(f.make_user(superuser=True)).get(API + "program/"),
                         404, "disabled")

    def test_broken_token_is_treated_as_anonymous(self):
        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION="Bearer not-a-token")
        response = client.get(API + "program/")
        self.assertEqual(response.status_code, 200, response.data)
        self.assertFalse(response.data["me"]["is_authenticated"])


# -------------------------------------------------------------------- click/

class ClickTests(ApiTestCase):
    def setUp(self):
        super().setUp()
        self.creator = f.make_creator(code="TORA20")

    def post(self, code, client=None, **headers):
        return (client or self.client_for()).post(API + "click/", {"code": code},
                                                  format="json", **headers)

    def test_known_code_writes_one_click_per_device(self):
        response = self.post("tora20", HTTP_X_DEVICE_KEY="device-1")
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data, {"ok": True})
        self.post("TORA20", HTTP_X_DEVICE_KEY="device-1")
        self.assertEqual(CreatorClick.objects.filter(creator=self.creator).count(), 1)
        self.post("TORA20", HTTP_X_DEVICE_KEY="device-2")
        self.assertEqual(CreatorClick.objects.filter(creator=self.creator).count(), 2)

    def test_answer_is_the_same_for_any_code(self):
        # По ответу нельзя понять, существует ли код.
        for code in ("NOSUCHCODE", "", None, "!!", {"a": 1}):
            response = self.post(code, HTTP_X_DEVICE_KEY="device-1")
            self.assertEqual(response.status_code, 200, response.data)
            self.assertEqual(response.data, {"ok": True})
        self.assertEqual(CreatorClick.objects.count(), 0)

    def test_body_that_is_not_an_object(self):
        response = self.client_for().post(API + "click/", ["TORA20"], format="json")
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data, {"ok": True})

    def test_own_click_is_not_counted(self):
        response = self.post("TORA20", self.client_for(self.creator.user),
                             HTTP_X_DEVICE_KEY="device-1")
        self.assertEqual(response.data, {"ok": True})
        self.assertEqual(CreatorClick.objects.count(), 0)

    @override_settings(CREATORS_MODE="off")
    def test_off_mode_is_404(self):
        self.assertError(self.post("TORA20", HTTP_X_DEVICE_KEY="device-1"), 404, "disabled")
        self.assertEqual(CreatorClick.objects.count(), 0)

    @override_settings(CREATORS_MODE="staff")
    def test_staff_mode_counts_clicks_of_ordinary_visitors(self):
        # Приглашённые — обычные люди: в режиме staff они не сотрудники.
        staff_creator = f.make_creator(f.make_user(staff=True), code="STAFF01")
        self.assertEqual(self.post("STAFF01", HTTP_X_DEVICE_KEY="d1").status_code, 200)
        self.assertEqual(CreatorClick.objects.filter(creator=staff_creator).count(), 1)
        # Креатор-не-сотрудник в этом режиме не участвует: ответ тот же, строки нет.
        self.assertEqual(self.post("TORA20", HTTP_X_DEVICE_KEY="d1").data, {"ok": True})
        self.assertEqual(CreatorClick.objects.filter(creator=self.creator).count(), 0)

    def test_throttle_scope_is_set(self):
        self.assertEqual(views.ClickView.scopes, {"POST": "creators_click"})
        self.assertTrue(views.ClickView.keep_anon_throttle)
        from django.conf import settings

        rates = settings.REST_FRAMEWORK["DEFAULT_THROTTLE_RATES"]
        for scope in ("creators_click", "creators_apply", "creators_write"):
            self.assertIn(scope, rates)

    def test_click_keeps_the_anonymous_limit_next_to_its_own(self):
        # Свой лимит считает по scope, общий анонимный — по IP: гостей держат оба.
        view = views.ClickView()
        view.request = SimpleNamespace(method="POST")
        throttles = view.get_throttles()
        self.assertEqual([type(t) for t in throttles], [ScopedRateThrottle, AnonRateThrottle])
        self.assertEqual(view.throttle_scope, "creators_click")

    def test_anonymous_click_is_also_throttled_by_the_anon_rate(self):
        rates = dict(AnonRateThrottle.THROTTLE_RATES, anon="2/min")
        with patch.object(AnonRateThrottle, "THROTTLE_RATES", rates):
            self.assertEqual(self.post("TORA20", HTTP_X_DEVICE_KEY="a").status_code, 200)
            self.assertEqual(self.post("TORA20", HTTP_X_DEVICE_KEY="b").status_code, 200)
            response = self.post("TORA20", HTTP_X_DEVICE_KEY="c")
        self.assertEqual(response.status_code, 429, response.data)
        self.assertEqual(CreatorClick.objects.count(), 2)

    def test_click_is_throttled_by_its_own_scope(self):
        rates = dict(ScopedRateThrottle.THROTTLE_RATES, creators_click="2/min")
        with patch.object(ScopedRateThrottle, "THROTTLE_RATES", rates):
            self.assertEqual(self.post("TORA20", HTTP_X_DEVICE_KEY="a").status_code, 200)
            self.assertEqual(self.post("TORA20", HTTP_X_DEVICE_KEY="b").status_code, 200)
            response = self.post("TORA20", HTTP_X_DEVICE_KEY="c")
        self.assertEqual(response.status_code, 429, response.data)
        self.assertEqual(response.data["code"], "throttled")
        self.assertEqual(CreatorClick.objects.count(), 2)


# ------------------------------------------------------------------- invite/

class InviteTests(ApiTestCase):
    def setUp(self):
        super().setUp()
        self.creator = f.make_creator(code="TORA20", display_name="Tora")

    def test_bound_user_sees_creator_name_and_code(self):
        user = f.make_user()
        referral = f.make_referral(self.creator, user)
        response = self.client_for(user).get(API + "invite/")
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(set(response.data), {"invited_by", "code", "bound_at"})
        self.assertEqual(response.data["invited_by"], "Tora")
        self.assertEqual(response.data["code"], "TORA20")
        self.assertEqual(response.data["bound_at"], referral.bound_at)

    def test_unbound_user_gets_nulls(self):
        response = self.client_for(f.make_user()).get(API + "invite/")
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data, {"invited_by": None, "code": None, "bound_at": None})

    def test_admin_binding_has_no_code(self):
        user = f.make_user()
        f.make_referral(self.creator, user, source="admin")
        response = self.client_for(user).get(API + "invite/")
        self.assertEqual(response.data["invited_by"], "Tora")
        self.assertIsNone(response.data["code"])

    def test_ended_binding_is_not_shown(self):
        user = f.make_user()
        referral = f.make_referral(self.creator, user)
        type(referral).objects.filter(pk=referral.pk).update(
            ended_at=referral.bound_at, end_reason="admin_unbind")
        self.assertIsNone(self.client_for(user).get(API + "invite/").data["invited_by"])

    def test_read_only(self):
        user = f.make_user()
        self.assertEqual(self.client_for(user).post(API + "invite/", {}).status_code, 405)

    @override_settings(CREATORS_MODE="off")
    def test_off_mode_is_404(self):
        user = f.make_user()
        f.make_referral(self.creator, user)
        self.assertError(self.client_for(user).get(API + "invite/"), 404, "disabled")
