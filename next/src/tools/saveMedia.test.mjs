// «Скачать» (tools/saveMedia.ts): какой путь выбирается на iPhone (Safari, PWA, Telegram), Android и компьютере,
// и что на сам файл (window.open — тёмная страница) не уходит ни одна ветка. Сеть, navigator и document — заглушки.
// Запуск (Node 22.6+):  node --experimental-strip-types --test src/tools/saveMedia.test.mjs
import "../lib/vstudio/nodeTsHooks.mjs";
import { test, afterEach } from "node:test";
import assert from "node:assert/strict";

const {
  saveMedia,
  followMedia,
  holdMedia,
  prefetchMedia,
  shareFile,
  toFile,
  canShareFileNow,
  canWarmMedia,
  wantMedia,
  STREAM_MAX_BYTES,
} = await import("./saveMedia.ts");
const { detectEnv, sheetMode } = await import("./saveEnv.ts");

const IPHONE_SAFARI =
  "Mozilla/5.0 (iPhone; CPU iPhone OS 18_6 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/26.0 Mobile/15E148 Safari/604.1";
const IPHONE_TELEGRAM =
  "Mozilla/5.0 (iPhone; CPU iPhone OS 26_0_1 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/26.0.1 Mobile/23A355 Safari/604.1";
const ANDROID_CHROME =
  "Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/141.0.0.0 Mobile Safari/537.36";
const MAC_SAFARI =
  "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.0 Safari/605.1.15";
const WIN_EDGE =
  "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36 Edg/130.0.0.0";

const DEVICES = {
  iphone: { userAgent: IPHONE_SAFARI, platform: "iPhone", maxTouchPoints: 5 },
  telegramIos: { userAgent: IPHONE_TELEGRAM, platform: "iPhone", maxTouchPoints: 5 },
  android: { userAgent: ANDROID_CHROME, platform: "Linux armv8l", maxTouchPoints: 5, userAgentData: { mobile: true } },
  mac: { userAgent: MAC_SAFARI, platform: "MacIntel", maxTouchPoints: 0 },
  win: { userAgent: WIN_EDGE, platform: "Win32", maxTouchPoints: 0, userAgentData: { mobile: false } },
};

const VIDEO = new Uint8Array(4096).fill(7);

/** Ответ сервера на файл: по умолчанию 200 и video/mp4 с длиной. */
function fileResponse({ status = 200, type = "video/mp4", body = VIDEO } = {}) {
  return new Response(status === 200 ? body : "not found", {
    status,
    headers: { "content-type": type, "content-length": String(status === 200 ? body.byteLength : 9) },
  });
}

let s;

/**
 * Окружение одного теста. share: функция-заглушка или null (нет Web Share);
 * canShare: true/false/null (null — функции нет).
 */
function setup({ device = "iphone", share, canShare = true, standalone = false, telegramProxy = false, miniApp = null,
  path = "/video-studio/3f9c1d2e", fetchImpl } = {}) {
  s = { fetches: 0, shares: [], opened: 0, reports: [], clicks: [], tgDownloads: [] };
  const d = DEVICES[device];
  const nav = {
    userAgent: d.userAgent,
    platform: d.platform,
    maxTouchPoints: d.maxTouchPoints,
    ...(d.userAgentData ? { userAgentData: d.userAgentData } : {}),
  };
  if (share !== null) {
    nav.share = async (data) => {
      s.shares.push(data);
      if (share) await share(data, s.shares.length);
    };
  }
  if (canShare !== null) nav.canShare = (data) => Boolean(canShare && data?.files?.length);
  Object.defineProperty(globalThis, "navigator", { configurable: true, value: nav });
  const w = {
    location: { href: `https://esai.kg${path}`, origin: "https://esai.kg" },
    open: () => {
      s.opened += 1;
    },
    matchMedia: (q) => ({ matches: standalone && q.includes("standalone") }),
  };
  if (telegramProxy) w.TelegramWebviewProxy = { postEvent() {} };
  if (miniApp) w.Telegram = { WebApp: miniApp };
  globalThis.window = w;
  globalThis.location = { pathname: path };
  globalThis.document = {
    visibilityState: "visible",
    body: { appendChild() {} },
    createElement: () => ({
      href: "",
      download: "",
      click() {
        s.clicks.push(this.download);
      },
      remove() {},
    }),
  };
  globalThis.fetch = async (...args) => {
    s.fetches += 1;
    return fetchImpl ? fetchImpl(...args) : fileResponse();
  };
}

const report = (meta) => s.reports.push(meta);
const named = (name) => Object.assign(new Error(`${name} (Load failed https://esai.kg/media/secret.mp4)`), { name });
let n = 0;
const nextUrl = () => `/media/vstudio/2026/10/t${(n += 1)}.mp4`;

afterEach(() => {
  // Ни одна ветка не открывает сам файл: на iPhone это та самая тёмная страница.
  assert.equal(s.opened, 0, "window.open на файл");
  for (const meta of s.reports) {
    const json = JSON.stringify(meta);
    assert.ok(!/media|esai|Mozilla|secret|\.mp4/.test(json), `в событии нет адресов и имён: ${json}`);
  }
});

test("компьютер: файл в «Загрузки», без окна «Поделиться», даже если браузер умеет файлы", async () => {
  for (const device of ["mac", "win"]) {
    setup({ device });
    const url = nextUrl();
    assert.deepEqual(await saveMedia(url, "esai-video.mp4", { report }), { result: "downloaded" });
    assert.deepEqual(s.clicks, ["esai-video.mp4"], device);
    assert.equal(s.shares.length, 0, device);
    assert.equal(s.reports.length, 0, "компьютер событий не шлёт");
  }
});

test("iPhone Safari: файл успел — окно с одним { files }, без title", async () => {
  setup();
  const url = nextUrl();
  assert.deepEqual(await saveMedia(url, "esai-video.mp4", { report }), { result: "saved" });
  assert.equal(s.shares.length, 1);
  assert.deepEqual(Object.keys(s.shares[0]), ["files"]);
  const [file] = s.shares[0].files;
  assert.equal(file.name, "esai-video.mp4");
  assert.equal(file.type, "video/mp4");
  assert.equal(file.size, VIDEO.byteLength);
  assert.equal(s.reports.length, 0, "сохранено — событие не нужно");
});

test("iPhone, файл качается дольше жеста: сразу шторка, загрузка продолжается в ней без повторного запроса", async () => {
  let release;
  // Первый запрос «висит», пока тест его не отпустит; следующие отвечают сразу.
  setup({
    fetchImpl: () =>
      release ? fileResponse() : new Promise((resolve) => (release = () => resolve(fileResponse()))),
  });
  const url = nextUrl();
  const out = await saveMedia(url, "esai-video.mp4", { report, budgetMs: 30 });
  assert.equal(out.result, "sheet");
  assert.equal(out.sheet.reason, "slow");
  assert.equal(out.sheet.failed, false);
  assert.match(out.sheet.diag, /^[A-Z2-9]{6}$/);
  assert.equal(s.shares.length, 0, "без файла окно не открываем — жест истёк бы");
  assert.equal(s.reports.length, 1);
  assert.equal(s.reports[0].step, "sheet");
  assert.equal(s.reports[0].result, "sheet");
  assert.equal(s.reports[0].err, "slow");
  assert.equal(s.reports[0].where, "vstudio");
  assert.equal(s.reports[0].diag, out.sheet.diag);

  // Шторка держит файл и видит прогресс той же загрузки.
  const free = holdMedia(url);
  const seen = [];
  const follow = followMedia(url, (p) => seen.push(p));
  release();
  const blob = await follow.blob;
  follow.stop();
  assert.equal(blob.size, VIDEO.byteLength);
  assert.equal(s.fetches, 1);
  assert.deepEqual(seen.at(-1), { done: VIDEO.byteLength, total: VIDEO.byteLength });
  // Второе нажатие в шторке: окно открывается синхронно с готовым файлом.
  const file = toFile(blob, "esai-video.mp4");
  assert.equal(canShareFileNow(file), true);
  await shareFile(file);
  assert.deepEqual(Object.keys(s.shares[0]), ["files"]);
  free();
  // Шторка закрыта — файл выброшен, следующее нажатие качает заново.
  await followMedia(url, () => {}).blob;
  assert.equal(s.fetches, 2);
  holdMedia(url)();
});

test("установленное приложение (PWA): отказ окна NotAllowedError → шторка с «Сохранить видео», файл в памяти", async () => {
  setup({
    standalone: true,
    share: (_data, count) => {
      if (count === 1) throw named("NotAllowedError");
    },
  });
  const url = nextUrl();
  const out = await saveMedia(url, "esai-video.mp4", { report });
  assert.equal(out.result, "sheet");
  assert.equal(out.sheet.reason, "NotAllowedError");
  assert.equal(s.reports[0].standalone, true);
  assert.equal(s.reports[0].step, "share");
  assert.equal(s.reports[0].err, "NotAllowedError");
  assert.equal(s.reports[0].can_share_file, true);
  assert.equal(s.reports[0].type_ok, true);
  assert.equal(s.reports[0].http, 200);
  const env = detectEnv({ ...navigator, standalone: true, tgProxy: false, tgAndroidBridge: false, tgMiniApp: false, hasShare: true, hasCanShare: true });
  assert.equal(sheetMode(env, true, out.sheet.reason), "share");
  const free = holdMedia(url);
  await followMedia(url, () => {}).blob;
  assert.equal(s.fetches, 1, "второе нажатие берёт файл из памяти");
  free();
});

test("iPhone: человек закрыл окно (AbortError) — без шторки, файл выброшен", async () => {
  setup({ share: () => { throw named("AbortError"); } });
  const url = nextUrl();
  assert.deepEqual(await saveMedia(url, "esai-video.mp4", { report }), { result: "cancelled" });
  assert.equal(s.reports.length, 1);
  assert.equal(s.reports[0].result, "cancelled");
  assert.equal(s.reports[0].err, "AbortError");
  await followMedia(url, () => {}).blob;
  assert.equal(s.fetches, 2);
  holdMedia(url)();
});

test("iPhone: окно сломано (InvalidStateError/TypeError) → шторка с «Скачать файл», а не переход на файл", async () => {
  for (const err of ["InvalidStateError", "TypeError", "DataError"]) {
    setup({ share: () => { throw named(err); } });
    const url = nextUrl();
    const out = await saveMedia(url, "esai-video.mp4", { report });
    assert.equal(out.result, "sheet", err);
    assert.equal(out.sheet.reason, err);
    assert.equal(s.reports[0].err, err);
    const env = detectEnv({ ...navigator, standalone: false, tgProxy: false, tgAndroidBridge: false, tgMiniApp: false, hasShare: true, hasCanShare: true });
    assert.equal(sheetMode(env, true, out.sheet.reason), "files", err);
    holdMedia(url)();
  }
});

test("Telegram на iPhone без файлового окна: шторка «Открыть в Safari» + ссылка /save", async () => {
  setup({ device: "telegramIos", telegramProxy: true, canShare: false });
  const url = nextUrl();
  const out = await saveMedia(url, "esai-scene-1.mp4", { report });
  assert.equal(out.result, "sheet");
  assert.equal(out.sheet.reason, "");
  assert.equal(s.shares.length, 0);
  const meta = s.reports[0];
  assert.equal(meta.inapp, "telegram");
  assert.equal(meta.frozen, false);
  assert.equal(meta.can_share_file, false);
  assert.equal(meta.stage, "canShare");
  assert.equal(meta.os_ver, "26.0");
  const env = detectEnv({ ...navigator, standalone: false, tgProxy: true, tgAndroidBridge: false, tgMiniApp: false, hasShare: true, hasCanShare: true });
  assert.equal(sheetMode(env, false, out.sheet.reason), "inapp");
  holdMedia(url)();
});

test("iPhone без Web Share вовсе: шторка, а не тёмная страница", async () => {
  setup({ share: null, canShare: null });
  const url = nextUrl();
  const out = await saveMedia(url, "esai-video.mp4", { report });
  assert.equal(out.result, "sheet");
  assert.equal(s.reports[0].has_share, false);
  assert.equal(s.reports[0].has_can_share, false);
  holdMedia(url)();
});

test("файл не отдался (404) или вместо файла страница: шторка с «Повторить», событие с кодом ответа", async () => {
  setup({ fetchImpl: () => fileResponse({ status: 404 }) });
  let out = await saveMedia(nextUrl(), "esai-video.mp4", { report });
  assert.equal(out.result, "sheet");
  assert.deepEqual([out.sheet.reason, out.sheet.failed], ["HttpError", true]);
  assert.equal(out.sheet.http, 404, "шторка сразу знает, что файла нет");
  assert.equal(s.shares.length, 0, "HTML ошибки не уходит в окно как .mp4");
  assert.deepEqual([s.reports[0].result, s.reports[0].err, s.reports[0].stage, s.reports[0].http], ["error", "HttpError", "fetch", 404]);

  setup({ fetchImpl: () => fileResponse({ type: "text/html; charset=utf-8" }) });
  out = await saveMedia(nextUrl(), "esai-video.mp4", { report });
  assert.deepEqual([out.sheet.reason, out.sheet.failed], ["BadType", true]);

  setup({ fetchImpl: () => { throw new TypeError("Load failed"); } });
  out = await saveMedia(nextUrl(), "esai-video.mp4", { report });
  assert.deepEqual([out.sheet.reason, out.sheet.failed], ["TypeError", true]);
  assert.equal(s.reports[0].err, "TypeError");
});

test("большой файл (> 50 МБ): без потока по кускам — r.blob(), шторка без «0 из N МБ»", async () => {
  // Куски потока в памяти JS плюс Blob из них — два размера файла; склейка на iPhone бывает > 100 МБ.
  let readerUsed = 0;
  const big = String(STREAM_MAX_BYTES + 1);
  setup({
    fetchImpl: () => ({
      ok: true,
      status: 200,
      headers: new Headers({ "content-type": "video/mp4", "content-length": big }),
      body: {
        getReader() {
          readerUsed += 1;
          throw new Error("поток не нужен");
        },
      },
      blob: async () => new Blob([VIDEO], { type: "video/mp4" }),
    }),
  });
  const url = nextUrl();
  const free = holdMedia(url);
  const seen = [];
  const follow = followMedia(url, (p) => seen.push(p));
  const blob = await follow.blob;
  follow.stop();
  assert.equal(readerUsed, 0);
  assert.equal(blob.size, VIDEO.byteLength);
  assert.equal(blob.type, "video/mp4");
  assert.deepEqual(seen.at(-1), { done: 0, total: 0 }, "длина неизвестна шторке — неопределённая полоса");
  free();

  // До порога — поток с прогрессом, как раньше.
  setup();
  const small = nextUrl();
  const seenSmall = [];
  const f2 = followMedia(small, (p) => seenSmall.push(p));
  await f2.blob;
  f2.stop();
  assert.deepEqual(seenSmall.at(-1), { done: VIDEO.byteLength, total: VIDEO.byteLength });
  holdMedia(small)();
});

test("Android Chrome — как раньше: окно «Поделиться» (только files), без него — файл в «Загрузки»", async () => {
  setup({ device: "android" });
  assert.deepEqual(await saveMedia(nextUrl(), "esai-video.mp4", { report }), { result: "saved" });
  assert.deepEqual(Object.keys(s.shares[0]), ["files"]);
  assert.equal(s.clicks.length, 0);

  setup({ device: "android", canShare: false });
  assert.deepEqual(await saveMedia(nextUrl(), "esai-video.mp4", { report }), { result: "downloaded" });
  assert.deepEqual(s.clicks, ["esai-video.mp4"]);
  assert.deepEqual([s.reports[0].step, s.reports[0].result, s.reports[0].os], ["blob_dl", "downloaded", "android"]);

  // Сломанное окно — запасной путь, как раньше: файл в «Загрузки».
  setup({ device: "android", share: () => { throw named("InvalidStateError"); } });
  assert.deepEqual(await saveMedia(nextUrl(), "esai-video.mp4", { report }), { result: "downloaded" });
  assert.deepEqual(s.clicks, ["esai-video.mp4"]);

  // Жест истёк — шторка со вторым нажатием (раньше — мигающая «Сохранить»).
  setup({ device: "android", share: () => { throw named("NotAllowedError"); } });
  const url = nextUrl();
  const out = await saveMedia(url, "esai-video.mp4", { report });
  assert.equal(out.result, "sheet");
  assert.equal(s.clicks.length, 0);
  holdMedia(url)();
});

test("Telegram Mini App: его окно скачивания, файл не качаем", async () => {
  setup({
    miniApp: {
      initData: "query_id=1",
      isVersionAtLeast: () => true,
      downloadFile: (params) => s.tgDownloads.push(params),
    },
    path: "/tg/studio",
  });
  assert.deepEqual(await saveMedia("/media/cartoon/a.mp4", "esai-cartoon.mp4", { report }), { result: "saved" });
  assert.deepEqual(s.tgDownloads, [{ url: "https://esai.kg/media/cartoon/a.mp4", file_name: "esai-cartoon.mp4" }]);
  assert.equal(s.fetches, 0);
});

test("повторные тапы во время сохранения не плодят окна; prefetch на касание не качает дважды", async () => {
  setup();
  const url = nextUrl();
  prefetchMedia(url);
  prefetchMedia(url);
  const [a, b] = await Promise.all([saveMedia(url, "esai-video.mp4"), saveMedia(url, "esai-video.mp4")]);
  assert.deepEqual([a.result, b.result], ["saved", "cancelled"]);
  assert.equal(s.fetches, 1);
  assert.equal(s.shares.length, 1);
});

/* ---------- прогрев: файл кнопки на экране ---------- */

const MB = 1024 * 1024;
const tick = () => new Promise((resolve) => setImmediate(resolve));
const settle = async () => {
  for (let i = 0; i < 6; i += 1) await tick();
};
/** Убрать запись и её таймер на 2 минуты: иначе тест ждал бы его. */
const forget = (url) => holdMedia(url)();

/** Ответ, который отдаёт куски по мере вызова feed; обрыв сигналом обрывает поток, как в браузере. */
function streamResponse(init, { length = null } = {}) {
  let ctrl;
  const body = new ReadableStream({ start: (c) => (ctrl = c) });
  init?.signal?.addEventListener("abort", () => {
    s.aborts = (s.aborts || 0) + 1;
    try {
      ctrl.error(Object.assign(new Error("aborted"), { name: "AbortError" }));
    } catch {
      /* поток уже закрыт */
    }
  });
  const headers = { "content-type": "video/mp4" };
  if (length != null) headers["content-length"] = String(length);
  return {
    response: new Response(body, { status: 200, headers }),
    feed: (bytes) => ctrl.enqueue(new Uint8Array(bytes)),
    end: () => ctrl.close(),
  };
}

/** Ответы на каждый адрес: тест сам решает, когда файл «докачался». */
function manualFetch() {
  const calls = new Map();
  const pending = new Map();
  const impl = (url, init) => {
    const stream = streamResponse(init);
    calls.set(url, stream);
    const wait = pending.get(url);
    if (wait) wait(stream);
    return stream.response;
  };
  const finish = async (url) => {
    const stream = calls.get(url);
    stream.feed(4096);
    stream.end();
    await settle();
  };
  return { impl, calls, finish };
}

test("canWarmMedia: iPhone — да, экономия трафика и компьютер — нет", () => {
  setup();
  assert.equal(canWarmMedia(), true);
  setup();
  navigator.connection = { saveData: true };
  assert.equal(canWarmMedia(), false);
  setup({ device: "win" });
  assert.equal(canWarmMedia(), false);
});

test("прогрев: файл готов заранее — первое нажатие сразу открывает окно, второго запроса нет", async () => {
  setup();
  const url = nextUrl();
  const leave = wantMedia(url);
  await settle();
  assert.equal(s.fetches, 1);
  const out = await saveMedia(url, "esai-video.mp4", { report, budgetMs: 1 });
  assert.deepEqual(out, { result: "saved" }, "ждать файл не пришлось");
  assert.equal(s.fetches, 1);
  assert.equal(s.shares.length, 1);
  assert.equal(s.reports.length, 0, "шторки не было");
  leave();
  forget(url);
});

test("прогрев: окно закрыли, кнопка на экране — второе нажатие берёт файл из памяти", async () => {
  setup({ share: (_d, count) => { if (count === 1) throw named("AbortError"); } });
  const url = nextUrl();
  const leave = wantMedia(url);
  await settle();
  assert.deepEqual(await saveMedia(url, "esai-video.mp4"), { result: "cancelled" });
  assert.deepEqual(await saveMedia(url, "esai-video.mp4", { budgetMs: 1 }), { result: "saved" });
  assert.equal(s.fetches, 1);
  leave();
  forget(url);
});

test("прогрев: длина больше 30 МБ — ответ оборван, повторно не качаем, нажатие работает как раньше", async () => {
  const big = String(30 * MB + 1);
  let inits = [];
  setup({
    fetchImpl: (_url, init) => {
      inits.push(init);
      return {
        ok: true,
        status: 200,
        headers: new Headers({ "content-type": "video/mp4", "content-length": big }),
        body: null,
        blob: async () => new Blob([VIDEO], { type: "video/mp4" }),
      };
    },
  });
  const url = nextUrl();
  const leave = wantMedia(url);
  await settle();
  assert.equal(s.fetches, 1);
  assert.equal(inits[0].signal.aborted, true, "браузер не докачивает файл в никуда");

  // Кнопка ушла и вернулась: прогрев по кругу не запускается.
  leave();
  const again = wantMedia(url);
  await settle();
  assert.equal(s.fetches, 1);

  // Нажатие качает файл обычным путём, без порога.
  assert.deepEqual(await saveMedia(url, "esai-video.mp4", { report }), { result: "saved" });
  assert.equal(s.fetches, 2);
  assert.equal(inits[1].signal, undefined, "загрузку по нажатию обрывать нечем");
  again();
  forget(url);
});

test("прогрев: сервер не назвал длину — обрыв по факту на 30 МБ", async () => {
  const net = manualFetch();
  setup({ fetchImpl: net.impl });
  const url = nextUrl();
  const leave = wantMedia(url);
  await settle();
  const stream = net.calls.get(url);
  stream.feed(16 * MB);
  await settle();
  assert.equal(s.aborts || 0, 0);
  stream.feed(16 * MB);
  await settle();
  assert.equal(s.aborts, 1);
  // Запись убрана — память свободна, а нажатие начнёт загрузку заново.
  const follow = followMedia(url, () => {});
  assert.equal(s.fetches, 2);
  follow.stop();
  await net.finish(url);
  await follow.blob;
  leave();
  forget(url);
});

test("прогрев: нажатие во время загрузки тяжёлого файла отменяет порог — ошибки вместо файла нет", async () => {
  const net = manualFetch();
  setup({ fetchImpl: net.impl });
  const url = nextUrl();
  const leave = wantMedia(url);
  await settle();
  prefetchMedia(url); // палец на кнопке
  const stream = net.calls.get(url);
  stream.feed(31 * MB);
  await settle();
  assert.equal(s.aborts || 0, 0, "человек ждёт файл — обрывать нельзя");
  const save = saveMedia(url, "esai-video.mp4", { report, budgetMs: 1000 });
  stream.end();
  assert.deepEqual(await save, { result: "saved" });
  assert.equal(s.fetches, 1);
  assert.equal(s.shares[0].files[0].size, 31 * MB);
  leave();
  forget(url);
});

test("прогрев: ушла с экрана посреди загрузки — обрыв; вернулась — снова; нажатая — не обрывается", async () => {
  const net = manualFetch();
  setup({ fetchImpl: net.impl });
  const url = nextUrl();
  wantMedia(url)();
  await settle();
  assert.equal(s.aborts, 1);
  const back = wantMedia(url);
  await settle();
  assert.equal(s.fetches, 2, "обрыв нашими руками не считается неудачей");

  prefetchMedia(url);
  back();
  await settle();
  assert.equal(s.aborts, 1, "человек нажал — файл докачается, даже если кнопка уехала");
  await net.finish(url);
  forget(url);
});

test("прогрев: одновременно один файл, следующий ждёт очереди, в памяти два", async () => {
  const net = manualFetch();
  setup({ fetchImpl: net.impl });
  const [a, b, c] = [nextUrl(), nextUrl(), nextUrl()];
  const leaveA = wantMedia(a);
  const leaveB = wantMedia(b);
  const leaveC = wantMedia(c);
  await settle();
  assert.deepEqual([...net.calls.keys()], [a], "второй файл ждёт");
  await net.finish(a);
  assert.deepEqual([...net.calls.keys()], [a, b]);
  await net.finish(b);
  assert.deepEqual([...net.calls.keys()], [a, b], "в памяти уже два, и оба на экране — третий ждёт");

  // Первая кнопка ушла с экрана: её файл вытесняется ради той, что на экране.
  leaveA();
  await settle();
  assert.deepEqual([...net.calls.keys()], [a, b, c]);
  await net.finish(c);
  const seen = net.calls.size;
  followMedia(a, () => {}).stop();
  assert.equal(net.calls.size, seen, "вытесненный файл качается заново только по запросу");
  assert.equal(s.fetches, 4);
  await net.finish(a);
  leaveB();
  leaveC();
  for (const url of [a, b, c]) forget(url);
});

test("прогрев: вытесняется только прогретое — файл под шторкой и файл по нажатию остаются", async () => {
  const net = manualFetch();
  setup({ fetchImpl: net.impl });
  const [a, b, c] = [nextUrl(), nextUrl(), nextUrl()];
  const leaveA = wantMedia(a);
  await settle();
  await net.finish(a);
  const free = holdMedia(a);
  leaveA();
  prefetchMedia(b);
  await net.finish(b);
  const leaveC = wantMedia(c);
  await settle();
  assert.equal(net.calls.has(c), false, "места нет, а выбросить нечего");
  free();
  await settle();
  assert.equal(net.calls.has(c), true, "шторка закрылась — место освободилось");
  await net.finish(c);
  leaveC();
  for (const url of [b, c]) forget(url);
});

test("прогрев: пока кнопка на экране, таймер файл не выбрасывает; ушла — живёт ещё 2 минуты", async (t) => {
  setup();
  t.mock.timers.enable({ apis: ["setTimeout"] });
  const url = nextUrl();
  const leave = wantMedia(url);
  await settle();
  t.mock.timers.tick(10 * 60 * 1000);
  await followMedia(url, () => {}).blob;
  assert.equal(s.fetches, 1, "человек досматривал ролик — файл на месте");

  leave();
  t.mock.timers.tick(119_000);
  await followMedia(url, () => {}).blob;
  assert.equal(s.fetches, 1, "вернулся через минуту — файл ещё здесь");
  t.mock.timers.tick(2000);
  await followMedia(url, () => {}).blob;
  assert.equal(s.fetches, 2, "прошло две минуты — выброшен");
  forget(url);
});

test("прогрев: шторка закрыта, кнопка на экране — файл остаётся; кнопки нет — выброшен", async () => {
  setup();
  const url = nextUrl();
  const leave = wantMedia(url);
  await settle();
  holdMedia(url)();
  await followMedia(url, () => {}).blob;
  assert.equal(s.fetches, 1);
  leave();
  holdMedia(url)();
  await followMedia(url, () => {}).blob;
  assert.equal(s.fetches, 2);
  forget(url);
});

test("тяжёлый файл по нажатию: кнопка на экране его в памяти не держит", async () => {
  const big = String(120 * MB);
  setup({
    fetchImpl: () => ({
      ok: true,
      status: 200,
      headers: new Headers({ "content-type": "video/mp4", "content-length": big }),
      body: null,
      blob: async () => new Blob([VIDEO], { type: "video/mp4" }),
    }),
  });
  const url = nextUrl();
  const leave = wantMedia(url);
  await settle();
  assert.equal(s.fetches, 1, "прогрев оборван по заголовку");

  // Нажали, файл докачался и отдан в окно: на следующий раз его снова качаем, а не держим 120 МБ.
  assert.deepEqual(await saveMedia(url, "esai-film.mp4", { report }), { result: "saved" });
  assert.equal(s.fetches, 2);
  holdMedia(url)();
  await followMedia(url, () => {}).blob;
  assert.equal(s.fetches, 3, "выброшен, хотя кнопка на экране");
  holdMedia(url)();
  leave();
  forget(url);
});

test("нажатие на тяжёлый файл без отпускания: докачанный файл не лежит до ухода кнопки", async (t) => {
  t.mock.timers.enable({ apis: ["setTimeout"] });
  const big = String(120 * MB);
  setup({
    fetchImpl: () => ({
      ok: true,
      status: 200,
      headers: new Headers({ "content-type": "video/mp4", "content-length": big }),
      body: null,
      blob: async () => new Blob([VIDEO], { type: "video/mp4" }),
    }),
  });
  const url = nextUrl();
  const leave = wantMedia(url);
  prefetchMedia(url);
  for (let i = 0; i < 5; i += 1) await Promise.resolve();
  await followMedia(url, () => {}).blob;
  const before = s.fetches;
  t.mock.timers.tick(120_000);
  await followMedia(url, () => {}).blob;
  assert.equal(s.fetches, before + 1, "через две минуты выброшен");
  leave();
  forget(url);
});

test("нажатие останавливает прогрев другого файла, потом он возвращается", async () => {
  const net = manualFetch();
  setup({ fetchImpl: net.impl });
  const warm = nextUrl();
  const tapped = nextUrl();
  const leave = wantMedia(warm);
  await settle();
  assert.equal(s.fetches, 1);

  prefetchMedia(tapped);
  await settle();
  assert.equal(s.aborts, 1, "канал отдан файлу, который ждёт человек");
  assert.equal(s.fetches, 2);

  await net.finish(tapped);
  await settle();
  assert.equal(s.fetches, 3, "обрыв нашими руками не считается неудачей");
  await net.finish(warm);
  leave();
  forget(warm);
  forget(tapped);
});

test("нажатие на готовый файл не трогает чужой прогрев: канал никому не нужен", async () => {
  const net = manualFetch();
  setup({ fetchImpl: net.impl });
  const ready = nextUrl();
  const warm = nextUrl();
  const leaveReady = wantMedia(ready);
  await settle();
  await net.finish(ready);
  const leaveWarm = wantMedia(warm);
  await settle();
  assert.equal(s.fetches, 2);

  prefetchMedia(ready);
  await settle();
  assert.deepEqual(await saveMedia(ready, "esai-video.mp4", { report }), { result: "saved" });
  await settle();
  assert.equal(s.aborts || 0, 0);
  assert.equal(s.fetches, 2);
  await net.finish(warm);
  leaveWarm();
  leaveReady();
  forget(warm);
  forget(ready);
});

test("прогрев: сервер отказал — без повторов по кругу; нажатие покажет шторку с кодом ответа", async () => {
  setup({ fetchImpl: () => fileResponse({ status: 404 }) });
  const url = nextUrl();
  const leave = wantMedia(url);
  await settle();
  assert.equal(s.fetches, 1);
  leave();
  wantMedia(url)();
  await settle();
  assert.equal(s.fetches, 1);
  const out = await saveMedia(url, "esai-video.mp4", { report });
  assert.equal(out.result, "sheet");
  assert.equal(out.sheet.http, 404);
});
