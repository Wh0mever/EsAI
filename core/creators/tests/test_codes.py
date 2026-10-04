"""Промокоды креаторов: формат, общее пространство имён, создание и замена.

Главное здесь — что одна строка никогда не ведёт к двум людям: код креатора
не совпадает ни с реферальным UID, ни с обычным промокодом (проверки в обе
стороны), а старый код после замены остаётся за тем же креатором навсегда.
"""
from unittest import mock

from django.contrib.auth import get_user_model
from django.db import IntegrityError
from django.test import override_settings

from adminapi.serializers import PromoCodeAdminSerializer
from audit.models import AdminActionLog
from plans.models import PromoCode

from .. import attribution, codes
from ..errors import CreatorsError
from ..models import CreatorCode
from . import factories as f


class FormatTests(f.CreatorsTestCase):
    def assertCode(self, code, error):
        with self.assertRaises(CreatorsError) as ctx:
            codes.validate_format(code)
        self.assertEqual(ctx.exception.code, error, code)

    def test_normalize(self):
        self.assertEqual(codes.normalize("  tora20 "), "TORA20")
        self.assertEqual(codes.normalize(None), "")
        self.assertEqual(codes.normalize(12345), "12345")

    def test_valid_codes(self):
        for code in ("TORA", "TORA20", "A123", "A" * 16, "Z9Z9Z9"):
            codes.validate_format(code)

    def test_bad_format(self):
        for code in ("", "TOR", "A" * 17, "1TORA", "tora20", "TORA-20", "TORA 20", "TORA_20",
                     "ТОРА20", "TORA.20", "TORA20!"):
            self.assertCode(code, "code_format")

    def test_reserved_words(self):
        for code in ("ADMIN", "SUPPORT", "PROMO", "FREE", "USDT", "TRC20", "TELEGRAM", "CREATOR"):
            self.assertCode(code, "code_reserved")

    def test_esai_prefix_is_reserved(self):
        for code in ("ESAI", "ESAI2026", "ESAIBONUS"):
            self.assertCode(code, "code_reserved")
        # Слово внутри кода никому не мешает.
        codes.validate_format("MYESAI")
        codes.validate_format("ADMIN1")


class NamespaceTests(f.CreatorsTestCase):
    def test_free_code(self):
        self.assertEqual(codes.taken_by("TORA20"), "")
        codes.check_available("TORA20")

    def test_taken_by_creator_code(self):
        f.make_creator(code="TORA20")
        self.assertEqual(codes.taken_by("TORA20"), "creator_code")
        with self.assertRaises(CreatorsError) as ctx:
            codes.check_available("TORA20")
        self.assertEqual(ctx.exception.code, "code_taken")
        self.assertEqual(ctx.exception.http, 409)
        self.assertEqual(ctx.exception.extra, {"taken_by": "creator_code"})

    def test_retired_creator_code_is_still_taken(self):
        creator = f.make_creator(code="TORA20")
        CreatorCode.objects.filter(creator=creator).update(is_active=False, is_primary=False)
        self.assertEqual(codes.taken_by("TORA20"), "creator_code")
        self.assertTrue(codes.creator_code_exists("tora20"))

    def test_taken_by_referral_uid_case_insensitive(self):
        user = f.make_user()
        get_user_model().objects.filter(pk=user.pk).update(referral_uid="Tora20")
        self.assertEqual(codes.taken_by("TORA20"), "referral_uid")
        with self.assertRaises(CreatorsError) as ctx:
            codes.check_available("TORA20")
        self.assertEqual(ctx.exception.extra, {"taken_by": "referral_uid"})

    def test_taken_by_promo_code_case_insensitive(self):
        PromoCode.objects.create(code="tora20", bonus_credits=10)
        self.assertEqual(codes.taken_by("TORA20"), "promo_code")
        with self.assertRaises(CreatorsError) as ctx:
            codes.check_available("TORA20")
        self.assertEqual(ctx.exception.extra, {"taken_by": "promo_code"})

    def test_creator_code_exists(self):
        f.make_creator(code="TORA20")
        self.assertTrue(codes.creator_code_exists("TORA20"))
        self.assertTrue(codes.creator_code_exists(" tora20 "))
        self.assertFalse(codes.creator_code_exists("OTHER1"))
        self.assertFalse(codes.creator_code_exists(""))
        self.assertFalse(codes.creator_code_exists(None))

    def test_creator_code_exists_never_raises(self):
        with mock.patch.object(CreatorCode.objects, "filter", side_effect=RuntimeError("db")):
            self.assertFalse(codes.creator_code_exists("TORA20"))


class LinkTests(f.CreatorsTestCase):
    def test_primary_code(self):
        creator = f.make_creator()
        self.assertEqual(codes.primary_code(creator), "")
        CreatorCode.objects.create(code="TORA20", creator=creator)
        self.assertEqual(codes.primary_code(creator), "TORA20")

    @override_settings(CREATORS_LINK_BASE="https://esai.kg/", TELEGRAM_PRODUCT_BOT_USERNAME="@esai_bot")
    def test_links(self):
        self.assertEqual(codes.link_for("TORA20"), "https://esai.kg/?ref=TORA20")
        self.assertEqual(codes.telegram_link_for("TORA20"), "https://t.me/esai_bot?start=ref_TORA20")

    @override_settings(TELEGRAM_PRODUCT_BOT_USERNAME="")
    def test_telegram_link_without_bot(self):
        self.assertEqual(codes.telegram_link_for("TORA20"), "")


class CreateCodeTests(f.CreatorsTestCase):
    def test_creator_creates_code_once(self):
        creator = f.make_creator()
        logs = AdminActionLog.objects.count()
        row = codes.create_code(creator, " tora20 ")
        self.assertEqual(row.code, "TORA20")
        self.assertTrue(row.is_primary and row.is_active)
        self.assertEqual(row.created_by_id, creator.user_id)
        self.assertEqual(codes.primary_code(creator), "TORA20")
        # Собственный код креатора — не действие администратора.
        self.assertEqual(AdminActionLog.objects.count(), logs)
        with self.assertRaises(CreatorsError) as ctx:
            codes.create_code(creator, "OTHER1")
        self.assertEqual(ctx.exception.code, "code_already_set")
        self.assertEqual(CreatorCode.objects.filter(creator=creator).count(), 1)

    def test_format_and_reserved_and_taken(self):
        creator = f.make_creator()
        f.make_creator(code="TAKEN1")
        for raw, error in (("ab", "code_format"), ("1abcd", "code_format"), ("admin", "code_reserved"),
                           ("esaifan", "code_reserved"), ("taken1", "code_taken")):
            with self.assertRaises(CreatorsError) as ctx:
                codes.create_code(creator, raw)
            self.assertEqual(ctx.exception.code, error, raw)
        self.assertFalse(CreatorCode.objects.filter(creator=creator).exists())

    def test_code_of_another_namespace_is_taken(self):
        # Реф-код пользователя и обычный промокод делят пространство имён с
        # кодами креаторов. Уникальный индекс CreatorCode такого совпадения не
        # ловит — только проверка занятости в create_code.
        creator = f.make_creator()
        f.make_user(referral_uid="UserUid9")
        PromoCode.objects.create(code="WELCOME5", bonus_credits=5)
        for raw, taken_by in (("useruid9", "referral_uid"), ("USERUID9", "referral_uid"),
                              ("welcome5", "promo_code"), ("WELCOME5", "promo_code")):
            with self.assertRaises(CreatorsError) as ctx:
                codes.create_code(creator, raw)
            self.assertEqual(ctx.exception.code, "code_taken", raw)
            self.assertEqual(ctx.exception.http, 409)
            self.assertEqual(ctx.exception.extra, {"taken_by": taken_by}, raw)
        self.assertFalse(CreatorCode.objects.exists())
        # Ссылка друга по-прежнему ведёт к пользователю, а не к креатору.
        kind, _ = attribution.resolve_code("UserUid9")
        self.assertEqual(kind, "user")

    def test_blocked_creator(self):
        creator = f.make_creator(status="blocked")
        with self.assertRaises(CreatorsError) as ctx:
            codes.create_code(creator, "TORA20")
        self.assertEqual(ctx.exception.code, "creator_blocked")

    def test_admin_sets_first_code_with_log(self):
        creator = f.make_creator()
        admin = f.make_user(superuser=True)
        row = codes.create_code(creator, "TORA20", actor=admin)
        self.assertEqual(row.created_by_id, admin.pk)
        log = AdminActionLog.objects.get(action="creator.code_set")
        self.assertEqual(log.actor_id, admin.pk)
        self.assertEqual(log.creator_id, creator.pk)
        self.assertEqual(log.after, {"code": "TORA20"})

    def test_lost_race_is_code_taken(self):
        creator = f.make_creator()
        # Проверка занятости прошла, а вставку опередил другой креатор.
        with mock.patch.object(CreatorCode.objects, "create", side_effect=IntegrityError("dup")):
            with self.assertRaises(CreatorsError) as ctx:
                codes.create_code(creator, "TORA20")
        self.assertEqual(ctx.exception.code, "code_taken")


class ChangeCodeTests(f.CreatorsTestCase):
    def setUp(self):
        super().setUp()
        self.admin = f.make_user(superuser=True)
        self.creator = f.make_creator(code="TORA20")

    def test_reason_required(self):
        with self.assertRaises(CreatorsError) as ctx:
            codes.change_code(self.creator, "TORA21", actor=self.admin, reason="  ")
        self.assertEqual(ctx.exception.code, "reason_required")

    def test_old_code_stays_as_resolving_alias(self):
        row = codes.change_code(self.creator, "tora21", actor=self.admin, reason="опечатка")
        self.assertEqual(row.code, "TORA21")
        self.assertEqual(codes.primary_code(self.creator), "TORA21")
        old = CreatorCode.objects.get(code="TORA20")
        self.assertFalse(old.is_primary)
        self.assertTrue(old.is_active)
        # Старые ссылки в соцсетях продолжают вести к тому же креатору.
        self.assertEqual(attribution.creator_code("TORA20").creator_id, self.creator.pk)
        self.assertEqual(attribution.creator_code("TORA21").creator_id, self.creator.pk)
        log = AdminActionLog.objects.get(action="creator.code_change")
        self.assertEqual(log.actor_id, self.admin.pk)
        self.assertEqual(log.creator_id, self.creator.pk)
        self.assertEqual(log.before, {"code": "TORA20"})
        self.assertEqual(log.after, {"code": "TORA21"})
        self.assertEqual(log.reason, "опечатка")

    def test_old_code_is_never_reissued(self):
        codes.change_code(self.creator, "TORA21", actor=self.admin, reason="r")
        other = f.make_creator()
        with self.assertRaises(CreatorsError) as ctx:
            codes.create_code(other, "TORA20")
        self.assertEqual(ctx.exception.code, "code_taken")
        with self.assertRaises(CreatorsError) as ctx:
            codes.change_code(other, "TORA20", actor=self.admin, reason="r")
        self.assertEqual(ctx.exception.code, "code_taken")
        self.assertEqual(codes.primary_code(other), "")

    def test_swap_back_to_alias(self):
        codes.change_code(self.creator, "TORA21", actor=self.admin, reason="r")
        row = codes.change_code(self.creator, "TORA20", actor=self.admin, reason="вернули")
        self.assertEqual(row.code, "TORA20")
        self.assertTrue(row.is_primary)
        self.assertFalse(CreatorCode.objects.get(code="TORA21").is_primary)
        self.assertTrue(CreatorCode.objects.get(code="TORA21").is_active)
        self.assertEqual(CreatorCode.objects.filter(creator=self.creator).count(), 2)
        self.assertEqual(AdminActionLog.objects.filter(action="creator.code_change").count(), 2)

    def test_swap_revives_a_retired_alias(self):
        codes.change_code(self.creator, "TORA21", actor=self.admin, reason="r")
        CreatorCode.objects.filter(code="TORA20").update(is_active=False)
        row = codes.change_code(self.creator, "TORA20", actor=self.admin, reason="r")
        self.assertTrue(row.is_primary and row.is_active)

    def test_code_unchanged(self):
        with self.assertRaises(CreatorsError) as ctx:
            codes.change_code(self.creator, "tora20", actor=self.admin, reason="r")
        self.assertEqual(ctx.exception.code, "code_unchanged")
        self.assertFalse(AdminActionLog.objects.filter(action="creator.code_change").exists())

    def test_format_checked(self):
        for raw, error in (("x", "code_format"), ("support", "code_reserved")):
            with self.assertRaises(CreatorsError) as ctx:
                codes.change_code(self.creator, raw, actor=self.admin, reason="r")
            self.assertEqual(ctx.exception.code, error)
        self.assertEqual(codes.primary_code(self.creator), "TORA20")

    def test_refused_change_keeps_old_primary(self):
        f.make_creator(code="TAKEN1")
        with self.assertRaises(CreatorsError):
            codes.change_code(self.creator, "TAKEN1", actor=self.admin, reason="r")
        self.assertEqual(codes.primary_code(self.creator), "TORA20")

    def test_creator_without_code_logs_code_set(self):
        creator = f.make_creator()
        row = codes.change_code(creator, "FIRST1", actor=self.admin, reason="задал за креатора")
        self.assertTrue(row.is_primary)
        log = AdminActionLog.objects.get(action="creator.code_set")
        self.assertEqual(log.before, {"code": None})
        self.assertEqual(log.after, {"code": "FIRST1"})

    def test_blocked_creator_code_can_still_be_changed(self):
        creator = f.make_creator(status="blocked", code="BLOCK1")
        row = codes.change_code(creator, "BLOCK2", actor=self.admin, reason="r")
        self.assertEqual(row.code, "BLOCK2")


class ReverseGuardTests(f.CreatorsTestCase):
    """Реферальный UID и обычный промокод не могут занять код креатора."""

    def test_generate_unique_uid_skips_creator_code(self):
        f.make_creator(code="ABCD2345")
        user = f.make_user()
        with mock.patch("users.models.random.choices",
                        side_effect=[list("ABCD2345"), list("ZZZZ9999")]) as choices:
            self.assertEqual(user._generate_unique_uid(), "ZZZZ9999")
        self.assertEqual(choices.call_count, 2)

    def test_new_user_default_uid_equal_to_creator_code_is_replaced(self):
        f.make_creator(code="ABCD2345")
        User = get_user_model()
        user = User(email="guard@example.com", referral_uid="ABCD2345")
        user.set_password("x")
        user.save()
        user.refresh_from_db()
        self.assertTrue(user.referral_uid)
        self.assertNotEqual(user.referral_uid, "ABCD2345")
        self.assertEqual(attribution.resolve_code("ABCD2345")[0], "creator")

    def test_existing_user_save_costs_no_creator_query(self):
        user = f.make_user()
        with mock.patch("users.models._creator_code_taken") as taken:
            user.first_name = "Имя"
            user.save()
        taken.assert_not_called()

    def test_failing_creators_import_does_not_break_signup(self):
        with mock.patch("creators.codes.creator_code_exists", side_effect=RuntimeError("boom")):
            user = f.make_user()
        self.assertTrue(user.referral_uid)

    def test_promo_serializer_rejects_creator_code(self):
        f.make_creator(code="TORA20")
        serializer = PromoCodeAdminSerializer(data={"code": "tora20", "bonus_credits": 10})
        self.assertFalse(serializer.is_valid())
        self.assertEqual([str(e) for e in serializer.errors["code"]],
                         ["Этот код занят промокодом креатора."])

    def test_promo_serializer_rejects_alias_and_retired_code(self):
        creator = f.make_creator(code="TORA20")
        codes.change_code(creator, "TORA21", actor=f.make_user(superuser=True), reason="r")
        CreatorCode.objects.filter(code="TORA20").update(is_active=False)
        serializer = PromoCodeAdminSerializer(data={"code": "TORA20", "bonus_credits": 10})
        self.assertFalse(serializer.is_valid())

    def test_promo_serializer_still_accepts_other_codes(self):
        f.make_creator(code="TORA20")
        serializer = PromoCodeAdminSerializer(data={"code": "welcome50", "bonus_credits": 50})
        self.assertTrue(serializer.is_valid(), serializer.errors)
        promo = serializer.save()
        self.assertEqual(promo.code, "WELCOME50")

    def test_promo_serializer_survives_failing_creators(self):
        with mock.patch("creators.codes.creator_code_exists", side_effect=RuntimeError("boom")):
            serializer = PromoCodeAdminSerializer(data={"code": "SPRING", "bonus_credits": 5})
            self.assertTrue(serializer.is_valid(), serializer.errors)
