# -*- coding: utf-8 -*-
"""«Снять» сверяет цену с кнопкой (Build C, ревью C_R1_money B1).

Цена сцены зависит от дока мультфильма, а док меняют с любого устройства, и
модель может выключить админ. Без сверки старая вкладка или старая кнопка в
Telegram списывала столько, сколько стоит съёмка сейчас (35 на кнопке → 905).
Теперь клиент присылает quoted_credits: выросла цена — 409 price_changed и
ничего не меняется; не прислал — как раньше; стала ниже — снимаем молча.

Ревью C_R1_money_r1: «Снять» у уже готовой сцены (старая вкладка, старое меню
бота) переснимало её без вопроса — 409 already_shot (AlreadyShotTests).
"""
from __future__ import annotations

from unittest.mock import patch

from cartoon import pricing as cp
from cartoon.models import CartoonKeyframe, CartoonScene
from cartoon.tests_dock_api import MINI, S20, DockBase, _client
from cartoon.tasks import render_scene as render_scene_task
from cartoon.tests_pipeline_dock import _Pipeline
from plans.models import TokenTransaction

SNAPSHOT = ("shot_model_id", "shot_resolution", "shot_duration", "shot_aspect", "credits_planned",
            "shot_video_credits")


class QuoteBase(DockBase):
    def post_render(self, scene, body, user=None):
        with patch("cartoon.views.render_scene.delay") as delay, \
                self.captureOnCommitCallbacks(execute=True):
            response = _client(user or self.user).post(f"/api/cartoon/scenes/{scene.pk}/render/", body,
                                                       format="json")
        scene.refresh_from_db()
        return response, delay

    def patch_retry(self, scene, body):
        with patch("cartoon.views.render_scene.delay") as delay, \
                self.captureOnCommitCallbacks(execute=True):
            response = self.client.patch(f"/api/cartoon/scenes/{scene.pk}/", {"retry": True, **body},
                                         format="json")
        scene.refresh_from_db()
        return response, delay

    def row(self, project, scene) -> dict:
        """Строка ленты, как её видит вкладка: цена на кнопке «Снять»."""
        body = self.client.get(f"/api/cartoon/projects/{project.pk}/").json()
        return next(s for s in body["scenes"] if s["id"] == scene.pk)

    def snapshot(self, scene) -> tuple:
        return tuple(getattr(scene, name) for name in SNAPSHOT)

    def assert_untouched(self, scene, status, snapshot, response, delay):
        """409: статус, снимок, резерв и баланс — как были; задача не поставлена."""
        self.assertEqual(response.status_code, 409, response.content)
        delay.assert_not_called()
        scene.refresh_from_db()
        self.assertEqual(scene.status, status)
        self.assertEqual(self.snapshot(scene), snapshot)
        self.assertEqual(cp.reserved_credits(self.user), 0)
        self.user.refresh_from_db()
        self.assertEqual(self.user.token_balance, 10000)
        self.assertFalse(TokenTransaction.objects.filter(user=self.user).exists())


class QuoteTests(QuoteBase):
    """markup 40 %: Mini 480p 5 с = 35 (кадр 7 + видео 28)."""

    def test_two_tabs_stale_quote_is_refused(self):
        project = self.project(model=MINI, resolution="480p", duration=5)
        scene = self.scene(project)
        shown = self.row(project, scene)["render_credits"]
        # Вкладка Б (или бот) поставила Seedance 2.0 1080p 15 с.
        r = self.client.patch(f"/api/cartoon/projects/{project.pk}/",
                              {"video_model": S20, "resolution": "1080p", "duration": 15}, format="json")
        self.assertEqual(r.status_code, 200, r.content)
        now = self.row(project, scene)["render_credits"]
        before = self.snapshot(scene)

        response, delay = self.post_render(scene, {"quoted_credits": shown})
        self.assert_untouched(scene, CartoonScene.STATUS_DRAFT, before, response, delay)
        body = response.json()
        self.assertEqual(body["error_code"], "price_changed")
        self.assertEqual((body["credits"], body["quoted"]), (now, shown))
        self.assertEqual(body["scene"]["render_credits"], now)
        self.assertEqual(body["detail"], f"Цена изменилась: теперь {now} кр. Проверьте и нажмите «Снять» ещё раз.")
        if self.markup:
            self.assertEqual((shown, now), (35, 905))

        # С новой ценой на кнопке — снимает, и снимок ровно по ней.
        response, delay = self.post_render(scene, {"quoted_credits": now})
        self.assertEqual(response.status_code, 200, response.content)
        delay.assert_called_once_with(scene.pk)
        self.assertEqual((scene.status, scene.shot_model.openrouter_id, scene.credits_planned),
                         (CartoonScene.STATUS_NEW, S20, now))

    def test_model_switched_off_after_page_load_is_refused(self):
        project = self.project(model=MINI, resolution="480p", duration=5)
        scene = self.scene(project)
        shown = self.row(project, scene)["render_credits"]
        # Админ выключил Mini, страница этого ещё не знает: на кнопке 35 (Mini).
        self.models[MINI].is_active = False
        self.models[MINI].save(update_fields=["is_active"])
        response, delay = self.post_render(scene, {"quoted_credits": shown})
        self.assert_untouched(scene, CartoonScene.STATUS_DRAFT, (None,) * len(SNAPSHOT), response, delay)
        self.assertEqual(response.json()["scene"]["config"]["video_model"], S20)
        self.assertGreater(response.json()["credits"], shown)
        if self.markup:
            self.assertEqual((shown, response.json()["credits"]), (35, 62))

    def test_no_quote_behaves_as_before(self):
        """Старый клиент цену не шлёт — снимаем по нынешней, как до сверки."""
        project = self.project(model=MINI, resolution="480p", duration=5)
        scene = self.scene(project)
        self.client.patch(f"/api/cartoon/projects/{project.pk}/",
                          {"video_model": S20, "resolution": "1080p", "duration": 15}, format="json")
        now = self.row(project, scene)["render_credits"]
        response, delay = self.post_render(scene, {})
        self.assertEqual(response.status_code, 200, response.content)
        delay.assert_called_once_with(scene.pk)
        self.assertEqual((scene.status, scene.credits_planned), (CartoonScene.STATUS_NEW, now))
        for empty in (None, ""):
            other = self.scene(project)
            response, _ = self.post_render(other, {"quoted_credits": empty})
            self.assertEqual((response.status_code, other.status), (200, CartoonScene.STATUS_NEW))

    def test_matching_quote_shoots(self):
        project = self.project(model=MINI, resolution="480p", duration=5)
        scene = self.scene(project)
        shown = self.row(project, scene)["render_credits"]
        response, delay = self.post_render(scene, {"quoted_credits": shown})
        self.assertEqual(response.status_code, 200, response.content)
        delay.assert_called_once_with(scene.pk)
        self.assertEqual(scene.credits_planned, shown)

    def test_cheaper_than_quoted_is_silent(self):
        """Кадр пары нашёлся в общем запасе после того, как строка нарисовалась."""
        project = self.project(model=MINI, resolution="480p", duration=5)
        scene = self.scene(project)
        shown = self.row(project, scene)["render_credits"]
        CartoonKeyframe.objects.create(preset=scene.preset, character=self.hero, aspect_ratio="16:9",
                                       image="cartoon/keyframes/pool.png")
        response, _ = self.post_render(scene, {"quoted_credits": shown})
        self.assertEqual(response.status_code, 200, response.content)
        self.assertLess(scene.credits_planned, shown)
        self.assertEqual(scene.credits_planned, scene.shot_video_credits)
        if self.markup:
            self.assertEqual((shown, scene.credits_planned), (35, 28))

    def test_quote_is_checked_before_the_balance(self):
        """Устаревшая цена — сначала «цена изменилась», а не окно покупки на чужую сумму."""
        project = self.project(model=MINI, resolution="480p", duration=5)
        scene = self.scene(project)
        shown = self.row(project, scene)["render_credits"]
        self.client.patch(f"/api/cartoon/projects/{project.pk}/",
                          {"video_model": S20, "resolution": "1080p", "duration": 15}, format="json")
        self.user.token_balance = shown
        self.user.save(update_fields=["token_balance"])
        response, delay = self.post_render(scene, {"quoted_credits": shown})
        self.assertEqual((response.status_code, response.json()["error_code"]), (409, "price_changed"))
        delay.assert_not_called()

    def test_retry_stale_quote_keeps_the_ready_scene(self):
        project = self.project(model=MINI, resolution="480p", duration=5)
        scene = self.scene(project, status=CartoonScene.STATUS_READY, video="cartoon/scenes/old.mp4",
                           keyframe="cartoon/k/1.png", shot_model=self.models[MINI], shot_resolution="480p",
                           shot_duration=5, shot_aspect="16:9", credits_planned=35, shot_video_credits=28)
        shown = self.row(project, scene)["render_credits"]
        self.client.patch(f"/api/cartoon/projects/{project.pk}/",
                          {"video_model": S20, "resolution": "720p", "duration": 10}, format="json")
        before = self.snapshot(scene)
        response, delay = self.patch_retry(scene, {"quoted_credits": shown})
        self.assert_untouched(scene, CartoonScene.STATUS_READY, before, response, delay)
        self.assertEqual((scene.video, scene.keyframe), ("cartoon/scenes/old.mp4", "cartoon/k/1.png"))
        # «Новый кадр» с ценой «только видео» на кнопке: кадр не сброшен, ничего не снято.
        response, delay = self.patch_retry(scene, {"new_keyframe": True, "quoted_credits": shown})
        self.assert_untouched(scene, CartoonScene.STATUS_READY, before, response, delay)
        self.assertEqual(scene.keyframe, "cartoon/k/1.png")
        # Свежая цена — переснимает по новым настройкам.
        now = response.json()["credits"]
        response, delay = self.patch_retry(scene, {"new_keyframe": True, "quoted_credits": now})
        self.assertEqual(response.status_code, 200, response.content)
        delay.assert_called_once_with(scene.pk)
        self.assertEqual((scene.status, scene.keyframe, scene.credits_planned, scene.shot_model.openrouter_id),
                         (CartoonScene.STATUS_NEW, "", now, S20))

    def test_retry_without_quote_behaves_as_before(self):
        project = self.project(model=MINI, resolution="480p", duration=5)
        scene = self.scene(project, status=CartoonScene.STATUS_FAILED, keyframe="cartoon/k/1.png")
        self.client.patch(f"/api/cartoon/projects/{project.pk}/",
                          {"video_model": S20, "resolution": "720p", "duration": 10}, format="json")
        now = self.row(project, scene)["render_credits"]
        response, delay = self.patch_retry(scene, {})
        self.assertEqual(response.status_code, 200, response.content)
        delay.assert_called_once_with(scene.pk)
        self.assertEqual(scene.credits_planned, now)

    def test_bad_quote_is_400_and_changes_nothing(self):
        project = self.project(model=MINI, resolution="480p", duration=5)
        for bad in ("abc", "²", "-5", True, -1, 1.5, [35], {"n": 35}):
            scene = self.scene(project, dialogue="")
            response, delay = self.post_render(scene, {"quoted_credits": bad})
            self.assertEqual((response.status_code, response.json()["error_code"]), (400, "invalid_quote"), bad)
            delay.assert_not_called()
            self.assertEqual(scene.status, CartoonScene.STATUS_DRAFT)
            # PATCH: кривая цена отказывает до любых правок — реплика не записана.
            response, delay = self.patch_retry(scene, {"dialogue": "Привет", "quoted_credits": bad})
            self.assertEqual(response.status_code, 400, bad)
            delay.assert_not_called()
            self.assertEqual((scene.status, scene.dialogue), (CartoonScene.STATUS_DRAFT, ""))
        # Целое из JSON в виде 35.0 или строки «35» (форма, бот) — годится.
        shown = self.row(project, self.scene(project))["render_credits"]
        for fine in (float(shown), str(shown), f" {shown} "):
            scene = self.scene(project)
            response, _ = self.post_render(scene, {"quoted_credits": fine})
            self.assertEqual(response.status_code, 200, (fine, response.content))

    def test_working_scene_returns_as_is(self):
        """Сцена уже снимается — второго снимка нет и сверять нечего."""
        project = self.project(model=MINI, resolution="480p", duration=5)
        scene = self.scene(project)
        shown = self.row(project, scene)["render_credits"]
        self.post_render(scene, {"quoted_credits": shown})
        planned = scene.credits_planned
        response, delay = self.post_render(scene, {"quoted_credits": 1})
        self.assertEqual(response.status_code, 200, response.content)
        delay.assert_not_called()
        self.assertEqual(scene.credits_planned, planned)


class LegacyQuoteTests(QuoteTests):
    """Режим «по-старому»: та же сверка, числа — прежней формулы."""
    markup = False


OLD_VIDEO = "cartoon/scenes/old.mp4"
OLD_FRAME = "cartoon/k/1.png"
ALREADY_SHOT = "Сцена уже снята — переснять можно кнопкой «Переснять»"


class AlreadyShotTests(QuoteBase):
    """Устаревшее «Снять» у готовой сцены (ревью C_R1_money_r1): POST render/ — только
    первая съёмка. Готовая сцена — 409 already_shot: без задачи, списания и замены ролика.
    Цена кнопки (кадр + видео) тут не спасала: у готовой сцены есть кадр, «Снять» стоит
    только видео — меньше, чем на кнопке."""

    def ready(self, project, **extra):
        fields = dict(status=CartoonScene.STATUS_READY, video=OLD_VIDEO, keyframe=OLD_FRAME,
                      shot_model=self.models[MINI], shot_resolution="480p", shot_duration=5,
                      shot_aspect="16:9", credits_planned=35, shot_video_credits=28)
        fields.update(extra)
        return self.scene(project, **fields)

    def assert_kept(self, scene, before, response, delay):
        self.assert_untouched(scene, CartoonScene.STATUS_READY, before, response, delay)
        body = response.json()
        self.assertEqual((body["error_code"], body["detail"], body["error"]),
                         ("already_shot", ALREADY_SHOT, ALREADY_SHOT))
        # Сцена в ответе — с ценами пересъёмки: бот рисует по ней меню.
        self.assertEqual((body["scene"]["id"], body["scene"]["status"]), (scene.pk, "ready"))
        self.assertEqual((scene.video, scene.keyframe), (OLD_VIDEO, OLD_FRAME))

    def test_stale_render_on_ready_scene_is_refused(self):
        project = self.project(model=MINI, resolution="480p", duration=5)
        scene = self.ready(project)
        before = self.snapshot(scene)
        # Кнопка строки «не снята»: кадр + видео (35). Сейчас «Снять» стоило бы 28 —
        # сверка цены его не остановила бы. Без цены (старый клиент) — тоже отказ.
        for body in ({"quoted_credits": 35}, {"quoted_credits": 10000}, {}):
            response, delay = self.post_render(scene, body)
            self.assert_kept(scene, before, response, delay)

    def test_scene_turning_ready_before_the_update_is_refused(self):
        """Строку прочли «не снята», а до условного UPDATE её доснял другой запрос."""
        project = self.project(model=MINI, resolution="480p", duration=5)
        scene = self.scene(project)
        shown = self.row(project, scene)["render_credits"]
        ready = dict(status=CartoonScene.STATUS_READY, video=OLD_VIDEO, keyframe=OLD_FRAME)

        def finish_elsewhere(s):
            CartoonScene.objects.filter(pk=s.pk).update(**ready)

        with patch("cartoon.views._attach_ready_keyframe", side_effect=finish_elsewhere):
            response, delay = self.post_render(scene, {"quoted_credits": shown})
        self.assertEqual((response.status_code, response.json()["error_code"]), (409, "already_shot"))
        delay.assert_not_called()
        self.assertEqual((scene.status, scene.video, scene.credits_planned),
                         (CartoonScene.STATUS_READY, OLD_VIDEO, None))
        self.assertEqual(cp.reserved_credits(self.user), 0)

    def test_first_shoot_of_draft_and_failed_still_works(self):
        project = self.project(model=MINI, resolution="480p", duration=5)
        for status in (CartoonScene.STATUS_DRAFT, CartoonScene.STATUS_FAILED):
            scene = self.scene(project, status=status)
            shown = self.row(project, scene)["render_credits"]
            response, delay = self.post_render(scene, {"quoted_credits": shown})
            self.assertEqual(response.status_code, 200, (status, response.content))
            delay.assert_called_once_with(scene.pk)
            self.assertEqual((scene.status, scene.credits_planned), (CartoonScene.STATUS_NEW, shown))

    def test_reshoot_of_ready_scene_goes_through_retry(self):
        """PATCH {retry} по-прежнему переснимает готовую: без expect_status (бот, старый
        сайт) и с expect_status «ready» (сайт спросил перед этим)."""
        project = self.project(model=MINI, resolution="480p", duration=5)
        for extra in ({}, {"expect_status": "ready"}):
            scene = self.ready(project)
            shown = self.row(project, scene)["render_credits"]
            response, delay = self.patch_retry(scene, {"quoted_credits": shown, **extra})
            self.assertEqual(response.status_code, 200, (extra, response.content))
            delay.assert_called_once_with(scene.pk)
            self.assertEqual((scene.status, scene.credits_planned), (CartoonScene.STATUS_NEW, shown))

    def test_stale_failed_row_retry_keeps_the_ready_scene(self):
        """↻ у строки «ошибка» из старой вкладки, а сцену с тех пор пересняли."""
        project = self.project(model=MINI, resolution="480p", duration=5)
        scene = self.ready(project, dialogue="")
        before = self.snapshot(scene)
        shown = self.row(project, scene)["render_credits"]
        for extra in ({}, {"new_keyframe": True}, {"dialogue": "Привет"}):
            response, delay = self.patch_retry(scene, {"expect_status": "failed", "quoted_credits": shown,
                                                       **extra})
            self.assert_kept(scene, before, response, delay)
            # Отказ — до любых правок: реплика не записана, кадр пары не удалён.
            self.assertEqual(scene.dialogue, "")

    def test_failed_row_retry_turning_ready_before_the_update_is_refused(self):
        project = self.project(model=MINI, resolution="480p", duration=5)
        scene = self.scene(project, status=CartoonScene.STATUS_FAILED, keyframe=OLD_FRAME)
        shown = self.row(project, scene)["render_credits"]

        def finish_elsewhere(s):
            CartoonScene.objects.filter(pk=s.pk).update(status=CartoonScene.STATUS_READY, video=OLD_VIDEO)

        with patch("cartoon.views._attach_ready_keyframe", side_effect=finish_elsewhere):
            response, delay = self.patch_retry(scene, {"expect_status": "failed", "quoted_credits": shown})
        self.assertEqual((response.status_code, response.json()["error_code"]), (409, "already_shot"))
        delay.assert_not_called()
        self.assertEqual((scene.status, scene.video, scene.credits_planned),
                         (CartoonScene.STATUS_READY, OLD_VIDEO, None))

    def test_failed_row_retry_with_expect_status_shoots(self):
        project = self.project(model=MINI, resolution="480p", duration=5)
        scene = self.scene(project, status=CartoonScene.STATUS_FAILED, keyframe=OLD_FRAME)
        shown = self.row(project, scene)["render_credits"]
        response, delay = self.patch_retry(scene, {"expect_status": "failed", "quoted_credits": shown})
        self.assertEqual(response.status_code, 200, response.content)
        delay.assert_called_once_with(scene.pk)
        self.assertEqual(scene.status, CartoonScene.STATUS_NEW)

    def test_bad_expect_status_is_400_and_changes_nothing(self):
        project = self.project(model=MINI, resolution="480p", duration=5)
        scene = self.ready(project, dialogue="")
        before = self.snapshot(scene)
        for bad in ("READY", "готова", 5, True, ["failed"], {"s": "failed"}):
            response, delay = self.patch_retry(scene, {"expect_status": bad, "dialogue": "Привет"})
            self.assertEqual((response.status_code, response.json()["error_code"]),
                             (400, "invalid_expect_status"), bad)
            delay.assert_not_called()
            self.assertEqual((scene.status, scene.dialogue, self.snapshot(scene)),
                             (CartoonScene.STATUS_READY, "", before))


class LegacyAlreadyShotTests(AlreadyShotTests):
    markup = False


class QuotedChargeTests(_Pipeline):
    """Цена с кнопки = снимок = списано: сверка не трогает путь денег дальше."""

    def test_quoted_render_charges_exactly_the_quote(self):
        project = self.project(model=MINI, resolution="480p", duration=5)
        scene = self.scene(project)
        response = self.client.post(f"/api/cartoon/scenes/{scene.pk}/render/", {"quoted_credits": 35},
                                    format="json")
        self.assertEqual(response.status_code, 200, response.content)
        scene.refresh_from_db()
        self.assertEqual(scene.credits_planned, 35)
        # Док сменили, пока сцена в очереди, — списание всё равно по кнопке.
        self.client.patch(f"/api/cartoon/projects/{project.pk}/",
                          {"video_model": S20, "resolution": "1080p", "duration": 15}, format="json")
        seen = self.shoot(scene)
        self.assertEqual(seen["result"]["status"], "ready", seen["result"])
        self.assertEqual((self.charges("cartoon_keyframe"), self.charges("cartoon_scene")), ([7], [28]))
        self.assertEqual(self.user.token_balance, 10000 - 35)

    def test_refused_quote_never_reaches_the_task(self):
        project = self.project(model=MINI, resolution="480p", duration=5)
        scene = self.scene(project)
        self.client.patch(f"/api/cartoon/projects/{project.pk}/",
                          {"video_model": S20, "resolution": "1080p", "duration": 15}, format="json")
        response = self.client.post(f"/api/cartoon/scenes/{scene.pk}/render/", {"quoted_credits": 35},
                                    format="json")
        self.assertEqual(response.status_code, 409, response.content)
        # Задача, если бы её кто-то всё же запустил, сцену не возьмёт: она не в «Ожидает».
        seen = self.shoot(scene)
        self.assertEqual((seen["video"], seen["frame"]), ([], []))
        self.assertEqual((self.charges("cartoon_keyframe"), self.charges("cartoon_scene")), ([], []))
        self.assertEqual(self.user.token_balance, 10000)

    def test_stale_render_after_ready_charges_nothing_more(self):
        """Ревью C_R1_money_r1: та же кнопка «Снять» (35) после готовой сцены переснимала
        её за 28 и заменяла ролик. Теперь — 409, задача сцену не берёт, списано один раз."""
        project = self.project(model=MINI, resolution="480p", duration=5)
        scene = self.scene(project)
        response = self.client.post(f"/api/cartoon/scenes/{scene.pk}/render/", {"quoted_credits": 35},
                                    format="json")
        self.assertEqual(response.status_code, 200, response.content)
        first = self.shoot(scene)
        self.assertEqual(first["result"]["status"], "ready", first["result"])
        video = scene.video
        self.assertTrue(video)
        self.assertEqual(self.user.token_balance, 10000 - 35)

        response = self.client.post(f"/api/cartoon/scenes/{scene.pk}/render/", {"quoted_credits": 35},
                                    format="json")
        self.assertEqual((response.status_code, response.json()["error_code"]), (409, "already_shot"))
        second = self.shoot(scene)
        self.assertEqual((second["video"], second["frame"]), ([], []))
        self.assertEqual((scene.status, scene.video), (CartoonScene.STATUS_READY, video))
        self.assertEqual((self.charges("cartoon_keyframe"), self.charges("cartoon_scene")), ([7], [28]))
        self.assertEqual(self.user.token_balance, 10000 - 35)


class ExpectShotTests(QuoteBase):
    """Кнопки пересъёмки из меню готовой сцены в боте (ревью C_R1_money_r2, W9):
    в них метка ролика (shot_token), сервер сверяет её (expect_shot). Сцену с тех пор
    пересняли — 409 already_shot; переснимают или пересъёмка не удалась — 409
    scene_changed. Ни задачи, ни снимка, ни списания, ролик прежний."""

    def ready(self, project, **extra):
        fields = dict(status=CartoonScene.STATUS_READY, video=OLD_VIDEO, keyframe=OLD_FRAME,
                      shot_model=self.models[MINI], shot_resolution="480p", shot_duration=5,
                      shot_aspect="16:9", credits_planned=35, shot_video_credits=28)
        fields.update(extra)
        return self.scene(project, **fields)

    def button(self, project, scene, **extra) -> dict:
        """Тело кнопки «🔁 С тем же кадром» меню готовой сцены, как его шлёт бот."""
        row = self.row(project, scene)
        return {"quoted_credits": row["render_credits"], "expect_status": "ready",
                "expect_shot": row["shot_token"], **extra}

    def test_token_is_in_the_scene_json_and_follows_the_video(self):
        project = self.project(model=MINI, resolution="480p", duration=5)
        scene = self.ready(project)
        token = self.row(project, scene)["shot_token"]
        self.assertRegex(token, r"^[0-9a-f]{8}$")
        CartoonScene.objects.filter(pk=scene.pk).update(mixed_video="cartoon/mixed/m.mp4")
        # Звук свели — ролик тот же: метка не меняется.
        self.assertEqual(self.row(project, scene)["shot_token"], token)
        CartoonScene.objects.filter(pk=scene.pk).update(video="cartoon/scenes/other.mp4")
        self.assertNotEqual(self.row(project, scene)["shot_token"], token)
        draft = self.scene(project)
        self.assertEqual(self.row(project, draft)["shot_token"], "")

    def test_matching_token_reshoots(self):
        project = self.project(model=MINI, resolution="480p", duration=5)
        scene = self.ready(project)
        body = self.button(project, scene)
        response, delay = self.patch_retry(scene, body)
        self.assertEqual(response.status_code, 200, response.content)
        delay.assert_called_once_with(scene.pk)
        self.assertEqual((scene.status, scene.credits_planned),
                         (CartoonScene.STATUS_NEW, body["quoted_credits"]))

    def test_reshot_since_is_already_shot(self):
        project = self.project(model=MINI, resolution="480p", duration=5)
        scene = self.ready(project, dialogue="")
        body = self.button(project, scene)
        # Сцену пересняли (этой же кнопкой, на сайте): ролик другой.
        CartoonScene.objects.filter(pk=scene.pk).update(video="cartoon/scenes/again.mp4")
        scene.refresh_from_db()
        before = self.snapshot(scene)
        for extra in ({}, {"new_keyframe": True}, {"dialogue": "Привет"}):
            response, delay = self.patch_retry(scene, {**body, **extra})
            self.assert_untouched(scene, CartoonScene.STATUS_READY, before, response, delay)
            self.assertEqual(response.json()["error_code"], "already_shot")
            # Отказ — до любых правок: реплика не записана, кадр на месте.
            self.assertEqual((scene.video, scene.keyframe, scene.dialogue),
                             ("cartoon/scenes/again.mp4", OLD_FRAME, ""))

    def test_reshooting_or_failed_since_is_scene_changed(self):
        project = self.project(model=MINI, resolution="480p", duration=5)
        for status in (CartoonScene.STATUS_NEW, CartoonScene.STATUS_VIDEO, CartoonScene.STATUS_FAILED):
            scene = self.ready(project)
            body = self.button(project, scene)
            # Пересъёмка из этого меню уже идёт или не удалась (прежний ролик остался).
            CartoonScene.objects.filter(pk=scene.pk).update(status=status)
            scene.refresh_from_db()
            before, reserved = self.snapshot(scene), cp.reserved_credits(self.user)
            response, delay = self.patch_retry(scene, body)
            self.assertEqual(response.status_code, 409, response.content)
            delay.assert_not_called()
            # Резерв идущей съёмки — её собственный; новой не прибавилось.
            self.assertEqual((scene.status, self.snapshot(scene), cp.reserved_credits(self.user)),
                             (status, before, reserved))
            self.assertFalse(TokenTransaction.objects.filter(user=self.user).exists())
            CartoonScene.objects.filter(pk=scene.pk).delete()
            answer = response.json()
            self.assertEqual((answer["error_code"], answer["scene"]["status"]), ("scene_changed", status))
            self.assertEqual(scene.video, OLD_VIDEO)

    def test_reshot_between_the_read_and_the_update_is_refused(self):
        project = self.project(model=MINI, resolution="480p", duration=5)
        scene = self.ready(project)
        body = self.button(project, scene)

        def reshot_elsewhere(s):
            CartoonScene.objects.filter(pk=s.pk).update(video="cartoon/scenes/again.mp4")

        with patch("cartoon.views._attach_ready_keyframe", side_effect=reshot_elsewhere):
            response, delay = self.patch_retry(scene, body)
        self.assertEqual((response.status_code, response.json()["error_code"]), (409, "already_shot"))
        delay.assert_not_called()
        self.assertEqual((scene.status, scene.video, scene.credits_planned),
                         (CartoonScene.STATUS_READY, "cartoon/scenes/again.mp4", 35))
        self.assertEqual(cp.reserved_credits(self.user), 0)

    def test_bad_token_is_400_and_changes_nothing(self):
        project = self.project(model=MINI, resolution="480p", duration=5)
        scene = self.ready(project, dialogue="")
        before = self.snapshot(scene)
        for bad in ("XYZ", "0123456789abcdef0", 5, True, ["ab"], "ab cd"):
            response, delay = self.patch_retry(scene, {"expect_shot": bad, "dialogue": "Привет"})
            answer = response.json()
            self.assertEqual((response.status_code, answer["error_code"], answer["field"]),
                             (400, "invalid_expect_status", "expect_shot"), bad)
            delay.assert_not_called()
            self.assertEqual((scene.status, scene.dialogue, self.snapshot(scene)),
                             (CartoonScene.STATUS_READY, "", before))


class LegacyExpectShotTests(ExpectShotTests):
    markup = False


class ExpectShotChargeTests(_Pipeline):
    """Настоящая render_scene: кнопка «🔁 С тем же кадром» из меню готовой сцены, нажатая
    второй раз после своей же пересъёмки, больше не снимает и не списывает (W9)."""

    def shoot_as(self, scene, video):
        with patch("cartoon.tasks.generate_scene_video", return_value=video), \
                patch("cartoon.services.generate_keyframe", return_value="cartoon/keyframes/k.png"), \
                patch("cartoon.director._ask", return_value={"prompt": "p", "negative": "n"}), \
                patch("cartoon.tasks.last_frame_of", return_value=""), \
                patch("cartoon.tasks._notify_scene"), patch("cartoon.audio.remix_scene"), \
                patch("cartoon.tasks.remember_pair_video"):
            result = render_scene_task.apply(args=[scene.pk]).get()
        scene.refresh_from_db()
        self.user.refresh_from_db()
        return result

    def menu_button(self, project, scene) -> dict:
        """Тело кнопки меню готовой сцены, как его шлёт бот."""
        row = next(s for s in self.client.get(f"/api/cartoon/projects/{project.pk}/").json()["scenes"]
                   if s["id"] == scene.pk)
        return {"retry": True, "new_keyframe": False, "quoted_credits": row["render_credits"],
                "expect_status": "ready", "expect_shot": row["shot_token"]}

    def test_ready_menu_button_pressed_twice(self):
        project = self.project(model=MINI, resolution="480p", duration=5)
        scene = self.scene(project)
        self.client.post(f"/api/cartoon/scenes/{scene.pk}/render/", {"quoted_credits": 35}, format="json")
        self.assertEqual(self.shoot_as(scene, "cartoon/scenes/v1.mp4")["status"], "ready")
        button = self.menu_button(project, scene)
        r = self.client.patch(f"/api/cartoon/scenes/{scene.pk}/", button, format="json")
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(self.shoot_as(scene, "cartoon/scenes/v2.mp4")["status"], "ready")
        paid = (self.charges("cartoon_keyframe"), self.charges("cartoon_scene"))
        self.assertEqual(paid, ([7], [28, 28]))

        # Та же кнопка того же сообщения: ролик с тех пор другой — 409, задача сцену не берёт.
        r = self.client.patch(f"/api/cartoon/scenes/{scene.pk}/", button, format="json")
        self.assertEqual((r.status_code, r.json()["error_code"]), (409, "already_shot"))
        self.assertEqual(self.shoot_as(scene, "cartoon/scenes/v3.mp4"), {"status": "not_queued"})
        self.assertEqual((scene.status, scene.video), (CartoonScene.STATUS_READY, "cartoon/scenes/v2.mp4"))
        self.assertEqual((self.charges("cartoon_keyframe"), self.charges("cartoon_scene")), paid)
        self.assertEqual(self.user.token_balance, 10000 - 35 - 28)
