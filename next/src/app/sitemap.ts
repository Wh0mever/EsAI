import type { MetadataRoute } from "next";
import { SITE_URL } from "@/lib/seo/site";
import { SEO_MODELS } from "@/lib/seo/models";
import { SEO_FUNCTIONS } from "@/lib/seo/functions";
import { getArticles, articleDate } from "@/lib/content";

export default async function sitemap(): Promise<MetadataRoute.Sitemap> {
  const now = new Date();

  const home: MetadataRoute.Sitemap = [
    {
      url: `${SITE_URL}/`,
      lastModified: now,
      changeFrequency: "daily",
      priority: 1,
    },
  ];

  const staticPages: MetadataRoute.Sitemap = [
    { path: "/pricing", priority: 0.7 },
    { path: "/blog", priority: 0.6 },
  ].map(({ path, priority }) => ({
    url: `${SITE_URL}${path}`,
    lastModified: now,
    changeFrequency: "weekly" as const,
    priority,
  }));

  const modelPages: MetadataRoute.Sitemap = SEO_MODELS.map((m) => ({
    url: `${SITE_URL}/model/${m.slug}`,
    lastModified: now,
    changeFrequency: "weekly",
    priority: 0.9,
  }));

  const functionPages: MetadataRoute.Sitemap = SEO_FUNCTIONS.map((f) => ({
    url: `${SITE_URL}/ai/${f.slug}`,
    lastModified: now,
    changeFrequency: "weekly",
    priority: 0.8,
  }));

  // Blog articles (best-effort: getArticles never throws and returns [] on error).
  const articles = await getArticles();
  const articlePages: MetadataRoute.Sitemap = articles
    .filter((a) => a?.slug)
    .map((a) => {
      const d = articleDate(a);
      const lm = d ? new Date(d) : now;
      return {
        url: `${SITE_URL}/blog/${a.slug}`,
        lastModified: Number.isNaN(lm.getTime()) ? now : lm,
        changeFrequency: "monthly" as const,
        priority: 0.6,
      };
    });

  return [...home, ...modelPages, ...functionPages, ...staticPages, ...articlePages];
}
