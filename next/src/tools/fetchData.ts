// api/fetchData.ts

// Domain-aware bases:
// - API remains a strict same-origin prefix routed by Nginx to Django
// - BACKEND resolves to the current origin, ensuring media/static links work on all domains
const isBrowser = typeof window !== "undefined";
const ORIGIN = isBrowser
  ? window.location.origin
  : (process.env.NEXT_PUBLIC_SITE_URL || "").replace(/\/$/, "");

export const API = "/api/"; // keep relative; Nginx maps /api/* -> core
export const BACKEND = ORIGIN || ""; // used to prefix absolute media URLs if needed

import Cookies from "js-cookie";

export type ApiResponse<T = any> = {
	ok: boolean;
	status: number;
	url: string;
	data: T | null; // Parsed body (JSON | text | null)
	error?: string; // Human-readable error if any
	headers: Headers;
};

// Accept both UPPER and lower case; normalize internally
type HttpMethod = "GET" | "POST" | "PUT" | "PATCH" | "DELETE";
type HttpMethodAny = HttpMethod | Lowercase<HttpMethod>;

type BodyLike = Record<string, any> | FormData | Blob | ArrayBuffer | string | null | undefined;

type RequestInitLite = {
	method?: HttpMethodAny;
	auth?: boolean;
	headers?: Record<string, string>;
	body?: BodyLike;
};

const isNil = (v: unknown): v is null | undefined => v === null || v === undefined;

async function parseResponse(res: Response): Promise<any | null> {
	const ct = res.headers.get("content-type") || "";
	try {
		if (ct.includes("application/json")) return await res.json();
		const text = await res.text();
		return text.length ? text : null;
	} catch {
		return null;
	}
}

// Normalize method to uppercase and build RequestInit
function buildInit(method: HttpMethodAny, auth: boolean, body?: BodyLike, extra?: Record<string, string>): RequestInit {
	const m = (method || "GET").toString().toUpperCase() as HttpMethod;

	const headers: Record<string, string> = {
		Accept: "application/json",
		...(extra || {}),
	};

	const init: RequestInit = { method: m, headers };

	if (auth) {
		const token = Cookies.get("access");
		if (token) headers.Authorization = `Bearer ${token}`;
	}

	// Treat null/undefined as no body
	if (!isNil(body)) {
		if (body instanceof FormData || body instanceof Blob || body instanceof ArrayBuffer) {
			init.body = body as any; // Let fetch set boundary/content-type
		} else if (typeof body === "string") {
			headers["Content-Type"] = headers["Content-Type"] || "application/json";
			init.body = body;
		} else {
			// JSON object
			headers["Content-Type"] = headers["Content-Type"] || "application/json";
			init.body = JSON.stringify(body);
		}
	}

	return init;
}

async function refreshAuth(): Promise<boolean> {
	const refresh = Cookies.get("refresh");
	if (!refresh) return false;

	try {
		const r = await fetch(`${API}users/token/refresh/`, {
			method: "POST",
			headers: { "Content-Type": "application/json", Accept: "application/json" },
			body: JSON.stringify({ refresh }),
		});
		if (!r.ok) return false;

		const data = await r.json().catch(() => ({}));
		const newAccess = data?.access;
		const newRefresh = data?.refresh;

		if (newAccess) Cookies.set("access", newAccess, { expires: 7 });
		if (newRefresh) Cookies.set("refresh", newRefresh, { expires: 15 });
		return Boolean(newAccess);
	} catch {
		return false;
	}
}

async function requestOnce<T = any>(
	endpoint: string,
	method: HttpMethodAny,
	auth: boolean,
	body?: BodyLike,
	extraHeaders?: Record<string, string>
): Promise<ApiResponse<T>> {
	const url = `${API}${endpoint}`;
	const init = buildInit(method, auth, body, extraHeaders);

	try {
		const res = await fetch(url, init);
		const data = (await parseResponse(res)) as T | null;

		let error: string | undefined;
		if (!res.ok) {
			if (data && typeof data === "object" && ("detail" in (data as any) || "message" in (data as any))) {
				error = (data as any).detail || (data as any).message;
			} else if (typeof data === "string") {
				error = data;
			} else {
				error = `HTTP ${res.status}`;
			}
		}

		return { ok: res.ok, status: res.status, url, data, error, headers: res.headers };
	} catch (e: any) {
		return {
			ok: false,
			status: 0,
			url,
			data: null,
			error: e?.message || "Network error",
			headers: new Headers(),
		};
	}
}

/** Public API: always returns body/meta, never throws */
export async function fetchData<T = any>(
	endpoint: string,
	method: HttpMethodAny = "GET",
	body?: BodyLike,
	auth: boolean = false,
	extraHeaders?: Record<string, string>
): Promise<ApiResponse<T>> {
	const first = await requestOnce<T>(endpoint, method, auth, body, extraHeaders);

	if (!(auth && first.status === 401)) return first;

	const refreshed = await refreshAuth();
	if (!refreshed) {
		return { ...first, error: first.error || "Unauthorized and refresh failed" };
	}

	const second = await requestOnce<T>(endpoint, method, auth, body, extraHeaders);
	return second;
}
