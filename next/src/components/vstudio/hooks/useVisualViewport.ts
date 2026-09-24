"use client";

import { useEffect, useState } from "react";

/**
 * Видимая часть окна с учётом экранной клавиатуры (§9.7).
 *
 * На телефоне клавиатура не меняет window.innerHeight, а только
 * visualViewport: без поправки нижние шторки (выбор материалов, параметры,
 * библиотека) и прилипший композер уезжают под клавиатуру. Хук отдаёт высоту
 * видимой области и высоту клавиатуры, а с cssVars=true ещё и пишет их в
 * :root как --vvh и --kb — шторки и оболочка берут их прямо в CSS
 * (bottom: var(--kb, 0px); max-height: var(--vvh, 100dvh)).
 */
export type VisualViewportState = {
  /** Высота видимой области, px. */
  height: number;
  width: number;
  /** Сдвиг видимой области от верха страницы (iOS прокручивает её при фокусе поля). */
  offsetTop: number;
  /** Высота экранной клавиатуры (и прочего, что закрыло низ окна), px; 0 — закрыта. */
  keyboard: number;
};

function read(): VisualViewportState | null {
  if (typeof window === "undefined") return null;
  const vv = window.visualViewport;
  const innerH = window.innerHeight || 0;
  if (!vv) return { height: innerH, width: window.innerWidth || 0, offsetTop: 0, keyboard: 0 };
  const height = Math.round(vv.height);
  const offsetTop = Math.round(vv.offsetTop);
  // Меньше 40 px — это не клавиатура, а панель адреса браузера: её не считаем.
  const gap = Math.max(0, Math.round(innerH - vv.height - vv.offsetTop));
  return { height, width: Math.round(vv.width), offsetTop, keyboard: gap < 40 ? 0 : gap };
}

/** Порог «клавиатура открыта»: видимая часть заметно ниже окна. */
export function isKeyboardOpen(v: VisualViewportState | null): boolean {
  return Boolean(v && v.keyboard > 0);
}

export function useVisualViewport(opts: { cssVars?: boolean } = {}): VisualViewportState | null {
  const { cssVars = false } = opts;
  const [state, setState] = useState<VisualViewportState | null>(null);

  useEffect(() => {
    if (typeof window === "undefined") return;
    const root = document.documentElement;
    let frame = 0;
    const apply = () => {
      frame = 0;
      const next = read();
      if (!next) return;
      setState((prev) =>
        prev &&
        prev.height === next.height &&
        prev.width === next.width &&
        prev.offsetTop === next.offsetTop &&
        prev.keyboard === next.keyboard
          ? prev
          : next,
      );
      if (cssVars) {
        root.style.setProperty("--vvh", `${next.height}px`);
        root.style.setProperty("--kb", `${next.keyboard}px`);
      }
    };
    // События resize/scroll у visualViewport идут пачками при каждом кадре
    // анимации клавиатуры — пересчитываем не чаще раза за кадр.
    const schedule = () => {
      if (!frame) frame = window.requestAnimationFrame(apply);
    };
    apply();
    const vv = window.visualViewport;
    vv?.addEventListener("resize", schedule);
    vv?.addEventListener("scroll", schedule);
    window.addEventListener("resize", schedule);
    window.addEventListener("orientationchange", schedule);
    return () => {
      if (frame) window.cancelAnimationFrame(frame);
      vv?.removeEventListener("resize", schedule);
      vv?.removeEventListener("scroll", schedule);
      window.removeEventListener("resize", schedule);
      window.removeEventListener("orientationchange", schedule);
      if (cssVars) {
        root.style.removeProperty("--vvh");
        root.style.removeProperty("--kb");
      }
    };
  }, [cssVars]);

  return state;
}
