/**
 * Каталог Академии для серверного рендера (страница /academy, её метаданные и
 * SEO-блок корневого layout). Только для сервера: в клиентский код не импортировать.
 */
import { cache } from "react";
import { SITE_URL } from "@/lib/seo/site";
import { parseCatalog, type AcademyCatalog } from "./shared";

export type CatalogResult = { ok: true; catalog: AcademyCatalog } | { ok: false };

/** Правка в панели видна на сайте не позже чем через минуту (то же обещает панель). */
const REVALIDATE_S = 60;
/** Ответ core ждём недолго: зависший бэкенд не должен держать страницу. */
const TIMEOUT_MS = 6000;

/**
 * Куда идти за каталогом. Внутри docker-сети — напрямую в core (INTERNAL_API_ORIGIN,
 * на проде http://core:8000), мимо Cloudflare: снаружи весь SSR пришёл бы с одного IP
 * сервера. Без него — тем же путём, что middleware.ts (apiOrigin): публичный адрес сайта.
 */
function apiTarget(): { origin: string; internal: boolean } {
  const internal = (process.env.INTERNAL_API_ORIGIN || "").replace(/\/$/, "");
  if (internal) return { origin: internal, internal: true };
  const site = (process.env.NEXT_PUBLIC_SITE_URL || process.env.SITE_URL || "").replace(/\/$/, "");
  return { origin: site || SITE_URL, internal: false };
}

/**
 * Все опубликованные курсы одним запросом: один адрес — один ключ кэша fetch,
 * сколько бы разных ?page= ни открывали. Не бросает: сбой — { ok: false }, и
 * страница показывает «не удалось загрузить», а не пустой каталог. cache() —
 * один запрос на рендер, хотя каталог нужен метаданным, странице и SEO-блоку.
 */
export const getAcademyCatalog = cache(async (): Promise<CatalogResult> => {
  const { origin, internal } = apiTarget();
  const headers: Record<string, string> = { Accept: "application/json" };
  if (internal) {
    // Прямой вызов core по http: без X-Forwarded-Proto включённый DJANGO_SECURE_SSL_REDIRECT
    // ответил бы 301 на https://core:8000 (как в middleware.ts). Host — боевой домен, как
    // у запросов через nginx. X-Forwarded-For посетителя не передаём: заголовки входят в
    // ключ кэша fetch, и кэш разошёлся бы по посетителям.
    headers["X-Forwarded-Proto"] = "https";
    headers.Host = new URL(SITE_URL).host;
  }
  try {
    const res = await fetch(`${origin}/api/academy/courses/`, {
      headers,
      redirect: "manual",
      signal: AbortSignal.timeout(TIMEOUT_MS),
      next: { revalidate: REVALIDATE_S, tags: ["academy"] },
    });
    if (res.status !== 200) return { ok: false };
    if (!(res.headers.get("content-type") || "").includes("application/json")) return { ok: false };
    const catalog = parseCatalog(await res.json());
    return catalog ? { ok: true, catalog } : { ok: false };
  } catch {
    return { ok: false };
  }
});
