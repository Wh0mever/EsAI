"""Привязка пользователя к креатору: кто, когда и по какому коду.

Проверяется весь путь, которым привязка появляется в жизни: реф-ссылка и бот
при регистрации (users.services.maybe_link_referrer), код в поле промокода
(activate_promo и PromoActivateView), ручная перепривязка администратором.
Отдельно — признаки накрутки: подозрительная привязка создаётся, но не
считается и не объявляется креатору.
"""
import sys
from datetime import timedelta
from types import SimpleNamespace
from unittest import mock

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.db import IntegrityError
from django.test import override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from audit.models import AdminActionLog, EventLog, SignupDevice
from plans.models import PromoActivation, PromoCode, TokenTransaction
from users import services as user_services
from users.models import NotificationDelivery

from .. import attribution
from ..errors import CreatorsError
from ..models import CreatorClick, CreatorCode, CreatorCommission, CreatorReferral
from . import factories as f

NOT_FOUND = "Промокод не найден или неактивен"
_DEFAULT = object()


def _request(cookies=None, data=None):
    """Запрос регистрации: сервисам нужны только COOKIES и data."""
    return SimpleNamespace(COOKIES=dict(cookies or {}), data=dict(data or {}), META={})


def _device(user, *, fingerprint="", ip=None, subnet=""):
    return SignupDevice.objects.create(user=user, fingerprint=fingerprint, ip=ip, subnet=subnet)


def _ordinary_referrer(uid="AB12CD34"):
    user = f.make_user()
    get_user_model().objects.filter(pk=user.pk).update(referral_uid=uid)
    user.refresh_from_db()
    return user


class ResolveCodeTests(f.CreatorsTestCase):
    def setUp(self):
        super().setUp()
        self.creator = f.make_creator(code="TORA20")
        self.referrer = _ordinary_referrer("AB12CD34")

    def test_creator_code(self):
        kind, row = attribution.resolve_code(" tora20 ")
        self.assertEqual(kind, "creator")
        self.assertEqual(row.creator_id, self.creator.pk)

    def test_referral_uid_case_insensitive(self):
        self.assertEqual(attribution.resolve_code("ab12cd34"), ("user", self.referrer))

    def test_digits_fall_back_to_user_pk(self):
        self.assertEqual(attribution.resolve_code(str(self.referrer.pk)), ("user", self.referrer))

    def test_uid_wins_over_pk_for_digit_codes(self):
        other = _ordinary_referrer(str(self.referrer.pk))
        self.assertEqual(attribution.resolve_code(str(self.referrer.pk)), ("user", other))

    def test_none(self):
        for raw in ("", None, "NOSUCH1", "999999999"):
            self.assertIsNone(attribution.resolve_code(raw), raw)

    def test_retired_code_does_not_resolve(self):
        CreatorCode.objects.filter(code="TORA20").update(is_active=False)
        self.assertIsNone(attribution.creator_code("TORA20"))
        self.assertIsNone(attribution.resolve_code("TORA20"))

    @override_settings(CREATORS_MODE="off")
    def test_off_mode_skips_creators(self):
        self.assertIsNone(attribution.creator_code("TORA20"))
        self.assertIsNone(attribution.resolve_code("TORA20"))
        self.assertEqual(attribution.resolve_code("AB12CD34"), ("user", self.referrer))


class LinkAtSignupTests(f.CreatorsTestCase):
    """maybe_link_referrer: ссылка креатора при регистрации."""

    def setUp(self):
        super().setUp()
        self.creator = f.make_creator(code="TORA20")

    def _referral(self, user):
        return CreatorReferral.objects.filter(user=user).first()

    def test_cookie(self):
        user = f.make_user()
        user_services.maybe_link_referrer(_request(cookies={"esai_ref": "tora20"}), user)
        referral = self._referral(user)
        self.assertEqual(referral.creator_id, self.creator.pk)
        self.assertEqual(referral.source, "link")
        self.assertEqual(referral.code_used, "TORA20")
        self.assertIsNone(referral.ended_at)
        user.refresh_from_db()
        self.assertIsNone(user.referred_by_id)
        # Переход по ссылке сайта пишет сайт (POST /click/), а не регистрация.
        self.assertFalse(CreatorClick.objects.exists())

    def test_body_ref(self):
        user = f.make_user()
        user_services.maybe_link_referrer(_request(data={"ref": "TORA20"}), user)
        self.assertEqual(self._referral(user).source, "link")

    def test_bot_argument(self):
        user = f.make_user(telegram_uid=700200)
        user_services.maybe_link_referrer(_request(), user, code="TORA20")
        referral = self._referral(user)
        self.assertEqual(referral.source, "bot")
        self.assertEqual(referral.telegram_uid, "700200")
        self.assertFalse(referral.suspect)
        click = CreatorClick.objects.get()
        self.assertEqual(click.creator_id, self.creator.pk)
        # Ключ перехода — сам Telegram, а не строка пользователя.
        self.assertEqual(click.device_key, "tg:700200")
        self.assertEqual(click.code, "TORA20")

    def test_alias_code_binds_to_the_same_creator(self):
        from .. import codes

        codes.change_code(self.creator, "TORA21", actor=f.make_user(superuser=True), reason="r")
        user = f.make_user()
        user_services.maybe_link_referrer(_request(cookies={"esai_ref": "TORA20"}), user)
        referral = self._referral(user)
        self.assertEqual(referral.creator_id, self.creator.pk)
        self.assertEqual(referral.code_used, "TORA20")

    def test_ten_minute_rule(self):
        user = f.make_user(joined_ago=timedelta(minutes=11))
        user_services.maybe_link_referrer(_request(cookies={"esai_ref": "TORA20"}), user)
        self.assertIsNone(self._referral(user))
        self.assertIsNone(user.referred_by_id)

    def test_refused_creator_hit_never_sets_referred_by(self):
        # Сотрудника к креатору не привязываем — и обычным рефералом он тоже не становится.
        user = f.make_user(staff=True)
        user_services.maybe_link_referrer(_request(cookies={"esai_ref": "TORA20"}), user)
        self.assertIsNone(self._referral(user))
        user.refresh_from_db()
        self.assertIsNone(user.referred_by_id)

    def test_blocked_creator_link_does_not_fall_through(self):
        blocked = f.make_creator(status="blocked", code="BLOCK1")
        user = f.make_user()
        user_services.maybe_link_referrer(_request(cookies={"esai_ref": "BLOCK1"}), user)
        self.assertIsNone(self._referral(user))
        user.refresh_from_db()
        self.assertIsNone(user.referred_by_id)
        self.assertFalse(CreatorClick.objects.filter(creator=blocked).exists())

    def test_typed_creator_promo_beats_ordinary_ref_cookie(self):
        referrer = _ordinary_referrer()
        user = f.make_user()
        request = _request(cookies={"esai_ref": referrer.referral_uid, "esai_promo": "tora20"})
        user_services.maybe_link_referrer(request, user)
        referral = self._referral(user)
        self.assertEqual(referral.source, "promo")
        self.assertEqual(referral.creator_id, self.creator.pk)
        user.refresh_from_db()
        self.assertIsNone(user.referred_by_id)

    def test_refused_typed_creator_code_keeps_the_ordinary_referrer(self):
        # Код креатора введён, но привязка отказана (креатор заблокирован):
        # человек не закреплён ни за кем, и обычная ссылка друга работает как раньше.
        f.make_creator(status="blocked", code="BLOCK1")
        referrer = _ordinary_referrer()
        user = f.make_user()
        request = _request(cookies={"esai_ref": referrer.referral_uid, "esai_promo": "BLOCK1"})
        user_services.maybe_link_referrer(request, user)
        self.assertIsNone(self._referral(user))
        user.refresh_from_db()
        self.assertEqual(user.referred_by_id, referrer.pk)

    @override_settings(CREATORS_MODE="staff")
    def test_typed_code_unusable_in_staff_mode_keeps_the_ordinary_referrer(self):
        referrer = _ordinary_referrer()
        user = f.make_user()
        request = _request(cookies={"esai_ref": referrer.referral_uid, "esai_promo": "TORA20"})
        user_services.maybe_link_referrer(request, user)
        self.assertIsNone(self._referral(user))
        user.refresh_from_db()
        self.assertEqual(user.referred_by_id, referrer.pk)

    def test_refused_typed_creator_code_falls_back_to_the_creator_link(self):
        f.make_creator(status="blocked", code="BLOCK1")
        user = f.make_user()
        user_services.maybe_link_referrer(
            _request(cookies={"esai_ref": "TORA20", "esai_promo": "BLOCK1"}), user)
        referral = self._referral(user)
        self.assertEqual((referral.creator_id, referral.source), (self.creator.pk, "link"))
        user.refresh_from_db()
        self.assertIsNone(user.referred_by_id)

    def test_typed_code_of_a_user_bound_to_another_creator_sets_no_referrer(self):
        # Отказ «уже закреплён за другим креатором»: человек покрыт привязкой,
        # обычного реферера рядом с ней не ставим (никогда обе программы сразу).
        other = f.make_creator(code="OTHER1")
        referrer = _ordinary_referrer()
        user = f.make_user()
        f.make_referral(other, user)
        request = _request(cookies={"esai_ref": referrer.referral_uid, "esai_promo": "TORA20"})
        user_services.maybe_link_referrer(request, user)
        self.assertEqual(CreatorReferral.objects.get(user=user).creator_id, other.pk)
        user.refresh_from_db()
        self.assertIsNone(user.referred_by_id)

    def test_lost_race_of_the_typed_code_sets_no_referrer(self):
        referrer = _ordinary_referrer()
        user = f.make_user()
        request = _request(cookies={"esai_ref": referrer.referral_uid, "esai_promo": "TORA20"})
        with mock.patch.object(CreatorReferral.objects, "create", side_effect=IntegrityError("dup")):
            user_services.maybe_link_referrer(request, user)
        user.refresh_from_db()
        self.assertIsNone(user.referred_by_id)

    def test_failing_bind_of_the_typed_code_sets_no_referrer(self):
        # Сбой программы: состоялась ли привязка, неизвестно — реферера не ставим.
        referrer = _ordinary_referrer()
        user = f.make_user()
        request = _request(cookies={"esai_ref": referrer.referral_uid, "esai_promo": "TORA20"})
        with mock.patch("creators.attribution.bind", side_effect=RuntimeError("boom")):
            user_services.maybe_link_referrer(request, user)
        user.refresh_from_db()
        self.assertIsNone(user.referred_by_id)

    def test_typed_creator_promo_in_body_beats_ref(self):
        referrer = _ordinary_referrer()
        user = f.make_user()
        user_services.maybe_link_referrer(
            _request(data={"ref": referrer.referral_uid, "promo": "TORA20"}), user)
        self.assertEqual(self._referral(user).source, "promo")

    def test_same_code_in_link_and_promo_field_is_a_link(self):
        user = f.make_user()
        user_services.maybe_link_referrer(
            _request(cookies={"esai_ref": "TORA20", "esai_promo": "tora20"}), user)
        self.assertEqual(self._referral(user).source, "link")

    def test_typed_ordinary_promo_does_not_block_ordinary_ref(self):
        PromoCode.objects.create(code="WELCOME", bonus_credits=5)
        referrer = _ordinary_referrer()
        user = f.make_user()
        user_services.maybe_link_referrer(
            _request(cookies={"esai_ref": referrer.referral_uid, "esai_promo": "WELCOME"}), user)
        user.refresh_from_db()
        self.assertEqual(user.referred_by_id, referrer.pk)
        self.assertIsNone(self._referral(user))

    def test_user_with_referrer_is_left_alone(self):
        referrer = _ordinary_referrer()
        user = f.make_user()
        user.referred_by = referrer
        user.save(update_fields=["referred_by"])
        user_services.maybe_link_referrer(_request(cookies={"esai_ref": "TORA20"}), user)
        self.assertIsNone(self._referral(user))

    def test_failing_creators_module_keeps_ordinary_program(self):
        referrer = _ordinary_referrer()
        user = f.make_user()
        with mock.patch("creators.attribution.creator_code", side_effect=RuntimeError("boom")):
            user_services.maybe_link_referrer(
                _request(cookies={"esai_ref": referrer.referral_uid}), user)
        user.refresh_from_db()
        self.assertEqual(user.referred_by_id, referrer.pk)

    def test_new_referral_notification(self):
        user = f.make_user(email="invited@example.com")
        with mock.patch("botapi.tasks.notify") as telegram:
            with self.captureOnCommitCallbacks(execute=True):
                user_services.maybe_link_referrer(_request(cookies={"esai_ref": "TORA20"}), user)
        delivery = NotificationDelivery.objects.get(recipient=self.creator.user)
        self.assertEqual(delivery.notification.title, "Новый реферал")
        # Почта приглашённого креатору не показывается.
        self.assertNotIn("invited@example.com", delivery.notification.body)
        self.assertEqual(telegram.call_args.args[1], "creator")


class BindRefusalTests(f.CreatorsTestCase):
    def setUp(self):
        super().setUp()
        self.creator = f.make_creator(code="TORA20")
        self.user = f.make_user()

    def assertRefused(self, reason, user=_DEFAULT, creator=None, **kwargs):
        kwargs.setdefault("source", "promo")
        before = CreatorReferral.objects.count()
        result = attribution.bind(self.user if user is _DEFAULT else user,
                                  creator or self.creator, **kwargs)
        self.assertFalse(result.ok)
        self.assertEqual(result.reason, reason)
        self.assertEqual(CreatorReferral.objects.count(), before)
        return result

    def test_ok(self):
        result = attribution.bind(self.user, self.creator, source="promo", code_used="tora20")
        self.assertTrue(result.ok)
        self.assertEqual(result.reason, "")
        self.assertEqual(result.referral.code_used, "TORA20")
        self.assertEqual(result.referral.flags, {"reasons": []})
        self.assertIsNone(result.referral.bound_by_id)

    @override_settings(CREATORS_MODE="off")
    def test_disabled(self):
        self.assertRefused("disabled")

    def test_no_user(self):
        self.assertRefused("no_user", user=None)
        self.assertRefused("no_user", user=get_user_model()(email="unsaved@example.com"))
        self.user.is_active = False
        self.user.save(update_fields=["is_active"])
        self.assertRefused("no_user")

    def test_creator_unusable_blocked(self):
        self.assertRefused("creator_unusable", creator=f.make_creator(status="blocked"))
        # Даже администратору.
        self.assertRefused("creator_unusable", creator=f.make_creator(status="blocked"),
                           source="admin", force=True)

    @override_settings(CREATORS_MODE="staff")
    def test_creator_unusable_in_staff_mode(self):
        self.assertRefused("creator_unusable")
        staff_creator = f.make_creator(f.make_user(staff=True))
        self.assertTrue(attribution.bind(self.user, staff_creator, source="promo").ok)

    def test_stale_creator_object_is_reread(self):
        from ..models import Creator

        Creator.objects.filter(pk=self.creator.pk).update(status="blocked")
        # В руках вызывающего креатор ещё «активен».
        self.assertEqual(self.creator.status, "active")
        self.assertRefused("creator_unusable")

    def test_self(self):
        self.assertRefused("self", user=self.creator.user)
        self.assertRefused("self", user=self.creator.user, source="admin", force=True)

    def test_staff(self):
        self.assertRefused("staff", user=f.make_user(staff=True))
        self.assertRefused("staff", user=f.make_user(superuser=True), source="admin", force=True)

    def test_already_bound_same(self):
        first = attribution.bind(self.user, self.creator, source="promo")
        result = self.assertRefused("already_bound_same")
        self.assertEqual(result.referral.pk, first.referral.pk)

    def test_already_bound(self):
        attribution.bind(self.user, self.creator, source="promo")
        result = self.assertRefused("already_bound", creator=f.make_creator())
        self.assertIsNone(result.referral)
        self.assertRefused("already_bound", creator=f.make_creator(), source="admin", force=True)

    def test_has_referrer(self):
        self.user.referred_by = f.make_user()
        self.user.save(update_fields=["referred_by"])
        self.assertRefused("has_referrer")
        self.assertRefused("has_referrer", source="link")
        self.assertTrue(attribution.bind(self.user, self.creator, source="admin", force=True).ok)

    def test_link_window(self):
        late = f.make_user(joined_ago=timedelta(minutes=11))
        self.assertRefused("link_window", user=late, source="link")
        self.assertRefused("link_window", user=late, source="bot")
        # Введённый код в те же минуты ещё действует.
        self.assertTrue(attribution.bind(late, self.creator, source="promo").ok)

    def test_link_inside_window(self):
        fresh = f.make_user(joined_ago=timedelta(minutes=9))
        self.assertTrue(attribution.bind(fresh, self.creator, source="link").ok)

    def test_too_late(self):
        self.assertRefused("too_late", user=f.make_user(joined_ago=73))
        self.assertTrue(attribution.bind(f.make_user(joined_ago=71), self.creator,
                                         source="promo").ok)

    def test_already_paid(self):
        self.assertRefused("already_paid", user=f.make_user(paid=True))
        only_flag = f.make_user()
        get_user_model().objects.filter(pk=only_flag.pk).update(is_paid=True)
        self.assertRefused("already_paid", user=only_flag)
        only_date = f.make_user()
        get_user_model().objects.filter(pk=only_date.pk).update(first_paid_at=timezone.now())
        self.assertRefused("already_paid", user=only_date)

    def test_force_skips_time_and_payment_rules(self):
        old_paying = f.make_user(paid=True, joined_ago=timedelta(days=400))
        admin = f.make_user(superuser=True)
        result = attribution.bind(old_paying, self.creator, source="admin", actor=admin, force=True)
        self.assertTrue(result.ok)
        self.assertEqual(result.referral.bound_by_id, admin.pk)

    def test_race(self):
        # Проверка «привязки нет» прошла, а вставку опередил параллельный запрос.
        with mock.patch.object(CreatorReferral.objects, "create", side_effect=IntegrityError("dup")):
            self.assertRefused("race")

    def test_order_of_refusals(self):
        # Свой код важнее, чем «сотрудник»; «сотрудник» важнее окна по времени.
        staff_creator = f.make_creator(f.make_user(staff=True))
        self.assertRefused("self", user=staff_creator.user, creator=staff_creator)
        self.assertRefused("staff", user=f.make_user(staff=True, joined_ago=100))
        late_referred = f.make_user(joined_ago=100)
        late_referred.referred_by = f.make_user()
        late_referred.save(update_fields=["referred_by"])
        self.assertRefused("has_referrer", user=late_referred)
        self.assertRefused("too_late", user=f.make_user(joined_ago=100, paid=True))


class ActivatePromoTests(f.CreatorsTestCase):
    def setUp(self):
        super().setUp()
        self.creator = f.make_creator(code="TORA20", display_name="Tora")
        self.user = f.make_user()

    def test_success(self):
        result = user_services.activate_promo(self.user, " tora20 ")
        self.assertEqual(result, (True, "Промокод принят — вы пришли по приглашению Tora", 0))
        referral = CreatorReferral.objects.get(user=self.user)
        self.assertEqual(referral.source, "promo")
        self.assertEqual(referral.code_used, "TORA20")
        # Ничего не начислено и активация обычного промокода не записана.
        self.user.refresh_from_db()
        self.assertEqual(self.user.token_balance, 0)
        self.assertFalse(TokenTransaction.objects.filter(user=self.user).exists())
        self.assertFalse(PromoActivation.objects.exists())
        self.assertIsNone(self.user.referred_by_id)

    def test_second_call_is_idempotent(self):
        first = user_services.activate_promo(self.user, "TORA20")
        second = user_services.activate_promo(self.user, "TORA20")
        self.assertEqual(first, second)
        self.assertTrue(second[0])
        self.assertEqual(CreatorReferral.objects.filter(user=self.user).count(), 1)

    def test_refusal_messages(self):
        other = f.make_creator(code="OTHER1")
        bound = f.make_user()
        f.make_referral(other, bound)
        referred = f.make_user()
        referred.referred_by = f.make_user()
        referred.save(update_fields=["referred_by"])
        blocked = f.make_creator(status="blocked", code="BLOCK1")
        cases = (
            (self.creator.user, "TORA20", "self"),
            (f.make_user(staff=True), "TORA20", "staff"),
            (bound, "TORA20", "already_bound"),
            (referred, "TORA20", "has_referrer"),
            (f.make_user(joined_ago=73), "TORA20", "too_late"),
            (f.make_user(paid=True), "TORA20", "already_paid"),
            (f.make_user(), "BLOCK1", "not_found"),
        )
        for user, code, client_code in cases:
            ok, message, credited = user_services.activate_promo(user, code)
            self.assertFalse(ok, client_code)
            self.assertEqual(credited, 0)
            self.assertEqual(message, user_services.CREATOR_PROMO_MESSAGES[client_code])
            self.assertEqual(user_services.creator_promo_code(message), client_code)
        self.assertFalse(CreatorReferral.objects.filter(creator=blocked).exists())
        self.assertEqual(CreatorReferral.objects.filter(creator=self.creator).count(), 0)

    def test_race_is_retry(self):
        with mock.patch.object(CreatorReferral.objects, "create", side_effect=IntegrityError("dup")):
            ok, message, _ = user_services.activate_promo(self.user, "TORA20")
        self.assertFalse(ok)
        self.assertEqual(user_services.creator_promo_code(message), "retry")

    def test_messages_table(self):
        self.assertEqual(set(user_services.CREATOR_PROMO_MESSAGES),
                         {"self", "staff", "already_bound", "has_referrer", "too_late",
                          "already_paid", "not_found", "retry"})
        texts = list(user_services.CREATOR_PROMO_MESSAGES.values())
        self.assertEqual(len(texts), len(set(texts)), "по тексту код должен находиться однозначно")
        self.assertEqual(user_services.creator_promo_code("что-то другое"), "error")

    def test_unknown_code_keeps_the_old_answer(self):
        self.assertEqual(user_services.activate_promo(self.user, "NOSUCH1"), (False, NOT_FOUND, 0))
        self.assertEqual(user_services.activate_promo(self.user, "нет такого"), (False, NOT_FOUND, 0))

    @override_settings(CREATORS_MODE="off")
    def test_off_mode_answers_not_found(self):
        self.assertEqual(user_services.activate_promo(self.user, "TORA20"), (False, NOT_FOUND, 0))
        self.assertFalse(CreatorReferral.objects.exists())

    def test_eleventh_failed_attempt_is_not_found(self):
        late = f.make_user(joined_ago=100)
        for _ in range(10):
            ok, message, _ = user_services.activate_promo(late, "TORA20")
            self.assertEqual(user_services.creator_promo_code(message), "too_late")
        self.assertEqual(user_services.activate_promo(late, "TORA20"), (False, NOT_FOUND, 0))
        # Счётчик свой у каждого пользователя.
        self.assertTrue(user_services.activate_promo(self.user, "TORA20")[0])

    def test_wrong_codes_count_as_failed_attempts(self):
        for _ in range(10):
            user_services.activate_promo(self.user, "NOSUCH1")
        self.assertEqual(user_services.activate_promo(self.user, "TORA20"), (False, NOT_FOUND, 0))
        self.assertFalse(CreatorReferral.objects.exists())

    def test_repeat_of_own_binding_is_not_a_failed_attempt(self):
        for _ in range(12):
            self.assertTrue(user_services.activate_promo(self.user, "TORA20")[0])
        self.assertIsNone(cache.get(f"creators:typed_fail:{self.user.pk}"))

    def test_ordinary_promo_code_credits_as_before(self):
        PromoCode.objects.create(code="WELCOME", bonus_credits=25)
        self.assertEqual(user_services.activate_promo(self.user, "welcome"),
                         (True, "Промокод активирован", 25))
        self.user.refresh_from_db()
        self.assertEqual(self.user.token_balance, 25)
        self.assertEqual(PromoActivation.objects.filter(user=self.user).count(), 1)
        self.assertEqual(TokenTransaction.objects.get(user=self.user).reason, "promo")
        self.assertFalse(CreatorReferral.objects.exists())
        self.assertEqual(user_services.activate_promo(self.user, "WELCOME"),
                         (False, "Вы уже активировали этот промокод", 0))

    def test_failing_creators_module_answers_not_found(self):
        with mock.patch("creators.attribution.bind_by_typed_code", side_effect=RuntimeError("x")):
            self.assertEqual(user_services.activate_promo(self.user, "TORA20"),
                             (False, NOT_FOUND, 0))

    def test_signup_promo_cookie_binds(self):
        user_services.maybe_activate_promo_on_signup(_request(cookies={"esai_promo": "TORA20"}),
                                                     self.user)
        self.assertEqual(CreatorReferral.objects.get(user=self.user).source, "promo")


class PromoActivateViewTests(f.CreatorsTestCase):
    URL = "/api/users/promo/activate/"

    def setUp(self):
        super().setUp()
        self.creator = f.make_creator(code="TORA20", display_name="Tora")

    def _post(self, user, code):
        client = APIClient()
        client.force_authenticate(user)
        return client.post(self.URL, {"code": code}, format="json")

    def test_creator_success(self):
        response = self._post(f.make_user(), "tora20")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {
            "ok": True, "credited": 0, "balance": 0, "kind": "creator",
            "message": "Промокод принят — вы пришли по приглашению Tora"})

    def test_ordinary_success_has_kind_promo(self):
        PromoCode.objects.create(code="WELCOME", bonus_credits=25)
        response = self._post(f.make_user(), "WELCOME")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"ok": True, "credited": 25, "balance": 25,
                                           "message": "Промокод активирован", "kind": "promo"})

    def test_creator_refusals_carry_code(self):
        other = f.make_creator(code="OTHER1")
        bound = f.make_user()
        f.make_referral(other, bound)
        referred = f.make_user()
        referred.referred_by = f.make_user()
        referred.save(update_fields=["referred_by"])
        cases = (
            (self.creator.user, "TORA20", "self"),
            (f.make_user(staff=True), "TORA20", "staff"),
            (bound, "TORA20", "already_bound"),
            (referred, "TORA20", "has_referrer"),
            (f.make_user(joined_ago=73), "TORA20", "too_late"),
            (f.make_user(paid=True), "TORA20", "already_paid"),
        )
        for user, code, client_code in cases:
            response = self._post(user, code)
            self.assertEqual(response.status_code, 400, client_code)
            self.assertEqual(response.json(), {
                "status": "error", "kind": "creator", "code": client_code,
                "message": user_services.CREATOR_PROMO_MESSAGES[client_code]})

    def _assert_plain_not_found(self, response):
        """Тело байт в байт как у несуществующего промокода: ни kind, ни code."""
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json(), {"status": "error", "message": NOT_FOUND})

    def test_blocked_creator_code_looks_like_an_unknown_code(self):
        f.make_creator(status="blocked", code="BLOCK1")
        self._assert_plain_not_found(self._post(f.make_user(), "BLOCK1"))

    def test_retired_code_looks_like_an_unknown_code(self):
        CreatorCode.objects.create(code="OLDONE", creator=self.creator, is_primary=False,
                                   is_active=False)
        self._assert_plain_not_found(self._post(f.make_user(), "OLDONE"))

    @override_settings(CREATORS_MODE="off")
    def test_off_mode_does_not_reveal_creator_codes(self):
        self._assert_plain_not_found(self._post(f.make_user(), "TORA20"))

    def test_past_the_attempt_limit_creator_code_looks_unknown(self):
        user = f.make_user(joined_ago=73)
        for _ in range(attribution.TYPED_FAIL_LIMIT):
            self.assertEqual(self._post(user, "TORA20").json()["code"], "too_late")
        # Лимит попыток исчерпан: настоящий код неотличим от случайной строки.
        self._assert_plain_not_found(self._post(user, "TORA20"))

    def test_creator_retry_code(self):
        with mock.patch.object(CreatorReferral.objects, "create", side_effect=IntegrityError("dup")):
            response = self._post(f.make_user(), "TORA20")
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["code"], "retry")
        self.assertEqual(response.json()["kind"], "creator")

    def test_ordinary_failure_body_is_unchanged(self):
        response = self._post(f.make_user(), "NOSUCH1")
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json(), {"status": "error", "message": NOT_FOUND})
        PromoCode.objects.create(code="OLD", bonus_credits=5,
                                 expires_at=timezone.now() - timedelta(days=1))
        response = self._post(f.make_user(), "OLD")
        self.assertEqual(response.json(),
                         {"status": "error", "message": "Срок действия промокода истёк"})

    def test_empty_code_body_is_unchanged(self):
        response = self._post(f.make_user(), "  ")
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json(), {"status": "error", "message": "Введите промокод"})

    def test_failing_creators_module_keeps_ordinary_promo_working(self):
        PromoCode.objects.create(code="WELCOME", bonus_credits=25)
        with mock.patch("creators.codes.creator_code_exists", side_effect=RuntimeError("boom")):
            response = self._post(f.make_user(), "WELCOME")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["kind"], "promo")


class SuspectTests(f.CreatorsTestCase):
    def setUp(self):
        super().setUp()
        self.creator = f.make_creator(code="TORA20")
        patcher = mock.patch("creators.attribution.notify.emit")
        self.emit = patcher.start()
        self.addCleanup(patcher.stop)

    def test_clean_bind_copies_signup_evidence(self):
        user = f.make_user()
        _device(user, fingerprint="old", ip="10.0.0.1", subnet="10.0.0.0/24")
        latest = _device(user, fingerprint="fp-user", ip="10.0.0.2", subnet="10.0.0.0/24")
        SignupDevice.objects.filter(pk=latest.pk).update(
            created_at=timezone.now() + timedelta(seconds=5))
        referral = attribution.bind(user, self.creator, source="link").referral
        self.assertEqual(referral.fingerprint, "fp-user")
        self.assertEqual(referral.ip, "10.0.0.2")
        self.assertEqual(referral.subnet, "10.0.0.0/24")
        self.assertFalse(referral.suspect)
        self.assertEqual(referral.flags, {"reasons": []})
        self.emit.assert_called_once()
        self.assertEqual(self.emit.call_args.args[1], "new_referral")

    def test_no_signup_device(self):
        referral = attribution.bind(f.make_user(), self.creator, source="link").referral
        self.assertEqual((referral.fingerprint, referral.subnet, referral.ip), ("", "", None))
        self.assertFalse(referral.suspect)

    def test_same_fingerprint_as_creator(self):
        _device(self.creator.user, fingerprint="fp-1", ip="10.0.0.1")
        user = f.make_user()
        _device(user, fingerprint="fp-1", ip="10.9.9.9")
        result = attribution.bind(user, self.creator, source="link")
        # Привязка не отклонена: отказ спрятал бы схему.
        self.assertTrue(result.ok)
        self.assertTrue(result.referral.suspect)
        self.assertEqual(result.referral.flags, {"reasons": ["same_device_as_creator"]})
        self.emit.assert_not_called()

    def test_same_fingerprint_as_another_referral(self):
        first = f.make_user()
        _device(first, fingerprint="fp-2")
        self.assertFalse(attribution.bind(first, self.creator, source="link").referral.suspect)
        second = f.make_user()
        _device(second, fingerprint="fp-2")
        referral = attribution.bind(second, self.creator, source="link").referral
        self.assertTrue(referral.suspect)
        self.assertEqual(referral.flags, {"reasons": ["same_device_as_referral"]})

    def test_same_device_under_another_creator_is_a_repeat_registration(self):
        first = f.make_user()
        _device(first, fingerprint="fp-3")
        attribution.bind(first, f.make_creator(), source="link")
        second = f.make_user()
        _device(second, fingerprint="fp-3")
        referral = attribution.bind(second, self.creator, source="link").referral
        self.assertTrue(referral.suspect)
        self.assertEqual(referral.flags, {"reasons": ["repeat_registration"]})

    def test_second_account_on_the_device_of_an_existing_user(self):
        # ТЗ п.35: у человека уже есть аккаунт EsAI, он заводит второй по ссылке
        # креатора в том же браузере — новым рефералом это не считается.
        _device(f.make_user(), fingerprint="fp-4")
        user = f.make_user()
        _device(user, fingerprint="fp-4")
        self.emit.reset_mock()
        result = attribution.bind(user, self.creator, source="promo")
        self.assertTrue(result.ok)
        self.assertTrue(result.referral.suspect)
        self.assertEqual(result.referral.flags, {"reasons": ["repeat_registration"]})
        self.emit.assert_not_called()
        from .. import stats

        self.assertEqual(stats.counters(self.creator)["registrations"], 0)

    def test_device_of_a_deleted_account_still_counts_as_repeat(self):
        _device(None, fingerprint="fp-5")
        user = f.make_user()
        _device(user, fingerprint="fp-5")
        self.assertTrue(attribution.bind(user, self.creator, source="link").referral.suspect)

    def test_admin_bind_ignores_an_earlier_account_on_the_device(self):
        _device(f.make_user(), fingerprint="fp-6")
        user = f.make_user()
        _device(user, fingerprint="fp-6")
        result = attribution.bind(user, self.creator, source="admin",
                                  actor=f.make_user(superuser=True), force=True)
        self.assertFalse(result.referral.suspect)
        self.assertEqual(result.referral.flags, {"reasons": []})

    def test_same_ip_only_is_recorded_but_not_suspect(self):
        _device(self.creator.user, fingerprint="fp-creator", ip="10.0.0.1")
        user = f.make_user()
        _device(user, fingerprint="fp-user", ip="10.0.0.1")
        referral = attribution.bind(user, self.creator, source="link").referral
        self.assertFalse(referral.suspect)
        self.assertEqual(referral.flags, {"reasons": ["same_ip_as_creator"]})
        self.emit.assert_called_once()

    def test_suspect_bind_does_not_check_next_level(self):
        _device(self.creator.user, fingerprint="fp-1")
        user = f.make_user()
        _device(user, fingerprint="fp-1")
        with mock.patch("creators.attribution.stats.check_next_level") as check:
            attribution.bind(user, self.creator, source="link")
        check.assert_not_called()

    def test_clean_bind_checks_next_level(self):
        with mock.patch("creators.attribution.stats.check_next_level") as check:
            attribution.bind(f.make_user(), self.creator, source="link")
        check.assert_called_once()

    def test_failing_notification_does_not_break_the_bind(self):
        self.emit.side_effect = RuntimeError("boom")
        self.assertTrue(attribution.bind(f.make_user(), self.creator, source="link").ok)


class RepeatRegistrationTests(f.CreatorsTestCase):
    """Цикл «/delete в боте -> /start по ссылке креатора» не создаёт нового реферала."""

    TG = 700300

    def setUp(self):
        super().setUp()
        self.creator_a = f.make_creator(code="AAAA1")
        self.creator_b = f.make_creator(code="BBBB1")
        patcher = mock.patch("creators.attribution.notify.emit")
        self.emit = patcher.start()
        self.addCleanup(patcher.stop)

    def _first_account(self):
        """Человек пришёл из бота по ссылке A, а потом сделал /delete."""
        from allauth.socialaccount.models import SocialAccount

        first = f.make_user(telegram_uid=self.TG)
        result = attribution.bind(first, self.creator_a, source="bot", code_used="AAAA1")
        self.assertFalse(result.referral.suspect)
        # forget_telegram: привязка Telegram удалена, заглушка погашена, реферал остался.
        SocialAccount.objects.filter(user=first).delete()
        first.is_active = False
        first.save(update_fields=["is_active"])
        self.emit.reset_mock()
        return first

    def test_same_telegram_by_the_same_creator_link(self):
        self._first_account()
        again = f.make_user(telegram_uid=self.TG)
        result = attribution.bind(again, self.creator_a, source="bot", code_used="AAAA1")
        self.assertTrue(result.ok)
        self.assertTrue(result.referral.suspect)
        self.assertEqual(result.referral.flags, {"reasons": ["repeat_registration"]})
        self.assertEqual(result.referral.telegram_uid, str(self.TG))
        self.emit.assert_not_called()

    def test_same_telegram_by_another_creator_link(self):
        self._first_account()
        again = f.make_user(telegram_uid=self.TG)
        result = attribution.bind(again, self.creator_b, source="link", code_used="BBBB1")
        self.assertTrue(result.referral.suspect)
        self.assertEqual(result.referral.flags, {"reasons": ["repeat_registration"]})
        self.emit.assert_not_called()

    def test_typed_code_is_checked_too(self):
        self._first_account()
        again = f.make_user(telegram_uid=self.TG)
        self.assertTrue(attribution.bind(again, self.creator_b, source="promo").referral.suspect)

    def test_through_the_signup_path(self):
        self._first_account()
        again = f.make_user(telegram_uid=self.TG)
        user_services.maybe_link_referrer(_request(), again, code="AAAA1")
        referral = CreatorReferral.objects.get(user=again)
        self.assertEqual(referral.source, "bot")
        self.assertTrue(referral.suspect)

    def test_another_telegram_is_clean(self):
        self._first_account()
        other = f.make_user(telegram_uid=self.TG + 1)
        self.assertFalse(attribution.bind(other, self.creator_a, source="bot").referral.suspect)
        self.emit.assert_called_once()

    def test_user_without_telegram_is_clean(self):
        self._first_account()
        site_user = f.make_user()
        referral = attribution.bind(site_user, self.creator_a, source="link").referral
        self.assertEqual(referral.telegram_uid, "")
        self.assertFalse(referral.suspect)

    def test_was_deleted_before_flags_a_user_with_no_earlier_referral(self):
        user = f.make_user(telegram_uid=self.TG)
        with mock.patch("creators.attribution._was_deleted_before", return_value=True) as deleted:
            result = attribution.bind(user, self.creator_a, source="bot")
        deleted.assert_called_once_with(str(self.TG))
        self.assertTrue(result.referral.suspect)
        self.assertEqual(result.referral.flags, {"reasons": ["repeat_registration"]})
        self.emit.assert_not_called()

    def test_telegram_seen_under_another_account_in_the_link_log(self):
        # Человек раньше не был ничьим рефералом: след прежнего аккаунта — только
        # журнал привязок и отвязок Telegram.
        old = f.make_user()
        EventLog.objects.create(type="other", user=old, message="tg unlinked",
                                meta={"deactivated": True, "telegram_id": str(self.TG)})
        user = f.make_user(telegram_uid=self.TG)
        result = attribution.bind(user, self.creator_a, source="bot")
        self.assertTrue(result.referral.suspect)
        self.assertEqual(result.referral.flags, {"reasons": ["repeat_registration"]})
        self.emit.assert_not_called()

    def test_own_link_log_rows_and_other_telegrams_are_not_evidence(self):
        user = f.make_user(telegram_uid=self.TG)
        # Собственная привязка Telegram к этому же аккаунту — не повтор.
        EventLog.objects.create(type="other", user=user, message="linked",
                                meta={"telegram_id": str(self.TG), "status": "linked"})
        EventLog.objects.create(type="other", user=f.make_user(), message="tg unlinked",
                                meta={"deactivated": True, "telegram_id": str(self.TG + 1)})
        EventLog.objects.create(type="other", user=f.make_user(), message="no meta", meta=None)
        self.assertFalse(attribution.bind(user, self.creator_a, source="bot").referral.suspect)

    def test_failing_link_log_does_not_break_the_bind(self):
        user = f.make_user(telegram_uid=self.TG)
        with mock.patch.object(EventLog.objects, "filter", side_effect=RuntimeError("boom")):
            self.assertFalse(attribution._telegram_seen_before(str(self.TG), user.pk))
            result = attribution.bind(user, self.creator_a, source="bot")
        self.assertTrue(result.ok)
        self.assertFalse(result.referral.suspect)

    def test_was_deleted_before_is_taken_from_botapi(self):
        fake = SimpleNamespace(was_deleted_before=mock.Mock(return_value=True))
        with mock.patch.dict(sys.modules, {"botapi.services": fake}):
            self.assertTrue(attribution._was_deleted_before("700300"))
        fake.was_deleted_before.assert_called_once_with("700300")

    def test_failing_import_does_not_break_the_bind(self):
        user = f.make_user(telegram_uid=self.TG)
        # None в sys.modules — «такого модуля нет»: import бросает ImportError.
        with mock.patch.dict(sys.modules, {"botapi.services": None}):
            self.assertFalse(attribution._was_deleted_before(str(self.TG)))
            result = attribution.bind(user, self.creator_a, source="bot")
        self.assertTrue(result.ok)
        self.assertFalse(result.referral.suspect)

    def test_raising_was_deleted_before_does_not_break_the_bind(self):
        fake = SimpleNamespace(was_deleted_before=mock.Mock(side_effect=RuntimeError("boom")))
        user = f.make_user(telegram_uid=self.TG)
        with mock.patch.dict(sys.modules, {"botapi.services": fake}):
            result = attribution.bind(user, self.creator_a, source="bot")
        self.assertTrue(result.ok)
        self.assertFalse(result.referral.suspect)

    def test_admin_source_is_never_flagged(self):
        self._first_account()
        again = f.make_user(telegram_uid=self.TG)
        admin = f.make_user(superuser=True)
        with mock.patch("creators.attribution._was_deleted_before", return_value=True) as deleted:
            result = attribution.bind(again, self.creator_b, source="admin", actor=admin,
                                      force=True)
        deleted.assert_not_called()
        self.assertTrue(result.ok)
        self.assertFalse(result.referral.suspect)
        self.assertEqual(result.referral.flags, {"reasons": []})
        # Telegram id всё равно записан: он — улика для следующих привязок.
        self.assertEqual(result.referral.telegram_uid, str(self.TG))


class RebindTests(f.CreatorsTestCase):
    def setUp(self):
        super().setUp()
        self.admin = f.make_user(superuser=True)
        self.creator_a = f.make_creator(code="AAAA1")
        self.creator_b = f.make_creator(code="BBBB1")
        self.user = f.make_user(joined_ago=timedelta(days=30), paid=True)

    def test_reason_required(self):
        with self.assertRaises(CreatorsError) as ctx:
            attribution.rebind(self.user, self.creator_b, actor=self.admin, reason="")
        self.assertEqual(ctx.exception.code, "reason_required")

    def test_ends_old_and_opens_admin_binding(self):
        old = f.make_referral(self.creator_a, self.user)
        logs = AdminActionLog.objects.filter(action="referral.rebind").count()
        new = attribution.rebind(self.user, self.creator_b, actor=self.admin, reason="ошибка ссылки")
        old.refresh_from_db()
        self.assertIsNotNone(old.ended_at)
        self.assertEqual(old.end_reason, "admin_rebind")
        self.assertEqual(new.creator_id, self.creator_b.pk)
        self.assertEqual(new.source, "admin")
        self.assertEqual(new.bound_by_id, self.admin.pk)
        self.assertEqual(new.code_used, "")
        self.assertIsNone(new.ended_at)
        # Новая привязка начинается ровно там, где кончилась старая: зазора нет.
        self.assertEqual(new.bound_at, old.ended_at)
        self.assertEqual(CreatorReferral.objects.covering(self.user.pk, old.ended_at).pk, new.pk)
        self.assertEqual(CreatorReferral.objects.active_for(self.user.pk).pk, new.pk)
        self.assertEqual(AdminActionLog.objects.filter(action="referral.rebind").count(), logs + 1)
        log = AdminActionLog.objects.filter(action="referral.rebind").first()
        self.assertEqual(log.actor_id, self.admin.pk)
        self.assertEqual(log.creator_id, self.creator_b.pk)
        self.assertEqual((log.target_type, log.target_id), ("users.user", str(self.user.pk)))
        self.assertEqual(log.before, {"creator_id": self.creator_a.pk})
        # referral_id — по нему сверка I8 находит запись после слияния аккаунтов.
        self.assertEqual(log.after, {"creator_id": self.creator_b.pk, "referral_id": new.pk})
        self.assertEqual(log.reason, "ошибка ссылки")

    def test_binds_an_unbound_old_paying_user(self):
        new = attribution.rebind(self.user, self.creator_a, actor=self.admin, reason="r")
        self.assertEqual(new.source, "admin")
        log = AdminActionLog.objects.filter(action="referral.rebind").first()
        self.assertEqual(log.before, {"creator_id": None})

    def test_leaves_referred_by(self):
        referrer = f.make_user()
        self.user.referred_by = referrer
        self.user.save(update_fields=["referred_by"])
        attribution.rebind(self.user, self.creator_a, actor=self.admin, reason="r")
        self.user.refresh_from_db()
        self.assertEqual(self.user.referred_by_id, referrer.pk)
        self.assertEqual(CreatorReferral.objects.active_for(self.user.pk).creator_id,
                         self.creator_a.pk)

    def test_unbind_with_none(self):
        old = f.make_referral(self.creator_a, self.user)
        self.assertIsNone(attribution.rebind(self.user, None, actor=self.admin, reason="по просьбе"))
        old.refresh_from_db()
        self.assertEqual(old.end_reason, "admin_unbind")
        self.assertIsNone(CreatorReferral.objects.active_for(self.user.pk))
        log = AdminActionLog.objects.filter(action="referral.rebind").first()
        self.assertEqual(log.creator_id, self.creator_a.pk)
        self.assertEqual(log.after, {"creator_id": None})

    def test_unbind_without_binding_is_not_found(self):
        logs = AdminActionLog.objects.count()
        with self.assertRaises(CreatorsError) as ctx:
            attribution.rebind(self.user, None, actor=self.admin, reason="r")
        self.assertEqual(ctx.exception.code, "not_found")
        self.assertEqual(AdminActionLog.objects.count(), logs)

    def test_refusals_roll_back(self):
        old = f.make_referral(self.creator_a, self.user)
        blocked = f.make_creator(status="blocked")
        own = f.make_creator(self.user)
        logs = AdminActionLog.objects.count()
        for creator, code in ((blocked, "creator_unusable"), (own, "self")):
            with self.assertRaises(CreatorsError) as ctx:
                attribution.rebind(self.user, creator, actor=self.admin, reason="r")
            self.assertEqual(ctx.exception.code, code)
            old.refresh_from_db()
            # Старая привязка осталась действующей.
            self.assertIsNone(old.ended_at)
            self.assertEqual(old.end_reason, "")
        self.assertEqual(AdminActionLog.objects.count(), logs)

    def test_staff_user_is_refused(self):
        with self.assertRaises(CreatorsError) as ctx:
            attribution.rebind(f.make_user(staff=True), self.creator_a, actor=self.admin, reason="r")
        self.assertEqual(ctx.exception.code, "staff")

    def test_orders_before_the_rebind_stay_with_the_old_creator(self):
        bound_at = timezone.now() - timedelta(days=10)
        f.make_referral(self.creator_a, self.user, bound_at=bound_at)
        before = timezone.now() - timedelta(seconds=1)
        attribution.rebind(self.user, self.creator_b, actor=self.admin, reason="r")
        self.assertEqual(CreatorReferral.objects.covering(self.user.pk, before).creator_id,
                         self.creator_a.pk)
        self.assertEqual(CreatorReferral.objects.covering(self.user.pk, timezone.now()).creator_id,
                         self.creator_b.pk)


class ClearSuspectTests(f.CreatorsTestCase):
    def setUp(self):
        super().setUp()
        self.admin = f.make_user(superuser=True)
        self.creator = f.make_creator(code="TORA20")
        self.user = f.make_user()
        self.referral = f.make_referral(self.creator, self.user, suspect=True)
        patcher = mock.patch("creators.attribution.notify.emit")
        self.emit = patcher.start()
        self.addCleanup(patcher.stop)

    def test_reason_required(self):
        with self.assertRaises(CreatorsError) as ctx:
            attribution.clear_suspect(self.referral.pk, actor=self.admin, reason=" ")
        self.assertEqual(ctx.exception.code, "reason_required")

    def test_not_found(self):
        with self.assertRaises(CreatorsError) as ctx:
            attribution.clear_suspect(10 ** 9, actor=self.admin, reason="r")
        self.assertEqual(ctx.exception.code, "not_found")

    def test_bad_state_when_not_suspect(self):
        clean = f.make_referral(self.creator)
        with self.assertRaises(CreatorsError) as ctx:
            attribution.clear_suspect(clean.pk, actor=self.admin, reason="r")
        self.assertEqual(ctx.exception.code, "bad_state")
        self.assertEqual(ctx.exception.http, 409)
        self.assertFalse(AdminActionLog.objects.filter(action="referral.clear_suspect").exists())

    def test_flag_cleared_with_log_and_notification(self):
        with mock.patch("creators.attribution.stats.check_next_level") as check:
            result = attribution.clear_suspect(self.referral.pk, actor=self.admin,
                                               reason="проверили вручную")
        self.assertFalse(result.suspect)
        self.referral.refresh_from_db()
        self.assertFalse(self.referral.suspect)
        self.assertEqual(self.referral.flags, {"reasons": ["factory"], "cleared_by": self.admin.pk})
        log = AdminActionLog.objects.get(action="referral.clear_suspect")
        self.assertEqual(log.actor_id, self.admin.pk)
        self.assertEqual(log.creator_id, self.creator.pk)
        self.assertEqual((log.target_type, log.target_id),
                         ("creators.creatorreferral", str(self.referral.pk)))
        self.assertEqual(log.before, {"suspect": True, "reasons": ["factory"]})
        self.assertEqual(log.after, {"suspect": False, "released": 0})
        self.assertEqual(log.reason, "проверили вручную")
        # Реферал теперь считается: креатор узнаёт о нём, условия уровня перепроверяются.
        self.emit.assert_called_once()
        self.assertEqual(self.emit.call_args.args[:2], (self.creator, "new_referral"))
        self.assertIn("user_label", self.emit.call_args.kwargs)
        check.assert_called_once()

    def test_second_clear_is_bad_state(self):
        attribution.clear_suspect(self.referral.pk, actor=self.admin, reason="r")
        with self.assertRaises(CreatorsError) as ctx:
            attribution.clear_suspect(self.referral.pk, actor=self.admin, reason="r")
        self.assertEqual(ctx.exception.code, "bad_state")
        self.assertEqual(AdminActionLog.objects.filter(action="referral.clear_suspect").count(), 1)

    def test_ended_referral_is_cleared_silently(self):
        CreatorReferral.objects.filter(pk=self.referral.pk).update(
            ended_at=timezone.now(), end_reason="admin_unbind")
        with mock.patch("creators.attribution.stats.check_next_level") as check:
            attribution.clear_suspect(self.referral.pk, actor=self.admin, reason="r")
        self.emit.assert_not_called()
        check.assert_not_called()

    def test_held_commissions_stay_without_release_flag(self):
        held = f.make_commission(self.creator, buyer=self.user, status="held",
                                 reason="referral_suspect")
        fake = SimpleNamespace(release=mock.Mock())
        with mock.patch.dict(sys.modules, {"creators.commission": fake}):
            attribution.clear_suspect(self.referral.pk, actor=self.admin, reason="r")
        fake.release.assert_not_called()
        held.refresh_from_db()
        self.assertEqual(held.status, "held")

    def test_release_held_calls_the_money_service_for_suspect_rows_only(self):
        # Сервис денег (T2) подменён: здесь проверяется только, что и с чем вызвано.
        first = f.make_commission(self.creator, buyer=self.user, status="held",
                                  reason="referral_suspect")
        second = f.make_commission(self.creator, buyer=self.user, status="held",
                                   reason="referral_suspect")
        f.make_commission(self.creator, buyer=self.user, status="held", reason="creator_blocked")
        f.make_commission(self.creator, buyer=self.user, status="accrued")
        other_buyer = f.make_user()
        f.make_referral(self.creator, other_buyer, suspect=True)
        f.make_commission(self.creator, buyer=other_buyer, status="held", reason="referral_suspect")
        fake = SimpleNamespace(release=mock.Mock())
        request = object()
        with mock.patch.dict(sys.modules, {"creators.commission": fake}):
            attribution.clear_suspect(self.referral.pk, actor=self.admin, reason="чисто",
                                      release_held=True, request=request)
        self.assertEqual([call.args for call in fake.release.call_args_list],
                         [(first.pk,), (second.pk,)])
        for call in fake.release.call_args_list:
            self.assertEqual(call.kwargs, {"actor": self.admin, "reason": "чисто",
                                           "request": request})
        log = AdminActionLog.objects.get(action="referral.clear_suspect")
        self.assertEqual(log.after, {"suspect": False, "released": 2})

    def test_failing_release_rolls_everything_back(self):
        f.make_commission(self.creator, buyer=self.user, status="held", reason="referral_suspect")
        fake = SimpleNamespace(release=mock.Mock(side_effect=CreatorsError("payment_refunded")))
        with mock.patch.dict(sys.modules, {"creators.commission": fake}):
            with self.assertRaises(CreatorsError) as ctx:
                attribution.clear_suspect(self.referral.pk, actor=self.admin, reason="r",
                                          release_held=True)
        self.assertEqual(ctx.exception.code, "payment_refunded")
        self.referral.refresh_from_db()
        self.assertTrue(self.referral.suspect)
        self.assertFalse(AdminActionLog.objects.filter(action="referral.clear_suspect").exists())
        self.emit.assert_not_called()

    def test_release_held_releases_the_held_rows(self):
        """[gate] С настоящим сервисом денег (T2): held -> accrued с отметкой released."""
        try:
            from creators import commission  # noqa: F401
        except ImportError:
            self.skipTest("[gate] creators.commission (T2) ещё нет")
        held = f.make_commission(self.creator, buyer=self.user, status="held",
                                 reason="referral_suspect")
        attribution.clear_suspect(self.referral.pk, actor=self.admin, reason="чисто",
                                  release_held=True)
        held.refresh_from_db()
        self.assertEqual(held.status, "accrued")
        self.assertEqual(held.reason, "released")
        self.assertTrue(AdminActionLog.objects.filter(action="commission.release").exists())


class InvitedByTests(f.CreatorsTestCase):
    def setUp(self):
        super().setUp()
        self.creator = f.make_creator(code="TORA20", display_name="Tora")
        self.user = f.make_user()

    def test_bound_user(self):
        referral = f.make_referral(self.creator, self.user)
        self.assertEqual(attribution.invited_by(self.user),
                         {"invited_by": "Tora", "code": "TORA20", "bound_at": referral.bound_at})

    def test_unbound_user(self):
        self.assertIsNone(attribution.invited_by(self.user))
        self.assertIsNone(attribution.invited_by(None))

    def test_ended_binding_is_not_shown(self):
        referral = f.make_referral(self.creator, self.user)
        CreatorReferral.objects.filter(pk=referral.pk).update(ended_at=timezone.now())
        self.assertIsNone(attribution.invited_by(self.user))

    @override_settings(CREATORS_MODE="off")
    def test_off_mode(self):
        f.make_referral(self.creator, self.user)
        self.assertIsNone(attribution.invited_by(self.user))

    def test_never_raises(self):
        f.make_referral(self.creator, self.user)
        with mock.patch.object(CreatorReferral.objects, "active_for", side_effect=RuntimeError("x")):
            self.assertIsNone(attribution.invited_by(self.user))


class BindCommissionIndependenceTests(f.CreatorsTestCase):
    def test_bind_writes_no_money_rows(self):
        creator = f.make_creator(code="TORA20")
        attribution.bind(f.make_user(), creator, source="promo")
        self.assertFalse(CreatorCommission.objects.exists())
        self.assertFalse(TokenTransaction.objects.exists())


@override_settings(TELEGRAM_PRODUCT_BOT_TOKEN="1:x", TELEGRAM_PRODUCT_BOT_USERNAME="esai_bot")
class BotSignupTests(f.CreatorsTestCase):
    """Весь путь бота: /start с параметром -> botapi.services -> users.services."""

    TG = 700600

    def setUp(self):
        super().setUp()
        self.creator = f.make_creator(code="TORA20")

    def _start(self, **kwargs):
        from botapi.services import authenticate_telegram_user

        return authenticate_telegram_user(
            {"id": self.TG, "first_name": "Иван", "username": "ivan"}, chat_id=self.TG, **kwargs)

    def test_start_ref_code_binds_and_counts_the_arrival(self):
        user, created = self._start(ref="tora20")
        self.assertTrue(created)
        referral = CreatorReferral.objects.get(user=user)
        self.assertEqual((referral.creator_id, referral.source, referral.code_used),
                         (self.creator.pk, "bot", "TORA20"))
        self.assertEqual(referral.telegram_uid, str(self.TG))
        self.assertFalse(referral.suspect)
        user.refresh_from_db()
        self.assertIsNone(user.referred_by_id)
        self.assertEqual(CreatorClick.objects.get().device_key, f"tg:{self.TG}")

    def test_existing_bot_user_is_not_bound_by_a_later_link(self):
        user, _ = self._start()
        again, created = self._start(ref="TORA20")
        self.assertFalse(created)
        self.assertEqual(again.pk, user.pk)
        self.assertFalse(CreatorReferral.objects.exists())
        self.assertFalse(CreatorClick.objects.exists())

    def test_start_promo_code_binds_as_typed_code(self):
        user, _ = self._start(promo="TORA20")
        referral = CreatorReferral.objects.get(user=user)
        self.assertEqual(referral.source, "promo")
        self.assertFalse(PromoActivation.objects.exists())

    def test_organic_start_then_delete_then_creator_link_is_suspect(self):
        """ТЗ п.35: человек уже был в боте без креатора, /delete -> /start ref_CODE."""
        from botapi.linking import forget_telegram

        from .. import stats

        first, _ = self._start()
        self.assertFalse(CreatorReferral.objects.exists())
        self.assertEqual(forget_telegram(self.TG)["deactivated"], True)
        second, created = self._start(ref="TORA20")
        self.assertTrue(created)
        self.assertNotEqual(second.pk, first.pk)
        referral = CreatorReferral.objects.get(user=second)
        self.assertTrue(referral.suspect)
        self.assertEqual(referral.flags, {"reasons": ["repeat_registration"]})
        self.assertEqual(stats.counters(self.creator)["registrations"], 0)

    def test_delete_and_start_loop_counts_one_arrival(self):
        from botapi.linking import forget_telegram

        for _ in range(3):
            self._start(ref="TORA20")
            forget_telegram(self.TG)
        self.assertEqual(CreatorClick.objects.count(), 1)

    def test_delete_then_start_by_the_link_again_is_suspect(self):
        from botapi.linking import forget_telegram

        first, _ = self._start(ref="TORA20")
        self.assertEqual(forget_telegram(self.TG)["deactivated"], True)
        second, created = self._start(ref="TORA20")
        self.assertTrue(created)
        self.assertNotEqual(second.pk, first.pk)
        referral = CreatorReferral.objects.get(user=second)
        self.assertTrue(referral.suspect)
        self.assertIn("repeat_registration", referral.flags["reasons"])
        # Счётчик регистраций не вырос: первый аккаунт погашен, второй помечен.
        from .. import stats

        self.assertEqual(stats.counters(self.creator)["registrations"], 0)
