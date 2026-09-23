import type { MetadataRoute } from "next";
import { SITE_URL } from "@/lib/seo/site";

export default function robots(): MetadataRoute.Robots {
  return {
    rules: [
      {
        userAgent: "*",
        allow: "/",
        // Служебное и личное: админка, кабинет, Mini App и ссылки на чужие ролики
        // поисковику не нужны (/v/ сами по себе noindex, но зачем их обходить).
        disallow: ["/api/", "/admin/", "/admin-new", "/auth/", "/dashboard/", "/profile",
                   "/transfer", "/tg/"],
      },
    ],
    sitemap: `${SITE_URL}/sitemap.xml`,
    host: "esai.kg",
  };
}
