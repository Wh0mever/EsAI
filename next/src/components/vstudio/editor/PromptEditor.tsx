"use client";

/**
 * Видеостудия: поле промпта (§9.5) — точка входа для композера.
 *
 *   <PromptEditor doc labels pickerItems onChange onUpload onGenerate onSubmit
 *                 handleRef onPickLibrary onMention fullscreen onFullscreenChange … />
 *
 * TipTap (≈70–100 КБ gzip) грузится отдельным куском через next/dynamic
 * (ssr: false) — только на /video-studio. Если кусок не загрузился или
 * редактор упал при создании, показывается TextareaFallback с теми же
 * пропсами: теги пишутся текстом, запрос уходит с prompt_text (onPromptText).
 * Принудительно включить textarea (проверка на телефонах):
 * localStorage["vstudio:editor"]="textarea" или ?vseditor=textarea в адресе.
 */
import dynamic from "next/dynamic";
import { Component, useSyncExternalStore, type ErrorInfo, type ReactNode } from "react";
import type { VsPromptEditorProps } from "./editorTypes";
import TextareaFallback from "./TextareaFallback";

export type { PromptEditorExtraProps, VsPromptEditorProps } from "./editorTypes";

const loadEditor = () => import("./TipTapEditor");

/** Начать загрузку редактора заранее (например, при открытии студии). */
export function preloadPromptEditor(): void {
  void loadEditor().catch(() => undefined);
}

function EditorSkeleton() {
  return (
    <div className="flex min-h-[4.75rem] flex-col gap-2 px-3 py-3" aria-busy="true">
      <div className="h-3.5 w-3/4 animate-pulse rounded bg-surface-3" />
      <div className="h-3.5 w-1/2 animate-pulse rounded bg-surface-3" />
    </div>
  );
}

function LoadFailed(props: VsPromptEditorProps) {
  return <TextareaFallback {...props} />;
}

const RichEditor = dynamic<VsPromptEditorProps>(
  () =>
    loadEditor()
      .then((m) => m.default)
      .catch((err: unknown) => {
        // Сеть оборвалась или браузер не разобрал модуль — работаем без TipTap.
        console.error("[vstudio] editor chunk failed, using textarea", err);
        return LoadFailed;
      }),
  { ssr: false, loading: () => <EditorSkeleton /> },
);

/** Редактор упал при создании или рендере — та же страница, но с textarea. */
class EditorBoundary extends Component<{ fallback: ReactNode; children: ReactNode }, { failed: boolean }> {
  state = { failed: false };

  static getDerivedStateFromError() {
    return { failed: true };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error("[vstudio] editor crashed, using textarea", error, info.componentStack);
  }

  render() {
    return this.state.failed ? this.props.fallback : this.props.children;
  }
}

const PREF_KEY = "vstudio:editor";

function readPreferTextarea(): boolean {
  try {
    if (new URLSearchParams(window.location.search).get("vseditor") === "textarea") return true;
    return window.localStorage.getItem(PREF_KEY) === "textarea";
  } catch {
    return false;
  }
}

const noopSubscribe = () => () => undefined;

export default function PromptEditor(props: VsPromptEditorProps) {
  // Читается один раз на клиенте; на сервере — false (там всё равно скелетон).
  const preferTextarea = useSyncExternalStore(noopSubscribe, readPreferTextarea, () => false);
  if (preferTextarea) return <TextareaFallback {...props} />;
  return (
    <EditorBoundary fallback={<TextareaFallback {...props} />}>
      <RichEditor {...props} />
    </EditorBoundary>
  );
}
