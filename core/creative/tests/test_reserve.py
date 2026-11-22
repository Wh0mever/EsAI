"""Резерв Creative Studio в общих суммах сайта и гонка за последние кредиты (только Postgres)."""
from __future__ import annotations

import threading
from unittest import mock, skipUnless

from django.db import connection
from django.test import TransactionTestCase, override_settings

from creative import reserve
from creative.models import CreativeJob
from plans.wallet import available_tokens, transferable_tokens
from vstudio.reserve import creative_reserved, total_reserved

from .helpers import CreativeTestCase, make_user


class ReserveSumTests(CreativeTestCase):
    def test_creative_reserve_in_site_totals(self):
        user = make_user(balance=100)
        CreativeJob.objects.create(user=user, tool_slug="portrait", kind="image", params={},
                                   credits_quoted=30, credits_reserved=30)
        CreativeJob.objects.create(user=user, tool_slug="portrait", kind="image", params={}, credits_quoted=5,
                                   credits_reserved=5, status="done", charge_state="charged")
        self.assertEqual(creative_reserved(user), 30)
        self.assertEqual(total_reserved(user), 30)
        self.assertEqual(total_reserved(user, strict=True), 30)
        self.assertEqual(available_tokens(user), 70)
        self.assertLessEqual(transferable_tokens(user), 70)

    def test_charge_on_delivery_clawback_partial(self):
        user = make_user(balance=3)
        charge = reserve.charge_on_delivery(user, 10, "creative_image", meta={"job": "x"})
        self.assertEqual((charge.credits, charge.partial), (3, True))
        with self.assertRaises(ValueError):
            reserve.charge_on_delivery(user, 1, "vstudio_image")

    def test_open_reserve_check_constraint(self):
        from django.db import IntegrityError, transaction

        user = make_user(balance=10)
        job = CreativeJob.objects.create(user=user, tool_slug="portrait", kind="image", params={},
                                         credits_quoted=1, credits_reserved=1)
        with self.assertRaises(IntegrityError), transaction.atomic():
            CreativeJob.objects.filter(pk=job.pk).update(status="done")


@skipUnless(connection.vendor == "postgresql", "настоящая гонка замков — только на Postgres")
@override_settings(CREATIVE_MODE="on")
class LastCreditsRaceTests(TransactionTestCase):
    def test_two_runs_for_the_last_credits(self):
        user = make_user(balance=14)
        results = []

        def run(cid):
            from django.db import connection as conn
            try:
                with mock.patch("creative.storage.storage_ready", return_value=(True, "")):
                    with reserve.spend_gate(user, 14, kind="image", client_request_id=cid) as locked:
                        CreativeJob.objects.create(user=locked, tool_slug="portrait", kind="image", params={},
                                                   credits_quoted=14, credits_reserved=14, client_request_id=cid)
                results.append("ok")
            except reserve.SpendRefused as exc:
                results.append(exc.status)
            finally:
                conn.close()

        threads = [threading.Thread(target=run, args=(f"c{n}",)) for n in range(2)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(sorted(map(str, results)), ["402", "ok"])
        self.assertEqual(CreativeJob.objects.filter(user=user).count(), 1)
