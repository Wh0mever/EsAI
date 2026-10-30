// «Скачать»: среда (iPhone, встроенные браузеры, PWA), режим шторки, ссылка /save и диагностика (tools/saveEnv.ts).
// Запуск (Node 22.6+):  node --experimental-strip-types --test src/tools/saveEnv.test.mjs
import { test } from "node:test";
import assert from "node:assert/strict";
import {
  afterShareError,
  detectEnv,
  envLabel,
  fileFallback,
  isHandheld,
  mediaKind,
  mimeFor,
  newDiagCode,
  openableUrl,
  parseSaveTarget,
  safeMediaPath,
  sameOriginMediaPath,
  saveDiagMeta,
  saveLinkFor,
  sheetMode,
  surfaceOf,
} from "./saveEnv.ts";

const base = {
  platform: "iPhone",
  maxTouchPoints: 5,
  uaMobile: null,
  standalone: false,
  tgProxy: false,
  tgAndroidBridge: false,
  tgMiniApp: false,
  hasShare: true,
  hasCanShare: true,
};
const ios = (userAgent, extra = {}) => ({ ...base, userAgent, ...extra });
const android = (userAgent, extra = {}) => ({ ...base, platform: "Linux armv8l", uaMobile: true, userAgent, ...extra });
const desktop = (userAgent, extra = {}) => ({ ...base, platform: "MacIntel", maxTouchPoints: 0, uaMobile: false, userAgent, ...extra });

const SAFARI_18 =
  "Mozilla/5.0 (iPhone; CPU iPhone OS 18_6 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.6 Mobile/15E148 Safari/604.1";
// Safari 26: «OS 18_6» заморожен, настоящая версия — в Version/.
const SAFARI_26 =
  "Mozilla/5.0 (iPhone; CPU iPhone OS 18_6 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/26.0 Mobile/15E148 Safari/604.1";
// Встроенный браузер Telegram iOS: UA как у Safari, но сборка настоящая вместо 15E148.
const TG_IOS =
  "Mozilla/5.0 (iPhone; CPU iPhone OS 26_0_1 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/26.0.1 Mobile/23A355 Safari/604.1";
const CHROME_IOS =
  "Mozilla/5.0 (iPhone; CPU iPhone OS 26_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) CriOS/141.0.7390.41 Mobile/15E148 Safari/604.1";
const INSTAGRAM_IOS =
  "Mozilla/5.0 (iPhone; CPU iPhone OS 18_5 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E148 Instagram 385.0.0.21.95 (iPhone15,3; iOS 18_5; ru_RU; ru; scale=3.00; 1290x2796; 123456789)";
const BARE_WKWEBVIEW =
  "Mozilla/5.0 (iPhone; CPU iPhone OS 18_5 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E148";
// Telegram Android, встроенный браузер: «; wv)» вырезан, модель заменена на K, Version/ убран.
const TG_ANDROID_BROWSER =
  "Mozilla/5.0 (Linux; Android 14; K) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/141.0.0.0 Mobile Safari/537.36";
const TG_ANDROID_MINIAPP = `${TG_ANDROID_BROWSER} Telegram-Android/12.1.1 (Samsung SM-S918B; Android 14; SDK 34; HIGH)`;
const ANDROID_WV =
  "Mozilla/5.0 (Linux; Android 13; SM-A525F Build/TP1A.220624.014; wv) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/141.0.0.0 Mobile Safari/537.36";
const ANDROID_CHROME =
  "Mozilla/5.0 (Linux; Android 14; K) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/141.0.0.0 Mobile Safari/537.36";
const MAC_SAFARI =
  "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.0 Safari/605.1.15";

test("iOS: версия ОС и Safari 26 с замороженным OS 18_6", () => {
  assert.deepEqual(detectEnv(ios(SAFARI_18)), {
    os: "ios", osVer: "18.6", browser: "safari", inApp: "", standalone: false, frozenBuild: true, handheld: true,
  });
  const s26 = detectEnv(ios(SAFARI_26));
  assert.equal(s26.osVer, "26.0");
  assert.equal(s26.browser, "safari");
  assert.equal(detectEnv(ios(CHROME_IOS)).osVer, "26.0");
  assert.equal(detectEnv(ios(CHROME_IOS)).browser, "chrome");
  // iPadOS выдаёт себя за Mac — отличает только тачскрин.
  assert.equal(detectEnv({ ...desktop(MAC_SAFARI), maxTouchPoints: 5 }).os, "ios");
  assert.equal(detectEnv(desktop(MAC_SAFARI)).handheld, false);
});

test("встроенные браузеры и установленное приложение", () => {
  const tg = detectEnv(ios(TG_IOS, { tgProxy: true }));
  assert.equal(tg.inApp, "telegram");
  assert.equal(tg.osVer, "26.0");
  assert.equal(tg.frozenBuild, false, "у Telegram iOS настоящая сборка вместо 15E148");
  // Без моста Telegram iOS по UA неотличим от Safari — кроме сборки (поле frozen в событии).
  assert.equal(detectEnv(ios(TG_IOS)).inApp, "");
  assert.equal(detectEnv(ios(INSTAGRAM_IOS)).inApp, "instagram");
  assert.equal(detectEnv(ios(BARE_WKWEBVIEW)).inApp, "wkwebview");
  assert.equal(detectEnv(android(TG_ANDROID_BROWSER, { tgProxy: true, tgAndroidBridge: true })).inApp, "telegram");
  assert.equal(detectEnv(android(TG_ANDROID_MINIAPP, { tgMiniApp: true })).inApp, "tg_miniapp");
  assert.equal(detectEnv(android(ANDROID_WV)).inApp, "android_wv");
  assert.equal(detectEnv(android(ANDROID_CHROME)).inApp, "");
  assert.equal(detectEnv(ios(SAFARI_18, { standalone: true })).standalone, true);
});

test("компьютер с сенсорным экраном — не телефон; mobile из userAgentData решает за неизвестный UA", () => {
  const touchLaptop = {
    userAgent: "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36 Edg/130.0.0.0",
    platform: "Win32",
    maxTouchPoints: 10,
    uaMobile: false,
  };
  assert.equal(isHandheld(touchLaptop), false);
  const unknown = { userAgent: "Mozilla/5.0 (X11; Linux aarch64)", platform: "Linux aarch64", maxTouchPoints: 5 };
  assert.equal(isHandheld(unknown), false);
  assert.equal(isHandheld({ ...unknown, uaMobile: true }), true);
});

test("ошибки share и режим шторки", () => {
  assert.equal(afterShareError("AbortError"), "cancelled");
  for (const n of ["NotAllowedError", "InvalidStateError", "TypeError", "DataError", ""]) {
    assert.equal(afterShareError(n), "sheet", n);
  }
  const safari = detectEnv(ios(SAFARI_26));
  const tg = detectEnv(ios(TG_IOS, { tgProxy: true }));
  const pwa = detectEnv(ios(SAFARI_26, { standalone: true }));
  // Жест истёк — второе нажатие в шторке откроет окно.
  assert.equal(sheetMode(safari, true, "NotAllowedError"), "share");
  assert.equal(sheetMode(safari, true, "slow"), "share");
  assert.equal(sheetMode(pwa, true, "NotAllowedError"), "share");
  // Окно с файлом здесь не работает — обычная ссылка на файл.
  assert.equal(sheetMode(safari, false, ""), "files");
  assert.equal(sheetMode(safari, true, "InvalidStateError"), "files");
  assert.equal(sheetMode(safari, true, "TypeError"), "files");
  // Встроенный браузер iPhone без файлового окна — путь в Safari.
  assert.equal(sheetMode(tg, false, ""), "inapp");
  assert.equal(sheetMode(tg, true, "DataError"), "inapp");
  assert.equal(sheetMode(tg, true, "NotAllowedError"), "share");
  assert.equal(sheetMode(detectEnv(ios(INSTAGRAM_IOS)), false, ""), "inapp");
  // Android: подсказки про Safari нет, файл качается сам.
  assert.equal(sheetMode(detectEnv(android(ANDROID_WV)), false, ""), "files");
  assert.equal(sheetMode(detectEnv(android(ANDROID_CHROME)), true, "NotAllowedError"), "share");
  // Компьютер: окно «Поделиться» без «Сохранить» — только файл.
  assert.equal(sheetMode(detectEnv(desktop(MAC_SAFARI)), true, ""), "files");
});

test("ссылка /save: только наш /media/, без открытого редиректа", () => {
  const origin = "https://esai.kg";
  assert.equal(sameOriginMediaPath("/media/vstudio/2026/10/a1b2.mp4", origin), "/media/vstudio/2026/10/a1b2.mp4");
  assert.equal(sameOriginMediaPath("https://esai.kg/media/cartoon/scenes/ab_cd-1.mp4?x=1", origin), "/media/cartoon/scenes/ab_cd-1.mp4");
  for (const bad of [
    "https://evil.example/media/x.mp4",
    "//evil.example/media/x.mp4",
    "/media/../core/settings.py",
    "/media/x/../../etc.mp4",
    "/media//x.mp4",
    "/media/x.html",
    "/media/x%2e%2e/y.mp4",
    "/static/x.mp4",
    "javascript:alert(1)//x.mp4",
    "",
  ]) {
    assert.equal(sameOriginMediaPath(bad, origin), null, bad);
  }

  const link = saveLinkFor("/media/vstudio/a1b2.mp4", "esai-video-1.mp4", origin);
  assert.equal(link, "/save?f=%2Fmedia%2Fvstudio%2Fa1b2.mp4&n=esai-video-1.mp4");
  const q = new URLSearchParams(link.split("?")[1]);
  assert.deepEqual(parseSaveTarget(q.get("f"), q.get("n")), {
    path: "/media/vstudio/a1b2.mp4", filename: "esai-video-1.mp4", kind: "video",
  });
  assert.equal(saveLinkFor("https://cdn.example/media/a.mp4", "a.mp4", origin), null, "чужой файл — без ссылки");

  // Неверное имя файла — безопасное имя по расширению; неверный путь — null.
  assert.deepEqual(parseSaveTarget("/media/chat/p.png", "../../evil name.png"), {
    path: "/media/chat/p.png", filename: "esai-file.png", kind: "image",
  });
  assert.equal(parseSaveTarget("https://evil.example/x.mp4", "x.mp4"), null);
  assert.equal(parseSaveTarget(["/media/a.mp4"], "a.mp4"), null, "повтор параметра — не строка");
  assert.equal(parseSaveTarget(undefined, undefined), null);
});

test("ссылка /save: префикс /media/ с учётом регистра, как в nginx; расширение — без", () => {
  // /Media/… nginx отдал бы в Next — вместо файла HTML 404.
  for (const bad of ["/Media/x.mp4", "/MEDIA/x.mp4", "/media/x.MP4.html", "/media/x.exe", "/media/x"]) {
    assert.equal(safeMediaPath(bad), null, bad);
  }
  assert.equal(parseSaveTarget("/Media/vstudio/a.mp4", "a.mp4"), null);
  assert.equal(sameOriginMediaPath("https://esai.kg/Media/a.mp4", "https://esai.kg"), null);
  assert.equal(safeMediaPath("/media/vstudio/Clip_01.MP4"), "/media/vstudio/Clip_01.MP4");
  assert.equal(safeMediaPath("/media/chat/IMG.JPEG"), "/media/chat/IMG.JPEG");
});

test("запасной путь к файлу: свой /media/ — ссылка, чужой — из памяти или во вкладке, на iPhone — нет", () => {
  const origin = "https://esai.kg";
  const own = { filePath: "/media/vstudio/a.mp4", url: "/media/vstudio/a.mp4", origin, hasBlob: false };
  const foreign = { filePath: null, url: "https://cdn.provider.example/out/a.png?sig=1", origin, hasBlob: false };
  // Свой файл: <a download> и после сбоя загрузки, и на iPhone (в «Файлы», без тёмной страницы).
  for (const os of ["ios", "android", "other"]) assert.equal(fileFallback({ ...own, os }), "link", os);
  // Чужой без CORS после сбоя: компьютер и Android открывают файл во вкладке, как до шторки.
  assert.equal(fileFallback({ ...foreign, os: "other" }), "open");
  assert.equal(fileFallback({ ...foreign, os: "android" }), "open");
  // iPhone: переход на файл — та самая тёмная страница.
  assert.equal(fileFallback({ ...foreign, os: "ios" }), "none");
  // Чужой, но файл уже в памяти — сохранить из памяти, а не показывать «не удалось».
  assert.equal(fileFallback({ ...foreign, os: "other", hasBlob: true }), "blob");
  assert.equal(fileFallback({ ...foreign, os: "ios", hasBlob: true }), "none");
  // Открыть можно только http(s).
  for (const bad of ["javascript:alert(1)", "data:image/png;base64,AAAA", "blob:https://esai.kg/x", ""]) {
    assert.equal(openableUrl(bad, origin), null, bad);
    assert.equal(fileFallback({ ...foreign, url: bad, os: "other" }), "none", bad);
  }
  assert.equal(openableUrl("https://cdn.provider.example/a.png", origin), "https://cdn.provider.example/a.png");
  assert.equal(openableUrl("/media/a.mp3", origin), "https://esai.kg/media/a.mp3");
});

test("тип файла и вид: по расширению, когда сервер его не назвал", () => {
  assert.equal(mimeFor("", "esai-scene-1.mp4"), "video/mp4");
  assert.equal(mimeFor("", "pic.JPG"), "image/jpeg");
  assert.equal(mimeFor("video/webm", "x.mp4"), "video/webm");
  assert.equal(mimeFor("", "noext"), "application/octet-stream");
  assert.equal(mediaKind("esai-video.mp4"), "video");
  assert.equal(mediaKind("x", "/media/a.mov?v=2"), "video");
  assert.equal(mediaKind("image.png", "/media/a.png"), "image");
});

test("раздел сайта без uid", () => {
  assert.equal(surfaceOf("/video-studio/3f9c1d2e-aaaa-bbbb"), "vstudio");
  assert.equal(surfaceOf("/studio"), "cartoon");
  assert.equal(surfaceOf("/tg/studio"), "tg_studio");
  assert.equal(surfaceOf("/v/abc123"), "shared");
  assert.equal(surfaceOf("/save"), "save_page");
  assert.equal(surfaceOf("/merge"), "merge");
  assert.equal(surfaceOf("/"), "chat");
  assert.equal(surfaceOf("/dashboard/xyz"), "chat");
  assert.equal(surfaceOf("/pricing"), "other");
});

test("meta: только перечислимое, без адресов и сырых строк", () => {
  const env = detectEnv(ios(TG_IOS, { tgProxy: true }));
  const input = {
    env,
    hints: { hasShare: true, hasCanShare: true },
    surface: "vstudio",
    kind: "video",
    step: "share",
    result: "sheet",
    err: "NotAllowedError",
    stage: "share",
    canShareFile: true,
    waitedMs: 6234,
    prefetchHit: false,
    sizeBytes: 3_150_000,
    typeOk: true,
    httpStatus: 200,
    attempt: 1,
    diag: "K7Q2XM",
    visible: true,
  };
  const meta = saveDiagMeta(input);
  assert.deepEqual(Object.keys(meta).sort(), [
    "browser", "can_share_file", "diag", "err", "frozen", "has_can_share", "has_share", "http", "inapp", "kind", "n",
    "os", "os_ver", "prefetch_hit", "result", "size_kb", "stage", "standalone", "step", "type_ok", "v", "vis",
    "wait_ms", "where",
  ]);
  assert.equal(meta.v, "s4");
  assert.equal(meta.err, "NotAllowedError");
  assert.equal(meta.wait_ms, 6200);
  assert.equal(meta.size_kb, 3072);
  assert.equal(meta.inapp, "telegram");
  const json = JSON.stringify(meta);
  assert.ok(json.length < 600, `meta ${json.length} байт`);
  for (const v of Object.values(meta)) assert.ok(v === null || ["string", "number", "boolean"].includes(typeof v));
  assert.ok(!/media|https?:|esai|Mozilla/.test(json), json);
  // Сообщение ошибки (может содержать адрес) не уходит — только имя.
  const bad = saveDiagMeta({ ...input, err: "Load failed https://esai.kg/media/x.mp4", waitedMs: 999_999, attempt: 500 });
  assert.equal(bad.err, "other");
  assert.equal(bad.wait_ms, 60_000);
  assert.equal(bad.n, 99);
});

test("код для поддержки и подвал шторки", () => {
  let i = 0;
  const seq = [0, 0.5, 0.99, 0.1, 0.2, 0.3];
  const code = newDiagCode(() => seq[i++]);
  assert.match(code, /^[A-HJ-NP-Z2-9]{6}$/);
  assert.equal(code.length, 6);
  assert.match(newDiagCode(), /^[A-HJ-NP-Z2-9]{6}$/);
  assert.equal(envLabel(detectEnv(ios(TG_IOS, { tgProxy: true }))), "iOS 26.0 · Telegram · s4");
  assert.equal(envLabel(detectEnv(ios(SAFARI_26, { standalone: true }))), "iOS 26.0 · Safari · PWA · s4");
  assert.equal(envLabel(detectEnv(android(ANDROID_CHROME))), "Android 14 · Chrome · s4");
});
