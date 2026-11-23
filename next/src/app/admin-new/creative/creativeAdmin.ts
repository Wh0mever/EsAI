/**
 * «Creative Studio» в админке: весь контракт с сервером и чистая логика
 * страницы (core/creative/views_manage.py, SPEC_B §8).
 *
 *   GET   manage/creative/settings/  → режим, общая наценка, по инструментам: включён,
 *                                      своя наценка, пример себестоимости и цены
 *   PATCH manage/creative/settings/  {mode?, markup_pct?, tools?: [{id, enabled?, markup_pct?,
 *                                      use_own_markup?}]} → то же + changed
 *   GET   manage/creative/log/       → {items: [{at, actor, before, after}]} (до 200 записей)
 *   GET   manage/creative/summary/?from=ГГГГ-ММ-ДД&to=ГГГГ-ММ-ДД → сводка за период
 *
 * Деньги (наценки) меняет только главный администратор: остальным сервер
 * отвечает 403 {detail, code: "superuser_required"}. Отказы — {detail} и рядом
 * errors {поле: текст}.
 *
 * Админский JS — публичный файл: имён поставщика и его моделей здесь нет и не
 * должно быть. Подписи инструментов — наши (их присылает сервер, запасные —
 * из lib/creative/tools.ts). Модуль без React и сети — его проверяет
 * creativeAdmin.test.mjs.
 */
import { toolById } from "@/lib/creative/tools";

export const SETTINGS_PATH = "manage/creative/settings/";
export const LOG_PATH = "manage/creative/log/";
export const summaryPath = (from: string, to: string): string =>
  `manage/creative/summary/?from=${encodeURIComponent(from)}&to=${encodeURIComponent(to)}`;

export const PCT_MIN = 0;
export const PCT_MAX = 1000;
/** Сервер не даёт период длиннее года (SUMMARY_MAX_DAYS = 366). */
export const SUMMARY_MAX_DAYS = 366;
export const PERIODS = [7, 30, 90] as const;
export type Period = (typeof PERIODS)[number];

/* ------------------------------------------------------------------ */
/* Типы                                                                */
/* ------------------------------------------------------------------ */

export type Mode = "off" | "staff" | "on";
export type Kind = "image" | "video" | "character";

export type ToolExample = {
  /** «5 с, 480p» — наши слова, присылает сервер */
  label: string;
  costUsd: string | null;
  /** null — цены нет (нет пакета с ценой или себестоимость не посчиталась) */
  credits: number | null;
};

export type ToolRow = {
  id: string;
  n: number;
  name: string;
  kind: Kind | "";
  enabled: boolean;
  /** Набранная своя наценка (может лежать и при выключенном флажке). */
  ownMarkupPct: string | null;
  useOwnMarkup: boolean;
  /** С чем реально считается цена: своя или общая, но не ниже порога. */
  effectiveMarkupPct: string;
  usesGlobal: boolean;
  example: ToolExample;
};

export type Settings = {
  mode: Mode;
  modeEnv: Mode;
  /** null — действует режим из окружения */
  modeOverride: Mode | null;
  markupPct: string;
  markupDefaultPct: string;
  /** Нижний порог наценки из общих «Цен и наценки» — здесь только читаем. */
  floorPct: string;
  /** Цена самого дешёвого кредита в $; null — ни одного пакета с ценой. */
  creditUsd: string | null;
  tools: ToolRow[];
  /** Сервер сказал, можно ли менять деньги; null — не сказал (узнаем по 403). */
  canEditMoney: boolean | null;
};

export type LogEntry = {
  at: string;
  actor: string;
  before: Record<string, unknown>;
  after: Record<string, unknown>;
};

export type Money = {
  /** Выручка по текущей цене кредита; null — цены кредита нет. */
  revenueUsd: string | null;
  costUsd: string;
  marginUsd: string | null;
};

export type SummaryTool = Money & { id: string; name: string; jobs: number; done: number; credits: number };

export type JobCounts = Record<"total" | "done" | "failed" | "nsfw" | "canceled" | "lost" | "open", number>;

export type Summary = Money & {
  from: string;
  to: string;
  jobs: JobCounts;
  creditsCharged: number;
  creditUsd: string | null;
  byTool: SummaryTool[];
};

/* ------------------------------------------------------------------ */
/* Разбор ответов («как из чужих рук»)                                 */
/* ------------------------------------------------------------------ */

type Row = Record<string, unknown>;

const isRow = (v: unknown): v is Row => typeof v === "object" && v !== null && !Array.isArray(v);
const rows = (v: unknown): Row[] => (Array.isArray(v) ? v.filter(isRow) : []);
const text = (v: unknown): string => (typeof v === "string" ? v.trim() : "");
const int = (v: unknown): number | null =>
  typeof v === "number" && Number.isInteger(v) && v >= 0 ? v : null;
/** Decimal строкой ("40", "0.7700") — как отдаёт сервер; число тоже принимаем. */
const decimalText = (v: unknown): string | null => {
  if (typeof v === "number" && Number.isFinite(v)) return String(v);
  const s = text(v);
  return s && Number.isFinite(Number(s)) ? s : null;
};

const MODES: readonly Mode[] = ["off", "staff", "on"];
const asMode = (v: unknown): Mode | null => {
  const s = text(v).toLowerCase();
  return (MODES as readonly string[]).includes(s) ? (s as Mode) : null;
};
const asKind = (v: unknown): Kind | "" => (v === "image" || v === "video" || v === "character" ? v : "");

function parseTool(v: Row): ToolRow | null {
  const id = text(v.id);
  if (!id) return null;
  const example = isRow(v.example) ? v.example : {};
  const ownMarkupPct = decimalText(v.own_markup_pct);
  const useOwnMarkup = v.use_own_markup === true;
  return {
    id,
    n: int(v.n) ?? toolById(id)?.n ?? 0,
    name: text(v.name) || toolById(id)?.name || id,
    kind: asKind(v.kind),
    enabled: v.enabled !== false,
    ownMarkupPct,
    useOwnMarkup,
    effectiveMarkupPct: decimalText(v.effective_markup_pct) ?? "",
    usesGlobal: typeof v.uses_global === "boolean" ? v.uses_global : !(useOwnMarkup && ownMarkupPct !== null),
    example: {
      label: text(example.label),
      costUsd: decimalText(example.cost_usd),
      credits: int(example.credits),
    },
  };
}

/** Ответ GET/PATCH settings/ → страница; null — ответ не похож на настройки. */
export function parseSettings(v: unknown): Settings | null {
  if (!isRow(v)) return null;
  const mode = asMode(v.mode);
  const markupPct = decimalText(v.markup_pct);
  if (!mode || markupPct === null) return null;
  const canEdit = typeof v.can_edit_money === "boolean" ? v.can_edit_money : null;
  return {
    mode,
    modeEnv: asMode(v.mode_env) ?? mode,
    modeOverride: asMode(v.mode_override),
    markupPct,
    markupDefaultPct: decimalText(v.markup_default_pct) ?? markupPct,
    floorPct: decimalText(v.floor_pct) ?? "0",
    creditUsd: decimalText(v.credit_usd),
    tools: rows(v.tools)
      .map(parseTool)
      .filter((t): t is ToolRow => t !== null)
      .sort((a, b) => a.n - b.n),
    canEditMoney: canEdit,
  };
}

export function parseLog(v: unknown): LogEntry[] | null {
  if (!isRow(v) || !Array.isArray(v.items)) return null;
  return rows(v.items)
    .map((r) => ({
      at: text(r.at),
      actor: text(r.actor),
      before: isRow(r.before) ? r.before : {},
      after: isRow(r.after) ? r.after : {},
    }))
    .filter((r) => r.at !== "");
}

function parseMoney(v: Row): Money {
  return {
    revenueUsd: decimalText(v.revenue_usd),
    costUsd: decimalText(v.cost_usd) ?? "0",
    marginUsd: decimalText(v.margin_usd),
  };
}

export function parseSummary(v: unknown): Summary | null {
  if (!isRow(v)) return null;
  const from = text(v.from);
  const to = text(v.to);
  if (!from || !to || !isRow(v.jobs)) return null;
  const jobs = v.jobs;
  const count = (k: keyof JobCounts) => int(jobs[k]) ?? 0;
  return {
    from,
    to,
    jobs: {
      total: count("total"),
      done: count("done"),
      failed: count("failed"),
      nsfw: count("nsfw"),
      canceled: count("canceled"),
      lost: count("lost"),
      open: count("open"),
    },
    creditsCharged: int(v.credits_charged) ?? 0,
    creditUsd: decimalText(v.credit_usd),
    ...parseMoney(v),
    byTool: rows(v.by_tool)
      .map((r) => {
        const id = text(r.id);
        if (!id) return null;
        return {
          id,
          name: text(r.name) || toolById(id)?.name || id,
          jobs: int(r.jobs) ?? 0,
          done: int(r.done) ?? 0,
          credits: int(r.credits) ?? 0,
          ...parseMoney(r),
        };
      })
      .filter((r): r is SummaryTool => r !== null),
  };
}

/* ------------------------------------------------------------------ */
/* Числа и подписи                                                     */
/* ------------------------------------------------------------------ */

/** "87.40" → "87,4": в панели числа по-русски, без хвостовых нулей. */
export function ru(value: string | number): string {
  const n = Number(value);
  if (typeof value === "string" && !Number.isFinite(n)) return value;
  return String(Number.isFinite(n) ? n : value).replace(".", ",");
}

export const pctText = (value: string | number): string => `${ru(value)} %`;

const DECIMAL_RE = /^\d+(?:[.,]\d+)?$/;

/** Набранное число: запятая или точка; null — не число. */
export function typedNumber(typed: string): number | null {
  const s = typed.trim();
  if (!DECIMAL_RE.test(s)) return null;
  const n = Number(s.replace(",", "."));
  return Number.isFinite(n) ? n : null;
}

function decimals(typed: string): number {
  const s = typed.trim().replace(",", ".");
  const dot = s.indexOf(".");
  return dot < 0 ? 0 : s.length - dot - 1;
}

/** Ошибка процента или null: 0…1000, не больше двух знаков после запятой. */
export function pctProblem(typed: string, what: string): string | null {
  const n = typedNumber(typed);
  if (n === null) return `${what}: нужно число от ${PCT_MIN} до ${PCT_MAX}.`;
  if (n < PCT_MIN || n > PCT_MAX) return `${what}: от ${PCT_MIN} до ${PCT_MAX} %.`;
  if (decimals(typed) > 2) return `${what}: не больше 2 знаков после запятой.`;
  return null;
}

const plainTyped = (typed: string): string => typed.trim().replace(",", ".");

/** «$0,77» / «$0,039» / «$12,40»; null — «—». */
export function usdText(value: string | number | null): string {
  if (value === null) return "—";
  const n = Number(value);
  if (!Number.isFinite(n)) return "—";
  const abs = Math.abs(n);
  const sign = n < 0 ? "−" : "";
  let body: string;
  if (abs === 0) body = "0";
  else if (abs >= 0.1) body = abs.toFixed(2);
  else body = String(Number(abs.toPrecision(2)));
  return `${sign}$${body.replace(".", ",")}`;
}

export const creditsText = (credits: number | null): string =>
  credits === null ? "—" : `${credits.toLocaleString("ru-RU")} кр`;

export const fmtInt = (n: number): string => n.toLocaleString("ru-RU");

/** Доля маржи от выручки, «32 %»; null — не из чего считать. */
export function marginShare(m: Money): string | null {
  if (m.revenueUsd === null || m.marginUsd === null) return null;
  const revenue = Number(m.revenueUsd);
  if (!(revenue > 0)) return null;
  return `${ru(Math.round((Number(m.marginUsd) / revenue) * 1000) / 10)} %`;
}

/* ------------------------------------------------------------------ */
/* Режим                                                               */
/* ------------------------------------------------------------------ */

export const MODE_LABEL: Record<Mode, string> = {
  off: "Закрыт",
  staff: "Только сотрудники",
  on: "Открыт всем",
};

export const MODE_HINT: Record<Mode, string> = {
  off: "Никто не может запускать инструменты: на сайте раздел «скоро откроется». Работы, которые уже идут, доделаются.",
  staff: "Запускать могут только сотрудники — для проверки перед открытием. Остальные видят «скоро откроется».",
  on: "Запускать могут все вошедшие пользователи. Кредиты списываются за готовый результат.",
};

/** Значение кнопки режима: "" — «как в окружении» (правка из админки снимается). */
export type ModeChoice = Mode | "";

export const MODE_CHOICES: ModeChoice[] = ["", "off", "staff", "on"];

export function choiceLabel(choice: ModeChoice, env: Mode): string {
  return choice === "" ? `Как в окружении (${MODE_LABEL[env].toLowerCase()})` : MODE_LABEL[choice];
}

/** Что действует после выбора: правка или режим из окружения. */
export const modeAfter = (choice: ModeChoice, env: Mode): Mode => (choice === "" ? env : choice);

/* ------------------------------------------------------------------ */
/* Цена в кредитах (превью общей наценки)                              */
/* ------------------------------------------------------------------ */

/**
 * Кредиты по себестоимости и наценке — та же формула, что на сервере
 * (ai.pricing.credits_for_cost): max(1, ⌈cost·(100+max(pct, порог))/(100·цена кредита)⌉).
 * Цена кредита приходит округлённой до 6 знаков, поэтому на краю округления
 * сервер может дать на 1 кр иначе — в интерфейсе это «≈». null — считать не из чего.
 */
export function estimateCredits(
  costUsd: string | null,
  pct: number,
  floorPct: string,
  creditUsd: string | null,
): number | null {
  if (costUsd === null || creditUsd === null) return null;
  const cost = Number(costUsd);
  const credit = Number(creditUsd);
  if (!Number.isFinite(cost) || !(credit > 0) || cost < 0) return null;
  const floor = Number(floorPct);
  const effective = Math.max(pct, Number.isFinite(floor) ? floor : 0);
  const raw = (cost * (100 + effective)) / (100 * credit);
  // Погрешность дробей: 23.0000000001 не должно стать 24.
  return Math.max(1, Math.ceil(raw - 1e-9));
}

export type PreviewRow = {
  id: string;
  name: string;
  label: string;
  costUsd: string | null;
  now: number | null;
  next: number | null;
  /** Инструмент считает по своей наценке — общая на него не действует. */
  own: boolean;
};

/**
 * Как поменяются цены, если сохранить общую наценку draftPct. Инструменты со
 * своей наценкой не меняются. Пока процент равен сохранённому — «стало» берём
 * у сервера, а не пересчитываем: иначе округление показало бы мнимую разницу.
 */
export function previewRows(s: Settings, draftPct: number | null): PreviewRow[] {
  const same = draftPct === null || draftPct === Number(s.markupPct);
  return s.tools.map((t) => {
    const now = t.example.credits;
    const next =
      !t.usesGlobal || same ? now : estimateCredits(t.example.costUsd, draftPct as number, s.floorPct, s.creditUsd);
    return { id: t.id, name: t.name, label: t.example.label, costUsd: t.example.costUsd, now, next, own: !t.usesGlobal };
  });
}

export const changedPreview = (list: PreviewRow[]): PreviewRow[] =>
  list.filter((r) => !r.own && r.next !== r.now);

/** Тело PATCH общей наценки и ошибка поля. Сравниваем числа: «40» и «40,00» одно и то же. */
export function markupChange(typed: string, saved: Settings): { body: Record<string, unknown> | null; error: string | null } {
  const error = pctProblem(typed, "Наценка");
  if (error) return { body: null, error };
  if (typedNumber(typed) === Number(saved.markupPct)) return { body: null, error: null };
  return { body: { markup_pct: plainTyped(typed) }, error: null };
}

/* ------------------------------------------------------------------ */
/* Строка инструмента                                                  */
/* ------------------------------------------------------------------ */

/** Своя наценка в поле: пусто — инструмент считает по общей. */
export const ownDraft = (t: ToolRow): string =>
  t.useOwnMarkup && t.ownMarkupPct !== null ? ru(t.ownMarkupPct) : "";

/**
 * Что из поля «своя наценка» отличается от сохранённого — элемент tools[]
 * для PATCH. Пусто — снова общая (флажок снимаем, число чистим, чтобы в
 * журнале не висело забытое значение).
 */
export function ownChange(t: ToolRow, typed: string): { item: Record<string, unknown> | null; error: string | null } {
  const s = typed.trim();
  if (s === "") {
    if (!t.useOwnMarkup) return { item: null, error: null };
    return { item: { id: t.id, use_own_markup: false, markup_pct: null }, error: null };
  }
  const error = pctProblem(s, "Своя наценка");
  if (error) return { item: null, error };
  const savedOwn = t.useOwnMarkup && t.ownMarkupPct !== null ? Number(t.ownMarkupPct) : null;
  if (typedNumber(s) === savedOwn) return { item: null, error: null };
  return { item: { id: t.id, use_own_markup: true, markup_pct: plainTyped(s) }, error: null };
}

/** «40 % · общая» / «55 % · своя» / «25 % · порог» — с чем сейчас считается цена. */
export function markupSource(t: ToolRow, s: Settings): { pct: string; source: "global" | "own" | "floor" } {
  const pct = t.effectiveMarkupPct || (t.usesGlobal ? s.markupPct : (t.ownMarkupPct ?? s.markupPct));
  const base = t.usesGlobal ? Number(s.markupPct) : Number(t.ownMarkupPct);
  if (Number(pct) > base && Number(pct) === Number(s.floorPct)) return { pct, source: "floor" };
  return { pct, source: t.usesGlobal ? "global" : "own" };
}

/* ------------------------------------------------------------------ */
/* Категории (с сайта)                                                 */
/* ------------------------------------------------------------------ */

const CATEGORY_LABEL: Record<string, string> = {
  video: "Видео и движение",
  image: "Изображения",
  characters: "AI-персонажи",
  ads: "Реклама и маркетинг",
};

export function categoryLabel(id: string): string {
  const cat = toolById(id)?.cat;
  return (cat && CATEGORY_LABEL[cat]) || "—";
}

export const KIND_LABEL: Record<Kind, string> = {
  image: "картинка",
  video: "видео",
  character: "персонаж",
};

/* ------------------------------------------------------------------ */
/* Журнал                                                              */
/* ------------------------------------------------------------------ */

export type LogLine = { label: string; before: string; after: string };

type LogContext = { names: Record<string, string>; defaultPct: string };

const asRow = (v: unknown): Row => (isRow(v) ? v : {});

function modeValueText(v: unknown): string {
  const mode = asMode(v);
  return mode ? MODE_LABEL[mode] : "как в окружении";
}

function markupValueText(v: unknown, defaultPct: string): string {
  const pct = decimalText(v);
  return pct === null ? `по умолчанию (${pctText(defaultPct)})` : pctText(pct);
}

function ownValueText(v: Row): string {
  const pct = decimalText(v.markup_pct);
  return v.use_own_markup === true && pct !== null ? pctText(pct) : "общая";
}

const yesNo = (v: unknown): string => (v === true ? "включён" : v === false ? "выключен" : "—");

function anyText(v: unknown): string {
  if (v === null || v === undefined || v === "") return "—";
  if (typeof v === "object") {
    try {
      return JSON.stringify(v);
    } catch {
      return String(v);
    }
  }
  return String(v);
}

/**
 * Запись журнала → строки «что: было → стало» нашими словами. Ключи сервера:
 * mode, markup_pct, tool:<id> ({enabled, markup_pct, use_own_markup}).
 */
export function logLines(entry: LogEntry, ctx: LogContext): LogLine[] {
  const keys = Array.from(new Set([...Object.keys(entry.before), ...Object.keys(entry.after)]));
  const out: LogLine[] = [];
  for (const key of keys) {
    const b = entry.before[key];
    const a = entry.after[key];
    if (key === "mode") {
      out.push({ label: "Режим", before: modeValueText(b), after: modeValueText(a) });
    } else if (key === "markup_pct") {
      out.push({
        label: "Общая наценка",
        before: markupValueText(b, ctx.defaultPct),
        after: markupValueText(a, ctx.defaultPct),
      });
    } else if (key.startsWith("tool:")) {
      const id = key.slice(5);
      const name = ctx.names[id] || toolById(id)?.name || id;
      const br = asRow(b);
      const ar = asRow(a);
      if (br.enabled !== ar.enabled) out.push({ label: name, before: yesNo(br.enabled), after: yesNo(ar.enabled) });
      const bo = ownValueText(br);
      const ao = ownValueText(ar);
      if (bo !== ao) out.push({ label: `${name}: наценка`, before: bo, after: ao });
    } else {
      out.push({ label: key, before: anyText(b), after: anyText(a) });
    }
  }
  return out;
}

/* ------------------------------------------------------------------ */
/* Период сводки                                                       */
/* ------------------------------------------------------------------ */

const pad = (n: number): string => String(n).padStart(2, "0");

/** Дата по местному времени → «ГГГГ-ММ-ДД». */
export const isoDay = (d: Date): string => `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;

/** Последние days дней, включая сегодня. */
export function periodRange(days: number, today: Date): { from: string; to: string } {
  const start = new Date(today.getFullYear(), today.getMonth(), today.getDate() - (days - 1));
  return { from: isoDay(start), to: isoDay(today) };
}

const DAY_RE = /^\d{4}-\d{2}-\d{2}$/;

function dayNumber(day: string): number | null {
  if (!DAY_RE.test(day)) return null;
  const [y, m, d] = day.split("-").map(Number);
  const t = Date.UTC(y, m - 1, d);
  const back = new Date(t);
  if (back.getUTCFullYear() !== y || back.getUTCMonth() !== m - 1 || back.getUTCDate() !== d) return null;
  return t / 86_400_000;
}

/** Свой период: ошибка или null. Правила сервера — от одного дня до года. */
export function rangeProblem(from: string, to: string): string | null {
  const a = dayNumber(from);
  const b = dayNumber(to);
  if (a === null || b === null) return "Укажите обе даты.";
  if (a > b) return "Начало периода позже конца.";
  if (b - a > SUMMARY_MAX_DAYS) return "Период — не длиннее года.";
  return null;
}

/** «01.11 — 23.11.2026». */
export function rangeText(from: string, to: string): string {
  const f = from.split("-");
  const t = to.split("-");
  if (f.length !== 3 || t.length !== 3) return `${from} — ${to}`;
  const left = f[0] === t[0] ? `${f[2]}.${f[1]}` : `${f[2]}.${f[1]}.${f[0]}`;
  return `${left} — ${t[2]}.${t[1]}.${t[0]}`;
}

/* ------------------------------------------------------------------ */
/* Ошибки                                                              */
/* ------------------------------------------------------------------ */

export const SUPERUSER_TEXT = "Наценки меняет только главный администратор.";

/** Отказ из-за роли: денежные поля дальше выключаем. */
export function isSuperuserRefusal(res: { status: number; data?: unknown }): boolean {
  return res.status === 403 && isRow(res.data) && res.data.code === "superuser_required";
}

/** Текст отказа: связь, частота, роль, {detail} и первая ошибка поля. */
export function errorText(res: { status: number; data?: unknown }, fallback: string): string {
  if (res.status === 0) return "Нет связи с сервером. Проверьте интернет и повторите.";
  if (res.status === 429) return "Слишком много запросов подряд. Подождите минуту и повторите.";
  if (isSuperuserRefusal(res)) return SUPERUSER_TEXT;
  if (res.status === 401) return "Сессия истекла — войдите в админку заново.";
  const data = isRow(res.data) ? res.data : {};
  const errors = isRow(data.errors) ? data.errors : {};
  const first = Object.values(errors).map(text).find(Boolean);
  const detail = text(data.detail);
  if (first && detail && first !== detail) return `${detail} ${first}`;
  return first || detail || `${fallback} (HTTP ${res.status})`;
}
