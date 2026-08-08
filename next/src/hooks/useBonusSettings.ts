"use client";

import { useEffect, useState } from "react";
import { fetchData } from "@/tools/fetchData";

export type BonusSettings = {
  /** Сколько кредитов начисляется за регистрацию. */
  welcome_bonus: number;
  /** До скольки кредитов бесплатно пополняется баланс каждый день. */
  daily_free_credits: number;
};

/**
 * useBonusSettings — реальные размеры бонусов из админки
 * (GET /api/plans/bonus-settings/, публично, без авторизации).
 *
 * Зачем: раньше «5 кредитов за регистрацию» было захардкожено в i18n-строках
 * ru/en/kg. Админ менял число в /admin-new, а сайт продолжал обещать старое —
 * классический рассинхрон. Теперь цифры в текстах подставляются отсюда.
 *
 * Запрос делается ОДИН РАЗ за сессию вкладки (модульный кэш ниже): хук
 * монтируется параллельно в нескольких местах (страница входа, сайдбар,
 * модалка лимита гостя, карточка баланса), дублировать сеть незачем.
 *
 * Значения по умолчанию совпадают с текущими настройками прода — если сеть
 * недоступна, текст останется осмысленным, а не покажет «0 кредитов».
 */
const FALLBACK: BonusSettings = { welcome_bonus: 20, daily_free_credits: 10 };

let cached: BonusSettings | null = null;
let inflight: Promise<BonusSettings> | null = null;

async function fetchOnce(): Promise<BonusSettings> {
  if (cached) return cached;
  if (inflight) return inflight;

  inflight = (async () => {
    try {
      const res = await fetchData<BonusSettings>("plans/bonus-settings/", "GET", null, false);
      const d = res?.data;
      if (res?.ok && d) {
        cached = {
          welcome_bonus: Number.isFinite(Number(d.welcome_bonus))
            ? Number(d.welcome_bonus)
            : FALLBACK.welcome_bonus,
          daily_free_credits: Number.isFinite(Number(d.daily_free_credits))
            ? Number(d.daily_free_credits)
            : FALLBACK.daily_free_credits,
        };
        return cached;
      }
    } catch {
      // сеть недоступна — отдаём фолбэк ниже
    }
    cached = FALLBACK;
    return cached;
  })();

  return inflight;
}

export function useBonusSettings(): BonusSettings {
  const [value, setValue] = useState<BonusSettings>(cached ?? FALLBACK);

  useEffect(() => {
    let cancelled = false;
    fetchOnce().then((v) => {
      if (!cancelled) setValue(v);
    });
    return () => {
      cancelled = true;
    };
  }, []);

  return value;
}
