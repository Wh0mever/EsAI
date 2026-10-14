"use client";

import { memo } from "react";
import { FiArrowRight } from "react-icons/fi";
import LazyClip from "../../ui/LazyClip";
import { VS_FOCUS, VS_MEDIA, VS_ON_MEDIA, VS_SHEEN_ON_MEDIA, vx } from "../../ui/skin";
import type { ReelItem } from "../showreelData";
import { trendFit } from "./trendsLogic";

export type TrendCardProps = {
  item: ReelItem;
  title: string;
  /** Модель; пусто — она уже стоит названием. */
  subtitle: string;
  /** «5 с»; пусто — плашки на кадре нет. */
  seconds: string;
  /** Что будет по нажатию: «Снять похожее» или «Выбрать эту модель». */
  action: string;
  /** Есть курсор: ролик играет под ним, подпись действия выходит при наведении. */
  hover: boolean;
  onUse: (item: ReelItem) => void;
};

// Кольцо фокуса отодвинуто: вплотную к подписи оно читалось бы как рамка текста.
const CARD = vx(
  "group block w-full cursor-pointer rounded-xl text-left transition-transform duration-200 motion-safe:active:scale-[0.97] focus-visible:ring-offset-4 focus-visible:ring-offset-background",
  VS_FOCUS,
);

// Отклик кадра на курсор. В тёмной теме его даёт светлеющая кромка (ниже); на тёмном кадре посреди светлой
// сцены тёмная кромка почти не видна — там кадр приподнимается мягкой тенью.
const MEDIA_LIFT =
  "transition-shadow duration-300 group-hover:shadow-[var(--vs-card-hover-shadow)] group-focus-visible:shadow-[var(--vs-card-hover-shadow)] dark:group-hover:shadow-none dark:group-focus-visible:shadow-none";

// Подпись действия выезжает поверх правого края второй строки; слева растворяется в фоне сцены.
const ACTION =
  "pointer-events-none absolute inset-y-0 right-0 flex items-center gap-1 whitespace-nowrap bg-linear-to-l from-background from-[calc(100%-2.5rem)] to-transparent pl-10 text-xs font-medium text-vs-accent opacity-0 transition-opacity duration-300 group-hover:opacity-100 group-focus-visible:opacity-100 motion-reduce:transition-none";

/**
 * Карточка «Трендов»: кадр 16:9 и две строки под ним. Вся карточка — одна
 * кнопка: нажатие готовит панель запроса, как пример из карусели. Высоту держит
 * рамка кадра, поэтому сетка не прыгает, пока грузятся постеры. Ролик заводит
 * LazyClip — под курсором или фокусом с клавиатуры, а где курсора нет, — когда
 * карточка на экране; сколько играет разом, решает общий бюджет первого экрана.
 */
function TrendCard({ item, title, subtitle, seconds, action, hover, onUse }: TrendCardProps) {
  return (
    <button type="button" onClick={() => onUse(item)} data-vs-card="" className={CARD}>
      <span className={vx(VS_MEDIA, "vs-sheen block aspect-video w-full", VS_SHEEN_ON_MEDIA, MEDIA_LIFT)}>
        <LazyClip
          src={item.video}
          poster={item.poster}
          mode="hover"
          alt=""
          fit={trendFit(item)}
          className="absolute inset-0"
        />
        {seconds && (
          <span className={vx(VS_ON_MEDIA, "pointer-events-none absolute bottom-2 right-2 tabular-nums")}>
            {seconds}
          </span>
        )}
        {/* Кромка — «чернилами» темы: кадр лежит прямо на сцене, и светлый постер на светлой сцене без неё теряет край. */}
        <span
          aria-hidden
          className="pointer-events-none absolute inset-0 rounded-xl border border-vs-ink/10 transition-colors duration-300 group-hover:border-vs-ink/25 group-focus-visible:border-vs-ink/25"
        />
      </span>
      <span className="mt-2.5 block truncate text-sm font-medium text-foreground">{title}</span>
      <span className="relative mt-0.5 flex h-5 items-center gap-2">
        <span className="min-w-0 flex-1 truncate text-xs text-muted">{subtitle}</span>
        {hover ? (
          <span className={ACTION}>
            {action}
            <FiArrowRight
              aria-hidden
              className="size-3.5 transition-transform duration-300 motion-safe:group-hover:translate-x-0.5"
            />
          </span>
        ) : (
          // Навести нечем — подпись остаётся для скринридера, на экране хватает стрелки.
          <>
            <span className="sr-only">{action}</span>
            <FiArrowRight aria-hidden className="size-3.5 shrink-0 text-muted-2" />
          </>
        )}
      </span>
    </button>
  );
}

export default memo(TrendCard);
