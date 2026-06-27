import type { MetadataRoute } from "next";
import { SITE_URL } from "@/lib/seo/site";
import { SEO_MODELS } from "@/lib/seo/models";
import { SEO_FUNCTIONS } from "@/lib/seo/functions";

export default function sitemap(): MetadataRoute.Sitemap {
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

  return [...home, ...modelPages, ...functionPages, ...staticPages];
}
