"""Возврат оплаты отменяет комиссию креатора целиком — каким бы путём возврат ни пришёл."""
import hashlib
import threading
from decimal import Decimal
from unittest import skipUnless
from unittest.mock import MagicMock, patch
from urllib.parse import urlencode

from django.db import connection
from django.test import override_settings
from rest_framework.test import APIClient

from audit.models import AdminActionLog
from botapi import stars as stars_service
from payments import tasks as payment_tasks
from payments import views as payment_views
from payments.crypto import base as crypto_base
from payments.models import Payment
from payments.referral import reverse_creator_commission
from plans.models import TokenTransaction

from .. import commission, tasks
from ..errors import CreatorsError
from ..models import Creator, CreatorCommission
from . import factories as f
from .test_commission import (
    MoneyTestCase,
    crypto_invoice,
    pay_crypto,
    pay_postback,
    pay_stars,
    pay_yookassa,
    refund_postback,
    star_invoice,
    yk_answer,
)

D = Decimal
SECRET = "secret"
POSTBACK = "/api/payments/tokens/postback/"
REFUND = "/api/payments/tokens/refund/"
YK_WEBHOOK = "/api/payments/yookassa/webhook/"


def _sig(script, params, secret=SECRET):
    pieces = [script] + [str(params[k]) for k in sorted(params)] + [secret]
    return hashlib.md5(";".join(pieces).encode("utf-8")).hexdigest()


class ReversalTestCase(MoneyTestCase):
    def setUp(self):
        super().setUp()
        self.admin = f.make_user(superuser=True)
        self.creator, self.buyer, self.referral = self.bound()

    def paid(self, **kwargs):
        """Оплаченный настоящим путём заказ покупателя, закреплённого за креатором."""
        kwargs.setdefault("amount", "490.00")
        payment = f.make_payment(self.buyer, success=False, **kwargs)
        pay_postback(payment)
        payment.refresh_from_db()
        return payment

    def states(self, payment):
        return [(row.status, row.reason) for row in self.rows(payment)]

    def balance(self):
        self.buyer.refresh_from_db()
        return self.buyer.token_balance


# ----------------------------------------------------- FreedomPay / общий хук ---

class ClawbackHookTests(ReversalTestCase):
    def test_refund_signal_reverses_and_claws_back(self):
        payment = self.paid()
        self.assertEqual(self.states(payment), [("accrued", "")])
        refund_postback(payment)
        row = self.rows(payment)[0]
        self.assertEqual((row.status, row.reason), ("reversed", "refund:freedompay"))
        self.assertIsNotNone(row.reversed_at)
        # Сумма остаётся в строке: по ней видно, что именно отменено.
        self.assertEqual(row.amount_usdt, D("0.563500"))
        self.assertEqual(self.balance(), 0)
        # Отмена — без уведомления креатору.
        self.assertEqual(len(self.emit.call_args_list), 2)   # только начисление

    def test_double_refund_is_a_noop(self):
        payment = self.paid()
        refund_postback(payment)
        first = self.rows(payment)[0]
        refund_postback(payment)
        again = self.rows(payment)[0]
        self.assertEqual((again.status, again.reason, again.reversed_at),
                         (first.status, first.reason, first.reversed_at))
        self.assertEqual(TokenTransaction.objects.filter(reason="refund").count(), 1)

    def test_reversed_before_the_already_clawed_back_guard(self):
        # Кредиты уже изъяты раньше (флаг стоит), а комиссия осталась — хук отменяет её до выхода.
        payment = f.make_payment(self.buyer)
        payment.response = {"token_purchase_clawed_back": True}
        payment.save(update_fields=["response"])
        f.make_commission(self.creator, payment)
        payment_views._clawback_token_package_for_payment(payment, payment.order_id, {})
        self.assertEqual(self.states(payment), [("reversed", "refund:freedompay")])

    def test_reversed_when_there_was_no_purchase_transaction(self):
        payment = f.make_payment(self.buyer)
        f.make_commission(self.creator, payment)
        payment_views._clawback_token_package_for_payment(payment, payment.order_id, {})
        self.assertEqual(self.states(payment), [("reversed", "refund:freedompay")])
        self.assertTrue(payment.response["token_purchase_clawed_back"])

    def test_reversed_when_the_payment_lost_its_user(self):
        payment = f.make_payment(self.buyer)
        f.make_commission(self.creator, payment)
        Payment.objects.filter(pk=payment.pk).update(user=None)
        payment = Payment.objects.get(pk=payment.pk)
        payment_views._clawback_token_package_for_payment(payment, payment.order_id, {})
        self.assertEqual(self.states(payment), [("reversed", "refund:freedompay")])

    def test_held_rows_are_reversed_too(self):
        Creator.objects.filter(pk=self.creator.pk).update(status="blocked")
        payment = self.paid()
        self.assertEqual(self.states(payment), [("held", "creator_blocked")])
        refund_postback(payment)
        self.assertEqual(self.states(payment), [("reversed", "refund:freedompay")])

    def test_void_and_reversed_rows_are_left_alone(self):
        payment = f.make_payment(self.buyer)
        f.make_commission(self.creator, payment, status="void", reason="admin_void", part="a")
        f.make_commission(self.creator, payment, status="reversed", reason="fraud", part="b")
        self.assertEqual(commission.reverse_for_payment(payment, "refund:freedompay"), 0)
        self.assertEqual(sorted(self.states(payment)), [("reversed", "fraud"), ("void", "admin_void")])

    def test_reversal_ignores_the_mode(self):
        payment = self.paid()
        with override_settings(CREATORS_MODE="off"):
            refund_postback(payment)
        self.assertEqual(self.states(payment), [("reversed", "refund:freedompay")])

    def test_payment_without_commission_takes_no_lock(self):
        payment = f.make_payment(f.make_user())
        with patch.object(Creator.objects, "locked") as locked, \
                patch("creators.commission.get_user_model") as user_model:
            self.assertEqual(commission.reverse_for_payment(payment, "refund:freedompay"), 0)
        locked.assert_not_called()
        user_model.assert_not_called()

    def test_buyer_is_locked_before_the_creator(self):
        payment = self.paid()
        order = []
        real_locked = Creator.objects.locked
        users = MagicMock()
        users.objects.select_for_update.return_value.filter.return_value.first.side_effect = (
            lambda: order.append("buyer"))
        with patch.object(Creator.objects, "locked",
                          side_effect=lambda pk: order.append("creator") or real_locked(pk)), \
                patch("creators.commission.get_user_model", return_value=users):
            self.assertEqual(commission.reverse_for_payment(payment, "refund:freedompay"), 1)
        self.assertEqual(order, ["buyer", "creator"])
        users.objects.select_for_update.return_value.filter.assert_called_once_with(pk=self.buyer.pk)

    def test_several_creators_are_locked_in_pk_order(self):
        other = f.make_creator()
        payment = f.make_payment(self.buyer)
        f.make_commission(other, payment, part="b")
        f.make_commission(self.creator, payment, part="a")
        order = []
        real_locked = Creator.objects.locked
        with patch.object(Creator.objects, "locked",
                          side_effect=lambda pk: order.append(pk) or real_locked(pk)):
            self.assertEqual(commission.reverse_for_payment(payment, "fraud"), 2)
        self.assertEqual(order, sorted([self.creator.pk, other.pk]))

    def test_reversal_never_raises(self):
        payment = self.paid()
        with patch.object(Creator.objects, "locked", side_effect=RuntimeError("база")):
            self.assertEqual(commission.reverse_for_payment(payment, "x"), 0)
            self.assertEqual(reverse_creator_commission(payment, "x"), 0)
            # Возврат покупки при этом проходит: кредиты изъяты.
            refund_postback(payment)
        self.assertEqual(self.balance(), 0)
        self.assertEqual(self.states(payment), [("accrued", "")])
        with patch("creators.commission.reverse_for_payment", side_effect=RuntimeError("boom")):
            self.assertEqual(reverse_creator_commission(payment, "x"), 0)


# ------------------------------------------------------------- Stars / крипта ---

class StarsAndCryptoTests(ReversalTestCase):
    def test_stars_refund(self):
        payment = f.make_payment(self.buyer, provider="telegram_stars", amount="385",
                                 success=False)
        invoice = star_invoice(payment)
        pay_stars(payment)
        self.assertEqual(self.states(payment), [("accrued", "")])

        result = stars_service.mark_refunded(charge_id=invoice.telegram_payment_charge_id)
        self.assertEqual(result["status"], "refunded")
        self.assertEqual(self.states(payment), [("reversed", "refund:telegram_stars")])
        self.assertEqual(self.balance(), 0)
        again = stars_service.mark_refunded(charge_id=invoice.telegram_payment_charge_id)
        self.assertEqual(again["status"], "already_refunded")
        self.assertEqual(self.states(payment), [("reversed", "refund:telegram_stars")])

    def test_crypto_refunded_status_reverses_every_part(self):
        payment = f.make_payment(self.buyer, provider="crypto_nowpayments", amount="10.00",
                                 tokens=1000, success=False)
        invoice = crypto_invoice(payment, pay_amount="10.5")
        pay_crypto(invoice, "5.25", crypto_base.PARTIALLY_PAID)
        pay_crypto(invoice, "10.5")
        self.assertEqual(self.states(payment), [("accrued", ""), ("accrued", "")])

        pay_crypto(invoice, "10.5", crypto_base.REFUNDED)
        self.assertEqual(self.states(payment), [("reversed", "refund:crypto")] * 2)
        # Кредиты крипты автоматом не изымаются — это по-прежнему решает человек.
        self.assertEqual(self.balance(), 1000)
        pay_crypto(invoice, "10.5", crypto_base.REFUNDED)
        self.assertEqual(self.states(payment), [("reversed", "refund:crypto")] * 2)


# ------------------------------------------------------------------- ЮKassa ---

@override_settings(YOOKASSA_SHOP_ID="shop", YOOKASSA_SECRET_KEY="key")
class YooKassaRefundTests(ReversalTestCase):
    def yk_paid(self, **extra):
        payment = f.make_payment(self.buyer, provider="yookassa", amount="520.00",
                                 kgs_price="490.00", success=False,
                                 yookassa_payment_id="yk-1", **extra)
        self.assertEqual(pay_yookassa(payment), "credited")
        payment.refresh_from_db()
        return payment

    def refunded(self, payment, value="520.00"):
        return yk_answer(payment, refunded_amount={"value": value, "currency": "RUB"})

    def test_refunded_amount_parsing(self):
        amount = payment_views.yookassa_refunded_amount
        self.assertEqual(amount({"refunded_amount": {"value": "12.50", "currency": "RUB"}}), D("12.50"))
        for broken in ({}, None, {"refunded_amount": None}, {"refunded_amount": {"value": "x"}},
                       {"refunded_amount": {}}):
            self.assertEqual(amount(broken), D("0"))

    def test_apply_refund(self):
        payment = self.yk_paid()
        result = payment_views.apply_yookassa_refund(payment, self.refunded(payment),
                                                     source="yookassa_refund_poll")
        self.assertEqual(result, "refunded")
        self.assertEqual(self.states(payment), [("reversed", "refund:yookassa")])
        payment.refresh_from_db()
        mark = payment.response["yookassa_refunded"]
        self.assertEqual((mark["amount"], mark["currency"], mark["full"]), ("520.00", "RUB", True))
        self.assertEqual(payment.response["callbacks"][-1]["type"], "yookassa_refund_poll")
        # Кредиты, признак оплаты и обычная доля не трогаются: это решает человек.
        self.assertTrue(payment.success)
        self.assertEqual(self.balance(), 500)

        again = payment_views.apply_yookassa_refund(payment, self.refunded(payment),
                                                    source="yookassa_refund_poll")
        self.assertEqual(again, "already")
        payment.refresh_from_db()
        self.assertEqual(len([c for c in payment.response["callbacks"]
                              if c["type"] == "yookassa_refund_poll"]), 1)

    def test_partial_refund_reverses_the_whole_commission(self):
        payment = self.yk_paid()
        payment_views.apply_yookassa_refund(payment, self.refunded(payment, "100.00"), source="x")
        self.assertEqual(self.states(payment), [("reversed", "refund:yookassa")])
        payment.refresh_from_db()
        self.assertFalse(payment.response["yookassa_refunded"]["full"])

    def test_no_refund_changes_nothing(self):
        payment = self.yk_paid()
        for answer in (yk_answer(payment), self.refunded(payment, "0.00"), {}):
            self.assertEqual(payment_views.apply_yookassa_refund(payment, answer, source="x"), "none")
        # Ответ про чужой заказ к этому платежу не применяется.
        foreign = self.refunded(payment)
        foreign["metadata"] = {"order_id": "tokpkg-other"}
        self.assertEqual(payment_views.apply_yookassa_refund(payment, foreign, source="x"), "none")
        self.assertEqual(self.states(payment), [("accrued", "")])
        payment.refresh_from_db()
        self.assertNotIn("yookassa_refunded", payment.response)

    def test_webhook_refund_uses_payment_id_and_trusts_only_the_api(self):
        payment = self.yk_paid()
        client = APIClient()
        # В уведомлении о возврате object.id — это id возврата, платёж лежит в payment_id.
        body = {"type": "notification", "event": "refund.succeeded",
                "object": {"id": "refund-777", "payment_id": "yk-1", "status": "succeeded",
                           "amount": {"value": "520.00", "currency": "RUB"}}}

        # API отвечает, что возврата нет: телу уведомления не верим.
        with patch("payments.yookassa.fetch_payment", return_value=yk_answer(payment)) as fetch:
            response = client.post(YK_WEBHOOK, body, format="json")
        self.assertEqual((response.status_code, response.data), (200, {"status": "ok"}))
        fetch.assert_called_once_with("yk-1")
        self.assertEqual(self.states(payment), [("accrued", "")])

        with patch("payments.yookassa.fetch_payment", return_value=self.refunded(payment)):
            response = client.post(YK_WEBHOOK, body, format="json")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.states(payment), [("reversed", "refund:yookassa")])
        payment.refresh_from_db()
        self.assertEqual(payment.response["callbacks"][-1]["type"], "yookassa_refund_webhook")
        self.assertTrue(payment.success)

    def test_webhook_refund_edge_cases(self):
        payment = self.yk_paid()
        client = APIClient()
        with patch("payments.yookassa.fetch_payment") as fetch:
            # Без payment_id спрашивать API не о чем.
            response = client.post(YK_WEBHOOK, {"event": "refund.succeeded",
                                                "object": {"id": "refund-1"}}, format="json")
            self.assertEqual((response.status_code, response.data), (200, {"status": "ignored"}))
            fetch.assert_not_called()
            # API недоступен — 503, ЮKassa повторит уведомление.
            fetch.side_effect = RuntimeError("timeout")
            response = client.post(YK_WEBHOOK, {"event": "refund.succeeded",
                                                "object": {"id": "r", "payment_id": "yk-1"}},
                                   format="json")
            self.assertEqual(response.status_code, 503)
        self.assertEqual(self.states(payment), [("accrued", "")])

    def test_webhook_payment_event_is_unchanged(self):
        payment = f.make_payment(self.buyer, provider="yookassa", amount="520.00",
                                 kgs_price="490.00", success=False, yookassa_payment_id="yk-1")
        body = {"event": "payment.succeeded", "object": {"id": "yk-1", "payment_id": "ignored"}}
        with patch("payments.yookassa.fetch_payment", return_value=yk_answer(payment)) as fetch:
            response = APIClient().post(YK_WEBHOOK, body, format="json")
        self.assertEqual(response.status_code, 200)
        fetch.assert_called_once_with("yk-1")
        self.assertEqual(self.states(payment), [("accrued", "")])
        self.assertEqual(self.balance(), 500)

    def test_poll_task(self):
        payment = self.yk_paid()
        with patch("payments.yookassa.fetch_payment", return_value=self.refunded(payment)) as fetch:
            self.assertEqual(tasks.poll_yookassa_refunds(),
                             {"status": "ok", "checked": 1, "refunded": 1})
            fetch.assert_called_once_with("yk-1")
        self.assertEqual(self.states(payment), [("reversed", "refund:yookassa")])
        payment.refresh_from_db()
        self.assertEqual(payment.response["callbacks"][-1]["type"], "yookassa_refund_poll")

    def test_poll_is_disabled_without_keys(self):
        self.yk_paid()
        with override_settings(YOOKASSA_SHOP_ID="", YOOKASSA_SECRET_KEY=""), \
                patch("payments.yookassa.fetch_payment") as fetch:
            self.assertEqual(tasks.poll_yookassa_refunds(), {"status": "disabled"})
        fetch.assert_not_called()

    def test_reconcile_skips_payments_marked_refunded(self):
        marks = ({"admin_refund": {"kind": "refund", "clawback": True}},
                 {"token_purchase_clawed_back": True},
                 {"yookassa_refunded": {"amount": "520.00"}})
        marked = []
        for mark in marks:
            payment = f.make_payment(self.buyer, provider="yookassa", amount="520.00",
                                     kgs_price="490.00", yookassa_payment_id="yk-marked",
                                     success=False)
            Payment.objects.filter(pk=payment.pk).update(response=mark, error="refunded")
            marked.append(payment)
        control = f.make_payment(self.buyer, provider="yookassa", amount="520.00",
                                 kgs_price="490.00", yookassa_payment_id="yk-control",
                                 success=False)

        def answer(yk_id):
            # ЮKassa по-прежнему отвечает «оплачен» про возвращённый платёж.
            return yk_answer(control if yk_id == "yk-control" else marked[0])

        with patch("payments.yookassa.fetch_payment", side_effect=answer) as fetch:
            result = payment_tasks.reconcile_yookassa_payments()
        self.assertEqual(result, {"status": "ok", "checked": 1, "credited": 1})
        fetch.assert_called_once_with("yk-control")
        for payment in marked:
            payment.refresh_from_db()
            self.assertEqual((payment.success, payment.error), (False, "refunded"))
        control.refresh_from_db()
        self.assertTrue(control.success)


# ---------------------------------------------- FreedomPay: возврат в кабинете ---

@override_settings(FREEDOM_PAY_MERCHANT_ID="m1", FREEDOM_PAY_TOKEN=SECRET)
class FreedomPayCabinetRefundTests(ReversalTestCase):
    def test_status_is_refund(self):
        is_refund = payment_views.freedompay_status_is_refund
        for status in ({"pg_status": "ok", "pg_transaction_status": "refunded"},
                       {"pg_status": "ok", "pg_transaction_status": "REVOKED"},
                       {"pg_status": "ok", "pg_payment_status": "partial_refunded"},
                       {"pg_status": "refunded"},
                       {"pg_status": "ok", "pg_refund_amount": "100.00"},
                       {"pg_status": "ok", "pg_refund_payment_id": "77"}):
            self.assertTrue(is_refund(status), status)
        for status in ({}, None, {"pg_status": "ok", "pg_transaction_status": "ok"},
                       {"pg_status": "ok", "pg_transaction_status": "success"},
                       {"pg_status": "error"}, {"pg_status": "ok", "pg_refund_amount": "0"},
                       {"pg_status": "ok", "pg_refund_amount": "мусор"},
                       # Отмена неоплаченного платежа — не возврат начисленного.
                       {"pg_status": "ok", "pg_transaction_status": "canceled"}):
            self.assertFalse(is_refund(status), status)

    def test_apply_refund_keeps_credits(self):
        payment = self.paid()
        status = {"pg_status": "ok", "pg_transaction_status": "refunded", "pg_sig": "secret-sig"}
        result = payment_views.apply_freedompay_refund(payment, status,
                                                       source="freedompay_refund_poll")
        self.assertEqual(result, "refunded")
        self.assertEqual(self.states(payment), [("reversed", "refund:freedompay")])
        payment.refresh_from_db()
        self.assertEqual(payment.response["freedompay_refunded"]["status"], "refunded")
        callback = payment.response["callbacks"][-1]
        self.assertEqual(callback["type"], "freedompay_refund_poll")
        self.assertNotIn("pg_sig", callback["payload"])
        # Кредиты и признак оплаты на месте: их изымает ручная отметка администратора.
        self.assertTrue(payment.success)
        self.assertEqual(self.balance(), 500)
        self.assertEqual(payment_views.apply_freedompay_refund(payment, status, source="x"), "already")

    def test_non_refund_status_changes_nothing(self):
        payment = self.paid()
        for status in ({"pg_status": "ok", "pg_transaction_status": "ok"}, {}):
            self.assertEqual(payment_views.apply_freedompay_refund(payment, status, source="x"), "none")
        payment.refresh_from_db()
        self.assertNotIn("freedompay_refunded", payment.response)
        self.assertEqual(self.states(payment), [("accrued", "")])

    def test_poll_task(self):
        payment = self.paid()
        untouched = self.paid()
        answers = {payment.order_id: {"pg_status": "ok", "pg_transaction_status": "refunded"},
                   untouched.order_id: {"pg_status": "ok", "pg_transaction_status": "ok"}}
        with patch("payments.tasks.fetch_payment_status", side_effect=answers.get) as fetch:
            self.assertEqual(tasks.poll_freedompay_refunds(),
                             {"status": "ok", "checked": 2, "refunded": 1})
            self.assertEqual(fetch.call_count, 2)
        self.assertEqual(self.states(payment), [("reversed", "refund:freedompay")])
        self.assertEqual(self.states(untouched), [("accrued", "")])
        self.assertEqual(self.balance(), 1000)

    def test_poll_is_disabled_without_keys(self):
        self.paid()
        with override_settings(FREEDOM_PAY_MERCHANT_ID="", FREEDOM_PAY_TOKEN=""), \
                patch("payments.tasks.fetch_payment_status") as fetch:
            self.assertEqual(tasks.poll_freedompay_refunds(), {"status": "disabled"})
        fetch.assert_not_called()


# ----------------------------------------- сигнал возврата: изъятие упало ---

@override_settings(FREEDOM_PAY_MERCHANT_ID="m1", FREEDOM_PAY_TOKEN=SECRET)
class FailedClawbackTests(ReversalTestCase):
    def signed(self, payment, script, **extra):
        params = {"pg_order_id": payment.order_id, "pg_payment_id": "1502541913",
                  "pg_amount": "490", "pg_currency": "KGS", "pg_salt": "abc123", **extra}
        params["pg_sig"] = _sig(script, params)
        return params

    def assertLeftForTheSafetyNet(self, payment):
        payment.refresh_from_db()
        self.assertTrue(str(payment.error).startswith("token_clawback_failed"), payment.error)
        # Отмена комиссии откатилась вместе с упавшим изъятием кредитов…
        self.assertEqual(self.states(payment), [("accrued", "")])
        self.assertEqual(self.balance(), 500)
        # …и её подбирает страховка.
        self.assertEqual(tasks.commission_safety_net(),
                         {"status": "ok", "checked": 1, "reversed": 1})
        self.assertEqual(self.states(payment), [("reversed", "refund:clawback_failed")])

    def test_refund_signal_in_the_postback(self):
        payment = self.paid()
        params = self.signed(payment, "postback", pg_result="1", pg_status="refunded")
        with patch("plans.wallet.clawback_tokens", side_effect=RuntimeError("wallet down")):
            response = APIClient().post(POSTBACK, urlencode(params),
                                        content_type="application/x-www-form-urlencoded")
        # FreedomPay получает «принято» и больше не повторит.
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"<pg_status>ok</pg_status>", response.content)
        self.assertLeftForTheSafetyNet(payment)

    def test_refund_endpoint(self):
        payment = self.paid()
        params = self.signed(payment, "refund")
        with patch("plans.wallet.clawback_tokens", side_effect=RuntimeError("wallet down")):
            response = APIClient().post(REFUND, params)
        self.assertEqual((response.status_code, response.data), (200, {"status": "ok"}))
        self.assertLeftForTheSafetyNet(payment)

    def test_refund_endpoint_normal_path(self):
        payment = self.paid()
        response = APIClient().post(REFUND, self.signed(payment, "refund"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.states(payment), [("reversed", "refund:freedompay")])
        self.assertEqual(self.balance(), 0)
        payment.refresh_from_db()
        self.assertEqual((payment.success, payment.error), (False, "refunded"))

    def test_postback_refund_normal_path(self):
        payment = self.paid()
        params = self.signed(payment, "postback", pg_result="1", pg_refund="1")
        response = APIClient().post(POSTBACK, urlencode(params),
                                    content_type="application/x-www-form-urlencoded")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.states(payment), [("reversed", "refund:freedompay")])
        self.assertEqual(self.balance(), 0)

    def test_unsigned_refund_is_ignored(self):
        payment = self.paid()
        params = self.signed(payment, "refund")
        params["pg_sig"] = "0" * 32
        response = APIClient().post(REFUND, params)
        self.assertEqual(response.status_code, 400)
        self.assertEqual(self.states(payment), [("accrued", "")])


# ------------------------------------------- отметка администратора ---

class MarkRefundedTests(ReversalTestCase):
    def mark(self, payment, **kwargs):
        kwargs.setdefault("kind", "refund")
        kwargs.setdefault("reason", "клиент попросил возврат")
        return commission.mark_payment_refunded(payment.pk, actor=self.admin, **kwargs)

    def logs(self):
        return AdminActionLog.objects.filter(action="payment.mark_refunded").order_by("id")

    def assertRefused(self, code, fn, *args, **kwargs):
        with self.assertRaises(CreatorsError) as ctx:
            fn(*args, **kwargs)
        self.assertEqual(ctx.exception.code, code)

    def test_refund_without_clawback(self):
        payment = self.paid()
        self.assertEqual(self.mark(payment), {"reversed": 1, "clawback_debited": 0})
        self.assertEqual(self.states(payment), [("reversed", "refund:admin")])
        payment.refresh_from_db()
        mark = payment.response["admin_refund"]
        self.assertEqual((mark["kind"], mark["by_id"], mark["reason"], mark["clawback"]),
                         ("refund", self.admin.pk, "клиент попросил возврат", False))
        # Кредиты и признак оплаты не трогаются: отметка — про комиссию.
        self.assertTrue(payment.success)
        self.assertEqual(self.balance(), 500)

        log = self.logs().get()
        self.assertEqual((log.actor_id, log.creator_id, log.target_type, log.target_id),
                         (self.admin.pk, self.creator.pk, "payments.payment", str(payment.pk)))
        self.assertEqual(log.reason, "клиент попросил возврат")
        self.assertEqual((log.after["kind"], log.after["reversed"], log.after["clawback_credits"]),
                         ("refund", 1, False))
        self.assertEqual((log.before["success"], log.after["success"]), (True, True))

    def test_fraud(self):
        payment = self.paid()
        self.assertEqual(self.mark(payment, kind="fraud")["reversed"], 1)
        self.assertEqual(self.states(payment), [("reversed", "fraud")])
        payment.refresh_from_db()
        self.assertEqual(commission.refund_marker(payment), "admin_fraud")

    def test_with_clawback_keeps_the_admin_reason_and_the_real_count(self):
        # Ответ платежа пуст ({}): отметка должна пережить изъятие, которое
        # пересобирает словарь ответа.
        payment = f.make_payment(self.buyer, amount="490.00", tokens=500)
        f.credit_purchase(payment)
        commission.accrue(payment)
        self.assertEqual(payment.response, {})

        self.assertEqual(self.mark(payment, clawback_credits=True),
                         {"reversed": 1, "clawback_debited": 500})
        # Причина администратора, а не «refund:freedompay» из общего кода возврата.
        self.assertEqual(self.states(payment), [("reversed", "refund:admin")])
        payment.refresh_from_db()
        self.assertEqual(payment.response["admin_refund"]["clawback"], True)
        self.assertTrue(payment.response["token_purchase_clawed_back"])
        self.assertEqual((payment.success, payment.error), (False, "refunded"))
        self.assertEqual(self.balance(), 0)
        log = self.logs().get()
        self.assertEqual((log.after["reversed"], log.after["clawback_credits"], log.creator_id),
                         (1, True, self.creator.pk))
        self.assertEqual((log.before["success"], log.after["success"], log.after["error"]),
                         (True, False, "refunded"))

    def test_crypto_parts_are_all_reversed(self):
        payment = f.make_payment(self.buyer, provider="crypto_nowpayments", amount="10.00",
                                 tokens=1000, success=False)
        invoice = crypto_invoice(payment)
        pay_crypto(invoice, "5.25", crypto_base.PARTIALLY_PAID)
        pay_crypto(invoice, "10.5")
        self.assertEqual(self.mark(payment, kind="fraud")["reversed"], 2)
        self.assertEqual(self.states(payment), [("reversed", "fraud")] * 2)
        self.assertEqual(self.logs().get().after["reversed"], 2)

    def test_clawback_takes_back_every_credited_part_of_a_crypto_order(self):
        # Криптосчёт зачислен двумя частями (недоплата, потом доплата): изъятие
        # забирает обе, а не только первую, — повторить его нельзя.
        payment = f.make_payment(self.buyer, provider="crypto_nowpayments", amount="10.00",
                                 tokens=1000, success=False)
        invoice = crypto_invoice(payment)
        pay_crypto(invoice, "5.25", crypto_base.PARTIALLY_PAID)
        pay_crypto(invoice, "10.5")
        self.assertEqual(self.balance(), 1000)

        self.assertEqual(self.mark(payment, clawback_credits=True),
                         {"reversed": 2, "clawback_debited": 1000})
        self.assertEqual(self.balance(), 0)
        refund = TokenTransaction.objects.get(reason="refund", meta__order_id=payment.order_id)
        self.assertEqual((int(refund.delta), refund.meta["credited"]), (-1000, 1000))
        payment.refresh_from_db()
        self.assertTrue(payment.response["token_purchase_clawed_back"])
        self.assertRefused("already_marked", self.mark, payment, clawback_credits=True)
        self.assertEqual(self.balance(), 0)

    def test_followup_clawback_takes_back_every_crypto_part(self):
        payment = f.make_payment(self.buyer, provider="crypto_nowpayments", amount="10.00",
                                 tokens=1000, success=False)
        invoice = crypto_invoice(payment)
        pay_crypto(invoice, "5.25", crypto_base.PARTIALLY_PAID)
        pay_crypto(invoice, "10.5")
        self.mark(payment)
        self.assertEqual(self.mark(payment, clawback_credits=True)["clawback_debited"], 1000)
        self.assertEqual(self.balance(), 0)

    def test_followup_clawback_once(self):
        payment = self.paid()
        self.mark(payment)
        # Сначала отметили без изъятия, теперь решили забрать кредиты.
        result = self.mark(payment, clawback_credits=True, reason="кредиты тоже вернуть")
        self.assertEqual(result, {"reversed": 0, "clawback_debited": 500})
        self.assertEqual(self.states(payment), [("reversed", "refund:admin")])
        payment.refresh_from_db()
        self.assertEqual(payment.response["admin_refund"]["clawback"], True)
        self.assertEqual((payment.success, payment.error), (False, "refunded"))
        self.assertEqual(self.balance(), 0)

        first, second = self.logs()
        self.assertEqual(second.after["followup"], True)
        self.assertEqual(second.after["clawback_credits"], True)
        self.assertEqual(second.creator_id, self.creator.pk)
        # Третий раз — уже нельзя.
        self.assertRefused("already_marked", self.mark, payment, clawback_credits=True)
        self.assertRefused("already_marked", self.mark, payment)
        self.assertEqual(self.logs().count(), 2)

    def test_any_other_second_call_is_refused(self):
        payment = self.paid()
        self.mark(payment)
        self.assertRefused("already_marked", self.mark, payment)
        self.assertRefused("already_marked", self.mark, payment, kind="fraud")
        clawed = self.paid()
        self.mark(clawed, clawback_credits=True)
        self.assertRefused("already_marked", self.mark, clawed, clawback_credits=True)
        self.assertEqual(self.logs().count(), 2)

    def test_validation(self):
        payment = self.paid()
        self.assertRefused("kind_invalid", self.mark, payment, kind="chargeback")
        self.assertRefused("reason_required", self.mark, payment, reason="  ")
        self.assertRefused("not_found", commission.mark_payment_refunded, 10 ** 9,
                           kind="refund", actor=self.admin, reason="x")
        self.assertEqual(self.states(payment), [("accrued", "")])
        self.assertEqual(self.logs().count(), 0)

    def test_payment_without_commission(self):
        payment = f.make_payment(f.make_user())
        self.assertEqual(self.mark(payment), {"reversed": 0, "clawback_debited": 0})
        log = self.logs().get()
        self.assertIsNone(log.creator_id)
        self.assertEqual(log.after["reversed"], 0)

    def test_a_missed_reversal_is_picked_up_by_the_safety_net(self):
        payment = self.paid()
        with patch("creators.commission.reverse_for_payment", return_value=0):
            self.assertEqual(self.mark(payment, kind="fraud")["reversed"], 0)
        self.assertEqual(self.states(payment), [("accrued", "")])
        self.assertEqual(tasks.commission_safety_net()["reversed"], 1)
        self.assertEqual(self.states(payment), [("reversed", "fraud")])

    def test_wrong_mark_is_undone_by_restore(self):
        payment = self.paid()
        self.mark(payment)
        row = self.rows(payment)[0]
        commission.restore(row.pk, actor=self.admin, reason="мисклик", clear_admin_refund=True)
        self.assertEqual(self.states(payment), [("accrued", "restored")])
        # Страховка восстановленную комиссию больше не трогает.
        self.assertEqual(tasks.commission_safety_net()["reversed"], 0)
        self.assertEqual(self.states(payment), [("accrued", "restored")])


# ------------------------------------------------------- блокировки [pg] ---

@skipUnless(connection.vendor == "postgresql", "блокировки строк есть только в PostgreSQL")
class RefundAndPurchaseInParallelTests(f.CreatorsTransactionTestCase):
    def test_credit_of_one_order_and_refund_of_another_do_not_deadlock(self):
        creator = f.make_creator()
        buyer = f.make_user()
        f.make_referral(creator, buyer)
        errors = []

        def run(fn, payment):
            try:
                fn(payment)
            except Exception as exc:  # noqa: BLE001
                errors.append(repr(exc))
            finally:
                connection.close()

        # Заглушки ставит главный поток: два потока, которые одновременно ставят и
        # снимают одну и ту же подмену, могут оставить её навсегда.
        for target in ("creators.notify.emit", "botapi.tasks.notify",
                       "payments.views._notify_balance_topup"):
            patcher = patch(target)
            patcher.start()
            self.addCleanup(patcher.stop)

        for _ in range(10):
            to_refund = f.make_payment(buyer, success=False)
            pay_postback(to_refund)
            to_credit = f.make_payment(buyer, success=False)
            threads = [threading.Thread(target=run, args=(refund_postback, to_refund)),
                       threading.Thread(target=run, args=(pay_postback, to_credit))]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join(30)
            self.assertFalse(any(thread.is_alive() for thread in threads))
            self.assertEqual(errors, [])
            self.assertEqual(CreatorCommission.objects.get(payment=to_refund).status, "reversed")
            self.assertEqual(CreatorCommission.objects.get(payment=to_credit).status, "accrued")
