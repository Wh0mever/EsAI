/**
 * Видеостудия, редактор промпта: пропсы реализации.
 *
 * Контракт — PromptEditorProps из lib/vstudio/types.ts (§9.5). Здесь только
 * необязательные дополнения, которых там пока нет; оба редактора (TipTap и
 * запасная textarea) принимают одно и то же.
 */
import type { MentionVia, PromptEditorProps, Uid } from "@/lib/vstudio/types";

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
};

export type VsPromptEditorProps = PromptEditorProps & PromptEditorExtraProps;

export type { MentionVia };
