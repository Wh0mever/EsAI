"""Creator Credits: ручная выдача, остаток и история.

Остаток нигде не хранится — он считается по леджеру, и от него зависит, сколько
человек может перевести другому. Поэтому главное здесь — правило «выданные
кредиты тратятся первыми, переводы их не трогают» и то, что подсчёт не падает.
"""
from unittest import mock

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.db import OperationalError, connection
from django.test.utils import CaptureQueriesContext

from audit.models import AdminActionLog
from plans.models import TokenTransaction
from plans.wallet import charge_tokens, clawback_tokens, credit_tokens
from users.models import Notification

from .. import credits
from ..errors import CreatorsError
from ..models import Creator
from . import factories as f


def _data_queries(ctx) -> list:
    """Запросы без SAVEPOINT / RELEASE: точка сохранения — не обращение к данным."""
    return [q["sql"] for q in ctx.captured_queries if "SAVEPOINT" not in q["sql"].upper()]


def _db_blinks_on(table):
    def wrapper(execute, sql, params, many, context):
        if table in sql:
            raise OperationalError("db blinked")
        return execute(sql, params, many, context)
    return wrapper


def _grants(user):
    return TokenTransaction.objects.filter(user=user, reason="creator_credit")


class GrantTests(f.CreatorsTestCase):
    def setUp(self):
        super().setUp()
        self.admin = f.make_user(superuser=True)
        self.creator = f.make_creator()
        self.user = self.creator.user
        patcher = mock.patch("botapi.tasks.notify")
        self.tg = patcher.start()
        self.addCleanup(patcher.stop)

    def _code(self, *args, **kwargs):
        with self.assertRaises(CreatorsError) as caught:
            credits.grant(*args, **kwargs)
        return caught.exception

    def test_grant_writes_ledger_row_with_safe_meta(self):
        tx = credits.grant(self.creator, 1000, "start", actor=self.admin,
                           note="  Добро пожаловать ")
        self.assertIsInstance(tx, TokenTransaction)
        tx.refresh_from_db()
        self.assertEqual(tx.user, self.user)
        self.assertEqual(tx.reason, "creator_credit")
        self.assertEqual(tx.delta, 1000)
        self.assertEqual(tx.balance_after, 1000)
        self.assertEqual(set(tx.meta), {"category", "note", "by_id", "grant_id"})
        self.assertEqual(tx.meta["category"], "start")
        self.assertEqual(tx.meta["note"], "Добро пожаловать")
        self.assertEqual(tx.meta["by_id"], self.admin.pk)
        self.assertEqual(len(tx.meta["grant_id"]), 32)
        self.user.refresh_from_db()
        self.assertEqual(self.user.token_balance, 1000)

    def test_amount_is_added_to_the_common_wallet(self):
        credit_tokens(self.user, 250, "purchase", meta={"order_id": "o1"})
        tx = credits.grant(self.creator, "500", "content", actor=self.admin)
        self.assertEqual(tx.delta, 500)
        self.assertEqual(tx.balance_after, 750)

    def test_note_is_cut_to_300_characters(self):
        tx = credits.grant(self.creator, 10, "other", actor=self.admin, note="я" * 500)
        self.assertEqual(len(tx.meta["note"]), 300)

    def test_amount_validation(self):
        for bad in (0, -5, credits.MAX_GRANT + 1, "abc", "", None, 12.5, "12.5", True, [100]):
            error = self._code(self.creator, bad, "start", actor=self.admin)
            self.assertEqual((error.code, error.http), ("amount_invalid", 400), bad)
        self.assertEqual(_grants(self.user).count(), 0)
        self.assertEqual(AdminActionLog.objects.filter(action="credits.grant").count(), 0)

    def test_amount_bounds_are_inclusive(self):
        self.assertEqual(credits.grant(self.creator, 1, "start", actor=self.admin).delta, 1)
        self.assertEqual(credits.grant(self.creator, credits.MAX_GRANT, "start",
                                       actor=self.admin).delta, credits.MAX_GRANT)

    def test_category_validation(self):
        # "merge" — подпись для слияния аккаунтов, администратор её выбрать не может.
        for bad in ("bonus", "", None, "merge", "START"):
            error = self._code(self.creator, 100, bad, actor=self.admin)
            self.assertEqual(error.code, "category_invalid", bad)
        self.assertEqual(_grants(self.user).count(), 0)

    def test_every_client_category_is_accepted(self):
        self.assertEqual(credits.CATEGORIES,
                         ("start", "activity", "content", "result", "special", "other"))
        for index, category in enumerate(credits.CATEGORIES, start=1):
            credits.grant(self.creator, index, category, actor=self.admin)
            self.assertIn(category, credits.CATEGORY_LABELS)
        self.assertEqual(_grants(self.user).count(), 6)

    def test_blocked_creator_gets_nothing(self):
        blocked = f.make_creator(status="blocked")
        error = self._code(blocked, 100, "start", actor=self.admin)
        self.assertEqual((error.code, error.http), ("creator_blocked", 403))
        self.assertEqual(_grants(blocked.user).count(), 0)

    def test_status_is_read_from_the_database(self):
        # Объект в руках ещё «активен», а креатора уже заблокировали.
        Creator.objects.filter(pk=self.creator.pk).update(status="blocked")
        self.assertEqual(self.creator.status, "active")
        self.assertEqual(self._code(self.creator, 100, "start", actor=self.admin).code,
                         "creator_blocked")

    def test_owner_is_read_from_the_database(self):
        # Аккаунт креатора слили с другим: строка Creator уже у нового владельца.
        owner = f.make_user()
        Creator.objects.filter(pk=self.creator.pk).update(user=owner)
        tx = credits.grant(self.creator, 100, "start", actor=self.admin)
        self.assertEqual(tx.user, owner)
        self.assertEqual(_grants(self.user).count(), 0)

    def test_refusal_does_not_arm_the_duplicate_guard(self):
        Creator.objects.filter(pk=self.creator.pk).update(status="blocked")
        self._code(self.creator, 100, "start", actor=self.admin)
        Creator.objects.filter(pk=self.creator.pk).update(status="active")
        credits.grant(self.creator, 100, "start", actor=self.admin)
        self.assertEqual(_grants(self.user).count(), 1)

    def test_duplicate_guard(self):
        credits.grant(self.creator, 100, "start", actor=self.admin)
        error = self._code(self.creator, 100, "start", actor=self.admin)
        self.assertEqual((error.code, error.http), ("duplicate_request", 409))
        self.assertEqual(_grants(self.user).count(), 1)
        # Другая сумма, другая причина, другой креатор, другой админ — не повтор.
        credits.grant(self.creator, 101, "start", actor=self.admin)
        credits.grant(self.creator, 100, "content", actor=self.admin)
        credits.grant(f.make_creator(), 100, "start", actor=self.admin)
        credits.grant(self.creator, 100, "start", actor=f.make_user(superuser=True))
        self.assertEqual(_grants(self.user).count(), 4)
        # Окно в 10 секунд прошло (кэш очищен) — та же выдача снова разрешена.
        cache.clear()
        credits.grant(self.creator, 100, "start", actor=self.admin)
        self.assertEqual(_grants(self.user).count(), 5)

    def test_failed_grant_rolls_back_and_frees_the_guard(self):
        with mock.patch("creators.credits.log_admin_action", side_effect=RuntimeError("log")):
            with self.assertRaises(RuntimeError):
                credits.grant(self.creator, 100, "start", actor=self.admin)
        # Журнал не записался — не осталось ни кредитов, ни строки леджера.
        self.assertEqual(_grants(self.user).count(), 0)
        self.user.refresh_from_db()
        self.assertEqual(self.user.token_balance, 0)
        credits.grant(self.creator, 100, "start", actor=self.admin)
        self.assertEqual(_grants(self.user).count(), 1)

    def test_unavailable_cache_does_not_block_the_grant(self):
        with mock.patch("creators.credits.cache.add", side_effect=RuntimeError("redis")), \
                self.assertLogs("creators", level="WARNING"):
            credits.grant(self.creator, 100, "start", actor=self.admin)
        self.assertEqual(_grants(self.user).count(), 1)

    def test_log_row(self):
        before = AdminActionLog.objects.filter(action="credits.grant").count()
        tx = credits.grant(self.creator, 700, "result", actor=self.admin, note="за ролик")
        rows = AdminActionLog.objects.filter(action="credits.grant")
        self.assertEqual(rows.count(), before + 1)
        row = rows.first()
        self.assertEqual(row.actor, self.admin)
        self.assertEqual(row.creator, self.creator)
        self.assertEqual((row.target_type, row.target_id),
                         ("plans.tokentransaction", str(tx.pk)))
        self.assertEqual(row.after, {"amount": 700, "category": "result", "note": "за ролик",
                                     "grant_id": tx.meta["grant_id"], "balance_after": 700})

    def test_notification(self):
        with self.captureOnCommitCallbacks(execute=True):
            credits.grant(self.creator, 500, "activity", actor=self.admin)
        notification = Notification.objects.get()
        self.assertEqual(notification.title, "Получены Creator Credits")
        self.assertEqual(notification.body, "Вам начислено 500 Creator Credits.")
        self.assertEqual(list(notification.recipients.all()), [self.user])
        self.assertEqual(self.tg.call_args.args[1], "creator")

    def test_unknown_creator(self):
        ghost = Creator(pk=999_999)
        self.assertEqual(self._code(ghost, 100, "start", actor=self.admin).code, "not_found")


class RemainingTests(f.CreatorsTestCase):
    def setUp(self):
        super().setUp()
        self.user = f.make_user()

    def _grant(self, amount, user=None):
        credit_tokens(user or self.user, amount, "creator_credit",
                      meta={"category": "start", "note": "", "by_id": None, "grant_id": "g"})

    def test_no_grants_is_zero_with_one_query(self):
        credit_tokens(self.user, 100, "purchase", meta={"order_id": "o1"})
        charge_tokens(self.user, 40, "chat")
        with CaptureQueriesContext(connection) as ctx:
            self.assertEqual(credits.remaining(self.user), 0)
        self.assertEqual(len(_data_queries(ctx)), 1, ctx.captured_queries)

    def test_no_user_is_zero_without_queries(self):
        with self.assertNumQueries(0):
            self.assertEqual(credits.remaining(None), 0)
            self.assertEqual(credits.remaining(get_user_model()()), 0)
            self.assertEqual(credits.granted_total(None), 0)

    def test_grant_then_spends(self):
        self._grant(100)
        self.assertEqual(credits.remaining(self.user), 100)
        charge_tokens(self.user, 30, "chat")
        self.assertEqual(credits.remaining(self.user), 70)
        charge_tokens(self.user, 70, "vstudio_video")
        self.assertEqual(credits.remaining(self.user), 0)

    def test_creator_credits_are_spent_first(self):
        credit_tokens(self.user, 100, "purchase", meta={"order_id": "o1"})
        self._grant(100)
        charge_tokens(self.user, 60, "chat")
        # Баланс 140: списание целиком легло на Creator Credits, купленные не тронуты.
        self.assertEqual(credits.remaining(self.user), 40)
        charge_tokens(self.user, 90, "chat")
        self.assertEqual(credits.remaining(self.user), 0)
        self.user.refresh_from_db()
        self.assertEqual(self.user.token_balance, 50)

    def test_spends_before_the_first_grant_do_not_count(self):
        credit_tokens(self.user, 100, "purchase", meta={"order_id": "o1"})
        charge_tokens(self.user, 100, "chat")
        self._grant(100)
        self.assertEqual(credits.remaining(self.user), 100)

    def test_second_grant_after_the_first_is_spent(self):
        self._grant(100)
        charge_tokens(self.user, 100, "chat")
        credit_tokens(self.user, 500, "purchase", meta={"order_id": "o1"})
        charge_tokens(self.user, 200, "chat")
        self._grant(50)
        charge_tokens(self.user, 20, "chat")
        self.assertEqual(credits.remaining(self.user), 30)

    def test_transfer_out_does_not_reduce_it(self):
        credit_tokens(self.user, 100, "purchase", meta={"order_id": "o1"})
        self._grant(100)
        charge_tokens(self.user, 50, "transfer_out", meta={"to_user_id": 1})
        self.assertEqual(credits.remaining(self.user), 100)

    def test_refund_clawback_reduces_it(self):
        credit_tokens(self.user, 100, "purchase", meta={"order_id": "o1"})
        self._grant(100)
        clawback_tokens(self.user, 60, "refund", meta={"kind": "chargeback_clawback"})
        self.assertEqual(credits.remaining(self.user), 40)

    def test_never_above_the_balance(self):
        self._grant(100)
        # Баланс правили мимо леджера (например, в админке Django).
        get_user_model().objects.filter(pk=self.user.pk).update(token_balance=30)
        self.assertEqual(credits.remaining(self.user), 30)

    def test_positive_rows_of_other_reasons_do_not_add(self):
        self._grant(100)
        charge_tokens(self.user, 100, "chat")
        credit_tokens(self.user, 300, "daily_bonus")
        credit_tokens(self.user, 300, "promo")
        self.assertEqual(credits.remaining(self.user), 0)

    def test_other_users_rows_are_not_mixed_in(self):
        other = f.make_user()
        self._grant(100)
        self._grant(40, other)
        charge_tokens(other, 40, "chat")
        self.assertEqual(credits.remaining(self.user), 100)
        self.assertEqual(credits.remaining(other), 0)

    def test_never_raises(self):
        self._grant(100)
        with mock.patch("creators.credits._fold", side_effect=RuntimeError("boom")), \
                self.assertLogs("creators", level="ERROR"):
            self.assertEqual(credits.remaining(self.user), 0)

    def test_db_failure_keeps_the_callers_transaction_alive(self):
        self._grant(100)
        with connection.execute_wrapper(_db_blinks_on("plans_tokentransaction")), \
                self.assertLogs("creators", level="ERROR"):
            self.assertEqual(credits.remaining(self.user), 0)
        # Точка сохранения: транзакция вызывающего осталась рабочей.
        self.assertEqual(get_user_model().objects.filter(pk=self.user.pk).count(), 1)
        self.assertEqual(credits.remaining(self.user), 100)

    def test_query_count_does_not_grow_with_spends(self):
        self._grant(1000)
        charge_tokens(self.user, 1, "chat")
        with CaptureQueriesContext(connection) as few:
            credits.remaining(self.user)
        for _ in range(15):
            charge_tokens(self.user, 1, "chat")
        with CaptureQueriesContext(connection) as many:
            self.assertEqual(credits.remaining(self.user), 984)
        self.assertEqual(len(_data_queries(many)), len(_data_queries(few)))
        self.assertEqual(len(_data_queries(many)), 3)

    def test_granted_total(self):
        self.assertEqual(credits.granted_total(self.user), 0)
        self._grant(100)
        self._grant(250)
        credit_tokens(self.user, 999, "purchase", meta={"order_id": "o1"})
        charge_tokens(self.user, 300, "chat")
        self.assertEqual(credits.granted_total(self.user), 350)


class HistoryTests(f.CreatorsTestCase):
    def setUp(self):
        super().setUp()
        self.admin = f.make_user("boss@example.com", superuser=True)
        self.creator = f.make_creator()
        self.user = self.creator.user

    def test_rows_newest_first(self):
        credits.grant(self.creator, 100, "start", actor=self.admin, note="старт")
        credits.grant(self.creator, 250, "content", actor=self.admin)
        credit_tokens(self.user, 500, "purchase", meta={"order_id": "o1"})
        rows = credits.history(self.user)
        self.assertEqual([row["amount"] for row in rows], [250, 100])
        first = rows[1]
        self.assertEqual(set(first), {"id", "date", "amount", "category", "category_label",
                                      "note", "balance_after"})
        self.assertEqual(first["category"], "start")
        self.assertEqual(first["category_label"], "Старт")
        self.assertEqual(first["note"], "старт")
        self.assertEqual(first["balance_after"], 100)
        self.assertEqual(rows[0]["category_label"], "За контент")
        self.assertEqual(rows[0]["note"], "")
        tx = TokenTransaction.objects.get(pk=first["id"])
        self.assertEqual(first["date"], tx.created_at)

    def test_creator_does_not_see_who_granted(self):
        credits.grant(self.creator, 100, "start", actor=self.admin)
        for rows in (credits.history(self.user), credits.ledger(self.user)):
            for row in rows:
                self.assertNotIn("by_id", row)
                self.assertNotIn("by_email", row)
                self.assertNotIn("meta", row)
                self.assertNotIn("boss@example.com", repr(row))
                self.assertNotIn("grant_id", row)

    def test_admin_sees_who_granted(self):
        credits.grant(self.creator, 100, "start", actor=self.admin)
        row = credits.history(self.user, for_admin=True)[0]
        self.assertEqual(row["by_id"], self.admin.pk)
        self.assertEqual(row["by_email"], "boss@example.com")
        self.assertNotIn("meta", row)

    def test_merge_row_has_its_own_label_and_no_admin(self):
        credit_tokens(self.user, 70, "creator_credit", meta={
            "category": "merge", "note": "", "by_id": None, "grant_id": "",
            "kind": "merge_in", "merge_from": 5})
        row = credits.history(self.user, for_admin=True)[0]
        self.assertEqual(row["category"], "merge")
        self.assertEqual(row["category_label"], "Перенос с аккаунта Telegram")
        self.assertIsNone(row["by_id"])
        self.assertIsNone(row["by_email"])

    def test_row_without_meta_is_shown_as_other(self):
        credit_tokens(self.user, 5, "creator_credit")
        row = credits.history(self.user, for_admin=True)[0]
        self.assertEqual((row["category"], row["category_label"], row["note"]),
                         ("", "Другое", ""))

    def test_limit(self):
        for index in range(1, 5):
            credits.grant(self.creator, index, "start", actor=self.admin)
        self.assertEqual([row["amount"] for row in credits.history(self.user, limit=2)], [4, 3])
        self.assertEqual(credits.history(None), [])

    def test_admin_emails_come_with_one_query(self):
        for index in range(1, 6):
            credits.grant(self.creator, index, "start", actor=f.make_user(superuser=True))
        with self.assertNumQueries(2):
            rows = credits.history(self.user, for_admin=True)
        self.assertEqual(len({row["by_email"] for row in rows}), 5)


class LedgerTests(f.CreatorsTestCase):
    def setUp(self):
        super().setUp()
        self.admin = f.make_user("boss@example.com", superuser=True)
        self.creator = f.make_creator()
        self.user = self.creator.user

    def test_grants_and_spends(self):
        credits.grant(self.creator, 100, "start", actor=self.admin, note="старт")
        charge_tokens(self.user, 30, "chat")
        charge_tokens(self.user, 20, "vstudio_video")
        rows = credits.ledger(self.user)
        self.assertEqual([(row["kind"], row["amount"], row["remaining_after"]) for row in rows],
                         [("spend", -20, 50), ("spend", -30, 70), ("grant", 100, 100)])
        self.assertEqual(credits.remaining(self.user), 50)

        video, chat, grant = rows
        self.assertEqual(set(chat), {"id", "date", "amount", "kind", "reason", "reason_label",
                                     "remaining_after"})
        self.assertEqual((chat["reason"], chat["reason_label"]), ("chat", "Списание за чат"))
        self.assertEqual(video["reason_label"], "Видеостудия: видео")
        self.assertEqual(set(grant), {"id", "date", "amount", "category", "category_label",
                                      "note", "balance_after", "kind", "remaining_after"})
        self.assertEqual((grant["category_label"], grant["note"]), ("Старт", "старт"))

    def test_charge_larger_than_what_is_left_shows_only_the_creator_part(self):
        credit_tokens(self.user, 100, "purchase", meta={"order_id": "o1"})
        credits.grant(self.creator, 30, "start", actor=self.admin)
        charge_tokens(self.user, 50, "chat")
        charge_tokens(self.user, 10, "chat")
        rows = credits.ledger(self.user)
        # Из 50 списанных на Creator Credits пришлось 30; следующее списание — уже не они.
        self.assertEqual([(row["kind"], row["amount"], row["remaining_after"]) for row in rows],
                         [("spend", -30, 0), ("grant", 30, 30)])

    def test_transfer_out_is_not_a_spend(self):
        credit_tokens(self.user, 100, "purchase", meta={"order_id": "o1"})
        credits.grant(self.creator, 100, "start", actor=self.admin)
        charge_tokens(self.user, 40, "transfer_out", meta={"to_user_id": 1})
        self.assertEqual([row["kind"] for row in credits.ledger(self.user)], ["grant"])

    def test_unknown_reason_is_shown_as_is(self):
        credits.grant(self.creator, 100, "start", actor=self.admin)
        charge_tokens(self.user, 5, "brand_new_reason")
        row = credits.ledger(self.user)[0]
        self.assertEqual((row["reason"], row["reason_label"]),
                         ("brand_new_reason", "brand_new_reason"))

    def test_granted_minus_remaining_equals_spends(self):
        credit_tokens(self.user, 300, "purchase", meta={"order_id": "o1"})
        credits.grant(self.creator, 100, "start", actor=self.admin)
        charge_tokens(self.user, 45, "chat")
        credits.grant(self.creator, 60, "content", actor=self.admin)
        charge_tokens(self.user, 80, "cartoon_scene")
        clawback_tokens(self.user, 10, "refund")
        spent = -sum(row["amount"] for row in credits.ledger(self.user) if row["kind"] == "spend")
        self.assertEqual(spent, 135)
        self.assertEqual(credits.granted_total(self.user) - credits.remaining(self.user), spent)

    def test_limit_keeps_the_newest_rows(self):
        credits.grant(self.creator, 100, "start", actor=self.admin)
        for _ in range(5):
            charge_tokens(self.user, 10, "chat")
        rows = credits.ledger(self.user, limit=3)
        self.assertEqual([row["remaining_after"] for row in rows], [50, 60, 70])
        self.assertEqual(credits.ledger(self.user, limit=0), [])

    def test_admin_identity_only_for_admin(self):
        credits.grant(self.creator, 100, "start", actor=self.admin)
        charge_tokens(self.user, 10, "chat")
        spend, grant = credits.ledger(self.user, for_admin=True)
        self.assertEqual((grant["by_id"], grant["by_email"]),
                         (self.admin.pk, "boss@example.com"))
        self.assertNotIn("by_id", spend)
        self.assertNotIn("meta", grant)

    def test_no_grants(self):
        credit_tokens(self.user, 100, "purchase", meta={"order_id": "o1"})
        charge_tokens(self.user, 10, "chat")
        self.assertEqual(credits.ledger(self.user), [])
        self.assertEqual(credits.ledger(None), [])

    def test_query_count_does_not_grow_with_rows(self):
        credits.grant(self.creator, 1000, "start", actor=self.admin)
        charge_tokens(self.user, 1, "chat")
        with CaptureQueriesContext(connection) as few:
            credits.ledger(self.user, for_admin=True)
        for index in range(10):
            charge_tokens(self.user, 1, "chat")
            credits.grant(self.creator, index + 1, "content", actor=self.admin)
        with CaptureQueriesContext(connection) as many:
            self.assertEqual(len(credits.ledger(self.user, for_admin=True)), 22)
        self.assertEqual(len(many), len(few))


class HistoryAllTests(f.CreatorsTestCase):
    def setUp(self):
        super().setUp()
        self.admin = f.make_user("boss@example.com", superuser=True)
        self.tora = f.make_creator(display_name="Tora")
        self.aziz = f.make_creator(display_name="Aziz")

    def test_all_creators_newest_first(self):
        credits.grant(self.tora, 100, "start", actor=self.admin)
        credits.grant(self.aziz, 200, "content", actor=self.admin, note="за ролик")
        credits.grant(self.tora, 300, "result", actor=self.admin)
        # Списания и покупки во вкладку не попадают.
        charge_tokens(self.tora.user, 50, "chat")
        credit_tokens(self.aziz.user, 500, "purchase", meta={"order_id": "o1"})

        total, rows = credits.history_all()
        self.assertEqual(total, 3)
        self.assertEqual([(row["amount"], row["creator_name"]) for row in rows],
                         [(300, "Tora"), (200, "Aziz"), (100, "Tora")])
        row = rows[1]
        self.assertEqual(set(row), {"id", "date", "amount", "category", "category_label", "note",
                                    "balance_after", "by_id", "by_email", "creator_id",
                                    "creator_name"})
        self.assertEqual(row["creator_id"], self.aziz.pk)
        self.assertEqual((row["by_id"], row["by_email"]), (self.admin.pk, "boss@example.com"))
        self.assertEqual((row["category_label"], row["note"]), ("За контент", "за ролик"))

    def test_creator_filter(self):
        credits.grant(self.tora, 100, "start", actor=self.admin)
        credits.grant(self.aziz, 200, "start", actor=self.admin)
        total, rows = credits.history_all(creator_id=self.aziz.pk)
        self.assertEqual((total, [row["amount"] for row in rows]), (1, [200]))
        self.assertEqual(credits.history_all(creator_id=999_999), (0, []))

    def test_offset_and_limit(self):
        for index in range(1, 6):
            credits.grant(self.tora, index, "start", actor=self.admin)
        total, rows = credits.history_all(offset=1, limit=2)
        self.assertEqual((total, [row["amount"] for row in rows]), (5, [4, 3]))
        total, rows = credits.history_all(offset=50, limit=50)
        self.assertEqual((total, rows), (5, []))

    def test_user_without_creator_row(self):
        # После слияния аккаунтов кредиты могут лежать у человека без строки Creator.
        plain = f.make_user()
        credit_tokens(plain, 70, "creator_credit", meta={"category": "merge", "note": "",
                                                         "by_id": None, "grant_id": ""})
        total, rows = credits.history_all()
        self.assertEqual(total, 1)
        self.assertIsNone(rows[0]["creator_id"])
        self.assertIsNone(rows[0]["creator_name"])
        self.assertEqual(rows[0]["category_label"], "Перенос с аккаунта Telegram")

    def test_without_admin_identity(self):
        credits.grant(self.tora, 100, "start", actor=self.admin)
        _, rows = credits.history_all(for_admin=False)
        self.assertNotIn("by_id", rows[0])
        self.assertNotIn("by_email", rows[0])
        self.assertEqual(rows[0]["creator_name"], "Tora")

    def test_query_count_is_constant(self):
        credits.grant(self.tora, 1, "start", actor=self.admin)
        credits.grant(self.aziz, 2, "start", actor=self.admin)
        with CaptureQueriesContext(connection) as few:
            credits.history_all()
        for index in range(3, 11):
            credits.grant(f.make_creator(), index, "start", actor=f.make_user(superuser=True))
        with CaptureQueriesContext(connection) as many:
            total, rows = credits.history_all()
        self.assertEqual((total, len(rows)), (10, 10))
        self.assertEqual(len(many), len(few))
        # Счётчик, страница, карта креаторов, почты выдавших.
        self.assertEqual(len(many), 4)
