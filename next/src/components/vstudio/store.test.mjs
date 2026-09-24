// Видеостудия: редьюсер стора (components/vstudio/store.ts) — модели и
// параметры, лента и дубли, лоток и кадры, запуск, библиотека, интерфейс.
// Запуск (Node 22.6+):  node --experimental-strip-types --test src/components/vstudio/store.test.mjs
import "../../lib/vstudio/nodeTsHooks.mjs";
import { test } from "node:test";
import assert from "node:assert/strict";

const S = await import("./store.ts");
const fx = await import("../../lib/vstudio/fixtures.ts");

const { reducer, createInitialState } = S;
const U = (n) => n.toString(16).padStart(32, "0");
const MODELS = fx.FIXTURE_MODELS;

/** Цепочка действий от начального состояния. */
function run(actions, state = createInitialState()) {
  return actions.reduce((s, a) => reducer(s, a), state);
}

const loaded = () => run([{ type: "models/loaded", payload: MODELS }]);

function project(n, extra = {}) {
  return {
    uid: U(n),
    title: `Проект ${n}`,
    kind: "playground",
    settings: {},
    is_archived: false,
    last_activity_at: new Date(Date.UTC(2026, 8, 24, 10, n)).toISOString(),
    thumb_url: null,
    open_takes: 0,
    ...extra,
  };
}

function take(n, shot, status, extra = {}) {
  return fx.fixtureTake(status, { uid: U(n), shot, created_at: new Date(Date.UTC(2026, 8, 24, 10, 0, n)).toISOString(), ...extra });
}

function shot(n, projectUid, takes = [], extra = {}) {
  return {
    uid: U(n),
    project: projectUid,
    kind: "video",
    origin: "composer",
    model: { id: "bytedance/seedance-2.0", name: "Seedance 2.0" },
    prompt_doc: { v: 1, blocks: [[{ t: "text", v: `кадр ${n}` }]] },
    prompt_text: `кадр ${n}`,
    params: { duration: 5 },
    inputs: [],
    forked_from: null,
    created_at: new Date(Date.UTC(2026, 8, 24, 9, n)).toISOString(),
    takes,
    ...extra,
  };
}

function chip(lid, extra = {}) {
  return { lid, slot: "reference", role: "", included: true, status: "ready", progress: 100, preview: null, ...extra };
}

/* ------------------------------------------------------------------ */
/* Начальное состояние и модели                                        */
/* ------------------------------------------------------------------ */

test("начальное состояние: пустая лента, скелетон страницы, модель не выбрана", () => {
  const s = createInitialState();
  assert.equal(s.ui.page, "loading");
  assert.equal(s.composer.model, null);
  assert.equal(s.composer.kind, "video");
  assert.deepEqual(s.composer.doc, { v: 1, blocks: [[]] });
  assert.equal(s.shots.size, 0);
  assert.deepEqual(s.ui.panels, { rail: false, settings: false, library: false, picker: false });
});

test("models/loaded: первая доступная модель вида и её параметры по умолчанию", () => {
  const s = loaded();
  assert.equal(s.mode, "on");
  assert.equal(s.available, true);
  assert.equal(s.composer.model, "bytedance/seedance-2.0");
  assert.deepEqual(s.composer.params, { aspect_ratio: "16:9", duration: 5, resolution: "720p" });
});

test("models/loaded: заблокированная по тарифу модель по умолчанию не выбирается", () => {
  const payload = { ...MODELS, video: MODELS.video.map((m, i) => (i < 2 ? { ...m, locked: true } : m)) };
  const s = run([{ type: "models/loaded", payload }]);
  assert.equal(s.composer.model, "google/veo-3.1-fast");
  assert.equal(s.composer.params.duration, 8);
});

test("createInitialState(seed): модели из памяти вкладки сразу дают модель композера", () => {
  const s = createInitialState({ mode: "on", available: true, models: { video: MODELS.video, image: MODELS.image } });
  assert.equal(s.composer.model, "bytedance/seedance-2.0");
  assert.equal(s.ui.page, "loading");
});

test("composer/model: значение, которого у модели нет, — ближайшее разрешённое", () => {
  let s = loaded();
  s = reducer(s, {
    type: "composer/params",
    params: { duration: 10, aspect_ratio: "9:16", resolution: "1080p", generate_audio: false, seed: 42 },
  });
  // Veo: 4/6/8 с, 720p/1080p, 16:9 и 9:16, звук и seed есть.
  s = reducer(s, { type: "composer/model", model: "google/veo-3.1-fast" });
  assert.deepEqual(s.composer.params, {
    aspect_ratio: "9:16",
    duration: 8,
    resolution: "1080p",
    generate_audio: false,
    seed: 42,
  });
  // Kling: только 720p, seed не принимает.
  s = reducer(s, { type: "composer/model", model: "kwaivgi/kling-v3.0-std" });
  assert.equal(s.composer.params.resolution, "720p");
  assert.equal(s.composer.params.seed, undefined);
  assert.equal(s.composer.params.aspect_ratio, "9:16");
  assert.equal(s.composer.params.duration, 10);
});

test("composer/model: «Авто» пропорция допустима у любой модели", () => {
  let s = loaded();
  s = reducer(s, { type: "composer/params", params: { aspect_ratio: "auto" } });
  s = reducer(s, { type: "composer/model", model: "google/veo-3.1-fast" });
  assert.equal(s.composer.params.aspect_ratio, "auto");
});

test("composer/model: картинка переключает вид, у картинки нет длительности и звука", () => {
  let s = loaded();
  s = reducer(s, { type: "composer/params", params: { duration: 10, generate_audio: true, aspect_ratio: "21:9" } });
  s = reducer(s, { type: "composer/model", model: "google/gemini-2.5-flash-image" });
  assert.equal(s.composer.kind, "image");
  assert.deepEqual(s.composer.params, { aspect_ratio: "1:1" });
});

test("composer/kind: модель по умолчанию нужного вида; неизвестный id модели сохраняется до загрузки моделей", () => {
  let s = loaded();
  s = reducer(s, { type: "composer/kind", kind: "image" });
  assert.equal(s.composer.kind, "image");
  assert.equal(s.composer.model, "google/gemini-2.5-flash-image");
  s = reducer(s, { type: "composer/kind", kind: "video" });
  assert.equal(s.composer.model, "bytedance/seedance-2.0");
  const noModels = reducer(createInitialState(), { type: "composer/model", model: "x/y" });
  assert.equal(noModels.composer.model, "x/y");
});

test("composer/kind: вид без моделей не включается", () => {
  const payload = { ...MODELS, image: [] };
  let s = run([{ type: "models/loaded", payload }]);
  const before = s;
  s = reducer(s, { type: "composer/kind", kind: "image" });
  assert.equal(s, before);
});

test("composer/params: undefined убирает ключ", () => {
  let s = loaded();
  s = reducer(s, { type: "composer/params", params: { seed: 7 } });
  assert.equal(s.composer.params.seed, 7);
  s = reducer(s, { type: "composer/params", params: { seed: undefined } });
  assert.equal("seed" in s.composer.params, false);
});

/* ------------------------------------------------------------------ */
/* Проекты                                                             */
/* ------------------------------------------------------------------ */

test("projects/loaded: замена и дозагрузка без дублей, архивные не попадают", () => {
  let s = createInitialState();
  s = reducer(s, { type: "projects/loading" });
  assert.equal(s.projects.loading, true);
  s = reducer(s, { type: "projects/loaded", page: { items: [project(3), project(2)], next: "cur" }, append: false });
  assert.deepEqual(s.projects.items.map((p) => p.uid), [U(3), U(2)]);
  assert.equal(s.projects.next, "cur");
  assert.equal(s.projects.loaded, true);
  s = reducer(s, {
    type: "projects/loaded",
    page: { items: [project(2), project(1), project(9, { is_archived: true })], next: null },
    append: true,
  });
  assert.deepEqual(s.projects.items.map((p) => p.uid), [U(3), U(2), U(1)]);
  assert.equal(s.projects.next, null);
});

test("projects/upsert: новая активность — наверх; в архив — из списка; при поиске чужое не добавляется", () => {
  let s = run([{ type: "projects/loaded", page: { items: [project(3), project(2)], next: null }, append: false }]);
  s = reducer(s, { type: "projects/upsert", project: project(2, { last_activity_at: "2026-09-24T12:00:00.000Z" }) });
  assert.deepEqual(s.projects.items.map((p) => p.uid), [U(2), U(3)]);
  s = reducer(s, { type: "projects/upsert", project: project(3, { is_archived: true }) });
  assert.deepEqual(s.projects.items.map((p) => p.uid), [U(2)]);
  s = reducer(s, { type: "projects/query", q: "кошка" });
  assert.equal(s.projects.q, "кошка");
  assert.equal(s.projects.loading, true);
  s = reducer(s, { type: "projects/upsert", project: project(7, { title: "Собака" }) });
  assert.equal(s.projects.items.some((p) => p.uid === U(7)), false);
  s = reducer(s, { type: "projects/upsert", project: project(8, { title: "Кошка на крыше" }) });
  assert.equal(s.projects.items.some((p) => p.uid === U(8)), true);
});

test("projects/upsert обновляет и открытый проект; projects/remove убирает строку", () => {
  let s = run([
    { type: "projects/loaded", page: { items: [project(1)], next: null }, append: false },
    { type: "project/set", project: project(1) },
  ]);
  s = reducer(s, { type: "projects/upsert", project: project(1, { title: "Новое имя" }) });
  assert.equal(s.project.title, "Новое имя");
  s = reducer(s, { type: "projects/remove", uid: U(1) });
  assert.equal(s.projects.items.length, 0);
});

test("groupProjects: Сегодня / Вчера / Раньше по местной дате", () => {
  const now = new Date(2026, 8, 24, 15, 0);
  const at = (d, h) => new Date(2026, 8, d, h, 0).toISOString();
  const g = S.groupProjects(
    [project(1, { last_activity_at: at(24, 1) }), project(2, { last_activity_at: at(23, 23) }), project(3, { last_activity_at: at(20, 9) }), project(4, { last_activity_at: "кривая дата" })],
    now,
  );
  assert.deepEqual(g.today.map((p) => p.uid), [U(1)]);
  assert.deepEqual(g.yesterday.map((p) => p.uid), [U(2)]);
  assert.deepEqual(g.earlier.map((p) => p.uid), [U(3), U(4)]);
});

test("project/set: смена проекта очищает ленту, открытые дубли остаются, параметры — из настроек проекта", () => {
  const p1 = project(1);
  let s = run([{ type: "models/loaded", payload: MODELS }, { type: "project/set", project: p1 }]);
  s = reducer(s, {
    type: "feed/loaded",
    page: { items: [shot(10, p1.uid, [take(20, U(10), "running"), take(21, U(10), "done")])], next: null },
    older: false,
  });
  assert.equal(s.order.length, 1);
  const p2 = project(2, { settings: { kind: "video", model: "google/veo-3.1-fast", params: { duration: 6, aspect_ratio: "9:16" } } });
  s = reducer(s, { type: "project/set", project: p2 });
  assert.equal(s.project.uid, p2.uid);
  assert.equal(s.shots.size, 0);
  assert.deepEqual(s.order, []);
  assert.equal(s.feed.loaded, false);
  // Опрос открытого дубля из прошлого проекта не должен пропасть.
  assert.deepEqual([...s.takes.keys()], [U(20)]);
  assert.equal(s.composer.model, "google/veo-3.1-fast");
  assert.equal(s.composer.params.duration, 6);
  assert.equal(s.composer.params.aspect_ratio, "9:16");
  // Тот же uid — только обновление объекта, лента не трогается.
  const same = reducer(s, { type: "project/set", project: { ...p2, title: "x" } });
  assert.equal(same.project.title, "x");
  assert.equal(same.takes, s.takes);
});

test("project/set: модель из настроек проекта, которой уже нет, заменяется моделью по умолчанию", () => {
  const p = project(1, { settings: { kind: "video", model: "gone/model", params: { duration: 99 } } });
  const s = run([{ type: "models/loaded", payload: MODELS }, { type: "project/set", project: p }]);
  assert.equal(s.composer.model, "bytedance/seedance-2.0");
  assert.equal(s.composer.params.duration, 15);
});

/* ------------------------------------------------------------------ */
/* Лента и дубли                                                       */
/* ------------------------------------------------------------------ */

test("feed/loaded: чужой проект выбрасывается, порядок — по времени, «показать раньше» ставит курсор", () => {
  const p = project(1);
  let s = run([{ type: "project/set", project: p }, { type: "feed/loading" }]);
  assert.equal(s.feed.loading, true);
  s = reducer(s, {
    type: "feed/loaded",
    page: { items: [shot(12, p.uid), shot(11, p.uid), shot(99, U(2))], next: U(11) },
    older: false,
  });
  assert.deepEqual(s.order, [U(11), U(12)]);
  assert.equal(s.shots.has(U(99)), false);
  assert.equal(s.feed.next, U(11));
  assert.equal(s.feed.loaded, true);
  s = reducer(s, { type: "feed/loaded", page: { items: [shot(5, p.uid)], next: null }, older: true });
  assert.deepEqual(s.order, [U(5), U(11), U(12)]);
  assert.equal(s.feed.next, null);
  assert.deepEqual(S.feedShots(s).map((x) => x.uid), [U(5), U(11), U(12)]);
});

test("feed/loaded без открытого проекта (ушли в новую сессию) — ничего не добавляет", () => {
  const s = reducer(createInitialState(), {
    type: "feed/loaded",
    page: { items: [shot(1, U(1))], next: null },
    older: false,
  });
  assert.equal(s.shots.size, 0);
  assert.equal(s.feed.loading, false);
});

test("mergeTake: статус не откатывается назад; lost → done («Довезти») разрешён", () => {
  const running = take(1, U(9), "running");
  const done = take(1, U(9), "done");
  assert.equal(S.mergeTake(done, running), done);
  assert.equal(S.mergeTake(running, done), done);
  const lost = take(1, U(9), "lost");
  assert.equal(S.mergeTake(lost, done), done);
  assert.equal(S.mergeTake(undefined, running), running);
});

test("takes/upsert: устаревший ответ ленты не возвращает «Снимается»; карточка кадра видит новый статус", () => {
  const p = project(1);
  let s = run([
    { type: "project/set", project: p },
    { type: "feed/loaded", page: { items: [shot(10, p.uid, [take(20, U(10), "running")])], next: null }, older: false },
  ]);
  s = reducer(s, { type: "takes/upsert", takes: [take(20, U(10), "done")] });
  assert.equal(s.takes.get(U(20)).status, "done");
  assert.equal(s.shots.get(U(10)).takes[0].status, "done");
  // Опоздавший ответ ленты с running.
  s = reducer(s, { type: "shot/upsert", shot: shot(10, p.uid, [take(20, U(10), "running")]) });
  assert.equal(s.takes.get(U(20)).status, "done");
  assert.equal(s.shots.get(U(10)).takes[0].status, "done");
  assert.equal(reducer(s, { type: "takes/upsert", takes: [] }), s);
});

test("take/added: новый дубль (Повторить) — в карту и в карусель кадра", () => {
  const p = project(1);
  let s = run([
    { type: "project/set", project: p },
    { type: "feed/loaded", page: { items: [shot(10, p.uid, [take(20, U(10), "done")])], next: null }, older: false },
  ]);
  s = reducer(s, { type: "take/added", shot: U(10), take: take(21, U(10), "queued") });
  assert.deepEqual(s.shots.get(U(10)).takes.map((t) => t.uid), [U(20), U(21)]);
  assert.deepEqual(S.openTakeUids(s), [U(21)]);
  assert.equal(S.studioReserved(s), 164);
});

test("reservedNow: «ждут результата» = резерв сервера + поправка на дубли, закрывшиеся или появившиеся после quote", () => {
  const p = project(1);
  let s = run([
    { type: "project/set", project: p },
    {
      type: "feed/loaded",
      page: { items: [shot(10, p.uid, [take(20, U(10), "running"), take(21, U(10), "queued")])], next: null },
      older: false,
    },
  ]);
  const local = S.studioReserved(s);
  assert.equal(local, 328);
  // quote сказал: в резерве 400 (ещё 72 — видео чата), дубли вкладки держали 328.
  const snap = { balance: 1200, reserved: 400, local };
  assert.equal(S.reservedNow(snap, S.studioReserved(s)), 400);
  // Один дубль выдан и списан — его резерв ушёл, видео чата осталось.
  s = reducer(s, { type: "takes/upsert", takes: [take(20, U(10), "done", { charge_state: "charged" })] });
  assert.deepEqual(S.openTakeUids(s), [U(21)]);
  assert.equal(S.reservedNow(snap, S.studioReserved(s)), 236);
  // Отменённый дубль тоже не держит резерв; ниже нуля число не уходит.
  s = reducer(s, { type: "takes/upsert", takes: [take(21, U(10), "canceled", { charge_state: "released" })] });
  assert.equal(S.studioReserved(s), 0);
  assert.equal(S.reservedNow(snap, 0), 72);
  assert.equal(S.reservedNow({ balance: 0, reserved: 10, local: 328 }, 0), 0);
  // Ответа сервера ещё не было — только то, что видит вкладка.
  assert.equal(S.reservedNow(null, 164), 164);
  assert.equal(S.reservedNow(null, -5), 0);
});

test("shot/upsert: кадр чужого проекта не попадает в ленту", () => {
  const s = run([{ type: "project/set", project: project(1) }, { type: "shot/upsert", shot: shot(10, U(2)) }]);
  assert.equal(s.shots.size, 0);
});

/* ------------------------------------------------------------------ */
/* Композер, лоток и кадры                                             */
/* ------------------------------------------------------------------ */

test("tray/add: без дублей по (слот, ассет); позиция at; кадр — в свой слот", () => {
  let s = loaded();
  s = reducer(s, { type: "tray/add", item: chip("a", { assetUid: U(1) }) });
  s = reducer(s, { type: "tray/add", item: chip("b", { assetUid: U(2) }) });
  s = reducer(s, { type: "tray/add", item: chip("c", { assetUid: U(3) }), at: 0 });
  assert.deepEqual(s.composer.tray.map((i) => i.lid), ["c", "a", "b"]);
  const same = reducer(s, { type: "tray/add", item: chip("d", { assetUid: U(1) }) });
  assert.equal(same, s);
  s = reducer(s, { type: "tray/add", item: chip("f", { assetUid: U(4), slot: "first_frame" }) });
  assert.equal(s.composer.frames.first_frame.lid, "f");
  // Новый первый кадр заменяет прежний.
  s = reducer(s, { type: "tray/add", item: chip("g", { assetUid: U(5), slot: "first_frame" }) });
  assert.equal(s.composer.frames.first_frame.lid, "g");
  assert.equal(s.composer.tray.length, 3);
});

test("tray/move: перестановка меняет порядок (а с ним номера @Image N)", () => {
  let s = loaded();
  for (const [lid, n] of [["a", 1], ["b", 2], ["c", 3]]) s = reducer(s, { type: "tray/add", item: chip(lid, { assetUid: U(n) }) });
  s = reducer(s, { type: "tray/move", lid: "c", to: 0 });
  assert.deepEqual(s.composer.tray.map((i) => i.lid), ["c", "a", "b"]);
  s = reducer(s, { type: "tray/move", lid: "c", to: 99 });
  assert.deepEqual(s.composer.tray.map((i) => i.lid), ["a", "b", "c"]);
  assert.equal(reducer(s, { type: "tray/move", lid: "zzz", to: 0 }), s);
});

test("tray/slot: референс → первый кадр (занятый кадр встаёт на его место), кадр → референс в конец", () => {
  let s = loaded();
  for (const [lid, n] of [["a", 1], ["b", 2], ["c", 3]]) s = reducer(s, { type: "tray/add", item: chip(lid, { assetUid: U(n) }) });
  s = reducer(s, { type: "tray/slot", lid: "b", slot: "first_frame" });
  assert.deepEqual(s.composer.tray.map((i) => i.lid), ["a", "c"]);
  assert.equal(s.composer.frames.first_frame.lid, "b");
  assert.equal(s.composer.frames.first_frame.slot, "first_frame");
  s = reducer(s, { type: "tray/slot", lid: "a", slot: "first_frame" });
  assert.deepEqual(s.composer.tray.map((i) => i.lid), ["b", "c"]);
  assert.equal(s.composer.tray[0].slot, "reference");
  assert.equal(s.composer.frames.first_frame.lid, "a");
  // Первый → последний кадр.
  s = reducer(s, { type: "tray/slot", lid: "a", slot: "last_frame" });
  assert.equal(s.composer.frames.first_frame, null);
  assert.equal(s.composer.frames.last_frame.lid, "a");
  // Кадр → референс.
  s = reducer(s, { type: "tray/slot", lid: "a", slot: "reference" });
  assert.equal(s.composer.frames.last_frame, null);
  assert.deepEqual(s.composer.tray.map((i) => i.lid), ["b", "c", "a"]);
});

test("tray/include, tray/role (≤60 символов), tray/update, tray/remove — и в лотке, и в кадрах", () => {
  let s = loaded();
  s = reducer(s, { type: "tray/add", item: chip("a", { assetUid: U(1) }) });
  s = reducer(s, { type: "tray/add", item: chip("f", { assetUid: U(2), slot: "first_frame" }) });
  s = reducer(s, { type: "tray/include", lids: ["a", "f"], included: false });
  assert.equal(s.composer.tray[0].included, false);
  assert.equal(s.composer.frames.first_frame.included, false);
  s = reducer(s, { type: "tray/role", lid: "a", role: "г".repeat(80) });
  assert.equal(s.composer.tray[0].role.length, 60);
  s = reducer(s, { type: "tray/update", lid: "f", patch: { status: "failed", errorCode: "bad_image", slot: "reference" } });
  assert.equal(s.composer.frames.first_frame.status, "failed");
  assert.equal(s.composer.frames.first_frame.slot, "first_frame", "слот меняется только через tray/slot");
  s = reducer(s, { type: "tray/remove", lid: "f" });
  assert.equal(s.composer.frames.first_frame, null);
  s = reducer(s, { type: "tray/remove", lid: "a" });
  assert.equal(s.composer.tray.length, 0);
});

test("takes/upsert: готовая картинка из «Создать картинку» превращает чип «создаётся» в обычный", () => {
  const pendingAsset = fx.fixtureAsset({ uid: U(50), status: "pending", url: null, thumb_url: null, source: "generated_image" });
  let s = run([{ type: "models/loaded", payload: MODELS }, { type: "library/loaded", page: { items: [], next: null }, append: false }]);
  s = reducer(s, { type: "tray/add", item: chip("gen", { assetUid: U(50), status: "pending", asset: pendingAsset }) });
  const ready = fx.fixtureAsset({ uid: U(50), status: "ready", source: "generated_image", thumb_url: "/t.jpg", url: "/f.jpg" });
  s = reducer(s, { type: "takes/upsert", takes: [take(60, U(70), "done", { kind: "image", result: ready })] });
  const item = s.composer.tray[0];
  assert.equal(item.status, "ready");
  assert.equal(item.preview, "/t.jpg");
  assert.equal(item.asset.status, "ready");
  assert.equal(s.library.items[0].uid, U(50));
  // Не удалось — чип красный с причиной.
  const failed = fx.fixtureAsset({ uid: U(51), status: "failed", error_code: "prompt_rejected", source: "generated_image" });
  s = reducer(s, { type: "tray/add", item: chip("gen2", { assetUid: U(51), status: "pending" }) });
  s = reducer(s, { type: "takes/upsert", takes: [take(61, U(70), "failed", { kind: "image", result: failed })] });
  const f = s.composer.tray.find((i) => i.lid === "gen2");
  assert.equal(f.status, "failed");
  assert.equal(f.errorCode, "prompt_rejected");
});

test("library/remove: удалённый материал в запросе — красный чип «удалён»", () => {
  let s = run([
    { type: "models/loaded", payload: MODELS },
    { type: "library/loaded", page: { items: [fx.fixtureAsset({ uid: U(1) })], next: null }, append: false },
    { type: "tray/add", item: chip("a", { assetUid: U(1) }) },
  ]);
  s = reducer(s, { type: "library/remove", uid: U(1) });
  assert.equal(s.library.items.length, 0);
  assert.equal(s.composer.tray[0].status, "deleted");
  // Готовая картинка не «воскрешает» удалённый чип.
  s = reducer(s, { type: "library/upsert", asset: fx.fixtureAsset({ uid: U(1) }) });
  assert.equal(s.composer.tray[0].status, "deleted");
});

test("library: фильтр сбрасывает список; upsert — только подходящее под фильтр", () => {
  let s = run([{ type: "library/loaded", page: { items: [fx.fixtureAsset({ uid: U(1) })], next: "c" }, append: false }]);
  s = reducer(s, { type: "library/filter", filter: "frames" });
  assert.equal(s.library.items.length, 0);
  assert.equal(s.library.loaded, false);
  s = reducer(s, { type: "library/loaded", page: { items: [], next: null }, append: false });
  s = reducer(s, { type: "library/upsert", asset: fx.fixtureAsset({ uid: U(2), source: "upload" }) });
  assert.equal(s.library.items.length, 0);
  s = reducer(s, { type: "library/upsert", asset: fx.fixtureAsset({ uid: U(3), source: "frame" }) });
  assert.deepEqual(s.library.items.map((a) => a.uid), [U(3)]);
});

test("composer/fill: «Изменить» — текст, параметры, лоток по порядку, кадры и forked_from", () => {
  const a1 = fx.fixtureAsset({ uid: U(1) });
  const a2 = fx.fixtureAsset({ uid: U(2), status: "failed", error_code: "bad_image" });
  const a3 = fx.fixtureAsset({ uid: U(3) });
  const sh = shot(10, U(1), [], {
    params: { duration: 10, aspect_ratio: "9:16", resolution: "720p" },
    inputs: [
      { asset: a2, slot: "reference", position: 1, role: "кот", included: false, label: null },
      { asset: a1, slot: "reference", position: 0, role: "героиня", included: true, label: "Image 1" },
      { asset: a3, slot: "first_frame", position: 0, role: "", included: true, label: "first_frame" },
    ],
  });
  let s = loaded();
  s = reducer(s, { type: "composer/fill", shot: sh });
  const c = s.composer;
  assert.equal(c.forkedFrom, U(10));
  assert.deepEqual(c.tray.map((i) => i.assetUid), [U(1), U(2)]);
  assert.equal(c.tray[0].role, "героиня");
  assert.equal(c.tray[1].included, false);
  assert.equal(c.tray[1].status, "failed");
  assert.equal(c.tray[1].errorCode, "bad_image");
  assert.equal(c.frames.first_frame.assetUid, U(3));
  assert.equal(c.params.duration, 10);
  assert.deepEqual(c.doc, sh.prompt_doc);
  // «Другая модель»: то же, но с выбранной моделью.
  s = reducer(s, { type: "composer/fill", shot: sh, model: "google/veo-3.1-fast" });
  assert.equal(s.composer.model, "google/veo-3.1-fast");
  assert.equal(s.composer.params.duration, 8);
});

test("composer/restore (черновик) и composer/reset", () => {
  let s = loaded();
  const doc = { v: 1, blocks: [[{ t: "text", v: "кот на крыше" }]] };
  s = reducer(s, {
    type: "composer/restore",
    draft: { kind: "video", model: "google/veo-3.1-fast", params: { duration: 12, aspect_ratio: "9:16" }, doc },
  });
  assert.equal(s.composer.model, "google/veo-3.1-fast");
  assert.equal(s.composer.params.duration, 8, "12 с у Veo нет — ближайшие 8");
  assert.deepEqual(s.composer.doc, doc);
  s = reducer(s, { type: "tray/add", item: chip("a", { assetUid: U(1) }) });
  const kept = reducer(s, { type: "composer/reset", keepText: true });
  assert.deepEqual(kept.composer.doc, doc);
  assert.equal(kept.composer.tray.length, 0);
  assert.equal(kept.composer.model, "google/veo-3.1-fast");
  const cleared = reducer(s, { type: "composer/reset" });
  assert.deepEqual(cleared.composer.doc, { v: 1, blocks: [[]] });
});

/* ------------------------------------------------------------------ */
/* Цена и запуск                                                       */
/* ------------------------------------------------------------------ */

test("quote: ответ на устаревшее тело не принимается", () => {
  let s = createInitialState();
  s = reducer(s, { type: "quote/loading", key: "k1" });
  s = reducer(s, { type: "quote/loading", key: "k2" });
  const stale = reducer(s, { type: "quote/loaded", key: "k1", quote: fx.FIXTURE_QUOTE });
  assert.equal(stale, s);
  s = reducer(s, { type: "quote/loaded", key: "k2", quote: fx.FIXTURE_QUOTE });
  assert.equal(s.quote.status, "ready");
  assert.equal(s.quote.data.credits, 164);
  const err = { status: 0, code: "network", message: "", data: {} };
  assert.equal(reducer(s, { type: "quote/failed", key: "k1", error: err }), s);
  s = reducer(s, { type: "quote/loading", key: "k3" });
  assert.equal(s.quote.data.credits, 164, "старая цена видна, пока считается новая");
  s = reducer(s, { type: "quote/failed", key: "k3", error: err });
  assert.equal(s.quote.status, "error");
});

function runResponse(p, sh, tk, extra = {}) {
  return { project: p, shot: sh, take: tk, asset: null, balance: { balance: 1200, reserved: 164, available: 1036 }, ...extra };
}

test("run/done в новой сессии: проект открыт, лента «загружена», кадр в ленте, проект в истории", () => {
  let s = run([{ type: "models/loaded", payload: MODELS }, { type: "run/start", clientRequestId: "a".repeat(32) }]);
  assert.equal(s.run.status, "sending");
  const p = project(1);
  const t = take(20, U(10), "queued");
  s = reducer(s, { type: "run/done", response: runResponse(p, shot(10, p.uid, [t]), t) });
  assert.equal(s.run.status, "idle");
  assert.equal(s.run.clientRequestId, null);
  assert.equal(s.project.uid, p.uid);
  assert.deepEqual(s.order, [U(10)]);
  assert.equal(s.feed.loaded, true);
  assert.equal(s.projects.items[0].uid, p.uid);
  assert.equal(s.takes.get(U(20)).status, "queued");
});

test("run/done после перехода в другой проект: лента не трогается, дубль всё равно опрашивается", () => {
  const other = project(2);
  let s = run([{ type: "project/set", project: other }, { type: "run/start", clientRequestId: "b".repeat(32) }]);
  const p = project(1);
  const t = take(20, U(10), "queued");
  s = reducer(s, { type: "run/done", response: runResponse(p, shot(10, p.uid, [t]), t) });
  assert.equal(s.project.uid, other.uid);
  assert.equal(s.shots.size, 0);
  assert.deepEqual(S.openTakeUids(s), [U(20)]);
});

test("run/done с картинкой: ассет «создаётся» попадает в загруженную библиотеку", () => {
  const p = project(1);
  const t = take(20, U(10), "queued", { kind: "image" });
  const asset = fx.fixtureAsset({ uid: U(30), status: "pending", source: "generated_image", url: null, thumb_url: null });
  let s = run([{ type: "library/loaded", page: { items: [], next: null }, append: false }]);
  s = reducer(s, { type: "run/done", response: runResponse(p, shot(10, p.uid, [t], { kind: "image" }), t, { asset }) });
  assert.deepEqual(s.library.items.map((a) => a.uid), [U(30)]);
});

test("run/failed: кнопка снова свободна, ошибка сохранена", () => {
  const err = { status: 402, code: "insufficient_balance", message: "", data: {} };
  const s = run([{ type: "run/start", clientRequestId: "c".repeat(32) }, { type: "run/failed", error: err }]);
  assert.equal(s.run.status, "idle");
  assert.equal(s.run.clientRequestId, null);
  assert.equal(s.run.error.code, "insufficient_balance");
});

/* ------------------------------------------------------------------ */
/* Интерфейс                                                           */
/* ------------------------------------------------------------------ */

test("ui: панели, окна, тосты (не больше четырёх), фокус дубля, полноэкранный редактор", () => {
  let s = createInitialState();
  s = reducer(s, { type: "ui/panel", panel: "rail" });
  assert.equal(s.ui.panels.rail, true);
  s = reducer(s, { type: "ui/panel", panel: "rail" });
  assert.equal(s.ui.panels.rail, false);
  assert.equal(reducer(s, { type: "ui/panel", panel: "rail", open: false }), s);
  s = reducer(s, { type: "ui/paywall", paywall: { reason: "premium_locked" } });
  assert.equal(s.ui.paywall.reason, "premium_locked");
  s = reducer(s, { type: "ui/auth", open: true });
  s = reducer(s, { type: "ui/topup", open: true });
  assert.equal(s.ui.auth && s.ui.topup, true);
  for (let i = 0; i < 6; i++) s = reducer(s, { type: "ui/toast", toast: { id: `t${i}`, tone: "info", text: `${i}` } });
  assert.deepEqual(s.ui.toasts.map((x) => x.id), ["t2", "t3", "t4", "t5"]);
  s = reducer(s, { type: "ui/toast", toast: { id: "t3", tone: "ok", text: "обновлён" } });
  assert.deepEqual(s.ui.toasts.map((x) => x.id), ["t2", "t4", "t5", "t3"]);
  s = reducer(s, { type: "ui/toastDismiss", id: "t2" });
  assert.equal(s.ui.toasts.length, 3);
  s = reducer(s, { type: "ui/focusTake", take: U(5) });
  assert.equal(s.ui.focusTake, U(5));
  s = reducer(s, { type: "ui/fullscreen", open: true });
  assert.equal(s.ui.fullscreen, true);
  s = reducer(s, { type: "page/status", status: "not_found" });
  assert.equal(s.ui.page, "not_found");
});

test("неизвестное действие не ломает стор", () => {
  const s = createInitialState();
  assert.equal(reducer(s, { type: "nope/nope" }), s);
});

/* ------------------------------------------------------------------ */
/* Адрес                                                               */
/* ------------------------------------------------------------------ */

test("parseStudioPath: новая сессия, проект, кривой uid", () => {
  assert.deepEqual(S.parseStudioPath("/video-studio"), { uid: null, invalid: false });
  assert.deepEqual(S.parseStudioPath("/video-studio/"), { uid: null, invalid: false });
  assert.deepEqual(S.parseStudioPath(`/video-studio/${U(7)}`), { uid: U(7), invalid: false });
  assert.deepEqual(S.parseStudioPath(`/video-studio/${U(7)}/`), { uid: U(7), invalid: false });
  assert.deepEqual(S.parseStudioPath("/video-studio/123"), { uid: null, invalid: true });
  assert.deepEqual(S.parseStudioPath(`/video-studio/${"AB".repeat(16)}`), { uid: null, invalid: true });
  assert.deepEqual(S.parseStudioPath("/video-studio/%E0%A4%A"), { uid: null, invalid: true });
  // До гидратации — uid со страницы.
  assert.deepEqual(S.parseStudioPath(null, U(8)), { uid: U(8), invalid: false });
  assert.deepEqual(S.parseStudioPath(null, null), { uid: null, invalid: false });
});
