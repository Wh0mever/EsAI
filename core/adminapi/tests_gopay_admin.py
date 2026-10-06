# -*- coding: utf-8 -*-
"""Единый QR (GoPay) в админ-панели: настройки, проверка ключей, платежи, выручка.

Ни один тест не ходит в сеть: подменяется payments.gopay.client.requests.post.
Ключи — заведомые пустышки. Главное, что здесь проверяется: секрет нельзя
прочитать обратно ни из одного ответа и ни из журнала; менять ключи может
только главный администратор; отказ не оставляет после себя половину
настроек; ручные кнопки (перепроверить, отметить возврат) не начисляют
лишнего и не зависят от того, отвечает ли GoPay.
"""
import json
from datetime import timedelta
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import patch

import requests
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.db import connection
from django.test import TestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.utils import timezone
from rest_framework.test import APIClient

from adminapi.models import AppSetting
from adminapi.runtime import KEYS, get_runtime, set_runtime
from audit.metrics import collect_dashboard_metrics
from audit.models import AdminActionLog
from payments.gopay import config as gopay_config
from payments.gopay import service as gopay_service
from payments.models import CryptoInvoice, GoPayInvoice, Payment
from plans.models import TokenTransaction

TEST_CACHES = {"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache",
                           "LOCATION": "adminapi-gopay-tests"}}

# Заведомые пустышки: настоящих ключей в тестах не бывает.
API_KEY = "dummy-api-key-not-real"
API_SECRET = "dummy-api-secret-not-real"
WEBHOOK_SECRET = "dummy-webhook-secret-not-real"
LIVE_API_KEY = "dummy-live-api-key-not-L1VE"
LIVE_API_SECRET = "dummy-live-api-secret-not-real"
LIVE_WEBHOOK_SECRET = "dummy-live-webhook-secret-not-real"
OTHER_SECRET = "dummy-rotated-secret-not-real"
ALL_SECRETS = (API_KEY, API_SECRET, WEBHOOK_SECRET, LIVE_API_KEY, LIVE_API_SECRET,
               LIVE_WEBHOOK_SECRET, OTHER_SECRET)

BASE = "https://api.gopay.kg"
PID = "a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4"
ORDER = "tokpkg-7-3-0a1b2c3d4e"

SETTINGS_URL = "/api/manage/settings/"
TEST_URL = "/api/manage/settings/test-gopay/"
PAYMENTS_URL = "/api/manage/payments/"
SUMMARY_URL = "/api/manage/summary/"

IP_HINT = "Проверьте также ограничение по IP для боевого ключа в кабинете GoPay."

GOPAY_BLOCK_KEYS = {
    "mode", "env", "lifetime_minutes", "send_buyer_email", "configured", "effective",
    "webhook_url", "webhook_events", "webhook_events_optional", "api_host", "test", "live",
    "health", "in_flight", "unsettled",
}

# Состояние «как после выкладки»: режим «сотрудникам», тестовая среда, ключей нет.
SHIPPED = dict(
    CACHES=TEST_CACHES,
    GOPAY_API_URL=BASE, GOPAY_MODE="staff", GOPAY_ENV="test",
    GOPAY_LIFETIME_MINUTES=15, GOPAY_SEND_BUYER_EMAIL=True,
    GOPAY_TEST_API_KEY="", GOPAY_TEST_API_SECRET="", GOPAY_TEST_WEBHOOK_SECRET="",
    GOPAY_LIVE_API_KEY="", GOPAY_LIVE_API_SECRET="", GOPAY_LIVE_WEBHOOK_SECRET="",
    SITE_BASE_URL="https://esai.test",
)


# ----------------------------------------------------------- заглушки ---

class FakeResponse:
    def __init__(self, status_code=200, payload=None, text=None):
        self.status_code = status_code
        self._payload = payload
        self.text = text if text is not None else json.dumps(payload)

    def json(self):
        if self._payload is None:
            raise ValueError("not json")
        return self._payload


def ok(data, code="0000"):
    return FakeResponse(200, {"status": "OK", "code": code, "data": data})


def fail(code, message="", http=200):
    return FakeResponse(http, {"status": "FAIL", "code": code, "error_message": message})


def html(status):
    return FakeResponse(status, None, text="<html><body>nope</body></html>")


class FakeGoPay:
    """GoPay, который отвечает то, что ему велели, и помнит каждый запрос."""

    def __init__(self):
        self.calls = []
        self.routes = {}
        self.before_call = None

    def on(self, path, *responses):
        self.routes[path] = list(responses)
        return self

    def __call__(self, url, data=None, headers=None, timeout=None, **kwargs):
        path = url[len(BASE):] if url.startswith(BASE) else url
        try:
            body = json.loads(data)
        except Exception:
            body = None
        call = SimpleNamespace(url=url, path=path, headers=headers or {}, body=body)
        if self.before_call is not None:
            self.before_call(call)
        self.calls.append(call)
        queue = self.routes.get(path)
        if not queue:
            raise AssertionError(f"неожиданный запрос к GoPay: {path}")
        item = queue.pop(0) if len(queue) > 1 else queue[0]
        if isinstance(item, Exception):
            raise item
        return item

    def paths(self):
        return [c.path for c in self.calls]


def pay_data(**over):
    data = {
        "payment_id": PID, "order_id": ORDER, "amount": "392.00", "status": "CREATED",
        "created_at": "2026-10-06T10:00:00", "expires_at": "2026-10-06T10:15:00",
        "committed_at": None, "bank_op_date": None,
    }
    data.update(over)
    return data


@override_settings(**SHIPPED)
class GoPayAdminTestCase(TestCase):
    """Общее: чистый кэш, подменённый HTTP, три роли и фабрики платежа/счёта."""

    def setUp(self):
        # Настройки из админки кэшируются на 30 с, а кэш между тестами общий.
        cache.clear()
        self.addCleanup(cache.clear)
        self.fake = FakeGoPay()
        patcher = patch("payments.gopay.client.requests.post", side_effect=self.fake)
        self.post = patcher.start()
        self.addCleanup(patcher.stop)

        users = get_user_model().objects
        self.buyer = users.create_user(email="buyer@example.com", password="x-pass-123")
        self.staff_user = users.create_user(email="staff@example.com", password="x-pass-123",
                                            is_staff=True)
        self.owner = users.create_user(email="owner@example.com", password="x-pass-123",
                                       is_staff=True, is_superuser=True)
        self.anon = APIClient()
        self.user_client = APIClient()
        self.user_client.force_authenticate(self.buyer)
        self.staff = APIClient()
        self.staff.force_authenticate(self.staff_user)
        self.su = APIClient()
        self.su.force_authenticate(self.owner)
        self._seq = 0

    # --- настройки ---

    def set_keys(self, env, *, webhook=True):
        values = ((API_KEY, API_SECRET, WEBHOOK_SECRET) if env == "test"
                  else (LIVE_API_KEY, LIVE_API_SECRET, LIVE_WEBHOOK_SECRET))
        set_runtime(gopay_config.runtime_key(env, "api_key"), values[0])
        set_runtime(gopay_config.runtime_key(env, "api_secret"), values[1])
        if webhook:
            set_runtime(gopay_config.runtime_key(env, "webhook_secret"), values[2])

    def patch_gopay(self, body, client=None):
        return (client or self.su).patch(SETTINGS_URL, {"gopay": body}, format="json")

    def snapshot(self, client=None):
        response = (client or self.su).get(SETTINGS_URL)
        self.assertEqual(response.status_code, 200)
        return response.data["gopay"]

    def stored(self, key):
        row = AppSetting.objects.filter(key=key).first()
        return None if row is None else row.value

    def gopay_rows(self):
        return set(AppSetting.objects.filter(key__istartswith="gopay").values_list("key", flat=True))

    def edits(self):
        return AdminActionLog.objects.filter(action="settings.edit")

    def assert_no_secrets(self, response):
        text = response.content.decode("utf-8")
        for secret in ALL_SECRETS:
            self.assertNotIn(secret, text)

    # --- платежи ---

    def make_payment(self, env="live", user=..., amount="392.00", provider="gopay", **over):
        self._seq += 1
        if user is ...:
            user = self.staff_user if env == "test" else self.buyer
        request = {
            "provider": "gopay", "pay_method": "elqr",
            "token_purchase": {"package_id": 3, "tokens": 500, "bonus_tokens": 0},
            "return_to": "/profile",
            "gopay": {"env": env, "lifetime": 900, "package_name": "Про"},
        }
        fields = dict(
            user=user, provider=provider, amount=Decimal(amount), currency="KGS",
            order_id=f"tokpkg-7-3-{self._seq:010x}", description="Token package purchase #3 (qr)",
            is_test=(env == "test"), request=request, response={})
        fields.update(over)
        return Payment.objects.create(**fields)

    def make_invoice(self, payment=None, env="live", **over):
        payment = payment or self.make_payment(env=env)
        fields = dict(
            payment=payment, env=env, provider_payment_id=f"{payment.pk:032x}", status="created",
            amount=payment.amount, lifetime_seconds=900, qr_data="https://pay.payqr.kg#0002",
            expires_at=timezone.now() + timedelta(minutes=15))
        fields.update(over)
        return GoPayInvoice.objects.create(**fields)

    def state_for(self, invoice, **over):
        """Ответ GoPay про этот счёт: номера и сумма сходятся, среда — счёта."""
        data = pay_data(payment_id=invoice.provider_payment_id,
                        order_id=invoice.payment.order_id,
                        amount=format(invoice.amount, ".2f"))
        if invoice.env == "test":
            data["testing_mode"] = True
        data.update(over)
        return data

    def balance(self, user=None):
        user = user or self.buyer
        user.refresh_from_db()
        return int(user.token_balance or 0)

    def ledger(self, user=None):
        return TokenTransaction.objects.filter(user=user or self.buyer, reason="purchase").count()


# ============================================================ снимок ===

class SnapshotTests(GoPayAdminTestCase):
    def test_runtime_keys_are_registered(self):
        for key in ("gopay_mode", "gopay_env", "gopay_lifetime_minutes", "gopay_send_buyer_email",
                    "GOPAY_TEST_API_KEY", "GOPAY_TEST_API_SECRET", "GOPAY_TEST_WEBHOOK_SECRET",
                    "GOPAY_LIVE_API_KEY", "GOPAY_LIVE_API_SECRET", "GOPAY_LIVE_WEBHOOK_SECRET"):
            self.assertIn(key, KEYS)
        # Имена ключей — те самые, что читает модуль настроек GoPay.
        for env in gopay_config.ENVS:
            for field in gopay_config.SECRET_FIELDS:
                self.assertIn(gopay_config.runtime_key(env, field), KEYS)
        for key in (gopay_config.RT_MODE, gopay_config.RT_ENV, gopay_config.RT_LIFETIME,
                    gopay_config.RT_SEND_BUYER_EMAIL):
            self.assertIn(key, KEYS)

    def test_shipped_block_has_the_exact_shape(self):
        block = self.snapshot()
        self.assertEqual(set(block), GOPAY_BLOCK_KEYS)
        self.assertEqual((block["mode"], block["env"], block["lifetime_minutes"],
                          block["send_buyer_email"]), ("staff", "test", 15, True))
        self.assertFalse(block["configured"])
        self.assertEqual(block["effective"], {"public": False, "staff": False})
        self.assertEqual(block["webhook_url"], "https://esai.test/api/payments/gopay/webhook/")
        self.assertEqual(block["webhook_events"], ["payment.committed", "payment.failed",
                                                   "payment.expired", "payment.cancelled"])
        self.assertEqual(block["webhook_events_optional"], ["receipt.sent"])
        self.assertEqual(block["api_host"], "api.gopay.kg")
        empty = {"api_key_set": False, "api_key_tail": "", "api_secret_set": False,
                 "webhook_secret_set": False}
        self.assertEqual(block["test"], empty)
        self.assertEqual(block["live"], empty)
        healthy = {"ok": True, "fails": 0, "kind": "", "code": "", "since": None, "down": False}
        self.assertEqual(block["health"], {"test": healthy, "live": healthy})
        self.assertEqual(block["in_flight"], {"test": 0, "live": 0})
        self.assertEqual(block["unsettled"], 0)

    def test_any_staff_reads_the_block_but_outsiders_do_not(self):
        self.assertEqual(set(self.snapshot(self.staff)), GOPAY_BLOCK_KEYS)
        self.assertEqual(self.user_client.get(SETTINGS_URL).status_code, 403)
        self.assertEqual(self.anon.get(SETTINGS_URL).status_code, 401)

    def test_secrets_never_leave_whether_typed_in_admin_or_set_in_env(self):
        self.set_keys("test")
        with self.settings(GOPAY_LIVE_API_KEY=LIVE_API_KEY, GOPAY_LIVE_API_SECRET=LIVE_API_SECRET,
                           GOPAY_LIVE_WEBHOOK_SECRET=LIVE_WEBHOOK_SECRET):
            response = self.su.get(SETTINGS_URL)
            self.assert_no_secrets(response)
            block = response.data["gopay"]
            self.assertEqual(block["test"], {"api_key_set": True, "api_key_tail": "…real",
                                             "api_secret_set": True, "webhook_secret_set": True})
            self.assertEqual(block["live"], {"api_key_set": True, "api_key_tail": "…L1VE",
                                             "api_secret_set": True, "webhook_secret_set": True})
            self.assertTrue(block["configured"])
            self.assertEqual(block["effective"], {"public": False, "staff": True})

    def test_live_counters_are_shown(self):
        self.make_invoice(env="live")                               # открыт
        paid = self.make_invoice(env="live", status="committed")    # оплачен, не зачислен
        gopay_service.note_result("live", gopay_service.GoPayUnavailable("x", code="network"))
        block = self.snapshot()
        self.assertEqual(block["in_flight"], {"test": 0, "live": 2})
        self.assertEqual(block["unsettled"], 1)
        self.assertFalse(block["health"]["live"]["ok"])
        self.assertEqual((block["health"]["live"]["kind"], block["health"]["live"]["fails"]),
                         ("unavailable", 1))
        self.assertTrue(block["health"]["test"]["ok"])
        # Отмеченный возврат убирает платёж из «оплачено, не зачислено».
        paid.payment.response = {"admin_refund": {"kind": "refund"}}
        paid.payment.save(update_fields=["response"])
        self.assertEqual(self.snapshot()["unsettled"], 0)

    def test_page_opens_when_the_live_part_fails(self):
        with patch("payments.gopay.service.admin_state", side_effect=RuntimeError("db down")):
            block = self.snapshot()
        # Трёх «живых» ключей просто нет, остальное на месте.
        self.assertEqual(set(block), GOPAY_BLOCK_KEYS - {"health", "in_flight", "unsettled"})

    def test_kgs_methods_line_is_not_affected(self):
        before = self.su.get(SETTINGS_URL).data["kgs_methods_enabled"]
        self.set_keys("test")
        response = self.patch_gopay({"mode": "on", "lifetime_minutes": 20})
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["kgs_methods_enabled"], before)
        self.assertNotIn("elqr", response.data["kgs_methods_enabled"].split(","))
        self.assertEqual(get_runtime("kgs_methods_enabled", "unset"), "unset")


# ====================================================== запись настроек ===

class PatchPermissionTests(GoPayAdminTestCase):
    def test_staff_who_is_not_the_owner_cannot_change_anything(self):
        for body in ({"mode": "off"}, {"lifetime_minutes": 30}, {"test": {"api_key": API_KEY}},
                     {}, "junk", None):
            with self.subTest(body=body):
                response = self.patch_gopay(body, client=self.staff)
                self.assertEqual(response.status_code, 403)
                self.assertEqual(response.data["code"], "superuser_required")
                self.assertEqual(response.data["detail"],
                                 "Это действие доступно только главному администратору")
        self.assertEqual(self.gopay_rows(), set())
        self.assertFalse(self.edits().exists())

    def test_refusal_comes_before_any_other_field_is_written(self):
        response = self.staff.patch(
            SETTINGS_URL, {"referral_percent": 77, "kgs_methods_mode": "off",
                           "gopay": {"mode": "on"}}, format="json")
        self.assertEqual(response.status_code, 403)
        self.assertEqual(get_runtime("REFERRAL_PERCENT", -1), -1)
        self.assertEqual(get_runtime("kgs_methods_mode", "unset"), "unset")

    def test_staff_still_saves_other_settings(self):
        response = self.staff.patch(SETTINGS_URL, {"referral_percent": 12}, format="json")
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["referral_percent"], 12)

    def test_outsiders_are_refused(self):
        self.assertEqual(self.patch_gopay({"mode": "off"}, client=self.user_client).status_code, 403)
        self.assertEqual(self.patch_gopay({"mode": "off"}, client=self.anon).status_code, 401)
        self.assertEqual(self.gopay_rows(), set())


class PatchValidationTests(GoPayAdminTestCase):
    def assert_bad(self, body, contains="gopay"):
        response = self.patch_gopay(body)
        self.assertEqual(response.status_code, 400, response.data)
        self.assertIn(contains, response.data["detail"])
        return response

    def test_block_must_be_an_object_with_known_keys(self):
        for body in ("on", 1, None, ["mode"], True):
            with self.subTest(body=body):
                self.assert_bad(body)
        self.assert_bad({"mode": "off", "api_url": "https://evil.example"}, "неизвестное поле")
        self.assert_bad({"callback_url": "x"}, "неизвестное поле")
        self.assert_bad({"test": {"api_key": API_KEY, "url": "x"}}, "неизвестное поле")
        self.assert_bad({"live": {"secret": API_SECRET}}, "неизвестное поле")
        self.assertEqual(self.gopay_rows(), set())

    def test_mode_and_env(self):
        self.set_keys("test")
        self.set_keys("live")
        for bad in (True, 1, None, "", "everyone", ["on"]):
            with self.subTest(mode=bad):
                self.assert_bad({"mode": bad}, "mode")
        for bad in (True, 0, None, "", "prod", "sandbox"):
            with self.subTest(env=bad):
                self.assert_bad({"env": bad}, "env")
        self.assertIsNone(self.stored("gopay_mode"))
        self.assertIsNone(self.stored("gopay_env"))

        response = self.patch_gopay({"mode": " ON ", "env": "live"})
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual((response.data["gopay"]["mode"], response.data["gopay"]["env"]),
                         ("on", "live"))
        self.assertEqual((gopay_config.mode(), gopay_config.env()), ("on", "live"))
        self.assertEqual(response.data["gopay"]["effective"], {"public": True, "staff": True})

    def test_lifetime(self):
        for bad in (True, False, 4, 1441, 0, -5, "20", 20.5, None, [20]):
            with self.subTest(lifetime=bad):
                self.assert_bad({"lifetime_minutes": bad}, "lifetime_minutes")
        self.assertIsNone(self.stored("gopay_lifetime_minutes"))
        for good in (5, 1440, 20):
            response = self.patch_gopay({"lifetime_minutes": good})
            self.assertEqual(response.status_code, 200, response.data)
            self.assertEqual(response.data["gopay"]["lifetime_minutes"], good)
            self.assertEqual(gopay_config.lifetime_seconds(), good * 60)

    def test_switches_are_booleans_only(self):
        for bad in ("false", "true", 0, 1, None, "off"):
            with self.subTest(value=bad):
                self.assert_bad({"send_buyer_email": bad}, "send_buyer_email")
                self.assert_bad({"lifetime_minutes": 20, "force": bad}, "force")
        self.assertEqual(self.gopay_rows(), set())

        response = self.patch_gopay({"send_buyer_email": False})
        self.assertEqual(response.status_code, 200, response.data)
        self.assertIs(response.data["gopay"]["send_buyer_email"], False)
        self.assertIs(gopay_config.send_buyer_email(), False)
        response = self.patch_gopay({"send_buyer_email": True})
        self.assertIs(response.data["gopay"]["send_buyer_email"], True)
        self.assertIs(gopay_config.send_buyer_email(), True)

    def test_secret_fields(self):
        spaced = "dummy secret with space"
        short = "dummy-7"
        self.assertEqual(len(short), 7)
        for env in ("test", "live"):
            for field in ("api_key", "api_secret", "webhook_secret"):
                for bad in (spaced, short, "x" * 257, "ключ-кириллицей", 12345678, None, True,
                            ["dummy-list-value"]):
                    with self.subTest(env=env, field=field, value=bad):
                        response = self.assert_bad({env: {field: bad}}, f"{env}.{field}")
                        # Отказ называет поле, но значения не повторяет.
                        if isinstance(bad, str):
                            self.assertNotIn(bad, response.content.decode("utf-8"))
        for bad in ("keys", None, [API_KEY], True):
            with self.subTest(block=bad):
                self.assert_bad({"test": bad}, "test")
                self.assert_bad({"live": bad}, "live")
        self.assertEqual(self.gopay_rows(), set())

    def test_surrounding_spaces_are_trimmed(self):
        response = self.patch_gopay({"test": {"api_key": f"  {API_KEY}\n"}})
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(self.stored("GOPAY_TEST_API_KEY"), API_KEY)

    def test_all_or_nothing(self):
        self.set_keys("test")
        response = self.patch_gopay({
            "mode": "off", "env": "test", "lifetime_minutes": 30, "send_buyer_email": False,
            "test": {"webhook_secret": OTHER_SECRET},
            "live": {"api_key": LIVE_API_KEY, "api_secret": "bad secret"}})
        self.assertEqual(response.status_code, 400)
        self.assertIn("live.api_secret", response.data["detail"])
        self.assertEqual(gopay_config.mode(), "staff")
        self.assertEqual(gopay_config.lifetime_minutes(), 15)
        self.assertIs(gopay_config.send_buyer_email(), True)
        self.assertEqual(self.stored("GOPAY_TEST_WEBHOOK_SECRET"), WEBHOOK_SECRET)
        self.assertEqual(self.gopay_rows(), {"GOPAY_TEST_API_KEY", "GOPAY_TEST_API_SECRET",
                                             "GOPAY_TEST_WEBHOOK_SECRET"})
        self.assertFalse(self.edits().exists())

    def test_force_alone_or_an_empty_block_changes_nothing(self):
        for body in ({}, {"force": True}):
            response = self.patch_gopay(body)
            self.assertEqual(response.status_code, 200, response.data)
            self.assertEqual(set(response.data["gopay"]), GOPAY_BLOCK_KEYS)
        self.assertEqual(self.gopay_rows(), set())
        self.assertFalse(self.edits().exists())
        # force — подтверждение, а не настройка: в базу он не попадает.
        self.patch_gopay({"lifetime_minutes": 20, "force": True})
        self.assertEqual(self.gopay_rows(), {"gopay_lifetime_minutes"})


class KeyPresenceTests(GoPayAdminTestCase):
    def test_first_save_may_be_the_live_pair_while_env_is_still_test(self):
        response = self.patch_gopay({"live": {"api_key": LIVE_API_KEY,
                                              "api_secret": LIVE_API_SECRET}})
        self.assertEqual(response.status_code, 200, response.data)
        self.assert_no_secrets(response)
        block = response.data["gopay"]
        self.assertEqual(block["live"], {"api_key_set": True, "api_key_tail": "…L1VE",
                                         "api_secret_set": True, "webhook_secret_set": False})
        self.assertEqual((block["mode"], block["env"], block["configured"]),
                         ("staff", "test", False))
        # Видимым такое сохранение ничего не делает.
        self.assertEqual(block["effective"], {"public": False, "staff": False})
        self.assertEqual(self.stored("GOPAY_LIVE_API_KEY"), LIVE_API_KEY)
        self.assertEqual(self.stored("GOPAY_LIVE_API_SECRET"), LIVE_API_SECRET)

    def test_plain_settings_are_always_accepted(self):
        self.assertEqual(self.patch_gopay({"lifetime_minutes": 20}).status_code, 200)
        self.assertEqual(self.patch_gopay({"send_buyer_email": False}).status_code, 200)
        self.assertEqual(self.patch_gopay({"test": {"webhook_secret": WEBHOOK_SECRET}}).status_code,
                         200)

    def test_switching_env_needs_the_keys_of_that_env(self):
        self.set_keys("test")
        response = self.patch_gopay({"env": "live"})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data["detail"],
                         "gopay: сначала введите API-ключ и секрет для выбранной среды")
        self.assertEqual(gopay_config.env(), "test")
        # Половины пары мало.
        response = self.patch_gopay({"env": "live", "live": {"api_key": LIVE_API_KEY}})
        self.assertEqual(response.status_code, 400)
        self.assertIsNone(self.stored("GOPAY_LIVE_API_KEY"))
        # Пара в том же запросе — можно.
        response = self.patch_gopay({"env": "live", "live": {"api_key": LIVE_API_KEY,
                                                             "api_secret": LIVE_API_SECRET}})
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(gopay_config.env(), "live")
        self.assertTrue(response.data["gopay"]["configured"])

    def test_env_is_checked_even_when_the_value_is_the_stored_one(self):
        response = self.patch_gopay({"env": "test"})
        self.assertEqual(response.status_code, 400)
        self.assertIn("сначала введите", response.data["detail"])

    def test_staff_mode_needs_keys_of_the_active_env(self):
        response = self.patch_gopay({"mode": "staff"})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data["detail"],
                         "gopay: сначала введите API-ключ и секрет для выбранной среды")
        # Ключи есть только у другой среды — это не считается.
        self.set_keys("live")
        self.assertEqual(self.patch_gopay({"mode": "staff"}).status_code, 400)
        self.set_keys("test", webhook=False)
        self.assertEqual(self.patch_gopay({"mode": "staff"}).status_code, 200)

    def test_public_mode_needs_the_webhook_secret(self):
        self.set_keys("test", webhook=False)
        response = self.patch_gopay({"mode": "on"})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data["detail"],
                         "gopay: для режима «Включено» нужен секрет вебхуков")
        self.assertEqual(gopay_config.mode(), "staff")
        response = self.patch_gopay({"mode": "on", "test": {"webhook_secret": WEBHOOK_SECRET}})
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(gopay_config.mode(), "on")

    def test_switching_env_under_public_mode_needs_its_webhook_secret(self):
        self.set_keys("test")
        self.set_keys("live", webhook=False)
        self.assertEqual(self.patch_gopay({"mode": "on"}).status_code, 200)
        response = self.patch_gopay({"env": "live"})
        self.assertEqual(response.status_code, 400)
        self.assertIn("секрет вебхуков", response.data["detail"])
        self.assertEqual(gopay_config.env(), "test")

    def test_turning_off_never_needs_keys(self):
        response = self.patch_gopay({"mode": "off"})
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["gopay"]["mode"], "off")
        # С выключенным режимом среду можно переключить и без ключей.
        self.assertEqual(self.patch_gopay({"env": "live"}).status_code, 200)
        self.assertEqual(self.patch_gopay({"mode": "off", "env": "test"}).status_code, 200)

    def test_keys_from_the_environment_count(self):
        with self.settings(GOPAY_LIVE_API_KEY=LIVE_API_KEY, GOPAY_LIVE_API_SECRET=LIVE_API_SECRET):
            self.assertEqual(self.patch_gopay({"env": "live"}).status_code, 200)
            self.assertEqual(self.gopay_rows(), {"gopay_env"})

    def test_deleting_a_key_in_the_same_request_is_seen_by_the_check(self):
        self.set_keys("test")
        response = self.patch_gopay({"mode": "staff", "test": {"api_secret": ""}})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(self.stored("GOPAY_TEST_API_SECRET"), API_SECRET)
        # Удалённое из админки значение заменяет ключ из окружения — он и считается.
        with self.settings(GOPAY_TEST_API_SECRET=OTHER_SECRET):
            response = self.patch_gopay({"mode": "staff", "test": {"api_secret": ""}})
            self.assertEqual(response.status_code, 200, response.data)
            self.assertIsNone(self.stored("GOPAY_TEST_API_SECRET"))
            self.assertTrue(response.data["gopay"]["test"]["api_secret_set"])

    def test_same_key_in_both_envs_is_refused(self):
        self.set_keys("test")
        response = self.patch_gopay({"live": {"api_key": API_KEY, "api_secret": LIVE_API_SECRET}})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data["detail"], "gopay: ключи Test и Live совпадают")
        self.assert_no_secrets(response)
        self.assertIsNone(self.stored("GOPAY_LIVE_API_KEY"))
        self.assertIsNone(self.stored("GOPAY_LIVE_API_SECRET"))
        # Проверяется при любом сохранении блока, а не только при записи ключа.
        set_runtime("GOPAY_LIVE_API_KEY", API_KEY)
        self.assertEqual(self.patch_gopay({"lifetime_minutes": 20}).status_code, 400)
        # Исправить можно тем же запросом.
        response = self.patch_gopay({"lifetime_minutes": 20, "live": {"api_key": LIVE_API_KEY}})
        self.assertEqual(response.status_code, 200, response.data)

    def test_deleting_the_last_key_of_the_active_env_just_hides_the_qr(self):
        self.set_keys("test")
        self.assertEqual(self.snapshot()["effective"], {"public": False, "staff": True})
        response = self.patch_gopay({"test": {"api_secret": ""}})
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["gopay"]["effective"], {"public": False, "staff": False})
        self.assertFalse(response.data["gopay"]["configured"])


class CredentialsInUseTests(GoPayAdminTestCase):
    def setUp(self):
        super().setUp()
        self.set_keys("test")
        self.set_keys("live")

    def test_deleting_a_key_with_an_open_invoice_needs_confirmation(self):
        self.make_invoice(env="live")
        for field in ("api_key", "api_secret", "webhook_secret"):
            with self.subTest(field=field):
                response = self.patch_gopay({"mode": "off", "lifetime_minutes": 30,
                                             "live": {field: ""}})
                self.assertEqual(response.status_code, 409)
                self.assertEqual(response.data["code"], "gopay_in_flight")
                self.assertEqual(response.data["count"], 1)
                self.assertIn("незавершённые QR-счета (1)", response.data["detail"])
                self.assert_no_secrets(response)
        # Не записано ничего — ни ключ, ни соседние поля запроса.
        self.assertEqual(self.stored("GOPAY_LIVE_API_KEY"), LIVE_API_KEY)
        self.assertEqual(self.stored("GOPAY_LIVE_API_SECRET"), LIVE_API_SECRET)
        self.assertEqual(self.stored("GOPAY_LIVE_WEBHOOK_SECRET"), LIVE_WEBHOOK_SECRET)
        self.assertEqual(gopay_config.mode(), "staff")
        self.assertEqual(gopay_config.lifetime_minutes(), 15)
        self.assertFalse(self.edits().exists())
        # force: false — не подтверждение.
        self.assertEqual(self.patch_gopay({"live": {"api_secret": ""}, "force": False}).status_code,
                         409)

    def test_confirmed_deletion_goes_through_and_is_logged(self):
        self.make_invoice(env="live")
        self.make_invoice(env="live", status="pending")
        response = self.patch_gopay({"live": {"api_secret": ""}, "force": True})
        self.assertEqual(response.status_code, 200, response.data)
        self.assertIsNone(self.stored("GOPAY_LIVE_API_SECRET"))
        self.assertFalse(response.data["gopay"]["live"]["api_secret_set"])
        self.assertEqual(self.edits().get().after["gopay_in_flight"], {"live": 2})

    def test_other_env_is_not_held_by_these_invoices(self):
        self.make_invoice(env="live")
        response = self.patch_gopay({"test": {"api_secret": ""}})
        self.assertEqual(response.status_code, 200, response.data)
        self.assertIsNone(self.stored("GOPAY_TEST_API_SECRET"))
        self.assertNotIn("gopay_in_flight", self.edits().get().after)

    def test_invoice_closed_only_by_our_clock_still_holds_the_keys(self):
        now = timezone.now()
        self.make_invoice(env="live", status="expired", expires_at=now - timedelta(days=3),
                          finalized_at=now - timedelta(days=3), flags={"local_expiry": True})
        response = self.patch_gopay({"live": {"api_secret": ""}})
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.data["count"], 1)
        self.assertEqual(self.stored("GOPAY_LIVE_API_SECRET"), LIVE_API_SECRET)

    def test_paid_but_not_credited_invoice_holds_the_keys(self):
        self.make_invoice(env="live", status="committed",
                          finalized_at=timezone.now() - timedelta(days=30))
        self.assertEqual(self.patch_gopay({"live": {"api_key": ""}}).status_code, 409)

    def test_old_confirmed_closes_do_not_hold_the_keys(self):
        now = timezone.now()
        for status_ in ("cancelled", "expired", "failed"):
            self.make_invoice(env="live", status=status_, expires_at=now - timedelta(hours=8),
                              finalized_at=now - timedelta(hours=7))
        paid = self.make_payment(env="live", success=True,
                                 response={"token_purchase_applied": True})
        self.make_invoice(paid, env="live", status="committed")
        response = self.patch_gopay({"live": {"api_secret": ""}})
        self.assertEqual(response.status_code, 200, response.data)
        self.assertIsNone(self.stored("GOPAY_LIVE_API_SECRET"))
        self.assertNotIn("gopay_in_flight", self.edits().get().after)

    def test_recent_confirmed_close_holds_the_keys(self):
        now = timezone.now()
        self.make_invoice(env="live", status="cancelled", finalized_at=now - timedelta(hours=1))
        self.assertEqual(self.patch_gopay({"live": {"api_secret": ""}}).status_code, 409)

    def test_rotation_is_allowed_and_leaves_a_trace(self):
        self.make_invoice(env="live")
        response = self.patch_gopay({"live": {"api_secret": OTHER_SECRET}})
        self.assertEqual(response.status_code, 200, response.data)
        self.assert_no_secrets(response)
        self.assertEqual(self.stored("GOPAY_LIVE_API_SECRET"), OTHER_SECRET)
        self.assertEqual(self.edits().get().after["gopay_in_flight"], {"live": 1})

    def test_saving_the_same_value_is_not_a_rotation(self):
        self.make_invoice(env="live")
        response = self.patch_gopay({"live": {"api_secret": LIVE_API_SECRET}})
        self.assertEqual(response.status_code, 200, response.data)
        self.assertNotIn("gopay_in_flight", self.edits().get().after)

    def test_deleting_what_is_not_stored_is_not_a_deletion(self):
        # Строки в админке нет — удалять нечего, и счёта это не касается.
        AppSetting.objects.filter(key="GOPAY_LIVE_WEBHOOK_SECRET").delete()
        cache.clear()
        self.make_invoice(env="live")
        response = self.patch_gopay({"live": {"webhook_secret": ""}})
        self.assertEqual(response.status_code, 200, response.data)

    def test_empty_string_deletes_the_row_and_env_value_returns(self):
        with self.settings(GOPAY_TEST_API_KEY="dummy-env-api-key-ENV1"):
            self.assertEqual(self.snapshot()["test"]["api_key_tail"], "…real")
            response = self.patch_gopay({"test": {"api_key": ""}})
            self.assertEqual(response.status_code, 200, response.data)
            self.assertIsNone(self.stored("GOPAY_TEST_API_KEY"))
            self.assertEqual(response.data["gopay"]["test"]["api_key_tail"], "…ENV1")
            self.assertNotIn("dummy-env-api-key-ENV1", response.content.decode("utf-8"))


class AuditTests(GoPayAdminTestCase):
    def test_edit_is_logged_without_any_value(self):
        response = self.patch_gopay({
            "lifetime_minutes": 20, "send_buyer_email": False,
            "test": {"api_key": API_KEY, "api_secret": API_SECRET,
                     "webhook_secret": WEBHOOK_SECRET},
            "live": {"api_key": LIVE_API_KEY, "api_secret": LIVE_API_SECRET,
                     "webhook_secret": LIVE_WEBHOOK_SECRET}})
        self.assertEqual(response.status_code, 200, response.data)
        self.assert_no_secrets(response)
        log = self.edits().get()
        self.assertEqual(log.actor_id, self.owner.pk)
        self.assertEqual(set(log.before), {"gopay"})
        self.assertEqual(set(log.after), {"gopay"})
        self.assertFalse(log.before["gopay"]["test"]["api_key_set"])
        self.assertEqual(log.after["gopay"]["test"],
                         {"api_key_set": True, "api_key_tail": "…real", "api_secret_set": True,
                          "webhook_secret_set": True})
        self.assertEqual((log.before["gopay"]["lifetime_minutes"],
                          log.after["gopay"]["lifetime_minutes"]), (15, 20))
        self.assertEqual((log.before["gopay"]["send_buyer_email"],
                          log.after["gopay"]["send_buyer_email"]), (True, False))
        dump = json.dumps({"before": log.before, "after": log.after, "reason": log.reason},
                          ensure_ascii=False)
        for secret in ALL_SECRETS:
            self.assertNotIn(secret, dump)

    def test_rotation_and_deletion_are_logged_without_values(self):
        self.set_keys("test")
        self.patch_gopay({"test": {"api_secret": OTHER_SECRET}})
        self.patch_gopay({"test": {"webhook_secret": ""}})
        self.assertEqual(self.edits().count(), 2)
        for log in self.edits():
            dump = json.dumps([log.before, log.after], ensure_ascii=False)
            for secret in ALL_SECRETS:
                self.assertNotIn(secret, dump)
        last = self.edits().order_by("-id").first()
        self.assertTrue(last.before["gopay"]["test"]["webhook_secret_set"])
        self.assertFalse(last.after["gopay"]["test"]["webhook_secret_set"])

    def test_refused_request_writes_no_log(self):
        self.patch_gopay({"mode": "on"})
        self.patch_gopay({"lifetime_minutes": 1})
        self.patch_gopay({"mode": "off"}, client=self.staff)
        self.assertFalse(self.edits().exists())

    def test_settings_do_not_survive_a_failed_log(self):
        self.set_keys("test")
        client = APIClient(raise_request_exception=False)
        client.force_authenticate(self.owner)
        with patch("audit.services.log_admin_action", side_effect=RuntimeError("journal down")):
            response = client.patch(SETTINGS_URL, {"gopay": {
                "mode": "on", "test": {"api_secret": OTHER_SECRET}}}, format="json")
        self.assertEqual(response.status_code, 500)
        # Запрос откатился целиком, и в кэше не осталось несохранённых значений.
        self.assertIsNone(self.stored("gopay_mode"))
        self.assertEqual(self.stored("GOPAY_TEST_API_SECRET"), API_SECRET)
        self.assertEqual(gopay_config.mode(), "staff")
        self.assertEqual(gopay_config.credentials("test").api_secret, API_SECRET)

    def test_cache_is_dropped_again_after_commit(self):
        with self.captureOnCommitCallbacks(execute=False) as callbacks:
            self.assertEqual(self.patch_gopay({"lifetime_minutes": 20}).status_code, 200)
        self.assertEqual(len(callbacks), 1)
        # Сосед успел положить в кэш старое значение, пока запрос не был зафиксирован.
        cache.set("appset:gopay_lifetime_minutes", "15", 30)
        self.assertEqual(gopay_config.lifetime_minutes(), 15)
        callbacks[0]()
        self.assertEqual(gopay_config.lifetime_minutes(), 20)


# ================================================== проверка соединения ===

class TestConnectionTests(GoPayAdminTestCase):
    APPS = [{"code": "mbank", "name": "MBank", "order": 1, "url": "mbank://x?d={qr_data}"},
            {"code": "odengi", "name": "O!Dengi", "order": 2, "url": "odengi://x?d={qr_data}"}]

    def run_test(self, body=None, client=None):
        return (client or self.su).post(TEST_URL, body or {}, format="json")

    def test_not_configured_answers_without_http(self):
        response = self.run_test()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data, {
            "ok": False, "env": "test", "apps": None, "webhook_secret_set": False,
            "error": "Ключ и секрет для этой среды не заданы.", "provider_code": None})
        # Половина пары — тоже «не заданы»; секрет вебхуков виден отдельно.
        set_runtime("GOPAY_TEST_API_KEY", API_KEY)
        set_runtime("GOPAY_TEST_WEBHOOK_SECRET", WEBHOOK_SECRET)
        response = self.run_test()
        self.assertFalse(response.data["ok"])
        self.assertTrue(response.data["webhook_secret_set"])
        self.assertEqual(self.fake.calls, [])
        # Проверка без запроса «здоровье» GoPay не портит.
        self.assertTrue(gopay_service.health("test")["ok"])

    def test_success_counts_bank_apps(self):
        self.set_keys("test")
        self.fake.on("/v1/payment-app", ok(self.APPS))
        response = self.run_test()
        self.assertEqual(response.data, {
            "ok": True, "env": "test", "apps": 2, "webhook_secret_set": True,
            "error": None, "provider_code": None})
        self.assert_no_secrets(response)
        call = self.fake.calls[0]
        self.assertEqual((call.path, call.body), ("/v1/payment-app", {"platform": "any"}))
        self.assertEqual(call.headers["GoPay-Api-Key"], API_KEY)

    def test_empty_list_is_a_success(self):
        self.set_keys("test", webhook=False)
        self.fake.on("/v1/payment-app", ok([]))
        response = self.run_test()
        self.assertIs(response.data["ok"], True)
        self.assertEqual(response.data["apps"], 0)
        self.assertIsNone(response.data["error"])
        self.assertIs(response.data["webhook_secret_set"], False)

    def test_explicit_env_uses_the_keys_of_that_env(self):
        self.set_keys("test")
        self.set_keys("live")
        self.fake.on("/v1/payment-app", ok(self.APPS))
        response = self.run_test({"env": "live"})
        self.assertEqual((response.data["ok"], response.data["env"]), (True, "live"))
        self.assertEqual(self.fake.calls[-1].headers["GoPay-Api-Key"], LIVE_API_KEY)
        response = self.run_test({"env": "test"})
        self.assertEqual(response.data["env"], "test")
        self.assertEqual(self.fake.calls[-1].headers["GoPay-Api-Key"], API_KEY)
        # Без env — активная среда.
        set_runtime("gopay_env", "live")
        response = self.run_test()
        self.assertEqual(response.data["env"], "live")
        self.assertEqual(self.fake.calls[-1].headers["GoPay-Api-Key"], LIVE_API_KEY)

    def test_bad_env_is_refused(self):
        self.set_keys("test")
        for bad in ("prod", "", "LIVE", 1, True, ["live"], {"x": 1}):
            with self.subTest(env=bad):
                response = self.run_test({"env": bad})
                self.assertEqual(response.status_code, 400)
        self.assertEqual(self.fake.calls, [])

    def test_auth_failure_in_test_env_has_no_ip_hint(self):
        self.set_keys("test")
        for answer in (fail("4001", "Invalid signature"), fail("4002", "bad key"), html(401),
                       html(403), fail("7001", "wrong signature")):
            self.fake.on("/v1/payment-app", answer)
            response = self.run_test()
            self.assertEqual(response.status_code, 200)
            self.assertIs(response.data["ok"], False)
            self.assertIsNone(response.data["apps"])
            self.assertEqual(response.data["error"],
                             "GoPay не принял ключ или подпись. Проверьте API-ключ и секрет.")
        self.assert_no_secrets(response)

    def test_live_auth_or_unknown_failure_ends_with_the_ip_hint(self):
        self.set_keys("live")
        cases = (
            (fail("4001", "Invalid signature"),
             "GoPay не принял ключ или подпись. Проверьте API-ключ и секрет. " + IP_HINT, "4001"),
            (html(403),
             "GoPay не принял ключ или подпись. Проверьте API-ключ и секрет. " + IP_HINT, None),
            (fail("7777", "something new"), "GoPay отклонил запрос (код 7777). " + IP_HINT, "7777"),
            (html(404), "GoPay отклонил запрос (код 404). " + IP_HINT, None),
        )
        for answer, text, provider_code in cases:
            self.fake.on("/v1/payment-app", answer)
            response = self.run_test({"env": "live"})
            self.assertEqual(response.data["error"], text)
            self.assertTrue(response.data["error"].endswith(IP_HINT))
            self.assertEqual(response.data["provider_code"], provider_code)

    def test_unknown_failure_in_test_env_names_the_code_only(self):
        self.set_keys("test")
        self.fake.on("/v1/payment-app", fail("7777", "something new"))
        self.assertEqual(self.run_test().data["error"], "GoPay отклонил запрос (код 7777).")
        self.fake.on("/v1/payment-app", html(404))
        self.assertEqual(self.run_test().data["error"], "GoPay отклонил запрос (код 404).")
        self.fake.on("/v1/payment-app", fail("4003", "bad field", http=400))
        self.assertEqual(self.run_test().data["error"], "GoPay отклонил запрос (код 4003).")

    def test_known_refusals_have_their_own_text_and_no_ip_hint(self):
        self.set_keys("live")
        cases = (
            (fail("0016", "inactive"), "Организация в GoPay не активирована (код 0016)."),
            (fail("0004", "slow down"), "Лимит запросов GoPay, повторите через минуту."),
            (fail("4003", "bad field", http=400), "GoPay отклонил запрос (код 4003)."),
        )
        for answer, text in cases:
            self.fake.on("/v1/payment-app", answer)
            self.assertEqual(self.run_test({"env": "live"}).data["error"], text)

    def test_unavailable(self):
        self.set_keys("test")
        text = "GoPay не отвечает. Проверьте сеть сервера и ограничение по IP для боевого ключа."
        for answer in (requests.ConnectionError("refused"), requests.Timeout("slow"), html(502),
                       html(200), fail("9999", "internal")):
            self.fake.on("/v1/payment-app", answer)
            response = self.run_test()
            self.assertEqual(response.status_code, 200)
            self.assertIs(response.data["ok"], False)
            self.assertEqual(response.data["error"], text)

    def test_provider_text_and_our_keys_never_reach_the_answer(self):
        self.set_keys("test")
        self.fake.on("/v1/payment-app",
                     fail("7777", f"key {API_KEY} with secret {API_SECRET} is wrong"))
        response = self.run_test()
        self.assert_no_secrets(response)
        self.assertNotIn("is wrong", response.content.decode("utf-8"))

    def test_never_answers_5xx(self):
        self.set_keys("test")
        self.fake.on("/v1/payment-app", RuntimeError("unexpected"))
        response = self.run_test()
        self.assertEqual(response.status_code, 200)
        self.assertIs(response.data["ok"], False)
        with patch("payments.gopay.client.get_client", side_effect=RuntimeError("boom")):
            response = self.run_test()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data, {
            "ok": False, "env": "test", "apps": None, "webhook_secret_set": True,
            "error": "Не удалось выполнить проверку. Повторите позже.", "provider_code": None})
        with patch("payments.gopay.service.note_result", side_effect=RuntimeError("cache")):
            self.assertEqual(self.run_test().status_code, 200)

    def test_works_while_the_breaker_is_set_and_feeds_health(self):
        self.set_keys("test")
        down = gopay_service.GoPayUnavailable("x", code="network")
        for _ in range(gopay_service.DOWN_AFTER_FAILURES):
            gopay_service.note_result("test", down)
        self.assertTrue(gopay_service.provider_down("test"))
        self.assertFalse(self.snapshot()["health"]["test"]["ok"])

        self.fake.on("/v1/payment-app", ok(self.APPS))
        response = self.run_test()
        self.assertIs(response.data["ok"], True)
        self.assertEqual(len(self.fake.calls), 1)
        # Удачная проверка гасит и красную строку, и предохранитель.
        self.assertFalse(gopay_service.provider_down("test"))
        self.assertEqual(self.snapshot()["health"]["test"],
                         {"ok": True, "fails": 0, "kind": "", "code": "", "since": None,
                          "down": False})

    def test_failure_is_counted_in_health(self):
        self.set_keys("live")
        self.fake.on("/v1/payment-app", fail("4001", "Invalid signature"))
        self.run_test({"env": "live"})
        health = self.snapshot()["health"]
        self.assertEqual((health["live"]["ok"], health["live"]["kind"], health["live"]["fails"]),
                         (False, "auth", 1))
        self.assertTrue(health["test"]["ok"])
        # Отказ, который значит «GoPay жив и нас принял», сбоем не считается.
        self.fake.on("/v1/payment-app", fail("7777", "something new"))
        self.run_test({"env": "live"})
        self.assertTrue(self.snapshot()["health"]["live"]["ok"])

    def test_any_staff_may_run_it_but_not_outsiders(self):
        self.set_keys("test")
        self.fake.on("/v1/payment-app", ok([]))
        self.assertIs(self.run_test(client=self.staff).data["ok"], True)
        self.assertEqual(self.run_test(client=self.user_client).status_code, 403)
        self.assertEqual(self.run_test(client=self.anon).status_code, 401)
        self.assertEqual(len(self.fake.calls), 1)

    def test_get_is_not_allowed(self):
        self.assertEqual(self.su.get(TEST_URL).status_code, 405)


# ======================================================= список платежей ===

class PaymentsListTests(GoPayAdminTestCase):
    def ids(self, query):
        response = self.staff.get(PAYMENTS_URL + query)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["count"], len(response.data["results"]))
        return {row["id"] for row in response.data["results"]}

    def row(self, payment):
        response = self.staff.get(PAYMENTS_URL + f"?q={payment.order_id}")
        return response.data["results"][0]

    def crypto_invoice(self, payment, **over):
        fields = dict(payment=payment, provider_invoice_id=f"np-{payment.pk}",
                      price_amount=Decimal("5.00"), pay_currency="usdttrc20",
                      pay_address="T-dummy-address", pay_amount=Decimal("5"))
        fields.update(over)
        return CryptoInvoice.objects.create(**fields)

    def test_provider_and_test_filters(self):
        card = self.make_payment(provider="freedompay", is_test=False)
        live = self.make_invoice(env="live").payment
        test = self.make_invoice(env="test").payment
        self.assertEqual(self.ids("?provider=gopay"), {live.pk, test.pk})
        self.assertEqual(self.ids("?provider=freedompay"), {card.pk})
        self.assertEqual(self.ids("?is_test=1"), {test.pk})
        self.assertEqual(self.ids("?is_test=0"), {card.pk, live.pk})
        self.assertEqual(self.ids("?provider=gopay&is_test=0"), {live.pk})
        # Непонятное значение фильтр не включает.
        self.assertEqual(self.ids("?is_test=yes"), {card.pk, live.pk, test.pk})
        self.assertEqual(self.ids(""), {card.pk, live.pk, test.pk})

    def test_unsettled_filter_matches_the_counter(self):
        waiting = self.make_invoice(env="live").payment
        stuck = self.make_invoice(env="live", status="committed").payment
        stuck_test = self.make_invoice(env="test", status="committed").payment
        refunded = self.make_payment(response={"admin_refund": {"kind": "refund"}})
        self.make_invoice(refunded, status="committed")
        clawed = self.make_payment(response={"token_purchase_clawed_back": True})
        self.make_invoice(clawed, status="committed")
        paid = self.make_payment(success=True, response={"token_purchase_applied": True})
        self.make_invoice(paid, status="committed")
        self.make_payment(provider="freedompay")

        self.assertEqual(self.ids("?unsettled=1"), {stuck.pk, stuck_test.pk})
        self.assertEqual(self.snapshot()["unsettled"], 2)
        self.assertEqual(self.ids("?unsettled=1&is_test=0"), {stuck.pk})
        self.assertNotIn(waiting.pk, self.ids("?unsettled=1"))
        self.assertEqual(len(self.ids("?unsettled=0")), 7)

    def test_needs_review_finds_gopay_and_crypto(self):
        flagged = self.make_invoice(env="live", status="committed",
                                    flags={"needs_review": "mismatch:amount"}).payment
        self.make_invoice(env="live", flags={"late_commit": True})
        coin = self.make_payment(provider="crypto_nowpayments", currency="USD")
        self.crypto_invoice(coin, flags={"needs_review": "overpaid"})
        calm = self.make_payment(provider="crypto_nowpayments", currency="USD")
        self.crypto_invoice(calm)
        self.assertEqual(self.ids("?needs_review=1"), {flagged.pk, coin.pk})
        self.assertEqual(self.ids("?needs_review=1&provider=gopay"), {flagged.pk})

    def test_row_of_a_live_qr(self):
        invoice = self.make_invoice(env="live")
        row = self.row(invoice.payment)
        self.assertEqual((row["provider"], row["method"], row["is_test"]), ("gopay", "elqr", False))
        self.assertIs(row["pending"], True)
        self.assertIsNone(row["crypto"])
        self.assertIsNone(row["stars"])
        self.assertEqual(set(row["qr"]), {"status", "env", "provider_payment_id", "expires_at",
                                          "committed_at", "bank_op_date", "receipt_url",
                                          "abandoned", "flags"})
        self.assertEqual(row["qr"], {
            "status": "created", "env": "live",
            "provider_payment_id": invoice.provider_payment_id,
            "expires_at": invoice.expires_at.isoformat(), "committed_at": None,
            "bank_op_date": None, "receipt_url": "", "abandoned": False, "flags": {}})

    def test_row_of_a_paid_test_qr(self):
        now = timezone.now()
        payment = self.make_payment(env="test", success=True,
                                    response={"token_purchase_applied": True})
        invoice = self.make_invoice(
            payment, env="test", status="committed", committed_at=now,
            bank_op_date=now.date(), receipt_url="https://pay.gopay.kg/r/1/",
            flags={"late_commit": True})
        row = self.row(payment)
        self.assertIs(row["is_test"], True)
        self.assertIs(row["pending"], False)
        self.assertEqual(row["qr"]["env"], "test")
        self.assertEqual(row["qr"]["committed_at"], invoice.committed_at.isoformat())
        self.assertEqual(row["qr"]["bank_op_date"], now.date().isoformat())
        self.assertEqual(row["qr"]["receipt_url"], "https://pay.gopay.kg/r/1/")
        self.assertEqual(row["qr"]["flags"], {"late_commit": True})

    def test_pending_only_while_the_qr_is_really_alive(self):
        now = timezone.now()
        cases = {
            "live": (dict(), True),
            "bank_is_processing": (dict(status="pending"), True),
            "abandoned": (dict(cancel_requested_at=now, flags={"abandoned": "user"}), False),
            "past_our_deadline": (dict(expires_at=now - timedelta(seconds=5)), False),
            "expired": (dict(status="expired"), False),
            "cancelled": (dict(status="cancelled", cancel_requested_at=now), False),
            "failed": (dict(status="failed"), False),
            "paid_not_credited": (dict(status="committed"), False),
        }
        for name, (fields, expected) in cases.items():
            with self.subTest(case=name):
                invoice = self.make_invoice(env="live", **fields)
                row = self.row(invoice.payment)
                self.assertIs(row["pending"], expected)
                self.assertIs(row["qr"]["abandoned"], name == "abandoned")
        # Успешный платёж не «ждёт», что бы ни говорил счёт.
        paid = self.make_payment(success=True)
        self.make_invoice(paid)
        self.assertIs(self.row(paid)["pending"], False)

    def test_other_providers_keep_their_rows(self):
        card = self.make_payment(provider="freedompay",
                                 request={"pay_method": "card"}, is_test=False)
        row = self.row(card)
        self.assertEqual((row["provider"], row["method"], row["pending"], row["qr"],
                          row["is_test"]), ("freedompay", "card", False, None, False))
        coin = self.make_payment(provider="crypto_nowpayments", currency="USD")
        self.crypto_invoice(coin)
        row = self.row(coin)
        self.assertIs(row["pending"], True)
        self.assertIsNone(row["qr"])
        self.assertEqual(row["crypto"]["status"], "waiting")

    def test_no_secret_or_payment_link_in_the_list(self):
        self.set_keys("live")
        self.make_invoice(env="live", checkout_url="https://pay.gopay.kg/p/secret-link/",
                          qr_url="https://pay.gopay.kg/p/secret-link/qr/")
        response = self.staff.get(PAYMENTS_URL)
        self.assert_no_secrets(response)
        text = response.content.decode("utf-8")
        self.assertNotIn("secret-link", text)
        self.assertNotIn("pay.payqr.kg", text)

    def test_query_count_does_not_grow_with_rows(self):
        def count_queries():
            with CaptureQueriesContext(connection) as ctx:
                response = self.staff.get(PAYMENTS_URL)
            self.assertEqual(response.status_code, 200)
            self.last_queries = list(ctx.captured_queries)
            return len(ctx), len(response.data["results"])

        self.make_invoice(env="live")
        self.make_payment(provider="freedompay")
        few, rows_few = count_queries()
        for _ in range(6):
            self.make_invoice(env="live")
            self.make_invoice(env="test", status="committed")
            self.make_payment(provider="freedompay")
        many, rows_many = count_queries()
        self.assertEqual((rows_few, rows_many), (2, 20))
        self.assertEqual(few, many)
        # Подсчёт строк и сама страница (счета приезжают тем же запросом), плюс
        # точка сохранения запроса и её снятие.
        selects = [q["sql"] for q in self.last_queries if q["sql"].lstrip().startswith("SELECT")]
        self.assertEqual(len(selects), 2, selects)
        self.assertLessEqual(many, 4)

    def test_outsiders_are_refused(self):
        self.assertEqual(self.user_client.get(PAYMENTS_URL).status_code, 403)


# ========================================================= перепроверка ===

class RecheckTests(GoPayAdminTestCase):
    def setUp(self):
        super().setUp()
        self.set_keys("test")
        self.set_keys("live")

    def recheck(self, payment, client=None):
        return (client or self.staff).post(PAYMENTS_URL + f"{payment.pk}/recheck/", {},
                                           format="json")

    def test_paid_invoice_is_credited_through_the_common_path(self):
        invoice = self.make_invoice(env="live")
        self.fake.on("/v1/payments/query", ok(self.state_for(
            invoice, status="COMMITTED", committed_at="2026-10-06T10:01:00",
            bank_op_date="2026-10-06")))
        response = self.recheck(invoice.payment)
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(set(response.data), {"result", "payment"})
        self.assertEqual(response.data["result"], "credited")
        self.assertEqual(response.data["payment"]["id"], invoice.payment_id)
        self.assertIs(response.data["payment"]["success"], True)
        self.assertEqual(response.data["payment"]["qr"]["status"], "committed")
        self.assertEqual(response.data["payment"]["qr"]["bank_op_date"], "2026-10-06")
        self.assertEqual(self.balance(), 500)
        self.assertEqual(self.ledger(), 1)
        self.assert_no_secrets(response)
        # Спросили по номеру платежа GoPay и ключом среды счёта.
        call = self.fake.calls[0]
        self.assertEqual((call.path, call.body),
                         ("/v1/payments/query", {"payment_id": invoice.provider_payment_id}))
        self.assertEqual(call.headers["GoPay-Api-Key"], LIVE_API_KEY)

        # Повторное нажатие ничего не добавляет.
        again = self.recheck(invoice.payment)
        self.assertEqual(again.data["result"], "already")
        self.assertEqual((self.balance(), self.ledger()), (500, 1))

    def test_invoice_env_decides_the_keys_not_the_active_env(self):
        invoice = self.make_invoice(env="test")
        set_runtime("gopay_env", "live")
        self.fake.on("/v1/payments/query", ok(self.state_for(invoice)))
        response = self.recheck(invoice.payment)
        self.assertEqual(response.data["result"], "pending")
        self.assertEqual(self.fake.calls[0].headers["GoPay-Api-Key"], API_KEY)

    def test_open_and_closed_answers(self):
        invoice = self.make_invoice(env="live")
        self.fake.on("/v1/payments/query", ok(self.state_for(invoice, status="PENDING")))
        self.assertEqual(self.recheck(invoice.payment).data["result"], "pending")
        self.fake.on("/v1/payments/query", ok(self.state_for(invoice, status="EXPIRED")))
        response = self.recheck(invoice.payment)
        self.assertEqual(response.data["result"], "closed")
        self.assertEqual(response.data["payment"]["error"], "gopay_status:expired")
        self.assertIs(response.data["payment"]["pending"], False)
        self.assertEqual(self.balance(), 0)

    def test_wrong_amount_is_not_credited(self):
        invoice = self.make_invoice(env="live")
        self.fake.on("/v1/payments/query", ok(self.state_for(invoice, status="COMMITTED",
                                                             amount="1.00")))
        response = self.recheck(invoice.payment)
        self.assertEqual(response.data["result"], "mismatch")
        self.assertIs(response.data["payment"]["success"], False)
        self.assertEqual(response.data["payment"]["qr"]["flags"]["needs_review"],
                         "mismatch:amount")
        self.assertEqual((self.balance(), self.ledger()), (0, 0))

    def test_unavailable_gopay_gives_502(self):
        invoice = self.make_invoice(env="live")
        for answer, code in ((requests.ConnectionError(f"{LIVE_API_SECRET} refused"), "network"),
                             (html(503), "http_503"), (fail("9999", "x"), "provider_error")):
            self.fake.on("/v1/payments/query", answer)
            response = self.recheck(invoice.payment)
            self.assertEqual(response.status_code, 502)
            self.assertEqual(response.data, {"detail": f"GoPay не ответил: {code}"})
            self.assert_no_secrets(response)
        invoice.refresh_from_db()
        self.assertEqual(invoice.status, "created")
        self.assertEqual(self.balance(), 0)

    def test_refusals_and_missing_keys_are_named_not_raised(self):
        invoice = self.make_invoice(env="live")
        self.fake.on("/v1/payments/query", fail("4041", "Payment not found"))
        response = self.recheck(invoice.payment)
        self.assertEqual((response.status_code, response.data["result"]), (200, "not_found"))
        self.fake.on("/v1/payments/query", fail("4001", "Invalid signature"))
        self.assertEqual(self.recheck(invoice.payment).data["result"], "provider_error")
        AppSetting.objects.filter(key="GOPAY_LIVE_API_SECRET").delete()
        cache.clear()
        calls = len(self.fake.calls)
        self.assertEqual(self.recheck(invoice.payment).data["result"], "not_configured")
        self.assertEqual(len(self.fake.calls), calls)

    def test_breaker_does_not_stop_a_human(self):
        invoice = self.make_invoice(env="live")
        for _ in range(gopay_service.DOWN_AFTER_FAILURES):
            gopay_service.note_result("live", gopay_service.GoPayUnavailable("x", code="network"))
        self.assertTrue(gopay_service.provider_down("live"))
        self.fake.on("/v1/payments/query", ok(self.state_for(invoice)))
        self.assertEqual(self.recheck(invoice.payment).data["result"], "pending")
        self.assertEqual(len(self.fake.calls), 1)

    def test_gopay_payment_without_invoice_has_nothing_to_check(self):
        payment = self.make_payment(error="gopay_create_failed:network")
        with patch("payments.tasks.reconcile_pending_token_payments.delay") as delay:
            response = self.recheck(payment)
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data,
                         {"detail": "QR по этому заказу не был создан — проверять нечего."})
        delay.assert_not_called()
        self.assertEqual(self.fake.calls, [])

    def test_refunded_payment_is_never_credited_by_a_recheck(self):
        payment = self.make_payment(
            error="refunded_by_admin",
            response={"admin_refund": {"kind": "refund", "clawback": False}})
        invoice = self.make_invoice(payment)
        self.fake.on("/v1/payments/query", ok(self.state_for(invoice, status="COMMITTED")))
        response = self.recheck(payment)
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["result"], "already")
        self.assertIs(response.data["payment"]["success"], False)
        self.assertEqual(response.data["payment"]["error"], "refunded_by_admin")
        payment.refresh_from_db()
        self.assertFalse(payment.success)
        self.assertNotIn("token_purchase_applied", payment.response)
        self.assertEqual((self.balance(), self.ledger()), (0, 0))
        self.assertEqual(self.snapshot()["unsettled"], 0)

    def test_freedompay_branch_is_unchanged(self):
        card = self.make_payment(provider="freedompay", request={"pay_method": "card"})
        with patch("payments.tasks.reconcile_pending_token_payments.delay") as delay:
            response = self.recheck(card)
        self.assertEqual((response.status_code, response.data), (200, {"queued": True}))
        delay.assert_called_once_with()
        with patch("payments.tasks.reconcile_pending_token_payments.delay",
                   side_effect=RuntimeError("broker down")):
            self.assertEqual(self.recheck(card).status_code, 503)
        self.assertEqual(self.fake.calls, [])

    def test_crypto_branch_is_unchanged(self):
        coin = self.make_payment(provider="crypto_nowpayments", currency="USD")
        CryptoInvoice.objects.create(
            payment=coin, provider_invoice_id="np-1", price_amount=Decimal("5.00"),
            pay_currency="usdttrc20", pay_address="T-dummy-address", pay_amount=Decimal("5"))
        adapter = SimpleNamespace(fetch_invoice=lambda invoice_id: {"id": invoice_id})
        with patch("payments.crypto.registry.get_adapter", return_value=adapter), \
                patch("payments.crypto.credit.apply_provider_status",
                      return_value="pending") as apply:
            response = self.recheck(coin)
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["result"], "pending")
        self.assertEqual(apply.call_args.args[1], {"id": "np-1"})
        self.assertEqual(apply.call_args.kwargs, {"source": "admin"})
        self.assertEqual(self.fake.calls, [])

    def test_missing_payment_and_outsiders(self):
        self.assertEqual(self.staff.post(PAYMENTS_URL + "999999/recheck/").status_code, 404)
        invoice = self.make_invoice(env="live")
        self.assertEqual(self.recheck(invoice.payment, client=self.user_client).status_code, 403)
        self.assertEqual(self.fake.calls, [])


# ======================================================= отметка возврата ===

class MarkRefundedTests(GoPayAdminTestCase):
    def setUp(self):
        super().setUp()
        self.set_keys("test")
        self.set_keys("live")

    def mark(self, payment, client=None, **body):
        data = {"kind": "refund", "reason": "Вернули вручную", **body}
        return (client or self.su).post(PAYMENTS_URL + f"{payment.pk}/mark-refunded/", data,
                                        format="json")

    def assert_marked(self, response, payment):
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(set(response.data), {"reversed", "clawback_debited", "payment"})
        payment.refresh_from_db()
        self.assertEqual(payment.response["admin_refund"]["kind"], "refund")

    def test_open_qr_is_cancelled_at_gopay_before_the_mark(self):
        invoice = self.make_invoice(env="live")
        payment = invoice.payment
        seen = []
        # В момент обращения к GoPay отметки ещё нет: сеть — до блокировок.
        self.fake.before_call = lambda call: seen.append(
            "admin_refund" in (Payment.objects.get(pk=payment.pk).response or {}))
        self.fake.on("/v1/payments/cancel", ok(self.state_for(invoice, status="CANCELLED")))
        response = self.mark(payment)
        self.assert_marked(response, payment)
        self.assertEqual(seen, [False])
        call = self.fake.calls[0]
        self.assertEqual((call.path, call.body),
                         ("/v1/payments/cancel", {"payment_id": invoice.provider_payment_id}))
        self.assertEqual(call.headers["GoPay-Api-Key"], LIVE_API_KEY)
        invoice.refresh_from_db()
        self.assertEqual(invoice.status, "cancelled")
        self.assertIsNotNone(invoice.cancel_requested_at)
        self.assertEqual(invoice.flags.get("cancel_reason"), "admin_refund")
        self.assertEqual(response.data["payment"]["qr"]["status"], "cancelled")
        self.assertIs(response.data["payment"]["pending"], False)
        self.assertEqual(AdminActionLog.objects.filter(action="payment.mark_refunded").count(), 1)

    def test_bank_unavailable_leaves_the_qr_abandoned_and_the_mark_succeeds(self):
        invoice = self.make_invoice(env="live")
        self.fake.on("/v1/payments/cancel", fail("0015", "bank is unavailable"))
        response = self.mark(invoice.payment)
        self.assert_marked(response, invoice.payment)
        invoice.refresh_from_db()
        self.assertEqual(invoice.status, "created")
        self.assertIsNotNone(invoice.cancel_requested_at)
        self.assertEqual(invoice.flags.get("abandoned"), "admin_refund")
        self.assertIs(response.data["payment"]["qr"]["abandoned"], True)
        self.assertIs(response.data["payment"]["pending"], False)

    def test_bank_busy_leaves_the_qr_abandoned(self):
        invoice = self.make_invoice(env="live")
        self.fake.on("/v1/payments/cancel", fail("0013", "bank is processing"))
        self.fake.on("/v1/payments/query", ok(self.state_for(invoice, status="PENDING")))
        response = self.mark(invoice.payment)
        self.assert_marked(response, invoice.payment)
        invoice.refresh_from_db()
        self.assertEqual(invoice.flags.get("abandoned"), "admin_refund")

    def test_silent_gopay_does_not_stop_the_mark(self):
        invoice = self.make_invoice(env="live")
        self.fake.on("/v1/payments/cancel", requests.ConnectionError("refused"))
        response = self.mark(invoice.payment)
        self.assert_marked(response, invoice.payment)
        invoice.refresh_from_db()
        self.assertEqual(invoice.flags.get("abandoned"), "admin_refund")

    def test_any_failure_of_the_pre_step_does_not_stop_the_mark(self):
        invoice = self.make_invoice(env="live")
        with patch("payments.gopay.service.cancel_invoice", side_effect=RuntimeError("boom")):
            response = self.mark(invoice.payment)
        self.assert_marked(response, invoice.payment)
        with patch("payments.gopay.service.invoice_of", side_effect=RuntimeError("boom")):
            other = self.make_invoice(env="live")
            self.assert_marked(self.mark(other.payment), other.payment)

    def test_missing_keys_do_not_stop_the_mark(self):
        invoice = self.make_invoice(env="live")
        AppSetting.objects.filter(key__startswith="GOPAY_LIVE").delete()
        cache.clear()
        response = self.mark(invoice.payment)
        self.assert_marked(response, invoice.payment)
        self.assertEqual(self.fake.calls, [])
        invoice.refresh_from_db()
        self.assertEqual(invoice.flags.get("abandoned"), "admin_refund")

    def test_qr_closed_only_by_our_clock_is_cancelled_too(self):
        now = timezone.now()
        invoice = self.make_invoice(env="live", status="expired", flags={"local_expiry": True},
                                    expires_at=now - timedelta(hours=1), finalized_at=now)
        self.fake.on("/v1/payments/cancel", ok(self.state_for(invoice, status="CANCELLED")))
        self.assert_marked(self.mark(invoice.payment), invoice.payment)
        self.assertEqual(self.fake.paths(), ["/v1/payments/cancel"])
        invoice.refresh_from_db()
        self.assertNotIn("local_expiry", invoice.flags)

    def test_closed_or_paid_qr_is_not_touched(self):
        closed = self.make_invoice(env="live", status="cancelled")
        self.assert_marked(self.mark(closed.payment), closed.payment)
        paid_payment = self.make_payment(success=True, response={"token_purchase_applied": True})
        paid = self.make_invoice(paid_payment, status="committed")
        TokenTransaction.objects.create(user=self.buyer, delta=500, reason="purchase",
                                        balance_after=500, meta={"order_id": paid_payment.order_id})
        self.assert_marked(self.mark(paid_payment), paid_payment)
        self.assertEqual(self.fake.calls, [])
        paid.refresh_from_db()
        self.assertEqual(paid.status, "committed")

    def test_payment_that_turns_out_paid_is_credited_then_marked(self):
        invoice = self.make_invoice(env="live")
        self.fake.on("/v1/payments/cancel", fail("0013", "already confirmed by the bank"))
        self.fake.on("/v1/payments/query", ok(self.state_for(invoice, status="COMMITTED")))
        response = self.mark(invoice.payment, clawback_credits=True)
        self.assert_marked(response, invoice.payment)
        # Деньги пришли — кредиты начислены и тут же изъяты отметкой с изъятием.
        self.assertEqual(response.data["clawback_debited"], 500)
        self.assertEqual(self.balance(), 0)
        self.assertIs(response.data["payment"]["success"], False)

    def test_late_payment_after_the_mark_is_not_credited(self):
        invoice = self.make_invoice(env="live")
        self.fake.on("/v1/payments/cancel", fail("0015", "bank is unavailable"))
        self.assert_marked(self.mark(invoice.payment), invoice.payment)
        self.fake.on("/v1/payments/query", ok(self.state_for(invoice, status="COMMITTED")))
        response = self.staff.post(PAYMENTS_URL + f"{invoice.payment_id}/recheck/")
        self.assertEqual(response.data["result"], "already")
        self.assertIs(response.data["payment"]["success"], False)
        self.assertEqual((self.balance(), self.ledger()), (0, 0))
        self.assertEqual(self.snapshot()["unsettled"], 0)

    def test_late_payment_after_the_mark_calls_a_human(self):
        # Отменить QR у GoPay не вышло, платёж отметили мошенничеством — а
        # покупатель потом заплатил. Кредитов не будет, но деньги настоящие:
        # платёж обязан появиться в «нужен разбор» с событием уровня error.
        from audit.models import EventLog

        for clawback in (False, True):
            with self.subTest(clawback=clawback):
                cache.clear()
                self.set_keys("live")
                EventLog.objects.all().delete()
                invoice = self.make_invoice(env="live")
                self.fake.on("/v1/payments/cancel", fail("0015", "bank is unavailable"))
                self.assert_marked(self.mark(invoice.payment, clawback_credits=clawback),
                                   invoice.payment)
                listed = self.su.get(PAYMENTS_URL + "?needs_review=1").data["results"]
                self.assertNotIn(invoice.payment_id, [row["id"] for row in listed])

                self.fake.on("/v1/payments/query",
                             ok(self.state_for(invoice, status="COMMITTED")))
                response = self.staff.post(PAYMENTS_URL + f"{invoice.payment_id}/recheck/")
                self.assertEqual(response.data["result"], "already")
                self.assertEqual((self.balance(), self.ledger()), (0, 0))
                invoice.refresh_from_db()
                self.assertEqual(invoice.status, "committed")
                self.assertEqual(invoice.flags["needs_review"], "paid_after_refund_mark")
                listed = self.su.get(PAYMENTS_URL + "?needs_review=1").data["results"]
                self.assertIn(invoice.payment_id, [row["id"] for row in listed])
                alerts = EventLog.objects.filter(level="error", meta__needs_review=True)
                self.assertEqual([e.meta["what"] for e in alerts], ["paid_after_refund_mark"])
                self.assertEqual(alerts[0].meta["order_id"], invoice.payment.order_id)

    def test_other_providers_never_reach_gopay(self):
        card = self.make_payment(provider="freedompay", request={"pay_method": "card"})
        with patch("payments.gopay.service.cancel_invoice") as cancel, \
                patch("payments.gopay.service.mark_abandoned") as abandon:
            response = self.mark(card)
        self.assert_marked(response, card)
        self.assertEqual((response.data["reversed"], response.data["clawback_debited"]), (0, 0))
        self.assertIsNone(response.data["payment"]["qr"])
        cancel.assert_not_called()
        abandon.assert_not_called()
        self.assertEqual(self.fake.calls, [])

    def test_errors_and_permissions_are_unchanged(self):
        invoice = self.make_invoice(env="live")
        response = self.mark(invoice.payment, client=self.staff)
        self.assertEqual(response.status_code, 403)
        self.assertEqual(self.fake.calls, [])
        response = self.su.post(PAYMENTS_URL + "999999/mark-refunded/",
                                {"kind": "refund", "reason": "r"}, format="json")
        self.assertEqual(response.status_code, 404)
        self.assertEqual(self.fake.calls, [])

    def test_request_the_mark_refuses_does_not_kill_the_qr(self):
        invoice = self.make_invoice(env="live")
        url = PAYMENTS_URL + f"{invoice.payment_id}/mark-refunded/"
        for body in ({"kind": "chargeback", "reason": "r"}, {"reason": "r"},
                     {"kind": "refund"}, {"kind": "refund", "reason": "   "}):
            with self.subTest(body=body):
                self.assertEqual(self.su.post(url, body, format="json").status_code, 400)
        self.assertEqual(self.fake.calls, [])
        invoice.refresh_from_db()
        self.assertEqual(invoice.status, "created")
        self.assertIsNone(invoice.cancel_requested_at)
        self.assertNotIn("admin_refund", invoice.payment.response or {})

    def test_fraud_mark_closes_the_qr_too(self):
        invoice = self.make_invoice(env="live")
        self.fake.on("/v1/payments/cancel", ok(self.state_for(invoice, status="CANCELLED")))
        response = self.mark(invoice.payment, kind="fraud")
        self.assertEqual(response.status_code, 200, response.data)
        invoice.refresh_from_db()
        self.assertEqual(invoice.status, "cancelled")

    def test_repeated_mark_still_closes_a_qr_left_open(self):
        payment = self.make_payment(response={"admin_refund": {"kind": "refund",
                                                               "clawback": False}})
        invoice = self.make_invoice(payment)
        self.fake.on("/v1/payments/cancel", ok(self.state_for(invoice, status="CANCELLED")))
        # Отметка уже стоит — запрос отклонён (409), но открытый QR погашен:
        # возвращённый платёж с живым QR хуже, чем лишняя отмена.
        self.assertEqual(self.mark(payment).status_code, 409)
        self.assertEqual(self.fake.paths(), ["/v1/payments/cancel"])


# ================================================================ выручка ===

class RevenueTests(GoPayAdminTestCase):
    def setUp(self):
        super().setUp()
        self.real = self.make_payment(env="live", amount="392.00", success=True)
        self.make_invoice(self.real, status="committed")
        self.testing = self.make_payment(env="test", amount="1000.00", success=True)
        self.make_invoice(self.testing, env="test", status="committed")
        self.make_payment(env="live", amount="50.00", success=False)

    def test_dashboard_revenue_skips_test_payments(self):
        with patch("adminapi.views._openrouter_summary",
                   return_value={"total": None, "active": None, "active_title": "",
                                 "accounts": 0}):
            data = self.staff.get(SUMMARY_URL).data
        self.assertEqual(data["revenue_kgs"], 392.0)
        # В ленте последних платежей тестовый виден — он никуда не спрятан.
        self.assertIn(self.testing.pk, {row["id"] for row in data["recent_payments"]})

    def test_audit_metrics_skip_test_payments(self):
        data = collect_dashboard_metrics()
        self.assertEqual(data["payments_success_count"], 1)
        self.assertEqual(data["revenue_total"], Decimal("392.00"))
        self.assertEqual(data["avg_check"], Decimal("392.00"))
