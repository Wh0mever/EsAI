"use client";

import { useEffect, useRef } from "react";

/**
 * Фокус клавиатуры для окна: открылось — фокус уходит внутрь, закрылось —
 * возвращается туда, где был (на кнопку, открывшую окно).
 *
 * Общее окно (components/dialog/Dialog) фокус не трогает: без этого он остаётся
 * на кнопке под затемнением, и Tab идёт по странице за окном. Ref вешается на
 * контейнер содержимого с tabIndex={-1} — не на поле ввода, чтобы на телефоне
 * вместе с окном не выезжала клавиатура.
 */
export function useDialogFocus<T extends HTMLElement>(open: boolean) {
  const ref = useRef<T>(null);

  useEffect(() => {
    if (!open) return;
    const before = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    try {
      ref.current?.focus({ preventScroll: true });
    } catch {}
    return () => {
      // Кнопки уже может не быть на странице (после заявки её сменила карточка статуса).
      try {
        if (before?.isConnected) before.focus({ preventScroll: true });
      } catch {}
    };
  }, [open]);

  return ref;
}
