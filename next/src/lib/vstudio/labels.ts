/**
 * Видеостудия: метки чипов «@Image N» (§4.2).
 *
 * Номер — позиция среди ВКЛЮЧЁННЫХ фото-референсов в порядке лотка, с
 * единицы. Сервер нумерует тем же правилом (prompt_doc.number_refs), поэтому
 * модель получает ровно то, что видит человек. Перестановка в лотке меняет
 * номера — чипы в тексте перерисовываются сразу, потому что документ хранит
 * uid, а не номер.
 *
 * Здесь же: состояние чипа (ok / pending / failed / excluded / deleted /
 * missing), подсказка и aria («Фото 1 · героиня»), текст для копирования
 * («@Image 1» — как prompt_text сервера) и пункты выбора материалов по «@».
 *
 * Модуль чистый: его грузят и Next, и node-тесты. Переводы — через
 * необязательный t (без него русские тексты по умолчанию).
 */
import { EXCLUDED_TAG, labelTag, numberRefs, type TagIndex, type TagInput, tagIndex } from "./promptDoc";
import type {
  AssetJSON,
  ComposerFrames,
  FrameSlot,
  PickerItem,
  RefChipState,
  RefLabel,
  RefLabels,
  TrayItem,
  Uid,
} from "./types";

/** Перевод: i18next t или совместимая функция (ns задаётся здесь). */
export type LabelT = (key: string, options?: Record<string, unknown>) => unknown;

/** Русские тексты по умолчанию (ns vstudio). */
export const LABEL_RU = {
  "tray.image": "Фото {{n}}",
  "tray.firstFrame": "Первый кадр",
  "tray.lastFrame": "Последний кадр",
  "tray.pending": "Создаётся…",
  "tray.failed": "Не получилось",
  "tray.excluded": "Не учитывается и не оплачивается",
  "tray.deleted": "Удалено",
  "tray.missing": "Фото нет в запросе",
  "tray.photo": "Фото",
} as const;
export type LabelKey = keyof typeof LABEL_RU;

function fill(template: string, params?: Record<string, unknown>): string {
  return template.replace(/\{\{\s*(\w+)\s*\}\}/g, (_, k: string) => String(params?.[k] ?? ""));
}

function tr(t: LabelT | undefined, key: LabelKey, params?: Record<string, unknown>): string {
  const ru = fill(LABEL_RU[key], params);
  if (!t) return ru;
  const out = t(key, { ns: "vstudio", defaultValue: LABEL_RU[key], ...(params || {}) });
  return typeof out === "string" && out ? out : ru;
}

/** Композер в том виде, который нужен меткам (ComposerState подходит целиком). */
export type LabelSource = { tray: readonly TrayItem[]; frames: ComposerFrames };

const FRAME_ORDER: FrameSlot[] = ["first_frame", "last_frame"];

/** Входы запроса так же, как их соберёт api.buildInputs: только чипы с uid. */
export function trayInputs(src: LabelSource): TagInput[] {
  const out: TagInput[] = [];
  let position = 0;
  for (const item of src.tray) {
    if (!item.assetUid) continue;
    out.push({
      asset: item.assetUid,
      slot: "reference",
      position: position++,
      included: item.included,
      kind: item.asset?.kind ?? "image",
    });
  }
  for (const slot of FRAME_ORDER) {
    const item = src.frames[slot];
    if (item?.assetUid) out.push({ asset: item.assetUid, slot, position: 0, included: item.included });
  }
  return out;
}

/** {uid: N} по лотку — то же, что number_refs сервера. */
export function trayRefNumbers(tray: readonly TrayItem[]): Record<Uid, number> {
  return numberRefs(trayInputs({ tray, frames: { first_frame: null, last_frame: null } }));
}

/** Номер для бейджа чипа в лотке по lid (null — выключен, грузится или не картинка). */
export function trayNumbers(tray: readonly TrayItem[]): Record<string, number | null> {
  const byUid = trayRefNumbers(tray);
  const out: Record<string, number | null> = {};
  const used = new Set<Uid>();
  for (const item of tray) {
    const uid = item.assetUid;
    // Второй чип с тем же uid номера не получает: сервер склеивает дубли.
    out[item.lid] = uid && !used.has(uid) && byUid[uid] ? byUid[uid] : null;
    if (uid) used.add(uid);
  }
  return out;
}

/** Состояние чипа по материалу: выключен > удалён > ошибка > создаётся > готов. */
export function chipState(item: TrayItem): RefChipState {
  if (!item.included) return "excluded";
  if (item.status === "deleted") return "deleted";
  if (item.status === "failed" || item.asset?.status === "failed") return "failed";
  if (item.status !== "ready" || item.asset?.status === "pending") return "pending";
  return "ok";
}

const STATE_KEY: Partial<Record<RefChipState, LabelKey>> = {
  pending: "tray.pending",
  failed: "tray.failed",
  deleted: "tray.deleted",
  excluded: "tray.excluded",
};

function joinAria(parts: Array<string | null | undefined>): string {
  return parts.map((p) => (p || "").trim()).filter(Boolean).join(" · ");
}

function aliasOf(asset: AssetJSON | undefined): string {
  return (asset?.label || "").trim();
}

function refLabel(item: TrayItem, n: number | null, t?: LabelT): RefLabel {
  const state = chipState(item);
  const alias = aliasOf(item.asset);
  const role = (item.role || "").trim();
  const num = state === "excluded" ? null : n;
  let text = num ? (alias ? `@${alias}` : `@Image ${num}`) : EXCLUDED_TAG;
  if (state === "deleted") text = `${text} · ${tr(t, "tray.deleted").toLowerCase()}`;
  const who = num ? tr(t, "tray.image", { n: num }) : tr(t, "tray.photo");
  const stateKey = STATE_KEY[state];
  return {
    text,
    n: num,
    slot: "reference",
    state,
    aria: joinAria([who, alias && alias !== role ? alias : "", role, stateKey ? tr(t, stateKey) : ""]),
  };
}

function frameLabel(item: TrayItem, slot: FrameSlot, t?: LabelT): RefLabel {
  const state = chipState(item);
  const name = tr(t, slot === "first_frame" ? "tray.firstFrame" : "tray.lastFrame");
  let text = `@${name}`;
  if (state === "deleted") text = `${text} · ${tr(t, "tray.deleted").toLowerCase()}`;
  const stateKey = STATE_KEY[state];
  return { text, n: null, slot, state, aria: joinAria([name, item.role || "", stateKey ? tr(t, stateKey) : ""]) };
}

/**
 * Метки всех материалов запроса: {uid: {text, n, slot, state, aria}}.
 * Чип, чьего uid здесь нет, рисуется как missingLabel (красный, mention_not_attached).
 */
export function buildRefLabels(src: LabelSource, t?: LabelT): RefLabels {
  const numbers = trayRefNumbers(src.tray);
  const out: RefLabels = {};
  const put = (uid: Uid, label: RefLabel) => {
    const prev = out[uid];
    // Один uid и в лотке, и в слоте: побеждает включённый (сервер берёт его).
    if (!prev || (prev.state === "excluded" && label.state !== "excluded")) out[uid] = label;
  };
  for (const item of src.tray) {
    if (item.assetUid) put(item.assetUid, refLabel(item, numbers[item.assetUid] ?? null, t));
  }
  for (const slot of FRAME_ORDER) {
    const item = src.frames[slot];
    if (item?.assetUid) put(item.assetUid, frameLabel(item, slot, t));
  }
  return out;
}

/** Чип на материал, которого нет в запросе (удалили из лотка, чужой черновик). */
export function missingLabel(t?: LabelT): RefLabel {
  return { text: "@Image ?", n: null, slot: null, state: "missing", aria: tr(t, "tray.missing") };
}

/** Чип только что вставлен, а родитель ещё не положил материал в лоток. */
export function optimisticLabel(t?: LabelT): RefLabel {
  return { text: "@Image …", n: null, slot: "reference", state: "pending", aria: tr(t, "tray.pending") };
}

/**
 * Текст чипа при копировании (TipTap clipboardTextSerializer): так же, как
 * prompt_text сервера — «@Image N», «@Первый кадр», иначе «@Image —». Вставка
 * этого текста снова даёт чипы (§4.3), поэтому кадры — всегда по-русски, как
 * их понимает сервер, даже если на экране чип переведён.
 */
export function copyTagFor(label: RefLabel | null | undefined): string {
  return labelTag(serverLabelOf(label));
}

/**
 * Метка чипа в форме сервера: «Image N», "first_frame", "last_frame" или null.
 * null — материал модели не уйдёт (выключен или его нет в запросе): у сервера
 * такого uid нет в Compiled.labels, и prompt_text показывает «@Image —».
 */
export function serverLabelOf(label: RefLabel | null | undefined): string | null {
  if (!label || label.state === "excluded" || label.state === "missing") return null;
  if (label.slot === "reference" && label.n) return `Image ${label.n}`;
  if (label.slot === "first_frame" || label.slot === "last_frame") return label.slot;
  return null;
}

/** Метки в форме сервера ({uid: "Image 1" | "first_frame" | "last_frame"}) — для promptDoc.renderText. */
export function serverLabels(labels: RefLabels): Record<Uid, string> {
  const out: Record<Uid, string> = {};
  for (const [uid, l] of Object.entries(labels)) {
    const label = serverLabelOf(l);
    if (label) out[uid] = label;
  }
  return out;
}

/**
 * Входы для fromText/перепривязки из готовых меток: номер N у референса,
 * включённые кадры по слотам. Так редактору не нужен весь лоток.
 */
export function inputsFromLabels(labels: RefLabels): TagInput[] {
  const out: TagInput[] = [];
  for (const [uid, l] of Object.entries(labels)) {
    const label = serverLabelOf(l);
    if (!label) continue;
    if (l.slot === "reference") out.push({ asset: uid, slot: "reference", position: l.n, included: true });
    else if (l.slot) out.push({ asset: uid, slot: l.slot, position: 0, included: true });
  }
  return out;
}

export function indexFromLabels(labels: RefLabels): TagIndex {
  return tagIndex(inputsFromLabels(labels));
}

/**
 * Пункты выбора материалов по «@»: сначала «В этом запросе» (лоток по порядку,
 * затем кадры), потом «Мои материалы» — картинки библиотеки, которых в запросе
 * ещё нет. Строит родитель (композер), редактор только показывает.
 */
export function pickerItemsFrom(src: LabelSource & { library?: readonly AssetJSON[] }, labels: RefLabels): PickerItem[] {
  const out: PickerItem[] = [];
  const seen = new Set<Uid>();
  const add = (item: TrayItem | null | undefined) => {
    const uid = item?.assetUid;
    if (!item || !uid || seen.has(uid)) return;
    seen.add(uid);
    out.push({
      asset: uid,
      section: "in_request",
      label: labels[uid]?.text || "",
      thumb: item.asset?.thumb_url || item.preview || null,
      role: item.role || undefined,
      status: item.asset?.status,
    });
  };
  src.tray.forEach(add);
  FRAME_ORDER.forEach((slot) => add(src.frames[slot]));
  for (const asset of src.library || []) {
    if (seen.has(asset.uid) || asset.kind !== "image" || asset.status === "failed") continue;
    seen.add(asset.uid);
    out.push({
      asset: asset.uid,
      section: "library",
      label: "",
      thumb: asset.thumb_url || asset.url,
      status: asset.status,
    });
  }
  return out;
}

/* ------------------------------------------------------------------ */
/* Фильтр выбора по «@запрос»                                          */
/* ------------------------------------------------------------------ */

const SYNONYMS = ["image", "img", "photo", "фото", "изображение", "картинка", "сүрөт"];

/** Для фильтра: без регистра, пробелов, «_», «@» и скобок — «@Image 1» → «image1». */
export function normalizeQuery(s: string): string {
  return s.toLowerCase().replace(/[\s_@[\]<>]/gu, "");
}

function tokensFor(item: PickerItem, labels: RefLabels): string[] {
  const label = labels[item.asset];
  const out = [item.label, label?.text || "", label?.aria || "", item.role || ""];
  if (label?.n) out.push(...SYNONYMS.map((w) => `${w}${label.n}`));
  if (label?.slot === "first_frame") out.push("первый кадр", "first frame", "кадр", "frame");
  if (label?.slot === "last_frame") out.push("последний кадр", "last frame", "кадр", "frame");
  if (item.section === "library") out.push(...SYNONYMS, "мои материалы", "library");
  return out.filter(Boolean);
}

/**
 * Пункты под фильтр «@фо», «@im», «@2», «@героиня»: совпадение с любой из
 * подписей — метки «@Image 1», подсказки «Фото 1 · героиня», роли, синонимов.
 */
export function filterPickerItems(items: readonly PickerItem[], labels: RefLabels, query: string): PickerItem[] {
  const q = normalizeQuery(query);
  if (!q) return items.slice();
  return items.filter((it) => tokensFor(it, labels).some((tok) => normalizeQuery(tok).includes(q)));
}
