// Видеостудия, правая панель: чистая логика (settingsModel.ts) и тексты (settingsText.ts).
// Запуск (Node 22.6+):
//   node --experimental-strip-types --test src/components/vstudio/settings/*.test.mjs
import "../../../lib/vstudio/nodeTsHooks.mjs";
import { test } from "node:test";
import assert from "node:assert/strict";

const sm = await import("./settingsModel.ts");
const st = await import("./settingsText.ts");
const fx = await import("../../../lib/vstudio/fixtures.ts");
const lb = await import("../../../lib/vstudio/labels.ts");

const M = structuredClone(fx.FIXTURE_MODELS);
const byId = (id) => [...M.video, ...M.image].find((m) => m.id === id);
const SEEDANCE = byId("bytedance/seedance-2.0");
const VEO = byId("google/veo-3.1-fast");
const KLING = byId("kwaivgi/kling-v3.0-std");
const NANO = byId("google/gemini-2.5-flash-image");
const FLUX = byId("black-forest-labs/flux.2-flex");
// Veo после живой пробы: референсы включены, с ними — только 8 с.
const VEO_REFS = { ...VEO, caps: { ...VEO.caps, refs: { image: 3 } } };
// Модель только с первым кадром (Hailuo 2.3 / Grok).
const FIRST_ONLY = {
  ...KLING,
  id: "minimax/hailuo-2.3",
  name: "Hailuo 2.3",
  locked: false,
  caps: { ...KLING.caps, frames: ["first_frame"], audio: false, seed: false, negative: false, resolutions: ["768p"] },
};

const item = (n, over = {}) => ({
  lid: `l${n}`,
  assetUid: n.toString(16).padStart(32, "a"),
  slot: "reference",
  role: "",
  included: true,
  status: "ready",
  progress: 100,
  preview: `blob:${n}`,
  ...over,
});
const NO_FRAMES = { first_frame: null, last_frame: null };
const fakeT = (key, opts = {}) => st.fillText(String(opts.defaultValue ?? key), opts);

/* ---------- модели ---------- */

test("modelsFor / findModel / defaultModel", () => {
  assert.equal(sm.modelsFor(M, "video").length, 4);
  assert.deepEqual(sm.modelsFor(null, "video"), []);
  assert.equal(sm.findModel(M, "google/veo-3.1-fast")?.name, "Veo 3.1 Fast");
  assert.equal(sm.findModel(M, "google/veo-3.1-fast", "image"), null, "вид учитывается");
  assert.equal(sm.findModel(M, null), null);
  // Первая доступная по тарифу, а не первая в списке.
  assert.equal(sm.defaultModel([KLING, VEO]).id, VEO.id);
  assert.equal(sm.defaultModel([KLING]).id, KLING.id, "все под замком — всё равно показываем первую");
  assert.equal(sm.defaultModel([]), null);
});

/* ---------- параметры ---------- */

test("nearest: ближайшее, при равенстве — меньшее (как компилятор)", () => {
  assert.equal(sm.nearest([4, 6, 8], 10), 8);
  assert.equal(sm.nearest([4, 6], 5), 4);
  assert.equal(sm.nearest([5, 10, 15], 12), 10);
});

test("normalizeParams: Seedance сохраняет выбор и включает звук по умолчанию", () => {
  const p = sm.normalizeParams(SEEDANCE, "video", { duration: 10, resolution: "1080P", aspect_ratio: "9:16", seed: 7 });
  assert.deepEqual(p, { aspect_ratio: "9:16", duration: 10, resolution: "1080p", generate_audio: true, seed: 7 });
  // Негатив Seedance не понимает — в запрос не уходит.
  assert.equal(sm.normalizeParams(SEEDANCE, "video", { negative_prompt: "blur" }).negative_prompt, undefined);
  // Выключенный звук остаётся выключенным.
  assert.equal(sm.normalizeParams(SEEDANCE, "video", { generate_audio: false }).generate_audio, false);
});

test("normalizeParams: смена на Veo — ближайшая длительность, неизвестная пропорция → по умолчанию", () => {
  const p = sm.normalizeParams(VEO, "video", {
    duration: 10,
    resolution: "480p",
    aspect_ratio: "21:9",
    negative_prompt: "текст",
    seed: 3,
  });
  assert.equal(p.duration, 8);
  assert.equal(p.resolution, "720p", "480p у Veo нет — значение модели по умолчанию");
  assert.equal(p.aspect_ratio, "16:9");
  assert.equal(p.negative_prompt, "текст", "Veo понимает негатив");
  assert.equal(p.seed, 3);
  assert.equal(sm.normalizeParams(VEO, "video", { aspect_ratio: "auto" }).aspect_ratio, "auto");
});

test("normalizeParams: у модели без звука/seed/негатива эти поля убираются", () => {
  const p = sm.normalizeParams(FIRST_ONLY, "video", { generate_audio: true, seed: 1, negative_prompt: "x", resolution: "720p" });
  assert.equal(p.generate_audio, undefined);
  assert.equal(p.seed, undefined);
  assert.equal(p.negative_prompt, undefined);
  assert.equal(p.resolution, "768p");
});

test("normalizeParams: картинка — только пропорция", () => {
  const p = sm.normalizeParams(NANO, "image", { duration: 10, resolution: "720p", aspect_ratio: "9:16", generate_audio: true, seed: 4 });
  assert.deepEqual(p, { aspect_ratio: "9:16" });
  assert.deepEqual(sm.normalizeParams(NANO, "image", { aspect_ratio: "21:9" }), { aspect_ratio: "1:1" });
  assert.deepEqual(sm.normalizeParams({ ...NANO, defaults: { aspect_ratio: "auto" } }, "image", {}), { aspect_ratio: "auto" });
});

test("diffParams: удалённое — явным undefined, пустое равно пустому", () => {
  assert.deepEqual(sm.diffParams({ duration: 5 }, { duration: 5 }), {});
  assert.deepEqual(sm.diffParams({ seed: null }, {}), {});
  assert.deepEqual(sm.diffParams({ negative_prompt: "" }, {}), {});
  const patch = sm.diffParams({ duration: 10, seed: 3, aspect_ratio: "9:16" }, { duration: 8, aspect_ratio: "9:16" });
  assert.deepEqual(Object.keys(patch).sort(), ["duration", "seed"]);
  assert.equal(patch.duration, 8);
  assert.ok("seed" in patch && patch.seed === undefined);
});

test("applyParamsPatch: как редьюсер — undefined удаляет ключ", () => {
  const base = { duration: 5, seed: 3, aspect_ratio: "9:16" };
  const out = sm.applyParamsPatch(base, { seed: undefined, duration: 10 });
  assert.deepEqual(out, { duration: 10, aspect_ratio: "9:16" });
  assert.ok(!("seed" in out));
  assert.deepEqual(base, { duration: 5, seed: 3, aspect_ratio: "9:16" }, "исходник не меняется");
});

test("sanitizeParams: мусор из Project.settings отбрасывается", () => {
  assert.deepEqual(sm.sanitizeParams(null), {});
  assert.deepEqual(sm.sanitizeParams([1, 2]), {});
  assert.deepEqual(
    sm.sanitizeParams({ duration: "10", resolution: 720, aspect_ratio: "9:16", seed: -1, generate_audio: "yes", extra: 1 }),
    { aspect_ratio: "9:16" },
  );
  assert.equal(sm.sanitizeParams({ negative_prompt: "x".repeat(5000) }).negative_prompt.length, sm.NEGATIVE_MAX);
  assert.equal(sm.sanitizeParams({ seed: sm.SEED_MAX + 1 }).seed, undefined);
});

test("shownParams: пустые параметры показываются значениями модели по умолчанию", () => {
  assert.deepEqual(sm.shownParams(SEEDANCE, "video", {}), {
    aspect_ratio: "16:9",
    duration: 5,
    resolution: "720p",
    generate_audio: true,
  });
  assert.deepEqual(sm.shownParams(NANO, "image", {}), { aspect_ratio: "1:1" });
  assert.deepEqual(sm.shownParams(null, "video", { duration: 4 }), { duration: 4 });
});

/* ---------- смена модели и вида ---------- */

test("switchModelChoice / switchKindChoice", () => {
  const c = sm.switchModelChoice(M, "video", VEO.id, { duration: 12, aspect_ratio: "9:16" });
  assert.equal(c.model, VEO.id);
  assert.equal(c.params.duration, 8);
  assert.equal(sm.switchModelChoice(M, "video", NANO.id, {}), null, "модель другого вида не выбирается");

  // Видео → картинка: пропорция переезжает, если подходит.
  const img = sm.switchKindChoice(M, "image", { duration: 10, aspect_ratio: "9:16" }, {});
  assert.deepEqual(img, { kind: "image", model: NANO.id, params: { aspect_ratio: "9:16" } });

  // Обратно — к той же модели видео с её параметрами.
  const mem = { video: { model: VEO.id, params: { duration: 6, aspect_ratio: "16:9" } } };
  const back = sm.switchKindChoice(M, "video", { aspect_ratio: "1:1" }, mem);
  assert.equal(back.model, VEO.id);
  assert.equal(back.params.duration, 6);
  // Запомненная модель под замком не восстанавливается.
  const lockedMem = { video: { model: KLING.id, params: {} } };
  assert.equal(sm.switchKindChoice(M, "video", {}, lockedMem).model, SEEDANCE.id);
  assert.equal(sm.switchKindChoice({ video: [], image: [] }, "video", {}, null), null);
});

test("choiceFromSettings / initialChoice", () => {
  const settings = { kind: "video", model: VEO.id, params: { duration: 6, aspect_ratio: "9:16", junk: 1 } };
  const c = sm.choiceFromSettings(M, settings);
  assert.deepEqual(c, { kind: "video", model: VEO.id, params: { aspect_ratio: "9:16", duration: 6, resolution: "720p", generate_audio: true } });
  assert.equal(sm.choiceFromSettings(M, { kind: "video", model: KLING.id }), null, "модель под замком");
  assert.equal(sm.choiceFromSettings(M, { kind: "video", model: "gone/model" }), null);
  assert.equal(sm.choiceFromSettings(M, { kind: "movie", model: VEO.id }), null);
  assert.equal(sm.choiceFromSettings(M, {}), null);

  assert.equal(sm.initialChoice(M, "video", { settings }).model, VEO.id, "настройки проекта главнее");
  assert.equal(
    sm.initialChoice(M, "video", { memory: { video: { model: VEO.id, params: {} } } }).model,
    VEO.id,
    "потом — последний выбор во вкладке",
  );
  assert.equal(sm.initialChoice(M, "video", {}).model, SEEDANCE.id);
  // Видео-моделей нет — переходим на картинки, а не оставляем пустую панель.
  const onlyImages = { video: [], image: M.image };
  assert.equal(sm.initialChoice(onlyImages, "video", {}).kind, "image");
  assert.equal(sm.initialChoice({ video: [], image: [] }, "video", {}), null);
});

/* ---------- Project.settings ---------- */

test("settingsPayload: чужие ключи проекта сохраняются, by_kind помнит оба вида", () => {
  const prev = { kind: "image", model: NANO.id, params: { aspect_ratio: "1:1" }, foo: "bar", by_kind: { image: { model: NANO.id, params: { aspect_ratio: "1:1" } } } };
  const payload = sm.settingsPayload(prev, { kind: "video", model: VEO.id, params: { duration: 8, seed: null, negative_prompt: "" } });
  assert.equal(payload.foo, "bar");
  assert.equal(payload.kind, "video");
  assert.deepEqual(payload.params, { duration: 8 }, "пустые значения не сохраняются");
  assert.deepEqual(payload.by_kind.image, { model: NANO.id, params: { aspect_ratio: "1:1" } });
  assert.deepEqual(payload.by_kind.video, { model: VEO.id, params: { duration: 8 } });
  assert.deepEqual(sm.memoryFromSettings(payload).video, { model: VEO.id, params: { duration: 8 } });
  assert.deepEqual(sm.memoryFromSettings({ by_kind: "x" }), {});
});

test("settingsKey: порядок ключей и by_kind не важны, пустое = пустое", () => {
  const a = sm.settingsKey({ kind: "video", model: "m", params: { duration: 5, aspect_ratio: "9:16" } });
  const b = sm.settingsKey({ params: { aspect_ratio: "9:16", duration: 5, seed: null }, model: "m", kind: "video", by_kind: { x: 1 } });
  assert.equal(a, b);
  assert.notEqual(a, sm.settingsKey({ kind: "video", model: "m", params: { duration: 10, aspect_ratio: "9:16" } }));
  assert.equal(sm.settingsKey(null), "");
  assert.equal(sm.settingsKey({}), sm.settingsKey({ params: {} }));
});

/* ---------- цены-подсказки ---------- */

test("priceHint: таблица, by_aspect (21:9 дороже), Авто — базовая таблица", () => {
  const base = SEEDANCE.price.table["720p"]["10"];
  assert.equal(sm.priceHint(SEEDANCE, { duration: 10, resolution: "720p", aspect: "16:9" }), base);
  assert.equal(sm.priceHint(SEEDANCE, { duration: 10, resolution: "720P", aspect: "auto" }), base);
  const wide = sm.priceHint(SEEDANCE, { duration: 10, resolution: "720p", aspect: "21:9" });
  assert.equal(wide, SEEDANCE.price.by_aspect["21:9"]["720p"]["10"]);
  assert.ok(wide > base);
  assert.ok(sm.priceHint(SEEDANCE, { duration: 10, resolution: "1080p" }) > base, "1080p дороже");
  assert.equal(sm.priceHint(SEEDANCE, { duration: 7, resolution: "720p" }), null, "нет в таблице — без подсказки");
  assert.equal(sm.priceHint(SEEDANCE, { duration: null, resolution: "720p" }), null);
  assert.equal(sm.priceHint(NANO, { duration: 5, resolution: "720p" }), null, "у картинок нет таблицы");
  assert.equal(sm.aspectAffectsPrice(SEEDANCE), true);
  assert.equal(sm.aspectAffectsPrice(VEO), false);
});

test("visibleDurations: длинный ряд сворачивается до ходовых, текущее не пропадает", () => {
  const all = Array.from({ length: 27 }, (_, i) => i + 4); // 4…30 (Seedance 2.5)
  const shown = sm.visibleDurations(all, 7, false);
  assert.ok(shown.includes(4) && shown.includes(30), "минимум и максимум");
  assert.ok(shown.includes(7), "текущее значение");
  assert.ok(shown.length <= 11);
  assert.deepEqual(sm.visibleDurations(all, 7, true), all);
  assert.deepEqual(sm.visibleDurations([4, 6, 8], 6, false), [4, 6, 8]);
});

/* ---------- материалы и режим ---------- */

test("countInputs: выключенные и упавшие не считаются, свои загрузки — считаются", () => {
  const tray = [
    item(1),
    item(2, { included: false }),
    item(3, { status: "failed" }),
    item(4, { asset: { source: "generated_image" } }),
    item(5, { status: "uploading", assetUid: undefined }),
  ];
  const frames = { first_frame: item(6, { slot: "first_frame" }), last_frame: item(7, { slot: "last_frame", included: false }) };
  const c = sm.countInputs(tray, frames);
  assert.deepEqual(c, { refs: 3, refsExcluded: 1, first: true, last: false, uploads: 3 });
});

test("localMode: режимы как у компилятора", () => {
  const c = (over) => ({ refs: 0, refsExcluded: 0, first: false, last: false, uploads: 0, ...over });
  assert.deepEqual(sm.localMode("video", SEEDANCE, c({})), { mode: "t2v", issue: null, pinK: null });
  assert.equal(sm.localMode("video", SEEDANCE, c({ first: true })).mode, "i2v");
  assert.equal(sm.localMode("video", SEEDANCE, c({ first: true, last: true })).mode, "flf2v");
  assert.equal(sm.localMode("video", SEEDANCE, c({ last: true })).mode, "flf2v");
  assert.deepEqual(sm.localMode("video", SEEDANCE, c({ refs: 2 })), { mode: "r2v", issue: null, pinK: null });
  // Референсы у Veo выключены до пробы.
  assert.deepEqual(sm.localMode("video", VEO, c({ refs: 1 })), { mode: "r2v", issue: "refsOff", pinK: null });
  assert.equal(sm.localMode("video", VEO, c({ refs: 1, first: true })).issue, "refsOff");
  // Seedance: кадр + референсы → кадр уходит последним референсом Image k.
  assert.deepEqual(sm.localMode("video", SEEDANCE, c({ refs: 2, first: true })), { mode: "r2v_pin", issue: null, pinK: 3 });
  assert.deepEqual(sm.localMode("video", SEEDANCE, c({ refs: 2, last: true })), { mode: "r2v", issue: null, pinK: null });
  // Veo после пробы: кадры и референсы вместе нельзя.
  assert.equal(sm.localMode("video", VEO_REFS, c({ refs: 1, first: true })).issue, "conflict");
  assert.equal(sm.localMode("image", NANO, c({})).mode, "t2i");
  assert.equal(sm.localMode("image", NANO, c({ refs: 2 })).mode, "i2i");
  assert.equal(sm.localMode("image", { ...NANO, caps: { ...NANO.caps, refs: { image: 0 } } }, c({ refs: 1 })).issue, "refsOff");
});

test("forcedDuration: Veo + референсы → 8 с, только когда референсы реально уходят", () => {
  const withRefs = { refs: 1, refsExcluded: 0, first: false, last: false, uploads: 1 };
  assert.equal(sm.forcedDuration("video", VEO_REFS, withRefs), 8);
  assert.equal(sm.forcedDuration("video", VEO, withRefs), null, "референсы выключены — не форсирует");
  assert.equal(sm.forcedDuration("video", VEO_REFS, { ...withRefs, refs: 0 }), null);
  assert.equal(sm.forcedDuration("video", SEEDANCE, withRefs), null);
  assert.equal(sm.forcedDuration("image", VEO_REFS, withRefs), null);
});

/* ---------- карточки ---------- */

test("modelBadges: возможности модели", () => {
  const keys = (refs) => refs.map((r) => st.fillText(st.SETTINGS_RU[r.key], r.params));
  assert.deepEqual(keys(sm.modelBadges(SEEDANCE, "video")), ["до 9 фото", "первый и последний кадр", "звук", "до 15 с", "до 1080p"]);
  assert.deepEqual(keys(sm.modelBadges(VEO, "video")), ["первый и последний кадр", "звук", "до 8 с", "до 1080p"]);
  assert.deepEqual(keys(sm.modelBadges(FIRST_ONLY, "video")), ["первый кадр", "до 15 с"]);
  assert.deepEqual(keys(sm.modelBadges(FLUX, "image")), ["до 8 фото"]);
});

test("modelCompat: причина видна до выбора модели", () => {
  const c = (over) => ({ refs: 0, refsExcluded: 0, first: false, last: false, uploads: 0, ...over });
  const keys = (m, kind, counts) => sm.modelCompat(m, kind, counts).map((r) => r.key);
  assert.deepEqual(keys(SEEDANCE, "video", c({ refs: 3 })), []);
  assert.deepEqual(keys(VEO, "video", c({ refs: 2 })), ["settings.compat.refsOff"]);
  assert.deepEqual(keys(VEO_REFS, "video", c({ refs: 4 })), ["settings.compat.tooManyRefs", "settings.compat.forced"]);
  assert.deepEqual(keys(VEO_REFS, "video", c({ refs: 1, first: true })), ["settings.compat.framesRefs", "settings.compat.forced"]);
  // soft_pin: кадр занимает ещё одно место среди референсов.
  assert.deepEqual(keys(SEEDANCE, "video", c({ refs: 9, first: true })), ["settings.compat.tooManyRefs"]);
  assert.deepEqual(keys(FIRST_ONLY, "video", c({ first: true, last: true })), ["settings.compat.noLastFrame"]);
  assert.deepEqual(keys(NANO, "image", c({ refs: 4, first: true })), ["settings.compat.tooManyRefs", "settings.compat.imageFrames"]);
  const tm = sm.modelCompat(NANO, "image", c({ refs: 4 }))[0];
  assert.equal(st.fillText(st.SETTINGS_RU[tm.key], tm.params), "Принимает не больше 3 фото, у вас 4");
});

test("modelFacts и etaText", () => {
  assert.deepEqual(
    sm.modelFacts(SEEDANCE, "video").map((r) => r.key),
    ["settings.fact.maxRefs", "settings.fact.minPx", "settings.fact.faces", "settings.fact.en"],
  );
  assert.deepEqual(sm.modelFacts(NANO, "image").map((r) => r.key), ["settings.fact.maxRefs"]);
  assert.deepEqual(sm.etaText(150), { key: "settings.etaMin", params: { n: 3 } });
  assert.deepEqual(sm.etaText(90), { key: "settings.etaMin", params: { n: 2 } });
  assert.deepEqual(sm.etaText(22), { key: "settings.etaSec", params: { n: 20 } });
  assert.deepEqual(sm.etaText(2), { key: "settings.etaSec", params: { n: 5 } });
  assert.equal(sm.etaText(0), null);
  assert.equal(sm.etaText(null), null);
});

/* ---------- «Как модель использует ваши фото» ---------- */

test("explainRows: номера @Image N только у включённых, метки quote главнее", () => {
  const tray = [
    item(1, { role: "героиня" }),
    item(2, { included: false }),
    item(3, { status: "failed", assetUid: undefined }),
    item(4),
    item(5, { status: "uploading", assetUid: undefined }),
  ];
  const rows = sm.explainRows("video", SEEDANCE, tray, NO_FRAMES);
  // Номер — как на чипе в лотке (labels.trayNumbers): у грузящегося uid ещё нет — нет и номера.
  assert.deepEqual(rows.map((r) => r.label), ["@Image 1", "—", "—", "@Image 2", "—"]);
  const chipNumbers = lb.trayNumbers(tray);
  assert.deepEqual(
    rows.map((r) => (r.label === "—" ? null : Number(r.label.replace("@Image ", "")))),
    tray.map((it) => chipNumbers[it.lid]),
    "совпадает с бейджами лотка",
  );
  assert.deepEqual(rows.map((r) => r.note?.key ?? null), [
    null,
    "settings.refExcluded",
    "settings.refFailed",
    "settings.refNoRole",
    "settings.refUploading",
  ]);
  assert.equal(rows[0].role, "героиня");
  assert.deepEqual(rows.map((r) => r.tone), ["ok", "muted", "error", "muted", "muted"]);

  // Свежий quote уже пронумеровал — его метка главнее.
  const labels = { [item(4).assetUid]: "Image 7" };
  assert.equal(sm.explainRows("video", SEEDANCE, tray, NO_FRAMES, { labels })[3].label, "@Image 7");

  // Больше, чем принимает модель: лишние видно сразу.
  const nano = sm.explainRows("image", NANO, [item(1), item(2), item(3), item(4)], NO_FRAMES);
  assert.deepEqual(nano.map((r) => r.note?.key ?? null).slice(2), ["settings.refNoRole", "settings.refOverflow"]);
  assert.deepEqual(nano[3].note.params, { model: "Nano Banana", max: 3 });
  // soft_pin: первый кадр занимает девятое место из девяти.
  const nine = Array.from({ length: 9 }, (_, i) => item(i + 1, { role: "x" }));
  const pin = sm.explainRows("video", SEEDANCE, nine, { first_frame: item(20, { slot: "first_frame" }), last_frame: null }, { mode: "r2v_pin", pinK: 10 });
  assert.equal(pin[8].note?.key, "settings.refOverflow");
  assert.equal(pin[7].note, null);

  // Модель без референсов: фото не уйдут — это видно в строке.
  const veo = sm.explainRows("video", VEO, [item(1)], NO_FRAMES);
  assert.equal(veo[0].note.key, "settings.refIgnored");
  assert.equal(veo[0].tone, "warn");

  // Созданная картинка не получилась: номер остаётся (как у красного чипа), причина — в строке.
  const failed = sm.explainRows("video", SEEDANCE, [item(1, { status: "failed" }), item(2)], NO_FRAMES);
  assert.deepEqual(failed.map((r) => [r.label, r.note?.key ?? null, r.tone]), [
    ["@Image 1", "settings.refFailed", "error"],
    ["@Image 2", "settings.refNoRole", "muted"],
  ]);
  // Тот же материал дважды: сервер склеит дубли — второй без номера.
  const dup = sm.explainRows("video", SEEDANCE, [item(1), item(1, { lid: "copy" })], NO_FRAMES);
  assert.deepEqual(dup.map((r) => r.label), ["@Image 1", "—"]);
});

test("explainRows: кадры — начало/конец, soft_pin, картинка", () => {
  const frames = { first_frame: item(8, { slot: "first_frame" }), last_frame: item(9, { slot: "last_frame" }) };
  const rows = sm.explainRows("video", SEEDANCE, [], frames);
  assert.deepEqual(rows.map((r) => [r.slot, r.note.key]), [
    ["first_frame", "settings.frameFirst"],
    ["last_frame", "settings.frameLast"],
  ]);
  const pinned = sm.explainRows("video", SEEDANCE, [item(1)], frames, { mode: "r2v_pin", pinK: 2 });
  assert.deepEqual(pinned[1].note, { key: "settings.framePinned", params: { k: 2 } });
  const img = sm.explainRows("image", NANO, [], frames);
  assert.equal(img[0].note.key, "settings.frameImage");
  const off = sm.explainRows("video", SEEDANCE, [], { first_frame: item(8, { slot: "first_frame", included: false }), last_frame: null });
  assert.equal(off[0].note.key, "settings.refExcluded");
});

test("modeText: одна фраза на режим", () => {
  const c = (over) => ({ refs: 0, refsExcluded: 0, first: false, last: false, uploads: 0, ...over });
  const text = (kind, m, counts) => {
    const r = sm.modeText(kind, m, sm.localMode(kind, m, counts), counts);
    return st.fillText(st.SETTINGS_RU[r.key], r.params);
  };
  assert.match(text("video", SEEDANCE, c({})), /только по тексту/);
  assert.match(text("video", SEEDANCE, c({ first: true })), /начнётся с первого кадра/);
  assert.match(text("video", SEEDANCE, c({ last: true })), /закончится последним кадром/);
  assert.match(text("video", SEEDANCE, c({ refs: 2, first: true })), /как Image 3/);
  assert.match(text("video", VEO, c({ refs: 1 })), /^Veo 3\.1 Fast не умеет работать с фото-референсами/);
  assert.match(text("video", VEO_REFS, c({ refs: 1, first: true })), /одновременно/);
  assert.match(text("image", NANO, c({ refs: 1 })), /опирается на ваши фото/);
  assert.match(text("image", NANO, c({})), /нарисует/);
});

test("chipParts: «Seedance 2.0 · 9:16 · 10 с»", () => {
  assert.deepEqual(sm.chipParts(SEEDANCE, "video", { aspect_ratio: "9:16", duration: 10 }), {
    model: "Seedance 2.0",
    aspect: "9:16",
    duration: 10,
  });
  assert.deepEqual(sm.chipParts(SEEDANCE, "video", {}), { model: "Seedance 2.0", aspect: "16:9", duration: 5 });
  assert.deepEqual(sm.chipParts(NANO, "image", { duration: 10 }), { model: "Nano Banana", aspect: "1:1", duration: null });
  assert.deepEqual(sm.chipParts(null, "video", {}), { model: "", aspect: null, duration: null });
});

/* ---------- тексты ---------- */

test("tx: ключ ns vstudio, русский по умолчанию, подстановки", () => {
  const seen = [];
  const t = (key, opts) => {
    seen.push([key, opts.ns]);
    return fakeT(key, opts);
  };
  assert.equal(st.tx(t, "settings.priceFrom", { n: st.fmtNum(1200) }), `от ${(1200).toLocaleString("ru-RU")} кр`);
  assert.deepEqual(seen[0], ["settings.priceFrom", "vstudio"]);
  assert.equal(st.txRef(fakeT, { key: "settings.durationForced", params: { model: "Veo", n: 8 } }),
    "С фото-референсами Veo снимает только 8 с — другие значения недоступны");
  // t вернул не строку (объект при returnObjects) — не падаем, берём русский.
  assert.equal(st.tx(() => ({}), "settings.title"), "Параметры запуска");
  assert.equal(st.fillText("{{a}} и {{b}}", { a: 1 }), "1 и ");
});

test("SETTINGS_RU: все ключи в группах §10 и без пустых строк", () => {
  const groups = new Set(["kind", "settings", "mobile"]);
  for (const [k, v] of Object.entries(st.SETTINGS_RU)) {
    assert.ok(groups.has(k.split(".")[0]), k);
    assert.ok(typeof v === "string" && v.trim().length > 0, k);
  }
  // Ключи §10, которые панель обязана использовать.
  for (const k of [
    "settings.title", "settings.model", "settings.aspect", "settings.aspectAuto", "settings.duration",
    "settings.seconds", "settings.resolution", "settings.audio", "settings.audioHint", "settings.advanced",
    "settings.seed", "settings.seedHint", "settings.negative", "settings.priceFrom", "settings.locked",
    "settings.eta", "settings.disabledWhy", "settings.howRefsUsed", "settings.refRole", "settings.refNoRole",
    "settings.frameFirst", "settings.frameLast", "settings.badge.refs", "settings.badge.frames",
    "settings.badge.audio", "kind.video", "kind.image", "mobile.params", "mobile.close",
  ]) {
    assert.ok(k in st.SETTINGS_RU, k);
  }
});
