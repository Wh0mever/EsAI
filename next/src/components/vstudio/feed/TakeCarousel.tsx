"use client";

import { memo, type ReactNode } from "react";
import { useTranslation } from "react-i18next";
import { FiChevronLeft, FiChevronRight } from "react-icons/fi";
import type { TakeLite, Uid } from "@/lib/vstudio/types";
import { isOpenStatus } from "./feedLogic";

export type TakeCarouselProps = {
  takes: TakeLite[];
  /** Индекс показанного дубля (pickTakeIndex). */
  index: number;
  onSelect: (uid: Uid) => void;
  children: ReactNode;
};

const DOT: Record<string, string> = {
  done: "bg-status-ok",
  failed: "bg-status-fail",
  lost: "bg-status-wait",
  canceled: "bg-muted-2",
};

/**
 * Карусель дублей «Дубль 2 из 3» (§9.6). Каждый «Повторить» — новый дубль
 * того же кадра; лента не растёт, а карточка листается. С одним дублем
 * переключателя нет вовсе.
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
  const caption = t("run.actions.takes", { defaultValue: "Дубль {{i}} из {{n}}", i: i + 1, n });

  return (
    <div className="flex flex-col gap-2">
      <div className="flex items-center gap-1">
        <button
          type="button"
          onClick={() => go(i - 1)}
          disabled={i === 0}
          aria-label={t("run.actions.prevTake", { defaultValue: "Предыдущий дубль" })}
          className="grid size-9 cursor-pointer place-items-center rounded-lg text-muted transition-colors hover:bg-surface-2 hover:text-foreground disabled:cursor-default disabled:opacity-35"
        >
          <FiChevronLeft aria-hidden />
        </button>
        <span className="min-w-[6.5rem] text-center text-xs tabular-nums text-muted" aria-live="polite">
          {caption}
        </span>
        <button
          type="button"
          onClick={() => go(i + 1)}
          disabled={i === n - 1}
          aria-label={t("run.actions.nextTake", { defaultValue: "Следующий дубль" })}
          className="grid size-9 cursor-pointer place-items-center rounded-lg text-muted transition-colors hover:bg-surface-2 hover:text-foreground disabled:cursor-default disabled:opacity-35"
        >
          <FiChevronRight aria-hidden />
        </button>
        <div className="ml-1 flex items-center gap-1" role="group" aria-label={caption}>
          {takes.map((take, k) => (
            <button
              key={take.uid}
              type="button"
              aria-current={k === i ? "true" : undefined}
              aria-label={t("run.actions.takes", { defaultValue: "Дубль {{i}} из {{n}}", i: k + 1, n })}
              onClick={() => onSelect(take.uid)}
              className="grid size-6 cursor-pointer place-items-center rounded-full"
            >
              <span
                className={`block rounded-full transition-all ${k === i ? "size-2.5" : "size-1.5 opacity-70"} ${
                  isOpenStatus(take.status) ? "animate-pulse bg-status-progress" : DOT[take.status] || "bg-muted-2"
                }`}
              />
            </button>
          ))}
        </div>
      </div>
      {children}
    </div>
  );
}

export default memo(TakeCarousel);
