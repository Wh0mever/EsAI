/**
 * Горизонтальные ленты первого экрана («Продолжить», чипы сценариев на
 * телефоне): чистая логика без React — с какой стороны ленте гасить край,
 * на сколько листать стрелкой и как подписать давность проекта.
 */

/* ---------- края ленты ---------- */

/**
 * none — всё помещается, гасить нечего; start — лента в начале (продолжение
 * справа); end — долистана до конца; mid — продолжение с обеих сторон.
 */
export type EdgeFade = "none" | "start" | "mid" | "end";

/** Дробные пиксели прокрутки на плотных экранах и при масштабе страницы. */
const SLACK_PX = 2;

export function edgeFade(scrollLeft: number, clientWidth: number, scrollWidth: number): EdgeFade {
  const room = scrollWidth - clientWidth;
  if (!(room > SLACK_PX)) return "none";
  if (scrollLeft <= SLACK_PX) return "start";
  if (scrollLeft >= room - SLACK_PX) return "end";
  return "mid";
}

/** Сколько прежнего содержимого остаётся на виду после шага стрелкой. */
const PAGE_KEEP_PX = 96;

/**
 * Шаг стрелки: почти экран ленты, но целым числом карточек — тогда после шага
 * карточка стоит у края ровно, а не обрезанной. pitch — расстояние между
 * началами соседних карточек; 0 — неизвестно, листаем просто на экран.
 */
export function pageStep(clientWidth: number, pitch: number): number {
  const room = Math.max(clientWidth - PAGE_KEEP_PX, clientWidth / 2);
  if (!(pitch > 0)) return Math.round(room);
  return Math.max(1, Math.floor(room / pitch)) * pitch;
}

/* ---------- давность ---------- */

const MINUTE_MS = 60_000;
const HOUR_MS = 3_600_000;
const DAY_MS = 86_400_000;
/** Дальше недели «N дней назад» читается хуже, чем дата. */
const RELATIVE_DAYS = 7;

/** Язык сайта → тег для Intl: «kg» там не киргизский, киргизский — «ky». */
const INTL_TAG: Record<string, string> = { kg: "ky" };

type WhenFormats = {
  ago: Intl.RelativeTimeFormat;
  date: Intl.DateTimeFormat;
  dateYear: Intl.DateTimeFormat;
};

const formats = new Map<string, WhenFormats | null>();

function whenFormats(lang: string): WhenFormats | null {
  const known = formats.get(lang);
  if (known !== undefined) return known;
  let made: WhenFormats | null = null;
  try {
    const want = INTL_TAG[lang] || lang || "ru";
    // Языка в браузере может не быть (киргизский в старых версиях) — тогда
    // по-русски, а не на языке системы, какой бы он ни был.
    const tag = Intl.RelativeTimeFormat.supportedLocalesOf([want]).length ? want : "ru";
    made = {
      ago: new Intl.RelativeTimeFormat(tag, { numeric: "auto" }),
      date: new Intl.DateTimeFormat(tag, { day: "numeric", month: "short" }),
      dateYear: new Intl.DateTimeFormat(tag, { day: "numeric", month: "short", year: "numeric" }),
    };
  } catch {
    made = null;
  }
  formats.set(lang, made);
  return made;
}

const dayStart = (d: Date) => new Date(d.getFullYear(), d.getMonth(), d.getDate()).getTime();

/**
 * «5 минут назад», «2 часа назад», «вчера», «12 сент.» — когда в проекте
 * последний раз что-то происходило. Слова и формы числа даёт Intl на языке
 * сайта, своих ключей перевода здесь нет. Дни считаются по календарю — так же,
 * как группы «Сегодня / Вчера» в левой колонке (store.groupProjects): проект
 * из вчерашнего вечера в час ночи — «вчера», а не «2 часа назад».
 *
 * Пустая строка — дата не разобралась, часы ещё неизвестны (nowMs = 0 на
 * сервере) или в браузере нет Intl.RelativeTimeFormat.
 */
export function lastActive(iso: string, nowMs: number, lang: string): string {
  const at = Date.parse(iso);
  if (!Number.isFinite(at) || !(nowMs > 0)) return "";
  const f = whenFormats(lang);
  if (!f) return "";
  // Часы устройства могут отставать от серверных — «через 2 минуты» не пишем.
  const ago = Math.max(0, nowMs - at);
  if (ago < MINUTE_MS) return f.ago.format(0, "second");
  if (ago < HOUR_MS) return f.ago.format(-Math.floor(ago / MINUTE_MS), "minute");
  const now = new Date(nowMs);
  const then = new Date(at);
  // round — из-за суток в 23 и 25 часов при переводе часов.
  const days = Math.round((dayStart(now) - dayStart(then)) / DAY_MS);
  if (days <= 0) return f.ago.format(-Math.floor(ago / HOUR_MS), "hour");
  if (days < RELATIVE_DAYS) return f.ago.format(-days, "day");
  return (then.getFullYear() === now.getFullYear() ? f.date : f.dateYear).format(then);
}
