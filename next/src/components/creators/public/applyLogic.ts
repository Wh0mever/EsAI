/**
 * EsAI Creators: заявка на участие — значения формы, проверка и черновик.
 *
 * Проверка повторяет серверную (core/creators/program.py, _clean_application):
 * человек видит ошибку сразу, а не после запроса. Решает всё равно сервер —
 * его ответ `validation` с ошибками по полям форма тоже показывает.
 *
 * Здесь нет ни текстов, ни React: только данные, поэтому файл проверяется
 * обычным node-тестом (applyLogic.test.mjs).
 */
import { isHttpUrl, splitLinks } from "@/lib/creators/format";
import type { Application, ApplicationBody, ApplicationStatus, Program } from "@/lib/creators/types";

/** Пределы полей — как в модели и в _clean_application. */
export const LIMITS = {
  name: 120,
  telegram: 64,
  country: 64,
  url: 300,
  text: 2000,
  otherLinks: 5,
  samples: 10,
  followers: 2_000_000_000,
} as const;

/** Поля формы; все — строки, как их вводит человек. */
export type FormValues = {
  name: string;
  telegram: string;
  country: string;
  instagram_url: string;
  tiktok_url: string;
  youtube_url: string;
  /** Текст поля «по одной ссылке в строке». */
  other_links: string;
  followers: string;
  occupation: string;
  motivation: string;
  /** Текст поля «по одной ссылке в строке». */
  samples: string;
};
export type FieldName = keyof FormValues;

/** Порядок полей на экране: по нему ищем первое поле с ошибкой. */
export const FIELD_ORDER: FieldName[] = [
  "name",
  "telegram",
  "country",
  "instagram_url",
  "tiktok_url",
  "youtube_url",
  "other_links",
  "followers",
  "occupation",
  "motivation",
  "samples",
];

/** Что не так с полем; текст по виду ошибки выбирает форма. */
export type FieldIssue =
  | { kind: "required" }
  | { kind: "too_long"; max: number }
  | { kind: "url" }
  | { kind: "url_too_long"; max: number }
  | { kind: "too_many_links"; max: number }
  | { kind: "followers" };

export type Issues = Partial<Record<FieldName, FieldIssue>>;

export type Validation = {
  issues: Issues;
  /** Нет ни одной ссылки на соцсеть (код сервера links_required). */
  linksMissing: boolean;
  /** Тело запроса без языка; null — форму отправлять нельзя. */
  body: Omit<ApplicationBody, "lang"> | null;
};

export function emptyValues(): FormValues {
  return {
    name: "",
    telegram: "",
    country: "",
    instagram_url: "",
    tiktok_url: "",
    youtube_url: "",
    other_links: "",
    followers: "",
    occupation: "",
    motivation: "",
    samples: "",
  };
}

const text = (v: unknown): string => (typeof v === "string" ? v : "");
const lines = (v: unknown): string =>
  Array.isArray(v) ? v.filter((item): item is string => typeof item === "string").join("\n") : "";

/** Прошлая заявка → значения формы («Подать заявку снова» открывает её заполненной). */
export function valuesFromApplication(application: Application | null | undefined): FormValues {
  if (!application) return emptyValues();
  const followers = Number(application.followers);
  return {
    name: text(application.name),
    telegram: text(application.telegram),
    country: text(application.country),
    instagram_url: text(application.instagram_url),
    tiktok_url: text(application.tiktok_url),
    youtube_url: text(application.youtube_url),
    other_links: lines(application.other_links),
    followers: Number.isInteger(followers) && followers >= 0 ? String(followers) : "",
    occupation: text(application.occupation),
    motivation: text(application.motivation),
    samples: lines(application.samples),
  };
}

/**
 * Ссылка без схемы («instagram.com/name») → с https://. Сервер принимает
 * только http(s)://, а люди копируют адрес из приложения без него. Всё, что
 * на адрес сайта не похоже («@name»), не трогаем — пусть поле покажет ошибку.
 */
export function normalizeUrl(raw: string | null | undefined): string {
  const value = String(raw ?? "").trim();
  if (!value || /^https?:\/\//i.test(value)) return value;
  if (/^[a-z0-9-]+(\.[a-z0-9-]+)*\.[a-z][a-z0-9-]+([/?#]\S*)?$/i.test(value)) return `https://${value}`;
  return value;
}

/** Значения со ссылками, приведёнными к https://; остальное — как есть. */
export function normalizeValues(values: FormValues): FormValues {
  const list = (value: string) => splitLinks(value).map(normalizeUrl).join("\n");
  return {
    ...values,
    instagram_url: normalizeUrl(values.instagram_url),
    tiktok_url: normalizeUrl(values.tiktok_url),
    youtube_url: normalizeUrl(values.youtube_url),
    other_links: list(values.other_links),
    samples: list(values.samples),
  };
}

function urlIssue(url: string): FieldIssue | null {
  if (url.length > LIMITS.url) return { kind: "url_too_long", max: LIMITS.url };
  if (!isHttpUrl(url)) return { kind: "url" };
  return null;
}

/** Число подписчиков: целое от 0; пробелы-разделители («10 000») допускаем. */
export function parseFollowers(raw: string): number | null {
  const digits = String(raw ?? "").replace(/[\s ]/g, "");
  if (!/^\d{1,10}$/.test(digits)) return null;
  const value = Number(digits);
  return value <= LIMITS.followers ? value : null;
}

/** Проверить форму. Ошибки — все сразу, по полям. */
export function validateApplication(values: FormValues): Validation {
  const issues: Issues = {};

  const required = (name: "name" | "telegram" | "country" | "occupation" | "motivation", max: number): string => {
    const value = values[name].trim();
    if (!value) issues[name] = { kind: "required" };
    else if (value.length > max) issues[name] = { kind: "too_long", max };
    return value;
  };
  const singleUrl = (name: "instagram_url" | "tiktok_url" | "youtube_url"): string => {
    const value = values[name].trim();
    const issue = value ? urlIssue(value) : null;
    if (issue) issues[name] = issue;
    return value;
  };
  const urlList = (name: "other_links" | "samples", max: number): string[] => {
    const urls = splitLinks(values[name]);
    const bad = urls.map(urlIssue).find(Boolean);
    if (bad) issues[name] = bad;
    else if (urls.length > max) issues[name] = { kind: "too_many_links", max };
    return urls;
  };

  const name = required("name", LIMITS.name);
  const telegram = required("telegram", LIMITS.telegram);
  const country = required("country", LIMITS.country);
  const followers = parseFollowers(values.followers);
  if (followers === null) issues.followers = { kind: "followers" };
  const instagram_url = singleUrl("instagram_url");
  const tiktok_url = singleUrl("tiktok_url");
  const youtube_url = singleUrl("youtube_url");
  const other_links = urlList("other_links", LIMITS.otherLinks);
  const occupation = required("occupation", LIMITS.text);
  const motivation = required("motivation", LIMITS.text);
  const samples = urlList("samples", LIMITS.samples);

  // Неверно написанная ссылка — это ошибка поля, а не «ссылок нет».
  const linksMissing = !(instagram_url || tiktok_url || youtube_url || other_links.length);

  const valid = Object.keys(issues).length === 0 && !linksMissing && followers !== null;
  return {
    issues,
    linksMissing,
    body: valid
      ? {
          name,
          telegram,
          country,
          instagram_url,
          tiktok_url,
          youtube_url,
          other_links,
          followers,
          occupation,
          motivation,
          samples,
        }
      : null,
  };
}

/** Первое по порядку поле из набора — туда ставим курсор после неудачной отправки. */
export function firstField(names: Iterable<string>): FieldName | null {
  const set = new Set(names);
  return FIELD_ORDER.find((name) => set.has(name)) ?? null;
}

/* ------------------------------------------------------------------ */
/* Состояние посетителя                                                */
/* ------------------------------------------------------------------ */

/**
 * Кем человек приходится программе — от этого зависит, что стоит на месте
 * главной кнопки: вход, форма, карточка статуса или ссылка в кабинет.
 */
export type Stage =
  | "guest"
  | "can_apply"
  | "pending"
  | "rejected"
  | "apply_blocked"
  | "creator"
  | "creator_blocked";

export function stageOf(me: Program["me"] | null | undefined): Stage {
  if (!me || !me.is_authenticated) return "guest";
  if (me.is_creator) return me.creator_status === "blocked" ? "creator_blocked" : "creator";
  const status: ApplicationStatus | null = me.application_status;
  if (status === "new") return "pending";
  if (status === "rejected") return "rejected";
  if (status === "blocked") return "apply_blocked";
  // Заявки нет (или одобренная осталась без креатора после слияния аккаунтов).
  return "can_apply";
}

/** Форму можно открыть: заявки нет или прошлую отклонили. */
export function canApply(stage: Stage): boolean {
  return stage === "can_apply" || stage === "rejected";
}

/* ------------------------------------------------------------------ */
/* Черновик                                                            */
/* ------------------------------------------------------------------ */

/**
 * Черновик живёт в sessionStorage вкладки: форма длинная, и терять её из-за
 * случайной перезагрузки или истёкшей сессии (уход на вход и обратно) обидно.
 * Хранилище может быть закрыто (приватный режим, webview) — тогда черновика
 * просто нет.
 */
const DRAFT_KEY = "esai_creators_apply_draft";

export function loadDraft(): FormValues | null {
  try {
    if (typeof window === "undefined") return null;
    const raw = window.sessionStorage.getItem(DRAFT_KEY);
    if (!raw) return null;
    const parsed: unknown = JSON.parse(raw);
    if (typeof parsed !== "object" || parsed === null) return null;
    const source = parsed as Record<string, unknown>;
    const values = emptyValues();
    let filled = false;
    for (const name of FIELD_ORDER) {
      const value = source[name];
      if (typeof value !== "string") continue;
      values[name] = value;
      if (value.trim()) filled = true;
    }
    return filled ? values : null;
  } catch {
    return null;
  }
}

export function saveDraft(values: FormValues): void {
  try {
    window.sessionStorage.setItem(DRAFT_KEY, JSON.stringify(values));
  } catch {}
}

export function clearDraft(): void {
  try {
    window.sessionStorage.removeItem(DRAFT_KEY);
  } catch {}
}
