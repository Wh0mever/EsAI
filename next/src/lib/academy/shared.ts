/**
 * EsAI Академия: общее для страницы /academy, её SEO-блока в HTML с сервера и
 * превью карточки в панели. Модуль чистый — без React, сети и алиасов «@/»:
 * его проверяет shared.test.mjs обычным Node.
 *
 * Публичный API (core/academy, CONTRACT_ACADEMY §1) отдаёт ВСЕ опубликованные
 * курсы одним ответом: один ключ кэша fetch на весь сайт, сколько бы разных
 * ?page= ни перебирали. По 9 на страницу режет Next — здесь (paginate).
 */

export const ACADEMY_PATH = "/academy";
/** Карточек на странице — ТЗ; сервер присылает то же число в page_size. */
export const PAGE_SIZE = 9;

// Метаданные — дословно ТЗ, на всех языках одни: адрес у языков общий, как у всего сайта.
export const ACADEMY_TITLE = "EsAI Академия — курсы по созданию AI-контента";
export const ACADEMY_DESCRIPTION =
  "Обучение созданию AI-видео, мультфильмов, сериалов и изображений с помощью нейросетей. Курсы от авторов и экспертов в EsAI Академии.";

/**
 * rel внешних ссылок — один на карточку, SEO-блок и «Предложить курс». Если места
 * в Академии станут платными, Google требует sponsored — поменять только здесь.
 */
export const EXTERNAL_REL = "noopener noreferrer";

/**
 * Русские тексты страницы (ТЗ дословно). Это и defaultValue у t(), и запасной
 * текст SEO-блока; ru/academy.json обязан совпадать с ними байт в байт — это
 * проверяет shared.test.mjs.
 */
export const ACADEMY_RU = {
  "hero.title": "EsAI Academy — обучение созданию AI-контента",
  "hero.subtitle":
    "Курсы от авторов и экспертов. Учитесь создавать AI-видео, мультфильмы, сериалы и изображения с помощью нейросетей.",
  "trust.title": "EsAI Академия — учитесь создавать AI-контент у авторов, которые знают своё дело.",
  "trust.text": "Мы собираем курсы по нейросетям от авторов и практиков, чтобы вам было проще найти подходящее обучение.",
  "trust.authors.title": "Проверенные авторы",
  "trust.authors.text": "Отбираем преподавателей, специализирующихся на создании AI-контента.",
  "trust.practice.title": "Практическое обучение",
  "trust.practice.text": "Курсы по созданию AI-видео, мультфильмов, сериалов и другого контента.",
  "trust.direct.title": "Прямой переход к автору",
  "trust.direct.text": "Подробности, стоимость и условия обучения доступны на сайте преподавателя.",
  "catalog.heading": "Курсы",
  "card.teacher": "Преподаватель:",
  "card.cta": "Перейти к курсу",
  "card.new_tab": "(откроется в новой вкладке)",
  "pager.label": "Страницы курсов",
  "pager.prev": "Назад",
  "pager.next": "Вперёд",
  "pager.page": "Страница {{page}}",
  "empty.title": "Курсы скоро появятся",
  "empty.text": "Мы отбираем первых авторов. Загляните чуть позже.",
  "missing.title": "На этой странице курсов нет.",
  "missing.link": "К первой странице",
  "error.title": "Не удалось загрузить курсы.",
  "error.retry": "Обновить страницу",
  "suggest.title": "Хотите добавить свой курс в EsAI Академию?",
  "suggest.text": "Мы открыты к сотрудничеству с авторами и преподавателями, которые обучают созданию AI-контента.",
  "suggest.cta": "Предложить курс",
  "breadcrumb.home": "Главная",
  "breadcrumb.academy": "EsAI Академия",
} as const;

export type AcademyKey = keyof typeof ACADEMY_RU;

/** Строка словаря academy.json по ключу «a.b»; нет такой (или не строка) — русский текст. */
export function academyText(dict: unknown, key: AcademyKey): string {
  let node: unknown = dict;
  for (const part of key.split(".")) {
    node = node && typeof node === "object" && !Array.isArray(node) ? (node as Record<string, unknown>)[part] : undefined;
  }
  return typeof node === "string" && node.trim() ? node : ACADEMY_RU[key];
}

/** Подстановка {{name}} — для SEO-блока, где нет i18next. */
export const fill = (text: string, vars: Record<string, string | number>): string =>
  text.replace(/\{\{(\w+)\}\}/g, (all, name: string) => (name in vars ? String(vars[name]) : all));

/* ------------------------------------------------------------------ */
/* Курсы                                                               */
/* ------------------------------------------------------------------ */

export type AcademyCourse = {
  id: number;
  title: string;
  teacher: string;
  description: string;
  /** Только http/https — проверено и сервером, и здесь (safeExternalUrl). */
  url: string;
  cover: string | null;
  /** Лёгкая копия 480 px; нет — карточка берёт cover. */
  coverThumb: string | null;
  coverWidth: number | null;
  coverHeight: number | null;
};

export type AcademyCatalog = {
  courses: AcademyCourse[];
  /** Ссылка «Предложить курс»; null — кнопки нет (текст блока остаётся, ТЗ). */
  suggestUrl: string | null;
  pageSize: number;
};

type Row = Record<string, unknown>;
const isRow = (v: unknown): v is Row => typeof v === "object" && v !== null && !Array.isArray(v);
const text = (v: unknown): string => (typeof v === "string" ? v.trim() : "");
const positiveInt = (v: unknown): number | null =>
  typeof v === "number" && Number.isInteger(v) && v > 0 ? v : null;

/**
 * Внешняя ссылка, которую можно поставить в href: только http(s) с хостом.
 * javascript:, data:, относительные и битые адреса → null (карточка не рисуется).
 */
export function safeExternalUrl(raw: unknown): string | null {
  const value = text(raw);
  if (!value || /[\s\\]/.test(value)) return null;
  try {
    const url = new URL(value);
    if (url.protocol !== "http:" && url.protocol !== "https:") return null;
    if (!url.hostname || url.username || url.password) return null;
    return url.href;
  } catch {
    return null;
  }
}

/** Адрес картинки: свой путь от корня (/media/…) или http(s); «//чужой.хост» и схемы вроде data: — нет. */
export function safeMediaPath(raw: unknown): string | null {
  const value = text(raw);
  if (!value || /[\s\\"'<>]/.test(value)) return null;
  if (value.startsWith("/") && !value.startsWith("//")) return value;
  return safeExternalUrl(value);
}

function parseCourse(value: unknown): AcademyCourse | null {
  if (!isRow(value)) return null;
  const id = positiveInt(value.id);
  const title = text(value.title);
  const url = safeExternalUrl(value.url);
  if (id === null || !title || !url) return null;
  const cover = safeMediaPath(value.cover);
  return {
    id,
    title,
    teacher: text(value.teacher),
    description: text(value.description),
    url,
    cover,
    coverThumb: cover ? safeMediaPath(value.cover_thumb) : null,
    coverWidth: positiveInt(value.cover_width),
    coverHeight: positiveInt(value.cover_height),
  };
}

/**
 * Ответ GET /api/academy/courses/ — разбор как «чужие руки»: строка без номера,
 * названия или годной ссылки страницу не роняет, а просто не показывается.
 * null — ответил не API (страница ошибки, не JSON).
 */
export function parseCatalog(payload: unknown): AcademyCatalog | null {
  if (!isRow(payload) || !Array.isArray(payload.results)) return null;
  const seen = new Set<number>();
  const courses: AcademyCourse[] = [];
  for (const row of payload.results) {
    const course = parseCourse(row);
    if (!course || seen.has(course.id)) continue;
    seen.add(course.id);
    courses.push(course);
  }
  const size = positiveInt(payload.page_size);
  return {
    courses,
    suggestUrl: safeExternalUrl(payload.suggest_url),
    pageSize: size !== null && size <= 60 ? size : PAGE_SIZE,
  };
}

/* ------------------------------------------------------------------ */
/* Страницы                                                            */
/* ------------------------------------------------------------------ */

/** Самый большой номер, который принимаем как номер: дальше — мусор, то есть первая страница. */
const MAX_PAGE_PARAM = 1_000_000;

/**
 * ?page= из searchParams страницы. Номер — только целое ≥ 1 записанное цифрами;
 * мусор («abc», «0», «-1», «1.5», пусто, повтор ?page=2&page=3) — первая
 * страница: у неё свой canonical /academy, дублей в индексе не будет.
 */
export function pageFromParam(raw: string | string[] | null | undefined): number {
  if (typeof raw !== "string") return 1;
  const value = raw.trim();
  if (!/^\d{1,7}$/.test(value)) return 1;
  const page = Number(value);
  return page >= 1 && page <= MAX_PAGE_PARAM ? page : 1;
}

/** То же из строки адреса («?page=3&utm=…») — для SEO-блока корневого layout, где searchParams нет. */
export function pageFromSearch(search: string | null | undefined): number {
  let params: URLSearchParams;
  try {
    params = new URLSearchParams(search || "");
  } catch {
    return 1;
  }
  const all = params.getAll("page");
  return all.length === 1 ? pageFromParam(all[0]) : 1;
}

/** Ссылка на страницу каталога; первая — без ?page=1, как её canonical. */
export const pageHref = (page: number): string => (page > 1 ? `${ACADEMY_PATH}?page=${page}` : ACADEMY_PATH);

export const pageCount = (total: number, size: number = PAGE_SIZE): number =>
  Math.max(1, Math.ceil(Math.max(0, total) / Math.max(1, size)));

export type AcademyPageView = {
  courses: AcademyCourse[];
  page: number;
  pages: number;
  total: number;
  /**
   * Номер за последней страницей: «страницы нет», noindex без canonical. При пустом
   * каталоге тоже (страница сама покажет пустое состояние) — иначе /academy?page=5
   * была бы индексируемой копией пустой первой с canonical на себя.
   */
  outOfRange: boolean;
  /** Место первой карточки страницы во всём каталоге (с 1) — для ItemList. */
  firstPosition: number;
};

export function paginate(courses: readonly AcademyCourse[], page: number, size: number = PAGE_SIZE): AcademyPageView {
  const total = courses.length;
  const pages = pageCount(total, size);
  const start = (page - 1) * size;
  const outOfRange = page > pages;
  return {
    courses: outOfRange ? [] : courses.slice(start, start + size),
    page,
    pages,
    total,
    outOfRange,
    firstPosition: start + 1,
  };
}

export type PagerItem = { kind: "page"; page: number; current: boolean } | { kind: "gap"; key: string };

/**
 * Номера под каталогом: до 7 страниц — все; дальше — первая, последняя и
 * соседи текущей с «…» между ними («1 … 4 5 6 … 12»). Число элементов
 * постоянное (7), чтобы ряд не прыгал при листании.
 */
export function pagerItems(current: number, total: number): PagerItem[] {
  const pages = Math.max(1, Math.floor(total));
  const at = (page: number): PagerItem => ({ kind: "page", page, current: page === current });
  if (pages <= 7) return Array.from({ length: pages }, (_, i) => at(i + 1));
  const middle = Math.min(Math.max(current, 1), pages);
  let list: (number | "gap")[];
  if (middle <= 4) list = [1, 2, 3, 4, 5, "gap", pages];
  else if (middle >= pages - 3) list = [1, "gap", pages - 4, pages - 3, pages - 2, pages - 1, pages];
  else list = [1, "gap", middle - 1, middle, middle + 1, "gap", pages];
  return list.map((item, i) => (item === "gap" ? { kind: "gap", key: `gap-${i}` } : at(item)));
}

/* ------------------------------------------------------------------ */
/* Разметка для поисковиков                                            */
/* ------------------------------------------------------------------ */

/** ItemList курсов страницы: места — сквозные по каталогу, ссылки — на сайты авторов. */
export function courseListJsonLd(view: AcademyPageView) {
  return {
    "@context": "https://schema.org",
    "@type": "ItemList",
    numberOfItems: view.total,
    itemListElement: view.courses.map((course, i) => ({
      "@type": "ListItem",
      position: view.firstPosition + i,
      name: course.title,
      url: course.url,
    })),
  };
}
