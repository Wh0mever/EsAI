import type { MetadataRoute } from "next";
import { SITE_URL } from "@/lib/seo/site";

export default function robots(): MetadataRoute.Robots {
  return {
    rules: [
      {
        userAgent: "*",
        // /api/creators/program/ — условия программы: страница /creators рисует
        // их из этого ответа, и без него поисковик увидел бы только «нет
        // соединения». Более длинное правило Allow сильнее Disallow: /api/.
        allow: ["/", "/api/creators/program/"],
        // Служебное и личное: админка, кабинет, Mini App и ссылки на чужие ролики
        // поисковику не нужны (/v/ сами по себе noindex, но зачем их обходить).
        // /video-studio/ со слэшем — личные проекты видеостудии (у них ещё и
        // noindex); сама /video-studio без слэша остаётся открытой.
        // /creators/dashboard — кабинет креатора; публичная /creators открыта.
        disallow: ["/api/", "/admin/", "/admin-new", "/auth/", "/dashboard/", "/profile",
                   "/transfer", "/tg/", "/video-studio/", "/creators/dashboard"],
      },
    ],
    sitemap: `${SITE_URL}/sitemap.xml`,
    host: "esai.kg",
  };
}
