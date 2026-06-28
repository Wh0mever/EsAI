// Server-side content fetchers for the EsAI blog and dynamic site settings.
//
// These run inside React Server Components (blog list/detail) and during
// `generateMetadata`, so they must NOT depend on the browser (`window`,
// `js-cookie`). The API base is resolved from NEXT_PUBLIC_SITE_URL and falls
// back to the canonical SITE_URL. Every helper is best-effort: on any error or
// non-OK response it returns an empty/`null` result so the page can render a
// graceful empty state instead of crashing the build.

import { SITE_URL } from "@/lib/seo/site";

/** Absolute origin used to reach the Django API from the server. */
function apiOrigin(): string {
  const env = (process.env.NEXT_PUBLIC_SITE_URL || "").replace(/\/$/, "");
  return env || SITE_URL;
}

/** Build an absolute API URL: `<origin>/api/<path>`. */
function apiUrl(path: string): string {
  const clean = path.replace(/^\/+/, "");
  return `${apiOrigin()}/api/${clean}`;
}

/** A single blog article as returned by `/api/content/articles/`. */
export type Article = {
  id?: number | string;
  slug: string;
  title?: string;
  excerpt?: string;
  /** Markdown (preferred) or HTML body of the article. */
  content?: string;
  cover?: string;
  image?: string;
  author?: string;
  date?: string;
  published_at?: string;
  created_at?: string;
  updated_at?: string;
  // SEO meta (optional; falls back to title/excerpt).
  meta_title?: string;
  meta_description?: string;
  tags?: string[];
  [key: string]: any;
};

/** Dynamic site settings (footer/contacts) from `/api/content/site-settings/`. */
export type SiteSettings = {
  email?: string;
  phone?: string;
  address?: string;
  telegram?: string;
  instagram?: string;
  facebook?: string;
  twitter?: string;
  [key: string]: any;
};

const REVALIDATE = 300; // seconds — ISR window for content endpoints

async function getJson<T>(url: string): Promise<T | null> {
  try {
    const res = await fetch(url, {
      headers: { Accept: "application/json" },
      next: { revalidate: REVALIDATE },
    });
    if (!res.ok) return null;
    const ct = res.headers.get("content-type") || "";
    if (!ct.includes("application/json")) return null;
    return (await res.json()) as T;
  } catch {
    return null;
  }
}

/**
 * Normalize a list response that may be a bare array or a paginated
 * `{ results: [...] }` / `{ articles: [...] }` envelope.
 */
function toList<T>(data: any): T[] {
  if (Array.isArray(data)) return data as T[];
  if (Array.isArray(data?.results)) return data.results as T[];
  if (Array.isArray(data?.articles)) return data.articles as T[];
  if (Array.isArray(data?.data)) return data.data as T[];
  return [];
}

/** Fetch the full list of published articles (best-effort, never throws). */
export async function getArticles(): Promise<Article[]> {
  const data = await getJson<any>(apiUrl("content/articles/"));
  return toList<Article>(data);
}

/** Fetch a single article by slug (best-effort, returns null when missing). */
export async function getArticle(slug: string): Promise<Article | null> {
  if (!slug) return null;
  const data = await getJson<any>(apiUrl(`content/articles/${encodeURIComponent(slug)}/`));
  if (!data) return null;
  // Some backends wrap detail responses in `{ data: {...} }`.
  const article = (data?.data ?? data) as Article;
  return article && (article.slug || article.title) ? article : null;
}

/** Fetch dynamic site settings (best-effort, returns null on any failure). */
export async function getSiteSettings(): Promise<SiteSettings | null> {
  const data = await getJson<any>(apiUrl("content/site-settings/"));
  if (!data) return null;
  return (data?.data ?? data) as SiteSettings;
}

/* ---------- small content helpers shared by the blog pages ---------- */

/** Best available cover image URL for an article (absolute or site-relative). */
export function articleCover(a: Article): string {
  return (a.cover || a.image || "").toString();
}

/** Best available publish date (ISO string) for an article. */
export function articleDate(a: Article): string {
  return (a.date || a.published_at || a.created_at || "").toString();
}

/** Best available SEO title / description with sensible fallbacks. */
export function articleMeta(a: Article): { title: string; description: string } {
  return {
    title: (a.meta_title || a.title || "").toString(),
    description: (a.meta_description || a.excerpt || "").toString(),
  };
}

/* ---------- table of contents (TOC) from Markdown headings ---------- */

/** Slugify heading text into an anchor id (Cyrillic-aware). */
export function slugify(text: string): string {
  return text
    .toString()
    .trim()
    .toLowerCase()
    .replace(/[`*_~>#]/g, "") // strip common markdown marks
    .replace(/\s+/g, "-")
    .replace(/[^\p{L}\p{N}-]+/gu, "") // keep letters/numbers/hyphen (any script)
    .replace(/-{2,}/g, "-")
    .replace(/^-+|-+$/g, "");
}

export type TocItem = { id: string; text: string; level: number };

/**
 * Extract an ordered list of H2/H3 headings from Markdown content for the
 * article TOC. Ignores headings inside fenced code blocks.
 */
export function extractToc(markdown: string): TocItem[] {
  if (!markdown) return [];
  const lines = markdown.split(/\r?\n/);
  const items: TocItem[] = [];
  const seen = new Map<string, number>();
  let inFence = false;
  for (const line of lines) {
    if (/^\s*(```|~~~)/.test(line)) {
      inFence = !inFence;
      continue;
    }
    if (inFence) continue;
    const m = /^(#{2,3})\s+(.+?)\s*#*\s*$/.exec(line);
    if (!m) continue;
    const level = m[1].length;
    const text = m[2].replace(/[*_`~]/g, "").trim();
    if (!text) continue;
    let id = slugify(text) || "section";
    const n = seen.get(id) || 0;
    seen.set(id, n + 1);
    if (n > 0) id = `${id}-${n}`;
    items.push({ id, text, level });
  }
  return items;
}
