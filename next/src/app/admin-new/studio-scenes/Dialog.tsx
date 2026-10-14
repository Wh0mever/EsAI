"use client";

import { useEffect, useRef, type ReactNode } from "react";
import { createPortal } from "react-dom";

/**
 * Окно страницы сцен — то же, что «В витрину» у витрины видеостудии: своё, а
 * не Modal из components/dialog, потому что тот рисуется в document.body мимо
 * обёртки data-theme="dark" панели и при светлой теме сайта вышел бы светлым.
 * Монтируется только на время действия — поля каждый раз чистые.
 */
type Props = {
  title: string;
  subtitle?: ReactNode;
  /** Запрос в пути: закрыть нельзя — ответ сервера некуда было бы показать. */
  busy: boolean;
  /** Ссылка постоянная: на неё вешается Escape. */
  onClose: () => void;
  onSubmit: () => void;
  /** Отказ — над кнопками, а не в конце длинной формы: там его не увидят. */
  error?: string | null;
  footer: ReactNode;
  children: ReactNode;
  wide?: boolean;
};

export default function Dialog({
  title,
  subtitle,
  busy,
  onClose,
  onSubmit,
  error = null,
  footer,
  children,
  wide = false,
}: Props) {
  const boxRef = useRef<HTMLDivElement>(null);
  // Закрываем, только если и нажали, и отпустили на затемнении: выделяя текст
  // мышью, легко увести её за край окна — набранное терять нельзя.
  const pressedOutside = useRef(false);

  // Фокус: окно открылось — в первое поле, закрылось — обратно на кнопку,
  // которая его открыла. Иначе Tab ходит по строкам под затемнением.
  useEffect(() => {
    const before = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    const box = boxRef.current;
    try {
      (box?.querySelector<HTMLElement>("input[type=text]") ?? box)?.focus({ preventScroll: true });
    } catch {}
    return () => {
      try {
        if (before?.isConnected) before.focus({ preventScroll: true });
      } catch {}
    };
  }, []);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape" && !busy) onClose();
    };
    document.addEventListener("keydown", onKey);
    const prev = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.removeEventListener("keydown", onKey);
      document.body.style.overflow = prev || "";
    };
  }, [busy, onClose]);

  if (typeof document === "undefined") return null;

  return createPortal(
    <div
      data-theme="dark"
      className="fixed inset-0 z-[1100] flex items-end justify-center bg-black/80 text-foreground sm:items-center sm:p-4"
      onMouseDown={(e) => {
        pressedOutside.current = e.target === e.currentTarget;
      }}
      onClick={(e) => {
        if (e.target === e.currentTarget && pressedOutside.current && !busy) onClose();
      }}
    >
      <div
        ref={boxRef}
        tabIndex={-1}
        role="dialog"
        aria-modal="true"
        aria-label={title}
        className={`flex max-h-[92dvh] w-full flex-col overflow-hidden rounded-t-2xl border border-border bg-surface outline-none sm:rounded-2xl ${
          wide ? "max-w-3xl" : "max-w-lg"
        }`}
      >
        <div className="border-b border-border px-5 py-4">
          <h3 className="text-base font-semibold">{title}</h3>
          {subtitle && <div className="mt-1 text-sm text-muted">{subtitle}</div>}
        </div>

        <form
          noValidate
          className="flex min-h-0 flex-1 flex-col"
          onSubmit={(e) => {
            e.preventDefault();
            onSubmit();
          }}
        >
          <div className="min-h-0 flex-1 space-y-5 overflow-y-auto overscroll-contain px-5 py-4">{children}</div>
          {error && (
            <div
              role="alert"
              className="mx-5 mb-3 max-h-28 overflow-y-auto rounded-xl border border-status-fail/40 bg-status-fail/10 px-3 py-2 text-sm text-status-fail"
            >
              {error}
            </div>
          )}
          <div className="flex flex-wrap justify-end gap-2 border-t border-border px-5 py-3 pb-[calc(0.75rem+env(safe-area-inset-bottom,0px))]">
            {footer}
          </div>
        </form>
      </div>
    </div>,
    document.body,
  );
}
