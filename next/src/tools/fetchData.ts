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
import { isJwtExpired, isJwtValid } from "./jwt";

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


// Внутри Telegram (Mini App в iframe web.telegram.org) cookie могут быть
// заблокированы браузером как сторонние. Токены дублируются в sessionStorage,
// и все места, которые читают cookie, читают через эти помощники.
function safeSession(): Storage | null {
    try {
        return typeof window !== "undefined" ? window.sessionStorage : null;
    } catch {
        return null;
    }
}

export function getToken(name: "access" | "refresh"): string | undefined {
    const fromCookie = Cookies.get(name);
    if (fromCookie) return fromCookie;
    return safeSession()?.getItem(`tg_${name}`) || undefined;
}

export function setSessionTokens(access: string, refresh: string): void {
    // SameSite=None — иначе cookie не уйдёт из iframe Telegram в /api/.
    try {
        if (access) Cookies.set("access", access, { expires: 0.5, secure: true, sameSite: "none" });
        if (refresh) Cookies.set("refresh", refresh, { expires: 15, secure: true, sameSite: "none" });
    } catch {}
    const session = safeSession();
    if (session) {
        if (access) session.setItem("tg_access", access);
        if (refresh) session.setItem("tg_refresh", refresh);
    }
}

function clearSessionTokens(): void {
    const session = safeSession();
    session?.removeItem("tg_access");
    session?.removeItem("tg_refresh");
}

/** Полный выход: cookie сессии + копии токенов Mini App в sessionStorage. */
export function clearAuthTokens(): void {
    try {
        Cookies.remove("access");
        Cookies.remove("refresh");
        Cookies.remove("user");
        Cookies.remove("sessionid");
    } catch {}
    try {
        clearSessionTokens();
    } catch {}
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
        const token = getToken("access");
        if (token) headers.Authorization = `Bearer ${token}`;
    }

    // Add CSRF header for unsafe methods when cookie is present
    // Be explicit to satisfy TS unions and future-proof method additions
    const unsafe = m === "POST" || m === "PUT" || m === "PATCH" || m === "DELETE";
    if (unsafe) {
        const csrftoken = Cookies.get("csrftoken");
        if (csrftoken && !headers["X-CSRFToken"]) headers["X-CSRFToken"] = csrftoken;
        if (!headers["X-Requested-With"]) headers["X-Requested-With"] = "XMLHttpRequest";
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

/**
 * ok — новые токены сохранены; invalid — сервер отверг refresh (сессия
 * мертва); error — сеть/5xx, про сессию ничего не известно.
 */
type RefreshOutcome = "ok" | "invalid" | "error";

async function doRefresh(): Promise<RefreshOutcome> {
    const refresh = getToken("refresh");
    if (!refresh) return "invalid";

    try {
        const r = await fetch(`${API}users/token/refresh/`, {
            method: "POST",
            headers: { "Content-Type": "application/json", Accept: "application/json" },
            body: JSON.stringify({ refresh }),
        });
        if (!r.ok) {
            // Пока шёл запрос, токен могли обновить в другом месте (middleware
            // на навигации, другая вкладка) — старый refresh после ротации в
            // чёрном списке, и 401 тут не значит, что сессия умерла.
            const current = getToken("refresh");
            if (current && current !== refresh) {
                return isJwtValid(getToken("access")) ? "ok" : "error";
            }
            return r.status === 401 || r.status === 400 ? "invalid" : "error";
        }

		const data = await r.json().catch(() => ({}));
		const newAccess = data?.access;
		const newRefresh = data?.refresh;

        // Cookie-хардненинг: secure + sameSite lax (lax переживает возврат из OAuth); access короткоживущий.
        if (safeSession()?.getItem("tg_access")) {
            // Сессия Mini App: обновляем там же, где она живёт.
            setSessionTokens(newAccess || "", newRefresh || "");
        } else {
            if (newAccess) Cookies.set("access", newAccess, { expires: 0.5, secure: true, sameSite: "lax" });
            if (newRefresh) Cookies.set("refresh", newRefresh, { expires: 15, secure: true, sameSite: "lax" });
        }
        return newAccess ? "ok" : "error";
    } catch {
        return "error";
    }
}

// Один refresh на всю вкладку. ROTATE_REFRESH_TOKENS + blacklist: раньше
// несколько параллельных 401 отправляли один и тот же refresh, первый
// ротировал его, остальные получали «blacklisted» — и стирали уже свежие
// cookie, выкидывая человека на вход.
let refreshInFlight: Promise<RefreshOutcome> | null = null;

function refreshShared(): Promise<RefreshOutcome> {
    if (!refreshInFlight) {
        refreshInFlight = doRefresh().finally(() => {
            refreshInFlight = null;
        });
    }
    return refreshInFlight;
}

/**
 * Есть ли живой access; если истёк, но есть refresh — тихо обновить.
 * Нужен всем, кто решает «гость или вошёл» по cookie: access живёт 12 ч, и
 * вкладка, открытая со вчера, иначе показывала платящему человеку гостевой
 * режим. Мёртвую сессию (сервер отверг refresh) убираем, но на вход не
 * перебрасываем — гостевой режим на «/» законен.
 */
export async function ensureAccess(): Promise<boolean> {
    if (isJwtValid(getToken("access"))) return true;
    const refresh = getToken("refresh");
    if (!refresh || isJwtExpired(refresh, 0)) return false;
    const outcome = await refreshShared();
    if (outcome === "invalid") clearAuthTokens();
    return outcome === "ok";
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
                const s = (data || "").toString();
                const looksHtml = /<html|<!DOCTYPE/i.test(s);
                if (looksHtml) {
                    error = `HTTP ${res.status}`;
                } else {
                    const line = s.split(/\r?\n/)[0];
                    error = line.length > 200 ? line.slice(0, 200) + "…" : line;
                }
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
    const usedToken = auth ? getToken("access") : undefined;
    const first = await requestOnce<T>(endpoint, method, auth, body, extraHeaders);

    // Treat both 401 and 403 as auth failures for soft redirect
    if (!(auth && (first.status === 401 || first.status === 403))) return first;
    // 403 с живым токеном — это «нельзя», а не «сессия истекла»: лишняя
    // ротация refresh тут только плодит гонки.
    if (first.status === 403 && isJwtValid(usedToken)) return first;

    // Пока запрос летел, токен уже обновили (параллельный запрос/вкладка) —
    // просто повторяем с новым, второй раз refresh не крутим.
    const currentAccess = getToken("access");
    if (currentAccess && currentAccess !== usedToken && isJwtValid(currentAccess)) {
        return requestOnce<T>(endpoint, method, auth, body, extraHeaders);
    }

    // Была ли у пользователя сессия (токены) ДО рефреша? Если гость без токенов —
    // не редиректим на /auth/signin (он вправе пользоваться гостевым режимом на «/»).
    const hadSession = Boolean(getToken("access") || getToken("refresh"));
    const outcome = await refreshShared();
    if (outcome !== "ok") {
        // Гость без сессии: тихо возвращаем 401 вызывающему (покажет пустые данные),
        // НЕ перебрасываем на вход.
        if (!hadSession) {
            return first;
        }
        // Сеть/5xx на refresh — сессия, скорее всего, жива: не выкидываем
        // человека из аккаунта из-за мигнувшего интернета.
        if (outcome === "error") {
            return first;
        }
        // Истёкшая сессия залогиненного пользователя — мягкий выход на /auth/signin.
        clearAuthTokens();
        if (typeof window !== "undefined") {
            const loc = window.location;
            const current = `${loc.pathname}${loc.search}${loc.hash}` || "/";
            const nextParam = encodeURIComponent(current);
            if (!/\/auth\/(signin|callback)/.test(loc.pathname)) {
                // Avoid redirect loops if already on auth pages
                window.location.replace(`/auth/signin?next=${nextParam}`);
            }
        }
        return { ...first, error: first.error || "Unauthorized and refresh failed" };
    }

    const second = await requestOnce<T>(endpoint, method, auth, body, extraHeaders);
    return second;
}
