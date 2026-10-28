# -*- coding: utf-8 -*-
"""F29 «Возвраты»: дни активности пользователей.

- touch() пишет «был сегодня» один раз за местные сутки, кэш не пускает
  повторы в базу, и никакая ошибка учёта не роняет запрос;
- middleware отмечает авторизованный (JWT) запрос и не трогает анонимов;
- досинхронизация из истории берёт только то, что человек делал сам:
  ежедневный бонус ночной задачи активностью не считается;
- день — местная дата Бишкека: 18:00 UTC уже следующий день.
"""
from datetime import date, datetime, timedelta, timezone as dt_timezone
from io import StringIO
from unittest.mock import patch

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.core.management import CommandError, call_command
from django.test import TestCase, TransactionTestCase, override_settings
from django.urls import path
from django.utils import timezone
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.test import APIClient
from rest_framework.views import APIView
from rest_framework_simplejwt.token_blacklist.models import OutstandingToken
from rest_framework_simplejwt.tokens import AccessToken

from ai.models import AiChatSession
from audit import activity
from audit.models import ActivitySource, EventLog, UserActivityDay
from payments.models import Payment
from plans.models import TokenTransaction
from users.models import UserFeedback

TEST_CACHES = {"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache",
                           "LOCATION": "audit-activity-tests"}}

UTC = dt_timezone.utc


def _utc(y, m, d, hh=12, mm=0, ss=0):
    return datetime(y, m, d, hh, mm, ss, tzinfo=UTC)


def _days(user):
    return sorted(UserActivityDay.objects.filter(user=user).values_list("day", flat=True))


# --- маленький urlconf для middleware: свои вью, чтобы не зависеть от чужих ---

class _MeView(APIView):
    def get(self, request):
        return Response({"id": request.user.pk})


class _OpenView(APIView):
    permission_classes = [AllowAny]

    def get(self, request):
        return Response({"ok": True})


class _BrokenView(APIView):
    def get(self, request):
        return Response({"detail": "boom"}, status=500)


urlpatterns = [
    path("t/me/", _MeView.as_view()),
    path("t/open/", _OpenView.as_view()),
    path("t/broken/", _BrokenView.as_view()),
]


@override_settings(CACHES=TEST_CACHES)
class TouchTests(TestCase):
    def setUp(self):
        cache.clear()
        self.user = get_user_model().objects.create_user(email="u@example.com", password="x-12345678")

    def test_first_touch_writes_live_row_then_cache_skips_db(self):
        self.assertTrue(activity.touch(self.user))
        row = UserActivityDay.objects.get(user=self.user)
        self.assertEqual(row.day, activity.local_day())
        self.assertEqual(row.source, ActivitySource.LIVE)
        # Повтор в те же сутки: ключ в кэше есть — до базы не доходим вовсе.
        with self.assertNumQueries(0):
            self.assertFalse(activity.touch(self.user))
        self.assertEqual(UserActivityDay.objects.filter(user=self.user).count(), 1)

    def test_idempotent_even_when_cache_forgot(self):
        activity.touch(self.user)
        cache.clear()
        self.assertTrue(activity.touch(self.user))
        self.assertEqual(UserActivityDay.objects.filter(user=self.user).count(), 1)

    def test_history_row_is_not_overwritten_by_live(self):
        UserActivityDay.objects.create(user=self.user, day=activity.local_day(),
                                       source=ActivitySource.HISTORY)
        activity.touch(self.user)
        row = UserActivityDay.objects.get(user=self.user)
        self.assertEqual(row.source, ActivitySource.HISTORY)

    def test_anonymous_and_none_are_ignored(self):
        from django.contrib.auth.models import AnonymousUser

        self.assertFalse(activity.touch(None))
        self.assertFalse(activity.touch(AnonymousUser()))
        self.assertFalse(UserActivityDay.objects.exists())

    def test_db_error_never_raises_and_releases_cache_key(self):
        with patch.object(UserActivityDay.objects, "bulk_create", side_effect=RuntimeError("db down")):
            self.assertFalse(activity.touch(self.user))
        # Ключ снят — следующий запрос попробует снова и запишет.
        self.assertTrue(activity.touch(self.user))
        self.assertEqual(UserActivityDay.objects.filter(user=self.user).count(), 1)

    def test_cache_error_never_raises(self):
        with patch("audit.activity.cache.add", side_effect=ConnectionError("redis down")):
            self.assertFalse(activity.touch(self.user))
        self.assertFalse(UserActivityDay.objects.exists())

    def test_bishkek_day_boundary_is_18_utc(self):
        # 17:59:59 UTC = 23:59:59 в Бишкеке (тот же день), 18:00 UTC = полночь следующего.
        self.assertTrue(activity.touch(self.user, when=_utc(2026, 10, 27, 17, 59, 59)))
        self.assertTrue(activity.touch(self.user, when=_utc(2026, 10, 27, 18, 0, 0)))
        self.assertFalse(activity.touch(self.user, when=_utc(2026, 10, 28, 17, 0, 0)))
        self.assertEqual(_days(self.user), [date(2026, 10, 27), date(2026, 10, 28)])

    def test_cache_key_lives_until_local_midnight(self):
        with patch("audit.activity.cache.add", return_value=True) as add:
            activity.touch(self.user, when=_utc(2026, 10, 27, 17, 0, 0))  # 23:00 в Бишкеке
        key, _value = add.call_args.args
        self.assertEqual(key, f"act:{self.user.pk}:2026-10-27")
        # Час до полуночи + час запаса.
        self.assertEqual(add.call_args.kwargs["timeout"], 3600 + 3600)


@override_settings(CACHES=TEST_CACHES, ROOT_URLCONF="audit.tests_activity")
class ActivityMiddlewareTests(TransactionTestCase):
    """Без внешней транзакции, как в бою: внутри неё middleware не пишет."""

    def setUp(self):
        cache.clear()
        self.user = get_user_model().objects.create_user(email="m@example.com", password="x-12345678")
        self.client = APIClient()

    def _auth(self):
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {AccessToken.for_user(self.user)}")

    def test_middleware_is_installed_last(self):
        self.assertEqual(settings.MIDDLEWARE[-1], "audit.middleware.ActivityDayMiddleware")

    def test_authenticated_jwt_request_is_recorded_once_a_day(self):
        self._auth()
        r = self.client.get("/t/me/")
        self.assertEqual(r.status_code, 200)
        row = UserActivityDay.objects.get(user=self.user)
        self.assertEqual(row.day, activity.local_day())
        self.assertEqual(row.source, ActivitySource.LIVE)
        self.assertEqual(self.client.get("/t/me/").status_code, 200)
        self.assertEqual(UserActivityDay.objects.filter(user=self.user).count(), 1)

    def test_jwt_user_on_open_view_is_recorded_too(self):
        # Вью не требует входа, но токен прислан — человек на сайте.
        self._auth()
        self.assertEqual(self.client.get("/t/open/").status_code, 200)
        self.assertTrue(UserActivityDay.objects.filter(user=self.user).exists())

    def test_anonymous_is_ignored(self):
        self.assertEqual(self.client.get("/t/open/").status_code, 200)
        self.assertEqual(self.client.get("/t/me/").status_code, 401)
        self.assertFalse(UserActivityDay.objects.exists())

    def test_bad_token_is_ignored(self):
        self.client.credentials(HTTP_AUTHORIZATION="Bearer not-a-token")
        self.assertEqual(self.client.get("/t/open/").status_code, 401)
        self.assertFalse(UserActivityDay.objects.exists())

    def test_5xx_is_not_recorded(self):
        self._auth()
        self.assertEqual(self.client.get("/t/broken/").status_code, 500)
        self.assertFalse(UserActivityDay.objects.exists())

    def test_tracking_failure_does_not_break_response(self):
        self._auth()
        with patch("audit.middleware.touch", side_effect=RuntimeError("boom")):
            r = self.client.get("/t/me/")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json(), {"id": self.user.pk})


@override_settings(CACHES=TEST_CACHES, ROOT_URLCONF="audit.tests_activity")
class ActivityMiddlewareInsideTransactionTests(TestCase):
    def test_nothing_is_written_inside_outer_transaction(self):
        # Так выглядит любой TestCase: чужие тесты на число запросов и колбэков
        # on_commit не должны замечать учёт.
        cache.clear()
        user = get_user_model().objects.create_user(email="t@example.com", password="x-12345678")
        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION=f"Bearer {AccessToken.for_user(user)}")
        with self.captureOnCommitCallbacks() as callbacks:
            self.assertEqual(client.get("/t/me/").status_code, 200)
        self.assertEqual(callbacks, [])
        self.assertFalse(UserActivityDay.objects.exists())


@override_settings(CACHES=TEST_CACHES)
class SyncFromSourcesTests(TestCase):
    def setUp(self):
        cache.clear()
        self.user = get_user_model().objects.create_user(email="s@example.com", password="x-12345678")
        self._set(get_user_model(), self.user.pk, "date_joined", _utc(2026, 9, 1))

    @staticmethod
    def _set(model, pk, field, value):
        # created_at везде auto_now_add — ставим нужное время отдельным UPDATE.
        model.objects.filter(pk=pk).update(**{field: value})

    def _tx(self, reason, delta, when):
        tx = TokenTransaction.objects.create(user=self.user, delta=delta, reason=reason, balance_after=0)
        self._set(TokenTransaction, tx.pk, "created_at", when)

    def _token(self, when, n=1):
        OutstandingToken.objects.create(user=self.user, jti=f"jti-{when.isoformat()}-{n}", token="t",
                                        created_at=when, expires_at=when + timedelta(days=15))

    def _full_history(self):
        self._token(_utc(2026, 9, 2))
        self._token(_utc(2026, 9, 2, 20), n=2)  # 02:00 03.09 в Бишкеке
        login = EventLog.objects.create(type="login", user=self.user)
        self._set(EventLog, login.pk, "created_at", _utc(2026, 9, 4))
        other = EventLog.objects.create(type="payment", user=self.user)
        self._set(EventLog, other.pk, "created_at", _utc(2026, 9, 25))  # не вход — не считаем
        # Снятие чужой неподтверждённой почты пишется тем же типом — хозяин не заходил.
        detached = EventLog.objects.create(type="login", user=self.user,
                                           message="unproven_email_detached: x@example.com")
        self._set(EventLog, detached.pk, "created_at", _utc(2026, 9, 23))
        # Сам человек в своём запросе: чат, промокод, перевод другому.
        self._tx("chat", -5, _utc(2026, 9, 5))
        self._tx("promo", 10, _utc(2026, 9, 7))
        self._tx("transfer_out", -5, _utc(2026, 9, 8))
        # Пишет воркер или вебхук, когда результат готов / оплата прошла: день
        # строки бывает следующим, и человек «вернулся» бы, не заходя.
        self._tx("purchase", 100, _utc(2026, 9, 6))
        self._tx("vstudio_video", -40, _utc(2026, 9, 9))
        self._tx("cartoon_scene", -105, _utc(2026, 9, 18))
        self._tx("merge_video", -10, _utc(2026, 9, 19))
        # Не сам человек — ни один из этих дней не должен появиться.
        self._tx("daily_bonus", 1, _utc(2026, 9, 10))
        self._tx("welcome", 3, _utc(2026, 9, 11))
        self._tx("admin", -5, _utc(2026, 9, 12))
        self._tx("refund", -10, _utc(2026, 9, 13))
        self._tx("transfer_in", 5, _utc(2026, 9, 14))
        self._tx("referral", 3, _utc(2026, 9, 15))
        self._tx("bonus", 3, _utc(2026, 9, 16))
        self._tx("creator_credit", 10, _utc(2026, 9, 17))
        pay = Payment.objects.create(user=self.user, amount=100, currency="KGS")
        self._set(Payment, pay.pk, "created_at", _utc(2026, 9, 20))
        chat = AiChatSession.objects.create(user=self.user, title="t")
        self._set(AiChatSession, chat.pk, "created_at", _utc(2026, 9, 21))
        fb = UserFeedback.objects.create(user=self.user, message="ok")
        self._set(UserFeedback, fb.pk, "created_at", _utc(2026, 9, 22))

    EXPECTED = [date(2026, 9, d) for d in (1, 2, 3, 4, 5, 7, 8, 20, 21, 22)]

    def test_includes_user_actions_and_excludes_system_credits(self):
        self._full_history()
        added = activity.sync_from_sources()
        self.assertEqual(_days(self.user), self.EXPECTED)
        self.assertEqual(added, len(self.EXPECTED))
        self.assertEqual(set(UserActivityDay.objects.values_list("source", flat=True)),
                         {ActivitySource.HISTORY})

    def test_second_run_adds_nothing_and_keeps_live_rows(self):
        UserActivityDay.objects.create(user=self.user, day=date(2026, 9, 2), source=ActivitySource.LIVE)
        self._full_history()
        self.assertEqual(activity.sync_from_sources(), len(self.EXPECTED) - 1)
        self.assertEqual(activity.sync_from_sources(), 0)
        self.assertEqual(UserActivityDay.objects.get(user=self.user, day=date(2026, 9, 2)).source,
                         ActivitySource.LIVE)

    def test_daily_bonus_alone_is_never_activity(self):
        # Ночная задача начисляет бонус всем подряд: человек, который только
        # получал бонусы, после дня регистрации ни разу «не был».
        for d in range(2, 30):
            self._tx("daily_bonus", 1, _utc(2026, 9, d, 19))
        activity.sync_from_sources()
        self.assertEqual(_days(self.user), [date(2026, 9, 1)])

    def test_since_limits_by_local_day_start(self):
        self._full_history()
        # Начало 20.09 в Бишкеке = 19.09 18:00 UTC.
        self._token(_utc(2026, 9, 19, 17, 59, 59), n=3)  # ещё 19.09 — не берём
        self._token(_utc(2026, 9, 19, 18, 0, 0), n=4)  # уже 20.09 — берём
        self.assertEqual(activity.sync_from_sources(since=date(2026, 9, 20)), 3)
        self.assertEqual(_days(self.user), [date(2026, 9, 20), date(2026, 9, 21), date(2026, 9, 22)])

    def test_bishkek_day_boundary(self):
        self._token(_utc(2026, 10, 27, 17, 59, 59), n=1)
        self._token(_utc(2026, 10, 27, 18, 0, 0), n=2)
        activity.sync_from_sources(since=date(2026, 10, 1))
        self.assertEqual(_days(self.user), [date(2026, 10, 27), date(2026, 10, 28)])

    def test_broken_source_is_skipped_softly(self):
        self._token(_utc(2026, 9, 2))
        broken = (("missing_model", "nope.Missing", "created_at", "user", None),
                  ("missing_field", "payments.Payment", "no_such_field", "user", None))
        with patch.object(activity, "SOURCES", broken + activity.SOURCES):
            results = activity.sync_sources_detailed()
        by_name = {r["source"]: r for r in results}
        self.assertTrue(by_name["missing_model"]["error"])
        self.assertTrue(by_name["missing_field"]["error"])
        self.assertEqual(by_name["session"], {"source": "session", "found": 1, "added": 1, "error": ""})
        self.assertEqual(_days(self.user), [date(2026, 9, 1), date(2026, 9, 2)])

    def test_sync_recent_runs_at_most_every_ten_minutes(self):
        get_user_model().objects.filter(pk=self.user.pk).update(date_joined=timezone.now())
        self.assertEqual(activity.sync_recent(), 1)
        get_user_model().objects.create_user(email="later@example.com", password="x-12345678")
        self.assertIsNone(activity.sync_recent())
        self.assertEqual(UserActivityDay.objects.count(), 1)

    def test_backfill_command_reports_per_source(self):
        self._full_history()
        out = StringIO()
        call_command("backfill_activity_days", stdout=out)
        text = out.getvalue()
        self.assertIn("registration: найдено 1, добавлено 1", text)
        self.assertIn("session: найдено 2, добавлено 2", text)
        self.assertIn("credits: найдено 3, добавлено 3", text)
        self.assertIn("login: найдено 1, добавлено 1", text)
        self.assertIn(f"Итого добавлено: {len(self.EXPECTED)}", text)
        out = StringIO()
        call_command("backfill_activity_days", "--since", "2026-09-21", stdout=out)
        self.assertIn("Итого добавлено: 0", out.getvalue())
        with self.assertRaises(CommandError):
            call_command("backfill_activity_days", "--since", "21.09.2026", stdout=StringIO())
