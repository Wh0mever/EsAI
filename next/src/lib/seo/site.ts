// Central SEO/site constants for EsAI.
// Used by metadata, JSON-LD, sitemap, robots and the SEO landing pages.

export const SITE_URL = "https://esai.kg";
export const SITE_NAME = "EsAI";
export const SITE_TAGLINE = "Все AI в одном месте";
export const SITE_DESCRIPTION =
  "EsAI — агрегатор нейросетей в одном чате: ChatGPT, DeepSeek, Gemini, Claude, Grok, Mistral, Perplexity. На русском, кыргызском и английском. Оплата в сомах.";

export const OG_IMAGE = "/og-cover.png";
export const LOGO = "/esai-logo.svg";

/** Build an absolute URL from a site-relative path. */
export function absoluteUrl(path = "/"): string {
  if (/^https?:\/\//i.test(path)) return path;
  return `${SITE_URL}${path.startsWith("/") ? "" : "/"}${path}`;
}
