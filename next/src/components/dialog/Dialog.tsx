"use client";

import React, { ReactNode, useEffect, useCallback } from "react";
import { createPortal } from "react-dom";
import { IoClose } from "react-icons/io5";
import { Button } from "@/components/ui/buttons/Buttons";

type ConfirmationModalProps = {
  isOpen: boolean;
  title: string;
  confirmText: string;
  cancelText: string;
  onConfirm: () => void;
  onCancel: () => void;
  /** disable Confirm button while async action in progress */
  confirmDisabled?: boolean;
  /** optional one-line description under title */
  description?: string;
  /** when confirmDisabled===true, use this text instead of confirmText */
  confirmLoadingText?: string;
};
type ModalProps = {
  title: string;
  children: ReactNode;
  size?: "full" | "lg" | "md" | "sm";
  onClose: () => void;
  open: boolean;
};

const sizeClasses = {
  sm: "max-w-sm rounded-2xl shadow-lg",
  md: "max-w-md rounded-2xl shadow-lg",
  lg: "max-w-4xl rounded-2xl shadow-lg",
  full: "w-full h-full rounded-none shadow-none",
};

export function ConfirmationModal({
  isOpen,
  title,
  confirmText,
  cancelText,
  onConfirm,
  onCancel,
  confirmDisabled = false,
  description,
  confirmLoadingText,
}: ConfirmationModalProps) {
  // Close on ESC
  useEffect(() => {
    if (!isOpen) return;
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onCancel();
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [isOpen, onCancel]);

  if (!isOpen) return null;

  const isLoading = Boolean(confirmDisabled);
  const confirmLabel = isLoading && confirmLoadingText ? confirmLoadingText : confirmText;

  return createPortal(
    // z-[1100] — ВЫШЕ выезжающего сайдбара (z-[901]); иначе подтверждение
    // удаления вылезало ПОЗАДИ сайдбара и было не видно (жалоба клиента).
    <div
      className="fixed inset-0 z-[1100] flex items-center justify-center bg-black/70 p-4"
      onClick={onCancel} // backdrop click closes
      role="dialog"
      aria-modal="true"
      aria-labelledby="confirm-modal-title"
    >
      <div
        className="bg-surface rounded-lg shadow-lg w-full max-w-md p-6 relative"
        onClick={(e) => e.stopPropagation()}
      >
        <h2 id="confirm-modal-title" className="text-xl font-semibold mb-3 border-b py-2 border-border">
          {title}
        </h2>

        {description ? (
          <p className="text-sm text-muted mb-4">{description}</p>
        ) : null}

        <button
          className="text-muted text-xl absolute right-5 top-5 hover:text-foreground"
          onClick={onCancel}
          aria-label="Close"
        >
          <IoClose />
        </button>

        <div className="flex gap-3 mt-5">
          <Button
            className="flex-1 px-5 py-3 text-base font-semibold bg-rose-600 text-white rounded-xl hover:bg-rose-700 disabled:opacity-60 disabled:cursor-not-allowed"
            onClick={onConfirm}
            disabled={isLoading}
            aria-busy={isLoading}
          >
            {confirmLabel}
          </Button>
          <Button
            className="flex-1 px-5 py-3 text-base font-semibold bg-surface-3 text-foreground rounded-xl hover:bg-surface-2"
            onClick={onCancel}
          >
            {cancelText}
          </Button>
        </div>
      </div>
    </div>,
    document.body
  );
}

export function Modal({ title, children, size = "md", onClose, open }: ModalProps) {
  if (typeof window === "undefined") return null;

  useEffect(() => {
    if (!open) return;
    const prev = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => { document.body.style.overflow = prev || ""; };
  }, [open]);

  const onKey = useCallback((e: KeyboardEvent) => {
    if (open && e.key === "Escape") onClose();
  }, [open, onClose]);

  useEffect(() => {
    if (!open) return;
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [open, onKey]);

  if (!open) return null;

  const containerClasses = size === "full"
    ? "w-full h-full"
    : `w-full ${sizeClasses[size]} mx-4 max-h-[85dvh]`; // важно: ограничение по высоте

  return createPortal(
    <div
      className="fixed inset-0 z-[1100] flex items-center justify-center bg-black/90"
      onClick={onClose}
    >
      <div
        role="dialog"
        aria-modal="true"
        aria-label={title}
        // ВАЖНО: колонка + min-h-0 + overflow-hidden
        className={`bg-surface p-6 relative border border-border ${containerClasses} flex flex-col min-h-0 overflow-hidden`}
        onClick={(e) => e.stopPropagation()}
      >
        <h2 className="text-xl font-semibold mb-4 border-b py-2 border-border capitalize">{title}</h2>
        <button
          onClick={onClose}
          className="absolute top-5 right-5 text-xl text-muted hover:text-foreground duration-300 transition cursor-pointer"
          aria-label="Close"
        >
          <IoClose />
        </button>

        {/* ВАЖНО: единственная прокручиваемая область */}
        <div className="mt-3 flex-1 min-h-0 overflow-auto overscroll-contain touch-pan-y">
          {children}
        </div>
      </div>
    </div>,
    document.body
  );
}
