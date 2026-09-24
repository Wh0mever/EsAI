// Видеостудия: слой API (lib/vstudio/api.ts) — пути, тела, разбор ошибок,
// опрос пачками, отмена, загрузка через XHR и режим фикстур.
// Сеть подменена: global fetch и XMLHttpRequest — заглушки, наружу ничего не уходит.
// Запуск (Node 22.6+):  node --experimental-strip-types --test src/lib/vstudio/api.test.mjs
import "./nodeTsHooks.mjs";
import { test, beforeEach } from "node:test";
import assert from "node:assert/strict";

// Живой access-токен в sessionStorage (как у Mini App): getToken прочитает его без document.cookie.
const b64 = (o) => Buffer.from(JSON.stringify(o)).toString("base64url");
const TOKEN = `${b64({ alg: "HS256" })}.${b64({ exp: Math.floor(Date.now() / 1000) + 3600 })}.sig`;
const session = new Map([["tg_access", TOKEN]]);
globalThis.window = {
  sessionStorage: {
    getItem: (k) => (session.has(k) ? session.get(k) : null),
    setItem: (k, v) => session.set(k, String(v)),
    removeItem: (k) => session.delete(k),
  },
  location: { origin: "https://esai.test", pathname: "/video-studio", search: "", hash: "", protocol: "https:", replace() {} },
};

const api = await import("./api.ts");
const fx = await import("./fixtures.ts");

const U = (n) => n.toString(16).padStart(32, "0");

/* ---------- заглушка fetch ---------- */
let calls = [];
let responder = () => ({ status: 200, body: {} });
globalThis.fetch = async (url, init = {}) => {
  const call = {
    url: String(url),
    method: init.method,
    headers: init.headers || {},
    body: typeof init.body === "string" ? JSON.parse(init.body) : init.body,
  };
  calls.push(call);
  const r = await responder(call);
  if (r.status === 204) return new Response(null, { status: 204 });
  const isText = typeof r.body === "string";
  return new Response(isText ? r.body : JSON.stringify(r.body), {
    status: r.status,
    headers: { "content-type": isText ? "text/html" : "application/json" },
  });
};

beforeEach(() => {
  calls = [];
  responder = () => ({ status: 200, body: {} });
  api.setFixturesMode(false);
  session.set("tg_access", TOKEN);
});

test("GET models/: путь, Bearer, разбор ответа", async () => {
  responder = () => ({ status: 200, body: fx.FIXTURE_MODELS });
  const r = await api.getModels();
  assert.equal(r.ok, true);
  assert.equal(r.data.video[0].id, "bytedance/seedance-2.0");
  assert.equal(calls.length, 1);
  assert.equal(calls[0].url, "/api/vstudio/models/");
  assert.equal(calls[0].method, "GET");
  assert.equal(calls[0].headers.Authorization, `Bearer ${TOKEN}`);
});

test("гость: заголовка Authorization нет, AllowAny отвечает как есть", async () => {
  session.delete("tg_access");
  responder = () => ({ status: 200, body: { ...fx.FIXTURE_MODELS, available: false } });
  const r = await api.getModels();
  assert.equal(r.ok, true);
  assert.equal(calls[0].headers.Authorization, undefined);
});

test("проекты: строка запроса без пустых полей, архив 0/1", async () => {
  responder = () => ({ status: 200, body: { items: [], next: null } });
  await api.listProjects();
  await api.listProjects({ q: "  кошка ", archived: true, before: "2026-09-24T10:00:00.000Z", limit: 30 });
  assert.equal(calls[0].url, "/api/vstudio/projects/?archived=0");
  assert.equal(
    calls[1].url,
    "/api/vstudio/projects/?q=%D0%BA%D0%BE%D1%88%D0%BA%D0%B0&archived=1&before=2026-09-24T10%3A00%3A00.000Z&limit=30",
  );
});

test("проект: создать, прочитать, PATCH, DELETE → 204 без тела", async () => {
  const p = U(0xb1);
  responder = (c) => (c.method === "DELETE" ? { status: 204 } : { status: c.method === "POST" ? 201 : 200, body: { uid: p } });
  assert.equal((await api.createProject({ title: "Кошка" })).status, 201);
  assert.equal((await api.getProject(p)).ok, true);
  assert.equal((await api.updateProject(p, { title: "Новое" })).ok, true);
  const del = await api.archiveProject(p);
  assert.deepEqual(del, { ok: true, status: 204, data: null });
  assert.deepEqual(
    calls.map((c) => `${c.method} ${c.url}`),
    [
      "POST /api/vstudio/projects/",
      `GET /api/vstudio/projects/${p}/`,
      `PATCH /api/vstudio/projects/${p}/`,
      `DELETE /api/vstudio/projects/${p}/`,
    ],
  );
  assert.deepEqual(calls[0].body, { title: "Кошка" });
  assert.deepEqual(calls[2].body, { title: "Новое" });
});

test("кривой uid (из ?take= или чужого кода) не уходит в сеть", async () => {
  for (const bad of ["../../users/me", "123", "", U(0xabc).toUpperCase(), `${U(1)}/`]) {
    const results = await Promise.all([
      api.getTake(bad),
      api.getProject(bad),
      api.cancelTake(bad),
      api.retryShot(bad, { quoted_credits: 1, client_request_id: "x" }),
      api.deleteAsset(bad),
      api.assetFromTake(bad),
      api.listShots(bad),
    ]);
    for (const r of results) {
      assert.equal(r.ok, false);
      assert.equal(r.error.code, "bad_request");
    }
  }
  assert.equal((await api.listShots(U(1), { before: "evil" })).error.code, "bad_request");
  assert.equal(calls.length, 0);
});

test("лента: before и limit", async () => {
  responder = () => ({ status: 200, body: { items: [], next: null } });
  await api.listShots(U(0xb1), { before: U(0xc1), limit: 20 });
  assert.equal(calls[0].url, `/api/vstudio/projects/${U(0xb1)}/shots/?before=${U(0xc1)}&limit=20`);
});

test("материалы: kind=image по умолчанию, фильтры библиотеки → source", async () => {
  responder = () => ({ status: 200, body: { items: [], next: null } });
  await api.listAssets();
  await api.listAssets({ source: api.LIBRARY_FILTER_SOURCE.uploads, limit: 60 });
  await api.listAssets({ source: api.LIBRARY_FILTER_SOURCE.all });
  assert.equal(calls[0].url, "/api/vstudio/assets/?kind=image");
  assert.equal(calls[1].url, "/api/vstudio/assets/?kind=image&source=upload&limit=60");
  assert.equal(calls[2].url, "/api/vstudio/assets/?kind=image");
  assert.deepEqual(api.LIBRARY_FILTER_SOURCE, { all: "", uploads: "upload", generated: "generated_image", frames: "frame" });
});

test("quote: тело уходит как есть, ошибки компилятора — внутри 200", async () => {
  responder = () => ({ status: 200, body: { ...fx.FIXTURE_QUOTE, errors: [{ code: "prompt_empty", params: {}, message: "m" }] } });
  const body = {
    project: null,
    kind: "video",
    model: "bytedance/seedance-2.0",
    prompt_doc: { v: 1, blocks: [[{ t: "text", v: "Кошка" }]] },
    inputs: [],
    params: { duration: 5 },
  };
  const r = await api.quote(body);
  assert.equal(r.ok, true);
  assert.equal(r.data.errors[0].code, "prompt_empty");
  assert.equal(calls[0].url, "/api/vstudio/quote/");
  assert.equal(calls[0].method, "POST");
  assert.deepEqual(calls[0].body, body);
  // Повтор кадра — {shot}.
  await api.quote({ shot: U(0xc1) });
  assert.deepEqual(calls[1].body, { shot: U(0xc1) });
});

test("shots/: 402 той же формы, что в чате; 409 price_changed; 403 premium_locked", async () => {
  const body = { project: null, kind: "video", model: "m", prompt_text: "x", inputs: [], params: {}, quoted_credits: 164, client_request_id: "a".repeat(32) };
  responder = () => ({
    status: 402,
    body: { error: "Недостаточно кредитов.", error_code: "insufficient_balance", balance_tokens: 40, required_estimate: 164 },
  });
  const r402 = await api.runShot(body);
  assert.equal(r402.ok, false);
  assert.equal(r402.error.code, "insufficient_balance");
  assert.equal(r402.error.data.required_estimate, 164);
  assert.equal(calls[0].url, "/api/vstudio/shots/");

  responder = () => ({ status: 409, body: { error: "Цена изменилась", error_code: "price_changed", credits: 171, breakdown: [] } });
  const r409 = await api.runShot(body);
  assert.equal(r409.error.code, "price_changed");
  assert.equal(r409.error.data.credits, 171);

  responder = () => ({ status: 403, body: { error: "Премиум", error_code: "premium_locked" } });
  const r403 = await api.runShot(body);
  assert.equal(r403.error.code, "premium_locked");
  // 403 с живым токеном — «нельзя», а не «сессия истекла»: refresh не крутится.
  assert.equal(calls.filter((c) => c.url.includes("token/refresh")).length, 0);

  responder = () => ({ status: 202, body: { take: { uid: U(0xd1) }, balance: null } });
  const retry = await api.retryShot(U(0xc1), { quoted_credits: 164, client_request_id: "b".repeat(32) });
  assert.equal(retry.status, 202);
  assert.equal(calls.at(-1).url, `/api/vstudio/shots/${U(0xc1)}/retry/`);
});

test("опрос: пачки по 30, дубли и мусор выброшены, ответы склеены", async () => {
  const ids = Array.from({ length: 65 }, (_, i) => U(0xd000 + i));
  responder = (c) => {
    const q = new URL(c.url, "https://x").searchParams.get("ids").split(",");
    return { status: 200, body: { items: q.map((uid) => ({ uid, status: "running" })) } };
  };
  const r = await api.pollTakes([...ids, ids[0], "не-uid"]);
  assert.equal(r.ok, true);
  assert.equal(r.data.items.length, 65);
  assert.equal(calls.length, 3);
  for (const c of calls) {
    assert.ok(c.url.startsWith("/api/vstudio/takes/?ids="));
    const n = new URL(c.url, "https://x").searchParams.get("ids").split(",").length;
    assert.ok(n <= api.MAX_POLL_IDS);
  }
  calls = [];
  assert.deepEqual(await api.pollTakes([]), { ok: true, status: 200, data: { items: [] } });
  assert.equal(calls.length, 0);
});

test("опрос: неудачная пачка — ошибка всего тика", async () => {
  let n = 0;
  responder = () => (n++ === 1 ? { status: 429, body: { detail: "Request was throttled." } } : { status: 200, body: { items: [] } });
  const r = await api.pollTakes(Array.from({ length: 40 }, (_, i) => U(0xd100 + i)));
  assert.equal(r.ok, false);
  assert.equal(r.error.code, "throttled");
});

test("отмена через AbortSignal: до запроса — сеть не трогаем, после — ответ выброшен", async () => {
  const pre = new AbortController();
  pre.abort();
  const r1 = await api.quote({ shot: U(1) }, { signal: pre.signal });
  assert.equal(r1.error.code, "aborted");
  assert.equal(calls.length, 0);

  const mid = new AbortController();
  responder = async () => {
    mid.abort();
    return { status: 200, body: fx.FIXTURE_QUOTE };
  };
  const r2 = await api.quote({ shot: U(1) }, { signal: mid.signal });
  assert.equal(r2.ok, false);
  assert.equal(r2.error.code, "aborted");
});

test("остальные эндпоинты: пути и тела", async () => {
  responder = (c) => ({ status: c.method === "DELETE" ? 204 : 200, body: { ok: 1, items: [], share_url: "https://esai.kg/v/x" } });
  await api.activeTakes();
  await api.getTake(U(0xd1));
  await api.cancelTake(U(0xd1));
  await api.deleteAsset(U(0xa1));
  await api.assetFromTake(U(0xd1));
  await api.condense({ model: "m", prompt_doc: { v: 1, blocks: [[]] }, inputs: [] });
  await api.shareVideo("https://esai.kg/media/v.mp4", { prompt: "p" });
  assert.deepEqual(
    calls.map((c) => `${c.method} ${c.url}`),
    [
      "GET /api/vstudio/takes/active/",
      `GET /api/vstudio/takes/${U(0xd1)}/`,
      `POST /api/vstudio/takes/${U(0xd1)}/cancel/`,
      `DELETE /api/vstudio/assets/${U(0xa1)}/`,
      "POST /api/vstudio/assets/from-take/",
      "POST /api/vstudio/assist/condense/",
      "POST /api/ai/video/share/",
    ],
  );
  assert.deepEqual(calls[4].body, { take: U(0xd1), at: "last_frame" });
  assert.deepEqual(calls[6].body, { url: "https://esai.kg/media/v.mp4", prompt: "p", model: "" });
});

test("ответ 200 без тела — bad_response, а не падение", async () => {
  responder = () => ({ status: 200, body: "" });
  const r = await api.getTake(U(0xd1));
  assert.equal(r.ok, false);
  assert.equal(r.error.code, "bad_response");
});

test("входы из композера: номера по лотку, кадры отдельно, чипы без uid не уходят", () => {
  const item = (lid, assetUid, extra = {}) => ({
    lid, assetUid, slot: "reference", role: "", included: true, status: "ready", progress: 100, preview: null, ...extra,
  });
  const tray = [
    item("l1", U(0xa1), { role: " героиня " }),
    item("l2", undefined, { status: "uploading", progress: 40 }),
    item("l3", U(0xa3), { included: false }),
    item("l4", U(0xa4), { status: "pending" }),
  ];
  const frames = { first_frame: item("f1", U(0xa5), { slot: "first_frame" }), last_frame: null };
  assert.deepEqual(api.buildInputs(tray, frames), [
    { asset: U(0xa1), slot: "reference", position: 0, role: "героиня", included: true },
    { asset: U(0xa3), slot: "reference", position: 1, role: undefined, included: false },
    { asset: U(0xa4), slot: "reference", position: 2, role: undefined, included: true },
    { asset: U(0xa5), slot: "first_frame", position: 0, role: undefined, included: true },
  ]);

  const doc = { v: 1, blocks: [[{ t: "text", v: "x" }]] };
  const video = api.quoteBodyFrom(
    { kind: "video", model: "bytedance/seedance-2.0", params: { duration: 5, seed: null, negative_prompt: "" }, doc, tray, frames },
    "не-uid",
  );
  assert.equal(video.project, null);
  assert.deepEqual(video.params, { duration: 5 });
  assert.equal(video.prompt_doc, doc);

  const image = api.quoteBodyFrom(
    { kind: "image", model: "google/gemini-2.5-flash-image", params: { duration: 5, aspect_ratio: "1:1", generate_audio: true }, doc, tray: [], frames: { first_frame: null, last_frame: null } },
    U(0xb1),
  );
  assert.deepEqual(image.params, { aspect_ratio: "1:1" });
  assert.equal(image.project, U(0xb1));
  assert.equal(api.quoteBodyFrom({ kind: "video", model: null, params: {}, doc, tray: [], frames }, null), null);

  // Ключ не зависит от порядка полей.
  assert.equal(api.quoteKey({ a: 1, b: { d: 1, c: 2 } }), api.quoteKey({ b: { c: 2, d: 1 }, a: 1 }));
  assert.notEqual(api.quoteKey({ a: 1 }), api.quoteKey({ a: 2 }));
  assert.equal(api.quoteKey(null), "");
});

test("client_request_id и isUid", () => {
  const a = api.newClientRequestId();
  const b = api.newClientRequestId();
  assert.match(a, /^[0-9a-f]{32}$/);
  assert.notEqual(a, b);
  assert.equal(api.isUid(U(5)), true);
  assert.equal(api.isUid("x"), false);
  assert.equal(api.isUid(null), false);
});

test("воронка: trackVs шлёт шаг в payments/funnel/event/", async () => {
  api.trackVs("vstudio_blocked", { code: "prompt_too_long" });
  api.trackVs("vstudio_view");
  await new Promise((r) => setTimeout(r, 0));
  const events = calls.filter((c) => c.url === "/api/payments/funnel/event/");
  assert.deepEqual(events.map((c) => c.body), [
    { name: "vstudio_blocked", meta: { code: "prompt_too_long" } },
    { name: "vstudio_view", meta: {} },
  ]);
});

/* ---------- загрузка через XHR ---------- */

class FakeXHR {
  static plan = { status: 201, body: "{}" };
  static last = null;
  constructor() {
    this.headers = {};
    this.upload = {};
    FakeXHR.last = this;
  }
  open(method, url) {
    this.method = method;
    this.url = url;
  }
  setRequestHeader(k, v) {
    this.headers[k] = v;
  }
  send(body) {
    this.body = body;
    const plan = FakeXHR.plan;
    if (plan.hang) return;
    setTimeout(() => {
      if (plan.networkError) return this.onerror?.();
      for (const [loaded, total] of plan.progress || []) this.upload.onprogress?.({ lengthComputable: true, loaded, total });
      this.upload.onload?.();
      this.status = plan.status;
      this.responseText = plan.body;
      this.onload?.();
    }, 0);
  }
  abort() {
    this.aborted = true;
    this.onabort?.();
  }
}
globalThis.XMLHttpRequest = FakeXHR;

const photo = () => new File([new Uint8Array([0xff, 0xd8, 0xff, 0xe0])], "кот.jpg", { type: "image/jpeg" });

test("загрузка: POST multipart, заголовки, прогресс, 201 → новый ассет", async () => {
  const asset = fx.fixtureAsset({ uid: U(0xa9) });
  FakeXHR.plan = { status: 201, body: JSON.stringify(asset), progress: [[1, 4], [2, 4], [4, 4]] };
  const progress = [];
  const r = await api.uploadAsset(photo(), { project: U(0xb1), onProgress: (p, phase) => progress.push(`${phase}:${p}`) });
  assert.equal(r.ok, true);
  assert.equal(r.data.duplicate, false);
  assert.equal(r.data.asset.uid, U(0xa9));
  const x = FakeXHR.last;
  assert.equal(x.method, "POST");
  assert.equal(x.url, "/api/vstudio/assets/");
  assert.equal(x.headers.Authorization, `Bearer ${TOKEN}`);
  assert.equal(x.headers["X-Requested-With"], "XMLHttpRequest");
  assert.equal(x.body.get("project"), U(0xb1));
  assert.equal(x.body.get("file").name, "кот.jpg");
  assert.deepEqual(progress, ["upload:0", "upload:25", "upload:50", "upload:99", "processing:100"]);
});

test("загрузка: 200 — тот же файл уже был (дедупликация)", async () => {
  FakeXHR.plan = { status: 200, body: JSON.stringify(fx.fixtureAsset()) };
  const r = await api.uploadAsset(new Blob([new Uint8Array([1])], { type: "image/png" }), { filename: "canvas.png" });
  assert.equal(r.ok, true);
  assert.equal(r.data.duplicate, true);
  assert.equal(FakeXHR.last.body.get("file").name, "canvas.png");
  assert.equal(FakeXHR.last.body.get("project"), null);
});

test("загрузка: 413 от nginx (HTML), 422 с кодом, обрыв сети", async () => {
  FakeXHR.plan = { status: 413, body: "<html><body>413 Request Entity Too Large</body></html>" };
  assert.equal((await api.uploadAsset(photo())).error.code, "file_too_large");
  FakeXHR.plan = { status: 422, body: JSON.stringify({ error: "Видео позже", error_code: "video_refs_unsupported" }) };
  const r = await api.uploadAsset(photo());
  assert.equal(r.error.code, "video_refs_unsupported");
  assert.equal(r.error.message, "Видео позже");
  FakeXHR.plan = { networkError: true };
  assert.equal((await api.uploadAsset(photo())).error.code, "network");
});

test("загрузка: отмена во время отправки", async () => {
  FakeXHR.plan = { hang: true };
  const ctrl = new AbortController();
  const pending = api.uploadAsset(photo(), { signal: ctrl.signal });
  await new Promise((r) => setTimeout(r, 0));
  ctrl.abort();
  const r = await pending;
  assert.equal(r.error.code, "aborted");
  assert.equal(FakeXHR.last.aborted, true);
});

test("загрузка: гостю запрос не отправляется", async () => {
  session.delete("tg_access");
  FakeXHR.last = null;
  const r = await api.uploadAsset(photo());
  assert.equal(r.status, 401);
  assert.equal(r.error.code, "unauthorized");
  assert.equal(FakeXHR.last, null);
});

test("режим фикстур: сеть не трогаем, мок отвечает по контракту", async () => {
  fx.resetMockBackend({ latencyMs: 0 });
  api.setFixturesMode(true);
  const models = await api.getModels();
  assert.equal(models.ok, true);
  assert.equal(models.data.mode, "on");
  const projects = await api.listProjects();
  assert.ok(projects.data.items.length >= 1);
  const up = await api.uploadAsset(photo());
  assert.equal(up.ok, true);
  assert.equal(up.status, 201);
  api.trackVs("vstudio_view");
  assert.equal(calls.length, 0);
  fx.resetMockBackend(null);
});
