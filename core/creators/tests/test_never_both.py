"""Двух программ сразу не бывает: с заказа платится либо комиссия креатору, либо доля кредитами."""
from decimal import Decimal
from unittest.mock import patch

from django.test import override_settings
from django.utils import timezone

from payments.crypto import base as crypto_base
from payments.referral import pay_referral_share, settle_referral
from plans.models import TokenTransaction

from .. import checks, commission
from ..models import CreatorCommission, CreatorReferral
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


@override_settings(REFERRAL_PERCENT=10)
class NeverBothTests(MoneyTestCase):
    def setUp(self):
        super().setUp()
        self.inviter = f.make_user()

    def referred(self):
        """Обычный приглашённый: только referred_by, креатора нет."""
        buyer = f.make_user()
        buyer.referred_by = self.inviter
        buyer.save(update_fields=["referred_by"])
        return buyer

    def pay_every_way(self, buyer):
        """Пять путей начисления; возвращает {путь: (платёж, начислено кредитов)}."""
        paid = {}
        payment = f.make_payment(buyer, amount="490.00", tokens=500, success=False)
        pay_postback(payment)
        paid["postback"] = (payment, 500)

        payment = f.make_payment(buyer, amount="990.00", tokens=1000, bonus=100, success=False)
        pay_reconcile(payment)
        paid["reconcile"] = (payment, 1100)

        payment = f.make_payment(buyer, provider="yookassa", amount="520.00", kgs_price="490.00",
                                 tokens=500, success=False)
        pay_yookassa(payment)
        paid["yookassa"] = (payment, 500)

        payment = f.make_payment(buyer, provider="crypto_nowpayments", amount="10.00",
                                 tokens=1000, success=False)
        invoice = crypto_invoice(payment, pay_amount="10.5")
        pay_crypto(invoice, "5.25", crypto_base.PARTIALLY_PAID)
        pay_crypto(invoice, "10.5")
        paid["crypto"] = (payment, 1000)

        payment = f.make_payment(buyer, provider="telegram_stars", amount="385", tokens=500,
                                 success=False)
        star_invoice(payment)
        pay_stars(payment)
        paid["stars"] = (payment, 500)
        return paid

    def test_creator_buyer_gives_commission_and_no_share_on_every_path(self):
        # У покупателя есть и обычный пригласивший, и креатор: платится только комиссия.
        creator = f.make_creator()
        buyer = self.referred()
        f.make_referral(creator, buyer, source="admin")
        paid = self.pay_every_way(buyer)

        self.assertEqual(TokenTransaction.objects.filter(reason="referral").count(), 0)
        self.inviter.refresh_from_db()
        self.assertEqual(self.inviter.token_balance, 0)
        for path, (payment, credited) in paid.items():
            with self.subTest(path=path):
                rows = self.rows(payment)
                self.assertEqual(len(rows), 2 if path == "crypto" else 1)
                self.assertTrue(all(row.status == "accrued" and row.creator_id == creator.pk
                                    for row in rows))
                self.assertEqual(sum(int(tx.delta) for tx in TokenTransaction.objects.filter(
                    reason="purchase", meta__order_id=payment.order_id)), credited)

    def test_ordinary_referred_buyer_gets_exactly_todays_share(self):
        buyer = self.referred()
        paid = self.pay_every_way(buyer)

        self.assertEqual(CreatorCommission.objects.count(), 0)
        for path, (payment, credited) in paid.items():
            with self.subTest(path=path):
                shares = list(self.shares(payment.order_id))
                self.assertTrue(all(tx.user_id == self.inviter.pk for tx in shares))
                if path == "crypto":
                    # Две части — две доли, каждая со своей половины.
                    self.assertEqual(sorted(int(tx.delta) for tx in shares), [50, 50])
                    self.assertEqual(sorted(tx.meta["idem"] for tx in shares), ["1000", "500"])
                else:
                    self.assertEqual([int(tx.delta) for tx in shares], [credited * 10 // 100])
                    self.assertNotIn("idem", shares[0].meta)
        self.inviter.refresh_from_db()
        self.assertEqual(self.inviter.token_balance, 50 + 110 + 50 + 100 + 50)

    def test_buyer_without_anyone_gives_nothing(self):
        buyer = f.make_user()
        payment = f.make_payment(buyer, success=False)
        pay_postback(payment)
        self.assertEqual(CreatorCommission.objects.count(), 0)
        self.assertEqual(TokenTransaction.objects.filter(reason="referral").count(), 0)

    def test_settle_referral_answer(self):
        creator = f.make_creator()
        covered = f.make_user()
        f.make_referral(creator, covered)
        cases = ((covered, "commission"), (self.referred(), "referral"), (f.make_user(), "none"))
        for buyer, expected in cases:
            with self.subTest(expected=expected):
                payment = f.make_payment(buyer)
                self.assertEqual(settle_referral(payment, payment.order_id, 500), expected)

    def test_rebound_by_admin_switches_programs_from_the_next_paid_order(self):
        creator = f.make_creator()
        buyer = self.referred()
        before = f.make_payment(buyer, tokens=500, success=False)
        open_order = f.make_payment(buyer, tokens=500, success=False)   # создан до перепривязки
        pay_postback(before)

        f.make_referral(creator, buyer, source="admin")
        pay_postback(open_order)
        after = f.make_payment(buyer, tokens=500, success=False)
        pay_postback(after)

        # Оплачено до перепривязки — обычная доля; после — комиссия и никакой доли.
        self.assertEqual([int(tx.delta) for tx in self.shares(before.order_id)], [50])
        self.assertEqual(self.rows(before), [])
        for payment in (open_order, after):
            self.assertEqual(self.shares(payment.order_id).count(), 0)
            self.assertEqual([row.creator_id for row in self.rows(payment)], [creator.pk])
        # referred_by при этом никто не трогал.
        buyer.refresh_from_db()
        self.assertEqual(buyer.referred_by_id, self.inviter.pk)

    def test_unbound_by_admin_returns_to_the_ordinary_program(self):
        creator = f.make_creator()
        buyer = self.referred()
        referral = f.make_referral(creator, buyer, source="admin")
        CreatorReferral.objects.filter(pk=referral.pk).update(
            ended_at=timezone.now(), end_reason="admin_unbind")
        payment = f.make_payment(buyer, tokens=500, success=False)
        pay_postback(payment)
        self.assertEqual(self.rows(payment), [])
        self.assertEqual([int(tx.delta) for tx in self.shares(payment.order_id)], [50])

    def test_mode_off_always_takes_the_ordinary_path(self):
        creator = f.make_creator()
        buyer = self.referred()
        f.make_referral(creator, buyer, source="admin")
        with override_settings(CREATORS_MODE="off"):
            payment = f.make_payment(buyer, tokens=500, success=False)
            pay_postback(payment)
        self.assertEqual(self.rows(payment), [])
        self.assertEqual([int(tx.delta) for tx in self.shares(payment.order_id)], [50])

    def test_staff_mode_accrues_for_existing_bindings(self):
        creator = f.make_creator()
        buyer = self.referred()
        f.make_referral(creator, buyer, source="admin")
        with override_settings(CREATORS_MODE="staff"):
            payment = f.make_payment(buyer, tokens=500, success=False)
            pay_postback(payment)
        self.assertEqual(len(self.rows(payment)), 1)
        self.assertEqual(self.shares(payment.order_id).count(), 0)

    def test_order_with_a_paid_share_never_gets_a_commission(self):
        # Заказ оплачен при выключенной программе (доля ушла пригласившему), потом
        # программу включили и дозачисление дошло до этой покупки: комиссии нет.
        creator = f.make_creator()
        buyer = self.referred()
        f.make_referral(creator, buyer, source="admin")
        with override_settings(CREATORS_MODE="off"):
            payment = f.make_payment(buyer, tokens=500, success=False)
            pay_postback(payment)
        row = commission.accrue(payment)
        self.assertEqual((row.status, row.reason, row.amount_usdt),
                         ("void", "referral_share_paid", D("0")))
        self.assertEqual(self.shares(payment.order_id).count(), 1)

    def crypto_order_with_first_part_paid(self, buyer):
        payment = f.make_payment(buyer, provider="crypto_nowpayments", amount="10.00",
                                 tokens=1000, success=False)
        invoice = crypto_invoice(payment, pay_amount="10.5")
        pay_crypto(invoice, "5.25", crypto_base.PARTIALLY_PAID)
        self.assertEqual([(row.part, row.status) for row in self.rows(payment)],
                         [("500", "accrued")])
        return payment, invoice

    def test_crypto_part_after_unbind_pays_no_share_on_top_of_a_commission(self):
        # Криптосчёт оплачен наполовину (креатору — комиссия), привязку сняли,
        # пришла доплата. Привязки уже нет, но доля кредитами с того же заказа
        # не платится: правило «не обе программы» действует в обе стороны.
        creator = f.make_creator()
        buyer = self.referred()
        referral = f.make_referral(creator, buyer, source="admin")
        payment, invoice = self.crypto_order_with_first_part_paid(buyer)

        CreatorReferral.objects.filter(pk=referral.pk).update(
            ended_at=timezone.now(), end_reason="admin_unbind")
        pay_crypto(invoice, "10.5")

        self.assertEqual(self.shares(payment.order_id).count(), 0)
        self.assertEqual([(row.part, row.status) for row in self.rows(payment)],
                         [("500", "accrued")])
        # Покупатель своё получил целиком.
        buyer.refresh_from_db()
        self.assertEqual(buyer.token_balance, 1000)
        self.inviter.refresh_from_db()
        self.assertEqual(self.inviter.token_balance, 0)
        self.assertEqual([v for v in checks.run() if v.code == "I3"], [])
        # Следующий заказ того же человека — уже обычная программа.
        later = f.make_payment(buyer, tokens=500, success=False)
        pay_postback(later)
        self.assertEqual([int(tx.delta) for tx in self.shares(later.order_id)], [50])

    def test_crypto_part_after_switching_the_program_off_pays_no_share(self):
        # Проверка не зависит от рубильника программы.
        creator = f.make_creator()
        buyer = self.referred()
        f.make_referral(creator, buyer, source="admin")
        payment, invoice = self.crypto_order_with_first_part_paid(buyer)
        with override_settings(CREATORS_MODE="off"):
            pay_crypto(invoice, "10.5")
        self.assertEqual(self.shares(payment.order_id).count(), 0)
        self.assertEqual(len(self.rows(payment)), 1)

    def test_share_is_paid_when_the_commission_of_the_order_is_not_live(self):
        # Отменённая или аннулированная комиссия места не занимает.
        creator = f.make_creator()
        for status, reason in (("reversed", "refund:crypto"), ("void", "admin_void")):
            with self.subTest(status=status):
                buyer = self.referred()
                payment = f.make_payment(buyer)
                f.make_commission(creator, payment, buyer=buyer, status=status, reason=reason)
                self.assertEqual(settle_referral(payment, payment.order_id, 500), "referral")
        live = f.make_payment(self.referred())
        f.make_commission(creator, live, status="held", reason="creator_blocked")
        self.assertEqual(settle_referral(live, live.order_id, 500), "none")
        self.assertEqual(self.shares(live.order_id).count(), 0)

    def test_broken_commission_lookup_falls_back_to_the_ordinary_program(self):
        buyer = self.referred()
        payment = f.make_payment(buyer, tokens=500, success=False)
        with patch.object(CreatorCommission.objects, "filter", side_effect=RuntimeError("база")):
            pay_postback(payment)
        buyer.refresh_from_db()
        self.assertEqual(buyer.token_balance, 500)
        self.assertEqual([int(tx.delta) for tx in self.shares(payment.order_id)], [50])

    def test_no_share_for_being_your_own_referrer(self):
        # След слияния аккаунтов: человек оказался собственным пригласившим.
        buyer = f.make_user()
        buyer.referred_by = buyer
        buyer.save(update_fields=["referred_by"])
        self.assertEqual(pay_referral_share(buyer, "tokpkg-self", 500), 0)
        payment = f.make_payment(buyer, tokens=500, success=False)
        pay_postback(payment)
        self.assertEqual(TokenTransaction.objects.filter(reason="referral").count(), 0)
        buyer.refresh_from_db()
        self.assertEqual(buyer.token_balance, 500)

    def test_broken_coverage_lookup_falls_back_to_the_ordinary_program(self):
        buyer = self.referred()
        payment = f.make_payment(buyer, tokens=500, success=False)
        with patch("creators.models.CreatorReferralManager.covering",
                   side_effect=RuntimeError("база")):
            pay_postback(payment)
        buyer.refresh_from_db()
        self.assertEqual(buyer.token_balance, 500)
        self.assertEqual([int(tx.delta) for tx in self.shares(payment.order_id)], [50])

    def test_failed_accrual_still_pays_no_share(self):
        # Комиссия не записалась — доля кредитами всё равно не платится: её
        # место занято, комиссию доначислит backfill_commissions.
        creator = f.make_creator()
        buyer = self.referred()
        f.make_referral(creator, buyer, source="admin")
        payment = f.make_payment(buyer, tokens=500, success=False)
        with patch("creators.commission._insert", side_effect=RuntimeError("boom")):
            pay_postback(payment)
        self.assertEqual(self.shares(payment.order_id).count(), 0)
        self.assertEqual(self.rows(payment), [])

    def test_ordinary_share_helper_is_unchanged(self):
        buyer = self.referred()
        self.assertEqual(pay_referral_share(buyer, "tokpkg-x", 1234), 123)
        # Повтор по тому же заказу ничего не платит.
        self.assertEqual(pay_referral_share(buyer, "tokpkg-x", 1234), 0)
        self.assertEqual(pay_referral_share(buyer, "", 1234), 0)
        self.assertEqual(pay_referral_share(buyer, "tokpkg-y", 0), 0)
        self.assertEqual(pay_referral_share(f.make_user(), "tokpkg-z", 1234), 0)
        self.inviter.refresh_from_db()
        self.assertEqual(self.inviter.token_balance, 123)
