"""Журнал ручных действий администратора (audit.services.log_admin_action).

Главное отличие от log_event: помощник бросает исключение. Действие с деньгами
без записи в журнале должно откатиться целиком, а не пройти молча.
"""
from datetime import datetime, timezone as dt_timezone
from decimal import Decimal
from unittest import mock

from django.db import transaction
from django.test import RequestFactory

from audit.models import ADMIN_ACTIONS, AdminActionLog
from audit.services import log_admin_action

from . import factories as f

# §1.12 спецификации — единственные допустимые значения action.
SPEC_ACTIONS = {
    "application.approve", "application.reject", "application.block", "application.unblock",
    "creator.level_change", "creator.block", "creator.unblock", "creator.code_set",
    "creator.code_change", "creator.payout_address_change", "publication.approve",
    "publication.reject", "referral.rebind", "referral.clear_suspect", "commission.void",
    "commission.release", "commission.restore", "withdrawal.approve", "withdrawal.reject",
    "withdrawal.mark_paid", "withdrawal.fix_txid", "withdrawal.reopen", "credits.grant",
    "level.edit", "settings.edit", "payment.mark_refunded",
}


class LogAdminActionTests(f.CreatorsTestCase):
    def setUp(self):
        super().setUp()
        self.admin = f.make_user(superuser=True)
        self.creator = f.make_creator(logged=False)

    def test_writes_actor_action_target_and_creator(self):
        withdrawal = f.make_withdrawal(self.creator, logged=False)
        row = log_admin_action(self.admin, "withdrawal.approve", target=withdrawal,
                               creator=self.creator, before={"status": "review"},
                               after={"status": "approved"}, reason="проверено")
        self.assertIsInstance(row, AdminActionLog)
        row.refresh_from_db()
        self.assertEqual(row.actor, self.admin)
        self.assertEqual(row.action, "withdrawal.approve")
        self.assertEqual(row.target_type, "creators.creatorwithdrawal")
        self.assertEqual(row.target_id, str(withdrawal.pk))
        self.assertEqual(row.creator, self.creator)
        self.assertEqual(row.before, {"status": "review"})
        self.assertEqual(row.after, {"status": "approved"})
        self.assertEqual(row.reason, "проверено")
        self.assertIsNone(row.ip)
        self.assertIsNotNone(row.created_at)

    def test_target_of_another_app(self):
        payment = f.make_payment(f.make_user())
        row = log_admin_action(self.admin, "payment.mark_refunded", target=payment)
        self.assertEqual((row.target_type, row.target_id), ("payments.payment", str(payment.pk)))
        user_row = log_admin_action(self.admin, "referral.rebind", target=payment.user)
        self.assertEqual(user_row.target_type, "users.user")

    def test_defaults_without_target(self):
        row = log_admin_action(self.admin, "settings.edit")
        row.refresh_from_db()
        self.assertEqual((row.target_type, row.target_id, row.reason), ("", "", ""))
        self.assertEqual((row.before, row.after), ({}, {}))
        self.assertIsNone(row.creator)
        self.assertIsNone(row.ip)

    def test_before_and_after_are_json_safe(self):
        moment = datetime(2026, 10, 4, 12, 30, tzinfo=dt_timezone.utc)
        row = log_admin_action(
            self.admin, "commission.void",
            before={"amount": Decimal("1.500000"), "at": moment, "nested": {"p": Decimal("15.00")}},
            after={"amounts": [Decimal("0"), Decimal("2.25")], "who": self.admin, "none": None})
        row.refresh_from_db()
        self.assertEqual(row.before["amount"], "1.500000")
        self.assertEqual(row.before["nested"], {"p": "15.00"})
        self.assertTrue(row.before["at"].startswith("2026-10-04 12:30"))
        self.assertEqual(row.after["amounts"], ["0", "2.25"])
        self.assertEqual(row.after["who"], str(self.admin))
        self.assertIsNone(row.after["none"])

    def test_ip_first_hop_of_forwarded_for(self):
        request = RequestFactory().post("/", HTTP_X_FORWARDED_FOR="203.0.113.7, 10.0.0.1",
                                        REMOTE_ADDR="10.0.0.9")
        row = log_admin_action(self.admin, "creator.block", creator=self.creator, request=request)
        self.assertEqual(row.ip, "203.0.113.7")

    def test_ip_falls_back_to_remote_addr(self):
        request = RequestFactory().post("/", REMOTE_ADDR="198.51.100.4")
        self.assertEqual(log_admin_action(self.admin, "creator.block", request=request).ip,
                         "198.51.100.4")
        v6 = RequestFactory().post("/", HTTP_X_FORWARDED_FOR="2001:db8::1")
        self.assertEqual(log_admin_action(self.admin, "creator.block", request=v6).ip,
                         "2001:db8::1")

    def test_garbage_forwarded_for_does_not_break_the_action(self):
        # Postgres не примет в поле адреса произвольную строку: чужой заголовок
        # не должен откатывать действие администратора.
        request = RequestFactory().post("/", HTTP_X_FORWARDED_FOR="<script>, 1.2.3.4",
                                        REMOTE_ADDR="198.51.100.4")
        self.assertEqual(log_admin_action(self.admin, "creator.block", request=request).ip,
                         "198.51.100.4")
        request.META["REMOTE_ADDR"] = ""
        self.assertIsNone(log_admin_action(self.admin, "creator.block", request=request).ip)

    def test_works_with_drf_request(self):
        from rest_framework.request import Request

        request = Request(RequestFactory().post("/", HTTP_X_FORWARDED_FOR="203.0.113.7"))
        self.assertEqual(log_admin_action(self.admin, "level.edit", request=request).ip,
                         "203.0.113.7")

    def test_raises_without_actor(self):
        from django.contrib.auth import get_user_model
        from django.contrib.auth.models import AnonymousUser

        for actor in (None, AnonymousUser(), get_user_model()(email="unsaved@example.com")):
            with self.assertRaises(ValueError) as cm:
                log_admin_action(actor, "creator.block", creator=self.creator)
            self.assertEqual(str(cm.exception), "actor_required")
        self.assertEqual(AdminActionLog.objects.count(), 0)

    def test_raises_on_unknown_action(self):
        for action in ("", None, "creator.delete", "withdrawal.pay"):
            with self.assertRaises(ValueError) as cm:
                log_admin_action(self.admin, action)
            self.assertEqual(str(cm.exception), "action_unknown")
        self.assertEqual(AdminActionLog.objects.count(), 0)

    def test_allowed_actions_are_exactly_the_spec_list(self):
        self.assertEqual(set(ADMIN_ACTIONS), SPEC_ACTIONS)
        max_length = AdminActionLog._meta.get_field("action").max_length
        for action in sorted(SPEC_ACTIONS):
            self.assertLessEqual(len(action), max_length)
            log_admin_action(self.admin, action)
        self.assertEqual(AdminActionLog.objects.count(), len(SPEC_ACTIONS))

    def test_database_failure_is_raised_not_swallowed(self):
        with mock.patch.object(AdminActionLog.objects, "create", side_effect=RuntimeError("db")):
            with self.assertRaises(RuntimeError):
                log_admin_action(self.admin, "creator.block")

    def test_rollback_of_outer_transaction_removes_the_row(self):
        withdrawal = f.make_withdrawal(self.creator, logged=False)

        class Boom(Exception):
            pass

        with self.assertRaises(Boom):
            with transaction.atomic():
                type(withdrawal).objects.filter(pk=withdrawal.pk).update(status="approved")
                log_admin_action(self.admin, "withdrawal.approve", target=withdrawal,
                                 creator=self.creator)
                self.assertEqual(AdminActionLog.objects.count(), 1)
                raise Boom()
        self.assertEqual(AdminActionLog.objects.count(), 0)
        withdrawal.refresh_from_db()
        self.assertEqual(withdrawal.status, "review")

    def test_failed_log_rolls_back_the_action(self):
        withdrawal = f.make_withdrawal(self.creator, logged=False)
        with self.assertRaises(ValueError):
            with transaction.atomic():
                type(withdrawal).objects.filter(pk=withdrawal.pk).update(status="approved")
                log_admin_action(None, "withdrawal.approve", target=withdrawal)
        withdrawal.refresh_from_db()
        self.assertEqual(withdrawal.status, "review")
