"use client";

import { useEffect, useRef } from "react";

/**
 * «Откройте пополнение» от компонентов вне страницы (напоминание об остатке).
 * Страница со своим окном пакетов (чат, видеостудия, склейка) ловит событие и
 * открывает окно на месте — человек не уходит из студии посреди генерации.
 * Никто не поймал — requestTopUp вернёт false, и вызывающий ведёт на /pricing.
 */
export const TOPUP_EVENT = "esai:topup";

export function requestTopUp(): boolean {
  if (typeof window === "undefined") return false;
  const event = new Event(TOPUP_EVENT, { cancelable: true });
  return !window.dispatchEvent(event);
}

export function useTopUpRequest(open: () => void) {
  const ref = useRef(open);
  useEffect(() => {
    ref.current = open;
  });
  useEffect(() => {
    const onRequest = (e: Event) => {
      e.preventDefault();
      ref.current();
    };
    window.addEventListener(TOPUP_EVENT, onRequest);
    return () => window.removeEventListener(TOPUP_EVENT, onRequest);
  }, []);
}
