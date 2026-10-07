"use client";

import { useSyncExternalStore } from "react";

/**
 * Сколько колонок сейчас у сетки галереи.
 *
 * Пороги те же, что у её классов md:grid-cols-3 и xl:grid-cols-4, и тоже в
 * rem — иначе при крупном шрифте браузера счёт разошёлся бы с вёрсткой. От
 * числа колонок зависят первая порция (на телефоне она короче) и очередь, в
 * которой появляются карточки ряда.
 */
export type GridCols = 2 | 3 | 4;

const MD_QUERY = "(min-width: 48rem)";
const XL_QUERY = "(min-width: 80rem)";

const canMatch = () => typeof window !== "undefined" && typeof window.matchMedia === "function";

function read(): GridCols {
  if (!canMatch()) return 2;
  if (window.matchMedia(XL_QUERY).matches) return 4;
  return window.matchMedia(MD_QUERY).matches ? 3 : 2;
}

function subscribe(onChange: () => void): () => void {
  if (!canMatch()) return () => {};
  const queries = [window.matchMedia(MD_QUERY), window.matchMedia(XL_QUERY)];
  for (const query of queries) query.addEventListener("change", onChange);
  return () => {
    for (const query of queries) query.removeEventListener("change", onChange);
  };
}

// На сервере и до гидрации — телефон: короткая первая порция.
const onServer = (): GridCols => 2;

export function useGridCols(): GridCols {
  return useSyncExternalStore(subscribe, read, onServer);
}
