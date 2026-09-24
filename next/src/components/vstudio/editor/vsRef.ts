/**
 * Видеостудия, редактор промпта: чип-ссылка на материал (узел vsRef, §9.5).
 *
 * Неделимый inline-атом с одним атрибутом {asset: uid}. Метку («@Image 2»,
 * «@Первый кадр», «—»), состояние и aria чип берёт из RefStore — это метки
 * labels.ts, которые считает родитель по лотку. Перестановка в лотке меняет
 * только метки: документ не трогается, чипы перерисовываются на месте.
 *
 * NodeView — обычный DOM, без React-портала: на Android (Gboard, композиция)
 * это заметно надёжнее, и перерисовка 64 чипов — это 64 присваивания текста.
 * Копирование даёт «@Image N» (renderText → clipboardTextSerializer), HTML
 * несёт uid — вставка в тот же запрос возвращает те же чипы.
 *
 * Модуль без JSX (.ts): node-тесты (lib/vstudio/promptDoc.test.mjs) строят
 * из него настоящую схему редактора. React-обёртка чипа — RefNode.tsx.
 */
import { mergeAttributes, Node } from "@tiptap/core";
import type { Node as PMNode } from "@tiptap/pm/model";
import type { NodeView } from "@tiptap/pm/view";
import { copyTagFor, missingLabel, optimisticLabel } from "@/lib/vstudio/labels";
import { EXCLUDED_TAG, isUid, REF_NODE } from "@/lib/vstudio/promptDoc";
import type { RefLabel, RefLabels, Uid } from "@/lib/vstudio/types";
import { chipClassName } from "./chipStyle";

export { CHIP_STATE_CLASS, chipClassName } from "./chipStyle";

/* ------------------------------------------------------------------ */
/* Хранилище меток одного редактора                                    */
/* ------------------------------------------------------------------ */

type ChipView = { refresh: () => void };

/**
 * Метки для чипов одного экземпляра редактора. Создаётся компонентом и
 * передаётся в VsRef.configure({store}) — у двух редакторов на странице
 * свои метки.
 */
export class RefStore {
  labels: RefLabels = {};
  /** uid → до какого времени рисовать «создаётся», пока родитель кладёт материал в лоток. */
  private optimistic = new Map<Uid, number>();
  private views = new Set<ChipView>();
  private timers = new Set<ReturnType<typeof setTimeout>>();
  /** Переводы для «нет в запросе» / «создаётся» (без них — русские). */
  translate?: (key: string, options?: Record<string, unknown>) => unknown;

  constructor(labels?: RefLabels | null) {
    this.labels = labels || {};
  }

  label(uid: Uid): RefLabel {
    const known = this.labels[uid];
    if (known) return known;
    const until = this.optimistic.get(uid);
    if (until && until > Date.now()) return optimisticLabel(this.translate);
    return missingLabel(this.translate);
  }

  /** Текст чипа при копировании: «@Image N» / «@Первый кадр» / «@Image —». */
  copyText(uid: Uid): string {
    return copyTagFor(this.labels[uid]);
  }

  setLabels(labels: RefLabels): void {
    this.labels = labels || {};
    this.refreshAll();
  }

  /** Чип вставлен до того, как материал попал в лоток: не пугаем красным «нет в запросе». */
  expect(uids: readonly Uid[], ms = 5000): void {
    if (!uids.length) return;
    const until = Date.now() + ms;
    for (const uid of uids) this.optimistic.set(uid, until);
    // Срок вышел, а материала в лотке так и нет — перерисовать чип красным.
    const id = setTimeout(() => {
      this.timers.delete(id);
      this.refreshAll();
    }, ms + 50);
    this.timers.add(id);
  }

  refreshAll(): void {
    for (const v of this.views) v.refresh();
  }

  add(v: ChipView): void {
    this.views.add(v);
  }

  remove(v: ChipView): void {
    this.views.delete(v);
  }

  /**
   * Компонент редактора ушёл: таймеры больше не нужны. Чипы (views) не
   * трогаем — их снимает NodeView.destroy; в StrictMode эффект отрабатывает
   * «размонтирование» понарошку, а редактор с чипами остаётся жить.
   */
  dispose(): void {
    for (const id of this.timers) clearTimeout(id);
    this.timers.clear();
  }
}

/* ------------------------------------------------------------------ */
/* NodeView                                                            */
/* ------------------------------------------------------------------ */

class RefChipView implements NodeView {
  dom: HTMLElement;
  private node: PMNode;
  private selected = false;
  private store: RefStore;

  constructor(node: PMNode, store: RefStore) {
    this.node = node;
    this.store = store;
    const el = document.createElement("span");
    el.setAttribute("contenteditable", "false");
    el.setAttribute("role", "button");
    el.setAttribute("tabindex", "-1");
    el.setAttribute("data-vs-ref", String(node.attrs.asset || ""));
    this.dom = el;
    this.refresh();
    store.add(this);
  }

  refresh(): void {
    const label = this.store.label(String(this.node.attrs.asset || ""));
    const el = this.dom;
    if (el.textContent !== label.text) el.textContent = label.text;
    el.className = chipClassName(label.state, this.selected);
    el.setAttribute("data-state", label.state);
    el.setAttribute("aria-label", label.aria);
    el.title = label.aria;
  }

  update(node: PMNode): boolean {
    if (node.type !== this.node.type) return false;
    this.node = node;
    this.dom.setAttribute("data-vs-ref", String(node.attrs.asset || ""));
    this.refresh();
    return true;
  }

  selectNode(): void {
    this.selected = true;
    this.refresh();
  }

  deselectNode(): void {
    this.selected = false;
    this.refresh();
  }

  /** Своё содержимое чип меняет сам (метки) — ProseMirror это не касается. */
  ignoreMutation(): boolean {
    return true;
  }

  stopEvent(): boolean {
    return false;
  }

  destroy(): void {
    this.store.remove(this);
  }
}

/* ------------------------------------------------------------------ */
/* Узел                                                                */
/* ------------------------------------------------------------------ */

export type VsRefOptions = { store: RefStore | null };

export const VsRef = Node.create<VsRefOptions>({
  name: REF_NODE,
  group: "inline",
  inline: true,
  atom: true,
  selectable: true,
  draggable: false,

  addOptions() {
    return { store: null };
  },

  addAttributes() {
    return {
      asset: {
        default: null,
        parseHTML: (el: HTMLElement) => el.getAttribute("data-vs-ref"),
        renderHTML: (attrs: Record<string, unknown>) => ({ "data-vs-ref": attrs.asset }),
      },
      // Подпись на момент копирования: если uid в этом запросе неизвестен
      // (скопировали из другого проекта), вставка превратит её в тег и
      // привяжет по номеру. В prompt_doc не попадает.
      tag: {
        default: null,
        rendered: false,
        parseHTML: (el: HTMLElement) => el.getAttribute("data-vs-tag") || el.textContent || null,
      },
    };
  },

  parseHTML() {
    return [
      {
        tag: "span[data-vs-ref]",
        // Мусорный uid в чужом HTML — не наш чип: пусть будет текстом.
        getAttrs: (el) => (isUid((el as HTMLElement).getAttribute("data-vs-ref")) ? null : false),
      },
    ];
  },

  renderHTML({ node, HTMLAttributes }) {
    const text = this.options.store?.copyText(String(node.attrs.asset || "")) ?? EXCLUDED_TAG;
    return ["span", mergeAttributes(HTMLAttributes, { "data-vs-tag": text }), text];
  },

  renderText({ node }) {
    return this.options.store?.copyText(String(node.attrs.asset || "")) ?? EXCLUDED_TAG;
  },

  addNodeView() {
    const store = this.options.store ?? new RefStore();
    return ({ node }) => new RefChipView(node, store);
  },

  addKeyboardShortcuts() {
    // Backspace/Delete рядом с чипом удаляют его целиком (браузеры по-разному
    // обходятся с contenteditable=false внутри строки, особенно Safari).
    const removeAdjacent = (dir: -1 | 1) => () => {
      const { state, view } = this.editor;
      const sel = state.selection;
      if (!sel.empty) return false;
      const $pos = sel.$from;
      const node = dir < 0 ? $pos.nodeBefore : $pos.nodeAfter;
      if (!node || node.type.name !== REF_NODE) return false;
      const from = dir < 0 ? $pos.pos - node.nodeSize : $pos.pos;
      view.dispatch(state.tr.delete(from, from + node.nodeSize).scrollIntoView());
      return true;
    };
    return { Backspace: removeAdjacent(-1), Delete: removeAdjacent(1) };
  },
});
