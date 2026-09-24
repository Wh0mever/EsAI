/**
 * Видеостудия: черновик гостя (§9.1).
 *
 * Гость видит студию, модели и цены и может написать промпт, а вход нужен
 * только на «Создать», «Загрузить» и «Создать картинку». Чтобы текст не
 * пропал по дороге через страницу входа, композер гостя живёт в
 * localStorage["vstudio:draft:v1"]: текст и параметры, без материалов (гость
 * загружать не может, а чужой uid в черновике был бы красным чипом). После
 * входа студия поднимает черновик в композер и стирает его.
 *
 * Хранилищу браузера не доверяем: в приватном режиме оно бросает, а
 * содержимое мог поправить кто угодно. Поэтому каждое обращение — в
 * try/catch, а прочитанное проходит белый список полей. Длинный текст не
 * обрезаем молча (§0 п. 10): черновик больше лимита редактора просто не
 * поднимается.
 *
 * Модуль без импорта значений из React и Next: его проверяют node-тесты
 * (draft.test.mjs).
 */
import { EMPTY_PROMPT_DOC, PROMPT_DOC_LIMITS, PROMPT_MAX_CHARS } from "./types";
import type { ComposerState, PromptBlock, PromptDoc, ShotParams, VsKind } from "./types";

export const DRAFT_KEY = "vstudio:draft:v1";
/** Неделю черновик ждёт; дальше это уже не «вернулся после входа», а мусор. */
export const DRAFT_MAX_AGE_MS = 7 * 24 * 60 * 60 * 1000;

/** То, что черновик возвращает композеру (action composer/restore). */
export type DraftComposer = Pick<ComposerState, "kind" | "model" | "params" | "doc">;

type StoredDraft = DraftComposer & { v: 1; updated_at: number };

export type DraftStorage = Pick<Storage, "getItem" | "setItem" | "removeItem">;
export type DraftOptions = { storage?: DraftStorage | null; now?: () => number };

function storageOf(opts?: DraftOptions): DraftStorage | null {
  if (opts?.storage) return opts.storage;
  try {
    return typeof window !== "undefined" && window.localStorage ? window.localStorage : null;
  } catch {
    // Safari в приватном режиме и запрет cookie бросают уже на обращении к localStorage.
    return null;
  }
}

const isObj = (v: unknown): v is Record<string, unknown> =>
  typeof v === "object" && v !== null && !Array.isArray(v);

/* ------------------------------------------------------------------ */
/* Белые списки                                                        */
/* ------------------------------------------------------------------ */

const MODEL_RE = /^[\w.\-/:]{1,128}$/;
const RESOLUTION_RE = /^[\w.-]{1,16}$/;
const ASPECT_RE = /^(auto|\d{1,2}:\d{1,2})$/;
const MAX_NEGATIVE = 2000;

/** Документ черновика: только текст. Ссылки на материалы выбрасываются (материалов у гостя нет). */
export function sanitizeDraftDoc(raw: unknown): PromptDoc | null {
  if (!isObj(raw) || raw.v !== 1 || !Array.isArray(raw.blocks)) return null;
  if (raw.blocks.length > PROMPT_DOC_LIMITS.maxBlocks) return null;
  const blocks: PromptBlock[] = [];
  let chars = 0;
  for (const block of raw.blocks) {
    if (!Array.isArray(block) || block.length > PROMPT_DOC_LIMITS.maxNodesPerBlock) return null;
    let text = "";
    for (const node of block) {
      if (!isObj(node)) return null;
      if (node.t === "text") {
        if (typeof node.v !== "string") return null;
        text += node.v;
      } else if (node.t !== "ref") {
        return null;
      }
    }
    chars += text.length;
    // Слишком длинный черновик не поднимаем вовсе: молча резать текст нельзя.
    if (chars > PROMPT_MAX_CHARS) return null;
    blocks.push(text ? [{ t: "text", v: text }] : []);
  }
  return { v: 1, blocks: blocks.length ? blocks : [[]] };
}

export function sanitizeDraftParams(raw: unknown): ShotParams {
  const out: ShotParams = {};
  if (!isObj(raw)) return out;
  const d = raw.duration;
  if (typeof d === "number" && Number.isFinite(d) && d > 0 && d <= 600) out.duration = d;
  if (typeof raw.resolution === "string" && RESOLUTION_RE.test(raw.resolution)) out.resolution = raw.resolution;
  if (typeof raw.aspect_ratio === "string" && ASPECT_RE.test(raw.aspect_ratio)) out.aspect_ratio = raw.aspect_ratio;
  if (typeof raw.generate_audio === "boolean") out.generate_audio = raw.generate_audio;
  if (raw.seed === null) out.seed = null;
  else if (typeof raw.seed === "number" && Number.isSafeInteger(raw.seed) && raw.seed >= 0) out.seed = raw.seed;
  if (typeof raw.negative_prompt === "string" && raw.negative_prompt.length <= MAX_NEGATIVE) {
    out.negative_prompt = raw.negative_prompt;
  }
  return out;
}

/** Есть ли в документе хоть один непробельный символ. */
export function docHasText(doc: PromptDoc | null | undefined): boolean {
  if (!doc || !Array.isArray(doc.blocks)) return false;
  return doc.blocks.some((b) => Array.isArray(b) && b.some((n) => n.t === "text" && n.v.trim() !== ""));
}

/* ------------------------------------------------------------------ */
/* Чтение и запись                                                     */
/* ------------------------------------------------------------------ */

/** Черновик для composer/restore или null (нет, протух, испорчен). Испорченный стирается. */
export function loadDraft(opts?: DraftOptions): DraftComposer | null {
  const store = storageOf(opts);
  if (!store) return null;
  let raw: string | null = null;
  try {
    raw = store.getItem(DRAFT_KEY);
  } catch {
    return null;
  }
  if (!raw) return null;

  const drop = () => {
    try {
      store.removeItem(DRAFT_KEY);
    } catch {
      /* ничего: хранилище недоступно */
    }
    return null;
  };

  let data: unknown;
  try {
    data = JSON.parse(raw);
  } catch {
    return drop();
  }
  if (!isObj(data) || data.v !== 1) return drop();
  const now = opts?.now ? opts.now() : Date.now();
  const at = Number(data.updated_at);
  if (!Number.isFinite(at) || now - at > DRAFT_MAX_AGE_MS) return drop();

  const doc = sanitizeDraftDoc(data.doc);
  if (!doc || !docHasText(doc)) return drop();
  const kind: VsKind = data.kind === "image" ? "image" : "video";
  const model = typeof data.model === "string" && MODEL_RE.test(data.model) ? data.model : null;
  return { kind, model, params: sanitizeDraftParams(data.params), doc };
}

/**
 * Сохранить композер гостя. Пустой текст — черновик стирается: поднимать
 * после входа нечего. Возвращает true, если запись удалась.
 */
export function saveDraft(composer: DraftComposer, opts?: DraftOptions): boolean {
  const store = storageOf(opts);
  if (!store) return false;
  const doc = sanitizeDraftDoc(composer.doc);
  if (!doc || !docHasText(doc)) {
    clearDraft(opts);
    return false;
  }
  const payload: StoredDraft = {
    v: 1,
    kind: composer.kind === "image" ? "image" : "video",
    model: composer.model && MODEL_RE.test(composer.model) ? composer.model : null,
    params: sanitizeDraftParams(composer.params),
    doc,
    updated_at: opts?.now ? opts.now() : Date.now(),
  };
  try {
    store.setItem(DRAFT_KEY, JSON.stringify(payload));
    return true;
  } catch {
    // Переполненное хранилище или запрет записи: черновик — удобство, не более.
    return false;
  }
}

export function clearDraft(opts?: DraftOptions): void {
  const store = storageOf(opts);
  if (!store) return;
  try {
    store.removeItem(DRAFT_KEY);
  } catch {
    /* хранилище недоступно */
  }
}

/** Пустой документ черновика (для тестов и сброса). */
export function emptyDraftDoc(): PromptDoc {
  return { v: 1, blocks: EMPTY_PROMPT_DOC.blocks.map((b) => [...b]) };
}
