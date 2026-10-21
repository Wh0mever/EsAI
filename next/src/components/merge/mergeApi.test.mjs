// «Склейка»: загрузка своего видео (mergeApi.ts) — XHR, прогресс, отмена, 413, повтор после истёкшего токена.
// Сеть подменена: XMLHttpRequest и fetch — заглушки, наружу ничего не уходит.
// Запуск (Node 22.6+):  node --experimental-strip-types --test src/components/merge/*.test.mjs
import "../../lib/vstudio/nodeTsHooks.mjs";
import { test, beforeEach } from "node:test";
import assert from "node:assert/strict";

// Access-токен в sessionStorage (как у Mini App): getToken прочитает его без document.cookie.
const b64 = (o) => Buffer.from(JSON.stringify(o)).toString("base64url");
const token = (exp) => `${b64({ alg: "HS256" })}.${b64({ exp })}.sig`;
const now = () => Math.floor(Date.now() / 1000);
const LIVE = token(now() + 3600);
const session = new Map();
globalThis.window = {
  sessionStorage: {
    getItem: (k) => (session.has(k) ? session.get(k) : null),
    setItem: (k, v) => session.set(k, String(v)),
    removeItem: (k) => session.delete(k),
  },
  location: { origin: "https://esai.test", pathname: "/merge", search: "", hash: "", protocol: "https:", replace() {} },
};

const api = await import("./mergeApi.ts");

class FakeXHR {
  static plans = [];
  static sent = [];
  constructor() {
    this.headers = {};
    this.upload = {};
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
    FakeXHR.sent.push(this);
    const plan = FakeXHR.plans.shift() ?? { status: 201, body: "{}" };
    if (plan.hang) return;
    setTimeout(() => {
      if (plan.networkError) return this.onerror?.();
      for (const [loaded, total] of plan.progress || []) this.upload.onprogress?.({ lengthComputable: true, loaded, total });
      this.upload.onload?.();
      plan.before?.();
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

let refreshes = 0;
let refreshTo = null;
globalThis.fetch = async (url) => {
  if (String(url).endsWith("users/token/refresh/")) {
    refreshes += 1;
    if (!refreshTo) return new Response("{}", { status: 401, headers: { "content-type": "application/json" } });
    return new Response(JSON.stringify({ access: refreshTo, refresh: "r2" }), {
      status: 200,
      headers: { "content-type": "application/json" },
    });
  }
  throw new Error(`неожиданный запрос ${url}`);
};

const CARD = {
  type: "upload",
  id: "07d09605372244e78a5050bbbaf6678e",
  title: "IMG_0001",
  subtitle: "",
  poster: "/media/merge/uploads/1/07d09605372244e78a5050bbbaf6678e.jpg",
  url: "/media/merge/uploads/1/07d09605372244e78a5050bbbaf6678e.mp4",
  duration_s: 3.0,
  width: 720,
  height: 1280,
  created_at: "2026-10-21T08:01:17.794531+00:00",
  size_bytes: 45563,
  has_audio: true,
  expires_at: "2026-11-20T08:01:17.794412+00:00",
};
const clip = () => new File([new Uint8Array([0, 0, 0, 0x18, 0x66, 0x74, 0x79, 0x70])], "IMG_0001.MOV", { type: "video/quicktime" });

beforeEach(() => {
  session.clear();
  session.set("tg_access", LIVE);
  session.set("tg_refresh", token(now() + 86400));
  FakeXHR.plans = [];
  FakeXHR.sent = [];
  refreshes = 0;
  refreshTo = null;
});

test("загрузка: POST multipart, поле file, заголовки, ?lang=, прогресс, 201 → карточка", async () => {
  FakeXHR.plans = [{ status: 201, body: JSON.stringify(CARD), progress: [[1, 4], [2, 4], [4, 4]] }];
  const progress = [];
  const r = await api.uploadVideo(clip(), { lang: "kg", onProgress: (p, phase) => progress.push(`${phase}:${p}`) });
  assert.equal(r.ok, true);
  assert.deepEqual(r.data, CARD);
  const x = FakeXHR.sent[0];
  assert.equal(x.method, "POST");
  assert.equal(x.url, "/api/merge/uploads/?lang=kg");
  assert.equal(x.headers.Authorization, `Bearer ${LIVE}`);
  assert.equal(x.headers.Accept, "application/json");
  assert.equal(x.body.get("file").name, "IMG_0001.MOV");
  assert.deepEqual(progress, ["upload:0", "upload:25", "upload:50", "upload:99", "processing:100"]);
});

test("загрузка: имя для сервера — из uploadName, если у файла не было расширения", async () => {
  FakeXHR.plans = [{ status: 201, body: JSON.stringify(CARD) }];
  await api.uploadVideo(new File([new Uint8Array([1])], "video:12", { type: "video/mp4" }), { filename: "video:12.mp4" });
  assert.equal(FakeXHR.sent[0].body.get("file").name, "video:12.mp4");
});

test("загрузка: отказ сервера с кодом, 413 nginx (HTML) → upload_too_big, обрыв сети", async () => {
  FakeXHR.plans = [
    { status: 400, body: JSON.stringify({ error: "Видео длиннее 60 секунд.", error_code: "upload_too_long", max_s: 60 }) },
    { status: 413, body: "<html><body>413 Request Entity Too Large</body></html>" },
    { networkError: true },
    { status: 409, body: JSON.stringify({ error: "Место занято", error_code: "upload_quota", max_files: 10 }) },
  ];
  const long = await api.uploadVideo(clip());
  assert.equal(long.error.code, "upload_too_long");
  assert.equal(long.error.message, "Видео длиннее 60 секунд.");
  assert.equal(long.error.data.max_s, 60);
  const big = await api.uploadVideo(clip());
  assert.equal(big.status, 413);
  assert.equal(big.error.code, "upload_too_big");
  assert.equal((await api.uploadVideo(clip())).error.code, "network");
  const quota = await api.uploadVideo(clip());
  assert.equal(quota.status, 409);
  assert.equal(quota.error.code, "upload_quota");
});

test("загрузка: отмена во время отправки и до неё", async () => {
  FakeXHR.plans = [{ hang: true }];
  const ctrl = new AbortController();
  const pending = api.uploadVideo(clip(), { signal: ctrl.signal });
  await new Promise((r) => setTimeout(r, 0));
  ctrl.abort();
  const r = await pending;
  assert.equal(r.error.code, "aborted");
  assert.equal(FakeXHR.sent[0].aborted, true);
  const early = new AbortController();
  early.abort();
  assert.equal((await api.uploadVideo(clip(), { signal: early.signal })).error.code, "aborted");
  assert.equal(FakeXHR.sent.length, 1, "отменённая заранее не уходит");
});

test("загрузка: гость — 401 без отправки файла", async () => {
  session.clear();
  const r = await api.uploadVideo(clip());
  assert.equal(r.status, 401);
  assert.equal(r.error.code, "unauthorized");
  assert.equal(FakeXHR.sent.length, 0);
});

test("загрузка: токен истёк, пока шёл файл — обновляем и повторяем один раз", async () => {
  const FRESH = token(now() + 7200);
  refreshTo = FRESH;
  // Сервер ответил 401, а к этому моменту часы уже прошли срок токена.
  FakeXHR.plans = [
    { status: 401, body: JSON.stringify({ detail: "Token is invalid or expired" }), before: () => session.set("tg_access", token(now() - 5)) },
    { status: 201, body: JSON.stringify(CARD) },
  ];
  const r = await api.uploadVideo(clip());
  assert.equal(r.ok, true);
  assert.equal(refreshes, 1);
  assert.equal(FakeXHR.sent.length, 2);
  assert.equal(FakeXHR.sent[1].headers.Authorization, `Bearer ${FRESH}`);
});

test("загрузка: 401 при живом токене — не повторяем (второй раз был бы тот же отказ)", async () => {
  FakeXHR.plans = [{ status: 401, body: JSON.stringify({ detail: "User is inactive" }) }];
  const r = await api.uploadVideo(clip());
  assert.equal(r.status, 401);
  assert.equal(FakeXHR.sent.length, 1);
  assert.equal(refreshes, 0);
});

test("список и удаление своих видео: пути; кривой id не уходит в сеть", async () => {
  const calls = [];
  const prev = globalThis.fetch;
  globalThis.fetch = async (url, init = {}) => {
    calls.push(`${init.method} ${url}`);
    if (init.method === "DELETE") return new Response(null, { status: 204 });
    return new Response(JSON.stringify({ results: [CARD], usage: { files: 1, bytes: 45563, max_files: 10, max_bytes: 629145600 } }), {
      status: 200,
      headers: { "content-type": "application/json" },
    });
  };
  try {
    const list = await api.listUploads("en");
    assert.equal(list.ok, true);
    assert.equal(list.data.results[0].id, CARD.id);
    const del = await api.deleteUpload(CARD.id);
    assert.equal(del.ok, true);
    const bad = await api.deleteUpload("../1");
    assert.equal(bad.error.code, "upload_not_found");
    assert.deepEqual(calls, ["GET /api/merge/uploads/?lang=en", `DELETE /api/merge/uploads/${CARD.id}/`]);
  } finally {
    globalThis.fetch = prev;
  }
});
