export type Currency = "USD" | "RUB" | "KGS";

/**
 * Приоритет источника валюты (задача клиента: вернуть переключатель KGS/RUB
 * для ЮKassa, авто-детект по геолокации IP, но ручной выбор пользователя
 * ВСЕГДА должен перебивать авто — многие пользуются VPN).
 *
 *   "manual" — пользователь явно щёлкнул переключатель (CurrencySwitch) —
 *              залипает навсегда, пока не переключит ещё раз.
 *   "auto"   — определено автоматически (геолокация IP через бэкенд,
 *              GET /api/plans/currency-rate/ -> suggested_currency) —
 *              может быть переопределено следующим авто-детектом.
 */
export type CurrencySource = "manual" | "auto";

/**
 * Способ оплаты в сомах, который человек выбирает у нас
 * (core/payments/kgs_methods.py). kind решает, в какой группе окна выбора
 * окажется кнопка: «по QR» (свой экран оплаты, GoPay), «через приложение
 * банка» или «картой» (оба — страница Freedom Pay).
 */
export type KgsMethodKey = "elqr" | "mbank" | "odengi" | "balance" | "megapay" | "card";
export type KgsMethodKind = "qr" | "app" | "card";
/**
 * test — способ работает в тестовом окружении платёжной системы (единый QR на
 * тестовых ключах GoPay): его видят только сотрудники, и кнопка помечена.
 */
export type KgsMethod = { key: KgsMethodKey; kind: KgsMethodKind; test?: boolean };

/** Ключи, которые знает клиент, в порядке показа. Незнакомый ключ с сервера отбрасываем. */
export const KGS_METHOD_KEYS: KgsMethodKey[] = ["elqr", "mbank", "odengi", "balance", "megapay", "card"];

/**
 * Разбор kgs_methods из ответа сервера. Порядок — серверный (он и есть порядок
 * показа); всё, чего клиент не знает, выкидываем: кнопку без подписи рисовать
 * нечем, а старый сервер без этого поля даёт пустой список — и витрина ведёт
 * себя как раньше.
 */
export function parseKgsMethods(raw: unknown): KgsMethod[] {
  if (!Array.isArray(raw)) return [];
  const out: KgsMethod[] = [];
  for (const item of raw) {
    const key = (item as { key?: unknown } | null)?.key;
    const kind = (item as { kind?: unknown } | null)?.kind;
    if (!KGS_METHOD_KEYS.includes(key as KgsMethodKey)) continue;
    if (kind !== "qr" && kind !== "app" && kind !== "card") continue;
    if (out.some((m) => m.key === key)) continue;
    // Пометку «тест» ставим только по явному true: всё остальное — боевой способ.
    const test = (item as { test?: unknown } | null)?.test === true;
    out.push(test ? { key: key as KgsMethodKey, kind, test: true } : { key: key as KgsMethodKey, kind });
  }
  return out;
}

/** Ответ бэкенда GET /api/plans/currency-rate/ (core/plans/views.py CurrencyRateView). */
export type CurrencyRateResponse = {
  base_currency: "KGS";
  rate_kgs_to_rub: number;
  /**
   * Курс сом -> доллар. В отличие от рублёвого он ПЛАТЁЖНЫЙ: по нему
   * выставляется криптосчёт, поэтому показанная цена и есть та, что человек
   * переведёт (сервер фиксирует её в момент создания счёта).
   */
  rate_kgs_to_usd: number;
  /** доступна ли оплата криптой этому человеку (режим off/staff/on) */
  crypto_enabled: boolean;
  suggested_currency: "KGS" | "RUB";
  /**
   * Способы оплаты в сомах для окна выбора, в порядке показа. Пустой список —
   * выбора нет (режим выключен или не для этого человека): «Пополнить» сразу
   * уводит на страницу Freedom Pay, как раньше.
   */
  kgs_methods?: KgsMethod[];
};

// Фолбэк-курс, если запрос к бэкенду не удался (сеть/CORS/сервер лежит) —
// используется ТОЛЬКО как временная заглушка на клиенте, реальный курс
// (админ-настраиваемый, core/adminapi settings) отдаёт /api/plans/currency-rate/.
// НЕ обновлять вручную под "актуальный курс" — редактировать курс нужно в
// админке (Настройки -> Валюта), это значение — просто чтобы UI не сломался
// при недоступности бэкенда.
export const FALLBACK_KGS_TO_RUB_RATE = 0.95;
// Тот же смысл, что и у рублёвого фолбэка: заглушка на случай, когда бэкенд
// недоступен. Настоящий курс приходит с /api/plans/currency-rate/.
export const FALLBACK_KGS_TO_USD_RATE = 0.0115;

function readCookie(name: string): string | null {
  if (typeof document === "undefined") return null;
  const match = document.cookie.match(new RegExp("(?:^|; )" + name.replace(/([.$?*|{}()\[\]\\\/\+^])/g, "\\$1") + "=([^;]*)"));
  return match ? decodeURIComponent(match[1]) : null;
}

function currencyFromHost(hostname: string | undefined | null): Currency {
  const h = (hostname || "").toLowerCase();
  // EsAI — единственный домен esai.kg, дефолт на "холодном" визите — сом.
  if (h.endsWith("esai.kg")) return "KGS";
  return "KGS"; // kg by default (ТЗ)
}

/**
 * Валюта для ПЕРВОГО рендера (синхронно, до ответа /api/plans/currency-rate/):
 * ручной выбор (если есть) -> ранее сохранённая (cookie/localStorage, в т.ч.
 * прошлый авто-детект) -> дефолт по домену (KGS). Геолокация IP асинхронна —
 * см. useCurrency() (next/src/hooks/useCurrency.ts), который может обновить
 * валюту сразу после монтирования, если авто-выбор ещё не зафиксирован.
 */
export function getInitialCurrency(): Currency {
  if (typeof window === "undefined") return "KGS";
  const manualCookie = readCookie("APP_CURRENCY_MANUAL");
  const ls = (() => { try { return window.localStorage.getItem("APP_CURRENCY"); } catch { return null; } })();
  const ck = readCookie("APP_CURRENCY");

  const isManual = manualCookie === "1";
  if (isManual && (ls === "USD" || ls === "RUB" || ls === "KGS")) return ls as Currency;

  if (ck === "USD" || ck === "RUB" || ck === "KGS") return ck as Currency;

  return currencyFromHost(window.location.hostname);
}

/**
 * Сохранить валюту. markManual=true (по умолчанию) — пользователь выбрал
 * ЯВНО (клик по CurrencySwitch): пишет и APP_CURRENCY_SOURCE=manual, и
 * legacy-флаг APP_CURRENCY_MANUAL=1 (совместимость с getInitialCurrency()
 * и middleware.ts, которые проверяют именно его). markManual=false —
 * авто-детект (гео IP): валюта сохраняется (переживает навигацию/reload),
 * но источник остаётся "auto" — следующий авто-детект (например, при смене
 * IP/VPN) вправе её снова изменить, а ручной выбор пользователя как только
 * произойдёт — навсегда выигрывает у авто.
 */
export function persistCurrency(code: Currency, markManual = true) {
  if (typeof window !== "undefined") {
    try { window.localStorage.setItem("APP_CURRENCY", code); } catch {}
    try { window.localStorage.setItem("APP_CURRENCY_SOURCE", markManual ? "manual" : "auto"); } catch {}
    try { document.cookie = `APP_CURRENCY=${code}; path=/; max-age=${60 * 60 * 24 * 365}`; } catch {}
    try {
      if (markManual) {
        document.cookie = `APP_CURRENCY_MANUAL=1; path=/; max-age=${60 * 60 * 24 * 365}`;
      }
      // Намеренно НЕ снимаем APP_CURRENCY_MANUAL при markManual=false: если
      // пользователь уже выбирал валюту вручную раньше, авто-детект (гео)
      // не должен тихо забрать у него этот приоритет обратно.
    } catch {}
  }
}

/** Валюта была выбрана пользователем явно (а не подставлена авто-детектом). */
export function isManualCurrency(): boolean {
  if (typeof window === "undefined") return false;
  try {
    if (window.localStorage.getItem("APP_CURRENCY_SOURCE") === "manual") return true;
  } catch {}
  return readCookie("APP_CURRENCY_MANUAL") === "1";
}

/**
 * Пересчёт цены из сомов (базовая валюта всех TokenPackage.price) в текущую
 * отображаемую валюту. USD не поддержан (переключателя USD в UI нет) —
 * возвращает цену в сомах без изменений как безопасный фолбэк.
 *
 * ⚠️ Только для ОТОБРАЖЕНИЯ. Реальная оплата (POST /api/plans/purchase/)
 * всегда списывается в сомах по TokenPackage.currency на бэкенде — этот
 * пересчёт не участвует в платеже никак.
 */
export function convertFromKgs(
  priceKgs: number,
  currency: Currency,
  rateKgsToRub: number,
  rateKgsToUsd?: number
): number {
  // API отдаёт цену пакета строкой-десятичной («490.00»): без приведения сомы
  // уходили на витрину как есть — «490.00 сом», «1990.00 сом».
  priceKgs = Number(priceKgs) || 0;
  if (currency === "RUB") {
    const rate = Number.isFinite(rateKgsToRub) && rateKgsToRub > 0 ? rateKgsToRub : FALLBACK_KGS_TO_RUB_RATE;
    return Math.round(priceKgs * rate * 100) / 100;
  }
  if (currency === "USD") {
    const rate =
      Number.isFinite(rateKgsToUsd as number) && (rateKgsToUsd as number) > 0
        ? (rateKgsToUsd as number)
        : FALLBACK_KGS_TO_USD_RATE;
    return Math.round(priceKgs * rate * 100) / 100;
  }
  return priceKgs;
}

/**
 * Цена с подписью валюты. Вынесено сюда, потому что раньше каждая витрина
 * склеивала её сама («₽», «сом»), и доллар пришлось бы дописывать в четырёх
 * местах по-разному.
 */
export function formatPrice(value: number, currency: Currency, somLabel = "сом"): string {
  value = Number(value) || 0;
  if (currency === "USD") {
    // Доллары показываем как в кассе: два знака и знак впереди.
    return `$${value.toFixed(2)}`;
  }
  const shown = value.toLocaleString("ru-RU");
  return currency === "RUB" ? `${shown} ₽` : `${shown} ${somLabel}`;
}
