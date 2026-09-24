"""REST API видеостудии /api/vstudio/ (спецификация §8).

Сеть не трогаем: каталог OpenRouter подменён спеками из caps_fixtures, цена
кредита и маржа зафиксированы, постановка задач записывается через
pipeline._enqueue и никуда не уходит.

Главное, что проверяем:
- формы ответов — ровно те, что ждёт фронт (lib/vstudio/types.ts);
- чужой uid неотличим от несуществующего (404 с кодом);
- цена quote = резерв запуска; расхождение — 409 price_changed, без записи;
- повтор client_request_id не создаёт второй дубль и не резервирует дважды;
- 402 — в форме чата (PaywallModal работает без правок);
- флаг VSTUDIO_MODE и форма любых отказов {error, error_code}.
"""
from contextlib import contextmanager
from datetime import timedelta
from datetime import timezone as dt_timezone
from unittest import mock

from django.core.cache import cache
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import transaction
from django.test import RequestFactory, TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient
from rest_framework.throttling import SimpleRateThrottle

from vstudio import notify, views
from vstudio import serializers as S
from vstudio.models import Asset, Project, Shot, ShotInput, Take
from vstudio.tests import factories as f
from vstudio.tests.caps_fixtures import SEEDANCE_20, VEO_FAST

API = "/api/vstudio/"
SITE = "https://esai.kg"
SEEDANCE = f.VIDEO_MODEL_REF
NANO = f.IMAGE_MODEL_REF
VEO = "google/veo-3.1-fast"

# Прайс «за секунду»: цена держится себестоимостью, фото добавляют к ней.
PRICED = dict(SEEDANCE_20, supported_resolutions=["480p", "720p", "1080p"], pricing_skus={
    "duration_seconds_480p": "0.05", "duration_seconds_720p": "0.10",
    "duration_seconds_1080p": "0.25", "reference_images": "0.04"})
SPECS = {SEEDANCE: PRICED, VEO: VEO_FAST}
VIDEO_PARAMS = {"duration": 5, "resolution": "720p", "aspect_ratio": "16:9"}


class ApiCase(TestCase):
    """Общая обвязка: режим on, подменённый каталог и цена, запись постановок задач."""

    mode = "on"

    def setUp(self):
        cache.clear()
        self.enqueued = []
        self.enterContext(mock.patch("vstudio.pipeline._enqueue", side_effect=self._record))
        self.enterContext(mock.patch("ai.handlers._openrouter_video_catalog",
                                     side_effect=lambda mid: dict(SPECS.get(mid) or {})))
        self.enterContext(mock.patch("ai.video_cost.cheapest_credit_usd", return_value=0.01))
        self.enterContext(mock.patch("ai.video_cost.min_margin", return_value=0.4))
        self.enterContext(override_settings(VSTUDIO_MODE=self.mode, SITE_BASE_URL=SITE,
                                            VSTUDIO_INLINE_REFS=False, VSTUDIO_MIN_PROVIDER_USD=0))
        self.user = f.make_user(balance=5000)
        self.video = f.make_gpt_model(SEEDANCE, name="Seedance 2.0", markup=5)
        self.image = f.make_gpt_model(NANO, name="Nano Banana", markup=6, category="image")
        self.api = self.client_for(self.user)

    def _record(self, name, take_id, countdown=None, **kwargs):
        self.enqueued.append((name, take_id))
        return True

    # --- помощники

    def client_for(self, user=None):
        client = APIClient()
        if user is not None:
            client.force_authenticate(user)
        return client

    def url(self, path: str) -> str:
        return API + path

    def body(self, *, kind="video", model=None, doc=None, text=None, inputs=(), params=None,
             project=None, **extra):
        rows = []
        positions = {}
        for item in inputs:
            if isinstance(item, Asset):
                item = {"asset": item}
            slot = item.get("slot", "reference")
            pos = positions.get(slot, 0)
            positions[slot] = pos + 1
            rows.append({"asset": item["asset"].uid if isinstance(item["asset"], Asset) else item["asset"],
                         "slot": slot, "position": item.get("position", pos),
                         "role": item.get("role", ""), "included": item.get("included", True)})
        out = {"project": project, "kind": kind, "model": model or (SEEDANCE if kind == "video" else NANO),
               "inputs": rows,
               "params": dict(VIDEO_PARAMS if kind == "video" else {}) if params is None else params}
        if text is not None:
            out["prompt_text"] = text
        else:
            out["prompt_doc"] = doc or f.prompt_doc("Девушка идёт по крыше")
        out.update(extra)
        return out

    def quote(self, body, client=None):
        return (client or self.api).post(self.url("quote/"), body, format="json")

    def launch(self, body, *, quoted=None, cid=None, client=None):
        client = client or self.api
        if quoted is None:
            q = self.quote(body, client)
            self.assertEqual(q.status_code, 200, q.content)
            quoted = q.json()["credits"]
        payload = dict(body, quoted_credits=quoted, client_request_id=cid or f"cid{timezone.now().timestamp()}")
        return client.post(self.url("shots/"), payload, format="json")

    def assert_error(self, res, status, code):
        self.assertEqual(res.status_code, status, res.content)
        data = res.json()
        self.assertEqual(data.get("error_code"), code, data)
        self.assertIsInstance(data.get("error"), str)
        self.assertTrue(data["error"])
        return data

    def other_user(self, **kw):
        return f.make_user(balance=kw.pop("balance", 1000), **kw)


# ---------------------------------------------------------------- флаг и форма ошибок

class ModeOffTests(ApiCase):
    mode = "off"

    def test_models_open_everything_else_disabled(self):
        res = self.api.get(self.url("models/"))
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json(), {"mode": "off", "available": False, "video": [], "image": []})
        self.assert_error(self.api.get(self.url("projects/")), 403, "vstudio_disabled")
        self.assert_error(self.quote(self.body()), 403, "vstudio_disabled")
        self.assert_error(self.api.post(self.url("shots/"), {}, format="json"), 403, "vstudio_disabled")


class ModeStaffTests(ApiCase):
    mode = "staff"

    def test_only_staff_can_use(self):
        self.assert_error(self.api.get(self.url("projects/")), 403, "vstudio_disabled")
        self.assert_error(self.quote(self.body()), 403, "vstudio_disabled")
        self.assert_error(self.quote(self.body(), self.client_for()), 403, "vstudio_disabled")
        models = self.api.get(self.url("models/")).json()
        self.assertEqual(models["mode"], "staff")
        self.assertFalse(models["available"])
        self.assertFalse(self.client_for().get(self.url("models/")).json()["available"])

        staff = f.make_user(balance=1000, is_staff=True)
        client = self.client_for(staff)
        self.assertEqual(client.get(self.url("projects/")).status_code, 200)
        self.assertEqual(self.quote(self.body(), client).status_code, 200)
        self.assertTrue(client.get(self.url("models/")).json()["available"])

    def test_admin_runtime_override_wins(self):
        with mock.patch("adminapi.runtime.get_runtime", return_value="on"):
            self.assertEqual(views.studio_mode(), "on")
            self.assertEqual(self.api.get(self.url("projects/")).status_code, 200)
        with mock.patch("adminapi.runtime.get_runtime", return_value="nonsense"):
            self.assertEqual(views.studio_mode(), "staff")


class ErrorShapeTests(ApiCase):
    def test_guest_gets_401_in_studio_shape(self):
        data = self.assert_error(self.client_for().get(self.url("projects/")), 401, "unauthorized")
        self.assertIn("detail", data)

    def test_method_not_allowed(self):
        self.assert_error(self.api.post(self.url("models/"), {}, format="json"), 405, "method_not_allowed")

    def test_throttled_in_studio_shape(self):
        with mock.patch.dict(SimpleRateThrottle.THROTTLE_RATES, {"vstudio_poll": "2/min"}):
            for _ in range(2):
                self.assertEqual(self.api.get(self.url("takes/")).status_code, 200)
            data = self.assert_error(self.api.get(self.url("takes/")), 429, "throttled")
        self.assertGreater(data["wait"], 0)

    def test_scope_per_method(self):
        view = views.ProjectDetailView()
        for method, scope in (("GET", "vstudio_read"), ("PATCH", "vstudio_write"),
                              ("DELETE", "vstudio_write")):
            view.request = RequestFactory().generic(method, "/")
            self.assertEqual(view.throttle_scope, scope)
        run = views.ShotsView()
        run.request = RequestFactory().post("/")
        self.assertEqual(run.throttle_scope, "vstudio_run")
        # quote/ — только свой scope: общий anon-лимит по IP съел бы пересчёт цены у гостей за NAT.
        self.assertEqual(views.QuoteView.throttle_classes, [views.ScopedRateThrottle])
        self.assertIn(views.AnonRateThrottle, views.ModelsView.throttle_classes)


# ---------------------------------------------------------------- модели

class ModelsTests(ApiCase):
    def test_lists_studio_models_with_caps_and_prices(self):
        f.make_gpt_model(VEO, name="Veo hidden", vstudio_enabled=False)
        f.make_gpt_model("openai/gpt-4o", name="Chat model", category="chat")
        res = self.api.get(self.url("models/"))
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(data["mode"], "on")
        self.assertTrue(data["available"])
        self.assertEqual([m["id"] for m in data["video"]], [SEEDANCE])
        self.assertEqual([m["id"] for m in data["image"]], [NANO])

        video = data["video"][0]
        self.assertEqual(set(video), {"id", "name", "badge", "locked", "eta_s", "price_from", "caps",
                                      "defaults", "price"})
        self.assertEqual(video["name"], "Seedance 2.0")
        self.assertFalse(video["locked"])
        self.assertEqual(video["caps"]["refs"], {"image": 9})
        self.assertEqual(video["caps"]["frames"], ["first_frame", "last_frame"])
        self.assertEqual(set(video["defaults"]), {"duration", "resolution", "aspect_ratio"})
        self.assertIn("720p", video["price"]["table"])
        self.assertGreater(video["price"]["table"]["720p"]["5"], 0)
        tables = [video["price"]["table"], *video["price"].get("by_aspect", {}).values()]
        self.assertEqual(video["price_from"], min(c for t in tables for row in t.values() for c in row.values()))
        self.assertIsInstance(video["eta_s"], int)

        image = data["image"][0]
        self.assertNotIn("price", image)
        self.assertEqual(image["per_image"], 6)
        self.assertEqual(image["price_from"], 6)
        self.assertEqual(image["defaults"], {"aspect_ratio": "auto"})
        self.assertEqual(image["caps"]["durations"], [])

    def test_locked_by_tier_and_cached_per_tier(self):
        guest = self.client_for().get(self.url("models/")).json()
        self.assertTrue(guest["available"])  # гость видит студию и цены
        self.assertTrue(guest["video"][0]["locked"])
        free = self.client_for(f.make_user(is_paid=False)).get(self.url("models/")).json()
        self.assertTrue(free["video"][0]["locked"])
        self.assertFalse(self.api.get(self.url("models/")).json()["video"][0]["locked"])

        # Кэш на тариф: правка модели не видна гостю до истечения кэша, а новый
        # тариф (ещё не в кэше) видит список уже без неё.
        type(self.video).objects.filter(pk=self.video.pk).update(vstudio_enabled=False)
        cache.delete(views.MODELS_CACHE_KEY.format(tier="paid"))
        self.assertEqual(len(self.client_for().get(self.url("models/")).json()["video"]), 1)
        self.assertEqual(self.api.get(self.url("models/")).json()["video"], [])

    def test_free_tier_model_unlocked_for_guest(self):
        type(self.image).objects.filter(pk=self.image.pk).update(free_tier=True)
        guest = self.client_for().get(self.url("models/")).json()
        self.assertFalse(guest["image"][0]["locked"])


# ---------------------------------------------------------------- цена

class QuoteTests(ApiCase):
    def test_guest_text_only_quote(self):
        res = self.quote(self.body(), self.client_for())
        self.assertEqual(res.status_code, 200, res.content)
        data = res.json()
        self.assertEqual(set(data), {"credits", "breakdown", "balance", "mode", "effective", "labels",
                                     "serialized_prompt", "errors", "warnings", "meter", "dropped", "eta_s"})
        self.assertIsNone(data["balance"])
        self.assertGreater(data["credits"], 0)
        self.assertEqual(data["mode"], "t2v")
        self.assertEqual(data["errors"], [])
        self.assertEqual(sum(line["credits"] for line in data["breakdown"]), data["credits"])
        self.assertEqual(data["effective"]["duration"], 5)
        self.assertEqual(data["meter"]["level"], "ok")
        self.assertIsInstance(data["eta_s"], int)

    def test_guest_cannot_quote_with_materials(self):
        asset = f.make_asset(self.user)
        self.assert_error(self.quote(self.body(inputs=[asset]), self.client_for()), 401, "unauthorized")

    def test_refs_labels_balance_and_breakdown(self):
        asset = f.make_asset(self.user)
        doc = f.prompt_doc(asset, " идёт по крыше")
        data = self.quote(self.body(doc=doc, inputs=[{"asset": asset, "role": "героиня"}])).json()
        self.assertEqual(data["errors"], [])
        self.assertEqual(data["mode"], "r2v")
        self.assertEqual(data["labels"], {asset.uid: "Image 1"})
        self.assertIn("[Image 1] is героиня.", data["serialized_prompt"])
        keys = [line["key"] for line in data["breakdown"]]
        self.assertEqual(keys, ["price.video", "price.refs"])
        self.assertEqual(data["breakdown"][1]["params"], {"n": 1})
        balance = data["balance"]
        self.assertEqual(balance["balance"], 5000)
        self.assertEqual(balance["reserved"], 0)
        self.assertEqual(balance["available"], 5000)
        self.assertEqual(balance["after"], 5000 - data["credits"])

    def test_prompt_text_tags_become_refs(self):
        a, b = f.make_asset(self.user), f.make_asset(self.user)
        data = self.quote(self.body(text="@Image 1 и [Image 2] танцуют, @Image 7 смотрит",
                                    inputs=[a, b])).json()
        self.assertEqual(data["errors"], [])
        self.assertEqual(data["labels"], {a.uid: "Image 1", b.uid: "Image 2"})
        self.assertIn("[Image 1] и [Image 2] танцуют", data["serialized_prompt"])
        self.assertIn("tag_unknown", [w["code"] for w in data["warnings"]])

    def test_compiler_errors_come_inside_200(self):
        data = self.quote(self.body(params={"duration": 99, "resolution": "720p"})).json()
        self.assertIn("invalid_param", [e["code"] for e in data["errors"]])
        self.assertIsNone(data["credits"])  # цена «за другой ролик» хуже, чем никакой

    def test_unknown_model_is_unavailable(self):
        data = self.quote(self.body(model="nobody/none")).json()
        self.assertEqual([e["code"] for e in data["errors"]], ["model_unavailable"])
        self.assertIsNone(data["credits"])
        self.assertEqual(set(data["meter"]), {"chars", "words", "soft_words", "hard_chars", "level"})

    def test_foreign_asset_is_not_found(self):
        foreign = f.make_asset(self.other_user())
        data = self.quote(self.body(inputs=[foreign])).json()
        self.assertEqual([e["code"] for e in data["errors"]], ["asset_not_found"])
        self.assertEqual(data["errors"][0]["params"]["asset"], foreign.uid)
        self.assertEqual(data["errors"][0]["fix"], {"action": "exclude_inputs", "assets": [foreign.uid]})
        # Упомянутое в тексте чужое фото — одна ошибка mention_not_attached, без дубля.
        data = self.quote(self.body(doc=f.prompt_doc(foreign, " идёт"), inputs=[foreign])).json()
        self.assertEqual([e["code"] for e in data["errors"]], ["mention_not_attached"])
        # Выключенное чужое фото просто не учитывается.
        data = self.quote(self.body(inputs=[{"asset": foreign, "included": False}])).json()
        self.assertEqual(data["errors"], [])

    def test_quote_for_retry_allows_deleted_asset(self):
        asset = f.make_asset(self.user)
        run = self.launch(self.body(doc=f.prompt_doc(asset, " идёт"), inputs=[asset])).json()
        Asset.objects.filter(pk=asset.pk).update(deleted_at=timezone.now())
        fresh = self.quote(self.body(doc=f.prompt_doc(asset, " идёт"), inputs=[asset])).json()
        self.assertEqual([e["code"] for e in fresh["errors"]], ["asset_not_found"])
        retry = self.quote({"shot": run["shot"]["uid"]}).json()
        self.assertEqual(retry["errors"], [])
        self.assertEqual(retry["credits"], run["take"]["credits"]["reserved"])

    def test_quote_for_foreign_or_guest_shot(self):
        shot = f.make_shot(self.other_user())
        self.assert_error(self.quote({"shot": shot.uid}), 404, "shot_not_found")
        self.assert_error(self.quote({"shot": "nope"}), 404, "shot_not_found")
        self.assert_error(self.quote({"shot": shot.uid}, self.client_for()), 401, "unauthorized")

    def test_bad_bodies(self):
        self.assert_error(self.quote({"model": SEEDANCE, "prompt_text": "x"}), 400, "bad_request")
        both = self.body(text="x")
        both["prompt_doc"] = f.prompt_doc("x")
        self.assert_error(self.quote(both), 400, "bad_request")
        self.assert_error(self.quote(self.body(inputs=[{"asset": "not-a-uid"}])), 400, "bad_request")
        self.assert_error(self.quote(self.body(params={"seed": {"x": 1}})), 400, "bad_request")

    def test_oversized_prompt_text_is_reported_not_cut(self):
        data = self.quote(self.body(text="а" * 20_001)).json()
        self.assertEqual([e["code"] for e in data["errors"]], ["prompt_doc_invalid"])
        self.assertIsNone(data["credits"])
        self.assertEqual(data["meter"]["chars"], 20_001)  # счётчик видит весь текст

    def test_invalid_doc_is_reported_inside(self):
        data = self.quote(self.body(doc={"v": 2, "blocks": []})).json()
        self.assertEqual([e["code"] for e in data["errors"]], ["prompt_doc_invalid"])
        self.assertIsNone(data["credits"])


# ---------------------------------------------------------------- запуск

class RunTests(ApiCase):
    def test_run_video_reserves_quoted_price_and_enqueues_after_commit(self):
        asset = f.make_asset(self.user)
        body = self.body(doc=f.prompt_doc(asset, " идёт по крыше"), inputs=[{"asset": asset, "role": "героиня"}])
        credits = self.quote(body).json()["credits"]
        with self.captureOnCommitCallbacks(execute=True) as callbacks:
            res = self.launch(body, quoted=credits, cid="c" * 32)
        self.assertEqual(res.status_code, 202, res.content)
        self.assertEqual(len(callbacks), 1)
        data = res.json()
        self.assertEqual(set(data), {"project", "shot", "take", "asset", "balance"})

        take = Take.objects.get()
        self.assertEqual(self.enqueued, [("submit_take", take.pk)])
        self.assertEqual(take.status, Take.STATUS_QUEUED)
        self.assertEqual(take.charge_state, Take.CHARGE_RESERVED)
        self.assertEqual(take.credits_reserved, credits)
        self.assertEqual(take.credits_quoted, credits)
        self.assertEqual(take.client_request_id, "c" * 32)
        self.assertEqual(take.mode, Take.MODE_R2V)
        refs = take.request_body["input_references"]
        self.assertEqual(refs[0]["image_url"]["url"], SITE + default_storage.url(asset.file))
        self.assertNotIn("frame_images", take.request_body)

        self.assertEqual(data["project"]["title"], "@Image 1 идёт по крыше")
        self.assertEqual(data["project"]["open_takes"], 1)
        self.assertEqual(set(data["project"]), {"uid", "title", "kind", "settings", "is_archived",
                                                "last_activity_at", "thumb_url", "open_takes"})
        self.assertEqual(data["project"]["settings"]["model"], SEEDANCE)
        shot = data["shot"]
        self.assertEqual(shot["model"], {"id": SEEDANCE, "name": "Seedance 2.0"})
        self.assertEqual(shot["prompt_text"], "@Image 1 идёт по крыше")
        self.assertEqual(shot["inputs"][0]["label"], "Image 1")
        self.assertEqual(shot["inputs"][0]["role"], "героиня")
        self.assertEqual(shot["inputs"][0]["asset"]["uid"], asset.uid)
        self.assertEqual([t["uid"] for t in shot["takes"]], [take.uid])
        lite = data["take"]
        self.assertEqual(lite["uid"], take.uid)
        self.assertEqual(lite["shot"], shot["uid"])
        self.assertEqual(lite["credits"], {"quoted": credits, "reserved": credits, "charged": 0})
        self.assertEqual(lite["queue_position"], 0)
        self.assertIsNone(lite["error"])
        self.assertIsNone(data["asset"])
        self.assertEqual(data["balance"]["reserved"], credits)
        self.assertEqual(data["balance"]["available"], 5000 - credits)
        self.assertEqual(ShotInput.objects.get().role, "героиня")

    def test_same_click_twice_creates_one_take(self):
        body = self.body()
        first = self.launch(body, cid="d" * 32)
        self.assertEqual(first.status_code, 202)
        again = self.launch(body, cid="d" * 32)
        self.assertEqual(again.status_code, 200, again.content)
        self.assertEqual(again.json()["take"]["uid"], first.json()["take"]["uid"])
        self.assertEqual(again.json()["project"]["uid"], first.json()["project"]["uid"])
        self.assertEqual(Take.objects.count(), 1)
        self.assertEqual(Shot.objects.count(), 1)

    def test_click_seen_only_under_the_lock_returns_that_take(self):
        first = self.launch(self.body(), cid="e" * 32).json()
        with mock.patch("vstudio.views._existing_take", return_value=None):
            again = self.launch(self.body(), cid="e" * 32)
        self.assertEqual(again.status_code, 200, again.content)
        self.assertEqual(again.json()["take"]["uid"], first["take"]["uid"])
        self.assertEqual(Take.objects.count(), 1)

    def test_unique_index_race_returns_existing_take(self):
        first = self.launch(self.body(), cid="f" * 32).json()
        existing = Take.objects.get()

        @contextmanager
        def open_gate(user, need, *, kind, client_request_id=""):
            with transaction.atomic():
                yield user

        with mock.patch("vstudio.views.reserve.spend_gate", open_gate), \
                mock.patch("vstudio.views._existing_take", side_effect=[None, existing]):
            again = self.launch(self.body(), cid="f" * 32)
        self.assertEqual(again.status_code, 200, again.content)
        self.assertEqual(again.json()["take"]["uid"], first["take"]["uid"])
        self.assertEqual(Take.objects.count(), 1)
        self.assertEqual(Shot.objects.count(), 1)

    def test_price_changed_writes_nothing(self):
        credits = self.quote(self.body()).json()["credits"]
        data = self.assert_error(self.launch(self.body(), quoted=credits + 1), 409, "price_changed")
        self.assertEqual(data["credits"], credits)
        self.assertEqual(sum(line["credits"] for line in data["breakdown"]), credits)
        self.assertFalse(Take.objects.exists())
        self.assertFalse(Project.objects.exists())

    def test_insufficient_balance_in_chat_shape(self):
        User = type(self.user)
        User.objects.filter(pk=self.user.pk).update(token_balance=3)
        credits = self.quote(self.body()).json()["credits"]
        data = self.assert_error(self.launch(self.body(), quoted=credits), 402, "insufficient_balance")
        self.assertEqual(data["balance_tokens"], 3)
        self.assertEqual(data["required_estimate"], credits)
        self.assertNotIn("reserved_credits", data)
        self.assertFalse(Take.objects.exists())
        self.assertFalse(Shot.objects.exists())

    def test_insufficient_balance_counts_open_reserve(self):
        credits = self.quote(self.body()).json()["credits"]
        f.make_take(f.make_shot(self.user, model=self.video), status="running", credits=100)
        type(self.user).objects.filter(pk=self.user.pk).update(token_balance=credits + 50)
        data = self.assert_error(self.launch(self.body(), quoted=credits), 402, "insufficient_balance")
        self.assertEqual(data["reserved_credits"], 100)
        self.assertEqual(data["balance_tokens"], credits - 50)
        self.assertEqual(Take.objects.count(), 1)

    def test_too_many_open(self):
        for _ in range(2):
            f.make_take(f.make_shot(self.user, model=self.video), status="queued", credits=10)
        data = self.assert_error(self.launch(self.body()), 409, "too_many_open")
        self.assertEqual((data["limit"], data["kind"]), (2, "video"))

    def test_premium_locked_for_free_user(self):
        free = f.make_user(balance=5000, is_paid=False)
        data = self.assert_error(self.launch(self.body(), client=self.client_for(free)), 403, "premium_locked")
        self.assertIn("min_package_kgs", data)
        self.assertFalse(Take.objects.exists())

    def test_blocked_by_compiler(self):
        foreign = f.make_asset(self.other_user())
        body = self.body(doc=f.prompt_doc(foreign, " идёт"), inputs=[foreign])
        credits = self.quote(body).json()["credits"] or 1
        data = self.assert_error(self.launch(body, quoted=credits), 422, "blocked")
        self.assertEqual([e["code"] for e in data["errors"]], ["mention_not_attached"])
        self.assertIn("warnings", data)
        self.assertFalse(Take.objects.exists())

    def test_invalid_doc_is_422(self):
        body = self.body(doc={"v": 1, "blocks": [[{"t": "script", "v": "x"}]]})
        self.assert_error(self.launch(body, quoted=10), 422, "prompt_doc_invalid")

    def test_refs_without_public_site_is_503(self):
        asset = f.make_asset(self.user)
        with override_settings(SITE_BASE_URL=""):
            data = self.assert_error(self.launch(self.body(inputs=[asset]), quoted=10), 503,
                                     "service_misconfigured")
        self.assertIn("service_misconfigured", [e["code"] for e in data["errors"]])
        self.assertFalse(Take.objects.exists())

    def test_image_run_creates_pending_asset(self):
        body = self.body(kind="image", doc=f.prompt_doc("Рыжий кот"), params={"aspect_ratio": "1:1"},
                         origin="tray")
        with self.captureOnCommitCallbacks(execute=True):
            res = self.launch(body)
        self.assertEqual(res.status_code, 202, res.content)
        data = res.json()
        take = Take.objects.get()
        asset = Asset.objects.get()
        self.assertEqual(self.enqueued, [("run_image_take", take.pk)])
        self.assertEqual(take.result_asset_id, asset.pk)
        self.assertEqual(asset.origin_take_id, take.pk)
        self.assertEqual((asset.status, asset.source), (Asset.STATUS_PENDING, Asset.SOURCE_GENERATED_IMAGE))
        self.assertEqual(asset.meta["take"], take.uid)
        self.assertEqual(take.credits_reserved, 6)
        self.assertEqual(data["asset"]["uid"], asset.uid)
        self.assertEqual(data["asset"]["status"], "pending")
        self.assertIsNone(data["asset"]["url"])
        self.assertEqual(data["take"]["result"]["uid"], asset.uid)
        self.assertEqual(data["shot"]["origin"], "tray")

    def test_tray_origin_only_for_images(self):
        self.assert_error(self.launch(self.body(origin="tray"), quoted=10), 400, "bad_request")

    def test_existing_project_and_ownership(self):
        project = f.make_project(self.user)
        res = self.launch(self.body(project=project.uid))
        self.assertEqual(res.status_code, 202, res.content)
        self.assertEqual(res.json()["project"]["uid"], project.uid)
        project.refresh_from_db()
        self.assertEqual(project.title, "Девушка идёт по крыше")  # пустое название — из промпта
        foreign = f.make_project(self.other_user())
        self.assert_error(self.launch(self.body(project=foreign.uid), quoted=10), 404, "project_not_found")

    def test_prompt_text_run_stores_doc(self):
        asset = f.make_asset(self.user)
        res = self.launch(self.body(text="@фото1 идёт по крыше", inputs=[asset]))
        self.assertEqual(res.status_code, 202, res.content)
        shot = Shot.objects.get()
        self.assertEqual(shot.prompt_doc["blocks"][0][0], {"t": "ref", "asset": asset.uid})
        self.assertEqual(shot.prompt_text, "@Image 1 идёт по крыше")

    def test_forked_from_links_own_shot_only(self):
        first = self.launch(self.body(), cid="g" * 32).json()
        res = self.launch(self.body(forked_from=first["shot"]["uid"]), cid="h" * 32)
        self.assertEqual(res.status_code, 202, res.content)
        self.assertEqual(res.json()["shot"]["forked_from"], first["shot"]["uid"])
        # Лимит открытых видео — 2: закрываем прошлые, чтобы проверить только связь.
        Take.objects.update(status=Take.STATUS_FAILED, charge_state=Take.CHARGE_RELEASED)
        foreign = f.make_shot(self.other_user())
        res = self.launch(self.body(forked_from=foreign.uid), cid="i" * 32)
        self.assertEqual(res.status_code, 202, res.content)
        self.assertIsNone(res.json()["shot"]["forked_from"])
        self.assert_error(self.launch(self.body(forked_from="../x"), quoted=10, cid="j" * 32), 400, "bad_request")

    def test_guest_and_bad_ids(self):
        self.assert_error(self.launch(self.body(), quoted=10, client=self.client_for()), 401, "unauthorized")
        payload = dict(self.body(), quoted_credits=10, client_request_id="has space")
        self.assert_error(self.api.post(self.url("shots/"), payload, format="json"), 400, "bad_request")
        payload = dict(self.body(), quoted_credits="10", client_request_id="x1")
        self.assert_error(self.api.post(self.url("shots/"), payload, format="json"), 400, "bad_request")


class RetryTests(ApiCase):
    def setUp(self):
        super().setUp()
        self.asset = f.make_asset(self.user)
        first = self.launch(self.body(doc=f.prompt_doc(self.asset, " идёт"), inputs=[self.asset])).json()
        self.shot_uid = first["shot"]["uid"]
        self.first_take = Take.objects.get()
        Take.objects.filter(pk=self.first_take.pk).update(status=Take.STATUS_FAILED,
                                                          charge_state=Take.CHARGE_RELEASED)
        self.enqueued.clear()

    def retry(self, *, quoted=None, cid="r" * 32, uid=None):
        uid = uid or self.shot_uid
        if quoted is None:
            quoted = self.quote({"shot": uid}).json()["credits"]
        return self.api.post(self.url(f"shots/{uid}/retry/"),
                             {"quoted_credits": quoted, "client_request_id": cid}, format="json")

    def test_retry_new_take_same_shot_even_with_deleted_photo(self):
        Asset.objects.filter(pk=self.asset.pk).update(deleted_at=timezone.now())
        with self.captureOnCommitCallbacks(execute=True):
            res = self.retry()
        self.assertEqual(res.status_code, 202, res.content)
        data = res.json()
        self.assertEqual(set(data), {"take", "balance"})
        new = Take.objects.exclude(pk=self.first_take.pk).get()
        self.assertEqual(new.shot_id, self.first_take.shot_id)
        self.assertEqual(new.charge_state, Take.CHARGE_RESERVED)
        self.assertEqual(data["take"]["uid"], new.uid)
        self.assertEqual(data["take"]["shot"], self.shot_uid)
        self.assertEqual(self.enqueued, [("submit_take", new.pk)])
        self.assertEqual(data["balance"]["reserved"], new.credits_reserved)

    def test_retry_is_idempotent_and_checks_price(self):
        first = self.retry(cid="s" * 32)
        again = self.retry(cid="s" * 32)
        self.assertEqual(again.status_code, 200)
        self.assertEqual(again.json()["take"]["uid"], first.json()["take"]["uid"])
        self.assertEqual(Take.objects.count(), 2)
        data = self.assert_error(self.retry(quoted=1, cid="t" * 32), 409, "price_changed")
        self.assertEqual(data["credits"], first.json()["take"]["credits"]["reserved"])

    def test_image_retry_gets_new_pending_asset(self):
        run = self.launch(self.body(kind="image", doc=f.prompt_doc("Кот"), params={})).json()
        Take.objects.filter(uid=run["take"]["uid"]).update(status=Take.STATUS_FAILED,
                                                          charge_state=Take.CHARGE_RELEASED)
        res = self.retry(uid=run["shot"]["uid"], cid="u" * 32)
        self.assertEqual(res.status_code, 202, res.content)
        result = res.json()["take"]["result"]
        self.assertEqual(result["status"], "pending")
        self.assertNotEqual(result["uid"], run["asset"]["uid"])
        self.assertEqual(Asset.objects.get(uid=result["uid"]).origin_take.uid, res.json()["take"]["uid"])

    def test_foreign_shot(self):
        other = f.make_shot(self.other_user())
        self.assert_error(self.retry(uid=other.uid, quoted=10), 404, "shot_not_found")


# ---------------------------------------------------------------- дубли

class TakesTests(ApiCase):
    def test_poll_returns_only_own_and_marks_seen(self):
        mine = f.make_take(f.make_shot(self.user, model=self.video), status="running", genlog=False)
        other = f.make_take(f.make_shot(self.other_user(), model=self.video), status="running")
        ids = ",".join([other.uid, mine.uid, "garbage", mine.uid])
        res = self.api.get(self.url(f"takes/?ids={ids}"))
        self.assertEqual(res.status_code, 200)
        items = res.json()["items"]
        self.assertEqual([t["uid"] for t in items], [mine.uid])
        self.assertTrue(notify.is_seen(self.user.pk))
        self.assertEqual(set(items[0]), {
            "uid", "shot", "kind", "status", "stage", "mode", "charge_state", "credits", "effective",
            "warnings", "dropped", "result", "error", "eta_s", "elapsed_s", "queue_position",
            "created_at", "submitted_at", "finished_at"})
        self.assertIsNone(items[0]["queue_position"])
        self.assertIsInstance(items[0]["eta_s"], int)

    def test_poll_limit(self):
        ids = ",".join(f"{n:032x}" for n in range(31))
        self.assert_error(self.api.get(self.url(f"takes/?ids={ids}")), 400, "bad_request")

    def test_queue_position_and_elapsed(self):
        other = f.make_take(f.make_shot(self.other_user(), model=self.video), status="queued")
        mine = f.make_take(f.make_shot(self.user, model=self.video), status="queued")
        Take.objects.filter(pk=other.pk).update(created_at=timezone.now() - timedelta(seconds=30))
        Take.objects.filter(pk=mine.pk).update(created_at=timezone.now() - timedelta(seconds=10))
        item = self.api.get(self.url(f"takes/?ids={mine.uid}")).json()["items"][0]
        self.assertEqual(item["queue_position"], 1)
        self.assertGreaterEqual(item["elapsed_s"], 9)

        running = f.make_take(f.make_shot(self.user, model=self.video), status="running",
                              submitted_at=timezone.now() - timedelta(seconds=40))
        Take.objects.filter(pk=running.pk).update(created_at=timezone.now() - timedelta(minutes=5))
        item = self.api.get(self.url(f"takes/?ids={running.uid}")).json()["items"][0]
        self.assertLess(item["elapsed_s"], 100)  # от отправки, а не от создания

    def test_failed_and_done_shapes(self):
        shot = f.make_shot(self.user, model=self.video)
        failed = f.make_take(shot, status="failed", error="Модель не принимает фото реальных людей.",
                             error_code="image_real_person", error_input="a" * 32)
        video = f.make_asset(self.user, kind="video", source=Asset.SOURCE_GENERATED_VIDEO)
        done = f.make_take(shot, status="done", result_asset=video)
        items = {t["uid"]: t for t in self.api.get(self.url(f"takes/?ids={failed.uid},{done.uid}")).json()["items"]}
        self.assertEqual(items[failed.uid]["error"], {"code": "image_real_person",
                                                      "message": "Модель не принимает фото реальных людей.",
                                                      "input": "a" * 32})
        self.assertIsNone(items[done.uid]["error"])
        self.assertEqual(items[done.uid]["result"]["uid"], video.uid)
        self.assertEqual(items[done.uid]["result"]["url"], default_storage.url(video.file))
        self.assertEqual(items[done.uid]["credits"]["charged"], 150)

    def test_active_detail_and_ownership(self):
        shot = f.make_shot(self.user, model=self.video)
        running = f.make_take(shot, status="running")
        f.make_take(shot, status="done")
        f.make_take(f.make_shot(self.other_user(), model=self.video), status="running")
        items = self.api.get(self.url("takes/active/")).json()["items"]
        self.assertEqual([t["uid"] for t in items], [running.uid])
        self.assertEqual(items[0]["project_uid"], shot.project.uid)

        detail = self.api.get(self.url(f"takes/{running.uid}/")).json()
        self.assertEqual(detail["serialized_prompt"], running.serialized_prompt)
        self.assertEqual(detail["request_body"], running.request_body)
        foreign = Take.objects.exclude(user=self.user).get()
        self.assert_error(self.api.get(self.url(f"takes/{foreign.uid}/")), 404, "take_not_found")
        self.assert_error(self.api.get(self.url("takes/xyz/")), 404, "take_not_found")

    def test_cancel_only_from_queue(self):
        with self.captureOnCommitCallbacks(execute=True):
            run = self.launch(self.body(kind="image", doc=f.prompt_doc("Кот"), params={})).json()
        uid = run["take"]["uid"]
        res = self.api.post(self.url(f"takes/{uid}/cancel/"), {}, format="json")
        self.assertEqual(res.status_code, 200, res.content)
        self.assertEqual((res.json()["status"], res.json()["charge_state"]), ("canceled", "released"))
        self.assertEqual(res.json()["result"]["status"], "failed")
        self.assertEqual(Asset.objects.get().error_code, "canceled")
        self.assertEqual(self.api.post(self.url("quote/"), self.body(), format="json").json()["balance"]["reserved"], 0)

        running = f.make_take(f.make_shot(self.user, model=self.video), status="running")
        self.assert_error(self.api.post(self.url(f"takes/{running.uid}/cancel/"), {}, format="json"),
                          409, "already_submitted")
        running.refresh_from_db()
        self.assertEqual(running.status, Take.STATUS_RUNNING)
        foreign = f.make_take(f.make_shot(self.other_user(), model=self.video), status="queued")
        self.assert_error(self.api.post(self.url(f"takes/{foreign.uid}/cancel/"), {}, format="json"),
                          404, "take_not_found")
        foreign.refresh_from_db()
        self.assertEqual(foreign.status, Take.STATUS_QUEUED)


# ---------------------------------------------------------------- проекты и лента

class ProjectsTests(ApiCase):
    def make(self, title, minutes_ago, user=None, **kw):
        p = f.make_project(user or self.user, title=title, **kw)
        Project.objects.filter(pk=p.pk).update(last_activity_at=timezone.now() - timedelta(minutes=minutes_ago))
        return p

    def test_list_pages_by_activity(self):
        c, b, a = self.make("C", 30), self.make("B", 20), self.make("A", 10)
        self.make("Чужой", 1, user=self.other_user())
        first = self.api.get(self.url("projects/?limit=2")).json()
        self.assertEqual([p["uid"] for p in first["items"]], [a.uid, b.uid])
        self.assertEqual(first["next"], first["items"][-1]["last_activity_at"])
        second = self.api.get(self.url("projects/"), {"limit": 2, "before": first["next"]}).json()
        self.assertEqual([p["uid"] for p in second["items"]], [c.uid])
        self.assertIsNone(second["next"])

    def test_search_archive_and_counters(self):
        roof = self.make("Крыша", 5)
        cat = self.make("Без названия", 6)
        f.make_shot(self.user, project=cat, prompt="Рыжий кот на подоконнике")
        self.make("Старое", 7, is_archived=True)
        found = self.api.get(self.url("projects/"), {"q": "кот"}).json()["items"]
        self.assertEqual([p["uid"] for p in found], [cat.uid])
        # (SQLite сравнивает без учёта регистра только латиницу — на Postgres «КРЫШ» тоже найдётся.)
        found = self.api.get(self.url("projects/"), {"q": "Крыш"}).json()["items"]
        self.assertEqual([p["uid"] for p in found], [roof.uid])
        archived = self.api.get(self.url("projects/"), {"archived": "1"}).json()["items"]
        self.assertEqual([p["title"] for p in archived], ["Старое"])

        shot = f.make_shot(self.user, project=roof)
        f.make_take(shot, status="running")
        thumb = f.make_asset(self.user, project=roof, kind="video", source=Asset.SOURCE_GENERATED_VIDEO)
        item = next(p for p in self.api.get(self.url("projects/")).json()["items"] if p["uid"] == roof.uid)
        self.assertEqual(item["open_takes"], 1)
        self.assertEqual(item["thumb_url"], default_storage.url(thumb.thumb))

    def test_create_get_patch_delete(self):
        res = self.api.post(self.url("projects/"), {"title": "  Реклама  "}, format="json")
        self.assertEqual(res.status_code, 201, res.content)
        uid = res.json()["uid"]
        self.assertEqual(res.json()["title"], "Реклама")
        self.assertEqual(self.api.get(self.url(f"projects/{uid}/")).json()["uid"], uid)

        settings_ = {"kind": "video", "model": SEEDANCE, "params": {"duration": 5},
                     "by_kind": {"video": {"model": SEEDANCE, "params": {}}}}
        res = self.api.patch(self.url(f"projects/{uid}/"), {"title": "Новое", "settings": settings_},
                             format="json")
        self.assertEqual(res.status_code, 200, res.content)
        self.assertEqual((res.json()["title"], res.json()["settings"]), ("Новое", settings_))
        self.assert_error(self.api.patch(self.url(f"projects/{uid}/"), {"is_archived": "yes"}, format="json"),
                          400, "bad_request")
        self.assert_error(self.api.patch(self.url(f"projects/{uid}/"), {"title": "x" * 141}, format="json"),
                          400, "bad_request")

        res = self.api.delete(self.url(f"projects/{uid}/"))
        self.assertEqual(res.status_code, 204)
        self.assertEqual(res.content, b"")
        self.assertTrue(Project.objects.get(uid=uid).is_archived)

    def test_foreign_project_is_404(self):
        foreign = f.make_project(self.other_user())
        for method in ("get", "patch", "delete"):
            res = getattr(self.api, method)(self.url(f"projects/{foreign.uid}/"), {}, format="json")
            self.assert_error(res, 404, "project_not_found")
        self.assert_error(self.api.get(self.url(f"projects/{foreign.uid}/shots/")), 404, "project_not_found")
        self.assert_error(self.api.get(self.url("projects/not-a-uid/")), 404, "project_not_found")
        foreign.refresh_from_db()
        self.assertFalse(foreign.is_archived)

    def test_bad_cursor(self):
        self.assert_error(self.api.get(self.url("projects/"), {"before": "вчера"}), 400, "bad_request")


class FeedTests(ApiCase):
    def test_shots_pages_newest_first_ascending_inside(self):
        project = f.make_project(self.user)
        asset = f.make_asset(self.user)
        shots = []
        for n in range(5):
            s = f.make_shot(self.user, project=project, model=self.video, prompt=f"Кадр {n}",
                            inputs=[asset, {"asset": f.make_asset(self.user), "included": False}])
            Shot.objects.filter(pk=s.pk).update(created_at=timezone.now() - timedelta(minutes=10 - n))
            f.make_take(s, status="done")
            shots.append(s)
        page1 = self.api.get(self.url(f"projects/{project.uid}/shots/"), {"limit": 2}).json()
        self.assertEqual([s["uid"] for s in page1["items"]], [shots[3].uid, shots[4].uid])
        self.assertEqual(page1["next"], shots[3].uid)
        page2 = self.api.get(self.url(f"projects/{project.uid}/shots/"),
                             {"limit": 2, "before": page1["next"]}).json()
        self.assertEqual([s["uid"] for s in page2["items"]], [shots[1].uid, shots[2].uid])
        page3 = self.api.get(self.url(f"projects/{project.uid}/shots/"),
                             {"limit": 2, "before": page2["next"]}).json()
        self.assertEqual([s["uid"] for s in page3["items"]], [shots[0].uid])
        self.assertIsNone(page3["next"])

        item = page1["items"][1]
        self.assertEqual(set(item), {"uid", "project", "kind", "origin", "model", "prompt_doc", "prompt_text",
                                     "params", "inputs", "forked_from", "created_at", "takes"})
        self.assertEqual([i["label"] for i in item["inputs"]], ["Image 1", None])
        self.assertEqual(item["takes"][0]["status"], "done")
        self.assertEqual(item["project"], project.uid)

    def test_unknown_cursor_gives_empty_page(self):
        project = f.make_project(self.user)
        res = self.api.get(self.url(f"projects/{project.uid}/shots/"), {"before": "0" * 32}).json()
        self.assertEqual(res, {"items": [], "next": None})


# ---------------------------------------------------------------- материалы

class AssetsTests(ApiCase):
    def setUp(self):
        super().setUp()
        self.media = self.enterContext(f.media_root())

    def upload(self, blob, name="photo.jpg", **extra):
        return self.api.post(self.url("assets/"), {"file": SimpleUploadedFile(name, blob), **extra},
                             format="multipart")

    def test_library_lists_own_alive_with_filters_and_cursor(self):
        up1 = f.make_asset(self.user)
        gen = f.make_asset(self.user, source=Asset.SOURCE_GENERATED_IMAGE)
        up2 = f.make_asset(self.user)
        for n, a in enumerate((up1, gen, up2)):
            Asset.objects.filter(pk=a.pk).update(created_at=timezone.now() - timedelta(minutes=10 - n))
        f.make_asset(self.user, deleted_at=timezone.now())
        f.make_asset(self.other_user())
        f.make_asset(self.user, kind="video", source=Asset.SOURCE_GENERATED_VIDEO)

        items = self.api.get(self.url("assets/")).json()["items"]
        self.assertEqual([a["uid"] for a in items], [up2.uid, gen.uid, up1.uid])
        uploads = self.api.get(self.url("assets/"), {"source": "upload"}).json()["items"]
        self.assertEqual([a["uid"] for a in uploads], [up2.uid, up1.uid])
        page = self.api.get(self.url("assets/"), {"limit": 1}).json()
        self.assertEqual(page["next"], page["items"][0]["created_at"])
        rest = self.api.get(self.url("assets/"), {"limit": 5, "before": page["next"]}).json()
        self.assertEqual([a["uid"] for a in rest["items"]], [gen.uid, up1.uid])
        self.assertEqual(set(items[0]), {"uid", "kind", "source", "status", "url", "thumb_url", "width",
                                         "height", "duration_s", "label", "flags", "error_code",
                                         "created_at", "deleted"})
        self.assert_error(self.api.get(self.url("assets/"), {"source": "internet"}), 400, "bad_request")

    def test_upload_new_then_duplicate(self):
        project = f.make_project(self.user)
        blob = f.image_bytes(800, 600)
        res = self.upload(blob, project=project.uid)
        self.assertEqual(res.status_code, 201, res.content)
        data = res.json()
        self.assertEqual((data["kind"], data["source"], data["status"]), ("image", "upload", "ready"))
        self.assertEqual((data["width"], data["height"]), (800, 600))
        self.assertTrue(data["url"])
        self.assertEqual(Asset.objects.get(uid=data["uid"]).project_id, project.pk)
        again = self.upload(blob, name="same.jpg")
        self.assertEqual(again.status_code, 200)
        self.assertEqual(again.json()["uid"], data["uid"])

    def test_upload_refusals(self):
        self.assert_error(self.upload(b"hello", name="notes.txt"), 422, "unsupported_type")
        self.assert_error(self.upload(b"\x00" * 100, name="clip.mp4"), 422, "video_refs_unsupported")
        self.assert_error(self.upload(b"not an image", name="photo.jpg"), 422, "bad_image")
        self.assert_error(self.api.post(self.url("assets/"), {}, format="multipart"), 400, "bad_request")
        two = {"file": SimpleUploadedFile("a.jpg", f.image_bytes()),
               "other": SimpleUploadedFile("b.jpg", f.image_bytes(10, 10))}
        self.assert_error(self.api.post(self.url("assets/"), two, format="multipart"), 400, "bad_request")
        foreign = f.make_project(self.other_user())
        self.assert_error(self.upload(f.image_bytes(), project=foreign.uid), 404, "project_not_found")
        self.assertFalse(Asset.objects.exists())

    def test_soft_delete(self):
        asset = f.make_asset(self.user)
        self.assertEqual(self.api.delete(self.url(f"assets/{asset.uid}/")).status_code, 204)
        asset.refresh_from_db()
        first = asset.deleted_at
        self.assertIsNotNone(first)
        self.assertEqual(self.api.delete(self.url(f"assets/{asset.uid}/")).status_code, 204)
        asset.refresh_from_db()
        self.assertEqual(asset.deleted_at, first)
        foreign = f.make_asset(self.other_user())
        self.assert_error(self.api.delete(self.url(f"assets/{foreign.uid}/")), 404, "asset_not_found")
        foreign.refresh_from_db()
        self.assertIsNone(foreign.deleted_at)

    def test_last_frame_from_own_done_video(self):
        video = f.make_asset(self.user, kind="video", source=Asset.SOURCE_GENERATED_VIDEO)
        default_storage.save(video.file, ContentFile(b"\x00\x00\x00\x18ftypmp42" + b"\x00" * 64))
        take = f.make_take(f.make_shot(self.user, model=self.video), status="done", result_asset=video)
        frame = f.image_bytes(1280, 720)
        with mock.patch("ai.video_edit.extract_last_frame", return_value=frame):
            res = self.api.post(self.url("assets/from-take/"), {"take": take.uid, "at": "last_frame"},
                                format="json")
            self.assertEqual(res.status_code, 201, res.content)
            self.assertEqual(res.json()["source"], "frame")
            again = self.api.post(self.url("assets/from-take/"), {"take": take.uid}, format="json")
        self.assertEqual(again.status_code, 200)
        self.assertEqual(again.json()["uid"], res.json()["uid"])

        self.assert_error(self.api.post(self.url("assets/from-take/"), {"take": take.uid, "at": "first"},
                                        format="json"), 400, "bad_request")
        running = f.make_take(f.make_shot(self.user, model=self.video), status="running")
        self.assert_error(self.api.post(self.url("assets/from-take/"), {"take": running.uid}, format="json"),
                          409, "take_not_ready")
        foreign = f.make_take(f.make_shot(self.other_user(), model=self.video), status="done")
        self.assert_error(self.api.post(self.url("assets/from-take/"), {"take": foreign.uid}, format="json"),
                          404, "take_not_found")


# ---------------------------------------------------------------- помощники сериализации

class SerializerUnitTests(TestCase):
    def test_before_cursor_accepts_iso_forms(self):
        now = timezone.now().replace(microsecond=123456)
        text = S.iso(now)
        self.assertEqual(S.parse_before(text), now)
        self.assertEqual(S.parse_before(text.replace("+", " ")), now)  # «+» из адреса без кодирования
        utc = now.astimezone(dt_timezone.utc).isoformat().replace("+00:00", "Z")
        self.assertEqual(S.parse_before(utc), now)
        self.assertIsNone(S.parse_before(""))

    def test_auto_title(self):
        self.assertEqual(S.auto_title("  @Image 1   идёт \n по крыше "), "@Image 1 идёт по крыше")
        long = S.auto_title("слово " * 30)
        self.assertLessEqual(len(long), Project.AUTO_TITLE_CHARS + 1)
        self.assertTrue(long.endswith("…"))
