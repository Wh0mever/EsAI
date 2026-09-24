// Видеостудия: загрузка фото (lib/vstudio/upload.ts) — проверка до сети,
// уменьшение через canvas (подменено), очередь «по одному файлу», отмена и
// полный путь через мок-сервер фикстур. Наружу ничего не уходит.
// Запуск (Node 22.6+):  node --experimental-strip-types --test src/lib/vstudio/upload.test.mjs
import "./nodeTsHooks.mjs";
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
};

const up = await import("./upload.ts");
const api = await import("./api.ts");
const fx = await import("./fixtures.ts");

const MB = 1024 * 1024;

function file(name, type, size = 1000) {
  const f = new File([new Uint8Array(Math.min(size, 64))], name, { type });
  if (size > 64) Object.defineProperty(f, "size", { value: size });
  return f;
}

beforeEach(() => {
  api.setFixturesMode(true);
  fx.resetMockBackend({ latencyMs: 0, balance: 1000 });
});

/* ---------- проверка до сети ---------- */

test("checkFile: принимает фото из белого списка сервера, в том числе HEIC и .jfif", () => {
  for (const [name, type] of [
    ["a.jpg", "image/jpeg"],
    ["a.JPEG", "image/jpeg"],
    ["a.jfif", "image/jpeg"],
    ["a.png", "image/png"],
    ["a.webp", "image/webp"],
    ["a.gif", "image/gif"],
    ["a.bmp", "image/bmp"],
    ["IMG_1.HEIC", ""],
    ["b.heif", "image/heif"],
    ["image.png", "image/png"],
  ]) {
    const c = up.checkFile({ name, type, size: 1000 });
    assert.equal(c.ok, true, name);
  }
  const heic = up.checkFile({ name: "IMG_1.HEIC", type: "", size: 1000 });
  assert.equal(heic.ok && heic.heic, true);
  assert.equal(heic.ok && heic.resizable, false, "HEIC уходит как есть — переведёт сервер");
  const jpg = up.checkFile({ name: "x.jpg", type: "image/jpeg", size: 1000 });
  assert.equal(jpg.ok && jpg.resizable, true);
});

test("checkFile: вставка скриншота без имени — по type", () => {
  assert.equal(up.checkFile({ name: "", type: "image/png", size: 10 }).ok, true);
  assert.equal(up.checkFile({ name: "blob", type: "image/jpeg", size: 10 }).ok, true);
});

test("checkFile: видео и звук — video_refs_unsupported, SVG и документы — unsupported_type", () => {
  assert.deepEqual(up.checkFile({ name: "clip.mp4", type: "video/mp4", size: 10 }), { ok: false, code: "video_refs_unsupported" });
  assert.deepEqual(up.checkFile({ name: "voice.m4a", type: "", size: 10 }), { ok: false, code: "video_refs_unsupported" });
  assert.deepEqual(up.checkFile({ name: "logo.svg", type: "image/svg+xml", size: 10 }), { ok: false, code: "unsupported_type" });
  assert.deepEqual(up.checkFile({ name: "doc.pdf", type: "application/pdf", size: 10 }), { ok: false, code: "unsupported_type" });
  assert.deepEqual(up.checkFile({ name: "photo.avif", type: "image/avif", size: 10 }), { ok: false, code: "unsupported_type" });
  assert.deepEqual(up.checkFile({ name: "", type: "", size: 10 }), { ok: false, code: "unsupported_type" });
});

test("checkFile: размер отказывает только тому, что не уменьшится на клиенте", () => {
  assert.deepEqual(up.checkFile({ name: "big.heic", type: "image/heic", size: 16 * MB }), { ok: false, code: "file_too_large" });
  assert.deepEqual(up.checkFile({ name: "big.gif", type: "image/gif", size: 16 * MB }), { ok: false, code: "file_too_large" });
  // Тяжёлый JPEG станет лёгким после canvas — отказывать рано.
  assert.equal(up.checkFile({ name: "big.jpg", type: "image/jpeg", size: 30 * MB }).ok, true);
});

test("fitWithin: длинная сторона до 2048, пропорции сохраняются; меньше — не трогаем", () => {
  assert.equal(up.fitWithin(2048, 1000), null);
  assert.equal(up.fitWithin(800, 600), null);
  assert.deepEqual(up.fitWithin(4032, 3024), { width: 2048, height: 1536 });
  assert.deepEqual(up.fitWithin(3000, 6000), { width: 1024, height: 2048 });
  assert.equal(up.fitWithin(0, 100), null);
});

test("renamedFor: расширение под новый формат, мусор из имени убирается", () => {
  assert.equal(up.renamedFor("IMG_0042.JPG", "image/jpeg"), "IMG_0042.jpg");
  assert.equal(up.renamedFor("shot.webp", "image/png"), "shot.png");
  assert.equal(up.renamedFor("", "image/png"), "photo.png");
  assert.equal(up.renamedFor('a/b:c*?.jpeg', "image/jpeg"), "a_b_c_.jpg");
});

/* ---------- уменьшение через canvas (подменено) ---------- */

function fakeDecoded(w, h) {
  let closed = false;
  return { width: w, height: h, draw() {}, close: () => (closed = true), get closed() { return closed; } };
}

test("prepareImage: большое фото перерисовывается до 2048 и получает новое имя", async () => {
  const src = fakeDecoded(4000, 3000);
  const calls = [];
  const res = await up.prepareImage(file("IMG.JPG", "image/jpeg", 8 * MB), {
    decode: async () => src,
    encode: async (s, w, h, mime, q) => {
      calls.push({ w, h, mime, q });
      return new Blob([new Uint8Array(100)], { type: "image/jpeg" });
    },
  });
  assert.equal(res.resized, true);
  assert.equal(res.filename, "IMG.jpg");
  assert.deepEqual(calls, [{ w: 2048, h: 1536, mime: "image/jpeg", q: 0.9 }]);
  assert.equal(src.closed, true, "раскодированная картинка освобождается");
});

test("prepareImage: маленькое фото уходит как есть, WebP без поддержки браузера — PNG по факту", async () => {
  const small = file("a.png", "image/png", 2000);
  const same = await up.prepareImage(small, { decode: async () => fakeDecoded(800, 600), encode: async () => assert.fail("не нужно") });
  assert.equal(same.resized, false);
  assert.equal(same.blob, small);

  const webp = await up.prepareImage(file("a.webp", "image/webp", 5 * MB), {
    decode: async () => fakeDecoded(5000, 5000),
    encode: async () => new Blob([new Uint8Array(10)], { type: "image/png" }),
  });
  assert.equal(webp.filename, "a.png");
});

test("prepareImage: сбой canvas или декодера — уходит исходный файл (сервер уменьшит сам)", async () => {
  const f = file("x.jpg", "image/jpeg", 3 * MB);
  assert.equal((await up.prepareImage(f, { decode: async () => null })).blob, f);
  assert.equal((await up.prepareImage(f, { decode: async () => { throw new Error("oom"); } })).blob, f);
  assert.equal((await up.prepareImage(f, { decode: async () => fakeDecoded(5000, 4000), encode: async () => null })).blob, f);
  // HEIC и GIF не трогаем вовсе.
  const heic = file("x.heic", "image/heic", 3 * MB);
  assert.equal((await up.prepareImage(heic, { decode: async () => assert.fail("не декодируем") })).blob, heic);
});

/* ---------- одна загрузка ---------- */

test("uploadOne: отказ до сети — код для чипа, запрос не уходит", async () => {
  const seeded = fx.getMockBackend().inspect().assets;
  const video = await up.uploadOne(file("clip.mov", "video/quicktime"));
  assert.equal(video.ok, false);
  assert.equal(video.error.code, "video_refs_unsupported");
  const big = await up.uploadOne(file("big.heic", "image/heic", 20 * MB));
  assert.equal(big.ok, false);
  assert.equal(big.error.code, "file_too_large");
  assert.equal(big.error.status, 413);
  assert.equal(fx.getMockBackend().inspect().assets, seeded, "мок не получил ни одного файла");
});

test("uploadOne: фото доходит до сервера, прогресс «загрузка → обработка», дубль по тому же файлу — 200", async () => {
  const before = fx.getMockBackend().inspect().assets;
  const phases = [];
  const f = file("cat.png", "image/png", 1000);
  const res = await up.uploadOne(f, { onProgress: (pct, phase) => phases.push(`${phase}:${pct}`) });
  assert.equal(res.ok, true);
  assert.equal(res.data.duplicate, false);
  assert.match(res.data.asset.uid, /^[0-9a-f]{32}$/);
  assert.ok(phases.includes("processing:100"));
  assert.equal(fx.getMockBackend().inspect().assets, before + 1);
  const again = await up.uploadOne(f);
  assert.equal(again.ok && again.data.duplicate, true);
  assert.equal(again.ok && again.data.asset.uid, res.data.asset.uid);
});

/* ---------- очередь ---------- */

function deferred() {
  let resolve;
  const promise = new Promise((r) => (resolve = r));
  return { promise, resolve };
}
const OK = (uid) => ({ ok: true, status: 201, data: { asset: { uid }, duplicate: false } });

test("очередь: файлы уходят по одному, в порядке добавления", async () => {
  const started = [];
  const gates = new Map();
  const q = up.createUploadQueue((job) => {
    started.push(job.lid);
    const d = deferred();
    gates.set(job.lid, d);
    return d.promise;
  });
  const a = q.add({ lid: "a", file: file("a.jpg", "image/jpeg"), project: null });
  const b = q.add({ lid: "b", file: file("b.jpg", "image/jpeg"), project: null });
  await Promise.resolve();
  assert.deepEqual(started, ["a"], "второй ждёт первого");
  assert.equal(q.size(), 2);
  assert.equal(q.active(), "a");
  gates.get("a").resolve(OK("1"));
  assert.equal((await a).ok, true);
  await Promise.resolve();
  assert.deepEqual(started, ["a", "b"]);
  gates.get("b").resolve(OK("2"));
  assert.equal((await b).data.asset.uid, "2");
  assert.equal(q.size(), 0);
});

test("очередь: отмена текущего прерывает его (aborted), ждущий убирается сразу", async () => {
  const signals = new Map();
  const events = [];
  const q = up.createUploadQueue(
    (job, ctl) => {
      signals.set(job.lid, ctl.signal);
      return new Promise((resolve) => ctl.signal.addEventListener("abort", () => resolve(OK("late"))));
    },
    (e) => events.push(`${e.type}:${e.lid}`),
  );
  const a = q.add({ lid: "a", file: file("a.jpg", "image/jpeg"), project: null });
  const b = q.add({ lid: "b", file: file("b.jpg", "image/jpeg"), project: null });
  const c = q.add({ lid: "c", file: file("c.jpg", "image/jpeg"), project: null });
  assert.equal(q.cancel("b"), true);
  const rb = await b;
  assert.equal(rb.ok, false);
  assert.equal(rb.error.code, "aborted");
  assert.equal(q.has("b"), false);

  assert.equal(q.cancel("a"), true);
  const ra = await a;
  assert.equal(ra.error.code, "aborted", "даже если сервер успел ответить — отменённое не считается загруженным");
  assert.equal(signals.get("a").aborted, true);
  await Promise.resolve();
  assert.equal(q.active(), "c", "после отмены очередь идёт дальше");
  q.cancelAll();
  assert.equal((await c).error.code, "aborted");
  assert.equal(q.cancel("zzz"), false);
  assert.ok(events.includes("done:b"));
});

test("очередь: исключение внутри отправки — ошибка этого файла, очередь не встаёт", async () => {
  let n = 0;
  const q = up.createUploadQueue(async () => {
    n += 1;
    if (n === 1) throw new Error("boom");
    return OK("x");
  });
  const a = await q.add({ lid: "a", file: file("a.jpg", "image/jpeg"), project: null });
  assert.equal(a.ok, false);
  assert.equal(a.error.code, "unknown");
  const b = await q.add({ lid: "b", file: file("b.jpg", "image/jpeg"), project: null });
  assert.equal(b.ok, true);
});

test("очередь: прогресс приходит только от текущего файла", async () => {
  const seen = [];
  const q = up.createUploadQueue(
    async (job, ctl) => {
      ctl.onProgress(50, "upload");
      ctl.onProgress(100, "processing");
      return OK(job.lid);
    },
    (e) => {
      if (e.type === "progress") seen.push(`${e.lid}:${e.phase}:${e.pct}`);
    },
  );
  await q.add({ lid: "a", file: file("a.jpg", "image/jpeg"), project: null });
  assert.deepEqual(seen, ["a:upload:50", "a:processing:100"]);
});
