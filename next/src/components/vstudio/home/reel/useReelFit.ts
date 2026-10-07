"use client";

import { useCallback, useState } from "react";
import type { RefCallback } from "react";
import { REEL_FOOT, fitWidth } from "./reelMath";

/**
 * Ширина кадра карусели по месту (правила — в fitWidth).
 *
 * Меряем блок карусели: его ширина — это ширина центральной колонки, а его
 * верх внутри ленты говорит, сколько места осталось до панели запроса.
 * Первый замер идёт прямо при появлении блока, до отрисовки, — заглушки и
 * кадры сразу встают в свой размер и не прыгают.
 *
 * Пересчитываем, когда меняется ширина колонки или окно. За панелью запроса
 * не следим намеренно: она растёт, пока человек печатает, и карусель,
 * сжимающаяся с каждой новой строкой запроса, мешала бы больше, чем кадр,
 * слегка ушедший под панель. По той же причине не откликаемся на экранную
 * клавиатуру планшета: она меняет только высоту окна, пока фокус в поле ввода.
 *
 * На блоке не должно быть transform (появление vs-reveal — на вложенном
 * элементе): иначе его верх на время анимации измерился бы со сдвигом.
 */
function keyboardUp(): boolean {
  const el = document.activeElement;
  const typing =
    el instanceof HTMLElement && (el.isContentEditable || el.tagName === "TEXTAREA" || el.tagName === "INPUT");
  return typing && typeof window.matchMedia === "function" && window.matchMedia("(pointer: coarse)").matches;
}

export function useReelFit<T extends HTMLElement>(): { frame: RefCallback<T>; width: number | null } {
  const [width, setWidth] = useState<number | null>(null);

  const frame = useCallback((el: T | null) => {
    if (!el) return;
    let column = -1;
    let viewport = -1;
    const measure = () => {
      column = el.clientWidth;
      viewport = window.innerWidth;
      const feed = el.closest<HTMLElement>("[data-vs-feed]");
      // Верх блока в содержимом ленты — от прокрутки не зависит.
      const top = feed ? el.getBoundingClientRect().top - feed.getBoundingClientRect().top + feed.scrollTop : 0;
      const room = feed ? feed.clientHeight - top - REEL_FOOT : null;
      setWidth(fitWidth(viewport, column, room));
    };
    measure();
    // Высота блока меняется вместе с самим кадром — на неё не откликаемся, только на ширину.
    const ro =
      typeof ResizeObserver === "undefined"
        ? null
        : new ResizeObserver(() => {
            if (el.clientWidth !== column) measure();
          });
    ro?.observe(el);
    const onResize = () => {
      if (window.innerWidth === viewport && keyboardUp()) return;
      measure();
    };
    window.addEventListener("resize", onResize);
    return () => {
      ro?.disconnect();
      window.removeEventListener("resize", onResize);
    };
  }, []);

  return { frame, width };
}
