"""Документ промпта (vstudio/prompt_doc.py, спецификация §4.1–4.3)."""
import copy

from django.test import SimpleTestCase

from vstudio import prompt_doc as pd

A = "a" * 32
B = "b" * 32
C = "c" * 32
F = "f" * 32
L = "e" * 32


def txt(v):
    return {"t": "text", "v": v}


def ref(uid):
    return {"t": "ref", "asset": uid}


def doc(*blocks):
    return {"v": 1, "blocks": [list(b) for b in blocks]}


def inp(uid, slot="reference", position=0, included=True, kind="image"):
    return {"asset": uid, "slot": slot, "position": position, "included": included, "kind": kind}


class ValidateTests(SimpleTestCase):
    def test_valid_doc_is_copied_clean(self):
        d = doc([txt("Девушка "), ref(A), txt(" идёт\tпо крыше\nи смотрит")], [txt("Камера отъезжает")])
        got = pd.validate(d)
        self.assertEqual(got, d)
        self.assertIsNot(got, d)
        self.assertTrue(pd.is_valid(d))
        self.assertTrue(pd.is_valid(pd.empty_doc()))
        self.assertTrue(pd.is_valid({"v": 1, "blocks": []}))

    def assertInvalid(self, d):
        with self.assertRaises(pd.PromptDocError) as ctx:
            pd.validate(d)
        self.assertEqual(ctx.exception.code, "prompt_doc_invalid")
        self.assertIn("Обновите страницу", ctx.exception.message)

    def test_shape_violations(self):
        good = doc([txt("x"), ref(A)])
        self.assertInvalid(None)
        self.assertInvalid([])
        self.assertInvalid({"v": 2, "blocks": []})
        self.assertInvalid({"v": True, "blocks": []})  # True == 1, но это не версия
        self.assertInvalid({"v": "1", "blocks": []})
        self.assertInvalid({"blocks": []})
        self.assertInvalid(dict(good, extra=1))
        self.assertInvalid({"v": 1, "blocks": "text"})
        self.assertInvalid({"v": 1, "blocks": ["text"]})
        self.assertInvalid(doc(["text"]))
        self.assertInvalid(doc([{"t": "html", "v": "<b>"}]))
        self.assertInvalid(doc([{"t": "text", "v": "x", "role": "героиня"}]))
        self.assertInvalid(doc([{"t": "text", "v": 5}]))
        self.assertInvalid(doc([{"t": "ref", "asset": A, "label": "Image 1"}]))
        self.assertInvalid(doc([{"t": "ref", "asset": A.upper()}]))
        self.assertInvalid(doc([{"t": "ref", "asset": "a" * 31}]))
        self.assertInvalid(doc([{"t": "ref", "asset": "../../etc/passwd" + "a" * 16}]))
        self.assertInvalid(doc([{"t": "ref"}]))

    def test_control_characters(self):
        for bad in ("\x00", "\x07", "\r", "\x1b[31m", "\x7f", "\x85"):
            self.assertInvalid(doc([txt(f"a{bad}b")]))
        pd.validate(doc([txt("строка\nещё\tтаб")]))

    def test_limits(self):
        self.assertTrue(pd.is_valid({"v": 1, "blocks": [[txt("x")]] * 200}))
        self.assertInvalid({"v": 1, "blocks": [[txt("x")]] * 201})
        self.assertTrue(pd.is_valid(doc([txt("x")] * 400)))
        self.assertInvalid(doc([txt("x")] * 401))
        self.assertTrue(pd.is_valid(doc([txt("я" * 20_000)])))
        self.assertInvalid(doc([txt("я" * 10_000)], [txt("я" * 10_001)]))
        self.assertTrue(pd.is_valid(doc([ref(A)] * 64)))
        self.assertInvalid(doc([ref(A)] * 65))


class RenderTests(SimpleTestCase):
    def test_labels(self):
        d = doc([ref(A), txt(" и "), ref(B), txt(" с "), ref(F), txt(" до "), ref(L)], [txt("конец "), ref(C)])
        labels = {A: "Image 1", B: "Image 2", F: "first_frame", L: "last_frame"}
        self.assertEqual(pd.render_text(d, labels),
                         "@Image 1 и @Image 2 с @Первый кадр до @Последний кадр\nконец @Image —")

    def test_helpers(self):
        d = doc([txt("a "), ref(B), txt(" b "), ref(A)], [ref(B), txt("c")])
        self.assertEqual(pd.ref_uids(d), [B, A])
        self.assertEqual(pd.plain_text(d), "a  b \nc")
        self.assertEqual(pd.serialize(d, lambda uid: uid[:1].upper()), "a B b A\nBc")


class NumberingTests(SimpleTestCase):
    def test_numbers_follow_tray_order_of_included_images(self):
        inputs = [inp(C, position=2), inp(A, position=0), inp(B, position=1, included=False),
                  inp(F, slot="first_frame"), inp("d" * 32, position=3, kind="video")]
        self.assertEqual(pd.number_refs(inputs), {A: 1, C: 2})
        # Перестановка в лотке — номера меняются.
        inputs[0]["position"], inputs[1]["position"] = 0, 2
        self.assertEqual(pd.number_refs(inputs), {C: 1, A: 2})

    def test_frames(self):
        inputs = [inp(F, slot="first_frame", position=1), inp(A, slot="first_frame", position=0, included=False),
                  inp(L, slot="last_frame")]
        self.assertEqual(pd.frame_uids(inputs), {"first_frame": F, "last_frame": L})


class FromTextTests(SimpleTestCase):
    INPUTS = [inp(A, position=0), inp(B, position=1), inp(C, position=2)]

    def refs_of(self, text, inputs=None):
        got = pd.from_text(text, self.INPUTS if inputs is None else inputs)
        return got, pd.ref_uids(got.doc)

    def test_recognized_forms(self):
        for text in ("@Image 1", "@Image1", "@image_1", "[Image 1]", "<IMAGE_1>", "@Фото 1", "@фото1",
                     "@изображение 1", "@Сүрөт 1", "@img 1", "@Photo 1", "[ image 1 ]", "@картинка 1"):
            got, uids = self.refs_of(f"девушка {text} идёт")
            self.assertEqual(uids, [A], text)
            self.assertEqual(got.warnings, [], text)
            self.assertEqual(got.doc["blocks"][0][0], txt("девушка "), text)
            self.assertEqual(got.doc["blocks"][0][-1], txt(" идёт"), text)

    def test_bare_words_are_plain_text(self):
        # Голое «Image 1» — обычный английский текст, его не трогаем.
        for text in ("Image 1 is a cat", "photo 2 of the city", "email@image1.com", "фото 1"):
            got, uids = self.refs_of(text)
            self.assertEqual(uids, [], text)
            self.assertEqual(got.warnings, [], text)
            self.assertEqual(pd.plain_text(got.doc), text)

    def test_unknown_number_stays_text_with_warning(self):
        got, uids = self.refs_of("@Image 1 и @Image 7 и снова @Image 7")
        self.assertEqual(uids, [A])
        self.assertEqual(pd.plain_text(got.doc), " и @Image 7 и снова @Image 7")
        self.assertEqual([w["code"] for w in got.warnings], ["tag_unknown"])
        self.assertEqual(got.warnings[0]["params"], {"text": "@Image 7"})
        self.assertIn("@Image 7", got.warnings[0]["message"])

    def test_excluded_reference_has_no_number(self):
        inputs = [inp(A, position=0, included=False), inp(B, position=1)]
        got, uids = self.refs_of("@Image 1 и @Image 2", inputs)
        self.assertEqual(uids, [B])
        self.assertEqual([w["code"] for w in got.warnings], ["tag_unknown"])

    def test_video_and_audio_tags_are_an_error(self):
        for text in ("@Видео 1 как пример", "@video1", "@Audio 2", "@звук 1"):
            got = pd.from_text(text, self.INPUTS)
            self.assertEqual([e["code"] for e in got.errors], ["video_refs_unsupported"], text)

    def test_frame_chips_round_trip(self):
        inputs = self.INPUTS + [inp(F, slot="first_frame"), inp(L, slot="last_frame")]
        got, uids = self.refs_of("От @Первый кадр к @Последний кадр, как @Image 2", inputs)
        self.assertEqual(uids, [F, L, B])
        # Кадра нет — тег остаётся текстом с предупреждением.
        got, uids = self.refs_of("От @Первый кадр")
        self.assertEqual(uids, [])
        self.assertEqual([w["code"] for w in got.warnings], ["tag_unknown"])

    def test_chatgpt_paste(self):
        # Так промпт приходит из ChatGPT: markdown, скобочные теги, CRLF, разные формы тегов.
        text = ("**Scene:** A woman ([Image 1]) walks through the old courtyard <IMAGE_2>.\r\n"
                "\r\n"
                "- Camera: slow dolly-in, @image3 in the background\r\n"
                "- Light: warm sunset; the dog from @Фото 2 follows her.\r\n"
                "Note: Image 1 must keep the red coat.")
        got, uids = self.refs_of(text)
        self.assertEqual(uids, [A, B, C])
        self.assertEqual(got.warnings, [])
        self.assertEqual(len(got.doc["blocks"]), 5)
        labels = {A: "Image 1", B: "Image 2", C: "Image 3"}
        self.assertEqual(pd.render_text(got.doc, labels),
                         "**Scene:** A woman (@Image 1) walks through the old courtyard @Image 2.\n"
                         "\n"
                         "- Camera: slow dolly-in, @Image 3 in the background\n"
                         "- Light: warm sunset; the dog from @Image 2 follows her.\n"
                         "Note: Image 1 must keep the red coat.")
        pd.validate(got.doc)

    def test_round_trip_of_rendered_text(self):
        labels = {A: "Image 1", B: "Image 2", C: "Image 3"}
        text = "@Image 1 идёт по двору @Image 2\n\nкамера: @Image 3, @Image 1 снова"
        got = pd.from_text(text, self.INPUTS)
        self.assertEqual(pd.render_text(got.doc, labels), text)

    def test_control_chars_and_long_texts(self):
        got = pd.from_text("a\x00b\x1b[1mc\rd", self.INPUTS)
        self.assertEqual(pd.plain_text(got.doc), "ab[1mc\nd")
        pd.validate(got.doc)
        # 300 строк — больше 200 блоков: хвост уходит в последний абзац, текст тот же.
        text = "\n".join(f"строка {i} @Image 1" for i in range(300))
        got = pd.from_text(text, self.INPUTS)
        self.assertEqual(len(got.doc["blocks"]), 200)
        pd.validate(got.doc)
        self.assertEqual(pd.render_text(got.doc, {A: "Image 1"}), text)
        with self.assertRaises(pd.PromptDocError):
            pd.from_text("я" * 20_001, self.INPUTS)

    def test_empty_text(self):
        got = pd.from_text("", ())
        self.assertEqual(got.doc, {"v": 1, "blocks": [[]]})
        pd.validate(got.doc)

    def test_input_shapes(self):
        # Годятся и словари, и ResolvedInput компилятора.
        from vstudio.compiler import AssetView, ResolvedInput

        inputs = [ResolvedInput(AssetView(uid=B), "reference", 1), ResolvedInput(AssetView(uid=A), "reference", 0)]
        got = pd.from_text("@Image 2 и @Image 1", inputs)
        self.assertEqual(pd.ref_uids(got.doc), [B, A])

    def test_does_not_mutate_inputs(self):
        inputs = copy.deepcopy(self.INPUTS)
        pd.from_text("@Image 1", inputs)
        self.assertEqual(inputs, self.INPUTS)

    def test_tag_regex_matches_spec(self):
        # Одно выражение с фронтом: lib/vstudio/promptDoc.ts копирует эту строку.
        self.assertEqual(
            pd.TAG_PATTERN,
            r"(?<![\w])(?:@\s?|\[\s*|<\s*)(image|img|photo|фото|изображение|картинка|сүрөт)"
            r"[\s_]?(\d{1,2})(?:\s*[\]>])?")
