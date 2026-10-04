"""Участие в программе: заявка, одобрение, уровень, блокировка, правка уровней.

Здесь только то, чем владеет сам модуль program. Как блокировка и уровень
влияют на начисление, вывод и привязку — проверяют тесты этих модулей.
"""
from decimal import Decimal
from unittest import mock

from django.contrib.auth import get_user_model
from django.db import IntegrityError
from django.test import RequestFactory

from audit.models import AdminActionLog
from users.models import Notification

from .. import access, levels, program
from ..errors import CreatorsError
from ..models import Creator, CreatorApplication, CreatorCode, CreatorLevel
from . import factories as f


def app_data(**over):
    data = {
        "name": "  Tora  ", "telegram": "@tora", "country": "Кыргызстан",
        "instagram_url": "https://instagram.com/tora", "tiktok_url": "", "youtube_url": "",
        "other_links": [], "followers": 1200, "occupation": "Снимаю видео про ИИ",
        "motivation": "Хочу зарабатывать на своей аудитории",
        "samples": ["https://youtu.be/abc"], "lang": "en",
    }
    data.update(over)
    return data


def make_application(user=None, *, status="new", **over) -> CreatorApplication:
    """Заявка напрямую через ORM (без сервиса) — исходное состояние для тестов решений."""
    fields = {"name": "Tora", "telegram": "@tora", "country": "KG",
              "instagram_url": "https://instagram.com/tora", "occupation": "x",
              "motivation": "y", "lang": "ru"}
    fields.update(over)
    return CreatorApplication.objects.create(user=user or f.make_user(), status=status, **fields)


def _logs(action):
    return AdminActionLog.objects.filter(action=action)


class ProgramTestCase(f.CreatorsTestCase):
    def setUp(self):
        super().setUp()
        self.staff = f.make_user(staff=True)
        self.boss = f.make_user(superuser=True)
        patcher = mock.patch("botapi.tasks.notify")
        self.tg = patcher.start()
        self.addCleanup(patcher.stop)

    def assertRefused(self, code, http, call, *args, **kwargs):
        with self.assertRaises(CreatorsError) as caught:
            call(*args, **kwargs)
        self.assertEqual((caught.exception.code, caught.exception.http), (code, http))
        return caught.exception


# -------------------------------------------------------------------- заявка

class SubmitApplicationTests(ProgramTestCase):
    def setUp(self):
        super().setUp()
        self.user = f.make_user()

    def test_creates_an_open_application(self):
        request = RequestFactory().post("/", REMOTE_ADDR="203.0.113.7")
        application = program.submit_application(self.user, app_data(
            other_links=[" https://vk.com/tora ", ""], youtube_url="HTTPS://youtube.com/@tora"),
            request=request)
        application.refresh_from_db()
        self.assertEqual(application.user, self.user)
        self.assertEqual(application.status, "new")
        self.assertEqual(application.name, "Tora")
        self.assertEqual(application.telegram, "@tora")
        self.assertEqual(application.instagram_url, "https://instagram.com/tora")
        self.assertEqual(application.youtube_url, "HTTPS://youtube.com/@tora")
        self.assertEqual(application.other_links, ["https://vk.com/tora"])
        self.assertEqual(application.samples, ["https://youtu.be/abc"])
        self.assertEqual(application.followers, 1200)
        self.assertEqual(application.lang, "en")
        self.assertEqual(application.ip, "203.0.113.7")
        self.assertIsNone(application.decided_at)
        # Заявка — не участие: креатора нет, журнал администратора пуст.
        self.assertFalse(Creator.objects.filter(user=self.user).exists())
        self.assertEqual(AdminActionLog.objects.count(), 0)

    def test_unknown_language_falls_back_to_russian(self):
        for lang in ("de", "", None, 5):
            user = f.make_user()
            self.assertEqual(program.submit_application(user, app_data(lang=lang)).lang, "ru")
        self.assertEqual(program.submit_application(f.make_user(), app_data(lang="KG")).lang, "kg")

    def test_followers_as_a_string_of_digits(self):
        self.assertEqual(program.submit_application(
            self.user, app_data(followers="15000")).followers, 15000)

    def test_required_fields(self):
        error = self.assertRefused("validation", 400, program.submit_application, self.user, {})
        self.assertEqual(set(error.extra["fields"]),
                         {"name", "telegram", "country", "occupation", "motivation", "followers"})
        error = self.assertRefused("validation", 400, program.submit_application, self.user,
                                   app_data(name="   ", motivation=None))
        self.assertEqual(set(error.extra["fields"]), {"name", "motivation"})
        self.assertEqual(CreatorApplication.objects.count(), 0)

    def test_field_limits(self):
        cases = {
            "name": "я" * 121, "telegram": "t" * 65, "country": "c" * 65,
            "occupation": "о" * 2001, "motivation": "м" * 2001,
            "instagram_url": "https://instagram.com/" + "a" * 300,
            "tiktok_url": "tiktok.com/@tora", "youtube_url": "javascript:alert(1)",
            "followers": -1,
            "other_links": [f"https://example.com/{n}" for n in range(6)],
            "samples": [f"https://example.com/{n}" for n in range(11)],
        }
        for name, value in cases.items():
            error = self.assertRefused("validation", 400, program.submit_application,
                                       self.user, app_data(**{name: value}))
            self.assertEqual(set(error.extra["fields"]), {name}, name)
        for name, value in (("followers", "много"), ("followers", 1.5), ("followers", True),
                            ("other_links", "https://vk.com/tora"), ("samples", ["ftp://x.com/a"]),
                            ("samples", [{"url": "https://x.com"}]), ("name", ["Tora"])):
            error = self.assertRefused("validation", 400, program.submit_application,
                                       self.user, app_data(**{name: value}))
            self.assertEqual(set(error.extra["fields"]), {name}, (name, value))
        self.assertEqual(CreatorApplication.objects.count(), 0)

    def test_limits_are_inclusive(self):
        application = program.submit_application(self.user, app_data(
            name="я" * 120, occupation="о" * 2000, followers=0,
            other_links=[f"https://example.com/{n}" for n in range(5)],
            samples=[f"https://example.com/{n}" for n in range(10)]))
        self.assertEqual(len(application.name), 120)
        self.assertEqual(len(application.other_links), 5)
        self.assertEqual(len(application.samples), 10)

    def test_at_least_one_social_link(self):
        self.assertRefused("links_required", 400, program.submit_application, self.user,
                           app_data(instagram_url="", other_links=[]))
        # Примеры работ соцсетью не считаются.
        self.assertRefused("links_required", 400, program.submit_application, self.user,
                           app_data(instagram_url="", samples=["https://youtu.be/abc"]))
        for field in ("tiktok_url", "youtube_url"):
            program.submit_application(f.make_user(), app_data(
                instagram_url="", **{field: "https://example.com/tora"}))
        program.submit_application(self.user, app_data(
            instagram_url="", other_links=["https://vk.com/tora"]))

    def test_one_open_application(self):
        program.submit_application(self.user, app_data())
        self.assertRefused("application_open", 409, program.submit_application,
                           self.user, app_data())
        self.assertEqual(CreatorApplication.objects.filter(user=self.user).count(), 1)

    def test_race_on_the_unique_index_is_application_open(self):
        with mock.patch("creators.program.CreatorApplication.objects.create",
                        side_effect=IntegrityError("creators_app_one_open")):
            self.assertRefused("application_open", 409, program.submit_application,
                               self.user, app_data())
        # Транзакция после отказа жива.
        self.assertEqual(program.submit_application(self.user, app_data()).status, "new")

    def test_reapply_after_rejection(self):
        first = program.submit_application(self.user, app_data())
        program.reject_application(first.pk, actor=self.staff, reason="мало подписчиков")
        second = program.submit_application(self.user, app_data(followers=5000))
        self.assertNotEqual(first.pk, second.pk)
        self.assertEqual(second.status, "new")

    def test_blocked_until_unblocked(self):
        first = program.submit_application(self.user, app_data())
        program.reject_application(first.pk, actor=self.boss, reason="спам", block=True)
        self.assertRefused("apply_blocked", 403, program.submit_application,
                           self.user, app_data())
        program.unblock_application(first.pk, actor=self.boss, reason="ошиблись")
        self.assertEqual(program.submit_application(self.user, app_data()).status, "new")

    def test_already_creator(self):
        f.make_creator(self.user)
        self.assertRefused("already_creator", 409, program.submit_application,
                           self.user, app_data())
        blocked = f.make_creator(status="blocked").user
        self.assertRefused("already_creator", 409, program.submit_application,
                           blocked, app_data())

    def test_no_user(self):
        self.assertRefused("no_user", 400, program.submit_application, None, app_data())
        self.assertRefused("no_user", 400, program.submit_application,
                           get_user_model()(), app_data())


# ---------------------------------------------------------------- одобрение

class ApproveApplicationTests(ProgramTestCase):
    def setUp(self):
        super().setUp()
        self.application = make_application(name="Tora", lang="en")
        self.user = self.application.user

    def test_without_a_level_nothing_happens(self):
        for missing in ("", None, "   "):
            with self.assertNumQueries(0):
                error = self.assertRefused("validation", 400, program.approve_application,
                                           self.application.pk, actor=self.boss,
                                           level_key=missing)
            self.assertEqual(error.extra["fields"], {"level": "Выберите уровень"})
        with self.assertRaises(TypeError):
            # Значения по умолчанию у уровня нет: его обязан выбрать человек.
            program.approve_application(self.application.pk, actor=self.boss)
        self.application.refresh_from_db()
        self.assertEqual(self.application.status, "new")
        self.assertFalse(Creator.objects.exists())
        self.assertEqual(AdminActionLog.objects.count(), 0)

    def test_approve_creates_the_creator_with_exactly_that_level(self):
        with self.captureOnCommitCallbacks(execute=True):
            creator = program.approve_application(self.application.pk, actor=self.staff,
                                                  level_key="creator")
        creator.refresh_from_db()
        self.assertEqual(creator.user, self.user)
        self.assertEqual(creator.level.key, "creator")
        self.assertEqual(creator.status, "active")
        self.assertEqual(creator.display_name, "Tora")
        self.assertEqual(creator.lang, "en")
        self.assertEqual(creator.application, self.application)
        self.assertEqual(creator.payout_address, "")
        # Промокод придумывает сам креатор — при одобрении его нет.
        self.assertFalse(CreatorCode.objects.exists())

        self.application.refresh_from_db()
        self.assertEqual(self.application.status, "approved")
        self.assertEqual(self.application.decided_by, self.staff)
        self.assertIsNotNone(self.application.decided_at)

        row = _logs("application.approve").get()
        self.assertEqual(row.actor, self.staff)
        self.assertEqual(row.creator, creator)
        self.assertEqual((row.target_type, row.target_id),
                         ("creators.creatorapplication", str(self.application.pk)))
        self.assertEqual(row.after["level"], "creator")

        notification = Notification.objects.get()
        self.assertEqual(notification.title, "Application approved")
        self.assertIn("Level: CREATOR, commission 10%", notification.body)
        self.assertEqual(list(notification.recipients.all()), [self.user])

    def test_non_base_level_needs_a_superuser(self):
        self.assertRefused("superuser_required", 403, program.approve_application,
                           self.application.pk, actor=self.staff, level_key="ambassador")
        self.application.refresh_from_db()
        self.assertEqual(self.application.status, "new")
        self.assertFalse(Creator.objects.exists())
        self.assertEqual(AdminActionLog.objects.count(), 0)

        creator = program.approve_application(self.application.pk, actor=self.boss,
                                              level_key="ambassador")
        self.assertEqual(creator.level.key, "ambassador")
        self.assertEqual(_logs("application.approve").get().after["level"], "ambassador")

    def test_unknown_level(self):
        self.assertRefused("level_unknown", 400, program.approve_application,
                           self.application.pk, actor=self.boss, level_key="legend")
        self.assertFalse(Creator.objects.exists())

    def test_only_a_new_application(self):
        program.approve_application(self.application.pk, actor=self.staff, level_key="creator")
        self.assertRefused("bad_state", 409, program.approve_application,
                           self.application.pk, actor=self.staff, level_key="creator")
        rejected = make_application(status="rejected")
        self.assertRefused("bad_state", 409, program.approve_application,
                           rejected.pk, actor=self.staff, level_key="creator")
        self.assertEqual(Creator.objects.count(), 1)
        self.assertEqual(_logs("application.approve").count(), 1)

    def test_already_creator(self):
        f.make_creator(self.user, logged=False)
        self.assertRefused("already_creator", 409, program.approve_application,
                           self.application.pk, actor=self.staff, level_key="creator")
        self.application.refresh_from_db()
        self.assertEqual(self.application.status, "new")

    def test_not_found(self):
        self.assertRefused("not_found", 404, program.approve_application,
                           999_999, actor=self.staff, level_key="creator")
        self.assertRefused("not_found", 404, program.approve_application,
                           "abc", actor=self.staff, level_key="creator")

    def test_deactivated_account_is_not_approved(self):
        get_user_model().objects.filter(pk=self.user.pk).update(is_active=False)
        self.assertRefused("no_user", 400, program.approve_application,
                           self.application.pk, actor=self.staff, level_key="creator")
        self.assertFalse(Creator.objects.exists())

    def test_failed_log_rolls_the_approval_back(self):
        with mock.patch("creators.program.log_admin_action", side_effect=RuntimeError("log")):
            with self.assertRaises(RuntimeError):
                program.approve_application(self.application.pk, actor=self.staff,
                                            level_key="creator")
        self.application.refresh_from_db()
        self.assertEqual(self.application.status, "new")
        self.assertFalse(Creator.objects.exists())


class RejectApplicationTests(ProgramTestCase):
    def setUp(self):
        super().setUp()
        self.application = make_application(lang="kg")
        self.user = self.application.user

    def test_reject(self):
        with self.captureOnCommitCallbacks(execute=True):
            application = program.reject_application(self.application.pk, actor=self.staff,
                                                     reason="  Мало подписчиков ")
        application.refresh_from_db()
        self.assertEqual(application.status, "rejected")
        self.assertEqual(application.reject_reason, "Мало подписчиков")
        self.assertEqual(application.decided_by, self.staff)
        self.assertIsNotNone(application.decided_at)
        self.assertFalse(Creator.objects.exists())

        row = _logs("application.reject").get()
        self.assertEqual((row.actor, row.target_id, row.reason),
                         (self.staff, str(application.pk), "Мало подписчиков"))
        self.assertEqual((row.before, row.after), ({"status": "new"}, {"status": "rejected"}))
        self.assertIsNone(row.creator)

        # Кабинета у человека нет — уведомление идёт ему напрямую, на языке заявки.
        notification = Notification.objects.get()
        self.assertEqual(notification.title, "Өтүнмө четке кагылды")
        self.assertTrue(notification.body.endswith("Мало подписчиков"))
        self.assertEqual(list(notification.recipients.all()), [self.user])
        self.assertEqual(self.tg.call_args.args[:2], (self.user, "creator"))

    def test_reject_without_a_reason(self):
        application = program.reject_application(self.application.pk, actor=self.staff)
        self.assertEqual((application.status, application.reject_reason), ("rejected", ""))

    def test_block_needs_a_superuser(self):
        self.assertRefused("superuser_required", 403, program.reject_application,
                           self.application.pk, actor=self.staff, reason="спам", block=True)
        self.application.refresh_from_db()
        self.assertEqual(self.application.status, "new")
        self.assertEqual(AdminActionLog.objects.count(), 0)

    def test_block_by_a_superuser(self):
        application = program.reject_application(self.application.pk, actor=self.boss,
                                                 reason="спам", block=True)
        self.assertEqual(application.status, "blocked")
        row = _logs("application.block").get()
        self.assertEqual((row.actor, row.target_type, row.target_id, row.after),
                         (self.boss, "creators.creatorapplication", str(application.pk),
                          {"status": "blocked"}))
        self.assertEqual(_logs("application.reject").count(), 0)

    def test_string_false_is_not_a_block(self):
        application = program.reject_application(self.application.pk, actor=self.staff,
                                                 block="false")
        self.assertEqual(application.status, "rejected")

    def test_only_a_new_application(self):
        program.reject_application(self.application.pk, actor=self.staff)
        self.assertRefused("bad_state", 409, program.reject_application,
                           self.application.pk, actor=self.staff)
        self.assertRefused("bad_state", 409, program.reject_application,
                           self.application.pk, actor=self.boss, block=True)
        self.assertRefused("not_found", 404, program.reject_application,
                           999_999, actor=self.staff)
        self.assertEqual(_logs("application.reject").count(), 1)


class UnblockApplicationTests(ProgramTestCase):
    def setUp(self):
        super().setUp()
        self.application = make_application()
        program.reject_application(self.application.pk, actor=self.boss, reason="спам",
                                   block=True)

    def test_unblock(self):
        other_boss = f.make_user(superuser=True)
        with self.captureOnCommitCallbacks(execute=True):
            application = program.unblock_application(self.application.pk, actor=other_boss,
                                                      reason="заблокировали по ошибке")
        application.refresh_from_db()
        self.assertEqual(application.status, "rejected")
        self.assertEqual(application.decided_by, other_boss)
        row = _logs("application.unblock").get()
        self.assertEqual((row.before, row.after, row.reason),
                         ({"status": "blocked"}, {"status": "rejected"},
                          "заблокировали по ошибке"))
        # Уведомления о снятии запрета нет.
        self.assertEqual(Notification.objects.count(), 0)
        # Человек снова может подать заявку.
        self.assertEqual(program.submit_application(application.user, app_data()).status, "new")

    def test_reason_is_required(self):
        for reason in ("", "   ", None):
            self.assertRefused("reason_required", 400, program.unblock_application,
                               self.application.pk, actor=self.boss, reason=reason)
        self.application.refresh_from_db()
        self.assertEqual(self.application.status, "blocked")

    def test_only_a_blocked_application(self):
        program.unblock_application(self.application.pk, actor=self.boss, reason="ошибка")
        self.assertRefused("bad_state", 409, program.unblock_application,
                           self.application.pk, actor=self.boss, reason="ещё раз")
        self.assertRefused("bad_state", 409, program.unblock_application,
                           make_application().pk, actor=self.boss, reason="x")
        self.assertRefused("not_found", 404, program.unblock_application,
                           999_999, actor=self.boss, reason="x")


# ------------------------------------------------------------------ креатор

class SetLangTests(ProgramTestCase):
    def test_set_lang(self):
        creator = f.make_creator()
        before = AdminActionLog.objects.count()
        for lang in ("en", "kg", "ru", "EN"):
            self.assertIs(program.set_lang(creator, lang), creator)
            self.assertEqual(Creator.objects.get(pk=creator.pk).lang, lang.lower())
            self.assertEqual(creator.lang, lang.lower())
        # Свой язык креатор меняет сам — в журнал администратора это не идёт.
        self.assertEqual(AdminActionLog.objects.count(), before)

    def test_unknown_language(self):
        creator = f.make_creator(lang="en")
        for lang in ("de", "", None):
            error = self.assertRefused("validation", 400, program.set_lang, creator, lang)
            self.assertIn("lang", error.extra["fields"])
        self.assertEqual(Creator.objects.get(pk=creator.pk).lang, "en")


class SetLevelTests(ProgramTestCase):
    def setUp(self):
        super().setUp()
        self.creator = f.make_creator(level="creator_pro")
        Creator.objects.filter(pk=self.creator.pk).update(next_level_notified="ambassador")

    def test_level_up(self):
        with self.captureOnCommitCallbacks(execute=True):
            creator = program.set_level(self.creator, "ambassador", actor=self.boss,
                                        reason="условия выполнены")
        fresh = Creator.objects.get(pk=self.creator.pk)
        self.assertEqual(fresh.level.key, "ambassador")
        # Уведомление «условия выполнены» относилось к прежнему уровню.
        self.assertEqual(fresh.next_level_notified, "")
        self.assertEqual(creator.level.key, "ambassador")
        # Объект, который передал вызывающий, тоже обновлён.
        self.assertEqual(self.creator.level.key, "ambassador")
        self.assertEqual(self.creator.next_level_notified, "")

        row = _logs("creator.level_change").get()
        self.assertEqual((row.actor, row.creator, row.reason),
                         (self.boss, fresh, "условия выполнены"))
        self.assertEqual((row.target_type, row.target_id),
                         ("creators.creator", str(fresh.pk)))
        self.assertEqual(row.before, {"level": "creator_pro", "percent": "15.00"})
        self.assertEqual(row.after, {"level": "ambassador", "percent": "20.00"})

        notification = Notification.objects.get()
        self.assertEqual(notification.title, "Уровень изменён")
        self.assertEqual(notification.body, "Ваш уровень: AMBASSADOR. Комиссия: 20%.")

    def test_level_down(self):
        creator = program.set_level(self.creator, "creator", actor=self.boss)
        self.assertEqual(creator.level.percent, Decimal("10.00"))
        self.assertEqual(Creator.objects.get(pk=self.creator.pk).level.key, "creator")
        self.assertEqual(_logs("creator.level_change").get().after,
                         {"level": "creator", "percent": "10.00"})

    def test_same_level_is_refused(self):
        self.assertRefused("bad_state", 409, program.set_level, self.creator, "creator_pro",
                           actor=self.boss)
        self.assertEqual(_logs("creator.level_change").count(), 0)
        self.assertEqual(Creator.objects.get(pk=self.creator.pk).next_level_notified,
                         "ambassador")

    def test_unknown_level(self):
        self.assertRefused("level_unknown", 400, program.set_level, self.creator, "legend",
                           actor=self.boss)
        self.assertRefused("level_unknown", 400, program.set_level, self.creator, "",
                           actor=self.boss)

    def test_unknown_creator(self):
        self.assertRefused("not_found", 404, program.set_level, Creator(pk=999_999),
                           "creator", actor=self.boss)

    def test_blocked_creator_keeps_a_manageable_level(self):
        blocked = f.make_creator(status="blocked")
        self.assertEqual(program.set_level(blocked, "creator_pro", actor=self.boss).level.key,
                         "creator_pro")

    def test_log_matches_the_level_after_several_changes(self):
        # Сверка I9: уровень креатора равен after.level последней записи журнала.
        program.set_level(self.creator, "ambassador_pro", actor=self.boss)
        program.set_level(self.creator, "creator", actor=self.boss)
        latest = AdminActionLog.objects.filter(
            creator=self.creator,
            action__in=["creator.level_change", "application.approve"]).first()
        self.assertEqual(latest.after["level"],
                         Creator.objects.get(pk=self.creator.pk).level.key)


class BlockTests(ProgramTestCase):
    def setUp(self):
        super().setUp()
        self.creator = f.make_creator(lang="en")
        self.user = self.creator.user

    def _fresh_user(self):
        return get_user_model().objects.get(pk=self.user.pk)

    def test_block(self):
        self.assertTrue(access.has_paid_access(self._fresh_user()))
        creator = program.block(self.creator, actor=self.boss, reason="  накрутка ")
        fresh = Creator.objects.get(pk=self.creator.pk)
        self.assertEqual(fresh.status, "blocked")
        self.assertIsNotNone(fresh.blocked_at)
        self.assertEqual(fresh.blocked_reason, "накрутка")
        self.assertEqual((creator.status, self.creator.status), ("blocked", "blocked"))

        row = _logs("creator.block").get()
        self.assertEqual((row.actor, row.creator, row.reason), (self.boss, fresh, "накрутка"))
        self.assertEqual((row.before, row.after),
                         ({"status": "active"}, {"status": "blocked"}))
        self.assertEqual(_logs("withdrawal.reject").count(), 0)
        # Доступ к платным моделям пропадает со следующего запроса.
        self.assertFalse(access.has_paid_access(self._fresh_user()))

    def test_reason_is_required(self):
        for reason in ("", "  ", None):
            self.assertRefused("reason_required", 400, program.block, self.creator,
                               actor=self.boss, reason=reason)
        self.assertEqual(Creator.objects.get(pk=self.creator.pk).status, "active")

    def test_already_blocked(self):
        program.block(self.creator, actor=self.boss, reason="накрутка")
        self.assertRefused("bad_state", 409, program.block, self.creator, actor=self.boss,
                           reason="ещё раз")
        self.assertEqual(_logs("creator.block").count(), 1)

    def test_unknown_creator(self):
        self.assertRefused("not_found", 404, program.block, Creator(pk=999_999),
                           actor=self.boss, reason="x")

    def test_open_withdrawal_is_closed_with_its_own_log_row(self):
        for status in ("review", "approved"):
            creator = f.make_creator(lang="en")
            withdrawal = f.make_withdrawal(creator, "48.50", status=status)
            before_rows = _logs("withdrawal.reject").count()
            with self.captureOnCommitCallbacks(execute=True):
                program.block(creator, actor=self.boss, reason="накрутка")

            withdrawal.refresh_from_db()
            self.assertEqual(withdrawal.status, "rejected", status)
            self.assertEqual(withdrawal.reject_reason, "creator_blocked")
            self.assertEqual(withdrawal.rejected_by, self.boss)
            self.assertIsNotNone(withdrawal.rejected_at)
            self.assertEqual(withdrawal.txid, "")

            self.assertEqual(_logs("withdrawal.reject").count(), before_rows + 1)
            row = _logs("withdrawal.reject").first()
            self.assertEqual((row.actor, row.creator), (self.boss, creator))
            self.assertEqual((row.target_type, row.target_id),
                             ("creators.creatorwithdrawal", str(withdrawal.pk)))
            self.assertEqual(row.before, {"status": status})
            self.assertEqual(row.after, {"status": "rejected", "via": "creator.block"})
            self.assertEqual(_logs("creator.block").filter(creator=creator).count(), 1)

            notification = Notification.objects.filter(recipients=creator.user).get()
            self.assertEqual(notification.title, "Payout rejected")
            self.assertEqual(notification.body, "Your request for 48.50 USDT was rejected. "
                                                "The creator account is blocked")

    def test_closed_withdrawals_are_not_touched(self):
        paid = f.make_withdrawal(self.creator, "20.00", status="paid")
        rejected = f.make_withdrawal(self.creator, "30.00", status="rejected")
        before_rows = _logs("withdrawal.reject").count()
        program.block(self.creator, actor=self.boss, reason="накрутка")
        paid.refresh_from_db()
        rejected.refresh_from_db()
        self.assertEqual((paid.status, rejected.status), ("paid", "rejected"))
        self.assertEqual(rejected.reject_reason, "factory")
        self.assertEqual(_logs("withdrawal.reject").count(), before_rows)

    def test_other_creators_withdrawal_is_not_touched(self):
        other = f.make_withdrawal(f.make_creator(), "15.00")
        program.block(self.creator, actor=self.boss, reason="накрутка")
        other.refresh_from_db()
        self.assertEqual(other.status, "review")

    def test_failed_log_rolls_the_block_back(self):
        withdrawal = f.make_withdrawal(self.creator, "48.50")
        with mock.patch("creators.program.log_admin_action", side_effect=RuntimeError("log")):
            with self.assertRaises(RuntimeError):
                program.block(self.creator, actor=self.boss, reason="накрутка")
        withdrawal.refresh_from_db()
        self.assertEqual(withdrawal.status, "review")
        self.assertEqual(Creator.objects.get(pk=self.creator.pk).status, "active")


class UnblockTests(ProgramTestCase):
    def setUp(self):
        super().setUp()
        self.creator = f.make_creator()
        self.withdrawal = f.make_withdrawal(self.creator, "48.50", status="approved")
        program.block(self.creator, actor=self.boss, reason="накрутка")

    def test_unblock(self):
        creator = program.unblock(self.creator, actor=self.boss, reason="разобрались")
        fresh = Creator.objects.get(pk=self.creator.pk)
        self.assertEqual(fresh.status, "active")
        self.assertIsNone(fresh.blocked_at)
        self.assertEqual(fresh.blocked_reason, "")
        self.assertEqual((creator.status, self.creator.status), ("active", "active"))

        row = _logs("creator.unblock").get()
        self.assertEqual((row.actor, row.creator, row.reason), (self.boss, fresh, "разобрались"))
        self.assertEqual(row.before["status"], "blocked")
        self.assertEqual(row.before["blocked_reason"], "накрутка")
        self.assertEqual(row.after, {"status": "active"})

        # Отклонённая при блокировке заявка не оживает: креатор подаёт новую.
        self.withdrawal.refresh_from_db()
        self.assertEqual(self.withdrawal.status, "rejected")
        self.assertEqual(self.withdrawal.reject_reason, "creator_blocked")
        self.assertTrue(access.has_paid_access(
            get_user_model().objects.get(pk=self.creator.user_id)))

    def test_reason_is_optional(self):
        self.assertEqual(program.unblock(self.creator, actor=self.boss).status, "active")

    def test_only_a_blocked_creator(self):
        program.unblock(self.creator, actor=self.boss)
        self.assertRefused("bad_state", 409, program.unblock, self.creator, actor=self.boss)
        self.assertEqual(_logs("creator.unblock").count(), 1)

    def test_log_matches_the_status_after_several_changes(self):
        # Сверка I9: заблокирован тогда и только тогда, когда последняя запись — блокировка.
        program.unblock(self.creator, actor=self.boss)
        program.block(self.creator, actor=self.boss, reason="снова")
        latest = AdminActionLog.objects.filter(
            creator=self.creator, action__in=["creator.block", "creator.unblock"]).first()
        self.assertEqual(latest.action, "creator.block")
        self.assertEqual(Creator.objects.get(pk=self.creator.pk).status, "blocked")


# -------------------------------------------------------------------- уровни

class EditLevelTests(ProgramTestCase):
    def test_percent_range(self):
        for bad in (0, "0", -1, "25.01", 26, "abc", "", None, True, "12.345", "nan", "inf"):
            self.assertRefused("percent_invalid", 400, program.edit_level, "creator_pro",
                               {"percent": bad}, actor=self.boss)
        self.assertEqual(levels.get_level("creator_pro").percent, Decimal("15.00"))
        self.assertEqual(_logs("level.edit").count(), 0)

        for good, stored in (("25", "25.00"), ("0.01", "0.01"), (12.5, "12.50"),
                             ("17,5", "17.50")):
            level = program.edit_level("creator_pro", {"percent": good}, actor=self.boss)
            self.assertEqual(level.percent, Decimal(stored))
            self.assertEqual(CreatorLevel.objects.get(key="creator_pro").percent,
                             Decimal(stored))

    def test_log_has_only_the_changed_fields(self):
        level = program.edit_level("ambassador", {
            "title": " AMBASSADOR+ ", "percent": "20.00", "min_publications": 30,
            "min_registrations": "100", "min_paying": 30, "reason": "договорились с клиентом",
        }, actor=self.boss)
        level.refresh_from_db()
        self.assertEqual((level.title, level.min_publications), ("AMBASSADOR+", 30))
        self.assertEqual((level.percent, level.min_registrations, level.min_paying),
                         (Decimal("20.00"), 100, 30))
        self.assertEqual((level.key, level.sort), ("ambassador", 3))

        row = _logs("level.edit").get()
        self.assertEqual(row.actor, self.boss)
        self.assertEqual((row.target_type, row.target_id),
                         ("creators.creatorlevel", str(level.pk)))
        self.assertEqual(row.before, {"title": "AMBASSADOR", "min_publications": 25})
        self.assertEqual(row.after, {"title": "AMBASSADOR+", "min_publications": 30})
        self.assertEqual(row.reason, "договорились с клиентом")
        self.assertIsNone(row.creator)

    def test_same_values_write_no_log(self):
        level = program.edit_level("creator", {"percent": "10", "min_paying": 0}, actor=self.boss)
        self.assertEqual(level.percent, Decimal("10.00"))
        self.assertEqual(_logs("level.edit").count(), 0)

    def test_validation(self):
        cases = ({"key": "legend"}, {"sort": 9}, {"min_paying": -1}, {"min_paying": "много"},
                 {"min_publications": 1.5}, {"title": ""}, {"title": "T" * 65}, {}, {"reason": "x"},
                 None)
        for changes in cases:
            self.assertRefused("validation", 400, program.edit_level, "creator", changes,
                               actor=self.boss)
        self.assertEqual(_logs("level.edit").count(), 0)

    def test_unknown_level(self):
        self.assertRefused("level_unknown", 400, program.edit_level, "legend",
                           {"percent": "10"}, actor=self.boss)

    def test_existing_commissions_keep_their_percent(self):
        creator = f.make_creator(level="creator_pro")
        commission = f.make_commission(creator)
        program.edit_level("creator_pro", {"percent": "18"}, actor=self.boss, reason="рост")
        commission.refresh_from_db()
        self.assertEqual(commission.percent, Decimal("15.00"))
        self.assertEqual(commission.amount_usdt, Decimal("1.500000"))
        # Новый процент виден у креатора сразу — им посчитается следующая оплата.
        self.assertEqual(Creator.objects.get(pk=creator.pk).level.percent, Decimal("18.00"))
        self.assertEqual(_logs("level.edit").get().reason, "рост")
