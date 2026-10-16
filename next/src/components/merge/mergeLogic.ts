/**
 * «Склейка видео»: чистая логика страницы /merge — порядок и состав
 * фрагментов, пределы, подписи, разбор ошибок. Без React и без запросов —
 * её проверяет mergeLogic.test.mjs.
 *
 * Порядок меняется на месте (кнопки ↑/↓, перетаскивание), добавление и
 * удаление — тоже; на сервер уходит весь список целиком (PATCH items).
 * Пределы проверяем и здесь, до запроса: сервер отказывает всему изменению
 * сразу, и человек иначе узнавал бы о пределе только после нажатия.
 */
import { MERGE_ERROR_RU, MERGE_FAIL_RU } from "./mergeText";
import type {
  MergeAspect,
  MergeFit,
  MergeItem,
  MergeLimits,
  MergeProgress,
  MergeSourceCard,
  MergeSourceType,
  MergeStatus,
  MergeTab,
} from "./mergeTypes";

export const DEFAULT_LIMITS: MergeLimits = { min_fragments: 2, max_fragments: 30, max_total_s: 300, retention_days: 30 };
/** Сервер округляет сумму длительностей и прощает полсекунды сверх предела. */
export const DURATION_TOLERANCE_S = 0.5;
export const DEFAULT_PRICE = 20;
/** Адрес страницы склейки. */
export const MERGE_PATH = "/merge";
/** Видеостудия открыта всем — тот же флаг, что у пункта меню сайта и колонки мультстудии. */
export const VSTUDIO_NAV = process.env.NEXT_PUBLIC_VSTUDIO_NAV === "1";

export const TABS: readonly MergeTab[] = ["vstudio", "cartoon", "chat"];
export const ASPECTS: readonly MergeAspect[] = ["16:9", "9:16", "1:1"];
export const FITS: readonly MergeFit[] = ["pad", "crop"];
const SOURCE_TYPES: readonly MergeSourceType[] = ["vstudio", "cartoon_scene", "cartoon_movie", "chat"];

const UID_RE = /^[0-9a-f]{32}$/;
/** id источника в ссылке ?add=: число мультфильма или uid дубля. */
const SOURCE_ID_RE = /^[A-Za-z0-9_-]{1,64}$/;

export function isUid(v: unknown): v is string {
  return typeof v === "string" && UID_RE.test(v);
}

export function isActive(status: MergeStatus | null | undefined): boolean {
  return status === "queued" || status === "rendering";
}

/** Фрагменты, формат и заполнение можно менять (готовую — нельзя, только название). */
export function isEditable(status: MergeStatus | null | undefined): boolean {
  return status == null || status === "draft" || status === "failed" || status === "expired";
}

export function isAspect(v: unknown): v is MergeAspect {
  return typeof v === "string" && (ASPECTS as readonly string[]).includes(v);
}

export function isFit(v: unknown): v is MergeFit {
  return typeof v === "string" && (FITS as readonly string[]).includes(v);
}

export function isTab(v: unknown): v is MergeTab {
  return typeof v === "string" && (TABS as readonly string[]).includes(v);
}

/* ------------------------------------------------------------------ */
/* Фрагменты                                                           */
/* ------------------------------------------------------------------ */

/**
 * Фрагмент в редакторе: key — свой на каждую карточку, а не type+id: один и
 * тот же ролик можно поставить в склейку дважды.
 */
export type LocalItem = MergeItem & { key: string };

export type ItemRef = { type: MergeSourceType; id: string };

export function cardToItem(card: MergeSourceCard): MergeItem {
  return {
    type: card.type,
    id: card.id,
    title: card.title,
    subtitle: card.subtitle,
    poster: card.poster,
    url: card.url,
    duration_s: card.duration_s,
    width: card.width,
    height: card.height,
    available: true,
  };
}

/**
 * Ответ сервера → карточки редактора. Ключи берём у прежних карточек на тех
 * же местах (тот же ролик): иначе после каждого сохранения React пересоздавал
 * бы строки, и фокус с кнопки ↑ пропадал бы.
 */
export function toLocal(items: MergeItem[], prev: LocalItem[], makeKey: () => string): LocalItem[] {
  return items.map((item, i) => {
    const old = prev[i];
    const key = old && old.type === item.type && old.id === item.id ? old.key : makeKey();
    return { ...item, key };
  });
}

export function itemRefs(items: readonly ItemRef[]): ItemRef[] {
  return items.map(({ type, id }) => ({ type, id }));
}

/** Слепок того, что уходит на сервер: совпал — сохранять нечего. */
export function signature(items: readonly ItemRef[], aspect: MergeAspect, fit: MergeFit): string {
  return `${aspect}|${fit}|${items.map((i) => `${i.type}:${i.id}`).join(",")}`;
}

export function totalDuration(items: readonly { duration_s: number | null }[]): number {
  const sum = items.reduce((acc, i) => acc + (typeof i.duration_s === "number" && i.duration_s > 0 ? i.duration_s : 0), 0);
  return Math.round(sum * 10) / 10;
}

/** «M:SS»; секунды округляются. */
export function formatDuration(seconds: number | null | undefined): string {
  const s = Math.max(0, Math.round(typeof seconds === "number" && Number.isFinite(seconds) ? seconds : 0));
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
}

/** Переставить фрагмент; за краями — к краю. Ничего не поменялось — тот же массив. */
export function moveItem<T>(list: readonly T[], from: number, to: number): T[] {
  if (from < 0 || from >= list.length) return list as T[];
  const target = Math.max(0, Math.min(list.length - 1, to));
  if (target === from) return list as T[];
  const next = list.slice();
  const [moved] = next.splice(from, 1);
  next.splice(target, 0, moved);
  return next;
}

export function removeAt<T>(list: readonly T[], index: number): T[] {
  if (index < 0 || index >= list.length) return list as T[];
  return list.filter((_, i) => i !== index);
}

export type AddRefusal =
  | { code: "too_many_fragments"; max: number }
  | { code: "too_long"; max_s: number; total_s: number }
  | { code: "source_unreadable" };

/** Можно ли добавить ролик: null — можно, иначе почему нет (кнопка «+» гаснет с подсказкой). */
export function addRefusal(
  items: readonly { duration_s: number | null }[],
  card: { duration_s: number | null },
  limits: MergeLimits = DEFAULT_LIMITS,
): AddRefusal | null {
  if (!(typeof card.duration_s === "number" && card.duration_s > 0)) return { code: "source_unreadable" };
  if (items.length >= limits.max_fragments) return { code: "too_many_fragments", max: limits.max_fragments };
  const total = totalDuration(items) + card.duration_s;
  if (total > limits.max_total_s + DURATION_TOLERANCE_S) {
    return { code: "too_long", max_s: limits.max_total_s, total_s: Math.round(total * 10) / 10 };
  }
  return null;
}

export type LocalBlock =
  | { code: "too_few_fragments"; min: number }
  | { code: "too_many_fragments"; max: number }
  | { code: "source_unavailable"; index: number }
  | { code: "source_unreadable"; index: number }
  | { code: "too_long"; total_s: number; max_s: number }
  /** Идёт другая склейка — сервер ответил бы 409 busy. */
  | { code: "busy" };

/**
 * Почему «Склеить» сейчас нельзя — по тому, что на экране (сервер проверит то
 * же при запуске). Первая причина по порядку проверок сервера.
 */
export function renderBlock(
  items: readonly { available: boolean; duration_s: number | null }[],
  limits: MergeLimits = DEFAULT_LIMITS,
): LocalBlock | null {
  if (items.length < limits.min_fragments) return { code: "too_few_fragments", min: limits.min_fragments };
  if (items.length > limits.max_fragments) return { code: "too_many_fragments", max: limits.max_fragments };
  const gone = items.findIndex((i) => !i.available);
  if (gone >= 0) return { code: "source_unavailable", index: gone };
  const unreadable = items.findIndex((i) => !(typeof i.duration_s === "number" && i.duration_s > 0));
  if (unreadable >= 0) return { code: "source_unreadable", index: unreadable };
  const total = totalDuration(items);
  if (total > limits.max_total_s + DURATION_TOLERANCE_S) return { code: "too_long", total_s: total, max_s: limits.max_total_s };
  return null;
}

/* ------------------------------------------------------------------ */
/* Перетаскивание                                                      */
/* ------------------------------------------------------------------ */

/**
 * Куда встанет перетаскиваемый фрагмент: столько других, сколько их серединок
 * выше указателя. mids — середины строк в исходном порядке (в координатах
 * прокрутки), y — где сейчас указатель.
 */
export function dropIndex(mids: readonly number[], from: number, y: number): number {
  let index = 0;
  mids.forEach((mid, i) => {
    if (i !== from && mid < y) index += 1;
  });
  return index;
}

/** Насколько сдвинуть строку i, пока строку from тащат на место to: соседи расступаются. */
export function shiftFor(i: number, from: number, to: number, size: number): number {
  if (i === from || from === to) return 0;
  if (from < to && i > from && i <= to) return -size;
  if (from > to && i >= to && i < from) return size;
  return 0;
}

/* ------------------------------------------------------------------ */
/* Ссылка «Открыть в склейке»                                          */
/* ------------------------------------------------------------------ */

/**
 * ?add=cartoon_movie:12,vstudio:<uid> → фрагменты новой склейки. Чужое и
 * кривое отбрасываем молча: сервер всё равно примет только свои ролики.
 */
export function parseAddParam(value: string | null | undefined, max = DEFAULT_LIMITS.max_fragments): ItemRef[] {
  if (!value) return [];
  const out: ItemRef[] = [];
  for (const part of value.split(",")) {
    const [type, id, extra] = part.trim().split(":");
    if (extra !== undefined || !id) continue;
    if (!(SOURCE_TYPES as readonly string[]).includes(type) || !SOURCE_ID_RE.test(id)) continue;
    out.push({ type: type as MergeSourceType, id });
    if (out.length >= max) break;
  }
  return out;
}

/** Ссылка на страницу склейки с готовыми фрагментами. */
export function addHref(items: readonly ItemRef[]): string {
  const list = items.map((i) => `${i.type}:${i.id}`).join(",");
  return list ? `${MERGE_PATH}?add=${encodeURIComponent(list)}` : MERGE_PATH;
}

/* ------------------------------------------------------------------ */
/* Подписи                                                             */
/* ------------------------------------------------------------------ */

/** Доля готовности по стадии: заполнение полоски под кадром. */
export function progressShare(progress: MergeProgress | null | undefined): number {
  if (!progress) return 0;
  const total = Math.max(1, progress.total || 1);
  const done = Math.max(0, Math.min(total, progress.done || 0));
  switch (progress.stage) {
    case "preparing":
      return 0.03;
    case "normalizing":
      return 0.05 + (0.85 * done) / total;
    case "joining":
      return 0.92;
    case "saving":
      return 0.97;
    default:
      return 0;
  }
}

/** Какой по счёту фрагмент обрабатывается сейчас (с единицы, не больше их числа). */
export function currentFragment(progress: MergeProgress): number {
  const total = Math.max(1, progress.total || 1);
  return Math.min(total, Math.max(0, progress.done || 0) + 1);
}

/** «ДД.ММ» по местному времени; дата не разобралась — пусто. */
export function shortDate(iso: string | null | undefined): string {
  if (!iso) return "";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "";
  return `${String(d.getDate()).padStart(2, "0")}.${String(d.getMonth() + 1).padStart(2, "0")}`;
}

/** «ГГГГ-ММ-ДД» — имя файла склейки по умолчанию. */
export function fileDate(d: Date): string {
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

/** Имя файла готовой склейки — то же, что у сервера в Content-Disposition: дата окончания. */
export function downloadName(finishedAt: string | null | undefined, now: Date = new Date()): string {
  const d = finishedAt ? new Date(finishedAt) : now;
  return `EsAI-merge-${fileDate(Number.isNaN(d.getTime()) ? now : d)}.mp4`;
}

/**
 * iPhone и iPad (iPadOS выдаёт себя за Mac, но с тачскрином): там <a download>
 * не скачивает, а открывает ролик серой заглушкой — «Скачать» идёт через
 * системное окно «Сохранить видео» (tools/saveMedia), как в студиях.
 */
export function isAppleTouch(userAgent: string, platform: string, maxTouchPoints: number): boolean {
  return /iP(hone|ad|od)/.test(userAgent) || (platform === "MacIntel" && maxTouchPoints > 1);
}

/** Дописать следующую страницу карточек без повторов: новый ролик между загрузками сдвигает страницы. */
export function appendUnique<T extends { type: string; id: string }>(list: readonly T[], more: readonly T[]): T[] {
  const seen = new Set(list.map((c) => `${c.type}:${c.id}`));
  const out = list.slice();
  for (const card of more) {
    const key = `${card.type}:${card.id}`;
    if (seen.has(key)) continue;
    seen.add(key);
    out.push(card);
  }
  return out;
}

/** Паузы перед повторами автосохранения; дальше — ждём правки или «Попробовать снова». */
export const SAVE_RETRY_MS: readonly number[] = [3_000, 10_000, 30_000];

/**
 * Отказ сохранения, который проходит сам: пропала связь, лимит запросов, сбой
 * сервера. Отказ по существу (фрагмент пропал, длиннее 5 минут) повтор не исправит.
 */
export function transientSaveError(code: string): boolean {
  return code === "network" || code === "throttled" || code === "server_error";
}

/** Через сколько повторить сохранение после отказа; 0 — сами больше не повторяем. */
export function saveRetryDelay(code: string, attempt: number, waitS?: unknown): number {
  if (!transientSaveError(code)) return 0;
  const base = SAVE_RETRY_MS[attempt];
  if (base == null) return 0;
  const wait = typeof waitS === "number" && Number.isFinite(waitS) && waitS > 0 ? waitS * 1000 : 0;
  return Math.max(base, wait);
}

/** Рамка кадра готового ролика по формату склейки (ширина / высота). */
export function aspectRatio(aspect: MergeAspect | null | undefined): number {
  if (aspect === "9:16") return 9 / 16;
  if (aspect === "1:1") return 1;
  return 16 / 9;
}

/* ------------------------------------------------------------------ */
/* Ошибки                                                              */
/* ------------------------------------------------------------------ */

export type TextSpec = { key: string; ru: string; params: Record<string, string | number> };

const num = (v: unknown): number | null => (typeof v === "number" && Number.isFinite(v) ? v : null);
const str = (v: unknown): string => (typeof v === "string" ? v : "");

/**
 * Отказ запроса → ключ перевода, русский текст и подстановки. index у
 * фрагмента в отказе — с нуля, в тексте — номер с единицы. Неизвестный код —
 * текст сервера (он уже русский), иначе общий.
 */
export function refusalText(code: string, data: Record<string, unknown> = {}, serverText = ""): TextSpec {
  const field = str(data.field);
  const fieldKey = code === "bad_request" && field && field !== "items" ? `bad_request_${field}` : code;
  const key = MERGE_ERROR_RU[fieldKey] ? fieldKey : code;
  const params: Record<string, string | number> = {};
  const index = num(data.index);
  if (index != null) params.n = index + 1;
  const max = num(data.max);
  if (max != null) params.max = max;
  const credits = num(data.credits);
  if (credits != null) params.credits = credits;
  const total = num(data.total_s);
  if (total != null) params.total = formatDuration(total);
  if (code === "too_many_fragments" && params.max == null) params.max = DEFAULT_LIMITS.max_fragments;
  // Номер фрагмента или длина не пришли — текст с подстановкой вышел бы с дыркой.
  const missing = (code === "too_long" && params.total == null) || (/^source_/.test(code) && params.n == null);
  if (missing) {
    return serverText
      ? { key: "", ru: serverText, params }
      : { key: "merge.err.server_error", ru: MERGE_ERROR_RU.server_error, params };
  }
  const ru = MERGE_ERROR_RU[key];
  if (ru) return { key: `merge.err.${key}`, ru, params };
  return serverText
    ? { key: "", ru: serverText, params }
    : { key: "merge.err.server_error", ru: MERGE_ERROR_RU.server_error, params };
}

/** Неудачная склейка → текст. fragment — номер фрагмента с единицы (error_fragment). */
export function failureText(code: string | null | undefined, fragment: number | null | undefined, serverText = ""): TextSpec {
  const params: Record<string, string | number> = {};
  if (typeof fragment === "number" && fragment > 0) params.n = fragment;
  const known = code && MERGE_FAIL_RU[code] ? code : null;
  // Код с номером, а номера нет — текст про «Фрагмент №» вышел бы с дыркой.
  if (known && MERGE_FAIL_RU[known].includes("{{n}}") && params.n == null) {
    return serverText
      ? { key: "", ru: serverText, params }
      : { key: "merge.fail.failed", ru: MERGE_FAIL_RU.failed, params };
  }
  if (known) return { key: `merge.fail.${known}`, ru: MERGE_FAIL_RU[known], params };
  if (serverText) return { key: "", ru: serverText, params };
  return { key: "merge.fail.failed", ru: MERGE_FAIL_RU.failed, params };
}

/** Причина, по которой кнопка «Склеить» погашена, — тем же текстом, что у отказа сервера. */
export function blockText(block: LocalBlock): TextSpec {
  switch (block.code) {
    case "too_few_fragments":
      return refusalText("too_few_fragments", { min: block.min });
    case "too_many_fragments":
      return refusalText("too_many_fragments", { max: block.max });
    case "source_unavailable":
      return refusalText("source_unavailable", { index: block.index });
    case "source_unreadable":
      return refusalText("source_unreadable", { index: block.index });
    case "too_long":
      return refusalText("too_long", { total_s: block.total_s, max_s: block.max_s });
    case "busy":
      return refusalText("busy");
  }
}

/** Подставить {{x}} в русский текст (запасной путь, когда перевода нет). */
export function fillText(template: string, params: Record<string, string | number>): string {
  return template.replace(/\{\{\s*(\w+)\s*\}\}/g, (m, name: string) => (name in params ? String(params[name]) : m));
}
