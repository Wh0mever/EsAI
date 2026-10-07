"use client";

import { useCallback, useEffect, useRef, useState } from "react";

/**
 * Сменили вкладку на более короткую — страница не должна прыгнуть.
 *
 * Сетка стала ниже, лента короче, и браузер сам подтянул бы прокрутку:
 * вкладки уехали бы из-под курсора посреди выбора. Поэтому перед сменой
 * запоминаем, сколько блок занимал до нижнего края видимой части ленты, и
 * держим это как минимальную высоту (capture). Дальше края не держим: под
 * ним прокрутке ничего не грозит, а пустота длиной в двадцать рядов прежней
 * вкладки была бы хуже прыжка.
 *
 * Запас снимается сам, когда этого никто не увидит: содержимое доросло до
 * него или пустое место целиком ушло под нижний край ленты — тогда его
 * исчезновение ничего не сдвигает на экране.
 *
 *   <div ref={boxRef} style={{ minHeight }}>
 *     <div ref={contentRef}>…сетка и «Показать ещё»…</div>
 *   </div>
 */

// Первый экран листается не окном, а колонкой ленты.
const FEED_SELECTOR = "[data-vs-feed]";

/** Нижний край видимой части ленты, в координатах окна. */
const visibleBottom = (scroller: HTMLElement | null) =>
  scroller ? scroller.getBoundingClientRect().bottom : window.innerHeight;

export function useHeightHold() {
  const boxRef = useRef<HTMLDivElement>(null);
  const contentRef = useRef<HTMLDivElement>(null);
  const [held, setHeld] = useState<number | null>(null);

  /** Зовётся в обработчике, до смены содержимого. Прежний запас входит в высоту блока, так что он не уменьшится. */
  const capture = useCallback(() => {
    const box = boxRef.current;
    if (!box) return;
    const reach = visibleBottom(box.closest<HTMLElement>(FEED_SELECTOR)) - box.getBoundingClientRect().top;
    const height = Math.min(box.offsetHeight, Math.ceil(reach));
    setHeld(height > 0 ? height : null);
  }, []);

  useEffect(() => {
    if (held === null) return;
    const box = boxRef.current;
    const content = contentRef.current;
    if (!box || !content) return;
    const scroller = box.closest<HTMLElement>(FEED_SELECTOR);
    let frame = 0;
    const check = () => {
      frame = 0;
      if (content.offsetHeight >= held || content.getBoundingClientRect().bottom >= visibleBottom(scroller)) {
        setHeld(null);
      }
    };
    const queue = () => {
      if (!frame) frame = requestAnimationFrame(check);
    };
    // Ширина изменилась — карточки другой высоты, запомненное число уже ни о чём.
    // Высота окна меняется и сама (клавиатура телефона) — на неё не смотрим.
    const width = window.innerWidth;
    const drop = () => {
      if (window.innerWidth !== width) setHeld(null);
    };
    const target: HTMLElement | Window = scroller ?? window;
    target.addEventListener("scroll", queue, { passive: true });
    window.addEventListener("resize", drop);
    queue();
    return () => {
      target.removeEventListener("scroll", queue);
      window.removeEventListener("resize", drop);
      if (frame) cancelAnimationFrame(frame);
    };
  }, [held]);

  return { boxRef, contentRef, minHeight: held ?? undefined, capture };
}
