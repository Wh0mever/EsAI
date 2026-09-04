"use client";

import { useCallback, useEffect, useState } from "react";
import { fetchData } from "@/tools/fetchData";
import {
  Currency,
  CurrencyRateResponse,
  FALLBACK_KGS_TO_RUB_RATE,
  FALLBACK_KGS_TO_USD_RATE,
  convertFromKgs,
  formatPrice,
  getInitialCurrency,
  isManualCurrency,
  persistCurrency,
} from "@/lib/currency";

/**
 * useCurrency — общее состояние переключателя валют KGS/RUB (задача клиента:
 * ЮKassa попросила показывать цены и в рублях, см. project_esai_platform_ux).
 *
 * Приоритет: ручной выбор пользователя (CurrencySwitch) > авто-детект по
 * геолокации IP (бэкенд, GET /api/plans/currency-rate/) > дефолт KGS.
 * Ручной выбор ВСЕГДА побеждает — многие пользователи ходят через VPN, и
 * автоопределение может ошибиться (прямое требование клиента).
 *
 * Курс и гео-подсказка запрашиваются ОДИН РАЗ за сессию вкладки (модульный
 * кэш ниже) — компонент может быть смонтирован параллельно в нескольких
 * местах (TokenPackages на /pricing, HomePricingPreview на главной,
 * TopUpModal в чате), не нужно дублировать сетевой запрос за каждым.
 *
 * ⚠️ Это ТОЛЬКО витринный пересчёт цены. Реальная оплата (POST
 * /api/plans/purchase/) всегда идёт через FreedomPay в сомах — см. решение
 * по п.4 задачи в next/src/components/pricing/CurrencySwitch.tsx /
 * TokenPackages.tsx (кнопка покупки скрывается при выбранной RUB).
 */

let inflightRatePromise: Promise<CurrencyRateResponse> | null = null;
let cachedRate: CurrencyRateResponse | null = null;

async function fetchRateOnce(): Promise<CurrencyRateResponse> {
  if (cachedRate) return cachedRate;
  if (inflightRatePromise) return inflightRatePromise;

  inflightRatePromise = (async () => {
    try {
      // auth=true: доступность крипты зависит от человека (режим «только
      // сотрудникам» на время проверки боевых ключей).
      const res = await fetchData<CurrencyRateResponse>("plans/currency-rate/", "GET", null, true);
      if (res.ok && res.data && Number.isFinite(Number(res.data.rate_kgs_to_rub))) {
        cachedRate = {
          base_currency: "KGS",
          rate_kgs_to_rub: Number(res.data.rate_kgs_to_rub),
          rate_kgs_to_usd: Number(res.data.rate_kgs_to_usd) || FALLBACK_KGS_TO_USD_RATE,
          crypto_enabled: Boolean(res.data.crypto_enabled),
          suggested_currency: res.data.suggested_currency === "RUB" ? "RUB" : "KGS",
        };
        return cachedRate;
      }
    } catch {
      // сеть недоступна — тихо фолбэчимся ниже
    }
    cachedRate = {
      base_currency: "KGS",
      rate_kgs_to_rub: FALLBACK_KGS_TO_RUB_RATE,
      rate_kgs_to_usd: FALLBACK_KGS_TO_USD_RATE,
      crypto_enabled: false,
      suggested_currency: "KGS",
    };
    return cachedRate;
  })();

  return inflightRatePromise;
}

export function useCurrency() {
  const [currency, setCurrencyState] = useState<Currency>(() => getInitialCurrency());
  const [rate, setRate] = useState<number>(cachedRate?.rate_kgs_to_rub ?? FALLBACK_KGS_TO_RUB_RATE);
  const [usdRate, setUsdRate] = useState<number>(
    cachedRate?.rate_kgs_to_usd ?? FALLBACK_KGS_TO_USD_RATE
  );
  const [cryptoEnabled, setCryptoEnabled] = useState<boolean>(
    cachedRate?.crypto_enabled ?? false
  );
  const [rateReady, setRateReady] = useState(cachedRate !== null);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      const data = await fetchRateOnce();
      if (cancelled) return;
      setRate(data.rate_kgs_to_rub);
      setUsdRate(data.rate_kgs_to_usd);
      setCryptoEnabled(data.crypto_enabled);
      setRateReady(true);

      // Доллар выбирается только ради крипты. Если способ выключили (или
      // человек вышел из аккаунта), молча возвращаем сомы — иначе на витрине
      // остались бы долларовые цены без возможности заплатить.
      if (!data.crypto_enabled && currency === "USD") {
        setCurrencyState("KGS");
        persistCurrency("KGS", false);
      }

      // Авто-детект по геолокации применяется, ТОЛЬКО если пользователь ещё
      // ни разу не переключал валюту вручную — ручной выбор не трогаем.
      if (!isManualCurrency() && data.suggested_currency !== currency) {
        setCurrencyState(data.suggested_currency);
        persistCurrency(data.suggested_currency, false);
      }
    })();
    return () => {
      cancelled = true;
    };
    // Намеренно один раз при монтировании — currency в зависимостях не нужен
    // (иначе пересчёт суггеста зациклится сам на себя).
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const setCurrency = useCallback((code: Currency) => {
    setCurrencyState(code);
    persistCurrency(code, true);
  }, []);

  const convert = useCallback(
    (priceKgs: number) => convertFromKgs(priceKgs, currency, rate, usdRate),
    [currency, rate, usdRate]
  );

  /** Цена с подписью валюты — «1 900 сом», «1 805 ₽», «$21.66». */
  const format = useCallback(
    (priceKgs: number, somLabel?: string) =>
      formatPrice(convertFromKgs(priceKgs, currency, rate, usdRate), currency, somLabel),
    [currency, rate, usdRate]
  );

  return { currency, setCurrency, rate, usdRate, cryptoEnabled, rateReady, convert, format };
}
