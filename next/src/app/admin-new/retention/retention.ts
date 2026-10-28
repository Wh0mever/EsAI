/**
 * «Возвраты» в админке: контракт с сервером и вся чистая логика страницы.
 *
 *   GET manage/retention/?days=30|90 → отчёт (core/adminapi, F29_RETENTION_SPEC «API»)
 *
 * Бэкенд пишется параллельно, а прод может оказаться старее фронта, поэтому
 * ответ разбираем как «чужие руки»: нет ключа, число строкой, лишняя неделя в
 * когорте — страница всё равно рисуется, недостающее показываем пустым («—»),
 * а не нулём там, где ноль соврал бы. Модуль без React и сети — его
 * проверяет retention.test.mjs.
 */

export const PERIODS = [30, 90] as const;
export type Period = (typeof PERIODS)[number];

/** Сколько недель после регистрации показывает таблица когорт (столбцы «Неделя 1…8»). */
export const COHORT_WEEKS = 8;
/** Окна «Вернулись после регистрации» — в этом порядке идут плитки. */
export const WITHIN_DAYS = [1, 7, 30] as const;

export const retentionPath = (days: Period): string => `manage/retention/?days=${days}`;

/** Период из чего угодно: всё, кроме 90, — 30 (как и сервер: невалидный days → 30). */
export function toPeriod(value: unknown): Period {
  return Number(value) === 90 ? 90 : 30;
}

/* ------------------------------------------------------------------ */
/* Типы                                                                */
/* ------------------------------------------------------------------ */

export type Kpi = {
  dau: number;
  wau: number;
  mau: number;
  /** Проценты — null, когда считать не из чего (0 активных): «—», а не «0%». */
  stickiness: number | null;
  new: number;
  active: number;
  returning: number;
  returningShare: number | null;
  returnedEverShare: number | null;
  returnedEver: number;
};

export type ReturnedWithin = { days: number; base: number; returned: number; share: number | null };
export type DailyRow = { date: string; active: number; new: number; returning: number };
export type CohortWeek = { k: number; share: number | null; eligible: number; returned: number };
export type Cohort = { weekStart: string; size: number; weeks: CohortWeek[] };
export type Payers = { paying: number; repeat: number; repeatShare: number | null };

export type Retention = {
  generatedAt: string | null;
  today: string | null;
  days: Period;
  exactSince: string | null;
  historySince: string | null;
  usersTotal: number;
  kpi: Kpi;
  /** Всегда три окна 1/7/30 в этом порядке, даже если сервер прислал не все. */
  returnedWithin: ReturnedWithin[];
  /** По возрастанию даты. */
  daily: DailyRow[];
  /** От новых недель к старым; в каждой ровно COHORT_WEEKS недель k = 1…8. */
  cohorts: Cohort[];
  payers: Payers;
};

/* ------------------------------------------------------------------ */
/* Разбор ответа                                                       */
/* ------------------------------------------------------------------ */

type Row = Record<string, unknown>;
const isRow = (v: unknown): v is Row => typeof v === "object" && v !== null && !Array.isArray(v);
const rowOf = (v: unknown): Row => (isRow(v) ? v : {});
const listOf = (v: unknown): unknown[] => (Array.isArray(v) ? v : []);

/** Счётчик людей: целое ≥ 0. Мусор и отрицательное — 0 (столбик в минус не уйдёт). */
export function count(v: unknown): number {
  const n = typeof v === "string" && v.trim() !== "" ? Number(v) : v;
  return typeof n === "number" && Number.isFinite(n) && n > 0 ? Math.round(n) : 0;
}

/** Доля в процентах с 1 знаком, в пределах 0…100; нет числа — null («—» на экране). */
export function share(v: unknown): number | null {
  if (v === null || v === undefined || v === "") return null;
  const n = Number(v);
  if (!Number.isFinite(n)) return null;
  return Math.round(Math.min(100, Math.max(0, n)) * 10) / 10;
}

const DATE_RE = /^\d{4}-\d{2}-\d{2}$/;
/** Дата «YYYY-MM-DD» (локальная дата Бишкека с сервера) или null. */
export function isoDay(v: unknown): string | null {
  if (typeof v !== "string") return null;
  const day = v.slice(0, 10);
  if (!DATE_RE.test(day)) return null;
  // «2026-02-31» строку проходит, а датой не является — такие отбрасываем.
  const [y, m, d] = day.split("-").map(Number);
  const probe = new Date(Date.UTC(y, m - 1, d));
  return probe.getUTCFullYear() === y && probe.getUTCMonth() === m - 1 && probe.getUTCDate() === d ? day : null;
}

function parseKpi(raw: unknown): Kpi {
  const r = rowOf(raw);
  return {
    dau: count(r.dau),
    wau: count(r.wau),
    mau: count(r.mau),
    stickiness: share(r.stickiness),
    new: count(r.new),
    active: count(r.active),
    returning: count(r.returning),
    returningShare: share(r.returning_share),
    returnedEverShare: share(r.returned_ever_share),
    returnedEver: count(r.returned_ever),
  };
}

function parseWithin(raw: unknown): ReturnedWithin[] {
  const rows = listOf(raw).filter(isRow);
  // Ищем окно по полю days, а не по позиции: старый сервер мог прислать
  // окна в другом порядке или не все — плитка тогда пустая, а не чужая.
  return WITHIN_DAYS.map((days) => {
    const r = rows.find((row) => Number(row.days) === days);
    return r
      ? { days, base: count(r.base), returned: count(r.returned), share: share(r.share) }
      : { days, base: 0, returned: 0, share: null };
  });
}

function parseDaily(raw: unknown): DailyRow[] {
  const seen = new Set<string>();
  const rows: DailyRow[] = [];
  for (const item of listOf(raw)) {
    const r = rowOf(item);
    const date = isoDay(r.date);
    if (!date || seen.has(date)) continue;
    seen.add(date);
    const active = count(r.active);
    const fresh = count(r.new);
    // returning = active − new по определению; если сервер его не прислал,
    // выводим сами, а не рисуем столбик из одних «новых».
    const returning = r.returning === undefined || r.returning === null ? Math.max(0, active - fresh) : count(r.returning);
    rows.push({ date, active, new: fresh, returning });
  }
  // ISO-даты сравниваются как строки; порядок нужен графику (слева старое).
  return rows.sort((a, b) => (a.date < b.date ? -1 : a.date > b.date ? 1 : 0));
}

function parseCohortWeeks(raw: unknown): CohortWeek[] {
  const rows = listOf(raw);
  return Array.from({ length: COHORT_WEEKS }, (_, i) => {
    const k = i + 1;
    // Неделю узнаём по k; без k — по месту в списке (k-я по счёту).
    const byK = rows.find((row) => isRow(row) && Number(row.k) === k);
    const atPos = rows[i];
    const byPos = isRow(atPos) && atPos.k === undefined ? atPos : undefined;
    const r = rowOf(byK ?? byPos);
    return { k, share: share(r.share), eligible: count(r.eligible), returned: count(r.returned) };
  });
}

function parseCohorts(raw: unknown): Cohort[] {
  const seen = new Set<string>();
  const out: Cohort[] = [];
  for (const item of listOf(raw)) {
    const r = rowOf(item);
    const weekStart = isoDay(r.week_start);
    if (!weekStart || seen.has(weekStart)) continue;
    seen.add(weekStart);
    out.push({ weekStart, size: count(r.size), weeks: parseCohortWeeks(r.weeks) });
  }
  // Сверху — свежие недели: на них смотрят в первую очередь.
  return out.sort((a, b) => (a.weekStart < b.weekStart ? 1 : a.weekStart > b.weekStart ? -1 : 0));
}

function parsePayers(raw: unknown): Payers {
  const r = rowOf(raw);
  return { paying: count(r.paying), repeat: count(r.repeat), repeatShare: share(r.repeat_share) };
}

/**
 * Отчёт из ответа сервера. null — только если ответ вообще не объект
 * (HTML-страница 502, пустое тело): тогда показываем ошибку, а не пустой отчёт.
 */
export function parseRetention(raw: unknown): Retention | null {
  if (!isRow(raw)) return null;
  return {
    generatedAt: typeof raw.generated_at === "string" && raw.generated_at ? raw.generated_at : null,
    today: isoDay(raw.today),
    days: toPeriod(raw.days),
    exactSince: isoDay(raw.exact_since),
    historySince: isoDay(raw.history_since),
    usersTotal: count(raw.users_total),
    kpi: parseKpi(raw.kpi),
    returnedWithin: parseWithin(raw.returned_within),
    daily: parseDaily(raw.daily),
    cohorts: parseCohorts(raw.cohorts),
    payers: parsePayers(raw.payers),
  };
}

/** Текст ошибки загрузки: что сказал сервер, иначе — человеческое объяснение по статусу. */
export function errorText(res: { status: number; data?: unknown }): string {
  if (res.status === 0) return "Нет связи с сервером. Проверьте интернет и повторите.";
  const data = isRow(res.data) ? res.data : null;
  const told = data && typeof data.detail === "string" ? data.detail.trim() : "";
  if (told) return told;
  // 404 — фронт выложен раньше бэкенда: отчёта на сервере ещё нет.
  if (res.status === 404) return "На сервере ещё нет отчёта «Возвраты» — нужно обновить бэкенд.";
  if (res.status >= 200 && res.status < 300) return "Сервер прислал отчёт в непонятном виде.";
  return `Не удалось загрузить отчёт (HTTP ${res.status})`;
}

/* ------------------------------------------------------------------ */
/* Формат                                                              */
/* ------------------------------------------------------------------ */

/** 1 234 — с разделителем разрядов, как в остальной админке. */
export const fmtNum = (n: number): string => count(n).toLocaleString("ru-RU");

/** «12,5%» / «40%»; нет доли — «—». */
export function fmtPct(p: number | null): string {
  if (p === null || !Number.isFinite(p)) return "—";
  return `${p.toLocaleString("ru-RU", { maximumFractionDigits: 1 })}%`;
}

/** Подпись оси: от тысячи — коротко («1,2 тыс.»), иначе как есть. */
export function fmtCompact(n: number): string {
  if (n >= 1000) return `${(n / 1000).toLocaleString("ru-RU", { maximumFractionDigits: 1 })} тыс.`;
  return fmtNum(n);
}

// Дату с сервера показываем как календарную, без часового пояса браузера:
// «2026-10-13» в UTC — это 13 октября у всех, а new Date("2026-10-13")
// у админа западнее Гринвича превратился бы в 12-е.
function utcDate(day: string): Date | null {
  const ok = isoDay(day);
  if (!ok) return null;
  const [y, m, d] = ok.split("-").map(Number);
  return new Date(Date.UTC(y, m - 1, d));
}

// ICU пишет «28 окт. 2026 г.»: точку сокращения и «г.» убираем, неразрывные
// пробелы делаем обычными — в подписях это выглядит чище и одинаково везде.
// «г.» срезаем только отдельным словом: иначе «31 авг.» превращался в «31 ав».
const tidy = (s: string): string =>
  s
    .replace(/\s+г\.?$/u, "")
    .replace(/\./g, "")
    .replace(/\s+/g, " ")
    .trim();

/** «13 окт» — подпись оси и строки когорты. */
export function fmtDayShort(day: string): string {
  const d = utcDate(day);
  return d ? tidy(d.toLocaleDateString("ru-RU", { day: "numeric", month: "short", timeZone: "UTC" })) : day;
}

/** «28 окт 2026» — дата в пояснении («точный учёт — с …»). */
export function fmtDayFull(day: string): string {
  const d = utcDate(day);
  return d
    ? tidy(d.toLocaleDateString("ru-RU", { day: "numeric", month: "short", year: "numeric", timeZone: "UTC" }))
    : day;
}

/** «ср, 28 окт» — заголовок подсказки столбика: день недели объясняет провалы на выходных. */
export function fmtDayWeekday(day: string): string {
  const d = utcDate(day);
  return d
    ? tidy(d.toLocaleDateString("ru-RU", { weekday: "short", day: "numeric", month: "short", timeZone: "UTC" }))
    : day;
}

/** Время расчёта отчёта по Бишкеку («19:05»): дни в отчёте — тоже бишкекские. */
export function fmtTime(iso: string | null): string | null {
  if (!iso) return null;
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return null;
  return d.toLocaleTimeString("ru-RU", { hour: "2-digit", minute: "2-digit", timeZone: "Asia/Bishkek" });
}

/** Русское множественное: plural(5, ["человек", "человека", "человек"]) → «человек». */
export function plural(n: number, forms: readonly [string, string, string]): string {
  const a = Math.abs(Math.trunc(n)) % 100;
  const b = a % 10;
  if (a > 10 && a < 20) return forms[2];
  if (b === 1) return forms[0];
  if (b >= 2 && b <= 4) return forms[1];
  return forms[2];
}

export const PEOPLE = ["человек", "человека", "человек"] as const;

/**
 * Пояснение «как считаем» — дословно из спецификации. Пока живых строк нет
 * (exact_since = null, первые минуты после выкладки), дата заменяется словами.
 */
export function methodNote(exactSince: string | null, historySince: string | null = null): string {
  const since = exactSince ? `с ${fmtDayFull(exactSince)}` : "с момента выкладки";
  const from = historySince ? `Данные о заходах есть с ${fmtDayFull(historySince)}. ` : "";
  return (
    "Человек считается активным в день, если заходил на сайт (вход или продление сессии), " +
    "тратил кредиты, оплачивал или что-то создавал. " +
    `Точный учёт каждого захода — ${since}; до этого — по входам, продлениям сессии ` +
    "(не чаще раза в 12 часов), тратам, оплатам и созданным проектам. " +
    from +
    "Сотрудники, тестовый аккаунт, заблокированные и объединённые аккаунты не учитываются."
  );
}

/** Сколько дней истории нужно, чтобы доли «вернулись в течение 30 дней» и когорты не врали. */
export const HISTORY_ENOUGH_DAYS = 30;

/**
 * Предупреждение, что история заходов ещё не загружена: без разовой загрузки
 * истории (backfill) в таблице только последние дни, и доли возвратов почти
 * нулевые — показывать их фонду без оговорки нельзя. null — всё в порядке.
 */
export function historyWarning(historySince: string | null, today: string | null): string | null {
  const text = "История заходов ещё не загружена — доли возвратов пока занижены.";
  if (!historySince) return text;
  const from = utcDate(historySince);
  const now = today ? utcDate(today) : null;
  if (!from || !now) return null;
  const days = Math.round((now.getTime() - from.getTime()) / 86_400_000);
  return days < HISTORY_ENOUGH_DAYS ? text : null;
}

/* ------------------------------------------------------------------ */
/* График «Активные по дням»                                           */
/* ------------------------------------------------------------------ */

/** Высота столбика: сумма частей, но не меньше active (если сервер разошёлся сам с собой). */
export const barTotal = (row: DailyRow): number => Math.max(row.active, row.new + row.returning);

/**
 * Шкала оси Y по круглым числам: верх и деления (0 / 10 / 20 …), не больше
 * maxParts промежутков. Берём самый мелкий круглый шаг, который укладывается:
 * так верх шкалы ближе к пику и столбики не прижаты к низу.
 * Шаг — 1, 2, 5 × 10ⁿ (2,5 — только от десятков) и не меньше 1: людей дробно не бывает.
 */
export function chartScale(max: number, maxParts = 5): { top: number; ticks: number[] } {
  const peak = Math.max(0, Number.isFinite(max) ? max : 0);
  if (peak === 0) return { top: 1, ticks: [0, 1] };
  const step = niceStep(peak, maxParts);
  const top = Math.ceil(peak / step) * step;
  const ticks: number[] = [];
  for (let v = 0; v <= top; v += step) ticks.push(v);
  return { top, ticks };
}

function niceStep(peak: number, maxParts: number): number {
  const first = 10 ** Math.floor(Math.log10(peak / maxParts));
  // Подходящий шаг всегда найдётся в пределах двух порядков от первой прикидки.
  for (const mag of [first, first * 10, first * 100]) {
    for (const m of mag >= 10 ? [1, 2, 2.5, 5, 10] : [1, 2, 5, 10]) {
      const step = Math.round(m * mag * 1000) / 1000;
      if (step >= 1 && Math.ceil(peak / step) <= maxParts) return step;
    }
  }
  return Math.max(1, Math.ceil(peak / maxParts));
}

/**
 * Каких столбиков подписывать дату: не больше maxTicks, шаг от последнего дня
 * (сегодня подписан всегда). На 90 столбиках — примерно раз в две недели.
 */
export function tickIndexes(n: number, maxTicks = 6): number[] {
  if (n <= 0) return [];
  const step = Math.max(1, Math.ceil(n / Math.max(1, maxTicks)));
  const out: number[] = [];
  for (let i = n - 1; i >= 0; i -= step) out.unshift(i);
  return out;
}

/**
 * Как прижать подпись (и подсказку) к столбику i из n: у краёв — к краю,
 * иначе по центру. Центр у крайнего столбика вылез бы за карточку.
 */
export function edgeAlign(i: number, n: number): "start" | "center" | "end" {
  if (n <= 1) return "center";
  const pos = (i + 0.5) / n;
  if (pos < 0.15) return "start";
  if (pos > 0.85) return "end";
  return "center";
}

/** Индекс столбика под указателем: x — от левого края области, width — её ширина. */
export function barAt(x: number, width: number, n: number): number | null {
  if (n <= 0 || !(width > 0) || !Number.isFinite(x)) return null;
  return Math.min(n - 1, Math.max(0, Math.floor((x / width) * n)));
}

/* ------------------------------------------------------------------ */
/* Таблица когорт                                                      */
/* ------------------------------------------------------------------ */

/**
 * Подложка ячейки по доле: непрозрачность акцентного цвета 0…0.9.
 * Корень, а не прямая: удержание обычно 2–20%, и по прямой почти вся таблица
 * была бы одинаково бледной. strong — подложка такая яркая, что светлый текст
 * на ней не читается: тогда текст берём тёмный (--on-accent).
 */
export function cohortShade(p: number | null): { alpha: number; strong: boolean } | null {
  if (p === null || !Number.isFinite(p)) return null;
  const v = Math.min(100, Math.max(0, p));
  if (v === 0) return { alpha: 0, strong: false };
  const alpha = Math.round((0.08 + 0.82 * Math.sqrt(v / 100)) * 100) / 100;
  return { alpha, strong: alpha >= 0.55 };
}

/** CSS-фон ячейки: акцент сайта с прозрачностью — одинаково в тёмной и светлой теме. */
export const shadeBackground = (alpha: number): string =>
  alpha > 0 ? `color-mix(in srgb, var(--accent) ${Math.round(alpha * 100)}%, transparent)` : "transparent";

/** Подсказка ячейки: из скольких посчитано, если неделя прошла ещё не у всех. */
export function cohortCellTitle(week: CohortWeek, size: number): string {
  if (size === 0) return "в эту неделю никто не регистрировался";
  if (week.share === null) return "неделя ещё не прошла";
  const base = `Неделя ${week.k}: вернулись ${fmtNum(week.returned)} из ${fmtNum(week.eligible)} (${fmtPct(week.share)})`;
  return week.eligible < size
    ? `${base}. У остальных ${fmtNum(size - week.eligible)} неделя ещё не прошла`
    : base;
}
