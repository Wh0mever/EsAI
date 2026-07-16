// streamChat.ts — SSE (text/event-stream) client for the chat endpoint.
//
// The backend contract (agreed with core): POST /api/ai/chat/ with `stream:true`
// returns `text/event-stream` whose lines look like:
//   data: {"delta":"<chunk>"}            -> append to the live assistant message
//   data: {"sources":[{title,url}]}      -> attach web-search sources
//   data: {"done":true,"message":{...},"tokens_charged","balance_tokens","free_used","free_limit"}
//   data: {"error":"...","done":true}    -> stream-level error
//
// For 402/401 the backend replies with a normal JSON body (NOT event-stream)
// BEFORE any streaming starts — the caller detects that via `isStream` and the
// parsed `json` fallback.

import Cookies from "js-cookie";
import { API } from "./fetchData";

export type StreamEvent =
  | { type: "delta"; delta: string }
  | { type: "reasoning"; delta: string }
  | { type: "sources"; sources: Array<{ title?: string; url: string }> }
  /** backend готовит КАРТИНКУ (image-gen) — фронт рисует серый плейсхолдер */
  | { type: "image_pending" }
  /** backend готовит ВИДЕО (video-gen) — фронт рисует видео-плейсхолдер */
  | { type: "video_pending"; duration?: number }
  /** keepalive-кадр во время генерации видео (~каждые 5с) — UI не меняем */
  | { type: "video_progress" }
  | { type: "done"; payload: any }
  | { type: "error"; error: string; error_code?: string; payload?: any };

export type StreamResult = {
  /** true when the response is a real SSE stream we consumed */
  isStream: boolean;
  /** HTTP status */
  status: number;
  ok: boolean;
  /** parsed JSON body when the response was NOT a stream (fallback path) */
  json: any | null;
  headers: Headers;
};

type StreamOpts = {
  authed: boolean;
  extraHeaders?: Record<string, string>;
  signal?: AbortSignal;
  onEvent: (ev: StreamEvent) => void;
};

function buildHeaders(authed: boolean, extra?: Record<string, string>): Record<string, string> {
  const headers: Record<string, string> = {
    Accept: "text/event-stream, application/json",
    "Content-Type": "application/json",
    "X-Requested-With": "XMLHttpRequest",
    ...(extra || {}),
  };
  if (authed) {
    const token = Cookies.get("access");
    if (token) headers.Authorization = `Bearer ${token}`;
  }
  const csrftoken = Cookies.get("csrftoken");
  if (csrftoken && !headers["X-CSRFToken"]) headers["X-CSRFToken"] = csrftoken;
  return headers;
}

/** Parse a single SSE record's `data:` payload(s) and dispatch typed events. */
function dispatchRecord(record: string, onEvent: (ev: StreamEvent) => void) {
  // A record may contain comment lines (":...") and multiple `data:` lines.
  const dataLines = record
    .split(/\r?\n/)
    .filter((l) => l.startsWith("data:"))
    .map((l) => l.slice(5).replace(/^ /, ""));
  if (dataLines.length === 0) return;
  const data = dataLines.join("\n");
  if (data === "[DONE]") {
    onEvent({ type: "done", payload: { done: true } });
    return;
  }
  let obj: any;
  try {
    obj = JSON.parse(data);
  } catch {
    return; // ignore malformed chunk
  }
  if (typeof obj?.delta === "string") onEvent({ type: "delta", delta: obj.delta });
  if (typeof obj?.reasoning === "string") onEvent({ type: "reasoning", delta: obj.reasoning });
  if (Array.isArray(obj?.sources)) onEvent({ type: "sources", sources: obj.sources });
  if (obj?.image_pending) onEvent({ type: "image_pending" });
  if (obj?.video_pending)
    onEvent({ type: "video_pending", duration: typeof obj.duration === "number" ? obj.duration : undefined });
  if (obj?.video_progress) onEvent({ type: "video_progress" });
  // Stream-level error frame: data: {"error":"...","error_code":"...","done":true,...}
  // We surface error_code (and the whole frame) so the caller can route to the
  // right paywall/limit modal — same contract as the JSON-fallback path.
  if (obj?.error || obj?.error_code) {
    onEvent({
      type: "error",
      error: String(obj.error || obj.error_code || ""),
      error_code: obj.error_code ? String(obj.error_code) : undefined,
      payload: obj,
    });
    return;
  }
  if (obj?.done) onEvent({ type: "done", payload: obj });
}

/**
 * POSTs the chat body and, if the response is an event-stream, reads it to the
 * end while emitting typed events. Returns metadata so the caller can take the
 * JSON fallback path (402/401/non-stream) when needed.
 */
export async function streamChat(
  body: Record<string, any>,
  { authed, extraHeaders, signal, onEvent }: StreamOpts
): Promise<StreamResult> {
  const res = await fetch(`${API}ai/chat/`, {
    method: "POST",
    headers: buildHeaders(authed, extraHeaders),
    body: JSON.stringify(body),
    signal,
  });

  const ct = res.headers.get("content-type") || "";
  const isStream = ct.includes("text/event-stream") && !!res.body;

  if (!isStream) {
    // Fallback: parse JSON (covers 402/401-before-stream and non-stream backends).
    let json: any = null;
    try {
      json = ct.includes("application/json") ? await res.json() : null;
    } catch {
      json = null;
    }
    return { isStream: false, status: res.status, ok: res.ok, json, headers: res.headers };
  }

  const reader = res.body!.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  try {
    while (true) {
      const { value, done } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      // SSE records are separated by a blank line.
      let sep: number;
      // Normalize: split on \n\n (handle \r\n\r\n too).
      while ((sep = buffer.search(/\r?\n\r?\n/)) !== -1) {
        const matchLen = buffer.slice(sep).match(/^\r?\n\r?\n/)![0].length;
        const record = buffer.slice(0, sep);
        buffer = buffer.slice(sep + matchLen);
        if (record.trim()) dispatchRecord(record, onEvent);
      }
    }
    // Flush any trailing record without a final blank line.
    buffer += decoder.decode();
    if (buffer.trim()) dispatchRecord(buffer, onEvent);
  } finally {
    try {
      reader.releaseLock();
    } catch {}
  }

  return { isStream: true, status: res.status, ok: res.ok, json: null, headers: res.headers };
}
