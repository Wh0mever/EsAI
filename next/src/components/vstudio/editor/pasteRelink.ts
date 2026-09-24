/**
 * Видеостудия, редактор промпта: вставка, перепривязка тегов, лимиты.
 *
 * Всё на уровне ProseMirror (@tiptap/pm), без React и без @tiptap/core —
 * поэтому node-тесты (lib/vstudio/promptDoc.test.mjs) гоняют эти функции на
 * настоящей схеме и настоящем EditorState.
 *
 *  - Вставка текста (§4.3): «@Image 1», «[Image 2]», «<IMAGE_3>», «@Фото 1»,
 *    «@Первый кадр» → чипы по той же грамматике, что у сервера (promptDoc.fromText).
 *    Внешний текст берём из text/plain, а не из HTML: так переносы строк и
 *    пробелы доходят ровно такими, какими их видел человек. HTML разбираем
 *    только для копирования из самого редактора (чипы с uid).
 *  - Перепривязка при наборе: дописанный тег «@Image 1 » сам становится чипом;
 *    при появлении фото с нужным номером — тоже (relinkPlugin).
 *  - Подчёркивание тегов, которым некуда вести, и «@Видео N».
 *  - Лимит 20 000 символов и 64 ссылок: лишнее не вставляется и НЕ обрезается
 *    молча — редактор показывает, почему вставка не прошла.
 *  - Метки ожидания: вставили или бросили файл — чипы появятся ровно там, куда
 *    вставляли, даже если человек успел напечатать что-то ещё (pendingPlugin).
 */
import { Fragment, Slice, type Node as PMNode, type ResolvedPos, type Schema } from "@tiptap/pm/model";
import { Plugin, PluginKey, type EditorState, type Transaction } from "@tiptap/pm/state";
import { Decoration, DecorationSet, type EditorView } from "@tiptap/pm/view";
import {
  cpLength,
  docToTiptap,
  findTags,
  fromText,
  isUid,
  MAX_REFS,
  normalizeText,
  REF_NODE,
  relinkHits,
  resolveTag,
  unresolvedTags,
  type TagIndex,
} from "@/lib/vstudio/promptDoc";
import type { Uid } from "@/lib/vstudio/types";

/** Мета транзакции, пришедшей извне (setContent из пропса doc): её не режем и не перепривязываем. */
export const EXTERNAL_META = "vsExternal";

export type LimitKind = "chars" | "refs";

/* ------------------------------------------------------------------ */
/* Подсчёт                                                              */
/* ------------------------------------------------------------------ */

export type DocCounts = { chars: number; refs: number };

const countCache = new WeakMap<PMNode | Fragment, DocCounts>();

/**
 * Символы (кодовые точки текста + переносы hardBreak) и ссылки. Ровно то, что
 * сервер сверяет с 20 000 и 64 (validate): абзацы между собой не считаются.
 */
export function countContent(node: PMNode | Fragment): DocCounts {
  const cached = countCache.get(node);
  if (cached) return cached;
  const out: DocCounts = { chars: 0, refs: 0 };
  node.descendants((child) => {
    if (child.isText) out.chars += cpLength(child.text || "");
    else if (child.type.name === REF_NODE) out.refs++;
    else if (child.type.name === "hardBreak") out.chars++;
    return true;
  });
  countCache.set(node, out);
  return out;
}

const isIndexEmpty = (index: TagIndex) => index.byNumber.size === 0 && !index.frames.first_frame && !index.frames.last_frame;

/* ------------------------------------------------------------------ */
/* Текст → срез (вставка)                                              */
/* ------------------------------------------------------------------ */

/** Абзацы без перепривязки — запасной путь, когда текст длиннее лимита (его всё равно не вставим). */
function plainSlice(schema: Schema, text: string): Slice {
  const blocks = normalizeText(text)
    .split("\n")
    .map((line) => schema.nodes.paragraph.create(null, line ? schema.text(line) : undefined));
  return Slice.maxOpen(Fragment.fromArray(blocks));
}

/**
 * Текст из буфера → срез с чипами. Грамматика и нумерация — promptDoc.fromText,
 * то есть тот же документ, который сервер собрал бы из prompt_text.
 */
export function sliceFromText(schema: Schema, text: string, index: TagIndex): { slice: Slice; refs: number } {
  let json;
  try {
    json = docToTiptap(fromText(text, index).doc);
  } catch {
    // Длиннее 20 000: ничего не режем — вернём как есть, а лимит не даст вставить.
    return { slice: plainSlice(schema, text), refs: 0 };
  }
  const doc = schema.nodeFromJSON(json);
  return { slice: Slice.maxOpen(doc.content), refs: countContent(doc).refs };
}

/* ------------------------------------------------------------------ */
/* Перепривязка среза из HTML (копирование внутри редактора, drop)     */
/* ------------------------------------------------------------------ */

/**
 * Инлайн-содержимое абзаца: тексты и чипы с неизвестным uid (скопированы из
 * другого проекта) склеиваются в строку и разбираются грамматикой; известные
 * чипы и переносы остаются как есть.
 */
function relinkInline(content: Fragment, schema: Schema, index: TagIndex, known: (uid: Uid) => boolean): Fragment {
  const out: PMNode[] = [];
  let run = "";
  const flush = () => {
    if (!run) return;
    let pos = 0;
    for (const t of findTags(run)) {
      const uid = resolveTag(t, index);
      if (!uid) continue;
      if (t.start > pos) out.push(schema.text(run.slice(pos, t.start)));
      out.push(schema.nodes[REF_NODE].create({ asset: uid }));
      pos = t.end;
    }
    if (pos < run.length) out.push(schema.text(run.slice(pos)));
    run = "";
  };
  content.forEach((node) => {
    if (node.isText) {
      run += node.text || "";
    } else if (node.type.name === REF_NODE) {
      const asset = node.attrs.asset as unknown;
      if (isUid(asset) && known(asset)) {
        flush();
        out.push(schema.nodes[REF_NODE].create({ asset }));
      } else {
        // Чужой чип: его подпись на момент копирования («@Image 2») — как текст.
        const tag = node.attrs.tag;
        run += typeof tag === "string" ? tag : "";
      }
    } else {
      flush();
      out.push(node);
    }
  });
  flush();
  return Fragment.fromArray(out);
}

function relinkFragment(frag: Fragment, schema: Schema, index: TagIndex, known: (uid: Uid) => boolean): Fragment {
  // Срез из середины абзаца бывает «плоским» (инлайн на верхнем уровне).
  let inlineTop = frag.childCount > 0;
  frag.forEach((n) => {
    if (!n.isInline) inlineTop = false;
  });
  if (inlineTop) return relinkInline(frag, schema, index, known);
  const nodes: PMNode[] = [];
  frag.forEach((node) => {
    if (node.isTextblock) nodes.push(node.copy(relinkInline(node.content, schema, index, known)));
    else if (node.content.size) nodes.push(node.copy(relinkFragment(node.content, schema, index, known)));
    else nodes.push(node);
  });
  return Fragment.fromArray(nodes);
}

/** transformPasted: теги текста → чипы, чужие чипы → текст → чипы этого запроса. */
export function relinkSlice(slice: Slice, schema: Schema, index: TagIndex, known: (uid: Uid) => boolean): Slice {
  try {
    return new Slice(relinkFragment(slice.content, schema, index, known), slice.openStart, slice.openEnd);
  } catch {
    return slice;
  }
}

/* ------------------------------------------------------------------ */
/* Перепривязка при наборе                                              */
/* ------------------------------------------------------------------ */

export const relinkKey = new PluginKey<RelinkState>("vsRelink");

type RelinkState = { deco: DecorationSet };

/**
 * Транзакция, которая меняет дописанные теги на чипы в абзацах, задевающих
 * [from, to] (весь документ, если диапазона нет). null — менять нечего.
 * ignoreCursor — человек закончил печатать («Создать», ушёл из поля): тег
 * сразу перед курсором тоже дописан.
 */
export function relinkTransaction(
  state: EditorState,
  index: TagIndex,
  range?: { from: number; to: number } | null,
  opts: { ignoreCursor?: boolean } = {},
): Transaction | null {
  if (isIndexEmpty(index)) return null;
  const { doc, selection, schema } = state;
  const from = Math.max(0, Math.min(range ? range.from : 0, doc.content.size));
  const to = Math.max(from, Math.min(range ? range.to : doc.content.size, doc.content.size));
  const head = selection.empty && !opts.ignoreCursor ? selection.head : null;
  const hits: Array<{ from: number; to: number; asset: Uid }> = [];
  // ±1: пустой диапазон (удаление) на границе абзаца тоже должен его задеть.
  doc.nodesBetween(Math.max(0, from - 1), Math.min(doc.content.size, to + 1), (node, pos) => {
    if (!node.isTextblock) return true;
    node.forEach((child, offset) => {
      if (!child.isText) return;
      const start = pos + 1 + offset;
      const text = child.text || "";
      // Соседние тексты ProseMirror склеивает, так что за текстом всегда
      // другой узел или конец абзаца: тег в конце куска — «в конце».
      const cursor = head !== null && head >= start && head <= start + text.length ? head - start : null;
      for (const h of relinkHits(text, index, { atEnd: true, cursor })) {
        hits.push({ from: start + h.start, to: start + h.end, asset: h.asset });
      }
    });
    return false;
  });
  if (!hits.length) return null;
  let budget = MAX_REFS - countContent(doc).refs;
  const tr = state.tr;
  // С конца: позиции впереди не сдвигаются.
  for (const h of hits.slice().reverse()) {
    if (budget <= 0) break;
    tr.replaceWith(h.from, h.to, schema.nodes[REF_NODE].create({ asset: h.asset }));
    budget--;
  }
  return tr.docChanged ? tr : null;
}

const isHistoryTr = (tr: Transaction) => Boolean(tr.getMeta("history$"));
const isPasteTr = (tr: Transaction) => {
  const ui = tr.getMeta("uiEvent");
  return ui === "paste" || ui === "drop" || Boolean(tr.getMeta("paste"));
};

export type RelinkOptions = {
  getIndex: () => TagIndex;
  /** Подсказки к подчёркнутым тегам (уже переведённые). */
  texts?: () => { unknown: (raw: string) => string; media: string };
};

function buildDecorations(state: EditorState, index: TagIndex, texts?: RelinkOptions["texts"]): DecorationSet {
  const head = state.selection.empty ? state.selection.head : null;
  const decos: Decoration[] = [];
  const tx = texts?.();
  state.doc.descendants((node, pos) => {
    if (!node.isText) return true;
    const text = node.text || "";
    if (text.indexOf("@") < 0 && text.indexOf("[") < 0 && text.indexOf("<") < 0) return false;
    for (const u of unresolvedTags(text, index)) {
      const from = pos + u.start;
      const to = pos + u.end;
      // Пока курсор внутри слова или сразу за ним, не трогаем его: смена
      // разметки вокруг набираемого слова ломает композицию клавиатуры на Android.
      if (head !== null && head > from && head <= to) continue;
      decos.push(
        Decoration.inline(from, to, {
          class: "vs-tag-issue",
          "data-vs-issue": u.code,
          title: tx ? (u.code === "tag_unknown" ? tx.unknown(u.raw) : tx.media) : "",
        }),
      );
    }
    return false;
  });
  return DecorationSet.create(state.doc, decos);
}

/**
 * Плагин перепривязки. appendTransaction: после набора (не во время
 * композиции IME, не на undo/redo и не на вставке — у неё свой путь) меняет
 * дописанные теги на чипы в задетых абзацах. Мета {force:true} — пройти весь
 * документ (лоток изменился: у «@Image 2» появилось фото).
 */
export function relinkPlugin(opts: RelinkOptions): Plugin<RelinkState> {
  let view: EditorView | null = null;
  return new Plugin<RelinkState>({
    key: relinkKey,
    view(v) {
      view = v;
      return {
        destroy() {
          view = null;
        },
      };
    },
    state: {
      init: (_, state) => ({ deco: buildDecorations(state, opts.getIndex(), opts.texts) }),
      apply(tr, value, _old, next) {
        const force = Boolean(tr.getMeta(relinkKey)?.force);
        if (!tr.docChanged && !tr.selectionSet && !force) return value;
        if (view?.composing) return { deco: value.deco.map(tr.mapping, tr.doc) };
        return { deco: buildDecorations(next, opts.getIndex(), opts.texts) };
      },
    },
    props: {
      decorations(state) {
        return relinkKey.getState(state)?.deco ?? null;
      },
    },
    appendTransaction(trs, oldState, newState) {
      const force = trs.some((tr) => tr.getMeta(relinkKey)?.force);
      const typed = trs.some(
        (tr) =>
          tr.docChanged &&
          !tr.getMeta(relinkKey) &&
          !tr.getMeta(EXTERNAL_META) &&
          !isHistoryTr(tr) &&
          !isPasteTr(tr),
      );
      if (!force && !typed) return null;
      if (view?.composing) return null;
      let range: { from: number; to: number } | null = null;
      if (!force) {
        const start = oldState.doc.content.findDiffStart(newState.doc.content);
        if (start == null) return null;
        const end = oldState.doc.content.findDiffEnd(newState.doc.content);
        range = { from: start, to: Math.max(start, end ? end.b : start) };
      }
      const tr = relinkTransaction(newState, opts.getIndex(), range);
      if (!tr) return null;
      tr.setMeta(relinkKey, { done: true });
      // Автоматическая замена по смене лотка — не шаг человека: undo её не откатывает.
      if (force) tr.setMeta("addToHistory", false);
      return tr;
    },
  });
}

/** Попросить плагин пройти весь документ (после смены меток). */
export function forceRelink(view: EditorView): void {
  if (view.isDestroyed) return;
  view.dispatch(view.state.tr.setMeta(relinkKey, { force: true }).setMeta("addToHistory", false));
}

/**
 * Человек закончил печатать («Создать», Ctrl+Enter, ушёл из поля): тег, за
 * которым ещё стоял курсор («…в стиле @Image 1|»), тоже становится чипом.
 * Иначе запрос уходил с буквальным «@Image 1», а подсказка говорила «фото не
 * упомянуто», хотя тег виден в тексте. true — документ изменился.
 */
export function finishTags(view: EditorView, index: TagIndex): boolean {
  if (view.isDestroyed || view.composing) return false;
  const tr = relinkTransaction(view.state, index, null, { ignoreCursor: true });
  if (!tr) return false;
  // Не шаг человека: undo его не откатывает (как и перепривязка по смене лотка).
  view.dispatch(tr.setMeta(relinkKey, { done: true }).setMeta("addToHistory", false));
  return true;
}

/* ------------------------------------------------------------------ */
/* Лимиты                                                              */
/* ------------------------------------------------------------------ */

/**
 * filterTransaction: документ не может вырасти сверх maxChars символов и 64
 * ссылок. Транзакции, которые его уменьшают, проходят всегда (иначе из
 * слишком длинного текста, пришедшего извне, нельзя было бы даже стереть).
 */
export function limitPlugin(opts: { getMax: () => number; onLimit?: (kind: LimitKind) => void }): Plugin {
  return new Plugin({
    key: new PluginKey("vsLimit"),
    filterTransaction(tr, state) {
      if (!tr.docChanged || tr.getMeta(EXTERNAL_META)) return true;
      const next = countContent(tr.doc);
      const max = opts.getMax();
      if (next.chars > max) {
        const prev = countContent(state.doc);
        if (next.chars > prev.chars) {
          opts.onLimit?.("chars");
          return false;
        }
      }
      if (next.refs > MAX_REFS) {
        const prev = countContent(state.doc);
        if (next.refs > prev.refs) {
          opts.onLimit?.("refs");
          return false;
        }
      }
      return true;
    },
  });
}

/** Поместится ли срез вместо выделения. */
export function sliceFits(state: EditorState, slice: Slice, max: number): LimitKind | null {
  const { from, to } = state.selection;
  const cur = countContent(state.doc);
  const cut = countContent(state.doc.slice(from, to).content);
  const add = countContent(slice.content);
  if (cur.chars - cut.chars + add.chars > max && add.chars > cut.chars) return "chars";
  if (cur.refs - cut.refs + add.refs > MAX_REFS && add.refs > cut.refs) return "refs";
  return null;
}

/* ------------------------------------------------------------------ */
/* Вставка чипов                                                        */
/* ------------------------------------------------------------------ */

const OPENERS = new Set(["(", "[", "«", "\"", "'", "“", "„", "‘"]);
const CLOSERS_OR_PUNCT = /^[\s.,;:!?)\]»"'”’…—–-]$/u;
/** Заглушка чипа в тексте абзаца (U+FFFC, «объект»). */
export const OBJECT_CHAR = String.fromCharCode(0xfffc);
/** Чип — OBJECT_CHAR, перенос строки — "\n": после переноса пробел не нужен, после чипа нужен. */
const leafText = (node: PMNode) => (node.type.name === "hardBreak" ? "\n" : OBJECT_CHAR);

function lastCodePoint(s: string): string {
  if (!s) return "";
  const lo = s.charCodeAt(s.length - 1);
  if (lo >= 0xdc00 && lo <= 0xdfff && s.length >= 2) return s.slice(-2);
  return s.slice(-1);
}

/** Символ перед позицией внутри абзаца ("" — начало абзаца). */
export function charBefore($pos: ResolvedPos): string {
  if (!$pos.parent.inlineContent) return "";
  return lastCodePoint($pos.parent.textBetween(0, $pos.parentOffset, undefined, leafText));
}

/** Символ после позиции внутри абзаца ("" — конец абзаца). */
export function charAfter($pos: ResolvedPos): string {
  if (!$pos.parent.inlineContent) return "";
  const text = $pos.parent.textBetween($pos.parentOffset, $pos.parent.content.size, undefined, leafText);
  return text ? String.fromCodePoint(text.codePointAt(0) ?? 32) : "";
}

/**
 * Транзакция: чипы uids вместо [from, to] с пробелами по краям, чтобы чип не
 * слипся со словом («идёт по@Image 2»). Сверх 64 ссылок лишние не ставятся
 * (материалы всё равно остаются в лотке).
 */
export function refInsertTransaction(state: EditorState, from: number, to: number, uids: readonly Uid[]): Transaction | null {
  const schema = state.schema;
  const size = state.doc.content.size;
  const a = Math.max(0, Math.min(from, size));
  const b = Math.max(a, Math.min(to, size));
  const budget = MAX_REFS - countContent(state.doc).refs + countContent(state.doc.slice(a, b).content).refs;
  const list = uids.filter(isUid).slice(0, Math.max(0, budget));
  if (!list.length) return null;
  const $a = state.doc.resolve(a);
  const $b = state.doc.resolve(b);
  const before = charBefore($a);
  const after = charAfter($b);
  const nodes: PMNode[] = [];
  if (before && !/\s/u.test(before) && !OPENERS.has(before)) nodes.push(schema.text(" "));
  list.forEach((uid, i) => {
    if (i > 0) nodes.push(schema.text(" "));
    nodes.push(schema.nodes[REF_NODE].create({ asset: uid }));
  });
  if (!after || !CLOSERS_OR_PUNCT.test(after)) nodes.push(schema.text(" "));
  const inline = Fragment.fromArray(nodes);
  // Выделено всё (Ctrl+A) или несколько абзацев целиком: заменяем одним абзацем с чипами.
  if (!$a.parent.inlineContent || !$b.parent.inlineContent) {
    return state.tr.replaceWith(a, b, schema.nodes.paragraph.create(null, inline));
  }
  return state.tr.replaceWith(a, b, inline);
}

/* ------------------------------------------------------------------ */
/* Метки ожидания (файл вставлен — чип появится здесь)                 */
/* ------------------------------------------------------------------ */

type PendingMark = { id: string; pos: number; text: string };
type PendingState = { marks: PendingMark[] };
type PendingMeta = { add?: PendingMark; remove?: string };

export const pendingKey = new PluginKey<PendingState>("vsPending");

let pendingSeq = 0;

export function pendingPlugin(): Plugin<PendingState> {
  return new Plugin<PendingState>({
    key: pendingKey,
    state: {
      init: () => ({ marks: [] }),
      apply(tr, value) {
        const meta = tr.getMeta(pendingKey) as PendingMeta | undefined;
        if (!tr.docChanged && !meta) return value;
        // assoc -1: напечатанное в этой же точке уходит ПОСЛЕ будущего чипа.
        let marks = tr.docChanged ? value.marks.map((m) => ({ ...m, pos: tr.mapping.map(m.pos, -1) })) : value.marks;
        if (meta?.add) marks = [...marks, meta.add];
        if (meta?.remove) marks = marks.filter((m) => m.id !== meta.remove);
        return { marks };
      },
    },
    props: {
      decorations(state) {
        const marks = pendingKey.getState(state)?.marks || [];
        if (!marks.length) return null;
        return DecorationSet.create(
          state.doc,
          marks.map((m) =>
            Decoration.widget(
              m.pos,
              () => {
                const el = document.createElement("span");
                el.className = "vs-pending";
                el.setAttribute("contenteditable", "false");
                el.setAttribute("aria-hidden", "true");
                el.textContent = m.text;
                return el;
              },
              { key: `vs-pending-${m.id}`, side: -1 },
            ),
          ),
        );
      },
    },
  });
}

/** Поставить метку ожидания в позицию pos; вернуть её id. */
export function addPending(view: EditorView, pos: number, text: string): string {
  const id = `p${Date.now().toString(36)}${++pendingSeq}`;
  const safe = Math.max(0, Math.min(pos, view.state.doc.content.size));
  view.dispatch(view.state.tr.setMeta(pendingKey, { add: { id, pos: safe, text } } satisfies PendingMeta));
  return id;
}

/** Снять метку и узнать, где она теперь (после всех правок). null — метки нет. */
export function takePending(view: EditorView, id: string): number | null {
  if (view.isDestroyed) return null;
  const mark = pendingKey.getState(view.state)?.marks.find((m) => m.id === id);
  view.dispatch(view.state.tr.setMeta(pendingKey, { remove: id } satisfies PendingMeta));
  return mark ? mark.pos : null;
}

/* ------------------------------------------------------------------ */
/* Файлы из буфера и перетаскивания — в inputHelpers.ts (без TipTap)    */
/* ------------------------------------------------------------------ */

export { imageFiles } from "./inputHelpers";
