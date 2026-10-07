"use client";

import { useCallback } from "react";
import type { RefCallback } from "react";
import { prefersReducedMotion } from "./useAutoplayAllowed";

/**
 * Секция первого экрана появляется, когда до неё долистали.
 *
 *   const reveal = useReveal<HTMLElement>();
 *   <section ref={reveal} className="vs-reveal …">
 *
 * Класс vs-reveal прячет секцию (globals.css), хук один раз добавляет vs-in,
 * когда она показалась на 15% — или заняла четверть окна ленты: высокая
 * секция на телефоне 15% своей высоты на экран может и не уместить. Или
 * когда в неё пришёл фокус. Задержку между соседями задаёт сама секция через
 * --vs-delay.
 *
 * Первый экран листается не окном, а колонкой ленты ([data-vs-feed]), поэтому
 * наблюдаем относительно неё. При «меньше движения» секция видна сразу.
 */

const SHOWN = "vs-in";
const SHARE = 0.15;
/** Доля высоты ленты, которой достаточно высокой секции. */
const TALL_SHARE = 0.25;

export function useReveal<T extends HTMLElement>(): RefCallback<T> {
  return useCallback((node: T | null) => {
    if (!node) return;
    if (typeof IntersectionObserver === "undefined" || prefersReducedMotion()) {
      node.classList.add(SHOWN);
      return;
    }

    let io: IntersectionObserver | null = null;
    let guard: MutationObserver | null = null;

    const show = () => {
      node.removeEventListener("focusin", show);
      io?.disconnect();
      io = null;
      node.classList.add(SHOWN);
      // Класс стоит мимо React: когда секция перерисуется с другим className,
      // React сотрёт его, и секция снова спрячется — уже навсегда. Возвращаем.
      if (typeof MutationObserver === "undefined") return;
      guard = new MutationObserver(() => {
        if (!node.classList.contains(SHOWN)) node.classList.add(SHOWN);
      });
      guard.observe(node, { attributes: true, attributeFilter: ["class"] });
    };

    if (node.classList.contains(SHOWN)) {
      show();
    } else {
      io = new IntersectionObserver(
        (entries) => {
          const hit = entries.some((e) => {
            if (!e.isIntersecting) return false;
            const room = e.rootBounds?.height ?? window.innerHeight;
            return e.intersectionRatio >= SHARE || e.intersectionRect.height >= room * TALL_SHARE;
          });
          if (hit) show();
        },
        // Мелкие ступени в начале — чтобы наблюдатель вообще позвал нас, пока
        // высокая секция набирает свою четверть окна (её доля растёт медленно).
        { root: node.closest("[data-vs-feed]"), threshold: [0, 0.01, 0.02, 0.04, 0.08, SHARE] },
      );
      io.observe(node);
      // С клавиатуры в секцию можно прийти раньше, чем она покажется на свою
      // долю: кнопка у её верхнего края уже на экране, и браузер не листает.
      // Фокус на невидимой кнопке — потерянный фокус, поэтому показываем сразу.
      node.addEventListener("focusin", show);
    }

    return () => {
      node.removeEventListener("focusin", show);
      io?.disconnect();
      guard?.disconnect();
    };
  }, []);
}
