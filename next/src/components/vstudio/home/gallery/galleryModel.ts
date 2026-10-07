/**
 * Галерея «Сделано в EsAI» (§2.2): какие вкладки показать, что лежит в каждой
 * и сколько карточек видно до «Показать ещё».
 *
 * Модуль чистый (без React и DOM) — его проверяет node-тест gallery.test.mjs.
 */
import type { ReelCategory, ReelItem } from "../showreelData";

export const TAB_ALL = "all";
export const TAB_STUDIO = "studio";
/** Раздел мультстудии. С приставкой раздел по имени «all» или «studio» не спутается с нашими вкладками. */
const CATEGORY_PREFIX = "ct:";

/** Раздел короче — не вкладка: в нём не наберётся и ряда карточек. */
export const MIN_CATEGORY_ITEMS = 4;
export const MAX_CATEGORY_TABS = 8;

export const PAGE_SIZE = 12;
/** Первая порция: 12 карточек, на телефоне (сетка в две колонки) — 8. */
export const FIRST_PAGE = 12;
export const FIRST_PAGE_PHONE = 8;

/** Шаг задержки появления между соседними карточками ряда, мс (в сумме не больше 240). */
const REVEAL_STEP_MS = 60;

export type GalleryTab = {
  id: string;
  /** Название раздела мультстудии, как его прислал сервер; у «Все» и «Видеостудия» — null, их подписывает галерея. */
  title: string | null;
  count: number;
};

const isStudio = (item: ReelItem) => item.source === "vstudio";
const isCartoon = (item: ReelItem) => item.source === "cartoon";

/**
 * Вкладки: «Все», «Видеостудия» (если её работы есть), затем разделы
 * мультстудии — от самых полных. Если выбирать не из чего, список пуст и
 * галерея показывает сетку без вкладок.
 */
export function galleryTabs(items: ReelItem[], categories: ReelCategory[], hasStudio: boolean): GalleryTab[] {
  const tabs: GalleryTab[] = [{ id: TAB_ALL, title: null, count: items.length }];

  const studio = hasStudio ? items.filter(isStudio).length : 0;
  if (studio > 0) tabs.push({ id: TAB_STUDIO, title: null, count: studio });

  // Считаем по самим карточкам: вкладка обещает ровно то, что покажет сетка.
  const counts = new Map<string, number>();
  for (const item of items) {
    if (isCartoon(item) && item.category) counts.set(item.category, (counts.get(item.category) ?? 0) + 1);
  }
  const seen = new Set<string>();
  const sections: GalleryTab[] = [];
  for (const category of categories) {
    const count = counts.get(category.slug) ?? 0;
    if (count < MIN_CATEGORY_ITEMS || !category.title || seen.has(category.slug)) continue;
    seen.add(category.slug);
    sections.push({ id: CATEGORY_PREFIX + category.slug, title: category.title, count });
  }
  // Сортировка устойчивая: разделы с равным числом сцен остаются в порядке сервера.
  sections.sort((a, b) => b.count - a.count);
  tabs.push(...sections.slice(0, MAX_CATEGORY_TABS));

  // Вкладка, в которой лежит то же, что во «Все», ничего не отбирает.
  const useful = tabs.filter((tab) => tab.id === TAB_ALL || tab.count < items.length);
  return useful.length > 1 ? useful : [];
}

/** Выбранная вкладка могла исчезнуть (витрина обновилась, сменился язык) — тогда «Все». */
export function currentTab(tabs: GalleryTab[], wanted: string): string {
  return tabs.some((tab) => tab.id === wanted) ? wanted : TAB_ALL;
}

/** Карточки вкладки — в том же порядке, что и в общей витрине. */
export function tabItems(items: ReelItem[], tab: string): ReelItem[] {
  if (tab === TAB_STUDIO) return items.filter(isStudio);
  if (tab.startsWith(CATEGORY_PREFIX)) {
    const slug = tab.slice(CATEGORY_PREFIX.length);
    return items.filter((item) => isCartoon(item) && item.category === slug);
  }
  return items;
}

/** Сколько карточек видно: первая порция по ширине сетки и по 12 за каждое «Показать ещё». */
export function pageLimit(cols: number, extraPages: number): number {
  return (cols <= 2 ? FIRST_PAGE_PHONE : FIRST_PAGE) + Math.max(0, extraPages) * PAGE_SIZE;
}

/** Карточки ряда появляются по очереди слева направо. */
export function revealDelay(index: number, cols: number): number {
  return (index % Math.max(1, cols)) * REVEAL_STEP_MS;
}

/** Что в витрине — от этого зависит подзаголовок: обещать сцены мультстудии, когда их нет, нельзя. */
export type GalleryMix = "mixed" | "studio" | "cartoon";

export function galleryMix(items: ReelItem[], hasStudio: boolean): GalleryMix {
  if (!hasStudio) return "cartoon";
  return items.some(isCartoon) ? "mixed" : "studio";
}

/**
 * Что обещает карточка. Сцена мультстудии — снять такую же в /studio. Работа
 * видеостудии — «снять похожее»; но если её запрос скрыт, от неё останется
 * только модель, и подпись говорит об этом прямо (как в карусели).
 */
export type CardAction = "scene" | "similar" | "model";

export function cardAction(item: ReelItem): CardAction {
  if (isCartoon(item)) return "scene";
  return !item.prompt && item.modelId ? "model" : "similar";
}
