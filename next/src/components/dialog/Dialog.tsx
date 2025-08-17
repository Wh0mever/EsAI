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
}: ConfirmationModalProps) {
  // Close on ESC
  useEffect(() => {
    if (!isOpen) return;
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onCancel();
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [isOpen, onCancel]);

  if (!isOpen) return null;

  return createPortal(
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50">
      <div
        role="dialog"
        aria-modal="true"
        className="bg-neutral-900 rounded-lg shadow-lg w-full max-w-md p-6 relative"
        onClick={(e) => e.stopPropagation()}
      >
        <h2 className="text-xl font-semibold mb-4 border-b py-2 border-neutral-600">{title}</h2>
        <button
          className="text-gray-400 text-xl absolute right-5 top-5 hover:text-gray-200"
          onClick={onCancel}
          aria-label="Close"
        >
          <IoClose />
        </button>
        <div className="flex justify-end gap-3 mt-3">
          <Button className="px-4 py-2 text-sm bg-rose-700 text-white rounded hover:bg-rose-800" onClick={onConfirm}>
            {confirmText}
          </Button>
          <Button className="px-4 py-2 text-sm bg-gray-500 rounded hover:bg-gray-400" onClick={onCancel}>
            {cancelText}
          </Button>
        </div>
      </div>
    </div>,
    document.body
  );
}

export function Modal({ title, children, size = "md", onClose, open }: ModalProps) {
  // Avoid SSR mismatch
  if (typeof window === "undefined") return null;

  // Body scroll lock only when open
  useEffect(() => {
    if (!open) return;
    const prev = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.body.style.overflow = prev || "";
    };
  }, [open]);

  // Close on ESC when open
  const onKey = useCallback(
    (e: KeyboardEvent) => {
      if (open && e.key === "Escape") onClose();
    },
    [open, onClose]
  );

  useEffect(() => {
    if (!open) return;
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [open, onKey]);

  if (!open) return null;

  const containerClasses = size === "full" ? "w-full h-full" : `w-full ${sizeClasses[size]} mx-4`;

  return createPortal(
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/90"
      onClick={onClose} // backdrop click
    >
      <div
        role="dialog"
        aria-modal="true"
        aria-label={title}
        className={`bg-neutral-900 p-6 relative border border-neutral-600 ${containerClasses}`}
        onClick={(e) => e.stopPropagation()} // prevent backdrop close
      >
        <h2 className="text-xl font-semibold mb-4 border-b py-2 border-neutral-600 capitalize">{title}</h2>
        <button
          onClick={onClose}
          className="absolute top-5 right-5 text-xl text-gray-400 hover:text-gray-200 duration-300 transition cursor-pointer"
          aria-label="Close"
        >
          <IoClose />
        </button>
        <div className="mt-3">{children}</div>
      </div>
    </div>,
    document.body
  );
}
