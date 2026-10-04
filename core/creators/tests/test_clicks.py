"""Переходы по ссылке креатора: один на устройство в день, свои и чужие не считаются."""
import hashlib
from datetime import date
from types import SimpleNamespace
from unittest import mock

from django.conf import settings
from django.contrib.auth.models import AnonymousUser
from django.db import IntegrityError
from django.test import override_settings

from .. import clicks
from ..models import CreatorClick
from . import factories as f


def _request(*, device=None, body=None, cookie=None, ip="10.0.0.1", xff=None, user=None):
    meta = {}
    if ip:
        meta["REMOTE_ADDR"] = ip
    if xff:
        meta["HTTP_X_FORWARDED_FOR"] = xff
    if device:
        meta["HTTP_X_DEVICE_KEY"] = device
    return SimpleNamespace(META=meta, data=dict(body or {}),
                           COOKIES={"esai_device_key": cookie} if cookie else {},
                           user=user or AnonymousUser())


def _ip_hash(ip):
    return hashlib.sha256((settings.SECRET_KEY + ip).encode()).hexdigest()


class RecordTests(f.CreatorsTestCase):
    def setUp(self):
        super().setUp()
        self.creator = f.make_creator(code="TORA20")

    def test_new_row(self):
        self.assertTrue(clicks.record(" tora20 ", _request(device="dev-1")))
        click = CreatorClick.objects.get()
        self.assertEqual(click.creator_id, self.creator.pk)
        self.assertEqual(click.code, "TORA20")
        self.assertEqual(click.device_key, "dev-1")
        self.assertEqual(click.ip_hash, _ip_hash("10.0.0.1"))
        # Сам адрес посетителя в базе не лежит.
        self.assertNotIn("10.0.0.1", click.ip_hash)

    def test_same_device_same_day_is_deduped(self):
        self.assertTrue(clicks.record("TORA20", _request(device="dev-1")))
        self.assertFalse(clicks.record("TORA20", _request(device="dev-1", ip="10.0.0.99")))
        self.assertEqual(CreatorClick.objects.count(), 1)

    def test_another_device_same_day(self):
        clicks.record("TORA20", _request(device="dev-1"))
        self.assertTrue(clicks.record("TORA20", _request(device="dev-2")))
        self.assertEqual(CreatorClick.objects.count(), 2)

    def test_one_address_cannot_inflate_clicks_with_made_up_device_keys(self):
        # Ключ устройства присылает клиент: без потолка по адресу один IP
        # накручивал бы «Переходы» сколько угодно.
        for n in range(clicks.IP_DAILY_CAP + 5):
            clicks.record("TORA20", _request(device=f"dev-{n}"))
        self.assertEqual(CreatorClick.objects.count(), clicks.IP_DAILY_CAP)
        # Другой адрес и другой креатор считаются как обычно.
        self.assertTrue(clicks.record("TORA20", _request(device="dev-x", ip="10.0.0.2")))
        f.make_creator(code="OTHER1")
        self.assertTrue(clicks.record("OTHER1", _request(device="dev-0")))

    def test_address_cap_is_per_day(self):
        with mock.patch("creators.clicks.timezone.localdate", return_value=date(2026, 10, 1)):
            for n in range(clicks.IP_DAILY_CAP):
                self.assertTrue(clicks.record("TORA20", _request(device=f"dev-{n}")))
            self.assertFalse(clicks.record("TORA20", _request(device="dev-late")))
        with mock.patch("creators.clicks.timezone.localdate", return_value=date(2026, 10, 2)):
            self.assertTrue(clicks.record("TORA20", _request(device="dev-late")))

    def test_next_day_is_counted(self):
        with mock.patch("creators.clicks.timezone.localdate", return_value=date(2026, 10, 1)):
            self.assertTrue(clicks.record("TORA20", _request(device="dev-1")))
        with mock.patch("creators.clicks.timezone.localdate", return_value=date(2026, 10, 2)):
            self.assertTrue(clicks.record("TORA20", _request(device="dev-1")))
        self.assertEqual(sorted(CreatorClick.objects.values_list("day", flat=True)),
                         [date(2026, 10, 1), date(2026, 10, 2)])

    def test_device_key_sources(self):
        self.assertTrue(clicks.record("TORA20", _request(body={"device_key": "from-body"})))
        self.assertTrue(clicks.record("TORA20", _request(cookie="from-cookie")))
        # Заголовок важнее тела и cookie.
        self.assertTrue(clicks.record(
            "TORA20", _request(device="from-header", body={"device_key": "x"}, cookie="y")))
        self.assertEqual(set(CreatorClick.objects.values_list("device_key", flat=True)),
                         {"from-body", "from-cookie", "from-header"})

    def test_device_key_is_trimmed(self):
        clicks.record("TORA20", _request(device="k" * 200))
        self.assertEqual(CreatorClick.objects.get().device_key, "k" * 64)

    def test_no_device_key_falls_back_to_ip_hash(self):
        self.assertTrue(clicks.record("TORA20", _request()))
        click = CreatorClick.objects.get()
        self.assertEqual(click.device_key, "ip:" + _ip_hash("10.0.0.1")[:40])
        self.assertFalse(clicks.record("TORA20", _request()))
        self.assertTrue(clicks.record("TORA20", _request(ip="10.0.0.2")))

    def test_first_forwarded_hop_is_the_ip(self):
        clicks.record("TORA20", _request(xff="203.0.113.7, 10.0.0.1", ip="10.0.0.1"))
        self.assertEqual(CreatorClick.objects.get().ip_hash, _ip_hash("203.0.113.7"))

    def test_no_ip_and_no_device_key(self):
        self.assertFalse(clicks.record("TORA20", _request(ip=None)))
        self.assertFalse(CreatorClick.objects.exists())

    def test_device_key_without_ip(self):
        self.assertTrue(clicks.record("TORA20", _request(device="dev-1", ip=None)))
        self.assertEqual(CreatorClick.objects.get().ip_hash, "")

    def test_own_click_ignored(self):
        self.assertFalse(clicks.record("TORA20", _request(device="dev-1", user=self.creator.user)))
        self.assertFalse(CreatorClick.objects.exists())

    def test_other_signed_in_user_is_counted(self):
        self.assertTrue(clicks.record("TORA20", _request(device="dev-1", user=f.make_user())))

    def test_alias_click_goes_to_the_same_creator(self):
        from .. import codes

        codes.change_code(self.creator, "TORA21", actor=f.make_user(superuser=True), reason="r")
        self.assertTrue(clicks.record("TORA20", _request(device="dev-1")))
        click = CreatorClick.objects.get()
        self.assertEqual((click.creator_id, click.code), (self.creator.pk, "TORA20"))

    def test_unknown_code(self):
        for code in ("NOSUCH1", "", None, "12345", "x"):
            self.assertFalse(clicks.record(code, _request(device="dev-1")), code)
        self.assertFalse(CreatorClick.objects.exists())

    def test_ordinary_referral_uid_is_not_a_click(self):
        user = f.make_user()
        self.assertFalse(clicks.record(user.referral_uid, _request(device="dev-1")))

    def test_blocked_creator(self):
        f.make_creator(status="blocked", code="BLOCK1")
        self.assertFalse(clicks.record("BLOCK1", _request(device="dev-1")))
        self.assertFalse(CreatorClick.objects.exists())

    @override_settings(CREATORS_MODE="off")
    def test_off_mode(self):
        self.assertFalse(clicks.record("TORA20", _request(device="dev-1")))
        self.assertFalse(CreatorClick.objects.exists())

    @override_settings(CREATORS_MODE="staff")
    def test_staff_mode_counts_only_staff_creators(self):
        self.assertFalse(clicks.record("TORA20", _request(device="dev-1")))
        f.make_creator(f.make_user(staff=True), code="STAFF1")
        self.assertTrue(clicks.record("STAFF1", _request(device="dev-1")))

    def test_never_raises(self):
        self.assertFalse(clicks.record("TORA20", None))
        self.assertFalse(clicks.record("TORA20", object()))
        with mock.patch("creators.attribution.creator_code", side_effect=RuntimeError("boom")):
            self.assertFalse(clicks.record("TORA20", _request(device="dev-1")))
        with mock.patch.object(CreatorClick.objects, "get_or_create",
                               side_effect=IntegrityError("dup")):
            self.assertFalse(clicks.record("TORA20", _request(device="dev-1")))
        with mock.patch("creators.clicks.flags.is_off", side_effect=RuntimeError("boom")):
            self.assertFalse(clicks.record("TORA20", _request(device="dev-1")))
        self.assertFalse(CreatorClick.objects.exists())


class RecordBotTests(f.CreatorsTestCase):
    def setUp(self):
        super().setUp()
        self.creator = f.make_creator(code="TORA20")
        self.row = self.creator.codes.get()

    def test_one_row_per_telegram_account(self):
        user = f.make_user(telegram_uid=700900)
        self.assertTrue(clicks.record_bot(self.row, user))
        self.assertFalse(clicks.record_bot(self.row, user))
        click = CreatorClick.objects.get()
        self.assertEqual(click.device_key, "tg:700900")
        self.assertEqual(click.code, "TORA20")
        self.assertEqual(click.ip_hash, "")
        self.assertTrue(clicks.record_bot(self.row, f.make_user(telegram_uid=700901)))
        self.assertEqual(CreatorClick.objects.count(), 2)

    def test_delete_and_start_again_is_the_same_arrival(self):
        # /delete -> /start по ссылке заводит нового пользователя, но Telegram тот же.
        from allauth.socialaccount.models import SocialAccount

        first = f.make_user(telegram_uid=700900)
        self.assertTrue(clicks.record_bot(self.row, first))
        SocialAccount.objects.filter(user=first).delete()
        again = f.make_user(telegram_uid=700900)
        self.assertFalse(clicks.record_bot(self.row, again))
        self.assertEqual(CreatorClick.objects.count(), 1)

    def test_user_without_telegram_is_keyed_by_the_account(self):
        user = f.make_user()
        self.assertTrue(clicks.record_bot(self.row, user))
        self.assertFalse(clicks.record_bot(self.row, user))
        self.assertEqual(CreatorClick.objects.get().device_key, f"user:{user.pk}")

    def test_deactivated_creator_account(self):
        owner = self.creator.user
        owner.is_active = False
        owner.save(update_fields=["is_active"])
        row = self.creator.codes.select_related("creator__user").get()
        self.assertFalse(clicks.record_bot(row, f.make_user(telegram_uid=700902)))
        self.assertFalse(clicks.record("TORA20", _request(device="dev-1")))
        self.assertFalse(CreatorClick.objects.exists())

    def test_creators_own_account_ignored(self):
        self.assertFalse(clicks.record_bot(self.row, self.creator.user))
        self.assertFalse(CreatorClick.objects.exists())

    def test_user_without_pk(self):
        self.assertFalse(clicks.record_bot(self.row, None))
        self.assertFalse(clicks.record_bot(self.row, SimpleNamespace(pk=None)))

    def test_blocked_creator(self):
        blocked = f.make_creator(status="blocked", code="BLOCK1")
        self.assertFalse(clicks.record_bot(blocked.codes.get(), f.make_user()))
        self.assertFalse(CreatorClick.objects.exists())

    @override_settings(CREATORS_MODE="off")
    def test_off_mode(self):
        self.assertFalse(clicks.record_bot(self.row, f.make_user()))
        self.assertFalse(CreatorClick.objects.exists())

    def test_never_raises(self):
        self.assertFalse(clicks.record_bot(None, f.make_user()))
        with mock.patch.object(CreatorClick.objects, "get_or_create",
                               side_effect=IntegrityError("dup")):
            self.assertFalse(clicks.record_bot(self.row, f.make_user()))
