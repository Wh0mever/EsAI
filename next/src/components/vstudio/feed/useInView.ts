"use client";

import { useEffect, useRef, useState, type RefObject } from "react";

/**
 * Виден ли блок на экране.
 *
 * Дубль может сниматься минутами, а лента длинная: «плёнке» и кольцу загрузки
 * незачем крутиться там, куда никто не смотрит. До первого ответа наблюдателя
 * блок считается видимым — иначе заглушка появлялась бы замершей.
 */
export function useInView<T extends HTMLElement>(): [RefObject<T | null>, boolean] {
  const ref = useRef<T | null>(null);
  const [inView, setInView] = useState(true);

  useEffect(() => {
    const node = ref.current;
    if (!node || typeof IntersectionObserver === "undefined") return;
    const io = new IntersectionObserver((entries) => {
      setInView(entries[entries.length - 1].isIntersecting);
    });
    io.observe(node);
    return () => io.disconnect();
  }, []);

  return [ref, inView];
}
