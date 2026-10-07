// Ссылка с выбором /video-studio?model=&kind=&prompt= (deepLink.ts) на настоящем редьюсере.
// Запуск (Node 22.6+):  node --experimental-strip-types --test src/components/vstudio/deepLink.test.mjs
import "../../lib/vstudio/nodeTsHooks.mjs";
import { test } from "node:test";
import assert from "node:assert/strict";

const D = await import("./deepLink.ts");
const Store = await import("./store.ts");
const Sync = await import("./settings/useRunSettingsSync.ts");
const { FIXTURE_MODELS } = await import("@/lib/vstudio/fixtures");
const { plainText, isValidDoc } = await import("@/lib/vstudio/promptDoc");

const SEEDANCE = "bytedance/seedance-2.0";
const VEO = "google/veo-3.1-fast";
const KLING_LOCKED = "kwaivgi/kling-v3.0-std";
const FLUX = "black-forest-labs/flux.2-flex";

/* ---------- разбор адреса ---------- */

test("разбор: наших параметров нет — null, адрес трогать незачем", () => {
  assert.equal(D.parseDeepLink(""), null);
  assert.equal(D.parseDeepLink(null), null);
  assert.equal(D.parseDeepLink("?take=0123&utm_source=tg"), null);
});

test("разбор: модель, вид и текст", () => {
  assert.deepEqual(D.parseDeepLink(`?model=${encodeURIComponent(VEO)}&kind=video&prompt=${encodeURIComponent("Кот идёт по крыше")}`), {
    model: VEO,
    kind: "video",
    prompt: "Кот идёт по крыше",
  });
  // Косая черта в id без кодирования и «+» вместо пробела — так ссылку часто пишут руками.
  assert.deepEqual(D.parseDeepLink(`?model=${VEO}&prompt=night+city`), { model: VEO, kind: null, prompt: "night city" });
  assert.deepEqual(D.parseDeepLink("?kind=IMAGE"), { model: null, kind: "image", prompt: null });
});

test("разбор: негодные значения молча пропадают, но ссылка остаётся ссылкой", () => {
  assert.deepEqual(D.parseDeepLink("?model=<script>&kind=audio&prompt=%20%20"), { model: null, kind: null, prompt: null });
  assert.deepEqual(D.parseDeepLink(`?model=${"a".repeat(129)}`), { model: null, kind: null, prompt: null });
});

test("разбор: текст длиннее предела не берём вовсе, ровно предел — берём", () => {
  const max = D.DEEP_LINK_PROMPT_MAX;
  assert.equal(D.parseDeepLink(`?prompt=${"я".repeat(max)}`).prompt.length, max);
  assert.equal(D.parseDeepLink(`?prompt=${"я".repeat(max + 1)}`).prompt, null);
  // Эмодзи — один знак, как считает сервер.
  assert.equal(D.parseDeepLink(`?prompt=${encodeURIComponent("🎬".repeat(max))}`).prompt, "🎬".repeat(max));
});

test("разбор: управляющие символы вычищаются, переводы строк остаются", () => {
  assert.equal(D.parseDeepLink("?prompt=one%00%0D%0Atwo%1F").prompt, "one\ntwo");
});

test("чистый адрес: наши параметры убираются, чужие остаются", () => {
  assert.equal(D.stripDeepLink(`?model=${VEO}&kind=video&prompt=x`), "");
  assert.equal(D.stripDeepLink(`?utm_source=tg&model=${VEO}&payment=tokens_success`), "?utm_source=tg&payment=tokens_success");
  assert.equal(D.stripDeepLink(""), "");
});

/* ---------- путь возврата после входа ---------- */

test("возврат после входа: из проекта — в проект, без параметров", () => {
  const uid = "0123456789abcdef0123456789abcdef";
  assert.equal(D.signInReturnPath("/video-studio", uid, { kind: "video", model: VEO }), `/video-studio/${uid}`);
});

test("возврат после входа: с первого экрана — ссылка с выбором, которую примет страница входа", async () => {
  const { safeReturnPath } = await import("@/tools/returnPath");
  const path = D.signInReturnPath("/video-studio", null, { kind: "video", model: VEO });
  assert.equal(path, `/video-studio?kind=video&model=${encodeURIComponent(VEO)}`);
  assert.equal(safeReturnPath(path), path, "иначе вход увёл бы в чат");
  // Та же ссылка, разобранная студией после входа, — тот же выбор.
  assert.deepEqual(D.parseDeepLink(path.slice(path.indexOf("?"))), { model: VEO, kind: "video", prompt: null });
});

test("возврат после входа: модели ещё нет или id негодный — только вид", () => {
  assert.equal(D.signInReturnPath("/video-studio", null, { kind: "image", model: null }), "/video-studio?kind=image");
  assert.equal(D.signInReturnPath("/video-studio", null, { kind: "video", model: "<script>" }), "/video-studio?kind=video");
});

test("возврат после входа: путь длиннее предела страницы входа — без выбора, но в студию", () => {
  // 128 знаков «:» проходят белый список id, а в адресе каждый — три знака.
  assert.equal(D.signInReturnPath("/video-studio", null, { kind: "video", model: ":".repeat(128) }), "/video-studio");
});

/* ---------- применение к панели запроса ---------- */

/** Стор с моделями и выбранной Seedance 2.0; dispatch идёт через настоящий редьюсер. */
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
    get composer() {
      return state.composer;
    },
    open: (search) => D.applyDeepLink(D.parseDeepLink(search), () => state, dispatch),
  };
}

const typed = (text) => ({ type: "composer/doc", doc: { v: 1, blocks: [[{ t: "text", v: text }]] } });

test("ссылка на модель: выбирается она, параметры — её собственные", () => {
  const s = studio();
  s.open(`?model=${VEO}`);
  assert.equal(s.composer.kind, "video");
  assert.equal(s.composer.model, VEO);
  assert.ok([4, 6, 8].includes(s.composer.params.duration), "длительность — из тех, что умеет Veo");
  assert.equal(plainText(s.composer.doc), "");
});

test("ссылка на картинку при выбранном видео: вид и модель переключаются", () => {
  const s = studio();
  s.open(`?model=${FLUX}`);
  assert.equal(s.composer.kind, "image");
  assert.equal(s.composer.model, FLUX);
  assert.equal(s.composer.params.duration, undefined, "у картинки нет длительности");
});

test("модель главнее вида: «видео-модель, kind=image» открывает модель", () => {
  const s = studio();
  s.open(`?model=${VEO}&kind=image`);
  assert.equal(s.composer.kind, "video");
  assert.equal(s.composer.model, VEO);
});

test("только вид: переключается вкладка, модель вида выбирает стор", () => {
  const s = studio();
  s.open("?kind=image");
  assert.equal(s.composer.kind, "image");
  assert.ok(FIXTURE_MODELS.image.some((m) => m.id === s.composer.model));
});

test("неизвестная модель: остаётся прежняя, вид из ссылки всё равно применяется", () => {
  const s = studio();
  s.open("?model=retired/model");
  assert.equal(s.composer.model, SEEDANCE);
  assert.deepEqual(s.log, []);
  s.open("?model=retired/model&kind=image");
  assert.equal(s.composer.kind, "image");
});

test("та же модель, что уже выбрана: стор не трогаем", () => {
  const s = studio();
  s.open(`?model=${SEEDANCE}&kind=video`);
  assert.deepEqual(s.log, []);
});

test("модель под замком выбирается: о тарифе скажет кнопка запуска", () => {
  const s = studio();
  s.open(`?model=${KLING_LOCKED}`);
  assert.equal(s.composer.model, KLING_LOCKED);
});

test("текст ложится только в пустой запрос", () => {
  const empty = studio();
  empty.open(`?model=${VEO}&prompt=${encodeURIComponent("Ночной город\nпод дождём")}`);
  assert.equal(empty.composer.model, VEO);
  assert.equal(plainText(empty.composer.doc), "Ночной город\nпод дождём");
  assert.equal(empty.composer.doc.blocks.length, 2, "каждая строка — абзац");

  // Свой текст (или поднятый черновик гостя) дороже: модель из ссылки берём, текст — нет.
  const busy = studio([typed("мой сценарий")]);
  busy.open(`?model=${VEO}&prompt=chuzhoy`);
  assert.equal(busy.composer.model, VEO);
  assert.equal(plainText(busy.composer.doc), "мой сценарий");
  assert.ok(!busy.log.includes("composer/doc"));
});

test("текст из сотен строк остаётся валидным документом", () => {
  const s = studio();
  const lines = Array.from({ length: 400 }, (_, i) => `s${i}`).join("\n");
  s.open(`?prompt=${encodeURIComponent(lines)}`);
  assert.equal(isValidDoc(s.composer.doc), true);
  assert.equal(plainText(s.composer.doc), lines);
});

test("модели ещё не пришли: текст ложится, выбор не падает", () => {
  Sync.resetRunSettingsSync();
  let state = Store.createInitialState();
  const dispatch = (action) => {
    state = Store.reducer(state, action);
  };
  D.applyDeepLink(D.parseDeepLink(`?model=${VEO}&kind=image&prompt=hello`), () => state, dispatch);
  assert.equal(plainText(state.composer.doc), "hello");
  assert.equal(state.composer.kind, "video");
  assert.equal(state.composer.model, null);
});

test("гость выбрал модель и вошёл, не написав текста: после входа — она же, а не модель по умолчанию", () => {
  const guest = studio();
  guest.open(`?model=${VEO}`);
  const path = D.signInReturnPath("/video-studio", null, guest.composer);
  // Страница после входа открывается заново: стор с нуля, выбрана другая модель.
  const back = studio();
  assert.equal(back.composer.model, SEEDANCE);
  back.open(path.slice(path.indexOf("?")));
  assert.equal(back.composer.model, VEO);
  assert.equal(back.composer.kind, "video");
});
