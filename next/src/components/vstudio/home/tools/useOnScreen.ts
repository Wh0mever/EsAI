"use client";

import { useEffect, useState } from "react";

/**
 * Виден ли блок хоть краем. Нужен заглушкам «плёнка проявляется»: бегущий блик
 * за пределами экрана только греет телефон.
 *
 *   const [watch, seen] = useOnScreen<HTMLUListElement>();
 *   <ul ref={watch}> … className={seen ? "vs-film" : "bg-surface-2"}
 */
export function useOnScreen<T extends Element>(): [(node: T | null) => void, boolean] {
  const [node, setNode] = useState<T | null>(null);
  // Без IntersectionObserver считаем блок видимым: лучше лишний блик, чем мёртвая заглушка.
  const [seen, setSeen] = useState(() => typeof IntersectionObserver === "undefined");

  useEffect(() => {
    if (!node || typeof IntersectionObserver === "undefined") return;
    const io = new IntersectionObserver((entries) => setSeen(entries[entries.length - 1].isIntersecting));
    io.observe(node);
    return () => io.disconnect();
  }, [node]);

  return [setNode, seen];
}
