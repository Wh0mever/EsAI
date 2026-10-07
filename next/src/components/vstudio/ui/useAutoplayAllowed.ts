"use client";

import { useSyncExternalStore } from "react";

/**
 * Можно ли заводить движение без спроса.
 *
 * Два системных «нет»: просьба «меньше движения» и режим экономии трафика.
 * Оба человек включил на уровне устройства, поэтому первый экран их слушается:
 * ролики не стартуют сами (остаётся кнопка), карусель не листается, секции не
 * выезжают. CSS-анимации vs-* гасит медиа-запрос в globals.css, а всё, что
 * двигает JS, спрашивает здесь.
 */

const REDUCE_QUERY = "(prefers-reduced-motion: reduce)";

/** navigator.connection есть не везде (Safari, Firefox) и не описан в lib.dom. */
type NetworkInfo = {
  saveData?: boolean;
  addEventListener?: (type: "change", listener: () => void) => void;
  removeEventListener?: (type: "change", listener: () => void) => void;
};

function networkInfo(): NetworkInfo | null {
  if (typeof navigator === "undefined") return null;
  return (navigator as Navigator & { connection?: NetworkInfo }).connection ?? null;
}

/** Разовая проверка для обработчиков и эффектов. На сервере — true: двигать там нечего. */
export function prefersReducedMotion(): boolean {
  if (typeof window === "undefined" || typeof window.matchMedia !== "function") return true;
  return window.matchMedia(REDUCE_QUERY).matches;
}

/** Разовая проверка: ролики могут стартовать сами. */
export function autoplayAllowed(): boolean {
  return !prefersReducedMotion() && !networkInfo()?.saveData;
}

function subscribe(onChange: () => void): () => void {
  if (typeof window === "undefined" || typeof window.matchMedia !== "function") return () => {};
  const media = window.matchMedia(REDUCE_QUERY);
  const net = networkInfo();
  media.addEventListener("change", onChange);
  net?.addEventListener?.("change", onChange);
  return () => {
    media.removeEventListener("change", onChange);
    net?.removeEventListener?.("change", onChange);
  };
}

// На сервере и до гидрации — тихий вариант: постер вместо ролика, без движения.
const autoplayOnServer = () => false;
const reducedOnServer = () => true;

/** false — человек просил меньше движения или бережёт трафик: вместо автозапуска показываем кнопку. */
export function useAutoplayAllowed(): boolean {
  return useSyncExternalStore(subscribe, autoplayAllowed, autoplayOnServer);
}

/** true — «меньше движения»: карусель не листается сама, появление секций без анимации. */
export function useReducedMotion(): boolean {
  return useSyncExternalStore(subscribe, prefersReducedMotion, reducedOnServer);
}

/* ---------- курсор ---------- */

// Мышь или трекпад: наведение существует. На телефоне «наведения» нет — там
// ролик в карточке заводится, когда она на экране.
const HOVER_QUERY = "(hover: hover) and (pointer: fine)";

function canHover(): boolean {
  return typeof window !== "undefined" && typeof window.matchMedia === "function" && window.matchMedia(HOVER_QUERY).matches;
}

function subscribeHover(onChange: () => void): () => void {
  if (typeof window === "undefined" || typeof window.matchMedia !== "function") return () => {};
  const media = window.matchMedia(HOVER_QUERY);
  media.addEventListener("change", onChange);
  return () => media.removeEventListener("change", onChange);
}

const hoverOnServer = () => false;

/** true — у устройства есть курсор (ролик можно заводить наведением). */
export function useCanHover(): boolean {
  return useSyncExternalStore(subscribeHover, canHover, hoverOnServer);
}
