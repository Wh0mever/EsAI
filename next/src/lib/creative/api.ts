/**
 * Creative Studio: типизированный слой над /api/creative/ (SPEC_B §7).
 *
 * Как у видеостудии: обёртки ходят через fetchData и никогда не бросают —
 * ответ всегда VsResult с error_code из тела (lib/vstudio/errors.ts). Загрузка
 * файла — через XHR: у fetch нет прогресса отправки.
 *
 * Сервер отдаёт только наши поля и наши адреса файлов; имени поставщика здесь
 * нет и быть не должно — файл уходит в браузер.
 */
import Cookies from "js-cookie";
import { API, ensureAccess, fetchData, getToken } from "@/tools/fetchData";
import { abortedError, toResult } from "@/lib/vstudio/errors";
import type { VsError, VsResult } from "@/lib/vstudio/types";

export const CS = "creative/";

/* ------------------------------------------------------------------ */
/* Типы ответа                                                         */
/* ------------------------------------------------------------------ */

export type CreativeMode = "off" | "staff" | "on";
export type OutputKind = "image" | "video" | "character";

/** BalanceJSON: свободный остаток и сколько останется после запуска (after может быть < 0). */
export type Balance = { balance: number; reserved: number; available: number; after: number | null };

export type ToolAccess = {
  id: string;
  enabled: boolean;
  kind: OutputKind;
  face_consent: boolean;
  price_hint_credits: number | null;
};

export type ToolsResponse = {
  mode: CreativeMode;
  /** может ли этот человек запускать (режим + вход) */
  available: boolean;
  tools: ToolAccess[];
  balance?: Balance | null;
};

export type CatalogKind = "styles-v2" | "styles-v1" | "restyle" | "ms-presets" | "influencer";

/** name пустое — у варианта нет имени: подпись «Стиль N» (n) собирает форма на языке человека. */
export type CatalogItem = { id: string; name: string; n: number; preview: string | null; aspect?: string | null; group?: string | null };
export type InfluencerOption = { key: string; label: string; color: string | null; exclusive: boolean; preview: string | null };
export type InfluencerCategory = { key: string; label: string; max: number; options: InfluencerOption[] };

export type UploadKind = "image" | "video";
export type UploadJSON = { uid: string; kind: UploadKind; w: number | null; h: number | null; duration: number | null; preview: string };

export type QuoteJSON = { credits: number; tool: string; outputs: number; eta_s: number; balance: Balance | null };

export type JobStatus = "queued" | "submitting" | "running" | "saving" | "done" | "failed" | "nsfw" | "canceled" | "lost";
export const OPEN_STATUSES: readonly JobStatus[] = ["queued", "submitting", "running", "saving"];
export const isOpen = (s: string | null | undefined): boolean => OPEN_STATUSES.includes(s as JobStatus);

export type JobFile = { url: string; mime: string; w: number | null; h: number | null; poster: string | null; duration: number | null };

export type JobJSON = {
  uid: string;
  tool: string;
  kind: OutputKind;
  status: JobStatus;
  stage: string;
  credits_quoted: number;
  credits_reserved: number;
  credits_charged: number;
  created_at: string | null;
  finished_at: string | null;
  error_code: string | null;
  error: string | null;
  results: JobFile[];
  params_public: Record<string, unknown>;
};

export type RunResponse = { job: JobJSON; balance: Balance | null };
export type JobsPage = { items: JobJSON[]; page: number; has_more: boolean };

export type CharacterStatus = "training" | "ready" | "failed";
export type CharacterJSON = { uid: string; name: string; status: CharacterStatus; thumb: string | null; created_at: string | null };

export type RunBody = { tool: string; params: Record<string, unknown>; quoted_credits: number; client_request_id: string; lang?: string };

/* ------------------------------------------------------------------ */
/* Разбор «как от чужих»: кривую строку пропускаем, страница не падает  */
/* ------------------------------------------------------------------ */

const isObj = (v: unknown): v is Record<string, unknown> => typeof v === "object" && v !== null && !Array.isArray(v);
const str = (v: unknown): string => (typeof v === "string" ? v : "");
const num = (v: unknown): number | null => (typeof v === "number" && Number.isFinite(v) ? v : null);
const int0 = (v: unknown): number => Math.max(0, Math.round(num(v) ?? 0));

export function parseBalance(v: unknown): Balance | null {
  if (!isObj(v)) return null;
  const balance = num(v.balance);
  if (balance == null) return null;
  return { balance, reserved: num(v.reserved) ?? 0, available: num(v.available) ?? balance, after: num(v.after) };
}

function parseFile(v: unknown): JobFile | null {
  if (!isObj(v) || !str(v.url)) return null;
  return { url: str(v.url), mime: str(v.mime), w: num(v.w), h: num(v.h), poster: str(v.poster) || null, duration: num(v.duration) };
}

export function parseJob(v: unknown): JobJSON | null {
  if (!isObj(v) || !isUid(v.uid)) return null;
  const kind = str(v.kind);
  return {
    uid: v.uid,
    tool: str(v.tool),
    kind: kind === "video" || kind === "character" ? kind : "image",
    status: (str(v.status) || "queued") as JobStatus,
    stage: str(v.stage),
    credits_quoted: int0(v.credits_quoted),
    credits_reserved: int0(v.credits_reserved),
    credits_charged: int0(v.credits_charged),
    created_at: str(v.created_at) || null,
    finished_at: str(v.finished_at) || null,
    error_code: str(v.error_code) || null,
    error: str(v.error) || null,
    results: Array.isArray(v.results) ? (v.results.map(parseFile).filter(Boolean) as JobFile[]) : [],
    params_public: isObj(v.params_public) ? v.params_public : {},
  };
}

function parseTools(v: unknown): ToolsResponse | null {
  if (!isObj(v)) return null;
  const mode = str(v.mode);
  const tools = Array.isArray(v.tools)
    ? v.tools.filter(isObj).map((t) => ({
        id: str(t.id),
        enabled: t.enabled !== false,
        kind: (str(t.kind) || "image") as OutputKind,
        face_consent: t.face_consent === true,
        price_hint_credits: num(t.price_hint_credits),
      }))
    : [];
  return {
    mode: mode === "on" || mode === "off" ? mode : "staff",
    available: v.available === true,
    tools: tools.filter((t) => t.id),
    balance: parseBalance(v.balance),
  };
}

function parseCharacter(v: unknown): CharacterJSON | null {
  if (!isObj(v) || !isUid(v.uid)) return null;
  const s = str(v.status);
  return {
    uid: v.uid,
    name: str(v.name),
    status: s === "ready" || s === "failed" ? s : "training",
    thumb: str(v.thumb) || null,
    created_at: str(v.created_at) || null,
  };
}

/* ------------------------------------------------------------------ */
/* Мелочи                                                              */
/* ------------------------------------------------------------------ */

const UID_RE = /^[0-9a-f]{32}$/;
export function isUid(v: unknown): v is string {
  return typeof v === "string" && UID_RE.test(v);
}

/** client_request_id: 32 hex, один на клик «Создать» (живёт до ответа сервера). */
export function newClientRequestId(): string {
  try {
    const c = globalThis.crypto;
    if (c && typeof c.randomUUID === "function") return c.randomUUID().replace(/-/g, "");
    if (c && typeof c.getRandomValues === "function") {
      const b = new Uint8Array(16);
      c.getRandomValues(b);
      return Array.from(b, (x) => x.toString(16).padStart(2, "0")).join("");
    }
  } catch {
    /* ниже запасной вариант */
  }
  let s = "";
  while (s.length < 32) s += Math.floor(Math.random() * 16).toString(16);
  return s;
}

type Method = "GET" | "POST";

async function call<T>(endpoint: string, method: Method, body?: unknown): Promise<VsResult<T>> {
  const res = await fetchData(endpoint, method, (body ?? undefined) as Parameters<typeof fetchData>[2], true);
  return toResult<T>(res);
}

function mapped<T, U>(r: VsResult<T>, parse: (v: T) => U | null): VsResult<U> {
  if (!r.ok) return r;
  const value = parse(r.data);
  if (value == null) {
    const error: VsError = { status: r.status, code: "bad_response", message: "", data: {} };
    return { ok: false, status: r.status, error };
  }
  return { ok: true, status: r.status, data: value };
}

function localError<T>(code: string, data: Record<string, unknown> = {}): VsResult<T> {
  return { ok: false, status: 400, error: { status: 400, code, message: "", data } };
}

/* ------------------------------------------------------------------ */
/* Эндпоинты                                                           */
/* ------------------------------------------------------------------ */

/** GET tools/ — режим и доступность. AllowAny: сначала тихо обновляем истёкший вход. */
export async function getTools(): Promise<VsResult<ToolsResponse>> {
  try {
    await ensureAccess();
  } catch {
    /* гость — тоже нормально */
  }
  return mapped(await call<unknown>(`${CS}tools/`, "GET"), parseTools);
}

export async function getCatalog(kind: CatalogKind): Promise<VsResult<CatalogItem[] | InfluencerCategory[]>> {
  const r = await call<unknown>(`${CS}catalog/${kind}/`, "GET");
  return mapped(r, (v) => {
    if (!isObj(v)) return null;
    if (kind === "influencer") {
      if (!Array.isArray(v.categories)) return null;
      return v.categories.filter(isObj).map((c) => ({
        key: str(c.key),
        label: str(c.label) || str(c.key),
        max: Math.max(1, int0(c.max) || 1),
        options: Array.isArray(c.options)
          ? c.options.filter(isObj).map((o) => ({
              key: str(o.key),
              label: str(o.label) || str(o.key),
              color: str(o.color) || null,
              exclusive: o.exclusive === true,
              preview: str(o.preview) || null,
            })).filter((o) => o.key)
          : [],
      })).filter((c) => c.key && c.options.length);
    }
    if (!Array.isArray(v.items)) return null;
    return v.items.filter(isObj).map((i) => ({
      id: str(i.id),
      name: str(i.name),
      n: int0(i.n),
      preview: str(i.preview) || null,
      aspect: str(i.aspect) || null,
      group: str(i.group) || null,
    })).filter((i) => i.id);
  });
}

export async function quote(tool: string, params: Record<string, unknown>, lang?: string): Promise<VsResult<QuoteJSON>> {
  const r = await call<unknown>(`${CS}quote/`, "POST", { tool, params, lang });
  return mapped(r, (v) => {
    if (!isObj(v) || num(v.credits) == null) return null;
    return { credits: int0(v.credits), tool: str(v.tool), outputs: Math.max(1, int0(v.outputs) || 1), eta_s: int0(v.eta_s), balance: parseBalance(v.balance) };
  });
}

export async function run(body: RunBody): Promise<VsResult<RunResponse>> {
  const r = await call<unknown>(`${CS}run/`, "POST", body);
  return mapped(r, (v) => {
    if (!isObj(v)) return null;
    const job = parseJob(v.job);
    return job ? { job, balance: parseBalance(v.balance) } : null;
  });
}

export async function getJobs(opts: { tool?: string; page?: number } = {}): Promise<VsResult<JobsPage>> {
  const sp = new URLSearchParams();
  if (opts.tool) sp.set("tool", opts.tool);
  if (opts.page && opts.page > 1) sp.set("page", String(opts.page));
  const q = sp.toString();
  const r = await call<unknown>(`${CS}jobs/${q ? `?${q}` : ""}`, "GET");
  return mapped(r, (v) => {
    if (!isObj(v) || !Array.isArray(v.items)) return null;
    return { items: v.items.map(parseJob).filter(Boolean) as JobJSON[], page: int0(v.page) || 1, has_more: v.has_more === true };
  });
}

export async function getJob(uid: string): Promise<VsResult<JobJSON>> {
  if (!isUid(uid)) return localError("job_not_found");
  return mapped(await call<unknown>(`${CS}jobs/${uid}/`, "GET"), parseJob);
}

export async function cancelJob(uid: string): Promise<VsResult<RunResponse>> {
  if (!isUid(uid)) return localError("job_not_found");
  const r = await call<unknown>(`${CS}jobs/${uid}/cancel/`, "POST", {});
  return mapped(r, (v) => {
    if (!isObj(v)) return null;
    const job = parseJob(v.job);
    return job ? { job, balance: parseBalance(v.balance) } : null;
  });
}

export async function getCharacters(): Promise<VsResult<CharacterJSON[]>> {
  const r = await call<unknown>(`${CS}characters/`, "GET");
  return mapped(r, (v) => (isObj(v) && Array.isArray(v.items) ? (v.items.map(parseCharacter).filter(Boolean) as CharacterJSON[]) : null));
}

export async function hideCharacter(uid: string): Promise<VsResult<{ ok: boolean }>> {
  if (!isUid(uid)) return localError("character_not_found");
  return call<{ ok: boolean }>(`${CS}characters/${uid}/hide/`, "POST", {});
}

/* ------------------------------------------------------------------ */
/* Загрузка файла: XHR с прогрессом и отменой                          */
/* ------------------------------------------------------------------ */

export type UploadPhase = "upload" | "processing";
export type UploadOptions = {
  onProgress?: (pct: number, phase: UploadPhase) => void;
  signal?: AbortSignal;
};

/** Предел тела у nginx/Cloudflare для видео (как у склейки); больше — 413 без кода. */
export const VIDEO_MAX_MB = 90;
export const IMAGE_MAX_MB = 20;

function parseJson(text: string): unknown {
  if (!text) return null;
  try {
    return JSON.parse(text);
  } catch {
    return text;
  }
}

function sendUpload(file: Blob, name: string, kind: UploadKind, opts: UploadOptions): Promise<VsResult<UploadJSON>> {
  const { onProgress, signal } = opts;
  const form = new FormData();
  form.append("kind", kind);
  form.append("file", file, name);
  return new Promise((resolve) => {
    const xhr = new XMLHttpRequest();
    let settled = false;
    const done = (r: VsResult<UploadJSON>) => {
      if (settled) return;
      settled = true;
      signal?.removeEventListener("abort", onAbort);
      resolve(r);
    };
    const onAbort = () => {
      try {
        xhr.abort();
      } catch {
        /* уже закрыт */
      }
      done({ ok: false, status: 0, error: abortedError() });
    };
    const finish = (status: number, text: string) => {
      // Больше предела nginx до Django не доходит: 413 своей HTML-страницей.
      if (status === 413) {
        const maxMb = kind === "video" ? VIDEO_MAX_MB : IMAGE_MAX_MB;
        done({ ok: false, status, error: { status, code: "too_big", message: "", data: { max_mb: maxMb } } });
        return;
      }
      const r = toResult<unknown>({ ok: status >= 200 && status < 300, status, data: parseJson(text) });
      done(
        mapped(r, (v) => {
          if (!isObj(v) || !isUid(v.uid)) return null;
          return { uid: v.uid, kind: str(v.kind) === "video" ? "video" : "image", w: num(v.w), h: num(v.h), duration: num(v.duration), preview: str(v.preview) };
        }),
      );
    };
    xhr.open("POST", `${API}${CS}uploads/`, true);
    xhr.setRequestHeader("Accept", "application/json");
    xhr.setRequestHeader("X-Requested-With", "XMLHttpRequest");
    const token = getToken("access");
    if (token) xhr.setRequestHeader("Authorization", `Bearer ${token}`);
    let csrf: string | undefined;
    try {
      csrf = Cookies.get("csrftoken") || undefined;
    } catch {
      csrf = undefined;
    }
    if (csrf) xhr.setRequestHeader("X-CSRFToken", csrf);
    if (xhr.upload) {
      xhr.upload.onprogress = (e: ProgressEvent) => {
        if (e.lengthComputable && e.total > 0) onProgress?.(Math.min(99, Math.floor((e.loaded / e.total) * 100)), "upload");
      };
      xhr.upload.onload = () => onProgress?.(100, "processing");
    }
    xhr.onload = () => finish(xhr.status, xhr.responseText);
    xhr.onerror = () => finish(0, "");
    xhr.ontimeout = () => finish(0, "");
    xhr.onabort = () => done({ ok: false, status: 0, error: abortedError() });
    signal?.addEventListener("abort", onAbort);
    onProgress?.(0, "upload");
    xhr.send(form);
  });
}

/**
 * POST uploads/ (multipart: file, kind). Токен проверяем прямо перед отправкой;
 * если он истёк, пока файл шёл по медленной сети, — обновляем и шлём ещё раз, один.
 */
export async function uploadFile(file: Blob, name: string, kind: UploadKind, opts: UploadOptions = {}): Promise<VsResult<UploadJSON>> {
  if (opts.signal?.aborted) return { ok: false, status: 0, error: abortedError() };
  const unauthorized: VsResult<UploadJSON> = { ok: false, status: 401, error: { status: 401, code: "unauthorized", message: "", data: {} } };
  if (!(await ensureAccess())) return unauthorized;
  const token = getToken("access");
  const first = await sendUpload(file, name, kind, opts);
  if (first.ok || first.status !== 401 || opts.signal?.aborted) return first;
  if (!(await ensureAccess()) || getToken("access") === token) return first;
  return sendUpload(file, name, kind, opts);
}
