// «Голос сцены» склейки: ключи фрагментов (mergeLogic) и чистые функции голоса сцены (audioLogic).
// Запуск (Node 22.6+):  node --experimental-strip-types --test src/components/merge/*.test.mjs
import "../../lib/vstudio/nodeTsHooks.mjs";
import { test } from "node:test";
import assert from "node:assert/strict";

const m = await import("./mergeLogic.ts");
const a = await import("./audioLogic.ts");
const { MERGE_ERROR_RU } = await import("./mergeText.ts");

const item = (id, extra = {}) => ({
  type: "vstudio",
  id: String(id),
  title: `Ролик ${id}`,
  subtitle: "",
  poster: null,
  url: `/media/${id}.mp4`,
  duration_s: 5,
  width: 1280,
  height: 720,
  available: true,
  ...extra,
});

const line = (extra = {}) => ({
  id: "a".repeat(32),
  kind: "line",
  source: "generated",
  status: "ready",
  url: "/media/l.mp3",
  duration_s: 2,
  text: "Привет",
  prompt: "",
  title: "",
  voice_id: "v1",
  voice_name: "Rachel",
  start_fragment: null,
  start_fragment_effective: null,
  seconds: null,
  credits_reserved: 0,
  credits_charged: 5,
  error: "",
  error_code: null,
  request_id: null,
  created_at: null,
  expires_at: null,
  fragment_key: "abcdef012345",
  fragment_index: 0,
  fragment_duration_s: 5,
  max_start_s: 4.9,
  start_s: 0,
  volume: 1,
  orphan: false,
  overflow: false,
  ...extra,
});

test("ключ фрагмента: серверный вид, новый ключ — 12 hex", () => {
  assert.equal(m.isFragmentKey("abcdef01"), true);
  assert.equal(m.isFragmentKey("ABCDEF01"), false);
  assert.equal(m.isFragmentKey("f1"), false);
  assert.equal(m.isFragmentKey(null), false);
  assert.equal(m.isFragmentKey("a".repeat(33)), false);
  const k = m.newFragmentKey();
  assert.match(k, /^[0-9a-f]{12}$/);
  assert.notEqual(m.newFragmentKey(), k);
  // Без crypto — из rand.
  const saved = globalThis.crypto;
  try {
    Object.defineProperty(globalThis, "crypto", { value: undefined, configurable: true });
    assert.equal(m.newFragmentKey(() => 0.5), "888888888888");
  } finally {
    Object.defineProperty(globalThis, "crypto", { value: saved, configurable: true });
  }
});

test("toLocal берёт ключ сервера, без него — прежнее правило", () => {
  let n = 0;
  const make = () => `k${++n}`;
  const local = m.toLocal([item(1, { key: "abcdef012345" }), item(2)], [], make);
  assert.deepEqual(local.map((i) => i.key), ["abcdef012345", "k1"]);
  // Переставили на сервере — ключи едут за роликами.
  const swapped = m.toLocal([item(2, { key: "111111111111" }), item(1, { key: "abcdef012345" })], local, make);
  assert.deepEqual(swapped.map((i) => i.key), ["111111111111", "abcdef012345"]);
  // Негодный ключ сервера — как будто его нет.
  const bad = m.toLocal([item(1, { key: "XYZ" })], local, make);
  assert.equal(bad[0].key, "abcdef012345");
});

test("itemBody: ключ уходит только в серверном виде", () => {
  assert.deepEqual(m.itemBody([item(1, { key: "abcdef012345" }), item(2, { key: "f2" }), item(3)]), [
    { type: "vstudio", id: "1", key: "abcdef012345" },
    { type: "vstudio", id: "2" },
    { type: "vstudio", id: "3" },
  ]);
});

test("signature: ключи различают только одинаковые ролики", () => {
  const one = [item(1, { key: "aaaaaaaa" }), item(2, { key: "bbbbbbbb" })];
  assert.equal(m.signature(one, "16:9", "pad"), "16:9|pad|vstudio:1,vstudio:2");
  const twice = [item(1, { key: "aaaaaaaa" }), item(1, { key: "bbbbbbbb" })];
  const swapped = [twice[1], twice[0]];
  assert.notEqual(m.signature(twice, "16:9", "pad"), m.signature(swapped, "16:9", "pad"));
  assert.equal(m.signature(twice, "16:9", "pad"), "16:9|pad|vstudio:1#aaaaaaaa,vstudio:1#bbbbbbbb");
});

test("lineMaxStart и clampStart — то же правило, что у сервера", () => {
  for (const [d, want] of [[5, 4.9], [5.04, 5], [4.04, 4], [0.1, 0], [0.05, 0], [0, 0], [null, 0], [7, 6.9], [6.999, 6.9]]) {
    assert.equal(a.lineMaxStart(d), want, `длина ${d}`);
  }
  assert.equal(a.clampStart(4.96, 5), 4.9);
  assert.equal(a.clampStart(-1, 5), 0);
  assert.equal(a.clampStart(1.25, 5), 1.3);
  assert.equal(a.clampStart(Number.NaN, 5), 0);
  assert.equal(a.roundSecond(2.44), 2.4);
  assert.equal(a.formatSecond(2.5), "2,5");
  assert.equal(a.formatSecond(0), "0,0");
  assert.equal(a.formatSecond(2.5, "kg"), "2,5");
  assert.equal(a.formatSecond(2.5, "en"), "2.5");
  assert.equal(a.formatSecond(4.96, "en"), "5.0");
});

test("голоса фрагмента, предел, «потерявшие» ролик", () => {
  const lines = [
    line({ id: "1".repeat(32), start_s: 3 }),
    line({ id: "2".repeat(32), start_s: 1 }),
    line({ id: "3".repeat(32), status: "failed" }),
    line({ id: "4".repeat(32), fragment_key: "bbbbbbbbbbbb" }),
    line({ id: "5".repeat(32), orphan: true, fragment_key: "cccccccccccc", fragment_index: null }),
  ];
  assert.deepEqual(a.linesOf(lines, "abcdef012345").map((l) => l.start_s), [0, 1, 3]);
  assert.deepEqual(a.linesOf(lines, null), []);
  assert.equal(a.liveLineCount(lines, "abcdef012345"), 2, "неудачные не считаются");
  assert.equal(a.liveLineCount(lines), 4);
  assert.deepEqual(a.orphanLines(lines).map((l) => l.fragment_key), ["cccccccccccc"]);
  assert.deepEqual(a.lineMarks(a.linesOf(lines, "abcdef012345"), 5), [0.2, 0.6]);
  assert.deepEqual(a.lineMarks([line({ start_s: 9 })], 5), [1]);
  assert.deepEqual(a.lineMarks([line()], null), []);
});

test("markOrphans — «потерявшие» ролик по ленте на экране", () => {
  const here = line({ id: "1".repeat(32), fragment_key: "aaaaaaaaaaaa" });
  const gone = line({ id: "2".repeat(32), fragment_key: "bbbbbbbbbbbb" });
  const back = line({ id: "3".repeat(32), fragment_key: "cccccccccccc", orphan: true });
  const out = a.markOrphans([here, gone, back], ["aaaaaaaaaaaa", "cccccccccccc"]);
  assert.deepEqual(out.map((l) => l.orphan), [false, true, false]);
  assert.equal(out[0], here, "не изменившаяся строка — тот же объект");
  assert.deepEqual(a.linesOf(out, "cccccccccccc").map((l) => l.id), ["3".repeat(32)], "ролик вернули — голос снова у него");
  assert.deepEqual(a.orphanLines(out).map((l) => l.id), ["2".repeat(32)]);
  assert.deepEqual(a.markOrphans(null, []), []);
});

test("заход на следующую сцену", () => {
  assert.equal(a.lineOverflowS(4, 2, 5), 1);
  assert.equal(a.lineOverflowS(3, 2, 5), 0);
  assert.equal(a.lineOverflowS(3.04, 2, 5), 0, "до 0,05 с — не заход");
  assert.equal(a.lineOverflowS(1, null, 5), 0);
});

test("lineRefusal — тексты сервера", () => {
  const opts = { chars: 500, count: 0, perFragment: 3, total: 0, max: 40 };
  assert.equal(a.lineRefusal("  ", "v1", opts).key, "merge.err.audio_text_empty");
  const long = a.lineRefusal("а".repeat(501), "v1", opts);
  assert.deepEqual([long.key, long.params.max], ["merge.err.voice_too_long", 500]);
  assert.equal(a.lineRefusal("Привет", "", opts).key, "merge.err.audio_voice_id");
  const full = a.lineRefusal("Привет", "v1", { ...opts, count: 3 });
  assert.deepEqual([full.key, full.params.max], ["merge.err.line_fragment_full", 3]);
  assert.equal(full.ru, MERGE_ERROR_RU.line_fragment_full);
  assert.equal(a.lineRefusal("Привет", "v1", { ...opts, total: 40 }).key, "merge.err.lines_limit");
  assert.equal(a.lineRefusal("Привет", "v1", opts), null);
});

test("lineSignature: тот же заказ — тот же слепок", () => {
  const s = a.lineSignature("abcdef012345", " Привет  мир ", "v1", 1.24, 1);
  assert.equal(s, a.lineSignature("abcdef012345", "Привет мир", "v1", 1.2, 1));
  assert.notEqual(s, a.lineSignature("abcdef012345", "Привет мир", "v1", 1.3, 1));
  assert.notEqual(s, a.lineSignature("bbbbbbbbbbbb", "Привет мир", "v1", 1.2, 1));
});

test("отказы полей голоса сцены — свои тексты", () => {
  const err = (data, message = "") => ({ code: "bad_request", status: 400, message, data });
  assert.equal(a.audioErrorText(err({ field: "fragment_key" })).key, "merge.err.audio_fragment_key");
  assert.equal(a.audioErrorText(err({ field: "start_s" })).key, "merge.err.audio_start_s");
  const max = a.audioErrorText(err({ field: "start_s", max_start_s: 4.9, fragment_duration_s: 5 }));
  assert.deepEqual([max.key, max.params.max], ["merge.err.audio_start_s_max", "4,9"]);
  const maxEn = a.audioErrorText(err({ field: "start_s", max_start_s: 4.9 }), undefined, { lang: "en" });
  assert.equal(maxEn.params.max, "4.9");
  assert.equal(a.audioErrorText(err({ field: "volume" })).key, "merge.err.audio_line_volume");
  for (const code of ["line_busy", "line_orphan", "line_failed"]) {
    assert.equal(a.audioErrorText({ code, status: 409, message: "", data: {} }).key, `merge.err.${code}`);
  }
  const limit = a.audioErrorText({ code: "lines_limit", status: 409, message: "", data: { max: 40 } });
  assert.deepEqual([limit.key, limit.params.max], ["merge.err.lines_limit", 40]);
});

test("hasPending видит и голос сцены, который делается", () => {
  assert.equal(a.hasPending({ tracks: [], lines: [line({ status: "pending" })] }), true);
  assert.equal(a.hasPending({ tracks: [], lines: [line()] }), false);
  assert.equal(a.hasPending({ tracks: [] }), false);
});

test("пределы голоса сцены: старый сервер — по умолчанию", () => {
  assert.deepEqual(a.lineLimits(null), { line_chars: 500, lines_per_fragment: 3, lines_max: 40, line_volume_max: 2, line_start_step: 0.1 });
  assert.equal(a.lineLimits({ line_chars: 300 }).line_chars, 300);
  assert.equal(a.lineLimits({ line_chars: -1 }).line_chars, 500);
});

test("звук склейки: голоса сцен в подписи, в «уже оплачено» и в сводке", () => {
  const info = a.soundInfo({ tracks: [], clip_sound: "keep", lines: [line(), line({ id: "b".repeat(32), orphan: true }), line({ id: "c".repeat(32), status: "pending" })] });
  assert.deepEqual(info, { voice: false, music: null, clip: "keep", pending: true, lines: 1 });
  assert.deepEqual(a.soundParts(info), ["lines"]);
  assert.equal(a.hasSound(info), true);
  assert.equal(a.paidSound(info), "voice");
  const fromSummary = a.soundInfo(null, { clip_sound: "quiet", music_volume: 0.35, voice_volume: 1, voice: true, music: false, lines: 2, pending: false });
  assert.deepEqual(a.soundParts(fromSummary), ["voice", "lines", "quiet"]);
  // Без голосов сцен — прежний вид (поля lines нет).
  assert.deepEqual(a.soundInfo({ tracks: [], clip_sound: "keep", lines: [] }), { voice: false, music: null, clip: "keep", pending: false });
});

test("parseSecond: запятая и точка, пусто и не число — null (поле не обнуляется)", () => {
  assert.equal(a.parseSecond("2,5"), 2.5);
  assert.equal(a.parseSecond("2.5"), 2.5);
  assert.equal(a.parseSecond(" 3 "), 3);
  assert.equal(a.parseSecond(",5"), 0.5);
  assert.equal(a.parseSecond("4."), 4);
  assert.equal(a.parseSecond("-1"), -1);
  for (const raw of ["", "  ", ",", ".", "-", "abc", "1,2,3", "1e3", "Infinity", "NaN", "2,5с"]) {
    assert.equal(a.parseSecond(raw), null, raw);
  }
  // Минус приводит clampStart, а не поле.
  assert.equal(a.clampStart(a.parseSecond("-1"), 5), 0);
});

test("freshSaid: тот же текст подряд меняет невидимый хвост — читалка скажет снова", () => {
  const first = a.freshSaid("", "Голос сцены готов");
  assert.equal(first, "Голос сцены готов");
  const second = a.freshSaid(first, "Голос сцены готов");
  assert.notEqual(second, first);
  assert.equal(second.trim(), "Голос сцены готов");
  const third = a.freshSaid(second, "Голос сцены готов");
  assert.notEqual(third, second);
  assert.equal(a.freshSaid(second, "Голос сцены убран"), "Голос сцены убран");
  assert.equal(a.freshSaid("x", ""), "");
});

test("голос окна «Голос сцены» запоминается по склейкам", () => {
  assert.deepEqual(a.readLineVoices(null), {});
  assert.deepEqual(a.readLineVoices("не json"), {});
  assert.deepEqual(a.readLineVoices("[1,2]"), {});
  assert.deepEqual(a.readLineVoices('{"p1":"v1","p2":5,"p3":""}'), { p1: "v1" });
  let map = a.withLineVoice({}, "p1", "v1");
  map = a.withLineVoice(map, "p2", "v2");
  map = a.withLineVoice(map, "p1", "v3");
  assert.deepEqual(map, { p2: "v2", p1: "v3" });
  assert.deepEqual(Object.keys(map), ["p2", "p1"], "свежая — последней");
  let many = {};
  for (let i = 0; i < 5; i += 1) many = a.withLineVoice(many, `p${i}`, "v", 3);
  assert.deepEqual(Object.keys(many), ["p2", "p3", "p4"], "сверх предела забываются старые");
  assert.deepEqual(a.withLineVoice({ p1: "v1" }, "p1", ""), {});
});

test("line_unavailable: свой текст отказа (ролик фрагмента недоступен)", () => {
  const spec = m.refusalText("line_unavailable", { index: 1 });
  assert.equal(spec.key, "merge.err.line_unavailable");
  assert.equal(spec.ru, MERGE_ERROR_RU.line_unavailable);
  assert.match(spec.ru, /недоступно/);
  const err = { code: "line_unavailable", status: 409, data: { index: 1 }, message: "x" };
  assert.equal(a.audioErrorText(err).key, "merge.err.line_unavailable");
});
