"use client";

import { useId, type KeyboardEvent } from "react";
import { useTranslation } from "react-i18next";
import { FiArrowUpRight, FiCheck, FiChevronDown, FiFilm, FiLoader, FiPlus, FiRefreshCw } from "react-icons/fi";
import Link from "next/link";
import {
  VS_BTN_GHOST,
  VS_BTN_LINK,
  VS_CARD,
  VS_FOCUS,
  VS_ICON_BTN,
  VS_ON_MEDIA,
  VS_SEG_THUMB,
  VS_SEG_TRACK,
  VS_SUB,
  VS_TAG,
  vx,
} from "@/components/vstudio/ui/skin";
import { CS_CARD_BTN, CS_EMPTY, CS_SKELETON } from "@/components/studio/ui/cartoonSkin";
import FilmBlock from "@/components/studio/timeline/FilmBlock";
import MediaThumb from "./MediaThumb";
import { SOURCE_RU } from "./MergeTimeline";
import { TABS, VSTUDIO_NAV, addRefusal, formatDuration, type AddRefusal } from "./mergeLogic";
import type { MergeLimits, MergeSourceCard, MergeTab } from "./mergeTypes";
import type { SourcesState } from "./useMerge";

/**
 * Выбор роликов для склейки: вкладки «Видеостудия / Мультстудия / Чат» и
 * сетка своих готовых видео с длительностью и «+ Добавить». Один ролик можно
 * добавить несколько раз — значок на карточке говорит, сколько он уже стоит в
 * склейке. Предел (30 фрагментов, 5 минут) гасит кнопку с причиной.
 */

const TAB_RU: Record<MergeTab, string> = {
  vstudio: "Видеостудия",
  cartoon: "Мультстудия",
  chat: "Чат",
};

export type SourcePickerProps = {
  tab: MergeTab;
  sources: Record<MergeTab, SourcesState>;
  /** Уже в склейке: «тип:id» → сколько раз. */
  counts: Map<string, number>;
  items: { duration_s: number | null }[];
  limits: MergeLimits;
  onTab: (tab: MergeTab) => void;
  onAdd: (card: MergeSourceCard) => void;
  onMore: (tab: MergeTab) => void;
  onReload: (tab: MergeTab) => void;
  /** Заголовок секции (на компьютере — колонка слева, на телефоне — своя вкладка). */
  headingId: string;
};

export default function SourcePicker({
  tab,
  sources,
  counts,
  items,
  limits,
  onTab,
  onAdd,
  onMore,
  onReload,
  headingId,
}: SourcePickerProps) {
  const { t } = useTranslation("vstudio", { useSuspense: false });
  const panelId = useId();
  const state = sources[tab];
  const tabLabel = (x: MergeTab) => t(`merge.tab.${x}`, { defaultValue: TAB_RU[x] });

  // ←/→ по вкладкам, как у переключателя «Видео / Картинка».
  const onTabKey = (e: KeyboardEvent<HTMLButtonElement>, index: number) => {
    if (e.key !== "ArrowRight" && e.key !== "ArrowLeft") return;
    e.preventDefault();
    const next = TABS[(index + (e.key === "ArrowRight" ? 1 : TABS.length - 1)) % TABS.length];
    onTab(next);
    document.getElementById(`${panelId}-tab-${next}`)?.focus();
  };

  return (
    <section aria-labelledby={headingId} className="flex min-w-0 flex-col gap-3">
      <div className="flex items-end justify-between gap-3">
        <div className="min-w-0">
          <h2 id={headingId} className="text-base font-semibold text-foreground">
            {t("merge.picker.title", { defaultValue: "Ваши видео" })}
          </h2>
          <p className={vx(VS_SUB, "mt-0.5 text-[13px]")}>
            {t("merge.picker.sub", { defaultValue: "Готовые ролики из студий и чата" })}
          </p>
        </div>
        <button
          type="button"
          onClick={() => onReload(tab)}
          disabled={state.loading}
          className={vx(VS_ICON_BTN, "md:!size-9")}
          aria-label={t("merge.picker.reload", { defaultValue: "Обновить список" })}
          title={t("merge.picker.reload", { defaultValue: "Обновить список" })}
        >
          <FiRefreshCw className={vx("size-4", state.loading && "animate-spin motion-reduce:animate-none")} aria-hidden="true" />
        </button>
      </div>

      <div role="tablist" aria-label={t("merge.picker.tabs", { defaultValue: "Откуда взять видео" })} className={vx("grid grid-cols-3 gap-1 rounded-full p-1", VS_SEG_TRACK)}>
        {TABS.map((x, i) => {
          const on = x === tab;
          return (
            <button
              key={x}
              id={`${panelId}-tab-${x}`}
              type="button"
              role="tab"
              aria-selected={on}
              aria-controls={panelId}
              tabIndex={on ? 0 : -1}
              onClick={() => onTab(x)}
              onKeyDown={(e) => onTabKey(e, i)}
              className={vx(
                "min-h-11 min-w-0 cursor-pointer truncate rounded-full px-2 text-[13px] font-medium transition-colors md:min-h-9",
                VS_FOCUS,
                on ? vx(VS_SEG_THUMB, "text-vs-accent") : "text-muted hover:text-foreground",
              )}
            >
              {tabLabel(x)}
            </button>
          );
        })}
      </div>

      <div id={panelId} role="tabpanel" aria-labelledby={`${panelId}-tab-${tab}`} aria-busy={state.loading || undefined}>
        {!state.loaded && state.loading ? (
          <PickerSkeleton />
        ) : state.failed && state.items.length === 0 ? (
          <div className={CS_EMPTY}>
            <p>{t("merge.picker.failed", { defaultValue: "Не удалось загрузить видео" })}</p>
            <button type="button" onClick={() => onReload(tab)} className={VS_BTN_GHOST}>
              <FiRefreshCw aria-hidden="true" />
              {t("page.retry", { defaultValue: "Попробовать снова" })}
            </button>
          </div>
        ) : state.items.length === 0 ? (
          <EmptyTab tab={tab} />
        ) : (
          <>
            <ul className="grid grid-cols-2 gap-2.5 sm:grid-cols-3 lg:grid-cols-2">
              {state.items.map((card) => (
                <SourceCard
                  key={`${card.type}:${card.id}`}
                  card={card}
                  count={counts.get(`${card.type}:${card.id}`) ?? 0}
                  refusal={addRefusal(items, card, limits)}
                  onAdd={() => onAdd(card)}
                />
              ))}
            </ul>
            {state.hasMore && (
              <button
                type="button"
                onClick={() => onMore(tab)}
                disabled={state.loading}
                className={vx(VS_BTN_GHOST, "mx-auto mt-4 flex")}
              >
                {state.loading ? (
                  <FiLoader className="animate-spin motion-reduce:animate-none" aria-hidden="true" />
                ) : (
                  <FiChevronDown aria-hidden="true" />
                )}
                {t("nav.more", { defaultValue: "Показать ещё" })}
              </button>
            )}
          </>
        )}
      </div>
    </section>
  );
}

function SourceCard({
  card,
  count,
  refusal,
  onAdd,
}: {
  card: MergeSourceCard;
  count: number;
  refusal: AddRefusal | null;
  onAdd: () => void;
}) {
  const { t } = useTranslation("vstudio", { useSuspense: false });
  const title = card.title.trim() || t("merge.untitled", { defaultValue: "Без названия" });
  const vertical = Boolean(card.width && card.height && card.height > card.width);
  // Почему добавить нельзя: коротко на кнопке, полностью — в подсказке и для диктора.
  let off: { short: string; full: string } | null = null;
  if (refusal?.code === "too_many_fragments") {
    off = {
      short: t("merge.picker.full", { defaultValue: "Уже {{max}}", max: refusal.max }),
      full: t("merge.err.too_many_fragments", { defaultValue: "Можно склеить не больше {{max}} фрагментов.", max: refusal.max }),
    };
  } else if (refusal?.code === "too_long") {
    off = {
      short: t("merge.picker.tooLong", { defaultValue: "Не поместится" }),
      full: t("merge.picker.tooLongHint", {
        defaultValue: "Склейка выйдет длиннее 5 минут ({{total}}).",
        total: formatDuration(refusal.total_s),
      }),
    };
  } else if (refusal?.code === "source_unreadable") {
    off = {
      short: t("merge.picker.unreadable", { defaultValue: "Не читается" }),
      full: t("merge.picker.unreadableHint", { defaultValue: "Этот ролик не получается прочитать — склеить его нельзя." }),
    };
  }
  const addLabel = t("merge.picker.add", { defaultValue: "Добавить" });
  const inMerge = t("merge.picker.inMerge", { defaultValue: "В склейке: {{n}}", n: count });

  return (
    <li className={vx(VS_CARD, "flex min-w-0 flex-col overflow-hidden")}>
      <div className="relative aspect-video">
        <MediaThumb poster={card.poster} url={card.url} title={title} vertical={vertical} />
        {card.duration_s != null && (
          <span className={vx(VS_ON_MEDIA, "pointer-events-none absolute bottom-1.5 right-1.5 tabular-nums")}>
            {formatDuration(card.duration_s)}
          </span>
        )}
        {count > 0 && (
          <span className="pointer-events-none absolute left-1.5 top-1.5 inline-flex items-center gap-1 rounded-full bg-accent px-2 py-0.5 text-[10px] font-semibold leading-4 text-on-accent">
            <FiCheck className="size-3" aria-hidden="true" />
            {count > 1 ? `×${count}` : ""}
            <span className="sr-only">{inMerge}</span>
          </span>
        )}
      </div>
      <div className="flex min-w-0 flex-1 flex-col gap-1 p-2 sm:p-2.5">
        {/* «Мультстудия» отдаёт и целые мультфильмы, и их сцены: без метки легко взять фильм вместе с его же сценами. */}
        {(card.type === "cartoon_movie" || card.type === "cartoon_scene") && (
          <span className={vx(VS_TAG, "self-start")}>
            {t(`merge.source.${card.type}`, { defaultValue: SOURCE_RU[card.type] })}
          </span>
        )}
        <p className="line-clamp-2 text-[13px] font-medium leading-snug text-foreground" title={title}>
          {title}
        </p>
        {card.subtitle && <p className="truncate text-[11px] text-muted-2">{card.subtitle}</p>}
        <button
          type="button"
          onClick={() => {
            if (!off) onAdd();
          }}
          aria-disabled={off ? true : undefined}
          title={off?.full ?? addLabel}
          className={vx(
            CS_CARD_BTN,
            "mt-auto",
            off ? "!cursor-not-allowed opacity-60 hover:!border-vs-ink/12 hover:!bg-vs-ink/[0.05]" : "hover:!border-vs-accent/45",
          )}
        >
          {off ? (
            <>
              <span className="truncate">{off.short}</span>
              <span className="sr-only">. {off.full}</span>
            </>
          ) : (
            <>
              <FiPlus className="shrink-0 text-vs-accent" aria-hidden="true" />
              <span className="truncate">{addLabel}</span>
              <span className="sr-only">: {title}</span>
            </>
          )}
        </button>
      </div>
    </li>
  );
}

function EmptyTab({ tab }: { tab: MergeTab }) {
  const { t } = useTranslation("vstudio", { useSuspense: false });
  const text =
    tab === "vstudio"
      ? t("merge.picker.emptyVstudio", { defaultValue: "Здесь появятся видео, снятые в видеостудии." })
      : tab === "cartoon"
        ? t("merge.picker.emptyCartoon", { defaultValue: "Здесь появятся снятые сцены и собранные мультфильмы." })
        : t("merge.picker.emptyChat", { defaultValue: "Здесь появятся видео, созданные в чате с 21 сентября." });
  const link =
    tab === "vstudio"
      ? VSTUDIO_NAV
        ? { href: "/video-studio", label: t("merge.picker.toVstudio", { defaultValue: "Открыть видеостудию" }) }
        : null
      : tab === "cartoon"
        ? { href: "/studio", label: t("merge.picker.toCartoon", { defaultValue: "Открыть мультстудию" }) }
        : { href: "/", label: t("page.toChat", { defaultValue: "Открыть чат" }) };
  return (
    <div className={CS_EMPTY}>
      <FiFilm className="size-6 text-muted-2" aria-hidden="true" />
      <p className="max-w-xs">{text}</p>
      {link && (
        <Link href={link.href} prefetch={false} className={vx(VS_BTN_LINK, "!text-vs-accent")}>
          {link.label}
          <FiArrowUpRight aria-hidden="true" />
        </Link>
      )}
    </div>
  );
}

/** Заглушка сетки той же геометрии: карточки не прыгают, когда придут. */
export function PickerSkeleton() {
  return (
    <ul className="grid grid-cols-2 gap-2.5 sm:grid-cols-3 lg:grid-cols-2" aria-hidden="true">
      {[0, 1, 2, 3, 4, 5].map((i) => (
        <li key={i} className={vx(VS_CARD, "overflow-hidden")}>
          <FilmBlock className="aspect-video" />
          <div className="space-y-2 p-2.5">
            <div className={vx("h-2.5 w-3/4 rounded-full", CS_SKELETON)} />
            <div className={vx("h-11 w-full rounded-full md:h-9", CS_SKELETON)} />
          </div>
        </li>
      ))}
    </ul>
  );
}
