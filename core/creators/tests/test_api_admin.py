"""Раздел Creators в админке: каждый адрес §8.4 — ответ, фильтры, коды ошибок."""
from unittest.mock import patch

from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from adminapi.runtime import get_runtime, set_runtime
from audit.models import AdminActionLog
from plans.models import PromoCode
from plans.wallet import charge_tokens, credit_tokens
from users.models import Notification

from .. import flags
from ..models import (
    Creator,
    CreatorCode,
    CreatorCommission,
    CreatorLevel,
    CreatorPublication,
    CreatorReferral,
    CreatorWithdrawal,
)
from . import factories as f
from . import test_api_public as api
from . import test_commission as money

M = api.MANAGE + "creators/"
PAYMENTS = api.MANAGE + "payments/"

LIST_ROW = {"id", "user_id", "email", "username", "display_name", "telegram", "level", "percent",
            "status", "code", "clicks", "registrations", "paying", "sales_usdt", "earned_usdt",
            "credits_granted", "conditions_met", "joined_at"}


class AdminTestCase(api.ApiTestCase):
    def setUp(self):
        super().setUp()
        self.su_user = f.make_user(superuser=True)
        self.staff_user = f.make_user(staff=True)
        self.su = self.client_for(self.su_user)
        self.staff = self.client_for(self.staff_user)

    def logs(self, action):
        return AdminActionLog.objects.filter(action=action).exclude(reason="factory")

    def publication(self, creator, n=1, status="review"):
        return CreatorPublication.objects.create(
            creator=creator, network="instagram", url=f"https://instagram.com/p/{n}",
            url_norm=f"instagram.com/p/{creator.pk}-{n}", status=status)


# ------------------------------------------------------------------- заявки

class ApplicationAdminTests(AdminTestCase):
    def test_list_filters_and_shape(self):
        first = api.make_application(f.make_user(email="anna@example.com"), name="Анна")
        api.make_application(f.make_user(email="boris@example.com"), name="Борис",
                             status="rejected", decided_by=self.su_user)

        response = self.staff.get(M + "applications/")
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(set(response.data), {"count", "results"})
        self.assertEqual(response.data["count"], 2)
        row = next(r for r in response.data["results"] if r["id"] == first.pk)
        for key in ("user_id", "email", "decided_by_email", "name", "telegram", "country",
                    "instagram_url", "tiktok_url", "youtube_url", "other_links", "followers",
                    "occupation", "motivation", "samples", "status", "created_at", "decided_at",
                    "reject_reason", "lang", "ip"):
            self.assertIn(key, row)
        self.assertEqual(row["email"], "anna@example.com")
        self.assertIsNone(row["decided_by_email"])

        rejected = self.staff.get(M + "applications/", {"status": "rejected"})
        self.assertEqual(rejected.data["count"], 1)
        self.assertEqual(rejected.data["results"][0]["decided_by_email"], self.su_user.email)
        self.assertEqual(self.staff.get(M + "applications/", {"q": "boris@"}).data["count"], 1)
        self.assertEqual(self.staff.get(M + "applications/", {"q": "Анна"}).data["count"], 1)
        self.assertEqual(self.staff.get(M + "applications/", {"page": 3}).data,
                         {"count": 2, "results": []})

    def test_approve_requires_a_level(self):
        application = api.make_application()
        for body in ({}, {"level": ""}, {"level": None}):
            response = self.su.post(M + f"applications/{application.pk}/approve/", body,
                                    format="json")
            self.assertError(response, 400, "validation")
            self.assertIn("level", response.data["fields"])
        # Уровня по умолчанию нет: без выбора не создано ничего.
        self.assertFalse(Creator.objects.exists())
        application.refresh_from_db()
        self.assertEqual(application.status, "new")

    def test_approve(self):
        application = api.make_application(name="Тора", telegram="@tora", lang="en")
        response = self.staff.post(M + f"applications/{application.pk}/approve/",
                                   {"level": "creator"}, format="json")
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(set(response.data), {"application", "creator"})
        self.assertEqual(response.data["application"]["status"], "approved")
        self.assertEqual(response.data["application"]["decided_by_email"], self.staff_user.email)
        row = response.data["creator"]
        self.assertEqual(set(row), LIST_ROW)
        self.assertEqual(row["level"], {"key": "creator", "title": "CREATOR"})
        self.assertEqual(row["percent"], "10.00")
        self.assertEqual((row["display_name"], row["telegram"], row["status"], row["code"]),
                         ("Тора", "@tora", "active", None))
        creator = Creator.objects.get(pk=row["id"])
        self.assertEqual(creator.user_id, application.user_id)
        self.assertEqual(creator.lang, "en")
        # Код не создаётся: его придумывает сам креатор.
        self.assertFalse(CreatorCode.objects.exists())

        again = self.staff.post(M + f"applications/{application.pk}/approve/",
                                {"level": "creator"}, format="json")
        self.assertError(again, 409, "bad_state")

    def test_approval_notifies_the_new_creator(self):
        """Через API проходит и уведомление: в приложении и в боте, после фиксации."""
        application = api.make_application(lang="en")
        with self.captureOnCommitCallbacks(execute=True):
            response = self.su.post(M + f"applications/{application.pk}/approve/",
                                    {"level": "creator_pro"}, format="json")
        self.assertEqual(response.status_code, 200, response.data)
        note = Notification.objects.latest("id")
        self.assertEqual(note.title, "Application approved")
        self.assertIn("15%", note.body)
        self.assertTrue(note.deliveries.filter(recipient=application.user).exists())
        self.assertEqual(self.tg.call_args.args[:2], (application.user, "creator"))

    def test_refused_approval_notifies_nobody(self):
        application = api.make_application()
        with self.captureOnCommitCallbacks(execute=True):
            self.assertError(self.staff.post(M + f"applications/{application.pk}/approve/",
                                             {"level": "ambassador"}, format="json"),
                             403, "superuser_required")
        self.assertFalse(Notification.objects.exists())
        self.tg.assert_not_called()

    def test_approve_errors(self):
        application = api.make_application()
        url = M + f"applications/{application.pk}/approve/"
        self.assertError(self.su.post(url, {"level": "legend"}, format="json"),
                         400, "level_unknown")
        self.assertError(self.staff.post(url, {"level": "ambassador"}, format="json"),
                         403, "superuser_required")
        self.assertError(self.su.post(M + "applications/999999/approve/", {"level": "creator"},
                                      format="json"), 404, "not_found")
        f.make_creator(application.user)
        self.assertError(self.su.post(url, {"level": "creator"}, format="json"),
                         409, "already_creator")
        self.assertEqual(Creator.objects.count(), 1)

    def test_superuser_may_approve_with_a_higher_level(self):
        application = api.make_application()
        response = self.su.post(M + f"applications/{application.pk}/approve/",
                                {"level": "ambassador"}, format="json")
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["creator"]["percent"], "20.00")

    def test_reject_block_unblock(self):
        application = api.make_application()
        url = M + f"applications/{application.pk}/"
        response = self.staff.post(url + "reject/", {"reason": "Мало работ"}, format="json")
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual((response.data["status"], response.data["reject_reason"]),
                         ("rejected", "Мало работ"))
        self.assertError(self.staff.post(url + "reject/", {}, format="json"), 409, "bad_state")

        second = api.make_application()
        url = M + f"applications/{second.pk}/"
        # Строка "false" из формы — не блокировка.
        self.assertEqual(self.staff.post(url + "reject/", {"block": "false"},
                                         format="json").data["status"], "rejected")

        third = api.make_application()
        url = M + f"applications/{third.pk}/"
        self.assertError(self.staff.post(url + "reject/", {"block": True}, format="json"),
                         403, "superuser_required")
        third.refresh_from_db()
        self.assertEqual(third.status, "new")
        self.assertEqual(self.su.post(url + "reject/", {"block": True, "reason": "Накрутка"},
                                      format="json").data["status"], "blocked")

        self.assertError(self.su.post(url + "unblock/", {}, format="json"),
                         400, "reason_required")
        response = self.su.post(url + "unblock/", {"reason": "Ошиблись"}, format="json")
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["status"], "rejected")
        self.assertError(self.su.post(url + "unblock/", {"reason": "Ещё раз"}, format="json"),
                         409, "bad_state")


# ----------------------------------------------------------------- креаторы

class CreatorsListTests(AdminTestCase):
    def test_columns_of_the_list(self):
        """Столбцы ТЗ п.30."""
        application = api.make_application(telegram="@creator_example")
        creator = f.make_creator(application.user, level="creator_pro", code="TORA20",
                                 display_name="Tora", application=application)
        buyer = f.make_user()
        f.make_referral(creator, buyer)
        f.make_referral(creator, f.make_user(), suspect=True)
        f.make_commission(creator, buyer=buyer, amount="15.009000", base="100.059000")
        f.make_commission(creator, buyer=buyer, amount="7.000000", status="held",
                          reason="creator_blocked")
        credit_tokens(creator.user, 1000, "creator_credit", meta={"category": "start"})
        credit_tokens(creator.user, 500, "creator_credit", meta={"category": "content"})
        credit_tokens(creator.user, 300, "purchase", meta={})
        self.client_for().post(api.API + "click/", {"code": "TORA20"}, format="json",
                               HTTP_X_DEVICE_KEY="d1")

        response = self.staff.get(M)
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["count"], 1)
        row = response.data["results"][0]
        self.assertEqual(set(row), LIST_ROW)
        self.assertEqual(row["id"], creator.pk)
        self.assertEqual(row["user_id"], creator.user_id)
        self.assertEqual(row["email"], creator.user.email)
        self.assertEqual(row["display_name"], "Tora")
        self.assertEqual(row["telegram"], "@creator_example")
        self.assertEqual(row["level"], {"key": "creator_pro", "title": "CREATOR PRO"})
        self.assertEqual(row["percent"], "15.00")
        self.assertEqual(row["status"], "active")
        self.assertEqual(row["code"], "TORA20")
        self.assertEqual(row["clicks"], 1)
        self.assertEqual(row["registrations"], 1)
        self.assertEqual(row["paying"], 1)
        self.assertEqual(row["sales_usdt"], "110.05")
        self.assertEqual(row["earned_usdt"], "15.00")
        self.assertEqual(row["credits_granted"], 1500)
        self.assertFalse(row["conditions_met"])

    def test_filters(self):
        tora = f.make_creator(f.make_user(email="tora@example.com"), code="TORA20",
                              display_name="Tora")
        aziz = f.make_creator(f.make_user(email="aziz@example.com"), level="ambassador",
                              display_name="Азиз", status="blocked")
        # Старый код после замены — тоже повод найти креатора.
        CreatorCode.objects.create(code="OLDAZIZ", creator=aziz, is_primary=False)

        def ids(**params):
            return {row["id"] for row in self.staff.get(M, params).data["results"]}

        self.assertEqual(ids(), {tora.pk, aziz.pk})
        self.assertEqual(ids(status="blocked"), {aziz.pk})
        self.assertEqual(ids(level="ambassador"), {aziz.pk})
        self.assertEqual(ids(q="tora2"), {tora.pk})
        self.assertEqual(ids(q="oldaz"), {aziz.pk})
        self.assertEqual(ids(q="aziz@"), {aziz.pk})
        self.assertEqual(ids(q="Ази"), {aziz.pk})
        self.assertEqual(ids(q="nobody"), set())
        self.assertEqual(self.staff.get(M, {"page": 2}).data, {"count": 2, "results": []})

    def test_ready_filter(self):
        ready = f.make_creator()
        f.make_creator()
        CreatorLevel.objects.filter(key="creator_pro").update(
            min_publications=1, min_registrations=1, min_paying=0)
        self.publication(ready, status="approved")
        f.make_referral(ready, f.make_user())

        response = self.staff.get(M, {"ready": 1})
        self.assertEqual(response.data["count"], 1)
        self.assertEqual(response.data["results"][0]["id"], ready.pk)
        self.assertTrue(response.data["results"][0]["conditions_met"])
        # Уровень при этом не изменился: повышение только вручную.
        ready.refresh_from_db()
        self.assertEqual(ready.level.key, "creator")
        everyone = self.staff.get(M).data
        self.assertEqual(everyone["count"], 2)
        self.assertEqual(sorted(row["conditions_met"] for row in everyone["results"]),
                         [False, True])

    def _populate(self, count):
        for n in range(count):
            creator = f.make_creator(code=f"BULK{n:04d}X{CreatorCode.objects.count()}")
            buyer = f.make_user()
            f.make_referral(creator, buyer)
            f.make_commission(creator, buyer=buyer)
            credit_tokens(creator.user, 10, "creator_credit", meta={"category": "start"})

    def test_list_has_no_n_plus_one(self):
        self._populate(2)
        with CaptureQueriesContext(connection) as small:
            self.assertEqual(self.staff.get(M).data["count"], 2)
        self._populate(8)
        with CaptureQueriesContext(connection) as big:
            self.assertEqual(self.staff.get(M).data["count"], 10)
        self.assertEqual(len(big), len(small))
        self.assertLessEqual(len(big), 20)
        with CaptureQueriesContext(connection) as ready:
            self.staff.get(M, {"ready": 1})
        self.assertLessEqual(len(ready), 20)


class CreatorProfileTests(AdminTestCase):
    def test_profile_blocks(self):
        """Блоки ТЗ п.31."""
        application = api.make_application(telegram="@creator_example")
        creator = f.make_creator(application.user, code="TORA20", application=application,
                                 payout_address=f.VALID_TRC20)
        CreatorCode.objects.create(code="OLDTORA", creator=creator, is_primary=False)
        buyer = f.make_user(email="buyer@example.com")
        f.make_referral(creator, buyer)
        f.make_referral(creator, f.make_user(), suspect=True)
        f.make_commission(creator, buyer=buyer, amount="30.000000", base="300.000000",
                          available_in_days=-1)
        f.make_commission(creator, buyer=buyer, status="held", reason="creator_blocked")
        f.make_commission(creator, buyer=buyer, status="reversed", reason="refund:freedompay")
        f.make_commission(creator, buyer=buyer, status="reversed", reason="fraud")
        self.publication(creator)
        f.make_withdrawal(creator, "12.00")
        credit_tokens(creator.user, 100, "creator_credit",
                      meta={"category": "start", "note": "Старт", "by_id": self.su_user.pk})
        charge_tokens(creator.user, 30, "chat")

        response = self.staff.get(M + f"{creator.pk}/")
        self.assertEqual(response.status_code, 200, response.data)
        data = response.data
        self.assertEqual(set(data), {"creator", "application", "codes", "counters", "money",
                                     "progress", "publications", "referrals", "credits",
                                     "withdrawals", "risk", "log"})
        self.assertEqual(set(data["creator"]), LIST_ROW | {
            "lang", "blocked_at", "blocked_reason", "payout_address",
            "payout_address_changed_at"})
        self.assertEqual(data["creator"]["code"], "TORA20")
        self.assertEqual(data["creator"]["earned_usdt"], "30.00")
        self.assertEqual(data["creator"]["credits_granted"], 100)
        self.assertEqual(data["creator"]["payout_address"], f.VALID_TRC20)
        self.assertEqual(data["application"]["id"], application.pk)
        self.assertEqual(data["application"]["telegram"], "@creator_example")
        self.assertEqual([(c["code"], c["is_primary"], c["is_active"]) for c in data["codes"]],
                         [("TORA20", True, True), ("OLDTORA", False, True)])
        # Админ видит и подозрительные привязки.
        self.assertEqual(data["counters"]["registrations"], 1)
        self.assertEqual(data["counters"]["suspect_referrals"], 1)
        self.assertEqual(data["counters"]["sales_usdt"], "310.00")
        self.assertEqual(data["money"]["earned"], "30.00")
        self.assertEqual(data["money"]["held"], "1.50")
        self.assertEqual(data["money"]["in_withdrawal"], "12.00")
        self.assertIn("conditions_met", data["progress"])
        self.assertEqual(len(data["publications"]), 1)
        self.assertEqual(data["publications"][0]["creator_id"], creator.pk)
        self.assertEqual(len(data["referrals"]), 2)
        paying = next(r for r in data["referrals"] if r["user_id"] == buyer.pk)
        self.assertEqual(paying["email"], "buyer@example.com")
        self.assertTrue(paying["is_paying"])
        self.assertEqual(len(data["withdrawals"]), 1)
        self.assertTrue(data["withdrawals"][0]["covered"])
        self.assertEqual(data["risk"], {"suspect_referrals": 1, "held_commissions": 1,
                                        "reversed_commissions": 2, "debt": "0.00"})
        self.assertTrue(any(row["action"] == "application.approve" for row in data["log"]))

    def test_credits_block_has_grants_and_spends(self):
        creator = f.make_creator()
        credit_tokens(creator.user, 100, "creator_credit",
                      meta={"category": "start", "note": "Старт", "by_id": self.su_user.pk})
        charge_tokens(creator.user, 30, "chat")
        credit_tokens(creator.user, 50, "purchase", meta={})

        block = self.staff.get(M + f"{creator.pk}/").data["credits"]
        self.assertEqual({key: block[key] for key in ("granted", "remaining", "spent",
                                                      "wallet_balance")},
                         {"granted": 100, "remaining": 70, "spent": 30, "wallet_balance": 120})
        self.assertEqual([row["kind"] for row in block["history"]], ["spend", "grant"])
        self.assertEqual(block["history"][0]["amount"], -30)
        self.assertEqual(block["history"][1]["by_email"], self.su_user.email)

    def test_unknown_creator(self):
        self.assertError(self.staff.get(M + "999999/"), 404, "not_found")
        self.assertError(self.su.post(M + "999999/block/", {"reason": "x"}, format="json"),
                         404, "not_found")

    def test_debt_is_shown_in_risk(self):
        creator = f.make_creator()
        f.make_withdrawal(creator, "20.00", status="paid")
        data = self.staff.get(M + f"{creator.pk}/").data
        self.assertEqual(data["risk"]["debt"], "20.00")
        self.assertFalse(data["withdrawals"][0]["covered"])


class CreatorActionTests(AdminTestCase):
    def setUp(self):
        super().setUp()
        self.creator = f.make_creator(code="TORA20")
        self.url = M + f"{self.creator.pk}/"

    def test_level(self):
        response = self.su.post(self.url + "level/", {"level": "ambassador", "reason": "Рост"},
                                format="json")
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(set(response.data), LIST_ROW)
        self.assertEqual(response.data["level"]["key"], "ambassador")
        self.assertEqual(response.data["percent"], "20.00")
        log = self.logs("creator.level_change").get()
        self.assertEqual((log.before["level"], log.after["level"], log.reason),
                         ("creator", "ambassador", "Рост"))
        # Понизить тоже можно.
        self.assertEqual(self.su.post(self.url + "level/", {"level": "creator"},
                                      format="json").data["percent"], "10.00")

        self.assertError(self.su.post(self.url + "level/", {"level": "legend"}, format="json"),
                         400, "level_unknown")
        self.assertError(self.su.post(self.url + "level/", {}, format="json"),
                         400, "level_unknown")
        self.assertError(self.su.post(self.url + "level/", {"level": "creator"}, format="json"),
                         409, "bad_state")

    def test_block_and_unblock(self):
        withdrawal = f.make_withdrawal(self.creator, "10.00", status="approved")
        self.assertError(self.su.post(self.url + "block/", {}, format="json"),
                         400, "reason_required")
        response = self.su.post(self.url + "block/", {"reason": "Накрутка"}, format="json")
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["status"], "blocked")
        withdrawal.refresh_from_db()
        self.assertEqual((withdrawal.status, withdrawal.reject_reason),
                         ("rejected", "creator_blocked"))
        self.assertError(self.su.post(self.url + "block/", {"reason": "Ещё"}, format="json"),
                         409, "bad_state")

        response = self.su.post(self.url + "unblock/", {}, format="json")
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["status"], "active")
        self.assertError(self.su.post(self.url + "unblock/", {}, format="json"), 409, "bad_state")
        # Отклонённая заявка на вывод сама не оживает.
        withdrawal.refresh_from_db()
        self.assertEqual(withdrawal.status, "rejected")

    def test_code_change(self):
        response = self.su.post(self.url + "code/", {"code": "tora25", "reason": "Просьба"},
                                format="json")
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data, {"code": "TORA25", "link": "https://esai.kg/?ref=TORA25",
                                         "aliases": ["TORA20"]})
        # Старый код остался рабочим псевдонимом того же креатора.
        old = CreatorCode.objects.get(code="TORA20")
        self.assertEqual((old.creator_id, old.is_primary, old.is_active),
                         (self.creator.pk, False, True))

    def test_code_errors(self):
        other = f.make_creator(code="TAKEN01")
        PromoCode.objects.create(code="SALE2026", bonus_credits=10)

        def post(**body):
            return self.su.post(self.url + "code/", body, format="json")

        self.assertError(post(code="NEWCODE"), 400, "reason_required")
        self.assertError(post(code="ab", reason="r"), 400, "code_format")
        self.assertError(post(code="ADMIN", reason="r"), 400, "code_reserved")
        self.assertError(post(code="TAKEN01", reason="r"), 409, "code_taken")
        self.assertError(post(code="sale2026", reason="r"), 409, "code_taken")
        self.assertError(post(code="TORA20", reason="r"), 409, "code_unchanged")
        self.assertEqual(CreatorCode.objects.filter(creator=self.creator).count(), 1)
        self.assertEqual(CreatorCode.objects.get(code="TAKEN01").creator_id, other.pk)

    def test_grant_credits(self):
        response = self.su.post(self.url + "credits/",
                                {"amount": 1000, "category": "start", "note": "Старт"},
                                format="json")
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(set(response.data), {"granted", "remaining", "balance", "transaction"})
        self.assertEqual((response.data["granted"], response.data["remaining"],
                          response.data["balance"]), (1000, 1000, 1000))
        row = response.data["transaction"]
        self.assertEqual((row["amount"], row["category"], row["category_label"], row["note"],
                          row["by_email"]),
                         (1000, "start", "Старт", "Старт", self.su_user.email))
        self.creator.user.refresh_from_db()
        self.assertEqual(self.creator.user.token_balance, 1000)

        # Тот же запрос сразу следом — двойное нажатие кнопки.
        again = self.su.post(self.url + "credits/",
                             {"amount": 1000, "category": "start", "note": "Старт"},
                             format="json")
        self.assertError(again, 409, "duplicate_request")
        self.creator.user.refresh_from_db()
        self.assertEqual(self.creator.user.token_balance, 1000)

    def test_grant_credits_errors(self):
        def post(**body):
            return self.su.post(self.url + "credits/", body, format="json")

        for bad in (0, -5, "много", 12.5, None, True):
            self.assertError(post(amount=bad, category="start"), 400, "amount_invalid")
        self.assertError(post(amount=100, category="подарок"), 400, "category_invalid")
        self.assertError(post(amount=100), 400, "category_invalid")
        Creator.objects.filter(pk=self.creator.pk).update(status="blocked")
        self.assertError(post(amount=100, category="start"), 403, "creator_blocked")
        self.creator.user.refresh_from_db()
        self.assertEqual(self.creator.user.token_balance, 0)


# --------------------------------------------------------------- публикации

class PublicationAdminTests(AdminTestCase):
    def test_list_approve_reject(self):
        creator = f.make_creator(display_name="Tora")
        first = self.publication(creator, 1)
        second = self.publication(creator, 2)
        self.publication(f.make_creator(), 3, status="approved")

        response = self.staff.get(M + "publications/")
        self.assertEqual(response.data["count"], 3)
        row = next(r for r in response.data["results"] if r["id"] == first.pk)
        self.assertEqual(set(row), {"id", "creator_id", "creator_name", "network", "url",
                                    "description", "status", "created_at", "decided_at",
                                    "decided_by_email", "reject_reason"})
        self.assertEqual(row["creator_name"], "Tora")
        self.assertEqual(self.staff.get(M + "publications/", {"status": "review"}).data["count"], 2)
        self.assertEqual(self.staff.get(M + "publications/",
                                        {"creator": creator.pk}).data["count"], 2)
        self.assertEqual(self.staff.get(M + "publications/", {"creator": "abc"}).data["count"], 0)

        approved = self.staff.post(M + f"publications/{first.pk}/approve/")
        self.assertEqual(approved.status_code, 200, approved.data)
        self.assertEqual((approved.data["status"], approved.data["decided_by_email"]),
                         ("approved", self.staff_user.email))
        self.assertError(self.staff.post(M + f"publications/{first.pk}/approve/"),
                         409, "bad_state")

        rejected = self.staff.post(M + f"publications/{second.pk}/reject/",
                                   {"reason": "Не про EsAI"}, format="json")
        self.assertEqual((rejected.data["status"], rejected.data["reject_reason"]),
                         ("rejected", "Не про EsAI"))
        self.assertError(self.staff.post(M + f"publications/{second.pk}/reject/"),
                         409, "bad_state")
        self.assertError(self.staff.post(M + "publications/999999/approve/"), 404, "not_found")


# ----------------------------------------------------------------- рефералы

class ReferralAdminTests(AdminTestCase):
    def setUp(self):
        super().setUp()
        self.creator = f.make_creator(code="TORA20", display_name="Tora")

    def test_list_and_filters(self):
        buyer = f.make_user(email="buyer@example.com")
        paying = f.make_referral(self.creator, buyer)
        suspect = f.make_referral(self.creator, f.make_user(), suspect=True)
        ended = f.make_referral(f.make_creator(), f.make_user(email="gone@example.com"))
        CreatorReferral.objects.filter(pk=ended.pk).update(ended_at=timezone.now(),
                                                           end_reason="admin_unbind")
        f.make_commission(self.creator, buyer=buyer, amount="1.500000", base="10.000000")

        response = self.staff.get(M + "referrals/")
        self.assertEqual(response.data["count"], 3)
        row = next(r for r in response.data["results"] if r["id"] == paying.pk)
        self.assertEqual(set(row), {
            "id", "user_id", "email", "user_label", "creator_id", "creator_name", "source",
            "code_used", "bound_at", "bound_by_email", "ended_at", "end_reason", "suspect",
            "flags", "is_paying", "orders", "sales_usdt", "commission_usdt", "referred_by_id"})
        self.assertEqual((row["user_id"], row["email"], row["creator_name"], row["code_used"]),
                         (buyer.pk, "buyer@example.com", "Tora", "TORA20"))
        self.assertEqual((row["is_paying"], row["orders"], row["sales_usdt"],
                          row["commission_usdt"]), (True, 1, "10.00", "1.50"))

        def ids(**params):
            return {r["id"] for r in self.staff.get(M + "referrals/", params).data["results"]}

        self.assertEqual(ids(creator=self.creator.pk), {paying.pk, suspect.pk})
        self.assertEqual(ids(suspect=1), {suspect.pk})
        self.assertEqual(ids(active=1), {paying.pk, suspect.pk})
        self.assertEqual(ids(q="gone@"), {ended.pk})
        self.assertEqual(ids(q=str(buyer.pk)), {paying.pk})
        self.assertEqual(ids(q="tora2"), {paying.pk, suspect.pk})

    def test_rebind(self):
        user = f.make_user()
        other = f.make_creator(display_name="Aziz")
        old = f.make_referral(self.creator, user)

        response = self.su.post(M + "referrals/rebind/",
                                {"user_id": user.pk, "creator_id": other.pk,
                                 "reason": "Ошибка привязки"}, format="json")
        self.assertEqual(response.status_code, 200, response.data)
        row = response.data["referral"]
        self.assertEqual((row["user_id"], row["creator_id"], row["source"],
                          row["bound_by_email"]),
                         (user.pk, other.pk, "admin", self.su_user.email))
        old.refresh_from_db()
        self.assertEqual(old.end_reason, "admin_rebind")

        # Снять привязку совсем.
        response = self.su.post(M + "referrals/rebind/",
                                {"user_id": user.pk, "creator_id": None, "reason": "Просьба"},
                                format="json")
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data, {"referral": None})
        self.assertIsNone(CreatorReferral.objects.active_for(user.pk))

    def test_rebind_errors(self):
        user = f.make_user()
        f.make_referral(self.creator, user)
        blocked = f.make_creator(status="blocked")

        def post(**body):
            return self.su.post(M + "referrals/rebind/", body, format="json")

        self.assertError(post(user_id=user.pk, creator_id=self.creator.pk), 400, "reason_required")
        response = post(creator_id=self.creator.pk, reason="r")
        self.assertError(response, 400, "validation")
        self.assertIn("user_id", response.data["fields"])
        self.assertError(post(user_id=user.pk, creator_id="x", reason="r"), 400, "validation")
        self.assertError(post(user_id=999999, creator_id=self.creator.pk, reason="r"),
                         404, "not_found")
        self.assertError(post(user_id=user.pk, creator_id=999999, reason="r"), 404, "not_found")
        self.assertError(post(user_id=self.creator.user_id, creator_id=self.creator.pk,
                              reason="r"), 400, "self")
        self.assertError(post(user_id=self.staff_user.pk, creator_id=self.creator.pk,
                              reason="r"), 400, "staff")
        self.assertError(post(user_id=user.pk, creator_id=blocked.pk, reason="r"),
                         400, "creator_unusable")
        # Отказ откатил и снятие прежней привязки.
        self.assertEqual(CreatorReferral.objects.active_for(user.pk).creator_id, self.creator.pk)
        self.assertFalse(self.logs("referral.rebind").exists())

    def test_clear_suspect(self):
        buyer = f.make_user()
        referral = f.make_referral(self.creator, buyer, suspect=True)
        held = f.make_commission(self.creator, buyer=buyer, status="held",
                                 reason="referral_suspect")
        url = M + f"referrals/{referral.pk}/clear-suspect/"

        self.assertError(self.su.post(url, {}, format="json"), 400, "reason_required")
        response = self.su.post(url, {"reason": "Проверили", "release_held": True},
                                format="json")
        self.assertEqual(response.status_code, 200, response.data)
        self.assertFalse(response.data["suspect"])
        self.assertEqual(response.data["id"], referral.pk)
        held.refresh_from_db()
        self.assertEqual((held.status, held.reason), ("accrued", "released"))
        self.assertError(self.su.post(url, {"reason": "Ещё раз"}, format="json"), 409, "bad_state")
        self.assertError(self.su.post(M + "referrals/999999/clear-suspect/", {"reason": "r"},
                                      format="json"), 404, "not_found")

    def test_clear_suspect_keeps_held_rows_by_default(self):
        buyer = f.make_user()
        referral = f.make_referral(self.creator, buyer, suspect=True)
        held = f.make_commission(self.creator, buyer=buyer, status="held",
                                 reason="referral_suspect")
        response = self.su.post(M + f"referrals/{referral.pk}/clear-suspect/",
                                {"reason": "Проверили", "release_held": "false"}, format="json")
        self.assertEqual(response.status_code, 200, response.data)
        held.refresh_from_db()
        self.assertEqual(held.status, "held")


# ----------------------------------------------------------------- комиссии

class CommissionAdminTests(AdminTestCase):
    def setUp(self):
        super().setUp()
        self.creator = f.make_creator(display_name="Tora")

    def test_list_and_filters(self):
        buyer = f.make_user(email="buyer@example.com")
        accrued = f.make_commission(self.creator, buyer=buyer, amount="1.150000",
                                    base="11.500000")
        f.make_commission(self.creator, buyer=buyer, status="held", reason="creator_blocked")
        stars = f.make_payment(f.make_user(), provider="telegram_stars", amount="170")
        f.make_commission(f.make_creator(), stars)

        response = self.staff.get(M + "commissions/")
        self.assertEqual(response.data["count"], 3)
        row = next(r for r in response.data["results"] if r["id"] == accrued.pk)
        self.assertEqual(set(row), {
            "id", "created_at", "creator_id", "creator_name", "buyer_pk", "buyer_email",
            "payment_id", "order_id", "part", "provider", "paid_amount", "paid_currency",
            "rate_to_usd", "rate_source", "base_usd", "level_key", "percent", "amount_usdt",
            "status", "reason", "available_at", "reversed_at"})
        self.assertEqual((row["creator_name"], row["buyer_pk"], row["buyer_email"]),
                         ("Tora", buyer.pk, "buyer@example.com"))
        self.assertEqual((row["paid_amount"], row["paid_currency"], row["base_usd"],
                          row["amount_usdt"], row["percent"]),
                         ("490.00", "KGS", "11.500000", "1.150000", "10.00"))
        self.assertEqual(row["payment_id"], accrued.payment_id)

        def count(**params):
            return self.staff.get(M + "commissions/", params).data["count"]

        self.assertEqual(count(creator=self.creator.pk), 2)
        self.assertEqual(count(status="held"), 1)
        self.assertEqual(count(provider="telegram_stars"), 1)
        self.assertEqual(count(creator=self.creator.pk, status="accrued"), 1)

    def test_void(self):
        row = f.make_commission(self.creator)
        url = M + f"commissions/{row.pk}/void/"
        self.assertError(self.su.post(url, {}, format="json"), 400, "reason_required")
        response = self.su.post(url, {"reason": "Самовыкуп"}, format="json")
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual((response.data["status"], response.data["reason"]),
                         ("void", "admin_void"))
        self.assertError(self.su.post(url, {"reason": "Ещё"}, format="json"), 409, "bad_state")
        self.assertError(self.su.post(M + "commissions/999999/void/", {"reason": "r"},
                                      format="json"), 404, "not_found")

    def test_release(self):
        held = f.make_commission(self.creator, status="held", reason="creator_blocked")
        response = self.su.post(M + f"commissions/{held.pk}/release/")
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual((response.data["status"], response.data["reason"]),
                         ("accrued", "released"))
        self.assertError(self.su.post(M + f"commissions/{held.pk}/release/"), 409, "bad_state")

        refunded = f.make_payment(f.make_user())
        refunded.response = {"yookassa_refunded": True}
        refunded.save(update_fields=["response"])
        stuck = f.make_commission(self.creator, refunded, status="held",
                                  reason="creator_blocked")
        self.assertError(self.su.post(M + f"commissions/{stuck.pk}/release/"),
                         409, "payment_refunded")

    def test_restore(self):
        row = f.make_commission(self.creator, status="reversed", reason="refund:admin")
        url = M + f"commissions/{row.pk}/restore/"
        self.assertError(self.su.post(url, {}, format="json"), 400, "reason_required")
        response = self.su.post(url, {"reason": "Отмена была ошибкой"}, format="json")
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual((response.data["status"], response.data["reason"],
                          response.data["reversed_at"]), ("accrued", "restored", None))
        self.assertError(self.su.post(url, {"reason": "Ещё"}, format="json"), 409, "bad_state")

    def test_restore_of_a_refunded_payment(self):
        payment = f.make_payment(f.make_user())
        payment.response = {"admin_refund": {"kind": "refund", "by_id": self.su_user.pk}}
        payment.save(update_fields=["response"])
        row = f.make_commission(self.creator, payment, status="reversed", reason="refund:admin")
        url = M + f"commissions/{row.pk}/restore/"

        self.assertError(self.su.post(url, {"reason": "r"}, format="json"),
                         409, "payment_refunded")
        response = self.su.post(url, {"reason": "Отметка была ошибкой",
                                      "clear_admin_refund": True}, format="json")
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["status"], "accrued")
        payment.refresh_from_db()
        self.assertNotIn("admin_refund", payment.response)
        self.assertIn("admin_refund_cleared", payment.response)


# ------------------------------------------------------------------ выплаты

class WithdrawalAdminTests(AdminTestCase):
    def setUp(self):
        super().setUp()
        self.creator = f.make_creator(display_name="Tora", payout_address=f.VALID_TRC20)
        self.commission = f.make_commission(self.creator, amount="50.000000",
                                            base="500.000000", available_in_days=-1)

    def url(self, withdrawal, action):
        return M + f"withdrawals/{withdrawal.pk}/{action}/"

    def test_list_rows_carry_balance_and_covered(self):
        open_row = f.make_withdrawal(self.creator, "20.00")
        debtor = f.make_creator()
        f.make_withdrawal(debtor, "15.00", status="approved")
        f.make_withdrawal(self.creator, "10.00", status="paid", txid=f.VALID_TXID)

        response = self.staff.get(M + "withdrawals/")
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["count"], 3)
        row = next(r for r in response.data["results"] if r["id"] == open_row.pk)
        self.assertEqual(set(row), {
            "id", "creator_id", "creator_name", "creator_status", "email", "amount_usdt",
            "address", "network", "status", "txid", "created_at", "approved_at",
            "approved_by_email", "paid_at", "paid_by_email", "rejected_at", "reject_reason",
            "address_changed_at", "balance", "covered"})
        self.assertEqual((row["creator_name"], row["creator_status"], row["email"],
                          row["amount_usdt"], row["address"]),
                         ("Tora", "active", self.creator.user.email, "20.00", f.VALID_TRC20))
        self.assertTrue(row["covered"])
        self.assertEqual(row["balance"]["available"], "20.00")
        self.assertEqual(row["balance"]["in_withdrawal"], "20.00")
        self.assertEqual(row["balance"]["paid"], "10.00")
        # У второго креатора заявка есть, а денег под неё нет.
        uncovered = next(r for r in response.data["results"] if r["creator_id"] == debtor.pk)
        self.assertFalse(uncovered["covered"])
        self.assertEqual(uncovered["balance"]["debt"], "15.00")

        def count(**params):
            return self.staff.get(M + "withdrawals/", params).data["count"]

        self.assertEqual(count(status="review"), 1)
        self.assertEqual(count(status="paid"), 1)
        self.assertEqual(count(creator=debtor.pk), 1)

    def test_covered_turns_false_after_a_reversal(self):
        withdrawal = f.make_withdrawal(self.creator, "40.00")
        CreatorCommission.objects.filter(pk=self.commission.pk).update(
            status="reversed", reversed_at=timezone.now())
        row = self.staff.get(M + "withdrawals/").data["results"][0]
        self.assertEqual(row["id"], withdrawal.pk)
        self.assertFalse(row["covered"])
        self.assertError(self.su.post(self.url(withdrawal, "approve")),
                         400, "insufficient_available")

    def test_full_path(self):
        withdrawal = f.make_withdrawal(self.creator, "20.00")
        response = self.su.post(self.url(withdrawal, "approve"))
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual((response.data["status"], response.data["approved_by_email"]),
                         ("approved", self.su_user.email))
        self.assertError(self.su.post(self.url(withdrawal, "approve")), 409, "bad_state")

        self.assertError(self.su.post(self.url(withdrawal, "mark-paid"), {"txid": "xyz"},
                                      format="json"), 400, "txid_invalid")
        self.assertError(self.su.post(self.url(withdrawal, "mark-paid"), {}, format="json"),
                         400, "txid_invalid")
        response = self.su.post(self.url(withdrawal, "mark-paid"),
                                {"txid": "0x" + "AB" * 32}, format="json")
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual((response.data["status"], response.data["txid"],
                          response.data["paid_by_email"]),
                         ("paid", "ab" * 32, self.su_user.email))
        self.assertEqual(response.data["balance"]["paid"], "20.00")
        self.assertError(self.su.post(self.url(withdrawal, "mark-paid"),
                                      {"txid": "cd" * 32}, format="json"), 409, "bad_state")

        # Опечатка в TXID.
        self.assertError(self.su.post(self.url(withdrawal, "txid"), {"txid": "cd" * 32},
                                      format="json"), 400, "reason_required")
        self.assertError(self.su.post(self.url(withdrawal, "txid"),
                                      {"txid": "zz", "reason": "r"}, format="json"),
                         400, "txid_invalid")
        self.assertError(self.su.post(self.url(withdrawal, "txid"),
                                      {"txid": "ab" * 32, "reason": "r"}, format="json"),
                         409, "bad_state")
        response = self.su.post(self.url(withdrawal, "txid"),
                                {"txid": "cd" * 32, "reason": "Опечатка"}, format="json")
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["txid"], "cd" * 32)

        # Перевод не прошёл в сети.
        self.assertError(self.su.post(self.url(withdrawal, "reopen"), {}, format="json"),
                         400, "reason_required")
        response = self.su.post(self.url(withdrawal, "reopen"), {"reason": "Не дошло"},
                                format="json")
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual((response.data["status"], response.data["txid"],
                          response.data["paid_at"]), ("approved", "", None))
        self.assertError(self.su.post(self.url(withdrawal, "reopen"), {"reason": "r"},
                                      format="json"), 409, "bad_state")

    def test_reject(self):
        withdrawal = f.make_withdrawal(self.creator, "20.00")
        self.assertError(self.su.post(self.url(withdrawal, "reject"), {}, format="json"),
                         400, "reason_required")
        response = self.su.post(self.url(withdrawal, "reject"), {"reason": "Неверный адрес"},
                                format="json")
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual((response.data["status"], response.data["reject_reason"]),
                         ("rejected", "Неверный адрес"))
        # Деньги снова доступны.
        self.assertEqual(response.data["balance"]["available"], "50.00")
        self.assertError(self.su.post(self.url(withdrawal, "reject"), {"reason": "r"},
                                      format="json"), 409, "bad_state")
        self.assertError(self.su.post(M + "withdrawals/999999/approve/"), 404, "not_found")

    def test_txid_duplicate(self):
        f.make_withdrawal(self.creator, "10.00", status="paid", txid=f.VALID_TXID)
        other = f.make_creator()
        f.make_commission(other, amount="30.000000", base="300.000000", available_in_days=-1)
        withdrawal = f.make_withdrawal(other, "10.00", status="approved")
        self.assertError(self.su.post(self.url(withdrawal, "mark-paid"), {"txid": f.VALID_TXID},
                                      format="json"), 409, "txid_duplicate")
        paid = f.make_withdrawal(other, "10.00", status="rejected")
        CreatorWithdrawal.objects.filter(pk=paid.pk).update(status="paid", txid="ef" * 32)
        self.assertError(self.su.post(self.url(paid, "txid"),
                                      {"txid": f.VALID_TXID, "reason": "r"}, format="json"),
                         409, "txid_duplicate")

    def test_reopen_refused_while_another_request_is_open(self):
        paid = f.make_withdrawal(self.creator, "10.00", status="paid")
        f.make_withdrawal(self.creator, "10.00")
        self.assertError(self.su.post(self.url(paid, "reopen"), {"reason": "Не дошло"},
                                      format="json"), 409, "withdrawal_open")

    def test_mark_paid_after_block_or_reversal_needs_force(self):
        withdrawal = f.make_withdrawal(self.creator, "40.00", status="approved")
        Creator.objects.filter(pk=self.creator.pk).update(status="blocked")
        self.assertError(self.su.post(self.url(withdrawal, "mark-paid"), {"txid": f.VALID_TXID},
                                      format="json"), 403, "creator_blocked")
        Creator.objects.filter(pk=self.creator.pk).update(status="active")
        CreatorCommission.objects.filter(pk=self.commission.pk).update(
            status="reversed", reversed_at=timezone.now())
        self.assertError(self.su.post(self.url(withdrawal, "mark-paid"), {"txid": f.VALID_TXID},
                                      format="json"), 400, "insufficient_available")
        self.assertError(self.su.post(self.url(withdrawal, "mark-paid"),
                                      {"txid": f.VALID_TXID, "force": True}, format="json"),
                         400, "reason_required")
        response = self.su.post(self.url(withdrawal, "mark-paid"),
                                {"txid": f.VALID_TXID, "force": True,
                                 "reason": "Деньги уже ушли"}, format="json")
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["status"], "paid")
        self.assertFalse(response.data["covered"])
        self.assertTrue(self.logs("withdrawal.mark_paid").get().after["forced"])


# ------------------------------------------------- кредиты, уровни, журнал

class CreditsLevelsLogTests(AdminTestCase):
    def test_credits_list(self):
        tora = f.make_creator(display_name="Tora")
        aziz = f.make_creator(display_name="Aziz")
        credit_tokens(tora.user, 100, "creator_credit",
                      meta={"category": "start", "note": "", "by_id": self.su_user.pk})
        credit_tokens(aziz.user, 200, "creator_credit",
                      meta={"category": "content", "note": "", "by_id": self.su_user.pk})
        credit_tokens(tora.user, 999, "purchase", meta={})

        response = self.staff.get(M + "credits/")
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["count"], 2)
        self.assertEqual([row["amount"] for row in response.data["results"]], [200, 100])
        row = response.data["results"][0]
        for key in ("id", "date", "amount", "category", "category_label", "note", "by_id",
                    "by_email", "creator_id", "creator_name"):
            self.assertIn(key, row)
        self.assertEqual((row["creator_id"], row["creator_name"], row["by_email"]),
                         (aziz.pk, "Aziz", self.su_user.email))

        only = self.staff.get(M + "credits/", {"creator": tora.pk})
        self.assertEqual(only.data["count"], 1)
        self.assertEqual(only.data["results"][0]["creator_id"], tora.pk)
        self.assertEqual(self.staff.get(M + "credits/", {"creator": "abc"}).data,
                         {"count": 0, "results": []})
        self.assertEqual(self.staff.get(M + "credits/", {"page": 2}).data,
                         {"count": 2, "results": []})

    def test_levels_list(self):
        f.make_creator(level="creator_pro")
        f.make_creator(level="creator_pro")
        response = self.staff.get(M + "levels/")
        self.assertEqual(response.status_code, 200, response.data)
        rows = response.data["results"]
        self.assertEqual([row["key"] for row in rows],
                         ["creator", "creator_pro", "ambassador", "ambassador_pro"])
        self.assertEqual(set(rows[0]), {"key", "title", "percent", "sort", "min_publications",
                                        "min_registrations", "min_paying", "creators"})
        self.assertEqual([row["creators"] for row in rows], [0, 2, 0, 0])

    def test_level_edit(self):
        f.make_creator(level="creator_pro")
        url = M + "levels/creator_pro/"
        response = self.su.patch(url, {"percent": "17.5", "min_paying": 12,
                                       "reason": "Новые условия"}, format="json")
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual((response.data["percent"], response.data["min_paying"],
                          response.data["creators"]), ("17.50", 12, 1))
        log = self.logs("level.edit").get()
        self.assertEqual(log.reason, "Новые условия")
        self.assertEqual(set(log.after), {"percent", "min_paying"})

        for bad in ("0", "25.01", "-1", "много"):
            self.assertError(self.su.patch(url, {"percent": bad}, format="json"),
                             400, "percent_invalid")
        self.assertError(self.su.patch(url, {"key": "other"}, format="json"), 400, "validation")
        self.assertError(self.su.patch(url, {}, format="json"), 400, "validation")
        self.assertError(self.su.patch(url, {"min_paying": -3}, format="json"), 400, "validation")
        self.assertError(self.su.patch(M + "levels/legend/", {"percent": "5"}, format="json"),
                         400, "level_unknown")
        self.assertEqual(self.logs("level.edit").count(), 1)
        self.assertEqual(str(CreatorLevel.objects.get(key="creator_pro").percent), "17.50")

    def test_log_list_and_filters(self):
        creator = f.make_creator()
        self.su.post(M + f"{creator.pk}/block/", {"reason": "Накрутка"}, format="json",
                     HTTP_X_FORWARDED_FOR="203.0.113.7")
        self.su.post(M + f"{creator.pk}/unblock/", {"reason": "Разобрались"}, format="json")

        response = self.staff.get(M + "log/", {"creator": creator.pk})
        self.assertEqual(response.status_code, 200, response.data)
        # Третья строка — одобрение из фабрики.
        self.assertEqual(response.data["count"], 3)
        row = response.data["results"][0]
        self.assertEqual(set(row), {"id", "created_at", "actor_id", "actor_email", "action",
                                    "target_type", "target_id", "creator_id", "before", "after",
                                    "reason", "ip"})
        self.assertEqual((row["action"], row["actor_id"], row["actor_email"], row["creator_id"],
                          row["reason"], row["target_type"], row["target_id"]),
                         ("creator.unblock", self.su_user.pk, self.su_user.email, creator.pk,
                          "Разобрались", "creators.creator", str(creator.pk)))

        blocked = self.staff.get(M + "log/", {"action": "creator.block"})
        self.assertEqual(blocked.data["count"], 1)
        self.assertEqual(blocked.data["results"][0]["ip"], "203.0.113.7")
        self.assertEqual(blocked.data["results"][0]["after"], {"status": "blocked"})
        self.assertEqual(self.staff.get(M + "log/", {"actor": self.su_user.pk}).data["count"], 2)
        self.assertEqual(self.staff.get(M + "log/", {"actor": self.staff_user.pk}).data["count"], 0)
        self.assertEqual(self.staff.get(M + "log/", {"creator": "abc"}).data["count"], 0)


# ---------------------------------------------------------------- настройки

class SettingsTests(AdminTestCase):
    def test_read(self):
        response = self.su.get(M + "settings/")
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data, {"mode": "on", "payouts_enabled": True, "hold_days": 14})

    def test_patch_writes_runtime_and_log(self):
        response = self.su.patch(M + "settings/", {"mode": "staff", "payouts_enabled": False,
                                                   "hold_days": 30}, format="json")
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data, {"mode": "staff", "payouts_enabled": False,
                                         "hold_days": 30})
        self.assertEqual((flags.mode(), flags.payouts_enabled(), flags.hold_days()),
                         ("staff", False, 30))
        log = self.logs("settings.edit").get()
        self.assertEqual(log.actor_id, self.su_user.pk)
        self.assertEqual(log.before, {"mode": "on", "payouts_enabled": True, "hold_days": 14})
        self.assertEqual(log.after, {"mode": "staff", "payouts_enabled": False, "hold_days": 30})

        # Те же значения ещё раз — менять нечего, в журнале пусто.
        self.su.patch(M + "settings/", {"mode": "staff", "hold_days": "30"}, format="json")
        self.assertEqual(self.logs("settings.edit").count(), 1)

        response = self.su.patch(M + "settings/", {"payouts_enabled": "true"}, format="json")
        self.assertTrue(response.data["payouts_enabled"])
        self.assertEqual(self.logs("settings.edit").first().after, {"payouts_enabled": True})

    def test_admin_api_works_when_the_program_is_off(self):
        self.su.patch(M + "settings/", {"mode": "off"}, format="json")
        self.assertEqual(self.su.get(M + "settings/").data["mode"], "off")
        self.assertEqual(self.staff.get(M).status_code, 200)
        self.assertError(self.client_for().get(api.API + "program/"), 404, "disabled")

    def test_validation_writes_nothing(self):
        cases = [({"mode": "maybe"}, "mode"), ({"payouts_enabled": "perhaps"}, "payouts_enabled"),
                 ({"hold_days": 91}, "hold_days"), ({"hold_days": -1}, "hold_days"),
                 ({"hold_days": "две недели"}, "hold_days"), ({"hold_days": 1.5}, "hold_days"),
                 ({}, "settings"), ({"unknown": 1}, "settings")]
        for body, field in cases:
            response = self.su.patch(M + "settings/", body, format="json")
            self.assertError(response, 400, "validation")
            self.assertIn(field, response.data["fields"])
        # Одно неверное поле — не сохраняется ничего.
        response = self.su.patch(M + "settings/", {"mode": "off", "hold_days": 500},
                                 format="json")
        self.assertError(response, 400, "validation")
        self.assertEqual(flags.mode(), "on")
        self.assertFalse(self.logs("settings.edit").exists())


class KgsRateLogTests(AdminTestCase):
    """Ручной курс сом -> доллар задаёт сумму комиссий, поэтому его правка — в журнале."""

    URL = api.MANAGE + "settings/"

    def test_set_change_reset(self):
        response = self.staff.patch(self.URL, {"currency_kgs_to_usd_rate": 0.0115},
                                    format="json")
        self.assertEqual(response.status_code, 200, response.data)
        log = self.logs("settings.edit").get()
        self.assertEqual(log.actor_id, self.staff_user.pk)
        self.assertEqual(log.before, {"currency_kgs_to_usd_rate": None})
        self.assertEqual(log.after, {"currency_kgs_to_usd_rate": 0.0115})
        self.assertEqual(get_runtime("currency_kgs_to_usd_rate", 0.0), 0.0115)

        # То же значение — записи нет.
        self.staff.patch(self.URL, {"currency_kgs_to_usd_rate": "0.0115"}, format="json")
        self.assertEqual(self.logs("settings.edit").count(), 1)

        self.staff.patch(self.URL, {"currency_kgs_to_usd_rate": 0.012}, format="json")
        log = self.logs("settings.edit").first()
        self.assertEqual((log.before, log.after), ({"currency_kgs_to_usd_rate": 0.0115},
                                                   {"currency_kgs_to_usd_rate": 0.012}))

        self.staff.patch(self.URL, {"currency_kgs_to_usd_rate": ""}, format="json")
        log = self.logs("settings.edit").first()
        self.assertEqual((log.before, log.after), ({"currency_kgs_to_usd_rate": 0.012},
                                                   {"currency_kgs_to_usd_rate": None}))
        self.assertEqual(self.logs("settings.edit").count(), 3)
        self.assertEqual(get_runtime("currency_kgs_to_usd_rate", 0.0), 0.0)

        # Сброс уже сброшенного — снова без записи.
        self.staff.patch(self.URL, {"currency_kgs_to_usd_rate": None}, format="json")
        self.assertEqual(self.logs("settings.edit").count(), 3)

    def test_invalid_rate_and_other_fields_write_no_log(self):
        for bad in ("abc", 0, 1.5, -0.01):
            response = self.staff.patch(self.URL, {"currency_kgs_to_usd_rate": bad},
                                        format="json")
            self.assertEqual(response.status_code, 400, response.data)
        self.staff.patch(self.URL, {"crypto_fee_paid_by_user": True}, format="json")
        self.assertFalse(self.logs("settings.edit").exists())


# ------------------------------------------------------------------ платежи

class MarkRefundedTests(AdminTestCase):
    def setUp(self):
        super().setUp()
        self.creator = f.make_creator()
        self.buyer = f.make_user()
        f.make_referral(self.creator, self.buyer)
        self.payment = f.make_payment(self.buyer)
        f.credit_purchase(self.payment)
        self.commission = f.make_commission(self.creator, self.payment, buyer=self.buyer)
        self.url = PAYMENTS + f"{self.payment.pk}/mark-refunded/"

    def test_mark_then_follow_up(self):
        response = self.su.post(self.url, {"kind": "refund", "reason": "Вернули вручную"},
                                format="json")
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(set(response.data), {"reversed", "clawback_debited", "payment"})
        self.assertEqual((response.data["reversed"], response.data["clawback_debited"]), (1, 0))
        self.assertEqual(response.data["payment"]["id"], self.payment.pk)
        self.commission.refresh_from_db()
        self.assertEqual((self.commission.status, self.commission.reason),
                         ("reversed", "refund:admin"))
        # Кредиты без явной просьбы остаются у покупателя.
        self.buyer.refresh_from_db()
        self.assertEqual(self.buyer.token_balance, 500)

        self.assertError(self.su.post(self.url, {"kind": "refund", "reason": "Ещё раз"},
                                      format="json"), 409, "already_marked")

        # Один раз можно вернуться и изъять кредиты.
        follow = self.su.post(self.url, {"kind": "refund", "reason": "Изъять кредиты",
                                         "clawback_credits": True}, format="json")
        self.assertEqual(follow.status_code, 200, follow.data)
        self.assertEqual((follow.data["reversed"], follow.data["clawback_debited"]), (0, 500))
        self.buyer.refresh_from_db()
        self.assertEqual(self.buyer.token_balance, 0)
        self.assertError(self.su.post(self.url, {"kind": "refund", "reason": "И ещё",
                                                 "clawback_credits": True}, format="json"),
                         409, "already_marked")
        self.assertEqual(self.logs("payment.mark_refunded").count(), 2)

    def test_fraud_with_clawback(self):
        response = self.su.post(self.url, {"kind": "fraud", "reason": "Чарджбэк",
                                           "clawback_credits": True}, format="json")
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual((response.data["reversed"], response.data["clawback_debited"]), (1, 500))
        self.assertFalse(response.data["payment"]["success"])
        self.commission.refresh_from_db()
        self.assertEqual((self.commission.status, self.commission.reason), ("reversed", "fraud"))
        log = self.logs("payment.mark_refunded").get()
        self.assertEqual((log.creator_id, log.after["kind"], log.after["reversed"]),
                         (self.creator.pk, "fraud", 1))

    def test_errors(self):
        self.assertError(self.su.post(self.url, {"kind": "chargeback", "reason": "r"},
                                      format="json"), 400, "kind_invalid")
        self.assertError(self.su.post(self.url, {"reason": "r"}, format="json"),
                         400, "kind_invalid")
        self.assertError(self.su.post(self.url, {"kind": "refund"}, format="json"),
                         400, "reason_required")
        self.assertError(self.su.post(PAYMENTS + "999999/mark-refunded/",
                                      {"kind": "refund", "reason": "r"}, format="json"),
                         404, "not_found")
        self.commission.refresh_from_db()
        self.assertEqual(self.commission.status, "accrued")
        self.assertFalse(self.logs("payment.mark_refunded").exists())


class RefundStarsTests(AdminTestCase):
    """Возврат Stars отменяет комиссию — значит, это решение главного администратора."""

    def setUp(self):
        super().setUp()
        self.tg_api = self.patch("botapi.stars.tg_api")
        self.buyer = f.make_user()
        self.payment = f.make_payment(self.buyer, provider="telegram_stars", amount="170",
                                      tokens=500)
        self.invoice = money.star_invoice(self.payment)
        f.credit_purchase(self.payment)
        self.url = PAYMENTS + f"{self.payment.pk}/refund-stars/"

    def test_commissioned_payment_needs_superuser(self):
        creator = f.make_creator()
        f.make_referral(creator, self.buyer)
        commission = f.make_commission(creator, self.payment, buyer=self.buyer)

        response = self.staff.post(self.url, {"reason": "просьба"}, format="json")
        self.assertEqual(response.status_code, 403, response.data)
        self.assertEqual(response.data["code"], "superuser_required")
        self.assertIsInstance(response.data["detail"], str)
        # В Telegram ничего не ушло, и в базе ничего не изменилось.
        self.tg_api.assert_not_called()
        commission.refresh_from_db()
        self.invoice.refresh_from_db()
        self.assertEqual((commission.status, self.invoice.status), ("accrued", "paid"))
        self.assertFalse(self.logs("payment.mark_refunded").exists())

        response = self.su.post(self.url, {"reason": "просьба"}, format="json")
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["payment"]["stars"]["status"], "refunded")
        self.assertEqual(self.tg_api.call_args.args[0], "refundStarPayment")
        commission.refresh_from_db()
        self.assertEqual((commission.status, commission.reason),
                         ("reversed", "refund:telegram_stars"))
        self.buyer.refresh_from_db()
        self.assertEqual(self.buyer.token_balance, 0)
        log = self.logs("payment.mark_refunded").get()
        self.assertEqual((log.actor_id, log.creator_id, log.target_id, log.reason),
                         (self.su_user.pk, creator.pk, str(self.payment.pk), "просьба"))
        self.assertEqual(log.after, {"kind": "refund", "via": "refund-stars", "reversed": 1,
                                     "result": "refunded"})

    def test_payment_without_commission_works_for_staff_as_before(self):
        response = self.staff.post(self.url, {"reason": "просьба"}, format="json")
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(set(response.data), {"result", "payment"})
        self.assertEqual(response.data["result"]["status"], "refunded")
        self.assertEqual(response.data["payment"]["stars"]["refund_reason"], "просьба")
        log = self.logs("payment.mark_refunded").get()
        self.assertEqual((log.actor_id, log.creator_id, log.after["reversed"]),
                         (self.staff_user.pk, None, 0))

    def test_unreadable_commissions_fail_closed(self):
        with patch("creators.commission.open_for_payment", side_effect=RuntimeError("boom")):
            response = self.staff.post(self.url, {"reason": "просьба"}, format="json")
        self.assertEqual(response.status_code, 403, response.data)
        self.assertEqual(response.data["code"], "superuser_required")
        self.tg_api.assert_not_called()

    def test_failed_log_row_does_not_undo_the_refund(self):
        with patch("audit.services.log_admin_action", side_effect=RuntimeError("boom")):
            response = self.su.post(self.url, {"reason": "просьба"}, format="json")
        self.assertEqual(response.status_code, 200, response.data)
        self.invoice.refresh_from_db()
        self.assertEqual(self.invoice.status, "refunded")

    def test_user_less_payment_is_reversed_too(self):
        """Платёж без пользователя общий код возврата не трогает — комиссию отменяет вьюха."""
        creator = f.make_creator()
        commission = f.make_commission(creator, self.payment, buyer=self.buyer)
        type(self.payment).objects.filter(pk=self.payment.pk).update(user=None)
        response = self.su.post(self.url, {"reason": "просьба", "force": True}, format="json")
        self.assertEqual(response.status_code, 200, response.data)
        commission.refresh_from_db()
        self.assertEqual((commission.status, commission.reason),
                         ("reversed", "refund:telegram_stars"))

    def test_not_a_stars_payment(self):
        payment = f.make_payment(self.buyer)
        response = self.staff.post(PAYMENTS + f"{payment.pk}/refund-stars/", {}, format="json")
        self.assertEqual(response.status_code, 400, response.data)
        self.assertEqual(response.data["detail"], "not_stars_payment")


class HoldDaysTests(AdminTestCase):
    def test_hold_days_setting_reaches_the_program_page(self):
        self.su.patch(M + "settings/", {"hold_days": 7}, format="json")
        self.assertEqual(self.client_for().get(api.API + "program/").data["hold_days"], 7)
        self.assertEqual(get_runtime("creators_hold_days", 14), 7)
        # Значение, записанное мимо админки, читается тем же адресом.
        set_runtime("creators_hold_days", 14)
        self.assertEqual(self.su.get(M + "settings/").data["hold_days"], 14)
