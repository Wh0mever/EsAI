/**
 * Фронтовое зеркало правил биллинга картинок из core/ai/model_billing.py.
 * Нужно витрине тарифов (CreditsExplainer), чтобы подпись «за картинку» стояла
 * только там, где бэкенд действительно списывает плоско за картинку.
 */

/** Как is_flux_image_model: вендор black-forest-labs/ или «flux.2» в id. */
export function isFluxImageModel(openrouterId?: string | null): boolean {
  const name = String(openrouterId ?? "").toLowerCase().split(":")[0];
  return name.startsWith("black-forest-labs/") || name.includes("flux.2");
}

/** Как flux_charge_credits: max(1, int(coeff)); кривой коэффициент → 1. */
export function fluxCreditsPerImage(markupCoefficient?: number | string | null): number {
  const coeff = Number(markupCoefficient || 1);
  return Math.max(1, Number.isFinite(coeff) ? Math.trunc(coeff) : 1);
}
