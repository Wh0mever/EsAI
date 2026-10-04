"""Слияние заглушки Telegram с аккаунтом сайта и программа Creators.

Правило одно: если у пары есть данные программы, слияние либо переносит их
целиком, либо не происходит вовсе. Креатор с балансом на погашенной заглушке,
в которую никто не может войти, — худший из исходов.
"""
import sys
from types import SimpleNamespace
from unittest import mock

from django.contrib.auth import get_user_model
from django.utils import timezone

from botapi import linking
from botapi.linking import LinkError, merge_into
from plans.models import TokenTransaction
from plans.wallet import credit_tokens

from .. import attribution
from ..errors import CreatorsError
from ..models import (
    Creator,
    CreatorApplication,
    CreatorCode,
    CreatorReferral,
)
from . import factories as f

_tg = iter(range(710000, 720000))


def _stub(**extra):
    """Аккаунт, появившийся из бота: почта-заглушка и привязанный Telegram."""
    uid = next(_tg)
    return f.make_user(email=f"telegram_{uid}@social.esai.local", telegram_uid=uid, **extra)


def _application(user, status="new"):
    return CreatorApplication.objects.create(
        user=user, name="Имя", telegram="@name", country="KG", occupation="блог",
        motivation="хочу", status=status)


def _ledger(user):
    return list(TokenTransaction.objects.filter(user=user).order_by("id")
                .values_list("reason", "delta"))


class ReferredByFixTests(f.CreatorsTestCase):
    """Обычная реферальная связь при слиянии (исправление, не зависящее от программы)."""

    def test_stub_invitees_move_to_target(self):
        stub, target = _stub(), f.make_user()
        invited = f.make_user()
        invited.referred_by = stub
        invited.save(update_fields=["referred_by"])
        counts = merge_into(stub, target)
        invited.refresh_from_db()
        self.assertEqual(invited.referred_by_id, target.pk)
        self.assertEqual(counts["referrals"], 1)

    def test_target_never_becomes_its_own_referrer(self):
        stub, target = _stub(), f.make_user()
        # Человек пригласил сам себя: зарегистрировался на сайте по ссылке своей заглушки.
        target.referred_by = stub
        target.save(update_fields=["referred_by"])
        counts = merge_into(stub, target)
        target.refresh_from_db()
        self.assertIsNone(target.referred_by_id)
        self.assertEqual(counts["referrals"], 0)

    def test_targets_other_referrer_is_kept(self):
        stub, target, referrer = _stub(), f.make_user(), f.make_user()
        target.referred_by = referrer
        target.save(update_fields=["referred_by"])
        merge_into(stub, target)
        target.refresh_from_db()
        self.assertEqual(target.referred_by_id, referrer.pk)


class NoCreatorDataTests(f.CreatorsTestCase):
    def test_no_creators_function_is_called_and_ledger_is_todays(self):
        stub, target = _stub(), f.make_user()
        credit_tokens(stub, 50, "welcome")
        credit_tokens(stub, 100, "purchase", meta={"order_id": "x"})
        with mock.patch("creators.attribution.check_merge") as check, \
                mock.patch("creators.attribution.on_merge") as on_merge, \
                mock.patch("botapi.linking._creator_credits_left") as credits_left:
            counts = merge_into(stub, target)
        check.assert_not_called()
        on_merge.assert_not_called()
        credits_left.assert_not_called()
        self.assertEqual(counts["moved_credits"], 100)
        self.assertNotIn("creator_moved", counts)
        self.assertNotIn("creator_referral", counts)
        # Леджер как до программы: одно списание с заглушки, одно зачисление причиной admin.
        self.assertEqual(_ledger(stub), [("welcome", 50), ("purchase", 100), ("admin", -150)])
        self.assertEqual(_ledger(target), [("admin", 100)])
        meta = TokenTransaction.objects.get(user=target).meta
        self.assertEqual(meta, {"kind": "merge_in", "merge_from": stub.pk})
        stub.refresh_from_db()
        target.refresh_from_db()
        self.assertFalse(stub.is_active)
        self.assertEqual((stub.token_balance, target.token_balance), (0, 100))

    def test_ended_stub_referral_still_counts_as_creator_data(self):
        stub, target = _stub(), f.make_user()
        referral = f.make_referral(f.make_creator(), stub)
        CreatorReferral.objects.filter(pk=referral.pk).update(ended_at=timezone.now(),
                                                              end_reason="admin_unbind")
        with mock.patch("creators.attribution.on_merge", wraps=attribution.on_merge) as on_merge:
            counts = merge_into(stub, target)
        on_merge.assert_called_once()
        self.assertEqual(counts["creator_referral"], "none")


class CreatorMoveTests(f.CreatorsTestCase):
    def test_stub_creator_moves_to_target(self):
        stub, target = _stub(), f.make_user()
        creator = f.make_creator(stub, code="TORA20", payout_address=f.VALID_TRC20)
        buyer = f.make_user()
        f.make_referral(creator, buyer)
        commission = f.make_commission(creator, buyer=buyer)
        withdrawal = f.make_withdrawal(creator, "10.00")
        counts = merge_into(stub, target)
        self.assertTrue(counts["creator_moved"])
        creator.refresh_from_db()
        self.assertEqual(creator.user_id, target.pk)
        self.assertEqual(creator.payout_address, f.VALID_TRC20)
        # Код, рефералы, комиссии и вывод едут за креатором.
        self.assertEqual(CreatorCode.objects.get(code="TORA20").creator.user_id, target.pk)
        self.assertEqual(attribution.creator_code("TORA20").creator.user_id, target.pk)
        self.assertEqual(CreatorReferral.objects.get(user=buyer).creator.user_id, target.pk)
        commission.refresh_from_db()
        withdrawal.refresh_from_db()
        self.assertEqual(commission.creator.user_id, target.pk)
        self.assertEqual(withdrawal.creator.user_id, target.pk)
        self.assertFalse(Creator.objects.filter(user=stub).exists())

    def test_both_creators_is_a_conflict_and_nothing_changes(self):
        stub, target = _stub(balance=0), f.make_user()
        credit_tokens(stub, 100, "purchase", meta={"order_id": "x"})
        stub_creator = f.make_creator(stub, code="STUB1")
        target_creator = f.make_creator(target, code="SITE1")
        with self.assertRaises(LinkError) as ctx:
            merge_into(stub, target)
        self.assertEqual((ctx.exception.code, ctx.exception.http), ("creator_conflict", 409))
        stub.refresh_from_db()
        target.refresh_from_db()
        self.assertTrue(stub.is_active)
        self.assertTrue(stub.email.startswith("telegram_"))
        self.assertEqual((stub.token_balance, target.token_balance), (100, 0))
        self.assertEqual(_ledger(target), [])
        stub_creator.refresh_from_db()
        target_creator.refresh_from_db()
        self.assertEqual(stub_creator.user_id, stub.pk)
        self.assertEqual(target_creator.user_id, target.pk)

    def test_check_merge(self):
        stub, target = _stub(), f.make_user()
        attribution.check_merge(stub, target)
        f.make_creator(stub)
        attribution.check_merge(stub, target)
        f.make_creator(target)
        with self.assertRaises(CreatorsError) as ctx:
            attribution.check_merge(stub, target)
        self.assertEqual(ctx.exception.code, "creator_conflict")

    def test_target_creator_keeps_its_row(self):
        stub, target = _stub(), f.make_user()
        creator = f.make_creator(target, code="SITE1")
        counts = merge_into(stub, target)
        self.assertFalse(counts["creator_moved"])
        creator.refresh_from_db()
        self.assertEqual(creator.user_id, target.pk)


class ReferralMergeTests(f.CreatorsTestCase):
    def setUp(self):
        super().setUp()
        self.creator = f.make_creator(code="TORA20")
        self.stub = _stub()
        self.referral = f.make_referral(self.creator, self.stub, source="bot")

    def _merge(self, target):
        counts = merge_into(self.stub, target)
        self.referral.refresh_from_db()
        return counts

    def assertDropped(self, target):
        counts = self._merge(target)
        self.assertEqual(counts["creator_referral"], "dropped")
        self.assertEqual(self.referral.user_id, self.stub.pk)
        self.assertIsNotNone(self.referral.ended_at)
        self.assertEqual(self.referral.end_reason, "merge_dropped")

    def test_moved_to_a_fresh_unpaid_target(self):
        target = f.make_user(joined_ago=71)
        counts = self._merge(target)
        self.assertEqual(counts["creator_referral"], "moved")
        self.assertEqual(self.referral.user_id, target.pk)
        self.assertIsNone(self.referral.ended_at)
        self.assertEqual(CreatorReferral.objects.active_for(target.pk).creator_id, self.creator.pk)
        self.assertIsNone(CreatorReferral.objects.active_for(self.stub.pk))

    def test_dropped_when_target_is_bound(self):
        target = f.make_user()
        own = f.make_referral(f.make_creator(), target)
        self.assertDropped(target)
        own.refresh_from_db()
        self.assertIsNone(own.ended_at)

    def test_dropped_when_target_has_referrer(self):
        target = f.make_user()
        target.referred_by = f.make_user()
        target.save(update_fields=["referred_by"])
        self.assertDropped(target)

    def test_dropped_when_target_is_staff(self):
        self.assertDropped(f.make_user(staff=True))

    def test_dropped_when_target_is_older_than_72_hours(self):
        self.assertDropped(f.make_user(joined_ago=73))

    def test_dropped_when_target_already_paid(self):
        self.assertDropped(f.make_user(paid=True))

    def test_moved_when_the_only_referrer_was_the_stub_itself(self):
        target = f.make_user()
        target.referred_by = self.stub
        target.save(update_fields=["referred_by"])
        counts = self._merge(target)
        self.assertEqual(counts["creator_referral"], "moved")

    def test_commission_buyer_is_repointed(self):
        payment = f.make_payment(self.stub)
        commission = f.make_commission(self.creator, payment)
        other = f.make_commission(self.creator)
        target = f.make_user()
        self._merge(target)
        commission.refresh_from_db()
        other.refresh_from_db()
        self.assertEqual((commission.buyer_id, commission.buyer_pk), (target.pk, target.pk))
        self.assertEqual(commission.status, "accrued")
        payment.refresh_from_db()
        self.assertEqual(payment.user_id, target.pk)
        # Чужую комиссию слияние не трогает.
        self.assertNotEqual(other.buyer_pk, target.pk)

    def test_self_referral_is_ended_and_commissions_are_held(self):
        target = f.make_user()
        own = f.make_creator(target, code="SITE1")
        stub = _stub()
        referral = f.make_referral(own, stub, source="bot")
        accrued = f.make_commission(own, f.make_payment(stub))
        reversed_row = f.make_commission(own, f.make_payment(stub), status="reversed",
                                         reason="refund:freedompay")
        foreign = f.make_commission(own)
        held = f.make_commission(own, f.make_payment(stub), status="held",
                                 reason="referral_suspect")
        foreign_held = f.make_commission(own, status="held", reason="referral_suspect")
        counts = merge_into(stub, target)
        self.assertEqual(counts["creator_referral"], "self")
        # Уже придержанная строка собственной покупки тоже ждёт решения по
        # слиянию: снятие пометки с привязки её больше не отпустит.
        held.refresh_from_db()
        foreign_held.refresh_from_db()
        self.assertEqual((held.status, held.reason), ("held", "merge_self"))
        self.assertEqual((foreign_held.status, foreign_held.reason),
                         ("held", "referral_suspect"))
        referral.refresh_from_db()
        self.assertEqual(referral.user_id, stub.pk)
        self.assertEqual(referral.end_reason, "merge_self")
        self.assertIsNotNone(referral.ended_at)
        self.assertIsNone(CreatorReferral.objects.active_for(target.pk))
        accrued.refresh_from_db()
        reversed_row.refresh_from_db()
        foreign.refresh_from_db()
        # Комиссия с собственных покупок придержана: решит администратор.
        self.assertEqual((accrued.status, accrued.reason), ("held", "merge_self"))
        self.assertEqual((accrued.buyer_id, accrued.buyer_pk), (target.pk, target.pk))
        self.assertEqual((reversed_row.status, reversed_row.reason),
                         ("reversed", "refund:freedompay"))
        self.assertEqual((foreign.status, foreign.reason), ("accrued", ""))

    def test_clearing_suspect_after_self_merge_releases_nothing(self):
        # Подозрительная привязка заглушки к креатору, которым владеет аккаунт
        # сайта: после слияния «снять пометку и отпустить» не должно выдать
        # креатору комиссию с его же покупки.
        from creators import attribution

        target = f.make_user()
        own = f.make_creator(target, code="SITE2")
        stub = _stub()
        referral = f.make_referral(own, stub, source="bot", suspect=True)
        row = f.make_commission(own, f.make_payment(stub), status="held",
                                reason="referral_suspect")
        merge_into(stub, target)
        attribution.clear_suspect(referral.pk, actor=f.factory_admin(), reason="проверено",
                                  release_held=True)
        row.refresh_from_db()
        self.assertEqual((row.status, row.reason), ("held", "merge_self"))
        self.assertEqual(row.buyer_pk, target.pk)

    def test_target_bound_to_the_stubs_creator_is_ended_as_self(self):
        stub, target = _stub(), f.make_user()
        creator = f.make_creator(stub, code="STUB1")
        referral = f.make_referral(creator, target)
        commission = f.make_commission(creator, f.make_payment(target))
        counts = merge_into(stub, target)
        self.assertTrue(counts["creator_moved"])
        self.assertEqual(counts["creator_referral"], "self")
        referral.refresh_from_db()
        self.assertEqual(referral.end_reason, "merge_self")
        commission.refresh_from_db()
        self.assertEqual((commission.status, commission.reason), ("held", "merge_self"))

    def test_creator_locks_are_taken_in_ascending_order_before_updates(self):
        first, second = f.make_creator(), f.make_creator()
        f.make_commission(second, f.make_payment(self.stub))
        f.make_commission(first, f.make_payment(self.stub))
        target = f.make_user()
        with mock.patch.object(Creator.objects, "locked", wraps=Creator.objects.locked) as locked:
            self._merge(target)
        self.assertEqual([call.args[0] for call in locked.call_args_list],
                         sorted([first.pk, second.pk]))


class ApplicationMergeTests(f.CreatorsTestCase):
    def test_stub_applications_move(self):
        stub, target = _stub(), f.make_user()
        rejected = _application(stub, "rejected")
        opened = _application(stub)
        counts = merge_into(stub, target)
        self.assertEqual(counts["applications"], 2)
        rejected.refresh_from_db()
        opened.refresh_from_db()
        self.assertEqual((rejected.user_id, rejected.status), (target.pk, "rejected"))
        # Открытая заявка не осталась на погашенном аккаунте.
        self.assertEqual((opened.user_id, opened.status), (target.pk, "new"))

    def test_two_open_applications(self):
        stub, target = _stub(), f.make_user()
        stub_app, target_app = _application(stub), _application(target)
        counts = merge_into(stub, target)
        self.assertEqual(counts["applications"], 1)
        stub_app.refresh_from_db()
        target_app.refresh_from_db()
        self.assertEqual((stub_app.user_id, stub_app.status, stub_app.reject_reason),
                         (target.pk, "rejected", "merge"))
        self.assertIsNotNone(stub_app.decided_at)
        self.assertEqual(target_app.status, "new")

    def test_blocked_application_follows_the_person(self):
        stub, target = _stub(), f.make_user()
        _application(stub, "blocked")
        merge_into(stub, target)
        self.assertTrue(CreatorApplication.objects.filter(user=target, status="blocked").exists())


class FailClosedTests(f.CreatorsTestCase):
    def setUp(self):
        super().setUp()
        self.stub, self.target = _stub(), f.make_user()
        credit_tokens(self.stub, 100, "purchase", meta={"order_id": "x"})
        self.creator = f.make_creator(self.stub, code="STUB1")

    def assertNothingChanged(self):
        self.stub.refresh_from_db()
        self.target.refresh_from_db()
        self.creator.refresh_from_db()
        self.assertTrue(self.stub.is_active)
        self.assertTrue(self.stub.email.startswith("telegram_"))
        self.assertEqual((self.stub.token_balance, self.target.token_balance), (100, 0))
        self.assertEqual(self.creator.user_id, self.stub.pk)
        self.assertEqual(_ledger(self.target), [])

    def assertConflict(self):
        with self.assertRaises(LinkError) as ctx:
            merge_into(self.stub, self.target)
        self.assertEqual((ctx.exception.code, ctx.exception.http), ("creator_conflict", 409))
        self.assertNothingChanged()

    def test_raising_check_merge(self):
        with mock.patch("creators.attribution.check_merge", side_effect=RuntimeError("boom")):
            self.assertConflict()

    def test_raising_on_merge(self):
        with mock.patch("creators.attribution.on_merge", side_effect=RuntimeError("boom")):
            self.assertConflict()

    def test_on_merge_failing_half_way(self):
        # Креатор уже переехал, а перенос заявок упал — откатывается всё.
        with mock.patch.object(CreatorApplication.objects, "filter",
                               side_effect=RuntimeError("boom")), \
                mock.patch("botapi.linking._creators_has_data", return_value=True):
            self.assertConflict()

    def test_raising_data_probe(self):
        with mock.patch.object(Creator.objects, "filter", side_effect=RuntimeError("boom")):
            self.assertConflict()

    def test_raising_data_probe_without_creator_data(self):
        # Не смогли узнать, есть ли данные программы, — слияния нет даже у обычной пары.
        stub, target = _stub(), f.make_user()
        with mock.patch.object(Creator.objects, "filter", side_effect=RuntimeError("boom")):
            with self.assertRaises(LinkError) as ctx:
                merge_into(stub, target)
        self.assertEqual(ctx.exception.code, "creator_conflict")
        stub.refresh_from_db()
        self.assertTrue(stub.is_active)

    def test_merge_succeeds_without_failures(self):
        counts = merge_into(self.stub, self.target)
        self.assertTrue(counts["creator_moved"])
        self.stub.refresh_from_db()
        self.assertFalse(self.stub.is_active)


class CreatorCreditsMergeTests(f.CreatorsTestCase):
    def setUp(self):
        super().setUp()
        self.stub, self.target = _stub(), f.make_user()
        f.make_creator(self.stub)

    def test_credits_left_are_reissued_as_creator_credit(self):
        credit_tokens(self.stub, 100, "purchase", meta={"order_id": "x"})
        with mock.patch("botapi.linking._creator_credits_left", return_value=60):
            counts = merge_into(self.stub, self.target)
        self.assertEqual(counts["moved_credits"], 100)
        self.assertEqual(_ledger(self.target), [("creator_credit", 60), ("admin", 40)])
        meta = TokenTransaction.objects.get(user=self.target, reason="creator_credit").meta
        self.assertEqual(meta, {"category": "merge", "note": "", "by_id": None, "grant_id": "",
                                "kind": "merge_in", "merge_from": self.stub.pk})

    def test_credits_left_never_exceed_what_moves(self):
        credit_tokens(self.stub, 30, "purchase", meta={"order_id": "x"})
        with mock.patch("botapi.linking._creator_credits_left", return_value=500):
            merge_into(self.stub, self.target)
        self.assertEqual(_ledger(self.target), [("creator_credit", 30)])

    def test_failing_credits_module_moves_everything_as_before(self):
        credit_tokens(self.stub, 100, "purchase", meta={"order_id": "x"})
        fake = SimpleNamespace(remaining=mock.Mock(side_effect=RuntimeError("boom")))
        with mock.patch.dict(sys.modules, {"creators.credits": fake}):
            self.assertEqual(linking._creator_credits_left(self.stub), 0)
            merge_into(self.stub, self.target)
        self.assertEqual(_ledger(self.target), [("admin", 100)])

    def test_creator_credits_stay_non_transferable(self):
        """[gate] С настоящими creators.credits и защитой перевода (T3)."""
        try:
            from creators import credits
            from plans.wallet import transferable_tokens
        except ImportError:
            self.skipTest("[gate] creators.credits (T3) ещё нет")
        credit_tokens(self.stub, 100, "creator_credit",
                      meta={"category": "start", "note": "", "by_id": None, "grant_id": "g1"})
        self.assertEqual(credits.remaining(self.stub), 100)
        merge_into(self.stub, self.target)
        self.assertEqual(_ledger(self.target), [("creator_credit", 100)])
        self.target.refresh_from_db()
        self.assertEqual(self.target.token_balance, 100)
        self.assertEqual(credits.remaining(self.target), 100)
        self.assertEqual(transferable_tokens(self.target), 0)


class ConfirmLinkTests(f.CreatorsTestCase):
    def test_conflict_reaches_the_caller_of_confirm_link(self):
        from django.core.cache import cache

        from botapi.linking import confirm_link, start_link
        from botapi.services import find_user

        stub = _stub()
        stub.set_unusable_password()
        stub.save()
        uid = stub.email.split("_")[1].split("@")[0]
        self.assertEqual(find_user(uid).pk, stub.pk)
        target = f.make_user()
        f.make_creator(stub)
        f.make_creator(target)
        cache.clear()
        code = start_link(target)["code"]
        with self.assertRaises(LinkError) as ctx:
            confirm_link(code, {"id": int(uid), "username": "ivan"}, chat_id=int(uid))
        self.assertEqual((ctx.exception.code, ctx.exception.http), ("creator_conflict", 409))
        stub.refresh_from_db()
        self.assertTrue(stub.is_active)
        self.assertEqual(get_user_model().objects.get(pk=target.pk).is_active, True)


class ForgetTelegramTests(f.CreatorsTestCase):
    """/delete в боте и креатор: аккаунт-заглушка с балансом и кодом не гасится."""

    def _stub_user(self, **extra):
        from allauth.socialaccount.models import SocialAccount

        stub = _stub(**extra)
        stub.set_unusable_password()
        stub.save()
        uid = int(SocialAccount.objects.get(user=stub).uid)
        return stub, uid

    def test_creator_stub_is_not_deactivated(self):
        from allauth.socialaccount.models import SocialAccount

        from botapi.models import TelegramChat
        from botapi.services import authenticate_telegram_user

        stub, uid = self._stub_user()
        TelegramChat.objects.create(user=stub, telegram_id=uid, chat_id=uid)
        creator = f.make_creator(stub, code="STUBC1", payout_address=f.VALID_TRC20)
        email = stub.email

        result = linking.forget_telegram(uid)

        self.assertEqual(result, {"status": "creator_account", "deactivated": False})
        stub.refresh_from_db()
        self.assertTrue(stub.is_active)
        self.assertEqual(stub.email, email)
        # Telegram остался привязан: следующий /start приводит в тот же аккаунт,
        # а не заводит новый без креатора.
        self.assertTrue(SocialAccount.objects.filter(user=stub, uid=str(uid)).exists())
        self.assertTrue(TelegramChat.objects.filter(user=stub).exists())
        again, created = authenticate_telegram_user({"id": uid, "first_name": "Иван"},
                                                    chat_id=uid)
        self.assertFalse(created)
        self.assertEqual(again.pk, stub.pk)
        creator.refresh_from_db()
        self.assertEqual((creator.user_id, creator.status), (stub.pk, "active"))

    def test_blocked_creator_stub_is_not_deactivated_either(self):
        # У заблокированного креатора тоже остаются баланс и долг.
        stub, uid = self._stub_user()
        f.make_creator(stub, status="blocked")
        self.assertEqual(linking.forget_telegram(uid)["status"], "creator_account")
        stub.refresh_from_db()
        self.assertTrue(stub.is_active)

    def test_ordinary_stub_is_deactivated_as_before(self):
        stub, uid = self._stub_user()
        # Реферал креатора и автор заявки — не креатор: /delete работает как раньше.
        f.make_referral(f.make_creator(code="TORA20"), stub)
        _application(stub)
        self.assertEqual(linking.forget_telegram(uid),
                         {"status": "unlinked", "deactivated": True})
        stub.refresh_from_db()
        self.assertFalse(stub.is_active)

    def test_site_account_of_a_creator_only_loses_telegram(self):
        from allauth.socialaccount.models import SocialAccount

        owner = f.make_user(telegram_uid=next(_tg))
        f.make_creator(owner)
        uid = int(SocialAccount.objects.get(user=owner).uid)
        self.assertEqual(linking.forget_telegram(uid),
                         {"status": "unlinked", "deactivated": False})
        owner.refresh_from_db()
        self.assertTrue(owner.is_active)
        self.assertFalse(SocialAccount.objects.filter(user=owner).exists())

    def test_failing_probe_keeps_the_account(self):
        # Не смогли узнать, креатор ли это, — аккаунт не трогаем.
        stub, uid = self._stub_user()
        with mock.patch.object(Creator.objects, "filter", side_effect=RuntimeError("boom")):
            result = linking.forget_telegram(uid)
        self.assertEqual(result, {"status": "creator_account", "deactivated": False})
        stub.refresh_from_db()
        self.assertTrue(stub.is_active)

    def test_unlink_log_carries_the_telegram_id(self):
        # По этой записи программа узнаёт повторную регистрацию (attribution).
        from audit.models import EventLog

        stub, uid = self._stub_user()
        linking.forget_telegram(uid)
        row = EventLog.objects.filter(user=stub).latest("id")
        self.assertEqual(row.meta, {"deactivated": True, "telegram_id": str(uid)})


class DeactivatedCreatorAccountTests(f.CreatorsTestCase):
    """Аккаунт креатора отключён (администратором): его код больше никого не привязывает."""

    def setUp(self):
        super().setUp()
        self.creator = f.make_creator(code="GONE01")
        owner = self.creator.user
        owner.is_active = False
        owner.save(update_fields=["is_active"])

    def test_typed_code_answers_not_found(self):
        from users.services import activate_promo

        ok, message, _ = activate_promo(f.make_user(), "GONE01")
        self.assertFalse(ok)
        self.assertEqual(message, "Промокод не найден или неактивен")
        self.assertFalse(CreatorReferral.objects.exists())

    def test_link_at_signup_binds_nobody(self):
        from users.services import maybe_link_referrer

        user = f.make_user()
        request = SimpleNamespace(COOKIES={"esai_ref": "GONE01"}, data={}, META={})
        maybe_link_referrer(request, user)
        self.assertFalse(CreatorReferral.objects.exists())
        user.refresh_from_db()
        self.assertIsNone(user.referred_by_id)

    def test_bind_refuses(self):
        result = attribution.bind(f.make_user(), self.creator, source="link")
        self.assertEqual((result.ok, result.reason), (False, "creator_unusable"))

    def test_reactivated_account_binds_again(self):
        owner = self.creator.user
        owner.is_active = True
        owner.save(update_fields=["is_active"])
        self.assertTrue(attribution.bind(f.make_user(), self.creator, source="link").ok)
