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

/**
 * Что стоит под приглашением для авторов. url — кнопка «Предложить курс» на сайт
 * (новая вкладка); email — та же кнопка письмом, а под ней сам адрес: почтовой
 * программы у человека может не быть; text — без кнопки, текст абзацем.
 * href бывает только http:, https: или mailto: — его собирают функции ниже.
 */
export type AcademySuggest =
  | { kind: "url"; text: string; href: string }
  | { kind: "email"; text: string; href: string }
  | { kind: "text"; text: string; href: null };

export type AcademyCatalog = {
  courses: AcademyCourse[];
  /**
   * Блок «Предложить курс»; null — под приглашением ничего (текст блока остаётся, ТЗ).
   * Имя поля осталось от времён, когда тут была только ссылка: так его передаёт
   * app/academy/page.tsx.
   */
  suggestUrl: AcademySuggest | null;
  pageSize: number;
};

type Row = Record<string, unknown>;
const isRow = (v: unknown): v is Row => typeof v === "object" && v !== null && !Array.isArray(v);
const text = (v: unknown): string => (typeof v === "string" ? v.trim() : "");
const positiveInt = (v: unknown): number | null =>
  typeof v === "number" && Number.isInteger(v) && v > 0 ? v : null;

// Невидимые знаки и переключатели направления (Cc, Cf, Zl, Zp): ссылка или адрес
// выглядели бы не тем, куда ведут. Через конструктор: \p{…} в литерале требует цели ES2018.
const HIDDEN = new RegExp("[\\p{Cc}\\p{Cf}\\p{Zl}\\p{Zp}]", "u");
// Точки, которыми и браузер, и сервер (Python) делят имя хоста на метки.
const IDNA_DOTS = /[.\u3002\uff0e\uff61]/g;

/**
 * NFKC делает в имени точку из «не точки» (U+2024 → «.», U+2488 → «1.», U+FE12 → U+3002): сервер
 * (core/academy/links._nfkc_dots) видит другой хост, чем написан, а браузер такой адрес не
 * открывает (старый — открывает другой). Ссылкой или адресом почты такое не считаем.
 */
export function nfkcAddsDots(value: string): boolean {
  return (value.normalize("NFKC").match(IDNA_DOTS)?.length ?? 0) !== (value.match(IDNA_DOTS)?.length ?? 0);
}

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
    // Сервер после F28 присылает suggest (вид и текст; null — ничего), до него — только
    // suggest_url: страница понимает оба, в каком бы порядке ни выкладывали сайт и сервер.
    suggestUrl: "suggest" in payload ? parseSuggest(payload.suggest) : suggestFromUrl(payload.suggest_url),
    pageSize: size !== null && size <= 60 ? size : PAGE_SIZE,
  };
}

/* ------------------------------------------------------------------ */
/* «Предложить курс»: ссылка, e-mail или текст                         */
/* ------------------------------------------------------------------ */

// Адрес почты — как у сервера (core/academy/links._email): имя из букв любой азбуки,
// цифр, «_», «+», «-» и точек между ними; домен может быть кириллическим.
const EMAIL_LOCAL = new RegExp("^[\\p{L}\\p{N}_+-]+(?:\\.[\\p{L}\\p{N}_+-]+)*$", "u");
const EMAIL_DOMAIN = new RegExp("^[\\p{L}\\p{N}\\p{M}.-]+$", "u");
const ASCII_LABEL = /^(?!-)[a-z0-9-]{1,63}$/;
const ASCII_TLD = /^(?:[a-z]{2,63}|xn--[a-z0-9-]{1,59})$/;

export type EmailLink = { address: string; href: string };

/**
 * Строка — ровно адрес почты name@domain.tld: сам адрес и mailto: для него; иначе null.
 * В href домен в punycode (его понимает любая почтовая программа), имя — %-кодом
 * с «+» как есть: так же собирает сервер. «?», «#», «&» параметрами письма не станут.
 */
export function emailLink(raw: unknown): EmailLink | null {
  const address = text(raw);
  const at = address.lastIndexOf("@");
  if (at <= 0 || address.length > 254 || HIDDEN.test(address)) return null;
  const local = address.slice(0, at);
  const domain = address.slice(at + 1);
  if (local.length > 64 || !EMAIL_LOCAL.test(local) || !EMAIL_DOMAIN.test(domain) || domain.endsWith(".")) return null;
  // ß/ς браузер и сервер переводят в разные домены — сервер такой адрес не принимает.
  if (/[ßẞς]/.test(domain) || nfkcAddsDots(domain)) return null;
  let ascii: string;
  try {
    ascii = new URL(`http://${domain}`).hostname;
  } catch {
    return null;
  }
  const labels = ascii.split(".");
  if (ascii.length > 253 || labels.length < 2 || !ASCII_TLD.test(labels[labels.length - 1])) return null;
  if (!labels.every((label) => ASCII_LABEL.test(label) && !label.endsWith("-"))) return null;
  return { address, href: `mailto:${encodeURIComponent(local).replace(/%2B/g, "+")}@${ascii}` };
}

/** Адрес из mailto:…; параметры (?subject=…) отбрасываем, как сервер. */
export function emailFromMailto(raw: unknown): EmailLink | null {
  const value = text(raw);
  if (!/^mailto:/i.test(value)) return null;
  let address: string;
  try {
    address = decodeURIComponent(value.slice("mailto:".length).split(/[?#]/, 1)[0]);
  } catch {
    return null;
  }
  // Пробел по краям (mailto:%20a@b.kg) сервер адресом не считает — emailLink его бы срезал.
  return address === address.trim() ? emailLink(address) : null;
}

const IPV4 = /^(?:(?:25[0-5]|2[0-4]\d|1\d\d|[1-9]?\d)\.){3}(?:25[0-5]|2[0-4]\d|1\d\d|[1-9]?\d)$/;
const NUMERIC_TOP = /^(?:\d+|0x[0-9a-f]*)$/i;
// Метка хоста после punycode: браузер пускает и «_», и «-» по краям; прочее (!, $…) сервер не примет.
const OPEN_LABEL = /^[a-z0-9_-]{1,63}$/;

/**
 * Ссылка для href кнопки или ссылки в тексте: http(s):// с хостом — тем, что
 * написан (как links._open_link: любой сайт, localhost и IP тоже). Логин в адресе
 * («https://esai.kg@evil.com» откроется на evil.com — фишинговый приём), «%» в
 * хосте, ß/ς и числовые формы вроде 127.1 или 0x7f.1 браузер переписал бы молча и
 * открыл не то, что видит человек, — поэтому смотрим на написанное, до разбора.
 */
export function safeLinkHref(raw: unknown): string | null {
  const value = text(raw);
  const scheme = /^https?:\/\//i.exec(value);
  if (!scheme || HIDDEN.test(value)) return null;
  const authority = value.slice(scheme[0].length).split(/[/?#]/, 1)[0];
  // Пустой хост («https:///evil.com») парсер молча чинит в evil.com — сервер такую ссылку не берёт.
  if (!authority || /[@%ßẞς]/.test(authority) || nfkcAddsDots(authority)) return null;
  const href = safeExternalUrl(value);
  if (!href) return null;
  const url = new URL(href);
  if (url.port === "0" || url.hostname.length > 253) return null;
  // IPv6 в скобках парсер уже проверил; IPv4 — только обычной записью a.b.c.d.
  if (authority.startsWith("[")) return href;
  const host = authority.split(":", 1)[0].replace(/\.$/, "");
  // «example.com。»: браузер читает «。» как точку в конце, а сервер срезает только «.» — и отказывает.
  if (/[.\u3002\uff0e\uff61]$/.test(host)) return null;
  if (IPV4.test(host)) return href;
  if (NUMERIC_TOP.test(host.slice(host.lastIndexOf(".") + 1))) return null;
  return url.hostname.replace(/\.$/, "").split(".").every((label) => OPEN_LABEL.test(label)) ? href : null;
}

/** Строк в тексте блока не больше — лишние склеиваются в последнюю через пробел (как на сервере). */
export const SUGGEST_TEXT_LINES = 5;

const HIDDEN_ALL = new RegExp(HIDDEN.source, "gu");

/**
 * Текст блока так, как его хранит сервер (links._plain_text): пробелы в строке
 * схлопнуты, пустые строки убраны, строк не больше пяти. Сервер присылает уже
 * чистый текст — здесь страховка от правки мимо панели (и невидимые знаки прочь).
 */
export function suggestText(raw: unknown): string {
  if (typeof raw !== "string") return "";
  const source = raw.replace(/\r\n?/g, "\n").replace(HIDDEN_ALL, (ch) => (ch === "\n" ? ch : ch === "\t" ? " " : ""));
  const lines = source
    .split("\n")
    .map((line) => line.replace(/\s+/g, " ").trim())
    .filter(Boolean);
  if (lines.length > SUGGEST_TEXT_LINES) lines.push(lines.splice(SUGGEST_TEXT_LINES - 1).join(" "));
  return lines.join("\n");
}

export type SuggestPart = { kind: "text"; text: string } | { kind: "url" | "email"; text: string; href: string };

// Кандидаты в ссылки внутри текста: http(s)://… до пробела или кавычки и адреса почты.
// Без lookbehind: в Safari до 16.4 такой RegExp не создаётся вовсе и уронил бы страницу.
const LINK_CANDIDATE = new RegExp(
  "(https?:\\/\\/[^\\s<>\"«»]+)|([\\p{L}\\p{N}_.+-]+@[\\p{L}\\p{N}\\p{M}-]+(?:\\.[\\p{L}\\p{N}\\p{M}-]+)+)",
  "giu",
);
// Сервер хранит ≤ 300 символов (≤ 600 половинок UTF-16). Разбор ниже растёт быстрее длины:
// 100 000 знаков — секунды, поэтому длинное (не от нашего сервера) остаётся просто текстом.
const PARTS_MAX = 1000;
const URL_TAIL = ".,;:!?'…";
const URL_PAIRS: Record<string, string> = { ")": "(", "]": "[", "}": "{" };
const countOf = (value: string, ch: string): number => value.split(ch).length - 1;

/** Знаки после ссылки — не часть адреса: «форма: https://x.kg/form.», «(см. https://x.kg)». */
function trimUrlTail(candidate: string): string {
  let value = candidate;
  while (value) {
    const last = value[value.length - 1];
    const open = URL_PAIRS[last];
    if (!URL_TAIL.includes(last) && !(open && countOf(value, open) < countOf(value, last))) break;
    value = value.slice(0, -1);
  }
  return value;
}

/**
 * Текст блока по кускам: обычный текст, ссылки и адреса почты. Ссылка проходит
 * ту же проверку, что кнопка (safeLinkHref); не прошла — остаётся текстом. href
 * собирается только здесь и бывает только http:, https: или mailto:.
 */
export function suggestParts(raw: string): SuggestPart[] {
  if (raw.length > PARTS_MAX) return [{ kind: "text", text: raw }];
  const parts: SuggestPart[] = [];
  const pushText = (value: string) => {
    if (!value) return;
    const last = parts[parts.length - 1];
    if (last && last.kind === "text") last.text += value;
    else parts.push({ kind: "text", text: value });
  };
  let at = 0;
  for (const match of raw.matchAll(LINK_CANDIDATE)) {
    const start = match.index ?? 0;
    let found = match[0];
    let link: SuggestPart | null = null;
    if (match[1]) {
      found = trimUrlTail(found);
      const href = safeLinkHref(found);
      if (href) link = { kind: "url", text: found, href };
    } else {
      const email = emailLink(found);
      if (email) link = { kind: "email", text: email.address, href: email.href };
    }
    pushText(raw.slice(at, start));
    if (link) parts.push(link);
    else pushText(found);
    at = start + found.length;
  }
  pushText(raw.slice(at));
  return parts;
}

/** Объект suggest из ответа API; не разобрать (неизвестный вид, опасный href) — null, на сайте ничего. */
export function parseSuggest(value: unknown): AcademySuggest | null {
  if (!isRow(value)) return null;
  if (value.kind === "url") {
    const href = safeLinkHref(value.href);
    return href ? { kind: "url", text: text(value.text) || href, href } : null;
  }
  if (value.kind === "email") {
    // href собираем сами из проверенного адреса, а не берём готовый.
    const email = emailLink(value.text) ?? emailFromMailto(value.href);
    return email ? { kind: "email", text: email.address, href: email.href } : null;
  }
  if (value.kind === "text") {
    const body = suggestText(value.text);
    return body ? { kind: "text", text: body, href: null } : null;
  }
  return null;
}

/** Старое поле suggest_url: ссылка (как до F28) или mailto: — у письма сервер кладёт туда его href. */
export function suggestFromUrl(raw: unknown): AcademySuggest | null {
  const email = emailFromMailto(raw);
  if (email) return { kind: "email", text: email.address, href: email.href };
  const href = safeLinkHref(raw);
  return href ? { kind: "url", text: text(raw), href } : null;
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
