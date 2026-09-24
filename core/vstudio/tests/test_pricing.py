"""Цены видеостудии (vstudio/pricing.py, спецификация §5.1).

Цена считается по результату компилятора той же формулой, что в чате
(ai.video_cost.video_credits) и у картинок FLUX (flux_charge_credits):
оплачивается только отправляемое, раскладка сходится с итогом, при неверных
параметрах цены нет вовсе, а не «цена за другой ролик».
"""
from decimal import Decimal
from unittest import mock

from django.test import SimpleTestCase, TestCase

from ai.models import GenerationLog
from vstudio import caps as caps_mod
from vstudio import compiler as C
from vstudio import pricing
from vstudio import prompt_doc as pd
from vstudio.models import Take
from vstudio.tests import factories as f
from vstudio.tests.caps_fixtures import SEEDANCE_20, VEO_FAST, make_caps, model

SITE = "https://esai.kg"
A, B, D = "a" * 32, "b" * 32, "d" * 32
SEEDANCE = "bytedance/seedance-2.0"
NANO = "google/gemini-2.5-flash-image"
CREDIT_USD = 0.01
MARGIN = 0.4

# Прайс «за секунду» — цифры считаются в уме: 720p 5 с = $0.50, фото по $0.04.
PRICED = dict(SEEDANCE_20, supported_resolutions=["480p", "720p", "1080p"], pricing_skus={
    "duration_seconds_480p": "0.05", "duration_seconds_720p": "0.10",
    "duration_seconds_1080p": "0.25", "reference_images": "0.04"})


def _storage(name):
    return "/media/" + name


def _asset(uid, w=1080, h=1920, **kw):
    kw.setdefault("file", f"vstudio/42/{uid}.jpg")
    return C.AssetView(uid=uid, width=w, height=h, **kw)


def ref(uid, pos=0, included=True, **akw):
    return C.ResolvedInput(_asset(uid, **akw), "reference", pos, "", included)


def first(uid, **akw):
    return C.ResolvedInput(_asset(uid, **akw), "first_frame", 0, "", True)


def compile_(caps, text, inputs=(), params=None, kind=None, ok=True):
    inputs = list(inputs)
    doc = pd.from_text(text, inputs).doc
    out = C.compile(caps, kind or (caps.kind if caps else "video"), doc, inputs, params or {},
                    site_base=SITE, storage_url=_storage)
    if ok:
        assert out.ok, out.errors
    return out


class _Money:
    """Цена кредита и маржа фиксированы: цифры не зависят от пакетов в БД."""

    def setUp(self):
        super().setUp()
        for target, value in (("ai.video_cost.cheapest_credit_usd", CREDIT_USD),
                              ("ai.video_cost.min_margin", MARGIN)):
            patcher = mock.patch(target, return_value=value)
            patcher.start()
            self.addCleanup(patcher.stop)


class VideoPriceTests(_Money, SimpleTestCase):
    def setUp(self):
        super().setUp()
        self.caps = make_caps(SEEDANCE, spec=PRICED)
        self.cheap = model(SEEDANCE, markup_coefficient=5)     # цену держит себестоимость
        self.pricey = model(SEEDANCE, markup_coefficient=32)   # цену держит тариф

    def _price(self, compiled, model_obj=None):
        return pricing.price(compiled, model_obj or self.cheap, self.caps, spec=PRICED)

    def test_same_formula_as_chat_with_sent_images_and_price_aspect(self):
        compiled = compile_(self.caps, "@Image 1 and @Image 2 dance", [ref(A, 0), ref(B, 1)],
                            {"duration": 10, "resolution": "720p", "aspect_ratio": "9:16"})
        self.assertEqual(compiled.billable_images, 2)
        with mock.patch("ai.video_cost.video_credits", side_effect=[170, 150]) as vc:
            got = self._price(compiled)
        self.assertEqual(vc.call_args_list, [
            mock.call(self.cheap, PRICED, "720p", 10, images=2, aspect="9:16"),
            mock.call(self.cheap, PRICED, "720p", 10, images=0, aspect="9:16"),
        ])
        self.assertEqual(got.credits, 170)
        self.assertEqual(got.breakdown, [
            {"key": "price.video", "params": {"s": 10, "res": "720p", "ar": "9:16", "price_ar": "9:16"},
             "credits": 150},
            {"key": "price.refs", "params": {"n": 2}, "credits": 20},
        ])

    def test_refs_line_is_the_difference_and_lines_sum_to_total(self):
        # 720p 5 с: $0.50 → 84 кр по себестоимости; два фото +$0.08 → 97 кр.
        compiled = compile_(self.caps, "@Image 1 meets @Image 2", [ref(A, 0), ref(B, 1)],
                            {"duration": 5, "resolution": "720p", "aspect_ratio": "16:9"})
        got = self._price(compiled)
        self.assertEqual(got.credits, 97)
        self.assertEqual([(l["key"], l["credits"]) for l in got.breakdown],
                         [("price.video", 84), ("price.refs", 13)])
        self.assertEqual(sum(l["credits"] for l in got.breakdown), got.credits)

    def test_refs_line_hidden_when_tariff_already_covers_the_photos(self):
        compiled = compile_(self.caps, "@Image 1 meets @Image 2", [ref(A, 0), ref(B, 1)],
                            {"duration": 5, "resolution": "720p", "aspect_ratio": "16:9"})
        got = self._price(compiled, self.pricey)
        self.assertEqual(got.credits, 160)   # 5 с × 32 кр
        self.assertEqual([l["key"] for l in got.breakdown], ["price.video"])

    def test_resolution_changes_the_price(self):
        def at(res):
            return self._price(compile_(self.caps, "A girl on a roof", (),
                                        {"duration": 5, "resolution": res, "aspect_ratio": "16:9"})).credits

        self.assertEqual((at("480p"), at("720p"), at("1080p")), (42, 84, 209))

    def test_excluded_photo_is_not_paid(self):
        both = compile_(self.caps, "@Image 1 and @Image 2", [ref(A, 0), ref(B, 1)],
                        {"duration": 5, "resolution": "720p", "aspect_ratio": "16:9"})
        one = compile_(self.caps, "@Image 1 walks", [ref(A, 0), ref(B, 1, included=False)],
                       {"duration": 5, "resolution": "720p", "aspect_ratio": "16:9"})
        self.assertEqual(one.billable_images, 1)
        # $0.54 / 0.6 / $0.01 = 90.000…01 → 91: та же арифметика, что в чате.
        self.assertEqual(self._price(one).credits, 91)
        self.assertLess(self._price(one).credits, self._price(both).credits)
        self.assertEqual(self._price(one).breakdown[-1], {"key": "price.refs", "params": {"n": 1},
                                                          "credits": 7})

    def test_auto_aspect_prices_by_first_frame(self):
        compiled = compile_(self.caps, "The girl starts to run", [first(D, w=1080, h=1920)],
                            {"duration": 5, "resolution": "720p", "aspect_ratio": "auto"})
        self.assertEqual(compiled.price_aspect, "9:16")
        with mock.patch("ai.video_cost.video_credits", return_value=90) as vc:
            got = self._price(compiled)
        total_call = vc.call_args_list[0]
        self.assertEqual(total_call.kwargs["aspect"], "9:16")
        self.assertEqual(total_call.kwargs["images"], 1)   # кадр тоже оплачиваемое фото
        self.assertEqual(got.breakdown[0]["params"]["ar"], "auto")
        self.assertEqual(got.breakdown[0]["params"]["price_ar"], "9:16")

    def test_forced_duration_is_what_gets_paid(self):
        caps = make_caps("google/veo-3.1-fast", overrides={"refs_verified": "2026-09-24"},
                         spec=VEO_FAST)
        compiled = compile_(caps, "(the subject of @Image 1) waves", [ref(A, 0)],
                            {"duration": 4, "resolution": "720p", "aspect_ratio": "16:9"})
        self.assertEqual(compiled.effective["duration"], 8)
        with mock.patch("ai.video_cost.video_credits", return_value=200) as vc:
            pricing.price(compiled, model("google/veo-3.1-fast"), caps, spec=VEO_FAST)
        self.assertEqual(vc.call_args.args[3], 8)

    def test_quote_and_run_get_the_same_number(self):
        compiled = compile_(self.caps, "@Image 1 dances", [ref(A, 0)],
                            {"duration": 7, "resolution": "1080p", "aspect_ratio": "21:9"})
        self.assertEqual(self._price(compiled), self._price(compiled))
        self.assertEqual(self._price(compiled).to_dict()["credits"], self._price(compiled).credits)

    def test_catalog_spec_is_read_when_not_passed(self):
        compiled = compile_(self.caps, "A girl on a roof", (),
                            {"duration": 5, "resolution": "720p", "aspect_ratio": "16:9"})
        with mock.patch("vstudio.caps.catalog_spec", return_value=PRICED) as spec:
            got = pricing.price(compiled, self.cheap, self.caps)
        spec.assert_called_once_with(SEEDANCE)
        self.assertEqual(got.credits, 84)


class NoPriceTests(_Money, SimpleTestCase):
    def setUp(self):
        super().setUp()
        self.caps = make_caps(SEEDANCE, spec=PRICED)
        self.model = model(SEEDANCE, markup_coefficient=5)

    def test_wrong_params_give_no_price_instead_of_a_price_for_defaults(self):
        for params in ({"duration": 3}, {"resolution": "8K"}, {"aspect_ratio": "5:1"}):
            compiled = compile_(self.caps, "A girl", (), params, ok=False)
            self.assertEqual(compiled.errors[0]["code"], "invalid_param", params)
            got = pricing.price(compiled, self.model, self.caps, spec=PRICED)
            self.assertIs(got, pricing.NO_PRICE, params)
            self.assertEqual(got.to_dict(), {"credits": None, "breakdown": []})

    def test_hidden_model_or_broken_document(self):
        compiled = C.compile(None, "video", pd.from_text("A girl", []).doc, [], {}, site_base=SITE)
        self.assertFalse(pricing.price(compiled, self.model, None).ok)
        self.assertFalse(pricing.price(compiled, self.model, self.caps, spec=PRICED).ok)
        broken = C.compile(self.caps, "video", {"v": 2}, [], {}, site_base=SITE)
        self.assertEqual(broken.errors[0]["code"], "prompt_doc_invalid")
        self.assertFalse(pricing.price(broken, self.model, self.caps, spec=PRICED).ok)
        self.assertFalse(pricing.price(None, self.model, self.caps).ok)
        self.assertFalse(pricing.price(broken, None, self.caps).ok)

    def test_kind_mismatch(self):
        image = caps_mod.for_model(model(NANO))
        compiled = compile_(self.caps, "A girl", (), {"duration": 5})
        self.assertFalse(pricing.price(compiled, self.model, image).ok)

    def test_other_blocking_errors_still_show_the_price(self):
        # Слишком длинный текст — запуск заблокирован, но цену на кнопке видно.
        compiled = C.Compiled(kind="video", model=SEEDANCE, errors=[C.issue("prompt_too_long")],
                              effective={"duration": 5, "resolution": "720p", "aspect_ratio": "16:9"},
                              price_aspect="16:9")
        self.assertEqual(pricing.price(compiled, self.model, self.caps, spec=PRICED).credits, 84)


class ImagePriceTests(SimpleTestCase):
    def test_flat_price_per_image_like_flux_and_cartoon_frames(self):
        caps = caps_mod.for_model(model(NANO))
        compiled = compile_(caps, "a cat in a hat", (), {"aspect_ratio": "auto"})
        for markup, want in ((7, 7), (Decimal("6.9"), 6), (Decimal("0.5"), 1)):
            got = pricing.price(compiled, model(NANO, markup_coefficient=markup), caps)
            self.assertEqual(got.credits, want)
            self.assertEqual(got.breakdown, [{"key": "price.image", "params": {"n": 1}, "credits": want}])

    def test_reference_photos_do_not_change_image_price(self):
        caps = caps_mod.for_model(model(NANO))
        with_refs = compile_(caps, "@Image 1 and @Image 2 as a poster", [ref(A, 0), ref(B, 1)],
                             {"aspect_ratio": "1:1"})
        self.assertEqual(with_refs.mode, "i2i")
        self.assertEqual(pricing.price(with_refs, model(NANO, markup_coefficient=6), caps).credits, 6)


class ModelPricesTests(_Money, SimpleTestCase):
    def test_video_hints_use_the_same_formula_without_images(self):
        caps = make_caps(SEEDANCE, spec=PRICED)
        m = model(SEEDANCE, markup_coefficient=5)
        got = pricing.model_prices(m, caps, spec=PRICED)
        table = got["price"]["table"]
        self.assertEqual(sorted(table), ["1080p", "480p", "720p"])
        self.assertEqual(table["720p"]["5"], 84)
        self.assertEqual(table["1080p"]["5"], 209)
        self.assertEqual(got["price"]["by_aspect"], {})   # прайс за секунду от пропорций не зависит
        self.assertEqual(got["price_from"], min(c for row in table.values() for c in row.values()))
        self.assertEqual(got["price_from"], table["480p"]["4"])
        self.assertIsNone(got["per_image"])

    def test_image_hint_is_the_per_image_price(self):
        caps = caps_mod.for_model(model(NANO))
        got = pricing.model_prices(model(NANO, markup_coefficient=6), caps)
        self.assertEqual(got, {"price": None, "per_image": 6, "price_from": 6})

    def test_hidden_model(self):
        self.assertEqual(pricing.model_prices(model(SEEDANCE), None),
                         {"price": None, "per_image": None, "price_from": None})


class MarginTests(_Money, TestCase):
    def _take(self, credits=100, cost="0.90"):
        take = f.make_take(status=Take.STATUS_DONE, credits=credits, genlog=True)
        Take.objects.filter(pk=take.pk).update(provider_cost_usd=Decimal(cost))
        take.refresh_from_db()
        return take

    def _stages(self, take):
        return [s["stage"] for s in GenerationLog.objects.get(pk=take.genlog_id).stages]

    def test_low_margin_warns_and_marks_the_journal(self):
        take = self._take(credits=100, cost="0.90")   # 100 кр ≈ $1.00, ×0.6 = $0.60 < $0.90
        with self.assertLogs("vstudio.pricing", level="WARNING") as logs:
            self.assertIs(pricing.check_margin(take), False)
        self.assertIn("vstudio low margin", logs.output[0])
        self.assertIn(take.uid, logs.output[0])
        self.assertEqual(self._stages(take)[-1], "low_margin")

    def test_healthy_margin_is_quiet(self):
        take = self._take(credits=100, cost="0.50")
        self.assertIs(pricing.check_margin(take), True)
        self.assertNotIn("low_margin", self._stages(take))

    def test_cost_can_be_passed_explicitly(self):
        take = self._take(credits=100, cost="0.10")
        self.assertIs(pricing.check_margin(take, cost_usd="0.95"), False)

    def test_nothing_to_compare(self):
        take = self._take()
        self.assertIsNone(pricing.check_margin(take, cost_usd=0))
        Take.objects.filter(pk=take.pk).update(provider_cost_usd=None)
        take.refresh_from_db()
        self.assertIsNone(pricing.check_margin(take))
        # Бесплатный довоз из lost: списано 0 — это не «низкая маржа».
        free = f.make_take(status=Take.STATUS_DONE, credits=100, credits_charged=0)
        self.assertIsNone(pricing.check_margin(free, cost_usd="1.00"))
        with mock.patch("ai.video_cost.cheapest_credit_usd", return_value=None):
            self.assertIsNone(pricing.check_margin(self._take(), cost_usd="5"))

    def test_never_raises(self):
        take = self._take()
        with mock.patch("ai.video_cost.min_margin", side_effect=RuntimeError("boom")), \
                self.assertLogs("vstudio.pricing", level="ERROR"):
            self.assertIsNone(pricing.check_margin(take))
