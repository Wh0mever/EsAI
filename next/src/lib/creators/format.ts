/**
 * EsAI Creators: показ денег, чисел и дат; простые проверки формы.
 *
 * Деньги приходят строками и строками остаются: здесь их только расставляют
 * по разрядам. Арифметики над деньгами в браузере нет — единственная
 * операция, сравнение (cmpDec), нужна для подсказок интерфейса; решает сервер.
 */
import { apiLang } from "@/lib/apiLang";

/** Пункты меню и карта сайта — только когда программа открыта всем (вшивается при сборке). */
export const CREATORS_NAV = process.env.NEXT_PUBLIC_CREATORS_NAV === "1";

const NBSP = " ";
const DECIMAL_RE = /^([+-]?)(\d*)(?:\.(\d*))?$/;

/** "8460.00" → "8 460.00": разряды неразрывным пробелом, знаки после точки — как прислал сервер. */
export function fmtUsdt(v: string | null | undefined): string {
  const raw = String(v ?? "").trim();
  if (!raw) return "0.00";
  const m = /^(-?)(\d+)(\.\d+)?$/.exec(raw);
  // Не число — показываем как есть: переформатировать чужую строку нельзя.
  if (!m) return raw;
  const int = m[2].replace(/^0+(?=\d)/, "").replace(/\B(?=(\d{3})+(?!\d))/g, NBSP);
  return `${m[1]}${int}${m[3] || ""}`;
}

/** "15.00" → "15", "12.50" → "12.5" (без знака %). */
export function fmtPercent(v: string | null | undefined): string {
  const raw = String(v ?? "").trim();
  if (!raw) return "0";
  if (!/^-?\d+(\.\d+)?$/.test(raw)) return raw;
  return raw.includes(".") ? raw.replace(/0+$/, "").replace(/\.$/, "") : raw;
}

function localeOf(lang: string | null | undefined): string {
  // ru и kg — русский формат чисел и дат; «ky» из i18n приводим к kg.
  return apiLang(lang) === "en" ? "en-US" : "ru-RU";
}

export function fmtInt(n: number | null | undefined, lang?: string | null): string {
  const value = Number(n ?? 0);
  if (!Number.isFinite(value)) return "0";
  try {
    return new Intl.NumberFormat(localeOf(lang), { maximumFractionDigits: 0 }).format(value);
  } catch {
    return String(Math.trunc(value));
  }
}

function fmtWith(iso: string | null | undefined, lang: string | null | undefined, options: Intl.DateTimeFormatOptions): string {
  if (!iso) return "";
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return String(iso);
  try {
    return date.toLocaleString(localeOf(lang), options);
  } catch {
    return String(iso);
  }
}

/** Дата: 05.10.2026 (ru, kg) или 10/05/2026 (en). */
export function fmtDate(iso: string | null | undefined, lang?: string | null): string {
  return fmtWith(iso, lang, { day: "2-digit", month: "2-digit", year: "numeric" });
}

/** Дата и время до минут. */
export function fmtDateTime(iso: string | null | undefined, lang?: string | null): string {
  return fmtWith(iso, lang, { day: "2-digit", month: "2-digit", year: "numeric", hour: "2-digit", minute: "2-digit" });
}

/**
 * Сравнение десятичных строк: -1, 0 или 1. Дробные части выравниваются
 * нулями, дальше сравниваются целые (BigInt) — без плавающей точки.
 * Только сравнение; не число — считается нулём.
 */
export function cmpDec(a: string | null | undefined, b: string | null | undefined): -1 | 0 | 1 {
  const parse = (v: string | null | undefined) => {
    const m = DECIMAL_RE.exec(String(v ?? "").trim());
    if (!m || (!m[2] && !m[3])) return { neg: false, int: "0", frac: "" };
    return { neg: m[1] === "-", int: m[2] || "0", frac: m[3] || "" };
  };
  const x = parse(a);
  const y = parse(b);
  const scale = Math.max(x.frac.length, y.frac.length);
  const digits = (p: { int: string; frac: string }) => (p.int + p.frac.padEnd(scale, "0")).replace(/^0+(?=\d)/, "");
  const dx = digits(x);
  const dy = digits(y);

  if (typeof BigInt === "function") {
    const bx = BigInt(dx) * (x.neg ? BigInt(-1) : BigInt(1));
    const by = BigInt(dy) * (y.neg ? BigInt(-1) : BigInt(1));
    return bx < by ? -1 : bx > by ? 1 : 0;
  }
  // Старый webview без BigInt: строки цифр одной длины сравниваются как числа.
  const sx = x.neg && dx !== "0" ? -1 : 1;
  const sy = y.neg && dy !== "0" ? -1 : 1;
  if (sx !== sy) return sx < sy ? -1 : 1;
  const magnitude = dx.length !== dy.length ? (dx.length < dy.length ? -1 : 1) : dx < dy ? -1 : dx > dy ? 1 : 0;
  return (sx < 0 ? -magnitude : magnitude) as -1 | 0 | 1;
}

/**
 * Наибольший процент комиссии среди уровней — для «до {{max}}%»: "25.00" → "25".
 * Уровней нет (ответ ещё не пришёл) — 25, как в условиях программы.
 */
export function maxLevelPercent(levels: readonly { percent: string }[] | null | undefined): string {
  let max: string | null = null;
  for (const level of levels || []) {
    if (max === null || cmpDec(level.percent, max) > 0) max = level.percent;
  }
  return max === null ? "25" : fmtPercent(max);
}

/** "https://esai.kg/?ref=TORA20" → "esai.kg/?ref=TORA20": на экране, копируется полная ссылка. */
export function displayLink(url: string | null | undefined): string {
  return String(url ?? "").trim().replace(/^https?:\/\//i, "");
}

/** Похоже на адрес TRON (T + 33 символа base58). Только форма: контрольную сумму проверяет сервер. */
export function isTronAddressShape(s: string | null | undefined): boolean {
  return /^T[1-9A-HJ-NP-Za-km-z]{33}$/.test(String(s ?? "").trim());
}

/** Форма промокода креатора: 4–16 символов, латинские буквы и цифры, первой идёт буква. */
export function isCodeShape(s: string | null | undefined): boolean {
  return /^[A-Z][A-Z0-9]{3,15}$/.test(String(s ?? ""));
}

/** Текст поля «по одной ссылке в строке» → список непустых строк. */
export function splitLinks(text: string | null | undefined): string[] {
  return String(text ?? "")
    .split(/\s+/)
    .map((s) => s.trim())
    .filter(Boolean);
}

/** Ссылка начинается с http:// или https:// и разбирается как адрес. */
export function isHttpUrl(s: string | null | undefined): boolean {
  const value = String(s ?? "").trim();
  if (!/^https?:\/\/\S+$/i.test(value)) return false;
  try {
    return Boolean(new URL(value).hostname);
  } catch {
    return false;
  }
}
