"""Реестр: формулы себестоимости всех 15 инструментов, тела запросов, проверка полей."""
from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace

from django.test import SimpleTestCase

from creative import registry
from creative.registry import BuildCtx, cinema_tokens, cost_usd, get

from .helpers import CreativeTestCase, make_user

D = Decimal


def vid(duration):
    return {"v": SimpleNamespace(duration_s=duration, w=854, h=480, pixels=854 * 480)}


class RegistryShapeTests(SimpleTestCase):
    def test_ids_match_site_registry(self):
        expected = ["motion-transfer", "object-swap", "restyle", "character-motion", "item-swap",
                    "ad-creative", "photo-restyle", "text-to-image", "virtual-blogger",
                    "consistent-character", "portrait", "ad-campaign", "ad-poster", "product-ad",
                    "script-to-video"]
        self.assertEqual(list(registry.TOOL_IDS), expected)
        self.assertEqual([t.n for t in registry.TOOLS], list(range(1, 16)))

    def test_public_tools_have_no_model_paths(self):
        text = str(registry.public_tools()).lower()
        for word in ("higgsfield", "soul", "genjutsu", "marketing", "cinema", "ads-studio"):
            self.assertNotIn(word, text)

    def test_kinds_and_reasons(self):
        self.assertEqual(get("ad-creative").kind, "image")
        self.assertEqual(get("consistent-character").kind, "character")
        self.assertEqual(get("consistent-character").reason, "creative_character")
        self.assertEqual(get("script-to-video").reason, "creative_video")


class CostFormulaTests(SimpleTestCase):
    """Каждая формула §2 — на точных числах."""

    def test_motion_transfer_and_object_swap(self):
        for tool_id in ("motion-transfer", "object-swap"):
            t = get(tool_id)
            self.assertEqual(cost_usd(t, {"video": "v", "resolution": "480p"}, vid(4.0)), D("0.6160"))
            # 10.2 с → 11 оплаченных секунд
            self.assertEqual(cost_usd(t, {"video": "v", "resolution": "720p"}, vid(10.2)), D("3.7906"))
            # длиннее 30 с поставщик обрезает: дороже 30 с не бывает
            self.assertEqual(cost_usd(t, {"video": "v", "resolution": "1080p"}, vid(45)), D("25.0380"))

    def test_restyle(self):
        t = get("restyle")
        self.assertEqual(cost_usd(t, {"video": "v", "resolution": "480p"}, vid(4.0)), D("1.2720"))
        self.assertEqual(cost_usd(t, {"video": "v", "resolution": "1080p"}, vid(30)), D("48.9600"))

    def test_light_tools(self):
        for tool_id in ("character-motion", "item-swap"):
            t = get(tool_id)
            self.assertEqual(cost_usd(t, {"video": "v", "resolution": "480p"}, vid(4.0)), D("0.2956"))
            self.assertEqual(cost_usd(t, {"video": "v", "resolution": "720p"}, vid(4.0001)), D("0.5884"))

    def test_ad_creative(self):
        t = get("ad-creative")
        self.assertEqual(cost_usd(t, {"count": 1}), D("0.1500"))
        self.assertEqual(cost_usd(t, {"count": 3}), D("0.4500"))

    def test_photo_restyle(self):
        t = get("photo-restyle")
        # medium 1k = $0.063 × 1.25 за входное фото
        self.assertEqual(cost_usd(t, {"image": "x", "quality": "medium", "resolution": "1k"}), D("0.0788"))
        self.assertEqual(cost_usd(t, {"image": "x", "quality": "low", "resolution": "2k"}), D("0.0288"))

    def test_soul_tools(self):
        self.assertEqual(cost_usd(get("text-to-image"), {"resolution": "720p", "count": 1}), D("0.0040"))
        self.assertEqual(cost_usd(get("text-to-image"), {"resolution": "1080p", "count": 4}), D("0.0230"))
        self.assertEqual(cost_usd(get("portrait"), {"resolution": "720p", "count": 1}), D("0.0940"))
        self.assertEqual(cost_usd(get("portrait"), {"resolution": "1080p", "count": 4}), D("0.3130"))

    def test_flat_tools(self):
        self.assertEqual(cost_usd(get("virtual-blogger"), {}), D("0.0500"))
        self.assertEqual(cost_usd(get("consistent-character"), {"photos": ["a", "b", "c"]}), D("2.5000"))

    def test_ad_campaign(self):
        t = get("ad-campaign")
        self.assertEqual(cost_usd(t, {"quality": "high", "resolution": "2k"}), D("0.4390"))
        self.assertEqual(cost_usd(t, {"quality": "low", "resolution": "1k"}), D("0.0170"))
        # пресет: качество принудительно high; фото товара — фиксированная надбавка $0.014
        self.assertEqual(cost_usd(t, {"quality": "medium", "resolution": "1k", "preset": "p",
                                      "product_images": ["a"]}), D("0.2350"))
        # 8 фото: таблица + 8 × $0.014, а не втрое дороже таблицы
        self.assertEqual(cost_usd(t, {"quality": "high", "resolution": "2k",
                                      "product_images": list("abcdefgh")}), D("0.5510"))

    def test_token_tools(self):
        self.assertEqual(cost_usd(get("ad-poster"), {"quality": "low", "resolution": "1k"}), D("0.0375"))
        self.assertEqual(cost_usd(get("product-ad"), {"quality": "medium", "resolution": "2k",
                                                      "product_images": ["a", "b"]}), D("0.2225"))
        # у Flare пресет качество не меняет
        self.assertEqual(cost_usd(get("ad-poster"), {"quality": "low", "resolution": "1k", "preset": "p",
                                                     "product_images": ["a"]}), D("0.0550"))

    def test_script_to_video(self):
        t = get("script-to-video")
        self.assertEqual(cinema_tokens(4, "480p", "16:9"), 38430)
        self.assertEqual(cost_usd(t, {"duration": 4, "resolution": "480p", "aspect": "16:9"}), D("0.8225"))
        # 1:1 не дешевле 16:9 (берём не меньше площади 16:9)
        self.assertEqual(cost_usd(t, {"duration": 4, "resolution": "480p", "aspect": "1:1"}), D("0.8225"))
        # 21:9 шире — дороже
        self.assertEqual(cost_usd(t, {"duration": 5, "resolution": "720p", "aspect": "21:9"}), D("3.0335"))

    def test_hint_prices_exist_for_every_tool(self):
        for t in registry.TOOLS:
            params, inputs = registry.hint_params(t)
            self.assertGreater(cost_usd(t, params, inputs), 0, t.id)


class BuildBodyTests(SimpleTestCase):
    ctx = BuildCtx(urls={"v": "https://f/v.mp4", "i": "https://f/i.jpg", "j": "https://f/j.jpg",
                         "k": "https://f/k.jpg"},
                   character_provider_id="char-1", neutral_name="esai-abc")

    def body(self, tool_id, params):
        return registry.build_body(get(tool_id), params, self.ctx)

    def test_genjutsu_omits_empty_prompt(self):
        self.assertEqual(self.body("motion-transfer", {"video": "v", "image": "i", "resolution": "480p"}),
                         {"video_url": "https://f/v.mp4", "image_urls": ["https://f/i.jpg"], "resolution": "480p"})
        self.assertEqual(self.body("object-swap", {"video": "v", "image": "i", "resolution": "720p",
                                                   "prompt": "cup"})["prompt"], "cup")

    def test_restyle(self):
        self.assertEqual(self.body("restyle", {"video": "v", "style": "s-1", "resolution": "480p"}),
                         {"video_url": "https://f/v.mp4", "preset_id": "s-1", "resolution": "480p"})
        self.assertEqual(self.body("restyle", {"video": "v", "style": "s", "resolution": "480p",
                                               "images": ["i", "j"]})["image_urls"],
                         ["https://f/i.jpg", "https://f/j.jpg"])

    def test_ads(self):
        self.assertEqual(self.body("ad-creative", {"prompt": "чай", "count": 2, "aspect": "1:1", "language": "ru",
                                                   "audience": "студенты"}),
                         {"prompt": "чай", "batch_size": 2, "aspect_ratio": "1:1", "language": "ru",
                          "target_audience": "студенты"})

    def test_photo_restyle_edit_mode(self):
        self.assertEqual(self.body("photo-restyle", {"image": "i", "prompt": "студия", "quality": "medium",
                                                     "resolution": "1k", "aspect": "auto"}),
                         {"prompt": "студия", "image_urls": ["https://f/i.jpg"], "enhance_prompt": False,
                          "quality": "medium", "resolution": "1k"})

    def test_ms_preset(self):
        body = self.body("ad-campaign", {"prompt": "p", "quality": "low", "resolution": "1k", "aspect": "auto",
                                         "preset": "pr-1", "product_images": ["i"]})
        self.assertEqual(body, {"prompt": "p", "resolution": "1k", "preset_id": "pr-1", "enhance_prompt": True,
                                "quality": "high", "image_urls": ["https://f/i.jpg"]})
        body = self.body("ad-poster", {"prompt": "p", "quality": "low", "resolution": "2k", "aspect": "9:16",
                                       "preset": "pr-1", "product_images": ["i"]})
        self.assertEqual(body["quality"], "low")
        self.assertEqual(body["aspect_ratio"], "9:16")

    def test_soul(self):
        self.assertEqual(self.body("text-to-image", {"prompt": "p", "aspect": "1:1", "resolution": "720p",
                                                     "count": 4, "character": "x"}),
                         {"prompt": "p", "aspect_ratio": "1:1", "resolution": "720p", "batch_size": 4,
                          "custom_reference_id": "char-1"})
        self.assertEqual(self.body("portrait", {"prompt": "p", "aspect": "3:4", "resolution": "1080p",
                                                "count": 1, "style": "st"})["style_id"], "st")

    def test_influencer_and_character(self):
        self.assertEqual(self.body("virtual-blogger", {}), {"tier": "normal"})
        self.assertEqual(self.body("virtual-blogger", {"options": {"gender": ["female"]}, "brief": "b"}),
                         {"tier": "normal", "selection": {"gender": ["female"]}, "brief": "b"})
        body = self.body("consistent-character", {"name": "Моё имя", "photos": ["i", "j", "k"]})
        self.assertEqual(body["name"], "esai-abc")       # имя человека поставщику не уходит
        self.assertEqual(body["model_version"], "v2")
        self.assertEqual(len(body["input_images"]), 3)

    def test_cinema_auto_fields_omitted(self):
        body = self.body("script-to-video", {"prompt": "p", "duration": 5, "resolution": "480p",
                                             "aspect": "16:9", "audio": False, "genre": "noir"})
        self.assertEqual(body, {"prompt": "p", "duration": 5, "resolution": "480p", "aspect_ratio": "16:9",
                                "generate_audio": False, "genre": "noir"})


class ValidationTests(CreativeTestCase):
    def setUp(self):
        super().setUp()
        self.user = make_user(balance=1000)

    def codes(self, tool_id, params, lookup=None):
        v = registry.validate(get(tool_id), params, user=self.user, catalog_lookup=lookup)
        return {(e["field"], e["code"]) for e in v.errors}, v

    def test_missing_required(self):
        codes, _ = self.codes("motion-transfer", {})
        self.assertIn(("video", "required"), codes)
        self.assertIn(("image", "required"), codes)
        self.assertIn(("consent", "consent_required"), codes)
        codes, _ = self.codes("portrait", {"prompt": "  "})
        self.assertIn(("prompt", "required"), codes)

    def test_bad_enum_and_range(self):
        codes, _ = self.codes("portrait", {"prompt": "p", "resolution": "4k", "count": 3})
        self.assertIn(("resolution", "bad_value"), codes)
        self.assertIn(("count", "bad_value"), codes)
        codes, _ = self.codes("script-to-video", {"prompt": "p", "duration": 16})
        self.assertIn(("duration", "out_of_range"), codes)

    def test_defaults_applied(self):
        codes, v = self.codes("portrait", {"prompt": "кот"})
        self.assertFalse(codes)
        self.assertEqual(v.params, {"prompt": "кот", "aspect": "3:4", "resolution": "720p", "count": 1})

    def test_video_too_short_and_small_frame(self):
        img = self.make_image(self.user)
        short = self.make_video(self.user, duration=3.2)
        codes, _ = self.codes("motion-transfer", {"video": short.uid, "image": img.uid, "consent": True})
        self.assertIn(("video", "too_short"), codes)
        small = self.make_video(self.user, duration=5, w=640, h=480)
        codes, _ = self.codes("object-swap", {"video": small.uid, "image": img.uid, "prompt": "cup",
                                              "consent": True})
        self.assertIn(("video", "too_small_frame"), codes)
        # для переноса движения кадр 640×480 подходит
        codes, _ = self.codes("motion-transfer", {"video": small.uid, "image": img.uid, "consent": True})
        self.assertFalse(codes)

    def test_foreign_and_wrong_kind_uploads(self):
        other = make_user()
        foreign = self.make_image(other)
        video = self.make_video(self.user)
        codes, _ = self.codes("photo-restyle", {"image": foreign.uid, "prompt": "p", "consent": True})
        self.assertIn(("image", "not_found"), codes)
        codes, _ = self.codes("photo-restyle", {"image": video.uid, "prompt": "p", "consent": True})
        self.assertIn(("image", "wrong_kind"), codes)

    def test_images_with_non_string_items_are_bad_type(self):
        """Список картинок из словарей/списков — 422 bad_type, а не TypeError (500)."""
        for bad in ([{"a": 1}], [["x"]], ["ok", 5]):
            codes, _ = self.codes("ad-campaign", {"prompt": "p", "product_images": bad})
            self.assertIn(("product_images", "bad_type"), codes)

    def test_ms_preset_needs_product_photo(self):
        lookup = lambda kind: None   # каталог не известен — проверяем только вид uuid
        codes, _ = self.codes("ad-campaign", {"prompt": "p", "preset": "5f7e5c32-068e-533b-b10e-fca42ca993af"},
                              lookup)
        self.assertIn(("product_images", "too_few"), codes)
        codes, _ = self.codes("ad-campaign", {"prompt": "p", "preset": "not-a-uuid"}, lookup)
        self.assertIn(("preset", "bad_value"), codes)

    def test_catalog_membership(self):
        known = {"c2143317-f28d-4c3c-a0b8-39bd547e08a7"}
        video = self.make_video(self.user)
        codes, _ = self.codes("restyle", {"video": video.uid, "style": "c2143317-f28d-4c3c-a0b8-39bd547e08a7",
                                          "consent": True}, lambda kind: known)
        self.assertFalse(codes)
        codes, _ = self.codes("restyle", {"video": video.uid, "style": "11111111-1111-1111-1111-111111111111"},
                              lambda kind: known)
        self.assertIn(("style", "bad_value"), codes)

    def test_character_ownership_and_state(self):
        mine = self.make_character(self.user)
        training = self.make_character(self.user, status="training", provider_id="")
        foreign = self.make_character(make_user())
        codes, v = self.codes("text-to-image", {"prompt": "p", "character": mine.uid})
        self.assertFalse(codes)
        self.assertEqual(v.character.pk, mine.pk)
        codes, _ = self.codes("text-to-image", {"prompt": "p", "character": training.uid})
        self.assertIn(("character", "character_not_ready"), codes)
        codes, _ = self.codes("text-to-image", {"prompt": "p", "character": foreign.uid})
        self.assertIn(("character", "not_found"), codes)

    def test_soul_id_photo_count(self):
        imgs = [self.make_image(self.user) for _ in range(2)]
        codes, _ = self.codes("consistent-character", {"name": "Я", "photos": [i.uid for i in imgs],
                                                       "consent": True})
        self.assertIn(("photos", "too_few"), codes)

    def test_influencer_options(self):
        cats = [{"key": "gender", "label": "Gender", "max": 1,
                 "options": [{"key": "female", "exclusive": False}, {"key": "male", "exclusive": False}]},
                {"key": "accessory", "label": "Acc", "max": 3,
                 "options": [{"key": "acc_none", "exclusive": True}, {"key": "acc_hat", "exclusive": False}]}]
        lookup = lambda kind: cats
        codes, v = self.codes("virtual-blogger", {"options": {"gender": ["female"]}}, lookup)
        self.assertFalse(codes)
        self.assertEqual(v.params["options"], {"gender": ["female"]})
        codes, _ = self.codes("virtual-blogger", {"options": {"gender": ["female", "male"]}}, lookup)
        self.assertIn(("options", "too_many"), codes)
        codes, _ = self.codes("virtual-blogger", {"options": {"accessory": ["acc_none", "acc_hat"]}}, lookup)
        self.assertIn(("options", "bad_value"), codes)
        codes, _ = self.codes("virtual-blogger", {"options": {"wings": ["x"]}}, lookup)
        self.assertIn(("options", "bad_value"), codes)
