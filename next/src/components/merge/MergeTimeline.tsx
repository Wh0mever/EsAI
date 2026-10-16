"use client";

import { useEffect, useId, useRef, useState, type KeyboardEvent, type PointerEvent as ReactPointerEvent } from "react";
import { useTranslation } from "react-i18next";
import { FiAlertCircle, FiArrowDown, FiArrowUp, FiMenu, FiPlus, FiX } from "react-icons/fi";
import { VS_BTN_GHOST, VS_BTN_LINK, VS_CARD, VS_ICON_BTN, VS_ON_MEDIA, VS_SUB, VS_TAG, vx } from "@/components/vstudio/ui/skin";
import { CS_EMPTY, CS_SKELETON } from "@/components/studio/ui/cartoonSkin";
import MediaThumb from "./MediaThumb";
import { dropIndex, formatDuration, shiftFor, type LocalItem } from "./mergeLogic";
import type { MergeLimits, MergeSourceType } from "./mergeTypes";

/**
 * Лента склейки: фрагменты по порядку, сверху вниз — так же они пойдут в
 * ролик. Переставить — кнопками ↑/↓ (с клавиатуры тоже), стрелками на ручке
 * ≡ или перетаскиванием за неё (мышью и пальцем: ручка не прокручивает
 * страницу). Убрать — ✕. Без правки (склейка идёт или готова) — тот же
 * список без кнопок.
 */

/** Откуда фрагмент — метка на строке ленты и на карточке «Мультстудии» в выборе. */
export const SOURCE_RU: Record<MergeSourceType, string> = {
  vstudio: "Видеостудия",
  cartoon_scene: "Сцена мультфильма",
  cartoon_movie: "Мультфильм",
  chat: "Чат",
};

/** У края прокрутки лента сама едет за пальцем. */
const EDGE_PX = 56;
const EDGE_STEP = 14;

type Drag = { key: string; from: number; to: number; dy: number; size: number };
type DragData = {
  pointerId: number;
  startY: number;
  scroll0: number;
  mids: number[];
  from: number;
  to: number;
  scroller: HTMLElement | null;
};

export type MergeTimelineProps = {
  items: LocalItem[];
  editable: boolean;
  limits: MergeLimits;
  total: number;
  onMove: (from: number, to: number) => void;
  onRemove: (index: number) => void;
  /** Телефон: пустая лента ведёт к выбору роликов. */
  onAdd?: () => void;
  /** Последняя правка не дошла до сервера (повтор идёт сам). */
  unsaved?: boolean;
  onRetrySave?: () => void;
  headingId: string;
};

export default function MergeTimeline({
  items,
  editable,
  limits,
  total,
  onMove,
  onRemove,
  onAdd,
  unsaved = false,
  onRetrySave,
  headingId,
}: MergeTimelineProps) {
  const { t } = useTranslation("vstudio", { useSuspense: false });
  const listRef = useRef<HTMLOListElement>(null);
  const data = useRef<DragData | null>(null);
  /** Куда вернуть фокус после ✕: строка исчезла, и фокус иначе упал бы в начало страницы. */
  const refocus = useRef<{ index: number; length: number } | null>(null);
  const [drag, setDrag] = useState<Drag | null>(null);
  const [said, setSaid] = useState("");
  const hintId = useId();

  useEffect(() => {
    const want = refocus.current;
    refocus.current = null;
    if (!want || items.length !== want.length) return;
    const buttons = listRef.current?.querySelectorAll<HTMLElement>("[data-merge-remove]");
    const next = buttons && buttons.length > 0 ? buttons[Math.min(want.index, buttons.length - 1)] : null;
    if (next) next.focus();
    else document.getElementById(headingId)?.focus();
  }, [items, headingId]);

  const titleOf = (it: LocalItem) => it.title.trim() || t("merge.untitled", { defaultValue: "Без названия" });

  /** Переставили — говорим, куда встал: глазами это видно, ушами — нет. */
  const move = (from: number, to: number) => {
    if (to < 0 || to >= items.length || to === from) return;
    onMove(from, to);
    setSaid(
      t("merge.tl.moved", {
        defaultValue: "«{{title}}» — место {{n}} из {{total}}",
        title: titleOf(items[from]),
        n: to + 1,
        total: items.length,
      }),
    );
  };

  const remove = (index: number) => {
    const title = titleOf(items[index]);
    // Фокус — на ✕ строки, вставшей на это место (или предыдущей), без строк — на заголовок.
    refocus.current = { index, length: items.length - 1 };
    onRemove(index);
    setSaid(t("merge.tl.removed", { defaultValue: "«{{title}}» убран из склейки", title }));
  };

  const onDown = (e: ReactPointerEvent<HTMLButtonElement>, index: number) => {
    if (!editable || e.button !== 0 || items.length < 2) return;
    const list = listRef.current;
    if (!list) return;
    const rows = Array.from(list.children) as HTMLElement[];
    const scroller = list.closest<HTMLElement>("[data-vs-feed]");
    const scroll0 = scroller?.scrollTop ?? 0;
    const rects = rows.map((r) => r.getBoundingClientRect());
    const gap = rects.length > 1 ? rects[1].top - rects[0].bottom : 0;
    data.current = {
      pointerId: e.pointerId,
      startY: e.clientY,
      scroll0,
      mids: rects.map((r) => r.top + r.height / 2 + scroll0),
      from: index,
      to: index,
      scroller,
    };
    e.currentTarget.setPointerCapture(e.pointerId);
    e.preventDefault();
    setDrag({ key: items[index].key, from: index, to: index, dy: 0, size: rects[index].height + gap });
  };

  const onMovePointer = (e: ReactPointerEvent<HTMLButtonElement>) => {
    const d = data.current;
    if (!d || e.pointerId !== d.pointerId) return;
    const scroller = d.scroller;
    if (scroller) {
      const box = scroller.getBoundingClientRect();
      if (e.clientY < box.top + EDGE_PX) scroller.scrollTop -= EDGE_STEP;
      else if (e.clientY > box.bottom - EDGE_PX) scroller.scrollTop += EDGE_STEP;
    }
    const dy = e.clientY + (scroller?.scrollTop ?? 0) - (d.startY + d.scroll0);
    const to = dropIndex(d.mids, d.from, d.mids[d.from] + dy);
    d.to = to;
    setDrag((cur) => (cur ? { ...cur, dy, to } : cur));
  };

  const finish = (commit: boolean) => {
    const d = data.current;
    data.current = null;
    setDrag(null);
    if (commit && d && d.to !== d.from) move(d.from, d.to);
  };

  const onHandleKey = (e: KeyboardEvent<HTMLButtonElement>, index: number) => {
    if (e.key === "Escape" && data.current) {
      e.preventDefault();
      finish(false);
      return;
    }
    if (e.key !== "ArrowUp" && e.key !== "ArrowDown") return;
    e.preventDefault();
    move(index, index + (e.key === "ArrowUp" ? -1 : 1));
  };

  const limitText = t("merge.tl.limit", {
    defaultValue: "{{n}} из {{max}} · {{total}} из {{maxTotal}}",
    n: items.length,
    max: limits.max_fragments,
    total: formatDuration(total),
    maxTotal: formatDuration(limits.max_total_s),
  });

  return (
    <section aria-labelledby={headingId} className="flex min-w-0 flex-col gap-3">
      <div className="flex flex-wrap items-end justify-between gap-x-4 gap-y-1">
        <div className="min-w-0">
          {/* tabIndex — сюда ставят фокус «N фрагм. · M:SS» из дока. */}
          <h2 id={headingId} tabIndex={-1} className="text-base font-semibold text-foreground focus:outline-none">
            {t("merge.tl.title", { defaultValue: "Порядок фрагментов" })}
          </h2>
          {editable && items.length > 1 && (
            <p id={hintId} className={vx(VS_SUB, "mt-0.5 text-[13px]")}>
              {t("merge.tl.hint", { defaultValue: "Сверху вниз — так они пойдут в ролик. Перетащите за ≡ или двигайте стрелками." })}
            </p>
          )}
        </div>
        {items.length > 0 && <span className="text-xs tabular-nums text-muted-2">{limitText}</span>}
      </div>

      {editable && unsaved && onRetrySave && (
        <div role="status" className="flex flex-wrap items-center gap-x-2 text-[13px] leading-snug text-status-fail">
          <FiAlertCircle className="shrink-0" aria-hidden="true" />
          <span>{t("merge.tl.unsaved", { defaultValue: "Изменения не сохранены" })}</span>
          <button type="button" onClick={onRetrySave} className={vx(VS_BTN_LINK, "!px-1.5 !text-vs-accent")}>
            {t("page.retry", { defaultValue: "Попробовать снова" })}
          </button>
        </div>
      )}

      {items.length === 0 ? (
        <div className={vx(CS_EMPTY, "py-10")}>
          <FiPlus className="size-6 text-vs-accent" aria-hidden="true" />
          <p className="max-w-sm">
            {t("merge.tl.empty", {
              defaultValue: "Добавьте хотя бы два ролика — они склеятся в один в том порядке, в каком стоят здесь.",
            })}
          </p>
          {onAdd && (
            <button type="button" onClick={onAdd} className={vx(VS_BTN_GHOST, "mt-1 lg:hidden")}>
              <FiPlus className="text-vs-accent" aria-hidden="true" />
              {t("merge.tl.add", { defaultValue: "Добавить видео" })}
            </button>
          )}
        </div>
      ) : (
        <ol ref={listRef} className="flex flex-col gap-2" aria-describedby={editable && items.length > 1 ? hintId : undefined}>
          {items.map((it, i) => {
            const dragged = drag?.key === it.key;
            const shift = drag && !dragged ? shiftFor(i, drag.from, drag.to, drag.size) : 0;
            const offset = dragged && drag ? drag.dy : shift;
            const title = titleOf(it);
            const vertical = Boolean(it.width && it.height && it.height > it.width);
            const upLabel = t("merge.tl.up", { defaultValue: "Выше" });
            const downLabel = t("merge.tl.down", { defaultValue: "Ниже" });
            const removeLabel = t("merge.tl.remove", { defaultValue: "Убрать из склейки" });
            const handleLabel = t("merge.tl.handle", { defaultValue: "Перетащить: {{title}}", title });
            const first = i === 0;
            const last = i === items.length - 1;
            return (
              <li
                key={it.key}
                style={offset ? { transform: `translateY(${offset}px)` } : undefined}
                className={vx(
                  VS_CARD,
                  "relative flex items-center gap-3 p-2 sm:p-2.5",
                  // Соседи расступаются плавно, пока строку тащат; сама строка идёт за пальцем без задержки.
                  drag && !dragged && "transition-transform duration-150 motion-reduce:transition-none",
                  dragged && "z-10 vs-shadow-float",
                )}
              >
                <div className="relative aspect-video w-24 shrink-0 overflow-hidden rounded-xl sm:w-36">
                  <MediaThumb
                    poster={it.poster}
                    url={it.available ? it.url : null}
                    title={title}
                    vertical={vertical}
                    compact
                    className={it.available ? "" : "opacity-50"}
                  />
                  <span className="pointer-events-none absolute left-1 top-1 grid size-5 place-items-center rounded-full bg-accent text-[10px] font-bold text-on-accent">
                    {i + 1}
                  </span>
                  {it.duration_s != null && (
                    <span className={vx(VS_ON_MEDIA, "pointer-events-none absolute bottom-1 right-1 tabular-nums")}>
                      {formatDuration(it.duration_s)}
                    </span>
                  )}
                </div>

                <div className="flex min-w-0 flex-1 flex-col gap-1.5 sm:flex-row sm:items-center sm:gap-3">
                  <div className="min-w-0 flex-1">
                    <p className="line-clamp-2 text-[13px] font-medium leading-snug text-foreground sm:text-sm" title={title}>
                      <span className="sr-only">{t("merge.tl.number", { defaultValue: "Фрагмент {{n}}:", n: i + 1 })} </span>
                      {title}
                    </p>
                    <div className="mt-1 flex flex-wrap items-center gap-1.5">
                      <span className={vx(VS_TAG, "max-sm:hidden")}>
                        {t(`merge.source.${it.type}`, { defaultValue: SOURCE_RU[it.type] })}
                      </span>
                      {it.subtitle && <span className="min-w-0 truncate text-[11px] text-muted-2 max-sm:hidden">{it.subtitle}</span>}
                    </div>
                    {!it.available && (
                      <p className="mt-1 flex items-start gap-1 text-[12px] leading-snug text-status-fail">
                        <FiAlertCircle className="mt-0.5 shrink-0" aria-hidden="true" />
                        {t("merge.tl.unavailable", { defaultValue: "Видео недоступно — уберите его из склейки" })}
                      </p>
                    )}
                  </div>

                  {editable && (
                    <div className="flex shrink-0 items-center gap-1">
                      {items.length > 1 && (
                        <button
                          type="button"
                          onPointerDown={(e) => onDown(e, i)}
                          onPointerMove={onMovePointer}
                          onPointerUp={() => finish(true)}
                          onPointerCancel={() => finish(false)}
                          onLostPointerCapture={() => {
                            if (data.current) finish(true);
                          }}
                          onKeyDown={(e) => onHandleKey(e, i)}
                          aria-label={handleLabel}
                          title={handleLabel}
                          className={vx(VS_ICON_BTN, "touch-none !cursor-grab active:!cursor-grabbing md:!size-9")}
                        >
                          <FiMenu aria-hidden="true" />
                        </button>
                      )}
                      <button
                        type="button"
                        onClick={() => move(i, i - 1)}
                        aria-disabled={first || undefined}
                        aria-label={upLabel}
                        title={upLabel}
                        className={vx(VS_ICON_BTN, "md:!size-9", first && "!cursor-not-allowed opacity-40")}
                      >
                        <FiArrowUp aria-hidden="true" />
                      </button>
                      <button
                        type="button"
                        onClick={() => move(i, i + 1)}
                        aria-disabled={last || undefined}
                        aria-label={downLabel}
                        title={downLabel}
                        className={vx(VS_ICON_BTN, "md:!size-9", last && "!cursor-not-allowed opacity-40")}
                      >
                        <FiArrowDown aria-hidden="true" />
                      </button>
                      <button
                        type="button"
                        data-merge-remove=""
                        onClick={() => remove(i)}
                        aria-label={removeLabel}
                        title={removeLabel}
                        className={vx(VS_ICON_BTN, "md:!size-9 hover:!text-status-fail")}
                      >
                        <FiX aria-hidden="true" />
                      </button>
                    </div>
                  )}
                </div>
              </li>
            );
          })}
        </ol>
      )}
      {/* Один фрагмент на телефоне (сразу после «Открыть в склейке»): что дальше — видно здесь, а не только у кнопки. */}
      {editable && onAdd && items.length > 0 && items.length < limits.min_fragments && (
        <div className={vx(CS_EMPTY, "py-5 lg:hidden")}>
          <p className="max-w-sm">
            {t("merge.err.too_few_fragments", { defaultValue: "Добавьте хотя бы 2 фрагмента, чтобы склеить." })}
          </p>
          <button type="button" onClick={onAdd} className={VS_BTN_GHOST}>
            <FiPlus className="text-vs-accent" aria-hidden="true" />
            {t("merge.tl.add", { defaultValue: "Добавить видео" })}
          </button>
        </div>
      )}
      <p className="sr-only" role="status" aria-live="polite">
        {said}
      </p>
    </section>
  );
}

/** Заглушка ленты той же геометрии, пока склейка открывается. */
export function TimelineSkeleton() {
  return (
    <div className="flex flex-col gap-2" aria-hidden="true">
      {[0, 1, 2].map((i) => (
        <div key={i} className={vx(VS_CARD, "flex items-center gap-3 p-2 sm:p-2.5")}>
          <div className={vx("aspect-video w-24 shrink-0 rounded-xl sm:w-36", CS_SKELETON)} />
          <div className="flex-1 space-y-2">
            <div className={vx("h-2.5 w-3/4 rounded-full", CS_SKELETON)} />
            <div className={vx("h-2.5 w-1/3 rounded-full", CS_SKELETON)} />
          </div>
        </div>
      ))}
    </div>
  );
}
