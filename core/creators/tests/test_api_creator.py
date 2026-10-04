"""Кабинет креатора: каждый адрес §8.3 — ответ, коды ошибок, права заблокированного."""
import json
from decimal import Decimal
from unittest.mock import patch

from django.test import override_settings
from django.utils import timezone

from adminapi.runtime import set_runtime
from audit.models import AdminActionLog
from plans.wallet import charge_tokens, credit_tokens
from users.models import Notification

from .. import notify
from ..models import (
    Creator,
    CreatorApplication,
    CreatorCode,
    CreatorPublication,
    CreatorReferral,
    CreatorWithdrawal,
)
from . import factories as f
from . import test_api_public as api

API = api.API


def _grant(user, amount, *, by, category="start", note="Стартовый пакет"):
    """Выдача Creator Credits строкой леджера — как её пишет credits.grant."""
    credit_tokens(user, amount, "creator_credit",
                  meta={"category": category, "note": note, "by_id": by.pk, "grant_id": "g1"})


# ------------------------------------------------------------------- заявка

class ApplicationTests(api.ApiTestCase):
    def setUp(self):
        super().setUp()
        self.user = f.make_user()
        self.client_ = self.client_for(self.user)

    def post(self, **changes):
        body = dict(api.APPLY)
        body.update(changes)
        return self.client_.post(API + "application/", body, format="json")

    def test_no_application_yet(self):
        response = self.client_.get(API + "application/")
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data, {"application": None})

    def test_submit_and_read_back(self):
        response = self.post()
        self.assertEqual(response.status_code, 201, response.data)
        row = response.data["application"]
        self.assertEqual(set(row), {
            "id", "status", "created_at", "decided_at", "reject_reason", "name", "telegram",
            "country", "instagram_url", "tiktok_url", "youtube_url", "other_links", "followers",
            "occupation", "motivation", "samples"})
        self.assertEqual(row["status"], "new")
        self.assertEqual(row["followers"], 1200)
        self.assertEqual(row["samples"], ["https://youtube.com/watch?v=abc"])
        application = CreatorApplication.objects.get(pk=row["id"])
        self.assertEqual(application.user_id, self.user.pk)
        self.assertEqual(application.lang, "en")
        # Одобрения нет: заявка — ещё не участие в программе.
        self.assertFalse(Creator.objects.filter(user=self.user).exists())

        again = self.client_.get(API + "application/")
        self.assertEqual(again.data["application"]["id"], row["id"])

    def test_latest_application_is_returned(self):
        api.make_application(self.user, status="rejected", reject_reason="Мало работ")
        newest = api.make_application(self.user, status="new")
        self.assertEqual(self.client_.get(API + "application/").data["application"]["id"],
                         newest.pk)

    def test_errors(self):
        response = self.post(name="", followers="много")
        self.assertError(response, 400, "validation")
        self.assertEqual(set(response.data["fields"]), {"name", "followers"})

        self.assertError(self.post(instagram_url=""), 400, "links_required")
        self.assertEqual(CreatorApplication.objects.count(), 0)

        self.assertEqual(self.post().status_code, 201)
        self.assertError(self.post(), 409, "application_open")
        self.assertEqual(CreatorApplication.objects.count(), 1)

    def test_already_creator(self):
        f.make_creator(self.user)
        self.assertError(self.post(), 409, "already_creator")

    def test_blocked_applicant_cannot_apply_again(self):
        api.make_application(self.user, status="blocked")
        self.assertError(self.post(), 403, "apply_blocked")

    def test_rejected_applicant_may_apply_again(self):
        api.make_application(self.user, status="rejected")
        self.assertEqual(self.post().status_code, 201)

    def test_refused_submissions_do_not_use_up_the_daily_limit(self):
        # Ошибки в форме (ссылка без https://, пустое поле) — не заявки: после
        # пяти исправлений человек всё ещё может подать заявку.
        for _ in range(4):
            self.assertError(self.post(name=""), 400, "validation")
        for _ in range(4):
            self.assertError(self.post(instagram_url="instagram.com/tora"), 400, "validation")
        self.assertError(self.post(instagram_url=""), 400, "links_required")
        response = self.post()
        self.assertEqual(response.status_code, 201, response.data)

    def test_apply_has_its_own_daily_limit_of_accepted_applications(self):
        for _ in range(5):
            self.assertEqual(self.post().status_code, 201)
            # Отклонённый может подать снова — но не бесконечно за один день.
            CreatorApplication.objects.filter(user=self.user).update(status="rejected")
        response = self.post()
        self.assertEqual(response.status_code, 429, response.data)
        self.assertEqual(response.data["code"], "throttled")
        self.assertEqual(CreatorApplication.objects.filter(user=self.user).count(), 5)
        # Чтение заявки этим лимитом не задето, и чужой лимит — тоже.
        self.assertEqual(self.client_.get(API + "application/").status_code, 200)
        other = self.client_for(f.make_user())
        self.assertEqual(other.post(API + "application/", dict(api.APPLY),
                                    format="json").status_code, 201)

    def test_refused_submissions_are_still_held_by_the_common_limit(self):
        from rest_framework.throttling import UserRateThrottle

        rates = dict(UserRateThrottle.THROTTLE_RATES, user="3/min")
        with patch.object(UserRateThrottle, "THROTTLE_RATES", rates):
            for _ in range(3):
                self.assertError(self.post(name=""), 400, "validation")
            self.assertEqual(self.post(name="").status_code, 429)

    @override_settings(CREATORS_MODE="staff")
    def test_staff_mode_only_staff_may_apply(self):
        self.assertError(self.post(), 404, "disabled")
        staff = f.make_user(staff=True)
        response = self.client_for(staff).post(API + "application/", api.APPLY, format="json")
        self.assertEqual(response.status_code, 201, response.data)


# ------------------------------------------------------------- главный экран

class MeTests(api.ApiTestCase):
    def setUp(self):
        super().setUp()
        self.creator = f.make_creator(level="creator_pro", display_name="Tora",
                                      payout_address=f.VALID_TRC20)
        self.user = self.creator.user
        self.client_ = self.client_for(self.user)

    def test_empty_cabinet(self):
        response = self.client_.get(API + "me/")
        self.assertEqual(response.status_code, 200, response.data)
        data = response.data
        self.assertEqual(set(data), {
            "creator", "level", "code", "link", "telegram_link", "counters", "money",
            "progress", "credits", "payout_address", "payout_address_changed_at",
            "open_withdrawal"})
        self.assertEqual(data["creator"], {
            "id": self.creator.pk, "status": "active", "display_name": "Tora",
            "joined_at": self.creator.created_at, "lang": "ru"})
        self.assertEqual(data["level"], {"key": "creator_pro", "title": "CREATOR PRO",
                                         "percent": "15.00"})
        # Кода ещё нет — нет и ссылок.
        self.assertIsNone(data["code"])
        self.assertIsNone(data["link"])
        self.assertIsNone(data["telegram_link"])
        self.assertEqual(data["counters"], {
            "clicks": 0, "registrations": 0, "paying": 0, "orders": 0,
            "sales_usdt": "0.00", "publications_approved": 0})
        self.assertEqual(data["money"], {
            "earned": "0.00", "pending": "0.00", "held": "0.00", "available": "0.00",
            "in_withdrawal": "0.00", "paid": "0.00", "debt": "0.00", "min_payout": "10.00",
            "can_withdraw": False, "payouts_enabled": True})
        self.assertEqual(data["credits"], {"granted": 0, "remaining": 0})
        self.assertEqual(data["payout_address"], f.VALID_TRC20)
        self.assertIsNone(data["open_withdrawal"])

    def test_held_money_hides_commissions_of_suspect_referrals(self):
        # Привязка на проверке креатору не видна ни в списках, ни в сумме
        # «придержано»; остальные удержания он видит.
        from creators import balance

        f.make_commission(self.creator, amount="4.000000", base="40.000000",
                          status="held", reason="referral_suspect")
        self.assertEqual(self.client_.get(API + "me/").data["money"]["held"], "0.00")
        f.make_commission(self.creator, amount="2.250000", base="15.000000",
                          status="held", reason="creator_blocked")
        f.make_commission(self.creator, amount="1.500000", base="10.000000",
                          status="held", reason="merge_self")
        money = self.client_.get(API + "me/").data["money"]
        self.assertEqual(money["held"], "3.75")
        self.assertEqual(money["earned"], "0.00")
        # Расчёт баланса (и профиль в админке) по-прежнему видит всё придержанное.
        self.assertEqual(balance.summary(self.creator).held, Decimal("7.750000"))

    @override_settings(TELEGRAM_PRODUCT_BOT_USERNAME="@EsAI_Bot",
                       CREATORS_LINK_BASE="https://esai.kg/")
    def test_full_cabinet(self):
        """Всё, что ТЗ п.14–15 и п.37–38 требует на первом экране."""
        CreatorCode.objects.create(code="TORA20", creator=self.creator, created_by=self.user)
        buyer, lurker, suspect = f.make_user(), f.make_user(), f.make_user()
        f.make_referral(self.creator, buyer)
        f.make_referral(self.creator, lurker)
        f.make_referral(self.creator, suspect, suspect=True)
        f.make_commission(self.creator, buyer=buyer, amount="30.000000", base="200.000000",
                          available_in_days=-1)
        f.make_commission(self.creator, buyer=buyer, amount="1.500000", base="10.000000")
        f.make_commission(self.creator, buyer=buyer, amount="9.000000", base="60.000000",
                          status="reversed")
        for n in range(3):
            CreatorPublication.objects.create(
                creator=self.creator, network="instagram", url=f"https://instagram.com/p/{n}",
                url_norm=f"instagram.com/p/{n}", status="approved" if n < 2 else "review")
        f.make_withdrawal(self.creator, "12.00")
        _grant(self.user, 1000, by=f.factory_admin())
        charge_tokens(self.user, 360, "chat")
        self.client_for().post(API + "click/", {"code": "TORA20"}, format="json",
                               HTTP_X_DEVICE_KEY="phone-1")

        data = self.client_.get(API + "me/").data
        self.assertEqual(data["code"], "TORA20")
        self.assertEqual(data["link"], "https://esai.kg/?ref=TORA20")
        self.assertEqual(data["telegram_link"], "https://t.me/EsAI_Bot?start=ref_TORA20")
        self.assertEqual(data["counters"], {
            "clicks": 1, "registrations": 2, "paying": 1, "orders": 2,
            "sales_usdt": "210.00", "publications_approved": 2})
        # Счётчик подозрительных привязок — только для админки.
        self.assertNotIn("suspect_referrals", data["counters"])
        money = data["money"]
        self.assertEqual(money["earned"], "31.50")
        self.assertEqual(money["available"], "18.00")
        self.assertEqual(money["pending"], "13.50")
        self.assertEqual(money["in_withdrawal"], "12.00")
        self.assertEqual(money["paid"], "0.00")
        # Доступно больше минимума, но заявка уже в работе.
        self.assertFalse(money["can_withdraw"])
        self.assertEqual(data["open_withdrawal"]["amount_usdt"], "12.00")
        self.assertEqual(data["open_withdrawal"]["status"], "review")
        self.assertEqual(data["credits"], {"granted": 1000, "remaining": 640})

        progress = data["progress"]
        self.assertEqual(progress["next_level"],
                         {"key": "ambassador", "title": "AMBASSADOR", "percent": "20.00"})
        self.assertEqual(progress["publications"], {"have": 2, "need": 25, "done": False})
        self.assertEqual(progress["registrations"], {"have": 2, "need": 100, "done": False})
        self.assertEqual(progress["paying"], {"have": 1, "need": 30, "done": False})
        self.assertFalse(progress["conditions_met"])
        self.assertFalse(progress["awaiting_confirmation"])
        # Ответ целиком сериализуется (даты, Decimal) и не содержит чужой почты.
        raw = json.dumps(self.client_.get(API + "me/").json())
        self.assertNotIn(buyer.email, raw)

    def test_can_withdraw_and_conditions_met(self):
        f.make_commission(self.creator, amount="15.000000", base="100.000000",
                          available_in_days=-1)
        type(self.creator.level).objects.filter(key="ambassador").update(
            min_publications=0, min_registrations=0, min_paying=1)
        data = self.client_.get(API + "me/").data
        self.assertTrue(data["money"]["can_withdraw"])
        self.assertTrue(data["progress"]["conditions_met"])
        self.assertTrue(data["progress"]["awaiting_confirmation"])
        # Уровень сам не меняется: решение за администратором.
        self.assertEqual(data["level"]["key"], "creator_pro")

        set_runtime("creators_payouts_enabled", False)
        data = self.client_.get(API + "me/").data
        self.assertFalse(data["money"]["payouts_enabled"])
        self.assertFalse(data["money"]["can_withdraw"])

    def test_open_withdrawal_of_another_creator_is_not_shown(self):
        other = f.make_creator(payout_address=f.VALID_TRC20_2)
        f.make_withdrawal(other, "30.00", status="review")
        f.make_commission(self.creator, amount="50.000000", base="500.000000",
                          available_in_days=-1)
        data = self.client_.get(API + "me/").data
        self.assertIsNone(data["open_withdrawal"])
        # Чужая открытая заявка не мешает выводу этого креатора.
        self.assertTrue(data["money"]["can_withdraw"])
        own = f.make_withdrawal(self.creator, "10.00", status="approved")
        data = self.client_.get(API + "me/").data
        self.assertEqual(data["open_withdrawal"]["id"], own.pk)
        self.assertFalse(data["money"]["can_withdraw"])

    def test_top_level_has_no_next(self):
        top = f.make_creator(level="ambassador_pro")
        progress = self.client_for(top.user).get(API + "me/").data["progress"]
        self.assertIsNone(progress["next_level"])
        self.assertFalse(progress["conditions_met"])

    def test_patch_lang_and_next_notification_uses_it(self):
        response = self.client_.patch(API + "me/", {"lang": "en"}, format="json")
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data, {"lang": "en"})
        self.creator.refresh_from_db()
        self.assertEqual(self.creator.lang, "en")
        # Свой выбор языка — не действие администратора.
        self.assertFalse(AdminActionLog.objects.filter(creator=self.creator)
                         .exclude(action="application.approve").exists())

        with self.captureOnCommitCallbacks(execute=True):
            notify.emit(self.creator, "payout_approved", amount_usdt="48.50")
        note = Notification.objects.latest("id")
        self.assertEqual(note.title, "Payout approved")
        self.assertIn("48.50", note.body)
        self.assertEqual(self.client_.get(API + "me/").data["creator"]["lang"], "en")

    def test_patch_lang_validation(self):
        for bad in ("de", "", None, ["en"]):
            response = self.client_.patch(API + "me/", {"lang": bad}, format="json")
            self.assertError(response, 400, "validation")
            self.assertIn("lang", response.data["fields"])
        self.creator.refresh_from_db()
        self.assertEqual(self.creator.lang, "ru")


# ---------------------------------------------------------------------- код

class CodeTests(api.ApiTestCase):
    def setUp(self):
        super().setUp()
        self.creator = f.make_creator()
        self.client_ = self.client_for(self.creator.user)

    def check(self, code):
        return self.client_.get(API + "code/check/", {"code": code})

    def create(self, code, creator=None):
        client = self.client_for(creator.user) if creator else self.client_
        return client.post(API + "me/code/", {"code": code}, format="json")

    def test_check_available(self):
        response = self.check(" tora20 ")
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data, {"code": "TORA20", "available": True})

    def test_check_reasons(self):
        f.make_creator(code="TAKEN01")
        rival = f.make_user(referral_uid="UserUid9")
        cases = {"ab": "code_format", "1ABCD": "code_format", "TO-RA": "code_format", "": "code_format",
                 "ADMIN": "code_reserved", "ESAIPROMO": "code_reserved",
                 "taken01": "code_taken", rival.referral_uid.upper(): "code_taken"}
        for code, reason in cases.items():
            response = self.check(code)
            self.assertEqual(response.status_code, 200, response.data)
            self.assertEqual(response.data, {"code": code.strip().upper(), "available": False,
                                             "reason": reason}, code)

    @override_settings(TELEGRAM_PRODUCT_BOT_USERNAME="EsAI_Bot")
    def test_create_code_once(self):
        response = self.create("tora20")
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(response.data, {
            "code": "TORA20", "link": "https://esai.kg/?ref=TORA20",
            "telegram_link": "https://t.me/EsAI_Bot?start=ref_TORA20"})
        row = CreatorCode.objects.get(code="TORA20")
        self.assertEqual(row.creator_id, self.creator.pk)
        self.assertTrue(row.is_primary)
        # Свой код креатор задал сам — в журнал администратора это не идёт.
        self.assertFalse(AdminActionLog.objects.filter(action="creator.code_set").exists())

        # Изменить сам уже не может.
        self.assertError(self.create("OTHER01"), 409, "code_already_set")
        self.assertEqual(CreatorCode.objects.filter(creator=self.creator).count(), 1)

    def test_create_code_errors(self):
        f.make_creator(code="TAKEN01")
        self.assertError(self.create("ab"), 400, "code_format")
        self.assertError(self.create("SUPPORT"), 400, "code_reserved")
        response = self.create("taken01")
        self.assertError(response, 409, "code_taken")
        self.assertEqual(response.data["taken_by"], "creator_code")
        self.assertError(self.create(None), 400, "code_format")
        self.assertFalse(CreatorCode.objects.filter(creator=self.creator).exists())

    def test_create_code_taken_by_a_referral_uid_or_a_promo_code(self):
        # Код креатора ищется раньше реф-кода пользователя: совпади они, чужая
        # ссылка ?ref= начала бы привязывать людей к креатору.
        from plans.models import PromoCode

        f.make_user(referral_uid="UserUid9")
        PromoCode.objects.create(code="WELCOME5", bonus_credits=5)
        for code, taken_by in (("useruid9", "referral_uid"), ("USERUID9", "referral_uid"),
                               ("welcome5", "promo_code")):
            response = self.create(code)
            self.assertError(response, 409, "code_taken")
            self.assertEqual(response.data["taken_by"], taken_by, code)
        self.assertFalse(CreatorCode.objects.exists())


# --------------------------------------------------------------- публикации

class PublicationTests(api.ApiTestCase):
    def setUp(self):
        super().setUp()
        self.creator = f.make_creator()
        self.client_ = self.client_for(self.creator.user)

    def post(self, **body):
        return self.client_.post(API + "me/publications/", body, format="json")

    def test_add_and_list(self):
        response = self.post(network="instagram", url="https://www.instagram.com/p/abc/?igshid=1",
                             description="Ролик про EsAI")
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(set(response.data), {"id", "network", "url", "description", "status",
                                              "created_at", "decided_at", "reject_reason"})
        self.assertEqual(response.data["status"], "review")
        self.assertEqual(response.data["description"], "Ролик про EsAI")

        CreatorPublication.objects.create(creator=self.creator, network="tiktok",
                                          url="https://tiktok.com/@a/video/1",
                                          url_norm="tiktok.com/@a/video/1", status="approved")
        # Чужие публикации в списке не видны.
        CreatorPublication.objects.create(creator=f.make_creator(), network="tiktok",
                                          url="https://tiktok.com/@b/video/2",
                                          url_norm="tiktok.com/@b/video/2")
        listing = self.client_.get(API + "me/publications/")
        self.assertEqual(listing.status_code, 200, listing.data)
        self.assertEqual(listing.data["count"], 2)
        self.assertEqual(len(listing.data["results"]), 2)
        approved = self.client_.get(API + "me/publications/", {"status": "approved"})
        self.assertEqual(approved.data["count"], 1)
        self.assertEqual(approved.data["results"][0]["network"], "tiktok")
        self.assertEqual(self.client_.get(API + "me/publications/", {"page": 2}).data,
                         {"count": 2, "results": []})

    def test_errors(self):
        self.assertError(self.post(network="myspace", url="https://example.com/p/1"),
                         400, "network_invalid")
        self.assertError(self.post(network="instagram", url="instagram.com/p/1"),
                         400, "url_invalid")
        self.assertError(self.post(network="instagram"), 400, "url_invalid")
        self.assertEqual(self.post(network="instagram",
                                   url="https://instagram.com/p/1").status_code, 201)
        self.assertError(self.post(network="instagram", url="https://www.instagram.com/p/1/"),
                         409, "publication_duplicate")
        # Один пост засчитывается одному креатору.
        other = self.client_for(f.make_creator().user)
        self.assertError(other.post(API + "me/publications/",
                                    {"network": "instagram", "url": "https://instagram.com/p/1"},
                                    format="json"), 409, "publication_duplicate")
        self.assertEqual(CreatorPublication.objects.count(), 1)


# ------------------------------------------------------------------ кредиты

class CreditsTests(api.ApiTestCase):
    def setUp(self):
        super().setUp()
        self.creator = f.make_creator()
        self.user = self.creator.user
        self.client_ = self.client_for(self.user)
        self.admin = f.factory_admin()

    def test_no_grants(self):
        response = self.client_.get(API + "me/credits/")
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data, {"granted": 0, "remaining": 0, "spent": 0,
                                         "count": 0, "results": []})

    def test_history_has_no_admin_identity(self):
        _grant(self.user, 100, by=self.admin, category="content", note="За ролик")
        charge_tokens(self.user, 30, "chat")
        response = self.client_.get(API + "me/credits/")
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["granted"], 100)
        self.assertEqual(response.data["remaining"], 70)
        self.assertEqual(response.data["spent"], 30)
        self.assertEqual(response.data["count"], 1)
        row = response.data["results"][0]
        self.assertEqual(set(row), {"id", "date", "amount", "category", "category_label", "note"})
        self.assertEqual((row["amount"], row["category"], row["category_label"], row["note"]),
                         (100, "content", "За контент", "За ролик"))
        raw = json.dumps(response.json())
        self.assertNotIn(self.admin.email, raw)
        self.assertNotIn("by_id", raw)
        self.assertNotIn("grant_id", raw)

    def test_full_history_has_grants_and_spends(self):
        _grant(self.user, 100, by=self.admin)
        charge_tokens(self.user, 30, "chat")
        charge_tokens(self.user, 20, "video")
        response = self.client_.get(API + "me/credits/", {"full": 1})
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["remaining"], 50)
        self.assertEqual(response.data["spent"], 50)
        rows = response.data["results"]
        self.assertEqual(response.data["count"], 3)
        self.assertEqual([row["kind"] for row in rows], ["spend", "spend", "grant"])
        self.assertEqual([row["amount"] for row in rows], [-20, -30, 100])
        self.assertEqual([row["remaining_after"] for row in rows], [50, 70, 100])
        self.assertEqual(set(rows[0]), {"id", "date", "amount", "kind", "reason", "reason_label",
                                        "remaining_after"})
        self.assertEqual(rows[0]["reason"], "video")
        self.assertNotIn("by_id", json.dumps(response.json()))


# ----------------------------------------------------------------- комиссии

class CommissionListTests(api.ApiTestCase):
    def setUp(self):
        super().setUp()
        self.creator = f.make_creator()
        self.client_ = self.client_for(self.creator.user)

    def test_rows_mask_the_buyer(self):
        buyer = f.make_user(email="longbuyer@example.com")
        f.make_referral(self.creator, buyer)
        accrued = f.make_commission(self.creator, buyer=buyer, amount="1.234567",
                                    base="12.345678")
        f.make_commission(self.creator, buyer=buyer, status="held", reason="creator_blocked")
        f.make_commission(f.make_creator(), amount="5.000000")

        response = self.client_.get(API + "me/commissions/")
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["count"], 2)
        row = next(r for r in response.data["results"] if r["id"] == accrued.pk)
        self.assertEqual(set(row), {"id", "date", "buyer", "provider", "base_usdt", "percent",
                                    "amount_usdt", "status", "reason", "available_at"})
        self.assertEqual(row["amount_usdt"], "1.234567")
        self.assertEqual(row["base_usdt"], "12.34")
        self.assertEqual(row["percent"], "10.00")
        self.assertEqual(row["provider"], "freedompay")
        self.assertEqual(row["buyer"], "l*******r@example.com")
        raw = json.dumps(response.json())
        self.assertNotIn(buyer.email, raw)
        self.assertNotIn("buyer_pk", raw)

        held = self.client_.get(API + "me/commissions/", {"status": "held"})
        self.assertEqual(held.data["count"], 1)
        self.assertEqual(held.data["results"][0]["reason"], "review")

    def test_antifraud_and_staff_signals_are_not_shown(self):
        """Кабинет не выдаёт ни пометку «на проверке», ни то, что покупатель — сотрудник."""
        suspect = f.make_user(email="multiacc@example.com")
        f.make_referral(self.creator, suspect, suspect=True)
        f.make_commission(self.creator, buyer=suspect, status="held", reason="referral_suspect")
        staff_buyer = f.make_user(email="staffbuyer@example.com")
        for reason in ("buyer_staff", "buyer_unlimited", "test_payment", "self_purchase"):
            f.make_commission(self.creator, buyer=staff_buyer, status="void", reason=reason,
                              amount="0", base="10.000000")

        for params in ({}, {"status": "held"}, {"status": "void"}):
            response = self.client_.get(API + "me/commissions/", params)
            self.assertEqual(response.status_code, 200, response.data)
            self.assertEqual(response.data, {"count": 0, "results": []}, params)

    def test_reasons_are_reduced_to_a_public_vocabulary(self):
        buyer = f.make_user()
        cases = (
            ("accrued", "", ""),
            ("accrued", "released", ""),
            ("accrued", "restored", ""),
            ("held", "creator_blocked", "review"),
            ("held", "merge_self", "review"),
            ("reversed", "refund:freedompay", "refund"),
            ("reversed", "refund:admin", "refund"),
            ("reversed", "fraud", "cancelled"),
            ("void", "admin_void", "cancelled"),
        )
        expected = {}
        for status, reason, public in cases:
            row = f.make_commission(self.creator, buyer=buyer, status=status, reason=reason)
            expected[row.pk] = (status, public)
        response = self.client_.get(API + "me/commissions/")
        self.assertEqual(response.data["count"], len(cases))
        shown = {row["id"]: (row["status"], row["reason"]) for row in response.data["results"]}
        self.assertEqual(shown, expected)
        raw = json.dumps(response.json())
        for secret in ("fraud", "merge_self", "creator_blocked", "admin_void", "refund:",
                       "released", "restored"):
            self.assertNotIn(f'"reason": "{secret}', raw)

    def test_page_far_beyond_the_end_is_empty_not_an_error(self):
        f.make_commission(self.creator)
        for path in ("me/commissions/", "me/publications/", "me/referrals/", "me/withdrawals/"):
            for page in ("99999999999999999999", str(10 ** 40), "2"):
                response = self.client_.get(API + path, {"page": page})
                self.assertEqual(response.status_code, 200, (path, page))
                self.assertEqual(response.data["results"], [], (path, page))
        response = self.client_.get(API + "me/commissions/", {"page": "99999999999999999999"})
        self.assertEqual(response.data["count"], 1)
        # Мусор и ноль — первая страница, как раньше.
        for page in ("abc", "0", "-5"):
            self.assertEqual(len(self.client_.get(API + "me/commissions/",
                                                  {"page": page}).data["results"]), 1)


# ----------------------------------------------------------------- рефералы

class ReferralListTests(api.ApiTestCase):
    def setUp(self):
        super().setUp()
        self.creator = f.make_creator(code="TORA20")
        self.client_ = self.client_for(self.creator.user)

    def test_rows_have_no_id_or_email_of_the_user(self):
        buyer = f.make_user(email="payinguser@example.com", username="payer")
        quiet = f.make_user(email="quietuser@example.com")
        paying = f.make_referral(self.creator, buyer)
        f.make_referral(self.creator, quiet, source="promo")
        f.make_commission(self.creator, buyer=buyer, amount="1.500000", base="10.000000")
        f.make_commission(self.creator, buyer=buyer, amount="3.000000", base="20.004000",
                          status="held", reason="creator_blocked")
        f.make_commission(self.creator, buyer=buyer, amount="9.000000", base="60.000000",
                          status="reversed")

        response = self.client_.get(API + "me/referrals/")
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["count"], 2)
        row = next(r for r in response.data["results"] if r["id"] == paying.pk)
        self.assertEqual(set(row), {"id", "user", "bound_at", "source", "is_paying", "orders",
                                    "sales_usdt", "commission_usdt"})
        self.assertEqual(row["user"], "@payer")
        self.assertTrue(row["is_paying"])
        self.assertEqual(row["orders"], 2)
        self.assertEqual(row["sales_usdt"], "30.00")
        # В «заработано» — только начисленное; придержанное и отменённое — нет.
        self.assertEqual(row["commission_usdt"], "1.50")
        other = next(r for r in response.data["results"] if r["id"] != paying.pk)
        self.assertEqual((other["is_paying"], other["orders"], other["sales_usdt"],
                          other["commission_usdt"], other["source"]),
                         (False, 0, "0.00", "0.00", "promo"))
        self.assertEqual(other["user"], "q*******r@example.com")

        raw = json.dumps(response.json())
        for secret in (buyer.email, quiet.email, "user_id", "email"):
            self.assertNotIn(secret, raw)

    def test_list_matches_the_registrations_counter(self):
        f.make_referral(self.creator, f.make_user())
        f.make_referral(self.creator, f.make_user(), suspect=True)
        f.make_referral(self.creator, f.make_user(is_active=False))
        ended = f.make_referral(self.creator, f.make_user())
        CreatorReferral.objects.filter(pk=ended.pk).update(ended_at=timezone.now(),
                                                           end_reason="admin_unbind")
        f.make_referral(f.make_creator(), f.make_user())

        response = self.client_.get(API + "me/referrals/")
        self.assertEqual(response.data["count"], 1)
        me = self.client_.get(API + "me/").data
        self.assertEqual(me["counters"]["registrations"], response.data["count"])


# ------------------------------------------------------------------- выводы

class WithdrawalTests(api.ApiTestCase):
    def setUp(self):
        super().setUp()
        self.creator = f.make_creator()
        self.client_ = self.client_for(self.creator.user)
        f.make_commission(self.creator, amount="48.500000", base="485.000000",
                          available_in_days=-1)

    def post(self, **body):
        return self.client_.post(API + "me/withdrawals/", body, format="json")

    def test_request_and_history(self):
        response = self.post(amount="25.50", address=f.VALID_TRC20)
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(set(response.data), {
            "id", "created_at", "amount_usdt", "address", "network", "status", "txid",
            "reject_reason", "approved_at", "paid_at"})
        self.assertEqual(response.data["amount_usdt"], "25.50")
        self.assertEqual(response.data["address"], f.VALID_TRC20)
        self.assertEqual(response.data["network"], "TRC20")
        self.assertEqual(response.data["status"], "review")
        self.assertEqual(response.data["txid"], "")
        # Адрес из заявки запомнен в профиле (и это попало в журнал).
        self.creator.refresh_from_db()
        self.assertEqual(self.creator.payout_address, f.VALID_TRC20)
        self.assertTrue(AdminActionLog.objects.filter(
            action="creator.payout_address_change", actor=self.creator.user).exists())

        listing = self.client_.get(API + "me/withdrawals/")
        self.assertEqual(listing.status_code, 200, listing.data)
        self.assertEqual(listing.data["count"], 1)
        self.assertEqual(listing.data["results"][0]["id"], response.data["id"])
        me = self.client_.get(API + "me/").data
        self.assertEqual(me["money"]["in_withdrawal"], "25.50")
        self.assertEqual(me["money"]["available"], "23.00")

    def test_history_shows_only_own_withdrawals(self):
        other = f.make_creator(payout_address=f.VALID_TRC20_2)
        f.make_withdrawal(other, "77.00", status="paid", txid="b" * 64)
        f.make_withdrawal(other, "33.00", status="review")
        self.assertEqual(self.client_.get(API + "me/withdrawals/").data,
                         {"count": 0, "results": []})
        own = f.make_withdrawal(self.creator, "10.00", status="paid", txid=f.VALID_TXID)
        listing = self.client_.get(API + "me/withdrawals/")
        self.assertEqual(listing.data["count"], 1)
        self.assertEqual([row["id"] for row in listing.data["results"]], [own.pk])
        raw = json.dumps(listing.json())
        # Ни адреса, ни суммы, ни TXID чужих выплат.
        for secret in (f.VALID_TRC20_2, "77.00", "33.00", "b" * 64):
            self.assertNotIn(secret, raw)

    def test_number_amount_and_saved_address(self):
        Creator.objects.filter(pk=self.creator.pk).update(payout_address=f.VALID_TRC20_2)
        response = self.post(amount=10)
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(response.data["amount_usdt"], "10.00")
        self.assertEqual(response.data["address"], f.VALID_TRC20_2)

    def test_paid_row_shows_txid(self):
        paid = f.make_withdrawal(self.creator, "10.00", status="paid", txid=f.VALID_TXID)
        row = self.client_.get(API + "me/withdrawals/").data["results"][0]
        self.assertEqual(row["id"], paid.pk)
        self.assertEqual(row["status"], "paid")
        self.assertEqual(row["txid"], f.VALID_TXID)
        self.assertIsNotNone(row["paid_at"])

    def test_errors(self):
        self.assertError(self.post(amount="25"), 400, "address_required")
        self.assertError(self.post(amount="25", address="T123"), 400, "address_invalid")
        for bad in ("abc", "", None, "10.555", "-5", 0):
            self.assertError(self.post(amount=bad, address=f.VALID_TRC20), 400, "amount_invalid")
        self.assertError(self.post(amount="9.99", address=f.VALID_TRC20), 400, "amount_below_min")
        response = self.post(amount="48.51", address=f.VALID_TRC20)
        self.assertError(response, 400, "insufficient_available")
        self.assertEqual(response.data["available"], "48.50")
        self.assertEqual(CreatorWithdrawal.objects.count(), 0)
        # Отказ ничего не оставил после себя — даже адреса.
        self.creator.refresh_from_db()
        self.assertEqual(self.creator.payout_address, "")

        self.assertEqual(self.post(amount="10.00", address=f.VALID_TRC20).status_code, 201)
        self.assertError(self.post(amount="10.00", address=f.VALID_TRC20), 409, "withdrawal_open")
        self.assertEqual(CreatorWithdrawal.objects.count(), 1)

    def test_payouts_switched_off(self):
        set_runtime("creators_payouts_enabled", False)
        self.assertError(self.post(amount="10.00", address=f.VALID_TRC20), 403, "payouts_disabled")

    def test_payout_address(self):
        response = self.client_.put(API + "me/payout-address/", {"address": f.VALID_TRC20},
                                    format="json")
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(set(response.data), {"payout_address", "payout_address_changed_at"})
        self.assertEqual(response.data["payout_address"], f.VALID_TRC20)
        self.assertIsNotNone(response.data["payout_address_changed_at"])
        self.assertEqual(self.client_.get(API + "me/").data["payout_address"], f.VALID_TRC20)

        for bad in ("", None, "0x52908400098527886E0F7030069857D2E4169EE7", "T" * 34):
            self.assertError(self.client_.put(API + "me/payout-address/", {"address": bad},
                                              format="json"), 400, "address_invalid")
        self.creator.refresh_from_db()
        self.assertEqual(self.creator.payout_address, f.VALID_TRC20)


# ------------------------------------------------- заблокированный креатор

class BlockedCreatorTests(api.ApiTestCase):
    """Заблокированный креатор видит кабинет, но ничего не может изменить."""

    def setUp(self):
        super().setUp()
        self.creator = f.make_creator(status="blocked", code="BLOCK01",
                                      payout_address=f.VALID_TRC20)
        f.make_commission(self.creator, amount="50.000000", base="500.000000",
                          available_in_days=-1)
        self.client_ = self.client_for(self.creator.user)

    def test_reads_work(self):
        for path in ("me/", "me/publications/", "me/credits/", "me/commissions/",
                     "me/referrals/", "me/withdrawals/"):
            response = self.client_.get(API + path)
            self.assertEqual(response.status_code, 200, (path, response.data))
        me = self.client_.get(API + "me/").data
        self.assertEqual(me["creator"]["status"], "blocked")
        self.assertEqual(me["money"]["available"], "50.00")
        self.assertFalse(me["money"]["can_withdraw"])

    def test_writes_are_refused(self):
        calls = [
            ("patch", "me/", {"lang": "en"}),
            ("post", "me/code/", {"code": "NEWCODE1"}),
            ("post", "me/publications/", {"network": "instagram",
                                          "url": "https://instagram.com/p/1"}),
            ("post", "me/withdrawals/", {"amount": "10.00", "address": f.VALID_TRC20}),
            ("put", "me/payout-address/", {"address": f.VALID_TRC20_2}),
        ]
        for method, path, body in calls:
            response = getattr(self.client_, method)(API + path, body, format="json")
            self.assertError(response, 403, "creator_blocked")
        self.assertError(self.client_.get(API + "code/check/", {"code": "NEWCODE1"}),
                         403, "creator_blocked")
        self.creator.refresh_from_db()
        self.assertEqual((self.creator.lang, self.creator.payout_address),
                         ("ru", f.VALID_TRC20))
        self.assertEqual(CreatorPublication.objects.count(), 0)
        self.assertEqual(CreatorWithdrawal.objects.count(), 0)


class PrecisionTests(api.ApiTestCase):
    def test_money_is_rounded_down(self):
        creator = f.make_creator()
        f.make_commission(creator, amount="10.999999", base="109.999999", available_in_days=-1)
        data = self.client_for(creator.user).get(API + "me/").data
        self.assertEqual(data["money"]["earned"], "10.99")
        self.assertEqual(data["money"]["available"], "10.99")
        self.assertEqual(data["counters"]["sales_usdt"], "109.99")
        self.assertEqual(Decimal(data["money"]["earned"]), Decimal("10.99"))
