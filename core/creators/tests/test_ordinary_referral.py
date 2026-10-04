"""Обычная реферальная программа (referred_by, 10% кредитами) не изменилась.

Программа Creators встроена в ту же функцию регистрации, поэтому здесь —
прежнее поведение обычной реф-ссылки в каждом режиме программы: on, staff, off.
"""
from datetime import timedelta
from types import SimpleNamespace

from django.contrib.auth import get_user_model
from django.test import override_settings

from users import services as user_services

from ..models import CreatorClick, CreatorReferral
from . import factories as f


def _request(cookies=None, data=None):
    return SimpleNamespace(COOKIES=dict(cookies or {}), data=dict(data or {}), META={})


class OrdinaryReferralMixin:
    def setUp(self):
        super().setUp()
        # Креатор с кодом существует рядом и ничему не мешает.
        f.make_creator(code="TORA20")
        self.referrer = f.make_user()
        get_user_model().objects.filter(pk=self.referrer.pk).update(referral_uid="AB12CD34")
        self.referrer.refresh_from_db()
        self.user = f.make_user()

    def assertLinked(self, user, referrer):
        user.refresh_from_db()
        self.assertEqual(user.referred_by_id, referrer.pk)
        self.assertFalse(CreatorReferral.objects.exists())
        self.assertFalse(CreatorClick.objects.exists())

    def test_cookie_sets_referred_by(self):
        user_services.maybe_link_referrer(_request(cookies={"esai_ref": "AB12CD34"}), self.user)
        self.assertLinked(self.user, self.referrer)

    def test_cookie_is_case_insensitive(self):
        user_services.maybe_link_referrer(_request(cookies={"esai_ref": " ab12cd34 "}), self.user)
        self.assertLinked(self.user, self.referrer)

    def test_body_ref(self):
        user_services.maybe_link_referrer(_request(data={"ref": "AB12CD34"}), self.user)
        self.assertLinked(self.user, self.referrer)

    def test_bot_argument(self):
        user_services.maybe_link_referrer(_request(), self.user, code="AB12CD34")
        self.assertLinked(self.user, self.referrer)

    def test_argument_wins_over_cookie(self):
        other = f.make_user()
        user_services.maybe_link_referrer(
            _request(cookies={"esai_ref": other.referral_uid}), self.user, code="AB12CD34")
        self.assertLinked(self.user, self.referrer)

    def test_numeric_pk_fallback(self):
        user_services.maybe_link_referrer(
            _request(cookies={"esai_ref": str(self.referrer.pk)}), self.user)
        self.assertLinked(self.user, self.referrer)

    def test_self_link_ignored(self):
        user_services.maybe_link_referrer(
            _request(cookies={"esai_ref": self.user.referral_uid}), self.user)
        self.user.refresh_from_db()
        self.assertIsNone(self.user.referred_by_id)
        user_services.maybe_link_referrer(
            _request(cookies={"esai_ref": str(self.user.pk)}), self.user)
        self.user.refresh_from_db()
        self.assertIsNone(self.user.referred_by_id)

    def test_second_call_does_not_overwrite(self):
        user_services.maybe_link_referrer(_request(cookies={"esai_ref": "AB12CD34"}), self.user)
        other = f.make_user()
        self.user.refresh_from_db()
        user_services.maybe_link_referrer(
            _request(cookies={"esai_ref": other.referral_uid}), self.user)
        self.assertLinked(self.user, self.referrer)

    def test_unknown_code(self):
        user_services.maybe_link_referrer(_request(cookies={"esai_ref": "NOSUCH99"}), self.user)
        self.user.refresh_from_db()
        self.assertIsNone(self.user.referred_by_id)

    def test_no_code(self):
        user_services.maybe_link_referrer(_request(), self.user)
        self.user.refresh_from_db()
        self.assertIsNone(self.user.referred_by_id)

    def test_ten_minute_rule(self):
        old = f.make_user(joined_ago=timedelta(minutes=11))
        user_services.maybe_link_referrer(_request(cookies={"esai_ref": "AB12CD34"}), old)
        old.refresh_from_db()
        self.assertIsNone(old.referred_by_id)

    def test_alias_is_the_same_function(self):
        self.assertIs(user_services.maybe_grant_referral_bonus, user_services.maybe_link_referrer)

    def test_staff_user_is_linked_as_before(self):
        # Ограничение «сотрудников не привязываем» — только у программы Creators.
        staff = f.make_user(staff=True)
        user_services.maybe_link_referrer(_request(cookies={"esai_ref": "AB12CD34"}), staff)
        self.assertLinked(staff, self.referrer)

    def test_request_without_cookies_and_data(self):
        user_services.maybe_link_referrer(None, self.user, code="AB12CD34")
        self.assertLinked(self.user, self.referrer)


@override_settings(CREATORS_MODE="on")
class OrdinaryReferralOnTests(OrdinaryReferralMixin, f.CreatorsTestCase):
    pass


@override_settings(CREATORS_MODE="staff")
class OrdinaryReferralStaffTests(OrdinaryReferralMixin, f.CreatorsTestCase):
    pass


@override_settings(CREATORS_MODE="off")
class OrdinaryReferralOffTests(OrdinaryReferralMixin, f.CreatorsTestCase):
    def test_creator_code_is_just_an_unknown_code(self):
        # Программа выключена: код креатора ничего не привязывает.
        user_services.maybe_link_referrer(_request(cookies={"esai_ref": "TORA20"}), self.user)
        self.user.refresh_from_db()
        self.assertIsNone(self.user.referred_by_id)
        self.assertFalse(CreatorReferral.objects.exists())
