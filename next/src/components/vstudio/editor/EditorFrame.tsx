"use client";

/**
 * Видеостудия, редактор промпта: рамка поля — кнопка ⤢, полноэкранный режим
 * (§4.8: править вставленные 3000+ символов), строка подсказок под полем.
 *
 * Полноэкранный режим не пересоздаёт редактор: содержимое рендерится порталом
 * в один и тот же «носитель», а носитель физически переносится между местом в
 * композере и оверлеем. Так курсор, история правок и композиция IME не
 * теряются, а оверлей не зависит от transform/backdrop-filter у предков
 * композера (они ломают position: fixed).
 */
import { useCallback, useEffect, useLayoutEffect, useRef, useState, type MutableRefObject, type ReactNode } from "react";
import { createPortal } from "react-dom";
import { useTranslation } from "react-i18next";
import { IoContractOutline, IoExpandOutline } from "react-icons/io5";
import { VS_FOCUS } from "../ui/skin";

type Box = { top: number; height: number };

/** Видимая часть окна (над клавиатурой телефона). */
function useViewportBox(active: boolean): Box | null {
  const [box, setBox] = useState<Box | null>(null);
  useEffect(() => {
    if (!active || typeof window === "undefined") return;
    const vv = window.visualViewport;
    const read = () =>
      setBox(vv ? { top: Math.round(vv.offsetTop), height: Math.round(vv.height) } : { top: 0, height: window.innerHeight });
    read();
    vv?.addEventListener("resize", read);
    vv?.addEventListener("scroll", read);
    window.addEventListener("resize", read);
    return () => {
      vv?.removeEventListener("resize", read);
      vv?.removeEventListener("scroll", read);
      window.removeEventListener("resize", read);
    };
  }, [active]);
  return active ? box : null;
}

export type EditorFrameProps = {
  fullscreen: boolean;
  onFullscreenChange: (open: boolean) => void;
  /** Строка под полем (почему вставка не прошла и т. п.). */
  notice?: string | null;
  /** Счётчик символов появляется ближе к пределу. */
  chars?: number;
  max?: number;
  /** Носитель содержимого (он переезжает в оверлей и обратно) — «внутри редактора» для кликов. */
  hostRef?: MutableRefObject<HTMLDivElement | null>;
  /** После переезда в оверлей и обратно — вернуть фокус в поле. */
  onMoved?: () => void;
  className?: string;
  children: ReactNode;
};

export default function EditorFrame({
  fullscreen,
  onFullscreenChange,
  notice,
  chars = 0,
  max = 0,
  hostRef,
  onMoved,
  className = "",
  children,
}: EditorFrameProps) {
  const { t } = useTranslation("vstudio", { useSuspense: false });
  const tx = (key: string, ru: string, opts?: Record<string, unknown>) => String(t(key, { defaultValue: ru, ...(opts || {}) }));
  const [host] = useState<HTMLDivElement | null>(() => {
    if (typeof document === "undefined") return null;
    const el = document.createElement("div");
    el.className = "vs-editor-host flex min-h-0 flex-1 flex-col";
    return el;
  });
  const inlineSlot = useRef<HTMLDivElement | null>(null);
  const placed = useRef(false);
  const box = useViewportBox(fullscreen);
  const onMovedRef = useRef(onMoved);
  useLayoutEffect(() => {
    onMovedRef.current = onMoved;
  });

  useLayoutEffect(() => {
    if (hostRef) hostRef.current = host;
  }, [host, hostRef]);

  // Носитель — туда, где сейчас поле: в композер или в оверлей. Перенос
  // снимает фокус (элемент на миг выходит из документа) — возвращаем его.
  const moveHost = useCallback(
    (target: HTMLElement | null) => {
      if (!host || !target || host.parentNode === target) return;
      target.appendChild(host);
      if (placed.current) onMovedRef.current?.();
      placed.current = true;
    },
    [host],
  );
  const fullSlotRef = useCallback((el: HTMLDivElement | null) => moveHost(el), [moveHost]);

  useLayoutEffect(() => {
    if (!fullscreen) moveHost(inlineSlot.current);
  }, [fullscreen, moveHost]);

  useEffect(() => {
    if (!fullscreen) return;
    // Esc закрывает полноэкранный режим, если его не забрал редактор (список «@»).
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape" && !e.defaultPrevented) onFullscreenChange(false);
    };
    document.addEventListener("keydown", onKey);
    const prev = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.removeEventListener("keydown", onKey);
      document.body.style.overflow = prev;
    };
  }, [fullscreen, onFullscreenChange]);

  // Носитель уезжает из DOM вместе с рамкой — вернём его, чтобы портал не остался висеть.
  useEffect(
    () => () => {
      host?.remove();
    },
    [host],
  );

  const nearLimit = max > 0 && chars >= max * 0.9;
  const fmt = (n: number) => n.toLocaleString("ru-RU");
  const footer =
    notice || nearLimit ? (
      <div className="flex items-start justify-between gap-3 px-1.5 pb-1 text-xs" aria-live="polite">
        <span className={notice ? "text-status-fail" : ""}>{notice || ""}</span>
        {nearLimit && (
          <span className={`shrink-0 tabular-nums ${chars >= max ? "text-status-fail" : "text-status-wait"}`}>
            {fmt(chars)} / {fmt(max)}
          </span>
        )}
      </div>
    ) : null;

  const expandLabel = tx("composer.expand", "Развернуть");
  const collapseLabel = tx("composer.collapse", "Свернуть");

  return (
    <>
      <div className={`relative flex min-w-0 flex-col ${className}`}>
        <div ref={inlineSlot} className="flex min-h-0 min-w-0 flex-col" />
        {!fullscreen && (
          <button
            type="button"
            onMouseDown={(e) => e.preventDefault()}
            onClick={() => onFullscreenChange(true)}
            className={`absolute right-0 top-0 grid size-9 cursor-pointer place-items-center rounded-full text-base text-muted-2 transition-colors hover:bg-white/[0.08] hover:text-foreground max-md:size-11 ${VS_FOCUS}`}
            aria-label={expandLabel}
            title={expandLabel}
          >
            <IoExpandOutline aria-hidden />
          </button>
        )}
        {!fullscreen && footer}
      </div>
      {fullscreen &&
        typeof document !== "undefined" &&
        createPortal(
          <div
            role="dialog"
            aria-modal="true"
            aria-label={tx("composer.fullscreen", "Текст запроса")}
            className="fixed inset-x-0 z-[950] flex flex-col bg-surface"
            style={box ? { top: box.top, height: box.height } : { top: 0, bottom: 0 }}
          >
            <div className="flex items-center justify-between gap-2 border-b border-white/10 py-1.5 pl-4 pr-2 pt-[max(0.375rem,env(safe-area-inset-top))]">
              <span className="truncate text-xs text-muted-2">
                {tx("composer.shortcut", "Ctrl/⌘ + Enter — создать")}
              </span>
              <button
                type="button"
                onMouseDown={(e) => e.preventDefault()}
                onClick={() => onFullscreenChange(false)}
                className={`flex h-11 cursor-pointer items-center gap-1.5 rounded-full px-3 text-sm text-muted transition-colors hover:bg-white/[0.08] hover:text-foreground ${VS_FOCUS}`}
                aria-label={collapseLabel}
              >
                <IoContractOutline aria-hidden className="text-base" />
                <span className="max-sm:hidden">{collapseLabel}</span>
              </button>
            </div>
            {/* Во весь экран поля у текста свои: в панели запроса их даёт сама панель. */}
            <div ref={fullSlotRef} className="mx-auto flex min-h-0 w-full max-w-3xl flex-1 flex-col px-2.5 pt-2 sm:px-4" />
            <div className="mx-auto w-full max-w-3xl px-2.5 pb-[env(safe-area-inset-bottom)] sm:px-4">{footer}</div>
          </div>,
          document.body,
        )}
      {host && createPortal(children, host)}
    </>
  );
}
