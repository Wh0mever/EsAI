"""Сверка creators_check: каждый инвариант ловит нарушение, сделанное руками мимо сервисов."""
import io
import json
from datetime import timedelta
from decimal import ROUND_UP, Decimal
from unittest import skipUnless
from unittest.mock import patch

from django.core.management import call_command
from django.db import connection
from django.test import override_settings
from django.utils import timezone

from audit.models import AdminActionLog
from botapi.linking import merge_into
from payments.models import Payment
from plans.models import TokenTransaction
from plans.wallet import clawback_tokens, credit_tokens

from .. import attribution, checks
from ..models import (
    Creator,
    CreatorApplication,
    CreatorCode,
    CreatorCommission,
    CreatorLevel,
    CreatorReferral,
    CreatorWithdrawal,
)
from . import factories as f
from .test_commission import crypto_invoice

D = Decimal
SQLITE = connection.vendor == "sqlite"

_tg = iter(range(730000, 740000))


def telegram_stub():
    """Аккаунт, появившийся из бота: почта-заглушка и привязанный Telegram."""
    uid = next(_tg)
    return f.make_user(email=f"telegram_{uid}@social.esai.local", telegram_uid=uid)


class ChecksTestCase(f.CreatorsTestCase):
    def setUp(self):
        super().setUp()
        self.creator = f.make_creator(code="TORA20")
        self.buyer = f.make_user()
        self.referral = f.make_referral(self.creator, self.buyer)

    def found(self, code, level="fail"):
        return [v for v in checks.run() if v.code == code and v.level == level]

    def assertClean(self):
        self.assertEqual([v for v in checks.run() if v.level == "fail"], [])

    def assertFails(self, code, count=1):
        violations = self.found(code)
        self.assertEqual(sum(v.count for v in violations), count,
                         [f"{v.code} {v.detail}" for v in checks.run()])
        # Нарушение одного инварианта не задевает остальные.
        self.assertEqual({v.code for v in checks.run() if v.level == "fail"}, {code})
        return violations

    def commission(self, payment=None, **kwargs):
        if payment is None:
            # Платёж под стать базе комиссии (курс 0.0115): иначе сверка I2
            # справедливо сочла бы базу завышенной.
            base = D(str(kwargs.get("base", "10.000000")))
            amount = max((base / D("0.0115")).quantize(D("0.01"), rounding=ROUND_UP), D("1.00"))
            payment = f.make_payment(self.buyer, amount=str(amount))
        return f.make_commission(self.creator, payment, buyer=self.buyer, **kwargs)

    def log(self, action, target, **kwargs):
        return AdminActionLog.objects.create(
            actor=f.factory_admin(), action=action,
            target_type=f"{target._meta.app_label}.{target._meta.model_name}",
            target_id=str(target.pk), creator=self.creator, **kwargs)


class CleanDataTests(ChecksTestCase):
    def test_factory_data_passes(self):
        # Всё, что умеют фабрики, в согласованном виде: ни одного fail.
        other = f.make_creator(level="ambassador", status="blocked", code="BLOCKED1")
        f.make_referral(other, source="admin")
        f.make_referral(self.creator, suspect=True)
        self.commission(amount="30.000000", base="300.000000", available_in_days=-20)
        self.commission(status="held", reason="creator_blocked")
        self.commission(status="reversed", reason="refund:freedompay")
        self.commission(status="void", reason="self_purchase", amount="0", base="0")
        for provider, amount in (("yookassa", "520.00"), ("telegram_stars", "1000"),
                                 ("crypto_nowpayments", "10.00")):
            payment = f.make_payment(self.buyer, provider=provider, amount=amount)
            if provider.startswith("crypto_"):
                invoice = crypto_invoice(payment)
                type(invoice).objects.filter(pk=invoice.pk).update(credited_tokens=500)
            self.commission(payment, amount="0.750000", base="5.000000", available_in_days=-20)
        f.make_withdrawal(self.creator, "10.00", status="paid")
        f.make_withdrawal(self.creator, "10.00", status="rejected")
        f.make_withdrawal(self.creator, "10.00", status="approved")
        f.make_withdrawal(other, "10.00", status="rejected")
        self.assertEqual(checks.run(), [])

    def test_empty_database_passes(self):
        CreatorReferral.objects.all().delete()
        CreatorCode.objects.all().delete()
        Creator.objects.all().delete()
        self.assertEqual(checks.run(), [])

    def test_check_is_read_only(self):
        self.commission()
        before = (CreatorCommission.objects.count(), AdminActionLog.objects.count(),
                  Payment.objects.count())
        checks.run()
        self.assertEqual((CreatorCommission.objects.count(), AdminActionLog.objects.count(),
                          Payment.objects.count()), before)


class MoneyInvariantTests(ChecksTestCase):
    # --- I1

    def test_i1_duplicate_payment_part(self):
        self.commission()
        # Сама база дубль не пропустит (уникальный индекс), поэтому подменяем выборку.
        self.assertEqual(checks._commission_keys(), [])
        with patch("creators.checks._commission_keys", return_value=[(7, ""), (9, "500")]):
            violation = self.assertFails("I1", 2)[0]
        self.assertIn("платёж 7", violation.detail)

    # --- I2

    def test_i2_amount_does_not_match_base_and_percent(self):
        row = self.commission()
        CreatorCommission.objects.filter(pk=row.pk).update(amount_usdt=D("1.500001"))
        self.assertFails("I2")

    def test_i2_percent_above_the_cap(self):
        row = self.commission(amount="3.000000", base="10.000000")     # 30 %
        self.assertEqual(row.percent, D("30.00"))
        self.assertFails("I2")

    def test_i2_inflated_base_with_a_consistent_amount(self):
        # Курс в десять раз выше настоящего: строка сходится сама с собой
        # (сумма = база × процент), но база не сходится с платежом.
        payment = f.make_payment(self.buyer, amount="490.00")
        row = self.commission(payment, amount="5.635000", base="56.350000")
        self.assertEqual(row.percent, D("10.00"))
        violation = self.assertFails("I2")[0]
        self.assertIn(str(payment.pk), violation.detail)

    def test_i2_rate_outside_the_corridor(self):
        # Курс перепутан местами: 87 долларов за сом.
        payment = f.make_payment(self.buyer, amount="1.00")
        self.commission(payment, amount="8.700000", base="87.000000")
        self.assertGreaterEqual(sum(v.count for v in self.found("I2")), 2)   # курс и потолок

    def test_i2_gopay_is_checked_as_a_kgs_payment(self):
        # Единый QR (GoPay) — оплата в сомах: без своей ветки такая строка не
        # попала бы ни в одну проверку и завышенная база прошла бы незамеченной.
        payment = f.make_payment(self.buyer, provider="gopay", amount="490.00")
        row = self.commission(payment, amount="0.563500", base="5.635000")
        self.assertClean()
        # Курс в десять раз выше настоящего: строка сходится сама с собой, но не с платежом.
        CreatorCommission.objects.filter(pk=row.pk).update(
            base_usd=D("56.350000"), amount_usdt=D("5.635000"))
        violation = self.assertFails("I2")[0]
        self.assertIn(str(payment.pk), violation.detail)

    def test_i2_gopay_base_above_the_payment(self):
        # Сом никогда не дороже доллара: база больше суммы в сомах — нарушение.
        payment = f.make_payment(self.buyer, provider="gopay", amount="1.00")
        self.commission(payment, amount="8.700000", base="87.000000")
        self.assertGreaterEqual(sum(v.count for v in self.found("I2")), 2)   # курс и потолок

    def test_i2_yookassa_base_above_the_kgs_price(self):
        payment = f.make_payment(self.buyer, provider="yookassa", amount="520.00",
                                 kgs_price="490.00")
        self.commission(payment, amount="60.000000", base="500.000000")
        self.assertFails("I2")

    def test_i2_usd_base_above_the_payment(self):
        payment = f.make_payment(self.buyer, amount="10.00", currency="USD")
        self.commission(payment, amount="1.100000", base="11.000000")
        self.assertFails("I2")
        CreatorCommission.objects.update(base_usd=D("10"), amount_usdt=D("1"))
        self.assertClean()

    def test_i2_crypto_parts_above_the_payment(self):
        payment = f.make_payment(self.buyer, provider="crypto_nowpayments", amount="10.00",
                                 tokens=1000)
        invoice = crypto_invoice(payment)
        type(invoice).objects.filter(pk=invoice.pk).update(credited_tokens=1000)
        self.commission(payment, part="500", amount="0.600000", base="6.000000")
        self.commission(payment, part="1000", amount="0.600000", base="6.000000")
        self.assertFails("I2")
        # Ровно в сумму платежа — нарушения нет.
        CreatorCommission.objects.update(base_usd=D("5"), amount_usdt=D("0.5"))
        self.assertClean()

    def test_i2_crypto_base_above_what_was_credited(self):
        # Оплачена половина счёта, а база комиссии — как за целый.
        payment = f.make_payment(self.buyer, provider="crypto_nowpayments", amount="10.00",
                                 tokens=1000)
        invoice = crypto_invoice(payment)
        type(invoice).objects.filter(pk=invoice.pk).update(credited_tokens=500)
        self.commission(payment, part="500", amount="1.000000", base="10.000000")
        self.assertFails("I2")

    def test_i2_stars_is_a_warning(self):
        payment = f.make_payment(self.buyer, provider="telegram_stars", amount="100")
        self.commission(payment, amount="0.500000", base="5.000000")     # 100 ⭐ — это 1.3 USD
        with patch("plans.stars.withdraw_rate", return_value=D("0.013")):
            self.assertEqual(self.found("I2"), [])
            self.assertEqual(len(self.found("I2", "warn")), 1)

    def test_i2_void_rows_are_ignored(self):
        payment = f.make_payment(self.buyer, amount="1.00")
        self.commission(payment, status="void", reason="admin_void", amount="50", base="500")
        self.log("commission.void", CreatorCommission.objects.get(payment=payment))
        self.assertClean()

    # --- I3

    def test_i3_both_programs_paid_for_one_order(self):
        payment = f.make_payment(self.buyer)
        self.commission(payment)
        credit_tokens(f.make_user(), 50, "referral", meta={"order_id": payment.order_id})
        violation = self.assertFails("I3")[0]
        self.assertIn(payment.order_id, violation.detail)

    def test_i3_reversed_commission_or_clawed_share_is_fine(self):
        payment = f.make_payment(self.buyer)
        self.commission(payment, status="void", reason="referral_share_paid", amount="0", base="0")
        credit_tokens(f.make_user(), 50, "referral", meta={"order_id": payment.order_id})
        other = f.make_payment(self.buyer)
        self.commission(other)
        inviter = f.make_user(balance=50)
        clawback_tokens(inviter, 50, "refund", meta={"kind": "referral_clawback",
                                                     "order_id": other.order_id})
        self.assertClean()

    # --- I4

    def test_i4_commission_on_own_purchase(self):
        payment = f.make_payment(self.creator.user)
        f.make_commission(self.creator, payment, buyer=self.creator.user)
        self.assertFails("I4")
        CreatorCommission.objects.update(status="void", reason="self_purchase")
        self.assertClean()

    def test_held_row_of_a_deactivated_creator_account_is_clean(self):
        # Причина creator_inactive — обычное удержание: сверка её не считает
        # нарушением и не ждёт для неё записи журнала.
        owner = self.creator.user
        owner.is_active = False
        owner.save(update_fields=["is_active"])
        f.make_commission(self.creator, status="held", reason="creator_inactive")
        self.assertEqual(checks.run(), [])

    def test_i4_held_own_purchase_is_a_warning(self):
        # Придержанная строка заработком не считается: это след слияния
        # аккаунтов, который ждёт решения администратора.
        payment = f.make_payment(self.creator.user)
        for reason in ("merge_self", "referral_suspect", "creator_blocked"):
            with self.subTest(reason=reason):
                CreatorCommission.objects.all().delete()
                f.make_commission(self.creator, payment, buyer=self.creator.user,
                                  status="held", reason=reason)
                self.assertClean()
                self.assertEqual([v.count for v in self.found("I4", "warn")], [1])

    # --- I5

    def test_i5_over_withdrawal_is_not_excused_by_an_old_reversal(self):
        self.commission(amount="10.000000", base="100", available_in_days=-5)
        # Отменена ещё ДО первого вывода: к выведенному отношения не имеет.
        self.commission(amount="50.000000", base="500", status="reversed",
                        reason="refund:freedompay", available_in_days=-10)
        f.make_withdrawal(self.creator, "30.00", status="paid")
        violation = self.assertFails("I5")[0]
        self.assertIn(str(self.creator.pk), violation.detail)

    def test_i5_reversal_after_the_payout_explains_it(self):
        row = self.commission(amount="30.000000", base="300", available_in_days=-5)
        f.make_withdrawal(self.creator, "30.00", status="paid")
        CreatorCommission.objects.filter(pk=row.pk).update(
            status="reversed", reason="refund:freedompay", reversed_at=timezone.now())
        self.assertClean()

    def test_i5_reversal_of_money_still_on_hold_does_not_explain(self):
        # Отменённая комиссия была ещё в холде: в «доступно» она не входила никогда.
        self.commission(amount="10.000000", base="100", available_in_days=-5)
        f.make_withdrawal(self.creator, "30.00", status="paid")
        row = self.commission(amount="20.000000", base="200", available_in_days=10)
        CreatorCommission.objects.filter(pk=row.pk).update(
            status="reversed", reason="refund:freedompay", reversed_at=timezone.now())
        self.assertFails("I5")

    def test_i5_merge_self_and_admin_void_explain_it(self):
        for status, reason, action in (("held", "merge_self", None),
                                       ("void", "admin_void", "commission.void")):
            with self.subTest(reason=reason):
                CreatorWithdrawal.objects.all().delete()
                CreatorCommission.objects.all().delete()
                row = self.commission(amount="30.000000", base="300", available_in_days=-5)
                f.make_withdrawal(self.creator, "30.00", status="paid")
                CreatorCommission.objects.filter(pk=row.pk).update(status=status, reason=reason)
                if action:
                    self.log(action, row)
                self.assertClean()

    def test_i5_open_request_while_in_debt_is_a_warning(self):
        row = self.commission(amount="30.000000", base="300", available_in_days=-5)
        f.make_withdrawal(self.creator, "30.00", status="approved")
        CreatorCommission.objects.filter(pk=row.pk).update(
            status="reversed", reason="refund:freedompay", reversed_at=timezone.now())
        self.assertClean()
        self.assertEqual(len(self.found("I5", "warn")), 1)

    def test_i5_honest_withdrawal_passes(self):
        self.commission(amount="30.000000", base="300", available_in_days=-5)
        f.make_withdrawal(self.creator, "20.00", status="paid")
        f.make_withdrawal(self.creator, "10.00", status="review")
        self.assertEqual(checks.run(), [])

    # --- I6

    def test_i6_helpers_are_reported(self):
        self.assertEqual((checks._paid_without_txid(), checks._repeated_txids()), ([], []))
        with patch("creators.checks._paid_without_txid", return_value=[5]), \
                patch("creators.checks._repeated_txids", return_value=["ab" * 32]):
            self.assertFails("I6", 2)

    @skipUnless(SQLITE, "ограничения снимаются только в SQLite")
    def test_i6_paid_without_txid_and_repeated_txid(self):
        self.commission(amount="50.000000", base="500", available_in_days=-5)
        first = f.make_withdrawal(self.creator, "10.00", status="paid", txid="ab" * 32)
        second = f.make_withdrawal(self.creator, "10.00", status="paid", txid="cd" * 32)
        third = f.make_withdrawal(self.creator, "10.00", status="paid", txid="ef" * 32)
        with connection.cursor() as cursor:
            # База сама этого не допустит — на время теста снимаем её защиту
            # (правки схемы в SQLite откатываются вместе с транзакцией теста).
            cursor.execute("PRAGMA ignore_check_constraints = 1")
            cursor.execute('DROP INDEX "creators_wd_txid_unique"')
        try:
            CreatorWithdrawal.objects.filter(pk=second.pk).update(txid=first.txid)
            CreatorWithdrawal.objects.filter(pk=third.pk).update(txid="")
        finally:
            with connection.cursor() as cursor:
                cursor.execute("PRAGMA ignore_check_constraints = 0")
        violations = self.found("I6")
        self.assertEqual(sorted(v.count for v in violations), [1, 1])
        self.assertTrue(any(first.txid in v.detail for v in violations))

    # --- I7

    def test_i7_refund_marker(self):
        payment = f.make_payment(self.buyer)
        self.commission(payment)
        Payment.objects.filter(pk=payment.pk).update(error="refunded")
        self.assertFails("I7")

    def test_i7_refund_seen_only_in_callbacks(self):
        # Ни одного признака, который читает refund_marker (и страховка): возврат
        # виден только в истории уведомлений платежа.
        cases = ([{"type": "refund", "payload": {"pg_order_id": "x"}}],
                 [{"type": "post", "payload": {"pg_status": "refunded", "pg_result": "1"}}],
                 [{"type": "post", "payload": {"pg_refund": "1"}}])
        for callbacks in cases:
            with self.subTest(callbacks=callbacks):
                CreatorCommission.objects.all().delete()
                payment = f.make_payment(self.buyer)
                self.commission(payment)
                Payment.objects.filter(pk=payment.pk).update(response={"callbacks": callbacks})
                from ..commission import refund_marker

                self.assertEqual(refund_marker(Payment.objects.get(pk=payment.pk)), "")
                self.assertFails("I7")

    def test_i7_ordinary_callbacks_are_not_refunds(self):
        payment = f.make_payment(self.buyer)
        self.commission(payment)
        Payment.objects.filter(pk=payment.pk).update(response={"callbacks": [
            {"type": "post", "payload": {"pg_status": "ok", "pg_result": "1"}},
            {"type": "success", "payload": {"pg_status": "refunded"}, "presentational": True},
            {"type": "status_reconcile", "payload": {"pg_transaction_status": "ok"}},
            "мусор"]})
        self.assertClean()

    def test_i7_refund_seen_only_in_the_ledger(self):
        payment = f.make_payment(self.buyer)
        self.commission(payment)
        credit_tokens(self.buyer, 500, "purchase", meta={"order_id": payment.order_id})
        clawback_tokens(self.buyer, 500, "refund",
                        meta={"kind": "chargeback_clawback", "order_id": payment.order_id})
        self.assertFails("I7")
        # Комиссия отменена — нарушения больше нет.
        CreatorCommission.objects.update(status="reversed", reversed_at=timezone.now())
        self.assertClean()


class LogInvariantTests(ChecksTestCase):
    # --- I8

    def test_i8_withdrawal_status_without_log(self):
        self.commission(amount="50.000000", base="500", available_in_days=-5)
        for status in ("approved", "paid", "rejected"):
            with self.subTest(status=status):
                CreatorWithdrawal.objects.all().delete()
                f.make_withdrawal(self.creator, "10.00", status=status, logged=False)
                self.assertFails("I8")

    def test_i8_withdrawal_log_of_another_status(self):
        self.commission(amount="50.000000", base="500", available_in_days=-5)
        # В журнале последним стоит одобрение, а заявка уже «выплачена».
        row = f.make_withdrawal(self.creator, "10.00", status="approved")
        CreatorWithdrawal.objects.filter(pk=row.pk).update(status="paid", txid="ab" * 32)
        self.assertFails("I8")

    def test_i8_retyped_txid_without_log(self):
        self.commission(amount="50.000000", base="500", available_in_days=-5)
        row = f.make_withdrawal(self.creator, "10.00", status="paid", txid="ab" * 32)
        self.assertClean()
        CreatorWithdrawal.objects.filter(pk=row.pk).update(txid="cd" * 32)
        self.assertFails("I8")
        # Исправление через сервис оставляет запись — и сверка сходится.
        self.log("withdrawal.fix_txid", row, before={"txid": "ab" * 32}, after={"txid": "cd" * 32})
        self.assertClean()

    def test_i8_reopened_withdrawal(self):
        self.commission(amount="50.000000", base="500", available_in_days=-5)
        row = f.make_withdrawal(self.creator, "10.00", status="paid", txid="ab" * 32)
        CreatorWithdrawal.objects.filter(pk=row.pk).update(status="approved", txid="",
                                                           paid_at=None, paid_by=None)
        self.assertFails("I8")
        self.log("withdrawal.reopen", row, after={"status": "approved"})
        self.assertClean()

    def test_i8_commission_reasons_without_log(self):
        for reason, status, action in (("released", "accrued", "commission.release"),
                                       ("restored", "accrued", "commission.restore"),
                                       ("admin_void", "void", "commission.void")):
            with self.subTest(reason=reason):
                CreatorCommission.objects.all().delete()
                row = self.commission(status=status, reason=reason)
                self.assertFails("I8")
                # Запись про другое действие не считается.
                self.log("commission.void" if action != "commission.void" else "commission.release",
                         row)
                self.assertFails("I8")
                self.log(action, row)
                self.assertClean()

    def test_i8_creator_credits_without_log(self):
        credit_tokens(self.creator.user, 100, "creator_credit",
                      meta={"category": "start", "note": "", "by_id": 1, "grant_id": "abc"})
        # Перенос при слиянии аккаунтов идёт без grant_id — журнал ему не нужен.
        credit_tokens(self.creator.user, 30, "creator_credit",
                      meta={"category": "merge", "grant_id": ""})
        self.assertFails("I8")
        transaction = TokenTransaction.objects.get(meta__grant_id="abc")
        self.log("credits.grant", transaction, after={"amount": 100, "grant_id": "abc"})
        self.assertClean()

    def test_i8_admin_binding_without_log(self):
        user = f.make_user()
        CreatorReferral.objects.create(user=user, creator=self.creator, source="admin")
        self.assertFails("I8")
        self.log("referral.rebind", user, after={"creator_id": self.creator.pk})
        self.assertClean()

    def test_i8_blocked_application_without_log(self):
        application = CreatorApplication.objects.create(
            user=f.make_user(), name="X", telegram="@x", country="KG", occupation="o",
            motivation="m", status="blocked")
        self.assertFails("I8")
        self.log("application.block", application)
        self.assertClean()

    # --- I9

    def test_i9_level_changed_without_log(self):
        Creator.objects.filter(pk=self.creator.pk).update(
            level=CreatorLevel.objects.get(key="ambassador_pro"))
        violation = self.assertFails("I9")[0]
        self.assertIn("уровень", violation.detail)
        self.log("creator.level_change", self.creator, before={"level": "creator"},
                 after={"level": "ambassador_pro", "percent": "25.00"})
        self.assertClean()

    def test_i9_creator_without_any_level_log(self):
        f.make_creator(logged=False)
        self.assertFails("I9")

    def test_i9_status_changed_without_log(self):
        Creator.objects.filter(pk=self.creator.pk).update(status="blocked")
        violation = self.assertFails("I9")[0]
        self.assertIn("статус", violation.detail)
        self.log("creator.block", self.creator, after={"status": "blocked"})
        self.assertClean()
        # Разблокировали в журнале, а в базе креатор всё ещё заблокирован.
        self.log("creator.unblock", self.creator, after={"status": "active"})
        self.assertFails("I9")

    def test_i9_code_differs_from_the_log(self):
        self.assertClean()      # кода в журнале нет — сверять не с чем
        self.log("creator.code_change", self.creator, before={"code": "TORA20"},
                 after={"code": "TORA21"})
        violation = self.assertFails("I9")[0]
        self.assertIn("промокод", violation.detail)
        CreatorCode.objects.filter(creator=self.creator).update(is_primary=False)
        CreatorCode.objects.create(code="TORA21", creator=self.creator, is_primary=True)
        self.assertClean()

    # --- I10

    def purchase(self, hours_ago, buyer=None, **kwargs):
        payment = f.make_payment(buyer or self.buyer, **kwargs)
        f.credit_purchase(payment)
        TokenTransaction.objects.filter(meta__order_id=payment.order_id).update(
            created_at=timezone.now() - timedelta(hours=hours_ago))
        return payment

    def test_i10_covered_purchase_without_commission(self):
        CreatorReferral.objects.filter(pk=self.referral.pk).update(
            bound_at=timezone.now() - timedelta(days=40))
        payment = self.purchase(hours_ago=3)
        violation = self.assertFails("I10")[0]
        self.assertIn(payment.order_id, violation.detail)
        # Любая строка комиссии (даже аннулированная) закрывает вопрос.
        self.commission(payment, status="void", reason="test_payment", amount="0", base="0")
        self.assertClean()

    def test_i10_window_and_coverage(self):
        # Привязка старше любой покупки ниже: «слишком старую» и «слишком
        # свежую» покупку исключает только окно, а не отсутствие привязки.
        CreatorReferral.objects.filter(pk=self.referral.pk).update(
            bound_at=timezone.now() - timedelta(days=60))
        young = self.purchase(hours_ago=0.5)      # моложе часа: хук ещё может доехать
        old = self.purchase(hours_ago=24 * 31)    # старше 30 дней
        late = f.make_user()
        f.make_referral(self.creator, late, bound_at=timezone.now() - timedelta(days=5))
        self.purchase(hours_ago=24 * 6, buyer=late)          # до привязки
        self.purchase(hours_ago=3, buyer=f.make_user())      # человек без креатора
        refunded = self.purchase(hours_ago=3)
        Payment.objects.filter(pk=refunded.pk).update(error="refunded")
        credit_tokens(self.buyer, 10, "purchase", meta={"order_id": "tokpkg-ghost"})
        TokenTransaction.objects.filter(meta__order_id="tokpkg-ghost").update(
            created_at=timezone.now() - timedelta(hours=3))
        self.assertClean()

        # Те же покупки внутри окна — уже нарушение: их исключало именно окно.
        for payment, hours_ago in ((young, 2), (old, 24 * 29)):
            with self.subTest(order=payment.order_id):
                TokenTransaction.objects.filter(meta__order_id=payment.order_id).update(
                    created_at=timezone.now() - timedelta(hours=hours_ago))
                violation = self.assertFails("I10")[0]
                self.assertIn(payment.order_id, violation.detail)
                self.commission(payment, status="void", reason="test_payment",
                                amount="0", base="0")
                self.assertClean()

    def test_i10_crypto_part(self):
        CreatorReferral.objects.filter(pk=self.referral.pk).update(
            bound_at=timezone.now() - timedelta(days=5))
        payment = f.make_payment(self.buyer, provider="crypto_nowpayments", amount="10.00",
                                 tokens=1000)
        crypto_invoice(payment)
        type(payment.crypto_invoice).objects.update(credited_tokens=1000)
        f.credit_purchase(payment, credited=500, idem="500")
        f.credit_purchase(payment, credited=500, idem="1000")
        TokenTransaction.objects.update(created_at=timezone.now() - timedelta(hours=3))
        self.commission(payment, part="500", amount="0.500000", base="5.000000")
        violation = self.assertFails("I10")[0]
        self.assertIn(f"{payment.order_id}#1000", violation.detail)

    def test_i10_is_skipped_when_the_program_is_off(self):
        CreatorReferral.objects.filter(pk=self.referral.pk).update(
            bound_at=timezone.now() - timedelta(days=5))
        self.purchase(hours_ago=3)
        with override_settings(CREATORS_MODE="off"):
            self.assertClean()
        self.assertFails("I10")


class MergeTests(ChecksTestCase):
    """Сверка после настоящего слияния аккаунтов: сделанное слиянием намеренно — не нарушение."""

    def test_i4_self_referral_merge_leaves_no_failure(self):
        # Слияние ставит причину merge_self и уже придержанной строке: иначе
        # снятие пометки с привязки отпустило бы комиссию с собственной покупки.
        for suspect, reason in ((False, "merge_self"), (True, "merge_self")):
            with self.subTest(suspect=suspect):
                CreatorCommission.objects.all().delete()
                stub = telegram_stub()
                f.make_referral(self.creator, stub, source="bot", suspect=suspect)
                payment = f.make_payment(stub)
                row = f.make_commission(self.creator, payment, amount="0.563500", base="5.635000",
                                        status="held" if suspect else "accrued",
                                        reason="referral_suspect" if suspect else "")
                # Тот же человек привязал этот Telegram к собственному аккаунту креатора.
                counts = merge_into(stub, self.creator.user)
                self.assertEqual(counts["creator_referral"], "self")
                row.refresh_from_db()
                self.assertEqual((row.status, row.reason, row.buyer_pk),
                                 ("held", reason, self.creator.user_id))
                self.assertClean()
                self.assertEqual([v.count for v in self.found("I4", "warn")], [1])

                # Строку отпустили — собственная покупка стала заработком: это нарушение.
                CreatorCommission.objects.filter(pk=row.pk).update(status="accrued",
                                                                   reason="released")
                self.log("commission.release", row)
                self.assertFails("I4")

    def test_i8_admin_binding_moved_by_a_merge_is_still_covered(self):
        admin = f.make_user(superuser=True)
        stub = telegram_stub()
        referral = attribution.rebind(stub, self.creator, actor=admin, reason="партнёр попросил")
        self.assertEqual(referral.source, "admin")
        self.assertClean()

        # Заглушку привязали к свежему аккаунту сайта: привязка переехала на
        # него, а запись журнала по-прежнему указывает на заглушку.
        target = f.make_user(joined_ago=1)
        counts = merge_into(stub, target)
        self.assertEqual(counts["creator_referral"], "moved")
        referral.refresh_from_db()
        self.assertEqual(referral.user_id, target.pk)
        self.assertClean()
        # Запись журнала называет саму привязку — этого достаточно и без
        # сведений о том, кто привязал.
        log = AdminActionLog.objects.get(action="referral.rebind")
        self.assertEqual(log.after, {"creator_id": self.creator.pk, "referral_id": referral.pk})
        CreatorReferral.objects.filter(pk=referral.pk).update(bound_by=None)
        self.assertClean()

        # Журнал, в котором привязка не названа (записи до этой правки), узнаёт
        # её по паре «кто привязал — к кому»: чужой креатор под неё не подходит.
        AdminActionLog.objects.filter(pk=log.pk).update(after={"creator_id": self.creator.pk})
        CreatorReferral.objects.filter(pk=referral.pk).update(bound_by=admin)
        self.assertClean()
        other = f.make_creator()
        CreatorReferral.objects.filter(pk=referral.pk).update(creator=other)
        self.assertFails("I8")

    def test_i8_admin_binding_is_matched_by_referral_id_or_by_who_bound_it(self):
        admin = f.factory_admin()
        elsewhere = f.make_user()
        user = f.make_user()
        referral = CreatorReferral.objects.create(user=user, creator=self.creator, source="admin")
        self.assertFails("I8")
        # Запись про другого пользователя и без «кто привязал» ничего не доказывает.
        self.log("referral.rebind", elsewhere, after={"creator_id": self.creator.pk})
        self.assertFails("I8")
        # Привязку сделал тот же администратор к тому же креатору.
        CreatorReferral.objects.filter(pk=referral.pk).update(bound_by=admin)
        self.assertClean()
        # Тот же администратор, но другой креатор — не подходит.
        other = f.make_creator()
        CreatorReferral.objects.filter(pk=referral.pk).update(creator=other)
        self.assertFails("I8")
        # Запись с id самой привязки подходит всегда.
        self.log("referral.rebind", elsewhere,
                 after={"creator_id": other.pk, "referral_id": referral.pk})
        CreatorReferral.objects.filter(pk=referral.pk).update(bound_by=None)
        self.assertClean()


class CommandTests(ChecksTestCase):
    def run_command(self, *args):
        out = io.StringIO()
        try:
            call_command("creators_check", *args, stdout=out)
            code = 0
        except SystemExit as exc:
            code = exc.code
        return code, out.getvalue()

    def test_clean_run_exits_zero(self):
        code, output = self.run_command()
        self.assertEqual(code, 0)
        self.assertEqual(output.split(), [word for name in checks.CODES for word in (name, "OK")])

    def test_violation_exits_one(self):
        payment = f.make_payment(self.creator.user)
        f.make_commission(self.creator, payment, buyer=self.creator.user)
        code, output = self.run_command()
        self.assertEqual(code, 1)
        lines = output.strip().splitlines()
        self.assertEqual(len(lines), len(checks.CODES))
        self.assertTrue(lines[3].startswith("I4 FAIL (1) "), lines[3])
        self.assertEqual(lines[0], "I1 OK")

    def test_warning_alone_exits_zero(self):
        with patch("creators.checks.run",
                   return_value=[checks.Violation("I5", "warn", "долг", 2)]):
            code, output = self.run_command()
        self.assertEqual(code, 0)
        self.assertIn("I5 WARN (2) долг", output)

    def test_json(self):
        payment = f.make_payment(self.creator.user)
        f.make_commission(self.creator, payment, buyer=self.creator.user)
        code, output = self.run_command("--json")
        data = json.loads(output)
        self.assertEqual((code, data["ok"]), (1, False))
        self.assertEqual([(v["code"], v["level"], v["count"]) for v in data["violations"]],
                         [("I4", "fail", 1)])
        code, output = self.run_command("--json")
        CreatorCommission.objects.all().delete()
        code, output = self.run_command("--json")
        self.assertEqual((code, json.loads(output)), (0, {"ok": True, "violations": []}))
