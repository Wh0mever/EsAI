"use client";

import { useEffect, useState } from "react";
import { fetchData } from "@/tools/fetchData";
import type { CryptoCurrenciesResponse, CryptoCurrency } from "@/types/crypto";

/**
 * Список монет для оплаты. Запрашивается ОДИН раз за вкладку (модульный кэш,
 * как курс валют в useCurrency.ts): переключатель валют висит на нескольких
 * страницах сразу, дублировать запрос за каждым не нужно.
 *
 * enabled === null означает «ещё не знаем»: пока ответ не пришёл, кнопки
 * «Крипта» просто нет — лучше, чем показать её и через секунду убрать.
 */

let cached: CryptoCurrenciesResponse | null = null;
let inflight: Promise<CryptoCurrenciesResponse> | null = null;

async function fetchOnce(): Promise<CryptoCurrenciesResponse> {
  if (cached) return cached;
  if (inflight) return inflight;

  inflight = (async () => {
    try {
      const res = await fetchData<CryptoCurrenciesResponse>(
        "payments/crypto/currencies/", "GET", null, true
      );
      if (res.ok && res.data && typeof res.data.enabled === "boolean") {
        cached = {
          enabled: res.data.enabled,
          rate_kgs_to_usd: res.data.rate_kgs_to_usd,
          fee_paid_by_user: Boolean(res.data.fee_paid_by_user),
          currencies: Array.isArray(res.data.currencies) ? res.data.currencies : [],
        };
        return cached;
      }
    } catch {
      // сеть недоступна — считаем, что способа оплаты нет
    }
    // Не запоминаем неудачу: иначе один сетевой сбой прятал бы способ
    // оплаты до перезагрузки вкладки.
    inflight = null;
    return { enabled: false, currencies: [] };
  })();

  return inflight;
}

/** Сбросить кэш: нужно после входа/выхода — доступность зависит от человека. */
export function resetCryptoCurrenciesCache(): void {
  cached = null;
  inflight = null;
}

export function useCryptoCurrencies(active = true) {
  const [enabled, setEnabled] = useState<boolean | null>(cached ? cached.enabled : null);
  const [currencies, setCurrencies] = useState<CryptoCurrency[]>(cached?.currencies || []);
  const [rateKgsToUsd, setRateKgsToUsd] = useState<number | null>(
    cached?.rate_kgs_to_usd ? Number(cached.rate_kgs_to_usd) || null : null
  );
  const [feePaidByUser, setFeePaidByUser] = useState<boolean>(Boolean(cached?.fee_paid_by_user));
  const [loading, setLoading] = useState(!cached);

  useEffect(() => {
    if (!active) return;
    let alive = true;
    setLoading(!cached);
    (async () => {
      const data = await fetchOnce();
      if (!alive) return;
      setEnabled(data.enabled);
      setCurrencies(data.currencies);
      setRateKgsToUsd(data.rate_kgs_to_usd ? Number(data.rate_kgs_to_usd) || null : null);
      setFeePaidByUser(Boolean(data.fee_paid_by_user));
      setLoading(false);
    })();
    return () => {
      alive = false;
    };
  }, [active]);

  return { enabled, currencies, loading, rateKgsToUsd, feePaidByUser };
}
