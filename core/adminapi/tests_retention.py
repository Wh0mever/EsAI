# -*- coding: utf-8 -*-
"""F29 «Возвраты» и F30 «По направлениям»: GET /api/manage/retention/.

Маленький набор людей, собранный руками, и для каждой цифры отчёта — что
должно получиться по определениям из спецификации. «Сегодня» зафиксировано
(28.10.2026, среда), досинхронизация из истории в этих тестах выключена,
кроме одного теста, который проверяет именно её.
"""
from datetime import date, datetime, timedelta, timezone as dt_timezone
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.db import connection
from django.test import TestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.utils import timezone
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import AccessToken

from adminapi.retention import retention_report
from ai.models import AiChatMessage, AiChatSession
from audit.models import ActivitySource, UserActivityDay
from payments.models import Payment
from plans.models import TokenTransaction

TEST_CACHES = {"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache",
                           "LOCATION": "adminapi-retention-tests"}}

URL = "/api/manage/retention/"
NOW = datetime(2026, 10, 28, 7, 0, tzinfo=dt_timezone.utc)  # 13:00 в Бишкеке
T = date(2026, 10, 28)


def d(n):
    """День «сегодня минус n»."""
    return T - timedelta(days=n)


def noon(n):
    """Полдень по Бишкеку в день «сегодня минус n»."""
    return timezone.make_aware(datetime.combine(d(n), datetime.min.time()) + timedelta(hours=12))


class RetentionFixtures:
    """Сборка людей: регистрация, дни на сайте, оплаты."""

    def _user(self, email, joined_ago, active_ago, live=(), **extra):
        user = get_user_model().objects.create_user(email=email, password="x-12345678",
                                                    date_joined=noon(joined_ago), **extra)
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


@override_settings(CACHES=TEST_CACHES, TEST_LOGIN_EMAIL="TEST@esai.kg")
class RetentionReportTests(RetentionFixtures, TestCase):
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
                                     "payers", "directions"})
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
        for row in data["directions"]:
            self.assertEqual(set(row), {"key", "group", "label", "parent", "users", "generations",
                                        "per_user", "repeat", "repeat_share", "returned_direction",
                                        "returned_site", "paid", "paid_share", "active_period",
                                        "generations_period"})
            for name in ("returned_direction", "returned_site"):
                self.assertEqual([w["days"] for w in row[name]], [1, 7, 30])
                for w in row[name]:
                    self.assertEqual(set(w), {"days", "base", "returned", "share"})

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
        # Генераций нет: строки всё равно на месте, деления на ноль — null, а не 0.
        self.assertEqual(len(data["directions"]), 9)
        for row in data["directions"]:
            self.assertEqual((row["users"], row["generations"]), (0, 0))
            for key in ("per_user", "repeat_share", "paid_share"):
                self.assertIsNone(row[key], key)
            self.assertTrue(all(w["share"] is None and w["base"] == 0
                                for w in row["returned_direction"] + row["returned_site"]))

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


# Формы meta — дословно из мест списания чата: ai/handlers.py, ai/generation.py, ai/recovery.py.
TEXT_META = {"session_id": 1, "message_id": 1, "model": "openai/gpt-4o",
             "openrouter_id": "openai/gpt-4o", "total_tokens": 900, "markup_coefficient": 1.0}
# Nano Banana: рисует через обычный чат и списывается той же веткой, что и текст, — без флага.
BANANA_META = {"session_id": 1, "message_id": 1, "model": "google/gemini-2.5-flash-image",
               "openrouter_id": "google/gemini-2.5-flash-image", "total_tokens": 1300,
               "markup_coefficient": 8.0}
FLUX_META = {"session_id": 1, "message_id": 1, "model": "black-forest-labs/flux.2-pro",
             "image": True, "provider_cost_usd": 0.03}
VIDEO_META = {"session_id": 1, "message_id": 1, "model": "google/veo-3.1", "video": True,
              "duration": 8, "provider_cost_usd": 1.2}


@override_settings(CACHES=TEST_CACHES, TEST_LOGIN_EMAIL="TEST@esai.kg")
class RetentionDirectionsTests(RetentionFixtures, TestCase):
    """Блок «По направлениям»: источник — журнал кредитов, день — по Бишкеку."""

    def setUp(self):
        cache.clear()

    def _tx(self, user, reason, ago=0, meta=None, delta=-5, at=None):
        tx = TokenTransaction.objects.create(user=user, delta=delta, reason=reason, balance_after=0,
                                             meta=meta)
        # created_at — auto_now_add: нужное время ставим отдельным UPDATE.
        TokenTransaction.objects.filter(pk=tx.pk).update(created_at=at or noon(ago))
        return tx

    def _message(self, user, meta=None, attachments=None):
        session = AiChatSession.objects.create(user=user, title="t")
        return AiChatMessage.objects.create(session=session, role="assistant", content="готово",
                                            meta=meta, attachments=attachments)

    def _partial(self, message_id, required=30):
        # Не хватило баланса: в журнале остаётся только это (handlers, generation).
        return {"session_id": 1, "message_id": message_id, "partial": True, "required": required}

    def _rows(self, days=30):
        return {row["key"]: row for row in retention_report(days, now=NOW)["directions"]}

    def _full_set(self):
        """Ручной набор: на него посчитаны все поля в test_all_fields_* руками."""
        # Анна: две разных даты текста (одна с двумя запросами), студия, мультфильм,
        # картинка Nano Banana без флага. Платила дважды, успешную оплату считаем один раз.
        anna = self._user("anna@example.com", 60, [60, 40, 39, 35, 12, 0])
        self._pay(anna)
        self._pay(anna)
        self._tx(anna, "chat", 40, TEXT_META)
        self._tx(anna, "chat", 40, TEXT_META)
        self._tx(anna, "chat", 39, {**TEXT_META, "interrupted": True})
        self._tx(anna, "vstudio_video", 35, {"take": "a" * 32})
        self._tx(anna, "vstudio_video", 12, {"take": "b" * 32})
        self._tx(anna, "cartoon_scene", 12, {"scene": 1, "project": 1})
        self._tx(anna, "vstudio_image", 35, {"take": "c" * 32})
        self._tx(anna, "chat", 20, BANANA_META)

        # Борис: неуспешная и тестовая оплаты не в счёт. Видео в двух сценариях в разные
        # дни (повтор группы, но не сценария); ролик из чата — частичное списание.
        boris = self._user("boris@example.com", 20, [20, 15, 8])
        self._pay(boris, success=False)
        self._pay(boris, is_test=True)
        self._tx(boris, "chat", 20, TEXT_META)
        self._tx(boris, "chat", 8, TEXT_META)
        self._tx(boris, "cartoon_scene", 20, {"scene": 2, "project": 1})
        video = self._message(boris, meta={"model": "google/veo-3.1", "video": True})
        self._tx(boris, "chat", 10, self._partial(video.pk))
        self._tx(boris, "cartoon_keyframe", 20, {"scene": 2})
        self._tx(boris, "cartoon_character", 15, {"character": 1})

        # Вера: пришла недавно, в окнах 7 и 30 её ещё нет.
        vera = self._user("vera@example.com", 3, [3, 2, 1, 0])
        self._tx(vera, "chat", 3, TEXT_META)
        self._tx(vera, "vstudio_image", 0, {"take": "d" * 32})
        self._tx(vera, "chat", 1, VIDEO_META)

        # Глеб платил, но ничего не генерировал: в направления не попадает.
        gleb = self._user("gleb@example.com", 50, [50, 49])
        self._pay(gleb)

    def test_order_and_labels(self):
        rows = retention_report(30, now=NOW)["directions"]
        self.assertEqual(
            [(r["key"], r["group"], r["label"], r["parent"]) for r in rows],
            [("video", "video", "Видео", None),
             ("cartoon_scene", "video", "Мультстудия", "video"),
             ("vstudio_video", "video", "Видеостудия", "video"),
             ("chat_video", "video", "Чат", "video"),
             ("image", "image", "Изображения", None),
             ("cartoon_image", "image", "Мультстудия", "image"),
             ("vstudio_image", "image", "Видеостудия", "image"),
             ("chat_image", "image", "Чат", "image"),
             ("text", "text", "Текст", None)])

    def test_all_fields_text(self):
        self._full_set()
        self.assertEqual(self._rows()["text"], {
            "key": "text", "group": "text", "label": "Текст", "parent": None,
            "users": 3,           # Анна, Борис, Вера
            "generations": 6,
            "per_user": 2.0,
            "repeat": 2,          # Анна (40 и 39), Борис (20 и 8)
            "repeat_share": 66.7,
            "returned_direction": [
                {"days": 1, "base": 3, "returned": 1, "share": 33.3},   # Анна на следующий день
                {"days": 7, "base": 2, "returned": 1, "share": 50.0},   # Вера ещё не в базе
                {"days": 30, "base": 1, "returned": 1, "share": 100.0},  # Борис ещё не в базе
            ],
            "returned_site": [
                {"days": 1, "base": 3, "returned": 2, "share": 66.7},   # Анна, Вера
                {"days": 7, "base": 2, "returned": 2, "share": 100.0},  # Анна, Борис
                {"days": 30, "base": 1, "returned": 1, "share": 100.0},
            ],
            "paid": 1,            # Глеб платил, но его здесь нет
            "paid_share": 33.3,
            "active_period": 2,   # Борис (08), Вера: у Анны всё старше 30 дней
            "generations_period": 3,
        })

    def test_all_fields_video_group_and_scenarios(self):
        self._full_set()
        rows = self._rows()
        self.assertEqual(rows["video"], {
            "key": "video", "group": "video", "label": "Видео", "parent": None,
            "users": 3,
            "generations": 6,     # Анна 3, Борис 2, Вера 1
            "per_user": 2.0,
            "repeat": 2,          # Анна, Борис: у него разные дни только в сумме сценариев
            "repeat_share": 66.7,
            "returned_direction": [
                {"days": 1, "base": 3, "returned": 0, "share": 0.0},
                {"days": 7, "base": 2, "returned": 0, "share": 0.0},
                {"days": 30, "base": 1, "returned": 1, "share": 100.0},
            ],
            "returned_site": [
                {"days": 1, "base": 3, "returned": 1, "share": 33.3},   # Вера
                {"days": 7, "base": 2, "returned": 1, "share": 50.0},   # Борис
                {"days": 30, "base": 1, "returned": 1, "share": 100.0},
            ],
            "paid": 1,
            "paid_share": 33.3,
            "active_period": 3,
            "generations_period": 5,  # кроме студии Анны 35 дней назад
        })
        self.assertEqual(rows["cartoon_scene"], {
            "key": "cartoon_scene", "group": "video", "label": "Мультстудия", "parent": "video",
            "users": 2, "generations": 2, "per_user": 1.0,
            "repeat": 0, "repeat_share": 0.0,
            "returned_direction": [
                {"days": 1, "base": 2, "returned": 0, "share": 0.0},
                {"days": 7, "base": 2, "returned": 0, "share": 0.0},
                {"days": 30, "base": 0, "returned": 0, "share": None},
            ],
            "returned_site": [
                {"days": 1, "base": 2, "returned": 0, "share": 0.0},
                {"days": 7, "base": 2, "returned": 1, "share": 50.0},   # Борис на сайте 15 дней назад
                {"days": 30, "base": 0, "returned": 0, "share": None},
            ],
            "paid": 1, "paid_share": 50.0,
            "active_period": 2, "generations_period": 2,
        })
        studio = rows["vstudio_video"]
        self.assertEqual((studio["users"], studio["generations"], studio["per_user"]), (1, 2, 2.0))
        self.assertEqual((studio["repeat"], studio["repeat_share"]), (1, 100.0))
        self.assertEqual(studio["returned_direction"][2],
                         {"days": 30, "base": 1, "returned": 1, "share": 100.0})
        self.assertEqual((studio["active_period"], studio["generations_period"]), (1, 1))
        chat = rows["chat_video"]
        self.assertEqual((chat["users"], chat["generations"], chat["repeat"]), (2, 2, 0))
        self.assertEqual(chat["returned_site"], [
            {"days": 1, "base": 2, "returned": 1, "share": 50.0},   # Вера на следующий день
            {"days": 7, "base": 1, "returned": 1, "share": 100.0},  # Борис на сайте 8 дней назад
            {"days": 30, "base": 0, "returned": 0, "share": None},
        ])
        self.assertEqual((chat["paid"], chat["paid_share"]), (0, 0.0))

    def test_all_fields_image_group_and_scenarios(self):
        self._full_set()
        rows = self._rows()
        image = rows["image"]
        self.assertEqual((image["users"], image["generations"], image["per_user"]), (3, 5, 1.7))
        self.assertEqual((image["repeat"], image["repeat_share"]), (2, 66.7))  # Анна, Борис
        self.assertEqual(image["returned_direction"], [
            {"days": 1, "base": 2, "returned": 0, "share": 0.0},    # Вера начала сегодня
            {"days": 7, "base": 2, "returned": 1, "share": 50.0},   # Борис
            {"days": 30, "base": 1, "returned": 1, "share": 100.0},  # Анна
        ])
        self.assertEqual((image["paid"], image["paid_share"]), (1, 33.3))
        self.assertEqual((image["active_period"], image["generations_period"]), (3, 4))
        # Кадр и свой герой — один сценарий; разные дни значит повтор.
        frames = rows["cartoon_image"]
        self.assertEqual((frames["users"], frames["generations"], frames["repeat"]), (1, 2, 1))
        self.assertEqual(rows["vstudio_image"]["generations"], 2)
        # Картинка Nano Banana без флага в журнале — это картинка, а не текст.
        self.assertEqual((rows["chat_image"]["users"], rows["chat_image"]["generations"]), (1, 1))

    def test_days_param_moves_only_period_fields(self):
        self._full_set()
        narrow, wide = self._rows(30)["text"], self._rows(90)["text"]
        self.assertEqual((wide["active_period"], wide["generations_period"]), (3, 6))
        for key in ("users", "generations", "repeat", "returned_direction", "paid"):
            self.assertEqual(narrow[key], wide[key], key)

    def test_chat_meta_shapes(self):
        banana = "google/gemini-2.5-flash-image"
        owner = self._user("owner@example.com", 90, [])
        image_with_files = self._message(owner, attachments=[{"type": "image", "url": "/m/1.png"}])
        image_with_flag = self._message(owner, meta={"image": True})
        video_with_files = self._message(owner, attachments=[{"type": "video", "url": "/m/1.mp4"}])
        plain_answer = self._message(owner, meta={"model": "openai/gpt-4o"}, attachments=[])
        cases = (
            ("обычный ответ", TEXT_META, "text"),
            ("веб-поиск", {**TEXT_META, "model": "openai/gpt-4o:online"}, "text"),
            ("оборванный поток", {**TEXT_META, "interrupted": True}, "text"),
            ("пустая meta", None, "text"),
            ("meta не словарь", ["x"], "text"),
            ("только session_id", {"session_id": 1}, "text"),
            ("Nano Banana", BANANA_META, "chat_image"),
            ("Nano Banana, только model", {"model": banana, "message_id": 1}, "chat_image"),
            ("модель с суффиксом", {"model": f"{banana}:free"}, "chat_image"),
            ("FLUX", FLUX_META, "chat_image"),
            ("видео", VIDEO_META, "chat_video"),
            ("довоз видео", {"model": "m", "video": True, "recovered": True}, "chat_video"),
            ("довоз, не хватило", {"video": True, "recovered": True, "partial": True, "required": 9},
             "chat_video"),
            ("частичное: картинка по вложению", self._partial(image_with_files.pk), "chat_image"),
            ("частичное: картинка по флагу", self._partial(image_with_flag.pk), "chat_image"),
            ("частичное: ролик по вложению", self._partial(video_with_files.pk), "chat_video"),
            ("частичное: обычный ответ", self._partial(plain_answer.pk), "text"),
            # Человек очистил историю: сообщения нет, частичная строка ничего больше не знает.
            ("частичное: чат удалён", self._partial(10 ** 9), "text"),
        )
        for i, (name, meta, expected) in enumerate(cases):
            with self.subTest(name):
                TokenTransaction.objects.all().delete()
                user = self._user(f"shape{i}@example.com", 90, [])
                self._tx(user, "chat", 5, meta)
                rows = self._rows()
                self.assertEqual({k for k in ("text", "chat_image", "chat_video") if rows[k]["users"]},
                                 {expected})

    def test_only_generations_are_counted(self):
        user = self._user("only@example.com", 90, [])
        self._tx(user, "chat", 5, TEXT_META, delta=0)        # за неполученную картинку не взяли
        self._tx(user, "chat", 5, BANANA_META, delta=0)
        self._tx(user, "chat", 5, TEXT_META, delta=5)
        for reason in ("cartoon_voice", "cartoon_music", "cartoon_sfx", "merge_video", "stt",
                       "transfer_out", "refund", "admin"):
            self._tx(user, reason, 5)
        self.assertTrue(all(row["users"] == 0 for row in self._rows().values()))

    def test_ledger_before_28_june_is_not_counted(self):
        user = self._user("old@example.com", 200, [])
        tz = timezone.get_default_timezone()
        self._tx(user, "chat", meta=TEXT_META, at=datetime(2026, 6, 27, 23, 59, tzinfo=tz))
        self._tx(user, "chat", meta=TEXT_META, at=datetime(2026, 6, 28, 0, 1, tzinfo=tz))
        self.assertEqual(self._rows()["text"]["generations"], 1)

    def test_same_people_as_the_report(self):
        staff = get_user_model().objects.create_user(email="s@example.com", password="x-12345678",
                                                     is_staff=True)
        root = self._user("root@example.com", 9, [], is_superuser=True)
        tester = self._user("test@esai.kg", 9, [])
        blocked = self._user("farm@example.com", 9, [], is_active=False)
        for user in (staff, root, tester, blocked):
            self._tx(user, "chat", 3, TEXT_META)
            self._tx(user, "vstudio_video", 3)
        self.assertTrue(all(row["users"] == 0 for row in self._rows().values()))

    def test_same_day_is_not_a_repeat_and_day_is_local(self):
        user = self._user("zone@example.com", 40, [])
        # Разные дни UTC, один день Бишкека (21.10, 01:00 и 11:00) — не повтор.
        self._tx(user, "vstudio_image", at=datetime(2026, 10, 20, 19, 0, tzinfo=dt_timezone.utc))
        self._tx(user, "vstudio_image", at=datetime(2026, 10, 21, 5, 0, tzinfo=dt_timezone.utc))
        # Один день UTC, разные дни Бишкека (23.10 23:30 и 24.10 00:30) — повтор.
        self._tx(user, "chat", meta=TEXT_META, at=datetime(2026, 10, 23, 17, 30, tzinfo=dt_timezone.utc))
        self._tx(user, "chat", meta=TEXT_META, at=datetime(2026, 10, 23, 18, 30, tzinfo=dt_timezone.utc))
        rows = self._rows()
        self.assertEqual((rows["vstudio_image"]["repeat"], rows["vstudio_image"]["generations"]), (0, 2))
        self.assertEqual(rows["text"]["repeat"], 1)

    def test_window_base_and_edges(self):
        # Первая генерация ровно 7 дней назад: окно целиком прошло, сегодня — его последний день.
        edge = self._user("edge@example.com", 40, [7, 0])
        self._tx(edge, "chat", 7, TEXT_META)
        self._tx(edge, "chat", 0, TEXT_META)
        # 8 дней назад: сегодня уже за окном, в базе есть, но не вернулся. На сайт — тоже.
        late = self._user("late@example.com", 40, [8, 0])
        self._tx(late, "chat", 8, TEXT_META)
        self._tx(late, "chat", 0, TEXT_META)
        # 6 дней назад: неделя ещё не прошла — в базе 7 дней его нет, хотя он вернулся.
        fresh = self._user("fresh@example.com", 40, [6, 5])
        self._tx(fresh, "chat", 6, TEXT_META)
        self._tx(fresh, "chat", 5, TEXT_META)
        row = self._rows()["text"]
        self.assertEqual(row["returned_direction"][1], {"days": 7, "base": 2, "returned": 1, "share": 50.0})
        self.assertEqual(row["returned_site"][1], {"days": 7, "base": 2, "returned": 1, "share": 50.0})
        self.assertEqual(row["returned_direction"][0], {"days": 1, "base": 3, "returned": 1, "share": 33.3})
        self.assertEqual(row["returned_direction"][2]["base"], 0)

    def test_same_day_activity_is_not_a_return(self):
        # Был на сайте только в день первой генерации — не вернулся.
        user = self._user("once@example.com", 40, [10])
        self._tx(user, "chat", 10, TEXT_META)
        self.assertEqual(self._rows()["text"]["returned_site"][1]["returned"], 0)

    def test_no_query_per_row(self):
        self._full_set()
        with CaptureQueriesContext(connection) as before:
            retention_report(30, now=NOW)
        anna = get_user_model().objects.get(email="anna@example.com")
        for i in range(40):
            self._tx(anna, "chat", i, TEXT_META)
            self._tx(anna, "chat", i, BANANA_META)
            self._tx(anna, "chat", i, self._partial(self._message(anna, meta={"image": True}).pk))
        with CaptureQueriesContext(connection) as after:
            retention_report(30, now=NOW)
        self.assertEqual(len(after), len(before))

    def test_report_is_served_from_the_shared_cache(self):
        user = self._user("cached@example.com", 40, [10])
        self._tx(user, "chat", 10, TEXT_META)
        staff = get_user_model().objects.create_user(email="s2@example.com", password="x-12345678",
                                                     is_staff=True)
        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION=f"Bearer {AccessToken.for_user(staff)}")

        def text_generations(days=30):
            with patch("adminapi.retention._now", return_value=NOW), patch("adminapi.retention.sync_recent"):
                rows = client.get(URL, {"days": days}).json()["directions"]
            return next(r["generations"] for r in rows if r["key"] == "text")

        self.assertEqual(text_generations(), 1)
        self._tx(user, "chat", 9, TEXT_META)
        self.assertEqual(text_generations(), 1)    # тот же ключ — из кэша
        self.assertEqual(text_generations(90), 2)  # другой days — считается заново


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
