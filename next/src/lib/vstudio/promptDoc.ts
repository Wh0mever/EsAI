/**
 * Видеостудия: документ промпта (prompt_doc v1, §4.1–4.3) на клиенте.
 *
 * Промпт хранится документом со ссылками на asset.uid, а не текстом с
 * «@Image 1»: номер — позиция фото в лотке, после перестановки он меняется,
 * поэтому метку считает labels.ts, а в документ она не пишется никогда.
 *
 * Здесь:
 *  - грамматика текстовых тегов — ТА ЖЕ, что у сервера (core/vstudio/prompt_doc.py:
 *    TAG_RE, MEDIA_TAG_RE, FRAME_TAG_RE), и fromText — зеркало серверного from_text:
 *    вставка текста из ChatGPT и запасная textarea дают ровно тот документ,
 *    который собрал бы сервер из prompt_text;
 *  - TipTap JSON ⇄ prompt_doc (редактор, §9.5);
 *  - validate/render_text/plain_text — зеркала серверных.
 *
 * Модуль чистый (без DOM и TipTap): его грузят и Next, и node-тесты
 * (promptDoc.test.mjs). Импорт значений — только из соседних .ts.
 */
import { issueRu } from "./errors";
import { PROMPT_DOC_LIMITS } from "./types";
import type { CompilerIssue, FrameSlot, InputSlot, PromptBlock, PromptDoc, PromptNode, Uid } from "./types";

export const DOC_VERSION = 1 as const;
export const MAX_BLOCKS = PROMPT_DOC_LIMITS.maxBlocks;
export const MAX_NODES_PER_BLOCK = PROMPT_DOC_LIMITS.maxNodesPerBlock;
export const MAX_TEXT_CHARS = PROMPT_DOC_LIMITS.maxTextChars;
export const MAX_REFS = PROMPT_DOC_LIMITS.maxRefs;

export const UID_RE = /^[0-9a-f]{32}$/;

export function isUid(v: unknown): v is Uid {
  return typeof v === "string" && UID_RE.test(v);
}

/* ------------------------------------------------------------------ */
/* Символы: длина, пробелы, управляющие                                */
/* ------------------------------------------------------------------ */

/**
 * Длина в кодовых точках — как len() в питоне. Сервер считает лимит 20 000
 * так же; у JS .length эмодзи весит 2, и без этого граница разъехалась бы.
 */
export function cpLength(s: string): number {
  let n = 0;
  for (let i = 0; i < s.length; i++) {
    const c = s.charCodeAt(i);
    if (c >= 0xd800 && c <= 0xdbff && i + 1 < s.length) {
      const d = s.charCodeAt(i + 1);
      if (d >= 0xdc00 && d <= 0xdfff) i++;
    }
    n++;
  }
  return n;
}

/** Управляющие символы, которых сервер не пропустит (всё C0/DEL/C1, кроме \n и \t). */
function isCtrl(code: number): boolean {
  return (code <= 0x08) || (code >= 0x0b && code <= 0x1f) || (code >= 0x7f && code <= 0x9f);
}

function hasCtrl(s: string): boolean {
  for (let i = 0; i < s.length; i++) if (isCtrl(s.charCodeAt(i))) return true;
  return false;
}

function stripCtrl(s: string): string {
  if (!hasCtrl(s)) return s;
  let out = "";
  for (let i = 0; i < s.length; i++) if (!isCtrl(s.charCodeAt(i))) out += s[i];
  return out;
}

/**
 * Переводы строк → "\n", управляющие символы (кроме \n и \t) убираем —
 * normalize_text сервера. Вставка из Word/Windows приносит \r\n и невидимый
 * мусор: без этого документ не прошёл бы validate, хотя человек ничего не нарушал.
 */
export function normalizeText(text: unknown): string {
  const s = String(text ?? "").replace(/\r\n/g, "\n").replace(/\r/g, "\n");
  return stripCtrl(s);
}

/**
 * Пробельные символы питонского `\s` (str.isspace). У JS свой набор (
 * есть, \x1c–\x1f и \x85 нет), а грамматика обязана совпадать с серверной.
 */
const WS = "\\t\\n\\x0b\\x0c\\r\\x1c-\\x1f \\x85\\xa0\\u1680\\u2000-\\u200a\\u2028\\u2029\\u202f\\u205f\\u3000";
const PY_WS_RE = new RegExp(`[${WS}]`, "u");
/** Питонский `\w` в режиме UNICODE: буквы, цифры любых алфавитов и «_». */
const WORD_CLASS = "\\p{L}\\p{N}_";
const WORD_RE = new RegExp(`^[${WORD_CLASS}]$`, "u");
const ND_RE = /^\p{Nd}$/u;

export function isWordChar(ch: string): boolean {
  return ch !== "" && WORD_RE.test(ch);
}

/** Слова для счётчика: `\S+` в питонском смысле пробела. */
export function countWords(text: string): number {
  let n = 0;
  let inWord = false;
  for (const ch of text) {
    const space = PY_WS_RE.test(ch);
    if (!space && !inWord) n++;
    inWord = !space;
  }
  return n;
}

/** {chars, words} текста — те же правила, что у счётчика сервера (meter). */
export function textStats(text: string): { chars: number; words: number } {
  return { chars: cpLength(text), words: countWords(text) };
}

/* ------------------------------------------------------------------ */
/* Грамматика тегов (§4.3)                                             */
/* ------------------------------------------------------------------ */

/**
 * Выражение ровно в том виде, в каком оно записано на сервере
 * (prompt_doc.TAG_PATTERN; флаги IGNORECASE | UNICODE). Тест сверяет строки.
 * Исполняется эквивалент без lookbehind (см. TAG_BODY): Safari до 16.4
 * падает на (?<!…) ещё при разборе файла, и студия не открылась бы вовсе.
 */
export const TAG_PATTERN =
  String.raw`(?<![\w])(?:@\s?|\[\s*|<\s*)(image|img|photo|фото|изображение|картинка|сүрөт)` +
  String.raw`[\s_]?(\d{1,2})(?:\s*[\]>])?`;
export const MEDIA_TAG_PATTERN = String.raw`(?<![\w])@\s?(video|видео|audio|аудио|звук)[\s_]?\d`;
export const FRAME_TAG_PATTERN = String.raw`(?<![\w])@\s?(первый кадр|последний кадр|first frame|last frame)(?![\w])`;

// Тела выражений: \s и \w — в питонском смысле, \d — любая десятичная цифра
// (питон в UNICODE-режиме тоже принимает «@Image ١»). Проверку «перед тегом
// не буква» делает scan() — вместо lookbehind.
const S = `[${WS}]`;
const TAG_BODY =
  `(?:@${S}?|\\[${S}*|<${S}*)(image|img|photo|фото|изображение|картинка|сүрөт)` +
  `[${WS}_]?(\\p{Nd}{1,2})(?:${S}*[\\]>])?`;
const MEDIA_BODY = `@${S}?(video|видео|audio|аудио|звук)[${WS}_]?\\p{Nd}`;
const FRAME_BODY = `@${S}?(первый кадр|последний кадр|first frame|last frame)(?![${WORD_CLASS}])`;

const FRAME_WORDS: Record<string, FrameSlot> = {
  "первый кадр": "first_frame",
  "first frame": "first_frame",
  "последний кадр": "last_frame",
  "last frame": "last_frame",
};

/** Как метка выглядит в человекочитаемом тексте (prompt_text): как у сервера. */
export const FRAME_TAGS: Record<FrameSlot, string> = { first_frame: "@Первый кадр", last_frame: "@Последний кадр" };
export const EXCLUDED_TAG = "@Image —";

function codePointBefore(s: string, index: number): string {
  if (index <= 0) return "";
  const lo = s.charCodeAt(index - 1);
  if (lo >= 0xdc00 && lo <= 0xdfff && index >= 2) {
    const hi = s.charCodeAt(index - 2);
    if (hi >= 0xd800 && hi <= 0xdbff) return s.slice(index - 2, index);
  }
  return s[index - 1];
}

/** Все совпадения тела, перед которыми не стоит буква/цифра/«_» — как (?<![\w]) у сервера. */
function scan(body: string, text: string): RegExpExecArray[] {
  const re = new RegExp(body, "giu");
  const out: RegExpExecArray[] = [];
  let m: RegExpExecArray | null;
  while ((m = re.exec(text)) !== null) {
    if (m[0].length === 0) {
      re.lastIndex++;
      continue;
    }
    if (isWordChar(codePointBefore(text, m.index))) {
      // Lookbehind не прошёл бы: сервер попробовал бы следующую позицию — и мы.
      re.lastIndex = m.index + 1;
      continue;
    }
    out.push(m);
  }
  return out;
}

/** Значение десятичной цифры любого алфавита: цифры Unicode идут подряд десятками от нуля. */
function digitValue(ch: string): number {
  const cp = ch.codePointAt(0) ?? 48;
  if (cp >= 48 && cp <= 57) return cp - 48;
  let start = cp;
  while (start > 0 && cp - start < 60 && ND_RE.test(String.fromCodePoint(start - 1))) start--;
  return (cp - start) % 10;
}

function parseNumber(digits: string): number {
  let n = 0;
  for (const ch of digits) n = n * 10 + digitValue(ch);
  return n;
}

export type TagMatch = {
  start: number;
  end: number;
  /** Исходный текст тега: «[Image 2]», «@фото1», «@Первый кадр». */
  raw: string;
  kind: "tag" | "frame";
  /** Номер «Image N» у kind=tag. */
  n?: number;
  /** Слот у kind=frame. */
  frame?: FrameSlot;
};

/**
 * Теги в строке — в порядке появления, без перекрытий (как цикл from_text:
 * совпадения TAG_RE и FRAME_TAG_RE сортируются по (start, -end), перекрытые
 * пропускаются). Строка — один абзац без "\n".
 */
export function findTags(line: string): TagMatch[] {
  const found: TagMatch[] = [];
  for (const m of scan(TAG_BODY, line)) {
    found.push({ start: m.index, end: m.index + m[0].length, raw: m[0], kind: "tag", n: parseNumber(m[2]) });
  }
  for (const m of scan(FRAME_BODY, line)) {
    const frame = FRAME_WORDS[m[1].toLowerCase()];
    if (frame) found.push({ start: m.index, end: m.index + m[0].length, raw: m[0], kind: "frame", frame });
  }
  found.sort((a, b) => a.start - b.start || b.end - a.end);
  const out: TagMatch[] = [];
  let pos = 0;
  for (const t of found) {
    if (t.start < pos) continue; // перекрылось с уже разобранным тегом
    out.push(t);
    pos = t.end;
  }
  return out;
}

/** «@Видео 1» / «@audio 2»: в Фазе 1 это ошибка video_refs_unsupported, а не молчаливый текст. */
export function findMediaTags(text: string): Array<{ start: number; end: number; raw: string }> {
  return scan(MEDIA_BODY, text).map((m) => ({ start: m.index, end: m.index + m[0].length, raw: m[0] }));
}

/* ------------------------------------------------------------------ */
/* Нумерация входов (§4.2) — зеркало number_refs / frame_uids          */
/* ------------------------------------------------------------------ */

/** Вход запроса в той форме, которую понимает fromText (ShotInputBody подходит). */
export type TagInput = {
  asset: Uid;
  slot: InputSlot | (string & {});
  position?: number | null;
  /** По умолчанию true. */
  included?: boolean | null;
  /** По умолчанию "image"; видео и звук в номера Image N не входят. */
  kind?: string | null;
};

function positionOf(inp: TagInput): number {
  const v = Math.trunc(Number(inp.position ?? 0));
  return Number.isFinite(v) ? v : 0;
}

function includedOf(inp: TagInput): boolean {
  return inp.included === undefined ? true : Boolean(inp.included);
}

/** Входы слота в порядке лотка (position, затем порядок в запросе). */
export function ordered(inputs: readonly TagInput[], slot: InputSlot): TagInput[] {
  return inputs
    .map((inp, i) => ({ inp, i }))
    .filter((r) => r.inp.slot === slot)
    .sort((a, b) => positionOf(a.inp) - positionOf(b.inp) || a.i - b.i)
    .map((r) => r.inp);
}

/**
 * {uid: N} — номер «Image N»: позиция среди ВКЛЮЧЁННЫХ референсов-картинок
 * в порядке лотка, с единицы. То же правило у сервера (number_refs), поэтому
 * модель получает ровно то, что видит человек. Один uid дважды не нумеруется.
 */
export function numberRefs(inputs: readonly TagInput[]): Record<Uid, number> {
  const out: Record<Uid, number> = {};
  let n = 0;
  for (const inp of ordered(inputs, "reference")) {
    const uid = inp.asset;
    if (!uid || uid in out) continue;
    if (!includedOf(inp) || String(inp.kind || "image") !== "image") continue;
    out[uid] = ++n;
  }
  return out;
}

/** {slot: uid} первого включённого кадра каждого слота. */
export function frameUids(inputs: readonly TagInput[]): Partial<Record<FrameSlot, Uid>> {
  const out: Partial<Record<FrameSlot, Uid>> = {};
  for (const slot of ["first_frame", "last_frame"] as const) {
    const hit = ordered(inputs, slot).find((inp) => includedOf(inp) && inp.asset);
    if (hit) out[slot] = hit.asset;
  }
  return out;
}

/** Куда ведёт текстовый тег: номер → uid, слово кадра → uid. */
export type TagIndex = {
  byNumber: Map<number, Uid>;
  frames: Partial<Record<FrameSlot, Uid>>;
};

export function tagIndex(inputs: readonly TagInput[]): TagIndex {
  const byNumber = new Map<number, Uid>();
  for (const [uid, n] of Object.entries(numberRefs(inputs))) byNumber.set(n, uid);
  return { byNumber, frames: frameUids(inputs) };
}

export function resolveTag(t: TagMatch, index: TagIndex): Uid | null {
  if (t.kind === "frame") return (t.frame && index.frames[t.frame]) || null;
  return index.byNumber.get(t.n ?? -1) ?? null;
}

/* ------------------------------------------------------------------ */
/* Проверка и чистка документа (§4.1)                                  */
/* ------------------------------------------------------------------ */

/** Документ не прошёл проверку → на сервере это 422 prompt_doc_invalid. */
export class PromptDocError extends Error {
  code = "prompt_doc_invalid" as const;
  detail: string;
  constructor(detail: string) {
    super(detail);
    this.name = "PromptDocError";
    this.detail = detail;
  }
}

const isPlainObject = (v: unknown): v is Record<string, unknown> =>
  typeof v === "object" && v !== null && !Array.isArray(v);

const sameKeys = (o: Record<string, unknown>, keys: string[]) => {
  const own = Object.keys(o);
  return own.length === keys.length && keys.every((k) => own.includes(k));
};

/**
 * Зеркало prompt_doc.validate: белый список, лишние ключи запрещены, пределы
 * §4.1. Возвращает чистую копию или бросает PromptDocError.
 */
export function validateDoc(doc: unknown): PromptDoc {
  const fail = (detail: string): never => {
    throw new PromptDocError(detail);
  };
  if (!isPlainObject(doc)) fail("doc is not an object");
  const d = doc as Record<string, unknown>;
  if (!sameKeys(d, ["v", "blocks"])) fail(`doc keys: ${Object.keys(d).sort().join(",")}`);
  if (d.v !== DOC_VERSION) fail(`unsupported version ${String(d.v)}`);
  if (!Array.isArray(d.blocks)) fail("blocks is not a list");
  const blocks = d.blocks as unknown[];
  if (blocks.length > MAX_BLOCKS) fail(`too many blocks: ${blocks.length}`);
  let chars = 0;
  let refs = 0;
  const out: PromptBlock[] = [];
  blocks.forEach((block, bi) => {
    if (!Array.isArray(block)) fail(`block ${bi} is not a list`);
    const nodes = block as unknown[];
    if (nodes.length > MAX_NODES_PER_BLOCK) fail(`block ${bi}: too many nodes (${nodes.length})`);
    const outBlock: PromptNode[] = [];
    nodes.forEach((node, ni) => {
      if (!isPlainObject(node)) fail(`node ${bi}.${ni} is not an object`);
      const n = node as Record<string, unknown>;
      if (n.t === "text") {
        if (!sameKeys(n, ["t", "v"])) fail(`text node ${bi}.${ni} keys`);
        if (typeof n.v !== "string") fail(`text node ${bi}.${ni}: v is not a string`);
        const v = n.v as string;
        if (hasCtrl(v)) fail(`text node ${bi}.${ni}: control characters`);
        chars += cpLength(v);
        outBlock.push({ t: "text", v });
      } else if (n.t === "ref") {
        if (!sameKeys(n, ["t", "asset"])) fail(`ref node ${bi}.${ni} keys`);
        if (!isUid(n.asset)) fail(`ref node ${bi}.${ni}: bad asset uid`);
        refs++;
        outBlock.push({ t: "ref", asset: n.asset as Uid });
      } else {
        fail(`node ${bi}.${ni}: unknown type ${String(n.t)}`);
      }
    });
    out.push(outBlock);
  });
  if (chars > MAX_TEXT_CHARS) fail(`text too long: ${chars}`);
  if (refs > MAX_REFS) fail(`too many refs: ${refs}`);
  return { v: DOC_VERSION, blocks: out };
}

export function isValidDoc(doc: unknown): doc is PromptDoc {
  try {
    validateDoc(doc);
    return true;
  } catch {
    return false;
  }
}

export function emptyDoc(): PromptDoc {
  return { v: DOC_VERSION, blocks: [[]] };
}

/** Дописать текст, склеивая с предыдущим текстовым узлом. */
function pushText(nodes: PromptNode[], s: string): void {
  if (!s) return;
  const last = nodes[nodes.length - 1];
  if (last && last.t === "text") nodes[nodes.length - 1] = { t: "text", v: last.v + s };
  else nodes.push({ t: "text", v: s });
}

/** Абзацы сверх 200 уходят в последний с "\n" внутри — текст при сборке тот же (_split_blocks). */
function capBlocks(blocks: PromptBlock[]): PromptBlock[] {
  if (blocks.length <= MAX_BLOCKS) return blocks;
  const head = blocks.slice(0, MAX_BLOCKS - 1);
  const tail: PromptNode[] = [];
  blocks.slice(MAX_BLOCKS - 1).forEach((block, i) => {
    if (i > 0) pushText(tail, "\n");
    for (const node of block) {
      if (node.t === "text") pushText(tail, node.v);
      else tail.push(node);
    }
  });
  return [...head, tail];
}

/**
 * Любой вход → валидный документ без потерь текста: соседние тексты склеены,
 * пустые убраны, управляющие символы вычищены, ссылки с плохим uid выброшены,
 * абзацы сверх 200 слиты в последний. Длину НЕ режет (текст не обрезается
 * никогда) — сверх 20 000 сервер вернёт prompt_doc_invalid, а редактор такого
 * набрать не даёт.
 */
export function sanitizeDoc(doc: unknown): PromptDoc {
  const blocksIn = isPlainObject(doc) && Array.isArray(doc.blocks) ? (doc.blocks as unknown[]) : [];
  const blocks: PromptBlock[] = [];
  for (const block of blocksIn) {
    const nodes: PromptNode[] = [];
    if (Array.isArray(block)) {
      for (const node of block) {
        if (!isPlainObject(node)) continue;
        if (node.t === "text" && typeof node.v === "string") pushText(nodes, normalizeText(node.v));
        else if (node.t === "ref" && isUid(node.asset)) nodes.push({ t: "ref", asset: node.asset });
      }
    }
    blocks.push(nodes);
  }
  return { v: DOC_VERSION, blocks: blocks.length ? capBlocks(blocks) : [[]] };
}

/** Стабильный ключ содержимого: равные документы — равные ключи, как бы ни были порезаны тексты. */
export function docKey(doc: PromptDoc | null | undefined): string {
  if (!doc) return "";
  return JSON.stringify(sanitizeDoc(doc).blocks.map((b) => b.map((n) => (n.t === "ref" ? ["r", n.asset] : n.v))));
}

/* ------------------------------------------------------------------ */
/* Чтение документа                                                    */
/* ------------------------------------------------------------------ */

/** uid упомянутых материалов в порядке первого появления, без повторов. */
export function refUids(doc: PromptDoc | null | undefined): Uid[] {
  const seen: Uid[] = [];
  for (const block of doc?.blocks || []) {
    for (const node of block) if (node.t === "ref" && !seen.includes(node.asset)) seen.push(node.asset);
  }
  return seen;
}

/** Сколько ссылок в документе (с повторами — так считает validate). */
export function refCount(doc: PromptDoc | null | undefined): number {
  let n = 0;
  for (const block of doc?.blocks || []) for (const node of block) if (node.t === "ref") n++;
  return n;
}

/** Только текст человека, без тегов. */
export function plainText(doc: PromptDoc | null | undefined): string {
  return (doc?.blocks || []).map((b) => b.map((n) => (n.t === "text" ? n.v : "")).join("")).join("\n");
}

/** Сумма длин текстовых узлов — ровно то, что сервер сверяет с 20 000. */
export function docTextLength(doc: PromptDoc | null | undefined): number {
  let n = 0;
  for (const block of doc?.blocks || []) for (const node of block) if (node.t === "text") n += cpLength(node.v);
  return n;
}

/** Пусто: ни одной ссылки и только пробелы. */
export function isEmptyDoc(doc: PromptDoc | null | undefined): boolean {
  return refCount(doc) === 0 && plainText(doc).trim() === "";
}

/** Собрать текст; renderRef(uid) превращает ссылку в текст. Абзацы соединяет "\n". */
export function serialize(doc: PromptDoc, renderRef: (uid: Uid) => string): string {
  return (doc.blocks || [])
    .map((block) => block.map((n) => (n.t === "text" ? n.v : renderRef(n.asset))).join(""))
    .join("\n");
}

/** Метка сервера → тег текста: «Image 2» → «@Image 2», кадры словами, прочее — «@Image —». */
export function labelTag(label: string | null | undefined): string {
  if (label === "first_frame" || label === "last_frame") return FRAME_TAGS[label];
  if (label && label.startsWith("Image ")) return "@" + label;
  return EXCLUDED_TAG;
}

/**
 * prompt_text (§4.2): документ с метками «@Image N» — для копирования, поиска и
 * запасной textarea. labels — {uid: "Image 1" | "first_frame" | "last_frame"}
 * (как QuoteJSON.labels); без метки — «@Image —», как серый чип.
 */
export function renderText(doc: PromptDoc, labels: Record<Uid, string> | null | undefined): string {
  const l = labels || {};
  return serialize(doc, (uid) => labelTag(l[uid]));
}

/* ------------------------------------------------------------------ */
/* Текст → документ (зеркало from_text)                                */
/* ------------------------------------------------------------------ */

export type FromTextResult = {
  doc: PromptDoc;
  warnings: CompilerIssue[];
  errors: CompilerIssue[];
};

function makeIssue(code: string, params: Record<string, unknown>, which: "errors" | "warnings"): CompilerIssue {
  return { code, params, message: issueRu(code, params, which) };
}

function splitBlocks(text: string): string[] {
  const lines = text.split("\n");
  if (lines.length <= MAX_BLOCKS) return lines;
  return [...lines.slice(0, MAX_BLOCKS - 1), lines.slice(MAX_BLOCKS - 1).join("\n")];
}

/**
 * Текст с тегами «@Image 1», «[Image 2]», «<IMAGE_3>», «@Фото 1», «@Первый кадр»
 * → prompt_doc, ровно как prompt_doc.from_text на сервере. Тег с номером
 * включённого референса становится ссылкой; без такого номера остаётся
 * текстом с предупреждением tag_unknown (одно на одинаковый текст тега).
 * «@Видео 1» — ошибка video_refs_unsupported. Больше 20 000 символов → PromptDocError.
 */
export function fromText(text: string, inputs: readonly TagInput[] | TagIndex = []): FromTextResult {
  const clean = normalizeText(text);
  if (cpLength(clean) > MAX_TEXT_CHARS) throw new PromptDocError(`text too long: ${cpLength(clean)}`);
  const warnings: CompilerIssue[] = [];
  const errors: CompilerIssue[] = [];
  if (findMediaTags(clean).length) errors.push(makeIssue("video_refs_unsupported", {}, "errors"));

  const index = Array.isArray(inputs) ? tagIndex(inputs as readonly TagInput[]) : (inputs as TagIndex);
  const unknownSeen = new Set<string>();
  let refs = 0;
  const blocks: PromptBlock[] = [];
  for (const line of splitBlocks(clean)) {
    const nodes: PromptNode[] = [];
    let pos = 0;
    for (const t of findTags(line)) {
      const uid = resolveTag(t, index);
      pushText(nodes, line.slice(pos, t.start));
      if (uid && refs < MAX_REFS) {
        nodes.push({ t: "ref", asset: uid });
        refs++;
      } else {
        pushText(nodes, t.raw);
        if (!uid && !unknownSeen.has(t.raw)) {
          unknownSeen.add(t.raw);
          warnings.push(makeIssue("tag_unknown", { text: t.raw }, "warnings"));
        }
      }
      pos = t.end;
    }
    pushText(nodes, line.slice(pos));
    blocks.push(nodes);
  }
  return { doc: { v: DOC_VERSION, blocks: blocks.length ? blocks : [[]] }, warnings, errors };
}

/**
 * Теги, оставшиеся ТЕКСТОМ внутри документа, → ссылки. Зеркало сервера
 * (prompt_doc.link_tags, его зовёт компилятор в quote и запуске): тег, за
 * которым стоял курсор при «Создать», сервер всё равно привяжет. Тег без фото —
 * tag_unknown, «@Видео 1» — video_refs_unsupported. Перенос строки внутри
 * абзаца — граница тега, как между строками в fromText.
 */
export function linkDocTags(doc: PromptDoc, inputs: readonly TagInput[] | TagIndex = []): FromTextResult {
  const index = Array.isArray(inputs) ? tagIndex(inputs as readonly TagInput[]) : (inputs as TagIndex);
  const warnings: CompilerIssue[] = [];
  const errors: CompilerIssue[] = [];
  const unknownSeen = new Set<string>();
  let refs = doc.blocks.reduce((n, b) => n + b.filter((node) => node.t === "ref").length, 0);
  let media = false;
  const blocks = doc.blocks.map((block) => {
    const nodes: PromptNode[] = [];
    for (const node of block) {
      if (node.t !== "text") {
        nodes.push(node);
        continue;
      }
      if (!media && findMediaTags(node.v).length) media = true;
      node.v.split("\n").forEach((line, i) => {
        if (i > 0) pushText(nodes, "\n");
        let pos = 0;
        for (const t of findTags(line)) {
          const uid = resolveTag(t, index);
          pushText(nodes, line.slice(pos, t.start));
          if (uid && refs < MAX_REFS) {
            nodes.push({ t: "ref", asset: uid });
            refs++;
          } else {
            pushText(nodes, t.raw);
            if (!uid && !unknownSeen.has(t.raw)) {
              unknownSeen.add(t.raw);
              warnings.push(makeIssue("tag_unknown", { text: t.raw }, "warnings"));
            }
          }
          pos = t.end;
        }
        pushText(nodes, line.slice(pos));
      });
    }
    return nodes;
  });
  if (media) errors.push(makeIssue("video_refs_unsupported", {}, "errors"));
  return { doc: { v: DOC_VERSION, blocks: blocks.length ? blocks : [[]] }, warnings, errors };
}

/* ------------------------------------------------------------------ */
/* Перепривязка при наборе (редактор)                                   */
/* ------------------------------------------------------------------ */

/** Тег «дописан»: закрыт скобкой или за ним уже стоит не-буква (пробел, запятая…). */
export function isTagClosed(t: TagMatch, text: string): boolean {
  if (/[\]>]$/.test(t.raw)) return true;
  if (t.end >= text.length) return false;
  const next = String.fromCodePoint(text.codePointAt(t.end) ?? 32);
  return !isWordChar(next);
}

export type RelinkHit = { start: number; end: number; asset: Uid; raw: string };

/**
 * Какие теги в куске текста превратить в чипы, пока человек печатает.
 * Строже вставки: тег меняется, только когда он дописан — иначе «@Image 1»
 * стал бы чипом раньше, чем человек допечатал «2». Тег в конце куска
 * считается дописанным, если за ним идёт другой узел или конец абзаца
 * (atEnd), а курсор не стоит сразу за ним (cursor — смещение курсора в куске).
 */
export function relinkHits(
  text: string,
  index: TagIndex,
  opts: { atEnd?: boolean; cursor?: number | null } = {},
): RelinkHit[] {
  const out: RelinkHit[] = [];
  for (const t of findTags(text)) {
    const uid = resolveTag(t, index);
    if (!uid) continue;
    const closed = isTagClosed(t, text) || (t.end >= text.length && Boolean(opts.atEnd) && opts.cursor !== t.end);
    if (closed) out.push({ start: t.start, end: t.end, asset: uid, raw: t.raw });
  }
  return out;
}

/** Теги, которым некуда вести (нет такого фото) и «@Видео N» — их редактор подчёркивает. */
export function unresolvedTags(
  text: string,
  index: TagIndex,
): Array<{ start: number; end: number; raw: string; code: "tag_unknown" | "video_refs_unsupported" }> {
  const out: Array<{ start: number; end: number; raw: string; code: "tag_unknown" | "video_refs_unsupported" }> = [];
  for (const t of findTags(text)) {
    if (!resolveTag(t, index)) out.push({ start: t.start, end: t.end, raw: t.raw, code: "tag_unknown" });
  }
  for (const m of findMediaTags(text)) out.push({ ...m, code: "video_refs_unsupported" });
  return out.sort((a, b) => a.start - b.start);
}

/* ------------------------------------------------------------------ */
/* TipTap JSON ⇄ prompt_doc                                            */
/* ------------------------------------------------------------------ */

/** Имя inline-узла ссылки в схеме редактора (RefNode.tsx). */
export const REF_NODE = "vsRef";
export const HARD_BREAK_NODE = "hardBreak";
export const PARAGRAPH_NODE = "paragraph";

/** Минимальная форма JSON TipTap/ProseMirror (JSONContent без зависимости от @tiptap/core). */
export type TiptapJSON = {
  type?: string;
  attrs?: Record<string, unknown>;
  content?: TiptapJSON[];
  text?: string;
};

function inlineFromNodes(nodes: PromptNode[]): TiptapJSON[] {
  const out: TiptapJSON[] = [];
  for (const node of nodes) {
    if (node.t === "ref") {
      out.push({ type: REF_NODE, attrs: { asset: node.asset } });
      continue;
    }
    // Перенос внутри абзаца хранится как "\n" в тексте; в редакторе это hardBreak.
    node.v.split("\n").forEach((part, i) => {
      if (i > 0) out.push({ type: HARD_BREAK_NODE });
      if (part) out.push({ type: "text", text: part });
    });
  }
  return out;
}

/** prompt_doc → JSON документа TipTap: абзац на блок, "\n" → hardBreak, ref → vsRef. */
export function docToTiptap(doc: PromptDoc | null | undefined): TiptapJSON {
  const clean = sanitizeDoc(doc);
  return {
    type: "doc",
    content: clean.blocks.map((block) => {
      const content = inlineFromNodes(block);
      return content.length ? { type: PARAGRAPH_NODE, content } : { type: PARAGRAPH_NODE };
    }),
  };
}

function collectInline(node: TiptapJSON, out: PromptNode[]): void {
  if (node.type === "text") {
    pushText(out, normalizeText(node.text ?? ""));
  } else if (node.type === HARD_BREAK_NODE) {
    pushText(out, "\n");
  } else if (node.type === REF_NODE) {
    const asset = node.attrs?.asset;
    if (isUid(asset)) out.push({ t: "ref", asset });
  } else if (Array.isArray(node.content)) {
    // Незнакомый узел (в минимальной схеме их нет): берём его текст, ничего не теряем.
    for (const child of node.content) collectInline(child, out);
  }
}

/** JSON редактора → prompt_doc. Всегда валидная структура (пределы длины — забота редактора). */
export function tiptapToDoc(json: TiptapJSON | null | undefined): PromptDoc {
  const blocks: PromptBlock[] = [];
  for (const block of json?.content || []) {
    const nodes: PromptNode[] = [];
    for (const child of block.content || []) collectInline(child, nodes);
    blocks.push(nodes);
  }
  return { v: DOC_VERSION, blocks: blocks.length ? capBlocks(blocks) : [[]] };
}
