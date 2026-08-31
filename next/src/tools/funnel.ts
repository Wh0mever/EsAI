"use client";

import { fetchData } from "@/tools/fetchData";
import { getOrCreateDeviceKey } from "@/tools/deviceKey";

/**
 * Счётчики воронки оплаты.
 *
 * По таблице платежей видно только то, что началось с нажатия «Пополнить».
 * Сколько людей вообще дошло до тарифов и сколько нажало кнопку — не видно,
 * а без этого нельзя понять, где теряются деньги.
 *
 * Гость узнаётся по тому же ключу устройства, что и скидка при уходе: он
 * лежит в браузере и общий на весь сайт.
 *
 * Ошибки глушим намеренно: счётчик, который может сломать оплату, вреднее,
 * чем отсутствие счётчика.
 */
export type FunnelStep =
  | "pricing_view"
  | "topup_click"
  | "studio_view"
  | "studio_scene_add";

export function trackFunnel(name: FunnelStep, meta?: Record<string, unknown>): void {
  try {
    void fetchData(
      "payments/funnel/event/",
      "POST",
      { name, meta: meta || {} },
      false,
      { "X-Device-Key": getOrCreateDeviceKey() }
    );
  } catch {
    // тишина: аналитика не должна мешать покупке
  }
}
