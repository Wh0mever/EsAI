/**
 * Видеостудия, композер: строка баланса в раскладке цены — что в ней сказать (§5.4).
 *
 * «На балансе 987 992 кр (из них 390 кр ждут результата) → останется 987 212 кр»
 * читалось как 987 992 − 390 = 987 212, то есть как ошибка счёта: в строке было
 * только одно «390» — резерв идущей генерации, а цена самого запуска стоит выше,
 * в «Итого». Поэтому первой называем сумму, из которой цена и вычитается: при
 * резерве это «Свободно N кр», а сколько в резерве и сколько всего на балансе —
 * отдельной тихой строкой. Тогда «свободно − итого = останется» проверяется
 * взглядом. Без резерва строка прежняя.
 *
 * Резерв в ответе — одна сумма по всем идущим генерациям (их бывает несколько,
 * и не только из этой ленты), поэтому тихая строка не говорит, сколько их:
 * «пока идёт генерация», а не «держит генерация, которая сейчас идёт» — иначе
 * 404 кр «одной генерации» не сошлись бы с 390 кр на её карточке.
 *
 * Числа — как прислал сервер (quote.balance), форматирует их компонент.
 */
import type { BalanceJSON } from "@/lib/vstudio/types";
import type { ComposerTextKey } from "./composerText";

export type BalanceText = { key: ComposerTextKey; params: Record<string, number> };

export type BalanceLines = {
  /** От этой суммы отнимается цена: «На балансе N кр» или, при резерве, «Свободно N кр». */
  head: BalanceText;
  /** «останется N кр»; null — кредитов не хватает или остатка в ответе нет. */
  after: BalanceText | null;
  /** Тихая строка про резерв и весь баланс; null — резерва нет. */
  held: BalanceText | null;
  /** Сколько кредитов не хватает; 0 — хватает. */
  missing: number;
};

const amount = (v: unknown): number => (typeof v === "number" && Number.isFinite(v) ? v : 0);

/** null — баланса в ответе нет (гость). */
export function balanceLines(b: BalanceJSON | null | undefined, credits: number | null | undefined): BalanceLines | null {
  if (!b) return null;
  const balance = amount(b.balance);
  const reserved = Math.max(0, amount(b.reserved));
  const available = amount(b.available);
  const price = amount(credits);
  const after = typeof b.after === "number" && Number.isFinite(b.after) && b.after >= 0 ? b.after : null;
  return {
    head: reserved > 0 ? { key: "price.available", params: { available } } : { key: "price.balance", params: { balance } },
    after: after == null ? null : { key: "price.after", params: { after } },
    held: reserved > 0 ? { key: "price.held", params: { reserved, balance } } : null,
    missing: available < price ? Math.ceil(price - available) : 0,
  };
}

/**
 * Короткая строка у «Повторить» в ленте: «останется N кр». Рядом с ней баланс в
 * верхней строке и цена на кнопке, и при резерве «баланс − цена» не сходится с
 * остатком так же, как не сходилось в раскладке. Поэтому при резерве и здесь
 * впереди сумма, из которой цена вычитается (free); без резерва строка прежняя.
 * null — остатка в ответе нет или кредитов не хватает (тогда рядом «Пополнить»).
 */
export function retryBalance(
  b: BalanceJSON | null | undefined,
  credits: number | null | undefined,
): { free: number | null; after: number } | null {
  const lines = balanceLines(b, credits);
  if (!lines || !lines.after || lines.missing > 0) return null;
  return { free: lines.held ? lines.head.params.available : null, after: lines.after.params.after };
}
