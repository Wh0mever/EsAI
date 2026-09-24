// Видеостудия, правая панель: кэш моделей (hooks/useVStudioModels.ts) и жизненный
// цикл параметров (useRunSettingsSync.ts): выбор модели по умолчанию, настройки
// открытого проекта, память по видам и PATCH в Project.settings.
// Сеть — мок-сервер фикстур (lib/vstudio/fixtures.ts), наружу ничего не уходит.
// Запуск (Node 22.6+):
//   node --experimental-strip-types --test src/components/vstudio/settings/*.test.mjs
import "../../../lib/vstudio/nodeTsHooks.mjs";
import { test, beforeEach } from "node:test";
import assert from "node:assert/strict";

const session = new Map();
globalThis.window = {
  sessionStorage: {
    getItem: (k) => (session.has(k) ? session.get(k) : null),
    setItem: (k, v) => session.set(k, String(v)),
    removeItem: (k) => session.delete(k),
  },
  location: { origin: "https://esai.test", pathname: "/video-studio", search: "", hash: "", protocol: "https:", replace() {} },
  addEventListener() {},
  removeEventListener() {},
  dispatchEvent() {},
};

const api = await import("../../../lib/vstudio/api.ts");
const fx = await import("../../../lib/vstudio/fixtures.ts");
const models = await import("../hooks/useVStudioModels.ts");
const sync = await import("./useRunSettingsSync.ts");
const sm = await import("./settingsModel.ts");
const store = await import("../store.ts");

api.setFixturesMode(true);

const b64 = (o) => Buffer.from(JSON.stringify(o)).toString("base64url");
const token = (userId) => `${b64({ alg: "HS256" })}.${b64({ user_id: userId, exp: Math.floor(Date.now() / 1000) + 3600 })}.sig`;
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

let calls = [];
function freshBackend() {
  const m = fx.resetMockBackend({ latencyMs: 0 });
  const orig = m.fetch;
  m.fetch = (endpoint, method, body) => {
    calls.push({ endpoint, method, body });
    return orig(endpoint, method, body);
  };
  return m;
}

const M = structuredClone(fx.FIXTURE_MODELS);
const SEEDANCE = "bytedance/seedance-2.0";
const VEO = "google/veo-3.1-fast";
const NANO = "google/gemini-2.5-flash-image";
const NO_FRAMES = { first_frame: null, last_frame: null };

/** Мини-редьюсер композера: ровно те действия, что шлёт панель. */
function reduce(state, a) {
  const c = state.composer;
  switch (a.type) {
    case "composer/kind":
      return { ...state, composer: { ...c, kind: a.kind } };
    case "composer/model":
      return { ...state, composer: { ...c, model: a.model } };
    case "composer/params":
      return { ...state, composer: { ...c, params: { ...c.params, ...a.params } } };
    case "projects/upsert":
      return state.project?.uid === a.project.uid ? { ...state, project: a.project } : state;
    default:
      return state;
  }
}

function harness(initial) {
  let state = initial;
  const log = [];
  const dispatch = (a) => {
    log.push(a);
    state = reduce(state, a);
  };
  return { get state() { return state; }, set state(v) { state = v; }, log, dispatch };
}

const baseState = (over = {}) => ({
  models: M,
  project: null,
  mode: "on",
  available: true,
  composer: { kind: "video", model: null, params: {}, tray: [], frames: NO_FRAMES, doc: { v: 1, blocks: [[]] }, forkedFrom: null },
  ...over,
});

beforeEach(() => {
  calls = [];
  session.clear();
  freshBackend();
  models.resetVStudioModelsCache();
  sync.resetRunSettingsSync();
});

/* ---------- кэш моделей ---------- */

test("loadVStudioModels: один запрос на всех, кэш 10 минут, force и смена аккаунта", async () => {
  const modelCalls = () => calls.filter((c) => c.endpoint === "vstudio/models/").length;
  const [a, b] = await Promise.all([models.loadVStudioModels(), models.loadVStudioModels()]);
  assert.ok(a.ok && b.ok);
  assert.equal(modelCalls(), 1, "параллельные вызовы делят один запрос");
  assert.equal(a.data, b.data);
  assert.equal(models.peekVStudioModels(), a.data);

  const c = await models.loadVStudioModels();
  assert.equal(modelCalls(), 1, "свежий кэш — без запроса");
  assert.equal(c.data, a.data);

  await models.loadVStudioModels({ force: true });
  assert.equal(modelCalls(), 2, "force — мимо кэша");

  // Вошёл другой человек: у него свои замки и цены.
  session.set("tg_access", token(42));
  assert.equal(models.currentIdentity(), "u42");
  assert.equal(models.isGuest(), false);
  await models.loadVStudioModels();
  assert.equal(modelCalls(), 3);

  models.invalidateVStudioModels();
  await models.loadVStudioModels();
  assert.equal(modelCalls(), 4, "после invalidate — новый запрос");
  assert.equal(models.MODELS_TTL_MS, 10 * 60 * 1000);
});

test("currentIdentity / isGuest без токенов и с битым токеном", () => {
  assert.equal(models.currentIdentity(), "guest");
  assert.equal(models.isGuest(), true);
  session.set("tg_access", "not-a-jwt");
  assert.equal(models.currentIdentity(), "user");
});

/* ---------- действия панели ---------- */

test("selectModel: модель и параметры целиком, лишнее — явным undefined", () => {
  const h = harness(baseState({ composer: { ...baseState().composer, model: SEEDANCE, params: { duration: 12, aspect_ratio: "9:16", seed: 5, generate_audio: false } } }));
  const cur = () => ({ kind: h.state.composer.kind, model: h.state.composer.model, params: h.state.composer.params });
  sync.selectModel(h.dispatch, M, cur(), VEO);
  assert.deepEqual(h.log.map((a) => a.type), ["composer/model", "composer/params"]);
  const patch = h.log[1].params;
  assert.deepEqual(Object.keys(patch).sort(), [...sm.PARAM_KEYS].sort(), "все ключи — редьюсер мог сбросить параметры");
  assert.equal(patch.duration, 8);
  assert.equal(patch.aspect_ratio, "9:16");
  assert.equal(patch.generate_audio, false);
  assert.equal(patch.seed, 5);
  assert.equal(patch.negative_prompt, undefined);
  assert.equal(h.state.composer.model, VEO);
});

test("selectKind: «Картинка» и обратно возвращает ту же модель видео с её параметрами", () => {
  const h = harness(baseState({ composer: { ...baseState().composer, model: VEO, params: { duration: 6, aspect_ratio: "9:16", resolution: "1080p", generate_audio: true } } }));
  const cur = () => ({ kind: h.state.composer.kind, model: h.state.composer.model, params: h.state.composer.params });

  sync.selectKind(h.dispatch, M, cur(), "image");
  assert.deepEqual(h.log.map((a) => a.type), ["composer/kind", "composer/model", "composer/params"]);
  assert.equal(h.state.composer.kind, "image");
  assert.equal(h.state.composer.model, NANO);
  assert.deepEqual(sm.cleanParams(h.state.composer.params), { aspect_ratio: "9:16" }, "у картинки — только пропорция");

  sync.selectKind(h.dispatch, M, cur(), "video");
  assert.equal(h.state.composer.model, VEO);
  assert.deepEqual(sm.cleanParams(h.state.composer.params), { aspect_ratio: "9:16", duration: 6, resolution: "1080p", generate_audio: true });

  // Тот же вид — ничего не делаем.
  const n = h.log.length;
  sync.selectKind(h.dispatch, M, cur(), "video");
  assert.equal(h.log.length, n);
});

/* ---------- жизненный цикл ---------- */

test("syncRunSettings: пока моделей нет — ничего; потом выбирается первая доступная", () => {
  const h = harness(baseState({ models: null }));
  assert.equal(sync.syncRunSettings(h.state, h.dispatch), "idle");
  assert.equal(h.log.length, 0);

  h.state = { ...h.state, models: M };
  assert.equal(sync.syncRunSettings(h.state, h.dispatch), "selected");
  assert.equal(h.state.composer.model, SEEDANCE);
  assert.equal(h.state.composer.params.duration, 5);
  assert.equal(sync.syncRunSettings(h.state, h.dispatch), "synced", "второй проход — выбор в порядке");
  assert.equal(sync.getKindMemory().video.model, SEEDANCE);

  // Модель не того вида (например, после «Изменить» картинки) — выбирается заново.
  h.state = { ...h.state, composer: { ...h.state.composer, kind: "image" } };
  assert.equal(sync.syncRunSettings(h.state, h.dispatch), "selected");
  assert.equal(h.state.composer.model, NANO);
});

test("syncRunSettings: открыли проект — его настройки; изменения уходят одним PATCH", async () => {
  const created = await api.createProject({ title: "Кошка" });
  assert.ok(created.ok);
  const uid = created.data.uid;
  const withSettings = await api.updateProject(uid, {
    settings: { kind: "video", model: VEO, params: { duration: 6, aspect_ratio: "9:16", resolution: "720p", generate_audio: true }, note: "keep" },
  });
  assert.ok(withSettings.ok);

  const h = harness(baseState({ composer: { ...baseState().composer, model: SEEDANCE, params: { duration: 10 } } }));
  h.state = { ...h.state, project: withSettings.data };
  calls = [];

  assert.equal(sync.syncRunSettings(h.state, h.dispatch, { delayMs: 5 }), "restored");
  assert.equal(h.state.composer.model, VEO);
  assert.equal(h.state.composer.params.duration, 6);

  // Композер совпал с сохранённым — PATCH не нужен.
  assert.equal(sync.syncRunSettings(h.state, h.dispatch, { delayMs: 5 }), "synced");
  await sleep(30);
  assert.equal(calls.filter((c) => c.method === "PATCH").length, 0);

  // Человек щёлкает: 8 с → PATCH один, даже если хук позвали трижды (панель, чип, контейнер).
  h.dispatch({ type: "composer/params", params: { duration: 8 } });
  for (let i = 0; i < 3; i++) sync.syncRunSettings(h.state, h.dispatch, { delayMs: 5 });
  await sleep(40);
  const patches = calls.filter((c) => c.method === "PATCH");
  assert.equal(patches.length, 1);
  assert.equal(patches[0].endpoint, `vstudio/projects/${uid}/`);
  assert.equal(patches[0].body.settings.params.duration, 8);
  assert.equal(patches[0].body.settings.note, "keep", "чужие ключи настроек не теряются");
  assert.equal(patches[0].body.settings.by_kind.video.model, VEO);
  const upsert = h.log.find((a) => a.type === "projects/upsert");
  assert.equal(upsert.project.settings.params.duration, 8);

  // Повтор с тем же содержимым — тишина; туда-обратно до отправки — тоже.
  sync.syncRunSettings(h.state, h.dispatch, { delayMs: 5 });
  h.dispatch({ type: "composer/params", params: { duration: 4 } });
  sync.syncRunSettings(h.state, h.dispatch, { delayMs: 20 });
  h.dispatch({ type: "composer/params", params: { duration: 8 } });
  sync.syncRunSettings(h.state, h.dispatch, { delayMs: 20 });
  await sleep(60);
  assert.equal(calls.filter((c) => c.method === "PATCH").length, 1);

  const stored = await api.getProject(uid);
  assert.equal(stored.data.settings.params.duration, 8);

  // Другая вкладка поставила 10 с, проект перечитали, а здесь на экране 8 с — отправляем 8.
  const other = await api.updateProject(uid, { settings: { ...stored.data.settings, params: { ...stored.data.settings.params, duration: 10 } } });
  h.state = { ...h.state, project: other.data };
  calls = [];
  sync.syncRunSettings(h.state, h.dispatch, { delayMs: 5 });
  await sleep(30);
  const again = calls.filter((c) => c.method === "PATCH");
  assert.equal(again.length, 1, "свежие настройки с сервера главнее памяти о прошлом PATCH");
  assert.equal(again[0].body.settings.params.duration, 8);
});

test("syncRunSettings: проект без настроек — остаётся выбор из этой вкладки", async () => {
  const h = harness(baseState());
  sync.syncRunSettings(h.state, h.dispatch);
  sync.selectModel(h.dispatch, M, { kind: "video", model: h.state.composer.model, params: h.state.composer.params }, VEO);
  sync.syncRunSettings(h.state, h.dispatch);

  // Первый запуск создал проект с пустыми настройками; оболочка могла пересоздать стор.
  const created = await api.createProject({});
  const fresh = harness(baseState({ project: created.data }));
  assert.equal(sync.syncRunSettings(fresh.state, fresh.dispatch, { delayMs: 5 }), "selected");
  assert.equal(fresh.state.composer.model, VEO, "последний выбор во вкладке, а не первая модель списка");
});

test("syncRunSettings: гость и закрытая студия — ничего не сохраняется", async () => {
  const created = await api.createProject({});
  for (const over of [{ available: false }, { mode: "off" }]) {
    sync.resetRunSettingsSync();
    const h = harness(baseState({ project: created.data, ...over }));
    sync.syncRunSettings(h.state, h.dispatch, { delayMs: 1 });
    sync.syncRunSettings(h.state, h.dispatch, { delayMs: 1 });
    await sleep(15);
  }
  assert.equal(calls.filter((c) => c.method === "PATCH").length, 0);
});

test("claimSyncRun: одно состояние — один прогон на стор (панель, чип и контейнер)", () => {
  const storeA = () => {};
  const storeB = () => {};
  assert.equal(sync.claimSyncRun(storeA, "s1"), true);
  assert.equal(sync.claimSyncRun(storeA, "s1"), false, "второй экземпляр хука в том же коммите молчит");
  assert.equal(sync.claimSyncRun(storeB, "s1"), true, "у другого стора — свой счёт");
  assert.equal(sync.claimSyncRun(storeA, "s2"), true, "состояние изменилось — снова работаем");
  assert.equal(sync.claimSyncRun(storeA, "s1"), true, "вернулись к прежнему — это новое изменение");
  sync.resetRunSettingsSync();
  assert.equal(sync.claimSyncRun(storeA, "s1"), true);
});

/* ---------- вместе с настоящим редьюсером студии (store.ts, FE-1) ---------- */

function realHarness(initial) {
  let state = initial;
  const log = [];
  const dispatch = (a) => {
    log.push(a);
    state = store.reducer(state, a);
  };
  return { get state() { return state; }, set state(v) { state = v; }, log, dispatch };
}
const current = (s) => ({ kind: s.composer.kind, model: s.composer.model, params: s.composer.params });

test("с редьюсером студии: смена модели и вида даёт ровно выбор панели", () => {
  const h = realHarness(store.createInitialState());
  h.dispatch({ type: "models/loaded", payload: M });
  // Модель по умолчанию уже поставил редьюсер — синхронизации выбирать нечего.
  assert.equal(h.state.composer.model, SEEDANCE);
  assert.equal(sync.syncRunSettings(h.state, h.dispatch), "synced");

  h.dispatch({ type: "composer/params", params: { duration: 12, aspect_ratio: "9:16", generate_audio: false, seed: 5 } });
  sync.selectModel(h.dispatch, h.state.models, current(h.state), VEO);
  assert.equal(h.state.composer.model, VEO);
  assert.deepEqual(
    sm.cleanParams(h.state.composer.params),
    sm.cleanParams(sm.normalizeParams(sm.findModel(M, VEO), "video", { duration: 12, aspect_ratio: "9:16", generate_audio: false, seed: 5 })),
  );
  assert.equal(h.state.composer.params.duration, 8, "12 с у Veo нет — ближайшее, 8");
  assert.equal(h.state.composer.params.generate_audio, false, "выключенный звук не включился сам");

  sync.selectKind(h.dispatch, h.state.models, current(h.state), "image");
  assert.equal(h.state.composer.kind, "image");
  assert.equal(h.state.composer.model, NANO);
  assert.deepEqual(sm.cleanParams(h.state.composer.params), { aspect_ratio: "9:16" });

  sync.selectKind(h.dispatch, h.state.models, current(h.state), "video");
  assert.equal(h.state.composer.model, VEO, "вернулись к той же модели видео");
  assert.equal(h.state.composer.params.duration, 8);
});

test("недонабранный seed/негатив входит в выбор новой модели, а не догоняет его", () => {
  const h = realHarness(store.createInitialState());
  h.dispatch({ type: "models/loaded", payload: M });
  let pending = { seed: 42 };
  const unregister = sync.registerParamsDraft(() => {
    const d = pending;
    pending = null;
    return d;
  });
  try {
    sync.selectModel(h.dispatch, h.state.models, current(h.state), VEO);
    assert.equal(h.state.composer.model, VEO);
    assert.equal(h.state.composer.params.seed, 42, "seed набран у Seedance и переехал в Veo");
    assert.equal(sync.takeParamsDraft(), null, "черновик забран один раз");

    // Негатив у Veo → Seedance негатива не понимает: в параметры он не попадает.
    pending = { negative_prompt: "blur" };
    sync.selectModel(h.dispatch, h.state.models, current(h.state), SEEDANCE);
    assert.equal(h.state.composer.params.negative_prompt, undefined);

    // Тот же вид — черновик не трогаем (смены нет).
    pending = { seed: 7 };
    sync.selectKind(h.dispatch, h.state.models, current(h.state), "video");
    assert.deepEqual(pending, { seed: 7 });
  } finally {
    unregister();
  }
  assert.equal(sync.takeParamsDraft(), null);
});

test("с редьюсером студии: проект открыт — его настройки и память по видам (by_kind)", async () => {
  const created = await api.createProject({ title: "Реклама" });
  const saved = await api.updateProject(created.data.uid, {
    settings: {
      kind: "video",
      model: VEO,
      params: { duration: 6, aspect_ratio: "9:16", resolution: "1080p", generate_audio: true },
      by_kind: { image: { model: "black-forest-labs/flux.2-flex", params: { aspect_ratio: "4:5" } } },
    },
  });
  const h = realHarness(store.createInitialState());
  h.dispatch({ type: "models/loaded", payload: M });
  h.dispatch({ type: "project/set", project: saved.data });
  calls = [];

  sync.syncRunSettings(h.state, h.dispatch, { delayMs: 5 });
  assert.equal(h.state.composer.model, VEO);
  assert.equal(h.state.composer.params.duration, 6);
  assert.equal(h.state.composer.params.resolution, "1080p");
  // Настройки совпали с сохранёнными — PATCH не нужен.
  sync.syncRunSettings(h.state, h.dispatch, { delayMs: 5 });
  await sleep(20);
  assert.equal(calls.filter((c) => c.method === "PATCH").length, 0);

  // «Картинка» — модель картинок из памяти проекта, а не первая в списке.
  sync.selectKind(h.dispatch, h.state.models, current(h.state), "image");
  assert.equal(h.state.composer.model, "black-forest-labs/flux.2-flex");
  assert.equal(h.state.composer.params.aspect_ratio, "4:5");
  sync.syncRunSettings(h.state, h.dispatch, { delayMs: 5 });
  await sleep(30);
  const patches = calls.filter((c) => c.method === "PATCH");
  assert.equal(patches.length, 1);
  assert.equal(patches[0].body.settings.kind, "image");
  assert.equal(patches[0].body.settings.by_kind.video.model, VEO, "видео-выбор проекта не потерялся");
  assert.equal(h.state.project.settings.kind, "image", "ответ PATCH попал в стор");
});

test("scheduleSettingsSave: ошибка сервера не ломает следующее сохранение", async () => {
  const created = await api.createProject({});
  const uid = created.data.uid;
  const bad = "f".repeat(32); // такого проекта нет — 404
  sync.scheduleSettingsSave(bad, { kind: "video", model: VEO, params: { duration: 4 } }, undefined, 1);
  sync.scheduleSettingsSave(uid, { kind: "video", model: VEO, params: { duration: 4 } }, undefined, 1);
  await sleep(20);
  assert.equal((await api.getProject(uid)).data.settings.params.duration, 4);
  assert.equal(calls.filter((c) => c.method === "PATCH").length, 2);
});
