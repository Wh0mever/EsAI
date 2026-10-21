/**
 * «Склейка»: свои видео — проверки до загрузки, подписи и разбор отказов
 * (CONTRACT_M.md §9). Чистые функции проверяет uploadLogic.test.mjs;
 * probeVideoFile работает только в браузере.
 *
 * Здесь проверяем то же, что сервер: размер, расширение, место в «Моих
 * файлах», а по метаданным из <video> — длину и кадр. Сервер всё равно
 * проверит заново; смысл в том, чтобы не гнать 90 МБ по мобильной сети ради
 * отказа, который виден сразу.
 */
import { DEFAULT_MAX_UPLOADS, refusalText, shortDate, waitMinutes, type TextSpec } from "./mergeLogic";
import type { MergeUploadLimits, MergeUploadUsage } from "./mergeTypes";

const MB = 1024 * 1024;

export const DEFAULT_UPLOAD_LIMITS: MergeUploadLimits = {
  max_bytes: 90 * MB,
  max_mb: 90,
  min_duration_s: 0.5,
  max_duration_s: 60,
  max_side: 4096,
  max_fps: 120,
  max_per_project: DEFAULT_MAX_UPLOADS,
  max_files: 10,
  max_total_bytes: 600 * MB,
  max_total_mb: 600,
  retention_days: 30,
  extensions: ["mp4", "mov", "m4v", "webm"],
  accept: "video/mp4,video/quicktime,video/webm,.mp4,.mov,.m4v,.webm",
};

/** Сервер прощает полсекунды сверх предела: обрезка «1:00» на телефоне — это 60,03 с. */
export const UPLOAD_DURATION_TOLERANCE_S = 0.5;

/** Файл без расширения в имени (так отдают некоторые галереи) — расширение по типу. */
const MIME_EXT: Record<string, string> = {
  "video/mp4": "mp4",
  "video/quicktime": "mov",
  "video/x-m4v": "m4v",
  "video/webm": "webm",
};

export type UploadCode =
  | "upload_too_big"
  | "upload_bad_type"
  | "upload_unreadable"
  | "upload_too_short"
  | "upload_too_long"
  | "upload_resolution"
  | "upload_quota";

export type UploadRefusal = { code: UploadCode };

export type FileLike = { name: string; size: number; type: string };

export function fileExtension(name: string): string {
  const base = (name || "").split(/[\\/]/).pop() ?? "";
  const dot = base.lastIndexOf(".");
  return dot > 0 ? base.slice(dot + 1).toLowerCase() : "";
}

/**
 * Имя файла для сервера: он принимает только mp4/mov/m4v/webm в конце имени.
 * Расширения нет, но тип — видео из списка — дописываем; null — не подходит.
 */
export function uploadName(file: { name: string; type: string }, limits: MergeUploadLimits = DEFAULT_UPLOAD_LIMITS): string | null {
  const name = file.name || "";
  if (limits.extensions.includes(fileExtension(name))) return name;
  const ext = MIME_EXT[(file.type || "").toLowerCase()];
  if (!ext || !limits.extensions.includes(ext)) return null;
  return `${name || "video"}.${ext}`;
}

/** До загрузки: то, что видно по самому файлу, — в том же порядке, что у сервера. */
export function precheckFile(
  file: FileLike,
  limits: MergeUploadLimits = DEFAULT_UPLOAD_LIMITS,
  usage: MergeUploadUsage | null = null,
): UploadRefusal | null {
  if (file.size > limits.max_bytes) return { code: "upload_too_big" };
  if (usage && usage.files >= (usage.max_files || limits.max_files)) return { code: "upload_quota" };
  if (uploadName(file, limits) == null) return { code: "upload_bad_type" };
  if (!(file.size > 0)) return { code: "upload_unreadable" };
  if (usage && usage.bytes + file.size > (usage.max_bytes || limits.max_total_bytes)) return { code: "upload_quota" };
  return null;
}

export type MediaMeta = { duration: number; width: number; height: number };

/**
 * По метаданным <video>: длина и кадр. Чего браузер не прочитал (HEVC в
 * Chrome, WebM без длины) — не проверяем: решит сервер.
 */
export function precheckMedia(
  meta: Partial<MediaMeta> | null,
  limits: MergeUploadLimits = DEFAULT_UPLOAD_LIMITS,
): UploadRefusal | null {
  if (!meta) return null;
  const d = meta.duration;
  if (typeof d === "number" && Number.isFinite(d) && d > 0) {
    if (d < limits.min_duration_s) return { code: "upload_too_short" };
    if (d > limits.max_duration_s + UPLOAD_DURATION_TOLERANCE_S) return { code: "upload_too_long" };
  }
  const w = typeof meta.width === "number" ? meta.width : 0;
  const h = typeof meta.height === "number" ? meta.height : 0;
  if (w > limits.max_side || h > limits.max_side) return { code: "upload_resolution" };
  return null;
}

/** Отказ до загрузки → текст (тот же, что прислал бы сервер). */
export function precheckText(refusal: UploadRefusal): TextSpec {
  return refusalText(refusal.code);
}

/**
 * Отказ сервера при загрузке → код текста. 400 без поля file — это разбор
 * multipart: для человека файл просто не прочитался. 429 с wait — свой текст
 * с минутами: «подождите немного» при пределе 20 в час — неправда.
 */
export function uploadErrorCode(err: { code: string; data: Record<string, unknown> }): string {
  if (err.code === "bad_request" && err.data.field !== "file") return "upload_unreadable";
  if (err.code === "throttled" && waitMinutes(err.data.wait) != null) return "upload_throttled";
  return err.code;
}

export function uploadErrorText(err: { code: string; message: string; data: Record<string, unknown> }): TextSpec {
  const code = uploadErrorCode(err);
  return refusalText(code, err.data, code === err.code ? err.message : "");
}

/**
 * Отказ, после которого тот же файл стоит отправить ещё раз (связь, сбой
 * сервера, лимит, занятое место загрузки, вход): кнопка «Повторить» без
 * нового выбора 90 МБ из галереи. Отказ из-за самого файла повтор не исправит.
 */
const RETRYABLE = new Set([
  "network",
  "server_error",
  "bad_response",
  "throttled",
  "upload_throttled",
  "upload_busy",
  "upload_unavailable",
  "unauthorized",
]);

export function retryableUpload(code: string): boolean {
  return RETRYABLE.has(code);
}

/** «Мои файлы» заполнены по числу файлов: новая загрузка получит отказ сразу. */
export function uploadsFull(usage: MergeUploadUsage | null, limits: MergeUploadLimits = DEFAULT_UPLOAD_LIMITS): boolean {
  return Boolean(usage && usage.files >= (usage.max_files || limits.max_files));
}

/** Сколько дней ещё хранится файл, когда «скоро»: за три дня и меньше дата — цветом предупреждения. */
export const EXPIRY_SOON_DAYS = 3;

export type UploadExpiry = { date: string; soon: boolean };

/** «до ДД.ММ» у своего видео; срока нет или он не разобрался — null. */
export function uploadExpiry(expiresAt: string | null | undefined, now: Date = new Date()): UploadExpiry | null {
  const date = shortDate(expiresAt);
  if (!date || !expiresAt) return null;
  const left = (new Date(expiresAt).getTime() - now.getTime()) / 86_400_000;
  return { date, soon: left <= EXPIRY_SOON_DAYS };
}

/** Язык страницы → локаль чисел («12,3» по-русски и по-кыргызски, «12.3» по-английски). */
export function numberLocale(lang: string): string {
  if (lang === "en") return "en-US";
  if (lang === "kg") return "ky-KG";
  return "ru-RU";
}

/** Мегабайты для «12,3 МБ»: до 10 МБ — с десятой, дальше целые; крошечный файл — не «0». */
export function formatMb(bytes: number, locale = "ru-RU"): string {
  const raw = Math.max(0, Number.isFinite(bytes) ? bytes : 0) / MB;
  const mb = raw > 0 && raw < 0.1 ? 0.1 : raw;
  return mb.toLocaleString(locale, { minimumFractionDigits: 0, maximumFractionDigits: mb < 10 ? 1 : 0 });
}

/** Доля полоски загрузки: после 100 % сервер ещё проверяет файл — полоска полная. */
export function uploadShare(pct: number, phase: "upload" | "processing"): number {
  if (phase === "processing") return 1;
  return Math.max(0, Math.min(1, (Number.isFinite(pct) ? pct : 0) / 100));
}

/** Дольше не ждём: проверка на месте — лишь подсказка, её не должно быть заметно. */
const PROBE_TIMEOUT_MS = 5_000;

/**
 * Длина и размер кадра из метаданных файла — скрытым <video> по blob-ссылке
 * (на телефоне файл из галереи не копируется). Не вышло за 5 с или браузер не
 * умеет такой кодек — null: проверит сервер.
 */
export function probeVideoFile(file: Blob, timeoutMs = PROBE_TIMEOUT_MS): Promise<MediaMeta | null> {
  if (typeof document === "undefined" || typeof URL === "undefined" || typeof URL.createObjectURL !== "function") {
    return Promise.resolve(null);
  }
  return new Promise((resolve) => {
    const video = document.createElement("video");
    const url = URL.createObjectURL(file);
    let timer = 0;
    let done = false;
    const finish = (meta: MediaMeta | null) => {
      if (done) return;
      done = true;
      window.clearTimeout(timer);
      video.onloadedmetadata = null;
      video.onerror = null;
      video.removeAttribute("src");
      try {
        video.load();
      } catch {
        /* уже отпустил файл */
      }
      URL.revokeObjectURL(url);
      resolve(meta);
    };
    timer = window.setTimeout(() => finish(null), timeoutMs);
    video.preload = "metadata";
    video.muted = true;
    video.playsInline = true;
    video.onloadedmetadata = () => finish({ duration: video.duration, width: video.videoWidth, height: video.videoHeight });
    video.onerror = () => finish(null);
    video.src = url;
    // Safari на iPhone не грузит даже метаданные сам по себе — просим явно.
    try {
      video.load();
    } catch {
      /* без load() — дождёмся таймера */
    }
  });
}
