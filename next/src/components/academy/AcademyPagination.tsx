import Link from "next/link";
import type { MouseEvent } from "react";
import { FiChevronLeft, FiChevronRight } from "react-icons/fi";
import { pageHref, pagerItems } from "@/lib/academy/shared";

export type PagerLabels = { nav: string; prev: string; next: string; page: (page: number) => string };

const CELL =
  "inline-flex min-h-11 min-w-11 items-center justify-center gap-1 rounded-full px-3 text-sm font-medium tabular-nums";
const LINK = `${CELL} border border-border bg-surface text-foreground transition-colors hover:border-accent/60 hover:text-accent focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent`;
const OFF = `${CELL} border border-border text-muted-2 opacity-50`;

/**
 * Страницы каталога — обычные ссылки ?page=N (их видят и краулеры без JS), без
 * «Показать ещё» (ТЗ). scroll={false} и onPick: к началу каталога, а не к шапке
 * страницы, прокручивает AcademyView — в момент нажатия, пока грузится страница.
 * На телефоне ряд из 9 кнопок по 44 px не влезает в 360 px — при больших
 * списках там вместо номеров «3 / 12» между стрелками.
 */
export default function AcademyPagination({
  page,
  pages,
  labels,
  onPick,
}: {
  page: number;
  pages: number;
  labels: PagerLabels;
  onPick?: () => void;
}) {
  if (pages <= 1) return null;
  // Открыть в новой вкладке (Ctrl/⌘, средняя кнопка) — эту страницу не трогаем.
  const pick = (e: MouseEvent<HTMLAnchorElement>) => {
    if (e.button === 0 && !e.metaKey && !e.ctrlKey && !e.shiftKey && !e.altKey) onPick?.();
  };
  const inRange = page >= 1 && page <= pages;
  const prev = inRange && page > 1 ? page - 1 : null;
  const next = page < pages ? page + 1 : null;
  const compact = pages > 4;
  const numberCls = compact ? "hidden sm:block" : "";

  return (
    <nav aria-label={labels.nav} className="flex justify-center">
      <ul className="flex flex-wrap items-center justify-center gap-2">
        <li>
          {prev !== null ? (
            <Link href={pageHref(prev)} scroll={false} onClick={pick} rel="prev" className={LINK}>
              <FiChevronLeft className="h-4 w-4" aria-hidden />
              <span className="sr-only sm:not-sr-only">{labels.prev}</span>
            </Link>
          ) : (
            <span className={OFF} aria-hidden>
              <FiChevronLeft className="h-4 w-4" />
              <span className="hidden sm:inline">{labels.prev}</span>
            </span>
          )}
        </li>
        {compact && inRange && (
          <li className="sm:hidden">
            <span aria-current="page" aria-label={labels.page(page)} className={`${CELL} text-muted tabular-nums`}>
              {page} / {pages}
            </span>
          </li>
        )}
        {pagerItems(page, pages).map((item) =>
          item.kind === "gap" ? (
            <li key={item.key} aria-hidden className={`${numberCls} px-1 text-sm text-muted-2`}>
              …
            </li>
          ) : (
            <li key={item.page} className={numberCls}>
              {item.current ? (
                <span aria-current="page" aria-label={labels.page(item.page)} className={`${CELL} bg-accent text-on-accent`}>
                  {item.page}
                </span>
              ) : (
                <Link href={pageHref(item.page)} scroll={false} onClick={pick} aria-label={labels.page(item.page)} className={LINK}>
                  {item.page}
                </Link>
              )}
            </li>
          ),
        )}
        <li>
          {next !== null ? (
            <Link href={pageHref(next)} scroll={false} onClick={pick} rel="next" className={LINK}>
              <span className="sr-only sm:not-sr-only">{labels.next}</span>
              <FiChevronRight className="h-4 w-4" aria-hidden />
            </Link>
          ) : (
            <span className={OFF} aria-hidden>
              <span className="hidden sm:inline">{labels.next}</span>
              <FiChevronRight className="h-4 w-4" />
            </span>
          )}
        </li>
      </ul>
    </nav>
  );
}
