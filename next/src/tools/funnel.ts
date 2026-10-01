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
  | "studio_hero_pick"
  | "studio_scene_add"
  | "studio_tryon"
  | "studio_auth_prompt"
  | "studio_render_click"
  | "studio_paywall"
  // Крипта: между «выбрал монету» и «оплатил» человек уходит в свой кошелёк,
  // и без этих шагов видно только начало и конец пути.
  | "crypto_currency_pick"
  | "crypto_invoice_created"
  | "crypto_paid"
  // Оплата в сомах: какой способ человек выбрал в нашем окне до ухода на
  // страницу банка. meta: { package_id, method }.
  | "kgs_method_pick"
  // Видеостудия (/video-studio): имена — в белом списке FunnelEvent.NAMES,
  // meta по шагам — VsFunnelMeta в lib/vstudio/types.ts (отправлять через trackVs).
  | "vstudio_view"
  | "vstudio_upload"
  | "vstudio_mention"
  | "vstudio_imagegen"
  | "vstudio_blocked"
  | "vstudio_run_click"
  | "vstudio_paywall"
  | "vstudio_auth_prompt"
  | "vstudio_condense"
  | "vstudio_share";

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
