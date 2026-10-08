"use client";

import { useEffect, useRef, useState } from "react";
import type { KeyboardEvent } from "react";
import { FiChevronLeft, FiChevronRight } from "react-icons/fi";
import { VS_FOCUS, VS_PILL, VS_PILL_ON, vx } from "../../ui/skin";
import { prefersReducedMotion } from "../../ui/useAutoplayAllowed";

/**
 * Вкладки галереи — лента в одну строку.
 *
 * Это настоящий tablist: Tab приводит на выбранную вкладку, дальше ← → Home
 * End — вкладка выбирается сразу, сетка под ней (tabpanel) меняется. Так
 * десять разделов не превращаются в десять остановок Tab на пути к карточкам.
 *
 * Лента шире экрана листается пальцем; колесом мыши вбок её не прокрутить,
 * поэтому там, где есть курсор, у краёв появляются стрелки. Край затухает
 * только с той стороны, где за ним ещё есть вкладки: первая вкладка не должна
 * стоять полупрозрачной.
 */

export type GalleryTabView = { id: string; title: string };

export type GalleryTabsProps = {
  tabs: GalleryTabView[];
  active: string;
  onSelect: (id: string) => void;
  /** Общая часть id вкладок: по ней панель с сеткой ссылается на выбранную (tabDomId). */
  idBase: string;
  panelId: string;
  /** Подпись группы для скринридера. */
  label: string;
  /** У устройства есть курсор — нужны стрелки прокрутки. */
  arrows: boolean;
  prevLabel: string;
  nextLabel: string;
  className?: string;
};

export const tabDomId = (idBase: string, index: number) => `${idBase}-tab-${index}`;

// Те же 28 px, что у vs-fade-x, но с одной стороны. black здесь — непрозрачность маски, а не цвет: от темы не зависит.
const FADE_START =
  "[-webkit-mask-image:linear-gradient(90deg,transparent,black_28px)] [mask-image:linear-gradient(90deg,transparent,black_28px)]";
const FADE_END =
  "[-webkit-mask-image:linear-gradient(90deg,black_calc(100%-28px),transparent)] [mask-image:linear-gradient(90deg,black_calc(100%-28px),transparent)]";

// Чип на телефоне 40 px высотой — добираем зону нажатия до 44 невидимым полем.
const TAB = "relative whitespace-nowrap before:absolute before:inset-x-0 before:-inset-y-0.5";

// Стрелка лежит поверх ленты, поэтому непрозрачная. На светлой сцене она белая с мягкой тёплой тенью: серый кружок
// почти сливался бы с «бумагой», а чёрная тень легла бы на неё пятном.
const ARROW = `absolute top-1/2 grid size-8 -translate-y-1/2 cursor-pointer place-items-center rounded-full border border-vs-ink/12 bg-surface text-muted shadow-lg shadow-vs-ink/15 transition-colors hover:border-vs-ink/25 hover:text-foreground dark:bg-surface-2 dark:shadow-black/50 ${VS_FOCUS}`;

const scrollMode = (): ScrollBehavior => (prefersReducedMotion() ? "auto" : "smooth");

export default function GalleryTabs({
  tabs,
  active,
  onSelect,
  idBase,
  panelId,
  label,
  arrows,
  prevLabel,
  nextLabel,
  className,
}: GalleryTabsProps) {
  const strip = useRef<HTMLDivElement>(null);
  // С какой стороны за краем ленты ещё есть вкладки.
  const [edges, setEdges] = useState({ start: false, end: false });

  useEffect(() => {
    const el = strip.current;
    if (!el) return;
    let frame = 0;
    const measure = () => {
      frame = 0;
      const start = el.scrollLeft > 1;
      const end = el.scrollLeft + el.clientWidth < el.scrollWidth - 1;
      setEdges((prev) => (prev.start === start && prev.end === end ? prev : { start, end }));
    };
    const queue = () => {
      if (!frame) frame = requestAnimationFrame(measure);
    };
    el.addEventListener("scroll", queue, { passive: true });
    const ro = typeof ResizeObserver === "undefined" ? null : new ResizeObserver(queue);
    ro?.observe(el);
    queue();
    return () => {
      el.removeEventListener("scroll", queue);
      ro?.disconnect();
      if (frame) cancelAnimationFrame(frame);
    };
    // Вкладки сменились (другой язык, обновилась витрина) — ширина ленты другая.
  }, [tabs]);

  /** Выбранную вкладку — в середину ленты: видно соседей с обеих сторон. Двигаем только ленту, не страницу. */
  const center = (tab: HTMLElement) => {
    const el = strip.current;
    if (!el) return;
    const box = el.getBoundingClientRect();
    const rect = tab.getBoundingClientRect();
    el.scrollBy({ left: rect.left - box.left - (box.width - rect.width) / 2, behavior: scrollMode() });
  };

  const nudge = (dir: -1 | 1) => {
    const el = strip.current;
    if (el) el.scrollBy({ left: dir * el.clientWidth * 0.7, behavior: scrollMode() });
  };

  const onKeyDown = (e: KeyboardEvent<HTMLDivElement>) => {
    // Alt+← — «назад» в браузере: чужие сочетания не трогаем.
    if (e.altKey || e.ctrlKey || e.metaKey || e.shiftKey) return;
    const last = tabs.length - 1;
    const at = Math.max(
      0,
      tabs.findIndex((tab) => tab.id === active),
    );
    let next: number;
    if (e.key === "ArrowRight") next = at === last ? 0 : at + 1;
    else if (e.key === "ArrowLeft") next = at === 0 ? last : at - 1;
    else if (e.key === "Home") next = 0;
    else if (e.key === "End") next = last;
    else return;
    e.preventDefault();
    if (next === at) return;
    onSelect(tabs[next].id);
    const button = strip.current?.querySelectorAll<HTMLElement>('[role="tab"]')[next];
    if (!button) return;
    button.focus({ preventScroll: true });
    center(button);
  };

  return (
    // Лента идёт от края до края секции (её поля — VS_SECTION): вкладки уезжают под край экрана, а не под поле.
    <div className={vx("relative -mx-4 sm:-mx-6", className)}>
      <div
        ref={strip}
        role="tablist"
        aria-label={label}
        aria-orientation="horizontal"
        onKeyDown={onKeyDown}
        // Поля по вертикали — чтобы прокрутка ленты не обрезала кольцо фокуса и зону нажатия.
        className={vx(
          "vs-noscroll -my-1 flex gap-2 overflow-x-auto overscroll-x-contain px-4 py-1 sm:px-6",
          edges.start && edges.end ? "vs-fade-x" : edges.start ? FADE_START : edges.end && FADE_END,
        )}
      >
        {tabs.map((tab, index) => {
          const on = tab.id === active;
          return (
            <button
              key={tab.id}
              type="button"
              role="tab"
              id={tabDomId(idBase, index)}
              aria-selected={on}
              aria-controls={panelId}
              tabIndex={on ? 0 : -1}
              onClick={(e) => {
                onSelect(tab.id);
                center(e.currentTarget);
              }}
              className={vx(VS_PILL, TAB, on && VS_PILL_ON)}
            >
              {tab.title}
            </button>
          );
        })}
      </div>

      {arrows && edges.start && (
        <button
          type="button"
          tabIndex={-1}
          onClick={() => nudge(-1)}
          aria-label={prevLabel}
          title={prevLabel}
          className={vx(ARROW, "left-1.5 sm:left-3")}
        >
          <FiChevronLeft aria-hidden />
        </button>
      )}
      {arrows && edges.end && (
        <button
          type="button"
          tabIndex={-1}
          onClick={() => nudge(1)}
          aria-label={nextLabel}
          title={nextLabel}
          className={vx(ARROW, "right-1.5 sm:right-3")}
        >
          <FiChevronRight aria-hidden />
        </button>
      )}
    </div>
  );
}
