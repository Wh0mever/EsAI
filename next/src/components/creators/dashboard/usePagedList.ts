"use client";

import { useCallback, useEffect, useState } from "react";
import type { CrError, CrResult, Paged } from "@/lib/creators/types";

type Row = { id: number };
type FetchPage<T> = (page: number) => Promise<CrResult<Paged<T>>>;

type Loaded<T> = {
  /** Чей это ответ: запрос (он меняется вместе с фильтром) и номер попытки. */
  source: FetchPage<T>;
  attempt: number;
  rows: T[];
  count: number;
  page: number;
  error: CrError | null;
};

export type PagedList<T> = {
  /** Первая страница ещё не пришла (в том числе после смены фильтра и «Повторить»). */
  loading: boolean;
  /** Ошибка первой страницы — список показать нечем. */
  error: CrError | null;
  rows: T[];
  count: number;
  loadingMore: boolean;
  /** Ошибка кнопки «Ещё»: уже показанные строки остаются на экране. */
  moreError: CrError | null;
  loadMore: () => void;
  reload: () => void;
  /** Поставить только что созданную строку первой, не перезапрашивая список. */
  prepend: (row: T) => void;
};

/**
 * Список кабинета со страницами: ?page=N по 50 строк, тело {count, results},
 * под списком кнопка «Ещё».
 *
 * fetchPage должен быть стабильным (useCallback): новая функция = новый фильтр,
 * список грузится заново. Какому запросу принадлежат строки, хранится рядом с
 * ними — поэтому после смены фильтра старые строки не мелькают под новым.
 */
export function usePagedList<T extends Row>(fetchPage: FetchPage<T>): PagedList<T> {
  const [attempt, setAttempt] = useState(0);
  const [state, setState] = useState<Loaded<T> | null>(null);
  const [more, setMore] = useState<{ busy: boolean; error: CrError | null }>({ busy: false, error: null });

  useEffect(() => {
    let alive = true;
    (async () => {
      const res = await fetchPage(1);
      if (!alive) return;
      setState(
        res.ok
          ? { source: fetchPage, attempt, rows: res.data.results, count: res.data.count, page: 1, error: null }
          : { source: fetchPage, attempt, rows: [], count: 0, page: 0, error: res.error },
      );
      setMore({ busy: false, error: null });
    })();
    return () => {
      alive = false;
    };
  }, [fetchPage, attempt]);

  const current = state && state.source === fetchPage && state.attempt === attempt ? state : null;
  const nextPage = current ? current.page + 1 : 0;
  const busy = more.busy;

  const loadMore = useCallback(() => {
    if (!nextPage || busy) return;
    setMore({ busy: true, error: null });
    void (async () => {
      const res = await fetchPage(nextPage);
      if (res.ok) {
        setState((prev) => {
          // Пока шёл запрос, фильтр сменили — этот ответ уже не нужен.
          if (!prev || prev.source !== fetchPage || prev.attempt !== attempt || prev.page + 1 !== nextPage) return prev;
          // Пока человек читал, наверху могли появиться новые строки, и граница
          // страниц сдвинулась: одну и ту же строку дважды не показываем.
          const seen = new Set(prev.rows.map((row) => row.id));
          const fresh = res.data.results.filter((row) => !seen.has(row.id));
          const rows = [...prev.rows, ...fresh];
          // Пустая страница — дальше ничего нет, кнопка «Ещё» должна исчезнуть.
          const count = res.data.results.length ? Math.max(res.data.count, rows.length) : rows.length;
          return { ...prev, rows, count, page: nextPage };
        });
      }
      setMore({ busy: false, error: res.ok ? null : res.error });
    })();
  }, [fetchPage, attempt, nextPage, busy]);

  const reload = useCallback(() => setAttempt((n) => n + 1), []);

  const prepend = useCallback((row: T) => {
    setState((prev) =>
      prev ? { ...prev, rows: [row, ...prev.rows.filter((r) => r.id !== row.id)], count: prev.count + 1 } : prev,
    );
  }, []);

  return {
    loading: current === null,
    error: current?.error ?? null,
    rows: current?.rows ?? [],
    count: current?.count ?? 0,
    loadingMore: busy,
    moreError: more.error,
    loadMore,
    reload,
    prepend,
  };
}
