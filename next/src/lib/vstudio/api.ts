/**
 * Видеостудия: типизированный слой над /api/vstudio/ (§8.2).
 *
 * Все обёртки ходят через fetchData (сам он не меняется) и никогда не бросают:
 * ответ — VsResult с error_code, прочитанным из тела (errors.ts). Загрузка
 * файла — через XHR, потому что у fetch нет прогресса отправки.
 *
 * Режим фикстур (fixtures.ts) подменяет сервер целиком, чтобы FE-1…FE-5
 * работали без бэкенда: NEXT_PUBLIC_VSTUDIO_FIXTURES=1 в сборке или, только
 * вне production, localStorage["vstudio:fixtures"]="1". Модуль фикстур грузится
 * динамически и в обычную сборку страницы не попадает.
 */
import Cookies from "js-cookie";
import { ensureAccess, fetchData, getToken, API } from "@/tools/fetchData";
import { trackFunnel } from "@/tools/funnel";
import { abortedError, toResult, type RawResponse } from "./errors";
import type {
  ActiveTake,
  AssetJSON,
  ComposerState,
  CondenseBody,
  CondenseResponse,
  LibraryFilter,
  ListAssetsQuery,
  ListProjectsQuery,
  ListShotsQuery,
  ModelsResponse,
  Paged,
  ProjectJSON,
  ProjectPatch,
  QuoteBody,
  QuoteJSON,
  QuoteRequest,
  RetryBody,
  RetryResponse,
  RunShotBody,
  RunShotResponse,
  ShotInputBody,
  ShotJSON,
  ShotParams,
  TakeJSON,
  TakeLite,
  Uid,
  UploadPhase,
  UploadResult,
  VsError,
  VsFunnelMeta,
  VsResult,
} from "./types";

export const VS = "vstudio/";
/** Предел GET takes/?ids= на один запрос. */
export const MAX_POLL_IDS = 30;

type Method = "GET" | "POST" | "PATCH" | "DELETE";
type CallOpts = { signal?: AbortSignal; allowEmpty?: boolean };

/* ------------------------------------------------------------------ */
/* Режим фикстур                                                       */
/* ------------------------------------------------------------------ */

let fixturesOverride: boolean | null = null;

/** Для тестов и отладки: true/false — принудительно, null — по окружению. */
export function setFixturesMode(on: boolean | null): void {
  fixturesOverride = on;
}

export function fixturesEnabled(): boolean {
  if (fixturesOverride !== null) return fixturesOverride;
  if (process.env.NEXT_PUBLIC_VSTUDIO_FIXTURES === "1") return true;
  // В проде локальный флажок не включает фикстуры: человек не должен случайно
  // увидеть «сгенерированное» видео, за которое никто не платил.
  if (process.env.NODE_ENV === "production") return false;
  try {
    return typeof window !== "undefined" && window.localStorage.getItem("vstudio:fixtures") === "1";
  } catch {
    return false;
  }
}

async function mock() {
  const mod = await import("./fixtures");
  return mod.getMockBackend();
}

/* ------------------------------------------------------------------ */
/* Мелочи                                                              */
/* ------------------------------------------------------------------ */

const UID_RE = /^[0-9a-f]{32}$/;

/** uid из адреса (?take=) и из ответа — только 32 hex: иначе запрос не уходит вовсе. */
export function isUid(v: unknown): v is Uid {
  return typeof v === "string" && UID_RE.test(v);
}

/** client_request_id: 32 hex, один на клик «Создать» (живёт до ответа). */
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

function badUid(what: string): VsResult<never> {
  const error: VsError = { status: 400, code: "bad_request", message: "", data: { field: what } };
  return { ok: false, status: 400, error };
}

function qs(params: Record<string, string | number | boolean | null | undefined>): string {
  const sp = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) {
    if (v === undefined || v === null || v === "") continue;
    sp.set(k, typeof v === "boolean" ? (v ? "1" : "0") : String(v));
  }
  const s = sp.toString();
  return s ? `?${s}` : "";
}

async function call<T>(endpoint: string, method: Method, body?: unknown, opts?: CallOpts): Promise<VsResult<T>> {
  if (opts?.signal?.aborted) return { ok: false, status: 0, error: abortedError() };
  let res: RawResponse;
  if (fixturesEnabled()) {
    res = await (await mock()).fetch(endpoint, method, body);
  } else {
    // auth=true всегда: гостю заголовок просто не ставится, а вошедшему AllowAny
    // (models/, quote/) считает locked и баланс по его тарифу.
    res = await fetchData(endpoint, method, (body ?? undefined) as Parameters<typeof fetchData>[2], true);
  }
  // fetchData не умеет AbortSignal: запрос долетает, но устаревший ответ выбрасываем.
  if (opts?.signal?.aborted) return { ok: false, status: 0, error: abortedError() };
  return toResult<T>(res, { allowEmpty: opts?.allowEmpty });
}

/** AllowAny-эндпоинты: сначала тихо обновить истёкший access, чтобы мёртвая сессия не увела на вход. */
async function withFreshAccess(): Promise<void> {
  if (fixturesEnabled()) return;
  try {
    await ensureAccess();
  } catch {
    /* гость — тоже нормально */
  }
}

/* ------------------------------------------------------------------ */
/* Модели и цена                                                       */
/* ------------------------------------------------------------------ */

export async function getModels(opts?: CallOpts): Promise<VsResult<ModelsResponse>> {
  await withFreshAccess();
  return call<ModelsResponse>(`${VS}models/`, "GET", undefined, opts);
}

/** Ошибки компилятора приходят внутри QuoteJSON (200), а не кодом HTTP. */
export async function quote(body: QuoteRequest, opts?: CallOpts): Promise<VsResult<QuoteJSON>> {
  await withFreshAccess();
  return call<QuoteJSON>(`${VS}quote/`, "POST", body, opts);
}

/* ------------------------------------------------------------------ */
/* Проекты                                                             */
/* ------------------------------------------------------------------ */

export function listProjects(q: ListProjectsQuery = {}, opts?: CallOpts): Promise<VsResult<Paged<ProjectJSON>>> {
  const query = qs({
    q: q.q?.trim() || undefined,
    archived: q.archived ?? false,
    before: q.before ?? undefined,
    limit: q.limit,
  });
  return call<Paged<ProjectJSON>>(`${VS}projects/${query}`, "GET", undefined, opts);
}

export function createProject(body: { title?: string } = {}): Promise<VsResult<ProjectJSON>> {
  return call<ProjectJSON>(`${VS}projects/`, "POST", body);
}

export async function getProject(uid: Uid, opts?: CallOpts): Promise<VsResult<ProjectJSON>> {
  if (!isUid(uid)) return badUid("project");
  return call<ProjectJSON>(`${VS}projects/${uid}/`, "GET", undefined, opts);
}

export async function updateProject(uid: Uid, patch: ProjectPatch): Promise<VsResult<ProjectJSON>> {
  if (!isUid(uid)) return badUid("project");
  return call<ProjectJSON>(`${VS}projects/${uid}/`, "PATCH", patch);
}

/** DELETE = мягко в архив, 204. */
export async function archiveProject(uid: Uid): Promise<VsResult<null>> {
  if (!isUid(uid)) return badUid("project");
  return call<null>(`${VS}projects/${uid}/`, "DELETE", undefined, { allowEmpty: true });
}

/** Страница кадров от новых к старым; внутри страницы — по возрастанию. next — uid для before. */
export async function listShots(
  projectUid: Uid,
  q: ListShotsQuery = {},
  opts?: CallOpts,
): Promise<VsResult<Paged<ShotJSON>>> {
  if (!isUid(projectUid)) return badUid("project");
  if (q.before && !isUid(q.before)) return badUid("before");
  const query = qs({ before: q.before ?? undefined, limit: q.limit });
  return call<Paged<ShotJSON>>(`${VS}projects/${projectUid}/shots/${query}`, "GET", undefined, opts);
}

/* ------------------------------------------------------------------ */
/* Материалы                                                           */
/* ------------------------------------------------------------------ */

/** Фильтры «Моих материалов» → параметр source у GET assets/. */
export const LIBRARY_FILTER_SOURCE: Record<LibraryFilter, ListAssetsQuery["source"]> = {
  all: "",
  uploads: "upload",
  generated: "generated_image",
  frames: "frame",
};

export function listAssets(q: ListAssetsQuery = {}, opts?: CallOpts): Promise<VsResult<Paged<AssetJSON>>> {
  const query = qs({ kind: q.kind ?? "image", source: q.source || undefined, before: q.before ?? undefined, limit: q.limit });
  return call<Paged<AssetJSON>>(`${VS}assets/${query}`, "GET", undefined, opts);
}

export async function deleteAsset(uid: Uid): Promise<VsResult<null>> {
  if (!isUid(uid)) return badUid("asset");
  return call<null>(`${VS}assets/${uid}/`, "DELETE", undefined, { allowEmpty: true });
}

/** «Последний кадр → первый»: кадр из своего готового видео. */
export async function assetFromTake(takeUid: Uid): Promise<VsResult<AssetJSON>> {
  if (!isUid(takeUid)) return badUid("take");
  return call<AssetJSON>(`${VS}assets/from-take/`, "POST", { take: takeUid, at: "last_frame" });
}

export type UploadOptions = {
  project?: Uid | null;
  /** Имя файла для Blob без имени (например, после уменьшения через canvas). */
  filename?: string;
  /** pct 0…100; phase=processing — файл ушёл, сервер нормализует фото. */
  onProgress?: (pct: number, phase: UploadPhase) => void;
  signal?: AbortSignal;
};

function readCsrf(): string | undefined {
  try {
    return Cookies.get("csrftoken") || undefined;
  } catch {
    return undefined;
  }
}

function parseJson(text: string): unknown {
  if (!text) return null;
  try {
    return JSON.parse(text);
  } catch {
    return text;
  }
}

/**
 * POST assets/ — ровно один файл, с прогрессом (XHR). 201 — новый ассет,
 * 200 — тот же файл уже был (duplicate). Гостю запрос не отправляется: 401.
 */
export async function uploadAsset(file: Blob, opts: UploadOptions = {}): Promise<VsResult<UploadResult>> {
  const { project, onProgress, signal } = opts;
  if (signal?.aborted) return { ok: false, status: 0, error: abortedError() };
  if (project != null && !isUid(project)) return badUid("project");

  const finish = (raw: RawResponse): VsResult<UploadResult> => {
    const res = toResult<AssetJSON>(raw);
    if (!res.ok) return res;
    return { ok: true, status: res.status, data: { asset: res.data, duplicate: res.status === 200 } };
  };

  if (fixturesEnabled()) {
    return finish(await (await mock()).upload(file, { project: project ?? null, onProgress, signal }));
  }

  if (!(await ensureAccess())) {
    return {
      ok: false,
      status: 401,
      error: { status: 401, code: "unauthorized", message: "", data: {} },
    };
  }

  const form = new FormData();
  const name =
    opts.filename || (typeof File !== "undefined" && file instanceof File && file.name ? file.name : "photo.jpg");
  form.append("file", file, name);
  if (project) form.append("project", project);

  return new Promise<VsResult<UploadResult>>((resolve) => {
    const xhr = new XMLHttpRequest();
    let settled = false;
    const done = (r: VsResult<UploadResult>) => {
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

    xhr.open("POST", `${API}${VS}assets/`, true);
    xhr.setRequestHeader("Accept", "application/json");
    xhr.setRequestHeader("X-Requested-With", "XMLHttpRequest");
    const token = getToken("access");
    if (token) xhr.setRequestHeader("Authorization", `Bearer ${token}`);
    const csrf = readCsrf();
    if (csrf) xhr.setRequestHeader("X-CSRFToken", csrf);

    if (xhr.upload) {
      xhr.upload.onprogress = (e: ProgressEvent) => {
        if (e.lengthComputable && e.total > 0) {
          onProgress?.(Math.min(99, Math.floor((e.loaded / e.total) * 100)), "upload");
        }
      };
      // Байты ушли — дальше сервер перекодирует фото (HEIC до 2–3 с).
      xhr.upload.onload = () => onProgress?.(100, "processing");
    }
    xhr.onload = () =>
      done(finish({ ok: xhr.status >= 200 && xhr.status < 300, status: xhr.status, data: parseJson(xhr.responseText) }));
    xhr.onerror = () => done(finish({ ok: false, status: 0, data: null }));
    xhr.ontimeout = () => done(finish({ ok: false, status: 0, data: null }));
    xhr.onabort = () => done({ ok: false, status: 0, error: abortedError() });
    signal?.addEventListener("abort", onAbort);

    onProgress?.(0, "upload");
    xhr.send(form);
  });
}

/* ------------------------------------------------------------------ */
/* Запуск и дубли                                                      */
/* ------------------------------------------------------------------ */

/** 202 — принято (200 — повтор того же client_request_id). */
export function runShot(body: RunShotBody): Promise<VsResult<RunShotResponse>> {
  return call<RunShotResponse>(`${VS}shots/`, "POST", body);
}

/** Новый дубль того же кадра — после нового quote({shot}). */
export async function retryShot(shotUid: Uid, body: RetryBody): Promise<VsResult<RetryResponse>> {
  if (!isUid(shotUid)) return badUid("shot");
  return call<RetryResponse>(`${VS}shots/${shotUid}/retry/`, "POST", body);
}

/**
 * Опрос статусов: GET takes/?ids= пачками по 30. Чужие и неизвестные uid
 * сервер просто не вернёт. Одна неудачная пачка — ошибка всего опроса
 * (следующий тик повторит).
 */
export async function pollTakes(uids: Uid[], opts?: CallOpts): Promise<VsResult<{ items: TakeLite[] }>> {
  const ids = Array.from(new Set(uids.filter(isUid)));
  if (!ids.length) return { ok: true, status: 200, data: { items: [] } };
  const chunks: Uid[][] = [];
  for (let i = 0; i < ids.length; i += MAX_POLL_IDS) chunks.push(ids.slice(i, i + MAX_POLL_IDS));
  const results = await Promise.all(
    chunks.map((c) => call<{ items: TakeLite[] }>(`${VS}takes/${qs({ ids: c.join(",") })}`, "GET", undefined, opts)),
  );
  const items: TakeLite[] = [];
  for (const r of results) {
    if (!r.ok) return r;
    items.push(...(r.data.items || []));
  }
  return { ok: true, status: 200, data: { items } };
}

/** Открытые дубли по всем проектам — «Восстановили N генераций». */
export function activeTakes(opts?: CallOpts): Promise<VsResult<{ items: ActiveTake[] }>> {
  return call<{ items: ActiveTake[] }>(`${VS}takes/active/`, "GET", undefined, opts);
}

/** «Что ушло модели»: serialized_prompt и request_body. */
export async function getTake(uid: Uid, opts?: CallOpts): Promise<VsResult<TakeJSON>> {
  if (!isUid(uid)) return badUid("take");
  return call<TakeJSON>(`${VS}takes/${uid}/`, "GET", undefined, opts);
}

/** Отмена только из queued; иначе 409 already_submitted. */
export async function cancelTake(uid: Uid): Promise<VsResult<TakeLite>> {
  if (!isUid(uid)) return badUid("take");
  return call<TakeLite>(`${VS}takes/${uid}/cancel/`, "POST", {});
}

/** «Сжать с ИИ»: бесплатно, 20 в час; 422 condense_failed, если теги не сошлись. */
export function condense(body: CondenseBody, opts?: CallOpts): Promise<VsResult<CondenseResponse>> {
  return call<CondenseResponse>(`${VS}assist/condense/`, "POST", body, opts);
}

/** «Поделиться»: существующий эндпоинт чата, владение — по GenerationLog.result_url. */
export function shareVideo(
  url: string,
  meta: { prompt?: string; model?: string } = {},
): Promise<VsResult<{ share_url: string }>> {
  return call<{ share_url: string }>("ai/video/share/", "POST", {
    url,
    prompt: meta.prompt || "",
    model: meta.model || "",
  });
}

/* ------------------------------------------------------------------ */
/* Тело запроса из композера                                           */
/* ------------------------------------------------------------------ */

/**
 * Входы запроса из лотка и слотов кадров. Уходят все материалы с assetUid,
 * включая выключенные (included=false) и ещё создающиеся: сервер сам скажет
 * asset_not_ready / input_excluded. Чипы без uid (идёт загрузка) не уходят.
 */
export function buildInputs(tray: ComposerState["tray"], frames: ComposerState["frames"]): ShotInputBody[] {
  const out: ShotInputBody[] = [];
  let position = 0;
  for (const item of tray) {
    if (!item.assetUid) continue;
    out.push({
      asset: item.assetUid,
      slot: "reference",
      position: position++,
      role: item.role.trim() || undefined,
      included: item.included,
    });
  }
  for (const slot of ["first_frame", "last_frame"] as const) {
    const item = frames[slot];
    if (!item?.assetUid) continue;
    out.push({ asset: item.assetUid, slot, position: 0, role: item.role.trim() || undefined, included: item.included });
  }
  return out;
}

/** Параметры, которые имеют смысл для вида: у картинки нет длительности, звука и негатива. */
export function paramsFor(kind: ComposerState["kind"], params: ShotParams): ShotParams {
  if (kind === "image") {
    const out: ShotParams = {};
    if (params.aspect_ratio) out.aspect_ratio = params.aspect_ratio;
    if (params.seed != null) out.seed = params.seed;
    return out;
  }
  const out: ShotParams = { ...params };
  if (!out.negative_prompt) delete out.negative_prompt;
  if (out.seed == null) delete out.seed;
  return out;
}

/** QuoteBody из композера; null — модель ещё не выбрана. */
export function quoteBodyFrom(
  composer: Pick<ComposerState, "kind" | "model" | "params" | "doc" | "tray" | "frames">,
  project: Uid | null,
): QuoteBody | null {
  if (!composer.model) return null;
  return {
    project: isUid(project) ? project : null,
    kind: composer.kind,
    model: composer.model,
    prompt_doc: composer.doc,
    inputs: buildInputs(composer.tray, composer.frames),
    params: paramsFor(composer.kind, composer.params),
  };
}

/** Стабильный ключ тела: цена из quote годится для запуска, только если ключ совпал. */
export function quoteKey(body: QuoteRequest | null): string {
  if (!body) return "";
  return JSON.stringify(body, (_k, v) =>
    v && typeof v === "object" && !Array.isArray(v)
      ? Object.fromEntries(Object.keys(v).sort().map((k) => [k, (v as Record<string, unknown>)[k]]))
      : v,
  );
}

/* ------------------------------------------------------------------ */
/* Воронка                                                             */
/* ------------------------------------------------------------------ */

/** trackFunnel с проверкой meta по шагу (§11). В режиме фикстур молчит. */
export function trackVs<K extends keyof VsFunnelMeta>(
  name: K,
  ...meta: VsFunnelMeta[K] extends undefined ? [] : [VsFunnelMeta[K]]
): void {
  if (fixturesEnabled()) return;
  const m = (meta as unknown[])[0] as Record<string, unknown> | undefined;
  trackFunnel(name, m);
}
