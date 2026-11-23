"use client";

import { useCallback, useEffect, useState } from "react";
import { getCatalog, type CatalogItem, type CatalogKind, type InfluencerCategory } from "@/lib/creative/api";
import type { VsError } from "@/lib/vstudio/types";

/**
 * Каталог формы (стили, пресеты, опции блогера) с кэшем на вкладку: сервер сам
 * держит его 6 часов, а переходы между инструментами не должны его перезапрашивать.
 */
type Entry = { at: number; data: CatalogItem[] | InfluencerCategory[] };
const cache = new Map<CatalogKind, Entry>();
const TTL_MS = 10 * 60_000;

export type CatalogState<T> = { data: T | null; error: VsError | null; loading: boolean; retry: () => void };

export function useCatalog<T extends CatalogItem[] | InfluencerCategory[]>(kind: CatalogKind, enabled = true): CatalogState<T> {
  const [state, setState] = useState<{ kind: CatalogKind; tick: number; data: T | null; error: VsError | null } | null>(null);
  const [tick, setTick] = useState(0);

  useEffect(() => {
    if (!enabled) return;
    let alive = true;
    const hit = cache.get(kind);
    const load = async () => {
      if (hit && Date.now() - hit.at < TTL_MS) {
        if (alive) setState({ kind, tick, data: hit.data as T, error: null });
        return;
      }
      const r = await getCatalog(kind);
      if (!alive) return;
      if (r.ok) {
        cache.set(kind, { at: Date.now(), data: r.data });
        setState({ kind, tick, data: r.data as T, error: null });
      } else {
        setState({ kind, tick, data: null, error: r.error });
      }
    };
    void load();
    return () => {
      alive = false;
    };
  }, [kind, tick, enabled]);

  const retry = useCallback(() => setTick((x) => x + 1), []);
  const current = state && state.kind === kind && state.tick === tick ? state : null;
  return { data: current?.data ?? null, error: current?.error ?? null, loading: enabled && !current, retry };
}
