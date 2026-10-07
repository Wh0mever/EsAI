// Первый экран: карточки моделей (tools/modelStrip.ts) и карточка «Первый и последний кадр» (tools/framesPlan.ts).
// Запуск (Node 22.6+):  node --experimental-strip-types --test src/components/vstudio/home/tools/*.test.mjs
import "../../../../lib/vstudio/nodeTsHooks.mjs";
import { test } from "node:test";
import assert from "node:assert/strict";

const M = await import("./modelStrip.ts");
const F = await import("./framesPlan.ts");
const Store = await import("../../store.ts");
const Sync = await import("../../settings/useRunSettingsSync.ts");
const { FIXTURE_MODELS } = await import("@/lib/vstudio/fixtures");

const SEEDANCE = "bytedance/seedance-2.0";
const SEEDANCE_FAST = "bytedance/seedance-2.0-fast";
const VEO = "google/veo-3.1-fast";
const KLING_LOCKED = "kwaivgi/kling-v3.0-std";
const BANANA = "google/gemini-2.5-flash-image";
const FLUX = "black-forest-labs/flux.2-flex";

const video = (id) => FIXTURE_MODELS.video.find((m) => m.id === id);
const image = (id) => FIXTURE_MODELS.image.find((m) => m.id === id);
const keys = (facts) => facts.map((f) => (f.kind === "badge" ? f.ref.key : f.kind));

/* ---------- метки и цена ---------- */

test("метки карточки: не больше трёх, сначала свои фото, звук и длина ролика", () => {
  // Seedance умеет всё — кадры и качество на карточку уже не помещаются.
  const seedance = M.stripFacts(video(SEEDANCE), "video");
  assert.deepEqual(keys(seedance), ["settings.badge.refs", "settings.badge.audio", "settings.badge.duration"]);
  assert.deepEqual(seedance[0].ref.params, { n: 9 });
  assert.deepEqual(seedance[2].ref.params, { n: 15 });
  // Veo без фото-референсов — место занимает качество.
  assert.deepEqual(keys(M.stripFacts(video(VEO), "video")), [
    "settings.badge.audio",
    "settings.badge.duration",
    "settings.badge.resolution",
  ]);
  // Одно качество — не достоинство; тогда на карточку попадают кадры.
  assert.deepEqual(keys(M.stripFacts(video(KLING_LOCKED), "video")), [
    "settings.badge.audio",
    "settings.badge.duration",
    "settings.badge.frames",
  ]);
  assert.equal(M.STRIP_FACTS_MAX, 3);
});

test("метки картинок: свои фото и число пропорций", () => {
  const flux = M.stripFacts(image(FLUX), "image");
  assert.deepEqual(keys(flux), ["settings.badge.refs", "aspects"]);
  assert.deepEqual(flux[1], { kind: "aspects", n: image(FLUX).caps.aspect_ratios.length });
  // Единственная пропорция — не выбор, метки нет.
  const square = { ...image(FLUX), caps: { ...image(FLUX).caps, aspect_ratios: ["1:1"], refs: { image: 0 } } };
  assert.deepEqual(M.stripFacts(square, "image"), []);
});

test("цена: «от N кр» у видео, цена за картинку у картинок, без цены — ничего", () => {
  const seedance = video(SEEDANCE);
  assert.deepEqual(M.stripPrice(seedance, "video"), {
    key: "settings.priceFrom",
    params: { n: Math.round(seedance.price_from).toLocaleString("ru-RU") },
  });
  assert.deepEqual(M.stripPrice(image(FLUX), "image"), { key: "settings.perImage", params: { n: "12" } });
  // У картинки нет per_image — берём price_from, как в списке моделей панели.
  assert.deepEqual(M.stripPrice({ ...image(FLUX), per_image: undefined, price_from: 9 }, "image").params, { n: "9" });
  assert.equal(M.stripPrice({ ...seedance, price_from: null }, "video"), null);
});

/* ---------- шапка ---------- */

test("шапка: цвет вендора в двух пятнах на подложке студии", () => {
  const art = M.vendorArt("#25f4ee");
  assert.equal(art.split("#25f4ee").length - 1, 2);
  assert.match(art, /^radial-gradient\(120% 140% at 0% 0%, color-mix\(in srgb, #25f4ee 42%, transparent\), transparent 62%\), /);
  assert.match(art, /color-mix\(in srgb, #25f4ee 18%, transparent\), transparent 60%\), var\(--surface-2\)$/);
});

test("шапка: у каждой модели своё место колец, одно и то же при каждом показе", () => {
  const ids = [...FIXTURE_MODELS.video, ...FIXTURE_MODELS.image].map((m) => m.id);
  for (const id of ids) {
    const lens = M.artLens(id);
    assert.deepEqual(M.artLens(id), lens);
    assert.ok(lens.x >= 56 && lens.x <= 86, `${id}: x=${lens.x}`);
    assert.ok(lens.y >= 4 && lens.y <= 48, `${id}: y=${lens.y}`);
  }
  // Две модели одного вендора (тот же цвет и буква) не должны выглядеть копиями.
  assert.notDeepEqual(M.artLens(SEEDANCE), M.artLens(SEEDANCE_FAST));
});

/* ---------- выбор ---------- */

/** Стор с моделями и выбранной Seedance 2.0; действия идут через настоящий редьюсер. */
function studio(setup = []) {
  Sync.resetRunSettingsSync();
  let state = Store.reducer(Store.createInitialState(), { type: "models/loaded", payload: FIXTURE_MODELS });
  const log = [];
  const dispatch = (action) => {
    log.push(action.type);
    state = Store.reducer(state, action);
  };
  dispatch({ type: "composer/model", model: SEEDANCE });
  for (const action of setup) dispatch(action);
  log.length = 0;
  return {
    log,
    dispatch,
    get state() {
      return state;
    },
    get composer() {
      return state.composer;
    },
    choose: (kind, id) => M.chooseModel(dispatch, state.models, state.composer, kind, id),
  };
}

test("выбор: модель того же вида — как в панели параметров, значения подстраиваются", () => {
  const s = studio();
  s.choose("video", VEO);
  assert.equal(s.composer.kind, "video");
  assert.equal(s.composer.model, VEO);
  // Seedance стояла на 5 с — Veo так не снимает, берётся ближайшее её значение.
  assert.ok(video(VEO).caps.durations.includes(s.composer.params.duration));
  assert.ok(video(VEO).caps.resolutions.includes(s.composer.params.resolution));
});

test("выбор: модель другого вида — меняется и вид, пропорция переносится", () => {
  const s = studio([{ type: "composer/params", params: { aspect_ratio: "9:16" } }]);
  s.choose("image", FLUX);
  assert.equal(s.composer.kind, "image");
  assert.equal(s.composer.model, FLUX);
  assert.equal(s.composer.params.aspect_ratio, "9:16");
  // У картинки нет длительности и звука — в запрос они уйти не должны.
  assert.equal(s.composer.params.duration, undefined);
  assert.equal(s.composer.params.generate_audio, undefined);
});

test("выбор: возврат к модели, с которой ушли из вида, возвращает и её параметры", () => {
  const s = studio();
  s.choose("video", VEO);
  s.dispatch({ type: "composer/params", params: { duration: 6, resolution: "1080p", aspect_ratio: "9:16" } });
  s.choose("image", BANANA);
  assert.equal(s.composer.model, BANANA);
  s.log.length = 0;
  s.choose("video", VEO);
  assert.equal(s.composer.kind, "video");
  assert.equal(s.composer.model, VEO);
  assert.equal(s.composer.params.duration, 6);
  assert.equal(s.composer.params.resolution, "1080p");
  assert.equal(s.composer.params.aspect_ratio, "9:16");
  // Вид сам вернул эту модель — второй раз её выбирать незачем.
  assert.equal(s.log.filter((type) => type === "composer/model").length, 1);
});

test("выбор: другая модель вида, из которого уходили, получает его значения, а не случайные", () => {
  const s = studio();
  s.choose("video", VEO);
  s.dispatch({ type: "composer/params", params: { duration: 8, aspect_ratio: "9:16" } });
  s.choose("image", FLUX);
  s.choose("video", SEEDANCE_FAST);
  assert.equal(s.composer.model, SEEDANCE_FAST);
  assert.equal(s.composer.params.duration, 8);
  assert.equal(s.composer.params.aspect_ratio, "9:16");
});

test("выбор: уже выбранная модель — ни вид, ни модель не меняются", () => {
  const s = studio();
  s.choose("video", SEEDANCE);
  // Как и в панели параметров, первый выбор может дописать значения по умолчанию (звук) — но не больше.
  assert.ok(s.log.every((type) => type === "composer/params"), s.log.join(","));
  assert.equal(s.composer.model, SEEDANCE);
  const params = s.composer.params;
  s.log.length = 0;
  s.choose("video", SEEDANCE);
  assert.deepEqual(s.log, []);
  assert.deepEqual(s.composer.params, params);
});

/* ---------- первый и последний кадр ---------- */

const frames = (id, list, locked = false) => ({ ...video(VEO), id, name: id, locked, caps: { ...video(VEO).caps, frames: list } });
const BOTH = ["first_frame", "last_frame"];

test("кадры: модель человека их уже умеет — её не меняем", () => {
  assert.deepEqual(F.framesPlan(FIXTURE_MODELS, { kind: "video", model: VEO }), { kind: "keep" });
  // Хватает и одного кадра: слоты у панели запроса уже есть.
  const models = { video: [frames("a/first", ["first_frame"]), frames("b/both", BOTH)], image: [] };
  assert.deepEqual(F.framesPlan(models, { kind: "video", model: "a/first" }), { kind: "keep" });
});

test("кадры: выбрана картинка или модель без кадров — первая доступная модель с обоими кадрами", () => {
  const fromImage = F.framesPlan(FIXTURE_MODELS, { kind: "image", model: FLUX });
  assert.equal(fromImage.kind, "select");
  assert.equal(fromImage.model.id, SEEDANCE);

  const models = {
    video: [frames("a/none", []), frames("b/locked", BOTH, true), frames("c/first", ["first_frame"]), frames("d/both", BOTH)],
    image: [],
  };
  const plan = F.framesPlan(models, { kind: "video", model: "a/none" });
  // Под замком пропускаем; оба кадра важнее порядка — «c/first» стоит раньше, но конец ролика не задаст.
  assert.equal(plan.kind, "select");
  assert.equal(plan.model.id, "d/both");
});

test("кадры: обоих кадров нет ни у одной доступной — годится модель с первым", () => {
  const models = { video: [frames("a/none", []), frames("b/locked", BOTH, true), frames("c/first", ["first_frame"])], image: [] };
  const plan = F.framesPlan(models, { kind: "video", model: "a/none" });
  assert.equal(plan.kind, "select");
  assert.equal(plan.model.id, "c/first");
});

test("кадры: умеют только платные модели — замок; не умеет никто или список не пришёл — нечего выбирать", () => {
  const paid = { video: [frames("a/none", []), frames("b/locked", BOTH, true)], image: [] };
  assert.deepEqual(F.framesPlan(paid, { kind: "video", model: "a/none" }), { kind: "locked" });
  const none = { video: [frames("a/none", [])], image: [] };
  assert.deepEqual(F.framesPlan(none, { kind: "video", model: "a/none" }), { kind: "none" });
  assert.deepEqual(F.framesPlan(null, { kind: "video", model: null }), { kind: "none" });
});

test("кадры: план и выбор вместе — из картинки в видео с моделью, у которой есть слоты", () => {
  const s = studio();
  s.choose("image", FLUX);
  const plan = F.framesPlan(s.state.models, s.composer);
  assert.equal(plan.kind, "select");
  s.choose("video", plan.model.id);
  assert.equal(s.composer.kind, "video");
  assert.deepEqual(F.framesPlan(s.state.models, s.composer), { kind: "keep" });
});
