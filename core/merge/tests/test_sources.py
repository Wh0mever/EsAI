"""Источники склейки: только свои, только готовые, только с файлом на диске."""
from __future__ import annotations

from ai.models import GenerationLog
from cartoon.models import CartoonProject, CartoonScene
from merge import sources
from vstudio.models import Take

from .helpers import MediaTestCase


class ResolveTests(MediaTestCase):
    def setUp(self):
        super().setUp()
        self.owner = self.user()
        self.stranger = self.user()

    def _keys(self, user, *objs):
        refs = [(self.ref(o)["type"], str(self.ref(o)["id"])) for o in objs]
        return set(sources.resolve(user, refs))

    def test_own_finished_sources_of_every_kind(self):
        take, scene = self.take(self.owner), self.scene(self.owner)
        movie, chat = self.movie(self.owner), self.chat(self.owner)
        found = sources.resolve(self.owner, [("vstudio", take.uid), ("cartoon_scene", str(scene.pk)),
                                             ("cartoon_movie", str(movie.pk)), ("chat", str(chat.pk))])
        self.assertEqual(set(found), {("vstudio", take.uid), ("cartoon_scene", str(scene.pk)),
                                      ("cartoon_movie", str(movie.pk)), ("chat", str(chat.pk))})
        self.assertEqual(found[("vstudio", take.uid)].file, take.result_asset.file)
        self.assertEqual(found[("chat", str(chat.pk))].file,
                         chat.result_url.replace("/media/", "", 1))
        for source in found.values():
            self.assertEqual(source.duration_s, 5.0)

    def test_someone_elses_sources_are_invisible(self):
        objs = (self.take(self.owner), self.scene(self.owner), self.movie(self.owner),
                self.chat(self.owner))
        self.assertEqual(self._keys(self.stranger, *objs), set())

    def test_unfinished_or_deleted_sources_are_invisible(self):
        objs = (
            self.take(self.owner, status=Take.STATUS_RUNNING),
            self.take(self.owner, deleted=True),
            self.scene(self.owner, status=CartoonScene.STATUS_VIDEO),
            self.movie(self.owner, status=CartoonProject.STATUS_ASSEMBLING),
            self.chat(self.owner, status=GenerationLog.STATUS_SUBMITTED),
            self.chat(self.owner, source="studio"),
        )
        self.assertEqual(self._keys(self.owner, *objs), set())

    def test_missing_file_is_invisible(self):
        objs = (self.take(self.owner, with_file=False), self.scene(self.owner, with_file=False),
                self.movie(self.owner, with_file=False), self.chat(self.owner, with_file=False))
        self.assertEqual(self._keys(self.owner, *objs), set())

    def test_chat_video_outside_ai_videos_is_not_trusted(self):
        row = self.chat(self.owner)
        GenerationLog.objects.filter(pk=row.pk).update(result_url="/media/vstudio/9/other.mp4")
        self.assertEqual(self._keys(self.owner, row), set())
        GenerationLog.objects.filter(pk=row.pk).update(result_url="/media/ai_videos/../vstudio/x.mp4")
        self.assertEqual(self._keys(self.owner, row), set())

    def test_scene_with_sound_uses_mixed_video(self):
        scene = self.scene(self.owner, mixed=True)
        found = sources.resolve(self.owner, [("cartoon_scene", str(scene.pk))])
        self.assertEqual(found[("cartoon_scene", str(scene.pk))].file, scene.mixed_video)

    def test_bad_ids_are_ignored(self):
        self.assertEqual(sources.resolve(self.owner, [("vstudio", "../etc"), ("chat", "0"),
                                                      ("cartoon_scene", "abc"), ("nope", "1")]), {})

    def test_duration_from_probe_and_cache(self):
        movie = self.movie(self.owner)
        self.durations[movie.result_video] = 42.5
        key = [("cartoon_movie", str(movie.pk))]
        self.assertEqual(sources.resolve(self.owner, key)[key[0]].duration_s, 42.5)
        calls = self.probe.call_count
        sources.resolve(self.owner, key)
        self.assertEqual(self.probe.call_count, calls)


class ValidIdTests(MediaTestCase):
    def test_valid_id(self):
        self.assertEqual(sources.valid_id("vstudio", "A" * 32), "a" * 32)
        self.assertIsNone(sources.valid_id("vstudio", "a" * 31))
        self.assertEqual(sources.valid_id("chat", 12), "12")
        self.assertIsNone(sources.valid_id("chat", True))
        self.assertIsNone(sources.valid_id("chat", "-1"))
        self.assertIsNone(sources.valid_id("chat", "1.5"))
        self.assertIsNone(sources.valid_id("other", "1"))


class ListPageTests(MediaTestCase):
    def setUp(self):
        super().setUp()
        self.owner = self.user()

    def test_cards_shape(self):
        take = self.take(self.owner)
        page = sources.list_page(self.owner, "vstudio")
        self.assertEqual(page["type"], "vstudio")
        self.assertFalse(page["has_more"])
        card = page["results"][0]
        self.assertEqual(set(card), {"type", "id", "title", "subtitle", "poster", "url",
                                     "duration_s", "width", "height", "created_at"})
        self.assertEqual(card["id"], take.uid)
        self.assertEqual(card["title"], "Кот летит над городом на закате")
        self.assertEqual(card["url"], "/media/" + take.result_asset.file)
        self.assertEqual((card["width"], card["height"], card["duration_s"]), (1280, 720, 5.0))

    def test_pagination(self):
        for _ in range(3):
            self.chat(self.owner)
        first = sources.list_page(self.owner, "chat", 1, page_size=2)
        second = sources.list_page(self.owner, "chat", 2, page_size=2)
        self.assertTrue(first["has_more"])
        self.assertFalse(second["has_more"])
        ids = [c["id"] for c in first["results"] + second["results"]]
        self.assertEqual(len(set(ids)), 3)

    def test_cartoon_tab_has_movies_and_scenes(self):
        scene = self.scene(self.owner)
        movie = self.movie(self.owner)
        cards = sources.list_page(self.owner, "cartoon")["results"]
        self.assertEqual({(c["type"], c["id"]) for c in cards},
                         {("cartoon_scene", str(scene.pk)), ("cartoon_movie", str(movie.pk))})
        movie_card = next(c for c in cards if c["type"] == "cartoon_movie")
        self.assertEqual(movie_card["poster"], None)

    def test_scene_title_follows_language(self):
        self.scene(self.owner)
        card = sources.list_page(self.owner, "cartoon_scene", lang="en")["results"][0]
        self.assertEqual(card["title"], "Roof")
        self.assertEqual(card["subtitle"], "Про кота")
