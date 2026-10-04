"""Вывод USDT: заявка креатора и ручной путь review -> approved -> paid / rejected."""
import threading
from decimal import Decimal
from unittest import skipUnless
from unittest.mock import patch

from django.db import IntegrityError, connection, transaction
from django.test import RequestFactory, override_settings
from django.utils import timezone

from adminapi.runtime import set_runtime
from audit.models import AdminActionLog

from .. import balance, withdrawals
from ..errors import CreatorsError
from ..models import Creator, CreatorCommission, CreatorWithdrawal
from . import factories as f

D = Decimal
TXID = "ab" * 32
TXID_2 = "cd" * 32


class WithdrawalTestCase(f.CreatorsTestCase):
    def setUp(self):
        super().setUp()
        patcher = patch("creators.notify.emit")
        self.emit = patcher.start()
        self.addCleanup(patcher.stop)
        self.admin = f.make_user(superuser=True)
        self.creator = f.make_creator(payout_address=f.VALID_TRC20)
        # 50 USDT уже вышли из холда.
        self.commission = f.make_commission(self.creator, amount="50.000000", base="500",
                                            available_in_days=-1)

    def assertRefused(self, code, fn, *args, **kwargs):
        with self.assertRaises(CreatorsError) as ctx:
            fn(*args, **kwargs)
        self.assertEqual(ctx.exception.code, code)
        return ctx.exception

    def request(self, amount="10", **kwargs):
        return withdrawals.request_withdrawal(self.creator, amount, **kwargs)

    def logs(self, action):
        return AdminActionLog.objects.filter(action=action)

    def emitted(self, event):
        return [call for call in self.emit.call_args_list if call.args[1] == event]

    def reverse_commission(self):
        """Возврат оплаты: комиссия отменена, баланс уходит в минус."""
        CreatorCommission.objects.filter(pk=self.commission.pk).update(
            status="reversed", reversed_at=timezone.now(), reason="refund:freedompay")


class RequestTests(WithdrawalTestCase):
    def test_request_is_created_in_review(self):
        http = RequestFactory().post("/", HTTP_X_FORWARDED_FOR="203.0.113.7, 10.0.0.1")
        row = self.request("25.50", request=http)
        self.assertEqual((row.status, row.amount_usdt, row.network), ("review", D("25.50"), "TRC20"))
        self.assertEqual((row.address, row.ip, row.txid), (f.VALID_TRC20, "203.0.113.7", ""))
        b = balance.summary(self.creator)
        self.assertEqual((b.available, b.in_withdrawal), (D("24.500000"), D("25.500000")))
        # Заявка — действие креатора: журнал администратора и уведомления молчат.
        self.assertEqual(AdminActionLog.objects.filter(action__startswith="withdrawal.").count(), 0)
        self.assertEqual(self.emit.call_count, 0)

    def test_refusals_come_in_the_documented_order(self):
        # Все причины отказа сразу; снимаем их по одной — каждый раз всплывает следующая.
        set_runtime("creators_payouts_enabled", False)
        Creator.objects.filter(pk=self.creator.pk).update(status="blocked", payout_address="")
        f.make_withdrawal(self.creator, "10.00", status="review")
        self.reverse_commission()

        with override_settings(CREATORS_MODE="staff"):
            self.assertRefused("disabled", self.request, "x")
        self.assertRefused("payouts_disabled", self.request, "x")
        set_runtime("creators_payouts_enabled", True)
        self.assertRefused("creator_blocked", self.request, "x")
        Creator.objects.filter(pk=self.creator.pk).update(status="active")
        self.assertRefused("address_required", self.request, "x")
        self.assertRefused("address_invalid", self.request, "x",
                           address="TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6u")
        Creator.objects.filter(pk=self.creator.pk).update(payout_address=f.VALID_TRC20)
        self.assertRefused("amount_invalid", self.request, "x")
        self.assertRefused("amount_below_min", self.request, "9.99")
        self.assertRefused("withdrawal_open", self.request, "10")
        CreatorWithdrawal.objects.filter(creator=self.creator).delete()
        exc = self.assertRefused("insufficient_available", self.request, "10")
        self.assertEqual(exc.extra, {"available": "0.00"})
        self.assertEqual(CreatorWithdrawal.objects.count(), 0)

    def test_mode_off_and_staff(self):
        with override_settings(CREATORS_MODE="off"):
            self.assertRefused("disabled", self.request)
        with override_settings(CREATORS_MODE="staff"):
            # В режиме staff программа открыта только креаторам-сотрудникам.
            self.assertRefused("disabled", self.request)
            staff_creator = f.make_creator(f.make_user(staff=True), payout_address=f.VALID_TRC20)
            f.make_commission(staff_creator, amount="20.000000", base="200", available_in_days=-1)
            row = withdrawals.request_withdrawal(staff_creator, "10")
            self.assertEqual(row.status, "review")

    def test_payouts_switch(self):
        with override_settings(CREATORS_PAYOUTS_ENABLED=False):
            self.assertRefused("payouts_disabled", self.request)
        self.assertEqual(self.request().status, "review")

    def test_minimum_is_exactly_ten(self):
        self.assertRefused("amount_below_min", self.request, "9.99")
        self.assertRefused("amount_below_min", self.request, D("9.99"))
        self.assertEqual(self.request("10.00").amount_usdt, D("10.00"))

    def test_amount_validation(self):
        for bad in ("10.001", "10.999", "abc", "", None, "NaN", "Infinity", "-10", "0", True,
                    D("NaN"), D("10.005"), [], {}):
            with self.subTest(amount=bad):
                self.assertRefused("amount_invalid", self.request, bad)
        self.assertEqual(CreatorWithdrawal.objects.count(), 0)

    def test_amount_too_long_to_round_is_invalid_not_a_server_error(self):
        # Больше 28 значащих цифр: Decimal.quantize бросает InvalidOperation.
        # Это неверная сумма (HTTP 400), а не необработанная ошибка (HTTP 500).
        for bad in ("1e30", 1e30, "1E+40", "1e400", "9" * 40, D("1e30"), D("9" * 29)):
            with self.subTest(amount=bad):
                self.assertRefused("amount_invalid", self.request, bad)
        # Большое, но представимое число — обычный отказ «недостаточно средств».
        self.assertRefused("insufficient_available", self.request, "1e20")
        self.assertEqual(CreatorWithdrawal.objects.count(), 0)

    def test_amount_forms_that_pass(self):
        for good, expected in ((10, "10.00"), ("10.5", "10.50"), (D("12.34"), "12.34"),
                               (" 11 ", "11.00"), (10.5, "10.50")):
            with self.subTest(amount=good):
                row = self.request(good)
                self.assertEqual(str(row.amount_usdt), expected)
                row.delete()

    def test_cannot_request_more_than_available(self):
        exc = self.assertRefused("insufficient_available", self.request, "50.01")
        self.assertEqual(exc.extra, {"available": "50.00"})
        self.assertEqual(self.request("50").amount_usdt, D("50.00"))

    def test_money_on_hold_or_held_is_not_available(self):
        creator = f.make_creator(payout_address=f.VALID_TRC20)
        f.make_commission(creator, amount="30.000000", base="300", available_in_days=3)
        f.make_commission(creator, amount="30.000000", base="300", status="held",
                          reason="creator_blocked", available_in_days=-1)
        self.assertRefused("insufficient_available", withdrawals.request_withdrawal, creator, "10")

    def test_second_request_is_refused_while_one_is_open(self):
        first = self.request("10")
        self.assertRefused("withdrawal_open", self.request, "10")
        withdrawals.approve(first.pk, actor=self.admin)
        self.assertRefused("withdrawal_open", self.request, "10")
        withdrawals.reject(first.pk, actor=self.admin, reason="нет")
        self.assertEqual(self.request("10").status, "review")

    def test_database_refuses_the_second_open_request(self):
        # Гонка двух запросов: проверка в коде прошла у обоих, второго останавливает индекс.
        self.request("10")
        real_filter = CreatorWithdrawal.objects.filter

        def blind(*args, **kwargs):
            if "status__in" in kwargs:
                return CreatorWithdrawal.objects.none()
            return real_filter(*args, **kwargs)

        with patch.object(CreatorWithdrawal.objects, "filter", side_effect=blind):
            self.assertRefused("withdrawal_open", self.request, "10")
        self.assertEqual(CreatorWithdrawal.objects.count(), 1)

    def test_address_from_the_request_is_saved_and_logged(self):
        Creator.objects.filter(pk=self.creator.pk).update(payout_address="")
        row = self.request("10", address=f" {f.VALID_TRC20_2} ")
        self.creator.refresh_from_db()
        self.assertEqual(row.address, f.VALID_TRC20_2)
        self.assertEqual(self.creator.payout_address, f.VALID_TRC20_2)
        self.assertIsNotNone(self.creator.payout_address_changed_at)
        log = self.logs("creator.payout_address_change").get()
        self.assertEqual((log.actor_id, log.creator_id), (self.creator.user_id, self.creator.pk))
        self.assertEqual((log.before, log.after), ({"payout_address": ""},
                                                   {"payout_address": f.VALID_TRC20_2}))

    def test_refused_request_does_not_change_the_address(self):
        self.assertRefused("insufficient_available", self.request, "60", address=f.VALID_TRC20_2)
        self.creator.refresh_from_db()
        self.assertEqual(self.creator.payout_address, f.VALID_TRC20)
        self.assertEqual(self.logs("creator.payout_address_change").count(), 0)

    def test_address_snapshot_survives_a_later_change(self):
        row = self.request("10")
        withdrawals.set_payout_address(self.creator, f.VALID_TRC20_2)
        row.refresh_from_db()
        self.assertEqual(row.address, f.VALID_TRC20)


class PayoutAddressTests(WithdrawalTestCase):
    def test_set_and_log(self):
        result = withdrawals.set_payout_address(self.creator, f.VALID_TRC20_2)
        self.assertEqual(result.payout_address, f.VALID_TRC20_2)
        self.assertIsNotNone(result.payout_address_changed_at)
        log = self.logs("creator.payout_address_change").get()
        self.assertEqual(log.actor_id, self.creator.user_id)
        self.assertEqual((log.before, log.after), ({"payout_address": f.VALID_TRC20},
                                                   {"payout_address": f.VALID_TRC20_2}))

    def test_same_address_is_a_noop(self):
        result = withdrawals.set_payout_address(self.creator, f.VALID_TRC20)
        self.assertIsNone(result.payout_address_changed_at)
        self.assertEqual(self.logs("creator.payout_address_change").count(), 0)

    def test_refusals(self):
        self.assertRefused("address_invalid", withdrawals.set_payout_address, self.creator, "T123")
        self.assertRefused("address_invalid", withdrawals.set_payout_address, self.creator, None)
        Creator.objects.filter(pk=self.creator.pk).update(status="blocked")
        self.assertRefused("creator_blocked", withdrawals.set_payout_address, self.creator,
                           f.VALID_TRC20_2)


class StateMachineTests(WithdrawalTestCase):
    def test_full_path(self):
        row = self.request("30")
        row = withdrawals.approve(row.pk, actor=self.admin)
        self.assertEqual((row.status, row.approved_by_id), ("approved", self.admin.pk))
        self.assertIsNotNone(row.approved_at)
        self.assertEqual(self.emitted("payout_approved")[0].kwargs, {"amount_usdt": "30.00"})

        row = withdrawals.mark_paid(row.pk, actor=self.admin, txid="0x" + TXID.upper())
        self.assertEqual((row.status, row.txid, row.paid_by_id), ("paid", TXID, self.admin.pk))
        self.assertIsNotNone(row.paid_at)
        self.assertEqual(self.emitted("payout_sent")[0].kwargs,
                         {"amount_usdt": "30.00", "txid": TXID})

        b = balance.summary(self.creator)
        self.assertEqual((b.paid, b.available, b.in_withdrawal),
                         (D("30.000000"), D("20.000000"), D("0")))

        approve, paid = self.logs("withdrawal.approve").get(), self.logs("withdrawal.mark_paid").get()
        for log in (approve, paid):
            self.assertEqual((log.actor_id, log.creator_id, log.target_type, log.target_id),
                             (self.admin.pk, self.creator.pk, "creators.creatorwithdrawal",
                              str(row.pk)))
        self.assertEqual(approve.after, {"status": "approved"})
        self.assertEqual(paid.after, {"status": "paid", "txid": TXID})

    def test_reject_from_review_and_from_approved_frees_the_money(self):
        for approve_first in (False, True):
            with self.subTest(approved=approve_first):
                row = self.request("30")
                if approve_first:
                    withdrawals.approve(row.pk, actor=self.admin)
                self.assertEqual(balance.summary(self.creator).available, D("20.000000"))
                row = withdrawals.reject(row.pk, actor=self.admin, reason="адрес биржи")
                self.assertEqual((row.status, row.reject_reason, row.rejected_by_id),
                                 ("rejected", "адрес биржи", self.admin.pk))
                self.assertIsNotNone(row.rejected_at)
                # Деньги вернулись сами: баланс считается из строк.
                self.assertEqual(balance.summary(self.creator).available, D("50.000000"))
        self.assertEqual(self.logs("withdrawal.reject").count(), 2)
        self.assertEqual(self.emitted("payout_rejected")[0].kwargs,
                         {"amount_usdt": "30.00", "reason": "адрес биржи"})

    def test_reject_needs_a_reason(self):
        row = self.request("10")
        self.assertRefused("reason_required", withdrawals.reject, row.pk, actor=self.admin, reason="  ")
        row.refresh_from_db()
        self.assertEqual(row.status, "review")

    def test_illegal_transitions(self):
        calls = {
            "approve": lambda pk: withdrawals.approve(pk, actor=self.admin),
            "reject": lambda pk: withdrawals.reject(pk, actor=self.admin, reason="x"),
            "mark_paid": lambda pk: withdrawals.mark_paid(pk, actor=self.admin, txid=TXID_2),
            "fix_txid": lambda pk: withdrawals.fix_txid(pk, actor=self.admin, txid=TXID_2, reason="x"),
            "reopen": lambda pk: withdrawals.reopen(pk, actor=self.admin, reason="x"),
        }
        allowed = {"review": {"approve", "reject"}, "approved": {"reject", "mark_paid"},
                   "paid": {"fix_txid", "reopen"}, "rejected": set()}
        for status, legal in allowed.items():
            for name, call in calls.items():
                if name in legal:
                    continue
                with self.subTest(status=status, action=name):
                    CreatorWithdrawal.objects.all().delete()
                    row = f.make_withdrawal(self.creator, "10.00", status=status)
                    self.assertRefused("bad_state", call, row.pk)
                    row.refresh_from_db()
                    self.assertEqual(row.status, status)

    def test_unknown_id(self):
        self.assertRefused("not_found", withdrawals.approve, 10 ** 9, actor=self.admin)

    def test_approve_refused_after_a_reversal(self):
        row = self.request("30")
        self.reverse_commission()
        self.assertRefused("insufficient_available", withdrawals.approve, row.pk, actor=self.admin)
        row.refresh_from_db()
        self.assertEqual(row.status, "review")
        self.assertEqual(self.logs("withdrawal.approve").count(), 0)

    def test_approve_refused_for_blocked_creator(self):
        row = self.request("30")
        Creator.objects.filter(pk=self.creator.pk).update(status="blocked")
        self.assertRefused("creator_blocked", withdrawals.approve, row.pk, actor=self.admin)

    def test_mark_paid_is_rechecked_after_a_reversal(self):
        row = self.request("30")
        withdrawals.approve(row.pk, actor=self.admin)
        self.reverse_commission()

        self.assertRefused("insufficient_available", withdrawals.mark_paid, row.pk,
                           actor=self.admin, txid=TXID)
        # Обойти можно только осознанно: деньги уже ушли в сеть, и причина записана.
        self.assertRefused("reason_required", withdrawals.mark_paid, row.pk,
                           actor=self.admin, txid=TXID, force=True)
        row.refresh_from_db()
        self.assertEqual(row.status, "approved")

        row = withdrawals.mark_paid(row.pk, actor=self.admin, txid=TXID, force=True,
                                    reason="перевод уже отправлен")
        self.assertEqual((row.status, row.txid), ("paid", TXID))
        log = self.logs("withdrawal.mark_paid").get()
        self.assertEqual(log.after, {"status": "paid", "txid": TXID, "forced": True})
        self.assertEqual(log.reason, "перевод уже отправлен")
        self.assertEqual(balance.summary(self.creator).debt, D("30.000000"))

    def test_mark_paid_for_blocked_creator(self):
        row = self.request("30")
        withdrawals.approve(row.pk, actor=self.admin)
        Creator.objects.filter(pk=self.creator.pk).update(status="blocked")
        self.assertRefused("creator_blocked", withdrawals.mark_paid, row.pk,
                           actor=self.admin, txid=TXID)
        row = withdrawals.mark_paid(row.pk, actor=self.admin, txid=TXID, force=True,
                                    reason="отправлено до блокировки")
        self.assertEqual(row.status, "paid")

    def test_txid_format_and_duplicate(self):
        other = f.make_creator()
        f.make_withdrawal(other, "10.00", status="paid", txid=TXID)
        row = self.request("30")
        withdrawals.approve(row.pk, actor=self.admin)
        for bad in ("", "a" * 63, "z" * 64, None):
            self.assertRefused("txid_invalid", withdrawals.mark_paid, row.pk,
                               actor=self.admin, txid=bad)
        # Тот же хеш в любом регистре и с 0x — это тот же перевод.
        self.assertRefused("txid_duplicate", withdrawals.mark_paid, row.pk,
                           actor=self.admin, txid="0x" + TXID.upper())
        row.refresh_from_db()
        self.assertEqual((row.status, row.txid), ("approved", ""))
        self.assertEqual(self.logs("withdrawal.mark_paid").filter(target_id=str(row.pk)).count(), 0)

    def test_txid_duplicate_caught_by_the_database(self):
        other = f.make_creator()
        f.make_withdrawal(other, "10.00", status="paid", txid=TXID)
        row = self.request("30")
        withdrawals.approve(row.pk, actor=self.admin)
        with patch("creators.withdrawals._txid_taken", return_value=False):
            self.assertRefused("txid_duplicate", withdrawals.mark_paid, row.pk,
                               actor=self.admin, txid=TXID)
        row.refresh_from_db()
        self.assertEqual(row.status, "approved")

    def test_fix_txid(self):
        row = f.make_withdrawal(self.creator, "10.00", status="paid", txid=TXID)
        other = f.make_withdrawal(f.make_creator(), "10.00", status="paid", txid="ef" * 32)

        self.assertRefused("reason_required", withdrawals.fix_txid, row.pk, actor=self.admin,
                           txid=TXID_2, reason="")
        self.assertRefused("txid_invalid", withdrawals.fix_txid, row.pk, actor=self.admin,
                           txid="a" * 63, reason="опечатка")
        self.assertRefused("bad_state", withdrawals.fix_txid, row.pk, actor=self.admin,
                           txid=TXID.upper(), reason="опечатка")
        self.assertRefused("txid_duplicate", withdrawals.fix_txid, row.pk, actor=self.admin,
                           txid=other.txid, reason="опечатка")

        fixed = withdrawals.fix_txid(row.pk, actor=self.admin, txid=TXID_2.upper(), reason="опечатка")
        self.assertEqual((fixed.status, fixed.txid), ("paid", TXID_2))
        log = self.logs("withdrawal.fix_txid").get()
        self.assertEqual((log.before, log.after, log.reason),
                         ({"txid": TXID}, {"txid": TXID_2}, "опечатка"))
        self.assertEqual((log.creator_id, log.target_id), (self.creator.pk, str(row.pk)))
        # Исправление TXID — тихая правка, креатору ничего не уходит.
        self.assertEqual(self.emit.call_count, 0)

    def test_reopen(self):
        row = f.make_withdrawal(self.creator, "10.00", status="paid", txid=TXID)
        self.assertRefused("reason_required", withdrawals.reopen, row.pk, actor=self.admin, reason="")
        reopened = withdrawals.reopen(row.pk, actor=self.admin, reason="перевод не прошёл")
        self.assertEqual((reopened.status, reopened.txid, reopened.paid_at, reopened.paid_by_id),
                         ("approved", "", None, None))
        self.assertIsNotNone(reopened.approved_at)
        log = self.logs("withdrawal.reopen").get()
        self.assertEqual(log.before["txid"], TXID)
        self.assertIn("paid_at", log.before)
        self.assertEqual(log.after, {"status": "approved"})
        self.assertEqual(self.emit.call_count, 0)

        # Освободившийся TXID можно ввести заново, и заявку снова оплатить.
        paid = withdrawals.mark_paid(row.pk, actor=self.admin, txid=TXID)
        self.assertEqual(paid.status, "paid")

    def test_reopen_refused_while_another_request_is_open(self):
        row = f.make_withdrawal(self.creator, "10.00", status="paid", txid=TXID)
        self.request("10")
        self.assertRefused("withdrawal_open", withdrawals.reopen, row.pk, actor=self.admin,
                           reason="перевод не прошёл")
        row.refresh_from_db()
        self.assertEqual((row.status, row.txid), ("paid", TXID))

    def test_reopen_race_is_caught_by_the_database(self):
        row = f.make_withdrawal(self.creator, "10.00", status="paid", txid=TXID)
        self.request("10")
        real_filter = CreatorWithdrawal.objects.filter

        def blind(*args, **kwargs):
            if "status__in" in kwargs:
                return CreatorWithdrawal.objects.none()
            return real_filter(*args, **kwargs)

        with patch.object(CreatorWithdrawal.objects, "filter", side_effect=blind):
            self.assertRefused("withdrawal_open", withdrawals.reopen, row.pk, actor=self.admin,
                               reason="перевод не прошёл")
        row.refresh_from_db()
        self.assertEqual(row.status, "paid")

    def test_failed_log_rolls_the_transition_back(self):
        row = self.request("10")
        with patch("creators.withdrawals.log_admin_action", side_effect=RuntimeError("журнал")):
            with self.assertRaises(RuntimeError):
                withdrawals.approve(row.pk, actor=self.admin)
        row.refresh_from_db()
        self.assertEqual(row.status, "review")

    def test_database_constraints_back_the_service(self):
        # «Выплачено» без TXID и сумму меньше минимума не примет сама база.
        row = self.request("10")
        with self.assertRaises(IntegrityError), transaction.atomic():
            CreatorWithdrawal.objects.filter(pk=row.pk).update(status="paid")
        with self.assertRaises(IntegrityError), transaction.atomic():
            CreatorWithdrawal.objects.filter(pk=row.pk).update(amount_usdt=Decimal("9.99"))


@skipUnless(connection.vendor == "postgresql", "блокировки строк есть только в PostgreSQL")
class ParallelRequestTests(f.CreatorsTransactionTestCase):
    def test_two_parallel_requests_make_one_row(self):
        creator = f.make_creator(payout_address=f.VALID_TRC20)
        f.make_commission(creator, amount="50.000000", base="500", available_in_days=-1)
        barrier = threading.Barrier(2)
        results = []

        def worker():
            try:
                barrier.wait(10)
                results.append(withdrawals.request_withdrawal(creator, "30").status)
            except CreatorsError as exc:
                results.append(exc.code)
            finally:
                connection.close()

        threads = [threading.Thread(target=worker) for _ in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertEqual(sorted(results), ["review", "withdrawal_open"])
        self.assertEqual(CreatorWithdrawal.objects.filter(creator=creator).count(), 1)
