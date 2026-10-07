"use client";

import { useEffect, useId, useRef, useSyncExternalStore } from "react";
import type { CSSProperties, ReactNode, RefObject } from "react";
import { createPortal } from "react-dom";
import { AnimatePresence, motion, useDragControls } from "framer-motion";
import { FiX } from "react-icons/fi";
import { useTranslation } from "react-i18next";
import { VS_ICON_BTN } from "./ui/skin";
import { useReducedMotion } from "./ui/useAutoplayAllowed";

/**
 * Нижняя шторка студии (§9.7): выбор материалов, параметры, библиотека.
 *
 * Высота считается от видимой части окна, а не от 100vh: экранная клавиатура
 * на телефоне закрывает низ, и обычная шторка уезжала бы под неё. Оболочка
 * пишет в :root переменные --vvh (видимая высота) и --kb (высота клавиатуры)
 * — см. hooks/useVisualViewport; без них работают запасные 100dvh и 0.
 *
 * Закрывается тапом по фону, Esc, крестиком и свайпом вниз за шапку. Фокус
 * уходит в шторку и возвращается туда, откуда её открыли (§9.8).
 */

/* ------------------------------------------------------------------ */
/* Общее поведение шторок (BottomSheet и MobileDrawer)                 */
/* ------------------------------------------------------------------ */

// Открытые шторки по порядку: Esc закрывает только верхнюю.
const stack: string[] = [];
// Сколько шторок держат прокрутку страницы.
let scrollLocks = 0;
let savedOverflow = "";

const FOCUSABLE =
  'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"]), [contenteditable="true"]';

/** Tab не выходит из открытой шторки. */
function trapTab(e: KeyboardEvent, container: HTMLElement | null) {
  if (e.key !== "Tab" || !container) return;
  // inert: свёрнутый блок («Дополнительно») остаётся в раскладке, но фокус не
  // берёт. Счесть его поле последним — Tab с настоящего последнего уйдёт из шторки.
  const items = Array.from(container.querySelectorAll<HTMLElement>(FOCUSABLE)).filter(
    (el) => !el.hasAttribute("disabled") && el.offsetParent !== null && !el.closest("[inert]"),
  );
  if (!items.length) {
    e.preventDefault();
    container.focus();
    return;
  }
  const first = items[0];
  const last = items[items.length - 1];
  const active = document.activeElement as HTMLElement | null;
  // active === container: сразу после открытия фокус стоит на самой шторке.
  if (e.shiftKey && (active === first || active === container || !container.contains(active))) {
    e.preventDefault();
    last.focus();
  } else if (!e.shiftKey && (active === last || !container.contains(active))) {
    e.preventDefault();
    first.focus();
  }
}

/**
 * Поверх шторки открыто чужое модальное окно (подтверждение архива, окно
 * входа, пэйволл — они рисуются порталом в конец body)? Тогда Esc и Tab —
 * его: иначе Esc закрыл бы и окно, и шторку под ним, а ловушка Tab вернула бы
 * фокус из окна обратно в шторку.
 */
function coveredByForeignModal(panel: HTMLElement | null): boolean {
  if (!panel || typeof document === "undefined") return false;
  const modals = document.querySelectorAll<HTMLElement>('[aria-modal="true"]');
  const top = modals[modals.length - 1];
  return Boolean(top && top !== panel && !panel.contains(top) && !top.contains(panel));
}

/**
 * Esc (только верхняя шторка), ловушка Tab, блок прокрутки страницы и возврат
 * фокуса. Используется BottomSheet и MobileDrawer.
 */
export function useOverlayBehavior(
  open: boolean,
  onClose: () => void,
  panelRef: RefObject<HTMLElement | null>,
  opts: { initialFocus?: RefObject<HTMLElement | null>; lockScroll?: boolean; trapFocus?: boolean } = {},
): void {
  const id = useId();
  const onCloseRef = useRef(onClose);
  useEffect(() => {
    onCloseRef.current = onClose;
  }, [onClose]);
  const { initialFocus, lockScroll = true, trapFocus = true } = opts;

  useEffect(() => {
    if (!open) return;
    const previous = document.activeElement as HTMLElement | null;
    stack.push(id);
    if (lockScroll) {
      if (scrollLocks === 0) {
        savedOverflow = document.body.style.overflow;
        document.body.style.overflow = "hidden";
      }
      scrollLocks++;
    }
    // Фокус — после кадра: панель ещё монтируется внутри анимации.
    const frame = window.requestAnimationFrame(() => {
      const target = initialFocus?.current || panelRef.current;
      target?.focus({ preventScroll: true });
    });
    const onKey = (e: KeyboardEvent) => {
      if (stack[stack.length - 1] !== id) return;
      if (coveredByForeignModal(panelRef.current)) return;
      if (e.key === "Escape") {
        e.stopPropagation();
        onCloseRef.current();
        return;
      }
      if (trapFocus) trapTab(e, panelRef.current);
    };
    document.addEventListener("keydown", onKey);
    return () => {
      window.cancelAnimationFrame(frame);
      document.removeEventListener("keydown", onKey);
      const i = stack.lastIndexOf(id);
      if (i >= 0) stack.splice(i, 1);
      if (lockScroll) {
        scrollLocks = Math.max(0, scrollLocks - 1);
        if (scrollLocks === 0) document.body.style.overflow = savedOverflow;
      }
      // Фокус туда, откуда открыли (если элемент ещё на странице).
      if (previous && document.contains(previous)) previous.focus({ preventScroll: true });
    };
  }, [open, id, panelRef, initialFocus, lockScroll, trapFocus]);
}

const noopSubscribe = () => () => {};

/** Портал только в браузере: на сервере и при гидратации — false, без расхождения разметки. */
export function usePortalReady(): boolean {
  return useSyncExternalStore(
    noopSubscribe,
    () => true,
    () => false,
  );
}

/* ------------------------------------------------------------------ */
/* BottomSheet                                                          */
/* ------------------------------------------------------------------ */

export type BottomSheetProps = {
  open: boolean;
  onClose: () => void;
  /** Заголовок в шапке; он же подпись диалога для экранного диктора. */
  title?: ReactNode;
  /** Подпись для диктора, если заголовка нет или он не текст. */
  ariaLabel?: string;
  children: ReactNode;
  /** Прилипший низ шторки (кнопки). */
  footer?: ReactNode;
  /** auto — по содержимому (до видимой высоты); half — около 60 %; full — во всю видимую высоту. */
  size?: "auto" | "half" | "full";
  /** Тап по фону и свайп закрывают шторку (false — например, пока идёт загрузка). */
  dismissible?: boolean;
  showClose?: boolean;
  initialFocus?: RefObject<HTMLElement | null>;
  className?: string;
  bodyClassName?: string;
  /** Выше обычных шторок студии, но ниже окон Modal (z 1100). */
  zIndex?: number;
};

export default function BottomSheet({
  open,
  onClose,
  title,
  ariaLabel,
  children,
  footer,
  size = "auto",
  dismissible = true,
  showClose = true,
  initialFocus,
  className = "",
  bodyClassName = "",
  zIndex = 1000,
}: BottomSheetProps) {
  const { t } = useTranslation("vstudio", { useSuspense: false });
  const panelRef = useRef<HTMLDivElement>(null);
  const titleId = useId();
  const controls = useDragControls();
  const portal = usePortalReady();
  // «Меньше движения»: шторка появляется сразу, без выезда.
  const reduced = useReducedMotion();
  const close = () => {
    if (dismissible) onClose();
  };
  useOverlayBehavior(open, close, panelRef, { initialFocus });

  if (!portal) return null;

  const maxH = "calc(var(--vvh, 100dvh) - 12px)";
  const style: CSSProperties = {
    bottom: "var(--kb, 0px)",
    maxHeight: maxH,
    paddingBottom: "env(safe-area-inset-bottom, 0px)",
    ...(size === "full" ? { height: maxH } : size === "half" ? { height: `min(62dvh, ${maxH})` } : {}),
  };

  return createPortal(
    <AnimatePresence>
      {open && (
        <div key="vs-sheet" className="fixed inset-0" style={{ zIndex }} role="presentation">
          <motion.div
            className="absolute inset-0"
            style={{ background: "var(--overlay)" }}
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            transition={{ duration: reduced ? 0 : 0.18 }}
            onClick={close}
            aria-hidden="true"
          />
          <motion.div
            ref={panelRef}
            role="dialog"
            aria-modal="true"
            aria-labelledby={title ? titleId : undefined}
            aria-label={title ? undefined : ariaLabel}
            tabIndex={-1}
            // Большую панель с backdrop-filter слабый телефон двигает рывками,
            // поэтому шторка без размытия и непрозрачная (vs-solid): сквозь
            // обычное стекло проступал бы текст страницы.
            className={
              "vs-solid absolute inset-x-0 mx-auto flex w-full max-w-[680px] flex-col rounded-t-[24px] !border-b-0 text-foreground outline-none " +
              className
            }
            style={style}
            initial={{ y: "100%" }}
            animate={{ y: 0 }}
            exit={{ y: "100%" }}
            transition={{ type: "tween", duration: reduced ? 0 : 0.24, ease: "easeOut" }}
            drag={dismissible ? "y" : false}
            dragListener={false}
            dragControls={controls}
            dragConstraints={{ top: 0, bottom: 0 }}
            dragElastic={{ top: 0, bottom: 0.6 }}
            dragSnapToOrigin
            onDragEnd={(_e, info) => {
              if (info.offset.y > 90 || info.velocity.y > 500) close();
            }}
          >
            {/* Шапка — ручка свайпа: за неё тянут вниз, список внутри при этом прокручивается как обычно. */}
            <div
              className="shrink-0 touch-none select-none px-4 pt-2"
              onPointerDown={(e) => {
                if (dismissible) controls.start(e);
              }}
            >
              <div className="mx-auto mb-2 h-1 w-10 rounded-full bg-white/20" aria-hidden="true" />
              {(title || showClose) && (
                <div className="flex min-h-11 items-center gap-2 pb-2.5">
                  <div id={titleId} className="vs-display min-w-0 flex-1 truncate py-1 text-[17px] text-foreground">
                    {title}
                  </div>
                  {showClose && (
                    <button
                      type="button"
                      onClick={onClose}
                      onPointerDown={(e) => e.stopPropagation()}
                      className={VS_ICON_BTN}
                      aria-label={t("mobile.close", { defaultValue: "Закрыть" })}
                    >
                      <FiX className="text-lg" aria-hidden="true" />
                    </button>
                  )}
                </div>
              )}
            </div>
            <div className={"min-h-0 flex-1 overflow-y-auto overscroll-contain px-4 pb-4 " + bodyClassName}>{children}</div>
            {footer && <div className="shrink-0 border-t border-white/10 px-4 py-3">{footer}</div>}
          </motion.div>
        </div>
      )}
    </AnimatePresence>,
    document.body,
  );
}
