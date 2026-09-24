/**
 * Ближайший прокручиваемый предок ленты. Нужен IntersectionObserver'ам
 * («показать раньше», ленивый плеер): внутри колонки с overflow-y наблюдатель
 * с root=null не видит rootMargin — всё, что за краем колонки, для него
 * обрезано, и подгрузка начиналась бы только у самого края.
 */
export function scrollParentOf(node: Element | null | undefined): HTMLElement | null {
  let el = node?.parentElement || null;
  while (el && el !== document.body && el !== document.documentElement) {
    const oy = getComputedStyle(el).overflowY;
    if (oy === "auto" || oy === "scroll" || oy === "overlay") return el;
    el = el.parentElement;
  }
  return null;
}

/** Прокручиваемый ли сам элемент (контейнер ленты из контекста студии). */
export function isScrollable(el: Element | null | undefined): el is HTMLElement {
  if (!el) return false;
  const oy = getComputedStyle(el).overflowY;
  return oy === "auto" || oy === "scroll" || oy === "overlay";
}
