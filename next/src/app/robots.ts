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
        // /video-studio/ со слэшем — личные проекты видеостудии (у них ещё и
        // noindex); сама /video-studio без слэша остаётся открытой.
        disallow: ["/api/", "/admin/", "/admin-new", "/auth/", "/dashboard/", "/profile",
                   "/transfer", "/tg/", "/video-studio/"],
      },
    ],
    sitemap: `${SITE_URL}/sitemap.xml`,
    host: "esai.kg",
  };
}
