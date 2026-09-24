"""Компилятор запроса (vstudio/compiler.py, спецификация §4.4–4.7).

Эталонные тела по семействам и режимам плюс инварианты: кадры и референсы
никогда не уходят вместе, текст не обрезается, скрытого 21:9 нет, выключенное
не оплачивается, номера следуют порядку лотка.
"""
import itertools
import json
import re

from django.test import SimpleTestCase, override_settings

from vstudio import caps as caps_mod
from vstudio import compiler as C
from vstudio import prompt_doc as pd
from vstudio.tests.caps_fixtures import SPECS, make_caps, model

SITE = "https://esai.kg"
A, B, D, E = "a" * 32, "b" * 32, "d" * 32, "e" * 32
F, L = "f" * 32, "0" * 32


def storage(name):
    return "/media/" + name


def url(uid):
    return f"{SITE}/media/vstudio/42/{uid}.jpg"


def asset(uid, w=1080, h=1920, **kw):
    kw.setdefault("file", f"vstudio/42/{uid}.jpg")
    return C.AssetView(uid=uid, width=w, height=h, **kw)


def ref_in(uid, pos=0, role="", included=True, **akw):
    return C.ResolvedInput(asset(uid, **akw), "reference", pos, role, included)


def frame_in(uid, slot="first_frame", included=True, **akw):
    return C.ResolvedInput(asset(uid, **akw), slot, 0, "", included)


def image_caps(model_id, overrides=None):
    return caps_mod.for_model(model(model_id, vstudio_overrides=overrides or {}))


def compile_(caps, text_or_doc, inputs=(), params=None, kind=None, **kw):
    inputs = list(inputs)
    doc = pd.from_text(text_or_doc, inputs).doc if isinstance(text_or_doc, str) else text_or_doc
    kw.setdefault("site_base", SITE)
    kw.setdefault("storage_url", storage)
    return C.compile(caps, kind or caps.kind, doc, inputs, params or {}, **kw)


def codes(items):
    return [i["code"] for i in items]


def find(items, code):
    return next(i for i in items if i["code"] == code)


EXAMPLE = "@Image 1 медленно идёт по старому двору @Image 2, камера плавно наезжает, тёплый закатный свет"


@override_settings(VIDEO_GEN_DURATION=5, VIDEO_GEN_RESOLUTION="720p")
class SeedanceTests(SimpleTestCase):
    def setUp(self):
        self.caps = make_caps("bytedance/seedance-2.0")

    def test_reference_example_from_spec(self):
        # §4.6 с шаблоном тега «[Image N]» (решение лида).
        inputs = [ref_in(A, 0, "героиня"), ref_in(B, 1)]
        got = compile_(self.caps, EXAMPLE, inputs, {"duration": 10, "resolution": "720p",
                                                    "aspect_ratio": "9:16", "generate_audio": True})
        self.assertEqual(got.errors, [])
        self.assertEqual(got.mode, "r2v")
        self.assertEqual(got.body, {
            "model": "bytedance/seedance-2.0",
            "prompt": ("[Image 1] is героиня.\n[Image 1] медленно идёт по старому двору [Image 2], "
                       "камера плавно наезжает, тёплый закатный свет"),
            "duration": 10, "resolution": "720p", "aspect_ratio": "9:16", "generate_audio": True,
            "input_references": [{"type": "image_url", "image_url": {"url": url(A)}},
                                 {"type": "image_url", "image_url": {"url": url(B)}}],
        })
        self.assertEqual(got.serialized_prompt, got.body["prompt"])
        self.assertEqual(got.prompt_text, EXAMPLE)
        self.assertEqual(got.labels, {A: "Image 1", B: "Image 2"})
        self.assertEqual(got.used, [{"asset": A, "slot": "reference", "label": "Image 1"},
                                    {"asset": B, "slot": "reference", "label": "Image 2"}])
        self.assertEqual(got.billable_images, 2)
        self.assertEqual(got.effective, {"duration": 10, "resolution": "720p", "aspect_ratio": "9:16",
                                         "generate_audio": True})
        self.assertEqual(got.price_aspect, "9:16")
        self.assertEqual(got.meter["level"], "ok")
        self.assertEqual(got.meter["hard_chars"], 6000)
        # Загруженное фото на Seedance — предупреждение про лица ДО оплаты; русский текст — lang_hint.
        self.assertEqual(sorted(codes(got.warnings)), ["faces_risk", "lang_hint"])
        self.assertEqual(find(got.warnings, "faces_risk")["params"]["assets"], [A, B])
        json.dumps(got.to_dict(), ensure_ascii=False)

    def test_text_to_video(self):
        got = compile_(self.caps, "A red fox runs through snow", params={}, site_base="")
        self.assertEqual(got.errors, [])
        self.assertEqual(got.mode, "t2v")
        # Без фото адрес сайта не нужен; параметры по умолчанию, пропорция «авто» не уходит.
        self.assertEqual(got.body, {"model": "bytedance/seedance-2.0", "prompt": "A red fox runs through snow",
                                    "duration": 5, "resolution": "720p", "generate_audio": True})
        self.assertEqual(got.effective["aspect_ratio"], "auto")
        self.assertEqual(got.price_aspect, "16:9")
        self.assertEqual(got.billable_images, 0)
        self.assertEqual(got.warnings, [])

    def test_first_frame(self):
        inputs = [frame_in(F)]
        got = compile_(self.caps, "@Первый кадр оживает: девушка оборачивается", inputs)
        self.assertEqual(got.errors, [])
        self.assertEqual(got.mode, "i2v")
        self.assertEqual(got.body["frame_images"], [
            {"type": "image_url", "image_url": {"url": url(F)}, "frame_type": "first_frame"}])
        self.assertNotIn("input_references", got.body)
        self.assertTrue(got.body["prompt"].startswith("the first frame оживает"))
        self.assertEqual(got.labels, {F: "first_frame"})
        self.assertEqual(got.prompt_text, "@Первый кадр оживает: девушка оборачивается")
        # «Авто»: цена по пропорции первого кадра (1080×1920 → 9:16).
        self.assertEqual(got.price_aspect, "9:16")
        self.assertNotIn("aspect_ratio", got.body)
        self.assertEqual(got.billable_images, 1)

    def test_first_and_last_frame(self):
        got = compile_(self.caps, "Переход от дня к ночи", [frame_in(F), frame_in(L, "last_frame")])
        self.assertEqual(got.mode, "flf2v")
        self.assertEqual([f["frame_type"] for f in got.body["frame_images"]], ["first_frame", "last_frame"])
        self.assertEqual(got.billable_images, 2)

    def test_soft_pin_sends_frame_as_last_reference(self):
        inputs = [ref_in(A, 0, "героиня"), ref_in(B, 1), frame_in(F)]
        got = compile_(self.caps, "@Image 1 выходит из @Image 2, начало как @Первый кадр", inputs)
        self.assertEqual(got.errors, [])
        self.assertEqual(got.mode, "r2v_pin")
        self.assertNotIn("frame_images", got.body)
        self.assertEqual([r["image_url"]["url"] for r in got.body["input_references"]], [url(A), url(B), url(F)])
        # Номера человека не сдвигаются: кадр — Image k = n + 1.
        self.assertEqual(got.body["prompt"],
                         "[Image 3] is the first frame of the video.\n[Image 1] is героиня.\n"
                         "[Image 1] выходит из [Image 2], начало как [Image 3]")
        pin = find(got.warnings, "frame_soft_pin")
        self.assertEqual(pin["params"]["k"], 3)
        self.assertIn("Image 3", pin["message"])
        self.assertEqual(got.billable_images, 3)
        self.assertEqual(got.used[-1], {"asset": F, "slot": "first_frame", "label": "Image 3"})
        self.assertEqual(got.labels[F], "first_frame")

    def test_last_frame_with_references_is_blocked(self):
        got = compile_(self.caps, "@Image 1 идёт", [ref_in(A), frame_in(F), frame_in(L, "last_frame")])
        err = find(got.errors, "last_frame_with_refs")
        self.assertEqual(err["fix"], {"action": "exclude_inputs", "assets": [L]})
        self.assertEqual(got.body, {})

    def test_too_many_references_counts_the_pinned_frame(self):
        uids = [f"{i:032x}" for i in range(1, 10)]
        inputs = [ref_in(u, i) for i, u in enumerate(uids)] + [frame_in(F)]
        got = compile_(self.caps, "Все вместе @Image 1", inputs)
        err = find(got.errors, "too_many_refs")
        self.assertEqual((err["params"]["max"], err["params"]["n"]), (9, 10))
        self.assertEqual(err["fix"], {"action": "exclude_inputs", "assets": [uids[-1]]})
        self.assertEqual(got.body, {})

    def test_hidden_21_9_is_off(self):
        text = "Кинематографичный кадр: девушка идёт по крыше"
        got = compile_(self.caps, text, params={"aspect_ratio": "16:9"})
        self.assertEqual(got.body["aspect_ratio"], "16:9")
        w = find(got.warnings, "aspect_in_text")
        self.assertEqual(w["params"], {"value": "21:9", "current": "16:9"})
        self.assertEqual(w["fix"], {"action": "set_param", "field": "aspect_ratio", "value": "21:9"})
        auto = compile_(self.caps, text, params={"aspect_ratio": "auto"})
        self.assertNotIn("aspect_ratio", auto.body)
        self.assertEqual(auto.price_aspect, "16:9")
        self.assertIn("авто", find(auto.warnings, "aspect_in_text")["message"])
        same = compile_(self.caps, text, params={"aspect_ratio": "21:9"})
        self.assertNotIn("aspect_in_text", codes(same.warnings))

    def test_hard_limit_blocks_and_nothing_is_cut(self):
        text = ("Очень длинное описание сцены. " * 250).strip()
        self.assertGreater(len(text), 6000)
        got = compile_(self.caps, text)
        err = find(got.errors, "prompt_too_long")
        self.assertEqual(err["params"]["hard"], 6000)
        self.assertEqual(err["params"]["chars"], len(text))
        self.assertEqual(err["fix"], {"action": "condense"})
        self.assertEqual(got.meter["level"], "hard")
        # Ни в сериализации, ни в человекочитаемом тексте ничего не обрезано.
        self.assertEqual(got.serialized_prompt, text)
        self.assertEqual(got.prompt_text, text)
        self.assertEqual(got.body, {})

    def test_soft_limit_warns(self):
        text = " ".join(["word"] * 200)
        got = compile_(self.caps, text)
        self.assertEqual(got.errors, [])
        w = find(got.warnings, "prompt_long")
        self.assertEqual(w["params"], {"model": "Seedance 2.0", "soft": 150, "words": 200})
        self.assertEqual(w["fix"], {"action": "condense"})
        self.assertEqual(got.meter, {"chars": len(text), "words": 200, "soft_words": 150,
                                     "hard_chars": 6000, "level": "soft"})
        self.assertEqual(got.body["prompt"], text)

    def test_looks_like_script(self):
        scene = "Героиня идёт по городу, вокруг огни и дождь, камера следует за ней. " * 12
        script = f"Сцена 1\n{scene}\nСцена 2\n{scene}"
        self.assertGreater(len(script), 1500)
        self.assertIn("looks_like_script", codes(compile_(self.caps, script).warnings))
        # Короткий текст со «Сцена 1» — ещё не сценарий.
        self.assertNotIn("looks_like_script", codes(compile_(self.caps, "Сцена 1\nСцена 2 коротко").warnings))
        # Длинное описание с одной связкой «затем» — тоже нет.
        self.assertNotIn("looks_like_script", codes(compile_(self.caps, scene * 2 + " затем").warnings))

    def test_renumbering_after_reorder(self):
        doc = {"v": 1, "blocks": [[{"t": "ref", "asset": A}, {"t": "text", "v": " держит "},
                                   {"t": "ref", "asset": B}]]}
        before = compile_(self.caps, doc, [ref_in(A, 0), ref_in(B, 1)])
        after = compile_(self.caps, doc, [ref_in(A, 1), ref_in(B, 0)])
        self.assertEqual(before.body["prompt"], "[Image 1] держит [Image 2]")
        self.assertEqual(after.body["prompt"], "[Image 2] держит [Image 1]")
        self.assertEqual(after.labels, {B: "Image 1", A: "Image 2"})
        self.assertEqual(after.prompt_text, "@Image 2 держит @Image 1")
        self.assertEqual([r["image_url"]["url"] for r in after.body["input_references"]], [url(B), url(A)])
        self.assertEqual([(i["asset"], i["position"]) for i in after.inputs], [(B, 0), (A, 1)])

    def test_excluded_inputs_are_not_sent_or_billed(self):
        inputs = [ref_in(A, 0), ref_in(B, 1, role="кухня", included=False)]
        got = compile_(self.caps, "@Image 1 готовит, фон — кухня", inputs)
        self.assertEqual(got.billable_images, 1)
        self.assertEqual(len(got.body["input_references"]), 1)
        self.assertEqual(got.dropped, [{"asset": B, "slot": "reference", "reason": "excluded_by_user"}])
        self.assertEqual(got.labels, {A: "Image 1"})
        # Выключенный, но упомянутый чип: модели — роль словами, человеку — предупреждение.
        doc = {"v": 1, "blocks": [[{"t": "ref", "asset": A}, {"t": "text", "v": " на фоне "},
                                   {"t": "ref", "asset": B}]]}
        got = compile_(self.caps, doc, inputs)
        self.assertEqual(got.body["prompt"], "[Image 1] на фоне кухня")
        self.assertEqual(got.prompt_text, "@Image 1 на фоне @Image —")
        w = find(got.warnings, "input_excluded")
        self.assertEqual(w["params"]["asset"], B)
        self.assertIn("не учитывается и не оплачивается", w["message"])

    def test_unmentioned_reference_is_still_sent(self):
        got = compile_(self.caps, "@Image 1 танцует", [ref_in(A, 0), ref_in(B, 1)])
        self.assertEqual(len(got.body["input_references"]), 2)
        w = find(got.warnings, "ref_unmentioned")
        self.assertEqual((w["params"]["asset"], w["params"]["n"]), (B, 2))
        self.assertTrue(w["message"].startswith("@Image 2 прикреплено"))

    def test_foreign_and_deleted_assets(self):
        # Чужой uid API не находит, поэтому его нет во входах → тег «не прикреплён».
        doc = {"v": 1, "blocks": [[{"t": "text", "v": "Кот и "}, {"t": "ref", "asset": D}]]}
        got = compile_(self.caps, doc, [ref_in(A)])
        self.assertEqual(find(got.errors, "mention_not_attached")["params"], {"asset": D})
        self.assertEqual(got.body, {})
        deleted = [ref_in(A, deleted=True)]
        got = compile_(self.caps, "@Image 1 бежит", deleted)
        self.assertIn("asset_not_found", codes(got.errors))
        # Повтор старого кадра: удалённое фото ещё живёт, пока на него ссылаются.
        got = compile_(self.caps, "@Image 1 бежит", deleted, allow_deleted=True)
        self.assertEqual(got.errors, [])

    def test_pending_and_failed_assets(self):
        got = compile_(self.caps, "@Image 1 бежит", [ref_in(A, status="pending")])
        err = find(got.errors, "asset_not_ready")
        self.assertEqual(err["params"]["n"], 1)
        self.assertEqual(err["message"], "@Image 1 ещё создаётся — подождите несколько секунд.")
        got = compile_(self.caps, "@Первый кадр оживает", [frame_in(F, status="failed")])
        self.assertEqual(find(got.errors, "asset_failed")["message"],
                         "@Первый кадр не получился — удалите его или создайте заново.")

    def test_invalid_params_are_not_snapped(self):
        got = compile_(self.caps, "Лес", params={"duration": 3, "resolution": "2K", "aspect_ratio": "5:4"})
        errs = {e["params"]["field"]: e for e in got.errors if e["code"] == "invalid_param"}
        self.assertEqual(set(errs), {"duration", "resolution", "aspect_ratio"})
        self.assertEqual(errs["duration"]["fix"], {"action": "set_param", "field": "duration", "value": 4})
        self.assertEqual(errs["duration"]["params"]["allowed"], list(range(4, 16)))
        self.assertIn("длительность = 3", errs["duration"]["message"])
        self.assertIn("auto", errs["aspect_ratio"]["params"]["allowed"])
        self.assertEqual(got.body, {})
        for bad in ("abc", 5.5, True, [5]):
            self.assertIn("invalid_param", codes(compile_(self.caps, "Лес", params={"duration": bad}).errors))
        ok = compile_(self.caps, "Лес", params={"duration": "8", "resolution": "1080P"})
        self.assertEqual((ok.body["duration"], ok.body["resolution"]), (8, "1080p"))

    def test_seed_and_audio(self):
        got = compile_(self.caps, "Лес", params={"seed": 42, "generate_audio": False})
        self.assertEqual((got.body["seed"], got.body["generate_audio"]), (42, False))
        self.assertIs(compile_(self.caps, "Лес", params={"generate_audio": "false"}).body["generate_audio"], False)
        for bad in ("x", -1, 2**32, True):
            self.assertIn("invalid_param", codes(compile_(self.caps, "Лес", params={"seed": bad}).errors))

    def test_negative_never_top_level(self):
        got = compile_(self.caps, "Лес", params={"negative_prompt": "blur"})
        self.assertNotIn("negative_prompt", got.body)
        self.assertNotIn("provider", got.body)

    def test_reference_size_and_aspect(self):
        got = compile_(self.caps, "@Image 1 и @Image 2", [ref_in(A, 0, w=200, h=400), ref_in(B, 1, w=3000, h=600)])
        small = find(got.errors, "ref_too_small")
        self.assertEqual((small["params"]["asset"], small["params"]["min"]), (A, 300))
        self.assertEqual(small["message"],
                         "@Image 1 слишком маленькое для Seedance 2.0: нужно от 300 px по короткой стороне.")
        wide = find(got.errors, "ref_bad_aspect")
        self.assertEqual(wide["params"]["asset"], B)
        self.assertIn("от 2:5 до 5:2", wide["message"])
        frame = compile_(self.caps, "Старт", [frame_in(F, w=100, h=100)])
        self.assertIn("@Первый кадр слишком маленький", find(frame.errors, "ref_too_small")["message"])
        # Размер неизвестен — не придираемся.
        self.assertEqual(compile_(self.caps, "@Image 1 бежит", [ref_in(A, w=None, h=None)]).errors, [])

    def test_faces_risk_only_for_uploads(self):
        got = compile_(self.caps, "@Image 1 бежит", [ref_in(A, source="generated_image")])
        self.assertNotIn("faces_risk", codes(got.warnings))

    def test_site_base_is_required_for_images(self):
        got = compile_(self.caps, "@Image 1 бежит", [ref_in(A)], site_base="")
        self.assertEqual(codes(got.errors), ["service_misconfigured"])
        self.assertEqual(got.body, {})
        # Локальный стенд: ссылки остаются относительными, submit подменит их data-URL.
        dev = compile_(self.caps, "@Image 1 бежит", [ref_in(A)], site_base="", inline_refs=True)
        self.assertEqual(dev.errors, [])
        self.assertEqual(dev.body["input_references"][0]["image_url"]["url"], f"/media/vstudio/42/{A}.jpg")
        # Слэш в конце адреса сайта и абсолютные ссылки хранилища.
        got = compile_(self.caps, "@Image 1 бежит", [ref_in(A)], site_base="https://esai.kg/",
                       storage_url=lambda n: "https://cdn.example.com/" + n)
        self.assertEqual(got.body["input_references"][0]["image_url"]["url"],
                         f"https://cdn.example.com/vstudio/42/{A}.jpg")

    def test_default_storage_url(self):
        got = C.compile(self.caps, "video", pd.from_text("@Image 1 бежит", [ref_in(A)]).doc, [ref_in(A)], {},
                        site_base="https://esai.kg/")
        self.assertEqual(got.body["input_references"][0]["image_url"]["url"], url(A))

    def test_prompt_empty(self):
        got = compile_(self.caps, "@Image 1   ", [ref_in(A)])
        self.assertIn("prompt_empty", codes(got.errors))
        self.assertIn("prompt_empty", codes(compile_(self.caps, "").errors))

    def test_bad_doc_and_model(self):
        got = C.compile(self.caps, "video", {"v": 2, "blocks": []}, [], {}, site_base=SITE)
        self.assertEqual(codes(got.errors), ["prompt_doc_invalid"])
        self.assertEqual(codes(C.compile(None, "video", pd.empty_doc(), [], {}, site_base=SITE).errors),
                         ["model_unavailable"])
        self.assertEqual(codes(C.compile(self.caps, "image", pd.empty_doc(), [], {}, site_base=SITE).errors),
                         ["model_unavailable"])

    def test_too_many_inputs(self):
        inputs = [ref_in(f"{i:032x}", i, included=False) for i in range(17)]
        self.assertIn("too_many_inputs", codes(compile_(self.caps, "Лес", inputs).errors))

    def test_video_asset_as_input(self):
        got = compile_(self.caps, "Лес", [ref_in(A, kind="video")])
        self.assertIn("video_refs_unsupported", codes(got.errors))

    def test_duplicates_are_collapsed(self):
        got = compile_(self.caps, "@Image 1 и @Image 2", [ref_in(A, 0), ref_in(A, 1), ref_in(B, 2)])
        self.assertEqual(got.labels, {A: "Image 1", B: "Image 2"})
        self.assertEqual([(i["asset"], i["position"]) for i in got.inputs], [(A, 0), (B, 1)])
        two_firsts = compile_(self.caps, "Старт", [frame_in(F), C.ResolvedInput(asset(D), "first_frame", 1)])
        self.assertEqual(len(two_firsts.body["frame_images"]), 1)
        self.assertEqual(two_firsts.dropped, [{"asset": D, "slot": "first_frame", "reason": "duplicate_frame"}])

    def test_role_is_cleaned_and_limited(self):
        got = compile_(self.caps, "@Image 1 идёт", [ref_in(A, role="  героиня \n в  пальто ")])
        self.assertTrue(got.body["prompt"].startswith("[Image 1] is героиня в пальто.\n"))
        long = compile_(self.caps, "@Image 1 идёт", [ref_in(A, role="я" * 61)])
        self.assertEqual(find(long.errors, "invalid_param")["params"]["field"], "role")


@override_settings(VIDEO_GEN_DURATION=5, VIDEO_GEN_RESOLUTION="720p")
class OtherFamiliesTests(SimpleTestCase):
    def test_seedance_mini_references_off_until_probe(self):
        c = make_caps("bytedance/seedance-2.0-mini")
        got = compile_(c, "@Image 1 бежит", [ref_in(A)])
        err = find(got.errors, "refs_not_supported")
        self.assertEqual(err["fix"], {"action": "move_to_first_frame", "asset": A})
        self.assertEqual(err["fixes"][1], {"action": "exclude_inputs", "assets": [A]})
        self.assertEqual(err["message"], "Seedance 2.0 mini не умеет работать с фото-референсами. "
                                         "Сделайте фото первым кадром или выберите другую модель.")

    def test_veo_references_force_8s_and_natural_text(self):
        c = make_caps("google/veo-3.1-fast", {"refs_verified": "2026-10-01"})
        inputs = [ref_in(A, 0, "героиня"), ref_in(B, 1)]
        got = compile_(c, EXAMPLE, inputs, {"duration": 4, "resolution": "720p", "aspect_ratio": "9:16",
                                            "negative_prompt": "blur, text"})
        self.assertEqual(got.errors, [])
        self.assertEqual(got.body["duration"], 8)
        self.assertEqual(got.effective["duration"], 8)
        w = find(got.warnings, "duration_forced")
        self.assertEqual(w["params"], {"model": "Veo 3.1 Fast", "value": 8})
        # §4.6: у Veo нет индексов — роль словами, без роли «(the subject of reference image N)».
        self.assertEqual(got.body["prompt"],
                         "героиня (reference image 1) медленно идёт по старому двору "
                         "(the subject of reference image 2), камера плавно наезжает, тёплый закатный свет")
        # Негатив — только passthrough, верхнеуровневого negative_prompt нет.
        self.assertEqual(got.body["provider"],
                         {"options": {"google-vertex": {"parameters": {"negativePrompt": "blur, text"}}}})
        self.assertNotIn("negative_prompt", got.body)
        self.assertEqual(got.mode, "r2v")
        # Запрошенная длительность вне списка тоже заменяется, а не ошибка: её всё равно не будет.
        forced = compile_(c, EXAMPLE, inputs, {"duration": 5})
        self.assertEqual(forced.errors, [])
        self.assertEqual(forced.body["duration"], 8)

    def test_veo_frames_and_references_conflict(self):
        c = make_caps("google/veo-3.1-fast", {"refs_verified": "2026-10-01"})
        got = compile_(c, "@Image 1 бежит", [ref_in(A), frame_in(F)])
        err = find(got.errors, "frames_refs_conflict")
        self.assertEqual(err["fix"], {"action": "use_frames_only", "assets": [A]})
        self.assertEqual(err["fixes"], [{"action": "use_frames_only", "assets": [A]},
                                        {"action": "use_refs_only", "assets": [F]}])
        self.assertEqual(got.body, {})
        # Человек нажал «Оставить кадры»: референс выключен, но не удалён, чип в тексте остался.
        doc = pd.from_text("@Image 1 бежит", [ref_in(A)]).doc
        fixed = compile_(c, doc, [ref_in(A, included=False), frame_in(F)])
        self.assertEqual(fixed.errors, [])
        self.assertEqual(fixed.mode, "i2v")
        self.assertIn("frame_images", fixed.body)
        self.assertIn("input_excluded", codes(fixed.warnings))

    def test_veo_frames_only(self):
        c = make_caps("google/veo-3.1-fast")
        got = compile_(c, "От @Первый кадр к @Последний кадр", [frame_in(F), frame_in(L, "last_frame")],
                       {"duration": 6, "aspect_ratio": "16:9"})
        self.assertEqual(got.errors, [])
        self.assertEqual(got.body["prompt"], "От the starting frame к the ending frame")
        self.assertEqual(got.body["duration"], 6)
        # Референсы Veo без пробы выключены; кадры уже заняты — только «уберите референсы».
        blocked = compile_(c, "@Image 1", [ref_in(A), frame_in(F)])
        self.assertEqual(find(blocked.errors, "refs_not_supported")["fix"],
                         {"action": "exclude_inputs", "assets": [A]})

    def test_veo_aspect_21_9_invalid(self):
        c = make_caps("google/veo-3.1-fast")
        err = find(compile_(c, "Лес", params={"aspect_ratio": "21:9"}).errors, "invalid_param")
        self.assertEqual(err["params"]["allowed"], ["16:9", "9:16", "auto"])
        # 21:9 в тексте у Veo даже не предлагаем — модель так не снимает.
        self.assertNotIn("aspect_in_text", codes(compile_(c, "кинематографичный кадр").warnings))

    def test_kling_first_frame(self):
        c = make_caps("kwaivgi/kling-v3.0-std")
        got = compile_(c, "@Первый кадр: машина уезжает", [frame_in(F, w=1920, h=1080)],
                       {"duration": 5, "seed": 7, "negative_prompt": "blur"})
        self.assertEqual(got.errors, [])
        self.assertEqual(got.body["prompt"], "the first frame: машина уезжает")
        # seed Kling не умеет, slug негатива не подтверждён — ни то, ни другое не уходит.
        self.assertNotIn("seed", got.body)
        self.assertNotIn("provider", got.body)
        self.assertEqual(got.price_aspect, "16:9")
        # Язык «any» — подсказки про английский нет.
        self.assertNotIn("lang_hint", codes(got.warnings))

    def test_hailuo_23(self):
        c = make_caps("minimax/hailuo-2.3")
        got = compile_(c, "Закат", [frame_in(F), frame_in(L, "last_frame")])
        self.assertEqual(find(got.errors, "last_frame_not_supported")["fix"],
                         {"action": "exclude_inputs", "assets": [L]})
        t2v = compile_(c, "Закат", params={"generate_audio": True})
        self.assertNotIn("generate_audio", t2v.body)
        self.assertIsNone(t2v.effective["generate_audio"])
        self.assertEqual(t2v.body["resolution"], "1080p")
        self.assertEqual(t2v.body["duration"], 6)

    def test_grok_starting_image(self):
        c = make_caps("x-ai/grok-imagine-video")
        got = compile_(c, "@Первый кадр взлетает", [frame_in(F)])
        self.assertEqual(got.body["prompt"], "the starting image взлетает")
        self.assertNotIn("generate_audio", got.body)
        c = make_caps("x-ai/grok-imagine-video", {"refs_verified": "2026-10-01"})
        got = compile_(c, "@Image 1 и @Image 2", [ref_in(A, 0, "Анна"), ref_in(B, 1)])
        self.assertEqual(got.body["prompt"], "<IMAGE_1> is Анна.\n<IMAGE_1> и <IMAGE_2>")

    def test_hailuo3_after_probe(self):
        c = make_caps("minimax/hailuo-3", {"refs_verified": "2026-10-01"})
        inputs = [ref_in(A, 0, "героиня", label="Анна"), frame_in(F)]
        got = compile_(c, "@Image 1 идёт", inputs)
        self.assertEqual(got.mode, "r2v_pin")
        self.assertEqual(got.body["prompt"],
                         "Reference image 2 is the first frame of the video.\n"
                         "Reference image 1 is Анна (героиня).\nreference image 1 идёт")

    def test_wan_block(self):
        c = make_caps("alibaba/wan-2.7", {"refs_verified": "2026-10-01"})
        got = compile_(c, "@Image 1", [ref_in(A), frame_in(F)])
        self.assertIn("frames_refs_conflict", codes(got.errors))
        ok = compile_(c, "@Image 1 танцует", [ref_in(A, role="кот")])
        self.assertEqual(ok.body["prompt"], "Image 1 is кот.\nImage 1 танцует")


class ImageTests(SimpleTestCase):
    def test_nano_banana_references(self):
        c = image_caps("google/gemini-2.5-flash-image")
        got = compile_(c, "@Image 1 в кафе, стиль как @Image 2", [ref_in(A, 0, "героиня"), ref_in(B, 1)],
                       {"aspect_ratio": "9:16", "duration": 10})
        self.assertEqual(got.errors, [])
        self.assertEqual(got.mode, "i2i")
        self.assertEqual(got.body, {
            "model": "google/gemini-2.5-flash-image",
            "prompt": "Image 1: героиня.\nimage 1 в кафе, стиль как image 2",
            "aspect_ratio": "9:16",
            "input_references": [{"type": "image_url", "image_url": {"url": url(A)}},
                                 {"type": "image_url", "image_url": {"url": url(B)}}],
        })
        self.assertEqual(got.effective, {"aspect_ratio": "9:16"})
        self.assertEqual(got.price_aspect, "9:16")
        self.assertEqual(got.billable_images, 2)
        self.assertEqual(got.meter["soft_words"], None)

    def test_text_to_image(self):
        c = image_caps("black-forest-labs/flux.2-flex")
        got = compile_(c, "Кот в очках", params={"aspect_ratio": "auto"}, site_base="")
        self.assertEqual(got.errors, [])
        self.assertEqual(got.mode, "t2i")
        self.assertEqual(got.body, {"model": "black-forest-labs/flux.2-flex", "prompt": "Кот в очках"})
        self.assertIsNone(got.price_aspect)

    def test_limits(self):
        c = image_caps("google/gemini-2.5-flash-image")
        inputs = [ref_in(u, i) for i, u in enumerate((A, B, D, E))]
        err = find(compile_(c, "Все", inputs).errors, "too_many_refs")
        self.assertEqual((err["params"]["max"], err["params"]["n"]), (3, 4))
        self.assertEqual(err["fix"]["assets"], [E])
        self.assertIn("frames_not_supported", codes(compile_(c, "Кадр", [frame_in(F)]).errors))
        off = image_caps("google/gemini-2.5-flash-image", {"refs": "off"})
        self.assertIn("refs_not_supported", codes(compile_(off, "@Image 1", [ref_in(A)]).errors))
        self.assertIn("invalid_param", codes(compile_(c, "Кот", params={"aspect_ratio": "21:9"}).errors))


@override_settings(VIDEO_GEN_DURATION=5, VIDEO_GEN_RESOLUTION="720p")
class InvariantTests(SimpleTestCase):
    """Перебор семейств × наборов входов: свойства, которые не должны ломаться никогда."""

    def all_caps(self):
        out = []
        for model_id in SPECS:
            out.append(make_caps(model_id))
            fam = caps_mod.family_of(model_id)
            if fam.vendor_max_image_refs:
                out.append(make_caps(model_id, {"refs_verified": "2026-10-01"}))
        for model_id in ("google/gemini-2.5-flash-image", "black-forest-labs/flux.2-klein-4b"):
            out.append(image_caps(model_id))
        return out

    def combos(self):
        pieces = {
            "first": lambda: [frame_in(F)],
            "last": lambda: [frame_in(L, "last_frame")],
            "ref1": lambda: [ref_in(A, 0, "героиня")],
            "ref2": lambda: [ref_in(B, 1)],
            "off": lambda: [ref_in(D, 2, included=False)],
        }
        keys = list(pieces)
        for r in range(len(keys) + 1):
            for combo in itertools.combinations(keys, r):
                inputs = []
                for k in combo:
                    inputs += pieces[k]()
                yield combo, inputs

    def test_properties(self):
        text = "@Image 1 идёт к @Image 2, @Первый кадр и @Последний кадр вокруг, кинематографично"
        checked = 0
        for c in self.all_caps():
            for combo, inputs in self.combos():
                for params in ({}, {"aspect_ratio": "16:9"}, {"aspect_ratio": "auto", "duration": 8}):
                    got = compile_(c, text, inputs, params)
                    label = f"{c.model} refs={c.max_image_refs} {combo} {params}"
                    body = got.body
                    # 1. Кадры и референсы вместе — никогда.
                    self.assertFalse("frame_images" in body and "input_references" in body, label)
                    # 2. Ошибки → тело пустое; нет ошибок → тело полное.
                    if got.errors:
                        self.assertEqual(body, {}, label)
                    else:
                        self.assertEqual(body["model"], c.model, label)
                        self.assertEqual(body["prompt"], got.serialized_prompt, label)
                        sent = len(body.get("frame_images") or body.get("input_references") or [])
                        self.assertEqual(got.billable_images, sent, label)
                        # 3. Выключенное не уходит и не оплачивается.
                        self.assertNotIn(D, json.dumps(body), label)
                        # 4. Верхнеуровневого negative_prompt нет никогда.
                        self.assertNotIn("negative_prompt", body, label)
                        # 5. Скрытого 21:9 нет: без явного выбора пропорция не уходит.
                        if params.get("aspect_ratio") in (None, "auto"):
                            self.assertNotIn("aspect_ratio", body, label)
                        if c.kind == "video":
                            self.assertIn(body["duration"], c.durations, label)
                    # 6. Каждое сообщение — из таблицы §4.7 и полностью подставлено.
                    for item in got.errors + got.warnings:
                        self.assertIn(item["code"], C.MESSAGES, label)
                        self.assertIn(item["code"], C.BLOCKING if item in got.errors else C.WARNINGS, label)
                        self.assertTrue(item["message"], label)
                        self.assertNotRegex(item["message"], r"\{\w*\}", label)
                        json.dumps(item, ensure_ascii=False)
                    # 7. Текст не обрезается: человекочитаемая версия — весь документ.
                    self.assertTrue(got.prompt_text.endswith("кинематографично"), label)
                    checked += 1
        self.assertGreater(checked, 500)


class IssueTests(SimpleTestCase):
    def test_every_code_has_a_message(self):
        self.assertEqual(set(C.MESSAGES), C.BLOCKING | C.WARNINGS)
        self.assertFalse(C.BLOCKING & C.WARNINGS)
        params = {"model": "Seedance 2.0", "chars": 7000, "hard": 6000, "n": 2, "max": 3, "min": 300,
                  "soft": 150, "words": 480, "text": "@Image 9", "k": 3, "value": "21:9"}
        fmt = {"subject": "@Image 2", "lo_text": "2:5", "hi_text": "5:2", "field_text": "длительность",
               "value_text": "7", "allowed_text": "4, 6, 8", "current_text": "16:9"}
        for code in C.MESSAGES:
            got = C.issue(code, fmt=fmt, **params)
            self.assertNotRegex(got["message"], r"\{\w*\}", code)
            self.assertEqual(got["code"], code)
            self.assertNotIn("fix", got)

    def test_shape(self):
        got = C.issue("prompt_long", model="Veo", soft=120, words=300, fix={"action": "condense"})
        self.assertEqual(got, {"code": "prompt_long", "params": {"model": "Veo", "soft": 120, "words": 300},
                               "message": "Veo лучше всего понимает до ~120 слов, а у вас 300. Детали в конце "
                                          "могут потеряться — попробуйте «Сжать с ИИ».",
                               "fix": {"action": "condense"}})
        one = C.issue("frames_refs_conflict", model="Veo", fix={"action": "use_frames_only"},
                      fixes=[{"action": "use_frames_only"}])
        self.assertNotIn("fixes", one)

    def test_helpers(self):
        self.assertGreaterEqual(C.script_signs("Scene 1\nScene 2\n00:05 затем"), 3)
        self.assertEqual(C.script_signs("просто текст"), 0)
        self.assertGreater(C.cyrillic_share("Девушка идёт"), 0.9)
        self.assertEqual(C.cyrillic_share("123 !!!"), 0.0)
        self.assertTrue(re.fullmatch(r"\d+:\d+", C._ratio_text(0.4)))
