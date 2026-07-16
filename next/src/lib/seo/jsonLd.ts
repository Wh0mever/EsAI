// JSON-LD builders for EsAI SEO pages.
// Returned objects are stringified into <script type="application/ld+json">.

import { SITE_URL, SITE_NAME, SITE_DESCRIPTION, absoluteUrl, LOGO, OG_IMAGE } from "./site";

/** Organization + WebSite + SoftwareApplication graph for the homepage. */
export function homeJsonLd() {
  return {
    "@context": "https://schema.org",
    "@graph": [
      {
        "@type": "Organization",
        "@id": `${SITE_URL}/#organization`,
        name: SITE_NAME,
        url: SITE_URL,
        logo: absoluteUrl(LOGO),
        description: SITE_DESCRIPTION,
      },
      {
        "@type": "WebSite",
        "@id": `${SITE_URL}/#website`,
        name: SITE_NAME,
        url: SITE_URL,
        description: SITE_DESCRIPTION,
        inLanguage: ["ru", "ky", "en"],
        publisher: { "@id": `${SITE_URL}/#organization` },
      },
      {
        "@type": "SoftwareApplication",
        name: SITE_NAME,
        applicationCategory: "BusinessApplication",
        operatingSystem: "Web",
        url: SITE_URL,
        description: SITE_DESCRIPTION,
        offers: {
          "@type": "Offer",
          price: "0",
          priceCurrency: "KGS",
        },
      },
    ],
  };
}

/**
 * Product + AggregateOffer для платных пакетов кредитов на /pricing.
 * Цены/кредиты/названия ЗЕРКАЛЯТ сид (миграция plans/0013) и публичный
 * GET /api/plans/packages/ → держать в синхроне при изменении тарифов, чтобы
 * structured data совпадал с видимой страницей (требование Google).
 */
export function tokenPackagesJsonLd() {
  const packages = [
    { name: "Старт", price: "190", credits: "150" },
    { name: "Про", price: "490", credits: "500" },
    { name: "Премиум", price: "990", credits: "1300" },
    { name: "Максимум", price: "1990", credits: "2800" },
  ];
  return {
    "@context": "https://schema.org",
    "@type": "Product",
    name: "EsAI — пакеты кредитов",
    description:
      "Пакеты кредитов EsAI для доступа ко всем нейросетям (ChatGPT, Claude, Gemini, DeepSeek, Grok, Perplexity). Оплата в сомах, без подписок.",
    image: absoluteUrl(OG_IMAGE),
    brand: { "@type": "Brand", name: SITE_NAME },
    url: `${SITE_URL}/pricing`,
    offers: {
      "@type": "AggregateOffer",
      priceCurrency: "KGS",
      lowPrice: "190",
      highPrice: "1990",
      offerCount: packages.length,
      offers: packages.map((p) => ({
        "@type": "Offer",
        name: `${p.name} — ${p.credits} кредитов`,
        price: p.price,
        priceCurrency: "KGS",
        availability: "https://schema.org/InStock",
        url: `${SITE_URL}/pricing`,
      })),
    },
  };
}

/** FAQPage from a list of {q,a}. */
export function faqJsonLd(items: { q: string; a: string }[]) {
  return {
    "@context": "https://schema.org",
    "@type": "FAQPage",
    mainEntity: items.map((it) => ({
      "@type": "Question",
      name: it.q,
      acceptedAnswer: { "@type": "Answer", text: it.a },
    })),
  };
}

/** BreadcrumbList from ordered {name, url(relative or absolute)}. */
export function breadcrumbJsonLd(items: { name: string; url: string }[]) {
  return {
    "@context": "https://schema.org",
    "@type": "BreadcrumbList",
    itemListElement: items.map((it, i) => ({
      "@type": "ListItem",
      position: i + 1,
      name: it.name,
      item: absoluteUrl(it.url),
    })),
  };
}

/** BlogPosting/Article schema for a single blog article. */
export function articleJsonLd(input: {
  title: string;
  description?: string;
  url: string;
  image?: string;
  author?: string;
  datePublished?: string;
  dateModified?: string;
}) {
  const node: Record<string, unknown> = {
    "@context": "https://schema.org",
    "@type": "BlogPosting",
    headline: input.title,
    mainEntityOfPage: { "@type": "WebPage", "@id": absoluteUrl(input.url) },
    url: absoluteUrl(input.url),
    publisher: {
      "@type": "Organization",
      name: SITE_NAME,
      logo: { "@type": "ImageObject", url: absoluteUrl(LOGO) },
    },
  };
  if (input.description) node.description = input.description;
  if (input.image) node.image = absoluteUrl(input.image);
  if (input.author) node.author = { "@type": "Person", name: input.author };
  if (input.datePublished) node.datePublished = input.datePublished;
  if (input.dateModified || input.datePublished)
    node.dateModified = input.dateModified || input.datePublished;
  return node;
}

/** Reusable inline JSON-LD <script> serializer. */
export function jsonLdScript(data: unknown): string {
  return JSON.stringify(data).replace(/</g, "\\u003c");
}
