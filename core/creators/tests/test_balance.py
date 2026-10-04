"""Баланс креатора: считается из строк комиссий и выводов, в таблицах его нет."""
from datetime import timedelta
from decimal import Decimal

from django.utils import timezone

from .. import balance
from ..models import CreatorCommission
from . import factories as f

D = Decimal


class BalanceTests(f.CreatorsTestCase):
    def setUp(self):
        super().setUp()
        self.creator = f.make_creator()

    def summary(self, **kwargs):
        return balance.summary(self.creator, **kwargs)

    def assertIdentity(self, b):
        # «Заработано всего» = «Ожидает» + «Доступно» + «Выплачено» (пока нет долга).
        self.assertEqual(b.debt, D("0"))
        self.assertEqual(b.earned, b.pending + b.available + b.paid)

    def test_empty(self):
        b = self.summary()
        for name in ("earned", "pending", "held", "available", "in_withdrawal", "paid", "debt",
                     "available_raw"):
            self.assertEqual(getattr(b, name), D("0"), name)
        self.assertIdentity(b)

    def test_formulas(self):
        # Доступно: 30 + 25. В холде: 12.5. Придержано: 7. Отменено и аннулировано — мимо.
        f.make_commission(self.creator, amount="30.000000", base="300", available_in_days=-1)
        f.make_commission(self.creator, amount="25.000000", base="250", available_in_days=-10)
        f.make_commission(self.creator, amount="12.500000", base="125", available_in_days=5)
        f.make_commission(self.creator, amount="7.000000", base="70", status="held",
                          reason="creator_blocked")
        f.make_commission(self.creator, amount="99.000000", base="990", status="reversed",
                          available_in_days=-1)
        f.make_commission(self.creator, amount="50.000000", base="500", status="void",
                          reason="admin_void")
        f.make_withdrawal(self.creator, "20.00", status="paid")
        f.make_withdrawal(self.creator, "15.00", status="review")
        f.make_withdrawal(self.creator, "40.00", status="rejected")

        b = self.summary()
        self.assertEqual(b.earned, D("67.500000"))            # 30 + 25 + 12.5
        self.assertEqual(b.held, D("7.000000"))               # отдельно, не в earned
        self.assertEqual(b.in_withdrawal, D("15.000000"))
        self.assertEqual(b.paid, D("20.000000"))
        self.assertEqual(b.pending, D("27.500000"))           # 12.5 в холде + 15 запрошено
        self.assertEqual(b.available_raw, D("20.000000"))     # 55 − 15 − 20
        self.assertEqual(b.available, D("20.000000"))
        self.assertIdentity(b)

    def test_other_creators_rows_are_not_counted(self):
        other = f.make_creator()
        f.make_commission(other, amount="30.000000", base="300", available_in_days=-1)
        f.make_withdrawal(other, "10.00", status="paid")
        self.assertEqual(self.summary().earned, D("0"))
        self.assertEqual(self.summary().paid, D("0"))
        self.assertEqual(balance.summary(other).earned, D("30.000000"))

    def test_summary_accepts_a_pk(self):
        f.make_commission(self.creator, amount="3.000000", base="30", available_in_days=-1)
        self.assertEqual(balance.summary(self.creator.pk).available, D("3.000000"))

    def test_hold_boundary_is_inclusive(self):
        row = f.make_commission(self.creator, amount="10.000000", base="100")
        at = row.available_at
        before = self.summary(now=at - timedelta(microseconds=1))
        self.assertEqual((before.available, before.pending), (D("0"), D("10.000000")))
        exactly = self.summary(now=at)
        self.assertEqual((exactly.available, exactly.pending), (D("10.000000"), D("0")))
        self.assertIdentity(before)
        self.assertIdentity(exactly)

    def test_reversal_after_payout_makes_a_debt(self):
        row = f.make_commission(self.creator, amount="30.000000", base="300", available_in_days=-1)
        f.make_withdrawal(self.creator, "30.00", status="paid")
        self.assertEqual(self.summary().available, D("0"))

        # Возврат оплаты уже после выплаты: комиссия отменена, деньги у креатора.
        CreatorCommission.objects.filter(pk=row.pk).update(status="reversed",
                                                           reversed_at=timezone.now())
        b = self.summary()
        self.assertEqual(b.available_raw, D("-30.000000"))
        self.assertEqual((b.available, b.debt), (D("0"), D("30.000000")))
        self.assertEqual((b.earned, b.paid), (D("0"), D("30.000000")))

        # Следующие комиссии сначала гасят долг.
        f.make_commission(self.creator, amount="12.000000", base="120", available_in_days=-1)
        b = self.summary()
        self.assertEqual((b.available, b.debt), (D("0"), D("18.000000")))
        f.make_commission(self.creator, amount="25.000000", base="250", available_in_days=-1)
        b = self.summary()
        self.assertEqual((b.available, b.debt, b.available_raw),
                         (D("7.000000"), D("0"), D("7.000000")))
        self.assertIdentity(b)

    def test_commission_on_hold_does_not_pay_the_debt_yet(self):
        row = f.make_commission(self.creator, amount="10.000000", base="100", available_in_days=-1)
        f.make_withdrawal(self.creator, "10.00", status="paid")
        CreatorCommission.objects.filter(pk=row.pk).update(status="reversed")
        f.make_commission(self.creator, amount="4.000000", base="40", available_in_days=14)
        self.assertEqual(self.summary().debt, D("10.000000"))
        later = self.summary(now=timezone.now() + timedelta(days=15))
        self.assertEqual(later.debt, D("6.000000"))

    def test_open_withdrawal_reserves_the_money(self):
        f.make_commission(self.creator, amount="50.000000", base="500", available_in_days=-1)
        for status in ("review", "approved"):
            with self.subTest(status=status):
                withdrawal = f.make_withdrawal(self.creator, "20.00", status=status)
                b = self.summary()
                self.assertEqual((b.available, b.in_withdrawal, b.pending),
                                 (D("30.000000"), D("20.000000"), D("20.000000")))
                self.assertIdentity(b)
                withdrawal.delete()

    def test_small_amounts_are_summed_exactly(self):
        # Суммы SQLite отдаёт дробным числом: 0.1 + 0.2 не должно стать 0.30000000000000004.
        for amount in ("0.100000", "0.200000", "0.000001"):
            f.make_commission(self.creator, amount=amount, base="10", available_in_days=-1)
        self.assertEqual(self.summary().earned, D("0.300001"))

    def test_as_json_rounds_down_and_hides_raw(self):
        f.make_commission(self.creator, amount="10.999999", base="100", available_in_days=-1)
        f.make_commission(self.creator, amount="0.019999", base="10", status="held",
                          reason="creator_blocked")
        data = balance.as_json(self.summary())
        self.assertEqual(set(data), {"earned", "pending", "held", "available", "in_withdrawal",
                                     "paid", "debt"})
        # Вниз: показать больше, чем есть, нельзя.
        self.assertEqual(data["earned"], "10.99")
        self.assertEqual(data["available"], "10.99")
        self.assertEqual(data["held"], "0.01")
        self.assertEqual(data["pending"], "0.00")
        self.assertTrue(all(isinstance(value, str) for value in data.values()))

    def test_earned_bulk(self):
        other, empty = f.make_creator(), f.make_creator()
        f.make_commission(self.creator, amount="1.500000", base="15")
        f.make_commission(self.creator, amount="2.250000", base="20", available_in_days=-1)
        f.make_commission(self.creator, amount="9.000000", base="90", status="held",
                          reason="creator_blocked")
        f.make_commission(other, amount="4.000000", base="40")
        with self.assertNumQueries(1):
            result = balance.earned_bulk([self.creator.pk, other.pk, empty.pk])
        self.assertEqual(result, {self.creator.pk: D("3.750000"), other.pk: D("4.000000"),
                                  empty.pk: D("0")})
        self.assertEqual(balance.earned_bulk([]), {})

    def test_lock_returns_the_creator_with_level_and_user(self):
        locked = balance.lock(self.creator.pk)
        with self.assertNumQueries(0):
            self.assertEqual(locked.level.key, "creator")
            self.assertEqual(locked.user.pk, self.creator.user_id)
