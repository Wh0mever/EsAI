"use client";

import { memo, type KeyboardEvent, type ReactNode } from "react";
import { useTranslation } from "react-i18next";
import { FiChevronLeft, FiChevronRight } from "react-icons/fi";
import type { TakeLite, Uid } from "@/lib/vstudio/types";
import Segments, { type SegmentTone } from "../ui/Segments";
import { VS_FOCUS, VS_LABEL, vx } from "../ui/skin";
import { isOpenStatus, statusPhrase } from "./feedLogic";

export type TakeCarouselProps = {
  takes: TakeLite[];
  /** Индекс показанного дубля (pickTakeIndex). */
  index: number;
  onSelect: (uid: Uid) => void;
  children: ReactNode;
};

/** Чем закончился дубль — цветом его сегмента; отменённый остаётся серым. */
const TAKE_TONE: Partial<Record<TakeLite["status"], SegmentTone>> = {
  done: "ok",
  failed: "fail",
  lost: "wait",
};

const ARROW = `grid size-11 shrink-0 cursor-pointer place-items-center rounded-full text-muted transition-colors hover:bg-white/[0.08] hover:text-foreground disabled:cursor-default disabled:opacity-30 disabled:hover:bg-transparent md:size-9 ${VS_FOCUS}`;

/**
 * Карусель дублей «Дубль 2 из 3» (§9.6). Каждый «Повторить» — новый дубль
 * того же кадра; лента не растёт, а карточка листается. С одним дублем
 * переключателя нет вовсе.
 *
 * Переключатель стоит над кадром, а не под ним: дубли разной высоты (идущий —
 * полоса, готовый — ролик), и под кадром стрелки убегали бы из-под курсора
 * при каждом нажатии.
 */
function TakeCarousel({ takes, index, onSelect, children }: TakeCarouselProps) {
  const { t } = useTranslation("vstudio", { useSuspense: false });
  const n = takes.length;
  if (n <= 1) return <>{children}</>;

  const i = Math.min(Math.max(index, 0), n - 1);
  const go = (to: number) => {
    const next = takes[Math.min(Math.max(to, 0), n - 1)];
    if (next) onSelect(next.uid);
  };
  const takeLabel = (k: number) => t("run.actions.takes", { defaultValue: "Дубль {{i}} из {{n}}", i: k + 1, n });
  const caption = takeLabel(i);
  // Исход дубля виден по цвету сегмента; скринридеру его говорит подпись.
  const segmentTone = (k: number): SegmentTone => {
    const take = takes[k];
    if (!take) return "idle";
    return isOpenStatus(take.status) ? "progress" : (TAKE_TONE[take.status] ?? "idle");
  };
  const segmentLabel = (k: number) => {
    const take = takes[k];
    if (!take) return takeLabel(k);
    const phrase = statusPhrase(take);
    return `${takeLabel(k)} · ${t(phrase.key, { defaultValue: phrase.ru, ...(phrase.params || {}) })}`;
  };

  const onKeyDown = (e: KeyboardEvent<HTMLDivElement>) => {
    if (e.altKey || e.ctrlKey || e.metaKey || e.shiftKey) return;
    if (e.key !== "ArrowLeft" && e.key !== "ArrowRight") return;
    e.preventDefault();
    go(e.key === "ArrowLeft" ? i - 1 : i + 1);
  };

  return (
    <div className="flex flex-col gap-1.5">
      <div
        role="group"
        aria-label={caption}
        onKeyDown={onKeyDown}
        className="flex min-h-11 items-center gap-3 pl-0.5 md:min-h-9"
      >
        <span className={vx(VS_LABEL, "shrink-0 tabular-nums !text-muted")} aria-live="polite">
          {caption}
        </span>
        <Segments
          count={n}
          active={i}
          onSelect={go}
          label={segmentLabel}
          tone={segmentTone}
          className="min-w-0 flex-1 !justify-start"
        />
        <div className="flex shrink-0 items-center">
          <button
            type="button"
            onClick={() => go(i - 1)}
            disabled={i === 0}
            aria-label={t("run.actions.prevTake", { defaultValue: "Предыдущий дубль" })}
            className={ARROW}
          >
            <FiChevronLeft aria-hidden />
          </button>
          <button
            type="button"
            onClick={() => go(i + 1)}
            disabled={i === n - 1}
            aria-label={t("run.actions.nextTake", { defaultValue: "Следующий дубль" })}
            className={ARROW}
          >
            <FiChevronRight aria-hidden />
          </button>
        </div>
      </div>
      {children}
    </div>
  );
}

export default memo(TakeCarousel);
