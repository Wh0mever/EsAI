"use client";

import { useCallback, useRef, useState } from "react";
import type { RefCallback } from "react";
import { prefersReducedMotion } from "../../ui/useAutoplayAllowed";
import { edgeFade, pageStep, type EdgeFade } from "./stripLogic";

/**
 * Горизонтальная лента с мягкими краями.
 *
 *   const { attach, fade } = useEdgeFade<HTMLDivElement>();
 *   <div ref={attach} className={vx("vs-noscroll overflow-x-auto", EDGE_FADE[fade])}>
 *     <ul className="flex w-max gap-3">…</ul>
 *   </div>
 *
 * vs-fade-x гасит оба края сразу: у ленты, которая стоит в начале, первая
 * карточка выглядела бы полупрозрачной. Поэтому край гаснет только там, где
 * за ним есть продолжение, а когда всё помещается (чипы на широком экране
 * переносятся строками) маски нет вовсе.
 *
 * Содержимое ленты — её первый потомок: за его шириной тоже следим (проекты
 * догружаются, меняется язык). page() листает на экран ленты — для стрелок
 * в шапке секции.
 *
 * Результат разбирают на части сразу: линтер считает ссылкой весь объект,
 * из которого что-то ушло в ref, и чтение fade из него принял бы за ошибку.
 */

/** Ширина затухания у края та же, что у vs-fade-x (globals.css) — 28 px. */
export const EDGE_FADE: Record<EdgeFade, string> = {
  none: "",
  start: "mask-r-from-[calc(100%-28px)]",
  mid: "vs-fade-x",
  end: "mask-l-from-[calc(100%-28px)]",
};

export type EdgeFadeStrip<T extends HTMLElement> = {
  /** Ставится в ref прокручиваемого блока. */
  attach: RefCallback<T>;
  fade: EdgeFade;
  page: (dir: -1 | 1) => void;
};

/** Расстояние между началами двух первых карточек ленты; 0 — карточка одна. */
function cardPitch(list: Element | null): number {
  const first = list?.children[0];
  const second = list?.children[1];
  if (!(first instanceof HTMLElement) || !(second instanceof HTMLElement)) return 0;
  return second.offsetLeft - first.offsetLeft;
}

export function useEdgeFade<T extends HTMLElement>(): EdgeFadeStrip<T> {
  const [fade, setFade] = useState<EdgeFade>("none");
  const box = useRef<T | null>(null);

  const attach = useCallback((node: T | null) => {
    box.current = node;
    if (!node) return;
    const measure = () => setFade(edgeFade(node.scrollLeft, node.clientWidth, node.scrollWidth));
    node.addEventListener("scroll", measure, { passive: true });
    // Наблюдатель сообщает размер сразу после подписки — это и есть первый замер.
    const sizes = typeof ResizeObserver === "undefined" ? null : new ResizeObserver(measure);
    sizes?.observe(node);
    if (node.firstElementChild) sizes?.observe(node.firstElementChild);
    return () => {
      node.removeEventListener("scroll", measure);
      sizes?.disconnect();
      box.current = null;
    };
  }, []);

  const page = useCallback((dir: -1 | 1) => {
    const node = box.current;
    if (!node) return;
    node.scrollBy({
      left: dir * pageStep(node.clientWidth, cardPitch(node.firstElementChild)),
      behavior: prefersReducedMotion() ? "auto" : "smooth",
    });
  }, []);

  return { attach, fade, page };
}
