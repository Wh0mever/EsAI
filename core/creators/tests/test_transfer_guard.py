"""Creator Credits нельзя перевести другому человеку.

Дыра, которую закрывает защита: «купил 100, потратил 100, получил 100 от EsAI».
По старой формуле (куплено минус отправлено, не больше баланса) эти 100
выданных кредитов считались бы купленными и уходили переводом.
"""
from unittest import mock

from rest_framework.test import APIClient

from plans.wallet import (
    TRANSFERABLE_IN_REASONS,
    _creator_credits_left,
    charge_tokens,
    credit_tokens,
    transferable_tokens,
)

from .. import credits
from . import factories as f


class TransferGuardTests(f.CreatorsTestCase):
    def setUp(self):
        super().setUp()
        self.admin = f.make_user(superuser=True)
        self.creator = f.make_creator(f.make_user("sender@example.com"))
        self.sender = self.creator.user
        self.friend = f.make_user("friend@example.com")
        self.api = APIClient()
        self.api.force_authenticate(self.sender)

    def _send(self, amount):
        return self.api.post("/api/users/transfer/", {"recipient": "friend@example.com",
                                                     "amount": amount}, format="json")

    def _friend_balance(self):
        self.friend.refresh_from_db()
        return self.friend.token_balance

    def test_bought_spent_granted_is_not_transferable(self):
        credit_tokens(self.sender, 100, "purchase", meta={"order_id": "o1"})
        charge_tokens(self.sender, 100, "chat")
        credits.grant(self.creator, 100, "start", actor=self.admin)

        self.assertEqual(transferable_tokens(self.sender), 0)
        response = self._send(10)
        self.assertEqual(response.status_code, 400, response.data)
        self.assertEqual(response.data["transferable"], 0)
        self.assertEqual(self._friend_balance(), 0)
        self.sender.refresh_from_db()
        self.assertEqual(self.sender.token_balance, 100)

    def test_purchased_part_stays_transferable(self):
        credit_tokens(self.sender, 100, "purchase", meta={"order_id": "o1"})
        credits.grant(self.creator, 100, "start", actor=self.admin)
        self.assertEqual(transferable_tokens(self.sender), 100)

        self.assertEqual(self._send(101).status_code, 400)
        self.assertEqual(self._send(100).status_code, 200)
        self.assertEqual(self._friend_balance(), 100)
        # Купленное ушло, выданное осталось на балансе и по-прежнему не переводится.
        self.assertEqual(credits.remaining(self.sender), 100)
        self.assertEqual(transferable_tokens(self.sender), 0)
        self.assertEqual(self._send(1).status_code, 400)
        self.assertEqual(self._friend_balance(), 100)

    def test_spending_takes_creator_credits_first(self):
        credit_tokens(self.sender, 100, "purchase", meta={"order_id": "o1"})
        credits.grant(self.creator, 100, "start", actor=self.admin)
        charge_tokens(self.sender, 70, "chat")
        # Потрачены выданные: купленные 100 целы и переводятся.
        self.assertEqual(credits.remaining(self.sender), 30)
        self.assertEqual(transferable_tokens(self.sender), 100)
        charge_tokens(self.sender, 60, "chat")
        self.assertEqual(credits.remaining(self.sender), 0)
        self.assertEqual(transferable_tokens(self.sender), 70)

    def test_grant_alone_is_never_transferable(self):
        credits.grant(self.creator, 5000, "special", actor=self.admin)
        self.assertEqual(transferable_tokens(self.sender), 0)
        response = self.api.get("/api/users/transfer/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data, {"transferable": 0, "balance": 5000})

    def test_get_reports_the_guarded_pool(self):
        credit_tokens(self.sender, 40, "purchase", meta={"order_id": "o1"})
        credits.grant(self.creator, 100, "start", actor=self.admin)
        response = self.api.get("/api/users/transfer/")
        self.assertEqual(response.data, {"transferable": 40, "balance": 140})

    def test_reserves_still_subtract(self):
        credit_tokens(self.sender, 100, "purchase", meta={"order_id": "o1"})
        credits.grant(self.creator, 100, "start", actor=self.admin)
        with mock.patch("vstudio.reserve.total_reserved", return_value=30):
            # 200 на балансе − 30 обещано роликам − 100 выданных = 70.
            self.assertEqual(transferable_tokens(self.sender), 70)
        with mock.patch("vstudio.reserve.total_reserved", return_value=150):
            self.assertEqual(transferable_tokens(self.sender), 0)
        self.assertEqual(transferable_tokens(self.sender), 100)

    def test_credits_moved_by_account_merge_stay_non_transferable(self):
        # Слияние аккаунтов переносит остаток той же причиной, без строки Creator.
        plain = f.make_user()
        credit_tokens(plain, 80, "creator_credit", meta={"category": "merge", "note": "",
                                                         "by_id": None, "grant_id": ""})
        credit_tokens(plain, 20, "purchase", meta={"order_id": "o1"})
        self.assertEqual(transferable_tokens(plain), 20)

    def test_creator_credit_is_not_a_transferable_reason(self):
        self.assertEqual(TRANSFERABLE_IN_REASONS, ("purchase", "referral", "transfer_in"))

    def test_received_transfer_can_be_passed_on_but_not_the_grant(self):
        credit_tokens(self.sender, 50, "transfer_in", meta={"from_user_id": self.friend.pk})
        credits.grant(self.creator, 100, "start", actor=self.admin)
        self.assertEqual(transferable_tokens(self.sender), 50)


class OrdinaryUsersTests(f.CreatorsTestCase):
    """У людей без выдач цифры прежние, и стоит это один лишний запрос."""

    def setUp(self):
        super().setUp()
        self.sender = f.make_user()

    def test_numbers_are_unchanged(self):
        credit_tokens(self.sender, 40, "daily_bonus")
        credit_tokens(self.sender, 30, "promo")
        self.assertEqual(transferable_tokens(self.sender), 0)
        credit_tokens(self.sender, 100, "purchase", meta={"order_id": "o1"})
        self.assertEqual(transferable_tokens(self.sender), 100)
        charge_tokens(self.sender, 60, "transfer_out", meta={"to_user_id": 1})
        self.assertEqual(transferable_tokens(self.sender), 40)
        # Подарочное тратится первым — купленные 40 остаются к переводу.
        charge_tokens(self.sender, 70, "chat")
        self.assertEqual(transferable_tokens(self.sender), 40)

    def test_guard_is_zero_without_grants(self):
        credit_tokens(self.sender, 100, "purchase", meta={"order_id": "o1"})
        self.assertEqual(_creator_credits_left(self.sender), 0)
        self.assertEqual(_creator_credits_left(None), 0)

    def test_failing_creators_code_does_not_break_transfers(self):
        credit_tokens(self.sender, 100, "purchase", meta={"order_id": "o1"})
        with mock.patch("creators.credits.remaining", side_effect=RuntimeError("boom")):
            self.assertEqual(_creator_credits_left(self.sender), 0)
            self.assertEqual(transferable_tokens(self.sender), 100)
        with mock.patch.dict("sys.modules", {"creators.credits": None}):
            # Модуль не импортируется вовсе — перевод работает как раньше.
            self.assertEqual(_creator_credits_left(self.sender), 0)
            self.assertEqual(transferable_tokens(self.sender), 100)
