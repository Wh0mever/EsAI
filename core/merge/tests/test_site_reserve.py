"""Резерв склейки виден общим гейтам сайта; списание подписано в леджере."""
from __future__ import annotations

from merge import services
from plans.models import TokenTransactionReason
from plans.wallet import available_tokens
from vstudio.reserve import balance_snapshot, total_reserved

from .helpers import MediaTestCase, client_for


class SiteReserveTests(MediaTestCase):
    def test_running_merge_holds_credits_for_the_whole_site(self):
        user = self.user(balance=100)
        self.project(user, [self.take(user), self.scene(user)], status="rendering",
                     credits_reserved=20)
        self.project(user, [self.take(user), self.scene(user)], status="failed")
        self.assertEqual(total_reserved(user), 20)
        self.assertEqual(total_reserved(user, strict=True), 20)
        self.assertEqual(available_tokens(user), 80)
        self.assertEqual(balance_snapshot(user, 20)["after"], 60)

    def test_someone_elses_merge_is_not_counted(self):
        user, other = self.user(balance=100), self.user(balance=100)
        self.project(other, [self.take(other), self.scene(other)], status="queued",
                     credits_reserved=20)
        self.assertEqual(total_reserved(user), 0)
        self.assertEqual(total_reserved(other), 20)

    def test_config_counts_the_merge_reserve_once(self):
        user = self.user(balance=100)
        self.project(user, [self.take(user), self.scene(user)], status="queued",
                     credits_reserved=20)
        body = client_for(user).get("/api/merge/config/").json()
        self.assertEqual(body["balance"], {"balance": 100, "reserved": 20, "available": 80,
                                           "after": 60})

    def test_ledger_reason_has_a_label(self):
        self.assertEqual(services.REASON, TokenTransactionReason.MERGE_VIDEO.value)
        self.assertEqual(TokenTransactionReason(services.REASON).label, "Склейка видео")
