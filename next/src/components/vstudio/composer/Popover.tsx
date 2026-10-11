"use client";

/**
 * Видеостудия, композер: всплывающее окошко у кнопки (меню чипа, раскладка
 * цены, «Создать картинку» на компьютере).
 *
 * Рисуется порталом в body с position: fixed по прямоугольнику якоря: лоток —
 * это полоса с горизонтальной прокруткой, и обычный absolute внутри неё
 * обрезался бы. Открывается над якорем (композер прилип к низу), не вылезает
 * за край окна; Esc и клик мимо закрывают, фокус возвращается на якорь. Tab
 * за край окошка закрывает его там, где это просили (closeOnTabOut).
 */
import { useEffect, useLayoutEffect, useRef, useState, type ReactNode, type RefObject } from "react";
import { createPortal } from "react-dom";
import { useDockHold } from "./dockHold";

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
  /**
   * Tab с последнего элемента (Shift+Tab с первого) закрывает окошко и возвращает фокус на якорь.
   * Только для окошек с якорем-кнопкой и без несохранённого ввода: форма «Создать картинку»
   * привязана к коробке композера, и там закрытие по Tab стёрло бы набранное описание.
   */
  closeOnTabOut?: boolean;
  zIndex?: number;
};

type Pos = { left: number; top: number; maxHeight: number };

const GAP = 8;
const EDGE = 8;

/** Куда внутри окошка приходит Tab. Выключенные значения (длительность под замком) — мимо. */
const TAB_STOPS =
  "button:not([disabled]), a[href], input:not([disabled]):not([type=hidden]), select:not([disabled]), textarea:not([disabled]), [tabindex]";

function tabStops(box: HTMLElement): HTMLElement[] {
  return Array.from(box.querySelectorAll<HTMLElement>(TAB_STOPS)).filter(
    (el) => el.tabIndex >= 0 && !el.closest("[inert]") && el.getClientRects().length > 0,
  );
}

/** Появление: окошко чуть поднимается к якорю. Без движения — сразу на месте. */
const POPOVER_CSS = `
@keyframes vs-pop-in { from { opacity: 0; transform: translateY(6px) scale(0.985); } }
`;

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
  closeOnTabOut = false,
  zIndex = 1040,
}: AnchoredPopoverProps) {
  const boxRef = useRef<HTMLDivElement | null>(null);
  const [pos, setPos] = useState<Pos | null>(null);
  const onCloseRef = useRef(onClose);
  useLayoutEffect(() => {
    onCloseRef.current = onClose;
  });
  // Окошко стоит у своего якоря в панели: пока оно открыто, поле запроса не сворачивается — панель под ним не едет.
  useDockHold(open);

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
      if (e.defaultPrevented) return;
      if (e.key === "Tab" && closeOnTabOut) {
        // Окошко стоит порталом в конце body: без этого Tab с последнего значения уводил фокус
        // из страницы, а окошко так и висело над панелью открытым.
        if (e.ctrlKey || e.altKey || e.metaKey) return;
        const box = boxRef.current;
        const at = document.activeElement;
        if (!box || !at || !box.contains(at)) return;
        const stops = tabStops(box);
        if (stops.length && at !== (e.shiftKey ? stops[0] : stops[stops.length - 1])) return;
      } else if (e.key !== "Escape") {
        return;
      }
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
  }, [open, anchor, ignore, closeOnTabOut]);

  useEffect(() => {
    if (!open || !autoFocus) return;
    const id = requestAnimationFrame(() => {
      // Сначала поле ввода (роль, описание картинки), потом выбранное значение
      // (модель, пропорция), потом пункт меню — не «×» в шапке.
      const box = boxRef.current;
      const el =
        box?.querySelector<HTMLElement>("input:not([type=hidden]), textarea") ??
        box?.querySelector<HTMLElement>("button[aria-pressed='true']:not([disabled])") ??
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
        "vs-glass fixed flex origin-bottom animate-[vs-pop-in_180ms_cubic-bezier(0.16,1,0.3,1)] flex-col overflow-y-auto overscroll-contain rounded-2xl text-foreground motion-reduce:animate-none " +
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
      <style href="vs-popover" precedence="default">
        {POPOVER_CSS}
      </style>
      {children}
    </div>,
    document.body,
  );
}
