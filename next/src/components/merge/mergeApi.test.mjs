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

/* ---------- звук склейки (CONTRACT_M.md §10) ---------- */

const PID = "3c0917b144dc454092047e74d12a079f";
const TRACK = "1814eb6841284714b356aa88f5d67b29";
const AUDIO = { project_id: PID, status: "draft", editable: true, tracks: [], fragments: 2 };
const song = () => new File([new Uint8Array([0x49, 0x44, 0x33, 4])], "Песня.mp3", { type: "audio/mpeg" });

test("звук: пути и тела запросов; кривой id не уходит в сеть", async () => {
  const calls = [];
  const prev = globalThis.fetch;
  globalThis.fetch = async (url, init = {}) => {
    calls.push({ line: `${init.method} ${url}`, body: init.body ? JSON.parse(init.body) : null });
    const status = String(url).endsWith("voice/") ? 201 : String(url).endsWith("music/") ? 202 : 200;
    const body = String(url).includes("cartoon/audio/voices/") && !String(url).includes("preview") ? [] : String(url).includes("preview") ? { url: "/media/p.mp3" } : AUDIO;
    return new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json" } });
  };
  try {
    assert.equal((await api.getAudio(PID)).ok, true);
    await api.patchAudio(PID, { clip_sound: "quiet" });
    const voice = await api.makeVoice(PID, { text: "Привет", voice_id: "v1", start_fragment: 1, price: 5, request_id: "r1" });
    assert.equal(voice.status, 201);
    const music = await api.makeMusic(PID, { prompt: "пианино", price: 8, request_id: "r2" });
    assert.equal(music.status, 202);
    await api.deleteTrack(PID, TRACK);
    assert.deepEqual((await api.listVoices()).data, []);
    assert.equal((await api.voicePreview("EXAVITQu4vr4xnSDxMaL", "kg")).data.url, "/media/p.mp3");
    assert.equal((await api.getAudio("../x")).error.code, "project_not_found");
    assert.equal((await api.deleteTrack(PID, "x")).error.code, "audio_not_found");
    assert.equal((await api.voicePreview("../../secret", "ru")).ok, false);
    assert.deepEqual(
      calls.map((c) => c.line),
      [
        `GET /api/merge/${PID}/audio/`,
        `PATCH /api/merge/${PID}/audio/`,
        `POST /api/merge/${PID}/audio/voice/`,
        `POST /api/merge/${PID}/audio/music/`,
        `DELETE /api/merge/${PID}/audio/${TRACK}/`,
        "GET /api/cartoon/audio/voices/",
        "GET /api/cartoon/audio/voices/EXAVITQu4vr4xnSDxMaL/preview/?lang=kg",
      ],
    );
    assert.deepEqual(calls[1].body, { clip_sound: "quiet" });
    assert.deepEqual(calls[2].body, { text: "Привет", voice_id: "v1", start_fragment: 1, price: 5, request_id: "r1" });
    assert.deepEqual(calls[3].body, { prompt: "пианино", price: 8, request_id: "r2" });
  } finally {
    globalThis.fetch = prev;
  }
});

test("свой трек: XHR на music/upload/, имя для сервера, прогресс, 413 nginx → audio_too_big 20 МБ", async () => {
  FakeXHR.plans = [
    { status: 201, body: JSON.stringify({ ...AUDIO, track: { id: TRACK } }), progress: [[1, 2], [2, 2]] },
    { status: 413, body: "<html><body>413 Request Entity Too Large</body></html>" },
    { status: 400, body: JSON.stringify({ error: "Трек длиннее 5 минут.", error_code: "audio_too_long", max_s: 300 }) },
  ];
  const progress = [];
  const ok = await api.uploadMusic(PID, song(), { filename: "Песня.mp3", onProgress: (p, phase) => progress.push(`${phase}:${p}`) });
  assert.equal(ok.ok, true);
  assert.equal(ok.data.track.id, TRACK);
  const x = FakeXHR.sent[0];
  assert.equal(x.url, `/api/merge/${PID}/audio/music/upload/`);
  assert.equal(x.body.get("file").name, "Песня.mp3");
  assert.deepEqual(progress, ["upload:0", "upload:50", "upload:99", "processing:100"]);
  const big = await api.uploadMusic(PID, song());
  assert.equal(big.error.code, "audio_too_big");
  assert.equal(big.error.data.max_mb, 20);
  const long = await api.uploadMusic(PID, song());
  assert.equal(long.error.code, "audio_too_long");
  assert.equal((await api.uploadMusic("nope", song())).error.code, "project_not_found");
  assert.equal(FakeXHR.sent.length, 3, "кривой id не уходит в сеть");
});

test("свой трек: имя без расширения — то, что дал audioUploadName; отмена", async () => {
  FakeXHR.plans = [{ status: 201, body: JSON.stringify(AUDIO) }, { hang: true }];
  await api.uploadMusic(PID, new File([new Uint8Array([1])], "Запись 12", { type: "audio/x-m4a" }), { filename: "Запись 12.m4a" });
  assert.equal(FakeXHR.sent[0].body.get("file").name, "Запись 12.m4a");
  const ctrl = new AbortController();
  const pending = api.uploadMusic(PID, song(), { signal: ctrl.signal });
  await new Promise((r) => setTimeout(r, 0));
  ctrl.abort();
  assert.equal((await pending).error.code, "aborted");
});

test("удаление склейки: 409 audio_busy (звук ещё делается) — отказ с текстом сервера (MA_FIX4)", async () => {
  const { deleteRefusal } = await import("./mergeLogic.ts");
  const calls = [];
  const prev = globalThis.fetch;
  const body = { error: "Звук для этой склейки ещё делается — дождитесь его.", error_code: "audio_busy" };
  globalThis.fetch = async (url, init = {}) => {
    calls.push(`${init.method} ${url}`);
    return new Response(JSON.stringify(body), { status: 409, headers: { "content-type": "application/json" } });
  };
  try {
    const res = await api.deleteProject(PID);
    assert.equal(res.ok, false);
    assert.equal(res.error.code, "audio_busy");
    assert.equal(res.error.status, 409);
    assert.deepEqual(deleteRefusal(res.error), { key: "merge.err.audio_busy", ru: body.error, params: {} });
    assert.deepEqual(calls, [`DELETE /api/merge/${PID}/`]);
  } finally {
    globalThis.fetch = prev;
  }
});
