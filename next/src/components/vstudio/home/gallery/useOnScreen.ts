"use client";

import { useCallback, useState } from "react";
import type { RefCallback } from "react";

/**
 * Виден ли блок хоть краем. Нужен заглушкам галереи: «плёнка» (vs-film)
 * проявляется, только пока её видно, — за экраном анимации не место.
 */
export function useOnScreen<T extends Element>(): [RefCallback<T>, boolean] {
  const [seen, setSeen] = useState(false);
  const ref = useCallback((node: T | null) => {
    if (!node) return;
    // Без IntersectionObserver считаем блок видимым: лучше лишнее движение, чем мёртвая заглушка.
    if (typeof IntersectionObserver === "undefined") {
      setSeen(true);
      return;
    }
    const io = new IntersectionObserver((entries) => setSeen(entries[entries.length - 1].isIntersecting));
    io.observe(node);
    return () => io.disconnect();
  }, []);
  return [ref, seen];
}
