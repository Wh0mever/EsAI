import ru from "@/locales/ru/academy.json";
import en from "@/locales/en/academy.json";
import kg from "@/locales/kg/academy.json";
import { getAcademyCatalog } from "@/lib/academy/server";
import { breadcrumbJsonLd, jsonLdScript } from "@/lib/seo/jsonLd";
import {
  ACADEMY_PATH,
  ACADEMY_RU,
  EXTERNAL_REL,
  academyText,
  courseListJsonLd,
  fill,
  pageFromSearch,
  pageHref,
  paginate,
  type AcademyKey,
} from "@/lib/academy/shared";
import SuggestText from "./SuggestText";

// Что видит /academy в HTML с сервера, пока в браузере грузятся переводы.
//
// I18nProvider рисует детей только после загрузки переводов, поэтому без этого
// блока HTML страницы пустой: краулеры без JS, превью ссылок и AI-боты не нашли
// бы ни заголовка, ни курсов. Приём тот же, что у главной (HomeSeoFallback):
// блок скрыт (sr-only) и исчезает, когда появляется настоящая страница со своим
// H1 — заголовок H1 всегда один. Номер страницы корневой layout берёт из
// заголовка x-esai-search (searchParams у layout нет); каталог — тот же запрос,
// что у страницы, поэтому второго обращения к core нет.

export default async function AcademySeoFallback({ lang, search }: { lang: string; search: string }) {
  const dict = lang === "en" ? en : lang === "kg" ? kg : ru;
  const tx = (key: AcademyKey) => academyText(dict, key);
  const page = pageFromSearch(search);
  const result = await getAcademyCatalog();
  const view = result.ok ? paginate(result.catalog.courses, page, result.catalog.pageSize) : null;
  const suggest = result.ok ? result.catalog.suggestUrl : null;
  // Разметка — по-русски, как метаданные и JSON-LD самой страницы (app/academy/page.tsx).
  const breadcrumb = breadcrumbJsonLd([
    { name: ACADEMY_RU["breadcrumb.home"], url: "/" },
    { name: ACADEMY_RU["breadcrumb.academy"], url: ACADEMY_PATH },
  ]);

  return (
    <div className="sr-only">
      <h1>{tx("hero.title")}</h1>
      <p>{tx("hero.subtitle")}</p>

      <h2>{tx("trust.title")}</h2>
      <p>{tx("trust.text")}</p>
      <ul>
        {(["authors", "practice", "direct"] as const).map((key) => (
          <li key={key}>
            <h3>{tx(`trust.${key}.title`)}</h3>
            <p>{tx(`trust.${key}.text`)}</p>
          </li>
        ))}
      </ul>

      <h2>{tx("catalog.heading")}</h2>
      {!view ? (
        <p>{tx("error.title")}</p>
      ) : view.total === 0 ? (
        <p>
          {tx("empty.title")}. {tx("empty.text")}
        </p>
      ) : view.outOfRange ? (
        <p>
          {tx("missing.title")} <a href={pageHref(1)}>{tx("missing.link")}</a>
        </p>
      ) : (
        <ul>
          {view.courses.map((course) => (
            <li key={course.id}>
              <h3>{course.title}</h3>
              {course.teacher && (
                <p>
                  {tx("card.teacher")} {course.teacher}
                </p>
              )}
              {course.description && <p>{course.description}</p>}
              <a href={course.url} rel={EXTERNAL_REL}>
                {tx("card.cta")}
              </a>
            </li>
          ))}
        </ul>
      )}

      {/* Все страницы каталога ссылками: краулер без JS доберётся до каждой. */}
      {view && view.pages > 1 && (
        <nav aria-label={tx("pager.label")}>
          <ul>
            {Array.from({ length: view.pages }, (_, i) => i + 1).map((n) => (
              <li key={n}>
                <a href={pageHref(n)} aria-current={n === view.page ? "page" : undefined}>
                  {fill(tx("pager.page"), { page: n })}
                </a>
              </li>
            ))}
          </ul>
        </nav>
      )}

      <h2>{tx("suggest.title")}</h2>
      <p>{tx("suggest.text")}</p>
      {suggest?.kind === "url" && (
        <a href={suggest.href} rel={EXTERNAL_REL}>
          {tx("suggest.cta")}
        </a>
      )}
      {suggest?.kind === "email" && (
        <p>
          <a href={suggest.href}>{tx("suggest.cta")}</a> {suggest.text}
        </p>
      )}
      {suggest?.kind === "text" && <SuggestText text={suggest.text} newTab={tx("card.new_tab")} />}

      <script type="application/ld+json" dangerouslySetInnerHTML={{ __html: jsonLdScript(breadcrumb) }} />
      {view && view.courses.length > 0 && (
        <script type="application/ld+json" dangerouslySetInnerHTML={{ __html: jsonLdScript(courseListJsonLd(view)) }} />
      )}
    </div>
  );
}
