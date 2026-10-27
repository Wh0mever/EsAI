"use client";

import Link from "next/link";
import { useRef, type ComponentType, type ReactNode } from "react";
import { useTranslation } from "react-i18next";
import { FiAlertCircle, FiBookOpen, FiExternalLink, FiMail, FiPlayCircle, FiSend, FiUserCheck } from "react-icons/fi";
import CourseCard, { type CourseCardLabels } from "./CourseCard";
import AcademyPagination, { type PagerLabels } from "./AcademyPagination";
import SuggestText from "./SuggestText";
import {
  ACADEMY_RU,
  EXTERNAL_REL,
  pageHref,
  type AcademyKey,
  type AcademyPageView,
  type AcademySuggest,
} from "@/lib/academy/shared";

/**
 * Что страница получила с сервера: каталог, нарезанный на текущую страницу, или сбой API.
 * suggestUrl — блок «Предложить курс» (имя осталось от времён одной ссылки, см. AcademyCatalog).
 */
export type AcademyState =
  | { ok: true; view: AcademyPageView; suggestUrl: AcademySuggest | null }
  | { ok: false; page: number };

const CONTAINER = "mx-auto w-full max-w-[1200px] px-4 sm:px-6";
const CARD = "rounded-3xl border border-border bg-surface";

const TRUST: { key: "authors" | "practice" | "direct"; Icon: ComponentType<{ className?: string }> }[] = [
  { key: "authors", Icon: FiUserCheck },
  { key: "practice", Icon: FiPlayCircle },
  { key: "direct", Icon: FiExternalLink },
];

/**
 * Страница «EsAI Академия» (ТЗ клиента 27.10.2026): заголовок, блок доверия,
 * каталог курсов со ссылками на сайты авторов, страницы по 9 и приглашение
 * для авторов. Данные приходят с сервера (app/academy/page.tsx) — сам компонент
 * в сеть не ходит.
 */
export default function AcademyView({ state }: { state: AcademyState }) {
  const { t } = useTranslation("academy", { useSuspense: false });
  const tx = (key: AcademyKey, vars?: Record<string, string | number>) =>
    t(key, { defaultValue: ACADEMY_RU[key], ...vars });

  const page = state.ok ? state.view.page : state.page;
  const catalogRef = useRef<HTMLElement>(null);

  // Листание: к началу каталога, а не к шапке страницы — блоки над ним на всех страницах одни.
  const toCatalog = () => {
    const reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    catalogRef.current?.scrollIntoView({ behavior: reduce ? "auto" : "smooth", block: "start" });
  };

  const cardLabels: CourseCardLabels = { cta: tx("card.cta"), newTab: tx("card.new_tab"), teacher: tx("card.teacher") };
  const pagerLabels: PagerLabels = {
    nav: tx("pager.label"),
    prev: tx("pager.prev"),
    next: tx("pager.next"),
    page: (n) => tx("pager.page", { page: n }),
  };
  const suggest = state.ok ? state.suggestUrl : null;

  return (
    <main className="pb-16 sm:pb-24">
      <section className="relative isolate px-4 pb-10 pt-28 sm:pb-14 sm:pt-36">
        {/* Мягкое свечение фирменного цвета, как у первого экрана Creators: одинаково в обеих темах. */}
        <div
          aria-hidden
          className="pointer-events-none absolute inset-x-0 top-0 -z-10 h-[26rem] bg-[radial-gradient(60%_60%_at_50%_0%,var(--accent-soft),transparent_70%)]"
        />
        <div className="mx-auto flex max-w-3xl flex-col items-center text-center">
          <h1 className="text-balance break-words text-3xl font-bold leading-tight text-foreground sm:text-5xl">
            {tx("hero.title")}
          </h1>
          <p className="mt-4 max-w-2xl text-balance text-base text-muted sm:text-lg">{tx("hero.subtitle")}</p>
        </div>
      </section>

      <div className={`${CONTAINER} flex flex-col gap-10 sm:gap-14`}>
        <section aria-labelledby="academy-trust" className={`${CARD} p-6 sm:p-8`}>
          <h2 id="academy-trust" className="text-balance text-xl font-bold leading-snug text-foreground sm:text-2xl">
            {tx("trust.title")}
          </h2>
          <p className="mt-3 max-w-3xl text-muted">{tx("trust.text")}</p>
          <ul className="mt-6 grid gap-4 sm:grid-cols-3 sm:gap-6">
            {TRUST.map(({ key, Icon }) => (
              <li key={key} className="flex min-w-0 gap-3 sm:flex-col">
                <span
                  aria-hidden
                  className="flex h-11 w-11 shrink-0 items-center justify-center rounded-full bg-accent-soft text-accent"
                >
                  <Icon className="h-5 w-5" />
                </span>
                <div className="min-w-0">
                  <h3 className="font-semibold text-foreground">{tx(`trust.${key}.title`)}</h3>
                  <p className="mt-1 text-sm leading-relaxed text-muted">{tx(`trust.${key}.text`)}</p>
                </div>
              </li>
            ))}
          </ul>
        </section>

        <section ref={catalogRef} aria-labelledby="academy-courses" className="flex scroll-mt-24 flex-col gap-8">
          <h2 id="academy-courses" className="sr-only">
            {tx("catalog.heading")}
          </h2>

          {!state.ok ? (
            <Notice Icon={FiAlertCircle} title={tx("error.title")}>
              {/* Обычная ссылка, не Link: нужна полная перезагрузка — повторный запрос к серверу. */}
              <a href={pageHref(page)} className={NOTICE_LINK}>
                {tx("error.retry")}
              </a>
            </Notice>
          ) : state.view.total === 0 ? (
            <Notice Icon={FiBookOpen} title={tx("empty.title")}>
              <p className="text-sm text-muted">{tx("empty.text")}</p>
            </Notice>
          ) : state.view.outOfRange ? (
            <Notice Icon={FiBookOpen} title={tx("missing.title")}>
              <Link href={pageHref(1)} className={NOTICE_LINK}>
                {tx("missing.link")}
              </Link>
            </Notice>
          ) : (
            <ul className="grid grid-cols-1 gap-5 md:grid-cols-2 lg:grid-cols-3">
              {state.view.courses.map((course, i) => (
                <li key={course.id} className="min-w-0">
                  <CourseCard
                    course={{ ...course, href: course.url }}
                    labels={cardLabels}
                    eager={i < 3}
                    headingId={`academy-course-${course.id}`}
                  />
                </li>
              ))}
            </ul>
          )}

          {state.ok && (
            <AcademyPagination page={state.view.page} pages={state.view.pages} labels={pagerLabels} onPick={toCatalog} />
          )}
        </section>

        <section
          aria-labelledby="academy-suggest"
          className={`${CARD} flex flex-col items-center px-6 py-8 text-center sm:px-10 sm:py-12`}
        >
          <h2 id="academy-suggest" className="max-w-2xl text-balance text-xl font-bold text-foreground sm:text-2xl">
            {tx("suggest.title")}
          </h2>
          <p className="mt-3 max-w-2xl text-balance text-muted">{tx("suggest.text")}</p>
          {/* Что под приглашением, задают в панели: ссылка или почта — кнопка, иное — текст; пусто — ничего. */}
          {suggest?.kind === "url" && (
            <a href={suggest.href} target="_blank" rel={EXTERNAL_REL} className={SUGGEST_BUTTON}>
              <FiSend className="h-4 w-4 shrink-0" aria-hidden />
              {tx("suggest.cta")}
              <span className="sr-only">{tx("card.new_tab")}</span>
            </a>
          )}
          {suggest?.kind === "email" && (
            <>
              {/* Письмо открывается в почтовой программе, не во вкладке. */}
              <a href={suggest.href} className={SUGGEST_BUTTON}>
                <FiMail className="h-4 w-4 shrink-0" aria-hidden />
                {tx("suggest.cta")}
              </a>
              {/* Почтовой программы может не быть — адрес виден и выделяется целиком для копирования. */}
              <p className="mt-3 max-w-full select-all text-sm text-muted [overflow-wrap:anywhere]">{suggest.text}</p>
            </>
          )}
          {suggest?.kind === "text" && (
            <SuggestText
              text={suggest.text}
              newTab={tx("card.new_tab")}
              className="mt-5 max-w-2xl whitespace-pre-line text-foreground [overflow-wrap:anywhere]"
              linkClassName="rounded-sm text-accent underline underline-offset-2 transition-colors hover:text-accent-strong focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent"
            />
          )}
        </section>
      </div>
    </main>
  );
}

const SUGGEST_BUTTON =
  "mt-6 inline-flex min-h-11 w-full items-center justify-center gap-2 rounded-full bg-accent px-6 py-2.5 font-semibold text-on-accent transition-colors hover:bg-accent-strong focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent focus-visible:ring-offset-2 focus-visible:ring-offset-background sm:w-auto";

const NOTICE_LINK =
  "inline-flex min-h-11 items-center justify-center rounded-full border border-border px-5 text-sm font-semibold text-foreground transition-colors hover:border-accent/60 hover:text-accent focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent";

function Notice({
  Icon,
  title,
  children,
}: {
  Icon: ComponentType<{ className?: string }>;
  title: string;
  children: ReactNode;
}) {
  return (
    <div className={`${CARD} flex flex-col items-center gap-3 px-6 py-12 text-center`}>
      <span aria-hidden className="flex h-12 w-12 items-center justify-center rounded-full bg-surface-2 text-muted">
        <Icon className="h-6 w-6" />
      </span>
      <p className="text-balance text-lg font-semibold text-foreground">{title}</p>
      {children}
    </div>
  );
}
