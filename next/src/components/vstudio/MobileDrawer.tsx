"use client";

import { useRef } from "react";
import type { ReactNode, RefObject } from "react";
import { createPortal } from "react-dom";
import { AnimatePresence, motion } from "framer-motion";
import { useOverlayBehavior, usePortalReady } from "./BottomSheet";

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
            transition={{ duration: 0.18 }}
            onClick={onClose}
            aria-hidden="true"
          />
          <motion.aside
            ref={panelRef}
            role="dialog"
            aria-modal="true"
            aria-label={ariaLabel}
            tabIndex={-1}
            className={
              "absolute inset-y-0 flex flex-col bg-surface text-foreground shadow-2xl outline-none " +
              (left ? "left-0 border-r border-border " : "right-0 border-l border-border ") +
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
            transition={{ type: "tween", duration: 0.26, ease: "easeOut" }}
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
