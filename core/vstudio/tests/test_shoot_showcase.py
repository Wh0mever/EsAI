"""Команда vstudio_shoot_showcase: съёмка роликов сценариев для карусели.

Провайдер подменён на границе, как в тестах конвейера (ai.media_provider.*,
ai.video_edit.*), каталог OpenRouter — спеками из caps_fixtures. Задачи
записываются через pipeline._enqueue, а «воркер» выполняет их, пока команда
спит между проверками базы: её time подменён часами теста. Запросы команды
идут в настоящие вьюхи студии, поэтому класс — TransactionTestCase: задача
дубля ставится после настоящей фиксации транзакции, как на сервере.

Главное, что проверяем:
- пробный прогон не пишет в базу ни строки;
- деньги: в резерве и в списании ровно цена из плана, списание — только за
  готовое, неудачный дубль бесплатен и в витрину не попадает;
- повторный запуск с той же меткой ничего не переснимает;
- Image → Video: сначала картинка, потом ролик с ней первым кадром.
"""
import io
import re
from types import SimpleNamespace
from unittest import mock

from django.core.cache import cache
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import OperationalError, connection
from django.test import SimpleTestCase, TransactionTestCase, override_settings
from django.test.utils import CaptureQueriesContext
from rest_framework.throttling import SimpleRateThrottle

from ai import media_provider as mp
from ai.models import GPTModels
from audit.models import AdminActionLog
from plans.models import TokenTransaction
from vstudio import pipeline, showcase, views
from vstudio import serializers as S
from vstudio import showcase_scenarios as scen
from vstudio.management.commands import vstudio_shoot_showcase as cmd
from vstudio.models import Asset, Project, Shot, ShotInput, ShowcaseItem, Take
from vstudio.tests import factories as f
from vstudio.tests.caps_fixtures import HAILUO_23, KLING_STD, SEEDANCE_20, VEO_FAST
from vstudio.tests.test_pipeline import png_b64, write_mp4

SITE = "https://esai.kg"
CMD = "vstudio.management.commands.vstudio_shoot_showcase"

SEEDANCE = "bytedance/seedance-2.0"
SEEDANCE_FAST = "bytedance/seedance-2.0-fast"
VEO_FAST_ID = "google/veo-3.1-fast"
VEO_LITE = "google/veo-3.1-lite"
KLING = "kwaivgi/kling-v3.0-std"
HAILUO = "minimax/hailuo-2.3"
KLEIN = "black-forest-labs/flux.2-klein-4b"
FLUX_PRO = "black-forest-labs/flux.2-pro"

# Прайс «за секунду» и отдельная плата за входное фото: ролик с первым кадром
# стоит дороже ролика по тексту — на этом держится проверка оценки для i2v.
PRICED = dict(SEEDANCE_20, supported_resolutions=["480p", "720p", "1080p"], pricing_skus={
    "duration_seconds_480p": "0.05", "duration_seconds_720p": "0.10",
    "duration_seconds_1080p": "0.25", "reference_images": "0.04"})
SPECS = {SEEDANCE: PRICED, SEEDANCE_FAST: dict(PRICED, id=SEEDANCE_FAST), VEO_FAST_ID: VEO_FAST,
         VEO_LITE: dict(VEO_FAST, id=VEO_LITE), KLING: KLING_STD, HAILUO: HAILUO_23}

# Какая модель достаётся сценарию при каталоге из setUp.
EXPECTED_MODELS = {
    "film": SEEDANCE, "ad": SEEDANCE, "person": KLING, "car": SEEDANCE, "action": KLING,
    "scifi": VEO_LITE, "fashion": SEEDANCE, "music": SEEDANCE, "i2v": SEEDANCE, "anim": HAILUO,
    "real": VEO_LITE, "vertical": SEEDANCE,
}
BRIEF_KEYS = ("film", "ad", "person", "car", "action", "scifi", "fashion", "music", "i2v", "anim",
              "real", "vertical")


def row(name, *, locked=False, price=10, frames=("first_frame", "last_frame"), **caps):
    """ModelJSON в том объёме, который читает выбор модели."""
    return {"id": name.lower().replace(" ", "-"), "name": name, "locked": locked, "price_from": price,
            "caps": {"durations": [], "resolutions": [], "aspect_ratios": [], "frames": list(frames),
                     **caps},
            "defaults": {}}


# ---------------------------------------------------------------- выбор модели и параметров

class PickModelTests(SimpleTestCase):
    def names(self, rows, fragments, **kw):
        choice = cmd.pick_model(rows, fragments, **kw)
        return (choice.row["name"] if choice.row else None), choice

    def test_exact_name_wins_over_lite_and_fast(self):
        rows = [row("Veo 3.1 Lite"), row("Veo 3.1 Fast"), row("Veo 3.1")]
        name, choice = self.names(rows, ["veo 3.1"])
        self.assertEqual(name, "Veo 3.1")
        self.assertIn("точное название", choice.why)

    def test_fragment_never_takes_a_lighter_variant_unless_it_says_so(self):
        rows = [row("Veo 3.1 Lite"), row("Veo 3.1 Fast"), row("Seedance 2.0 mini"), row("Seedance 2.0")]
        name, choice = self.names(rows, ["Veo 3.1", "Seedance 2.0"])
        self.assertEqual(name, "Seedance 2.0")
        self.assertEqual(choice.skipped, ["«Veo 3.1» — такой модели в студии нет"])
        self.assertEqual(self.names(rows, ["Veo 3.1 Lite"])[0], "Veo 3.1 Lite")
        self.assertEqual(self.names(rows, ["VEO  3.1 fast"])[0], "Veo 3.1 Fast")

    def test_shortest_name_with_the_fragment(self):
        rows = [row("Kling 3.0 Pro Max"), row("Kling 3.0 Std"), row("Kling 3.0 Pro"), row("Hailuo 3")]
        name, choice = self.names(rows, ["Kling"])
        self.assertEqual(name, "Kling 3.0 Std")   # при равной длине — порядок каталога
        self.assertIn("самое короткое", choice.why)

    def test_locked_model_gives_way_to_the_next_fragment(self):
        rows = [row("Veo 3.1", locked=True), row("Seedance 2.0")]
        name, choice = self.names(rows, ["Veo 3.1", "Seedance 2.0"])
        self.assertEqual(name, "Seedance 2.0")
        self.assertEqual(choice.skipped, ["«Veo 3.1» — Veo 3.1: закрыто тарифом аккаунта"])

    def test_falls_back_to_the_studio_default(self):
        rows = [row("Wan 2.7", locked=True), row("Hailuo 3"), row("Grok Imagine")]
        name, choice = self.names(rows, ["Seedance 2.5", "Wan"])
        self.assertEqual(name, "Hailuo 3")   # первая открытая в каталоге
        self.assertEqual(choice.why, "модель студии по умолчанию")
        self.assertEqual(len(choice.skipped), 2)
        name, choice = self.names([row("Wan 2.7", locked=True)], ["Wan"])
        self.assertIsNone(name)
        self.assertEqual(choice.why, "нет доступной модели")
        self.assertIsNone(cmd.pick_model([], ["Wan"]).row)

    def test_first_frame_is_required_for_image_to_video(self):
        rows = [row("Seedance 2.0", frames=()), row("Kling 3.0 Std")]
        name, choice = self.names(rows, ["Seedance 2.0"], first_frame=True)
        self.assertEqual(name, "Kling 3.0 Std")
        self.assertIn("не умеет начинать видео с кадра", choice.skipped[0])
        self.assertIsNone(cmd.pick_model([row("Seedance 2.0", frames=())], [], first_frame=True).row)

    def test_scenario_aspect_is_required_like_the_first_frame(self):
        rows = [row("Hailuo 2.3", aspect_ratios=["16:9"]), row("Seedance 2.0", aspect_ratios=["16:9"]),
                row("Kling 3.0 Std", aspect_ratios=["16:9", "9:16"])]
        name, choice = self.names(rows, ["Seedance 2.0"], aspect="9:16")
        self.assertEqual(name, "Kling 3.0 Std")   # первая открытая, что умеет 9:16
        self.assertEqual(choice.skipped, ["«Seedance 2.0» — Seedance 2.0: не умеет 9:16"])
        name, choice = self.names(rows, ["Seedance 2.0", "Kling"], aspect="9:16")
        self.assertEqual((name, choice.why), ("Kling 3.0 Std", "самое короткое название с «Kling»"))
        # Пропорции, которые модель умеет, и выбор без пропорций — как раньше.
        self.assertEqual(self.names(rows, ["Seedance 2.0"], aspect="16:9")[0], "Seedance 2.0")
        self.assertEqual(self.names(rows, ["Seedance 2.0"])[0], "Seedance 2.0")
        # Ни одна открытая не умеет — сценарий без модели, а не на чужих пропорциях.
        name, choice = self.names(rows[:2], ["Seedance 2.0"], aspect="9:16")
        self.assertIsNone(name)
        self.assertEqual(choice.why, "нет доступной модели (открытые не умеют 9:16)")
        choice = cmd.pick_model([row("Seedance 2.0", frames=())], [], first_frame=True)
        self.assertEqual(choice.why, "нет доступной модели (открытые не умеют начинать видео с кадра)")

    def test_cheapest_picture_model(self):
        rows = [row("FLUX.2 Pro", price=10), row("FLUX.2 Klein", price=4), row("FLUX.2 Fast", price=6),
                row("Nano Banana", price=1)]
        name, choice = self.names(rows, ["FLUX", "Klein"], cheapest=True)
        self.assertEqual(name, "FLUX.2 Klein")
        self.assertIn("самая дешёвая", choice.why)
        self.assertEqual(self.names([row("Klein", price=3)], ["FLUX", "Klein"], cheapest=True)[0], "Klein")


class FitParamsTests(SimpleTestCase):
    WANTED = {"duration": 5, "resolution": "720p", "aspect_ratio": "16:9"}

    def fit(self, wanted=None, *, kind="video", defaults=None, **caps):
        model = row("Model", **caps)
        model["defaults"] = defaults or {}
        return cmd.fit_params(model, kind, wanted or self.WANTED)

    def test_supported_values_stay(self):
        params, changes = self.fit(durations=[4, 5, 6], resolutions=["480p", "720P"],
                                   aspect_ratios=["16:9", "9:16"])
        self.assertEqual(params, {"duration": 5, "resolution": "720P", "aspect_ratio": "16:9"})
        self.assertEqual(changes, [])

    def test_duration_goes_to_the_nearest_and_smaller_on_a_tie(self):
        params, changes = self.fit(durations=[4, 6, 8], resolutions=["720p"], aspect_ratios=["16:9"])
        self.assertEqual(params["duration"], 4)
        self.assertEqual(changes, ["длительность: 5 → 4 (модель умеет: 4, 6, 8)"])
        self.assertEqual(self.fit(durations=[6, 10], resolutions=["720p"],
                                  aspect_ratios=["16:9"])[0]["duration"], 6)

    def test_resolution_and_aspect_fall_back_to_the_model_defaults(self):
        params, changes = self.fit(
            {"duration": 6, "resolution": "720p", "aspect_ratio": "9:16"},
            durations=[6, 10], resolutions=["768p", "1080p"], aspect_ratios=["16:9", "1:1"],
            defaults={"duration": 6, "resolution": "1080p", "aspect_ratio": "16:9"})
        self.assertEqual(params, {"duration": 6, "resolution": "1080p", "aspect_ratio": "16:9"})
        self.assertEqual(len(changes), 2)
        self.assertIn("пропорции: 9:16 → 16:9", changes[1])
        # Без значения по умолчанию: первое качество из списка и пропорции «авто».
        params, _ = self.fit(durations=[5], resolutions=["1080p"], aspect_ratios=["1:1"])
        self.assertEqual((params["resolution"], params["aspect_ratio"]), ("1080p", "auto"))

    def test_picture_gets_only_the_aspect(self):
        params, changes = self.fit({"aspect_ratio": "16:9"}, kind="image", aspect_ratios=["1:1", "16:9"])
        self.assertEqual((params, changes), ({"aspect_ratio": "16:9"}, []))
        params, changes = self.fit({"aspect_ratio": "21:9"}, kind="image", aspect_ratios=["1:1"])
        self.assertEqual(params, {"aspect_ratio": "auto"})
        self.assertEqual(len(changes), 1)


class ScenarioDataTests(SimpleTestCase):
    def test_twelve_scenarios_in_carousel_order(self):
        self.assertEqual(scen.KEYS, BRIEF_KEYS)
        self.assertEqual(scen.KEYS, tuple(ShowcaseItem.SCENARIOS))
        labels = dict(ShowcaseItem.CATEGORY_CHOICES)
        for n, sc in enumerate(scen.SCENARIOS, start=1):
            self.assertEqual(sc.title, labels[sc.key])
            self.assertEqual(scen.sort_for(sc.key), 10 * n)
            self.assertTrue(sc.models)
            self.assertTrue(sc.prompt.endswith("no watermark."), sc.key)
            self.assertEqual((sc.params["duration"], sc.params["resolution"]), (5, "720p"))
            self.assertEqual(sc.params["aspect_ratio"], "9:16" if sc.key == "vertical" else "16:9")

    def test_only_image_to_video_starts_from_a_picture(self):
        for sc in scen.SCENARIOS:
            is_i2v = sc.key == "i2v"
            self.assertEqual(sc.mode, "i2v" if is_i2v else "t2v")
            self.assertEqual(bool(sc.image_prompt), is_i2v)
            self.assertEqual(bool(sc.image_models), is_i2v)

    def test_client_ids_fit_the_api(self):
        longest = "L" * 24
        for key in scen.KEYS:
            for part in (cmd.PART_VIDEO, cmd.PART_IMAGE):
                self.assertRegex(cmd.client_id(longest, key, part), S.CLIENT_REQUEST_ID_RE)
        self.assertNotEqual(cmd.client_id("v1", "i2v"), cmd.client_id("v1", "i2v", cmd.PART_IMAGE))
        self.assertNotEqual(cmd.client_id("v1", "film"), cmd.client_id("v2", "film"))


# ---------------------------------------------------------------- команда

@override_settings(VSTUDIO_MODE="staff", SITE_BASE_URL=SITE, VSTUDIO_INLINE_REFS=False,
                   VSTUDIO_MIN_PROVIDER_USD=0, VSTUDIO_MAX_OPEN_VIDEO=2, VSTUDIO_MAX_OPEN_IMAGE=4)
class ShootCase(TransactionTestCase):
    """Обвязка: каталог студии, подменённый провайдер, «воркер» и часы вместо time."""

    BALANCE = 100_000

    def setUp(self):
        cache.clear()
        self.media = self.enterContext(f.media_root())
        self.staff = f.make_user("boss@example.com", balance=self.BALANCE, is_staff=True)
        f.make_gpt_model(SEEDANCE, name="Seedance 2.0", markup=5, sort_order=10)
        f.make_gpt_model(SEEDANCE_FAST, name="Seedance 2.0 Fast", markup=3)
        f.make_gpt_model(VEO_FAST_ID, name="Veo 3.1 Fast", markup=12)
        f.make_gpt_model(VEO_LITE, name="Veo 3.1 Lite", markup=8)
        f.make_gpt_model(KLING, name="Kling 3.0 Std", markup=10)
        f.make_gpt_model(HAILUO, name="Hailuo 2.3", markup=7)
        f.make_gpt_model(FLUX_PRO, name="FLUX.2 Pro", markup=10, category="image")
        f.make_gpt_model(KLEIN, name="FLUX.2 Klein", markup=4, category="image")

        self.enterContext(mock.patch("ai.handlers._openrouter_video_catalog",
                                     side_effect=lambda mid: dict(SPECS.get(mid) or {})))
        self.enterContext(mock.patch("ai.video_cost.cheapest_credit_usd", return_value=0.01))
        self.enterContext(mock.patch("ai.video_cost.min_margin", return_value=0.4))
        self.enterContext(mock.patch("users.webpush.notify_user", return_value={}))
        # Сборку лёгкой копии ставит каждая новая строка витрины — ffmpeg в тестах не зовём.
        self.clip_task = self.enterContext(
            mock.patch("vstudio.tasks.build_showcase_clip.apply_async"))

        # Провайдер: всё снимается, кроме запросов со словом из self.reject.
        self.reject = None
        self.image_error = None
        self.submitted = []
        self.pictures = []
        self.enterContext(mock.patch("ai.media_provider.submit_video", side_effect=self._submit))
        self.enterContext(mock.patch("ai.media_provider.poll_video", side_effect=self._poll))
        self.enterContext(mock.patch("ai.media_provider.download_to_file", side_effect=write_mp4))
        self.enterContext(mock.patch("ai.media_provider.generate_image", side_effect=self._image))
        self.enterContext(mock.patch("ai.video_edit.probe_video",
                                     return_value={"width": 1280, "height": 720, "duration": 5.04}))
        self.enterContext(mock.patch("ai.video_edit.extract_poster",
                                     return_value=f.image_bytes(1280, 720)))

        # Воркер и часы: задачи выполняются, пока команда «спит».
        self.tasks = []
        self.worker_on = True
        self.clock = 0.0
        self.peak_open_video = 0
        self.enterContext(mock.patch("vstudio.pipeline._enqueue", side_effect=self._enqueue))
        self.enterContext(mock.patch(f"{CMD}.time", SimpleNamespace(
            sleep=self._sleep, monotonic=lambda: self.clock)))

        # Каждый запрос команды во вьюху — с его ответом.
        self.posts = []
        real_post = cmd.Command._post

        def spy(command, view_cls, path, body):
            status, data = real_post(command, view_cls, path, body)
            self.posts.append((path, status, body.get("client_request_id"), data))
            return status, data

        self.enterContext(mock.patch.object(cmd.Command, "_post", spy))

    # --- провайдер

    def _submit(self, body, **_kw):
        self.submitted.append(body)
        if self.reject and self.reject in body["prompt"]:
            return mp.Submit(state=mp.STATE_REJECTED, status_code=400, text="content policy violation")
        job = f"gen-{len(self.submitted)}"
        return mp.Submit(state=mp.STATE_ACCEPTED, job_id=job, status_code=200,
                         polling_url=f"https://openrouter.ai/api/v1/videos/{job}")

    def _poll(self, url, **_kw):
        return mp.Poll(status="completed", urls=[f"{url}/content?index=0"], cost=0.5, status_code=200)

    def _image(self, body, **_kw):
        self.pictures.append(body)
        if self.image_error:
            return mp.Images(error=self.image_error, status_code=400)
        return mp.Images(items=[mp.ImageItem(b64=png_b64(1344, 768), media_type="image/jpeg")],
                         cost=0.01, status_code=200)

    # --- воркер и часы

    def _enqueue(self, name, take_id, countdown=None, **kwargs):
        self.tasks.append((name, take_id, kwargs))
        return True

    def _work(self):
        runners = {"submit_take": pipeline.submit, "poll_take": pipeline.poll,
                   "finalize_take": pipeline.finalize, "run_image_take": pipeline.run_image}
        for _ in range(500):
            if not self.tasks:
                break
            name, take_id, kwargs = self.tasks.pop(0)
            if name not in runners:
                continue   # уведомления — не часть конвейера денег
            if name == "poll_take":
                # countdown «уже прошёл»
                Take.objects.filter(pk=take_id).update(next_poll_at=None)
            runners[name](take_id, **kwargs)

    def _sleep(self, seconds):
        self.clock += seconds
        open_now = Take.objects.filter(kind=Take.KIND_VIDEO, status__in=Take.OPEN).count()
        self.peak_open_video = max(self.peak_open_video, open_now)
        if self.worker_on:
            self._work()

    # --- помощники

    def run_command(self, *args, user=None, yes=True, out=None):
        # out — свой поток: когда команда кончается ошибкой, напечатанное иначе не достать.
        out = io.StringIO() if out is None else out
        argv = ["--user", (user or self.staff).email, *args]
        if yes and "--dry-run" not in args:
            argv.append("--yes")
        call_command("vstudio_shoot_showcase", *argv, stdout=out)
        return out.getvalue()

    def launches(self):
        return [(status, cid) for path, status, cid, _data in self.posts if path == "shots/"]

    def planned_total(self, output) -> int:
        return int(re.search(r"Всего (\d+) кр", output).group(1))

    def balance(self, user=None) -> int:
        user = user or self.staff
        return type(user).objects.get(pk=user.pk).token_balance

    def ledger(self):
        return list(TokenTransaction.objects.filter(user=self.staff).order_by("id"))

    def take_of(self, key, label="v1", part=cmd.PART_VIDEO) -> Take:
        return Take.objects.select_related("shot", "result_asset").get(
            user=self.staff, client_request_id=cmd.client_id(label, key, part))

    def row_counts(self) -> dict:
        models = (Project, Shot, ShotInput, Take, Asset, ShowcaseItem, TokenTransaction, AdminActionLog)
        return {m.__name__: m.objects.count() for m in models}

    def assert_money_rule(self):
        for take in Take.objects.all():
            self.assertEqual(take.status in Take.OPEN, take.charge_state == Take.CHARGE_RESERVED,
                             f"{take.client_request_id}: {take.status}/{take.charge_state}")
            if take.charge_state == Take.CHARGE_CHARGED:
                self.assertEqual(take.credits_charged, take.credits_reserved)
                self.assertEqual(take.credits_charged, take.credits_quoted)
            else:
                self.assertEqual(take.credits_charged, 0)
        charged = sum(t.credits_charged for t in Take.objects.all())
        self.assertEqual(-sum(t.delta for t in self.ledger()), charged)
        self.assertEqual(self.balance(), self.BALANCE - charged)
        return charged


class DryRunTests(ShootCase):
    def test_dry_run_prints_the_plan_and_writes_nothing(self):
        before = self.row_counts()
        with CaptureQueriesContext(connection) as queries:
            out = self.run_command("--dry-run")
        writes = [q["sql"] for q in queries
                  if q["sql"].lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE", "REPLACE"))]
        self.assertEqual(writes, [])
        self.assertEqual(self.row_counts(), before)
        self.assertEqual(self.balance(), self.BALANCE)
        self.assertEqual((self.tasks, self.posts, self.submitted, self.pictures), ([], [], [], []))
        self.assertIn("Пробный прогон: ничего не запущено, в базу ничего не записано.", out)
        self.assertIn("К запуску: видео — 12, картинок — 1.", out)
        self.assertIn("Режим студии: staff", out)
        for key in scen.KEYS:
            self.assertRegex(out, rf"\n\s*\d+  {key} · ")
        total = self.planned_total(out)
        self.assertGreater(total, 0)
        self.assertIn(f"свободно {self.BALANCE} — хватает, останется {self.BALANCE - total} кр.", out)

    def test_plan_names_the_model_and_every_changed_param(self):
        out = self.run_command("--dry-run")
        self.assertIn("film: Seedance 2.0 — точное название «Seedance 2.0». Пропущено: «Veo 3.1» — "
                      "такой модели в студии нет; «Seedance 2.5» — такой модели в студии нет.", out)
        self.assertIn("person: Kling 3.0 Std — самое короткое название с «Kling».", out)
        self.assertIn("scifi: Veo 3.1 Lite — точное название «Veo 3.1 Lite».", out)
        self.assertIn("i2v (кадр): FLUX.2 Klein — самая дешёвая из «FLUX».", out)
        self.assertIn("scifi: длительность: 5 → 4 (модель умеет: 4, 6, 8)", out)
        self.assertIn("anim: длительность: 5 → 6 (модель умеет: 6, 10)", out)
        self.assertIn("anim: качество: 720p → 1080p (модель умеет: 1080p)", out)
        self.assertNotIn("vertical: пропорции", out)

    def test_locked_models_are_skipped_for_an_unpaid_account(self):
        free = f.make_user("free-staff@example.com", balance=5000, is_staff=True, is_paid=False)
        GPTModels.objects.filter(openrouter_id=HAILUO).update(free_tier=True)
        out = self.run_command("--dry-run", "--only", "film,ad", user=free)
        self.assertIn("У аккаунта не платный тариф", out)
        self.assertIn("film: Hailuo 2.3 — модель студии по умолчанию.", out)
        self.assertIn("«Seedance 2.0» — Seedance 2.0: закрыто тарифом аккаунта", out)
        self.assertIn("К запуску: видео — 2, картинок — 0.", out)

    def test_nothing_to_shoot_when_every_model_is_locked(self):
        free = f.make_user("free-staff@example.com", balance=5000, is_staff=True, is_paid=False)
        out = self.run_command("--only", "film,i2v", user=free)
        self.assertIn("нельзя: нет доступной модели", out)
        self.assertIn("Запускать нечего", out)
        self.assertEqual(self.posts, [])
        self.assertFalse(Take.objects.exists())


class RefusalTests(ShootCase):
    def refused(self, *args, **kw) -> str:
        before = self.row_counts()
        with self.assertRaises(CommandError) as ctx:
            self.run_command(*args, **kw)
        self.assertEqual(self.row_counts(), before)
        self.assertEqual(self.posts, [])
        return str(ctx.exception)

    def test_only_a_staff_account_may_shoot(self):
        client = f.make_user("client@example.com", balance=5000)
        self.assertIn("не сотрудник", self.refused(user=client))
        self.assertIn("не сотрудник", self.refused("--dry-run", user=client))
        self.assertIn("не найден", self.refused(user=SimpleNamespace(email="nobody@example.com")))
        type(self.staff).objects.filter(pk=self.staff.pk).update(is_active=False)
        self.assertIn("отключён", self.refused())

    def test_studio_must_let_this_account_generate(self):
        with override_settings(VSTUDIO_MODE="off"):
            message = self.refused()
        self.assertIn("в режиме «off»", message)
        with mock.patch("adminapi.runtime.get_runtime", return_value="off"):
            self.assertIn("в режиме «off»", self.refused("--dry-run"))

    def test_scenario_keys_must_be_deployed(self):
        with mock.patch.object(showcase, "CATEGORIES", ("film", "ad", "music", "other")):
            message = self.refused("--dry-run")
            self.assertIn("В витрине нет сценариев: person, car", message)
            self.assertIn("vertical", message)
            # Сценарии, которые сервер уже знает, снять можно.
            self.assertIn("К запуску: видео — 2", self.run_command("--dry-run", "--only", "film,ad"))

    def test_bad_arguments(self):
        self.assertIn("нет сценариев cartoon", self.refused("--only", "film,cartoon"))
        self.assertIn("--label", self.refused("--label", "с пробелом"))
        self.assertIn("--label", self.refused("--label", "x" * 25))

    def test_empty_only_is_refused_instead_of_shooting_everything(self):
        # --only "$KEYS" с пустой переменной: без отказа это были бы все 12 сценариев.
        for empty in ("", ",", " , "):
            message = self.refused("--only", empty, "--label", "v2")
            self.assertIn("--only: пустой список сценариев", message)
            self.assertIn("film, ad", message)
        self.assertIn("К запуску: видео — 12, картинок — 1.", self.run_command("--dry-run"))

    def test_balance_must_cover_the_whole_plan(self):
        type(self.staff).objects.filter(pk=self.staff.pk).update(token_balance=100)
        message = self.refused("--only", "film,ad")
        self.assertIn("Баланса не хватает: нужно 168 кр, свободно 100 кр.", message)
        self.assertIn("НЕ ХВАТАЕТ 68 кр", self.run_command("--dry-run", "--only", "film,ad"))

    def test_shooting_needs_a_yes(self):
        with mock.patch("builtins.input", return_value="n") as asked:
            out = self.run_command("--only", "ad", yes=False)
        self.assertIn("Запустить съёмку на 84 кр?", asked.call_args.args[0])
        self.assertIn("Отменено: ничего не запущено.", out)
        self.assertEqual(self.posts, [])
        self.assertFalse(Take.objects.exists())
        with mock.patch("builtins.input", side_effect=EOFError):
            with self.assertRaises(CommandError):
                self.run_command("--only", "ad", yes=False)
        self.assertFalse(Take.objects.exists())
        with mock.patch("builtins.input", return_value="y"):
            out = self.run_command("--only", "ad", yes=False)
        self.assertIn("ad: готов, списано 84 кр", out)


class ShootTests(ShootCase):
    def test_shoots_all_twelve_and_puts_them_into_the_showcase_hidden(self):
        out = self.run_command()
        total = self.planned_total(out)

        takes = list(Take.objects.all())
        self.assertEqual(len(takes), 13)
        self.assertEqual({t.status for t in takes}, {Take.STATUS_DONE})
        self.assertEqual(self.assert_money_rule(), total)
        self.assertIn(f"Списано за этот запуск: {total} кр.", out)
        self.assertIn("Итог: снято — 12, не получилось — 0.", out)

        # Все запуски приняты с первого раза: лимит открытых видео команда держит сама.
        launches = self.launches()
        self.assertEqual([status for status, _cid in launches], [202] * 13)
        self.assertEqual(len({cid for _status, cid in launches}), 13)
        self.assertLessEqual(self.peak_open_video, 2)
        self.assertEqual(len(self.submitted), 12)
        self.assertEqual(len(self.pictures), 1)

        for n, sc in enumerate(scen.SCENARIOS, start=1):
            take = self.take_of(sc.key)
            self.assertEqual(take.model_ref, EXPECTED_MODELS[sc.key], sc.key)
            self.assertEqual(take.shot.prompt_text, sc.prompt)
            self.assertEqual(take.mode, sc.mode)
            item = ShowcaseItem.objects.get(take=take)
            self.assertEqual((item.category, item.title, item.sort), (sc.key, sc.title, 10 * n))
            self.assertEqual((item.is_active, item.show_prompt), (False, True))
            self.assertEqual(item.created_by, self.staff)
        self.assertEqual(ShowcaseItem.objects.count(), 12)
        self.assertEqual(showcase.public_items(), [])   # скрытые наружу не идут
        self.assertEqual(AdminActionLog.objects.filter(target_type="vstudio.showcaseitem").count(), 12)
        self.assertEqual(self.clip_task.call_count, 12)

        # Параметры: что модель умеет — как в сценарии, остальное — ближайшее.
        self.assertEqual(self.take_of("film").effective["duration"], 5)
        self.assertEqual(self.take_of("vertical").effective["aspect_ratio"], "9:16")
        self.assertEqual(self.take_of("scifi").effective["duration"], 4)
        anim = self.take_of("anim").effective
        self.assertEqual((anim["duration"], anim["resolution"]), (6, "1080p"))

        # Один проект на весь прогон, порядок запуска — порядок карусели.
        project = Project.objects.get()
        self.assertEqual((project.user, project.title), (self.staff, "Карусель: сценарии (v1)"))
        order = [cid for _status, cid in launches if not cid.endswith(":img")]
        self.assertEqual(order, [cmd.client_id("v1", key) for key in BRIEF_KEYS])

    def test_second_run_with_the_same_label_shoots_nothing(self):
        first = self.run_command("--only", "ad,car")
        charged = self.assert_money_rule()
        before = self.row_counts()
        self.posts.clear()
        self.submitted.clear()

        again = self.run_command("--only", "ad,car")
        self.assertEqual(self.row_counts(), before)
        self.assertEqual((self.posts, self.submitted), ([], []))
        self.assertEqual(self.assert_money_rule(), charged)
        self.assertIn("ad · Реклама товара", again)
        self.assertIn("уже снят", again)
        self.assertIn("К запуску: видео — 0, картинок — 0. Всего 0 кр.", again)
        self.assertIn("ad: снят ранее; уже в витрине", again)
        self.assertIn("были сняты раньше — 2", again)
        self.assertIn("Списано за этот запуск: 0 кр.", again)
        self.assertIn("ad: готов, списано 84 кр; в витрине №", first)

        # Новая метка — новая попытка, прежняя работа и её строка остаются.
        fresh = self.run_command("--only", "ad", "--label", "v2")
        self.assertIn("ad: готов, списано 84 кр", fresh)
        self.assertEqual(Take.objects.count(), 3)
        self.assertEqual(ShowcaseItem.objects.filter(category="ad").count(), 2)
        self.assertNotEqual(self.take_of("ad", "v2").pk, self.take_of("ad").pk)
        self.assertEqual(self.assert_money_rule(), charged + 84)

    def test_done_take_missing_from_the_showcase_is_added_on_the_next_run(self):
        self.run_command("--only", "ad")
        ShowcaseItem.objects.all().delete()
        out = self.run_command("--only", "ad")
        self.assertIn("ad: снят ранее; в витрине №", out)
        self.assertEqual(ShowcaseItem.objects.get().take, self.take_of("ad"))
        self.assertEqual(Take.objects.count(), 1)

    def test_failed_take_is_free_reported_and_gets_no_showcase_row(self):
        self.reject = "perfume"   # сценарий ad
        out = self.run_command("--only", "ad,car")
        ad, car = self.take_of("ad"), self.take_of("car")
        self.assertEqual((ad.status, ad.error_code, ad.charge_state, ad.credits_charged),
                         (Take.STATUS_FAILED, "prompt_rejected", Take.CHARGE_RELEASED, 0))
        self.assertEqual(car.status, Take.STATUS_DONE)
        self.assertEqual(self.assert_money_rule(), car.credits_charged)
        self.assertEqual([t.reason for t in self.ledger()], ["vstudio_video"])
        self.assertEqual([item.take for item in ShowcaseItem.objects.all()], [car])
        self.assertIn("ad: не получилось (prompt_rejected)", out)
        self.assertIn("car: готов, списано 84 кр", out)
        self.assertIn("Итог: снято — 1, не получилось — 1.", out)
        self.assertIn("Списано за этот запуск: 84 кр.", out)
        self.assertIn("Переснять неудачные: --only ad --label <новая метка>", out)

        # Та же метка неудачный сценарий не переснимает — только подсказывает как.
        self.posts.clear()
        again = self.run_command("--only", "ad,car")
        self.assertEqual(self.posts, [])
        self.assertEqual(Take.objects.count(), 2)
        self.assertIn("ad: в прошлый раз не получилось (prompt_rejected). Переснять: "
                      "--only ad --label <новая метка>", again)
        self.reject = None
        self.run_command("--only", "ad", "--label", "retry")
        self.assertEqual(self.take_of("ad", "retry").status, Take.STATUS_DONE)
        self.assertEqual(ShowcaseItem.objects.count(), 2)

    def test_image_to_video_shoots_the_picture_first_and_starts_from_it(self):
        out = self.run_command("--only", "i2v")
        picture = self.take_of("i2v", part=cmd.PART_IMAGE)
        video = self.take_of("i2v")
        self.assertEqual((picture.kind, picture.mode, picture.status, picture.model_ref),
                         ("image", Take.MODE_T2I, Take.STATUS_DONE, KLEIN))
        self.assertEqual(picture.shot.prompt_text, scen.BY_KEY["i2v"].image_prompt)
        self.assertEqual(picture.effective, {"aspect_ratio": "16:9"})
        frame = picture.result_asset
        self.assertEqual((frame.status, frame.source), (Asset.STATUS_READY, Asset.SOURCE_GENERATED_IMAGE))

        self.assertEqual((video.kind, video.mode, video.status), ("video", Take.MODE_I2V, Take.STATUS_DONE))
        self.assertGreater(video.created_at, picture.finished_at)
        row = ShotInput.objects.get(shot=video.shot)
        self.assertEqual((row.asset, row.slot, row.included), (frame, ShotInput.SLOT_FIRST_FRAME, True))
        self.assertEqual(video.request_body["frame_images"], [
            {"type": "image_url", "image_url": {"url": SITE + frame.url}, "frame_type": "first_frame"}])
        self.assertNotIn("input_references", video.request_body)
        self.assertEqual(self.submitted[0]["frame_images"], video.request_body["frame_images"])

        # Цена ролика с кадром посчитана до съёмки картинки и совпала с настоящей:
        # 91 кр с фото против 84 по одному тексту.
        self.assertRegex(out, r"i2v · исходная картинка\s+FLUX\.2 Klein\s+t2i\s+16:9\s+4\s+новый")
        self.assertRegex(out, r"i2v · Image → Video\s+Seedance 2\.0\s+i2v\s+5 с · 720p · 16:9\s+≈91\s+новый")
        self.assertEqual((picture.credits_charged, video.credits_charged), (4, 91))
        self.assertEqual(self.planned_total(out), 95)
        self.assertEqual(self.assert_money_rule(), 95)
        self.assertEqual([t.reason for t in self.ledger()], ["vstudio_image", "vstudio_video"])
        self.assertEqual([status for status, _cid in self.launches()], [202, 202])

        # В витрине — ролик, а не картинка; первый кадр виден вместе с запросом.
        item = ShowcaseItem.objects.get()
        self.assertEqual((item.take, item.category), (video, "i2v"))
        card = showcase.public_json(item)
        self.assertEqual((card["needs_photo"], card["start_frame_url"]), (True, frame.thumb_url))
        self.assertEqual(card["prompt"], scen.BY_KEY["i2v"].prompt)
        self.assertEqual(Project.objects.count(), 1)

    def test_picture_failure_stops_the_scenario_before_the_video(self):
        self.image_error = '{"error":{"message":"content policy"}}'
        out = self.run_command("--only", "i2v,car")
        picture = self.take_of("i2v", part=cmd.PART_IMAGE)
        self.assertEqual((picture.status, picture.charge_state), (Take.STATUS_FAILED, Take.CHARGE_RELEASED))
        self.assertFalse(Take.objects.filter(client_request_id=cmd.client_id("v1", "i2v")).exists())
        self.assertEqual([item.category for item in ShowcaseItem.objects.all()], ["car"])
        self.assertIn("i2v (кадр): не получилось", out)
        self.assertIn("Итог: снято — 1, не получилось — 1.", out)
        self.assertEqual(self.assert_money_rule(), 84)

        again = self.run_command("--only", "i2v", "--dry-run")
        self.assertIn("нельзя: исходная картинка в прошлый раз не получилась", again)
        self.assertIn("К запуску: видео — 0, картинок — 0.", again)

    def test_ready_picture_is_reused_and_priced_exactly(self):
        # Прошлый запуск оборвался между картинкой и роликом: картинка снята и оплачена,
        # ролика ещё нет.
        self.reject = "photo comes alive"   # ролик i2v
        self.run_command("--only", "i2v")
        picture = self.take_of("i2v", part=cmd.PART_IMAGE)
        Take.objects.filter(pk=self.take_of("i2v").pk).delete()
        self.reject = None

        plan = self.run_command("--only", "i2v", "--dry-run")
        self.assertRegex(plan, r"i2v · исходная картинка\s+FLUX\.2 Klein\s+t2i\s+16:9\s+4\s+уже снят")
        self.assertRegex(plan, r"i2v · Image → Video\s+Seedance 2\.0\s+i2v\s+5 с · 720p · 16:9\s+91\s+новый")
        self.assertIn("К запуску: видео — 1, картинок — 0. Всего 91 кр.", plan)

        out = self.run_command("--only", "i2v")
        self.assertIn("i2v (кадр): снят ранее — идёт первым кадром в ролик", out)
        self.assertEqual(len(self.pictures), 1)
        video = self.take_of("i2v")
        self.assertEqual((video.status, video.credits_charged), (Take.STATUS_DONE, 91))
        self.assertEqual(ShotInput.objects.get(shot=video.shot).asset, picture.result_asset)

    def test_picture_is_not_bought_when_the_video_cannot_start_from_it(self):
        # Без публичного адреса сайта провайдер не получит первый кадр: ролик
        # не запустится, значит и картинку под него снимать незачем.
        with override_settings(SITE_BASE_URL=""):
            out = self.run_command("--only", "ad,i2v")
        self.assertEqual(self.pictures, [])
        self.assertEqual([t.client_request_id for t in Take.objects.all()], [cmd.client_id("v1", "ad")])
        self.assertIn("К запуску: видео — 1, картинок — 0. Всего 84 кр.", out)
        self.assertRegex(out, r"i2v · исходная картинка\s+FLUX\.2 Klein .* не нужна: ролик снять нельзя")
        self.assertRegex(out, r"i2v · Image → Video .* нельзя: Студия временно недоступна\. Мы уже чиним\.")
        self.assertIn("i2v: пропущен — Студия временно недоступна. Мы уже чиним.", out)
        self.assertIn("Итог: снято — 1, не получилось — 0, пропущено — 1.", out)
        self.assertEqual(self.assert_money_rule(), 84)

    def test_second_copy_of_the_command_takes_the_first_ones_take(self):
        def other_copy(_question):
            # Пока эта копия ждёт подтверждения, вторая уже всё сняла.
            self.run_command("--only", "ad")
            return "y"

        with mock.patch("builtins.input", side_effect=other_copy):
            out = self.run_command("--only", "ad", yes=False)
        self.assertEqual([status for status, _cid in self.launches()], [202, 200])
        self.assertIn("ad: снят ранее; уже в витрине", out)
        self.assertIn("были сняты раньше — 1", out)
        self.assertEqual(Take.objects.count(), 1)
        self.assertEqual(ShowcaseItem.objects.count(), 1)
        self.assertEqual(Project.objects.count(), 1)
        self.assertEqual(len(self.submitted), 1)
        self.assertEqual(self.assert_money_rule(), 84)

    def test_publish_shows_the_work_unless_the_scenario_already_has_one(self):
        old = f.make_take(f.make_shot(self.staff), status="done", result_asset=f.make_asset(
            self.staff, kind="video", source=Asset.SOURCE_GENERATED_VIDEO))
        ShowcaseItem.objects.create(take=old, category="car", is_active=True)
        self.clip_task.reset_mock()

        out = self.run_command("--only", "ad,car", "--publish")
        ad = ShowcaseItem.objects.get(take=self.take_of("ad"))
        car = ShowcaseItem.objects.get(take=self.take_of("car"))
        self.assertTrue(ad.is_active)
        self.assertFalse(car.is_active)
        self.assertTrue(ShowcaseItem.objects.get(take=old).is_active)
        self.assertRegex(out, r"ad: готов, списано 84 кр; в витрине № \d+ \(показывается\)")
        self.assertIn("в сценарии уже есть включённая работа, новая оставлена скрытой", out)
        self.assertIn("В витрине: показываются — 1, скрыты — 1. Посмотреть и включить: "
                      "/admin-new/vstudio-showcase", out)

    def test_publish_ignores_a_work_of_the_scenario_moved_to_trends(self):
        # Работу «car» перенесли в «Тренды»: сценарий в карусели пуст, новую надо показать.
        old = f.make_take(f.make_shot(self.staff), status="done", result_asset=f.make_asset(
            self.staff, kind="video", source=Asset.SOURCE_GENERATED_VIDEO))
        trend = ShowcaseItem.objects.create(take=old, category="car", is_active=True,
                                            placement=ShowcaseItem.PLACEMENT_TRENDS, sort=7)
        self.clip_task.reset_mock()

        out = self.run_command("--only", "car", "--publish")
        car = ShowcaseItem.objects.get(take=self.take_of("car"))
        self.assertTrue(car.is_active)
        self.assertEqual(car.placement, ShowcaseItem.PLACEMENT_REEL)
        self.assertNotIn("новая оставлена скрытой", out)
        trend.refresh_from_db()
        self.assertEqual((trend.placement, trend.is_active, trend.category, trend.sort),
                         (ShowcaseItem.PLACEMENT_TRENDS, True, "car", 7))

    def test_publish_on_a_rerun_does_not_claim_hidden_rows_are_shown(self):
        first = self.run_command("--only", "ad,car")
        self.assertIn("В витрине: показываются — 0, скрыты — 2.", first)

        # Посмотрели скрытые работы и запустили то же с --publish: строки уже стоят,
        # команда их не включает — и не должна говорить, что они на сайте.
        again = self.run_command("--only", "ad,car", "--publish")
        self.assertEqual(list(ShowcaseItem.objects.values_list("is_active", flat=True)), [False, False])
        self.assertRegex(again, r"ad: снят ранее; уже в витрине, № \d+ \(скрыт\) — --publish уже "
                                r"стоящую строку не включает, включите в панели\n")
        self.assertIn("В витрине: показываются — 0, скрыты — 2.", again)
        self.assertNotIn("показываются на сайте", again)

    def test_summary_counts_rows_by_their_real_state(self):
        self.run_command("--only", "ad,car")
        # Владелец включил работу в панели: повторный запуск без --publish это видит.
        ShowcaseItem.objects.filter(category="ad").update(is_active=True)
        again = self.run_command("--only", "ad,car")
        self.assertRegex(again, r"ad: снят ранее; уже в витрине, № \d+ \(показывается\)\n")
        self.assertRegex(again, r"car: снят ранее; уже в витрине, № \d+ \(скрыт\)\n")
        self.assertIn("В витрине: показываются — 1, скрыты — 1.", again)
        self.assertNotIn("стоят в витрине скрытыми", again)

    def test_work_that_missed_the_showcase_is_not_reported_as_placed(self):
        with mock.patch.object(showcase, "add", side_effect=RuntimeError("витрина лежит")):
            out = self.run_command("--only", "ad")
        self.assertIn("ad: готов, списано 84 кр; в витрину НЕ поставлен (RuntimeError: витрина лежит)", out)
        self.assertIn("Итог: снято — 1, не получилось — 0, не встали в витрину — 1.", out)
        self.assertNotIn("В витрине:", out)
        self.assertNotIn("Посмотреть и включить", out)
        self.assertFalse(ShowcaseItem.objects.exists())
        self.assertEqual(self.assert_money_rule(), 84)

    def test_vertical_is_not_shot_on_a_model_without_vertical_video(self):
        # В студии осталась одна видеомодель, и она умеет только 16:9: горизонтальный
        # ролик под названием «Reels / TikTok» — кредиты впустую.
        GPTModels.objects.filter(category="video").exclude(openrouter_id=HAILUO).update(
            vstudio_enabled=False)
        out = self.run_command("--only", "anim,vertical")
        self.assertRegex(out, r"vertical · Reels / TikTok\s+—\s+—\s+—\s+—\s+нельзя: нет доступной "
                              r"модели \(открытые не умеют 9:16\)\n")
        self.assertIn("vertical: нет доступной модели (открытые не умеют 9:16). Пропущено: "
                      "«Seedance 2.0» — такой модели в студии нет.", out)
        self.assertNotIn("vertical: пропорции", out)
        self.assertIn("К запуску: видео — 1, картинок — 0.", out)
        self.assertIn("vertical: пропущен — нет доступной модели (открытые не умеют 9:16)", out)
        self.assertIn("Итог: снято — 1, не получилось — 0, пропущено — 1.", out)
        self.assertEqual(self.launches(), [(202, cmd.client_id("v1", "anim"))])
        self.assertEqual([t.client_request_id for t in Take.objects.all()], [cmd.client_id("v1", "anim")])
        self.assertEqual([item.category for item in ShowcaseItem.objects.all()], ["anim"])
        self.assertEqual(self.assert_money_rule(), self.take_of("anim").credits_charged)

    def test_vertical_goes_to_the_next_model_that_can_shoot_it(self):
        # Seedance 2.0 выключена; первая открытая в каталоге — Hailuo 2.3 (только 16:9),
        # следующая — Kling, она 9:16 умеет.
        GPTModels.objects.filter(openrouter_id=SEEDANCE).update(vstudio_enabled=False)
        out = self.run_command("--only", "vertical")
        take = self.take_of("vertical")
        self.assertEqual((take.model_ref, take.status), (KLING, Take.STATUS_DONE))
        self.assertEqual(take.effective["aspect_ratio"], "9:16")
        self.assertEqual(ShowcaseItem.objects.get().take, take)
        self.assertIn("vertical: Kling 3.0 Std — модель студии по умолчанию. Пропущено: "
                      "«Seedance 2.0» — такой модели в студии нет.", out)
        self.assertNotIn("vertical: пропорции", out)
        self.assertEqual(self.assert_money_rule(), take.credits_charged)

    def test_timeout_leaves_the_take_open_and_the_next_run_picks_it_up(self):
        self.worker_on = False
        out = self.run_command("--only", "ad", "--timeout", "60")
        take = self.take_of("ad")
        self.assertEqual((take.status, take.charge_state), (Take.STATUS_QUEUED, Take.CHARGE_RESERVED))
        self.assertIn(f"ad: не дождались за 60 с — дубль {take.uid} ещё снимается.", out)
        self.assertIn("не дождались — 1", out)
        self.assertIn("Доснять остальное: та же команда с той же меткой (--only ad).", out)
        self.assertFalse(ShowcaseItem.objects.exists())
        self.assertEqual(self.balance(), self.BALANCE)
        self.assertGreater(self.clock, 60)

        self.worker_on = True
        self.posts.clear()
        again = self.run_command("--only", "ad")
        self.assertEqual(self.posts, [])
        self.assertIn("уже снимается", again)
        self.assertIn(f"ad: уже снимается (дубль {take.uid}) — ждём", again)
        self.assertIn("ad: готов, списано 84 кр; в витрине №", again)
        self.assertEqual(Take.objects.count(), 1)
        self.assertEqual(ShowcaseItem.objects.get().take, take)
        self.assertEqual(self.assert_money_rule(), 84)

    def test_waits_for_a_free_slot_instead_of_hammering_the_api(self):
        # У аккаунта уже идут две чужие для команды съёмки — лимит открытых видео занят.
        busy = [f.make_take(f.make_shot(self.staff), status="running", credits=10) for _ in range(2)]
        self.worker_on = False
        out = self.run_command("--only", "ad", "--timeout", "30")
        self.assertEqual(self.launches(), [])
        self.assertFalse(Take.objects.exclude(pk__in=[t.pk for t in busy]).exists())
        self.assertIn("ad: не запущен — у аккаунта так и не освободилось место", out)
        self.assertIn("не запущено — 1", out)

    def test_price_change_after_the_plan_shoots_nothing_for_that_scenario(self):
        def reprice(_question):
            # Тариф подняли, пока план ждал подтверждения.
            GPTModels.objects.filter(openrouter_id=KLING).update(markup_coefficient=20)
            return "y"

        with mock.patch("builtins.input", side_effect=reprice):
            out = self.run_command("--only", "person,car", yes=False)
        self.assertFalse(Take.objects.filter(client_request_id=cmd.client_id("v1", "person")).exists())
        self.assertIn("person: не запущен — цена изменилась: в плане 50 кр, сейчас 100 кр.", out)
        self.assertEqual(self.take_of("car").status, Take.STATUS_DONE)
        self.assertEqual([status for status, _cid in self.launches()], [409, 202])
        self.assertIn("пропущено — 1", out)
        self.assertEqual(self.assert_money_rule(), 84)

    def test_gate_refusal_for_a_busy_account_is_retried_not_reported(self):
        busy = [f.make_take(f.make_shot(self.staff), status="running", credits=10) for _ in range(2)]
        self.worker_on = False
        # Своя проверка места обманута — отвечает сам гейт запуска.
        with mock.patch.object(cmd.Command, "_free_slot", return_value=True):
            out = self.run_command("--only", "ad", "--timeout", "12")
        statuses = [status for status, _cid in self.launches()]
        self.assertGreater(len(statuses), 1)
        self.assertEqual(set(statuses), {409})
        self.assertFalse(Take.objects.exclude(pk__in=[t.pk for t in busy]).exists())
        self.assertNotIn("запуск отклонён", out)
        self.assertIn("не запущено — 1", out)

    def test_request_limit_pauses_launches(self):
        with mock.patch.dict(SimpleRateThrottle.THROTTLE_RATES, {"vstudio_run": "1/min"}):
            out = self.run_command("--only", "ad,car", "--timeout", "30")
        self.assertEqual([status for status, _cid in self.launches()][:2], [202, 429])
        self.assertEqual(self.take_of("ad").status, Take.STATUS_DONE)
        self.assertEqual(Take.objects.count(), 1)
        self.assertIn("car: не запущен", out)
        self.assertIn("Итог: снято — 1, не получилось — 0, не запущено — 1.", out)
        self.assertEqual(self.assert_money_rule(), 84)

    def test_interrupt_leaves_takes_to_the_worker(self):
        self.worker_on = False
        real_sleep = self._sleep

        def interrupted(seconds):
            real_sleep(seconds)
            raise KeyboardInterrupt

        with mock.patch(f"{CMD}.time", SimpleNamespace(sleep=interrupted, monotonic=lambda: self.clock)):
            out = self.run_command("--only", "ad,car,film")
        self.assertIn("Остановлено. Запущенные дубли воркер доснимет", out)
        self.assertIn("не запущено — 1, не дождались — 2", out)
        self.assertEqual(Take.objects.filter(status__in=Take.OPEN).count(), 2)

        self.worker_on = True
        again = self.run_command("--only", "ad,car,film")
        self.assertIn("Итог: снято — 3, не получилось — 0.", again)
        self.assertEqual(Take.objects.count(), 3)
        self.assertEqual(ShowcaseItem.objects.count(), 3)
        self.assertEqual(self.assert_money_rule(), 84 * 3)

    def crashed(self, *args) -> tuple[str, str]:
        """Прогон, оборванный сбоем: (напечатанное до ошибки, текст ошибки команды)."""
        out = io.StringIO()
        with self.assertRaises(CommandError) as ctx:
            self.run_command(*args, out=out)
        return out.getvalue(), str(ctx.exception)

    def test_unexpected_error_while_waiting_still_ends_with_the_summary(self):
        self.worker_on = False
        with mock.patch.object(cmd.Command, "_check_waiting",
                               side_effect=OperationalError("server closed\nthe connection")):
            out, error = self.crashed("--only", "ad,car,film")
        self.assertIn("Сбой: OperationalError: server closed the connection. Новые запуски "
                      "остановлены; запущенные дубли воркер доснимет", out)
        self.assertIn("Итог: снято — 0, не получилось — 0, не запущено — 1, не дождались — 2. "
                      f"Списано за этот запуск: 0 кр. Баланс: {self.BALANCE} кр, в резерве 168.", out)
        self.assertIn("Доснять остальное: та же команда с той же меткой (--only film,ad,car).", out)
        self.assertIn("OperationalError: server closed the connection", error)
        self.assertEqual([status for status, _cid in self.launches()], [202, 202])
        self.assertEqual(Take.objects.filter(status__in=Take.OPEN).count(), 2)

        # Повторный запуск подхватывает начатое: ничего не снято и не оплачено дважды.
        self.worker_on = True
        again = self.run_command("--only", "ad,car,film")
        self.assertIn("Итог: снято — 3, не получилось — 0.", again)
        self.assertEqual(Take.objects.count(), 3)
        self.assertEqual(ShowcaseItem.objects.count(), 3)
        self.assertEqual(self.assert_money_rule(), 84 * 3)

    def test_unexpected_error_inside_a_launch_stops_new_launches(self):
        self.worker_on = False
        real_create, calls = views._create_take, []

        def flaky(**kw):
            calls.append(kw["cid"])
            if len(calls) == 2:
                # Не ответ студии, а сбой под вьюхой: по HTTP это был бы один 500.
                raise RuntimeError("cache is down")
            return real_create(**kw)

        with mock.patch.object(views, "_create_take", side_effect=flaky):
            out, error = self.crashed("--only", "ad,car,film")
        # Порядок запуска — порядок карусели: film, ad, car.
        self.assertEqual(calls, [cmd.client_id("v1", "film"), cmd.client_id("v1", "ad")])
        self.assertIn("Сбой: RuntimeError: cache is down.", out)
        self.assertIn("Итог: снято — 0, не получилось — 0, не запущено — 2, не дождались — 1.", out)
        self.assertIn("в резерве 84.", out)
        self.assertIn("Доснять остальное: та же команда с той же меткой (--only film,ad,car).", out)
        self.assertIn("RuntimeError: cache is down", error)
        # Упавший запуск откатился целиком: ни дубля, ни запроса, ни резерва.
        self.assertEqual([t.client_request_id for t in Take.objects.all()], [cmd.client_id("v1", "film")])
        self.assertEqual(Shot.objects.count(), 1)

        self.worker_on = True
        again = self.run_command("--only", "ad,car,film")
        self.assertIn("Итог: снято — 3, не получилось — 0.", again)
        self.assertEqual((Take.objects.count(), Shot.objects.count()), (3, 3))
        self.assertEqual(self.assert_money_rule(), 84 * 3)

    def test_summary_survives_a_database_that_stays_down(self):
        self.worker_on = False

        def database_dies():
            self.enterContext(mock.patch("vstudio.reserve.balance_snapshot",
                                         side_effect=OperationalError("connection already closed")))
            raise OperationalError("server closed the connection")

        with mock.patch.object(cmd.Command, "_check_waiting", side_effect=database_dies):
            out, error = self.crashed("--only", "ad")
        self.assertIn("Итог: снято — 0, не получилось — 0, не дождались — 1. Списано за этот "
                      "запуск: 0 кр. Баланс: не прочитан.", out)
        # Наружу идёт первая ошибка, а не та, что случилась при печати итога.
        self.assertIn("server closed the connection", error)
        self.assertNotIn("already closed", error)

    def test_refused_balance_stops_new_launches(self):
        def spend(_question):
            type(self.staff).objects.filter(pk=self.staff.pk).update(token_balance=10)
            return "y"

        with mock.patch("builtins.input", side_effect=spend):
            out = self.run_command("--only", "ad,car", yes=False)
        self.assertFalse(Take.objects.exists())
        self.assertEqual([status for status, _cid in self.launches()], [402])
        self.assertIn("ad: запуск отклонён (insufficient_balance)", out)
        self.assertIn("car: не запущен — новые запуски остановлены", out)
        self.assertIn("не запущено — 2", out)
        self.assertEqual(self.balance(), 10)
