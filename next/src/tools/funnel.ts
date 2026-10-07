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
  // Единый QR (GoPay), наш экран оплаты. shown — экран с кодом показан
  // { package_id, resumed, mobile, embed, is_test }; app_open — нажата кнопка
  // банка { package_id, app }; save — «сохранить QR» { package_id, ok };
  // other_method — ушёл платить иначе; paid — УВИДЕЛ наш экран «Оплачено»
  // { package_id, seconds } (на телефоне многие платят в банке и во вкладку не
  // возвращаются, настоящие оплаты отчёт берёт с сервера); expired — код истёк.
  | "kgs_qr_shown"
  | "kgs_qr_app_open"
  | "kgs_qr_save"
  | "kgs_qr_other_method"
  | "kgs_qr_paid"
  | "kgs_qr_expired"
  // Видеостудия (/video-studio): имена — в белом списке FunnelEvent.NAMES,
  // meta по шагам — VsFunnelMeta в lib/vstudio/types.ts (отправлять через trackVs).
  // view — студия открылась и ею можно пользоваться { authed, home };
  // home_pick — нажатие на первом экране до первого запуска { what, id }.
  | "vstudio_view"
  | "vstudio_home_pick"
  | "vstudio_upload"
  | "vstudio_mention"
  | "vstudio_imagegen"
  | "vstudio_blocked"
  | "vstudio_run_click"
  | "vstudio_paywall"
  | "vstudio_auth_prompt"
  | "vstudio_condense"
  | "vstudio_share";

/**
 * Шаги, после которых страница сразу уходит в фон: нажали кнопку банка или
 * открылось системное окно «сохранить». iOS замораживает вкладку в тот же
 * миг, и обычный запрос не успевает уйти — а именно эти два шага показывают,
 * пользуются ли люди кнопками банков.
 */
const LEAVING_STEPS: ReadonlySet<FunnelStep> = new Set<FunnelStep>(["kgs_qr_app_open", "kgs_qr_save"]);

const EVENT_URL = "/api/payments/funnel/event/";

/** Доставка, которая переживает уход со страницы. Пишется без пользователя, по устройству. */
function sendLeaving(name: FunnelStep, meta: Record<string, unknown>): void {
  const key = getOrCreateDeviceKey();
  const json = JSON.stringify({ name, meta, device_key: key });
  try {
    void fetch(EVENT_URL, {
      method: "POST",
      keepalive: true,
      headers: { "Content-Type": "application/json", "X-Device-Key": key },
      body: json,
    }).catch(() => {
      // тишина: аналитика не должна мешать покупке
    });
    return;
  } catch {
    // fetch с keepalive не поддержан или отклонён — пробуем sendBeacon
  }
  try {
    navigator.sendBeacon(EVENT_URL, new Blob([json], { type: "application/json" }));
  } catch {
    // тишина
  }
}

export function trackFunnel(name: FunnelStep, meta?: Record<string, unknown>): void {
  if (LEAVING_STEPS.has(name)) {
    try {
      sendLeaving(name, meta || {});
    } catch {
      // тишина
    }
    return;
  }
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
