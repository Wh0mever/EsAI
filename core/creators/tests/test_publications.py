"""Публикации креатора: нормализация ссылки, повторы, ручная проверка."""
import types
from unittest import mock

from django.db import IntegrityError

from audit.models import AdminActionLog
from users.models import Notification

from .. import publications
from ..errors import CreatorsError
from ..models import Creator, CreatorPublication
from . import factories as f

POST = "https://www.instagram.com/p/ABC123/"


def _logs(action):
    return AdminActionLog.objects.filter(action=action)


class NormalizeUrlTests(f.CreatorsTestCase):
    def test_table(self):
        cases = (
            # www. и m., регистр хоста, хвостовой слэш
            ("https://www.instagram.com/p/ABC123/", "instagram.com/p/ABC123"),
            ("http://Instagram.com/p/ABC123", "instagram.com/p/ABC123"),
            ("https://m.facebook.com/tora/posts/1/", "facebook.com/tora/posts/1"),
            ("https://WWW.TikTok.com/@tora/video/77//", "tiktok.com/@tora/video/77"),
            # регистр пути сохраняется: в коде поста он значим
            ("https://instagram.com/p/AbC", "instagram.com/p/AbC"),
            # запрос (метки) и якорь отбрасываются
            ("https://instagram.com/p/ABC123/?igshid=xyz&utm_source=tg", "instagram.com/p/ABC123"),
            ("https://tiktok.com/@tora/video/77?is_from_webapp=1#comments",
             "tiktok.com/@tora/video/77"),
            ("https://t.me/esai/15#top", "t.me/esai/15"),
            # YouTube: остаётся только v
            ("https://www.youtube.com/watch?v=dQw4w9WgXcQ&t=10s",
             "youtube.com/watch?v=dQw4w9WgXcQ"),
            ("https://m.youtube.com/watch?feature=share&v=dQw4w9WgXcQ",
             "youtube.com/watch?v=dQw4w9WgXcQ"),
            ("https://youtube.com/shorts/abc?feature=share", "youtube.com/shorts/abc"),
            ("https://youtu.be/dQw4w9WgXcQ?si=track", "youtu.be/dQw4w9WgXcQ"),
            # v у других сайтов — не идентификатор
            ("https://vimeo.com/123?v=2", "vimeo.com/123"),
            # только хост
            ("https://example.com", "example.com"),
            ("https://example.com/", "example.com"),
            ("  https://example.com/a  ", "example.com/a"),
            # порт и логин в адрес повтора не попадают
            ("https://user:pw@example.com:8443/a", "example.com/a"),
        )
        for url, expected in cases:
            self.assertEqual(publications.normalize_url(url), expected, url)

    def test_post_id_in_the_query_is_kept(self):
        # У этих сайтов сам пост назван в запросе: без него разные публикации
        # слились бы в одну ссылку и вторая считалась бы повтором.
        first = publications.normalize_url("https://www.facebook.com/watch/?v=111&ref=sharing")
        second = publications.normalize_url("https://facebook.com/watch?v=222")
        self.assertEqual(first, "facebook.com/watch?v=111")
        self.assertNotEqual(first, second)
        self.assertEqual(
            publications.normalize_url(
                "https://m.facebook.com/story.php?story_fbid=5&id=9&mibextid=x"),
            "facebook.com/story.php?story_fbid=5&id=9")
        self.assertEqual(publications.normalize_url("https://vk.com/feed?w=wall-1_2&from=x"),
                         "vk.com/feed?w=wall-1_2")
        self.assertNotEqual(publications.normalize_url("https://vk.com/video?z=video-1_2"),
                            publications.normalize_url("https://vk.com/video?z=video-1_3"))

    def test_same_post_by_different_links_is_one(self):
        norms = {publications.normalize_url(url) for url in (
            "https://www.youtube.com/watch?v=abc", "http://youtube.com/watch/?v=abc&t=1",
            "https://m.youtube.com/watch?list=PL1&v=abc#t=5")}
        self.assertEqual(norms, {"youtube.com/watch?v=abc"})

    def test_invalid(self):
        for bad in ("", "   ", None, 123, ["https://x.com"], "instagram.com/p/1",
                    "ftp://example.com/a", "javascript:alert(1)", "https://", "https:///path",
                    "//example.com/a", "https://www.", "http://[bad"):
            with self.assertRaises(CreatorsError) as caught:
                publications.normalize_url(bad)
            self.assertEqual((caught.exception.code, caught.exception.http),
                             ("url_invalid", 400), bad)


class PublicationsTestCase(f.CreatorsTestCase):
    def setUp(self):
        super().setUp()
        self.staff = f.make_user(staff=True)
        self.creator = f.make_creator()
        patcher = mock.patch("botapi.tasks.notify")
        self.tg = patcher.start()
        self.addCleanup(patcher.stop)
        # Подсчёт условий следующего уровня — чужой модуль: здесь важно только,
        # что его зовут после подтверждения и что его сбой ничего не ломает.
        self.check_next_level = mock.Mock(return_value=False)
        stats = types.SimpleNamespace(check_next_level=self.check_next_level)
        modules = mock.patch.dict("sys.modules", {"creators.stats": stats})
        modules.start()
        self.addCleanup(modules.stop)

    def assertRefused(self, code, http, call, *args, **kwargs):
        with self.assertRaises(CreatorsError) as caught:
            call(*args, **kwargs)
        self.assertEqual((caught.exception.code, caught.exception.http), (code, http))
        return caught.exception


class SubmitTests(PublicationsTestCase):
    def test_submit(self):
        publication = publications.submit(self.creator, "instagram", f"  {POST}?igshid=1 ",
                                          "  Обзор EsAI ")
        publication.refresh_from_db()
        self.assertEqual(publication.creator, self.creator)
        self.assertEqual(publication.status, "review")
        self.assertEqual(publication.network, "instagram")
        self.assertEqual(publication.url, f"{POST}?igshid=1")
        self.assertEqual(publication.url_norm, "instagram.com/p/ABC123")
        self.assertEqual(publication.description, "Обзор EsAI")
        self.assertIsNone(publication.decided_at)
        self.assertEqual(Notification.objects.count(), 0)
        self.assertEqual(_logs("publication.approve").count(), 0)

    def test_every_network_of_the_list(self):
        for index, network in enumerate(CreatorPublication.Network.values):
            row = publications.submit(self.creator, network, f"https://example.com/{index}")
            self.assertEqual(row.network, network)
        self.assertEqual(publications.submit(self.creator, " TikTok ",
                                             "https://tiktok.com/@t/video/1").network, "tiktok")

    def test_description_is_optional_and_cut(self):
        self.assertEqual(publications.submit(self.creator, "x", "https://x.com/t/1").description,
                         "")
        long = publications.submit(self.creator, "x", "https://x.com/t/2", "о" * 600)
        self.assertEqual(len(long.description), 500)

    def test_network_validation(self):
        for bad in ("myspace", "", None):
            self.assertRefused("network_invalid", 400, publications.submit, self.creator, bad,
                               POST)
        self.assertEqual(CreatorPublication.objects.count(), 0)

    def test_url_validation(self):
        for bad in ("", None, "instagram.com/p/1", "ftp://x.com/a",
                    "https://example.com/" + "a" * 500):
            self.assertRefused("url_invalid", 400, publications.submit, self.creator,
                               "instagram", bad)
        self.assertEqual(CreatorPublication.objects.count(), 0)
        ok = "https://example.com/" + "a" * 480
        self.assertEqual(len(publications.submit(self.creator, "other", ok).url), 500)

    def test_blocked_creator(self):
        blocked = f.make_creator(status="blocked")
        self.assertRefused("creator_blocked", 403, publications.submit, blocked, "instagram",
                           POST)
        # Статус читается из базы, а не с объекта в руках.
        Creator.objects.filter(pk=self.creator.pk).update(status="blocked")
        self.assertRefused("creator_blocked", 403, publications.submit, self.creator,
                           "instagram", POST)
        self.assertRefused("not_found", 404, publications.submit, Creator(pk=999_999),
                           "instagram", POST)

    def test_duplicate_across_creators(self):
        publications.submit(self.creator, "instagram", POST)
        other = f.make_creator()
        # Та же публикация другой ссылкой — всё равно повтор.
        self.assertRefused("publication_duplicate", 409, publications.submit, other,
                           "instagram", "http://instagram.com/p/ABC123?igshid=other")
        self.assertRefused("publication_duplicate", 409, publications.submit, self.creator,
                           "instagram", POST)
        self.assertEqual(CreatorPublication.objects.count(), 1)

    def test_approved_publication_is_still_a_duplicate(self):
        publication = publications.submit(self.creator, "instagram", POST)
        publications.approve(publication.pk, actor=self.staff)
        self.assertRefused("publication_duplicate", 409, publications.submit,
                           f.make_creator(), "instagram", POST)

    def test_race_on_the_unique_index_is_a_duplicate(self):
        with mock.patch("creators.publications.CreatorPublication.objects.create",
                        side_effect=IntegrityError("creators_pub_url_once")):
            self.assertRefused("publication_duplicate", 409, publications.submit,
                               self.creator, "instagram", POST)
        # Транзакция после отказа жива.
        self.assertEqual(publications.submit(self.creator, "instagram", POST).status, "review")

    def test_resubmit_after_rejection(self):
        first = publications.submit(self.creator, "instagram", POST)
        publications.reject(first.pk, actor=self.staff, reason="нет упоминания EsAI")
        second = publications.submit(self.creator, "instagram", POST)
        self.assertNotEqual(first.pk, second.pk)
        self.assertEqual(second.status, "review")
        # Отклонённую ссылку может подать и другой креатор, но только пока она свободна.
        self.assertRefused("publication_duplicate", 409, publications.submit,
                           f.make_creator(), "instagram", POST)


class ReviewTests(PublicationsTestCase):
    def setUp(self):
        super().setUp()
        self.publication = publications.submit(self.creator, "instagram", POST)

    def test_approve(self):
        with self.captureOnCommitCallbacks(execute=True):
            publication = publications.approve(self.publication.pk, actor=self.staff)
        publication.refresh_from_db()
        self.assertEqual(publication.status, "approved")
        self.assertEqual(publication.decided_by, self.staff)
        self.assertIsNotNone(publication.decided_at)
        self.assertEqual(publication.reject_reason, "")

        row = _logs("publication.approve").get()
        self.assertEqual((row.actor, row.creator), (self.staff, self.creator))
        self.assertEqual((row.target_type, row.target_id),
                         ("creators.creatorpublication", str(publication.pk)))
        self.assertEqual((row.before, row.after),
                         ({"status": "review"}, {"status": "approved"}))

        notification = Notification.objects.get()
        self.assertEqual(notification.title, "Публикация подтверждена")
        self.assertEqual(notification.body, f"Публикация засчитана: {POST}")
        self.assertEqual(list(notification.recipients.all()), [self.creator.user])

        # После подтверждения проверяются условия следующего уровня.
        self.check_next_level.assert_called_once()
        self.assertEqual(self.check_next_level.call_args.args[0].pk, self.creator.pk)

    def test_reject(self):
        with self.captureOnCommitCallbacks(execute=True):
            publication = publications.reject(self.publication.pk, actor=self.staff,
                                              reason="  Нет упоминания EsAI ")
        publication.refresh_from_db()
        self.assertEqual(publication.status, "rejected")
        self.assertEqual(publication.reject_reason, "Нет упоминания EsAI")
        self.assertEqual(publication.decided_by, self.staff)
        self.assertIsNotNone(publication.decided_at)

        row = _logs("publication.reject").get()
        self.assertEqual((row.actor, row.creator, row.reason),
                         (self.staff, self.creator, "Нет упоминания EsAI"))
        self.assertEqual((row.before, row.after),
                         ({"status": "review"}, {"status": "rejected"}))

        notification = Notification.objects.get()
        self.assertEqual(notification.title, "Публикация отклонена")
        self.assertEqual(notification.body,
                         f"Публикация не засчитана: {POST}. Нет упоминания EsAI")
        # Отклонение прогресс не меняет — пересчитывать нечего.
        self.check_next_level.assert_not_called()

    def test_reject_without_a_reason(self):
        publication = publications.reject(self.publication.pk, actor=self.staff)
        self.assertEqual((publication.status, publication.reject_reason), ("rejected", ""))

    def test_only_from_review(self):
        publications.approve(self.publication.pk, actor=self.staff)
        self.assertRefused("bad_state", 409, publications.approve, self.publication.pk,
                           actor=self.staff)
        self.assertRefused("bad_state", 409, publications.reject, self.publication.pk,
                           actor=self.staff, reason="передумали")

        other = publications.submit(self.creator, "tiktok", "https://tiktok.com/@t/video/2")
        publications.reject(other.pk, actor=self.staff)
        self.assertRefused("bad_state", 409, publications.reject, other.pk, actor=self.staff)
        self.assertRefused("bad_state", 409, publications.approve, other.pk, actor=self.staff)

        self.assertEqual(_logs("publication.approve").count(), 1)
        self.assertEqual(_logs("publication.reject").count(), 1)
        self.check_next_level.assert_called_once()

    def test_not_found(self):
        self.assertRefused("not_found", 404, publications.approve, 999_999, actor=self.staff)
        self.assertRefused("not_found", 404, publications.reject, "abc", actor=self.staff)

    def test_only_approved_are_counted(self):
        rejected = publications.submit(self.creator, "tiktok", "https://tiktok.com/@t/video/2")
        publications.submit(self.creator, "youtube", "https://youtube.com/watch?v=3")
        publications.approve(self.publication.pk, actor=self.staff)
        publications.reject(rejected.pk, actor=self.staff)
        counted = CreatorPublication.objects.filter(creator=self.creator, status="approved")
        self.assertEqual([row.pk for row in counted], [self.publication.pk])
        self.assertEqual(CreatorPublication.objects.filter(creator=self.creator).count(), 3)

    def test_failing_level_check_does_not_undo_the_approval(self):
        self.check_next_level.side_effect = RuntimeError("stats")
        with self.assertLogs("creators", level="ERROR"):
            publication = publications.approve(self.publication.pk, actor=self.staff)
        publication.refresh_from_db()
        self.assertEqual(publication.status, "approved")
        self.assertEqual(_logs("publication.approve").count(), 1)

    def test_missing_stats_module_does_not_undo_the_approval(self):
        with mock.patch.dict("sys.modules", {"creators.stats": None}), \
                self.assertLogs("creators", level="ERROR"):
            publication = publications.approve(self.publication.pk, actor=self.staff)
        self.assertEqual(publication.status, "approved")

    def test_failed_log_rolls_the_decision_back(self):
        with mock.patch("creators.publications.log_admin_action",
                        side_effect=RuntimeError("log")):
            with self.assertRaises(RuntimeError):
                publications.approve(self.publication.pk, actor=self.staff)
            with self.assertRaises(RuntimeError):
                publications.reject(self.publication.pk, actor=self.staff)
        self.publication.refresh_from_db()
        self.assertEqual(self.publication.status, "review")
        self.assertIsNone(self.publication.decided_at)

    def test_blocked_creators_publication_can_still_be_reviewed(self):
        Creator.objects.filter(pk=self.creator.pk).update(status="blocked")
        self.assertEqual(publications.approve(self.publication.pk, actor=self.staff).status,
                         "approved")
