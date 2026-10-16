/**
 * «Модели» в панели: весь контракт с сервером — здесь (core/adminapi/views.py,
 * core/adminapi/prices.py; описание — vstudio2-notes/pricing/CONTRACT_A_admin.md §2).
 *
 *   GET   manage/models/                       → [модель] (с колонками цены: pricing, cost_sample, price_sample…)
 *   PATCH manage/models/<id>/                  { правленые поля } → модель; отказ — {detail: {поле: [текст]}}
 *   POST  manage/models/                       { openrouter_id, name?, category? } → {model, warnings} (201)
 *   GET   manage/models/catalog/?q=&kind=      → {results, count, truncated, catalogs}
 *   GET   manage/models/text-recompute/[?ids=] → предпросмотр «Пересчитать тарифы текста»
 *   POST  manage/models/text-recompute/        {confirm: true, items: [{id, coefficient}]} → {updated, preview}
 *   GET   manage/models/chat-image-recompute/[?ids=] → предпросмотр «Пересчитать тариф картинок в чате»
 *   POST  manage/models/chat-image-recompute/  то же тело и ответ, что у тарифов текста
 *
 * Ответы разбираем как «чужие руки»: строка без id или с полем не того типа
 * страницу не роняет. Модуль чистый (без React и сети) — его проверяет
 * modelsAdmin.test.mjs.
 */

export const MODELS_PATH = "manage/models/";
export const modelPath = (id: number): string => `${MODELS_PATH}${id}/`;
export const CATALOG_PATH = "manage/models/catalog/";
export const RECOMPUTE_PATH = "manage/models/text-recompute/";
export const CHAT_IMAGE_RECOMPUTE_PATH = "manage/models/chat-image-recompute/";
export const PRICING_SETTINGS_LINK = "/admin-new/settings#pricing";

export type Kind = "video" | "image" | "text";
export type PricingMode = "legacy" | "markup";

export const CATEGORIES: { value: string; label: string }[] = [
  { value: "chat", label: "Для общения" },
  { value: "writing", label: "Тексты и SEO" },
  { value: "coding", label: "Программирование" },
  { value: "reasoning", label: "Анализ" },
  { value: "search", label: "Поиск" },
  { value: "image", label: "Изображения" },
  { value: "fast", label: "Быстрые" },
  { value: "budget", label: "Экономичные" },
  { value: "video", label: "Видео" },
];

/** Категории текста: в них может встать новая текстовая модель. */
export const TEXT_CATEGORIES = CATEGORIES.filter((c) => c.value !== "image" && c.value !== "video");

export const CARTOON_STAGES: { value: string; label: string }[] = [
  { value: "", label: "—" },
  { value: "script", label: "Сценарий" },
  { value: "image", label: "Изображения" },
  { value: "video", label: "Видео" },
];

/** Вид модели по категории — так же решает сервер: всё, что не картинки и не видео, — текст. */
export const kindOf = (category: string): Kind =>
  category === "video" ? "video" : category === "image" ? "image" : "text";

export const KIND_LABEL: Record<Kind, string> = { video: "Видео", image: "Картинки", text: "Текст" };

/** Единица тарифа: у одного поля три смысла (MAP_admin §1.2). */
export const TARIFF_UNIT: Record<Kind, string> = {
  video: "кр за 1 с (720p)",
  image: "кр за картинку",
  text: "кр за 1000 токенов",
};

/* ------------------------------------------------------------------ */
/* Разбор                                                              */
/* ------------------------------------------------------------------ */

type Row = Record<string, unknown>;

const isRow = (v: unknown): v is Row => typeof v === "object" && v !== null && !Array.isArray(v);
const rows = (v: unknown): Row[] => (Array.isArray(v) ? v.filter(isRow) : []);
const text = (v: unknown): string => (typeof v === "string" ? v.trim() : "");
const num = (v: unknown): number | null => (typeof v === "number" && Number.isFinite(v) ? v : null);
const int = (v: unknown): number | null => {
  const n = num(v);
  return n !== null && Number.isInteger(n) ? n : null;
};
/** Число строкой ("40", "1.224") или числом — как отдаёт сервер. */
const decimalText = (v: unknown): string | null => {
  if (typeof v === "number" && Number.isFinite(v)) return String(v);
  const s = text(v);
  return s && Number.isFinite(Number(s)) ? s : null;
};
/** Число или числовая строка → число (DRF отдаёт Decimal то строкой, то числом). */
const numeric = (v: unknown): number | null => {
  const s = decimalText(v);
  return s === null ? null : Number(s);
};
const flagsOf = (v: unknown): string[] => (Array.isArray(v) ? v.filter((f): f is string => typeof f === "string") : []);

export type ModelPricing = {
  kind: Kind;
  mode: PricingMode;
  legacy: number | null;
  markup: number | null;
  active: number | null;
  flags: string[];
  /** model — своя наценка у модели, global — общая */
  markupSource: "model" | "global";
  effectiveMarkupPct: string | null;
};

export type Model = {
  id: number;
  name: string;
  openrouterId: string;
  markupCoefficient: number;
  category: string;
  recommended: boolean;
  freeTier: boolean;
  isActive: boolean;
  sortOrder: number;
  cartoonStage: string;
  vstudioEnabled: boolean;
  /** Код видеостудии знает модель — без этого тумблер ничего не даёт. */
  vstudioSupported: boolean;
  markupPct: number | null;
  unitCostUsd: number | null;
  refCostUsd: number | null;
  pricing: ModelPricing | null;
  costSample: string | null;
  priceSample: string | null;
  priceSampleOther: string | null;
};

function parseModelPricing(v: unknown, category: string): ModelPricing | null {
  if (!isRow(v)) return null;
  const kind = v.kind === "video" || v.kind === "image" || v.kind === "text" ? v.kind : kindOf(category);
  return {
    kind,
    mode: v.mode === "markup" ? "markup" : "legacy",
    legacy: int(v.legacy),
    markup: int(v.markup),
    active: int(v.active),
    flags: flagsOf(v.flags),
    markupSource: v.markup_source === "model" ? "model" : "global",
    effectiveMarkupPct: decimalText(v.effective_markup_pct),
  };
}

export function parseModel(v: unknown): Model | null {
  if (!isRow(v)) return null;
  const id = int(v.id);
  if (id === null) return null;
  const category = text(v.category) || "chat";
  return {
    id,
    name: text(v.name) || `Модель №${id}`,
    openrouterId: text(v.openrouter_id),
    markupCoefficient: numeric(v.markup_coefficient) ?? 0,
    category,
    recommended: v.recommended === true,
    freeTier: v.free_tier === true,
    isActive: v.is_active === true,
    sortOrder: int(v.sort_order) ?? 0,
    cartoonStage: text(v.cartoon_stage),
    vstudioEnabled: v.vstudio_enabled === true,
    vstudioSupported: v.vstudio_supported === true,
    markupPct: numeric(v.markup_pct),
    unitCostUsd: numeric(v.unit_cost_usd),
    refCostUsd: numeric(v.ref_cost_usd),
    pricing: parseModelPricing(v.pricing, category),
    costSample: text(v.cost_sample) || null,
    priceSample: text(v.price_sample) || null,
    priceSampleOther: text(v.price_sample_other) || null,
  };
}

/** Список моделей; null — ответ не список (старый сервер так не отвечает никогда). */
export function parseModels(v: unknown): Model[] | null {
  if (!Array.isArray(v)) return null;
  return v.map(parseModel).filter((m): m is Model => m !== null);
}

/** Режим цен, в котором посчитаны колонки; null — сервер не прислал колонки цены. */
export function modeOf(models: readonly Model[]): PricingMode | null {
  return models.find((m) => m.pricing)?.pricing?.mode ?? null;
}

/** Порядок как у сервера: sort_order, затем id. */
export const byOrder = (a: Model, b: Model): number => a.sortOrder - b.sortOrder || a.id - b.id;

/** Строка с сервера встаёт на своё место; новая — по порядку. */
export function replaceModel(list: readonly Model[], saved: Model): Model[] {
  const has = list.some((m) => m.id === saved.id);
  const next = has ? list.map((m) => (m.id === saved.id ? saved : m)) : [...list, saved];
  return next.sort(byOrder);
}

/** Поиск по названию и ID OpenRouter. */
export function matchesModel(m: Model, query: string): boolean {
  const q = query.trim().toLocaleLowerCase("ru");
  if (!q) return true;
  return m.name.toLocaleLowerCase("ru").includes(q) || m.openrouterId.toLowerCase().includes(q);
}

/* ------------------------------------------------------------------ */
/* Ошибки                                                              */
/* ------------------------------------------------------------------ */

/**
 * Текст отказа. У PATCH модели detail — словарь {поле: [тексты]} (форма
 * сериализатора), у остального — строка.
 */
export function errorText(res: { status: number; data?: unknown }, fallback: string): string {
  if (res.status === 0) return "Нет связи с сервером. Проверьте интернет и повторите.";
  if (res.status === 429) return "Слишком много запросов подряд. Подождите минуту и повторите.";
  const data = isRow(res.data) ? res.data : null;
  const detail = data?.detail;
  if (typeof detail === "string" && detail.trim()) return detail.trim();
  if (isRow(detail)) {
    const parts: string[] = [];
    for (const value of Object.values(detail)) {
      const list = Array.isArray(value) ? value : [value];
      for (const item of list) {
        const s = text(item);
        if (s && !parts.includes(s)) parts.push(s);
      }
    }
    if (parts.length) return parts.join(" ");
  }
  return `${fallback} (HTTP ${res.status})`;
}

/* ------------------------------------------------------------------ */
/* Правка строки                                                       */
/* ------------------------------------------------------------------ */

/** "0.039" → "0,039": числа в панели по-русски. */
export const ru = (value: number | string): string => String(value).replace(".", ",");

const DECIMAL_RE = /^\d+(?:[.,]\d+)?$/;

function typedDecimal(typed: string): { value: number; places: number } | null {
  const s = typed.trim();
  if (!DECIMAL_RE.test(s)) return null;
  const plain = s.replace(",", ".");
  const value = Number(plain);
  if (!Number.isFinite(value)) return null;
  const dot = plain.indexOf(".");
  return { value, places: dot < 0 ? 0 : plain.length - dot - 1 };
}

export type RowForm = {
  coefficient: string;
  /** "" — общая наценка */
  markupPct: string;
  /** "" — не задана */
  unitCost: string;
  /** "" — входное фото бесплатно */
  refCost: string;
  category: string;
  cartoonStage: string;
  recommended: boolean;
  freeTier: boolean;
  isActive: boolean;
  vstudioEnabled: boolean;
};

const optional = (value: number | null): string => (value === null ? "" : ru(value));

export function formFromModel(m: Model): RowForm {
  return {
    coefficient: ru(m.markupCoefficient),
    markupPct: optional(m.markupPct),
    unitCost: optional(m.unitCostUsd),
    refCost: optional(m.refCostUsd),
    category: m.category,
    cartoonStage: m.cartoonStage,
    recommended: m.recommended,
    freeTier: m.freeTier,
    isActive: m.isActive,
    vstudioEnabled: m.vstudioEnabled,
  };
}

type Optional = { typed: string; saved: number | null; max: number; places: number; problem: string };

/** Необязательное число: "" — null. Возвращает [значение для тела, изменилось ли] или текст ошибки. */
function optionalChange(o: Optional): { value: string | null; changed: boolean } | string {
  if (o.typed.trim() === "") return { value: null, changed: o.saved !== null };
  const parsed = typedDecimal(o.typed);
  if (!parsed || parsed.value > o.max) return o.problem;
  if (parsed.places > o.places) return `${o.problem.split(":")[0]}: не больше ${o.places} знаков после запятой`;
  return { value: o.typed.trim().replace(",", "."), changed: parsed.value !== o.saved };
}

/**
 * Что изменилось в строке — тело PATCH — и первая ошибка. Пустое тело —
 * строку не трогали (или вернули как было).
 */
export function rowChanges(m: Model, f: RowForm): { body: Record<string, unknown>; error: string | null } {
  const body: Record<string, unknown> = {};

  const coeff = typedDecimal(f.coefficient);
  if (!coeff || coeff.value > 999.999) {
    return { body, error: "Тариф: число от 0 до 999,999" };
  }
  if (coeff.places > 3) return { body, error: "Тариф: не больше 3 знаков после запятой" };
  if (coeff.value !== m.markupCoefficient) body.markup_coefficient = coeff.value;

  const markup = optionalChange({
    typed: f.markupPct,
    saved: m.markupPct,
    max: 1000,
    places: 2,
    problem: "Наценка: от 0 до 1000 %; пусто — общая наценка",
  });
  if (typeof markup === "string") return { body, error: markup };
  if (markup.changed) body.markup_pct = markup.value;

  // Себестоимость картинки — только у категории «Изображения» (так же решает сервер).
  if (f.category === "image") {
    const unit = optionalChange({
      typed: f.unitCost,
      saved: m.unitCostUsd,
      max: 1000,
      places: 6,
      problem: "Себестоимость картинки: сумма в долларах от 0 до 1000, например 0,039; пусто — не задана",
    });
    if (typeof unit === "string") return { body, error: unit };
    if (unit.changed) body.unit_cost_usd = unit.value;

    const ref = optionalChange({
      typed: f.refCost,
      saved: m.refCostUsd,
      max: 1000,
      places: 6,
      problem: "Себестоимость входного фото: сумма в долларах от 0 до 1000, например 0,06; пусто — бесплатно",
    });
    if (typeof ref === "string") return { body, error: ref };
    if (ref.changed) body.ref_cost_usd = ref.value;
  }

  if (f.category !== m.category) body.category = f.category;
  if (f.cartoonStage !== m.cartoonStage) body.cartoon_stage = f.cartoonStage;
  if (f.recommended !== m.recommended) body.recommended = f.recommended;
  if (f.freeTier !== m.freeTier) body.free_tier = f.freeTier;
  if (f.isActive !== m.isActive) body.is_active = f.isActive;
  if (f.vstudioEnabled !== m.vstudioEnabled) body.vstudio_enabled = f.vstudioEnabled;
  return { body, error: null };
}

/** Правка меняет цену — колонка «Цена» до сохранения устарела. */
export const PRICE_FIELDS = ["markup_coefficient", "markup_pct", "unit_cost_usd", "ref_cost_usd", "category", "is_active"];

export const touchesPrice = (body: Record<string, unknown>): boolean => PRICE_FIELDS.some((f) => f in body);

/**
 * FLUX: картинки через images-API, чат берёт за картинку. Так же решает сервер
 * (core/ai/model_billing.py, is_flux_image_model).
 */
export function isFluxModel(openrouterId: string): boolean {
  const id = openrouterId.toLowerCase().split(":")[0];
  return id.startsWith("black-forest-labs/") || id.includes("flux.2");
}

/** Картинка, которую чат списывает по токенам × тариф (Nano Banana и др.), а студии — за картинку. */
const chatTokenImage = (m: Model, form: RowForm): boolean =>
  kindOf(form.category) === "image" && !isFluxModel(m.openrouterId);

/**
 * Тариф в текущем режиме нигде не действует — подсказка под полем. У Nano Banana
 * он действует всегда: в чате картинка списывается по токенам × тариф и в режиме
 * «наценка» тоже.
 */
export function tariffIgnored(m: Model, form: RowForm): boolean {
  if (!m.pricing || m.pricing.mode !== "markup") return false;
  const kind = kindOf(form.category);
  if (kind === "video") return true;
  return kind === "image" && m.unitCostUsd !== null && !chatTokenImage(m, form);
}

/** Единица тарифа под полем: у Nano Banana в чате и в студиях она разная. */
export function tariffUnit(m: Model, form: RowForm): string {
  if (!chatTokenImage(m, form)) return TARIFF_UNIT[kindOf(form.category)];
  const byCost = m.pricing?.mode === "markup" && m.unitCostUsd !== null;
  return `в чате — ${TARIFF_UNIT.text}; в студиях — ${byCost ? "по себестоимости" : TARIFF_UNIT.image}`;
}

/* ------------------------------------------------------------------ */
/* Флаги цены                                                          */
/* ------------------------------------------------------------------ */

export type FlagView = { label: string; tone: "wait" | "fail" | "muted"; title: string };

const FLAGS: Record<string, FlagView> = {
  no_cost: {
    label: "нет себестоимости",
    tone: "wait",
    title: "Видео без себестоимости в режиме «наценка» не продаётся; картинка остаётся по тарифу",
  },
  floor: { label: "порог", tone: "muted", title: "Наценка ниже нижнего порога — цену задаёт порог" },
  below_cost: {
    label: "ниже себестоимости",
    tone: "fail",
    title: "Действующая цена ниже себестоимости с нижним порогом — продаётся в убыток",
  },
  chat_below_cost: {
    label: "в чате ниже себестоимости",
    tone: "fail",
    title:
      "Картинка в чате (по тарифу за токены или FLUX как правка с 1 фото) дешевле себестоимости с нижним порогом",
  },
  chat_tariff_stale: {
    label: "в чате не по наценке",
    tone: "wait",
    title:
      "Картинка в чате списывается по тарифу за токены, и он не даёт цену по наценке — нажмите «Пересчитать тариф картинок в чате»",
  },
};

export const flagViews = (flags: readonly string[]): FlagView[] =>
  flags.map((flag) => FLAGS[flag] ?? { label: flag, tone: "muted" as const, title: flag });

/* ------------------------------------------------------------------ */
/* «Добавить модель»: каталог OpenRouter                              */
/* ------------------------------------------------------------------ */

export type CatalogKind = "" | Kind;

export const CATALOG_KINDS: { key: CatalogKind; label: string }[] = [
  { key: "", label: "Все" },
  { key: "video", label: "Видео" },
  { key: "image", label: "Картинки" },
  { key: "text", label: "Текст" },
];

export type CatalogEntry = {
  openrouterId: string;
  name: string;
  fullName: string;
  kind: Kind;
  category: string;
  exists: boolean;
  modelId: number | null;
  isActive: boolean | null;
  vstudioSupported: boolean;
  description: string;
  costText: string | null;
  /** Цена при общей наценке и пороге (у текста — сообщение после пересчёта тарифа). */
  priceMarkup: number | null;
  /** Текст: тариф по себестоимости с наценкой, "8.990". */
  coefficient: string | null;
};

export type Catalog = {
  results: CatalogEntry[];
  count: number;
  truncated: boolean;
  /** Каталоги, которые не ответили: video / text. */
  unavailable: string[];
};

export const CATALOG_QUERY_MAX = 200;

export function catalogUrl(query: string, kind: CatalogKind): string {
  const params = new URLSearchParams();
  const q = query.trim();
  if (q) params.set("q", q);
  if (kind) params.set("kind", kind);
  const qs = params.toString();
  return qs ? `${CATALOG_PATH}?${qs}` : CATALOG_PATH;
}

function parseEntry(v: Row): CatalogEntry | null {
  const openrouterId = text(v.openrouter_id);
  if (!openrouterId) return null;
  const kind = v.kind === "video" || v.kind === "image" || v.kind === "text" ? v.kind : null;
  if (!kind) return null;
  return {
    openrouterId,
    name: text(v.name) || openrouterId,
    fullName: text(v.full_name),
    kind,
    category: text(v.category) || (kind === "text" ? "chat" : kind),
    exists: v.exists === true,
    modelId: int(v.model_id),
    isActive: typeof v.is_active === "boolean" ? v.is_active : null,
    vstudioSupported: v.vstudio_supported === true,
    description: text(v.description),
    costText: text(v.cost_text) || null,
    priceMarkup: int(v.price_markup),
    coefficient: decimalText(v.coefficient),
  };
}

export function parseCatalog(v: unknown): Catalog | null {
  if (!isRow(v) || !Array.isArray(v.results)) return null;
  const results = rows(v.results)
    .map(parseEntry)
    .filter((e): e is CatalogEntry => e !== null);
  const catalogs = isRow(v.catalogs) ? v.catalogs : {};
  return {
    results,
    count: int(v.count) ?? results.length,
    truncated: v.truncated === true,
    unavailable: Object.entries(catalogs)
      .filter(([, state]) => state === "unavailable")
      .map(([name]) => name),
  };
}

/** Тело POST models/: название и категорию шлём, только если их поменяли. */
export function addBody(entry: CatalogEntry, name: string, category: string): Record<string, unknown> {
  const body: Record<string, unknown> = { openrouter_id: entry.openrouterId };
  const typed = name.trim();
  if (typed && typed !== entry.name) body.name = typed;
  if (entry.kind === "text" && category && category !== entry.category) body.category = category;
  return body;
}

export const NAME_MAX = 100;

export function addProblem(entry: CatalogEntry, name: string): string | null {
  if (entry.exists) return `Модель «${entry.name}» уже есть в списке.`;
  if (name.trim().length > NAME_MAX) return `Название длиннее ${NAME_MAX} символов.`;
  return null;
}

export type Added = { model: Model; warnings: string[] };

export function parseAdded(v: unknown): Added | null {
  if (!isRow(v)) return null;
  const model = parseModel(v.model);
  if (!model) return null;
  const warnings = Array.isArray(v.warnings) ? v.warnings.map(text).filter(Boolean) : [];
  return { model, warnings };
}

/** 409 «уже есть» отдаёт номер строки — по нему её можно показать. */
export function existingId(data: unknown): number | null {
  return isRow(data) ? int(data.model_id) : null;
}

/* ------------------------------------------------------------------ */
/* «Пересчитать тарифы текста» и «… тариф картинок в чате»             */
/* ------------------------------------------------------------------ */

/**
 * text — тарифы текста от цен OpenRouter за токен; chat_image — тариф картинок
 * Nano Banana в чате (чат берёт за них токены × тариф) от цены картинки по
 * наценке. Ответы и тело POST у обоих одинаковые.
 */
export type RecomputeKind = "text" | "chat_image";

export const RECOMPUTE_PATHS: Record<RecomputeKind, string> = {
  text: RECOMPUTE_PATH,
  chat_image: CHAT_IMAGE_RECOMPUTE_PATH,
};

/** Тексты окна пересчёта: заголовок, единица цены в строке, пустой список, итог. */
export const RECOMPUTE_COPY: Record<
  RecomputeKind,
  { title: string; button: string; subtitle: (tokens: number) => string; unit: string; empty: string; applied: string }
> = {
  text: {
    title: "Пересчитать тарифы текста",
    button: "Пересчитать тарифы текста",
    subtitle: (tokens) => `Тариф от себестоимости OpenRouter с наценкой. Цена — за сообщение в ${tokens} токенов.`,
    unit: "сообщение",
    empty: "Включённых текстовых моделей нет.",
    applied: "Тарифы текста обновлены",
  },
  chat_image: {
    title: "Пересчитать тариф картинок в чате",
    button: "Тариф картинок в чате",
    subtitle: (tokens) =>
      `Чат берёт за картинку Nano Banana токены × тариф. Тариф подгоняется под цену картинки по наценке — на картинку в ~${tokens} токенов.`,
    unit: "картинка в чате",
    empty: "Включённых моделей картинок, которые чат списывает по токенам, нет.",
    applied: "Тарифы картинок в чате обновлены",
  },
};

export type RecomputeStatus = "ok" | "unchanged" | "no_price" | "no_cost" | "too_expensive" | "no_basis";

export type RecomputeRow = {
  id: number;
  name: string;
  openrouterId: string;
  isActive: boolean;
  oldCoefficient: string;
  newCoefficient: string | null;
  /** Цена единицы (сообщения или картинки в чате) с нынешним и новым тарифом. */
  oldCredits: number | null;
  newCredits: number | null;
  deltaPct: number | null;
  priceText: string | null;
  markupPct: string | null;
  markupSource: "model" | "global";
  /** Картинки: студии в режиме «по-старому» берут этот же тариф за картинку — было и станет. */
  legacyStudioOld: number | null;
  legacyStudioNew: number | null;
  status: RecomputeStatus;
};

export type Recompute = {
  kind: RecomputeKind;
  mode: PricingMode;
  canApply: boolean;
  applyBlocked: string | null;
  markupPct: string | null;
  floorPct: string | null;
  basisLine: string;
  tokens: number;
  catalogOk: boolean;
  rows: RecomputeRow[];
};

const STATUSES: readonly RecomputeStatus[] = ["ok", "unchanged", "no_price", "no_cost", "too_expensive", "no_basis"];

export const STATUS_LABEL: Record<RecomputeStatus, string> = {
  ok: "пересчитается",
  unchanged: "уже так",
  no_price: "нет цены в каталоге",
  no_cost: "нет себестоимости",
  too_expensive: "слишком дорогая",
  no_basis: "нет пакета с ценой",
};

export const STATUS_HINT: Record<RecomputeStatus, string> = {
  ok: "Новый тариф по себестоимости OpenRouter с наценкой",
  unchanged: "Тариф уже равен расчётному",
  no_price: "OpenRouter не сообщает цену этой модели — тариф не меняем",
  no_cost: "Себестоимость картинки не задана — введите её в строке модели",
  too_expensive: "Расчётный тариф больше 999,999 — задайте его вручную",
  no_basis: "Нет активного пакета с ценой: не из чего считать цену кредита",
};

function parseRecomputeRow(v: Row): RecomputeRow | null {
  const id = int(v.id);
  if (id === null) return null;
  const status = STATUSES.find((s) => s === v.status) ?? "no_price";
  return {
    id,
    name: text(v.name) || `Модель №${id}`,
    openrouterId: text(v.openrouter_id),
    isActive: v.is_active === true,
    oldCoefficient: decimalText(v.old_coefficient) ?? "0",
    newCoefficient: decimalText(v.new_coefficient),
    oldCredits: int(v.old_message_credits),
    newCredits: int(v.new_message_credits),
    deltaPct: num(v.delta_pct),
    priceText: text(v.price_text) || null,
    markupPct: decimalText(v.markup_pct),
    markupSource: v.markup_source === "model" ? "model" : "global",
    legacyStudioOld: int(v.legacy_studio_old),
    legacyStudioNew: int(v.legacy_studio_new),
    status,
  };
}

export function parseRecompute(v: unknown): Recompute | null {
  if (!isRow(v) || !Array.isArray(v.rows)) return null;
  const kind: RecomputeKind = v.kind === "chat_image" ? "chat_image" : "text";
  return {
    kind,
    mode: v.mode === "markup" ? "markup" : "legacy",
    canApply: v.can_apply === true,
    applyBlocked: text(v.apply_blocked) || null,
    markupPct: decimalText(v.markup_pct),
    floorPct: decimalText(v.floor_pct),
    basisLine: text(v.basis_line),
    tokens: int(v.tokens) ?? (kind === "text" ? 2000 : 1450),
    catalogOk: v.catalog !== "unavailable",
    rows: rows(v.rows)
      .map(parseRecomputeRow)
      .filter((r): r is RecomputeRow => r !== null),
  };
}

export function recomputeUrl(ids: readonly number[] = [], kind: RecomputeKind = "text"): string {
  const path = RECOMPUTE_PATHS[kind];
  return ids.length ? `${path}?ids=${ids.join(",")}` : path;
}

/** «в студиях по-старому 12 → 15 кр»: тариф Nano Banana — ещё и цена картинки в режиме legacy. */
export function legacyStudioText(row: RecomputeRow): string | null {
  if (row.legacyStudioOld === null || row.legacyStudioNew === null) return null;
  if (row.legacyStudioOld === row.legacyStudioNew) return `в студиях по-старому — ${row.legacyStudioOld} кр, без изменений`;
  return `в студиях по-старому — ${row.legacyStudioOld} → ${row.legacyStudioNew} кр`;
}

/** Строку можно применить: новый тариф посчитан и отличается от нынешнего. */
export const applicable = (row: RecomputeRow): boolean => row.status === "ok" && row.newCoefficient !== null;

/** Что отмечено сразу: всё, что пересчитается. */
export const defaultPicked = (preview: Recompute): Set<number> =>
  new Set(preview.rows.filter(applicable).map((r) => r.id));

/**
 * Свежий предпросмотр (после 409 «цены изменились»): отметки остаются у
 * строк, которые по-прежнему можно применить; снятые остаются снятыми.
 */
export function keepPicked(picked: ReadonlySet<number>, fresh: Recompute): Set<number> {
  return new Set(fresh.rows.filter((r) => applicable(r) && picked.has(r.id)).map((r) => r.id));
}

/** Тело POST: ровно те тарифы, что показаны в предпросмотре. */
export function applyBody(preview: Recompute, picked: ReadonlySet<number>): Record<string, unknown> {
  const items = preview.rows
    .filter((r) => applicable(r) && picked.has(r.id))
    .map((r) => ({ id: r.id, coefficient: r.newCoefficient }));
  return { confirm: true, items };
}

/** Свежий предпросмотр из отказа 409 (сервер прикладывает его к «цены изменились»). */
export function previewFromRefusal(data: unknown): Recompute | null {
  return isRow(data) ? parseRecompute(data.preview) : null;
}

export function appliedCount(data: unknown): number {
  return isRow(data) && Array.isArray(data.updated) ? data.updated.length : 0;
}

/** «−91,2 %» / «+4 %»; null — сравнивать не с чем. */
export function deltaText(delta: number | null): string | null {
  if (delta === null) return null;
  if (delta === 0) return "0 %";
  return `${delta > 0 ? "+" : "−"}${ru(Math.abs(delta))} %`;
}

/** Тариф строкой из сервера ("17.000") → «17» / «1,224». */
export const coefText = (value: string): string => ru(String(Number(value)));
