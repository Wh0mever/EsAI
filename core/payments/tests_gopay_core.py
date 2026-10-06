# -*- coding: utf-8 -*-
"""Ядро единого QR (GoPay): подпись, клиент, настройки, счёт и зачисление.

Ни один тест не ходит в сеть: подменяется payments.gopay.client.requests.post,
и проверяется именно наша сторона — байты запроса, разбор ответов, деньги,
идемпотентность и отказы. Ключи здесь — заведомые пустышки.

Эталонные подписи посчитаны отдельно от кода клиента по описанию алгоритма
(HMAC-SHA512 от nonce + "\\n" + тело + "\\n", hex заглавными) и сверены с
openssl dgst -sha512 -hmac.
"""
import hashlib
import hmac
import json
import os
from datetime import timedelta
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import patch

import requests
from django.conf import settings
from django.contrib import admin
from django.contrib.auth import get_user_model
from django.contrib.auth.models import AnonymousUser
from django.core.cache import cache
from django.db import IntegrityError, transaction
from django.test import SimpleTestCase, TestCase, override_settings
from django.utils import timezone

from adminapi.runtime import delete_runtime, set_runtime
from audit.models import EventLog
from payments.gopay import client as gp_client
from payments.gopay import config, service
from payments.gopay.client import (GoPayClient, GoPayError, GoPayRejected, GoPayUnavailable,
                                   PaymentState, parse_testing_mode, serialize, sign,
                                   verify_signature)
from payments.models import GoPayInvoice, GoPayWebhookEvent, Payment
from plans.models import ExitDiscountOffer, TokenTransaction

TEST_CACHES = {"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache",
                           "LOCATION": "gopay-core-tests"}}

# Заведомые пустышки: настоящих ключей в тестах не бывает.
API_KEY = "dummy-api-key-not-real"
API_SECRET = "dummy-api-secret-not-real"
WEBHOOK_SECRET = "dummy-webhook-secret-not-real"
LIVE_API_KEY = "dummy-live-api-key-not-real"
LIVE_API_SECRET = "dummy-live-api-secret-not-real"
LIVE_WEBHOOK_SECRET = "dummy-live-webhook-secret-not-real"
ALL_SECRETS = (API_KEY, API_SECRET, WEBHOOK_SECRET, LIVE_API_KEY, LIVE_API_SECRET,
               LIVE_WEBHOOK_SECRET)
DESC = "EsAI: \u0421\u0442\u0430\u0440\u0442 \u2014 500 \u043a\u0440\u0435\u0434\u0438\u0442\u043e\u0432"

ORDER = "tokpkg-7-3-0a1b2c3d4e"
PID = "a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4"
QR_DATA = "https://pay.payqr.kg#00020101021232990012c2c.kg.elqr5204599953034175802KG6304ABCD"
BASE = "https://api.gopay.kg"

V1_SIG = ("188F2ACC4E271C690EEDA1C6E072DF4272FC5B4F3379D08275E8465DFC2DC2AEEE2797EF828256FC"
          "A929EE464352ACDE9F46ECE913411C972162A91DE4F7CCBB")
V1B_SIG = ("C02F63B44D41F9F46901BDEE8EF0A342817C25F791EA56149B3573EB074D9BB7774C7AB0A5B26623"
           "E440246880B6DB2025BECAB7FAF6B09F18B5FC0EC29C5896")
V2_SIG = ("19777C0C8BDF571CD57B88846ECA3EA951DBDC99196ACCB1178F28E6AC1105DE393EAF9C8EF32425"
          "C989E61079661F1D15BECD804A3650A15709F5FA585C364E")
V3_SIG = ("D8F87D411B6CC5894AF26A4B9A013E2A4022D246FD89DD0059F30D130268FD6E7CFC7DD61422B706"
          "0017BA505F2F9CE5B7768BD5909BAEE9B4F3270242232027")
V4_RAW = (b'{"event":"payment.committed","data":{"payment_id":"a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4",'
          b'"order_id":"tokpkg-7-3-0a1b2c3d4e","status":"COMMITTED","amount":"100.00",'
          b'"testing_mode":true,"created_at":"2026-09-03T04:00:00Z",'
          b'"committed_at":"2026-09-03T04:00:20Z","bank_op_date":null},'
          b'"created_at":"2026-09-03T04:00:20Z"}')
V4_NONCE = "abcdefabcdefabcdefabcdefabcdefab"
V4_SIG = ("5CBE87B2E62C0694530A579EBD469453E9E087CB7EBF89ABEC1EC4CF3A030F6D13D33C7A1772EC67"
          "92252A197858E3396D9044F35DE70D30094FFFC703855297")
V5_KEY = "e24e1e3619012b5c3214389188d2f8113701fe6a137e2d9b3204a31298145835"

GOPAY_SETTINGS = dict(
    CACHES=TEST_CACHES,
    GOPAY_API_URL=BASE, GOPAY_MODE="staff", GOPAY_ENV="test",
    GOPAY_LIFETIME_MINUTES=15, GOPAY_SEND_BUYER_EMAIL=True,
    GOPAY_TEST_API_KEY=API_KEY, GOPAY_TEST_API_SECRET=API_SECRET,
    GOPAY_TEST_WEBHOOK_SECRET=WEBHOOK_SECRET,
    GOPAY_LIVE_API_KEY=LIVE_API_KEY, GOPAY_LIVE_API_SECRET=LIVE_API_SECRET,
    GOPAY_LIVE_WEBHOOK_SECRET=LIVE_WEBHOOK_SECRET,
    SITE_BASE_URL="https://esai.test",
)


def independent_sign(secret: str, nonce: str, body: bytes) -> str:
    """Подпись по описанию алгоритма, без единой строки из клиента."""
    message = nonce.encode("utf-8") + b"\n" + body + b"\n"
    return hmac.new(secret.encode("utf-8"), message, hashlib.sha512).hexdigest().upper()


# ----------------------------------------------------------- заглушки ---

class FakeResponse:
    def __init__(self, status_code=200, payload=None, text=None):
        self.status_code = status_code
        self._payload = payload
        self.text = text if text is not None else json.dumps(payload)
        self.content = self.text.encode("utf-8")

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
        self.routes = {"/v1/payment-app": [ok([])]}

    def on(self, path, *responses):
        self.routes[path] = list(responses)
        return self

    def __call__(self, url, data=None, headers=None, timeout=None, **kwargs):
        path = url[len(BASE):] if url.startswith(BASE) else url
        try:
            body = json.loads(data)
        except Exception:
            body = None
        self.calls.append(SimpleNamespace(url=url, path=path, data=data, headers=headers or {},
                                          timeout=timeout, kwargs=kwargs, body=body,
                                          at=timezone.now()))
        queue = self.routes.get(path)
        if not queue:
            raise AssertionError(f"неожиданный запрос к GoPay: {path}")
        item = queue.pop(0) if len(queue) > 1 else queue[0]
        if isinstance(item, Exception):
            raise item
        return item

    def paths(self):
        return [c.path for c in self.calls]

    def bodies(self, path):
        return [c.body for c in self.calls if c.path == path]


def pay_data(**over):
    data = {
        "payment_id": PID, "order_id": ORDER, "amount": "392.00", "status": "CREATED",
        "qr_data": QR_DATA, "qr_url": f"https://pay.gopay.kg/p/{PID}/qr/",
        "checkout_url": f"https://pay.gopay.kg/p/{PID}/",
        "app_links": {"mbank": "mbank://elqr?data=abc", "megapay": "megapay://payment?x=1"},
        "created_at": "2026-10-06T10:00:00", "expires_at": "2026-10-06T10:15:00",
        "committed_at": None, "bank_op_date": None,
    }
    data.update(over)
    return {k: v for k, v in data.items() if v is not ...}


def state_of(**over) -> PaymentState:
    return PaymentState.from_payload(pay_data(**over))


def creds(env="test"):
    if env == "test":
        return config.Credentials("test", API_KEY, API_SECRET, WEBHOOK_SECRET)
    return config.Credentials("live", LIVE_API_KEY, LIVE_API_SECRET, LIVE_WEBHOOK_SECRET)


class GoPayTestCase(TestCase):
    """Общее: чистый кэш, подменённый HTTP, покупатель и фабрики платежа/счёта."""

    def setUp(self):
        cache.clear()
        self.addCleanup(cache.clear)
        self.fake = FakeGoPay()
        patcher = patch("payments.gopay.client.requests.post", side_effect=self.fake)
        self.post = patcher.start()
        self.addCleanup(patcher.stop)
        User = get_user_model()
        self.user = User.objects.create_user(email="buyer@example.com", password="x-pass-123")
        self.staff = User.objects.create_user(email="staff@example.com", password="x-pass-123",
                                              is_staff=True)

    def make_payment(self, env="live", user=..., amount="392.00", order_id=ORDER, **over):
        if user is ...:
            user = self.staff if env == "test" else self.user
        request = {
            "provider": "gopay", "pay_method": "elqr",
            "token_purchase": {"package_id": 3, "tokens": 500, "bonus_tokens": 0},
            "return_to": "/profile",
            "gopay": {"env": env, "lifetime": 900, "package_name": "Про"},
        }
        request.update(over.pop("request_extra", {}))
        fields = dict(
            user=user, provider="gopay", amount=Decimal(amount), currency="KGS",
            order_id=order_id, description="Token package purchase #3 (qr)",
            is_test=(env == "test"), request=request, response={})
        fields.update(over)
        return Payment.objects.create(**fields)

    def make_invoice(self, payment=None, env="live", **over):
        payment = payment or self.make_payment(env=env)
        fields = dict(
            payment=payment, env=env, provider_payment_id=PID, status="created",
            amount=payment.amount, lifetime_seconds=900, qr_data=QR_DATA,
            qr_url=f"https://pay.gopay.kg/p/{PID}/qr/",
            checkout_url=f"https://pay.gopay.kg/p/{PID}/",
            app_links={"mbank": "mbank://elqr?data=abc"},
            expires_at=timezone.now() + timedelta(minutes=15))
        fields.update(over)
        return GoPayInvoice.objects.create(**fields)

    def balance(self, user=None):
        user = user or self.user
        user.refresh_from_db()
        return int(user.token_balance or 0)

    def ledger(self, user=None):
        return TokenTransaction.objects.filter(user=user or self.user, reason="purchase").count()

    def review_events(self):
        return EventLog.objects.filter(level="error", meta__needs_review=True)


# ============================================================ подпись ===

class SigningTests(SimpleTestCase):
    def test_v1_create_body(self):
        body = serialize({"order_id": ORDER, "amount": "100.00", "description": DESC,
                          "lifetime": 900})
        self.assertEqual(len(body), 127)
        self.assertEqual(hashlib.sha256(body).hexdigest(),
                         "620775f467af89753014d2fd2ee0e4f8fa55a9632ac256942626e056bd3de513")
        self.assertEqual(sign(API_SECRET, "0123456789abcdef0123456789abcdef", body), V1_SIG)

    def test_v1b_with_return_urls(self):
        body = serialize({"order_id": ORDER, "amount": "100.00", "description": DESC,
                          "lifetime": 900,
                          "success_url": "https://esai.kg/profile?payment=tokens_success",
                          "failure_url": "https://esai.kg/profile?payment=tokens_failed"})
        self.assertEqual(len(body), 252)
        self.assertEqual(hashlib.sha256(body).hexdigest(),
                         "000f477f4461e861ba57ce3ffe8c806b4ad171ae869c83f3106d7acce74bbab9")
        self.assertEqual(sign(API_SECRET, "0123456789abcdef0123456789abcdef", body), V1B_SIG)

    def test_v2_query_and_v3_payment_app(self):
        self.assertEqual(sign(API_SECRET, "f" * 32, b'{"payment_id":"' + PID.encode() + b'"}'),
                         V2_SIG)
        self.assertEqual(serialize({"platform": "any"}), b'{"platform":"any"}')
        self.assertEqual(sign(API_SECRET, "0" * 32, b'{"platform":"any"}'), V3_SIG)

    def test_vectors_match_an_independent_implementation(self):
        # Тот же алгоритм, записанный второй раз: расхождение = ошибка в клиенте.
        for secret, nonce, body, expected in (
                (API_SECRET, "f" * 32, b'{"payment_id":"' + PID.encode() + b'"}', V2_SIG),
                (API_SECRET, "0" * 32, b'{"platform":"any"}', V3_SIG),
                (WEBHOOK_SECRET, V4_NONCE, V4_RAW, V4_SIG)):
            self.assertEqual(independent_sign(secret, nonce, body), expected)
            self.assertEqual(sign(secret, nonce, body), expected)

    def test_serialize_is_compact_real_utf8(self):
        body = serialize({"a": "Старт — 500", "b": 1})
        self.assertEqual(body, '{"a":"Старт — 500","b":1}'.encode("utf-8"))
        self.assertNotIn(b"\\u", body)
        self.assertNotIn(b", ", body)
        self.assertNotIn(b'": ', body)

    def test_nonce_is_32_lowercase_hex_and_fresh(self):
        seen = {gp_client.new_nonce() for _ in range(50)}
        self.assertEqual(len(seen), 50)
        for nonce in seen:
            self.assertRegex(nonce, r"^[0-9a-f]{32}$")

    def test_verify_signature_v4(self):
        self.assertEqual(len(V4_RAW), 310)
        self.assertTrue(verify_signature(WEBHOOK_SECRET, V4_NONCE, V4_RAW, V4_SIG))
        self.assertTrue(verify_signature(WEBHOOK_SECRET, V4_NONCE, V4_RAW, V4_SIG.lower()))
        self.assertTrue(verify_signature(WEBHOOK_SECRET, V4_NONCE, V4_RAW, f"  {V4_SIG}\n"))

    def test_verify_signature_rejects(self):
        tampered = V4_RAW.replace(b'"100.00"', b'"900.00"')
        self.assertEqual(len(tampered), len(V4_RAW))
        self.assertFalse(verify_signature(WEBHOOK_SECRET, V4_NONCE, tampered, V4_SIG))
        self.assertFalse(verify_signature(API_SECRET, V4_NONCE, V4_RAW, V4_SIG))
        self.assertFalse(verify_signature("", V4_NONCE, V4_RAW, V4_SIG))
        self.assertFalse(verify_signature(WEBHOOK_SECRET, "", V4_RAW, V4_SIG))
        self.assertFalse(verify_signature(WEBHOOK_SECRET, "n" * 65, V4_RAW, V4_SIG))
        self.assertFalse(verify_signature(WEBHOOK_SECRET, V4_NONCE, V4_RAW, V4_SIG[:127]))
        self.assertFalse(verify_signature(WEBHOOK_SECRET, V4_NONCE, V4_RAW, "Z" * 128))
        self.assertFalse(verify_signature(WEBHOOK_SECRET, V4_NONCE, V4_RAW, "Я" * 128))
        self.assertFalse(verify_signature(WEBHOOK_SECRET, V4_NONCE, V4_RAW, ""))
        self.assertFalse(verify_signature(WEBHOOK_SECRET, V4_NONCE, V4_RAW, None))

    def test_v5_event_key(self):
        state = PaymentState.from_payload(json.loads(V4_RAW)["data"])
        self.assertEqual(service.event_key("payment.committed", state, "2026-09-03T04:00:20Z"),
                         V5_KEY)


# ============================================================= клиент ===

class ClientCase(SimpleTestCase):
    def setUp(self):
        self.fake = FakeGoPay()
        patcher = patch("payments.gopay.client.requests.post", side_effect=self.fake)
        self.post = patcher.start()
        self.addCleanup(patcher.stop)
        self.client_ = GoPayClient(creds("test"), base_url=BASE)

    def create(self, **over):
        kwargs = dict(order_id=ORDER, amount=Decimal("100.00"), description=DESC, lifetime=900)
        kwargs.update(over)
        return self.client_.create_payment(**kwargs)


class ClientRequestTests(ClientCase):
    def test_signed_bytes_are_the_bytes_sent(self):
        self.fake.on("/v1/payments", ok(pay_data(amount="100.00")))
        self.create(success_url="https://esai.kg/profile?payment=tokens_success",
                    failure_url="https://esai.kg/profile?payment=tokens_failed",
                    buyer_email="buyer@example.com")
        call = self.fake.calls[0]
        self.assertIsInstance(call.data, bytes)
        # Подпись пересчитана по тому, что реально ушло в сеть.
        self.assertEqual(call.headers["GoPay-Signature"],
                         independent_sign(API_SECRET, call.headers["GoPay-Nonce"], call.data))
        self.assertNotIn("json", call.kwargs)
        self.assertIs(call.kwargs.get("allow_redirects"), False)
        self.assertIn("Старт — 500".encode("utf-8"), call.data)

    def test_v1_vector_through_the_client(self):
        self.fake.on("/v1/payments", ok(pay_data(amount="100.00")))
        with patch("payments.gopay.client.new_nonce",
                   return_value="0123456789abcdef0123456789abcdef"):
            self.create()
        call = self.fake.calls[0]
        self.assertEqual(hashlib.sha256(call.data).hexdigest(),
                         "620775f467af89753014d2fd2ee0e4f8fa55a9632ac256942626e056bd3de513")
        self.assertEqual(call.headers["GoPay-Signature"], V1_SIG)

    def test_v1b_v2_v3_vectors_through_the_client(self):
        self.fake.on("/v1/payments", ok(pay_data(amount="100.00")))
        self.fake.on("/v1/payments/query", ok(pay_data()))
        with patch("payments.gopay.client.new_nonce",
                   return_value="0123456789abcdef0123456789abcdef"):
            self.create(success_url="https://esai.kg/profile?payment=tokens_success",
                        failure_url="https://esai.kg/profile?payment=tokens_failed")
        with patch("payments.gopay.client.new_nonce", return_value="f" * 32):
            self.client_.query_payment(payment_id=PID)
        with patch("payments.gopay.client.new_nonce", return_value="0" * 32):
            self.client_.payment_apps("any")
        signatures = [c.headers["GoPay-Signature"] for c in self.fake.calls]
        self.assertEqual(signatures, [V1B_SIG, V2_SIG, V3_SIG])
        self.assertEqual(self.fake.calls[1].data, b'{"payment_id":"' + PID.encode() + b'"}')
        self.assertEqual(self.fake.calls[2].data, b'{"platform":"any"}')

    def test_headers_and_fresh_nonce_per_call(self):
        self.fake.on("/v1/payments/query", ok(pay_data()))
        self.client_.query_payment(payment_id=PID)
        self.client_.query_payment(payment_id=PID)
        first, second = self.fake.calls
        self.assertEqual(first.headers["Content-Type"], "application/json")
        self.assertEqual(first.headers["GoPay-Api-Key"], API_KEY)
        self.assertRegex(first.headers["GoPay-Nonce"], r"^[0-9a-f]{32}$")
        self.assertRegex(first.headers["GoPay-Signature"], r"^[0-9A-F]{128}$")
        self.assertNotEqual(first.headers["GoPay-Nonce"], second.headers["GoPay-Nonce"])
        self.assertEqual(set(first.headers), {"Content-Type", "GoPay-Api-Key", "GoPay-Nonce",
                                              "GoPay-Signature"})
        self.assertEqual(first.url, f"{BASE}/v1/payments/query")

    def test_timeouts_per_method(self):
        self.fake.on("/v1/payments", ok(pay_data(amount="100.00")))
        self.fake.on("/v1/payments/query", ok(pay_data()))
        self.fake.on("/v1/payments/cancel", ok(pay_data(status="CANCELLED")))
        self.create()
        self.client_.query_payment(payment_id=PID)
        self.client_.cancel_payment(payment_id=PID)
        self.client_.payment_apps()
        self.assertEqual([c.timeout for c in self.fake.calls], [(5, 15), (3, 5), (5, 10), (5, 8)])

    def test_body_key_order_and_omission_of_empty_optionals(self):
        self.fake.on("/v1/payments", ok(pay_data(amount="100.00")))
        self.create(description="")
        self.assertEqual(self.fake.calls[0].data,
                         b'{"order_id":"tokpkg-7-3-0a1b2c3d4e","amount":"100.00","lifetime":900}')
        self.create(success_url="https://esai.kg/a?payment=ok",
                    failure_url="https://esai.kg/a?payment=no",
                    buyer_email="buyer@example.com")
        self.assertEqual(list(self.fake.calls[1].body),
                         ["order_id", "amount", "description", "lifetime", "success_url",
                          "failure_url", "buyer"])
        self.assertEqual(self.fake.calls[1].body["buyer"], {"email": "buyer@example.com"})

    def test_never_sends_legacy_or_fiscal_fields(self):
        self.fake.on("/v1/payments", ok(pay_data(amount="100.00")))
        self.create(buyer_email="buyer@example.com",
                    success_url="https://esai.kg/a", failure_url="https://esai.kg/b")
        body = self.fake.calls[0].body
        for key in ("callback_url", "testing_mode", "items", "currency"):
            self.assertNotIn(key, body)
        self.assertNotIn("phone", body["buyer"])

    def test_amount_is_a_two_decimal_string(self):
        self.fake.on("/v1/payments", ok(pay_data()))
        self.create(amount=Decimal("392"))
        self.assertEqual(self.fake.calls[0].body["amount"], "392.00")
        self.assertIsInstance(self.fake.calls[0].body["lifetime"], int)
        with self.assertRaises(ValueError):
            self.create(amount=Decimal("391.996"))
        self.assertEqual(len(self.fake.calls), 1)

    def test_description_is_cut_to_255(self):
        self.fake.on("/v1/payments", ok(pay_data(amount="100.00")))
        self.create(description="я" * 400)
        self.assertEqual(len(self.fake.calls[0].body["description"]), 255)

    def test_return_urls_only_as_a_valid_pair(self):
        self.fake.on("/v1/payments", ok(pay_data(amount="100.00")))
        cases = (
            ("https://esai.kg/ok", ""),
            ("", "https://esai.kg/no"),
            ("https://esai.kg/ok", "http://esai.kg/no"),
            ("https://esai.kg/ok", "https://esai.kg/мой профиль"),
            ("https://esai.kg/ok", 'https://esai.kg/a"b'),
        )
        for success_url, failure_url in cases:
            self.create(success_url=success_url, failure_url=failure_url)
            call = self.fake.calls[-1]
            self.assertNotIn("success_url", call.body)
            self.assertNotIn("failure_url", call.body)
            # И без адресов тело сходится со своей подписью.
            self.assertEqual(call.headers["GoPay-Signature"],
                             independent_sign(API_SECRET, call.headers["GoPay-Nonce"], call.data))

    def test_buyer_email_only_for_a_real_mailbox(self):
        # Решение R2: почта-заглушка аккаунта из Telegram в GoPay не уходит.
        self.fake.on("/v1/payments", ok(pay_data(amount="100.00")))
        for email in ("", "   ", "tg123@social.esai.local", "TG9@Social.Esai.Local",
                      "no-at-sign", "a" * 250 + "@example.com"):
            self.create(buyer_email=email)
            self.assertNotIn("buyer", self.fake.calls[-1].body, email)
        self.create(buyer_email=" real@example.com ")
        self.assertEqual(self.fake.calls[-1].body["buyer"], {"email": "real@example.com"})

    def test_order_id_longer_than_32_is_refused_before_http(self):
        long_id = "t" * 33
        with self.assertRaises(ValueError):
            self.create(order_id=long_id)
        with self.assertRaises(ValueError):
            self.client_.query_payment(order_id=long_id)
        with self.assertRaises(ValueError):
            self.client_.cancel_payment(order_id=long_id)
        with self.assertRaises(ValueError):
            self.client_.query_payment()
        with self.assertRaises(ValueError):
            self.create(order_id="")
        self.assertEqual(self.fake.calls, [])

    def test_query_and_cancel_body_rule(self):
        self.fake.on("/v1/payments/query", ok(pay_data()))
        self.fake.on("/v1/payments/cancel", ok(pay_data(status="CANCELLED")))
        self.client_.query_payment(payment_id=PID, order_id=ORDER)
        self.client_.query_payment(order_id=ORDER)
        self.client_.cancel_payment(payment_id=PID)
        self.assertEqual([c.body for c in self.fake.calls],
                         [{"payment_id": PID}, {"order_id": ORDER}, {"payment_id": PID}])

    def test_incomplete_credentials_never_reach_the_network(self):
        client = GoPayClient(config.Credentials("test", API_KEY, "", ""), base_url=BASE)
        with self.assertRaises(GoPayError) as ctx:
            client.query_payment(payment_id=PID)
        self.assertEqual(ctx.exception.kind, "not_configured")
        self.assertEqual(self.fake.calls, [])


class EnvelopeTests(ClientCase):
    def query(self):
        return self.client_.query_payment(payment_id=PID)

    def assert_unavailable(self, response, code):
        self.fake.on("/v1/payments/query", response)
        with self.assertRaises(GoPayUnavailable) as ctx:
            self.query()
        self.assertEqual(ctx.exception.code, code)
        self.assertEqual(ctx.exception.kind, "unavailable")
        return ctx.exception

    def test_network_errors_are_unavailable(self):
        for exc in (requests.Timeout("t"), requests.ConnectionError("c"),
                    requests.exceptions.SSLError("s")):
            self.assert_unavailable(exc, "network")

    def test_network_error_text_carries_no_request_details(self):
        self.fake.on("/v1/payments/query",
                     requests.ConnectionError(f"boom {API_SECRET} {API_KEY}"))
        with self.assertRaises(GoPayUnavailable) as ctx:
            self.query()
        self.assertEqual(str(ctx.exception), "network: ConnectionError")
        self.assertIsNone(ctx.exception.__cause__)
        self.assertTrue(ctx.exception.__suppress_context__)

    def test_http_5xx_408_429_are_unavailable(self):
        for status in (500, 502, 503, 408, 429):
            exc = self.assert_unavailable(html(status), f"http_{status}")
            self.assertEqual(exc.http_status, status)
        # И с телом-конвертом тоже: статус решает раньше тела.
        self.assert_unavailable(fail("4005", "dup", http=500), "http_500")

    def test_non_json_on_200_is_bad_response(self):
        self.assert_unavailable(html(200), "bad_response")
        self.assert_unavailable(FakeResponse(200, ["not", "an", "object"]), "bad_response")

    def test_non_json_on_other_statuses_is_rejected(self):
        self.fake.on("/v1/payments/query", html(404))
        with self.assertRaises(GoPayRejected) as ctx:
            self.query()
        self.assertEqual((ctx.exception.code, ctx.exception.kind, ctx.exception.provider_code),
                         ("http_404", "other", ""))
        for status in (401, 403):
            self.fake.on("/v1/payments/query", html(status))
            with self.assertRaises(GoPayRejected) as ctx:
                self.query()
            self.assertEqual((ctx.exception.code, ctx.exception.kind),
                             (f"http_{status}", "auth"))
        self.fake.on("/v1/payments/query", html(405))
        with self.assertRaises(GoPayRejected) as ctx:
            self.query()
        self.assertEqual(ctx.exception.kind, "other")

    def test_ok_without_data_is_bad_response(self):
        self.assert_unavailable(FakeResponse(200, {"status": "OK", "code": "0000"}),
                                "bad_response")
        self.assert_unavailable(FakeResponse(200, {"status": "OK", "code": "0000", "data": None}),
                                "bad_response")

    def test_ok_with_empty_list_is_success(self):
        self.fake.on("/v1/payment-app", ok([]))
        self.assertEqual(self.client_.payment_apps(), [])
        self.assertEqual(self.client_.healthcheck(), {"ok": True, "apps": 0})

    def test_ok_with_empty_object_is_success(self):
        self.fake.on("/v1/payments/query", ok({}))
        state = self.query()
        self.assertEqual((state.payment_id, state.status), ("", "unknown"))

    def test_ok_with_unexpected_code_is_success_with_warning(self):
        self.fake.on("/v1/payments/query", ok(pay_data(), code="0001"))
        with self.assertLogs("payments.gopay", level="WARNING") as logs:
            state = self.query()
        self.assertEqual(state.payment_id, PID)
        self.assertIn("0001", "".join(logs.output))

    def test_ok_envelope_on_a_non_2xx_status_is_not_success(self):
        self.fake.on("/v1/payments/query",
                     FakeResponse(400, {"status": "OK", "code": "0000", "data": pay_data()}))
        with self.assertRaises(GoPayRejected) as ctx:
            self.query()
        self.assertEqual(ctx.exception.kind, "invalid")


class KindTests(ClientCase):
    def kind_of(self, code, message="", http=200):
        self.fake.on("/v1/payments/query", fail(code, message, http))
        with self.assertRaises(GoPayError) as ctx:
            self.client_.query_payment(payment_id=PID)
        return ctx.exception

    def test_exact_codes(self):
        expected = {
            "4005": ("duplicate", "duplicate_order"), "4041": ("not_found", "not_found"),
            "0013": ("cannot_cancel", "cannot_cancel"), "0015": ("cancel_retry", "cancel_retry"),
            "0016": ("org_inactive", "org_inactive"), "0004": ("rate_limited", "rate_limited"),
            "4001": ("auth", "auth"), "4002": ("auth", "auth"),
            "4003": ("invalid", "invalid_request"), "4004": ("invalid", "invalid_request"),
        }
        for code, (kind, our_code) in expected.items():
            exc = self.kind_of(code, "whatever")
            self.assertIsInstance(exc, GoPayRejected)
            self.assertEqual((exc.kind, exc.code, exc.provider_code), (kind, our_code, code))

    def test_internal_error_codes_are_unavailable(self):
        for code in ("5001", "9999"):
            exc = self.kind_of(code, "Internal error")
            self.assertIsInstance(exc, GoPayUnavailable)
            self.assertEqual((exc.code, exc.provider_code), ("provider_error", code))

    def test_unknown_code_falls_back_to_message_and_status(self):
        self.assertEqual(self.kind_of("0009", "Order already exists").kind, "duplicate")
        self.assertEqual(self.kind_of("0009", "Дублирующийся order_id").kind, "duplicate")
        self.assertEqual(self.kind_of("", "Неверная подпись запроса").kind, "auth")
        self.assertEqual(self.kind_of("0009", "nope", http=403).kind, "auth")
        exc = self.kind_of("0009", "amount mismatch", http=400)
        self.assertEqual((exc.kind, exc.code), ("invalid", "invalid_request"))
        exc = self.kind_of("0009", "something else")
        self.assertEqual((exc.kind, exc.code, exc.provider_code), ("other", "rejected", "0009"))

    def test_code_wins_over_text(self):
        self.assertEqual(self.kind_of("0013", "Payment not found at bank").kind, "cannot_cancel")
        self.assertEqual(self.kind_of("0015", "already exists").kind, "cancel_retry")
        self.assertEqual(self.kind_of("4041", "duplicate signature api key").kind, "not_found")

    def test_not_found_never_comes_from_a_message(self):
        exc = self.kind_of("0009", "API key not found")
        self.assertEqual(exc.kind, "auth")
        for message in ("Payment not found", "Not found.", "Объект не найден"):
            self.assertNotEqual(self.kind_of("0009", message).kind, "not_found")
            self.assertNotEqual(self.kind_of("", message, http=404).kind, "not_found")

    def test_error_text_is_bounded_and_scrubbed(self):
        exc = self.kind_of("0009", f"key {API_KEY} secret {API_SECRET} " + "x" * 500)
        self.assertNotIn(API_KEY, str(exc))
        self.assertNotIn(API_SECRET, str(exc))
        self.assertNotIn(API_KEY, exc.message)
        self.assertLessEqual(len(str(exc)), len("rejected: ") + 160)
        self.assertTrue(str(exc).startswith("rejected: "))


class PaymentAppsTests(ClientCase):
    APPS = [
        {"code": "mbank", "name": "MBank", "order": 1, "icon": "https://media.gopay.kg/apps/mbank.png",
         "url": "mbank://elqr?data={qr_data}", "android_package_name": "kg.mbank.mbankmobile",
         "is_active_on_ios": True},
        {"code": "megapay", "name": "MegaPay", "order": "2", "icon": "https://media.gopay.kg/apps/megapay.png",
         "url": "megapay://elqr?data={qr_data}", "android_package_name": "kg.megabank.megapay",
         "is_active_on_ios": False},
        {"name": "No code", "order": 3},
        "garbage",
    ]

    def test_list_empty_and_single_dict(self):
        self.fake.on("/v1/payment-app", ok(self.APPS))
        apps = self.client_.payment_apps("any")
        self.assertEqual([a["code"] for a in apps], ["mbank", "megapay"])
        self.assertEqual(set(apps[0]), {"code", "name", "order", "icon", "url",
                                        "android_package_name", "is_active_on_ios"})
        self.assertEqual(apps[1]["order"], 2)
        self.assertIs(apps[1]["is_active_on_ios"], False)
        self.assertEqual(self.fake.calls[0].body, {"platform": "any"})

        self.fake.on("/v1/payment-app", ok([]))
        self.assertEqual(self.client_.payment_apps(), [])
        self.fake.on("/v1/payment-app", ok(self.APPS[0]))
        self.assertEqual([a["code"] for a in self.client_.payment_apps()], ["mbank"])

    def test_ios_flag_and_order_parsing(self):
        def one(**fields):
            self.fake.on("/v1/payment-app", ok([{"code": "x", **fields}]))
            return self.client_.payment_apps()[0]

        for value in (True, "true", "TRUE", " 1 ", "1", 1):
            self.assertIs(one(is_active_on_ios=value)["is_active_on_ios"], True, value)
        for value in (False, "false", "FALSE", "0", 0, ""):
            self.assertIs(one(is_active_on_ios=value)["is_active_on_ios"], False, value)
        for value in ("maybe", 2, [], None):
            self.assertIsNone(one(is_active_on_ios=value)["is_active_on_ios"], value)
        self.assertIsNone(one()["is_active_on_ios"])
        self.assertEqual(one(order="2")["order"], 2)
        self.assertEqual(one(order=7)["order"], 7)
        for value in ("garbage", None, [], True, 1.5):
            self.assertEqual(one(order=value)["order"], 999, value)

    def test_healthcheck_never_raises(self):
        self.fake.on("/v1/payment-app", ok(self.APPS))
        self.assertEqual(self.client_.healthcheck(), {"ok": True, "apps": 2})
        self.fake.on("/v1/payment-app", fail("4001", f"Bad signature for {API_KEY}"))
        result = self.client_.healthcheck()
        self.assertEqual((result["ok"], result["kind"], result["code"], result["provider_code"],
                          result["http_status"]), (False, "auth", "auth", "4001", 200))
        self.assertNotIn(API_KEY, json.dumps(result))
        self.fake.on("/v1/payment-app", requests.Timeout())
        self.assertEqual(self.client_.healthcheck()["kind"], "unavailable")
        self.fake.on("/v1/payment-app", RuntimeError("unexpected"))
        self.assertEqual(self.client_.healthcheck()["ok"], False)


class PaymentStateTests(SimpleTestCase):
    def test_garbage_gives_an_empty_state(self):
        for garbage in (None, [], "text", 5, {"status": {"a": 1}, "amount": [1]}):
            state = PaymentState.from_payload(garbage)
            self.assertEqual(state.status, "unknown")
            self.assertIsNone(state.amount)
            self.assertEqual(state.payment_id, "")
            self.assertEqual(state.app_links, {})
        self.assertEqual(PaymentState.from_payload({}).raw, {})

    def test_full_payload(self):
        state = state_of(status="committed", committed_at="2026-10-06T10:03:00Z",
                         bank_op_date="2026-10-06", testing_mode=True, description="x",
                         extra={"nested": 1})
        self.assertEqual(state.status, "committed")
        self.assertEqual(state.provider_status, "COMMITTED")
        self.assertEqual(state.amount, Decimal("392.00"))
        self.assertIs(state.testing_mode, True)
        self.assertEqual(state.qr_data, QR_DATA)
        self.assertEqual(state.bank_op_date, "2026-10-06")
        self.assertEqual(state.committed_at_raw, "2026-10-06T10:03:00Z")
        self.assertEqual(state.app_links["mbank"], "mbank://elqr?data=abc")
        # В raw — только белый список: ни QR, ни ссылок, ни чужих ключей.
        self.assertEqual(set(state.raw), {"payment_id", "order_id", "amount", "status",
                                          "testing_mode", "created_at", "expires_at",
                                          "committed_at", "bank_op_date"})

    def test_statuses(self):
        for raw, expected in (("CREATED", "created"), ("PENDING", "pending"),
                              ("COMMITTED", "committed"), ("FAILED", "failed"),
                              ("EXPIRED", "expired"), ("CANCELLED", "cancelled"),
                              ("CANCELED", "cancelled"), ("canceled", "cancelled"),
                              ("REFUNDED", "unknown"), ("", "unknown")):
            self.assertEqual(state_of(status=raw).status, expected, raw)
        self.assertEqual(state_of(status="REFUNDED").provider_status, "REFUNDED")
        self.assertEqual(PaymentState.from_payload({"payment_id": PID}).status, "unknown")

    def test_amount_is_exact(self):
        for raw in ("392.00", 392, "392.0", "392"):
            self.assertEqual(state_of(amount=raw).amount, Decimal("392.00"), raw)
        for raw in ("391.996", "NaN", "Infinity", "-Infinity", "-1", "abc", "", None, True,
                    [392], {"v": 392}, 391.996):
            self.assertIsNone(state_of(amount=raw).amount, raw)

    def test_fields_are_bounded(self):
        state = state_of(payment_id=" " + "p" * 100, order_id="o" * 100,
                         expires_at="e" * 100, status="s" * 100, app_links={"a": 1, 2: "x"},
                         bank_op_date="06.10.2026")
        self.assertEqual(len(state.payment_id), 64)
        self.assertEqual(len(state.order_id), 64)
        self.assertEqual(len(state.expires_at_raw), 40)
        self.assertEqual(len(state.provider_status), 32)
        self.assertEqual(state.app_links, {})
        self.assertEqual(state.bank_op_date, "")
        self.assertEqual(state_of(app_links="nope").app_links, {})

    def test_parse_testing_mode(self):
        for value in (None, False, 0, "false", "0", "", " FALSE "):
            self.assertIs(parse_testing_mode(value), False, value)
        for value in (True, 1, "true", "TRUE", "1", " True "):
            self.assertIs(parse_testing_mode(value), True, value)
        for value in ("yes", 2, [], {}, "on", 1.0, -1):
            self.assertIsNone(parse_testing_mode(value), value)
        self.assertIs(PaymentState.from_payload({"status": "CREATED"}).testing_mode, False)
        self.assertIsNone(state_of(testing_mode="yes").testing_mode)


class SecrecyTests(SimpleTestCase):
    def test_credentials_repr_has_no_values(self):
        c = creds("test")
        for text in (repr(c), str(c), f"{c}"):
            for secret in ALL_SECRETS:
                self.assertNotIn(secret, text)
            self.assertIn("…real", text)
            self.assertIn("secrets=set", text)
        self.assertIn("secrets=unset", repr(config.Credentials("live", "", "", "")))
        self.assertTrue(c.complete)
        self.assertFalse(config.Credentials("test", API_KEY, "", WEBHOOK_SECRET).complete)

    def test_error_text_format(self):
        exc = GoPayError("m" * 500, code="some_code", kind="auth", provider_code="4001",
                         http_status=200)
        self.assertEqual(str(exc), "some_code: " + "m" * 160)
        self.assertEqual((exc.code, exc.kind, exc.provider_code, exc.http_status),
                         ("some_code", "auth", "4001", 200))
        self.assertEqual(str(GoPayError()), "gopay_error: ")
        self.assertEqual(GoPayUnavailable(code="network").kind, "unavailable")
        self.assertIsInstance(GoPayUnavailable(), GoPayError)
        self.assertIsInstance(GoPayRejected(), GoPayError)

    def test_client_repr_has_no_values(self):
        text = repr(GoPayClient(creds("test"), base_url=BASE))
        for secret in ALL_SECRETS:
            self.assertNotIn(secret, text)


# ========================================================== настройки ===

@override_settings(**GOPAY_SETTINGS)
class ConfigTests(TestCase):
    def setUp(self):
        cache.clear()
        self.addCleanup(cache.clear)

    def test_shipped_defaults(self):
        # Что записано в settings.py. Читаем текст, а не значения: на проде после
        # запуска в .env стоит GOPAY_ENV=live, и тест не должен от этого зависеть.
        path = os.path.join(str(settings.BASE_DIR), "core", "settings.py")
        with open(path, encoding="utf-8") as handle:
            source = handle.read()
        for line in ('GOPAY_API_URL = env.str("GOPAY_API_URL", default="https://api.gopay.kg")',
                     'GOPAY_MODE = env.str("GOPAY_MODE", default="staff")',
                     'GOPAY_ENV = env.str("GOPAY_ENV", default="test")',
                     'GOPAY_LIFETIME_MINUTES = env.int("GOPAY_LIFETIME_MINUTES", default=15)',
                     'GOPAY_SEND_BUYER_EMAIL = env.bool("GOPAY_SEND_BUYER_EMAIL", default=True)',
                     'GOPAY_LIVE_API_SECRET = env.str("GOPAY_LIVE_API_SECRET", default="")'):
            self.assertIn(line, source)
        # И то, к чему откатывается код, если настройки нет вовсе.
        with override_settings():
            for name in ("GOPAY_MODE", "GOPAY_ENV", "GOPAY_LIFETIME_MINUTES",
                         "GOPAY_SEND_BUYER_EMAIL"):
                delattr(settings, name)
            self.assertEqual((config.mode(), config.env(), config.lifetime_minutes()),
                             ("staff", "test", 15))
            self.assertIs(config.send_buyer_email(), True)
        self.assertEqual(config.mode(), "staff")
        self.assertEqual(config.env(), "test")
        self.assertEqual(config.lifetime_minutes(), 15)
        self.assertEqual(config.lifetime_seconds(), 900)
        self.assertIs(config.send_buyer_email(), True)
        self.assertEqual(config.api_base_url(), "https://api.gopay.kg")

    def test_constants(self):
        self.assertEqual(config.MODES, ("off", "staff", "on"))
        self.assertEqual(config.ENVS, ("test", "live"))
        self.assertEqual(config.WEBHOOK_PATH, "/api/payments/gopay/webhook/")
        self.assertEqual(config.WEBHOOK_EVENTS, ("payment.committed", "payment.failed",
                                                 "payment.expired", "payment.cancelled"))
        self.assertEqual(config.WEBHOOK_EVENTS_OPTIONAL, ("receipt.sent",))
        self.assertEqual((config.RT_MODE, config.RT_ENV, config.RT_LIFETIME,
                          config.RT_SEND_BUYER_EMAIL),
                         ("gopay_mode", "gopay_env", "gopay_lifetime_minutes",
                          "gopay_send_buyer_email"))
        self.assertEqual(config.runtime_key("test", "api_key"), "GOPAY_TEST_API_KEY")
        self.assertEqual(config.runtime_key("live", "webhook_secret"), "GOPAY_LIVE_WEBHOOK_SECRET")
        for env, field in (("prod", "api_key"), ("test", "password"), ("", "")):
            with self.assertRaises(ValueError):
                config.runtime_key(env, field)

    def test_garbage_mode_and_env(self):
        with override_settings(GOPAY_MODE="everyone", GOPAY_ENV="prod"):
            self.assertEqual(config.mode(), "off")
            self.assertEqual(config.env(), "test")
        with override_settings(GOPAY_MODE=" ON ", GOPAY_ENV=" Live "):
            self.assertEqual(config.mode(), "on")
            self.assertEqual(config.env(), "live")
        set_runtime(config.RT_MODE, "nonsense")
        set_runtime(config.RT_ENV, "nonsense")
        self.assertEqual(config.mode(), "off")
        self.assertEqual(config.env(), "test")

    def test_lifetime_clamp(self):
        for raw, expected in ((0, 5), (5000, 1440), ("abc", 15), (4, 5), (5, 5), (1440, 1440),
                              (30, 30), (-7, 5)):
            with override_settings(GOPAY_LIFETIME_MINUTES=raw):
                self.assertEqual(config.lifetime_minutes(), expected, raw)
        for raw, expected in (("0", 5), ("5000", 1440), ("abc", 15), ("45", 45)):
            set_runtime(config.RT_LIFETIME, raw)
            self.assertEqual(config.lifetime_minutes(), expected, raw)
            self.assertEqual(config.lifetime_seconds(), expected * 60)

    def test_runtime_overrides_settings_and_falls_back(self):
        set_runtime(config.RT_MODE, "on")
        set_runtime(config.RT_ENV, "live")
        set_runtime(config.RT_SEND_BUYER_EMAIL, False)
        set_runtime("GOPAY_TEST_API_KEY", "dummy-runtime-key-not-real")
        self.assertEqual((config.mode(), config.env()), ("on", "live"))
        self.assertIs(config.send_buyer_email(), False)
        self.assertEqual(config.credentials("test").api_key, "dummy-runtime-key-not-real")
        for key in (config.RT_MODE, config.RT_ENV, config.RT_SEND_BUYER_EMAIL,
                    "GOPAY_TEST_API_KEY"):
            delete_runtime(key)
        self.assertEqual((config.mode(), config.env()), ("staff", "test"))
        self.assertIs(config.send_buyer_email(), True)
        self.assertEqual(config.credentials("test").api_key, API_KEY)

    def test_runtime_failure_falls_back_to_settings(self):
        with patch("adminapi.runtime.get_runtime", side_effect=RuntimeError("cache down")):
            self.assertEqual((config.mode(), config.env()), ("staff", "test"))
            self.assertEqual(config.lifetime_minutes(), 15)
            self.assertEqual(config.credentials().api_key, API_KEY)

    def test_credentials(self):
        self.assertEqual(config.credentials(), creds("test"))
        self.assertEqual(config.credentials("live"), creds("live"))
        with override_settings(GOPAY_ENV="live", GOPAY_LIVE_API_KEY=f"  {LIVE_API_KEY}  "):
            self.assertEqual(config.credentials().env, "live")
            self.assertEqual(config.credentials().api_key, LIVE_API_KEY)
        with self.assertRaises(ValueError):
            config.credentials("prod")
        self.assertTrue(config.is_configured())
        self.assertTrue(config.is_configured("live"))
        self.assertFalse(config.is_configured("prod"))
        with override_settings(GOPAY_LIVE_API_SECRET=""):
            self.assertFalse(config.is_configured("live"))
        # Секрет вебхуков для «настроено» не нужен.
        with override_settings(GOPAY_TEST_WEBHOOK_SECRET=""):
            self.assertTrue(config.is_configured("test"))

    def test_enabled_for_truth_table(self):
        rows = 0
        for mode in config.MODES:
            for env in config.ENVS:
                for configured in (True, False):
                    for is_staff in (True, False):
                        overrides = {"GOPAY_MODE": mode, "GOPAY_ENV": env}
                        if not configured:
                            overrides[f"GOPAY_{env.upper()}_API_SECRET"] = ""
                        if mode == "off" or not configured:
                            expected = False
                        elif env == "test":
                            expected = is_staff
                        elif mode == "on":
                            expected = True
                        else:
                            expected = is_staff
                        with override_settings(**overrides):
                            self.assertIs(config.enabled_for(is_staff), expected,
                                          (mode, env, configured, is_staff))
                        rows += 1
        self.assertEqual(rows, 24)
        with override_settings(GOPAY_MODE="on", GOPAY_ENV="test"):
            self.assertFalse(config.enabled_for(False))
        with override_settings(GOPAY_MODE="on", GOPAY_ENV="live"):
            self.assertTrue(config.enabled_for(False))

    def test_is_staff_user_and_is_enabled_for(self):
        User = get_user_model()
        normal = User.objects.create_user(email="n@example.com", password="x")
        staff = User.objects.create_user(email="s@example.com", password="x", is_staff=True)
        boss = User.objects.create_user(email="b@example.com", password="x", is_superuser=True)

        class Exploding:
            @property
            def is_authenticated(self):
                raise RuntimeError("boom")

        self.assertFalse(config.is_staff_user(None))
        self.assertFalse(config.is_staff_user(AnonymousUser()))
        self.assertFalse(config.is_staff_user(normal))
        self.assertTrue(config.is_staff_user(staff))
        self.assertTrue(config.is_staff_user(boss))
        self.assertFalse(config.is_staff_user(Exploding()))
        self.assertTrue(config.is_enabled_for(staff))
        self.assertFalse(config.is_enabled_for(normal))
        self.assertFalse(config.is_enabled_for())

    def test_webhook_secrets_order_and_omission(self):
        self.assertEqual(config.webhook_secrets(),
                         [("test", WEBHOOK_SECRET), ("live", LIVE_WEBHOOK_SECRET)])
        with override_settings(GOPAY_ENV="live"):
            self.assertEqual(config.webhook_secrets(),
                             [("live", LIVE_WEBHOOK_SECRET), ("test", WEBHOOK_SECRET)])
        with override_settings(GOPAY_TEST_WEBHOOK_SECRET=""):
            self.assertEqual(config.webhook_secrets(), [("live", LIVE_WEBHOOK_SECRET)])
        with override_settings(GOPAY_TEST_WEBHOOK_SECRET="", GOPAY_LIVE_WEBHOOK_SECRET=" "):
            self.assertEqual(config.webhook_secrets(), [])

    def test_mask_tail(self):
        self.assertEqual(config.mask_tail(""), "")
        self.assertEqual(config.mask_tail(None), "")
        self.assertEqual(config.mask_tail("1234567"), "…")
        self.assertEqual(config.mask_tail("12345678"), "…5678")
        self.assertEqual(config.mask_tail(API_KEY), "…real")

    def test_clean_secret(self):
        self.assertEqual(config.clean_secret(""), "")
        self.assertEqual(config.clean_secret("   "), "")
        self.assertEqual(config.clean_secret("  abcDEF12-_=+/  "), "abcDEF12-_=+/")
        self.assertEqual(config.clean_secret("x" * 256), "x" * 256)
        bad = ("abcd efgh1", "1234567", "секретный-ключ", "x" * 257, "abcdefgh\tijk",
               None, 12345678, True, ["abcdefgh"], b"abcdefgh")
        for value in bad:
            with self.assertRaises(ValueError) as ctx:
                config.clean_secret(value)
            if isinstance(value, str):
                self.assertNotIn(value, str(ctx.exception))

    def test_webhook_url_only_from_settings(self):
        self.assertEqual(config.webhook_url(), "https://esai.test/api/payments/gopay/webhook/")
        with override_settings(SITE_BASE_URL="https://esai.kg/"):
            self.assertEqual(config.webhook_url(), "https://esai.kg/api/payments/gopay/webhook/")
        with override_settings(SITE_BASE_URL=""):
            self.assertEqual(config.webhook_url(), "")
        import inspect

        # Адрес нельзя собрать из запроса: у функции нет ни одного параметра.
        self.assertEqual(len(inspect.signature(config.webhook_url).parameters), 0)

    def test_api_base_url_is_https_only(self):
        with override_settings(GOPAY_API_URL="https://api.gopay.kg/"):
            self.assertEqual(config.api_base_url(), "https://api.gopay.kg")
        with override_settings(GOPAY_API_URL="http://api.gopay.kg", DEBUG=False):
            self.assertEqual(config.api_base_url(), "")
            with self.assertRaises(GoPayError) as ctx:
                gp_client.get_client("test")
            self.assertEqual(ctx.exception.kind, "not_configured")
        with override_settings(GOPAY_API_URL="http://localhost:9", DEBUG=True):
            self.assertEqual(config.api_base_url(), "http://localhost:9")

    def test_get_client(self):
        self.assertIsInstance(gp_client.get_client("test"), GoPayClient)
        for env, overrides in (("live", {"GOPAY_LIVE_API_KEY": ""}),
                               ("test", {"GOPAY_TEST_API_SECRET": ""}),
                               ("prod", {})):
            with override_settings(**overrides):
                with self.assertRaises(GoPayError) as ctx:
                    gp_client.get_client(env)
                self.assertEqual((ctx.exception.code, ctx.exception.kind),
                                 ("not_configured", "not_configured"))

    def test_public_state_has_no_secret_values(self):
        state = config.public_state()
        dumped = json.dumps(state, ensure_ascii=False)
        for secret in ALL_SECRETS:
            self.assertNotIn(secret, dumped)
        self.assertEqual(set(state), {"mode", "env", "lifetime_minutes", "send_buyer_email",
                                      "configured", "effective", "webhook_url", "webhook_events",
                                      "webhook_events_optional", "api_host", "test", "live"})
        self.assertEqual(state["webhook_events_optional"], ["receipt.sent"])
        self.assertEqual(state["webhook_events"], list(config.WEBHOOK_EVENTS))
        self.assertEqual(state["api_host"], "api.gopay.kg")
        self.assertEqual(state["effective"], {"public": False, "staff": True})
        self.assertEqual(state["test"], {"api_key_set": True, "api_key_tail": "…real",
                                         "api_secret_set": True, "webhook_secret_set": True})
        self.assertIs(state["configured"], True)
        with override_settings(GOPAY_TEST_API_KEY="", GOPAY_TEST_API_SECRET="",
                               GOPAY_TEST_WEBHOOK_SECRET=""):
            empty = config.public_state()
        self.assertEqual(empty["test"], {"api_key_set": False, "api_key_tail": "",
                                         "api_secret_set": False, "webhook_secret_set": False})
        self.assertIs(empty["configured"], False)
        self.assertEqual(empty["effective"], {"public": False, "staff": False})


class ProjectSettingsTests(SimpleTestCase):
    def test_throttle_logger_and_beat_are_declared(self):
        rates = settings.REST_FRAMEWORK["DEFAULT_THROTTLE_RATES"]
        self.assertEqual(rates["gopay_status"], "90/min")
        self.assertEqual(rates["gopay_cancel"], "10/min")
        self.assertEqual(rates["gopay_webhook"], "600/min")
        self.assertEqual(settings.LOGGING["loggers"]["payments.gopay"],
                         {"handlers": ["file"], "level": "INFO", "propagate": False})
        entry = settings.CELERY_BEAT_SCHEDULE["payments:reconcile_gopay_invoices"]
        self.assertEqual(entry["task"], "payments.tasks.reconcile_gopay_invoices")
        self.assertEqual(entry["schedule"], timedelta(minutes=1))


# ====================================================== создание счёта ===

@override_settings(**GOPAY_SETTINGS)
class CreateInvoiceTests(GoPayTestCase):
    def create(self, payment, **over):
        kwargs = dict(description=DESC, lifetime_seconds=900, buyer_email="buyer@example.com",
                      success_url="https://esai.test/profile?payment=tokens_success",
                      failure_url="https://esai.test/profile?payment=tokens_failed")
        kwargs.update(over)
        return service.create_invoice(payment, **kwargs)

    def assert_refused(self, payment, code, kind=None, **over):
        with self.assertRaises(GoPayError) as ctx:
            self.create(payment, **over)
        self.assertEqual(ctx.exception.code, code)
        if kind:
            self.assertEqual(ctx.exception.kind, kind)
        self.assertFalse(GoPayInvoice.objects.filter(payment=payment).exists())
        return ctx.exception

    def test_happy_path(self):
        payment = self.make_payment(env="live")
        self.fake.on("/v1/payments", ok(pay_data(status="CREATED")))
        invoice = self.create(payment)

        create_call = self.fake.calls[0]
        self.assertEqual(create_call.headers["GoPay-Api-Key"], LIVE_API_KEY)
        self.assertEqual(create_call.body["order_id"], ORDER)
        self.assertEqual(create_call.body["amount"], "392.00")
        self.assertEqual(create_call.body["lifetime"], 900)
        self.assertEqual(create_call.body["buyer"], {"email": "buyer@example.com"})
        self.assertIn("success_url", create_call.body)

        invoice.refresh_from_db()
        self.assertEqual((invoice.env, invoice.provider_payment_id, invoice.status),
                         ("live", PID, "created"))
        self.assertEqual(invoice.amount, Decimal("392.00"))
        self.assertEqual(invoice.lifetime_seconds, 900)
        self.assertEqual(invoice.qr_data, QR_DATA)
        self.assertEqual(invoice.qr_url, f"https://pay.gopay.kg/p/{PID}/qr/")
        self.assertEqual(invoice.checkout_url, f"https://pay.gopay.kg/p/{PID}/")
        self.assertEqual(invoice.app_links, {"mbank": "mbank://elqr?data=abc",
                                             "megapay": "megapay://payment?x=1"})
        self.assertEqual(invoice.provider_expires_at, "2026-10-06T10:15:00")
        self.assertIsNotNone(invoice.last_checked_at)
        self.assertIsNone(invoice.cancel_requested_at)
        self.assertEqual(invoice.flags, {})
        # Наш срок считается от момента ДО запроса: не позже, чем у GoPay.
        self.assertLessEqual(invoice.expires_at, create_call.at + timedelta(seconds=900))
        self.assertGreater(invoice.expires_at,
                           create_call.at + timedelta(seconds=900) - timedelta(seconds=5))

        payment.refresh_from_db()
        raw = state_of(status="CREATED").raw
        self.assertEqual(payment.response, {"gopay_create": raw})
        self.assertNotIn("redirect_url", payment.response)
        self.assertNotIn("qr_data", json.dumps(payment.response))
        self.assertFalse(payment.success)
        self.assertEqual(service.invoice_of(payment).pk, invoice.pk)

    def test_expires_at_is_t0_plus_lifetime(self):
        payment = self.make_payment(env="live")
        self.fake.on("/v1/payments", ok(pay_data()))
        t0 = timezone.now()
        with patch("payments.gopay.service.timezone.now", return_value=t0):
            invoice = self.create(payment, lifetime_seconds=1200)
        self.assertEqual(invoice.expires_at, t0 + timedelta(seconds=1200))
        self.assertEqual(invoice.lifetime_seconds, 1200)

    def test_pending_status_is_accepted(self):
        payment = self.make_payment(env="live")
        self.fake.on("/v1/payments", ok(pay_data(status="PENDING")))
        self.assertEqual(self.create(payment).status, "pending")

    def test_timeout_then_query_adopts(self):
        payment = self.make_payment(env="live")
        self.fake.on("/v1/payments", requests.Timeout())
        self.fake.on("/v1/payments/query", ok(pay_data()))
        invoice = self.create(payment)
        self.assertEqual(invoice.provider_payment_id, PID)
        self.assertEqual(self.fake.bodies("/v1/payments/query"), [{"order_id": ORDER}])
        self.assertEqual(self.fake.paths()[:2], ["/v1/payments", "/v1/payments/query"])

    def test_duplicate_then_query_adopts(self):
        payment = self.make_payment(env="live")
        self.fake.on("/v1/payments", fail("4005", "Duplicate order_id"))
        self.fake.on("/v1/payments/query", ok(pay_data()))
        self.assertEqual(self.create(payment).provider_payment_id, PID)

    def test_unknown_rejection_adopts_when_found(self):
        payment = self.make_payment(env="live")
        self.fake.on("/v1/payments", fail("0009", "something odd"))
        self.fake.on("/v1/payments/query", ok(pay_data()))
        self.assertEqual(self.create(payment).provider_payment_id, PID)

    def test_unknown_rejection_raises_original_when_not_found(self):
        payment = self.make_payment(env="live")
        self.fake.on("/v1/payments", fail("0009", "something odd"))
        self.fake.on("/v1/payments/query", fail("4041", "Payment not found"))
        exc = self.assert_refused(payment, "rejected", "other")
        self.assertEqual(exc.provider_code, "0009")

    def test_timeout_and_not_found_raises_original(self):
        payment = self.make_payment(env="live")
        self.fake.on("/v1/payments", requests.Timeout())
        self.fake.on("/v1/payments/query", fail("4041", "Payment not found"))
        self.assert_refused(payment, "network", "unavailable")
        payment.refresh_from_db()
        self.assertEqual(payment.response, {})

    def test_timeout_and_query_timeout_raises_original(self):
        payment = self.make_payment(env="live")
        self.fake.on("/v1/payments", html(502))
        self.fake.on("/v1/payments/query", requests.Timeout())
        self.assert_refused(payment, "http_502", "unavailable")

    def test_invalid_with_urls_retries_once_without_them(self):
        payment = self.make_payment(env="live")
        self.fake.on("/v1/payments", fail("4004", "Invalid uri"), ok(pay_data()))
        invoice = self.create(payment)
        self.assertEqual(invoice.provider_payment_id, PID)
        first, second = self.fake.bodies("/v1/payments")
        self.assertIn("success_url", first)
        self.assertEqual(first["buyer"], {"email": "buyer@example.com"})
        self.assertNotIn("success_url", second)
        self.assertNotIn("failure_url", second)
        # Повтор идёт без ВСЕГО необязательного: что именно не понравилось GoPay,
        # из ответа не узнать, а почту он проверяет строже нас.
        self.assertNotIn("buyer", second)
        self.assertEqual({k: second[k] for k in ("order_id", "amount", "lifetime")},
                         {k: first[k] for k in ("order_id", "amount", "lifetime")})
        self.assertNotIn("/v1/payments/query", self.fake.paths())

    def test_invalid_because_of_the_email_retries_without_it(self):
        # Адресов возврата нет вовсе (сайт не на https), а почту покупателя GoPay
        # не принял: без повтора этот покупатель не смог бы платить по QR никогда.
        payment = self.make_payment(env="live")
        self.fake.on("/v1/payments", fail("4004", "buyer.email is not a valid email"),
                     ok(pay_data()))
        invoice = self.create(payment, buyer_email="odd@address", success_url="",
                              failure_url="")
        self.assertEqual(invoice.provider_payment_id, PID)
        first, second = self.fake.bodies("/v1/payments")
        self.assertEqual(first["buyer"], {"email": "odd@address"})
        self.assertNotIn("success_url", first)
        self.assertNotIn("buyer", second)
        self.assertEqual(self.fake.paths().count("/v1/payments"), 2)
        self.assertNotIn("/v1/payments/query", self.fake.paths())

    def test_invalid_twice_is_not_retried_again(self):
        payment = self.make_payment(env="live")
        self.fake.on("/v1/payments", fail("4004", "Invalid amount"))
        self.assert_refused(payment, "invalid_request", "invalid")
        self.assertEqual(self.fake.paths(), ["/v1/payments", "/v1/payments"])

    def test_invalid_without_optional_fields_is_not_retried(self):
        payment = self.make_payment(env="live")
        self.fake.on("/v1/payments", fail("4004", "Invalid amount"))
        self.assert_refused(payment, "invalid_request", "invalid", success_url="",
                            failure_url="", buyer_email="")
        self.assertEqual(self.fake.paths(), ["/v1/payments"])
        # Негодная пара адресов — то же самое, что без адресов: повторять нечего.
        self.fake.calls.clear()
        self.assert_refused(payment, "invalid_request", "invalid", buyer_email="",
                            success_url="https://esai.test/мой профиль")
        self.assertEqual(self.fake.paths(), ["/v1/payments"])
        # Почта выключена в админке — в запрос она не попала, значит, и убирать нечего.
        self.fake.calls.clear()
        with override_settings(GOPAY_SEND_BUYER_EMAIL=False):
            self.assert_refused(payment, "invalid_request", "invalid", success_url="",
                                failure_url="")
        self.assertEqual(self.fake.paths(), ["/v1/payments"])

    def test_auth_and_org_errors_propagate_without_adoption(self):
        payment = self.make_payment(env="live")
        for code, our, kind in (("4001", "auth", "auth"), ("0016", "org_inactive", "org_inactive"),
                                ("0004", "rate_limited", "rate_limited")):
            self.fake.calls.clear()
            self.fake.on("/v1/payments", fail(code, "x"))
            self.assert_refused(payment, our, kind)
            self.assertEqual(self.fake.paths(), ["/v1/payments"])

    def test_order_or_amount_mismatch_cancels_and_refuses(self):
        payment = self.make_payment(env="live")
        self.fake.on("/v1/payments/cancel", ok(pay_data(status="CANCELLED")))
        for over in ({"order_id": "tokpkg-9-9-ffffffffff"}, {"amount": "39.20"},
                     {"amount": "391.996"}, {"amount": None}):
            self.fake.calls.clear()
            self.fake.on("/v1/payments", ok(pay_data(**over)))
            self.assert_refused(payment, "response_mismatch", "mismatch")
            self.assertEqual(self.fake.bodies("/v1/payments/cancel"), [{"payment_id": PID}])

    def test_failed_cancel_of_a_refused_invoice_changes_nothing(self):
        payment = self.make_payment(env="live")
        self.fake.on("/v1/payments", ok(pay_data(amount="1.00")))
        self.fake.on("/v1/payments/cancel", requests.Timeout())
        self.assert_refused(payment, "response_mismatch", "mismatch")

    def test_mode_mismatch(self):
        self.fake.on("/v1/payments/cancel", ok(pay_data(status="CANCELLED")))
        live = self.make_payment(env="live")
        self.fake.on("/v1/payments", ok(pay_data(testing_mode=True)))
        self.assert_refused(live, "mode_mismatch", "mismatch")
        self.assertIn("/v1/payments/cancel", self.fake.paths())

        test = self.make_payment(env="test", order_id="tokpkg-7-3-1111111111")
        self.fake.on("/v1/payments", ok(pay_data(order_id="tokpkg-7-3-1111111111")))
        self.assert_refused(test, "mode_mismatch", "mismatch")

    def test_ambiguous_testing_mode_is_refused_in_both_envs(self):
        self.fake.on("/v1/payments/cancel", ok(pay_data(status="CANCELLED")))
        for env, order in (("live", "tokpkg-7-3-aaaaaaaaaa"), ("test", "tokpkg-7-3-bbbbbbbbbb")):
            payment = self.make_payment(env=env, order_id=order)
            self.fake.on("/v1/payments", ok(pay_data(order_id=order, testing_mode="yes")))
            self.assert_refused(payment, "mode_mismatch", "mismatch")

    def test_live_without_qr_data_is_incomplete(self):
        payment = self.make_payment(env="live")
        self.fake.on("/v1/payments/cancel", ok(pay_data(status="CANCELLED")))
        self.fake.on("/v1/payments", ok(pay_data(qr_data=...)))
        self.assert_refused(payment, "incomplete_response", "mismatch")
        self.assertIn("/v1/payments/cancel", self.fake.paths())

    def test_missing_payment_id_is_incomplete(self):
        payment = self.make_payment(env="live")
        self.fake.on("/v1/payments", ok(pay_data(payment_id=...)))
        self.assert_refused(payment, "incomplete_response", "mismatch")
        self.assertNotIn("/v1/payments/cancel", self.fake.paths())

    def test_unexpected_status_is_refused(self):
        payment = self.make_payment(env="live")
        for status in ("COMMITTED", "EXPIRED", "SOMETHING"):
            self.fake.on("/v1/payments", ok(pay_data(status=status)))
            self.assert_refused(payment, "unexpected_status", "mismatch")

    def test_test_env_without_qr_data_still_runs_the_chain(self):
        payment = self.make_payment(env="test")
        self.fake.on("/v1/payments", ok({"payment_id": PID, "order_id": ORDER, "amount": "392.00",
                                         "status": "CREATED", "testing_mode": True}))
        invoice = self.create(payment)
        self.assertEqual(invoice.qr_data, "")
        self.assertEqual(invoice.env, "test")
        self.assertEqual(self.fake.calls[0].headers["GoPay-Api-Key"], API_KEY)
        data = service.invoice_json(invoice)
        self.assertEqual(data["qr"], {"data": "", "image_url": ""})
        self.assertEqual(data["ui_state"], "awaiting_payment")
        self.assertIs(data["is_test"], True)

        committed = PaymentState.from_payload({
            "payment_id": PID, "order_id": ORDER, "amount": "392.00", "status": "COMMITTED",
            "testing_mode": True, "committed_at": "2026-10-06T10:00:20Z"})
        self.assertEqual(service.apply_state(invoice, committed, source="query"), "credited")
        self.assertEqual(self.balance(self.staff), 500)

    def test_test_env_for_a_non_staff_user_is_refused_before_http(self):
        payment = self.make_payment(env="test", user=self.user)
        exc = self.assert_refused(payment, "test_non_staff", "mismatch")
        self.assertIsInstance(exc, GoPayError)
        payment_without_user = self.make_payment(env="test", user=None,
                                                 order_id="tokpkg-0-3-cccccccccc")
        self.assert_refused(payment_without_user, "test_non_staff", "mismatch")
        self.assertEqual(self.fake.calls, [])

    def test_open_circuit_is_refused_before_http(self):
        payment = self.make_payment(env="live")
        cache.set("gopay:down:live", 1, 45)
        exc = self.assert_refused(payment, "circuit_open", "unavailable")
        self.assertIsInstance(exc, GoPayUnavailable)
        self.assertEqual(self.fake.calls, [])
        # Свой быстрый отказ здоровье не портит.
        self.assertEqual(service.health("live")["fails"], 0)

    def test_not_configured_is_refused_before_http(self):
        payment = self.make_payment(env="live")
        with override_settings(GOPAY_LIVE_API_SECRET=""):
            self.assert_refused(payment, "not_configured", "not_configured")
        bad_env = self.make_payment(env="live", order_id="tokpkg-7-3-dddddddddd")
        bad_env.request["gopay"]["env"] = "prod"
        self.assert_refused(bad_env, "not_configured", "not_configured")
        no_env = self.make_payment(env="live", order_id="tokpkg-7-3-eeeeeeeeee")
        no_env.request.pop("gopay")
        self.assert_refused(no_env, "not_configured", "not_configured")
        self.assertEqual(self.fake.calls, [])

    def test_too_long_order_id_is_our_error_not_a_crash(self):
        payment = self.make_payment(env="live", order_id="tokpkg-" + "9" * 30)
        self.assert_refused(payment, "bad_order", "mismatch")
        self.assertEqual(self.fake.calls, [])

    def test_unsafe_app_links_and_urls_are_filtered(self):
        payment = self.make_payment(env="live")
        self.fake.on("/v1/payments", ok(pay_data(
            qr_url="http://pay.gopay.kg/qr.png", checkout_url="https://pay.gopay.kg/" + "p" * 600,
            app_links={
                "mbank": "mbank://elqr?data=abc",
                "optima": "https://optima24.kg/pay?x=1",
                "evil": "javascript:alert(1)",
                "evil2": "JaVaScRiPt:alert(1)",
                "datauri": "data:text/html,<script>1</script>",
                "local": "file:///etc/passwd",
                "bad key!": "mbank://x",
                "k" * 33: "mbank://x",
                "noscheme": "//example.com",
                "long": "mbank://" + "x" * 2000,
                "number": 5,
            })))
        invoice = self.create(payment)
        self.assertEqual(invoice.app_links, {"mbank": "mbank://elqr?data=abc",
                                             "optima": "https://optima24.kg/pay?x=1"})
        self.assertEqual(invoice.qr_url, "")
        self.assertEqual(invoice.checkout_url, "")

    def test_app_links_are_capped(self):
        payment = self.make_payment(env="live")
        links = {f"bank{i}": f"bank{i}://pay" for i in range(40)}
        self.fake.on("/v1/payments", ok(pay_data(app_links=links)))
        self.assertEqual(len(self.create(payment).app_links), service.APPS_MAX)

    def test_buyer_email_switch_and_synthetic_address(self):
        payment = self.make_payment(env="live")
        self.fake.on("/v1/payments", ok(pay_data()))
        with override_settings(GOPAY_SEND_BUYER_EMAIL=False):
            self.create(payment)
        self.assertNotIn("buyer", self.fake.bodies("/v1/payments")[0])

        other = self.make_payment(env="live", order_id="tokpkg-7-3-9999999999")
        self.fake.calls.clear()
        self.fake.on("/v1/payments", ok(pay_data(order_id="tokpkg-7-3-9999999999",
                                                 payment_id="b" * 32)))
        self.create(other, buyer_email="tg555@social.esai.local")
        self.assertNotIn("buyer", self.fake.bodies("/v1/payments")[0])

    def test_duplicate_invoice_row_is_a_gopay_error_and_keeps_the_transaction(self):
        first = self.make_payment(env="live")
        self.make_invoice(first)
        second = self.make_payment(env="live", order_id="tokpkg-7-3-2222222222")
        self.fake.on("/v1/payments", ok(pay_data(order_id="tokpkg-7-3-2222222222")))
        with self.assertRaises(GoPayError) as ctx:
            self.create(second)
        self.assertEqual(ctx.exception.code, "duplicate_invoice")
        # Транзакция жива: точка сохранения поймала нарушение уникальности.
        self.assertEqual(GoPayInvoice.objects.count(), 1)

    def test_apps_are_fetched_once_and_only_for_live(self):
        apps = [{"code": "mbank", "name": "MBank", "order": 1, "url": "mbank://elqr?data={qr_data}",
                 "icon": "https://media.gopay.kg/apps/mbank.png",
                 "android_package_name": "kg.mbank", "is_active_on_ios": True}]
        self.fake.on("/v1/payment-app", ok(apps))
        self.fake.on("/v1/payments", ok(pay_data()))
        self.create(self.make_payment(env="live"))
        self.assertEqual(self.fake.paths(), ["/v1/payments", "/v1/payment-app"])
        self.assertEqual([a["code"] for a in service.cached_apps("live")], ["mbank"])

        self.fake.calls.clear()
        self.fake.on("/v1/payments", ok(pay_data(order_id="tokpkg-7-3-3333333333",
                                                 payment_id="c" * 32)))
        self.create(self.make_payment(env="live", order_id="tokpkg-7-3-3333333333"))
        self.assertEqual(self.fake.paths(), ["/v1/payments"])

        self.fake.calls.clear()
        self.fake.on("/v1/payments", ok(pay_data(order_id="tokpkg-7-3-4444444444",
                                                 payment_id="d" * 32, testing_mode=True)))
        self.create(self.make_payment(env="test", order_id="tokpkg-7-3-4444444444"))
        self.assertEqual(self.fake.paths(), ["/v1/payments"])

    def test_failing_apps_call_never_fails_the_purchase(self):
        self.fake.on("/v1/payment-app", requests.Timeout())
        self.fake.on("/v1/payments", ok(pay_data()))
        invoice = self.create(self.make_payment(env="live"))
        self.assertEqual(invoice.status, "created")
        # И на следующем счёте мы не ждём этот метод заново.
        self.fake.calls.clear()
        self.fake.on("/v1/payments", ok(pay_data(order_id="tokpkg-7-3-5555555555",
                                                 payment_id="e" * 32)))
        self.create(self.make_payment(env="live", order_id="tokpkg-7-3-5555555555"))
        self.assertEqual(self.fake.paths(), ["/v1/payments"])

    def test_nothing_secret_is_stored_or_logged(self):
        payment = self.make_payment(env="live")
        self.fake.on("/v1/payments", ok(pay_data()))
        with self.assertLogs("payments.gopay", level="INFO") as logs:
            invoice = self.create(payment)
        payment.refresh_from_db()
        invoice.refresh_from_db()
        stored = json.dumps([payment.request, payment.response, payment.error, invoice.flags,
                             invoice.app_links], ensure_ascii=False) + "".join(logs.output)
        call = self.fake.calls[0]
        for secret in ALL_SECRETS + (call.headers["GoPay-Nonce"], call.headers["GoPay-Signature"]):
            self.assertNotIn(secret, stored)


# ================================================== применение статуса ===

@override_settings(**GOPAY_SETTINGS)
class ApplyStateTests(GoPayTestCase):
    def setUp(self):
        super().setUp()
        # Оплачено полминуты назад: тесты не должны зависеть от даты на часах.
        self.paid_at = timezone.now() - timedelta(seconds=30)

    def committed(self, **over):
        over.setdefault("status", "COMMITTED")
        over.setdefault("committed_at", self.paid_at.isoformat().replace("+00:00", "Z"))
        over.setdefault("bank_op_date", "2026-10-06")
        return state_of(**over)

    def reload(self, invoice):
        invoice.refresh_from_db()
        invoice.payment.refresh_from_db()
        return invoice

    def test_committed_credits_once(self):
        invoice = self.make_invoice()
        self.assertEqual(service.apply_state(invoice, self.committed(), source="query"),
                         "credited")
        self.assertEqual(self.balance(), 500)
        self.reload(invoice)
        self.assertEqual(invoice.status, "committed")
        self.assertTrue(invoice.payment.success)
        self.assertEqual(invoice.payment.error, "")
        self.assertTrue(invoice.payment.response["token_purchase_applied"])
        self.assertEqual(str(invoice.bank_op_date), "2026-10-06")
        self.assertEqual(invoice.committed_at, self.paid_at)
        self.assertIsNotNone(invoice.finalized_at)
        self.assertIsNotNone(invoice.last_checked_at)
        self.assertIsNone(invoice.last_webhook_at)
        self.assertEqual(invoice.flags, {})

        # Повтор — из любого источника — ничего не добавляет.
        for source in ("webhook", "reconcile", "admin", "query"):
            self.assertEqual(service.apply_state(invoice, self.committed(), source=source),
                             "already")
        self.assertEqual(self.balance(), 500)
        self.assertEqual(self.ledger(), 1)
        self.reload(invoice)
        self.assertTrue(invoice.payment.success)
        self.assertIsNotNone(invoice.last_webhook_at)
        self.assertEqual(self.review_events().count(), 0)

    def test_two_interleaved_deliveries_credit_once(self):
        invoice = self.make_invoice()
        # Две копии, прочитанные до первой обработки: вторая начинает после того,
        # как первая отпустила блокировку, и видит уже начисленный заказ.
        first = GoPayInvoice.objects.get(pk=invoice.pk)
        second = GoPayInvoice.objects.get(pk=invoice.pk)
        self.assertEqual(service.apply_state(first, self.committed(), source="webhook"),
                         "credited")
        self.assertEqual(service.apply_state(second, self.committed(), source="query"),
                         "already")
        self.assertEqual(self.ledger(), 1)
        self.assertEqual(self.balance(), 500)

    def test_naive_committed_at_is_replaced_by_our_clock(self):
        invoice = self.make_invoice()
        before = timezone.now()
        service.apply_state(invoice, self.committed(committed_at="2026-10-06T10:03:00"),
                            source="query")
        self.reload(invoice)
        self.assertGreaterEqual(invoice.committed_at, before)

    def test_mismatches_never_credit(self):
        cases = (
            ("amount", {"amount": "39.20"}, "amount_mismatch"),
            ("payment_id", {"payment_id": "f" * 32}, "gopay_mismatch:payment_id"),
            ("order_id", {"order_id": "tokpkg-7-3-ffffffffff"}, "gopay_mismatch:order_id"),
            ("mode", {"testing_mode": True}, "gopay_mismatch:mode"),
        )
        for index, (what, over, error) in enumerate(cases):
            order = f"tokpkg-7-3-000000000{index}"
            payment = self.make_payment(order_id=order)
            invoice = self.make_invoice(payment, provider_payment_id=f"{index}" * 32)
            base = {"order_id": order, "payment_id": f"{index}" * 32}
            base.update(over)
            self.assertEqual(service.apply_state(invoice, self.committed(**base), source="query"),
                             "mismatch", what)
            self.reload(invoice)
            self.assertEqual(invoice.flags["needs_review"], f"mismatch:{what}")
            self.assertFalse(invoice.payment.success)
            self.assertEqual(invoice.payment.error, error)
            self.assertNotIn("token_purchase_applied", invoice.payment.response)
        self.assertEqual(self.balance(), 0)
        self.assertEqual(self.ledger(), 0)

    def test_committed_without_ids_is_a_mismatch(self):
        for index, over in enumerate(({"order_id": ""}, {"payment_id": ""},
                                      {"order_id": ..., "payment_id": ...})):
            order = f"tokpkg-7-3-100000000{index}"
            invoice = self.make_invoice(self.make_payment(order_id=order),
                                        provider_payment_id=f"{index}" * 32)
            base = {"order_id": order, "payment_id": f"{index}" * 32}
            base.update(over)
            self.assertEqual(service.apply_state(invoice, self.committed(**base), source="webhook"),
                             "mismatch")
            self.reload(invoice)
            self.assertEqual(invoice.flags["needs_review"], "mismatch:ids_missing")
            self.assertEqual(invoice.payment.error, "gopay_mismatch:ids_missing")
            # Номера не наши — счёт оплаченным не считаем.
            self.assertEqual(invoice.status, "created")
        self.assertEqual(self.ledger(), 0)

    def test_amount_with_three_decimals_is_a_mismatch(self):
        invoice = self.make_invoice()
        self.assertEqual(service.apply_state(invoice, self.committed(amount="391.996"),
                                             source="query"), "mismatch")
        self.reload(invoice)
        self.assertEqual(invoice.flags["needs_review"], "mismatch:amount")
        self.assertEqual(invoice.payment.error, "amount_mismatch")
        self.assertEqual(self.ledger(), 0)

    def test_invoice_amount_and_currency_must_match_too(self):
        payment = self.make_payment()
        invoice = self.make_invoice(payment, amount=Decimal("39.20"))
        self.assertEqual(service.apply_state(invoice, self.committed(), source="query"),
                         "mismatch")
        other = self.make_payment(order_id="tokpkg-7-3-usd0000000")
        Payment.objects.filter(pk=other.pk).update(currency="USD")
        usd = self.make_invoice(other, provider_payment_id="9" * 32)
        self.assertEqual(service.apply_state(
            usd, self.committed(order_id="tokpkg-7-3-usd0000000", payment_id="9" * 32),
            source="query"), "mismatch")
        self.assertEqual(self.ledger(), 0)

    def test_ambiguous_testing_mode_is_a_mismatch_in_both_envs(self):
        live = self.make_invoice()
        self.assertEqual(service.apply_state(live, self.committed(testing_mode="yes"),
                                             source="query"), "mismatch")
        test_payment = self.make_payment(env="test", order_id="tokpkg-7-3-test000000")
        test = self.make_invoice(test_payment, env="test", provider_payment_id="8" * 32)
        self.assertEqual(service.apply_state(
            test, self.committed(order_id="tokpkg-7-3-test000000", payment_id="8" * 32,
                                 testing_mode=2), source="webhook"), "mismatch")
        for invoice in (live, test):
            self.reload(invoice)
            self.assertEqual(invoice.flags["needs_review"], "mismatch:mode")
        self.assertEqual(self.ledger(), 0)
        self.assertEqual(self.ledger(self.staff), 0)

    def test_test_env_missing_flag_is_a_mismatch(self):
        payment = self.make_payment(env="test")
        invoice = self.make_invoice(payment, env="test")
        self.assertEqual(service.apply_state(invoice, self.committed(), source="query"),
                         "mismatch")
        self.assertEqual(self.ledger(self.staff), 0)

    def test_test_env_never_credits_a_non_staff_user(self):
        payment = self.make_payment(env="test", user=self.user)
        invoice = self.make_invoice(payment, env="test")
        self.assertEqual(service.apply_state(invoice, self.committed(testing_mode=True),
                                             source="webhook"), "mismatch")
        self.reload(invoice)
        self.assertEqual(invoice.flags["needs_review"], "mismatch:test_non_staff")
        self.assertEqual(invoice.payment.error, "gopay_mismatch:test_non_staff")
        self.assertFalse(invoice.payment.success)
        self.assertEqual(invoice.status, "committed")
        self.assertEqual(self.ledger(), 0)
        self.assertEqual(self.review_events().count(), 1)

    def test_test_env_staff_is_credited_and_stays_test(self):
        payment = self.make_payment(env="test")
        invoice = self.make_invoice(payment, env="test")
        self.assertEqual(service.apply_state(invoice, self.committed(testing_mode=True),
                                             source="query"), "credited")
        self.reload(invoice)
        self.assertTrue(invoice.payment.is_test)
        self.assertTrue(invoice.payment.success)
        self.assertEqual(self.balance(self.staff), 500)

    def test_paid_mismatch_is_committed_under_review(self):
        invoice = self.make_invoice()
        with self.assertLogs("payments.gopay", level="ERROR"):
            self.assertEqual(service.apply_state(invoice, self.committed(amount="39.20"),
                                                 source="query"), "mismatch")
        self.reload(invoice)
        self.assertEqual(invoice.status, "committed")
        self.assertIsNotNone(invoice.committed_at)
        self.assertIsNotNone(invoice.finalized_at)
        self.assertEqual(service.ui_state(invoice), "processing")
        data = service.invoice_json(invoice)
        self.assertEqual((data["qr"], data["apps"], data["can_cancel"]),
                         ({"data": "", "image_url": ""}, [], False))
        # Наши часы такой счёт больше не закрывают.
        GoPayInvoice.objects.filter(pk=invoice.pk).update(
            expires_at=timezone.now() - timedelta(hours=1))
        self.assertFalse(service.mark_expired_locally(invoice))
        self.assertFalse(service.mark_abandoned(invoice, "user"))
        self.assertEqual(service.cancel_invoice(invoice, reason="user"), "committed")
        self.assertEqual(self.fake.calls, [])
        self.reload(invoice)
        self.assertEqual(invoice.status, "committed")

        events = self.review_events()
        self.assertEqual(events.count(), 1)
        event = events.get()
        self.assertEqual(event.meta["what"], "mismatch:amount")
        self.assertEqual(event.meta["order_id"], ORDER)
        self.assertEqual(event.meta["payment_id"], PID)
        self.assertEqual((event.meta["provider"], event.meta["env"]), ("gopay", "live"))
        self.assertEqual(event.user_id, self.user.id)

        # Тот же сигнал в пределах шести часов второй раз не пишется.
        self.assertEqual(service.apply_state(invoice, self.committed(amount="39.20"),
                                             source="reconcile"), "mismatch")
        self.assertEqual(self.review_events().count(), 1)
        self.assertEqual(service.admin_state()["unsettled"], 1)

    def test_mismatch_on_a_non_committed_state_raises_no_alert(self):
        invoice = self.make_invoice()
        self.assertEqual(service.apply_state(invoice, state_of(status="EXPIRED",
                                                               order_id="tokpkg-1-1-zzzzzzzzzz"),
                                             source="webhook"), "mismatch")
        self.reload(invoice)
        self.assertEqual(invoice.status, "created")
        self.assertEqual(invoice.flags["needs_review"], "mismatch:order_id")
        self.assertEqual(self.review_events().count(), 0)

    def test_late_commit_after_local_expiry(self):
        invoice = self.make_invoice(expires_at=timezone.now() - timedelta(minutes=30))
        self.assertTrue(service.mark_expired_locally(invoice))
        self.reload(invoice)
        self.assertEqual(invoice.status, "expired")
        self.assertEqual(invoice.payment.error, "gopay_status:expired")
        self.assertEqual(service.apply_state(invoice, self.committed(), source="reconcile"),
                         "credited")
        self.reload(invoice)
        self.assertEqual(invoice.status, "committed")
        self.assertIs(invoice.flags.get("late_commit"), True)
        self.assertNotIn("local_expiry", invoice.flags)
        self.assertTrue(invoice.payment.success)
        self.assertEqual(invoice.payment.error, "")
        self.assertEqual(self.balance(), 500)

    def test_late_commit_after_cancel(self):
        invoice = self.make_invoice()
        self.assertEqual(service.apply_state(invoice, state_of(status="CANCELLED"),
                                             source="webhook"), "closed")
        self.reload(invoice)
        self.assertEqual(invoice.status, "cancelled")
        self.assertEqual(invoice.payment.error, "gopay_status:cancelled")
        self.assertEqual(service.apply_state(invoice, self.committed(), source="webhook"),
                         "credited")
        self.reload(invoice)
        self.assertIs(invoice.flags.get("late_commit"), True)
        self.assertEqual(self.ledger(), 1)

    def test_late_commit_after_abandonment(self):
        invoice = self.make_invoice()
        self.assertTrue(service.mark_abandoned(invoice, "superseded"))
        self.assertEqual(service.apply_state(invoice, self.committed(), source="query"),
                         "credited")
        self.reload(invoice)
        self.assertIs(invoice.flags.get("late_commit"), True)
        self.assertEqual(invoice.flags.get("abandoned"), "superseded")
        self.assertEqual(self.balance(), 500)

    def test_in_time_commit_is_not_late_even_when_rechecked_later(self):
        invoice = self.make_invoice()
        now = timezone.now()
        in_time = (now - timedelta(seconds=30)).isoformat()
        self.assertEqual(service.apply_state(invoice, self.committed(committed_at=in_time),
                                             source="query"), "credited")
        # Перепроверка через день: срок счёта давно вышел, но оплата была вовремя.
        GoPayInvoice.objects.filter(pk=invoice.pk).update(
            expires_at=now - timedelta(days=1))
        self.assertEqual(service.apply_state(invoice, self.committed(committed_at=in_time),
                                             source="admin"), "already")
        self.reload(invoice)
        self.assertNotIn("late_commit", invoice.flags)

    def test_commit_long_after_our_deadline_is_late(self):
        invoice = self.make_invoice(expires_at=timezone.now() - timedelta(minutes=5))
        self.assertEqual(service.apply_state(
            invoice, self.committed(committed_at=timezone.now().isoformat()), source="reconcile"),
            "credited")
        self.reload(invoice)
        self.assertIs(invoice.flags.get("late_commit"), True)

    def test_discount_that_moved_elsewhere_is_flagged(self):
        other = self.make_payment(order_id="tokpkg-7-4-othe000000")
        payment = self.make_payment(request_extra={"exit_discount": {
            "offer_id": 0, "percent": 20, "original_amount": "490.00"}})
        offer = ExitDiscountOffer.objects.create(
            user=self.user, percent=20, shown_at=timezone.now(), claimed_at=timezone.now(),
            expires_at=timezone.now() + timedelta(hours=1), applied_to_payment=other)
        payment.request["exit_discount"]["offer_id"] = offer.pk
        payment.save(update_fields=["request"])
        invoice = self.make_invoice(payment)
        self.assertEqual(service.apply_state(invoice, self.committed(), source="query"),
                         "credited")
        self.reload(invoice)
        self.assertEqual(invoice.flags["needs_review"], "discount_reused")
        self.assertTrue(invoice.payment.success)
        self.assertEqual(self.balance(), 500)
        self.assertEqual(self.review_events().filter(meta__what="discount_reused").count(), 1)

    def test_discount_still_held_is_not_flagged(self):
        payment = self.make_payment(request_extra={"exit_discount": {
            "offer_id": 0, "percent": 20, "original_amount": "490.00"}})
        offer = ExitDiscountOffer.objects.create(
            user=self.user, percent=20, shown_at=timezone.now(), claimed_at=timezone.now(),
            expires_at=timezone.now() + timedelta(hours=1), applied_to_payment=payment)
        invoice = self.make_invoice(payment)
        self.assertEqual(service.apply_state(invoice, self.committed(), source="query"),
                         "credited")
        self.reload(invoice)
        self.assertNotIn("needs_review", invoice.flags)
        offer.refresh_from_db()
        self.assertIsNotNone(offer.redeemed_at)

    def test_closing_status_after_credit_is_ignored(self):
        invoice = self.make_invoice()
        service.apply_state(invoice, self.committed(), source="query")
        for status in ("EXPIRED", "CANCELLED", "FAILED"):
            self.assertEqual(service.apply_state(invoice, state_of(status=status),
                                                 source="webhook"), "ignored")
            self.reload(invoice)
            self.assertEqual(invoice.status, "committed")
            self.assertTrue(invoice.payment.success)
            self.assertEqual(invoice.payment.error, "")
            self.assertEqual(invoice.flags["status_after_commit"], status)
        self.assertEqual(self.balance(), 500)

    def test_closing_statuses_close_an_open_invoice(self):
        for index, status in enumerate(("FAILED", "EXPIRED", "CANCELLED")):
            order = f"tokpkg-7-3-200000000{index}"
            invoice = self.make_invoice(self.make_payment(order_id=order),
                                        provider_payment_id=f"{index}" * 32, status="pending")
            self.assertEqual(service.apply_state(
                invoice, state_of(status=status, order_id=order, payment_id=f"{index}" * 32),
                source="webhook"), "closed")
            self.reload(invoice)
            self.assertEqual(invoice.status, status.lower())
            self.assertIsNotNone(invoice.finalized_at)
            self.assertEqual(invoice.payment.error, f"gopay_status:{status.lower()}")
            self.assertFalse(invoice.payment.success)
            self.assertEqual(service.ui_state(invoice), status.lower())
        self.assertEqual(self.ledger(), 0)

    def test_closed_to_closed_keeps_first_status_and_confirms_it(self):
        invoice = self.make_invoice(expires_at=timezone.now() - timedelta(minutes=30))
        service.mark_expired_locally(invoice)
        self.reload(invoice)
        finalized = invoice.finalized_at
        self.assertIs(invoice.flags["local_expiry"], True)
        self.assertEqual(service.apply_state(invoice, state_of(status="CANCELLED"),
                                             source="reconcile"), "closed")
        self.reload(invoice)
        self.assertEqual(invoice.status, "expired")
        self.assertEqual(invoice.finalized_at, finalized)
        self.assertNotIn("local_expiry", invoice.flags)
        self.assertEqual(invoice.payment.error, "gopay_status:expired")

    def test_pending_never_reopens_a_closed_invoice(self):
        invoice = self.make_invoice(expires_at=timezone.now() - timedelta(minutes=30))
        service.mark_expired_locally(invoice)
        for status in ("CREATED", "PENDING"):
            self.assertEqual(service.apply_state(invoice, state_of(status=status),
                                                 source="reconcile"), "pending")
            self.reload(invoice)
            self.assertEqual(invoice.status, "expired")
            self.assertIs(invoice.flags.get("local_expiry"), True)

    def test_created_moves_to_pending_and_not_back(self):
        invoice = self.make_invoice()
        self.assertEqual(service.apply_state(invoice, state_of(status="PENDING"), source="query"),
                         "pending")
        self.reload(invoice)
        self.assertEqual(invoice.status, "pending")
        self.assertEqual(service.apply_state(invoice, state_of(status="CREATED"), source="query"),
                         "pending")
        self.reload(invoice)
        self.assertEqual(invoice.status, "pending")
        self.assertFalse(invoice.payment.success)

    def test_unknown_status_is_pending_with_a_flag(self):
        invoice = self.make_invoice()
        self.assertEqual(service.apply_state(invoice, state_of(status="REFUNDED_PARTIALLY"),
                                             source="query"), "pending")
        self.reload(invoice)
        self.assertEqual(invoice.status, "created")
        self.assertEqual(invoice.flags["unknown_status"], "REFUNDED_PARTIALLY")
        self.assertNotIn("callbacks", invoice.payment.response)
        self.assertEqual(self.ledger(), 0)

    def test_flags_from_different_calls_accumulate(self):
        invoice = self.make_invoice(expires_at=timezone.now() - timedelta(minutes=30))
        stale = GoPayInvoice.objects.get(pk=invoice.pk)      # копия со старыми flags
        service.apply_state(invoice, state_of(status="WEIRD"), source="query")
        service.mark_abandoned(invoice, "user")
        # Вызов со старой копией не затирает пометки, поставленные другими путями.
        self.assertEqual(service.apply_state(stale, self.committed(), source="reconcile"),
                         "credited")
        self.reload(invoice)
        self.assertEqual(invoice.flags.get("unknown_status"), "WEIRD")
        self.assertEqual(invoice.flags.get("abandoned"), "user")
        self.assertIs(invoice.flags.get("late_commit"), True)

    def test_admin_refund_without_credit_is_never_credited(self):
        payment = self.make_payment()
        payment.response = {"admin_refund": {"by": 1, "at": "2026-10-06T10:00:00Z"}}
        payment.error = "refunded_by_admin"
        payment.save(update_fields=["response", "error"])
        invoice = self.make_invoice(payment)
        self.assertEqual(service.apply_state(invoice, self.committed(), source="admin"),
                         "already")
        self.reload(invoice)
        self.assertFalse(invoice.payment.success)
        self.assertEqual(invoice.payment.error, "refunded_by_admin")
        self.assertNotIn("token_purchase_applied", invoice.payment.response)
        self.assertEqual(invoice.status, "committed")
        self.assertEqual(self.ledger(), 0)
        self.assertEqual(self.balance(), 0)
        self.assertEqual(service.ui_state(invoice), "cancelled")
        self.assertEqual(service.admin_state()["unsettled"], 0)
        # COMMITTED мы увидели впервые и уже после отметки — зовём человека.
        self.assertEqual(invoice.flags["needs_review"], "paid_after_refund_mark")

    def test_payment_that_arrives_after_a_refund_mark_calls_a_human(self):
        # Администратор отметил возврат (или мошенничество) по ещё не оплаченному
        # QR, отменить его у GoPay не вышло — и покупатель потом заплатил. Не
        # зачисляем, но это настоящие деньги: молча проглотить их нельзя.
        for name, response in (
                ("mark", {"admin_refund": {"kind": "fraud", "clawback": False}}),
                ("mark+clawback", {"admin_refund": {"kind": "refund", "clawback": True},
                                   "token_purchase_clawed_back": True})):
            with self.subTest(name):
                cache.clear()
                EventLog.objects.all().delete()
                GoPayInvoice.objects.all().delete()
                Payment.objects.all().delete()
                payment = self.make_payment()
                payment.response = response
                payment.error = "refunded"
                payment.save(update_fields=["response", "error"])
                invoice = self.make_invoice(payment)
                self.assertTrue(service.mark_abandoned(invoice, "admin_refund"))

                self.assertEqual(service.apply_state(invoice, self.committed(),
                                                     source="reconcile"), "already")
                self.reload(invoice)
                self.assertEqual((invoice.status, invoice.payment.success, invoice.payment.error),
                                 ("committed", False, "refunded"))
                self.assertEqual(self.ledger(), 0)
                self.assertEqual(invoice.flags["needs_review"], "paid_after_refund_mark")
                self.assertIs(invoice.flags["late_commit"], True)
                events = self.review_events()
                self.assertEqual([e.meta["what"] for e in events], ["paid_after_refund_mark"])
                self.assertEqual(EventLog.objects.filter(
                    meta__kind="gopay_reconcile_already").count(), 1)

                # Повторный COMMITTED — уже не новость: ни второго сигнала, ни строки.
                self.assertEqual(service.apply_state(invoice, self.committed(), source="admin"),
                                 "already")
                self.assertEqual(self.review_events().count(), 1)
                self.assertEqual(EventLog.objects.filter(type="payment").count(), 2)

    def test_refund_mark_after_a_seen_payment_is_not_a_new_alarm(self):
        # Оплату мы видели (счёт уже «оплачен», на разборе), потом отметили возврат:
        # повторный COMMITTED ничего нового не сообщает.
        invoice = self.make_invoice()
        self.assertEqual(service.apply_state(invoice, self.committed(amount="1.00"),
                                             source="query"), "mismatch")
        self.assertEqual(self.review_events().count(), 1)
        Payment.objects.filter(pk=invoice.payment_id).update(
            response={"admin_refund": {"kind": "refund", "clawback": False}})
        self.assertEqual(service.apply_state(invoice, self.committed(), source="admin"),
                         "already")
        self.reload(invoice)
        self.assertEqual(invoice.flags["needs_review"], "mismatch:amount")
        self.assertEqual(self.review_events().count(), 1)

    def test_credited_then_refunded_order_is_not_flagged(self):
        invoice = self.make_invoice()
        self.assertEqual(service.apply_state(invoice, self.committed(), source="query"),
                         "credited")
        payment = Payment.objects.get(pk=invoice.payment_id)
        payment.response = {**payment.response, "admin_refund": {"kind": "refund"},
                            "token_purchase_clawed_back": True}
        payment.success = False
        payment.save(update_fields=["response", "success"])
        self.assertEqual(service.apply_state(invoice, self.committed(), source="reconcile"),
                         "already")
        self.reload(invoice)
        self.assertNotIn("needs_review", invoice.flags)
        self.assertEqual(self.review_events().count(), 0)

    def test_admin_refund_on_an_open_invoice_still_lets_it_close(self):
        payment = self.make_payment()
        payment.response = {"admin_refund": {"by": 1}}
        payment.error = "refunded_by_admin"
        payment.save(update_fields=["response", "error"])
        invoice = self.make_invoice(payment)
        self.assertEqual(service.apply_state(invoice, state_of(status="CANCELLED"),
                                             source="cancel"), "closed")
        self.reload(invoice)
        self.assertEqual(invoice.status, "cancelled")
        # Отметку администратора закрытие не переписывает.
        self.assertEqual(invoice.payment.error, "refunded_by_admin")

    def test_clawed_back_order_is_never_credited_again(self):
        payment = self.make_payment()
        payment.response = {"token_purchase_clawed_back": True}
        payment.error = "clawed_back"
        payment.save(update_fields=["response", "error"])
        invoice = self.make_invoice(payment)
        self.assertEqual(service.apply_state(invoice, self.committed(), source="reconcile"),
                         "already")
        self.reload(invoice)
        self.assertEqual(invoice.payment.error, "clawed_back")
        self.assertFalse(invoice.payment.success)
        self.assertEqual(self.ledger(), 0)

    def test_existing_ledger_row_means_already(self):
        invoice = self.make_invoice()
        TokenTransaction.objects.create(user=self.user, delta=500, reason="purchase",
                                        balance_after=500, meta={"order_id": ORDER})
        self.assertEqual(service.apply_state(invoice, self.committed(), source="query"),
                         "already")
        self.assertEqual(self.ledger(), 1)

    def test_failed_credit_keeps_the_transaction_usable(self):
        invoice = self.make_invoice()
        other = self.make_payment(order_id="tokpkg-7-3-othr000000")

        def broken_credit(payment, order_id, **kwargs):
            # Настоящая ошибка базы внутри начисления: нарушение уникальности.
            GoPayInvoice.objects.create(
                payment=other, env="live", provider_payment_id=PID, amount=Decimal("1.00"),
                lifetime_seconds=900, expires_at=timezone.now())

        with patch("payments.views._credit_token_package_for_payment",
                   side_effect=broken_credit):
            with self.assertLogs("payments.gopay", level="ERROR"):
                self.assertEqual(service.apply_state(invoice, self.committed(), source="webhook"),
                                 "failed")
        # Транзакция жива — запросы после упавшего начисления проходят.
        self.reload(invoice)
        self.assertEqual(invoice.status, "committed")
        self.assertFalse(invoice.payment.success)
        self.assertEqual(invoice.payment.error, "token_purchase_apply_failed:IntegrityError")
        self.assertEqual(self.ledger(), 0)
        self.assertEqual(self.review_events().filter(meta__what="credit_failed").count(), 1)
        self.assertEqual(service.ui_state(invoice), "processing")
        self.assertEqual(service.admin_state()["unsettled"], 1)

        # Следующий COMMITTED (сверка) дозачисляет.
        self.assertEqual(service.apply_state(invoice, self.committed(), source="reconcile"),
                         "credited")
        self.assertEqual(self.balance(), 500)
        self.assertEqual(service.admin_state()["unsettled"], 0)

    def test_payment_without_user(self):
        payment = self.make_payment(user=None)
        invoice = self.make_invoice(payment)
        self.assertEqual(service.apply_state(invoice, self.committed(), source="webhook"),
                         "no_user")
        self.reload(invoice)
        self.assertEqual(invoice.status, "committed")
        self.assertEqual(invoice.payment.error, "gopay_no_user")
        self.assertFalse(invoice.payment.success)
        self.assertEqual(self.review_events().filter(meta__what="no_user").count(), 1)

    def test_callbacks_are_typed_and_capped(self):
        payment = self.make_payment()
        payment.response = {"gopay_create": {"status": "CREATED"},
                            "callbacks": [{"type": "gopay_query", "payload": {"n": i}}
                                          for i in range(45)]}
        payment.save(update_fields=["response"])
        invoice = self.make_invoice(payment)
        service.apply_state(invoice, state_of(status="PENDING"), source="reconcile")
        self.reload(invoice)
        callbacks = invoice.payment.response["callbacks"]
        self.assertEqual(len(callbacks), service.CALLBACKS_CAP)
        self.assertEqual(callbacks[-1]["type"], "gopay_reconcile")
        self.assertEqual(callbacks[-1]["payload"], state_of(status="PENDING").raw)
        self.assertEqual(invoice.payment.response["gopay_create"], {"status": "CREATED"})

        # Тот же статус ещё раз истории не добавляет.
        service.apply_state(invoice, state_of(status="PENDING"), source="reconcile")
        self.reload(invoice)
        self.assertEqual(invoice.payment.response["callbacks"], callbacks)

    def test_callback_types_never_look_like_another_provider(self):
        allowed = {f"gopay_{s}" for s in service.SOURCES}
        self.assertEqual(allowed, {"gopay_create", "gopay_webhook", "gopay_query",
                                   "gopay_reconcile", "gopay_admin", "gopay_cancel",
                                   "gopay_chain_check"})
        invoice = self.make_invoice()
        for source in ("refund", "post", "success", "ipn", ""):
            with self.assertRaises(ValueError):
                service.apply_state(invoice, self.committed(), source=source)
        self.assertEqual(self.ledger(), 0)
        service.apply_state(invoice, self.committed(), source="chain_check")
        self.reload(invoice)
        self.assertEqual([c["type"] for c in invoice.payment.response["callbacks"]],
                         ["gopay_chain_check"])

    def test_notification_goes_only_after_commit(self):
        invoice = self.make_invoice()
        with patch("payments.views._notify_balance_topup") as notify:
            with self.captureOnCommitCallbacks(execute=False) as callbacks:
                self.assertEqual(service.apply_state(invoice, self.committed(), source="webhook"),
                                 "credited")
            notify.assert_not_called()
            self.assertGreaterEqual(len(callbacks), 1)
            for callback in callbacks:
                callback()
            notify.assert_called_once()
            self.assertEqual(notify.call_args.args[1], 500)

    def test_cancel_answer_without_testing_mode_closes_a_test_invoice(self):
        payment = self.make_payment(env="test")
        invoice = self.make_invoice(payment, env="test")
        # В ответе на отмену флага нет — и для этого источника он не сверяется.
        self.assertEqual(service.apply_state(invoice, state_of(status="CANCELLED"),
                                             source="cancel"), "closed")
        self.reload(invoice)
        self.assertEqual(invoice.status, "cancelled")
        self.assertNotIn("needs_review", invoice.flags)

    def test_cancel_source_still_checks_ids(self):
        invoice = self.make_invoice()
        self.assertEqual(service.apply_state(
            invoice, state_of(status="CANCELLED", payment_id="f" * 32), source="cancel"),
            "mismatch")
        self.reload(invoice)
        self.assertEqual(invoice.status, "created")

    def test_cancel_source_never_credits_without_the_mode_check(self):
        payment = self.make_payment(env="test")
        invoice = self.make_invoice(payment, env="test")
        self.assertEqual(service.apply_state(invoice, self.committed(), source="cancel"),
                         "mismatch")
        self.assertEqual(self.ledger(self.staff), 0)

    def test_status_checks_that_change_nothing_leave_no_audit_rows(self):
        # Открытую вкладку опрашивают раз в пять секунд, сверка ходит каждую
        # минуту: строка «…pending FAIL» на каждый такой запрос похоронила бы
        # под собой сигналы «нужен разбор».
        invoice = self.make_invoice()
        for source in ("query", "query", "reconcile", "webhook", "query"):
            self.assertEqual(service.apply_state(invoice, state_of(status="CREATED"),
                                                 source=source), "pending")
        self.assertEqual(service.apply_state(invoice, state_of(status="PENDING"),
                                             source="query"), "pending")
        self.assertEqual(service.apply_state(invoice, state_of(status="WEIRD"),
                                             source="query"), "pending")
        self.assertEqual(EventLog.objects.count(), 0)

        # Закрытие — событие, но одно: поздняя сверка спрашивает закрытый счёт
        # ещё шесть часов и получает тот же ответ.
        for _ in range(4):
            self.assertEqual(service.apply_state(invoice, state_of(status="EXPIRED"),
                                                 source="reconcile"), "closed")
        self.assertEqual(list(EventLog.objects.values_list("meta__kind", flat=True)),
                         ["gopay_reconcile_closed"])

        # Оплата — событие; повторы «уже начислено» — нет.
        self.assertEqual(service.apply_state(invoice, self.committed(), source="reconcile"),
                         "credited")
        for source in ("webhook", "query", "admin"):
            self.assertEqual(service.apply_state(invoice, self.committed(), source=source),
                             "already")
        # Закрытие после оплаты запоминаем один раз.
        for _ in range(3):
            self.assertEqual(service.apply_state(invoice, state_of(status="EXPIRED"),
                                                 source="webhook"), "ignored")
        self.assertEqual(list(EventLog.objects.order_by("id")
                              .values_list("meta__kind", flat=True)),
                         ["gopay_reconcile_closed", "gopay_reconcile_credited",
                          "gopay_webhook_ignored"])

    def test_confirmed_close_of_a_locally_expired_invoice_is_an_event(self):
        invoice = self.make_invoice(expires_at=timezone.now() - timedelta(minutes=30))
        self.assertTrue(service.mark_expired_locally(invoice))
        self.assertEqual(service.apply_state(invoice, state_of(status="CREATED"),
                                             source="reconcile"), "pending")
        self.assertEqual(EventLog.objects.count(), 0)
        # GoPay подтвердил закрытие: статус прежний, но пометка «только по нашим
        # часам» снята — это изменение, и оно в журнале.
        self.assertEqual(service.apply_state(invoice, state_of(status="EXPIRED"),
                                             source="reconcile"), "closed")
        self.assertEqual(EventLog.objects.filter(meta__kind="gopay_reconcile_closed").count(), 1)

    def test_repeated_mismatch_and_failed_credit_are_logged_once(self):
        # Расхождение по открытому счёту сверка видит каждую минуту двое суток.
        invoice = self.make_invoice()
        wrong = state_of(status="CREATED", testing_mode=True)
        for _ in range(5):
            self.assertEqual(service.apply_state(invoice, wrong, source="reconcile"), "mismatch")
        self.assertEqual(EventLog.objects.filter(meta__kind="gopay_reconcile_mismatch").count(), 1)

        other = self.make_invoice(self.make_payment(order_id="tokpkg-7-3-fail000000"),
                                  provider_payment_id="e" * 32)
        paid = self.committed(order_id="tokpkg-7-3-fail000000", payment_id="e" * 32)
        with self.assertLogs("payments.gopay", level="ERROR"):
            with patch("payments.views._credit_token_package_for_payment",
                       side_effect=RuntimeError("база моргнула")):
                for _ in range(4):
                    self.assertEqual(service.apply_state(other, paid, source="reconcile"),
                                     "failed")
            # Другая ошибка — уже новость.
            with patch("payments.views._credit_token_package_for_payment",
                       side_effect=ValueError("другое")):
                self.assertEqual(service.apply_state(other, paid, source="reconcile"), "failed")
        self.assertEqual(EventLog.objects.filter(meta__kind="gopay_reconcile_failed").count(), 2)
        # Сигнал «нужен разбор» при этом один на шесть часов, как и был.
        self.assertEqual(self.review_events().filter(meta__what="credit_failed").count(), 1)

    def test_audit_log_records_the_outcome_without_secrets(self):
        invoice = self.make_invoice()
        service.apply_state(invoice, self.committed(), source="webhook")
        event = EventLog.objects.filter(type="payment", meta__kind="gopay_webhook_credited").get()
        self.assertEqual(event.meta["order_id"], ORDER)
        dumped = json.dumps(list(EventLog.objects.values_list("message", "meta")),
                            ensure_ascii=False)
        for secret in ALL_SECRETS:
            self.assertNotIn(secret, dumped)


# ============================================ запрос статуса и отмена ===

@override_settings(**GOPAY_SETTINGS)
class RefreshAndCancelTests(GoPayTestCase):
    def reload(self, invoice):
        invoice.refresh_from_db()
        invoice.payment.refresh_from_db()
        return invoice

    def test_fetch_state_uses_the_keys_of_the_invoice_env(self):
        invoice = self.make_invoice(env="live")
        self.fake.on("/v1/payments/query", ok(pay_data()))
        # Активная среда — тест, счёт боевой: спрашиваем боевыми ключами.
        self.assertEqual(config.env(), "test")
        state = service.fetch_state(invoice)
        call = self.fake.calls[0]
        self.assertEqual(call.headers["GoPay-Api-Key"], LIVE_API_KEY)
        self.assertEqual(call.headers["GoPay-Signature"],
                         independent_sign(LIVE_API_SECRET, call.headers["GoPay-Nonce"], call.data))
        self.assertEqual(call.body, {"payment_id": PID})
        self.assertEqual(call.timeout, (3, 5))
        self.assertEqual(state.status, "created")
        # Ничего не записано.
        self.reload(invoice)
        self.assertIsNone(invoice.last_checked_at)

        test_payment = self.make_payment(env="test", order_id="tokpkg-7-3-test000000")
        test_invoice = self.make_invoice(test_payment, env="test", provider_payment_id="8" * 32)
        with override_settings(GOPAY_ENV="live"):
            service.fetch_state(test_invoice)
        self.assertEqual(self.fake.calls[-1].headers["GoPay-Api-Key"], API_KEY)

    def test_refresh_applies_the_answer(self):
        invoice = self.make_invoice()
        self.fake.on("/v1/payments/query", ok(pay_data(status="COMMITTED")))
        self.assertEqual(service.refresh_invoice(invoice), "credited")
        self.assertEqual(self.balance(), 500)
        self.reload(invoice)
        self.assertEqual(invoice.payment.response["callbacks"][-1]["type"], "gopay_query")
        self.fake.on("/v1/payments/query", ok(pay_data(status="COMMITTED")))
        self.assertEqual(service.refresh_invoice(invoice, source="admin"), "already")

    def test_not_found_is_a_counter_not_a_verdict(self):
        invoice = self.make_invoice()
        self.fake.on("/v1/payments/query", fail("4041", "Payment not found"))
        self.assertEqual(service.refresh_invoice(invoice, source="reconcile"), "not_found")
        self.reload(invoice)
        self.assertEqual(invoice.flags["not_found"]["count"], 1)
        self.assertIn("at", invoice.flags["not_found"])
        self.assertIsNotNone(invoice.last_checked_at)
        self.assertEqual(invoice.status, "created")
        self.assertEqual(service.refresh_invoice(invoice, source="reconcile"), "not_found")
        self.reload(invoice)
        self.assertEqual(invoice.flags["not_found"]["count"], 2)

        # Следующий нормальный ответ счётчик снимает.
        self.fake.on("/v1/payments/query", ok(pay_data(status="CREATED")))
        self.assertEqual(service.refresh_invoice(invoice, source="reconcile"), "pending")
        self.reload(invoice)
        self.assertNotIn("not_found", invoice.flags)

    def test_not_found_text_with_another_code_is_a_provider_error(self):
        invoice = self.make_invoice()
        self.fake.on("/v1/payments/query", fail("0009", "Payment not found"))
        self.assertEqual(service.refresh_invoice(invoice), "provider_error")
        self.reload(invoice)
        self.assertNotIn("not_found", invoice.flags)
        self.assertIsNotNone(invoice.last_checked_at)
        self.fake.on("/v1/payments/query", html(404))
        self.assertEqual(service.refresh_invoice(invoice), "provider_error")
        self.reload(invoice)
        self.assertNotIn("not_found", invoice.flags)

    def test_unavailable_propagates(self):
        invoice = self.make_invoice()
        for response in (requests.Timeout(), html(503), fail("5001", "Internal")):
            self.fake.on("/v1/payments/query", response)
            with self.assertRaises(GoPayUnavailable):
                service.refresh_invoice(invoice)
        self.reload(invoice)
        self.assertEqual(invoice.status, "created")

    def test_not_configured(self):
        invoice = self.make_invoice()
        with override_settings(GOPAY_LIVE_API_KEY=""):
            self.assertEqual(service.refresh_invoice(invoice), "not_configured")
        self.assertEqual(self.fake.calls, [])

    def test_refresh_ignores_the_circuit_breaker(self):
        invoice = self.make_invoice()
        cache.set("gopay:down:live", 1, 45)
        self.fake.on("/v1/payments/query", ok(pay_data()))
        self.assertEqual(service.refresh_invoice(invoice, source="admin"), "pending")
        self.assertEqual(len(self.fake.calls), 1)

    def test_refresh_always_checks_the_mode(self):
        payment = self.make_payment(env="test")
        invoice = self.make_invoice(payment, env="test")
        self.fake.on("/v1/payments/query", ok(pay_data(status="EXPIRED")))
        # Ответ на запрос статуса без флага теста — расхождение, даже с source="cancel".
        self.assertEqual(service.refresh_invoice(invoice, source="cancel"), "mismatch")

    # --- отмена ---------------------------------------------------------------

    def test_cancel_success(self):
        invoice = self.make_invoice()
        self.fake.on("/v1/payments/cancel", ok(pay_data(
            status="CANCELLED", committed_at="2026-10-06T10:02:00")))
        self.assertEqual(service.cancel_invoice(invoice, reason="user"), "cancelled")
        call = self.fake.calls[0]
        self.assertEqual((call.path, call.body, call.timeout),
                         ("/v1/payments/cancel", {"payment_id": PID}, (5, 10)))
        self.reload(invoice)
        self.assertEqual(invoice.status, "cancelled")
        self.assertIsNotNone(invoice.cancel_requested_at)
        self.assertEqual(invoice.flags["cancel_reason"], "user")
        self.assertEqual(invoice.payment.error, "gopay_status:cancelled")
        self.assertEqual(invoice.payment.response["callbacks"][-1]["type"], "gopay_cancel")
        self.assertEqual(service.ui_state(invoice), "cancelled")
        # Повторная отмена уже закрытого счёта в сеть не идёт.
        self.assertEqual(service.cancel_invoice(invoice), "not_open")
        self.assertEqual(len(self.fake.calls), 1)

    def test_cancel_of_a_test_invoice_without_the_flag_in_the_answer(self):
        payment = self.make_payment(env="test")
        invoice = self.make_invoice(payment, env="test")
        self.fake.on("/v1/payments/cancel", ok(pay_data(status="CANCELLED")))
        self.assertEqual(service.cancel_invoice(invoice, reason="user"), "cancelled")
        self.assertEqual(self.fake.calls[0].headers["GoPay-Api-Key"], API_KEY)
        self.reload(invoice)
        self.assertNotIn("needs_review", invoice.flags)

    def test_cancel_reason_is_cut(self):
        invoice = self.make_invoice()
        self.fake.on("/v1/payments/cancel", ok(pay_data(status="CANCELLED")))
        service.cancel_invoice(invoice, reason="r" * 100)
        self.reload(invoice)
        self.assertEqual(len(invoice.flags["cancel_reason"]), 40)

    def test_cannot_cancel_and_the_query_says_committed(self):
        invoice = self.make_invoice()
        self.fake.on("/v1/payments/cancel",
                     fail("0013", "Payment is already COMMITTED and cannot be cancelled."))
        self.fake.on("/v1/payments/query", ok(pay_data(status="COMMITTED")))
        self.assertEqual(service.cancel_invoice(invoice, reason="user"), "committed")
        self.assertEqual(self.balance(), 500)
        self.reload(invoice)
        self.assertTrue(invoice.payment.success)
        self.assertIsNone(invoice.cancel_requested_at)
        self.assertEqual(self.fake.paths(), ["/v1/payments/cancel", "/v1/payments/query"])

    def test_cannot_cancel_and_still_open_is_busy(self):
        invoice = self.make_invoice()
        self.fake.on("/v1/payments/cancel", fail("0013", "bank status: PROCESSING"))
        self.fake.on("/v1/payments/query", ok(pay_data(status="CREATED")))
        self.assertEqual(service.cancel_invoice(invoice, reason="user"), "busy")
        self.reload(invoice)
        self.assertEqual(invoice.status, "created")
        self.assertIsNone(invoice.cancel_requested_at)
        self.assertEqual(self.balance(), 0)

    def test_cannot_cancel_and_the_query_fails_is_busy(self):
        invoice = self.make_invoice()
        self.fake.on("/v1/payments/cancel", fail("0013", "x"))
        self.fake.on("/v1/payments/query", requests.Timeout())
        self.assertEqual(service.cancel_invoice(invoice, reason="user"), "busy")
        self.fake.on("/v1/payments/query", fail("4041", "Payment not found"))
        self.assertEqual(service.cancel_invoice(invoice, reason="user"), "busy")

    def test_cannot_cancel_and_the_query_says_closed(self):
        invoice = self.make_invoice()
        self.fake.on("/v1/payments/cancel", fail("0013", "already EXPIRED"))
        self.fake.on("/v1/payments/query", ok(pay_data(status="EXPIRED")))
        self.assertEqual(service.cancel_invoice(invoice), "closed")
        other = self.make_invoice(self.make_payment(order_id="tokpkg-7-3-canc000000"),
                                  provider_payment_id="7" * 32)
        self.fake.on("/v1/payments/query", ok(pay_data(
            status="CANCELLED", order_id="tokpkg-7-3-canc000000", payment_id="7" * 32)))
        self.assertEqual(service.cancel_invoice(other), "cancelled")

    def test_cancel_retry_code_and_network_error(self):
        invoice = self.make_invoice()
        self.fake.on("/v1/payments/cancel", fail("0015", "bank unavailable"))
        self.assertEqual(service.cancel_invoice(invoice, reason="user"), "retry")
        self.fake.on("/v1/payments/cancel", requests.ConnectionError())
        self.assertEqual(service.cancel_invoice(invoice, reason="user"), "retry")
        self.fake.on("/v1/payments/cancel", html(503))
        self.assertEqual(service.cancel_invoice(invoice, reason="user"), "retry")
        with override_settings(GOPAY_LIVE_API_SECRET=""):
            self.assertEqual(service.cancel_invoice(invoice, reason="user"), "retry")
        self.assertNotIn("/v1/payments/query", self.fake.paths())
        self.reload(invoice)
        self.assertEqual(invoice.status, "created")
        self.assertIsNone(invoice.cancel_requested_at)

    def test_missing_cancel_endpoint_asks_for_the_real_state(self):
        invoice = self.make_invoice()
        self.fake.on("/v1/payments/cancel", html(404))
        self.fake.on("/v1/payments/query", ok(pay_data(status="EXPIRED")))
        self.assertEqual(service.cancel_invoice(invoice, reason="user"), "closed")

        other = self.make_invoice(self.make_payment(order_id="tokpkg-7-3-open000000"),
                                  provider_payment_id="6" * 32)
        self.fake.on("/v1/payments/query", ok(pay_data(
            status="CREATED", order_id="tokpkg-7-3-open000000", payment_id="6" * 32)))
        self.assertEqual(service.cancel_invoice(other, reason="user"), "retry")
        self.fake.on("/v1/payments/query", requests.Timeout())
        self.assertEqual(service.cancel_invoice(other, reason="user"), "retry")
        self.fake.on("/v1/payments/cancel", fail("0009", "unknown refusal"))
        self.fake.on("/v1/payments/query", ok(pay_data(
            status="COMMITTED", order_id="tokpkg-7-3-open000000", payment_id="6" * 32)))
        self.assertEqual(service.cancel_invoice(other, reason="user"), "committed")
        self.assertEqual(self.ledger(), 1)

    def test_locally_expired_invoice_is_still_cancelled_at_gopay(self):
        invoice = self.make_invoice(expires_at=timezone.now() - timedelta(minutes=30))
        service.mark_expired_locally(invoice)
        self.fake.on("/v1/payments/cancel", ok(pay_data(status="CANCELLED")))
        self.assertEqual(service.cancel_invoice(invoice, reason="expired"), "closed")
        self.assertEqual(len(self.fake.calls), 1)
        self.reload(invoice)
        self.assertEqual(invoice.status, "expired")
        self.assertNotIn("local_expiry", invoice.flags)
        self.assertIsNotNone(invoice.cancel_requested_at)
        self.assertEqual(service.cancel_invoice(invoice, reason="expired"), "not_open")
        self.assertEqual(len(self.fake.calls), 1)

    def test_locally_expired_invoice_that_gopay_keeps_open_is_not_closed(self):
        invoice = self.make_invoice(expires_at=timezone.now() - timedelta(minutes=30))
        service.mark_expired_locally(invoice)
        self.fake.on("/v1/payments/cancel", fail("0013", "bank is processing"))
        self.fake.on("/v1/payments/query", ok(pay_data(status="PENDING")))
        self.assertEqual(service.cancel_invoice(invoice, reason="expired"), "busy")
        self.reload(invoice)
        self.assertIs(invoice.flags.get("local_expiry"), True)

    def test_closed_or_paid_invoice_is_not_sent_to_gopay(self):
        closed = self.make_invoice(status="expired")
        self.assertEqual(service.cancel_invoice(closed), "not_open")
        paid_payment = self.make_payment(order_id="tokpkg-7-3-paid000000")
        paid = self.make_invoice(paid_payment, provider_payment_id="5" * 32, status="committed")
        self.assertEqual(service.cancel_invoice(paid), "committed")
        success_payment = self.make_payment(order_id="tokpkg-7-3-succ000000", success=True)
        odd = self.make_invoice(success_payment, provider_payment_id="4" * 32)
        self.assertEqual(service.cancel_invoice(odd), "committed")
        self.assertEqual(self.fake.calls, [])

    def test_cancel_answer_saying_committed_is_never_credited_directly(self):
        payment = self.make_payment(env="test")
        invoice = self.make_invoice(payment, env="test")
        self.fake.on("/v1/payments/cancel", ok(pay_data(status="COMMITTED")))
        self.fake.on("/v1/payments/query", ok(pay_data(status="CREATED", testing_mode=True)))
        self.assertEqual(service.cancel_invoice(invoice, reason="user"), "busy")
        self.assertEqual(self.ledger(self.staff), 0)
        self.assertEqual(self.fake.paths(), ["/v1/payments/cancel", "/v1/payments/query"])


# ======================================= пометки, выборки, экран, банки ===

@override_settings(**GOPAY_SETTINGS)
class InvoiceHelpersTests(GoPayTestCase):
    def reload(self, invoice):
        invoice.refresh_from_db()
        invoice.payment.refresh_from_db()
        return invoice

    def many(self, count, **over):
        invoices = []
        for index in range(count):
            payment = self.make_payment(order_id=f"tokpkg-7-3-many00000{index}")
            invoices.append(self.make_invoice(payment, provider_payment_id=f"{index}" * 32, **over))
        return invoices

    def test_mark_abandoned(self):
        invoice = self.make_invoice()
        self.assertTrue(service.mark_abandoned(invoice, "superseded-by-a-much-newer-qr"))
        self.reload(invoice)
        self.assertIsNotNone(invoice.cancel_requested_at)
        self.assertEqual(invoice.flags["abandoned"], "superseded-by-a-much-new")
        # Ни статус, ни платёж не тронуты: счёт остаётся в сверке.
        self.assertEqual(invoice.status, "created")
        self.assertFalse(invoice.payment.success)
        self.assertIsNone(invoice.payment.error)
        first_time = invoice.cancel_requested_at
        self.assertFalse(service.mark_abandoned(invoice, "user"))
        self.reload(invoice)
        self.assertEqual(invoice.cancel_requested_at, first_time)
        self.assertEqual(invoice.flags["abandoned"], "superseded-by-a-much-new")
        self.assertEqual(service.ui_state(invoice), "cancelled")

    def test_mark_abandoned_only_for_open_or_locally_expired(self):
        closed, paid, local = self.many(3)
        GoPayInvoice.objects.filter(pk=closed.pk).update(status="cancelled")
        GoPayInvoice.objects.filter(pk=paid.pk).update(status="committed")
        GoPayInvoice.objects.filter(pk=local.pk).update(
            status="expired", flags={"local_expiry": True})
        self.assertFalse(service.mark_abandoned(closed, "user"))
        self.assertFalse(service.mark_abandoned(paid, "user"))
        self.assertTrue(service.mark_abandoned(local, "expired"))
        self.reload(local)
        self.assertEqual(local.flags, {"local_expiry": True, "abandoned": "expired"})
        self.assertEqual(local.status, "expired")
        confirmed = self.make_invoice(self.make_payment(order_id="tokpkg-7-3-conf000000"),
                                      provider_payment_id="a" * 32, status="expired")
        self.assertFalse(service.mark_abandoned(confirmed, "user"))

    def test_mark_expired_locally(self):
        fresh, just_expired, overdue = self.many(3)
        now = timezone.now()
        GoPayInvoice.objects.filter(pk=just_expired.pk).update(
            expires_at=now - timedelta(minutes=9))
        GoPayInvoice.objects.filter(pk=overdue.pk).update(
            expires_at=now - service.LOCAL_EXPIRY_GRACE - timedelta(seconds=1))
        self.assertFalse(service.mark_expired_locally(fresh))
        self.assertFalse(service.mark_expired_locally(just_expired))
        self.assertTrue(service.mark_expired_locally(overdue))
        self.reload(overdue)
        self.assertEqual(overdue.status, "expired")
        self.assertIs(overdue.flags["local_expiry"], True)
        self.assertIsNotNone(overdue.finalized_at)
        self.assertFalse(overdue.payment.success)
        self.assertEqual(overdue.payment.error, "gopay_status:expired")
        self.assertFalse(service.mark_expired_locally(overdue))
        self.reload(just_expired)
        self.assertEqual(just_expired.status, "created")

    def test_mark_expired_locally_never_rewrites_a_settled_payment(self):
        payment = self.make_payment()
        payment.response = {"token_purchase_applied": True}
        payment.success = True
        payment.error = ""
        payment.save()
        invoice = self.make_invoice(payment, expires_at=timezone.now() - timedelta(hours=1))
        self.assertTrue(service.mark_expired_locally(invoice))
        self.reload(invoice)
        self.assertTrue(invoice.payment.success)
        self.assertEqual(invoice.payment.error, "")

        refunded = self.make_payment(order_id="tokpkg-7-3-refu000000")
        refunded.response = {"admin_refund": {"by": 1}}
        refunded.error = "refunded_by_admin"
        refunded.save()
        other = self.make_invoice(refunded, provider_payment_id="b" * 32,
                                  expires_at=timezone.now() - timedelta(hours=1))
        self.assertTrue(service.mark_expired_locally(other))
        self.reload(other)
        self.assertEqual(other.payment.error, "refunded_by_admin")

    def test_find_resumable(self):
        with override_settings(GOPAY_ENV="live"):
            invoice = self.make_invoice()
            self.assertEqual(service.find_resumable(self.user, 3).pk, invoice.pk)
            self.assertEqual(service.find_resumable(self.user, "3").pk, invoice.pk)
            # Другой пакет, другой человек, мусор вместо номера пакета.
            self.assertIsNone(service.find_resumable(self.user, 4))
            self.assertIsNone(service.find_resumable(self.staff, 3))
            self.assertIsNone(service.find_resumable(self.user, "abc"))
            self.assertIsNone(service.find_resumable(self.user, None))

            def excluded(**fields):
                GoPayInvoice.objects.filter(pk=invoice.pk).update(**fields)
                result = service.find_resumable(self.user, 3)
                GoPayInvoice.objects.filter(pk=invoice.pk).update(
                    status="created", cancel_requested_at=None, env="live",
                    expires_at=timezone.now() + timedelta(minutes=15))
                return result is None

            for status in ("committed", "failed", "expired", "cancelled"):
                self.assertTrue(excluded(status=status), status)
            self.assertTrue(excluded(cancel_requested_at=timezone.now()))
            self.assertTrue(excluded(env="test"))
            self.assertTrue(excluded(expires_at=timezone.now() + timedelta(seconds=60)))
            self.assertTrue(excluded(expires_at=timezone.now() - timedelta(seconds=1)))
            self.assertFalse(excluded(status="pending"))
            self.assertFalse(excluded(expires_at=timezone.now() + timedelta(seconds=120)))

            Payment.objects.filter(pk=invoice.payment_id).update(success=True)
            self.assertIsNone(service.find_resumable(self.user, 3))
            Payment.objects.filter(pk=invoice.payment_id).update(success=False)

            newer = self.make_invoice(self.make_payment(order_id="tokpkg-7-3-newe000000"),
                                      provider_payment_id="c" * 32)
            self.assertEqual(service.find_resumable(self.user, 3).pk, newer.pk)
        # Активная среда сменилась на тест — боевой счёт не возвращаем.
        self.assertIsNone(service.find_resumable(self.user, 3))

    def test_open_invoices_and_provider_count(self):
        live, abandoned, expired, closed = self.many(4)
        service.mark_abandoned(abandoned, "user")
        GoPayInvoice.objects.filter(pk=expired.pk).update(
            expires_at=timezone.now() - timedelta(seconds=1))
        GoPayInvoice.objects.filter(pk=closed.pk).update(status="cancelled")
        self.assertEqual([i.pk for i in service.open_invoices_for(self.user)], [live.pk])
        # Оставленный счёт у GoPay всё ещё открыт — в подстраховочный предел он входит.
        self.assertEqual(service.open_at_provider_count(self.user), 2)
        self.assertEqual(service.open_at_provider_count(self.staff), 0)
        self.assertEqual(list(service.open_invoices_for(self.staff)), [])
        self.assertEqual(service.MAX_OPEN_AT_PROVIDER, 6)

    def test_invoice_of(self):
        payment = self.make_payment()
        self.assertIsNone(service.invoice_of(payment))
        self.assertIsNone(service.invoice_of(None))
        self.assertIsNone(service.invoice_of(Payment()))
        invoice = self.make_invoice(payment)
        self.assertEqual(service.invoice_of(Payment.objects.get(pk=payment.pk)).pk, invoice.pk)

    def test_ui_state_every_branch(self):
        invoice = self.make_invoice()

        def state(**fields):
            payment_fields = {k[8:]: v for k, v in fields.items() if k.startswith("payment_")}
            invoice_fields = {k: v for k, v in fields.items() if not k.startswith("payment_")}
            base_invoice = dict(status="created", cancel_requested_at=None,
                                expires_at=timezone.now() + timedelta(minutes=15))
            base_payment = dict(success=False, response={})
            base_invoice.update(invoice_fields)
            base_payment.update(payment_fields)
            GoPayInvoice.objects.filter(pk=invoice.pk).update(**base_invoice)
            Payment.objects.filter(pk=invoice.payment_id).update(**base_payment)
            return service.ui_state(GoPayInvoice.objects.select_related("payment")
                                    .get(pk=invoice.pk))

        self.assertEqual(state(), "awaiting_payment")
        self.assertEqual(state(status="pending"), "awaiting_payment")
        self.assertEqual(state(payment_success=True, status="committed"), "paid")
        self.assertEqual(state(payment_success=True, status="expired"), "paid")
        self.assertEqual(state(status="committed"), "processing")
        self.assertEqual(state(status="committed", payment_response={"admin_refund": {"by": 1}}),
                         "cancelled")
        self.assertEqual(state(status="committed",
                               payment_response={"token_purchase_clawed_back": True}),
                         "cancelled")
        self.assertEqual(state(status="failed"), "failed")
        self.assertEqual(state(status="cancelled"), "cancelled")
        self.assertEqual(state(status="expired"), "expired")
        self.assertEqual(state(cancel_requested_at=timezone.now()), "cancelled")
        self.assertEqual(state(expires_at=timezone.now() - timedelta(seconds=1)), "expired")

    def test_invoice_json_contract(self):
        cache.set("gopay:apps:v1:live", [
            {"code": "mbank", "name": "MBank", "order": 1, "url": "mbank://elqr?data={qr_data}",
             "icon": "https://media.gopay.kg/apps/mbank.png",
             "android_package_name": "kg.mbank", "is_active_on_ios": True}], 600)
        invoice = self.make_invoice()
        data = service.invoice_json(invoice)
        self.assertEqual(set(data), {
            "kind", "provider", "resumed", "order_id", "status", "ui_state", "amount", "currency",
            "original_amount", "discount_percent", "package", "credits", "qr", "apps",
            "checkout_url", "created_at", "expires_at", "server_time", "seconds_left",
            "lifetime_seconds", "is_test", "can_cancel", "return_to"})
        self.assertNotIn("redirect_url", data)
        self.assertEqual((data["kind"], data["provider"], data["resumed"]), ("qr", "gopay", False))
        self.assertEqual((data["order_id"], data["status"], data["ui_state"]),
                         (ORDER, "created", "awaiting_payment"))
        self.assertEqual((data["amount"], data["currency"]), ("392.00", "KGS"))
        self.assertIsNone(data["original_amount"])
        self.assertIsNone(data["discount_percent"])
        self.assertEqual(data["package"], {"id": 3, "name": "Про", "tokens": 500,
                                           "bonus_tokens": 0})
        self.assertEqual(data["credits"], {"total": 500, "credited": 0})
        self.assertEqual(data["qr"], {"data": QR_DATA,
                                      "image_url": f"https://pay.gopay.kg/p/{PID}/qr/"})
        self.assertEqual(data["apps"], [{
            "code": "mbank", "name": "MBank", "url": "mbank://elqr?data=abc",
            "icon": "https://media.gopay.kg/apps/mbank.png", "ios": True, "android": True}])
        self.assertEqual(data["checkout_url"], f"https://pay.gopay.kg/p/{PID}/")
        self.assertEqual(data["expires_at"], invoice.expires_at.isoformat())
        self.assertEqual(data["created_at"], invoice.created_at.isoformat())
        self.assertTrue(895 <= data["seconds_left"] <= 900)
        self.assertEqual(data["lifetime_seconds"], 900)
        self.assertIs(data["is_test"], False)
        self.assertIs(data["can_cancel"], True)
        self.assertEqual(data["return_to"], "/profile")
        self.assertTrue(service.invoice_json(invoice, resumed=True)["resumed"])
        json.dumps(data)        # целиком сериализуется

    def test_invoice_json_blanks_payment_data_outside_awaiting(self):
        invoice = self.make_invoice()
        for fields in ({"status": "expired"}, {"status": "cancelled"}, {"status": "failed"},
                       {"status": "committed"}, {"cancel_requested_at": timezone.now()},
                       {"expires_at": timezone.now() - timedelta(seconds=5)}):
            GoPayInvoice.objects.filter(pk=invoice.pk).update(
                status="created", cancel_requested_at=None,
                expires_at=timezone.now() + timedelta(minutes=15))
            GoPayInvoice.objects.filter(pk=invoice.pk).update(**fields)
            data = service.invoice_json(GoPayInvoice.objects.get(pk=invoice.pk))
            self.assertNotEqual(data["ui_state"], "awaiting_payment", fields)
            self.assertEqual(data["qr"], {"data": "", "image_url": ""}, fields)
            self.assertEqual(data["apps"], [], fields)
            self.assertEqual(data["checkout_url"], "", fields)
            self.assertIs(data["can_cancel"], False, fields)
        self.assertEqual(data["seconds_left"], 0)

    def test_invoice_json_paid_and_discount(self):
        payment = self.make_payment(request_extra={
            "exit_discount": {"offer_id": 5, "percent": 20, "original_amount": "490.00"},
            "token_purchase": {"package_id": 3, "tokens": 500, "bonus_tokens": 50}})
        invoice = self.make_invoice(payment)
        data = service.invoice_json(invoice)
        self.assertEqual((data["original_amount"], data["discount_percent"]), ("490.00", 20))
        self.assertEqual(data["credits"], {"total": 550, "credited": 0})
        service.apply_state(invoice, state_of(status="COMMITTED"), source="query")
        data = service.invoice_json(GoPayInvoice.objects.get(pk=invoice.pk))
        self.assertEqual(data["ui_state"], "paid")
        self.assertEqual(data["credits"], {"total": 550, "credited": 550})
        self.assertEqual(data["status"], "committed")

    def test_invoice_json_for_a_test_invoice(self):
        cache.set("gopay:apps:v1:test", [
            {"code": "mbank", "name": "MBank", "order": 1, "url": "mbank://elqr?data={qr_data}",
             "icon": "", "android_package_name": "kg.mbank", "is_active_on_ios": True}], 600)
        payment = self.make_payment(env="test", request_extra={
            "gopay": {"env": "test", "lifetime": 900}})
        invoice = self.make_invoice(payment, env="test", qr_data="", qr_url="")
        data = service.invoice_json(invoice)
        self.assertEqual(data["ui_state"], "awaiting_payment")
        self.assertEqual(data["qr"], {"data": "", "image_url": ""})
        # Тестовый QR не оплачивается — кнопок банков нет, даже если ссылки есть.
        self.assertEqual(data["apps"], [])
        self.assertIs(data["is_test"], True)
        self.assertEqual(data["package"]["name"], "")

    # --- банки ------------------------------------------------------------------

    CATALOG = [
        {"code": "megapay", "name": "MegaPay", "order": 2, "url": "megapay://elqr?data={qr_data}",
         "icon": "https://media.gopay.kg/apps/megapay.png",
         "android_package_name": "kg.megabank.megapay", "is_active_on_ios": False},
        {"code": "mbank", "name": "MBank", "order": 1, "url": "mbank://elqr?data={qr_data}",
         "icon": "https://media.gopay.kg/apps/mbank.png",
         "android_package_name": "kg.mbank.mbankmobile", "is_active_on_ios": True},
        {"code": "optima", "name": "Optima24", "order": 3, "url": "optima24://pay",
         "icon": "http://insecure.example/icon.png", "android_package_name": "",
         "is_active_on_ios": None},
    ]

    def test_apps_for_prefers_links_of_the_payment(self):
        cache.set("gopay:apps:v1:live", self.CATALOG, 600)
        invoice = self.make_invoice(app_links={
            "megapay": "megapay://payment?id=1", "mbank": "mbank://payment?id=1",
            "newbank": "newbank://pay?id=1"})
        apps = service.apps_for(invoice)
        self.assertEqual([a["code"] for a in apps], ["mbank", "megapay", "newbank"])
        self.assertEqual(apps[0], {"code": "mbank", "name": "MBank", "url": "mbank://payment?id=1",
                                   "icon": "https://media.gopay.kg/apps/mbank.png",
                                   "ios": True, "android": True})
        # False обязан дойти до клиента как false, а не как null.
        self.assertIs(apps[1]["ios"], False)
        self.assertIs(apps[1]["android"], True)
        # Кода нет в списке GoPay: имя из кода, платформы неизвестны.
        self.assertEqual(apps[2], {"code": "newbank", "name": "Newbank",
                                   "url": "newbank://pay?id=1", "icon": "",
                                   "ios": None, "android": None})
        self.assertEqual(self.fake.calls, [])

    def test_relative_icon_path_resolves_to_gopay_media(self):
        # GoPay отдаёт значок путём без узла; файлы лежат на media.gopay.kg.
        # Раньше такой путь отбрасывался — и у банка на экране стояла буква.
        self.fake.on("/v1/payment-app", ok([
            {"code": "mbank", "name": "MBank", "order": 1, "url": "mbank://elqr?data={qr_data}",
             "icon": "payment_apps/mbank.webp", "android_package_name": "kg.mbank",
             "is_active_on_ios": True},
            {"code": "odengi", "name": "O!Dengi", "order": 2, "url": "odengi://elqr?d={qr_data}",
             "icon": "/payment_apps/odengi.webp", "android_package_name": "kg.o",
             "is_active_on_ios": True},
            {"code": "optima", "name": "Optima24", "order": 3, "url": "optima://elqr?d={qr_data}",
             "icon": "https://media.gopay.kg/apps/optima.png", "android_package_name": "kg.optima",
             "is_active_on_ios": True},
            {"code": "evil", "name": "Evil", "order": 4, "url": "evil://elqr?d={qr_data}",
             "icon": "//evil.example/icon.png", "android_package_name": "kg.evil",
             "is_active_on_ios": True}]))
        service.refresh_apps_cache("live")
        icons = {a["code"]: a["icon"] for a in service.apps_for(self.make_invoice(app_links={}))}
        self.assertEqual(icons, {
            "mbank": "https://media.gopay.kg/payment_apps/mbank.webp",
            "odengi": "https://media.gopay.kg/payment_apps/odengi.webp",
            "optima": "https://media.gopay.kg/apps/optima.png",
            "evil": ""})
        # Значок без узла, но кнопка всё равно есть: буква на экране, а не дыра.
        self.assertEqual(len(icons), 4)

    def test_icon_url_is_https_on_a_gopay_host_or_nothing(self):
        base = "https://media.gopay.kg/"
        for value, expected in (
                ("payment_apps/mbank.webp", base + "payment_apps/mbank.webp"),
                ("  payment_apps/mbank.webp  ", base + "payment_apps/mbank.webp"),
                ("/payment_apps/mbank.webp", base + "payment_apps/mbank.webp"),
                ("../payment_apps/mbank.webp", base + "payment_apps/mbank.webp"),
                ("payment_apps/mbank.webp?v=3", base + "payment_apps/mbank.webp?v=3"),
                (base + "apps/mbank.png", base + "apps/mbank.png"),
                ("https://gopay.kg/static/mbank.png", "https://gopay.kg/static/mbank.png"),
                ("https://pay.gopay.kg/i/mbank.png", "https://pay.gopay.kg/i/mbank.png")):
            self.assertEqual(service._icon_url(value), expected, value)
        for value in (
                "", "   ", None, 0, 5, ["payment_apps/mbank.webp"], {"icon": "x"},
                # не https
                "http://media.gopay.kg/apps/mbank.png", "ftp://media.gopay.kg/mbank.png",
                "javascript:alert(1)", "data:image/png;base64,AAAA",
                # чужой узел — в том числе похожий на наш
                "https://insecure.example/icon.png", "//evil.example/icon.png",
                "https://media.gopay.kg.evil.example/icon.png",
                "https://evilgopay.kg/icon.png", "https://gopay.kg.evil.example/icon.png",
                # узел подменён учётными данными, портом или обратным слэшем
                "https://media.gopay.kg@evil.example/icon.png",
                "https://user:pass@media.gopay.kg/icon.png",
                "https://media.gopay.kg:8443/icon.png",
                "https://evil.example\\@media.gopay.kg/icon.png",
                "\\\\evil.example/icon.png",
                # то, чему в адресе картинки не место
                "payment_apps/m bank.webp", "payment_apps/mbank.webp#x",
                'payment_apps/"><script>.webp', "payment_apps/mbank.webp\nX",
                "https://[media.gopay.kg/icon.png",
                "p/" + "a" * 500):
            self.assertEqual(service._icon_url(value), "", repr(value))

    def test_apps_for_drops_an_icon_from_a_foreign_or_insecure_address(self):
        cache.set("gopay:apps:v1:live", self.CATALOG, 600)
        invoice = self.make_invoice(app_links={
            "mbank": "mbank://payment?id=1", "optima": "optima24://pay?id=1"})
        icons = {a["code"]: a["icon"] for a in service.apps_for(invoice)}
        # У optima в списке http-адрес на чужом узле — значка нет, кнопка есть.
        self.assertEqual(icons, {"mbank": "https://media.gopay.kg/apps/mbank.png", "optima": ""})

    def test_mbank_link_gets_the_slash_mbank_itself_uses(self):
        # GoPay отдаёт /qr#<код>, а МБанк открывает оплату по /qr/#<код>.
        cache.set("gopay:apps:v1:live", self.CATALOG, 600)
        invoice = self.make_invoice(app_links={
            "mbank": "https://app.mbank.kg/qr#000201010212PAYLOAD",
            "megapay": "https://megapay.kg/get#000201010212PAYLOAD"})
        apps = {a["code"]: a["url"] for a in service.apps_for(invoice)}
        self.assertEqual(apps["mbank"], "https://app.mbank.kg/qr/#000201010212PAYLOAD")
        # Остальные банки и уже правильная ссылка не трогаются.
        self.assertEqual(apps["megapay"], "https://megapay.kg/get#000201010212PAYLOAD")
        self.assertEqual(service._fix_bank_link("mbank", "https://app.mbank.kg/qr/#X"),
                         "https://app.mbank.kg/qr/#X")
        self.assertEqual(service._fix_bank_link("odengi", "https://app.mbank.kg/qr#X"),
                         "https://app.mbank.kg/qr#X")

    def test_apps_for_falls_back_to_templates(self):
        cache.set("gopay:apps:v1:live", self.CATALOG, 600)
        invoice = self.make_invoice(app_links={})
        apps = service.apps_for(invoice)
        # Шаблон без {qr_data} ссылкой на оплату не является.
        self.assertEqual([a["code"] for a in apps], ["mbank", "megapay"])
        self.assertEqual(apps[0]["url"], f"mbank://elqr?data={QR_DATA}")
        self.assertIs(apps[1]["ios"], False)
        # Без содержимого QR по шаблону строить нечего.
        GoPayInvoice.objects.filter(pk=invoice.pk).update(qr_data="")
        self.assertEqual(service.apps_for(GoPayInvoice.objects.get(pk=invoice.pk)), [])

    def test_apps_for_string_false_from_gopay_is_false(self):
        self.fake.on("/v1/payment-app", ok([
            {"code": "megapay", "name": "MegaPay", "order": "2",
             "url": "megapay://elqr?data={qr_data}", "is_active_on_ios": "false",
             "android_package_name": "kg.megabank.megapay"}]))
        service.refresh_apps_cache("live")
        apps = service.apps_for(self.make_invoice(app_links={}))
        self.assertIs(apps[0]["ios"], False)
        self.assertIs(apps[0]["android"], True)

    def test_missing_android_package_never_hides_a_bank(self):
        # Признака «на Android недоступен» у GoPay нет: пустое имя пакета — это
        # «не знаем». False клиент понял бы как «спрятать» — и банк, на который
        # GoPay сам прислал готовую ссылку, исчез бы у всех покупателей с Android.
        cache.set("gopay:apps:v1:live", [
            {"code": "mbank", "name": "MBank", "order": 1, "url": "", "icon": "",
             "android_package_name": "", "is_active_on_ios": True},
            {"code": "optima", "name": "Optima24", "order": 2, "url": "", "icon": "",
             "is_active_on_ios": True},
            {"code": "megapay", "name": "MegaPay", "order": 3, "url": "", "icon": "",
             "android_package_name": "kg.megabank.megapay", "is_active_on_ios": False},
        ], 600)
        invoice = self.make_invoice(app_links={
            "mbank": "mbank://payment?id=1", "optima": "optima24://pay?id=1",
            "megapay": "megapay://payment?id=1"})
        apps = {a["code"]: a for a in service.apps_for(invoice)}
        self.assertIsNone(apps["mbank"]["android"])
        self.assertIsNone(apps["optima"]["android"])
        self.assertIs(apps["megapay"]["android"], True)
        self.assertNotIn(False, [a["android"] for a in apps.values()])
        # С iPhone всё по-прежнему: там отметка есть, и False обязан дойти.
        self.assertIs(apps["megapay"]["ios"], False)

    def test_apps_fresh_tells_the_fresh_copy_from_the_last_good_one(self):
        self.assertFalse(service.apps_fresh("live"))
        # Только «последний удачный» список: показывать можно, но он не свежий.
        cache.set("gopay:apps:last:live", self.CATALOG, 600)
        self.assertEqual(len(service.cached_apps("live")), 3)
        self.assertFalse(service.apps_fresh("live"))
        self.fake.on("/v1/payment-app", ok(self.CATALOG[:2]))
        service.refresh_apps_cache("live")
        self.assertTrue(service.apps_fresh("live"))
        self.assertFalse(service.apps_fresh("test"))
        # Пустой ответ GoPay — тоже ответ: спрашивать снова раньше срока незачем.
        cache.clear()
        self.fake.on("/v1/payment-app", ok([]))
        service.refresh_apps_cache("live")
        self.assertTrue(service.apps_fresh("live"))
        # Сбой свежей копии не оставляет.
        cache.clear()
        self.fake.on("/v1/payment-app", requests.Timeout())
        service.refresh_apps_cache("live")
        self.assertFalse(service.apps_fresh("live"))
        with patch("payments.gopay.service.cache.get", side_effect=RuntimeError("кэш лежит")):
            self.assertTrue(service.apps_fresh("live"))

    def test_apps_for_without_a_catalog_and_with_unsafe_links(self):
        invoice = self.make_invoice(app_links={"mbank": "mbank://pay", "evil": "javascript:1"})
        apps = service.apps_for(invoice)
        self.assertEqual(apps, [{"code": "mbank", "name": "Mbank", "url": "mbank://pay",
                                 "icon": "", "ios": None, "android": None}])

    def test_apps_are_capped_and_ordered(self):
        catalog = [{"code": f"b{i:02d}", "name": f"Bank {i:02d}", "order": 100 - i,
                    "url": "bank://p?d={qr_data}", "icon": "", "android_package_name": "p",
                    "is_active_on_ios": True} for i in range(40)]
        self.fake.on("/v1/payment-app", ok(catalog))
        stored = service.refresh_apps_cache("live")
        self.assertEqual(len(stored), service.APPS_MAX)
        apps = service.apps_for(self.make_invoice(app_links={}))
        self.assertEqual(len(apps), service.APPS_MAX)
        orders = [100 - int(a["code"][1:]) for a in apps]
        self.assertEqual(orders, sorted(orders))

    def test_apps_cache_never_hits_the_network_on_read(self):
        self.assertEqual(service.cached_apps("live"), [])
        service.apps_for(self.make_invoice())
        service.invoice_json(self.make_invoice(
            self.make_payment(order_id="tokpkg-7-3-read000000"), provider_payment_id="d" * 32))
        self.assertEqual(self.fake.calls, [])

    def test_empty_answer_does_not_replace_the_last_good_list(self):
        self.fake.on("/v1/payment-app", ok(self.CATALOG))
        self.assertEqual(len(service.refresh_apps_cache("live")), 3)
        self.assertEqual(self.fake.calls[0].headers["GoPay-Api-Key"], LIVE_API_KEY)
        self.fake.on("/v1/payment-app", ok([]))
        self.assertEqual(len(service.refresh_apps_cache("live")), 3)
        self.assertEqual(cache.get("gopay:apps:v1:live"), [])
        self.assertEqual(len(cache.get("gopay:apps:last:live")), 3)
        self.assertEqual(len(service.cached_apps("live")), 3)
        # Среды не смешиваются.
        self.assertEqual(service.cached_apps("test"), [])

    def test_refresh_apps_cache_never_raises(self):
        cache.set("gopay:apps:last:live", self.CATALOG[:1], 600)
        for response in (requests.Timeout(), fail("4001", "bad signature"), html(500),
                         RuntimeError("boom")):
            self.fake.on("/v1/payment-app", response)
            self.assertEqual([a["code"] for a in service.refresh_apps_cache("live")], ["megapay"])
        with override_settings(GOPAY_LIVE_API_KEY=""):
            self.assertEqual(len(service.refresh_apps_cache("live")), 1)
        self.assertEqual(service.refresh_apps_cache("prod"), [])

    # --- вебхук -----------------------------------------------------------------

    def test_verify_webhook(self):
        self.assertEqual(service.verify_webhook(V4_NONCE, V4_SIG, V4_RAW), ["test"])
        self.assertEqual(service.verify_webhook(V4_NONCE, V4_SIG.lower(), V4_RAW), ["test"])
        live_sig = independent_sign(LIVE_WEBHOOK_SECRET, V4_NONCE, V4_RAW)
        self.assertEqual(service.verify_webhook(V4_NONCE, live_sig, V4_RAW), ["live"])
        self.assertEqual(service.verify_webhook(V4_NONCE, V4_SIG, V4_RAW + b" "), [])
        self.assertEqual(service.verify_webhook("", V4_SIG, V4_RAW), [])
        self.assertEqual(service.verify_webhook(V4_NONCE, "", V4_RAW), [])
        self.assertEqual(service.verify_webhook(V4_NONCE, None, V4_RAW), [])
        # Подпись секретом API (а не вебхуков) не принимается.
        api_sig = independent_sign(API_SECRET, V4_NONCE, V4_RAW)
        self.assertEqual(service.verify_webhook(V4_NONCE, api_sig, V4_RAW), [])
        with override_settings(GOPAY_LIVE_WEBHOOK_SECRET=WEBHOOK_SECRET):
            self.assertEqual(service.verify_webhook(V4_NONCE, V4_SIG, V4_RAW), ["test", "live"])
        with override_settings(GOPAY_TEST_WEBHOOK_SECRET="", GOPAY_LIVE_WEBHOOK_SECRET=""):
            self.assertEqual(service.verify_webhook(V4_NONCE, V4_SIG, V4_RAW), [])
            empty_sig = independent_sign("", V4_NONCE, V4_RAW)
            self.assertEqual(service.verify_webhook(V4_NONCE, empty_sig, V4_RAW), [])

    def test_event_key_depends_on_every_part(self):
        state = PaymentState.from_payload(json.loads(V4_RAW)["data"])
        base = service.event_key("payment.committed", state, "2026-09-03T04:00:20Z")
        self.assertEqual(base, V5_KEY)
        self.assertEqual(len(base), 64)
        other_state = PaymentState.from_payload({**json.loads(V4_RAW)["data"],
                                                 "payment_id": "f" * 32})
        expired = PaymentState.from_payload({**json.loads(V4_RAW)["data"], "status": "EXPIRED"})
        for key in (service.event_key("payment.expired", state, "2026-09-03T04:00:20Z"),
                    service.event_key("payment.committed", state, "2026-09-03T04:00:21Z"),
                    service.event_key("payment.committed", other_state, "2026-09-03T04:00:20Z"),
                    service.event_key("payment.committed", expired, "2026-09-03T04:00:20Z")):
            self.assertNotEqual(key, base)

    def test_sanitize_event(self):
        body = json.loads(V4_RAW)
        body["data"]["qr_data"] = QR_DATA
        body["data"]["buyer"] = {"email": "buyer@example.com"}
        body["signature"] = V4_SIG
        clean = service.sanitize_event(body)
        self.assertEqual(set(clean), {"event", "created_at", "data"})
        self.assertEqual(clean["event"], "payment.committed")
        self.assertEqual(clean["created_at"], "2026-09-03T04:00:20Z")
        self.assertEqual(clean["data"], {
            "payment_id": PID, "order_id": ORDER, "status": "COMMITTED", "amount": "100.00",
            "testing_mode": True, "created_at": "2026-09-03T04:00:00Z",
            "committed_at": "2026-09-03T04:00:20Z"})
        dumped = json.dumps(clean)
        for leak in (V4_SIG, "buyer@example.com", QR_DATA):
            self.assertNotIn(leak, dumped)

        receipt = {"event": "receipt.sent", "created_at": "2026-09-03T04:01:00Z",
                   "data": {"payment_id": PID, "order_id": ORDER,
                            "receipt_url": "https://tax.salyk.kg/check?fn=1"}}
        self.assertEqual(service.sanitize_event(receipt)["data"]["receipt_url"],
                         "https://tax.salyk.kg/check?fn=1")
        receipt["data"]["receipt_url"] = "http://tax.salyk.kg/check"
        self.assertNotIn("receipt_url", service.sanitize_event(receipt)["data"])
        receipt["data"]["receipt_url"] = "https://tax.salyk.kg/" + "x" * 600
        self.assertNotIn("receipt_url", service.sanitize_event(receipt)["data"])
        # receipt_url в событии об оплате не сохраняется.
        body["data"]["receipt_url"] = "https://tax.salyk.kg/check?fn=1"
        self.assertNotIn("receipt_url", service.sanitize_event(body)["data"])
        for garbage in (None, [], "x", {"event": 5, "data": "nope", "created_at": []}):
            self.assertEqual(service.sanitize_event(garbage),
                             {"event": "", "created_at": "", "data": {}})


# ============================================ здоровье и предохранитель ===

@override_settings(**GOPAY_SETTINGS)
class HealthTests(GoPayTestCase):
    def health_events(self):
        return EventLog.objects.filter(level="error", meta__gopay_health__isnull=False)

    def test_two_unavailable_in_a_row_open_the_breaker(self):
        self.assertFalse(service.provider_down("live"))
        self.assertEqual(service.health("live"), {"ok": True, "fails": 0, "kind": "", "code": "",
                                                  "since": None, "down": False})
        service.note_result("live", GoPayUnavailable(code="network"))
        self.assertFalse(service.provider_down("live"))
        service.note_result("live", GoPayUnavailable(code="http_503"))
        self.assertTrue(service.provider_down("live"))
        state = service.health("live")
        self.assertEqual((state["ok"], state["fails"], state["kind"], state["code"], state["down"]),
                         (False, 2, "unavailable", "http_503", True))
        self.assertIsNotNone(state["since"])
        # Среды независимы.
        self.assertFalse(service.provider_down("test"))
        self.assertTrue(service.health("test")["ok"])

        service.note_result("live", None)
        self.assertFalse(service.provider_down("live"))
        self.assertTrue(service.health("live")["ok"])

    def test_since_is_kept_from_the_first_failure(self):
        service.note_result("live", GoPayUnavailable(code="network"))
        since = service.health("live")["since"]
        service.note_result("live", GoPayUnavailable(code="network"))
        self.assertEqual(service.health("live")["since"], since)

    def test_auth_failures_alert_once_per_window(self):
        for _ in range(4):
            service.note_result("live", GoPayRejected(code="auth", kind="auth"))
        self.assertEqual(self.health_events().count(), 0)
        with self.assertLogs("payments.gopay", level="ERROR"):
            service.note_result("live", GoPayRejected(code="auth", kind="auth"))
        self.assertEqual(self.health_events().count(), 1)
        event = self.health_events().get()
        self.assertEqual(event.meta, {"gopay_health": "auth", "env": "live", "fails": 5})
        self.assertIn("live", event.message)
        service.note_result("live", GoPayRejected(code="auth", kind="auth"))
        self.assertEqual(self.health_events().count(), 1)
        # Отказ в ключе — не «GoPay лежит»: предохранитель не срабатывает.
        self.assertFalse(service.provider_down("live"))
        self.assertEqual(service.health("live")["fails"], 6)

    def test_a_refusal_means_gopay_is_alive(self):
        service.note_result("live", GoPayUnavailable(code="network"))
        service.note_result("live", GoPayRejected(code="cannot_cancel", kind="cannot_cancel",
                                                  provider_code="0013"))
        self.assertTrue(service.health("live")["ok"])
        service.note_result("live", GoPayUnavailable(code="network"))
        self.assertFalse(service.provider_down("live"))

    def test_org_inactive_and_not_configured_count_as_failures(self):
        service.note_result("live", GoPayRejected(code="org_inactive", kind="org_inactive"))
        service.note_result("live", GoPayError(code="not_configured", kind="not_configured"))
        self.assertEqual(service.health("live")["fails"], 2)
        self.assertFalse(service.provider_down("live"))

    def test_circuit_open_is_not_counted(self):
        service.note_result("live", GoPayUnavailable(code="network"))
        for _ in range(5):
            service.note_result("live", GoPayUnavailable(code="circuit_open"))
        self.assertEqual(service.health("live")["fails"], 1)
        self.assertFalse(service.provider_down("live"))

    def test_real_calls_feed_the_health(self):
        invoice = self.make_invoice()
        self.fake.on("/v1/payments/query", requests.Timeout())
        for _ in range(2):
            with self.assertRaises(GoPayUnavailable):
                service.fetch_state(invoice)
        self.assertTrue(service.provider_down("live"))
        self.fake.on("/v1/payments/query", ok(pay_data()))
        service.fetch_state(invoice)
        self.assertFalse(service.provider_down("live"))
        self.assertTrue(service.health("live")["ok"])

    def test_broken_cache_breaks_nothing(self):
        invoice = self.make_invoice(app_links={})

        class BrokenCache:
            def __getattr__(self, name):
                def boom(*args, **kwargs):
                    raise RuntimeError("cache is down")
                return boom

        self.fake.on("/v1/payments/query", ok(pay_data(
            status="COMMITTED", amount="39.20")))
        with patch("payments.gopay.service.cache", BrokenCache()):
            service.note_result("live", GoPayUnavailable(code="network"))
            service.note_result("live", None)
            self.assertFalse(service.provider_down("live"))
            self.assertEqual(service.health("live")["fails"], 0)
            self.assertEqual(service.cached_apps("live"), [])
            self.assertEqual(service.apps_for(invoice), [])
            self.assertEqual(service.refresh_apps_cache("live"), [])
            self.assertEqual(service.admin_state()["unsettled"], 0)
            # Сигнал о разборе без кэша всё равно пишется.
            with self.assertLogs("payments.gopay", level="ERROR"):
                self.assertEqual(service.refresh_invoice(invoice), "mismatch")
            self.assertEqual(service.invoice_json(invoice)["kind"], "qr")
        self.assertEqual(self.review_events().count(), 1)

    def test_in_flight_count_and_admin_state(self):
        now = timezone.now()

        def invoice(index, env="live", payment_over=None, **fields):
            payment = self.make_payment(env=env, order_id=f"tokpkg-7-3-flig0000{index:02d}",
                                        **(payment_over or {}))
            inv = self.make_invoice(payment, env=env, provider_payment_id=f"{index:02d}" * 16)
            if fields:
                GoPayInvoice.objects.filter(pk=inv.pk).update(**fields)
            return inv

        self.assertEqual(service.in_flight_count("live"), 0)
        invoice(1)                                                        # открыт
        invoice(2, status="pending")                                      # открыт
        invoice(3, status="expired", finalized_at=now - timedelta(hours=1))    # в позднем окне
        invoice(4, status="cancelled", finalized_at=now - timedelta(hours=7))  # окно вышло
        invoice(5, status="expired", finalized_at=now - timedelta(days=3),
                flags={"local_expiry": True})                             # не подтверждён, 7 дней
        invoice(6, status="expired", finalized_at=now - timedelta(days=8),
                flags={"local_expiry": True})                             # и это окно вышло
        invoice(7, status="committed")                                    # оплачен, не зачислен
        invoice(8, status="committed", payment_over={"success": True})    # оплачен и зачислен
        invoice(9, status="committed",
                payment_over={"response": {"admin_refund": {"by": 1}}})   # возврат отмечен
        invoice(10, status="committed",
                payment_over={"response": {"token_purchase_clawed_back": True}})
        invoice(11, env="test")                                           # другая среда
        invoice(12, status="failed", finalized_at=None)                   # закрыт без даты

        self.assertEqual(service.in_flight_count("live"), 5)
        self.assertEqual(service.in_flight_count("test"), 1)
        state = service.admin_state()
        self.assertEqual(set(state), {"health", "in_flight", "unsettled"})
        self.assertEqual(state["in_flight"], {"test": 1, "live": 5})
        self.assertEqual(state["unsettled"], 1)
        self.assertEqual(set(state["health"]), {"test", "live"})
        self.assertEqual(set(state["health"]["live"]),
                         {"ok", "fails", "kind", "code", "since", "down"})
        json.dumps(state)


# ============================================================= модели ===

class ModelTests(TestCase):
    def test_migration_file_exists(self):
        path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "migrations",
                            "0006_gopay.py")
        self.assertTrue(os.path.exists(path))
        with open(path, encoding="utf-8") as handle:
            source = handle.read()
        self.assertIn("('payments', '0005_fix_yookassa_provider')", source)
        self.assertIn("name='GoPayInvoice'", source)
        self.assertIn("name='GoPayWebhookEvent'", source)
        self.assertIn("('gopay', 'GoPay (единый QR)')", source)

    def test_provider_choice_and_funnel_names(self):
        from payments.models import FunnelEvent

        self.assertIn(("gopay", "GoPay (единый QR)"), Payment.PROVIDER_CHOICES)
        index = FunnelEvent.NAMES.index("kgs_method_pick")
        self.assertEqual(FunnelEvent.NAMES[index + 1:index + 7],
                         ("kgs_qr_shown", "kgs_qr_app_open", "kgs_qr_save", "kgs_qr_paid",
                          "kgs_qr_expired", "kgs_qr_other_method"))
        for name in FunnelEvent.NAMES:
            self.assertLessEqual(len(name), 32)

    def test_invoice_constants(self):
        self.assertEqual(GoPayInvoice.OPEN_STATES, ("created", "pending"))
        self.assertEqual(GoPayInvoice.CLOSED_UNPAID, ("failed", "expired", "cancelled"))
        self.assertEqual([c[0] for c in GoPayInvoice.STATUS_CHOICES],
                         ["created", "pending", "committed", "failed", "expired", "cancelled"])

    def _payment(self, order):
        return Payment.objects.create(provider="gopay", amount=Decimal("10.00"), currency="KGS",
                                      order_id=order, request={}, response={})

    def test_provider_payment_id_and_payment_are_unique(self):
        first = self._payment("tokpkg-1-1-aaaaaaaaaa")
        invoice = GoPayInvoice.objects.create(
            payment=first, env="live", provider_payment_id=PID, amount=Decimal("10.00"),
            lifetime_seconds=900, expires_at=timezone.now())
        self.assertEqual(invoice.status, "created")
        self.assertTrue(invoice.is_open)
        self.assertEqual((invoice.flags, invoice.app_links, invoice.qr_data), ({}, {}, ""))
        self.assertEqual(first.gopay_invoice.pk, invoice.pk)
        with self.assertRaises(IntegrityError), transaction.atomic():
            GoPayInvoice.objects.create(
                payment=self._payment("tokpkg-1-1-bbbbbbbbbb"), env="live",
                provider_payment_id=PID, amount=Decimal("10.00"), lifetime_seconds=900,
                expires_at=timezone.now())
        with self.assertRaises(IntegrityError), transaction.atomic():
            GoPayInvoice.objects.create(
                payment=first, env="live", provider_payment_id="f" * 32,
                amount=Decimal("10.00"), lifetime_seconds=900, expires_at=timezone.now())
        GoPayInvoice.objects.filter(pk=invoice.pk).update(status="expired")
        invoice.refresh_from_db()
        self.assertFalse(invoice.is_open)

    def test_webhook_event_key_is_unique(self):
        GoPayWebhookEvent.objects.create(event_key=V5_KEY, event="payment.committed")
        with self.assertRaises(IntegrityError), transaction.atomic():
            GoPayWebhookEvent.objects.create(event_key=V5_KEY, event="payment.committed")
        event = GoPayWebhookEvent.objects.get()
        self.assertEqual((event.processed, event.result, event.payload, event.amount),
                         (False, "", {}, None))

    def test_django_admin_is_read_only(self):
        for model in (GoPayInvoice, GoPayWebhookEvent):
            self.assertTrue(admin.site.is_registered(model))
            model_admin = admin.site._registry[model]
            self.assertFalse(model_admin.has_add_permission(None))
            self.assertFalse(model_admin.has_change_permission(None))
            self.assertFalse(model_admin.has_delete_permission(None))
