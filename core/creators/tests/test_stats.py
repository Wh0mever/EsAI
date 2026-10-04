"""Счётчики креатора и прогресс до следующего уровня.

Что здесь важно: накрутка счётчик не поднимает (подозрительная привязка и
погашенный аккаунт — не регистрация), отменённые деньги не считаются
продажами, а «условия выполнены» — только уведомление, уровень код не меняет.
"""
from decimal import Decimal
from unittest import mock

from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from .. import attribution, levels, stats
from ..models import (
    Creator,
    CreatorClick,
    CreatorLevel,
    CreatorPublication,
    CreatorReferral,
)
from . import factories as f

ZERO = {"clicks": 0, "registrations": 0, "suspect_referrals": 0, "paying": 0, "orders": 0,
        "sales_usdt": Decimal("0.00"), "publications_approved": 0}


def _click(creator, n=1):
    for i in range(n):
        CreatorClick.objects.create(creator=creator, code="X", device_key=f"d{creator.pk}-{i}",
                                    day=timezone.localdate())


def _publication(creator, status="approved"):
    n = CreatorPublication.objects.count() + 1
    return CreatorPublication.objects.create(
        creator=creator, network="instagram", url=f"https://instagram.com/p/{n}",
        url_norm=f"instagram.com/p/{n}", status=status)


def _thresholds(key, publications, registrations, paying):
    CreatorLevel.objects.filter(key=key).update(
        min_publications=publications, min_registrations=registrations, min_paying=paying)


class CountersTests(f.CreatorsTestCase):
    def setUp(self):
        super().setUp()
        self.creator = f.make_creator(code="TORA20")

    def test_empty(self):
        self.assertEqual(stats.counters(self.creator), ZERO)
        self.assertEqual(stats.counters_bulk([]), {})
        self.assertEqual(stats.counters_bulk([self.creator.pk, 10 ** 9]),
                         {self.creator.pk: ZERO, 10 ** 9: ZERO})

    def test_everything_counted(self):
        _click(self.creator, 3)
        buyer_a, buyer_b = f.make_user(), f.make_user()
        f.make_referral(self.creator, buyer_a)
        f.make_referral(self.creator, buyer_b)
        f.make_referral(self.creator)
        payment = f.make_payment(buyer_a)
        f.make_commission(self.creator, payment, base="10.005000", amount="1.000500")
        f.make_commission(self.creator, buyer=buyer_a, base="20.004000", amount="2.000400")
        f.make_commission(self.creator, buyer=buyer_b, base="5.000000", amount="0.500000",
                          status="held", reason="creator_blocked")
        _publication(self.creator)
        _publication(self.creator)
        _publication(self.creator, status="review")
        _publication(self.creator, status="rejected")
        self.assertEqual(stats.counters(self.creator), {
            "clicks": 3, "registrations": 3, "suspect_referrals": 0, "paying": 2, "orders": 3,
            # 35.009 — вниз до цента.
            "sales_usdt": Decimal("35.00"), "publications_approved": 2})

    def test_crypto_parts_are_one_order(self):
        buyer = f.make_user()
        f.make_referral(self.creator, buyer)
        payment = f.make_payment(buyer, provider="crypto_usdt", amount="30.00")
        f.make_commission(self.creator, payment, base="10.000000", amount="1.000000", part="100")
        f.make_commission(self.creator, payment, base="20.000000", amount="2.000000", part="300")
        have = stats.counters(self.creator)
        self.assertEqual((have["paying"], have["orders"], have["sales_usdt"]),
                         (1, 1, Decimal("30.00")))

    def test_reversed_and_void_rows_are_excluded(self):
        buyer = f.make_user()
        f.make_referral(self.creator, buyer)
        f.make_commission(self.creator, buyer=buyer, base="10.000000", status="reversed",
                          reason="refund:freedompay")
        f.make_commission(self.creator, buyer=buyer, base="10.000000", amount="0", status="void",
                          reason="test_payment")
        have = stats.counters(self.creator)
        self.assertEqual((have["paying"], have["orders"], have["sales_usdt"]),
                         (0, 0, Decimal("0.00")))
        f.make_commission(self.creator, buyer=buyer, base="7.000000", amount="0.700000")
        have = stats.counters(self.creator)
        self.assertEqual((have["paying"], have["orders"], have["sales_usdt"]),
                         (1, 1, Decimal("7.00")))

    def test_suspect_referral_is_not_a_registration_until_cleared(self):
        f.make_referral(self.creator)
        suspect = f.make_referral(self.creator, suspect=True)
        have = stats.counters(self.creator)
        self.assertEqual((have["registrations"], have["suspect_referrals"]), (1, 1))
        with mock.patch("creators.attribution.notify.emit"):
            attribution.clear_suspect(suspect.pk, actor=f.make_user(superuser=True), reason="чисто")
        have = stats.counters(self.creator)
        self.assertEqual((have["registrations"], have["suspect_referrals"]), (2, 0))

    def test_deactivated_user_is_not_a_registration(self):
        user = f.make_user()
        f.make_referral(self.creator, user)
        self.assertEqual(stats.counters(self.creator)["registrations"], 1)
        user.is_active = False
        user.save(update_fields=["is_active"])
        self.assertEqual(stats.counters(self.creator)["registrations"], 0)

    def test_delete_start_loop_never_raises_the_counter(self):
        """Один Telegram: зашёл по ссылке, /delete, снова /start по ссылке — и так трижды."""
        from allauth.socialaccount.models import SocialAccount

        with mock.patch("creators.attribution.notify.emit") as emit:
            for _ in range(3):
                user = f.make_user(telegram_uid=700500)
                self.assertTrue(attribution.bind(user, self.creator, source="bot").ok)
                # /delete в боте: привязка Telegram удалена, заглушка погашена.
                SocialAccount.objects.filter(user=user).delete()
                user.is_active = False
                user.save(update_fields=["is_active"])
            last = f.make_user(telegram_uid=700500)
            attribution.bind(last, self.creator, source="bot")
        have = stats.counters(self.creator)
        self.assertEqual(have["registrations"], 0)
        # Действующих привязок четыре: первая чистая (но аккаунт погашен), три помечены.
        self.assertEqual(CreatorReferral.objects.filter(creator=self.creator).count(), 4)
        self.assertEqual(have["suspect_referrals"], 3)
        # Креатору объявили только самого первого.
        self.assertEqual(emit.call_count, 1)

    def test_ended_referral_is_not_counted(self):
        referral = f.make_referral(self.creator)
        CreatorReferral.objects.filter(pk=referral.pk).update(ended_at=timezone.now())
        ended_suspect = f.make_referral(self.creator, suspect=True)
        CreatorReferral.objects.filter(pk=ended_suspect.pk).update(ended_at=timezone.now())
        have = stats.counters(self.creator)
        self.assertEqual((have["registrations"], have["suspect_referrals"]), (0, 0))

    def test_commissions_of_suspect_referral_are_excluded(self):
        buyer = f.make_user()
        referral = f.make_referral(self.creator, buyer, suspect=True)
        f.make_commission(self.creator, buyer=buyer, base="10.000000", status="held",
                          reason="referral_suspect")
        have = stats.counters(self.creator)
        self.assertEqual((have["paying"], have["orders"], have["sales_usdt"]),
                         (0, 0, Decimal("0.00")))
        CreatorReferral.objects.filter(pk=referral.pk).update(suspect=False)
        have = stats.counters(self.creator)
        self.assertEqual((have["paying"], have["orders"], have["sales_usdt"]),
                         (1, 1, Decimal("10.00")))

    def test_commission_without_referral_is_counted(self):
        f.make_commission(self.creator, base="10.000000")
        have = stats.counters(self.creator)
        self.assertEqual((have["paying"], have["orders"]), (1, 1))

    def test_paid_money_counts_even_for_a_deactivated_buyer(self):
        buyer = f.make_user()
        f.make_referral(self.creator, buyer)
        f.make_commission(self.creator, buyer=buyer, base="10.000000")
        buyer.is_active = False
        buyer.save(update_fields=["is_active"])
        have = stats.counters(self.creator)
        self.assertEqual((have["registrations"], have["paying"], have["sales_usdt"]),
                         (0, 1, Decimal("10.00")))

    def test_counters_and_counters_bulk_agree(self):
        other = f.make_creator(code="OTHER1")
        empty = f.make_creator()
        _click(self.creator, 2)
        _click(other, 5)
        f.make_referral(self.creator)
        f.make_referral(other)
        f.make_referral(other, suspect=True)
        f.make_commission(self.creator, base="3.000000")
        f.make_commission(other, base="4.000000")
        f.make_commission(other, base="6.000000", status="reversed")
        _publication(other)
        bulk = stats.counters_bulk([self.creator.pk, other.pk, empty.pk])
        for creator in (self.creator, other, empty):
            self.assertEqual(bulk[creator.pk], stats.counters(creator))
        self.assertEqual(bulk[empty.pk], ZERO)
        self.assertEqual(bulk[other.pk], {
            "clicks": 5, "registrations": 1, "suspect_referrals": 1, "paying": 1, "orders": 1,
            "sales_usdt": Decimal("4.00"), "publications_approved": 1})

    def test_bulk_query_count_does_not_grow(self):
        creators = [self.creator] + [f.make_creator() for _ in range(4)]
        for creator in creators:
            _click(creator)
            f.make_referral(creator)
            f.make_commission(creator)
        with CaptureQueriesContext(connection) as one:
            stats.counters_bulk([self.creator.pk])
        with CaptureQueriesContext(connection) as many:
            stats.counters_bulk([creator.pk for creator in creators])
        self.assertEqual(len(one), len(many))
        self.assertLessEqual(len(many), 4)


class ProgressTests(f.CreatorsTestCase):
    def setUp(self):
        super().setUp()
        self.creator = f.make_creator()
        _thresholds("creator_pro", 2, 2, 1)

    def _fill(self, creator, *, publications=0, registrations=0, paying=0):
        for _ in range(publications):
            _publication(creator)
        buyers = [f.make_user() for _ in range(registrations)]
        for buyer in buyers:
            f.make_referral(creator, buyer)
        for buyer in buyers[:paying]:
            f.make_commission(creator, buyer=buyer)

    def test_thresholds(self):
        self._fill(self.creator, publications=1, registrations=2)
        self.assertEqual(stats.progress(self.creator), {
            "next_level": {"key": "creator_pro", "title": "CREATOR PRO", "percent": "15.00"},
            "publications": {"have": 1, "need": 2, "done": False},
            "registrations": {"have": 2, "need": 2, "done": True},
            "paying": {"have": 0, "need": 1, "done": False},
            "conditions_met": False})

    def test_conditions_met(self):
        self._fill(self.creator, publications=2, registrations=3, paying=1)
        state = stats.progress(self.creator)
        self.assertTrue(state["conditions_met"])
        self.assertEqual(state["registrations"], {"have": 3, "need": 2, "done": True})

    def test_each_condition_alone_keeps_the_level_closed(self):
        # Пороги 2 / 2 / 1. Не хватает ровно одного условия — «выполнено» быть
        # не должно, какое бы из трёх ни осталось.
        cases = (
            ("publications", dict(publications=1, registrations=2, paying=1)),
            ("registrations", dict(publications=2, registrations=1, paying=1)),
            ("paying", dict(publications=2, registrations=2, paying=0)),
        )
        for missing, have in cases:
            creator = f.make_creator()
            self._fill(creator, **have)
            state = stats.progress(creator)
            done = {key: state[key]["done"] for key in ("publications", "registrations", "paying")}
            self.assertEqual(done, {key: key != missing
                                    for key in ("publications", "registrations", "paying")})
            self.assertFalse(state["conditions_met"], missing)
            self.assertFalse(stats.progress_bulk([creator])[creator.pk]["conditions_met"], missing)
            with mock.patch("creators.stats.notify.emit") as emit:
                self.assertFalse(stats.check_next_level(creator), missing)
            emit.assert_not_called()
            creator.refresh_from_db()
            self.assertEqual(creator.next_level_notified, "", missing)

    def test_top_level_has_no_next(self):
        top = f.make_creator(level="ambassador_pro")
        self._fill(top, publications=1, registrations=1, paying=1)
        state = stats.progress(top)
        self.assertIsNone(state["next_level"])
        self.assertFalse(state["conditions_met"])
        self.assertEqual(state["publications"], {"have": 1, "need": 0, "done": True})

    def test_passed_counters_run_no_counter_query(self):
        have = stats.counters(self.creator)
        creator = Creator.objects.select_related("level").get(pk=self.creator.pk)
        # Один запрос — следующий уровень.
        with self.assertNumQueries(1):
            state = stats.progress(creator, counters=have)
        self.assertEqual(state, stats.progress(self.creator))

    def test_suspect_referrals_do_not_move_progress(self):
        _publication(self.creator)
        _publication(self.creator)
        for _ in range(3):
            buyer = f.make_user()
            f.make_referral(self.creator, buyer, suspect=True)
            f.make_commission(self.creator, buyer=buyer, status="held", reason="referral_suspect")
        state = stats.progress(self.creator)
        self.assertEqual(state["registrations"]["have"], 0)
        self.assertEqual(state["paying"]["have"], 0)
        self.assertFalse(state["conditions_met"])

    def test_progress_bulk_equals_progress(self):
        ready = f.make_creator()
        self._fill(ready, publications=2, registrations=2, paying=1)
        pro = f.make_creator(level="creator_pro")
        self._fill(pro, publications=1)
        top = f.make_creator(level="ambassador_pro")
        creators = [self.creator, ready, pro, top]
        bulk = stats.progress_bulk(creators)
        self.assertEqual(set(bulk), {creator.pk for creator in creators})
        for creator in creators:
            self.assertEqual(bulk[creator.pk], stats.progress(creator))
        self.assertTrue(bulk[ready.pk]["conditions_met"])
        self.assertFalse(bulk[self.creator.pk]["conditions_met"])
        self.assertEqual(bulk[pro.pk]["next_level"]["key"], "ambassador")
        self.assertIsNone(bulk[top.pk]["next_level"])
        self.assertEqual(stats.progress_bulk([]), {})

    def test_progress_bulk_query_count_does_not_grow(self):
        creators = [self.creator] + [f.make_creator() for _ in range(5)]
        for creator in creators:
            self._fill(creator, publications=1, registrations=1, paying=1)
        # Как в списке админки: уровни не подгружены заранее.
        loaded = list(Creator.objects.filter(pk__in=[creator.pk for creator in creators]))
        with CaptureQueriesContext(connection) as one:
            stats.progress_bulk(loaded[:1])
        with CaptureQueriesContext(connection) as many:
            stats.progress_bulk(loaded)
        self.assertEqual(len(one), len(many))
        self.assertLessEqual(len(many), 5)


class CheckNextLevelTests(f.CreatorsTestCase):
    def setUp(self):
        super().setUp()
        self.creator = f.make_creator()
        _thresholds("creator_pro", 1, 1, 0)
        _thresholds("ambassador", 1, 1, 0)
        patcher = mock.patch("creators.stats.notify.emit")
        self.emit = patcher.start()
        self.addCleanup(patcher.stop)

    def _meet(self):
        _publication(self.creator)
        f.make_referral(self.creator)

    def test_not_met(self):
        self.assertFalse(stats.check_next_level(self.creator))
        self.emit.assert_not_called()
        self.creator.refresh_from_db()
        self.assertEqual(self.creator.next_level_notified, "")

    def test_emits_once_per_level(self):
        self._meet()
        self.assertTrue(stats.check_next_level(self.creator))
        self.emit.assert_called_once_with(self.creator, "next_level_ready",
                                          next_title="CREATOR PRO", next_percent="15.00")
        self.assertFalse(stats.check_next_level(self.creator))
        # Объект, загруженный заново (другой запрос), тоже не шлёт второй раз.
        self.assertFalse(stats.check_next_level(Creator.objects.get(pk=self.creator.pk)))
        self.assertEqual(self.emit.call_count, 1)
        self.creator.refresh_from_db()
        self.assertEqual(self.creator.next_level_notified, "creator_pro")

    def test_stale_object_does_not_send_twice(self):
        self._meet()
        stale = Creator.objects.get(pk=self.creator.pk)
        self.assertTrue(stats.check_next_level(self.creator))
        # У второго объекта отметки ещё нет — решает условный UPDATE в базе.
        self.assertEqual(stale.next_level_notified, "")
        self.assertFalse(stats.check_next_level(stale))
        self.assertEqual(self.emit.call_count, 1)

    def test_never_changes_the_level(self):
        self._meet()
        stats.check_next_level(self.creator)
        self.creator.refresh_from_db()
        self.assertEqual(self.creator.level.key, "creator")

    def test_emits_again_after_a_level_change(self):
        self._meet()
        self.assertTrue(stats.check_next_level(self.creator))
        # Администратор поднял уровень (program.set_level очищает отметку).
        Creator.objects.filter(pk=self.creator.pk).update(
            level=levels.get_level("creator_pro"), next_level_notified="")
        creator = Creator.objects.get(pk=self.creator.pk)
        self.assertTrue(stats.check_next_level(creator))
        self.assertEqual(self.emit.call_count, 2)
        self.assertEqual(self.emit.call_args.kwargs,
                         {"next_title": "AMBASSADOR", "next_percent": "20.00"})
        creator.refresh_from_db()
        self.assertEqual(creator.next_level_notified, "ambassador")
        self.assertEqual(creator.level.key, "creator_pro")

    def test_top_level_never_emits(self):
        top = f.make_creator(level="ambassador_pro")
        _publication(top)
        self.assertFalse(stats.check_next_level(top))
        self.emit.assert_not_called()

    def test_never_raises(self):
        self._meet()
        with mock.patch("creators.stats.progress", side_effect=RuntimeError("boom")):
            self.assertFalse(stats.check_next_level(self.creator))
        self.assertFalse(stats.check_next_level(None))
        self.emit.assert_not_called()


class CheckNextLevelDeliveryTests(f.CreatorsTestCase):
    def test_delivered_notification(self):
        from users.models import NotificationDelivery

        creator = f.make_creator()
        _thresholds("creator_pro", 1, 0, 0)
        _publication(creator)
        with mock.patch("botapi.tasks.notify") as telegram:
            with self.captureOnCommitCallbacks(execute=True):
                self.assertTrue(stats.check_next_level(creator))
        delivery = NotificationDelivery.objects.get(recipient=creator.user)
        self.assertEqual(delivery.notification.title, "Условия уровня выполнены")
        self.assertIn("CREATOR PRO", delivery.notification.body)
        self.assertEqual(telegram.call_args.args[1], "creator")


class PurchaseCompletesTheLevelTests(f.CreatorsTestCase):
    """[gate] Покупка, закрывшая последнее условие уровня, сообщает об этом (ТЗ п.15, 36).

    Проверяется связка двух модулей: начисление комиссии (commission.accrue)
    само зовёт check_next_level — отдельной задачи, которая заметила бы
    выполненные условия позже, нет.
    """

    def test_first_paying_user_meets_the_last_condition(self):
        from .. import commission

        creator = f.make_creator()
        _thresholds("creator_pro", 0, 0, 1)
        buyer = f.make_user()
        f.make_referral(creator, buyer)
        self.assertFalse(stats.progress(creator)["conditions_met"])

        with mock.patch("creators.notify.emit") as emit, \
                mock.patch("creators.commission.kgs_rate",
                           return_value=(Decimal("0.0115"), "test")):
            for _ in range(2):
                payment = f.make_payment(buyer)
                f.credit_purchase(payment)
                row = commission.accrue(payment)
                self.assertEqual(row.status, "accrued")

        ready = [call for call in emit.call_args_list if call.args[1] == "next_level_ready"]
        # Одно уведомление: вторая покупка того же уровня его не повторяет.
        self.assertEqual(len(ready), 1)
        self.assertEqual(ready[0].kwargs, {"next_title": "CREATOR PRO", "next_percent": "15.00"})
        creator.refresh_from_db()
        self.assertEqual(creator.next_level_notified, "creator_pro")
        # Сам уровень покупка не меняет.
        self.assertEqual(creator.level.key, "creator")
