"use client";

import { useEffect, useRef, useState, type ReactNode } from "react";
import { createPortal } from "react-dom";
import type { CrError } from "@/lib/creators/types";
import { BTN_LG, BTN_PRIMARY, BTN_PRIMARY_DANGER, ErrorBox, INPUT } from "./ui";

/**
 * Окно действия раздела «Creators»: что делаем, поля, причина, кнопка.
 *
 * Своё окно, а не Modal из components/dialog: тот рисуется в document.body,
 * мимо обёртки data-theme="dark" панели, и при светлой теме сайта окно в
 * тёмной админке вышло бы светлым. Здесь тема задана на самом окне.
 *
 * Окно монтируется только на время действия (`{dialog && <ReasonDialog …/>}`),
 * поэтому причина и ошибка каждый раз начинаются с чистого листа.
 */
type Props = {
  title: string;
  /** Пояснение под заголовком: над кем действие и чем оно закончится. */
  description?: ReactNode;
  /** required — без причины сервер откажет (reason_required); hidden — причины у действия нет. */
  reason?: "required" | "optional" | "hidden";
  reasonLabel?: string;
  confirmLabel?: string;
  danger?: boolean;
  /** Свои поля действия (TXID, уровень, флажки) — над причиной. */
  children?: ReactNode;
  /** false — свои поля ещё не заполнены, кнопка выключена. */
  canSubmit?: boolean;
  /** Вопрос window.confirm перед запросом — для необратимого. */
  confirmText?: string;
  /** Выполнить действие. null — успех (окно закроется), иначе отказ сервера. */
  onSubmit: (reason: string) => Promise<CrError | null>;
  onClose: () => void;
};

export default function ReasonDialog({
  title,
  description,
  reason = "required",
  reasonLabel = "Причина",
  confirmLabel = "Подтвердить",
  danger = false,
  children,
  canSubmit = true,
  confirmText,
  onSubmit,
  onClose,
}: Props) {
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<CrError | null>(null);
  const dialogRef = useRef<HTMLDivElement>(null);

  // Фокус клавиатуры: окно открылось — в первое поле (TXID, уровень, причина),
  // закрылось — обратно на кнопку, которая его открыла. Иначе фокус остаётся
  // под затемнением и Tab ходит по таблице за окном.
  useEffect(() => {
    const before = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    const box = dialogRef.current;
    const field = box?.querySelector<HTMLElement>(
      "input:not([type=hidden]):not([type=checkbox]):not([type=radio]):not([disabled]), select:not([disabled]), textarea:not([disabled])",
    );
    try {
      (field ?? box)?.focus({ preventScroll: true });
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

  const value = text.trim();
  const ready = canSubmit && (reason !== "required" || value.length > 0);

  const submit = async () => {
    if (!ready || busy) return;
    if (confirmText && !confirm(confirmText)) return;
    setBusy(true);
    setError(null);
    const failure = await onSubmit(reason === "hidden" ? "" : value);
    setBusy(false);
    if (failure) setError(failure);
    else onClose();
  };

  return createPortal(
    <div
      data-theme="dark"
      className="fixed inset-0 z-[1100] flex items-end justify-center bg-black/80 text-foreground sm:items-center sm:p-4"
      onClick={() => {
        if (!busy) onClose();
      }}
    >
      <div
        ref={dialogRef}
        tabIndex={-1}
        role="dialog"
        aria-modal="true"
        aria-label={title}
        className="flex max-h-[92dvh] w-full max-w-md flex-col overflow-hidden rounded-t-2xl border border-border bg-surface outline-none sm:rounded-2xl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="border-b border-border px-5 py-4">
          <h3 className="text-base font-semibold">{title}</h3>
          {description ? <div className="mt-1 text-sm text-muted">{description}</div> : null}
        </div>

        <form
          className="flex min-h-0 flex-1 flex-col"
          onSubmit={(e) => {
            e.preventDefault();
            submit();
          }}
        >
          <div className="min-h-0 flex-1 space-y-4 overflow-y-auto overscroll-contain px-5 py-4">
            {children}

            {reason !== "hidden" && (
              <label className="block text-sm">
                <span className="text-muted">
                  {reasonLabel}
                  {reason === "required" ? " *" : " (необязательно)"}
                </span>
                <textarea
                  value={text}
                  onChange={(e) => setText(e.target.value)}
                  rows={3}
                  maxLength={500}
                  className={`${INPUT} mt-1.5 w-full resize-y`}
                />
              </label>
            )}

            <ErrorBox error={error} />
          </div>

          <div className="flex justify-end gap-2 border-t border-border px-5 py-3">
            <button type="button" onClick={onClose} disabled={busy} className={BTN_LG}>
              Отмена
            </button>
            <button
              type="submit"
              disabled={!ready || busy}
              className={danger ? BTN_PRIMARY_DANGER : BTN_PRIMARY}
            >
              {busy ? "Выполняю…" : confirmLabel}
            </button>
          </div>
        </form>
      </div>
    </div>,
    document.body,
  );
}
