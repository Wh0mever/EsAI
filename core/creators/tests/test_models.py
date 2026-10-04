"""Схема программы Creators: ограничения БД, менеджеры, уровни, ошибки, фабрики.

«Один открытый», «один основной», «один раз за платёж» держит база, а не
проверки в коде — здесь проверяем, что она действительно так себя ведёт
(и на SQLite, на котором идут тесты, и по форме запроса — на Postgres).
"""
from datetime import timedelta
from decimal import Decimal
from unittest import skipUnless

from django.apps import apps
from django.contrib import admin
from django.db import IntegrityError, connection, transaction
from django.db.models import ProtectedError
from django.test import RequestFactory
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone

from audit.models import AdminActionLog
from plans.models import TokenTransaction, TokenTransactionReason

from .. import levels
from ..errors import HTTP, MESSAGES, CreatorsError, error_body
from ..models import (
    Creator,
    CreatorApplication,
    CreatorClick,
    CreatorCode,
    CreatorCommission,
    CreatorLevel,
    CreatorPublication,
    CreatorReferral,
    CreatorWithdrawal,
)
from . import factories as f


class ConstraintTests(f.CreatorsTestCase):
    def assertIntegrityError(self, fn):
        # Отдельная точка сохранения: после ошибки транзакция теста остаётся живой.
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                fn()

    def _application(self, user, **extra):
        fields = {"name": "Tora", "telegram": "@tora", "country": "KG",
                  "occupation": "блогер", "motivation": "хочу"}
        fields.update(extra)
        return CreatorApplication.objects.create(user=user, **fields)

    def test_one_open_application_per_user(self):
        user = f.make_user()
        first = self._application(user)
        self.assertEqual(first.status, "new")
        self.assertEqual(first.other_links, [])
        self.assertIntegrityError(lambda: self._application(user))
        # Отклонённая заявка место не занимает: человек подаёт снова.
        CreatorApplication.objects.filter(pk=first.pk).update(status="rejected")
        self._application(user)
        # У другого пользователя своя открытая заявка.
        self._application(f.make_user())

    def test_code_is_unique_and_stored_upper_case(self):
        creator, other = f.make_creator(), f.make_creator()
        code = CreatorCode.objects.create(code=" tora20 ", creator=creator)
        self.assertEqual(code.code, "TORA20")
        self.assertTrue(code.is_primary and code.is_active)
        self.assertIntegrityError(
            lambda: CreatorCode.objects.create(code="Tora20", creator=other))

    def test_one_primary_code_per_creator(self):
        creator = f.make_creator(code="TORA20")
        self.assertIntegrityError(
            lambda: CreatorCode.objects.create(code="TORA21", creator=creator))
        # Псевдоним (старый код после замены) рядом с основным — можно.
        CreatorCode.objects.create(code="TORA21", creator=creator, is_primary=False)
        self.assertEqual(creator.codes.count(), 2)

    def test_code_row_cannot_be_deleted_with_creator(self):
        creator = f.make_creator(code="TORA20")
        with self.assertRaises(ProtectedError):
            creator.delete()

    def test_one_active_referral_per_user(self):
        a, b = f.make_creator(), f.make_creator()
        user = f.make_user()
        first = f.make_referral(a, user)
        self.assertIntegrityError(lambda: f.make_referral(b, user))
        self.assertIntegrityError(lambda: f.make_referral(a, user))
        # Снятая привязка освобождает место для новой.
        CreatorReferral.objects.filter(pk=first.pk).update(ended_at=timezone.now(),
                                                           end_reason="admin_rebind")
        f.make_referral(b, user)
        self.assertEqual(CreatorReferral.objects.filter(user=user).count(), 2)

    def test_click_dedupe_per_device_and_day(self):
        creator, other = f.make_creator(), f.make_creator()
        today = timezone.localdate()
        row = {"code": "TORA20", "device_key": "dev-1", "day": today}
        CreatorClick.objects.create(creator=creator, **row)
        self.assertIntegrityError(lambda: CreatorClick.objects.create(creator=creator, **row))
        CreatorClick.objects.create(creator=creator, code="TORA20", device_key="dev-2", day=today)
        CreatorClick.objects.create(creator=creator, code="TORA20", device_key="dev-1",
                                    day=today + timedelta(days=1))
        CreatorClick.objects.create(creator=other, **row)
        self.assertEqual(CreatorClick.objects.count(), 4)

    def test_publication_url_counted_once_unless_rejected(self):
        creator, other = f.make_creator(), f.make_creator()
        row = {"network": "instagram", "url": "https://instagram.com/p/1/",
               "url_norm": "instagram.com/p/1"}
        first = CreatorPublication.objects.create(creator=creator, **row)
        self.assertEqual(first.status, "review")
        # Тот же пост не засчитывается ни тому же, ни другому креатору.
        self.assertIntegrityError(
            lambda: CreatorPublication.objects.create(creator=other, **row))
        CreatorPublication.objects.filter(pk=first.pk).update(status="approved")
        self.assertIntegrityError(
            lambda: CreatorPublication.objects.create(creator=creator, **row))
        # Отклонённую ссылку можно подать снова; отклонённых может быть сколько угодно.
        CreatorPublication.objects.filter(pk=first.pk).update(status="rejected")
        second = CreatorPublication.objects.create(creator=other, **row)
        CreatorPublication.objects.filter(pk=second.pk).update(status="rejected")
        CreatorPublication.objects.create(creator=creator, **row)

    def test_commission_unique_per_payment_and_part(self):
        creator = f.make_creator()
        payment = f.make_payment(f.make_user())
        f.make_commission(creator, payment)
        self.assertIntegrityError(lambda: f.make_commission(creator, payment))
        # У крипты части одного платежа — отдельные строки.
        f.make_commission(creator, payment, part="250")
        self.assertIntegrityError(lambda: f.make_commission(creator, payment, part="250"))
        f.make_commission(creator, f.make_payment(payment.user))
        self.assertEqual(CreatorCommission.objects.count(), 3)

    def test_commission_amount_cannot_be_negative(self):
        creator = f.make_creator()
        self.assertIntegrityError(lambda: f.make_commission(creator, amount="-0.000001"))
        f.make_commission(creator, amount="0", status="void")

    def test_commission_keeps_six_decimals(self):
        row = f.make_commission(f.make_creator(), amount="0.115000", base="1.150000")
        row.refresh_from_db()
        self.assertEqual(row.amount_usdt, Decimal("0.115000"))
        self.assertEqual(row.base_usd, Decimal("1.150000"))
        self.assertEqual(row.percent, Decimal("10.00"))
        self.assertEqual(row.buyer_pk, row.buyer_id)

    def test_withdrawal_minimum_is_ten(self):
        creator = f.make_creator()
        self.assertIntegrityError(lambda: f.make_withdrawal(creator, "9.99"))
        self.assertIntegrityError(lambda: f.make_withdrawal(creator, "0"))
        f.make_withdrawal(creator, "10.00")

    def test_one_open_withdrawal_per_creator(self):
        creator = f.make_creator()
        first = f.make_withdrawal(creator)
        self.assertIntegrityError(lambda: f.make_withdrawal(creator))
        CreatorWithdrawal.objects.filter(pk=first.pk).update(status="approved")
        self.assertIntegrityError(lambda: f.make_withdrawal(creator))
        # Закрытая заявка (выплачена или отклонена) новую не блокирует.
        CreatorWithdrawal.objects.filter(pk=first.pk).update(status="paid", txid=f.VALID_TXID)
        second = f.make_withdrawal(creator)
        CreatorWithdrawal.objects.filter(pk=second.pk).update(status="rejected")
        f.make_withdrawal(creator)
        f.make_withdrawal(f.make_creator())

    def test_withdrawal_txid_is_unique_when_set(self):
        a, b = f.make_creator(), f.make_creator()
        f.make_withdrawal(a, status="paid", txid=f.VALID_TXID)
        self.assertIntegrityError(
            lambda: f.make_withdrawal(b, status="paid", txid=f.VALID_TXID))
        # Пустой TXID уникальности не подчиняется.
        f.make_withdrawal(b, status="rejected")
        f.make_withdrawal(b, status="rejected")
        f.make_withdrawal(b, status="paid", txid="b" * 64)

    def test_paid_withdrawal_needs_txid(self):
        creator = f.make_creator()
        self.assertIntegrityError(lambda: CreatorWithdrawal.objects.create(
            creator=creator, amount_usdt=Decimal("10.00"), address=f.VALID_TRC20, status="paid"))
        row = f.make_withdrawal(creator, status="approved")
        self.assertIntegrityError(
            lambda: CreatorWithdrawal.objects.filter(pk=row.pk).update(status="paid"))
        CreatorWithdrawal.objects.filter(pk=row.pk).update(status="paid", txid=f.VALID_TXID)

    def test_level_percent_range(self):
        def make(percent, sort):
            return CreatorLevel.objects.create(key=f"lvl{sort}", title="X",
                                               percent=Decimal(percent), sort=sort)

        self.assertIntegrityError(lambda: make("0", 50))
        self.assertIntegrityError(lambda: make("-1", 51))
        self.assertIntegrityError(lambda: make("25.01", 52))
        make("0.01", 53)
        make("25", 54)
        self.assertIntegrityError(
            lambda: CreatorLevel.objects.filter(key="creator").update(percent=Decimal("30")))

    def test_level_key_and_sort_are_unique(self):
        self.assertIntegrityError(lambda: CreatorLevel.objects.create(
            key="creator", title="X", percent=Decimal("5"), sort=60))
        self.assertIntegrityError(lambda: CreatorLevel.objects.create(
            key="another", title="X", percent=Decimal("5"), sort=1))

    def test_one_creator_per_user_and_level_is_protected(self):
        creator = f.make_creator()
        self.assertIntegrityError(lambda: f.make_creator(creator.user))
        with self.assertRaises(ProtectedError):
            creator.level.delete()
        with self.assertRaises(ProtectedError):
            creator.user.delete()


class ManagerTests(f.CreatorsTestCase):
    def test_active_for_ignores_ended_rows(self):
        a, b = f.make_creator(), f.make_creator()
        user = f.make_user()
        self.assertIsNone(CreatorReferral.objects.active_for(user.pk))
        old = f.make_referral(a, user)
        self.assertEqual(CreatorReferral.objects.active_for(user.pk), old)
        CreatorReferral.objects.filter(pk=old.pk).update(ended_at=timezone.now(),
                                                         end_reason="admin_rebind")
        self.assertIsNone(CreatorReferral.objects.active_for(user.pk))
        new = f.make_referral(b, user, source="admin")
        found = CreatorReferral.objects.active_for(user.pk)
        self.assertEqual(found, new)
        # Креатор и уровень подгружены — вызывающий не делает лишних запросов.
        with self.assertNumQueries(0):
            self.assertEqual(found.creator.level.key, "creator")

    def test_covering_returns_binding_in_force_at_moment(self):
        a, b = f.make_creator(), f.make_creator()
        user = f.make_user()
        now = timezone.now()
        t_bind, t_rebind = now - timedelta(days=10), now - timedelta(days=3)
        old = f.make_referral(a, user, bound_at=t_bind)
        CreatorReferral.objects.filter(pk=old.pk).update(ended_at=t_rebind,
                                                         end_reason="admin_rebind")
        new = f.make_referral(b, user, source="admin", bound_at=t_rebind)

        covering = CreatorReferral.objects.covering
        # До первой привязки — никого.
        self.assertIsNone(covering(user.pk, t_bind - timedelta(seconds=1)))
        self.assertEqual(covering(user.pk, t_bind), old)
        self.assertEqual(covering(user.pk, now - timedelta(days=5)), old)
        # Ровно в момент перепривязки заказ уже принадлежит новому креатору.
        self.assertEqual(covering(user.pk, t_rebind), new)
        self.assertEqual(covering(user.pk, now), new)
        self.assertIsNone(covering(f.make_user().pk, now))

    def test_covering_none_after_unbind(self):
        user = f.make_user()
        now = timezone.now()
        row = f.make_referral(f.make_creator(), user, bound_at=now - timedelta(days=2))
        CreatorReferral.objects.filter(pk=row.pk).update(ended_at=now - timedelta(days=1),
                                                         end_reason="admin_unbind")
        self.assertIsNone(CreatorReferral.objects.covering(user.pk, now))
        self.assertEqual(
            CreatorReferral.objects.covering(user.pk, now - timedelta(days=1, hours=1)), row)

    def test_locked_returns_creator_with_level_and_user(self):
        creator = f.make_creator(level="ambassador")
        with transaction.atomic():
            with self.assertNumQueries(1):
                locked = Creator.objects.locked(creator.pk)
            with self.assertNumQueries(0):
                self.assertEqual(locked.level.key, "ambassador")
                self.assertEqual(locked.level.percent, Decimal("20.00"))
                self.assertEqual(locked.user.pk, creator.user_id)
        self.assertEqual(locked, creator)

    def test_locked_raises_for_missing_creator(self):
        with self.assertRaises(Creator.DoesNotExist):
            with transaction.atomic():
                Creator.objects.locked(10 ** 9)

    @skipUnless(connection.vendor == "postgresql", "FOR UPDATE есть только в Postgres")
    def test_locked_locks_only_the_creator_table(self):
        creator = f.make_creator()
        with transaction.atomic():
            with CaptureQueriesContext(connection) as ctx:
                Creator.objects.locked(creator.pk)
        sql = ctx.captured_queries[-1]["sql"]
        # Строки уровня и пользователя не блокируются — только сам креатор.
        # NO KEY: блокировка не спорит с проверками внешних ключей на эту строку.
        self.assertTrue(sql.rstrip().endswith('FOR NO KEY UPDATE OF "creators_creator"'), sql)


class AdminActionLogModelTests(f.CreatorsTestCase):
    def test_log_is_append_only(self):
        creator = f.make_creator()
        row = AdminActionLog.objects.filter(creator=creator).first()
        self.assertIsNotNone(row)
        row.reason = "переписали историю"
        with self.assertRaises(RuntimeError):
            row.save()
        with self.assertRaises(RuntimeError):
            row.save(update_fields=["reason"])
        with self.assertRaises(RuntimeError):
            row.delete()
        row.refresh_from_db()
        self.assertEqual(row.reason, "factory")
        self.assertTrue(AdminActionLog.objects.filter(pk=row.pk).exists())

    def test_actor_with_log_rows_cannot_be_deleted(self):
        f.make_creator()
        with self.assertRaises(ProtectedError):
            f.factory_admin().delete()

    def test_default_ordering_is_newest_first(self):
        creator = f.make_creator(status="blocked")
        actions = list(AdminActionLog.objects.filter(creator=creator)
                       .values_list("action", flat=True))
        self.assertEqual(actions, ["creator.block", "application.approve"])


class LevelsTests(f.CreatorsTestCase):
    def test_default_levels_match_the_client_table(self):
        rows = list(CreatorLevel.objects.values_list(
            "key", "title", "percent", "sort", "min_publications", "min_registrations",
            "min_paying"))
        self.assertEqual(rows, [
            ("creator", "CREATOR", Decimal("10.00"), 1, 0, 0, 0),
            ("creator_pro", "CREATOR PRO", Decimal("15.00"), 2, 10, 25, 10),
            ("ambassador", "AMBASSADOR", Decimal("20.00"), 3, 25, 100, 30),
            ("ambassador_pro", "AMBASSADOR PRO", Decimal("25.00"), 4, 50, 300, 100),
        ])
        self.assertEqual(levels.BASE_LEVEL_KEY, "creator")
        self.assertEqual(levels.MAX_PERCENT, Decimal("25"))
        self.assertEqual(max(row["percent"] for row in levels.DEFAULT_LEVELS), levels.MAX_PERCENT)

    def test_ensure_levels_is_idempotent_and_keeps_edits(self):
        self.assertEqual(CreatorLevel.objects.count(), 4)
        CreatorLevel.objects.filter(key="creator_pro").update(
            title="PRO", percent=Decimal("17.50"), min_paying=77)
        levels.ensure_levels()
        levels.ensure_levels()
        self.assertEqual(CreatorLevel.objects.count(), 4)
        edited = CreatorLevel.objects.get(key="creator_pro")
        self.assertEqual((edited.title, edited.percent, edited.min_paying),
                         ("PRO", Decimal("17.50"), 77))

    def test_ensure_levels_restores_only_missing_rows(self):
        CreatorLevel.objects.filter(key="ambassador_pro").delete()
        levels.ensure_levels()
        self.assertEqual(CreatorLevel.objects.get(key="ambassador_pro").percent, Decimal("25.00"))

    def test_get_level(self):
        self.assertEqual(levels.get_level("ambassador").percent, Decimal("20.00"))
        self.assertEqual(levels.get_level(" creator ").key, "creator")
        for bad in ("", None, "nope", "CREATOR"):
            with self.assertRaises(CreatorsError) as cm:
                levels.get_level(bad)
            self.assertEqual(cm.exception.code, "level_unknown")

    def test_next_level(self):
        chain = []
        level = levels.get_level("creator")
        while level is not None:
            chain.append(level.key)
            level = levels.next_level(level)
        self.assertEqual(chain, ["creator", "creator_pro", "ambassador", "ambassador_pro"])
        self.assertIsNone(levels.next_level(None))


class ErrorsTests(f.CreatorsTestCase):
    # Все коды §8.1: у каждого должен быть русский текст.
    CODES_404 = ("disabled", "not_found")
    CODES_403 = ("not_creator", "creator_blocked", "superuser_required", "apply_blocked",
                 "payouts_disabled")
    CODES_409 = ("already_creator", "application_open", "code_taken", "code_already_set",
                 "code_unchanged", "already_bound", "has_referrer", "publication_duplicate",
                 "withdrawal_open", "txid_duplicate", "bad_state", "already_marked",
                 "payment_refunded", "duplicate_request", "creator_conflict")
    CODES_400 = ("validation", "links_required", "code_format", "code_reserved", "self", "staff",
                 "creator_unusable", "too_late", "already_paid", "link_window", "race",
                 "no_user", "network_invalid", "url_invalid", "address_required",
                 "address_invalid", "amount_invalid", "amount_below_min",
                 "insufficient_available", "txid_invalid", "reason_required", "kind_invalid",
                 "category_invalid", "level_unknown", "percent_invalid")

    def test_every_code_has_message_and_status(self):
        table = {404: self.CODES_404, 403: self.CODES_403, 409: self.CODES_409,
                 400: self.CODES_400}
        for status, codes in table.items():
            for code in codes:
                exc = CreatorsError(code)
                self.assertEqual(exc.http, status, code)
                self.assertTrue(MESSAGES.get(code), code)
                self.assertEqual(exc.message, MESSAGES[code])
        # В таблице статусов нет лишних кодов без текста.
        self.assertFalse(set(HTTP) - set(MESSAGES))

    def test_error_fields_and_overrides(self):
        exc = CreatorsError("code_taken", taken_by="promo_code")
        self.assertEqual((exc.code, exc.http), ("code_taken", 409))
        self.assertEqual(exc.extra, {"taken_by": "promo_code"})
        custom = CreatorsError("bad_state", "Свой текст", http=422)
        self.assertEqual((custom.message, custom.http), ("Свой текст", 422))
        unknown = CreatorsError("something_new")
        self.assertEqual(unknown.http, 400)
        self.assertTrue(unknown.message)

    def test_error_body_shape(self):
        body = error_body(CreatorsError("validation", fields={"level": "Выберите уровень"}))
        self.assertEqual(body["code"], "validation")
        self.assertEqual(body["detail"], body["message"])
        self.assertIsInstance(body["detail"], str)
        self.assertEqual(body["fields"], {"level": "Выберите уровень"})
        # Доп. поле не может подменить код и текст.
        tricky = error_body(CreatorsError("bad_state", code_hint=1, detail={"x": 1}))
        self.assertEqual(tricky["code"], "bad_state")
        self.assertEqual(tricky["detail"], MESSAGES["bad_state"])


class LedgerReasonTests(f.CreatorsTestCase):
    def test_creator_credit_reason_exists(self):
        self.assertEqual(TokenTransactionReason.CREATOR_CREDIT.value, "creator_credit")
        self.assertIn(("creator_credit", "Creator Credits"), TokenTransactionReason.choices)
        self.assertLessEqual(len("creator_credit"),
                             TokenTransaction._meta.get_field("reason").max_length)


class FactoriesTests(f.CreatorsTestCase):
    def test_make_user_options(self):
        plain = f.make_user()
        self.assertFalse(plain.is_staff or plain.is_superuser or plain.is_paid)
        self.assertEqual(plain.token_balance, 0)
        boss = f.make_user(superuser=True)
        self.assertTrue(boss.is_staff and boss.is_superuser)
        rich = f.make_user(paid=True, balance=500, joined_ago=timedelta(hours=80),
                           telegram_uid=777)
        rich.refresh_from_db()
        self.assertTrue(rich.is_paid)
        self.assertIsNotNone(rich.first_paid_at)
        self.assertEqual(rich.token_balance, 500)
        self.assertGreater(timezone.now() - rich.date_joined, timedelta(hours=79))
        from allauth.socialaccount.models import SocialAccount

        self.assertEqual(SocialAccount.objects.get(user=rich, provider="telegram").uid, "777")
        self.assertGreater(timezone.now() - f.make_user(joined_ago=2).date_joined,
                           timedelta(hours=1, minutes=59))

    def test_make_creator(self):
        creator = f.make_creator(level="creator_pro", code="tora20", lang="en")
        self.assertEqual((creator.status, creator.level.key, creator.lang),
                         ("active", "creator_pro", "en"))
        self.assertTrue(creator.display_name)
        code = creator.codes.get()
        self.assertEqual((code.code, code.is_primary, code.created_by_id),
                         ("TORA20", True, creator.user_id))
        log = AdminActionLog.objects.get(creator=creator)
        self.assertEqual((log.action, log.after), ("application.approve", {"level": "creator_pro"}))
        self.assertTrue(log.actor.is_superuser)

        blocked = f.make_creator(status="blocked")
        self.assertIsNotNone(blocked.blocked_at)
        self.assertEqual(AdminActionLog.objects.filter(creator=blocked).count(), 2)
        silent = f.make_creator(logged=False, display_name="Тора")
        self.assertEqual(silent.display_name, "Тора")
        self.assertFalse(AdminActionLog.objects.filter(creator=silent).exists())

    def test_make_referral(self):
        creator = f.make_creator(code="TORA20")
        row = f.make_referral(creator)
        self.assertEqual((row.source, row.code_used, row.suspect, row.flags),
                         ("link", "TORA20", False, {}))
        self.assertIsNone(row.ended_at)
        suspect = f.make_referral(creator, suspect=True)
        self.assertEqual(suspect.flags, {"reasons": ["factory"]})
        manual = f.make_referral(creator, source="admin")
        self.assertEqual(manual.bound_by, f.factory_admin())
        self.assertTrue(AdminActionLog.objects.filter(
            action="referral.rebind", target_type="users.user",
            target_id=str(manual.user_id)).exists())

    def test_make_payment_per_provider(self):
        user = f.make_user()
        fp = f.make_payment(user)
        self.assertEqual((fp.provider, fp.currency, fp.amount), ("freedompay", "KGS",
                                                                 Decimal("490.00")))
        self.assertEqual(fp.request["token_purchase"], {"package_id": 1, "tokens": 500,
                                                        "bonus_tokens": 0})
        self.assertTrue(fp.order_id.startswith("tokpkg-"))
        self.assertFalse(fp.is_test)

        yk = f.make_payment(user, provider="yookassa", amount="450.00", kgs_price="490.00",
                            rate_kgs_to_rub="0.92")
        self.assertEqual(yk.currency, "RUB")
        self.assertEqual((yk.request["kgs_price"], yk.request["rate_kgs_to_rub"]),
                         ("490.00", "0.92"))

        crypto = f.make_payment(user, provider="crypto_nowpayments", amount="5.64", bonus=50)
        self.assertEqual(crypto.currency, "USD")
        self.assertGreater(Decimal(crypto.request["kgs_price"]), 0)
        self.assertEqual(crypto.request["token_purchase"]["bonus_tokens"], 50)

        stars = f.make_payment(user, provider="telegram_stars", amount="250")
        self.assertEqual((stars.currency, stars.request["stars"]), ("XTR", 250))

        legacy = f.make_payment(user, token_purchase=None, is_test=True, order_id="legacy-1")
        self.assertNotIn("token_purchase", legacy.request)
        self.assertTrue(legacy.is_test)
        self.assertEqual(legacy.order_id, "legacy-1")

        past = timezone.now() - timedelta(days=40)
        old = f.make_payment(user, created_at=past)
        old.refresh_from_db()
        self.assertEqual(old.created_at, past)

    def test_make_commission_defaults(self):
        creator = f.make_creator()
        buyer = f.make_user()
        referral = f.make_referral(creator, buyer)
        row = f.make_commission(creator, buyer=buyer)
        self.assertEqual((row.status, row.reason, row.part), ("accrued", "", ""))
        self.assertEqual((row.buyer, row.referral, row.payment.user), (buyer, referral, buyer))
        self.assertEqual((row.amount_usdt, row.base_usd, row.percent),
                         (Decimal("1.500000"), Decimal("10.000000"), Decimal("15.00")))
        self.assertEqual(row.level_key, "creator")
        self.assertAlmostEqual((row.available_at - timezone.now()).total_seconds(),
                               14 * 86400, delta=60)
        self.assertEqual(row.order_id, row.payment.order_id)

        matured = f.make_commission(creator, available_in_days=-1)
        self.assertLess(matured.available_at, timezone.now())
        reversed_row = f.make_commission(creator, status="reversed", reason="refund:freedompay")
        self.assertIsNotNone(reversed_row.reversed_at)
        void = f.make_commission(creator, status="void", amount="0", reason="test_payment")
        self.assertIsNone(void.available_at)

    def test_make_withdrawal_statuses(self):
        creator = f.make_creator(payout_address=f.VALID_TRC20_2)
        review = f.make_withdrawal(creator)
        self.assertEqual((review.status, review.address, review.network, review.amount_usdt),
                         ("review", f.VALID_TRC20_2, "TRC20", Decimal("10.00")))
        self.assertFalse(AdminActionLog.objects.filter(
            target_type="creators.creatorwithdrawal").exists())
        CreatorWithdrawal.objects.filter(pk=review.pk).update(status="rejected")

        paid = f.make_withdrawal(creator, "25.50", status="paid")
        self.assertRegex(paid.txid, r"^[0-9a-f]{64}$")
        self.assertIsNotNone(paid.paid_at)
        latest = AdminActionLog.objects.filter(target_type="creators.creatorwithdrawal",
                                               target_id=str(paid.pk)).first()
        self.assertEqual((latest.action, latest.after["txid"]), ("withdrawal.mark_paid", paid.txid))
        # Второй «выплачено» без явного TXID не упирается в уникальность.
        f.make_withdrawal(creator, status="paid")
        rejected = f.make_withdrawal(creator, status="rejected", logged=False)
        self.assertIsNotNone(rejected.rejected_at)

    def test_credit_purchase_writes_only_the_ledger_row(self):
        user = f.make_user()
        payment = f.make_payment(user, tokens=500, bonus=50)
        f.credit_purchase(payment)
        f.credit_purchase(payment, credited=100, idem="650")
        rows = list(TokenTransaction.objects.filter(user=user).order_by("id"))
        self.assertEqual([(r.reason, r.delta) for r in rows], [("purchase", 550),
                                                               ("purchase", 100)])
        self.assertEqual(rows[0].meta["order_id"], payment.order_id)
        self.assertNotIn("idem", rows[0].meta)
        self.assertEqual(rows[1].meta["idem"], "650")
        user.refresh_from_db()
        self.assertEqual(user.token_balance, 650)
        # Хуки оплаты не вызывались: пользователь не стал «платным», комиссий нет.
        self.assertFalse(user.is_paid)
        self.assertEqual(CreatorCommission.objects.count(), 0)


class DjangoAdminTests(f.CreatorsTestCase):
    """Django-админка только показывает: правка мимо журнала действий невозможна."""

    def _models(self):
        return list(apps.get_app_config("creators").get_models()) + [AdminActionLog]

    def test_every_model_is_registered_read_only(self):
        request = RequestFactory().get("/")
        request.user = f.make_user(superuser=True)
        models = self._models()
        self.assertEqual(len(models), 10)
        for model in models:
            self.assertIn(model, admin.site._registry, model.__name__)
            model_admin = admin.site._registry[model]
            self.assertFalse(model_admin.has_add_permission(request), model.__name__)
            self.assertFalse(model_admin.has_change_permission(request), model.__name__)
            self.assertFalse(model_admin.has_delete_permission(request), model.__name__)
            # Даже суперпользователь видит раздел, но не правит его.
            self.assertTrue(model_admin.has_view_permission(request), model.__name__)
            self.assertNotIn("delete_selected", model_admin.get_actions(request))

    def test_changelists_and_detail_pages_render(self):
        creator = f.make_creator(code="TORA20")
        buyer = f.make_user()
        f.make_referral(creator, buyer)
        commission = f.make_commission(creator, buyer=buyer, available_in_days=-1)
        f.make_withdrawal(creator, status="paid")
        self.client.force_login(f.make_user(superuser=True))
        for model in self._models():
            meta = model._meta
            response = self.client.get(
                reverse(f"admin:{meta.app_label}_{meta.model_name}_changelist"))
            self.assertEqual(response.status_code, 200, meta.model_name)
        for obj in (creator, commission, AdminActionLog.objects.first()):
            meta = obj._meta
            url = reverse(f"admin:{meta.app_label}_{meta.model_name}_change", args=[obj.pk])
            self.assertEqual(self.client.get(url).status_code, 200, meta.model_name)
            # Сохранение формы запрещено.
            self.assertEqual(self.client.post(url, {}).status_code, 403, meta.model_name)
