"use client";

import clsx from "clsx";
import { useId, type ReactNode } from "react";

/**
 * Общие куски форм Creative Studio. Цвета — токены сайта (bg-surface,
 * border-border, text-muted…), поэтому тёмная и светлая темы работают сами;
 * золото #F5C518 — фирменный акцент раздела, текст на нём всегда чёрный.
 */
export const FOCUS =
  "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--accent-text)] focus-visible:ring-offset-2 focus-visible:ring-offset-background";

export const CARD = "rounded-2xl border border-border bg-surface";

export const INPUT = clsx(
  "w-full rounded-xl border border-border bg-background px-3.5 py-2.5 text-[15px] text-foreground placeholder:text-muted-2",
  // Фокус — токеном темы: золото на светлом фоне даёт ~1.5:1, --accent-text держит 3:1 (в тёмной теме это то же золото).
  "transition-colors hover:border-border-strong focus:border-[var(--accent-text)] focus:outline-none focus:ring-2 focus:ring-[var(--accent-text)]/50",
  "disabled:cursor-not-allowed disabled:opacity-60",
);

export const BTN_GOLD = clsx(
  "inline-flex min-h-11 items-center justify-center gap-2 rounded-xl bg-[#F5C518] px-5 text-[15px] font-semibold text-black",
  "transition hover:bg-[#ffd633] active:scale-[0.99] disabled:cursor-not-allowed disabled:opacity-55 disabled:active:scale-100",
  FOCUS,
);

export const BTN_GHOST = clsx(
  "inline-flex min-h-10 items-center justify-center gap-2 rounded-xl border border-border bg-surface px-4 text-sm font-medium text-foreground",
  "transition-colors hover:border-[#F5C518]/60 disabled:cursor-not-allowed disabled:opacity-55",
  FOCUS,
);

export const chip = (on: boolean) =>
  clsx(
    "inline-flex min-h-9 items-center justify-center gap-1.5 rounded-lg border px-3 text-sm font-medium transition-colors",
    FOCUS,
    on ? "border-[#F5C518] bg-[#F5C518] text-black" : "border-border bg-background text-foreground hover:border-[#F5C518]/60",
    "disabled:cursor-not-allowed disabled:opacity-50",
  );

/** Подпись, подсказка и ошибка поля. id поля передаётся детям через render-prop. */
export function FieldShell({
  label,
  hint,
  error,
  required,
  counter,
  as = "div",
  children,
}: {
  label: string;
  hint?: string;
  error?: string;
  required?: boolean;
  counter?: ReactNode;
  /** fieldset — для групп (кнопки-варианты, загрузки) */
  as?: "div" | "fieldset";
  children: (ids: { id: string; describedBy: string | undefined; labelId: string }) => ReactNode;
}) {
  const id = useId();
  const hintId = `${id}-hint`;
  const errId = `${id}-err`;
  const labelId = `${id}-label`;
  const describedBy = [hint ? hintId : "", error ? errId : ""].filter(Boolean).join(" ") || undefined;
  const head = (
    <span className="flex items-baseline justify-between gap-3">
      <span id={labelId} className="text-sm font-semibold text-foreground">
        {label}
        {required && (
          <span aria-hidden="true" className="ml-0.5 text-[var(--accent-text)]">
            *
          </span>
        )}
      </span>
      {counter}
    </span>
  );
  const tail = (
    <>
      {hint && (
        <p id={hintId} className="text-xs leading-snug text-muted">
          {hint}
        </p>
      )}
      {error && (
        <p id={errId} role="alert" className="text-xs font-medium text-status-fail">
          {error}
        </p>
      )}
    </>
  );
  if (as === "fieldset") {
    return (
      <fieldset className="min-w-0 space-y-2" aria-describedby={describedBy}>
        <legend className="mb-2 w-full">{head}</legend>
        {children({ id, describedBy, labelId })}
        {tail}
      </fieldset>
    );
  }
  return (
    <div className="space-y-2">
      <label htmlFor={id} className="block">
        {head}
      </label>
      {children({ id, describedBy, labelId })}
      {tail}
    </div>
  );
}

export function Spinner({ className }: { className?: string }) {
  return (
    <span
      aria-hidden="true"
      className={clsx("inline-block size-4 animate-spin rounded-full border-2 border-current border-r-transparent motion-reduce:animate-none", className)}
    />
  );
}

export function Skeleton({ className }: { className?: string }) {
  return <div aria-hidden="true" className={clsx("animate-pulse rounded-xl bg-surface-2 motion-reduce:animate-none", className)} />;
}

/** «мм:сс» для таймера ожидания. */
export function clock(seconds: number): string {
  const s = Math.max(0, Math.floor(seconds));
  const m = Math.floor(s / 60);
  return `${m}:${String(s % 60).padStart(2, "0")}`;
}

/** Имя файла результата: только наши слова — инструмент, начало uid, номер. */
export function resultFilename(tool: string, uid: string, index: number, mime: string, url: string): string {
  let ext = "";
  if (mime.includes("png")) ext = "png";
  else if (mime.includes("webp")) ext = "webp";
  else if (mime.includes("jpeg") || mime.includes("jpg")) ext = "jpg";
  else if (mime.includes("mp4")) ext = "mp4";
  else if (mime.includes("webm")) ext = "webm";
  else {
    const m = /\.([a-z0-9]{2,4})(?:$|\?)/i.exec(url);
    ext = m ? m[1].toLowerCase() : mime.startsWith("video") ? "mp4" : "jpg";
  }
  return `esai-${tool}-${uid.slice(0, 8)}${index > 0 ? `-${index + 1}` : ""}.${ext}`;
}
