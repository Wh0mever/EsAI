"""Фоновые задачи программы: страховка возвратов, дозачисление, очередь опроса провайдеров."""
import uuid
from datetime import timedelta
from decimal import Decimal
from unittest.mock import patch

from django.core.cache import cache
from django.test import override_settings
from django.utils import timezone

from audit.models import EventLog
from payments.models import CryptoInvoice, Payment, StarInvoice
from plans.models import TokenTransaction

from .. import checks, tasks
from ..models import CreatorCommission, CreatorReferral
from . import factories as f
from .test_commission import MoneyTestCase, crypto_invoice, pay_postback, star_invoice

D = Decimal


class SafetyNetTests(MoneyTestCase):
    def setUp(self):
        super().setUp()
        self.creator, self.buyer, self.referral = self.bound()

    def commissioned(self, **kwargs):
        payment = f.make_payment(self.buyer, **kwargs)
        f.make_commission(self.creator, payment, buyer=self.buyer)
        return payment

    def state(self, payment):
        row = CreatorCommission.objects.get(payment=payment)
        return row.status, row.reason

    def test_every_marker_is_reversed(self):
        cases = {
            "refund:admin_refund": {"response": {"admin_refund": {"kind": "refund"}}},
            "fraud": {"response": {"admin_refund": {"kind": "fraud"}}},
            "refund:clawback": {"response": {"token_purchase_clawed_back": True}},
            "refund:yookassa": {"response": {"yookassa_refunded": {"amount": "1.00"}}},
            "refund:freedompay": {"response": {"freedompay_refunded": {"status": "refunded"}}},
            "refund:error_flag": {"error": "refunded"},
            "refund:clawback_failed": {"error": "token_clawback_failed:wallet down"},
        }
        payments = {}
        for reason, fields in cases.items():
            payment = self.commissioned()
            Payment.objects.filter(pk=payment.pk).update(**fields)
            payments[reason] = payment
        # Признаки, которые лежат не в самом платеже, а в счёте.
        stars = self.commissioned(provider="telegram_stars", amount="385")
        star_invoice(stars, status=StarInvoice.STATUS_REFUNDED)
        payments["refund:stars"] = stars
        stars_flag = self.commissioned(provider="telegram_stars", amount="385")
        Payment.objects.filter(pk=stars_flag.pk).update(error="stars_refunded")
        crypto = self.commissioned(provider="crypto_nowpayments", amount="10.00")
        CryptoInvoice.objects.filter(pk=crypto_invoice(crypto).pk).update(status="refunded")
        crypto_flag = self.commissioned(provider="crypto_nowpayments", amount="10.00")
        CryptoInvoice.objects.filter(pk=crypto_invoice(crypto_flag).pk).update(
            flags={"refund_seen": True, "needs_review": "refunded"})
        clean = self.commissioned()

        result = tasks.commission_safety_net()
        self.assertEqual(result, {"status": "ok", "checked": len(cases) + 4,
                                  "reversed": len(cases) + 4})
        for reason, payment in payments.items():
            self.assertEqual(self.state(payment), ("reversed", reason), reason)
        self.assertEqual(self.state(stars_flag), ("reversed", "refund:error_flag"))
        self.assertEqual(self.state(crypto), ("reversed", "refund:crypto"))
        self.assertEqual(self.state(crypto_flag), ("reversed", "refund:crypto"))
        # Платёж без признака возврата страховка не трогает.
        self.assertEqual(self.state(clean), ("accrued", ""))
        # Второй проход: набор пуст.
        self.assertEqual(tasks.commission_safety_net(),
                         {"status": "ok", "checked": 0, "reversed": 0})

    def test_stars_refund_of_a_payment_without_user(self):
        # botapi.stars.mark_refunded не зовёт изъятие кредитов, когда покупателя у
        # платежа уже нет, — значит, и хук отмены комиссии не срабатывает.
        payment = self.commissioned(provider="telegram_stars", amount="385")
        star_invoice(payment, status=StarInvoice.STATUS_REFUNDED)
        Payment.objects.filter(pk=payment.pk).update(user=None, error="stars_refunded")
        self.assertEqual(tasks.commission_safety_net()["reversed"], 1)
        self.assertEqual(self.state(payment), ("reversed", "refund:stars"))

    def test_held_rows_and_every_part_are_reversed(self):
        payment = f.make_payment(self.buyer, provider="crypto_nowpayments", amount="10.00")
        f.make_commission(self.creator, payment, part="500")
        f.make_commission(self.creator, payment, part="1000", status="held",
                          reason="creator_blocked")
        f.make_commission(self.creator, payment, part="x", status="void", reason="admin_void")
        Payment.objects.filter(pk=payment.pk).update(error="refunded")
        self.assertEqual(tasks.commission_safety_net(),
                         {"status": "ok", "checked": 1, "reversed": 2})
        self.assertEqual(sorted(CreatorCommission.objects.filter(payment=payment)
                                .values_list("part", "status")),
                         [("1000", "reversed"), ("500", "reversed"), ("x", "void")])

    def test_works_in_every_mode(self):
        payment = self.commissioned()
        Payment.objects.filter(pk=payment.pk).update(error="refunded")
        with override_settings(CREATORS_MODE="off"):
            self.assertEqual(tasks.commission_safety_net()["reversed"], 1)

    def test_busy_while_another_run_holds_the_lock(self):
        cache.add("creators:commission_safety_net:lock", "1", timeout=60)
        self.assertEqual(tasks.commission_safety_net(), {"status": "busy"})
        cache.delete("creators:commission_safety_net:lock")
        self.assertEqual(tasks.commission_safety_net()["status"], "ok")
        # Замок снят после прогона: следующий запуск не «занят».
        self.assertEqual(tasks.commission_safety_net()["status"], "ok")

    def test_one_broken_payment_does_not_stop_the_run(self):
        first, second = self.commissioned(), self.commissioned()
        Payment.objects.filter(pk__in=[first.pk, second.pk]).update(error="refunded")
        real = tasks.commission.refund_marker

        def flaky(payment):
            if payment.pk == first.pk:
                raise RuntimeError("битый платёж")
            return real(payment)

        with patch("creators.commission.refund_marker", side_effect=flaky):
            result = tasks.commission_safety_net()
        self.assertEqual(result, {"status": "ok", "checked": 2, "reversed": 1})
        self.assertEqual(self.state(second), ("reversed", "refund:error_flag"))


class BackfillTests(MoneyTestCase):
    def setUp(self):
        super().setUp()
        self.creator, self.buyer, self.referral = self.bound(
            bound_at=timezone.now() - timedelta(days=60))

    def purchase(self, days_ago=0, **kwargs):
        """Покупка без комиссии: кредиты начислены, хук начисления «не сработал»."""
        payment = f.make_payment(self.buyer, amount="490.00", **kwargs)
        f.credit_purchase(payment)
        if days_ago:
            TokenTransaction.objects.filter(meta__order_id=payment.order_id).update(
                created_at=timezone.now() - timedelta(days=days_ago))
        return payment

    def test_missing_row_is_created(self):
        payment = self.purchase()
        self.assertEqual(tasks.backfill_commissions(), {"status": "ok", "checked": 1, "accrued": 1})
        row = CreatorCommission.objects.get(payment=payment)
        self.assertEqual((row.status, row.amount_usdt, row.creator_id, row.part),
                         ("accrued", D("0.563500"), self.creator.pk, ""))
        # Повторный проход ничего не добавляет.
        self.assertEqual(tasks.backfill_commissions(), {"status": "ok", "checked": 1, "accrued": 0})
        self.assertEqual(CreatorCommission.objects.count(), 1)

    def test_existing_and_refunded_are_skipped(self):
        existing = self.purchase()
        f.make_commission(self.creator, existing, buyer=self.buyer, status="void",
                          reason="admin_void")
        refunded = self.purchase()
        Payment.objects.filter(pk=refunded.pk).update(error="refunded")
        self.assertEqual(tasks.backfill_commissions(), {"status": "ok", "checked": 2, "accrued": 0})
        self.assertEqual(CreatorCommission.objects.count(), 1)

    def test_purchases_without_order_or_payment_are_skipped(self):
        from plans.wallet import credit_tokens

        credit_tokens(self.buyer, 100, "purchase", meta={})
        credit_tokens(self.buyer, 100, "purchase", meta={"order_id": "tokpkg-ghost"})
        stranger = f.make_user()
        credit_tokens(stranger, 100, "purchase", meta={"order_id": "tokpkg-stranger"})
        self.assertEqual(tasks.backfill_commissions(), {"status": "ok", "checked": 2, "accrued": 0})

    def test_purchase_whose_payment_belongs_to_another_user_is_skipped(self):
        # След слияния аккаунтов: запись леджера осталась у одного человека, а
        # платёж с тем же номером заказа — у другого. Комиссию тут не начисляем.
        payment = self.purchase()
        Payment.objects.filter(pk=payment.pk).update(user=f.make_user())
        self.assertEqual(tasks.backfill_commissions(), {"status": "ok", "checked": 1, "accrued": 0})
        self.assertEqual(CreatorCommission.objects.count(), 0)
        # Платёж вернулся к покупателю — та же покупка доначисляется.
        Payment.objects.filter(pk=payment.pk).update(user=self.buyer)
        self.assertEqual(tasks.backfill_commissions()["accrued"], 1)

    def test_crypto_parts(self):
        payment = f.make_payment(self.buyer, provider="crypto_nowpayments", amount="10.00",
                                 tokens=1000)
        f.credit_purchase(payment, credited=400, idem="400")
        f.credit_purchase(payment, credited=600, idem="1000")
        f.make_commission(self.creator, payment, buyer=self.buyer, part="400",
                          amount="0.400000", base="4.000000")
        self.assertEqual(tasks.backfill_commissions(), {"status": "ok", "checked": 2, "accrued": 1})
        row = CreatorCommission.objects.get(payment=payment, part="1000")
        self.assertEqual((row.base_usd, row.amount_usdt), (D("6.000000"), D("0.600000")))

    def test_disabled_when_the_program_is_off(self):
        self.purchase()
        with override_settings(CREATORS_MODE="off"):
            self.assertEqual(tasks.backfill_commissions(), {"status": "disabled"})
        self.assertEqual(CreatorCommission.objects.count(), 0)
        with override_settings(CREATORS_MODE="staff"):
            self.assertEqual(tasks.backfill_commissions()["accrued"], 1)

    def test_window(self):
        inside = self.purchase(days_ago=6)
        outside = self.purchase(days_ago=8)
        self.assertEqual(tasks.backfill_commissions(), {"status": "ok", "checked": 1, "accrued": 1})
        self.assertTrue(CreatorCommission.objects.filter(payment=inside).exists())
        self.assertFalse(CreatorCommission.objects.filter(payment=outside).exists())
        # Оператор после сбоя проходит окно шире.
        self.assertEqual(tasks.backfill_commissions(days=30)["accrued"], 1)
        self.assertTrue(CreatorCommission.objects.filter(payment=outside).exists())

    def test_days_are_clamped(self):
        ancient = self.purchase(days_ago=100)
        recent = self.purchase(days_ago=2)
        # 0 и мусор — это не «всё время» и не «ничего»: минимум сутки, по умолчанию 7.
        self.assertEqual(tasks.backfill_commissions(days=0)["checked"], 0)
        self.assertEqual(tasks.backfill_commissions(days="мусор")["accrued"], 1)
        self.assertTrue(CreatorCommission.objects.filter(payment=recent).exists())
        # Больше 90 дней назад задача не смотрит, что бы ни передали.
        self.assertEqual(tasks.backfill_commissions(days=10 ** 6)["accrued"], 0)
        self.assertFalse(CreatorCommission.objects.filter(payment=ancient).exists())

    def test_coverage_is_taken_at_the_purchase_time(self):
        # Привязку сняли вчера, покупка была три дня назад: комиссия положена прежнему креатору.
        payment = self.purchase(days_ago=3)
        CreatorReferral.objects.filter(pk=self.referral.pk).update(
            ended_at=timezone.now() - timedelta(days=1), end_reason="admin_rebind")
        new_creator = f.make_creator()
        f.make_referral(new_creator, self.buyer, source="admin")
        late = self.purchase()

        self.assertEqual(tasks.backfill_commissions()["accrued"], 2)
        self.assertEqual(CreatorCommission.objects.get(payment=payment).creator_id, self.creator.pk)
        self.assertEqual(CreatorCommission.objects.get(payment=late).creator_id, new_creator.pk)

    def test_purchase_before_the_binding_is_not_attributed(self):
        creator, buyer, referral = self.bound()
        payment = f.make_payment(buyer)
        f.credit_purchase(payment)
        TokenTransaction.objects.filter(meta__order_id=payment.order_id).update(
            created_at=timezone.now() - timedelta(days=2))
        self.assertEqual(tasks.backfill_commissions()["accrued"], 0)
        self.assertFalse(CreatorCommission.objects.filter(payment=payment).exists())

    def test_old_miss_behind_a_thousand_newer_purchases_is_found(self):
        # Срез «последние 1000 покупок» почти весь состоял бы из уже начисленных —
        # и до старого пропуска очередь не дошла бы никогда.
        missed = self.purchase(days_ago=6)
        now = timezone.now()
        payments = Payment.objects.bulk_create([
            Payment(user=self.buyer, provider="freedompay", amount=D("490.00"), currency="KGS",
                    order_id=f"tokpkg-{self.buyer.pk}-1-bulk{n:05d}", success=True,
                    request={"token_purchase": {"package_id": 1, "tokens": 500, "bonus_tokens": 0}},
                    response={})
            for n in range(1001)])
        TokenTransaction.objects.bulk_create([
            TokenTransaction(user=self.buyer, delta=500, reason="purchase", balance_after=0,
                             meta={"order_id": payment.order_id})
            for payment in payments])
        CreatorCommission.objects.bulk_create([
            CreatorCommission(creator=self.creator, referral=self.referral, buyer=self.buyer,
                              buyer_pk=self.buyer.pk, payment=payment, order_id=payment.order_id,
                              provider="freedompay", paid_amount=D("490.00"), paid_currency="KGS",
                              rate_to_usd=D("0.0115"), rate_source="test", base_usd=D("5.635"),
                              level_key="creator", percent=D("10.00"), amount_usdt=D("0.5635"),
                              status="accrued", available_at=now + timedelta(days=14))
            for payment in payments])

        result = tasks.backfill_commissions()
        self.assertEqual(result, {"status": "ok", "checked": 1002, "accrued": 1})
        self.assertTrue(CreatorCommission.objects.filter(payment=missed).exists())

    def test_real_hook_failure_is_repaired(self):
        payment = f.make_payment(self.buyer, amount="490.00", success=False)
        with patch("creators.commission._insert", side_effect=RuntimeError("boom")):
            pay_postback(payment)
        self.assertEqual(CreatorCommission.objects.count(), 0)
        self.assertEqual(tasks.backfill_commissions()["accrued"], 1)
        row = CreatorCommission.objects.get(payment=payment)
        self.assertEqual((row.status, row.amount_usdt), ("accrued", D("0.563500")))


@override_settings(YOOKASSA_SHOP_ID="shop", YOOKASSA_SECRET_KEY="key")
class PollQueueTests(MoneyTestCase):
    """Очередь опроса возвратов: срочные всегда в проходе, остальные — по кругу."""

    def setUp(self):
        super().setUp()
        self.creator, self.buyer, self.referral = self.bound()
        self.now = timezone.now()

    def row(self, *, checked_ago=None, available_in_days=14, provider="yookassa", creator=None,
            **commission):
        payment = f.make_payment(self.buyer, provider=provider, amount="520.00",
                                 yookassa_payment_id=f"yk-{uuid.uuid4().hex[:12]}")
        row = f.make_commission(creator or self.creator, payment, buyer=self.buyer,
                                available_in_days=available_in_days, **commission)
        if checked_ago is not None:
            CreatorCommission.objects.filter(pk=row.pk).update(
                refund_checked_at=self.now - checked_ago)
        return row

    def ids(self, rows):
        return [row.pk for row in rows]

    def test_never_checked_first_then_the_oldest_check(self):
        recent = self.row(checked_ago=timedelta(hours=1))
        old = self.row(checked_ago=timedelta(days=3))
        never_2 = self.row()
        older = self.row(checked_ago=timedelta(days=9))
        never_1 = self.row()
        # never_2 создан раньше never_1 — при равных условиях порядок по id.
        self.assertEqual(self.ids(tasks._poll_candidates("yookassa")),
                         self.ids([never_2, never_1, older, old, recent]))

    def test_only_open_rows_of_this_provider_within_the_window(self):
        mine = self.row()
        self.row(provider="freedompay")
        self.row(status="reversed")
        self.row(status="void", reason="admin_void")
        held = self.row(status="held", reason="creator_blocked")
        ancient = self.row()
        CreatorCommission.objects.filter(pk=ancient.pk).update(
            created_at=self.now - timedelta(days=181))
        self.assertEqual(self.ids(tasks._poll_candidates("yookassa")), self.ids([mine, held]))

    def test_urgent_rows_are_always_in_the_run(self):
        # Очередь длиннее прохода, и всё уже проверялось; срочные стоят в самом хвосте.
        filler = [self.row(checked_ago=timedelta(days=20 - n)) for n in range(6)]
        maturing = self.row(checked_ago=timedelta(hours=7), available_in_days=0.5)
        payout_creator = f.make_creator()
        requested = self.row(checked_ago=timedelta(hours=8), creator=payout_creator)
        f.make_withdrawal(payout_creator, "10.00", status="approved")
        # Срочная, но спрошенная меньше шести часов назад — ждёт своей очереди.
        asked_recently = self.row(checked_ago=timedelta(hours=1), available_in_days=0.5)
        matured = self.row(checked_ago=timedelta(hours=9), available_in_days=-1)

        picked = self.ids(tasks._poll_candidates("yookassa", per_run=4))
        self.assertEqual(picked[:2], self.ids([requested, maturing]))
        self.assertEqual(picked[2:], self.ids(filler[:2]))
        self.assertNotIn(asked_recently.pk, picked)
        self.assertNotIn(matured.pk, picked)

    def test_urgent_rows_may_exceed_the_run_size(self):
        urgent = [self.row(available_in_days=0.5) for _ in range(5)]
        self.row(checked_ago=timedelta(days=30))
        self.assertEqual(self.ids(tasks._poll_candidates("yookassa", per_run=3)), self.ids(urgent))

    def test_two_runs_cover_different_rows(self):
        rows = [self.row() for _ in range(5)]
        answer = {"status": "succeeded", "paid": True}
        with patch.object(tasks, "POLL_PER_RUN", 3),                 patch("payments.yookassa.fetch_payment", return_value=answer) as fetch:
            first = tasks.poll_yookassa_refunds()
            first_asked = {call.args[0] for call in fetch.call_args_list}
            fetch.reset_mock()
            second = tasks.poll_yookassa_refunds()
            second_asked = {call.args[0] for call in fetch.call_args_list}
        self.assertEqual((first["checked"], second["checked"]), (3, 3))
        expected = [row.payment.request["yookassa_payment_id"] for row in rows]
        self.assertEqual(first_asked, set(expected[:3]))
        # Второй проход начинает с тех, до кого первый не дошёл.
        self.assertTrue(set(expected[3:]) <= second_asked)
        self.assertEqual(CreatorCommission.objects.filter(refund_checked_at__isnull=True).count(), 0)

    def test_stamp_is_written_even_when_the_fetch_fails(self):
        broken, fine = self.row(), self.row()
        broken_id = broken.payment.request["yookassa_payment_id"]

        def fetch(yk_id):
            if yk_id == broken_id:
                raise RuntimeError("timeout")
            return {"status": "succeeded", "paid": True}

        with patch("payments.yookassa.fetch_payment", side_effect=fetch) as mock:
            result = tasks.poll_yookassa_refunds()
        # Сбой одного платежа не останавливает очередь и не оставляет его первым навсегда.
        self.assertEqual(result, {"status": "ok", "checked": 2, "refunded": 0})
        self.assertEqual(mock.call_count, 2)
        for row in (broken, fine):
            row.refresh_from_db()
            self.assertIsNotNone(row.refund_checked_at)
            self.assertEqual(row.status, "accrued")

    def test_rows_that_need_no_request_are_stamped_too(self):
        already = self.row()
        Payment.objects.filter(pk=already.payment_id).update(
            response={"yookassa_refunded": {"amount": "1"}})
        no_id = self.row()
        payment = Payment.objects.get(pk=no_id.payment_id)
        payment.request.pop("yookassa_payment_id")
        payment.save(update_fields=["request"])
        with patch("payments.yookassa.fetch_payment") as fetch:
            tasks.poll_yookassa_refunds()
        fetch.assert_not_called()
        self.assertEqual(CreatorCommission.objects.filter(refund_checked_at__isnull=True).count(), 0)

    def test_crypto_like_parts_ask_the_provider_once(self):
        payment = f.make_payment(self.buyer, provider="yookassa", amount="520.00",
                                 yookassa_payment_id="yk-parts")
        f.make_commission(self.creator, payment, part="a")
        f.make_commission(self.creator, payment, part="b")
        with patch("payments.yookassa.fetch_payment",
                   return_value={"status": "succeeded", "paid": True}) as fetch:
            self.assertEqual(tasks.poll_yookassa_refunds()["checked"], 1)
        fetch.assert_called_once_with("yk-parts")
        self.assertEqual(CreatorCommission.objects.filter(refund_checked_at__isnull=True).count(), 0)


class NightlyCheckTests(MoneyTestCase):
    def test_clean_data_logs_nothing(self):
        creator, buyer, _ = self.bound()
        f.make_commission(creator, f.make_payment(buyer), buyer=buyer)
        self.assertEqual(tasks.nightly_check(), {"status": "ok", "fail": 0, "warn": 0})
        self.assertFalse(EventLog.objects.filter(message__startswith="creators_check").exists())

    def test_violations_are_logged_and_nothing_is_changed(self):
        creator = f.make_creator()
        own = f.make_payment(creator.user)
        row = f.make_commission(creator, own, buyer=creator.user)      # I4: своя покупка
        result = tasks.nightly_check()
        self.assertEqual(result["status"], "ok")
        self.assertGreaterEqual(result["fail"], 1)
        event = EventLog.objects.get(message__startswith="creators_check")
        self.assertEqual(event.level, "error")
        self.assertIn("I4", event.meta["codes"])
        row.refresh_from_db()
        self.assertEqual(row.status, "accrued")

    def test_never_raises(self):
        with patch.object(checks, "run", side_effect=RuntimeError("boom")):
            self.assertEqual(tasks.nightly_check(), {"status": "error"})
