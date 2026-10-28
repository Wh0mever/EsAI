# -*- coding: utf-8 -*-
"""F29 «Возвраты»: GET /api/manage/retention/.

Маленький набор людей, собранный руками, и для каждой цифры отчёта — что
должно получиться по определениям из спецификации. «Сегодня» зафиксировано
(28.10.2026, среда), досинхронизация из истории в этих тестах выключена,
кроме одного теста, который проверяет именно её.
"""
from datetime import date, datetime, timedelta, timezone as dt_timezone
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import AccessToken

from audit.models import ActivitySource, UserActivityDay
from payments.models import Payment

TEST_CACHES = {"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache",
                           "LOCATION": "adminapi-retention-tests"}}

URL = "/api/manage/retention/"
NOW = datetime(2026, 10, 28, 7, 0, tzinfo=dt_timezone.utc)  # 13:00 в Бишкеке
T = date(2026, 10, 28)


def d(n):
    """День «сегодня минус n»."""
    return T - timedelta(days=n)


@override_settings(CACHES=TEST_CACHES, TEST_LOGIN_EMAIL="TEST@esai.kg")
class RetentionReportTests(TestCase):
    def setUp(self):
        cache.clear()
        User = get_user_model()
        self.staff = User.objects.create_user(email="staff@example.com", password="x-12345678",
                                              is_staff=True)
        self.staff_client = APIClient()
        self.staff_client.credentials(HTTP_AUTHORIZATION=f"Bearer {AccessToken.for_user(self.staff)}")

        # A пришёл 40 дней назад, вернулся на следующий день, через 5 дней,
        # за 10 дней до сегодня и сегодня.
        self.a = self._user("a@example.com", 40, [40, 39, 35, 10, 0], live=[0])
        # B пришёл 5 дней назад и вернулся через два дня.
        self.b = self._user("b@example.com", 5, [5, 3])
        # C пришёл сегодня — новый, не вернувшийся.
        self.c = self._user("c@example.com", 0, [0], live=[0])
        # D пришёл 20 дней назад и больше не появлялся. Строка за 25 дней —
        # раньше регистрации (кривые данные) — в отчёт не попадает.
        self.d = self._user("d@example.com", 20, [25, 20])
        # E пришёл 100 дней назад и вернулся через 40 дней.
        self.e = self._user("e@example.com", 100, [100, 60])

        # Кого не считаем: сотрудник, суперпользователь, тестовый аккаунт платёжки.
        self._mark(self.staff, 10, [10, 3, 0], live=[10, 3, 0])
        self._user("root@example.com", 1, [1, 0], is_superuser=True)
        self._user("test@esai.kg", 2, [2, 0])

        # Оплаты: A — дважды, B — один раз (плюс неуспешная), у C только тестовая,
        # сотрудник платил трижды, одна оплата без пользователя.
        self._pay(self.a)
        self._pay(self.a)
        self._pay(self.b)
        self._pay(self.b, success=False)
        self._pay(self.c, is_test=True)
        for _ in range(3):
            self._pay(self.staff)
        self._pay(None)

    # --- сборка данных ---

    def _user(self, email, joined_ago, active_ago, live=(), **extra):
        joined_at = timezone.make_aware(datetime.combine(d(joined_ago), datetime.min.time())
                                        + timedelta(hours=12))
        user = get_user_model().objects.create_user(email=email, password="x-12345678",
                                                    date_joined=joined_at, **extra)
        self._mark(user, joined_ago, active_ago, live=live)
        return user

    def _mark(self, user, _joined_ago, active_ago, live=()):
        UserActivityDay.objects.bulk_create([
            UserActivityDay(user=user, day=d(n),
                            source=ActivitySource.LIVE if n in live else ActivitySource.HISTORY)
            for n in active_ago
        ])

    def _pay(self, user, success=True, is_test=False):
        Payment.objects.create(user=user, amount=100, currency="KGS", success=success, is_test=is_test)

    def _get(self, client=None, **params):
        with patch("adminapi.retention._now", return_value=NOW), \
                patch("adminapi.retention.sync_recent") as sync:
            r = (client or self.staff_client).get(URL, params)
        self.last_sync = sync
        return r

    # --- доступ ---

    def test_anonymous_gets_401(self):
        self.assertEqual(APIClient().get(URL).status_code, 401)

    def test_non_staff_gets_403(self):
        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION=f"Bearer {AccessToken.for_user(self.a)}")
        self.assertEqual(self._get(client).status_code, 403)

    # --- цифры ---

    def test_header_and_bounds(self):
        data = self._get().json()
        self.assertEqual(data["generated_at"], "2026-10-28T13:00:00+06:00")
        self.assertEqual(data["today"], "2026-10-28")
        self.assertEqual(data["days"], 30)
        # Первый день живого учёта — по всей таблице (сотрудник записан раньше всех).
        self.assertEqual(data["exact_since"], d(10).isoformat())
        self.assertEqual(data["history_since"], d(100).isoformat())
        self.assertEqual(data["users_total"], 5)

    def test_kpi_30_days(self):
        self.assertEqual(self._get().json()["kpi"], {
            "dau": 2,             # A, C
            "wau": 3,             # A, B, C
            "mau": 4,             # A, B, C, D
            # Средний DAU за 30 дней = (2 + 1 + 1 + 1 + 1) / 30 = 0.2; 0.2 / 4 = 5 %.
            "stickiness": 5.0,
            "new": 3,             # B, C, D
            "active": 4,          # A, B, C, D
            "returning": 2,       # A (после дня регистрации), B
            "returning_share": 50.0,
            "returned_ever_share": 60.0,  # A, B, E из пяти
            "returned_ever": 3,
        })

    def test_kpi_90_days(self):
        kpi = self._get(days=90).json()["kpi"]
        self.assertEqual((kpi["new"], kpi["active"], kpi["returning"], kpi["returning_share"]),
                         (4, 5, 3, 60.0))  # + A в новых, + E в активных и вернувшихся
        self.assertEqual((kpi["dau"], kpi["wau"], kpi["mau"], kpi["stickiness"]), (2, 3, 4, 5.0))

    def test_returned_within_n_days(self):
        self.assertEqual(self._get().json()["returned_within"], [
            # База: зарегистрированы не меньше дня назад — A, B, D, E; на следующий день вернулся A.
            {"days": 1, "base": 4, "returned": 1, "share": 25.0},
            # База: A, D, E; в первые 7 дней вернулся A.
            {"days": 7, "base": 3, "returned": 1, "share": 33.3},
            # База: A, E; E вернулся только на 40-й день.
            {"days": 30, "base": 2, "returned": 1, "share": 50.0},
        ])

    def test_daily(self):
        daily = self._get().json()["daily"]
        self.assertEqual(len(daily), 30)
        self.assertEqual([row["date"] for row in daily], [d(n).isoformat() for n in range(29, -1, -1)])
        by_date = {row["date"]: row for row in daily}
        self.assertEqual(by_date[d(0).isoformat()], {"date": d(0).isoformat(), "active": 2, "new": 1,
                                                     "returning": 1})
        self.assertEqual(by_date[d(3).isoformat()]["active"], 1)
        self.assertEqual(by_date[d(3).isoformat()]["returning"], 1)
        self.assertEqual((by_date[d(5).isoformat()]["new"], by_date[d(5).isoformat()]["returning"]), (1, 0))
        self.assertEqual((by_date[d(20).isoformat()]["new"], by_date[d(20).isoformat()]["returning"]),
                         (1, 0))
        # Строка D раньше регистрации отброшена; сотрудники в графике не видны.
        self.assertEqual(by_date[d(25).isoformat()]["active"], 0)
        self.assertEqual(by_date[d(10).isoformat()]["active"], 1)  # только A
        self.assertEqual(sum(row["active"] for row in daily), 6)
        self.assertEqual(len(self._get(days=90).json()["daily"]), 90)

    def test_cohorts(self):
        cohorts = self._get().json()["cohorts"]
        self.assertEqual(len(cohorts), 12)
        # От новых к старым, неделя — с понедельника: 28.10.2026 — среда.
        self.assertEqual(cohorts[0]["week_start"], "2026-10-26")
        self.assertEqual(cohorts[-1]["week_start"], "2026-08-10")
        by_week = {c["week_start"]: c for c in cohorts}
        self.assertEqual([by_week[w]["size"] for w in ("2026-10-26", "2026-10-19", "2026-10-12",
                                                       "2026-10-05", "2026-09-14")], [1, 1, 0, 1, 1])

        def cells(week):
            return [(w["k"], w["share"], w["eligible"], w["returned"]) for w in by_week[week]["weeks"]]

        # C и B: ни одна неделя после регистрации ещё не прошла — пусто.
        self.assertEqual(cells("2026-10-26"), [(k, None, 0, 0) for k in range(1, 9)])
        self.assertEqual(cells("2026-10-19"), [(k, None, 0, 0) for k in range(1, 9)])
        self.assertEqual(cells("2026-10-12"), [(k, None, 0, 0) for k in range(1, 9)])
        # D (08.10): прошли недели 1 и 2, не возвращался.
        self.assertEqual(cells("2026-10-05")[:3], [(1, 0.0, 1, 0), (2, 0.0, 1, 0), (3, None, 0, 0)])
        # A (18.09): неделя 1 — 19.09 и 23.09, неделя 5 — 18.10; неделя 6 кончается 30.10.
        self.assertEqual(cells("2026-09-14"), [
            (1, 100.0, 1, 1), (2, 0.0, 1, 0), (3, 0.0, 1, 0), (4, 0.0, 1, 0), (5, 100.0, 1, 1),
            (6, None, 0, 0), (7, None, 0, 0), (8, None, 0, 0)])
        # E зарегистрировался раньше 12 недель — в когортах его нет.
        self.assertEqual(sum(c["size"] for c in cohorts), 4)

    def test_payers(self):
        self.assertEqual(self._get().json()["payers"], {"paying": 2, "repeat": 1, "repeat_share": 50.0})

    def test_excluded_people(self):
        data = self._get().json()
        self.assertEqual(data["users_total"], 5)
        # Без настройки тестового аккаунта он — обычный человек (пришёл 2 дня
        # назад, вернулся сегодня); сотрудник и суперпользователь — нет.
        cache.clear()
        with override_settings(TEST_LOGIN_EMAIL=""):
            data = self._get().json()
        self.assertEqual(data["users_total"], 6)
        self.assertEqual((data["kpi"]["dau"], data["kpi"]["returning"]), (3, 3))

    def test_blocked_and_merged_accounts_are_not_people(self):
        # Заблокированная ферма и заглушка Telegram, слитая с аккаунтом сайта
        # (is_active=False): иначе один человек считался бы дважды.
        self._user("farm@example.com", 3, [3, 1], is_active=False)
        self._user("merged_77_tg@example.com", 30, [30, 2], is_active=False)
        data = self._get().json()
        self.assertEqual(data["users_total"], 5)
        self.assertEqual(data["kpi"]["returned_ever"], 3)

    def test_shares_round_half_up(self):
        from adminapi.retention import _share
        # round() у float дал бы 81.2 и 31.2 — плитка разошлась бы с таблицей.
        self.assertEqual(_share(13, 16), 81.3)
        self.assertEqual(_share(5, 16), 31.3)
        self.assertEqual(_share(1, 3), 33.3)
        self.assertIsNone(_share(1, 0))

    # --- параметры, форма ответа, кэш ---

    def test_days_param_fallback(self):
        for raw, expected in (("90", 90), ("30", 30), ("7", 30), ("365", 30), ("abc", 30), ("", 30)):
            with self.subTest(days=raw):
                data = self._get(days=raw).json()
                self.assertEqual(data["days"], expected)
                self.assertEqual(len(data["daily"]), expected)
        self.assertEqual(self._get().json()["days"], 30)

    def test_response_shape(self):
        data = self._get().json()
        self.assertEqual(set(data), {"generated_at", "today", "days", "exact_since", "history_since",
                                     "users_total", "kpi", "returned_within", "daily", "cohorts",
                                     "payers"})
        self.assertEqual(set(data["kpi"]), {"dau", "wau", "mau", "stickiness", "new", "active",
                                            "returning", "returning_share", "returned_ever_share",
                                            "returned_ever"})
        self.assertEqual([r["days"] for r in data["returned_within"]], [1, 7, 30])
        for r in data["returned_within"]:
            self.assertEqual(set(r), {"days", "base", "returned", "share"})
        for row in data["daily"]:
            self.assertEqual(set(row), {"date", "active", "new", "returning"})
        for c in data["cohorts"]:
            self.assertEqual(set(c), {"week_start", "size", "weeks"})
            self.assertEqual([w["k"] for w in c["weeks"]], list(range(1, 9)))
            for w in c["weeks"]:
                self.assertEqual(set(w), {"k", "share", "eligible", "returned"})
        self.assertEqual(set(data["payers"]), {"paying", "repeat", "repeat_share"})
        self.assertIsInstance(data["kpi"]["stickiness"], float)

    def test_empty_base_gives_null_shares(self):
        UserActivityDay.objects.all().delete()
        Payment.objects.all().delete()
        get_user_model().objects.filter(is_staff=False).delete()
        data = self._get().json()
        self.assertEqual(data["users_total"], 0)
        self.assertIsNone(data["exact_since"])
        self.assertIsNone(data["history_since"])
        for key in ("stickiness", "returning_share", "returned_ever_share"):
            self.assertIsNone(data["kpi"][key], key)
        self.assertTrue(all(r["share"] is None for r in data["returned_within"]))
        self.assertIsNone(data["payers"]["repeat_share"])

    def test_report_is_cached_for_five_minutes_per_days(self):
        first = self._get().json()
        self.last_sync.assert_called_once()
        UserActivityDay.objects.create(user=self.d, day=d(0))
        # Тот же days — из кэша (и без повторной досинхронизации).
        self.assertEqual(self._get().json()["kpi"], first["kpi"])
        self.last_sync.assert_not_called()
        # Другой days — свой ключ, считается заново.
        self.assertEqual(self._get(days=90).json()["kpi"]["dau"], 3)
        with patch("adminapi.retention.cache.set") as cache_set:
            cache.clear()
            self._get()
        self.assertEqual(cache_set.call_args.args[0], "adminapi:retention:30")
        self.assertEqual(cache_set.call_args.args[2], 300)


@override_settings(CACHES=TEST_CACHES, TEST_LOGIN_EMAIL="")
class RetentionSyncTests(TestCase):
    def setUp(self):
        cache.clear()
        staff = get_user_model().objects.create_user(email="staff@example.com", password="x-12345678",
                                                     is_staff=True)
        self.client = APIClient()
        self.client.force_authenticate(staff)

    def test_view_pulls_recent_days_from_history(self):
        # Человек только что зарегистрировался, живых строк ещё нет: отчёт
        # сам дотягивает последние дни из истории и видит его сегодня.
        user = get_user_model().objects.create_user(email="fresh@example.com", password="x-12345678")
        data = self.client.get(URL).json()
        self.assertTrue(UserActivityDay.objects.filter(user=user).exists())
        self.assertEqual(data["kpi"]["dau"], 1)
        self.assertEqual(data["kpi"]["new"], 1)
        self.assertIsNone(data["exact_since"])  # живых строк нет — точного учёта ещё нет
