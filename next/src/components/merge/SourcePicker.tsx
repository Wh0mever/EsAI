"use client";

import { useId, useState, type KeyboardEvent } from "react";
import { useTranslation } from "react-i18next";
import {
  FiArrowUpRight,
  FiCheck,
  FiChevronDown,
  FiChevronsUp,
  FiFilm,
  FiLoader,
  FiPlus,
  FiRefreshCw,
  FiTrash2,
  FiX,
} from "react-icons/fi";
import Link from "next/link";
import { apiLang } from "@/lib/apiLang";
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
import type { TextSpec } from "./mergeLogic";
import FilmBlock from "@/components/studio/timeline/FilmBlock";
import MediaThumb from "./MediaThumb";
import { SOURCE_RU } from "./MergeTimeline";
import UploadPanel, { useUploadBadge, type UploadPanelProps } from "./UploadPanel";
import { TABS, VSTUDIO_NAV, addRefusal, fillText, formatDuration, type AddPlace, type AddRefusal } from "./mergeLogic";
import { formatMb, numberLocale, uploadExpiry } from "./uploadLogic";
import type { MergeLimits, MergeSourceCard, MergeTab } from "./mergeTypes";
import type { SourcesState } from "./useMerge";

/**
 * Выбор роликов для склейки: вкладки «Видеостудия / Мультстудия / Чат / Мои
 * файлы» и сетка готовых видео с длительностью и «+ Добавить» (в конец) или
 * «В начало». Один ролик можно добавить несколько раз — значок на карточке
 * говорит, сколько он уже стоит в склейке. Предел (30 фрагментов, 5 минут,
 * 3 своих видео) гасит кнопку с причиной. «Мои файлы» — ещё и загрузка своего
 * видео и его удаление.
 */

const TAB_RU: Record<MergeTab, string> = {
  vstudio: "Видеостудия",
  cartoon: "Мультстудия",
  chat: "Чат",
  upload: "Мои файлы",
};

/** «Мои файлы»: загрузка (UploadPanel) и удаление своих видео. */
export type PickerUploads = Omit<UploadPanelProps, "buttonId"> & {
  /** id видео, которые сейчас удаляются. */
  deleting: readonly string[];
  /** Почему не удалилось — показываем на той же карточке. */
  deleteError: { id: string; text: TextSpec } | null;
  onDismissDeleteError: () => void;
  onDelete: (card: MergeSourceCard) => void;
};

export type SourcePickerProps = {
  tab: MergeTab;
  sources: Record<MergeTab, SourcesState>;
  /** Уже в склейке: «тип:id» → сколько раз. */
  counts: Map<string, number>;
  items: { duration_s: number | null; type?: string }[];
  limits: MergeLimits;
  /** Своих видео в одной склейке. */
  maxUploads: number;
  onTab: (tab: MergeTab) => void;
  onAdd: (card: MergeSourceCard, place: AddPlace) => void;
  onMore: (tab: MergeTab) => void;
  onReload: (tab: MergeTab) => void;
  uploads: PickerUploads;
  /** id кнопки «Загрузить видео» — туда уходит фокус, когда удалённая карточка исчезла. */
  uploadButtonId: string;
  /** Заголовок секции (на компьютере — колонка слева, на телефоне — своя вкладка). */
  headingId: string;
};

export default function SourcePicker({
  tab,
  sources,
  counts,
  items,
  limits,
  maxUploads,
  onTab,
  onAdd,
  onMore,
  onReload,
  uploads,
  uploadButtonId,
  headingId,
}: SourcePickerProps) {
  const { t, i18n } = useTranslation("vstudio", { useSuspense: false });
  const panelId = useId();
  const state = sources[tab];
  const locale = numberLocale(apiLang(i18n.language));
  const tabLabel = (x: MergeTab) => t(`merge.tab.${x}`, { defaultValue: TAB_RU[x] });
  // Загрузка идёт сама по себе: открыта другая вкладка — ход и итог видны на ярлыке «Мои файлы».
  const badge = useUploadBadge(uploads.upload, Boolean(uploads.error));
  const uploadBadge = tab === "upload" ? null : badge;

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
          <h2 id={headingId} tabIndex={-1} className="text-base font-semibold text-foreground focus:outline-none">
            {t("merge.picker.title", { defaultValue: "Ваши видео" })}
          </h2>
          <p className={vx(VS_SUB, "mt-0.5 text-[13px]")}>
            {t("merge.picker.sub", { defaultValue: "Готовые ролики из студий и чата или свои файлы" })}
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

      {/* Четыре вкладки в ряд не помещаются в узкую колонку (телефон, колонка с 1024 px) — там два ряда. */}
      <div
        role="tablist"
        aria-label={t("merge.picker.tabs", { defaultValue: "Откуда взять видео" })}
        className={vx("grid grid-cols-2 gap-1 rounded-[24px] p-1 sm:grid-cols-4 sm:rounded-full lg:grid-cols-2 lg:rounded-[24px]", VS_SEG_TRACK)}
      >
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
              {x === "upload" && uploadBadge && (
                <span className={vx("tabular-nums", uploadBadge.failed ? "text-status-fail" : "text-muted-2")}>
                  {` · ${uploadBadge.text}`}
                </span>
              )}
            </button>
          );
        })}
      </div>

      <div
        id={panelId}
        role="tabpanel"
        aria-labelledby={`${panelId}-tab-${tab}`}
        aria-busy={state.loading || undefined}
        className="flex flex-col gap-3"
      >
        {tab === "upload" && <UploadPanel {...uploads} buttonId={uploadButtonId} />}
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
          // У «Моих файлов» пустое место уже занимает зона загрузки.
          tab === "upload" ? null : <EmptyTab tab={tab} />
        ) : (
          <>
            <ul className="grid grid-cols-2 gap-2.5 sm:grid-cols-3 lg:grid-cols-2">
              {state.items.map((card) => {
                const count = counts.get(`${card.type}:${card.id}`) ?? 0;
                return (
                  <SourceCard
                    key={`${card.type}:${card.id}`}
                    card={card}
                    count={count}
                    refusal={addRefusal(items, card, limits, maxUploads)}
                    canStart={items.length > 0}
                    locale={locale}
                    onAdd={(place) => onAdd(card, place)}
                    deleting={card.type === "upload" && uploads.deleting.includes(card.id)}
                    deleteError={uploads.deleteError?.id === card.id ? uploads.deleteError.text : null}
                    onDismissDeleteError={uploads.onDismissDeleteError}
                    onDelete={
                      card.type === "upload"
                        ? () => {
                            const title = card.title.trim() || t("merge.untitled", { defaultValue: "Без названия" });
                            const ask =
                              count > 0
                                ? t("merge.upload.deleteConfirmUsed", {
                                    defaultValue: "Удалить видео «{{title}}»? Оно стоит в этой склейке — там станет недоступным.",
                                    title,
                                  })
                                : t("merge.upload.deleteConfirm", {
                                    defaultValue: "Удалить видео «{{title}}»? Вернуть его будет нельзя.",
                                    title,
                                  });
                            if (window.confirm(ask)) uploads.onDelete(card);
                          }
                        : undefined
                    }
                  />
                );
              })}
            </ul>
            {state.hasMore && (
              <button
                type="button"
                onClick={() => onMore(tab)}
                disabled={state.loading}
                className={vx(VS_BTN_GHOST, "mx-auto mt-1 flex")}
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
  canStart,
  locale,
  onAdd,
  deleting = false,
  deleteError = null,
  onDismissDeleteError,
  onDelete,
}: {
  card: MergeSourceCard;
  count: number;
  refusal: AddRefusal | null;
  /** «В начало» — только когда в склейке уже что-то есть: в пустую это то же, что «в конец». */
  canStart: boolean;
  locale: string;
  onAdd: (place: AddPlace) => void;
  deleting?: boolean;
  /** Почему своё видео не удалилось. */
  deleteError?: TextSpec | null;
  onDismissDeleteError?: () => void;
  /** Своё видео: «Удалить» на кадре. */
  onDelete?: () => void;
}) {
  const { t } = useTranslation("vstudio", { useSuspense: false });
  // Ролик играет прямо на карточке — корзина не закрывает угол плеера (там громкость на iPhone).
  const [playing, setPlaying] = useState(false);
  const title = card.title.trim() || t("merge.untitled", { defaultValue: "Без названия" });
  const vertical = Boolean(card.width && card.height && card.height > card.width);
  // Почему добавить нельзя: коротко на кнопке, полностью — в подсказке и для диктора.
  let off: { short: string; full: string } | null = null;
  if (refusal?.code === "too_many_fragments") {
    off = {
      short: t("merge.picker.full", { defaultValue: "Уже {{max}}", max: refusal.max }),
      full: t("merge.err.too_many_fragments", { defaultValue: "Можно склеить не больше {{max}} фрагментов.", max: refusal.max }),
    };
  } else if (refusal?.code === "too_many_uploads") {
    off = {
      short: t("merge.picker.uploadsFull", { defaultValue: "Уже {{max}} своих", max: refusal.max }),
      full: t("merge.err.too_many_uploads", { defaultValue: "В одной склейке — не больше {{max}} своих видео.", max: refusal.max }),
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
  const toEnd = t("merge.picker.toEndHint", { defaultValue: "Добавить в конец склейки" });
  const startLabel = t("merge.picker.toStart", { defaultValue: "В начало" });
  const toStart = t("merge.picker.toStartHint", { defaultValue: "Добавить в начало склейки" });
  const inMerge = t("merge.picker.inMerge", { defaultValue: "В склейке: {{n}}", n: count });
  const deleteLabel = t("merge.upload.delete", { defaultValue: "Удалить видео" });
  // Своё видео: вместо подписи — размер, «без звука» (склеится с тишиной) и до какого числа хранится.
  const facts =
    card.type === "upload"
      ? [
          typeof card.size_bytes === "number" ? t("merge.upload.size", { defaultValue: "{{n}} МБ", n: formatMb(card.size_bytes, locale) }) : "",
          card.has_audio === false ? t("merge.upload.noAudio", { defaultValue: "без звука" }) : "",
        ]
          .filter(Boolean)
          .join(" · ")
      : card.subtitle;
  const expiry = card.type === "upload" ? uploadExpiry(card.expires_at) : null;
  const deleteText = deleteError
    ? deleteError.key
      ? t(deleteError.key, { defaultValue: deleteError.ru, ...deleteError.params })
      : fillText(deleteError.ru, deleteError.params)
    : "";

  return (
    <li className={vx(VS_CARD, "flex min-w-0 flex-col overflow-hidden", deleting && "opacity-60")}>
      <div className="relative aspect-video">
        <MediaThumb poster={card.poster} url={card.url} title={title} vertical={vertical} onPlayingChange={setPlaying} />
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
        {onDelete && !playing && (
          // Поверх кадра — чёрно-белое в любой теме, как кнопка ▶.
          <button
            type="button"
            onClick={() => {
              if (!deleting) onDelete();
            }}
            aria-disabled={deleting || undefined}
            aria-label={`${deleteLabel}: ${title}`}
            title={deleteLabel}
            className={vx(
              "absolute right-1.5 top-1.5 grid size-9 cursor-pointer place-items-center rounded-full bg-black/55 text-white transition-colors hover:bg-black/75 hover:text-status-fail before:absolute before:-inset-1 motion-reduce:transition-none",
              VS_FOCUS,
            )}
          >
            {deleting ? (
              <FiLoader className="size-4 animate-spin motion-reduce:animate-none" aria-hidden="true" />
            ) : (
              <FiTrash2 className="size-4" aria-hidden="true" />
            )}
          </button>
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
        {(facts || expiry) && (
          <p className="truncate text-[11px] text-muted-2">
            {facts}
            {expiry && (
              // Черновик срок не продлевает: видео, которому осталось три дня, скоро станет недоступным.
              <span className={expiry.soon ? "text-status-wait" : undefined}>
                {facts ? " · " : ""}
                <span aria-hidden="true">{t("merge.upload.until", { defaultValue: "до {{date}}", date: expiry.date })}</span>
                <span className="sr-only">{t("merge.until", { defaultValue: "Хранится до {{date}}", date: expiry.date })}</span>
              </span>
            )}
          </p>
        )}
        {deleteText && (
          <div role="alert" className="flex items-start gap-1.5 text-[11px] leading-snug text-status-fail">
            <p className="min-w-0 flex-1 break-words">{deleteText}</p>
            <button
              type="button"
              onClick={onDismissDeleteError}
              aria-label={t("merge.closeError", { defaultValue: "Скрыть" })}
              title={t("merge.closeError", { defaultValue: "Скрыть" })}
              className={vx(
                "relative -mr-1 grid size-6 shrink-0 cursor-pointer place-items-center rounded-full hover:bg-status-fail/15 before:absolute before:-inset-2.5",
                VS_FOCUS,
              )}
            >
              <FiX className="size-3.5" aria-hidden="true" />
            </button>
          </div>
        )}
        {/* «+ Добавить» — в конец, главное действие; «В начало» — рядом: на телефоне и планшете с подписью,
            в узкой колонке компьютера (с 1024 px) значком. */}
        <div className="mt-auto flex min-w-0 flex-col gap-1.5 lg:flex-row">
          <button
            type="button"
            onClick={() => {
              if (!off) onAdd("end");
            }}
            aria-disabled={off ? true : undefined}
            title={off?.full ?? toEnd}
            className={vx(
              CS_CARD_BTN,
              "min-w-0 lg:flex-1",
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
          {!off && canStart && (
            <button
              type="button"
              onClick={() => onAdd("start")}
              title={toStart}
              className={vx(CS_CARD_BTN, "min-w-0 hover:!border-vs-accent/45 lg:!w-9 lg:shrink-0 lg:!px-0")}
            >
              <FiChevronsUp className="shrink-0 text-vs-accent" aria-hidden="true" />
              <span className="truncate lg:sr-only">{startLabel}</span>
              <span className="sr-only">: {title}</span>
            </button>
          )}
        </div>
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
