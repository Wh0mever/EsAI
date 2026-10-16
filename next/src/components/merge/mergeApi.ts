/**
 * «Склейка видео»: обёртки над /api/merge/ (CONTRACT_M.md). Ходят через
 * fetchData и никогда не бросают: ответ — VsResult той же формы, что у
 * видеостудии (error_code из тела, русский текст сервера в message).
 */
import { fetchData } from "@/tools/fetchData";
import { toResult } from "@/lib/vstudio/errors";
import type { VsResult } from "@/lib/vstudio/types";
import { isUid } from "./mergeLogic";
import type {
  MergeConfig,
  MergeEditBody,
  MergeList,
  MergeProject,
  MergeRenderBody,
  MergeSourcesPage,
  MergeTab,
} from "./mergeTypes";

const M = "merge/";

type Method = "GET" | "POST" | "PATCH" | "DELETE";
type Body = Parameters<typeof fetchData>[2];

async function call<T>(endpoint: string, method: Method, body?: object, allowEmpty = false): Promise<VsResult<T>> {
  // auth всегда: гостю заголовок просто не ставится, а config/ вошедшему отдаёт баланс.
  const res = await fetchData(endpoint, method, (body ?? undefined) as Body, true);
  return toResult<T>(res, { allowEmpty });
}

/**
 * ?lang= — язык страницы: подписи, которые ставит сервер (ролик без промпта,
 * название новой склейки), иначе шли бы по языку браузера, а не выбранному.
 */
function withLang(endpoint: string, lang?: string): string {
  return lang ? `${endpoint}${endpoint.includes("?") ? "&" : "?"}lang=${encodeURIComponent(lang)}` : endpoint;
}

/** Кривой id в запрос не уходит: адрес с ним не совпал бы ни с одним маршрутом. */
function notFound<T>(): VsResult<T> {
  return { ok: false, status: 404, error: { status: 404, code: "project_not_found", message: "", data: {} } };
}

export function getConfig(): Promise<VsResult<MergeConfig>> {
  return call<MergeConfig>(`${M}config/`, "GET");
}

export function listSources(tab: MergeTab, page: number, lang: string): Promise<VsResult<MergeSourcesPage>> {
  const q = new URLSearchParams({ type: tab, page: String(page), lang });
  return call<MergeSourcesPage>(`${M}sources/?${q}`, "GET");
}

export function listProjects(page = 1): Promise<VsResult<MergeList>> {
  return call<MergeList>(`${M}?page=${page}`, "GET");
}

export function createProject(body: MergeEditBody, lang?: string): Promise<VsResult<MergeProject>> {
  return call<MergeProject>(withLang(M, lang), "POST", body);
}

export function getProject(id: string, lang?: string): Promise<VsResult<MergeProject>> {
  return isUid(id) ? call<MergeProject>(withLang(`${M}${id}/`, lang), "GET") : Promise.resolve(notFound<MergeProject>());
}

export function patchProject(id: string, body: MergeEditBody, lang?: string): Promise<VsResult<MergeProject>> {
  return isUid(id)
    ? call<MergeProject>(withLang(`${M}${id}/`, lang), "PATCH", body)
    : Promise.resolve(notFound<MergeProject>());
}

export function deleteProject(id: string): Promise<VsResult<null>> {
  return isUid(id) ? call<null>(`${M}${id}/`, "DELETE", undefined, true) : Promise.resolve(notFound<null>());
}

/** 202 — поставлена в очередь, 200 — уже идёт (повторное нажатие, второго резерва нет). */
export function renderProject(id: string, body: MergeRenderBody, lang?: string): Promise<VsResult<MergeProject>> {
  return isUid(id)
    ? call<MergeProject>(withLang(`${M}${id}/render/`, lang), "POST", body)
    : Promise.resolve(notFound<MergeProject>());
}
