/**
 * Какой пакет кредитов показать первым.
 *
 * Человек нажал «Снять» или «Создать», а кредитов не хватило. Сколько именно
 * не хватает, студия уже знает, — значит, первым показываем самый дешёвый
 * пакет, которого на эту операцию хватит. Пролистывать карусель в поисках
 * подходящего ему не нужно.
 *
 * Логика общая для мультстудии и видеостудии, поэтому живёт здесь, без React.
 */

export type PickPkg = {
  id: number | string;
  tokens: number;
  bonus_tokens?: number;
  price: number;
};

/** Сколько кредитов начислит пакет: основные плюс бонусные. */
export function packageCredits(p: PickPkg): number {
  return (Number(p.tokens) || 0) + (Number(p.bonus_tokens) || 0);
}

/** Сколько не хватает: цена операции минус баланс, не меньше нуля. */
export function shortfall(cost: number, balance: number): number {
  const c = Number(cost) || 0;
  const b = Number(balance) || 0;
  return Math.max(0, Math.ceil(c - b));
}

/**
 * Самый дешёвый пакет, которого хватит, чтобы покрыть нехватку.
 * Ничего не хватает — самый большой пакет: он ближе всего к цели.
 * null — нехватки нет или пакетов нет: тогда показываем первый по порядку.
 */
export function recommendPackage<P extends PickPkg>(packages: P[], missing: number | null | undefined): P | null {
  const need = Number(missing) || 0;
  if (need <= 0 || packages.length === 0) return null;
  const enough = packages.filter((p) => packageCredits(p) >= need);
  if (enough.length > 0) {
    return enough.reduce((best, p) => {
      const price = Number(p.price) || 0;
      const bestPrice = Number(best.price) || 0;
      if (price !== bestPrice) return price < bestPrice ? p : best;
      // При равной цене — тот, где кредитов больше.
      return packageCredits(p) > packageCredits(best) ? p : best;
    });
  }
  return packages.reduce((best, p) => (packageCredits(p) > packageCredits(best) ? p : best));
}

/**
 * Откуда открыли пополнение: ?need=12&cost=63&for=scene в адресе тарифов
 * мультстудии. Мусор в адресе превращается в «ничего не выбрано».
 */
export type NeedFor = "scene" | "character" | "audio" | "generation";

export type PackageNeed = {
  /** сколько кредитов не хватает */
  missing: number;
  /** сколько стоит сама операция; 0 — неизвестно */
  cost: number;
  for: NeedFor;
};

const NEED_FOR: NeedFor[] = ["scene", "character", "audio", "generation"];

export function parseNeed(search: string): PackageNeed | null {
  const q = new URLSearchParams(search);
  const missing = Math.floor(Number(q.get("need")));
  if (!Number.isFinite(missing) || missing <= 0 || missing > 10_000_000) return null;
  const rawCost = Math.floor(Number(q.get("cost")));
  const cost = Number.isFinite(rawCost) && rawCost >= missing ? rawCost : 0;
  const f = q.get("for") as NeedFor | null;
  return { missing, cost, for: f && NEED_FOR.includes(f) ? f : "generation" };
}

/** Адрес тарифов с нехваткой: обратная сторона parseNeed. */
export function needHref(base: string, cost: number, balance: number, kind: NeedFor): string {
  const missing = shortfall(cost, balance);
  if (missing <= 0) return base;
  const q = new URLSearchParams({ need: String(missing), cost: String(Math.ceil(Number(cost) || 0)), for: kind });
  return `${base}${base.includes("?") ? "&" : "?"}${q.toString()}`;
}
