// Видеостудия: документ промпта и редактор без браузера.
//  - promptDoc.ts: грамматика тегов §4.3 (и сверка с сервером), from_text,
//    проверка документа, TipTap JSON ⇄ prompt_doc, prompt_text;
//  - labels.ts: нумерация @Image N по лотку, состояния чипов, выбор по «@»;
//  - editor/pasteRelink.ts, editor/vsRef.ts, editor/suggestion.ts — на
//    НАСТОЯЩЕЙ схеме редактора (getSchema из тех же расширений TipTap) и
//    настоящем EditorState: вставка, перепривязка при наборе, лимиты,
//    копирование «@Image N», метки ожидания загрузки, «@» для выбора.
// Запуск (Node 22.6+):  node --experimental-strip-types --test src/lib/vstudio/promptDoc.test.mjs
import "./nodeTsHooks.mjs";
import { test } from "node:test";
import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import { existsSync, readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";

const P = await import("./promptDoc.ts");
const L = await import("./labels.ts");
const R = await import("../../components/vstudio/editor/pasteRelink.ts");
const V = await import("../../components/vstudio/editor/vsRef.ts");
const SG = await import("../../components/vstudio/editor/suggestion.ts");
const core = await import("@tiptap/core");
const { default: Document } = await import("@tiptap/extension-document");
const { default: Paragraph } = await import("@tiptap/extension-paragraph");
const { default: Text } = await import("@tiptap/extension-text");
const { default: HardBreak } = await import("@tiptap/extension-hard-break");
const { EditorState, TextSelection } = await import("@tiptap/pm/state");
const { Slice, Fragment } = await import("@tiptap/pm/model");
const { findSuggestionMatch } = await import("@tiptap/suggestion");

const U = (n) => n.toString(16).padStart(32, "0");
const A = U(0xa1);
const B = U(0xb2);
const C = U(0xc3);
const D = U(0xd4);
const F = U(0xf1);
const G = U(0xf2);

const text = (v) => ({ t: "text", v });
const ref = (asset) => ({ t: "ref", asset });
const doc = (...blocks) => ({ v: 1, blocks });

/** Входы запроса: A, B(выключен), C, D — референсы по порядку лотка; F — первый кадр. */
const INPUTS = [
  { asset: A, slot: "reference", position: 0, included: true },
  { asset: B, slot: "reference", position: 1, included: false },
  { asset: C, slot: "reference", position: 2, included: true },
  { asset: D, slot: "reference", position: 3 },
  { asset: F, slot: "first_frame", position: 0, included: true },
];

/* ================================================================== */
/* Грамматика тегов §4.3                                              */
/* ================================================================== */

const SERVER_PY = fileURLToPath(new URL("../../../../core/vstudio/prompt_doc.py", import.meta.url));

/** Строки r"…" выражения NAME из prompt_doc.py, склеенные (как это делает питон). */
function pyPattern(src, name) {
  const at = src.indexOf(`${name} =`);
  if (at < 0) return null;
  const tail = src.slice(at);
  const end = tail.indexOf(",\n") >= 0 && name.endsWith("_RE") ? tail.indexOf(",\n") : tail.indexOf(")\n");
  const chunk = tail.slice(0, end + 1);
  return [...chunk.matchAll(/r"((?:[^"\\]|\\.)*)"/g)].map((m) => m[1]).join("");
}

test("выражение тегов буква в букву то же, что у сервера (TAG_RE, MEDIA_TAG_RE, FRAME_TAG_RE)", (t) => {
  if (!existsSync(SERVER_PY)) return t.skip("нет core/vstudio/prompt_doc.py рядом");
  const src = readFileSync(SERVER_PY, "utf8");
  assert.equal(P.TAG_PATTERN, pyPattern(src, "TAG_PATTERN"));
  assert.equal(P.MEDIA_TAG_PATTERN, pyPattern(src, "MEDIA_TAG_RE"));
  assert.equal(P.FRAME_TAG_PATTERN, pyPattern(src, "FRAME_TAG_RE"));
});

test("§4.3: все формы из спецификации распознаются", () => {
  const forms = [
    ["@Image 1", 1],
    ["@Image1", 1],
    ["@image_1", 1],
    ["[Image 1]", 1],
    ["<IMAGE_1>", 1],
    ["@Фото 2", 2],
    ["@фото2", 2],
    ["@изображение 3", 3],
    ["@Сүрөт 1", 1],
    ["@img 4", 4],
    ["@photo_2", 2],
    ["@картинка 1", 1],
    ["@ Image 1", 1],
    ["[ Image 2 ]", 2],
    ["@Image 1", 1],
    ["@Image 05", 5],
    ["@Image ١", 1],
  ];
  for (const [raw, n] of forms) {
    const tags = P.findTags(`идёт ${raw} дальше`);
    assert.equal(tags.length, 1, raw);
    assert.equal(tags[0].kind, "tag", raw);
    assert.equal(tags[0].n, n, raw);
    assert.equal(tags[0].raw.trim(), raw.trim(), raw);
  }
});

test("§4.3: голое «Image 1» и тег, прилипший к слову, — обычный текст", () => {
  for (const s of [
    "Image 1 walks",
    "mail@image1",
    "x[Image 1]",
    "_@Image 1",
    "1@Image 1",
    "é@Image 1",
    "ж@Image 1",
    "@Image  1",
    "@Imagery 1",
    "@Image",
  ]) {
    assert.deepEqual(P.findTags(s), [], s);
  }
  // Эмодзи — не буква: тег после него распознаётся (суррогатная пара — один символ).
  assert.equal(P.findTags("😀@Image 1").length, 1);
  // Два тега подряд: второй прилип к цифре первого — как у сервера, не тег.
  assert.deepEqual(P.findTags("@IMAGE_1@image_2").map((m) => m.raw), ["@IMAGE_1"]);
});

test("§4.3: скобка и хвост тега входят в тег, номер — не больше двух цифр", () => {
  assert.deepEqual(P.findTags("@Image 1] и <IMAGE_2").map((m) => m.raw), ["@Image 1]", "<IMAGE_2"]);
  const [m] = P.findTags("@Image 123");
  assert.equal(m.raw, "@Image 12");
  assert.equal(m.n, 12);
});

test("кадры: «@Первый кадр» / «@Last frame» — теги слотов, «@last frameX» — нет", () => {
  const tags = P.findTags("@Первый кадр, @последний кадр; @First frame @last frameX");
  assert.deepEqual(
    tags.map((m) => [m.kind, m.frame, m.raw]),
    [
      ["frame", "first_frame", "@Первый кадр"],
      ["frame", "last_frame", "@последний кадр"],
      ["frame", "first_frame", "@First frame"],
    ],
  );
});

test("«@Видео 1», «@audio2», «@звук 3» — отдельно: в Фазе 1 это ошибка", () => {
  assert.deepEqual(P.findMediaTags("@Видео 1 и @audio2, @звук 3, а@video1").map((m) => m.raw), [
    "@Видео 1",
    "@audio2",
    "@звук 3",
  ]);
});

/* ================================================================== */
/* Нумерация и fromText                                                */
/* ================================================================== */

test("§4.2: номер — позиция среди ВКЛЮЧЁННЫХ фото-референсов в порядке лотка", () => {
  assert.deepEqual(P.numberRefs(INPUTS), { [A]: 1, [C]: 2, [D]: 3 });
  // Порядок — по position, а не по порядку в массиве.
  const shuffled = [
    { asset: C, slot: "reference", position: 1 },
    { asset: A, slot: "reference", position: 0 },
  ];
  assert.deepEqual(P.numberRefs(shuffled), { [A]: 1, [C]: 2 });
  // Один uid дважды — один номер; видео в Image N не входит.
  const dup = [
    { asset: A, slot: "reference", position: 0 },
    { asset: A, slot: "reference", position: 1 },
    { asset: B, slot: "reference", position: 2, kind: "video" },
    { asset: C, slot: "reference", position: 3 },
  ];
  assert.deepEqual(P.numberRefs(dup), { [A]: 1, [C]: 2 });
  assert.deepEqual(P.frameUids(INPUTS), { first_frame: F });
  assert.deepEqual(P.frameUids([{ asset: F, slot: "last_frame", included: false }]), {});
});

test("fromText: теги → ссылки по номерам, неизвестные — текст и одно предупреждение на тег", () => {
  const r = P.fromText("@Image 1 идёт к [Image 2], потом <IMAGE_3> и @Image 9, снова @Image 9\n@Первый кадр — @Последний кадр", INPUTS);
  assert.deepEqual(r.doc, {
    v: 1,
    blocks: [
      [ref(A), text(" идёт к "), ref(C), text(", потом "), ref(D), text(" и @Image 9, снова @Image 9")],
      [ref(F), text(" — @Последний кадр")],
    ],
  });
  assert.deepEqual(
    r.warnings.map((w) => [w.code, w.params.text]),
    [
      ["tag_unknown", "@Image 9"],
      ["tag_unknown", "@Последний кадр"],
    ],
  );
  assert.equal(r.warnings[0].message, "«@Image 9» похоже на тег, но такого фото в запросе нет.");
  assert.deepEqual(r.errors, []);
});

test("fromText: «@Видео 1» — ошибка video_refs_unsupported, текст остаётся", () => {
  const r = P.fromText("@Видео 1 танцует", INPUTS);
  assert.deepEqual(r.errors.map((e) => e.code), ["video_refs_unsupported"]);
  assert.deepEqual(r.doc, doc([text("@Видео 1 танцует")]));
});

test("fromText: переводы строк Windows, управляющие символы, пустые строки", () => {
  const r = P.fromText("a\u0007b\r\n\r\n@Image 1\rc", INPUTS);
  assert.deepEqual(r.doc, doc([text("ab")], [], [ref(A)], [text("c")]));
  assert.deepEqual(P.fromText("", INPUTS).doc, doc([]));
});

test("fromText: больше 20 000 символов — PromptDocError (ничего не режем), 20 000 ровно — можно", () => {
  assert.throws(() => P.fromText("я".repeat(20001)), (e) => e instanceof P.PromptDocError && e.code === "prompt_doc_invalid");
  // Эмодзи — один символ, как len() у питона.
  assert.equal(P.fromText("😀".repeat(20000)).doc.blocks[0][0].v.length, 40000);
});

test("fromText: больше 200 строк — хвост в последнем абзаце с \\n, текст тот же", () => {
  const lines = Array.from({ length: 250 }, (_, i) => `строка ${i}`);
  const r = P.fromText(lines.join("\n"));
  assert.equal(r.doc.blocks.length, 200);
  assert.equal(P.plainText(r.doc), lines.join("\n"));
  assert.doesNotThrow(() => P.validateDoc(r.doc));
});

test("fromText: не больше 64 ссылок — лишние теги остаются текстом без предупреждений", () => {
  const r = P.fromText("@Image 1 ".repeat(70), INPUTS);
  assert.equal(P.refCount(r.doc), 64);
  assert.deepEqual(r.warnings, []);
  assert.ok(P.plainText(r.doc).includes("@Image 1"));
});

/* ------------------------------------------------------------------ */
/* Сверка с сервером: те же строки через core/vstudio/prompt_doc.py      */
/* ------------------------------------------------------------------ */

const PARITY_TEXTS = [
  "@Image 1 идёт по крыше @Image 2",
  "[Image 1] and <IMAGE_2>, @image_3 @img4 @photo 1",
  "@Фото 2 и @фото1 и @изображение 3 и @Сүрөт 1 и @картинка 2",
  "Image 1 bare and mail@image1 and x[Image 1] and _@Image 1 and 1@Image 1",
  "@Image 12 and @Image 123 and @Image  1 and @ Image 1 and [ Image 2 ] and @Image 0",
  "@Первый кадр и @последний кадр, @First frame; @last frameX",
  "@Видео 1 и @audio2 и @звук 3",
  "@IMAGE_1@image_2 <IMAGE_1 @Image 1] @image1_",
  "Сцена 1\n@Image 1 идёт\r\nдальше\n\n@Image 2\r",
  "@Image ١ 😀@Image 1 é@Image 1 ж@Image 1 @ Image 1 @Image 05",
  "a\u0007b\u0000 @Image 1 \u0085 @Image 2",
  "@Image 1 ".repeat(70),
  "",
];
const PARITY_INPUTS = [
  INPUTS,
  [],
  [
    { asset: C, slot: "reference", position: 1 },
    { asset: A, slot: "reference", position: 0 },
    { asset: G, slot: "last_frame", position: 0 },
  ],
  [
    { asset: A, slot: "reference", position: 0 },
    { asset: A, slot: "reference", position: 1 },
    { asset: B, slot: "reference", position: 2, kind: "video" },
    { asset: C, slot: "reference", position: 3, included: false },
    { asset: F, slot: "first_frame", position: 0, included: false },
  ],
];

const PY_SCRIPT = String.raw`
import json, sys
sys.path.insert(0, ".")
from vstudio import prompt_doc as pd
cases = json.loads(sys.stdin.read())
out = []
for c in cases:
    inputs = c["inputs"]
    try:
        r = pd.from_text(c["text"], inputs)
    except pd.PromptDocError as e:
        out.append({"error": e.code})
        continue
    labels = {uid: "Image %d" % n for uid, n in pd.number_refs(inputs).items()}
    labels.update({uid: slot for slot, uid in pd.frame_uids(inputs).items()})
    out.append({"doc": r.doc, "warnings": r.warnings, "errors": r.errors,
                "numbers": pd.number_refs(inputs), "frames": pd.frame_uids(inputs),
                "text": pd.render_text(r.doc, labels), "plain": pd.plain_text(r.doc), "refs": pd.ref_uids(r.doc)})
sys.stdout.write(json.dumps(out, ensure_ascii=False))
`;

function runServer(cases) {
  const coreDir = fileURLToPath(new URL("../../../../core/", import.meta.url));
  if (!existsSync(coreDir)) return { skip: "нет каталога core/" };
  for (const exe of [process.env.PYTHON, "python", "python3", "py"].filter(Boolean)) {
    const res = spawnSync(exe, ["-c", PY_SCRIPT], {
      cwd: coreDir,
      input: JSON.stringify(cases),
      encoding: "utf8",
      env: { ...process.env, PYTHONIOENCODING: "utf-8", PYTHONUTF8: "1" },
      timeout: 60000,
    });
    if (res.error || res.status !== 0) {
      if (res.stderr && /ImportError|ModuleNotFoundError/.test(res.stderr)) return { skip: `питон без зависимостей сервера (${exe})` };
      continue;
    }
    return { out: JSON.parse(res.stdout) };
  }
  return { skip: "питон не найден" };
}

test("сверка с сервером: from_text, number_refs, render_text дают то же самое", (t) => {
  const cases = [];
  for (const inputs of PARITY_INPUTS) for (const s of PARITY_TEXTS) cases.push({ text: s, inputs });
  cases.push({ text: "я".repeat(20001), inputs: INPUTS });
  const server = runServer(cases);
  if (server.skip) return t.skip(server.skip);
  assert.equal(server.out.length, cases.length);
  cases.forEach((c, i) => {
    const want = server.out[i];
    const label = `#${i}: ${JSON.stringify(c.text.slice(0, 60))}`;
    if (want.error) {
      assert.throws(() => P.fromText(c.text, c.inputs), (e) => e.code === want.error, label);
      return;
    }
    const got = P.fromText(c.text, c.inputs);
    assert.deepEqual(got.doc, want.doc, label);
    assert.deepEqual(got.warnings, want.warnings, label);
    assert.deepEqual(got.errors, want.errors, label);
    assert.deepEqual(P.numberRefs(c.inputs), want.numbers, label);
    assert.deepEqual(P.frameUids(c.inputs), want.frames, label);
    const labels = Object.fromEntries(Object.entries(want.numbers).map(([uid, n]) => [uid, `Image ${n}`]));
    for (const [slot, uid] of Object.entries(want.frames)) labels[uid] = slot;
    assert.equal(P.renderText(got.doc, labels), want.text, label);
    assert.equal(P.plainText(got.doc), want.plain, label);
    assert.deepEqual(P.refUids(got.doc), want.refs, label);
  });
});

/* ------------------------------------------------------------------ */
/* Теги, оставшиеся текстом в документе (compiler → link_tags)          */
/* ------------------------------------------------------------------ */

test("linkDocTags: тег текстом в документе → ссылка, без фото — tag_unknown, «@Видео» — ошибка", () => {
  const r = P.linkDocTags(doc([text("Кошка в стиле @Image 1")], [ref(C), text(" и @Image 9, @Видео 1")]), INPUTS);
  assert.deepEqual(r.doc, doc([text("Кошка в стиле "), ref(A)], [ref(C), text(" и @Image 9, @Видео 1")]));
  assert.deepEqual(r.warnings.map((w) => [w.code, w.params.text]), [["tag_unknown", "@Image 9"]]);
  assert.deepEqual(r.errors.map((e) => e.code), ["video_refs_unsupported"]);
  // Перенос строки внутри абзаца — граница тега, как между строками в fromText.
  assert.deepEqual(P.linkDocTags(doc([text("@\nImage 1 и @Image 2")]), INPUTS).doc,
    doc([text("@\nImage 1 и "), ref(C)]));
  // Нечего привязывать — документ тот же.
  const same = doc([text("просто текст "), ref(A)]);
  assert.deepEqual(P.linkDocTags(same, INPUTS).doc, same);
});

const PY_LINK_SCRIPT = String.raw`
import json, sys
sys.path.insert(0, ".")
from vstudio import prompt_doc as pd
cases = json.loads(sys.stdin.read())
out = []
for c in cases:
    r = pd.link_tags(pd.validate(c["doc"]), c["inputs"])
    out.append({"doc": r.doc, "warnings": r.warnings, "errors": r.errors})
sys.stdout.write(json.dumps(out, ensure_ascii=False))
`;

test("сверка с сервером: linkDocTags = prompt_doc.link_tags", (t) => {
  const docs = [
    doc([text("Кошка в стиле @Image 1")]),
    doc([text("@Image 1 и "), ref(D), text(" [Image 2] @Image 7 @Image 7")], [text("@Первый кадр\n@Видео 2")]),
    doc([text("@\nImage 1 и @image_2")], []),
    doc([text("@Image 1 ".repeat(70))]),
  ];
  const cases = [];
  for (const inputs of PARITY_INPUTS) for (const d of docs) cases.push({ doc: d, inputs });
  const coreDir = fileURLToPath(new URL("../../../../core/", import.meta.url));
  if (!existsSync(coreDir)) return t.skip("нет каталога core/");
  let out = null;
  for (const exe of [process.env.PYTHON, "python", "python3", "py"].filter(Boolean)) {
    const res = spawnSync(exe, ["-c", PY_LINK_SCRIPT], {
      cwd: coreDir,
      input: JSON.stringify(cases),
      encoding: "utf8",
      env: { ...process.env, PYTHONIOENCODING: "utf-8", PYTHONUTF8: "1" },
      timeout: 60000,
    });
    if (res.error || res.status !== 0) {
      if (res.stderr && /ImportError|ModuleNotFoundError/.test(res.stderr)) return t.skip(`питон без зависимостей (${exe})`);
      continue;
    }
    out = JSON.parse(res.stdout);
    break;
  }
  if (!out) return t.skip("питон не найден");
  cases.forEach((c, i) => {
    const got = P.linkDocTags(c.doc, c.inputs);
    const label = `#${i}`;
    assert.deepEqual(got.doc, out[i].doc, label);
    assert.deepEqual(got.warnings, out[i].warnings, label);
    assert.deepEqual(got.errors, out[i].errors, label);
  });
});

/* ================================================================== */
/* Проверка документа (§4.1)                                          */
/* ================================================================== */

test("validateDoc: белый список и пределы как у сервера", () => {
  const ok = doc([text("Девушка "), ref(A), text(" идёт")], [text("Камера")]);
  assert.deepEqual(P.validateDoc(ok), ok);
  const bad = [
    null,
    [],
    { v: 1 },
    { v: 2, blocks: [] },
    { v: 1, blocks: [], extra: 1 },
    { v: 1, blocks: {} },
    doc({}),
    doc([{ t: "text", v: "a", x: 1 }]),
    doc([{ t: "text", v: 1 }]),
    doc([{ t: "text", v: "a\u0001" }]),
    doc([{ t: "ref", asset: "A".repeat(32) }]),
    doc([{ t: "ref", asset: A, label: "Image 1" }]),
    doc([{ t: "image", v: "x" }]),
    { v: 1, blocks: Array.from({ length: 201 }, () => []) },
    doc(Array.from({ length: 401 }, () => text("a"))),
    doc([text("я".repeat(20001))]),
    doc(Array.from({ length: 65 }, () => ref(A))),
  ];
  for (const d of bad) assert.throws(() => P.validateDoc(d), P.PromptDocError, JSON.stringify(d)?.slice(0, 80));
  assert.equal(P.isValidDoc(doc([text("\tтаб\nперенос")])), true);
  // Метка никогда не хранится в документе (§4.2): узел ref — только {t, asset}.
  assert.equal(P.isValidDoc(doc([{ t: "ref", asset: A, n: 1 }])), false);
});

test("sanitizeDoc: чинит без потерь текста — склейка, управляющие, плохие uid, пустой документ", () => {
  const messy = {
    v: 1,
    blocks: [[text("a"), text("b\r\nc"), { t: "ref", asset: "zzz" }, ref(A), text(""), { junk: 1 }], "not a block"],
  };
  assert.deepEqual(P.sanitizeDoc(messy), doc([text("ab\nc"), ref(A)], []));
  assert.deepEqual(P.sanitizeDoc(null), doc([]));
  assert.equal(P.docKey(doc([text("a"), text("b")])), P.docKey(doc([text("ab")])));
  assert.notEqual(P.docKey(doc([text("ab")])), P.docKey(doc([text("a")], [text("b")])));
});

test("чтение документа: refUids, refCount, plainText, docTextLength, isEmptyDoc", () => {
  const d = doc([ref(A), text(" и "), ref(C), text(" и "), ref(A)], [text("😀\n")]);
  assert.deepEqual(P.refUids(d), [A, C]);
  assert.equal(P.refCount(d), 3);
  assert.equal(P.plainText(d), " и  и \n😀\n");
  assert.equal(P.docTextLength(d), 8);
  assert.equal(P.isEmptyDoc(doc([text("  ")], [])), true);
  assert.equal(P.isEmptyDoc(doc([ref(A)])), false);
});

test("renderText (prompt_text): «@Image N», кадры словами, без метки — «@Image —»", () => {
  const d = doc([ref(A), text(" идёт по двору "), ref(C)], [ref(F), text(" и "), ref(B)]);
  const labels = { [A]: "Image 1", [C]: "Image 2", [F]: "first_frame" };
  assert.equal(P.renderText(d, labels), "@Image 1 идёт по двору @Image 2\n@Первый кадр и @Image —");
  assert.equal(P.labelTag("last_frame"), "@Последний кадр");
  assert.equal(P.labelTag(null), "@Image —");
});

/* ================================================================== */
/* TipTap JSON ⇄ prompt_doc                                            */
/* ================================================================== */

test("prompt_doc → TipTap: абзац на блок, \\n → hardBreak, ref → vsRef", () => {
  const d = doc([text("a\nb"), ref(A), text("\n")], [], [text("c")]);
  assert.deepEqual(P.docToTiptap(d), {
    type: "doc",
    content: [
      {
        type: "paragraph",
        content: [
          { type: "text", text: "a" },
          { type: "hardBreak" },
          { type: "text", text: "b" },
          { type: "vsRef", attrs: { asset: A } },
          { type: "hardBreak" },
        ],
      },
      { type: "paragraph" },
      { type: "paragraph", content: [{ type: "text", text: "c" }] },
    ],
  });
});

test("TipTap → prompt_doc: обратно тот же документ; незнакомый узел отдаёт свой текст", () => {
  const d = doc([text("a\nb"), ref(A), text("\n")], [], [text("c")]);
  assert.deepEqual(P.tiptapToDoc(P.docToTiptap(d)), d);
  const odd = {
    type: "doc",
    content: [
      { type: "paragraph", content: [{ type: "mention", content: [{ type: "text", text: "@x" }] }, { type: "vsRef", attrs: { asset: "bad" } }] },
    ],
  };
  assert.deepEqual(P.tiptapToDoc(odd), doc([text("@x")]));
  assert.deepEqual(P.tiptapToDoc(null), doc([]));
  assert.deepEqual(P.tiptapToDoc({ type: "doc", content: [] }), doc([]));
});

/* ================================================================== */
/* Схема редактора — из тех же расширений, что в TipTapEditor.tsx       */
/* ================================================================== */

function makeSchema(labels = {}) {
  const store = new V.RefStore(labels);
  const schema = core.getSchema([Document, Paragraph, Text, HardBreak, V.VsRef.configure({ store })]);
  return { schema, store };
}

const pmDoc = (schema, d) => schema.nodeFromJSON(P.docToTiptap(d));

test("схема: prompt_doc → ProseMirror → prompt_doc без потерь (чипы, переносы, пустые абзацы)", () => {
  const { schema } = makeSchema();
  const d = doc([text("Девушка "), ref(A), text(" идёт\nпо крыше "), ref(A)], [], [ref(F)]);
  const node = pmDoc(schema, d);
  assert.equal(node.child(0).childCount, 6);
  assert.equal(node.child(0).child(1).type.name, "vsRef");
  assert.equal(node.child(0).child(1).isAtom, true);
  assert.equal(node.child(0).child(1).isInline, true);
  assert.deepEqual(P.tiptapToDoc(node.toJSON()), d);
});

/* ------------------------------------------------------------------ */
/* Метки (labels.ts)                                                    */
/* ------------------------------------------------------------------ */

const item = (lid, assetUid, over = {}) => ({
  lid,
  assetUid,
  slot: "reference",
  role: "",
  included: true,
  status: "ready",
  progress: 100,
  preview: null,
  ...over,
});
const noFrames = { first_frame: null, last_frame: null };

test("labels: @Image N по лотку, выключенный — «—», загружающийся без uid — не в счёт", () => {
  const tray = [
    item("l1", A, { role: "героиня" }),
    item("l2", B, { included: false }),
    item("l3", undefined, { status: "uploading", progress: 40 }),
    item("l4", C, { status: "pending" }),
    item("l5", D, { status: "deleted" }),
  ];
  const labels = L.buildRefLabels({ tray, frames: { first_frame: item("f1", F, { slot: "first_frame" }), last_frame: null } });
  assert.deepEqual(Object.keys(labels).sort(), [A, B, C, D, F].sort());
  assert.deepEqual(labels[A], { text: "@Image 1", n: 1, slot: "reference", state: "ok", aria: "Фото 1 · героиня" });
  assert.equal(labels[B].text, "@Image —");
  assert.equal(labels[B].n, null);
  assert.equal(labels[B].state, "excluded");
  assert.equal(labels[B].aria, "Фото · Не учитывается и не оплачивается");
  assert.equal(labels[C].text, "@Image 2");
  assert.equal(labels[C].state, "pending");
  assert.equal(labels[D].state, "deleted");
  assert.equal(labels[D].n, 3);
  assert.equal(labels[F].text, "@Первый кадр");
  assert.equal(labels[F].slot, "first_frame");
  // То же правило, что у сервера: номера лотка = number_refs входов запроса.
  assert.deepEqual(L.trayRefNumbers(tray), P.numberRefs(L.trayInputs({ tray, frames: noFrames })));
  assert.deepEqual(L.trayNumbers(tray), { l1: 1, l2: null, l3: null, l4: 2, l5: 3 });
});

test("labels: перестановка в лотке меняет номера, документ тот же — чипы перерисовываются", () => {
  const d = doc([ref(A), text(" идёт к "), ref(C)]);
  const before = L.buildRefLabels({ tray: [item("l1", A), item("l2", C)], frames: noFrames });
  const after = L.buildRefLabels({ tray: [item("l2", C), item("l1", A)], frames: noFrames });
  assert.equal(P.renderText(d, L.serverLabels(before)), "@Image 1 идёт к @Image 2");
  assert.equal(P.renderText(d, L.serverLabels(after)), "@Image 2 идёт к @Image 1");
  // Выключили первое — второе стало первым.
  const off = L.buildRefLabels({ tray: [item("l1", A, { included: false }), item("l2", C)], frames: noFrames });
  assert.equal(P.renderText(d, L.serverLabels(off)), "@Image — идёт к @Image 1");
});

test("labels: копирование чипа как prompt_text сервера; выключенный кадр — «@Image —»", () => {
  const frames = { first_frame: item("f1", F, { slot: "first_frame" }), last_frame: item("f2", G, { slot: "last_frame", included: false }) };
  const labels = L.buildRefLabels({ tray: [item("l1", A)], frames });
  assert.equal(L.copyTagFor(labels[A]), "@Image 1");
  assert.equal(L.copyTagFor(labels[F]), "@Первый кадр");
  assert.equal(L.copyTagFor(labels[G]), "@Image —");
  assert.equal(L.copyTagFor(undefined), "@Image —");
  assert.equal(L.copyTagFor(L.missingLabel()), "@Image —");
  assert.deepEqual(L.serverLabels(labels), { [A]: "Image 1", [F]: "first_frame" });
  // Перепривязка текста ведёт туда же, куда нумерует сервер.
  const idx = L.indexFromLabels(labels);
  assert.equal(idx.byNumber.get(1), A);
  assert.equal(idx.frames.first_frame, F);
  assert.equal(idx.frames.last_frame, undefined);
});

test("labels: один uid и в лотке (выключен), и кадром — побеждает включённый", () => {
  const labels = L.buildRefLabels({
    tray: [item("l1", F, { included: false })],
    frames: { first_frame: item("f1", F, { slot: "first_frame" }), last_frame: null },
  });
  assert.equal(labels[F].slot, "first_frame");
  assert.equal(labels[F].state, "ok");
});

test("labels: подсказки переводятся через t, метка @Image N — нет", () => {
  const t = (key, opts) => (key === "tray.image" ? `Photo ${opts.n}` : key === "tray.excluded" ? "Not used" : opts.defaultValue);
  const labels = L.buildRefLabels({ tray: [item("l1", A, { role: "hero" }), item("l2", B, { included: false })], frames: noFrames }, t);
  assert.equal(labels[A].text, "@Image 1");
  assert.equal(labels[A].aria, "Photo 1 · hero");
  assert.equal(labels[B].aria, "Фото · Not used");
});

test("выбор по «@»: сначала «В этом запросе» по порядку, потом «Мои материалы» без повторов", () => {
  const tray = [item("l1", A, { role: "героиня" }), item("l2", C)];
  const frames = { first_frame: item("f1", F, { slot: "first_frame" }), last_frame: null };
  const labels = L.buildRefLabels({ tray, frames });
  const lib = [
    { uid: C, kind: "image", status: "ready", thumb_url: "/c.jpg", url: "/c.jpg" },
    { uid: D, kind: "image", status: "ready", thumb_url: "/d.jpg", url: "/d.jpg" },
    { uid: G, kind: "image", status: "failed", thumb_url: null, url: null },
    { uid: B, kind: "video", status: "ready", thumb_url: null, url: "/b.mp4" },
  ];
  const items = L.pickerItemsFrom({ tray, frames, library: lib }, labels);
  assert.deepEqual(
    items.map((i) => [i.section, i.asset, i.label]),
    [
      ["in_request", A, "@Image 1"],
      ["in_request", C, "@Image 2"],
      ["in_request", F, "@Первый кадр"],
      ["library", D, ""],
    ],
  );
  const pick = (q) => L.filterPickerItems(items, labels, q).map((i) => i.asset);
  assert.deepEqual(pick(""), [A, C, F, D]);
  assert.deepEqual(pick("@im"), [A, C, D]);
  assert.deepEqual(pick("фо"), [A, C, D]);
  assert.deepEqual(pick("2"), [C]);
  assert.deepEqual(pick("image1"), [A]);
  assert.deepEqual(pick("Image 1"), [A]);
  assert.deepEqual(pick("герои"), [A]);
  assert.deepEqual(pick("кадр"), [F]);
  assert.deepEqual(pick("zzz"), []);
});

/* ------------------------------------------------------------------ */
/* Копирование: clipboardTextSerializer → «@Image N»                    */
/* ------------------------------------------------------------------ */

test("копирование: чипы → «@Image N» / «@Первый кадр», абзацы через \\n; вставка обратно — те же чипы", () => {
  const tray = [item("l1", A), item("l2", C)];
  const frames = { first_frame: item("f1", F, { slot: "first_frame" }), last_frame: null };
  const labels = L.buildRefLabels({ tray, frames });
  const { schema } = makeSchema(labels);
  const d = doc([ref(C), text(" идёт к "), ref(A), text("\nи дальше")], [ref(F), text(" крупно")]);
  const node = pmDoc(schema, d);
  const copied = core.getTextBetween(
    node,
    { from: 0, to: node.content.size },
    { blockSeparator: "\n", textSerializers: core.getTextSerializersFromSchema(schema) },
  );
  assert.equal(copied, "@Image 2 идёт к @Image 1\nи дальше\n@Первый кадр крупно");
  // Ровно то, что сервер показал бы как prompt_text.
  assert.equal(copied, P.renderText(d, L.serverLabels(labels)));
  // Вставка этого текста в тот же запрос даёт те же чипы и тот же текст
  // (перенос внутри абзаца станет абзацем — как from_text у сервера:
  // в обычном тексте их не различить, а собранный промпт тот же).
  const { slice, refs } = R.sliceFromText(schema, copied, L.indexFromLabels(labels));
  assert.equal(refs, 3);
  const pasted = P.tiptapToDoc(schema.nodes.doc.create(null, slice.content).toJSON());
  assert.deepEqual(pasted, P.fromText(copied, L.inputsFromLabels(labels)).doc);
  assert.deepEqual(P.refUids(pasted), [C, A, F]);
  assert.equal(P.renderText(pasted, L.serverLabels(labels)), copied);
  const flat = doc([ref(C), text(" идёт к "), ref(A)], [ref(F), text(" крупно")]);
  const again = R.sliceFromText(schema, P.renderText(flat, L.serverLabels(labels)), L.indexFromLabels(labels));
  assert.deepEqual(P.tiptapToDoc(schema.nodes.doc.create(null, again.slice.content).toJSON()), flat);
});

test("HTML чипа несёт uid и подпись — для вставки в тот же или другой запрос", () => {
  const labels = L.buildRefLabels({ tray: [item("l1", A)], frames: noFrames });
  const { schema } = makeSchema(labels);
  const spec = schema.nodes.vsRef.spec.toDOM(schema.nodes.vsRef.create({ asset: A }));
  assert.equal(spec[0], "span");
  assert.equal(spec[1]["data-vs-ref"], A);
  assert.equal(spec[1]["data-vs-tag"], "@Image 1");
  assert.equal(spec[2], "@Image 1");
});

/* ------------------------------------------------------------------ */
/* Вставка текста (pasteRelink)                                         */
/* ------------------------------------------------------------------ */

test("вставка текста из ChatGPT: теги → чипы, строки → абзацы, неизвестный тег — текст", () => {
  const { schema } = makeSchema();
  const idx = P.tagIndex(INPUTS);
  const { slice, refs } = R.sliceFromText(schema, "Сцена: [Image 1] встречает <IMAGE_3>\r\nФон — @Image 7", idx);
  assert.equal(refs, 2);
  const pasted = schema.nodes.doc.create(null, slice.content);
  assert.deepEqual(
    P.tiptapToDoc(pasted.toJSON()),
    doc([text("Сцена: "), ref(A), text(" встречает "), ref(D)], [text("Фон — @Image 7")]),
  );
  // Длиннее 20 000 — срез без разбора (лимит потом не даст его вставить), ничего не падает.
  const long = R.sliceFromText(schema, "a".repeat(20001) + " @Image 1", idx);
  assert.equal(long.refs, 0);
  assert.equal(R.countContent(long.slice.content).chars, 20010);
});

test("перепривязка HTML-среза: свой чип остаётся, чужой (другой проект) — по подписи на этот запрос", () => {
  const { schema } = makeSchema();
  const idx = P.tagIndex(INPUTS);
  const known = (uid) => uid === A;
  const foreign = U(0x999);
  const para = schema.nodes.paragraph.create(null, [
    schema.nodes.vsRef.create({ asset: A }),
    schema.text(" и "),
    schema.nodes.vsRef.create({ asset: foreign, tag: "@Image 2" }),
    schema.text(", фон [Image 3]"),
  ]);
  const out = R.relinkSlice(new Slice(Fragment.from(para), 1, 1), schema, idx, known);
  const d = P.tiptapToDoc(schema.nodes.doc.create(null, out.content).toJSON());
  assert.deepEqual(d, doc([ref(A), text(" и "), ref(C), text(", фон "), ref(D)]));
  // Плоский срез (кусок из середины абзаца) — тоже.
  const flat = R.relinkSlice(new Slice(Fragment.from(schema.text("и @Image 1")), 0, 0), schema, idx, known);
  assert.equal(flat.content.childCount, 2);
  assert.equal(flat.content.child(1).attrs.asset, A);
});

/* ------------------------------------------------------------------ */
/* Перепривязка при наборе и лимиты — на EditorState с плагинами        */
/* ------------------------------------------------------------------ */

function makeState(d, { labels = {}, index = P.tagIndex(INPUTS), max = 20000, onLimit } = {}) {
  const { schema } = makeSchema(labels);
  const ctx = { index, max };
  const state = EditorState.create({
    schema,
    doc: pmDoc(schema, d),
    plugins: [
      R.relinkPlugin({ getIndex: () => ctx.index }),
      R.limitPlugin({ getMax: () => ctx.max, onLimit }),
      R.pendingPlugin(),
    ],
  });
  return { state, schema, ctx };
}

const docOf = (state) => P.tiptapToDoc(state.doc.toJSON());

/** Напечатать строку в позиции курсора, как пользователь: транзакция на символ. */
function type(state, s) {
  let st = state;
  for (const ch of s) st = st.apply(st.tr.insertText(ch));
  return st;
}

test("набор: «@Image 1» становится чипом, только когда тег дописан (пробел, запятая, скобка)", () => {
  let { state } = makeState(doc([]));
  state = state.apply(state.tr.setSelection(TextSelection.create(state.doc, 1)));
  state = type(state, "идёт @Image 1");
  // Курсор сразу за тегом: человек может допечатать «2» — не трогаем.
  assert.deepEqual(docOf(state), doc([text("идёт @Image 1")]));
  state = type(state, " по крыше");
  assert.deepEqual(docOf(state), doc([text("идёт "), ref(A), text(" по крыше")]));
  // Закрывающая скобка дописывает тег сразу.
  state = type(state, " [Image 2]");
  assert.deepEqual(docOf(state), doc([text("идёт "), ref(A), text(" по крыше "), ref(C)]));
  // Номера нет в лотке — остаётся текстом.
  state = type(state, " @Image 9 ");
  assert.deepEqual(docOf(state), doc([text("идёт "), ref(A), text(" по крыше "), ref(C), text(" @Image 9 ")]));
});

test("«Создать» с курсором сразу за тегом: finishTags делает его чипом (не шаг истории)", () => {
  const made = makeState(doc([]));
  const ctx = made.ctx;
  let state = made.state.apply(made.state.tr.setSelection(TextSelection.create(made.state.doc, 1)));
  state = type(state, "Кошка в стиле @Image 1");
  assert.deepEqual(docOf(state), doc([text("Кошка в стиле @Image 1")]));
  assert.equal(R.relinkTransaction(state, ctx.index), null);
  const view = {
    isDestroyed: false,
    composing: false,
    state,
    dispatched: [],
    dispatch(tr) {
      this.dispatched.push(tr);
      this.state = this.state.apply(tr);
    },
  };
  assert.equal(R.finishTags(view, ctx.index), true);
  assert.deepEqual(docOf(view.state), doc([text("Кошка в стиле "), ref(A)]));
  assert.equal(view.dispatched[0].getMeta("addToHistory"), false);
  // Второй раз менять нечего; во время композиции IME документ не трогаем.
  assert.equal(R.finishTags(view, ctx.index), false);
  const composing = { ...view, composing: true, state };
  assert.equal(R.finishTags(composing, ctx.index), false);
});

test("набор: «@Image 1» → «@Image 12» — ждём конца числа, ведём на 12-е фото", () => {
  const many = Array.from({ length: 12 }, (_, i) => ({ asset: U(0x100 + i), slot: "reference", position: i }));
  let { state } = makeState(doc([]), { index: P.tagIndex(many) });
  state = state.apply(state.tr.setSelection(TextSelection.create(state.doc, 1)));
  state = type(state, "@Image 12 ");
  assert.deepEqual(docOf(state), doc([ref(U(0x100 + 11)), text(" ")]));
});

test("набор: undo/redo и вставка не перепривязываются автоматически", () => {
  let { state } = makeState(doc([]));
  const tr = state.tr.insertText("@Image 1 ", 1).setMeta("uiEvent", "paste");
  state = state.apply(tr);
  assert.deepEqual(docOf(state), doc([text("@Image 1 ")]));
  const hist = state.tr.insertText("x", state.doc.content.size - 1).setMeta("history$", { redo: false });
  state = state.apply(hist);
  assert.deepEqual(docOf(state), doc([text("@Image 1 x")]));
});

test("смена лотка (force): теги-текст по всему документу получают фото, не шаг истории", () => {
  const { state: s0, ctx } = makeState(doc([text("@Image 1 и @Image 2")], [text("[Image 5]")]), { index: P.tagIndex([]) });
  let state = s0;
  assert.equal(R.relinkTransaction(state, ctx.index), null);
  ctx.index = P.tagIndex(INPUTS);
  const tr = state.tr.setMeta(R.relinkKey, { force: true }).setMeta("addToHistory", false);
  const res = state.applyTransaction(tr);
  state = res.state;
  assert.deepEqual(docOf(state), doc([ref(A), text(" и "), ref(C)], [text("[Image 5]")]));
  const appended = res.transactions[1];
  assert.equal(appended.getMeta("addToHistory"), false);
});

test("подчёркивание: тег без фото и «@Видео 1» размечены, набираемый тег (курсор в нём) — нет", () => {
  const { state } = makeState(doc([text("@Image 9 и @Видео 1 и @Image 1")]));
  const marks = (st) => R.relinkKey.getState(st).deco.find().map((d) => [d.from, d.to, d.type.attrs["data-vs-issue"]]);
  // Курсор в начале абзаца (перед «@») — тег не набирается, размечаем.
  assert.deepEqual(marks(state), [
    [1, 9, "tag_unknown"],
    [12, 20, "video_refs_unsupported"],
  ]);
  assert.match(
    R.relinkKey.getState(state).deco.find()[0].type.attrs.class,
    /vs-tag-issue/,
  );
  // Курсор сразу за «@Image 9»: человек, может быть, ещё печатает номер.
  const typing = state.apply(state.tr.setSelection(TextSelection.create(state.doc, 9)));
  assert.deepEqual(marks(typing), [[12, 20, "video_refs_unsupported"]]);
});

test("лимит 20 000: лишнее не вставляется и не обрезается молча, стирать можно всегда", () => {
  const events = [];
  let { state } = makeState(doc([text("a".repeat(9))]), { max: 10, onLimit: (k) => events.push(k) });
  state = state.apply(state.tr.insertText("b", 10));
  assert.equal(R.countContent(state.doc).chars, 10);
  const same = state.apply(state.tr.insertText("cc", 11));
  assert.equal(same, state, "транзакция сверх лимита отклонена целиком");
  assert.deepEqual(events, ["chars"]);
  // Перенос строки (hardBreak) — тоже символ, как «\n» у сервера.
  const br = state.apply(state.tr.insert(11, state.schema.nodes.hardBreak.create()));
  assert.equal(br, state);
  // Документ извне длиннее лимита — его можно сокращать.
  const { state: big } = makeState(doc([text("a".repeat(15))]), { max: 10 });
  const shorter = big.apply(big.tr.delete(1, 3));
  assert.equal(R.countContent(shorter.doc).chars, 13);
  // Абзацы между собой не считаются (сервер соединяет их «\n» только при сборке).
  const counted = doc([text("ab")], [text("c\nd"), ref(A)]);
  assert.deepEqual(R.countContent(pmDoc(state.schema, counted)), { chars: 5, refs: 1 });
  assert.equal(R.countContent(pmDoc(state.schema, counted)).chars, P.docTextLength(counted));
});

test("лимит 64 упоминаний: 65-й чип не встаёт", () => {
  const events = [];
  const d = doc(Array.from({ length: 64 }, () => ref(A)));
  const { state } = makeState(d, { onLimit: (k) => events.push(k) });
  const next = state.apply(state.tr.insert(1, state.schema.nodes.vsRef.create({ asset: C })));
  assert.equal(next, state);
  assert.deepEqual(events, ["refs"]);
  assert.equal(R.refInsertTransaction(state, 1, 1, [C]), null);
});

test("sliceFits: вставка вместо выделения считается честно", () => {
  const { state: s0, schema } = makeState(doc([text("abcdefgh")]), { max: 10 });
  const slice = (s) => R.sliceFromText(schema, s, P.tagIndex([])).slice;
  let state = s0.apply(s0.tr.setSelection(TextSelection.create(s0.doc, 9)));
  assert.equal(R.sliceFits(state, slice("12"), 10), null);
  assert.equal(R.sliceFits(state, slice("123"), 10), "chars");
  // Выделили 3 символа — теперь 5 помещается.
  state = state.apply(state.tr.setSelection(TextSelection.create(state.doc, 1, 4)));
  assert.equal(R.sliceFits(state, slice("12345"), 10), null);
});

/* ------------------------------------------------------------------ */
/* Вставка чипа в позицию курсора                                       */
/* ------------------------------------------------------------------ */

test("чип в позиции курсора: пробелы по краям, чтобы не слипся со словом", () => {
  const { state } = makeState(doc([text("идёт по, дальше")]));
  const at = (pos, uids = [A]) => docOf(state.apply(R.refInsertTransaction(state, pos, pos, uids)));
  // После слова и перед запятой: пробел перед чипом, после — нет.
  assert.deepEqual(at(8), doc([text("идёт по "), ref(A), text(", дальше")]));
  // В начале абзаца — пробел только после.
  assert.deepEqual(at(1), doc([ref(A), text(" идёт по, дальше")]));
  // В конце — пробел после, чтобы продолжать печатать.
  assert.deepEqual(at(16), doc([text("идёт по, дальше "), ref(A), text(" ")]));
  // Несколько чипов — через пробел.
  assert.deepEqual(at(16, [A, C]), doc([text("идёт по, дальше "), ref(A), text(" "), ref(C), text(" ")]));
  // После открывающей скобки пробел не нужен.
  const { state: s2 } = makeState(doc([text("(")]));
  assert.deepEqual(docOf(s2.apply(R.refInsertTransaction(s2, 2, 2, [A]))), doc([text("("), ref(A), text(" ")]));
  // Выделено всё — заменяется одним абзацем с чипом.
  const { state: s3 } = makeState(doc([text("a")], [text("b")]));
  assert.deepEqual(docOf(s3.apply(R.refInsertTransaction(s3, 0, s3.doc.content.size, [A]))), doc([ref(A), text(" ")]));
  // Мусорный uid не вставляется.
  assert.equal(R.refInsertTransaction(state, 1, 1, ["nope"]), null);
});

/* ------------------------------------------------------------------ */
/* Метки ожидания: файл вставлен — чип появится ровно там               */
/* ------------------------------------------------------------------ */

function fakeView(state) {
  return {
    state,
    isDestroyed: false,
    dispatch(tr) {
      this.state = this.state.apply(tr);
    },
  };
}

test("метка ожидания едет вместе с текстом; напечатанное в той же точке — после будущего чипа", () => {
  const { state } = makeState(doc([text("идёт по крыше")]));
  const view = fakeView(state);
  const id = R.addPending(view, 6, "Загрузка…");
  // Пока грузится, человек печатает перед меткой и в самой точке метки.
  view.dispatch(view.state.tr.insertText("Кот ", 1));
  view.dispatch(view.state.tr.insertText("быстро ", 10));
  const pos = R.takePending(view, id);
  assert.equal(pos, 10);
  view.dispatch(R.refInsertTransaction(view.state, pos, pos, [A]));
  assert.deepEqual(docOf(view.state), doc([text("Кот идёт "), ref(A), text(" быстро по крыше")]));
  // Второй раз метки уже нет.
  assert.equal(R.takePending(view, id), null);
});

/* ------------------------------------------------------------------ */
/* «@» — выбор материалов                                               */
/* ------------------------------------------------------------------ */

function suggestAt(state, pos) {
  return findSuggestionMatch({
    char: "@",
    allowSpaces: false,
    allowToIncludeChar: false,
    allowedPrefixes: SG.ALLOWED_PREFIXES,
    startOfLine: false,
    $position: state.doc.resolve(pos),
  });
}

test("«@» открывает выбор после пробела, скобки, в начале строки и после переноса; «mail@» — нет", () => {
  const { state, schema } = makeState(doc([text("идёт @фо")], [text("(@")], [text("mail@x")], [text("@im")]));
  const m1 = suggestAt(state, 9);
  assert.equal(m1.query, "фо");
  assert.deepEqual(m1.range, { from: 6, to: 9 });
  assert.equal(suggestAt(state, 13).query, "");
  assert.equal(suggestAt(state, 21), null);
  assert.equal(suggestAt(state, 26).query, "im");
  // После Shift+Enter (hardBreak) и после чипа «@» тоже открывает выбор.
  const d2 = schema.nodes.doc.create(null, [
    schema.nodes.paragraph.create(null, [schema.text("a"), schema.nodes.hardBreak.create(), schema.text("@x")]),
  ]);
  const st2 = EditorState.create({ schema, doc: d2 });
  assert.equal(suggestAt(st2, 5).query, "x");
});

test("кнопка «@ Материалы»: пробел перед «@» только после слова или чипа", () => {
  const { state } = makeState(doc([text("идёт")], [], [ref(A)]));
  assert.equal(SG.needsSpaceBefore(state, 5), true);
  assert.equal(SG.needsSpaceBefore(state, 1), false);
  assert.equal(SG.needsSpaceBefore(state, 7), false);
  assert.equal(SG.needsSpaceBefore(state, 10), true);
  const view = { ...fakeView(state), editable: true, focus() {} };
  const s1 = state.apply(state.tr.setSelection(TextSelection.create(state.doc, 5)));
  view.state = s1;
  const range = SG.openAt(view);
  assert.deepEqual(range, { from: 5, to: 7 });
  assert.equal(view.state.doc.child(0).textContent, "идёт @");
});

test("запасная textarea: «@запрос» перед кареткой по тем же правилам", () => {
  assert.deepEqual(SG.atBeforeCaret("идёт @фо", 8), { query: "фо", from: 5 });
  assert.deepEqual(SG.atBeforeCaret("@", 1), { query: "", from: 0 });
  assert.deepEqual(SG.atBeforeCaret("a\n@im", 5), { query: "im", from: 2 });
  assert.deepEqual(SG.atBeforeCaret("«@x", 3), { query: "x", from: 1 });
  assert.equal(SG.atBeforeCaret("mail@x", 6), null);
  assert.equal(SG.atBeforeCaret("@фо бар", 7), null);
  assert.equal(SG.atBeforeCaret("идёт @фо", 5), null);
});

/* ------------------------------------------------------------------ */
/* Хранилище меток чипов                                                */
/* ------------------------------------------------------------------ */

test("RefStore: известная метка, «создаётся» сразу после вставки, потом — красная «нет в запросе»", () => {
  const labels = L.buildRefLabels({ tray: [item("l1", A)], frames: noFrames });
  const store = new V.RefStore(labels);
  assert.equal(store.label(A).text, "@Image 1");
  assert.equal(store.label(C).state, "missing");
  store.expect([C], 60000);
  assert.equal(store.label(C).state, "pending");
  assert.equal(store.copyText(C), "@Image —");
  let refreshed = 0;
  store.add({ refresh: () => refreshed++ });
  store.setLabels(L.buildRefLabels({ tray: [item("l2", C), item("l1", A)], frames: noFrames }));
  assert.equal(refreshed, 1);
  assert.equal(store.label(C).text, "@Image 1");
  assert.equal(store.label(A).text, "@Image 2");
  store.dispose();
});

/* ------------------------------------------------------------------ */
/* Лёгкость куска страницы: TipTap только в ленивом куске               */
/* ------------------------------------------------------------------ */

const SRC_DIR = fileURLToPath(new URL("../../", import.meta.url));

/** Файл по спецификатору импорта (./x, ../x, @/x) — как резолвит Next; null — пакет. */
function resolveSpec(spec, fromFile) {
  let base;
  if (spec.startsWith("@/")) base = SRC_DIR + spec.slice(2);
  else if (spec.startsWith("./") || spec.startsWith("../")) base = fileURLToPath(new URL(spec, "file:///" + fromFile.replace(/\\/g, "/")));
  else return null;
  for (const ext of ["", ".ts", ".tsx", "/index.ts", "/index.tsx"]) {
    if (existsSync(base + ext) && /\.(ts|tsx)$/.test(base + ext)) return base + ext;
  }
  throw new Error(`не нашёлся ${spec} из ${fromFile}`);
}

/** Все пакеты, которые модуль тянет СТАТИЧЕСКИ (import … from / export … from; type-импорты и import() — нет). */
function staticPackages(entry) {
  const seen = new Set();
  const packages = new Map();
  const walk = (file) => {
    if (seen.has(file)) return;
    seen.add(file);
    const src = readFileSync(file, "utf8").replace(/\/\*[\s\S]*?\*\//g, "").replace(/^\s*\/\/.*$/gm, "");
    const re = /^\s*(?:import|export)\s+(type\s+)?(?:[^"';]*?\sfrom\s+)?["']([^"']+)["']/gm;
    let m;
    while ((m = re.exec(src)) !== null) {
      if (m[1]) continue; // import type — стирается при сборке
      const spec = m[2];
      const local = resolveSpec(spec, file);
      if (local) walk(local);
      else if (!packages.has(spec)) packages.set(spec, file.slice(SRC_DIR.length));
    }
  };
  walk(entry);
  return packages;
}

test("кусок страницы без TipTap: PromptEditor, textarea, список «@», чип вне редактора", () => {
  const editorDir = SRC_DIR + "components/vstudio/editor/";
  for (const entry of ["PromptEditor.tsx", "TextareaFallback.tsx", "MentionPicker.tsx", "RefChip.tsx", "EditorFrame.tsx"]) {
    const pk = staticPackages(editorDir + entry);
    const heavy = [...pk.entries()].filter(([spec]) => /^@tiptap\/|^prosemirror-/.test(spec));
    assert.deepEqual(heavy, [], `${entry} тянет редактор статически: ${JSON.stringify(heavy)}`);
  }
  // А сам редактор — тянет (иначе проверка выше ничего не стоит).
  assert.ok([...staticPackages(editorDir + "TipTapEditor.tsx").keys()].some((s) => s.startsWith("@tiptap/")));
  // PromptEditor грузит TipTapEditor только через import().
  const pe = readFileSync(editorDir + "PromptEditor.tsx", "utf8");
  assert.match(pe, /import\("\.\/TipTapEditor"\)/);
  assert.match(pe, /ssr:\s*false/);
});

test("класс чипа: у каждого состояния свой вид, акцент — только у готового", () => {
  for (const s of ["ok", "pending", "failed", "excluded", "deleted", "missing"]) {
    assert.ok(V.chipClassName(s).includes("vs-chip"), s);
  }
  assert.ok(V.chipClassName("ok").includes("text-accent"));
  assert.ok(!V.chipClassName("excluded").includes("accent"));
  assert.ok(V.chipClassName("missing").includes("status-fail"));
  assert.ok(V.chipClassName("ok", true).includes("ring-accent"));
});
