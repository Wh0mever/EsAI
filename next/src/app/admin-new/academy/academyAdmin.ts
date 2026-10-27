/**
 * EsAI Академия в панели: весь контракт с сервером — в этом файле
 * (core/adminapi/academy.py, правила — core/academy/panel.py; CONTRACT_ACADEMY §2–4).
 *
 *   GET    manage/academy/courses/            → { results: [курс], suggest_url, suggest, limits, counts }
 *   POST   manage/academy/courses/            { title?, teacher?, description?, url? } → курс (201, черновик в конце)
 *   PATCH  manage/academy/courses/<id>/       { любое из title, teacher, description, url, is_published } → курс
 *   DELETE manage/academy/courses/<id>/       → 204
 *   POST   manage/academy/courses/<id>/cover/ multipart file → курс
 *   POST   manage/academy/courses/order/      { ids: [все id в новом порядке] } → { results }; 409 — список устарел
 *   GET    manage/academy/settings/           → { suggest_url (сохранённое), suggest (что покажет сайт) }
 *   PATCH  manage/academy/settings/           { suggest_url } → то же, что GET
 *
 * Ответы разбираем как «чужие руки»: запись без id или с полем не того типа
 * страницу не роняет. Проверки формы повторяют серверные (те же тексты), но
 * решает сервер: здесь — подсказка до отправки, а не запрет.
 * Модуль чистый (без React и сети) — его проверяет academyAdmin.test.mjs.
 */

import {
  emailFromMailto,
  emailLink,
  nfkcAddsDots,
  parseSuggest,
  safeLinkHref,
  suggestFromUrl,
  suggestText,
  type AcademySuggest,
} from "@/lib/academy/shared";

export const COURSES_PATH = "manage/academy/courses/";
export const coursePath = (id: number): string => `${COURSES_PATH}${id}/`;
export const coverPath = (id: number): string => `${COURSES_PATH}${id}/cover/`;
export const ORDER_PATH = `${COURSES_PATH}order/`;
export const SETTINGS_PATH = "manage/academy/settings/";

/* ------------------------------------------------------------------ */
/* Типы                                                                */
/* ------------------------------------------------------------------ */

/** live — на сайте; draft — ни разу не публиковался; hidden — снят; incomplete — включён, но чего-то нет (не на сайте). */
export type CourseState = "live" | "draft" | "hidden" | "incomplete";
const STATES: readonly CourseState[] = ["live", "draft", "hidden", "incomplete"];

/** Чего не хватает для публикации — в порядке сервера. */
export type MissingField = "cover" | "title" | "teacher" | "description" | "url";
export const MISSING_ORDER: readonly MissingField[] = ["cover", "title", "teacher", "description", "url"];

export type Course = {
  id: number;
  title: string;
  teacher: string;
  description: string;
  url: string;
  /** Хост ссылки в punycode: подмену кириллицей видно сразу. */
  urlHost: string;
  cover: string | null;
  coverThumb: string | null;
  coverWidth: number;
  coverHeight: number;
  published: boolean;
  state: CourseState;
  missing: MissingField[];
  sort: number;
  /** Где курс на сайте: страница и место на ней (с 1); null — не на сайте. */
  place: { page: number; index: number } | null;
  publishedAt: string | null;
  createdAt: string;
  updatedAt: string;
};

/** Границы — те же, что проверяет сервер (limits). */
export type Limits = {
  titleMax: number;
  teacherMax: number;
  descriptionMax: number;
  urlMax: number;
  suggestUrlMax: number;
  coverMaxBytes: number;
  coverMinWidth: number;
  coverMinHeight: number;
  coverMaxSide: number;
  pageSize: number;
  maxCourses: number;
};

/** Запасные границы: сервер присылает свои, эти — на случай ответа без них. */
export const DEFAULT_LIMITS: Limits = {
  titleMax: 120,
  teacherMax: 80,
  descriptionMax: 400,
  urlMax: 1000,
  suggestUrlMax: 300,
  coverMaxBytes: 15 * 1024 * 1024,
  coverMinWidth: 480,
  coverMinHeight: 270,
  coverMaxSide: 1280,
  pageSize: 9,
  maxCourses: 500,
};

/**
 * Блок «Предложить курс»: suggestUrl — что сохранено (как ввёл сотрудник, после
 * нормализации сервером), suggest — что из этого покажет сайт (null — ничего).
 */
export type SuggestSetting = { suggestUrl: string; suggest: AcademySuggest | null };

export type CourseList = SuggestSetting & { courses: Course[]; limits: Limits };

/* ------------------------------------------------------------------ */
/* Разбор ответов                                                      */
/* ------------------------------------------------------------------ */

type Row = Record<string, unknown>;

const isRow = (v: unknown): v is Row => typeof v === "object" && v !== null && !Array.isArray(v);
const text = (v: unknown): string => (typeof v === "string" ? v.trim() : "");
const media = (v: unknown): string | null => text(v) || null;
const int = (v: unknown): number | null => (typeof v === "number" && Number.isInteger(v) ? v : null);

function parsePlace(value: unknown): Course["place"] {
  if (!isRow(value)) return null;
  const page = int(value.page);
  const index = int(value.index);
  return page !== null && index !== null && page > 0 && index > 0 ? { page, index } : null;
}

export function parseCourse(value: unknown): Course | null {
  if (!isRow(value)) return null;
  const id = int(value.id);
  if (id === null || id <= 0) return null;
  const published = value.is_published === true;
  const missing = Array.isArray(value.missing)
    ? MISSING_ORDER.filter((field) => (value.missing as unknown[]).includes(field))
    : [];
  const state = STATES.find((s) => s === value.state) ?? (published ? (missing.length ? "incomplete" : "live") : "draft");
  const cover = media(value.cover);
  return {
    id,
    title: text(value.title),
    teacher: text(value.teacher),
    description: text(value.description),
    url: text(value.url),
    urlHost: text(value.url_host),
    cover,
    coverThumb: cover ? media(value.cover_thumb) : null,
    coverWidth: Math.max(0, int(value.cover_width) ?? 0),
    coverHeight: Math.max(0, int(value.cover_height) ?? 0),
    published,
    state,
    missing,
    sort: int(value.sort) ?? 0,
    place: state === "live" ? parsePlace(value.place) : null,
    publishedAt: text(value.published_at) || null,
    createdAt: text(value.created_at),
    updatedAt: text(value.updated_at),
  };
}

/** Курсы в присланном порядке, без повторов id. */
function parseCourses(value: unknown): Course[] {
  const seen = new Set<number>();
  const out: Course[] = [];
  for (const row of Array.isArray(value) ? value : []) {
    const course = parseCourse(row);
    if (!course || seen.has(course.id)) continue;
    seen.add(course.id);
    out.push(course);
  }
  return out;
}

export function parseLimits(value: unknown): Limits {
  const row = isRow(value) ? value : {};
  const d = DEFAULT_LIMITS;
  const pick = (key: string, fallback: number): number => {
    const n = int(row[key]);
    return n !== null && n > 0 ? n : fallback;
  };
  const min = Array.isArray(row.cover_min) ? row.cover_min : [];
  const minW = int(min[0]);
  const minH = int(min[1]);
  return {
    titleMax: pick("title", d.titleMax),
    teacherMax: pick("teacher", d.teacherMax),
    descriptionMax: pick("description", d.descriptionMax),
    urlMax: pick("url", d.urlMax),
    suggestUrlMax: pick("suggest_url", d.suggestUrlMax),
    coverMaxBytes: pick("cover_max_bytes", d.coverMaxBytes),
    coverMinWidth: minW !== null && minW > 0 ? minW : d.coverMinWidth,
    coverMinHeight: minH !== null && minH > 0 ? minH : d.coverMinHeight,
    coverMaxSide: pick("cover_max_side", d.coverMaxSide),
    pageSize: pick("page_size", d.pageSize),
    maxCourses: pick("max_courses", d.maxCourses),
  };
}

/** Ответ GET списка; null — вместо панели ответил кто-то другой (страница nginx, не JSON). */
export function parseList(payload: unknown): CourseList | null {
  if (!isRow(payload) || !Array.isArray(payload.results)) return null;
  return {
    courses: parseCourses(payload.results),
    ...suggestSetting(payload),
    limits: parseLimits(payload.limits),
  };
}

/** Ответ перестановки: весь список в новом порядке; null — не разобрать. */
export function parseOrder(payload: unknown): Course[] | null {
  return isRow(payload) && Array.isArray(payload.results) ? parseCourses(payload.results) : null;
}

/**
 * Вид блока — от сервера (suggest). Сервер до F28 его не присылал: там сохранённое
 * значение всегда ссылка, её вид понятен и так.
 */
function suggestSetting(row: Row): SuggestSetting {
  const suggestUrl = typeof row.suggest_url === "string" ? row.suggest_url.trim() : "";
  return { suggestUrl, suggest: "suggest" in row ? parseSuggest(row.suggest) : suggestFromUrl(suggestUrl) };
}

/** Ответ настроек (GET и PATCH): сохранённое значение и что покажет сайт; null — не разобрать. */
export function parseSettings(payload: unknown): SuggestSetting | null {
  return isRow(payload) && typeof payload.suggest_url === "string" ? suggestSetting(payload) : null;
}

/**
 * Текст отказа. Сервер отвечает {detail, code, field?, missing?} — detail
 * показываем как есть; 413 nginx (страница, не JSON) и обрыв связи объясняем сами.
 */
export function errorText(res: { status: number; data?: unknown }, fallback: string): string {
  if (res.status === 0) return "Нет связи с сервером. Проверьте интернет и повторите.";
  const data = isRow(res.data) ? res.data : null;
  const told = data ? text(data.detail) || text(data.error) || text(data.message) : "";
  if (told) return told;
  if (res.status === 413) return "Файл больше, чем пропускает сервер. Уменьшите обложку и загрузите снова.";
  if (res.status === 429) return "Слишком много запросов подряд. Подождите минуту и повторите.";
  return `${fallback} (HTTP ${res.status})`;
}

/** Какое поле подсветить по отказу сервера; null — отказ не про поле. */
export function errorField(res: { data?: unknown }): string | null {
  return isRow(res.data) ? text(res.data.field) || null : null;
}

/* ------------------------------------------------------------------ */
/* Подписи                                                             */
/* ------------------------------------------------------------------ */

export const STATE_LABEL: Record<CourseState, string> = {
  live: "На сайте",
  draft: "Черновик",
  hidden: "Скрыт",
  incomplete: "Не на сайте",
};

export const STATE_TITLE: Record<CourseState, string> = {
  live: "Курс виден на /academy",
  draft: "Черновик: ещё не публиковался, на сайте его нет",
  hidden: "Курс снят с сайта; опубликуйте снова, когда понадобится",
  incomplete: "Курс включён, но на сайт не попадает: не хватает полей. Дозаполните или скройте его",
};

/** Винительный падеж — в фразу «добавьте: …»; тот же текст, что у отказа сервера publish_incomplete. */
const MISSING_ACC: Record<MissingField, string> = {
  cover: "обложку",
  title: "название",
  teacher: "имя преподавателя",
  description: "описание",
  url: "ссылку на курс",
};

export function publishHint(missing: readonly MissingField[]): string {
  const list = MISSING_ORDER.filter((field) => missing.includes(field));
  return list.length ? `Чтобы опубликовать, добавьте: ${list.map((field) => MISSING_ACC[field]).join(", ")}` : "";
}

/** «стр. 1 · №3» — где курс стоит на сайте. */
export const placeLabel = (place: Course["place"]): string => (place ? `стр. ${place.page} · №${place.index}` : "");

export const chars = (value: string, max: number): string => `${cleanText(value).length}/${max}`;

export const fmtMb = (bytes: number): string => `${Math.max(0.1, Math.round((bytes / (1024 * 1024)) * 10) / 10)} МБ`;

/* ------------------------------------------------------------------ */
/* Форма курса                                                         */
/* ------------------------------------------------------------------ */

export type CourseForm = { title: string; teacher: string; description: string; url: string };
export type TextField = "title" | "teacher" | "description";

export const EMPTY_FORM: CourseForm = { title: "", teacher: "", description: "", url: "" };

export const formFromCourse = (course: Course): CourseForm => ({
  title: course.title,
  teacher: course.teacher,
  description: course.description,
  url: course.url,
});

/** Невидимые знаки, которые сервер вырезает из текста (panel._INVISIBLE): управляющие, нулевой ширины, bidi. */
function invisible(ch: string): boolean {
  const code = ch.charCodeAt(0);
  return (
    code < 0x20 ||
    (code >= 0x7f && code <= 0x9f) ||
    code === 0x200b ||
    (code >= 0x202a && code <= 0x202e) ||
    (code >= 0x2066 && code <= 0x2069) ||
    code === 0xfeff
  );
}

/** Как чистит сервер: пробелы и переводы строк — один пробел, невидимые знаки — прочь, по краям — ничего. */
export const cleanText = (value: string): string =>
  Array.from(value.replace(/\s+/g, " "), (ch) => (invisible(ch) ? "" : ch))
    .join("")
    .replace(/ {2,}/g, " ")
    .trim();

const FIELD_NAME: Record<TextField, string> = { title: "Название", teacher: "Преподаватель", description: "Описание" };

const textMax = (field: TextField, limits: Limits): number =>
  field === "title" ? limits.titleMax : field === "teacher" ? limits.teacherMax : limits.descriptionMax;

/** Слишком длинное поле — тот же текст, что у сервера (too_long); null — всё влезает. */
export function lengthError(form: CourseForm, limits: Limits): { field: TextField; text: string } | null {
  for (const field of ["title", "teacher", "description"] as const) {
    const max = textMax(field, limits);
    if (cleanText(form[field]).length > max) return { field, text: `${FIELD_NAME[field]} длиннее ${max} символов` };
  }
  return null;
}

/** Тело POST: почищенные поля как есть (пустые — тоже: черновик бывает неполным). */
export const createBody = (form: CourseForm): Record<string, string> => ({
  title: cleanText(form.title),
  teacher: cleanText(form.teacher),
  description: cleanText(form.description),
  url: form.url.trim(),
});

/** Тело PATCH: только то, что поменяли (сервер на пустую правку отвечает «Нечего менять»). */
export function courseChanges(course: Course, form: CourseForm): Record<string, string> {
  const out: Record<string, string> = {};
  for (const field of ["title", "teacher", "description"] as const) {
    const value = cleanText(form[field]);
    if (value !== course[field]) out[field] = value;
  }
  const url = form.url.trim();
  if (url !== course.url) out.url = url;
  return out;
}

/**
 * Чего не хватает для публикации по форме и обложке — до отправки. Ссылку здесь
 * проверяем только на пустоту: годится ли адрес, решает сервер (его отказ покажем).
 */
export function missingForPublish(form: CourseForm, hasCover: boolean): MissingField[] {
  const filled: Record<MissingField, boolean> = {
    cover: hasCover,
    title: cleanText(form.title) !== "",
    teacher: cleanText(form.teacher) !== "",
    description: cleanText(form.description) !== "",
    url: form.url.trim() !== "",
  };
  return MISSING_ORDER.filter((field) => !filled[field]);
}

/* ------------------------------------------------------------------ */
/* Ссылки (CONTRACT_ACADEMY §4)                                        */
/* ------------------------------------------------------------------ */

export const URL_TEXT = {
  scheme: "Ссылка должна начинаться с https:// или http://",
  userinfo: "В ссылке не должно быть логина и пароля (user:pass@)",
  local: "Ссылка ведёт на внутренний адрес — нужен адрес сайта в интернете",
  invalid: "Ссылка на курс — адрес сайта вида https://example.com/kurs",
} as const;

export type UrlCheck = { ok: true; url: string; href: string; host: string } | { ok: false; error: string };

const SPECIAL_ZONES = new Set([
  "localhost",
  "local",
  "internal",
  "intranet",
  "lan",
  "home",
  "corp",
  "test",
  "invalid",
  "example",
  "arpa",
  "onion",
]);

/** Внутренний IPv4: 0/8, 10/8, 100.64/10, 127/8, 169.254/16, 172.16/12, 192.0.0/24, 192.168/16, 198.18/15, 224+. */
function privateIpv4(parts: number[]): boolean {
  const [a, b, c] = parts;
  return (
    a === 0 ||
    a === 10 ||
    a === 127 ||
    a >= 224 ||
    (a === 100 && b >= 64 && b <= 127) ||
    (a === 169 && b === 254) ||
    (a === 172 && b >= 16 && b <= 31) ||
    (a === 192 && b === 0 && c === 0) ||
    (a === 192 && b === 168) ||
    (a === 198 && (b === 18 || b === 19))
  );
}

// Адрес без схемы, к которому сервер подставит https:// (links._DOMAIN_LIKE).
const DOMAIN_LIKE = /^[^/?#:@\s]+\.[^/?#:@\s.]+(?::\d{1,5})?(?:[/?#]|$)/;
const SCHEME = /^([A-Za-z][A-Za-z0-9+.-]*):\/\//;
// Пробелы и «\»: браузер читает «\» как «/», и хост у него разошёлся бы с серверным.
const BAD_CHARS = /[\s\\]/;
// Невидимые знаки и переключатели направления (Cc, Cf, Zl, Zp): ссылка выглядела бы не тем,
// куда ведёт. Через конструктор: \p{…} в литерале требует цели сборки ES2018.
const HIDDEN = new RegExp("[\\p{Cc}\\p{Cf}\\p{Zl}\\p{Zp}]", "u");
// «Отклоняющиеся» буквы IDNA (ß ẞ ς): сервер (Python, IDNA2003) пишет straße.de как strasse.de,
// а браузер открывает xn--strae-oqa.de — такие хосты сервер отклоняет (links._IDNA_DEVIATION).
const IDNA_DEVIATION = /[ßẞς]/;
const LABEL = /^(?!-)[a-z0-9-]{1,63}$/;
const TLD = /^(?:[a-z]{2,63}|xn--[a-z0-9-]{1,59})$/;
const IPV4 = /^(\d{1,3})\.(\d{1,3})\.(\d{1,3})\.(\d{1,3})$/;

/**
 * Ссылка на курс по правилам сервера (core/academy/links.clean_url): http/https,
 * сайт в интернете, без логина в адресе; «example.com/kurs» → https://example.com/kurs.
 * Пусто — ok с пустой строкой (черновику можно). url — что сохранит сервер,
 * href — разобранный браузером адрес для «Открыть ↗», host — хост в punycode.
 */
export function checkCourseUrl(raw: string, max: number = DEFAULT_LIMITS.urlMax): UrlCheck {
  let value = raw.trim();
  if (!value) return { ok: true, url: "", href: "", host: "" };
  if (BAD_CHARS.test(value) || HIDDEN.test(value)) return { ok: false, error: URL_TEXT.invalid };
  const scheme = SCHEME.exec(value);
  if (scheme) {
    const name = scheme[1].toLowerCase();
    if (name !== "http" && name !== "https") return { ok: false, error: URL_TEXT.scheme };
    value = name + value.slice(scheme[1].length);
  } else if (DOMAIN_LIKE.test(value)) {
    value = `https://${value}`;
  } else {
    // javascript:, data:, mailto:, tg: и всё, что не похоже на адрес сайта.
    return { ok: false, error: URL_TEXT.scheme };
  }
  if (value.length > max) return { ok: false, error: `Ссылка длиннее ${max} символов` };
  // Логин в адресе ищем до разбора: «https://a@b.com» браузер примет молча.
  const authority = value.slice(value.indexOf("://") + 3).split(/[/?#]/, 1)[0];
  if (authority.includes("@")) return { ok: false, error: URL_TEXT.userinfo };
  // Точку из NFKC (U+2024 и т. п.) сервер не пускает: карточка с такой ссылкой на сайте молча пропала бы.
  if (IDNA_DEVIATION.test(authority) || nfkcAddsDots(authority)) return { ok: false, error: URL_TEXT.invalid };
  let url: URL;
  try {
    url = new URL(value);
  } catch {
    return { ok: false, error: URL_TEXT.invalid };
  }
  const host = url.hostname.toLowerCase().replace(/\.$/, "");
  if (!host || url.port === "0") return { ok: false, error: URL_TEXT.invalid };
  // Нужен адрес сайта, а не IP. Числовые формы (127.1, 0x7f.1, 2130706433) парсер уже привёл к a.b.c.d.
  if (host.startsWith("[")) return { ok: false, error: URL_TEXT.local };
  const ipv4 = IPV4.exec(host);
  if (ipv4) return { ok: false, error: privateIpv4(ipv4.slice(1).map(Number)) ? URL_TEXT.local : URL_TEXT.invalid };
  if (!host.includes(".")) return { ok: false, error: URL_TEXT.local };
  const labels = host.split(".");
  const top = labels[labels.length - 1];
  if (host.length > 253 || !labels.every((label) => LABEL.test(label) && !label.endsWith("-"))) {
    return { ok: false, error: URL_TEXT.invalid };
  }
  if (!TLD.test(top)) return { ok: false, error: URL_TEXT.invalid };
  if (SPECIAL_ZONES.has(top)) return { ok: false, error: URL_TEXT.local };
  return { ok: true, url: value, href: url.href, host };
}

/* ------------------------------------------------------------------ */
/* «Предложить курс»: ссылка, e-mail или текст                         */
/* ------------------------------------------------------------------ */

// Тексты отказов — дословно сервера (core/academy/links.py, MSG_SUGGEST_*): подсказка
// до сохранения и ответ после него говорят одно и то же.
export const SUGGEST_TEXT = {
  hidden:
    "Уберите невидимые символы: управляющие, нулевой ширины (в том числе внутри составных эмодзи) или смены направления текста",
  host: "Не разобрать адрес сайта в ссылке — проверьте её, например https://example.com/forma",
} as const;
export const suggestTooLong = (max: number, n: number): string => `Не длиннее ${max} символов — сейчас ${n}`;
export const suggestDanger = (scheme: string): string =>
  `Ссылки «${scheme}:» на сайт не ставим — нужна ссылка https://…, e-mail, @имя или обычный текст`;
export const suggestScheme = (scheme: string): string =>
  `Ссылки «${scheme}:» не подходят — нужна https:// или http://, e-mail или @имя в Telegram`;

export type SuggestCheck = { ok: true; suggest: AcademySuggest | null } | { ok: false; error: string };

// Только с @: без неё «Academy» или «Soon» — обычный текст, а не канал в Telegram.
const TG_AT = /^@([A-Za-z][A-Za-z0-9_]{3,31})$/;
const TG_HOST = /^(?:https?:\/\/)?(?:www\.)?(?:t\.me|telegram\.me|telegram\.dog)(?=[/?#]|$)(.*)$/i;
const TG_TAIL = /^\/[A-Za-z0-9_+-]+(?:\/[A-Za-z0-9_-]+)*\/?(?:\?[A-Za-z0-9_=&-]*)?$/;
// Схемы, которые браузер исполняет или открывает как документ (file: — файл с компьютера
// посетителя): их нет даже в тексте.
const DANGER = /^(javascript|vbscript|data|file):/i;
const HTTP_LINK = /^https?:\/\//i;
const MAILTO = /^mailto:/i;
// Адрес без схемы становится кнопкой, только если похож на сайт, а не на прозу без пробела
// («Скоро.Ждите», «v1.2»): домен верхнего уровня — латиницей или из настоящих кириллических.
const SCHEMELESS_HOST = /^[^/?#:]+/;
const ASCII_TOP = /^[A-Za-z]{2,24}$/;
const CYRILLIC_TOPS = new Set(["рф", "бел", "укр", "срб", "қаз", "рус", "мкд", "мон", "онлайн", "сайт"]);
// Кириллица с латиницей в одной метке — подмена похожих букв (русская «а» в латинском имени).
const CYRILLIC = /[\u0400-\u052f\u1c80-\u1c8f\ua640-\ua69f]/;
const LATIN = /[A-Za-z\u00c0-\u00d6\u00d8-\u00f6\u00f8-\u024f]/;
// Невидимое и переворачивающее строку, кроме перевода строки; Cs — одинокий суррогат.
const SUGGEST_HIDDEN = new RegExp("[\\p{Cc}\\p{Cf}\\p{Zl}\\p{Zp}\\p{Cs}]", "u");

type LinkCheck = { ok: true; value: string; href: string } | { ok: false; error: string };

/**
 * http(s)://-ссылка кнопки одним словом (links._open_link): любой хост — и localhost, и IP, —
 * но тот, что откроет браузер. value — что сохранит сервер (схема строчными), href — для
 * «Проверить». Хост проверяет safeLinkHref — та же функция, что у страницы: подсказка не
 * обещает кнопку, которую сайт не покажет. Здесь — только отказы со своим текстом.
 */
function openLink(raw: string): LinkCheck {
  const colon = raw.indexOf(":");
  const value = raw.slice(0, colon).toLowerCase() + raw.slice(colon);
  // С «\» сервер отвечает «адрес не разобрать», даже если дальше в нём есть @.
  if (!value.includes("\\") && value.slice(colon + 3).split(/[/?#]/, 1)[0].includes("@")) {
    return { ok: false, error: URL_TEXT.userinfo };
  }
  const href = safeLinkHref(value);
  return href ? { ok: true, value, href } : { ok: false, error: SUGGEST_TEXT.host };
}

/** Одно слово — адрес сайта без схемы (links._schemeless): example.com, www.example.com/path, курсы.рф. */
function schemeless(value: string): boolean {
  if (value.includes("@") || !DOMAIN_LIKE.test(value)) return false;
  const labels = (SCHEMELESS_HOST.exec(value)?.[0] ?? "").split(".");
  const top = labels[labels.length - 1];
  if (!ASCII_TOP.test(top) && !CYRILLIC_TOPS.has(top.toLowerCase())) return false;
  return !labels.some((label) => CYRILLIC.test(label) && LATIN.test(label));
}

/**
 * Что сайт покажет под приглашением — по правилам сервера (core/academy/links._classify) и в
 * том же порядке: javascript:/vbscript:/data:/file: — отказ; @имя и t.me/… → кнопка на
 * https://t.me/…; mailto: с адресом или адрес почты → кнопка-письмо; http(s)://… одним словом →
 * кнопка на ссылку (а со словами или строками после неё — текст); адрес без схемы
 * (example.com/form, курсы.рф) → https://, а не откроется — текст; чужая схема одним словом
 * (tg://, ftp://) — отказ; всё остальное — текст без кнопки, и с двоеточием тоже (tel:+996…).
 * Только подсказка до сохранения: решает сервер, его ответ панель покажет после.
 */
export function classifySuggest(raw: string, max: number = DEFAULT_LIMITS.suggestUrlMax): SuggestCheck {
  const value = raw.replace(/\r\n?/g, "\n").replace(/\t/g, " ").trim();
  if (!value) return { ok: true, suggest: null };
  // Длина — в символах, как len() в Python, а не в половинках UTF-16.
  const length = Array.from(value).length;
  if (length > max) return { ok: false, error: suggestTooLong(max, length) };
  const flat = value.replace(/\n/g, "");
  if (SUGGEST_HIDDEN.test(flat)) return { ok: false, error: SUGGEST_TEXT.hidden };
  // Переводы строк браузер из ссылки выбрасывает: «java⏎script:» — тоже она.
  const danger = DANGER.exec(flat);
  if (danger) return { ok: false, error: suggestDanger(danger[1].toLowerCase()) };
  const result = classifyValue(value);
  // Ещё раз — по тому, что сохранит сервер (links.parse_suggest): у текста срезаны пробелы
  // у переносов, и «java ⏎ script:» склеился бы в опасное начало — сервер такое не примет.
  const glued = result.ok && result.suggest ? DANGER.exec(result.suggest.text.replace(/\n/g, "")) : null;
  if (glued) return { ok: false, error: suggestDanger(glued[1].toLowerCase()) };
  if (result.ok && result.suggest && Array.from(result.suggest.text).length > max) {
    // Длиннее входа становятся только формы Telegram (t.me/… → https://t.me/…).
    return { ok: false, error: suggestTooLong(max, Array.from(result.suggest.text).length) };
  }
  return result;
}

function classifyValue(value: string): SuggestCheck {
  const asUrl = (text: string, href: string): SuggestCheck => ({ ok: true, suggest: { kind: "url", text, href } });
  const asText = (): SuggestCheck => ({ ok: true, suggest: { kind: "text", text: suggestText(value), href: null } });
  const oneWord = !/\s/.test(value);
  const name = TG_AT.exec(value);
  if (name) return asUrl(`https://t.me/${name[1]}`, `https://t.me/${name[1]}`);
  const tg = TG_HOST.exec(value);
  if (tg && TG_TAIL.test(tg[1])) return asUrl(`https://t.me${tg[1]}`, `https://t.me${tg[1]}`);
  if (MAILTO.test(value)) {
    // Не адрес после mailto: — обычный текст: годный адрес в нём сайт всё равно сделает ссылкой.
    const email = emailFromMailto(value);
    return email ? { ok: true, suggest: { kind: "email", text: email.address, href: email.href } } : asText();
  }
  if (oneWord && value.includes("@")) {
    const email = emailLink(value);
    if (email) return { ok: true, suggest: { kind: "email", text: email.address, href: email.href } };
  }
  if (HTTP_LINK.test(value)) {
    // Ссылка, а за ней слова или строки («https://forms.gle/… ⏎ Заполните анкету»), — это текст:
    // ссылку в нём сайт сделает ссылкой, если она проходит те же правила.
    if (!oneWord) return asText();
    const link = openLink(value);
    return link.ok ? asUrl(link.value, link.href) : link;
  }
  if (oneWord && schemeless(value)) {
    // Похоже на адрес, но ссылкой не откроется (порт 99999) — пусть остаётся текстом.
    const link = openLink(`https://${value}`);
    return link.ok ? asUrl(link.value, link.href) : asText();
  }
  const scheme = SCHEME.exec(value);
  if (oneWord && scheme) {
    // tg://, ftp://, whatsapp://: кнопка с такой ссылкой у посетителя не откроется.
    return { ok: false, error: suggestScheme(scheme[1].toLowerCase()) };
  }
  // Остальное — текст, и с двоеточием тоже: «Contact:a@b.kg», «tel:+996…», «https:example.com».
  return asText();
}

/**
 * Хост кнопки (сайт ссылки или домен почты) в punycode — только если в нём есть
 * не-ASCII: посетитель адреса не видит, и подмену кириллицей (русская «е» в «esai.kg»)
 * должен заметить сотрудник — как у ссылок курсов. null — показывать нечего.
 */
export function suggestPunycodeHost(suggest: AcademySuggest | null): string | null {
  if (!suggest || suggest.kind === "text") return null;
  let host: string;
  try {
    host = suggest.kind === "url" ? new URL(suggest.href).hostname : suggest.href.slice(suggest.href.lastIndexOf("@") + 1);
  } catch {
    return null;
  }
  return host.split(".").some((label) => label.startsWith("xn--")) ? host : null;
}

/* ------------------------------------------------------------------ */
/* Обложка                                                             */
/* ------------------------------------------------------------------ */

/** Что можно выбрать — то же, что принимает сервер. */
export const COVER_ACCEPT =
  "image/jpeg,image/png,image/webp,image/heic,image/heif,image/gif,image/bmp,.jpg,.jpeg,.jfif,.png,.webp,.heic,.heif,.gif,.bmp";
const COVER_EXT = /\.(jpe?g|jfif|png|webp|heic|heif|gif|bmp)$/i;

/** Файл, который сервер точно отклонит, — до отправки; null — можно слать. */
export function coverFileError(file: { name: string; size: number; type: string }, limits: Limits): string | null {
  const imageType = /^image\/(jpeg|pjpeg|png|webp|heic|heif|gif|bmp|x-ms-bmp)$/i.test(file.type);
  if (!imageType && !COVER_EXT.test(file.name)) return "Обложка — картинка JPG, PNG, WebP или HEIC";
  if (file.size > limits.coverMaxBytes) {
    return `Обложка больше ${Math.floor(limits.coverMaxBytes / (1024 * 1024))} МБ — уменьшите её`;
  }
  return null;
}

/** Меньше минимума сервер не примет — не шлём. Размер неизвестен (HEIC браузер не открыл) — решит сервер. */
export function coverSizeError(width: number, height: number, limits: Limits): string | null {
  if (!width || !height) return null;
  if (width >= limits.coverMinWidth && height >= limits.coverMinHeight) return null;
  return `Обложка слишком маленькая: нужно не меньше ${limits.coverMinWidth}×${limits.coverMinHeight}, лучше 1280×720 (16:9)`;
}

/** Предупреждение, не запрет: карточка режет обложку под 16:9 (object-cover). */
export function aspectWarning(width: number, height: number): string | null {
  if (!width || !height) return null;
  const ratio = width / height;
  if (ratio < 1.6 || ratio > 1.9) return `Пропорции ${width}×${height} — не 16:9: на карточке края обрежутся`;
  if (width < 1280 || height < 720) return `Обложка ${width}×${height} — меньше 1280×720: на больших экранах будет мягкой`;
  return null;
}

/* ------------------------------------------------------------------ */
/* Список: фильтры и порядок                                           */
/* ------------------------------------------------------------------ */

export type Filter = "all" | "live" | "draft" | "hidden";

/** «Скрытые» — всё, что включали, но сейчас не на сайте (и снятые, и недозаполненные). */
export function matchesFilter(course: Course, filter: Filter): boolean {
  if (filter === "all") return true;
  if (filter === "hidden") return course.state === "hidden" || course.state === "incomplete";
  return course.state === filter;
}

export function filterCounts(courses: readonly Course[]): Record<Filter, number> {
  const counts: Record<Filter, number> = { all: courses.length, live: 0, draft: 0, hidden: 0 };
  for (const course of courses) {
    for (const filter of ["live", "draft", "hidden"] as const) if (matchesFilter(course, filter)) counts[filter] += 1;
  }
  return counts;
}

/** Новый порядок id: элемент с места from — на место to (за краем — к краю). */
export function reorderIds(ids: readonly number[], from: number, to: number): number[] {
  const out = [...ids];
  if (from < 0 || from >= out.length) return out;
  const target = Math.min(Math.max(to, 0), out.length - 1);
  const [moved] = out.splice(from, 1);
  out.splice(target, 0, moved);
  return out;
}

/** Список в порядке ids — для мгновенного показа, пока сервер переставляет. */
export function orderBy(courses: readonly Course[], ids: readonly number[]): Course[] {
  const byId = new Map(courses.map((course) => [course.id, course]));
  const out = ids.map((id) => byId.get(id)).filter((course): course is Course => course !== undefined);
  return out.length === courses.length ? out : [...courses];
}

/** Курс с сервера встаёт на своё место; новый — в конец (сервер ставит новые последними). */
export function replaceCourse(courses: readonly Course[], saved: Course): Course[] {
  return courses.some((course) => course.id === saved.id)
    ? courses.map((course) => (course.id === saved.id ? saved : course))
    : [...courses, saved];
}

/** Место на сайте пересчитывает сервер; после публикации или скрытия перечитываем список, чтобы «стр. · №» не врали. */
export const placesChanged = (before: Course, after: Course): boolean => (before.state === "live") !== (after.state === "live");
