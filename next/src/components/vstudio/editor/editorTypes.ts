/**
 * Видеостудия, редактор промпта: пропсы реализации.
 *
 * Контракт — PromptEditorProps из lib/vstudio/types.ts (§9.5). Здесь только
 * необязательные дополнения, которых там пока нет; оба редактора (TipTap и
 * запасная textarea) принимают одно и то же.
 */
import type { MentionVia, PromptEditorProps, Uid } from "@/lib/vstudio/types";

/**
 * Свёрнутый вид поля (панель запроса, см. useFoldClip). Когда сворачивать,
 * решает родитель; редактор обрезает то же самое поле и сообщает, есть ли что
 * обрезать.
 */
export type PromptFoldProps = {
  /** Панель просит свёрнутый вид. Обрезается поле, только если тексту есть что прятать (cut). */
  compact: boolean;
  /** Сколько строк остаётся на виду. */
  lines: number;
  /** Тексту есть что прятать в свёрнутом поле: тогда у него кнопка, а в свёрнутом виде — затухание у среза. */
  cut: boolean;
  onCut: (cut: boolean) => void;
  /** Кнопка «Показать весь запрос» / «Свернуть запрос». */
  onToggle: () => void;
};

export type PromptEditorExtraProps = {
  /**
   * Запасная textarea (§9.5): сырой текст для prompt_text — теги разберёт
   * сервер. null — снова работает TipTap, отправлять prompt_doc. Без этого
   * пропса textarea отдаёт документ, собранный на клиенте той же грамматикой.
   */
  onPromptText?: (text: string | null) => void;
  /** Клик по чипу в тексте — например, подсветить материал в лотке. */
  onRefClick?: (asset: Uid) => void;
  /** aria-label поля (по умолчанию — placeholder). */
  ariaLabel?: string;
  className?: string;
  /** Без этого пропса поле не сворачивается вовсе. */
  fold?: PromptFoldProps;
};

export type VsPromptEditorProps = PromptEditorProps & PromptEditorExtraProps;

export type { MentionVia };
