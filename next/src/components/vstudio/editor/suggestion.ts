/**
 * Видеостудия, редактор промпта: «@» открывает выбор материалов (§9.5).
 *
 * Сам список рисует React (MentionPicker) — здесь только мост: плагин
 * @tiptap/suggestion сообщает, что «@запрос» набран / изменился / закрыт, и
 * отдаёт клавиши ↑↓ Enter Esc, пока список открыт. Кнопка «@ Материалы»
 * делает то же самое, вставляя «@» в позицию курсора (openAt) — один путь
 * для клавиатуры, мыши и телефона.
 */
import { Extension, type Range } from "@tiptap/core";
import { PluginKey, type EditorState } from "@tiptap/pm/state";
import type { EditorView } from "@tiptap/pm/view";
import Suggestion, { exitSuggestion } from "@tiptap/suggestion";
import { ALLOWED_PREFIXES } from "./inputHelpers";
import { charBefore } from "./pasteRelink";

export { ALLOWED_PREFIXES, atBeforeCaret } from "./inputHelpers";

export const mentionKey = new PluginKey("vsMention");

export type MentionSession = {
  /** Текст после «@» (фильтр списка). */
  query: string;
  /** Диапазон «@запрос» в документе — его заменит выбранный чип. */
  range: Range;
  /** Прямоугольник курсора/«@» на экране (null — не знаем). */
  rect: () => DOMRect | null;
};

export type MentionBridge = {
  open: (s: MentionSession) => void;
  update: (s: MentionSession) => void;
  close: (reason: "exit" | "escape") => void;
  /** Клавиша, пока список открыт: true — обработана списком. */
  keyDown: (event: KeyboardEvent) => boolean;
};

type Props = { query: string; range: Range; clientRect?: (() => DOMRect | null) | null };

function sessionOf(p: Props): MentionSession {
  return { query: p.query || "", range: { from: p.range.from, to: p.range.to }, rect: () => p.clientRect?.() ?? null };
}

export type VsMentionOptions = { bridge: MentionBridge | null };

/** Расширение «@»: Suggestion с нашим ключом и мостом в React. */
export const VsMention = Extension.create<VsMentionOptions>({
  name: "vsMention",
  // Раньше базовых клавиш: Enter/↑↓ сначала получает открытый список.
  priority: 1000,
  addOptions() {
    return { bridge: null };
  },
  addProseMirrorPlugins() {
    const bridge = () => this.options.bridge;
    return [
      Suggestion({
        editor: this.editor,
        pluginKey: mentionKey,
        char: "@",
        allowSpaces: false,
        allowedPrefixes: ALLOWED_PREFIXES,
        items: () => [],
        render: () => ({
          onStart: (p) => bridge()?.open(sessionOf(p)),
          onUpdate: (p) => bridge()?.update(sessionOf(p)),
          onExit: () => bridge()?.close("exit"),
          onKeyDown: ({ event }) => {
            if (event.key === "Escape" || event.key === "Esc") {
              bridge()?.close("escape");
              return true;
            }
            // Ctrl/⌘+Enter — «Создать», а не выбор пункта.
            if (event.metaKey || event.ctrlKey || event.altKey) return false;
            return bridge()?.keyDown(event) ?? false;
          },
        }),
      }),
    ];
  },
});

/** Список открыт? (состояние плагина Suggestion). */
export function isMentionActive(state: EditorState): boolean {
  const s = mentionKey.getState(state) as { active?: boolean } | undefined;
  return Boolean(s?.active);
}

/** Закрыть список без правки текста. */
export function closeMention(view: EditorView): void {
  if (!view.isDestroyed && isMentionActive(view.state)) exitSuggestion(view, mentionKey);
}

/** Нужен ли пробел перед «@», чтобы выбор открылся (после слова или чипа — нужен). */
export function needsSpaceBefore(state: EditorState, pos: number): boolean {
  const before = charBefore(state.doc.resolve(pos));
  return before !== "" && before !== "\n" && !ALLOWED_PREFIXES.includes(before);
}

/**
 * Кнопка «@ Материалы»: вставить «@» в позицию курсора (с пробелом перед ним,
 * если нужно) — Suggestion сам откроет список. Возвращает вставленный
 * диапазон, чтобы при отмене убрать «@» обратно.
 */
export function openAt(view: EditorView): Range | null {
  if (view.isDestroyed || !view.editable) return null;
  const { state } = view;
  const { from, to } = state.selection;
  const text = needsSpaceBefore(state, from) ? " @" : "@";
  const tr = state.tr.insertText(text, from, to).scrollIntoView();
  view.dispatch(tr);
  view.focus();
  const end = from + text.length;
  return { from, to: end };
}
