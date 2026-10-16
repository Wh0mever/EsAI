/**
 * Фронтовое зеркало правил биллинга картинок из core/ai/model_billing.py.
 * Нужно витрине тарифов (CreditsExplainer), чтобы подпись «за картинку» стояла
 * только там, где бэкенд действительно списывает плоско за картинку.
 *
 * Цену показываем ту, что дал сервер: в режиме цен «наценка» она считается от
 * себестоимости и из коэффициента модели не выводится. Своя формула — только
 * для сервера, который цену ещё не отдаёт (у него и режима «наценка» нет).
 */

/** Как is_flux_image_model: вендор black-forest-labs/ или «flux.2» в id. */
export function isFluxImageModel(openrouterId?: string | null): boolean {
  const name = String(openrouterId ?? "").toLowerCase().split(":")[0];
  return name.startsWith("black-forest-labs/") || name.includes("flux.2");
}

/** Как flux_charge_credits в режиме legacy: max(1, int(coeff)); кривой коэффициент → 1. */
export function fluxCreditsPerImage(markupCoefficient?: number | string | null): number {
  const coeff = Number(markupCoefficient || 1);
  return Math.max(1, Number.isFinite(coeff) ? Math.trunc(coeff) : 1);
}

/** Целое число кредитов с сервера или null, если цены нет. */
function serverCredits(value: unknown): number | null {
  if (value === null || value === undefined || value === "") return null;
  const n = Number(value);
  return Number.isFinite(n) && n >= 1 ? Math.trunc(n) : null;
}

/**
 * Цена одной картинки FLUX в действующем режиме цен: credits_per_image с
 * сервера, а без него — legacy-формула (сервер без этого поля режима «наценка»
 * не знает, и формула совпадает со списанием).
 */
export function fluxImageCredits(model: {
  credits_per_image?: number | null;
  markup_coefficient?: number | string | null;
}): number {
  return serverCredits(model.credits_per_image) ?? fluxCreditsPerImage(model.markup_coefficient);
}

/** Таблица цен ролика с сервера: {разрешение: {секунды: кредиты}}. */
export type VideoPriceTable = Record<string, Record<string, number>>;

/**
 * «От N»: самая дешёвая ячейка серверных таблиц (общей и по пропорциям) —
 * как price_from у видеостудии. null — сервер цены не дал (в режиме «наценка»
 * у модели нет себестоимости, или таблица не посчиталась). «Секунды × тариф»
 * не считаем: у видео тариф — не цена, у Seedance он вовсе 0.
 */
export function videoPriceFrom(
  table?: VideoPriceTable | null,
  byAspect?: Record<string, VideoPriceTable> | null,
): number | null {
  let best: number | null = null;
  for (const t of [table, ...Object.values(byAspect ?? {})]) {
    for (const row of Object.values(t ?? {})) {
      for (const cell of Object.values(row ?? {})) {
        const n = serverCredits(cell);
        if (n !== null && (best === null || n < best)) best = n;
      }
    }
  }
  return best;
}
