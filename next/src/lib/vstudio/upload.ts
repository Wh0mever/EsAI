/**
 * Видеостудия: загрузка фото в «Мои материалы» (§7, §9.4 useUpload).
 *
 * Здесь всё, что не зависит от React:
 *  - проверка файла до сети (тип, размер) — те же правила, что у сервера
 *    (core/vstudio/assets.py ← белый список вложений чата), чтобы человек не
 *    ждал загрузку 15 МБ ради ответа «не тот формат»;
 *  - уменьшение на клиенте: JPEG/PNG/WebP больше 2048 px по длинной стороне
 *    перерисовываются через canvas (быстрее уходит с телефона, провайдер
 *    быстрее скачивает — инцидент 21.09 был из-за тяжёлых фото). HEIC уходит
 *    как есть: браузеры, кроме Safari, его не декодируют — переведёт сервер;
 *  - очередь «по одному файлу»: следующий файл уходит, когда закончился
 *    предыдущий, отмена — через AbortController.
 *
 * Сервер всё равно проверяет и перекодирует каждый файл (EXIF, GPS,
 * полиглоты, «бомбы»); клиентская проверка только экономит время человека.
 */
import { uploadAsset } from "./api";
import type { UploadPhase, UploadResult, Uid, VsError, VsResult } from "./types";

/** MAX_ATTACHMENT_SIZE сервера (15 МБ). */
export const MAX_UPLOAD_BYTES = 15 * 1024 * 1024;
/** Длинная сторона после уменьшения на клиенте (сервер режет до того же). */
export const CLIENT_MAX_SIDE = 2048;
/** JPEG/WebP после canvas: q90, как у сервера. */
export const CLIENT_QUALITY = 0.9;
/**
 * accept для <input type="file">: image/* сам предлагает на телефоне камеру и
 * галерею (§9.7), расширения — для HEIC и .jfif, у которых браузер не знает type.
 */
export const UPLOAD_ACCEPT = "image/*,.heic,.heif,.jfif,.jpe";

/** Расширения, которые принимает сервер (ChatAttachmentUploadAPIView._IMAGE_EXTENSIONS + .jfif/.jpe). */
export const SERVER_IMAGE_EXT = [".jpg", ".jpeg", ".jfif", ".jpe", ".png", ".gif", ".webp", ".bmp", ".heic", ".heif"];

const TYPE_EXT: Record<string, string> = {
  "image/jpeg": ".jpg",
  "image/jpg": ".jpg",
  "image/pjpeg": ".jpg",
  "image/png": ".png",
  "image/gif": ".gif",
  "image/webp": ".webp",
  "image/bmp": ".bmp",
  "image/heic": ".heic",
  "image/heif": ".heif",
  "image/heic-sequence": ".heic",
  "image/heif-sequence": ".heif",
};

/** Что canvas умеет перерисовать без потерь смысла (GIF — анимация, BMP — редкость: оставляем серверу). */
const RESIZABLE = new Set(["image/jpeg", "image/png", "image/webp"]);

export type UploadFileLike = { name?: string; type?: string; size: number };

export type FileCheck =
  | { ok: true; ext: string; mime: string; heic: boolean; resizable: boolean }
  | { ok: false; code: "unsupported_type" | "video_refs_unsupported" | "file_too_large" };

export function fileExt(name: string | null | undefined): string {
  const m = /\.[a-z0-9]{1,8}$/i.exec(String(name || "").trim());
  return m ? m[0].toLowerCase() : "";
}

/** MIME по type файла, а если его нет (HEIC в части браузеров) — по расширению. */
export function mimeOf(file: UploadFileLike): string {
  const type = String(file.type || "").toLowerCase();
  if (type) return type === "image/jpg" || type === "image/pjpeg" ? "image/jpeg" : type;
  const ext = fileExt(file.name);
  if (ext === ".jpg" || ext === ".jpeg" || ext === ".jfif" || ext === ".jpe") return "image/jpeg";
  if (ext === ".png") return "image/png";
  if (ext === ".webp") return "image/webp";
  if (ext === ".gif") return "image/gif";
  if (ext === ".bmp") return "image/bmp";
  if (ext === ".heic") return "image/heic";
  if (ext === ".heif") return "image/heif";
  return "";
}

/**
 * Проверка до сети. Видео и звук — отдельный код (в Фазе 1 только фото),
 * SVG и документы — unsupported_type. Размер проверяем только у того, что
 * не уменьшится на клиенте: тяжёлый JPEG станет лёгким после canvas.
 */
export function checkFile(file: UploadFileLike): FileCheck {
  const type = String(file.type || "").toLowerCase();
  const ext = fileExt(file.name);
  if (type.startsWith("video/") || type.startsWith("audio/")) return { ok: false, code: "video_refs_unsupported" };
  if (/^\.(mp4|mov|m4v|webm|avi|mkv|mp3|wav|m4a|aac|ogg|flac)$/.test(ext)) return { ok: false, code: "video_refs_unsupported" };
  if (type === "image/svg+xml" || ext === ".svg") return { ok: false, code: "unsupported_type" };
  const mime = mimeOf(file);
  const byExt = ext ? SERVER_IMAGE_EXT.includes(ext) : false;
  const byType = Boolean(TYPE_EXT[mime]);
  // Расширение решает, если оно есть: «photo.avif» с type image/avif сервер не примет.
  if (ext ? !byExt : !byType) return { ok: false, code: "unsupported_type" };
  const resizable = RESIZABLE.has(mime);
  const heic = mime === "image/heic" || mime === "image/heif" || ext === ".heic" || ext === ".heif";
  if (!resizable && file.size > MAX_UPLOAD_BYTES) return { ok: false, code: "file_too_large" };
  return { ok: true, ext: ext || TYPE_EXT[mime] || "", mime, heic, resizable };
}

/** Размер после уменьшения; null — уменьшать не нужно. */
export function fitWithin(width: number, height: number, max: number = CLIENT_MAX_SIDE): { width: number; height: number } | null {
  if (!(width > 0) || !(height > 0)) return null;
  const long = Math.max(width, height);
  if (long <= max) return null;
  const k = max / long;
  return { width: Math.max(1, Math.round(width * k)), height: Math.max(1, Math.round(height * k)) };
}

/** Имя файла под новый формат: «IMG_0042.JPG» → «IMG_0042.jpg», вставка без имени → «photo.png». */
export function renamedFor(name: string | null | undefined, mime: string): string {
  const ext = TYPE_EXT[mime] || ".jpg";
  const raw = String(name || "").trim();
  const base = raw.replace(/\.[a-z0-9]{1,8}$/i, "").replace(/[\\/:*?"<>|]+/g, "_").slice(0, 80) || "photo";
  return `${base}${ext}`;
}

/* ------------------------------------------------------------------ */
/* Уменьшение через canvas                                             */
/* ------------------------------------------------------------------ */

/** Раскодированная картинка: размеры и отрисовка в контекст canvas. */
export type Decoded = {
  width: number;
  height: number;
  draw: (ctx: CanvasRenderingContext2D | OffscreenCanvasRenderingContext2D, width: number, height: number) => void;
  close?: () => void;
};

export type PrepareDeps = {
  decode?: (file: Blob) => Promise<Decoded | null>;
  encode?: (src: Decoded, width: number, height: number, mime: string, quality: number) => Promise<Blob | null>;
  maxSide?: number;
};

export type Prepared = {
  blob: Blob;
  filename: string;
  resized: boolean;
  /** Размер после подготовки, если его удалось узнать. */
  width?: number;
  height?: number;
};

async function defaultDecode(file: Blob): Promise<Decoded | null> {
  // EXIF-поворот применяем здесь: после canvas метаданных не останется, а
  // «лежащее на боку» фото с телефона должно уйти так, как его видит человек.
  if (typeof createImageBitmap === "function") {
    try {
      const bmp = await createImageBitmap(file, { imageOrientation: "from-image" });
      return {
        width: bmp.width,
        height: bmp.height,
        draw: (ctx, w, h) => ctx.drawImage(bmp, 0, 0, w, h),
        close: () => bmp.close?.(),
      };
    } catch {
      /* ниже — через <img> */
    }
  }
  if (typeof document === "undefined" || typeof URL === "undefined" || typeof URL.createObjectURL !== "function") return null;
  const url = URL.createObjectURL(file);
  try {
    const img = new Image();
    img.decoding = "async";
    const loaded = new Promise<boolean>((resolve) => {
      img.onload = () => resolve(true);
      img.onerror = () => resolve(false);
    });
    img.src = url;
    if (!(await loaded) || !img.naturalWidth) return null;
    return {
      width: img.naturalWidth,
      height: img.naturalHeight,
      draw: (ctx, w, h) => ctx.drawImage(img, 0, 0, w, h),
    };
  } finally {
    // Картинка уже раскодирована — ссылка больше не нужна.
    setTimeout(() => URL.revokeObjectURL(url), 0);
  }
}

async function defaultEncode(src: Decoded, width: number, height: number, mime: string, quality: number): Promise<Blob | null> {
  try {
    if (typeof OffscreenCanvas !== "undefined") {
      const canvas = new OffscreenCanvas(width, height);
      const ctx = canvas.getContext("2d");
      if (!ctx) return null;
      ctx.imageSmoothingQuality = "high";
      src.draw(ctx, width, height);
      return await canvas.convertToBlob({ type: mime, quality });
    }
    if (typeof document === "undefined") return null;
    const canvas = document.createElement("canvas");
    canvas.width = width;
    canvas.height = height;
    const ctx = canvas.getContext("2d");
    if (!ctx) return null;
    ctx.imageSmoothingQuality = "high";
    src.draw(ctx, width, height);
    return await new Promise<Blob | null>((resolve) => canvas.toBlob((b) => resolve(b), mime, quality));
  } catch {
    return null;
  }
}

/**
 * Файл, готовый к отправке. Уменьшаем только JPEG/PNG/WebP и только когда
 * это нужно (длинная сторона > 2048 или файл тяжелее 15 МБ). Любая неудача
 * canvas (старый браузер, память iOS) — уходит исходный файл: сервер сам
 * уменьшит, а «не получилось уменьшить» не повод отказать человеку.
 */
export async function prepareImage(file: Blob & { name?: string }, deps: PrepareDeps = {}): Promise<Prepared> {
  const name = typeof file.name === "string" ? file.name : "";
  const mime = mimeOf({ name, type: file.type, size: file.size });
  const original: Prepared = { blob: file, filename: name || renamedFor("", mime || "image/jpeg"), resized: false };
  if (!RESIZABLE.has(mime)) return original;
  const decode = deps.decode ?? defaultDecode;
  const encode = deps.encode ?? defaultEncode;
  let src: Decoded | null = null;
  try {
    src = await decode(file);
  } catch {
    src = null;
  }
  if (!src) return original;
  try {
    const target = fitWithin(src.width, src.height, deps.maxSide ?? CLIENT_MAX_SIDE);
    if (!target && file.size <= MAX_UPLOAD_BYTES) {
      return { ...original, width: src.width, height: src.height };
    }
    const w = target?.width ?? src.width;
    const h = target?.height ?? src.height;
    const blob = await encode(src, w, h, mime, CLIENT_QUALITY);
    // WebP умеют не все браузеры: toBlob молча отдаёт PNG — имя берём по факту.
    if (!blob || !blob.size) return original;
    if (!target && blob.size >= file.size) return original;
    const outMime = blob.type || mime;
    return { blob, filename: renamedFor(name, outMime), resized: true, width: w, height: h };
  } finally {
    src.close?.();
  }
}

/* ------------------------------------------------------------------ */
/* Одна загрузка: проверка → уменьшение → POST assets/                 */
/* ------------------------------------------------------------------ */

export function localUploadError(code: string): VsError {
  const status = code === "file_too_large" ? 413 : 422;
  return { status, code, message: "", data: { client: true } };
}

export type UploadOneOptions = {
  project?: Uid | null;
  signal?: AbortSignal;
  onProgress?: (pct: number, phase: UploadPhase) => void;
  deps?: PrepareDeps;
};

export async function uploadOne(file: File | Blob, opts: UploadOneOptions = {}): Promise<VsResult<UploadResult>> {
  const named = file as Blob & { name?: string };
  const check = checkFile({ name: named.name, type: file.type, size: file.size });
  if (!check.ok) {
    const error = localUploadError(check.code);
    return { ok: false, status: error.status, error };
  }
  const prepared = check.resizable ? await prepareImage(named, opts.deps) : { blob: file, filename: named.name || renamedFor("", check.mime), resized: false };
  if (opts.signal?.aborted) return { ok: false, status: 0, error: { status: 0, code: "aborted", message: "", data: {} } };
  if (prepared.blob.size > MAX_UPLOAD_BYTES) {
    const error = localUploadError("file_too_large");
    return { ok: false, status: error.status, error };
  }
  return uploadAsset(prepared.blob, {
    project: opts.project ?? null,
    filename: prepared.filename,
    onProgress: opts.onProgress,
    signal: opts.signal,
  });
}

/* ------------------------------------------------------------------ */
/* Очередь «по одному файлу»                                          */
/* ------------------------------------------------------------------ */

export type UploadJob = { lid: string; file: File | Blob; project: Uid | null };

export type UploadEvent =
  | { type: "queued"; lid: string }
  | { type: "started"; lid: string }
  | { type: "progress"; lid: string; pct: number; phase: UploadPhase }
  | { type: "done"; lid: string; result: VsResult<UploadResult> };

export type UploadSend = (
  job: UploadJob,
  ctl: { signal: AbortSignal; onProgress: (pct: number, phase: UploadPhase) => void },
) => Promise<VsResult<UploadResult>>;

export type UploadQueue = {
  /** Поставить файл в очередь; промис — итог именно этого файла (отмена → code "aborted"). */
  add: (job: UploadJob) => Promise<VsResult<UploadResult>>;
  /** Отменить: текущий — прервать XHR, ждущий — убрать из очереди. false — такого нет. */
  cancel: (lid: string) => boolean;
  cancelAll: () => void;
  has: (lid: string) => boolean;
  /** Сколько файлов ещё не закончилось (включая текущий). */
  size: () => number;
  active: () => string | null;
};

const ABORTED: VsResult<never> = { ok: false, status: 0, error: { status: 0, code: "aborted", message: "", data: {} } };

export function createUploadQueue(send: UploadSend, onEvent?: (e: UploadEvent) => void): UploadQueue {
  type Entry = { job: UploadJob; resolve: (r: VsResult<UploadResult>) => void; ctl: AbortController };
  const waiting: Entry[] = [];
  let current: Entry | null = null;
  const emit = (e: UploadEvent) => {
    try {
      onEvent?.(e);
    } catch {
      /* ошибка подписчика не должна останавливать очередь */
    }
  };

  const finish = (entry: Entry, result: VsResult<UploadResult>) => {
    emit({ type: "done", lid: entry.job.lid, result });
    entry.resolve(result);
  };

  const pump = () => {
    if (current || !waiting.length) return;
    const entry = waiting.shift() as Entry;
    current = entry;
    emit({ type: "started", lid: entry.job.lid });
    const onProgress = (pct: number, phase: UploadPhase) => {
      if (current === entry && !entry.ctl.signal.aborted) emit({ type: "progress", lid: entry.job.lid, pct, phase });
    };
    let run: Promise<VsResult<UploadResult>>;
    try {
      run = send(entry.job, { signal: entry.ctl.signal, onProgress });
    } catch (err) {
      run = Promise.reject(err);
    }
    run
      .catch(
        (err: unknown): VsResult<UploadResult> => ({
          ok: false,
          status: 0,
          error: { status: 0, code: "unknown", message: err instanceof Error ? err.message : "", data: {} },
        }),
      )
      .then((res) => {
        current = null;
        finish(entry, entry.ctl.signal.aborted ? ABORTED : res);
        pump();
      });
  };

  return {
    add(job) {
      return new Promise<VsResult<UploadResult>>((resolve) => {
        waiting.push({ job, resolve, ctl: new AbortController() });
        emit({ type: "queued", lid: job.lid });
        pump();
      });
    },
    cancel(lid) {
      if (current && current.job.lid === lid) {
        current.ctl.abort();
        return true;
      }
      const i = waiting.findIndex((e) => e.job.lid === lid);
      if (i < 0) return false;
      const [entry] = waiting.splice(i, 1);
      entry.ctl.abort();
      finish(entry, ABORTED);
      return true;
    },
    cancelAll() {
      for (const entry of waiting.splice(0)) {
        entry.ctl.abort();
        finish(entry, ABORTED);
      }
      current?.ctl.abort();
    },
    has(lid) {
      return current?.job.lid === lid || waiting.some((e) => e.job.lid === lid);
    },
    size() {
      return waiting.length + (current ? 1 : 0);
    },
    active() {
      return current ? current.job.lid : null;
    },
  };
}
