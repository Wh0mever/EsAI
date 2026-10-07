"use client";

import { useRef } from "react";
import type { ReactNode, RefObject } from "react";
import { createPortal } from "react-dom";
import { AnimatePresence, motion } from "framer-motion";
import { useOverlayBehavior, usePortalReady } from "./BottomSheet";
import { useReducedMotion } from "./ui/useAutoplayAllowed";

/**
 * Выдвижная панель сбоку (§9.2, §9.7).
 *
 * Слева — история и «Мои материалы» на планшете и телефоне (кнопка ☰) и
 * развёрнутая левая колонка на ширине 1024–1279. Справа — «Параметры
 * запуска» поверх ленты на ширине 768–1279. Закрывается тапом мимо, Esc и
 * свайпом к краю. Список внутри прокручивается как обычно: drag по оси x
 * сам ставит touch-action: pan-y.
 */
export type MobileDrawerProps = {
  open: boolean;
  onClose: () => void;
  side?: "left" | "right";
  /** Подпись панели для экранного диктора. */
  ariaLabel: string;
  children: ReactNode;
  /** Ширина: CSS-значение. По умолчанию min(86vw, 320px). */
  width?: string;
  /** dim — затемнить ленту; clear — прозрачный фон (панель параметров поверх ленты). */
  backdrop?: "dim" | "clear";
  initialFocus?: RefObject<HTMLElement | null>;
  className?: string;
  zIndex?: number;
};

export default function MobileDrawer({
  open,
  onClose,
  side = "left",
  ariaLabel,
  children,
  width = "min(86vw, 320px)",
  backdrop = "dim",
  initialFocus,
  className = "",
  zIndex = 1000,
}: MobileDrawerProps) {
  const panelRef = useRef<HTMLElement>(null);
  const portal = usePortalReady();
  // «Меньше движения»: панель появляется сразу, без выезда.
  const reduced = useReducedMotion();
  useOverlayBehavior(open, onClose, panelRef, { initialFocus });
  if (!portal) return null;

  const left = side === "left";
  const hidden = left ? "-100%" : "100%";

  return createPortal(
    <AnimatePresence>
      {open && (
        <div key={`vs-drawer-${side}`} className="fixed inset-0" style={{ zIndex }} role="presentation">
          <motion.div
            className="absolute inset-0"
            style={{ background: backdrop === "dim" ? "var(--overlay)" : "transparent" }}
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            transition={{ duration: reduced ? 0 : 0.18 }}
            onClick={onClose}
            aria-hidden="true"
          />
          <motion.aside
            ref={panelRef}
            role="dialog"
            aria-modal="true"
            aria-label={ariaLabel}
            tabIndex={-1}
            // Стекло с одной светлой кромкой — со стороны ленты. Тяжёлую тень
            // заменяет мягкая: панель параметров открывается без затемнения,
            // и чёрная полоса вдоль неё резала бы кадры. Над затемнённой лентой
            // размытие не видно, а слабый телефон двигает такую панель рывками —
            // там оно снято, а стекло взято непрозрачное (vs-solid): иначе сквозь него
            // проступал бы текст страницы; без затемнения размытие нужно по той же причине.
            className={
              (backdrop === "dim" ? "vs-solid " : "vs-glass ") +
              "absolute inset-y-0 flex flex-col text-foreground outline-none !border-y-0 !shadow-[0_0_44px_rgba(0,0,0,0.5)] " +
              (left ? "left-0 rounded-r-[24px] !border-l-0 " : "right-0 rounded-l-[24px] !border-r-0 ") +
              className
            }
            style={{
              width,
              // Вырезы экрана: панель от края до края, содержимое — внутри безопасной зоны.
              paddingTop: "env(safe-area-inset-top, 0px)",
              paddingBottom: "env(safe-area-inset-bottom, 0px)",
            }}
            initial={{ x: hidden }}
            animate={{ x: 0 }}
            exit={{ x: hidden }}
            transition={{ type: "tween", duration: reduced ? 0 : 0.26, ease: "easeOut" }}
            drag="x"
            dragConstraints={{ left: 0, right: 0 }}
            dragElastic={left ? { left: 0.6, right: 0 } : { left: 0, right: 0.6 }}
            dragSnapToOrigin
            onDragEnd={(_e, info) => {
              const toEdge = left ? -info.offset.x : info.offset.x;
              const speed = left ? -info.velocity.x : info.velocity.x;
              if (toEdge > 70 || speed > 500) onClose();
            }}
          >
            {children}
          </motion.aside>
        </div>
      )}
    </AnimatePresence>,
    document.body,
  );
}
