"use client";

import Link from "next/link";
import { memo } from "react";
import type { CSSProperties } from "react";
import { FiArrowRight } from "react-icons/fi";
import LazyClip from "../../ui/LazyClip";
import { VS_FOCUS, VS_MEDIA, VS_ON_MEDIA, vx } from "../../ui/skin";
import { useReveal } from "../../ui/useReveal";
import type { ReelItem } from "../showreelData";

/** Сетка галереи; заглушки на время загрузки повторяют её же. */
export const GALLERY_GRID = "grid grid-cols-2 gap-x-4 gap-y-6 md:grid-cols-3 xl:grid-cols-4";

export type GalleryCardProps = {
  item: ReelItem;
  /** Название; если сервер его не дал, запасное подставляет галерея. */
  title: string;
  /** Откуда кадр: «Мультстудия» или «Видеостудия» — плашка на кадре. */
  source: string;
  /** Что будет по нажатию: «Снять такую сцену», «Снять похожее»… */
  action: string;
  /** Есть курсор: ролик играет под ним, подпись действия появляется при наведении. */
  hover: boolean;
  /** Задержка появления, мс: карточки ряда выходят по очереди. */
  delayMs: number;
  onUse: (item: ReelItem) => void;
};

// Кольцо фокуса отодвинуто: вплотную к подписи оно читалось бы как рамка текста.
const CARD = `group block w-full cursor-pointer rounded-xl text-left transition-transform duration-200 motion-safe:active:scale-[0.97] focus-visible:ring-offset-4 focus-visible:ring-offset-background ${VS_FOCUS}`;

// Подпись действия выезжает поверх правого края второй строки; слева растворяется в фоне сцены.
const ACTION =
  "pointer-events-none absolute inset-y-0 right-0 flex items-center gap-1 whitespace-nowrap bg-linear-to-l from-background from-[calc(100%-2.5rem)] to-transparent pl-10 text-xs font-medium text-accent opacity-0 transition-opacity duration-300 group-hover:opacity-100 group-focus-visible:opacity-100 motion-reduce:transition-none";

/**
 * Карточка галереи: кадр 16:9 и две строки под ним. Вся карточка — одна
 * ссылка (сцена мультстудии ведёт в /studio) или одна кнопка (работа
 * видеостудии готовит панель запроса). Высоту держит рамка кадра, поэтому
 * сетка не прыгает, пока грузятся постеры.
 */
function GalleryCard({ item, title, source, action, hover, delayMs, onUse }: GalleryCardProps) {
  const reveal = useReveal<HTMLLIElement>();

  const body = (
    <>
      <span className={vx(VS_MEDIA, "vs-sheen block aspect-video w-full")}>
        <LazyClip
          src={item.video}
          poster={item.poster}
          mode={hover ? "hover" : "visible"}
          alt=""
          className="absolute inset-0"
        />
        <span className={vx(VS_ON_MEDIA, "pointer-events-none absolute left-2 top-2")}>{source}</span>
        <span
          aria-hidden
          className="pointer-events-none absolute inset-0 rounded-xl border border-white/10 transition-colors duration-300 group-hover:border-white/25 group-focus-visible:border-white/25"
        />
      </span>
      <span className="mt-2.5 block truncate text-sm font-medium text-foreground/90 transition-colors group-hover:text-foreground">
        {title}
      </span>
      <span className="relative mt-0.5 flex h-5 items-center gap-2">
        <span className="min-w-0 flex-1 truncate text-xs text-muted">{item.subtitle}</span>
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
    </>
  );

  return (
    <li ref={reveal} className="vs-reveal min-w-0" style={{ "--vs-delay": `${delayMs}ms` } as CSSProperties}>
      {item.href ? (
        <Link href={item.href} onClick={() => onUse(item)} data-vs-card="" className={CARD}>
          {body}
        </Link>
      ) : (
        <button type="button" onClick={() => onUse(item)} data-vs-card="" className={CARD}>
          {body}
        </button>
      )}
    </li>
  );
}

export default memo(GalleryCard);
