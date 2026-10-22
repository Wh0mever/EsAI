/**
 * «Склейка видео»: обёртки над /api/merge/ (CONTRACT_M.md). Ходят через
 * fetchData и никогда не бросают: ответ — VsResult той же формы, что у
 * видеостудии (error_code из тела, русский текст сервера в message).
 * Загрузка своего видео и своего трека — через XHR: у fetch нет прогресса отправки.
 */
import Cookies from "js-cookie";
import { API, ensureAccess, fetchData, getToken } from "@/tools/fetchData";
import { abortedError, toResult } from "@/lib/vstudio/errors";
import type { VsResult } from "@/lib/vstudio/types";
import { isUid } from "./mergeLogic";
import type {
  MergeAudioSettings,
  MergeAudioState,
  MergeConfig,
  MergeEditBody,
  MergeList,
  MergeMusicBody,
  MergeProject,
  MergeRenderBody,
  MergeSourcesPage,
  MergeTab,
  MergeUploadCard,
  MergeUploadList,
  MergeVoice,
  MergeVoiceBody,
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
function notFound<T>(code = "project_not_found"): VsResult<T> {
  return { ok: false, status: 404, error: { status: 404, code, message: "", data: {} } };
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

/* ---------- свои видео (CONTRACT_M.md §9) ---------- */

/** «Мои файлы»: все свои видео (до 10), занятое место и пределы. */
export function listUploads(lang?: string): Promise<VsResult<MergeUploadList>> {
  return call<MergeUploadList>(withLang(`${M}uploads/`, lang), "GET");
}

/** 204; чужое или уже удалённое — 404 upload_not_found, идёт его склейка — 409 upload_in_use. */
export function deleteUpload(id: string): Promise<VsResult<null>> {
  return isUid(id)
    ? call<null>(`${M}uploads/${id}/`, "DELETE", undefined, true)
    : Promise.resolve(notFound<null>("upload_not_found"));
}

export type UploadPhase = "upload" | "processing";

export type UploadVideoOptions = {
  /** Имя для сервера (uploadName): с расширением, даже если у файла его не было. */
  filename?: string;
  lang?: string;
  /** pct 0…100; processing — байты ушли, сервер проверяет видео и делает обложку. */
  onProgress?: (pct: number, phase: UploadPhase) => void;
  signal?: AbortSignal;
};

function parseJson(text: string): unknown {
  if (!text) return null;
  try {
    return JSON.parse(text);
  } catch {
    return text;
  }
}

function readCsrf(): string | undefined {
  try {
    return Cookies.get("csrftoken") || undefined;
  } catch {
    return undefined;
  }
}

/** Отказ 413 от nginx (HTML, без кода): какой код и предел показать человеку. */
type TooBig = { code: string; maxMb: number };

/** multipart с полем file через XHR: прогресс отправки, отмена, 413 nginx → свой код. */
function sendFile<T>(
  endpoint: string,
  file: Blob,
  name: string,
  tooBig: TooBig,
  opts: { onProgress?: (pct: number, phase: UploadPhase) => void; signal?: AbortSignal },
): Promise<VsResult<T>> {
  const { onProgress, signal } = opts;
  const form = new FormData();
  form.append("file", file, name);

  return new Promise<VsResult<T>>((resolve) => {
    const xhr = new XMLHttpRequest();
    let settled = false;
    const done = (r: VsResult<T>) => {
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
      // Больше предела nginx до Django не доходит: nginx (и Cloudflare) отвечают 413 своей HTML-страницей.
      if (status === 413) {
        done({ ok: false, status, error: { status, code: tooBig.code, message: "", data: { max_mb: tooBig.maxMb } } });
        return;
      }
      done(toResult<T>({ ok: status >= 200 && status < 300, status, data: parseJson(text) }));
    };

    xhr.open("POST", `${API}${endpoint}`, true);
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
 * Токен проверяем прямо перед отправкой. Сервер видит запрос только целиком:
 * если токен всё же истёк, пока файл шёл по медленной сети, — обновляем и
 * шлём ещё раз, один.
 */
async function sendWithFreshToken<T>(send: () => Promise<VsResult<T>>, signal?: AbortSignal): Promise<VsResult<T>> {
  const unauthorized: VsResult<T> = {
    ok: false,
    status: 401,
    error: { status: 401, code: "unauthorized", message: "", data: {} },
  };
  if (signal?.aborted) return { ok: false, status: 0, error: abortedError() };
  if (!(await ensureAccess())) return unauthorized;
  const token = getToken("access");
  const first = await send();
  if (first.ok || first.status !== 401 || signal?.aborted) return first;
  // Токен тот же — второй раз будет тот же отказ.
  if (!(await ensureAccess()) || getToken("access") === token) return first;
  return send();
}

/** POST uploads/ (multipart, поле file) → 201 карточка. */
export function uploadVideo(file: Blob, opts: UploadVideoOptions = {}): Promise<VsResult<MergeUploadCard>> {
  const name = opts.filename || (typeof File !== "undefined" && file instanceof File && file.name ? file.name : "video.mp4");
  const endpoint = withLang(`${M}uploads/`, opts.lang);
  return sendWithFreshToken(
    () => sendFile<MergeUploadCard>(endpoint, file, name, { code: "upload_too_big", maxMb: 90 }, opts),
    opts.signal,
  );
}

/* ---------- звук склейки (CONTRACT_M.md §10) ---------- */

function audioPath(id: string, tail = ""): string {
  return `${M}${id}/audio/${tail}`;
}

/** Всё о звуке склейки: дорожки, звук роликов, громкости, цены, пределы. */
export function getAudio(id: string): Promise<VsResult<MergeAudioState>> {
  return isUid(id) ? call<MergeAudioState>(audioPath(id), "GET") : Promise.resolve(notFound<MergeAudioState>());
}

/** Звук роликов, громкости, фрагмент голоса — бесплатно; отказ одного поля — отказ всей правки. */
export function patchAudio(id: string, body: MergeAudioSettings): Promise<VsResult<MergeAudioState>> {
  return isUid(id) ? call<MergeAudioState>(audioPath(id), "PATCH", body) : Promise.resolve(notFound<MergeAudioState>());
}

/** 201 — голос сделан и оплачен (ответ ждёт ElevenLabs); 200 — этот request_id уже был. */
export function makeVoice(id: string, body: MergeVoiceBody): Promise<VsResult<MergeAudioState>> {
  return isUid(id)
    ? call<MergeAudioState>(audioPath(id, "voice/"), "POST", body)
    : Promise.resolve(notFound<MergeAudioState>());
}

/** 202 — кредиты в резерве, музыку делает очередь (опрашивать GET audio/); 200 — этот request_id уже был. */
export function makeMusic(id: string, body: MergeMusicBody): Promise<VsResult<MergeAudioState>> {
  return isUid(id)
    ? call<MergeAudioState>(audioPath(id, "music/"), "POST", body)
    : Promise.resolve(notFound<MergeAudioState>());
}

/** Убрать дорожку → 200 и состояние звука; ещё делается — 409 audio_busy. */
export function deleteTrack(id: string, trackId: string): Promise<VsResult<MergeAudioState>> {
  return isUid(id) && isUid(trackId)
    ? call<MergeAudioState>(audioPath(id, `${trackId}/`), "DELETE")
    : Promise.resolve(notFound<MergeAudioState>("audio_not_found"));
}

export type UploadMusicOptions = {
  /** Имя для сервера (audioUploadName): с расширением, даже если у файла его не было. */
  filename?: string;
  onProgress?: (pct: number, phase: UploadPhase) => void;
  signal?: AbortSignal;
};

/** Свой трек вместо музыки (multipart, поле file) → 201 и состояние звука; бесплатно. */
export function uploadMusic(id: string, file: Blob, opts: UploadMusicOptions = {}): Promise<VsResult<MergeAudioState>> {
  if (!isUid(id)) return Promise.resolve(notFound<MergeAudioState>());
  const name = opts.filename || (typeof File !== "undefined" && file instanceof File && file.name ? file.name : "music.mp3");
  return sendWithFreshToken(
    () => sendFile<MergeAudioState>(audioPath(id, "music/upload/"), file, name, { code: "audio_too_big", maxMb: 20 }, opts),
    opts.signal,
  );
}

/** Голоса — общие с мультстудией; ElevenLabs выключен или лежит — пустой список. */
export function listVoices(): Promise<VsResult<MergeVoice[]>> {
  return call<MergeVoice[]>("cartoon/audio/voices/", "GET");
}

/** Пример голоса на языке страницы: {url} mp3. Ответ мультстудии — {detail} при отказе. */
export function voicePreview(voiceId: string, lang: string): Promise<VsResult<{ url: string }>> {
  if (!/^[A-Za-z0-9_-]{2,64}$/.test(voiceId)) return Promise.resolve(notFound<{ url: string }>("not_found"));
  const q = new URLSearchParams({ lang });
  return call<{ url: string }>(`cartoon/audio/voices/${voiceId}/preview/?${q}`, "GET");
}
