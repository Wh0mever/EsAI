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
import { IoChevronDown, IoChevronUp, IoContractOutline, IoExpandOutline } from "react-icons/io5";
import { VS_FOCUS } from "../ui/skin";
import type { PromptFoldProps } from "./editorTypes";

type Box = { top: number; height: number };

/** Кнопка в правом поле текста: ⤢ и «свернуть / показать весь запрос». */
const GUTTER_BTN = `pointer-events-auto grid size-9 shrink-0 cursor-pointer place-items-center rounded-full text-base transition-colors hover:bg-vs-ink/[0.08] hover:text-foreground max-md:size-11 ${VS_FOCUS}`;

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
  /** Свёрнутый вид поля: кнопка у нижнего края. foldId — id блока, который она сворачивает. */
  fold?: PromptFoldProps;
  foldId?: string;
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
  fold,
  foldId,
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
  const foldShowLabel = tx("composer.foldShow", "Показать весь запрос");
  const foldHideLabel = tx("composer.foldHide", "Свернуть запрос");
  // Кнопка есть, только когда тексту есть что прятать: короткий запрос её не видит.
  const folding = Boolean(fold?.cut);
  const compact = folding && Boolean(fold?.compact);
  const foldLabel = compact ? foldShowLabel : foldHideLabel;

  return (
    <>
      <div className={`relative flex min-w-0 flex-col ${className}`}>
        <div className="relative flex min-w-0 flex-col">
          <div ref={inlineSlot} className="flex min-h-0 min-w-0 flex-col" />
          {!fullscreen && (
            // Правое поле текста. ⤢ — у верхнего края, кнопка сворачивания — у нижнего: панель прижата
            // к низу окна, и нижний край поля стоит на месте при любой его высоте — кнопка не уезжает
            // из-под указателя. Пока двум кнопкам тесно (первые кадры разворота, поле, зажатое
            // клавиатурой телефона), одну из них прячет vs-fold-rail (globals.css): кнопка под
            // указателем не должна мигать. Перенос колонки — запас для браузеров без @container: лишняя
            // кнопка уходит во вторую колонку, а та обрезана. Поля в 4 px — под кольцо фокуса; сама
            // колонка нажатий не ловит, клик в правое поле текста по-прежнему ставит курсор.
            // С 768 px колонка отступает от края на ширину полосы прокрутки (8 px): у длинного запроса
            // полоса есть всегда, и кнопка поверх её нижнего конца сворачивала бы поле вместо прокрутки.
            // На телефоне полоса рисуется поверх текста и нажатий не ловит — там кнопки у самого края.
            <div className="vs-fold-rail pointer-events-none absolute -inset-y-1 right-1 flex w-11 flex-col flex-wrap content-start gap-x-2 overflow-hidden p-1 max-md:-right-1 max-md:w-[3.25rem]">
              {/* В свёрнутом поле место одно, и оно — кнопке «Показать весь запрос». */}
              {!compact && (
                <button
                  type="button"
                  onMouseDown={(e) => e.preventDefault()}
                  onClick={() => onFullscreenChange(true)}
                  className={`${GUTTER_BTN} vs-fold-zoom text-muted-2`}
                  aria-label={expandLabel}
                  title={expandLabel}
                >
                  <IoExpandOutline aria-hidden />
                </button>
              )}
              {folding && fold && (
                <button
                  type="button"
                  onClick={fold.onToggle}
                  className={`${GUTTER_BTN} mt-auto ${compact ? "text-muted" : "text-muted-2"}`}
                  aria-expanded={!compact}
                  aria-controls={foldId}
                  aria-label={foldLabel}
                  title={foldLabel}
                >
                  {compact ? <IoChevronDown aria-hidden /> : <IoChevronUp aria-hidden />}
                </button>
              )}
            </div>
          )}
        </div>
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
            <div className="flex items-center justify-between gap-2 border-b border-vs-ink/10 py-1.5 pl-4 pr-2 pt-[max(0.375rem,env(safe-area-inset-top))]">
              <span className="truncate text-xs text-muted-2">
                {tx("composer.shortcut", "Ctrl/⌘ + Enter — создать")}
              </span>
              <button
                type="button"
                onMouseDown={(e) => e.preventDefault()}
                onClick={() => onFullscreenChange(false)}
                className={`flex h-11 cursor-pointer items-center gap-1.5 rounded-full px-3 text-sm text-muted transition-colors hover:bg-vs-ink/[0.08] hover:text-foreground ${VS_FOCUS}`}
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
