"use client";

/**
 * Видеостудия, композер: всплывающее окошко у кнопки (меню чипа, раскладка
 * цены, «Создать картинку» на компьютере).
 *
 * Рисуется порталом в body с position: fixed по прямоугольнику якоря: лоток —
 * это полоса с горизонтальной прокруткой, и обычный absolute внутри неё
 * обрезался бы. Открывается над якорем (композер прилип к низу), не вылезает
 * за край окна; Esc и клик мимо закрывают, фокус возвращается на якорь.
 */
import { useEffect, useLayoutEffect, useRef, useState, type ReactNode, type RefObject } from "react";
import { createPortal } from "react-dom";

export type PopoverPlacement = "top-start" | "top-end" | "top-center";

export type AnchoredPopoverProps = {
  anchor: RefObject<HTMLElement | null>;
  open: boolean;
  onClose: () => void;
  placement?: PopoverPlacement;
  children: ReactNode;
  className?: string;
  /** role окошка: menu, dialog или tooltip-подобное region. */
  role?: "menu" | "dialog" | "region";
  ariaLabel?: string;
  /** Поставить фокус внутрь при открытии (меню, форма). */
  autoFocus?: boolean;
  /** Не закрывать по клику внутри этих элементов (кроме якоря). */
  ignore?: Array<RefObject<HTMLElement | null>>;
  zIndex?: number;
};

type Pos = { left: number; top: number; maxHeight: number };

const GAP = 8;
const EDGE = 8;

/** Место над якорем: не за краем окна и не выше видимой части (клавиатура телефона). */
function measure(a: HTMLElement, box: HTMLElement, placement: PopoverPlacement): Pos {
  const r = a.getBoundingClientRect();
  const vw = window.innerWidth;
  const vv = window.visualViewport;
  const viewTop = vv ? vv.offsetTop : 0;
  const w = box.offsetWidth;
  const h = box.offsetHeight;
  let left = placement === "top-end" ? r.right - w : placement === "top-center" ? r.left + r.width / 2 - w / 2 : r.left;
  left = Math.max(EDGE, Math.min(left, vw - w - EDGE));
  const spaceAbove = r.top - viewTop - GAP - EDGE;
  const top = Math.max(viewTop + EDGE, r.top - GAP - Math.min(h, Math.max(spaceAbove, 120)));
  return { left: Math.round(left), top: Math.round(top), maxHeight: Math.max(120, Math.round(spaceAbove)) };
}

export default function AnchoredPopover({
  anchor,
  open,
  onClose,
  placement = "top-start",
  children,
  className = "",
  role = "dialog",
  ariaLabel,
  autoFocus = false,
  ignore,
  zIndex = 1040,
}: AnchoredPopoverProps) {
  const boxRef = useRef<HTMLDivElement | null>(null);
  const [pos, setPos] = useState<Pos | null>(null);
  const onCloseRef = useRef(onClose);
  useLayoutEffect(() => {
    onCloseRef.current = onClose;
  });

  // Функция замера живёт в ref: слушатели окна и ResizeObserver зовут её свежей.
  const placeRef = useRef<() => void>(() => undefined);
  useLayoutEffect(() => {
    placeRef.current = () => {
      const a = anchor.current;
      const box = boxRef.current;
      if (!a || !box) return;
      const next = measure(a, box, placement);
      setPos((p) => (p && p.left === next.left && p.top === next.top && p.maxHeight === next.maxHeight ? p : next));
    };
  });

  useLayoutEffect(() => {
    if (!open) return;
    placeRef.current();
    // Содержимое выросло (раскрыли поле роли) — пересчитать место.
    const box = boxRef.current;
    if (!box || typeof ResizeObserver === "undefined") return;
    const ro = new ResizeObserver(() => placeRef.current());
    ro.observe(box);
    return () => ro.disconnect();
  }, [open]);

  useEffect(() => {
    if (!open) return;
    const onResize = () => placeRef.current();
    const onDown = (e: PointerEvent) => {
      const target = e.target as Node | null;
      if (!target) return;
      if (boxRef.current?.contains(target) || anchor.current?.contains(target)) return;
      if (ignore?.some((r) => r.current?.contains(target))) return;
      onCloseRef.current();
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== "Escape" || e.defaultPrevented) return;
      e.preventDefault();
      onCloseRef.current();
      anchor.current?.focus?.();
    };
    window.addEventListener("resize", onResize);
    window.visualViewport?.addEventListener("resize", onResize);
    // Прокрутка ленты или лотка — окошко едет за якорем.
    window.addEventListener("scroll", onResize, true);
    document.addEventListener("pointerdown", onDown, true);
    document.addEventListener("keydown", onKey);
    return () => {
      window.removeEventListener("resize", onResize);
      window.visualViewport?.removeEventListener("resize", onResize);
      window.removeEventListener("scroll", onResize, true);
      document.removeEventListener("pointerdown", onDown, true);
      document.removeEventListener("keydown", onKey);
    };
  }, [open, anchor, ignore]);

  useEffect(() => {
    if (!open || !autoFocus) return;
    const id = requestAnimationFrame(() => {
      // Сначала поле ввода (роль, описание картинки), потом пункт меню — не «×» в шапке.
      const box = boxRef.current;
      const el =
        box?.querySelector<HTMLElement>("input:not([type=hidden]), textarea") ??
        box?.querySelector<HTMLElement>("[role=menuitem], button:not([disabled]), [tabindex]:not([tabindex='-1'])");
      el?.focus();
    });
    return () => cancelAnimationFrame(id);
  }, [open, autoFocus]);

  if (!open || typeof document === "undefined") return null;
  return createPortal(
    <div
      ref={boxRef}
      role={role}
      aria-label={ariaLabel}
      className={
        "fixed flex flex-col overflow-y-auto overscroll-contain rounded-xl border border-border bg-surface text-foreground shadow-2xl " +
        className
      }
      style={{
        zIndex,
        left: pos?.left ?? -9999,
        top: pos?.top ?? -9999,
        maxHeight: pos?.maxHeight,
        visibility: pos ? "visible" : "hidden",
      }}
    >
      {children}
    </div>,
    document.body,
  );
}
