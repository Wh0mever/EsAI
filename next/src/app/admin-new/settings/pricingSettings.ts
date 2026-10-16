/**
 * Карточка «Цены и наценка» в «Настройках»: весь контракт с сервером — здесь
 * (core/adminapi/prices.py, описание — vstudio2-notes/pricing/CONTRACT_A_admin.md).
 *
 *   GET   manage/pricing/          → настройки, следствия (курс, основа кредита), 10 примеров, предупреждения
 *   PATCH manage/pricing/          { mode?, markup_pct?, floor_pct?, kgs_per_usd?, pin_live_rate? } → то же + changed
 *   POST  manage/pricing/preview/  то же тело → то же, посчитанное с несохранёнными значениями (ничего не пишет)
 *   PATCH manage/settings/         { studio_scene_credits } — «цена сцены 5 с», только режим legacy
 *
 * Ответ разбираем как «чужие руки»: запись не того типа карточку не роняет.
 * Модуль чистый (без React и сети) — его проверяет pricingSettings.test.mjs.
 */

export const PRICING_PATH = "manage/pricing/";
export const PRICING_PREVIEW_PATH = "manage/pricing/preview/";
export const SETTINGS_PATH = "manage/settings/";

export type PricingMode = "legacy" | "markup";

export const MODE_LABEL: Record<PricingMode, string> = {
  legacy: "По-старому (legacy)",
  markup: "Наценка от себестоимости",
};

export type Sample = {
  key: string;
  /** video | image | cartoon | text */
  kind: string;
  label: string;
  modelId: number | null;
  costText: string | null;
  legacy: number | null;
  markup: number | null;
  active: number | null;
  deltaPct: number | null;
  /** Только текст: цена сообщения после «Пересчитать тарифы текста». */
  afterRecompute: number | null;
  flags: string[];
};

export type Basis = {
  pkg: string;
  currency: string;
  kgsPerCredit: string | null;
  creditUsd: string | null;
  kgsPerUsd: string | null;
  /** pinned | live | "" (пакет в $ или Stars) */
  rateSource: string;
};

export type Warning = { code: string; text: string };

export type Limits = { pctMin: number; pctMax: number; rateMin: number; rateMax: number };

export const DEFAULT_LIMITS: Limits = { pctMin: 0, pctMax: 1000, rateMin: 1, rateMax: 100000 };

export type Pricing = {
  mode: PricingMode;
  markupPct: string;
  floorPct: string;
  /** null — живой курс */
  kgsPerUsd: string | null;
  liveKgsPerUsd: string | null;
  rateWarning: boolean;
  basis: Basis | null;
  basisLine: string;
  preview: boolean;
  effectiveMarkupPct: string;
  limits: Limits;
  /** «Мультфильм: цена сцены 5 с»; null — сервер не прочитал */
  sceneCredits: number | null;
  samples: Sample[];
  warnings: Warning[];
  /** Сколько включённых моделей без себестоимости. */
  withoutCost: number;
};

type Row = Record<string, unknown>;

const isRow = (v: unknown): v is Row => typeof v === "object" && v !== null && !Array.isArray(v);
const rows = (v: unknown): Row[] => (Array.isArray(v) ? v.filter(isRow) : []);
const text = (v: unknown): string => (typeof v === "string" ? v.trim() : "");
const num = (v: unknown): number | null => (typeof v === "number" && Number.isFinite(v) ? v : null);
const int = (v: unknown): number | null => {
  const n = num(v);
  return n !== null && Number.isInteger(n) ? n : null;
};
/** Число строкой ("40", "87.4") — как Decimal отдаёт сервер; число тоже принимаем. */
const decimalText = (v: unknown): string | null => {
  if (typeof v === "number" && Number.isFinite(v)) return String(v);
  const s = text(v);
  return s && Number.isFinite(Number(s)) ? s : null;
};

const limitOf = (v: unknown, fallback: number): number => {
  const s = decimalText(v);
  return s === null ? fallback : Number(s);
};

function parseLimits(v: unknown): Limits {
  if (!isRow(v)) return DEFAULT_LIMITS;
  return {
    pctMin: limitOf(v.pct_min, DEFAULT_LIMITS.pctMin),
    pctMax: limitOf(v.pct_max, DEFAULT_LIMITS.pctMax),
    rateMin: limitOf(v.rate_min, DEFAULT_LIMITS.rateMin),
    rateMax: limitOf(v.rate_max, DEFAULT_LIMITS.rateMax),
  };
}

function parseBasis(v: unknown): Basis | null {
  if (!isRow(v)) return null;
  const pkg = text(v.package);
  if (!pkg) return null;
  return {
    pkg,
    currency: text(v.currency),
    kgsPerCredit: decimalText(v.kgs_per_credit),
    creditUsd: decimalText(v.credit_usd),
    kgsPerUsd: decimalText(v.kgs_per_usd),
    rateSource: text(v.rate_source),
  };
}

function parseSample(v: Row): Sample | null {
  const key = text(v.key);
  if (!key) return null;
  const model = isRow(v.model) ? v.model : null;
  return {
    key,
    kind: text(v.kind),
    label: text(v.label) || key,
    modelId: model ? int(model.id) : null,
    costText: text(v.cost_text) || null,
    legacy: int(v.legacy),
    markup: int(v.markup),
    active: int(v.active),
    deltaPct: num(v.delta_pct),
    afterRecompute: int(v.after_recompute),
    flags: Array.isArray(v.flags) ? v.flags.filter((f): f is string => typeof f === "string") : [],
  };
}

/** Ответ GET/PATCH/preview → карточка; null — ответ не похож на карточку цен. */
export function parsePricing(v: unknown): Pricing | null {
  if (!isRow(v)) return null;
  const mode = v.mode === "markup" ? "markup" : v.mode === "legacy" ? "legacy" : null;
  const markupPct = decimalText(v.markup_pct);
  const floorPct = decimalText(v.floor_pct);
  if (!mode || markupPct === null || floorPct === null) return null;
  return {
    mode,
    markupPct,
    floorPct,
    kgsPerUsd: decimalText(v.kgs_per_usd),
    liveKgsPerUsd: decimalText(v.live_kgs_per_usd),
    rateWarning: v.rate_warning === true,
    basis: parseBasis(v.basis),
    basisLine: text(v.basis_line),
    preview: v.preview === true,
    effectiveMarkupPct: decimalText(v.effective_markup_pct) ?? markupPct,
    limits: parseLimits(v.limits),
    sceneCredits: int(v.studio_scene_credits),
    samples: rows(v.samples)
      .map(parseSample)
      .filter((s): s is Sample => s !== null),
    warnings: rows(v.warnings)
      .map((w) => ({ code: text(w.code), text: text(w.text) }))
      .filter((w) => w.text !== ""),
    withoutCost: Array.isArray(v.models_without_cost) ? v.models_without_cost.length : 0,
  };
}

/* ------------------------------------------------------------------ */
/* Числа                                                               */
/* ------------------------------------------------------------------ */

/** "87.4" → "87,4": в панели числа по-русски, как toLocaleString("ru-RU"). */
export const ru = (value: string | number): string => String(value).replace(".", ",");

const DECIMAL_RE = /^\d+(?:[.,]\d+)?$/;

/** Набранное число: запятая или точка; null — не число. */
export function typedNumber(typed: string): number | null {
  const s = typed.trim();
  if (!DECIMAL_RE.test(s)) return null;
  const n = Number(s.replace(",", "."));
  return Number.isFinite(n) ? n : null;
}

/** Сколько знаков после запятой набрано. */
export function decimals(typed: string): number {
  const s = typed.trim().replace(",", ".");
  const dot = s.indexOf(".");
  return dot < 0 ? 0 : s.length - dot - 1;
}

/** Для тела запроса: "35,5" → "35.5" (сервер принимает и запятую, но так однозначно). */
const plainTyped = (typed: string): string => typed.trim().replace(",", ".");

/* ------------------------------------------------------------------ */
/* Черновик формы                                                      */
/* ------------------------------------------------------------------ */

export type Draft = {
  mode: PricingMode;
  markup: string;
  floor: string;
  /** "" — живой курс */
  rate: string;
  /** Нажали «Закрепить текущий»: сервер закрепит живой курс сам, точно. */
  pin: boolean;
};

export type Field = "mode" | "markup_pct" | "floor_pct" | "kgs_per_usd" | "pin_live_rate" | "__all__";
export type FieldErrors = Partial<Record<Field, string>>;

export function draftFrom(p: Pricing): Draft {
  return {
    mode: p.mode,
    markup: ru(p.markupPct),
    floor: ru(p.floorPct),
    rate: p.kgsPerUsd === null ? "" : ru(p.kgsPerUsd),
    pin: false,
  };
}

/** «Закрепить текущий»: в поле — живой курс, а серверу уйдёт pin_live_rate. */
export function pinDraft(draft: Draft, p: Pricing): Draft {
  if (p.liveKgsPerUsd === null) return draft;
  return { ...draft, rate: ru(p.liveKgsPerUsd), pin: true };
}

function pctProblem(typed: string, what: string, limits: Limits): string | null {
  const n = typedNumber(typed);
  if (n === null) return `${what}: нужно число от ${ru(limits.pctMin)} до ${ru(limits.pctMax)}.`;
  if (n < limits.pctMin || n > limits.pctMax) return `${what}: от ${ru(limits.pctMin)} до ${ru(limits.pctMax)} %.`;
  if (decimals(typed) > 2) return `${what}: не больше 2 знаков после запятой.`;
  return null;
}

const RATE_PROBLEM = "Курс: сколько сомов за доллар, например 87,5. Пусто — живой курс.";

/**
 * Что из черновика отличается от сохранённого — тело PATCH и превью — и
 * ошибки полей. Сравниваем числа, а не строки: «40» и «40,00» одно и то же.
 */
export function draftChanges(draft: Draft, saved: Pricing): { body: Record<string, unknown>; errors: FieldErrors } {
  const body: Record<string, unknown> = {};
  const errors: FieldErrors = {};
  const { limits } = saved;

  if (draft.mode !== saved.mode) body.mode = draft.mode;

  const markupError = pctProblem(draft.markup, "Наценка", limits);
  if (markupError) errors.markup_pct = markupError;
  else if (typedNumber(draft.markup) !== Number(saved.markupPct)) body.markup_pct = plainTyped(draft.markup);

  const floorError = pctProblem(draft.floor, "Нижний порог", limits);
  if (floorError) errors.floor_pct = floorError;
  else if (typedNumber(draft.floor) !== Number(saved.floorPct)) body.floor_pct = plainTyped(draft.floor);

  const savedRate = saved.kgsPerUsd === null ? null : Number(saved.kgsPerUsd);
  if (draft.pin) {
    const live = saved.liveKgsPerUsd === null ? null : Number(saved.liveKgsPerUsd);
    if (live === null) errors.pin_live_rate = "Живой курс сейчас недоступен — введите курс вручную.";
    else if (live !== savedRate) body.pin_live_rate = true;
  } else if (draft.rate.trim() === "") {
    if (savedRate !== null) body.kgs_per_usd = null;
  } else {
    const rate = typedNumber(draft.rate);
    if (rate === null || rate < limits.rateMin || rate > limits.rateMax || decimals(draft.rate) > 4) {
      errors.kgs_per_usd = RATE_PROBLEM;
    } else if (rate !== savedRate) {
      body.kgs_per_usd = plainTyped(draft.rate);
    }
  }
  return { body, errors };
}

export const hasErrors = (errors: FieldErrors): boolean => Object.values(errors).some(Boolean);

/** Текст отказа: {detail: "…"} — как у всех ответов панели. */
export function errorText(res: { status: number; data?: unknown }, fallback: string): string {
  if (res.status === 0) return "Нет связи с сервером. Проверьте интернет и повторите.";
  if (res.status === 429) return "Слишком много запросов подряд. Подождите минуту и повторите.";
  const detail = isRow(res.data) ? text(res.data.detail) : "";
  return detail || `${fallback} (HTTP ${res.status})`;
}

/** Что ещё сохранится вместе с режимом — строками для окна подтверждения. */
export function changeLines(body: Record<string, unknown>, saved: Pricing): string[] {
  const out: string[] = [];
  if ("markup_pct" in body) out.push(`Наценка: ${ru(saved.markupPct)} → ${ru(String(body.markup_pct))} %`);
  if ("floor_pct" in body) out.push(`Нижний порог: ${ru(saved.floorPct)} → ${ru(String(body.floor_pct))} %`);
  if ("pin_live_rate" in body) {
    out.push(`Курс: закрепить живой${saved.liveKgsPerUsd ? ` ${ru(saved.liveKgsPerUsd)}` : ""} сом/$`);
  } else if ("kgs_per_usd" in body) {
    out.push(body.kgs_per_usd === null ? "Курс: брать живой" : `Курс: ${ru(String(body.kgs_per_usd))} сом/$`);
  }
  return out;
}

/** Ошибки полей из отказа сервера ({detail, errors: {поле: текст}}). */
export function serverErrors(data: unknown): FieldErrors {
  if (!isRow(data) || !isRow(data.errors)) return {};
  const out: FieldErrors = {};
  for (const field of ["mode", "markup_pct", "floor_pct", "kgs_per_usd", "pin_live_rate", "__all__"] as const) {
    const message = text(data.errors[field]);
    if (message) out[field] = message;
  }
  return out;
}

/* ------------------------------------------------------------------ */
/* Примеры                                                             */
/* ------------------------------------------------------------------ */

/** «−15,9 %» / «+4 %»; null — сравнивать не с чем. */
export function deltaText(delta: number | null): string | null {
  if (delta === null) return null;
  if (delta === 0) return "0 %";
  const sign = delta > 0 ? "+" : "−";
  return `${sign}${ru(Math.abs(delta))} %`;
}

export const creditsText = (credits: number | null): string => (credits === null ? "—" : `${credits} кр`);

export type FlagView = { label: string; tone: "wait" | "fail" | "muted"; title: string };

const FLAGS: Record<string, FlagView> = {
  no_cost: {
    label: "нет себестоимости",
    tone: "wait",
    title: "OpenRouter не сообщает цену или в «Моделях» не задана себестоимость картинки",
  },
  floor: { label: "порог", tone: "muted", title: "Наценка ниже нижнего порога — цену задаёт порог" },
  below_cost: {
    label: "ниже себестоимости",
    tone: "fail",
    title: "Действующая цена ниже себестоимости с нижним порогом",
  },
  not_in_db: {
    label: "модели нет в базе",
    tone: "muted",
    title: "Строки модели ещё нет: цена посчитана по каталогу с тарифом 1. Добавьте её в «Моделях»",
  },
  inactive: { label: "выключена", tone: "muted", title: "Модель выключена в «Моделях»" },
  // Только у сцены мультфильма (cartoon.pricing.scene_sample).
  frame_no_cost: {
    label: "кадр без себестоимости",
    tone: "wait",
    title: "У модели кадра в «Моделях» не задана себестоимость: кадр стоит по-старому",
  },
  estimate: {
    label: "оценка",
    tone: "muted",
    title: "Себестоимость кадра взята из «Моделей» (прайс OpenRouter), а не из живого каталога",
  },
  error: { label: "не посчиталось", tone: "fail", title: "Пример не посчитался — подробности в журнале сервера" },
};

export function flagViews(flags: readonly string[]): FlagView[] {
  return flags.map((flag) => FLAGS[flag] ?? { label: flag, tone: "muted" as const, title: flag });
}

/** Наценка примера до правки — показать «было», пока смотрим превью. */
export function previousMarkup(saved: Pricing, key: string): number | null {
  return saved.samples.find((s) => s.key === key)?.markup ?? null;
}

/** Что изменится при переключении режима: примеры, где цена другая, — для окна подтверждения. */
export function modeSwitchExamples(samples: readonly Sample[], to: PricingMode, limit = 4): string[] {
  const out: string[] = [];
  for (const s of samples) {
    if (s.kind === "text") continue;
    const from = to === "markup" ? s.legacy : s.markup;
    const next = to === "markup" ? s.markup : s.legacy;
    if (from === next) continue;
    out.push(`${s.label}: ${creditsText(from)} → ${next === null ? "не продаётся" : creditsText(next)}`);
    if (out.length >= limit) break;
  }
  return out;
}

/* ------------------------------------------------------------------ */
/* «Мультфильм: цена сцены 5 с» (только legacy)                        */
/* ------------------------------------------------------------------ */

export const SCENE_CREDITS_MAX = 100000;

/** Набранная цена сцены → число; null — не целое от 0 до 100000. */
export function typedSceneCredits(typed: string): number | null {
  const s = typed.trim();
  if (!/^\d+$/.test(s)) return null;
  const n = Number(s);
  return n <= SCENE_CREDITS_MAX ? n : null;
}
