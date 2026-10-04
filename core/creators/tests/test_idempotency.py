"""Одна комиссия на (платёж, часть): повторы уведомлений, сверка и дозачисление не удваивают."""
import threading
from decimal import Decimal
from unittest import skipUnless
from unittest.mock import patch

from django.db import connection

from payments.crypto import base as crypto_base
from plans.models import TokenTransaction

from .. import commission, tasks
from ..models import CreatorCommission
from . import factories as f
from .test_commission import (
    MoneyTestCase,
    crypto_invoice,
    pay_crypto,
    pay_postback,
    pay_reconcile,
    pay_stars,
    pay_yookassa,
    star_invoice,
)

D = Decimal


class IdempotencyTests(MoneyTestCase):
    def setUp(self):
        super().setUp()
        self.creator, self.buyer, self.referral = self.bound()

    def purchases(self, payment):
        return TokenTransaction.objects.filter(reason="purchase",
                                               meta__order_id=payment.order_id).count()

    def assertOnce(self, payment, amount):
        rows = self.rows(payment)
        self.assertEqual([(row.part, row.status, row.amount_usdt) for row in rows],
                         [("", "accrued", D(amount))])
        self.assertEqual(self.purchases(payment), 1)

    def test_same_postback_twice(self):
        payment = f.make_payment(self.buyer, amount="490.00", success=False)
        pay_postback(payment)
        pay_postback(payment)
        self.assertOnce(payment, "0.563500")
        self.assertEqual(len(self.emitted("commission_accrued")), 1)

    def test_postback_then_reconcile(self):
        payment = f.make_payment(self.buyer, amount="490.00", success=False)
        pay_postback(payment)
        self.assertEqual(pay_reconcile(payment), "already")
        self.assertOnce(payment, "0.563500")

    def test_reconcile_then_postback(self):
        payment = f.make_payment(self.buyer, amount="490.00", success=False)
        self.assertEqual(pay_reconcile(payment), "credited")
        self.assertEqual(pay_reconcile(payment), "already")
        pay_postback(payment)
        self.assertOnce(payment, "0.563500")

    def test_yookassa_webhook_twice(self):
        payment = f.make_payment(self.buyer, provider="yookassa", amount="520.00",
                                 kgs_price="490.00", success=False)
        self.assertEqual(pay_yookassa(payment), "credited")
        pay_yookassa(payment)
        self.assertOnce(payment, "0.563500")

    def test_stars_confirmation_twice(self):
        payment = f.make_payment(self.buyer, provider="telegram_stars", amount="385",
                                 success=False)
        star_invoice(payment)
        with patch("plans.stars.withdraw_rate", return_value=D("0.013")):
            pay_stars(payment)
            pay_stars(payment)
        self.assertOnce(payment, "0.500500")

    def test_accrue_twice_returns_the_same_row(self):
        payment = f.make_payment(self.buyer)
        first = commission.accrue(payment)
        # Второй вызов ничего не пересчитывает — даже если уровень уже другой.
        self.creator.level = type(self.creator.level).objects.get(key="ambassador")
        self.creator.save(update_fields=["level"])
        second = commission.accrue(payment)
        self.assertEqual(first.pk, second.pk)
        self.assertEqual(second.percent, D("10.00"))
        self.assertEqual(CreatorCommission.objects.count(), 1)

    def test_crypto_same_cumulative_twice_and_two_parts(self):
        payment = f.make_payment(self.buyer, provider="crypto_nowpayments", amount="10.00",
                                 tokens=1000, success=False)
        invoice = crypto_invoice(payment, pay_amount="10.5")
        # Половина суммы — и тот же ответ процессора ещё раз (повтор вебхука).
        self.assertEqual(pay_crypto(invoice, "5.25", crypto_base.PARTIALLY_PAID), "credited")
        self.assertEqual(pay_crypto(invoice, "5.25", crypto_base.PARTIALLY_PAID), "noop")
        self.assertEqual([(row.part, row.base_usd, row.amount_usdt) for row in self.rows(payment)],
                         [("500", D("5.000000"), D("0.500000"))])
        # Доплата: вторая часть — вторая строка. И снова повтор.
        self.assertEqual(pay_crypto(invoice, "10.5"), "credited")
        self.assertEqual(pay_crypto(invoice, "10.5"), "noop")
        self.assertEqual([(row.part, row.base_usd, row.amount_usdt) for row in self.rows(payment)],
                         [("500", D("5.000000"), D("0.500000")),
                          ("1000", D("5.000000"), D("0.500000"))])
        self.assertEqual(self.purchases(payment), 2)
        # «Новый платящий» — один раз на человека, а не на часть.
        self.assertEqual(len(self.emitted("new_paying_user")), 1)

    def test_hook_racing_the_backfill(self):
        # Дозачисление находит покупку в тот момент, когда хук оплаты уже решил
        # вставить строку, но ещё не вставил: вторую строку не пускает индекс.
        payment = f.make_payment(self.buyer, amount="490.00", success=False)
        real_insert = commission._insert
        seen = {}

        def racing_insert(fields):
            if "entered" not in seen:
                seen["entered"] = True
                seen["backfill"] = tasks.backfill_commissions()
            return real_insert(fields)

        with patch("creators.commission._insert", side_effect=racing_insert):
            pay_postback(payment)
        self.assertEqual(seen["backfill"], {"status": "ok", "checked": 1, "accrued": 1})
        self.assertOnce(payment, "0.563500")
        self.assertEqual(len(self.emitted("commission_accrued")), 1)
        # Покупка при этом не пострадала.
        self.buyer.refresh_from_db()
        self.assertEqual(self.buyer.token_balance, 500)

    def test_backfill_after_the_hook_adds_nothing(self):
        payment = f.make_payment(self.buyer, amount="490.00", success=False)
        pay_postback(payment)
        self.assertEqual(tasks.backfill_commissions(), {"status": "ok", "checked": 1, "accrued": 0})
        self.assertOnce(payment, "0.563500")


@skipUnless(connection.vendor == "postgresql", "блокировки строк есть только в PostgreSQL")
class ParallelAccrualTests(f.CreatorsTransactionTestCase):
    def test_two_threads_one_row(self):
        creator = f.make_creator()
        buyer = f.make_user()
        f.make_referral(creator, buyer)
        payment = f.make_payment(buyer)
        barrier = threading.Barrier(2)
        results = []

        def worker():
            try:
                barrier.wait(10)
                row = commission.accrue(payment)
                results.append(row.pk if row else None)
            finally:
                connection.close()

        threads = [threading.Thread(target=worker) for _ in range(2)]
        # Заглушку ставит главный поток — одна на оба рабочих.
        with patch("creators.notify.emit"):
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join()
        row = CreatorCommission.objects.get(payment=payment)
        self.assertEqual(results, [row.pk, row.pk])
