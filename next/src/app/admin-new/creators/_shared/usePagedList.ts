"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import type { CrError, CrResult, Paged } from "@/lib/creators/types";

type Query = Record<string, string | number | boolean | null | undefined>;

type ListState<T> = {
  /** Каким запросом получен список; не совпадает с текущим — идёт загрузка. */
  key: string | null;
  rows: T[];
  count: number;
  page: number;
  error: CrError | null;
};

/** Сколько раз подряд перечитываем список, если его правят прямо во время перечитывания. */
const REREAD_TRIES = 3;

/**
 * Список раздела с дозагрузкой «Ещё»: сервер отдаёт по 50 строк, тело {count, results}.
 *
 * Список перезапрашивается с первой страницы при смене фильтров (params) и по
 * reload(). Ответ на устаревший фильтр отбрасывается: чипы переключают быстрее,
 * чем отвечает сервер. fetcher — функция из lib/creators/adminApi (ссылка на
 * неё не меняется между рендерами).
 *
 * Страницы на сервере считаются смещением по текущему отбору. Строка, над
 * которой выполнили действие, остаётся на экране (replace), но из отбора на
 * сервере могла уйти — тогда «страница N+1» начинается уже не там, где кончается
 * экран, и часть очереди потерялась бы. Поэтому после правок «Ещё» перечитывает
 * список с первой страницы, а не доклеивает следующую.
 */
export function usePagedList<T extends { id: number }, P extends Query>(
  fetcher: (params: P & { page: number }) => Promise<CrResult<Paged<T>>>,
  params: P,
) {
  const query = JSON.stringify(params);
  const [tick, setTick] = useState(0);
  const key = `${query}#${tick}`;

  const [state, setState] = useState<ListState<T>>({ key: null, rows: [], count: 0, page: 1, error: null });
  const [loadingMore, setLoadingMore] = useState(false);
  const [moreError, setMoreError] = useState<CrError | null>(null);

  /** Строки, изменённые на месте после последнего чтения списка с сервера. Не пусто — смещения страниц не верны. */
  const edited = useRef(new Map<number, T>());
  /** «Ещё» уже выполняется: второй клик в том же кадре не должен запросить ту же страницу. */
  const busy = useRef(false);

  useEffect(() => {
    let alive = true;
    (async () => {
      const res = await fetcher({ ...(JSON.parse(query) as P), page: 1 });
      if (!alive) return;
      edited.current = new Map();
      setMoreError(null);
      setState(
        res.ok
          ? { key, rows: res.data.results || [], count: res.data.count || 0, page: 1, error: null }
          : { key, rows: [], count: 0, page: 1, error: res.error },
      );
    })();
    return () => {
      alive = false;
    };
  }, [fetcher, query, key]);

  const more = useCallback(async () => {
    if (busy.current) return;
    busy.current = true;
    setLoadingMore(true);
    setMoreError(null);
    const base = JSON.parse(query) as P;
    const next = state.page + 1;
    try {
      // Список не трогали — доклеиваем следующую страницу.
      if (edited.current.size === 0) {
        const res = await fetcher({ ...base, page: next });
        if (!res.ok) {
          setMoreError(res.error);
          return;
        }
        // Правка успела пройти, пока страница шла, — смещение уже могло съехать, перечитываем ниже.
        if (edited.current.size === 0) {
          const { results, count } = res.data;
          // Пока страница шла, фильтр могли сменить — к чужому списку её не приклеиваем.
          // Строки, сдвинутые новыми записями на эту страницу, уже показаны: второй раз не добавляем.
          setState((prev) => {
            if (prev.key !== key) return prev;
            const seen = new Set(prev.rows.map((item) => item.id));
            const fresh = (results || []).filter((item) => !seen.has(item.id));
            return { ...prev, rows: [...prev.rows, ...fresh], count: count || 0, page: next };
          });
          return;
        }
      }

      // Строки меняли на месте — читаем заново страницы 1..next и заменяем список целиком.
      for (let attempt = 1; attempt <= REREAD_TRIES; attempt++) {
        const pending = edited.current;
        edited.current = new Map();

        const rows: T[] = [];
        const seen = new Set<number>();
        let count = 0;
        let lastPage = 1;
        let failed: CrError | null = null;
        for (let page = 1; page <= next; page++) {
          const res = await fetcher({ ...base, page });
          if (!res.ok) {
            failed = res.error;
            break;
          }
          const results = res.data.results || [];
          count = res.data.count || 0;
          if (results.length === 0) break;
          lastPage = page;
          for (const item of results) {
            if (seen.has(item.id)) continue;
            seen.add(item.id);
            rows.push(item);
          }
          if (rows.length >= count) break;
        }

        if (failed) {
          // Список на экране прежний, значит и правки в нём всё ещё не учтены.
          edited.current = new Map([...pending, ...edited.current]);
          setMoreError(failed);
          return;
        }
        // Правили прямо во время чтения — страницы могли разойтись, читаем ещё раз.
        if (edited.current.size > 0 && attempt < REREAD_TRIES) continue;

        // Если правки не прекращаются, показываем прочитанное с ними поверх; следующее «Ещё» перечитает снова.
        const overlay = edited.current;
        setState((prev) =>
          prev.key === key
            ? { ...prev, rows: rows.map((item) => overlay.get(item.id) ?? item), count, page: lastPage }
            : prev,
        );
        return;
      }
    } finally {
      busy.current = false;
      setLoadingMore(false);
    }
  }, [fetcher, query, key, state.page]);

  /** Строку заменяем ответом действия: статус меняется на месте, строка из списка не пропадает. */
  const replace = useCallback((row: T) => {
    edited.current.set(row.id, row);
    setState((prev) => ({ ...prev, rows: prev.rows.map((item) => (item.id === row.id ? row : item)) }));
  }, []);

  const reload = useCallback(() => setTick((value) => value + 1), []);

  return {
    rows: state.rows,
    count: state.count,
    error: state.error,
    loading: state.key !== key,
    loadingMore,
    moreError,
    more,
    replace,
    reload,
  };
}
