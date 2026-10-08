"use client";

import { useEffect, useId, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { FiChevronDown } from "react-icons/fi";
import { VS_BTN_GHOST, VS_H2, VS_SECTION, VS_SECTION_GAP, VS_SUB, vx } from "../ui/skin";
import { useCanHover } from "../ui/useAutoplayAllowed";
import { useReveal } from "../ui/useReveal";
import GalleryCard, { GALLERY_GRID } from "./gallery/GalleryCard";
import GallerySkeleton from "./gallery/GallerySkeleton";
import GalleryTabs, { tabDomId, type GalleryTabView } from "./gallery/GalleryTabs";
import {
  TAB_ALL,
  TAB_STUDIO,
  cardAction,
  currentTab,
  galleryMix,
  galleryTabs,
  pageLimit,
  revealDelay,
  tabItems,
} from "./gallery/galleryModel";
import { useGridCols } from "./gallery/useGridCols";
import { useHeightHold } from "./gallery/useHeightHold";
import type { ReelCategory, ReelItem } from "./useShowreel";

export type ShowcaseGalleryProps = {
  /** Вся витрина: работы видеостудии, затем сцены мультстудии. */
  items: ReelItem[];
  /** Разделы мультстудии со счётчиками, от самых полных (вкладки отбирает галерея). */
  categories: ReelCategory[];
  /** Есть ли работы самой видеостудии (вкладка «Видеостудия» и подзаголовок). */
  hasStudio: boolean;
  loading: boolean;
  /** Нажата карточка; смысл нажатия знает StudioHome, переход в мультстудию делает ссылка. */
  onUse: (item: ReelItem) => void;
};

/**
 * «Сделано в EsAI» (§2.2): настоящие ролики — работы видеостудии и сцены
 * мультстудии, каждая подписана своим источником. Вкладки отбирают, сетка
 * показывает порциями: 150 сцен разом — это 150 постеров на мобильной сети.
 *
 * Ролик в карточке заводит LazyClip: под курсором, а где курсора нет — когда
 * карточка на экране; сколько играет одновременно, решает общий бюджет
 * первого экрана. По нажатию ничего не запускается: сцена мультстудии ведёт
 * в /studio, работа видеостудии готовит панель запроса (это делает StudioHome).
 */
export default function ShowcaseGallery({ items, categories, hasStudio, loading, onUse }: ShowcaseGalleryProps) {
  const { t } = useTranslation("vstudio", { useSuspense: false });
  const reveal = useReveal<HTMLElement>();
  const canHover = useCanHover();
  const cols = useGridCols();
  const uid = useId();
  const titleId = `${uid}-title`;
  const panelId = `${uid}-panel`;

  const [wanted, setWanted] = useState(TAB_ALL);
  const [extraPages, setExtraPages] = useState(0);
  const { boxRef, contentRef, minHeight, capture } = useHeightHold();
  const gridRef = useRef<HTMLUListElement>(null);
  // С какой карточки начинается порция, открытая «Показать ещё»: туда уйдёт фокус.
  const focusFrom = useRef<number | null>(null);

  const tabs = useMemo(() => galleryTabs(items, categories, hasStudio), [items, categories, hasStudio]);
  const tab = currentTab(tabs, wanted);
  const list = useMemo(() => tabItems(items, tab), [items, tab]);
  const limit = pageLimit(cols, extraPages);
  const shown = useMemo(() => list.slice(0, limit), [list, limit]);
  const more = list.length > shown.length;

  const allLabel = t("home.showcase.all", { defaultValue: "Все" });
  const studioLabel = t("home.showcase.studio", { defaultValue: "Видеостудия" });
  const cartoonLabel = t("home.showcase.cartoon", { defaultValue: "Мультстудия" });
  const tabViews = useMemo<GalleryTabView[]>(
    // Без своего названия — только «Все» и «Видеостудия»; разделы мультстудии называет сервер.
    () => tabs.map(({ id, title }) => ({ id, title: title ?? (id === TAB_STUDIO ? studioLabel : allLabel) })),
    [tabs, allLabel, studioLabel],
  );

  useEffect(() => {
    const from = focusFrom.current;
    if (from === null) return;
    focusFrom.current = null;
    // Новые карточки стоят в разметке перед кнопкой: без этого Tab с неё пролетел бы мимо них.
    // Страницу не двигаем — первая из новых появляется там, где была кнопка.
    gridRef.current?.querySelectorAll<HTMLElement>("[data-vs-card]")[from]?.focus({ preventScroll: true });
  }, [extraPages]);

  if (!loading && items.length === 0) return null;
  const busy = loading && items.length === 0;

  const selectTab = (id: string) => {
    if (id === tab) return;
    // До смены содержимого: короткая вкладка иначе дёрнула бы страницу под курсором.
    capture();
    setWanted(id);
    setExtraPages(0);
  };

  const showMore = () => {
    focusFrom.current = shown.length;
    setExtraPages((n) => n + 1);
  };

  const mix = galleryMix(items, hasStudio);
  const sub =
    mix === "mixed"
      ? t("home.showcase.subMixed", { defaultValue: "Работы из видеостудии и сцены мультстудии" })
      : mix === "studio"
        ? t("home.showcase.subStudio", { defaultValue: "Работы, снятые в видеостудии EsAI" })
        : t("home.showcase.subCartoon", {
            defaultValue: "Сцены мультстудии EsAI — каждую можно снять со своим героем",
          });

  const actions = {
    scene: t("home.showcase.useScene", { defaultValue: "Снять такую сцену" }),
    similar: t("home.showcase.useSimilar", { defaultValue: "Снять похожее" }),
    model: t("home.showcase.useModel", { defaultValue: "Выбрать эту модель" }),
  };
  const untitledScene = t("home.showcase.untitledScene", { defaultValue: "Сцена мультстудии" });
  const untitledWork = t("home.showcase.untitledWork", { defaultValue: "Работа из видеостудии" });

  const tabbed = tabViews.length > 0;
  const tabIndex = Math.max(
    0,
    tabViews.findIndex((view) => view.id === tab),
  );

  return (
    <section
      ref={reveal}
      aria-labelledby={titleId}
      aria-busy={busy}
      className={vx(VS_SECTION, VS_SECTION_GAP, "vs-reveal")}
    >
      <h2 id={titleId} className={VS_H2}>
        {t("home.showcase.title", { defaultValue: "Сделано в EsAI" })}
      </h2>

      {busy ? (
        <>
          <div aria-hidden className="mt-1.5 flex h-5 items-center">
            {/* На светлой сцене та же доля «чернил» почти не видна — там полоска чуть плотнее. */}
            <span className="h-3 w-64 max-w-full rounded-full bg-vs-ink/[0.07] dark:bg-vs-ink/[0.05]" />
          </div>
          <GallerySkeleton count={pageLimit(cols, 0)} />
        </>
      ) : (
        <>
          <p className={vx(VS_SUB, "mt-1.5")}>{sub}</p>

          {tabbed && (
            <GalleryTabs
              tabs={tabViews}
              active={tab}
              onSelect={selectTab}
              idBase={uid}
              panelId={panelId}
              label={t("home.showcase.tabsLabel", { defaultValue: "Разделы витрины" })}
              arrows={canHover}
              prevLabel={t("home.showcase.tabsPrev", { defaultValue: "Прокрутить разделы назад" })}
              nextLabel={t("home.showcase.tabsNext", { defaultValue: "Прокрутить разделы вперёд" })}
              className="mt-5"
            />
          )}

          <div
            ref={boxRef}
            id={panelId}
            role={tabbed ? "tabpanel" : undefined}
            aria-labelledby={tabbed ? tabDomId(uid, tabIndex) : undefined}
            style={{ minHeight }}
            className="mt-5"
          >
            <div ref={contentRef}>
              {/* Ключ по вкладке: карточки новой вкладки выходят заново, а не подменяются на месте. */}
              <ul key={tab} ref={gridRef} className={GALLERY_GRID}>
                {shown.map((item, index) => {
                  const cartoon = item.source === "cartoon";
                  return (
                    <GalleryCard
                      key={item.id}
                      item={item}
                      title={item.title || (cartoon ? untitledScene : untitledWork)}
                      source={cartoon ? cartoonLabel : studioLabel}
                      action={actions[cardAction(item)]}
                      hover={canHover}
                      delayMs={revealDelay(index, cols)}
                      onUse={onUse}
                    />
                  );
                })}
              </ul>

              {more && (
                <div className="mt-8 flex flex-col items-center gap-2.5">
                  <button type="button" onClick={showMore} className={VS_BTN_GHOST}>
                    {t("home.showcase.more", { defaultValue: "Показать ещё" })}
                    <FiChevronDown aria-hidden className="text-base" />
                  </button>
                  <p aria-live="polite" className="text-[11px] tabular-nums text-muted">
                    {t("home.showcase.shown", {
                      defaultValue: "Показано {{shown}} из {{total}}",
                      shown: shown.length,
                      total: list.length,
                    })}
                  </p>
                </div>
              )}
            </div>
          </div>
        </>
      )}
    </section>
  );
}
