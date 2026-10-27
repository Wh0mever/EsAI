import type { Metadata } from "next";
import AcademyView, { type AcademyState } from "@/components/academy/AcademyView";
import { getAcademyCatalog } from "@/lib/academy/server";
import { breadcrumbJsonLd, jsonLdScript } from "@/lib/seo/jsonLd";
import { OG_IMAGE, OG_IMAGE_ALT, OG_IMAGE_META, SITE_NAME, SITE_URL } from "@/lib/seo/site";
import {
  ACADEMY_DESCRIPTION,
  ACADEMY_PATH,
  ACADEMY_RU,
  ACADEMY_TITLE,
  courseListJsonLd,
  pageFromParam,
  pageHref,
  paginate,
} from "@/lib/academy/shared";

/**
 * /academy — «EsAI Академия» (ТЗ клиента 27.10.2026): каталог курсов со ссылками на
 * сайты авторов. Курсы заводят в панели (/admin-new/academy). Каталог приходит
 * одним запросом, страницы по 9 режутся здесь; ?page= за последней страницей —
 * «мягкий 404»: Next 16 отдаёт тут 200 (корневой layout читает cookies), поэтому
 * noindex и ссылка на первую страницу.
 */

type SearchParams = Promise<Record<string, string | string[] | undefined>>;

export async function generateMetadata({ searchParams }: { searchParams: SearchParams }): Promise<Metadata> {
  const page = pageFromParam((await searchParams).page);
  const result = await getAcademyCatalog();
  const view = result.ok ? paginate(result.catalog.courses, page, result.catalog.pageSize) : null;
  // У каждой страницы списка свой canonical; мусорный ?page= — копия первой.
  const url = `${SITE_URL}${pageHref(page)}`;
  return {
    // Дословно ТЗ, без суффикса сайта и номера страницы.
    title: { absolute: ACADEMY_TITLE },
    description: ACADEMY_DESCRIPTION,
    // У «страницы нет» canonical не ставим: noindex вместе с canonical на другой адрес — противоречивый сигнал.
    alternates: view?.outOfRange ? undefined : { canonical: url },
    openGraph: {
      title: ACADEMY_TITLE,
      description: ACADEMY_DESCRIPTION,
      url,
      siteName: SITE_NAME,
      type: "website",
      images: [OG_IMAGE_META],
    },
    twitter: {
      card: "summary_large_image",
      title: ACADEMY_TITLE,
      description: ACADEMY_DESCRIPTION,
      images: [{ url: OG_IMAGE, alt: OG_IMAGE_ALT }],
    },
    // Сбой API индексацию не трогает: временная ошибка не должна выкинуть страницу из поиска.
    robots: view?.outOfRange ? { index: false, follow: true } : undefined,
  };
}

export default async function AcademyPage({ searchParams }: { searchParams: SearchParams }) {
  const page = pageFromParam((await searchParams).page);
  const result = await getAcademyCatalog();
  const state: AcademyState = result.ok
    ? {
        ok: true,
        view: paginate(result.catalog.courses, page, result.catalog.pageSize),
        suggestUrl: result.catalog.suggestUrl,
      }
    : { ok: false, page };
  const breadcrumb = breadcrumbJsonLd([
    { name: ACADEMY_RU["breadcrumb.home"], url: "/" },
    { name: ACADEMY_RU["breadcrumb.academy"], url: ACADEMY_PATH },
  ]);

  return (
    <>
      {/* Та же разметка, что у SEO-блока layout: тот виден в HTML с сервера, эта — после загрузки страницы. */}
      <script type="application/ld+json" dangerouslySetInnerHTML={{ __html: jsonLdScript(breadcrumb) }} />
      {state.ok && state.view.courses.length > 0 && (
        <script type="application/ld+json" dangerouslySetInnerHTML={{ __html: jsonLdScript(courseListJsonLd(state.view)) }} />
      )}
      <AcademyView state={state} />
    </>
  );
}
