/**
 * saveEnv — чистые функции для «Скачать»: где мы (телефон, встроенный браузер,
 * установленное приложение), какой шаг выбрать, что показать в шторке и что
 * отправить в диагностику. Без window и navigator — проверяется тестом в Node
 * (saveEnv.test.mjs); браузерную часть собирает tools/saveMedia.
 */

/** Что известно об устройстве — отдельно от navigator, чтобы выбор пути проверялся тестом. */
export type DeviceHints = {
  userAgent: string;
  platform: string;
  maxTouchPoints: number;
  /** navigator.userAgentData.mobile (Chromium); нет — null. */
  uaMobile?: boolean | null;
};

export type EnvHints = DeviceHints & {
  /** matchMedia("(display-mode: standalone)") или navigator.standalone — установленное приложение. */
  standalone: boolean;
  /** window.TelegramWebviewProxy есть: встроенный браузер Telegram (iOS и Android) или Mini App. */
  tgProxy: boolean;
  /** window.TelegramWebview есть — только Android: через этот мост Telegram подменяет navigator.share. */
  tgAndroidBridge: boolean;
  /** Telegram.WebApp.initData непустой — мы внутри Mini App. */
  tgMiniApp: boolean;
  hasShare: boolean;
  hasCanShare: boolean;
};

/** iPhone/iPod/iPad, включая iPadOS, который выдаёт себя за Mac, но с тачскрином. */
export function isAppleHandheld(h: DeviceHints): boolean {
  return /iP(hone|ad|od)/.test(h.userAgent) || (h.platform === "MacIntel" && h.maxTouchPoints > 1);
}

/**
 * Телефон или планшет. Ноутбук с сенсорным экраном — компьютер: тач у него есть,
 * а «мобильного» признака в user agent нет.
 */
export function isHandheld(h: DeviceHints): boolean {
  if (isAppleHandheld(h) || /Android/i.test(h.userAgent) || h.uaMobile === true) return true;
  return h.maxTouchPoints > 0 && /Mobi|Tablet|Silk|KFAPWI/i.test(h.userAgent);
}

export type SaveOs = "ios" | "android" | "other";
export type InApp =
  | ""
  | "telegram"
  | "tg_miniapp"
  | "instagram"
  | "facebook"
  | "tiktok"
  | "vk"
  | "line"
  | "snapchat"
  | "google_app"
  | "wkwebview"
  | "android_wv";
export type Browser = "safari" | "chrome" | "firefox" | "edge" | "yandex" | "opera" | "samsung" | "duckduckgo" | "other";

export type SaveEnv = {
  os: SaveOs;
  /** Мажор.минор ОС, «» — неизвестно. */
  osVer: string;
  browser: Browser;
  inApp: InApp;
  standalone: boolean;
  /** Safari заморозил сборку «Mobile/15E148»; у Telegram iOS там настоящая сборка. */
  frozenBuild: boolean;
  handheld: boolean;
};

function majorMinor(v: string): string {
  const [a, b] = v.split(/[._]/);
  if (!a) return "";
  return b ? `${a}.${b}` : a;
}

export function detectEnv(h: EnvHints): SaveEnv {
  const ua = h.userAgent || "";
  const os: SaveOs = isAppleHandheld(h) ? "ios" : /Android/i.test(ua) ? "android" : "other";

  let osVer = "";
  if (os === "ios") {
    const osTok = /OS (\d+[_.]\d+(?:[_.]\d+)?) like Mac OS X/.exec(ua)?.[1] || "";
    const verTok = /Version\/(\d+(?:\.\d+)?)/.exec(ua)?.[1] || "";
    const osMajor = Number(osTok.split(/[._]/)[0] || 0);
    const verMajor = Number(verTok.split(".")[0] || 0);
    // Safari 26 заморозил «OS 18_6» в user agent — настоящий номер стоит в Version/.
    osVer = verMajor >= 26 && osMajor === 18 ? majorMinor(verTok) : majorMinor(osTok || verTok);
  } else if (os === "android") {
    osVer = majorMinor(/Android (\d+(?:\.\d+)?)/.exec(ua)?.[1] || "");
  }

  let browser: Browser = "other";
  if (/CriOS|Chrome\//.test(ua) && !/Edg|OPR|OPT\/|YaBrowser|SamsungBrowser/.test(ua)) browser = "chrome";
  if (/FxiOS|Firefox\//.test(ua)) browser = "firefox";
  if (/EdgiOS|EdgA|Edg\//.test(ua)) browser = "edge";
  if (/YaBrowser|YaApp/.test(ua)) browser = "yandex";
  if (/OPT\/|OPR\/|OPiOS/.test(ua)) browser = "opera";
  if (/SamsungBrowser/.test(ua)) browser = "samsung";
  if (/DuckDuckGo|Ddg\//.test(ua)) browser = "duckduckgo";
  if (browser === "other" && os === "ios" && /Version\/[\d.]+.*Safari\//.test(ua)) browser = "safari";

  let inApp: InApp = "";
  if (h.tgMiniApp) inApp = "tg_miniapp";
  else if (h.tgProxy || h.tgAndroidBridge || /Telegram/i.test(ua)) inApp = "telegram";
  else if (/Instagram/.test(ua)) inApp = "instagram";
  else if (/FBAN|FBAV|FB_IAB|FBIOS/.test(ua)) inApp = "facebook";
  else if (/musical_ly|BytedanceWebview|TikTok/i.test(ua)) inApp = "tiktok";
  else if (/VKClient|vkclient/.test(ua)) inApp = "vk";
  else if (/\bLine\//.test(ua)) inApp = "line";
  else if (/Snapchat/.test(ua)) inApp = "snapchat";
  else if (/\bGSA\//.test(ua)) inApp = "google_app";
  // WKWebView чужого приложения без его имени в user agent: у Safari и у
  // браузеров на его движке «Safari/» в строке есть всегда.
  else if (os === "ios" && !/Safari\//.test(ua)) inApp = "wkwebview";
  else if (os === "android" && /; wv\)/.test(ua)) inApp = "android_wv";

  return {
    os,
    osVer,
    browser,
    inApp,
    standalone: h.standalone,
    frozenBuild: /Mobile\/15E148/.test(ua),
    handheld: isHandheld(h),
  };
}

/**
 * Режим шторки «Сохранить». В каждом есть видимый следующий шаг — на сам файл
 * (тёмную страницу) не уводит ни один.
 * share — файл в памяти, кнопка открывает системное окно сразу, в жесте;
 * inapp  — встроенный браузер iPhone без файлового окна: «Открыть в Safari»,
 *          ссылка на /save и запасное «Скачать файл»;
 * files  — «Скачать файл» обычной ссылкой этого же сайта.
 */
export type SheetMode = "share" | "inapp" | "files";

/** Ошибки share(), после которых второе нажатие не поможет: окно с файлом здесь не работает. */
const SHARE_BROKEN = new Set(["InvalidStateError", "TypeError", "DataError"]);

export function sheetMode(env: SaveEnv, canShareFile: boolean | null, lastError: string): SheetMode {
  if (env.handheld && canShareFile && !SHARE_BROKEN.has(lastError)) return "share";
  // «Открыть в Safari» — подсказка только для iPhone; на Android файл качается сам.
  if (env.os === "ios" && env.inApp && env.inApp !== "tg_miniapp") return "inapp";
  return "files";
}

/** Что делать, когда share() отклонён: AbortError — человек сам закрыл окно. */
export function afterShareError(name: string): "cancelled" | "sheet" {
  return name === "AbortError" ? "cancelled" : "sheet";
}

const VIDEO_EXT = /\.(mp4|m4v|mov|webm)$/i;

export function mediaKind(filename: string, url = ""): "video" | "image" {
  const path = url.split(/[?#]/)[0];
  return VIDEO_EXT.test(filename) || VIDEO_EXT.test(path) ? "video" : "image";
}

const MIME: Record<string, string> = {
  mp4: "video/mp4",
  m4v: "video/mp4",
  mov: "video/quicktime",
  webm: "video/webm",
  jpg: "image/jpeg",
  jpeg: "image/jpeg",
  png: "image/png",
  webp: "image/webp",
  gif: "image/gif",
};

/**
 * Тип файла для окна «Поделиться». Без типа iOS не предлагает «Сохранить видео»,
 * а canShare может ответить «нельзя» — берём его из расширения.
 */
export function mimeFor(blobType: string, filename: string): string {
  if (blobType) return blobType;
  const ext = /\.([a-z0-9]+)$/i.exec(filename)?.[1]?.toLowerCase() || "";
  return MIME[ext] || "application/octet-stream";
}

/* ---------- страница /save ---------- */

/**
 * Файл, который можно открыть на /save: только наш /media/, с понятным
 * расширением, без «..», «//», процентов и запроса — ни открытого редиректа,
 * ни чужого адреса.
 */
// Префикс /media/ — с учётом регистра, как location ^~ /media/ в nginx: «/Media/…»
// ушёл бы в Next, и вместо файла скачалась бы HTML-страница 404. Расширение — без учёта.
const SAVE_PATH = /^\/media\/[A-Za-z0-9_\-/.]+\.([A-Za-z0-9]+)$/;
const SAVE_EXT = new Set(["mp4", "m4v", "mov", "webm", "jpg", "jpeg", "png", "webp", "gif"]);
const SAVE_NAME = /^[A-Za-z0-9_\-][A-Za-z0-9_.\-]{0,79}$/;

export function safeMediaPath(path: string): string | null {
  if (typeof path !== "string" || path.length > 300) return null;
  const ext = SAVE_PATH.exec(path)?.[1]?.toLowerCase() || "";
  if (!SAVE_EXT.has(ext) || path.includes("..") || path.includes("//")) return null;
  return path;
}

/** Путь /media/… этого же сайта по адресу файла; чужой сайт или не /media/ — null. */
export function sameOriginMediaPath(url: string, origin: string): string | null {
  if (!url) return null;
  if (url.startsWith("/") && !url.startsWith("//")) return safeMediaPath(url.split(/[?#]/)[0]);
  try {
    const u = new URL(url);
    if (u.origin !== origin) return null;
    return safeMediaPath(u.pathname);
  } catch {
    return null;
  }
}

/** Имя файла для /save: из ссылки, если оно безопасное, иначе esai-file.<расширение>. */
export function safeSaveName(name: string, path: string): string {
  if (typeof name === "string" && SAVE_NAME.test(name)) return name;
  const ext = /\.([a-z0-9]+)$/i.exec(path)?.[1]?.toLowerCase() || "mp4";
  return `esai-file.${ext}`;
}

export type SaveTarget = { path: string; filename: string; kind: "video" | "image" };

/** Разбор параметров /save?f=…&n=…; неверная ссылка — null. */
export function parseSaveTarget(f: unknown, n: unknown): SaveTarget | null {
  const path = safeMediaPath(typeof f === "string" ? f : "");
  if (!path) return null;
  const filename = safeSaveName(typeof n === "string" ? n : "", path);
  return { path, filename, kind: mediaKind(filename, path) };
}

/** Адрес, который можно открыть ссылкой «Открыть файл»: только http(s); относительный — от origin. */
export function openableUrl(url: string, origin: string): string | null {
  if (!url) return null;
  try {
    const u = new URL(url, origin);
    return u.protocol === "https:" || u.protocol === "http:" ? u.href : null;
  } catch {
    return null;
  }
}

/**
 * Запасной путь к файлу в шторке, когда окна «Поделиться» нет, а загрузка в
 * память не удалась (ошибка: «Повторить» при постоянном сбое падает так же) или
 * файл лежит на чужом сайте (режим files).
 * link — <a download> на наш /media/: работает без файла в памяти, на iPhone
 *        кладёт его в «Файлы», тёмной страницы нет;
 * blob — файл уже в памяти (чужой адрес): сохранить его из памяти;
 * open — чужой адрес без CORS (провайдер отдал готовую ссылку): открыть файл во
 *        вкладке, как было до шторки;
 * none — пути нет. На iPhone переход на файл — та самая тёмная страница.
 */
export type FileFallback = "link" | "blob" | "open" | "none";

export function fileFallback(p: {
  filePath: string | null;
  url: string;
  origin: string;
  os: SaveOs;
  hasBlob: boolean;
}): FileFallback {
  if (p.filePath) return "link";
  if (p.os === "ios") return "none";
  if (p.hasBlob) return "blob";
  return openableUrl(p.url, p.origin) ? "open" : "none";
}

/** Относительная ссылка на /save для файла этого сайта (или null — тогда кнопки «Скопировать ссылку» нет). */
export function saveLinkFor(url: string, filename: string, origin: string): string | null {
  const path = sameOriginMediaPath(url, origin);
  if (!path) return null;
  const q = new URLSearchParams({ f: path, n: safeSaveName(filename, path) });
  return `/save?${q.toString()}`;
}

/* ---------- диагностика ---------- */

const PATHS: Array<[RegExp, string]> = [
  [/^\/video-studio/, "vstudio"],
  [/^\/tg\/studio/, "tg_studio"],
  [/^\/studio/, "cartoon"],
  [/^\/merge/, "merge"],
  [/^\/v\//, "shared"],
  [/^\/save/, "save_page"],
  [/^\/(dashboard)?$|^\/dashboard\//, "chat"],
];

/** Раздел сайта по пути — без uid проекта и прочих хвостов. */
export function surfaceOf(pathname: string): string {
  for (const [re, name] of PATHS) if (re.test(pathname || "")) return name;
  return "other";
}

/** Версия кода сохранения в событии: событий нет совсем — значит, у человека старая вкладка. */
export const SAVE_CODE_VERSION = "s3";

export type SaveStep =
  | "share"
  | "sheet"
  | "blob_dl"
  | "sheet_share"
  | "sheet_files"
  | "sheet_copy";
export type SaveDiagResult = "saved" | "cancelled" | "downloaded" | "sheet" | "error" | "copied";
export type SaveStage = "" | "fetch" | "share" | "canShare" | "download" | "copy";

const SIZE_STEP_KB = 256;

/** Только имя ошибки: в сообщении бывает адрес файла. */
export function errName(e: unknown): string {
  const name = (e as { name?: unknown } | null)?.name;
  return typeof name === "string" ? name : "";
}

/**
 * meta события media_save: только перечислимые значения, числа и булевы.
 * Ни адреса файла и страницы, ни имени файла, ни сырого user agent.
 * Тот же белый список держит сервер (payments/funnel.py).
 */
export function saveDiagMeta(input: {
  env: SaveEnv;
  hints: Pick<EnvHints, "hasShare" | "hasCanShare">;
  surface: string;
  kind: "video" | "image";
  step: SaveStep;
  result: SaveDiagResult;
  err: string;
  stage: SaveStage;
  canShareFile: boolean | null;
  waitedMs: number | null;
  prefetchHit: boolean | null;
  sizeBytes: number | null;
  typeOk: boolean | null;
  httpStatus: number | null;
  attempt: number;
  diag: string;
  visible: boolean;
}): Record<string, string | number | boolean | null> {
  const err = /^[A-Za-z_]{1,32}$/.test(input.err) ? input.err : input.err ? "other" : "";
  return {
    v: SAVE_CODE_VERSION,
    where: input.surface,
    kind: input.kind,
    step: input.step,
    result: input.result,
    err,
    stage: input.stage,
    os: input.env.os,
    os_ver: input.env.osVer.slice(0, 8),
    browser: input.env.browser,
    inapp: input.env.inApp,
    standalone: input.env.standalone,
    frozen: input.env.frozenBuild,
    has_share: input.hints.hasShare,
    has_can_share: input.hints.hasCanShare,
    can_share_file: input.canShareFile,
    wait_ms: input.waitedMs == null ? null : Math.min(60_000, Math.max(0, Math.round(input.waitedMs / 100) * 100)),
    prefetch_hit: input.prefetchHit,
    size_kb: input.sizeBytes == null ? null : Math.round(input.sizeBytes / 1024 / SIZE_STEP_KB) * SIZE_STEP_KB,
    type_ok: input.typeOk,
    http: input.httpStatus,
    n: Math.max(1, Math.min(99, input.attempt)),
    diag: input.diag.slice(0, 8),
    vis: input.visible,
  };
}

const DIAG_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789";

/** Код попытки для подвала шторки: по скриншоту клиента строка события находится сразу. */
export function newDiagCode(random: () => number = Math.random): string {
  let s = "";
  for (let i = 0; i < 6; i += 1) s += DIAG_ALPHABET[Math.floor(random() * DIAG_ALPHABET.length) % DIAG_ALPHABET.length];
  return s;
}

const OS_LABEL: Record<SaveOs, string> = { ios: "iOS", android: "Android", other: "" };
const INAPP_LABEL: Partial<Record<InApp, string>> = {
  telegram: "Telegram",
  tg_miniapp: "Telegram Mini App",
  instagram: "Instagram",
  facebook: "Facebook",
  tiktok: "TikTok",
  vk: "VK",
  line: "LINE",
  snapchat: "Snapchat",
  google_app: "Google",
  wkwebview: "WebView",
  android_wv: "WebView",
};
const BROWSER_LABEL: Record<Browser, string> = {
  safari: "Safari",
  chrome: "Chrome",
  firefox: "Firefox",
  edge: "Edge",
  yandex: "Yandex",
  opera: "Opera",
  samsung: "Samsung",
  duckduckgo: "DuckDuckGo",
  other: "",
};

/** Хвост подвала шторки: «iOS 26.0 · Telegram · PWA · s3» — по скриншоту видно, где человек. */
export function envLabel(env: SaveEnv): string {
  const os = [OS_LABEL[env.os], env.osVer].filter(Boolean).join(" ");
  const where = INAPP_LABEL[env.inApp] || BROWSER_LABEL[env.browser];
  return [os, where, env.standalone ? "PWA" : "", SAVE_CODE_VERSION].filter(Boolean).join(" · ");
}
