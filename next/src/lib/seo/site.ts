// Central SEO/site constants for EsAI.
// Used by metadata, JSON-LD, sitemap, robots and the SEO landing pages.

export const SITE_URL = "https://esai.kg";
export const SITE_NAME = "EsAI";
export const SITE_TAGLINE = "Все AI в одном месте";
export const SITE_DESCRIPTION =
  "EsAI — все нейросети в одном месте: ChatGPT, Claude, Gemini, DeepSeek и другие на русском, кыргызском и английском. Мультстудия — мультфильмы с вашим героем, Видеостудия — видео по описанию и фото, бесплатная склейка видео. Без подписок, оплата в сомах.";

// Превью ссылки (Telegram, WhatsApp, соцсети): три направления — Мультстудия, Видеостудия,
// Склейка видео. Новое имя файла, а не замена og-cover.png: мессенджеры кэшируют превью по адресу.
export const OG_IMAGE = "/og-esai.jpg";
export const OG_IMAGE_WIDTH = 1200;
export const OG_IMAGE_HEIGHT = 630;
export const OG_IMAGE_ALT = "EsAI — все нейросети в одном месте: Мультстудия, Видеостудия, Склейка видео";
/** og:image с размерами и подписью (без размеров анализаторы ругаются, а мессенджеры дольше строят превью). */
export const OG_IMAGE_META = { url: OG_IMAGE, width: OG_IMAGE_WIDTH, height: OG_IMAGE_HEIGHT, alt: OG_IMAGE_ALT };
export const LOGO = "/esai-logo.svg";

/** Build an absolute URL from a site-relative path. */
export function absoluteUrl(path = "/"): string {
  if (/^https?:\/\//i.test(path)) return path;
  return `${SITE_URL}${path.startsWith("/") ? "" : "/"}${path}`;
}
