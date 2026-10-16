/**
 * Карточка «Склейка: цена» в «Настройках»: весь контракт с сервером — здесь
 * (core/merge/views.ManageSettingsView, описание — vstudio2-notes/pricing/CONTRACT_M.md §5).
 *
 *   GET   merge/manage/settings/   → { price_credits, default_price_credits, overridden }
 *   PATCH merge/manage/settings/   { price_credits: 0…100000 | null } → то же; null — цена из кода
 *
 * Цена списывается только за готовую склейку; 0 — склейка бесплатная. Новая
 * цена действует через ~30 с (кэш настроек сервера). Модуль чистый — его
 * проверяет mergePrice.test.mjs.
 */

export const MERGE_SETTINGS_PATH = "merge/manage/settings/";
export const MAX_MERGE_PRICE = 100000;

export type MergePriceSettings = {
  price: number;
  /** Цена из кода (сейчас 20). */
  defaultPrice: number;
  /** false — действует цена из кода. */
  overridden: boolean;
};

type Row = Record<string, unknown>;
const isRow = (v: unknown): v is Row => typeof v === "object" && v !== null && !Array.isArray(v);
const int = (v: unknown): number | null => (typeof v === "number" && Number.isInteger(v) && v >= 0 ? v : null);
const str = (v: unknown): string => (typeof v === "string" ? v : "");

/** Ответ GET/PATCH → карточка; null — ответ не похож на настройки. */
export function parseMergePrice(raw: unknown): MergePriceSettings | null {
  if (!isRow(raw)) return null;
  const price = int(raw.price_credits);
  if (price == null) return null;
  return {
    price,
    defaultPrice: int(raw.default_price_credits) ?? price,
    overridden: raw.overridden === true,
  };
}

/** Поле ввода → цена. Только целое число 0…100000, без знаков и пробелов внутри. */
export function parsePriceInput(text: string): { ok: true; value: number } | { ok: false; error: string } {
  const v = text.trim();
  if (!/^\d+$/.test(v)) return { ok: false, error: `Цена — целое число от 0 до ${MAX_MERGE_PRICE}` };
  const value = Number(v);
  if (!Number.isSafeInteger(value) || value > MAX_MERGE_PRICE) {
    return { ok: false, error: `Цена — целое число от 0 до ${MAX_MERGE_PRICE}` };
  }
  return { ok: true, value };
}

/** «20 кр» / «бесплатно». */
export function priceText(n: number): string {
  return n > 0 ? `${n} кр` : "бесплатно";
}

/** Что действует сейчас — одной строкой. */
export function priceSummary(s: MergePriceSettings): string {
  const now = s.price > 0 ? `Склейка стоит ${priceText(s.price)} за готовый ролик` : "Склейка сейчас бесплатная";
  return s.overridden ? `${now}. В коде — ${priceText(s.defaultPrice)}.` : `${now} — это цена из кода.`;
}

export function errorText(res: { status: number; data?: unknown }, fallback: string): string {
  if (res.status === 0) return "Нет связи с сервером. Проверьте интернет и повторите.";
  if (res.status === 401 || res.status === 403) return "Нет доступа: цену склейки меняют только сотрудники.";
  if (res.status === 429) return "Слишком много запросов подряд. Подождите минуту и повторите.";
  const data = isRow(res.data) ? res.data : {};
  const errors = isRow(data.errors) ? data.errors : {};
  const detail = str(errors.price_credits) || str(data.detail);
  return detail || `${fallback} (HTTP ${res.status})`;
}
