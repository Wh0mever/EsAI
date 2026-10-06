# -*- coding: utf-8 -*-
"""Единый QR (GoPay): состояние счёта, отказ от него, вебхук, сверка, воронка.

Ни один тест не ходит в сеть: payments.gopay.client.requests.post подменён
«банком» с памятью — он помнит счета и отвечает так, как ответил бы GoPay.
Ключи здесь — заведомые пустышки.

Главное, что проверяется: подписанное «оплачено» само не зачисляет — зачисляет
ответ на наш запрос статуса, ровно один раз; закрытие счёта не отменяет
оплату; сверка не занимает общую очередь, когда GoPay лежит.
"""
import json
import uuid
from datetime import timedelta
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import patch

import requests
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from audit.models import EventLog
from payments import tasks
from payments.funnel import _payment_stage, funnel_report
from payments.gopay import config, service
from payments.gopay.client import serialize, sign
from payments.models import FunnelEvent, GoPayInvoice, GoPayWebhookEvent, Payment
from payments.tests_gopay_core import (
    API_KEY, BASE, GOPAY_SETTINGS, LIVE_WEBHOOK_SECRET, ORDER, PID, QR_DATA, V4_NONCE,
    V4_RAW, V4_SIG, WEBHOOK_SECRET, FakeResponse, fail, html, ok,
)
from plans.models import ExitDiscountOffer, TokenPackage, TokenTransaction

FLOW_CACHES = {"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache",
                           "LOCATION": "gopay-flow-tests"}}
# Боевая среда, способ открыт всем — как после запуска. Тестовую среду тесты
# включают сами там, где она нужна.
FLOW_SETTINGS = dict(
    GOPAY_SETTINGS, CACHES=FLOW_CACHES, GOPAY_MODE="on", GOPAY_ENV="live",
    KGS_METHODS_MODE="on",
    FREEDOM_PAY_MERCHANT_ID="m1", FREEDOM_PAY_TOKEN="secret",
    FREEDOM_PAY_INIT_PAYMENT_URL="https://fp.example/init_payment.php",
    YOOKASSA_SHOP_ID="", YOOKASSA_SECRET_KEY="",
)
WEBHOOK_PATH = "/api/payments/gopay/webhook/"
NETWORK_DOWN = requests.ConnectionError("нет сети")


class Bank:
    """Поддельный GoPay с памятью.

    Помнит счета и отвечает по ним, как настоящий: создание, статус, отмена,
    список банков. Тест меняет статус счёта (pay / set_status) или подсовывает
    на очередной запрос свой ответ (script) — после него банк снова отвечает сам.
    """

    def __init__(self):
        self.calls = []
        self.records = {}       # payment_id -> запись счёта
        self.scripts = {}       # путь -> очередь ответов «вне очереди»
        self.forever = {}       # путь -> ответ на каждый запрос
        self.on_call = None     # хук: вызывается на каждый запрос (часы, замки)

    # --- управление из теста -------------------------------------------------

    def add(self, payment_id, order_id, amount, status="CREATED", test=False):
        record = {
            "payment_id": payment_id, "order_id": order_id, "amount": str(amount),
            "status": status, "qr_data": QR_DATA,
            "qr_url": f"https://pay.gopay.kg/p/{payment_id}/qr/",
            "checkout_url": f"https://pay.gopay.kg/p/{payment_id}/",
            "app_links": {"mbank": "mbank://elqr?data=abc"},
            "created_at": "2026-10-06T10:00:00", "expires_at": "2026-10-06T10:15:00",
            "committed_at": None, "bank_op_date": None,
        }
        if test:
            record["testing_mode"] = True       # GoPay шлёт флаг только у тестовых
        self.records[payment_id] = record
        return record

    def of(self, invoice):
        return self.records[invoice.provider_payment_id]

    def set_status(self, invoice, status, **over):
        record = self.of(invoice)
        record["status"] = status
        record.update(over)
        return record

    def pay(self, invoice, **over):
        return self.set_status(invoice, "COMMITTED", committed_at="2026-10-06T10:01:00Z",
                               bank_op_date="2026-10-06", **over)

    def script(self, path, *answers):
        """Ответить на ближайшие запросы к пути этими ответами (None — «как обычно»)."""
        self.scripts.setdefault(path, []).extend(answers)
        return self

    def always(self, path, answer):
        self.forever[path] = answer
        return self

    # --- сам «GoPay» -----------------------------------------------------------

    def __call__(self, url, data=None, headers=None, timeout=None, **kwargs):
        path = url[len(BASE):] if url.startswith(BASE) else url
        body = json.loads(data)
        self.calls.append(SimpleNamespace(path=path, body=body, data=data,
                                          headers=headers or {}, timeout=timeout, kwargs=kwargs))
        if self.on_call is not None:
            self.on_call(path)
        answer = None
        queue = self.scripts.get(path)
        if queue:
            answer = queue.pop(0)
        elif path in self.forever:
            answer = self.forever[path]
        if isinstance(answer, Exception):
            raise answer
        if answer is not None:
            return answer(body) if callable(answer) else answer
        return self._default(path, body, headers or {})

    def _find(self, body):
        if body.get("payment_id"):
            return self.records.get(body["payment_id"])
        return next((r for r in self.records.values()
                     if r["order_id"] == body.get("order_id")), None)

    def _default(self, path, body, headers):
        if path == "/v1/payment-app":
            return ok([])
        if path == "/v1/payments":
            record = self.add(uuid.uuid4().hex, body["order_id"], body["amount"],
                              test=(headers.get("GoPay-Api-Key") == API_KEY))
            return ok(dict(record))
        record = self._find(body)
        if record is None:
            return fail("4041", "Payment not found")
        if path == "/v1/payments/cancel":
            if record["status"] in ("CREATED", "PENDING"):
                record["status"] = "CANCELLED"
            elif record["status"] == "COMMITTED":
                return fail("0013", "COMMITTED")
        return ok(dict(record))

    def paths(self):
        return [c.path for c in self.calls]

    def count(self, path):
        return self.paths().count(path)

    def bodies(self, path):
        return [c.body for c in self.calls if c.path == path]


@override_settings(**FLOW_SETTINGS)
class FlowCase(TestCase):
    """Общее: чистый кэш, «банк», покупатели, фабрика счёта и подписанный вебхук."""

    def setUp(self):
        cache.clear()
        self.addCleanup(cache.clear)
        self.bank = Bank()
        self._start(patch("payments.gopay.client.requests.post", side_effect=self.bank))
        # Задачи по умолчанию не выполняются: тест видит, что и с какой задержкой
        # поставлено. Кому нужно выполнение — зовёт задачу сам.
        self.check_task = self._start(patch("payments.tasks.check_gopay_invoice.apply_async"))
        self.cancel_task = self._start(patch("payments.tasks.cancel_gopay_invoice.delay"))
        users = get_user_model().objects
        self.user = users.create_user(email="buyer@example.com", password="x-pass-123")
        self.staff = users.create_user(email="staff@example.com", password="x-pass-123",
                                       is_staff=True)
        self.other = users.create_user(email="other@example.com", password="x-pass-123")
        self.pkg = TokenPackage.objects.create(name="Про", tokens=500, price=Decimal("490"))
        self.client = APIClient()
        self.client.force_authenticate(self.user)
        self.staff_client = APIClient()
        self.staff_client.force_authenticate(self.staff)
        self.http = APIClient()         # без авторизации — для вебхука

    def _start(self, patcher):
        mock = patcher.start()
        self.addCleanup(patcher.stop)
        return mock

    def make_invoice(self, user=None, env="live", amount="490.00", order_id=None, pid=None,
                     status="created", expires_in=900, bank_status="CREATED", package=None,
                     discount=None, in_bank=True, **over):
        user = user or (self.staff if env == "test" else self.user)
        package = package or self.pkg
        order_id = order_id or f"tokpkg-{user.id}-{package.id}-{uuid.uuid4().hex[:10]}"
        pid = pid or uuid.uuid4().hex
        request = {
            "provider": "gopay", "pay_method": "elqr",
            "token_purchase": {"package_id": package.id, "tokens": int(package.tokens),
                               "bonus_tokens": int(package.bonus_tokens or 0)},
            "return_to": "/profile",
            "gopay": {"env": env, "lifetime": 900, "package_name": package.name},
        }
        if discount:
            request["exit_discount"] = discount
        payment = Payment.objects.create(
            user=user, provider="gopay", amount=Decimal(amount), currency="KGS",
            order_id=order_id, description=f"Token package purchase #{package.id} (qr)",
            is_test=(env == "test"), request=request, response={})
        fields = dict(
            payment=payment, env=env, provider_payment_id=pid, status=status,
            amount=payment.amount, lifetime_seconds=900, qr_data=QR_DATA,
            qr_url=f"https://pay.gopay.kg/p/{pid}/qr/",
            checkout_url=f"https://pay.gopay.kg/p/{pid}/",
            app_links={"mbank": "mbank://elqr?data=abc"},
            expires_at=timezone.now() + timedelta(seconds=expires_in))
        fields.update(over)
        invoice = GoPayInvoice.objects.create(**fields)
        if in_bank:
            self.bank.add(pid, order_id, amount, bank_status, test=(env == "test"))
        return invoice

    def reload(self, invoice):
        return GoPayInvoice.objects.select_related("payment").get(pk=invoice.pk)

    def balance(self, user=None):
        user = user or self.user
        user.refresh_from_db()
        return int(user.token_balance or 0)

    def ledger(self, user=None):
        return TokenTransaction.objects.filter(user=user or self.user, reason="purchase").count()

    def checks_enqueued(self):
        """[(номер счёта, задержка)] — какие перепроверки поставлены."""
        return [(c.args[0][0], c.kwargs.get("countdown", 0))
                for c in self.check_task.call_args_list]

    # --- вебхук ---------------------------------------------------------------

    def event_body(self, event, invoice, status, *, created_at="2026-10-06T10:01:05Z", **data):
        payload = {
            "payment_id": invoice.provider_payment_id, "order_id": invoice.payment.order_id,
            "status": status, "amount": format(invoice.payment.amount, ".2f"),
            "created_at": "2026-10-06T10:00:00Z", "committed_at": None, "bank_op_date": None,
        }
        if invoice.env == "test":
            payload["testing_mode"] = True
        payload.update(data)
        payload = {k: v for k, v in payload.items() if v is not ...}
        return serialize({"event": event, "data": payload, "created_at": created_at})

    def post_hook(self, raw, *, secret=LIVE_WEBHOOK_SECRET, nonce=None, signature=None,
                  path=WEBHOOK_PATH, content_type="application/json", **extra):
        nonce = nonce or uuid.uuid4().hex
        signature = signature if signature is not None else sign(secret, nonce, raw)
        return self.http.generic("POST", path, raw, content_type=content_type,
                                 HTTP_GOPAY_NONCE=nonce, HTTP_GOPAY_SIGNATURE=signature,
                                 **extra)

    def hook(self, event, invoice, status, *, secret=None, **data):
        secret = secret or (WEBHOOK_SECRET if invoice.env == "test" else LIVE_WEBHOOK_SECRET)
        return self.post_hook(self.event_body(event, invoice, status, **data), secret=secret)

    def journal(self):
        return list(GoPayWebhookEvent.objects.order_by("id"))


# ================================================== состояние счёта ===

class StatusEndpointTests(FlowCase):
    def url(self, invoice):
        return f"/api/plans/purchase/qr/{invoice.payment.order_id}/"

    def test_owner_gets_the_contract(self):
        invoice = self.make_invoice(last_checked_at=timezone.now())
        r = self.client.get(self.url(invoice))
        self.assertEqual(r.status_code, 200)
        self.assertEqual(set(r.data), {
            "kind", "provider", "resumed", "order_id", "status", "ui_state", "amount",
            "currency", "original_amount", "discount_percent", "package", "credits", "qr",
            "apps", "checkout_url", "created_at", "expires_at", "server_time", "seconds_left",
            "lifetime_seconds", "is_test", "can_cancel", "return_to"})
        self.assertEqual((r.data["kind"], r.data["provider"], r.data["ui_state"]),
                         ("qr", "gopay", "awaiting_payment"))
        self.assertEqual(r.data["order_id"], invoice.payment.order_id)
        self.assertEqual(r.data["qr"]["data"], QR_DATA)
        self.assertNotIn("redirect_url", r.data)
        self.assertEqual(reverse("token-purchase-qr-status", args=["o-1"]),
                         "/api/plans/purchase/qr/o-1/")
        # Свежий счёт у GoPay не перепроверяем.
        self.assertEqual(self.checks_enqueued(), [])
        self.assertEqual(self.bank.calls, [])

    def test_foreign_and_unknown_orders_are_hidden(self):
        invoice = self.make_invoice(user=self.other)
        for url in (self.url(invoice), "/api/plans/purchase/qr/tokpkg-0-0-nope/"):
            r = self.client.get(url)
            self.assertEqual(r.status_code, 404)
            self.assertEqual(r.data, {"detail": "not_found"})
        self.assertEqual(self.checks_enqueued(), [])

    def test_unauthenticated_is_refused(self):
        invoice = self.make_invoice()
        self.assertEqual(APIClient().get(self.url(invoice)).status_code, 401)
        self.assertEqual(APIClient().post(self.url(invoice) + "cancel/").status_code, 401)

    def test_stale_open_invoice_enqueues_one_check_per_cooldown(self):
        invoice = self.make_invoice(last_checked_at=timezone.now() - timedelta(seconds=6))
        self.assertEqual(self.client.get(self.url(invoice)).status_code, 200)
        self.assertEqual(self.checks_enqueued(), [(invoice.id, 0)])
        # Второй опрос внутри тех же пяти секунд ничего не ставит.
        self.client.get(self.url(invoice))
        self.client.get(self.url(invoice))
        self.assertEqual(len(self.checks_enqueued()), 1)
        # Сам запрос состояния к GoPay не ходит никогда.
        self.assertEqual(self.bank.calls, [])
        # Счёт, который ещё ни разу не проверяли, — тоже «устарел».
        fresh = self.make_invoice(package=TokenPackage.objects.create(
            name="B", tokens=100, price=Decimal("100")))
        self.client.get(self.url(fresh))
        self.assertEqual(len(self.checks_enqueued()), 2)

    def test_nothing_is_enqueued_while_the_breaker_is_set(self):
        invoice = self.make_invoice(last_checked_at=None)
        cache.set("gopay:down:live", 1, 45)
        self.assertTrue(service.provider_down("live"))
        self.assertEqual(self.client.get(self.url(invoice)).status_code, 200)
        self.assertEqual(self.checks_enqueued(), [])

    def test_paid_order_makes_no_gopay_call(self):
        invoice = self.make_invoice(status="committed", last_checked_at=None)
        Payment.objects.filter(pk=invoice.payment_id).update(success=True)
        r = self.client.get(self.url(invoice))
        self.assertEqual(r.data["ui_state"], "paid")
        self.assertEqual(r.data["credits"], {"total": 500, "credited": 500})
        self.assertEqual(r.data["qr"], {"data": "", "image_url": ""})
        self.assertEqual(self.checks_enqueued(), [])
        self.assertEqual(self.bank.calls, [])

    def test_check_that_finds_the_payment_flips_the_answer_to_paid(self):
        # Так это выглядит, когда очередь выполняет задачу сразу: перепроверка
        # находит оплату, и тот же ответ уже говорит «оплачено».
        invoice = self.make_invoice(last_checked_at=None)
        self.bank.pay(invoice)
        self.check_task.side_effect = lambda args, countdown=0: tasks.check_gopay_invoice(*args)
        r = self.client.get(self.url(invoice))
        self.assertEqual(r.data["ui_state"], "paid")
        self.assertEqual(r.data["status"], "committed")
        self.assertEqual(r.data["credits"]["credited"], 500)
        self.assertEqual((self.balance(), self.ledger()), (500, 1))
        # Следующие опросы ничего не добавляют.
        self.client.get(self.url(invoice))
        self.assertEqual((self.balance(), self.ledger()), (500, 1))
        self.assertEqual(self.bank.count("/v1/payments/query"), 1)

    def test_abandoned_open_invoice_is_shown_as_cancelled(self):
        invoice = self.make_invoice(last_checked_at=timezone.now())
        self.assertTrue(service.mark_abandoned(invoice, "user"))
        r = self.client.get(self.url(invoice))
        self.assertEqual((r.data["status"], r.data["ui_state"]), ("created", "cancelled"))
        self.assertEqual(r.data["qr"], {"data": "", "image_url": ""})
        self.assertEqual((r.data["apps"], r.data["checkout_url"], r.data["can_cancel"]),
                         ([], "", False))

    def test_closed_invoice_is_rechecked_slowly_for_a_while(self):
        # Банк мог провести оплату в последнюю секунду: закрытый счёт ещё спрашиваем,
        # но раз в полминуты и только пока не вышла отсрочка.
        invoice = self.make_invoice(status="expired", expires_in=-60,
                                    last_checked_at=timezone.now() - timedelta(seconds=10))
        self.client.get(self.url(invoice))
        self.assertEqual(self.checks_enqueued(), [])
        GoPayInvoice.objects.filter(pk=invoice.pk).update(
            last_checked_at=timezone.now() - timedelta(seconds=31))
        self.client.get(self.url(invoice))
        self.assertEqual(self.checks_enqueued(), [(invoice.id, 0)])
        # Отсрочка вышла — больше не спрашиваем (дальше дело сверки).
        old = self.make_invoice(status="expired", expires_in=-3600, last_checked_at=None,
                                package=TokenPackage.objects.create(
                                    name="C", tokens=100, price=Decimal("100")))
        self.client.get(self.url(old))
        self.assertEqual(len(self.checks_enqueued()), 1)

    def test_processing_invoice_is_rechecked(self):
        invoice = self.make_invoice(status="committed",
                                    last_checked_at=timezone.now() - timedelta(seconds=16))
        r = self.client.get(self.url(invoice))
        self.assertEqual(r.data["ui_state"], "processing")
        self.assertEqual(self.checks_enqueued(), [(invoice.id, 0)])

    def test_queue_failure_does_not_break_the_answer(self):
        invoice = self.make_invoice(last_checked_at=None)
        self.check_task.side_effect = RuntimeError("очередь недоступна")
        self.assertEqual(self.client.get(self.url(invoice)).status_code, 200)


# ====================================================== отказ от QR ===

class CancelEndpointTests(FlowCase):
    def cancel(self, invoice, client=None, **body):
        with self.captureOnCommitCallbacks(execute=True):
            return (client or self.client).post(
                f"/api/plans/purchase/qr/{invoice.payment.order_id}/cancel/", body, format="json")

    def offer_on(self, invoice):
        now = timezone.now()
        return ExitDiscountOffer.objects.create(
            user=invoice.payment.user, shown_at=now, claimed_at=now, percent=20,
            expires_at=now + timedelta(hours=2), applied_to_payment=invoice.payment)

    def discount_free(self, offer):
        from plans.views import _offer_free_for_new_payment

        offer = ExitDiscountOffer.objects.select_related("applied_to_payment").get(pk=offer.pk)
        return _offer_free_for_new_payment(offer)

    def test_cancelled_releases_the_buyer_and_the_discount(self):
        invoice = self.make_invoice(amount="392.00")
        offer = self.offer_on(invoice)
        self.assertFalse(self.discount_free(offer))
        cache.set(f"gopay:create:{self.user.id}:{self.pkg.id}", "1", 90)

        r = self.cancel(invoice)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(set(r.data), {"result", "released", "invoice"})
        self.assertEqual((r.data["result"], r.data["released"]), ("cancelled", True))
        self.assertEqual(r.data["invoice"]["ui_state"], "cancelled")
        self.assertEqual(r.data["invoice"]["qr"]["data"], "")
        invoice = self.reload(invoice)
        self.assertEqual(invoice.status, "cancelled")
        self.assertIsNotNone(invoice.cancel_requested_at)
        self.assertEqual(invoice.flags.get("cancel_reason"), "user")
        self.assertTrue(self.discount_free(offer))
        # Замок «идёт создание» снят: следующий клик получит новый QR.
        self.assertIsNone(cache.get(f"gopay:create:{self.user.id}:{self.pkg.id}"))
        self.cancel_task.assert_not_called()
        self.assertEqual(reverse("token-purchase-qr-cancel", args=["o-1"]),
                         "/api/plans/purchase/qr/o-1/cancel/")

    def test_refused_cancel_of_a_paid_invoice_credits_it(self):
        invoice = self.make_invoice()
        self.bank.pay(invoice)            # отмена ответит 0013, запрос статуса — COMMITTED
        r = self.cancel(invoice)
        self.assertEqual((r.data["result"], r.data["released"]), ("committed", False))
        self.assertEqual(r.data["invoice"]["ui_state"], "paid")
        self.assertEqual((self.balance(), self.ledger()), (500, 1))
        self.assertEqual(self.bank.paths(), ["/v1/payments/cancel", "/v1/payments/query"])

    def test_busy_keeps_the_buyer_then_abandon_releases(self):
        invoice = self.make_invoice(amount="392.00")
        offer = self.offer_on(invoice)
        # 0013 и счёт всё ещё открыт: банк прямо сейчас проводит оплату.
        self.bank.always("/v1/payments/cancel", fail("0013", "bank is processing"))

        r = self.cancel(invoice)
        self.assertEqual((r.data["result"], r.data["released"]), ("busy", False))
        self.assertEqual(r.data["invoice"]["ui_state"], "awaiting_payment")
        invoice = self.reload(invoice)
        self.assertIsNone(invoice.cancel_requested_at)
        self.assertNotIn("abandoned", invoice.flags)
        self.assertFalse(self.discount_free(offer))
        # Скоро посмотрим ещё раз — с задержкой, а не сразу.
        self.assertEqual(self.checks_enqueued(), [(invoice.id, 10)])
        self.cancel_task.assert_not_called()

        # «Всё равно уйти»: второй запрос отпускает.
        for junk in ("true", 1, "yes"):
            self.assertFalse(self.cancel(invoice, abandon=junk).data["released"])
        r = self.cancel(invoice, abandon=True)
        self.assertEqual((r.data["result"], r.data["released"]), ("busy", True))
        self.assertEqual(r.data["invoice"]["ui_state"], "cancelled")
        invoice = self.reload(invoice)
        self.assertIsNotNone(invoice.cancel_requested_at)
        self.assertEqual(invoice.flags["abandoned"], "user")
        self.assertEqual(invoice.status, "created")       # у GoPay он всё ещё открыт
        self.assertTrue(self.discount_free(offer))
        self.cancel_task.assert_called_once_with(invoice.id, "user")

    def test_missing_cancel_endpoint_releases_at_once(self):
        # У GoPay нет метода отмены (HTML 404): на оплату ничто не указывает —
        # покупателя не держим у QR четверть часа.
        invoice = self.make_invoice(amount="392.00")
        offer = self.offer_on(invoice)
        self.bank.always("/v1/payments/cancel", html(404))
        r = self.cancel(invoice)
        self.assertEqual((r.data["result"], r.data["released"]), ("retry", True))
        invoice = self.reload(invoice)
        self.assertEqual(invoice.flags["abandoned"], "user")
        self.assertTrue(self.discount_free(offer))
        self.cancel_task.assert_called_once_with(invoice.id, "user")
        # Оставленный QR не возвращается в «незавершённую оплату».
        self.assertIsNone(self.client.get("/api/plans/purchase/pending/").data["pending"])

    def test_bank_unavailable_and_network_error_release_too(self):
        for answer in (fail("0015", "bank unavailable"), NETWORK_DOWN):
            with self.subTest(answer=type(answer).__name__):
                cache.clear()
                invoice = self.make_invoice(package=TokenPackage.objects.create(
                    name=uuid.uuid4().hex[:6], tokens=100, price=Decimal("100")))
                self.bank.forever["/v1/payments/cancel"] = answer
                r = self.cancel(invoice)
                self.assertEqual((r.data["result"], r.data["released"]), ("retry", True))
                self.assertEqual(self.reload(invoice).flags["abandoned"], "user")

    def test_breaker_skips_the_call_and_releases(self):
        invoice = self.make_invoice()
        cache.set("gopay:down:live", 1, 45)
        r = self.cancel(invoice)
        self.assertEqual((r.data["result"], r.data["released"]), ("retry", True))
        self.assertEqual(self.bank.calls, [])
        self.assertEqual(self.reload(invoice).flags["abandoned"], "user")

    def test_already_closed_invoice_is_released_without_a_call(self):
        invoice = self.make_invoice(status="expired", expires_in=-60)
        r = self.cancel(invoice)
        self.assertEqual((r.data["result"], r.data["released"]), ("not_open", True))
        self.assertEqual(self.bank.calls, [])

    def test_foreign_order_is_hidden(self):
        invoice = self.make_invoice(user=self.other)
        r = self.cancel(invoice)
        self.assertEqual(r.status_code, 404)
        self.assertEqual(self.reload(invoice).status, "created")
        self.assertEqual(self.bank.calls, [])


# =========================================================== вебхук ===

class WebhookTests(FlowCase):
    def v4_invoice(self, **over):
        """Тестовый счёт сотрудника — ровно тот, о котором эталонное тело V4."""
        return self.make_invoice(env="test", amount="100.00", order_id=ORDER, pid=PID, **over)

    def post_v4(self, **over):
        return self.post_hook(V4_RAW, nonce=V4_NONCE, signature=V4_SIG, **over)

    def assert_untouched(self, invoice):
        invoice = self.reload(invoice)
        self.assertEqual(invoice.status, "created")
        self.assertFalse(invoice.payment.success)
        self.assertIsNone(invoice.last_webhook_at)
        self.assertEqual(invoice.flags, {})
        self.assertEqual((self.balance(invoice.payment.user), self.ledger(invoice.payment.user)),
                         (0, 0))

    # --- «оплачено»: зачисляет ответ на НАШ запрос ----------------------------

    def test_signed_committed_is_confirmed_by_our_query_and_credited_once(self):
        invoice = self.v4_invoice()
        self.bank.pay(invoice)
        r = self.post_v4()
        self.assertEqual((r.status_code, r.json()), (200, {"status": "ok"}))
        invoice = self.reload(invoice)
        self.assertEqual(invoice.status, "committed")
        self.assertTrue(invoice.payment.success)
        self.assertTrue(invoice.payment.is_test)
        self.assertIsNotNone(invoice.last_webhook_at)
        self.assertEqual((self.balance(self.staff), self.ledger(self.staff)), (500, 1))
        # Ровно один запрос к GoPay — подтверждающий, по нашему номеру платежа.
        self.assertEqual(self.bank.paths(), ["/v1/payments/query"])
        self.assertEqual(self.bank.calls[0].body, {"payment_id": PID})
        self.assertEqual(self.bank.calls[0].headers["GoPay-Api-Key"], API_KEY)
        (row,) = self.journal()
        self.assertEqual((row.event, row.result, row.processed), ("payment.committed", "credited", True))
        self.assertEqual((row.order_id, row.provider_payment_id, row.status, row.amount,
                          row.testing_mode), (ORDER, PID, "COMMITTED", Decimal("100.00"), True))
        self.assertEqual(invoice.payment.response["callbacks"][-1]["type"], "gopay_webhook")
        self.assertEqual(self.checks_enqueued(), [])

    def test_forged_committed_while_gopay_says_created_credits_nothing(self):
        # Секрет вебхуков утёк, событие подписано верно — но GoPay на наш
        # запрос отвечает «ждёт оплату».
        invoice = self.v4_invoice()
        r = self.post_v4()
        self.assertEqual((r.status_code, r.json()), (200, {"status": "ok"}))
        self.assertEqual((self.balance(self.staff), self.ledger(self.staff)), (0, 0))
        invoice = self.reload(invoice)
        self.assertEqual(invoice.status, "created")
        self.assertFalse(invoice.payment.success)
        (row,) = self.journal()
        self.assertEqual((row.result, row.processed), ("query_pending", False))
        self.assertEqual(self.checks_enqueued(), [(invoice.id, 10)])
        self.assertEqual(self.bank.paths(), ["/v1/payments/query"])

    def test_failed_confirmation_answers_503_and_a_redelivery_is_processed(self):
        # Решение ведущего R1: подпись верна, а спросить GoPay не удалось —
        # 503, чтобы событие доставили снова; в этом запросе не зачисляем ничего.
        invoice = self.v4_invoice()
        self.bank.pay(invoice)
        self.bank.script("/v1/payments/query", NETWORK_DOWN)
        r = self.post_v4()
        self.assertEqual(r.status_code, 503)
        self.assertEqual(r.json(), {"status": "retry_later"})
        self.assertEqual((self.balance(self.staff), self.ledger(self.staff)), (0, 0))
        self.assertEqual(self.reload(invoice).status, "created")
        (row,) = self.journal()
        self.assertEqual((row.result, row.processed), ("query_failed:network", False))
        self.assertEqual(self.checks_enqueued(), [(invoice.id, 15)])

        # То же событие доставлено ещё раз, GoPay уже отвечает.
        r = self.post_v4()
        self.assertEqual(r.status_code, 200)
        self.assertEqual((self.balance(self.staff), self.ledger(self.staff)), (500, 1))
        (row,) = self.journal()
        self.assertEqual((row.result, row.processed), ("credited", True))

    def test_provider_refusal_of_the_confirmation_is_503_too(self):
        self.bank.pay(self.v4_invoice())
        for answer, code in ((fail("4001", "Invalid signature"), "auth"),
                             (FakeResponse(500, None, text="oops"), "http_500"),
                             (fail("4041", "Payment not found"), "not_found")):
            with self.subTest(code=code):
                GoPayWebhookEvent.objects.all().delete()
                self.bank.script("/v1/payments/query", answer)
                r = self.post_v4()
                self.assertEqual(r.status_code, 503)
                (row,) = self.journal()
                self.assertEqual((row.result, row.processed), (f"query_failed:{code}", False))
        self.assertEqual((self.balance(self.staff), self.ledger(self.staff)), (0, 0))

    def test_missing_keys_for_the_confirmation_are_503(self):
        invoice = self.v4_invoice()
        self.bank.pay(invoice)
        with override_settings(GOPAY_TEST_API_SECRET=""):
            r = self.post_v4()
        self.assertEqual(r.status_code, 503)
        self.assertEqual(self.journal()[0].result, "query_failed:not_configured")
        self.assertEqual(self.bank.calls, [])
        self.assert_untouched(invoice)

    def test_already_paid_order_needs_no_query(self):
        invoice = self.v4_invoice()
        self.bank.pay(invoice)
        self.assertEqual(service.refresh_invoice(invoice, source="reconcile"), "credited")
        calls = len(self.bank.calls)
        r = self.post_v4()
        self.assertEqual(r.status_code, 200)
        self.assertEqual(self.journal()[0].result, "already")
        self.assertEqual(len(self.bank.calls), calls)
        self.assertEqual((self.balance(self.staff), self.ledger(self.staff)), (500, 1))

    def test_exact_replay_is_a_duplicate_without_a_query(self):
        invoice = self.v4_invoice()
        self.bank.pay(invoice)
        self.post_v4()
        r = self.post_v4()
        self.assertEqual((r.status_code, r.json()), (200, {"status": "duplicate"}))
        self.assertEqual(self.bank.count("/v1/payments/query"), 1)
        self.assertEqual(len(self.journal()), 1)
        self.assertEqual((self.balance(self.staff), self.ledger(self.staff)), (500, 1))

    def test_same_event_with_a_new_envelope_time_is_already(self):
        invoice = self.v4_invoice()
        self.bank.pay(invoice)
        self.post_v4()
        raw = V4_RAW.replace(b'"created_at":"2026-09-03T04:00:20Z"}', b'"created_at":"2026-09-03T04:05:00Z"}')
        self.assertNotEqual(raw, V4_RAW)
        r = self.post_hook(raw, secret=WEBHOOK_SECRET)
        self.assertEqual(r.status_code, 200)
        self.assertEqual([row.result for row in self.journal()], ["credited", "already"])
        self.assertEqual(self.bank.count("/v1/payments/query"), 1)
        self.assertEqual((self.balance(self.staff), self.ledger(self.staff)), (500, 1))

    def test_query_showing_another_amount_is_not_credited(self):
        # В теле сумма верная, а на наш запрос GoPay показывает другую.
        invoice = self.v4_invoice()
        self.bank.pay(invoice, amount="1.00")
        r = self.post_v4()
        self.assertEqual(r.status_code, 200)
        invoice = self.reload(invoice)
        self.assertEqual(invoice.status, "committed")          # оплачен и на разборе
        self.assertEqual(invoice.flags["needs_review"], "mismatch:amount")
        self.assertFalse(invoice.payment.success)
        self.assertEqual(invoice.payment.error, "amount_mismatch")
        self.assertEqual((self.balance(self.staff), self.ledger(self.staff)), (0, 0))
        self.assertEqual(self.journal()[0].result, "mismatch")
        self.assertEqual(service.ui_state(invoice), "processing")
        self.assertEqual(EventLog.objects.filter(level="error", meta__needs_review=True).count(), 1)

    def test_committed_event_with_another_status_in_the_body(self):
        invoice = self.v4_invoice()
        self.bank.pay(invoice)
        r = self.hook("payment.committed", invoice, "EXPIRED")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(self.bank.calls, [])
        self.assertEqual((self.journal()[0].result, self.journal()[0].processed),
                         ("event_status_mismatch", True))
        self.assertEqual(self.checks_enqueued(), [(invoice.id, 0)])
        self.assert_untouched(invoice)

    def test_event_signed_with_the_other_envs_secret(self):
        invoice = self.v4_invoice()
        self.bank.pay(invoice)
        r = self.hook("payment.committed", invoice, "COMMITTED", secret=LIVE_WEBHOOK_SECRET)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(self.bank.calls, [])
        self.assertEqual(self.journal()[0].result, "secret_env_mismatch")
        self.assertEqual(self.checks_enqueued(), [(invoice.id, 0)])
        self.assert_untouched(invoice)
        # И закрыть счёт чужим секретом тоже нельзя.
        self.hook("payment.expired", invoice, "EXPIRED", secret=LIVE_WEBHOOK_SECRET)
        self.assert_untouched(invoice)

    @override_settings(GOPAY_LIVE_WEBHOOK_SECRET=WEBHOOK_SECRET)
    def test_one_secret_for_both_envs_is_accepted(self):
        invoice = self.v4_invoice()
        self.bank.pay(invoice)
        self.assertEqual(self.post_v4().status_code, 200)
        self.assertEqual(self.journal()[0].result, "credited")
        self.assertEqual((self.balance(self.staff), self.ledger(self.staff)), (500, 1))

    def test_committed_after_local_expiry_is_credited_late(self):
        invoice = self.make_invoice(expires_in=-3600)
        self.assertTrue(service.mark_expired_locally(invoice))
        self.assertEqual(self.reload(invoice).flags, {"local_expiry": True})
        self.bank.pay(invoice)
        self.assertEqual(self.hook("payment.committed", invoice, "COMMITTED").status_code, 200)
        invoice = self.reload(invoice)
        self.assertEqual((invoice.status, invoice.payment.success), ("committed", True))
        self.assertTrue(invoice.flags["late_commit"])
        self.assertNotIn("local_expiry", invoice.flags)
        self.assertEqual((self.balance(), self.ledger()), (500, 1))

    # --- подпись ---------------------------------------------------------------

    def test_bad_signatures_change_nothing(self):
        invoice = self.v4_invoice()
        self.bank.pay(invoice)
        tampered = V4_RAW.replace(b'"100.00"', b'"100.01"')
        attempts = {
            "чужой секрет": lambda: self.post_hook(V4_RAW, secret="dummy-wrong-secret-not-real"),
            "тело изменено": lambda: self.post_hook(tampered, nonce=V4_NONCE, signature=V4_SIG),
            "другая строка nonce": lambda: self.post_hook(V4_RAW, nonce="0" * 32, signature=V4_SIG),
            "подпись не hex": lambda: self.post_hook(V4_RAW, nonce=V4_NONCE, signature="z" * 128),
            "пустая подпись": lambda: self.post_hook(V4_RAW, nonce=V4_NONCE, signature=""),
            "нет заголовков": lambda: self.http.generic("POST", WEBHOOK_PATH, V4_RAW,
                                                        content_type="application/json"),
        }
        for name, attempt in attempts.items():
            with self.subTest(case=name):
                r = attempt()
                self.assertEqual(r.status_code, 400)
                self.assertEqual(r.json(), {"status": "invalid_signature"})
        self.assertEqual(self.journal(), [])
        self.assertEqual(self.bank.calls, [])
        self.assertEqual(self.checks_enqueued(), [])
        self.assert_untouched(invoice)

    @override_settings(GOPAY_TEST_WEBHOOK_SECRET="", GOPAY_LIVE_WEBHOOK_SECRET="")
    def test_no_secret_configured_accepts_nothing(self):
        invoice = self.v4_invoice()
        self.assertEqual(self.post_v4().status_code, 400)
        # Подпись «пустым секретом» тоже не проходит.
        self.assertEqual(self.post_hook(V4_RAW, secret="").status_code, 400)
        self.assertEqual(self.journal(), [])
        self.assert_untouched(invoice)

    def test_oversized_body_is_refused(self):
        raw = b'{"event":"test.ping","pad":"' + b"x" * (64 * 1024) + b'"}'
        r = self.post_hook(raw)
        self.assertEqual((r.status_code, r.json()), (400, {"status": "too_large"}))

    # --- что принимаем молча ----------------------------------------------------

    def test_ping_and_foreign_event_types_leave_no_trace(self):
        for body in ({"event": "test.ping", "created_at": "2026-10-06T10:00:00Z"},
                     {"event": "test.ping", "data": {"message": "ok"}},
                     {"event": "subscription.created", "data": {"id": "s1"}},
                     {"event": "static_qr.paid", "data": {"payment_id": PID}},
                     {"event": "payment.committed", "data": "строка вместо объекта"}):
            with self.subTest(event=body["event"]):
                r = self.post_hook(serialize(body))
                self.assertEqual((r.status_code, r.json()), (200, {"status": "ok"}))
        for raw in (b"not json at all", b'["list"]', b"\xff\xfe"):
            r = self.post_hook(raw)
            self.assertEqual((r.status_code, r.json()), (200, {"status": "ignored"}))
        self.assertEqual(self.journal(), [])
        self.assertEqual(self.bank.calls, [])

    def test_unknown_order_is_acknowledged_and_processed_once_it_exists(self):
        # Событие про заказ, которого у нас нет (другая интеграция той же точки).
        r = self.post_v4()
        self.assertEqual((r.status_code, r.json()), (200, {"status": "ok"}))
        (row,) = self.journal()
        self.assertEqual((row.result, row.processed), ("unknown_order", False))
        self.assertEqual(self.bank.calls, [])
        # Заказ появился — повторная доставка того же события обрабатывается.
        invoice = self.v4_invoice()
        self.bank.pay(invoice)
        self.assertEqual(self.post_v4().status_code, 200)
        (row,) = self.journal()
        self.assertEqual((row.result, row.processed), ("credited", True))
        self.assertEqual(self.ledger(self.staff), 1)

    def test_other_payment_events_are_journaled_and_ignored(self):
        invoice = self.make_invoice()
        r = self.hook("payment.created", invoice, "CREATED")
        self.assertEqual(r.status_code, 200)
        self.assertEqual((self.journal()[0].result, self.journal()[0].processed),
                         ("ignored_event", True))
        self.assertEqual(self.reload(invoice).status, "created")

    # --- закрывающие события -----------------------------------------------------

    def test_closing_events_close_an_open_invoice_from_the_body(self):
        for event, status in (("payment.expired", "EXPIRED"), ("payment.cancelled", "CANCELLED"),
                              ("payment.failed", "FAILED")):
            with self.subTest(event=event):
                invoice = self.make_invoice(package=TokenPackage.objects.create(
                    name=status, tokens=100, price=Decimal("100")), amount="100.00")
                r = self.hook(event, invoice, status)
                self.assertEqual(r.status_code, 200)
                invoice = self.reload(invoice)
                self.assertEqual(invoice.status, status.lower())
                self.assertFalse(invoice.payment.success)
                self.assertEqual(invoice.payment.error, f"gopay_status:{status.lower()}")
                self.assertIsNotNone(invoice.last_webhook_at)
        self.assertEqual([row.result for row in self.journal()], ["closed"] * 3)
        # Закрытие — из подписанного тела, без запроса к GoPay.
        self.assertEqual(self.bank.calls, [])
        self.assertEqual((self.balance(), self.ledger()), (0, 0))

    def test_closing_event_without_the_test_flag_does_not_close_a_test_invoice(self):
        invoice = self.v4_invoice()
        r = self.hook("payment.expired", invoice, "EXPIRED", testing_mode=...)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(self.journal()[0].result, "mismatch")
        invoice = self.reload(invoice)
        self.assertEqual(invoice.status, "created")
        self.assertEqual(invoice.flags["needs_review"], "mismatch:mode")

    def test_closing_event_after_credit_keeps_the_order_paid(self):
        invoice = self.make_invoice()
        self.bank.pay(invoice)
        self.assertEqual(service.refresh_invoice(invoice, source="reconcile"), "credited")
        r = self.hook("payment.expired", invoice, "EXPIRED")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(self.journal()[0].result, "ignored")
        invoice = self.reload(invoice)
        self.assertEqual((invoice.status, invoice.payment.success, invoice.payment.error),
                         ("committed", True, ""))
        self.assertEqual(invoice.flags["status_after_commit"], "EXPIRED")
        self.assertEqual((self.balance(), self.ledger()), (500, 1))

    def test_processing_error_is_journaled_and_rechecked(self):
        invoice = self.make_invoice()
        with patch("payments.gopay.views.gopay_service.apply_state",
                   side_effect=RuntimeError("сбой")):
            r = self.hook("payment.expired", invoice, "EXPIRED")
        self.assertEqual(r.status_code, 200)
        (row,) = self.journal()
        self.assertEqual((row.result, row.processed), ("error", False))
        self.assertEqual(self.checks_enqueued(), [(invoice.id, 0)])
        # Событие не обработано — повторная доставка закрывает счёт.
        self.hook("payment.expired", invoice, "EXPIRED")
        self.assertEqual(self.reload(invoice).status, "expired")
        self.assertEqual((self.journal()[0].result, self.journal()[0].processed), ("closed", True))

    # --- прочее ------------------------------------------------------------------

    def test_legacy_flat_body_only_triggers_a_check(self):
        invoice = self.make_invoice()
        raw = serialize({"payment_id": invoice.provider_payment_id,
                         "order_id": invoice.payment.order_id, "status": "COMMITTED",
                         "amount": "490.00"})
        r = self.post_hook(raw)
        self.assertEqual((r.status_code, r.json()), (200, {"status": "ok"}))
        self.assertEqual(self.checks_enqueued(), [(invoice.id, 0)])
        self.assertEqual(self.journal(), [])
        self.assertEqual(self.bank.calls, [])
        self.assert_untouched(invoice)
        # По одному номеру платежа счёт тоже находится.
        self.post_hook(serialize({"payment_id": invoice.provider_payment_id, "status": "EXPIRED"}))
        self.assertEqual(len(self.checks_enqueued()), 2)
        self.assertEqual(self.reload(invoice).status, "created")

    def test_receipt_event_stores_the_receipt_link(self):
        invoice = self.make_invoice()
        url = "https://receipt.example/r/abc"
        raw = self.event_body("receipt.sent", invoice, ..., receipt_url=url)
        self.assertEqual(self.post_hook(raw).status_code, 200)
        self.assertEqual(self.reload(invoice).receipt_url, url)
        (row,) = self.journal()
        self.assertEqual((row.result, row.processed), ("receipt_saved", True))
        self.assertEqual(row.payload["data"]["receipt_url"], url)
        # Не https — не сохраняем; уже сохранённую ссылку не затираем.
        for bad in ("http://receipt.example/r/x", "javascript:alert(1)", 12345):
            raw = self.event_body("receipt.sent", invoice, ..., receipt_url=bad,
                                  created_at=f"2026-10-06T11:00:0{len(str(bad)) % 10}Z")
            self.post_hook(raw)
        self.assertEqual(self.reload(invoice).receipt_url, url)
        self.assertEqual(self.reload(invoice).status, "created")
        self.assertEqual(self.bank.calls, [])

    def test_request_data_is_never_parsed(self):
        invoice = self.v4_invoice()
        self.bank.pay(invoice)
        for content_type in ("text/plain", "application/octet-stream"):
            r = self.post_v4(content_type=content_type)
            self.assertEqual(r.status_code, 200)
        self.assertEqual(self.ledger(self.staff), 1)

    def test_accept_header_does_not_matter(self):
        invoice = self.v4_invoice()
        self.bank.pay(invoice)
        r = self.post_v4(HTTP_ACCEPT="application/xml")
        self.assertEqual((r.status_code, r.json()), (200, {"status": "ok"}))

    def test_both_url_spellings_work(self):
        self.assertEqual(reverse("payments:gopay-webhook"), config.WEBHOOK_PATH)
        self.assertEqual(reverse("payments:gopay-webhook"), WEBHOOK_PATH)
        invoice = self.v4_invoice()
        self.bank.pay(invoice)
        r = self.post_v4(path=WEBHOOK_PATH.rstrip("/"))
        self.assertEqual((r.status_code, r.json()), (200, {"status": "ok"}))
        self.assertEqual(self.post_v4().json(), {"status": "duplicate"})
        self.assertEqual(self.ledger(self.staff), 1)
        self.assertEqual(self.http.get(WEBHOOK_PATH).status_code, 405)

    def test_fifty_deliveries_in_a_row_are_not_throttled(self):
        invoice = self.make_invoice()
        codes = set()
        for n in range(50):
            raw = self.event_body("payment.expired", invoice, "EXPIRED",
                                  created_at=f"2026-10-06T10:{n:02d}:00Z")
            codes.add(self.post_hook(raw).status_code)
        self.assertEqual(codes, {200})
        self.assertEqual(len(self.journal()), 50)

    def test_journal_keeps_only_whitelisted_fields(self):
        invoice = self.v4_invoice()
        self.bank.pay(invoice)
        raw = self.event_body("payment.committed", invoice, "COMMITTED",
                              buyer={"email": "someone@example.com", "phone": "+996555000111"},
                              card_mask="4169 **** 1234", qr_data=QR_DATA)
        nonce = "feedfacefeedfacefeedfacefeedface"
        signature = sign(WEBHOOK_SECRET, nonce, raw)
        self.assertEqual(self.post_hook(raw, nonce=nonce, signature=signature).status_code, 200)
        (row,) = self.journal()
        self.assertEqual(set(row.payload), {"event", "created_at", "data"})
        self.assertLessEqual(set(row.payload["data"]), {
            "payment_id", "order_id", "amount", "status", "testing_mode", "created_at",
            "expires_at", "committed_at", "bank_op_date"})
        dumped = json.dumps(row.payload) + json.dumps(self.reload(invoice).payment.response)
        for secret in (signature, nonce, WEBHOOK_SECRET, "someone@example.com", "4169"):
            self.assertNotIn(secret, dumped)


# ============================================================ задачи ===

class TaskTests(FlowCase):
    def test_check_task_applies_the_answer(self):
        invoice = self.make_invoice()
        self.assertEqual(tasks.check_gopay_invoice(invoice.id), "pending")
        self.bank.pay(invoice)
        self.assertEqual(tasks.check_gopay_invoice(invoice.id), "credited")
        self.assertEqual(tasks.check_gopay_invoice(invoice.id), "already")
        self.assertEqual((self.balance(), self.ledger()), (500, 1))
        self.assertEqual(tasks.check_gopay_invoice(10 ** 9), "missing")
        self.assertEqual(self.reload(invoice).payment.response["callbacks"][-1]["type"],
                         "gopay_query")

    def test_check_task_retries_once(self):
        invoice = self.make_invoice()
        self.bank.always("/v1/payments/query", NETWORK_DOWN)
        result = tasks.check_gopay_invoice.apply(args=(invoice.id,))
        self.assertTrue(result.failed())
        # Первая попытка и ровно один повтор.
        self.assertEqual(self.bank.count("/v1/payments/query"), 2)
        self.assertEqual(tasks.check_gopay_invoice.max_retries, 1)

    def test_check_task_is_skipped_under_the_breaker(self):
        invoice = self.make_invoice()
        cache.set("gopay:down:live", 1, 45)
        self.assertEqual(tasks.check_gopay_invoice(invoice.id), "skipped_down")
        self.assertEqual(self.bank.calls, [])

    def test_cancel_task(self):
        invoice = self.make_invoice()
        self.assertEqual(tasks.cancel_gopay_invoice(invoice.id, "superseded"), "cancelled")
        invoice = self.reload(invoice)
        self.assertEqual((invoice.status, invoice.flags["cancel_reason"]),
                         ("cancelled", "superseded"))
        self.assertEqual(tasks.cancel_gopay_invoice(invoice.id, "superseded"), "not_open")
        self.assertEqual(tasks.cancel_gopay_invoice(10 ** 9), "missing")

    def test_cancel_task_gives_up_quietly_after_its_retries(self):
        invoice = self.make_invoice()
        self.bank.always("/v1/payments/cancel", fail("0015", "bank unavailable"))
        result = tasks.cancel_gopay_invoice.apply(args=(invoice.id, "user"))
        # Не ошибка задачи: оставленный счёт добьёт сверка.
        self.assertFalse(result.failed())
        self.assertEqual(result.result, "retry")
        self.assertEqual(self.bank.count("/v1/payments/cancel"), 6)     # попытка + пять повторов

    def test_cancel_task_does_not_call_gopay_under_the_breaker(self):
        invoice = self.make_invoice()
        cache.set("gopay:down:live", 1, 45)
        result = tasks.cancel_gopay_invoice.apply(args=(invoice.id, "user"))
        self.assertEqual(result.result, "retry")
        self.assertEqual(self.bank.calls, [])

    def test_freedompay_reconcile_never_asks_about_gopay_orders(self):
        invoice = self.make_invoice()
        with patch("payments.tasks.fetch_payment_status", return_value={}) as fp_status:
            result = tasks.reconcile_pending_token_payments()
        self.assertEqual(result["checked"], 0)
        fp_status.assert_not_called()
        # А такой же свежий заказ FreedomPay — спрашивает.
        Payment.objects.create(user=self.user, amount=Decimal("490"), currency="KGS",
                               order_id=f"tokpkg-{self.user.id}-1-fp", request={}, response={})
        with patch("payments.tasks.fetch_payment_status", return_value={}) as fp_status:
            tasks.reconcile_pending_token_payments()
        fp_status.assert_called_once()
        self.assertEqual(self.reload(invoice).status, "created")


# ============================================================ сверка ===

class ReconcileTests(FlowCase):
    APPS_MARK = "gopay:apps:recon:live"

    def setUp(self):
        super().setUp()
        # Список банков сверка обновляет отдельно и редко (свой тест ниже) —
        # здесь он не должен мешать считать запросы по счетам.
        cache.set(self.APPS_MARK, 1, 600)

    def run_reconcile(self):
        return tasks.reconcile_gopay_invoices()

    def age(self, invoice, **fields):
        """Сдвинуть времена счёта в прошлое (auto_now_add не даёт задать их при создании)."""
        GoPayInvoice.objects.filter(pk=invoice.pk).update(**fields)
        return self.reload(invoice)

    def test_paid_invoice_is_credited_once(self):
        invoice = self.make_invoice()
        self.bank.pay(invoice)
        result = self.run_reconcile()
        self.assertEqual(result, {"status": "ok", "checked": 1, "credited": 1, "closed": 0,
                                  "skipped_env": []})
        invoice = self.reload(invoice)
        self.assertEqual((invoice.status, invoice.payment.success), ("committed", True))
        self.assertEqual(str(invoice.bank_op_date), "2026-10-06")
        self.assertEqual(invoice.payment.response["callbacks"][-1]["type"], "gopay_reconcile")
        self.assertEqual((self.balance(), self.ledger()), (500, 1))
        # Вебхук, пришедший после сверки, ничего не добавляет.
        self.assertEqual(self.hook("payment.committed", invoice, "COMMITTED").status_code, 200)
        self.assertEqual(GoPayWebhookEvent.objects.get().result, "already")
        self.assertEqual(self.run_reconcile()["credited"], 0)
        self.assertEqual((self.balance(), self.ledger()), (500, 1))

    def test_open_invoice_before_expiry_is_left_alone(self):
        invoice = self.make_invoice()
        self.assertEqual(self.run_reconcile()["checked"], 1)
        invoice = self.reload(invoice)
        self.assertEqual(invoice.status, "created")
        self.assertIsNotNone(invoice.last_checked_at)
        self.assertEqual(self.bank.paths(), ["/v1/payments/query"])
        # Только что проверенный счёт следующий проход не трогает (не чаще раза в 20 с).
        self.run_reconcile()
        self.assertEqual(self.bank.count("/v1/payments/query"), 1)

    def test_open_invoice_past_expiry_is_cancelled_at_gopay(self):
        fresh = self.make_invoice(expires_in=-60)            # срок вышел, но двух минут не прошло
        late = self.make_invoice(expires_in=-121, package=TokenPackage.objects.create(
            name="B", tokens=100, price=Decimal("100")))
        result = self.run_reconcile()
        self.assertEqual(self.reload(fresh).status, "created")
        late = self.reload(late)
        self.assertEqual(late.status, "cancelled")
        self.assertEqual(late.flags["cancel_reason"], "expired")
        self.assertEqual(self.bank.count("/v1/payments/cancel"), 1)
        self.assertEqual(result["closed"], 1)

    def test_abandoned_invoice_is_cancelled_on_every_pass(self):
        invoice = self.make_invoice()
        service.mark_abandoned(invoice, "superseded")
        self.bank.always("/v1/payments/cancel", fail("0015", "bank unavailable"))
        self.run_reconcile()
        self.assertEqual(self.bank.count("/v1/payments/cancel"), 1)
        self.assertEqual(self.reload(invoice).status, "created")
        # Следующий проход (через минуту) пробует снова — срок при этом не важен.
        self.age(invoice, last_checked_at=timezone.now() - timedelta(seconds=61))
        self.bank.forever.clear()
        self.run_reconcile()
        invoice = self.reload(invoice)
        self.assertEqual((invoice.status, invoice.flags["cancel_reason"]),
                         ("cancelled", "superseded"))

    def test_abandoned_invoice_paid_late_is_still_credited(self):
        invoice = self.make_invoice()
        service.mark_abandoned(invoice, "user")
        self.bank.pay(invoice)
        self.assertEqual(self.run_reconcile()["credited"], 1)
        invoice = self.reload(invoice)
        self.assertTrue(invoice.flags["late_commit"])
        self.assertEqual((self.balance(), self.ledger()), (500, 1))
        self.assertEqual(self.bank.count("/v1/payments/cancel"), 0)

    def test_failed_cancel_after_the_grace_expires_the_invoice_locally(self):
        invoice = self.make_invoice(expires_in=-700)         # отсрочка 10 минут вышла
        self.bank.always("/v1/payments/cancel", fail("0015", "bank unavailable"))
        self.run_reconcile()
        invoice = self.reload(invoice)
        self.assertEqual(invoice.status, "expired")
        self.assertIs(invoice.flags["local_expiry"], True)
        self.assertEqual(invoice.payment.error, "gopay_status:expired")
        # До отсрочки тот же отказ счёт не закрывает.
        early = self.make_invoice(expires_in=-300, package=TokenPackage.objects.create(
            name="B", tokens=100, price=Decimal("100")))
        self.run_reconcile()
        self.assertEqual(self.reload(early).status, "created")

    def test_unreachable_gopay_expires_overdue_invoices_without_a_call(self):
        invoice = self.make_invoice(expires_in=-700)
        self.bank.always("/v1/payments/query", NETWORK_DOWN)
        self.run_reconcile()
        invoice = self.reload(invoice)
        self.assertEqual((invoice.status, invoice.flags.get("local_expiry")), ("expired", True))
        self.assertEqual(self.bank.count("/v1/payments/cancel"), 0)

    def test_outage_then_committed_for_an_invoice_expired_seven_hours_ago(self):
        # GoPay не отвечал час, счёт закрыли своими часами семь часов назад —
        # а деньги по нему пришли. У таких счетов нет шестичасового предела.
        invoice = self.make_invoice(expires_in=-8 * 3600)
        self.assertTrue(service.mark_expired_locally(invoice))
        invoice = self.age(invoice, finalized_at=timezone.now() - timedelta(hours=7),
                           last_checked_at=timezone.now() - timedelta(hours=1))
        self.bank.always("/v1/payments/query", NETWORK_DOWN)
        self.assertEqual(self.run_reconcile()["credited"], 0)
        self.assertEqual(self.reload(invoice).status, "expired")

        cache.clear()                     # предохранитель и «здоровье» истекли
        self.bank.forever.clear()
        self.bank.pay(invoice)
        result = self.run_reconcile()
        self.assertEqual(result["credited"], 1)
        invoice = self.reload(invoice)
        self.assertEqual((invoice.status, invoice.payment.success, invoice.payment.error),
                         ("committed", True, ""))
        self.assertTrue(invoice.flags["late_commit"])
        self.assertNotIn("local_expiry", invoice.flags)
        self.assertEqual((self.balance(), self.ledger()), (500, 1))

    def test_locally_expired_invoice_still_open_at_gopay_is_cancelled(self):
        invoice = self.make_invoice(expires_in=-3600)
        service.mark_expired_locally(invoice)
        self.assertEqual(self.bank.of(invoice)["status"], "CREATED")
        self.run_reconcile()
        self.assertEqual(self.bank.paths(), ["/v1/payments/query", "/v1/payments/cancel"])
        invoice = self.reload(invoice)
        # Первый статус закрытия остаётся, но закрытие теперь подтверждено GoPay.
        self.assertEqual(invoice.status, "expired")
        self.assertNotIn("local_expiry", invoice.flags)
        self.assertEqual(self.bank.of(invoice)["status"], "CANCELLED")

    def test_unconfirmed_sweep_is_two_speed_and_lasts_a_week(self):
        invoice = self.make_invoice(expires_in=-3600)
        service.mark_expired_locally(invoice)
        self.bank.always("/v1/payments/cancel", fail("0015", "bank unavailable"))

        def queries_after(**fields):
            before = self.bank.count("/v1/payments/query")
            self.age(invoice, **fields)
            self.run_reconcile()
            return self.bank.count("/v1/payments/query") - before

        now = timezone.now()
        # Первые полчаса — раз в две минуты.
        self.assertEqual(queries_after(finalized_at=now, last_checked_at=now - timedelta(seconds=90)), 0)
        self.assertEqual(queries_after(finalized_at=now, last_checked_at=now - timedelta(seconds=130)), 1)
        # Потом — раз в полчаса.
        day = now - timedelta(days=1)
        self.assertEqual(queries_after(finalized_at=day, last_checked_at=now - timedelta(minutes=20)), 0)
        self.assertEqual(queries_after(finalized_at=day, last_checked_at=now - timedelta(minutes=31)), 1)
        # Неделя прошла — больше не спрашиваем.
        self.assertEqual(queries_after(finalized_at=now - timedelta(days=7, minutes=1),
                                       last_checked_at=now - timedelta(days=1)), 0)

    def test_not_found_counter_does_not_exclude_an_invoice(self):
        invoice = self.make_invoice(expires_in=-3600, in_bank=False)
        service.mark_expired_locally(invoice)
        self.run_reconcile()
        invoice = self.reload(invoice)
        first = invoice.flags["not_found"]["count"]
        self.assertGreaterEqual(first, 1)
        # Счёт не объявлен «несуществующим»: он закрыт по-прежнему только нашими
        # часами и остаётся в сверке.
        self.assertEqual((invoice.status, invoice.flags.get("local_expiry")), ("expired", True))
        self.age(invoice, last_checked_at=timezone.now() - timedelta(minutes=31))
        self.run_reconcile()
        self.assertGreater(self.reload(invoice).flags["not_found"]["count"], first)
        # GoPay «нашёл» платёж — и он оплачен.
        self.bank.add(invoice.provider_payment_id, invoice.payment.order_id, "490.00", "COMMITTED")
        self.age(invoice, last_checked_at=timezone.now() - timedelta(minutes=31))
        self.assertEqual(self.run_reconcile()["credited"], 1)
        self.assertNotIn("not_found", self.reload(invoice).flags)

    def test_late_sweep_credits_after_a_confirmed_close_for_six_hours(self):
        invoice = self.make_invoice(status="expired", expires_in=-3600,
                                    finalized_at=timezone.now() - timedelta(hours=5),
                                    last_checked_at=timezone.now() - timedelta(minutes=31))
        self.bank.pay(invoice)
        self.assertEqual(self.run_reconcile()["credited"], 1)
        self.assertTrue(self.reload(invoice).flags["late_commit"])
        self.assertEqual((self.balance(), self.ledger()), (500, 1))

        old = self.make_invoice(status="expired", expires_in=-8 * 3600, user=self.other,
                                finalized_at=timezone.now() - timedelta(hours=6, minutes=1),
                                last_checked_at=timezone.now() - timedelta(hours=5))
        self.bank.pay(old)
        calls = len(self.bank.calls)
        self.assertEqual(self.run_reconcile()["credited"], 0)
        self.assertEqual(len(self.bank.calls), calls)
        self.assertEqual(self.reload(old).status, "expired")

    def test_admin_refunded_rows_are_skipped_and_never_credited(self):
        refund = {"kind": "refund", "by_id": self.staff.id, "at": "2026-10-06T10:00:00+00:00",
                  "reason": "вернули руками", "clawback": False}
        closed = self.make_invoice(status="cancelled", expires_in=-600,
                                   finalized_at=timezone.now() - timedelta(hours=1))
        unsettled = self.make_invoice(
            status="committed", user=self.other, finalized_at=timezone.now() - timedelta(hours=1),
            last_checked_at=timezone.now() - timedelta(minutes=10))
        for invoice in (closed, unsettled):
            Payment.objects.filter(pk=invoice.payment_id).update(
                response={"admin_refund": refund}, error="refunded")
            self.bank.pay(invoice)
        result = self.run_reconcile()
        self.assertEqual((result["checked"], result["credited"]), (0, 0))
        self.assertEqual(self.bank.calls, [])
        # В любом другом месте такой платёж отвечает «already».
        for invoice in (closed, unsettled):
            self.assertEqual(service.refresh_invoice(invoice, source="admin"), "already")
            invoice = self.reload(invoice)
            self.assertEqual((invoice.payment.success, invoice.payment.error), (False, "refunded"))
        self.assertEqual(TokenTransaction.objects.filter(reason="purchase").count(), 0)

    def test_failed_credit_is_retried_without_a_cutoff(self):
        invoice = self.make_invoice()
        self.bank.pay(invoice)
        with patch("payments.views._credit_token_package_for_payment",
                   side_effect=RuntimeError("база моргнула")):
            self.assertEqual(self.run_reconcile()["credited"], 0)
        invoice = self.reload(invoice)
        self.assertEqual((invoice.status, invoice.payment.success), ("committed", False))
        self.assertEqual(invoice.payment.error, "token_purchase_apply_failed:RuntimeError")
        self.assertEqual(service.ui_state(invoice), "processing")
        # Раньше пяти минут не повторяем.
        self.assertEqual(self.run_reconcile()["checked"], 0)
        self.age(invoice, last_checked_at=timezone.now() - timedelta(minutes=6))
        self.assertEqual(self.run_reconcile()["credited"], 1)
        self.assertEqual((self.balance(), self.ledger()), (500, 1))

    def test_failed_credit_is_still_retried_after_three_days(self):
        invoice = self.make_invoice(status="committed", expires_in=-3 * 86400,
                                    finalized_at=timezone.now() - timedelta(days=3))
        Payment.objects.filter(pk=invoice.payment_id).update(
            error="token_purchase_apply_failed:RuntimeError")
        self.bank.pay(invoice)
        # Спустя двое суток — раз в шесть часов.
        self.age(invoice, last_checked_at=timezone.now() - timedelta(hours=5))
        self.assertEqual(self.run_reconcile()["checked"], 0)
        self.age(invoice, last_checked_at=timezone.now() - timedelta(hours=6, minutes=1))
        self.assertEqual(self.run_reconcile()["credited"], 1)
        self.assertEqual((self.balance(), self.ledger()), (500, 1))

    def test_rows_nobody_retries_do_not_starve_a_failed_credit(self):
        # Возвращённые руками и ушедшие на разбор счета сверка не перепроверяет,
        # поэтому их last_checked_at не меняется и они всегда «самые давние».
        # Когда их набралось больше окна выборки, упавшее начисление всё равно
        # обязано дождаться повтора — иначе оплативший останется без кредитов.
        long_ago = timezone.now() - timedelta(days=30)
        refund = {"kind": "refund", "by_id": self.staff.id, "at": "2026-09-01T10:00:00+00:00",
                  "reason": "вернули руками", "clawback": True}
        window = tasks._GOPAY_SWEEP * 10
        for n in range(window + 5):
            flags = {"needs_review": "mismatch:amount"} if n % 2 else {}
            self.make_invoice(status="committed", user=self.other, in_bank=False, flags=flags,
                              finalized_at=long_ago, last_checked_at=long_ago)
        Payment.objects.filter(user=self.other, gopay_invoice__flags={}).update(
            response={"admin_refund": refund, "token_purchase_clawed_back": True},
            error="refunded")
        Payment.objects.filter(user=self.other).exclude(error="refunded").update(
            error="amount_mismatch")
        self.assertEqual(GoPayInvoice.objects.filter(status="committed").count(), window + 5)

        failed = self.make_invoice(status="committed",
                                   finalized_at=timezone.now() - timedelta(hours=1),
                                   last_checked_at=timezone.now() - timedelta(minutes=10))
        Payment.objects.filter(pk=failed.payment_id).update(
            error="token_purchase_apply_failed:RuntimeError")
        self.bank.pay(failed)
        result = self.run_reconcile()
        self.assertEqual((result["checked"], result["credited"]), (1, 1))
        self.assertEqual(self.bank.paths(), ["/v1/payments/query"])
        self.assertTrue(self.reload(failed).payment.success)
        self.assertEqual((self.balance(), self.ledger()), (500, 1))
        self.assertEqual(self.ledger(self.other), 0)

    def test_invoices_under_review_are_left_to_a_human(self):
        invoice = self.make_invoice(status="committed", flags={"needs_review": "mismatch:amount"},
                                    finalized_at=timezone.now() - timedelta(hours=1),
                                    last_checked_at=timezone.now() - timedelta(hours=1))
        self.bank.pay(invoice)
        self.assertEqual(self.run_reconcile()["checked"], 0)
        self.assertEqual(self.bank.calls, [])
        self.assertFalse(self.reload(invoice).payment.success)

    def test_budget_stops_the_run(self):
        # Каждый запрос статуса «длится» девять секунд: проход обязан остановиться
        # сам, а не занять очередь на минуты.
        packages = [TokenPackage.objects.create(name=f"P{n}", tokens=100, price=Decimal("100"))
                    for n in range(12)]
        for package in packages:
            self.make_invoice(package=package, amount="100.00")
        clock = {"now": 1000.0}

        def slow(path):
            clock["now"] += 9.0

        self.bank.on_call = slow
        with patch("payments.tasks._clock", side_effect=lambda: clock["now"]):
            result = self.run_reconcile()
        self.assertEqual(result["status"], "budget")
        self.assertLessEqual(clock["now"] - 1000.0, 50.0)
        self.assertEqual(result["checked"], 5)
        self.assertEqual(self.bank.count("/v1/payments/query"), 5)
        self.assertIsNone(cache.get("payments:gopay_reconcile:lock"))

    def test_two_unavailable_answers_stop_the_env_and_the_next_run_is_skipped(self):
        for n in range(6):
            self.make_invoice(package=TokenPackage.objects.create(
                name=f"P{n}", tokens=100, price=Decimal("100")), amount="100.00")
        test_invoice = self.make_invoice(env="test", amount="100.00")
        for n in range(3):
            self.make_invoice(env="test", amount="100.00", package=TokenPackage.objects.create(
                name=f"T{n}", tokens=100, price=Decimal("100")))
        self.bank.always("/v1/payments/query", NETWORK_DOWN)
        result = self.run_reconcile()
        # Две неудачи подряд по каждой среде — и среда закрыта до конца прохода.
        self.assertEqual(self.bank.count("/v1/payments/query"), 4)
        self.assertEqual(sorted(result["skipped_env"]), ["live", "test"])
        self.assertEqual(result["checked"], 0)
        self.assertTrue(service.provider_down("live"))

        # Пока предохранитель стоит, следующий проход GoPay не трогает вовсе.
        result = self.run_reconcile()
        self.assertEqual(self.bank.count("/v1/payments/query"), 4)
        self.assertEqual(sorted(result["skipped_env"]), ["live", "test"])
        self.assertEqual(self.reload(test_invoice).status, "created")

    def test_breaker_set_during_the_run_stops_the_env_at_once(self):
        # Предохранитель сработал посреди прохода (его поставили запросы
        # покупателей в другом процессе), и наш запрос тоже не прошёл: вторую
        # неудачу не ждём — оставшиеся счета этой среды не трогаем.
        for n in range(5):
            self.make_invoice(package=TokenPackage.objects.create(
                name=f"P{n}", tokens=100, price=Decimal("100")), amount="100.00")

        def trip(path):
            cache.set("gopay:down:live", 1, 45)

        self.bank.on_call = trip
        self.bank.always("/v1/payments/query", NETWORK_DOWN)
        result = self.run_reconcile()
        self.assertEqual(self.bank.count("/v1/payments/query"), 1)
        self.assertEqual((result["checked"], result["skipped_env"]), (0, ["live"]))

    def test_only_the_failing_env_is_skipped(self):
        live = self.make_invoice()
        test = self.make_invoice(env="test")
        cache.set("gopay:down:test", 1, 45)
        self.bank.pay(live)
        self.bank.pay(test)
        result = self.run_reconcile()
        self.assertEqual((result["credited"], result["skipped_env"]), (1, ["test"]))
        self.assertTrue(self.reload(live).payment.success)
        self.assertFalse(self.reload(test).payment.success)

    def test_skipped_env_still_expires_overdue_invoices_locally(self):
        invoice = self.make_invoice(expires_in=-700)
        fresh = self.make_invoice(expires_in=-300, user=self.other)
        cache.set("gopay:down:live", 1, 45)
        self.run_reconcile()
        self.assertEqual(self.bank.calls, [])
        invoice = self.reload(invoice)
        self.assertEqual((invoice.status, invoice.flags.get("local_expiry")), ("expired", True))
        self.assertEqual(self.reload(fresh).status, "created")

    def test_lock_makes_a_second_run_busy(self):
        self.make_invoice()
        cache.add("payments:gopay_reconcile:lock", "другой-проход", 120)
        self.assertEqual(self.run_reconcile(), {"status": "busy"})
        self.assertEqual(self.bank.calls, [])
        self.assertEqual(cache.get("payments:gopay_reconcile:lock"), "другой-проход")

    def test_run_that_lost_its_lock_does_not_remove_the_new_owners_lock(self):
        invoice = self.make_invoice()

        def steal(path):
            # Проход затянулся, его замок истёк, и следующий проход взял свой.
            cache.set("payments:gopay_reconcile:lock", "новый-владелец", 120)

        self.bank.on_call = steal
        self.assertEqual(self.run_reconcile()["status"], "ok")
        self.assertEqual(cache.get("payments:gopay_reconcile:lock"), "новый-владелец")
        self.assertIsNotNone(self.reload(invoice).last_checked_at)

    def test_one_broken_invoice_does_not_stop_the_run(self):
        broken = self.make_invoice()
        good = self.make_invoice(user=self.other)
        self.bank.pay(good)
        real = service.refresh_invoice

        def flaky(invoice, *, source="query"):
            if invoice.pk == broken.pk:
                raise RuntimeError("сбой на одном счёте")
            return real(invoice, source=source)

        with patch("payments.gopay.service.refresh_invoice", side_effect=flaky):
            result = self.run_reconcile()
        self.assertEqual(result["credited"], 1)
        self.assertTrue(self.reload(good).payment.success)

    def test_newest_and_longest_unchecked_are_both_served(self):
        # 45 счетов: срез «самые свежие» берёт 40, остальным достаётся второй срез.
        invoices = [self.make_invoice(package=TokenPackage.objects.create(
            name=f"P{n}", tokens=100, price=Decimal("100")), amount="100.00") for n in range(45)]
        result = self.run_reconcile()
        self.assertEqual(result["checked"], 45)
        self.assertEqual(self.bank.count("/v1/payments/query"), 45)
        self.assertTrue(all(self.reload(inv).last_checked_at for inv in invoices))

    def test_old_open_invoice_and_orphan_are_not_asked(self):
        old = self.make_invoice()
        self.age(old, created_at=timezone.now() - timedelta(hours=49))
        orphan = self.make_invoice(user=self.other)
        Payment.objects.filter(pk=orphan.payment_id).update(user=None)
        self.assertEqual(self.run_reconcile()["checked"], 0)
        self.assertEqual(self.bank.calls, [])

    def test_bank_apps_are_refreshed_rarely(self):
        cache.delete(self.APPS_MARK)
        self.run_reconcile()
        self.run_reconcile()
        # Список банков пуст — спрашиваем, но не каждую минуту.
        self.assertEqual(self.bank.count("/v1/payment-app"), 1)
        with override_settings(GOPAY_ENV="test"):
            cache.clear()
            self.run_reconcile()
        self.assertEqual(self.bank.count("/v1/payment-app"), 1)      # в тесте банков нет вовсе

    def test_bank_apps_are_refreshed_when_only_the_last_good_copy_is_left(self):
        def app(code, order):
            return {"code": code, "name": code.capitalize(), "order": order,
                    "url": code + "://elqr?data={qr_data}", "icon": "",
                    "android_package_name": "kg." + code, "is_active_on_ios": True}

        # Свежая копия (шесть часов) истекла, «последний удачный» список (неделя)
        # ещё жив. Он годится, чтобы показать кнопки, но не чтобы перестать
        # спрашивать: иначе новый банк доходил бы до покупателя через неделю.
        cache.delete(self.APPS_MARK)
        cache.set("gopay:apps:last:live", [app("mbank", 1)], 600)
        self.assertEqual(len(service.cached_apps("live")), 1)
        self.bank.always("/v1/payment-app", ok([app("mbank", 1), app("newbank", 2)]))
        self.run_reconcile()
        self.assertEqual(self.bank.count("/v1/payment-app"), 1)
        self.assertEqual([a["code"] for a in cache.get("gopay:apps:v1:live")],
                         ["mbank", "newbank"])
        self.assertEqual(len(cache.get("gopay:apps:last:live")), 2)

        # Свежая копия есть — не спрашиваем, даже когда десятиминутная отметка истекла.
        cache.delete(self.APPS_MARK)
        self.run_reconcile()
        self.assertEqual(self.bank.count("/v1/payment-app"), 1)

        # Свежая копия истекла, а GoPay не ответил: кнопки остаются из запаса,
        # следующая попытка — не раньше чем через десять минут.
        cache.delete("gopay:apps:v1:live")
        cache.delete(self.APPS_MARK)
        self.bank.always("/v1/payment-app", NETWORK_DOWN)
        self.run_reconcile()
        self.run_reconcile()
        self.assertEqual(self.bank.count("/v1/payment-app"), 2)
        self.assertEqual(len(service.cached_apps("live")), 2)
        self.assertFalse(service.apps_fresh("live"))

    def test_beat_entry_points_at_the_task(self):
        from django.conf import settings

        entry = settings.CELERY_BEAT_SCHEDULE["payments:reconcile_gopay_invoices"]
        self.assertEqual(entry["task"], tasks.reconcile_gopay_invoices.name)
        self.assertEqual(tasks.check_gopay_invoice.name, "payments.tasks.check_gopay_invoice")
        self.assertEqual(tasks.cancel_gopay_invoice.name, "payments.tasks.cancel_gopay_invoice")


# ========================================================== воронка ===

class FunnelTests(FlowCase):
    QR_STEPS = ("kgs_qr_shown", "kgs_qr_app_open", "kgs_qr_save", "kgs_qr_paid",
                "kgs_qr_expired", "kgs_qr_other_method")

    def stage(self, invoice):
        return _payment_stage(Payment.objects.select_related("gopay_invoice").get(
            pk=invoice.payment_id))

    def test_payment_stage_for_each_gopay_status(self):
        cases = [
            (dict(status="created"), "pending"),
            (dict(status="pending"), "pending"),
            (dict(status="created", expires_in=-5), "left"),        # срок вышел, не закрыт
            (dict(status="expired", expires_in=-600), "left"),
            (dict(status="cancelled"), "canceled"),
            (dict(status="failed"), "declined"),
            (dict(status="committed"), "left"),                    # оплачен, не зачислен
        ]
        for n, (fields, expected) in enumerate(cases):
            with self.subTest(fields=fields):
                invoice = self.make_invoice(package=TokenPackage.objects.create(
                    name=f"P{n}", tokens=100, price=Decimal("100")), **fields)
                self.assertEqual(self.stage(invoice), expected)
        abandoned = self.make_invoice(user=self.other)
        service.mark_abandoned(abandoned, "user")
        self.assertEqual(self.stage(abandoned), "canceled")
        paid = self.make_invoice(user=self.staff, status="committed")
        Payment.objects.filter(pk=paid.payment_id).update(success=True)
        self.assertEqual(self.stage(paid), "paid")
        # История статусов в callbacks не превращает истёкший QR в «отклонён».
        expired = self.make_invoice(user=self.other, status="expired", expires_in=-600,
                                    package=TokenPackage.objects.create(
                                        name="E", tokens=100, price=Decimal("100")))
        Payment.objects.filter(pk=expired.payment_id).update(
            response={"callbacks": [{"type": "gopay_webhook", "payload": {"status": "EXPIRED"}}]})
        self.assertEqual(self.stage(expired), "left")

    def test_report_breaks_purchases_down_by_method(self):
        paid = self.make_invoice(status="committed")
        Payment.objects.filter(pk=paid.payment_id).update(success=True)
        self.make_invoice(user=self.other, status="expired", expires_in=-600)
        self.make_invoice(user=self.other, package=TokenPackage.objects.create(
            name="B", tokens=100, price=Decimal("100")))
        # Создание счёта не удалось: платёж есть, счёта нет.
        Payment.objects.create(user=self.user, provider="gopay", amount=Decimal("490"),
                               currency="KGS", order_id="tokpkg-1-1-nocreate",
                               error="gopay_create_failed:network",
                               request={"provider": "gopay", "pay_method": "elqr",
                                        "token_purchase": {"package_id": self.pkg.id}})
        # Тестовый платёж сотрудника в отчёт не попадает вовсе.
        test = self.make_invoice(env="test", status="committed")
        Payment.objects.filter(pk=test.payment_id).update(success=True)

        def other(provider, method, success, currency="KGS"):
            request = {"token_purchase": {"package_id": self.pkg.id}}
            if method:
                request["pay_method"] = method
            Payment.objects.create(
                user=self.user, provider=provider, amount=Decimal("490"), currency=currency,
                order_id=f"tokpkg-{uuid.uuid4().hex[:12]}", success=success, request=request,
                response={})

        other("freedompay", "card", True)
        other("freedompay", "card", False)
        other("freedompay", "", False)
        other("freedompay", "mbank", False)
        other("yookassa", "", True, "RUB")
        other("crypto_nowpayments", "crypto", False, "USD")
        other("telegram_stars", "stars", True, "XTR")

        report = funnel_report(30)
        rows = {row["key"]: row for row in report["by_method"]}
        self.assertEqual(rows["gopay:elqr"], {
            "key": "gopay:elqr", "provider": "gopay", "method": "elqr",
            "label": "Единый QR (GoPay)", "всего": 4, "оплачено": 1})
        self.assertEqual((rows["freedompay:card"]["label"], rows["freedompay:card"]["всего"],
                          rows["freedompay:card"]["оплачено"]), ("Карта (FreedomPay)", 2, 1))
        self.assertEqual(rows["freedompay:"]["label"], "FreedomPay без выбора способа")
        self.assertEqual(rows["freedompay:mbank"]["label"], "MBANK (FreedomPay)")
        self.assertEqual(rows["yookassa:"]["label"], "ЮKassa")
        self.assertEqual(rows["crypto_nowpayments:"]["label"], "Крипта")
        self.assertEqual(rows["telegram_stars:"]["label"], "Telegram Stars")
        # Сортировка — по числу попыток.
        totals = [row["всего"] for row in report["by_method"]]
        self.assertEqual(totals, sorted(totals, reverse=True))
        self.assertEqual(report["by_method"][0]["key"], "gopay:elqr")
        self.assertEqual(sum(totals), 11)

        # Тестовый платёж не посчитан нигде.
        self.assertEqual(next(s for s in report["steps"] if s["key"] == "payment_started")["count"], 11)
        self.assertEqual(next(s for s in report["steps"] if s["key"] == "paid")["count"], 4)
        kgs = next(row for row in report["by_currency"] if row["currency"] == "KGS")
        self.assertEqual((kgs["всего"], kgs["оплачено"]), (8, 2))
        pending = next(r for r in report["reasons"] if r["key"] == "pending")
        self.assertEqual((pending["label"], pending["count"]), ("Ждём оплату (крипта, QR)", 1))

    def test_qr_block_counts_server_rows_and_client_events_separately(self):
        paid = self.make_invoice(status="committed")
        Payment.objects.filter(pk=paid.payment_id).update(success=True)
        self.make_invoice(user=self.other, status="expired", expires_in=-600)
        self.make_invoice(user=self.other, package=TokenPackage.objects.create(
            name="B", tokens=100, price=Decimal("100")))
        test = self.make_invoice(env="test", status="committed")
        Payment.objects.filter(pk=test.payment_id).update(success=True)

        def seen(name, *devices):
            for device in devices:
                FunnelEvent.objects.create(name=name, device_key=device, meta={})

        seen("kgs_qr_shown", "d1", "d1", "d2", "d3")       # три устройства
        seen("kgs_qr_app_open", "d1", "d2")
        seen("kgs_qr_save", "d3")
        seen("kgs_qr_other_method", "d2")
        seen("kgs_qr_expired", "d2", "d3")                  # пишется, но в строку не идёт

        self.assertEqual(funnel_report(30)["qr"], {
            "created": 3, "shown": 3, "app_open": 2, "saved": 1, "other_method": 1,
            # Оплаченный QR считается оплаченным и без события клиента: с телефона
            # человек платит в приложении банка и во вкладку не возвращается.
            "paid": 1, "expired": 1, "paid_seen": 0})
        seen("kgs_qr_paid", "d1")
        self.assertEqual(funnel_report(30)["qr"]["paid_seen"], 1)

    def test_qr_steps_are_accepted_by_the_event_endpoint(self):
        for name in self.QR_STEPS:
            with self.subTest(name=name):
                self.assertIn(name, FunnelEvent.NAMES)
                self.assertLessEqual(len(name), FunnelEvent._meta.get_field("name").max_length)
                r = self.http.post("/api/payments/funnel/event/",
                                   {"name": name, "meta": {"package_id": self.pkg.id}},
                                   format="json", HTTP_X_DEVICE_KEY="dev-header")
                self.assertEqual(r.status_code, 201)
        # Ключ устройства в теле, без заголовка (sendBeacon заголовки не шлёт).
        for name in self.QR_STEPS:
            r = self.http.post("/api/payments/funnel/event/",
                               {"name": name, "device_key": "dev-body"}, format="json")
            self.assertEqual(r.status_code, 201)
        self.assertEqual(FunnelEvent.objects.filter(name__startswith="kgs_qr_",
                                                    device_key="dev-header").count(), 6)
        self.assertEqual(FunnelEvent.objects.filter(name__startswith="kgs_qr_",
                                                    device_key="dev-body").count(), 6)
        self.assertEqual(self.http.post("/api/payments/funnel/event/",
                                        {"name": "kgs_qr_hacked"}, format="json").status_code, 400)


# ================================================ обычная рефералка ===

class ReferralTests(FlowCase):
    def setUp(self):
        super().setUp()
        self.inviter = get_user_model().objects.create_user(email="inviter@example.com",
                                                            password="x-pass-123")
        self._start(patch("botapi.tasks.notify"))

    def shares(self):
        return TokenTransaction.objects.filter(user=self.inviter, reason="referral").count()

    def test_normal_gopay_payment_pays_the_referral_share(self):
        get_user_model().objects.filter(pk=self.user.pk).update(referred_by=self.inviter)
        invoice = self.make_invoice()
        self.bank.pay(invoice)
        self.assertEqual(service.refresh_invoice(invoice, source="reconcile"), "credited")
        self.assertEqual(self.shares(), 1)
        self.assertEqual(self.balance(self.inviter), 50)
        # Повтор долю не удваивает.
        service.refresh_invoice(invoice, source="reconcile")
        self.assertEqual(self.shares(), 1)

    @override_settings(GOPAY_ENV="test")
    def test_test_payment_credits_the_tester_but_pays_no_share(self):
        get_user_model().objects.filter(pk=self.staff.pk).update(referred_by=self.inviter)
        invoice = self.make_invoice(env="test")
        self.bank.pay(invoice)
        self.assertEqual(service.refresh_invoice(invoice, source="reconcile"), "credited")
        self.assertEqual((self.balance(self.staff), self.ledger(self.staff)), (500, 1))
        self.assertEqual(self.shares(), 0)
        self.assertEqual(self.balance(self.inviter), 0)
        # Цепочку надо уметь пройти целиком: «платным» тестировщик всё же становится.
        self.staff.refresh_from_db()
        self.assertTrue(self.staff.is_paid)
        self.assertTrue(self.reload(invoice).payment.is_test)

    def test_settle_referral_skips_only_the_ordinary_share(self):
        from payments.referral import settle_referral

        get_user_model().objects.filter(pk=self.user.pk).update(referred_by=self.inviter)
        self.user.refresh_from_db()
        test = Payment.objects.create(user=self.user, provider="gopay", amount=Decimal("490"),
                                      currency="KGS", order_id="tokpkg-t-1", is_test=True)
        real = Payment.objects.create(user=self.user, provider="gopay", amount=Decimal("490"),
                                      currency="KGS", order_id="tokpkg-t-2", is_test=False)
        self.assertEqual(settle_referral(test, test.order_id, 500), "none")
        self.assertEqual(self.shares(), 0)
        self.assertEqual(settle_referral(real, real.order_id, 500), "referral")
        self.assertEqual(self.shares(), 1)
