"use client";

import { useCallback, useEffect, useState } from "react";
import { quote, type QuoteJSON } from "@/lib/creative/api";
import type { VsError } from "@/lib/vstudio/types";

/**
 * Живая цена: POST quote/ через 300 мс после последней правки формы.
 *
 * Цена годна для запуска, только если её ключ (paramsKey тела) совпадает с
 * текущим — иначе кнопка ждёт новый ответ. Устаревшие ответы выбрасываем.
 * После пополнения (balance:refresh) пересчитываем — меняется «останется N кр».
 */
export const QUOTE_DELAY_MS = 300;

export type QuoteState = {
  /** ответ для ключа key (или null, пока считаем / ошибка) */
  quote: QuoteJSON | null;
  error: VsError | null;
  /** ключ, к которому относится quote/error */
  key: string;
  loading: boolean;
  refresh: () => void;
};

export function useQuote(tool: string, params: Record<string, unknown>, key: string, enabled: boolean, lang: string): QuoteState {
  const [result, setResult] = useState<{ key: string; nonce: number; quote: QuoteJSON | null; error: VsError | null } | null>(null);
  const [nonce, setNonce] = useState(0);

  useEffect(() => {
    if (!enabled) return;
    let alive = true;
    const timer = setTimeout(async () => {
      const r = await quote(tool, params, lang);
      if (!alive) return;
      setResult(r.ok ? { key, nonce, quote: r.data, error: null } : { key, nonce, quote: null, error: r.error });
    }, QUOTE_DELAY_MS);
    return () => {
      alive = false;
      clearTimeout(timer);
    };
    // params описывает key: пересчёт — по ключу, а не по ссылке на объект.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tool, key, enabled, nonce, lang]);

  const refresh = useCallback(() => setNonce((x) => x + 1), []);

  useEffect(() => {
    const onBalance = () => setNonce((x) => x + 1);
    window.addEventListener("balance:refresh", onBalance);
    return () => window.removeEventListener("balance:refresh", onBalance);
  }, []);

  const current = enabled && result && result.key === key && result.nonce === nonce ? result : null;
  // Пересчёт той же формы (после пополнения) — прежняя цена видна, пока считаем.
  const sameKey = enabled && result && result.key === key ? result : null;
  return {
    quote: current?.quote ?? sameKey?.quote ?? null,
    error: current?.error ?? null,
    key,
    loading: enabled && !current,
    refresh,
  };
}
