/**
 * Карточка «Мультстудия: по умолчанию» в «Настройках»: весь контракт с сервером —
 * здесь (core/cartoon/views.DefaultsAdminView, описание —
 * vstudio2-notes/pricing/CONTRACT_C.md §3.8).
 *
 *   GET   cartoon/manage/defaults/   → значения, что из них выйдет, список моделей, предупреждения
 *   PATCH cartoon/manage/defaults/   { model?, resolution?, duration? } → то же; null — значение из кода
 *
 * С какими моделью, качеством и длительностью начинается новый мультфильм (на
 * сайте и в боте). Сервер применяет их, только если модель включена и умеет
 * эту пару; иначе новые мультфильмы снимаются как в сцене библиотеки, и ответ
 * объясняет почему (warnings). Ответ разбираем как «чужие руки»: запись не
 * того типа карточку не роняет. Модуль чистый — его проверяет cartoonDefaults.test.mjs.
 */
import { clampDuration, clampResolution, findResolution } from "@/components/studio/dockLogic";

export const DEFAULTS_PATH = "cartoon/manage/defaults/";

export type DefaultsModel = {
  id: string;
  name: string;
  /** «Seedance Mini». */
  short: string;
  /** Строка есть в «Моделях». */
  exists: boolean;
  active: boolean;
  /** Модель включена и попадает в док мультстудии. */
  offered: boolean;
  /** Пусто — каталог OpenRouter модель не знает (или строки нет). */
  resolutions: string[];
  durations: number[];
};

export type DefaultsTriple = { model: string; resolution: string; duration: number };

export type CartoonDefaults = DefaultsTriple & {
  /** false — действует значение из кода. */
  stored: { model: boolean; resolution: boolean; duration: boolean };
  codeDefaults: DefaultsTriple;
  /** Что реально получат новые мультфильмы; source=preset — откат на сцену библиотеки. */
  effective: { model: string | null; resolution: string | null; duration: number | null; source: string };
  models: DefaultsModel[];
  warnings: string[];
};

type Row = Record<string, unknown>;

const isRow = (v: unknown): v is Row => typeof v === "object" && v !== null && !Array.isArray(v);
const str = (v: unknown): string => (typeof v === "string" ? v : "");
const int = (v: unknown): number | null => (typeof v === "number" && Number.isInteger(v) ? v : null);

function triple(v: unknown): DefaultsTriple | null {
  if (!isRow(v)) return null;
  const model = str(v.model);
  const resolution = str(v.resolution);
  const duration = int(v.duration);
  return model && resolution && duration ? { model, resolution, duration } : null;
}

function parseModel(v: unknown): DefaultsModel | null {
  if (!isRow(v) || !str(v.id)) return null;
  const id = str(v.id);
  return {
    id,
    name: str(v.name) || id,
    short: str(v.short) || str(v.name) || id,
    exists: v.exists === true,
    active: v.active === true,
    offered: v.offered === true,
    resolutions: Array.isArray(v.resolutions) ? v.resolutions.filter((r): r is string => typeof r === "string") : [],
    durations: Array.isArray(v.durations)
      ? v.durations.filter((d): d is number => typeof d === "number" && Number.isInteger(d))
      : [],
  };
}

/** Ответ GET/PATCH → карточка; null — ответ не похож на настройки. */
export function parseDefaults(raw: unknown): CartoonDefaults | null {
  const own = triple(raw);
  if (!own || !isRow(raw)) return null;
  const stored = isRow(raw.stored) ? raw.stored : {};
  const eff = isRow(raw.effective) ? raw.effective : {};
  return {
    ...own,
    stored: { model: stored.model === true, resolution: stored.resolution === true, duration: stored.duration === true },
    codeDefaults: triple(raw.code_defaults) ?? own,
    effective: {
      model: str(eff.video_model) || null,
      resolution: str(eff.resolution) || null,
      duration: int(eff.duration),
      source: str(eff.source) || "preset",
    },
    models: (Array.isArray(raw.models) ? raw.models : []).map(parseModel).filter((m): m is DefaultsModel => m !== null),
    warnings: (Array.isArray(raw.warnings) ? raw.warnings : []).filter((w): w is string => typeof w === "string" && !!w),
  };
}

export function draftFrom(d: CartoonDefaults): DefaultsTriple {
  return { model: d.model, resolution: d.resolution, duration: d.duration };
}

export function findDefaultsModel(d: CartoonDefaults, id: string): DefaultsModel | null {
  return d.models.find((m) => m.id === id) ?? null;
}

/** Состояние модели словами — рядом с её названием в списке. */
export function modelNote(m: DefaultsModel): string {
  if (!m.exists) return "нет в «Моделях»";
  if (!m.offered) return m.active ? "не видео-модель" : "выключена";
  return "";
}

/** Список качеств: что умеет модель; каталог её не знает — привычные значения. */
export function resolutionOptions(m: DefaultsModel | null, current: string): string[] {
  const base = m && m.resolutions.length ? [...m.resolutions] : ["480p", "720p", "1080p"];
  if (current && !base.some((r) => r.toLowerCase() === current.toLowerCase())) base.push(current);
  return base;
}

/** Список длительностей: что умеет модель; каталог её не знает — 4…15 с. */
export function durationOptions(m: DefaultsModel | null, current: number): number[] {
  const base = m && m.durations.length ? [...m.durations] : Array.from({ length: 12 }, (_, i) => i + 4);
  if (current && !base.includes(current)) base.push(current);
  return base.sort((a, b) => a - b);
}

/**
 * Выбрали другую модель: качество и длительность остаются, если она их умеет,
 * иначе — ближайшие (то же правило, что в доке студии), и строка об этом.
 */
export function pickModel(d: CartoonDefaults, draft: DefaultsTriple, id: string): { draft: DefaultsTriple; notes: string[] } {
  const m = findDefaultsModel(d, id);
  const next = { ...draft, model: id };
  const notes: string[] = [];
  if (!m) return { draft: next, notes };
  const name = m.short || m.name;
  if (m.resolutions.length) {
    const kept = findResolution(m.resolutions, draft.resolution);
    next.resolution = kept ?? clampResolution(m.resolutions, draft.resolution);
    if (!kept) notes.push(`${name} не снимает в ${draft.resolution} — выбрано ${next.resolution}`);
  }
  if (m.durations.length && !m.durations.includes(draft.duration)) {
    next.duration = clampDuration(m.durations, draft.duration);
    notes.push(`${name} не снимает ${draft.duration} с — выбрано ${next.duration} с`);
  }
  return { draft: next, notes };
}

/** Тело PATCH: только то, что поменяли. Пусто — сохранять нечего. */
export function patchBody(draft: DefaultsTriple, saved: DefaultsTriple): Partial<DefaultsTriple> {
  const body: Partial<DefaultsTriple> = {};
  if (draft.model !== saved.model) body.model = draft.model;
  if (draft.resolution !== saved.resolution) body.resolution = draft.resolution;
  if (draft.duration !== saved.duration) body.duration = draft.duration;
  return body;
}

/** Тело PATCH «Вернуть значения из кода»: строки настроек удаляются. */
export const RESET_BODY = { model: null, resolution: null, duration: null } as const;

export function shortName(d: CartoonDefaults, id: string | null): string {
  if (!id) return "—";
  return findDefaultsModel(d, id)?.short || id;
}

/** «Seedance Mini · 480p · 5 с». */
export function tripleText(d: CartoonDefaults, t: { model: string | null; resolution: string | null; duration: number | null }): string {
  return [shortName(d, t.model), t.resolution || "—", t.duration ? `${t.duration} с` : "—"].join(" · ");
}

/** Что сейчас получают новые мультфильмы — одной строкой. */
export function effectiveText(d: CartoonDefaults): string {
  if (d.effective.source === "settings") return `Новые мультфильмы снимаются: ${tripleText(d, d.effective)}.`;
  const preset = d.effective.model ? ` (сейчас это ${tripleText(d, d.effective)})` : "";
  return `Новые мультфильмы снимаются как в сцене библиотеки${preset}.`;
}

/** Все значения — из кода (в настройках ничего не сохранено). */
export function allFromCode(d: CartoonDefaults): boolean {
  return !d.stored.model && !d.stored.resolution && !d.stored.duration;
}

export function errorText(res: { status: number; data?: unknown }, fallback: string): string {
  if (res.status === 0) return "Нет связи с сервером. Проверьте интернет и повторите.";
  if (res.status === 401 || res.status === 403) return "Нет доступа: настройки мультстудии меняют только сотрудники.";
  if (res.status === 429) return "Слишком много запросов подряд. Подождите минуту и повторите.";
  const data = isRow(res.data) ? res.data : {};
  const errors = isRow(data.errors) ? data.errors : {};
  const detail = str(errors.defaults) || str(data.detail);
  return detail || `${fallback} (HTTP ${res.status})`;
}
