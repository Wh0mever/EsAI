/**
 * saveMedia — надёжное «Скачать» для картинок/видео: на телефоне — системное окно
 * «Сохранить видео/фото», на компьютере — обычный файл в «Загрузки».
 *
 * Телефоны и планшеты (iPhone, iPad, Android). В iOS <a download> на blob
 * ИГНОРИРУЕТСЯ WebKit, поэтому там открываем НАТИВНЫЙ шитшет через Web Share API
 * с файлом.
 *
 * Компьютер (в т.ч. Safari на macOS и Edge/Chrome на Windows): шитшет там тоже
 * «умеет файлы», но в нём нет пункта «Сохранить» — клиент отправлял сцену в
 * «Избранное» Telegram и получал только текст «esai-scene-1.mp4». Там — только
 * загрузка файла через <a download> из blob.
 *
 * Тонкость iOS: navigator.share({files}) требует «user activation» (жеста), и
 * WebKit держит её 5 с от касания (r293635); через fetch жест не переносится.
 * prefetchMedia() стартует загрузку на нажатие пальцем, а saveMedia ждёт файл
 * не дольше SHARE_BUDGET_MS. Не успел — открываем шторку (components/ui/SaveSheet):
 * она догружает файл с прогрессом, и второе, свежее нажатие открывает окно сразу.
 *
 * На сам файл (window.open) не уходим НИКОГДА: на iPhone это тёмная страница со
 * значком, на которую жаловался клиент. В шторке у каждой неудачи есть следующий шаг.
 */
import {
  afterShareError,
  detectEnv,
  errName,
  mediaKind,
  mimeFor,
  newDiagCode,
  saveDiagMeta,
  surfaceOf,
  type EnvHints,
  type SaveDiagResult,
  type SaveEnv,
  type SaveStage,
  type SaveStep,
} from "./saveEnv";

/** Сколько ждём файл после нажатия на iPhone: жест живёт 5 с, нужен запас на само окно. */
export const SHARE_BUDGET_MS = 3000;

type ShareNavigator = Navigator & {
  canShare?: (data?: ShareData) => boolean;
  userAgentData?: { mobile?: boolean };
  standalone?: boolean;
};

type TelegramWebApp = {
  initData?: unknown;
  downloadFile?: (params: { url: string; file_name: string }, cb?: (accepted: boolean) => void) => void;
  isVersionAtLeast?: (v: string) => boolean;
};

type EnvWindow = Window & {
  TelegramWebviewProxy?: unknown;
  TelegramWebview?: unknown;
  Telegram?: { WebApp?: TelegramWebApp };
};

/** Признаки среды из браузера (только в обработчиках и эффектах — на сервере window нет). */
export function readEnvHints(): EnvHints {
  const nav = navigator as ShareNavigator;
  const w = window as EnvWindow;
  let standalone = nav.standalone === true;
  try {
    standalone = standalone || Boolean(w.matchMedia?.("(display-mode: standalone)").matches);
  } catch {
    // matchMedia нет (старый webview) — считаем, что не установлено
  }
  const initData = w.Telegram?.WebApp?.initData;
  return {
    userAgent: nav.userAgent || "",
    platform: nav.platform || "",
    maxTouchPoints: nav.maxTouchPoints || 0,
    uaMobile: typeof nav.userAgentData?.mobile === "boolean" ? nav.userAgentData.mobile : null,
    standalone,
    tgProxy: typeof w.TelegramWebviewProxy !== "undefined",
    tgAndroidBridge: typeof w.TelegramWebview !== "undefined",
    tgMiniApp: typeof initData === "string" && initData.length > 0,
    hasShare: typeof nav.share === "function",
    hasCanShare: typeof nav.canShare === "function",
  };
}

export function readSaveEnv(): { hints: EnvHints; env: SaveEnv } {
  const hints = readEnvHints();
  return { hints, env: detectEnv(hints) };
}

/* ---------- загрузка файла в память ---------- */

export type MediaProgress = { done: number; total: number };

type Entry = {
  blob: Promise<Blob>;
  settled: boolean;
  done: number;
  total: number;
  http: number | null;
  listeners: Set<() => void>;
  timer: ReturnType<typeof setTimeout> | null;
};

// Начатые загрузки: url → файл в памяти. Видео весит мегабайты, поэтому запись
// живёт, пока файл ждёт нажатия (шторка держит её через holdMedia), и не дольше
// KEEP_MS после prefetch, если нажатия так и не было.
const _entries = new Map<string, Entry>();
const _holds = new Map<string, number>();
const KEEP_MS = 120_000;

// Гвард от повторных запусков по одному url: пока идёт сохранение, лишние тапы
// (пользователь думает «не жмётся») не плодят несколько шитшетов подряд.
const _inFlight = new Set<string>();

let _attempt = 0;

/** Номер попытки на этой странице — для диагностики (n в событии). */
export function nextAttempt(): number {
  _attempt += 1;
  return _attempt;
}

function namedError(name: string, message: string): Error {
  const e = new Error(message);
  e.name = name;
  return e;
}

function dropMedia(url: string, entry?: Entry): void {
  const cur = _entries.get(url);
  if (!cur || (entry && cur !== entry)) return;
  if (cur.timer) clearTimeout(cur.timer);
  _entries.delete(url);
}

function scheduleDrop(url: string, entry: Entry): void {
  if (entry.timer) clearTimeout(entry.timer);
  entry.timer = null;
  if (_holds.get(url)) return;
  entry.timer = setTimeout(() => dropMedia(url, entry), KEEP_MS);
}

/**
 * Больше этого — без прогресса. Куски потока лежат в памяти JS, а Blob из них —
 * ещё одна копия: в пике два размера файла, а склейка на iPhone бывает больше
 * 100 МБ. r.blob() держит файл вне кучи JS.
 */
export const STREAM_MAX_BYTES = 50 * 1024 * 1024;

async function readBody(r: Response, entry: Entry, notify: () => void): Promise<Blob> {
  entry.http = r.status;
  if (!r.ok) throw namedError("HttpError", `HTTP ${r.status}`);
  const type = (r.headers.get("content-type") || "").split(";")[0].trim().toLowerCase();
  // Вместо файла пришла страница (заглушка ошибки, проверка Cloudflare): в окно
  // «Поделиться» она ушла бы как .mp4.
  if (type.startsWith("text/")) throw namedError("BadType", "not a media file");
  const length = Number(r.headers.get("content-length")) || 0;
  const reader = length > STREAM_MAX_BYTES ? undefined : r.body?.getReader();
  // Без потока шторка показывает неопределённую полосу, а не «0 из N МБ» до конца.
  if (!reader) return r.blob();
  entry.total = length;
  const parts: BlobPart[] = [];
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    if (value) {
      parts.push(value);
      entry.done += value.byteLength;
      notify();
    }
  }
  return new Blob(parts, { type });
}

function startFetch(url: string): Entry {
  const notify = () => entry.listeners.forEach((fn) => fn());
  const entry: Entry = {
    blob: fetch(url, { credentials: "omit" }).then((r) => readBody(r, entry, notify)),
    settled: false,
    done: 0,
    total: 0,
    http: null,
    listeners: new Set(),
    timer: null,
  };
  entry.blob.then(
    () => {
      entry.settled = true;
      notify();
    },
    () => {
      entry.settled = true;
      // ошибку не кэшируем — дать возможность повтора
      dropMedia(url, entry);
      notify();
    },
  );
  _entries.set(url, entry);
  scheduleDrop(url, entry);
  return entry;
}

function entryFor(url: string): Entry {
  return _entries.get(url) || startFetch(url);
}

/** Начать загрузку файла заранее (вешать на onPointerDown кнопки «Скачать»). */
export function prefetchMedia(url: string): void {
  if (!url || _entries.has(url)) return;
  // Ошибки здесь не ловим: это лишь «прогрев», их обработает saveMedia или шторка.
  startFetch(url);
}

/**
 * Файл для шторки: берёт начатую загрузку или начинает новую. onProgress
 * вызывается по мере прихода байтов; stop — отписка.
 */
export function followMedia(
  url: string,
  onProgress: (p: MediaProgress) => void,
): { blob: Promise<Blob>; stop: () => void } {
  const entry = entryFor(url);
  const fn = () => onProgress({ done: entry.done, total: entry.total });
  entry.listeners.add(fn);
  return {
    blob: entry.blob,
    stop: () => {
      entry.listeners.delete(fn);
    },
  };
}

/** Держать файл в памяти, пока открыта шторка. Возвращает «отпустить» — после него файл выбрасывается. */
export function holdMedia(url: string): () => void {
  _holds.set(url, (_holds.get(url) || 0) + 1);
  const entry = _entries.get(url);
  if (entry?.timer) {
    clearTimeout(entry.timer);
    entry.timer = null;
  }
  let released = false;
  return () => {
    if (released) return;
    released = true;
    const left = (_holds.get(url) || 1) - 1;
    if (left > 0) {
      _holds.set(url, left);
      return;
    }
    _holds.delete(url);
    dropMedia(url);
  };
}

export function toFile(blob: Blob, filename: string): File {
  return new File([blob], filename, { type: mimeFor(blob.type, filename) });
}

/** Умеет ли системное окно принять этот файл. canShare в части webview бросает — тогда «нет». */
export function canShareFileNow(file: File): boolean {
  const nav = navigator as ShareNavigator;
  if (typeof nav.share !== "function" || typeof nav.canShare !== "function") return false;
  try {
    return nav.canShare({ files: [file] });
  } catch {
    return false;
  }
}

/**
 * Открыть системное окно с файлом. Вызывать СИНХРОННО в обработчике нажатия,
 * без await перед вызовом — иначе iOS сочтёт жест истёкшим. Только { files }:
 * title рядом с файлом ничего не даёт, а Telegram на Android при большом файле
 * выбрасывает файл и отправляет один title текстом.
 */
export function shareFile(file: File): Promise<void> {
  try {
    return navigator.share({ files: [file] });
  } catch (e) {
    return Promise.reject(e);
  }
}

/** Файл из памяти — в «Загрузки» через <a download>. На iPhone WebKit это игнорирует. */
export function downloadBlob(blob: Blob, filename: string): void {
  const objUrl = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = objUrl;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(objUrl), 4000);
}

/** Мини-приложение Telegram (Bot API 8.0+): у него своё окно скачивания файла. */
function telegramDownload(url: string, filename: string): boolean {
  const tg = (window as EnvWindow).Telegram?.WebApp;
  if (!tg?.downloadFile || (tg.isVersionAtLeast && !tg.isVersionAtLeast("8.0"))) return false;
  try {
    tg.downloadFile({ url: new URL(url, window.location.href).href, file_name: filename });
    return true;
  } catch {
    return false;
  }
}

/* ---------- диагностика ---------- */

export type SaveDiagMeta = Record<string, string | number | boolean | null>;
export type SaveReport = (meta: SaveDiagMeta) => void;

function pageVisible(): boolean {
  return typeof document !== "undefined" && document.visibilityState === "visible";
}

function pagePath(): string {
  return typeof location !== "undefined" ? location.pathname : "";
}

/**
 * meta события media_save для шага в шторке или на /save. На компьютере — null:
 * там событий нет, жалобы только с телефонов.
 */
export function mediaEventMeta(p: {
  url: string;
  filename: string;
  step: SaveStep;
  result: SaveDiagResult;
  err?: string;
  stage?: SaveStage;
  canShareFile: boolean | null;
  blob: Blob | null;
  diag: string;
  waitedMs?: number | null;
}): SaveDiagMeta | null {
  const { hints, env } = readSaveEnv();
  if (!env.handheld) return null;
  return saveDiagMeta({
    env,
    hints,
    surface: surfaceOf(pagePath()),
    kind: mediaKind(p.filename, p.url),
    step: p.step,
    result: p.result,
    err: p.err || "",
    stage: p.stage || "",
    canShareFile: p.canShareFile,
    waitedMs: p.waitedMs ?? null,
    prefetchHit: null,
    sizeBytes: p.blob ? p.blob.size : null,
    typeOk: p.blob ? /^(video|image)\//.test(p.blob.type) : null,
    httpStatus: _entries.get(p.url)?.http ?? null,
    attempt: nextAttempt(),
    diag: p.diag,
    visible: pageVisible(),
  });
}

/* ---------- первое нажатие ---------- */

/**
 * С чем открыть шторку: reason — почему не вышло сразу ("slow", имя ошибки share), failed — файл не скачался,
 * http — код ответа файла (404/410: файла больше нет, шторка не предлагает повтор).
 */
export type SheetStart = { reason: string; failed: boolean; diag: string; http?: number | null };

/**
 * Чем закончилось первое нажатие. "sheet" — сразу не вышло (файл качается дольше
 * жеста, окно отказало, нет файлового окна, файл не скачался): кнопка открывает
 * шторку, и следующий шаг человек делает в ней.
 */
export type SaveOutcome =
  | { result: "saved" | "cancelled" | "downloaded" }
  | { result: "sheet"; sheet: SheetStart };

export type SaveOptions = {
  /** Куда отправить событие media_save (кнопка шлёт его в воронку). */
  report?: SaveReport;
  /** Сколько ждать файл на iPhone; по умолчанию SHARE_BUDGET_MS (тест укорачивает). */
  budgetMs?: number;
};

async function blobWithin(entry: Entry, ms: number): Promise<Blob | null> {
  let timer: ReturnType<typeof setTimeout> | undefined;
  const late = new Promise<null>((resolve) => {
    timer = setTimeout(() => resolve(null), ms);
  });
  try {
    return await Promise.race([entry.blob, late]);
  } finally {
    clearTimeout(timer);
  }
}

export async function saveMedia(url: string, filename: string, opts: SaveOptions = {}): Promise<SaveOutcome> {
  if (!url || _inFlight.has(url)) return { result: "cancelled" };
  _inFlight.add(url);
  const { hints, env } = readSaveEnv();
  const diag = newDiagCode();
  const startedAt = Date.now();
  const prefetchHit = Boolean(_entries.get(url)?.settled);
  let entry: Entry | null = null;
  let blob: Blob | null = null;
  let canShareFile: boolean | null = null;
  // Шторке файл ещё нужен: не выбрасывать его в finally.
  let handOver = false;

  const report = (step: SaveStep, result: SaveDiagResult, err: string, stage: SaveStage) => {
    if (!env.handheld || !opts.report) return;
    try {
      opts.report(
        saveDiagMeta({
          env,
          hints,
          surface: surfaceOf(pagePath()),
          kind: mediaKind(filename, url),
          step,
          result,
          err,
          stage,
          canShareFile,
          waitedMs: Date.now() - startedAt,
          prefetchHit,
          sizeBytes: blob ? blob.size : null,
          typeOk: blob ? /^(video|image)\//.test(blob.type) : null,
          httpStatus: entry ? entry.http : null,
          attempt: nextAttempt(),
          diag,
          visible: pageVisible(),
        }),
      );
    } catch {
      // диагностика не должна мешать сохранению
    }
  };
  const toSheet = (step: SaveStep, reason: string, stage: SaveStage): SaveOutcome => {
    handOver = true;
    report(step, "sheet", reason, stage);
    return { result: "sheet", sheet: { reason, failed: false, diag } };
  };

  try {
    // Внутри Telegram Mini App: его окно скачивания — без шитшета и без пустой страницы.
    if (env.handheld && telegramDownload(url, filename)) return { result: "saved" };

    // Берём заранее начатую загрузку (prefetch на pointerdown), иначе качаем сейчас.
    entry = entryFor(url);

    if (!env.handheld) {
      blob = await entry.blob;
      downloadBlob(blob, filename);
      return { result: "downloaded" };
    }

    if (env.os !== "ios") {
      // Android и прочие телефоны — как раньше: окно «Поделиться», если умеет
      // файлы, иначе файл в «Загрузки».
      blob = await entry.blob;
      const file = toFile(blob, filename);
      canShareFile = canShareFileNow(file);
      let shareErr = "";
      if (canShareFile) {
        try {
          await shareFile(file);
          return { result: "saved" };
        } catch (e) {
          shareErr = errName(e);
          if (shareErr === "AbortError") {
            report("share", "cancelled", shareErr, "share");
            return { result: "cancelled" };
          }
          // Жест «истёк», пока качался файл: второе нажатие в шторке откроет окно сразу.
          if (shareErr === "NotAllowedError") return toSheet("share", shareErr, "share");
        }
      }
      downloadBlob(blob, filename);
      report(canShareFile ? "share" : "blob_dl", "downloaded", shareErr, shareErr ? "share" : "");
      return { result: "downloaded" };
    }

    // iPhone/iPad: окно с файлом — только если файл успел за жест.
    blob = await blobWithin(entry, opts.budgetMs ?? SHARE_BUDGET_MS);
    if (!blob) return toSheet("sheet", "slow", "fetch");
    const file = toFile(blob, filename);
    canShareFile = canShareFileNow(file);
    if (!canShareFile) return toSheet("sheet", "", "canShare");
    try {
      await shareFile(file);
      return { result: "saved" };
    } catch (e) {
      const name = errName(e) || "other";
      if (afterShareError(name) === "cancelled") {
        report("share", "cancelled", name, "share");
        return { result: "cancelled" };
      }
      return toSheet("share", name, "share");
    }
  } catch (e) {
    // Файл не скачался (сеть, 404/502, вместо файла страница): шторка с «Повторить».
    const name = errName(e) || "other";
    report("sheet", "error", name, blob ? "download" : "fetch");
    return { result: "sheet", sheet: { reason: name, failed: true, diag, http: entry ? entry.http : null } };
  } finally {
    _inFlight.delete(url);
    // Освобождаем память (видео — несколько МБ), если файл не нужен шторке.
    if (!handOver && !_holds.get(url)) dropMedia(url);
  }
}
