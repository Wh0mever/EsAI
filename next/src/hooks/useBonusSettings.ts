"use client";

import { useEffect, useState } from "react";
import { fetchData } from "@/tools/fetchData";

export type BonusSettings = {
  /** Сколько кредитов начисляется за регистрацию. */
  welcome_bonus: number;
  /** До скольки кредитов бесплатно пополняется баланс каждый день. */
  daily_free_credits: number;
  /**
   * Числа уже известны (пришли с сервера либо взяты из прошлого визита).
   * Пока false — показывать текст БЕЗ цифры.
   */
  loaded: boolean;
};

/**
 * useBonusSettings — реальные размеры бонусов из админки
 * (GET /api/plans/bonus-settings/, публично, без авторизации).
 *
 * Зачем: раньше «5 кредитов за регистрацию» было захардкожено в i18n-строках
 * ru/en/kg. Админ менял число в /admin-new, а сайт продолжал обещать старое.
 *
 * Почему нет числового значения по умолчанию. Оно тут было — и оказалось той
 * же граблей: клиент снизил бонус в админке до 10, а страница входа первую
 * долю секунды показывала зашитые 20 и только потом подставляла настоящее
 * число. Обещать сумму, которой нет, нельзя даже на мгновение, поэтому до
 * ответа сервера числа считаются неизвестными (loaded=false), а тексты
 * показывают вариант без цифры.
 *
 * Прошлый ответ сохраняется в localStorage, так что «без цифры» видно только
 * в самый первый визит: дальше первый кадр сразу с числом, пусть и с прошлой
 * загрузки — это настоящее значение сервера, а не выдуманная константа.
 */

const LS_KEY = "esai-bonus-settings";

type Values = Pick<BonusSettings, "welcome_bonus" | "daily_free_credits">;

let cached: Values | null = null;
let inflight: Promise<Values | null> | null = null;

function readStored(): Values | null {
  if (typeof window === "undefined") return null;
  try {
    const raw = window.localStorage.getItem(LS_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw);
    const w = Number(parsed?.welcome_bonus);
    const d = Number(parsed?.daily_free_credits);
    if (!Number.isFinite(w) || !Number.isFinite(d)) return null;
    return { welcome_bonus: w, daily_free_credits: d };
  } catch {
    return null;
  }
}

function store(v: Values) {
  try {
    window.localStorage.setItem(LS_KEY, JSON.stringify(v));
  } catch {}
}

async function fetchOnce(): Promise<Values | null> {
  if (cached) return cached;
  if (inflight) return inflight;

  inflight = (async () => {
    try {
      const res = await fetchData<Values>("plans/bonus-settings/", "GET", null, false);
      const d = res?.data;
      const w = Number(d?.welcome_bonus);
      const f = Number(d?.daily_free_credits);
      if (res?.ok && Number.isFinite(w) && Number.isFinite(f)) {
        cached = { welcome_bonus: w, daily_free_credits: f };
        store(cached);
        return cached;
      }
    } catch {
      // Сеть недоступна — остаёмся на значениях прошлого визита (или без цифры).
    }
    return null;
  })();

  return inflight;
}

export function useBonusSettings(): BonusSettings {
  const [value, setValue] = useState<Values | null>(cached);

  useEffect(() => {
    if (!cached) {
      const stored = readStored();
      if (stored) {
        cached = stored;
        setValue(stored);
      }
    }
    let cancelled = false;
    fetchOnce().then((v) => {
      if (v && !cancelled) setValue(v);
    });
    return () => {
      cancelled = true;
    };
  }, []);

  return {
    welcome_bonus: value?.welcome_bonus ?? 0,
    daily_free_credits: value?.daily_free_credits ?? 0,
    loaded: value !== null,
  };
}
