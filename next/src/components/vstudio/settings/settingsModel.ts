/**
 * Видеостудия, правая панель: чистая логика без React.
 *
 * Здесь всё, что панель решает сама: какие значения показать, что выключить
 * и почему, какую цену написать под значением, что сохранить в
 * Project.settings. Итоговую цену и проверки считает только сервер (quote);
 * отсюда — лишь подсказки из ModelJSON.price (images=0).
 *
 * Правило §4.4 «молча к другим значениям не подгоняем» соблюдается так:
 * значения подстраиваются под модель только при явной смене модели или вида
 * (человек сам нажал), а чужое значение из «Изменить» остаётся как есть и
 * показывается выключенным с причиной — сервер вернёт invalid_param с fix.
 *
 * Модуль чистый (без React и сети): его проверяет node-тест settingsModel.test.mjs.
 */
import { trayNumbers } from "@/lib/vstudio/labels";
import type {
  ComposerFrames,
  InputSlot,
  ModelJSON,
  ModelsResponse,
  PriceTable,
  ProjectSettings,
  ShotParams,
  TakeMode,
  TrayItem,
  VsKind,
} from "@/lib/vstudio/types";
import type { TextRef } from "./settingsText";

export const AUTO = "auto";
/** Предел seed у компилятора (SEED_MAX в core/vstudio/compiler.py). */
export const SEED_MAX = 4294967295;
/** Предел негатива у компилятора (NEGATIVE_MAX). */
export const NEGATIVE_MAX = 2000;
/** Пауза перед PATCH projects/<uid>/: человек щёлкает значения подряд. */
export const PERSIST_DEBOUNCE_MS = 1000;
/** Больше стольких значений длительности — ряд сворачивается до ходовых. */
export const DURATIONS_COLLAPSE_OVER = 8;
const PREFERRED_DURATIONS = [4, 5, 6, 8, 10, 12, 15, 20, 25, 30];

export const PARAM_KEYS = [
  "duration",
  "resolution",
  "aspect_ratio",
  "generate_audio",
  "seed",
  "negative_prompt",
] as const satisfies readonly (keyof ShotParams)[];

type Models = Pick<ModelsResponse, "video" | "image">;

/** Выбор панели: вид, модель и её параметры. */
export type SettingsChoice = { kind: VsKind; model: string; params: ShotParams };

/** Последний выбор по видам — «Картинка» и обратно не теряет модель видео. */
export type KindMemory = Partial<Record<VsKind, { model: string; params: ShotParams }>>;

/* ------------------------------------------------------------------ */
/* Модели                                                              */
/* ------------------------------------------------------------------ */

export function modelsFor(models: Models | null | undefined, kind: VsKind): ModelJSON[] {
  const list = models ? models[kind] : null;
  return Array.isArray(list) ? list : [];
}

export function findModel(models: Models | null | undefined, id: string | null | undefined, kind?: VsKind): ModelJSON | null {
  if (!models || !id) return null;
  const kinds: VsKind[] = kind ? [kind] : ["video", "image"];
  for (const k of kinds) {
    const hit = modelsFor(models, k).find((m) => m.id === id);
    if (hit) return hit;
  }
  return null;
}

/** Модель по умолчанию: первая доступная по тарифу (сервер уже отсортировал). */
export function defaultModel(list: ModelJSON[]): ModelJSON | null {
  return list.find((m) => !m.locked) ?? list[0] ?? null;
}

/* ------------------------------------------------------------------ */
/* Параметры                                                           */
/* ------------------------------------------------------------------ */

/** Ближайшее из списка; при равенстве — меньшее (как nearest в компиляторе). */
export function nearest(values: number[], target: number): number {
  let best = values[0];
  for (const v of values) {
    const d = Math.abs(v - target);
    const bd = Math.abs(best - target);
    if (d < bd || (d === bd && v < best)) best = v;
  }
  return best;
}

function sameRes(a: unknown, b: unknown): boolean {
  return typeof a === "string" && typeof b === "string" && a.toLowerCase() === b.toLowerCase();
}

/** Параметры из чужих рук (Project.settings, localStorage): только известные поля нужных типов. */
export function sanitizeParams(raw: unknown): ShotParams {
  const out: ShotParams = {};
  if (!raw || typeof raw !== "object" || Array.isArray(raw)) return out;
  const p = raw as Record<string, unknown>;
  if (typeof p.duration === "number" && Number.isInteger(p.duration) && p.duration > 0) out.duration = p.duration;
  if (typeof p.resolution === "string" && p.resolution.length <= 16) out.resolution = p.resolution;
  if (typeof p.aspect_ratio === "string" && p.aspect_ratio.length <= 8) out.aspect_ratio = p.aspect_ratio;
  if (typeof p.generate_audio === "boolean") out.generate_audio = p.generate_audio;
  if (typeof p.seed === "number" && Number.isInteger(p.seed) && p.seed >= 0 && p.seed <= SEED_MAX) out.seed = p.seed;
  if (typeof p.negative_prompt === "string" && p.negative_prompt) {
    out.negative_prompt = p.negative_prompt.slice(0, NEGATIVE_MAX);
  }
  return out;
}

/**
 * Параметры под модель — ТОЛЬКО при явной смене модели или вида: то, что
 * модель умеет, остаётся; остальное — ближайшее или значение по умолчанию.
 * Всё, чего модель не принимает (звук, seed, негатив), убирается, чтобы в
 * запрос не ушло то, чего нет на экране.
 */
export function normalizeParams(model: ModelJSON, kind: VsKind, params: ShotParams = {}): ShotParams {
  const caps = model.caps;
  const d = model.defaults || {};
  const out: ShotParams = {};

  const aspects = caps.aspect_ratios || [];
  const fits = (ar: unknown): ar is string => ar === AUTO || (typeof ar === "string" && aspects.includes(ar));
  if (fits(params.aspect_ratio)) out.aspect_ratio = params.aspect_ratio;
  else if (fits(d.aspect_ratio)) out.aspect_ratio = d.aspect_ratio;
  else out.aspect_ratio = AUTO;

  if (kind === "video") {
    const durs = caps.durations || [];
    const want = typeof params.duration === "number" ? params.duration : d.duration;
    if (durs.length) {
      out.duration = typeof want === "number" && durs.includes(want) ? want : nearest(durs, want ?? durs[0]);
    } else if (typeof want === "number") {
      out.duration = want;
    }

    const res = caps.resolutions || [];
    if (res.length) {
      out.resolution =
        res.find((r) => sameRes(r, params.resolution)) ?? res.find((r) => sameRes(r, d.resolution)) ?? res[0];
    } else if (params.resolution || d.resolution) {
      out.resolution = params.resolution || d.resolution;
    }

    // Звук по умолчанию включён — так же решает компилятор, когда поле не пришло.
    if (caps.audio) out.generate_audio = typeof params.generate_audio === "boolean" ? params.generate_audio : true;
    if (caps.negative && params.negative_prompt) out.negative_prompt = params.negative_prompt;
  }
  if (caps.seed && typeof params.seed === "number") out.seed = params.seed;
  return out;
}

const emptyish = (v: unknown) => v === undefined || v === null || v === "";

/**
 * Патч для composer/params (Partial-слияние): изменившиеся ключи, а удалённые —
 * явным undefined (JSON.stringify и quoteKey их просто не увидят).
 */
export function diffParams(prev: ShotParams, next: ShotParams): Partial<ShotParams> {
  const patch: Partial<ShotParams> = {};
  for (const k of PARAM_KEYS) {
    const a = (prev as Record<string, unknown>)[k];
    const b = (next as Record<string, unknown>)[k];
    if (emptyish(a) && emptyish(b)) continue;
    if (a !== b) (patch as Record<string, unknown>)[k] = emptyish(b) ? undefined : b;
  }
  return patch;
}

/** Патч composer/params поверх параметров — так же, как его применяет редьюсер (undefined удаляет ключ). */
export function applyParamsPatch(params: ShotParams, patch: Partial<ShotParams>): ShotParams {
  const out: ShotParams = { ...params, ...patch };
  for (const [k, v] of Object.entries(patch)) {
    if (v === undefined) delete (out as Record<string, unknown>)[k];
  }
  return out;
}

/** Без пустых значений — для сохранения и сравнения. */
export function cleanParams(params: ShotParams | null | undefined): ShotParams {
  const out: ShotParams = {};
  for (const k of PARAM_KEYS) {
    const v = (params as Record<string, unknown> | null | undefined)?.[k];
    if (!emptyish(v)) (out as Record<string, unknown>)[k] = v;
  }
  return out;
}

/** Показать значение как выбранное: явное или значение модели по умолчанию. */
export function shownParams(model: ModelJSON | null, kind: VsKind, params: ShotParams): ShotParams {
  if (!model) return params;
  const d = model.defaults || {};
  const out: ShotParams = { ...params };
  if (out.aspect_ratio == null) out.aspect_ratio = d.aspect_ratio ?? AUTO;
  if (kind === "video") {
    if (out.duration == null && d.duration != null) out.duration = d.duration;
    if (out.resolution == null && d.resolution != null) out.resolution = d.resolution;
    if (out.generate_audio == null && model.caps.audio) out.generate_audio = true;
  }
  return out;
}

/* ------------------------------------------------------------------ */
/* Смена модели и вида                                                 */
/* ------------------------------------------------------------------ */

export function switchModelChoice(
  models: Models | null | undefined,
  kind: VsKind,
  modelId: string,
  prevParams: ShotParams,
): SettingsChoice | null {
  const model = findModel(models, modelId, kind);
  if (!model) return null;
  return { kind, model: model.id, params: normalizeParams(model, kind, prevParams) };
}

/**
 * Переключение «Видео / Картинка»: модель вида — последняя выбранная в этой
 * вкладке, иначе первая доступная. Пропорция переносится, если подходит.
 */
export function switchKindChoice(
  models: Models | null | undefined,
  kind: VsKind,
  prevParams: ShotParams,
  memory?: KindMemory | null,
): SettingsChoice | null {
  const list = modelsFor(models, kind);
  if (!list.length) return null;
  const mem = memory?.[kind];
  const remembered = mem ? list.find((m) => m.id === mem.model && !m.locked) : undefined;
  const model = remembered ?? defaultModel(list);
  if (!model) return null;
  const base: ShotParams = remembered && mem ? mem.params : { aspect_ratio: prevParams.aspect_ratio };
  return { kind, model: model.id, params: normalizeParams(model, kind, base) };
}

function isKind(v: unknown): v is VsKind {
  return v === "video" || v === "image";
}

export function memoryFromSettings(settings: ProjectSettings | null | undefined): KindMemory {
  const raw = settings?.by_kind;
  const out: KindMemory = {};
  if (!raw || typeof raw !== "object" || Array.isArray(raw)) return out;
  for (const k of ["video", "image"] as const) {
    const e = (raw as Record<string, unknown>)[k];
    if (e && typeof e === "object" && typeof (e as { model?: unknown }).model === "string") {
      out[k] = { model: (e as { model: string }).model, params: sanitizeParams((e as { params?: unknown }).params) };
    }
  }
  return out;
}

/** Выбор из Project.settings; null — там нет модели или она больше недоступна. */
export function choiceFromSettings(
  models: Models | null | undefined,
  settings: ProjectSettings | null | undefined,
): SettingsChoice | null {
  if (!settings || !isKind(settings.kind) || typeof settings.model !== "string") return null;
  const model = modelsFor(models, settings.kind).find((m) => m.id === settings.model);
  if (!model || model.locked) return null;
  return { kind: settings.kind, model: model.id, params: normalizeParams(model, settings.kind, sanitizeParams(settings.params)) };
}

/**
 * Начальный выбор, когда в композере модели нет: сначала настройки проекта,
 * потом последний выбор в этой вкладке браузера, потом первая доступная модель
 * нужного вида (если у вида моделей нет — другого вида).
 */
export function initialChoice(
  models: Models | null | undefined,
  preferredKind: VsKind,
  opts: { settings?: ProjectSettings | null; memory?: KindMemory | null; params?: ShotParams } = {},
): SettingsChoice | null {
  const fromSettings = choiceFromSettings(models, opts.settings);
  if (fromSettings) return fromSettings;
  const kinds: VsKind[] = preferredKind === "video" ? ["video", "image"] : ["image", "video"];
  for (const kind of kinds) {
    const c = switchKindChoice(models, kind, opts.params || {}, opts.memory);
    if (c) return c;
  }
  return null;
}

/* ------------------------------------------------------------------ */
/* Project.settings                                                    */
/* ------------------------------------------------------------------ */

/** Что уходит в PATCH: прежние ключи проекта сохраняются, наши — перезаписываются. */
export function settingsPayload(
  prev: ProjectSettings | null | undefined,
  choice: SettingsChoice,
  memory?: KindMemory | null,
): ProjectSettings {
  const params = cleanParams(choice.params);
  const byKind: KindMemory = { ...memoryFromSettings(prev), ...(memory || {}) };
  byKind[choice.kind] = { model: choice.model, params };
  for (const k of ["video", "image"] as const) {
    const e = byKind[k];
    if (e) byKind[k] = { model: e.model, params: cleanParams(e.params) };
  }
  return { ...(prev || {}), kind: choice.kind, model: choice.model, params, by_kind: byKind };
}

function stable(v: unknown): unknown {
  if (Array.isArray(v)) return v.map(stable);
  if (v && typeof v === "object") {
    return Object.fromEntries(
      Object.keys(v as Record<string, unknown>)
        .sort()
        .map((k) => [k, stable((v as Record<string, unknown>)[k])]),
    );
  }
  return v;
}

/** Ключ для «изменилось ли»: только вид, модель и параметры. */
export function settingsKey(settings: ProjectSettings | null | undefined): string {
  if (!settings) return "";
  return JSON.stringify(stable({ kind: settings.kind ?? null, model: settings.model ?? null, params: cleanParams(settings.params) }));
}

/* ------------------------------------------------------------------ */
/* Цены-подсказки (images=0; итог — только из quote)                   */
/* ------------------------------------------------------------------ */

export function priceTableFor(model: ModelJSON | null | undefined, aspect?: string | null): PriceTable | null {
  const p = model?.price;
  if (!p) return null;
  if (aspect && aspect !== AUTO && p.by_aspect && p.by_aspect[aspect]) return p.by_aspect[aspect];
  return p.table || null;
}

function row(table: PriceTable, res: string | null | undefined): Record<string, number> | null {
  if (!res) return null;
  if (table[res]) return table[res];
  const key = Object.keys(table).find((k) => sameRes(k, res));
  return key ? table[key] : null;
}

export function priceHint(
  model: ModelJSON | null | undefined,
  at: { duration?: number | null; resolution?: string | null; aspect?: string | null },
): number | null {
  const table = priceTableFor(model, at.aspect);
  if (!table || at.duration == null) return null;
  const r = row(table, at.resolution);
  const v = r?.[String(at.duration)];
  return typeof v === "number" && Number.isFinite(v) ? v : null;
}

/** Цена зависит от пропорций (Seedance 21:9) — тогда подписываем её и под пропорциями. */
export function aspectAffectsPrice(model: ModelJSON | null | undefined): boolean {
  const by = model?.price?.by_aspect;
  return !!by && Object.keys(by).length > 0;
}

/** Ряд длительностей: длинный список (Seedance 2.5: 4…30) сворачивается до ходовых. */
export function visibleDurations(all: number[], current: number | null | undefined, expanded: boolean): number[] {
  if (expanded || all.length <= DURATIONS_COLLAPSE_OVER) return all;
  const set = new Set<number>([all[0], all[all.length - 1], ...all.filter((d) => PREFERRED_DURATIONS.includes(d))]);
  if (current != null && all.includes(current)) set.add(current);
  return Array.from(set).sort((a, b) => a - b);
}

/* ------------------------------------------------------------------ */
/* Материалы запроса и режим                                           */
/* ------------------------------------------------------------------ */

export type InputCounts = {
  /** Включённые референсы (без упавших загрузок). */
  refs: number;
  refsExcluded: number;
  first: boolean;
  last: boolean;
  /** Сколько своих загрузок уйдёт (для «без фото реальных людей»). */
  uploads: number;
};

const alive = (it: TrayItem | null | undefined): it is TrayItem => !!it && it.status !== "failed";

export function countInputs(tray: TrayItem[], frames: ComposerFrames): InputCounts {
  let refs = 0;
  let refsExcluded = 0;
  let uploads = 0;
  const isUpload = (it: TrayItem) => (it.asset ? it.asset.source === "upload" : true);
  for (const it of tray) {
    if (!alive(it)) continue;
    if (!it.included) {
      refsExcluded++;
      continue;
    }
    refs++;
    if (isUpload(it)) uploads++;
  }
  const first = alive(frames.first_frame) && frames.first_frame.included;
  const last = alive(frames.last_frame) && frames.last_frame.included;
  if (first && isUpload(frames.first_frame as TrayItem)) uploads++;
  if (last && isUpload(frames.last_frame as TrayItem)) uploads++;
  return { refs, refsExcluded, first, last, uploads };
}

export type ModeIssue = "conflict" | "refsOff" | null;
export type LocalMode = { mode: TakeMode; issue: ModeIssue; pinK: number | null };

/**
 * Режим, как его выберет компилятор (§4.4 п. 2) — для объяснения «как модель
 * использует ваши фото» без ожидания quote. Если свежий quote есть, его mode главнее.
 */
export function localMode(kind: VsKind, model: ModelJSON | null, c: InputCounts): LocalMode {
  const refsOn = !!model && model.caps.refs.image > 0;
  if (kind === "image") {
    return { mode: c.refs ? "i2i" : "t2i", issue: c.refs && !refsOn ? "refsOff" : null, pinK: null };
  }
  const frames = c.first || c.last;
  if (!c.refs && !frames) return { mode: "t2v", issue: null, pinK: null };
  if (!c.refs) return { mode: c.first && !c.last ? "i2v" : "flf2v", issue: null, pinK: null };
  if (!frames) return { mode: "r2v", issue: refsOn ? null : "refsOff", pinK: null };
  if (!refsOn) return { mode: "r2v", issue: "refsOff", pinK: null };
  if (model && model.caps.frames_with_refs === "soft_pin") {
    return c.first ? { mode: "r2v_pin", issue: null, pinK: c.refs + 1 } : { mode: "r2v", issue: null, pinK: null };
  }
  return { mode: "r2v", issue: "conflict", pinK: null };
}

/** Veo + фото-референсы → только 8 с (ref_forces_duration). null — не форсирует. */
export function forcedDuration(kind: VsKind, model: ModelJSON | null, c: InputCounts): number | null {
  if (kind !== "video" || !model) return null;
  const f = model.caps.ref_forces_duration;
  return f && model.caps.refs.image > 0 && c.refs > 0 ? f : null;
}

/* ------------------------------------------------------------------ */
/* Карточки моделей                                                    */
/* ------------------------------------------------------------------ */

function resRank(r: string): number {
  const m = /(\d+)/.exec(r);
  return m ? Number(m[1]) : 0;
}

/** Бейджи возможностей: «до 9 фото», «первый и последний кадр», «звук», «до 15 с», «до 1080p». */
export function modelBadges(model: ModelJSON, kind: VsKind): TextRef[] {
  const caps = model.caps;
  const out: TextRef[] = [];
  if (caps.refs.image > 0) out.push({ key: "settings.badge.refs", params: { n: caps.refs.image } });
  if (kind === "image") return out;
  const frames = caps.frames || [];
  if (frames.includes("first_frame") && frames.includes("last_frame")) out.push({ key: "settings.badge.frames" });
  else if (frames.includes("first_frame")) out.push({ key: "settings.badge.firstFrame" });
  if (caps.audio) out.push({ key: "settings.badge.audio" });
  if (caps.durations?.length) out.push({ key: "settings.badge.duration", params: { n: Math.max(...caps.durations) } });
  if (caps.resolutions?.length > 1) {
    const top = [...caps.resolutions].sort((a, b) => resRank(b) - resRank(a))[0];
    out.push({ key: "settings.badge.resolution", params: { res: top } });
  }
  return out;
}

/** Чем модель не подходит к материалам, которые уже в запросе (видимая причина до выбора). */
export function modelCompat(model: ModelJSON, kind: VsKind, c: InputCounts): TextRef[] {
  const caps = model.caps;
  const out: TextRef[] = [];
  const max = caps.refs.image;
  if (kind === "image") {
    if (c.refs && max === 0) out.push({ key: "settings.compat.refsOff", params: { n: c.refs } });
    else if (c.refs > max) out.push({ key: "settings.compat.tooManyRefs", params: { max, n: c.refs } });
    if (c.first || c.last) out.push({ key: "settings.compat.imageFrames" });
    return out;
  }
  if (c.refs && max === 0) out.push({ key: "settings.compat.refsOff", params: { n: c.refs } });
  else if (c.refs) {
    const pinned = c.first && caps.frames_with_refs === "soft_pin" ? 1 : 0;
    if (c.refs + pinned > max) out.push({ key: "settings.compat.tooManyRefs", params: { max, n: c.refs + pinned } });
  }
  const frames = caps.frames || [];
  if (c.first && !frames.includes("first_frame")) out.push({ key: "settings.compat.noFrames" });
  if (c.last && !frames.includes("last_frame")) out.push({ key: "settings.compat.noLastFrame" });
  if (c.refs && max > 0 && (c.first || c.last) && caps.frames_with_refs !== "soft_pin") {
    out.push({ key: "settings.compat.framesRefs" });
  }
  const forced = forcedDuration(kind, model, c);
  if (forced) out.push({ key: "settings.compat.forced", params: { n: forced } });
  return out;
}

/** Свойства модели для блока «Как модель использует ваши фото». */
export function modelFacts(model: ModelJSON, kind: VsKind): TextRef[] {
  const caps = model.caps;
  const out: TextRef[] = [];
  if (caps.refs.image > 0) out.push({ key: "settings.fact.maxRefs", params: { n: caps.refs.image } });
  if (caps.min_ref_px > 0) out.push({ key: "settings.fact.minPx", params: { n: caps.min_ref_px } });
  if (caps.rejects_real_faces) out.push({ key: "settings.fact.faces" });
  if (kind === "video" && caps.prompt?.lang === "en") out.push({ key: "settings.fact.en" });
  return out;
}

/** «~2 мин» / «~30 с». */
export function etaText(seconds: number | null | undefined): TextRef | null {
  if (!seconds || !Number.isFinite(seconds) || seconds <= 0) return null;
  if (seconds < 60) return { key: "settings.etaSec", params: { n: Math.max(5, Math.round(seconds / 5) * 5) } };
  return { key: "settings.etaMin", params: { n: Math.max(1, Math.round(seconds / 60)) } };
}

/* ------------------------------------------------------------------ */
/* «Как модель использует ваши фото»                                   */
/* ------------------------------------------------------------------ */

export type ExplainTone = "ok" | "muted" | "warn" | "error";

export type ExplainRow = {
  lid: string;
  assetUid?: string;
  preview: string | null;
  slot: InputSlot;
  /** «@Image 1», «—» у выключенного; у кадров пусто — подпись переводит компонент. */
  label: string;
  role: string;
  note: TextRef | null;
  tone: ExplainTone;
};

/** «Image 3» из quote.labels → 3. */
function labelNumber(label: string | undefined): number | null {
  const m = /^Image\s+(\d+)$/.exec(label || "");
  return m ? Number(m[1]) : null;
}

/**
 * Строки блока по лотку и кадрам. Номер @Image N — тот же, что на чипе в лотке
 * и в тексте (labels.trayNumbers, §4.2: позиция среди включённых референсов с
 * uid); если свежий quote уже дал метку — она. У чипа, который ещё грузится,
 * номера нет и здесь — он появится вместе с uid.
 */
export function explainRows(
  kind: VsKind,
  model: ModelJSON | null,
  tray: TrayItem[],
  frames: ComposerFrames,
  opts: { mode?: TakeMode | null; pinK?: number | null; labels?: Record<string, string> | null } = {},
): ExplainRow[] {
  const rows: ExplainRow[] = [];
  const refsOn = !!model && model.caps.refs.image > 0;
  const modelName = model?.name || "";
  // Сколько референсов поместится: при soft_pin первый кадр занимает ещё одно место.
  const maxRefs = model ? model.caps.refs.image : 0;
  const limit = opts.mode === "r2v_pin" ? maxRefs - 1 : maxRefs;
  const numbers = trayNumbers(tray);
  for (const it of tray) {
    const fromQuote = it.assetUid ? labelNumber(opts.labels?.[it.assetUid]) : null;
    const num = it.included ? (fromQuote ?? numbers[it.lid] ?? null) : null;
    let note: TextRef | null = null;
    let tone: ExplainTone = "ok";
    if (it.status === "failed") {
      note = { key: "settings.refFailed" };
      tone = "error";
    } else if (it.status === "deleted") {
      note = { key: "settings.refDeleted" };
      tone = "error";
    } else if (!it.included) {
      note = { key: "settings.refExcluded" };
      tone = "muted";
    } else if (it.status === "uploading" || it.status === "processing") {
      note = { key: "settings.refUploading" };
      tone = "muted";
    } else if (it.status === "pending") {
      note = { key: "settings.refPending" };
      tone = "muted";
    } else if (!refsOn) {
      note = { key: "settings.refIgnored", params: { model: modelName } };
      tone = "warn";
    } else if (num != null && num > limit) {
      note = { key: "settings.refOverflow", params: { model: modelName, max: maxRefs } };
      tone = "warn";
    } else if (!it.role.trim()) {
      note = { key: "settings.refNoRole" };
      tone = "muted";
    }
    rows.push({
      lid: it.lid,
      assetUid: it.assetUid,
      preview: it.preview,
      slot: "reference",
      label: num != null ? `@Image ${num}` : "—",
      role: it.role.trim(),
      note,
      tone,
    });
  }
  for (const slot of ["first_frame", "last_frame"] as const) {
    const it = frames[slot];
    if (!it) continue;
    let note: TextRef | null;
    let tone: ExplainTone = "ok";
    if (it.status === "failed") {
      note = { key: "settings.refFailed" };
      tone = "error";
    } else if (it.status === "deleted") {
      note = { key: "settings.refDeleted" };
      tone = "error";
    } else if (!it.included) {
      note = { key: "settings.refExcluded" };
      tone = "muted";
    } else if (kind === "image") {
      note = { key: "settings.frameImage" };
      tone = "warn";
    } else if (slot === "first_frame" && opts.mode === "r2v_pin" && opts.pinK) {
      note = { key: "settings.framePinned", params: { k: opts.pinK } };
    } else {
      note = { key: slot === "first_frame" ? "settings.frameFirst" : "settings.frameLast" };
    }
    rows.push({ lid: it.lid, assetUid: it.assetUid, preview: it.preview, slot, label: "", role: it.role.trim(), note, tone });
  }
  return rows;
}

/** Пояснение режима одной строкой. */
export function modeText(kind: VsKind, model: ModelJSON | null, lm: LocalMode, c: InputCounts): TextRef {
  const name = model?.name || "";
  if (lm.issue === "refsOff") return { key: "settings.mode.refsOff", params: { model: name } };
  if (lm.issue === "conflict") return { key: "settings.mode.conflict", params: { model: name } };
  switch (lm.mode) {
    case "i2v":
      return { key: "settings.mode.i2v" };
    case "flf2v":
      return { key: c.first ? "settings.mode.flf2v" : "settings.mode.lf" };
    case "r2v":
      return { key: "settings.mode.r2v" };
    case "r2v_pin":
      return { key: "settings.mode.r2v_pin", params: { k: lm.pinK ?? c.refs + 1 } };
    case "i2i":
      return { key: "settings.mode.i2i" };
    case "t2i":
      return { key: "settings.mode.t2i" };
    default:
      return kind === "image" ? { key: "settings.mode.t2i" } : { key: "settings.mode.t2v" };
  }
}

/* ------------------------------------------------------------------ */
/* Чип «Seedance 2.0 · 9:16 · 10 с ▾»                                  */
/* ------------------------------------------------------------------ */

export type ChipParts = { model: string; aspect: string | null; duration: number | null };

export function chipParts(model: ModelJSON | null, kind: VsKind, params: ShotParams): ChipParts {
  const shown = shownParams(model, kind, params);
  return {
    model: model?.name || "",
    aspect: shown.aspect_ratio ?? null,
    duration: kind === "video" && typeof shown.duration === "number" ? shown.duration : null,
  };
}
